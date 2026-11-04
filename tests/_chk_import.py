# -*- coding: utf-8 -*-
"""Проверка импорта группы: Novikov/Orlova добавлены, дубликатов нет."""
import glob
import io
import json
import os

files = [f for f in glob.glob("_teststore/*.json")
         if not os.path.basename(f).startswith("_")]
assert files, "реестр не найден"
db = json.loads(io.open(files[0], encoding="utf-8").read())
fios = [s.get("fio", "") for s in db["студенты"]]
assert fios.count("Novikov N.N.") == 1, fios
assert "Orlova O.A." in fios, fios
grp = {s["fio"]: s.get("group", "") for s in db["студенты"]}
assert grp["Novikov N.N."] == "P-22", grp
assert grp["Orlova O.A."] == "", grp  # без группы по умолчанию
assert fios.count("Иванов И.И.") == 1, "демо-студент задублировался"
assert "Ivanov I.I." not in fios, "латиница не должна была добавиться"
print("IMPORT OK")
