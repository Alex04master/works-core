# -*- coding: utf-8 -*-
"""Модуль «Панель преподавателя»: управление курсами, занятиями, заданиями, студентами."""
import json
import urllib.parse
from datetime import datetime


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
                ' <a href="/staff/export/course/%s" class="btn btn-secondary">CSV</a>'
                ' <a href="/staff/delete/course/%s" class="btn btn-danger" '
                'onclick="%s">Удалить</a>'
                '</div></div>') % (
                    _e(c["id"]), _e(c.get("title", "")),
                    len(lessons), tasks_count,
                    _e(c["id"]), _e(c["id"]), _e(c["id"]), dc)

        new_form = (
            '<details><summary>Создать курс</summary>'
            '<form method="post" action="/staff/new_course" class="staff-card">'
            '<p><label>Название: <input type="text" name="title" required></label></p>'
            '<p><button>Создать</button></p></form></details>')
        course_opts = "".join(
            '<option value="%s">%s</option>'
            % (_e(c["id"]), _e(c.get("title", "")))
            for c in courses)
        import_card = (
            '<details><summary>📥 Импорт группы</summary>'
            '<form method="post" action="/staff/import_group" '
            'enctype="multipart/form-data" class="staff-card">'
            '<p><label>Курс: <select name="course">%s</select></label></p>'
            '<p><label>Название группы: '
            '<input type="text" name="group" placeholder="П-21"></label></p>'
            '<p><label>Файл .txt с ФИО (по одному на строку): '
            '<input type="file" name="file" accept=".txt,.csv,text/plain"></label></p>'
            '<p><label>Или вставьте список:<br>'
            '<textarea name="text" rows="5" '
            'placeholder="Иванов И.И.&#10;Петров П.П."></textarea></label></p>'
            '<p><button>Импортировать</button></p></form></details>'
        ) % course_opts
        body = ('<div class="staff-grid">%s</div>%s%s'
                '<p class="hint"><a href="/staff/password">🔑 Сменить пароль</a>'
                ' · <a href="/staff/scenarios">🎬 Сценарии</a></p>'
                ) % (cards, new_form, import_card)
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
            brig = (s.get("бригада") or "").strip()
            brig_cell = ('<span class="team-badge">👥 %s</span>' % _e(brig)
                         if brig else "—")
            student_rows += (
                '<tr><td>%s</td><td>%s</td><td>%s</td>'
                '<td><a href="/staff/delete/student/%s" '
                'onclick="%s" class="btn btn-danger btn-sm">X</a></td></tr>') % (
                    _e(s["fio"]), _e(s.get("group", "")), brig_cell,
                    _e(s["id"]), ds)

        student_table = ""
        if students:
            student_table = (
                '<table class="staff-table">'
                '<tr><th>ФИО</th><th>Группа</th><th>Бригада</th>'
                '<th></th></tr>%s</table>') % student_rows

        enrolled = set(course.get("студенты") or [])
        enroll_rows = ""
        for s in students:
            in_course = s["id"] in enrolled
            enroll_rows += (
                '<tr><td>%s</td><td>%s</td><td>%s</td>'
                '<td><form method="post" action="/staff/enroll" '
                'style="display:inline">'
                '<input type="hidden" name="course" value="%s">'
                '<input type="hidden" name="student" value="%s">'
                '<input type="hidden" name="act" value="%s">'
                '<button>%s</button></form></td></tr>') % (
                    _e(s["fio"]), _e(s.get("group", "")),
                    "✅" if in_course else "—",
                    _e(cid), _e(s["id"]),
                    "off" if in_course else "on",
                    "Отчислить" if in_course else "Зачислить")
        enroll_card = (
            '<div class="staff-card"><h2>Зачисление</h2>'
            '<p class="hint">Зачислено: %d из %d. Если никого не зачислять '
            'и не задать группы — курс открыт всем.</p>'
            '<table class="staff-table"><tr><th>ФИО</th><th>Группа</th>'
            '<th>В курсе</th><th></th></tr>%s</table>'
            '<form method="post" action="/staff/enroll_all">'
            '<input type="hidden" name="course" value="%s">'
            '<p><button>Зачислить всех</button></p></form>'
            '</div>') % (len(enrolled), len(students), enroll_rows, _e(cid))

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
            '<p><label>Бригада: <input type="text" name="brigade" '
            'placeholder="Бригада-1"></label></p>'
            '<p><button>Добавить</button></p></form></details>'
            '</div>')
        import_form = (
            '<details><summary>📥 Импорт группы</summary>'
            '<form method="post" action="/staff/import_group" '
            'enctype="multipart/form-data" class="staff-card">'
            '<input type="hidden" name="course" value="%s">'
            '<p><label>Название группы: '
            '<input type="text" name="group" placeholder="П-21"></label></p>'
            '<p><label>Файл .txt с ФИО (по одному на строку): '
            '<input type="file" name="file" accept=".txt,.csv,text/plain"></label></p>'
            '<p><label>Или вставьте список:<br>'
            '<textarea name="text" rows="5" '
            'placeholder="Иванов И.И.&#10;Петров П.П."></textarea></label></p>'
            '<p><button>Импортировать</button></p>'
            '<p class="hint">Один студент в строке — просто ФИО. Расширенный '
            'формат: «ФИО;Группа;Бригада» — второй и третий столбцы '
            'необязательны (бригада объединяет студентов, отчёт один на '
            'всех). Строки с # — комментарии, дубликаты пропускаются.</p>'
            '</form></details>') % _e(cid)
        groups_list = course.get("группы") or []
        group_rows = ""
        for g in groups_list:
            group_rows += (
                '<p>👥 <b>%s</b> <form method="post" '
                'action="/staff/course_group" style="display:inline">'
                '<input type="hidden" name="course" value="%s">'
                '<input type="hidden" name="group" value="%s">'
                '<input type="hidden" name="act" value="off">'
                '<button class="btn-sm btn-danger" '
                'title="Закрыть доступ группе">✕</button></form></p>'
            ) % (_e(g), _e(cid), _e(g))
        if groups_list:
            groups_status = (
                '<p class="hint">Курс видят только перечисленные группы '
                '(плюс зачисленные индивидуально).</p>')
        elif course.get("студенты"):
            groups_status = (
                '<p class="hint">Индивидуальное зачисление: %d чел.</p>'
                % len(course.get("студенты") or []))
        else:
            groups_status = ('<p class="hint">Курс открыт всем. Добавьте '
                             'группы — и его увидят только они.</p>')
        groups_card = (
            '<div class="staff-card"><h2>🏫 Доступ группам</h2>'
            '%s%s'
            '<form method="post" action="/staff/course_group">'
            '<input type="hidden" name="course" value="%s">'
            '<input type="hidden" name="act" value="add">'
            '<p><label>Группа: <input type="text" name="group" '
            'placeholder="П-21" required></label></p>'
            '<p><button>Открыть группе</button></p></form></div>'
        ) % (group_rows, groups_status, _e(cid))
        bmax = ctx.brigade_max(cid)
        teams = {}
        for s in ctx.list_students():
            b = (s.get("бригада") or "").strip()
            if b:
                teams.setdefault(b, []).append(s.get("fio", ""))
        team_rows = "".join(
            '<li>👥 <b>%s</b> — %d чел.: %s</li>'
            % (_e(b), len(m), _e(", ".join(m)))
            for b, m in sorted(teams.items())) or \
            '<li class="hint">Пока нет бригад.</li>'
        brigade_card = (
            '<div class="staff-card"><h2>👷 Бригады</h2>'
            '<p class="hint">Названия бригад придумывают студенты и вступают '
            'сами — на странице курса. Максимальный состав назначаете вы.</p>'
            '<ul>%s</ul>'
            '<form method="post" action="/staff/brigade_max">'
            '<input type="hidden" name="course" value="%s">'
            '<p><label>Максимальный состав бригады: '
            '<input type="number" name="max" value="%d" min="1" max="20" '
            'required></label></p>'
            '<p><button>Сохранить</button></p></form></div>'
        ) % (team_rows, _e(cid), bmax)
        body = body.replace("</div></div>",
                            "</div>" + groups_card + brigade_card + enroll_card +
                            import_form + "</div>", 1)

        qs = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
        imp = (qs.get("imp") or [""])[0]
        if imp:
            body = ('<div class="sub-status"><p>Импорт группы: добавлено %s.</p></div>'
                    % _e(imp.replace("/", ", пропущено дубликатов: "))) + body
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
        brigade = data.get("brigade", "").strip()
        if fio:
            ctx.add_student(fio, group, brigade)
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
            '<p><label>Срок сдачи (необязательно): '
            '<input type="text" name="deadline" placeholder="2026-12-31 18:00">'
            '</label></p>'
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
        dl = data.get("deadline", "").strip()
        if title and ctx.get_lesson(lid):
            ctx.add_task(lid, title, desc,
                         settings={"срок": dl} if dl else None)
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
            if v.get("просрочено"):
                icon += " ⏰"
            sub_rows += (
                '<tr><td>%s</td><td>%s</td><td>v%d</td><td>%s</td>'
                '<td><a href="/staff/sub/%s__%s" class="btn btn-sm">Открыть</a></td></tr>') % (
                    _e(student["fio"] if student else "?"),
                    icon, v.get("n", 0), v.get("time", ""),
                    _e(tid), _e(s["student"]))

        form_json = json.dumps(task.get("форма", []),
                               ensure_ascii=False, indent=2)
        dl = _parse_dl((task.get("настройки") or {}).get("срок"))
        dl_info = ""
        if dl:
            dl_info = ('<p>⏰ Срок сдачи: %s%s</p>' % (
                _e(dl.strftime("%d.%m.%Y %H:%M")),
                ' <span class="state-сбой">(истёк)</span>'
                if datetime.now() > dl else ""))

        issued_val = task.get("выдано")
        issued_set = set(issued_val) if isinstance(issued_val, list) else None
        is_scenario = bool((task.get("настройки") or {}).get("план"))
        brigades = sorted({(s.get("бригада") or "").strip()
                           for s in ctx.list_students()
                           if (s.get("бригада") or "").strip()})
        brig_rows = "".join(
            '<label class="cb-label"><input type="checkbox" name="brigade" '
            'value="%s"%s> 👥 %s</label>' % (
                _e(b), " checked" if issued_set and b in issued_set else "",
                _e(b))
            for b in brigades) or \
            '<p class="hint">Бригад пока нет — студенты регистрируют их на странице курса.</p>'
        if issued_set is None and is_scenario:
            status_html = ('<p class="reason">⏳ Сценарное задание ещё не '
                           'выдано — студенты его не видят. Отметьте бригады '
                           'или «выдать всем».</p>')
        elif issued_set is None:
            status_html = '<p class="hint">Обычное задание — видно всем.</p>'
        elif not issued_set:
            status_html = '<p class="hint">✅ Выдано всем студентам курса.</p>'
        else:
            status_html = ('<p class="hint">Выдано бригадам: %s.</p>'
                           % _e(", ".join(sorted(issued_set))))
        all_checked = " checked" if issued_set is not None and not issued_set else ""
        issue_card = (
            '<form method="post" action="/staff/task_issue" class="staff-card">'
            '<h2>📤 Выдача бригадам</h2>'
            '%s'
            '<p class="hint">Отметьте бригады, которым выдано задание.</p>'
            '%s'
            '<p><label class="cb-label"><input type="checkbox" name="all"%s> '
            'Выдать всем</label></p>'
            '<p><button>Сохранить выдачу</button></p></form>'
        ) % (status_html, brig_rows, all_checked)
        body = (
            '<p><a href="/staff/lesson/%s">%s</a></p>'
            '<div class="staff-card">'
            '%s'
            '<h2>Форма задания (JSON)</h2>'
            '<pre>%s</pre>'
            '<details><summary>Редактировать форму</summary>'
            '<form method="post" action="/staff/edit_task/%s" class="staff-card">'
            '<p><label>Название: <input type="text" name="title" value="%s"></label></p>'
            '<p><label>Срок сдачи (необязательно): '
            '<input type="text" name="deadline" value="%s" '
            'placeholder="2026-12-31 18:00"></label></p>'
            '<p><label>Описание:<br><textarea name="description" rows="6">'
            '%s</textarea></label></p>'
            '<p><label>Форма (JSON):<br><textarea name="form_json" rows="8">'
            '%s</textarea></label></p>'
            '<p><button>Сохранить</button></p></form></details>'
            '</div>'
            '<h2>Сдачи (%d)</h2>'
            '<table class="staff-table"><tr><th>Студент</th><th>Статус</th>'
            '<th>Версия</th><th>Время</th><th></th></tr>%s</table>'
            '%s') % (
                _e(task.get("lesson", "")),
                _e(lesson["title"] if lesson else ""),
                dl_info,
                _e(form_json),
                _e(tid),
                _e(task.get("title", "")),
                _e((task.get("настройки") or {}).get("срок", "")),
                _e(task.get("описание", "")),
                _e(form_json),
                len(subs), sub_rows, issue_card)
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
        form = None  # пустое поле — форму не трогаем
        if form_raw:
            try:
                form = json.loads(form_raw)
                if not isinstance(form, list):
                    form = [form]
            except json.JSONDecodeError:
                pass
        settings = dict(task.get("настройки") or {})
        dl = data.get("deadline", "").strip()
        if dl:
            settings["срок"] = dl
        else:
            settings.pop("срок", None)
        ctx.update_task(tid,
                        title=title or task["title"],
                        description=desc or task.get("описание", ""),
                        form=form,
                        settings=settings)
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

        versions = sub.get("versions", [])
        v = versions[-1] if versions else {}
        if len(parts) > 1 and parts[1].startswith("v") and parts[1][1:].isdigit():
            for x in versions:
                if x.get("n") == int(parts[1][1:]):
                    v = x
                    break
        answers = v.get("answers", {})
        status = sub.get("status", "сдано")

        answer_rows = ""
        for fd in (task.get("форма", []) if task else []):
            key = fd.get("ключ", "")
            if fd.get("тип") in ("file", "hidden"):
                continue
            val = answers.get(key, "")
            if not val and key not in answers:
                continue
            q = fd.get("вопрос") or key
            answer_rows += '<tr><td>%s</td><td>%s</td></tr>' % (
                _e(q), _e(str(val)[:200]))
        _pd = answers.get("plan_data") or ""
        if _pd:
            import json as _json
            try:
                _dev = _json.loads(_pd)
                _cnt = {}
                for _x in (_dev if isinstance(_dev, list) else []):
                    if isinstance(_x, dict) and _x.get("t"):
                        _cnt[_x["t"]] = _cnt.get(_x["t"], 0) + 1
                _sum = ", ".join("%s × %d" % (k, n)
                                 for k, n in sorted(_cnt.items()))
                answer_rows += (
                    '<tr><td>Интерактивный план</td>'
                    '<td>Устройств: %d%s '
                    '<a href="/plan/%s?sub=%s&amp;v=%d" target="_blank">'
                    'Смотреть план</a></td></tr>') % (
                        len(_dev) if isinstance(_dev, list) else 0,
                        (" — " + _e(_sum)) if _sum else "",
                        _e(tid), _e(full_key), v.get("n", 1))
            except ValueError:
                pass

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

        vlinks = " ".join(
            '<a href="/staff/sub/%s/v%d"%s>v%d</a>' % (
                _e(full_key), x.get("n", 0),
                ' style="font-weight:700"' if x is v else "",
                x.get("n", 0))
            for x in versions)
        files_html = ""
        fl = v.get("files") or {}
        if isinstance(fl, dict) and fl:
            frows = ""
            for fkey in sorted(fl):
                info = fl[fkey] or {}
                url = "/_subfile/%s/v%d/%s" % (full_key, v.get("n", 0), fkey)
                size = info.get("размер", "")
                size_s = ("%d байт" % size) if isinstance(size, int) else ""
                frows += ('<tr><td><code>%s</code></td>'
                          '<td><a href="%s">%s</a></td><td>%s</td></tr>') % (
                    _e(fkey), _e(url), _e(info.get("имя", fkey)), _e(size_s))
            files_html = ('<h2>Файлы</h2>'
                          '<table class="staff-table"><tr><th>Поле</th>'
                          '<th>Файл</th><th>Размер</th></tr>%s</table>') % frows
        elif isinstance(fl, list) and fl:
            files_html = '<h2>Файлы</h2><p>%s</p>' % _e(
                ", ".join(str(x) for x in fl))

        late_s = " ⏰ сдано после срока" if v.get("просрочено") else ""
        body = (
            '<p><a href="/staff/task/%s">%s</a></p>'
            '<div class="staff-card"><h2>%s</h2>'
            '<p>Версия %d, %s%s</p>'
            '<p class="hint">Версии: %s</p>%s</div>'
            '<h2>Ответы</h2>'
            '<table class="staff-table"><tr><th>Поле</th><th>Ответ</th></tr>'
            '%s</table>%s%s') % (
                _e(tid),
                _e(task["title"] if task else ""),
                _e(student["fio"] if student else "?"),
                v.get("n", 0), v.get("time", ""), late_s,
                vlinks or "-", status_info,
                answer_rows, files_html, verdict_form)
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

    # ── Выдача задания бригадам ──────────────────────────────────────
    @ctx.add_route("POST", "/staff/task_issue", access="staff")
    def task_issue(handler, params):
        data = handler._parse_post()
        tid = data.get("task", "")
        if not ctx.get_task(tid):
            handler._redirect("/staff")
            return handler._SENT
        if data.get("all"):
            ctx.task_set_issue(tid, [])
        else:
            brs = data.get("brigade") or []
            if isinstance(brs, str):
                brs = [brs]
            ctx.task_set_issue(tid, brs)
        handler._redirect("/staff/task/%s" % _e(tid))
        return handler._SENT

    # ── Максимальный состав бригад ───────────────────────────────────
    @ctx.add_route("POST", "/staff/brigade_max", access="staff")
    def brigade_max(handler, params):
        data = handler._parse_post()
        cid = data.get("course", "")
        if cid:
            ctx.set_brigade_max(cid, data.get("max", 0))
        handler._redirect("/staff/course/%s" % _e(cid))
        return handler._SENT

    # ── Доступ курса группам ─────────────────────────────────────────
    @ctx.add_route("POST", "/staff/course_group", access="staff")
    def course_group(handler, params):
        data = handler._parse_post()
        cid = data.get("course", "")
        group = data.get("group", "").strip()
        act = data.get("act", "add")
        if cid and group:
            if act == "off":
                ctx.course_group_remove(cid, group)
            else:
                ctx.course_group_add(cid, group)
        handler._redirect("/staff/course/%s" % _e(cid))
        return handler._SENT

    # ── Смена пароля ─────────────────────────────────────────────────
    @ctx.add_route("GET", "/staff/password", access="staff")
    def password_page(handler, params):
        srv = handler._server_inst
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
        msg = ""
        if (qs.get("ok") or [""])[0]:
            msg = '<div class="sub-status"><p>Пароль изменён.</p></div>'
        elif (qs.get("err") or [""])[0]:
            e = (qs.get("err") or [""])[0]
            texts = {"old": "Текущий пароль неверен.",
                     "short": "Новый пароль слишком короткий (минимум 4 символа).",
                     "match": "Пароли не совпадают."}
            msg = '<div class="error"><p>%s</p></div>' % _e(texts.get(e, "Ошибка."))
        if getattr(srv, "no_pass", False):
            body = ('<p><a href="/staff">Панель</a></p>'
                    '<div class="notice">Сервер запущен с --no-pass: вход по '
                    'паролю отключён. Перезапустите сервер с паролем, чтобы '
                    'включить его.</div>')
        else:
            body = ('<p><a href="/staff">Панель</a></p>' + msg +
                    '<form method="post" action="/staff/password" '
                    'class="staff-card">'
                    '<h2>Сменить пароль</h2>'
                    '<p><label>Текущий пароль: '
                    '<input type="password" name="old" required></label></p>'
                    '<p><label>Новый пароль (минимум 4 символа): '
                    '<input type="password" name="new" required minlength="4">'
                    '</label></p>'
                    '<p><label>Повторите новый пароль: '
                    '<input type="password" name="new2" required></label></p>'
                    '<p><button>Сменить пароль</button></p>'
                    '</form>')
        return _page(ctx, "Сменить пароль", body)

    @ctx.add_route("POST", "/staff/password", access="staff")
    def password_post(handler, params):
        srv = handler._server_inst
        data = handler._parse_post()
        old = data.get("old", "")
        new = data.get("new", "")
        new2 = data.get("new2", "")
        if not srv.check_password(old):
            handler._redirect("/staff/password?err=old")
            return handler._SENT
        if len(new) < 4:
            handler._redirect("/staff/password?err=short")
            return handler._SENT
        if new != new2:
            handler._redirect("/staff/password?err=match")
            return handler._SENT
        srv.set_password(new)
        handler._redirect("/staff/password?ok=1")
        return handler._SENT

    # ── Импорт группы ────────────────────────────────────────────────
    @ctx.add_route("POST", "/staff/import_group", access="staff")
    def import_group(handler, params):
        data = handler._parse_post()
        cid = data.get("course", "")
        if not ctx.get_course(cid):
            handler._redirect("/staff")
            return handler._SENT
        up = data.get("file")
        gdef = data.get("group", "").strip()
        text = ""
        if up is not None and hasattr(up, "data") and up.data:
            try:
                text = up.data.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = up.data.decode("cp1251", "replace")
        if not text:
            text = data.get("text", "")

        existing = {(s.get("fio", ""), s.get("group", ""))
                    for s in ctx.list_students()}
        added = skipped = 0
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ";" in line:
                parts = line.split(";")
            elif "\t" in line:
                parts = line.split("\t")
            elif "," in line:
                parts = line.split(",")
            else:
                parts = [line]
            fio = parts[0].strip()
            grp = parts[1].strip() if len(parts) > 1 else ""
            brig = parts[2].strip() if len(parts) > 2 else ""
            grp = grp or gdef
            if not fio:
                continue
            if (fio, grp) in existing:
                skipped += 1
                continue
            ctx.add_student(fio, grp, brig)
            existing.add((fio, grp))
            added += 1
        handler._redirect("/staff/course/%s?imp=%d/%d" % (_e(cid), added, skipped))
        return handler._SENT

    # ── Зачисление на курс ───────────────────────────────────────────
    @ctx.add_route("POST", "/staff/enroll", access="staff")
    def enroll_student(handler, params):
        data = handler._parse_post()
        cid = data.get("course", "")
        sid = data.get("student", "")
        if cid and sid:
            if data.get("act") == "off":
                ctx.unenroll(cid, sid)
            else:
                ctx.enroll(cid, sid)
        handler._redirect("/staff/course/%s" % _e(cid))
        return handler._SENT

    @ctx.add_route("POST", "/staff/enroll_all", access="staff")
    def enroll_all(handler, params):
        data = handler._parse_post()
        cid = data.get("course", "")
        if ctx.get_course(cid):
            for s in ctx.list_students():
                ctx.enroll(cid, s["id"])
        handler._redirect("/staff/course/%s" % _e(cid))
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
        ctx.delete_task(tid)
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


def _parse_dl(value):
    """Строка срока -> datetime или None (те же форматы, что в ядре)."""
    if not value:
        return None
    s = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
                "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None
