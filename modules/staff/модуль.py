# -*- coding: utf-8 -*-
"""Модуль «Панель преподавателя»: управление курсами, занятиями, заданиями, студентами."""
import json
import urllib.parse
from datetime import datetime


TITLE = "Панель преподавателя"


def register(ctx):
    def _extra_cards(event, **kw):
        """HTML-фрагменты от модулей-подписчиков (кнопки, карточки)."""
        try:
            parts = ctx.emit(event, **kw)
        except Exception:
            parts = []
        return "".join(str(p) for p in parts if p)

    # ── Очередь проверки ─────────────────────────────────────────────
    def _pending_queue():
        """Сдачи, у которых последняя версия ещё без вердикта."""
        items = []
        for s in ctx.list_submissions():
            vers = s.get("versions") or []
            if not vers or vers[-1].get("verdict"):
                continue
            t = ctx.get_task(s.get("task", ""))
            if not t:
                continue
            les = ctx.get_lesson(t.get("lesson", ""))
            course = ctx.get_course(les.get("course", "")) if les else None
            brig = (s.get("бригада") or "").strip()
            if brig:
                who = "👥 " + brig
            else:
                st = ctx.get_student(s.get("student", ""))
                who = st["fio"] if st else "?"
            items.append({
                "key": s.get("key", ""),
                "task": t.get("title", ""),
                "course": (course or {}).get("title", ""),
                "who": who,
                "time": str(vers[-1].get("time") or ""),
                "late": bool(vers[-1].get("просрочено")),
            })
        items.sort(key=lambda d: d["time"], reverse=True)
        return items

    def _queue_html():
        items = _pending_queue()
        if not items:
            return ""
        n = len(items)
        rows = ""
        for it in items[:10]:
            rows += (
                '<tr><td>%s%s</td><td>%s%s</td><td>%s</td>'
                '<td><a class="btn btn-sm" href="/staff/sub/%s">'
                'Проверить</a></td></tr>'
            ) % (_e(it["who"]), " ⏰" if it["late"] else "",
                 _e(it["task"]),
                 ('<div class="reason">%s</div>' % _e(it["course"]))
                 if it["course"] else "",
                 _e(it["time"]), _e(it["key"]))
        more = ""
        if n > 10:
            more = ('<p class="hint">Показаны последние 10, всего '
                    'не проверено: %d.</p>') % n
        return (
            '<div class="staff-card queue-card">'
            '<h2>⚠️ Требуют проверки: %d</h2>'
            '<table class="staff-table">'
            '<tr><th>Кто сдал</th><th>Задание</th><th>Когда</th>'
            '<th></th></tr>%s</table>%s</div>') % (n, rows, more)

    # ── ГЛАВНАЯ ─────────────────────────────────────────────────────
    @ctx.add_route("GET", "/staff", access="staff")
    def staff_home(handler, params):
        courses = ctx.list_courses()
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
        err = (qs.get("err") or [""])[0]
        err_msg = ('<div class="error"><p>Импорт курса не удался: %s</p></div>'
                   % _e(err)) if err else ""
        if not courses:
            body = (err_msg +
                    '<p class="hint">Нет курсов. Создайте первый курс или '
                    'импортируйте готовый пакетом.</p>'
                    '<form method="post" action="/staff/new_course" class="staff-card">'
                    '<h2>Создать курс</h2>'
                    '<p><label>Название курса: <input type="text" name="title" required autofocus>'
                    '</label></p>'
                    '<p><button>Создать</button></p></form>'
                    + _extra_cards("staff.home_cards"))
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
        body = ('%s<div class="staff-grid">%s</div>%s%s%s%s'
                '<p class="hint"><a href="/staff/password">🔑 Сменить пароль</a>'
                ' · <a href="/staff/scenarios">🎬 Сценарии</a></p>'
                ) % (err_msg, cards, _queue_html(), new_form, import_card,
                     _extra_cards("staff.home_cards"))
        return _page(ctx, "Панель преподавателя", body)

    # ── Создать курс ─────────────────────────────────────────────────
    @ctx.add_route("POST", "/staff/new_course", access="staff")
    def new_course(handler, params):
        data = handler._parse_post()
        title = data.get("title", "").strip()
        if title:
            ctx.add_course(title)
            ctx.audit("создан курс", {"название": title}, handler=handler)
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
        # Скрыть студентов, не зачисленных на этот курс: доступ =
        # индивидуальное зачисление и/или группы. Если курс открыт всем
        # (ничего не задано) - показываем всех. Полный список остаётся
        # в карточке «Зачисление».
        students_all = students
        enr_filter = bool((course.get("студенты") or [])
                          or [g for g in (course.get("группы") or []) if g])
        if enr_filter:
            students = [s for s in students_all
                        if ctx.can_access(cid, s["id"])]
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
            _ds = _e((s["fio"] + " " + s.get("group", "") + " " + brig)
                     .strip().lower())
            student_rows += (
                '<tr class="stu-row" data-s="%s"><td>%s</td><td>%s</td>'
                '<td><form method="post" action="/staff/student_brigade" '
                'style="display:inline;white-space:nowrap">'
                '<input type="hidden" name="student" value="%s">'
                '<input type="hidden" name="course" value="%s">'
                '<input type="text" name="brigade" value="%s" placeholder="—" '
                'style="width:140px;padding:6px 8px"> '
                '<button class="btn-sm">💾</button></form></td>'
                '<td><a href="/staff/delete/student/%s" '
                'onclick="%s" class="btn btn-danger btn-sm">X</a></td></tr>') % (
                    _ds, _e(s["fio"]), _e(s.get("group", "")),
                    _e(s["id"]), _e(cid), _e(brig), _e(s["id"]), ds)

        st_hint = ""
        if enr_filter:
            st_hint = ('<p class="hint">Показаны зачисленные на курс: '
                       '%d из %d. Полный список и зачисление — в карточке '
                       '«Зачисление».</p>'
                       % (len(students), len(students_all)))
        student_table = ""
        if students:
            student_table = st_hint + (
                '<details class="stu-list">'
                '<summary>📋 Студенты (%d) — нажмите, чтобы развернуть'
                '</summary>'
                '<p style="margin:10px 0">'
                '<input type="text" class="stu-filter" data-tb="tb_students" '
                'data-cnt="cnt_students" oninput="stuFilt(this)" '
                'placeholder="Поиск: ФИО, группа, бригада…" '
                'style="max-width:340px;display:inline-block"> '
                '<span class="reason" id="cnt_students"></span></p>'
                '<table class="staff-table" id="tb_students">'
                '<tr><th>ФИО</th><th>Группа</th><th>Бригада</th>'
                '<th></th></tr>%s</table></details>'
                '<script>'
                'function stuFilt(inp){var q=inp.value.toLowerCase();'
                'var tb=document.getElementById(inp.getAttribute("data-tb"));'
                'var n=0,tot=0;'
                'Array.prototype.forEach.call('
                'tb.querySelectorAll("tr.stu-row"),function(tr){tot++;'
                'var ok=!q||tr.getAttribute("data-s").indexOf(q)>=0;'
                'tr.style.display=ok?"":"none";if(ok)n++;});'
                'var c=document.getElementById(inp.getAttribute("data-cnt"));'
                'if(c)c.textContent="показано: "+n+" из "+tot;}'
                '</script>'
            ) % (len(students), student_rows)

        enrolled = set(course.get("студенты") or [])
        enroll_rows = ""
        for s in students_all:
            in_course = s["id"] in enrolled
            _es = _e((s["fio"] + " " + s.get("group", "")).strip().lower())
            enroll_rows += (
                '<tr class="stu-row" data-s="%s"><td>%s</td><td>%s</td>'
                '<td>%s</td>'
                '<td><form method="post" action="/staff/enroll" '
                'style="display:inline">'
                '<input type="hidden" name="course" value="%s">'
                '<input type="hidden" name="student" value="%s">'
                '<input type="hidden" name="act" value="%s">'
                '<button>%s</button></form></td></tr>') % (
                    _es, _e(s["fio"]), _e(s.get("group", "")),
                    "✅" if in_course else "—",
                    _e(cid), _e(s["id"]),
                    "off" if in_course else "on",
                    "Отчислить" if in_course else "Зачислить")
        grp_list = sorted({(s.get("group", "") or "").strip()
                           for s in students_all} - {""})
        grp_form = ""
        if grp_list:
            opts = "".join('<option value="%s">%s</option>'
                           % (_e(g), _e(g)) for g in grp_list)
            grp_form = (
                '<form method="post" action="/staff/enroll_group" '
                'style="display:inline-flex;gap:8px;align-items:center;'
                'margin:6px 0 0">'
                '<input type="hidden" name="course" value="%s">'
                '<select name="group">%s</select>'
                '<button class="btn-sm">＋ Зачислить группу</button></form>'
                % (_e(cid), opts))
        enroll_card = (
            '<div class="staff-card"><h2>Зачисление</h2>'
            '<p class="hint">Зачислено: %d из %d. Если никого не зачислять '
            'и не задать группы — курс открыт всем.</p>'
            '<details><summary>Список зачисления (%d)</summary>'
            '<p style="margin:10px 0">'
            '<input type="text" class="stu-filter" data-tb="tb_enroll" '
            'data-cnt="cnt_enroll" oninput="stuFilt(this)" '
            'placeholder="Поиск: ФИО, группа…" '
            'style="max-width:340px;display:inline-block"> '
            '<span class="reason" id="cnt_enroll"></span></p>'
            '<table class="staff-table" id="tb_enroll"><tr><th>ФИО</th>'
            '<th>Группа</th><th>В курсе</th><th></th></tr>%s</table>'
            '</details>'
            '<form method="post" action="/staff/enroll_all">'
            '<input type="hidden" name="course" value="%s">'
            '<p><button>Зачислить всех</button></p></form>'
            + grp_form +
            '</div>') % (len(enrolled), len(students_all),
                         len(students_all),
                         enroll_rows, _e(cid))

        body = (
            '<p><a href="/staff">Все курсы</a></p>'
            '%s'
            '<div class="staff-grid">'
            '<div class="staff-card">'
            '<h2>Занятия</h2>'
            + (('<details><summary>📋 Занятия (%d)</summary>'
                % len(lessons)) + lesson_table + '</details>'
               if lessons else '<p class="hint">Нет занятий.</p>') +
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
            '</div></div>') % (_extra_cards("staff.course_actions",
                                             cid=cid),
                               _e(cid), len(students))
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
        bon = ctx.brigades_enabled(cid)
        bmax = ctx.brigade_max(cid)
        teams = {}
        for s in ctx.list_students():
            b = (s.get("бригада") or "").strip()
            if b:
                teams.setdefault(b, []).append(s.get("fio", ""))
        max_form = ""
        if bon:
            team_blocks = ""
            for b, m in sorted(teams.items()):
                boff = ctx.brigade_off(b)
                team_blocks += (
                    '<div class="field-block" style="margin:8px 0%s">'
                    '<p><b>👥 %s</b>%s — %d чел. (лимит %d): %s</p>'
                    '<form method="post" action="/staff/brigade_state" '
                    'style="display:inline">'
                    '<input type="hidden" name="course" value="%s">'
                    '<input type="hidden" name="name" value="%s">'
                    '<input type="hidden" name="act" value="%s">'
                    '<button class="btn-sm btn-secondary">%s</button></form> '
                    '<form method="post" action="/staff/brigade_rename" '
                    'style="display:inline">'
                    '<input type="hidden" name="course" value="%s">'
                    '<input type="hidden" name="old" value="%s">'
                    '<input type="text" name="new" value="%s" '
                    'style="width:150px;padding:6px 8px">'
                    '<button class="btn-sm">Переименовать</button></form> '
                    '<form method="post" action="/staff/brigade_delete" '
                    'style="display:inline">'
                    '<input type="hidden" name="course" value="%s">'
                    '<input type="hidden" name="name" value="%s">'
                    '<button class="btn-sm btn-danger">Распустить</button></form>'
                    '</div>'
                ) % (';opacity:.55' if boff else "",
                     _e(b),
                     ' <span class="reason">⛔ отключена</span>' if boff else "",
                     len(m), bmax, _e(", ".join(m)),
                     _e(cid), _e(b), "on" if boff else "off",
                     '▶️ Включить' if boff else '⏸ Отключить',
                     _e(cid), _e(b), _e(b), _e(cid), _e(b))
            if not team_blocks:
                team_blocks = (
                    '<p class="hint">Пока нет бригад. Создайте состав: '
                    'впишите название бригады студенту в таблице '
                    '«📋 Студенты» выше — или студенты зарегистрируются '
                    'сами на странице курса.</p>')
            max_form = (
                '<form method="post" action="/staff/brigade_max">'
                '<input type="hidden" name="course" value="%s">'
                '<p><label>Максимальный состав бригады: '
                '<input type="number" name="max" value="%d" min="1" max="20" '
                'required></label></p>'
                '<p><button>Сохранить</button></p></form>'
            ) % (_e(cid), bmax)
        else:
            team_blocks = (
                '<p class="hint">⛔ Бригады на курсе отключены: студенты '
                'сдают работы лично, блок регистрации бригад на странице '
                'курса скрыт, выдача бригадам недоступна.</p>')
        sw = (
            '<div style="margin:0 0 10px"><b>Бригады на курсе:</b> '
            '<span class="%s">%s</span> '
            '<form method="post" action="/staff/brigades_course" '
            'style="display:inline">'
            '<input type="hidden" name="course" value="%s">'
            '<input type="hidden" name="act" value="%s">'
            '<button class="btn-sm btn-secondary">%s</button></form></div>'
        ) % ("state-ok" if bon else "reason",
             '✅ включены' if bon else '⛔ отключены',
             _e(cid), "off" if bon else "on",
             '⏸ Отключить бригады на курсе' if bon
             else '▶️ Включить бригады на курсе')
        brigade_card = (
            '<div class="staff-card"><h2>👷 Бригады</h2>'
            '%s'
            '<p class="hint">Студенты регистрируют бригады на странице курса; '
            'вы можете править состав в таблице студентов, переименовывать '
            'и распускать бригады, отключать отдельную бригаду или бригады '
            'всего курса. Отключённая бригада не принимает сдачи за бригаду '
            'и недоступна для вступления (состав сохраняется).</p>'
            '%s%s</div>'
        ) % (sw, team_blocks, max_form)
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
            ctx.audit("создано занятие", {"курс": cid, "название": title},
                      handler=handler)
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
            ctx.audit("добавлен студент",
                      {"фио": fio, "группа": group, "бригада": brigade},
                      handler=handler)
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

        # ── Массовая выдача: задания × бригады ──
        brigades = sorted({(s.get("бригада") or "").strip()
                           for s in ctx.list_students()
                           if (s.get("бригада") or "").strip()})
        issue_head = ('<tr><th>Задание</th>'
                      + "".join('<th title="состав см. в студентах">👥 %s%s</th>'
                                % (_e(b), ' · отключена'
                                   if ctx.brigade_off(b) else "")
                                for b in brigades)
                      + '<th>Всем</th><th>Снять</th></tr>')
        issue_rows = ""
        for t in tasks:
            issued = set(t.get("выдано")) if isinstance(t.get("выдано"),
                                                        list) else set()
            cells = "".join(
                '<td style="text-align:center">'
                '<input type="checkbox" name="iss" value="%s|%s"%s></td>'
                % (_e(t["id"]), _e(b), " checked" if b in issued else "")
                for b in brigades)
            if not brigades:
                cells = ('<td colspan="1" class="reason">Бригад пока нет — '
                         'студенты регистрируют их на странице курса</td>')
            allc = ('<td style="text-align:center">'
                    '<input type="checkbox" name="alltask" value="%s"%s></td>'
                    % (_e(t["id"]),
                       " checked" if isinstance(t.get("выдано"), list)
                       and not t.get("выдано") else ""))
            off_cell = ('<td style="text-align:center">'
                        '<a class="btn-sm btn-secondary" '
                        'href="/staff/task_off?task=%s&amp;back=%s" '
                        'onclick="return confirm(&quot;Снять выдачу?&quot;)">'
                        '🚫</a></td>'
                        ) % (_e(t["id"]), _e("/staff/lesson/" + lid))
            wait_mark = ("⏳ " if t.get("выдано") is None
                         and (t.get("настройки") or {}).get("план") else "")
            issue_rows += ('<tr><td>%s<a href="/staff/task/%s">%s</a></td>'
                           '%s%s%s</tr>'
                           % (wait_mark, _e(t["id"]), _e(t.get("title", "")),
                              cells, allc, off_cell))
        issue_card = ""
        if tasks and not ctx.brigades_enabled(lesson.get("course", "")):
            issue_card = (
                '<div class="staff-card"><h2>📤 Массовая выдача бригадам</h2>'
                '<p class="hint">⛔ Бригады на этом курсе отключены '
                '(включить — на странице курса). Выдача «всем» и снятие '
                'доступны на странице задания.</p></div>')
        elif tasks:
            issue_card = (
                '<form method="post" action="/staff/issue_mass" class="staff-card">'
                '<h2>📤 Массовая выдача бригадам</h2>'
                '<p class="hint">Отметьте, какие задания какой бригаде выданы. '
                '«Всем» — задание видно всем студентам курса. Ничего не '
                'отмечено — сценарное задание ждёт выдачи (студенты его '
                'не видят). Состав бригад — студенты регистрируют их на '
                'странице курса.</p>'
                '<input type="hidden" name="lesson" value="%s">'
                '<table class="staff-table">%s%s</table>'
                '<p><button>Сохранить выдачу</button></p></form>'
            ) % (_e(lid), issue_head, issue_rows)

        # ── Матрица сдач: бригады × задания ──
        mx_rows = ""
        matrix_card = ""
        if tasks:
            def _short(s, n=26):
                s = str(s or "")
                return s if len(s) <= n else s[:n - 1] + "…"

            info = {}
            for t in tasks:
                m = {"brig": {}, "sid": {}}
                for s in ctx.list_submissions(task_id=t["id"]):
                    _ver = (s.get("versions") or [{}])[-1]
                    if s.get("бригада"):
                        m["brig"][s["бригада"]] = (s, _ver)
                    m["sid"][s.get("student", "")] = (s, _ver)
                info[t["id"]] = m

            def _cell(t, m, brigade, sid):
                if not ctx.task_for_brigade(t, brigade or ""):
                    return '<td class="mx-off" title="не выдано">—</td>'
                sv = m["brig"].get(brigade) if brigade else m["sid"].get(sid)
                if not sv:
                    return '<td class="mx-wait" title="ждёт сдачи">⏳</td>'
                s, ver = sv
                st = s.get("status", "сдано")
                ic = {"сдано": "📤", "принято": "✅", "доработка": "🔄",
                      "отклонено": "❌"}.get(st, "📤")
                cls = {"сдано": "mx-sent", "принято": "mx-ok",
                       "доработка": "mx-fix", "отклонено": "mx-rej"
                       }.get(st, "mx-sent")
                late = " ⏰" if ver.get("просрочено") else ""
                sc = ("" if ver.get("score") is None
                      else " · %s" % ver["score"])
                return ('<td class="%s"><a href="/staff/sub/%s__%s" '
                        'title="%s">%s%s%s</a></td>'
                        ) % (cls, _e(t["id"]), _e(s.get("student", "")),
                             _e(st), ic, sc, late)

            solo = [s for s in ctx.list_students()
                    if not (s.get("бригада") or "").strip()]
            for b in brigades:
                cnt = sum(1 for s in ctx.list_students()
                          if (s.get("бригада") or "").strip() == b)
                cells = "".join(_cell(t, info[t["id"]], b, "") for t in tasks)
                mx_rows += ('<tr><td>👥 <b>%s</b> <span class="reason">(%d)'
                            '</span></td>%s</tr>' % (_e(b), cnt, cells))
            for s in solo:
                cells = "".join(_cell(t, info[t["id"]], "", s["id"])
                                for t in tasks)
                mx_rows += ('<tr><td>👤 %s <span class="reason">%s</span></td>'
                            '%s</tr>' % (_e(s.get("fio", "")),
                                         _e(s.get("group", "")), cells))
            heads = "".join('<th title="%s">%s</th>' % (
                _e(t.get("title", "")), _e(_short(t.get("title", ""))))
                for t in tasks)
            matrix_card = (
                '<div class="staff-card"><h2>📊 Матрица сдач</h2>'
                '<p class="hint">⏳ ждёт сдачи · 📤 сдано · ✅ принято · '
                '🔄 доработка · ❌ не принято · ⏰ после срока · '
                '— не выдано этой бригаде</p>'
                '<div class="mx-wrap"><table class="staff-table mx-tbl">'
                '<tr><th>Бригада / студент</th>%s</tr>%s</table></div></div>'
            ) % (heads, mx_rows)

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
            '%s%s'
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
                issue_card, matrix_card, rows, _e(lid))
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
            ctx.audit("создано задание", {"занятие": lid, "название": title},
                      handler=handler)
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
        _lsn_t = ctx.get_lesson(task.get("lesson", ""))
        _bon_t = ctx.brigades_enabled(_lsn_t.get("course", "") if _lsn_t else "")
        brigades = sorted({(s.get("бригада") or "").strip()
                           for s in ctx.list_students()
                           if (s.get("бригада") or "").strip()})
        if _bon_t:
            brig_rows = "".join(
                '<label class="cb-label"><input type="checkbox" name="brigade" '
                'value="%s"%s> 👥 %s%s</label>' % (
                    _e(b), " checked" if issued_set and b in issued_set else "",
                    _e(b), ' <span class="reason">отключена</span>'
                    if ctx.brigade_off(b) else "")
                for b in brigades) or \
                '<p class="hint">Бригад пока нет — студенты регистрируют их на странице курса.</p>'
        else:
            brig_rows = ('<p class="hint">⛔ Бригады на этом курсе отключены '
                         '(включить — на странице курса). Выдача «всем» и '
                         'снятие выдачи работают.</p>')
        if issued_set is None and is_scenario:
            status_html = (
                '<p class="reason">⏳ Сценарное задание ещё не выдано — '
                'студенты его не видят. Отметьте бригады или «выдать всем».'
                '</p>' if _bon_t else
                '<p class="reason">⏳ Сценарное задание ещё не выдано — '
                'студенты его не видят. Бригады на курсе отключены: '
                'используйте «выдать всем».</p>')
        elif issued_set is None:
            status_html = '<p class="hint">Обычное задание — видно всем.</p>'
        elif not issued_set:
            status_html = '<p class="hint">✅ Выдано всем студентам курса.</p>'
        else:
            _items = "".join(
                '<span class="team-badge">👥 %s</span> '
                '<a class="btn-sm btn-danger" '
                'title="Снять выдачу этой бригаде" '
                'href="/staff/task_off?task=%(tid)s&amp;back=%(back)s'
                '&amp;brigade=%(b)s" '
                'onclick="return confirm(&quot;Снять выдачу?&quot;)">✕</a> '
                % {"tid": _e(tid), "back": _e("/staff/task/" + tid),
                   "b": _e(b)}
                for b in sorted(issued_set))
            status_html = ('<p class="hint">Выдано бригадам: %s</p>' % _items)
        all_checked = " checked" if issued_set is not None and not issued_set else ""
        issue_card = (
            '<form method="post" action="/staff/task_issue" class="staff-card">'
            '<h2>📤 Выдача бригадам</h2>'
            '%(status)s'
            '<p class="hint">Отметьте бригады, которым выдано задание. '
            'Снять выдачу — кнопкой ниже или ✕ у бригады.</p>'
            '%(brig)s'
            '<p><label class="cb-label"><input type="checkbox" name="all"'
            '%(allc)s> Выдать всем</label></p>'
            '<p><button>Сохранить выдачу</button> '
            '<a class="btn btn-secondary" '
            'href="/staff/task_off?task=%(tid)s&amp;back=%(back)s" '
            'onclick="return confirm(&quot;Снять выдачу полностью? Задание '
            'снова будет скрыто от студентов.&quot;)">🚫 Снять выдачу</a></p>'
            '</form>'
        ) % {"status": status_html, "brig": brig_rows, "allc": all_checked,
             "tid": _e(tid), "back": _e("/staff/task/" + tid)}
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
        for _frag in ctx.emit("staff.task_cards", task=task,
                              handler=handler):
            body += _frag or ""
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
        ctx.audit("изменено задание", {"задание": tid}, handler=handler)
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
            if fd.get("тип") == "shlei":
                import json as _json
                try:
                    _rl = _json.loads(answers.get(key, "") or "[]")
                except ValueError:
                    _rl = []
                _rows = "".join(
                    '<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td>'
                    '<td>%s</td></tr>' % (
                        _e(r.get("n", "")), _e(r.get("type", "")),
                        _e(r.get("dev", "")), _e(r.get("cnt", "")),
                        _e(r.get("note", "")))
                    for r in (_rl if isinstance(_rl, list) else [])
                    if isinstance(r, dict) and
                    (r.get("n") or r.get("type") or r.get("dev")
                     or r.get("cnt") or r.get("note")))
                answer_rows += (
                    '<tr><td>%s</td><td><table class="shlei-view">'
                    '<tr><th>№ шлейфа</th><th>Тип</th><th>Прибор</th>'
                    '<th>Кол-во</th><th>Комментарий</th></tr>%s</table>'
                    '</td></tr>') % (_e(fd.get("вопрос") or key), _rows)
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

        crits = ((task or {}).get("настройки") or {}).get("критерии") or []
        if not isinstance(crits, list):
            crits = []
        _chk = v.get("чек") or []
        if not isinstance(_chk, list):
            _chk = []
        crit_html = ""
        if crits:
            crit_rows = "".join(
                '<label class="crit-row"><input type="checkbox" name="crit" '
                'value="%d"%s> %s</label>'
                % (i, " checked" if i in _chk else "", _e(c))
                for i, c in enumerate(crits))
            crit_html = ('<p class="crit-box"><span class="field-label">'
                         'Критерии (выполнены)</span>%s</p>') % crit_rows
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
            '%s'
            '<p><label>Балл: <input type="number" name="score" step="0.5" '
            'min="0" max="100" value="%s"></label></p>'
            '<p><label>Комментарий:<br><textarea name="comment" rows="3" '
            'placeholder="Замечания и рекомендации...">%s</textarea></label></p>'
            '<p><button>Применить вердикт</button></p></form>') % (
                _e(full_key), crit_html,
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
        raw = data.get("crit", [])
        if not isinstance(raw, list):
            raw = [raw]
        crit_idx = sorted(int(x) for x in raw if str(x).strip().isdigit())
        if "__" not in key or not verdict:
            handler._redirect("/staff")
            return handler._SENT
        tid, sid = key.split("__", 1)
        try:
            score_val = float(score) if score else None
        except ValueError:
            score_val = None
        ctx.set_verdict(tid, sid, verdict, score_val, comment, check=crit_idx)
        ctx.audit("вердикт",
                  {"задание": tid, "студент": sid, "решение": verdict,
                   "балл": score_val, "критерии": len(crit_idx)},
                  handler=handler)
        handler._redirect("/staff/sub/%s" % _e(key))
        return handler._SENT

    # ── Массовая выдача заданий бригадам ─────────────────────────────
    @ctx.add_route("POST", "/staff/issue_mass", access="staff")
    def issue_mass(handler, params):
        data = handler._parse_post()
        lid = data.get("lesson", "")
        if not ctx.get_lesson(lid):
            handler._redirect("/staff")
            return handler._SENT
        alltasks = data.get("alltask") or []
        if isinstance(alltasks, str):
            alltasks = [alltasks]
        pairs = data.get("iss") or []
        if isinstance(pairs, str):
            pairs = [pairs]
        by_task = {}
        for p in pairs:
            if "|" in str(p):
                t, b = str(p).split("|", 1)
                by_task.setdefault(t, []).append(b)
        n = 0
        for t in ctx.list_tasks():
            if t.get("lesson") != lid:
                continue
            if t["id"] in alltasks:
                ctx.task_set_issue(t["id"], [])
            elif t["id"] in by_task:
                ctx.task_set_issue(t["id"], by_task[t["id"]])
            else:
                ctx.task_set_issue(t["id"], None)  # ждёт выдачи
            n += 1
        ctx.audit("массовая выдача заданий", {"занятие": lid, "заданий": n},
                  handler=handler)
        ctx.log("массовая выдача %s: заданий %d" % (lid, n))
        handler._redirect("/staff/lesson/%s" % _e(lid))
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
            det = {"задание": tid, "выдано": "всем"}
        else:
            brs = data.get("brigade") or []
            if isinstance(brs, str):
                brs = [brs]
            ctx.task_set_issue(tid, brs)
            det = {"задание": tid, "бригады": brs}
        ctx.audit("выдача задания", det, handler=handler)
        handler._redirect("/staff/task/%s" % _e(tid))
        return handler._SENT

    # ── Снять выдачу задания ─────────────────────────────────────────
    @ctx.add_route("GET", "/staff/task_off", access="staff")
    def task_off(handler, params):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
        tid = (qs.get("task") or [""])[0]
        task = ctx.get_task(tid)
        if not task:
            handler._redirect("/staff")
            return handler._SENT
        back = (qs.get("back") or [""])[0] or "/staff/task/%s" % _e(tid)
        brig = (qs.get("brigade") or [""])[0].strip()
        issued = task.get("выдано")
        if brig and isinstance(issued, list) and brig in issued:
            issued = [b for b in issued if b != brig]
            ctx.task_set_issue(tid, issued if issued else None)
        else:
            ctx.task_set_issue(tid, None)  # задание снова ждёт выдачи
        ctx.audit("снята выдача задания",
                  {"задание": tid, "бригада": brig or "полностью"},
                  handler=handler)
        handler._redirect(back)
        return handler._SENT

    # ── Редактирование бригад ────────────────────────────────────────
    @ctx.add_route("POST", "/staff/student_brigade", access="staff")
    def student_brigade(handler, params):
        data = handler._parse_post()
        sid = data.get("student", "")
        if ctx.get_student(sid):
            ctx.student_set_brigade(sid, data.get("brigade", ""))
            ctx.audit("изменена бригада студента",
                      {"студент": sid, "бригада": data.get("brigade", "")},
                      handler=handler)
        handler._redirect("/staff/course/%s" % _e(data.get("course", "")))
        return handler._SENT

    @ctx.add_route("POST", "/staff/brigade_rename", access="staff")
    def brigade_rename(handler, params):
        data = handler._parse_post()
        ctx.brigade_rename(data.get("old", ""), data.get("new", ""))
        ctx.audit("бригада переименована",
                  {"было": data.get("old", ""), "стало": data.get("new", "")},
                  handler=handler)
        handler._redirect("/staff/course/%s" % _e(data.get("course", "")))
        return handler._SENT

    @ctx.add_route("POST", "/staff/brigade_delete", access="staff")
    def brigade_delete(handler, params):
        data = handler._parse_post()
        ctx.brigade_delete(data.get("name", ""))
        ctx.audit("бригада распущена",
                  {"бригада": data.get("name", "")}, handler=handler)
        handler._redirect("/staff/course/%s" % _e(data.get("course", "")))
        return handler._SENT

    # ── Включение/отключение бригады ──────────────────────────────────
    @ctx.add_route("POST", "/staff/brigade_state", access="staff")
    def brigade_state(handler, params):
        data = handler._parse_post()
        name = (data.get("name") or "").strip()
        on = (data.get("act") or "").strip() == "on"
        if name and ctx.brigade_set_enabled(name, on):
            ctx.audit("бригада включена" if on else "бригада отключена",
                      {"бригада": name}, handler=handler)
        handler._redirect("/staff/course/%s" % _e(data.get("course", "")))
        return handler._SENT

    # ── Бригады курса: включить/отключить ─────────────────────────────
    @ctx.add_route("POST", "/staff/brigades_course", access="staff")
    def brigades_course(handler, params):
        data = handler._parse_post()
        cid = data.get("course", "")
        on = (data.get("act") or "").strip() == "on"
        if cid and ctx.set_brigades_enabled(cid, on):
            ctx.audit("бригады курса включены" if on
                      else "бригады курса отключены",
                      {"курс": cid}, handler=handler)
        handler._redirect("/staff/course/%s" % _e(cid))
        return handler._SENT

    # ── Максимальный состав бригад ───────────────────────────────────
    @ctx.add_route("POST", "/staff/brigade_max", access="staff")
    def brigade_max(handler, params):
        data = handler._parse_post()
        cid = data.get("course", "")
        if cid:
            ctx.set_brigade_max(cid, data.get("max", 0))
            ctx.audit("изменён лимит состава бригад",
                      {"курс": cid, "лимит": data.get("max", "")},
                      handler=handler)
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
            ctx.audit("доступ курса группе",
                      {"курс": cid, "группа": group,
                       "действие": "закрыт" if act == "off" else "открыт"},
                      handler=handler)
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
        ctx.audit("изменён пароль преподавателя", handler=handler)
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
        ctx.audit("импорт группы",
                  {"курс": cid, "добавлено": added, "пропущено": skipped},
                  handler=handler)
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
            ctx.audit("отчисление" if data.get("act") == "off"
                      else "зачисление",
                      {"курс": cid, "студент": sid}, handler=handler)
        handler._redirect("/staff/course/%s" % _e(cid))
        return handler._SENT

    @ctx.add_route("POST", "/staff/enroll_all", access="staff")
    def enroll_all(handler, params):
        data = handler._parse_post()
        cid = data.get("course", "")
        if ctx.get_course(cid):
            for s in ctx.list_students():
                ctx.enroll(cid, s["id"])
            ctx.audit("зачислены все студенты", {"курс": cid},
                      handler=handler)
        handler._redirect("/staff/course/%s" % _e(cid))
        return handler._SENT

    @ctx.add_route("POST", "/staff/enroll_group", access="staff")
    def enroll_group(handler, params):
        """Зачислить на курс всех студентов выбранной группы."""
        data = handler._parse_post()
        cid = data.get("course", "")
        grp = str(data.get("group") or "").strip()
        course = ctx.get_course(cid)
        if not course or not grp:
            handler._redirect("/staff")
            return handler._SENT
        enrolled = set(course.get("студенты") or [])
        added = 0
        for s in ctx.list_students():
            sid = s.get("id", "")
            if (s.get("group", "") or "").strip() != grp:
                continue
            if sid in enrolled:
                continue
            ctx.enroll(cid, sid)
            enrolled.add(sid)
            added += 1
        ctx.audit("зачислена группа",
                  {"курс": cid, "группа": grp, "зачислено": added},
                  handler=handler)
        handler._redirect("/staff/course/%s" % _e(cid))
        return handler._SENT

    # ── Удаление курса ───────────────────────────────────────────────
    @ctx.add_route("GET", "/staff/delete/course/", access="staff")
    def delete_course(handler, params):
        parts = params.get("_parts", [])
        cid = parts[0] if parts else ""
        ctx.delete_course(cid)
        ctx.audit("удалён курс", {"курс": cid}, handler=handler)
        handler._redirect("/staff")
        return handler._SENT

    @ctx.add_route("GET", "/staff/delete/lesson/", access="staff")
    def delete_lesson(handler, params):
        parts = params.get("_parts", [])
        lid = parts[0] if parts else ""
        lesson = ctx.get_lesson(lid)
        cid = lesson.get("course", "") if lesson else ""
        ctx.delete_lesson(lid)
        ctx.audit("удалено занятие", {"занятие": lid}, handler=handler)
        handler._redirect("/staff/course/%s" % _e(cid) if cid else "/staff")
        return handler._SENT

    @ctx.add_route("GET", "/staff/delete/task/", access="staff")
    def delete_task(handler, params):
        parts = params.get("_parts", [])
        tid = parts[0] if parts else ""
        task = ctx.get_task(tid)
        lid = task.get("lesson", "") if task else ""
        ctx.delete_task(tid)
        ctx.audit("удалено задание", {"задание": tid}, handler=handler)
        handler._redirect("/staff/lesson/%s" % _e(lid))
        return handler._SENT

    @ctx.add_route("GET", "/staff/delete/student/", access="staff")
    def delete_student(handler, params):
        parts = params.get("_parts", [])
        sid = parts[0] if parts else ""
        ctx.delete_student(sid)
        ctx.audit("удалён студент", {"студент": sid}, handler=handler)
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
