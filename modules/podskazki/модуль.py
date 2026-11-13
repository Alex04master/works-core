# -*- coding: utf-8 -*-
"""Подсказки: локальная нейросеть с опорой на загруженную документацию.

Студент: плавающая кнопка «🤖 Подсказка» → выдвижная панель-чат. Вопрос
уходит на сервер, там:
  1) проверяются лимиты и кэш частых вопросов;
  2) вопрос превращается в вектор (эмбеддер Ollama) и по косинусной
     близости ищутся ближайшие фрагменты загруженной документации;
  3) модель получает правила + топ-фрагменты + вопрос и отвечает ТОЛЬКО
     по документации, с указанием источника. Если релевантного фрагмента
     не нашлось — честный отказ без выдумок.

Преподаватель: страница /podskazki — статус Ollama, загрузка источников
(txt/md/docx/pdf), пересборка индекса, настройки, история вопросов.

Хранение (данные/модули/podskazki/):
  источники/   — файлы документации;
  индекс.json  — чанки + векторы (строится кнопкой «Пересобрать»);
  кэш.json     — ответы на повторяющиеся вопросы (сбрасывается при
                 пересборке); вопросы.json — журнал; настройки.json —
                 конфигурация.

Нейросеть — локальная Ollama (см. docs/ПЛАН-НЕЙРОПОДСКАЗКИ.md): по
умолчанию qwen3:1.7b с think:false и эмбеддер bge-m3. У гибридных qwen3
обязателен think:false на верхнем уровне запроса, иначе модель тратит
бюджет токенов на размышления и возвращает пустой ответ.
"""
import hashlib
import html
import io
import json
import math
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timedelta

MAX_SRC = 20 * 1024 * 1024  # 20 МБ на файл источника
MAX_ZIP = 100 * 1024 * 1024        # размер ZIP-архива
MAX_ZIP_FILES = 300                # файлов в одном архиве
MAX_ZIP_UNPACK = 300 * 1024 * 1024  # суммарно распаковано за архив
# версия извлечения текста: сменилась — «⚡ Только новое» само сделает
# полную переобработку (иначе старые чанки без таблиц/картинок остались бы)
ИЗВ_ВЕРСИЯ = "3"

# Страница просмотра документации (клик по «📄 файл» в шторке)
_VIEW_CSS = (
    '<style>'
    '.wc-doc{background:#fafafa;border:1px solid #e0e0e0;border-radius:8px;'
    'padding:4px 16px;white-space:pre-wrap;word-wrap:break-word;'
    'font-size:14px;line-height:1.55;margin-top:10px}'
    '.wc-doc>div{padding:10px 0;border-bottom:1px dashed #e6e6e6}'
    '.wc-doc>div:last-child{border-bottom:none}'
    '.wc-doc-n{font-size:11px;color:#999;margin-bottom:2px}'
    '.wc-hit{background:#fff3b0;box-shadow:0 0 0 6px #fff3b0;'
    'border-radius:4px;animation:wcflash 1s ease-out 2}'
    '@keyframes wcflash{0%{background:#ffd54f}100%{background:#fff3b0}}'
    '.wc-pic{max-width:100%;max-height:420px;border:1px solid #e0e0e0;'
    'border-radius:6px;margin:6px 0;display:block}'
    '.wc-page{display:inline-block;background:#eef1f4;color:#888;'
    'border-radius:6px;padding:1px 8px;font-size:11px;margin:2px 0}'
    '.wc-nopic{background:#fff3d6;border-radius:4px;padding:1px 6px;'
    'color:#8a6d1a}'
    'html.dark .wc-doc{background:#1e293b;border-color:#334155}'
    'html.dark .wc-doc>div{border-bottom-color:#334155}'
    'html.dark .wc-doc-n{color:#64748b}'
    'html.dark .wc-page{background:#334155;color:#94a3b8}'
    'html.dark .wc-hit{background:rgba(250,204,21,.28);'
    'box-shadow:0 0 0 6px rgba(250,204,21,.28)}'
    'html.dark .wc-nopic{background:rgba(245,158,11,.15);color:#fbbf24}'
    'html.dark .wc-pic{border-color:#334155}'
    '</style>')

# ── просмотрщик PDF (pdf.js из статики, работает офлайн): открывает
# оригинальный файл, прыгает на страницу фрагмента и подсвечивает его
_PDF_HTML = (
    '<style>'
    '.pdfbar{position:sticky;top:0;background:#fff;'
    'border-bottom:1px solid #e0e0e0;padding:8px 10px;display:flex;'
    'gap:8px;align-items:center;z-index:5;flex-wrap:wrap}'
    '.pdfbar button{border:1px solid #c9d2d8;background:#f5f7f8;'
    'border-radius:6px;padding:4px 10px;cursor:pointer;font:inherit}'
    '.pdfbar input{padding:4px 6px;border:1px solid #c9d2d8;'
    'border-radius:6px;width:5.5em;font:inherit}'
    '#pdfwrap{position:relative;overflow:auto;background:#525659;'
    'height:calc(100vh - 60px);text-align:center}'
    '#pdfbox{position:relative;display:inline-block;margin:8px auto}'
    '#pdfbox>canvas{display:block;box-shadow:0 2px 10px rgba(0,0,0,.4)}'
    '.pdf-ov{pointer-events:none;position:absolute;left:0;top:0}'
    '#pdflinks{position:absolute;left:0;top:0;width:100%;height:100%;'
    'pointer-events:none}'
    '#pdflinks a{position:absolute;pointer-events:auto;border-radius:2px}'
    'html.dark .pdfbar{background:#1e293b;border-bottom-color:#334155}'
    'html.dark .pdfbar button{background:#0f172a;border-color:#334155;'
    'color:#e2e8f0}'
    'html.dark .pdfbar input{background:#0f172a;color:#e2e8f0;'
    'border-color:#334155}'
    'html.dark .pdfbar .hint{color:#94a3b8}'
    '</style>'
    '<div class="pdfbar">'
    '<button id="pf-prev">◀</button>'
    '<span>стр. <input id="pf-page" type="number" min="1" value="1">'
    ' из <span id="pf-cnt">…</span></span>'
    '<button id="pf-next">▶</button>'
    '<button id="pf-zoom-out">−</button>'
    '<button id="pf-zoom-in">+</button>'
    '<span id="pf-hint" class="hint"></span>'
    '</div>'
    '<div id="pdfwrap"><div id="pdfbox">'
    '<canvas id="pdfcv"></canvas>'
    '<div id="pdflinks"></div></div></div>'
    '<script src="/_static/pdfjs/pdf.min.js"></script>'
    '<script>(function(){'
    'var CFG=__CFG__,W=document.getElementById("pdfwrap"),'
    'box=document.getElementById("pdfbox"),'
    'cv=document.getElementById("pdfcv"),'
    'hint=document.getElementById("pf-hint"),'
    'doc=null,cur=CFG.стр||1,zoom=0;'
    'pdfjsLib.GlobalWorkerOptions.workerSrc='
    '"/_static/pdfjs/pdf.worker.min.js";'
    'function norm(s){return String(s||"").toLowerCase()'
    '.replace(/\\s+/g," ").trim()}'
    'function say(t){hint.textContent=t}'
    'function render(n){'
    'if(n<1||n>doc.numPages)return;'
    'doc.getPage(n).then(function(page){'
    'cur=n;document.getElementById("pf-page").value=n;'
    'var v0=page.getViewport({scale:1});'
    'var s=Math.max(.4,Math.min(2.5,'
    '(W.clientWidth-14)/v0.width))+zoom;'
    'var vp=page.getViewport({scale:s});'
    'cv.width=vp.width;cv.height=vp.height;'
    'page.render({canvasContext:cv.getContext("2d"),viewport:vp});'
    'if(n===(CFG.стр||1))highlight(page,vp);'
    'links(page,vp);'
    '})}'
    'function highlight(page,vp){'
    'var q=norm(CFG.запрос);'
    'if(!q){say("");return}'
    'page.getTextContent().then(function(tc){'
    'var items=tc.items,all=[],total="",i,t;'
    'for(i=0;i<items.length;i++){'
    't=norm(items[i].str);if(!t)continue;'
    'all.push({it:items[i],a:total.length,b:total.length+t.length});'
    'total+=(total?" ":"")+t}'
    'var L=Math.min(q.length,160),p=-1;'
    'while(L>=20&&p<0){p=total.indexOf(q.slice(0,L));'
    'if(p<0)L=Math.floor(L/2)}'
    'if(p<0){say("фрагмент не найден — открыта страница "'
    '+(CFG.стр||1));return}'
    'var a=p,b=p+L,ov=document.createElement("canvas");'
    'ov.width=cv.width;ov.height=cv.height;'
    'ov.className="pdf-ov";'
    'var g=ov.getContext("2d");'
    'g.fillStyle="rgba(255,214,0,.45)";'
    'var first=null;'
    'for(i=0;i<all.length;i++){'
    'if(all[i].b>a&&all[i].a<b){'
    'var tx=pdfjsLib.Util.transform(vp.transform,'
    'all[i].it.transform);'
    'var h=Math.hypot(tx[2],tx[3]),'
    'w=(all[i].it.width||0)*vp.scale;'
    'g.fillRect(tx[4],tx[5]-h,w,h*1.25);'
    'if(first===null||tx[5]-h<first)first=tx[5]-h}}'
    'box.appendChild(ov);'
    'if(first!==null)W.scrollTop=Math.max(0,first-80);'
    'say("использованный фрагмент подсвечен")})}'
    'function links(page,vp){'
    'page.getAnnotations().then(function(list){'
    'var L=document.getElementById("pdflinks");L.innerHTML="";'
    'for(var i=0;i<list.length;i++){'
    'var a=list[i];if(a.subtype!=="Link")continue;'
    'var el=document.createElement("a");'
    'el.style.cssText=rectCss(a.rect,vp);'
    'if(a.url){el.href=a.url;el.target="_blank";el.rel="noopener";'
    'el.title="Открыть ссылку"}'
    'else if(a.dest){el.href="#";el.title="Перейти в документе";'
    '(function(d){el.onclick=function(ev){ev.preventDefault();'
    'var go=function(arr){doc.getPageIndex(arr[0]).then(function(ix){'
    'render(ix+1)},function(){})};'
    'if(typeof d=="string")doc.getDestination(d).then(go)'
    '.catch(function(){});else go(d)}})(a.dest)}'
    'else continue;'
    'L.appendChild(el)}})}'
    'function rectCss(r,vp){'
    'var p1=vp.convertToViewportPoint(r[0],r[1]),'
    'p2=vp.convertToViewportPoint(r[2],r[3]),'
    'l=Math.min(p1[0],p2[0]),t=Math.min(p1[1],p2[1]);'
    'return "left:"+l+"px;top:"+t+"px;width:"'
    '+Math.abs(p2[0]-l)+"px;height:"+Math.abs(p2[1]-t)+"px"}'
    'document.getElementById("pf-prev").onclick=function(){'
    'render(cur-1)};'
    'document.getElementById("pf-next").onclick=function(){'
    'render(cur+1)};'
    'var pi=document.getElementById("pf-page");'
    'pi.onchange=function(){render(parseInt(pi.value,10)||1)};'
    'document.getElementById("pf-zoom-out").onclick=function(){'
    'zoom-=0.15;render(cur)};'
    'document.getElementById("pf-zoom-in").onclick=function(){'
    'zoom+=0.15;render(cur)};'
    'pdfjsLib.getDocument("/podskazki/файл/"'
    '+encodeURIComponent(CFG.файл)).promise.then(function(d){'
    'doc=d;document.getElementById("pf-cnt").textContent=d.numPages;'
    'if(cur>d.numPages)cur=d.numPages;render(cur)},'
    'function(e){say("не удалось открыть PDF: "+e)});'
    '})();</script>'
)
TXT_EXT = (".txt", ".md", ".markdown", ".log", "")
GOOD_EXT = (".txt", ".md", ".markdown", ".log", ".docx", ".pdf")
BATCH = 16  # текстов на один вызов эмбеддера

