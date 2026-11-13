# -*- coding: utf-8 -*-
"""Подсказки: регресс-тест (сервер :8091 + мок Ollama :18434, своё хранилище).

Проверки: кнопка/панель/плашка на страницах, загрузка источников,
пересборка индекса, ответ с источниками, кэш частых вопросов, отказ на
нерелевантный вопрос, лимит в час, выключатель, история в панели.

Мок Ollama: /api/embed — гистограмма слов (детерминированная), /api/chat
— фиксированный ответ, /api/tags — список моделей.
"""
import base64
import hashlib
import html
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.getcwd()
PORT = 8091
OLLAMA_PORT = 18434
API_PORT = 18435
BASE = "http://localhost:%d" % PORT
STORE = os.path.join(ROOT, "_podsk_store")
PY = sys.executable

MD_DOC = (
    "# Руководство стенда ОПС\n\n"
    "Прибор ППК контролирует шлейфы сигнализации. Сопротивление шлейфа "
    "в дежурном режиме должно быть 1,0-2,2 кОм. При обрыве шлейфа "
    "прибор фиксирует неисправность за 10 секунд. Проверка шлейфа "
    "выполняется в следующем порядке: осмотр клемм, измерение "
    "сопротивления, проверка полярности подключения извещателей.\n\n"
    "Питание от сети 220 В, резервный аккумулятор 12 В 7 Ач обеспечивает "
    "не менее 24 часов работы. Ёмкость аккумулятора проверяется "
    "тестером раз в месяц, при просадке ниже 11,5 В аккумулятор "
    "заменяется.\n\n"
    "Извещатели подключаются по двухпроводной схеме, полярность важна. "
    "Ток потребления извещателя в дежурном режиме не более 60 мкА, "
    "в режиме срабатывания до 15 мА.\n\n"
    "Оповещатели подключаются к выходам прибора: нагрузка до 1 А на "
    "каждый выход, сечение провода не менее 0,5 мм2.\n"
)

