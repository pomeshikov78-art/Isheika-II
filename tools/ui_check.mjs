/* TOOL-04. Проверка интерфейса в DOM (jsdom) против живого сервера.
 *
 *   npm install jsdom            # единственная dev-зависимость, в рантайме не нужна
 *   node tools/ui_check.mjs --base http://127.0.0.1:8000
 *
 * Загружает index.html со всеми скриптами, входит в систему и последовательно
 * открывает все экраны UI-01…UI-26 (включая вкладки), проверяя отсутствие
 * ошибок рендеринга, состояний error/permission_denied и «зависших» спиннеров.
 */
import {JSDOM, VirtualConsole} from 'jsdom';

const arg = (n, d) => { const i = process.argv.indexOf('--' + n); return i > 0 ? process.argv[i + 1] : d; };
const BASE = arg('base', 'http://127.0.0.1:8000');
const LOGIN = arg('login', 'analyst');
const PASS = arg('password', 'dev:' + LOGIN);

const errors = [];
const vc = new VirtualConsole();
vc.on('jsdomError', e => errors.push('jsdomError: ' + (e.message || e)));
vc.on('error', (...a) => errors.push('console.error: ' + a.join(' ')));

const dom = await JSDOM.fromURL(BASE + '/', {
  runScripts: 'dangerously', resources: 'usable', virtualConsole: vc, pretendToBeVisual: true,
});
const {window} = dom;
window.fetch = (input, init) => fetch(new URL(input, BASE), init);
window.EventSource = class { constructor(u) { this.url = u; setTimeout(() => this.onopen && this.onopen(), 0); } close() {} };
window.addEventListener('error', e => errors.push('window.error: ' + (e.error?.stack || e.message)));
window.addEventListener('unhandledrejection', e => errors.push('unhandledrejection: ' + JSON.stringify(e.reason)));

const sleep = ms => new Promise(r => setTimeout(r, ms));
await new Promise(r => window.addEventListener('load', r, {once: true}));
await sleep(300);

const App = window.App;
if (!App) { console.error('App не инициализирован'); process.exit(1); }
await App.api('/api/v1/auth/login', {method: 'POST', body: {login: LOGIN, password: PASS}})
  .then(d => { App.S.token = d.token; App.S.user = d.user; App.S.rights = new Set(d.user.rights); });
window.localStorage.setItem('isheika.token', App.S.token);
await App.refreshSystem();
await App.loadResearches(true);
window.document.getElementById('login').hidden = true;
window.document.getElementById('app').hidden = false;

const rid = App.S.researchId;
const docs = await App.get('/api/v1/documents', {research_id: rid, limit: 1});
const did = docs.items?.[0]?.id;

const routes = [
  ['dashboard', {}], ['researches', {}], ['research', {id: rid}], ['new', {}], ['query', {}],
  ['results', {}], ['results', {tab: 'cards'}], ['results', {tab: 'duplicates'}],
  ['document', {id: did}],
  ['ai', {}], ['ai', {tab: 'providers'}], ['ai', {tab: 'agents'}], ['ai', {tab: 'tasks'}],
  ['passport', {}], ['passport', {tab: 'ident'}], ['passport', {tab: 'graph'}],
  ['trl', {}], ['feasibility', {}],
  ['science', {}], ['patents', {}], ['industry', {}], ['compare', {}],
  ['barriers', {}], ['alternatives', {}], ['trends', {}],
  ['forecast', {}], ['forecast', {tab: 'scenarios'}], ['forecast', {tab: 'table'}],
  ['consensus', {}], ['consensus', {tab: 'critic'}], ['evidence', {}],
  ['report', {}], ['report', {tab: 'export'}],
  ['sources', {}], ['countries', {}], ['monitor', {}], ['logs', {}],
  ['settings', {}], ['settings', {tab: 'keys'}], ['settings', {tab: 'users'}], ['quality', {}],
  // экраны редакции v1.1 (ИД-03, ИД-09, ИД-11, ИД-12)
  ['methodologies', {}], ['methodologies', {code: 'FEASIBILITY_V1'}],
  ['independence', {}], ['dedup', {}], ['dedup', {tab: 'graph'}],
  ['reproducibility', {}], ['reproducibility', {tab: 'versions'}], ['reproducibility', {tab: 'replay'}],
];

