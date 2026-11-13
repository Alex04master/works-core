# -*- coding: utf-8 -*-
"""Симулятор Arduino (velxio): встраивание в страницу задания.

Запуск: python -X utf8 tests/_chk_sim.py  (сервер _teststore на 8099).
Проверки: карточка в панели, привязка URL, резолв пути через базу,
абсолютный URL, iframe на студенческой странице, отвязка, аудит.
"""
import io
import json
import glob
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
    store = os.environ.get("STORE", "_teststore")
    files = [f for f in glob.glob(store + "/*.json")
             if not os.path.basename(f).startswith("_")]
    return json.loads(io.open(files[0], encoding="utf-8").read())


# логины (тест сам получает свежие куки — хранилище может быть пересоздано)
curl("-s", "-c", "_staff.txt", "-d", "pass=x", BASE + "/_staff_login")
curl("-s", "-c", "_ck.txt", "-d", "student=s1", "-d", "next=/", BASE + "/_login")

# 0) сброс состояния (тест можно перезапускать)
curl("-s", "-b", "_staff.txt", "-d", "task=t1", "-d", "url=",
     BASE + "/staff/sim_set")
# форма t1: файловое поле схемы — чтобы проверить, куда импортируется
FORM = [{"тип": "file", "ключ": "scheme", "вопрос": "Файл схемы",
         "обязательно": True}]
curl("-s", "-b", "_staff.txt",
     "--data-urlencode",
     "form_json=" + json.dumps(FORM, ensure_ascii=False),
     "-d", "title=", "-d", "description=", "-d", "deadline=",
     BASE + "/staff/edit_task/t1")

# 1) карточка «Симулятор» на странице задания в панели
sp = curl("-b", "_staff.txt", BASE + "/staff/task/t1")
need("/staff/sim_set" in sp, "панель: карточка «Симулятор» есть")
need("Симулятор" in sp and "staff-card" in sp,
     "панель: карточка оформлена")
need("Не привязан" in sp, "панель: пустое состояние")

# 2) на студенческой странице iframe пока нет
tp0 = curl("-b", "_ck.txt", BASE + "/task/t1")
need('src="http://localhost:5173' not in tp0,
     "студент: до привязки iframe нет")

# 3) привязка пути → резолвится через базу
h = curl("-i", "-b", "_staff.txt", "-d", "task=t1", "-d", "url=/editor",
         BASE + "/staff/sim_set")
need("Location: /staff/task/t1" in h, "привязка: редирект назад")
db = registry()
t1 = next(t for t in db["задания"] if t.get("id") == "t1")
need(t1.get("симулятор") == "/editor", "реестр: симулятор = /editor")

sp = curl("-b", "_staff.txt", BASE + "/staff/task/t1")
need('value="/editor"' in sp, "панель: значение показано")
tp = curl("-b", "_ck.txt", BASE + "/task/t1")
need('src="http://localhost:5173/editor"' in tp,
     "студент: iframe с базой из хоста + /editor")
need("Открыть симулятор" in tp, "студент: кнопка «Открыть симулятор»")
need("wc-sim-import" in tp, "студент: кнопка импорта схемы есть")
need("'velxio-export'" in tp,
     "студент: JS-мост импорта (postMessage)")
need('"scheme"' in tp,
     "студент: импорт знает поле файла отчёта (KEY)")
need("wc-sim-draft_" in tp and "DOMContentLoaded" in tp,
     "студент: схема хранится в черновике и восстанавливается")
need("if(!localStorage.getItem(K))" in tp and "/api/draft" in tp,
     "задание: черновик формы важнее серверного предзаполнения")

# 4) абсолютный URL — без изменений
curl("-s", "-b", "_staff.txt", "-d", "task=t1",
     "-d", "url=http://velxio.local:3080/editor", BASE + "/staff/sim_set")
db = registry()
t1 = next(t for t in db["задания"] if t.get("id") == "t1")
need(t1.get("симулятор") == "http://velxio.local:3080/editor",
     "абсолютный URL сохранён как есть")
tp = curl("-b", "_ck.txt", BASE + "/task/t1")
need('src="http://velxio.local:3080/editor"' in tp,
     "студент: iframe с абсолютным URL")

# 5) отвязка
h = curl("-i", "-b", "_staff.txt", "-d", "task=t1", "-d", "url=",
         BASE + "/staff/sim_set")
need("Location: /staff/task/t1" in h, "отвязка: редирект")
db = registry()
t1 = next(t for t in db["задания"] if t.get("id") == "t1")
need("симулятор" not in t1, "реестр: ключ снят")
tp = curl("-b", "_ck.txt", BASE + "/task/t1")
need('src="http://velxio.local' not in tp, "студент: iframe скрыт")
sp = curl("-b", "_staff.txt", BASE + "/staff/task/t1")
need("Не привязан" in sp, "панель: снова пустое состояние")

# 6) ошибка валидации видна на странице задания
ERR = urllib.parse.quote("Файл схемы симулятора (.robxsim): обязательное поле")
tp_err = curl("-b", "_ck.txt", BASE + "/task/t1?error=" + ERR)
need("обязательное поле" in tp_err and 'class="error"' in tp_err,
     "задание: ?error= показывается студенту", tp_err[:120])

# 7) аудит
lg = curl("-b", "_staff.txt", BASE + "/staff/log")
need("симулятор привязан" in lg and "симулятор отвязан" in lg,
     "аудит: привязка и отвязка записаны")

# 8) вернуть форму как была (пустой)
curl("-s", "-b", "_staff.txt", "-d", "title=", "-d", "description=",
     "-d", "form_json=", "-d", "deadline=",
     BASE + "/staff/edit_task/t1")

print("SIM OK" if ok else "SIM FAIL")
sys.exit(0 if ok else 1)