УМОЛЧ = {
    "включено": True,
    "url": "http://127.0.0.1:11434",
    "модель": "qwen3:1.7b",
    "эмбеддер": "bge-m3",
    # внешний провайдер генерации (OpenAI-совместимый API): url + ключ.
    # Эмбеддинги ВСЕГДА локальные — документы не уходят наружу.
    "режим": "лок",       # лок | api | авто (API → при сбое локально)
    "api_url": "",        # напр. https://api.proxyapi.ru/openai/v1
    "api_key": "",
    "api_model": "",
    "лимит_час": 10,       # вопросов на студента в час (0 = без лимита)
    "топ_k": 4,            # фрагментов в промпт
    "мин_оценка": 0.22,    # порог релевантности (косинус)
    "num_predict": 220,    # максимум токенов ответа
    "num_ctx": 4096,       # контекст модели
    "системный_промт": (
        "Ты — ассистент-подсказчик в учебной СДО. Отвечай ТОЛЬКО по "
        "приведённым фрагментам документации. Называй источник (файл, "
        "раздел). Если ответа во фрагментах нет — прямо скажи об этом "
        "и предложи спросить преподавателя. Не выдумывай цифры и "
        "названия устройств. Отвечай по-русски, по шагам, кратко."),
}

ОТКАЗ = ("В загруженной документации я не нашёл ничего по вашему "
         "вопросу. Попробуйте переформулировать (используйте термины "
         "из задания) или спросите преподавателя.")


