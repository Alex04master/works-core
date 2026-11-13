# -*- coding: utf-8 -*-
"""Проверка модуля «Новое задание» (newmark): ⚠️ на новом, снятие по
просмотру, раздельные метки курса/занятия, инъекция скрипта.

Свой сервер: порт 8127 (PORT), хранилище _tmp_newmark_store (STORE).
Запуск: python -X utf8 tests/_chk_newmark.py
"""
import http.cookiejar
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PORT = int(os.environ.get("PORT", "8127"))
STORE = os.environ.get("STORE", "_tmp_newmark_store")
BASE = "http://127.0.0.1:%d" % PORT

ok = True


def need(cond, msg):
    global ok
    print(("OK   " if cond else "FAIL ") + msg)
    ok = ok and bool(cond)


def opener():
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj)), cj


def post(op, path, fields):
    data = urllib.parse.urlencode(fields).encode()
    r = op.open(BASE + path, data=data, timeout=10)
    body = r.read().decode("utf-8", "replace")
    return r.geturl(), body


def get(op, path):
    r = op.open(BASE + path, timeout=10)
    return r.geturl(), r.read().decode("utf-8", "replace")


def api(op):
    """JSON /newmark/api; не-JSON (redirect на логин) -> None."""
    try:
        return json.loads(op.open(BASE + "/newmark/api", timeout=10)
                          .read().decode("utf-8"))
    except Exception:
        return None


shutil.rmtree(STORE, ignore_errors=True)

proc = subprocess.Popen(
    [sys.executable, "-X", "utf8", "server.py", "--port", str(PORT),
     "--store", STORE, "--no-pass", "--no-ci-watch", "--demo"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    up = False
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE + "/api/rev", timeout=1).read()
            up = True
            break
        except Exception:
            time.sleep(0.5)
    need(up, "сервер поднялся")
    if not up:
        sys.exit(1)

    staff, _ = opener()
    post(staff, "/_staff_login", {"pass": "x"})

    # ── курс и занятие (id берём из реестра на диске) ──
    post(staff, "/staff/new_course", {"title": "Курс-новый"})
    reg = json.load(open(os.path.join(STORE, "реестр.json"), encoding="utf-8"))
    cid = next(c["id"] for c in reg["курсы"]
               if c.get("title") == "Курс-новый")
    need(cid.startswith("c"), "курс создан (%s)" % cid)
    post(staff, "/staff/new_lesson", {"course": cid, "title": "Занятие-новое"})
    reg = json.load(open(os.path.join(STORE, "реестр.json"), encoding="utf-8"))
    lid = next(l["id"] for l in reg["занятия"]
               if l.get("course") == cid and l.get("title") == "Занятие-новое")
    need(lid.startswith("l"), "занятие создано (%s)" % lid)
    # непустой список зачисленных: иначе курс открыт всем (семантика ядра)
    post(staff, "/staff/enroll", {"course": cid, "student": "s1"})

    # ── студент s1: базовая синхронизация — старое не «новое» ──
    stu, stujar = opener()
    post(stu, "/_login", {"student": "s1", "next": "/"})
    j = api(stu)
    need(j is not None, "api отвечает студенту")
    need(not j.get("курсы") and not j.get("занятия") and not j.get("задания"),
         "первый вызов: ничего нового (базовая линия)")

    # ── преподаватель создаёт задание ──
    post(staff, "/staff/new_task", {"lesson": lid, "title": "Задание-новое"})
    reg = json.load(open(os.path.join(STORE, "реестр.json"), encoding="utf-8"))
    tid = next(t["id"] for t in reg["задания"] if t.get("lesson") == lid)
    need(tid.startswith("t"), "задание создано (%s)" % tid)

    j = api(stu)
    need(cid in (j.get("курсы") or {}), "⚠️ на курсе")
    need(lid in (j.get("занятия") or {}), "⚠️ на занятии")
    need(any(t["id"] == tid for t in (j.get("задания") or [])),
         "⚠️ на задании")

    # ── просмотр курса снимает метку курса, но не занятия ──
    post(stu, "/newmark/seen", {"курс": cid})
    j = api(stu)
    need(cid not in (j.get("курсы") or {}), "курс: метка снята")
    need(lid in (j.get("занятия") or {}), "занятие: метка ещё стоит")
    need(any(t["id"] == tid for t in (j.get("задания") or [])),
         "задание: метка ещё стоит")

    # ── просмотр занятия снимает всё ──
    post(stu, "/newmark/seen", {"курс": cid, "занятие": lid})
    j = api(stu)
    need(not j.get("курсы") and not j.get("занятия") and not j.get("задания"),
         "после просмотра: всё чисто")

    # ── инъекция скрипта на страницы ──
    _, home = get(stu, "/")
    need("/newmark/api" in home, "скрипт в head главной")
    _, cpage = get(stu, "/course/%s" % cid)
    need("/newmark/api" in cpage and ('var C="%s"' % cid) in cpage,
          "скрипт на странице курса с id курса")
    _, tpage = get(stu, "/task/%s" % tid)
    need(('L="%s"' % lid) in tpage, "скрипт на странице задания с id занятия")

    # ── анониму и гостю api недоступен (не JSON) ──
    anon, _ = opener()
    need(api(anon) is None, "аноним: api без данных")

    # ── студент без зачисления не видит курс ──
    stu2, _ = opener()
    post(stu2, "/_login", {"student": "s2", "next": "/"})
    j = api(stu2)
    need(cid not in (j.get("курсы") or {}),
         "не зачислен: курс без метки")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

sys.exit(0 if ok else 1)
