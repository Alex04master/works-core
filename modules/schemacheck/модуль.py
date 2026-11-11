# -*- coding: utf-8 -*-
"""Модуль «Проверка схемы» — разбор .vlx/.robxsim при сдаче.

1. При каждой сдаче: если в файлах есть .vlx или .robxsim, файл
   разбирается (компоненты, провода, скетч). Результат пишется в
   версию сдачи (ver["контроль"]["схема"]).
2. Если у задания задан эталон (настройки["схема_эталон"]), каждая
   позиция отмечается ✅/❌/⚠ (совпадение / не хватает / лишние).
3. Преподаватель видит отчёт на странице сдачи (JS-инъекция) и может
   задать эталон на странице задания.
"""
import html
import io
import json
import os
import time
import urllib.parse

TITLE = "Проверка схемы"


def _parse_schema(raw):
    """Разобрать .vlx или .robxsim. Возвращает dict или None."""
    try:
        d = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    if d.get("format") == "velxio-project":
        comps = d.get("components") or []
        wires = d.get("wires") or []
        sketches = []
        for _gid, files in (d.get("fileGroups") or {}).items():
            for f in files:
                sketches.append(f.get("name", ""))
        fmt = "velxio"
    elif "circuit" in d:
        circ = d.get("circuit") or {}
        comps = circ.get("components") or []
        wires = circ.get("wires") or []
        sketches = []
        code = d.get("code")
        if code:
            sketches.append("sketch.ino (%d байт)" % len(code))
        fmt = "robxsim"
    else:
        return None
    counts = {}
    for c in comps:
        mid = (c.get("metadataId") or c.get("type") or "?").strip()
        counts[mid] = counts.get(mid, 0) + 1
    return {"компоненты": counts, "провода": len(wires),
            "скетчи": sketches, "формат": fmt,
            "компонентов_всего": len(comps)}


def _check_schema(ver, task, store_root):
    """Найти .vlx/.robxsim в файлах версии, разобрать, записать отчёт."""
    files = ver.get("files") or {}
    subs_dir = os.path.join(store_root, "сдачи")
    schema = None
    for _key, meta in files.items():
        if not isinstance(meta, dict):
            continue
        fn = meta.get("файл", "") or meta.get("file", "")
        if not fn or not fn.lower().endswith((".vlx", ".robxsim")):
            continue
        fp = os.path.join(subs_dir, fn)
        if not os.path.isfile(fp):
            continue
        try:
            raw = io.open(fp, "rb").read()
        except OSError:
            continue
        schema = _parse_schema(raw)
        if schema:
            schema["файл"] = meta.get("имя", fn)
            break  # первый найденный файл схемы
    if not schema:
        return
    # эталон из настроек задания
    etalon = ((task.get("настройки") or {}).get("схема_эталон") or {})
    checks = []
    if etalon and isinstance(etalon, dict):
        for comp, want in etalon.items():
            got = schema["компоненты"].get(comp, 0)
            if got >= want:
                checks.append({"компонент": comp, "нужно": want,
                               "есть": got, "статус": "ok"})
            else:
                checks.append({"компонент": comp, "нужно": want,
                               "есть": got, "статус": "мало"})
        for comp, got in schema["компоненты"].items():
            if comp not in etalon:
                checks.append({"компонент": comp, "нужно": 0,
                               "есть": got, "статус": "доп"})
    ctl = ver.get("контроль") or {}
    ctl["схема"] = {"разбор": schema, "эталон": checks or None,
                    "когда": time.time()}
    ver["контроль"] = ctl


