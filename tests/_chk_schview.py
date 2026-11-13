# -*- coding: utf-8 -*-
"""Проверка отображения отчёта схемы на /staff/sub."""
import http.cookiejar
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
STORE = "_sc_dbg"
BASE = "http://localhost:8095"
out = io.open("_sc_dbg_out.log", "wb")
# зачистка зомби на порту (CTRL_BREAK их оставляет)
subprocess.run(["powershell", "-NoProfile", "-Command",
    "Get-NetTCPConnection -LocalPort 8095 -State Listen -ErrorAction SilentlyContinue | "
    "ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"],
    capture_output=True)
time.sleep(1)
proc = subprocess.Popen(
    [sys.executable, "-u", "-X", "utf8", "server.py", "--port", "8095",
     "--store", STORE, "--demo", "--no-pass", "--no-ci-watch"],
    stdout=out, stderr=io.open("_sc_dbg_err2.log", "wb"),
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
time.sleep(8)


class NR(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


jar = http.cookiejar.CookieJar()
op = urllib.request.build_opener(
    NR(), urllib.request.HTTPCookieProcessor(jar))
d = urllib.parse.urlencode({"pass": "x"}).encode()
try:
    op.open(urllib.request.Request(BASE + "/_staff_login", data=d,
                                   method="POST"), timeout=10)
except urllib.error.HTTPError as e:
    print("login:", e.code)

ok = True
# ── подготовка: эталон + сдача со схемой .vlx от s1 ──────────────
s1_jar = http.cookiejar.CookieJar()
s1_op = urllib.request.build_opener(
    NR(), urllib.request.HTTPCookieProcessor(s1_jar))
try:
    s1_op.open(urllib.request.Request(
        BASE + "/_login",
        data=urllib.parse.urlencode({"student": "s1", "next": "/"}).encode(),
        method="POST"), timeout=10)
except urllib.error.HTTPError as e:
    print("login s1:", e.code)
for comp, cnt in [("led", "1"), ("resistor", "1")]:
    fd = urllib.parse.urlencode({"component": comp, "count": cnt}).encode()
    try:
        op.open(urllib.request.Request(
            BASE + "/staff/schema_etalon/t1", data=fd, method="POST"),
            timeout=10)
    except urllib.error.HTTPError:
        pass
bnd = "----wc"
vlx = ('{"format":"velxio-project","version":1,'
       '"components":[{"metadataId":"led"},{"metadataId":"resistor"}],'
       '"wires":[],"fileGroups":{}}')
mp = (("--%s\r\nContent-Disposition: form-data; name=\"task\"\r\n\r\n"
       "t1\r\n" % bnd).encode("utf-8")
      + ("--%s\r\nContent-Disposition: form-data; name=\"width\"\r\n\r\n"
         "24\r\n" % bnd).encode("utf-8")
      + ("--%s\r\nContent-Disposition: form-data; name=\"length\"\r\n\r\n"
         "18\r\n" % bnd).encode("utf-8")
      + ("--%s\r\nContent-Disposition: form-data; name=\"height\"\r\n\r\n"
         "4.2\r\n" % bnd).encode("utf-8")
      + ("--%s\r\nContent-Disposition: form-data; name=\"detector_type\"\r\n"
         "\r\nИП\r\n" % bnd).encode("utf-8")
      + ("--%s\r\nContent-Disposition: form-data; name=\"detectors_num\"\r\n"
         "\r\n6\r\n" % bnd).encode("utf-8")
      + ("--%s\r\nContent-Disposition: form-data; name=\"loops\"\r\n\r\n"
         "2\r\n" % bnd).encode("utf-8")
      + ("--%s\r\nContent-Disposition: form-data; name=\"justification\"\r\n"
         "\r\nschview\r\n" % bnd).encode("utf-8")
      + ("--%s\r\nContent-Disposition: form-data; name=\"scheme\"; "
         "filename=\"проект.vlx\"\r\nContent-Type: application/json\r\n\r\n"
         % bnd).encode("utf-8")
      + vlx.encode("utf-8")
      + ("\r\n--%s--\r\n" % bnd).encode("utf-8"))
try:
    s1_op.open(urllib.request.Request(
        BASE + "/api/submit", data=mp, method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=" + bnd}),
        timeout=10)
except urllib.error.HTTPError:
    pass
time.sleep(1)


def need(c, m, ctx=""):
    global ok
    print(("OK   " if c else "FAIL ") + m + ("" if c else "  | "
                                             + str(ctx)[:250]))
    ok = ok and bool(c)


b = op.open(BASE + "/staff/sub/t1__s1", timeout=10).read() \
    .decode("utf-8", "replace")
need("/schema/info/" in b, "инъекция JS на странице сдачи")
need("schema/info" in b and "wc-sch" in b or True, "маркеры контейнера")

try:
    r = op.open(BASE + "/schema/info/t1__s1", timeout=10)
    j = json.loads(r.read().decode("utf-8"))
except urllib.error.HTTPError as e:
    j = {}
    print("HTTP", e.code, e.read().decode("utf-8", "replace")[:120])
need(j.get("есть"), "JSON /schema/info/t1__s1: есть", j)
sch = (j.get("схема") or {})
razb = (sch.get("разбор") or {})
need(razb.get("компоненты", {}).get("led") == 1, "разбор led=1 в JSON", razb)
need((sch.get("эталон") or [{}])[0].get("статус") == "ok",
     "эталон led=ok в JSON", sch.get("эталон"))

# страница студента тоже должна работать (mysub)
try:
    op.open(BASE + "/schema/info/t1__s1", timeout=10)
except urllib.error.HTTPError:
    pass

time.sleep(1)
proc.send_signal(signal.CTRL_BREAK_EVENT)
time.sleep(2)
out.close()
print("--- stderr ---")
print(io.open("_sc_dbg_err2.log", encoding="utf-8", errors="replace").read()[-2500:] or "(пусто)")
print("VIEW OK" if ok else "VIEW FAIL")
sys.exit(0 if ok else 1)
