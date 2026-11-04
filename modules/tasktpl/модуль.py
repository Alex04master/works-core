# -*- coding: utf-8 -*-
"""Модуль «Шаблоны заданий»: заготовки типовых заданий.

- Кнопка «🗃 В шаблоны» на странице задания сохраняет название,
  описание, форму отчёта, срок и критерии в библиотеку шаблонов.
- Страница /staff/tpl: задание из шаблона создаётся в любом занятии
  любого курса одним кликом; шаблоны можно удалять.
- Шаблоны хранятся в данных модуля (данные/модули/tasktpl).
"""
import json


def _e(v):
    import html
    return html.escape(str(v), quote=True)


SAVE_JS = """<script>
document.addEventListener('DOMContentLoaded',function(){
 try{
  if(!document.body.classList.contains('staff'))return;
  var m=/^\\/staff\\/task\\/([^\\/?]+)/.exec(location.pathname);if(!m)return;
  var card=document.querySelector('main .staff-card');if(!card)return;
  var bar=document.getElementById('wc-task-tools');
  if(!bar){bar=document.createElement('div');bar.className='staff-actions';
    bar.id='wc-task-tools';card.parentNode.insertBefore(bar,card);}
  if(bar.querySelector('form[action="/staff/tpl/save"]'))return;
  var f=document.createElement('form');f.method='POST';
  f.action='/staff/tpl/save';f.style.display='inline-block';
  var h=document.createElement('input');h.type='hidden';h.name='task';h.value=m[1];
  var b=document.createElement('button');b.className='btn btn-secondary';
  b.title='Сохранить задание как шаблон';
  b.textContent='🗃 В шаблоны';
  f.appendChild(h);f.appendChild(b);bar.appendChild(f);
 }catch(e){}
});</script>"""


