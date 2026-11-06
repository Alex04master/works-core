# -*- coding: utf-8 -*-
"""Проверка модуля «Автотест»: автопроверка тестовых заданий.

Запуск: python -X utf8 tests/_chk_autotest.py
Создаёт временный реестр (курс/занятие/3 задания/4 студента), поднимает
сервер на порту 8098 и проверяет: верные/неверные/смешанные ответы,
допуск числа, запятая-точка, ключевые слова, список допустимых, веса,
вторые версии, отсутствие правил, импорт курса-пакета (правила
автопроверки переносятся вместе с заданием) и работу правил в
импортированном задании.
"""
import http.client
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(ROOT, "tests", "_tmp_autotest_store")
PORT = 8098
C_TITLE = "Тестовый курс · Демо автопроверки"
T_TITLE = "Тест-демо: автопроверка (4 вопроса)"

RULES = [
    {"field": "q1", "type": "exact", "expect": "Шлейф сигнализации",
     "вопрос": "ШС — расшифровка"},
    {"field": "q2", "type": "number", "expect": 12, "допуск": 0.5,
     "вопрос": "Число с допуском"},
    {"field": "q3", "type": "keywords", "expect": "линия извещател",
     "вопрос": "Ключевые слова"},
    {"field": "q4", "type": "oneof", "expect": ["ШС", "шлейф сигнализации"],
     "вопрос": "Список допустимых"},
]

T1 = {
    "id": "t1", "lesson": "l1", "title": T_TITLE,
    "описание": "## Демонстрация автопроверки\n\n1. Точное совпадение.\n"
                "2. Число с допуском ±0,5 (введите 12).\n"
                "3. Ключевые слова: «линия» и «извещатель».\n"
                "4. Список допустимых: ШС или «шлейф сигнализации».",
    "форма": [
        {"ключ": "q1", "тип": "select", "вопрос": "ШС — это…",
         "варианты": ["Шлейф сигнализации", "Шкаф связи", "Шифр секретный"],
         "обязательно": True},
        {"ключ": "q2", "тип": "number", "вопрос": "Число с допуском ±0,5",
         "обязательно": True, "мин": 0, "макс": 30},
        {"ключ": "q3", "тип": "textarea", "вопрос": "Ключевые слова",
         "обязательно": True, "строк": 3},
        {"ключ": "q4", "тип": "text", "вопрос": "Сокращение ШС",
         "обязательно": True},
    ],
    "материалы": [],
    "настройки": {"автопроверка": RULES},
    "выдано": [],
}
T2 = {
    "id": "t2", "lesson": "l1", "title": "Веса пунктов",
    "описание": "q1 — вес 2, q2 — вес 1.",
    "форма": [
        {"ключ": "q1", "тип": "select", "вопрос": "Сигнал при пожаре",
         "варианты": ["Тревога", "Неисправность"], "обязательно": True},
        {"ключ": "q2", "тип": "number", "вопрос": "Число", "обязательно": True},
    ],
    "материалы": [],
    "настройки": {"автопроверка": [
        {"field": "q1", "type": "exact", "expect": "Тревога",
         "вопрос": "Сигнал", "вес": 2},
        {"field": "q2", "type": "number", "expect": 10, "вопрос": "Число"},
    ]},
    "выдано": [],
}
T3 = {
    "id": "t3", "lesson": "l1", "title": "Без правил автопроверки",
    "описание": "Обычное задание: автопроверка не применяется.",
    "форма": [{"ключ": "q1", "тип": "select", "вопрос": "Выбор",
               "варианты": ["А", "Б"], "обязательно": True}],
    "материалы": [],
    "настройки": {},
    "выдано": [],
}
STUDENTS = [
    {"id": "s1", "fio": "Тестов Тест Тестович", "group": "Демо", "бригада": ""},
    {"id": "s2", "fio": "Петров П.П.", "group": "Демо", "бригада": ""},
    {"id": "s3", "fio": "Сидоров С.С.", "group": "Демо", "бригада": ""},
    {"id": "s4", "fio": "Козлов К.К.", "group": "Демо", "бригада": ""},
]


