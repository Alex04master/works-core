# -*- coding: utf-8 -*-
"""Закрытие бригады для сдач (модель редактора бригад 1.4+).

Запуск: python -X utf8 tests/_chk_brig9.py  (сервер с _teststore на 8099).
Проверки: сдача за бригаду; POST /staff/brigades_save (off=true) —
флаг «бригады_откл», чекбокс «закрыта для сдач» checked на панели,
сдача за бригаду отклонена («отключена преподавателем»), метка на доске;
brigades_save (off=false) — всё возвращается; аудит «сохранены бригады».
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


def audit_actions():
    acts = []
    for f in glob.glob("_teststore/лог/*.jsonl"):
        for ln in io.open(f, encoding="utf-8"):
            if ln.strip():
                acts.append(json.loads(ln).get("действие", ""))
    return acts


# ── подготовка: студент s1 в бригаде BR9 (как преподаватель) ──────────
curl("-c", "_br9_st.txt", "-d", "pass=x", BASE + "/_staff_login")
curl("-c", "_br9_ck.txt", "-d", "student=s1", "-d", "next=/",
     BASE + "/_login")

# сброс формы t1 (после _chk_sim там обязательный файл — мешает сдаче)
curl("-s", "-b", "_br9_st.txt", "--data-urlencode",
     "form_json=" + json.dumps([{"тип": "text", "ключ": "justification",
                                 "вопрос": "Обоснование",
                                 "обязательно": True}],
                               ensure_ascii=False),
     "-d", "title=", "-d", "description=", "-d", "deadline=",
     BASE + "/staff/edit_task/t1")
curl("-b", "_br9_st.txt", "-d", "student=s1", "-d", "course=c1",
     "-d", "brigade=BR9", BASE + "/staff/student_brigade")
db = registry()
s1 = next(s for s in db["студенты"] if s["id"] == "s1")
need((s1.get("бригада") or "") == "BR9", "подготовка: s1 в бригаде BR9")

# редактор бригад на странице курса
cp = curl("-b", "_br9_st.txt", BASE + "/staff/course/c1")
need("wc-br-name" in cp and "wc-br-del" in cp and "wc-br-save" in cp,
     "панель: редактор бригад (переименование + расформировать + сохранить)")
need("закрыта для сдач" in cp, "панель: чекбокс «закрыта для сдач»")

# ── до отключения: сдача за бригаду работает ──────────────────────────
hdr = curl("-s", "-i", "-b", "_br9_ck.txt", "-F", "task=t1",
           "-F", "justification=brig9 before", BASE + "/api/submit")
need("Location: /mysub/t1" in hdr, "до отключения: сдача за бригаду OK",
     hdr[:120])

# ── отключение бригады: brigades_save off=true ────────────────────────
payload = {"rows": [{"old": "BR9", "name": "BR9", "off": True,
                     "members": [{"sid": "s1", "fio": "Иванов И.И."}]}],
           "removed": []}
res = curl("-b", "_br9_st.txt", "-d", "course=c1",
           "--data-urlencode", "data=" + json.dumps(payload,
                                                    ensure_ascii=False),
           BASE + "/staff/brigades_save")
need('"ok": true' in res, "brigades_save off=true применён", res[:120])
db = registry()
need(db.get("бригады_откл", {}).get("BR9") is True,
     "реестр: флаг «бригады_откл.BR9»")

cp = curl("-b", "_br9_st.txt", BASE + "/staff/course/c1")
need("закрыта для сдач" in cp and "checked" in cp,
     "панель: чекбокс «закрыта для сдач» отмечен")

# личная сдача при отключённой бригаде — разрешена
hdr = curl("-s", "-i", "-b", "_br9_ck.txt", "-F", "task=t1",
           "-F", "justification=brig9 personal", BASE + "/api/submit")
need("Location: /mysub/t1" in hdr,
     "отключённая бригада: личная сдача разрешена", hdr[:120])
d = registry()
last = d["сдачи"].get("t1__s1")
need(bool(last) and last["versions"][-1].get("answers", {}).get("justification") == "brig9 personal",
     "личная сдача записана (новая версия, без бригадного режима)")

# принудительная бригадная сдача — отклонена ядром
hdr = curl("-s", "-i", "-b", "_br9_ck.txt", "-F", "task=t1",
           "-F", "justification=brig9 forced", "-F", "brigade=BR9",
           BASE + "/api/submit")
need("Location: /task/t1?error=" in hdr,
     "бригадная сдача за отключённую бригаду отклонена", hdr[:120])
qs = urllib.parse.unquote(hdr)
need("отключена преподавателем" in qs and "лично" in qs,
     "ошибка: объяснение студенту")
tp = curl("-b", "_br9_ck.txt", BASE + "/task/t1")
need("отключена преподавателем" in tp and 'name="brigade"' not in tp,
     "страница задания: пояснение, бригадное поле скрыто")
cp2 = curl("-b", "_br9_ck.txt", BASE + "/course/c1")
need("сдача за бригаду закрыта" in cp2,
     "страница курса: у своей бригады пометка «закрыта для сдач»")
bd = curl("-b", "_br9_st.txt", BASE + "/board")
need("· отключена" in bd, "доска: бригада помечена отключённой")

# ── включение бригады: brigades_save off=false ────────────────────────
payload["rows"][0]["off"] = False
res = curl("-b", "_br9_st.txt", "-d", "course=c1",
           "--data-urlencode", "data=" + json.dumps(payload,
                                                    ensure_ascii=False),
           BASE + "/staff/brigades_save")
need('"ok": true' in res, "brigades_save off=false применён", res[:120])
db = registry()
need(not db.get("бригады_откл", {}).get("BR9"), "включена: флаг снят")
s1 = next(s for s in db["студенты"] if s["id"] == "s1")
need((s1.get("бригада") or "") == "BR9", "включена: состав сохранён")
cp = curl("-b", "_br9_st.txt", BASE + "/staff/course/c1")
need('wc-br-off" data-i="0" checked' not in cp,
     "панель: чекбокс снова не отмечен")
hdr = curl("-s", "-i", "-b", "_br9_ck.txt", "-F", "task=t1",
           "-F", "justification=brig9 after", "-F", "brigade=BR9",
           BASE + "/api/submit")
need("Location: /mysub/t1" in hdr, "сдача за включённую бригаду: OK",
     hdr[:120])
d = registry()
last = d["сдачи"].get("t1__s1")
need(bool(last) and last.get("бригада") == "BR9",
     "сдача снова за бригаду (participants)")

acts = audit_actions()
need("сохранены бригады" in acts, "аудит: «сохранены бригады»")

for p in ("_br9_st.txt", "_br9_ck.txt"):
    os.remove(p)
print("BRIG9 OK" if ok else "BRIG9 FAIL")
sys.exit(0 if ok else 1)
