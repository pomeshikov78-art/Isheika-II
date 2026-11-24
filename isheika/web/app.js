/* ИЩЕЙКА НТР AI — клиент приложения (ТЗ-04).
   Принципы: научные показатели НЕ пересчитываются в браузере — только отображение
   серверных значений с версией методики; все состояния экрана явные; цвет не единственный
   носитель смысла; таблицы и графики имеют экспорт и текстовые альтернативы. */
window.Screens = window.Screens || {};

const App = (() => {
  // ---------------------------------------------------------------- утилиты
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const uid = p => (p || 'id-') + Math.random().toString(36).slice(2, 10);
  const num = (v, d = 0) => v == null || v === '' || Number.isNaN(Number(v)) ? '—' : Number(v).toFixed(d);
  const pct = (v, d = 0) => v == null ? '—' : (Number(v) * 100).toFixed(d) + ' %';
  const dt = s => !s ? '—' : String(s).replace('T', ' ').slice(0, 19);
  const donly = s => !s ? '—' : String(s).slice(0, 10);
  const short = (s, n = 120) => { s = String(s == null ? '' : s); return s.length > n ? s.slice(0, n) + '…' : s; };
  const $ = id => document.getElementById(id);
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  // Хранилище браузера может быть недоступно (приватный режим, песочница iframe) —
  // приложение обязано работать и без него.
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* без сохранения */ } },
    del(k) { try { localStorage.removeItem(k); } catch (e) { /* noop */ } },
  };

  const S = {
    token: store.get('isheika.token') || '',
    user: null, rights: new Set(), system: null,
    researchId: store.get('isheika.rid') || '',
    research: null, countries: null, researches: [],
    online: true, route: null, params: {}, notifications: [], unread: 0,
    sse: null, sseOk: false, lastSync: null, jobsRunning: 0, theme: store.get('isheika.theme') || 'light',
  };

  // ---------------------------------------------------------------- состояние связи (ред. 1.4.1)
  /* Недоступность сервера — не конец работы: сервер может перезапускаться или
     быть недоступен минуту (замечание пользователя: E_NETWORK на UI-24 и UI-32,
     экраны оставались «недоступны» до перезагрузки страницы). Теперь:
       * безопасные запросы повторяются сами (3 попытки с паузами);
       * ответы шлюза 502/503/504 без тела API считаются недоступностью, а не ошибкой данных;
       * при отказе включается автопереподключение, и после ответа сервера экран
         перерисовывается сам;
       * события журнала, не доставленные во время отказа, ждут в localStorage
         и досылаются после восстановления (раньше они терялись навсегда). */
  const NET = {tries: 0, probe: null, delay: 4000, wasOffline: false, lastError: '', unloading: false};
  /* ИД-21: при перезагрузке/закрытии вкладки браузер отменяет все незавершённые
     запросы. Раньше каждая отмена попадала в журнал как «Сервер недоступен»
     (E_NETWORK) и переводила приложение в offline — выгрузка журнала с машины
     пользователя содержала ~50 таких ложных отказов за одну секунду, при том что
     сервер в ту же секунду отвечал на POST /journal/client за 0.2 мс. */
  window.addEventListener('pagehide', () => { NET.unloading = true; });
  window.addEventListener('beforeunload', () => { NET.unloading = true; });
  window.addEventListener('pageshow', () => { NET.unloading = false; });
  const QUEUE_KEY = 'isheika.journal.queue';
  const QUEUE_MAX = 50;
  const queueRead = () => { try { return JSON.parse(store.get(QUEUE_KEY) || '[]') || []; } catch (e) { return []; } };
  const queueWrite = list => store.set(QUEUE_KEY, JSON.stringify((list || []).slice(-QUEUE_MAX)));
  function queuePush(payload) { const l = queueRead(); l.push(payload); queueWrite(l); paintConn(); }
  const journalQueueSize = () => queueRead().length;

  async function flushJournal() {
    const list = queueRead();
    if (!list.length) return 0;
    const rest = []; let sent = 0;
    for (const p of list) {
      try {
        const headers = {'Content-Type': 'application/json'};
        if (S.token) headers['Authorization'] = 'Bearer ' + S.token;
        const body = JSON.stringify(Object.assign({}, p, {queued_at: p.queued_at || new Date().toISOString()}));
        const r = await fetch('api/v1/journal/client', {method: 'POST', headers, body, keepalive: true});
        if (r && r.ok) { sent += 1; continue; }
        if (r && (r.status === 422 || r.status === 429)) continue;   // битое или лишнее событие не держим
        rest.push(p);
      } catch (e) { rest.push(p); }
    }
    queueWrite(rest); paintConn();
    return sent;
  }

  async function probeServer() {
    try {
      const r = await fetch('api/v1/system', {headers: {'Accept': 'application/json'}, cache: 'no-store'});
      if (r && r.ok) { markOnline(); return true; }
    } catch (e) { /* сервер ещё недоступен */ }
    return false;
  }
  function startProbe() {
    if (NET.probe) return;
    const tick = async () => {
      NET.probe = null;
      const ok = await probeServer();
      if (!ok && !S.online) {
        NET.tries += 1;
        NET.delay = Math.min(15000, 4000 + NET.tries * 1000);
        NET.probe = setTimeout(tick, NET.delay);
        paintConn();
      }
    };
    NET.probe = setTimeout(tick, NET.delay);
  }
  function stopProbe() { if (NET.probe) { clearTimeout(NET.probe); NET.probe = null; } }
  function markOffline(reason) {
    NET.lastError = reason || NET.lastError;
    if (!S.online) { startProbe(); return; }
    S.online = false; NET.wasOffline = true; paintConn(); startProbe();
  }
  function markOnline() {
    const back = !S.online && NET.wasOffline;
    S.online = true; S.lastSync = new Date(); NET.tries = 0; NET.delay = 4000; NET.lastError = '';
    stopProbe(); paintConn();
    if (back) {
      NET.wasOffline = false;
      flushJournal().then(n => toast('Соединение восстановлено' +
        (n ? ': отправлено событий журнала — ' + n : '') + '. Экран обновлён.', 'ok'));
      if (S.route) render();
    }
  }
  window.addEventListener('online', () => probeServer());
  window.addEventListener('offline', () => markOffline('браузер сообщил об отсутствии сети'));

  // ---------------------------------------------------------------- API-клиент
  async function api(path, opts = {}) {
    const {method = 'GET', body, query, idem} = opts;
    const url = new URL(path, location.origin);
    Object.entries(query || {}).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v); });
    const rid = uid('req-');
    const headers = {'Accept': 'application/json', 'Accept-Language': 'ru', 'X-Request-ID': rid};
    if (S.token) headers['Authorization'] = 'Bearer ' + S.token;
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (idem) headers['Idempotency-Key'] = idem;
    if (S.researchId) headers['X-Correlation-ID'] = S.researchId;
    const limit = opts.timeout || 45000;
    // повтор допустим только для безопасных или идемпотентных запросов
    const safe = method === 'GET' || method === 'HEAD' || !!idem;
    const attempts = opts.attempts || (safe ? 3 : 1);
    const req = {method, headers, body: body !== undefined ? JSON.stringify(body) : undefined};
    let netErr = null;
    for (let attempt = 1; attempt <= attempts; attempt++) {
      if (attempt > 1) await sleep(600 * (attempt - 1) * (attempt - 1) + Math.round(Math.random() * 250));
      let res;
      const ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
      let timedOut = false;
      const timer = ctrl ? setTimeout(() => { timedOut = true; ctrl.abort(); }, limit) : null;
      try {
        res = await fetch(url.toString(), Object.assign({}, req, {signal: ctrl ? ctrl.signal : undefined}));
      } catch (e) {
        // ИД-21: отмена запроса — НЕ недоступность сервера. Отмену отличаем по
        // признаку AbortError и по тому, кто её вызвал: наш таймер (timedOut) —
        // это отказ ответа, выгрузка страницы или внешний abort — нет.
        const aborted = (e && e.name === 'AbortError') || (ctrl && ctrl.signal.aborted);
        if (aborted && !timedOut) {
          if (timer) clearTimeout(timer);
          throw {code: 'E_ABORTED', aborted: true, request_id: rid,
                 message: NET.unloading ? 'Запрос отменён: страница закрывается или перезагружается'
                                      : 'Запрос отменён (переход на другой экран)'};
        }
        const offlineByBrowser = typeof navigator !== 'undefined' && navigator.onLine === false;
        netErr = {code: 'E_NETWORK',
               message: timedOut ? 'Сервер не ответил за ' + Math.round(limit / 1000) + ' с: ' + path
                                 : (offlineByBrowser ? 'Браузер сообщает об отсутствии сети: ' + path
                                                     : 'Сервер недоступен. Проверьте соединение — данные могли устареть.'),
               request_id: rid, offline: true, attempts: attempt};
        markOffline(netErr.message);
        continue;
      } finally { if (timer) clearTimeout(timer); }
      let data = {};
      try { data = await res.json(); } catch (e) { data = {}; }
      // Ответ шлюза (502/503/504 без тела API) — недоступность сервера, а не ошибка данных.
      if ([502, 503, 504].includes(res.status) && !(data && data.error)) {
        netErr = {code: 'E_NETWORK', http: res.status, request_id: rid, offline: true, attempts: attempt,
                  message: 'Шлюз вернул HTTP ' + res.status + ': сервер не отвечает. Данные могли устареть.'};
        markOffline(netErr.message);
        continue;
      }
      markOnline();
      if (!res.ok) {
        const err = (data && data.error) || {code: 'E_INTERNAL', message: 'HTTP ' + res.status};
        err.http = res.status; err.request_id = err.request_id || rid;
        // В журнал — то, что похоже на дефект, а не на ожидаемый отказ прав/валидации.
        if (res.status >= 500 || ['E_INTERNAL', 'E_SCHEMA', 'E_PROVIDER'].includes(err.code)) {
          reportClient({action: 'api.' + method + ' ' + path, message: err.message, code: err.code,
                        type: 'ApiError', detail: {http: res.status, request_id: err.request_id}});
        }
        if (res.status === 401 && S.user) { toast('Сессия истекла — требуется повторный вход', 'warn'); logout(false); }
        throw err;
      }
      return data;
    }
    netErr = netErr || {code: 'E_NETWORK', message: 'Сервер недоступен: ' + path, request_id: rid, offline: true};
    if (NET.unloading) throw netErr;      // ИД-21: выгрузка страницы — не отказ сервера
    reportClient({action: 'api.' + method + ' ' + path, message: netErr.message, code: 'E_NETWORK',
                  type: netErr.http ? 'GatewayError' : 'NetworkError',
                  detail: {http: netErr.http || 0, attempts: netErr.attempts || attempts, request_id: rid}});
    throw netErr;
  }
  const get = (p, query) => api(p, {query});
  const post = (p, body, idem) => api(p, {method: 'POST', body: body || {}, idem});
  const del = p => api(p, {method: 'DELETE'});

  // ---------------------------------------------------------------- журнал действий (ред. 1.4.0)
  /* Ошибки интерфейса уходят на сервер: раньше они жили только в памяти вкладки
     и терялись при перезагрузке — найти дефект у пользователя было нечем.
     Отправка идёт напрямую через fetch (не через api), чтобы отказ самого
     журнала не порождал новую запись об отказе. */
  let jrnSent = 0;
  function reportClient(ev) {
    if (jrnSent >= 200) return;      // предохранитель от лавины; считаем только доставленные
    const payload = {
      level: ev.level || 'error', kind: ev.kind || 'ui', action: ev.action || 'browser.event',
      message: String(ev.message || '').slice(0, 1200),
      stack: ev.stack ? String(ev.stack).slice(0, 6000) : '',
      error_code: ev.code || '', error_type: ev.type || '',
      route: location.hash || '', screen: S.route || '', url: location.pathname,
      research_id: S.researchId || '', app_version: (S.system && S.system.version) || '',
      viewport: (window.innerWidth || 0) + 'x' + (window.innerHeight || 0),
      boot_id: (window.__isheikaBoot && window.__isheikaBoot.server && window.__isheikaBoot.server.boot_id) || '',
      detail: ev.detail || {},
    };
    // Отказ доставки НЕ отключает журнал: событие ждёт в очереди и уходит позже.
    try {
      const headers = {'Content-Type': 'application/json'};
      if (S.token) headers['Authorization'] = 'Bearer ' + S.token;
      const p = fetch('api/v1/journal/client', {method: 'POST', headers, keepalive: true,
                                               body: JSON.stringify(payload)});
      if (p && p.then) {
        p.then(r => {
          if (r && r.ok) { jrnSent += 1; return; }
          if (r && (r.status === 422 || r.status === 429)) return;   // брак/лимит — не копим
          queuePush(payload); markOffline('журнал не принял событие: HTTP ' + (r && r.status));
        }).catch(() => { queuePush(payload); markOffline('журнал недоступен'); });
      } else { jrnSent += 1; }
    } catch (e) { queuePush(payload); }
  }
  window.addEventListener('error', e => {
    if (e && e.target && e.target !== window && (e.target.src || e.target.href)) {
      reportClient({action: 'resource.load', message: 'Ресурс не загрузился: ' + (e.target.src || e.target.href),
                    type: 'ResourceError'});
      return;
    }
    reportClient({action: 'window.onerror', message: (e && e.message) || 'Ошибка сценария',
                  stack: (e && e.error && e.error.stack) || ((e && e.filename) + ':' + (e && e.lineno)),
                  type: (e && e.error && e.error.name) || 'Error'});
  }, true);
  window.addEventListener('unhandledrejection', e => {
    const r = (e && e.reason) || {};
    reportClient({action: 'unhandledrejection', message: r.message || String(r),
                  stack: r.stack || '', code: r.code || '', type: r.name || 'PromiseRejection'});
  });

  const can = right => S.rights.has('*') || S.rights.has(right);

  // ---------------------------------------------------------------- примитивы
  const tag = (text, cls = '') => `<span class="tag ${esc(cls)}">${esc(text)}</span>`;
  const STATUS_RU = {
    draft: 'черновик', queued: 'в очереди', running: 'выполняется', partial: 'частично',
    completed: 'завершено', failed: 'ошибка', cancelled: 'отменено', paused: 'пауза', ready: 'готово',
    active: 'активен', degraded: 'деградация', quota_exhausted: 'квота исчерпана', rate_limited: 'лимит частоты',
    auth_error: 'ошибка ключа', unavailable: 'недоступен', disabled: 'отключён', paid_blocked: 'платное заблокировано',
    policy_blocked: 'запрещено политикой', restricted: 'ограничен', not_implemented: 'не реализован',
    direct: 'прямое', adjacent: 'смежное', excluded: 'исключено',
    DIRECT: 'прямое соответствие', ADJACENT: 'смежная тема', BELOW_THRESHOLD: 'ниже порога',
    DISCOVERED: 'обнаружен', FETCHED: 'получен', EXTRACTED: 'извлечён', NORMALIZED: 'нормализован',
    FAILED: 'ошибка обработки', UNSUPPORTED: 'не поддерживается',
    PENDING: 'ожидает', UNIQUE: 'уникален', DUPLICATE: 'дубль', CLUSTERED: 'в кластере', REVIEW: 'на подтверждении',
    INCLUDE: 'включён', EXCLUDE: 'исключён', MANUAL_INCLUDE: 'включён вручную', MANUAL_EXCLUDE: 'исключён аналитиком',
    PRIMARY: 'первичный', INDEPENDENT_CONFIRMATION: 'независимое подтверждение', REPRINT: 'перепечатка',
    SUMMARY: 'пересказ', DERIVATIVE: 'производный', CONTRADICTORY: 'противоречащий',
    EXACT: 'точное значение', INTERVAL: 'интервал', COARSE: 'укрупнённо', SCENARIO: 'сценарий',
    PROVISIONAL: 'стартовая (не калибрована)', VALIDATED: 'валидирована', DEPRECATED: 'выведена',
    EXACT_DUPLICATE: 'точный дубль', ALTERNATIVE_HOSTING: 'другое размещение', PREPRINT_OF: 'препринт',
    PUBLISHED_VERSION_OF: 'опубликованная версия', REVISION_OF: 'редакция', TRANSLATION_OF: 'перевод',
    SUMMARY_OF: 'пересказ', CITES: 'цитирует',
    SUPPORTED: 'подтверждено', PARTIAL: 'частично', CONTRADICTED: 'опровергнуто',
    UNVERIFIED: 'не проверено', SUPERSEDED: 'устарело',
    CONNECTED: 'подключён', TESTED: 'протестирован', CANDIDATE: 'кандидат', UNAVAILABLE: 'недоступен', RESTRICTED: 'ограничен',
  };
  const STATUS_CLS = {
    completed: 'ok', active: 'ok', SUPPORTED: 'ok', CONNECTED: 'ok', direct: 'direct', ready: 'ok',
    DIRECT: 'direct', NORMALIZED: 'ok', EXTRACTED: 'ok', UNIQUE: 'ok', INCLUDE: 'ok', PRIMARY: 'ok',
    INDEPENDENT_CONFIRMATION: 'ok', VALIDATED: 'ok', MANUAL_INCLUDE: 'ok',
    ADJACENT: 'adjacent', FETCHED: 'adjacent', EXTRACTED_: 'adjacent', CLUSTERED: 'adjacent',
    DUPLICATE: 'warn', REVIEW: 'warn', PROVISIONAL: 'warn', REPRINT: 'warn', SUMMARY: 'warn',
    DERIVATIVE: 'warn', DISCOVERED: 'warn', PENDING: 'warn',
    BELOW_THRESHOLD: 'excluded', EXCLUDE: 'excluded', MANUAL_EXCLUDE: 'excluded',
    UNSUPPORTED: 'excluded', DEPRECATED: 'excluded', CONTRADICTORY: 'err',
    running: 'adjacent', adjacent: 'adjacent', partial: 'warn', degraded: 'warn', PARTIAL: 'warn',
    rate_limited: 'warn', quota_exhausted: 'warn', TESTED: 'warn', restricted: 'warn', RESTRICTED: 'warn',
    failed: 'err', CONTRADICTED: 'err', auth_error: 'err', unavailable: 'err', UNAVAILABLE: 'err',
    cancelled: 'excluded', excluded: 'excluded', disabled: 'excluded', UNVERIFIED: 'warn', SUPERSEDED: 'excluded',
  };
  const statusTag = st => tag((STATUS_RU[st] || st || '—') + (STATUS_CLS[st] === 'err' ? ' ✕' : STATUS_CLS[st] === 'ok' ? ' ✓' : STATUS_CLS[st] === 'warn' ? ' ⚠' : ''), STATUS_CLS[st] || '');
  const kpi = (label, val, sub = '') => `<div class="kpi"><div class="lbl">${esc(label)}</div><div class="val">${esc(val)}</div><div class="sub">${sub}</div></div>`;
  const card = (title, body, actions = '') => `<div class="card"><h3>${title}${actions ? `<span style="margin-left:auto" class="row">${actions}</span>` : ''}</h3>${body}</div>`;
  const alertBox = (kind, text) => `<div class="alert ${kind}">${text}</div>`;
  const kv = obj => `<div class="kv">${Object.entries(obj).map(([k, v]) => `<b>${esc(k)}</b><span>${v == null ? '—' : v}</span>`).join('')}</div>`;
  const spinner = t => `<div class="state"><span class="spinner"></span><div style="margin-top:10px">${esc(t || 'Загрузка…')}</div></div>`;
  const empty = (text, ico = '📭', hint = '') => `<div class="state"><span class="ico">${ico}</span>${esc(text)}${hint ? `<div class="tiny" style="margin-top:6px">${hint}</div>` : ''}</div>`;
  const denied = right => `<div class="state"><span class="ico">🔒</span>Доступ запрещён<div class="tiny" style="margin-top:6px">Роль «${esc(S.user ? S.user.role : '—')}» не имеет права <code>${esc(right || '')}</code>. Обратитесь к администратору.</div></div>`;
  const loading = host => { host.innerHTML = spinner(); };

  function errorBlock(e, ctx = {}) {
    const code = e && e.code || 'E_INTERNAL';
    // ИД-21: отменённый запрос (переход/перезагрузка) — не ошибка экрана.
    if (code === 'E_ABORTED') return '';
    const msg = e && e.message || String(e);
    const extra = [ctx.stage ? 'этап: ' + esc(ctx.stage) : '', ctx.task ? 'task_id: <code>' + esc(ctx.task) + '</code>' : '',
      e && e.request_id ? 'request_id: <code>' + esc(e.request_id) + '</code>' : ''].filter(Boolean).join(' · ');
    const hint = {
      E_QUOTA: 'Квота источника исчерпана. Повторите позже или включите альтернативный источник.',
      E_RATE_LIMIT: 'Превышен лимит частоты запросов. Система применит Retry-After и повторит попытку.',
      E_AUTH: 'Требуется повторная аутентификация.',
      E_FORBIDDEN: 'Недостаточно прав для операции.',
      E_POLICY: 'Операция запрещена политикой безопасности (стоп-лист, paywall, robots).',
      E_ROBOTS: 'Источник запрещает автоматический доступ по robots.txt.',
      E_NETWORK: 'Сетевая недоступность. Приложение само повторяет запрос и обновит экран, когда сервер ответит; события журнала сохранены в очереди и будут досланы.',
      E_SCHEMA: 'Ответ не соответствует JSON Schema. Ограниченная попытка исправления выполнена.',
      E_PROVIDER: 'Ошибка провайдера ИИ. Возможен переход на бесплатную альтернативу.',
    }[code] || '';
    return `<div class="state"><span class="ico">⛔</span><b>Ошибка ${esc(code)}</b>
      <div style="margin-top:6px">${esc(msg)}</div>
      ${hint ? `<div class="tiny" style="margin-top:6px">${esc(hint)}</div>` : ''}
      <div class="tiny muted" style="margin-top:8px">${extra}</div>
      <div class="row" style="justify-content:center;margin-top:10px">
        <button class="btn sm" onclick="App.go('logs')">Подробный лог</button>
        <button class="btn sm primary" onclick="App.retry()">Повторить</button>
        ${code === 'E_NETWORK' ? '<button class="btn sm" onclick="App.retry()">Переподключиться</button>' : ''}</div></div>`;
  }
  function fail(host, e, ctx) { host.innerHTML = errorBlock(e, ctx); }

  // ---------------------------------------------------------------- таблица
  function table(host, spec) {
    const el = typeof host === 'string' ? $(host) : host;
    if (!el) return;
    const cols = spec.cols;
    const st = {sort: spec.sort || null, dir: spec.dir || 'desc', page: 0, size: spec.size || 25, q: '', hidden: new Set(spec.hidden || [])};
    const raw = (c, r) => c.v ? c.v(r) : r[c.k];
    const vis = () => cols.filter(c => !st.hidden.has(c.k));
    function rows() {
      let out = spec.rows || [];
      if (st.q) { const q = st.q.toLowerCase(); out = out.filter(r => vis().some(c => String(raw(c, r) ?? '').toLowerCase().includes(q))); }
      if (st.sort) {
        const c = cols.find(x => x.k === st.sort);
        if (c) out = out.slice().sort((a, b) => {
          const av = raw(c, a), bv = raw(c, b);
          if (av == null && bv == null) return 0; if (av == null) return 1; if (bv == null) return -1;
          const r = (typeof av === 'number' && typeof bv === 'number') ? av - bv : String(av).localeCompare(String(bv), 'ru');
          return st.dir === 'asc' ? r : -r;
        });
      }
      return out;
    }
    function paint() {
      const all = rows(), n = all.length;
      const pages = Math.max(1, Math.ceil(n / st.size));
      st.page = Math.min(st.page, pages - 1);
      const slice = all.slice(st.page * st.size, st.page * st.size + st.size);
      const id = el.id || (el.id = uid('tbl-'));
      el.innerHTML = `
        <div class="tbl-toolbar">
          ${spec.search === false ? '' : `<input type="search" placeholder="Фильтр по таблице…" value="${esc(st.q)}" data-act="q" style="max-width:260px">`}
          ${spec.toolbar || ''}
          <span class="tiny muted">строк: ${n}</span>
          <select data-act="size" style="width:auto">${[10, 25, 50, 100, 250].map(v => `<option ${v === st.size ? 'selected' : ''}>${v}</option>`).join('')}</select>
          <details class="acc" style="margin:0;padding:4px 8px"><summary class="tiny">Колонки</summary>
            <div class="row" style="margin-top:6px">${cols.map(c => `<label class="tiny"><input type="checkbox" data-col="${esc(c.k)}" ${st.hidden.has(c.k) ? '' : 'checked'}> ${esc(c.t)}</label>`).join('')}</div></details>
          <button class="btn sm" data-act="csv">Экспорт CSV</button>
        </div>
        ${n ? `<div class="tbl-wrap"><table class="tbl"><thead><tr>${vis().map(c => `<th data-sort="${esc(c.k)}" title="Сортировать">${esc(c.t)}${st.sort === c.k ? (st.dir === 'asc' ? ' ▲' : ' ▼') : ''}</th>`).join('')}</tr></thead>
          <tbody>${slice.map((r, i) => `<tr data-i="${st.page * st.size + i}" ${spec.onRow ? 'tabindex="0" style="cursor:pointer"' : ''}>${vis().map(c => `<td class="${c.cls || ''}">${c.r ? c.r(r) : esc(raw(c, r) ?? '—')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>
          <div class="row tiny muted" style="margin-top:6px">
            <button class="btn sm" data-act="prev" ${st.page === 0 ? 'disabled' : ''}>← назад</button>
            <span>стр. ${st.page + 1} из ${pages} · показано ${st.page * st.size + 1}–${Math.min(n, (st.page + 1) * st.size)}</span>
            <button class="btn sm" data-act="next" ${st.page >= pages - 1 ? 'disabled' : ''}>вперёд →</button></div>`
        : empty(spec.empty || 'Нет строк: фильтр слишком строгий или данных нет', '🗂️')}`;
      el.querySelector('[data-act="q"]')?.addEventListener('input', ev => { st.q = ev.target.value; st.page = 0; paint(); el.querySelector('[data-act="q"]').focus(); });
      el.querySelector('[data-act="size"]')?.addEventListener('change', ev => { st.size = +ev.target.value; st.page = 0; paint(); });
      el.querySelector('[data-act="prev"]')?.addEventListener('click', () => { st.page--; paint(); });
      el.querySelector('[data-act="next"]')?.addEventListener('click', () => { st.page++; paint(); });
      el.querySelector('[data-act="csv"]')?.addEventListener('click', () => exportCSV(spec.export || 'table', vis(), all, raw));
      el.querySelectorAll('[data-col]').forEach(cb => cb.addEventListener('change', ev => {
        const k = ev.target.dataset.col; ev.target.checked ? st.hidden.delete(k) : st.hidden.add(k); paint();
      }));
      el.querySelectorAll('th[data-sort]').forEach(th => th.addEventListener('click', () => {
        const k = th.dataset.sort;
        if (st.sort === k) st.dir = st.dir === 'asc' ? 'desc' : 'asc'; else { st.sort = k; st.dir = 'desc'; }
        paint();
      }));
      if (spec.onRow) el.querySelectorAll('tbody tr').forEach(tr => {
        const go = () => spec.onRow(all[+tr.dataset.i]);
        tr.addEventListener('click', go);
        tr.addEventListener('keydown', ev => { if (ev.key === 'Enter') go(); });
      });
      if (spec.after) spec.after(el);
    }
    paint();
    return {repaint: paint, state: st};
  }

  function exportCSV(name, cols, rows, raw) {
    const q = v => '"' + String(v == null ? '' : v).replace(/"/g, '""') + '"';
    const lines = [cols.map(c => q(c.t)).join(';')];
    rows.forEach(r => lines.push(cols.map(c => q(c.r ? String(c.r(r)).replace(/<[^>]*>/g, '') : raw(c, r))).join(';')));
    download(name + '.csv', '\ufeff' + lines.join('\r\n'), 'text/csv;charset=utf-8');
    toast('Таблица выгружена: ' + name + '.csv', 'ok');
  }
  function download(name, content, type) {
    const blob = content instanceof Blob ? content : new Blob([content], {type: type || 'text/plain;charset=utf-8'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1500);
  }
  const fileURL = (path, query) => {
    const u = new URL(path, location.origin);
    Object.entries(query || {}).forEach(([k, v]) => u.searchParams.set(k, v));
    u.searchParams.set('token', S.token);
    return u.toString();
  };

  // ---------------------------------------------------------------- тосты / модал / контекст
  function toast(text, kind = 'info', ms = 5200) {
    const box = $('toasts'); if (!box) return;
    const d = document.createElement('div');
    d.className = 'toast ' + kind; d.innerHTML = text;
    box.appendChild(d); setTimeout(() => d.remove(), ms);
  }
  function modal(title, html, onMount) {
    $('modal-title').textContent = title;
    $('modal-body').innerHTML = html;
    $('modal').hidden = false;
    if (onMount) onMount($('modal-body'));
  }
  function closeModal() { $('modal').hidden = true; $('modal-body').innerHTML = ''; }
  function ctx(html) { $('context-body').innerHTML = html; }
  function ctxObject(title, fields, links = '') {
    ctx(`<b>${esc(title)}</b>${kv(fields)}${links}`);
  }

  // ---------------------------------------------------------------- исследование
  async function loadResearches(force) {
    if (!S.researches.length || force) {
      const d = await get('/api/v1/researches', {limit: 100});
      S.researches = d.items || [];
      if (!S.researchId && S.researches.length) setResearch(S.researches[0].id, true);
    }
    return S.researches;
  }
  function setResearch(rid, silent) {
    S.researchId = rid || '';
    store.set('isheika.rid', S.researchId);
    S.research = S.researches.find(r => r.id === rid) || null;
    if (!silent) render();
    paintStatus();
  }
  function researchBar(extra = '') {
    const opts = S.researches.map(r => `<option value="${esc(r.id)}" ${r.id === S.researchId ? 'selected' : ''}>${esc(short(r.title, 60))} · ${esc(STATUS_RU[r.status] || r.status)}</option>`).join('');
    return `<div class="card" style="padding:10px 12px"><div class="row">
      <b class="tiny muted">Исследование:</b>
      <select id="rid-select" style="max-width:460px">${opts || '<option value="">— нет исследований —</option>'}</select>
      ${S.researchId ? `<button class="btn sm" data-act="open">Карточка</button>
      ${can('research.run') ? `<button class="btn sm primary" data-act="run">▶ Запустить</button>
      <button class="btn sm" data-act="resume">⟳ Продолжить</button>
      <button class="btn sm danger" data-act="cancel">■ Отменить</button>` : ''}` : ''}
      ${extra}
      <span id="rid-state" class="tiny muted"></span></div></div>`;
  }
  function wireResearchBar(host) {
    const sel = host.querySelector('#rid-select');
    if (sel) sel.addEventListener('change', () => { setResearch(sel.value, true); render(); });
    host.querySelector('[data-act="open"]')?.addEventListener('click', () => go('research', {id: S.researchId}));
    host.querySelector('[data-act="run"]')?.addEventListener('click', () => runResearch(false));
    host.querySelector('[data-act="resume"]')?.addEventListener('click', () => runResearch(true));
    host.querySelector('[data-act="cancel"]')?.addEventListener('click', async () => {
      try { await post(`/api/v1/researches/${S.researchId}/cancel`); toast('Исследование отменено', 'warn'); render(); }
      catch (e) { toast('Отмена: ' + esc(e.message), 'error'); }
    });
  }
  async function runResearch(resume) {
    try {
      await post(`/api/v1/researches/${S.researchId}/${resume ? 'start' : 'start'}`, {resume: !!resume}, S.researchId + ':' + (resume ? 'resume' : 'run') + ':' + Date.now());
      toast(resume ? 'Продолжение с незавершённых этапов' : 'Исследование запущено. Следите за этапами в мониторинге.', 'ok');
      go('monitor', {rid: S.researchId});
    } catch (e) { toast('Запуск: ' + esc(e.message) + ' (' + esc(e.code) + ')', 'error'); }
  }
  async function needResearch(host) {
    await loadResearches();
    if (!S.researchId) {
      host.innerHTML = empty('Исследование не выбрано', '🔬', 'Создайте исследование в разделе «Новое исследование» (UI-02) или выберите существующее в базе исследований.') +
        `<div class="center" style="margin-top:10px"><button class="btn primary" onclick="App.go('new')">Создать исследование</button></div>`;
      return null;
    }
    return S.researchId;
  }

  // ---------------------------------------------------------------- статусы/события
  function paintConn() {
    const el = $('st-conn'); if (!el) return;
    el.className = S.online ? 'ok' : 'bad';
    const q = journalQueueSize();
    el.textContent = 'соединение: ' + (S.online ? (S.sseOk ? 'активно (SSE)' : 'активно')
      : 'недоступно — переподключение' + (NET.tries ? ', попытка ' + NET.tries : ''))
      + (q ? ' · событий журнала в очереди: ' + q : '');
    el.title = S.online ? '' : (NET.lastError || 'Сервер не отвечает');
  }
  function paintStatus() {
    if (!S.system) return;
    // версия в шапке — с сервера, а не зашитая в разметку (было «v0.1» при 1.3.x)
    const ver = $('app-ver');
    if (ver) ver.textContent = 'v' + S.system.version + ' · ' + (S.system.profile || '');
    $('st-method').textContent = 'методика: ' + S.system.methodology_version;
    $('st-sync').textContent = 'синхронизация: ' + (S.lastSync ? S.lastSync.toLocaleTimeString('ru-RU') : '—');
    $('st-jobs').textContent = 'задания: ' + (S.jobsRunning ? S.jobsRunning + ' выполняется' : 'нет активных');
    const r = S.research;
    $('st-period').textContent = 'период: ' + (r ? (donly(r.period_from) + ' … ' + donly(r.period_to)) : '—');
    $('sys-status').textContent = '● ' + (S.system.profile || '') + ' · источников ' + S.system.counters.sources;
    $('sys-status').className = 'pill ' + (S.online ? 'ok' : 'err');
  }
  async function refreshSystem() {
    try { S.system = await get('/api/v1/system'); paintStatus(); } catch (e) { /* offline */ }
  }
  function connectSSE() {
    if (S.sse) { S.sse.close(); S.sse = null; }
    if (!S.token || typeof EventSource === 'undefined') return;
    const es = new EventSource('/api/v1/events/stream?token=' + encodeURIComponent(S.token));
    S.sse = es;
    es.onopen = () => { S.sseOk = true; paintConn(); };
    es.onerror = () => { S.sseOk = false; paintConn(); };
    es.onmessage = ev => {
      let data; try { data = JSON.parse(ev.data); } catch (e) { return; }
      onEvent(data);
    };
  }
  function onEvent(ev) {
    S.lastSync = new Date();
    const t = ev.event_type || '';
    if (t === 'job.started') S.jobsRunning++;
    if (['job.completed', 'job.failed', 'job.retrying'].includes(t)) S.jobsRunning = Math.max(0, S.jobsRunning - 1);
    paintStatus(); paintNavDots();
    const sev = ev.severity === 'error' ? 'error' : ev.severity === 'warning' ? 'warn' : 'info';
    if (['research.completed', 'report.ready', 'job.failed', 'system.error', 'system.warning', 'ai.quota', 'consensus.conflict', 'forecast.ready'].includes(t)) {
      S.notifications.unshift(ev); S.unread++; paintNotif();
      toast(`<b>${esc(t)}</b><div class="tiny muted">${esc(short(JSON.stringify(ev.payload || {}), 160))}</div>`, sev === 'info' ? 'ok' : sev);
    }
    window.dispatchEvent(new CustomEvent('isheika:event', {detail: ev}));
  }
  function paintNotif() { const b = $('notif-count'); if (b) b.textContent = S.unread; }
  function paintNavDots() {
    document.querySelectorAll('.nav-item[data-route="monitor"]').forEach(n => {
      const d = n.querySelector('.nav-dot'); if (d) d.className = 'nav-dot' + (S.jobsRunning ? ' run' : '');
    });
  }

  // ---------------------------------------------------------------- меню и роутер
  const MENU = [
    {group: 'Обзор', items: [
      {m: 'M01', t: 'Главная панель', ico: '🏠', route: 'dashboard'},
      {m: 'M29', t: 'База исследований', ico: '🗄️', route: 'researches'},
    ]},
    {group: 'Поиск и источники', items: [
      {m: 'M02', t: 'Новое исследование', ico: '🔎', route: 'new'},
      {m: 'M08', t: 'Конструктор поиска', ico: '🧩', route: 'query'},
      {m: 'M09', t: 'Результаты поиска', ico: '📄', route: 'results'},
      {m: 'M10', t: 'Дедупликация', ico: '🧬', route: 'dedup'},
      {m: 'M03', t: 'Реестр источников', ico: '📚', route: 'sources'},
      {m: 'M04', t: 'Профили стран', ico: '🌍', route: 'countries'},
    ]},
    {group: 'Мульти-ИИ', items: [
      {m: 'M05', t: 'AI Orchestrator', ico: '🧠', route: 'ai'},
      {m: 'M06', t: 'AI Connectors', ico: '🔌', route: 'ai', params: {tab: 'providers'}},
      {m: 'M07', t: 'AI Agents', ico: '🤖', route: 'ai', params: {tab: 'agents'}},
      {m: 'M23', t: 'Коллективный анализ', ico: '👥', route: 'consensus'},
      {m: 'M24', t: 'Critic Engine', ico: '🧐', route: 'consensus', params: {tab: 'critic'}},
    ]},
    {group: 'Знания и доказательства', items: [
      {m: 'M11', t: 'Идентификация технологии', ico: '🏷️', route: 'passport', params: {tab: 'ident'}},
      {m: 'M12', t: 'Паспорт технологии', ico: '📇', route: 'passport'},
      {m: 'M25', t: 'Evidence Engine', ico: '🧾', route: 'evidence'},
      {m: 'M25', t: 'Независимость доказательств', ico: '🧫', route: 'independence'},
    ]},
    {group: 'Аналитика', items: [
      {m: 'M16', t: 'TRL', ico: '📶', route: 'trl'},
      {m: 'M17', t: 'Реализуемость', ico: '⚖️', route: 'feasibility'},
      {m: 'M14', t: 'Научная аналитика', ico: '🔬', route: 'science'},
      {m: 'M13', t: 'Патентная аналитика', ico: '📜', route: 'patents'},
      {m: 'M15', t: 'Промышленная аналитика', ico: '🏭', route: 'industry'},
      {m: 'M18', t: 'Барьеры и риски', ico: '🚧', route: 'barriers'},
      {m: 'M19', t: 'Альтернативы', ico: '🔀', route: 'alternatives'},
      {m: 'M20', t: 'Тренды', ico: '📈', route: 'trends'},
      {m: 'M21', t: 'Прогноз 0–50 лет', ico: '🔮', route: 'forecast'},
      {m: 'M22', t: 'Сценарный модуль', ico: '🎭', route: 'forecast', params: {tab: 'scenarios'}},
      {m: 'M26', t: 'Сравнение технологий', ico: '🆚', route: 'compare'},
    ]},
    {group: 'Отчётность', items: [
      {m: 'M27', t: 'Генератор отчёта', ico: '📝', route: 'report'},
      {m: 'M28', t: 'Экспорт', ico: '📤', route: 'report', params: {tab: 'export'}},
    ]},
    {group: 'Администрирование', items: [
      {m: 'M30', t: 'Мониторинг', ico: '📡', route: 'monitor'},
      {m: 'M30', t: 'Журнал работы', ico: '🧭', route: 'logs'},
      {m: 'M33', t: 'Журнал действий и диагностика', ico: '🧾', route: 'journal'},
      {m: 'M30', t: 'Эксплуатация и SLO', ico: '🛟', route: 'ops'},
      {m: 'M31', t: 'Настройки', ico: '⚙️', route: 'settings'},
      {m: 'M32', t: 'Контроль качества', ico: '✅', route: 'quality'},
      {m: 'M32', t: 'Реестр методик', ico: '📐', route: 'methodologies'},
      {m: 'M32', t: 'Воспроизводимость', ico: '🧪', route: 'reproducibility'},
    ]},
  ];

  function paintNav() {
    const nav = $('sidebar');
    nav.innerHTML = MENU.map(g => `<div class="nav-group">${esc(g.group)}</div>` + g.items.map(it => {
      const active = S.route === it.route && JSON.stringify(it.params || {}) === JSON.stringify(pickParams(it));
      return `<a class="nav-item ${active ? 'active' : ''}" href="#/${it.route}${qsOf(it.params)}" data-route="${it.route}" title="${esc(it.m + ' · ' + it.t)}">
        <span class="ico">${it.ico}</span><span class="lbl">${esc(it.t)}</span><span class="code">${it.m}</span>
        ${it.route === 'monitor' ? '<span class="nav-dot"></span>' : ''}</a>`;
    }).join('')).join('');
    paintNavDots();
  }
  function pickParams(it) {
    const out = {}; Object.keys(it.params || {}).forEach(k => { if (S.params[k]) out[k] = S.params[k]; });
    return out;
  }
  const qsOf = p => { const s = Object.entries(p || {}).map(([k, v]) => k + '=' + encodeURIComponent(v)).join('&'); return s ? '?' + s : ''; };

  function parseHash() {
    const h = location.hash.replace(/^#\/?/, '');
    const [path, qs] = h.split('?');
    const parts = (path || 'dashboard').split('/');
    const params = {};
    new URLSearchParams(qs || '').forEach((v, k) => params[k] = v);
    if (parts[1]) params.id = parts[1];
    return {route: parts[0] || 'dashboard', params};
  }
  function go(route, params) { location.hash = '#/' + route + qsOf(params); }

  /* Перерисовки идут СТРОГО по очереди (ред. 1.4.2).
     Раньше afterLogin менял location.hash (это вызывало render по hashchange) и
     сам вызывал render: две отрисовки одного экрана шли параллельно, вторая
     подменяла разметку, а первая писала в уже отсоединённый узел —
     «Cannot set properties of null (setting 'innerHTML')» на UI-01 и UI-23
     (журнал пользователя). Теперь запросы объединяются: выполняется последний. */
  const RENDER = {seq: 0, chain: Promise.resolve(), cleanups: []};
  function onCleanup(fn) { if (typeof fn === 'function') RENDER.cleanups.push(fn); }
  function runCleanups() {
    const list = RENDER.cleanups.splice(0, RENDER.cleanups.length);
    list.forEach(fn => { try { fn(); } catch (e) { /* очистка не должна ронять экран */ } });
  }
  function render() {
    const my = ++RENDER.seq;
    RENDER.chain = RENDER.chain.then(() => (my === RENDER.seq ? drawScreen() : null))
      .catch(e => { reportClient({action: 'render.chain', message: (e && e.message) || String(e),
                                  stack: e && e.stack, type: 'RenderChainError'}); });
    return RENDER.chain;
  }

  // Безопасная запись в узел: экран мог быть сменён, пока шёл запрос.
  function setHTML(id, html) {
    const el = typeof id === 'string' ? $(id) : id;
    if (!el) return false;
    el.innerHTML = html;
    return true;
  }
  const stale = host => !host || host.isConnected === false;

  async function drawScreen() {
    if (!S.user) return;
    runCleanups();
    const {route, params} = parseHash();
    S.route = route; S.params = params;
    if (params.rid && params.rid !== S.researchId) { S.researchId = params.rid; store.set('isheika.rid', params.rid); }
    paintNav();
    const screen = Screens[route];
    const host = $('screen');
    ctx('<p class="muted tiny">Выберите объект — здесь появятся источники, доказательства и история.</p>');
    if (!screen) { host.innerHTML = empty('Экран не найден: ' + route, '🧭'); return; }
    $('crumbs').innerHTML = `ИЩЕЙКА НТР AI / ${esc(screen.group || '')} / <b>${esc(screen.title)}</b>` +
      (S.researchId ? ` · исследование <code>${esc(S.researchId)}</code>` : '');
    document.title = screen.title + ' — ИЩЕЙКА НТР AI';
    host.innerHTML = `<h2 class="screen-title">${esc(screen.title)}<span class="ui-code">${esc(screen.ui || '')}</span>
      ${screen.module ? `<span class="ui-code">${esc(screen.module)}</span>` : ''}</h2><div id="screen-body"></div>`;
    const body = $('screen-body');
    if (screen.right && !can(screen.right)) { body.innerHTML = denied(screen.right); return; }
    loading(body);
    try {
      await screen.render(body, params);
      if (stale(body)) return;                 // экран уже сменился — не трогаем DOM
    } catch (e) {
      if (stale(body)) return;                 // отказ устаревшей отрисовки не дефект
      fail(body, e, {stage: screen.ui});
      reportClient({action: 'render.' + route, message: (e && e.message) || String(e),
                    stack: e && e.stack, code: e && e.code, type: (e && e.name) || 'RenderError',
                    detail: {screen: screen.ui, params: params}});
    }
    $('workspace').scrollTop = 0;
  }

  // ---------------------------------------------------------------- вход/выход/тема
  async function login(name, pass) {
    const d = await post('/api/v1/auth/login', {login: name, password: pass});
    S.token = d.token; store.set('isheika.token', d.token);
    S.user = d.user; S.rights = new Set(d.user.rights || []);
    await afterLogin();
  }
  async function afterLogin() {
    $('login').hidden = true; $('app').hidden = false;
    $('user').textContent = (S.user.display_name || S.user.login) + ' · ' + S.user.role;
    await refreshSystem();
    blog('Состояние системы получено', 'ok', S.system ? 'версия ' + S.system.version : '');
    await loadResearches(true).catch(e => blog('Список исследований не загружен', 'warn', (e && e.message) || ''));
    connectSSE(); paintStatus(); paintConn();
    if (!location.hash) location.hash = '#/dashboard';
    await render();
    blog('Интерфейс готов', 'ok', 'экран: ' + (S.route || 'dashboard'));
    const b = boot(); if (b) b.hide();
    setInterval(refreshSystem, 60000);
  }
  function logout(clear = true) {
    if (S.sse) { S.sse.close(); S.sse = null; }
    S.user = null; S.rights = new Set(); S.token = '';
    if (clear) store.del('isheika.token');
    $('app').hidden = true; $('login').hidden = false;
  }
  function setTheme(t) {
    S.theme = t; document.documentElement.dataset.theme = t; store.set('isheika.theme', t);
  }

  // ---------------------------------------------------------------- инициализация
  const boot = () => window.__isheikaBoot || null;
  const blog = (step, status, detail) => { const b = boot(); if (b) b.log(step, status, detail); };

  // Отсутствие элемента не должно ронять инициализацию: раньше любой null
  // в цепочке addEventListener приводил к пустому экрану без диагностики.
  function on(id, evt, fn) {
    const el = $(id);
    if (!el) { blog('Элемент интерфейса не найден: #' + id, 'fail', 'обработчик ' + evt + ' не установлен'); return null; }
    el.addEventListener(evt, fn);
    return el;
  }

  function tlsLine(srv) {
    const t = srv && srv.tls;
    if (!t || t.error) return '—';
    const extra = t.extra_bundle ? ' + свой набор оператора' : '';
    return `${t.total_anchors} корней (системных ${t.system_anchors}, приложения ${t.bundled_certs})${extra}`;
  }

  async function bootLogModal() {
    const b = boot();
    let srv = null;
    try { srv = await get('/api/v1/boot-log'); } catch (e) { srv = {error: e.message || String(e)}; }
    const rows = (srv && srv.steps || []).map(s =>
      `<tr><td>${esc(s.at)}</td><td>${s.status === 'ok' ? tag('ok', 'ok') : tag(s.status, 'err')}</td><td>${esc(s.step)}</td><td class="tiny">${esc(s.detail || '')}</td></tr>`).join('');
    const checks = (srv && srv.checks || []).map(c =>
      `<tr><td>${c.ok ? tag('исправно', 'ok') : tag('ОТКАЗ', 'err')}</td><td>${esc(c.check)}</td><td class="tiny">${esc(c.detail || '')}</td></tr>`).join('');
    const assets = (srv && srv.assets || []).map(a =>
      `<tr><td>${a.ok ? tag('ok', 'ok') : tag('нет', 'err')}</td><td>${esc(a.asset)}</td><td class="num">${a.bytes}</td><td class="tiny">${esc(a.ctype || '')}</td></tr>`).join('');
    modal('Журнал загрузки и самопроверка', `
      ${alertBox(srv && srv.ok ? 'ok' : 'error', srv && srv.ok ? 'Запуск исправен: все проверки пройдены.' : 'Есть отказы — см. строки ниже. Журнал можно скачать и приложить к обращению.')}
      ${kv({'Запуск': esc(srv && srv.boot_id || '—'), 'Версия': esc(srv && srv.app_version || '—'),
            'Профиль': esc(srv && srv.profile || '—'), 'Python': esc(srv && srv.python || '—'),
            'Платформа': esc(srv && srv.platform || '—'), 'Каталог данных': esc(srv && srv.data_dir || '—'),
            'Доверие сертификатам': esc(tlsLine(srv))})}
      <h3>Шаги запуска сервера</h3><table class="tbl">${rows || '<tr><td>нет данных</td></tr>'}</table>
      <h3>Самопроверка</h3><table class="tbl">${checks || '<tr><td>нет данных</td></tr>'}</table>
      <h3>Ресурсы интерфейса</h3><table class="tbl">${assets || '<tr><td>нет данных</td></tr>'}</table>
      <h3>Шаги браузера</h3><pre class="boot-log">${esc(b ? b.text() : 'журнал браузера недоступен')}</pre>
      <div class="row">
        <a class="btn sm" href="${fileURL('/api/v1/boot-log/export', {fmt: 'txt'})}">Скачать журнал сервера</a>
        <button class="btn sm" id="boot-dl-client">Скачать журнал браузера</button>
      </div>`);
    const dl = $('boot-dl-client');
    if (dl && b) dl.addEventListener('click', () => b.download());
  }

  function init() {
    setTheme(S.theme);
    blog('Инициализация интерфейса', 'ok', 'App.init');
    on('login-form', 'submit', async ev => {
      ev.preventDefault();
      const f = ev.target, box = $('login-error');
      box.hidden = true;
      try { await login(f.login.value.trim(), f.password.value); }
      catch (e) { box.hidden = false; box.innerHTML = esc(e.message || 'Ошибка входа') + ' <span class="tiny">(' + esc(e.code || '') + ')</span>'; }
    });
    on('theme-btn', 'click', () => { setTheme(S.theme === 'light' ? 'dark' : 'light'); if (S.user) render(); });
    on('logout-btn', 'click', () => logout());
    on('menu-toggle', 'click', () => $('app').classList.toggle('nav-collapsed'));
    on('context-toggle', 'click', () => $('app').classList.toggle('ctx-collapsed'));
    on('modal-close', 'click', closeModal);
    on('modal', 'click', ev => { if (ev.target.id === 'modal') closeModal(); });
    document.addEventListener('keydown', ev => { if (ev.key === 'Escape') closeModal(); });
    on('notif-btn', 'click', () => {
      S.unread = 0; paintNotif();
      modal('Уведомления', S.notifications.length ? S.notifications.slice(0, 60).map(e =>
        `<div class="evidence-item"><b>${esc(e.event_type)}</b> <span class="tiny muted">${dt(e.created_at)}</span>
         <div class="tiny">${esc(short(JSON.stringify(e.payload || {}), 300))}</div></div>`).join('') : empty('Уведомлений нет', '🔔'));
    });
    const gs = () => { const q = $('global-search').value.trim(); if (q) go('new', {q}); };
    on('global-search-btn', 'click', gs);
    on('global-search', 'keydown', ev => { if (ev.key === 'Enter') gs(); });
    window.addEventListener('hashchange', render);
    window.addEventListener('online', () => { S.online = true; paintConn(); });
    window.addEventListener('offline', () => { S.online = false; paintConn(); toast('Сеть недоступна: работа в режиме offline', 'warn'); });
    on('boot-btn', 'click', bootLogModal);
    (async () => {
      try {
        if (!S.token) {
          $('login').hidden = false;
          blog('Форма входа показана', 'ok', 'сохранённого токена нет');
          const b = boot(); if (b) b.hide();
          return;
        }
        const me = await get('/api/v1/auth/me');
        S.user = me.user; S.rights = new Set(me.rights || []);
        blog('Сессия восстановлена', 'ok', S.user.login + ' · ' + S.user.role);
        await afterLogin();
      } catch (e) {
        $('login').hidden = false;
        blog('Восстановление сессии не удалось', 'warn', (e && e.message) || String(e));
        const b = boot(); if (b) b.hide();
      }
    })();
  }

  return {
    S, api, get, post, del, can, esc, num, pct, dt, donly, short, uid, $, sleep,
    tag, statusTag, kpi, card, alert: alertBox, kv, spinner, empty, denied, loading, fail, errorBlock,
    table, exportCSV, download, fileURL, toast, modal, closeModal, ctx, ctxObject,
    loadResearches, setResearch, researchBar, wireResearchBar, needResearch, runResearch,
    go, render, refreshSystem, MENU, STATUS_RU, init, setTheme, logout, bootLogModal, reportClient,
    retry: () => { probeServer(); return render(); },
    flushJournal, journalQueueSize, probeServer, netState: NET,
    setHTML, stale, onCleanup,
  };
})();

window.App = App;
document.addEventListener('DOMContentLoaded', App.init);
