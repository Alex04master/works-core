# -*- coding: utf-8 -*-
"""Включение/отключение бригады преподавателем.

Запуск: python -X utf8 tests/_chk_brig9.py  (сервер с _teststore на 8099).
Проверки: /staff/brigade_state off/on; отключённая бригада — сдача за
бригаду отклонена, вступление закрыто, метки на странице курса и доске,
состав сохраняется; включённая — работает как раньше; события в аудите.
"""
import glob
import io
import json
import os
import re
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


def audit_actions():
    acts = []
    for f in glob.glob("_teststore/лог/*.jsonl"):
        for ln in io.open(f, encoding="utf-8"):
            if ln.strip():
                acts.append(json.loads(ln).get("действие", ""))
    return acts


FORM = {"width": "24", "length": "18", "height": "4.2",
        "detector_type": "ИП 212 (дымовой)", "detectors_num": "6",
        "loops": "2", "justification": "brig9 test"}

# ── подготовка: студент s1 в бригаде BR9 (как преподаватель) ──────────
curl("-c", "_br9_st.txt", "-d", "pass=x", BASE + "/_staff_login")
curl("-c", "_br9_ck.txt", "-d", "student=s1", "-d", "next=/",
     BASE + "/_login")
curl("-b", "_br9_st.txt", "-d", "student=s1", "-d", "course=c1",
     "-d", "brigade=BR9", BASE + "/staff/student_brigade")
db = registry()
s1 = next(s for s in db["студенты"] if s["id"] == "s1")
need((s1.get("бригада") or "") == "BR9", "подготовка: s1 в бригаде BR9")

# сдача за бригаду до отключения — работает
body = ["-b", "_br9_ck.txt", "-F", "task=t1"]
for k, v in FORM.items():
    body += ["-F", "%s=%s" % (k, urllib.parse.quote(v))]
body += ["-F", "brigade=BR9"]
r = subprocess.run(["curl.exe", "-s", "-i"] + body + [BASE + "/api/submit"],
                   capture_output=True)
hdr = r.stdout.decode("utf-8", "replace")
need("Location: /mysub/t1" in hdr, "до отключения: сдача за бригаду OK",
     hdr[:160])

# ── отключение бригады преподавателем ─────────────────────────────────
curl("-b", "_br9_st.txt", "-d", "course=c1", "-d", "name=BR9",
     "-d", "act=off", BASE + "/staff/brigade_state")
db = registry()
need(db.get("бригады_откл", {}).get("BR9") is True,
     "отключена: флаг в реестре")

sp = curl("-b", "_br9_st.txt", BASE + "/staff/course/c1")
need("⛔ отключена" in sp and "brigade_state" in sp,
     "панель: метка и кнопки включения/отключения")
need("▶️ Включить" in sp, "панель: кнопка «Включить» у отключённой")
need('style="margin:8px 0;opacity:.55"' in sp, "панель: блок бригады приглушён")

cp = curl("-b", "_br9_ck.txt", BASE + "/course/c1")
m = re.search(r"<li>(?:(?!</li>).)*BR9(?:(?!</li>).)*</li>", cp)
need(bool(m) and "отключена" in m.group(0) and 'value="join"' not in m.group(0),
     "страница курса: BR9 помечена, вступления нет", m.group(0) if m else "")
need("отключена преподавателем — сдача за бригаду закрыта" in cp,
     "страница курса: предупреждение в «Моя бригада»")

bd = curl("-b", "_br9_st.txt", BASE + "/board")
need("· отключена" in bd, "доска: бригада помечена отключённой")

# сдача за отключённую бригаду — отказ
r = subprocess.run(["curl.exe", "-s", "-i"] + body + [BASE + "/api/submit"],
                   capture_output=True)
hdr = r.stdout.decode("utf-8", "replace")
need("Location: /task/t1?error=" in hdr,
     "сдача за отключённую бригаду: отказ", hdr[:160])
err = urllib.parse.unquote_plus(hdr.split("Location: /task/t1?error=")[-1]
                                .split("\r\n")[0]) if "error=" in hdr else ""
need("отключена преподавателем" in err and "лично" in err,
     "текст отказа понятен", err)

tp = curl("-b", "_br9_ck.txt", BASE + "/task/t1")
need("отключена преподавателем" in tp and 'name="brigade"' not in tp,
     "страница задания: только личная сдача, выбор бригады скрыт")

# вступление в отключённую бригаду другим студентом — отказ
# (сначала убираем s2 из текущей бригады, чтобы join был возможен)
curl("-c", "_br9_ck2.txt", "-d", "student=s2", "-d", "next=/",
     BASE + "/_login")
curl("-b", "_br9_st.txt", "-d", "student=s2", "-d", "course=c1",
     "-d", "brigade=", BASE + "/staff/student_brigade")
j = curl("-sL", "-b", "_br9_ck2.txt", "-d", "course=c1", "-d", "act=join",
         "-d", "name=BR9", BASE + "/brigade")
need("Бригада «BR9» отключена преподавателем" in j,
     "вступление в отключённую бригаду: отказ")

# смена состава сохраняется: преподаватель может перевести студента
curl("-b", "_br9_st.txt", "-d", "student=s2", "-d", "course=c1",
     "-d", "brigade=BR9", BASE + "/staff/student_brigade")
db = registry()
need((next(s for s in db["студенты"] if s["id"] == "s2").get("бригада")
      or "") == "BR9", "отключённая: состав можно править")

# ── включение обратно ─────────────────────────────────────────────────
curl("-b", "_br9_st.txt", "-d", "course=c1", "-d", "name=BR9",
     "-d", "act=on", BASE + "/staff/brigade_state")
db = registry()
need(not db.get("бригады_откл", {}).get("BR9"), "включена: флаг снят")
need((next(s for s in db["студенты"] if s["id"] == "s1").get("бригада")
      or "") == "BR9", "включена: состав бригады сохранён")
sp2 = curl("-b", "_br9_st.txt", BASE + "/staff/course/c1")
need("⏸ Отключить" in sp2, "панель: кнопка «Отключить» у включённой")
cp2 = curl("-b", "_br9_ck.txt", BASE + "/course/c1")
need('value="leave"' in cp2, "страница курса: бригада снова активна")

r = subprocess.run(["curl.exe", "-s", "-i"] + body + [BASE + "/api/submit"],
                   capture_output=True)
hdr = r.stdout.decode("utf-8", "replace")
need("Location: /mysub/t1" in hdr, "сдача за включённую бригаду: OK",
     hdr[:160])

acts = audit_actions()
need("бригада отключена" in acts and "бригада включена" in acts,
     "аудит: события отключения/включения")

for p in ("_br9_st.txt", "_br9_ck.txt", "_br9_ck2.txt"):
    if os.path.exists(p):
        os.remove(p)
print("BRIG9 OK" if ok else "BRIG9 FAIL")
sys.exit(0 if ok else 1)