def register(ctx):
    def _on_submit(task=None, student=None, sub=None, version=None, **kw):
        try:
            if task and sub and version:
                _check_schema(version, task, ctx._core.store.root)
                ctx._core.store.save()
        except Exception as ex:
            ctx.log("проверка схемы: сбой (%s)" % ex)

    ctx.on("submit.after", _on_submit)

    # ── Эталон: форма на странице задания (преподаватель) ───────────
    @ctx.add_route("GET", "/staff/schema_etalon/", access="staff")
    def etalon_form(handler, params):
        try:
            return _etalon_body(handler, params)
        except Exception as ex:
            import traceback
            traceback.print_exc()
            handler._send_text(500, "etalon error: " + str(ex))
            return handler._SENT

    def _etalon_body(handler, params):
        tid = (params.get("_parts") or [""])[0]
        task = ctx.get_task(tid)
        if not task:
            handler._send_text(404, "нет задания")
            return handler._SENT
        et = (task.get("настройки") or {}).get("схема_эталон") or {}
        rows = ""
        for comp, want in sorted(et.items()):
            rows += (f'<tr><td>{comp}</td><td>{want}</td><td>'
                     f'<form method="post" action="/staff/schema_etalon/{tid}" style="display:inline">'
                     f'<input type="hidden" name="remove" value="{comp}">'
                     f'<button class="btn-sm btn-danger">Убрать</button></form></td></tr>')
        body = (f'<p><a href="/staff/task/{tid}">← Назад к заданию</a></p>'
                f'<div class="staff-card"><h2>🔍 Эталон схемы</h2>'
                '<p class="hint">Укажите минимальное количество компонентов, которые должны быть в схеме студента. При сдаче система автоматически проверит наличие и покажет преподавателю.</p>'
                f'<table class="staff-table" style="max-width:400px">'
                '<tr><th>Компонент</th><th>Мин.</th><th></th></tr>'
                f'{rows}</table>'
                f'<form method="post" action="/staff/schema_etalon/{tid}" style="margin-top:10px;display:flex;gap:8px;align-items:center">'
                f'<input type="text" name="component" placeholder="led" required style="width:140px">'
                f'<input type="number" name="count" value="1" min="1" style="width:60px">'
                f'<button class="btn-sm">＋ Добавить</button></form>'
                '<p class="hint" style="margin-top:8px">Имена компонентов: led, resistor, buzzer, potentiometer, lcd1602, dht11, hc-sr04, servo, arduino-uno и т.д. — как в симуляторе.</p></div>'
                )
        title = task.get("title", "?")
        return ctx.render_page("🔍 Эталон схемы — " + title, body, staff=True)

    @ctx.add_route("POST", "/staff/schema_etalon/", access="staff")
    def etalon_save(handler, params):
        tid = (params.get("_parts") or [""])[0]
        task = ctx.get_task(tid)
        if not task:
            handler._redirect("/staff")
            return handler._SENT
        data = handler._parse_post()
        settings = task.get("настройки") or {}
        et = settings.get("схема_эталон") or {}
        if data.get("remove"):
            et.pop(data["remove"], None)
        elif data.get("component"):
            comp = data["component"].strip().lower()
            try:
                cnt = max(1, int(data.get("count", 1)))
            except (TypeError, ValueError):
                cnt = 1
            et[comp] = cnt
        settings["схема_эталон"] = et
        task["настройки"] = settings
        ctx._core.store.save()
        ctx.audit("эталон схемы обновлён",
                  {"задание": tid, "эталон": et}, handler=handler)
        handler._redirect("/staff/schema_etalon/%s" % tid)
        return handler._SENT

    # ── Кнопка «Эталон схемы» на странице задания (преподаватель) ────
    def _task_link(task=None, **kw):
        tid = (task or {}).get("id", "")
        if not tid:
            return ""
        return ('<a class="btn btn-secondary" '
                'href="/staff/schema_etalon/%s" '
                'title="Настроить автопроверку схемы">🔍 Эталон схемы</a>'
                % tid)

    ctx.on("staff.task_actions", _task_link)

    # ── Отчёт на странице сдачи (JS-инъекция) ─────────────────────────
    def _head(course=None, lesson=None, **kw):
        return _INJECT_JS

    ctx.on("page.head", _head)

    # ── Данные для страницы сдачи ─────────────────────────────────────
    @ctx.add_route("GET", "/schema/info/", access="staff")
    def schema_info(handler, params):
        try:
            return _info_body(handler, params)
        except Exception as ex:
            import traceback
            tb = traceback.format_exc()
            handler._send_json(500, {"error": "schema info: " + str(ex),
                                     "tb": tb[-1500:]})
            return handler._SENT

    def _info_body(handler, params):
        key = urllib.parse.unquote((params.get("_parts") or [""])[0])
        if "__" not in key:
            return handler._send_json(200, {"есть": False})
        tid, sid = key.split("__", 1)
        sub = ctx._core.sub(tid, sid)
        ver = (sub or {}).get("versions", [{}])[-1] if sub else {}
        ctl = ver.get("контроль") or {}
        sch = ctl.get("схема")
        if not sch:
            return handler._send_json(200, {"есть": False})
        handler._send_json(200, {"есть": True, "схема": sch})
        return handler._SENT

    ctx.log("загружен: проверка схемы (авторазбор .vlx/.robxsim)")


_INJECT_JS = """<script>
(function(){
  var key=decodeURIComponent(location.pathname.match(
    /\\/staff\\/(?:sub|mysub)\\/(.+)/)?.[1]||'').split('/')[0];
  if(!key)return;
  fetch('/schema/info/'+encodeURIComponent(key))
    .then(function(r){return r.json();})
    .then(function(j){
      if(!j.есть)return;
      var sch=j.схема,razb=sch.разбор||{},et=sch.эталон;
      var h='<div class="staff-card" style="margin:10px 0">'
        +'<h3>🔍 Схема ('+(razb.формат||'?')+')</h3>';
      var comps=razb.компоненты||{};
      if(Object.keys(comps).length){
        h+='<table class="staff-table" style="max-width:400px">'
          +'<tr><th>Компонент</th><th>Кол-во</th>';
        if(et)h+='<th>Эталон</th><th></th>';
        h+='</tr>';
        var allc={};
        Object.keys(comps).forEach(function(k){allc[k]=1;});
        if(et)Object.keys(et).forEach(function(k){allc[k]=1;});
        Object.keys(allc).sort().forEach(function(k){
          var got=comps[k]||0;
          h+='<tr><td>'+k+'</td><td>'+(got||'—')+'</td>';
          if(et){
            var want=et[k]||0;
            var icon=got>=want?'✅':(got>0?'⚠':'❌');
            h+='<td>'+want+'</td><td>'+icon+'</td>';
          }
          h+='</tr>';});
        h+='</table>';
      } else {
        h+='<p class="hint">Компоненты не найдены в файле схемы.</p>';
      }
      h+='<p class="hint">Проводов: '+(razb.провода||0)
        +' · скетч: '+((razb.скетчи||[]).join(', ')||'—')+'</p>';
      // вставить после заголовка сдачи
      var el=document.querySelector('.sub-status,.task-desc,.staff-card');
      if(el)el.insertAdjacentHTML('beforebegin',h);
      else document.body.insertAdjacentHTML('afterbegin',h);
    });
})();
</script>"""
