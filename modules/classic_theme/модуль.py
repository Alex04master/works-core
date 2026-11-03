# -*- coding: utf-8 -*-
"""Модуль «Классический стиль» — академичная тема оформления.

Подписывается на событие page.head и подставляет CSS в зависимости
от курса. Настройки цветов — в манифесте модуля (модуль.json/настройки/темы).
Курс без явной темы получает тему "default".

Можно отключить через панель /_modules — вернётся базовый стиль ядра.
"""

CSS_TPL = """
<style>
  /* === Классическая тема для works-core === */

  body {{
    background: {bg_page};
    font-family: {font};
    font-size: 15px;
    line-height: 1.6;
    color: #2c3e50;
    min-height: 100vh;
  }}

  body.staff {{
    background: {bg_page};
  }}

  /* Верхняя панель */
  .topbar {{
    background: {bg_header};
    color: #ecf0f3;
    padding: 12px 24px;
    display: flex;
    align-items: center;
    gap: 14px;
    flex-wrap: wrap;
    border-bottom: 2px solid {accent};
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
  }}
  .topbar nav a {{
    color: #bcc8d5;
    text-decoration: none;
    padding: 6px 14px;
    border-radius: 4px;
    font-size: 14px;
    transition: background 0.15s;
  }}
  .topbar nav a:hover {{
    color: #fff;
    background: {accent};
  }}
  .topbar .user {{
    color: #cdd8e4;
    font-size: 13px;
  }}

  /* Заголовки */
  h1 {{
    font-size: 1.45em;
    margin: 20px 0 14px;
    color: {heading_color};
    border-bottom: 1px solid #d5dce6;
    padding-bottom: 6px;
    font-weight: 600;
  }}
  h2 {{
    font-size: 1.2em;
    margin: 22px 0 8px;
    color: {heading_color};
  }}
  h3 {{
    font-size: 1.05em;
    margin: 16px 0 6px;
    color: #3a4a5a;
    font-weight: 600;
  }}

  /* Основной блок */
  #main {{
    max-width: 980px;
    margin: 24px auto;
    padding: 0 24px 40px;
  }}

  /* Подвал */
  .footer {{
    text-align: center;
    padding: 16px;
    color: #8a9aa8;
    font-size: 12px;
    border-top: 1px solid #d5dce6;
    margin-top: 30px;
  }}

  /* Карточки (списки курсов, занятий, заданий) */
  .course-list, .lesson-list, .task-list {{
    list-style: none;
    padding: 0;
  }}
  .course-list li, .lesson-list li, .task-list li {{
    margin: 8px 0;
    padding: 12px 18px;
    background: #fff;
    border-radius: 6px;
    border: 1px solid #d5dce6;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    transition: border-color 0.12s;
  }}
  .course-list li:hover, .lesson-list li:hover, .task-list li:hover {{
    border-color: {accent};
  }}
  .course-list a, .lesson-list a, .task-list a {{
    font-size: 1.1em;
    font-weight: 600;
    color: {heading_color};
    text-decoration: none;
    display: block;
  }}
  .course-list a:hover, .lesson-list a:hover, .task-list a:hover {{
    color: {accent};
  }}
  .task-list .status {{
    float: right;
    font-size: 13px;
    color: #6a7a88;
  }}

  /* Материалы */
  .mat-list {{
    list-style: none;
    padding: 0;
  }}
  .mat-list li {{
    margin: 4px 0;
    padding: 8px 12px;
    background: #faf8f5;
    border-radius: 4px;
    border: 1px solid #e5e2dd;
    font-size: 14px;
  }}
  .mat-list a {{
    color: {heading_color};
  }}
  .mat-content {{
    margin-top: 8px;
    padding: 12px 16px;
    background: #f8f6f2;
    border-radius: 6px;
    border-left: 3px solid {accent};
  }}

  /* Описание задания */
  .task-desc {{
    background: #fff;
    padding: 18px 22px;
    border-radius: 6px;
    border: 1px solid #d5dce6;
    border-left: 4px solid {accent};
    margin: 14px 0;
    line-height: 1.55;
  }}
  .task-desc h2 {{
    margin-top: 0;
    border: none;
  }}
  .task-desc h3 {{
    margin: 10px 0 4px;
  }}

  /* Статус сдачи */
  .sub-status {{
    background: #eaf3e8;
    padding: 14px 18px;
    border-radius: 6px;
    border: 1px solid #b7d5b7;
    border-left: 4px solid #2a8a3a;
    margin: 10px 0;
  }}
  .sub-status h3 {{
    margin: 0 0 4px;
    color: #1a6a2a;
  }}

  /* Форма */
  .task-form {{
    background: #fff;
    padding: 22px;
    border-radius: 6px;
    border: 1px solid #d5dce6;
    margin: 14px 0;
  }}
  .field {{
    margin: 10px 0;
  }}
  .field label {{
    display: block;
    font-weight: 600;
    margin-bottom: 4px;
    color: {heading_color};
    font-size: 14px;
  }}
  .field-label {{
    display: block;
    font-weight: 600;
    margin-bottom: 4px;
    color: {heading_color};
  }}
  .req {{
    color: {accent};
    font-weight: 700;
  }}
  .field-block {{
    background: #f5f2ed;
    padding: 8px 14px;
    border-radius: 4px;
    margin: 12px 0 6px;
    font-size: 14px;
    color: #3a4a5a;
    border-bottom: 1px solid #e5e2dd;
  }}

  input[type="text"], input[type="number"], input[type="email"],
  input[type="tel"], input[type="date"],
  textarea, select {{
    width: 100%;
    padding: 8px 12px;
    border: 1px solid #d5dce6;
    border-radius: 4px;
    font: inherit;
    font-size: 14px;
    background: #faf8f5;
    transition: border-color 0.12s, box-shadow 0.12s;
  }}
  input:focus, textarea:focus, select:focus {{
    border-color: {accent};
    outline: none;
    box-shadow: 0 0 0 2px {accent}33;
    background: #fff;
  }}
  textarea {{
    resize: vertical;
    min-height: 70px;
  }}
  select {{
    background: #fff;
    cursor: pointer;
  }}

  .field-radio, .field-checkboxes {{
    padding: 6px 0;
  }}
  .radio-label, .cb-label {{
    display: inline-block;
    margin: 3px 8px 3px 0;
    padding: 5px 12px;
    background: #f5f2ed;
    border-radius: 4px;
    cursor: pointer;
    border: 1px solid #e5e2dd;
    font-size: 14px;
  }}
  .radio-label:hover, .cb-label:hover {{
    background: #ede8e0;
    border-color: {accent};
  }}
  .field-checkbox label {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    cursor: pointer;
  }}
  input[type="file"] {{
    display: block;
    padding: 8px 0;
  }}

  /* Кнопки */
  button, .btn {{
    background: {accent};
    color: #fff;
    border: none;
    padding: 10px 26px;
    border-radius: 4px;
    font: inherit;
    font-weight: 600;
    cursor: pointer;
    font-size: 14px;
    transition: background 0.12s;
    display: inline-block;
  }}
  button:hover, .btn:hover {{
    filter: brightness(0.88);
  }}
  .btn-secondary {{
    background: #6a7a88;
  }}
  .btn-secondary:hover {{
    background: #5a6a78;
  }}
  .btn-danger {{
    background: #c0392b;
  }}
  .btn-danger:hover {{
    background: #a03022;
  }}

  .hint {{
    color: #6a7a88;
    font-size: 13px;
    margin: 6px 0;
  }}
  .notice {{
    background: #faf3d5;
    padding: 10px 16px;
    border-radius: 6px;
    border-left: 4px solid #c5a332;
    margin: 10px 0;
  }}
  .error {{
    background: #fce8e8;
    padding: 10px 16px;
    border-radius: 6px;
    border-left: 4px solid {accent};
    margin: 10px 0;
  }}

  /* Панель преподавателя */
  body.staff #main {{
    max-width: 1120px;
  }}
  .staff-card {{
    background: #fff;
    padding: 18px 22px;
    border-radius: 6px;
    border: 1px solid #d5dce6;
    margin: 0 0 14px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
  }}
  .staff-card h2 {{
    margin-top: 0;
  }}
  .staff-card h2 a {{
    color: {heading_color};
    text-decoration: none;
  }}
  .staff-card h2 a:hover {{
    color: {accent};
  }}

  .staff-actions {{
    margin: 10px 0;
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }}
  .staff-actions a, .staff-actions button {{
    padding: 6px 16px;
    border-radius: 4px;
    text-decoration: none;
    font-size: 13px;
  }}

  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
  }}
  table.staff-table {{
    width: 100%;
    border-collapse: collapse;
    background: #fff;
    border-radius: 6px;
    overflow: hidden;
  }}
  table.staff-table th {{
    background: #f0ece6;
    font-weight: 600;
    padding: 8px 12px;
    text-align: left;
    border-bottom: 2px solid #d5dce6;
    color: {heading_color};
  }}
  table.staff-table td {{
    padding: 8px 12px;
    border-bottom: 1px solid #e5e2dd;
  }}
  table.staff-table tr:hover {{
    background: #f5f2ed;
  }}

  /* Таблица модулей */
  .module-table {{
    width: 100%;
    border-collapse: collapse;
    margin: 16px 0;
  }}
  .module-table th, .module-table td {{
    padding: 8px 14px;
    text-align: left;
    border-bottom: 1px solid #e5e2dd;
  }}
  .module-table th {{
    background: #f0ece6;
    font-weight: 600;
    color: {heading_color};
  }}
  .state-ok {{ color: #1a7a2a; }}
  .state-выключен {{ color: #8a7a30; }}
  .state-отключён {{ color: #8a7a30; }}
  .state-сбой {{ color: {accent}; }}
  .reason {{ color: #6a7a88; font-size: 13px; }}

  /* Входные формы */
  .login-form {{
    max-width: 420px;
    margin: 40px auto;
    background: #fff;
    padding: 28px;
    border-radius: 8px;
    border: 1px solid #d5dce6;
    box-shadow: 0 2px 10px rgba(0,0,0,0.06);
  }}
  .login-form h2 {{
    margin-top: 0;
    color: {heading_color};
  }}

  details {{
    margin: 8px 0;
  }}
  details summary {{
    cursor: pointer;
    font-weight: 600;
    color: {heading_color};
    padding: 6px 0;
  }}
  details[open] summary {{
    margin-bottom: 8px;
  }}

  /* Уведомления и подсказки */
  pre {{
    background: #f5f2ed;
    padding: 12px 16px;
    border-radius: 6px;
    overflow-x: auto;
    font-size: 13px;
    line-height: 1.45;
    border: 1px solid #e5e2dd;
  }}
  code {{
    background: #ede8e0;
    padding: 1px 5px;
    border-radius: 3px;
    font-size: 13px;
  }}
  .qr {{
    background: #fff;
    padding: 14px;
    border-radius: 6px;
    display: inline-block;
  }}

  @media (max-width: 700px) {{
    #main {{ padding: 0 12px; }}
    .topbar {{ padding: 8px 12px; }}
    table, .staff-table {{
      font-size: 13px;
    }}
  }}
</style>
"""


