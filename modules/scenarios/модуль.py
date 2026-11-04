# -*- coding: utf-8 -*-
"""Модуль «Сценарии УП» — интеграция занятий по сценариям (ОПС).

Преподаватель открывает /staff/scenarios, выбирает комплект (папку
со сценарием из настроек) и курс. Модуль создаёт занятие:
  • материалы комплекта (раздатка, планы сооружений, обозначения)
    копируются студентам курса — эталоны (etalon, notes, dev) и план
    преподавателя НЕ копируются;
  • по каждой карточке сценария создаётся задание с описанием
    (ситуация, задания, критерии, ловушки) и формой отчёта.
Отчёт по заданию бригада сдаёт один на всех (см. модуль бригад).
"""
import io
import os
import re
import shutil
import urllib.parse

# файлы комплекта, которые студентам не выдаются
STUDENT_SKIP_PREFIX = ("03_", "ИНСТРУКЦИЯ")
# эталонные устройства и подсказки-ответы вырезаются из копии plans.js
STRIP_RE = re.compile(r"\b(dev|notes)\s*:\s*\[.*?\]", re.S)


def _e(v):
    """Экранирование HTML (как в других модулях)."""
    import html as _html
    return _html.escape(str(v) if v is not None else "", quote=True)


def _clean(s):
    """HTML из данных сценария -> текст/Markdown (экранируется ядром)."""
    s = (s or "")
    s = s.replace("<b>", "**").replace("</b>", "**")
    s = s.replace("<br>", "\n").replace("<br/>", "\n").replace("&nbsp;", " ")
    s = re.sub(r"<[^>]+>", "", s)
    return s.strip()


def _clean_title(s):
    """Заголовок: без тегов и разметки, в одну строку."""
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = s.replace("**", " ").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", s).strip()


def _card_desc(card, ev):
    """Описание задания из карточки сценария."""
    stands_map = (ev or {}).get("stands") or {}
    out = []
    head = []
    if card.get("role"):
        head.append("**Роль:** %s" % _clean(card.get("role")))
    meta = [str(x) for x in (card.get("time", ""), card.get("team", "")) if x]
    if meta:
        head.append("**Время · состав:** %s" % " · ".join(_clean(x) for x in meta))
    if head:
        out.append("  \n".join(head))
    out.append("**Уровень:** %s" % (card.get("lvl") or "—"))
    if card.get("obj"):
        out.append("**Объект:** %s" % _clean(card.get("obj")))
    if card.get("story"):
        out.append("### Ситуация\n%s" % _clean(card.get("story")))
    dt = card.get("data_table") or []
    if dt:
        rows = ["- " + " — ".join(_clean(str(c)) for c in row) for row in dt]
        out.append("### Исходные данные\n" + "\n".join(rows))
    st_codes = card.get("stands") or []
    if st_codes:
        ss = []
        for k in st_codes:
            st = stands_map.get(k) or {}
            ss.append("%s — %s" % (st.get("code", k), st.get("name", "")))
        out.append("### Стенды\n" + "\n".join("- %s" % _clean(x) for x in ss))
    tasks = card.get("tasks") or []
    if tasks:
        out.append("### Задания бригады\n" + "\n".join(
            "%d. %s" % (i + 1, _clean(t)) for i, t in enumerate(tasks)))
    given = card.get("given") or []
    if given:
        out.append("### Что сдаёт бригада\n" + "\n".join(
            "- %s" % _clean(x) for x in given))
    crit = [c for c in (card.get("criteria") or []) if c]
    if crit:
        out.append("### Критерии оценки\n" + "\n".join(
            "- %s — **%s балл.**" % (_clean(str(c[0])), _clean(str(c[1])))
            for c in crit))
    traps = card.get("traps") or []
    if traps:
        out.append("### Ловушки (типовые ошибки)\n" + "\n".join(
            "- %s" % _clean(x) for x in traps))
    return "\n\n".join(out)


