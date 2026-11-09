# -*- coding: utf-8 -*-
"""Баг-репорты: студент сообщает о проблеме прямо из СДО.

Студент: плавающая кнопка «🐞 Баг» (не видна преподавателю) на любой
странице СДО → форма (что сломалось, что делал, скриншот) → POST /bugrep.
К репорту автоматически прикрепляются страница, студент (ФИО, группа),
время, браузер и IP — разбирать быстрее.

Преподаватель: плавающая плашка «🐞 Баг-репорты (N новых)» на
staff-страницах → /bugrep: список, статусы (новый → в работе →
решён/отклонён), удаление, просмотр скриншотов.

Хранение: данные/модули/bugrep/баги.json (атомарная запись),
скриншоты рядом. Всё живёт в модуле — обновляется через CI без
перезапуска сервера.
"""
import html
import os
import threading
from datetime import datetime

MAX_SHOT = 5 * 1024 * 1024  # 5 МБ на скриншот
SHOTS = {"png", "jpg", "jpeg", "webp", "gif"}
MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "webp": "image/webp", "gif": "image/gif"}
STATUSES = ["новый", "в работе", "решён", "отклонён"]

# Цвет плашек статуса
_STATUS_CLS = {"новый": "#b3261e", "в работе": "#b26a00",
               "решён": "#1a7a2a", "отклонён": "#666"}


