# -*- coding: utf-8 -*-
"""Проверка импорта пакета: новый курс, задания, сдачи, файлы, раздатка."""
import glob
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
files = [f for f in glob.glob("_teststore/*.json")
         if not os.path.basename(f).startswith("_")]
db = json.loads(io.open(files[0], encoding="utf-8").read())
c1 = db["курсы"][0]
cands = [c for c in db["курсы"]
         if c["id"] != c1["id"] and c.get("title") == c1.get("title")]
assert cands, "импортированный курс не найден: %s" % [
    (c["id"], c.get("title")) for c in db["курсы"]]
c2 = cands[-1]
lids2 = [l for l in db["занятия"] if l.get("course") == c2["id"]]
lset = {l["id"] for l in lids2}
tks2 = [t for t in db["задания"] if t.get("lesson") in lset]
assert lids2 and tks2, "нет занятий/заданий"
assert all(t.get("lesson") in lset for t in tks2), "битые ссылки заданий"
tset = {t["id"] for t in tks2}
subs2 = [s for s in db["сдачи"].values() if s.get("task") in tset]
assert subs2, "сдачи не перенесены"
for s in subs2:
    assert s["key"] == "%s__%s" % (s["task"], s["student"]), s["key"]
    for ver in s.get("versions", []):
        for info in (ver.get("files") or {}).values():
            rel = str(info.get("файл", ""))
            assert rel.startswith(s["key"] + "/"), rel
            p = os.path.join("_teststore", "сдачи", rel)
            assert os.path.isfile(p), p
handouts = []
for lid in lset:
    d = os.path.join("_teststore", "раздатка", c2["id"], lid)
    if os.path.isdir(d) and os.listdir(d):
        handouts.append(d)
assert handouts, "раздатка импортированного курса пуста"
assert set(c2.get("студенты") or []) == set(c1.get("студенты") or []), \
    "зачисление не перенесено"
print("IMPORT OK: курс %s, занятий %d, заданий %d, сдач %d"
      % (c2["id"], len(lids2), len(tks2), len(subs2)))