def register(ctx):
    # ── Кнопка на странице задания + ссылка в шапке курса ───────────
    def _tools_js(course=None, lesson=None, **kw):
        return SAVE_JS

    ctx.on("page.head", _tools_js)

    def _course_btn(cid="", **kw):
        return ('<a class="btn btn-secondary" href="/staff/tpl" '
                'title="Библиотека шаблонов заданий">🗃 Шаблоны</a>')

    ctx.on("staff.course_actions", _course_btn)

    def _load():
        d = ctx.kv_load("шаблоны.json", {"next": 1, "items": []})
        d.setdefault("next", 1)
        d.setdefault("items", [])
        return d

    # ── Сохранить задание как шаблон ─────────────────────────────────
    @ctx.add_route("POST", "/staff/tpl/save", access="staff")
    def tpl_save(handler, params):
        data = handler._parse_post()
        task = ctx.get_task(data.get("task", ""))
        if task:
            d = _load()
            st = task.get("настройки") or {}
            crit = st.get("критерии")
            d["items"].append({
                "id": "tpl-%d" % d["next"],
                "title": task.get("title", ""),
                "описание": task.get("описание", ""),
                "форма": json.loads(json.dumps(task.get("форма") or [])),
                "срок": st.get("срок", "") or "",
                "критерии": list(crit) if isinstance(crit, list) else [],
            })
            d["next"] += 1
            ctx.kv_save("шаблоны.json", d)
            ctx.audit("сохранён шаблон задания",
                      {"задание": task.get("id", ""),
                       "название": task.get("title", "")}, handler=handler)
        handler._redirect("/staff/tpl")
        return handler._SENT

    # ── Страница шаблонов ────────────────────────────────────────────
    @ctx.add_route("GET", "/staff/tpl", access="staff")
    def tpl_page(handler, params):
        d = _load()
        opts = ""
        for c in ctx.list_courses():
            for l in ctx.list_lessons(c["id"]):
                opts += ('<option value="%s">%s · %s</option>'
                         % (_e(l["id"]), _e(c.get("title", "")),
                            _e(l.get("title", ""))))
        cards = ""
        for t in d["items"]:
            nf = len(t.get("форма") or [])
            dl_s = (' · срок: %s' % _e(t["срок"])) if t.get("срок") else ""
            crit = t.get("критерии") or []
            crit_s = (' · критериев: %d' % len(crit)) if crit else ""
            cards += (
                '<details><summary>🗃 %s</summary><div class="staff-card">'
                '<p class="hint">Полей в форме: %d%s%s. Описание: %s</p>'
                '<form method="post" action="/staff/tpl/new">'
                '<input type="hidden" name="tpl" value="%s">'
                '<p><label>Создать в занятии: '
                '<select name="lesson">%s</select></label></p>'
                '<p><label>Название задания: '
                '<input type="text" name="title" value="%s"></label></p>'
                '<p><button>Создать задание из шаблона</button></p></form>'
                '<form method="post" action="/staff/tpl/del" '
                'onsubmit="return confirm(\'Удалить шаблон?\')">'
                '<input type="hidden" name="tpl" value="%s">'
                '<p><button class="btn btn-danger">Удалить шаблон</button>'
                '</p></form></div></details>'
            ) % (_e(t.get("title", "")), nf, dl_s, crit_s,
                 _e(t.get("описание", "")) or "—",
                 _e(t.get("id", "")), opts, _e(t.get("title", "")),
                 _e(t.get("id", "")))
        empty = ('<p class="hint">Шаблонов пока нет. Откройте любое задание '
                 '(курс → занятие → задание) и нажмите кнопку '
                 '«🗃 В шаблоны» — название, описание, форма отчёта, срок '
                 'и критерии сохранятся здесь.</p>') if not d["items"] else ""
        body = (
            '<p><a href="/staff">Все курсы</a></p>'
            '<div class="staff-card"><h2>🗃 Шаблоны заданий</h2>'
            '<p class="hint">Шаблон — заготовка задания для типовых работ: '
            'создайте задание из шаблона в любом занятии одним кликом.</p>'
            '%s</div>%s') % (empty, cards)
        return ctx.render_page("Шаблоны заданий", body, staff=True)

    # ── Создать задание из шаблона ───────────────────────────────────
    @ctx.add_route("POST", "/staff/tpl/new", access="staff")
    def tpl_new(handler, params):
        data = handler._parse_post()
        d = _load()
        tpl = next((x for x in d["items"]
                    if x.get("id") == data.get("tpl", "")), None)
        lesson = ctx.get_lesson(data.get("lesson", ""))
        if not tpl or not lesson:
            handler._redirect("/staff/tpl")
            return handler._SENT
        title = (data.get("title", "").strip()
                 or tpl.get("title", "") or "Задание")
        st = {}
        if tpl.get("срок"):
            st["срок"] = tpl["срок"]
        if tpl.get("критерии"):
            st["критерии"] = list(tpl["критерии"])
        tid = ctx.add_task(lesson["id"], title,
                           tpl.get("описание", ""),
                           json.loads(json.dumps(tpl.get("форма") or [])), st)
        ctx.audit("создано задание из шаблона",
                  {"задание": tid, "название": title,
                   "шаблон": tpl.get("title", ""),
                   "занятие": lesson["id"]}, handler=handler)
        handler._redirect("/staff/task/%s" % _e(tid))
        return handler._SENT

    # ── Удалить шаблон ───────────────────────────────────────────────
    @ctx.add_route("POST", "/staff/tpl/del", access="staff")
    def tpl_del(handler, params):
        data = handler._parse_post()
        key = data.get("tpl", "")
        d = _load()
        d["items"] = [x for x in d["items"] if x.get("id") != key]
        ctx.kv_save("шаблоны.json", d)
        ctx.audit("удалён шаблон задания", {"шаблон": key}, handler=handler)
        handler._redirect("/staff/tpl")
        return handler._SENT

    ctx.log("загружен: шаблоны заданий (кнопка на задании, /staff/tpl)")
