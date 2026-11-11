# -*- coding: utf-8 -*-
"""CI works-core: испытательный полигон (стенд) и горячий деплой.

Конвейер правок:
    правка файла -> компиляция -> СТЕНД (:8090, своё хранилище)
    -> проверки стенда -> и только потом боевой (:8080).

  * модули: на стенде горячая перезагрузка (/_reload), после зелёных
    проверок - та же перезагрузка на боевом;
  * ядро (core/*, server.py): на стенде ПОЛНЫЙ перезапуск (там нет
    студентов - это безопасно); на боевом CI ядро НЕ перезапускает сам -
    пишет «стенд зелёный», а перезапуск делает явная команда
    `python ci.py promote` (её запускает человек = согласие).

Команды:
    python ci.py check               однократная проверка (компиляция +
                                     пробный старт на :8097)
    python ci.py check --full        полный смоук (tests/_test2.ps1)
    python ci.py stage               поднять/проверить стенд (:8090)
    python ci.py stage --fresh       стенд на свежей копии боевых данных
    python ci.py watch               следить за файлами: стенд -> деплой
    python ci.py deploy module=sim   перезагрузить модуль на БОЕВОМ вручную
    python ci.py promote             перезапустить БОЕВОЙ сервер (согласие
                                     человека; новые ядро+модули уже
                                     проверены на стенде)

Параметры: --url http://localhost:8080 (боевой), --stage-url :8090,
--interval 2, --token (иначе <store>/_ci.token), --yes (promote без вопроса).

Правила безопасности:
  * CI никогда не пишет в боевой хранилище (стенд - отдельное);
  * CI убивает/перезапускает только СВОЙ стенд; боевой перезапускается
    только командой promote (явное действие человека).
"""
import argparse
import json
import os
import shutil
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
STAGE_PORT = 8090
STAGE_STORE = os.path.join(_HERE, "_stage_store")
PROD_STORE = os.path.join(_HERE, "данные")
WATCH_DIRS = [os.path.join(_HERE, "core"), os.path.join(_HERE, "modules")]
WATCH_FILES = [os.path.join(_HERE, "server.py"), os.path.join(_HERE, "ci.py")]

_stage_proc = None  # Popen стенда (живёт при watch)


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


def _port_busy(port):
    return _wait_port(port, timeout=0.6)


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


# ── токены ───────────────────────────────────────────────────────────
def read_token():
    """Боевой токен из хранилища по умолчанию (данные/_ci.token)."""
    for cand in (os.path.join(PROD_STORE, "_ci.token"),):
        try:
            with open(cand, encoding="ascii") as f:
                s = f.read().strip()
            if len(s) >= 16:
                return s
        except OSError:
            continue
    return ""


def stage_token():
    """Токен стенда: CI сам его создаёт и передаёт серверу (--ci-token)."""
    import secrets
    os.makedirs(STAGE_STORE, exist_ok=True)
    p = os.path.join(STAGE_STORE, "_ci.token")
    try:
        with open(p, encoding="ascii") as f:
            s = f.read().strip()
        if len(s) >= 16:
            return s
    except OSError:
        pass
    s = secrets.token_hex(16)
    with open(p, "w", encoding="ascii", newline="") as f:
        f.write(s)
    return s


# ── горячий деплой модулей ───────────────────────────────────────────
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


def deploy_modules(changed_files, url, token, quiet=False):
    """Перезагрузить модули, к которым относятся изменённые файлы.
    Возвращает (ok, список id)."""
    mod_ids = set()
    for p in changed_files:
        rel = os.path.relpath(p, _HERE)
        parts = rel.split(os.sep)
        if len(parts) >= 2 and parts[0] == "modules":
            mod_ids.add(parts[1])
    if not mod_ids:
        return True, []
    ok = True
    for mid in sorted(mod_ids):
        if not os.path.isdir(os.path.join(_HERE, "modules", mid)):
            continue  # папку удалили: перезагрузка в первый цикл после
        code, msg = live_reload(url, token, mid)
        if not quiet:
            log("деплой модуля %s -> HTTP %s: %s" % (mid, code, msg))
        if code != 200:
            ok = False
    return ok, sorted(mod_ids)


