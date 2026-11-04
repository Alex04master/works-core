# -*- coding: utf-8 -*-
"""Юнит-тест ядра: файлы, grade, дедлайны, markdown, delete_task, битый реестр."""
import io
import json
import os
import shutil
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from core.store import Store
from core.core import Core, _md, _parse_deadline, task_deadline

root = os.path.join(BASE, "_teststore2")
if os.path.exists(root):
    shutil.rmtree(root)

st = Store(root)
c = Core(st)
cid = c.new_course("K")
lid = c.new_lesson(cid, "L")
tid = c.new_task(lid, "T", form=[
    {"тип": "number", "ключ": "n", "вопрос": "N", "обязательно": True, "мин": 1},
    {"тип": "file", "ключ": "f", "вопрос": "Файл", "обязательно": True},
])
sid = c.add_student("Ivanov I.")


class _Up:
    def __init__(self, name, data):
        self.name = name
        self.data = data


calls = []


def fake_grade(task=None, answers=None, **kw):
    calls.append(1)
    return {"verdict": "Принято (автопроверка)", "score": 100.0,
            "status": "принято", "comment": "ok"}


c.events.on("grade", fake_grade, "test")

# 1) обязателен ли файл
sub0, err0 = c.collect(tid, sid, answers={"n": "5"}, files={})
assert err0 and "обязательное" in err0, err0

# 2) сдача с файлом + автопроверка
sub, err = c.collect(tid, sid, answers={"n": "5"}, files={"f": _Up("тест.txt", b"hello")})
assert err is None, err
ver = sub["versions"][-1]
assert ver["verdict"] == "Принято (автопроверка)", ver
assert sub["status"] == "принято", sub["status"]
assert ver["files"]["f"]["размер"] == 5
saved = os.path.join(st.subs, ver["files"]["f"]["файл"].replace("/", os.sep))
assert os.path.isfile(saved), saved
with open(saved, "rb") as f:
    assert f.read() == b"hello"
assert calls, "grade не вызван"

# 3) в реестре нет бинарного мусора
with open(st.reg, encoding="utf-8") as f:
    db_text = f.read()
assert "b'" not in db_text, "мусор в реестре"

# 4) markdown: рендер + экранирование
h = _md("## Задача\n\n- пункт **жирный**\n- <script>alert(1)</script>\n\nКод: `x=1`\n2. второй")
assert "<h2>Задача</h2>" in h, h
assert "<ul>" in h and "<li>пункт <strong>жирный</strong></li>" in h, h
assert "<script>" not in h and "&lt;script&gt;" in h, h
assert "<code>x=1</code>" in h, h
assert "<ol>" in h and "<li>второй</li>" in h, h
assert _md("") == ""
assert _md("<b>x</b>") == "<p>&lt;b&gt;x&lt;/b&gt;</p>"  # HTML экранируется

# 5) дедлайны
assert _parse_deadline("2026-12-31 18:00") is not None
assert _parse_deadline("31.12.2026") is not None
assert _parse_deadline("мусор") is None
assert _parse_deadline("") is None
assert task_deadline({"настройки": {"срок": "2026-12-31 18:00"}}) is not None
assert task_deadline({"настройки": {}}) is None

# 6) сдача после срока -> флаг просрочки
tid2 = c.new_task(lid, "T2", form=[
    {"тип": "number", "ключ": "n", "вопрос": "N", "обязательно": True}],
    settings={"срок": "2020-01-01 09:00"})
sub2, err2 = c.collect(tid2, sid, answers={"n": "3"})
assert err2 is None, err2
assert sub2["versions"][-1].get("просрочено") is True, sub2["versions"][-1]
assert sub2["status"] == "принято", sub2["status"]  # тестовый grade-хук применился поверх

# 7) валидация email/tel
tid3 = c.new_task(lid, "T3", form=[
    {"тип": "email", "ключ": "em", "вопрос": "E", "обязательно": True},
    {"тип": "tel", "ключ": "tel", "вопрос": "T"}])
_, err3 = c.collect(tid3, sid, answers={"em": "сломанный", "tel": ""})
assert err3 and "email" in err3, err3
_, err3b = c.collect(tid3, sid, answers={"em": "a@b.ru", "tel": "+7 (900) 000-00-00"})
assert err3b is None, err3b
_, err3c = c.collect(tid3, sid, answers={"em": "a@b.ru", "tel": "abc!!!"})
assert err3c and "телефон" in err3c, err3c

# 8) delete_task убирает и сдачи
c.delete_task(tid)
c.delete_task(tid2)
c.delete_task(tid3)
assert st.db["сдачи"] == {}, st.db["сдачи"]

# 9) зачисление (roster): пустой список = всем, зачисленный = только он
cid2 = c.new_course("K2")
sid2 = c.add_student("Petrov P.")
assert c.can_access(cid2, sid2) is True
c.enroll(cid2, sid2)
assert c.can_access(cid2, sid2) is True
sid3 = c.add_student("Sidorov S.")
assert c.can_access(cid2, sid3) is False
tid4 = c.new_task(c.new_lesson(cid2, "L4"), "T4")
_, err4 = c.collect(tid4, sid3, answers={})
assert err4 and "нет доступа" in err4, err4
_, err4b = c.collect(tid4, sid2, answers={})
assert err4b is None, err4b
assert cid2 in [x["id"] for x in c.courses(sid2)]
c.unenroll(cid2, sid2)
assert c.can_access(cid2, sid2) is True

# 10) битый реестр -> бэкап
with open(st.reg, "w", encoding="utf-8") as f:
    f.write("{битый json")
Store(root)
baks = [x for x in os.listdir(root) if x.startswith("реестр.json.битый-")]
assert baks, "нет бэкапа битого реестра"

print("UNIT OK")
shutil.rmtree(root)
