# -*- coding: utf-8 -*-
"""Браузерный тест панели «Офлайн-сдача»: фильтр студентов (курс/ФИО/группа).

Страница /staff/offline сохраняется на диск, в неё внедряется обвязка,
которая прогоняет сценарий фильтрации и пишет результат в document.title;
chrome --headless --dump-dom. Запуск — через _run_panelfilter.py.
"""
import http.cookiejar
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tests", "_browsertest")
BASE = os.environ.get("BASE", "http://localhost:8096")
_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)
CHROME = next((p for p in _CANDIDATES if os.path.exists(p)), "")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

if not CHROME:
    print("PANEL FILTER SKIP: не найден Chrome/Edge")
    sys.exit(0)

cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
with op.open(BASE + "/_staff_login",
             urllib.parse.urlencode({"pass": "x"}).encode()):
    pass
with op.open(BASE + "/staff/offline") as r:
    page = r.read().decode("utf-8", "replace")

HARNESS = """
<script>
window.addEventListener('load',function(){
 function vis(){var n=0;var labs=document.querySelectorAll('label[data-fio]');
  for(var i=0;i<labs.length;i++)if(labs[i].style.display!=='none')n++;return n}
 function ev(el,t){el.dispatchEvent(new Event(t))}
 function chk(sid){var i=document.querySelector(
   'input[name=student][value="'+sid+'"]');return i?i.checked:null}
 var out=[];
 try{
  var q=document.getElementById('wc-sfio');
  var g=document.getElementById('wc-sgrp');
  var c=document.getElementById('wc-course');
  if(!q||!g||!c){document.title='RESULT:ERR:no controls';return}
  out.push('TOTAL:'+vis());
  q.value='иванов';ev(q,'input');
  out.push('FIO_IVANOV:'+vis());
  out.push('CNT:'+document.getElementById('wc-scount')
    .textContent.replace(/\\s+/g,' '));
  q.value='';ev(q,'input');
  g.value='П-22';ev(g,'change');
  out.push('GRP_P22:'+vis());
  g.value='';ev(g,'change');
  document.querySelector('input[name=student][value="s1"]').checked=true;
  document.querySelector('input[name=student][value="s3"]').checked=true;
  c.value='c2';ev(c,'change');
  out.push('C2_VIS:'+vis());
  out.push('C2_S1:'+chk('s1'));
  out.push('C2_S3:'+chk('s3'));
  c.value='c1';ev(c,'change');
  out.push('C1_S3:'+chk('s3'));
  out.push('C1_S1:'+chk('s1'));
  document.title='RESULT:'+out.join('|');
 }catch(e){out.push('ERR:'+(e&&(e.message||e)));
   document.title='RESULT:'+out.join('|')}
});
</script>
</body>"""

shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(OUT, exist_ok=True)
p = os.path.join(OUT, "panel_test.html")
with open(p, "w", encoding="utf-8") as f:
    f.write(page.replace("</body>", HARNESS, 1))
r = subprocess.run(
    [CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
     "--virtual-time-budget=5000", "--dump-dom",
     "file:///" + p.replace("\\", "/")],
    capture_output=True, timeout=90)
dom = r.stdout.decode("utf-8", "replace")
m = re.search(r"<title>(.*?)</title>", dom, re.S)
res = m.group(1) if m else "NO TITLE"
print("PANEL:", res)

want = {
    "TOTAL": "4",
    "FIO_IVANOV": "1",
    "CNT": "· показано 1 из 4",
    "GRP_P22": "2",
    "C2_VIS": "1",
    "C2_S1": "false",
    "C2_S3": "true",
    "C1_S3": "true",
    "C1_S1": "false",
}
parts = dict(x.split(":", 1) for x in res.replace("RESULT:", "", 1).split("|")
             if ":" in x)
bad = []
for k, v in want.items():
    got = parts.get(k, "?")
    if v not in got:
        bad.append("%s=%s (ожидалось %s)" % (k, got, v))
if bad or not res.startswith("RESULT:"):
    print("PANEL FILTER FAIL:", "; ".join(bad) or res)
    sys.exit(1)
print("PANEL FILTER OK (%d проверок)" % len(want))
