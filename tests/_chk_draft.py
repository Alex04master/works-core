# -*- coding: utf-8 -*-
"""Черновик формы: кнопка + автосохранение + сервер (свой сервер :8092)."""
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
STORE = os.environ.get("STORE", "_draft_store")
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

    # студент s1 входит
    req("/_login", "POST",
        urllib.parse.urlencode({"student": "s1", "next": "/"}).encode(),
        {"Content-Type": "application/x-www-form-urlencoded"})

    # 1) страница задания содержит кнопку и __TID__ заменён
    code, h, body = req("/task/t1")
    need(code == 200, "страница задания открылась", code)
    need("wc-draft-btn" in body and "Сохранить черновик" in body,
         "кнопка «Сохранить черновик» на странице")
    need("__TID__" not in body and "__SID__" not in body,
         "плейсхолдеры заменены")
    need("wc-br-wrap" not in body or "Без бригады" in body,
         "бригады не мешают")

    # 2) сохранить черновик на сервер
    draft = json.dumps({"width": "30", "length": "20",
                        "justification": "тест черновика"},
                       ensure_ascii=False)
    code, h, body = req("/api/draft", "POST",
                        urllib.parse.urlencode(
                            {"task": "t1", "draft": draft}).encode(),
                        {"Content-Type": "application/x-www-form-urlencoded"})
    need(code == 200 and json.loads(body).get("ok"),
         "POST /api/draft — сохранён", body[:120])

    # 3) загрузить черновик
    code, h, body = req("/api/draft?task=t1")
    j = json.loads(body)
    need(j.get("ok") and j.get("data", {}).get("width") == "30"
         and j.get("data", {}).get("justification") == "тест черновика",
         "GET /api/draft — данные совпадают", body[:200])

    # 4) файл черновика на диске
    p = os.path.join(STORE, "черновики", "t1__s1.json")
    need(os.path.isfile(p), "файл черновика на диске", p)
    d = json.load(io.open(p, encoding="utf-8"))
    need(d.get("data", {}).get("width") == "30" and "когда" in d,
         "данные + timestamp на диске")

    # 5) очистить черновик
    code, h, body = req("/api/draft?task=t1&clear=1")
    need(json.loads(body).get("ok"), "clear=1 — очищен")
    need(not os.path.isfile(p), "файл удалён после clear")

    # 6) после очистки GET возвращает data: null
    code, h, body = req("/api/draft?task=t1")
    j = json.loads(body)
    need(j.get("ok") and j.get("data") is None,
         "после clear данные пусты")

finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

print("DRAFT OK" if ok else "DRAFT FAIL")
sys.exit(0 if ok else 1)
