# -*- coding: utf-8 -*-
"""Модуль «Экспорт»: журнал сдач курса в CSV (UTF-8 BOM — открывается в Excel).

Кнопка «CSV» на странице курса в панели преподавателя.
"""
import csv
import io


def register(ctx):
    @ctx.add_route("GET", "/staff/export/course/", access="staff")
    def export_course(handler, params):
        parts = params.get("_parts", [])
        cid = parts[0] if parts else ""
        course = ctx.get_course(cid)
        if not course:
            handler._send_text(404, "Not Found")
            return handler._SENT

        students = {s["id"]: s for s in ctx.list_students()}
        lessons = {l["id"]: l for l in ctx.list_lessons(cid)}
        tasks = {t["id"]: t for t in ctx.list_tasks()
                 if t.get("lesson") in lessons}

        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(["студент", "группа", "бригада", "сдавали", "задание",
                    "статус", "вердикт", "балл", "версия", "время",
                    "просрочено"])
        for sub in ctx.list_submissions():
            task = tasks.get(sub.get("task", ""))
            if not task:
                continue
            st = students.get(sub.get("student", ""), {})
            brig = (sub.get("бригада") or "").strip()
            who = ""
            if brig:
                ids, seen = [], set()
                for pid in (sub.get("participants") or []):
                    if pid and pid not in seen:
                        seen.add(pid)
                        ids.append(pid)
                for sid2, st2 in students.items():
                    if ((st2.get("бригада") or "").strip() == brig
                            and sid2 not in seen):
                        seen.add(sid2)
                        ids.append(sid2)
                who = " / ".join(
                    (students.get(p) or {}).get("fio", str(p))
                    for p in ids)
            for v in sub.get("versions", []):
                w.writerow([
                    st.get("fio", sub.get("student", "")),
                    st.get("group", ""),
                    brig,
                    who,
                    task.get("title", ""),
                    sub.get("status", ""),
                    v.get("verdict") or "",
                    v.get("score") if v.get("score") is not None else "",
                    v.get("n", ""),
                    v.get("time", ""),
                    "да" if v.get("просрочено") else "",
                ])

        data = b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "text/csv; charset=utf-8")
        handler.send_header(
            "Content-Disposition",
            'attachment; filename="journal-%s.csv"' % cid)
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)
        return handler._SENT

    ctx.log("загружен: экспорт журнала (CSV)")
