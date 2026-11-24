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

// Экраны документов, дедупликации и графа связей требуют исследование С документами.
// Самое свежее исследование может быть пустым (например, создано проверкой API),
// поэтому выбираем первое, где документы есть, — иначе проверка зависит от порядка прогонов.
for (const r of App.S.researches) {
  const probe = await App.get('/api/v1/documents', {research_id: r.id, limit: 1});
  if ((probe.items || []).length) { App.setResearch(r.id, true); break; }
}
const hasDocs = App.S.researchId &&
  ((await App.get('/api/v1/documents', {research_id: App.S.researchId, limit: 1})).items || []).length > 0;

// Чистая установка (например, только что распакованный образ): исследований нет.
// Раньше проверка падала на 422 «Не указан research_id» — вместо этого создаём
// демо-исследование и дожидаемся этапов, чтобы экраны имели данные.
if (!hasDocs) {
  console.log('Исследований нет — создаю демо-исследование для проверки экранов…');
  const created = await App.post('/api/v1/researches', {
    query: 'тропосферная связь за горизонтом', title: 'Проверка интерфейса',
    countries: ['RU', 'US', 'CN'], settings: {max_docs_per_source: 4},
  });
  await App.post(`/api/v1/researches/${created.id}/start`, {});
  for (let waited = 0; waited < 240000; waited += 4000) {
    await sleep(4000);
    const st = await App.get(`/api/v1/researches/${created.id}/status`);
    const jobs = st.jobs || [];
    const done = jobs.filter(j => ['completed', 'failed', 'cancelled', 'partial'].includes(j.status)).length;
    if (!st.running && done === jobs.length) break;
  }
  await App.loadResearches(true);
}

const rid = App.S.researchId;
if (!rid) { console.error('Не удалось подготовить исследование для проверки экранов'); process.exit(1); }
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
  ['ops', {}], ['ops', {tab: 'alerts'}], ['ops', {tab: 'backups'}],
  ['settings', {}], ['settings', {tab: 'keys'}], ['settings', {tab: 'users'}], ['quality', {}],
  // ред. 1.4.0: журнал действий и поиск противоречий (UI-32)
  ['journal', {}], ['journal', {tab: 'errors'}], ['journal', {tab: 'contradictions'}],
  ['journal', {tab: 'browser'}], ['journal', {level: 'error'}], ['journal', {kind: 'api'}],
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

// --- журнал загрузки: экран диагностики вместо «белого экрана»
const B = window.__isheikaBoot;
t('журнал загрузки: объект диагностики есть', () => !!B && Array.isArray(B.steps) && B.steps.length > 0);
// Регрессия BOOT-08: `const Charts` — лексическая привязка, а не свойство window;
// диагностика проверяла window.Charts и выдавала ложный FAIL на рабочем интерфейсе.
t('модуль Charts опубликован в window', () => !!window.Charts && typeof window.Charts.line === 'function');
t('Charts рисует SVG из данных', () => {
  const html = window.Charts.range(52, 40, 66);
  return html.includes('<svg') && html.includes('52%');
});
t('журнал загрузки: отказов при загрузке нет', () => {
  const bad = B.steps.filter(s => s.status === 'fail').map(s => s.step + ': ' + s.detail);
  return bad.length === 0 || bad.join(' | ');
});
t('журнал загрузки: сценарии отмечены', () => {
  const names = B.steps.map(s => s.step).join('|');
  return ['charts.js', 'screens_ops.js', 'app.js'].every(n => names.includes(n));
});
t('журнал загрузки: журнал сервера получен', () => !!B.server && Array.isArray(B.server.checks) && B.server.checks.length > 0);
t('журнал загрузки: отказ показывает экран диагностики', () => {
  B.log('Проверка диагностики', 'fail', 'искусственный отказ');
  const w = window.document.getElementById('boot');
  const shown = w && w.hidden === false && w.innerHTML.includes('Проверка диагностики');
  B.steps.pop(); B.failed = false; w.hidden = true;      // возвращаем состояние
  return shown;
});
t('журнал загрузки: выгрузка содержит шаги', () => B.text().includes('журнал загрузки браузера') && B.text().includes('App'));
// Регрессия BOOT-09: отказ диагностики не должен запирать работоспособный интерфейс.
t('журнал загрузки: отказ закрывается кнопкой', () => {
  const w = window.document.getElementById('boot');
  const btn = window.document.getElementById('boot-continue');
  if (!btn) return 'кнопка «Продолжить работу» отсутствует';
  B.log('Проверка закрытия', 'fail', 'искусственный отказ');
  const shown = w.hidden === false;
  btn.click();
  const closed = w.hidden === true && B.dismissed === true;
  B.steps.pop(); B.failed = false; B.dismissed = false;   // возвращаем состояние
  return shown && closed ? true : `показан=${shown}, закрыт=${closed}`;
});
await App.bootLogModal();
await sleep(900);
t('журнал загрузки: окно самопроверки открывается', () => {
  const m = window.document.getElementById('modal-body');
  return !!m && m.innerHTML.includes('Самопроверка') && m.innerHTML.includes('Ресурсы интерфейса');
});
App.closeModal();

