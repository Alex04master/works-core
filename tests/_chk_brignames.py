# -*- coding: utf-8 -*-
"""Проверка имён участников бригадной сдачи: поле на странице задания,
сохранение в версии сдачи, показ студенту (/mysub) и преподавателю
(/staff/sub).

Свой сервер: порт 8126 (PORT), хранилище _tmp_brignames_store (STORE).
Запуск: python -X utf8 tests/_chk_brignames.py
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

PORT = int(os.environ.get("PORT", "8126"))
STORE = os.environ.get("STORE", "_tmp_brignames_store")
BASE = "http://127.0.0.1:%d" % PORT

ok = True


def need(cond, msg):
    global ok
    print(("OK   " if cond else "FAIL ") + msg)
    ok = ok and bool(cond)


def login_student(name):
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    data = urllib.parse.urlencode({"student": name, "next": "/"}).encode()
    op.open(BASE + "/_login", data=data, timeout=10).read()
    return op


def login_staff():
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    data = urllib.parse.urlencode({"pass": "x"}).encode()
    op.open(BASE + "/_staff_login", data=data, timeout=10).read()
    return op


def post(op, path, fields):
    data = urllib.parse.urlencode(fields).encode()
    r = op.open(BASE + path, data=data, timeout=10)
    return r.geturl(), r.read().decode("utf-8", "replace")


def get(op, path):
    r = op.open(BASE + path, timeout=10)
    return r.read().decode("utf-8", "replace")


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

    s1 = login_student("s1")
    post(s1, "/brigade", {"course": "c1", "act": "create", "name": "БР-Неймс"})

    # ── поле на странице задания ──
    page = get(s1, "/task/t1")
    need('name="wc_names"' in page, "поле «Кто сдавал вместе» на странице")
    need("Кто сдавал вместе с вами" in page, "подпись поля")

    # ── бригадная сдача с именами ──
    post(s1, "/api/submit", {
        "task": "t1", "brigade": "БР-Неймс",
        "wc_names": "Иванов И.И., Петров П.П.",
        "width": "10", "length": "10", "height": "2",
        "detector_type": "IP212", "detectors_num": "4",
        "loops": "1", "justification": "проверка участников"})
    reg = json.load(open(os.path.join(STORE, "реестр.json"), encoding="utf-8"))
    sub = reg["сдачи"].get("t1__s1") or {}
    v1 = (sub.get("versions") or [{}])[0]
    need(v1.get("участники_имена") == ["Иванов И.И.", "Петров П.П."],
         "имена сохранены в версии (%s)" % v1.get("участники_имена"))

    # ── студент видит на странице сдачи ──
    my = get(s1, "/mysub/t1")
    need("Указали участников: Иванов И.И., Петров П.П." in my,
         "/mysub: имена показаны")

    # ── преподаватель видит на странице сдачи ──
    st = login_staff()
    sp = get(st, "/staff/sub/t1__s1")
    need("Указали участников: Иванов И.И., Петров П.П." in sp,
         "/staff/sub: имена показаны")

    # ── вторая версия: имена обновляются ──
    post(s1, "/api/submit", {
        "task": "t1", "brigade": "БР-Неймс",
        "wc_names": "Иванов И.И., Сидоров С.С.",
        "width": "12", "length": "10", "height": "2",
        "detector_type": "IP212", "detectors_num": "4",
        "loops": "1", "justification": "версия 2"})
    reg = json.load(open(os.path.join(STORE, "реестр.json"), encoding="utf-8"))
    v2 = reg["сдачи"]["t1__s1"]["versions"][-1]
    need(v2.get("участники_имена") == ["Иванов И.И.", "Сидоров С.С."],
         "вторая версия: имена обновлены")
    my2 = get(s1, "/mysub/t1")
    need("Сидоров С.С." in my2, "/mysub: показана последняя версия")

    # ── без имён поле просто не сохраняется ──
    post(s1, "/api/submit", {
        "task": "t1", "brigade": "БР-Неймс",
        "width": "14", "length": "10", "height": "2",
        "detector_type": "IP212", "detectors_num": "4",
        "loops": "1", "justification": "версия 3 без имён"})
    reg = json.load(open(os.path.join(STORE, "реестр.json"), encoding="utf-8"))
    v3 = reg["сдачи"]["t1__s1"]["versions"][-1]
    need("участники_имена" not in v3, "без имён: ключ не пишется")

    # ── личная сдача: имена тоже сохраняются (про запас) ──
    post(s1, "/api/submit", {
        "task": "t1", "wc_names": "Иванов И.И.",
        "width": "16", "length": "10", "height": "2",
        "detector_type": "IP212", "detectors_num": "4",
        "loops": "1", "justification": "лично"})
    reg = json.load(open(os.path.join(STORE, "реестр.json"), encoding="utf-8"))
    v4 = reg["сдачи"]["t1__s1"]["versions"][-1]
    need(v4.get("участники_имена") == ["Иванов И.И."],
         "личная сдача: имена сохранены")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

sys.exit(0 if ok else 1)
