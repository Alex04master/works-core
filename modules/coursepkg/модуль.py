# -*- coding: utf-8 -*-
"""Модуль «Пакет курса»: экспорт/импорт курса одним .zip-файлом.

Кнопка «📦 Скачать курс» (страница курса) и карточка «📦 Импорт курса»
(главная панель) вставляются через события staff.course_actions и
staff.home_cards — модуль самодостаточен и включается/выключается
на панели /_modules независимо от остальных.

Состав пакета: курс, занятия, задания, студенты, сдачи с результатами,
раздатка (включая event.js/plans.js сценариев) и файлы сдач.
При импорте id перемапливаются, студенты сливаются по ФИО.
"""
import json
import os
import urllib.parse
from datetime import datetime


def _e(v):
    import html
    return html.escape(str(v), quote=True)


def register(ctx):
    # ── Кнопки на страницах панели (события панели) ─────────────────
    def _import_card(**kw):
        return (
            '<details><summary>📦 Импорт курса</summary>'
            '<form method="post" action="/staff/course_import" '
            'enctype="multipart/form-data" class="staff-card">'
            '<p class="hint">Файл пакета (.zip) — то, что выгружается '
            'кнопкой «📦 Скачать курс» на странице курса. Занятия, задания '
            'и раздатка (включая сценарии с интерактивным планом) '
            'переносятся целиком. Студенты: совпадающие по ФИО объединяются, '
            'остальные добавляются.</p>'
            '<p><label>Файл пакета: <input type="file" name="pkgfile" '
            'accept=".zip,application/zip" required></label></p>'
            '<p><label><input type="checkbox" name="results" checked> '
            'Включая результаты (сдачи, вердикты, файлы)</label></p>'
            '<p><label><input type="checkbox" name="allowdup"> '
            'Разрешить повторный импорт (создать копию курса)</label></p>'
            '<p><button>Импортировать курс</button></p></form></details>')

    def _export_btn(cid="", **kw):
        return ('<a class="btn btn-secondary" href="/staff/course_export/%s" '
                'title="Скачать пакет курса (.zip): занятия, задания, '
                'раздатка, результаты сдач">📦 Скачать курс</a>' % _e(cid))

    ctx.on("staff.home_cards", _import_card)
    ctx.on("staff.course_actions", _export_btn)

    # ── Пакет курса: скачать (.zip) ──────────────────────────────────
    @ctx.add_route("GET", "/staff/course_export/", access="staff")
    def course_export(handler, params):
        import io as _io
        import zipfile
        cid = (params.get("_parts") or [""])[0]
        course = ctx.get_course(cid)
        if not course:
            handler._send_text(404, "course not found")
            return handler._SENT
        lessons = [l for l in ctx.list_lessons() if l.get("course") == cid]
        lids = {l["id"] for l in lessons}
        tasks = [t for t in ctx.list_tasks() if t.get("lesson") in lids]
        tids = {t["id"] for t in tasks}
        subs = [s for s in ctx.list_submissions() if s.get("task") in tids]
        sids = set(course.get("студенты") or [])
        for s in subs:
            sids.add(s.get("student", ""))
            sids.update(s.get("participants") or [])
        students = [st for st in ctx.list_students() if st["id"] in sids]
        buf = _io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("пакет.json", json.dumps(
                {"формат": "works-core-курс", "версия": 1,
                 "выгружен": datetime.now().isoformat(timespec="seconds")},
                ensure_ascii=False, indent=1))
            zf.writestr("курс.json",
                        json.dumps(course, ensure_ascii=False, indent=1))
            zf.writestr("занятия.json",
                        json.dumps(lessons, ensure_ascii=False, indent=1))
            zf.writestr("задания.json",
                        json.dumps(tasks, ensure_ascii=False, indent=1))
            zf.writestr("студенты.json",
                        json.dumps(students, ensure_ascii=False, indent=1))
            zf.writestr("сдачи.json",
                        json.dumps(subs, ensure_ascii=False, indent=1))
            mat_root = os.path.join(ctx._core.store.mat, cid)
            if os.path.isdir(mat_root):
                for root, _dirs, files in os.walk(mat_root):
                    for fn in files:
                        p = os.path.join(root, fn)
                        rel = os.path.relpath(p, mat_root).replace("\\", "/")
                        zf.write(p, "раздатка/" + rel)
            for s in subs:
                for ver in s.get("versions", []):
                    for _fk, info in (ver.get("files") or {}).items():
                        if isinstance(info, dict) and info.get("файл"):
                            p = os.path.join(ctx._core.store.subs,
                                             str(info["файл"]))
                            if os.path.isfile(p):
                                zf.write(p, "сдачи/" + str(
                                    info["файл"]).replace("\\", "/"))
        data = buf.getvalue()
        fname = "курс-%s.zip" % (course.get("title", cid)
                                 .replace(" ", "_").replace('"', ""))
        handler.send_response(200)
        handler.send_header("Content-Type", "application/zip")
        handler.send_header(
            "Content-Disposition",
            "attachment; filename*=UTF-8''" + urllib.parse.quote(fname))
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)
        ctx.audit("выгружен курс (пакет)",
                  {"курс": cid, "название": course.get("title", ""),
                   "занятий": len(lessons), "заданий": len(tasks),
                   "сдач": len(subs)}, handler=handler)
        return handler._SENT

    # ── Пакет курса: импорт (.zip) ───────────────────────────────────
    @ctx.add_route("POST", "/staff/course_import", access="staff")
    def course_import(handler, params):
        import io as _io
        import zipfile
        data = handler._parse_post()
        up = data.get("pkgfile")
        if isinstance(up, list):
            up = next((u for u in up if getattr(u, "data", None)), None)
        raw = getattr(up, "data", None) if up is not None else None
        with_results = data.get("results", "") in ("on", "1", "да")
        if not raw:
            handler._redirect("/staff?err=%s"
                              % urllib.parse.quote("файл пакета не передан"))
            return handler._SENT
        import hashlib
        import time as _time
        h = hashlib.sha256(raw).hexdigest()
        allowdup = data.get("allowdup", "") in ("on", "1", "да")
        try:
            zf = zipfile.ZipFile(_io.BytesIO(raw))
            names = [n for n in zf.namelist() if not n.endswith("/")]
            for n in ("пакет.json", "курс.json", "занятия.json",
                      "задания.json"):
                if n not in names:
                    raise ValueError("в пакете нет %s" % n)
            meta = json.loads(zf.read("пакет.json").decode("utf-8"))
            if meta.get("формат") != "works-core-курс":
                raise ValueError("чужой формат пакета")
            cpack = json.loads(zf.read("курс.json").decode("utf-8"))
            lessons = json.loads(zf.read("занятия.json").decode("utf-8"))
            tasks = json.loads(zf.read("задания.json").decode("utf-8"))
            students = (json.loads(zf.read("студенты.json").decode("utf-8"))
                        if "студенты.json" in names else [])
            subs = (json.loads(zf.read("сдачи.json").decode("utf-8"))
                    if ("сдачи.json" in names and with_results) else [])
        except Exception as ex:
            handler._redirect("/staff?err=%s"
                              % urllib.parse.quote(str(ex)[:120]))
            return handler._SENT

        # защита от повторного импорта того же пакета
        regs = ctx.kv_load("импорты", {})
        if not allowdup and h in regs:
            rec = regs[h]
            handler._redirect("/staff?err=%s" % urllib.parse.quote(
                "этот пакет уже импортирован %s (курс «%s», id %s) — "
                "отметьте «разрешить повторный импорт», чтобы создать копию"
                % (_time.strftime("%d.%m %H:%M",
                                  _time.localtime(rec.get("когда", 0))),
                   rec.get("название", "?"), rec.get("курс", "?"))))
            return handler._SENT

        db = ctx._core.db
        used_c = {x.get("id") for x in db["курсы"]}
        used_l = {x.get("id") for x in db["занятия"]}
        used_t = {x.get("id") for x in db["задания"]}
        used_s = {x.get("id") for x in db["студенты"]}

        def _nid1(prefix, used):
            n = 1
            while "%s%d" % (prefix, n) in used:
                n += 1
            nid = "%s%d" % (prefix, n)
            used.add(nid)
            return nid

        new_cid = _nid1("c", used_c)
        lid_map, tid_map, sid_map, key_map = {}, {}, {}, {}
        for st in students:
            fio = (st.get("fio") or "").strip()
            if not fio:
                continue
            ex = next((x for x in db["студенты"]
                       if (x.get("fio") or "").strip() == fio), None)
            if ex:
                sid_map[st.get("id", "")] = ex["id"]
            else:
                nid = _nid1("s", used_s)
                db["студенты"].append({"id": nid, "fio": fio,
                                       "group": st.get("group", ""),
                                       "бригада": st.get("бригада", "") or ""})
                sid_map[st.get("id", "")] = nid
        course = dict(cpack)
        course["id"] = new_cid
        course["студенты"] = sorted({sid_map.get(sid, sid)
                                     for sid in (cpack.get("студенты") or [])})
        for l in lessons:
            old = l.get("id", "")
            l["id"] = _nid1("l", used_l)
            lid_map[old] = l["id"]
            l["course"] = new_cid
        for t in tasks:
            old = t.get("id", "")
            t["id"] = _nid1("t", used_t)
            tid_map[old] = t["id"]
            t["lesson"] = lid_map.get(t.get("lesson", ""),
                                      t.get("lesson", ""))
        for s in subs:
            old_key = s.get("key", "")
            new_key = "%s__%s" % (tid_map.get(s.get("task", ""),
                                              s.get("task", "")),
                                  sid_map.get(s.get("student", ""),
                                              s.get("student", "")))
            key_map[old_key] = new_key
            s["key"] = new_key
            s["task"] = tid_map.get(s.get("task", ""), s.get("task", ""))
            s["student"] = sid_map.get(s.get("student", ""),
                                       s.get("student", ""))
            s["participants"] = [sid_map.get(p, p)
                                 for p in (s.get("participants") or [])]
            for ver in s.get("versions", []):
                fl = ver.get("files")
                if not isinstance(fl, dict):
                    continue
                for fkey, info in fl.items():
                    if isinstance(info, dict) and info.get("файл"):
                        rel = str(info["файл"]).replace("\\", "/")
                        parts = rel.split("/", 1)
                        rest = parts[1] if len(parts) > 1 else parts[0]
                        info["файл"] = "%s/%s" % (new_key, rest)
            db["сдачи"][new_key] = s
        db["курсы"].append(course)
        db["занятия"].extend(lessons)
        db["задания"].extend(tasks)

        def _dst_ok(base, rel):
            dst = os.path.normpath(os.path.join(base, rel))
            b = os.path.normpath(base)
            try:
                if os.path.commonpath([dst, b]) != b:
                    return ""
            except ValueError:
                return ""
            return dst

        n_files = 0
        for name in names:
            if name.startswith("раздатка/"):
                rel = name[len("раздатка/"):]
                old_lid, _, rest = rel.partition("/")
                new_lid = lid_map.get(old_lid, old_lid)
                dst = _dst_ok(os.path.join(ctx._core.store.mat, new_cid),
                              new_lid + ("/" + rest if rest else ""))
            elif name.startswith("сдачи/") and subs:
                rel = name[len("сдачи/"):]
                old_key, _, rest = rel.partition("/")
                new_key = key_map.get(old_key, "")
                if not new_key or not rest:
                    continue
                dst = _dst_ok(os.path.join(ctx._core.store.subs, new_key),
                              rest)
            else:
                continue
            if not dst:
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(zf.read(name))
            n_files += 1
        ctx.save()
        ctx.audit("импортирован курс",
                  {"курс": new_cid, "название": course.get("title", ""),
                   "занятий": len(lessons), "заданий": len(tasks),
                   "сдач": len(subs), "файлов": n_files}, handler=handler)
        regs = ctx.kv_load("импорты", {})
        regs[h] = {"когда": _time.time(), "курс": new_cid,
                   "название": course.get("title", "")}
        ctx.kv_save("импорты", regs)
        handler._redirect("/staff/course/%s" % new_cid)
        return handler._SENT

    ctx.log("загружен: пакет курса (экспорт/импорт)")
