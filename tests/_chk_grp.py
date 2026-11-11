# -*- coding: utf-8 -*-
"""Зачисление группы на курс + свёрнутые списки (свой сервер :8092)."""
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

PORT = os.environ.get("PORT", "8092")
STORE = os.environ.get("STORE", "_grp_store")
BASE = "http://localhost:" + PORT
ok = True


def need(c, m, ctx=""):
    global ok
    print(("OK   " if c else "FAIL ") + m + ("" if c else "  | "
                                             + str(ctx)[:200]))
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


def form(path, fields):
    return req(path, "POST",
               urllib.parse.urlencode(fields).encode("utf-8"),
               {"Content-Type": "application/x-www-form-urlencoded"})


if os.path.isdir(STORE):
    shutil.rmtree(STORE, ignore_errors=True)
proc = subprocess.Popen(
    [sys.executable, "-X", "utf8", "server.py", "--port", PORT,
     "--store", STORE, "--demo", "--no-pass"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
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

    form("/_staff_login", {"pass": "x"})

    # демо: 6 студентов П-21, все зачислены на c1
    reg = json.load(io.open(STORE + "\\реестр.json", encoding="utf-8"))
    c1 = next(c for c in reg["курсы"] if c.get("id") == "c1")
    n0 = len(c1.get("студенты") or [])
    need(n0 == 6, "демо: 6 зачисленных на c1", n0)

    # студент другой группы, не зачислен
    form("/staff/add_student", {"fio": "Новаков Новак Н.",
                                "group": "П-22", "brigade": ""})
    reg = json.load(io.open(STORE + "\\реестр.json", encoding="utf-8"))
    c1 = next(c for c in reg["курсы"] if c.get("id") == "c1")
    need(len(c1.get("студенты") or []) == n0,
         "новый студент пока не зачислен")

    # 1) зачисление группы П-22
    code, h, body = form("/staff/enroll_group",
                         {"course": "c1", "group": "П-22"})
    need(code == 302, "enroll_group -> редирект на курс", code)
    reg = json.load(io.open(STORE + "\\реестр.json", encoding="utf-8"))
    c1 = next(c for c in reg["курсы"] if c.get("id") == "c1")
    need(len(c1.get("студенты") or []) == n0 + 1,
         "группа П-22 зачислена (+1)", len(c1.get("студенты") or []))

    # 2) повтор — ничего не добавляет
    form("/staff/enroll_group", {"course": "c1", "group": "П-22"})
    reg = json.load(io.open(STORE + "\\реестр.json", encoding="utf-8"))
    c1 = next(c for c in reg["курсы"] if c.get("id") == "c1")
    need(len(c1.get("студенты") or []) == n0 + 1,
         "повторное зачисление группы не даёт дублей",
         len(c1.get("студенты") or []))

    # 3) аудит
    import glob
    acts = ""
    for f in glob.glob(STORE + "\\лог\\*.jsonl"):
        acts += io.open(f, encoding="utf-8").read()
    need('"зачислена группа"' in acts, "зачисление группы в аудите")

    # 4) свёрнутые списки на странице курса
    code, h, body = req("/staff/course/c1")
    need('<details class="stu-list" open>' not in body,
         "«Студенты» свёрнут (нет open)")
    need("нажмите, чтобы развернуть" in body, "текст «развернуть»")
    need("<details open>" not in body, "нигде нет details open")
    need("<details><summary>📋 Занятия (2)</summary>" in body,
         "«Занятия» в свёрнутом details")
    need("<details><summary>Список зачисления" in body,
         "«Список зачисления» свёрнут")
    need('action="/staff/enroll_group"' in body
         and "<option value=\"П-22\">П-22</option>" in body
         and "<option value=\"П-21\">П-21</option>" in body,
         "форма «Зачислить группу» с вариантами групп")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

print("GRP OK" if ok else "GRP FAIL")
sys.exit(0 if ok else 1)
