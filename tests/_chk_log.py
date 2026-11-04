# -*- coding: utf-8 -*-
import glob, io, json

files = glob.glob("_teststore/лог/*.jsonl")
assert files, "нет файлов журнала"
acts = []
for f in files:
    for ln in io.open(f, encoding="utf-8"):
        if ln.strip():
            acts.append(json.loads(ln).get("действие", ""))
need = ["вход студента", "вход в панель", "сдача задания", "вердикт",
        "выдача задания", "снята выдача задания", "импорт группы",
        "бригада переименована", "массовая выдача заданий",
        "импортирован сценарий", "зачислены все студенты",
        "изменена бригада студента", "добавлен студент",
        "доступ курса группе", "бригада распущена"]
missing = [a for a in need if a not in acts]
assert not missing, missing
print("AUDIT LOG OK (%d строк)" % len(acts))
