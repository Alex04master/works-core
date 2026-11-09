# -*- coding: utf-8 -*-
"""Симулятор Arduino (velxio) — встраивание прямо в страницу задания.

CI: правки этого файла применяются к работающему серверу без перезапуска
(ci.py watch → POST /_reload). Правка докстринга — безобидный маркер
такого деплоя.

Что делает:
  * на странице студенческого задания (событие ядра «task.panel») рисует
    панель с iframe на velxio — студент собирает схему, пишет и
    компилирует скетч, не покидая СДО; кнопка «↗ Открыть симулятор»
    открывает его в новой вкладке, кнопка «📥 Импортировать схему в
    отчёт» через postMessage-мост (патч main.tsx velxio) забирает
    текущий проект и прикрепляет файлом схемы к файловому полю формы;
  * в панели преподавателя на /staff/task/<id> — карточка «Симулятор»:
    привязать URL/путь к заданию или отвязать (событие «staff.task_cards»,
    маршрут POST /staff/sim_set).

Адрес симулятора. Путь из задания без http:// дополняется базой, которая
строится из хоста запроса («путь к симулятору — хост сервера»): СДО открыт
на http://192.168.1.113:8090 → симулятор ищется на http://192.168.1.113:<порт>.
Порт задаётся в modules/sim/модуль.json («порт», по умолчанию 5173);
явный адрес («url») имеет приоритет. Абсолютные URL в задании — как есть.

Где velxio: https://github.com/davidmonterocrespo24/velxio (AGPLv3).
Локальный запуск (Uno достаточно):
    E:/AI/velxio/start-velxio.bat   → фронтенд :5173, бэкенд :8001
"""
import html


