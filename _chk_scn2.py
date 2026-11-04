# -*- coding: utf-8 -*-
"""Фейковый комплект: материалы = 02/05/06, plans.js очищен; печатает tid."""
import glob, io, json, os, sys
files = [f for f in glob.glob("_teststore/*.json")
         if not os.path.basename(f).startswith("_")]
db = json.loads(io.open(files[0], encoding="utf-8").read())
les = [l for l in db["занятия"] if "SMOKE-KIT" in l.get("title", "")]
assert len(les) == 1, [l.get("title") for l in db["занятия"]]
mats = [m["имя"] for m in (les[0].get("материалы") or [])]
assert len(mats) == 3, mats
assert all(m.startswith(p) for m, p in zip(sorted(mats),
          ["02_", "05_", "06_"])) or sorted(m[0:3] for m in mats) == ["02_", "05_", "06_"], mats
lid = les[0]["id"]
d = os.path.join("_teststore", "раздатка", "c1", lid)
assert os.path.isdir(d), d
fl = os.listdir(d)
assert not any(f.startswith("03_") for f in fl), fl
plans = io.open(os.path.join(d, "plans.js"), encoding="utf-8").read()
assert "dev: []" in plans and "notes: []" in plans, plans[:200]
assert "эталон" not in plans and "SMOKE-ETALON" not in plans
tasks = sorted([t for t in db["задания"] if t.get("lesson") == lid],
               key=lambda t: t["title"])
assert len(tasks) == 1 and tasks[0].get("настройки", {}).get("план") == "SK-1"
print(tasks[0]["id"])
