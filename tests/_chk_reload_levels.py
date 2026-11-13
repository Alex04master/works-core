# -*- coding: utf-8 -*-
"""Проверка градации модулей (hot/lazy/restart): режим задаёт манифест,
hot применяется тумблером сразу, плавные — кнопкой «Применить изменения»
внизу панели, критические — только перезапуском сервера.

Свой сервер: порт 8128 (PORT), хранилище _tmp_reload_store (STORE).
Запуск: python -X utf8 tests/_chk_reload_levels.py
"""
import http.cookiejar
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PORT = int(os.environ.get("PORT", "8128"))
STORE = os.environ.get("STORE", "_tmp_reload_store")
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


def post(op, path, fields=None):
    data = urllib.parse.urlencode(fields or {}).encode()
    r = op.open(BASE + path, data=data, timeout=15)
    return json.loads(r.read().decode("utf-8"))


def get(op, path):
    r = op.open(BASE + path, timeout=10)
    return r.read().decode("utf-8", "replace")


shutil.rmtree(STORE, ignore_errors=True)

# временный модуль без ключа reload (проверка дефолта «плавный»)
ZZ = os.path.join("modules", "_zz_lvl")
os.makedirs(ZZ, exist_ok=True)
with open(os.path.join(ZZ, "модуль.json"), "w", encoding="utf-8") as f:
    json.dump({"id": "_zz_lvl", "name": "Тест-режим", "api": 1}, f,
              ensure_ascii=False)
with open(os.path.join(ZZ, "модуль.py"), "w", encoding="utf-8",
          newline="\n") as f:
    f.write('def register(ctx):\n'
            '    @ctx.add_route("GET", "/_zz_lvl/hello")\n'
            '    def hello(handler, params):\n'
            '        return "v1"\n')

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

    st = login_staff()

    # ── панель: бейджи режимов, кнопка внизу, селектора больше нет ──
    page = get(st, "/_modules")
    for marker in ("Режим", "⚡", "⏳", "🔒", "мгновенный", "плавный",
                   "критический", "Применить изменения", "applyAll()"):
        need(marker in page, "панель: есть «%s»" % marker)
    need("lvl-sel" not in page and "setLevel" not in page,
         "панель: режима-селектора у преподавателя нет")

    stu = login_student("s1")
    need("Мои задания" in get(stu, "/my"), "модуль mytasks работает")

    # ── HOT: тумблер применяется сразу ──
    d = post(st, "/_modules/toggle/mytasks")
    need(d.get("ok") and d.get("applied") is True and d.get("enabled") is False,
         "hot: тумблер применён сразу (%s)" % d)
    need("Мои задания" not in get(stu, "/my"), "hot: /my отключился живьём")
    d = post(st, "/_modules/toggle/mytasks")
    need(d.get("applied") is True and d.get("enabled") is True,
         "hot: включение тоже сразу")
    need("Мои задания" in get(stu, "/my"), "hot: /my вернулся")

    # ── LAZY: отложено, применяется кнопкой внизу ──
    d = post(st, "/_modules/toggle/offline")
    need(d.get("ok") and d.get("applied") is False,
         "lazy: переключено без применения (%s)" % d)
    need("офлайн" in get(st, "/staff/offline").lower(),
         "lazy: маршрут ещё жив до применения")
    page = get(st, "/_modules")
    need("⏳ по кнопке внизу" in page and "(1)" in page,
         "lazy: подсказка и счётчик на кнопке")
    d = post(st, "/_modules/apply")
    ids = [a.get("id") for a in (d.get("applied") or [])]
    need(d.get("ok") and "offline" in ids, "lazy: «Применить изменения» "
         "применил (%s)" % ids)
    need("офлайн" not in get(st, "/staff/offline").lower(),
         "lazy: маршрут снят после применения")
    post(st, "/_modules/toggle/offline")
    post(st, "/_modules/apply")
    need("офлайн" in get(st, "/staff/offline").lower(),
         "lazy: включение по кнопке работает")

    # ── выбор режима преподавателем недоступен ──
    try:
        post(st, "/_modules/level/offline", {"level": "hot"})
        need(False, "уровень преподавателем: недоступен")
    except urllib.error.HTTPError as ex:
        need(ex.code == 404, "уровень преподавателем: недоступен (404)")

    # ── RESTART: массовое применение их не трогает ──
    d = post(st, "/_modules/toggle/podskazki")
    need(d.get("applied") is False, "restart: тумблер без применения (%s)" % d)
    d = post(st, "/_modules/apply")
    need("podskazki" in (d.get("need_restart") or []),
         "restart: массовое применение отложило его (%s)" % d)
    page = get(st, "/_modules")
    need("после перезапуска" in page, "restart: плашка на панели")
    post(st, "/_modules/toggle/podskazki")

    # ── дефолт «плавный» для модуля без ключа reload ──
    d = post(st, "/_modules/toggle/_zz_lvl")
    need(d.get("applied") is False, "дефолт: без ключа reload = плавный")
    need(get(stu, "/_zz_lvl/hello") == "v1", "дефолт: маршрут жив")
    d = post(st, "/_modules/apply")
    zz = [a for a in (d.get("applied") or []) if a.get("id") == "_zz_lvl"]
    need(zz and zz[0].get("state") == "выключен",
         "дефолт: применён кнопкой (%s)" % zz)
    need(get(stu, "/_zz_lvl/hello") != "v1", "дефолт: маршрут снят")
    post(st, "/_modules/toggle/_zz_lvl")
    post(st, "/_modules/apply")
    need(get(stu, "/_zz_lvl/hello") == "v1", "дефолт: маршрут вернулся")

    # ── режим хранится только в манифесте, не в состоянии ──
    ms = json.load(open(os.path.join(STORE, "_modules_state.json"),
                        encoding="utf-8"))
    need("reload" not in ms, "в состоянии нет режимов (%s)" % list(ms))
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
    shutil.rmtree(ZZ, ignore_errors=True)

sys.exit(0 if ok else 1)