def register(ctx):
    _lock = threading.Lock()

    def _e(v):
        return html.escape(str(v if v is not None else ""), quote=True)

    def _load():
        return ctx.kv_load("баги.json", [])

    def _save(items):
        ctx.kv_save("баги.json", items)

    def _next_id(items):
        return max((b.get("id", 0) for b in items), default=0) + 1

    # ── фрагмент в <head>: кнопка студента / плашка преподавателя ────
    def page_head(**kw):
        with _lock:
            new_n = sum(1 for b in _load() if b.get("статус") == "новый")
        return _FRAGMENT % {"new": new_n}

    ctx.on("page.head", page_head)

    # ── студент отправляет репорт ────────────────────────────────────
    @ctx.add_route("POST", "/bugrep", access="any")
    def bugrep_post(handler, params):
        data = handler._parse_post()
        title = (data.get("title") or "").strip()
        desc = (data.get("desc") or "").strip()
        page_url = (data.get("page") or "").strip()
        nxt = (data.get("next") or "/").strip()
        if not nxt.startswith("/") or nxt.startswith("//"):
            nxt = "/"
        if not title or not desc:
            handler._redirect(nxt)
            return handler._SENT
        sid = ""
        try:
            sid = handler._student() or ""
        except Exception:
            sid = ""
        stu = ctx.get_student(sid) if sid else None
        rep = {
            "id": 0,  # заполним под блокировкой
            "время": datetime.now().isoformat(timespec="seconds"),
            "title": title[:200],
            "desc": desc[:4000],
            "страница": page_url[:300],
            "студент": sid,
            "фио": (stu or {}).get("fio", "") or "не залогинен",
            "группа": (stu or {}).get("group", ""),
            "браузер": (handler.headers.get("User-Agent") or "")[:200],
            "ip": handler.client_address[0],
            "статус": "новый",
            "скрин": "",
        }
        up = data.get("shot")
        if up is not None and getattr(up, "name", ""):
            ext = os.path.splitext(up.name)[1].lower().lstrip(".")
            blob = getattr(up, "data", b"") or b""
            if ext in SHOTS and blob and len(blob) <= MAX_SHOT:
                rep["_shot"] = (ext, blob)
        with _lock:
            items = _load()
            rep["id"] = _next_id(items)
            if "_shot" in rep:
                ext, blob = rep.pop("_shot")
                fn = "скрин-%d.%s" % (rep["id"], ext)
                try:
                    with open(os.path.join(ctx.data_dir, fn), "wb") as f:
                        f.write(blob)
                    rep["скрин"] = fn
                except OSError:
                    pass
            items.append(rep)
            _save(items)
        try:
            ctx.audit("баг-репорт #%d" % rep["id"], title[:100],
                      who=rep["фио"], handler=handler)
        except Exception:
            pass
        handler._send_html(_THANKS % (_e(nxt), _e(nxt)))
        return handler._SENT

    # ── преподаватель: список репортов ───────────────────────────────
    @ctx.add_route("GET", "/bugrep", access="staff")
    def bugrep_list(handler, params):
        items = sorted(_load(), key=lambda b: -b.get("id", 0))
        new_n = sum(1 for b in items if b.get("статус") == "новый")
        rows = ""
        for b in items:
            st = b.get("статус", "?")
            color = _STATUS_CLS.get(st, "#666")
            shot = ""
            if b.get("скрин"):
                shot = ('<a href="/bugrep/shot/%d" target="_blank" '
                        'rel="noopener">🖼 скрин</a>' % b["id"])
            nxt_btn = ""
            i = STATUSES.index(st) if st in STATUSES else -1
            if 0 <= i < len(STATUSES) - 1:
                nxt = STATUSES[i + 1]
                nxt_btn = (
                    '<form method="post" action="/bugrep/status" '
                    'style="display:inline">'
                    '<input type="hidden" name="id" value="%d">'
                    '<input type="hidden" name="status" value="%s">'
                    '<button class="btn-sm">→ %s</button></form> '
                ) % (b["id"], _e(nxt), _e(nxt))
            rows += (
                '<tr><td>#%d<br><span class="hint">%s</span></td>'
                '<td>%s <span class="hint">[%s]</span></td>'
                '<td style="max-width:420px"><b>%s</b>'
                '<details><summary>описание</summary>'
                '<p>%s</p>'
                '<p class="hint">Страница: %s<br>Браузер: %s<br>'
                'IP: %s</p></details></td>'
                '<td>%s</td>'
                '<td><span style="background:%s;color:#fff;'
                'border-radius:6px;padding:2px 8px;font-size:12px">%s</span>'
                '</td>'
                '<td style="white-space:nowrap">%s'
                '<form method="post" action="/bugrep/delete" '
                'style="display:inline" onsubmit="return confirm('
                "'Удалить репорт #%d?')\">"
                '<input type="hidden" name="id" value="%d">'
                '<button class="btn-sm btn-secondary" '
                'title="Удалить">🗑</button></form></td></tr>'
            ) % (b["id"], _e(b.get("время", "")),
                 _e(b.get("фио", "")), _e(b.get("группа", "")),
                 _e(b.get("title", "")),
                 _e(b.get("desc", "")).replace("\n", "<br>"),
                 _e(b.get("страница", "")) or "—",
                 _e(b.get("браузер", "")) or "—",
                 _e(b.get("ip", "")),
                 shot,
                 color, _e(st),
                 nxt_btn,
                 b["id"], b["id"])
        body = (
            '<div class="task-desc"><h2>🐞 Баг-репорты</h2>'
            '<p class="hint">Студенты отправляют проблемы кнопкой «🐞 Баг» '
            'на своих страницах. Новых: <b>%d</b> из %d.</p>'
            '<table class="staff-table"><tr><th>Репорт</th><th>Студент</th>'
            '<th>Что случилось</th><th>Файлы</th><th>Статус</th>'
            '<th>Действия</th></tr>%s</table>'
            '%s</div>'
        ) % (new_n, len(items),
             rows or '<tr><td colspan="6" class="hint">'
                     'Пока ни одного репорта.</td></tr>', "")
        return ctx.render_page("🐞 Баг-репорты", body, staff=True)

    # ── преподаватель: статус и удаление ─────────────────────────────
    @ctx.add_route("POST", "/bugrep/status", access="staff")
    def bugrep_status(handler, params):
        data = handler._parse_post()
        try:
            rid = int(data.get("id", 0))
        except (TypeError, ValueError):
            rid = 0
        status = data.get("status", "")
        if status in STATUSES:
            with _lock:
                items = _load()
                for b in items:
                    if b.get("id") == rid:
                        b["статус"] = status
                        b["время_статуса"] = datetime.now().isoformat(
                            timespec="seconds")
                        break
                _save(items)
            try:
                ctx.audit("баг-репорт #%d → %s" % (rid, status), "",
                          handler=handler)
            except Exception:
                pass
        handler._redirect("/bugrep")
        return handler._SENT

    @ctx.add_route("POST", "/bugrep/delete", access="staff")
    def bugrep_delete(handler, params):
        data = handler._parse_post()
        try:
            rid = int(data.get("id", 0))
        except (TypeError, ValueError):
            rid = 0
        with _lock:
            items = _load()
            gone = None
            kept = []
            for b in items:
                if b.get("id") == rid:
                    gone = b
                else:
                    kept.append(b)
            if gone is not None:
                _save(kept)
        if gone is not None and gone.get("скрин"):
            try:
                os.remove(os.path.join(ctx.data_dir, gone["скрин"]))
            except OSError:
                pass
        if gone is not None:
            try:
                ctx.audit("баг-репорт #%d удалён" % rid,
                          gone.get("title", ""), handler=handler)
            except Exception:
                pass
        handler._redirect("/bugrep")
        return handler._SENT

    # ── преподаватель: скриншот ──────────────────────────────────────
    @ctx.add_route("GET", "/bugrep/shot/", access="staff")
    def bugrep_shot(handler, params):
        try:
            rid = int((params.get("_parts") or [""])[0])
        except (TypeError, ValueError):
            rid = 0
        rep = next((b for b in _load() if b.get("id") == rid), None)
        fn = (rep or {}).get("скрин", "")
        path = os.path.join(ctx.data_dir, fn) if fn else ""
        if not fn or not os.path.isfile(path):
            handler._send_text(404, "Скриншот не найден")
            return handler._SENT
        ext = os.path.splitext(fn)[1].lower().lstrip(".")
        with open(path, "rb") as f:
            handler._send_response(200, MIME.get(ext, "application/"
                                                 "octet-stream"),
                                   f.read(), encode=False)
        return handler._SENT