def register(ctx):
    themes = ctx.settings.get("темы", {})
    default = themes.get("default", {})
    default_theme = {
        "bg_page": default.get("фон_страницы", "#f4f1ea"),
        "bg_header": default.get("фон_шапки", "#2c3e50"),
        "heading_color": default.get("цвет_заголовков", "#1a2a3a"),
        "accent": default.get("акцент", "#c0392b"),
        "font": default.get("шрифт", "'Georgia', 'Times New Roman', serif"),
    }

    def resolve_theme(course=None):
        """Выбрать тему по названию курса."""
        if not course:
            return default_theme
        title = course.get("title", "")
        for key, t in themes.items():
            if key == "default":
                continue
            if key in title.lower() or t.get("name", "") in title:
                return {
                    "bg_page": t.get("фон_страницы", default_theme["bg_page"]),
                    "bg_header": t.get("фон_шапки", default_theme["bg_header"]),
                    "heading_color": t.get("цвет_заголовков", default_theme["heading_color"]),
                    "accent": t.get("акцент", default_theme["accent"]),
                    "font": t.get("шрифт", default_theme["font"]),
                }
        return default_theme

    def on_page_head(course=None, lesson=None, **kw):
        t = resolve_theme(course)
        return CSS_TPL.format(
            bg_page=t["bg_page"],
            bg_header=t["bg_header"],
            heading_color=t["heading_color"],
            accent=t["accent"],
            font=t["font"],
        )

    ctx.on("page.head", on_page_head)
    ctx.log("загружен: классический стиль")