# -*- coding: utf-8 -*-
import glob, io, json, os
files = [f for f in glob.glob("_teststore/*.json")
         if not os.path.basename(f).startswith("_")]
db = json.loads(io.open(files[0], encoding="utf-8").read())
les = [l for l in db["занятия"] if "SCN-TEST" in l.get("title", "")]
assert len(les) == 1, [l.get("title") for l in db["занятия"]]
lid = les[0]["id"]
tasks = [t for t in db["задания"] if t.get("lesson") == lid]
assert len(tasks) == 2, len(tasks)
form = {f["ключ"]: f["тип"] for f in tasks[0]["форма"]}
assert form.get("plan_data") == "hidden" and form.get("calc") == "textarea", form
assert form.get("loops") == "shlei", form
assert "plan_photo" not in form and "plan" not in form, form
loops_f = [f for f in tasks[0]["форма"] if f.get("ключ") == "loops"][0]
assert loops_f.get("строк") == 10, loops_f
calc_f = [f for f in tasks[0]["форма"] if f.get("ключ") == "calc"][0]
assert calc_f.get("обязательно") is True, calc_f
assert tasks[0].get("настройки", {}).get("план") == "SC-1", tasks[0].get("настройки")
d = tasks[0].get("описание", "")
assert "**calc**" in d and "<b>" not in d and "<br" not in d
assert "SC-1" in tasks[0]["title"]
assert "Ловушк" in d and "Критерии" in d and "балл." in d
print("SCENARIO IMPORT OK")
