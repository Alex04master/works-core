# -*- coding: utf-8 -*-
"""Проверка пакета курса: манифест, состав, раздатка и файлы сдач."""
import io
import json
import os
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
zf = zipfile.ZipFile("_pkg.zip")
names = zf.namelist()
meta = json.loads(zf.read("пакет.json").decode("utf-8"))
assert meta.get("формат") == "works-core-курс", meta
lessons = json.loads(zf.read("занятия.json").decode("utf-8"))
tasks = json.loads(zf.read("задания.json").decode("utf-8"))
students = json.loads(zf.read("студенты.json").decode("utf-8"))
subs = json.loads(zf.read("сдачи.json").decode("utf-8"))
assert len(lessons) >= 1 and len(tasks) >= 1 and len(students) >= 1
assert len(subs) >= 1, "нет сдач в пакете"
assert any(n.startswith("раздатка/") for n in names), names[:5]
assert any(n.startswith("сдачи/") for n in names), "нет файлов сдач"
course = json.loads(zf.read("курс.json").decode("utf-8"))
assert course.get("id") == "c1"
print("COURSE PACKAGE OK: занятий %d, заданий %d, сдач %d"
      % (len(lessons), len(tasks), len(subs)))
