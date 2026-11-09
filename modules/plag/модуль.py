# -*- coding: utf-8 -*-
"""Модуль «Антиплагиат и нейро-контроль».

При КАЖДОЙ сдаче (обычной и офлайн) — до того, как преподаватель её
увидит — работа проверяется:

1. Антиплагиат: текст ответов сравнивается со ВСЕМИ уже сданными
   работами этого задания (шинглы слов + Жаккар). Считаются
   совпадающие фрагменты (показываются преподавателю) и одинаковые
   приложенные файлы (SHA-256 → 100%).
2. Нейро-контроль: эвристическая оценка «нейросетевого» текста —
   частота штампов-клише, однообразие длины предложений (низкая
   «взрывность»), бедность словаря. Оценка ЭВРИСТИЧЕСКАЯ — работает
   офлайн, без нейросетей, и не является доказательством.

Результаты пишутся в версию сдачи (ver["контроль"]) и показываются
преподавателю: на странице сдачи (/staff/sub/...) карточкой и на
панели /plag (сводка по заданию + пары похожих работ).

Все проверки — только для преподавателя; студенты результатов не видят.
"""
import hashlib
import html as _html
import json
import re
import urllib.parse
from datetime import datetime

SH_K = 3            # размер шингла (слов)
MIN_WORDS = 25      # короче — не сравниваем
FRAG_MIN = 8        # слов в показываемом совпадающем фрагменте
TOP_MATCHES = 3     # сколько совпадений сохраняем в версии
MAX_PER_TASK = 150  # отпечатков на задание (последние)
MIN_SENT = 6        # предложений для оценки однообразия
MIN_AI_WORDS = 40   # короче — нейро-оценка не считается


def _e(v):
    return _html.escape(str(v) if v is not None else "", quote=True)


AI_MARKERS = [
    "таким образом", "следует отметить", "важно отметить",
    "необходимо отметить", "стоит отметить", "в заключение",
    "подводя итог", "в современном мире", "в наше время",
    "играет важную роль", "играет ключевую роль",
    "имеет важное значение", "является одним из", "является важным",
    "особое внимание", "не вызывает сомнений", "как известно",
    "с одной стороны", "с другой стороны", "более того", "кроме того",
    "в связи с этим", "в свою очередь", "необходимо подчеркнуть",
    "представляет собой", "осуществляться", "проведён анализ",
    "проведен анализ", "анализ показывает", "результаты показывают",
    "существует множество", "широко используется",
    "на сегодняшний день", "в настоящее время", "целесообразно",
    "в рамках данной", "данная работа", "рассмотрим подробнее",
    "перейдём к рассмотрению", "не менее важным", "нельзя не отметить",
]


def _tok(text):
    return [w for w in re.split(r"\W+", str(text or "").lower()) if w]


def _shingles(words, k=SH_K):
    if len(words) < MIN_WORDS:
        return set()
    return {int.from_bytes(hashlib.blake2b(
        " ".join(words[i:i + k]).encode("utf-8"),
        digest_size=8).digest(), "big") for i in range(len(words) - k + 1)}


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _fragments(a, b, k=FRAG_MIN):
    """Максимальные общие последовательности слов (>= k), топ-3."""
    if len(a) < k or len(b) < k:
        return []
    bidx = {}
    for i in range(len(b) - k + 1):
        bidx.setdefault(tuple(b[i:i + k]), []).append(i)
    out = []
    i = 0
    while i <= len(a) - k:
        key = tuple(a[i:i + k])
        if key in bidx:
            best = None
            for j in bidx[key]:
                L = k
                while (i + L < len(a) and j + L < len(b)
                       and a[i + L] == b[j + L]):
                    L += 1
                if best is None or L > best[2]:
                    best = (i, j, L)
            i2, _, L = best
            out.append(" ".join(a[i2:i2 + L])[:220])
            i = i2 + L
        else:
            i += 1
    out.sort(key=len, reverse=True)
    return out[:3]


