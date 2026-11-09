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
import json
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
    def _kits_base():
        """Папка с комплектами: настройка, а если её нет на диске —
        известные места (путь зависит от компьютера: E:/ или D:/)."""
        cand = (ctx.settings.get("папка") or "").strip()
        if cand and os.path.isdir(cand):
            return cand
        root = os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))
        for c in (os.path.join(root, os.pardir, "AI-projects",
                               "Сценарии для УП"),
                  "E:/AI/AI-projects/Сценарии для УП",
                  "D:/AI/AI-projects/Сценарии для УП",
                  "D:/AI/AI-projects/works-core/Сценарии для УП"):
            c = os.path.abspath(c)
            if os.path.isdir(c):
                return c
        return cand

    base = _kits_base()

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
            mark = ""
            if marks:
                mark = ('<p class="reason">Уже импортирован в курсы: %s.</p>'
                        % _e(", ".join(marks)))
                for mc in marks:
                    mark += (
                        '<form method="post" '
                        'action="/staff/scenarios/repair" style="display:inline">'
                        '<input type="hidden" name="course" value="%s">'
                        '<input type="hidden" name="kit" value="%s">'
                        '<button class="btn-sm btn-secondary" '
                        'title="Починить форму (план), привязку плана и '
                        'материалы у ранее импортированного занятия">'
                        'Обновить: %s</button></form> ' % (_e(mc), _e(k), _e(mc)))
                mark += ('<p class="hint">После обновления задания снова ждут '
                         'выдачи бригадам.</p>')
            cards += (
                '<div class="staff-card"><h2>%s</h2>%s'
                '<form onsubmit="return _imp(this)">'
                '<input type="hidden" name="kit" value="%s">'
                '<p><label>Курс: <select name="course">%s</select></label></p>'
                '<p><button>Импортировать как занятие</button></p>'
                '</form></div>') % (_e(k), mark, _e(k), opts)
        rall = ""
        if any(isinstance(v, dict) and v for v in imported.values()):
            rall = ('<form method="post" '
                    'action="/staff/scenarios/repair_all" style="display:inline">'
                    '<button class="btn-sm btn-secondary" title="Обновить '
                    'материалы, форму и привязку плана у всех импортированных '
                    'занятий">🔄 Обновить все сценарии</button></form>')
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
                'и эталоны не копируются.</p>' + rall + '</div>' + cards + js)
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

    def _repair_one(cid, kit):
        """Обновить занятие, импортированное из комплекта: материалы,
        привязка плана, поля формы. Возвращает (ok, заданий, причина)."""
        imported = ctx.kv_load("scenarios", {})
        info = imported.get(cid, {}) if isinstance(imported.get(cid), dict) else {}
        lid = (info.get(kit) or {}).get("lid", "")
        lesson = ctx.get_lesson(lid) if lid else None
        if not lesson:
            return False, 0, "занятие не найдено"
        lesson["материалы"] = [
            m for m in (lesson.get("материалы") or [])
            if str(m.get("имя", "")).startswith(("02_", "05_", "06_"))]
        n = 0
        for t in ctx.list_tasks():
            if t.get("lesson") != lid:
                continue
            st = t.setdefault("настройки", {})
            if not st.get("план"):
                st["план"] = t.get("title", "").split("·")[0].strip()
            keys = [f.get("ключ") for f in t.get("форма", [])]
            if "plan_data" not in keys:
                calc = next((f for f in t.get("форма", [])
                             if f.get("тип") == "textarea"), None)
                if calc:
                    calc["обязательно"] = True
                t["форма"] = ([calc] if calc else
                              [{"ключ": "calc", "тип": "textarea",
                                "вопрос": "Расчёты, обоснование",
                                "обязательно": True, "строк": 7}]) + [
                    {"ключ": "plan_data", "тип": "hidden",
                     "вопрос": "Размещение устройств на плане"}]
                keys = [f.get("ключ") for f in t["форма"]]
            if "loops" not in keys:
                t["форма"].append({"ключ": "loops", "тип": "shlei",
                                   "вопрос": "Ведомость шлейфов",
                                   "строк": 10})
            if "firmware" not in keys:
                t["форма"].append({"ключ": "firmware", "тип": "firmware",
                                   "вопрос": "Файлы прошивки прибора",
                                   "лимит": 5})
            n += 1
        ctx.save()
        ctx.kv_save("scenarios", imported)
        ctx.log("починен импорт %s/%s: заданий %d" % (cid, kit, n))
        return True, n, ""

    # ── Починка ранее импортированного занятия ──────────────────────
    @ctx.add_route("POST", "/staff/scenarios/repair", access="staff")
    def repair_kit(handler, params):
        data = handler._parse_post()
        cid = data.get("course", "")
        kit = _safe_name(data.get("kit", ""))
        ok, n, why = _repair_one(cid, kit)
        if not ok:
            handler._send_text(400, "not imported")
            return handler._SENT
        ctx.audit("обновлён импорт сценария",
                  {"комплект": kit, "курс": cid, "заданий": n},
                  handler=handler)
        handler._send_text(200, "ok:%d" % n)
        return handler._SENT

    # ── Починка сразу всех импортированных занятий ──────────────────
    @ctx.add_route("POST", "/staff/scenarios/repair_all", access="staff")
    def repair_all_kits(handler, params):
        imported = ctx.kv_load("scenarios", {})
        pairs = []
        for cid, info in imported.items():
            if isinstance(info, dict):
                for kit in info:
                    pairs.append((cid, kit))
        pairs.sort()
        good, bad, parts = 0, 0, []
        for cid, kit in pairs:
            ok, n, why = _repair_one(cid, kit)
            if ok:
                good += 1
                parts.append("%s / %s — заданий %d" % (cid, kit, n))
            else:
                bad += 1
                parts.append("%s / %s — %s" % (cid, kit, why))
        ctx.audit("обновлены все сценарии",
                  {"обновлено": good, "ошибок": bad}, handler=handler)
        handler._send_text(200, "ok:%d (ошибок: %d) %s"
                           % (good, bad, "; ".join(parts)))
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
            # студентам — только раздатка (02), планы (05), обозначения (06)
            lesson["материалы"] = [
                {"тип": "файл", "имя": fn} for fn in mat_names
                if fn.lower().endswith(".html")
                and (fn.startswith("02_") or fn.startswith("05_")
                     or fn.startswith("06_"))]
            ctx.save()

        n_tasks = 0
        for card in cards:
            if not isinstance(card, dict) or not card.get("title"):
                continue
            ttitle = "%s · %s" % (card.get("id", ""),
                                  _clean_title(card.get("title", "")))
            form = [
                {"ключ": "plan_data", "тип": "hidden",
                 "вопрос": "Размещение устройств на плане"},
                {"ключ": "loops", "тип": "shlei",
                 "вопрос": "Ведомость шлейфов", "строк": 10},
                {"ключ": "firmware", "тип": "firmware",
                 "вопрос": "Файлы прошивки прибора", "лимит": 5},
                {"ключ": "calc", "тип": "textarea",
                 "вопрос": "Расчёты, обоснование",
                 "обязательно": True,
                 "строк": 7, "место": "Формулы, число ИП, выводы…"},
            ]
            crit = []
            for c in (card.get("criteria") or []):
                if isinstance(c, (list, tuple)) and len(c) >= 2 and c[0]:
                    crit.append("%s — %s балл." % (_clean(str(c[0])),
                                                   _clean(str(c[1]))))
                elif isinstance(c, str) and c.strip():
                    crit.append(_clean(c))
            ctx.add_task(lid, ttitle, _card_desc(card, ev), form,
                         {"план": card.get("id", ""), "критерии": crit})
            n_tasks += 1

        imported.setdefault(cid, {})[kit] = {"lid": lid, "tasks": n_tasks}
        ctx.kv_save("scenarios", imported)
        ctx.log("сценарий %s -> курс %s: занятие %s, заданий %d"
                % (kit, cid, lid, n_tasks))
        ctx.audit("импортирован сценарий",
                  {"комплект": kit, "курс": cid, "заданий": n_tasks},
                  handler=handler)
        handler._send_text(200, "ok")
        return handler._SENT

    # ── Интерактивный план (студент — редактор, преподаватель — просмотр) ──
    PLAN_TPL = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>План сооружения — works-core</title>
