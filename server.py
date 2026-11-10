# -*- coding: utf-8 -*-
"""Точка входа works-core.

Запуск:
    python server.py --port 8080 --pass ПАРОЛЬ --demo
    python server.py --port 8080 --no-pass
"""
import argparse
import os
import secrets
import socket
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from core.store import Store
from core.core import Core
from core.http import WorksServer
from core.module import load_modules


# ── Автозапуск симулятора velxio (модуль «sim») ─────────────────────────
_SIM_PORTS = {"бэкенд": 8001, "фронтенд": 5173}


def _port_busy(port):
    s = socket.socket()
    s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def _sim_autostart(root):
    """Поднять velxio (бэкенд :8001 + фронтенд :5173), если ещё не работают.

    Возвращает (строки-статусы, {имя: (порт, Popen)} — запущенные нами).
    Симулятор необязателен: любая ошибка не мешает работе СДО.
    """
    root = os.path.abspath(root)
    lines = []
    started = {}
    if not os.path.isdir(root):
        lines.append("Симулятор: каталог %s не найден — запуск без него" % root)
        return lines, started
    bdir = os.path.join(root, "backend")
    fdir = os.path.join(root, "frontend")
    bins = os.path.join(root, "bin")  # arduino-cli для компиляции скетчей
    bpy = os.path.join(bdir, "venv", "Scripts", "python.exe")
    flags = (subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
             if os.name == "nt" else 0)  # окна velxio не показываем

    def env():
        e = dict(os.environ)
        if os.path.isdir(bins):
            e["PATH"] = bins + os.pathsep + e.get("PATH", "")
        return e

    def spawn(name, args, cwd):
        log = open(os.path.join(root, "_сим-%s.log" % name), "ab")
        p = subprocess.Popen(args, cwd=cwd, env=env(),
                             stdin=subprocess.DEVNULL,
                             stdout=log, stderr=subprocess.STDOUT,
                             creationflags=flags)
        started[name] = (_SIM_PORTS[name], p)

    try:
        if _port_busy(8001):
            lines.append("Симулятор: бэкенд уже работает (http://localhost:8001)")
        elif os.path.isfile(bpy):
            spawn("бэкенд", [bpy, "-m", "uvicorn", "app.main:app",
                             "--host", "127.0.0.1", "--port", "8001"], bdir)
            lines.append("Симулятор: бэкенд запускается (:8001)…")
        else:
            lines.append("Симулятор: нет venv в %s — бэкенд пропущен" % root)

        if _port_busy(5173):
            lines.append("Симулятор: фронтенд уже работает "
                         "(http://localhost:5173)")
        elif os.path.isdir(os.path.join(fdir, "node_modules")):
            cmd = (["cmd", "/c", "npm", "run", "dev", "--", "--host", "0.0.0.0"]
                   if os.name == "nt" else
                   ["npm", "run", "dev", "--", "--host", "0.0.0.0"])
            spawn("фронтенд", cmd, fdir)
            lines.append("Симулятор: фронтенд запускается (:5173)…")
        else:
            lines.append("Симулятор: нет node_modules в %s — фронтенд пропущен"
                         % root)

        if started:  # ждём готовности (до ~12 с)
            for _ in range(24):
                time.sleep(0.5)
                if all(_port_busy(p) for p, _ in started.values()):
                    break
        for name, port in _SIM_PORTS.items():
            if _port_busy(port):
                lines.append("Симулятор %s: http://localhost:%d%s"
                             % (name, port,
                                "" if name in started else " (был запущен ранее)"))
            elif name in started:
                lines.append("Симулятор %s: не поднялся — см. лог _сим-%s.log"
                             % (name, name))
    except Exception as e:
        lines.append("Симулятор: ошибка автозапуска (%s) — СДО продолжает работу"
                     % e)
    return lines, started


def _sim_stop(started):
    """Остановить только те компоненты симулятора, что запущены нами."""
    for name, (port, p) in started.items():
        try:
            if os.name == "nt":
                out = subprocess.run(["netstat", "-aon"], capture_output=True,
                                     text=True, errors="replace").stdout
                for ln in out.splitlines():
                    parts = ln.split()
                    if (len(parts) >= 5 and parts[3] == "LISTENING"
                            and parts[1].endswith(":%d" % port)):
                        subprocess.run(["taskkill", "/F", "/PID", parts[4]],
                                       capture_output=True)
                        break
            else:
                p.terminate()
        except Exception:
            pass
    time.sleep(1)


