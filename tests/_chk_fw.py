# -*- coding: utf-8 -*-
import glob, io, json, os
files = glob.glob("_teststore/*.json")
files = [f for f in files if not os.path.basename(f).startswith("_")]
db = json.loads(io.open(files[0], encoding="utf-8").read())
sub = db["сдачи"][os.environ["PLANKEY"]]
fl = sub["versions"][-1].get("files", {})
assert "firmware" in fl and "firmware-2" in fl, list(fl)
assert fl["firmware"]["имя"].endswith(".bin"), fl["firmware"]
assert fl["firmware-2"]["имя"].endswith(".bin"), fl["firmware-2"]
print("FIRMWARE FILES OK")
