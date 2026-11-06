# -*- coding: utf-8 -*-
"""Модуль «Офлайн-сдача»: бланк задания → работа дома → загрузка в систему.

Как работает:
- Преподаватель открывает панель «📥 Офлайн-сдача» (кнопка в шапке сайта),
  выбирает студентов и задания, которые они должны сдать, — и скачивает
  архивы: на каждого студента один архив «ФИО.zip» с бланками выбранных
  заданий.
- Бланк — автономный HTML: описание и форма задания, ФИО/группа уже
  вписаны и подписаны HMAC-подписью (как кука студента) + индивидуальный
  токен выдачи (защита от списывания; старый токен стирается при
  перевыпуске).
- Студент заполняет бланк в браузере, прикладывает файлы, жмёт
  «💾 Сохранить работу» — получает файл работы (.json).
- В СДО: страница «📥 Офлайн-сдача» — студент загружает файл(ы), система
  распознаёт его по подписи и токену и создаёт обычную сдачу (новую
  версию). Преподаватель может импортировать пачку работ сам; спорные
  работы — выбором студента из списка.

Маршруты:
    GET  /offline/blank/<tid>          — предпросмотр анонимного бланка
                                       (только преподаватель)
    GET  /offline/                     — загрузка работы (студент)
    POST /offline/upload               — загрузка работы (студент)
    GET  /staff/offline                — панель: выдача бланков + импорт
    POST /staff/offline/issue          — выдача бланков (архивы «ФИО.zip»)
    POST /staff/offline/import         — импорт пачки
    POST /staff/offline/manual         — зачесть нераспознанные / отменить

Файл работы:
    {"формат": "works-core-работа", "версия": 1, "задание": "t1", …,
     "студент": {"sid":…, "подпись":…, "fio":…, "группа":…, "бригада":…},
     "токен": <токен выдачи бланка>, "ответы": {…},
     "файлы": {ключ: [{"имя":…, "b64":…}]}}

Защита от списывания:
    При скачивании бланка со своей страницы студенту выдаётся
    индивидуальный токен (KV «выдачи»; при перевыпуске старый стирается).
    Работа студента без своего актуального токена блокируется; при импорте
    преподавателем несовпадение токена — предупреждение (можно зачесть
    вручную). Работы студентов без подписи студентом не принимаются.
    Детект сходства: при каждой сдаче текстовые ответы сравниваются
    с работами других студентов по заданию (шинглы слов, порог 60%),
    идентичные файлы тоже отмечаются; пары попадают в KV «флаги» и
    показываются в панели /staff/offline (разделы «⚠️ Возможное
    списывание» и «🔐 Токены выдачи бланков»).
"""
import base64
import hashlib
import html as _html
import io
import json
import os
import re
import secrets
import time
import urllib.parse
import zipfile
from datetime import datetime

FMT = "works-core-работа"
VER = 1
MAX_ATTACH = 8 * 1024 * 1024     # вложения одной работы (в данных)
MAX_BATCH = 20 * 1024 * 1024     # пачка отложенного импорта
PENDING_TTL = 24 * 3600
SIM_MIN = 0.60                   # порог Жаккара: тексты похожи
SIM_K = 3                        # размер шингла (слов)
SIM_MIN_WORDS = 12               # короче — не сравниваем


# ── Вспомогательные ──────────────────────────────────────────────────────

def _e(v):
    return _html.escape(str(v) if v is not None else "", quote=True)


def _norm_fio(s):
    return re.sub(r"\s+", " ", str(s or "").strip()).lower()


def _safefn(s):
    base = re.sub(r'[\\/:*?"<>|]+', "_", str(s or "")).strip()
    base = re.sub(r"\s+", "_", base)[:60]
    return base or "file"


def _parse_dl(value):
    v = str(value or "").strip().replace("T", " ")
    if not v:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
                "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            continue
    return None


class _Up:
    """Загруженный файл (совместим с ядром: .name и .data)."""

    def __init__(self, name, data):
        self.name = name
        self.data = data


class _Manual(Exception):
    """Работа без подписи и неоднозначным ФИО — нужен выбор студента."""


def _md(text):
    """Мини-Markdown -> HTML (вход экранируется)."""
    if not text:
        return ""
    esc = _html.escape(str(text), quote=False)

    def inline(s):
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", s)
        return s

    out = []
    lst = None

    def close():
        nonlocal lst
        if lst:
            out.append("</%s>" % lst)
            lst = None

    for raw in esc.split("\n"):
        s = raw.strip()
        if not s:
            close()
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            close()
            lvl = 2 if len(m.group(1)) < 3 else 3
            out.append("<h%d>%s</h%d>" % (lvl, inline(m.group(2)), lvl))
            continue
        m = re.match(r"^[-*]\s+(.*)$", s)
        if m:
            if lst != "ul":
                close()
                lst = "ul"
                out.append("<ul>")
            out.append("<li>%s</li>" % inline(m.group(1)))
            continue
        m = re.match(r"^\d+[.)]\s+(.*)$", s)
        if m:
            if lst != "ol":
                close()
                lst = "ol"
                out.append("<ol>")
            out.append("<li>%s</li>" % inline(m.group(1)))
            continue
        close()
        out.append("<p>%s</p>" % inline(s))
    close()
    return "\n".join(out)


def _as_uploads(v):
    """Список Upload из поля формы (одно имя — несколько файлов).

    Проверка по duck-typing (как в ядре): handler._parse_post() отдаёт
    экземпляры core.http.Upload — это чужой для модуля класс, isinstance
    по _Up отфильтровал бы все файлы.
    """
    if v is None:
        return []
    if isinstance(v, list):
        return [x for x in v if hasattr(x, "data") and hasattr(x, "name") and x.data]
    return [v] if (hasattr(v, "data") and hasattr(v, "name") and v.data) else []


# ── Бланк задания ────────────────────────────────────────────────────────

BLANK_CSS = """
*{box-sizing:border-box}
body{font:15px/1.55 'Segoe UI',Tahoma,sans-serif;color:#2c3e50;max-width:860px;margin:0 auto;padding:16px}
h1{font-size:21px;color:#1e3a5f;margin:6px 0 4px}
h2{font-size:17px;color:#1e3a5f;border-bottom:2px solid #e3e8ef;padding-bottom:4px;margin-top:22px}
.meta{background:#f4f7fb;border:1px solid #dbe4ef;border-radius:10px;padding:10px 14px;font-size:14px;margin:10px 0}
.meta b{color:#1e3a5f}
.muted{color:#8a97a8}
.warn{background:#fef9c3;border-left:4px solid #eab308;padding:8px 12px;border-radius:0 8px 8px 0;margin:10px 0}
.desc{border:1px solid #e3e8ef;border-radius:10px;padding:4px 16px 10px;background:#fff}
.desc h2{border:none}
.fld{margin:12px 0}
.fld>label,.fld-llabel{display:block;font-weight:600;margin-bottom:4px}
.req{color:#dc2626}
input[type=text],input[type=number],input[type=date],input[type=email],input[type=tel],
select,textarea{width:100%;padding:7px 9px;border:1px solid #cfd8e3;border-radius:8px;font:inherit}
textarea{resize:vertical}
.fld-sep{font-weight:700;color:#1e3a5f;background:#eef2f7;border-radius:8px;padding:7px 10px;margin:16px 0 6px}
.opt{display:block;margin:4px 0}
.opt input{width:auto;margin-right:6px}
table.sl{border-collapse:collapse;width:100%;font-size:13.5px}
table.sl th,table.sl td{border:1px solid #cfd8e3;padding:3px}
table.sl th{background:#eef2f7;font-weight:600}
table.sl input{width:100%;border:none;padding:5px 7px;font:inherit}
.filebox{border:2px dashed #b6c2d2;border-radius:10px;padding:12px}
.filebox input{width:100%}
.savebar{position:sticky;bottom:0;background:#fff;border-top:2px solid #e3e8ef;padding:12px 0;margin-top:18px}
button.big{background:#2563eb;color:#fff;border:none;border-radius:10px;padding:11px 22px;font-size:16px;font-weight:600;cursor:pointer}
button.big:hover{background:#1e56d0}
#svmsg{margin-left:12px;color:#0f766e;font-weight:600}
footer{margin-top:26px;color:#8a97a8;font-size:12.5px;border-top:1px solid #e3e8ef;padding-top:8px}
@media print{.savebar,.noprint{display:none}body{max-width:none}}
"""


