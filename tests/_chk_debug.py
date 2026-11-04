# -*- coding: utf-8 -*-
"""Проверка режима отладки: правка/добавление/удаление/raw/reload."""
import glob
import http.cookiejar
import io
import json
import os
import sys
import urllib.parse
import urllib.request

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://localhost:8099"
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def post(p, fields):
    with op.open(BASE + p, urllib.parse.urlencode(fields).encode()) as r:
        return r.read().decode("utf-8", "replace")


def get(p):
    with op.open(BASE + p) as r:
        return r.read().decode("utf-8", "replace")


op.open(BASE + "/_staff_login", b"pass=x").read()

ok = True


def need(cond, msg):
    global ok
    print(("OK   " if cond else "FAIL ") + msg)
    ok = ok and bool(cond)


def db():
    f = [x for x in glob.glob("_teststore/*.json")
         if not os.path.basename(x).startswith("_")]
    return json.load(io.open(f[0], encoding="utf-8"))


TKEY = urllib.parse.quote("задания")
SKEY = urllib.parse.quote("студенты")

need("debug/view" in get("/debug"), "debug page renders")
need("debug/raw" in get("/debug"), "debug raw link present")
t = get("/debug/view/" + TKEY)
need("id=t1" in t and "debug/edit" in t, "debug view lists tasks")

d = db()
t1 = next(x for x in d["задания"] if x["id"] == "t1")
n_tasks = len(d["задания"])
orig_desc = t1.get("описание", "")

post("/debug/save", {"key": "задания", "id": "t1", "act": "save",
                     "text": json.dumps(dict(t1, описание="DEBUG-EDIT"),
                                        ensure_ascii=False)})
d = db()
t1b = next(x for x in d["задания"] if x["id"] == "t1")
need(t1b.get("описание") == "DEBUG-EDIT", "debug edit saved")
need(t1b.get("форма") == t1.get("форма"), "other fields intact")

post("/debug/save", {"key": "студенты", "id": "s99", "act": "add",
                     "text": json.dumps({"id": "s99", "fio": "Тест Тестов",
                                         "group": "Т-99", "бригада": ""},
                                        ensure_ascii=False)})
d = db()
need(any(s.get("id") == "s99" for s in d["студенты"]), "debug add record")

get("/debug/del/%s?id=s99" % SKEY)
d = db()
need(not any(s.get("id") == "s99" for s in d["студенты"]),
     "debug delete record")

r = post("/debug/save", {"key": "задания", "id": "t1", "act": "save",
                         "text": "{oops"})
need("JSON:" in r, "bad json rejected")

cur = json.dumps(db(), ensure_ascii=False, indent=1)
post("/debug/raw", {"text": cur})
d = db()
need("версия" in d and len(d["задания"]) == n_tasks
     and any(x["id"] == "t1" for x in d["задания"]),
     "raw replace roundtrip intact")

post("/debug/save", {"key": "задания", "id": "t1", "act": "save",
                     "text": json.dumps(dict(t1b, описание=orig_desc),
                                        ensure_ascii=False)})
post("/debug/reload", {})
d = db()
need(any(x["id"] == "t1" for x in d["задания"]), "reload intact")

print("DEBUG OK" if ok else "DEBUG FAIL")
sys.exit(0 if ok else 1)
