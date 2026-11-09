# -*- coding: utf-8 -*-
"""CI works-core: проверки и горячий деплой правок на работающий сервер.

Зачем: правки нужно вносить, пока студенты работают. Правки папки
modules/* применяются к живому серверу БЕЗ перезапуска (POST /_reload -
маршруты и обработчики модуля подменяются на лету, студенты ничего не
замечают). Правки ядра (core/*, server.py) требуют одноразового
перезапуска - CI сам его НЕ делает, только сообщает (студенческие входы
при перезапуске не слетают: ключ сессий хранится в хранилище).

Команды:
    python ci.py check                 однократная проверка (компиляция +
                                       пробный старт сервера на :8097)
    python ci.py check --full          полный смоук (tests/_test2.ps1)
    python ci.py watch                 следить за файлами и деплоить
    python ci.py deploy module=sim     перезагрузить модуль вручную

Параметры watch/deploy:
    --url http://localhost:8090   адрес работающего СДО
    --interval 2                  период опроса файлов, сек
    --token XXX                   токен CI (иначе читается <store>/_ci.token)

Правила безопасности:
  * CI никогда не пишет в рабочее хранилище; проверки гоняются на
    одноразовом хранилище _ci_scratch;
  * CI никогда не убивает чужие процессы: перезапуск основного сервера -
    только вручную, после явного согласия.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(_HERE)

PY = sys.executable or "python"
SCRATCH_PORT = 8097
SCRATCH_STORE = os.path.join(_HERE, "_ci_scratch")
WATCH_DIRS = [os.path.join(_HERE, "core"), os.path.join(_HERE, "modules")]
WATCH_FILES = [os.path.join(_HERE, "server.py"), os.path.join(_HERE, "ci.py")]


def log(msg):
    line = time.strftime("[%H:%M:%S] ") + msg
    print(line, flush=True)
    try:
        with open(os.path.join(_HERE, "_ci.log"), "a",
                  encoding="utf-8") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + msg + "\n")
    except OSError:
        pass


# ── компиляция ───────────────────────────────────────────────────────
def py_sources():
    out = []
    for root in WATCH_DIRS + [os.path.join(_HERE, "tests")]:
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                if fn.endswith(".py"):
                    out.append(os.path.join(dirpath, fn))
    out.append(os.path.join(_HERE, "server.py"))
    return out


def compile_all(changed=None):
    """py_compile: все исходники (быстро) или только изменённые."""
    files = changed if changed else py_sources()
    bad = []
    for p in files:
        if not p.endswith(".py") or not os.path.isfile(p):
            continue
        r = subprocess.run([PY, "-X", "utf8", "-m", "py_compile", p],
                           capture_output=True)
        if r.returncode != 0:
            bad.append((p, r.stderr.decode("utf-8", "replace")[-400:]))
    return bad


# ── пробный старт (своё хранилище, свой порт) ────────────────────────
def _wait_port(port, timeout=20):
    import socket
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = socket.socket()
        s.settimeout(0.5)
        try:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        finally:
            s.close()
        time.sleep(0.3)
    return False


def _http(url, method="GET", data=None, headers=None):
    req = urllib.request.Request(url, method=method,
                                 data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.getcode(), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)


def boot_check():
    """Пробный старт сервера на одноразовом хранилище + пара запросов."""
    import shutil
    if os.path.isdir(SCRATCH_STORE):
        shutil.rmtree(SCRATCH_STORE, ignore_errors=True)
    args = [PY, "-X", "utf8", os.path.join(_HERE, "server.py"),
            "--port", str(SCRATCH_PORT), "--store", SCRATCH_STORE,
            "--no-pass", "--demo"]
    log("пробный старт: порт %d, хранилище %s" % (SCRATCH_PORT, SCRATCH_STORE))
    proc = subprocess.Popen(args, cwd=_HERE,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    ok = True
    try:
        if not _wait_port(SCRATCH_PORT):
            log("FAIL сервер не поднялся за 20 с")
            return False
        code, body = _http("http://localhost:%d/_login" % SCRATCH_PORT)
        if code != 200 or "form" not in body:
            log("FAIL /_login -> %s" % code)
            ok = False
        code, _ = _http("http://localhost:%d/_modules" % SCRATCH_PORT)
        if code != 200:
            log("FAIL /_modules -> %s" % code)
            ok = False
        code, body = _http("http://localhost:%d/" % SCRATCH_PORT)
        if code not in (200, 302):
            log("FAIL / -> %s" % code)
            ok = False
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
    if ok:
        log("пробный старт: OK")
    return ok


def check(full=False):
    bad = compile_all()
    if bad:
        for p, err in bad:
            log("FAIL компиляция: %s\n%s" % (os.path.relpath(p, _HERE), err))
        return False
    log("компиляция: OK (%d файлов)" % len(py_sources()))
    if full:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy",
                            "Bypass", "-File",
                            os.path.join(_HERE, "tests", "_test2.ps1")])
        return r.returncode == 0
    return boot_check()


# ── горячий деплой модулей ───────────────────────────────────────────
def read_token():
    """Токен из --token, иначе из хранилища по умолчанию (данные/_ci.token)."""
    for cand in (os.path.join(_HERE, "данные", "_ci.token"),):
        try:
            with open(cand, encoding="ascii") as f:
                s = f.read().strip()
            if len(s) >= 16:
                return s
        except OSError:
            continue
    return ""


def live_reload(url, token, module):
    """POST /_reload. Возвращает (код, сообщение)."""
    data = urllib.parse.urlencode({"module": module}).encode("ascii")
    code, body = _http(url + "/_reload", method="POST", data=data,
                       headers={"X-CI-Token": token})
    if code == 404:
        return code, ("сервер ещё без поддержки /_reload - нужен "
                      "одноразовый перезапуск (спросить пользователя)")
    if code in (401, 403):
        return code, "отказ: " + body.strip()[:120]
    try:
        resp = json.loads(body)
    except ValueError:
        return code, "странный ответ: " + body.strip()[:120]
    parts = ["%s: %s%s" % (m["id"], m["state"],
                           (" - " + m["reason"]) if m.get("reason") else "")
             for m in resp.get("modules", [])]
    return code, ("; ".join(parts) or "(пусто)")


def deploy_modules(changed_files, url, token):
    """Перезагрузить модули, к которым относятся изменённые файлы."""
    mod_ids = set()
    for p in changed_files:
        rel = os.path.relpath(p, _HERE)
        parts = rel.split(os.sep)
        if len(parts) >= 2 and parts[0] == "modules":
            mod_ids.add(parts[1])
    if not mod_ids:
        return True
    ok = True
    for mid in sorted(mod_ids):
        if not os.path.isdir(os.path.join(_HERE, "modules", mid)):
            continue  # папку удалили: перезагрузка в первый цикл после
        code, msg = live_reload(url, token, mid)
        log("деплой модуля %s -> HTTP %s: %s" % (mid, code, msg))
        if code != 200:
            ok = False
    return ok


# ── наблюдение ───────────────────────────────────────────────────────
def snapshot():
    snap = {}
    for root in WATCH_DIRS:
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in ("__pycache__",)]
            for fn in files:
                if fn.endswith((".py", ".json")):
                    p = os.path.join(dirpath, fn)
                    try:
                        st = os.stat(p)
                        snap[p] = (st.st_mtime, st.st_size)
                    except OSError:
                        pass
    for p in WATCH_FILES:
        try:
            st = os.stat(p)
            snap[p] = (st.st_mtime, st.st_size)
        except OSError:
            pass
    return snap


def watch(url, interval, token):
    log("watch: слежу за core/, modules/, server.py (интервал %s с)" % interval)
    log("живой сервер: %s" % url)
    snap = snapshot()
    while True:
        time.sleep(interval)
        try:
            now = snapshot()
        except Exception as e:
            log("ошибка снимка файлов: %s" % e)
            continue
        changed = [p for p in now
                   if p not in snap or snap[p] != now[p]]
        removed = [p for p in snap if p not in now]
        snap = now
        if not changed and not removed:
            continue
        names = [os.path.relpath(p, _HERE) for p in changed + removed]
        log("изменения: %s" % ", ".join(names))

        # 1) компиляция изменённых
        bad = compile_all(changed)
        if bad:
            for p, err in bad:
                log("FAIL компиляция %s (файл ещё пишется? повтор на "
                    "следующем цикле):\n%s" % (os.path.relpath(p, _HERE), err))
            continue

        # 2) сортировка: модули / ядро
        mod_files = [p for p in changed if os.sep + "modules" + os.sep in p]
        # удалённые файлы тоже учитываем (модуль мог исчезнуть с диска)
        mod_files += [p for p in removed
                      if os.sep + "modules" + os.sep in p
                      and p not in mod_files]
        core_files = [p for p in changed + removed
                      if p not in mod_files
                      and (os.sep + "core" + os.sep in p
                           or p.endswith("server.py"))]
        other = [p for p in changed + removed
                 if p not in mod_files and p not in core_files]

        # 3) деплой модулей на живой сервер
        if mod_files:
            if token:
                deploy_modules(mod_files, url, token)
            else:
                log("нет токена CI - деплой невозможен "
                    "(--token или <store>/_ci.token)")

        # 4) ядро: нужен перезапуск - НЕ делаем сами
        if core_files:
            log("!! правки ядра: %s - нужен перезапуск сервера. "
                "CI сам его не делает: скажите пользователю." %
                ", ".join(os.path.relpath(p, _HERE) for p in core_files))
        if other:
            log("прочее (без деплоя): %s"
                % ", ".join(os.path.relpath(p, _HERE) for p in other))


def main():
    ap = argparse.ArgumentParser(description="CI works-core")
    ap.add_argument("cmd", choices=["check", "watch", "deploy"])
    ap.add_argument("--full", action="store_true",
                    help="check: полный смоук вместо быстрой проверки")
    ap.add_argument("--url", default="http://localhost:8080",
                    help="адрес живого СДО (watch/deploy)")
    ap.add_argument("--interval", type=float, default=2.0,
                    help="период опроса файлов, с (watch)")
    ap.add_argument("--token", default="",
                    help="токен CI (иначе <store по умолч.>/_ci.token)")
    ap.add_argument("kv", nargs="*", help="deploy: module=<id> | module=all")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if args.cmd == "check":
        ok = check(full=args.full)
        sys.exit(0 if ok else 1)
    if args.cmd == "deploy":
        kv = dict(x.split("=", 1) for x in args.kv if "=" in x)
        module = kv.get("module", "all")
        code, msg = live_reload(args.url, args.token or read_token(), module)
        print("HTTP %s: %s" % (code, msg))
        sys.exit(0 if code == 200 else 1)
    watch(args.url, args.interval, args.token or read_token())


if __name__ == "__main__":
    main()
