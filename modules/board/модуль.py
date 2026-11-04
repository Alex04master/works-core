# -*- coding: utf-8 -*-
"""Модуль «Доска» — ТАБЛИЦА ЛИДЕРОВ для проектора (как в референсе):
тёмный стенд с золотым заголовком и вращающимся ореолом, подиум топ-3
с парящими медалями, живые часы, дата, рейтинг бригад и студентов
с прогресс-барами, автообновление каждые 30 секунд.
"""
from datetime import datetime


def register(ctx):
    @ctx.add_route("GET", "/board", access="staff")
    def board_page(handler, params):
        # Баллы: последняя версия каждой сдачи
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
        entries = []  # {"name", "members": [fio], "score"}
        teams = {}
        for sid, s in students.items():
            br = (s.get("бригада") or "").strip()
            sc = scores.get(sid, 0)
            if br:
                t = teams.setdefault(br, {"score": 0, "members": []})
                t["score"] += sc
                t["members"].append(s.get("fio", ""))
            else:
                entries.append({"name": s.get("fio", ""), "members": [],
                                "score": sc})
        for br, t in teams.items():
            entries.append({"name": br, "members": t["members"],
                            "score": t["score"]})
        entries.sort(key=lambda d: -d["score"])

        max_sc = max([d["score"] for d in entries] + [0]) or 1
        medals = ["\U0001f947", "\U0001f948", "\U0001f949"]
        kinds = ["gold", "silver", "bronze"]

        # ── Подиум топ-3 ────────────────────────────────────────
        podium = ""
        for i, d in enumerate(entries[:3]):
            w = int(round(100.0 * d["score"] / max_sc))
            members = "<br>".join(d["members"]) if d["members"] else ""
            podium += (
                '<div class="pod-card %s"><div class="pod-medal">%s</div>'
                '<div class="pod-name">%s</div>'
                '<div class="pod-members">%s</div>'
                '<div class="pod-score">%.1f</div>'
                '<div class="pod-label">баллов</div>'
                '<div class="pbar"><div class="pbar-fill" style="width:%d%%">'
                '</div></div></div>'
            ) % (kinds[i], medals[i], d["name"], members, d["score"], w)

        # ── Остальные строки ────────────────────────────────────
        rows = ""
        for i, d in enumerate(entries[3:], start=4):
            w = int(round(100.0 * d["score"] / max_sc))
            members = ('<div class="rest-members">%s</div>'
                       % ", ".join(d["members"])) if d["members"] else ""
            rows += (
                '<div class="rest-row"><div class="rest-pos">%d.</div>'
                '<div><div class="rest-name">%s</div>%s</div>'
                '<div class="rest-score"><div class="rest-avg">%.1f</div>'
                '<div class="pbar"><div class="pbar-fill" style="width:%d%%">'
                '</div></div></div></div>'
            ) % (i, d["name"], members, d["score"], w)

        if not podium and not rows:
            rows = ('<div class="empty-msg"><span>\U0001f3c6</span>'
                    'Пока нет оценок</div>')

        grp = ", ".join(sorted({s.get("group", "") for s in students.values()
                                if s.get("group", "")})) or "—"
        now = datetime.now()
        extra = '''<meta http-equiv="refresh" content="30"><style>
body{background:radial-gradient(ellipse at top,#1a1f4e,#0a0e27 70%);color:#fff;font-family:'Segoe UI',Tahoma,sans-serif;}
body::before{content:'';position:fixed;top:-50%;left:-50%;width:200%;height:200%;background:radial-gradient(circle,rgba(102,126,234,.07),transparent 50%);animation:spin 40s linear infinite;pointer-events:none;}
@keyframes spin{to{transform:rotate(360deg)}}
#main>h1:first-of-type{display:none}
#main{max-width:1300px;position:relative;z-index:1;padding-bottom:40px;}
.stand-title{font-size:3em;font-weight:800;text-align:center;margin:6px 0 4px;background:linear-gradient(135deg,#ffd700,#ffed4e,#ffd700);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;}
.stand-sub{font-size:1.3em;color:#a0a8d0;font-weight:300;text-align:center;}
.stand-meta{display:flex;justify-content:space-between;align-items:center;margin:16px 0 26px;color:#8892c8;font-size:1.1em;flex-wrap:wrap;}
.clock{color:#ffd700;font-family:'Courier New',monospace;font-weight:700;font-size:1.2em;}
.podium{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin:0 auto 32px;}
.pod-card{background:rgba(255,255,255,.05);backdrop-filter:blur(8px);border-radius:16px;padding:22px 14px;text-align:center;border:2px solid transparent;animation:rise .7s ease-out both;}
@keyframes rise{from{opacity:0;transform:translateY(30px)}to{opacity:1;transform:translateY(0)}}
.pod-card.gold{border-color:#ffd700;background:linear-gradient(135deg,rgba(255,215,0,.13),rgba(255,215,0,.03));box-shadow:0 0 40px rgba(255,215,0,.2);transform:scale(1.05);order:2;}
.pod-card.silver{border-color:#c0c0c0;background:linear-gradient(135deg,rgba(192,192,192,.1),rgba(192,192,192,.03));box-shadow:0 0 25px rgba(192,192,192,.12);order:1;}
.pod-card.bronze{border-color:#cd7f32;background:linear-gradient(135deg,rgba(205,127,50,.1),rgba(205,127,50,.03));box-shadow:0 0 25px rgba(205,127,50,.12);order:3;}
.pod-medal{font-size:3.2em;animation:float 2.5s ease-in-out infinite;}
@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-7px)}}
.pod-name{font-size:1.4em;font-weight:700;margin:4px 0;}
.pod-members{font-size:.82em;color:#a0a8d0;line-height:1.3;margin-bottom:10px;}
.pod-score{font-size:2.6em;font-weight:800;background:linear-gradient(135deg,#ffd700,#ffed4e);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;}
.pod-label{color:#8892c8;font-size:.9em;margin-bottom:10px;}
.rest-row{display:grid;grid-template-columns:60px 1fr 170px;align-items:center;gap:10px;background:rgba(255,255,255,.05);backdrop-filter:blur(6px);border-radius:12px;padding:14px 22px;margin-bottom:10px;border-left:4px solid #667eea;transition:background .3s;animation:slideR .4s ease-out both;}
@keyframes slideR{from{opacity:0;transform:translateX(-15px)}to{opacity:1;transform:translateX(0)}}
.rest-row:hover{background:rgba(255,255,255,.08)}
.rest-pos{font-size:2em;font-weight:800;color:#667eea;text-align:center;}
.rest-name{font-size:1.2em;font-weight:600;}
.rest-members{font-size:.8em;color:#a0a8d0;}
.rest-score{text-align:center;}
.rest-avg{font-size:1.8em;font-weight:800;color:#ffd700;}
.pbar{width:100%;height:10px;background:rgba(255,255,255,.1);border-radius:6px;overflow:hidden;margin-top:4px;}
.pbar-fill{height:100%;background:linear-gradient(90deg,#667eea,#764ba2);border-radius:6px;transition:width 1s;}
.empty-msg{text-align:center;padding:40px 20px;color:#aaa;}
.empty-msg span{font-size:3em;display:block;margin-bottom:10px;}
@media(max-width:768px){.stand-title{font-size:2em}.podium{grid-template-columns:1fr}.pod-card.gold,.pod-card.silver,.pod-card.bronze{order:unset;transform:none}.rest-row{grid-template-columns:40px 1fr 90px}.pbar{display:none}}
</style>
<script>function _tick(){var d=new Date();var e=document.getElementById("clk");if(e)e.innerText=d.toLocaleTimeString("ru");}setInterval(_tick,1000);</script>'''
        body = ('<h1 class="stand-title">\U0001f3c6 ТАБЛИЦА ЛИДЕРОВ</h1>'
                '<p class="stand-sub">works-core · учебная практика</p>'
                '<div class="stand-meta"><span>%s</span>'
                '<span class="clock" id="clk">%s</span><span>%s</span></div>%s%s'
                ) % (grp, now.strftime("%H:%M:%S"), now.strftime("%d.%m.%Y"),
                     ('<div class="podium">%s</div>' % podium) if podium else "",
                     rows)
        return ctx.render_page("Доска", body, staff=True, extra_head=extra)

    ctx.log("загружен: доска (таблица лидеров)")