<style>
body{font:14px/1.45 'Segoe UI',Tahoma,sans-serif;color:#333;margin:0;padding:12px;background:#fff}
.tools{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px;align-items:center}
.tool{padding:6px 10px;border:2px solid #e0e0e0;border-radius:8px;cursor:pointer;background:#f8f9fa;font-weight:600;font-size:12.5px;display:inline-flex;align-items:center;gap:6px;transition:all .15s;font-family:inherit}
.tool:hover{transform:translateY(-1px)}
.tool.active{border-color:#667eea;background:#eef2ff;color:#667eea}
.sw{width:13px;height:13px;border-radius:50%;display:inline-block;border:2px solid #999;box-sizing:border-box}
.sw.sq{border-radius:3px}.sw.rc{border-radius:2px;width:19px}
svg{display:block;background:#fafbfe;border:1px solid #e5e7eb;border-radius:8px;cursor:crosshair;max-width:100%}
.bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:8px 0}
.cnt{font-size:12px;color:#555;background:#f8f9fa;border-radius:8px;padding:3px 8px}
.hint{color:#888;font-size:12px}
body.ro .tools{display:none}body.ro svg{cursor:default;background:#f8fafc}
.err{color:#b91c1c;font-weight:600}
.legbox{margin-top:10px}.legbox summary{cursor:pointer;font-weight:600;color:#667eea;padding:6px 0}
table.leg{border-collapse:collapse;font-size:12.5px;margin-top:4px}
table.leg td{padding:4px 12px 4px 0;vertical-align:top;color:#555}
</style></head><body>
<div id="app"><p class="hint">Загрузка данных плана…</p></div>
<script>var TID=__TID__,MATS=__MATS__,PLAN_ID=__PLANID__,RO=__RO__,INIT=__INIT__;</script>
<script src="__SRC1__"></script>
<script src="__SRC2__"></script>
<script>
function _esc(s){return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}
function boot(){
  var EV=window.EVENT||{}, ALL=window.PLANS||[];
  var PL=null; for(var i=0;i<ALL.length;i++){if(ALL[i].id===PLAN_ID){PL=ALL[i];break}}
  var app=document.getElementById("app");
  if(!PL){
    app.innerHTML='<p class="err">План не найден'+(PLAN_ID?' («'+_esc(PLAN_ID)+'»)':'')+'.</p>'
      +(ALL.length?'<p class="hint">Доступные планы: '+ALL.map(function(p){return _esc(p.id)}).join(', ')+'</p>'
                  :'<p class="hint">Файл plans.js не найден в материалах занятия.</p>');
    return}
  var LEG=EV.legend||[];
  var xs=[],ys=[];PL.rooms.forEach(function(r){xs.push(r.x,r.x+r.w);ys.push(r.y,r.y+r.h)});
  var mg=0.6,x0=Math.min.apply(null,xs)-mg,y0=Math.min.apply(null,ys)-mg;
  var w=Math.max.apply(null,xs)+mg-x0,h=Math.max.apply(null,ys)+mg-y0;
  var tb='<div class="tools">';
  if(!RO){LEG.forEach(function(l,i){
    var sh=(l.shape==="square")?" sq":(l.shape==="rect")?" rc":"";
    tb+='<button type="button" class="tool" data-i="'+i+'" title="'+_esc(l.rule||"")+'"><span class="sw'+sh+'" style="background:'+_esc(l.fill||"#fff")+';border-color:'+_esc(l.color||"#666")+'"></span>'+_esc(l.label)+'</button>'});
    tb+='<button type="button" class="tool" data-i="-1"><span class="sw" style="background:#fff"></span>Убрать (ластик)</button>';
    tb+='<button type="button" class="tool" id="clr">Очистить всё</button>';
  } else { tb+='<span class="hint">Режим просмотра — размещение студента.</span>'; }
  tb+='</div><div class="bar" id="cnt"></div>';
  var lg='<details class="legbox"><summary>Условные обозначения</summary>'
    +'<table class="leg">';
  LEG.forEach(function(l){
    lg+='<tr><td><span class="sw" style="background:'+_esc(l.fill||"#fff")
      +';border-color:'+_esc(l.color||"#666")+'"></span></td><td><b>'
      +_esc(l.label)+'</b></td><td>'+_esc(l.rule||"")+'</td></tr>'});
  lg+='</table></details>';
  app.innerHTML=tb+'<svg id="svg" viewBox="'+x0+" "+y0+" "+w+" "+h+'" width="100%" height="600"></svg>'+lg;
  if(RO)document.body.className="ro";
  var svg=document.getElementById("svg");
  var dev=(RO&&INIT)?INIT.slice():load();
  var act=RO?-2:0;
  function short(l){return String(l).split("(")[0].trim()}
  function draw(){
    var s="";
    PL.rooms.forEach(function(r){
      s+='<rect x="'+r.x+'" y="'+r.y+'" width="'+r.w+'" height="'+r.h+'" fill="#fff" stroke="#94a3b8" stroke-width="0.06"/>';
      s+='<text x="'+(r.x+r.w/2)+'" y="'+(r.y+r.h/2)+'" font-size="0.4" text-anchor="middle" fill="#475569">'+_esc(r.n)+(r.d?" · "+_esc(r.d):"")+"</text>";
    });
    dev.forEach(function(d,i){
      var l=null;for(var j=0;j<LEG.length;j++){if(LEG[j].key===d.t){l=LEG[j];break}}
      l=l||{color:"#667eea",shape:"circle",fill:"#fff"};
      var c=l.color||"#667eea";
      if(l.shape==="square"){s+='<rect x="'+(d.x-0.28)+'" y="'+(d.y-0.28)+'" width="0.56" height="0.56" fill="'+_esc(l.fill||"#fff")+'" stroke="'+c+'" stroke-width="0.07"/>'}
      else if(l.shape==="rect"){s+='<rect x="'+(d.x-0.85)+'" y="'+(d.y-0.22)+'" width="1.7" height="0.44" rx="0.08" fill="'+_esc(l.fill||"#fff")+'" stroke="'+c+'" stroke-width="0.06"/>'}
      else{s+='<circle cx="'+d.x+'" cy="'+d.y+'" r="0.3" fill="'+_esc(l.fill||"#fff")+'" stroke="'+c+'" stroke-width="0.07"/>'}
      var tx=l.planText||l.text||"";
      if(tx){s+='<text x="'+d.x+'" y="'+(d.y+0.12)+'" font-size="0.3" text-anchor="middle" fill="'+c+'" font-weight="bold">'+_esc(tx)+"</text>"}
      s+='<circle class="hit" data-i="'+i+'" cx="'+d.x+'" cy="'+d.y+'" r="0.42" fill="transparent"/>';
    });
    svg.innerHTML=s;
    var c2={};dev.forEach(function(d){c2[d.t]=(c2[d.t]||0)+1});
    var cc="Устройств: "+dev.length;
    LEG.forEach(function(l){if(c2[l.key])cc+=' <span class="cnt">'+_esc(short(l.label))+" × "+c2[l.key]+"</span>"});
    document.getElementById("cnt").innerHTML=cc;
    if(!RO){try{localStorage.setItem("wcplan_"+TID,JSON.stringify(dev))}catch(e){}}
  }
  svg.addEventListener("click",function(e){
    if(RO)return;
    var t=e.target;
    if(t.classList&&t.classList.contains("hit")){
      if(act===-1){dev.splice(+t.getAttribute("data-i"),1);draw()}
      return;
    }
    if(act<0)return;
    var pt=svg.createSVGPoint();pt.x=e.clientX;pt.y=e.clientY;
    var p=pt.matrixTransform(svg.getScreenCTM().inverse());
    var l=LEG[act];if(!l)return;
    dev.push({t:l.key,x:Math.round(p.x*100)/100,y:Math.round(p.y*100)/100});
    draw();
  });
  if(!RO){Array.prototype.forEach.call(document.querySelectorAll(".tool"),function(b){
    b.addEventListener("click",function(){
      if(b.id==="clr"){dev=[];draw();return}
      act=+b.getAttribute("data-i");
      Array.prototype.forEach.call(document.querySelectorAll(".tool"),function(x){x.classList.remove("active")});
      b.classList.add("active");
    });
  });
  var first=document.querySelector(".tool");if(first)first.classList.add("active");}
  function load(){try{return JSON.parse(localStorage.getItem("wcplan_"+TID)||"[]")}catch(e){return[]}}
  draw();
}
if(document.readyState!=="loading")boot();else document.addEventListener("DOMContentLoaded",boot);
</script></body></html>"""

    @ctx.add_route("GET", "/plan/", access="any")
    def plan_page(handler, params):
        parts = params.get("_parts", [])
        tid = parts[0] if parts else ""
        task = ctx.get_task(tid)
        if not task:
            handler._send_html("<h1>Задание не найдено</h1>")
            return handler._SENT
        lesson = ctx.get_lesson(task.get("lesson", ""))
        course_id = lesson.get("course", "") if lesson else ""
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
        is_staff = handler._is_staff()
        sid = handler._student()
        if not is_staff and not sid:
            handler._redirect("/_login?next=" + urllib.parse.quote(handler.path))
            return handler._SENT
        if not is_staff and course_id and not ctx.can_access(course_id, sid):
            handler._send_html("<h1>Нет доступа</h1>")
            return handler._SENT
        if not is_staff:
            _st = ctx.get_student(sid)
            _br = (_st.get("бригада", "") or "").strip() if _st else ""
            if not ctx.task_for_brigade(task, _br):
                handler._send_html(
                    "<h1>Задание не выдано</h1>"
                    "<p>Это задание выдано другой бригаде.</p>")
                return handler._SENT
        plan_id = (task.get("настройки") or {}).get("план", "")
        if not plan_id:
            # задания, импортированные раньше: id карточки — в начале названия
            # («СЦ-01 · Палатный корпус…»)
            plan_id = task.get("title", "").split("·")[0].strip()
        ro = False
        init = None
        if is_staff:
            sub_key = (qs.get("sub") or [""])[0]
            if sub_key and "__" in sub_key:
                _t, _s = sub_key.split("__", 1)
                sub = ctx.get_submission(_t, _s)
                if sub:
                    ver = None
                    vn = (qs.get("v") or [""])[0]
                    if vn.isdigit():
                        for x in sub.get("versions", []):
                            if x.get("n") == int(vn):
                                ver = x
                                break
                    ver = ver or (sub.get("versions") or [{}])[-1]
                    try:
                        init = json.loads(
                            ver.get("answers", {}).get("plan_data") or "[]")
                        if not isinstance(init, list):
                            init = []
                    except ValueError:
                        init = []
                    ro = True
        mats = "/materials/%s/%s" % (course_id, lesson["id"] if lesson else "")
        init_js = "[]" if not init else \
            json.dumps(init, ensure_ascii=False).replace("</", "<\\/")
        html = (PLAN_TPL
                .replace("__TID__", json.dumps(tid, ensure_ascii=False))
                .replace("__MATS__", json.dumps(mats))
                .replace("__PLANID__", json.dumps(plan_id, ensure_ascii=False))
                .replace("__RO__", "true" if ro else "false")
                .replace("__INIT__", init_js)
                .replace("__SRC1__", mats + "/event.js")
                .replace("__SRC2__", mats + "/plans.js"))
        handler._send_html(html)
        return handler._SENT

    ctx.log("загружен: сценарии УП (%s)" % (base or "папка не задана"))
