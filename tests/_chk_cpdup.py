# -*- coding: utf-8 -*-
"""Защита от повторного импорта пакета курса (свой сервер :8093).

Проверки: экспорт демо-курса; импорт принят (новый курс); повтор того же
.zip — отказ «уже импортирован»; импорт с allowdup — принят (копия);
реестр импортов на диске.
"""
import io
import glob
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

PORT = os.environ.get("PORT", "8093")
STORE = os.environ.get("STORE", "_cpdup_store")
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


def req(path, method="GET", data=None, headers=None, binary=False):
    h = dict(headers or {})
    if jar:
        h["Cookie"] = "; ".join(c.split(";")[0] for c in jar)
    r = urllib.request.Request(BASE + path, method=method, data=data,
                               headers=h)
    try:
        with _op.open(r, timeout=15) as resp:
            jar.extend(resp.headers.get_all("Set-Cookie") or [])
            body = resp.read()
            return (resp.getcode(), dict(resp.headers),
                    body if binary else
                    body.decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        jar.extend(e.headers.get_all("Set-Cookie") or [])
        body = e.read()
        return (e.code, dict(e.headers),
                body if binary else body.decode("utf-8", "replace"))
    except Exception as e:
        return 0, {}, str(e)


def mp_post(path, fields, files):
    b = "----wccp" + str(int(time.time() * 1000))
    body = b""
    for k, v in fields.items():
        body += ('--%s\r\nContent-Disposition: form-data; name="%s"'
                 '\r\n\r\n%s\r\n' % (b, k, v)).encode("utf-8")
    for k, (fn, blob, ct) in files.items():
        body += ('--%s\r\nContent-Disposition: form-data; name="%s"; '
                 'filename="%s"\r\nContent-Type: %s\r\n\r\n'
                 % (b, k, fn, ct)).encode("utf-8") + blob + b"\r\n"
    body += ("--%s--\r\n" % b).encode("utf-8")
    return req(path, "POST", body,
               {"Content-Type": "multipart/form-data; boundary=" + b})


if os.path.isdir(STORE):
    shutil.rmtree(STORE, ignore_errors=True)
args = [sys.executable, "-X", "utf8", "server.py",
        "--port", PORT, "--store", STORE, "--no-pass", "--demo"]
proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
try:
    import socket
    t0 = time.time()
    up = False
    while time.time() - t0 < 30:
        s = socket.socket()
        s.settimeout(0.4)
        try:
            if s.connect_ex(("127.0.0.1", int(PORT))) == 0:
                up = True
                break
        finally:
            s.close()
        time.sleep(0.3)
    need(up, "сервер поднялся")
    if not up:
        raise SystemExit("OFDUP FAIL")

    req("/_staff_login", "POST",
        urllib.parse.urlencode({"pass": "x"}).encode(),
        {"Content-Type": "application/x-www-form-urlencoded"})

    # 1) экспорт демо-курса c1
    code, h, blob = req("/staff/course_export/c1", binary=True)
    zname = h.get("Content-Disposition", "")
    need(code == 200 and "attachment" in zname and blob[:2] == b"PK",
         "пакет курса скачан (.zip)", (code, zname[:60]))

    # 2) первый импорт — принят (новый курс)
    code, h, body = mp_post("/staff/course_import", {},
                            {"pkgfile": ("курс-c1.zip", blob,
                                         "application/zip")})
    loc = h.get("Location", "")
    need(code == 302 and "/staff/course/c" in loc,
         "первый импорт принят (новый курс)", (code, loc))
    new_cid = loc.rsplit("/", 1)[-1] if loc else "?"

    # 3) повтор того же .zip — отказ «уже импортирован»
    code, h, body = mp_post("/staff/course_import", {},
                            {"pkgfile": ("курс-c1.zip", blob,
                                         "application/zip")})
    loc = urllib.parse.unquote(h.get("Location", ""))
    need(code == 302 and "/staff?err=" in loc
         and "уже импортирован" in loc,
         "повтор: пакет распознан как дубль", (code, loc[:160]))

    # курса по-прежнему два (c1 + один импорт)
    reg = json.load(io.open(glob.glob(STORE + "/*.json")[0],
                            encoding="utf-8"))
    need(len(reg.get("курсы") or []) == 2,
         "курсов по-прежнему 2 (дубль не создан)",
         len(reg.get("курсы") or []))

    # 4) импорт с allowdup — принят как копия
    code, h, body = mp_post("/staff/course_import", {"allowdup": "on"},
                            {"pkgfile": ("курс-c1.zip", blob,
                                         "application/zip")})
    loc = h.get("Location", "")
    need(code == 302 and "/staff/course/c" in loc and
         loc.rsplit("/", 1)[-1] != new_cid,
         "allowdup: копия курса создана", (code, loc))
    reg = json.load(io.open(glob.glob(STORE + "/*.json")[0],
                            encoding="utf-8"))
    need(len(reg.get("курсы") or []) == 3, "курсов стало 3",
         len(reg.get("курсы") or []))

    # 5) реестр импортов на диске (один и тот же пакет = одна запись,
    #    обновлённая последним импортом)
    regs = json.load(io.open(os.path.join(STORE, "модули", "coursepkg",
                                          "импорты"),
                             encoding="utf-8"))
    last_cid = loc.rsplit("/", 1)[-1]
    need(len(regs) == 1 and all(
        isinstance(v, dict) and "когда" in v and "курс" in v
        for v in regs.values())
        and list(regs.values())[0].get("курс") == last_cid,
        "реестр импортов ведётся (запись обновлена последним импортом)",
        (len(regs), loc))
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

print("CPDUP OK" if ok else "CPDUP FAIL")
sys.exit(0 if ok else 1)