def _sent_lens(text):
    parts = re.split(r"[.!?]+", str(text or ""))
    return [len(_tok(p)) for p in parts if _tok(p)]


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _ai_check(texts):
    """Эвристическая нейро-оценка текста. None — слишком короткий."""
    text = " ".join(texts)
    words = _tok(text)
    if len(words) < MIN_AI_WORDS:
        return None
    low = text.lower()
    markers = []
    for m in AI_MARKERS:
        n = low.count(m)
        if n:
            markers.append({"штамп": m, "раз": n})
    hits = sum(m["раз"] for m in markers)
    density = hits * 1000.0 / len(words)
    stamp = _clamp(density / 12.0)
    sl = _sent_lens(text)
    if len(sl) >= MIN_SENT:
        mean = sum(sl) / len(sl)
        var = sum((x - mean) ** 2 for x in sl) / len(sl)
        cv = (var ** 0.5) / mean if mean else 0
        uniform = _clamp(1 - cv / 0.65)
    else:
        uniform = 0.0
    ttr = len(set(words)) / len(words)
    poor = _clamp(1 - ttr / 0.6)
    score = int(round(100 * (0.55 * stamp + 0.25 * uniform + 0.20 * poor)))
    return {"оценка": score,
            "штампы": {"всего": hits,
                       "на_1000_слов": round(density, 1),
                       "список": markers[:10]},
            "предложений": len(sl),
            "однообразие": int(round(uniform * 100)),
            "словарь": int(round((1 - poor) * 100)),
            "слов": len(words)}


def _texts_of(task, answers):
    types = {fd.get("ключ"): fd.get("тип")
             for fd in (task.get("форма") or [])}
    return [str(v) for k, v in (answers or {}).items()
            if isinstance(v, str) and types.get(k) in ("text", "textarea")]


def _file_hashes(ctx, ver):
    out = {}
    base = ctx._core.store.subs
    for k, meta in (ver.get("files") or {}).items():
        rel = str((meta or {}).get("файл") or "")
        p = base
        for part in rel.split("/"):
            p = os.path.join(p, part) if rel else ""
        if not rel:
            continue
        try:
            with open(p, "rb") as f:
                out[k] = hashlib.sha256(f.read()).hexdigest()
        except OSError:
            pass
    return out


# os.path нужен _file_hashes
import os  # noqa: E402


def _badge(pct):
    if pct >= 60:
        return "mx-rej"
    if pct >= 30:
        return "mx-fix"
    return "mx-ok"


def _check(ctx, task, sub, ver):
    tid = task.get("id", "")
    key = sub.get("key", "")
    sid = sub.get("student", "")
    texts = _texts_of(task, ver.get("answers") or {})
    joined = " ".join(texts)
    words = _tok(joined)
    fp = _shingles(words) if len(words) >= MIN_WORDS else set()
    fhashes = _file_hashes(ctx, ver)

    kv = ctx.kv_load("fp", {})
    store = kv.get(tid) or []
    matches = []
    for e in store:
        if e.get("sid") == sid:
            continue
        pct = _jaccard(fp, set(e.get("шиглы") or []))
        frag = _fragments(words, e.get("слова") or []) if pct >= 0.15 else []
        file_hit = ""
        for hk, hh in fhashes.items():
            if hh in (e.get("файлы") or {}).values():
                file_hit = hk
        if file_hit and pct < 1.0:
            pct = 1.0
        if pct >= 0.15 or file_hit:
            stu = ctx.get_student(e.get("sid") or "") or {}
            matches.append({
                "sid": e.get("sid", ""), "кто": stu.get("fio", "?"),
                "вер": e.get("вер", 1), "процент": int(round(pct * 100)),
                "файл": file_hit,
                "фрагменты": frag if pct >= 0.3 else []})
    matches.sort(key=lambda m: m["процент"], reverse=True)
    matches = matches[:TOP_MATCHES]

    store.append({"key": key, "sid": sid, "вер": ver.get("n", 1),
                  "шиглы": sorted(fp), "слова": words[:4000],
                  "файлы": fhashes,
                  "когда": datetime.now().isoformat(timespec="seconds")})
    kv[tid] = store[-MAX_PER_TASK:]
    ctx.kv_save("fp", kv)

    anti = {"процент": matches[0]["процент"] if matches else 0,
            "совпадения": matches}
    neuro = _ai_check(texts)
    ver["контроль"] = {"антиплагиат": anti, "нейро": neuro,
                       "когда": datetime.now().isoformat(timespec="seconds")}
    # флаг в статус сдачи для панели/очереди
    if matches and matches[0]["процент"] >= 60:
        sub["флаг"] = "антиплагиат"
    elif neuro and neuro["оценка"] >= 60:
        sub["флаг"] = "нейро"
    ctx._core.store.save()
    return ver["контроль"]


