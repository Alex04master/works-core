# -*- coding: utf-8 -*-
import glob, io, json, os
files = [f for f in glob.glob("_teststore/*.json")
         if not os.path.basename(f).startswith("_")]
db = json.loads(io.open(files[0], encoding="utf-8").read())
s = [x for x in db["студенты"] if x.get("fio") == "Edit Test Student"]
assert s and not (s[0].get("бригада") or ""), s
print("BRIGADE DELETE OK")