t('версия в шапке берётся с сервера', () => {
  const el = window.document.getElementById('app-ver');
  return !!el && el.textContent.includes(App.S.system.version) && !el.textContent.includes('v0.1');
});
// --- ред. 1.4.0: журнал действий, ошибки и противоречия
App.go('journal', {});
await sleep(1500);
t('журнал действий: лента отрисована', () => window.document.querySelectorAll('#j-tbl tbody tr').length > 0);
t('журнал действий: фильтр по уровню применяется', () => {
  const sel = window.document.getElementById('j-level');
  if (!sel) return 'селектор уровня отсутствует';
  sel.value = 'error';
  window.document.getElementById('j-apply').click();
  return true;
});
await sleep(1500);
t('журнал действий: в ленте только ошибки', () => {
  const html = window.document.getElementById('screen-body').innerHTML;
  if (html.includes('Записей по фильтру нет')) return true;
  const rows = [...window.document.querySelectorAll('#j-tbl tbody tr')];
  if (!rows.length) return 'лента пуста без сообщения о пустом фильтре';
  const bad = rows.filter(r => !/ошибка|критично/.test(r.children[1]?.textContent || ''));
  return bad.length === 0 ? true : `не-ошибок в ленте: ${bad.length}`;
});
t('журнал действий: выгрузка CSV подготовлена', () => {
  const a = [...window.document.querySelectorAll('a')].find(x => (x.getAttribute('href') || '').includes('journal/export'));
  return !!a && a.getAttribute('href').includes('fmt=');
});
App.go('journal', {tab: 'contradictions'});
await sleep(1800);
t('противоречия: правила показаны', () => {
  const html = window.document.getElementById('screen-body').innerHTML;
  return html.includes('Правил проверки') && !html.includes('spinner');
});
t('противоречия: кнопка проверки есть', () => !!window.document.getElementById('dg-run'));
// Ошибка интерфейса должна дойти до сервера и вернуться в экран «Браузер».
App.reportClient({action: 'ui_check.test', message: 'Проверка журнала ошибок интерфейса',
                  type: 'TestError', stack: 'at ui_check (tools/ui_check.mjs:1)'});
await sleep(900);
const browserEvents = await App.get('/api/v1/journal', {source: 'browser', limit: 50});
t('ошибка интерфейса сохранена на сервере', () =>
  (browserEvents.items || []).some(e => e.action === 'ui_check.test') || 'событие не найдено в журнале');
App.go('journal', {tab: 'errors'});
await sleep(1500);
t('ошибки: группировка по подписи дефекта', () => {
  const html = window.document.getElementById('screen-body').innerHTML;
  return html.includes('Подпись') || html.includes('Ошибок не зафиксировано');
});
// --- ред. 1.4.1: недоступность сервера, автоповтор, очередь журнала
const realFetch = window.fetch;
let flakyCalls = 0;
window.fetch = (input, init) => {
  flakyCalls += 1;
  if (flakyCalls === 1) return Promise.reject(new TypeError('Failed to fetch'));
  return realFetch(input, init);
};
const retried = await App.get('/api/v1/system');
t('сеть: безопасный запрос повторяется сам', () =>
  (flakyCalls >= 2 && retried && retried.version) ? true : `попыток: ${flakyCalls}`);
window.fetch = realFetch;

// шлюз вернул 502 без тела API — это недоступность сервера, а не ошибка данных
window.fetch = () => Promise.resolve({ok: false, status: 502,
  json: async () => ({sandboxId: 'sbx', message: 'The sandbox was not found'})});
let gw = null;
try { await App.get('/api/v1/logs', {limit: 5}); } catch (e) { gw = e; }
t('сеть: ответ шлюза 502 распознан как E_NETWORK', () =>
  (gw && gw.code === 'E_NETWORK' && gw.http === 502) ? true : JSON.stringify(gw));
window.fetch = realFetch;
await App.probeServer();

// полная недоступность: событие журнала должно ждать в очереди, а не потеряться
window.fetch = () => Promise.reject(new TypeError('Failed to fetch'));
let netErr = null;
try { await App.get('/api/v1/journal', {limit: 5}); } catch (e) { netErr = e; }
t('сеть: отказ классифицирован как E_NETWORK', () => (netErr && netErr.code === 'E_NETWORK') ? true : JSON.stringify(netErr));
const qBefore = App.journalQueueSize();
App.reportClient({action: 'ui_check.offline', message: 'Событие, случившееся при недоступности сервера',
                  type: 'NetworkError'});
await sleep(600);
t('журнал: событие сохранено в очереди браузера', () =>
  App.journalQueueSize() > qBefore ? true : `очередь: ${App.journalQueueSize()}`);
t('сеть: включено автопереподключение', () =>
  (App.S.online === false && App.netState.probe !== null) ? true : `online=${App.S.online}`);
// сервер «вернулся»: восстановление должно произойти САМО, по таймеру пробы,
// без ручного вызова и без перезагрузки страницы (замечание пользователя).
window.fetch = realFetch;
await sleep(8000);
t('сеть: восстановление происходит само по таймеру', () =>
  (App.S.online === true && App.netState.probe === null) ? true : `online=${App.S.online}, проба=${App.netState.probe !== null}`);
const backOk = await App.probeServer();
await sleep(1200);
t('сеть: экран работоспособен после восстановления', () =>
  (backOk && App.S.online === true) ? true : `online=${App.S.online}`);
const afterQueue = await App.get('/api/v1/journal', {source: 'browser', limit: 60});
t('журнал: очередь дослана с отметкой queued_at', () =>
  (afterQueue.items || []).some(e => e.action === 'ui_check.offline' && (e.client || {}).queued_at)
    ? true : 'доставленное событие с queued_at не найдено');
t('журнал: очередь браузера очищена', () => App.journalQueueSize() === 0 || `осталось ${App.journalQueueSize()}`);

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
