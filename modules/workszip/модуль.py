# -*- coding: utf-8 -*-
"""Модуль «Все работы архивом»: скачать сдачи задания одним .zip.

- Кнопка «📥 Все работы (.zip)» на странице задания (страница /staff/task).
- Страница /staff/works — список всех заданий со сдачами (фильтр по курсу).
- В архиве: по папке на студента или бригаду; файлы всех версий в
  папках v1, v2, ...; «отчёт.txt» — ответы последней версии, файлы
  и вердикт с критериями.
"""
import io as _io
import json
import os
import re
import urllib.parse
import zipfile


def _e(v):
    import html
    return html.escape(str(v), quote=True)


_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _sanitize(name):
    s = _BAD.sub("_", str(name or "")).strip().rstrip(". ")
    return s or "без-имени"


TOOLS_JS = """<script>
document.addEventListener('DOMContentLoaded',function(){
 try{
  if(!document.body.classList.contains('staff'))return;
  var m=/^\\/staff\\/task\\/([^\\/?]+)/.exec(location.pathname);if(!m)return;
  var card=document.querySelector('main .staff-card');if(!card)return;
  var bar=document.getElementById('wc-task-tools');
  if(!bar){bar=document.createElement('div');bar.className='staff-actions';
    bar.id='wc-task-tools';card.parentNode.insertBefore(bar,card);}
  var a=document.createElement('a');a.className='btn btn-secondary';
  a.href='/staff/works/'+m[1];a.title='Скачать все сдачи задания одним архивом';
  a.textContent='📥 Все работы (.zip)';
  bar.appendChild(a);
 }catch(e){}
});</script>"""


