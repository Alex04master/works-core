# -*- coding: utf-8 -*-
"""E2E: сценарии — материалы 02/05/06, форма план+расчёты, виджет плана,
просмотр преподавателем, скрытие «Материалов». Реальный комплект Больница."""
import glob
import io
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.abspath(__file__)))

shutil.rmtree("_scntest", ignore_errors=True)
proc = subprocess.Popen(
    [sys.executable, "-X", "utf8", "server.py", "--port", "8093",
     "--store", "_scntest", "--demo", "--no-pass"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(6)


def curl(*args):
    r = subprocess.run(["curl.exe", "-s", *args], capture_output=True)
    return r.stdout.decode("utf-8", "replace")


fails = []


def chk(name, cond):
    print(("OK   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


try:
    curl("-c", "_e2e_staff.txt", "-d", "pass=x", "http://localhost:8093/_staff_login")
    kit = "Больница_день_ОПС"
    enc = urllib.parse.quote(kit)
    head = curl("-i", "-b", "_e2e_staff.txt",
                "http://localhost:8093/scnfile/%s/event.js" % enc)
    chk("scnfile percent-encoded -> 200", head.startswith("HTTP/1.0 200"))

    r = subprocess.run(["node", "_scn_export.js"], capture_output=True)
    resp = curl("-b", "_e2e_staff.txt", "-H", "Content-Type: application/json",
                "-d", "@_scn_real.json",
                "http://localhost:8093/staff/scenarios/import")
    chk("import ok", resp.strip() == "ok")

    files = [f for f in glob.glob("_scntest/*.json")
             if not os.path.basename(f).startswith("_")]
    db = json.loads(io.open(files[0], encoding="utf-8").read())
    les = [l for l in db["занятия"] if "больнице" in l.get("title", "")]
    chk("lesson title clean", len(les) == 1
        and les[0]["title"] == "Медицинский день ОПС в больнице № 3")
    lid = les[0]["id"]
    tasks = sorted([t for t in db["задания"] if t.get("lesson") == lid],
                   key=lambda t: t["title"])
    chk("6 tasks", len(tasks) == 6)
    t0 = tasks[0]
    form = {f["ключ"]: f["тип"] for f in t0["форма"]}
    chk("form: plan_data hidden + calc textarea (no file)",
        form.get("plan_data") == "hidden" and form.get("calc") == "textarea"
        and "plan" not in form and "plan_photo" not in form)
    chk("task settings plan id", t0.get("настройки", {}).get("план") == "СЦ-01")
    mats = les[0].get("материалы") or []
    names = sorted(m["имя"] for m in mats)
    chk("materials only 02/05/06", len(mats) == 3
        and names[0].startswith("02_") and names[1].startswith("05_")
        and names[2].startswith("06_"))

    sub_dir = os.path.join("_scntest", "раздатка", "c1", lid)
    fl = os.listdir(sub_dir)
    chk("handout: teacher plan excluded",
        not any(f.startswith("03_") for f in fl))
    plans = io.open(os.path.join(sub_dir, "plans.js"), encoding="utf-8").read()
    chk("plans.js stripped", plans.count("dev: []") == 6
        and "7 ИП" not in plans)

    # студент
    curl("-c", "_e2e_s1.txt", "-d", "student=s1", "-d", "next=/",
         "http://localhost:8093/_login")
    cp = curl("-b", "_e2e_s1.txt", "http://localhost:8093/course/c1")
    chk("course page: no Materials block", "<h2>Материалы</h2>" not in cp)
    lp = curl("-b", "_e2e_s1.txt", "http://localhost:8093/lesson/%s" % lid)
    chk("lesson page: no Materials block", "<h2>Материалы</h2>" not in lp)
    tid = t0["id"]
    tp = curl("-b", "_e2e_s1.txt", "http://localhost:8093/task/%s" % tid)
    chk("task: scenario handout links", "target=\"_blank\"" in tp
        and "/materials/c1/%s/" % lid in tp)
    chk("task: plan widget iframe", 'src="/plan/%s"' % tid in tp)
    chk("task: submit copies plan draft", "wcplan_" in tp)
    pp = curl("-b", "_e2e_s1.txt", "http://localhost:8093/plan/%s" % tid)
    chk("plan widget page", "wcplan_" in pp and "СЦ-01" in pp
        and "legend" in pp and "RO=false" in pp)

    # сдача с планом
    curl("-b", "_e2e_s1.txt",
         "-F", "task=%s" % tid, "-F", "calc=расчёт готов",
         "-F", 'plan_data=[{"t":"smoke","x":3,"y":2.5},{"t":"ipr","x":0.8,"y":6.2}]',
         "http://localhost:8093/api/submit")
    files = [f for f in glob.glob("_scntest/*.json")
             if not os.path.basename(f).startswith("_")]
    db = json.loads(io.open(files[0], encoding="utf-8").read())
    ver = db["сдачи"]["%s__s1" % tid]["versions"][-1]
    chk("plan_data stored in version",
        json.loads(ver["answers"]["plan_data"])[0]["t"] == "smoke")

    # преподаватель: сводка + просмотр плана
    sp = curl("-b", "_e2e_staff.txt",
              "http://localhost:8093/staff/sub/%s__s1" % tid)
    chk("sub page: plan summary + view link",
        "Смотреть план" in sp and "/plan/" in sp)
    pv = curl("-b", "_e2e_staff.txt",
              "http://localhost:8093/plan/%s?sub=%s__s1&v=1" % (tid, tid))
    chk("teacher plan view read-only",
        "RO=true" in pv and '"t": "smoke"' in pv.replace(", ", ", "))
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()

print("E2E OK" if not fails else "E2E FAILED: %d" % len(fails))
sys.exit(0 if not fails else 1)
