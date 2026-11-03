# -*- coding: utf-8 -*-
"""Точка входа works-core.

Запуск:
    python server.py --port 8080 --pass ПАРОЛЬ --demo
    python server.py --port 8080 --no-pass
"""
import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from core.store import Store
from core.core import Core
from core.http import WorksServer
from core.module import load_modules


def main():
    ap = argparse.ArgumentParser(description="works-core: раздача и сбор работ")
    ap.add_argument("--port", type=int, default=8080, help="порт (по умолч. 8080)")
    ap.add_argument("--host", default="0.0.0.0", help="хост (по умолч. 0.0.0.0)")
    ap.add_argument("--store", default="", help="путь к хранилищу (по умолч. ./данные)")
    ap.add_argument("--pass", dest="passwd", default="", help="пароль панели")
    ap.add_argument("--no-pass", action="store_true", help="панель без пароля")
    ap.add_argument("--demo", action="store_true", help="создать демо-данные")
    args = ap.parse_args()

    # Хранилище
    store_path = args.store or os.path.join(_HERE, "данные")
    store = Store(store_path)
    core = Core(store)

    # Демо-данные
    if args.demo and not store.db["курсы"]:
        _create_demo(core)

    # Пароль
    passwd = args.passwd
    if not passwd and not args.no_pass:
        import secrets
        passwd = secrets.token_hex(4)
        print(f"Пароль преподавателя: {passwd}")
        print("(сохраните его — показать второй раз я не смогу)")
    if args.no_pass:
        passwd = ""

    # Загрузка модулей
    mods_dir = os.path.join(_HERE, "modules")
    load_modules(core, mods_dir)

    # Старт сервера
    static_dir = os.path.join(_HERE, "static")
    server = WorksServer(core, host=args.host, port=args.port,
                         static_dir=static_dir, passwd=passwd)

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
    print(f"{'=' * 60}\n")
    print("  Остановка: Ctrl+C")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановка...")
        server.server_close()


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
        core.add_student(name, "П-21")

    core.store.save()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    import socket
    main()