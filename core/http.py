# -*- coding: utf-8 -*-
"""HTTP-сервер ядра: маршрутизация, multipart, сессии, статика."""
import cgi
import http.server
import json
import mimetypes
import os
import secrets
import socket
import urllib.parse


_mime = mimetypes.guess_type
_SENT = "___SENT___"  # маркер: ответ уже отправлен
SENT = _SENT  # экспорт для модулей


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
            path = urllib.parse.urlparse(self.path).path
            handler, access, params = self._router.match(method, path)
            if not handler:
                self._serve_static(path)
                return
            if access == "staff" and not self._is_staff():
                self._serve_staff_login()
                return
            if access == "student" and not self._student():
                self._redirect("/_login?next=" + urllib.parse.quote(self.path))
                return
            try:
                result = handler(self, params)
            except Exception as ex:
                import traceback
                traceback.print_exc()
                self._send_json(500, {"error": str(ex)})
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
        except Exception as ex:
            import traceback
            traceback.print_exc()
            try:
                self._send_text(500, str(ex))
            except ConnectionError:
                pass

    def _student(self):
        c = self._cookie("student")
        if c and self._core.student(c):
            return c
        return None

    def _is_staff(self):
        token = self._cookie("staff_token")
        if token:
            return self._server_inst.sessions.get(token)
        return False

    def _cookie(self, name):
        c = self.headers.get("Cookie", "")
        for part in c.split(";"):
            part = part.strip()
            if part.lower().startswith(name.lower() + "="):
                return urllib.parse.unquote(part[len(name) + 1:])
        return ""

    def _serve_staff_login(self):
        body = (
            '<form method="post" action="/_staff_login" class="login-form">'
            "<h2>Вход для преподавателя</h2>"
            '<p><label>Пароль: <input type="password" name="pass" required autofocus></label></p>'
            "<p><button>Войти</button></p>"
            '<p class="hint">Пароль задаётся при запуске: --pass ПАРОЛЬ</p>'
            "</form>")
        self._send_html(self._core.page("Вход", body))

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
        if not any(local.startswith(b) for b in basedirs):
            self._send_text(403, "Forbidden")
            return
        if not os.path.isfile(local):
            self._send_text(404, "Not Found")
            return
        mime, _ = _mime(local)
        self._send_response(200, mime or "application/octet-stream",
                            open(local, "rb").read(), encode=False)

    def _parse_post(self):
        ctype = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b""
        if "multipart/form-data" in ctype:
            _, pdict = cgi.parse_header(ctype)
            pdict["boundary"] = pdict.get("boundary", "").encode()
            import io
            fields = cgi.parse_multipart(io.BytesIO(body), pdict)
            return {k: (v[0] if isinstance(v, list) and len(v) == 1 else v)
                    for k, v in fields.items()}
        elif "application/x-www-form-urlencoded" in ctype or "application/json" in ctype:
            if "application/json" in ctype:
                return json.loads(body.decode("utf-8"))
            return dict(urllib.parse.parse_qsl(body.decode("utf-8")))
        else:
            try:
                return dict(urllib.parse.parse_qsl(body.decode("utf-8")))
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
        """Перенаправление (200 + meta-refresh).

        extra_headers — список (name, value) для дополнительных заголовков
        (например, Set-Cookie). Передаются ПОСЛЕ send_response, но ДО
        end_headers, чтобы порядок заголовков в HTTP был корректным.
        """
        body = (
            "<!doctype html><meta charset=\"utf-8\">"
            "<meta http-equiv=\"refresh\" content=\"0;url=%s\">"
            "<title>Redirect</title><a href=\"%s\">Continue</a>") % (url, url)
        data = body.encode("utf-8")
        self.send_response(200)
        # Дополнительные заголовки (например Set-Cookie) — после send_response
        for name, value in (extra_headers or []):
            self.send_header(name, value)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def _set_cookie(self, name, value, path="/", max_age=None):
        """Создать заголовок Set-Cookie (без отправки — возвращает строку)."""
        s = "%s=%s; Path=%s" % (name, urllib.parse.quote(value), path)
        if max_age:
            s += "; Max-Age=%d" % max_age
        return ("Set-Cookie", s)

    def log_message(self, format, *args):
        pass


