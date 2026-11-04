# -*- coding: utf-8 -*-
import glob, io, json, os
files = [f for f in glob.glob("_teststore/*.json")
         if not os.path.basename(f).startswith("_")]
db = json.loads(io.open(files[0], encoding="utf-8").read())
sub = db["сдачи"][os.environ.get("PLANKEY", "")]
ver = sub["versions"][-1]
dev = json.loads(ver["answers"]["plan_data"])
assert isinstance(dev, list) and len(dev) == 2, dev
assert dev[0]["t"] == "smoke" and dev[1]["t"] == "ipr"
print("PLAN DATA STORED OK")
