# -*- coding: utf-8 -*-
"""Выключатель бригад для курса: преподаватель включает/отключает.

Запуск: python -X utf8 tests/_chk_brig10.py  (сервер с _teststore на 8099).
Проверки: при отключённых бригадах курса — регистрация бригад скрыта,
сдача только личная (за бригаду отклоняется), вступление запрещено,
панель показывает выключатель и прячет карточки бригад; включение
возвращает всё обратно.
"""
import glob
import io
import json
import os
import subprocess
import sys
import urllib.parse

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PORT = os.environ.get("PORT", "8099")
BASE = "http://localhost:" + PORT
ok = True


def need(cond, msg, ctx=""):
    global ok
    print(("OK   " if cond else "FAIL ") + msg + ("" if cond else
                                                  "  | " + str(ctx)[:200]))
    ok = ok and bool(cond)


def curl(*args):
    r = subprocess.run(["curl.exe", "-s"] + list(args), capture_output=True)
    return r.stdout.decode("utf-8", "replace")


def registry():
    files = [f for f in glob.glob("_teststore/*.json")
             if not os.path.basename(f).startswith("_")]
    return json.loads(io.open(files[0], encoding="utf-8").read())


FORM = {"width": "24", "length": "18", "height": "4.2",
        "detector_type": "ИП 212 (дымовой)", "detectors_num": "6",
        "loops": "2", "justification": "brig10 test"}

curl("-c", "_b10_st.txt", "-d", "pass=x", BASE + "/_staff_login")
curl("-c", "_b10_ck.txt", "-d", "student=s1", "-d", "next=/",
     BASE + "/_login")

# подготовка: s1 в бригаде BR10, бригады курса включены
curl("-b", "_b10_st.txt", "-d", "student=s1", "-d", "course=c1",
     "-d", "brigade=BR10", BASE + "/staff/student_brigade")
db = registry()
need((next(s for s in db["студенты"] if s["id"] == "s1").get("бригада")
      or "") == "BR10", "подготовка: s1 в бригаде BR10")
need(db["курсы"][0].get("без_бригад") is None,
     "подготовка: бригады курса включены по умолчанию")

sp0 = curl("-b", "_b10_st.txt", BASE + "/staff/course/c1")
need("Бригады на курсе:</b>" in sp0 and "✅ включены" in sp0,
     "панель: выключатель виден, состояние «включены»")
need("⏸ Отключить бригады на курсе" in sp0,
     "панель: кнопка «Отключить бригады на курсе»")
cp0 = curl("-b", "_b10_ck.txt", BASE + "/course/c1")
need("Регистрация бригады" in cp0, "курс студента: регистрация бригад видна")

# ── отключаем бригады для курса ───────────────────────────────────────
curl("-b", "_b10_st.txt", "-d", "course=c1", "-d", "act=off",
     BASE + "/staff/brigades_course")
db = registry()
need(db["курсы"][0].get("без_бригад") is True, "реестр: без_бригад = True")

sp = curl("-b", "_b10_st.txt", BASE + "/staff/course/c1")
need("⛔ отключены" in sp and "▶️ Включить бригады на курсе" in sp,
     "панель: состояние «отключены» + кнопка включения")
need("brigade_rename" not in sp and "brigade_max" not in sp,
     "панель: карточки бригад и лимит скрыты")
need("Бригады на курсе отключены: студенты сдают работы лично" in sp,
     "панель: пояснение")

cp = curl("-b", "_b10_ck.txt", BASE + "/course/c1")
need("Регистрация бригады" not in cp and
     "Бригады на этом курсе отключены" in cp,
     "курс студента: блок бригад скрыт, есть пояснение")

tp = curl("-b", "_b10_ck.txt", BASE + "/task/t1")
need('name="brigade"' not in tp and "отключены" in tp,
     "страница задания: сдача только личная")

ls = curl("-b", "_b10_ck.txt", BASE + "/lesson/l1")
need(ls != "", "страница занятия открывается")

# сдача за бригаду отклоняется, личная — проходит
body = ["-b", "_b10_ck.txt", "-F", "task=t1"]
for k, v in FORM.items():
    body += ["-F", "%s=%s" % (k, urllib.parse.quote(v))]
r = subprocess.run(["curl.exe", "-s", "-i"] + body + ["-F", "brigade=BR10",
                   BASE + "/api/submit"], capture_output=True)
hdr = r.stdout.decode("utf-8", "replace")
need("Location: /task/t1?error=" in hdr,
     "сдача за бригаду при отключённых бригадах: отказ", hdr[:160])
err = urllib.parse.unquote_plus(hdr.split("Location: /task/t1?error=")[-1]
                                .split("\r\n")[0]) if "error=" in hdr else ""
need("бригады на этом курсе отключены" in err, "текст отказа понятен", err)

r = subprocess.run(["curl.exe", "-s", "-i"] + body + [BASE + "/api/submit"],
                   capture_output=True)
hdr = r.stdout.decode("utf-8", "replace")
need("Location: /mysub/t1" in hdr,
     "личная сдача при отключённых бригадах: принимается", hdr[:160])

# прямая попытка вступить — отказ
j = curl("-sL", "-b", "_b10_ck.txt", "-d", "course=c1", "-d", "act=join",
         "-d", "name=BR10", BASE + "/brigade")
need("Бригады на этом курсе отключены" in j, "вступление: отказ")

# страница «Мои задания» жива (бригада курса игнорируется)
my = curl("-b", "_b10_ck.txt", BASE + "/my")
need("mx-tbl" in my or "не зачислены" in my, "мои задания: работает")

# ── включаем обратно ──────────────────────────────────────────────────
curl("-b", "_b10_st.txt", "-d", "course=c1", "-d", "act=on",
     BASE + "/staff/brigades_course")
db = registry()
need(db["курсы"][0].get("без_бригад") is None, "включено: флаг снят")
cp2 = curl("-b", "_b10_ck.txt", BASE + "/course/c1")
need("Регистрация бригады" in cp2, "курс студента: регистрация снова видна")

r = subprocess.run(["curl.exe", "-s", "-i"] + body + ["-F", "brigade=BR10",
                   BASE + "/api/submit"], capture_output=True)
hdr = r.stdout.decode("utf-8", "replace")
need("Location: /mysub/t1" in hdr,
     "сдача за бригаду после включения: принимается", hdr[:160])

acts = []
for f in glob.glob("_teststore/лог/*.jsonl"):
    for ln in io.open(f, encoding="utf-8"):
        if ln.strip():
            acts.append(json.loads(ln).get("действие", ""))
need("бригады курса отключены" in acts and "бригады курса включены" in acts,
     "аудит: события включения/отключения бригад курса")

for p in ("_b10_st.txt", "_b10_ck.txt"):
    if os.path.exists(p):
        os.remove(p)
print("BRIG10 OK" if ok else "BRIG10 FAIL")
sys.exit(0 if ok else 1)
