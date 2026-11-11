# -*- coding: utf-8 -*-
"""Таблица бригад с батч-сохранением (свой сервер :8091).

Проверки: создание бригад, повторные имена отклоняются, лимит состава,
переименование, флаг «закрыта для сдач» с переносом при переименовании,
расформирование, чужой студент отклоняется.
"""
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

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PORT = os.environ.get("PORT", "8091")
STORE = os.environ.get("STORE", "_brsave_store")
BASE = "http://localhost:" + PORT
ok = True


def need(c, m, ctx=""):
    global ok
    print(("OK   " if c else "FAIL ") + m + ("" if c else "  | "
                                             + str(ctx)[:220]))
    ok = ok and bool(c)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_op = urllib.request.build_opener(_NoRedirect)
jar = []


def req(path, method="GET", data=None, headers=None):
    h = dict(headers or {})
    if jar:
        h["Cookie"] = "; ".join(c.split(";")[0] for c in jar)
    r = urllib.request.Request(BASE + path, method=method, data=data,
                               headers=h)
    try:
        with _op.open(r, timeout=15) as resp:
            jar.extend(resp.headers.get_all("Set-Cookie") or [])
            return (resp.getcode(), dict(resp.headers),
                    resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        jar.extend(e.headers.get_all("Set-Cookie") or [])
        return (e.code, dict(e.headers),
                e.read().decode("utf-8", "replace"))
    except Exception as e:
        return 0, {}, str(e)


def save(payload):
    return req("/staff/brigades_save", "POST",
               urllib.parse.urlencode(
                   {"course": "c1",
                    "data": json.dumps(payload, ensure_ascii=False)}
               ).encode("utf-8"),
               {"Content-Type": "application/x-www-form-urlencoded"})


if os.path.isdir(STORE):
    shutil.rmtree(STORE, ignore_errors=True)
proc = subprocess.Popen(
    [sys.executable, "-X", "utf8", "server.py", "--port", PORT,
     "--store", STORE, "--demo", "--no-pass"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    import glob
    import socket
    t0 = time.time()
    while time.time() - t0 < 30:
        s = socket.socket()
        s.settimeout(0.4)
        try:
            if s.connect_ex(("127.0.0.1", int(PORT))) == 0:
                break
        finally:
            s.close()
        time.sleep(0.3)

    req("/_staff_login", "POST",
        urllib.parse.urlencode({"pass": "x"}).encode(),
        {"Content-Type": "application/x-www-form-urlencoded"})

    def brig(sid):
        reg = json.load(io.open(glob.glob(STORE + "\\реестр.json")[0],
                                encoding="utf-8"))
        for st in reg["студенты"]:
            if st.get("id") == sid:
                return (st.get("бригада") or "").strip()
        return "<нет>"

    # 1) создать две бригады
    code, h, body = save({"rows": [
        {"old": "", "name": "Альфа", "off": False,
         "members": [{"sid": "s1"}, {"sid": "s2"}, {"sid": "s3"}]},
        {"old": "", "name": "Бета", "off": False,
         "members": [{"sid": "s4"}, {"sid": "s5"}]}]})
    need(code == 200 and json.loads(body).get("ok"), "бригады созданы",
         body[:120])
    need(brig("s1") == "Альфа" and brig("s3") == "Альфа"
         and brig("s4") == "Бета" and brig("s6") == "",
         "составы записаны студентам",
         (brig("s1"), brig("s4"), brig("s6")))

    # 2) повторные имена (в т.ч. в другом регистре) — отказ
    code, h, body = save({"rows": [
        {"old": "Альфа", "name": "Альфа-2", "members": [{"sid": "s1"}]},
        {"old": "", "name": "альфа-2", "members": [{"sid": "s4"}]}]})
    j = json.loads(body)
    need(j.get("ok") is False and "повторное имя" in j.get("err", ""),
         "повторное имя бригады отклонено", body[:120])
    need(brig("s1") == "Альфа" and brig("s4") == "Бета",
         "после отказа ничего не изменилось", (brig("s1"), brig("s4")))

    # 3) превышение лимита состава (демо-лимит 3)
    code, h, body = save({"rows": [
        {"old": "", "name": "Гамма", "members": [
            {"sid": "s1"}, {"sid": "s2"}, {"sid": "s3"}, {"sid": "s6"}]}]})
    j = json.loads(body)
    need(j.get("ok") is False and "лимита" in j.get("err", ""),
         "лимит состава отклоняет", body[:120])

    # 4) переименование
    code, h, body = save({"rows": [
        {"old": "Альфа", "name": "Альфа-2",
         "members": [{"sid": "s1"}, {"sid": "s2"}, {"sid": "s3"}]},
        {"old": "Бета", "name": "Бета",
         "members": [{"sid": "s4"}, {"sid": "s5"}]}]})
    need(json.loads(body).get("ok"), "переименование принято")
    need(brig("s1") == "Альфа-2" and brig("s3") == "Альфа-2",
         "студенты переименованы", (brig("s1"), brig("s3")))

    # 5) флаг «закрыта для сдач» + перенос при переименовании
    code, h, body = save({"rows": [
        {"old": "Альфа-2", "name": "Альфа-2",
         "members": [{"sid": "s1"}, {"sid": "s2"}, {"sid": "s3"}]},
        {"old": "Бета", "name": "Дельта", "off": True,
         "members": [{"sid": "s4"}, {"sid": "s5"}]}]})
    need(json.loads(body).get("ok"), "переименование с флагом принято")
    reg = json.load(io.open(glob.glob(STORE + "\\реестр.json")[0],
                            encoding="utf-8"))
    off = reg.get("бригады_откл") or {}
    need(off.get("Дельта") and not off.get("Бета") and not off.get("Альфа-2"),
         "флаг «закрыта» перенесён на новое имя", off)

    # 6) расформирование (в payload только Альфа-2)
    code, h, body = save({"removed": ["Дельта"], "rows": [
        {"old": "Альфа-2", "name": "Альфа-2",
         "members": [{"sid": "s1"}, {"sid": "s2"}, {"sid": "s3"}]}]})
    need(json.loads(body).get("ok"), "сохранение без Дельты принято")
    need(brig("s4") == "" and brig("s5") == "",
         "расформированная бригада снята со студентов",
         (brig("s4"), brig("s5")))

    # 7) чужой студент — отказ
    code, h, body = save({"rows": [
        {"old": "", "name": "Зета",
         "members": [{"sid": "s1"}, {"sid": "zz"}]}]})
    j = json.loads(body)
    need(j.get("ok") is False and "не из этого курса" in j.get("err", ""),
         "чужой студент отклонён", body[:120])

    # 8) страница курса содержит новую таблицу
    code, h, body = req("/staff/course/c1")
    need("wc-br-save" in body and "wc-br-wrap" in body
         and '"rows"' in body and "wc-br-new" in body,
         "таблица бригад на странице курса")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

print("BRSAVE OK" if ok else "BRSAVE FAIL")
sys.exit(0 if ok else 1)
