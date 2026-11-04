# -*- coding: utf-8 -*-
import io, re, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def show(path, pattern, before=1, after=18, tag=None):
    lines = io.open(path, "r", encoding="utf-8", newline="").read().splitlines()
    for i, ln in enumerate(lines):
        if re.search(pattern, ln):
            print(f"--- {tag or ''} @ {i+1} ---")
            for j in range(max(0, i - before), min(len(lines), i + after)):
                print(f"{j+1:5d}| {lines[j]}")

show("core/http.py", r"self\.core\s*=|self\._core\s*=", after=1, tag="server core attr")
show("core/core.py", r"from datetime", after=0, tag="core datetime import")
show("modules/staff/модуль.py", r'@ctx\.add_route\("POST", "/staff/enroll"', after=16, tag="enroll single")
show("modules/staff/модуль.py", r'handler\._redirect\("/staff/course/%s\?imp', before=2, after=2, tag="import tail")
show("modules/staff/модуль.py", r"def edit_task", after=34, tag="edit_task full")
