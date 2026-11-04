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
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

    r = subprocess.run(["node", "tests/_scn_export.js"], capture_output=True)
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
    crits = t0.get("настройки", {}).get("критерии") or []
    chk("criteria imported from card",
        isinstance(crits, list) and len(crits) >= 1)
    form = {f["ключ"]: f["тип"] for f in t0["форма"]}
    chk("form: plan_data + loops + firmware + calc (no file)",
        form.get("plan_data") == "hidden" and form.get("calc") == "textarea"
        and form.get("loops") == "shlei" and form.get("firmware") == "firmware"
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
    chk("lesson list hides waiting task",
        ('href="/task/%s"' % tid) not in lp)
    tp0 = curl("-b", "_e2e_s1.txt", "http://localhost:8093/task/%s" % tid)
    chk("waiting: scenario task hidden until issued",
        "task-form" not in tp0 and "не выдано" in tp0)
    mjs = curl("http://localhost:8093/materials/c1/%s/event.js" % lid)
    pls = curl("http://localhost:8093/materials/c1/%s/plans.js" % lid)
    chk("widget data served (event.js/plans.js)",
        "window.EVENT" in mjs[:400] and "window.PLANS" in pls[:400])
    curl("-b", "_e2e_staff.txt", "-d", "task=%s" % tid, "-d", "all=on",
         "http://localhost:8093/staff/task_issue")
    tp = curl("-b", "_e2e_s1.txt", "http://localhost:8093/task/%s" % tid)
    chk("task: no links block (content inline)", 'target="_blank"' not in tp)
    chk("task: plan widget iframe", 'src="/plan/%s"' % tid in tp)
    chk("task: submit copies plan draft", "wcplan_" in tp)
    chk("task: shlei table widget", "shlei-tbl" in tp and 'name="loops"' in tp)
    chk("task: single drag&drop file field",
        tp.count('type="file"') == 1 and "dnd-zone" in tp and "dnd-list" in tp)
    pp = curl("-b", "_e2e_s1.txt", "http://localhost:8093/plan/%s" % tid)
    chk("plan widget page", "wcplan_" in pp and "СЦ-01" in pp
        and "legend" in pp and "RO=false" in pp)
    chk("plan legend with rules", "Условные обозначения" in pp)

    # сдача с планом и ведомостью шлейфов
    curl("-b", "_e2e_s1.txt",
         "-F", "task=%s" % tid, "-F", "calc=расчёт готов",
         "-F", 'plan_data=[{"t":"smoke","x":3,"y":2.5},{"t":"ipr","x":0.8,"y":6.2}]',
         "-F", 'loops=<tests/_loops.json',
         "-F", "firmware=@tests/_fw1.bin",
         "-F", "firmware=@tests/_fw2.bin",
         "http://localhost:8093/api/submit")
    files = [f for f in glob.glob("_scntest/*.json")
             if not os.path.basename(f).startswith("_")]
    db = json.loads(io.open(files[0], encoding="utf-8").read())
    ver = db["сдачи"]["%s__s1" % tid]["versions"][-1]
    chk("plan_data stored in version",
        json.loads(ver["answers"]["plan_data"])[0]["t"] == "smoke")
    loops = json.loads(ver["answers"]["loops"])
    chk("loops stored in version",
        isinstance(loops, list) and loops[0].get("cnt") == "3")
    fl = ver.get("files", {})
    chk("firmware files saved (2)",
        "firmware" in fl and "firmware-2" in fl
        and fl["firmware"]["имя"].endswith(".bin"))
    lmx = curl("-b", "_e2e_staff.txt",
               "http://localhost:8093/staff/lesson/%s" % lid)
    chk("matrix: solo row shows submission",
        "mx-tbl" in lmx and "mx-sent" in lmx)
    ms0 = curl("-b", "_e2e_s1.txt", "http://localhost:8093/mysub/%s" % tid)
    chk("my sub page renders", "sub-status" in ms0)
    tpf = curl("-b", "_e2e_s1.txt", "http://localhost:8093/task/%s" % tid)
    chk("form prefilled with previous answers",
        "расчёт готов" in tpf and "&quot;smoke&quot;" in tpf)
    chk("files carry note shown", "carry-note" in tpf)

    # преподаватель: сводка + просмотр плана
    sp = curl("-b", "_e2e_staff.txt",
              "http://localhost:8093/staff/sub/%s__s1" % tid)
    chk("sub page: plan summary + view link",
        "Смотреть план" in sp and "/plan/" in sp)
    chk("sub page: shlei table view", "shlei-view" in sp)
    chk("sub page: firmware files listed", "firmware-2" in sp)
    chk("sub page: criteria checklist", 'name="crit"' in sp)
    pv = curl("-b", "_e2e_staff.txt",
              "http://localhost:8093/plan/%s?sub=%s__s1&v=1" % (tid, tid))
    chk("teacher plan view read-only",
        "RO=true" in pv and '"t": "smoke"' in pv.replace(", ", ", "))
    rr = curl("-b", "_e2e_staff.txt", "-d", "course=c1",
              "-d", "kit=Больница_день_ОПС",
              "http://localhost:8093/staff/scenarios/repair")
    chk("repair runs", rr.startswith("ok:"))
    spg = curl("-b", "_e2e_staff.txt", "http://localhost:8093/staff/scenarios")
    chk("scenarios page: repair-all button", "repair_all" in spg)
    ra = curl("-b", "_e2e_staff.txt", "-X", "POST",
              "http://localhost:8093/staff/scenarios/repair_all")
    chk("repair-all runs", ra.startswith("ok:"))
    files = [f for f in glob.glob("_scntest/*.json")
             if not os.path.basename(f).startswith("_")]
    db = json.loads(io.open(files[0], encoding="utf-8").read())
    les2 = [l for l in db["занятия"] if "больнице" in l.get("title", "")][0]
    mats2 = [m["имя"] for m in (les2.get("материалы") or [])]
    chk("repair: materials still 02/05/06", len(mats2) == 3)
    t2r = [t for t in db["задания"] if t.get("lesson") == les2["id"]
           and t["id"] == tid][0]
    chk("repair: plan binding intact",
        t2r.get("настройки", {}).get("план") == "СЦ-01")
    chk("repair: loops field added",
        any(f.get("ключ") == "loops" for f in t2r["форма"]))

    # вердикт с чек-листом + живые уведомления
    curl("-b", "_e2e_staff.txt", "-d", "key=%s__s1" % tid,
         "-d", "verdict=%s" % urllib.parse.quote("Принято"),
         "-d", "score=4.5", "-d", "crit=0", "-d", "crit=1",
         "http://localhost:8093/staff/verdict")
    files = [f for f in glob.glob("_scntest/*.json")
             if not os.path.basename(f).startswith("_")]
    db = json.loads(io.open(files[0], encoding="utf-8").read())
    sub2 = db["сдачи"]["%s__s1" % tid]
    ver3 = sub2["versions"][-1]
    chk("verdict checklist saved",
        ver3.get("чек") == [0, 1] and ver3.get("verdict") == "Принято"
        and bool(ver3.get("время_вердикта")))
    chk("submission status accepted", sub2.get("status") == "принято")
    tpv = curl("-b", "_e2e_s1.txt", "http://localhost:8093/task/%s" % tid)
    chk("student sees criteria result", "crit-list" in tpv)
    chk("task page links to my sub", "/mysub/" in tpv)
    ms2 = curl("-b", "_e2e_s1.txt", "http://localhost:8093/mysub/%s" % tid)
    chk("my sub page: criteria shown", "crit-list" in ms2)
    mf = curl("-i", "-b", "_e2e_s1.txt",
              "http://localhost:8093/mysubfile/%s__s1/v1/firmware" % tid)
    chk("my sub file download", mf.startswith("HTTP/1.0 200"))
    fdj = json.loads(curl("-b", "_e2e_staff.txt",
                          "http://localhost:8093/board/feed"))
    chk("board feed events",
        isinstance(fdj, list) and len(fdj) >= 1
        and any("Проверено" in (it.get("what") or "") for it in fdj))
    bdp = curl("-b", "_e2e_staff.txt", "http://localhost:8093/board")
    chk("board toast widget", "toastbox" in bdp and "/board/feed" in bdp)

    # пакет курса: экспорт и импорт
    subprocess.run(["curl.exe", "-s", "-o", "_exp_course.zip", "-b",
                    "_e2e_staff.txt",
                    "http://localhost:8093/staff/course_export/c1"],
                   capture_output=True)
    zfp = zipfile.ZipFile("_exp_course.zip")
    chk("package: manifest + tasks + handout",
        json.loads(zfp.read("пакет.json").decode("utf-8"))["формат"]
        == "works-core-курс"
        and len(json.loads(zfp.read("задания.json").decode("utf-8"))) >= 6
        and any(n.startswith("раздатка/") for n in zfp.namelist()))
    zfp.close()
    subprocess.run(["curl.exe", "-s", "-i", "-b", "_e2e_staff.txt",
                    "-F", "pkgfile=@_exp_course.zip", "-F", "results=on",
                    "http://localhost:8093/staff/course_import"],
                   capture_output=True)
    files = [f for f in glob.glob("_scntest/*.json")
             if not os.path.basename(f).startswith("_")]
    db = json.loads(io.open(files[0], encoding="utf-8").read())
    c2 = [c for c in db["курсы"] if c["id"] != "c1"][-1]
    lids2 = [l for l in db["занятия"] if l.get("course") == c2["id"]]
    lscn = [l for l in lids2 if "больнице" in l.get("title", "")]
    chk("imported course: lesson carried", len(lscn) == 1)
    lid2 = lscn[0]["id"]
    tks2 = [t for t in db["задания"] if t.get("lesson") == lid2]
    chk("imported course: 6 tasks", len(tks2) == 6)
    chk("imported: plan binding kept",
        any(t.get("настройки", {}).get("план") == "СЦ-01" for t in tks2))
    tset2 = {t["id"] for t in tks2}
    sub2 = [s for s in db["сдачи"].values() if s.get("task") in tset2]
    chk("imported: submissions remapped",
        len(sub2) >= 1 and sub2[0]["key"] == "%s__s1" % sub2[0]["task"])
    mdir = os.path.join("_scntest", "раздатка", c2["id"], lid2)
    chk("imported: handout copied",
        os.path.isfile(os.path.join(mdir, "plans.js")))
    pls2 = curl("http://localhost:8093/materials/%s/%s/plans.js"
                % (c2["id"], lid2))
    chk("imported: plans.js served", "window.PLANS" in pls2[:400])
    vdir = os.path.join("_scntest", "сдачи", sub2[0]["key"], "v1")
    chk("imported: submission files copied",
        any(f.startswith("firmware") for f in os.listdir(vdir)))

    lf = glob.glob("_scntest/лог/*.jsonl")
    chk("audit log written", bool(lf))
    txt = "".join(io.open(f, encoding="utf-8").read() for f in lf)
    chk("audit has import entry", "импортирован сценарий" in txt)

    # массовая выдача + скрытие занятий
    lmass = curl("-b", "_e2e_staff.txt",
                 "http://localhost:8093/staff/lesson/%s" % lid)
    chk("mass issue matrix on lesson page", "issue_mass" in lmass)
    curl("-b", "_e2e_staff.txt", "-d", "lesson=%s" % lid,
         "-d", "iss=%s|Iskra" % tid, "http://localhost:8093/staff/issue_mass")
    e1 = curl("-b", "_e2e_s1.txt", "http://localhost:8093/task/%s" % tid)
    chk("mass: unassigned student blocked", "task-form" not in e1)
    cpage = curl("-b", "_e2e_s1.txt", "http://localhost:8093/course/c1")
    chk("locked lesson hidden on course page", "больнице" not in cpage)
    lp3 = curl("-b", "_e2e_s1.txt", "http://localhost:8093/lesson/%s" % lid)
    chk("lesson page gate for unassigned", "не выданы" in lp3)
    curl("-b", "_e2e_staff.txt", "-d", "lesson=%s" % lid,
         "-d", "alltask=%s" % tid, "http://localhost:8093/staff/issue_mass")
    e2 = curl("-b", "_e2e_s1.txt", "http://localhost:8093/task/%s" % tid)
    chk("mass issue-all restores", "task-form" in e2)

    # выдача бригадам: сценарий видят только назначенные бригады
    curl("-b", "_e2e_staff.txt", "-d", "task=%s" % tid,
         "-d", "brigade=Iskra", "http://localhost:8093/staff/task_issue")
    tp2 = curl("-b", "_e2e_s1.txt", "http://localhost:8093/task/%s" % tid)
    chk("issued task hidden from brigadeless student", "task-form" not in tp2)
    pp2 = curl("-b", "_e2e_s1.txt", "http://localhost:8093/plan/%s" % tid)
    chk("plan hidden too", "wcplan_" not in pp2)
    lp2 = curl("-b", "_e2e_s1.txt", "http://localhost:8093/lesson/%s" % lid)
    chk("lesson list hides issued task",
        ('href="/task/%s"' % tid) not in lp2)
    r403 = subprocess.run(["curl.exe", "-s", "-i", "-b", "_e2e_s1.txt",
                           "-F", "task=%s" % tid, "-F", "calc=x",
                           "http://localhost:8093/api/submit"], capture_output=True)
    chk("submit 403 for unissued", " 403 " in r403.stdout.decode("utf-8", "replace"))
    curl("-b", "_e2e_staff.txt", "-d", "task=%s" % tid, "-d", "all=on",
         "http://localhost:8093/staff/task_issue")
    tp3 = curl("-b", "_e2e_s1.txt", "http://localhost:8093/task/%s" % tid)
    chk("issue-all restores visibility", "task-form" in tp3)
    rd = subprocess.run(["curl.exe", "-s", "-i", "-b", "_e2e_s1.txt",
                         "-F", "task=%s" % tid, "-F", "calc=x",
                         "http://localhost:8093/api/submit"],
                        capture_output=True)
    chk("submit redirects to my sub",
        "Location: /mysub/" in rd.stdout.decode("utf-8", "replace"))

    # снятие выдачи
    curl("-b", "_e2e_staff.txt",
         "http://localhost:8093/staff/task_off?task=%s&back=/staff/task/%s"
         % (tid, tid))
    tp4 = curl("-b", "_e2e_s1.txt", "http://localhost:8093/task/%s" % tid)
    chk("revoke hides task again", "task-form" not in tp4)
    curl("-b", "_e2e_staff.txt", "-d", "task=%s" % tid, "-d", "all=on",
         "http://localhost:8093/staff/task_issue")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()

print("E2E OK" if not fails else "E2E FAILED: %d" % len(fails))
sys.exit(0 if not fails else 1)
