# -*- coding: utf-8 -*-
"""Проверка модуля «Антиплагиат и нейро-контроль» (самодостаточный:
поднимает сервер :8096 с хранилищем _plag_store, в конце гасит).

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
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PORT = 8096
STORE = "_plag_store"
BASE = "http://localhost:" + str(PORT)


def wait_port(port, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def mkop():
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj))


proc = None
shutil.rmtree(STORE, ignore_errors=True)
try:
    proc = subprocess.Popen(
        [sys.executable, "-u", "-X", "utf8", "server.py",
         "--port", str(PORT), "--store", STORE, "--demo", "--no-pass"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not wait_port(PORT):
        print("FAIL сервер не поднялся")
        sys.exit(1)

    op_st = mkop()
    ops = {sid: mkop() for sid in ("s1", "s2", "s3")}

    def open_url(op, p, fields=None):
        data = urllib.parse.urlencode(fields).encode() if fields else None
        with op.open(BASE + p, data) as r:
            return r.read().decode("utf-8", "replace")

    ok = True

    def need(cond, msg):
        global ok
        print(("OK   " if cond else "FAIL ") + msg)
        ok = ok and bool(cond)

    def registry():
        f = [x for x in glob.glob(os.path.join(STORE, "*.json"))
             if not os.path.basename(x).startswith("_")]
        return json.load(io.open(f[0], encoding="utf-8"))

    # ── логины ───────────────────────────────────────────────────────
    open_url(op_st, "/_staff_login", {"pass": "x"})
    for sid, o in ops.items():
        open_url(o, "/_login", {"student": sid, "next": "/"})

    # ── задание с текстовым полем ────────────────────────────────────
    open_url(op_st, "/staff/new_task",
             {"lesson": "l1", "title": "PLAGTEST"})
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
    open_url(op_st, "/staff/edit_task/" + tid,
             {"title": "PLAGTEST", "description": "", "form_json": form,
              "deadline": ""})

    T1 = ("Двухпроводная линия сигнализации. Короче, считаем ток. "
          "В шлейфе четыре извещателя. Ток покоя каждого 90 мкА, "
          "итого 360. Резервный элемент ещё 20 мкА. Провода полтора "
          "квадрата, длина 250 м, падение 3,6 В. Это меньше нормы, "
          "значит идём дальше. Сопротивление шлейфа считаем по таблице, "
          "вышло 24 Ом. Порог прибора 2 кОм, запас почти двадцать раз. "
          "Вывод простой: шлейф нормальный, ставим ИПР и не забудем "
          "про резерв.")

    T_AI = ("В современном мире вопрос защиты объектов играет важную "
            "роль. Следует отметить, что проектирование систем "
            "безопасности требует особого внимания. Кроме того, "
            "необходимо подчеркнуть, что выбор оборудования имеет "
            "важное значение. В настоящее время широко используется "
            "адресная система оповещения на объектах. Как известно, "
            "правильный расчёт шлейфов является одним из главных "
            "этапов. С одной стороны, существует множество решений для "
            "защиты помещений. С другой стороны, целесообразно "
            "применять современное оборудование на объекте. Таким "
            "образом, грамотный подход обеспечивает надёжную работу "
            "системы. В заключение стоит отметить, что данная работа "
            "имеет важное значение. Результаты показывают, что "
            "эффективность применения системы не вызывает сомнений.")

    T2 = ("Шлейф считаем по токам покоя. Четыре дымовых извещателя и "
          "один ручной. Итого 380 мкА. Падение напряжения на линии "
          "небольшое. Сечение полтора квадрата хватает с запасом. "
          "Сопротивление 24 Ом при пороге 2 кОм. Резерв на расширение "
          "оставляем. Ставим ИПР 3 13 и ручник ИПР 513. Всё по нормам "
          "приложения.")

    def submit(sid, answer):
        open_url(ops[sid], "/api/submit",
                 {"task": tid, "answer": answer})

    submit("s1", T1)     # человеческий
    submit("s2", T1)     # точная копия
    submit("s3", T_AI)   # «нейросетевой»
    submit("s1", T2)     # пересдача другим текстом

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
         "s2: копия — антиплагиат >= 90 (%s)"
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

    d = registry()
    sub2 = d["сдачи"].get(tid + "__s2")
    need(sub2.get("флаг") == "антиплагиат", "s2: флаг «антиплагиат»")

    info = open_url(op_st, "/plag/info/" + tid + "__s2")
    need('"есть": true' in info and "Контроль работы" in info,
         "API /plag/info отдаёт карточку")
    pg = open_url(op_st, "/plag?task=" + tid)
    need("PLAGTEST" in pg and "v1" in pg, "панель: таблица по заданию")
    need("нейро" in pg, "панель: колонка нейро-оценки")

    print("PLAG OK" if ok else "PLAG FAIL")
finally:
    if proc:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    shutil.rmtree(STORE, ignore_errors=True)
sys.exit(0 if ok else 1)
