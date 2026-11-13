# -*- coding: utf-8 -*-
"""Модуль «Здоровье сервера»: состояние, нагрузка и данные одним взглядом.

- Карточка «💚 Сервер» на главной панели преподавателя: аптайм, диск,
  проблемные модули.
- /health/ — подробная страница: сервер (аптайм, порт, PID, Python, ОС,
  потоки, сессии), диск и объёмы, сводка данных (курсы, занятия, задания,
  студенты, сдачи, версии), таблица модулей с состояниями.
- /health/api — JSON для внешнего мониторинга (доступ открыт): полный
  снимок — преподавателю или по токену из настроек (?token=...),
  остальным — только «жив ли сервер» (без деталей).

Только GET, данных не меняет. Тяжёлые замеры (размер хранилища, диск)
кэшируются на минуту, чтобы карточка панели не нагружала сервер.
"""
import html
import os
import platform
import secrets
import shutil
import socket
import sys
import threading
import time
import urllib.parse

_START = time.time()   # аптайм считаем с загрузки модулей (= старта сервера)
_TTL = 60.0            # кэш тяжёлых замеров, сек
_cache = {}
_cache_lock = threading.Lock()


def _e(v):
    return html.escape(str(v), quote=True)


def _cached(key, fn):
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < _TTL:
            return hit[1]
    val = fn()
    with _cache_lock:
        _cache[key] = (now, val)
    return val


