# -*- coding: utf-8 -*-
"""Проверка офлайн-модуля (модель 1.4.0: бланки выдаёт преподаватель):
предпросмотр бланка, «Выдача бланков» (архивы «ФИО.zip» с токенами),
студенческая страница загрузки. JS бланков — node --check."""
import glob
import http.cookiejar
import io
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://localhost:8099"
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def get(p):
    with op.open(BASE + p) as r:
        return r.read().decode("utf-8", "replace")


def post(p, fields):
    with op.open(BASE + p, urllib.parse.urlencode(fields).encode()) as r:
        return r.read().decode("utf-8", "replace")


def blob(p, fields=None):
    data = (fields.encode() if isinstance(fields, str)
            else urllib.parse.urlencode(fields).encode())
    with op.open(BASE + p, data) as r:
        return r.read()


op.open(BASE + "/_staff_login", b"pass=x").read()
op.open(BASE + "/_login", urllib.parse.urlencode(
    {"student": "s1", "next": "/"}).encode()).read()

ok = True


def need(cond, msg):
    global ok
    print(("OK   " if cond else "FAIL ") + msg)
    ok = ok and bool(cond)


# 1) панель: выдача бланков
pg = get("/staff/offline")
need('action="/staff/offline/issue"' in pg and "wcTog" in pg,
     "panel: issue form present")
need("offline/import" in pg, "panel: import form present")

# 2) предпросмотр анонимного бланка (staff)
blank = get("/offline/blank/t1")
need("<script><script>" not in blank, "staff blank: no double script")
m = re.search(r"<script>(.*?)</script>", blank, re.S)
need(bool(m) and "function save(" in (m.group(1) if m else ""),
     "staff blank: save() present")
with open("_bt.js", "w", encoding="utf-8") as f:
    f.write(m.group(1) if m else "")
r = subprocess.run(["node", "--check", "_bt.js"], capture_output=True)
os.remove("_bt.js")
need(r.returncode == 0, "staff blank: node --check")

# 3) выдача бланков: два студента, одно задание
zb = blob("/staff/offline/issue", "task=t1&student=s1&student=s2")
z = zipfile.ZipFile(io.BytesIO(zb))
names = z.namelist()
need(len(names) == 2 and all(n.endswith(".zip") for n in names),
     "issue: two per-student zips (%s)" % ", ".join(names[:2]))
inner_ok = True
for n in names:
    expected = n[:-4]
    z2 = zipfile.ZipFile(io.BytesIO(z.read(n)))
    inner = [x for x in z2.namelist() if x.endswith(".html")]
    if not inner:
        inner_ok = False
        continue
    h = z2.read(inner[0]).decode("utf-8")
    if ("<script><script>" in h or "function save(" not in h
            or not re.search(r'"token": "[0-9a-f]{24}"', h)
            or not re.search(r'"sig": "[0-9a-f]+"', h)
            or expected not in h):
        inner_ok = False
need(inner_ok, "issue: personal blanks valid (save+token+sig+fio)")
if names:
    z2 = zipfile.ZipFile(io.BytesIO(z.read(names[0])))
    inner = [x for x in z2.namelist() if x.endswith(".html")][0]
    with open("_bt.js", "w", encoding="utf-8") as f:
        f.write(re.search(r"<script>(.*?)</script>",
                          z2.read(inner).decode("utf-8"), re.S).group(1))
    r = subprocess.run(["node", "--check", "_bt.js"], capture_output=True)
    os.remove("_bt.js")
    need(r.returncode == 0, "issue blank: node --check")

# 4) студентская страница загрузки
need("/offline/upload" in get("/offline"), "student upload page intact")
print("BLANKI OK" if ok else "BLANKI FAIL")
sys.exit(0 if ok else 1)
