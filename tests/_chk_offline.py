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
    body = urllib.parse.urlencode(fields, doseq=True)
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
        "курсы": [{"id": "c1", "title": "Тестовый курс",
                   "студенты": ["s1", "s2", "s3"], "группы": []}],
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

        # ── выдача бланков преподавателем ────────────────────────────
        r, zdata = post(conn, "/staff/offline/issue",
                        {"task": ["t1"], "student": ["s1"]},
                        cookie=staff_ck)
        check("выдача: архив отдаётся", r.status == 200 and
              zdata[:2] == b"PK", "%s %s" % (r.status, zdata[:60]))
        disp = r.getheader("Content-Disposition") or ""
        check("выдача: имя архива — zip", "zip" in disp.lower(), disp)
        zf = zipfile.ZipFile(io.BytesIO(zdata))
        names = zf.namelist()
        check("выдача: бланк + README", len(names) == 2 and
              names[0].endswith(".html") and "README.txt" in names,
              str(names))
        blank = zf.read([n for n in names if n.endswith(".html")][0]
                        ).decode("utf-8", "replace")
        check("бланк: форма сохранения", "Сохранить работу" in blank)
        check("бланк: ФИО подтянуто", "Иванов И.И." in blank, blank[:200])
        check("бланк: подпись в META", '"sig": "%s"' % sig("s1") in blank)
        check("бланк: описание", "Сделайте что-нибудь" in blank)
        check("бланк: поле number", 'data-key="period"' in blank)
        check("бланк: поле file", 'data-type="file"' in blank)

        # индивидуальный токен выдачи (защита от списывания)
        m_tok = re.search(r'"token": "([0-9a-f]+)"', blank)
        token1 = m_tok.group(1) if m_tok else ""
        check("бланк: токен в META", len(token1) == 24, token1)
        check("бланк: маркировка видна", "бланк промаркирован" in blank)

        # студент больше не может скачать бланк сам
        conn.request("GET", "/offline/blank/t1", headers={"Cookie": st1_ck})
        r = conn.getresponse()
        pno = r.read().decode("utf-8", "replace")
        check("бланк студенту закрыт", "Сохранить работу" not in pno,
              pno[:200])
        # предпросмотр анонимного бланка — преподавателю
        conn.request("GET", "/offline/blank/t1", headers={"Cookie": staff_ck})
        r = conn.getresponse()
        blank_anon = r.read().decode("utf-8", "replace")
        check("бланк аноним (предпросмотр): ввод ФИО",
              r.status == 200 and 'id="bf_fio"' in blank_anon, str(r.status))

        # ── файл работы (как его собирает JS бланка) ─────────────────
        def make_work(sid, fio, group="П-21", brigade="", fio_field=None,
                      token="", answers=None):
            return json.dumps({
                "формат": "works-core-работа", "версия": 1,
                "задание": "t1", "курс": "c1", "занятие": "l1",
                "студент": {"sid": sid, "подпись": sig(sid) if sid else "",
                            "fio": fio_field or fio, "группа": group,
                            "бригада": brigade},
                "токен": token,
                "когда": "2026-11-05T12:00:00",
                "примечание": "выполнено дома",
                "ответы": answers or {"answer": "Решение из дома",
                                      "period": "600", "mode": "норма"},
                "файлы": {"sketch": [{"имя": "схема.robxsim",
                                      "b64": B64(b"ROBXSIM-OK")}]},
            }, ensure_ascii=False).encode("utf-8")

        w1 = make_work("s1", "Иванов И.И.", token=token1)

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

        # ── защита от списывания: токен выдачи ───────────────────────
        # подписанный файл без токена
        r, page = post_multipart(conn, "/offline/upload",
                                 [("work", "нетокен.json",
                                   make_work("s1", "Иванов И.И."))],
                                 cookie=st1_ck)
        page = page.decode("utf-8", "replace")
        check("нет токена — блок", "в файле нет токена выдачи" in page,
              page[:300])
        # подписанный файл с чужим токеном
        r, page = post_multipart(conn, "/offline/upload",
                                 [("work", "чужтокен.json",
                                   make_work("s1", "Иванов И.И.",
                                             token="f" * 24))],
                                 cookie=st1_ck)
        page = page.decode("utf-8", "replace")
        check("чужой токен — блок", "токен выдачи не совпадает" in page,
              page[:300])
        # анонимный файл (без подписи) от студента
        r, page = post_multipart(conn, "/offline/upload",
                                 [("work", "аноним.json",
                                   make_work("", "Иванов И.И."))],
                                 cookie=st1_ck)
        page = page.decode("utf-8", "replace")
        check("анонимный файл студенту запрещён",
              "сдайте работу в нём" in page, page[:300])

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

        # ── повторная выдача: старый токен стирается ─────────────────
        r, zdata = post(conn, "/staff/offline/issue",
                        {"task": ["t1"], "student": ["s1"]},
                        cookie=staff_ck)
        zf = zipfile.ZipFile(io.BytesIO(zdata))
        blank2 = zf.read([n for n in zf.namelist()
                          if n.endswith(".html")][0]
                         ).decode("utf-8", "replace")
        m2 = re.search(r'"token": "([0-9a-f]+)"', blank2)
        token2 = m2.group(1) if m2 else ""
        check("токен перевыпущен", len(token2) == 24 and token2 != token1,
              token2)
        r, page = post_multipart(conn, "/offline/upload",
                                 [("work", "старый.json",
                                   make_work("s1", "Иванов И.И.",
                                             token=token1))],
                                 cookie=st1_ck)
        page = page.decode("utf-8", "replace")
        check("старый токен отклонён", "не совпадает" in page, page[:300])
        r, page = post_multipart(conn, "/offline/upload",
                                 [("work", "новый.json",
                                   make_work("s1", "Иванов И.И.",
                                             token=token2))],
                                 cookie=st1_ck)
        page = page.decode("utf-8", "replace")
        check("новый токен принят", "1 из 1 принято" in page, page[:300])

        # ── детект сходства работ ────────────────────────────────────
        LONG = ("Контроллер опрашивает считыватель каждые пятьдесят "
                "миллисекунд и при чтении карты сверяет хеш пина с записью "
                "в энергонезависимой памяти, после чего открывает замок "
                "и пишет событие в журнал.")
        ans_long = {"answer": LONG, "period": "600", "mode": "норма"}
        r, page = post_multipart(conn, "/offline/upload",
                                 [("work", "иванов_длинная.json",
                                   make_work("s1", "Иванов И.И.",
                                             token=token2,
                                             answers=ans_long))],
                                 cookie=st1_ck)
        page = page.decode("utf-8", "replace")
        check("длинная работа s1 принята", "1 из 1 принято" in page,
              page[:300])
        # ту же работу сдаёт s2 (анонимный файл, импорт преподавателем)
        w_same = make_work("", "Петров П.П.", "П-21", answers=ans_long)
        r, page = post_multipart(conn, "/staff/offline/import",
                                 [("work", "петров_копия.json", w_same)],
                                 cookie=staff_ck)
        page = page.decode("utf-8", "replace")
        check("копия s2 принята с пометкой",
              "похоже на работу" in page and "Иванов" in page, page[:400])
        with open(os.path.join(STORE, "реестр.json"), encoding="utf-8") as f:
            db = json.load(f)
        sub2 = db["сдачи"].get("t1__s2")
        check("сдача s2 в реестре", bool(sub2))
        last = sub2["versions"][-1] if sub2 else {}
        sim = last.get("похожесть") or []
        check("похожесть записана", bool(sim) and
              sim[0].get("fio") == "Иванов И.И." and
              sim[0].get("процент", 0) >= 60, str(sim)[:200])

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

        # ── преподаватель: несовпадение токена — предупреждение ──────
        r, page = post_multipart(conn, "/staff/offline/import",
                                 [("work", "с1_чужтокен.json",
                                   make_work("s1", "Иванов И.И.",
                                             token="a" * 24))],
                                 cookie=staff_ck)
        page = page.decode("utf-8", "replace")
        check("импорт с чужим токеном: предупреждение",
              "токен выдачи не совпадает с выданным" in page and "⚠" in page,
              page[:400])
        with open(os.path.join(STORE, "реестр.json"), encoding="utf-8") as f:
            db = json.load(f)
        subs1 = db["сдачи"]["t1__s1"]
        check("работа s1 всё же зачтена", len(subs1["versions"]) >= 5,
              str(len(subs1["versions"])))
        check("токен отмечен в версии",
              (subs1["versions"][-1].get("офлайн") or {}).get("токен")
              == "токен выдачи не совпадает с выданным")

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

        # ── выдача нескольким студентам: архивы «ФИО.zip» ────────────
        r, zdata = post(conn, "/staff/offline/issue",
                        {"task": ["t1"], "student": ["s2", "s3"]},
                        cookie=staff_ck)
        check("пачка бланков: zip", r.status == 200 and zdata[:2] == b"PK")
        zf = zipfile.ZipFile(io.BytesIO(zdata))
        names = zf.namelist()
        check("пачка бланков: архивы по ФИО",
              sorted(names) == sorted(["Петров П.П..zip",
                                       "Сидоров С.С..zip"]), str(names))
        inner = zipfile.ZipFile(io.BytesIO(zf.read(names[0])))
        inner_html = inner.read([n for n in inner.namelist()
                                 if n.endswith(".html")][0]
                                ).decode("utf-8", "replace")
        check("внутренний бланк: ФИО и токен",
              ("Петров П.П." in inner_html or "Сидоров С.С." in inner_html)
              and re.search(r'"token": "([0-9a-f]{24})"', inner_html),
              inner_html[:200])

        # страница студента и панель преподавателя открываются
        conn.request("GET", "/offline", headers={"Cookie": st1_ck})
        r = conn.getresponse()
        check("страница /offline", r.status == 200 and "Офлайн-сдача"
              in r.read().decode("utf-8", "replace"))
        conn.request("GET", "/staff/offline", headers={"Cookie": staff_ck})
        r = conn.getresponse()
        page = r.read().decode("utf-8", "replace")
        check("панель /staff/offline", r.status == 200 and
              "Импорт работ" in page and "Выдача бланков" in page,
              page[:200])
        check("панель: разделы защиты", "Возможное списывание" in page
              and "Токены выдачи" in page and "Петров П.П." in page,
              page[:200])
        check("панель: работы офлайн", "Работы офлайн-сдачи" in page
              and "посмотреть работу" in page, page[:200])
        check("панель: селектор курса", 'id="wc-course"' in page and
              '<option value="c1">' in page and "все курсы" in page,
              page[:200])
        check("панель: фильтр — строки и студенты с курсом",
              '<tr data-wcf="c1">' in page and
              'data-wcf="c1" data-fio="Иванов И.И." data-grp="П-21">'
              '<input type="checkbox" name="student" value="s1"' in page,
              page[:300])
        check("панель: группы заданий по курсу",
              '<div data-wcf="c1">' in page, page[:300])
        check("панель: поиск по ФИО и фильтр группы",
              'id="wc-sfio"' in page and 'id="wc-sgrp"' in page and
              'id="wc-scount"' in page and
              '<option value="П-21">' in page and
              '<option value="П-22">' in page, page[:300])
        check("панель: метки ФИО/группа на студентах",
              'data-fio="Сидоров С.С." data-grp="П-22"' in page and
              'data-fio="Петров П.П." data-grp="П-21"' in page, page[:300])
        # JS всех инлайн-скриптов страницы синтаксически корректен
        # (регрессия: сломанный wcTog ломал «все» в «Выдаче бланков»)
        _js = "\n;\n".join(
            m.group(1) for m in
            re.finditer(r"<script>(.*?)</script>", page, re.S))
        _pjs = os.path.join(STORE, "_panel_scripts.js")
        with open(_pjs, "w", encoding="utf-8") as f:
            f.write(_js)
        _rn = subprocess.run(["node", "--check", _pjs], capture_output=True)
        check("панель: JS синтаксис (node --check)", _rn.returncode == 0,
              _rn.stderr.decode("utf-8", "replace")[:300])
        os.remove(_pjs)

        # ── просмотр работы студента преподавателем ──────────────────
        conn.request("GET", "/staff/sub/t1__s1", headers={"Cookie": staff_ck})
        r = conn.getresponse()
        vpage = r.read().decode("utf-8", "replace")
        check("просмотр работы: страница", r.status == 200 and
              "Иванов И.И." in vpage, str(r.status))
        check("просмотр работы: ответы и файлы",
              "Решение" in vpage and "схема.robxsim" in vpage, vpage[:200])

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
