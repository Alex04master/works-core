# -*- coding: utf-8 -*-
"""Реальный браузерный тест бланков: headless Chrome.

Для каждого бланка: копия + обвязка (заполнить поля -> validate ->
save) -> document.title = RESULT:...; chrome --headless --dump-dom.
"""
import http.cookiejar
import io
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile

ROOT = r"D:\AI\AI-projects\works-core"
OUT = os.path.join(ROOT, "tests", "_browsertest")
BASE = "http://localhost:8095"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(OUT)

cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def get(p):
    with op.open(BASE + p) as r:
        return r.read().decode("utf-8", "replace")


def post(p, fields):
    with op.open(BASE + p, urllib.parse.urlencode(fields).encode()) as r:
        return r.read().decode("utf-8", "replace")


def fetch_blob(p, fields=None):
    data = urllib.parse.urlencode(fields).encode() if fields else None
    req = urllib.request.Request(BASE + p, data=data)
    with op.open(req) as r:
        return r.read()


post("/_login", {"student": "s1", "next": "/"})
post("/_staff_login", {"pass": "x"})

blanks = {}
blanks["student"] = get("/offline/blank/t1")
zb = fetch_blob("/offline/blanki.zip", {"mode": "all"})
z = zipfile.ZipFile(io.BytesIO(zb))
name = z.namelist()[0]
blanks["bulk-zip"] = z.read(name).decode("utf-8-sig")
zs = fetch_blob("/staff/offline/blanks/l1")
z2 = zipfile.ZipFile(io.BytesIO(zs))
name2 = z2.namelist()[0]
blanks["staff-anon"] = z2.read(name2).decode("utf-8-sig")

HARNESS = """
<script>
window.alert=function(m){};
window.addEventListener('load',function(){
 var out=[];
 try{
  var els=document.querySelectorAll('[data-key]');
  for(var i=0;i<els.length;i++){var el=els[i];
    var t=el.getAttribute('data-type');
    if(t==='file'||t==='firmware'||t==='shlei'||t==='checkboxes'
       ||t==='radio'||t==='checkbox')continue;
    if(el.tagName==='SELECT'){if(el.options.length>1)el.selectedIndex=1;
      continue;}
    el.value='1';}
  var tbl=document.querySelector('table.sl');
  if(tbl){var ins=tbl.querySelectorAll('tr[data-row="0"] input');
    for(var j=0;j<ins.length;j++)ins[j].value='x';}
  var fio=document.getElementById('bf_fio');
  if(fio)fio.value='Тестов Тест Тестович';
  var cb=document.querySelector('[data-type="checkboxes"]');
  if(cb)cb.checked=true;
  var rd=document.querySelector('[data-type="radio"]');
  if(rd)rd.checked=true;
  var errs=validate();
  out.push('VALIDATE:'+errs.length+(errs.length?':'+errs.join(','):''));
  HTMLAnchorElement.prototype.click=function(){};
  save();
  setTimeout(function(){
    var m=document.getElementById('svmsg');
    out.push('SAVE:'+((m&&m.textContent)?'OK('+m.textContent+')':'?'));
    document.title='RESULT:'+out.join('|');
  },120);
 }catch(e){out.push('ERR:'+(e&&(e.message||e)))}
});
</script>
</body>"""

results = {}
for key, html in blanks.items():
    p = os.path.join(OUT, key + "_test.html")
    with open(p, "w", encoding="utf-8") as f:
        f.write(html.replace("</body>", HARNESS, 1))
    r = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
         "--virtual-time-budget=5000", "--dump-dom",
         "file:///" + p.replace("\\", "/")],
        capture_output=True, timeout=90)
    dom = r.stdout.decode("utf-8", "replace")
    m = re.search(r"<title>(.*?)</title>", dom, re.S)
    results[key] = (m.group(1) if m else "NO TITLE")
    print("%-12s -> %s" % (key, results[key]))

allok = all(v.startswith("RESULT:VALIDATE:0|SAVE:OK") for v in results.values())
print("BROWSER BLANKS", "OK" if allok else "FAIL")
