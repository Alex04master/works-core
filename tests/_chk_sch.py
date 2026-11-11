# -*- coding: utf-8 -*-
"""Финальный тест schemacheck: 302 = успех для POST."""
import http.cookiejar
import io
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import shutil
import os

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
STORE = "_sc_v3"
BASE = "http://localhost:8092"
if os.path.isdir(STORE):
    shutil.rmtree(STORE, ignore_errors=True)
proc = subprocess.Popen(
    [sys.executable, "-X", "utf8", "server.py", "--port", "8092",
     "--store", STORE, "--demo", "--no-pass"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(8)


class NR(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


stu_jar = http.cookiejar.CookieJar()
stu_op = urllib.request.build_opener(
    NR(), urllib.request.HTTPCookieProcessor(stu_jar))
stf_jar = http.cookiejar.CookieJar()
stf_op = urllib.request.build_opener(
    NR(), urllib.request.HTTPCookieProcessor(stf_jar))
ok = True


def need(c, m, ctx=""):
    global ok
    print(("OK   " if c else "FAIL ") + m + ("" if c else "  | "
                                             + str(ctx)[:200]))
    ok = ok and bool(c)


# студенческий вход
d = urllib.parse.urlencode({"student": "s1", "next": "/"}).encode()
try:
    stu_op.open(urllib.request.Request(BASE + "/_login", data=d,
                                       method="POST"), timeout=10)
except urllib.error.HTTPError:
    pass

# staff вход
d = urllib.parse.urlencode({"pass": "x"}).encode()
try:
    stf_op.open(urllib.request.Request(BASE + "/_staff_login", data=d,
                                       method="POST"), timeout=10)
except urllib.error.HTTPError:
    pass

# 1) эталон: POST возвращает 302 = успешный redirect
for comp, cnt in [("led", "1"), ("resistor", "1")]:
    fd = urllib.parse.urlencode({"component": comp, "count": cnt}).encode()
    try:
        r = stf_op.open(urllib.request.Request(
            BASE + "/staff/schema_etalon/t1", data=fd, method="POST"),
            timeout=10)
        need(True, "эталон: %s (200)" % comp)
    except urllib.error.HTTPError as e:
        need(e.code == 302, "эталон: %s (302)" % comp, e.code)

# 2) форма эталона
try:
    b = stf_op.open(BASE + "/staff/schema_etalon/t1", timeout=10) \
        .read().decode("utf-8", "replace")
    need("led" in b and "resistor" in b,
         "форма эталона показывает компоненты", b[:200])
except urllib.error.HTTPError as e:
    need(False, "форма эталона", e.code)
    b = e.read().decode("utf-8", "replace")
    print("body:", b[:200])

# 3) сдача с .vlx (302 = успех)
bnd = "----wc"
vlx = ('{"format":"velxio-project","version":1,'
       '"components":[{"metadataId":"led"},{"metadataId":"resistor"}],'
       '"wires":[],"fileGroups":{}}')
parts = [("task", "t1"), ("width", "24"), ("length", "18"),
         ("height", "4.2"), ("detector_type", "ИП"),
         ("detectors_num", "6"), ("loops", "2"),
         ("justification", "тест")]
mp = b""
for name, val in parts:
    mp += ('--%s\r\nContent-Disposition: form-data; name="%s"'
           '\r\n\r\n%s\r\n' % (bnd, name, val)).encode("utf-8")
mp += ('--%s\r\nContent-Disposition: form-data; name="scheme"; '
       'filename="проект.vlx"\r\nContent-Type: application/json\r\n\r\n'
       % bnd).encode("utf-8") + vlx.encode("utf-8") + \
    ("\r\n--%s--\r\n" % bnd).encode("utf-8")
try:
    r = stu_op.open(urllib.request.Request(
        BASE + "/api/submit", data=mp, method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=" + bnd}),
        timeout=10)
    need(True, "сдача с .vlx принята")
except urllib.error.HTTPError as e:
    need(e.code == 302, "сдача с .vlx принята (302)", e.code)

# 4) реестр
time.sleep(1)
reg = json.load(io.open(STORE + "\\реестр.json", encoding="utf-8"))
subs = reg.get("сдачи") or {}
s = subs.get("t1__s1") or {}
vers = s.get("versions") or []
need(len(vers) >= 1, "версия сдачи создана", len(vers))
if vers:
    ctl = vers[-1].get("контроль") or {}
    sch = ctl.get("схема") or {}
    razb = sch.get("разбор") or {}
    comps = razb.get("компоненты") or {}
    need(comps.get("led") == 1, "авторазбор: led=1", comps)
    need(comps.get("resistor") == 1, "авторазбор: resistor=1", comps)
    checks = sch.get("эталон") or []
    led_c = next((c for c in checks if c["компонент"] == "led"), None)
    need(led_c and led_c["статус"] == "ok", "эталон: led ok", led_c)

proc.terminate()
print("SC OK" if ok else "SC FAIL")
sys.exit(0 if ok else 1)