def _card_html(ctl):
    """Карточка для страницы сдачи (HTML, экранирован)."""
    anti = ctl.get("антиплагиат") or {}
    pct = anti.get("процент", 0)
    neuro = ctl.get("нейро")
    rows = ""
    for m in (anti.get("совпадения") or [])[:3]:
        frags = ""
        for f in (m.get("фрагменты") or [])[:2]:
            frags += ('<div class="hint">«%s»</div>' % _e(f))
        rows += (
            '<tr><td>%s</td><td><span class="%s">%d%%</span></td>'
            '<td>v%d%s%s</td></tr>'
        ) % (_e(m.get("кто", "?")), _badge(m.get("процент", 0)),
             m.get("процент", 0), m.get("вер", 1),
             ' · <b>файл одинаков</b>' if m.get("файл") else "",
             frags)
    tbl = ('<table class="staff-table"><tr><th>Совпадает с работой</th>'
           '<th>Сходство</th><th>Версия</th></tr>%s</table>') % rows \
        if rows else '<p class="hint">Совпадений с другими работами ' \
                     'задания не найдено.</p>'
    neuro_html = ""
    if neuro:
        ms = ", ".join("%s (%d)" % (m["штамп"], m["раз"])
                       for m in (neuro.get("штампы") or {})
                       .get("список", [])[:6])
        neuro_html = (
            '<p><b>🤖 Нейро-оценка (эвристика, не доказательство):</b> '
            '<span class="%s">%d%%</span> · штампов: %s на 1000 слов · '
            'однообразие предложений: %d%% · словарь: %d%%</p>'
            '<p class="hint">Штампы: %s</p>'
        ) % (_badge(neuro["оценка"]), neuro["оценка"],
             neuro["штампы"]["на_1000_слов"], neuro["однообразие"],
             neuro["словарь"], _e(ms) or "—")
    else:
        neuro_html = ('<p class="hint">🤖 Нейро-оценка: текст короче %d '
                      'слов — не оценивался.</p>' % MIN_AI_WORDS)
    return (
        '<div class="staff-card"><h2>🛡 Контроль работы '
        '<span class="hint">(до проверки, %s)</span></h2>'
        '<p><b>Антиплагиат:</b> максимум сходства с другими работами '
        'задания — <span class="%s">%d%%</span></p>%s%s</div>'
    ) % (_e(ctl.get("когда", ""))[:16], _badge(pct), pct, tbl, neuro_html)


INJECT_JS = """<script>
document.addEventListener('DOMContentLoaded',function(){
 try{
  var m=location.pathname.match(/^\\/staff\\/sub\\/([^\\/?]+)/);
  if(!m)return;
  fetch('/plag/info/'+m[1]).then(function(r){return r.json()})
   .then(function(d){
    if(!d||!d.есть)return;
    var st=document.querySelector('.sub-status');
    if(!st)return;
    var dv=document.createElement('div');dv.innerHTML=d.html;
    while(dv.firstChild)st.parentNode.insertBefore(dv.firstChild,
                                                   st.nextSibling);
   }).catch(function(){});
 }catch(e){}
});</script>"""


