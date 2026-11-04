# -*- coding: utf-8 -*-
"""Модуль «Резервная копия».

- При каждом запуске сервера автоматически сохраняет архив всего
  хранилища в папку «данные/бэкап» (хранятся последние N копий).
- Кнопка «💾 Скачать резервную копию» на главной панели преподавателя —
  тот же архив (реестр, раздатка, сдачи с результатами, лог) скачивается
  на лету одним файлом.

Модуль самодостаточен: включается/выключается на панели /_modules,
настройки (сколько копий хранить, делать ли автокопию при старте) —
в «модуль.json».
"""
import os
import urllib.parse
import zipfile
from datetime import datetime


def _e(v):
    import html
    return html.escape(str(v), quote=True)


def register(ctx):
    try:
        keep_n = max(1, int(ctx.settings.get("хранить", 3)))
    except (TypeError, ValueError):
        keep_n = 3
    on_start = bool(ctx.settings.get("при_старте", True))

    root = os.path.abspath(ctx._core.store.root)
    bak_dir = os.path.join(root, "бэкап")

    def _build():
        """Собрать zip всего хранилища (кроме папки «бэкап» и *.tmp)."""
        import io as _io
        buf = _io.BytesIO()
        bak_abs = os.path.abspath(bak_dir)
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for dirpath, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs
                           if os.path.abspath(os.path.join(dirpath, d))
                           != bak_abs]
                for fn in files:
                    if fn.endswith(".tmp"):
                        continue
                    p = os.path.join(dirpath, fn)
                    zf.write(p,
                             os.path.relpath(p, root).replace("\\", "/"))
        return buf.getvalue()

    def _rotate():
        """Оставить только последние keep_n архивов."""
        try:
            zips = sorted(os.path.join(bak_dir, x)
                          for x in os.listdir(bak_dir)
                          if x.endswith(".zip"))
            while len(zips) > keep_n:
                os.remove(zips.pop(0))
        except OSError:
            pass

    def _auto_backup():
        try:
            os.makedirs(bak_dir, exist_ok=True)
            name = "бэкап-%s.zip" % datetime.now().strftime("%Y%m%d-%H%M%S")
            with open(os.path.join(bak_dir, name), "wb") as f:
                f.write(_build())
            _rotate()
            ctx.log("автокопия сохранена: %s" % name)
        except Exception as ex:
            ctx.log("автокопия не удалась: %s" % ex)

    if on_start:
        _auto_backup()

    # ── Карточка на главной панели ───────────────────────────────────
    def _backup_card(**kw):
        items = []
        try:
            items = sorted((x for x in os.listdir(bak_dir)
                            if x.endswith(".zip")), reverse=True)
        except OSError:
            pass
        lst = ""
        if items:
            rows = "".join("<li>%s</li>" % _e(x) for x in items[:keep_n])
            lst = '<ul class="hint">%s</ul>' % rows
        return (
            '<details><summary>💾 Резервная копия</summary>'
            '<div class="staff-card">'
            '<p class="hint">Архив всего хранилища: реестр, раздатка, '
            'сдачи (файлы и результаты), журнал действий. При каждом '
            'запуске сервера копия автоматически сохраняется в папку '
            '«данные/бэкап» (хранятся последние %d).</p>%s'
            '<p><a class="btn" href="/staff/backup">💾 Скачать резервную '
            'копию сейчас</a></p></div></details>') % (keep_n, lst)

    ctx.on("staff.home_cards", _backup_card)

    # ── Скачать копию (.zip) ─────────────────────────────────────────
    @ctx.add_route("GET", "/staff/backup", access="staff")
    def download_backup(handler, params):
        data = _build()
        fname = "works-core-бэкап-%s.zip" % datetime.now().strftime(
            "%Y-%m-%d_%H%M%S")
        handler.send_response(200)
        handler.send_header("Content-Type", "application/zip")
        handler.send_header(
            "Content-Disposition",
            "attachment; filename*=UTF-8''" + urllib.parse.quote(fname))
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)
        ctx.audit("скачана резервная копия", {"размер": len(data)},
                  handler=handler)
        return handler._SENT

    ctx.log("загружен: резервная копия (автокопия при старте + скачивание)")
