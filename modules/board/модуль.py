# -*- coding: utf-8 -*-
"""Модуль «Доска» — ТАБЛИЦА ЛИДЕРОВ для проектора.

Группировка по учебным группам и фильтр «группа, у которой сейчас
занятие»: преподаватель выбирает группу один раз — выбор сохраняется
в адресе страницы и переживает автообновление каждые 30 секунд.
Для выбранной группы — подиум топ-3; в режиме «Все группы» — секции
по группам с рейтингами. Живые часы, дата, прогресс-бары, медали.
"""
import urllib.parse
from datetime import datetime


def register(ctx):
    @ctx.add_route("GET", "/board", access="staff")
    def board_page(handler, params):
        scores = {}
        for sub in ctx.list_submissions():
            vs = sub.get("versions") or []
            if not vs:
                continue
            sc = vs[-1].get("score") or 0
            if not isinstance(sc, (int, float)):
                sc = 0
            sid = sub.get("student", "")
            scores[sid] = scores.get(sid, 0) + sc

        students = {s["id"]: s for s in ctx.list_students()}
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
        sel = (qs.get("group") or [""])[0].strip()
        groups = sorted({(s.get("group") or "").strip()
                         for s in students.values()
                         if (s.get("group") or "").strip()})
        if sel not in groups:
            sel = ""

        def entries_for(group):
            teams = {}
            solo = []
            for sid, s in students.items():
                if group and (s.get("group") or "").strip() != group:
                    continue
                br = (s.get("бригада") or "").strip()
                sc = scores.get(sid, 0)
                if br:
                    t = teams.setdefault(br, {"score": 0, "members": []})
                    t["score"] += sc
                    t["members"].append(s.get("fio", ""))
                else:
                    solo.append({"name": s.get("fio", ""), "members": [],
                                 "score": sc})
            out = [{"name": b, "members": t["members"], "score": t["score"]}
                   for b, t in teams.items()] + solo
            out.sort(key=lambda d: -d["score"])
            return out

        medals = ["\U0001f947", "\U0001f948", "\U0001f949"]

        def row(m, d, maxg):
            w = int(round(100.0 * d["score"] / maxg))
            members = ('<div class="rest-members">%s</div>'
                       % ", ".join(d["members"])) if d["members"] else ""
            return (
                '<div class="rest-row"><div class="rest-pos">%s</div>'
                '<div><div class="rest-name">%s</div>%s</div>'
                '<div class="rest-score"><div class="rest-avg">%.1f</div>'
                '<div class="pbar"><div class="pbar-fill" '
                'style="width:%d%%"></div></div></div></div>'
            ) % (m, d["name"], members, d["score"], w)

        def rows_html(entries, podium):
            if not entries:
                return '<div class="empty-msg">Нет данных</div>'
            html = ""
            maxg = max([d["score"] for d in entries] + [0]) or 1
            if podium:
                kinds = ["gold", "silver", "bronze"]
                pod = ""
                for i, d in enumerate(entries[:3]):
                    w = int(round(100.0 * d["score"] / maxg))
                    members = "<br>".join(d["members"]) if d["members"] else ""
                    pod += (
                        '<div class="pod-card %s">'
                        '<div class="pod-medal">%s</div>'
                        '<div class="pod-name">%s</div>'
                        '<div class="pod-members">%s</div>'
                        '<div class="pod-score">%.1f</div>'
                        '<div class="pod-label">баллов</div>'
                        '<div class="pbar"><div class="pbar-fill" '
                        'style="width:%d%%"></div></div></div>'
                    ) % (kinds[i], medals[i], d["name"], members,
                         d["score"], w)
                html += '<div class="podium">%s</div>' % pod
                for i, d in enumerate(entries[3:]):
                    html += row("%d." % (i + 4), d, maxg)
            else:
                for i, d in enumerate(entries):
                    html += row(medals[i] if i < 3 else "%d." % (i + 1),
                                d, maxg)
            return html

        chips = ('<div class="grp-chips">'
                 '<a class="gchip%s" href="/board">Все группы</a>'
                 % (" active" if not sel else ""))
        for g in groups:
            chips += ('<a class="gchip%s" href="/board?group=%s">%s</a>'
                      % (" active" if sel == g else "",
                         urllib.parse.quote(g), g))
        chips += "</div>"

        shown = [g for g in groups if not sel or g == sel]
        sections = ""
        for g in shown:
            sections += ('<h2 class="lb-grp">🏫 Группа: %s</h2>%s'
                         % (g, rows_html(entries_for(g), podium=bool(sel))))
        no_group = [s for s in students.values()
                    if not (s.get("group") or "").strip()]
        if not sel and no_group:
            sections += ('<h2 class="lb-grp">Без группы</h2>%s'
                         % rows_html(entries_for(""), podium=False))
        if not groups and not no_group:
            sections = ('<div class="empty-msg"><span>👥</span>'
                        'Пока нет студентов</div>')

        now = datetime.now()
        refresh = "30; url=/board" + ("?group=" + urllib.parse.quote(sel)
                                      if sel else "")
        extra = ('<meta http-equiv="refresh" content="%s"><style>'
                 % refresh +
                 'body{background:radial-gradient(ellipse at top,#1a1f4e,#0a0e27 70%);'
                 'color:#fff;font-family:\'Segoe UI\',Tahoma,sans-serif;}'
                 'body::before{content:\'\';position:fixed;top:-50%;left:-50%;'
                 'width:200%;height:200%;background:radial-gradient(circle,'
                 'rgba(102,126,234,.07),transparent 50%);'
                 'animation:spin 40s linear infinite;pointer-events:none;}'
                 '@keyframes spin{to{transform:rotate(360deg)}}'
                 '#main>h1:first-of-type{display:none}'
                 '#main{max-width:1300px;position:relative;z-index:1;'
                 'padding-bottom:40px;}'
                 '.stand-title{font-size:3em;font-weight:800;text-align:center;'
                 'margin:6px 0 4px;background:linear-gradient(135deg,#ffd700,'
                 '#ffed4e,#ffd700);-webkit-background-clip:text;'
                 'background-clip:text;-webkit-text-fill-color:transparent;}'
                 '.stand-sub{font-size:1.3em;color:#a0a8d0;font-weight:300;'
                 'text-align:center;}'
                 '.grp-chips{display:flex;gap:8px;flex-wrap:wrap;'
                 'justify-content:center;margin:14px 0 4px;}'
                 '.gchip{color:#c7d2fe;background:rgba(102,126,234,.18);'
                 'border:1px solid rgba(165,180,252,.35);padding:6px 16px;'
                 'border-radius:20px;font-size:.95em;text-decoration:none;'
                 'transition:all .2s;}'
                 '.gchip:hover{filter:brightness(1.2);transform:translateY(-1px);}'
                 '.gchip.active{background:linear-gradient(135deg,#667eea,#764ba2);'
                 'color:#fff;border-color:transparent;}'
                 '.lb-grp{font-size:1.5em;font-weight:700;color:#a5b4fc;'
                 'margin:20px 0 10px;text-align:center;}'
                 '.stand-meta{display:flex;justify-content:space-between;'
                 'align-items:center;margin:10px 0 22px;color:#8892c8;'
                 'font-size:1.1em;flex-wrap:wrap;}'
                 '.clock{color:#ffd700;font-family:\'Courier New\',monospace;'
                 'font-weight:700;font-size:1.2em;}'
                 '.podium{display:grid;grid-template-columns:1fr 1fr 1fr;'
                 'gap:16px;margin:0 auto 28px;}'
                 '.pod-card{background:rgba(255,255,255,.05);'
                 'backdrop-filter:blur(8px);border-radius:16px;'
                 'padding:22px 14px;text-align:center;'
                 'border:2px solid transparent;animation:rise .7s ease-out both;}'
                 '@keyframes rise{from{opacity:0;transform:translateY(30px)}'
                 'to{opacity:1;transform:translateY(0)}}'
                 '.pod-card.gold{border-color:#ffd700;background:linear-gradient('
                 '135deg,rgba(255,215,0,.13),rgba(255,215,0,.03));'
                 'box-shadow:0 0 40px rgba(255,215,0,.2);transform:scale(1.05);'
                 'order:2;}'
                 '.pod-card.silver{border-color:#c0c0c0;background:linear-gradient('
                 '135deg,rgba(192,192,192,.1),rgba(192,192,192,.03));'
                 'box-shadow:0 0 25px rgba(192,192,192,.12);order:1;}'
                 '.pod-card.bronze{border-color:#cd7f32;background:linear-gradient('
                 '135deg,rgba(205,127,50,.1),rgba(205,127,50,.03));'
                 'box-shadow:0 0 25px rgba(205,127,50,.12);order:3;}'
                 '.pod-medal{font-size:3.2em;animation:float 2.5s ease-in-out infinite;}'
                 '@keyframes float{0%,100%{transform:translateY(0)}'
                 '50%{transform:translateY(-7px)}}'
                 '.pod-name{font-size:1.4em;font-weight:700;margin:4px 0;}'
                 '.pod-members{font-size:.82em;color:#a0a8d0;line-height:1.3;'
                 'margin-bottom:10px;}'
                 '.pod-score{font-size:2.6em;font-weight:800;background:'
                 'linear-gradient(135deg,#ffd700,#ffed4e);'
                 '-webkit-background-clip:text;background-clip:text;'
                 '-webkit-text-fill-color:transparent;}'
                 '.pod-label{color:#8892c8;font-size:.9em;margin-bottom:10px;}'
                 '.rest-row{display:grid;grid-template-columns:60px 1fr 170px;'
                 'align-items:center;gap:10px;background:rgba(255,255,255,.05);'
                 'backdrop-filter:blur(6px);border-radius:12px;padding:14px 22px;'
                 'margin-bottom:10px;border-left:4px solid #667eea;'
                 'transition:background .3s;animation:slideR .4s ease-out both;}'
                 '@keyframes slideR{from{opacity:0;transform:translateX(-15px)}'
                 'to{opacity:1;transform:translateX(0)}}'
                 '.rest-row:hover{background:rgba(255,255,255,.08)}'
                 '.rest-pos{font-size:2em;font-weight:800;color:#667eea;'
                 'text-align:center;}'
                 '.rest-name{font-size:1.2em;font-weight:600;}'
                 '.rest-members{font-size:.8em;color:#a0a8d0;}'
                 '.rest-score{text-align:center;}'
                 '.rest-avg{font-size:1.8em;font-weight:800;color:#ffd700;}'
                 '.pbar{width:100%;height:10px;background:rgba(255,255,255,.1);'
                 'border-radius:6px;overflow:hidden;margin-top:4px;}'
                 '.pbar-fill{height:100%;background:linear-gradient(90deg,'
                 '#667eea,#764ba2);border-radius:6px;transition:width 1s;}'
                 '.empty-msg{text-align:center;padding:30px 20px;color:#aaa;}'
                 '.empty-msg span{font-size:3em;display:block;margin-bottom:10px;}'
                 '@media(max-width:768px){.stand-title{font-size:2em}'
                 '.podium{grid-template-columns:1fr}'
                 '.pod-card.gold,.pod-card.silver,.pod-card.bronze{order:unset;'
                 'transform:none}.rest-row{grid-template-columns:40px 1fr 90px}'
                 '.pbar{display:none}}'
                 '</style>'
                 '<script>function _tick(){var d=new Date();'
                 'var e=document.getElementById("clk");'
                 'if(e)e.innerText=d.toLocaleTimeString("ru");}'
                 'setInterval(_tick,1000);</script>')
        body = ('<h1 class="stand-title">\U0001f3c6 ТАБЛИЦА ЛИДЕРОВ</h1>'
                '<p class="stand-sub">works-core · учебная практика</p>'
                '%s'
                '<div class="stand-meta"><span>%s</span>'
                '<span class="clock" id="clk">%s</span><span>%s</span></div>%s'
                ) % (chips, sel or "Все группы", now.strftime("%H:%M:%S"),
                     now.strftime("%d.%m.%Y"), sections)
        return ctx.render_page("Доска", body, staff=True, extra_head=extra)

    ctx.log("загружен: доска (таблица лидеров, группировка по группам)")
