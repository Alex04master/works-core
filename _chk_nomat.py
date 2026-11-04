# -*- coding: utf-8 -*-
"""0 = блок «Материалы» скрыт; 1 = блок найден (провал)."""
import io, sys
d = io.open("_tmp_page.html", encoding="utf-8", errors="replace").read()
sys.exit(0 if "<h2>Материалы</h2>" not in d else 1)
