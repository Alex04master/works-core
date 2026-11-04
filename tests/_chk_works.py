# -*- coding: utf-8 -*-
"""Проверка «Все работы архивом»: состав zip по заданию t1."""
import os
import sys
import zipfile

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ok = True


def need(cond, msg):
    global ok
    print(("OK   " if cond else "FAIL ") + msg)
    ok = ok and bool(cond)


p = "_works.zip"
need(os.path.isfile(p) and os.path.getsize(p) > 0, "works zip downloaded")
try:
    z = zipfile.ZipFile(p)
except Exception as ex:
    print("FAIL zip readable:", ex)
    sys.exit(1)
names = z.namelist()
reps = [n for n in names if n.endswith("/отчёт.txt")]
need(len(reps) >= 2, "zip: submissions s1 + s3 (+ others)")
txt = "".join(z.read(n).decode("utf-8-sig") for n in reps)
need("ОТВЕТЫ" in txt and "ВЕРДИКТ" in txt, "zip: report sections")
need("late-test" in txt and "queue-test" in txt, "zip: answers present")
need("Студент:" in txt, "zip: student line")
sys.exit(0 if ok else 1)