# ── СТЕНД (:8090) ────────────────────────────────────────────────────
def _stage_cmd(token):
    return [PY, "-X", "utf8", os.path.join(_HERE, "server.py"),
            "--port", str(STAGE_PORT), "--store", STAGE_STORE,
            "--no-pass", "--ci-token", token]


def _stop_stage():
    global _stage_proc
    if _stage_proc is not None:
        try:
            _stage_proc.terminate()
            _stage_proc.wait(timeout=10)
        except Exception:
            try:
                _stage_proc.kill()
            except Exception:
                pass
        _stage_proc = None


def copy_store_to_stage():
    """Свежая копия боевого хранилища -> _stage_store (сначала чисто)."""
    if os.path.isdir(STAGE_STORE):
        shutil.rmtree(STAGE_STORE, ignore_errors=True)
    if os.path.isdir(PROD_STORE):
        shutil.copytree(PROD_STORE, STAGE_STORE)
        log("стенд: хранилище скопировано из боевого (%s)" % PROD_STORE)
    else:
        log("стенд: боевого хранилища нет - стенд стартует с демо")
    # токен стенда копировать нельзя (это боевой) - оставим наш
    tok = stage_token()  # создаёт файл, если его стёрла копия/чистка


def start_stage(fresh=False, quiet=False):
    """Поднять стенд. Уже запущен - переиспользуем. (ci убивает/растит
    только свой стенд; боевой не трогаем.)"""
    global _stage_proc
    if _port_busy(STAGE_PORT):
        if not quiet:
            log("стенд: порт %d уже слушается - переиспользую" % STAGE_PORT)
        return True
    if fresh:
        if not quiet:
            log("стенд: свежие данные...")
        copy_store_to_stage()
    tok = stage_token()
    if not quiet:
        log("стенд: старт на :%d (хранилище %s)" % (STAGE_PORT, STAGE_STORE))
    _stage_proc = subprocess.Popen(_stage_cmd(tok), cwd=_HERE,
                                   stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
    if not _wait_port(STAGE_PORT, timeout=30):
        log("FAIL стенд не поднялся за 30 с")
        _stop_stage()
        return False
    return True


def restart_stage(quiet=False):
    """Полный перезапуск стенда (для правок ядра). Стенд - свой, без спроса."""
    if not quiet:
        log("стенд: перезапуск (новое ядро)")
    _stop_stage()
    time.sleep(1.0)
    return start_stage(quiet=True)


def stage_health():
    """Проверки стенда. Возвращает (ok, краткое сообщение)."""
    url = "http://localhost:%d" % STAGE_PORT
    code, body = _http(url + "/_login")
    if code != 200 or "form" not in body:
        return False, "/_login -> %s" % code
    code, _ = _http(url + "/")
    if code not in (200, 302):
        return False, "/ -> %s" % code
    code, msg = live_reload(url, stage_token(), "all")
    # HTTP 200 от /_reload = все модули в состоянии ok/выключен;
    # 500 = кто-то «сбой»
    if code != 200:
        return False, "перегрузка модулей: HTTP %s: %s" % (code, msg)
    return True, "модули: %s" % msg[:160]


def stage():
    """Поднять стенд и проверить его (ручная команда)."""
    if not start_stage(fresh=False):
        return False
    ok, msg = stage_health()
    log("стенд: %s (%s)" % ("OK" if ok else "FAIL", msg))
    log("стенд доступен: http://localhost:%d  (вход студентом/стаффом "
        "как на боевом; данные - копия)" % STAGE_PORT)
    return ok


# ── promote: перезапуск боевого (только явная команда человека) ──────
def _prod_pids_on(port):
    """Список PID процессов, слушающих боевой порт (netstat)."""
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"],
                             capture_output=True,
                             errors="replace").stdout or ""
    except Exception:
        return []
    pids = []
    for line in out.splitlines():
        if ("LISTENING" in line and (":%d " % port) in line):
            parts = line.split()
            if parts and parts[-1].isdigit():
                pid = int(parts[-1])
                if pid and pid not in pids:
                    pids.append(pid)
    return pids