_THANKS = (
    '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
    '<meta http-equiv="refresh" content="2;url=%s">'
    '<title>Баг отправлен</title></head>'
    '<body style="font-family:system-ui,sans-serif;text-align:center;'
    'padding-top:14vh;background:#f6f7f9">'
    '<div style="font-size:46px">🐞✅</div>'
    '<h2 style="margin:8px 0 4px">Спасибо, баг записан!</h2>'
    '<p style="color:#555">Инженеры посмотрят. Через пару секунд вы '
    'вернётесь на страницу…</p>'
    '<p><a href="%s">Вернуться сейчас</a></p></body></html>'
)

_FRAGMENT = (
    '<style>'
    '.wc-bug-btn{position:fixed;right:18px;bottom:18px;z-index:9998;'
    'border:none;border-radius:999px;padding:10px 16px;font-size:14px;'
    'background:#8a1f1f;color:#fff;cursor:pointer;'
    'box-shadow:0 4px 12px rgba(0,0,0,.25)}'
    '.wc-bug-btn:hover{filter:brightness(1.15)}'
    '.wc-bug-staff{position:fixed;right:18px;bottom:18px;z-index:9998;'
    'display:inline-block;background:#1f4e8a;color:#fff;'
    'border-radius:999px;padding:10px 16px;font-size:14px;'
    'text-decoration:none;box-shadow:0 4px 12px rgba(0,0,0,.25)}'
    '.wc-bug-modal{position:fixed;inset:0;z-index:9999;display:none;'
    'background:rgba(0,0,0,.45)}'
    '.wc-bug-modal.open{display:block}'
    '.wc-bug-box{max-width:520px;margin:8vh auto;background:#fff;'
    'border-radius:12px;padding:20px 22px;font-family:inherit}'
    '.wc-bug-box h3{margin:0 0 6px}'
    '.wc-bug-box textarea,.wc-bug-box input[type=text]{width:100%%;'
    'box-sizing:border-box;padding:8px 10px;border:1px solid #ccc;'
    'border-radius:8px;font:inherit}'
    '.wc-bug-box label{display:block;margin:10px 0 4px;font-weight:600}'
    '</style>'
    '<div class="wc-bug-modal" id="wc-bug-modal">'
    '<form method="post" action="/bugrep" enctype="multipart/form-data" '
    'class="wc-bug-box">'
    '<h3>🐞 Сообщить о баге</h3>'
    '<p class="hint">Что-то работает не так? Опишите — разберёмся быстрее.'
    '</p>'
    '<label>Что сломалось?</label>'
    '<input type="text" name="title" required maxlength="200">'
    '<label>Что вы делали и что произошло?</label>'
    '<textarea name="desc" rows="4" required maxlength="4000"></textarea>'
    '<label>Скриншот (необязательно)</label>'
    '<input type="file" name="shot" accept="image/*">'
    '<input type="hidden" name="page" id="wc-bug-page">'
    '<input type="hidden" name="next" id="wc-bug-next">'
    '<p style="margin:14px 0 0">'
    '<button class="btn">Отправить</button> '
    '<button type="button" class="btn btn-secondary" '
    'id="wc-bug-close">Отмена</button></p>'
    '</form></div>'
    '<script>'
    '(function(){'
    'function boot(){'
    'var staff=document.body&&'
    'document.body.classList.contains("staff");'
    'if(staff){'
    'var a=document.createElement("a");'
    'a.href="/bugrep";a.className="wc-bug-staff";'
    'a.textContent="🐞 Баг-репорты"+(%(new)s?" (%(new)s новых)":"");'
    'document.body.appendChild(a);return;}'
    'var b=document.createElement("button");'
    'b.type="button";b.className="wc-bug-btn";'
    'b.title="Сообщить о баге";b.textContent="🐞 Баг";'
    'b.addEventListener("click",function(){'
    'document.getElementById("wc-bug-page").value=location.href;'
    'document.getElementById("wc-bug-next").value='
    'location.pathname+location.search;'
    'document.getElementById("wc-bug-modal").classList.add("open");});'
    'document.body.appendChild(b);'
    'var m=document.getElementById("wc-bug-modal");'
    'document.getElementById("wc-bug-close")'
    '.addEventListener("click",function(){m.classList.remove("open")});'
    'm.addEventListener("click",function(e){'
    'if(e.target===m)m.classList.remove("open")});'
    '}'
    'if(document.readyState==="loading")'
    'document.addEventListener("DOMContentLoaded",boot);'
    'else boot();'
    '})();'
    '</script>'
)
