# -*- coding: utf-8 -*-
"""CI (горячая перезагрузка модулей): регресс-тест.

Запуск: python -X utf8 tests/_chk_ci.py   (сам поднимает сервер :8097,
хранилище _ci_store; по окончании сервер гасится, хранилище удаляется).

Проверки: POST /_reload (токен/localhost), перезагрузка существующего
модуля, новый модуль «на лету», правка кода модуля без рестарта,
битый файл не валит работающий модуль, откат при сбое register,
удаление модуля, module=all, студент остаётся залогинен после рестарта.
"""
import glob
import io
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.getcwd()
PORT = 8097
BASE = "http://localhost:%d" % PORT
STORE = os.path.join(ROOT, "_ci_store")
PY = sys.executable or "python"

TMP_MOD = os.path.join(ROOT, "modules", "_zz_ci_tmp")
ok = True
proc = None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def need(cond, msg, ctx=""):
    global ok
    print(("OK   " if cond else "FAIL ") + msg + ("" if cond else
                                                  "  | " + str(ctx)[:200]))
    ok = ok and bool(cond)


def http(path, method="GET", data=None, headers=None, jar=None):
    """Запрос; если jar - куки из ответа сохраняются (Set-Cookie).
    Редиректы НЕ следуются: нужен сырой код (302 и куки из него)."""
    req = urllib.request.Request(BASE + path, method=method,
                                 data=data, headers=headers or {})
    try:
        with _opener.open(req, timeout=15) as r:
            if jar is not None:
                jar.extend(r.headers.get_all("Set-Cookie") or [])
            return r.getcode(), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if jar is not None:
            jar.extend(e.headers.get_all("Set-Cookie") or [])
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)


def post_form(path, fields, headers=None, jar=None):
    data = urllib.parse.urlencode(fields).encode("utf-8")
    h = dict(headers or {})
    h["Content-Type"] = "application/x-www-form-urlencoded"
    if jar:
        h["Cookie"] = "; ".join(c.split(";")[0] for c in jar)
    return http(path, method="POST", data=data, headers=h, jar=jar)


def get_with(path, jar):
    h = {"Cookie": "; ".join(c.split(";")[0] for c in jar)} if jar else {}
    return http(path, headers=h)


def wait_port(port, timeout=25):
    import socket
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = socket.socket()
        s.settimeout(0.5)
        try:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        finally:
            s.close()
        time.sleep(0.3)
    return False


