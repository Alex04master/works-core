# -*- coding: utf-8 -*-
"""Модуль «Режим отладки»: полный доступ к данным системы.

- /debug — обзор реестра (все ключи) и данных модулей.
- /debug/view/<ключ> — записи ключа (список/словарь): правка, добавление,
  удаление любой записи в формате JSON.
- /debug/edit/<ключ>?id=... — правка одной записи; без id — значение
  ключа целиком (в том числе создание новых ключей).
- /debug/raw — реестр.json целиком одним текстом; /debug/reload —
  перечитать реестр с диска; /debug/reg — скачать реестр.json.
- /debug/kv/<модуль>/<файл> — правка данных модулей.

Все изменения применяются сразу (без проверок структуры!) и
записываются в журнал действий. Доступ — только преподаватель.
"""
import json
import os
import urllib.parse


def _e(v):
    import html
    return html.escape(str(v), quote=True)


def _q(handler, params, name):
    """Значение из query. Диспетчер отрезает query от path до роутера,
    поэтому читаем handler.path (params может содержать только _parts)."""
    v = params.get(name)
    if isinstance(v, list):
        v = v[0] if v else ""
    if not v:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
        v = (qs.get(name) or [""])[0]
    return v or ""


def _uq(s):
    return urllib.parse.quote(str(s or ""))


def _unq(s):
    return urllib.parse.unquote(str(s or ""))


BANNER = (
    '<div class="error"><p>🐞 <b>Режим отладки.</b> Прямой доступ к данным: '
    'изменения применяются сразу и не проверяются на корректность. '
    'Сделайте резервную копию перед правками.</p></div>')


def _err(handler, msg, back="/debug"):
    handler._redirect(back + ("&" if "?" in back else "?")
                      + "err=" + urllib.parse.quote(str(msg)[:200]))
    return handler._SENT


