# -*- coding: utf-8 -*-
"""Тест связки: сервер -> наблюдатель; сервер стоп -> наблюдатель стоп."""
import os
import shutil
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
PORT = "8095"
STORE = "_cwtest"
ok = True


def need(c, m, ctx=""):
    global ok
    print(("OK   " if c else "FAIL ") + m + ("" if c else "  | " + str(ctx)[:200]))
    ok = ok and bool(c)


def ci_watchers():
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | "
         "Where-Object { $_.CommandLine -match 'ci\\.py watch' } | "
         "Select-Object -ExpandProperty ProcessId"],
        capture_output=True, text=True).stdout
    return [x.strip() for x in out.splitlines() if x.strip().isdigit()]


if os.path.isdir(STORE):
    shutil.rmtree(STORE, ignore_errors=True)
logf = open("_ci_watch.log", "ab")
proc = subprocess.Popen(
    [sys.executable, "-X", "utf8", "server.py", "--port", PORT,
     "--store", STORE, "--demo", "--no-pass", "--ci-watch"],
    stdout=logf, stderr=subprocess.STDOUT)
time.sleep(8)
try:
    code = urllib.request.urlopen(
        "http://localhost:%s/_login" % PORT, timeout=5).getcode()
    need(code == 200, "сервер поднялся", code)
    ids = ci_watchers()
    need(len(ids) == 1, "наблюдатель запущен вместе с сервером", ids)
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
time.sleep(3)
# сервер умер; наблюдатель должен самоустраниться (до ~2 мин с учётом
# циклов и закрытия стенда)
deadline = time.time() + 120
ids = ci_watchers()
while ids and time.time() < deadline:
    time.sleep(3)
    ids = ci_watchers()
need(not ids, "наблюдатель завершился вместе с сервером", ids)
logf.close()
print("COUPLE OK" if ok else "COUPLE FAIL")
sys.exit(0 if ok else 1)