class WorksServer(http.server.HTTPServer):
    """HTTP-сервер ядра со встроенными маршрутами."""

    def __init__(self, core, host="", port=8080, static_dir="", passwd=""):
        self.core = core
        self.static_dir = os.path.abspath(static_dir) if static_dir else ""
        self.passwd = passwd
        self.sessions = {}
        self._port = port

        WorksHandler._server_inst = self
        WorksHandler._router = self._make_router()
        WorksHandler._core = core
        core.router = WorksHandler._router

        for method, path, handler, access in core.pending_routes:
            WorksHandler._router.add(method, path, handler, access)

        super().__init__((host, port), WorksHandler)

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
                cookie = handler._set_cookie("student", sid, max_age=86400)
                handler._redirect(data.get("next", "/"), [cookie])
            else:
                handler._redirect("/_login?err=1")
            return _SENT

        def staff_logout(handler, params):
            cookie = handler._set_cookie("staff_token", "", max_age=0)
            handler._redirect("/", [cookie])
            return _SENT

        @r.add("POST", "/_staff_login")
        def staff_login(handler, params):
            data = handler._parse_post()
            if not self.passwd or data.get("pass", "") == self.passwd:
                token = secrets.token_hex(16)
                self.sessions[token] = True
                cookie = handler._set_cookie("staff_token", token, max_age=28800)
                handler._redirect("/staff", [cookie])
            else:
                handler._redirect("/_staff_login?err=1")
            return _SENT

        @r.add("GET", "/_modules")
        @r.add("GET", "/_modules")
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
        def toggle_module(handler, params):
            parts = params.get("_parts", [])
            mod_id = parts[0] if parts else ""
            if not mod_id:
                return handler._send_json(400, {"error": "no module id"})
            enabled = handler._core.toggle_module(mod_id)
            return handler._send_json(200, {"ok": True, "mod_id": mod_id, "enabled": enabled})

        @r.add("GET", "/")
        def home(handler, params):
            sid = handler._student()
            courses = handler._core.courses()
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
            lessons = handler._core.lessons(cid)
            items = "".join(
                '<li><a href="/lesson/%s">%s</a></li>' % (l["id"], _e(l.get("title", "")))
                for l in lessons)
            mats_html = ""
            for l in lessons:
                mats = handler._core.distribute(cid, l["id"])
                if mats:
                    mats_html += "<h3>%s</h3><ul>" % _e(l["title"])
                    for m in mats:
                        name = m.get("name") or m.get("имя", "")
                        if m.get("type") == "file" or m.get("тип") == "файл":
                            path = "/materials/%s/%s/%s" % (cid, l["id"],
                                                           urllib.parse.quote(name))
                            mats_html += '<li><a href="%s">%s</a></li>' % (path, _e(name))
                        else:
                            mats_html += "<li>%s</li>" % _e(name)
                    mats_html += "</ul>"
            body = '<ul class="lesson-list">%s</ul><h2>Материалы</h2>%s' % (items, mats_html)
            return handler._core.page(course.get("title", ""), body, course=course)

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
            course = handler._core.course(lesson.get("course", ""))
            tasks = handler._core.tasks(lid)
            items = ""
            for t in tasks:
                sub_info = ""
                if sid:
                    sub = handler._core.sub(t["id"], sid)
                    if sub:
                        icons = {"сдано": "отправлено", "принято": "принято",
                                 "доработка": "доработка", "отклонено": "отклонено"}
                        sub_info = " [%s]" % icons.get(sub.get("status", ""), sub.get("status", ""))
                items += '<li><a href="/task/%s">%s</a>%s</li>' % (
                    t["id"], _e(t.get("title", "")), sub_info)
            mats_html = ""
            mats = handler._core.distribute(lesson.get("course", ""), lid)
            if mats:
                mats_html = "<ul>"
                for m in mats:
                    name = m.get("name") or m.get("имя", "")
                    if m.get("type") == "file" or m.get("тип") == "файл":
                        path = "/materials/%s/%s/%s" % (
                            lesson.get("course", ""), lid, urllib.parse.quote(name))
                        mats_html += '<li><a href="%s">%s</a></li>' % (path, _e(name))
                    else:
                        mats_html += "<li>%s</li>" % _e(name)
                mats_html += "</ul>"
            body = ('<p><a href="/course/%s">%s</a></p>'
                    '<ul class="task-list">%s</ul>'
                    "<h2>Материалы</h2>%s") % (
                _e(lesson.get("course", "")),
                _e(course.get("title", "") if course else ""),
                items, mats_html or "<p>Нет материалов.</p>")
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
            lesson = handler._core.lesson(handler._core.task(tid).get("lesson", ""))
            course = handler._core.course(lesson.get("course", "")) if lesson else None
            form_html = handler._core.task_form_html(task_data)
            sub = handler._core.sub(tid, sid)
            sub_info = ""
            if sub:
                v = handler._core.latest(sub)
                icons = {"сдано": "сдано", "принято": "принято",
                         "доработка": "доработка", "отклонено": "отклонено"}
                status = icons.get(sub.get("status", ""), sub.get("status", ""))
                sub_info = '<div class="sub-status"><h3>Статус: %s</h3>' % status
                sub_info += "<p>Версия %d, %s</p>" % (v.get("n", 0), v.get("time", ""))
                if v.get("verdict"):
                    sub_info += "<p>Вердикт: %s</p>" % _e(v["verdict"])
                    if v.get("score"):
                        sub_info += "<p>Балл: %s</p>" % _e(str(v["score"]))
                    if v.get("comment"):
                        sub_info += "<p>%s</p>" % _e(v["comment"])
                sub_info += "</div>"
            body = ('<p><a href="/lesson/%s">%s</a></p>'
                    '<div class="task-desc">%s</div>%s'
                    '<form method="post" action="/api/submit"'
                    ' enctype="multipart/form-data" class="task-form">'
                    '<input type="hidden" name="task" value="%s">%s'
                    "<p><button>Отправить</button></p></form>") % (
                _e(lesson["id"] if lesson else ""),
                _e(lesson["title"] if lesson else ""),
                task_data.get("описание", ""), sub_info, tid, form_html)
            return handler._core.page(task_data.get("title", ""), body,
                                      course=course, lesson=lesson)

        @r.add("POST", "/api/submit")
        def submit_post(handler, params):
            data = handler._parse_post()
            tid = data.get("task", "")
            sid = handler._student()
            if not sid:
                return handler._send_json(403, {"error": "not authorised"})
            answers = {}
            files = {}
            for k, v in data.items():
                if k in ("task", "submit"):
                    continue
                if isinstance(v, bytes):
                    files[k] = v
                else:
                    answers[k] = v
            sub, err = handler._core.collect(tid, sid, answers, files)
            if err:
                handler._redirect("/task/%s?error=%s" % (tid, urllib.parse.quote(err)))
            else:
                handler._redirect("/task/%s?ok=1" % tid)
            return _SENT

        
        @r.add("POST", "/_modules/reorder")
        def reorder_modules(handler, params):
            data = handler._parse_post()
            order = data.get("order", [])
            if order:
                handler._core.set_module_order(order)
            return handler._send_json(200, {"ok": True})

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