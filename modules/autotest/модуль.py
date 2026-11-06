# -*- coding: utf-8 -*-
"""Модуль «Автотест»: автоматическая проверка тестовых заданий.

Правила задаются в настройках ЗАДАНИЯ (настройки.автопроверка) и потому
переезжают вместе с курсом при импорте/экспорте пакета:

    "настройки": {
      "автопроверка": [
        {"field": "q1", "type": "exact", "expect": "вариант",
         "вопрос": "Что контролирует ШС?"},
        {"field": "q2", "type": "number", "expect": "12", "допуск": 0.5},
        {"field": "q3", "type": "keywords", "expect": "линия извещател"},
        {"field": "q4", "type": "oneof", "expect": ["12 в", "двенадцать"]}
      ]
    }

Типы проверок:
    exact    — точное совпадение (регистр и лишние пробелы не важны);
    number   — число с допуском («допуск», по умолчанию 0; запятая
               в ответе считается точкой);
    keywords — все слова из expect встречаются в ответе в любой форме
               (подстрока или совпадение начала слова);
    oneof    — ответ входит в список допустимых (expect — список или
               строка с разделителем «|»).

Каждому правилу можно задать «вес» (по умолчанию 1).

Результат: все поля верно → вердикт «Тест пройден (автопроверка)»,
статус «принято», балл 100; иначе — «Тест: N из M верно», статус
«доработка», балл пропорционально весам. В комментарий кладётся разбор
по полям (✔/✘) — без разглашения правильных ответов.
"""
import re


def _norm(s):
    return re.sub(r"\s+", " ",
                  str(s if s is not None else "")).strip().lower()


def _tofloat(s):
    try:
        return float(str(s).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def _cpfx(a, b):
    """Длина общего начала двух слов."""
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def _check(val, rule):
    typ = str(rule.get("type") or "exact").lower()
    expect = rule.get("expect")
    if typ == "number":
        v, e = _tofloat(val), _tofloat(expect)
        if v is None or e is None:
            return False
        eps = _tofloat(rule.get("допуск")) or 0.0
        return abs(v - e) <= abs(eps) + 1e-9
    if typ == "keywords":
        # слово зачтено, если встречается в ответе как подстрока либо
        # совпадает с любым словом ответа по началу (любая форма слова:
        # «линия» найдётся в «линией», «извещател» — в «извещателями»)
        words = [w for w in re.split(r"[,\s]+", _norm(expect)) if w]
        hay = _norm(val)
        toks = hay.split(" ")
        return bool(words) and all(
            w in hay
            or any(_cpfx(w, t) >= max(4, len(w) - 2) for t in toks)
            for w in words)
    if typ == "oneof":
        opts = expect if isinstance(expect, list) else \
            str(expect or "").split("|")
        return _norm(val) in {_norm(x) for x in opts if str(x).strip()}
    return _norm(val) == _norm(expect)


def register(ctx):
    def grade(task=None, answers=None, **kw):
        settings = (task or {}).get("настройки") or {}
        rules = settings.get("автопроверка")
        if not isinstance(rules, list) or not rules:
            return None
        marks = []
        passed = total = 0.0
        for r in rules:
            if not isinstance(r, dict):
                continue
            key = str(r.get("field") or r.get("ключ") or "")
            if not key:
                continue
            ok = _check((answers or {}).get(key, ""), r)
            try:
                w = float(r.get("вес", 1) or 1)
            except (TypeError, ValueError):
                w = 1.0
            passed += w if ok else 0.0
            total += w
            marks.append((str(r.get("вопрос") or key), ok))
        if not total:
            return None
        all_ok = passed >= total - 1e-9
        score = round(100.0 * passed / total, 1)
        verdict = ("Тест пройден (автопроверка)" if all_ok
                   else "Тест: %d из %d верно"
                   % (round(passed), round(total)))
        comment = "Проверка: " + " · ".join(
            "%s %s" % (lbl, "✔" if ok else "✘") for lbl, ok in marks)
        return {"verdict": verdict, "score": score,
                "status": "принято" if all_ok else "доработка",
                "comment": comment}

    ctx.on("grade", grade)
    ctx.log("загружен: автотест (правила в настройках заданий)")
