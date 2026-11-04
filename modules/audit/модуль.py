# -*- coding: utf-8 -*-
"""Модуль «Журнал действий» — аудит системы.

Пишет файлы `данные/лог/действия-ГГГГ-ММ.jsonl` (по строке на событие):
входы, сдачи, вердикты, выдача/снятие заданий, правки бригад и студентов,
импорт, смена пароля.

Страница `/staff/log` (только преподаватель): фильтры по месяцу/кто/
действию/поиску, экспорт месяца в CSV. Настройка «хранить_месяцев» в
манифесте: 0 — хранить вечно, иначе старые месяцы удаляются.
"""
import csv
import io
import json
import urllib.parse


def register(ctx):
    keep = 0
    try:
        keep = int(ctx.settings.get("хранить_месяцев", 0) or 0)
    except (TypeError, ValueError):
        keep = 0

    def _e(v):
        import html as _html
        return _html.escape(str(v) if v is not None else "", quote=True)

    # ── Страница журнала ────────────────────────────────────────────
    @ctx.add_route("GET", "/staff/log", access="staff")
    def log_page(handler, params):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
        month = (qs.get("месяц") or [""])[0] or (ctx.audit_months() or [""])[0]
        who_q = (qs.get("кто") or [""])[0].strip()
        act_q = (qs.get("действие") or [""])[0].strip()
        q_q = (qs.get("q") or [""])[0].strip()

        removed = ctx.audit_cleanup(keep)

        rows = []
        for r in ctx.audit_read(month or None):
            if who_q and who_q.lower() not in str(r.get("кто", "")).lower():
                continue
            if act_q and act_q.lower() not in str(r.get("действие", "")).lower():
                continue
            det = json.dumps(r.get("детали", {}), ensure_ascii=False)
            if q_q and (q_q.lower() not in det.lower()
                        and q_q.lower() not in str(r.get("кто", "")).lower()
                        and q_q.lower() not in str(r.get("действие", "")).lower()):
                continue
            rows.append(r)
        rows = rows[:500]

        months = ctx.audit_months()
        chips = '<div class="staff-actions">'
        for m in months:
            chips += ('<a class="btn-sm %s" href="/staff/log?месяц=%s">%s</a> '
                      % ("btn-dark" if m == month else "btn-secondary",
                         urllib.parse.quote(m), _e(m)))
        chips += "</div>"

        flt = (
            '<form method="get" class="staff-card">'
            '<input type="hidden" name="месяц" value="%s">'
            '<p style="display:flex;gap:8px;flex-wrap:wrap">'
            '<input type="text" name="кто" placeholder="кто (студент:s1…)" '
            'value="%s" style="max-width:200px">'
            '<input type="text" name="действие" placeholder="действие" '
            'value="%s" style="max-width:220px">'
            '<input type="text" name="q" placeholder="поиск в деталях" '
            'value="%s" style="max-width:200px">'
            '<button class="btn-sm">Фильтр</button> '
            '<a class="btn-sm btn-secondary" '
            'href="/staff/log/export?месяц=%s">CSV за месяц</a>'
            '</p></form>'
        ) % (_e(month), _e(who_q), _e(act_q), _e(q_q), _e(month))

        info = ('<p class="reason">Показано строк: %d. Хранение: файлы '
                '<code>данные/лог/</code>%s</p>'
                % (len(rows), (" — удалено старых месяцев: %d." % removed)
                   if removed else ""))

        body_rows = "".join(
            '<tr><td>%s</td><td>%s</td><td>%s</td><td class="reason">%s</td></tr>'
            % (_e(r.get("время", "")), _e(r.get("кто", "")),
               _e(r.get("действие", "")),
               _e(json.dumps(r.get("детали", {}), ensure_ascii=False))
               if r.get("детали") else "")
            for r in rows)

        body = (
            '<div class="staff-card"><h2>📜 Журнал действий</h2>'
            '<p class="hint">Входы, сдачи, вердикты, выдача и снятие заданий, '
            'бригады, импорт, смена пароля. Файлы по месяцам: '
            '<code>данные/лог/действия-ГГГГ-ММ.jsonl</code>.</p></div>'
            '%s%s%s'
            '<table class="staff-table"><tr><th>Время</th><th>Кто</th>'
            '<th>Действие</th><th>Детали</th></tr>%s</table>'
        ) % (chips, flt, info, body_rows)
        return ctx.render_page("Журнал действий", body, staff=True)

    # ── Экспорт месяца в CSV ────────────────────────────────────────
    @ctx.add_route("GET", "/staff/log/export", access="staff")
    def log_export(handler, params):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
        month = (qs.get("месяц") or [""])[0] or (ctx.audit_months() or [""])[0]
        rows = ctx.audit_read(month or None)[::-1]  # хронологический порядок
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(["время", "кто", "ip", "действие", "детали"])
        for r in rows:
            w.writerow([r.get("время", ""), r.get("кто", ""), r.get("ip", ""),
                        r.get("действие", ""),
                        json.dumps(r.get("детали", {}), ensure_ascii=False)])
        data = b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")
        handler._send_response(200, "text/csv; charset=utf-8", data,
                               encode=False)
        return handler._SENT

    ctx.log("загружен: журнал действий")
