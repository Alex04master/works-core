# -*- coding: utf-8 -*-
"""Модуль «Новое задание»: ⚠️ на курсах и занятиях, где появилось новое.

- На студенческих страницах (главная, курс, занятие, задание, «Мои
  задания») ссылки на курсы/занятия/задания, где появилось новое задание,
  помечаются ⚠️; на странице курса/занятия добавляется баннер с
  названиями нового.
- «Новое» = задание стало видно студенту позже, чем он последний раз
  открывал страницу этого курса (или занятия): задание создано, либо
  выдача изменена так, что оно добралось до его бригады/всех.
- Открыл страницу — метки снялись: страница курса снимает метки курса,
  страница занятия — занятия; страница задания тоже снимает метку
  своего занятия.
- Как работает: в <head> каждой страницы добавляется скрипт, он
  спрашивает /newmark/api (список нового для текущего студента),
  расставляет ⚠️ и баннер, затем POST /newmark/seen отмечает просмотр.
- Учёт «рождений» заданий — в данных модуля (kv): при первом запуске всё
  существующее считается уже виденным, дальше фиксируется время
  появления задания/выдачи.

Маршруты: GET /newmark/api (JSON), POST /newmark/seen. Доступ —
студент; преподавателю и гостям модуль ничего не показывает.
"""
import json
import threading
import time

_PURGE_DAYS = 90          # сколько хранить «рождения» и просмотры

_lock = threading.Lock()  # kv-файлы читаем-пишем под замком

# Скрипт для <head>. Плейсхолдеры __WC_C__/__WC_LESSON__ заменяются на
# JSON-строки с id текущего курса/занятия ("" если страницы без них).
# seen шлётся ПОСЛЕ расстановки меток: сервер считает «новое» на момент
# этого запроса, так что метки за один показ гарантированы.
_HEAD_JS = """<script>
(function(){
 try{
  var C=__WC_C__,L=__WC_LESSON__;
  if(document.body&&document.body.classList.contains("staff"))return;
  var p=location.pathname;
  if(p==="/board"||p.indexOf("/board/")===0||
     p==="/plan"||p.indexOf("/plan/")===0)return;
  function esc(s){var d=document.createElement("div");
   d.textContent=String(s==null?"":s);return d.innerHTML}
  function markAll(base,ids){
   if(!ids||!ids.length)return;
   var re=new RegExp("^"+base+"(\\\\?|$)");
   ids.forEach(function(id){
    document.querySelectorAll('a[href^="'+base+id+'"]').forEach(function(a){
     if(a.dataset.wcNew)return;
     var h=a.getAttribute("href")||"";
     if(re.test(h)){a.dataset.wcNew="1";
      a.insertAdjacentHTML("beforeend"," ⚠️");
      a.title="Есть новое задание";}
    });
   });
  }
  fetch("/newmark/api",{cache:"no-store"})
  .then(function(r){return r.ok?r.json():null})
  .then(function(j){
   if(!j)return;
   markAll("/course/",Object.keys(j["курсы"]||{}));
   markAll("/lesson/",Object.keys(j["занятия"]||{}));
   markAll("/task/",(j["задания"]||[]).map(function(t){return t.id}));
   var cur=[];
   if(C&&j["курсы"]&&j["курсы"][C])cur=j["курсы"][C];
   if(L&&j["занятия"]&&j["занятия"][L])cur=j["занятия"][L];
   if(cur.length){
    var m=document.getElementById("main")||document.body;
    var d=document.createElement("div");d.className="notice wc-newmark";
    d.innerHTML="⚠️ Появилось новое задание: "+
     cur.map(function(t){return "<b>"+esc(t)+"</b>"}).join(" · ");
    m.insertBefore(d,m.firstChild);
   }
   var q=[];
   if(C)q.push("курс="+encodeURIComponent(C));
   if(L)q.push("занятие="+encodeURIComponent(L));
   if(q.length)fetch("/newmark/seen",{method:"POST",
    headers:{"Content-Type":"application/x-www-form-urlencoded"},
    body:q.join("&")});
  }).catch(function(){});
 }catch(e){}
})();
</script>"""


def _audience_keys(task):
    """Кому видно задание (ключи аудитории): '*' — всем, список бригад,
    [] — ждёт выдачи (сценарное, студентам не видно)."""
    issued = task.get("выдано")
    if issued is None:
        if (task.get("настройки") or {}).get("план"):
            return []
        return ["*"]
    if not issued:
        return ["*"]
    return sorted({str(b).strip() for b in issued if str(b).strip()})


