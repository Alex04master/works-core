# -*- coding: utf-8 -*-
"""E2E импорта сценариев с РЕАЛЬНЫМ комплектом «Больница_день_ОПС»:
scnfile (percent-encoded!), импорт, реестр, копия раздатки без эталонов,
материалы и страница задания у студента."""
import glob
import io
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

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

    # 1) /scnfile с percent-encoded кириллическим именем комплекта
    kit = "Больница_день_ОПС"
    enc = urllib.parse.quote(kit)
    head = curl("-i", "-b", "_e2e_staff.txt",
                "http://localhost:8093/scnfile/%s/event.js" % enc)
    chk("scnfile percent-encoded cyrillic -> 200",
        head.startswith("HTTP/1.0 200") and "window.EVENT" in head)
    chk("scnfile content-type js", "javascript" in head.split("\r\n\r\n")[0].lower()
        or "javascript" in head.split("\n\n")[0].lower())

    # 2) импорт реальными данными (payload готовит node — как браузер)
    r = subprocess.run(["node", "_scn_export.js"], capture_output=True)
    print("node:", r.stdout.decode("utf-8", "replace").strip(),
          r.stderr.decode("utf-8", "replace")[:200])
    resp = curl("-b", "_e2e_staff.txt", "-H", "Content-Type: application/json",
                "-d", "@_scn_real.json",
                "http://localhost:8093/staff/scenarios/import")
    chk("import returns ok", resp.strip() == "ok")
    # повторный импорт -> exists
    resp2 = curl("-b", "_e2e_staff.txt", "-H", "Content-Type: application/json",
                 "-d", "@_scn_real.json",
                 "http://localhost:8093/staff/scenarios/import")
    chk("re-import -> exists", resp2.strip() == "exists")

    # 3) реестр: занятие + 6 заданий
    files = [f for f in glob.glob("_scntest/*.json")
             if not os.path.basename(f).startswith("_")]
    db = json.loads(io.open(files[0], encoding="utf-8").read())
    les = [l for l in db["занятия"] if "больнице" in l.get("title", "")]
    chk("lesson created with clean title",
        len(les) == 1 and les[0]["title"] == "Медицинский день ОПС в больнице № 3")
    lid = les[0]["id"]
    tasks = sorted([t for t in db["задания"] if t.get("lesson") == lid],
                   key=lambda t: t["title"])
    chk("6 scenario tasks", len(tasks) == 6)
    t0 = tasks[0]
    chk("task title has card id", t0["title"].startswith("СЦ-01"))
    form = {f["ключ"]: f["тип"] for f in t0["форма"]}
    chk("form: plan file + calc textarea",
        form.get("plan") == "file" and form.get("calc") == "textarea")
    d = t0.get("описание", "")
    chk("description: ситуация/задания/критерии/ловушки",
        all(x in d for x in ("Ситуация", "Задания бригады", "Критерии", "Ловушки")))
    chk("no etalon leak in task", "эталон" not in d and "Итого: 7 ИП" not in d)
    chk("criteria points present", "балл." in d)

    # 4) копия комплекта: раздатка без эталонов
    sub = os.path.join("_scntest", "раздатка", "c1", lid)
    fl = os.listdir(sub) if os.path.isdir(sub) else []
    chk("handout copied (02/05/06 present)",
        all(any(f.startswith(p) for f in fl) for p in ("01_", "02_", "05_", "06_")))
    chk("teacher plan excluded",
        not any(f.startswith("03_") for f in fl)
        and not any(f.startswith("ИНСТРУКЦИЯ") for f in fl))
    plans = io.open(os.path.join(sub, "plans.js"), encoding="utf-8").read()
    chk("plans.js stripped (dev/notes empty)",
        plans.count("dev: []") == 6 and plans.count("notes: []") == 6
        and "7 ИП" not in plans)
    mats = les[0].get("материалы") or []
    chk("lesson materials = html pages",
        len(mats) >= 4 and all(m["тип"] == "файл" for m in mats))

    # 5) студент: материалы и страница задания
    curl("-c", "_e2e_s1.txt", "-d", "student=s1", "-d", "next=/",
         "http://localhost:8093/_login")
    page = curl("-b", "_e2e_s1.txt", "http://localhost:8093/course/c1")
    chk("scenario lesson on course page", "больнице" in page)
    mat_url = "/materials/c1/%s/%s" % (lid, urllib.parse.quote(mats[0]["имя"]))
    mat = curl("-b", "_e2e_s1.txt", "http://localhost:8093" + mat_url)
    chk("material page opens (html)", mat.lstrip().startswith("<!doctype")
        or "<html" in mat[:200].lower())
    tid = t0["id"]
    tp = curl("-b", "_e2e_s1.txt", "http://localhost:8093/task/%s" % tid)
    chk("scenario task page renders", "Задания бригады" in tp
        and 'name="plan"' in tp)
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()

print("E2E OK" if not fails else "E2E FAILED: %d" % len(fails))
sys.exit(0 if not fails else 1)
