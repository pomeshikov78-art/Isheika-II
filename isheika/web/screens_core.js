/* ИЩЕЙКА НТР AI — экраны ядра: UI-01…UI-09, UI-18…UI-20 (+ карточка исследования).
   Все научные значения приходят из серверного ядра; браузер их не пересчитывает. */
window.Screens = window.Screens || {};
(() => {
  const A = () => App;
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
  const docLink = d => {
    const ru = d.title_ru || d.title || d.id || d;
    const orig = d.title_ru && d.title_ru !== d.title ? d.title : '';
    return `<a href="#/document/${esc(d.id || d)}">${esc(App.short(ru, 90))}</a>`
      + (orig ? `<div class="tiny muted">${esc(App.short(orig, 80))}${d.translation_mode === 'terminology' ? ' · перевод терминологический' : d.translation_mode === 'ai_technical' ? ' · перевод ИИ' : ''}</div>` : '');
  };
  const evItem = e => `<div class="evidence-item">
      <div class="row">${App.statusTag(e.status)} ${App.tag(e.evidence_class || 'unknown')} ${App.tag('маркер ' + (e.marker || 'Д'))}
        ${e.quality != null ? `<span class="tiny muted">качество ${App.num(e.quality, 2)}</span>` : ''}
        ${e.independence_group ? `<span class="tiny muted">группа: ${esc(e.independence_group)}</span>` : ''}</div>
      ${e.quote ? `<q>${esc(App.short(e.quote, 320))}</q>` : ''}
      <div class="tiny muted">${esc(e.locator || '')} ${e.document_id ? `· <a href="#/document/${esc(e.document_id)}">документ</a>` : ''}
        ${e.url ? `· <a href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">первоисточник ↗</a>` : ''}
        ${e.archive_url ? `· <a href="${esc(e.archive_url)}" target="_blank" rel="noopener noreferrer">архив ↗</a>` : ''}</div></div>`;

  const TR_MODE = {original: 'оригинал на русском', terminology: 'терминологический перевод (черновик)',
                   ai_technical: 'перевод моделью ИИ'};

  function translationBlock(d) {
    const t = d.translation;
    if (!t) return '';
    if (t.mode === 'original') return '<p class="tiny muted" style="margin-top:6px">Материал на русском языке — перевод не требуется.</p>';
    const cov = t.coverage == null ? '—' : Math.round(t.coverage * 100) + ' %';
    const unknown = (t.untranslated || []).slice(0, 12);
    return `<div class="card" style="margin-top:10px;background:var(--panel-2)">
      <div class="row">${App.tag(TR_MODE[t.mode] || t.mode, t.mode === 'ai_technical' ? 'ok' : 'warn')}
        <span class="tiny muted">переведено ${cov} · словарь ${esc(t.glossary_version || '—')}${t.review_required ? ' · требует вычитки' : ''}</span></div>
      <p style="margin:6px 0"><b>${esc(t.title_ru || '')}</b></p>
      <p class="tiny">${esc(t.abstract_ru || '')}</p>
      ${unknown.length ? `<p class="tiny muted">Без перевода остались: ${esc(unknown.join(', '))}</p>` : ''}
      <details class="acc"><summary>Оригинал</summary>
        <p class="tiny">${esc(d.title || '')}</p><p class="tiny muted">${esc(d.abstract || '')}</p></details>
      <p class="tiny muted">Числа, единицы измерения и обозначения сохранены без изменений.</p>
    </div>`;
  }

  // ============================================================ UI-01 Главная панель
  Screens.dashboard = {
    title: 'Главная панель', ui: 'UI-01', module: 'M01', group: 'Обзор', right: 'research.read',
    async render(host) {
      const d = await App.get('/api/v1/system/dashboard');
      const c = (App.S.system || {}).counters || {};
      const jobs = {};
      (d.jobs || []).forEach(j => { jobs[j.status] = (jobs[j.status] || 0) + j.n; });
      const run = jobs.running || 0; App.S.jobsRunning = run;
      host.innerHTML = `
        <div class="grid g6">
          ${App.kpi('Исследования', c.researches ?? '—', `<a href="#/researches">база исследований</a>`)}
          ${App.kpi('Документы', c.documents ?? '—', 'в корпусе системы')}
          ${App.kpi('Источники', c.sources ?? '—', `<a href="#/sources">реестр</a> · коннекторов ${c.connectors ?? 0}`)}
          ${App.kpi('Страны', c.countries ?? '—', `<a href="#/countries">профили</a>`)}
          ${App.kpi('ИИ-провайдеры', d.providers_summary.active + '/' + d.providers_summary.total, `ключей: ${d.providers_summary.key_configured} · платных заблокировано: ${d.providers_summary.paid_blocked}`)}
          ${App.kpi('Доказательства', c.evidence ?? '—', `утверждений: ${c.claims ?? 0}`)}
        </div>
        <div class="grid g2" style="margin-top:14px">
          ${App.card('Последние исследования', '<div id="d-res"></div>', '<button class="btn sm primary" onclick="App.go(\'new\')">+ Новое</button>')}
          ${App.card('Состояние заданий (12 этапов ИВП)', '<div id="d-jobs"></div>' +
            `<div class="tiny muted">Статусы: queued / running / partial / completed / failed / cancelled. Прерванное исследование продолжается с незавершённых этапов.</div>`)}
        </div>
        <div class="grid g2">
          ${App.card('Новые документы', '<div id="d-docs"></div>')}
          ${App.card('Качество и калибровка', '<div id="d-quality"></div>' +
            App.alert('warn', 'Калибровка методик не завершена: пороги и веса стартовые (ТЗ-03 §8).'))}
        </div>
        <div class="grid g2">
          ${App.card('Покрытие реестра источников', Charts.bar((d.source_stats.by_category || []).map(x => ({label: x.category, value: x.n})), {unit: 'источников в категории', title: 'Источники по категориям'}))}
          ${App.card('Лента событий', (d.events || []).slice(0, 14).map(e => `<div class="evidence-item"><b>${esc(e.event_type)}</b>
            <span class="tiny muted">${App.dt(e.created_at)}</span><div class="tiny">${esc(App.short(JSON.stringify(e.payload || {}), 180))}</div></div>`).join('') || App.empty('Событий пока нет', '📡'))}
        </div>`;
      App.table('d-res', {
        rows: d.researches || [], sort: 'created_at', size: 8, export: 'researches',
        cols: [{k: 'title', t: 'Исследование', r: r => `<a href="#/research/${esc(r.id)}">${esc(App.short(r.title, 60))}</a>`},
          {k: 'status', t: 'Статус', r: r => App.statusTag(r.status)},
          {k: 'documents', t: 'Док.', cls: 'num', v: r => r.counts.documents},
          {k: 'direct', t: 'Прямых', cls: 'num', v: r => r.counts.direct},
          {k: 'created_at', t: 'Создано', r: r => App.dt(r.created_at)}],
        onRow: r => App.go('research', {id: r.id}),
      });
      App.table('d-jobs', {
        rows: d.jobs || [], size: 25, search: false, export: 'jobs',
        cols: [{k: 'stage', t: 'Этап'}, {k: 'status', t: 'Статус', r: r => App.statusTag(r.status)}, {k: 'n', t: 'Заданий', cls: 'num'}],
      });
      App.table('d-docs', {
        rows: d.recent_documents || [], size: 8, export: 'recent_documents',
        cols: [{k: 'title', t: 'Документ', r: docLink},
          {k: 'source_code', t: 'Источник'}, {k: 'country_code', t: 'Страна'},
          {k: 'state', t: 'Класс', r: r => App.statusTag(r.state)},
          {k: 'published_at', t: 'Дата', r: r => App.donly(r.published_at)}],
        onRow: r => App.go('document', {id: r.id}),
      });
      const q = d.quality || [];
      App.setHTML('d-quality', q.length ? `<table class="tbl"><tr><th>Метрика</th><th>Значение</th><th>Выборка</th><th>Калибровка</th></tr>
        ${q.map(x => `<tr><td>${esc(x.metric)}</td><td class="num">${x.value == null ? '—' : App.num(x.value, 3)}</td><td class="num">${x.sample_size}</td>
        <td>${x.calibrated ? App.tag('подтверждена', 'ok') : App.tag('не завершена', 'warn')}</td></tr>`).join('')}</table>`
        : App.empty('Метрики ещё не рассчитаны', '📏'));
      App.ctxObject('Система', {
        'Профиль': esc((App.S.system || {}).profile), 'Версия методики': esc((App.S.system || {}).methodology_version),
        'Коннекторов live': d.connectors_summary.live, 'Активных': d.connectors_summary.active,
        'Требуют ключ': d.connectors_summary.restricted, 'Событий': c.events,
      }, '<div class="tiny muted" style="margin-top:8px">Free-first: платные вызовы выключены по умолчанию и требуют явного согласия в настройках (UI-25).</div>');
    },
  };

  // ============================================================ M29 База исследований
  Screens.researches = {
    title: 'База исследований', ui: 'UI-01', module: 'M29', group: 'Обзор', right: 'research.read',
    async render(host, params) {
      const d = await App.get('/api/v1/researches', {limit: 200, status: params.status});
      App.S.researches = d.items || [];
      host.innerHTML = App.card('Исследования', '<div id="rs-list"></div>',
        `<select id="f-status" style="width:auto"><option value="">все статусы</option>${['draft', 'queued', 'running', 'partial', 'completed', 'failed', 'cancelled'].map(s => `<option value="${s}" ${params.status === s ? 'selected' : ''}>${App.STATUS_RU[s]}</option>`).join('')}</select>
         <button class="btn sm primary" onclick="App.go('new')">+ Новое исследование</button>`);
      document.getElementById('f-status').addEventListener('change', e => App.go('researches', {status: e.target.value}));
      App.table('rs-list', {
        rows: d.items || [], sort: 'created_at', size: 25, export: 'researches',
        cols: [{k: 'title', t: 'Название', r: r => `<a href="#/research/${esc(r.id)}">${esc(r.title)}</a>`},
          {k: 'research_type', t: 'Тип'}, {k: 'status', t: 'Статус', r: r => App.statusTag(r.status)},
          {k: 'countries', t: 'Стран', cls: 'num', v: r => (r.country_codes || []).length},
          {k: 'documents', t: 'Док.', cls: 'num', v: r => r.counts.documents},
          {k: 'direct', t: 'Прямых', cls: 'num', v: r => r.counts.direct},
          {k: 'forecast_horizon_years', t: 'Горизонт, лет', cls: 'num'},
          {k: 'methodology_version', t: 'Методика'},
          {k: 'created_at', t: 'Создано', r: r => App.dt(r.created_at)}],
        onRow: r => App.go('research', {id: r.id}),
        empty: 'Исследований нет. Создайте первое — кнопка «Новое исследование».',
      });
    },
  };

  // ============================================================ Карточка исследования
  Screens.research = {
    title: 'Карточка исследования', ui: 'UI-01', module: 'M29', group: 'Обзор', right: 'research.read',
    async render(host, params) {
      const rid = params.id || App.S.researchId;
      const st = await App.get(`/api/v1/researches/${rid}/status`);
      const r = st.research;
      App.setResearch(rid, true);
      const done = st.jobs.filter(j => j.status === 'completed').length;
      host.innerHTML = `
        <div class="grid g4">
          ${App.kpi('Статус', App.STATUS_RU[r.status] || r.status, 'этапов завершено: ' + done + '/' + st.jobs.length)}
          ${App.kpi('Документы', r.counts.documents, `прямых ${r.counts.direct} · смежных ${r.counts.adjacent}`)}
          ${App.kpi('TRL', r.trl ? r.trl.trl : '—', r.trl ? 'уверенность ' + App.num(r.trl.confidence, 2) : 'не рассчитан')}
          ${App.kpi('Реализуемость', r.feasibility ? App.num(r.feasibility.score, 1) + ' %' : '—', r.feasibility ? esc(r.feasibility.interpretation) : 'не рассчитана')}
        </div>
        ${App.card('Параметры', App.kv({
          'Название': esc(r.title), 'Тип': esc(r.research_type), 'Цель': esc(r.goal || '—'),
          'Запрос': esc((r.query || {}).raw_text), 'Версия запроса': (r.query || {}).query_version,
          'Период': App.donly(r.period_from) + ' … ' + App.donly(r.period_to),
          'Языки': esc((r.language_codes || []).join(', ')), 'Стран': (r.country_codes || []).length,
          'Горизонт прогноза': r.forecast_horizon_years + ' лет', 'Методика': esc(r.methodology_version),
          'Создано': App.dt(r.created_at), 'ID': '<code>' + esc(r.id) + '</code>',
        }), `<button class="btn sm" onclick="App.go('query')">Конструктор поиска</button>
             <button class="btn sm" onclick="App.go('results')">Результаты</button>
             <button class="btn sm" onclick="App.go('passport')">Паспорт</button>
             <button class="btn sm" onclick="App.go('report')">Отчёт</button>
             ${App.can('research.run') ? `<button class="btn sm primary" id="btn-run">▶ Запустить</button>
             <button class="btn sm" id="btn-resume">⟳ Продолжить</button>
             <button class="btn sm danger" id="btn-cancel">■ Отменить</button>` : ''}`)}
        ${App.card('Этапы информационно-вычислительного процесса', '<div id="rs-jobs"></div>')}
        ${App.card('Задания поиска по источникам', '<div id="rs-search"></div>')}`;
      const jobsTable = () => App.table('rs-jobs', {
        rows: st.jobs, size: 12, search: false, export: 'jobs',
        cols: [{k: 'name', t: 'Этап'}, {k: 'status', t: 'Статус', r: j => App.statusTag(j.status)},
          {k: 'progress', t: 'Прогресс', r: j => `<div class="progress" style="min-width:90px"><i style="width:${Math.round((j.progress || 0) * 100)}%"></i></div><span class="tiny">${Math.round((j.progress || 0) * 100)} %</span>`},
          {k: 'processed', t: 'Обработано', cls: 'num', r: j => `${j.processed || 0}/${j.total || 0}`},
          {k: 'attempts', t: 'Попыток', cls: 'num'},
          {k: 'error_code', t: 'Ошибка', r: j => j.error_code ? App.tag(j.error_code, 'err') + ' ' + esc(App.short(j.error_message, 60)) : '—'},
          {k: 'finished_at', t: 'Завершено', r: j => App.dt(j.finished_at)}],
      });
      jobsTable();
      App.table('rs-search', {
        rows: st.search_jobs || [], size: 15, export: 'search_jobs',
        cols: [{k: 'connector_code', t: 'Коннектор'}, {k: 'source_code', t: 'Источник'},
          {k: 'branch', t: 'Ветвь'}, {k: 'status', t: 'Статус', r: j => App.statusTag(j.status)},
          {k: 'found_count', t: 'Найдено', cls: 'num'}, {k: 'attempts', t: 'Попыток', cls: 'num'},
          {k: 'error_code', t: 'Ошибка', r: j => j.error_code ? App.tag(j.error_code, 'err') : '—'},
          {k: 'error_message', t: 'Причина', r: j => esc(App.short(j.error_message || '—', 70))}],
        empty: 'Задания поиска ещё не созданы',
      });
      document.getElementById('btn-run')?.addEventListener('click', () => App.runResearch(false));
      document.getElementById('btn-resume')?.addEventListener('click', () => App.runResearch(true));
      document.getElementById('btn-cancel')?.addEventListener('click', async () => {
        await App.post(`/api/v1/researches/${rid}/cancel`); App.toast('Отменено', 'warn'); App.render();
      });
      const onEv = ev => { if (ev.detail.research_id === rid) App.render(); };
      window.addEventListener('isheika:event', onEv, {once: true});
      App.ctxObject('Исследование', {'ID': '<code>' + esc(rid) + '</code>', 'Статус': App.statusTag(r.status),
        'Утверждений': r.counts.claims, 'Доказательств': r.counts.evidence});
    },
  };

  // ============================================================ UI-02 Новое исследование
  Screens.new = {
    title: 'Новое исследование', ui: 'UI-02', module: 'M02', group: 'Поиск и источники', right: 'research.write',
    async render(host, params) {
      const [countries, stats] = await Promise.all([App.get('/api/v1/countries'), App.get('/api/v1/sources/stats')]);
      const cs = countries.items || [];
      App.S.countries = cs;
      const langs = [['ru', 'Русский'], ['en', 'Английский'], ['de', 'Немецкий'], ['fr', 'Французский'], ['zh', 'Китайский'], ['ja', 'Японский'], ['ko', 'Корейский'], ['es', 'Испанский']];
      host.innerHTML = `
        <div class="grid g2">
          ${App.card('Постановка задачи', `
            <label class="fld"><span>Поисковый запрос (естественный язык, RU/EN)</span>
              <textarea id="f-query" placeholder="например: тропосферная связь за горизонтом, 5G NTN">${esc(params.q || '')}</textarea></label>
            <label class="fld"><span>Название исследования</span><input type="text" id="f-title" placeholder="краткое название"></label>
            <label class="fld"><span>Цель исследования</span><textarea id="f-goal" style="min-height:56px" placeholder="какой вопрос должен закрыть анализ"></textarea></label>
            <div class="grid g2">
              <label class="fld"><span>Тип объекта</span><select id="f-type">
                ${['technology', 'product', 'organization', 'research_field', 'country_program'].map(t => `<option value="${t}">${t}</option>`).join('')}</select></label>
              <label class="fld"><span>Горизонт прогноза, лет (0–50)</span><input type="number" id="f-horizon" value="50" min="0" max="50"></label>
              <label class="fld"><span>Период с</span><input type="text" id="f-from" placeholder="2015-01-01"></label>
              <label class="fld"><span>Период по</span><input type="text" id="f-to" placeholder="2026-12-31"></label>
            </div>
            <label class="fld"><span>Языки поиска</span><div class="chips" id="f-langs">
              ${langs.map(([c, n]) => `<label class="chip ${['ru', 'en'].includes(c) ? 'on' : ''}"><input type="checkbox" value="${c}" ${['ru', 'en'].includes(c) ? 'checked' : ''}>${n}</label>`).join('')}</div></label>`)}
          ${App.card('Охват: страны и источники', `
            <div class="row" style="margin-bottom:8px">
              <button class="btn sm" id="btn-all-countries">Выбрать все страны</button>
              <span class="tiny muted" id="cnt-countries"></span>
              <span class="tiny muted">повторное нажатие снимает выбор</span></div>
            <div class="chips" id="f-countries" style="max-height:230px">
              ${cs.map(c => `<label class="chip ${c.is_enabled ? 'on' : ''}" title="${esc(c.name_ru)} · источников: ${c.sources}"><input type="checkbox" value="${esc(c.code)}" ${c.is_enabled ? 'checked' : ''}>${esc(c.code)} ${esc(c.name_ru)}</label>`).join('')}</div>
            <label class="fld" style="margin-top:10px"><span>Категории источников (пусто = все 12)</span>
              <select id="f-cats" multiple size="6">${Object.entries(stats.categories || {}).map(([code, name]) => `<option value="${esc(code)}">${esc(code)} — ${esc(name)}</option>`).join('')}</select></label>
            <div class="grid g2">
              <label class="fld"><span>Максимальный класс доступа</span><select id="f-access">
                <option value="A0">A0 — открытый без ключа</option><option value="A1" selected>A1 — открытый с бесплатным ключом</option>
                <option value="A2">A2 — по заявке</option><option value="A3">A3 — подписка (отключено)</option><option value="A4">A4 — закрытый (запрещено)</option></select></label>
              <label class="fld"><span>Документов на источник</span><input type="number" id="f-maxdocs" value="8" min="1" max="200"></label>
            </div>
            ${App.alert('info', 'Режим Free-first: используются официальные открытые API. Платные вызовы выключены по умолчанию; обход paywall, CAPTCHA и авторизации запрещён политикой (стоп-лист).')}
            <div class="row">
              <button class="btn" id="btn-preview">Предпросмотр поисковой модели</button>
              <button class="btn primary" id="btn-create">Создать исследование</button>
              <button class="btn primary" id="btn-create-run">Создать и запустить ▶</button>
            </div>`)}
        </div>
        <div id="preview-box"></div>`;
      const chips = host.querySelectorAll('.chips input');
      chips.forEach(cb => cb.addEventListener('change', () => { cb.parentElement.classList.toggle('on', cb.checked); countCountries(); }));
      const countCountries = () => {
        const n = host.querySelectorAll('#f-countries input:checked').length;
        document.getElementById('cnt-countries').textContent = `выбрано стран: ${n} из ${cs.length}`;
        document.getElementById('btn-all-countries').textContent = n === cs.length ? 'Снять выбор со всех стран' : 'Выбрать все страны';
      };
      countCountries();
      document.getElementById('btn-all-countries').addEventListener('click', () => {
        const boxes = [...host.querySelectorAll('#f-countries input')];
        const target = !boxes.every(b => b.checked);
        boxes.forEach(b => { b.checked = target; b.parentElement.classList.toggle('on', target); });
        countCountries();
        App.toast(target ? 'Выбраны все доступные страны (' + boxes.length + ')' : 'Выбор стран снят', 'info', 2500);
      });
      const collect = () => ({
        query: document.getElementById('f-query').value.trim(),
        title: document.getElementById('f-title').value.trim(),
        goal: document.getElementById('f-goal').value.trim(),
        research_type: document.getElementById('f-type').value,
        forecast_horizon_years: +document.getElementById('f-horizon').value,
        period_from: document.getElementById('f-from').value.trim() || null,
        period_to: document.getElementById('f-to').value.trim() || null,
        languages: [...host.querySelectorAll('#f-langs input:checked')].map(x => x.value),
        countries: [...host.querySelectorAll('#f-countries input:checked')].map(x => x.value),
        settings: {
          categories: [...document.getElementById('f-cats').selectedOptions].map(o => o.value),
          access_max: document.getElementById('f-access').value,
          max_docs_per_source: +document.getElementById('f-maxdocs').value,
        },
      });
      document.getElementById('btn-preview').addEventListener('click', async () => {
        const b = document.getElementById('preview-box');
        b.innerHTML = App.spinner('Разбор запроса и подбор коннекторов…');
        try {
          const p = await App.post('/api/v1/queries/preview', collect());
          b.innerHTML = previewHTML(p);
        } catch (e) { b.innerHTML = App.errorBlock(e); }
      });
      const create = async run => {
        const body = collect();
        if (!body.query) { App.toast('Введите поисковый запрос', 'warn'); return; }
        try {
          // ИД-22: ключ идемпотентности уникален для ДЕЙСТВИЯ, а не для текста
          // запроса: повтор после сбоя возвращает то же исследование, а новое
          // исследование с тем же запросом создаётся заново.
          const r = await App.post('/api/v1/researches', body, 'create:' + App.uid('idem-'));
          await App.loadResearches(true);
          App.setResearch(r.id, true);
          App.toast('Исследование создано: ' + esc(r.title), 'ok');
          if (run) await App.runResearch(false); else App.go('research', {id: r.id});
        } catch (e) { App.toast('Ошибка: ' + esc(e.message), 'error'); }
      };
      document.getElementById('btn-create').addEventListener('click', () => create(false));
      document.getElementById('btn-create-run').addEventListener('click', () => create(true));
      App.ctx(App.alert('info', 'Подсказка: запрос можно писать на русском — система построит ветви RU/EN, синонимы и аббревиатуры, затем покажет предпросмотр выражений (UI-03).'));
    },
  };

  function previewHTML(p) {
    const ex = p.expansion || {}, parsed = p.parsed || {};
    const list = a => (a || []).map(x => esc(typeof x === 'string' ? x : JSON.stringify(x))).join(', ') || '—';
    const warns = ex.warnings || [];
    return App.card('Предпросмотр поисковой модели (UI-03)', `
      ${warns.map(w => App.alert('warn', esc(w))).join('')}
      ${App.kv({'Сущности': list(parsed.entities), 'Назначение': list(parsed.purpose),
        'Термины объекта': list(parsed.object_terms), 'Ограничения': list(parsed.constraints),
        'Типы документов': list(parsed.doc_types), 'Период': esc((parsed.period_from || '—') + ' … ' + (parsed.period_to || '—')),
        'Выражение': '<code>' + esc(p.expression || (ex.branches || [{}])[0]?.expression || '') + '</code>'})}
      <div class="grid g2" style="margin-top:10px">
        <div><b class="tiny muted">Синонимы (RU)</b><div class="tiny">${list(ex.synonyms)}</div>
          <b class="tiny muted">Переводы (EN)</b><div class="tiny">${list(ex.translations)}</div>
          <b class="tiny muted">Аббревиатуры</b><div class="tiny">${list(ex.abbreviations)}</div>
          <b class="tiny muted">Исключения</b><div class="tiny">${list(ex.exclusions)}</div></div>
        <div><b class="tiny muted">Ветви запроса (${(ex.branches || []).length})</b>
          ${(ex.branches || []).map(b => `<details class="acc"><summary>${esc(b.name || b.kind || '')}</summary>
            <div class="tiny"><code>${esc(b.expression || '')}</code></div>
            <div class="tiny muted">${esc(b.rationale || '')}</div></details>`).join('') || '<div class="tiny muted">—</div>'}</div>
      </div>
      <b class="tiny muted">Коннекторы к запуску (${(p.connectors || []).length})</b>
      <div class="row">${(p.connectors || []).map(c => App.tag(c.code + (c.requires_key ? ' 🔑' : ''), c.requires_key ? 'warn' : 'ok')).join(' ')}</div>`);
  }

  // ============================================================ UI-03 Конструктор поиска
  Screens.query = {
    title: 'Конструктор поиска', ui: 'UI-03', module: 'M08', group: 'Поиск и источники', right: 'research.read',
    async render(body) {
      const host = await scaffold(body, '<button class="btn sm" onclick="App.go(\'results\')">К результатам</button>');
      if (!host) return;
      const rid = App.S.researchId;
      const r = await App.get(`/api/v1/researches/${rid}`);
      const q = r.query || {};
      const p = await App.post('/api/v1/queries/preview', {query: q.raw_text, languages: r.language_codes});
      host.innerHTML = `
        ${App.card('Исходный запрос (версия ' + (q.query_version || 1) + ')', `
          <label class="fld"><span>Текст запроса</span><textarea id="q-text">${esc(q.raw_text || '')}</textarea></label>
          <div class="row"><button class="btn primary" id="q-save" ${App.can('research.write') ? '' : 'disabled'}>Сохранить новую версию</button>
            <button class="btn" id="q-preview">Пересобрать предпросмотр</button>
            <span class="tiny muted">Уточнение запроса создаёт новую версию и журналируется.</span></div>`)}
        <div id="q-preview-box">${previewHTML(p)}</div>
        ${App.card('Разбор запроса', App.kv({
          'Сущности': esc(((q.parsed || {}).entities || []).join('; ') || '—'),
          'Термины объекта': esc(((q.parsed || {}).object_terms || []).join(', ') || '—'),
          'Назначение': esc(((q.parsed || {}).purpose || []).join(', ') || '—'),
          'Аббревиатуры': esc((p.expansion.abbreviations || []).join(', ') || 'нет'),
          'Исключения (разбор)': esc(((q.parsed || {}).exclusions || []).join(', ') || 'нет'),
          'Языки': esc((r.language_codes || []).join(', ')),
          'Сохранённые исключения': esc((q.exclusions || []).join(', ') || 'нет'),
          'Версия расширения': esc(p.expansion.version || '—'),
        }))}`;
      document.getElementById('q-save').addEventListener('click', async () => {
        try {
          const res = await App.post(`/api/v1/researches/${rid}/query`, {query: document.getElementById('q-text').value, languages: r.language_codes});
          App.toast('Создана новая версия запроса', 'ok');
          App.setHTML('q-preview-box', previewHTML({parsed: res.parsed, expansion: res.expansion, expression: (res.expansion.branches || [{}])[0]?.expression, connectors: p.connectors}));
        } catch (e) { App.toast(esc(e.message), 'error'); }
      });
      document.getElementById('q-preview').addEventListener('click', async () => {
        const box = document.getElementById('q-preview-box');
        box.innerHTML = App.spinner();
        try { box.innerHTML = previewHTML(await App.post('/api/v1/queries/preview', {query: document.getElementById('q-text').value, languages: r.language_codes})); }
        catch (e) { box.innerHTML = App.errorBlock(e); }
      });
      App.ctxObject('Поисковая модель', {'Ветвей': (p.expansion.branches || []).length, 'Коннекторов': (p.connectors || []).length, 'Версия запроса': q.query_version});
    },
  };

  // ============================================================ UI-04 Результаты поиска
  Screens.results = {
    title: 'Результаты поиска', ui: 'UI-04', module: 'M09 / M10', group: 'Поиск и источники', right: 'research.read',
    async render(body, params) {
      const tab = params.tab || 'docs';
      const host = await scaffold(body);
      if (!host) return;
      const rid = App.S.researchId;
      host.innerHTML = tabsHTML('results', [{k: 'docs', t: 'Документы'}, {k: 'cards', t: 'Карточки'}, {k: 'duplicates', t: 'Дедупликация (M10)'}], tab) +
        `<div class="card"><div class="tbl-toolbar">
          <select id="f-class"><option value="">все классы</option><option value="DIRECT">DIRECT — прямое (R ≥ 0,80)</option><option value="ADJACENT">ADJACENT — смежное (0,60–0,79)</option><option value="BELOW_THRESHOLD">BELOW_THRESHOLD — ниже порога (&lt; 0,60)</option></select>
          <input type="search" id="f-q" placeholder="поиск по названию/аннотации" style="max-width:240px">
          <input type="text" id="f-country" placeholder="страна ISO2" style="width:110px">
          <input type="text" id="f-type" placeholder="тип документа" style="width:130px">
          <input type="text" id="f-lang" placeholder="язык" style="width:80px">
          <select id="f-sort"><option value="score">по релевантности</option><option value="date">по дате</option><option value="title">по названию</option></select>
          <button class="btn sm primary" id="f-apply">Применить</button>
          <button class="btn sm" id="f-translate" title="Технический перевод найденных материалов на русский язык">Перевести на русский</button>
          <span class="tiny muted" id="f-total"></span>
          <span class="tiny muted" id="f-trn"></span>
        </div><div id="docs-box">${App.spinner()}</div></div>
        ${App.alert('info', 'R = 0,30·S + 0,25·T + 0,15·C + 0,15·E + 0,10·K + 0,05·F. Пороги: ≥ 0,80 — прямое соответствие; 0,60–0,79 — смежное; &lt; 0,60 — исключается. Значения рассчитаны серверным ядром (ТЗ-03 §3).')}`;
      const load = async () => {
        const box = document.getElementById('docs-box');
        box.innerHTML = App.spinner('Загрузка документов…');
        const query = {
          research_id: rid, limit: 500, cls: document.getElementById('f-class').value,
          q: document.getElementById('f-q').value, country: document.getElementById('f-country').value,
          doc_type: document.getElementById('f-type').value, language: document.getElementById('f-lang').value,
          sort: document.getElementById('f-sort').value,
        };
        try {
          const d = await App.get('/api/v1/documents', query);
          document.getElementById('f-total').textContent = `найдено: ${d.total} (загружено ${d.items.length})`;
          let rows = d.items;
          if (tab === 'duplicates') {
            const cl = await App.get('/api/v1/document-clusters', {research_id: rid});
            const sm = cl.summary || {};
            box.innerHTML = `
              <div class="grid g4">
                ${App.kpi('Логических документов', sm.logical_documents ?? 0, 'уникальные материалы')}
                ${App.kpi('Вхождений', sm.occurrences ?? 0, 'обнаружений в источниках и по URL')}
                ${App.kpi('Объединено', sm.merged ?? 0, 'повторных обнаружений')}
                ${App.kpi('Кластеров', sm.clusters ?? 0, 'связанные версии и копии')}
              </div>
              ${App.alert('info', 'Модель ИД-03: физическое содержимое (blob, SHA-256) → логический документ → вхождение в источнике → кластер связанных версий. Объединение не уничтожает сведения об источниках обнаружения.')}
              <div id="cl-box"></div>`;
            const items = cl.items || [];
            App.setHTML('cl-box', items.length ? items.map(c => `
              <div class="card"><h3>${esc(App.short(c.title || c.cluster_key, 90))} ${App.statusTag(c.cluster_type)}</h3>
                <table class="tbl"><tr><th>Документ</th><th>Связь</th><th>Роль</th><th>Уверенность</th><th>Вхождения (источник · URL · дата)</th></tr>
                ${(c.members || []).map(mm => `<tr><td><a href="#/document/${esc(mm.document_id)}">${esc(App.short(mm.title, 70))}</a></td>
                  <td>${App.statusTag(mm.relation)}</td><td>${esc(mm.role)}</td><td class="num">${App.num(mm.confidence, 2)}</td>
                  <td class="tiny">${(mm.occurrences || []).map(o => `${esc(o.source_code)} · <a href="${esc(o.url)}" target="_blank" rel="noopener">${esc(App.short(o.url, 48))}</a> · ${esc(App.donly(o.accessed_at))}`).join('<br>')}</td></tr>`).join('')}
                </table></div>`).join('') : App.empty('Кластеры не сформированы: повторных размещений и версий не найдено', '🧬'));
            return;
          }
          if (!rows.length) {
            box.innerHTML = App.empty('Нет документов', '🔍', 'Возможные причины: нет совпадений по запросу; фильтр слишком строгий; источник недоступен; квота исчерпана; ошибка извлечения. Проверьте мониторинг (UI-23) и журнал (UI-24).');
            return;
          }
          if (tab === 'cards') {
            box.innerHTML = rows.map(cardHTML).join('');
            wireCards(box, rid);
          } else {
            box.innerHTML = '<div id="docs-tbl"></div>';
            App.table('docs-tbl', {
              rows, size: 25, export: 'documents', sort: 'score',
              cols: [
                {k: 'title', t: 'Документ', r: docLink},
                {k: 'score', t: 'R', cls: 'num', r: x => x.score == null ? '—' : App.num(x.score, 3)},
                {k: 'rclass', t: 'Класс R', r: x => App.statusTag(x.rclass || x.relevance_class)},
                {k: 'decision', t: 'Решение', r: x => App.statusTag(x.decision || 'INCLUDE')},
                {k: 'extraction_status', t: 'Обработка', r: x => App.statusTag(x.extraction_status)},
                {k: 'occurrence_count', t: 'Вхождений', cls: 'num', r: x => x.occurrence_count ?? 1},
                {k: 'doc_type', t: 'Тип'}, {k: 'source_code', t: 'Источник'},
                {k: 'country_code', t: 'Страна'}, {k: 'language', t: 'Яз.'},
                {k: 'published_at', t: 'Дата', r: x => App.donly(x.published_at)},
                {k: 'evidence_class', t: 'Класс док-ва'},
                {k: 'marker', t: 'Маркер'},
                {k: 'components', t: 'S/T/C/E/K/F', v: x => x.components ? Object.values(x.components).join('/') : '', r: x => x.components ? `<span class="tiny">${['S', 'T', 'C', 'E', 'K', 'F'].map(k => App.num((x.components || {})[k], 2)).join(' / ')}</span>` : '—'},
              ],
              onRow: x => App.go('document', {id: x.id}),
            });
          }
        } catch (e) { box.innerHTML = App.errorBlock(e, {stage: 'UI-04'}); }
      };
      document.getElementById('f-apply').addEventListener('click', load);
      document.getElementById('f-q').addEventListener('keydown', e => { if (e.key === 'Enter') load(); });
      const trnInfo = async () => {
        try {
          const t = await App.get(`/api/v1/researches/${rid}/translation`);
          const modes = t.modes || {};
          const term = (modes.terminology || {}).count || 0, ai = (modes.ai_technical || {}).count || 0;
          App.setHTML('f-trn', `· перевод: ${t.translated || 0} (ИИ ${ai}, терминология ${term})`
            + (t.review_required ? `, вычитка ${t.review_required}` : ''));
        } catch (e) { App.setHTML('f-trn', ''); }
      };
      const trBtn = document.getElementById('f-translate');
      if (trBtn) trBtn.addEventListener('click', async () => {
        trBtn.disabled = true;
        try {
          const res = await App.post(`/api/v1/researches/${rid}/translate`, {});
          App.toast(`Переведено материалов: ${res.translated} (ИИ ${res.ai_mode}, терминология ${res.terminology_mode})`, 'ok', 4000);
          await load(); await trnInfo();
        } catch (e) { App.toast(e.message || 'Перевод не выполнен', 'err', 5000); }
        finally { trBtn.disabled = false; }
      });
      await load(); await trnInfo();
      App.ctx(App.alert('info', 'Действия с документом: «Открыть источник», «В доказательства», «В паспорт», «Исключить». Ручная разметка релевантности (0/1/2) используется для калибровки метрик Precision@10 и nDCG@10.'));
    },
  };

  function cardHTML(d) {
    const comp = d.components || {};
    return `<div class="card" data-doc="${esc(d.id)}">
      <div class="spread"><b>${esc(d.title_ru || d.title || '(без названия)')}</b>
        <span class="row">${App.statusTag(d.rclass || d.state)}<span class="pill">R ${App.num(d.score, 3)}</span></span></div>
      <div class="tiny muted">${esc(d.doc_type || '—')} · ${esc(d.source_code || '—')} · ${esc(d.country_code || '—')} · ${App.donly(d.published_at)} · ${esc(d.evidence_class || '')} · маркер ${esc(d.marker || 'Д')}</div>
      <p class="tiny">${esc(App.short(d.abstract_ru || d.abstract || d.text_excerpt || 'Аннотация отсутствует в источнике', 340))}</p>
      ${d.title_ru && d.title_ru !== d.title ? `<p class="tiny muted">Оригинал: ${esc(App.short(d.title, 120))}${d.translation_mode === 'terminology' ? ' · терминологический перевод, требует вычитки' : d.translation_mode === 'ai_technical' ? ' · перевод ИИ' : ''}</p>` : ''}
      <div class="tiny muted">Компоненты: S ${App.num(comp.S, 2)} · T ${App.num(comp.T, 2)} · C ${App.num(comp.C, 2)} · E ${App.num(comp.E, 2)} · K ${App.num(comp.K, 2)} · F ${App.num(comp.F, 2)} ${d.reason ? '· ' + esc(App.short(d.reason, 120)) : ''}</div>
      <div class="row" style="margin-top:8px">
        <a class="btn sm" href="#/document/${esc(d.id)}">Карточка</a>
        ${d.url ? `<a class="btn sm" href="${esc(d.url)}" target="_blank" rel="noopener noreferrer">Открыть источник ↗</a>` : ''}
        <button class="btn sm" data-act="evidence">В доказательства</button>
        <button class="btn sm" data-act="passport">В паспорт</button>
        <button class="btn sm danger" data-act="exclude">Исключить</button>
        <span class="tiny muted">разметка:</span>
        ${[0, 1, 2].map(l => `<button class="btn sm" data-label="${l}" title="0 — нерелевантно, 1 — смежное, 2 — прямое">${l}</button>`).join('')}
      </div></div>`;
  }
  function wireCards(box, rid) {
    box.querySelectorAll('[data-doc]').forEach(el => {
      const id = el.dataset.doc;
      el.querySelector('[data-act="exclude"]')?.addEventListener('click', async () => {
        try { await App.post(`/api/v1/documents/${id}/exclude`, {reason: 'Исключено аналитиком в UI-04'}); App.toast('Документ исключён', 'warn'); el.style.opacity = .5; }
        catch (e) { App.toast(esc(e.message), 'error'); }
      });
      el.querySelector('[data-act="passport"]')?.addEventListener('click', () => App.go('passport'));
      el.querySelector('[data-act="evidence"]')?.addEventListener('click', () => evidenceModal(rid, id));
      el.querySelectorAll('[data-label]').forEach(b => b.addEventListener('click', async () => {
        try { await App.post(`/api/v1/documents/${id}/label`, {label: +b.dataset.label}); App.toast('Разметка сохранена (калибровка)', 'ok', 2500); }
        catch (e) { App.toast(esc(e.message), 'error'); }
      }));
    });
  }
  async function evidenceModal(rid, docId) {
    const claims = await App.get('/api/v1/claims', {research_id: rid});
    App.modal('Добавить доказательство', `
      <label class="fld"><span>Утверждение (claim_id)</span><select id="ev-claim">
        ${(claims.items || claims || []).map(c => `<option value="${esc(c.id)}">[${esc(c.claim_type)}] ${esc(App.short(c.claim_text, 90))}</option>`).join('')}</select></label>
      <label class="fld"><span>Цитата</span><textarea id="ev-quote"></textarea></label>
      <label class="fld"><span>Локатор (страница, раздел, абзац)</span><input type="text" id="ev-loc" placeholder="с. 4, раздел 2"></label>
      <label class="fld"><span>Статус</span><select id="ev-status">${['SUPPORTED', 'PARTIAL', 'UNVERIFIED', 'CONTRADICTED'].map(s => `<option value="${s}">${App.STATUS_RU[s]}</option>`).join('')}</select></label>
      <button class="btn primary" id="ev-save">Сохранить доказательство</button>`,
      root => root.querySelector('#ev-save').addEventListener('click', async () => {
        try {
          await App.post('/api/v1/evidence', {research_id: rid, claim_id: root.querySelector('#ev-claim').value,
            document_id: docId, quote: root.querySelector('#ev-quote').value, locator: root.querySelector('#ev-loc').value,
            status: root.querySelector('#ev-status').value});
          App.closeModal(); App.toast('Доказательство добавлено и связано с документом', 'ok');
        } catch (e) { App.toast(esc(e.message), 'error'); }
      }));
  }

  // ============================================================ UI-05 Карточка документа
  Screens.document = {
    title: 'Карточка документа', ui: 'UI-05', module: 'M09', group: 'Поиск и источники', right: 'research.read',
    async render(host, params) {
      const d = await App.get(`/api/v1/documents/${params.id}`);
      const rel = d.relevance || {}, comp = rel.components || {};
      host.innerHTML = `
        <div class="grid g2">
          ${App.card(esc(App.short(d.title, 120)), `
            ${App.kv({'Тип': esc(d.doc_type), 'Источник': esc(d.source_code) + ' / ' + esc(d.connector_code || ''),
              'Страна': esc(d.country_code || '—'), 'Язык': esc(d.language || '—'),
              'Опубликован': App.donly(d.published_at), 'Обращение': App.dt(d.accessed_at),
              'DOI': esc(d.doi || '—'), 'Лицензия': esc(d.license || 'не указана'),
              'Открытый доступ': esc(d.oa_status || '—'), 'Класс доказательства': esc(d.evidence_class),
              'Группа независимости': esc(d.independence_group || '—'), 'Маркер': esc(d.marker),
              'Состояние': App.statusTag(d.state), 'HTTP при загрузке': d.fetch_http_status ?? '—'})}
            <div class="row" style="margin-top:10px">
              ${d.url ? `<a class="btn sm primary" href="${esc(d.url)}" target="_blank" rel="noopener noreferrer">Открыть первоисточник ↗</a>` : ''}
              <button class="btn sm" id="d-ev">В доказательства</button>
              <button class="btn sm danger" id="d-excl">Исключить</button></div>
            <p class="tiny" style="margin-top:10px">${esc((d.translation && d.translation.abstract_ru) || d.abstract || 'Аннотация отсутствует в источнике.')}</p>
            ${translationBlock(d)}
            ${d.text_excerpt ? `<details class="acc"><summary>Фрагмент текста</summary><div class="tiny">${esc(d.text_excerpt)}</div></details>` : ''}`)}
          ${App.card('Релевантность (серверное ядро)', `
            <div class="grid g3">${App.kpi('R', App.num(rel.score, 3), esc(rel.class || ''))}
              ${App.kpi('Класс', App.STATUS_RU[rel.class] || rel.class || '—', 'порог 0,80 / 0,60')}
              ${App.kpi('Версия', esc(rel.methodology_version || '—'), 'методика')}
            </div>
            <table class="tbl" style="margin-top:10px"><tr><th>Компонент</th><th>Значение</th><th>Смысл</th></tr>
              ${[['S', 'семантическое соответствие'], ['T', 'совпадение терминов'], ['C', 'контекст/цель'], ['E', 'качество доказательства'], ['K', 'ключевые сущности'], ['F', 'формальные признаки']].map(([k, n]) =>
                `<tr><td><b>${k}</b></td><td class="num">${App.num(comp[k], 3)}</td><td class="tiny muted">${n}</td></tr>`).join('')}
            </table>
            <div class="tiny muted" style="margin-top:8px">${esc(rel.reason || '')}</div>`)}
        </div>
        ${App.card('Связанные утверждения', (d.claims || []).length ? `<table class="tbl"><tr><th>Тип</th><th>Утверждение</th><th>Статус</th><th>Уверенность</th><th>Автор</th></tr>
          ${d.claims.map(c => `<tr><td>${App.tag(c.claim_type, c.claim_type)}</td><td>${esc(c.claim_text)}</td><td>${App.statusTag(c.status)}</td>
            <td class="num">${App.num(c.confidence, 2)}</td><td class="tiny">${esc(c.produced_by)}</td></tr>`).join('')}</table>` : App.empty('Утверждений по документу нет', '🧾'))}
        ${App.card('Доказательства из документа', (d.evidence || []).length ? d.evidence.map(evItem).join('') : App.empty('Доказательства не сформированы', '🧾'))}
        ${App.card('Идентификаторы и качество источника', App.kv({
          'Внешний ID': esc(d.external_id), 'Идентификаторы': '<code>' + esc(JSON.stringify(d.identifiers || {})) + '</code>',
          'Content-hash': '<code>' + esc(String(d.content_hash || '').slice(0, 24)) + '</code>',
          'Simhash': '<code>' + esc(String(d.simhash || '').slice(0, 24)) + '</code>',
          'Дубликат документа': esc(d.duplicate_of || 'нет'),
        }))}`;
      document.getElementById('d-excl').addEventListener('click', async () => {
        try { await App.post(`/api/v1/documents/${d.id}/exclude`, {reason: 'Исключено в UI-05'}); App.toast('Исключён', 'warn'); App.render(); }
        catch (e) { App.toast(esc(e.message), 'error'); }
      });
      document.getElementById('d-ev').addEventListener('click', () => evidenceModal(d.research_id, d.id));
      App.ctxObject('Документ', {'ID': '<code>' + esc(d.id) + '</code>', 'Источник': esc(d.source_code),
        'Класс док-ва': esc(d.evidence_class), 'Доказательств': (d.evidence || []).length, 'Утверждений': (d.claims || []).length},
        `<div class="tiny muted" style="margin-top:8px">Открытые источники не покрывают закрытые материалы; отсутствие данных — не отрицательный факт.</div>`);
    },
  };

  // ============================================================ UI-06 Мульти-ИИ панель
  Screens.ai = {
    title: 'Мульти-ИИ панель', ui: 'UI-06', module: 'M05 / M06 / M07', group: 'Мульти-ИИ', right: 'ai.read',
    async render(body, params) {
      const tab = params.tab || 'route';
      const rid = App.S.researchId;
      body.innerHTML = tabsHTML('ai', [{k: 'route', t: 'Маршрутизация'}, {k: 'providers', t: 'Провайдеры и модели'}, {k: 'agents', t: 'Агенты A01–A12'}, {k: 'tasks', t: 'Задания и ответы'}], tab) +
        `<div id="ai-box">${App.spinner()}</div>`;
      const box = document.getElementById('ai-box');
      if (tab === 'route') {
        const classes = ['search_expansion', 'science_analysis', 'patent_analysis', 'industry_analysis', 'country_analysis', 'tech_analysis', 'trl_assessment', 'feasibility', 'competitor', 'forecast', 'critic', 'report'];
        const tc = params.tc || 'tech_analysis';
        const d = await App.get('/api/v1/ai/route', {task_class: tc});
        box.innerHTML = `
          ${App.card('Выбор модели: Q(m,t) = argmax', `
            <div class="row"><span class="tiny muted">Класс задачи:</span>
              <select id="tc" style="max-width:280px">${classes.map(c => `<option ${c === tc ? 'selected' : ''}>${c}</option>`).join('')}</select></div>
            ${d.chosen && d.chosen.error ? App.alert('warn', 'Маршрут не найден: ' + esc(d.chosen.error.message)) :
              App.kv({'Провайдер': esc(d.chosen.provider), 'Модель': esc(d.chosen.model), 'Группа': esc(d.chosen.group),
                'Оценка Q': App.num(d.chosen.score && d.chosen.score.total, 3), 'Обоснование': esc(d.chosen.reason)})}
            ${App.alert('info', 'Порядок: бесплатная подтверждённая → бесплатная альтернативная → локальная → платная только при явном разрешении. Голосование моделей не является доказательством.')}`)}
          <div class="grid g2">
            ${App.card('Бесплатные кандидаты (ранжирование)', d.free.length ? `<table class="tbl"><tr><th>Провайдер</th><th>Модель</th><th>Q</th></tr>
              ${d.free.map(f => `<tr><td>${esc(f.provider)}</td><td>${esc(f.model)}</td><td class="num">${App.num(f.score.total, 3)}</td></tr>`).join('')}</table>` : App.empty('Нет доступных бесплатных моделей', '🆓'))}
            ${App.card('Платные (заблокированы политикой)', d.paid_blocked.length ? `<table class="tbl"><tr><th>Провайдер</th><th>Модель</th></tr>
              ${d.paid_blocked.map(f => `<tr><td>${esc(f.provider)}</td><td>${esc(f.model)}</td></tr>`).join('')}</table>` + App.alert('warn', 'Платные вызовы выключены. Включение — только в настройках с бюджетом и лимитами.') : App.empty('Платные модели не сконфигурированы', '💳'))}
          </div>
          ${App.card('Отклонённые кандидаты', d.rejected.length ? `<table class="tbl"><tr><th>Провайдер</th><th>Модель</th><th>Причины</th></tr>
            ${d.rejected.map(f => `<tr><td>${esc(f.provider)}</td><td>${esc(f.model)}</td><td class="tiny">${esc((f.reasons || []).join('; '))}</td></tr>`).join('')}</table>` : App.empty('Отклонённых нет', '✅'))}`;
        document.getElementById('tc').addEventListener('change', e => App.go('ai', {tab: 'route', tc: e.target.value}));
      } else if (tab === 'providers') {
        const d = await App.get('/api/v1/ai/providers');
        box.innerHTML = App.card('Провайдеры ИИ', '<div id="prov-tbl"></div>') +
          App.alert('info', 'Ключи хранятся только на сервере в зашифрованном виде и никогда не передаются в браузер. Квоты берутся из реестра, а не зашиваются в код.');
        App.table('prov-tbl', {
          rows: d.items, size: 25, export: 'ai_providers',
          cols: [{k: 'name', t: 'Провайдер'}, {k: 'family', t: 'Семейство'},
            {k: 'status', t: 'Статус', r: p => App.statusTag(p.status)},
            {k: 'paid', t: 'Платный', r: p => p.paid ? App.tag('платный', 'warn') : App.tag('бесплатный', 'ok')},
            {k: 'key_configured', t: 'Ключ', r: p => p.key_configured ? App.tag('задан', 'ok') : App.tag('нет', 'warn')},
            {k: 'models', t: 'Моделей', cls: 'num', v: p => p.models.length},
            {k: 'privacy', t: 'Приватность', r: p => esc((p.privacy || {}).data_usage || '—')},
            {k: 'last_error', t: 'Ошибка', r: p => esc(App.short(p.last_error || '—', 60))},
            {k: 'act', t: 'Действия', r: p => `<button class="btn sm" data-check="${esc(p.id)}">Проверить</button>
              ${App.can('keys.write') ? `<button class="btn sm" data-toggle="${esc(p.id)}" data-on="${p.enabled ? 0 : 1}">${p.enabled ? 'Отключить' : 'Включить'}</button>` : ''}`}],
          after: el => {
            el.querySelectorAll('[data-check]').forEach(b => b.addEventListener('click', async () => {
              b.disabled = true; b.textContent = '…';
              try { const r = await App.post(`/api/v1/ai/providers/${b.dataset.check}/check`); App.toast('Статус: ' + esc(r.status) + (r.reason ? ' — ' + esc(r.reason) : ''), r.status === 'active' ? 'ok' : 'warn'); }
              catch (e) { App.toast(esc(e.message), 'error'); }
              App.render();
            }));
            el.querySelectorAll('[data-toggle]').forEach(b => b.addEventListener('click', async () => {
              await App.post(`/api/v1/ai/providers/${b.dataset.toggle}/toggle`, {enabled: b.dataset.on === '1'}); App.render();
            }));
          },
        });
        box.innerHTML += App.card('Модели', '<div id="model-tbl"></div>');
        const models = d.items.flatMap(p => p.models.map(m => ({...m, provider: p.name, pid: p.id})));
        App.table('model-tbl', {
          rows: models, size: 15, export: 'ai_models',
          cols: [{k: 'provider', t: 'Провайдер'}, {k: 'id', t: 'model_id'}, {k: 'display_name', t: 'Название'},
            {k: 'status', t: 'Статус', r: m => App.statusTag(m.status)},
            {k: 'free_tier', t: 'Бесплатный уровень', r: m => m.free_tier ? App.tag('да', 'ok') : App.tag('нет', 'warn')},
            {k: 'quota', t: 'Квота', r: m => esc(Object.keys(m.quota || {}).length ? JSON.stringify(m.quota) : 'неизвестно')},
            {k: 'quality_verified', t: 'Качество подтверждено', r: m => m.quality_verified ? App.tag('да', 'ok') : App.tag('нет', 'warn')}],
        });
      } else if (tab === 'agents') {
        const d = await App.get('/api/v1/ai/agents');
        box.innerHTML = App.card('Агенты A01–A12', '<div id="ag-tbl"></div>') +
          App.alert('info', 'Агент возвращает структурированный результат по JSON Schema. После ограниченной попытки исправления фиксируется schema_error. ИИ не подменяет расчётное ядро: TRL и реализуемость считает математический модуль.');
        App.table('ag-tbl', {
          rows: d.items, size: 12, search: false, export: 'ai_agents',
          cols: [{k: 'code', t: 'Код'}, {k: 'name', t: 'Агент'}, {k: 'purpose', t: 'Назначение'},
            {k: 'task_classes', t: 'Классы задач', r: a => esc((a.task_classes || []).join(', '))},
            {k: 'prompt_version', t: 'Версия промпта'},
            {k: 'enabled', t: 'Включён', r: a => a.enabled ? App.tag('да', 'ok') : App.tag('нет', 'warn')},
            {k: 'act', t: 'Запуск', r: a => App.can('ai.run') && rid ? `<button class="btn sm" data-run="${esc(a.code)}">Запустить</button>` : '—'}],
          after: el => el.querySelectorAll('[data-run]').forEach(b => b.addEventListener('click', async () => {
            b.disabled = true; b.textContent = '…';
            try { const r = await App.post(`/api/v1/ai/agents/${b.dataset.run}/run`, {research_id: rid}); App.toast('Агент ' + b.dataset.run + ': ' + esc(r.status || 'выполнено'), 'ok'); }
            catch (e) { App.toast(esc(e.message), 'error'); }
            App.render();
          })),
        });
      } else {
        if (!rid) { box.innerHTML = App.empty('Выберите исследование, чтобы увидеть задания ИИ', '🤖'); return; }
        const d = await App.get('/api/v1/ai/tasks', {research_id: rid});
        box.innerHTML = App.card('Задания агентам', '<div id="ai-t"></div>') +
          App.card('Запросы к провайдерам', '<div id="ai-r"></div>') +
          App.card('Ответы и структурированные результаты', (d.results || []).map(r => `
            <details class="acc"><summary>${esc(r.agent_code)} · ${App.dt(r.created_at)} · schema ${r.schema_valid ? '✓' : '✕'}</summary>
              <div class="tiny" style="white-space:pre-wrap">${esc(App.short(r.content, 1200))}</div>
              <details class="acc"><summary>structured_result (JSON)</summary><pre class="tiny" style="overflow:auto">${esc(JSON.stringify(r.structured_result, null, 1).slice(0, 4000))}</pre></details>
              <div class="tiny muted">Цитаты: ${esc(JSON.stringify(r.citations || []).slice(0, 6))}</div></details>`).join('') || App.empty('Ответов нет', '📭'));
        App.table('ai-t', {
          rows: d.tasks || [], size: 12, export: 'ai_tasks',
          cols: [{k: 'agent_code', t: 'Агент'}, {k: 'task_class', t: 'Класс'}, {k: 'mode', t: 'Режим'},
            {k: 'status', t: 'Статус', r: t => App.statusTag(t.status)}, {k: 'created_at', t: 'Создано', r: t => App.dt(t.created_at)}],
        });
        App.table('ai-r', {
          rows: d.requests || [], size: 12, export: 'ai_requests',
          cols: [{k: 'agent_code', t: 'Агент'}, {k: 'provider_id', t: 'Провайдер'}, {k: 'model_id', t: 'Модель'},
            {k: 'state', t: 'Состояние', r: r => App.statusTag(r.state)},
            {k: 'attempt_no', t: 'Попытка', cls: 'num'},
            {k: 'simulated', t: 'Источник ответа', r: r => r.simulated ? App.tag('детерминированный экстрактор', 'warn') : App.tag('модель', 'ok')},
            {k: 'latency_ms', t: 'Задержка, мс', cls: 'num'},
            {k: 'estimated_cost', t: 'Стоимость', cls: 'num', r: r => r.estimated_cost == null ? '—' : App.num(r.estimated_cost, 4)},
            {k: 'route_reason', t: 'Маршрут', r: r => esc(App.short((r.route_reason || {}).reason || r.route_reason || '', 70))},
            {k: 'error_code', t: 'Ошибка', r: r => r.error_code ? App.tag(r.error_code, 'err') : '—'}],
        });
      }
      App.ctx(App.alert('info', 'Статусы провайдера: active / degraded / quota_exhausted / rate_limited / auth_error / unavailable / disabled / paid_blocked / policy_blocked. При 429 применяется Retry-After и экспоненциальная задержка.'));
    },
  };

  // ============================================================ UI-07 Паспорт технологии
  Screens.passport = {
    title: 'Паспорт технологии', ui: 'UI-07', module: 'M11 / M12', group: 'Знания и доказательства', right: 'analytics.read',
    async render(body, params) {
      const host = await scaffold(body, '<button class="btn sm" onclick="App.go(\'report\')">В отчёт</button>');
      if (!host) return;
      const rid = App.S.researchId;
      const d = await App.get(`/api/v1/technologies/${rid}/passport`);
      const p = d.passport || {};
      const claimsBlock = arr => (arr || []).length ? arr.map(c => `<div class="evidence-item">
          ${App.tag(c.claim_type, c.claim_type)} ${App.statusTag(c.status)} <span class="tiny muted">уверенность ${App.num(c.confidence, 2)}</span>
          <div>${esc(c.claim_text || c.text)}</div>
          ${(c.evidence || []).map(e => `<div class="tiny muted">↳ ${esc(App.short(e.quote || e.locator || '', 140))} ${e.document_id ? `<a href="#/document/${esc(e.document_id)}">документ</a>` : ''}</div>`).join('')}
        </div>`).join('') : App.empty('Утверждений нет — пробел поиска', '🧾');
      const tab = params.tab || 'full';
      host.innerHTML = tabsHTML('passport', [{k: 'full', t: 'Паспорт'}, {k: 'ident', t: 'Идентификация (M11)'}, {k: 'graph', t: 'Граф связей'}], tab, {rid}) + '<div id="p-box"></div>';
      const box = document.getElementById('p-box');
      if (tab === 'ident') {
        const id = p.identification || {};
        box.innerHTML = App.card('Идентификация объекта', App.kv({
          'Название': esc(id.name), 'Запрос': esc(id.query), 'Сущности': esc((id.entities || []).join('; ')),
          'Назначение': esc(id.purpose || '—'), 'ID технологии': '<code>' + esc(d.technology_id) + '</code>',
          'Период публикаций': (p.period || {}).first_year + ' — ' + (p.period || {}).last_year,
        })) + App.card('Компоненты (требуют экспертного подтверждения)', (p.architecture_components || {}).components?.length ?
          `<ul>${p.architecture_components.components.map(c => `<li>${esc(typeof c === 'string' ? c : JSON.stringify(c))}</li>`).join('')}</ul>` :
          App.empty('Компоненты не извлечены из корпуса', '🧩'));
        return;
      }
      if (tab === 'graph') {
        const nodes = [{id: 'c', label: App.short((p.identification || {}).name, 24), kind: 'center'}];
        const links = [];
        (p.industry_base || {}).organizations?.slice(0, 8).forEach((o, i) => { nodes.push({id: 'o' + i, label: o[0]}); links.push({from: 'c', to: 'o' + i, confirmed: true}); });
        (p.countries || []).slice(0, 6).forEach((c, i) => { nodes.push({id: 's' + i, label: c.iso2}); links.push({from: 'c', to: 's' + i, confirmed: true}); });
        (p.alternatives || []).slice(0, 4).forEach((a, i) => { nodes.push({id: 'a' + i, label: App.short(a.name, 18)}); links.push({from: 'c', to: 'a' + i, confirmed: false}); });
        box.innerHTML = App.card('Граф связей технологии', Charts.graph(nodes, links));
        return;
      }
      box.innerHTML = `
        <div class="grid g4">
          ${App.kpi('TRL', (p.trl || {}).value ?? '—', 'уверенность ' + App.num((p.trl || {}).confidence, 2))}
          ${App.kpi('Реализуемость', (p.feasibility || {}).value == null ? '—' : App.num(p.feasibility.value, 1) + ' %', 'покрытие ' + App.pct((p.feasibility || {}).coverage))}
          ${App.kpi('Научная база', (p.science_base || {}).documents ?? 0, 'рецензируемых и препринтов')}
          ${App.kpi('Патентная база', (p.patent_base || {}).documents ?? 0, 'патент ≠ работоспособность')}
        </div>
        ${App.card('1. Идентификация и назначение', App.kv({
          'Объект': esc((p.identification || {}).name), 'Запрос': esc((p.identification || {}).query),
          'Принцип действия': esc((p.purpose_and_principle || {}).principle)}))}
        ${App.card('2. Принцип действия — утверждения', claimsBlock((p.purpose_and_principle || {}).claims))}
        ${App.card('3. Параметры (только из источников)', (p.parameters || {}).measured?.length ?
          `<table class="tbl"><tr><th>Параметр</th><th>Значение</th><th>Источник</th></tr>${p.parameters.measured.map(m => `<tr><td>${esc(m.name || m.parameter)}</td><td>${esc(m.value)} ${esc(m.unit || '')}</td><td class="tiny">${esc(m.document_id || '')}</td></tr>`).join('')}</table>` :
          App.empty('Измеренные параметры в источниках не найдены. Отсутствующее значение не подставляется.', '📐'))}
        ${App.card('4. Научная база', claimsBlock((p.science_base || {}).claims))}
        ${App.card('5. Патентная база', claimsBlock((p.patent_base || {}).claims))}
        ${App.card('6. Промышленная база', Charts.bar(((p.industry_base || {}).organizations || []).slice(0, 10).map(o => ({label: o[0], value: o[1]})), {unit: 'документов'}) + claimsBlock((p.industry_base || {}).claims))}
        ${App.card('7. География', Charts.bar((p.countries || []).slice(0, 12).map(c => ({label: c.iso2, value: c.documents})), {unit: 'документов'}))}
        ${App.card('8. Барьеры', (p.barriers || []).length ? `<table class="tbl"><tr><th>Тип</th><th>Критичность</th><th>Вероятность</th></tr>
          ${p.barriers.map(b => `<tr><td>${esc(b.barrier_type)}</td><td class="num">${App.num(b.criticality, 2)}</td><td class="num">${App.num(b.probability, 2)}</td></tr>`).join('')}</table>` : App.empty('Барьеры не выявлены — это пробел поиска, а не их отсутствие', '🚧'))}
        ${App.card('9. Доказательная база', App.kv({
          'Всего': (p.evidence_summary || {}).total, 'Независимых групп': (p.evidence_summary || {}).independence_groups,
          'По статусам': esc(JSON.stringify((p.evidence_summary || {}).by_status || {})),
          'Типы утверждений': esc(JSON.stringify(p.claim_type_counts || {}))}))}
        ${App.card('10. Ограничения', `<ul>${(p.limitations || []).map(l => `<li class="tiny">${esc(l)}</li>`).join('')}</ul>`)}
        ${App.card('Пробелы TRL', ((p.trl || {}).gaps || []).length ? `<ul>${p.trl.gaps.map(g => `<li class="tiny">Уровень ${g.level}: ${esc(g.text)} — ${esc(g.reason)}</li>`).join('')}</ul>` : App.empty('Пробелов нет', '✅'))}`;
      App.ctxObject('Паспорт', {'Технология': '<code>' + esc(d.technology_id) + '</code>',
        'TRL': (p.trl || {}).value, 'F': App.num((p.feasibility || {}).value, 1),
        'Доказательств': (p.evidence_summary || {}).total},
        '<div class="tiny muted" style="margin-top:8px">Каждое утверждение имеет claim_id и связано с Evidence. FACT без доказательства запрещён.</div>');
    },
  };

  // ============================================================ UI-08 TRL
  Screens.trl = {
    title: 'Уровень готовности технологии (TRL)', ui: 'UI-08', module: 'M16', group: 'Аналитика', right: 'analytics.read',
    async render(body) {
      const host = await scaffold(body, App.can('analytics.write') ? '<button class="btn sm" id="t-recalc">Пересчитать</button>' : '');
      if (!host) return;
      const rid = App.S.researchId;
      const d = await App.get(`/api/v1/analytics/${rid}`);
      const t = d.trl;
      if (!t) { host.innerHTML = App.empty('TRL ещё не рассчитан. Запустите исследование — этап 9 «Математические расчёты».', '📶'); return; }
      const levels = {};
      (t.criteria || []).forEach(c => { (levels[c.level] = levels[c.level] || []).push(c); });
      // ИД-08: нормативные формулировки ТЗ-03 (единые для всех документов комплекта)
      const NAMES = {1: 'Базовые принципы', 2: 'Концепция', 3: 'Экспериментальное подтверждение критической функции',
        4: 'Лабораторный компонент/макет', 5: 'Проверка в релевантной среде',
        6: 'Прототип подсистемы/системы в релевантной среде', 7: 'Прототип в эксплуатационной среде',
        8: 'Завершённая квалифицированная система', 9: 'Подтверждённая эксплуатация'};
      const conf = (d.confidence || []).find(c => c.subject_kind === 'trl');
      host.innerHTML = `
        <div class="grid g4">
          ${App.kpi('TRL', t.trl, 'максимальный подтверждённый уровень')}
          ${App.kpi('Уверенность оценки', conf ? App.num(conf.confidence, 2) : App.num(t.confidence, 2), 'отдельный показатель (ИД-10), не TRL и не вероятность')}
          ${App.kpi('Пробелов', (t.gaps || []).length, 'незакрытых критериев')}
          ${App.kpi('Методика', esc(t.methodology_version), 'хеш ' + esc(String(t.input_hash || '').slice(0, 10)))}
        </div>
        ${App.alert('info', 'TRL = максимальный уровень, у которого выполнены ВСЕ обязательные критерии и есть достаточные доказательства. Усреднение уровней запрещено (ТЗ-03 §4).')}
        ${App.card('Шкала 1–9', `<div class="ladder">${Object.keys(NAMES).map(l => `<div class="step ${+l <= t.trl ? 'on' : ''}">
          <b>${l}</b>${NAMES[l]}<div class="tiny muted">${+l <= t.trl ? '✓ подтверждён' : '✕ не подтверждён'}</div></div>`).join('')}</div>`)}
        ${App.card('Критерии по уровням', Object.entries(levels).map(([lvl, cs]) => `
          <details class="acc" ${+lvl <= t.trl + 1 ? 'open' : ''}><summary>Уровень ${lvl} — ${NAMES[lvl]} ${cs.every(c => !c.required || c.confirmed) ? '✓' : '✕'}</summary>
            <table class="tbl"><tr><th>Критерий (TRLn-Cnn)</th><th>Обяз.</th><th>Подтверждён</th><th>Уверенность</th><th>Классы док-в</th><th>Документы</th></tr>
            ${cs.map(c => `<tr><td>${esc(c.text)}<div class="tiny muted">${esc(c.criterion_id)} · ${esc(c.producer || '')}</div></td>
              <td>${(c.is_mandatory ?? c.required) ? 'да' : 'нет'}</td><td>${c.confirmed ? App.tag('да', 'ok') : App.tag('нет', 'warn')}</td>
              <td class="num">${c.confidence == null ? '—' : App.num(c.confidence, 2)}</td>
              <td class="tiny">${esc((c.evidence_classes || []).join(', ') || '—')}</td>
              <td class="tiny">${(c.document_ids || []).slice(0, 3).map(id => `<a href="#/document/${esc(id)}">док</a>`).join(' ') || '—'}</td></tr>`).join('')}
            </table></details>`).join(''))}
        ${conf ? App.card('Уверенность и независимость подтверждений (ИД-10/ИД-11)',
            App.kv({'Уверенность': App.num(conf.confidence, 3), 'Независимых групп': conf.independent_groups,
                    'Доказательств': conf.evidence_count, 'Противоречий': conf.contradictions,
                    'Методика': esc(conf.methodology_version)}) +
            (conf.limitations || []).map(l => App.alert('warn', esc(l))).join('')) : ''}
        ${App.card('Пробелы (что нужно найти/подтвердить)', (t.gaps || []).length ? `<table class="tbl"><tr><th>Уровень</th><th>Критерий</th><th>Причина</th></tr>
          ${t.gaps.map(g => `<tr><td>${g.level}</td><td>${esc(g.text)}<div class="tiny muted">${esc(g.criterion_id)}</div></td><td>${esc(g.reason)}</td></tr>`).join('')}</table>` : App.empty('Пробелов нет', '✅'))}`;
      document.getElementById('t-recalc')?.addEventListener('click', async () => {
        try { await App.post(`/api/v1/analytics/${rid}/recompute`, {}); App.toast('Расчёт ядра выполнен заново', 'ok'); App.render(); }
        catch (e) { App.toast(esc(e.message), 'error'); }
      });
      App.ctxObject('TRL', {'Уровень': t.trl, 'Уверенность': App.num(t.confidence, 2), 'Пробелов': (t.gaps || []).length,
        'Хеш входов': '<code>' + esc(String(t.input_hash || '').slice(0, 16)) + '</code>'},
        '<div class="tiny muted" style="margin-top:8px">Отсутствие подтверждения = «не подтверждено», а не ноль и не отрицательный факт.</div>');
    },
  };

  // ============================================================ UI-09 Реализуемость
  Screens.feasibility = {
    title: 'Техническая реализуемость', ui: 'UI-09', module: 'M17', group: 'Аналитика', right: 'analytics.read',
    async render(body) {
      const host = await scaffold(body, App.can('analytics.write') ? '<button class="btn sm" id="f-recalc">Пересчитать</button>' : '');
      if (!host) return;
      const rid = App.S.researchId;
      const d = await App.get(`/api/v1/analytics/${rid}`);
      const f = d.feasibility;
      if (!f) { host.innerHTML = App.empty('Реализуемость не рассчитана', '⚖️'); return; }
      const factors = f.factors || [];
      host.innerHTML = `
        <div class="grid g4">
          ${App.kpi('F (реализуемость)', f.score == null ? 'NULL' : App.num(f.score, 2) + ' %', f.score == null ? 'все факторы неизвестны — оценка не рассчитывается' : esc(f.interpretation || ''))}
          ${App.kpi('Покрытие C', App.pct(f.coverage), 'доля известных факторов по весу')}
          ${App.kpi('Диапазон', f.range_low == null ? '—' : App.num(f.range_low, 1) + '–' + App.num(f.range_high, 1), 'консервативная оценка ' + App.num(f.conservative, 1))}
          ${App.kpi('Неизвестно', (factors.filter(x => x.x == null).length) + '/' + factors.length, 'факторов исключено из расчёта')}
        </div>
        ${f.coverage_warning ? App.alert('warn', esc(f.coverage_warning)) : ''}
        ${f.interpretation_allowed === 0 || f.interpretation_allowed === false ? App.alert('warn', 'Интерпретация итоговой оценки ограничена: покрытие факторов ниже утверждённого порога (методика PROVISIONAL).') : ''}
        ${App.card('Шкала реализуемости', Charts.range(f.score, f.range_low, f.range_high))}
        ${(() => { const c = (d.confidence || []).find(x => x.subject_kind === 'feasibility');
          return c ? App.card('Уверенность оценки (отдельно от F и P)', App.kv({
            'Уверенность': App.num(c.confidence, 3), 'Независимых групп': c.independent_groups,
            'Покрытие': App.pct(c.coverage), 'Противоречий': c.contradictions}) +
            App.alert('info', 'F — оценка технической достижимости; P(T≤t) — вероятность достижения к сроку; уверенность — обоснованность оценки доказательствами. Показатели не подменяют друг друга (ИД-10).')) : ''; })()}
        <div class="grid g2">
          ${App.card('Профиль факторов (radar)', Charts.radar(factors.map(x => ({label: x.code + ' ' + App.short(x.name, 18), value: x.x}))))}
          ${App.card('Формула и правила', App.alert('info', 'F = 100 × Σ(wᵢ·xᵢ) / Σ(wᵢ·aᵢ), где aᵢ = 1 для известных факторов. Покрытие C = Σ(wᵢ·aᵢ)/Σwᵢ. Неизвестный фактор не приравнивается к нулю. F — оценка возможности достижения технического состояния, а не вероятность успеха.') +
            App.kv({'Классы': '0–20 низкая · 21–40 ограниченная · 41–60 средняя · 61–80 высокая · 81–100 очень высокая',
              'Методика': esc(f.methodology_version), 'Хеш входов': '<code>' + esc(String(f.input_hash || '').slice(0, 16)) + '</code>'}))}
        </div>
        ${App.card('Факторы, веса и оценки', '<div id="f-tbl"></div>')}
        ${App.card('Чувствительность', '<div id="f-sens"></div>')}
        ${App.card('Изменение весов (экспертный сценарий)', `<div class="grid g3" id="w-box">
          ${factors.map(x => `<label class="fld"><span>${esc(x.code)} · ${esc(x.name)} (вес ${App.num(x.weight, 2)})</span>
            <input type="number" step="0.01" min="0" max="1" value="${x.weight}" data-w="${esc(x.code)}"></label>`).join('')}</div>
          <button class="btn primary" id="w-apply" ${App.can('analytics.write') ? '' : 'disabled'}>Пересчитать с новыми весами</button>
          <span class="tiny muted">Изменение весов создаёт НОВУЮ версию методики (ИД-09); ранее рассчитанные результаты не переписываются.</span>`)}`;
      App.table('f-tbl', {
        rows: factors, size: 12, search: false, export: 'feasibility_factors',
        cols: [{k: 'code', t: 'Код'}, {k: 'name', t: 'Фактор'}, {k: 'weight', t: 'Вес', cls: 'num', r: x => App.num(x.weight, 2)},
          {k: 'x', t: 'Оценка xᵢ', cls: 'num', r: x => x.x == null ? App.tag('неизвестно', 'warn') : App.num(x.x, 2)},
          {k: 'is_available', t: 'Наличие aᵢ', cls: 'num', r: x => (x.is_available ?? (x.x != null)) ? App.tag('1', 'ok') : App.tag('0', 'warn')},
          {k: 'assessment', t: 'Статус оценки', r: x => App.tag(x.assessment, x.assessment === 'confirmed' ? 'ok' : x.assessment === 'partial' ? 'warn' : 'excluded')},
          {k: 'rationale', t: 'Обоснование', r: x => esc(App.short(x.rationale, 110))},
          {k: 'document_ids', t: 'Док-ты', cls: 'num', v: x => (x.document_ids || []).length},
          {k: 'producer', t: 'Источник оценки'}],
      });
      App.table('f-sens', {
        rows: f.sensitivity || [], size: 10, search: false, export: 'feasibility_sensitivity',
        cols: [{k: 'name', t: 'Фактор'}, {k: 'without_factor', t: 'F без фактора', cls: 'num', r: x => App.num(x.without_factor, 2)},
          {k: 'delta_without', t: 'Δ', cls: 'num', r: x => App.num(x.delta_without, 2)},
          {k: 'weight_plus30', t: 'F при весе +30 %', cls: 'num', r: x => App.num(x.weight_plus30, 2)},
          {k: 'delta_weight', t: 'Δ', cls: 'num', r: x => App.num(x.delta_weight, 2)}],
      });
      const recalc = async weights => {
        try { await App.post(`/api/v1/analytics/${rid}/recompute`, {weights}); App.toast('Пересчитано серверным ядром', 'ok'); App.render(); }
        catch (e) { App.toast(esc(e.message), 'error'); }
      };
      document.getElementById('f-recalc')?.addEventListener('click', () => recalc(null));
      document.getElementById('w-apply').addEventListener('click', () => {
        const w = {}; host.querySelectorAll('[data-w]').forEach(i => w[i.dataset.w] = +i.value); recalc(w);
      });
      App.ctxObject('Реализуемость', {'F': App.num(f.score, 2), 'Покрытие': App.pct(f.coverage),
        'Диапазон': App.num(f.range_low, 1) + '–' + App.num(f.range_high, 1), 'Неизвестных факторов': factors.filter(x => x.x == null).length});
    },
  };

  // ============================================================ UI-18 Коллективный анализ
  Screens.consensus = {
    title: 'Коллективный анализ и критика', ui: 'UI-18', module: 'M23 / M24', group: 'Мульти-ИИ', right: 'ai.read',
    async render(body, params) {
      const tab = params.tab || 'consensus';
      const host = await scaffold(body);
      if (!host) return;
      const rid = App.S.researchId;
      const d = await App.get('/api/v1/ai/tasks', {research_id: rid});
      host.innerHTML = tabsHTML('consensus', [{k: 'consensus', t: 'Коллективный анализ'}, {k: 'critic', t: 'Critic Engine (A11)'}], tab, {rid}) + '<div id="c-box"></div>';
      const box = document.getElementById('c-box');
      if (tab === 'critic') {
        const crit = (d.results || []).filter(r => r.agent_code === 'A11');
        box.innerHTML = App.alert('warn', 'Критик проверяет утверждения на противоречия, подмену тезиса и отсутствие доказательств. Замечания не удаляют данные, а понижают статус до PARTIAL / CONTRADICTED / UNVERIFIED.') +
          (crit.length ? crit.map(r => `<details class="acc" open><summary>Критика · ${App.dt(r.created_at)}</summary>
            <pre class="tiny" style="white-space:pre-wrap">${esc(JSON.stringify(r.structured_result, null, 1).slice(0, 5000))}</pre></details>`).join('')
            : App.empty('Замечаний критика нет (агент A11 не выполнялся)', '🧐'));
        return;
      }
      const cs = d.consensus || [];
      box.innerHTML = App.alert('info', 'Режимы: независимые оценки → перекрёстная проверка → арбитраж → синтез. Совпадение мнений моделей не является доказательством: итог опирается на Evidence и расчётное ядро.') +
        (cs.length ? cs.map(c => App.card(esc(c.topic) + ' · режим ' + esc(c.mode), `
          <b class="tiny muted">Позиции</b>
          <table class="tbl"><tr><th>Участник</th><th>Позиция</th><th>Уверенность</th></tr>
          ${(c.positions || []).map(p => `<tr><td>${esc(p.agent || p.agent_code || p.model || '—')}</td><td class="tiny">${esc(App.short(JSON.stringify(p.position || p.answer || p), 220))}</td><td class="num">${App.num(p.confidence, 2)}</td></tr>`).join('')}</table>
          <b class="tiny muted">Конфликты</b>
          ${(c.conflicts || []).length ? `<ul>${c.conflicts.map(x => `<li class="tiny">${esc(typeof x === 'string' ? x : JSON.stringify(x))}</li>`).join('')}</ul>` : '<div class="tiny muted">Конфликтов не зафиксировано</div>'}
          <b class="tiny muted">Разрешение</b><div class="tiny">${esc(JSON.stringify(c.resolution || {}))}</div>
          <b class="tiny muted">Синтез</b><div class="tiny">${esc(App.short(JSON.stringify(c.synthesis || {}), 900))}</div>`)) .join('')
          : App.empty('Коллективный анализ не выполнялся для этого исследования', '👥'));
    },
  };

  // ============================================================ UI-19 Доказательства
  Screens.evidence = {
    title: 'Доказательная база', ui: 'UI-19', module: 'M25', group: 'Знания и доказательства', right: 'research.read',
    async render(body, params) {
      const host = await scaffold(body);
      if (!host) return;
      const rid = App.S.researchId;
      const [an, claims] = await Promise.all([App.get(`/api/v1/analytics/${rid}`), App.get('/api/v1/claims', {research_id: rid, ctype: params.ctype, status: params.status})]);
      const s = an.evidence_summary || {};
      const items = claims.items || claims || [];
      host.innerHTML = `
        <div class="grid g4">
          ${App.kpi('Доказательств', s.total ?? 0, 'независимых групп: ' + (s.independence_groups ?? 0))}
          ${App.kpi('Подтверждено', (s.by_status || {}).SUPPORTED ?? 0, 'SUPPORTED')}
          ${App.kpi('Частично / не проверено', ((s.by_status || {}).PARTIAL ?? 0) + ' / ' + ((s.by_status || {}).UNVERIFIED ?? 0), 'PARTIAL / UNVERIFIED')}
          ${App.kpi('Опровергнуто', (s.by_status || {}).CONTRADICTED ?? 0, 'CONTRADICTED')}
        </div>
        ${App.alert('info', 'Типы утверждений: FACT (только с доказательством), ANALYSIS, HYPOTHESIS, FORECAST. Статусы: SUPPORTED / PARTIAL / CONTRADICTED / UNVERIFIED / SUPERSEDED. Классы доказательств и группы независимости учитываются при расчёте TRL.')}
        ${App.card('Утверждения', `<div class="tbl-toolbar">
            <select id="c-type"><option value="">все типы</option>${['FACT', 'ANALYSIS', 'HYPOTHESIS', 'FORECAST'].map(t => `<option ${params.ctype === t ? 'selected' : ''}>${t}</option>`).join('')}</select>
            <select id="c-status"><option value="">все статусы</option>${['SUPPORTED', 'PARTIAL', 'CONTRADICTED', 'UNVERIFIED', 'SUPERSEDED'].map(t => `<option value="${t}" ${params.status === t ? 'selected' : ''}>${App.STATUS_RU[t]}</option>`).join('')}</select>
          </div><div id="c-tbl"></div>`)}`;
      const reload = () => App.go('evidence', {rid, ctype: document.getElementById('c-type').value, status: document.getElementById('c-status').value});
      document.getElementById('c-type').addEventListener('change', reload);
      document.getElementById('c-status').addEventListener('change', reload);
      App.table('c-tbl', {
        rows: items, size: 25, export: 'claims',
        cols: [{k: 'claim_type', t: 'Тип', r: c => App.tag(c.claim_type, c.claim_type)},
          {k: 'claim_text', t: 'Утверждение', r: c => esc(App.short(c.claim_text, 160))},
          {k: 'section', t: 'Раздел'}, {k: 'status', t: 'Статус', r: c => App.statusTag(c.status)},
          {k: 'confidence', t: 'Уверенность', cls: 'num', r: c => App.num(c.confidence, 2)},
          {k: 'produced_by', t: 'Источник', r: c => esc(c.produced_by)},
          {k: 'id', t: 'claim_id', r: c => '<code>' + esc(String(c.id).slice(0, 12)) + '</code>'}],
        onRow: async c => {
          const ev = await App.get('/api/v1/evidence', {research_id: rid, claim_id: c.id});
          App.ctx(`<b>Доказательства утверждения</b><div class="tiny muted">${esc(App.short(c.claim_text, 200))}</div>
            ${(ev.items || []).map(evItem).join('') || App.empty('Доказательств нет — статус UNVERIFIED', '🧾')}
            ${App.can('evidence.write') ? `<button class="btn sm" id="ctx-add">Добавить доказательство</button>` : ''}`);
          document.getElementById('ctx-add')?.addEventListener('click', () => evidenceModal(rid, null));
        },
      });
    },
  };

  // ============================================================ UI-20 Генератор отчёта
  Screens.report = {
    title: 'Генератор отчёта и экспорт', ui: 'UI-20', module: 'M27 / M28', group: 'Отчётность', right: 'research.read',
    async render(body, params) {
      const tab = params.tab || 'report';
      const host = await scaffold(body);
      if (!host) return;
      const rid = App.S.researchId;
      const d = await App.get('/api/v1/reports', {research_id: rid});
      const FORMATS = [['html', 'Интерактивный HTML'], ['pdf', 'PDF'], ['docx', 'DOCX (редактируемый)'], ['xlsx', 'XLSX'], ['json', 'JSON'], ['csv', 'CSV (таблицы)']];
      host.innerHTML = tabsHTML('report', [{k: 'report', t: 'Отчёт'}, {k: 'export', t: 'Экспорт данных'}], tab, {rid}) + '<div id="r-box"></div>';
      const box = document.getElementById('r-box');
      if (tab === 'export') {
        box.innerHTML = App.card('Экспорт журнала и данных', `
          <div class="row">
            <a class="btn" href="${App.fileURL('/api/v1/logs/export', {research_id: rid, fmt: 'json'})}">Журнал JSON</a>
            <a class="btn" href="${App.fileURL('/api/v1/logs/export', {research_id: rid, fmt: 'csv'})}">Журнал CSV</a>
            <a class="btn" href="${App.fileURL('/api/v1/logs/export', {research_id: rid, fmt: 'txt'})}">Журнал TXT</a>
            <button class="btn" id="exp-docs">Выгрузить документы CSV</button>
            <button class="btn" id="exp-analytics">Выгрузить аналитику JSON</button>
          </div>
          ${App.alert('info', 'Любая таблица на экране выгружается кнопкой «Экспорт CSV»; графики раскрывают исходные данные в текстовой альтернативе.')}`);
        document.getElementById('exp-docs').addEventListener('click', async () => {
          const docs = await App.get('/api/v1/documents', {research_id: rid, limit: 1000});
          App.exportCSV('documents', [{k: 'title', t: 'Название'}, {k: 'url', t: 'URL'}, {k: 'source_code', t: 'Источник'},
            {k: 'country_code', t: 'Страна'}, {k: 'published_at', t: 'Дата'}, {k: 'score', t: 'R'}, {k: 'rclass', t: 'Класс'},
            {k: 'evidence_class', t: 'Класс док-ва'}], docs.items, (c, r) => r[c.k]);
        });
        document.getElementById('exp-analytics').addEventListener('click', async () => {
          const an = await App.get(`/api/v1/analytics/${rid}`);
          App.download('analytics-' + rid + '.json', JSON.stringify(an, null, 1), 'application/json');
        });
        return;
      }
      box.innerHTML = `
        ${App.card('Состав отчёта', `<div class="tiny muted">Постановка задачи · методика и её версия · поисковая стратегия · охват источников · описание технологии · научная/патентная/промышленная база · TRL · реализуемость · барьеры · альтернативы · тренды · сценарии · доказательства · ограничения · выводы · приложения.</div>
          <div class="row" style="margin-top:10px">${FORMATS.map(([f, n]) => `<label class="chip on"><input type="checkbox" value="${f}" checked>${n}</label>`).join('')}</div>
          <div class="row" style="margin-top:10px"><button class="btn primary" id="r-gen" ${App.can('report.write') ? '' : 'disabled'}>Сформировать отчёт</button>
          <span class="tiny muted">Выгрузка содержит дату, версии методик и моделей, параметры, источники и предупреждения.</span></div>`)}
        <div id="r-list">${(d.items || []).length ? '' : App.empty('Отчёты ещё не формировались', '📝')}</div>`;
      const paintReports = items => {
        App.setHTML('r-list', items.map(r => App.card(
          esc(r.title) + ' · ' + App.dt(r.created_at), `
          ${App.kv({'Статус': App.statusTag(r.status), 'Методика': esc(r.methodology_version),
            'Хеш снимка': '<code>' + esc(String(r.snapshot_hash || '').slice(0, 16)) + '</code>',
            'ID': '<code>' + esc(r.id) + '</code>'})}
          <div class="row" style="margin-top:8px">${Object.keys(r.files || {}).map(f => (r.missing_files || []).includes(f)
            ? `<button class="btn sm" disabled title="Файл отсутствует на диске — сформируйте отчёт заново">${esc(f.toUpperCase())} ⚠</button>`
            : `<a class="btn sm" href="${App.fileURL('/api/v1/reports/' + r.id + '/file', {fmt: f})}" target="_blank">${esc(f.toUpperCase())} ↗</a>`).join('')}</div>
          ${(r.missing_files || []).length ? App.alert('warn', 'Файлы отчёта отсутствуют на диске: ' + r.missing_files.map(f => esc(f.toUpperCase())).join(', ') + '. Запись отчёта сохранена, сами файлы — нет (перенос состояния или чистка каталога var/files). Нажмите «Сформировать отчёт», чтобы создать их заново.') : ''}
          ${(r.warnings || []).length ? App.alert('warn', (r.warnings || []).map(esc).join('<br>')) : ''}`)).join(''));
      };
      paintReports(d.items || []);
      document.getElementById('r-gen')?.addEventListener('click', async () => {
        const formats = [...box.querySelectorAll('input[type=checkbox]:checked')].map(x => x.value);
        const b = document.getElementById('r-gen'); b.disabled = true; b.textContent = 'Формирование…';
        try {
          const res = await App.post('/api/v1/reports', {research_id: rid, formats});
          App.toast('Отчёт готов: ' + Object.keys(res.files || {}).join(', '), 'ok');
          const upd = await App.get('/api/v1/reports', {research_id: rid});
          paintReports(upd.items || []);
        } catch (e) { App.toast(esc(e.message), 'error'); }
        b.disabled = false; b.textContent = 'Сформировать отчёт';
      });
      App.ctx(App.alert('info', 'PDF формируется встроенным генератором без внешних зависимостей; при наличии WeasyPrint используется типографская вёрстка. HTML-отчёт интерактивен и самодостаточен.'));
    },
  };
})();
