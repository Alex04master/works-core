# -*- coding: utf-8 -*-
import io, re, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
lines = io.open("core/http.py", "r", encoding="utf-8", newline="").read().splitlines()
for j, ln in enumerate(lines):
    if "_subfile" in ln and "add(" in ln:
        for k in range(j, min(len(lines), j + 22)):
            print(f"{k+1:5d}| {lines[k]}")
        break
