# -*- coding: utf-8 -*-
"""Проверка модуля «Антиплагиат и нейро-контроль» (свой сервер :8096).

Цикл: s1 сдаёт «человеческий» текст -> s2 сдаёт КОПИЮ -> антиплагиат
s2 = 100% + фрагменты; s3 сдаёт «нейросетевой» текст (штампы,
однообразие) -> высокая нейро-оценка; s1 пересдаёт другой текст ->
низкие показатели; API /plag/info и панель /plag.
"""
import glob
import http.cookiejar
import io
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PORT = os.environ.get("PORT", "8096")
STORE = os.environ.get("STORE", "_plag_store")
BASE = "http://localhost:" + PORT
ok = True


def need(cond, msg):
    global ok
    print(("OK   " if cond else "FAIL ") + msg)
    ok = ok and bool(cond)


def curl(*args):
    r = subprocess.run(["curl.exe", "-s"] + list(args), capture_output=True)
    return r.stdout.decode("utf-8", "replace")


def registry():
    d = json.load(io.open(glob.glob(os.path.join(STORE, "*.json"))[0],
                          encoding="utf-8"))
    return d


def login_staff(cookie):
    curl("-c", cookie, "-d", "pass=x", BASE + "/_staff_login")


def login_stu(cookie, sid):
    curl("-c", cookie, "-d", "student=" + sid, "-d", "next=/",
         BASE + "/_login")


def submit(cookie, tid, answer):
    curl("-b", cookie, "-F", "task=" + tid, "-F", "answer=" + answer,
         BASE + "/api/submit")


# ── логины ───────────────────────────────────────────────────────────
login_staff("_plag_st.txt")                     # преподаватель
login_stu("_plag_s1.txt", "s1")
login_stu("_plag_s2.txt", "s2")
login_stu("_plag_s3.txt", "s3")

# ── задание с текстовым полем ────────────────────────────────────────
curl("-b", "_plag_st.txt", "-d", "lesson=l1", "-d", "title=PLAGTEST",
     BASE + "/staff/new_task")
d = registry()
tid = ""
for t in d["задания"]:
    if t.get("title") == "PLAGTEST":
        tid = t["id"]
        break
need(bool(tid), "задание создано")
if not tid:
    sys.exit(1)
form = ('[{"ключ":"answer","тип":"textarea","вопрос":"Calc",'
        '"обязательно":true,"строк":5}]')
curl("-b", "_plag_st.txt", "-d", "title=PLAGTEST", "-d", "description=",
     "--data-urlencode", "form_json=" + form, "-d", "deadline=",
     BASE + "/staff/edit_task/" + tid)

T1 = ("Двухпроводная линия сигнализации. Короче, считаем ток. "
      "В шлейфе четыре извещателя. Ток покоя каждого 90 мкА, итого 360. "
      "Резервный элемент ещё 20 мкА. Провода полтора квадрата, длина "
      "250 м, падение 3,6 В. Это меньше нормы, значит идём дальше. "
      "Сопротивление шлейфа считаем по таблице, вышло 24 Ом. "
      "Порог прибора 2 кОм, запас почти двадцать раз. Вывод простой: "
      "шлейф нормальный, ставим ИПР и не забудем про резерв.")

T_AI = ("В современном мире вопрос защиты объектов играет важную роль. "
        "Следует отметить, что проектирование систем безопасности требует "
        "особого внимания. Кроме того, необходимо подчеркнуть, что выбор "
        "оборудования имеет важное значение. В настоящее время широко "
        "используется адресная система оповещения на объектах. "
        "Как известно, правильный расчёт шлейфов является одним из "
        "главных этапов. С одной стороны, существует множество решений "
        "для защиты помещений. С другой стороны, целесообразно применять "
        "современное оборудование на объекте. Таким образом, грамотный "
        "подход обеспечивает надёжную работу системы. В заключение стоит "
        "отметить, что данная работа имеет важное значение. Результаты "
        "показывают, что эффективность применения системы не вызывает "
        "сомнений.")

T2 = ("Шлейф считаем по токам покоя. Четыре дымовых извещателя и один "
      "ручной. Итого 380 мкА. Падение напряжения на линии небольшое. "
      "Сечение полтора квадрата хватает с запасом. Сопротивление 24 Ом "
      "при пороге 2 кОм. Резерв на расширение оставляем. Ставим "
      "ИПР 3 13 и ручник ИПР 513. Всё по нормам приложения.")

# s1 — «человеческий» текст
submit("_plag_s1.txt", tid, T1)
# s2 — ТОЧНАЯ КОПИЯ работы s1
submit("_plag_s2.txt", tid, T1)
# s3 — «нейросетевой» текст
submit("_plag_s3.txt", tid, T_AI)
# s1 — пересдача другим человеческим текстом
submit("_plag_s1.txt", tid, T2)


def ctl(sid, ver=-1):
    d = registry()
    sub = d["сдачи"].get(tid + "__" + sid)
    if not sub:
        return None
    return sub["versions"][ver].get("контроль")


c1 = ctl("s1", 0)
need(bool(c1) and c1["антиплагиат"]["процент"] == 0,
     "s1 v1: первый сдающий — сходство 0")
c2 = ctl("s2")
need(bool(c2) and c2["антиплагиат"]["процент"] >= 90,
     "s2: копия — антиплагиат >= 90%% (%s)"
     % (c2 or {}).get("антиплагиат", {}).get("процент"))
if c2 and c2["антиплагиат"]["совпадения"]:
    m = c2["антиплагиат"]["совпадения"][0]
    need(bool(m.get("фрагменты")), "s2: совпадающие фрагменты найдены")
    need("Иванов" in m.get("кто", ""), "s2: совпадение указывает на s1")
c3 = ctl("s3")
n3 = (c3 or {}).get("нейро") or {}
need(bool(n3) and n3.get("оценка", 0) >= 50,
     "s3: нейро-оценка >= 50 (%s)" % n3.get("оценка"))
n1v2 = (ctl("s1") or {}).get("нейро") or {}
need(n1v2.get("оценка", 0) <= 40,
     "s1 v2: человеческий текст — нейро <= 40 (%s)" % n1v2.get("оценка"))
a1v2 = (ctl("s1") or {}).get("антиплагиат") or {}
need(a1v2.get("процент", 0) < 30,
     "s1 v2: другой текст — антиплагиат < 30")

# флаги в сдаче
d = registry()
sub2 = d["сдачи"].get(tid + "__s2")
need(sub2.get("флаг") == "антиплагиат", "s2: флаг «антиплагиат» на сдаче")

# API для страницы сдачи
info = curl("-b", "_plag_st.txt",
            BASE + "/plag/info/" + tid + "__s2")
need('"есть": true' in info and "Контроль работы" in info,
     "API /plag/info отдаёт карточку")
# студент/аноним не видит
need("_login" in curl(BASE + "/plag/info/" + tid + "__s2") or
     "login" in curl(BASE + "/plag/info/" + tid + "__s2"),
     "API: без входа преподавателя не отвечает")

# панель
pg = curl("-b", "_plag_st.txt", BASE + "/plag?task=" + tid)
need("PLAGTEST" in pg and "v1" in pg, "панель: таблица по заданию")
need("s3" in pg or "Сидоров" in pg or "Максим" in pg or "%" in pg,
     "панель: строки сдач")
need("нейро" in pg, "панель: колонка нейро-оценки")

for p in ("_plag_st.txt", "_plag_s1.txt", "_plag_s2.txt", "_plag_s3.txt"):
    os.remove(p)
print("PLAG OK" if ok else "PLAG FAIL")
sys.exit(0 if ok else 1)