def promote(yes=False):
    """Перезапуск БОЕВОГО сервера на новых ядре+модулях. Вызывается
    человеком - это и есть согласие (правило 'предупреждать перед
    остановкой процессов')."""
    url = "http://localhost:8080"
    code, _ = _http(url + "/_login")
    pids = _prod_pids_on(8080)
    log("promote: боевой сейчас HTTP %s, PID %s" %
        (code or "недоступен", ", ".join(str(p) for p in pids) or "нет"))
    if not yes:
        try:
            ans = input("Перезапустить БОЕВОЙ сервер :8080? [Д/н] ")
        except EOFError:
            ans = ""
        if ans.strip().lower() not in ("", "y", "yes", "д", "да"):
            log("promote: отменено человеком")
            return False
    if pids:
        log("promote: останавливаю боевой PID %s" %
            ", ".join(str(p) for p in pids))
        for pid in pids:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True)
        time.sleep(2.0)
    # старт detached: переживает и консоль ci, и консоль запустившего
    cmd = ("cd /d %s && %s -X utf8 server.py --port 8080 --sim "
           "> _prod.log 2>&1" % (_HERE, PY))
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Start-Process -FilePath 'cmd.exe' -ArgumentList '/c','"
                    + cmd.replace("'", "''") + "' -WindowStyle Minimized"],
                    capture_output=True)
    ok = _wait_port(8080, timeout=40)
    code, _ = _http(url + "/_login") if ok else (0, "")
    log("promote: боевой %s (HTTP %s, /_login %s)" %
        ("поднялся" if ok else "НЕ поднялся", "200" if ok else "-",
         code or "-"))
    if ok:
        # все модули на новом ядре - перезагрузить для чистоты состояний
        c, m = live_reload(url, read_token(), "all")
        log("promote: перегрузка модулей -> HTTP %s: %s" % (c, m[:160]))
    return ok and code == 200


# ── наблюдение (конвейер) ────────────────────────────────────────────
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