def register(ctx):
    # ── Проверка при каждой сдаче ────────────────────────────────────
    def _on_submit(task=None, student=None, sub=None, version=None, **kw):
        try:
            if task and sub and version:
                _check(ctx, task, sub, version)
        except Exception as ex:
            ctx.log("антиплагиат: сбой проверки (%s)" % ex)

    ctx.on("submit.after", _on_submit)

    # ── Карточка на странице сдачи (JS-инъекция) ─────────────────────
    def _head(course=None, lesson=None, **kw):
        return INJECT_JS

    ctx.on("page.head", _head)

    # ── Карточка на главной панели ───────────────────────────────────
    def _home_card(**kw):
        return (
            '<details><summary>🛡 Антиплагиат</summary>'
            '<div class="staff-card">'
            '<p class="hint">Сводка контроля работ: сходство с уже '
            'сданными работами задания (шинглы слов) и эвристическая '
            'нейро-оценка текста. Проверка выполняется автоматически '
            'при каждой сдаче, до вердикта.</p>'
            '<p><a class="btn" href="/plag">🛡 Открыть контроль</a></p>'
            '</div></details>')

    ctx.on("staff.home_cards", _home_card)

    # ── Данные для страницы сдачи ────────────────────────────────────
    @ctx.add_route("GET", "/plag/info/", access="staff")
    def plag_info(handler, params):
        key = urllib.parse.unquote((params.get("_parts") or [""])[0])
        if "__" not in key:
            return handler._send_json(200, {"есть": False})
        tid, sid = key.split("__", 1)
        sub = ctx._core.sub(tid, sid)
        ver = (sub or {}).get("versions", [{}])[-1] if sub else {}
        ctl = ver.get("контроль")
        if not ctl:
            return handler._send_json(200, {"есть": False})
        return handler._send_json(200, {"есть": True, "версия":
                                        ver.get("n", 1), "html": _card_html(ctl)})

    # ── Панель ───────────────────────────────────────────────────────
    def _task_rows(tid):
        kv = ctx.kv_load("fp", {})
        entries = {e["key"]: e for e in (kv.get(tid) or [])}
        rows = ""
        for s in ctx.list_submissions(task_id=tid):
            vers = s.get("versions") or []
            if not vers:
                continue
            stu = ctx.get_student(s.get("student", "")) or {}
            for ver in vers:
                ctl = (ver.get("контроль") or {})
                anti = ctl.get("антиплагиат") or {}
                neuro = ctl.get("нейро")
                who = _e(stu.get("fio", "?"))
                if s.get("бригада"):
                    who += " 👥"
                top = (anti.get("совпадения") or [{}])[0]
                a_pct = anti.get("процент", 0)
                n_score = (neuro or {}).get("оценка")
                rows += (
                    '<tr><td>%s</td><td>v%d</td><td>%s</td>'
                    '<td><span class="%s">%d%%</span></td>'
                    '<td>%s</td><td>%s</td>'
                    '<td><a class="btn btn-sm" href="/staff/sub/%s/v%d">'
                    'Открыть</a></td></tr>'
                ) % (who, ver.get("n", 1), _e(ver.get("time", ""))[:16],
                     _badge(a_pct), a_pct,
                     ('%s (%d%%)' % (_e(top.get("кто", "—")),
                                     top.get("процент", 0)))
                     if top else "—",
                     ('<span class="%s">%d%%</span>' % (
                         _badge(n_score), n_score)) if n_score is not None
                     else '—',
                     _e(s.get("key", "")), ver.get("n", 1))
        return rows

    @ctx.add_route("GET", "/plag", access="staff")
    def plag_home(handler, params):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
        sel = (qs.get("task") or [""])[0]
        opts = ""
        counts = {}
        kv = ctx.kv_load("fp", {})
        for t in ctx.list_tasks():
            n = sum(1 for s in ctx.list_submissions(task_id=t["id"])
                    if any((v.get("контроль") or {})
                           for v in (s.get("versions") or [])))
            if n:
                counts[t["id"]] = n
        for t in ctx.list_tasks():
            if not counts.get(t["id"]):
                continue
            opts += ('<option value="%s"%s>%s (%d сд.)</option>'
                     % (_e(t["id"]), " selected" if t["id"] == sel else "",
                        _e(t.get("title", "")), counts[t["id"]]))
        if not opts:
            body = ('<p><a href="/staff">Все курсы</a></p>'
                    '<div class="staff-card"><h2>🛡 Антиплагиат и '
                    'нейро-контроль</h2><p class="hint">Проверенных работ '
                    'пока нет. Контроль выполняется автоматически при '
                    'каждой сдаче.</p></div>')
            return ctx.render_page("🛡 Антиплагиат", body, staff=True)
        sel_task = ctx.get_task(sel) if sel else None
        table = ""
        if sel_task:
            table = (
                '<div class="staff-card"><h2>%s</h2>'
                '<table class="staff-table"><tr><th>Студент</th><th>Вер.</th>'
                '<th>Сдано</th><th>Антиплагиат</th><th>Топ-совпадение</th>'
                '<th>Нейро</th><th></th></tr>%s</table></div>'
            ) % (_e(sel_task.get("title", "")), _task_rows(sel))
        body = (
            '<p><a href="/staff">Все курсы</a></p>'
            '<div class="staff-card"><h2>🛡 Антиплагиат и нейро-контроль</h2>'
            '<p class="hint">Антиплагиат — сходство текста с уже сданными '
            'работами того же задания (шинглы слов, Жаккар) + одинаковые '
            'файлы. Нейро-оценка — эвристика (штампы-клише, однообразие '
            'предложений, словарь), работает офлайн и не является '
            'доказательством. Проверка — при каждой сдаче, до вердикта.</p>'
            '<form method="get" action="/plag">'
            '<p><label>Задание: <select name="task">%s</select></label> '
            '<button>Показать</button></p></form></div>'
        ) % opts
        body += table
        return ctx.render_page("🛡 Антиплагиат", body, staff=True)

    ctx.log("загружен: антиплагиат и нейро-контроль (/plag)")
