# -*- coding: utf-8 -*-
"""Ядро: ровно 3 функции — раздать, назначить, собрать.

Всё остальное — модули.
"""
import json
import os
import re
from datetime import datetime

from .store import Store


def _now():

    return datetime.now().isoformat(timespec="seconds")


def _e(v):

    """Escape for HTML."""
    import html as _html
    return _html.escape(str(v) if v is not None else "", quote=True)


def _nid(key, db):

    """Сгенерировать id вида c1, l2, t3, s4."""
    n = 1
    while any(x.get("id") == key + str(n) for x in db):
        n += 1
    return key + str(n)


# ── События ────────────────────────────────────────────────────────────
class Events:
    """Таблица подписчиков на события. Сбой одного не роняет ядро."""

    def __init__(self):
        self._hooks = {}
        self.broken = {}

    def on(self, name, fn, mod_id=""):
        self._hooks.setdefault(name, []).append((mod_id, fn))

    def run(self, name, **kw):
        """Зовёт всех подписчиков события. Возвращает список результатов."""
        results = []
        for mod_id, fn in self._hooks.get(name, []):
            try:
                results.append(fn(**kw))
            except Exception as ex:
                import traceback
                self.broken[mod_id] = f"{type(ex).__name__}: {ex}"
                traceback.print_exc()
        return results


# ── Основные типы полей (встроенные в ядро) ────────────────────────────
def _render_field(fd, value=""):
    """HTML-инпут для поля формы."""
    typ = fd.get("тип", "text")
    key = fd.get("ключ", "")
    label = fd.get("вопрос") or fd.get("подсказка") or key
    val = str(value) if value is not None else ""
    req = fd.get("обязательно", False)
    star = ' <span class="req">*</span>' if req else ""
    html_id = f"f_{key}"

    if typ == "static":
        return f'<h3 class="field-block">{_e(fd.get("подсказка", label))}</h3>'

    if typ == "textarea":
        rows = int(fd.get("строк", 5))
        placeholder = _e(fd.get("место", ""))
        return (f'<div class="field"><label for="{html_id}">{_e(label)}{star}</label>'
                f'<textarea id="{html_id}" name="{_e(key)}" rows="{rows}" '
                f'placeholder="{placeholder}">{_e(val)}</textarea></div>')

    if typ == "select":
        opts = ""
        for o in fd.get("варианты", []):
            sel = ' selected' if str(o) == val else ''
            opts += f'<option value="{_e(o)}"{sel}>{_e(o)}</option>'
        return (f'<div class="field"><label for="{html_id}">{_e(label)}{star}</label>'
                f'<select id="{html_id}" name="{_e(key)}">{opts}</select></div>')

    if typ == "radio":
        opts = ""
        for o in fd.get("варианты", []):
            chk = ' checked' if str(o) == val else ''
            opts += (f'<label class="radio-label"><input type="radio" name="{_e(key)}" '
                     f'value="{_e(o)}"{chk}> {_e(o)}</label>')
        return f'<div class="field field-radio"><span class="field-label">{_e(label)}{star}</span>{opts}</div>'

    if typ == "checkbox":
        chk = ' checked' if val in ("1", "on", "true", "да") else ''
        tip = _e(fd.get("подсказка", label))
        return (f'<div class="field field-checkbox"><label>'
                f'<input type="checkbox" name="{_e(key)}"{chk}> {tip}{star}</label></div>')

    if typ == "checkboxes":
        opts = ""
        vals = set(val.split(",")) if val else set()
        for o in fd.get("варианты", []):
            chk = ' checked' if str(o) in vals else ''
            opts += (f'<label class="cb-label"><input type="checkbox" name="{_e(key)}" '
                     f'value="{_e(o)}"{chk}> {_e(o)}</label>')
        return f'<div class="field field-checkboxes"><span class="field-label">{_e(label)}{star}</span>{opts}</div>'

    if typ == "file":
        accept = fd.get("accept", "")
        acc = f' accept="{accept}"' if accept else ''
        return (f'<div class="field"><label for="{html_id}">{_e(label)}{star}</label>'
                f'<input type="file" id="{html_id}" name="{_e(key)}"{acc}></div>')

    # text, number, date, email, tel — все одинаковый input
    input_type = {"number": "number", "date": "date", "email": "email",
                  "tel": "tel"}.get(typ, "text")
    extra = ""
    if typ == "number":
        if "мин" in fd:
            extra += f' min="{fd["мин"]}"'
        if "макс" in fd:
            extra += f' max="{fd["макс"]}"'
        if "шаг" in fd:
            extra += f' step="{fd["шаг"]}"'
    placeholder = _e(fd.get("место", ""))
    ph = f' placeholder="{placeholder}"' if placeholder else ''
    return (f'<div class="field"><label for="{html_id}">{_e(label)}{star}</label>'
            f'<input type="{input_type}" id="{html_id}" name="{_e(key)}" '
            f'value="{_e(val)}"{ph}{extra}></div>')


