# -*- coding: utf-8 -*-
"""Проверка шаблонов: задание «tpl-made», созданное из шаблона t1."""
import glob
import io
import json
import os
import sys

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ok = True


def need(cond, msg):
    global ok
    print(("OK   " if cond else "FAIL ") + msg)
    ok = ok and bool(cond)


files = [f for f in glob.glob("_teststore/*.json")
         if not os.path.basename(f).startswith("_")]
db = json.loads(io.open(files[0], encoding="utf-8").read())
src = next(t for t in db["задания"] if t["id"] == "t1")
made = [t for t in db["задания"] if t.get("title") == "tpl-made"]
need(len(made) == 1, "template task created")
if made:
    t = made[0]
    need(t.get("lesson") == "l1", "created in chosen lesson")
    src_keys = {f.get("ключ") for f in (src.get("форма") or [])}
    new_keys = {f.get("ключ") for f in (t.get("форма") or [])}
    need(src_keys == new_keys and len(new_keys) >= 6,
         "form copied from template")
    need((t.get("настройки") or {}).get("критерии")
         == (src.get("настройки") or {}).get("критерии"),
         "criteria carried")
    need((t.get("настройки") or {}).get("срок", "")
         == (src.get("настройки") or {}).get("срок", ""),
         "deadline carried")
sys.exit(0 if ok else 1)