def register(ctx):
    base = (ctx.settings.get("папка") or "").strip()

    def kits():
        out = []
        if base and os.path.isdir(base):
            for name in sorted(os.listdir(base)):
                d = os.path.join(base, name)
                if os.path.isdir(d) and os.path.isfile(os.path.join(d, "cards.js")):
                    out.append(name)
        return out

    def _safe_name(name):
        name = os.path.basename(name or "")
        return name if re.match(r"^[\w.\- ]+$", name, re.U) else ""

    # ── Страница импорта (преподаватель) ────────────────────────────
    @ctx.add_route("GET", "/staff/scenarios", access="staff")
    def scenarios_page(handler, params):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
        msg = ""
        if (qs.get("ok") or [""])[0]:
            msg = ('<div class="sub-status"><p>Готово: занятие по сценарию '
                   '«%s» создано.</p></div>' % _e((qs.get("ok") or [""])[0]))
        elif (qs.get("exists") or [""])[0]:
            msg = ('<div class="notice"><p>Сценарий «%s» уже импортирован '
                   'в этот курс.</p></div>' % _e((qs.get("exists") or [""])[0]))
        ks = kits()
        if not ks:
            body = (msg +
                    '<div class="staff-card"><h2>🎬 Сценарии УП</h2>'
                    '<p class="error">Комплекты не найдены в папке '
                    '<code>%s</code>. Укажите путь в '
                    'modules/scenarios/модуль.json.</p></div>') % _e(base)
            return ctx.render_page("Сценарии УП", body, staff=True)

        imported = ctx.kv_load("scenarios", {})
        opts = "".join(
            '<option value="%s">%s</option>'
            % (_e(c["id"]), _e(c.get("title", "")))
            for c in ctx.list_courses())
        cards = ""
        for k in ks:
            marks = [cid for cid, v in imported.items()
                     if isinstance(v, dict) and k in v]
            mark = ('<p class="reason">Уже импортирован в курсы: %s</p>'
                    % _e(", ".join(marks))) if marks else ""
            cards += (
                '<div class="staff-card"><h2>%s</h2>%s'
                '<form onsubmit="return _imp(this)">'
                '<input type="hidden" name="kit" value="%s">'
                '<p><label>Курс: <select name="course">%s</select></label></p>'
                '<p><button>Импортировать как занятие</button></p>'
                '</form></div>') % (_e(k), mark, _e(k), opts)
        js = """<script>
function _imp(f){
  var kit=f.kit.value, cid=f.course.value;
  var btn=f.querySelector('button'); btn.disabled=true; btn.textContent='Импорт…';
  var n=0;
  function step(){
    n++;
    if(n===1){var s=document.createElement('script');
      s.src='/scnfile/'+encodeURIComponent(kit)+'/event.js';
      s.onload=step;
      s.onerror=function(){btn.disabled=false;btn.textContent='Импортировать как занятие';alert('Не найден event.js')};
      document.head.appendChild(s);return}
    if(n===2){var s2=document.createElement('script');
      s2.src='/scnfile/'+encodeURIComponent(kit)+'/cards.js';
      s2.onload=step;
      s2.onerror=function(){btn.disabled=false;btn.textContent='Импортировать как занятие';alert('Не найден cards.js')};
      document.head.appendChild(s2);return}
    var EV=window.EVENT||{}, CD=window.CARDS||[];
    var cards=CD.map(function(c){return{
      id:c.id,title:c.title,lvl:c.lvl,time:c.time,team:c.team,role:c.role,
      story:c.story,obj:c.obj,data_table:c.data_table,tasks:c.tasks,
      given:c.given,criteria:c.criteria,traps:c.traps,stands:c.stands};});
    fetch('/staff/scenarios/import',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({course:cid,kit:kit,
          event:{title:EV.title,place:EV.place,stands:EV.stands},
          cards:cards})})
      .then(function(r){return r.text()})
      .then(function(t){
        if(t==='ok'||t==='exists'){
          location.href='/staff/scenarios?'+t+'='+encodeURIComponent(kit)}
        else{btn.disabled=false;btn.textContent='Импортировать как занятие';alert(t)}});
  }
  step(); return false;
}
</script>"""
        body = (msg +
                '<div class="staff-card"><h2>🎬 Сценарии УП</h2>'
                '<p class="hint">Комплект = папка со сценарием (event.js + '
                'cards.js + plans.js). Модуль создаст занятие: материалы '
                'комплекта увидят студенты курса, по каждой карточке сценария '
                'будет задание (отчёт — один на бригаду). План преподавателя '
                'и эталоны не копируются.</p></div>' + cards + js)
        return ctx.render_page("Сценарии УП", body, staff=True)

    # ── Файлы комплекта для страницы импорта (только преподаватель) ──
    @ctx.add_route("GET", "/scnfile/", access="staff")
    def scn_file(handler, params):
        import mimetypes
        parts = params.get("_parts", [])
        kit = _safe_name(parts[0] if parts else "")
        fname = _safe_name(parts[1] if len(parts) > 1 else "")
        local = os.path.join(base, kit, fname) if kit and fname else ""
        if not local or not os.path.isfile(local):
            handler._send_text(404, "Not Found")
            return handler._SENT
        with open(local, "rb") as f:
            data = f.read()
        mime = mimetypes.guess_type(local)[0] or "application/octet-stream"
        handler._send_response(200, mime, data, encode=False)
        return handler._SENT

    # ── Импорт: занятие + задания по карточкам ──────────────────────
    @ctx.add_route("POST", "/staff/scenarios/import", access="staff")
    def import_kit(handler, params):
        try:
            data = handler._parse_post()
        except Exception:
            data = {}
        if not isinstance(data, dict):
            handler._send_text(400, "bad payload")
            return handler._SENT
        cid = data.get("course", "")
        kit = _safe_name(data.get("kit", ""))
        ev = data.get("event") or {}
        cards = data.get("cards") or []
        if not ctx.get_course(cid) or not kit or not cards:
            handler._send_text(400, "course/kit/cards required")
            return handler._SENT
        imported = ctx.kv_load("scenarios", {})
        if cid in imported and kit in imported[cid]:
            handler._send_text(200, "exists")
            return handler._SENT

        title = _clean_title(ev.get("title", "")) or kit.replace("_", " ")
        lid = ctx.add_lesson(cid, title, materials=[])

        # копия комплекта студентам (без эталонов и плана преподавателя)
        mat_names = []
        src_dir = os.path.join(base, kit)
        ddir = ctx.mat_dir(cid, lid)
        os.makedirs(ddir, exist_ok=True)
        if os.path.isdir(src_dir):
            for fn in sorted(os.listdir(src_dir)):
                src = os.path.join(src_dir, fn)
                if not os.path.isfile(src):
                    continue
                if fn.startswith(STUDENT_SKIP_PREFIX):
                    continue
                dst = os.path.join(ddir, fn)
                if fn.lower() == "plans.js":
                    try:
                        txt = io.open(src, encoding="utf-8").read()
                        txt = STRIP_RE.sub(
                            lambda m: m.group(1) + ": []", txt)
                        io.open(dst, "wb").write(txt.encode("utf-8"))
                    except (OSError, ValueError):
                        shutil.copy2(src, dst)
                else:
                    shutil.copy2(src, dst)
                mat_names.append(fn)
        lesson = ctx.get_lesson(lid)
        if lesson is not None:
            lesson["материалы"] = [
                {"тип": "файл", "имя": fn} for fn in mat_names
                if fn.lower().endswith(".html")]
            ctx.save()

        n_tasks = 0
        for card in cards:
            if not isinstance(card, dict) or not card.get("title"):
                continue
            ttitle = "%s · %s" % (card.get("id", ""),
                                  _clean_title(card.get("title", "")))
            form = [
                {"ключ": "plan", "тип": "file",
                 "вопрос": "План с размещёнными устройствами (фото/скан)",
                 "обязательно": True},
                {"ключ": "calc", "тип": "textarea",
                 "вопрос": "Расчёты, ведомость ШС, обоснование",
                 "строк": 7, "место": "Формулы, число ИП, шлейфы, выводы…"},
            ]
            ctx.add_task(lid, ttitle, _card_desc(card, ev), form, None)
            n_tasks += 1

        imported.setdefault(cid, {})[kit] = {"lid": lid, "tasks": n_tasks}
        ctx.kv_save("scenarios", imported)
        ctx.log("сценарий %s -> курс %s: занятие %s, заданий %d"
                % (kit, cid, lid, n_tasks))
        handler._send_text(200, "ok")
        return handler._SENT

    ctx.log("загружен: сценарии УП (%s)" % (base or "папка не задана"))
