# -*- coding: utf-8 -*-
"""Проверка резервной копии: скачанный zip + автокопия при старте."""
import glob
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


p = "_bak.zip"
need(os.path.isfile(p) and os.path.getsize(p) > 0, "backup downloaded")
try:
    names = zipfile.ZipFile(p).namelist()
except Exception as ex:
    print("FAIL backup zip readable:", ex)
    sys.exit(1)
need(any(n == "реестр.json" for n in names), "zip: реестр.json")
need(any(n.startswith("раздатка/") for n in names), "zip: раздатка/")
need(any(n.startswith("сдачи/") for n in names), "zip: сдачи/")
need(not any(n.startswith("бэкап/") for n in names), "zip: без бэкап/")
auto = sorted(glob.glob(os.path.join("_teststore", "бэкап", "*.zip")))
need(len(auto) >= 1, "auto backup created at start")
need(len(auto) <= 3, "auto backup rotation keeps <= 3")
sys.exit(0 if ok else 1)