def register(ctx):
    store = ctx._core.store
    db = ctx._core.db

    # ── Карточка на главной панели ───────────────────────────────────
    def _debug_card(**kw):
        return (
            '<details><summary>🐞 Режим отладки</summary>'
            '<div class="staff-card">'
            '<p class="hint">Прямой доступ к реестру: просмотр и правка '
            'любого параметра (JSON), добавление и удаление записей, '
            'правка реестра целиком, данные модулей. Изменения применяются '
            'сразу — используйте осознанно.</p>'
            '<p><a class="btn" href="/debug">🐞 Открыть отладку</a></p>'
            '</div></details>')

    ctx.on("staff.home_cards", _debug_card)

    # ── Хелперы ──────────────────────────────────────────────────────
    def _record(key, rid):
        """Найти запись в ключе реестра по id/ключу. → (запись, ссылка)."""
        val = db.get(key)
        if isinstance(val, dict):
            return val.get(rid)
        if isinstance(val, list):
            return next((r for r in val
                         if isinstance(r, dict)
                         and str(r.get("id", "")) == rid), None)
        return None

    def _set_record(key, rid, obj):
        val = db[key]
        if isinstance(val, dict):
            obj["key"] = rid
            val[rid] = obj
        else:
            obj["id"] = rid
            for i, r in enumerate(val):
                if isinstance(r, dict) and str(r.get("id", "")) == rid:
                    val[i] = obj
                    return
            val.append(obj)

    def _drop_record(key, rid):
        val = db[key]
        if isinstance(val, dict):
            val.pop(rid, None)
        elif isinstance(val, list):
            db[key] = [r for r in val
                       if not (isinstance(r, dict)
                               and str(r.get("id", "")) == rid)]

    def _preview(rec):
        if not isinstance(rec, dict):
            return _e(str(rec)[:60])
        base = (rec.get("title") or rec.get("fio") or rec.get("key")
                or rec.get("вопрос") or "")
        extra = ""
        if "versions" in rec:
            extra = " — версий: %d" % len(rec.get("versions") or [])
        return _e(str(base)[:60]) + _e(extra)

    # ── Обзор ────────────────────────────────────────────────────────
    @ctx.add_route("GET", "/debug", access="staff")
    def debug_home(handler, params):
        err = _q(handler, params, "err")
        err_msg = ('<div class="error"><p>%s</p></div>' % _e(err)) if err else ""
        rows = ""
        for key, val in db.items():
            if isinstance(val, list):
                kind, n = "список", "%d записей" % len(val)
            elif isinstance(val, dict):
                kind, n = "словарь", "%d ключей" % len(val)
            else:
                kind, n = "значение", _e(str(val)[:40])
            rows += (
                '<tr><td><a href="/debug/view/%s">%s</a></td>'
                '<td>%s</td><td>%s</td></tr>' % (_uq(key), _e(key), kind, n))
        files = ""
        mroot = os.path.abspath(store.mod_data)
        if os.path.isdir(mroot):
            for dirpath, dirs, fnames in os.walk(mroot):
                dirs.sort()
                for fn in sorted(fnames):
                    p = os.path.join(dirpath, fn)
                    rel = os.path.relpath(p, mroot).replace("\\", "/")
                    files += (
                        '<tr><td><a href="/debug/kv/%s">%s</a></td>'
                        '<td>%d</td></tr>'
                    ) % (_uq(rel), _e(rel), os.path.getsize(p))
        if not files:
            files = ('<tr><td colspan="2" class="hint">Файлов данных '
                     'модулей нет.</td></tr>')
        body = (
            '<p><a href="/staff">Все курсы</a></p>' + BANNER + err_msg +
            '<div class="staff-card"><h2>Реестр (реестр.json)</h2>'
            '<table class="staff-table"><tr><th>Ключ</th><th>Тип</th>'
            '<th>Объём</th></tr>%s</table>'
            '<p><a class="btn" href="/debug/raw">📄 Реестр целиком (JSON)</a> '
            '<form method="post" action="/debug/reload" '
            'onsubmit="return confirm(\'Перечитать реестр с диска? '
            'Несохранённые изменения в памяти будут потеряны.\')" '
            'style="display:inline-block">'
            '<button>🔄 Перечитать с диска</button></form> '
            '<a class="btn btn-secondary" href="/debug/reg">💾 Скачать '
            'реестр.json</a></p></div>'
            '<div class="staff-card"><h2>Данные модулей</h2>'
            '<table class="staff-table"><tr><th>Файл</th><th>Байт</th>'
            '</tr>%s</table></div>') % (rows, files)
        return ctx.render_page("Режим отладки", body, staff=True)

    # ── Просмотр ключа ───────────────────────────────────────────────
    @ctx.add_route("GET", "/debug/view/", access="staff")
    def debug_view(handler, params):
        parts = params.get("_parts") or [""]
        key = _unq(parts[0])
        err = _q(handler, params, "err")
        err_msg = ('<div class="error"><p>%s</p></div>' % _e(err)) if err else ""
        val = db.get(key)
        if val is None and key not in db:
            body = ('<p><a href="/debug">Отладка</a></p>' + BANNER +
                    '<div class="staff-card"><h2>%s</h2>'
                    '<p class="hint">Такого ключа в реестре нет. Его можно '
                    'создать на странице правки.</p>'
                    '<p><a class="btn" href="/debug/edit/%s">➕ Создать '
                    'ключ</a></p></div>') % (_e(key), _uq(key))
            return ctx.render_page("Отладка: %s" % key, body, staff=True)

        if not isinstance(val, (list, dict)):
            handler._redirect("/debug/edit/%s" % _uq(key))
            return handler._SENT

        rows = ""
        if isinstance(val, list):
            for rec in val:
                rid = str(rec.get("id", "")) if isinstance(rec, dict) else ""
                rows += (
                    '<tr><td>%s</td><td>%s</td>'
                    '<td><a class="btn btn-sm" '
                    'href="/debug/edit/%s?id=%s">✏️</a> '
                    '<a class="btn btn-sm btn-danger" '
                    'href="/debug/del/%s?id=%s" '
                    'onclick="return confirm(\'Удалить запись?\')">🗑</a>'
                    '</td></tr>'
                ) % (_e(rid), _preview(rec), _uq(key), _uq(rid),
                     _uq(key), _uq(rid))
        else:
            for k in sorted(val):
                rows += (
                    '<tr><td>%s</td><td>%s</td>'
                    '<td><a class="btn btn-sm" '
                    'href="/debug/edit/%s?id=%s">✏️</a> '
                    '<a class="btn btn-sm btn-danger" '
                    'href="/debug/del/%s?id=%s" '
                    'onclick="return confirm(\'Удалить запись?\')">🗑</a>'
                    '</td></tr>'
                ) % (_e(k), _preview(val[k]), _uq(key), _uq(k),
                     _uq(key), _uq(k))
        body = (
            '<p><a href="/debug">Отладка</a></p>' + BANNER + err_msg +
            '<div class="staff-card"><h2>Ключ «%s» — %d %s</h2>'
            '<table class="staff-table"><tr><th>ID / ключ</th><th>Запись</th>'
            '<th></th></tr>%s</table>'
            '<p><a class="btn btn-danger" href="/debug/del/%s" '
            'onclick="return confirm(\'Удалить ключ ЦЕЛИКОМ со всеми '
            'записями?\')">🗑 Удалить ключ целиком</a></p></div>'
            '<details open><summary>➕ Добавить запись</summary>'
            '<form method="post" action="/debug/save" class="staff-card">'
            '<input type="hidden" name="key" value="%s">'
            '<input type="hidden" name="act" value="add">'
            '<p><label>ID (для сдач — ключ вида t3__s1): '
            '<input type="text" name="id"></label></p>'
            '<p><label>JSON записи:<br><textarea name="text" rows="10" '
            'style="font-family:monospace;width:100%%" '
            'placeholder=\'{"id": "...", ...}\'></textarea></label></p>'
            '<p><button>Добавить</button></p></form></details>'
        ) % (_e(key), len(val),
             "записей" if isinstance(val, list) else "ключей",
             rows, _e(key), _uq(key))
        return ctx.render_page("Отладка: %s" % key, body, staff=True)

    # ── Правка записи / значения ключа ───────────────────────────────
    @ctx.add_route("GET", "/debug/edit/", access="staff")
    def debug_edit(handler, params):
        parts = params.get("_parts") or [""]
        key = _unq(parts[0])
        rid = _q(handler, params, "id")
        err = _q(handler, params, "err")
        err_msg = ('<div class="error"><p>%s</p></div>' % _e(err)) if err else ""
        title_extra = ""
        if rid:
            rec = _record(key, rid) if key in db else None
            if rec is None:
                return _err(handler, "запись не найдена", "/debug")
            text = json.dumps(rec, ensure_ascii=False, indent=1)
            title_extra = " — запись %s" % rid
            act = "save"
            confirm = ""
        else:
            val = db.get(key)
            if val is None and key not in db:
                text = "{\n}"
                title_extra = " — новый ключ"
            else:
                text = json.dumps(val, ensure_ascii=False, indent=1)
            act = "whole"
            confirm = (" onsubmit=\"return confirm('Заменить значение "
                       "ключа ЦЕЛИКОМ?')\"")
        back_link = ""
        if key in db:
            back_link = (' · <a href="/debug/view/' + _uq(key) + '">'
                         + _e(key) + "</a>")
        form = (
            '<form method="post" action="/debug/save" class="staff-card"%s>'
            '<h2>Правка JSON: %s%s</h2>'
            '<input type="hidden" name="key" value="%s">'
            '<input type="hidden" name="id" value="%s">'
            '<input type="hidden" name="act" value="%s">'
            '<p><label>JSON:<br><textarea name="text" rows="18" '
            'style="font-family:monospace;width:100%%">%s</textarea>'
            '</label></p>'
            '<p><button>💾 Сохранить</button></p></form>'
        ) % (confirm, _e(key), _e(title_extra), _e(key), _e(rid), act,
             _e(text))
        body = ('<p><a href="/debug">Отладка</a>' + back_link + "</p>"
                + BANNER + err_msg + form)
        return ctx.render_page("Отладка: правка", body, staff=True)

    # ── Сохранение ───────────────────────────────────────────────────
    @ctx.add_route("POST", "/debug/save", access="staff")
    def debug_save(handler, params):
        data = handler._parse_post()
        key = data.get("key", "")
        rid = (data.get("id") or "").strip()
        act = data.get("act", "save")
        back = "/debug/view/%s" % _uq(key) if key in db else "/debug"
        try:
            obj = json.loads(data.get("text", ""))
        except ValueError as ex:
            return _err(handler, "JSON: %s" % ex,
                        "/debug/edit/%s?id=%s" % (_uq(key), _uq(rid))
                        if rid else "/debug/edit/%s" % _uq(key))
        if act == "whole":
            if key in db and isinstance(db[key], (list, dict)):
                return _err(handler,
                            "ключ-список/словарь правьте записями "
                            "или через «Реестр целиком»",
                            "/debug/edit/%s" % _uq(key))
            db[key] = obj
            ctx.save()
            ctx.audit("отладка: ключ заменён целиком", {"ключ": key},
                      handler=handler)
            return handler._redirect(back)
        if act == "add":
            if not isinstance(db.get(key), (list, dict)):
                return _err(handler, "ключ не список и не словарь", back)
            nid = rid
            if not nid and isinstance(obj, dict):
                nid = obj.get("key", "") or obj.get("id", "")
            if not nid or not str(nid).strip():
                return _err(handler, "укажите ID записи", back)
            nid = str(nid).strip()
            exists = (nid in db[key] if isinstance(db[key], dict)
                      else any(isinstance(r, dict)
                               and str(r.get("id", "")) == nid
                               for r in db[key]))
            if exists:
                return _err(handler, "такой ID уже есть", back)
            _set_record(key, nid, obj)
            ctx.save()
            ctx.audit("отладка: добавлена запись",
                      {"ключ": key, "id": nid}, handler=handler)
            return handler._redirect(back)
        # act == save — правка одной записи
        if key not in db:
            return _err(handler, "нет такого ключа", "/debug")
        if not rid:
            return _err(handler, "не указан ID записи", back)
        if _record(key, rid) is None:
            return _err(handler, "запись не найдена", back)
        _set_record(key, rid, obj)
        ctx.save()
        ctx.audit("отладка: изменена запись",
                  {"ключ": key, "id": rid}, handler=handler)
        return handler._redirect(back)

    # ── Удаление записи / ключа ──────────────────────────────────────
    @ctx.add_route("GET", "/debug/del/", access="staff")
    def debug_del(handler, params):
        parts = params.get("_parts") or [""]
        key = _unq(parts[0])
        rid = _q(handler, params, "id")
        if key not in db:
            return _err(handler, "нет такого ключа", "/debug")
        if rid:
            if _record(key, rid) is None:
                return _err(handler, "запись не найдена",
                            "/debug/view/%s" % _uq(key))
            _drop_record(key, rid)
            ctx.save()
            ctx.audit("отладка: удалена запись",
                      {"ключ": key, "id": rid}, handler=handler)
        else:
            del db[key]
            ctx.save()
            ctx.audit("отладка: удалён ключ целиком", {"ключ": key},
                      handler=handler)
        handler._redirect("/debug/view/%s" % _uq(key)
                          if key in db else "/debug")
        return handler._SENT

    # ── Реестр целиком ───────────────────────────────────────────────
    @ctx.add_route("GET", "/debug/raw", access="staff")
    def debug_raw(handler, params):
        err = _q(handler, params, "err")
        err_msg = ('<div class="error"><p>%s</p></div>' % _e(err)) if err else ""
        text = json.dumps(db, ensure_ascii=False, indent=1)
        body = (
            '<p><a href="/debug">Отладка</a></p>' + BANNER + err_msg +
            '<form method="post" action="/debug/raw" class="staff-card" '
            'onsubmit="return confirm(\'Заменить ВЕСЬ реестр этим JSON? '
            'Структура не проверяется — только синтаксис.\')">'
            '<h2>реестр.json целиком</h2>'
            '<p><label><textarea name="text" rows="24" '
            'style="font-family:monospace;width:100%%">%s</textarea>'
            '</label></p>'
            '<p><button>💾 Заменить реестр</button></p></form>'
        ) % _e(text)
        return ctx.render_page("Отладка: реестр целиком", body, staff=True)

    @ctx.add_route("POST", "/debug/raw", access="staff")
    def debug_raw_save(handler, params):
        data = handler._parse_post()
        try:
            obj = json.loads(data.get("text", ""))
            if not isinstance(obj, dict):
                raise ValueError("корнем реестра должен быть объект {}")
        except ValueError as ex:
            return _err(handler, "JSON: %s" % ex, "/debug/raw")
        db.clear()
        db.update(obj)
        ctx.save()
        ctx.audit("отладка: реестр заменён целиком",
                  {"ключей": len(obj)}, handler=handler)
        handler._redirect("/debug?saved=1")
        return handler._SENT

    # ── Перечитать реестр с диска ────────────────────────────────────
    @ctx.add_route("POST", "/debug/reload", access="staff")
    def debug_reload(handler, params):
        fresh = store._load()
        db.clear()
        db.update(fresh)
        ctx.audit("отладка: реестр перечитан с диска", None)
        handler._redirect("/debug")
        return handler._SENT

    # ── Скачать реестр.json ──────────────────────────────────────────
    @ctx.add_route("GET", "/debug/reg", access="staff")
    def debug_reg(handler, params):
        with open(store.reg, "rb") as f:
            data = f.read()
        handler.send_response(200)
        handler.send_header("Content-Type",
                            "application/json; charset=utf-8")
        handler.send_header("Content-Disposition",
                            "attachment; filename=registry.json")
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)
        ctx.audit("отладка: скачан реестр.json", {"байт": len(data)},
                  handler=handler)
        return handler._SENT

    # ── Данные модулей (kv-файлы) ────────────────────────────────────
    def _kv_path(handler, parts):
        rel = "/".join(_unq(x) for x in (parts or []))
        p = os.path.normpath(os.path.join(store.mod_data, rel))
        base = os.path.normpath(store.mod_data)
        try:
            if os.path.commonpath([p, base]) != base:
                return None
        except ValueError:
            return None
        return p if os.path.isfile(p) else None

    @ctx.add_route("GET", "/debug/kv/", access="staff")
    def debug_kv(handler, params):
        p = _kv_path(handler, params.get("_parts"))
        if not p:
            return _err(handler, "файл не найден", "/debug")
        rel = os.path.relpath(p, store.mod_data).replace("\\", "/")
        err = _q(handler, params, "err")
        err_msg = ('<div class="error"><p>%s</p></div>' % _e(err)) if err else ""
        try:
            with open(p, encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError) as ex:
            return _err(handler, "файл не читается: %s" % ex, "/debug")
        body = (
            '<p><a href="/debug">Отладка</a></p>' + BANNER + err_msg +
            '<form method="post" action="/debug/kvsave" class="staff-card">'
            '<h2><code>%s</code></h2>'
            '<input type="hidden" name="rel" value="%s">'
            '<p><label><textarea name="text" rows="20" '
            'style="font-family:monospace;width:100%%">%s</textarea>'
            '</label></p>'
            '<p><button>💾 Сохранить файл</button></p></form>'
        ) % (_e(rel), _e(rel), _e(text))
        return ctx.render_page("Отладка: %s" % rel, body, staff=True)

    @ctx.add_route("POST", "/debug/kvsave", access="staff")
    def debug_kvsave(handler, params):
        data = handler._parse_post()
        rel = data.get("rel", "")
        p = os.path.normpath(os.path.join(store.mod_data, rel))
        base = os.path.normpath(store.mod_data)
        try:
            inside = os.path.commonpath([p, base]) == base
        except ValueError:
            inside = False
        if not inside or not os.path.isfile(p):
            return _err(handler, "файл не найден", "/debug")
        text = data.get("text", "")
        if rel.lower().endswith(".json"):
            try:
                json.loads(text)
            except ValueError as ex:
                return _err(handler, "JSON: %s" % ex,
                            "/debug/kv/%s" % _uq(rel))
        with open(p, "wb") as f:
            f.write(text.encode("utf-8"))
        ctx.audit("отладка: сохранён файл модуля",
                  {"файл": rel, "байт": len(text.encode("utf-8"))},
                  handler=handler)
        handler._redirect("/debug/kv/%s" % _uq(rel))
        return handler._SENT

    ctx.log("загружен: режим отладки (/debug) — полный доступ к реестру")