def register(ctx):
    # ── Кнопка на странице задания + ссылка в шапке курса ───────────
    def _tools_js(course=None, lesson=None, **kw):
        return TOOLS_JS

    ctx.on("page.head", _tools_js)

    def _course_btn(cid="", **kw):
        return ('<a class="btn btn-secondary" href="/staff/works?course=%s" '
                'title="Скачать все сдачи заданий курса архивами">'
                '📥 Работы</a>' % _e(cid))

    ctx.on("staff.course_actions", _course_btn)

    # ── Список заданий со сдачами ────────────────────────────────────
    @ctx.add_route("GET", "/staff/works", access="staff")
    def works_list(handler, params):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
        only = (qs.get("course") or [""])[0]
        rows = ""
        for c in ctx.list_courses():
            if only and c["id"] != only:
                continue
            for l in ctx.list_lessons(c["id"]):
                for t in ctx.list_tasks(l["id"]):
                    subs = ctx.list_submissions(task_id=t["id"])
                    if not subs:
                        continue
                    rows += (
                        '<tr><td>%s</td><td>%s</td><td>%s</td><td>%d</td>'
                        '<td><a class="btn btn-sm" href="/staff/works/%s">'
                        '📥 Скачать</a></td></tr>'
                    ) % (_e(c.get("title", "")), _e(l.get("title", "")),
                         _e(t.get("title", "")), len(subs), _e(t["id"]))
        if not rows:
            rows = ('<tr><td colspan="5" class="hint">Пока нет ни одной '
                    'сдачи.</td></tr>')
        body = (
            '<p><a href="/staff">Все курсы</a></p>'
            '<div class="staff-card">'
            '<h2>📥 Все работы архивом</h2>'
            '<p class="hint">В архиве — по папке на студента или бригаду: '
            'файлы всех версий (папки v1, v2, …) и «отчёт.txt» с ответами '
            'последней версии и вердиктом.</p>'
            '<table class="staff-table"><tr><th>Курс</th><th>Занятие</th>'
            '<th>Задание</th><th>Сдач</th><th></th></tr>%s</table>'
            '</div>') % rows
        return ctx.render_page("Все работы", body, staff=True)

    # ── Архив по заданию ─────────────────────────────────────────────
    def _folder(s, students, seen):
        brig = (s.get("бригада") or "").strip()
        if brig:
            base = "Бригада " + brig
        else:
            st = students.get(s.get("student", ""))
            base = (st["fio"] if st
                    else "студент " + str(s.get("student", "?")))
        base = _sanitize(base)
        cand, k = base, 2
        while cand in seen:
            cand = "%s [%d]" % (base, k)
            k += 1
        seen.add(cand)
        return cand

    def _report(task, lesson, course, s, students):
        vers = s.get("versions") or []
        v = vers[-1] if vers else {}
        brig = (s.get("бригада") or "").strip()
        lines = ["Задание: %s" % task.get("title", ""),
                 "Занятие: %s" % (lesson or {}).get("title", ""),
                 "Курс: %s" % (course or {}).get("title", "")]
        if brig:
            names, seen = [], set()
            for pid in (s.get("participants") or []):
                st = students.get(pid)
                names.append(st["fio"] if st else str(pid))
                seen.add(pid)
            for sid2, st2 in students.items():
                if ((st2.get("бригада") or "").strip() == brig
                        and sid2 not in seen):
                    names.append(st2.get("fio") or sid2)
            lines.append("Бригада: %s — участники: %s"
                         % (brig, ", ".join(names) or "-"))
            st0 = students.get(s.get("student", ""))
            if st0:
                lines.append("Сдал(и): %s" % st0.get("fio", ""))
        else:
            st = students.get(s.get("student", ""))
            if st:
                lines.append("Студент: %s (группа %s)"
                             % (st.get("fio", ""), st.get("group", "") or "-"))
        late = " (сдано после срока!)" if v.get("просрочено") else ""
        lines.append("Версия: %s от %s%s"
                     % (v.get("n", 0), v.get("time", ""), late))
        lines.append("-" * 40)
        lines.append("ОТВЕТЫ:")
        for fd in (task.get("форма") or []):
            key = fd.get("ключ", "")
            typ = fd.get("тип")
            if typ == "file":
                continue
            if typ == "hidden" and key != "plan_data":
                continue
            val = (v.get("answers") or {}).get(key, "")
            if typ == "shlei":
                lines.append("  %s:" % (fd.get("вопрос") or key))
                try:
                    rl = json.loads(val or "[]")
                except ValueError:
                    rl = []
                for r in (rl if isinstance(rl, list) else []):
                    if isinstance(r, dict):
                        lines.append(
                            "    шлейф %s: тип %s, прибор %s, кол-во %s%s"
                            % (r.get("n", ""), r.get("type", ""),
                               r.get("dev", ""), r.get("cnt", ""),
                               (" — " + r["note"]) if r.get("note") else ""))
                continue
            if key == "plan_data" and val:
                try:
                    dev = json.loads(val)
                    cnt = {}
                    for x in (dev if isinstance(dev, list) else []):
                        if isinstance(x, dict) and x.get("t"):
                            cnt[x["t"]] = cnt.get(x["t"], 0) + 1
                    lines.append(
                        "  Интерактивный план: устройств %d (%s)"
                        % (len(dev) if isinstance(dev, list) else 0,
                           ", ".join("%s × %d" % (k2, n2)
                                     for k2, n2 in sorted(cnt.items()))))
                except ValueError:
                    pass
                continue
            if val:
                lines.append("  %s: %s" % (fd.get("вопрос") or key, str(val)))
        files = v.get("files") or {}
        if files:
            lines.append("-" * 40)
            lines.append("ФАЙЛЫ:")
            for fk in sorted(files):
                info = files[fk] or {}
                lines.append("  %s — %s (%s байт)"
                             % (fk, info.get("имя", fk),
                                info.get("размер", "")))
        lines.append("-" * 40)
        if v.get("verdict"):
            lines.append("ВЕРДИКТ: %s" % v["verdict"])
            if v.get("score") is not None:
                lines.append("Балл: %s" % v.get("score"))
            if v.get("comment"):
                lines.append("Комментарий: %s" % v.get("comment"))
            crits = ((task.get("настройки") or {}).get("критерии")) or []
            chks = v.get("чек") or []
            if crits and chks:
                lines.append("Выполнено критериев:")
                for i, c in enumerate(crits):
                    if i in chks:
                        lines.append("  + %s" % c)
        else:
            lines.append("ВЕРДИКТ: ещё не проверено")
        lines.append("")
        return "\r\n".join(lines)

    @ctx.add_route("GET", "/staff/works/", access="staff")
    def works_zip(handler, params):
        tid = (params.get("_parts") or [""])[0]
        task = ctx.get_task(tid)
        if not task:
            handler._send_text(404, "task not found")
            return handler._SENT
        subs = ctx.list_submissions(task_id=tid)
        if not subs:
            handler._send_text(404, "no submissions")
            return handler._SENT
        lesson = ctx.get_lesson(task.get("lesson", ""))
        course = ctx.get_course(lesson.get("course", "")) if lesson else None
        students = {s["id"]: s for s in ctx.list_students()}
        subs_base = os.path.normpath(ctx._core.store.subs)
        buf = _io.BytesIO()
        seen = set()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for s in subs:
                folder = _folder(s, students, seen)
                for ver in s.get("versions", []):
                    for _fk, info in (ver.get("files") or {}).items():
                        if not (isinstance(info, dict) and info.get("файл")):
                            continue
                        rel = str(info["файл"]).replace("\\", "/")
                        p = os.path.normpath(
                            os.path.join(ctx._core.store.subs, rel))
                        try:
                            if os.path.commonpath([p, subs_base]) != subs_base:
                                continue
                        except ValueError:
                            continue
                        if not os.path.isfile(p):
                            continue
                        zf.write(p, "%s/v%d/%s" % (
                            folder, ver.get("n", 0), os.path.basename(rel)))
                zf.writestr("%s/отчёт.txt" % folder,
                            _report(task, lesson, course, s,
                                    students).encode("utf-8-sig"))
        data = buf.getvalue()
        fname = "работы-%s.zip" % _sanitize(task.get("title", tid))
        handler.send_response(200)
        handler.send_header("Content-Type", "application/zip")
        handler.send_header(
            "Content-Disposition",
            "attachment; filename*=UTF-8''" + urllib.parse.quote(fname))
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)
        ctx.audit("скачаны работы задания",
                  {"задание": tid, "название": task.get("title", ""),
                   "сдач": len(subs)}, handler=handler)
        return handler._SENT

    ctx.log("загружен: все работы архивом (кнопка на задании, /staff/works)")