def _field_html(fd):
    """HTML одного поля бланка (по типам ядра)."""
    typ = fd.get("тип", "text")
    key = fd.get("ключ", "")
    label = fd.get("вопрос") or fd.get("подсказка") or key
    req = "1" if fd.get("обязательно") else ""

    def lab():
        return ('<label class="fld-llabel">%s%s</label>'
                % (_e(label), ' <span class="req">*</span>' if req else ""))

    if typ == "static":
        return '<div class="fld-sep">%s</div>' % _e(fd.get("подсказка") or label)
    if typ == "hidden":
        return ""
    if typ == "textarea":
        rows = min(max(int(fd.get("строк", 4) or 4), 1), 20)
        ph = ' placeholder="%s"' % _e(fd.get("место")) if fd.get("место") else ""
        return ('<div class="fld">%s<textarea data-key="%s" data-type="textarea" '
                'data-req="%s" rows="%d"%s></textarea></div>'
                % (lab(), _e(key), req, rows, ph))
    if typ == "select":
        opts = ['<option value="">— выберите —</option>']
        for o in (fd.get("варианты") or []):
            opts.append('<option value="%s">%s</option>' % (_e(o), _e(o)))
        return ('<div class="fld">%s<select data-key="%s" data-type="select" '
                'data-req="%s">%s</select></div>'
                % (lab(), _e(key), req, "".join(opts)))
    if typ == "radio":
        ins = []
        for o in (fd.get("варианты") or []):
            ins.append('<label class="opt"><input type="radio" data-key="%s" '
                       'data-type="radio" data-req="%s" name="%s" value="%s">%s</label>'
                       % (_e(key), req, _e(key), _e(o), _e(o)))
        return '<div class="fld">%s%s</div>' % (lab(), "".join(ins))
    if typ == "checkboxes":
        ins = []
        for o in (fd.get("варианты") or []):
            ins.append('<label class="opt"><input type="checkbox" data-key="%s" '
                       'data-type="checkboxes" data-req="%s" name="%s" value="%s">%s</label>'
                       % (_e(key), req, _e(key), _e(o), _e(o)))
        return '<div class="fld">%s%s</div>' % (lab(), "".join(ins))
    if typ == "checkbox":
        return ('<div class="fld"><label class="opt"><input type="checkbox" '
                'data-key="%s" data-type="checkbox" data-req="%s" value="on">'
                '%s%s</label></div>'
                % (_e(key), req, _e(label), ' <span class="req">*</span>' if req else ""))
    if typ == "file":
        acc = ' accept="%s"' % _e(fd.get("accept")) if fd.get("accept") else ""
        return ('<div class="fld">%s<div class="filebox">'
                '<input type="file" data-key="%s" data-type="file" data-req="%s"%s>'
                '</div></div>' % (lab(), _e(key), req, acc))
    if typ == "firmware":
        lim = fd.get("лимит", 5)
        return ('<div class="fld">%s<div class="filebox">'
                '<input type="file" multiple data-key="%s" data-type="firmware" '
                'data-req="%s" data-limit="%s"></div>'
                '<p class="muted">До %s файлов</p></div>'
                % (lab(), _e(key), req, _e(lim), _e(lim)))
    if typ == "shlei":
        rows = min(max(int(fd.get("строк", 10) or 10), 1), 30)
        cols = [("n", "Номер шлейфа"), ("type", "Тип"),
                ("dev", "Установленный прибор"),
                ("cnt", "Кол-во приборов"), ("note", "Комментарий")]
        head = "".join("<th>%s</th>" % _e(c[1]) for c in cols)
        trs = []
        for i in range(rows):
            tds = "".join('<td><input data-col="%s"></td>' % c[0] for c in cols)
            trs.append('<tr data-row="%d">%s</tr>' % (i, tds))
        return ('<div class="fld">%s<table class="sl" id="sl_%s" data-rows="%d" '
                'data-key="%s" data-type="shlei" data-req="%s"><tr>%s</tr>%s</table>'
                '</div>' % (lab(), _e(key), rows, _e(key), req, head, "".join(trs)))
    # text / number / date / email / tel
    it = typ if typ in ("number", "date", "email", "tel") else "text"
    extra = ""
    if typ == "number":
        for p in ("мин", "макс", "шаг"):
            if fd.get(p) is not None:
                extra += ' %s="%s"' % ({"мин": "min", "макс": "max",
                                        "шаг": "step"}[p], _e(fd.get(p)))
    ph = ' placeholder="%s"' % _e(fd.get("место")) if fd.get("место") else ""
    return ('<div class="fld">%s<input type="%s" data-key="%s" data-type="text" '
            'data-req="%s" value=""%s%s></div>'
            % (lab(), it, _e(key), req, extra, ph))


BLANK_JS = """var M=__META__,LBL=__LABELS__;
function $$(s){return document.querySelector(s)}
function $$all(s){return document.querySelectorAll(s)}
function slCollect(k){
  var t=document.getElementById('sl_'+k);
  if(!t)return'[]';
  var rows=t.querySelectorAll('tr[data-row]'),out=[];
  for(var i=0;i<rows.length;i++){
    function g(c){var el=rows[i].querySelector('[data-col="'+c+'"]');
      return el?el.value.trim():''}
    var r={n:g('n'),type:g('type'),dev:g('dev'),cnt:g('cnt'),note:g('note')};
    if(r.n||r.type||r.dev||r.cnt||r.note)out.push(r);
  }
  return JSON.stringify(out);
}
function buildAnswers(){
  var ans={},els=$$all('[data-key]');
  for(var i=0;i<els.length;i++){
    var el=els[i],k=el.getAttribute('data-key'),
        t=el.getAttribute('data-type')||'text';
    if(t==='checkboxes'){if(el.checked){if(!ans[k])ans[k]=[];ans[k].push(el.value)}}
    else if(t==='checkbox'){ans[k]=el.checked?'да':''}
    else if(t==='radio'){if(el.checked)ans[k]=el.value}
    else if(t==='shlei'){ans[k]=slCollect(k)}
    else if(t==='file'||t==='firmware'){/* файлы отдельно */}
    else{ans[k]=el.value}
  }
  return ans;
}
function validate(){
  var errs=[];
  var seen={};
  var els=$$all('[data-key]');
  for(var i=0;i<els.length;i++){
    var el=els[i],k=el.getAttribute('data-key'),
        t=el.getAttribute('data-type')||'text';
    if(el.getAttribute('data-req')!=='1'||seen[k])continue;seen[k]=1;
    var bad=false;
    if(t==='checkboxes'||t==='radio'){
      bad=!$$('[data-key="'+k+'"][data-type="'+t+'"]:checked')}
    else if(t==='checkbox'){bad=!el.checked}
    else if(t==='shlei'){bad=slCollect(k)==='[]'}
    else if(t==='file'||t==='firmware'){bad=!(el.files&&el.files.length)}
    else{bad=!String(el.value).trim()}
    if(bad)errs.push(LBL[k]||k);
  }
  return errs;
}
function b64(f){return new Promise(function(res,rej){
  var r=new FileReader();
  r.onload=function(){var s=String(r.result||''),i=s.indexOf('base64,');
    res(i>=0?s.slice(i+7):'')};
  r.onerror=function(){rej(new Error('не удалось прочитать '+f.name))};
  r.readAsDataURL(f);
})}
function buildFiles(){
  var out={},ps=[];
  var els=$$all('[data-key][data-type="file"],[data-key][data-type="firmware"]');
  for(var i=0;i<els.length;i++){
    var el=els[i],k=el.getAttribute('data-key'),
        t=el.getAttribute('data-type');
    var lim=t==='firmware'?(parseInt(el.getAttribute('data-limit')||'5',10)||5):1;
    var fs=Array.prototype.slice.call(el.files||[]).slice(0,lim);
    if(fs.length){out[k]=[];(function(k2,fs2){
      ps.push(Promise.all(fs2.map(b64)).then(function(arr){
        for(var j=0;j<arr.length;j++)out[k2].push({имя:fs2[j].name,b64:arr[j]});
      }))})(k,fs)}
  }
  return Promise.all(ps).then(function(){return out});
}
function safefn(s){return String(s||'').replace(/[\\\\/:*?"<>|]+/g,'_')
  .replace(/\\s+/g,'_').slice(0,60)}
function idv(id){var el=document.getElementById(id);return el?el.value.trim():''}
function save(){
  var errs=validate();
  if(errs.length){alert('Заполните обязательные поля:\\n- '+errs.join('\\n- '));return}
  var stu={fio:M.sid?M.fio:idv('bf_fio'),
           группа:M.sid?M.group:idv('bf_group'),
           бригада:M.sid?M.brigade:idv('bf_brig')};
  if(M.sid){stu.sid=M.sid;stu.подпись=M.sig}
  if(!stu.fio){alert('Впишите ФИО в шапке бланка.');return}
  buildFiles().then(function(files){
    var p={формат:FMT_WC,версия:1,задание:M.tid,курс:M.cid,занятие:M.lid,
      студент:stu,токен:M.token||'',когда:new Date().toISOString(),
      примечание:idv('bf_note'),ответы:buildAnswers(),файлы:files};
    var blob=new Blob([JSON.stringify(p)],{type:'application/json'});
    var a=document.createElement('a');
    a.href=URL.createObjectURL(blob);
    a.download='работа_'+M.tid+'_'+safefn(stu.fio)+'.json';
    document.body.appendChild(a);a.click();
    setTimeout(function(){URL.revokeObjectURL(a.href);a.remove()},500);
    var m=document.getElementById('svmsg');
    if(m)m.textContent='Файл сохранён: '+a.download;
  }).catch(function(e){alert('Ошибка подготовки файла: '+(e.message||e))});
}
var FMT_WC=__FMT__;
"""

BLANK_TPL = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Бланк: __TITLE__</title>
<style>__CSS__</style>
</head>
<body>
<h1>Бланк задания</h1>
<div class="meta">
  <div><b>Задание:</b> __TITLE__</div>
  <div><b>Курс:</b> __COURSE__ · <b>Занятие:</b> __LESSON__</div>
  <div>__DEADLINE__</div>
  <div>__IDENT__</div>
