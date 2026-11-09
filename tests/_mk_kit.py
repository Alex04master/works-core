# -*- coding: utf-8 -*-
"""Создать/удалить фейковый комплект для смоука: _mk_kit.py make|remove"""
import io
import os
import shutil
import sys
base = ""
for cand in (r"E:\AI\AI-projects\Сценарии для УП",
             r"D:\AI\AI-projects\Сценарии для УП",
             r"D:\AI\AI-projects\works-core\Сценарии для УП"):
    if os.path.isdir(cand):
        base = cand
        break
if not base:
    print("SKIP: папка «Сценарии для УП» не найдена (E:/D:)")
    sys.exit(0)
kit = os.path.join(base, "_smoketest_kit")
if sys.argv[1:] and sys.argv[1] == "remove":
    shutil.rmtree(kit, ignore_errors=True)
    print("kit removed")
    sys.exit(0)
os.makedirs(kit, exist_ok=True)
F = {
    "event.js": "window.EVENT={title:'SMOKE-KIT план',legend:["
                "{key:'smoke',label:'Smoke detector (IP)',shape:'circle',"
                "fill:'#fff',color:'#1a9e94',rule:'r'},"
                "{key:'ipr',label:'Manual call point',shape:'square',"
                "fill:'#fff',color:'#e11',planText:'M'}],stands:{}};",
    "cards.js": "window.CARDS=[{id:'SK-1',title:'Kit card',lvl:'1',"
                "story:'s',tasks:['t1'],criteria:[['c','100']],traps:[],stands:[]}];",
    "plans.js": "window.PLANS=[{id:'SK-1',title:'Plan',rooms:["
                "{n:'Room A',x:0,y:0,w:6,h:5,d:'6x5',s:'30'},"
                "{n:'Room B',x:6,y:0,w:4,h:5,d:'4x5',s:'20'}],"
                "dev:[{t:'smoke',x:3,y:2}],notes:['SMOKE-ETALON answer']}];",
    "02_Раздатка_студентам.html": "<!doctype html><meta charset='utf-8'><h1>SMOKE-KIT handout</h1>",
    "05_Планы_сооружений.html": "<!doctype html><meta charset='utf-8'><h1>SMOKE-KIT plans</h1>",
    "06_Условные_обозначения.html": "<!doctype html><meta charset='utf-8'><h1>SMOKE-KIT legend</h1>",
    "03_План_преподавателя.html": "<!doctype html><meta charset='utf-8'><h1>TEACHER ONLY</h1>",
}
for name, content in F.items():
    with io.open(os.path.join(kit, name), "w", encoding="utf-8") as f:
        f.write(content)
print("kit created")