def _sync(ctx):
    """Обновить журнал «рождений»: время, когда задание стало доступно
    каждой аудитории. Первая синхронизация — всё существующее уже
    «виденное» (не сыпем ⚠️ на то, что было до установки модуля)."""
    db = ctx._core.store.db
    now = time.time()
    births = ctx.kv_load("рождения", {}) or {}
    init = ctx.kv_load("готово", False)
    alive = set()
    changed = False
    for t in db.get("задания") or []:
        tid, lid = t.get("id", ""), t.get("lesson", "")
        for aud in _audience_keys(t):
            k = "%s@%s|%s" % (tid, lid, aud)
            alive.add(k)
            if k not in births:
                births[k] = 0 if not init else now
                changed = True
    lim = now - _PURGE_DAYS * 86400
    cleaned = {k: v for k, v in births.items()
               if (k in alive and v >= lim) or v == 0}
    if changed or len(cleaned) != len(births):
        ctx.kv_save("рождения", cleaned)
    if not init:
        ctx.kv_save("готово", True)


def _new_for(ctx, sid):
    """Что нового для студента: {курсы: {cid: [названия]},
    занятия: {lid: [названия]}, задания: [{id, название, …}]}."""
    stu = ctx.get_student(sid) or {}
    births = ctx.kv_load("рождения", {}) or {}
    seen = (ctx.kv_load("просмотрено", {}) or {}).get(sid) or {}
    brig_all = (stu.get("бригада") or "").strip()
    out = {"курсы": {}, "занятия": {}, "задания": []}
    for c in ctx.list_courses():
        cid = c["id"]
        if not ctx.can_access(cid, sid):
            continue
        brig = brig_all if ctx.brigades_enabled(cid) else ""
        for l in ctx.list_lessons(cid):
            lid = l["id"]
            for t in ctx.list_tasks(lid):
                if not ctx.task_for_brigade(t, brig):
                    continue
                b = births.get("%s@%s|%s" % (t.get("id", ""), lid,
                                             brig or "*"), 0)
                if not b:
                    continue
                title = t.get("title", "")
                if b > (seen.get("c:" + cid) or 0):
                    out["курсы"].setdefault(cid, []).append(title)
                if b > (seen.get("l:" + lid) or 0):
                    out["занятия"].setdefault(lid, []).append(title)
                    out["задания"].append({"id": t.get("id", ""),
                                           "название": title,
                                           "занятие": lid, "курс": cid})
    return out


def register(ctx):
    @ctx.add_route("GET", "/newmark/api", access="student")
    def api(handler, params):
        sid = handler._student()
        with _lock:
            _sync(ctx)
        if not sid:
            handler._send_json(200, {"курсы": {}, "занятия": {},
                                     "задания": []})
            return handler._SENT
        handler._send_json(200, _new_for(ctx, sid))
        return handler._SENT

    @ctx.add_route("POST", "/newmark/seen", access="student")
    def seen(handler, params):
        data = handler._parse_post()
        sid = handler._student()
        cid = str(data.get("курс") or "").strip()
        lid = str(data.get("занятие") or "").strip()
        if sid and (cid or lid):
            now = time.time()
            with _lock:
                allseen = ctx.kv_load("просмотрено", {}) or {}
                mine = allseen.setdefault(sid, {})
                if cid:
                    mine["c:" + cid] = now
                if lid:
                    mine["l:" + lid] = now
                lim = now - _PURGE_DAYS * 86400
                allseen = {s: {k: v for k, v in d.items() if v >= lim}
                           for s, d in allseen.items()}
                allseen = {s: d for s, d in allseen.items() if d}
                ctx.kv_save("просмотрено", allseen)
        handler._send_json(200, {"ok": True})
        return handler._SENT

    # Скрипт в <head> всех страниц (свой на каждой: id курса/занятия)
    def _head(course=None, lesson=None, **kw):
        cid = course.get("id", "") if isinstance(course, dict) else ""
        lid = lesson.get("id", "") if isinstance(lesson, dict) else ""
        return (_HEAD_JS
                .replace("__WC_C__", json.dumps(cid, ensure_ascii=False))
                .replace("__WC_LESSON__", json.dumps(lid, ensure_ascii=False)))

    ctx.on("page.head", _head)

    ctx.log("загружен: newmark (⚠️ новое задание, /newmark/api)")
