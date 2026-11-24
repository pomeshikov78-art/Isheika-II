/* ИЩЕЙКА НТР AI — экраны редакции v1.1 (ведомость ИД-01…ИД-12):
   UI-27 Реестр методик, UI-28 Независимость доказательств, UI-29 Воспроизводимость,
   UI-30 Дедупликация и кластеры документов.
   Все научные показатели приходят из серверного ядра; браузер их не пересчитывает. */
window.Screens = window.Screens || {};
(() => {
  const esc = s => App.esc(s);
  const tabsHTML = (route, items, active, params = {}) =>
    `<div class="tabs">${items.map(i => `<button class="${i.k === active ? 'on' : ''}" onclick="App.go('${route}',${esc(JSON.stringify({...params, tab: i.k}))})">${esc(i.t)}</button>`).join('')}</div>`;
  async function scaffold(body, extra = '') {
    const rid = await App.needResearch(body);
    if (!rid) return null;
    body.innerHTML = App.researchBar(extra) + '<div id="rs-body">' + App.spinner() + '</div>';
    App.wireResearchBar(body);
    return document.getElementById('rs-body');
  }

  // ============================================================ UI-27 Реестр методик (ИД-09)
  Screens.methodologies = {
    title: 'Реестр методик и версий', ui: 'UI-27', module: 'M32 / M17', group: 'Администрирование', right: 'analytics.read',
    async render(body, params) {
      body.innerHTML = App.spinner();
      const d = await App.get('/api/v1/methodologies');
      const items = d.items || [];
      const active = items.filter(m => m.is_active);
      const code = params.code || (active[0] || {}).code;
      let detail = null;
      if (code) { try { detail = await App.get('/api/v1/methodologies/' + encodeURIComponent(code)); } catch (e) { detail = null; } }
      body.innerHTML = `
        <div class="grid g4">
          ${App.kpi('Методик в реестре', items.length, 'версионируемые объекты')}
          ${App.kpi('Активных', active.length, 'используются расчётным ядром')}
          ${App.kpi('Валидировано', items.filter(m => m.approval_status === 'VALIDATED').length, 'прошли калибровку')}
          ${App.kpi('Стартовых (PROVISIONAL)', items.filter(m => m.approval_status === 'PROVISIONAL').length, 'калибровка не завершена')}
        </div>
        ${App.alert('info', 'ИД-09: изменение весов или порогов создаёт НОВУЮ версию методики. Ранее рассчитанные результаты сохраняют ссылку на исходную версию и не переписываются. Пересчёт выполняется явной операцией.')}
        ${App.card('Активные методики', '<div id="m-tbl"></div>')}
        <div id="m-detail"></div>`;
      App.table('m-tbl', {
        rows: items, size: 20, export: 'methodologies',
        cols: [
          {k: 'code', t: 'Код', r: m => `<a href="#/methodologies?code=${esc(m.code)}">${esc(m.code)}</a>`},
          {k: 'version', t: 'Версия'}, {k: 'name', t: 'Назначение'},
          {k: 'approval_status', t: 'Статус утверждения', r: m => App.statusTag(m.approval_status)},
          {k: 'is_active', t: 'Активна', r: m => m.is_active ? App.tag('да', 'ok') : App.tag('нет', '')},
          {k: 'config_checksum', t: 'Контрольная сумма', r: m => '<code>' + esc(String(m.config_checksum).slice(0, 16)) + '</code>'},
          {k: 'valid_from', t: 'Действует с', r: m => App.donly(m.valid_from)},
          {k: 'author_user_id', t: 'Автор'},
        ],
        onRow: m => App.go('methodologies', {code: m.code}),
      });
      if (detail) {
        const weights = (detail.parameters || {}).weights || {};
        const factors = (detail.parameters || {}).factors || [];
        App.setHTML('m-detail', `
          ${App.card('Методика ' + esc(detail.code) + ' ' + esc(detail.version), `
            ${App.kv({'Формула': esc((detail.formula_definition || {}).expression || '—'),
                      'Нормативный источник': esc((detail.formula_definition || {}).normative_source || '—'),
                      'Пороги': '<code>' + esc(JSON.stringify(detail.thresholds || {})) + '</code>',
                      'Контрольная сумма': '<code>' + esc(detail.config_checksum) + '</code>',
                      'Статус': App.statusTag(detail.approval_status)})}
            ${Object.keys(weights).length ? `<h4>Веса компонент</h4>${App.kv(weights)}` : ''}
            ${factors.length ? `<h4>Факторы и веса</h4>${App.kv(Object.fromEntries(factors.map(f => [f.code + ' · ' + f.name, f.weight])))}` : ''}
            ${(detail.validation_examples || []).length ? `<h4>Контрольные примеры</h4>
              <table class="tbl"><tr><th>Тест</th><th>Условие</th><th>Ожидаемый результат</th></tr>
              ${detail.validation_examples.map(x => `<tr><td>${esc(x.name)}</td><td class="tiny">${esc(JSON.stringify(Object.fromEntries(Object.entries(x).filter(([k]) => k !== 'name'))))}</td>
                <td class="tiny">${esc(x.expected_class || x.expected || x.expected_display_mode || '—')}</td></tr>`).join('')}</table>` : ''}
            ${App.can('analytics.write') ? `<div class="row" style="margin-top:10px">
              <button class="btn sm" id="m-validate">Отметить валидированной</button>
              <button class="btn sm" id="m-newver">Создать новую версию (изменить пороги)</button>
            </div>` : ''}`)}
          ${App.card('История версий', `<table class="tbl"><tr><th>Код</th><th>Версия</th><th>Статус</th><th>Активна</th><th>Дата</th><th>Изменение</th></tr>
            ${(detail.history || []).map(h => `<tr><td>${esc(h.code)}</td><td>${esc(h.version)}</td>
              <td>${App.statusTag(h.approval_status)}</td><td>${h.is_active ? '✓' : '—'}</td>
              <td>${esc(App.donly(h.created_at))}</td><td class="tiny">${esc(h.change_description || '')}</td></tr>`).join('')}</table>`)}`);
        document.getElementById('m-validate')?.addEventListener('click', async () => {
          try {
            await App.post(`/api/v1/methodologies/${detail.id}/approval`, {approval_status: 'VALIDATED'});
            App.toast('Статус методики обновлён', 'ok'); App.render();
          } catch (e) { App.toast(esc(e.message), 'error'); }
        });
        document.getElementById('m-newver')?.addEventListener('click', () => {
          App.modal('Новая версия методики ' + detail.code, `
            <p class="tiny muted">Изменение параметров создаёт новую версию; исторические результаты не изменяются (ИД-09).</p>
            <label class="fld"><span>Описание изменения</span><input id="mv-desc" value="Корректировка порогов по результатам калибровки"></label>
            <label class="fld"><span>Пороги (JSON)</span><textarea id="mv-th" rows="5">${esc(JSON.stringify(detail.thresholds || {}, null, 2))}</textarea></label>
            <button class="btn primary" id="mv-save">Создать версию</button>`);
          document.getElementById('mv-save').addEventListener('click', async () => {
            let th;
            try { th = JSON.parse(document.getElementById('mv-th').value); }
            catch (e) { App.toast('Некорректный JSON порогов', 'error'); return; }
            try {
              const r = await App.post(`/api/v1/methodologies/${encodeURIComponent(detail.code)}/versions`,
                {thresholds: th, description: document.getElementById('mv-desc').value});
              App.closeModal(); App.toast('Создана версия ' + r.code, 'ok'); App.go('methodologies', {code: r.code});
            } catch (e) { App.toast(esc(e.message), 'error'); }
          });
        });
        App.ctxObject('Методика', {'Код': esc(detail.code), 'Версия': esc(detail.version),
          'Статус': App.statusTag(detail.approval_status), 'Сумма': '<code>' + esc(String(detail.config_checksum).slice(0, 16)) + '</code>'});
      }
    },
  };

  // ============================================================ UI-28 Независимость доказательств (ИД-11)
  Screens.independence = {
    title: 'Независимость доказательств', ui: 'UI-28', module: 'M25', group: 'Знания и доказательства', right: 'analytics.read',
    async render(body) {
      const host = await scaffold(body); if (!host) return;
      const rid = App.S.researchId;
      const [g, an] = await Promise.all([App.get('/api/v1/independence-groups', {research_id: rid}),
        App.get(`/api/v1/analytics/${rid}`)]);
      const items = g.items || [];
      const summary = an.evidence_summary || {};
      const conf = an.confidence || [];
      host.innerHTML = `
        <div class="grid g4">
          ${App.kpi('Групп независимости', items.length, 'перепечатки учтены как одна')}
          ${App.kpi('Доказательств', summary.total ?? 0, 'всего записей Evidence')}
          ${App.kpi('Производных', ((summary.by_origin || {}).REPRINT || 0) + ((summary.by_origin || {}).SUMMARY || 0) + ((summary.by_origin || {}).DERIVATIVE || 0), 'перепечатки, пересказы, производные')}
          ${App.kpi('Противоречий', (summary.by_status || {}).CONTRADICTED ?? 0, 'сохраняются, не усредняются')}
        </div>
        ${App.alert('info', 'ИД-11: несколько публикаций, пересказывающих один пресс-релиз, не являются независимыми подтверждениями. Уверенность и покрытие рассчитываются по числу НЕЗАВИСИМЫХ групп.')}
        ${App.card('Уверенность по показателям (ИД-10)', conf.length ? `<table class="tbl">
          <tr><th>Показатель</th><th>Уверенность</th><th>Независимых групп</th><th>Доказательств</th><th>Ограничения</th></tr>
          ${conf.map(c => `<tr><td>${esc(c.subject_kind)}</td><td class="num">${App.num(c.confidence, 3)}</td>
            <td class="num">${c.independent_groups}</td><td class="num">${c.evidence_count}</td>
            <td class="tiny">${(c.limitations || []).map(esc).join('; ') || '—'}</td></tr>`).join('')}</table>`
          : App.empty('Уверенность ещё не рассчитана', '🧮'))}
        ${App.card('Группы и состав', items.length ? items.map(gr => `
          <details class="acc"><summary>${esc(gr.group_key)} — ${gr.members} материал(ов) ${App.statusTag(gr.origin_class)}</summary>
            <div class="tiny muted">Первоисточник: ${esc(gr.primary_source_ref || '—')} · основание: ${esc(gr.basis || '')}</div>
            <table class="tbl"><tr><th>Документ</th><th>Класс доказательства</th><th>Происхождение</th><th>Дата</th></tr>
            ${(gr.documents || []).map(d => `<tr><td><a href="#/document/${esc(d.id)}">${esc(App.short(d.title, 80))}</a></td>
              <td>${esc(d.evidence_class)}</td><td>${App.statusTag(d.origin_class)}</td><td>${esc(App.donly(d.published_at))}</td></tr>`).join('')}
            </table></details>`).join('') : App.empty('Группы не сформированы', '🧾'))}`;
      App.ctxObject('Независимость', {'Групп': items.length, 'Доказательств': summary.total ?? 0},
        '<div class="tiny muted" style="margin-top:8px">Первичный источник предпочтительнее пересказа; противоречия сохраняются.</div>');
    },
  };

  // ============================================================ UI-29 Воспроизводимость (ИД-12)
  Screens.reproducibility = {
    title: 'Воспроизводимость и версии расчётов', ui: 'UI-29', module: 'M32', group: 'Администрирование', right: 'analytics.read',
    async render(body, params) {
      const tab = params.tab || 'runs';
      const host = await scaffold(body); if (!host) return;
      const rid = App.S.researchId;
      const [runs, trl, fea] = await Promise.all([
        App.get('/api/v1/research-runs', {research_id: rid}),
        App.get('/api/v1/trl-assessments', {research_id: rid}),
        App.get('/api/v1/feasibility-assessments', {research_id: rid})]);
      host.innerHTML = tabsHTML('reproducibility', [{k: 'runs', t: 'Запуски исследования'},
        {k: 'versions', t: 'Сравнение версий расчётов'}, {k: 'replay', t: 'Повторный расчёт'}], tab, {rid}) +
        '<div id="rp-box">' + App.spinner() + '</div>';
      const box = document.getElementById('rp-box');
      if (tab === 'runs') {
        const items = runs.items || [];
        box.innerHTML = App.alert('info', 'ИД-12: каждый запуск фиксирует версию набора документов, версии методик, моделей и промптов, параметры и контрольные суммы. Повторный расчёт на том же снимке обязан давать идентичный результат.') +
          (items.length ? '<div id="run-tbl"></div>' : App.empty('Запуски не зафиксированы', '🧪'));
        if (items.length) App.table('run-tbl', {
          rows: items, size: 20, export: 'research_runs',
          cols: [{k: 'id', t: 'run_id', r: r => '<code>' + esc(String(r.id).slice(0, 16)) + '</code>'},
            {k: 'document_set_version', t: 'Версия набора документов', r: r => '<code>' + esc(String(r.document_set_version).slice(0, 16)) + '</code>'},
            {k: 'methodology_versions', t: 'Методики', r: r => '<span class="tiny">' + esc(Object.values(r.methodology_versions || {}).join(', ')) + '</span>'},
            {k: 'prompt_versions', t: 'Промпты', r: r => '<span class="tiny">' + esc(Object.entries(r.prompt_versions || {}).map(([k, v]) => k + ':' + v).join(', ') || '—') + '</span>'},
            {k: 'status', t: 'Статус', r: r => App.statusTag(r.status)},
            {k: 'started_at', t: 'Начало'}, {k: 'finished_at', t: 'Завершение'},
            {k: 'output_checksum', t: 'Сумма результата', r: r => '<code>' + esc(String(r.output_checksum || '').slice(0, 12)) + '</code>'}],
          onRow: r => App.ctxObject('Запуск', {'run_id': '<code>' + esc(r.id) + '</code>',
            'Набор документов': '<code>' + esc(r.document_set_version) + '</code>',
            'Параметры': '<code>' + esc(JSON.stringify(r.parameters || {})) + '</code>'}),
        });
      } else if (tab === 'versions') {
        const th = trl.history || [], fh = fea.history || [];
        box.innerHTML = App.alert('info', 'Каждый пересчёт создаёт новую запись с новой версией методики. Исторические результаты не переписываются (ИД-09).') +
          App.card('История TRL', th.length ? '<div id="trl-h"></div>' : App.empty('Нет расчётов TRL', '📶')) +
          App.card('История реализуемости', fh.length ? '<div id="fea-h"></div>' : App.empty('Нет расчётов реализуемости', '⚖️'));
        if (th.length) App.table('trl-h', {rows: th, size: 20, export: 'trl_history', search: false,
          cols: [{k: 'created_at', t: 'Дата'}, {k: 'trl', t: 'TRL', cls: 'num'},
            {k: 'confidence', t: 'Уверенность', cls: 'num', r: r => App.num(r.confidence, 3)},
            {k: 'methodology_version', t: 'Методика'},
            {k: 'input_hash', t: 'Хеш входов', r: r => '<code>' + esc(String(r.input_hash || '').slice(0, 12)) + '</code>'},
            {k: 'output_hash', t: 'Хеш результата', r: r => '<code>' + esc(String(r.output_hash || '').slice(0, 12)) + '</code>'}]});
        if (fh.length) App.table('fea-h', {rows: fh, size: 20, export: 'feasibility_history', search: false,
          cols: [{k: 'created_at', t: 'Дата'}, {k: 'score', t: 'F', cls: 'num', r: r => r.score == null ? App.tag('NULL', 'warn') : App.num(r.score, 2)},
            {k: 'coverage', t: 'Покрытие C', cls: 'num', r: r => App.pct(r.coverage)},
            {k: 'interpretation_allowed', t: 'Интерпретация', r: r => r.interpretation_allowed ? App.tag('разрешена', 'ok') : App.tag('ограничена', 'warn')},
            {k: 'methodology_version', t: 'Методика'},
            {k: 'output_hash', t: 'Хеш результата', r: r => '<code>' + esc(String(r.output_hash || '').slice(0, 12)) + '</code>'}]});
        box.insertAdjacentHTML('beforeend', App.card('Сравнение двух расчётов', `
          <div class="diff-select">
            <select id="df-kind"><option value="feasibility">Реализуемость (F)</option><option value="trl">TRL</option></select>
            <select id="df-a"></select><span class="muted">→</span><select id="df-b"></select>
            <button class="btn sm primary" id="df-run">Сравнить</button>
          </div><div id="df-out" class="tiny muted" style="margin-top:10px">Выберите две записи и нажмите «Сравнить».</div>`));
        const hist = {feasibility: fh, trl: th};
        const fillSelects = () => {
          const kind = document.getElementById('df-kind').value;
          const rows = hist[kind] || [];
          const label = r => App.dt(r.created_at) + ' · ' + (kind === 'trl' ? ('TRL ' + r.trl) : ('F ' + (r.score == null ? 'NULL' : r.score))) + ' · ' + (r.methodology_version || '');
          ['df-a', 'df-b'].forEach((id, i) => {
            const el = document.getElementById(id);
            el.innerHTML = rows.map(r => `<option value="${esc(r.id)}">${esc(label(r))}</option>`).join('') || '<option value="">нет расчётов</option>';
            if (rows.length > 1 && i === 1) el.selectedIndex = 1;
          });
        };
        fillSelects();
        document.getElementById('df-kind').addEventListener('change', fillSelects);
        document.getElementById('df-run').addEventListener('click', async () => {
          const out = document.getElementById('df-out');
          const kind = document.getElementById('df-kind').value;
          const a = document.getElementById('df-a').value, b = document.getElementById('df-b').value;
          if (!a || !b) { out.innerHTML = App.alert('warn', 'Нет двух записей для сравнения.'); return; }
          out.innerHTML = App.spinner('Сравнение…');
          try {
            const d = await App.get('/api/v1/assessments/diff', {kind, a, b});
            out.innerHTML = (d.identical_result ? App.alert('ok', 'Результаты идентичны (совпадает хеш результата).')
              : App.alert('info', 'Результаты различаются — ниже построчное сравнение.')) +
              App.kv({'Методика A': esc(d.a.methodology || '—'), 'Методика B': esc(d.b.methodology || '—'),
                      'Методика изменена': d.methodology_changed ? App.tag('да', 'warn') : App.tag('нет', 'ok'),
                      'Набор документов изменён': d.document_set_changed ? App.tag('да', 'warn') : App.tag('нет', 'ok'),
                      'Хеш результата A': '<code>' + esc(String(d.a.output_hash || '').slice(0, 16)) + '</code>',
                      'Хеш результата B': '<code>' + esc(String(d.b.output_hash || '').slice(0, 16)) + '</code>'}) +
              '<div id="df-deltas"></div>';
            out.insertAdjacentHTML('beforeend', (d.factors || []).length ? '<h4>Факторы</h4><div id="df-factors"></div>' : '');
            out.insertAdjacentHTML('beforeend', (d.criteria || []).length ? '<h4>Изменившиеся критерии TRL</h4><div id="df-crit"></div>' : '');
            App.table('df-deltas', {rows: d.deltas || [], size: 20, search: false, export: 'assessment_diff',
              cols: [{k: 'field', t: 'Показатель'}, {k: 'a', t: 'A', cls: 'num', r: r => esc(JSON.stringify(r.a))},
                {k: 'b', t: 'B', cls: 'num', r: r => esc(JSON.stringify(r.b))},
                {k: 'delta', t: 'Δ', cls: 'num', r: r => r.delta == null ? '—' : App.num(r.delta, 4)},
                {k: 'changed', t: 'Изменено', r: r => r.changed ? App.tag('да', 'warn') : App.tag('нет', 'ok')}]});
            if ((d.factors || []).length) App.table('df-factors', {rows: d.factors, size: 20, search: false, export: 'assessment_diff_factors',
              cols: [{k: 'code', t: 'Фактор'}, {k: 'name', t: 'Название'},
                {k: 'x_a', t: 'x A', cls: 'num', r: r => r.x_a == null ? App.tag('неизвестно', '') : App.num(r.x_a, 2)},
                {k: 'x_b', t: 'x B', cls: 'num', r: r => r.x_b == null ? App.tag('неизвестно', '') : App.num(r.x_b, 2)},
                {k: 'weight_a', t: 'вес A', cls: 'num', r: r => App.num(r.weight_a, 3)},
                {k: 'weight_b', t: 'вес B', cls: 'num', r: r => App.num(r.weight_b, 3)},
                {k: 'changed', t: 'Изменено', r: r => r.changed ? App.tag('да', 'warn') : App.tag('нет', 'ok')}]});
            if ((d.criteria || []).length) App.table('df-crit', {rows: d.criteria, size: 20, search: false, export: 'assessment_diff_criteria',
              cols: [{k: 'criterion_code', t: 'Критерий'}, {k: 'level', t: 'Уровень', cls: 'num'},
                {k: 'confirmed_a', t: 'A', r: r => r.confirmed_a ? App.tag('подтверждён', 'ok') : App.tag('нет', 'warn')},
                {k: 'confirmed_b', t: 'B', r: r => r.confirmed_b ? App.tag('подтверждён', 'ok') : App.tag('нет', 'warn')},
                {k: 'text', t: 'Формулировка', r: r => esc(App.short(r.text, 90))}]});
          } catch (e) { out.innerHTML = App.alert('error', esc(e.message)); }
        });
      } else {
        const f = (fea.latest || {}), t = (trl.latest || {});
        box.innerHTML = App.alert('info', 'Повторный расчёт выполняется по сохранёнённому снимку и ИСХОДНОЙ версии методики. Историческая запись не изменяется; результат сравнения показывается ниже.') +
          App.card('Проверка воспроизводимости', `
            <div class="row">
              <button class="btn sm primary" id="rp-fea" ${f.id ? '' : 'disabled'}>Повторить расчёт реализуемости</button>
              <button class="btn sm primary" id="rp-trl" ${t.id ? '' : 'disabled'}>Повторить расчёт TRL</button>
            </div><div id="rp-res" class="tiny muted" style="margin-top:10px">Результат появится здесь.</div>`);
        const run = async (kind, id) => {
          const out = document.getElementById('rp-res');
          out.innerHTML = App.spinner('Повторный расчёт…');
          try {
            const r = await App.post('/api/v1/replay', {kind, assessment_id: id});
            out.innerHTML = (r.identical ? App.alert('ok', 'Результаты идентичны — воспроизводимость подтверждена (REPR-01).')
              : App.alert('warn', 'Результаты различаются — требуется разбор причин.')) +
              App.kv({'Исходный': '<code>' + esc(JSON.stringify(r.original)) + '</code>',
                      'Повторный': '<code>' + esc(JSON.stringify(r.recomputed)) + '</code>',
                      'Методика': '<code>' + esc(r.methodology_id || '—') + '</code>'});
          } catch (e) { out.innerHTML = App.alert('error', esc(e.message)); }
        };
        document.getElementById('rp-fea')?.addEventListener('click', () => run('feasibility', f.id));
        document.getElementById('rp-trl')?.addEventListener('click', () => run('trl', t.id));
      }
    },
  };

  // ============================================================ UI-30 Дедупликация (ИД-03)
  Screens.dedup = {
    title: 'Дедупликация и версии документов', ui: 'UI-30', module: 'M10', group: 'Поиск и источники', right: 'research.read',
    async render(body, params) {
      const tab = (params || {}).tab || 'clusters';
      const host = await scaffold(body); if (!host) return;
      const rid = App.S.researchId;
      const [cl, rel] = await Promise.all([App.get('/api/v1/document-clusters', {research_id: rid}),
        App.get('/api/v1/document-relations', {research_id: rid})]);
      const sm = cl.summary || {};
      host.innerHTML = tabsHTML('dedup', [{k: 'clusters', t: 'Кластеры и связи'},
        {k: 'graph', t: 'Граф связей'}], tab, {rid}) + '<div id="dd-box">' + App.spinner() + '</div>';
      const box = document.getElementById('dd-box');
      if (tab === 'graph') {
        const types = (params.types || '').split(',').filter(Boolean);
        const gr = await App.get('/api/v1/document-graph', {research_id: rid, types: types.join(',')});
        box.innerHTML = App.alert('info', 'Граф показывает связи версий и производных материалов (ИД-03). Фильтр типов применяется на сервере; щелчок по узлу открывает карточку документа. Изолированных документов: ' + (gr.isolated ?? 0) + '.') +
          App.card('Фильтр типов связей', '<div class="row" id="gr-types">' +
            (gr.types || []).map(t => `<label class="chk"><input type="checkbox" data-type="${esc(t.type)}" ${t.selected ? 'checked' : ''}> ${esc(t.type)} <span class="tiny muted">(${t.count})</span></label>`).join('') +
            ((gr.types || []).length ? '' : '<span class="tiny muted">Связи не обнаружены</span>') +
            '<button class="btn sm" id="gr-apply">Применить</button></div>') +
          App.card('Граф связей документов', Charts.network(gr.nodes || [], gr.edges || [])) +
          App.card('Рёбра графа (текстовая альтернатива и экспорт)', (gr.edges || []).length ? '<div id="gr-tbl"></div>' : App.empty('Связей нет', '🔗'));
        document.getElementById('gr-apply').addEventListener('click', () => {
          const sel = [...document.querySelectorAll('#gr-types input:checked')].map(i => i.dataset.type);
          App.go('dedup', {rid, tab: 'graph', types: sel.join(',')});
        });
        if ((gr.edges || []).length) App.table('gr-tbl', {
          rows: gr.edges.map(e => {
            const na = (gr.nodes || []).find(n => n.id === e.source) || {};
            const nb = (gr.nodes || []).find(n => n.id === e.target) || {};
            return {...e, from_title: na.title, to_title: nb.title};
          }), size: 25, export: 'document_graph',
          cols: [{k: 'from_title', t: 'Документ', r: r => `<a href="#/document/${esc(r.source)}">${esc(App.short(r.from_title, 60))}</a>`},
            {k: 'type', t: 'Тип связи', r: r => App.statusTag(r.type)},
            {k: 'to_title', t: 'Связан с', r: r => `<a href="#/document/${esc(r.target)}">${esc(App.short(r.to_title, 60))}</a>`},
            {k: 'confidence', t: 'Уверенность', cls: 'num', r: r => App.num(r.confidence, 2)},
            {k: 'basis', t: 'Основание'}, {k: 'decided_by', t: 'Кем решено'}],
        });
        App.ctxObject('Граф связей', {'Узлов': (gr.nodes || []).length, 'Рёбер': (gr.edges || []).length,
          'Кластеров': gr.clusters ?? 0, 'Изолированных': gr.isolated ?? 0});
        return;
      }
      box.innerHTML = `
        <div class="grid g4">
          ${App.kpi('Логических документов', sm.logical_documents ?? 0, 'уникальные материалы')}
          ${App.kpi('Вхождений', sm.occurrences ?? 0, 'источник + URL + дата')}
          ${App.kpi('Объединено', sm.merged ?? 0, 'повторных обнаружений')}
          ${App.kpi('Связей', (rel.items || []).length, 'версии, переводы, пересказы')}
        </div>
        ${App.alert('info', 'ИД-03: физическое содержимое (blob) ≠ логический документ ≠ вхождение. Препринт и опубликованная версия сохраняются как связанные документы; каждое обнаружение сохраняется для аудита происхождения.')}
        ${App.card('Связи между документами', (rel.items || []).length ? '<div id="rel-tbl"></div>' : App.empty('Связи не обнаружены', '🔗'))}
        ${App.card('Кластеры', (cl.items || []).length ? (cl.items || []).map(c => `
          <details class="acc"><summary>${esc(App.short(c.title || c.cluster_key, 80))} ${App.statusTag(c.cluster_type)}</summary>
            <table class="tbl"><tr><th>Документ</th><th>Связь</th><th>Уверенность</th><th>Кем решено</th><th>Вхождения</th></tr>
            ${(c.members || []).map(m => `<tr><td><a href="#/document/${esc(m.document_id)}">${esc(App.short(m.title, 70))}</a></td>
              <td>${App.statusTag(m.relation)}</td><td class="num">${App.num(m.confidence, 2)}</td><td>${esc(m.decided_by)}</td>
              <td class="tiny">${(m.occurrences || []).map(o => esc(o.source_code) + ' · ' + esc(App.short(o.url, 40))).join('<br>')}</td></tr>`).join('')}
            </table></details>`).join('') : App.empty('Кластеры не сформированы', '🧬'))}`;
      if ((rel.items || []).length) App.table('rel-tbl', {
        rows: rel.items, size: 25, export: 'document_relations',
        cols: [{k: 'from_title', t: 'Документ', r: r => `<a href="#/document/${esc(r.from_document_id)}">${esc(App.short(r.from_title, 60))}</a>`},
          {k: 'relation_type', t: 'Тип связи', r: r => App.statusTag(r.relation_type)},
          {k: 'to_title', t: 'Связан с', r: r => `<a href="#/document/${esc(r.to_document_id)}">${esc(App.short(r.to_title, 60))}</a>`},
          {k: 'confidence', t: 'Уверенность', cls: 'num', r: r => App.num(r.confidence, 2)},
          {k: 'basis', t: 'Основание'}, {k: 'decided_by', t: 'Кем решено'}],
      });
      App.ctxObject('Дедупликация', {'Логических документов': sm.logical_documents ?? 0,
        'Вхождений': sm.occurrences ?? 0, 'Кластеров': sm.clusters ?? 0});
    },
  };
})();
