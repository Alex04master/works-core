# -*- coding: utf-8 -*-
"""Загрузчик модулей. Модуль = папка с манифестом «модуль.json».

Модуль без кода (kind=json) — только декларации.
Модуль с кодом (kind=python) — файл «модуль.py» с функцией register(ctx).
"""
import importlib.util
import json
import os
import re
import sys
import traceback


API = 1  # версия контракта


class ModuleContext:
    """Всё, что модуль получает от ядра. Ничего другого он не видит."""

    def __init__(self, core, mod_id, manifest, mod_dir):
        self._core = core
        self.id = mod_id
        self.manifest = manifest
        self.dir = mod_dir
        self.settings = manifest.get("настройки") or manifest.get("settings", {})
        self.data_dir = os.path.join(core.store.root, "модули", mod_id)
        os.makedirs(self.data_dir, exist_ok=True)

    def add_route(self, method, path, handler=None, access="any"):
        """Зарегистрировать маршрут. Работает как декоратор и как прямой вызов.
        access: 'any', 'student', 'staff'.
        Маршруты накапливаются и подключаются после создания HTTP-сервера.
        """
        if handler is None:
            return lambda fn: self._add_route(method, path, fn, access)
        self._add_route(method, path, handler, access)

    def _add_route(self, method, path, handler, access):
        live = self._core.live_router
        if live is not None:
            # сервер уже работает: маршрут сразу в живой роутер
            # (горячая перезагрузка модуля)
            live.add(method, path, handler, access, owner=self.id)
        else:
            self._core.pending_routes.append(
                (method, path, handler, access, self.id))

    def on(self, event, handler):
        """Подписаться на событие ядра."""
        self._core.events.on(event, handler, self.id)

    def emit(self, event, **kw):
        """Собрать результаты подписчиков события (для вставки UI)."""
        return self._core.events.run(event, **kw)

    def get_course(self, cid):
        return self._core._get("курсы", cid)

    def get_lesson(self, lid):
        return self._core._get("занятия", lid)

    def get_task(self, tid):
        return self._core._get("задания", tid)

    def get_student(self, sid):
        return self._core._get("студенты", sid)

    def get_submission(self, task_id, student_id):
        return self._core.sub(task_id, student_id)

    def list_courses(self):
        return list(self._core.db.get("курсы", []))

    def list_lessons(self, course_id=None):
        ls = list(self._core.db.get("занятия", []))
        if course_id:
            ls = [l for l in ls if l.get("course") == course_id]
        return ls

    def list_tasks(self, lesson_id=None):
        ts = list(self._core.db.get("задания", []))
        if lesson_id:
            ts = [t for t in ts if t.get("lesson") == lesson_id]
        return ts

    def list_students(self):
        return list(self._core.db.get("студенты", []))

    def list_submissions(self, task_id=None, student_id=None):
        subs = list(self._core.db.get("сдачи", {}).values())
        if task_id:
            subs = [s for s in subs if s.get("task") == task_id]
        if student_id:
            subs = [s for s in subs if s.get("student") == student_id]
        return subs

    def list_modules(self):
        return [dict(m) for m in self._core.modules]

    def get_module_info(self, mid):
        for m in self._core.modules:
            if m["id"] == mid:
                return dict(m)
        return None

    # ── Мутация (через ядро) ─────────────────────────────────────────
    def add_course(self, title):
        return self._core.new_course(title)

    def add_lesson(self, course_id, title, materials=None):
        return self._core.new_lesson(course_id, title, materials)

    def add_task(self, lesson_id, title, description="", form=None, settings=None):
        return self._core.new_task(lesson_id, title, description, form, settings)

    def add_student(self, fio, group="", brigade=""):
        return self._core.add_student(fio, group, brigade)

    def update_student(self, sid, fio=None, group=None):
        return self._core.update_student(sid, fio, group)

    def delete_student(self, sid):
        return self._core.delete_student(sid)

    def delete_course(self, cid):
        return self._core.delete_course(cid)

    def delete_lesson(self, lid):
        return self._core.delete_lesson(lid)

    def delete_task(self, tid):
        """Удалить задание вместе со сдачами."""
        return self._core.delete_task(tid)

    def enroll(self, course_id, student_id):
        """Зачислить студента на курс."""
        return self._core.enroll(course_id, student_id)

    def unenroll(self, course_id, student_id):
        """Отчислить студента с курса."""
        return self._core.unenroll(course_id, student_id)

    def can_access(self, course_id, student_id):
        return self._core.can_access(course_id, student_id)

    def update_course(self, cid, title):
        c = self._core.course(cid)
        if c:
            c["title"] = title
            self._core.store.save()
            return True

    def course_group_add(self, cid, group):
        return self._core.course_group_add(cid, group)

    def course_group_remove(self, cid, group):
        return self._core.course_group_remove(cid, group)

    def brigade_max(self, cid):
        return self._core.brigade_max(cid)

    def set_brigade_max(self, cid, n):
        return self._core.set_brigade_max(cid, n)

    def student_set_brigade(self, sid, brigade):
        return self._core.student_set_brigade(sid, brigade)

    def task_set_issue(self, tid, brigades):
        return self._core.task_set_issue(tid, brigades)

    def task_for_brigade(self, task, brigade):
        return self._core.task_for_brigade(task, brigade)

    def brigade_rename(self, old, new):
        return self._core.brigade_rename(old, new)

    def brigade_off(self, name):
        """True, если бригада отключена преподавателем."""
        return self._core.brigade_off(name)

    def brigade_set_enabled(self, name, enabled):
        """Включить (True) или отключить (False) бригаду."""
        return self._core.brigade_set_enabled(name, enabled)

    def brigades_enabled(self, course_id):
        """True, если бригады на курсе включены."""
        return self._core.brigades_enabled(course_id)

    def set_brigades_enabled(self, course_id, enabled):
        """Включить (True) или отключить (False) бригады для курса."""
        return self._core.set_brigades_enabled(course_id, enabled)

    def brigade_delete(self, name):
        return self._core.brigade_delete(name)

    def audit(self, action, details=None, who="преподаватель", handler=None):
        """Запись в журнал действий (файл данные/лог/…)."""
        ip = ""
        if handler is not None:
            try:
                ip = handler.client_address[0]
            except Exception:
                ip = ""
        try:
            self._core.audit(who, action, details, ip)
        except Exception:
            pass

    def audit_read(self, month=None):
        return self._core.audit_read(month)

    def audit_months(self):
        return self._core.audit_months()

    def audit_cleanup(self, keep_months=0):
        return self._core.audit_cleanup(keep_months)

    def mat_dir(self, course_id, lesson_id):
        """Папка файлов занятия (данные/раздатка/<курс>/<занятие>)."""
        return os.path.join(self._core.store.mat, course_id, lesson_id)

    def save(self):
        self._core.store.save()
        return False

    def update_lesson(self, lid, title, materials=None):
        l = self._core.lesson(lid)
        if l:
            l["title"] = title
            if materials is not None:
                l["материалы"] = materials
            self._core.store.save()
            return True
        return False

    def update_task(self, tid, title=None, description=None, form=None, settings=None):
        t = self._core.task(tid)
        if not t:
            return False
        if title is not None:
            t["title"] = title
        if description is not None:
            t["описание"] = description
        if form is not None:
            t["форма"] = form
        if settings is not None:
            t["настройки"] = settings
        self._core.store.save()
        return True

    # ── Сдача ────────────────────────────────────────────────────────
    def submit(self, task_id, student_id, answers=None, files=None, note="",
               brigade=""):
        return self._core.collect(task_id, student_id, answers, files, note,
                                  brigade=brigade)

    def set_verdict(self, task_id, student_id, verdict, score=None, comment="",
                    check=None):
        from datetime import datetime
        sub = self._core.sub(task_id, student_id)
        if not sub:
            return False
        ver = self._core.latest(sub)
        ver["verdict"] = verdict
        ver["score"] = score
        ver["comment"] = comment
        ver["чек"] = sorted(int(x) for x in (check or []))
        ver["время_вердикта"] = datetime.now().isoformat(timespec="seconds")
        status_map = {"Принято": "принято", "Принято с замечаниями": "принято",
                      "На доработку": "доработка", "Не принято": "отклонено"}
        sub["status"] = status_map.get(verdict, "сдано")
        self._core.store.save()
        self._core.events.run("verdict.after", sub=sub, version=ver)
        return True

    # ── Журнал ─────────────────────────────────────────────────────────
    def log(self, msg):
        """Запись в журнал ядра."""
        print("[%s] %s" % (self.id, msg))

    # ── Доступ к данным модуля ───────────────────────────────────────
    def data_file(self, name):
        return os.path.join(self.data_dir, os.path.basename(name))

    def kv_load(self, name, dflt=None):
        import json
        path = self.data_file(name)
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return dflt if dflt is not None else {}

    def kv_save(self, name, obj):
        import json
        path = self.data_file(name)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        os.replace(path + ".tmp", path)

    # ── Вёрстка ──────────────────────────────────────────────────────
    def render_page(self, title, body, staff=False, extra_head="", course=None, lesson=None):
        return self._core.page(title, body, staff=staff, extra_head=extra_head,
                               course=course, lesson=lesson)