def watch(url, interval, token, stage_url="http://localhost:%d" % STAGE_PORT):
    log("watch: конвейер стенд->боевой (интервал %s с)" % interval)
    log("боевой: %s | стенд: %s" % (url, stage_url))
    if not start_stage(quiet=True):
        log("FAIL стенд не поднялся - конвейер всё равно работает: "
            "модули пойдут на боевой только после зелёного стенда")
    pending_prod = []   # модули, готовые к боевому деплою (prod был недоступен)
    snap = snapshot()
    down = 0            # циклы, в которых боевой недоступен
    while True:
        time.sleep(interval)
        # наблюдатель живёт вместе с сервером: сервер выключен —
        # наблюдатель тоже завершается (штатный рестарт ~10 с
        # переживается: 15 циклов = 30 с подряд недоступности)
        c0, _ = _http(url + "/_login")
        if c0 != 200:
            down += 1
            if down >= 15:
                log("боевой недоступен %d циклов подряд — "
                    "наблюдатель завершается (сервер выключен)"
                    % down)
                return
        else:
            down = 0
        try:
            now = snapshot()
        except Exception as e:
            log("ошибка снимка файлов: %s" % e)
            continue
        changed = [p for p in now if p not in snap or snap[p] != now[p]]
        removed = [p for p in snap if p not in now]
        snap = now

        # боевой мог быть выключен и включиться: сбрасываем долг модулей
        if pending_prod:
            code, _ = _http(url + "/_login")
            if code == 200:
                log("боевой снова доступен - довожу модули: %s"
                    % ", ".join(pending_prod))
                ok, _left = deploy_modules(
                    [os.path.join(_HERE, "modules", m, "модуль.py")
                     for m in pending_prod], url, token)
                if ok:
                    pending_prod = []

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
        mod_files += [p for p in removed
                      if os.sep + "modules" + os.sep in p
                      and p not in mod_files]
        core_files = [p for p in changed + removed
                      if p not in mod_files
                      and (os.sep + "core" + os.sep in p
                           or p.endswith("server.py"))]
        other = [p for p in changed + removed
                 if p not in mod_files and p not in core_files]

        # 3) СТЕНД: модули - горячо; ядро - перезапуском стенда
        need_stage_check = False
        if mod_files:
            s_ok, _ids = deploy_modules(mod_files, stage_url,
                                        stage_token(), quiet=True)
            log("стенд: модули %s -> %s" %
                (", ".join(_ids), "OK" if s_ok else "FAIL"))
            need_stage_check = True
        if core_files:
            if not restart_stage(quiet=True):
                log("FAIL стенд не поднялся на новом ядре - НА БОЕВОЙ "
                    "НЕ ДЕПЛОИМ. Разберитесь с ядром.")
                continue
            log("стенд: перезапущен на новом ядре")
            need_stage_check = True
        if not need_stage_check:
            if other:
                log("прочее (без деплоя): %s" %
                    ", ".join(os.path.relpath(p, _HERE) for p in other))
            continue

        # 4) проверки стенда
        ok, msg = stage_health()
        log("стенд: %s (%s)" % ("OK" if ok else "FAIL", msg))
        if not ok:
            log("!! на боевой НЕ деплоим - правки остались только на "
                "стенде. Исправьте файл - цикл повторится.")
            continue

        # 5) боевой: модули - сразу; ядро - только через promote (человек)
        if mod_files:
            code, _ = _http(url + "/_login")
            if code != 200:
                s_ok, ids = deploy_modules(mod_files, stage_url,
                                           stage_token(), quiet=True)
                pending_prod.extend(i for i in ids if i not in pending_prod)
                log("боевой недоступен (HTTP %s) - модули отложены: %s"
                    % (code, ", ".join(ids)))
            else:
                p_ok, ids = deploy_modules(mod_files, url, token)
                if not p_ok:
                    pending_prod.extend(i for i in ids
                                        if i not in pending_prod)
        if core_files:
            log("!! правки ядра проверены на стенде - зелёный. Боевой "
                "перезапускается ВРУЧНУЮ: python ci.py promote "
                "(это согласие человека).")

        if other:
            log("прочее (без деплоя): %s" %
                ", ".join(os.path.relpath(p, _HERE) for p in other))


def main():
    ap = argparse.ArgumentParser(description="CI works-core")
    ap.add_argument("cmd", choices=["check", "watch", "deploy",
                                    "stage", "promote"])
    ap.add_argument("--full", action="store_true",
                    help="check: полный смоук вместо быстрой проверки")
    ap.add_argument("--fresh", action="store_true",
                    help="stage: свежая копия боевого хранилища")
    ap.add_argument("--yes", action="store_true",
                    help="promote: без вопроса")
    ap.add_argument("--url", default="http://localhost:8080",
                    help="адрес боевого СДО (watch/deploy)")
    ap.add_argument("--interval", type=float, default=2.0,
                    help="период опроса файлов, с (watch)")
    ap.add_argument("--token", default="",
                    help="токен CI боевого (иначе данные/_ci.token)")
    ap.add_argument("kv", nargs="*", help="deploy: module=<id> | module=all")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if args.cmd == "check":
        ok = check(full=args.full)
        sys.exit(0 if ok else 1)
    if args.cmd == "stage":
        ok = stage()
        sys.exit(0 if ok else 1)
    if args.cmd == "promote":
        ok = promote(yes=args.yes)
        sys.exit(0 if ok else 1)
    if args.cmd == "deploy":
        kv = dict(x.split("=", 1) for x in args.kv if "=" in x)
        module = kv.get("module", "all")
        code, msg = live_reload(args.url, args.token or read_token(), module)
        print("HTTP %s: %s" % (code, msg))
        sys.exit(0 if code == 200 else 1)
    try:
        watch(args.url, args.interval, args.token or read_token())
    finally:
        _stop_stage()


if __name__ == "__main__":
    main()
