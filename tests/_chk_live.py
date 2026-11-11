# -*- coding: utf-8 -*-
"""Регресс: живые обновления — /api/rev растёт при сдаче и вердикте,
черновик не меняет ревизию, JS-инъекция на страницах."""
import http.cookiejar
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
STORE = "_sc_live"
BASE = "http://localhost:8098"
if os.path.isdir(STORE):
    shutil.rmtree(STORE, ignore_errors=True)
proc = subprocess.Popen(
    [sys.executable, "-X", "utf8", "server.py", "--port", "8098",
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
                                             + str(ctx)[:200]))
    ok = ok and bool(c)


def rev():
    j = json.loads(urllib.request.urlopen(BASE + "/api/rev",
                                          timeout=10).read().decode())
    return j.get("rev")


need(isinstance(rev(), int), "GET /api/rev без входа -> число", rev())

# логины
try:
    stf_op.open(urllib.request.Request(
        BASE + "/_staff_login",
        data=urllib.parse.urlencode({"pass": "x"}).encode(),
        method="POST"), timeout=10)
except urllib.error.HTTPError:
    pass
try:
    stu_op.open(urllib.request.Request(
        BASE + "/_login",
        data=urllib.parse.urlencode({"student": "s1"}).encode(),
        method="POST"), timeout=10)
except urllib.error.HTTPError:
    pass

# инъекция JS на страницах
b = stf_op.open(BASE + "/staff", timeout=10).read().decode("utf-8", "replace")
need("/api/rev" in b, "JS живых обновлений на странице преподавателя")
b = stu_op.open(BASE + "/task/t1", timeout=10).read() \
    .decode("utf-8", "replace")
need("/api/rev" in b, "JS живых обновлений на странице задания")

# сдача -> rev растёт
r0 = rev()
fields = [("task", "t1"), ("width", "24"), ("length", "18"),
          ("height", "4.2"), ("detector_type", "ИП 212 (дымовой)"),
          ("detectors_num", "6"), ("loops", "2"),
          ("justification", "тест живых обновлений")]
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
except urllib.error.HTTPError as e:
    if e.code != 302:
        need(False, "сдача", e.code)
time.sleep(0.5)
r1 = rev()
need(r1 > r0, "сдача увеличивает ревизию", "%s -> %s" % (r0, r1))

# вердикт -> rev растёт
try:
    stf_op.open(urllib.request.Request(
        BASE + "/staff/verdict",
        data=urllib.parse.urlencode(
            {"key": "t1__s1", "verdict": "Принято", "score": "5",
             "comment": "ок"}).encode(),
        method="POST"), timeout=10)
except urllib.error.HTTPError as e:
    if e.code != 302:
        need(False, "вердикт", e.code)
time.sleep(0.5)
r2 = rev()
need(r2 > r1, "вердикт увеличивает ревизию", "%s -> %s" % (r1, r2))

# черновик НЕ меняет ревизию
try:
    stu_op.open(urllib.request.Request(
        BASE + "/api/draft",
        data=urllib.parse.urlencode(
            {"task": "t1", "draft": json.dumps({"width": "1"})}).encode(),
        method="POST"), timeout=10)
except urllib.error.HTTPError as e:
    if e.code != 200:
        need(False, "черновик POST", e.code)
time.sleep(0.5)
r3 = rev()
need(r3 == r2, "черновик не увеличивает ревизию", "%s vs %s" % (r2, r3))

proc.terminate()
print("LIVE OK" if ok else "LIVE FAIL")
sys.exit(0 if ok else 1)