</div>
__PLANWARN__
<div class="desc">__DESC__</div>
<h2>Форма отчёта</h2>
__FORM__
<div class="fld"><label class="fld-llabel">Комментарий к сдаче (необязательно)</label>
<textarea id="bf_note" rows="2" placeholder="Например: почему сдаю позже срока…"></textarea></div>
<div class="savebar noprint">
  <button type="button" class="big" onclick="save()">💾 Сохранить работу (.json)</button>
  <span id="svmsg"></span>
  <p class="muted" style="margin:6px 0 0">Дальше: загрузите этот файл в СДО —
  «📥 Офлайн-сдача» в шапке сайта, или передайте преподавателю.</p>
</div>
<footer>Бланк сформирован СДО works-core (модуль «Офлайн-сдача»).
Работайте offline, интернет нужен только для загрузки файла работы.</footer>
<script>__JS__</script>
</body>
</html>"""


def _build_blank(task, lesson, course, sid, signed, stu=None, token="",
                 issued=""):
    """Собрать HTML бланка. sid="" — анонимный бланк (поля ввода ФИО).
    token — индивидуальный токен выдачи (защита от списывания)."""
    title = task.get("title", "")
    settings = task.get("настройки") or {}
    dl = _parse_dl(settings.get("срок"))
    stu = stu or {}
    meta = {
        "tid": task.get("id", ""),
        "cid": (course or {}).get("id", ""),
        "lid": (lesson or {}).get("id", ""),
        "title": title,
        "course": (course or {}).get("title", ""),
        "lesson": (lesson or {}).get("title", ""),
        "deadline": dl.strftime("%d.%m.%Y %H:%M") if dl else "",
        "sid": sid or "",
        "sig": signed or "",
        "token": token or "",
        "выдан": issued or "",
        "fio": (stu.get("fio") or "") if sid else "",
        "group": (stu.get("group") or "") if sid else "",
        "brigade": (stu.get("бригада") or "").strip() if sid else "",
        "plan": bool(settings.get("план")),
    }
    fields = []
    labels = {}
    for fd in task.get("форма") or []:
        key = fd.get("ключ", "")
        if fd.get("тип") in ("file", "firmware", "shlei", "hidden"):
            labels[key] = fd.get("вопрос") or fd.get("подсказка") or key
        elif fd.get("тип") == "static":
            continue
        else:
            labels[key] = fd.get("вопрос") or fd.get("подсказка") or key
        h = _field_html(fd)
        if h:
            fields.append(h)
    html = (BLANK_TPL
            .replace("__TITLE__", _e(title))
            .replace("__COURSE__", _e(meta["course"]) or "—")
            .replace("__LESSON__", _e(meta["lesson"]) or "—")
            .replace("__DEADLINE__",
                     ("<div><b>Срок сдачи:</b> %s</div>" % _e(meta["deadline"]))
                     if meta["deadline"] else
                     "<div class='muted'>Срок сдачи не установлен</div>")
            .replace("__IDENT__", _ident_html(meta))
            .replace("__PLANWARN__",
                     ("<div class='warn'>⚠️ Это задание содержит <b>интерактивный "
                      "план</b>. В бланке план не передаётся — расставьте "
                      "обозначения на сайте и учтите это при сдаче.</div>")
                     if meta["plan"] else "")
            .replace("__DESC__", _md(task.get("описание", "")))
            .replace("__FORM__", "".join(fields))
            .replace("__CSS__", BLANK_CSS)
            .replace("__JS__", (BLANK_JS
                                .replace("__META__", json.dumps(
                                    meta, ensure_ascii=False)
                                    .replace("<", "\\u003c"))
                                .replace("__LABELS__", json.dumps(
                                    labels, ensure_ascii=False)
                                    .replace("<", "\\u003c"))
                                .replace("__FMT__", json.dumps(FMT))))
            )
    return html


def _ident_html(meta):
    """Блок «Работу сдал(а)» в шапке бланка."""
    if meta["sid"]:
        bits = ['<b>Работу сдал(а):</b> %s' % _e(meta["fio"])]
        if meta["group"]:
            bits.append("группа %s" % _e(meta["group"]))
        if meta["brigade"]:
            bits.append("бригада «%s»" % _e(meta["brigade"]))
        bits.append('<span class="muted">— данные подтверждены системой</span>')
        if meta.get("token"):
            code = str(meta["token"])[-8:]
            mark = "бланк промаркирован: код %s-%s" % (code[:4], code[4:])
            if meta.get("выдан"):
                mark += " · выдан %s" % meta["выдан"]
            bits.append('<span class="muted">%s</span>' % _e(mark))
        return "<div>%s</div>" % " · ".join(bits)
    return ('<div><b>Работу сдал(а):</b> '
            '<input type="text" id="bf_fio" placeholder="ФИО полностью" '
            'style="width:220px"> группа <input type="text" id="bf_group" '
            'placeholder="группа" style="width:90px"> бригада '
            '<input type="text" id="bf_brig" placeholder="бригада (если есть)" '
            'style="width:130px"> <span class="muted">(впишите свои данные)</span>'
            '</div>')


# ── Код, встраиваемый в шапку страниц ────────────────────────────────────

HEAD_JS = """<script>
document.addEventListener('DOMContentLoaded',function(){
 try{
  var staff=document.body.classList.contains('staff');
  var n=document.querySelector('header.topbar nav');
  if(n&&!n.querySelector('a[href="/staff/offline"]')&&
     !n.querySelector('a[href="/offline"]')){
    var a=document.createElement('a');
    if(staff){a.href='/staff/offline';
      a.title='Выдать бланки офлайн-сдачи, импортировать работы'}
    else{a.href='/offline';
      a.title='Загрузить работу, выполненную офлайн'}
    a.textContent='\\ud83d\\udce5 Офлайн-сдача';n.appendChild(a);
  }
  var m=location.pathname.match(/^\\/task\\/([^\\/?]+)/);
  if(m&&!staff&&document.querySelector('form.task-form')&&
     !document.getElementById('wc-offline-note')){
    var f=document.querySelector('form.task-form');
    var d=document.createElement('div');d.className='notice';
    d.id='wc-offline-note';
    d.innerHTML='Офлайн-сдача: бланк выдаёт преподаватель (панель '
      +'«\\ud83d\\udce5 Офлайн-сдача»). Выполненную работу загрузите в '
      +'разделе «\\ud83d\\udce5 Офлайн-сдача» в шапке сайта.';
    if(f&&f.parentNode)f.parentNode.insertBefore(d,f);
    else{var main=document.getElementById('main');
      if(main)main.appendChild(d)}
  }
 }catch(e){}
});</script>"""


def _q(params, key, dflt=""):
    """Значение query-параметра (приходит списком)."""
    v = params.get(key)
    if isinstance(v, list):
        return v[0] if v else dflt
    return v if v else dflt


def _rows_table(rows):
    out = ['<table style="border-collapse:collapse;width:100%">',
           '<tr><th style="text-align:left;border:1px solid #dbe4ef;'
           'padding:6px 10px;background:#eef2f7">Файл</th>'
           '<th style="text-align:left;border:1px solid #dbe4ef;padding:6px 10px;'
           'background:#eef2f7">Результат</th></tr>']
    for name, ok, info in rows:
        icon = "✅" if ok else ("⏸" if ok is None else "❌")
        cell = _e(info) if not isinstance(info, dict) else (
            "сдано: <b>%s</b> · задание «%s» · версия %d%s%s%s%s" % (
                _e(info.get("студент", "")), _e(info.get("задание", "")),
                info.get("версия", 0),
                " · за бригаду «%s»" % _e(info["бригада"])
                if info.get("бригада") else "",
                " · ⚠ токен: %s" % _e(info["warn"]) if info.get("warn") else "",
                " · ⚠ похоже на работу: %s" % _e(info["похожесть"])
                if info.get("похожесть") else "",
                ' · <a href="/staff/sub/%s">👁 посмотреть работу</a>'
                % _e(info["link"]) if info.get("link") else ""))
        cid = info.get("курс", "") if isinstance(info, dict) else ""
        out.append('<tr data-wcf="%s"><td style="border:1px solid #dbe4ef;'
                   'padding:6px 10px">%s'
                   '</td><td style="border:1px solid #dbe4ef;padding:6px 10px">'
                   '%s %s</td></tr>' % (_e(cid), _e(name), icon, cell))
    out.append("</table>")
    return "".join(out)


def _staff_works_section(ctx):
    """Панель «Работы офлайн-сдачи»: всё, что сдано через модуль."""
    rows = []
    for sub in ctx.list_submissions():
        vers = [v for v in (sub.get("versions") or [])
                if isinstance(v.get("офлайн"), dict)]
        if not vers:
            continue
        ver = vers[-1]
        sid = sub.get("student", "")
        tid = sub.get("task", "")
        stu = ctx.get_student(sid) or {}
        task = ctx.get_task(tid) or {}
        key = sub.get("key") or ("%s__%s" % (tid, sid))
        tok = ver["офлайн"].get("токен") or ""
        tok_s = ("✔ токен совпадает" if tok == "ok"
                 else ("⚠ %s" % tok if tok else ""))
        sim = ver.get("похожесть") or []
        sim_s = ", ".join("%s (%d%%)" % (m.get("fio", "?"),
                                         m.get("процент", 0))
                          for m in sim[:2]) if sim else "—"
        rows.append((ver.get("time", ""), task.get("title") or tid,
                     stu.get("fio") or sid, ver.get("n", 0),
                     key, tok_s, sim_s, _task_course(ctx, tid)))
    rows.sort(reverse=True)
    if not rows:
        return ('<div class="task-desc"><h2>📥 Работы офлайн-сдачи</h2>'
                '<p class="hint">Пока никто не сдал работу через '
                'офлайн-модуль. Работа студента — это обычная сдача: '
                'список работ есть на странице задания, просмотр — '
                'по ссылке «👁».</p></div>')
    trs = "".join(
        '<tr data-wcf="%s"><td style="border:1px solid #dbe4ef;padding:6px 10px">%s</td>'
        '<td style="border:1px solid #dbe4ef;padding:6px 10px">%s</td>'
        '<td style="border:1px solid #dbe4ef;padding:6px 10px"><b>%s</b></td>'
        '<td style="border:1px solid #dbe4ef;padding:6px 10px">v%d</td>'
        '<td style="border:1px solid #dbe4ef;padding:6px 10px">%s</td>'
        '<td style="border:1px solid #dbe4ef;padding:6px 10px">%s</td>'
        '<td style="border:1px solid #dbe4ef;padding:6px 10px">'
        '<a href="/staff/sub/%s/v%d">👁 посмотреть работу</a></td></tr>'
        % (cid, _e(t), _e(s), _e(f), n, _e(tk), _e(sm), _e(key), n)
        for (t, s, f, n, key, tk, sm, cid) in rows[:100])
    return ('<div class="task-desc"><h2>📥 Работы офлайн-сдачи</h2>'
            '<p class="hint">Показано %d из %d последних. В просмотре — '
            'ответы формы, файлы работы, история версий и форма вердикта.'
            '</p>'
            '<table style="border-collapse:collapse;width:100%%">'
            '<tr><th style="text-align:left;border:1px solid #dbe4ef;'
            'padding:6px 10px;background:#eef2f7">Когда</th>'
            '<th style="text-align:left;border:1px solid #dbe4ef;'
            'padding:6px 10px;background:#eef2f7">Задание</th>'
            '<th style="text-align:left;border:1px solid #dbe4ef;'
            'padding:6px 10px;background:#eef2f7">Студент</th>'
            '<th style="text-align:left;border:1px solid #dbe4ef;'
            'padding:6px 10px;background:#eef2f7">Версия</th>'
            '<th style="text-align:left;border:1px solid #dbe4ef;'
            'padding:6px 10px;background:#eef2f7">Токен</th>'
            '<th style="text-align:left;border:1px solid #dbe4ef;'
            'padding:6px 10px;background:#eef2f7">Похожесть</th>'
            '<th style="text-align:left;border:1px solid #dbe4ef;'
            'padding:6px 10px;background:#eef2f7">Просмотр</th></tr>%s'
            '</table></div>' % (min(100, len(rows)), len(rows), trs))


def _staff_sim_section(ctx):
    """Панель «Возможное списывание»: пары похожих работ."""
    flags = ctx.kv_load("флаги", {})
    rows = []
    for tid, items in flags.items():
        task = ctx.get_task(tid) or {}
        tname = task.get("title") or tid
        for it in items:
            a = (ctx.get_student(str(it.get("sid_a") or "")) or {}).get(
                "fio") or it.get("sid_a") or "?"
            b = (ctx.get_student(str(it.get("sid_b") or "")) or {}).get(
                "fio") or it.get("sid_b") or "?"
            rows.append((str(it.get("когда") or ""), tname, str(a), str(b),
                         it, tid, _task_course(ctx, tid)))
    rows.sort(key=lambda r: r[0], reverse=True)
    if not rows:
        return ('<div class="task-desc"><h2>⚠️ Возможное списывание</h2>'
                '<p class="hint">Совпадений работ не обнаружено. Сравнение '
                'выполняется автоматически при каждой офлайн-сдаче: '
                'похожесть текста (шинглы слов, порог %d%%) и полностью '
                'идентичные файлы.</p></div>' % round(SIM_MIN * 100))
    trs = "".join(
        '<tr data-wcf="%s"><td style="border:1px solid #dbe4ef;padding:6px 10px">%s</td>'
        '<td style="border:1px solid #dbe4ef;padding:6px 10px">%s</td>'
        '<td style="border:1px solid #dbe4ef;padding:6px 10px">'
        '<a href="/staff/sub/%s__%s"><b>%s</b></a></td>'
        '<td style="border:1px solid #dbe4ef;padding:6px 10px">'
        '<a href="/staff/sub/%s__%s">%s</a></td>'
        '<td style="border:1px solid #dbe4ef;padding:6px 10px">%d%% · %s</td>'
        '</tr>' % (cid, _e(w), _e(t),
                   _e(tid2), _e(str(it.get("sid_b") or "")), _e(b),
                   _e(tid2), _e(str(it.get("sid_a") or "")), _e(a),
                   it.get("процент", 0), _e(it.get("тип", "")))
        for w, t, a, b, it, tid2, cid in rows[:100])
    return ('<div class="task-desc"><h2>⚠️ Возможное списывание</h2>'
            '<p>Найдено пар: %d</p>'
            '<table style="border-collapse:collapse;width:100%%">'
            '<tr><th style="text-align:left;border:1px solid #dbe4ef;'
            'padding:6px 10px;background:#eef2f7">Когда</th>'
            '<th style="text-align:left;border:1px solid #dbe4ef;'
            'padding:6px 10px;background:#eef2f7">Задание</th>'
            '<th style="text-align:left;border:1px solid #dbe4ef;'
            'padding:6px 10px;background:#eef2f7">Работа</th>'
            '<th style="text-align:left;border:1px solid #dbe4ef;'
            'padding:6px 10px;background:#eef2f7">Похожа на работу</th>'
            '<th style="text-align:left;border:1px solid #dbe4ef;'
            'padding:6px 10px;background:#eef2f7">Сходство</th></tr>%s'
            '</table><p class="hint">Проверьте обе работы, прежде чем '
            'принимать. Сходство 100%% по файлу — схемы приложены '
            'одинаковые.</p></div>' % (len(rows), trs))


def _staff_tokens_section(ctx):
    """Панель «Токены выдачи»: кому и когда выдавались бланки."""
    kv = ctx.kv_load("выдачи", {})
    if not kv:
        return ('<div class="task-desc"><h2>🔐 Токены выдачи бланков</h2>'
                '<p class="hint">Бланки ещё не выдавались. Токен вшивается '
                'в бланк при выдаче (форма «📤 Выдача бланков» выше); '
                'работа без своего токена от студента не принимается.'
                '</p></div>')
    rows = []
    for k, rec in kv.items():
        sid, _sep, tid = k.partition("|")
        stu = ctx.get_student(sid) or {}
        task = ctx.get_task(tid) or {}
        sub = ctx._core.sub(tid, sid)
        vers = (sub or {}).get("versions") or []
        if vers:
            last = vers[-1]
            tok = (last.get("офлайн") or {}).get("токен") or ""
            state = ("✔ токен совпадает" if tok == "ok"
                     else ("⚠ %s" % tok if tok
                           else "— сдано не через офлайн-модуль"))
            when_sub = "версия %s · %s" % (
                last.get("n", "?"),
                str(last.get("time", ""))[:16].replace("T", " "))
        else:
            state, when_sub = "— работа не сдана", "—"
        view = ('<a href="/staff/sub/%s__%s">👁 посмотреть</a>'
                % (_e(tid), _e(sid))) if vers else "—"
        rows.append((rec.get("выдан") or 0, task.get("title") or tid,
                     stu.get("fio") or sid, _fmt_ts(rec.get("выдан")),
                     when_sub, state, view,
                     _task_course(ctx, tid)))
    rows.sort(reverse=True)
    trs = "".join(
        '<tr data-wcf="%s"><td style="border:1px solid #dbe4ef;'
        'padding:6px 10px">%s</td>'
        '<td style="border:1px solid #dbe4ef;padding:6px 10px">%s</td>'
        '<td style="border:1px solid #dbe4ef;padding:6px 10px">%s</td>'
        '<td style="border:1px solid #dbe4ef;padding:6px 10px">%s</td>'
        '<td style="border:1px solid #dbe4ef;padding:6px 10px">%s</td>'
        '<td style="border:1px solid #dbe4ef;padding:6px 10px">%s</td></tr>'
        % (cid, _e(t), _e(s), _e(i), _e(c), _e(st), v)
        for _ts, t, s, i, c, st, v, cid in rows[:100])
    return ('<div class="task-desc"><h2>🔐 Токены выдачи бланков</h2>'
            '<table style="border-collapse:collapse;width:100%%">'
            '<tr><th style="text-align:left;border:1px solid #dbe4ef;'
            'padding:6px 10px;background:#eef2f7">Задание</th>'
            '<th style="text-align:left;border:1px solid #dbe4ef;'
            'padding:6px 10px;background:#eef2f7">Студент</th>'
            '<th style="text-align:left;border:1px solid #dbe4ef;'
            'padding:6px 10px;background:#eef2f7">Бланк выдан</th>'
            '<th style="text-align:left;border:1px solid #dbe4ef;'
            'padding:6px 10px;background:#eef2f7">Работа сдана</th>'
            '<th style="text-align:left;border:1px solid #dbe4ef;'
            'padding:6px 10px;background:#eef2f7">Токен</th>'
            '<th style="text-align:left;border:1px solid #dbe4ef;'
            'padding:6px 10px;background:#eef2f7">Просмотр</th></tr>%s'
            '</table><p class="hint">При выдаче бланка старый токен '
            'стирается и выдаётся новый: действителен только последний. '
            'Показано %d из %d записей.</p></div>'
            % (trs, min(100, len(rows)), len(rows)))


def _course_students(ctx, cid):
    """Студенты курса: зачисленные; если их нет — все (курс открыт)."""
    c = ctx.get_course(cid or "")
    sids = [x for x in ((c or {}).get("студенты") or []) if x]
    if sids:
        return [s for s in (ctx.get_student(x) for x in sids) if s]
    return sorted(ctx.list_students(), key=lambda s: s.get("fio", ""))


def _prune_pending(ctx):
    pend = ctx.kv_load("pending", {})
    now = time.time()
    stale = [k for k, v in pend.items()
             if now - (v.get("создан") or 0) > PENDING_TTL]
    if stale:
        for k in stale:
            pend.pop(k, None)
        ctx.kv_save("pending", pend)


def _task_course(ctx, tid):
    """Курс задания (по его занятию); «» если не найден."""
    task = ctx.get_task(tid or "")
    if not task:
        return ""
    lesson = ctx.get_lesson(task.get("lesson", ""))
    return (lesson or {}).get("course", "")


# ── Токены выдачи бланков (защита от списывания) ─────────────────────────

def _issue_token(ctx, sid, tid):
    """Выдать индивидуальный токен бланка. Старый токен стирается."""
    tok = secrets.token_hex(12)
    kv = ctx.kv_load("выдачи", {})
    kv["%s|%s" % (sid, tid)] = {"токен": tok, "выдан": time.time()}
    ctx.kv_save("выдачи", kv)
    return tok


def _issued_rec(ctx, sid, tid):
    """Запись о выдаче токена студенту за задание (или None)."""
    return (ctx.kv_load("выдачи", {}).get("%s|%s" % (sid, tid)))


def _fmt_ts(ts):
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def _token_check(ctx, payload, sid, for_staff):
    """Проверить токен выдачи в файле работы.

    Возвращает "" (ok) или текст предупреждения; для студента отказ
    оформляет вызывающая сторона через ValueError.
    """
    tok = str(payload.get("токен") or "")
    rec = _issued_rec(ctx, sid, str(payload.get("задание") or ""))
    if not rec:
        if for_staff:
            return "токен выдачи не выдавался этому студенту"
        raise ValueError("токен выдачи не найден — бланк для этого задания "
                         "вам ещё не выдавался. Скачайте бланк со своей "
                         "страницы задания")
    if not tok:
        if for_staff:
            return "токен выдачи отсутствует в файле"
        raise ValueError("в файле нет токена выдачи — скачайте бланк со "
                         "своей страницы задания заново")
    if tok != rec.get("токен"):
        if for_staff:
            return "токен выдачи не совпадает с выданным"
        raise ValueError("токен выдачи не совпадает — файл из чужого бланка "
                         "или бланк был перевыпущен. Скачайте бланк заново "
                         "и заполните его")
    return ""


# ── Детект сходства работ (шинглы слов + Жаккар, идентичные файлы) ───────

def _shingles(text, k=SIM_K, min_words=SIM_MIN_WORDS):
    """Множество k-словных шинглов, свёрнутых в 64-битные хеши."""
    words = [w for w in re.split(r"\W+", str(text or "").lower()) if w]
    if len(words) < min_words:
        return set()
    return {int.from_bytes(hashlib.blake2b(
        " ".join(words[i:i + k]).encode("utf-8"),
        digest_size=8).digest(), "big")
        for i in range(len(words) - k + 1)}


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _sim_text_fp(task, answers):
    """Отпечаток текстовых полей формы (text/textarea)."""
    types = {fd.get("ключ"): fd.get("тип")
             for fd in (task.get("форма") or [])}
    parts = [v for k, v in (answers or {}).items()
             if isinstance(v, str) and types.get(k) in ("text", "textarea")]
    return _shingles(" ".join(parts))


def _sim_file_fp(ctx, ver):
    """SHA-256 приложенных файлов работы (для поиска идентичных копий)."""
    out = {}
    base = ctx._core.store.subs
    for k, meta in (ver.get("files") or {}).items():
        rel = str(meta.get("файл") or "")
        p = os.path.join(base, *rel.split("/")) if rel else ""
        if not p:
            continue
        try:
            with open(p, "rb") as f:
                out[k] = hashlib.sha256(f.read()).hexdigest()
        except OSError:
            pass
    return out


def _sim_check(ctx, task, tid, sid, ver, key):
    """Сравнить работу с работами других студентов по этому заданию.

    Возвращает список совпадений [{sid, fio, вер, процент, тип}] и
    записывает флаги в KV «флаги» + отпечаток в KV «sim».
    """
    text_fp = _sim_text_fp(task, ver.get("answers") or {})
    file_fp = _sim_file_fp(ctx, ver)
    if not text_fp and not file_fp:
        return []
    kv = ctx.kv_load("sim", {})
    store = kv.get(tid) or []
    matches = []
    flags = ctx.kv_load("флаги", {})
    now = datetime.now().isoformat(timespec="seconds")
    for e in store:
        if e.get("sid") == sid:
            continue
        pct, typ = 0.0, ""
        j = _jaccard(text_fp, set(e.get("шиглы") or []))
        if j >= SIM_MIN:
            pct, typ = j, "текст"
        eh = set((e.get("файлы") or {}).values())
        for h in file_fp.values():
            if h in eh and 1.0 > pct:
                pct, typ = 1.0, "файл"
        if not typ:
            continue
        stu2 = ctx.get_student(e.get("sid") or "") or {}
        matches.append({"sid": e.get("sid", ""), "fio": stu2.get("fio", "?"),
                        "вер": e.get("вер", 1),
                        "процент": round(pct * 100), "тип": typ})
        fl = flags.setdefault(tid, [])
        if not any(f.get("a") == e.get("key") and f.get("b") == key
                   for f in fl):
            fl.append({"a": e.get("key", ""), "b": key,
                       "sid_a": e.get("sid", ""), "sid_b": sid,
                       "процент": round(pct * 100), "тип": typ,
                       "когда": now})
        ctx.kv_save("флаги", flags)
    store.append({"key": key, "sid": sid, "вер": ver.get("n", 1),
                  "шиглы": sorted(text_fp), "файлы": file_fp, "когда": now})
    kv[tid] = store[-300:]
    ctx.kv_save("sim", kv)
    return matches


# ── Выдача бланков преподавателем ────────────────────────────────────────

ZIP_README = (
    "Офлайн-сдача работы — что делать\n"
    "\n"
    "1. Откройте файл бланка (HTML) в браузере — интернет не нужен.\n"
    "2. Заполните поля, при необходимости приложите файлы.\n"
    "3. Нажмите «Сохранить работу (.json)» — получите файл работы.\n"
    "4. Передайте файл преподавателю или загрузите сами в СДО:\n"
    "   раздел «Офлайн-сдача» в шапке сайта.\n"
    "\n"
    "Бланк промаркирован вашим индивидуальным кодом: работа принимается\n"
    "только из вашего бланка и только под вашим именем.\n")


def _multi(v):
    """Повторяющееся поле POST как список (чекбоксы)."""
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v if str(x)]
    return [str(v)]


def _safezip(s):
    """Имя архива студента: ФИО с пробелами, опасные символы — прочерк."""
    base = re.sub(r'[\\/:*?"<>|]+', "_", str(s or ""))
    base = re.sub(r"\s+", " ", base).strip()
    return base or "архив"


def _issue_form(ctx):
    """Форма выдачи бланков: выбор студентов и заданий."""
    trows = []
    for c in ctx.list_courses():
        ls = ctx.list_lessons(c["id"])
        if not ls:
            continue
        grp = ['<p style="margin:10px 0 4px"><b>%s</b></p>'
               % _e(c.get("title", ""))]
        for l in ls:
            ts = ctx.list_tasks(l["id"])
            if not ts:
                continue
            grp.append('<p class="hint" style="margin:6px 0 2px">%s</p>'
                       % _e(l.get("title", "")))
            for t in ts:
                grp.append('<label class="opt" style="display:block">'
                           '<input type="checkbox" name="task" '
                           'value="%s"> %s</label>'
                           % (_e(t["id"]), _e(t.get("title", ""))))
        trows.append('<div data-wcf="%s">%s</div>'
                     % (_e(c["id"]), "".join(grp)))
    srows = []
    # Студент относится к курсу, где записан явно, и ко всем «открытым»
    # курсам (без явного списка студентов — туда можно любого).
    open_c = [c["id"] for c in ctx.list_courses()
              if not (c.get("студенты") or [])]
    enroll = {}
    for c in ctx.list_courses():
        for sid in (c.get("студенты") or []):
            if sid:
                enroll.setdefault(sid, set()).add(c["id"])
    for s in sorted(ctx.list_students(), key=lambda x: x.get("fio", "")):
        bits = [_e(s.get("fio", "?"))]
        if s.get("group"):
            bits.append("гр. %s" % _e(s["group"]))
        if (s.get("бригада") or "").strip():
            bits.append("бригада «%s»" % _e(s["бригада"]))
        cs = " ".join(sorted(enroll.get(s["id"], set()) | set(open_c)))
        srows.append('<label class="opt" style="display:block" '
                     'data-wcf="%s" data-fio="%s" data-grp="%s">'
                     '<input type="checkbox" name="student" value="%s"> %s'
                     '</label>' % (cs, _e(s.get("fio", "")),
                                   _e(s.get("group", "")), _e(s["id"]),
                                   " · ".join(bits)))
    if not trows:
        trows.append('<p class="hint">Нет заданий.</p>')
    if not srows:
        srows.append('<p class="hint">Нет студентов.</p>')
    grps = sorted({s.get("group", "").strip()
                   for s in ctx.list_students()
                   if (s.get("group") or "").strip()})
    grp_opts = ('<option value="">все группы</option>' + "".join(
        '<option value="%s">%s</option>' % (_e(g), _e(g)) for g in grps))
    return (
        '<form method="post" action="/staff/offline/issue" id="issue-form" '
        'class="staff-card">'
        '<h2>📤 Выдача бланков</h2>'
        '<p class="hint">Выберите студентов и задания, которые они должны '
        'сдать. Скачается архив: на каждого студента — один архив «ФИО.zip» '
        'с бланками выбранных заданий. Бланк промаркирован индивидуальным '
        'токеном студента; при повторной выдаче старый токен стирается и '
        'предыдущий бланк перестаёт действовать.</p>'
        '<script>function wcTog(box,cls){var on=box.checked,'
        'els=document.querySelectorAll(\'#issue-form input[name="\'+cls'
        '+\'"]\');for(var i=0;i<els.length;i++){var lab=els[i].closest'
        '(\'label\');if(lab&&lab.offsetParent===null)continue;'
        'els[i].checked=on}}</script>'
        '<fieldset style="border:1px solid #dbe4ef;border-radius:10px;'
        'padding:10px;max-height:260px;overflow:auto">'
        '<legend><b>Задания</b> · <label class="hint"><input type="checkbox" '
        'onchange="wcTog(this,\'task\')"> все</label></legend>'
        '%s</fieldset>'
        '<fieldset style="border:1px solid #dbe4ef;border-radius:10px;'
        'padding:10px;max-height:260px;overflow:auto;margin-top:10px">'
        '<legend><b>Студенты</b> · <label class="hint"><input '
        'type="checkbox" onchange="wcTog(this,\'student\')"> '
        'все</label><span id="wc-scount"></span></legend>'
        '<p style="margin:6px 0">'
        '<input type="text" id="wc-sfio" placeholder="🔍 ФИО студента…" '
        'oninput="wcStuFilter()" style="max-width:200px"> '
        '<select id="wc-sgrp" onchange="wcStuFilter()">%s</select></p>'
        '%s</fieldset>'
        '<p style="margin-top:10px"><button>⬇️ Скачать бланки</button></p>'
        '</form>' % ("".join(trows), grp_opts, "".join(srows)))


# ── Разбор файла работы ──────────────────────────────────────────────────

def _import_one(ctx, handler, up, for_staff, current_sid):
    """Разобрать один файл работы.

    Возвращает словарь: {"ok": True, "info": …} при успехе;
    {"ok": False, "err": текст} при отказе;
    {"ok": False, "manual": True, payload, fio, группа, курс, задание} —
    если работу без подписи не удалось распознать однозначно.
    """
    raw = up.data or b""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return {"ok": False, "err": "файл не читается как JSON"}
    if not isinstance(payload, dict):
        return {"ok": False, "err": "файл не читается как JSON"}
    if payload.get("формат") != FMT or payload.get("версия") != VER:
        return {"ok": False,
                "err": "не файл работы works-core (проверьте формат и версию)"}
    tid = str(payload.get("задание") or "")
    task = ctx.get_task(tid)
    if not task:
        return {"ok": False, "err": "задание «%s» не найдено" % (tid or "?")}
    stu_in = payload.get("студент") or {}
    try:
        sid, warn = _resolve_student(ctx, handler, payload, for_staff,
                                     current_sid)
    except _Manual:
        return {"ok": False, "manual": True, "payload": payload,
                "fio": str(stu_in.get("fio") or "?"),
                "группа": str(stu_in.get("group") or "?"),
                "курс": str(payload.get("курс") or ""),
                "задание": tid}
    except ValueError as ex:
        return {"ok": False, "err": str(ex)}
    info, err = _do_submit(ctx, task, payload, sid, for_staff, handler, warn)
    if err:
        return {"ok": False, "err": err}
    return {"ok": True, "info": info}


def _resolve_student(ctx, handler, payload, for_staff, current_sid):
    """Определить студента по файлу работы. Возвращает (sid, предупреждение).

    Бросает _Manual (спорная работа — нужен выбор преподавателя)
    или ValueError (отказ с текстом ошибки).
    Работа студента обязана нести валидный токен выдачи бланка; для
    преподавателя несовпадение токена — предупреждение, не отказ.
    """
    stu_in = payload.get("студент") or {}
    sid = str(stu_in.get("sid") or "")
    mac = str(stu_in.get("подпись") or "")
    fio = _norm_fio(stu_in.get("fio"))
    group = str(stu_in.get("group") or "").strip()

    if sid:
        # Файл подписан: подпись обязана совпадать со студентом.
        if not mac or handler._sign_sid(sid) != sid + "." + mac:
            raise ValueError("подпись работы не совпадает со студентом")
        if not for_staff and sid != current_sid:
            raise ValueError("в файле работа другого студента")
        if not ctx.get_student(sid):
            raise ValueError("студент «%s» не найден в системе" % sid)
        warn = _token_check(ctx, payload, sid, for_staff)
        return sid, warn

    # Файл без подписи.
    if not for_staff:
        # Студенту запрещено целиком: работа обязана идти из его бланка.
        raise ValueError("в файле нет токена выдачи. Скачайте бланк со "
                         "своей страницы задания и сдайте работу в нём")

    # Преподаватель: однозначное совпадение ФИО среди студентов курса.
    if not fio:
        raise ValueError("в файле нет ни подписи, ни ФИО студента")
    cands = [s for s in _course_students(ctx, str(payload.get("курс") or ""))
             if _norm_fio(s.get("fio")) == fio]
    if group:
        byg = [s for s in cands if str(s.get("group") or "").strip() == group]
        if byg:
            cands = byg
    if len(cands) == 1:
        return cands[0]["id"], ""
    raise _Manual()


def _do_submit(ctx, task, payload, sid, for_staff, handler, warn=""):
    """Создать сдачу из файла работы. Возвращает (info, ошибка)."""
    stu = ctx.get_student(sid) or {}
    answers = {}
    for k, v in (payload.get("ответы") or {}).items():
        if isinstance(v, list):
            answers[str(k)] = [str(x) for x in v if str(x)]
        elif isinstance(v, dict):
            continue
        else:
            answers[str(k)] = str(v)

    # Вложения: b64 → bytes (лимит на суммарный размер).
    ftypes = {fd.get("ключ"): fd.get("тип")
              for fd in (task.get("форма") or [])}
    files = {}
    total = 0
    for key, items in (payload.get("файлы") or {}).items():
        if not isinstance(items, list):
            items = [items]
        ups = []
        for it in items:
            if not isinstance(it, dict):
                continue
            name = str(it.get("имя") or "файл")
            try:
                data = base64.b64decode(str(it.get("b64") or ""))
            except Exception:
                return None, "вложение «%s» повреждено (base64)" % name
            if not data:
                continue
            total += len(data)
            if total > MAX_ATTACH:
                return None, ("вложения слишком большие — больше %d МБ"
                              % (MAX_ATTACH // (1024 * 1024)))
            ups.append(_Up(name, data))
        if ups:
            files[str(key)] = ups if ftypes.get(key) == "firmware" else ups[0]

    note = str(payload.get("примечание") or "")
    when = str(payload.get("когда") or "")
    note = ((note + " · ") if note else "") + \
        "офлайн-сдача, файл от " + (when or "?")

    # Бригада из файла принимается, только если совпадает с текущей.
    pb = str((payload.get("студент") or {}).get("бригада") or "").strip()
    brigade = pb if pb and pb == str(stu.get("бригада") or "").strip() else ""

    # Сценарное задание (интерактивный план): в бланке план не
    # передаётся, а ядро требует его (обязательное поле). Подставляем
    # пустой план с явной пометкой, иначе офлайн-сдача сценария
    # всегда отклонялась бы.
    if ftypes.get("plan_data") and "plan_data" not in answers:
        answers["plan_data"] = "[]"
        note += (" · " if note else "") + "план не прилагался (офлайн-сдача)"

    sub, err = ctx.submit(task.get("id", ""), sid, answers, files, note,
                          brigade)
    if err or not sub:
        return None, (err or "сдача не создана")
    versions = sub.get("versions") or []
    ver = versions[-1] if versions else {}
    info = {"студент": stu.get("fio", sid), "задание": task.get("title", ""),
            "версия": ver.get("n", len(versions)), "бригада": brigade,
            "курс": _task_course(ctx, task.get("id", ""))}

    # Маркировка версии + детект сходства (защита от списывания).
    rec = _issued_rec(ctx, sid, task.get("id", "")) or {}
    ver["офлайн"] = {"токен": warn or "ok",
                     "бланк_выдан": _fmt_ts(rec.get("выдан")),
                     "файл_работы": str(payload.get("когда") or "")}
    sim = _sim_check(ctx, task, task.get("id", ""), sid, ver,
                     sub.get("key", ""))
    if sim:
        ver["похожесть"] = sim
        info["похожесть"] = ", ".join(
            "%s (%d%%)" % (m["fio"], m["процент"]) for m in sim[:3])
    if for_staff and sub.get("key"):
        info["link"] = sub["key"]
    if warn:
        info["warn"] = warn
    ctx._core.store.save()

    ctx.audit("офлайн-сдача",
              details="%s · %s · версия %s%s"
                      % (stu.get("fio", sid), task.get("title", ""),
                         ver.get("n", "?"),
                         (" · бригада " + brigade) if brigade else ""),
              who=(stu.get("fio", sid) if not for_staff else "преподаватель"),
              handler=handler)
    return info, ""


# ── Регистрация модуля ───────────────────────────────────────────────────

def register(ctx):
    # ── Ссылки в шапке и на страницах заданий ────────────────────────
    def _head(course=None, lesson=None, **kw):
        return HEAD_JS

    ctx.on("page.head", _head)

    def _home_card(**kw):
        return ('<details><summary>📥 Офлайн-сдача</summary>'
                '<p class="hint">Выдать студентам бланки офлайн-сдачи '
                '(архив «ФИО.zip» на каждого), импортировать сданные '
                'работы, проверить подозрительные сходства.</p>'
                '<p><a class="btn btn-secondary" href="/staff/offline">'
                'Открыть панель офлайн-сдачи</a></p></details>')

    ctx.on("staff.home_cards", _home_card)

    # ── Бланк задания (только преподаватель: предпросмотр анонимного
    #    бланка; персональные бланки выдаются через панель) ────────────
    @ctx.add_route("GET", "/offline/blank/", access="staff")
    def blank_page(handler, params):
        """Предпросмотр анонимного бланка (только преподаватель).

        Персональные бланки с токенами выдаются через панель
        «📤 Выдача бланков» (POST /staff/offline/issue).
        """
        tid = (params.get("_parts") or [""])[0]
        task = ctx.get_task(tid)
        if not task:
            return ctx.render_page("Задание не найдено",
                                   "<p>Такого задания нет.</p>")
        lesson = ctx.get_lesson(task.get("lesson", ""))
        course = ctx.get_course(lesson.get("course", "")) if lesson else None
        html = _build_blank(task, lesson, course, "", "", None)
        handler._send_html(html)
        return handler._SENT

    # ── Страница студента: загрузка работы ───────────────────────────
    def _student_body(stu, err_html):
        bits = ["<b>%s</b>" % _e(stu.get("fio", "?"))]
        if stu.get("group"):
            bits.append("группа %s" % _e(stu["group"]))
        if (stu.get("бригада", "") or "").strip():
            bits.append("бригада «%s»" % _e(stu["бригада"]))
        return (
            err_html +
            '<div class="notice">Вы вошли как: %s — работы будут зачтены '
            'именно вам (ФИО и группа подтягиваются автоматически).</div>'
            % " · ".join(bits) +
            '<form method="post" action="/offline/upload" '
            'enctype="multipart/form-data" class="staff-card">'
            '<p>Выберите файл(ы) работы <code>.json</code> — полученные из '
            'бланка («💾 Сохранить работу»). Можно сразу несколько — '
            'каждый будет разобран отдельно.</p>'
            '<p><label>Файлы работ: <input type="file" name="work" multiple '
            'accept=".json,application/json" required></label></p>'
            '<p><button>📥 Загрузить работу</button></p></form>'
            '<div class="task-desc"><h3>Как это работает</h3>'
            '<ol><li>Получите у преподавателя бланк (архив с вашим ФИО) — '
            'он промаркирован вашим индивидуальным токеном, работа '
            'принимается только из него.</li>'
            '<li>Откройте бланк в браузере (интернет не нужен), заполните '
            'поля, при необходимости приложите файлы, нажмите «💾 Сохранить '
            'работу» — получите файл <code>.json</code>.</li>'
            '<li>Вернитесь на эту страницу и загрузите файл — сдача появится '
            'в системе как обычная версия работы.</li></ol>'
            '<p class="hint">Если в файле подпись другого студента, система '
            'его не примет — такие работы загружает преподаватель пачкой '
            'через панель.</p></div>')

    @ctx.add_route("GET", "/offline", access="student")
    def student_page(handler, params):
        sid = handler._student()
        stu = ctx.get_student(sid) or {}
        return ctx.render_page("📥 Офлайн-сдача", _student_body(stu, ""))

    @ctx.add_route("POST", "/offline/upload", access="student")
    def upload_post(handler, params):
        sid = handler._student()
        data = handler._parse_post()
        ups = _as_uploads(data.get("work"))
        if not ups:
            stu = ctx.get_student(sid) or {}
            return ctx.render_page(
                "📥 Офлайн-сдача", _student_body(
                    stu, '<div class="error">Файлы работ не переданы — '
                         'выберите файл .json</div>'))
        rows = []
        n_ok = 0
        for up in ups:
            try:
                r = _import_one(ctx, handler, up, False, sid)
            except Exception as ex:
                r = {"ok": False, "err": "сбой обработки (%s)"
                     % type(ex).__name__}
            if r.get("ok"):
                n_ok += 1
                rows.append((up.name, True, r["info"]))
            elif r.get("manual"):
                rows.append((up.name, False,
                             "работа без подписи, ФИО не совпало — загрузите "
                             "через преподавателя"))
            else:
                rows.append((up.name, False,
                             r.get("err", "неизвестная ошибка")))
        body = ('<p><a href="/offline">← Загрузить ещё</a> · '
                '<a href="/">На главную</a></p>'
                '<h2>Результат загрузки (%d из %d принято)</h2>%s'
                % (n_ok, len(ups), _rows_table(rows)))
        return ctx.render_page("📥 Офлайн-сдача — результат", body)

    # ── Панель преподавателя ─────────────────────────────────────────
    def _staff_home_body(err_html):
        courses = ctx.list_courses()
        sel = ""
        if courses:
            opts = ('<option value="">— все курсы —</option>' + "".join(
                '<option value="%s">%s</option>'
                % (_e(c["id"]), _e(c.get("title", "")))
                for c in courses))
            sel = ('<div class="staff-card"><b>📚 Курс:</b> '
                   '<select id="wc-course" onchange="wcCourse()">'
                   + opts + '</select> '
                   '<span class="hint">фильтрует списки на странице: '
                   'задания, студенты, работы, токены, списывание. '
                   'Скрытое снимается с выдачи.</span>'
                   '<script>var wcPrevC=null;'
                   'function wcApply(){'
                   "var sel=document.getElementById('wc-course');"
                   "var v=sel?(sel.value||''):'';"
                   'var cCh=(wcPrevC!==v);wcPrevC=v;'
                   'var i,els=document.querySelectorAll("[data-wcf]");'
                   "for(i=0;i<els.length;i++){var el=els[i];"
                   'if(el.tagName==="LABEL"&&el.hasAttribute("data-fio"))'
                   'continue;'
                   "var cs=(el.getAttribute('data-wcf')||'')"
                   '.split(/\\s+/).filter(Boolean);'
                   "var show=!v||!cs.length||cs.indexOf(v)>=0;"
                   "el.style.display=show?'':'none';"
                   "if(!show){var inp=el.querySelectorAll"
                   "('input[type=checkbox]');"
                   "for(var j=0;j<inp.length;j++)inp[j].checked=false;}}"
                   "var q=(document.getElementById('wc-sfio')?"
                   "document.getElementById('wc-sfio').value:'')"
                   '.toLowerCase();'
                   "var g=document.getElementById('wc-sgrp')?"
                   "document.getElementById('wc-sgrp').value:'';"
                   "var stu=document.querySelectorAll('label[data-fio]');"
                   'var vis=0;'
                   'for(i=0;i<stu.length;i++){var lab=stu[i];'
                   "var cs=(lab.getAttribute('data-wcf')||'')"
                   '.split(/\\s+/).filter(Boolean);'
                   "var show=!v||!cs.length||cs.indexOf(v)>=0;"
                   "if(show&&q&&(lab.getAttribute('data-fio')||'')"
                   '.toLowerCase().indexOf(q)<0)show=false;'
                   "if(show&&g&&(lab.getAttribute('data-grp')||'')!==g)"
                   'show=false;'
                   "lab.style.display=show?'':'none';"
                   'if(show)vis++;'
                   'else if(cCh){var inp=lab.querySelectorAll'
                   "('input[type=checkbox]');"
                   'for(var j=0;j<inp.length;j++)inp[j].checked=false;}}'
                   "var sc=document.getElementById('wc-scount');"
                   'if(sc)sc.textContent='
                   '(q||g||v)?'
                   '(" · показано "+vis+" из "+stu.length):"";'
                   '}'
                   'function wcCourse(){wcApply()}'
                   'function wcStuFilter(){wcApply()}</script></div>')
        return (
            err_html + sel + _issue_form(ctx) +
            '<form method="post" action="/staff/offline/import" '
            'enctype="multipart/form-data" class="staff-card">'
            '<p><b>Импорт работ</b> — файлы работ (.json), полученные из '
            'бланков. Можно выбрать сразу несколько: система распознаёт '
            'студента по подписи и токену в файле (или по ФИО/группе) и '
            'создаёт сдачу. Спорные работы будут предложены к ручному '
            'выбору студента.</p>'
            '<p><label>Файлы работ: <input type="file" name="work" multiple '
            'accept=".json,application/json" required></label></p>'
            '<p><button>📥 Импортировать</button></p></form>'
            + _staff_works_section(ctx)
            + _staff_sim_section(ctx) + _staff_tokens_section(ctx))

    @ctx.add_route("GET", "/staff/offline", access="staff")
    def staff_home(handler, params):
        return ctx.render_page("📥 Офлайн-сдача", _staff_home_body(""),
                               staff=True)

    @ctx.add_route("POST", "/staff/offline/import", access="staff")
    def import_post(handler, params):
        data = handler._parse_post()
        ups = _as_uploads(data.get("work"))
        if not ups:
            return ctx.render_page(
                "📥 Офлайн-сдача", _staff_home_body(
                    '<div class="error">Файлы работ не переданы — выберите '
                    'файлы .json</div>'), staff=True)
        _prune_pending(ctx)
        pend = ctx.kv_load("pending", {})
        batch_id = secrets.token_hex(8)
        items = []
        rows = []
        total = 0
        for up in ups:
            try:
                r = _import_one(ctx, handler, up, True, "")
            except Exception as ex:
                r = {"ok": False, "err": "сбой обработки (%s)"
                     % type(ex).__name__}
            if r.get("ok"):
                rows.append((up.name, True, r["info"]))
            elif r.get("manual"):
                size = len(json.dumps(r["payload"], ensure_ascii=False))
                if total + size > MAX_BATCH:
                    rows.append((up.name, False,
                                 "файл слишком большой для отложенного "
                                 "выбора — обработайте отдельно"))
                    continue
                total += size
                items.append({"i": len(items), "файл": up.name,
                              "payload": r["payload"], "fio": r["fio"],
                              "группа": r["группа"], "курс": r["курс"],
                              "задание": r["задание"]})
                rows.append((up.name, None,
                             "студент не распознан — выберите вручную ниже"))
            else:
                rows.append((up.name, False,
                             r.get("err", "неизвестная ошибка")))
        if items:
            pend[batch_id] = {"создан": time.time(), "items": items}
            ctx.kv_save("pending", pend)
        body = ('<p><a href="/staff/offline">← Импортировать ещё</a></p>'
                '<h2>Результат импорта (%d из %d принято)</h2>%s'
                % (sum(1 for _n, ok, _i in rows if ok), len(rows),
                   _rows_table(rows)))
        if items:
            body += _pending_form(ctx, batch_id, items)
        return ctx.render_page("📥 Импорт работ — результат", body, staff=True)

    @ctx.add_route("POST", "/staff/offline/manual", access="staff")
    def manual_post(handler, params):
        data = handler._parse_post()
        bid = str(data.get("batch") or "")
        pend = ctx.kv_load("pending", {})
        batch = pend.get(bid)
        if not batch:
            return ctx.render_page(
                "Пачка не найдена",
                '<p>Пачка не найдена или уже обработана.</p>'
                '<p><a href="/staff/offline">← К импорту</a></p>', staff=True)
        drop = str(data.get("drop") or "") == "1"
        rows = []
        if drop:
            for it in batch.get("items") or []:
                rows.append((it.get("файл", "?"), False, "отменено"))
            pend.pop(bid, None)
        else:
            rest = []
            for it in batch.get("items") or []:
                sel = str(data.get("sel_%d" % it.get("i", 0)) or "")
                if not sel:
                    rest.append(it)
                    continue
                payload = it.get("payload") or {}
                task = ctx.get_task(str(payload.get("задание") or ""))
                if not task:
                    rows.append((it.get("файл", "?"), False,
                                 "задание не найдено — файл пропущен"))
                    rest.append(it)
                    continue
                info, err = _do_submit(ctx, task, payload, sel, True, handler)
                if err:
                    rows.append((it.get("файл", "?"), False, err))
                    rest.append(it)
                else:
                    rows.append((it.get("файл", "?"), True, info))
            if rest:
                batch["items"] = rest
            else:
                pend.pop(bid, None)
        ctx.kv_save("pending", pend)
        left = len((pend.get(bid) or {}).get("items") or [])
        tail = (" · нераспознанных осталось: %d" % left) if left else ""
        body = ('<h2>Зачтено вручную</h2>%s'
                '<p><a href="/staff/offline">← К импорту</a>%s</p>'
                % (_rows_table(rows), _e(tail)))
        return ctx.render_page("📥 Импорт работ — вручную", body, staff=True)

    # ── Выдача бланков: архивы «ФИО.zip» ─────────────────────────────
    @ctx.add_route("POST", "/staff/offline/issue", access="staff")
    def issue_post(handler, params):
        data = handler._parse_post()
        tasks = [t for t in (ctx.get_task(x)
                             for x in _multi(data.get("task"))) if t]
        stus = [(x, ctx.get_student(x)) for x in _multi(data.get("student"))]
        stus = [(x, s) for x, s in stus if s]
        if not tasks or not stus:
            return ctx.render_page(
                "📥 Офлайн-сдача", _staff_home_body(
                    '<div class="error">Выберите хотя бы одного студента '
                    'и одно задание.</div>'), staff=True)
        made = []                      # (имя архива, байты)
        used_names = set()
        for sid, stu in stus:
            ib = io.BytesIO()
            with zipfile.ZipFile(ib, "w", zipfile.ZIP_DEFLATED) as izf:
                for t in tasks:
                    lesson = ctx.get_lesson(t.get("lesson", ""))
                    course = (ctx.get_course(lesson.get("course", ""))
                              if lesson else None)
                    # «Голый» MAC-хвост подписи — как в куке студента.
                    signed = handler._sign_sid(sid)
                    mac = signed.split(".", 1)[1] if signed else ""
                    # Токен выдачи: перевыпуск стирает старый токен.
                    tok = _issue_token(ctx, sid, t.get("id", ""))
                    html = _build_blank(
                        t, lesson, course, sid, mac, stu, token=tok,
                        issued=_fmt_ts(time.time()))
                    izf.writestr(
                        "бланк_%s__%s.html" % (t.get("id", ""),
                                               _safefn(t.get("title", ""))),
                        html.encode("utf-8"))
                izf.writestr("README.txt", ZIP_README.encode("utf-8"))
            base = _safezip(stu.get("fio") or sid)
            name = base if base not in used_names else "%s_%s" % (base, sid)
            used_names.add(name)
            made.append((name + ".zip", ib.getvalue()))
        if len(made) == 1:
            data, fname = made[0][1], made[0][0]
        else:
            ob = io.BytesIO()
            with zipfile.ZipFile(ob, "w", zipfile.ZIP_DEFLATED) as ozf:
                for nm, b in made:
                    ozf.writestr(nm, b)
            data = ob.getvalue()
            fname = "бланки_%s.zip" % datetime.now().strftime("%Y%m%d_%H%M")
        ctx.audit("офлайн-бланки",
                  details="выдано: %s · заданий: %d"
                          % (", ".join(s.get("fio", "?")
                                       for _x, s in stus), len(tasks)),
                  who="преподаватель", handler=handler)
        import urllib.parse as _up
        handler.send_response(200)
        handler.send_header("Content-Type", "application/zip")
        handler.send_header(
            "Content-Disposition",
            "attachment; filename*=UTF-8''" + _up.quote(fname))
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)
        return handler._SENT

    ctx.log("загружен: офлайн-сдача")


def _pending_form(ctx, batch_id, items):
    """Форма ручного выбора студента для нераспознанных работ."""
    blocks = []
    for it in items:
        opts = ['<option value="">— пропустить —</option>']
        for s in _course_students(ctx, it.get("курс", "")):
            bits = [s.get("fio", "?")]
            if s.get("group"):
                bits.append("гр. %s" % s["group"])
            opts.append('<option value="%s">%s</option>'
                        % (_e(s["id"]), _e(" · ".join(bits))))
        blocks.append(
            '<fieldset style="border:1px solid #dbe4ef;border-radius:10px;'
            'margin:10px 0"><legend>Файл «%s»</legend>'
            '<p>Задание: <b>%s</b> · ФИО в файле: <b>%s</b> · группа: %s</p>'
            '<p><label>Зачесть студенту: <select name="sel_%d">%s</select>'
            '</label></p></fieldset>'
            % (_e(it.get("файл", "")), _e(it.get("задание", "")),
               _e(it.get("fio", "?")), _e(it.get("группа", "?")),
               it.get("i", 0), "".join(opts)))
    return ('<h2>Нужен выбор студента (%d)</h2>'
            '<p class="hint">В этих файлах нет подписи и ФИО не распознано '
            'однозначно. Выберите, кому зачесть работу (или пропустите — '
            'файлы останутся на 24 часа).</p>'
            '<form method="post" action="/staff/offline/manual" '
            'class="staff-card">'
            '<input type="hidden" name="batch" value="%s">%s'
            '<p><button>✔ Зачесть выбранные</button></p></form>'
            '<form method="post" action="/staff/offline/manual" '
            'class="staff-card" style="margin-top:8px">'
            '<input type="hidden" name="batch" value="%s">'
            '<input type="hidden" name="drop" value="1">'
            '<p><button class="btn-sm">🗑 Отменить нераспознанные</button></p>'
            '</form>' % (len(items), _e(batch_id), "".join(blocks),
                         _e(batch_id)))
