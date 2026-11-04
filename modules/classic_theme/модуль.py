# -*- coding: utf-8 -*-
"""Модуль «Классический стиль» — палитры оформления поверх базового макета.

Подписывается на событие page.head и перекрашивает интерфейс в зависимости
от курса (курс без темы получает "default"). Отключается через /_modules —
останется базовый стиль ядра.
"""

CSS_TPL = """
<style>
  body { background: @bg_page; font-family: @font; color: #333; }
  a { color: @accent; }

  .topbar {
    background: linear-gradient(135deg, @bg_header 0%, @bg_header_light 100%);
    box-shadow: 0 4px 18px @bg_header55;
  }
  .topbar nav a:hover { background: rgba(255,255,255,.2); }

  h1, h2, h3 { color: @heading; }
  .footer { color: #9ca3af; }

  .course-list li:hover, .lesson-list li:hover, .task-list li:hover { background: @accent1a; }
  .course-list a, .lesson-list a, .task-list a { color: #333; }
  .course-list a:hover, .lesson-list a:hover, .task-list a:hover,
  .course-list a:hover::after, .lesson-list a:hover::after { color: @accent; }

  .task-desc { border-left: 4px solid @accent; }
  .mat-text .mat-content, .field-block { border-left: 4px solid @accent; }

  button, .btn { background: @accent; box-shadow: 0 2px 8px @accent33; }
  .btn-big { background: @accent; box-shadow: 0 4px 14px @accent33; }

  input:focus, textarea:focus, select:focus { border-color: @accent; }
  .radio-label:hover, .cb-label:hover { background: @accent1a; border-color: @accent; }
  input[type="checkbox"], input[type="radio"] { accent-color: @accent; }
  details summary { color: @accent; }
  .req { color: @accent; }

  table.staff-table th, .module-table th {
    background: linear-gradient(135deg, @bg_header 0%, @bg_header_light 100%);
    color: #fff;
  }
  .sub-status { background: #f0fdf4; border-left: 4px solid #10b981; }
  .sub-status h3 { color: #166534; }
  .notice { border-left: 4px solid #f59e0b; }
  .error { border-left: 4px solid #ef4444; }
  .state-ok { color: #16a34a; }
  .state-выключен, .state-отключён { color: #b07f18; }
  .state-сбой, .state-битый { color: #ef4444; }
</style>
"""


def _lighten(hex_color, f=0.22):
    """Осветлить hex-цвет (смешать с белым)."""
    h = (hex_color or "#000000").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return "#000000"
    mix = lambda c: int(c + (255 - c) * f)
    return "#%02x%02x%02x" % (mix(r), mix(g), mix(b))


def register(ctx):
    themes = ctx.settings.get("темы", {})

    def resolve_theme(course=None):
        t = themes.get("default", {})
        out = {
            "bg_page": t.get("фон_страницы", "#f0f2f5"),
            "bg_header": t.get("фон_шапки", "#667eea"),
            "bg_header2": t.get("фон_шапки_2", "#764ba2"),
            "heading": t.get("цвет_заголовков", "#1e293b"),
            "accent": t.get("акцент", "#667eea"),
            "font": t.get("шрифт",
                          "'Segoe UI', Tahoma, Geneva, Verdana, sans-serif"),
        }
        title = (course or {}).get("title", "").lower()
        for key, t in themes.items():
            if key == "default":
                continue
            if key.lower() in title or t.get("name", "").lower() in title:
                out.update({
                    "bg_page": t.get("фон_страницы", out["bg_page"]),
                    "bg_header": t.get("фон_шапки", out["bg_header"]),
                    "bg_header2": t.get("фон_шапки_2", out["bg_header2"]),
                    "heading": t.get("цвет_заголовков", out["heading"]),
                    "accent": t.get("акцент", out["accent"]),
                    "font": t.get("шрифт", out["font"]),
                })
                break
        return out

    def on_page_head(course=None, lesson=None, **kw):
        t = resolve_theme(course)
        # ВАЖНО: @bg_header_light заменяется ДО @bg_header,
        # иначе "@bg_header" съедает префикс "@bg_header_light".
        # @bg_header55 resolves автоматически при замене @bg_header.
        return (CSS_TPL
                .replace("@bg_page", t["bg_page"])
                .replace("@bg_header_light", t["bg_header2"] or _lighten(t["bg_header"]))
                .replace("@bg_header", t["bg_header"])
                .replace("@heading", t["heading"])
                .replace("@accent1a", t["accent"] + "1a")
                .replace("@accent33", t["accent"] + "33")
                .replace("@accent", t["accent"])
                .replace("@font", t["font"]))

    ctx.on("page.head", on_page_head)
    ctx.log("загружен: классический стиль")
