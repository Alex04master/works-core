# -*- coding: utf-8 -*-
"""Проверка CSV-экспорта: BOM + непустой журнал."""
import io

src = io.open("_exp.csv", "rb").read()
assert src.startswith(b"\xef\xbb\xbf"), "нет UTF-8 BOM"
text = src.decode("utf-8-sig")
assert ";" in text, "нет разделителя"
assert text.count("\n") >= 2, "журнал пуст"
print("EXPORT CSV OK")