def load_modules(core, mods_dir):
    """Просканировать папку модулей и загрузить найденные."""
    if not os.path.isdir(mods_dir):
        return
    core.mods_dir = mods_dir
    for name in sorted(os.listdir(mods_dir)):
        d = os.path.join(mods_dir, name)
        if not os.path.isdir(d):
            continue
        man_path = os.path.join(d, "модуль.json")
        if not os.path.isfile(man_path):
            continue
        info = {"id": name, "dir": d, "state": "ok", "reason": ""}
        try:
            with open(man_path, encoding="utf-8") as f:
                man = json.load(f)
        except (ValueError, OSError) as ex:
            info.update(state="битый манифест", reason=str(ex))
            core.modules.append(info)
            continue

        info["id"] = str(man.get("id") or name)
        info["name"] = str(man.get("name") or info["id"])

        # Проверка: выключен ли модуль через панель /_modules
        if not core.is_module_enabled(info["id"]):
            info.update(state="выключен")
            core.modules.append(info)
            continue

        # Проверка: выключен ли модуль в манифесте
        if not man.get("enabled", True):
            info.update(state="выключен")
            core.modules.append(info)
            continue

        if man.get("api") != API:
            info.update(state="отключён",
                        reason=f"нужен api v{man.get('api')}, ядро v{API}")
            core.modules.append(info)
            continue

        try:
            kind = man.get("kind", "python")
            if kind == "json":
                ctx = ModuleContext(core, info["id"], man, d)
                register_json(ctx, man)
            else:
                py_path = os.path.join(d, "модуль.py")
                if os.path.isfile(py_path):
                    mod_name = "ws_mod_%s_1" % re.sub(r"\W", "_", info["id"])
                    core._mod_names[info["id"]] = mod_name
                    core._mod_gen[info["id"]] = 1
                    ctx = ModuleContext(core, info["id"], man, d)
                    _import_py(py_path, mod_name).register(ctx)
                else:
                    info.update(state="сбой", reason="нет модуль.py")
                    core.modules.append(info)
                    continue
        except Exception as ex:
            info.update(state="сбой", reason=f"{type(ex).__name__}: {ex}")
            traceback.print_exc()

        core.modules.append(info)