def _dur(sec):
    """«2 д 3 ч 15 мин» из секунд."""
    s = int(sec)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    out = []
    if d:
        out.append("%d д" % d)
    if h:
        out.append("%d ч" % h)
    out.append("%d мин" % max(s // 60, 0))
    return " ".join(out)


def _ago(ts):
    if not ts:
        return "—"
    d = time.time() - ts
    if d < 90:
        return "только что"
    return _dur(d) + " назад"


def _size(n):
    n = float(n or 0)
    if n < 1024:
        return "%d Б" % n
    for unit, k in (("КБ", 1024), ("МБ", 1024 ** 2), ("ГБ", 1024 ** 3)):
        if n < k * 1024:
            return ("%.1f %s" % (n / k, unit)).replace(".", ",")
    return "%.1f ТБ" % (n / (1024 ** 4))


def _tree_size(path):
    total = 0
    for dp, _dn, fn in os.walk(path):
        for f in fn:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return total


def _safe_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _min_disk(ctx):
    try:
        return float(ctx.settings.get("мин_диск_гб", 2))
    except (TypeError, ValueError):
        return 2.0


def _disk_free_gb(ctx):
    try:
        return shutil.disk_usage(ctx._core.store.root).free / (1024 ** 3)
    except OSError:
        return None


def _broken_modules(ctx):
    """Модули с проблемами: сбой, битый манифест, отключён (не тот api)."""
    return [m for m in ctx.list_modules()
            if m.get("state") not in ("ok", "выключен")]


def _snapshot(ctx, handler):
    """Полный снимок состояния сервера (тяжёлое — из кэша)."""
    core = ctx._core
    store = core.store
    srv = getattr(handler, "server", None)
    db = store.db if isinstance(store.db, dict) else {}
    subs = db.get("сдачи") or {}
    students = db.get("студенты") or []
    brigades = {s.get("бригада", "") for s in students if s.get("бригада")}
    statuses = {}
    versions = 0
    for sub in subs.values():
        st = sub.get("status") or "сдано"
        statuses[st] = statuses.get(st, 0) + 1
        versions += len(sub.get("versions") or [])
    mods = ctx.list_modules()
    broken = [m for m in mods if m.get("state") not in ("ok", "выключен")]
    free_gb = _disk_free_gb(ctx)
    try:
        total_gb = shutil.disk_usage(store.root).total / (1024 ** 3)
    except OSError:
        total_gb = 0.0
    sessions = getattr(srv, "sessions", None) or {}
    last_t = max([v.get("t", 0) for v in sessions.values()] or [0])
    now = time.time()
    status = "ok"
    if broken or (free_gb is not None and free_gb < _min_disk(ctx)):
        status = "внимание"
    return {
        "ok": True,
        "status": status,
        "uptime": int(now - _START),
        "started": time.strftime("%d.%m.%Y %H:%M:%S", time.localtime(_START)),
        "port": getattr(srv, "_port", "?"),
        "pid": os.getpid(),
        "python": "%d.%d.%d" % sys.version_info[:3],
        "platform": "%s %s" % (platform.system(), platform.release()),
        "hostname": socket.gethostname(),
        "threads": threading.active_count(),
        "sessions": len(sessions),
        "sessions_last": int(now - last_t) if last_t else None,
        "rev": getattr(store, "rev", 0),
        "disk_free_gb": round(free_gb, 2) if free_gb is not None else None,
        "disk_total_gb": round(total_gb, 2),
        "store_size": _cached("store_size", lambda: _tree_size(store.root)),
        "subs_size": _cached("subs_size", lambda: _tree_size(store.subs)),
        "reg_size": _safe_size(store.reg),
        "counts": {
            "courses": len(db.get("курсы") or []),
            "lessons": len(db.get("занятия") or []),
            "tasks": len(db.get("задания") or []),
            "students": len(students),
            "brigades": len(brigades),
            "submissions": len(subs),
            "versions": versions,
            "statuses": statuses,
        },
        "modules": [{"id": m.get("id"), "name": m.get("name") or m.get("id"),
                     "state": m.get("state"), "reason": m.get("reason") or ""}
                    for m in mods],
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def _minimal(ctx):
    """Короткий ответ для внешнего мониторинга без права на детали."""
    free = _disk_free_gb(ctx)
    status = "ok"
    if _broken_modules(ctx) or (free is not None and free < _min_disk(ctx)):
        status = "внимание"
    return {"ok": True, "status": status, "uptime": int(time.time() - _START)}


def register(ctx):
    # ── JSON для внешнего мониторинга: открыт, но полный снимок —
    #    только преподавателю или по токену из настроек ──
    @ctx.add_route("GET", "/health/api", access="any")
    def api(handler, params):
        want = str(ctx.settings.get("токен") or "")
        full = handler._is_staff()
        if want and not full:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
            got = (qs.get("token") or [""])[0]
            try:
                full = secrets.compare_digest(got, want)
            except TypeError:          # не-ASCII токен — простое сравнение
                full = got == want
        if full:
            handler._send_json(200, _snapshot(ctx, handler))
        else:
            handler._send_json(200, _minimal(ctx))
        return handler._SENT

    # ── подробная страница ──
    @ctx.add_route("GET", "/health/", access="staff")
    def page(handler, params):
        snap = _snapshot(ctx, handler)
        c = snap["counts"]
        dot = "🟠" if snap["status"] != "ok" else "💚"

        rows = "".join(
            '<tr><td>%s</td><td><b>%s</b></td></tr>' % (k, v) for k, v in (
                ("Состояние", "%s работает" % dot),
                ("Аптайм", _e(_dur(snap["uptime"]))),
                ("Запущен", _e(snap["started"])),
                ("Адрес", ":%s" % _e(snap["port"])),
                ("PID", _e(snap["pid"])),
                ("Компьютер", _e(snap["hostname"])),
                ("Python", _e(snap["python"])),
                ("ОС", _e(snap["platform"])),
                ("Потоков", _e(snap["threads"])),
                ("Сессий", _e(snap["sessions"])),
                ("Последняя активность", _e(_ago(snap["sessions_last"]))),
                ("Ревизия реестра", _e(snap["rev"])),
            ))
        srv_html = ('<div class="staff-card"><h2>🖥 Сервер</h2>'
                    '<table class="staff-table">%s</table></div>' % rows)

        bar = ""
        if snap["disk_total_gb"] and snap["disk_free_gb"] is not None:
            used_pct = 100.0 * (1 - snap["disk_free_gb"] / snap["disk_total_gb"])
            color = "#ff9800" if snap["disk_free_gb"] < _min_disk(ctx) else "#4caf50"
            bar = ('<div style="background:rgba(127,127,127,.25);height:14px;'
                   'border-radius:7px;overflow:hidden;margin:6px 0 2px">'
                   '<div style="width:%.1f%%;height:100%%;background:%s"></div>'
                   '</div>' % (used_pct, color))
        if snap["disk_free_gb"] is not None:
            disk_note = "свободно %s из %s" % (
                _size(snap["disk_free_gb"] * (1024 ** 3)),
                _size(snap["disk_total_gb"] * (1024 ** 3)))
        else:
            disk_note = "н/д"
        disk_html = (
            '<div class="staff-card"><h2>💾 Диск и объёмы</h2>' + bar +
            '<p class="hint">Хранилище: %s (%s)</p>'
            '<table class="staff-table"><tr><th>Что</th><th>Объём</th></tr>%s'
            '</table></div>'
            % (_e(ctx._core.store.root), disk_note,
               "".join('<tr><td>%s</td><td><b>%s</b></td></tr>' % (k, v)
                       for k, v in (
                           ("Весь реестр (данные/)", _size(snap["store_size"])),
                           ("реестр.json", _size(snap["reg_size"])),
                           ("Папка сдач", _size(snap["subs_size"]))))))
        sts = " · ".join("%s: %d" % (_e(k), v)
                         for k, v in sorted(c["statuses"].items())) or "нет"
        data_html = (
            '<div class="staff-card"><h2>🗂 Данные</h2>'
            '<p>Курсов <b>%d</b> · занятий <b>%d</b> · заданий <b>%d</b></p>'
            '<p>Студентов <b>%d</b> · бригад <b>%d</b></p>'
            '<p>Сдач <b>%d</b> (версий <b>%d</b>), статусы: %s</p></div>'
            % (c["courses"], c["lessons"], c["tasks"], c["students"],
               c["brigades"], c["submissions"], c["versions"], sts))

        rows = ""
        for m in snap["modules"]:
            bad = m["state"] not in ("ok", "выключен")
            mark = ' style="color:#e65100"' if bad else ""
            rows += ('<tr><td>%s</td><td>%s</td><td%s>%s</td>'
                     '<td class="hint">%s</td></tr>'
                     % (_e(m["id"]), _e(m["name"]), mark, _e(m["state"]),
                        _e(m["reason"])))
        mods_html = (
            '<div class="staff-card"><h2>🧩 Модули: %d</h2>'
            '<table class="staff-table"><tr><th>id</th><th>Название</th>'
            '<th>Состояние</th><th>Детали</th></tr>%s</table></div>'
            % (len(snap["modules"]), rows))

        tok = str(ctx.settings.get("токен") or "")
        tok_html = ("задан — полный снимок снаружи: "
                    "<code>/health/api?token=…</code>"
                    if tok else
                    "не задан — снаружи только минимум (жив ли сервер); "
                    "задайте ключ «токен» в настройках модуля на /_modules")
        api_html = (
            '<div class="staff-card"><h2>📡 Мониторинг</h2>'
            '<p><code>GET /health/api</code> — JSON. Полный снимок — с сессией '
            'преподавателя или по токену: %s</p>'
            '<p class="hint">Пример: curl "http://localhost:%s/health/api?token=СЕКРЕТ"</p>'
            '</div>' % (tok_html, _e(snap["port"])))

        body = ('<p><a href="/staff">← Панель</a> · '
                '<a class="btn btn-sm btn-secondary" href="/health/?r=%d">'
                '🔄 Обновить</a></p>%s%s%s%s%s'
                % (int(time.time()), srv_html, disk_html, data_html,
                   mods_html, api_html))
        return ctx.render_page("Здоровье сервера", body, staff=True,
                               extra_head='<meta http-equiv="refresh" content="60">')

    # ── карточка на главной панели ──
    def _card(**kw):
        if not ctx.settings.get("карточка", True):
            return ""
        free = _disk_free_gb(ctx)
        broken = _broken_modules(ctx)
        warn = []
        if broken:
            warn.append("модулей с ошибками: %d" % len(broken))
        if free is not None and free < _min_disk(ctx):
            warn.append("мало места на диске")
        parts = ['Сервер работает %s' % _dur(time.time() - _START)]
        if free is not None:
            parts.append('на диске свободно %.1f ГБ' % free)
        warn_html = ('<p class="error">⚠️ %s</p>' % _e("; ".join(warn))
                     if warn else "")
        return ('<div class="staff-card"><h2>%s Здоровье сервера</h2>'
                '<p>%s</p>%s'
                '<div class="staff-actions">'
                '<a href="/health/" class="btn btn-sm btn-secondary">Подробно</a>'
                '</div></div>') % ("🟠" if warn else "💚",
                                   _e(" · ".join(parts)), warn_html)

    ctx.on("staff.home_cards", _card)

    ctx.log("загружен: health (/health/, /health/api)")