def register(ctx):
    def _e(v):
        return html.escape(str(v if v is not None else ""), quote=True)

    def _base(handler=None):
        explicit = str(ctx.settings.get("url") or "").strip().rstrip("/")
        if explicit:
            return explicit
        port = str(ctx.settings.get("порт") or 5173).strip() or "5173"
        host = ""
        if handler is not None:
            try:
                host = handler.headers.get("Host") or ""
            except Exception:
                host = ""
        # Host: "192.168.1.113:8090" → "192.168.1.113" (первый из списка,
        # без порта works-core; IPv6-литералы деградируют в fallback)
        host = host.split(",")[0].strip().split(":")[0].strip()
        if not host:
            host = "127.0.0.1"
        return "http://" + host + ":" + port

    def _resolve(task, handler=None):
        """Симулятор-URL задания: абсолютный — как есть, путь — с базой."""
        raw = str((task or {}).get("симулятор", "") or "").strip()
        if not raw:
            return ""
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw
        path = raw.lstrip("/")
        return _base(handler) + ("/" + path if path else "")

    # Горячий фикс виджета файлов (см. page_fix ниже).
    _FIX_JS = '''<script>
/* Файлы в блоке загрузки «выбирались», но не прикреплялись: старый
   обработчик change стирал их (inp.value='' после sync). Чиним со
   стороны модуля: при захвате события запоминаем выбор, при всплытии
   возвращаем в поле. После обновления ядра это no-op. */
(function(){
  function dnd(e){return e.target&&e.target.classList&&
    e.target.classList.contains('dnd-inp')?e.target:null}
  document.addEventListener('change',function(e){
    var inp=dnd(e);
    if(inp&&inp.files&&inp.files.length)
      inp._wc_keep=Array.prototype.slice.call(inp.files);
  },true);
  document.addEventListener('change',function(e){
    var inp=dnd(e);
    if(!inp)return;
    var keep=inp._wc_keep||[];
    inp._wc_keep=null;
    if(keep.length&&(!inp.files||!inp.files.length)){
      try{var dt=new DataTransfer();
        for(var i=0;i<keep.length;i++)dt.items.add(keep[i]);
        inp.files=dt.files;
      }catch(err){}
    }
  },false);
})();
</script>'''
    # ── Студенческая страница задания: панель с симулятором ─────────
    def task_panel(task=None, sub=None, handler=None, **kw):
        url = _resolve(task, handler)
        if not url:
            return ""
        u = _e(url)
        # Куда импортировать схему: первое файловое поле формы отчёта
        fkey = ""
        for fd in (task or {}).get("форма", []) or []:
            if fd.get("тип") in ("file", "firmware"):
                fkey = str(fd.get("ключ", "") or "")
                break
        sid = ''
        try:
            sid = handler._student() or ''
        except Exception:
            sid = ''
        return _panel_html(u, fkey, sid, str((task or {}).get("id", "") or ""))

    ctx.on("task.panel", task_panel)

    # Горячий фикс виджета файлов: обработчик change в ядре стирал
    # выбранные файлы (inp.value='' ПОСЛЕ sync) — чип на экране есть,
    # а поле пустое и файл не уходит с формой. Здесь чиним со стороны:
    # при захвате события запоминаем выбор, при всплытии возвращаем его
    # в поле. После обновления ядра фиксированным обработчиком — no-op.
    def page_fix(**kw):
        return _FIX_JS

    ctx.on("page.head", page_fix)
    # HTML панели + JS импорта схемы (кнопки: открыть в новой вкладке,
    # забрать схему из iframe в поле отчёта). velxio анонсирует себя
    # {wc:'velxio-ready'}, панель отвечает {wc:'velxio-task',task:<id>} —
    # симулятор привязывает к заданию свой черновик (работа студента
    # переживает перезагрузку страницы при отправке формы); на
    # {wc:'velxio-export'} отвечает снимком проекта (патч main.tsx).
    _PANEL_JS = '''<script>
(function(){
  var btn=document.getElementById('wc-sim-import'),
      st=document.getElementById('wc-sim-status'),
      fr=document.querySelector('#wc-sim iframe');
  if(!btn||!st||!fr)return;
  var KEY=__KEY__, U=__SID__, TID=__TID__, pending='';
  var DKEY='wc-sim-draft_'+U+location.pathname,
      // старый вариант ключа (sid был с кавычками) — для чтения
      DOLD='wc-sim-draft_"'+U+location.pathname;

  function target(){
    var inp=document.getElementById('dzinp_'+KEY);
    if(!inp)inp=document.querySelector('.task-form input[type=file]');
    return inp;
  }
  function keep(name,txt){
    try{localStorage.setItem(DKEY,JSON.stringify({n:name,d:txt}))}catch(e){}
  }
  function drop(){
    try{localStorage.removeItem(DKEY)}catch(e){}
    try{localStorage.removeItem(DOLD)}catch(e){}
  }
  // Скажем симулятору, какое задание открыто — он привяжет к нему
  // свой черновик (вся работа студента в симуляторе переживает
  // перезагрузку страницы при отправке формы).
  function tellTask(win){
    if(!TID||!win)return;
    try{win.postMessage({wc:'velxio-task',task:TID},'*');}catch(e){}
  }
  function attach(name,txt){
    var file=new File([txt],name,{type:'application/json'});
    var inp=target();
    if(!inp){st.textContent=
      '❌ В форме отчёта нет поля для файла схемы — попросите '+
      'преподавателя добавить поле «файл» в форму задания';return false;}
    var dt=new DataTransfer();
    dt.items.add(file);
    inp.files=dt.files;
    inp.dispatchEvent(new Event('change',{bubbles:true}));
    return inp.files.length>0;
  }
  window.addEventListener('message',function(e){
    var d=e.data||{};
    if(d.wc==='velxio-ready'){
      // Симулятор загрузился (в том числе заново — после отправки
      // формы или F5) — называем задание, он вернёт себе черновик.
      tellTask(e.source||fr.contentWindow);return;}
    if(d.wc!=='velxio-export-data')return;
    if(pending&&d.id!==pending)return;
    var p=d.payload||{};
    var empty=!(p.boards&&p.boards.length)&&
      !(p.components&&p.components.length)&&
      !(p.wires&&p.wires.length)&&
      !(p.fileGroups&&Object.keys(p.fileGroups).length);
    if(!d.error&&empty){
      // Снимок пришёл пустым — симулятор ещё не дорисовал стартер
      // (первая загрузка iframe). Ретраи продолжаются, ничего не
      // прикрепляем — иначе затёрли бы черновик пустой схемой.
      st.textContent='⏳ Симулятор ещё загружается…';
      return;
    }
    pending='';
    if(d.error){st.textContent='❌ Симулятор: '+d.error;return;}
    try{
      var txt=JSON.stringify(d.payload,null,2);
      var name='схема-симулятора.vlx';
      if(attach(name,txt)){
        keep(name,txt);
        st.textContent='✅ Схема прикреплена к отчёту: '+name+
          ' — сохранена в черновике, не потеряется при обновлении';
      } else st.textContent='⚠️ Файл не удержался в поле отчёта — '+
        'обновите страницу и повторите импорт';
    }catch(err){st.textContent='❌ Не удалось прикрепить: '+err;}  });
  btn.addEventListener('click',function(){
    var myId='wc'+(new Date()).getTime(), tries=0;
    pending=myId;
    st.textContent='⏳ Забираю схему из симулятора…';
    tellTask(fr.contentWindow);
    // Первая загрузка iframe (React, monaco) бывает долгой, поэтому
    // спрашиваем снимок повторно раз в секунду, пока не ответит.
    function poke(){
      if(pending!==myId)return;
      try{fr.contentWindow.postMessage({wc:'velxio-export',id:myId},'*');}
      catch(err){pending='';
        st.textContent='❌ Симулятор недоступен ('+err+
        '). Откройте его кнопкой выше.';return;}
      if(++tries>30){pending='';
        st.textContent='❌ Симулятор не отвечает. Подождите, пока он '+
        'загрузится, или откройте его в отдельной вкладке — и повторите.';
        return;}
      setTimeout(poke,1000);
    }
    poke();
  });
  // Восстановление схемы после обновления страницы / ошибки валидации:
  // файл нельзя запомнить на сервере, поэтому держим его в localStorage.
  document.addEventListener('DOMContentLoaded',function(){
    tellTask(fr.contentWindow);
    var raw=null;
    try{raw=localStorage.getItem(DKEY)}catch(e){}
    if(!raw){try{raw=localStorage.getItem(DOLD)}catch(e){}}
    if(!raw)return;
    try{
      var o=JSON.parse(raw);
      if(attach(o.n||'схема-симулятора.vlx',o.d))
        st.textContent='✅ Схема восстановлена из черновика: '+(o.n||'')+
          ' — можно отправлять работу';
      else st.textContent='⚠️ Черновик не удержался в поле — обновите '+
        'страницу и повторите импорт схемы';
    }catch(e){drop();}
  });
  // Студент убрал файл крестиком из поля — черновик схемы тоже забыть
  document.addEventListener('click',function(e){
    var b=e.target;
    if(!b||!b.classList||!b.classList.contains('dnd-x'))return;
    var inp=target();if(!inp)return;
    var list=document.getElementById('dzlist_'+KEY);
    if(list&&list.contains(b))drop();
    else{var dz=inp.closest?inp.closest('.dnd'):null;
      if(dz&&dz.contains(b))drop();}
  });
})();
</script>'''

    def _panel_html(url_esc, fkey, sid='', tid=''):
        import json as _json
        js = (_PANEL_JS
              .replace("__KEY__", _json.dumps(fkey))
              .replace("__SID__", _json.dumps(sid))
              .replace("__TID__", _json.dumps(tid)))
        return (
            '<div class="task-desc" id="wc-sim">'
            '<style>.wc-sim-btns{display:flex;gap:10px;flex-wrap:wrap;'
            'align-items:center;margin:10px 0}.wc-sim-btns .btn{display:'
            'inline-block;text-decoration:none;color:#fff}</style>'
            '<h2>🔌 Симулятор Arduino</h2>'
            '<p class="hint">Соберите схему, напишите скетч и запустите ▶ — '
            'плата работает прямо здесь. Когда схема готова, нажмите '
            '<b>«📥 Импортировать схему»</b> — файл схемы прикрепится к '
            'отчёту ниже. Не забудьте скриншот работающей платы.</p>'
            '<div class="wc-sim-btns">'
            '<a class="btn" href="%s" target="_blank" rel="noopener" '
            'style="text-decoration:none">↗ Открыть симулятор</a>'
            '<button type="button" class="btn" id="wc-sim-import">'
            '📥 Импортировать схему в отчёт</button>'
            '<span id="wc-sim-status" class="hint"></span>'
            '</div>'
            '<iframe src="%s" style="width:100%%;height:900px;'
            'border:1px solid #e0e0e0;border-radius:12px" '
            'title="Симулятор Arduino (velxio)"></iframe>'
            '%s</div>'
        ) % (url_esc, url_esc, js)

    # ── Панель преподавателя: карточка на /staff/task/<id> ────────────
    def staff_card(task=None, handler=None, **kw):
        tid = (task or {}).get("id", "")
        cur = str((task or {}).get("симулятор", "") or "").strip()
        if cur:
            state = ('<p class="hint">Привязан: <code>%s</code></p>' % _e(cur))
        else:
            state = ('<p class="hint">Не привязан — панель на странице '
                     'задания скрыта.</p>')
        return (
            '<form method="post" action="/staff/sim_set" class="staff-card">'
            '<h2>🔌 Симулятор</h2>%s'
            '<input type="hidden" name="task" value="%s">'
            '<p><label>URL или путь (например /example/blink-led — '
            'старт Uno с кодом, или /editor — пустой проект): '
            '<input type="text" name="url" value="%s" '
            'placeholder="/example/blink-led" '
            'style="width:100%%"></label></p>'
            '<p><button class="btn-sm">Сохранить</button> '
            '<a class="btn-sm btn-secondary" href="%s" target="_blank" '
            'rel="noopener">Открыть</a></p>'
            '<p class="hint">База для студентов: <code>%s</code> — хост, '
            'с которого открыт СДО, + порт из настроек модуля '
            '(modules/sim/модуль.json). Пустое поле = отвязать.</p>'
            '</form>'
        ) % (state, _e(tid), _e(cur), _e(_resolve(task, handler) or _base(handler)),
             _e(_base(handler)))

    ctx.on("staff.task_cards", staff_card)

    # ── Сохранение привязки ───────────────────────────────────────────
    @ctx.add_route("POST", "/staff/sim_set", access="staff")
    def sim_set(handler, params):
        data = handler._parse_post()
        tid = (data.get("task") or "").strip()
        url = (data.get("url") or "").strip()
        task = ctx.get_task(tid)
        if not task:
            handler._redirect("/staff")
            return handler._SENT
        if url:
            task["симулятор"] = url
            ctx.audit("симулятор привязан к заданию",
                      {"задание": tid, "url": url}, handler=handler)
        else:
            task.pop("симулятор", None)
            ctx.audit("симулятор отвязан от задания", {"задание": tid},
                      handler=handler)
        ctx.save()
        handler._redirect("/staff/task/%s" % _e(tid))
        return handler._SENT
