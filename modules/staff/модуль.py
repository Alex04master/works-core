# -*- coding: utf-8 -*-
"""Модуль «Панель преподавателя»: управление курсами, занятиями, заданиями, студентами."""
import json
import urllib.parse


TITLE = "Панель преподавателя"


def register(ctx):
    # ── ГЛАВНАЯ ─────────────────────────────────────────────────────
    @ctx.add_route("GET", "/staff", access="staff")
    def staff_home(handler, params):
        courses = ctx.list_courses()
        if not courses:
            body = (
                '<p class="hint">Нет курсов. Создайте первый курс.</p>'
                '<form method="post" action="/staff/new_course" class="staff-card">'
                '<h2>Создать курс</h2>'
                '<p><label>Название курса: <input type="text" name="title" required autofocus>'
                '</label></p>'
                '<p><button>Создать</button></p></form>')
            return _page(ctx, "Панель преподавателя", body)

        cards = ""
        dc = "return confirm('Удалить курс и все его данные?')"
        for c in courses:
            lessons = [l for l in ctx.list_lessons() if l.get("course") == c["id"]]
            tasks_count = sum(1 for t in ctx.list_tasks() if any(
                l.get("id") == t.get("lesson") for l in lessons))
            cards += (
                '<div class="staff-card">'
                '<h2><a href="/staff/course/%s">%s</a></h2>'
                '<p>%d занятий, %d заданий</p>'
                '<div class="staff-actions">'
                '<a href="/staff/course/%s" class="btn">Открыть</a>'
                ' <a href="/staff/delete/course/%s" class="btn btn-danger" '
                'onclick="%s">Удалить</a>'
                '</div></div>') % (
                    _e(c["id"]), _e(c.get("title", "")),
                    len(lessons), tasks_count,
                    _e(c["id"]), _e(c["id"]), dc)

        new_form = (
            '<details><summary>Создать курс</summary>'
            '<form method="post" action="/staff/new_course" class="staff-card">'
            '<p><label>Название: <input type="text" name="title" required></label></p>'
            '<p><button>Создать</button></p></form></details>')
        body = '<div class="staff-grid">%s</div>%s' % (cards, new_form)
        return _page(ctx, "Панель преподавателя", body)

    # ── Создать курс ─────────────────────────────────────────────────
    @ctx.add_route("POST", "/staff/new_course", access="staff")
    def new_course(handler, params):
        data = handler._parse_post()
        title = data.get("title", "").strip()
        if title:
            ctx.add_course(title)
        handler._redirect("/staff")
        return handler._SENT

    # ── Страница курса ───────────────────────────────────────────────
    @ctx.add_route("GET", "/staff/course/", access="staff")
    def course_page(handler, params):
        parts = params.get("_parts", [])
        cid = parts[0] if parts else ""
        course = ctx.get_course(cid)
        if not course:
            return _page(ctx, "Курс не найден", "<p>Такого курса нет.</p>")
        lessons = [l for l in ctx.list_lessons() if l.get("course") == cid]
        students = ctx.list_students()
        dc = "return confirm('Удалить занятие?')"
        ds = "return confirm('Удалить студента?')"

        rows = ""
        for l in lessons:
            tasks = [t for t in ctx.list_tasks() if t.get("lesson") == l["id"]]
            subs_count = sum(1 for t in tasks
                             for s in ctx.list_submissions(task_id=t["id"]))
            rows += (
                '<tr><td><a href="/staff/lesson/%s">%s</a></td>'
                '<td>%d</td><td>%d</td>'
                '<td><a href="/staff/delete/lesson/%s" class="btn btn-danger btn-sm" '
                'onclick="%s">X</a></td></tr>') % (
                    _e(l["id"]), _e(l.get("title", "")),
                    len(tasks), subs_count,
                    _e(l["id"]), dc)

        lesson_table = ""
        if lessons:
            lesson_table = (
                '<table class="staff-table">'
                '<tr><th>Занятие</th><th>Заданий</th><th>Сдач</th><th></th></tr>%s</table>') % rows

        student_rows = ""
        for s in students:
            student_rows += (
                '<tr><td>%s</td><td>%s</td>'
                '<td><a href="/staff/delete/student/%s" '
                'onclick="%s" class="btn btn-danger btn-sm">X</a></td></tr>') % (
                    _e(s["fio"]), _e(s.get("group", "")),
                    _e(s["id"]), ds)

        student_table = ""
        if students:
            student_table = (
                '<table class="staff-table">'
                '<tr><th>ФИО</th><th>Группа</th><th></th></tr>%s</table>') % student_rows

        body = (
            '<p><a href="/staff">Все курсы</a></p>'
            '<div class="staff-grid">'
            '<div class="staff-card">'
            '<h2>Занятия</h2>'
            + (lesson_table or '<p class="hint">Нет занятий.</p>') +
            '<details><summary>Создать занятие</summary>'
            '<form method="post" action="/staff/new_lesson">'
            '<input type="hidden" name="course" value="%s">'
            '<p><label>Название занятия: <input type="text" name="title" required></label></p>'
            '<p><button>Создать</button></p></form></details>'
            '</div>'
            '<div class="staff-card">'
            '<h2>Студенты (%d)</h2>'
            + (student_table or '<p class="hint">Нет студентов.</p>') +
            '<details><summary>Добавить студента</summary>'
            '<form method="post" action="/staff/add_student">'
            '<p><label>ФИО: <input type="text" name="fio" required></label></p>'
            '<p><label>Группа: <input type="text" name="group" placeholder="П-21"></label></p>'
            '<p><button>Добавить</button></p></form></details>'
            '</div></div>') % (_e(cid), len(students))
        return _page(ctx, course["title"], body)

    # ── Создать занятие ──────────────────────────────────────────────
    @ctx.add_route("POST", "/staff/new_lesson", access="staff")
    def new_lesson(handler, params):
        data = handler._parse_post()
        cid = data.get("course", "")
        title = data.get("title", "").strip()
        if title and ctx.get_course(cid):
            ctx.add_lesson(cid, title)
            handler._redirect("/staff/course/%s" % _e(cid))
        else:
            handler._redirect("/staff")
        return handler._SENT

    # ── Добавить студента ────────────────────────────────────────────
    @ctx.add_route("POST", "/staff/add_student", access="staff")
    def add_student(handler, params):
        data = handler._parse_post()
        fio = data.get("fio", "").strip()
        group = data.get("group", "").strip()
        if fio:
            ctx.add_student(fio, group)
        handler._redirect(handler.headers.get("Referer", "/staff"))
        return handler._SENT

    # ── Страница занятия ─────────────────────────────────────────────
    @ctx.add_route("GET", "/staff/lesson/", access="staff")
    def lesson_page(handler, params):
        parts = params.get("_parts", [])
        lid = parts[0] if parts else ""
        lesson = ctx.get_lesson(lid)
        if not lesson:
            return _page(ctx, "Занятие не найдено", "<p>Такого занятия нет.</p>")
        course = ctx.get_course(lesson.get("course", ""))
        tasks = [t for t in ctx.list_tasks() if t.get("lesson") == lid]
        dc = "return confirm('Удалить задание?')"

        rows = ""
        for t in tasks:
            subs = ctx.list_submissions(task_id=t["id"])
            submitted = sum(1 for s in subs if s.get("status") == "сдано")
            accepted = sum(1 for s in subs if s.get("status") == "принято")
            rows += (
                '<tr><td><a href="/staff/task/%s">%s</a></td>'
                '<td>%d</td><td>%d</td>'
                '<td><a href="/staff/delete/task/%s" class="btn btn-danger btn-sm" '
                'onclick="%s">X</a></td></tr>') % (
                    _e(t["id"]), _e(t.get("title", "")),
                    submitted, accepted,
                    _e(t["id"]), dc)

        body = (
            '<p><a href="/staff/course/%s">%s</a></p>'
            '<table class="staff-table"><tr><th>Задание</th><th>Сдано</th>'
            '<th>Принято</th><th></th></tr>%s</table>'
            '<details><summary>Создать задание</summary>'
            '<form method="post" action="/staff/new_task" class="staff-card">'
            '<input type="hidden" name="lesson" value="%s">'
            '<p><label>Название: <input type="text" name="title" required></label></p>'
            '<p><label>Описание (Markdown):<br>'
            '<textarea name="description" rows="5"></textarea></label></p>'
            '<p><button>Создать</button></p></form></details>') % (
                _e(lesson.get("course", "")),
                _e(course["title"] if course else ""),
                rows, _e(lid))
        return _page(ctx, lesson["title"], body)

    # ── Создать задание ──────────────────────────────────────────────
    @ctx.add_route("POST", "/staff/new_task", access="staff")
    def new_task(handler, params):
        data = handler._parse_post()
        lid = data.get("lesson", "")
        title = data.get("title", "").strip()
        desc = data.get("description", "").strip()
        if title and ctx.get_lesson(lid):
            ctx.add_task(lid, title, desc)
            handler._redirect("/staff/lesson/%s" % _e(lid))
        else:
            handler._redirect("/staff")
        return handler._SENT

    # ── Страница задания ─────────────────────────────────────────────
    @ctx.add_route("GET", "/staff/task/", access="staff")
    def task_page(handler, params):
        parts = params.get("_parts", [])
        tid = parts[0] if parts else ""
        task = ctx.get_task(tid)
        if not task:
            return _page(ctx, "Задание не найдено", "<p>Такого задания нет.</p>")
        lesson = ctx.get_lesson(task.get("lesson", ""))
        subs = ctx.list_submissions(task_id=tid)

        sub_rows = ""
        for s in subs:
            student = ctx.get_student(s.get("student", ""))
            v = s.get("versions", [{}])[-1]
            status = s.get("status", "сдано")
            icons = {"сдано": "сдано", "принято": "принято",
                     "доработка": "доработка", "отклонено": "отклонено"}
            icon = icons.get(status, status)
            sub_rows += (
                '<tr><td>%s</td><td>%s</td><td>v%d</td><td>%s</td>'
                '<td><a href="/staff/sub/%s__%s" class="btn btn-sm">Открыть</a></td></tr>') % (
                    _e(student["fio"] if student else "?"),
                    icon, v.get("n", 0), v.get("time", ""),
                    _e(tid), _e(s["student"]))

        form_json = json.dumps(task.get("форма", []),
                               ensure_ascii=False, indent=2)

        body = (
            '<p><a href="/staff/lesson/%s">%s</a></p>'
            '<div class="staff-card">'
            '<h2>Форма задания (JSON)</h2>'
            '<pre>%s</pre>'
            '<details><summary>Редактировать форму</summary>'
            '<form method="post" action="/staff/edit_task/%s" class="staff-card">'
            '<p><label>Название: <input type="text" name="title" value="%s"></label></p>'
            '<p><label>Описание:<br><textarea name="description" rows="6">'
            '%s</textarea></label></p>'
            '<p><label>Форма (JSON):<br><textarea name="form_json" rows="8">'
            '%s</textarea></label></p>'
            '<p><button>Сохранить</button></p></form></details>'
            '</div>'
            '<h2>Сдачи (%d)</h2>'
            '<table class="staff-table"><tr><th>Студент</th><th>Статус</th>'
            '<th>Версия</th><th>Время</th><th></th></tr>%s</table>') % (
                _e(task.get("lesson", "")),
                _e(lesson["title"] if lesson else ""),
                _e(form_json),
                _e(tid),
                _e(task.get("title", "")),
                _e(task.get("описание", "")),
                _e(form_json),
                len(subs), sub_rows)
        return _page(ctx, task.get("title", ""), body)

    # ── Редактировать задание ────────────────────────────────────────
    @ctx.add_route("POST", "/staff/edit_task/", access="staff")
    def edit_task(handler, params):
        parts = params.get("_parts", [])
        tid = parts[0] if parts else ""
        task = ctx.get_task(tid)
        if not task:
            handler._redirect("/staff")
            return handler._SENT
        data = handler._parse_post()
        title = data.get("title", "").strip()
        desc = data.get("description", "").strip()
        form_raw = data.get("form_json", "").strip()
        form = []
        if form_raw:
            try:
                form = json.loads(form_raw)
                if not isinstance(form, list):
                    form = [form]
            except json.JSONDecodeError:
                pass
        ctx.update_task(tid,
                        title=title or task["title"],
                        description=desc or task.get("описание", ""),
                        form=form)
        handler._redirect("/staff/task/%s" % _e(tid))
        return handler._SENT

    # ── Страница сдачи ───────────────────────────────────────────────
    @ctx.add_route("GET", "/staff/sub/", access="staff")
    def sub_page(handler, params):
        parts = params.get("_parts", [])
        full_key = parts[0] if parts else ""
        if "__" not in full_key:
            return _page(ctx, "Неверный ключ", "<p>Неверный формат.</p>")
        tid, sid = full_key.split("__", 1)
        task = ctx.get_task(tid)
        student = ctx.get_student(sid)
        sub = ctx.get_submission(tid, sid)
        if not sub:
            return _page(ctx, "Сдача не найдена", "<p>Такой сдачи нет.</p>")

        v = sub.get("versions", [{}])[-1]
        answers = v.get("answers", {})
        status = sub.get("status", "сдано")

        answer_rows = ""
        for fd in (task.get("форма", []) if task else []):
            key = fd.get("ключ", "")
            val = answers.get(key, "")
            if not val and key not in answers:
                continue
            q = fd.get("вопрос") or key
            answer_rows += '<tr><td>%s</td><td>%s</td></tr>' % (
                _e(q), _e(str(val)[:200]))

        verdict_form = (
            '<form method="post" action="/staff/verdict" class="staff-card">'
            '<input type="hidden" name="key" value="%s">'
            '<h2>Вердикт</h2>'
            '<p><label>Решение: <select name="verdict">'
            '<option value="Принято">Принято</option>'
            '<option value="Принято с замечаниями">Принято с замечаниями</option>'
            '<option value="На доработку">На доработку</option>'
            '<option value="Не принято">Не принято</option>'
            '</select></label></p>'
            '<p><label>Балл: <input type="number" name="score" step="0.5" '
            'min="0" max="100" value="%s"></label></p>'
            '<p><label>Комментарий:<br><textarea name="comment" rows="3" '
            'placeholder="Замечания и рекомендации...">%s</textarea></label></p>'
            '<p><button>Применить вердикт</button></p></form>') % (
                _e(full_key),
                str(v.get("score") or ""),
                _e(v.get("comment", "")))

        status_info = '<div class="sub-status"><h3>Статус: %s</h3>' % status
        if v.get("verdict"):
            score_str = (" Балл: " + str(v.get("score", ""))
                         if v.get("score") else "")
            status_info += (
                '<p>Вердикт: %s%s</p><p>%s</p>') % (
                    _e(v["verdict"]), score_str, _e(v.get("comment", "")))
        status_info += "</div>"

        body = (
            '<p><a href="/staff/task/%s">%s</a></p>'
            '<div class="staff-card"><h2>%s</h2>'
            '<p>Версия %d, %s</p>%s</div>'
            '<h2>Ответы</h2>'
            '<table class="staff-table"><tr><th>Поле</th><th>Ответ</th></tr>'
            '%s</table>%s') % (
                _e(tid),
                _e(task["title"] if task else ""),
                _e(student["fio"] if student else "?"),
                v.get("n", 0), v.get("time", ""),
                status_info, answer_rows, verdict_form)
        return _page(ctx, "Сдача: %s" % (student["fio"] if student else "?"), body)

    # ── Вердикт ──────────────────────────────────────────────────────
    @ctx.add_route("POST", "/staff/verdict", access="staff")
    def set_verdict(handler, params):
        data = handler._parse_post()
        key = data.get("key", "")
        verdict = data.get("verdict", "")
        score = data.get("score", "").strip()
        comment = data.get("comment", "").strip()
        if "__" not in key or not verdict:
            handler._redirect("/staff")
            return handler._SENT
        tid, sid = key.split("__", 1)
        score_val = float(score) if score else None
        ctx.set_verdict(tid, sid, verdict, score_val, comment)
        handler._redirect("/staff/sub/%s" % _e(key))
        return handler._SENT

    # ── Удаление курса ───────────────────────────────────────────────
    @ctx.add_route("GET", "/staff/delete/course/", access="staff")
    def delete_course(handler, params):
        parts = params.get("_parts", [])
        cid = parts[0] if parts else ""
        ctx.delete_course(cid)
        handler._redirect("/staff")
        return handler._SENT

    @ctx.add_route("GET", "/staff/delete/lesson/", access="staff")
    def delete_lesson(handler, params):
        parts = params.get("_parts", [])
        lid = parts[0] if parts else ""
        lesson = ctx.get_lesson(lid)
        cid = lesson.get("course", "") if lesson else ""
        ctx.delete_lesson(lid)
        handler._redirect("/staff/course/%s" % _e(cid) if cid else "/staff")
        return handler._SENT

    @ctx.add_route("GET", "/staff/delete/task/", access="staff")
    def delete_task(handler, params):
        parts = params.get("_parts", [])
        tid = parts[0] if parts else ""
        task = ctx.get_task(tid)
        lid = task.get("lesson", "") if task else ""
        ctx._core.db["задания"] = [t for t in ctx._core.db["задания"]
                                   if t.get("id") != tid]
        ctx._core.store.save()
        handler._redirect("/staff/lesson/%s" % _e(lid))
        return handler._SENT

    @ctx.add_route("GET", "/staff/delete/student/", access="staff")
    def delete_student(handler, params):
        parts = params.get("_parts", [])
        sid = parts[0] if parts else ""
        ctx.delete_student(sid)
        ref = handler.headers.get("Referer", "/staff")
        handler._redirect(ref)
        return handler._SENT

    ctx.log("загружен: панель преподавателя")


def _page(ctx, title, body):
    return ctx.render_page(title, body, staff=True)


def _e(v):
    import html as _html
    return _html.escape(str(v) if v is not None else "", quote=True)
