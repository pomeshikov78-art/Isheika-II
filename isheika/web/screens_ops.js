/* ИЩЕЙКА НТР AI — экраны эксплуатации (ROADMAP P6, ред. 1.3).
   UI-31 «Эксплуатация: SLO, алерты, резервные копии».

   Все показатели приходят с сервера готовыми: браузер не пересчитывает
   доступность, бюджет ошибок и скорость его расхода (ТЗ-04 §3).
*/
window.Screens = window.Screens || {};
(function () {
  // App инициализируется позже (app.js грузится последним) — обращения только внутри render.
  const Screens = window.Screens;
  const esc = s => App.esc(s);

  const stateTag = s => App.tag(s === 'OK' ? 'в норме' : s === 'BREACH' ? 'ниже цели' :
    s === 'CRITICAL' ? 'критично' : 'нет данных',
    s === 'OK' ? 'ok' : s === 'NO_DATA' ? '' : 'err');

  // ============================================================ UI-31 Эксплуатация
  Screens.ops = {
    title: 'Эксплуатация: SLO и резервные копии', ui: 'UI-31', module: 'M30',
    group: 'Администрирование', right: 'logs.read',
    async render(host, params) {
      const tab = params.tab || 'slo';
      const tabs = [['slo', 'Доступность (SLO)'], ['alerts', 'Алерты'], ['backups', 'Резервные копии']];
      const head = App.card('Разделы', '<div class="row">' + tabs.map(([k, n]) =>
        `<a class="btn sm ${tab === k ? 'primary' : ''}" href="#/ops?tab=${k}">${n}</a>`).join('') + '</div>');

      // ---------------------------------------------------------- доступность
      if (tab === 'slo') {
        const d = await App.get('/api/v1/slo');
        const month = (d.windows || []).find(w => w.window === '30d') || {};
        host.innerHTML = head + `
          <div class="grid g4">
            ${App.kpi('Доступность за 30 суток', month.availability_pct == null ? '—' : App.num(month.availability_pct, 3) + ' %',
              'цель ' + App.num(d.target_pct, 1) + ' %')}
            ${App.kpi('Бюджет ошибок', App.num(d.error_budget_pct, 1) + ' %', 'допустимая доля отказов')}
            ${App.kpi('Израсходовано бюджета', month.error_budget_used_pct == null ? '—' : App.num(month.error_budget_used_pct, 1) + ' %',
              'за 30 суток')}
            ${App.kpi('Самопроверок', d.probes_total ?? 0, 'шаг ' + d.probe_interval_sec + ' с')}
          </div>
          ${App.alert(month.state === 'BREACH' ? 'error' : month.state === 'NO_DATA' ? 'warn' : 'info',
            'Состояние SLO: ' + stateTag(month.state) + '. ' + esc(d.measurement_note || '') +
            ' Оценка простоя — расчётная: число отказов, умноженное на период самопроверки.')}
          ${App.card('Окна наблюдения', '<div id="ops-win"></div>')}
          ${App.card('Подсистемы за 24 часа', '<div id="ops-comp"></div>')}
          ${App.card('Скорость расхода бюджета ошибок', App.kv({
            'За 1 час': d.burn_rate_1h && d.burn_rate_1h.burn_rate != null ? App.num(d.burn_rate_1h.burn_rate, 2) + '×' : 'нет данных',
            'За 6 часов': d.burn_rate_6h && d.burn_rate_6h.burn_rate != null ? App.num(d.burn_rate_6h.burn_rate, 2) + '×' : 'нет данных',
            'Порог тревоги': App.num((d.burn_rate_1h || {}).threshold || 14.4, 1) + '×',
            'Измерений за час': (d.burn_rate_1h || {}).probes ?? 0,
          }) + '<p class="tiny">Burn rate = доля отказов / допустимая доля отказов. Значение 1× означает расход бюджета ровно за месяц.</p>')}
          ${App.card('Последние самопроверки', '<div id="ops-last"></div>')}
          <div class="row"><button class="btn sm" id="ops-probe">Выполнить самопроверки сейчас</button>
            <a class="btn sm" href="${App.fileURL('/metrics', {})}">Метрики Prometheus</a></div>`;
        App.table('ops-win', {
          rows: d.windows || [], size: 10, search: false, export: 'slo_windows',
          cols: [{k: 'window', t: 'Окно'}, {k: 'probes', t: 'Измерений', cls: 'num'},
            {k: 'failed', t: 'Отказов', cls: 'num'},
            {k: 'availability_pct', t: 'Доступность, %', cls: 'num', r: r => r.availability_pct == null ? '—' : App.num(r.availability_pct, 3)},
            {k: 'error_budget_used_pct', t: 'Бюджет израсходован, %', cls: 'num', r: r => r.error_budget_used_pct == null ? '—' : App.num(r.error_budget_used_pct, 1)},
            {k: 'estimated_downtime_minutes', t: 'Простой (оценка), мин', cls: 'num'},
            {k: 'state', t: 'Состояние', r: r => stateTag(r.state)}],
        });
        App.table('ops-comp', {
          rows: d.components || [], size: 10, search: false, export: 'slo_components',
          cols: [{k: 'component', t: 'Подсистема'}, {k: 'probes', t: 'Измерений', cls: 'num'},
            {k: 'failed', t: 'Отказов', cls: 'num'},
            {k: 'availability_pct', t: 'Доступность, %', cls: 'num', r: r => r.availability_pct == null ? '—' : App.num(r.availability_pct, 3)},
            {k: 'latency_ms_avg', t: 'Средняя проверка, мс', cls: 'num', r: r => App.num(r.latency_ms_avg, 2)},
            {k: 'state', t: 'Состояние', r: r => stateTag(r.state)}],
        });
        const last = Object.entries(d.last_probes || {}).map(([c, r]) => ({
          component: c, ok: r ? !!r.ok : null, at: r ? r.at : null, detail: r ? r.detail : 'проверок не было',
          latency_ms: r ? r.latency_ms : null,
        }));
        App.table('ops-last', {
          rows: last, size: 10, search: false,
          cols: [{k: 'component', t: 'Подсистема'},
            {k: 'ok', t: 'Результат', r: r => r.ok == null ? App.tag('нет данных') : r.ok ? App.tag('успех', 'ok') : App.tag('отказ', 'err')},
            {k: 'at', t: 'Время', r: r => r.at ? App.dt(r.at) : '—'},
            {k: 'latency_ms', t: 'мс', cls: 'num', r: r => r.latency_ms == null ? '—' : App.num(r.latency_ms, 2)},
            {k: 'detail', t: 'Подробности', r: r => `<span class="tiny">${esc(r.detail || '')}</span>`}],
        });
        document.getElementById('ops-probe').addEventListener('click', async () => {
          await App.api('/api/v1/slo/probes', {method: 'POST', body: {}});
          App.toast('Самопроверки выполнены', 'ok');
          App.go('ops', {tab: 'slo'});
        });
        App.ctxObject('SLO', {'Цель': App.num(d.target_pct, 1) + ' %',
          'Доступность 30 сут': month.availability_pct == null ? 'нет данных' : App.num(month.availability_pct, 3) + ' %',
          'Состояние': month.state});
        return;
      }

      // ---------------------------------------------------------- алерты
      if (tab === 'alerts') {
        const d = await App.get('/api/v1/alerts', {state: params.state || 'active'});
        const rules = Object.entries(d.rules || {}).map(([code, r]) => ({code, ...r}));
        host.innerHTML = head + `
          ${App.card('Фильтр', `<div class="row">
            <select id="al-state">${[['active', 'Активные'], ['open', 'Не подтверждённые'], ['acknowledged', 'Подтверждённые'], ['closed', 'Закрытые'], ['all', 'Все']].map(([k, n]) => `<option value="${k}" ${(params.state || 'active') === k ? 'selected' : ''}>${n}</option>`).join('')}</select>
            <button class="btn sm" id="al-eval">Пересчитать правила</button></div>`)}
          ${App.alert('info', 'Алерт открывается по детерминированному правилу и закрывается только при устранении причины. Подтверждение оператором не закрывает алерт. В столбце «Основание» — числа, по которым принято решение.')}
          ${App.card('Алерты (' + (d.items || []).length + ')', (d.items || []).length ? '<div id="al-tbl"></div>' : App.empty('Активных алертов нет', '✅'))}
          ${App.card('Правила оповещения', '<div id="al-rules"></div>')}`;
        if ((d.items || []).length) App.table('al-tbl', {
          rows: d.items, size: 20, export: 'ops_alerts', sort: 'opened_at',
          cols: [{k: 'opened_at', t: 'Открыт', r: r => App.dt(r.opened_at)},
            {k: 'rule_code', t: 'Правило', r: r => `<code>${esc(r.rule_code)}</code>`},
            {k: 'severity', t: 'Важность', r: r => App.tag(r.severity === 'critical' ? 'критично' : 'предупреждение', r.severity === 'critical' ? 'err' : 'warn')},
            {k: 'state', t: 'Состояние', r: r => App.statusTag(r.state)},
            {k: 'message', t: 'Сообщение'},
            {k: 'context', t: 'Основание', r: r => `<span class="tiny">${esc(App.short(JSON.stringify(r.context || {}), 160))}</span>`},
            {k: 'ack_by', t: 'Подтвердил', r: r => r.ack_by ? esc(r.ack_by) + ' · ' + App.dt(r.ack_at) : '—'},
            {k: 'id', t: 'Действие', r: r => r.state === 'open' ? `<button class="btn sm" data-ack="${esc(r.id)}">Подтвердить</button>` : '—'}],
        });
        App.table('al-rules', {
          rows: rules, size: 20, search: false,
          cols: [{k: 'code', t: 'Код', r: r => `<code>${esc(r.code)}</code>`}, {k: 'title', t: 'Условие'},
            {k: 'severity', t: 'Важность', r: r => App.tag(r.severity, r.severity === 'critical' ? 'err' : 'warn')}],
        });
        document.getElementById('al-state').addEventListener('change', e => App.go('ops', {tab: 'alerts', state: e.target.value}));
        document.getElementById('al-eval').addEventListener('click', async () => {
          const r = await App.api('/api/v1/alerts/evaluate', {method: 'POST', body: {}});
          App.toast('Открыто: ' + (r.opened || []).length + ', закрыто: ' + (r.closed || []).length, 'ok');
          App.go('ops', {tab: 'alerts', state: params.state || 'active'});
        });
        host.querySelectorAll('[data-ack]').forEach(b => b.addEventListener('click', async () => {
          await App.api('/api/v1/alerts/' + encodeURIComponent(b.dataset.ack) + '/acknowledge', {method: 'POST', body: {}});
          App.toast('Алерт подтверждён', 'ok');
          App.go('ops', {tab: 'alerts', state: params.state || 'active'});
        }));
        App.ctxObject('Алерты', {'Активных': (d.items || []).length, 'Правил': rules.length});
        return;
      }

      // ---------------------------------------------------------- резервные копии
      const d = await App.get('/api/v1/backups');
      host.innerHTML = head + `
        ${App.alert('info', 'Резервная копия включает согласованный снимок БД, зашифрованные ключи и конфигурацию с контрольными суммами. Восстановление выполняется при остановленном сервере: <code>run.py --restore ID --yes</code>; перед записью автоматически снимается копия текущего состояния.')}
        ${App.card('Регламент', App.kv({
          'Максимальная давность копии': ((d.policy || {}).max_age_hours || 168) + ' ч',
          'Копий в реестре': d.total ?? 0,
          'Правило': 'BACKUP_OVERDUE — предупреждение при просрочке',
        }))}
        <div class="row"><button class="btn sm primary" id="bk-new">Создать копию сейчас</button></div>
        ${App.card('Резервные копии', (d.items || []).length ? '<div id="bk-tbl"></div>' : App.empty('Копий ещё нет', '🗄'))}`;
      if ((d.items || []).length) App.table('bk-tbl', {
        rows: d.items, size: 20, export: 'ops_backups', sort: 'created_at',
        cols: [{k: 'created_at', t: 'Создана', r: r => App.dt(r.created_at)},
          {k: 'file_name', t: 'Файл', r: r => `<span class="tiny">${esc(r.file_name || '')}</span>`},
          {k: 'kind', t: 'Тип', r: r => App.statusTag(r.kind || 'manual')},
          {k: 'size_bytes', t: 'Размер, Б', cls: 'num'},
          {k: 'sha256', t: 'Контрольная сумма', r: r => `<code>${esc(String(r.sha256 || '').slice(0, 16))}…</code>`},
          {k: 'verified_at', t: 'Проверка', r: r => r.verified_at ? App.dt(r.verified_at) : 'не проверялась'},
          {k: 'exists', t: 'Файл', r: r => r.exists ? App.tag('на месте', 'ok') : App.tag('отсутствует', 'err')},
          {k: 'id', t: 'Действие', r: r => `<button class="btn sm" data-verify="${esc(r.id)}">Проверить</button>`}],
      });
      document.getElementById('bk-new').addEventListener('click', async () => {
        const r = await App.api('/api/v1/backups', {method: 'POST', body: {kind: 'manual'}});
        App.toast('Копия создана, проверка: ' + (r.verify && r.verify.ok ? 'пройдена' : 'НЕ пройдена'),
          r.verify && r.verify.ok ? 'ok' : 'error');
        App.go('ops', {tab: 'backups'});
      });
      host.querySelectorAll('[data-verify]').forEach(b => b.addEventListener('click', async () => {
        const r = await App.api('/api/v1/backups/' + encodeURIComponent(b.dataset.verify) + '/verify', {method: 'POST', body: {}});
        App.toast('Проверка: ' + (r.ok ? 'пройдена' : 'НЕ пройдена'), r.ok ? 'ok' : 'error');
        App.go('ops', {tab: 'backups'});
      }));
      App.ctxObject('Резервные копии', {'Копий': d.total ?? 0,
        'Последняя': (d.items || [])[0] ? App.dt(d.items[0].created_at) : '—'});
    },
  };
})();