def _parse_field(fd, raw):
    """Очистка и валидация значения поля."""
    typ = fd.get("тип", "text")
    key = fd.get("ключ", "")
    req = fd.get("обязательно", False)
    val = raw if raw is not None else ""

    if isinstance(val, list) and typ == "file":
        val = val  # список файлов — оставляем как есть

    if isinstance(val, list):
        val = ",".join(str(v) for v in val)

    val = str(val).strip() if not isinstance(val, list) else val

    if typ == "checkbox":
        val = "да" if val in ("on", "1", "true", "да") else ""

    if typ == "number":
        val = val.replace(",", ".")
        try:
            fv = float(val)
            if "мин" in fd and fv < float(fd["мин"]):
                return None, "меньше минимума"
            if "макс" in fd and fv > float(fd["макс"]):
                return None, "больше максимума"
        except (ValueError, TypeError):
            if req and val:
                return None, "не число"
            val = ""

    if req and not val:
        return None, "обязательное поле"

    return val, None


class Core:
    """Ядро works-core.

    Три основные функции:
        distribute(course_id, lesson_id) -> список материалов
        assign(task_id) -> данные задания с формой
        collect(task_id, student_id, answers, files) -> запись сдачи
    """

    def __init__(self, store):
        self.store = store
        self.db = store.db
        self.events = Events()
        self.modules = []      # список загруженных модулей
        self.fields = {}       # расширенные типы полей от модулей
        self.pending_routes = []  # маршруты от модулей, регистрируются после создания сервера
        self._module_states = self._load_module_states()

    # ── ТРИ ОСНОВНЫЕ ФУНКЦИИ ──────────────────────────────────────────

    def distribute(self, course_id, lesson_id):
        """Вернуть список материалов занятия: файлы и тексты.

        Каждый материал: {"тип": "файл"/"текст", "имя": ..., "путь" или "содержимое"}
        """
        lesson = self._get("занятия", lesson_id)
        if not lesson or lesson.get("course") != course_id:
            return []
        mats = lesson.get("материалы") or []
        result = []
        for m in mats:
            if m.get("тип") == "файл":
                path = os.path.join(self.store.mat, course_id, lesson_id, m["имя"])
                result.append({"тип": "файл", "имя": m["имя"], "путь": path})
            elif m.get("тип") == "текст":
                result.append({"тип": "текст", "имя": m.get("имя", ""),
                               "содержимое": m.get("содержимое", "")})
            else:
                result.append(m)
        return result

    def assign(self, task_id):
        """Вернуть данные задания: описание + форма отчёта."""
        task = self._get("задания", task_id)
        if not task:
            return None
        return {
            "id": task["id"],
            "title": task.get("title", ""),
            "описание": task.get("описание", ""),
            "форма": task.get("форма", []),
            "материалы": task.get("материалы", []),
            "настройки": task.get("настройки", {}),
        }

    def collect(self, task_id, student_id, answers=None, files=None, note=""):
        """Принять сдачу работы.

        Возвращает (запись_сдачи, ошибка).
        """
        task = self._get("задания", task_id)
        if not task:
            return None, "нет задания"
        student = self._get("студенты", student_id)
        if not student:
            return None, "нет студента"

        # Валидация полей
        cleaned = {}
        errors = []
        for fd in task.get("форма", []):
            key = fd.get("ключ", "")
            raw = None
            if answers and key in answers:
                raw = answers[key]
            elif files and key in files:
                raw = files[key]

            val, err = _parse_field(fd, raw)
            if err:
                errors.append(f"{fd.get('вопрос', key)}: {err}")
            elif val is not None:
                cleaned[key] = val

        # Хуки модулей перед сдачей
        for err in self.events.run("submit.before", task=task,
                                   student=student, answers=cleaned):
            if err:
                return None, str(err)

        if errors:
            return None, "; ".join(errors)

        # Сохраняем
        key = f"{task_id}__{student_id}"
        sub = self.db["сдачи"].setdefault(key, {
            "key": key, "task": task_id, "student": student_id,
            "participants": [student_id], "versions": [], "status": "сдано"})

        ver = {
            "n": len(sub["versions"]) + 1,
            "time": _now(),
            "answers": cleaned,
            "files": list(files.keys()) if files else [],
            "note": note,
            "verdict": None, "score": None, "comment": "",
        }
        sub["versions"].append(ver)
        sub["status"] = "сдано"
        self.store.save()

        self.events.run("submit.after", task=task, student=student, sub=sub, version=ver)
        return sub, None

    # ── ДОСТУП К ДАННЫМ ──────────────────────────────────────────────

    def _get(self, key, ident):
        for x in self.db.get(key, []):
            if x.get("id") == ident:
                return x
        return None

    def task(self, tid):
        return self._get("задания", tid)

    def lesson(self, lid):
        return self._get("занятия", lid)

    def course(self, cid):
        return self._get("курсы", cid)

    def student(self, sid):
        return self._get("студенты", sid)

    def sub(self, task_id, student_id):
        return self.db["сдачи"].get(f"{task_id}__{student_id}")

    def latest(self, sub):
        return (sub.get("versions") or [{}])[-1]

    def courses(self, student_id=None):
        return self.db.get("курсы", [])

    def lessons(self, course_id=None):
        ls = self.db.get("занятия", [])
        if course_id:
            ls = [l for l in ls if l.get("course") == course_id]
        return ls

    def tasks(self, lesson_id=None):
        ts = self.db.get("задания", [])
        if lesson_id:
            ts = [t for t in ts if t.get("lesson") == lesson_id]
        return ts

    def students(self):
        return self.db.get("студенты", [])

    def submissions(self, task_id=None, student_id=None):
        subs = list(self.db.get("сдачи", {}).values())
        if task_id:
            subs = [s for s in subs if s.get("task") == task_id]
        if student_id:
            subs = [s for s in subs if s.get("student") == student_id]
        return subs

    # ── CRUD (через модули) ──────────────────────────────────────────

    def new_course(self, title):
        cid = _nid("c", self.db["курсы"])
        obj = {"id": cid, "title": title}
        self.db["курсы"].append(obj)
        self.store.save()
        return cid

    def new_lesson(self, course_id, title, materials=None):
        lid = _nid("l", self.db["занятия"])
        obj = {"id": lid, "course": course_id, "title": title,
               "материалы": materials or []}
        self.db["занятия"].append(obj)
        self.store.save()
        return lid

    def new_task(self, lesson_id, title, description="", form=None, settings=None):
        tid = _nid("t", self.db["задания"])
        obj = {"id": tid, "lesson": lesson_id, "title": title,
               "описание": description, "форма": form or [],
               "настройки": settings or {}}
        self.db["задания"].append(obj)
        self.store.save()
        return tid

    def add_student(self, fio, group=""):
        sid = _nid("s", self.db["студенты"])
        obj = {"id": sid, "fio": fio, "group": group}
        self.db["студенты"].append(obj)
        self.store.save()
        return sid

    def update_student(self, sid, fio=None, group=None):
        s = self.student(sid)
        if not s:
            return False
        if fio is not None:
            s["fio"] = fio
        if group is not None:
            s["group"] = group
        self.store.save()
        return True

    def delete_student(self, sid):
        self.db["студенты"] = [s for s in self.db["студенты"] if s.get("id") != sid]
        self.store.save()
        return True

    def delete_course(self, cid):
        self.db["курсы"] = [c for c in self.db["курсы"] if c.get("id") != cid]
        # Удаляем занятия, задания, сдачи
        lesson_ids = [l["id"] for l in self.db["занятия"] if l.get("course") == cid]
        task_ids = [t["id"] for t in self.db["задания"] if t.get("lesson") in lesson_ids]
        self.db["занятия"] = [l for l in self.db["занятия"] if l.get("course") != cid]
        self.db["задания"] = [t for t in self.db["задания"] if t.get("lesson") not in lesson_ids]
        for tk in task_ids:
            for sk in list(self.db["сдачи"].keys()):
                if sk.startswith(tk + "__"):
                    del self.db["сдачи"][sk]
        self.store.save()
        return True

    def delete_lesson(self, lid):
        task_ids = [t["id"] for t in self.db["задания"] if t.get("lesson") == lid]
        self.db["занятия"] = [l for l in self.db["занятия"] if l.get("id") != lid]
        self.db["задания"] = [t for t in self.db["задания"] if t.get("lesson") != lid]
        for tk in task_ids:
            for sk in list(self.db["сдачи"].keys()):
                if sk.startswith(tk + "__"):
                    del self.db["сдачи"][sk]
        self.store.save()
        return True

    # ── ВЁРСТКА ──────────────────────────────────────────────────────

    def page(self, title, body, staff=False, extra_head="", course=None, lesson=None):
        """Собрать HTML-страницу.

        Модули могут подписаться на событие page.head и вернуть
        фрагменты для <head> (CSS, мета-теги, скрипты) — например,
        для разных тем оформления разных курсов.
        """
        cls = " staff" if staff else ""
        for fragment in self.events.run("page.head", course=course, lesson=lesson):
            if fragment:
                extra_head += fragment
        if not staff:
            extra_head += self.INACTIVITY_JS
        return (
            f'<!doctype html>'
            f'<meta charset="utf-8">'
            f'<title>{_e(title)}</title>'
            f'<link rel="stylesheet" href="/_static/core.css">'
            f'{extra_head}'
            f'<body class="{cls}">'
            f'<header class="topbar">{self._topbar(staff)}</header>'
            f'<main id="main"><h1>{_e(title)}</h1>{body}</main>'
            f'<footer class="footer">works-core</footer>'
            f'</body>')

    # ── Состояние модулей (вкл/выкл) ──────────────────────────────
    def _module_states_path(self):
        return os.path.join(self.store.root, "_modules_state.json")

    def _load_module_states(self):
        try:
            with open(self._module_states_path(), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save_module_states(self):
        path = self._module_states_path()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({
                "enabled": self._module_states.get("enabled", {}),
                "order": self._module_states.get("order", []),
            }, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)

    def toggle_module(self, mod_id):
        """Переключить состояние модуля. Возвращает новое состояние (True/False)."""
        enabled = self._module_states.setdefault("enabled", {})
        current = enabled.get(mod_id, True)
        enabled[mod_id] = not current
        self._save_module_states()
        return enabled[mod_id]

    def is_module_enabled(self, mod_id):
        enabled = self._module_states.get("enabled", {})
        return enabled.get(mod_id, True)

    def get_module_order(self):
        """Порядок модулей. Если не задан — порядок загрузки."""
        return self._module_states.get("order", [])

    def set_module_order(self, order_list):
        """Задать порядок модулей (список id)."""
        self._module_states["order"] = list(order_list)
        self._save_module_states()

    def sort_modules(self, modules):
        """Отсортировать список модулей по сохранённому порядку."""
        order = self.get_module_order()
        if not order:
            return list(modules)
        mod_map = {m["id"]: m for m in modules}
        ordered = []
        for mod_id in order:
            if mod_id in mod_map:
                ordered.append(mod_map.pop(mod_id))
        # Добавляем новые модули, которых нет в порядке
        ordered.extend(mod_map.values())
        return ordered

    
    # JS неактивности студента: предупреждение на 9 мин, выход на 10 мин
    INACTIVITY_JS = '''<script>
    var _iaL=Date.now();
    function _iaR(){_iaL=Date.now();var w=document.getElementById('_iaW');if(w)w.remove();}
    document.addEventListener('mousemove',_iaR);
    document.addEventListener('keydown',_iaR);
    document.addEventListener('click',_iaR);
    setInterval(function(){
 var d=Date.now()-_iaL;
 if(d>600000){location.href='/_logout';}
 else if(d>540000&&!document.getElementById('_iaW')){
  var w=document.createElement('div');w.id='_iaW';
  w.style.cssText='position:fixed;bottom:0;left:0;right:0;background:#c0392b;color:#fff;padding:14px 20px;font-size:15px;z-index:999;text-align:center;border-top:3px solid #a03022;cursor:pointer;';
  w.innerHTML='<b>SESSION WILL EXPIRE</b> due to inactivity. Move mouse to stay.';
  document.body.appendChild(w);}
    },10000);
    </script>'''
    def _topbar(self, staff):

        if staff:
            return ('<nav><a href="/">🏠 Студенту</a>'
                    ' <a href="/staff">📋 Панель</a>'
                    ' <a href="/_modules">🧩 Модули</a>'
                    ' <a href="/_staff_logout">Выйти</a></nav>')
        return '<nav><a href="/">🏠 Главная</a> <a href="/_logout">✖ Выйти</a></nav>'

    def task_form_html(self, task, values=None):
        """Сгенерировать HTML формы задания."""
        parts = []
        values = values or {}
        for fd in task.get("форма", []):
            key = fd.get("ключ", "")
            val = values.get(key, "")
            html = _render_field(fd, val)
            parts.append(html)
        return "\n".join(parts)