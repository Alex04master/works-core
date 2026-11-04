# -*- coding: utf-8 -*-
"""Проверка: в реестре сохранён флаг просрочки (ASCII-safe через \\u-escape)."""
import glob
import io
import os

LATE = "\u043f\u0440\u043e\u0441\u0440\u043e\u0447\u0435\u043d\u043e"  # просрочено
files = [f for f in glob.glob("_teststore/*.json")
         if not os.path.basename(f).startswith("_")]
assert files, "реестр не найден"
src = io.open(files[0], encoding="utf-8").read()
assert LATE in src, "флаг просрочки не сохранён"
print("LATE FLAG OK")