def register(ctx):
    _lock = threading.RLock()
    _build_lock = threading.Lock()
    _gen_sem = threading.Semaphore(2)   # не топим Ollama параллельными чатами
    _idx = {"mtime": None, "idx": None}  # индекс в памяти (mtime-кэш)
    _prog = {"фаза": ""}                 # прогресс пересборки индекса

    def _e(v):
        return html.escape(str(v if v is not None else ""), quote=True)

    # ── настройки и хранилище ────────────────────────────────────────
    def _st():
        s = dict(УМОЛЧ)
        sv = ctx.kv_load("настройки.json", {})
        if isinstance(sv, dict):  # битый/нечитаемый файл — работаем на умолч.
            s.update(sv)
        return s

    def _kv_save(name, obj):
        """kv_save с повторами. На Windows os.replace падает transient-
        ошибкой, если файл в этот миг открыт читателем (параллельный
        вопрос, антивирус) — повтор через паузу спасает запись."""
        last = None
        for i in range(4):
            try:
                ctx.kv_save(name, obj)
                return
            except OSError as ex:
                last = ex
                time.sleep(0.12 * (i + 1))
        raise last

    def _questions():
        # ВАЖНО: kv_load при нечитаемом файле возвращает {} — если журнал
        # вдруг не список (transient-ошибка чтения, чужая запись), дальше
        # .append()/r.get() уронили бы запрос (репорт #1 «Нейросеть
        # не отвечает»: 500 без записи в журнал)
        qs = ctx.kv_load("вопросы.json", [])
        return qs if isinstance(qs, list) else []

    def _save_questions(qs):
        _kv_save("вопросы.json", qs)

    def _cache():
        c = ctx.kv_load("кэш.json", {})
        return c if isinstance(c, dict) else {}

    def _save_cache(c):
        _kv_save("кэш.json", c)

    def _norm(s):
        s = s.lower().replace("ё", "е")
        s = re.sub(r"[^\w\s]", " ", s)
        return re.sub(r"\s+", " ", s).strip()

    # ── Ollama: базовые вызовы ───────────────────────────────────────
    def _api(st, path, payload, timeout, method="POST"):
        url = st["url"].rstrip("/") + path
        data = json.dumps(payload).encode("utf-8") if payload is not None \
            else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type":
                                              "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def _ollama_tags(st):
        try:
            return _api(st, "/api/tags", None, 5, method="GET")
        except Exception:
            return None

    def _embed(st, texts):
        d = _api(st, "/api/embed", {"model": st["эмбеддер"],
                                    "input": texts}, 300)
        vecs = d.get("embeddings") or []
        if len(vecs) < len(texts):
            # иначе [0] в ask() дал бы IndexError до fin() — 500 без журнала
            raise RuntimeError("эмбеддер вернул %d векторов на %d текстов"
                               % (len(vecs), len(texts)))
        return vecs

    def _chat(st, messages):
        payload = {"model": st["модель"], "messages": messages,
                   "stream": False,
                   "options": {"temperature": 0.2,
                               "num_ctx": int(st.get("num_ctx", 4096)),
                               "num_predict": int(st.get("num_predict",
                                                         220))}}
        m = str(st["модель"]).lower()
        if m.startswith("qwen3") and "instruct" not in m:
            payload["think"] = False  # иначе всё уйдёт в размышления
        d = _api(st, "/api/chat", payload, 300)
        return (d.get("message") or {}).get("content", "")

    def _chat_api(st, messages):
        """Генерация через внешний OpenAI-совместимый API."""
        payload = {"model": st.get("api_model") or st["модель"],
                   "messages": messages, "temperature": 0.2,
                   "max_tokens": int(st.get("num_predict", 220))}
        req = urllib.request.Request(
            st["api_url"].rstrip("/") + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + st.get("api_key", "")})
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.loads(r.read().decode("utf-8"))
        return ((d.get("choices") or [{}])[0].get("message")
                or {}).get("content", "")

    # ── извлечение текста из источников ──────────────────────────────
    def _extract(path):
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext in TXT_EXT:
                raw = open(path, "rb").read()
                for enc in ("utf-8", "cp1251"):
                    try:
                        return raw.decode(enc), None
                    except UnicodeDecodeError:
                        continue
                return raw.decode("utf-8", "replace"), None
            if ext == ".docx":
                doc = os.path.basename(path)
                with zipfile.ZipFile(path) as z:
                    xml = z.read("word/document.xml").decode(
                        "utf-8", "replace")
                    # картинки: blip-ссылки -> маркеры в тексте, сами
                    # файлы распаковываем в источники_медиа/<док>/
                    pics = {}
                    try:
                        rels = z.read(
                            "word/_rels/document.xml.rels").decode(
                            "utf-8", "replace")
                        for m in re.finditer(
                                r'Id="(rId\d+)"[^>]*Target="([^"]+)"',
                                rels):
                            t = m.group(2).lstrip("/")
                            if "/media/" in t or t.startswith("media/"):
                                pics[m.group(1)] = os.path.basename(t)
                    except (KeyError, OSError, ValueError):
                        pass
                    media_dir = os.path.join(ctx.data_dir,
                                             "источники_медиа", doc)
                    zimg = [n for n in z.namelist()
                            if n.startswith("word/media/")]
                    if zimg:
                        os.makedirs(media_dir, exist_ok=True)
                        for n in zimg:
                            with open(os.path.join(
                                    media_dir, os.path.basename(n)),
                                    "wb") as f:
                                f.write(z.read(n))
                    else:
                        shutil.rmtree(media_dir, ignore_errors=True)
                    nn = [0]

                    def _blip(m):
                        rid = re.search(r'r:embed="(rId\d+)"', m.group(0))
                        fn = pics.get(rid.group(1), "") if rid else ""
                        nn[0] += 1
                        return "\n[Рисунок %d: %s]\n" % (
                            nn[0], fn or "неизвестен")

                    def _cell(c):
                        t = re.sub(r"</w:p>", "\n", c)
                        t = re.sub(r"<w:tab[^>]*/>", " ", t)
                        t = html.unescape(re.sub(r"<[^>]+>", "", t))
                        return " ".join(t.split())

                    def _tbl(m):
                        rows = []
                        for tr in re.findall(r"<w:tr[ >].*?</w:tr>",
                                             m.group(0), re.S):
                            cells = [_cell(c) for c in re.findall(
                                r"<w:tc[ >].*?</w:tc>", tr, re.S)]
                            if any(cells):
                                rows.append(" | ".join(cells))
                        return "\n" + "\n".join(rows) + "\n"

                    # сначала картинки, затем таблицы (изнутри — вложенные)
                    xml = re.sub(r"<a:blip\b[^>]*>", _blip, xml)
                    for _ in range(3):
                        new = re.sub(r"<w:tbl>(?:(?!<w:tbl>).)*?</w:tbl>",
                                     _tbl, xml, flags=re.S)
                        if new == xml:
                            break
                        xml = new
                xml = re.sub(r"</w:p>", "\n", xml)
                xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
                txt = html.unescape(re.sub(r"<[^>]+>", "", xml))
                return re.sub(r"\n{3,}", "\n\n", txt), None
            if ext == ".pdf":
                try:
                    from pypdf import PdfReader
                except ImportError:
                    return None, ("PDF пропущен: для .pdf нужен пакет "
                                  "pypdf (только в инструменте, сервер "
                                  "его не требует)")
                reader = PdfReader(path)
                parts = []
                for i, p in enumerate(reader.pages, 1):
                    t = p.extract_text() or ""
                    n_img = 0
                    try:
                        xo = (p.get("/Resources") or {}).get("/XObject")
                        if xo:
                            xo = xo.get_object()
                            n_img = sum(
                                1 for k in xo
                                if xo[k].get_object().get("/Subtype")
                                == "/Image")
                    except Exception:
                        n_img = 0
                    head = "[Страница %d]" % i
                    if n_img:
                        head += " [Рисунков: %d]" % n_img
                    parts.append(head + "\n" + (t or "").strip())
                return "\n\n".join(parts), None
            return None, "формат не поддерживается (txt, md, docx, pdf)"
        except Exception as ex:
            return None, "не прочитан: %s" % ex

    def _chunks(text, size=800, overlap=150):
        text = re.sub(r"\r\n?", "\n", text)
        paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        out = []
        cur = ""

        def close():
            out.append(cur.strip())

        for p in paras:
            if len(p) > size:  # огромный абзац: режем по предложениям
                for s in re.split(r"(?<=[.!?;])\s+", p):
                    if not s:
                        continue
                    if len(cur) + len(s) + 1 <= size:
                        cur = (cur + " " + s).strip()
                    else:
                        if cur:
                            close()
                        cur = s[:size]
            elif len(cur) + len(p) + 2 <= size:
                cur = (cur + "\n" + p).strip()
            else:
                if cur:
                    close()
                tail = cur[-overlap:] if len(cur) > overlap else cur
                cur = (tail + "\n" + p).strip()
        if cur:
            close()
        return [c for c in out if len(c) >= 40]  # мусорные обрезки — мимо

    def _rebuild_run(only_new=False):
        st = _st()
        src = os.path.join(ctx.data_dir, "источники")
        os.makedirs(src, exist_ok=True)
        files = sorted(f for f in os.listdir(src)
                       if os.path.splitext(f)[1].lower() in GOOD_EXT)
        # старый индекс: переиспользуем чанки файлов без изменений
        old = _load_index() or {}
        stale_ver = old.get("извлечение") != ИЗВ_ВЕРСИЯ
        old_chunks = {}
        for c in old.get("чанки", []):
            old_chunks.setdefault(c.get("ф"), []).append(
                (c.get("т", ""), c.get("в"), c.get("н") or 1.0,
                 c.get("стр")))
        old_mt = old.get("файлы", {})
        if not isinstance(old_mt, dict):
            old_mt = {}
        _prog.update({"фаза": "чтение", "сделано": 0, "всего": len(files),
                      "ошибка": ""})
        report = {"время": datetime.now().isoformat(timespec="seconds"),
                  "файлов": len(files), "чанков": 0, "обновлено": [],
                  "без_изменений": 0, "предупреждения": [], "ошибка": ""}
        raw = []    # (файл, текст чанка, страница) — требуют эмбеддинга
        chunks = [] # готовые чанки (переиспользованные + новые)
        changed = []
        for n, fn in enumerate(files, 1):
            _prog.update({"сделано": n})
            path = os.path.join(src, fn)
            try:
                mt = os.path.getmtime(path)
            except OSError:
                mt = None
            reuse = (only_new and not stale_ver
                     and fn in old_chunks
                     and mt is not None and old_mt.get(fn) == mt)
            if reuse:
                for txt, vec, nrm, pg in old_chunks[fn]:
                    if vec is not None:
                        chunks.append({"ф": fn, "т": txt, "в": vec,
                                       "н": nrm, "стр": pg})
                report["без_изменений"] += 1
                continue
            changed.append(fn)
            text, warn = _extract(path)
            if warn:
                report["предупреждения"].append("%s: %s" % (fn, warn))
                continue
            if not (text or "").strip():
                report["предупреждения"].append("%s: пустой" % fn)
                continue
            page_texts = None
            if fn.lower().endswith(".pdf"):
                # страницы из маркеров извлечения: чанк -> страница
                page_texts = [
                    re.sub(r"\s+", " ", p).lower().strip()
                    for p in re.split(
                        r"\n?\[Страница \d+\](?: \[Рисунков: \d+\])?\n?",
                        text)]
            for ch in _chunks(text):
                pg = None
                if page_texts:
                    low = re.sub(r"\[Страница \d+\](?: \[Рисунков: \d+\])?",
                                 " ", ch)
                    low = re.sub(r"\[Рисунков: \d+\]", " ", low)
                    low = re.sub(r"\s+", " ", low).lower().strip()

                    def _find(sub):
                        return next((i for i, p in enumerate(page_texts)
                                     if i and p and sub in p), None)

                    pg = _find(low)
                    if pg is None and len(low) > 200:
                        pg = _find(low[-200:]) or _find(low[:200])
                raw.append((fn, ch, pg))
        if not raw and not chunks:
            report["ошибка"] = ("нечего индексировать — загрузите "
                                "документацию на странице источников")
            _prog.update({"фаза": "ошибка", "ошибка": report["ошибка"]})
            _kv_save("пересборка.json", report)
            return
        if raw:
            _prog.update({"фаза": "эмбеддинги", "сделано": 0,
                          "всего": len(raw)})
            vecs = []
            try:
                for i in range(0, len(raw), BATCH):
                    vecs.extend(_embed(st, [r[1] for r in
                                            raw[i:i + BATCH]]))
                    _prog.update({"сделано": min(i + BATCH, len(raw))})
            except Exception as ex:
                report["ошибка"] = "эмбеддер: %s" % ex
                _prog.update({"фаза": "ошибка", "ошибка": report["ошибка"]})
                _kv_save("пересборка.json", report)
                return
            if len(vecs) != len(raw):
                report["ошибка"] = ("эмбеддер вернул %d векторов на %d "
                                    "чанков" % (len(vecs), len(raw)))
                _prog.update({"фаза": "ошибка", "ошибка": report["ошибка"]})
                _kv_save("пересборка.json", report)
                return
            for (fn, txt, pg), v in zip(raw, vecs):
                n = math.sqrt(sum(x * x for x in v)) or 1.0
                chunks.append({"ф": fn, "т": txt, "в": v, "н": round(n, 6),
                               "стр": pg})
        else:
            # эмбеддить нечего (например, догрузка без изменений):
            # индекс и кэш не трогаем вовсе
            report["обновлено"] = changed
            report["чанков"] = len(chunks)
            _kv_save("пересборка.json", report)
            _prog.update({"фаза": "готово", "сделано": len(chunks),
                          "всего": len(chunks)})
            ctx.log("догрузка: изменений нет — %d файлов без изменений, "
                    "%d чанков" % (report["без_изменений"], len(chunks)))
            return
        report["обновлено"] = changed
        idx = {"модель": st["эмбеддер"], "построен": report["время"],
               "извлечение": ИЗВ_ВЕРСИЯ,
               "файлы": {fn: os.path.getmtime(os.path.join(src, fn))
                         for fn in files},
               "чанки": chunks}
        _kv_save("индекс.json", idx)
        _idx["mtime"] = None
        _idx["idx"] = None
        # устареть могли только ответы, опиравшиеся на изменённые файлы
        with _lock:
            if only_new:
                stale = set(changed)
                cache = {k: v for k, v in _cache().items()
                         if not (set(v.get("источники") or []) & stale
                                 if isinstance(v, dict) else True)}
            else:
                cache = {}
            _save_cache(cache)
        report["чанков"] = len(chunks)
        _kv_save("пересборка.json", report)
        _prog.update({"фаза": "готово", "сделано": len(chunks),
                      "всего": len(chunks)})
        if only_new:
            ctx.log("догрузка индекса: обновлено %d файлов (+%d чанков), "
                    "без изменений %d, всего %d чанков"
                    % (len(changed), len(raw), report["без_изменений"],
                       len(chunks)))
        else:
            ctx.log("индекс пересобран: %d чанков из %d файлов"
                    % (len(chunks), len(files)))

    def _rebuild_async(only_new=False):
        """Запустить пересборку фоном. False, если уже идёт.
        only_new: догрузка — эмбеддятся только новые/изменённые файлы."""
        if not _build_lock.acquire(False):
            return False
        _prog.update({"фаза": "старт", "сделано": 0, "всего": 0,
                      "ошибка": ""})

        def run():
            try:
                _rebuild_run(only_new)
            except Exception as ex:
                msg = "%s: %s" % (type(ex).__name__, ex)
                _prog.update({"фаза": "ошибка", "ошибка": msg})
                rep = ctx.kv_load("пересборка.json", {})
                rep["ошибка"] = msg
                rep["время"] = datetime.now().isoformat(timespec="seconds")
                _kv_save("пересборка.json", rep)
            finally:
                _build_lock.release()

        threading.Thread(target=run, daemon=True).start()
        return True

    def _load_index():
        path = ctx.data_file("индекс.json")
        try:
            mt = os.path.getmtime(path)
        except OSError:
            return None
        if _idx["mtime"] == mt and _idx["idx"] is not None:
            return _idx["idx"]
        idx = ctx.kv_load("индекс.json", {})
        idx = idx if idx.get("чанки") else None
        _idx["mtime"] = mt
        _idx["idx"] = idx
        return idx

    def _search(idx, qvec, k, min_score):
        qn = math.sqrt(sum(x * x for x in qvec)) or 1.0
        scored = []
        for c in idx["чанки"]:
            dot = 0.0
            for a, b in zip(qvec, c["в"]):
                dot += a * b
            score = dot / (qn * (c.get("н") or 1.0))
            if score >= min_score:
                scored.append((score, c))
        scored.sort(key=lambda x: -x[0])
        return [(c, s) for s, c in scored[:max(1, int(k or 1))]]

    # ── журнал вопросов ──────────────────────────────────────────────
    def _log(st_, q, page, answer, sources, cached, sec, err,
             фио, группа, sid, prov=""):
        # Журнал обязан пережить любые проблемы с файлом: иначе падение
        # записи теряло и запись, и ответ студенту (репорт #1).
        try:
            with _lock:
                qs = _questions()
                qs.append({
                    "время": datetime.now().isoformat(timespec="seconds"),
                    "студент": sid, "фио": фио, "группа": группа,
                    "вопрос": q[:400], "страница": page,
                    "ответ": (answer or "")[:4000],
                    "источники": sources, "кэш": bool(cached),
                    "сек": round(sec, 1), "ошибка": (err or "")[:200],
                    "провайдер": prov,
                })
                if len(qs) > 2000:
                    qs = qs[-2000:]
                _save_questions(qs)
        except Exception as ex:
            ctx.log("журнал вопросов не записан (%s: %s) — вопрос: %r"
                    % (type(ex).__name__, ex, q[:80]))

    def _err(handler, msg, hint=""):
        handler._send_json(200, {"ок": False, "ошибка": msg,
                                 "подсказка": hint})
        return handler._SENT

    def _ok(handler, answer, sources, cached, sec, prov="", фрагменты=None):
        handler._send_json(200, {"ок": True, "ответ": answer,
                                 "источники": sources,
                                 "фрагменты": фрагменты or [],
                                 "кэш": bool(cached), "сек": round(sec, 1),
                                 "провайдер": prov})
        return handler._SENT

    # ── студент задаёт вопрос ────────────────────────────────────────
    @ctx.add_route("POST", "/podskazka", access="any")
    def ask(handler, params):
        """Обёртка: ЛЮБАЯ непредвиденная ошибка → понятный JSON студенту +
        запись в журнал. Раньше исключение до fin() превращалось в 500 с
        телом {"error": ...} (шторка показывала «Ошибка подсказок»), а
        журнал молчал — так выглядел баг-репорт #1 «Нейросеть не отвечает»."""
        t0 = time.time()
        st = _st()
        sid = ""
        try:
            sid = handler._student() or ""
        except Exception:
            pass
        q, page, фио, группа = "", "", "не залогинен", ""
        try:
            data = handler._parse_post()
            if isinstance(data, dict):
                q = str(data.get("вопрос") or "").strip()[:1000]
                page = str(data.get("страница") or "").strip()[:200]
            stu = ctx.get_student(sid) if sid else None
            фио = (stu or {}).get("fio", "") or "не залогинен"
            группа = (stu or {}).get("group", "")
        except Exception:
            pass
        try:
            return _ask(handler, st, t0, q, page, фио, группа, sid)
        except Exception as ex:
            msg = "%s: %s" % (type(ex).__name__, ex)
            try:
                _log(st, q, page, "", [], False, time.time() - t0,
                     "внутренняя ошибка: " + msg, фио, группа, sid, "")
            except Exception:
                pass
            return _err(handler,
                        "Внутренняя ошибка модуля подсказок (%s). "
                        "Попробуйте ещё раз через минуту; если повторится — "
                        "сообщите преподавателю." % type(ex).__name__)

    def _ask(handler, st, t0, q, page, фио, группа, sid):
        def fin(answer, sources, cached, err="", prov="", фрагменты=None):
            sec = time.time() - t0
            _log(st, q, page, answer, sources, cached, sec, err,
                 фио, группа, sid, prov)
            if err and not answer:
                return _err(handler, err)
            return _ok(handler, answer or "", sources, cached, sec, prov,
                       фрагменты)

        if not st.get("включено", True):
            return fin("", [], False, "Подсказки сейчас выключены "
                                      "преподавателем.")
        if len(q) < 2:
            return fin("", [], False, "Пустой вопрос.")
        limit = int(st.get("лимит_час", 10) or 0)
        if limit and sid:
            edge = (datetime.now() - timedelta(hours=1)).isoformat(
                timespec="seconds")
            with _lock:  # журнал читается под замком: соседний fin() может
                n = sum(1 for r in _questions()  # в этот миг заменять файл
                        if r.get("студент") == sid
                        and str(r.get("время", "")) > edge)
            if n >= limit:
                return fin("", [], False, "Лимит подсказок исчерпан "
                                           "(%d в час). Спросите позже "
                                           "или обратитесь к "
                                           "преподавателю." % limit)

        idx = _load_index()
        if not idx:
            return fin("", [], False, "Индекс документации пуст — "
                                      "попросите преподавателя загрузить "
                                      "документы (панель «🤖 Подсказки»).")

        # кэш частых вопросов
        key = hashlib.sha1(
            (_norm(q) + "|" + _norm(page)).encode("utf-8")).hexdigest()
        with _lock:
            cache = _cache()
            hit = cache.get(key)
            if (isinstance(hit, dict)  # битая запись — просто мимо кэша
                    and time.time() - hit.get("т", 0) < 86400 * 3):
                return fin(hit["ответ"], hit.get("источники", []), True,
                           фрагменты=hit.get("фрагменты") or [])

        # вектор вопроса + поиск
        try:
            with _gen_sem:
                qvec = _embed(st, [q])[0]
        except Exception as ex:
            return fin("", [], False, "Поиск по документам недоступен — "
                                      "нужна локальная Ollama (эмбеддинги "
                                      "всегда локальные, даже в режиме "
                                      "API): %s" % ex)
        res = _search(idx, qvec, st.get("топ_k", 4),
                      float(st.get("мин_оценка", 0.22)))
        if not res:
            return fin(ОТКАЗ, [], False)

        frags = "\n\n".join(
            "[Фрагмент %d] источник: %s\n%s" % (i + 1, c["ф"], c["т"])
            for i, (c, _) in enumerate(res))
        user = ("ФРАГМЕНТЫ ДОКУМЕНТАЦИИ:\n\n" + frags
                + "\n\nВопрос студента: " + q)
        if page:
            user += "\nСтраница СДО: " + page
        msgs = [{"role": "system",
                 "content": st.get("системный_промт")
                 or УМОЛЧ["системный_промт"]},
                {"role": "user", "content": user}]
        режим = st.get("режим", "лок")
        prov, answer = "", None
        if режим in ("api", "авто") and st.get("api_url") \
                and st.get("api_key"):
            try:
                with _gen_sem:
                    answer = _chat_api(st, msgs).strip()
                prov = "API"
            except Exception as ex:
                if режим == "api":
                    return fin("", [], False,
                               "Внешний API не отвечает: %s" % ex)
                prov = ""  # авто: падаем на локальную модель
        if not prov:
            try:
                with _gen_sem:
                    answer = _chat(st, msgs).strip()
                prov = "локально"
            except Exception as ex:
                return fin("", [], False, "Модель не отвечает: %s" % ex)
        answer = (answer or "").strip() or ОТКАЗ
        sources = sorted({c["ф"] for c, _ in res})
        # самый релевантный фрагмент на каждый файл — для ссылки с подсветкой
        frags, seen = [], set()
        for c, _s in res:
            if c["ф"] in seen:
                continue
            seen.add(c["ф"])
            frags.append({"ф": c["ф"],
                          "х": hashlib.sha1(
                              c["т"].encode("utf-8")).hexdigest()[:8],
                          "стр": c.get("стр")})
        with _lock:
            cache = _cache()
            cache[key] = {"ответ": answer, "источники": sources,
                          "фрагменты": frags, "т": time.time()}
            if len(cache) > 400:  # самые свежие
                keep = sorted(cache.items(),
                              key=lambda kv: -kv[1].get("т", 0))[:400]
                cache = dict(keep)
            _save_cache(cache)
        return fin(answer, sources, False, prov=prov, фрагменты=frags)

    # ── панель преподавателя ─────────────────────────────────────────
    @ctx.add_route("GET", "/podskazki", access="staff")
    def panel(handler, params):
        st = _st()
        tags = _ollama_tags(st)
        names = [m.get("name", "") for m in (tags or {}).get("models", [])]
        model_ok = any(n == st["модель"] or n.startswith(st["модель"])
                       for n in names)
        emb_ok = any(n.startswith(st["эмбеддер"]) for n in names)
        idx = _load_index()
        rep = ctx.kv_load("пересборка.json", {})
        if not isinstance(rep, dict):  # битый отчёт — не ронять панель
            rep = {}
        qs = list(reversed(_questions()[-100:]))
        src_dir = os.path.join(ctx.data_dir, "источники")
        files = []
        if os.path.isdir(src_dir):
            for f in sorted(os.listdir(src_dir)):
                p = os.path.join(src_dir, f)
                if os.path.isfile(p):
                    files.append((f, os.path.getsize(p) // 1024,
                                  datetime.fromtimestamp(
                                      os.path.getmtime(p))
                                  .strftime("%d.%m.%Y")))

        if tags is None:
            oll = ('<span style="background:#b3261e;color:#fff;'
                   'border-radius:6px;padding:2px 8px">❌ не отвечает</span>')
            oll_hint = ('<p class="hint">Запустите: '
                        '<code>E:\\AI\\ollama\\ollama-cpu.bat</code> '
                        '(автостарт прописан). Адрес: <code>%s</code></p>'
                        % _e(st["url"]))
        else:
            oll = ('<span style="background:#1a7a2a;color:#fff;'
                   'border-radius:6px;padding:2px 8px">✅ отвечает</span>')
            oll_hint = ""
        if not st.get("api_url"):
            api_line = 'внешний API: <span class="hint">не настроен</span>'
        else:
            try:
                _rq = urllib.request.Request(
                    st["api_url"].rstrip("/") + "/models",
                    headers={"Authorization": "Bearer "
                             + st.get("api_key", "")})
                with urllib.request.urlopen(_rq, timeout=8) as _r:
                    _d = json.loads(_r.read().decode("utf-8"))
                api_line = ('внешний API: <span style="background:#1a7a2a;'
                            'color:#fff;border-radius:6px;padding:2px 8px">'
                            '✅ доступен (%d моделей)</span>'
                            % len(_d.get("data") or []))
            except Exception as _ex:
                api_line = ('внешний API: <span style="background:#b3261e;'
                            'color:#fff;border-radius:6px;padding:2px 8px">'
                            '❌ %s</span>' % _e(_ex))
        режим = st.get("режим", "лок")
        api_line += ' · режим: <b>%s</b>' % _e(режим)
        if режим in ("api", "авто") and not (st.get("api_url")
                                             and st.get("api_key")):
            api_line += (' <span class="hint">⚠️ выбран режим API, '
                         'но url/ключ не заданы — работает локально'
                         '</span>')
        status = (
            '<h2>🤖 Подсказки — панель</h2>'
            '<p>Ollama: %s · модель <b>%s</b> %s · эмбеддер <b>%s</b> %s'
            ' · индекс: <b>%s</b> чанков</p>'
            '<p>%s</p>%s'
        ) % (oll, _e(st["модель"]),
             "✅" if model_ok else "❌ (нет в списке моделей)",
             _e(st["эмбеддер"]),
             "✅" if emb_ok else "❌ (нет в списке моделей)",
             len(idx["чанки"]) if idx else 0,
             api_line, oll_hint)
        if rep.get("ошибка"):
            status += '<p style="color:#b3261e">Пересборка: %s</p>' \
                      % _e(rep["ошибка"])
        if isinstance(rep.get("обновлено"), list):
            upd = rep["обновлено"]
            status += ('<p class="hint">⚡ Догрузка (%s): обновлено %d — %s; '
                       'без изменений %d; всего чанков %d</p>'
                       % (_e(rep.get("время", "")), len(upd),
                          _e(", ".join(upd[:8])) + ("…" if len(upd) > 8
                                                    else "") or "нет",
                          rep.get("без_изменений", 0),
                          rep.get("чанков", 0)))
        for w in (rep.get("предупреждения") or [])[:10]:
            status += '<p class="hint">⚠️ %s</p>' % _e(w)
        prog_html = (
            '<style>html.dark #wc-pb>div{background:#334155}</style>'
            '<div id="wc-pb" style="display:none;margin:10px 0">'
            '<div style="background:#e3e7ea;border-radius:8px;height:16px;'
            'overflow:hidden"><div id="wc-pb-fill" style="width:0%%;'
            'height:16px;background:#1f6e8a;border-radius:8px;'
            'transition:width .4s"></div></div>'
            '<div id="wc-pb-text" class="hint" style="margin-top:4px">'
            '</div></div>')

        # настройки
        _реж = st.get("режим", "лок")
        _k = st.get("api_key", "")
        _mask = ((_k[:3] + "…" + _k[-3:]) if len(_k) > 6
                 else ("•" * len(_k) if _k else ""))
        st_form = (
            '<h3>⚙️ Настройки</h3>'
            '<form method="post" action="/podskazki/настройки">'
            '<table class="staff-table">'
            '<tr><td>Ollama (url)</td><td><input name="url" value="%s" '
            'style="width:100%%"></td></tr>'
            '<tr><td>Модель</td><td><input name="модель" value="%s">'
            '<span class="hint"> qwen3:1.7b — по умолчанию; '
            'qwen3:30b-a3b-instruct-2507-q4_K_M — глубокий режим</span>'
            '</td></tr>'
            '<tr><td>Эмбеддер</td><td><input name="эмбеддер" value="%s">'
            '</td></tr>'
            '<tr><td>Режим генерации</td><td><select name="режим">'
            '<option value="лок"%s>Локально (Ollama)</option>'
            '<option value="api"%s>Внешний API</option>'
            '<option value="авто"%s>Авто: API, при сбое — локально'
            '</option></select> <span class="hint">эмбеддинги всегда '
            'локальные — документы наружу не уходят</span></td></tr>'
            '<tr><td>API url</td><td><input name="api_url" value="%s" '
            'style="width:100%%" placeholder="https://api.пример.ru/v1">'
            '</td></tr>'
            '<tr><td>API ключ</td><td><input type="password" '
            'name="api_key" value="" placeholder="%s" '
            'autocomplete="new-password"> <span class="hint">пусто — '
            'оставить прежний</span></td></tr>'
            '<tr><td>API модель</td><td><input name="api_model" '
            'value="%s"> <span class="hint">OpenAI-совместимый '
            'эндпоинт: /chat/completions</span></td></tr>'
            '<tr><td>Лимит вопросов в час</td><td><input name="лимит_час" '
            'value="%s" size="4"> <span class="hint">0 — без лимита'
            '</span></td></tr>'
            '<tr><td>Максимум токенов ответа</td><td>'
            '<input name="num_predict" value="%s" size="6"></td></tr>'
            '<tr><td>Фрагментов в промпт (топ-k)</td><td>'
            '<input name="топ_k" value="%s" size="4"></td></tr>'
            '<tr><td>Порог релевантности</td><td>'
            '<input name="мин_оценка" value="%s" size="6"></td></tr>'
            '<tr><td>Системный промт</td><td><textarea name="промт" '
            'rows="5" style="width:100%%">%s</textarea></td></tr>'
            '<tr><td>Включено</td><td><input type="checkbox" '
            'name="включено" value="1"%s></td></tr>'
            '</table><p><button class="btn-sm">💾 Сохранить настройки'
            '</button></p></form>'
        ) % (_e(st["url"]), _e(st["модель"]), _e(st["эмбеддер"]),
             ' selected' if _реж == "лок" else '',
             ' selected' if _реж == "api" else '',
             ' selected' if _реж == "авто" else '',
             _e(st.get("api_url", "")),
             _e(_mask),
             _e(st.get("api_model", "")),
             _e(st.get("лимит_час", 10)), _e(st.get("num_predict", 220)),
             _e(st.get("топ_k", 4)), _e(st.get("мин_оценка", 0.22)),
             _e(st.get("системный_промт") or УМОЛЧ["системный_промт"]),
             " checked" if st.get("включено", True) else "")

        # источники
        rep_up = ctx.kv_load("загрузка.json", {})
        if not isinstance(rep_up, dict):
            rep_up = {}
        up_note = ""
        if rep_up.get("время"):
            up_note = ('<p class="hint">📦 Последняя загрузка (%s): '
                       '<b>сохранено %d</b>%s%s</p>')
            sv = rep_up.get("сохранено") or []
            sk = rep_up.get("пропущено") or []
            up_note %= (
                _e(rep_up["время"]), len(sv),
                (": " + _e(", ".join(sv[:12]))
                 + (" …" if len(sv) > 12 else "")) if sv else "",
                (";<br>⏭ пропущено: " + _e("; ".join(
                    "%s — %s" % (n, r) for n, r in sk[:10]))
                 + (" …" if len(sk) > 10 else "")) if sk else "")

        # источники
        rows = "".join(
            '<tr><td>📄 %s</td><td class="hint">%d КБ · %s</td>'
            '<td><form method="post" action="/podskazki/удалить" '
            'style="display:inline" onsubmit="return confirm('
            "'Удалить %s?')\">"
            '<input type="hidden" name="имя" value="%s">'
            '<button class="btn-sm btn-secondary">🗑</button></form></td>'
            '</tr>' % (_e(f), sz, d, _e(f), _e(f))
            for f, sz, d in files) or (
            '<tr><td colspan="3" class="hint">Файлов пока нет.</td></tr>')
        src_html = (
            '<h3>📚 Источники (папка: данные/модули/podskazki/источники)'
            '</h3>'
            + up_note
            + '<p class="hint">Загружайте паспорта стендов, руководства, '
            'методички: .txt, .md, .docx, .pdf (для .pdf нужен пакет '
            'pypdf). Эти документы студентам не показываются — только '
            'через ответы подсказок. <b>Массовая загрузка:</b> выделите '
            'сразу несколько файлов и/или загрузите <b>ZIP-архив</b> — '
            'он распакуется автоматически (до 300 файлов, русские имена '
            'поддерживаются).</p>'
            '<table class="staff-table"><tr><th>Файл</th><th>Размер</th>'
            '<th></th></tr>%s</table>'
            '<form method="post" action="/podskazki/загрузка" '
            'enctype="multipart/form-data" style="margin-top:8px">'
            '<input type="file" name="файлы" multiple> '
            '<button class="btn-sm">⬆️ Загрузить</button> '
            '<button class="btn-sm" formaction="/podskazki/пересобрать">'
            '🔄 Пересобрать индекс</button> '
            '<button class="btn-sm" formaction="/podskazki/догрузить" '
            'title="Эмбеддятся только новые или изменённые файлы — '
            'быстро, даже во время занятия">'
            '⚡ Только новое</button> '
            '<span class="hint">пересборка: до минуты; «Только новое» — '
            'секунды</span></form>'
        ) % rows

        # история вопросов
        def _src_links(r):
            out = []
            for s in (r.get("источники") or []):
                out.append('<a href="/podskazki/просмотр/%s" '
                           'target="_blank">%s</a>'
                           % (urllib.parse.quote(s), _e(s)))
            return " ".join(out) or "—"

        q_rows = "".join(
            '<tr><td class="hint">%s</td><td>%s <span class="hint">'
            '[%s]</span></td><td style="max-width:380px">%s</td>'
            '<td style="max-width:320px"><details><summary>%s</summary>'
            '<p>%s</p><p class="hint">Источники: %s</p></details></td>'
            '<td class="hint">%s с %s%s</td></tr>'
            % (_e(r.get("время", "")), _e(r.get("фио", "")),
               _e(r.get("группа", "")), _e(r.get("вопрос", "")),
               (r.get("ошибка") and "❌ ошибка") or "объяснение",
               _e(r.get("ответ", "")).replace("\n", "<br>"),
               _src_links(r),
               _e(r.get("сек", "")),
               "💾 кэш" if r.get("кэш") else "",
               (" · " + _e(r.get("провайдер", "")))
               if r.get("провайдер") else "")
            for r in qs) or (
            '<tr><td colspan="5" class="hint">Вопросов ещё не было.'
            '</td></tr>')
        hist = (
            '<h3>🕘 История вопросов (последние %d из %d)</h3>'
            '<table class="staff-table"><tr><th>Время</th><th>Студент'
            '</th><th>Вопрос</th><th>Ответ</th><th>Стат</th></tr>%s'
            '</table>'
            '<form method="post" action="/podskazki/очистить" '
            'onsubmit="return confirm(\'Очистить всю историю?\')">'
            '<button class="btn-sm btn-secondary">🗑 Очистить историю'
            '</button></form>'
        ) % (len(qs), len(_questions()), q_rows)

        body = ('<div class="task-desc">%s%s%s%s</div>'
                % (status, prog_html, st_form, src_html + hist))
        body += _PROGRESS_JS
        return ctx.render_page("🤖 Подсказки", body, staff=True)

    @ctx.add_route("POST", "/podskazki/настройки", access="staff")
    def save_settings(handler, params):
        data = handler._parse_post()
        st = _st()
        st["url"] = str(data.get("url") or УМОЛЧ["url"]).strip()
        st["модель"] = str(data.get("модель") or УМОЛЧ["модель"]).strip()
        st["эмбеддер"] = str(data.get("эмбеддер")
                             or УМОЛЧ["эмбеддер"]).strip()
        for key in ("лимит_час", "num_predict", "топ_k"):
            try:
                st[key] = max(0, int(data.get(key, УМОЛЧ[key])))
            except (TypeError, ValueError):
                st[key] = УМОЛЧ[key]
        try:
            st["мин_оценка"] = max(0.0, min(0.95,
                                float(str(data.get("мин_оценка", ""))
                                      .replace(",", "."))))
        except (TypeError, ValueError):
            st["мин_оценка"] = УМОЛЧ["мин_оценка"]
        st["системный_промт"] = str(data.get("промт")
                                    or УМОЛЧ["системный_промт"]).strip()
        st["включено"] = bool(data.get("включено"))
        # внешний API: поля, которых нет в форме, не трогаем;
        # пустой ключ в форме означает «оставить прежний»
        if data.get("режим") in ("лок", "api", "авто"):
            st["режим"] = data["режим"]
        if data.get("api_url") is not None:
            st["api_url"] = str(data["api_url"]).strip()
        if data.get("api_model") is not None:
            st["api_model"] = str(data["api_model"]).strip()
        key = str(data.get("api_key") or "").strip()
        if key:
            st["api_key"] = key
        _kv_save("настройки.json", st)
        try:
            ctx.audit("подсказки: настройки сохранены",
                      "%s, режим: %s" % (st["модель"],
                                         st.get("режим", "лок")),
                      handler=handler)
        except Exception:
            pass
        handler._redirect("/podskazki")
        return handler._SENT

    @ctx.add_route("POST", "/podskazki/загрузка", access="staff")
    def upload(handler, params):
        """Загрузка источников. Можно несколько файлов сразу и/или
        ZIP-архивы — они распаковываются в источники автоматически
        (массовая загрузка: один архив = целый комплект документации).
        Итог всегда пишется в загрузка.json и показывается на панели."""
        data = handler._parse_post()
        ups = data.get("файлы")
        if ups is None or not getattr(ups, "name", ""):
            ups = []
        elif not isinstance(ups, list):
            ups = [ups]
        src = os.path.join(ctx.data_dir, "источники")
        os.makedirs(src, exist_ok=True)
        saved, skipped = [], []
        total = [0]  # распаковано байт (лимит на архив)

        def _save(name, blob):
            name = os.path.basename(str(name or "").replace("\\", "/"))
            name = re.sub(r"[\\/:*?\"<>|]+", "_", name).strip()[:120]
            if not name or name in (".", ".."):
                return
            low = name.lower()
            if low in ("thumbs.db", "desktop.ini") or low.startswith(
                    (".", "__")):
                skipped.append([name, "служебный файл"])
                return
            ext = os.path.splitext(name)[1].lower()
            if ext not in GOOD_EXT:
                skipped.append([name, "формат не поддерживается"])
            elif not blob:
                skipped.append([name, "пустой файл"])
            elif len(blob) > MAX_SRC:
                skipped.append([name, "больше 20 МБ"])
            else:
                with open(os.path.join(src, name), "wb") as f:
                    f.write(blob)
                saved.append(name)
                total[0] += len(blob)

        def _unzip(name, blob):
            if len(blob) > MAX_ZIP:
                skipped.append([name, "архив больше %d МБ"
                                % (MAX_ZIP // (1024 * 1024))])
                return
            try:
                zf = zipfile.ZipFile(io.BytesIO(blob))
            except Exception as ex:
                skipped.append([name, "архив не прочитан: %s" % ex])
                return
            n = 0
            for info in zf.infolist():
                if info.is_dir():
                    continue
                n += 1
                if n > MAX_ZIP_FILES:
                    skipped.append([name, "в архиве больше %d файлов"
                                    % MAX_ZIP_FILES])
                    break
                if total[0] > MAX_ZIP_UNPACK:
                    skipped.append([name, "распаковано больше %d МБ"
                                    % (MAX_ZIP_UNPACK // (1024 * 1024))])
                    break
                # имя: zipfile читает cp437 без флага utf-8; русские имена
                # из Проводника Windows — cp866, старых архиваторов —
                # cp1251 (эвристика: псевдографика в cp866 => cp1251)
                zname = info.filename
                if not info.flag_bits & 0x800:
                    raw = zname.encode("cp437", "replace")
                    try:
                        zname = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        zname = raw.decode("cp866", "replace")
                        if any("\u2500" <= ch <= "\u25ff" for ch in zname):
                            zname = raw.decode("cp1251", "replace")
                _save(zname, zf.read(info))
            zf.close()

        for up in ups:
            name = getattr(up, "name", "") or ""
            blob = getattr(up, "data", b"") or b""
            if name.lower().endswith(".zip"):
                _unzip(name, blob)
            else:
                _save(name, blob)
        rep = {"время": datetime.now().isoformat(timespec="seconds"),
               "сохранено": saved[:100], "пропущено": skipped[:100]}
        _kv_save("загрузка.json", rep)
        try:
            ctx.audit("подсказки: загружено источников", str(len(saved)),
                      handler=handler)
        except Exception:
            pass
        handler._redirect("/podskazki")
        return handler._SENT

    @ctx.add_route("POST", "/podskazki/удалить", access="staff")
    def delete_src(handler, params):
        data = handler._parse_post()
        name = os.path.basename(str(data.get("имя") or ""))
        p = os.path.join(ctx.data_dir, "источники", name)
        root = os.path.join(ctx.data_dir, "источники")
        if name and os.path.commonpath([os.path.abspath(root),
                                        os.path.abspath(p)]) \
                == os.path.abspath(root) and os.path.isfile(p):
            os.remove(p)
            shutil.rmtree(os.path.join(ctx.data_dir, "источники_медиа",
                                       name),
                          ignore_errors=True)
            try:
                ctx.audit("подсказки: источник удалён", name,
                          handler=handler)
            except Exception:
                pass
        handler._redirect("/podskazki")
        return handler._SENT

    @ctx.add_route("POST", "/podskazki/пересобрать", access="staff")
    def rebuild(handler, params):
        started = _rebuild_async()
        try:
            ctx.audit("подсказки: индекс пересобран" if started
                      else "подсказки: пересборка уже идёт", "",
                      handler=handler)
        except Exception:
            pass
        handler._redirect("/podskazki?r=1" if started else "/podskazki")
        return handler._SENT

    @ctx.add_route("POST", "/podskazki/догрузить", access="staff")
    def rebuild_new(handler, params):
        """⚡ Только новое: эмбеддятся лишь новые/изменённые файлы,
        чанки неизменённых переиспользуются с готовыми векторами."""
        started = _rebuild_async(only_new=True)
        try:
            ctx.audit("подсказки: догрузка новых источников"
                      if started else "подсказки: пересборка уже идёт",
                      "", handler=handler)
        except Exception:
            pass
        handler._redirect("/podskazki?r=1" if started else "/podskazki")
        return handler._SENT

    @ctx.add_route("GET", "/podskazki/прогресс", access="staff")
    def rebuild_progress(handler, params):
        handler._send_json(200, dict(_prog))
        return handler._SENT

    @ctx.add_route("POST", "/podskazki/очистить", access="staff")
    def clear_hist(handler, params):
        _save_questions([])
        handler._redirect("/podskazki")
        return handler._SENT

    # ── просмотр документации с подсветкой использованного фрагмента ─
    @ctx.add_route("GET", "/podskazki/просмотр/", access="any")
    def view_source(handler, params):
        """Ссылки «📄 файл» в шторке ведут сюда: текст документа по чанкам,
        использованный фрагмент подсвечен и проскроллен в центр.
        /podskazki/просмотр/<файл>[/<хэш фрагмента>]"""
        parts = params.get("_parts", [])
        fname = os.path.basename(parts[0]) if parts else ""
        target = parts[1] if len(parts) > 1 else ""

        def _media_src(fn):
            p = os.path.join(ctx.data_dir, "источники_медиа", fname, fn)
            return ("/podskazki/медиа/%s/%s"
                    % (urllib.parse.quote(fname), urllib.parse.quote(fn))
                    ) if fn and os.path.isfile(p) else ""

        def _rich(txt):
            """Маркеры извлечения -> HTML: картинки из docx, разделители
            страниц pdf."""
            txt = _e(txt)
            txt = re.sub(r"\[Рисунок (\d+): ([^\]\n]+)\]",
                         lambda m: (
                             '<img class="wc-pic" loading="lazy" '
                             'alt="Рисунок %s" src="%s">'
                             % (m.group(1), _media_src(m.group(2).strip()))
                         ) if _media_src(m.group(2).strip())
                         else '<span class="wc-nopic">🖼 Рисунок %s: %s'
                              '</span>' % (m.group(1),
                                           m.group(2).strip()),
                         txt)
            txt = re.sub(r"\[Страница (\d+)\] ?\[Рисунков: \d+\]?",
                         r'<span class="wc-page">— стр. \1 —</span>', txt)
            txt = re.sub(r"\[Страница (\d+)\]",
                         r'<span class="wc-page">— стр. \1 —</span>', txt)
            txt = re.sub(r"\[Рисунков: (\d+)\]",
                         r'<span class="wc-page">🖼 рисунков: \1</span>',
                         txt)
            return txt

        src = os.path.join(ctx.data_dir, "источники")
        path = os.path.join(src, fname)
        if not fname or fname in ("..", ".") or not os.path.isfile(path):
            handler._send_text(404, "Not Found")
            return handler._SENT
        if fname.lower().endswith(".pdf"):
            # настоящий PDF: вьювер на pdf.js — страница фрагмента
            # и подсветка использованного текста
            idx = _load_index() or {}
            hit = None
            for c in idx.get("чанки", []):
                if c.get("ф") == fname and hashlib.sha1(
                        c.get("т", "").encode("utf-8")
                ).hexdigest()[:8] == target:
                    hit = c
                    break
            cfg = {"файл": fname, "хэш": target,
                   "стр": (hit or {}).get("стр") or 1,
                   "запрос": re.sub(
                       r"\s+", " ",
                       re.sub(r"\[Рисунков: \d+\]", " ",
                              re.sub(r"\[Страница \d+\]"
                                     r"(?: \[Рисунков: \d+\])?", " ",
                                     (hit or {}).get("т", "")))).strip()[:300]}
            handler._send_html(ctx.render_page(
                "Документация: " + fname,
                _PDF_HTML.replace("__CFG__",
                                  json.dumps(cfg, ensure_ascii=False))))
            return handler._SENT
        idx = _load_index() or {}
        blocks = [c for c in idx.get("чанки", []) if c.get("ф") == fname]
        if blocks:
            hit_i = -1
            if target:
                for i, c in enumerate(blocks):
                    if hashlib.sha1(c.get("т", "").encode("utf-8")
                                    ).hexdigest()[:8] == target:
                        hit_i = i
                        break
            rows = []
            for i, c in enumerate(blocks):
                cls = ' class="wc-hit" id="wc-hit"' if i == hit_i else ""
                rows.append('<div%s><div class="wc-doc-n">Фрагмент %d'
                            '</div>%s</div>' % (cls, i + 1,
                                                _rich(c.get("т", ""))))
            inner = "".join(rows)
            note = '<p class="hint">📄 <b>%s</b> — документация стенда. %s</p>'
            if hit_i >= 0:
                note %= (_e(fname), "Жёлтым выделен фрагмент, по которому "
                                    "отвечала нейросеть.")
            elif target:
                note %= (_e(fname), "Фрагмент не найден (возможно, индекс "
                                    "пересобран) — показан весь документ.")
            else:
                note %= (_e(fname), "Кликните по источнику в подсказке, "
                                    "чтобы увидеть использованный фрагмент.")
            page_body = note + '<div class="wc-doc">%s</div>' % inner
        else:
            text, warn = _extract(path)
            if not text:
                page_body = ('<p class="error">Не удалось извлечь текст '
                             'из файла: %s</p>' % _e(warn or "нет данных"))
            else:
                text = re.sub(r"\r\n?", "\n", text)
                page_body = ('<p class="hint">📄 <b>%s</b> — документация '
                             'стенда (индекс ещё не собран, показан весь '
                             'текст).</p>' % _e(fname)
                             + '<div class="wc-doc">%s</div>' % _rich(text))
        if hit_i >= 0:
            page_body += ('<script>var m=document.getElementById("wc-hit");'
                          'if(m)m.scrollIntoView({block:"center"});</script>')
        handler._send_html(ctx.render_page(
            "Документация: " + fname, page_body, extra_head=_VIEW_CSS))
        return handler._SENT

    # ── картинки из docx-источников ──────────────────────────────────
    @ctx.add_route("GET", "/podskazki/медиа/", access="any")
    def media_file(handler, params):
        parts = params.get("_parts", [])
        doc = os.path.basename(parts[0]) if parts else ""
        fn = os.path.basename(parts[1]) if len(parts) > 1 else ""
        root = os.path.abspath(os.path.join(ctx.data_dir,
                                            "источники_медиа"))
        p = os.path.abspath(os.path.join(root, doc, fn))
        mime = {".png": "image/png", ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg", ".gif": "image/gif",
                ".bmp": "image/bmp", ".webp": "image/webp",
                ".tif": "image/tiff", ".tiff": "image/tiff"}.get(
            os.path.splitext(fn)[1].lower())
        if (not doc or not fn or mime is None
                or not os.path.isfile(p)
                or os.path.commonpath([p, root]) != root):
            handler._send_text(404, "Not Found")
            return handler._SENT
        with open(p, "rb") as f:
            handler._send_response(200, mime, f.read(), encode=False)
        return handler._SENT

    # ── оригинал файла источника (для pdf-просмотрщика) ──────────────
    @ctx.add_route("GET", "/podskazki/файл/", access="any")
    def source_file(handler, params):
        parts = params.get("_parts", [])
        fname = os.path.basename(parts[0]) if parts else ""
        root = os.path.abspath(os.path.join(ctx.data_dir, "источники"))
        p = os.path.abspath(os.path.join(root, fname))
        mime = {".pdf": "application/pdf",
                ".txt": "text/plain; charset=utf-8",
                ".md": "text/plain; charset=utf-8",
                ".markdown": "text/plain; charset=utf-8",
                ".log": "text/plain; charset=utf-8",
                ".docx": "application/vnd.openxmlformats-officedocument"
                         ".wordprocessingml.document"}.get(
            os.path.splitext(fname)[1].lower())
        if (not fname or fname in ("..", ".") or mime is None
                or not os.path.isfile(p)
                or os.path.commonpath([p, root]) != root):
            handler._send_text(404, "Not Found")
            return handler._SENT
        with open(p, "rb") as f:
            handler._send_response(200, mime, f.read(), encode=False)
        return handler._SENT

    # ── фрагмент на страницах ────────────────────────────────────────
    def page_head(**kw):
        with _lock:
            qs = _questions()
        today = datetime.now().strftime("%Y-%m-%d")
        n = sum(1 for r in qs
                if str(r.get("время", "")).startswith(today))
        return _FRAG % {"today": n}

    ctx.on("page.head", page_head)


# ── вёрстка виджета ──────────────────────────────────────────────────
_FRAG = (
    '<style>'
    '.wc-ai-btn{position:fixed;right:18px;bottom:70px;z-index:9997;'
    'border:none;border-radius:999px;padding:10px 16px;font-size:14px;'
    'background:#1f6e8a;color:#fff;cursor:pointer;'
    'box-shadow:0 4px 12px rgba(0,0,0,.25)}'
    '.wc-ai-btn:hover{filter:brightness(1.15)}'
    '.wc-ai-pl{position:fixed;right:18px;bottom:18px;z-index:9997;'
    'display:inline-block;background:#1f6e8a;color:#fff;'
    'border-radius:999px;padding:10px 16px;font-size:14px;'
    'text-decoration:none;box-shadow:0 4px 12px rgba(0,0,0,.25)}'
    'body.staff .wc-ai-btn,body.staff .wc-ai-drawer{display:none!important}'
    'body:not(.staff) .wc-ai-pl{display:none!important}'
    '.wc-ai-drawer{position:fixed;top:0;right:-440px;width:400px;'
    'max-width:96vw;height:100vh;z-index:9997;background:#fff;'
    'color:#111;box-shadow:-6px 0 24px rgba(0,0,0,.22);'
    'transition:right .25s;display:flex;flex-direction:column;'
    'font-family:inherit}'
    '.wc-ai-drawer.open{right:0}'
    '.wc-ai-head{padding:12px 14px;border-bottom:1px solid #e0e0e0;'
    'display:flex;justify-content:space-between;align-items:center}'
    '.wc-ai-head b{font-size:15px}'
    '.wc-ai-x{border:none;background:none;font-size:20px;cursor:pointer;'
    'color:#666}'
    '.wc-ai-msgs{flex:1;overflow-y:auto;padding:12px;background:#fafafa}'
    '.wc-ai-msg{margin:8px 0;padding:10px 12px;border-radius:10px;'
    'max-width:94%%;white-space:pre-wrap;word-wrap:break-word;'
    'font-size:14px;line-height:1.45}'
    '.wc-ai-msg.u{background:#dcecf7;margin-left:auto;width:fit-content}'
    '.wc-ai-msg.a{background:#eef1f4}'
    '.wc-ai-msg.err{background:#fdecea;color:#8a1f1f}'
    '.wc-ai-src{display:inline-block;background:#e3f2fd;color:#145a7a;'
    'border-radius:6px;padding:2px 8px;margin:6px 4px 0 0;font-size:11px;'
    'text-decoration:none}'
    '.wc-ai-src:hover{background:#cfe6f7;text-decoration:underline}'
    '.wc-ai-meta{font-size:11px;color:#888;margin-top:4px}'
    '.wc-ai-foot{padding:10px;border-top:1px solid #e0e0e0;display:flex;'
    'gap:8px;background:#fff}'
    '.wc-ai-foot textarea{flex:1;resize:none;height:46px;padding:8px 10px;'
    'border:1px solid #ccc;border-radius:8px;font:inherit;font-size:14px}'
    '.wc-ai-foot button{border:none;border-radius:8px;padding:0 16px;'
    'background:#1f6e8a;color:#fff;cursor:pointer;font-size:14px}'
    '.wc-ai-foot button:disabled{opacity:.5;cursor:default}'
    '.wc-ai-note{font-size:11px;color:#888;padding:2px 10px 8px;'
    'background:#fff}'
    '/* ── тёмная тема (html.dark, тумблер в шапке) ── */'
    'html.dark .wc-ai-drawer{background:#1e293b;color:#e2e8f0}'
    'html.dark .wc-ai-head{border-bottom-color:#334155}'
    'html.dark .wc-ai-x{color:#94a3b8}'
    'html.dark .wc-ai-msgs{background:#0f172a}'
    'html.dark .wc-ai-msg.u{background:#312e81;color:#e2e8f0}'
    'html.dark .wc-ai-msg.a{background:#1e293b;color:#e2e8f0}'
    'html.dark .wc-ai-msg.err{background:rgba(239,68,68,.15);'
    'color:#fca5a5}'
    'html.dark .wc-ai-src{background:rgba(102,126,234,.18);'
    'color:#a5b4fc}'
    'html.dark .wc-ai-src:hover{background:rgba(102,126,234,.35)}'
    'html.dark .wc-ai-foot{border-top-color:#334155;background:#1e293b}'
    'html.dark .wc-ai-foot textarea{background:#0f172a;color:#e2e8f0;'
    'border-color:#334155}'
    'html.dark .wc-ai-note{background:#1e293b;color:#94a3b8}'
    '</style>'
    '<button class="wc-ai-btn" id="wc-ai-btn" title="Подсказка по '
    'документации">🤖 Подсказка</button>'
    '<a class="wc-ai-pl" href="/podskazki" title="Панель подсказок">'
    '🤖 Подсказки · %(today)d сегодня</a>'
    '<div class="wc-ai-drawer" id="wc-ai-drawer">'
    '<div class="wc-ai-head"><b>🤖 Подсказка по документации</b>'
    '<button class="wc-ai-x" id="wc-ai-x">×</button></div>'
    '<div class="wc-ai-msgs" id="wc-ai-msgs">'
    '<div class="wc-ai-msg a">Привет! Я ищу ответ в документации стенда. '
    'Спросите, например: «как проверить шлейф сигнализации?».</div>'
    '</div>'
    '<div class="wc-ai-foot">'
    '<textarea id="wc-ai-in" placeholder="Ваш вопрос…"></textarea>'
    '<button id="wc-ai-send">Спросить</button></div>'
    '<div class="wc-ai-note">Ответы — только по загруженной '
    'документации, с указанием источника. Нейросеть может ошибаться — '
    'проверяйте по паспорту стенда.</div>'
    '</div>'
    '<script>(function(){'
    'var d=document.getElementById("wc-ai-drawer");if(!d)return;'
    'var m=document.getElementById("wc-ai-msgs"),'
    'ta=document.getElementById("wc-ai-in"),'
    'sb=document.getElementById("wc-ai-send");'
    'document.getElementById("wc-ai-btn").addEventListener("click",'
    'function(){d.classList.add("open");ta.focus()});'
    'document.getElementById("wc-ai-x").addEventListener("click",'
    'function(){d.classList.remove("open")});'
    'function esc(s){var x=document.createElement("div");'
    'x.textContent=String(s==null?"":s);return x.innerHTML}'
    'function add(cls,text,srcs,meta,frags){var e=document.createElement("div");'
    'e.className="wc-ai-msg "+cls;e.innerHTML=esc(text);'
    'if(srcs&&srcs.length){var s=document.createElement("div");'
    'for(var i=0;i<srcs.length;i++){var fx="";'
    'if(frags){for(var k=0;k<frags.length;k++){'
    'if(frags[k].ф==srcs[i]&&frags[k].х){fx="/"+frags[k].х;break}}}'
    'var p=document.createElement("a");'
    'p.className="wc-ai-src";p.target="_blank";p.rel="noopener";'
    'p.href="/podskazki/просмотр/"+encodeURIComponent(srcs[i])+fx;'
    'p.textContent="📄 "+srcs[i];'
    'p.title="Открыть документацию";s.appendChild(p)}e.appendChild(s)}'
    'if(meta){var mm=document.createElement("div");mm.className='
    '"wc-ai-meta";mm.textContent=meta;e.appendChild(mm)}'
    'm.appendChild(e);m.scrollTop=m.scrollHeight;return e}'
    'var busy=null;'
    'function setbusy(on){sb.disabled=on;'
    'if(on){busy=add("a","🔎 Ищу в документации…")}else if(busy){'
    'busy.remove();busy=null}}'
    'function ask(){var q=ta.value.trim();if(!q||sb.disabled)return;'
    'add("u",q);ta.value="";setbusy(true);'
    'fetch("/podskazka",{method:"POST",'
    'headers:{"Content-Type":"application/json"},'
    'body:JSON.stringify({вопрос:q,страница:document.title||""})})'
    '.then(function(r){return r.json().catch(function(){'
    # не-JSON ответ (500/404) раньше падал в catch как «нет связи»
    'return {ок:false,ошибка:"Сервер СДО вернул ошибку (HTTP "+r.status+'
    '"). Попробуйте ещё раз через минуту."}})})'
    '.then(function(j){setbusy(false);'
    'if(j.ок){add("a",j.ответ,j.источники,'
    '(j.провайдер?(j.провайдер=="API"?"⚡ API":"💻 локально"):"")'
    '+(j.кэш?" · 💎 из кэша":"")+(j.сек?" · "+j.сек+" с":""),'
    'j.фрагменты)}'
    'else{add("err",j.ошибка||"Ошибка подсказок",null,'
    'j.подсказка||"")}})'
    '.catch(function(){setbusy(false);'
    'add("err","Нет связи с сервером СДО. Если сервер только что '
    'запускали — подождите минуту и повторите вопрос.")});}'
    'sb.addEventListener("click",ask);'
    'ta.addEventListener("keydown",function(e){'
    'if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();ask()}});'
    '})();</script>'
)

# Опрос прогресса пересборки на панели (только /podskazki).
_PROGRESS_JS = (
    '<script>(function(){'
    'var pb=document.getElementById("wc-pb");if(!pb)return;'
    'var txt=document.getElementById("wc-pb-text"),'
    'fill=document.getElementById("wc-pb-fill");'
    'function tick(){fetch("/podskazki/прогресс")'
    '.then(function(r){return r.json()}).then(function(j){'
    'if(j.фаза=="чтение"||j.фаза=="эмбеддинги"){'
    'pb.style.display="";'
    'var p=j.всего?Math.round(100*j.сделано/j.всего):0;'
    'fill.style.width=p+"%";'
    'txt.textContent=(j.фаза=="чтение"?"Читаю файлы…":"Эмбеддинги: "'
    '+j.сделано+" из "+j.всего)+" — "+p+"%";'
    'setTimeout(tick,1000)}'
    'else if(j.фаза=="готово"||j.фаза=="ошибка"){'
    'if(location.search.indexOf("r=1")>=0){'
    'location.replace("/podskazki");return}'
    'if(j.фаза=="ошибка"){pb.style.display="";'
    'txt.textContent="Ошибка пересборки: "+(j.ошибка||"")}'
    'else{pb.style.display="none"}}'
    'else{pb.style.display="none"}})'
    '.catch(function(){pb.style.display="none"})}'
    'tick();})();</script>'
)