def reload_module(core, mods_dir, mod_id):
    """Горячая перезагрузка одного модуля в работающем сервере.

    Безопасный порядок:
      1) новый код компилируется и импортируется ДО снятия старого -
         синтаксическая ошибка не трогает работающий модуль;
      2) старые маршруты и подписки снимаются по владельцу (mod_id);
      3) модуль регистрируется заново. Если register() падает -
         попытка восстановить прежний код; иначе модуль помечается
         «сбой» (исправление файла + повторный /_reload поднимает).
    """
    def detach(mid):
        core.events.remove_mod(mid)
        if core.live_router is not None:
            core.live_router.remove_owner(mid)

    # каталог модуля по манифесту (id может не совпадать с именем папки)
    d = None
    if os.path.isdir(mods_dir):
        for name in sorted(os.listdir(mods_dir)):
            cand = os.path.join(mods_dir, name)
            man_path = os.path.join(cand, "модуль.json")
            if not os.path.isfile(man_path):
                continue
            try:
                with open(man_path, encoding="utf-8") as f:
                    man = json.load(f)
            except (ValueError, OSError):
                continue
            if str(man.get("id") or name) == mod_id:
                d = cand
                break
        if d is None:
            cand = os.path.join(mods_dir, mod_id)
            if os.path.isfile(os.path.join(cand, "модуль.json")):
                d = cand

    known = next((m for m in core.modules if m.get("id") == mod_id), None)
    if known is None:
        # модуль, впервые загруженный на живом сервере: появится и в
        # /_modules, и в перезагрузке module=all
        known = {"id": mod_id, "state": "?", "reason": ""}
        core.modules.append(known)

    if d is None:
        # модуль исчез с диска: снять его с живого сервера
        detach(mod_id)
        known.update(state="выключен", reason="нет на диске")
        return known

    info = known
    info["dir"] = d

    try:
        with open(os.path.join(d, "модуль.json"), encoding="utf-8") as f:
            man = json.load(f)
    except (ValueError, OSError) as ex:
        detach(mod_id)
        info.update(state="битый манифест", reason=str(ex))
        return info

    mid = str(man.get("id") or mod_id)
    info["id"] = mid
    info["name"] = str(man.get("name") or mid)

    if not core.is_module_enabled(mid) or not man.get("enabled", True):
        detach(mid)
        info.update(state="выключен", reason="")
        return info

    if man.get("api") != API:
        info.update(state="отключён",
                    reason=f"нужен api v{man.get('api')}, ядро v{API}")
        return info

    # 1) импорт нового кода (старый пока работает)
    old_name = core._mod_names.get(mid)
    old_mod = sys.modules.pop(old_name, None) if old_name else None
    gen = core._mod_gen.get(mid, 0) + 1
    core._mod_gen[mid] = gen
    mod_name = "ws_mod_%s_%d" % (re.sub(r"\W", "_", mid), gen)
    new_mod = None
    try:
        py_path = os.path.join(d, "модуль.py")
        if man.get("kind", "python") == "json":
            pass
        elif os.path.isfile(py_path):
            new_mod = _import_py(py_path, mod_name)
        else:
            info.update(state="сбой", reason="нет модуль.py")
            return info
    except Exception as ex:
        info.update(state="сбой", reason=f"{type(ex).__name__}: {ex}")
        traceback.print_exc()
        return info  # старый код продолжает работать

    # 2) снять старую регистрацию
    detach(mid)

    # 3) зарегистрировать заново
    ctx = ModuleContext(core, mid, man, d)
    try:
        if new_mod is None:
            register_json(ctx, man)
        else:
            new_mod.register(ctx)
        info.update(state="ok", reason="")
        core._mod_names[mid] = mod_name
        return info
    except Exception as ex:
        traceback.print_exc()
        # откат: вернуть прежний код, если он у нас сохранился
        detach(mid)
        if old_mod is not None and old_name:
            sys.modules[old_name] = old_mod
            core._mod_names[mid] = old_name
            try:
                old_mod.register(ModuleContext(core, mid, man, d))
                info.update(state="ok", reason="откат на прежний код: "
                                               f"{type(ex).__name__}: {ex}")
                return info
            except Exception as ex2:
                traceback.print_exc()
                info.update(state="сбой",
                            reason=f"откат не удался: {type(ex2).__name__}")
                return info
        info.update(state="сбой", reason=f"{type(ex).__name__}: {ex}")
        return info


def register_json(ctx, man):
    """Декларативный модуль (JSON-only): правила автопроверки."""
    rules = man.get("rules") or []
    if rules:
        def grade(task=None, answers=None, **kw):
            marks = {}
            passed = total = 0
            for r in rules:
                key = r.get("field") or r.get("ключ")
                if not key:
                    continue
                if r.get("task") and r["task"] not in (
                        (task or {}).get("id"), (task or {}).get("title")):
                    continue
                val = str((answers or {}).get(key, "")).strip().lower()
                expect = str(r.get("expect") or r.get("ожидать", "")).lower()
                ok = expect in val if r.get("type") == "keywords" else val == expect
                marks[key] = ok
                total += 1
                if ok:
                    passed += 1
            if not total:
                return None
            all_ok = passed == total
            return {
                "verdict": ("Принято (автопроверка)" if all_ok
                            else "Автопроверка: %d/%d" % (passed, total)),
                "score": round(100.0 * passed / total, 1),
                "status": "принято" if all_ok else "доработка",
                "comment": "автопроверка: %d/%d" % (passed, total),
                "marks": marks,
            }
        ctx.on("grade", grade)


def _import_py(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod