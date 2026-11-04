# -*- coding: utf-8 -*-
"""Бригадная сдача: один отчёт на всех участников бригады."""
import glob, io, json, os

files = [f for f in glob.glob("_teststore/*.json")
         if not os.path.basename(f).startswith("_")]
db = json.loads(io.open(files[0], encoding="utf-8").read())
ids = {s["fio"]: s["id"] for s in db["студенты"]}
a, b = ids["Смирнов А.А."], ids["Кузнецов В.В."]
sub = db["сдачи"]["t1__s9"]
assert sub.get("бригада") == "BR-1", sub
assert sub.get("participants") == sorted([a, b]), sub.get("participants")
assert sub.get("student") == "s9", sub
print("PARTICIPANTS OK")
