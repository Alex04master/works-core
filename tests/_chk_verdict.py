# -*- coding: utf-8 -*-
"""Проверка: вердикт с чек-листом критериев сохранён в сдаче."""
import glob
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
key = os.environ.get("VKEY", "")
if not key:
    print("FAIL no VKEY")
    sys.exit(1)
files = [f for f in glob.glob("_teststore/*.json")
         if not os.path.basename(f).startswith("_")]
db = json.loads(io.open(files[0], encoding="utf-8").read())
sub = db["сдачи"].get(key)
assert sub, "no submission %s" % key
ver = sub["versions"][-1]
assert ver.get("verdict") == "Принято", ver.get("verdict")
assert ver.get("чек") == [0, 1], ver.get("чек")
assert ver.get("время_вердикта"), "no verdict time"
assert sub.get("status") == "принято", sub.get("status")
print("VERDICT CHECK OK")