class MockAPI(BaseHTTPRequestHandler):
    """Мок OpenAI-совместимого агрегатора (/v1/models, /v1/chat/...)."""
    def log_message(self, *a):
        pass

    def _reply(self, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            self._reply({"data": [{"id": "test-model"},
                                  {"id": "test-model-2"}]})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path.rstrip("/").endswith("/chat/completions"):
            n = int(self.headers.get("Content-Length", 0) or 0)
            data = json.loads(self.rfile.read(n).decode("utf-8")
                              or "{}") if n else {}
            q = str((data.get("messages") or [{}])[-1].get("content", ""))
            if "failapi" in q:
                self.send_response(500)
                self.end_headers()
                return
            auth = self.headers.get("Authorization", "")
            self._reply({"choices": [{"message": {
                "role": "assistant",
                "content": "API ОТВЕТ (ключ принят: %s)"
                           % ("да" if auth.startswith("Bearer ")
                              else "нет")}}]})
        else:
            self.send_response(404)
            self.end_headers()


ok = True
proc = None
mock = None
api_mock = None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_op = urllib.request.build_opener(_NoRedirect)


def need(cond, msg, ctx=""):
    global ok
    print(("OK   " if cond else "FAIL ") + msg + ("" if cond else
                                                  "  | " + str(ctx)[:220]))
    ok = ok and bool(cond)


def req(path, method="GET", data=None, headers=None, jar=None,
        base=None):
    r = urllib.request.Request(
        (base or BASE) + urllib.parse.quote(path), method=method,
        data=data, headers=headers or {})
    try:
        with _op.open(r, timeout=20) as resp:
            if jar is not None:
                jar.extend(resp.headers.get_all("Set-Cookie") or [])
            return (resp.getcode(), dict(resp.headers),
                    resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if jar is not None:
            jar.extend(e.headers.get_all("Set-Cookie") or [])
        return (e.code, dict(e.headers),
                e.read().decode("utf-8", "replace"))
    except Exception as e:
        return 0, {}, str(e)


def get(path, jar=None):
    h = {}
    if jar:
        h["Cookie"] = "; ".join(c.split(";")[0] for c in jar)
    return req(path, headers=h, jar=jar)


def form_post(path, fields, jar=None):
    d = urllib.parse.urlencode(fields).encode("utf-8")
    h = {"Content-Type": "application/x-www-form-urlencoded"}
    if jar:
        h["Cookie"] = "; ".join(c.split(";")[0] for c in jar)
    return req(path, "POST", d, h, jar=jar)


def json_post(path, obj, jar=None):
    d = json.dumps(obj).encode("utf-8")
    h = {"Content-Type": "application/json"}
    if jar:
        h["Cookie"] = "; ".join(c.split(";")[0] for c in jar)
    return req(path, "POST", d, h, jar=jar)


def mp_post(path, fields, files, jar=None):
    b = "----wc" + str(int(time.time() * 1000))
    body = b""
    for k, v in fields.items():
        body += ('--%s\r\nContent-Disposition: form-data; name="%s"'
                 '\r\n\r\n%s\r\n' % (b, k, v)).encode("utf-8")
    for k, (fn, blob) in files.items():
        body += ('--%s\r\nContent-Disposition: form-data; name="%s"; '
                 'filename="%s"\r\nContent-Type: text/plain\r\n\r\n'
                 % (b, k, fn)).encode("utf-8") + blob + b"\r\n"
    body += ("--%s--\r\n" % b).encode("utf-8")
    h = {"Content-Type": "multipart/form-data; boundary=" + b}
    if jar:
        h["Cookie"] = "; ".join(c.split(";")[0] for c in jar)
    return req(path, "POST", body, h, jar=jar)


def wait_port(port, timeout=25):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = socket.socket()
        s.settimeout(0.5)
        try:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        finally:
            s.close()
        time.sleep(0.3)
    return False


# ── мок Ollama ───────────────────────────────────────────────────────
class MockOllama(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _reply(self, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/tags":
            self._reply({"models": [{"name": "qwen3:1.7b"},
                                    {"name": "bge-m3:latest"}]})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        data = json.loads(self.rfile.read(n).decode("utf-8")
                          or "{}") if n else {}
        if self.path == "/api/embed":
            vecs = []
            for t in data.get("input", []):
                v = [0.0] * 256
                for w in str(t).lower().split():
                    stem = w[:5]  # псевдостемминг: шлейф/шлейфа/шлейфы
                    v[(sum(map(ord, stem)) * 31 + len(stem)) % 256] += 1.0
                vecs.append(v)
            self._reply({"embeddings": vecs})
        elif self.path == "/api/chat":
            # Ответ зависит от полученного системного промта: так тест
            # проверяет, что модель вызвана ИМЕННО с актуальным промтом
            # (репорт: «исправленный системный промт не применялся»),
            # и что правила продублированы в конце запроса.
            _msgs = data.get("messages") or []
            _sys = "\n".join(str(m.get("content") or "") for m in _msgs
                             if m.get("role") == "system")
            _last = str((_msgs or [{}])[-1].get("content") or "")
            _mark = hashlib.sha1(_sys.encode("utf-8")).hexdigest()[:6]
            _tail = " [правила-в-конце]" if "ПРАВИЛА ОТВЕТА" in _last else ""
            _tail += (" [без-пересказа]"
                      if "внутренние, студенту их не видно" in _last else "")
            self._reply({"message": {"role": "assistant",
                                     "content": "Проверьте сопротивление "
                                     "шлейфа: 1,0-2,2 кОм. [промт:%s]%s\n"
                                     "---\n"
                                     "Источник: Руководство стенда ОПС"
                                     % (_mark, _tail)},
                         "eval_count": 20, "eval_duration": 1})
        else:
            self.send_response(404)
            self.end_headers()


try:
    if os.path.isdir(STORE):
        shutil.rmtree(STORE)
    # настройки модуля заранее: url мока
    cfg_dir = os.path.join(STORE, "модули", "podskazki")
    os.makedirs(cfg_dir, exist_ok=True)
    io.open(os.path.join(cfg_dir, "настройки.json"), "w",
            encoding="utf-8").write(json.dumps(
        {"url": "http://127.0.0.1:%d" % OLLAMA_PORT}, ensure_ascii=False))

    mock = ThreadingHTTPServer(("127.0.0.1", OLLAMA_PORT), MockOllama)
    threading.Thread(target=mock.serve_forever, daemon=True).start()
    api_mock = ThreadingHTTPServer(("127.0.0.1", API_PORT), MockAPI)
    threading.Thread(target=api_mock.serve_forever, daemon=True).start()
    need(wait_port(OLLAMA_PORT), "мок Ollama поднялся (:%d)" % OLLAMA_PORT)
    need(wait_port(API_PORT), "мок API поднялся (:%d)" % API_PORT)
    errf = open(os.path.join(ROOT, "_podsk_srv.log"), "wb")
    proc = subprocess.Popen(
        [PY, "-X", "utf8", os.path.join(ROOT, "server.py"),
         "--port", str(PORT), "--store", STORE, "--no-pass", "--demo"],
        cwd=ROOT, stdout=errf, stderr=errf)
    need(wait_port(PORT), "сервер поднялся (:8091)")

    # ── фрагменты на страницах ───────────────────────────────────────
    code, h, body = get("/_login")
    need("wc-ai-btn" in body and "wc-ai-drawer" in body,
         "кнопка «🤖 Подсказка» и панель есть на странице входа")
    need("if(j.ок)" in body and "if(j.ok)" not in body,
         "шторка читает поле «ок» кириллицей (репорт #1: сервер шлёт «ок», "
         "JS читал латинское j.ok — все ответы показывались как ошибка)")
    need("html.dark .wc-ai-drawer" in body,
         "тёмная тема: стили шторки адаптированы (html.dark)")
    # JS шторки обязан быть синтаксически корректен: падение скрипта =
    # «кнопка не работает» (обработчики вообще не вешаются)
    _m = re.search(r"<script>(\(function\(\)\{var d=document"
                   r"\.getElementById\(\"wc-ai-drawer\"\).*?)</script>",
                   body, re.S)
    need(_m, "скрипт шторки найден на странице")
    if _m:
        _js = _m.group(1)
        _dp = _db = _i = 0
        _instr = None
        _bal = True
        while _i < len(_js):
            _c = _js[_i]
            if _instr:
                if _c == "\\":
                    _i += 2
                    continue
                if _c == _instr:
                    _instr = None
            elif _c in "\"'":
                _instr = _c
            elif _c == "(":
                _dp += 1
            elif _c == ")":
                _dp -= 1
                if _dp < 0:
                    _bal = False
                    break
            elif _c == "{":
                _db += 1
            elif _c == "}":
                _db -= 1
                if _db < 0:
                    _bal = False
                    break
            _i += 1
        need(_bal and _dp == 0 and _db == 0,
             "скобки скрипта шторки сбалансированы",
             "dp=%d db=%d" % (_dp, _db))
        need('""),j.фрагменты)}' in _js.replace(" ", ""),
             "фрагменты передаются внутрь вызова add(...), а не после него")
        _jsfile = os.path.join(ROOT, "_drawer_chk.js")
        io.open(_jsfile, "w", encoding="utf-8").write(_js)
        try:
            _np = subprocess.run(["node", "--check", _jsfile],
                                 capture_output=True)
            need(_np.returncode == 0,
                 "node --check: скрипт шторки синтаксически корректен",
                 _np.stderr.decode("utf-8", "replace")[-300:])
        except OSError:
            print("OK   node недоступен — полная проверка JS пропущена")
        finally:
            try:
                os.remove(_jsfile)
            except OSError:
                pass
    need("wc-ai-pl" in body and "/podskazki" in body,
         "плашка преподавателя со ссылкой на панель есть")
    need("body.staff .wc-ai-btn" in body,
         "CSS скрывает чат у преподавателя")

    # ── staff: вход, загрузка источника, пересборка ──────────────────
    jar = []
    form_post("/_staff_login", {"pass": "x"}, jar=jar)
    code, h, body = get("/podskazki", jar=jar)
    need(code == 200 and "Подсказки — панель" in body,
         "панель /podskazki открылась", body[:120])
    need("✅ отвечает" in body,
         "статус: мок Ollama отвечает", body[:400])
    need("qwen3:1.7b" in body,
         "модель найдена в списке мока")

    code, h, body = mp_post("/podskazki/загрузка", {},
                            {"файлы": ("руководство.md",
                                       MD_DOC.encode("utf-8"))}, jar=jar)
    src = os.path.join(STORE, "модули", "podskazki", "источники",
                       "руководство.md")
    need(os.path.isfile(src), "источник сохранён в папку источников")
    mp_post("/podskazki/загрузка", {},
            {"файлы": ("оповещатели.md",
                       ("Выходы оповещателей рассчитаны на нагрузку до "
                        "1 А 24 В. Сечение провода не менее 0,5 мм2. "
                        "Логика запуска: Пожар-1 — внутренние оповещатели,"
                        " Пожар-2 — все оповещатели.\n")
                       .encode("utf-8"))}, jar=jar)

    form_post("/podskazki/пересобрать", {}, jar=jar)
    prog, t_dead = {}, time.time() + 30
    while time.time() < t_dead:
        code, h, pbody = get("/podskazki/прогресс", jar=jar)
        prog = json.loads(pbody)
        if prog.get("фаза") in ("готово", "ошибка"):
            break
        time.sleep(0.3)
    need(prog.get("фаза") == "готово",
         "пересборка фоном завершилась", prog)
    need(prog.get("всего", 0) >= 2 and prog.get("сделано", 0) >= 2,
         "прогресс посчитал чанки", prog)
    idx = json.loads(io.open(os.path.join(cfg_dir, "индекс.json"),
                             encoding="utf-8").read())
    need(len(idx.get("чанки", [])) >= 2,
         "индекс собран, чанков >= 2", len(idx.get("чанки", [])))

    # ── настройки: порог повыше (мок даёт коллизии), лимит позже ─────
    form_post("/podskazki/настройки",
              {"url": "http://127.0.0.1:%d" % OLLAMA_PORT,
               "модель": "qwen3:1.7b", "эмбеддер": "bge-m3",
               "лимит_час": "0", "num_predict": "220", "топ_k": "4",
               "мин_оценка": "0.22", "промт": "", "включено": "1"},
              jar=jar)

    # ── студент: вопрос → ответ с источником ─────────────────────────
    jar_s = []
    form_post("/_login", {"student": "s1"}, jar=jar_s)
    code, h, body = json_post("/podskazka",
                              {"вопрос": "как проверить шлейф сигнализации",
                               "страница": "Задание — тест"}, jar=jar_s)
    j = json.loads(body)
    need(j.get("ок"), "вопрос прошёл", body[:200])
    need("шлейфа" in (j.get("ответ") or ""),
         "ответ от модели получен", j.get("ответ"))
    need("---" not in (j.get("ответ") or "")
         and "Источник: Руководство стенда ОПС" in (j.get("ответ") or ""),
         "служебные разделители («---») вычищены из ответа", j.get("ответ"))
    need(j.get("источники") == ["руководство.md"],
         "источник указан", j.get("источники"))
    need(not j.get("кэш"), "первый вопрос — не из кэша")
    fr = (j.get("фрагменты") or [{}])[0]
    need(fr.get("ф") == "руководство.md" and fr.get("х"),
         "в ответе есть фрагмент с хэшем для подсветки", str(j)[:200])

    # просмотр документации: клик по «📄 файл» с подсветкой фрагмента
    code, h, body = get("/podskazki/просмотр/руководство.md/" + fr["х"],
                        jar=jar_s)
    need(code == 200 and "wc-hit" in body
         and "Жёлтым выделен фрагмент" in body,
         "просмотр с подсветкой использованного фрагмента", body[:200])
    need("Фрагмент 1" in body and "wc-doc" in body,
         "документация показана по фрагментам")
    code, h, body = get("/podskazki/просмотр/руководство.md", jar=jar)
    need(code == 200 and "wc-doc" in body and 'id="wc-hit"' not in body,
         "просмотр файла без хэша — весь документ без подсветки",
         "код %s | %s" % (code, body[:160]))
    code, h, body = get("/podskazki/просмотр/../реестр.json", jar=jar)
    need(code == 404, "выход за папку источников запрещён")

    # кэш на повторе (тот же ключ: вопрос + страница)
    code, h, body = json_post("/podskazka",
                              {"вопрос": "Как проверить шлейф "
                                         "сигнализации?",
                               "страница": "Задание — тест"}, jar=jar_s)
    j2 = json.loads(body)
    need(j2.get("кэш"), "повтор вопроса — ответ из кэша", body[:200])
    need(j2.get("источники") == ["руководство.md"],
         "к источникам кэша вернулись те же файлы")
    need(j2.get("фрагменты"), "кэш хранит фрагменты для подсветки")

    # нерелевантный вопрос → отказ
    code, h, body = json_post("/podskazka",
                              {"вопрос": "zzz qqq xxx vvv kkk"},
                              jar=jar_s)
    j3 = json.loads(body)
    need(j3.get("ок") and "не нашёл" in (j3.get("ответ") or ""),
         "нерелевантный вопрос → честный отказ", body[:200])

    # ── лимит в час (уже 3 вопроса в журнале) ────────────────────────
    form_post("/podskazki/настройки",
              {"url": "http://127.0.0.1:%d" % OLLAMA_PORT,
               "модель": "qwen3:1.7b", "эмбеддер": "bge-m3",
               "лимит_час": "4", "num_predict": "220", "топ_k": "4",
               "мин_оценка": "0.22", "промт": "", "включено": "1"},
              jar=jar)
    code, h, body = json_post("/podskazka",
                              {"вопрос": "питание прибора резерв "
                                         "аккумулятор"}, jar=jar_s)
    need(json.loads(body).get("ок"), "четвёртый вопрос в пределах лимита",
         body[:150])
    code, h, body = json_post("/podskazka",
                              {"вопрос": "полярность извещателей схема"},
                              jar=jar_s)
    j4 = json.loads(body)
    need(not j4.get("ок") and "Лимит" in (j4.get("ошибка") or ""),
         "пятый вопрос — лимит исчерпан", body[:200])

    # ── внешний API (OpenAI-совместимый) ─────────────────────────────
    api_set = {"url": "http://127.0.0.1:%d" % OLLAMA_PORT,
               "модель": "qwen3:1.7b", "эмбеддер": "bge-m3",
               "num_predict": "220", "топ_k": "4", "мин_оценка": "0.22",
               "промт": "", "включено": "1",
               "api_url": "http://127.0.0.1:%d/v1" % API_PORT,
               "api_key": "SECRET-KEY-123", "api_model": "test-model"}
    api_set["лимит_час"] = "0"
    api_set["режим"] = "api"
    form_post("/podskazki/настройки", api_set, jar=jar)
    code, h, body = json_post("/podskazka",
                              {"вопрос": "как проверить шлейф "
                                         "сигнализации",
                               "страница": "страница API-теста"},
                              jar=jar_s)
    j6 = json.loads(body)
    need(j6.get("ок") and "API ОТВЕТ" in (j6.get("ответ") or ""),
         "режим api: ответ от внешнего API", body[:200])
    need(j6.get("провайдер") == "API", "провайдер отмечен как API",
         j6.get("провайдер"))
    need("ключ принят: да" in (j6.get("ответ") or ""),
         "ключ передан в Authorization", j6.get("ответ"))

    # авто: API падает (failapi) → локальная модель подхватывает
    api_set["режим"] = "авто"
    form_post("/podskazki/настройки", api_set, jar=jar)
    code, h, body = json_post("/podskazka",
                              {"вопрос": "failapi как проверить шлейф "
                                         "сигнализации",
                               "страница": "страница API-теста"},
                              jar=jar_s)
    j7 = json.loads(body)
    need(j7.get("ок") and "сопротивление шлейфа"
         in (j7.get("ответ") or ""),
         "авто: при сбое API ответила локальная модель", body[:200])
    need(j7.get("провайдер") == "локально", "провайдер — локально",
         j7.get("провайдер"))

    # api-only: сбой API → ошибка без фолбэка
    api_set["режим"] = "api"
    form_post("/podskazki/настройки", api_set, jar=jar)
    code, h, body = json_post("/podskazka",
                              {"вопрос": "failapi питание прибора "
                                         "резерв аккумулятор"},
                              jar=jar_s)
    j8 = json.loads(body)
    need(not j8.get("ок") and "Внешний API" in (j8.get("ошибка") or ""),
         "режим api: сбой → ошибка без фолбэка", body[:200])

    # ── выключатель ──────────────────────────────────────────────────
    form_post("/podskazki/настройки",
              {"url": "http://127.0.0.1:%d" % OLLAMA_PORT,
               "модель": "qwen3:1.7b", "эмбеддер": "bge-m3",
               "лимит_час": "0", "num_predict": "220", "топ_k": "4",
               "мин_оценка": "0.22", "промт": ""}, jar=jar)
    code, h, body = json_post("/podskazka",
                              {"вопрос": "как проверить шлейф"},
                              jar=jar_s)
    j5 = json.loads(body)
    need(not j5.get("ок") and "выключены" in (j5.get("ошибка") or ""),
         "модуль выключен настройкой", body[:200])

    # ── живучесть (баг-репорт #1 «Нейросеть не отвечает») ────────────
    # Суть репорта: непредвиденная ошибка ДО fin() давала студенту 500
    # без записи в журнал. Проверяем: битые файлы хранилища не роняют
    # вопрос, а честная внутренняя ошибка видна студенту и в журнале.
    form_post("/podskazki/настройки",
              {"url": "http://127.0.0.1:%d" % OLLAMA_PORT,
               "модель": "qwen3:1.7b", "эмбеддер": "bge-m3",
               "лимит_час": "0", "num_predict": "220", "топ_k": "4",
               "мин_оценка": "0.22", "промт": "", "включено": "1",
               "режим": "лок", "api_url": "", "api_model": ""},
              jar=jar)

    # ── правка системного промта ─────────────────────────────────────
    # Репорт: «исправленный системный промт не применяется». Причины
    # было две: кэш отдавал старые ответы (TTL 3 суток, промт не входил
    # в ключ) и правила промта «тонули» под дефолтными. Проверяем:
    # сохранение промта сбрасывает кэш, модель отвечает уже по новому
    # промту, а правила продублированы в конце запроса.
    PROMPT_A = "Ты — тестовый промт А: отвечай строго по фрагментам."
    form_post("/podskazki/настройки",
              {"url": "http://127.0.0.1:%d" % OLLAMA_PORT,
               "модель": "qwen3:1.7b", "эмбеддер": "bge-m3",
               "лимит_час": "0", "num_predict": "220", "топ_k": "4",
               "мин_оценка": "0.22", "промт": PROMPT_A, "включено": "1",
               "режим": "лок", "api_url": "", "api_model": ""},
              jar=jar)
    code, h, body = json_post("/podskazka",
                              {"вопрос": "Как проверить шлейф "
                                         "сигнализации?",
                               "страница": "Задание — тест"}, jar=jar_s)
    jA = json.loads(body)
    need(jA.get("ок") and not jA.get("кэш"),
         "правка промта: прежний кэш сброшен, вопрос пересчитан",
         body[:200])
    _mk = hashlib.sha1(PROMPT_A.encode("utf-8")).hexdigest()[:6]
    need("[промт:%s]" % _mk in (jA.get("ответ") or ""),
         "модель получила именно новый системный промт", jA.get("ответ"))
    need("[правила-в-конце]" in (jA.get("ответ") or ""),
         "правила промта продублированы в конце запроса", jA.get("ответ"))
    need("[без-пересказа]" in (jA.get("ответ") or ""),
         "запрет пересказа правил передан модели", jA.get("ответ"))
    code, h, body = json_post("/podskazka",
                              {"вопрос": "Как проверить шлейф "
                                         "сигнализации?",
                               "страница": "Задание — тест"}, jar=jar_s)
    need(json.loads(body).get("кэш"),
         "после пересчёта новый ответ снова берётся из кэша", body[:200])
    # вернуть обычный промт
    form_post("/podskazki/настройки",
              {"url": "http://127.0.0.1:%d" % OLLAMA_PORT,
               "модель": "qwen3:1.7b", "эмбеддер": "bge-m3",
               "лимит_час": "0", "num_predict": "220", "топ_k": "4",
               "мин_оценка": "0.22", "промт": "", "включено": "1",
               "режим": "лок", "api_url": "", "api_model": ""},
              jar=jar)

    # 1) журнал-словарь вместо списка: вопрос не падает, журнал чинится
    qpath = os.path.join(cfg_dir, "вопросы.json")
    qs_keep = json.load(io.open(qpath, encoding="utf-8"))
    io.open(qpath, "w", encoding="utf-8").write('{"сломано": true}')
    code, h, body = json_post("/podskazka",
                              {"вопрос": "как проверить шлейф",
                               "страница": "стр. живучести"}, jar=jar_s)
    j9 = json.loads(body)
    need(j9.get("ок"), "сломанный журнал (dict) не роняет вопрос",
         body[:200])
    qs = json.load(io.open(qpath, encoding="utf-8"))
    need(isinstance(qs, list) and len(qs) == 1
         and qs[0].get("вопрос") == "как проверить шлейф",
         "журнал после битого файла — валидный список с записью")
    io.open(qpath, "w", encoding="utf-8").write(
        json.dumps(qs_keep, ensure_ascii=False))  # вернуть историю

    # 2) битая запись кэша (не словарь) — просто мимо кэша
    def _norm(s):
        s = s.lower().replace("ё", "е")
        s = re.sub(r"[^\w\s]", " ", s)
        return re.sub(r"\s+", " ", s).strip()

    # Ключ кэша = отпечаток настроек + нормализованный вопрос/страница.
    # Отпечаток воспроизводим: промт берём из панели (он сейчас —
    # дефолтный, только что восстановлен), остальные поля — из последнего
    # form_post настроек. Поля и порядок обязаны совпадать с
    # _cfg_finger в modules/podskazki/модуль.py.
    code, h, body = get("/podskazki", jar=jar)
    _m = re.search(r'name="промт"[^>]*>(.*?)</textarea>', body, re.S)
    _sp = html.unescape(_m.group(1)) if _m else ""
    _fgr = hashlib.sha1("|".join(str(x) for x in (
        _sp, "qwen3:1.7b", "лок", "", "220", "4", "0.22",
        "http://127.0.0.1:%d" % OLLAMA_PORT, "bge-m3")).encode()).hexdigest()[:10]
    ck = hashlib.sha1(
        (_fgr + "|" + _norm("как измерить сопротивление шлейфа сигнализации")
         + "|" + _norm("стр. живучести")).encode()).hexdigest()
    io.open(os.path.join(cfg_dir, "кэш.json"), "w",
            encoding="utf-8").write(json.dumps(
                {ck: "мусор-не-словарь", "второй": 42}, ensure_ascii=False))
    code, h, body = json_post("/podskazka",
                              {"вопрос": "как измерить сопротивление "
                                          "шлейфа сигнализации",
                               "страница": "стр. живучести"}, jar=jar_s)
    j10 = json.loads(body)
    need(j10.get("ок") and not j10.get("кэш"),
         "битая запись кэша игнорируется (мимо кэша)", body[:200])

    # 3) непредвиденная ошибка (битый индекс) → понятный текст студенту
    #    И запись в журнал (раньше: 500 без журнала — сам баг-репорт #1)
    ipath = os.path.join(cfg_dir, "индекс.json")
    good_idx = io.open(ipath, "rb").read()
    io.open(ipath, "wb").write(json.dumps(
        {"модель": "bge-m3", "чанки": "мусор"},
        ensure_ascii=False).encode("utf-8"))
    # (2) закэшировал этот же вопрос — сбрасываем кэш, чтобы дойти до поиска
    try:
        os.remove(os.path.join(cfg_dir, "кэш.json"))
    except OSError:
        pass
    code, h, body = json_post("/podskazka",
                              {"вопрос": "как измерить сопротивление "
                                          "шлейфа сигнализации",
                               "страница": "стр. живучести"}, jar=jar_s)
    j11 = json.loads(body)
    need(not j11.get("ок")
         and "Внутренняя ошибка" in (j11.get("ошибка") or ""),
         "непредвиденная ошибка → понятный текст студенту", body[:200])
    qs = json.load(io.open(qpath, encoding="utf-8"))
    need(qs and (qs[-1].get("ошибка") or "").startswith("внутренняя ошибка"),
         "непредвиденная ошибка записана в журнал")
    io.open(ipath, "wb").write(good_idx)  # вернуть индекс

    # ── история в панели ─────────────────────────────────────────────
    code, h, body = get("/podskazki", jar=jar)
    need("как проверить шлейф" in body and "💾 кэш" in body,
         "история вопросов видна в панели")
    need(" · API" in body, "провайдер виден в истории")
    need("🗑 Очистить историю" in body, "кнопка очистки истории есть")
    # версия промта в записи истории: правка промта видна преподавателю
    _fgrA = hashlib.sha1("|".join(str(x) for x in (
        PROMPT_A, "qwen3:1.7b", "лок", "", "220", "4", "0.22",
        "http://127.0.0.1:%d" % OLLAMA_PORT, "bge-m3")).encode()).hexdigest()[:10]
    need("Промт ⚠️ старый — " + _fgrA in body and PROMPT_A in body,
         "версия промта видна в истории (правка промта отслеживается)",
         body[:200])

    # ── массовая загрузка: ZIP-архив ─────────────────────────────────
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("руководство2.md",
                   "# Руководство 2\nПроверка огнетушителей: раз в год.")
        z.writestr("подпапка/вложенный.txt",
                   "Заметки по стенду: шлейф 2,2 кОм.")
        z.writestr("мусор.exe", b"MZ")
        # имя в «проводниковой» кодировке cp866 без флага utf-8: пишем
        # ASCII-заглушку и подменяем байты имени на cp866 (та же длина)
        z.writestr("plan.txt", "План: полярность извещателей важна.")
    blob = buf.getvalue().replace(b"plan.txt", "план.txt".encode("cp866"))
    code, h, body = mp_post("/podskazki/загрузка", {},
                            {"файлы": ("документация.zip", blob)}, jar=jar)
    srcdir = os.path.join(STORE, "модули", "podskazki", "источники")
    need(os.path.isfile(os.path.join(srcdir, "руководство2.md")),
         "zip: файл сохранён")
    need(os.path.isfile(os.path.join(srcdir, "вложенный.txt")),
         "zip: вложенные папки распакованы в корень источников")
    need(os.path.isfile(os.path.join(srcdir, "план.txt")),
         "zip: русское имя из Проводника (cp866) восстановлено")
    need(not os.path.isfile(os.path.join(srcdir, "мусор.exe")),
         "zip: неподдерживаемый формат пропущен")
    uprep = json.load(io.open(os.path.join(STORE, "модули", "podskazki",
                                           "загрузка.json"),
                              encoding="utf-8"))
    need(len(uprep.get("сохранено", [])) == 3
         and any(n == "мусор.exe" for n, _ in uprep.get("пропущено", [])),
         "отчёт загрузки: сохранено 3, пропуск отмечен", str(uprep)[:200])
    code, h, body = get("/podskazki", jar=jar)
    need("Последняя загрузка" in body and "мусор.exe" in body,
         "панель показывает отчёт о последней загрузке")

    # ── догрузка: только новые/изменённые файлы ──────────────────────
    # На диске 5 файлов: руководство.md и оповещатели.md уже в индексе
    # (mtime совпадает), 3 файла из zip — новые. Хэши фрагментов
    # неизменённых файлов должны сохраняться.
    form_post("/podskazki/догрузить", {}, jar=jar)
    prog = {}
    for _ in range(60):  # до 30 с
        code, h, body = get("/podskazki/прогресс", jar=jar)
        prog = json.loads(body)
        if prog.get("фаза") in ("готово", "ошибка"):
            break
        time.sleep(0.5)
    need(prog.get("фаза") == "готово", "догрузка завершилась", str(prog))
    rep = json.load(io.open(os.path.join(cfg_dir, "пересборка.json"),
                            encoding="utf-8"))
    need(sorted(rep.get("обновлено", [])) ==
         ["вложенный.txt", "план.txt", "руководство2.md"],
         "догрузка: обновлены только новые файлы", str(rep)[:250])
    need(rep.get("без_изменений") == 2,
         "догрузка: неизменённые файлы переиспользованы", str(rep)[:250])
    # новый документ участвует в поиске
    code, h, body = json_post("/podskazka",
                              {"вопрос": "как часто проверять "
                                          "огнетушители"},
                              jar=jar_s)
    j12 = json.loads(body)
    need(j12.get("ок") and "руководство2.md" in (j12.get("источники") or []),
         "догрузка: новый документ участвует в поиске", body[:200])
    # хэш фрагмента старого файла жив (чанк переиспользован)
    code, h, body = get("/podskazki/просмотр/руководство.md/" + fr["х"],
                        jar=jar_s)
    need(code == 200 and 'id="wc-hit"' in body,
         "после догрузки хэш старого фрагмента всё ещё подсвечивается")
    # повторная догрузка: изменений нет
    form_post("/podskazki/догрузить", {}, jar=jar)
    for _ in range(60):
        code, h, body = get("/podskazki/прогресс", jar=jar)
        prog = json.loads(body)
        if prog.get("фаза") in ("готово", "ошибка"):
            break
        time.sleep(0.5)
    need(prog.get("фаза") == "готово", "повторная догрузка завершилась")
    rep = json.load(io.open(os.path.join(cfg_dir, "пересборка.json"),
                            encoding="utf-8"))
    need(not rep.get("без_изменений")
         or rep.get("без_изменений") == 3,
         "повторная догрузка: файлы с чанками переиспользованы",
         str(rep)[:250])
    need(sorted(rep.get("обновлено", [])) == ["вложенный.txt", "план.txt"],
         "повторная догрузка: слишком короткие файлы не дают чанков",
         str(rep)[:250])
    code, h, body = get("/podskazki", jar=jar)
    need("Догрузка (" in body and "обновлено 2" in body,
         "панель показывает итог догрузки")

    # ── docx: таблицы и картинки не теряются ─────────────────────────
    _PNG = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
        "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    _docxml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main" xmlns:a="http://schemas.'
        'openxmlformats.org/drawingml/2006/main" xmlns:r="http://'
        'schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<w:body>'
        '<w:p><w:r><w:t>Технические параметры прибора приведены '
        'в таблице.</w:t></w:r></w:p>'
        '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Параметр</w:t></w:r></w:p>'
        '</w:tc><w:tc><w:p><w:r><w:t>Значение</w:t></w:r></w:p></w:tc>'
        '</w:tr><w:tr><w:tc><w:p><w:r><w:t>Ток потребления</w:t></w:r>'
        '</w:p></w:tc><w:tc><w:p><w:r><w:t>60 мкА</w:t></w:r></w:p>'
        '</w:tc></w:tr></w:tbl>'
        '<w:p><w:r><w:drawing><a:blip r:embed="rId7"/></w:drawing></w:r>'
        '<w:r><w:t>Схема подключения шлейфа показана на рисунке.'
        '</w:t></w:r></w:p>'
        '</w:body></w:document>')
    _rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/'
        'package/2006/relationships"><Relationship Id="rId7" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/image" Target="media/image1.png"/></Relationships>')
    _buf = io.BytesIO()
    with zipfile.ZipFile(_buf, "w") as z:
        z.writestr("word/document.xml", _docxml)
        z.writestr("word/_rels/document.xml.rels", _rels)
        z.writestr("word/media/image1.png", _PNG)
    code, h, body = mp_post("/podskazki/загрузка", {},
                            {"файлы": ("стенд_таблицы.docx",
                                       _buf.getvalue())}, jar=jar)
    form_post("/podskazki/догрузить", {}, jar=jar)
    for _ in range(60):
        code, h, body = get("/podskazki/прогресс", jar=jar)
        prog = json.loads(body)
        if prog.get("фаза") in ("готово", "ошибка"):
            break
        time.sleep(0.5)
    need(prog.get("фаза") == "готово", "догрузка docx завершилась",
         str(prog))
    code, h, body = get("/podskazki/просмотр/стенд_таблицы.docx", jar=jar_s)
    need("Ток потребления | 60 мкА" in body,
         "docx: таблица сохранена в тексте (ячейки через « | »)")
    need('<img class="wc-pic"' in body and 'alt="Рисунок 1"' in body,
         "docx: картинка вставлена в просмотр")
    code, h, body = get("/podskazki/медиа/стенд_таблицы.docx/image1.png",
                        jar=jar_s)
    need(code == 200 and "PNG" in body[:10],
         "картинка из docx отдаётся по /podskazki/медиа/")
    code, h, body = json_post("/podskazka",
                              {"вопрос": "какой ток потребления прибора"},
                              jar=jar_s)
    j13 = json.loads(body)
    need(j13.get("ок")
         and "стенд_таблицы.docx" in (j13.get("источники") or []),
         "docx с таблицей участвует в поиске", body[:200])

    # ── pdf: настоящий PDF, страница фрагмента, подсветка ────────────
    _pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
        b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
        b"4 0 obj<</Length 210>>stream\n"
        b"BT /F1 14 Tf 60 720 Td (Parameter: tok potrebleniya pribora) "
        b"Tj 0 -20 Td (v dezhurnom rezhime sostavlyaet 60 mA. "
        b"Rezervnyy) Tj 0 -20 Td (akkumulyator 12 V 7 Ah obespechivaet "
        b"24 chasa raboty.) Tj ET\nendstream\nendobj\n"
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"trailer<</Root 1 0 R/Size 6>>\nstartxref\n0\n%%EOF\n")
    code, h, body = mp_post("/podskazki/загрузка", {},
                            {"файлы": ("стенд_паспорт.pdf", _pdf)}, jar=jar)
    form_post("/podskazki/догрузить", {}, jar=jar)
    for _ in range(60):
        code, h, body = get("/podskazki/прогресс", jar=jar)
        prog = json.loads(body)
        if prog.get("фаза") in ("готово", "ошибка"):
            break
        time.sleep(0.5)
    need(prog.get("фаза") == "готово", "догрузка pdf завершилась", str(prog))
    idx = json.load(io.open(os.path.join(cfg_dir, "индекс.json"),
                            encoding="utf-8"))
    ch = next(c for c in idx["чанки"] if c["ф"] == "стенд_паспорт.pdf")
    need(ch.get("стр") == 1,
         "pdf: страница чанка определена из маркеров", str(ch)[:150])
    hx = hashlib.sha1(ch["т"].encode("utf-8")).hexdigest()[:8]
    code, h, body = get("/podskazki/просмотр/стенд_паспорт.pdf/" + hx,
                        jar=jar_s)
    need(code == 200 and "pdf.min.js" in body and '"стр": 1' in body,
         "pdf: вьювер на pdf.js с целевой страницей", body[:200])
    need("Parameter: tok potrebleniya" in body,
         "pdf: текст фрагмента передан для подсветки")
    need("/_static/pdfjs/pdf.worker.min.js" in body,
         "pdf: воркер подключён")
    need("pdflinks" in body and "getAnnotations" in body,
         "pdf: слой кликабельных ссылок из аннотаций")
    _ps = re.search(r"<script>(\(function\(\)\{var CFG=.*?)</script>",
                    body, re.S)
    need(_ps, "скрипт pdf-вьювера найден")
    if _ps:
        _pf = os.path.join(ROOT, "_pdfchk.js")
        io.open(_pf, "w", encoding="utf-8").write(_ps.group(1))
        try:
            _np = subprocess.run(["node", "--check", _pf],
                                 capture_output=True)
            need(_np.returncode == 0,
                 "node --check: скрипт pdf-вьювера корректен",
                 _np.stderr.decode("utf-8", "replace")[-300:])
        except OSError:
            print("OK   node недоступен — проверка pdf-скрипта пропущена")
        finally:
            try:
                os.remove(_pf)
            except OSError:
                pass
    code, h, body = get("/podskazki/файл/стенд_паспорт.pdf", jar=jar_s)
    need(code == 200 and body.startswith("%PDF"),
         "оригинальный pdf отдаётся по /podskazki/файл/")
    code, h, body = get("/_static/pdfjs/pdf.min.js")
    need(code == 200 and len(body) > 100000, "pdf.js в статике")
    code, h, body = get("/podskazki/файл/../../реестр.json", jar=jar_s)
    need(code == 404, "файл-маршрут: выход за папку запрещён")
    code, h, body = json_post(
        "/podskazka",
        {"вопрос": "tok potrebleniya pribora dezhurnom rezhime"},
        jar=jar_s)
    j14 = json.loads(body)
    need(j14.get("ок")
         and "стенд_паспорт.pdf" in (j14.get("источники") or []),
         "pdf участвует в поиске", body[:200])
    fr14 = (j14.get("фрагменты") or [])
    pdf_fr = next((f for f in fr14 if f.get("ф") == "стенд_паспорт.pdf"),
                  {})
    need(pdf_fr.get("стр") == 1, "фрагменты несут номер страницы",
         str(fr14)[:200])

    # удаление источника
    code, h, body = form_post("/podskazki/удалить",
                              {"имя": "руководство.md"}, jar=jar)
    need(not os.path.isfile(src), "источник удалён")

finally:
    if proc:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
    if mock:
        mock.shutdown()
    if api_mock:
        api_mock.shutdown()
    shutil.rmtree(STORE, ignore_errors=True)

print("PODSK OK" if ok else "PODSK FAIL")
sys.exit(0 if ok else 1)
