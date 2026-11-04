# -*- coding: utf-8 -*-
import glob, io, json, os
files = [f for f in glob.glob("_teststore/*.json") if not os.path.basename(f).startswith("_")]
db = json.loads(io.open(files[0], encoding="utf-8").read())
st = {s["id"]: s for s in db["студенты"]}
assert st["s2"].get("бригада") == "TEST-TEAM", st["s2"]
print("BRIGADE JOIN OK")
