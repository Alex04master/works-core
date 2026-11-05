# -*- coding: utf-8 -*-
"""Проверка офлайн-модуля в smoke: бланк (JS без двойного <script>,
node --check), страница «Бланки», пачечное скачивание (.zip)."""
import glob
import http.cookiejar
import io
import json
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


op.open(BASE + "/_login", urllib.parse.urlencode(
    {"student": "s1", "next": "/"}).encode()).read()

ok = True


def need(cond, msg):
    global ok
    print(("OK   " if cond else "FAIL ") + msg)
    ok = ok and bool(cond)


need("offline/blank" in get("/task/t1"), "blank link on task page")
blank = get("/offline/blank/t1")
need("<script><script>" not in blank and "</script></script>" not in blank,
     "blank: no double script tag")
m = re.search(r"<script>(.*?)</script>", blank, re.S)
need(bool(m) and "function save(" in (m.group(1) if m else ""),
     "blank: save() in single script")
p = os.path.join("_blank_tmp.js")
with open(p, "w", encoding="utf-8") as f:
    f.write(m.group(1) if m else "")
r = subprocess.run(["node", "--check", p], capture_output=True)
os.remove(p)
need(r.returncode == 0, "blank: node --check JS syntax")

pg = get("/offline/blanki")
need("/offline/blanki.zip" in pg and 'name="sel"' in pg,
     "blanki page: form + checkboxes")
need('href="/offline/blanki"' in get("/task/t1"), "nav button «Бланки»")

req = urllib.request.Request(
    BASE + "/offline/blanki.zip",
    data=urllib.parse.urlencode({"mode": "all"}).encode())
with op.open(req) as r:
    blob = r.read()
    cd = r.headers.get("Content-Disposition", "")
need(blob[:2] == b"PK" and "attachment" in cd, "blanki zip downloaded")
z = zipfile.ZipFile(io.BytesIO(blob))
names = z.namelist()
need(len(names) >= 2, "zip: >= 2 blanks")
allok = True
for n in names:
    h = z.read(n).decode("utf-8-sig")
    if ("<script><script>" in h or "function save(" not in h
            or not re.search(r'"token": "[0-9a-f]{24}"', h)):
        allok = False
need(allok, "zip: blanks valid (save + token, no double script)")

# после скачивания бланков: работа без токена не принимается — уже
# покрывает авторский _chk_offline.py; здесь проверяем страницу загрузки.
need("offline/upload" in get("/offline"), "upload page intact")

# уборка временных токенов не нужна — тестовый store пересоздаётся
print("BLANKI OK" if ok else "BLANKI FAIL")
sys.exit(0 if ok else 1)
