# -*- coding: utf-8 -*-
"""Обёртка для _panelfilter: сид (4 студента, 2 курса) + сервер на 8096."""
import json
import os
import shutil
import socket
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(ROOT, "tests", "_tmp_panelfilter_store")
PORT = 8096


def wait_port(port, tmo=15):
    end = time.time() + tmo
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), 1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def main():
    if os.path.isdir(STORE):
        shutil.rmtree(STORE)
    os.makedirs(STORE)
    reg = {
        "версия": 3,
        "курсы": [
            {"id": "c1", "title": "Курс 1 · ОПС",
             "студенты": ["s1", "s2", "s3", "s4"], "группы": []},
            {"id": "c2", "title": "Курс 2 · СКУД",
             "студенты": ["s3"], "группы": []},
        ],
        "занятия": [{"id": "l1", "course": "c1", "title": "Занятие 1",
                     "материалы": []}],
        "задания": [{
            "id": "t1", "lesson": "l1", "title": "Тестовое задание",
            "описание": "## Ситуация\nСделайте что-нибудь.",
            "форма": [{"ключ": "answer", "тип": "textarea",
                       "вопрос": "Решение", "обязательно": True,
                       "строк": 3}],
            "настройки": {},
            "выдано": []}],
        "студенты": [
            {"id": "s1", "fio": "Иванов И.И.", "group": "П-21",
             "бригада": ""},
            {"id": "s2", "fio": "Иваницкий П.П.", "group": "П-21",
             "бригада": ""},
            {"id": "s3", "fio": "Сидоров С.С.", "group": "П-22",
             "бригада": ""},
            {"id": "s4", "fio": "Петров П.П.", "group": "П-22",
             "бригада": ""},
        ],
        "сдачи": {},
    }
    with open(os.path.join(STORE, "реестр.json"), "w",
              encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=1)
    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", "server.py", "--port", str(PORT),
         "--store", STORE, "--no-pass"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    try:
        assert wait_port(PORT), "сервер не поднялся"
        r = subprocess.run([sys.executable, "-X", "utf8",
                            os.path.join(ROOT, "tests", "_panelfilter.py")],
                           cwd=ROOT, env=dict(
                               os.environ, BASE="http://localhost:%d" % PORT))
        return r.returncode
    finally:
        proc.terminate()
        proc.wait(timeout=5)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
