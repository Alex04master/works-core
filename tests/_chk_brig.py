# -*- coding: utf-8 -*-
"""Импорт бригад: 3-й столбец попадает в поле бригада."""
import glob, io, json, os

files = [f for f in glob.glob("_teststore/*.json")
         if not os.path.basename(f).startswith("_")]
assert files, "реестр не найден"
db = json.loads(io.open(files[0], encoding="utf-8").read())
ids = {s["fio"]: s["id"] for s in db["студенты"]}
assert "Смирнов А.А." in ids and "Кузнецов В.В." in ids, ids
a, b = ids["Смирнов А.А."], ids["Кузнецов В.В."]
st = {s["id"]: s for s in db["студенты"]}
assert st[a].get("бригада") == "BR-1", st[a]
assert st[b].get("бригада") == "BR-1", st[b]
assert (a, b) == ("s9", "s10"), (a, b)  # ожидаемые id для смоук-теста
print("BRIG OK")
