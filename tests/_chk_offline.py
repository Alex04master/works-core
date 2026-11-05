# -*- coding: utf-8 -*-
"""Проверка модуля «Офлайн-сдача»: бланк, загрузка, импорт пачки.

Запуск: python -X utf8 tests/_chk_offline.py
Создаёт временный реестр (курс/занятие/задание/студенты), поднимает сервер
на порту 8097 и проходит весь цикл офлайн-сдачи.
"""
import base64
import hashlib
import hmac
import http.client
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import zipfile

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(ROOT, "tests", "_tmp_offline_store")
PORT = 8097
B64 = lambda s: base64.b64encode(s).decode("ascii")


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
    body = urllib.parse.urlencode(fields)
    conn.request("POST", path, body=body, headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Cookie": cookie})
    r = conn.getresponse()
    data = r.read()
    return r, data


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


def main():
    if os.path.isdir(STORE):
        shutil.rmtree(STORE)
    os.makedirs(STORE)

    # ── сид реестра: курс, занятие, задание с формой, 3 студента ────
    reg = {
        "версия": 3,
        "курсы": [{"id": "c1", "title": "Тестовый курс", "группы": []}],
        "занятия": [{"id": "l1", "course": "c1", "title": "Занятие 1",
                     "материалы": []}],
        "задания": [{
            "id": "t1", "lesson": "l1", "title": "Тестовое задание",
            "описание": "## Ситуация\nСделайте что-нибудь.\n\n## Задания\n1. Пункт",
            "форма": [
                {"ключ": "sketch", "тип": "file",
                 "вопрос": "Файл схемы (.robxsim)", "обязательно": True,
                 "accept": ".robxsim"},
                {"ключ": "answer", "тип": "textarea", "вопрос": "Решение",
                 "обязательно": True, "строк": 6},
                {"ключ": "period", "тип": "number",
                 "вопрос": "Период, мс", "обязательно": True,
                 "мин": 50, "макс": 5000},
                {"ключ": "mode", "тип": "select", "вопрос": "Режим",
                 "варианты": ["норма", "тревога"], "обязательно": True},
            ],
            "настройки": {},
            "выдано": []}],
        "студенты": [
            {"id": "s1", "fio": "Иванов И.И.", "group": "П-21", "бригада": ""},
            {"id": "s2", "fio": "Петров П.П.", "group": "П-21", "бригада": ""},
            {"id": "s3", "fio": "Сидоров С.С.", "group": "П-22", "бригада": ""},
        ],
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
        if not cond:
            print("ПРОВАЛ: %s %s" % (name, extra[:400]))

    try:
        assert wait_port(PORT), "сервер не поднялся"
        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=20)

        # ── вход персонала и студента ────────────────────────────────
        r, _ = post(conn, "/_staff_login", {"pass": "x"})
        staff_ck = (r.getheader("Set-Cookie") or "").split(";")[0]
        check("вход персонала", "staff_token" in staff_ck, staff_ck)

        r, _ = post(conn, "/_login", {"student": "s1"})
        st1_ck = (r.getheader("Set-Cookie") or "").split(";")[0]
        check("вход студента s1", st1_ck.startswith("student=s1."), st1_ck)
        r, _ = post(conn, "/_login", {"student": "s2"})
        st2_ck = (r.getheader("Set-Cookie") or "").split(";")[0]

        # подпись: как в ядре
        with open(os.path.join(STORE, "_секрет.key"), "rb") as f:
            secret = f.read().strip()

        def sig(sid):
            return hmac.new(secret, sid.encode("utf-8"),
                            hashlib.sha256).hexdigest()[:16]

        # ── бланк студента ───────────────────────────────────────────
        conn.request("GET", "/offline/blank/t1", headers={"Cookie": st1_ck})
        r = conn.getresponse()
        blank = r.read().decode("utf-8", "replace")
        check("бланк отдаётся", r.status == 200)
        check("бланк: форма сохранения", "Сохранить работу" in blank)
        check("бланк: ФИО подтянуто", "Иванов И.И." in blank, blank[:200])
        check("бланк: подпись в META", ("\"sig\": \"%s\"" % sig("s1")) in blank
              or ('"sig": "%s"' % sig("s1")) in blank)
        check("бланк: описание", "Сделайте что-нибудь" in blank)
        check("бланк: поле number", 'data-key="period"' in blank)
        check("бланк: поле file", 'data-type="file"' in blank)

        # анонимный бланк: поля ФИО для ввода
        conn.request("GET", "/offline/blank/t1")
        r = conn.getresponse()
        blank_anon = r.read().decode("utf-8", "replace")
        check("бланк аноним: ввод ФИО", 'id="bf_fio"' in blank_anon)

        # ── файл работы (как его собирает JS бланка) ─────────────────
        def make_work(sid, fio, group="П-21", brigade="", fio_field=None):
            return json.dumps({
                "формат": "works-core-работа", "версия": 1,
                "задание": "t1", "курс": "c1", "занятие": "l1",
                "студент": {"sid": sid, "подпись": sig(sid) if sid else "",
                            "fio": fio_field or fio, "группа": group,
                            "бригада": brigade},
                "когда": "2026-11-05T12:00:00",
                "примечание": "выполнено дома",
                "ответы": {"answer": "Решение из дома", "period": "600",
                           "mode": "норма"},
                "файлы": {"sketch": [{"имя": "схема.robxsim",
                                      "b64": B64(b"ROBXSIM-OK")}]},
            }, ensure_ascii=False).encode("utf-8")

        w1 = make_work("s1", "Иванов И.И.")

        # ── загрузка студентом ───────────────────────────────────────
        r, page = post_multipart(conn, "/offline/upload",
                                 [("work", "работа_t1_иванов.json", w1)],
                                 cookie=st1_ck)
        page = page.decode("utf-8", "replace")
        check("загрузка s1: принято", "1 из 1 принято" in page, page[:300])
        check("загрузка s1: сдано", "сдано:" in page)

        # повторная загрузка -> версия 2
        r, page = post_multipart(conn, "/offline/upload",
                                 [("work", "работа2.json", w1)],
                                 cookie=st1_ck)
        page = page.decode("utf-8", "replace")
        check("загрузка s1: версия 2", "версия 2" in page, page[:300])

        # ── работа другого студента при входе s1 ─────────────────────
        w2 = make_work("s2", "Петров П.П.")
        r, page = post_multipart(conn, "/offline/upload",
                                 [("work", "чужая.json", w2)],
                                 cookie=st1_ck)
        page = page.decode("utf-8", "replace")
        check("чужая работа отклонена", "другого студента" in page,
              page[:300])

        # битый файл
        r, page = post_multipart(conn, "/offline/upload",
                                 [("work", "битый.json",
                                   "{не json".encode("utf-8"))],
                                 cookie=st1_ck)
        page = page.decode("utf-8", "replace")
        check("битый файл отклонён", "не читается как JSON" in page)

        # реестр: версии, ответы, файл на диске
        with open(os.path.join(STORE, "реестр.json"), encoding="utf-8") as f:
            db = json.load(f)
        sub = db["сдачи"].get("t1__s1")
        check("сдача в реестре", bool(sub))
        check("2 версии", len(sub["versions"]) == 2)
        check("примечание офлайн",
              "офлайн-сдача" in sub["versions"][0]["note"])
        fpath = os.path.join(STORE, "сдачи",
                             sub["versions"][0]["files"]["sketch"]["файл"])
        with open(fpath, "rb") as f:
            check("вложение на диске", f.read() == b"ROBXSIM-OK")
        check("ответы формы", float(sub["versions"][0]["answers"]["period"])
              == 600 and sub["versions"][0]["answers"]["mode"] == "норма")

        # ── импорт пачки преподавателем ──────────────────────────────
        w_s2_auto = make_work("", "Петров П.П.", "П-21")   # ФИО распознается
        w_unknown = make_work("", "Кто-то Чужой", "Х-99")  # не распознан
        r, page = post_multipart(conn, "/staff/offline/import", [
            ("work", "петров.json", w_s2_auto),
            ("work", "чужой.json", w_unknown),
        ], cookie=staff_ck)
        page = page.decode("utf-8", "replace")
        check("пачка: Петров принят", "Петров П.П." in page, page[:400])
        check("пачка: нужен выбор", "Нужен выбор студента (1)" in page)
        m = re.search(r'name="batch" value="([0-9a-f]+)"', page)
        check("пачка: id батча", bool(m))
        batch_id = m.group(1) if m else ""

        # ручное зачисление за Сидорова
        r, page = post(conn, "/staff/offline/manual",
                       {"batch": batch_id, "sel_0": "s3"},
                       cookie=staff_ck)
        page = page.decode("utf-8", "replace")
        check("ручной выбор: сдано", "Сидоров С.С." in page, page[:400])
        with open(os.path.join(STORE, "реестр.json"), encoding="utf-8") as f:
            db = json.load(f)
        check("Сидорову записана сдача", "t1__s3" in db["сдачи"])

        # подделанная подпись
        bad = make_work("s1", "Иванов И.И.")
        old = ('"подпись": "%s"' % sig("s1")).encode("utf-8")
        fake = '"подпись": "0000000000000000"'.encode("utf-8")
        bad = bad.replace(old, fake)
        r, page = post_multipart(conn, "/staff/offline/import",
                                 [("work", "подделка.json", bad)],
                                 cookie=staff_ck)
        page = page.decode("utf-8", "replace")
        check("поддельная подпись отклонена", "подпись работы не совпадает"
              in page, page[:400])

        # ── бланки занятия .zip ──────────────────────────────────────
        conn.request("GET", "/staff/offline/blanks/l1",
                     headers={"Cookie": staff_ck})
        r = conn.getresponse()
        zdata = r.read()
        check("бланки: zip", r.status == 200 and zdata[:2] == b"PK")
        zf = zipfile.ZipFile(io.BytesIO(zdata))
        names = zf.namelist()
        check("бланки: 1 файл t1", len(names) == 1 and
              names[0].endswith(".html"), str(names))
        inner = zf.read(names[0]).decode("utf-8", "replace")
        check("бланки: внутри бланк задания",
              "Тестовое задание" in inner and 'id="bf_fio"' in inner)

        # страница студента и панель преподавателя открываются
        conn.request("GET", "/offline", headers={"Cookie": st1_ck})
        r = conn.getresponse()
        check("страница /offline", r.status == 200 and "Офлайн-сдача"
              in r.read().decode("utf-8", "replace"))
        conn.request("GET", "/staff/offline", headers={"Cookie": staff_ck})
        r = conn.getresponse()
        page = r.read().decode("utf-8", "replace")
        check("панель /staff/offline", r.status == 200 and
              "Импорт работ" in page and "Бланки .zip" in page)

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
