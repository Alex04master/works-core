# -*- coding: utf-8 -*-
"""HTTP-сервер ядра: маршрутизация, multipart, сессии, статика."""
import hashlib
import hmac
import http.server
import json
import mimetypes
import os
import secrets
import time
import urllib.parse
from datetime import datetime

from .core import _md, task_deadline


_mime = mimetypes.guess_type
_SENT = "___SENT___"  # маркер: ответ уже отправлен
SENT = _SENT  # экспорт для модулей


class Upload:
    """Загруженный файл (multipart): оригинальное имя + байты."""

    __slots__ = ("name", "data")

    def __init__(self, name, data):
        self.name = name or "file"
        self.data = data


DRAFT_JS = """<script>
(function(){
  var K='draft_'+location.pathname;
  if(/[?&]ok=1/.test(location.search)){try{localStorage.removeItem(K)}catch(e){}return}
  var f=document.querySelector('form.task-form');if(!f)return;
  try{
    var d=JSON.parse(localStorage.getItem(K)||'{}');
    for(var i=0;i<f.elements.length;i++){var el=f.elements[i];
      if(!el.name||el.type=='file'||el.type=='submit')continue;
      if(el.type=='radio'||el.type=='checkbox'){
        var v=d[el.name];
        el.checked=(v===undefined)?false:(Array.isArray(v)?v.indexOf(el.value)>=0:v===el.value);
      }else if(d[el.name]!==undefined){el.value=d[el.name];}
    }
  }catch(e){}
  function save(){
    try{
      var d={};new FormData(f).forEach(function(v,k){
        if(k=='task'||typeof v!='string')return;
        if(d[k]===undefined)d[k]=v;
        else if(Array.isArray(d[k]))d[k].push(v);
        else d[k]=[d[k],v];
      });
      localStorage.setItem(K,JSON.stringify(d));
    }catch(e){}
  }
  f.addEventListener('input',save);f.addEventListener('change',save);
})();
</script>"""


def _cd_param(text, param):
    """Параметр из Content-Disposition: name=... / filename=..."""
    for tok in text.split(";"):
        tok = tok.strip()
        if tok.lower().startswith(param + "="):
            v = tok[len(param) + 1:].strip()
            if v.startswith('"') and v.endswith('"') and len(v) >= 2:
                v = v[1:-1]
            return v.replace('\\"', '"')
    return ""


def _parse_multipart(body, boundary):
    """Минимальный парсер multipart/form-data (замена удалённого модуля cgi).

    Возвращает (поля, файлы): поля {имя: str | [str, ...]}, файлы {имя: Upload}.
    """
    fields = {}
    files = {}
    if not boundary:
        return fields, files
    delim = b"--" + boundary
    for part in body.split(delim):
        if not part or part.startswith(b"--"):
            continue
        p = part
        if p.startswith(b"\r\n"):
            p = p[2:]
        if p.endswith(b"\r\n"):
            p = p[:-2]
        if b"\r\n\r\n" not in p:
            continue
        head, _, content = p.partition(b"\r\n\r\n")
        disp = ""
        for line in head.split(b"\r\n"):
            text = line.decode("utf-8", "replace")
            if text.lower().startswith("content-disposition"):
                disp = text
        if not disp:
            continue
        name = _cd_param(disp, "name")
        if not name:
            continue
        fname = _cd_param(disp, "filename")
        if fname:
            files[name] = Upload(fname, content)
        else:
            val = content.decode("utf-8", "replace")
            prev = fields.get(name)
            if prev is None:
                fields[name] = val
            elif isinstance(prev, list):
                prev.append(val)
            else:
                fields[name] = [prev, val]
    return fields, files


class Router:
    """Простой роутер на основе префиксов."""

    def __init__(self):
        self.routes = []  # [(method, prefix, handler, access)]

    def add(self, method, path, handler=None, access="any"):
        assert access in ("any", "student", "staff"), "unknown access: " + access
        if handler is None:
            return lambda fn: self._register(method, path, fn, access)
        self._register(method, path, handler, access)

    def _register(self, method, path, handler, access):
        self.routes.append((method.upper(), path, handler, access))

    def match(self, method, path):
        method = method.upper()
        best = None
        best_access = "any"
        best_params = {}
        best_len = -1

        for m, prefix, handler, access in self.routes:
            if m not in (method, "ANY"):
                continue
            if path == prefix:
                return handler, access, {"_parts": []}
            if not path.startswith(prefix):
                continue
            rest = path[len(prefix):]
            if not rest:
                continue
            query = ""
            if "?" in rest:
                rest, query = rest.split("?", 1)
                query = urllib.parse.parse_qs(query)
            if not rest.startswith("/") and not prefix.endswith("/"):
                continue
            parts = rest.strip("/").split("/") if rest else []
            params = {"_parts": parts}
            if query:
                params.update(query)
            if len(prefix) > best_len:
                best = handler
                best_access = access
                best_params = params
                best_len = len(prefix)

        return best, best_access, best_params


