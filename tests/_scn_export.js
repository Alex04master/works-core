// Экспорт данных комплекта сценариев в JSON (как делает браузер на странице импорта).
const fs = require('fs'), vm = require('vm'), path = require('path');
const kitDir = 'D:/AI/AI-projects/Сценарии для УП/Больница_день_ОПС';
const kit = 'Больница_день_ОПС';
const c = {}; c.window = c; vm.createContext(c);
['event.js', 'cards.js'].forEach(f => vm.runInContext(
  fs.readFileSync(path.join(kitDir, f), 'utf8'), c, {filename: f}));
const EV = c.window.EVENT, CARDS = c.window.CARDS;
const out = {
  course: 'c1',
  kit: kit,
  event: {title: EV.title, place: EV.place, stands: EV.stands},
  cards: CARDS.map(x => ({
    id: x.id, title: x.title, lvl: x.lvl, time: x.time, team: x.team,
    role: x.role, story: x.story, obj: x.obj, data_table: x.data_table,
    tasks: x.tasks, given: x.given, criteria: x.criteria,
    traps: x.traps, stands: x.stands
  }))
};
fs.writeFileSync('_scn_real.json', JSON.stringify(out), 'utf8');
console.log('cards exported:', CARDS.length, '| title:', String(EV.title).replace(/<[^>]+>/g, ''));
