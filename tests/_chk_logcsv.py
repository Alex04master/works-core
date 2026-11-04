# -*- coding: utf-8 -*-
import io
data = io.open("_log.csv", "rb").read()
assert data.startswith(b"\xef\xbb\xbf"), data[:10]
head = "время;кто;ip;действие;детали".encode("utf-8")
assert head in data, data[:120]
print("AUDIT CSV OK")