class WorksHandler(http.server.BaseHTTPRequestHandler):
    _server_inst = None
    _router = None
    _core = None
    _SENT = _SENT  # доступен как self._SENT для модулей

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def _handle(self, method):
        try:
            # percent-encoding -> текст: браузер кодирует кириллицу
            # в путях (/scnfile/<комплект>, /materials/<файл>)
            path = urllib.parse.unquote(urllib.parse.urlparse(self.path).path)
            # Статика и материалы — до роутера: маршрут "/" (префикс,
            # оканчивающийся на "/") иначе перехватывает ВСЕ пути,
            # и core.css/файлы не отдаются вовсе.
            if path.startswith("/_static/") or path.startswith("/materials/"):
                self._serve_static(path)
                return
            handler, access, params = self._router.match(method, path)
            if not handler:
                self._serve_static(path)
                return
            if access == "staff" and not self._is_staff():
                self._send_html(self._serve_staff_login())
                return
            if access == "student" and not self._student():
                self._redirect("/_login?next=" + urllib.parse.quote(self.path))
                return
            try:
                result = handler(self, params)
            except Exception:
                import traceback
                traceback.print_exc()
                self._send_json(500, {"error": "внутренняя ошибка сервера"})
                return
            if result is _SENT:
                return  # ответ уже отправлен (редирект и т.п.)
            if result is None:
                self._send_text(500, "Internal error")
            elif isinstance(result, str):
                self._send_html(result)
            elif isinstance(result, dict):
                self._send_json(200, result)
            else:
                self._send_response(200, "text/html; charset=utf-8", str(result))
        except ConnectionError:
            pass
        except Exception:
            import traceback
            traceback.print_exc()
            try:
                self._send_text(500, "внутренняя ошибка сервера")
            except ConnectionError:
                pass

    def _sign_sid(self, sid):
        """Подписать id студента (HMAC) — защита от подделки куки."""
        mac = hmac.new(self._server_inst.secret, sid.encode("utf-8"),
                       hashlib.sha256).hexdigest()[:16]
        return sid + "." + mac

    def _student(self):
        c = self._cookie("student")
        if not c or "." not in c:
            return None
        sid, mac = c.rsplit(".", 1)
        good = hmac.new(self._server_inst.secret, sid.encode("utf-8"),
                        hashlib.sha256).hexdigest()[:16]
        if secrets.compare_digest(mac, good) and self._core.student(sid):
            return sid
        return None

    def _is_staff(self):
        token = self._cookie("staff_token")
        if not token:
            return False
        sess = self._server_inst.sessions.get(token)
        if not sess:
            return False
        now = time.time()
        if now - sess.get("t", 0) > self._server_inst.session_ttl:
            self._server_inst.sessions.pop(token, None)
            return False
        sess["t"] = now
        return True

    def _cookie(self, name):
        c = self.headers.get("Cookie", "")
        for part in c.split(";"):
            part = part.strip()
            if part.lower().startswith(name.lower() + "="):
                return urllib.parse.unquote(part[len(name) + 1:])
        return ""

    def _serve_staff_login(self):
        """Страница входа преподавателя (используется и как GET-маршрут)."""
        notice = ""
        if "err=limit" in self.path:
            notice = ('<div class="error">Слишком много попыток. '
                      "Подождите 10 минут.</div>")
        elif "err=1" in self.path:
            notice = '<div class="error">Неверный пароль.</div>'
        body = (
            '<form method="post" action="/_staff_login" class="login-form">'
            "<h2>Вход для преподавателя</h2>"
            + notice +
            '<p><label>Пароль: <input type="password" name="pass" required autofocus></label></p>'
            "<p><button>Войти</button></p>"
            '<p class="hint">Пароль задаётся при запуске: --pass ПАРОЛЬ</p>'
            "</form>")
        return self._core.page("Вход", body)

    def _serve_static(self, path):
        if path.startswith("/_static/"):
            local = os.path.join(self._server_inst.static_dir, path[9:])
        elif path.startswith("/materials/"):
            local = os.path.join(self._server_inst.core.store.mat, path[11:])
        else:
            self._send_text(404, "Not Found")
            return
        local = os.path.normpath(local)
        basedirs = [
            os.path.normpath(self._server_inst.static_dir),
            os.path.normpath(self._server_inst.core.store.mat)
        ]
        inside = False
        for b in basedirs:
            try:
                if os.path.commonpath([local, b]) == b:
                    inside = True
                    break
            except ValueError:
                pass
        if not inside:
            self._send_text(403, "Forbidden")
            return
        if not os.path.isfile(local):
            self._send_text(404, "Not Found")
            return
        mime, _ = _mime(local)
        with open(local, "rb") as f:
            self._send_response(200, mime or "application/octet-stream",
                                f.read(), encode=False)

    def _parse_post(self):
        ctype = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length > 0 else b""
        if "multipart/form-data" in ctype:
            boundary = ""
            for tok in ctype.split(";"):
                tok = tok.strip()
                if tok.lower().startswith("boundary="):
                    boundary = tok[9:].strip().strip('"')
            fields, files = _parse_multipart(body, boundary.encode("utf-8"))
            fields.update(files)
            return fields
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            text = ""
        if "application/json" in ctype:
            try:
                return json.loads(text)
            except ValueError:
                return {}
        try:
            return dict(urllib.parse.parse_qsl(text))
        except Exception:
            return {}

    def _send_response(self, code, content_type, data, encode=True):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        if isinstance(data, str) and encode:
            data = data.encode("utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if isinstance(data, str):
            self.wfile.write(data.encode("utf-8"))
        else:
            self.wfile.write(data)

    def _send_html(self, html):
        self._send_response(200, "text/html; charset=utf-8", html)

    def _send_text(self, code, text):
        self._send_response(code, "text/plain; charset=utf-8", text)

    def _send_json(self, code, obj):
        self._send_response(code, "application/json; charset=utf-8",
                            json.dumps(obj, ensure_ascii=False))

    def _redirect(self, url, extra_headers=None):
        """Перенаправление: 302 + Location (тело — meta-refresh для надёжности).

        extra_headers — список (name, value) для дополнительных заголовков
        (например, Set-Cookie). Передаются ПОСЛЕ send_response, но ДО
        end_headers, чтобы порядок заголовков в HTTP был корректным.
        """
        body = (
            "<!doctype html><meta charset=\"utf-8\">"
            "<meta http-equiv=\"refresh\" content=\"0;url=%s\">"
            "<title>Redirect</title><a href=\"%s\">Continue</a>") % (url, url)
        data = body.encode("utf-8")
        self.send_response(302)
        self.send_header("Location", url)
        # Дополнительные заголовки (например Set-Cookie) — после send_response
        for name, value in (extra_headers or []):
            self.send_header(name, value)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def _set_cookie(self, name, value, path="/", max_age=None, httponly=False):
        """Создать заголовок Set-Cookie (без отправки — возвращает строку)."""
        s = "%s=%s; Path=%s; SameSite=Lax" % (name, urllib.parse.quote(value), path)
        if max_age is not None:
            s += "; Max-Age=%d" % max_age
        if httponly:
            s += "; HttpOnly"
        return ("Set-Cookie", s)

    def log_message(self, format, *args):
        pass


class WorksServer(http.server.ThreadingHTTPServer):
    """HTTP-сервер ядра со встроенными маршрутами (потоковый)."""

    daemon_threads = True

    def __init__(self, core, host="", port=8080, static_dir="", passwd="",
                 no_pass=False):
        self.core = core
        self.static_dir = os.path.abspath(static_dir) if static_dir else ""
        self.passwd = passwd or ""
        self.no_pass = bool(no_pass)
        self.sessions = {}           # token -> {"t": время активности}
        self._fails = {}             # ip -> [время неудачных попыток входа]
        self.session_ttl = 8 * 3600  # срок жизни сессии преподавателя, сек
        self.secret = self._load_secret()
        self.pw_hash = None if self.no_pass else self._load_password_hash()
        self._port = port

        WorksHandler._server_inst = self
        WorksHandler._router = self._make_router()
        WorksHandler._core = core
        core.router = WorksHandler._router

        for method, path, handler, access in core.pending_routes:
            WorksHandler._router.add(method, path, handler, access)

        super().__init__((host, port), WorksHandler)

    def _load_secret(self):
        """Секрет для подписи кук студентов (переживает перезапуск)."""
        path = os.path.join(self.core.store.root, "_секрет.key")
        try:
            with open(path, "rb") as f:
                s = f.read().strip()
            if len(s) >= 32:
                return s
        except OSError:
            pass
        s = secrets.token_hex(32).encode("ascii")
        with open(path, "wb") as f:
            f.write(s)
        return s

    # ── Пароль преподавателя ──────────────────────────────────────────
    def _password_hash_path(self):
        return os.path.join(self.core.store.root, "_пароль.hash")

    def _load_password_hash(self):
        try:
            with open(self._password_hash_path(), encoding="ascii") as f:
                s = f.read().strip()
            if "$" in s and len(s) > 40:
                return s
        except OSError:
            pass
        return None

    @staticmethod
    def _hash_pw(plain, salt_hex):
        return hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"),
                                   bytes.fromhex(salt_hex), 60000).hex()

    def check_password(self, candidate):
        """Проверить пароль: no-pass / PBKDF2-хеш / пароль из CLI."""
        if self.no_pass:
            return True
        if self.pw_hash:
            salt, stored = self.pw_hash.split("$", 1)
            return secrets.compare_digest(self._hash_pw(candidate, salt),
                                          stored)
        if not self.passwd:
            return True
        return secrets.compare_digest(candidate.encode("utf-8"),
                                      self.passwd.encode("utf-8"))

    def set_password(self, plain):
        """Сменить пароль: PBKDF2-хеш сохраняется и переживает рестарт."""
        salt = secrets.token_hex(16)
        self.pw_hash = salt + "$" + self._hash_pw(plain, salt)
        self.passwd = plain
        with open(self._password_hash_path(), "w", encoding="ascii") as f:
            f.write(self.pw_hash)

    def _make_router(self):
        r = Router()

        @r.add("GET", "/_login")
        def login_page(handler, params):
            body = self._student_login_html(handler)
            return handler._core.page("Вход студента", body)

        @r.add("GET", "/_logout")
        def logout_student(handler, params):
            handler._redirect("/", [handler._set_cookie("student", "", max_age=0)])
            return _SENT

        @r.add("POST", "/_login")
        def login_post(handler, params):
            data = handler._parse_post()
            sid = data.get("student", "")
            if handler._core.student(sid):
                nxt = data.get("next", "/")
                if not nxt.startswith("/") or nxt.startswith("//"):
                    nxt = "/"
                cookie = handler._set_cookie("student", handler._sign_sid(sid),
                                             max_age=86400, httponly=True)
                handler._redirect(nxt, [cookie])
            else:
                handler._redirect("/_login?err=1")
            return _SENT

        @r.add("GET", "/_staff_logout")
        def staff_logout(handler, params):
            cookie = handler._set_cookie("staff_token", "", max_age=0,
                                         httponly=True)
            handler._redirect("/", [cookie])
            return _SENT

        @r.add("GET", "/_staff_login")
        def staff_login_page(handler, params):
            return handler._serve_staff_login()

        @r.add("POST", "/_staff_login")
        def staff_login(handler, params):
            ip = handler.client_address[0]
            now = time.time()
            fails = self._fails.setdefault(ip, [])
            fails[:] = [t for t in fails if now - t < 600]
            if len(fails) >= 5:
                handler._redirect("/_staff_login?err=limit")
                return _SENT
            data = handler._parse_post()
            ok = self.check_password(data.get("pass", ""))
            if ok:
                token = secrets.token_hex(16)
                self.sessions[token] = {"t": now}
                self._fails.pop(ip, None)
                cookie = handler._set_cookie("staff_token", token,
                                             max_age=self.session_ttl,
                                             httponly=True)
                handler._redirect("/staff", [cookie])
            else:
                fails.append(now)
                handler._redirect("/_staff_login?err=1")
            return _SENT

        @r.add("GET", "/_modules", access="staff")
        def modules_page(handler, params):
            if not handler._is_staff():
                return handler._core.page("Доступ запрещён",
                                          "<p>Только для преподавателя.</p>", staff=True)

            sorted_mods = handler._core.sort_modules(handler._core.modules)

            dnd_js = """
            <script>
            function toggleMod(id) {
              fetch('/_modules/toggle/' + id, {method:'POST'})
                .then(r => r.json())
                .then(d => { if(d.ok) location.reload(); });
            }
            function saveOrder() {
              var rows = Array.from(document.querySelectorAll('.mod-row'));
              var order = rows.map(function(r) { return r.dataset.modId; });
              fetch('/_modules/reorder', {
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body:JSON.stringify({order:order})
              }).then(function(r){ return r.json(); }).then(function(d){
                var msg = document.getElementById('order-msg');
                msg.style.display='block';
                setTimeout(function(){ msg.style.display='none'; }, 2000);
              });
            }
            document.addEventListener('DOMContentLoaded', function() {
              var rows = Array.from(document.querySelectorAll('.mod-row'));
              var dragSrc = null;
              rows.forEach(function(r) {
                var h = r.querySelector('.drag-handle');
                if (!h) return;
                h.addEventListener('mousedown', function(e) {
                  dragSrc = r; r.style.opacity='0.5';
                  e.preventDefault();
                });
              });
              document.addEventListener('mouseup', function() {
                if (dragSrc) { dragSrc.style.opacity='1'; dragSrc = null; }
              });
              document.addEventListener('mousemove', function(e) {
                if (!dragSrc) return;
                var rows2 = Array.from(document.querySelectorAll('.mod-row'));
                var target = null;
                rows2.forEach(function(r) {
                  if (r == dragSrc) return;
                  var rect = r.getBoundingClientRect();
                  if (e.clientY > rect.top && e.clientY < rect.bottom) target = r;
                });
                if (target) {
                  var tbody = dragSrc.parentNode;
                  var idx_src = rows2.indexOf(dragSrc);
                  var idx_tgt = rows2.indexOf(target);
                  if (idx_src < idx_tgt) {
                    tbody.insertBefore(dragSrc, target.nextSibling);
                  } else {
                    tbody.insertBefore(dragSrc, target);
                  }
                  saveOrder();
                }
              });
            });
            </script>"""

            dnd_css = (
                "<style>"
                ".drag-handle{cursor:grab;color:#8a9aa8;font-size:18px;user-select:none;"
                "padding:4px 8px;border-radius:4px;}"
                ".drag-handle:hover{background:#e5e2dd;color:#4a5a6a;}"
                ".toggle{position:relative;display:inline-block;width:40px;height:22px;}"
                ".toggle input{opacity:0;width:0;height:0;}"
                ".slider{position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;"
                "background:#ccc;transition:.3s;border-radius:11px;}"
                ".slider:before{position:absolute;content:'';height:16px;width:16px;"
                "left:3px;bottom:3px;background:#fff;border-radius:50%%;transition:.3s;}"
                ".toggle input:checked+.slider{background:#2a8a3a;}"
                ".toggle input:checked+.slider:before{transform:translateX(18px);}"
                ".mod-icon{text-align:center;font-size:16px;}"
                ".mod-toggle{text-align:center;}"
                ".mod-reason{color:#6a7a88;font-size:13px;max-width:200px;}"
                "#order-msg{display:none;position:fixed;bottom:20px;right:20px;"
                "background:#1a7a2a;color:#fff;padding:8px 16px;border-radius:6px;"
                "font-size:13px;z-index:99;}"
                "</style>")

            rows = ""
            for m in sorted_mods:
                state = m.get("state", "?")
                reason = m.get("reason", "")
                mod_id = m["id"]
                enabled = handler._core.is_module_enabled(mod_id)

                state_icons = {"ok": "✅", "выключен": "⏸️",
                               "отключён": "⚠️", "сбой": "❌",
                               "битый манифест": "💥"}
                icon = state_icons.get(state, "❓")

                toggle = ""
                if state == "ok" or state == "выключен":
                    checked = ' checked' if enabled else ''
                    toggle = ('<label class="toggle">'
                              '<input type="checkbox" %s onchange="toggleMod(\'%s\')">'
                              '<span class="slider"></span></label>') % (checked, mod_id)

                reason_html = (' <span class="reason">%s</span>' % reason) if reason else ""
                rows += (
                    '<tr class="mod-row" data-mod-id="%s">'
                    '<td class="mod-icon">%s</td>'
                    '<td><span class="drag-handle">⋮</span> %s</td>'
                    '<td><code>%s</code></td>'
                    '<td class="state-%s">%s</td>'
                    '<td class="mod-toggle">%s</td>'
                    '<td class="mod-reason">%s</td></tr>') % (
                        mod_id, icon, m.get("name", m["id"]), mod_id,
                        state.replace(" ", "-"), state,
                        toggle, reason_html)

            body = (
                dnd_css
                + '<div id="order-msg">Порядок сохранён</div>'
                + '<table class="module-table">'
                  '<tr><th></th><th>Модуль</th><th>ID</th><th>Статус</th><th>Вкл</th><th></th></tr>'
                  '%s</table>'
                  '<p class="hint">Всего: %d. Перетаскивайте строки за ⋮, чтобы изменить порядок. '
                  'Выключение — после перезапуска.</p>') % (
                    rows, len(handler._core.modules))
            return handler._core.page("Модули", body, staff=True, extra_head=dnd_js + dnd_css)
        @r.add("POST", "/_modules/toggle/", access="staff")
        def toggle_module(handler, params):
            parts = params.get("_parts", [])
            mod_id = parts[0] if parts else ""
            if not mod_id:
                handler._send_json(400, {"error": "no module id"})
                return _SENT
            enabled = handler._core.toggle_module(mod_id)
            handler._send_json(200, {"ok": True, "mod_id": mod_id,
                                     "enabled": enabled})
            return _SENT

        @r.add("GET", "/")
        def home(handler, params):
            sid = handler._student()
            if not sid:
                handler._redirect("/_login?next=%2F")
                return _SENT
            courses = handler._core.courses(sid)
            if not courses:
                return handler._core.page("Нет курсов", "<p>Нет доступных курсов.</p>")
            items = "".join(
                '<li><a href="/course/%s">%s</a></li>' % (c["id"], _e(c.get("title", "")))
                for c in courses)
            body = '<ul class="course-list">%s</ul>' % items
            if not sid:
                body = '<div class="notice"><a href="/_login">Войти как студент</a></div>' + body
            return handler._core.page("Курсы", body)

        @r.add("GET", "/course/")
        def course_page(handler, params):
            parts = params.get("_parts", [])
            cid = parts[0] if parts else ""
            course = handler._core.course(cid)
            if not course:
                return handler._core.page("Курс не найден", "<p>Такого курса нет.</p>")
            sid = handler._student()
            if not sid:
                handler._redirect("/_login?next=" + urllib.parse.quote(handler.path))
                return _SENT
            if not handler._core.can_access(cid, sid):
                return handler._core.page(
                    "Нет доступа",
                    '<p class="error">Вы не зачислены на этот курс.</p>')
            lessons = handler._core.lessons(cid)
            items = "".join(
                '<li><a href="/lesson/%s">%s</a></li>' % (l["id"], _e(l.get("title", "")))
                for l in lessons)
            # Материалы скрыты от студентов: сценарные страницы открываются
            # из заданий (кнопки + интерактивный план).
            # ── Бригады: названия придумывают студенты, лимит задаёт преподаватель
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
            bmsg = ""
            if (qs.get("brig_err") or [""])[0]:
                bmsg = '<p class="error">%s</p>' % _e((qs.get("brig_err") or [""])[0])
            elif (qs.get("brig_ok") or [""])[0]:
                bmsg = ('<div class="sub-status"><p>%s</p></div>'
                        % _e((qs.get("brig_ok") or [""])[0]))
            studs = handler._core.db.get("студенты", [])
            me = next((s for s in studs if s["id"] == sid), None)
            my_br = ((me or {}).get("бригада") or "").strip()
            teams = {}
            for s in studs:
                b = (s.get("бригада") or "").strip()
                if b:
                    teams.setdefault(b, []).append(s.get("fio", ""))
            bmax = handler._core.brigade_max(cid)
            if my_br:
                mine_html = ('<p>Моя бригада: <span class="team-badge">👥 %s'
                             '</span></p>' % _e(my_br))
            else:
                mine_html = '<p class="hint">Вы пока без бригады.</p>'
            rows = ""
            for b in sorted(teams):
                members = teams[b]
                if b == my_br:
                    act = ('<form method="post" action="/brigade" '
                           'style="display:inline">'
                           '<input type="hidden" name="course" value="%s">'
                           '<input type="hidden" name="act" value="leave">'
                           '<button class="btn-sm btn-secondary">Выйти</button>'
                           '</form>' % _e(cid))
                elif len(members) < bmax:
                    act = ('<form method="post" action="/brigade" '
                           'style="display:inline">'
                           '<input type="hidden" name="course" value="%s">'
                           '<input type="hidden" name="act" value="join">'
                           '<input type="hidden" name="name" value="%s">'
                           '<button class="btn-sm">Вступить</button></form>'
                           % (_e(cid), _e(b)))
                else:
                    act = '<span class="reason">мест нет</span>'
                rows += ('<li>👥 <b>%s</b> — %d/%d %s</li>'
                         % (_e(b), len(members), bmax, act))
            bhtml = ('<h2>👷 Бригады</h2>%s%s<ul>%s</ul>'
                     '<form method="post" action="/brigade" class="task-form" '
                     'style="padding:14px 18px">'
                     '<input type="hidden" name="course" value="%s">'
                     '<input type="hidden" name="act" value="create">'
                     '<p><label>Название бригады: '
                     '<input type="text" name="name" maxlength="40" '
                     'placeholder="например, Искра" required></label></p>'
                     '<p><button>Создать бригаду</button></p></form>'
                     '<p class="hint">Состав — до %d чел. Бригада сдаёт '
                     'один отчёт на всех.</p>'
                     ) % (bmsg, mine_html,
                          rows or '<li class="hint">Пока нет ни одной бригады.</li>',
                          _e(cid), bmax)
            body = ('<ul class="lesson-list">%s</ul>%s' % (items, bhtml))
            return handler._core.page(course.get("title", ""), body, course=course)

        @r.add("POST", "/brigade")
        def brigade_post(handler, params):
            data = handler._parse_post()
            sid = handler._student()
            if not sid:
                handler._send_json(403, {"error": "not authorised"})
                return _SENT
            cid = data.get("course", "")
            act = data.get("act", "")
            name = (data.get("name") or "").strip()
            back = "/course/%s" % _e(cid)
            if not handler._core.course(cid) or \
                    not handler._core.can_access(cid, sid):
                handler._redirect(back + "?brig_err="
                                  + urllib.parse.quote("Нет доступа к курсу"))
                return _SENT
            studs = handler._core.db.get("студенты", [])
            me = next((s for s in studs if s["id"] == sid), None)
            my_br = ((me or {}).get("бригада") or "").strip()
            teams = {}
            for s in studs:
                b = (s.get("бригада") or "").strip()
                if b:
                    teams.setdefault(b, []).append(s["id"])
            bmax = handler._core.brigade_max(cid)
            if act == "leave":
                if my_br:
                    handler._core.student_set_brigade(sid, "")
                    back += "?brig_ok=" + urllib.parse.quote("Вы вышли из бригады")
            elif act in ("create", "join"):
                if my_br:
                    back += "?brig_err=" + urllib.parse.quote(
                        "Вы уже в бригаде «%s» — сначала выйдите" % my_br)
                elif not name:
                    back += "?brig_err=" + urllib.parse.quote(
                        "Введите название бригады")
                elif name in teams and len(teams[name]) >= bmax:
                    back += "?brig_err=" + urllib.parse.quote(
                        "В бригаде «%s» нет мест (макс. %d)" % (name, bmax))
                else:
                    handler._core.student_set_brigade(sid, name)
                    back += "?brig_ok=" + urllib.parse.quote(
                        "Вы в бригаде «%s»" % name)
            handler._redirect(back)
            return _SENT

        @r.add("GET", "/lesson/")
        def lesson_page(handler, params):
            parts = params.get("_parts", [])
            lid = parts[0] if parts else ""
            lesson = handler._core.lesson(lid)
            if not lesson:
                return handler._core.page("Занятие не найдено",
                                          "<p>Такого занятия нет.</p>")
            sid = handler._student()
            if not sid:
                handler._redirect("/_login?next=" + urllib.parse.quote(handler.path))
                return _SENT
            if not handler._core.can_access(lesson.get("course", ""), sid):
                return handler._core.page(
                    "Нет доступа",
                    '<p class="error">Вы не зачислены на этот курс.</p>')
            course = handler._core.course(lesson.get("course", ""))
            tasks = handler._core.tasks(lid)
            _stu0 = handler._core.student(sid)
            _brg0 = (_stu0.get("бригада", "") or "").strip() if _stu0 else ""
            items = ""
            for t in tasks:
                if not handler._core.task_for_brigade(t, _brg0):
                    continue  # задание выдано другим бригадам
                sub_info = ""
                if sid:
                    sub = handler._core.sub(t["id"], sid)
                    if sub:
                        icons = {"сдано": "отправлено", "принято": "принято",
                                 "доработка": "доработка", "отклонено": "отклонено"}
                        sub_info = " [%s]" % icons.get(sub.get("status", ""), sub.get("status", ""))
                items += '<li><a href="/task/%s">%s</a>%s</li>' % (
                    t["id"], _e(t.get("title", "")), sub_info)
            body = ('<p><a href="/course/%s">%s</a></p>'
                    '<ul class="task-list">%s</ul>') % (
                _e(lesson.get("course", "")),
                _e(course.get("title", "") if course else ""),
                items)
            return handler._core.page(lesson.get("title", ""), body,
                                      course=course, lesson=lesson)

        @r.add("GET", "/task/")
        def task_page(handler, params):
            parts = params.get("_parts", [])
            tid = parts[0] if parts else ""
            task_data = handler._core.assign(tid)
            if not task_data:
                return handler._core.page("Задание не найдено",
                                          "<p>Такого задания нет.</p>")
            sid = handler._student()
            if not sid:
                handler._redirect("/_login?next=" + urllib.parse.quote("/task/" + tid))
                return _SENT
            _t = handler._core.task(tid)
            _lesson0 = handler._core.lesson(_t.get("lesson", "")) if _t else None
            if _lesson0 and not handler._core.can_access(_lesson0.get("course", ""), sid):
                return handler._core.page(
                    "Нет доступа",
                    '<p class="error">Вы не зачислены на этот курс.</p>')
            _stu0 = handler._core.student(sid)
            _brg0 = (_stu0.get("бригада", "") or "").strip() if _stu0 else ""
            if _t and not handler._core.task_for_brigade(_t, _brg0):
                return handler._core.page(
                    "Задание не выдано",
                    '<p class="error">Это задание ещё не выдано вашей бригаде. '
                    'Создайте бригаду на странице курса или попросите '
                    'преподавателя выдать его.</p>')
            lesson = handler._core.lesson(handler._core.task(tid).get("lesson", ""))
            course = handler._core.course(lesson.get("course", "")) if lesson else None
            form_html = handler._core.task_form_html(task_data)
            dl = task_deadline(handler._core.task(tid))
            dl_html = ""
            if dl:
                when = dl.strftime("%d.%m.%Y %H:%M")
                left = dl - datetime.now()
                if left.total_seconds() > 0:
                    left_s = ("осталось %d дн. %d ч." % (left.days, left.seconds // 3600)
                              if left.days else
                              "осталось %d ч. %d мин." % (left.seconds // 3600,
                                                          left.seconds % 3600 // 60))
                    dl_html = ('<div class="notice">⏰ Срок сдачи: %s — %s</div>'
                               % (_e(when), left_s))
                else:
                    dl_html = ('<div class="notice">⏰ Срок сдачи: %s — истёк, '
                               'работа будет помечена как просроченная.</div>'
                               % _e(when))
            sub = handler._core.sub(tid, sid)
            sub_info = ""
            if sub:
                v = handler._core.latest(sub)
                icons = {"сдано": "сдано", "принято": "принято",
                         "доработка": "доработка", "отклонено": "отклонено"}
                status = icons.get(sub.get("status", ""), sub.get("status", ""))
                sub_info = '<div class="sub-status"><h3>Статус: %s</h3>' % status
                sub_info += "<p>Версия %d, %s%s</p>" % (
                    v.get("n", 0), v.get("time", ""),
                    " ⏰ сдано после срока" if v.get("просрочено") else "")
                if v.get("verdict"):
                    sub_info += "<p>Вердикт: %s</p>" % _e(v["verdict"])
                    if v.get("score"):
                        sub_info += "<p>Балл: %s</p>" % _e(str(v["score"]))
                    if v.get("comment"):
                        sub_info += "<p>%s</p>" % _e(v["comment"])
                sub_info += "</div>"
                if sub.get("бригада"):
                    sub_info += '<p>👥 Бригада «%s» — участников: %d</p>' % (
                        _e(sub["бригада"]), len(sub.get("participants", [])))
            _stu = handler._core.student(sid)
            _brg = (_stu.get("бригада", "") or "").strip() if _stu else ""
            br_html = ""
            if _brg:
                br_html = (
                    '<p><label>Сдача: '
                    '<select name="brigade">'
                    '<option value="">👤 Лично (свой отчёт)</option>'
                    '<option value="%s">👥 За бригаду «%s» — отчёт один на всех'
                    '</option></select></label></p>' % (_e(_brg), _e(_brg)))
            else:
                _cb = "/course/%s" % course["id"] if course else ""
                if _cb:
                    br_html = ('<p class="hint">Сдать одним отчётом на бригаду? '
                               '<a href="%s">Создайте бригаду или вступите</a> '
                               'на странице курса.</p>' % _cb)
            # ── Материалы сценария + интерактивный план ──
            scn_html = ""
            if lesson and course:
                _mats = handler._core.distribute(course["id"], lesson["id"])
                _links = []
                for m in _mats:
                    _n = m.get("name") or m.get("имя", "")
                    if m.get("тип") != "файл":
                        continue
                    _lbl = ""
                    if _n.startswith("02_"):
                        _lbl = "📖 Раздатка"
                    elif _n.startswith("05_"):
                        _lbl = "📐 План сооружений"
                    elif _n.startswith("06_"):
                        _lbl = "🔤 Условные обозначения"
                    if _lbl:
                        _links.append(
                            '<a class="btn btn-secondary btn-sm" target="_blank" '
                            'href="/materials/%s/%s/%s">%s</a>'
                            % (_e(course["id"]), _e(lesson["id"]),
                               urllib.parse.quote(_n), _lbl))
                if _links:
                    scn_html = (
                        '<div class="task-desc"><h3>📐 План сооружения</h3>'
                        '<p class="hint">Выберите условное обозначение и щёлкните '
                        'по плану — устройство встанет в точку. Клик по '
                        'установленному устройству — убрать. Перечень '
                        'обозначений и правил — под планом. Черновик '
                        'сохраняется автоматически и уйдёт вместе с отчётом.'
                        '</p>'
                        '<iframe src="/plan/%s" style="width:100%%;height:900px;'
                        'border:1px solid #e0e0e0;border-radius:12px" '
                        'title="Интерактивный план сооружения"></iframe>'
                        '<script>(function(){var f=document.querySelector'
                        "('form.task-form');if(!f)return;"
                        "f.addEventListener('submit',function(){try{"
                        "var v=localStorage.getItem('wcplan_%s')||'[]';"
                        "var i=f.querySelector('[name=plan_data]');"
                        "if(i)i.value=v;}catch(e){}});})();</script>"
                    ) % (_e(tid), _e(tid))
            body = ('<p><a href="/lesson/%s">%s</a></p>'
                    '<div class="task-desc">%s</div>%s%s%s'
                    '<form method="post" action="/api/submit"'
                    ' enctype="multipart/form-data" class="task-form">'
                    '<input type="hidden" name="task" value="%s">%s%s'
                    "<p><button>Отправить</button></p></form>" + DRAFT_JS) % (
                _e(lesson["id"] if lesson else ""),
                _e(lesson["title"] if lesson else ""),
                _md(task_data.get("описание", "")),
                scn_html, dl_html, sub_info, tid, form_html, br_html)
            return handler._core.page(task_data.get("title", ""), body,
                                      course=course, lesson=lesson)

        @r.add("POST", "/api/submit")
        def submit_post(handler, params):
            data = handler._parse_post()
            tid = data.get("task", "")
            sid = handler._student()
            if not sid:
                handler._send_json(403, {"error": "not authorised"})
                return _SENT
            _tq = handler._core.task(tid)
            _sq = handler._core.student(sid)
            if _tq and not handler._core.task_for_brigade(
                    _tq, ((_sq.get("бригада", "") or "").strip() if _sq else "")):
                handler._send_json(403, {"error": "task not issued"})
                return _SENT
            answers = {}
            files = {}
            brigade = ""
            for k, v in data.items():
                if k in ("task", "submit"):
                    continue
                if hasattr(v, "data") and hasattr(v, "name"):
                    files[k] = v          # загруженный файл
                elif k == "brigade":
                    brigade = (v or "").strip()
                else:
                    answers[k] = v
            sub, err = handler._core.collect(tid, sid, answers, files,
                                             brigade=brigade)
            if err:
                handler._redirect("/task/%s?error=%s" % (tid, urllib.parse.quote(err)))
            else:
                handler._redirect("/task/%s?ok=1" % tid)
            return _SENT

        
        @r.add("GET", "/_subfile/", access="staff")
        def sub_file(handler, params):
            """Скачать файл из сдачи студента (только преподаватель)."""
            parts = params.get("_parts", [])
            if len(parts) < 3 or "__" not in parts[0]:
                handler._send_text(404, "Not Found")
                return _SENT
            key, vn, fkey = parts[0], parts[1], parts[2]
            tid, sid = key.split("__", 1)
            sub = handler._core.sub(tid, sid)
            ver = None
            if sub:
                for v in sub.get("versions", []):
                    if str(v.get("n")) == vn:
                        ver = v
                        break
            info = (ver or {}).get("files", {}).get(fkey) if ver else None
            if not info:
                handler._send_text(404, "Not Found")
                return _SENT
            local = os.path.normpath(os.path.join(handler._core.store.subs,
                                                  str(info.get("файл", ""))))
            base = os.path.normpath(handler._core.store.subs)
            try:
                inside = os.path.commonpath([local, base]) == base
            except ValueError:
                inside = False
            if not inside or not os.path.isfile(local):
                handler._send_text(404, "Not Found")
                return _SENT
            with open(local, "rb") as f:
                data = f.read()
            fname = info.get("имя") or os.path.basename(local)
            handler.send_response(200)
            handler.send_header("Content-Type", "application/octet-stream")
            handler.send_header(
                "Content-Disposition",
                "attachment; filename*=UTF-8''" + urllib.parse.quote(str(fname)))
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)
            return _SENT

        @r.add("POST", "/_modules/reorder", access="staff")
        def reorder_modules(handler, params):
            data = handler._parse_post()
            order = data.get("order", [])
            if order:
                handler._core.set_module_order(order)
            handler._send_json(200, {"ok": True})
            return _SENT

        return r

    def _student_login_html(self, handler):
        """HTML страницы входа студента с поиском-автодополнением."""
        students = handler._core.students()
        if not students:
            return "<p>\u041d\u0435\u0442 \u0441\u0442\u0443\u0434\u0435\u043d\u0442\u043e\u0432 \u0432 \u0441\u0438\u0441\u0442\u0435\u043c\u0435.</p>"

        import json as _jdata
        _stu_json = _jdata.dumps(
            [{"id": s["id"], "fio": s["fio"], "group": s.get("group", "")}
             for s in students],
            ensure_ascii=False)

        opts = "".join(
            '<option value="%s">%s%s</option>' % (
                s["id"],
                _e(s["fio"]),
                (" (" + _e(s.get("group", "")) + ")") if s.get("group") else "")
            for s in students)

        return (
            "<script>"
            "var _S=" + _stu_json + ";"
            "function _on(q){"
            "  q=q.toLowerCase().replace('\\u0451','\\u0435').trim();"
            "  var r=document.getElementById('_r');"
            "  if(!q||q.length<2){r.innerHTML='';return}"
            "  var h=_S.filter(function(x){"
            "    return x.fio.toLowerCase().replace('\\u0451','\\u0435').indexOf(q)>=0"
            "      || x.group.indexOf(q)>=0;"
            "  });"
            "  if(h.length==1){"
            "    document.getElementById('_s').value=h[0].id;"
            "    r.innerHTML='<b>'+h[0].fio+'</b>';return"
            "  }"
            "  r.innerHTML=h.map(function(x){"
            "    return '<div class=\"hit\" onclick=\"_pk(\\''+x.id+'\\')\">'+x.fio"
            "      +(x.group?' ('+x.group+')':'')+'</div>';"
            "  }).join('');"
            "  if(!h.length){r.innerHTML='<div class=\"no-hit\">\u041d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e</div>'}"
            "}"
            "function _pk(id){"
            "  var x=_S.find(function(y){return y.id==id;});"
            "  if(x){"
            "    document.getElementById('_s').value=x.id;"
            "    document.getElementById('_q').value=x.fio;"
            "    document.getElementById('_r').innerHTML='';"
            "    document.getElementById('_lf').querySelector('button').focus();"
            "  }"
            "}"
            "</script>"
            + '<form method="post" action="/_login" class="login-form" id="_lf">'
            + "<input type='hidden' name='next' value='/'>"
            + "<h2>\u0412\u0445\u043e\u0434 \u0441\u0442\u0443\u0434\u0435\u043d\u0442\u0430</h2>"
            + "<p><input type='search' id='_q' autocomplete='off'"
            + " placeholder='\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u0444\u0430\u043c\u0438\u043b\u0438\u044e...'"
            + " oninput='_on(this.value)'></p>"
            + "<div id='_r'></div>"
            + "<p><select name='student' id='_s' required>"
            + "<option value=''>- \u0432\u044b\u0431\u0435\u0440\u0438\u0442\u0435 -</option>"
            + opts
            + "</select></p>"
            + '<p><button class="btn-big">\u0412\u043e\u0439\u0442\u0438</button></p>'
            + "</form>"
        )
    def port(self):
        return self._port


def _e(v):

    import html as _html
    return _html.escape(str(v) if v is not None else "", quote=True)