def start_server(extra=()):
    global proc
    proc = subprocess.Popen(
        [PY, "-X", "utf8", os.path.join(ROOT, "server.py"),
         "--port", str(PORT), "--store", STORE, "--no-pass", "--demo",
         *extra],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return wait_port(PORT)


def stop_server():
    global proc
    if proc:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        proc = None
    time.sleep(1)


def token():
    with open(os.path.join(STORE, "_ci.token"), encoding="ascii") as f:
        return f.read().strip()


def reload_call(module, tok, extra_headers=None):
    h = dict(extra_headers or {})
    if tok:
        h["X-CI-Token"] = tok
    return post_form("/_reload", {"module": module}, headers=h)


TMP_MAN = json.dumps({"id": "_zz_ci_tmp", "name": "CI-временный",
                      "api": 1}, ensure_ascii=False)
TMP_V1 = (
    "def register(ctx):\n"
    "    @ctx.add_route(\"GET\", \"/_zz_ci_tmp/hello\")\n"
    "    def hello(handler, params):\n"
    "        return \"v1\"\n"
    "    ctx.on(\"page.head\", lambda **kw: None)\n"
)
TMP_V2 = TMP_V1.replace("v1", "v2")
TMP_V3 = TMP_V1.replace("v1", "v3")
TMP_BAD = "def register(ctx):\n    это синтаксическая ошибка\n"

try:
    # ── чистка и старт ────────────────────────────────────────────
    if os.path.isdir(TMP_MOD):
        shutil.rmtree(TMP_MOD)
    if os.path.isdir(STORE):
        shutil.rmtree(STORE)
    need(start_server(), "сервер поднялся (:8097)")
    need(wait_port(PORT), "порт слушается")

    t = token()
    need(len(t) >= 16, "токен CI создан в хранилище (_ci.token)")

    # вход преподавателя (для страниц staff)
    staffjar = []
    post_form("/_staff_login", {"pass": "x"}, jar=staffjar)

    # ── защита маршрута ───────────────────────────────────────────
    code, body = post_form("/_reload", {"module": "all"})
    need(code == 403, "без токена: отказ (403)", "%s %s" % (code, body[:80]))
    code, body = reload_call("all", "wrong-token-123456")
    need(code == 403, "с чужим токеном: отказ (403)", (code, body[:80]))

    # ── перезагрузка существующего модуля ─────────────────────────
    code, body = reload_call("sim", t)
    need(code == 200 and '"ok":true' in body.replace(" ", ""),
         "перезагрузка модуля sim: ok", body[:120])
    code, body = get_with("/_modules", staffjar)
    need(code == 200 and "sim" in body, "/_modules: sim в списке",
         (code, len(body)))

    # ── новый модуль «на лету» (без рестарта) ─────────────────────
    os.makedirs(TMP_MOD)
    io.open(os.path.join(TMP_MOD, "модуль.json"), "w",
            encoding="utf-8").write(TMP_MAN)
    io.open(os.path.join(TMP_MOD, "модуль.py"), "w",
            encoding="utf-8").write(TMP_V1)
    code, body = reload_call("_zz_ci_tmp", t)
    need(code == 200, "новый модуль загружен без рестарта", body[:120])
    code, body = http("/_zz_ci_tmp/hello")
    need(code == 200 and "v1" in body, "маршрут нового модуля жив: v1",
         "%s %s" % (code, body[:60]))

    # ── правка кода модуля без рестарта ───────────────────────────
    io.open(os.path.join(TMP_MOD, "модуль.py"), "w",
            encoding="utf-8").write(TMP_V2)
    code, body = reload_call("_zz_ci_tmp", t)
    need(code == 200, "правка кода: перезагрузка ok", body[:120])
    code, body = http("/_zz_ci_tmp/hello")
    need(code == 200 and "v2" in body, "правка применилась на лету: v2",
         body[:60])

    # ── битый файл не валит работающий модуль ─────────────────────
    io.open(os.path.join(TMP_MOD, "модуль.py"), "w",
            encoding="utf-8").write(TMP_BAD)
    code, body = reload_call("_zz_ci_tmp", t)
    need(code == 500 and "сбой" in body,
         "битый файл: ok=false, модуль помечен сбой", body[:160])
    code, body = http("/_zz_ci_tmp/hello")
    need(code == 200 and "v2" in body,
         "старый код продолжает работать (v2)", body[:60])

    # ── исправление и повторный деплой ────────────────────────────
    io.open(os.path.join(TMP_MOD, "модуль.py"), "w",
            encoding="utf-8").write(TMP_V3)
    code, body = reload_call("_zz_ci_tmp", t)
    need(code == 200, "исправленный файл: перезагрузка ok", body[:120])
    code, body = http("/_zz_ci_tmp/hello")
    need(code == 200 and "v3" in body, "новая версия жива: v3", body[:60])

    # ── module=all ────────────────────────────────────────────────
    code, body = reload_call("all", t)
    need(code == 200 and '"ok":true' in body.replace(" ", "")
         and "_zz_ci_tmp" in body,
         "module=all перезагружает всё живое", body[:200])

    # ── студент не вылетает после рестарта ────────────────────────
    jar = []
    code, body = post_form("/_login", {"student": "s1"}, jar=jar)
    need(code == 302 and jar, "студент s1 вошёл (кука выдана)", jar)
    stop_server()
    need(start_server(), "сервер перезапущен (то же хранилище)")
    code, body = get_with("/course/c1", jar)
    need(code == 200 and "Демо" in body,
         "студент остался залогинен после рестарта (куки на ключе "
         "из хранилища)", code)

    # ── удаление модуля с диска ───────────────────────────────────
    shutil.rmtree(TMP_MOD)
    code, body = reload_call("_zz_ci_tmp", t)
    need("выключен" in body and "нет на диске" in body and code == 200,
         "модуль снят с сервера после удаления папки", (code, body[:160]))
    code, body = get_with("/_zz_ci_tmp/hello", jar)
    need("v3" not in body,
         "маршрут удалённого модуля больше не отвечает (нет «v3»)",
         (code, body[:60]))

    # ── пробный CI-чек (ci.py check): свой порт, сервер теста гасим ─
    stop_server()
    r = subprocess.run([PY, "-X", "utf8", os.path.join(ROOT, "ci.py"),
                        "check"], capture_output=True)
    out = r.stdout.decode("utf-8", "replace")
    need(r.returncode == 0 and "пробный старт: OK" in out,
         "ci.py check: зелёный", out[-300:])
finally:
    stop_server()
    shutil.rmtree(STORE, ignore_errors=True)
    if os.path.isdir(TMP_MOD):
        shutil.rmtree(TMP_MOD, ignore_errors=True)
    for pyc in glob.glob(os.path.join(ROOT, "modules", "**", "__pycache__"),
                         recursive=True):
        shutil.rmtree(pyc, ignore_errors=True)

print("CI OK" if ok else "CI FAIL")
sys.exit(0 if ok else 1)
