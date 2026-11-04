# -*- coding: utf-8 -*-
import glob, io, json, os
files = [f for f in glob.glob("_teststore/*.json")
         if not os.path.basename(f).startswith("_")]
db = json.loads(io.open(files[0], encoding="utf-8").read())
sub = db["сдачи"][os.environ["PLANKEY"]]
rows = json.loads(sub["versions"][-1]["answers"]["loops"])
assert isinstance(rows, list) and rows and rows[0].get("n") == "1", rows
assert rows[0].get("cnt") == "3"
print("SHLEI DATA STORED OK")
