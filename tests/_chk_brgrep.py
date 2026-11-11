# -*- coding: utf-8 -*-
"""Регресс: бригадная сдача — все участники в отчётах (страница, CSV, zip)."""
import http.cookiejar
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
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
STORE = "_sc_br"
BASE = "http://localhost:8094"
if os.path.isdir(STORE):
    shutil.rmtree(STORE, ignore_errors=True)
proc = subprocess.Popen(
    [sys.executable, "-X", "utf8", "server.py", "--port", "8094",
     "--store", STORE, "--demo", "--no-pass", "--no-ci-watch"],
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
                                             + str(ctx)[:220]))
    ok = ok and bool(c)


try:
    stf_op.open(urllib.request.Request(
        BASE + "/_staff_login",
        data=urllib.parse.urlencode({"pass": "x"}).encode(),
        method="POST"), timeout=10)
except urllib.error.HTTPError:
    pass

# бригада «команда» из s1+s2
payload = json.dumps(
    {"rows": [{"old": "", "name": "команда", "off": False,
               "members": [{"sid": "s1"}, {"sid": "s2"}]}],
     "removed": []}, ensure_ascii=False)
fd = urllib.parse.urlencode(
    {"course": "c1", "data": payload}).encode()
try:
    r = stf_op.open(urllib.request.Request(
        BASE + "/staff/brigades_save", data=fd, method="POST"), timeout=10)
    res = json.loads(r.read().decode("utf-8"))
    need(res.get("ok"), "бригада создана", res)
except urllib.error.HTTPError as e:
    need(False, "бригада создана (HTTP)", e.code)

# сдача за бригаду от s1
try:
    stu_op.open(urllib.request.Request(
        BASE + "/_login",
        data=urllib.parse.urlencode({"student": "s1"}).encode(),
        method="POST"), timeout=10)
except urllib.error.HTTPError:
    pass
fields = [("task", "t1"), ("width", "24"), ("length", "18"),
          ("height", "4.2"), ("detector_type", "ИП 212 (дымовой)"),
          ("detectors_num", "6"), ("loops", "2"),
          ("justification", "тест бригады"), ("brigade", "команда")]
mp = b""
for name, val in fields:
    mp += ('--B\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
           % (name, val)).encode("utf-8")
mp += b"--B--\r\n"
try:
    stu_op.open(urllib.request.Request(
        BASE + "/api/submit", data=mp, method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=B"}),
        timeout=10)
    need(True, "сдача за бригаду")
except urllib.error.HTTPError as e:
    need(e.code == 302, "сдача за бригаду (302)", e.code)

# соло-сдача от s3
try:
    stu_op.open(urllib.request.Request(
        BASE + "/_login",
        data=urllib.parse.urlencode({"student": "s3"}).encode(),
        method="POST"), timeout=10)
except urllib.error.HTTPError:
    pass
fields3 = [(k, v) for k, v in fields if k != "brigade"]
mp = b""
for name, val in fields3:
    mp += ('--B\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
           % (name, val)).encode("utf-8")
mp += b"--B--\r\n"
try:
    stu_op.open(urllib.request.Request(
        BASE + "/api/submit", data=mp, method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=B"}),
        timeout=10)
    need(True, "соло-сдача")
except urllib.error.HTTPError as e:
    need(e.code == 302, "соло-сдача (302)", e.code)

time.sleep(1)
# реестр: участники
reg = json.load(io.open(STORE + "\\реестр.json", encoding="utf-8"))
sbr = (reg.get("сдачи") or {}).get("t1__s1") or {}
need(sbr.get("бригада") == "команда", "бригада в реестре",
     sbr.get("бригада"))
need(set(sbr.get("participants") or []) == {"s1", "s2"},
     "участники в реестре", sbr.get("participants"))

# 1) страница сдачи
b = stf_op.open(BASE + "/staff/sub/t1__s1", timeout=10).read() \
    .decode("utf-8", "replace")
need("Бригада «команда»" in b, "страница: заголовок бригады")
need("Иванов И.И." in b and "Петров П.П." in b,
     "страница: оба участника")
b3 = stf_op.open(BASE + "/staff/sub/t1__s3", timeout=10).read() \
    .decode("utf-8", "replace")
need("Сидоров С.С." in b3 and "Бригада «" not in b3,
     "страница: соло без бригады")

# 2) CSV журнала
csv_b = stf_op.open(BASE + "/staff/export/course/c1", timeout=10) \
    .read().decode("utf-8-sig", "replace")
need("команда" in csv_b and "Иванов И.И. / Петров П.П." in csv_b,
     "CSV: бригада + оба участника", csv_b[:300])

# 3) архив работ
zb = stf_op.open(BASE + "/staff/works/t1", timeout=10).read()
zf = zipfile.ZipFile(io.BytesIO(zb))
rep = ""
for n in zf.namelist():
    if n.endswith("отчёт.txt"):
        rep = zf.read(n).decode("utf-8-sig", "replace")
        break
need("Бригада: команда — участники: Иванов И.И., Петров П.П." in rep,
     "zip: оба участника в отчёте", rep[:250])

proc.terminate()
print("BR OK" if ok else "BR FAIL")
sys.exit(0 if ok else 1)
