/* ИЩЕЙКА НТР AI — журнал действий времени работы (ред. 1.4.0).
   UI-32 «Журнал действий и диагностика», модуль M33.

   Экран отвечает на три вопроса: что система делала, где она сломалась и
   что из сделанного противоречит правилам. Все выборки, группировки и
   проверки выполняет сервер — браузер только отображает (ТЗ-04 §3).
*/
window.Screens = window.Screens || {};
(function () {
  const Screens = window.Screens;
  const esc = s => App.esc(s);

  const LEVEL_RU = {debug: 'отладка', info: 'действие', warn: 'предупреждение',
                    error: 'ошибка', critical: 'критично'};
  const KIND_RU = {action: 'действие пользователя', api: 'обращение к API', workflow: 'этап исследования',
                   connector: 'внешний источник', ai: 'ИИ', analytics: 'расчёт', storage: 'хранилище',
                   security: 'безопасность', ui: 'интерфейс', system: 'система'};
  const SEV_RU = {critical: 'критично', error: 'ошибка', warn: 'предупреждение', info: 'сведение'};

  const levelTag = l => App.tag(LEVEL_RU[l] || l,
    l === 'error' || l === 'critical' ? 'err' : l === 'warn' ? 'warn' : l === 'debug' ? '' : 'ok');
  const sevTag = s => App.tag(SEV_RU[s] || s, s === 'critical' || s === 'error' ? 'err' : s === 'warn' ? 'warn' : '');
  const cidLink = c => c ? `<a href="#/logs?cid=${esc(c)}" title="Сквозная трассировка"><code>${esc(String(c).slice(0, 14))}</code></a>` : '—';
  const ridLink = r => r ? `<a href="#/research/${esc(r)}">${esc(String(r).slice(0, 12))}</a>` : '—';

  const COLS = [
    {k: 'at', t: 'Время', r: r => App.dt(r.at)},
    {k: 'level', t: 'Уровень', r: r => levelTag(r.level)},
    {k: 'kind', t: 'Вид', r: r => esc(KIND_RU[r.kind] || r.kind)},
    {k: 'action', t: 'Действие', r: r => `<a href="#" data-jrn="${esc(r.id)}" title="Открыть запись и контекст"><code>${esc(r.action)}</code></a>`},
    {k: 'actor', t: 'Пользователь', r: r => esc(r.actor || '—')},
    {k: 'outcome', t: 'Исход', r: r => r.outcome === 'fail' ? App.tag('отказ', 'err') : r.outcome === 'contradiction' ? App.tag('противоречие', 'warn') : App.tag('успех', 'ok')},
    {k: 'duration_ms', t: 'мс', cls: 'num', r: r => r.duration_ms == null ? '—' : App.num(r.duration_ms, 1)},
    {k: 'error_code', t: 'Код', r: r => r.error_code ? App.tag(r.error_code, 'err') : '—'},
    {k: 'research_id', t: 'Исследование', r: r => ridLink(r.research_id)},
    {k: 'correlation_id', t: 'Трассировка', r: r => cidLink(r.correlation_id)},
    {k: 'message', t: 'Сообщение', r: r => `<span class="tiny">${esc(App.short(r.message || '', 120))}</span>`},
  ];

  // Карточка записи: полный контекст, traceback и данные — то, чего не хватало для разбора.
  async function openEntry(id) {
    const e = await App.get('/api/v1/journal/' + encodeURIComponent(id));
    const stack = e.stack ? `<h3>Traceback</h3><pre class="boot-log">${esc(e.stack)}</pre>` : '';
    const ctxRows = (e.context || []).map(c =>
      `<tr><td class="tiny">${App.dt(c.at)}</td><td>${levelTag(c.level)}</td><td><code>${esc(c.action)}</code></td>
       <td class="tiny">${esc(App.short(c.message || '', 90))}</td><td class="num">${c.duration_ms == null ? '—' : App.num(c.duration_ms, 1)}</td></tr>`).join('');
    App.modal('Запись журнала · ' + e.action, `
      ${App.kv({'Время': App.dt(e.at), 'Уровень': levelTag(e.level), 'Вид': esc(KIND_RU[e.kind] || e.kind),
        'Источник': esc(e.source), 'Пользователь': esc(e.actor || '—') + (e.role ? ' · ' + esc(e.role) : ''),
        'Исход': esc(e.outcome || '—'), 'HTTP': e.http_status == null ? '—' : e.http_status,
        'Длительность': e.duration_ms == null ? '—' : App.num(e.duration_ms, 1) + ' мс',
        'Код ошибки': e.error_code ? App.tag(e.error_code, 'err') : '—',
        'Тип исключения': esc(e.error_type || '—'),
        'Подпись дефекта': e.fingerprint ? `<code>${esc(e.fingerprint)}</code>` : '—',
        'request_id': `<code>${esc(e.request_id || '—')}</code>`,
        'correlation_id': cidLink(e.correlation_id),
        'Исследование': ridLink(e.research_id), 'Объект': esc((e.entity_kind || '') + ' ' + (e.entity_id || '')) || '—'})}
      ${e.message ? App.alert(e.level === 'error' || e.level === 'critical' ? 'error' : 'info', esc(e.message)) : ''}
      ${stack}
      ${e.client && Object.keys(e.client).length ? '<h3>Данные браузера</h3>' + App.kv(Object.fromEntries(
        Object.entries(e.client).map(([k, v]) => [k, esc(String(v == null ? '—' : v))]))) : ''}
      <h3>Данные записи</h3><pre class="boot-log">${esc(JSON.stringify(e.detail || {}, null, 1))}</pre>
      ${ctxRows ? `<h3>Та же трассировка (${e.context.length})</h3>
        <table class="tbl"><tr><th>Время</th><th>Уровень</th><th>Действие</th><th>Сообщение</th><th>мс</th></tr>${ctxRows}</table>` : ''}
      <div class="row">
        ${e.fingerprint ? `<a class="btn sm" href="#/journal?tab=errors&fingerprint=${esc(e.fingerprint)}">Все падения этой подписи</a>` : ''}
        ${e.correlation_id ? `<a class="btn sm" href="#/logs?cid=${esc(e.correlation_id)}">Сквозная трассировка</a>` : ''}
      </div>`);
  }

  function wireRows(host) {
    host.querySelectorAll('[data-jrn]').forEach(a => a.addEventListener('click', ev => {
      ev.preventDefault();
      openEntry(a.dataset.jrn).catch(e => App.toast(esc(e.message), 'error'));
    }));
  }

  Screens.journal = {
    title: 'Журнал действий и диагностика', ui: 'UI-32', module: 'M33',
    group: 'Администрирование', right: 'logs.read',
    async render(host, params) {
      const tab = params.tab || 'feed';
      const tabs = [['feed', 'Лента действий'], ['errors', 'Ошибки и дефекты'],
                    ['contradictions', 'Противоречия'], ['browser', 'Ошибки браузера']];
      const head = App.card('Разделы', '<div class="row">' + tabs.map(([k, n]) =>
        `<a class="btn sm ${tab === k ? 'primary' : ''}" href="#/journal?tab=${k}">${n}</a>`).join('') +
        '<span class="tiny muted">Журнал пишет сервер: действия, отказы, этапы, внешние вызовы и ошибки интерфейса.</span></div>');

      // ---------------------------------------------------------- лента действий
      if (tab === 'feed') {
        const f = {level: params.level || '', kind: params.kind || '', source: params.source || '',
                   actor: params.actor || '', q: params.q || '', outcome: params.outcome || '',
                   research_id: params.scope === 'research' ? App.S.researchId : ''};
        // Частичная доступность: отказ сводки не должен лишать ленты (замечание
        // пользователя — экран оставался «недоступен» целиком).
        const [rd, rs] = await Promise.allSettled([
          App.get('/api/v1/journal', {...f, limit: 300}),
          App.get('/api/v1/journal/stats'),
        ]);
        if (rd.status === 'rejected' && rs.status === 'rejected') throw rd.reason;
        const d = rd.status === 'fulfilled' ? rd.value : {items: [], total: 0};
        const st = rs.status === 'fulfilled' ? rs.value : {};
        const partial = [rd, rs].filter(x => x.status === 'rejected')
          .map(x => (x.reason && x.reason.message) || 'отказ запроса');
        const opt = (list, cur) => list.map(([k, n]) => `<option value="${k}" ${cur === k ? 'selected' : ''}>${n}</option>`).join('');
        const day = st.last_24h || {};
        host.innerHTML = head + `
          <div class="grid g4">
            ${App.kpi('Записей в журнале', st.total ?? d.total ?? 0, 'политика хранения: ' + (st.retention_days ?? '—') + ' сут.')}
            ${App.kpi('Ошибок за 24 ч', day.errors ?? 0, 'уровни error и critical')}
            ${App.kpi('Предупреждений за 24 ч', day.warnings ?? 0, 'уровень warn')}
            ${App.kpi('Ошибок браузера', st.browser_errors ?? 0, 'присланы интерфейсом')}
          </div>
          ${partial.length ? App.alert('warn', 'Часть данных не получена: ' + esc(partial.join('; ')) + '. Показано то, что сервер отдал; приложение повторит запрос автоматически.') : ''}
          ${st.failed_writes ? App.alert('error', 'Сбои записи журнала: ' + st.failed_writes + '. Часть записей сохранена в var/journal-fallback.log — проверьте БД и диск.') : ''}
          ${App.card('Фильтры', `<div class="row">
            <select id="j-level">${opt([['', 'Все уровни'], ['info', 'Действия и выше'], ['warn', 'Предупреждения и выше'], ['error', 'Только ошибки'], ['debug', 'Включая отладку']], f.level)}</select>
            <select id="j-kind">${opt([['', 'Все виды']].concat(Object.entries(KIND_RU)), f.kind)}</select>
            <select id="j-source">${opt([['', 'Все источники'], ['server', 'Сервер'], ['workflow', 'Этапы'], ['connector', 'Источники'], ['browser', 'Браузер'], ['scheduler', 'Планировщик']], f.source)}</select>
            <select id="j-outcome">${opt([['', 'Любой исход'], ['ok', 'Успех'], ['fail', 'Отказ'], ['contradiction', 'Противоречие']], f.outcome)}</select>
            <select id="j-scope"><option value="all" ${f.research_id ? '' : 'selected'}>Вся система</option><option value="research" ${f.research_id ? 'selected' : ''}>Текущее исследование</option></select>
            <input id="j-q" type="search" placeholder="Поиск: действие, код, сообщение" value="${esc(f.q)}">
            <button class="btn sm" id="j-apply">Применить</button>
          </div>
          <div class="row" style="margin-top:8px">
            <a class="btn sm" href="${App.fileURL('/api/v1/journal/export', {...f, fmt: 'txt'})}">Экспорт TXT</a>
            <a class="btn sm" href="${App.fileURL('/api/v1/journal/export', {...f, fmt: 'json'})}">Экспорт JSON</a>
            <a class="btn sm" href="${App.fileURL('/api/v1/journal/export', {...f, fmt: 'csv'})}">Экспорт CSV</a>
            <a class="btn sm" href="#/logs">Подробный журнал исследования</a>
            <span class="tiny muted">Найдено: ${d.total}. Уровень записи задаётся в настройках (journal_level).</span>
          </div>`)}
          ${App.card('Лента (' + d.items.length + ')', d.items.length ? '<div id="j-tbl"></div>' : App.empty('Записей по фильтру нет', '🧾'))}
          ${App.card('Самые медленные действия', '<div id="j-slow"></div>')}`;
        App.table('j-tbl', {rows: d.items, cols: COLS, size: 25, sort: 'at', export: 'journal'});
        App.table('j-slow', {
          rows: st.slowest_actions || [], size: 8, search: false,
          cols: [{k: 'action', t: 'Действие'}, {k: 'n', t: 'Вызовов', cls: 'num'},
                 {k: 'avg_ms', t: 'Среднее, мс', cls: 'num'}, {k: 'max_ms', t: 'Максимум, мс', cls: 'num'}],
        });
        wireRows(host);
        const apply = () => App.go('journal', {
          tab: 'feed', level: document.getElementById('j-level').value,
          kind: document.getElementById('j-kind').value, source: document.getElementById('j-source').value,
          outcome: document.getElementById('j-outcome').value, scope: document.getElementById('j-scope').value,
          q: document.getElementById('j-q').value.trim(),
        });
        document.getElementById('j-apply').addEventListener('click', apply);
        document.getElementById('j-q').addEventListener('keydown', ev => { if (ev.key === 'Enter') apply(); });
        App.ctx(App.alert('info', 'Журнал действий не подменяет аудит: аудит отвечает «кто изменил данные», журнал — «что делала система и где сломалась». Записи связаны через request_id и correlation_id.'));
        return;
      }

      // ---------------------------------------------------------- ошибки и дефекты
      if (tab === 'errors') {
        const d = await App.get('/api/v1/journal/errors', {limit: 60});
        const fp = params.fingerprint || '';
        const rows = fp ? d.items.filter(x => x.fingerprint === fp) : d.items;
        host.innerHTML = head + `
          ${App.alert(rows.length ? 'warn' : 'ok', rows.length
            ? 'Дефектов (уникальных подписей): ' + rows.length + '. Подпись не зависит от идентификаторов и чисел — одинаковые падения собраны в одну строку.'
            : 'Ошибок в журнале нет.')}
          ${fp ? `<div class="row"><a class="btn sm" href="#/journal?tab=errors">← Все дефекты</a><span class="tiny">Подпись: <code>${esc(fp)}</code></span></div>` : ''}
          ${App.card('Дефекты по подписи', rows.length ? '<div id="je-tbl"></div>' : App.empty('Ошибок не зафиксировано', '✅'))}
          <div id="je-detail"></div>`;
        App.table('je-tbl', {
          rows, size: 20, sort: 'occurrences', export: 'journal_errors',
          cols: [{k: 'fingerprint', t: 'Подпись', r: r => `<a href="#" data-fp="${esc(r.fingerprint)}"><code>${esc(r.fingerprint)}</code></a>`},
                 {k: 'action', t: 'Действие'},
                 {k: 'kind', t: 'Вид', r: r => esc(KIND_RU[r.kind] || r.kind)},
                 {k: 'error_code', t: 'Код', r: r => r.error_code ? App.tag(r.error_code, 'err') : '—'},
                 {k: 'error_type', t: 'Исключение', r: r => esc(r.error_type || '—')},
                 {k: 'occurrences', t: 'Повторов', cls: 'num'},
                 {k: 'researches', t: 'Исследований', cls: 'num'},
                 {k: 'first_seen', t: 'Впервые', r: r => App.dt(r.first_seen)},
                 {k: 'last_seen', t: 'Последний раз', r: r => App.dt(r.last_seen)}],
        });
        const showSample = f => {
          const g = rows.find(x => x.fingerprint === f) || {};
          const s = g.sample || {};
          App.setHTML('je-detail', App.card('Последнее падение подписи ' + f, `
            ${App.kv({'Действие': esc(g.action || '—'), 'Код': esc(g.error_code || '—'),
                      'Повторов': g.occurrences ?? 0, 'Время': App.dt(s.at),
                      'Пользователь': esc(s.actor || '—'), 'request_id': `<code>${esc(s.request_id || '—')}</code>`,
                      'Трассировка': cidLink(s.correlation_id)})}
            ${App.alert('error', esc(s.message || ''))}
            ${s.stack ? `<pre class="boot-log">${esc(s.stack)}</pre>` : '<p class="tiny muted">Traceback не сохранён (ошибка предметная, а не программная).</p>'}
            <div class="row">${s.id ? `<button class="btn sm" data-jrn="${esc(s.id)}">Открыть запись</button>` : ''}
              <a class="btn sm" href="#/journal?level=error&q=${encodeURIComponent(g.action || '')}">Все записи этого действия</a></div>`));
          wireRows(document.getElementById('je-detail'));
        };
        host.querySelectorAll('[data-fp]').forEach(a => a.addEventListener('click', ev => {
          ev.preventDefault(); showSample(a.dataset.fp);
        }));
        if (rows.length) showSample(rows[0].fingerprint);
        return;
      }

      // ---------------------------------------------------------- противоречия
      if (tab === 'contradictions') {
        const scope = params.scope === 'research' ? App.S.researchId : '';
        const d = await App.get('/api/v1/diagnostics', scope ? {research_id: scope} : {});
        const c = d.counts || {};
        host.innerHTML = head + `
          <div class="grid g4">
            ${App.kpi('Правил проверки', d.rules ?? 0, 'состояния, расчёты, доказательства, политика')}
            ${App.kpi('Противоречий', (d.findings || []).length, 'уникальных расхождений')}
            ${App.kpi('Случаев', d.cases ?? 0, 'всего затронутых объектов')}
            ${App.kpi('Критичных / ошибок', (c.critical || 0) + ' / ' + (c.error || 0), 'предупреждений: ' + (c.warn || 0))}
          </div>
          ${App.alert(d.ok ? 'ok' : (c.critical || c.error) ? 'error' : 'warn', d.ok
            ? 'Противоречий не найдено: состояние, расчёты и доказательства согласованы с ТЗ.'
            : 'Найдены расхождения с правилами предметной области. Каждое сопровождается идентификаторами и рекомендацией.')}
          ${(d.broken_rules || []).length ? App.alert('error', 'Не выполнились правила: ' + d.broken_rules.map(b => esc(b.rule + ' — ' + b.error)).join('; ')) : ''}
          <div class="row">
            <select id="dg-scope"><option value="all" ${scope ? '' : 'selected'}>Вся система</option><option value="research" ${scope ? 'selected' : ''}>Текущее исследование</option></select>
            <button class="btn sm primary" id="dg-run" ${App.can('logs.read') ? '' : 'disabled'}>Проверить и записать в журнал</button>
            <span class="tiny muted">Проверка: ${App.dt(d.checked_at)}. Правила только читают данные.</span>
          </div>
          <div id="dg-list">${(d.findings || []).length ? '' : App.empty('Противоречий нет', '🔍')}</div>`;
        const list = document.getElementById('dg-list');
        (d.findings || []).forEach(f => {
          const card = document.createElement('div');
          card.innerHTML = App.card(`${f.code} · ${esc(f.title)} (${f.count})`, `
            ${App.alert(f.severity === 'critical' || f.severity === 'error' ? 'error' : 'warn', esc(f.detail))}
            ${App.kv({'Важность': sevTag(f.severity), 'Случаев': f.count,
                      'Что делать': esc(f.recommendation)})}
            <details class="acc"><summary>Основания (${Math.min(f.count, 10)} из ${f.count})</summary>
              <pre class="boot-log">${esc(JSON.stringify(f.evidence, null, 1))}</pre></details>`);
          list.appendChild(card);
        });
        document.getElementById('dg-scope').addEventListener('change', ev =>
          App.go('journal', {tab: 'contradictions', scope: ev.target.value}));
        document.getElementById('dg-run').addEventListener('click', async () => {
          const b = document.getElementById('dg-run');
          b.disabled = true; b.textContent = 'Проверка…';
          try {
            const res = await App.post('/api/v1/diagnostics/run', scope ? {research_id: scope} : {});
            App.toast('Проверено правил: ' + res.rules + ', противоречий: ' + (res.findings || []).length,
              (res.findings || []).length ? 'warn' : 'ok');
            App.go('journal', {tab: 'contradictions', scope: params.scope});
          } catch (e) { App.toast(esc(e.message), 'error'); b.disabled = false; b.textContent = 'Проверить и записать в журнал'; }
        });
        App.ctx(App.alert('info', 'Противоречие — это расхождение с ТЗ (например, TRL выше подтверждённого критериями или утверждение SUPPORTED без доказательств), а не мнение модели.'));
        return;
      }

      // ---------------------------------------------------------- ошибки браузера
      const d = await App.get('/api/v1/journal', {source: 'browser', limit: 200});
      const queued = App.journalQueueSize();
      host.innerHTML = head + `
        ${App.alert('info', 'Ошибки интерфейса присылает сам браузер (window.onerror, необработанные обещания, отказы API и рендеринга экранов). Они сохраняются на сервере и не теряются при перезагрузке вкладки.')}
        ${queued ? App.alert('warn', 'Не доставлено событий: ' + queued + '. Они сохранены в браузере (localStorage) и будут отправлены, как только сервер ответит — в записи появится время постановки в очередь queued_at.') : ''}
        <div class="row" style="margin-bottom:8px">
          <button class="btn sm" id="jb-flush" ${queued ? '' : 'disabled'}>Отправить очередь (${queued})</button>
          <span class="tiny muted">Очередь хранится локально, не более 50 событий; при недоступности сервера ошибки не теряются.</span>
        </div>
        ${App.card('События браузера (' + d.total + ')', d.items.length ? '<div id="jb-tbl"></div>' : App.empty('Ошибок интерфейса не зафиксировано', '🖥️'))}`;
      document.getElementById('jb-flush').addEventListener('click', async () => {
        const b = document.getElementById('jb-flush');
        b.disabled = true; b.textContent = 'Отправка…';
        const n = await App.flushJournal();
        App.toast(n ? 'Отправлено событий: ' + n : 'Сервер пока недоступен — очередь сохранена', n ? 'ok' : 'warn');
        App.go('journal', {tab: 'browser'});
      });
      App.table('jb-tbl', {
        rows: d.items, size: 25, sort: 'at', export: 'journal_browser',
        cols: [COLS[0], COLS[1],
               {k: 'action', t: 'Действие', r: r => `<a href="#" data-jrn="${esc(r.id)}"><code>${esc(r.action)}</code></a>`},
               {k: 'message', t: 'Сообщение', r: r => `<span class="tiny">${esc(App.short(r.message || '', 140))}</span>`},
               {k: 'client', t: 'Экран / маршрут', r: r => esc(((r.client || {}).screen || '') + ' ' + ((r.client || {}).route || ''))},
               {k: 'actor', t: 'Пользователь', r: r => esc(r.actor || 'до входа')},
               {k: 'fingerprint', t: 'Подпись', r: r => r.fingerprint ? `<code>${esc(r.fingerprint)}</code>` : '—'}],
      });
      wireRows(host);
    },
  };
})();