def wait_port(port, timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def post(conn, path, fields, cookie=""):
    body = urllib.parse.urlencode(fields, doseq=True)
    conn.request("POST", path, body=body, headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Cookie": cookie})
    r = conn.getresponse()
    return r, r.read()


def post_multipart(conn, path, files, fields=None, cookie=""):
    b = "----chk" + str(int(time.time() * 1000))
    parts = []
    for k, v in (fields or {}).items():
        parts.append(("--" + b,
                      'Content-Disposition: form-data; name="%s"' % k,
                      "", str(v)))
    for k, fname, data in files:
        parts.append(("--" + b,
                      'Content-Disposition: form-data; name="%s"; '
                      'filename="%s"' % (k, fname),
                      "application/octet-stream", data))
    chunks = []
    for head, disp, ctype, payload in parts:
        chunks.append(head + "\r\n" + disp)
        if ctype:
            chunks[-1] += "\r\nContent-Type: " + ctype
        chunks[-1] += "\r\n\r\n"
        chunks.append(payload if isinstance(payload, bytes)
                      else payload.encode("utf-8"))
        chunks.append("\r\n")
    chunks.append("--" + b + "--\r\n")
    body = b"".join(c.encode("utf-8") if isinstance(c, str) else c
                    for c in chunks)
    conn.request("POST", path, body=body, headers={
        "Content-Type": "multipart/form-data; boundary=" + b,
        "Cookie": cookie})
    r = conn.getresponse()
    return r, r.read()


def get(conn, path, cookie=""):
    conn.request("GET", path, headers={"Cookie": cookie})
    r = conn.getresponse()
    return r, r.read()


def registry():
    with open(os.path.join(STORE, "реестр.json"), encoding="utf-8") as f:
        return json.load(f)


def subver(tid, sid):
    sub = registry()["сдачи"].get("%s__%s" % (tid, sid))
    assert sub, "нет сдачи %s__%s" % (tid, sid)
    return sub, sub["versions"][-1]


def main():
    if os.path.isdir(STORE):
        shutil.rmtree(STORE)
    os.makedirs(STORE)
    reg = {
        "версия": 3,
        "курсы": [{"id": "c1", "title": C_TITLE, "студенты": ["s1", "s2",
                                                             "s3", "s4"],
                   "группы": [], "бригада_макс": 0}],
        "занятия": [{"id": "l1", "course": "c1",
                     "title": "Занятие 1 · Демо автопроверки",
                     "материалы": []}],
        "задания": [T1, T2, T3],
        "студенты": STUDENTS,
        "сдачи": {},
    }
    with open(os.path.join(STORE, "реестр.json"), "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=1)

    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", "server.py", "--port", str(PORT),
         "--store", STORE, "--no-pass"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    checks = []

    def check(name, cond, extra=""):
        checks.append((name, bool(cond)))
        print(("OK   " if cond else "ПРОВАЛ: ") + name +
              ("" if cond else " :: " + str(extra)[:400]))

    def good(title, tid, sid, verdict="Тест пройден (автопроверка)",
             score=100.0, status="принято"):
        _sub, ver = subver(tid, sid)
        check("%s: вердикт" % title, ver.get("verdict") == verdict,
              (ver.get("verdict"), ver.get("comment")))
        check("%s: балл" % title, ver.get("score") == score,
              (ver.get("score"),))
        check("%s: статус" % title,
              (_sub.get("status") == status), _sub.get("status"))

    try:
        assert wait_port(PORT), "сервер не поднялся"
        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=20)

        r, _ = post(conn, "/_staff_login", {"pass": "x"})
        staff_ck = (r.getheader("Set-Cookie") or "").split(";")[0]
        check("вход персонала", "staff_token" in staff_ck, staff_ck)
        cookies = {}
        for sid in ("s1", "s2", "s3", "s4"):
            r, _ = post(conn, "/_login", {"student": sid})
            cookies[sid] = (r.getheader("Set-Cookie") or "").split(";")[0]
        check("входы студентов", all(cookies[s].startswith("student=%s." % s)
                                     for s in cookies), str(cookies)[:120])

        # ── форма задания содержит вопросы ──────────────────────────
        r, page = get(conn, "/task/t1", cookie=cookies["s1"])
        ptxt = page.decode("utf-8", "replace")
        check("форма t1: поля и варианты", r.status == 200 and
              'name="q1"' in ptxt and 'name="q4"' in ptxt and
              "Шлейф сигнализации" in ptxt, str(r.status))

        # ── верные ответы s1 ────────────────────────────────────────
        r, _ = post(conn, "/api/submit",
                    {"task": "t1", "q1": "Шлейф сигнализации", "q2": "12",
                     "q3": "пожарные извещатели соединены линией связи",
                     "q4": "ШС"}, cookie=cookies["s1"])
        check("s1: redirect на /mysub",
              (r.getheader("Location") or "").endswith("/mysub/t1"),
              r.getheader("Location"))
        r, page = get(conn, "/mysub/t1", cookie=cookies["s1"])
        ptxt = page.decode("utf-8", "replace")
        check("s1: на странице вердикт и балл",
              "Тест пройден (автопроверка)" in ptxt and "Балл" in ptxt,
              ptxt[:150])
        good("s1 правильные", "t1", "s1")
        _sub, ver = subver("t1", "s1")
        cm = ver.get("comment", "")
        check("s1: разбор 4 ✔ и без утечки ответов",
              cm.count("✔") == 4 and cm.count("✘") == 0 and
              "Шлейф сигнализации" not in cm and
              cm.startswith("Проверка: "), cm)

        # ── неверные ответы s2 ──────────────────────────────────────
        r, _ = post(conn, "/api/submit",
                    {"task": "t1", "q1": "Шкаф связи", "q2": "30",
                     "q3": "всё сделано по инструкции", "q4": "зонтик"},
                    cookie=cookies["s2"])
        good("s2 неверные", "t1", "s2", verdict="Тест: 0 из 4 верно",
             score=0.0, status="доработка")
        r, page = get(conn, "/mysub/t1", cookie=cookies["s2"])
        check("s2: на странице вердикт", "Тест: 0 из 4 верно" in
              page.decode("utf-8", "replace"), page[:150])

        # ── смешанные s3: запятая в числе, одно слово, вариант не тот ─
        r, _ = post(conn, "/api/submit",
                    {"task": "t1", "q1": "Шлейф сигнализации", "q2": "11,8",
                     "q3": "извещатель", "q4": "ЛС"}, cookie=cookies["s3"])
        good("s3 смешанные", "t1", "s3", verdict="Тест: 2 из 4 верно",
             score=50.0, status="доработка")
        _sub, ver = subver("t1", "s3")
        cm = ver.get("comment", "")
        check("s3: разбор 2 ✔ · 2 ✘",
              cm.count("✔") == 2 and cm.count("✘") == 2, cm)

        # ── вторая версия s1: допуск, запятая, вариант из oneof ─────
        r, _ = post(conn, "/api/submit",
                    {"task": "t1", "q1": "Шлейф сигнализации", "q2": "11,8",
                     "q3": "линия связи содержит извещатели",
                     "q4": "шлейф сигнализации"}, cookie=cookies["s1"])
        good("s1 версия 2 (варианты/запятая)", "t1", "s1")
        _sub = registry()["сдачи"]["t1__s1"]
        check("s1: две версии, первая сохранена",
              len(_sub["versions"]) == 2 and
              _sub["versions"][0]["verdict"] ==
              "Тест пройден (автопроверка)",
              [v.get("verdict") for v in _sub["versions"]])

        # ── веса: t2, q1=2 q2=1 ─────────────────────────────────────
        r, _ = post(conn, "/api/submit",
                    {"task": "t2", "q1": "Неисправность", "q2": "10"},
                    cookie=cookies["s4"])
        good("s4 t2: 1 из 3 по весам", "t2", "s4",
             verdict="Тест: 1 из 3 верно", score=33.3, status="доработка")
        r, _ = post(conn, "/api/submit",
                    {"task": "t2", "q1": "Тревога", "q2": "10"},
                    cookie=cookies["s4"])
        good("s4 t2 версия 2: всё верно", "t2", "s4")

        # ── задание без правил: автопроверка не вмешивается ─────────
        r, _ = post(conn, "/api/submit", {"task": "t3", "q1": "А"},
                    cookie=cookies["s4"])
        _sub, ver = subver("t3", "s4")
        check("t3 без правил: вердикт пуст, статус «сдано»",
              ver.get("verdict") in (None, "") and
              ver.get("score") in (None, "") and
              _sub.get("status") == "сдано",
              (ver.get("verdict"), _sub.get("status")))

        # ── преподаватель видит автопроверку в работе студента ──────
        r, page = get(conn, "/staff/sub/t1__s1", cookie=staff_ck)
        ptxt = page.decode("utf-8", "replace")
        check("staff: просмотр работы с автопроверкой",
              r.status == 200 and "Тест пройден (автопроверка)" in ptxt and
              "✔" in ptxt, str(r.status))

        # ── импорт курса-пакета: правила переносятся ────────────────
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("пакет.json", json.dumps(
                {"формат": "works-core-курс", "версия": 1},
                ensure_ascii=False))
            zf.writestr("курс.json", json.dumps(
                {"id": "c1", "title": C_TITLE, "студенты": ["s1"],
                 "группы": [], "бригада_макс": 0}, ensure_ascii=False))
            zf.writestr("занятия.json", json.dumps(
                [{"id": "l1", "course": "c1",
                  "title": "Занятие 1 · Демо автопроверки",
                  "материалы": []}], ensure_ascii=False))
            zf.writestr("задания.json", json.dumps([T1], ensure_ascii=False))
            zf.writestr("студенты.json", json.dumps(
                [{"id": "s1", "fio": "Тестов Тест Тестович",
                  "group": "Демо", "бригада": ""}], ensure_ascii=False))
        pkg = buf.getvalue()
        r, _ = post_multipart(conn, "/staff/course_import",
                              [("pkgfile", "курс.zip", pkg)],
                              fields={"results": ""}, cookie=staff_ck)
        check("импорт: редирект на /staff",
              (r.getheader("Location") or "").startswith("/staff"),
              (r.getheader("Location"), r.status))

        db = registry()
        nc = [c for c in db["курсы"]
              if c["id"] != "c1" and c.get("title") == C_TITLE]
        check("импорт: курс появился", bool(nc), [c["id"] for c in
                                                  db["курсы"]])
        nc2 = nc[-1]
        nl = [l for l in db["занятия"] if l.get("course") == nc2["id"]]
        lset = {l["id"] for l in nl}
        nt = [t for t in db["задания"] if t.get("lesson") in lset]
        check("импорт: занятие и задание перенесены",
              len(nl) == 1 and len(nt) == 1 and nt[0]["title"] == T_TITLE,
              [(l["id"], t["title"]) for l in nl for t in nt])
        rules2 = (nt[0].get("настройки") or {}).get("автопроверка")
        check("импорт: правила автопроверки в настройках задания",
              json.dumps(rules2, sort_keys=True, ensure_ascii=False) ==
              json.dumps(RULES, sort_keys=True, ensure_ascii=False),
              rules2)
        check("импорт: студент Тестов зачислен (объединён по ФИО)",
              "s1" in (nc2.get("студенты") or []), nc2.get("студенты"))
        ntid = nt[0]["id"]

        # ── правила работают в импортированном задании ──────────────
        r, _ = post(conn, "/api/submit",
                    {"task": ntid, "q1": "Шлейф сигнализации", "q2": "12",
                     "q3": "пожарные извещатели соединены линией связи",
                     "q4": "ШС"}, cookie=cookies["s1"])
        good("импортированное задание: автопроверка", ntid, "s1")

        ok = all(c for _n, c in checks)
        print()
        print("ОТЛИЧНО (%d/%d)" % (sum(1 for _n, c in checks if c),
                                   len(checks)) if ok else "ЕСТЬ ПРОВАЛЫ")
        sys.exit(0 if ok else 1)
    finally:
        proc.terminate()
        try:
            proc.communicate(timeout=10)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    main()