def _ci_watch_start(port):
    """Наблюдатель CI живёт вместе с СДО: стартует с сервером и гаснет
    вместе с ним (сам завершается, если сервер выключили)."""
    logf = None
    try:
        logf = open(os.path.join(_HERE, "_ci_watch.log"), "ab")
        return subprocess.Popen(
            [sys.executable, "-X", "utf8", os.path.join(_HERE, "ci.py"),
             "watch", "--url", "http://localhost:%d" % port],
            stdout=logf, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    except Exception as ex:
        print("  (наблюдатель CI не запущен: %s)" % ex)
        return None
    finally:
        if logf:
            logf.close()


def main():
    ap = argparse.ArgumentParser(description="works-core: раздача и сбор работ")
    ap.add_argument("--port", type=int, default=8080, help="порт (по умолч. 8080)")
    ap.add_argument("--host", default="0.0.0.0", help="хост (по умолч. 0.0.0.0)")
    ap.add_argument("--store", default="", help="путь к хранилищу (по умолч. ./данные)")
    ap.add_argument("--pass", dest="passwd", default="", help="пароль панели")
    ap.add_argument("--no-pass", action="store_true", help="панель без пароля")
    ap.add_argument("--demo", action="store_true", help="создать демо-данные")
    ap.add_argument("--sim", nargs="?", const="", default=None,
                    metavar="ПУТЬ",
                    help="запустить симулятор velxio вместе с СДО "
                         "(путь к velxio; по умолч. соседний каталог)")
    ap.add_argument("--ci-token", default="",
                    help="токен CI для POST /_reload "
                         "(по умолч. файл _ci.token в хранилище)")
    ap.add_argument("--ci-watch", action="store_true",
                    help="запустить наблюдателя CI (ci.py watch) вместе "
                         "с СДО")
    ap.add_argument("--no-ci-watch", action="store_true",
                    help="не запускать наблюдателя CI (по умолч. он "
                         "запускается только для боевого хранилища)")
    args = ap.parse_args()

    # Хранилище
    store_path = args.store or os.path.join(_HERE, "данные")
    store = Store(store_path)
    core = Core(store)

    # Демо-данные
    if args.demo and not store.db["курсы"]:
        _create_demo(core)

    # Пароль: CLI --pass > сохранённый хеш > генерация нового.
    # --no-pass полностью отключает вход по паролю.
    passwd = args.passwd or None
    if args.no_pass:
        passwd = ""

    # Загрузка модулей
    mods_dir = os.path.join(_HERE, "modules")
    load_modules(core, mods_dir)
    core.mods_dir = mods_dir

    # Старт сервера
    static_dir = os.path.join(_HERE, "static")
    server = WorksServer(core, host=args.host, port=args.port,
                         static_dir=static_dir, passwd=passwd,
                         no_pass=args.no_pass, ci_token=args.ci_token)

    if not args.no_pass:
        if args.passwd:
            server.set_password(args.passwd)
        elif server.pw_hash:
            print("Пароль преподавателя: сохранён ранее (смена — в панели)")
        else:
            new_pw = secrets.token_hex(4)
            server.set_password(new_pw)
            print(f"Пароль преподавателя: {new_pw}")
            print("(сохраните его — показать второй раз я не смогу)")

    # Симулятор velxio: поднимаем вместе с СДО (--sim)
    sim_lines, sim_started = [], {}
    if args.sim is not None:
        sim_dir = args.sim or os.path.join(os.path.dirname(_HERE), "velxio")
        sim_lines, sim_started = _sim_autostart(sim_dir)

    # Наблюдатель CI: стартует вместе с СДО и гаснет вместе с ним
    # (по умолчанию — только для боевого хранилища; тестовые --store
    # наблюдателя не получают)
    watch_proc = None
    want_watch = ((args.ci_watch and not args.no_ci_watch)
                  or (store_path == os.path.join(_HERE, "данные")
                      and not args.no_ci_watch))
    if want_watch:
        watch_proc = _ci_watch_start(args.port)

    # Информация о запуске
    hostname = socket.gethostname()
    ips = set()
    try:
        ips = set(
            addr[4][0] for addr in socket.getaddrinfo(hostname, None)
            if addr[4][0].startswith(("192.", "10.", "172."))
        )
    except Exception:
        pass

    print(f"\n{'=' * 60}")
    print(f"  WORKS-CORE запущен")
    print(f"  Хранилище: {store.root}")
    print(f"  Порт:      {args.port}")
    print(f"  Студенты:  http://localhost:{args.port}/")
    for ip in sorted(ips):
        print(f"             http://{ip}:{args.port}/")
    print(f"  Панель:    http://localhost:{args.port}/staff")
    print(f"  Модули:    http://localhost:{args.port}/_modules")
    print(f"  Модулей загружено: {len(core.modules)}")
    for m in core.modules:
        state = m.get("state", "?")
        icon = "✅" if state == "ok" else "❌"
        print(f"    {icon} {m.get('name', m['id'])} ({m['id']}) — {state}")
    for ln in sim_lines:
        print("  " + ln)
    if watch_proc:
        print("  Наблюдатель CI: запущен — гаснет вместе с сервером")
    print(f"{'=' * 60}\n")
    print("  Остановка: Ctrl+C")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановка...")
    finally:
        server.server_close()
        if watch_proc:
            try:
                watch_proc.terminate()
                watch_proc.wait(timeout=5)
                print("Наблюдатель CI остановлен")
            except Exception:
                pass
        if sim_started:
            _sim_stop(sim_started)
            print("Симулятор остановлен (запущенные нами компоненты)")


def _create_demo(core):
    """Создать демонстрационные данные."""
    cid = core.new_course("Демо: Охранно-пожарная сигнализация (ОПС)")
    lid1 = core.new_lesson(cid, "Занятие 1: Монтаж АПС")
    lid2 = core.new_lesson(cid, "Занятие 2: Расчёт резерва питания")

    # Задание 1: монтаж АПС
    core.new_task(lid1, "Расчёт шлейфов и выбор типа",
                  description="""## Задача

Рассчитать количество извещателей для помещения **склад 24×18 м**.

### Порядок работы
1. Определите площадь помещения
2. Рассчитайте количество извещателей **по площади** и **по шагу**
3. Выберите бОльшее значение
4. Определите тип извещателя по среде помещения
5. Укажите количество шлейфов

### Нормы
- Один дымовой извещатель контролирует до **85 м²**
- Расстояние между извещателями не более **9 м**
- От стены не более **4,5 м**
- Высота потолка **4,2 м**""",
                  form=[
                      {"тип": "static", "подсказка": "📐 Расчёт помещения"},
                      {"тип": "number", "ключ": "width", "вопрос": "Ширина помещения, м",
                       "обязательно": True, "мин": 1},
                      {"тип": "number", "ключ": "length", "вопрос": "Длина помещения, м",
                       "обязательно": True, "мин": 1},
                      {"тип": "number", "ключ": "height", "вопрос": "Высота потолка, м",
                       "обязательно": True, "мин": 1},
                      {"тип": "static", "подсказка": "🔢 Тип извещателя"},
                      {"тип": "select", "ключ": "detector_type",
                       "вопрос": "Тип извещателя",
                       "варианты": ["ИП 212 (дымовой)", "ИП 101 (тепловой)",
                                    "ИП 102 (дымовой линейный)", "ИПР-К"],
                       "обязательно": True},
                      {"тип": "static", "подсказка": "📊 Результаты расчёта"},
                      {"тип": "number", "ключ": "detectors_num",
                       "вопрос": "Количество извещателей, шт",
                       "обязательно": True, "мин": 1},
                      {"тип": "number", "ключ": "loops", "вопрос": "Количество шлейфов",
                       "обязательно": True, "мин": 1},
                      {"тип": "textarea", "ключ": "justification",
                       "вопрос": "Обоснование выбора типа извещателя",
                       "обязательно": True, "строк": 4},
                      {"тип": "static", "подсказка": "📎 Вложения"},
                      {"тип": "file", "ключ": "scheme", "вопрос": "Схема расстановки"},
                  ])

    # Задание 2: расчёт резерва
    core.new_task(lid2, "Расчёт ёмкости аккумуляторной батареи",
                  description="""## Задача

Рассчитать ёмкость АКБ для резервного питания системы ОПС.

### Исходные данные
- Ток дежурного режима: **80 мА**
- Ток тревожного режима: **350 мА**
- Время резерва: **24 часа** в дежурном режиме + **3 часа** в тревожном
- Коэффициент запаса: **1.25**

### Формула
`C = (I_деж × T_деж + I_трев × T_трев) × K_запаса / 1000`""",
                  form=[
                      {"тип": "number", "ключ": "idle_current",
                       "вопрос": "Ток дежурного режима, мА",
                       "обязательно": True, "мин": 1},
                      {"тип": "number", "ключ": "alarm_current",
                       "вопрос": "Ток тревожного режима, мА",
                       "обязательно": True, "мин": 1},
                      {"тип": "number", "ключ": "idle_hours",
                       "вопрос": "Время дежурного режима, ч",
                       "обязательно": True, "мин": 1},
                      {"тип": "number", "ключ": "alarm_hours",
                       "вопрос": "Время тревожного режима, ч",
                       "обязательно": True, "мин": 1},
                      {"тип": "number", "ключ": "capacity",
                       "вопрос": "Расчётная ёмкость АКБ, А·ч",
                       "обязательно": True, "мин": 1},
                      {"тип": "select", "ключ": "battery_type",
                       "вопрос": "Выбранный типоразмер АКБ",
                       "варианты": ["7 А·ч", "12 А·ч", "17 А·ч", "25 А·ч", "50 А·ч"],
                       "обязательно": True},
                      {"тип": "textarea", "ключ": "conclusion",
                       "вопрос": "Вывод: достаточно ли выбранной АКБ?",
                       "строк": 3, "обязательно": True},
                  ])

    # Студенты
    for name in ["Иванов И.И.", "Петров П.П.", "Сидоров С.С.",
                 "Кузнецов А.В.", "Смирнова Е.Д.", "Васильев Д.К."]:
        core.enroll(cid, core.add_student(name, "П-21"))

    core.store.save()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import socket
    main()