let pass = 0;
const report = [];
for (const [route, params] of routes) {
  const before = errors.length;
  App.go(route, params);
  const body = () => window.document.getElementById('screen-body');
  let waited = 0;
  while (waited < 15000) {
    await sleep(120); waited += 120;
    const b = body();
    if (b && !b.querySelector('.spinner') && b.innerHTML.length > 40) break;
  }
  await sleep(250);
  const html = body()?.innerHTML || '';
  const newErrors = errors.slice(before);
  const bad = [];
  if (!html || html.length < 60) bad.push('пустой экран');
  if (html.includes('spinner')) bad.push('не завершилась загрузка');
  if (/Ошибка E_/.test(html)) bad.push('состояние error: ' + (html.match(/Ошибка (E_\w+)/) || [])[1]);
  if (html.includes('Экран не найден')) bad.push('экран не найден');
  if (html.includes('Доступ запрещён')) bad.push('permission_denied');
  if (newErrors.length) bad.push(...newErrors.slice(0, 2));
  const ok = bad.length === 0;
  pass += ok ? 1 : 0;
  const label = route + (params.tab ? ':' + params.tab : '') + (params.id && route !== 'document' ? '' : '');
  report.push(`${ok ? 'OK  ' : 'FAIL'} ${label.padEnd(26)} ${String(html.length).padStart(7)} байт  ${bad.join(' | ')}`);
}
console.log(report.join('\n'));

// Дополнительные проверки интерактива
const extra = [];
const t = (name, fn) => { try { const r = fn(); extra.push([!!r, name, r === true ? '' : String(r).slice(0, 90)]); } catch (e) { extra.push([false, name, e.message]); } };
App.go('sources', {});
await sleep(1200);
t('таблица источников отрисована', () => window.document.querySelectorAll('#src-tbl tbody tr').length > 0);
t('сортировка по клику на заголовок', () => {
  const th = window.document.querySelector('#src-tbl th[data-sort]'); th.click();
  return window.document.querySelectorAll('#src-tbl tbody tr').length > 0;
});
t('экспорт CSV создаёт ссылку', () => {
  let created = false;
  const orig = window.URL.createObjectURL, origRevoke = window.URL.revokeObjectURL;
  window.URL.createObjectURL = () => { created = true; return 'blob:test'; };
  window.URL.revokeObjectURL = () => {};          // в jsdom не реализовано
  window.document.querySelector('#src-tbl [data-act="csv"]').click();
  window.URL.createObjectURL = orig;
  setTimeout(() => { window.URL.revokeObjectURL = origRevoke; }, 1500);
  return created;
});
App.go('new', {});
await sleep(1200);
t('кнопка «Выбрать все страны» включает все', () => {
  const boxes = [...window.document.querySelectorAll('#f-countries input')];
  boxes.forEach(b => { b.checked = false; b.parentElement.classList.remove('on'); });
  window.document.getElementById('btn-all-countries').click();
  return boxes.every(b => b.checked);
});
t('повторное нажатие снимает выбор', () => {
  window.document.getElementById('btn-all-countries').click();
  return [...window.document.querySelectorAll('#f-countries input')].every(b => !b.checked);
});
// --- P4: граф связей документов (UI-30)
App.go('dedup', {tab: 'graph'});
await sleep(1500);
t('граф связей: SVG отрисован', () => window.document.querySelectorAll('#dd-box svg.chart').length > 0);
t('граф связей: фильтр типов присутствует', () => window.document.getElementById('gr-apply') !== null);
t('граф связей: узлы ведут на карточку документа', () => {
  const a = window.document.querySelector('#dd-box svg a.gnode');
  return !a || (a.getAttribute('href') || '').startsWith('#/document/');
});

// --- P4: сравнение версий расчётов (UI-29)
App.go('reproducibility', {tab: 'versions'});
await sleep(1800);
t('сравнение версий: элементы выбора есть', () => window.document.getElementById('df-run') !== null);
const diffRun = window.document.getElementById('df-run');
if (diffRun) { diffRun.click(); await sleep(1800); }
t('сравнение версий: результат сравнения отображён', () => {
  const out = window.document.getElementById('df-out');
  return !!out && (out.querySelectorAll('#df-deltas tbody tr').length > 0 || /Нет двух записей/.test(out.innerHTML));
});

// --- P6: сквозная трассировка (UI-24)
const ev = await App.get('/api/v1/events', {research_id: rid, limit: 30});
const cid = (ev.items || []).find(e => e.correlation_id)?.correlation_id;
if (cid) {
  App.go('logs', {cid});
  await sleep(1500);
  t('трассировка: экран открыт по correlation_id', () => {
    const h = window.document.getElementById('screen-body').innerHTML;
    return h.includes(cid.slice(0, 14)) && !h.includes('spinner');
  });
} else {
  extra.push([false, 'трассировка: события с correlation_id', 'нет событий с трассировкой']);
}

App.setTheme('dark');
t('тёмная тема применяется', () => window.document.documentElement.dataset.theme === 'dark');
App.setTheme('light');
console.log(extra.map(([ok, n, note]) => `${ok ? 'OK  ' : 'FAIL'} ${n.padEnd(40)} ${note}`).join('\n'));

const total = routes.length + extra.length;
const passed = pass + extra.filter(e => e[0]).length;
console.log(`\nИтого: ${passed}/${total} проверок интерфейса пройдено`);
if (errors.length) console.log('\nОшибки консоли:\n' + errors.slice(0, 12).join('\n'));
dom.window.close();
process.exit(passed === total ? 0 : 1);
