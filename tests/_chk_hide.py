# -*- coding: utf-8 -*-
"""Проверка фильтра студентов на странице курса (копия живых данных).

Для каждого курса считается ожидаемое число видимых студентов по правилам
доступа (индивидуальное зачисление и/или группы; открытый курс - все) и
сравнивается с карточкой «Студенты».
"""
import http.cookiejar
import io
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import os  # noqa: E402
STORE = "_hidecheck"
BASE = "http://localhost:8095"
ok = True


def need(c, m, ctx=""):
    global ok
    print(("OK   " if c else "FAIL ") + m + ("" if c else "  | "
                                             + str(ctx)[:200]))
    ok = ok and bool(c)


if __import__("os").path.isdir(STORE):
    shutil.rmtree(STORE, ignore_errors=True)
src = ""
for cand in (r"E:\AI\works-core\данные",
             r"D:\AI\works-core\данные"):
    if os.path.isdir(cand):
        src = cand
        break
if not src:
    print("SKIP: исходные данные не найдены (E:/D:)")
    sys.exit(0)
shutil.copytree(src, STORE)

proc = subprocess.Popen(
    [sys.executable, "-X", "utf8", "server.py", "--port", "8095",
     "--store", STORE, "--no-pass"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    import socket
    t0 = time.time()
    while time.time() - t0 < 30:
        s = socket.socket()
        s.settimeout(0.4)
        try:
            if s.connect_ex(("127.0.0.1", 8095)) == 0:
                break
        finally:
            s.close()
        time.sleep(0.3)

    class NR(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(NR(),
                                     urllib.request.HTTPCookieProcessor(jar))
    d = urllib.parse.urlencode({"pass": "x"}).encode()
    try:
        op.open(urllib.request.Request(BASE + "/_staff_login", data=d,
                                       method="POST"), timeout=10)
    except urllib.error.HTTPError:
        pass

    reg = json.load(io.open(STORE + "\\реестр.json", encoding="utf-8"))
    studs = reg.get("студенты") or {}
    students = list(studs.values()) if isinstance(studs, dict) else studs
    n_all = len(students)
    print("всего студентов в системе:", n_all)

    def expected(cid):
        c = next((x for x in reg["курсы"] if x.get("id") == cid), None)
        if not c:
            return 0
        studs_in = c.get("студенты") or []
        groups = [g for g in (c.get("группы") or []) if g]
        if not studs_in and not groups:
            return n_all  # открытый курс
        n = 0
        for s in students:
            sid = s.get("id", "")
            if sid in studs_in:
                n += 1
            elif groups and (s.get("group", "") or "").strip() in groups:
                n += 1
        return n

    for cid in ("c1", "c2", "c3"):
        c = next((x for x in reg["курсы"] if x.get("id") == cid), None)
        if not c:
            continue
        try:
            b = op.open(BASE + "/staff/course/" + cid,
                        timeout=10).read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            need(False, cid + ": страница курса", e.code)
            continue
        m = re.search(r"<h2>Студенты \((\d+)\)</h2>", b)
        shown = int(m.group(1)) if m else -1
        exp = expected(cid)
        hint = "Показаны зачисленные на курс" in b
        need(shown == exp, "%s «%s»: показано %d, ожидалось %d"
             % (cid, (c.get("title") or "?")[:24], shown, exp), shown)
        if exp != n_all:
            need(hint, cid + ": подсказка «показаны зачисленные» на месте")
        else:
            need(not hint, cid + ": открытому курсу подсказка не нужна")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

print("HIDE OK" if ok else "HIDE FAIL")
sys.exit(0 if ok else 1)
