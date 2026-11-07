# -*- coding: utf-8 -*-
"""Полный цикл офлайн-сдачи СЦЕНАРНОГО задания (модель 1.4.0):
преподаватель создаёт задание (план обязателен) и ВЫДАЁТ персональный
бланк студенту -> студент загружает файл работы -> сдача с планом «[]»
и пометкой. PORT/STORE из env (по умолчанию 8099/_teststore)."""
import glob
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import zipfile

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PORT = os.environ.get("PORT", "8099")
STORE = os.environ.get("STORE", "_teststore")
BASE = "http://localhost:" + PORT
ok = True


def need(cond, msg):
    global ok
    print(("OK   " if cond else "FAIL ") + msg)
    ok = ok and bool(cond)


def curl(*args):
    r = subprocess.run(["curl.exe", "-s"] + list(args), capture_output=True)
    return r.stdout.decode("utf-8", "replace")


def blob_curl(*args):
    r = subprocess.run(["curl.exe", "-s"] + list(args), capture_output=True)
    return r.stdout


form = ('[{"ключ":"plan_data","тип":"hidden","обязательно":true},'
        '{"ключ":"calc","тип":"textarea","вопрос":"Calc",'
        '"обязательно":true,"строк":3}]')
curl("-c", "_off_st.txt", "-d", "pass=x", BASE + "/_staff_login")
curl("-c", "_off_ck.txt", "-d", "student=s1", "-d", "next=/",
     BASE + "/_login")
curl("-s", "-i", "-b", "_off_st.txt", "-d", "lesson=l1",
     "-d", "title=SCNOFF", BASE + "/staff/new_task")
d = json.load(io.open(glob.glob(os.path.join(STORE, "*.json"))[0],
                      encoding="utf-8"))
tid = ""
for t in d["задания"]:
    if t.get("title") == "SCNOFF":
        tid = t["id"]
        break
if tid:
    curl("-b", "_off_st.txt", "-d", "title=SCNOFF", "-d", "description=",
         "--data-urlencode", "form_json=" + form, "-d", "deadline=",
         BASE + "/staff/edit_task/" + tid)
    d = json.load(io.open(glob.glob(os.path.join(STORE, "*.json"))[0],
                          encoding="utf-8"))
need(bool(tid), "scenario task created")
if not tid:
    sys.exit(1)
curl("-b", "_off_st.txt", "-d", "task=" + tid, "-d", "all=on",
     BASE + "/staff/task_issue")

# персональный бланк: преподаватель выдаёт
zb = blob_curl("-b", "_off_st.txt", "-d", "task=" + tid,
               "-d", "student=s1", BASE + "/staff/offline/issue")
z = zipfile.ZipFile(io.BytesIO(zb))
inner = [n for n in z.namelist() if n.endswith(".zip")]
if inner:
    z2 = zipfile.ZipFile(io.BytesIO(z.read(inner[0])))
else:
    z2 = z  # один студент: сервер отдаёт «ФИО.zip» напрямую
bhtml = [n for n in z2.namelist() if n.endswith(".html")][0]
blank = z2.read(bhtml).decode("utf-8")
msig = re.search(r'"sig": "([0-9a-f]+)"', blank)
mtok = re.search(r'"token": "([0-9a-f]{24})"', blank)
need(bool(msig) and bool(mtok), "issued blank: sig + token present")
need("Иванов И.И." in blank, "issued blank: student fio inside")

payload = {
    "формат": "works-core-работа", "версия": 1, "задание": tid,
    "курс": "c1", "занятие": "l1",
    "студент": {"sid": "s1", "подпись": msig.group(1) if msig else "",
                "fio": "Иванов И.И.", "group": "", "бригада": ""},
    "токен": mtok.group(1) if mtok else "",
    "когда": time.strftime("%Y-%m-%dT%H:%M:%S"),
    "примечание": "",
    "ответы": {"calc": "тестовый расчёт"},
    "файлы": {},
}
with io.open("_off_work.json", "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False)
res = curl("-b", "_off_ck.txt", "-F",
           "work=@_off_work.json;type=application/json",
           BASE + "/offline/upload")
need("принято" in res or "ok" in res.lower(), "offline upload accepted")

d = json.load(io.open(glob.glob(os.path.join(STORE, "*.json"))[0],
                      encoding="utf-8"))
sub = d["сдачи"].get(tid + "__s1")
need(bool(sub), "submission created")
if sub:
    ver = sub["versions"][-1]
    need(ver.get("answers", {}).get("plan_data") == "[]",
         "plan_data auto-substituted")
    need("офлайн" in (ver.get("note") or ""),
         "note marks offline submission")

for p in ("_off_st.txt", "_off_ck.txt", "_off_work.json"):
    os.remove(p)
print("PLANOFF OK" if ok else "PLANOFF FAIL")
sys.exit(0 if ok else 1)
