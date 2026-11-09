# -*- coding: utf-8 -*-
"""Баг-репорты: регресс-тест (сам поднимает сервер :8096, своё хранилище).

Проверки: кнопка/плашка на страницах, отправка студентом и анонимом,
скриншот, список в панели, статус, удаление, счётчик новых у staff.
"""
import base64
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
PORT = 8096
BASE = "http://localhost:%d" % PORT
STORE = os.path.join(ROOT, "_bugrep_store")
PY = sys.executable
KV = os.path.join(STORE, "модули", "bugrep", "баги.json")

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDw"
    "AChwGA60e6kgAAAABJRU5ErkJggg==")

ok = True
proc = None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_op = urllib.request.build_opener(_NoRedirect)


def need(cond, msg, ctx=""):
    global ok
    print(("OK   " if cond else "FAIL ") + msg + ("" if cond else
                                                  "  | " + str(ctx)[:200]))
    ok = ok and bool(cond)


def req(path, method="GET", data=None, headers=None, jar=None):
    r = urllib.request.Request(BASE + path, method=method, data=data,
                               headers=headers or {})
    try:
        with _op.open(r, timeout=15) as resp:
            if jar is not None:
                jar.extend(resp.headers.get_all("Set-Cookie") or [])
            return (resp.getcode(), dict(resp.headers),
                    resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if jar is not None:
            jar.extend(e.headers.get_all("Set-Cookie") or [])
        return (e.code, dict(e.headers),
                e.read().decode("utf-8", "replace"))
    except Exception as e:
        return 0, {}, str(e)


def form_post(path, fields, jar=None):
    d = urllib.parse.urlencode(fields).encode("utf-8")
    h = {"Content-Type": "application/x-www-form-urlencoded"}
    if jar:
        h["Cookie"] = "; ".join(c.split(";")[0] for c in jar)
    return req(path, "POST", d, h, jar=jar)


def mp_post(path, fields, files, jar=None):
    b = "----wc" + str(int(time.time() * 1000))
    body = b""
    for k, v in fields.items():
        body += ('--%s\r\nContent-Disposition: form-data; name="%s"'
                 '\r\n\r\n%s\r\n' % (b, k, v)).encode("utf-8")
    for k, (fn, blob) in files.items():
        body += ('--%s\r\nContent-Disposition: form-data; name="%s"; '
                 'filename="%s"\r\nContent-Type: image/png\r\n\r\n'
                 % (b, k, fn)).encode("utf-8") + blob + b"\r\n"
    body += ("--%s--\r\n" % b).encode("utf-8")
    h = {"Content-Type": "multipart/form-data; boundary=" + b}
    if jar:
        h["Cookie"] = "; ".join(c.split(";")[0] for c in jar)
    return req(path, "POST", body, h, jar=jar)


def get(path, jar=None):
    h = {}
    if jar:
        h["Cookie"] = "; ".join(c.split(";")[0] for c in jar)
    return req(path, headers=h, jar=jar)


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


try:
    if os.path.isdir(STORE):
        shutil.rmtree(STORE)
    proc = subprocess.Popen(
        [PY, "-X", "utf8", os.path.join(ROOT, "server.py"),
         "--port", str(PORT), "--store", STORE, "--no-pass", "--demo"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    need(wait_port(PORT), "сервер поднялся (:8096)")

    # ── фрагменты на страницах ────────────────────────────────────────
    code, h, body = get("/_login")
    need("wc-bug-btn" in body and "wc-bug-modal" in body,
         "кнопка «🐞 Баг» есть на странице входа")
    need("_wc_keep" in body,
         "горячий фикс виджета файлов подключён (page.head)")

    # ── студент отправляет репорт со скриншотом ───────────────────────
    jar = []
    form_post("/_login", {"student": "s1"}, jar=jar)
    code, h, body = mp_post("/bugrep",
                            {"title": "Кнопка импорта не работает",
                             "desc": "Нажимаю — схема не прикрепляется",
                             "page": "/task/t1", "next": "/task/t1"},
                            {"shot": ("bug.png", PNG)}, jar=jar)
    need(code == 200 and "баг записан" in body,
         "студент отправил репорт со скриншотом", (code, body[:120]))
    items = json.loads(io.open(KV, encoding="utf-8").read())
    need(len(items) == 1 and items[0]["студент"] == "s1",
         "репорт сохранён с привязкой к студенту", items[:1])
    need(items[0].get("фио") and items[0].get("группа"),
         "ФИО и группа подставлены", items[0].get("фио"))
    need(items[0].get("скрин", "").endswith(".png"),
         "скриншот сохранён", items[0].get("скрин"))
    need(os.path.isfile(os.path.join(STORE, "модули", "bugrep",
                                     items[0]["скрин"])),
         "файл скриншота на диске")
    need("/task/t1" in items[0].get("страница", ""),
         "страница бага записана", items[0].get("страница"))

    # ── анонимный репорт ──────────────────────────────────────────────
    code, h, body = form_post("/bugrep", {
        "title": "Не заходит", "desc": "Пароль не подходит",
        "page": "/_login", "next": "/"})
    need(code == 200 and "баг записан" in body,
         "анонимный репорт принят")
    items = json.loads(io.open(KV, encoding="utf-8").read())
    need(len(items) == 2 and items[-1]["фио"] == "не залогинен",
         "анонимный репорт помечен", items[-1].get("фио"))

    # ── панель преподавателя ──────────────────────────────────────────
    sj = []
    form_post("/_staff_login", {"pass": "x"}, jar=sj)
    code, h, body = get("/_modules", jar=sj)
    need("wc-bug-staff" in body,
         "плашка «Баг-репорты» видна преподавателю")
    need("2 новых" in body, "плашка показывает число новых", "")
    code, h, body = get("/bugrep", jar=sj)
    need(code == 200 and "Кнопка импорта не работает" in body,
         "список репортов открывается")
    need("Иванов" in body and "не залогинен" in body,
         "в списке студент и аноним")
    need("в работе" in body, "кнопка перевода статуса есть")

    # ── скриншот ──────────────────────────────────────────────────────
    rid = items[0]["id"]
    code, h, body = get("/bugrep/shot/%d" % rid, jar=sj)
    need(code == 200 and "image/png" in h.get("Content-Type", ""),
         "скриншот отдаётся преподавателю", (code, h.get("Content-Type")))
    code, h, body = get("/bugrep/shot/%d" % rid)
    # платформа отвечает на staff-маршрут страницей логина с кодом 200:
    # проверяем, что КАРТИНКА не отдаётся (Content-Type не image/*)
    need(code in (302, 403) or "image/" not in h.get("Content-Type", ""),
         "скриншот не отдаётся без staff-доступа",
         (code, h.get("Content-Type")))

    # ── статус и удаление ─────────────────────────────────────────────
    code, h, body = form_post("/bugrep/status",
                              {"id": rid, "status": "в работе"}, jar=sj)
    need(code == 302, "статус переключён (redirect)")
    items = json.loads(io.open(KV, encoding="utf-8").read())
    need(next(b for b in items if b["id"] == rid)["статус"] == "в работе",
         "статус записан в хранилище")
    code, h, body = form_post("/bugrep/delete", {"id": rid}, jar=sj)
    need(code == 302, "репорт удалён (redirect)")
    items = json.loads(io.open(KV, encoding="utf-8").read())
    need(all(b["id"] != rid for b in items), "репорта больше нет")
    need(not os.path.exists(os.path.join(STORE, "модули", "bugrep",
                                         "скрин-%d.png" % rid)),
         "скриншот удалён вместе с репортом")

    # ── битый репорт без текста не сохраняется ────────────────────────
    code, h, body = form_post("/bugrep", {"title": "", "desc": "",
                                          "next": "/_login"})
    items = json.loads(io.open(KV, encoding="utf-8").read())
    need(len(items) == 1, "пустой репорт отклонён", len(items))
finally:
    if proc:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
    shutil.rmtree(STORE, ignore_errors=True)

print("BUGREP OK" if ok else "BUGREP FAIL")
sys.exit(0 if ok else 1)
