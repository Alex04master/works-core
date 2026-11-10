# -*- coding: utf-8 -*-
"""Защита от повторного импорта офлайн-работ (свой сервер :8094).

Проверки: первый импорт принят; повтор того же файла — «дубликат,
пропущен» и версия не выросла; импорт с чекбоксом allowdup — принят
как новая версия; другой файл принят; реестр импортов на диске.
"""
import glob
import io
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PORT = os.environ.get("PORT", "8094")
STORE = os.environ.get("STORE", "_dup_store")
BASE = "http://localhost:" + PORT
ok = True


def need(cond, msg, ctx=""):
    global ok
    print(("OK   " if cond else "FAIL ") + msg +
          ("" if cond else "  | " + str(ctx)[:220]))
    ok = ok and bool(cond)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_op = urllib.request.build_opener(_NoRedirect)
jar = []


def req(path, method="GET", data=None, headers=None, jar_=None):
    h = dict(headers or {})
    if jar_:
        h["Cookie"] = "; ".join(c.split(";")[0] for c in jar_)
    r = urllib.request.Request(BASE + path, method=method, data=data,
                               headers=h)
    try:
        with _op.open(r, timeout=15) as resp:
            if jar_ is not None:
                jar_.extend(resp.headers.get_all("Set-Cookie") or [])
            return (resp.getcode(), dict(resp.headers),
                    resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if jar_ is not None:
            jar_.extend(e.headers.get_all("Set-Cookie") or [])
        return (e.code, dict(e.headers),
                e.read().decode("utf-8", "replace"))
    except Exception as e:
        return 0, {}, str(e)


def mp_post(path, fields, files, jar_=None):
    b = "----wcdup" + str(int(time.time() * 1000))
    body = b""
    for k, v in fields.items():
        body += ('--%s\r\nContent-Disposition: form-data; name="%s"'
                 '\r\n\r\n%s\r\n' % (b, k, v)).encode("utf-8")
    for k, (fn, blob, ct) in files.items():
        body += ('--%s\r\nContent-Disposition: form-data; name="%s"; '
                 'filename="%s"\r\nContent-Type: %s\r\n\r\n'
                 % (b, k, fn, ct)).encode("utf-8") + blob + b"\r\n"
    body += ("--%s--\r\n" % b).encode("utf-8")
    h = {"Content-Type": "multipart/form-data; boundary=" + b}
    if jar_:
        h["Cookie"] = "; ".join(c.split(";")[0] for c in jar_)
    return req(path, "POST", body, h, jar_=jar_)


def start_server():
    if os.path.isdir(STORE):
        import shutil
        shutil.rmtree(STORE, ignore_errors=True)
    args = [sys.executable, "-X", "utf8", "server.py",
            "--port", PORT, "--store", STORE, "--no-pass", "--demo"]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    t0 = time.time()
    import socket
    while time.time() - t0 < 30:
        s = socket.socket()
        s.settimeout(0.4)
        try:
            if s.connect_ex(("127.0.0.1", int(PORT))) == 0:
                return proc
        finally:
            s.close()
        time.sleep(0.3)
    proc.terminate()
    raise RuntimeError("сервер не поднялся")


proc = start_server()
try:
    # преподаватель
    code, h, body = req("/_staff_login")
    code, h, body = req("/_staff_login", "POST",
                        urllib.parse.urlencode({"pass": "x"}).encode(),
                        {"Content-Type": "application/x-www-form-urlencoded"},
                        jar_=jar)
    need(code in (200, 302), "преподаватель вошёл", code)

    # демо-задание t1 и курс
    reg = json.load(io.open(glob.glob(STORE + "/*.json")[0],
                            encoding="utf-8"))
    t1 = next(t for t in reg["задания"] if t.get("id") == "t1")
    need(t1.get("id") == "t1", "демо-задание t1 найдено")

    def work(answers, when):
        return json.dumps({
            "формат": "works-core-работа", "версия": 1,
            "задание": "t1", "курс": "c1",
            "студент": {"fio": "Иванов И.И.", "group": "П-21"},
            "ответы": answers, "когда": when,
        }, ensure_ascii=False).encode("utf-8")

    A = {"width": "24", "length": "18", "height": "4.2",
         "detector_type": "ИП 212", "detectors_num": "6",
         "loops": "2", "justification": "дубль-тест"}
    blob1 = work(A, "2026-11-10 12:00")

    # 1) первый импорт — принят
    code, h, body = mp_post("/staff/offline/import", {},
                            {"work": ("работа.json", blob1,
                                      "application/json")}, jar_=jar)
    need(code == 200 and "принято 1" in body and "дубликатов" not in body,
         "первый импорт принят", body[:200])

    # 2) повтор того же файла — дубликат пропущен
    code, h, body = mp_post("/staff/offline/import", {},
                            {"work": ("работа.json", blob1,
                                      "application/json")}, jar_=jar)
    need(code == 200 and "принято 0" in body and "дубликатов пропущено 1"
         in body and "дубликат — уже импортирована" in body,
         "повтор: дубликат распознан и пропущен", body[:300])

    # версия не выросла
    reg = json.load(io.open(glob.glob(STORE + "/*.json")[0],
                            encoding="utf-8"))
    subs = reg.get("сдачи") or {}
    if isinstance(subs, dict):
        subs = list(subs.values())
    sub = next(s for s in subs if s.get("task") == "t1"
               and s.get("student") == "s1")
    need(len(sub.get("versions") or []) == 1,
         "версий по-прежнему 1 (дубль не создал)",
         len(sub.get("versions") or []))

    # 3) импорт с чекбоксом allowdup — принят как новая версия
    code, h, body = mp_post("/staff/offline/import",
                            {"allowdup": "1"},
                            {"work": ("работа.json", blob1,
                                      "application/json")}, jar_=jar)
    need(code == 200 and "принято 1" in body,
         "allowdup: дубль принят как новая версия", body[:200])
    reg = json.load(io.open(glob.glob(STORE + "/*.json")[0],
                            encoding="utf-8"))
    subs = reg.get("сдачи") or {}
    if isinstance(subs, dict):
        subs = list(subs.values())
    sub = next(s for s in subs if s.get("task") == "t1"
               and s.get("student") == "s1")
    need(len(sub.get("versions") or []) == 2,
         "версий стало 2", len(sub.get("versions") or []))

    # 4) другой файл (изменены ответы) — принят без чекбокса
    B = dict(A, justification="дубль-тест v2")
    code, h, body = mp_post("/staff/offline/import", {},
                            {"work": ("работа2.json", work(B, "12:05"),
                                      "application/json")}, jar_=jar)
    need(code == 200 and "принято 1" in body,
         "другой файл принят (не дубль)", body[:200])

    # 5) реестр импортов на диске
    regs = json.load(io.open(os.path.join(STORE, "модули", "offline",
                                          "импорты"),
                             encoding="utf-8"))
    need(len(regs) == 2 and all(
        isinstance(v, dict) and "когда" in v and "версия" in v
        for v in regs.values()),
        "реестр импортов ведётся (2 записи)", len(regs))
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

print("OFDUP OK" if ok else "OFDUP FAIL")
sys.exit(0 if ok else 1)
