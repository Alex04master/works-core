# -*- coding: utf-8 -*-
"""Модуль «Мои задания»: личная страница студента по всем курсам.

- Ссылка «🙋 Мои задания» появляется в шапке студенческих страниц.
- Страница /my: все видимые задания по всем доступным курсам —
  статус (не сдано / на проверке / принято / доработка / не принято,
  своё или отчёт бригады), балл, срок и кнопки перехода.
"""
from datetime import datetime


def _e(v):
    import html
    return html.escape(str(v), quote=True)


NAV_JS = """<script>
document.addEventListener('DOMContentLoaded',function(){
 try{
  if(document.body.classList.contains('staff'))return;
  var n=document.querySelector('header.topbar nav');if(!n)return;
  if(n.querySelector('a[href="/my"]'))return;
  var a=document.createElement('a');a.href='/my';
  a.title='Все мои задания по всем курсам';
  a.textContent='🙋 Мои задания';
  n.appendChild(a);
 }catch(e){}
});</script>"""

_ICONS = {
    "сдано": ("mx-sent", "📤 на проверке"),
    "принято": ("mx-ok", "✅ принято"),
    "доработка": ("mx-fix", "🔄 доработка"),
    "отклонено": ("mx-rej", "❌ не принято"),
}


def _parse_dl(value):
    v = str(value or "").strip()
    if not v:
        return None
    v = v.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            pass
    return None


def register(ctx):
    # ── Ссылка в шапке студенческих страниц ──────────────────────────
    def _nav_js(course=None, lesson=None, **kw):
        return NAV_JS

    ctx.on("page.head", _nav_js)

    # ── Страница «Мои задания» ───────────────────────────────────────
    @ctx.add_route("GET", "/my", access="student")
    def my_page(handler, params):
        sid = handler._student()
        stu = ctx.get_student(sid) or {}
        brig = (stu.get("бригада", "") or "").strip()
        sections = ""
        for c in ctx.list_courses():
            if not ctx.can_access(c["id"], sid):
                continue
            blocks = ""
            for l in ctx.list_lessons(c["id"]):
                rows = ""
                for t in ctx.list_tasks(l["id"]):
                    if not ctx.task_for_brigade(t, brig):
                        continue
                    sub = ctx._core.sub_for(t["id"], sid)
                    if sub:
                        st = sub.get("status", "сдано")
                        cls, label = _ICONS.get(st, _ICONS["сдано"])
                        ver = (sub.get("versions") or [{}])[-1]
                        late = " ⏰" if ver.get("просрочено") else ""
                        score = ver.get("score")
                        score_s = str(score) if score is not None else "—"
                        brig_s = ('<div class="reason">👥 %s</div>'
                                  % _e(sub["бригада"])
                                  ) if sub.get("бригада") else ""
                        act = ('<a class="btn btn-sm" href="/mysub/%s">'
                               'Статус сдачи</a> '
                               '<a class="btn btn-sm btn-secondary" '
                               'href="/task/%s">Задание</a>'
                               ) % (_e(t["id"]), _e(t["id"]))
                        rows += (
                            '<tr><td>%s%s</td>'
                            '<td><span class="%s">%s</span>%s</td>'
                            '<td>%s</td><td>%s</td></tr>'
                        ) % (_e(t.get("title", "")), brig_s, cls, label,
                             late, score_s, act)
                    else:
                        dl = _parse_dl((t.get("настройки") or {}).get("срок"))
                        overdue = bool(dl) and datetime.now() > dl
                        mark = ('<span class="mx-rej">⏰ просрочено</span>'
                                if overdue
                                else '<span class="mx-wait">— не сдано</span>')
                        dl_s = ""
                        if dl:
                            dl_s = "до " + dl.strftime("%d.%m.%Y %H:%M")
                            if overdue:
                                dl_s += " (истёк)"
                        rows += (
                            '<tr><td>%s</td>'
                            '<td>%s%s</td><td>—</td>'
                            '<td><a class="btn btn-sm" href="/task/%s">'
                            'Открыть</a></td></tr>'
                        ) % (_e(t.get("title", "")), mark,
                             ('<div class="reason">%s</div>' % _e(dl_s))
                             if dl_s else "", _e(t["id"]))
                if rows:
                    blocks += (
                        '<h3>%s</h3>'
                        '<table class="mx-tbl my-tbl">'
                        '<tr><th>Задание</th><th>Статус</th><th>Балл</th>'
                        '<th></th></tr>%s</table>'
                    ) % (_e(l.get("title", "")), rows)
            if blocks:
                sections += ('<div class="staff-card"><h2>%s</h2>%s</div>'
                             ) % (_e(c.get("title", "")), blocks)
        if not sections:
            body = ('<p class="hint">Вы пока не зачислены ни на один курс '
                    '(или задания ещё не выданы). Откройте ссылку, которую '
                    'дал преподаватель.</p>')
        else:
            body = sections
        return ctx.render_page("Мои задания", body)

    ctx.log("загружен: мои задания (страница /my + ссылка в шапке)")
