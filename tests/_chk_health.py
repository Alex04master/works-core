# -*- coding: utf-8 -*-
"""Проверка модуля «Здоровье сервера»: страница /health/, JSON API,
карточка на панели, доступ по токену (через горячую перезагрузку).

Свой сервер: порт 8123 (PORT), хранилище _tmp_health_store (STORE).
Запуск: python -X utf8 tests/_chk_health.py
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

PORT = int(os.environ.get("PORT", "8123"))
STORE = os.environ.get("STORE", "_tmp_health_store")
BASE = "http://127.0.0.1:%d" % PORT

ok = True


def need(cond, msg):
    global ok
    print(("OK   " if cond else "FAIL ") + msg)
    ok = ok and bool(cond)


def post(path, fields, headers=None):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(BASE + path, data=data,
                                 headers=headers or {})
    try:
        r = urllib.request.urlopen(req, timeout=10)
        return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as ex:
        return ex.code, ex.read().decode("utf-8", "replace")


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

    # ── staff-сессия (--no-pass: любой пароль) ──
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    data = urllib.parse.urlencode({"pass": "x"}).encode()
    op.open(BASE + "/_staff_login", data=data, timeout=5).read()
    need(any(c.name == "staff_token" for c in cj), "staff-кука получена")

    # ── страница /health/ ──
    page = op.open(BASE + "/health/", timeout=5).read().decode("utf-8")
    for marker in ("Здоровье сервера", "🖥 Сервер", "работает", "Аптайм",
                   "Диск и объёмы", "🗂 Данные", "🧩 Модули", "📡 Мониторинг"):
        need(marker in page, "страница: есть «%s»" % marker)

    # ── полный JSON со staff-сессией ──
    obj = json.loads(op.open(BASE + "/health/api", timeout=5).read().decode("utf-8"))
    need(obj.get("ok") is True, "api: ok=true")
    need(isinstance(obj.get("uptime"), int) and obj["uptime"] >= 0, "api: аптайм")
    need(isinstance(obj.get("modules"), list) and obj["modules"], "api: список модулей")
    cnt = obj.get("counts") or {}
    need(cnt.get("courses", 0) >= 1, "api: полный снимок (курсы демо)")
    need("threads" in obj and "disk_free_gb" in obj, "api: нагрузка и диск")
    need(any(m.get("id") == "health" and m.get("state") == "ok"
             for m in obj["modules"]), "модуль health загружен без ошибок")

    # ── минимум без сессии ──
    anon = json.loads(urllib.request.urlopen(BASE + "/health/api", timeout=5).read()
                      .decode("utf-8"))
    need(anon.get("ok") is True, "api без сессии: жив")
    need("counts" not in anon and "modules" not in anon, "api без сессии: только минимум")

    # ── доступ по токену (настройки читаются при загрузке модуля,
    #    поэтому правим манифест и делаем горячую перезагрузку) ──
    man_path = os.path.join("modules", "health", "модуль.json")
    ci_token = open(os.path.join(STORE, "_ci.token"), encoding="ascii").read().strip()
    man = json.load(open(man_path, encoding="utf-8"))
    man["настройки"]["токен"] = "Тест-Токен-123"
    json.dump(man, open(man_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    code, body = post("/_reload", {"module": "health"},
                      headers={"X-CI-Token": ci_token})
    need(code == 200, "горячая перезагрузка health (code=%s)" % code)
    tok = json.loads(urllib.request.urlopen(
        BASE + "/health/api?token=" + urllib.parse.quote("Тест-Токен-123"),
        timeout=5).read().decode("utf-8"))
    need("counts" in tok, "api по токену: полный снимок")
    bad = json.loads(urllib.request.urlopen(
        BASE + "/health/api?token=" + urllib.parse.quote("неверный"),
        timeout=5).read().decode("utf-8"))
    need("counts" not in bad, "api с неверным токеном: минимум")
    # вернуть настройки к эталонным (независимо от того, что было до теста)
    man["настройки"]["токен"] = ""
    json.dump(man, open(man_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    post("/_reload", {"module": "health"}, headers={"X-CI-Token": ci_token})

    # ── карточка на главной панели ──
    home = op.open(BASE + "/staff", timeout=5).read().decode("utf-8")
    need("Здоровье сервера" in home and "/health/" in home, "карточка на панели")
    need("Сервер работает" in home, "карточка: аптайм")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

sys.exit(0 if ok else 1)
