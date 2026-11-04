# -*- coding: utf-8 -*-
import io
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
t = io.open("modules/staff/модуль.py", encoding="utf-8", newline="").read()
for tag, a, b in (("students", "student_rows = \"\"", "student_table = \""),
                  ("enroll", "enrolled = set(course.get", "enroll_card = (")):
    i = t.find(a)
    j = t.find(b, i)
    print("=" * 100)
    print(tag, "block:")
    for ln in t[i:j].splitlines():
        print(repr(ln))
