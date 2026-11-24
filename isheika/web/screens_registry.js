/* ИЩЕЙКА НТР AI — экраны аналитики и реестров: UI-10…UI-17, UI-21…UI-26. */
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
  const docLink = d => `<a href="#/document/${esc(d.id)}">${esc(App.short(d.title, 90))}</a>`;
  const TARGET_RU = {scientific_result: 'Научный результат', working_prototype: 'Работающий прототип',
    industrial_production: 'Промышленное производство', wide_adoption: 'Широкое внедрение'};

  // ============================================================ UI-11 Научная аналитика
  Screens.science = {
    title: 'Научная аналитика', ui: 'UI-11', module: 'M14', group: 'Аналитика', right: 'analytics.read',
    async render(body) {
      const host = await scaffold(body); if (!host) return;
      const rid = App.S.researchId;
      const [an, docs, claims] = await Promise.all([
        App.get(`/api/v1/analytics/${rid}`),
        App.get('/api/v1/documents', {research_id: rid, limit: 500}),
        App.get('/api/v1/claims', {research_id: rid})]);
      const sci = docs.items.filter(d => ['article', 'journal-article', 'preprint', 'report', 'dataset', 'thesis'].includes(d.doc_type));
      const byClass = {};
      sci.forEach(d => byClass[d.evidence_class] = (byClass[d.evidence_class] || 0) + 1);
      const cl = (claims.items || claims).filter(c => c.section === 'A02');
      host.innerHTML = `
        <div class="grid g4">
          ${App.kpi('Научных документов', sci.length, 'статьи, препринты, отчёты, данные')}
          ${App.kpi('Рецензируемых', byClass.primary_peer_reviewed || 0, 'высший класс доказательства')}
          ${App.kpi('Препринтов', byClass.preprint || 0, 'не подтверждают результат')}
          ${App.kpi('Утверждений A02', cl.length, 'научная база')}
        </div>
        <div class="grid g2">
          ${App.card('Динамика научных публикаций', Charts.line([
            {name: 'Статьи', points: ((an.trends || {}).articles || []).map(p => ({x: p.year, y: p.value}))},
            {name: 'Отчёты', points: ((an.trends || {}).reports || []).map(p => ({x: p.year, y: p.value}))}],
            {unit: 'документов в год', xLabel: 'год'}))}
          ${App.card('Классы доказательств', Charts.bar(Object.entries(byClass).map(([k, v]) => ({label: k, value: v})), {unit: 'документов'}))}
        </div>
        ${App.card('Научные документы', '<div id="sci-tbl"></div>')}
        ${App.card('Утверждения научной базы', cl.length ? `<table class="tbl"><tr><th>Тип</th><th>Утверждение</th><th>Статус</th></tr>
          ${cl.map(c => `<tr><td>${App.tag(c.claim_type, c.claim_type)}</td><td>${esc(c.claim_text)}</td><td>${App.statusTag(c.status)}</td></tr>`).join('')}</table>` : App.empty('Утверждений нет', '🔬'))}`;
      App.table('sci-tbl', {
        rows: sci, size: 20, export: 'science_documents', sort: 'score',
        cols: [{k: 'title', t: 'Работа', r: docLink}, {k: 'doc_type', t: 'Тип'},
          {k: 'evidence_class', t: 'Класс док-ва'}, {k: 'score', t: 'R', cls: 'num', r: d => App.num(d.score, 3)},
          {k: 'country_code', t: 'Страна'}, {k: 'published_at', t: 'Дата', r: d => App.donly(d.published_at)},
          {k: 'independence_group', t: 'Группа независимости'}, {k: 'oa_status', t: 'OA'}],
        onRow: d => App.go('document', {id: d.id}),
        empty: 'Научных документов не найдено — пробел поиска, а не отсутствие исследований',
      });
      App.ctx(App.alert('info', 'Препринт и пресс-релиз не подтверждают работоспособность. Повторная публикация того же результата не считается независимым подтверждением (группы независимости).'));
    },
  };

  // ============================================================ UI-10 Патентная аналитика
  Screens.patents = {
    title: 'Патентная аналитика', ui: 'UI-10', module: 'M13', group: 'Аналитика', right: 'analytics.read',
    async render(body) {
      const host = await scaffold(body); if (!host) return;
      const rid = App.S.researchId;
      const [an, docs, claims] = await Promise.all([
        App.get(`/api/v1/analytics/${rid}`),
        App.get('/api/v1/documents', {research_id: rid, doc_type: 'patent', limit: 500}),
        App.get('/api/v1/claims', {research_id: rid})]);
      const pats = docs.items;
      const byCountry = {};
      pats.forEach(d => byCountry[d.country_code || '??'] = (byCountry[d.country_code || '??'] || 0) + 1);
      const cl = (claims.items || claims).filter(c => c.section === 'A03');
      host.innerHTML = `
        <div class="grid g4">
          ${App.kpi('Патентных документов', pats.length, 'официальные реестры и API')}
          ${App.kpi('Юрисдикций', Object.keys(byCountry).length, 'по коду ведомства/страны')}
          ${App.kpi('Утверждений A03', cl.length, 'патентная база')}
          ${App.kpi('Класс док-ва', 'patent', 'подтверждает приоритет, не работоспособность')}
        </div>
        ${App.alert('warn', 'Патент не является доказательством работоспособности изделия. Для уровней TRL ≥ 5 требуются испытания/эксплуатация, а не патентная публикация.')}
        <div class="grid g2">
          ${App.card('Динамика патентования', Charts.line([{name: 'Патенты', points: ((an.trends || {}).patents || []).map(p => ({x: p.year, y: p.value}))}], {unit: 'документов в год', xLabel: 'год'}))}
          ${App.card('Патенты по юрисдикциям', Charts.bar(Object.entries(byCountry).map(([k, v]) => ({label: k, value: v})), {unit: 'документов'}))}
        </div>
        ${App.card('Патентные документы', '<div id="pat-tbl"></div>')}
        ${App.card('Утверждения патентной базы', cl.length ? `<table class="tbl"><tr><th>Тип</th><th>Утверждение</th><th>Статус</th></tr>
          ${cl.map(c => `<tr><td>${App.tag(c.claim_type, c.claim_type)}</td><td>${esc(c.claim_text)}</td><td>${App.statusTag(c.status)}</td></tr>`).join('')}</table>` : App.empty('Утверждений нет', '📜'))}`;
      App.table('pat-tbl', {
        rows: pats, size: 20, export: 'patents', sort: 'published_at',
        cols: [{k: 'title', t: 'Патент / заявка', r: docLink}, {k: 'external_id', t: 'Номер'},
          {k: 'country_code', t: 'Ведомство'}, {k: 'published_at', t: 'Дата', r: d => App.donly(d.published_at)},
          {k: 'organizations', t: 'Заявители', r: d => esc((d.organizations || []).join('; '))},
          {k: 'score', t: 'R', cls: 'num', r: d => App.num(d.score, 3)},
          {k: 'source_code', t: 'Источник'}],
        onRow: d => App.go('document', {id: d.id}),
        empty: 'Патентных документов нет. Возможные причины: коннекторы EPO/USPTO/Роспатент требуют ключ (A1/A2), квота исчерпана или запрос не совпал.',
      });
      App.ctx(App.alert('info', 'GUI Espacenet и автоматизация веб-интерфейсов запрещены стоп-листом. Используются официальные API: EPO OPS (OAuth2, 4 ГБ/нед), USPTO ODP (X-API-KEY), KIPRIS (1000/мес).'));
    },
  };

  // ============================================================ UI-12 Промышленная аналитика
  Screens.industry = {
    title: 'Промышленная аналитика', ui: 'UI-12', module: 'M15', group: 'Аналитика', right: 'analytics.read',
    async render(body) {
      const host = await scaffold(body); if (!host) return;
      const rid = App.S.researchId;
      const [pp, claims] = await Promise.all([
        App.get(`/api/v1/technologies/${rid}/passport`),
        App.get('/api/v1/claims', {research_id: rid})]);
      const p = pp.passport || {};
      const orgs = (p.industry_base || {}).organizations || [];
      const cl = (claims.items || claims).filter(c => c.section === 'A04');
      host.innerHTML = `
        <div class="grid g3">
          ${App.kpi('Организаций', orgs.length, 'извлечено из корпуса')}
          ${App.kpi('Стран', (p.countries || []).length, 'география публикаций')}
          ${App.kpi('Утверждений A04', cl.length, 'промышленная база')}
        </div>
        <div class="grid g2">
          ${App.card('Организации-лидеры', Charts.bar(orgs.slice(0, 12).map(o => ({label: o[0], value: o[1]})), {unit: 'документов'}))}
          ${App.card('География', Charts.bar((p.countries || []).slice(0, 12).map(c => ({label: c.iso2, value: c.documents})), {unit: 'документов'}))}
        </div>
        ${App.card('Организации', '<div id="org-tbl"></div>')}
        ${App.card('Утверждения промышленной базы', cl.length ? `<table class="tbl"><tr><th>Тип</th><th>Утверждение</th><th>Статус</th></tr>
          ${cl.map(c => `<tr><td>${App.tag(c.claim_type, c.claim_type)}</td><td>${esc(c.claim_text)}</td><td>${App.statusTag(c.status)}</td></tr>`).join('')}</table>` : App.empty('Утверждений нет', '🏭'))}
        ${App.alert('warn', 'Отсутствие промышленных упоминаний в открытых источниках не означает отсутствия работ: закрытые и ведомственные материалы недоступны легально.')}`;
      App.table('org-tbl', {
        rows: orgs.map(o => ({name: o[0], documents: o[1]})), size: 20, export: 'organizations', sort: 'documents',
        cols: [{k: 'name', t: 'Организация'}, {k: 'documents', t: 'Документов', cls: 'num'}],
        empty: 'Организации не извлечены',
      });
    },
  };

  // ============================================================ UI-13 Сравнение технологий
  Screens.compare = {
    title: 'Сравнение технологий и исследований', ui: 'UI-13', module: 'M26', group: 'Аналитика', right: 'analytics.read',
    async render(host, params) {
      await App.loadResearches(true);
      const all = App.S.researches;
      const sel = (params.ids ? params.ids.split(',') : all.slice(0, 4).map(r => r.id)).filter(Boolean);
      host.innerHTML = App.card('Выбор объектов сравнения', `
        <div class="chips" id="cmp-chips" style="max-height:150px">${all.map(r => `<label class="chip ${sel.includes(r.id) ? 'on' : ''}"><input type="checkbox" value="${esc(r.id)}" ${sel.includes(r.id) ? 'checked' : ''}>${esc(App.short(r.title, 46))}</label>`).join('')}</div>
        <div class="row" style="margin-top:8px"><button class="btn primary" id="cmp-apply">Сравнить</button>
        <span class="tiny muted">Сравнение по единым критериям: TRL, реализуемость, покрытие, доказательная база, барьеры, прогноз.</span></div>`) +
        `<div id="cmp-box">${App.spinner()}</div>`;
      document.getElementById('cmp-apply').addEventListener('click', () => {
        const ids = [...host.querySelectorAll('#cmp-chips input:checked')].map(x => x.value);
        App.go('compare', {ids: ids.join(',')});
      });
      const box = document.getElementById('cmp-box');
      if (!sel.length) { box.innerHTML = App.empty('Выберите хотя бы одно исследование', '🆚'); return; }
      const rows = [];
      for (const id of sel.slice(0, 8)) {
        try {
          const an = await App.get(`/api/v1/analytics/${id}`);
          const r = all.find(x => x.id === id) || {};
          const f = an.feasibility || {}, t = an.trl || {};
          const base = ((an.forecast || {}).scenarios || {}).working_prototype;
          rows.push({id, title: r.title || id, trl: t.trl, conf: t.confidence, F: f.score, coverage: f.coverage,
            range: f.range_low == null ? '—' : App.num(f.range_low, 1) + '–' + App.num(f.range_high, 1),
            barriers: (an.barriers || []).length, evidence: (an.evidence_summary || {}).total,
            groups: (an.evidence_summary || {}).independence_groups,
            p5: base ? (base[1] || {}).probability : null, docs: (r.counts || {}).documents});
        } catch (e) { rows.push({id, title: id, error: e.message}); }
      }
      box.innerHTML = `
        ${App.card('Сводная таблица', '<div id="cmp-tbl"></div>')}
        <div class="grid g2">
          ${App.card('TRL', Charts.bar(rows.map(r => ({label: App.short(r.title, 12), value: r.trl || 0})), {unit: 'уровень 1–9'}))}
          ${App.card('Реализуемость F', Charts.bar(rows.map(r => ({label: App.short(r.title, 12), value: r.F || 0})), {unit: '%'}))}
        </div>
        ${App.alert('info', 'Сравнение корректно только при одинаковой версии методики и сопоставимом охвате источников. Различие в покрыении (C) объясняет часть разницы оценок.')}`;
      App.table('cmp-tbl', {
        rows, size: 10, search: false, export: 'comparison',
        cols: [{k: 'title', t: 'Технология', r: r => `<a href="#/research/${esc(r.id)}">${esc(App.short(r.title, 50))}</a>`},
          {k: 'trl', t: 'TRL', cls: 'num'}, {k: 'conf', t: 'Уверенность', cls: 'num', r: r => App.num(r.conf, 2)},
          {k: 'F', t: 'F, %', cls: 'num', r: r => App.num(r.F, 1)},
          {k: 'coverage', t: 'Покрытие', cls: 'num', r: r => App.pct(r.coverage)},
          {k: 'range', t: 'Диапазон F'}, {k: 'barriers', t: 'Барьеров', cls: 'num'},
          {k: 'evidence', t: 'Доказательств', cls: 'num'}, {k: 'groups', t: 'Незав. групп', cls: 'num'},
          {k: 'p5', t: 'P(прототип ≤ 5 лет)', cls: 'num', r: r => r.p5 == null ? 'нет данных' : App.num(r.p5, 2)},
          {k: 'error', t: 'Ошибка', r: r => r.error ? App.tag(r.error, 'err') : '—'}],
      });
    },
  };

  // ============================================================ UI-14 Барьеры и риски
  Screens.barriers = {
    title: 'Барьеры и риски', ui: 'UI-14', module: 'M18', group: 'Аналитика', right: 'analytics.read',
    async render(body) {
      const host = await scaffold(body); if (!host) return;
      const rid = App.S.researchId;
      const [an, meth] = await Promise.all([App.get(`/api/v1/analytics/${rid}`), App.get('/api/v1/methodology')]);
      const bs = an.barriers || [];
      const types = ((meth.barriers || {}).types) || [];
      const found = new Set(bs.map(b => b.barrier_type));
      host.innerHTML = `
        <div class="grid g3">
          ${App.kpi('Выявлено барьеров', bs.length, 'из ' + types.length + ' классов методики')}
          ${App.kpi('Максимальная критичность', bs.length ? App.num(Math.max(...bs.map(b => b.criticality)), 2) : '—', 'шкала 0–1')}
          ${App.kpi('Не выявлено классов', types.length - found.size, 'пробел поиска, не отсутствие барьера')}
        </div>
        <div class="grid g2">
          ${App.card('Матрица рисков', Charts.riskMatrix(bs))}
          ${App.card('Классы барьеров (11)', `<div class="row">${types.map(t => App.tag(t + (found.has(t) ? ' ✓' : ' ?'), found.has(t) ? 'warn' : '')).join(' ')}</div>
            ${App.alert('info', 'Критичность и вероятность — стартовые эвристики по числу и классу подтверждений; требуют экспертного подтверждения. Отсутствие найденных барьеров не означает их отсутствия.')}`)}
        </div>
        ${App.card('Реестр барьеров', '<div id="bar-tbl"></div>')}`;
      App.table('bar-tbl', {
        rows: bs, size: 15, export: 'barriers', sort: 'criticality',
        cols: [{k: 'barrier_type', t: 'Класс'}, {k: 'title', t: 'Барьер'},
          {k: 'criticality', t: 'Критичность', cls: 'num', r: b => App.num(b.criticality, 2)},
          {k: 'probability', t: 'Вероятность', cls: 'num', r: b => App.num(b.probability, 2)},
          {k: 'evidence_ids', t: 'Доказательств', cls: 'num', v: b => (b.evidence_ids || []).length},
          {k: 'dependencies', t: 'Зависимости', r: b => esc((b.dependencies || []).join('; ') || '—')},
          {k: 'workarounds', t: 'Пути обхода', r: b => esc((b.workarounds || []).join('; ') || 'не найдены')}],
        empty: 'Барьеры не выявлены: это пробел поиска. Расширьте запрос или источники.',
      });
    },
  };

  // ============================================================ UI-15 Альтернативы
  Screens.alternatives = {
    title: 'Альтернативные решения', ui: 'UI-15', module: 'M19', group: 'Аналитика', right: 'analytics.read',
    async render(body) {
      const host = await scaffold(body); if (!host) return;
      const rid = App.S.researchId;
      const [an, meth] = await Promise.all([App.get(`/api/v1/analytics/${rid}`), App.get('/api/v1/methodology')]);
      const alts = an.alternatives || [];
      const crit = ((meth.alternatives || {}).criteria) || [];
      host.innerHTML = `
        ${App.alert('info', 'Сравнение альтернатив ведётся по единым критериям. Незаполненный критерий = «неизвестно», а не ноль; заполнение требует данных испытаний из источников.')}
        ${App.card('Альтернативы (' + alts.length + ')', '<div id="alt-tbl"></div>')}
        ${App.card('Критерии сравнения', `<div class="row">${crit.map(c => App.tag(c)).join(' ')}</div>`)}`;
      App.table('alt-tbl', {
        rows: alts, size: 15, export: 'alternatives',
        cols: [{k: 'name', t: 'Альтернатива'}, ...crit.map(c => ({k: c, t: c, v: a => (a.criteria || {})[c], r: a => {
          const v = (a.criteria || {})[c];
          return v == null || v === '' ? App.tag('неизвестно', 'warn') : esc(App.short(v, 80));
        }}))],
        empty: 'Альтернативы не извлечены. Уточните запрос или добавьте источники по конкурирующим решениям.',
      });
    },
  };

  // ============================================================ UI-16 Тренды
  Screens.trends = {
    title: 'Анализ трендов', ui: 'UI-16', module: 'M20', group: 'Аналитика', right: 'analytics.read',
    async render(body, params) {
      const host = await scaffold(body); if (!host) return;
      const rid = App.S.researchId;
      const [an, pp] = await Promise.all([App.get(`/api/v1/analytics/${rid}`), App.get(`/api/v1/technologies/${rid}/passport`)]);
      const t = an.trends || {};
      const p = pp.passport || {};
      const series = [['publications', 'Все публикации'], ['articles', 'Статьи'], ['patents', 'Патенты'], ['reports', 'Отчёты']];
      host.innerHTML = `
        ${App.alert('info', 'Год без наблюдений обозначается разрывом линии и меткой «нет данных», а не нулём. Динамика считается по документам прямого и смежного соответствия.')}
        ${App.card('Динамика по типам документов', Charts.line(series.map(([k, n]) => ({name: n, points: (t[k] || []).map(x => ({x: x.year, y: x.value}))})), {unit: 'документов в год', xLabel: 'год'}))}
        <div class="grid g2">
          ${App.card('Страны', Charts.bar((p.countries || []).slice(0, 12).map(c => ({label: c.iso2, value: c.documents})), {unit: 'документов'}))}
          ${App.card('Организации', Charts.bar(((p.industry_base || {}).organizations || []).slice(0, 12).map(o => ({label: o[0], value: o[1]})), {unit: 'документов'}))}
        </div>
        ${App.card('Ряды данных', '<div id="tr-tbl"></div>')}`;
      const rows = [];
      series.forEach(([k, n]) => (t[k] || []).forEach(x => rows.push({metric: n, year: x.year, value: x.value})));
      App.table('tr-tbl', {
        rows, size: 25, export: 'trends', sort: 'year',
        cols: [{k: 'metric', t: 'Ряд'}, {k: 'year', t: 'Год', cls: 'num'},
          {k: 'value', t: 'Документов', cls: 'num', r: r => r.value == null ? App.tag('нет данных', 'warn') : r.value}],
      });
    },
  };

  // ============================================================ UI-17 Прогноз
  Screens.forecast = {
    title: 'Прогноз 0–50 лет', ui: 'UI-17', module: 'M21 / M22', group: 'Аналитика', right: 'analytics.read',
    async render(body, params) {
      const tab = params.tab || 'chart';
      const host = await scaffold(body); if (!host) return;
      const rid = App.S.researchId;
      const an = await App.get(`/api/v1/analytics/${rid}`);
      const f = an.forecast;
      if (!f) { host.innerHTML = App.empty('Прогноз не построен. Запустите этап 10 «Прогнозирование».', '🔮'); return; }
      const targets = Object.keys(f.scenarios || {});
      const target = params.target && targets.includes(params.target) ? params.target : targets[0];
      host.innerHTML = tabsHTML('forecast', [{k: 'chart', t: 'Сценарный график'}, {k: 'scenarios', t: 'Сценарии и допущения'}, {k: 'table', t: 'Таблица горизонтов'}], tab, {rid}) +
        `<div class="card"><div class="row"><span class="tiny muted">Целевое состояние:</span>
          <select id="fc-target" style="max-width:340px">${targets.map(t => `<option value="${t}" ${t === target ? 'selected' : ''}>${esc(TARGET_RU[t] || t)}</option>`).join('')}</select>
          ${f.monotonic_ok ? App.tag('P(T≤t) не убывает ✓', 'ok') : App.tag('нарушена монотонность ✕', 'err')}
          ${App.tag('метод: ' + (f.method || ''), '')}</div></div>
        <div id="fc-box"></div>`;
      document.getElementById('fc-target').addEventListener('change', e => App.go('forecast', {rid, tab, target: e.target.value}));
      const box = document.getElementById('fc-box');
      const sc = (f.scenarios || {})[target] || {};
      if (tab === 'chart') {
        box.innerHTML = App.card('Fan chart: вероятность достижения состояния к горизонту', Charts.fan(f.horizons, sc)) +
          App.alert('warn', 'Режим представления задаётся СЕРВЕРОМ по горизонту и статусу калибровки (ИД-05). На горизонтах 20–50 лет основной вывод — сценарии и диапазоны; точечный процент не выводится. Интерфейс не вправе показать точность выше display_precision.') +
          App.card('Политика представления (серверная)', `<table class="tbl"><tr><th>Горизонт, лет</th><th>Режим</th><th>Точность</th><th>Класс неопределённости</th></tr>
            ${(f.presentation_policy || []).map(pp => `<tr><td>${pp.from}–${pp.to}</td><td>${App.statusTag(pp.mode)}</td>
              <td class="num">${pp.mode === 'SCENARIO' ? 'не выводится' : pp.precision}</td><td>${esc(pp.uncertainty)}</td></tr>`).join('')}</table>`) +
          App.card('Интервалы и метод', App.kv({
            'Метод': esc(((f.intervals || {})[target] || {}).method),
            'Середина кривой, лет': App.num(((f.intervals || {})[target] || {}).midpoint_years, 2),
            'Крутизна': App.num(((f.intervals || {})[target] || {}).steepness, 3),
            'Версия методики': esc(f.methodology_version)}));
      } else if (tab === 'scenarios') {
        box.innerHTML = App.card('Допущения', `<ul>${(f.assumptions || []).map(a => `<li class="tiny">${esc(a.text)} <span class="muted">[${esc(a.kind)}]</span></li>`).join('')}</ul>`) +
          ['optimistic', 'base', 'pessimistic'].map(n => App.card('Сценарий: ' + n, `
            <table class="tbl"><tr><th>Горизонт</th><th>Режим</th><th>Представление результата</th><th>Класс неопределённости</th><th>Предупреждение</th></tr>
            ${(sc[n] || []).map(p => { const pr = p.presentation || {}; return `<tr><td>${p.years_from}–${p.years_to} лет</td>
              <td>${App.statusTag(pr.mode || p.display_mode)}</td>
              <td>${esc(pr.display_text || '—')}</td>
              <td class="tiny">${esc(pr.uncertainty_class || '—')}</td>
              <td class="tiny muted">${esc(pr.warning_text || '')}</td></tr>`; }).join('')}</table>`)).join('');
      } else {
        const rows = [];
        targets.forEach(t => ['optimistic', 'base', 'pessimistic'].forEach(n => ((f.scenarios[t] || {})[n] || []).forEach(p => {
          const pr = p.presentation || {};
          rows.push({target: TARGET_RU[t] || t, scenario: n, horizon: p.years_from + '–' + p.years_to,
            mode: pr.mode, shown: pr.display_text, uncertainty: pr.uncertainty_class,
            low: pr.interval ? pr.interval[0] : null, high: pr.interval ? pr.interval[1] : null,
            qual: p.qualitative, warning: pr.warning_text});
        })));
        box.innerHTML = App.card('Все горизонты и сценарии', '<div id="fc-tbl"></div>');
        App.table('fc-tbl', {
          rows, size: 25, export: 'forecast',
          cols: [{k: 'target', t: 'Цель'}, {k: 'scenario', t: 'Сценарий'}, {k: 'horizon', t: 'Горизонт, лет'},
            {k: 'mode', t: 'Режим', r: r => App.statusTag(r.mode)},
            {k: 'shown', t: 'Представление (серверная политика)', r: r => esc(r.shown || '—')},
            {k: 'low', t: 'Нижняя, %', cls: 'num', r: r => App.num(r.low, 0)},
            {k: 'high', t: 'Верхняя, %', cls: 'num', r: r => App.num(r.high, 0)},
            {k: 'uncertainty', t: 'Неопределённость'},
            {k: 'warning', t: 'Предупреждение', r: r => esc(App.short(r.warning || '', 90))}],
        });
      }
      App.ctxObject('Прогноз', {'Целей': targets.length, 'Горизонтов': (f.horizons || []).length,
        'Монотонность': f.monotonic_ok ? 'соблюдена' : 'нарушена', 'Метод': esc(f.method),
        'Калибровка': esc(f.calibration_status || 'NOT_CALIBRATED')},
        '<div class="tiny muted" style="margin-top:8px">Калибровка прогноза не завершена: Brier score и покрытие интервалов требуют ретроспективной выборки (ТЗ-03 §8).</div>');
    },
  };

  // ============================================================ UI-21 Реестр источников
  Screens.sources = {
    title: 'Реестр источников', ui: 'UI-21', module: 'M03', group: 'Поиск и источники', right: 'registry.read',
    async render(host, params) {
      const stats = await App.get('/api/v1/sources/stats');
      const cats = Object.entries(stats.categories || {}).map(([code, name]) => ({code, name}));
      const q = {category: params.category, country: params.country, access: params.access,
        status: params.status, marker: params.marker, q: params.q, limit: 300, offset: +(params.offset || 0)};
      const d = await App.get('/api/v1/sources', q);
      host.innerHTML = `
        <div class="grid g4">
          ${App.kpi('Источников', stats.total, 'требование ТЗ: ≥ 300')}
          ${App.kpi('Категорий', (stats.by_category || []).length, 'C01–C12')}
          ${App.kpi('Открытых A0/A1', (stats.by_access || []).filter(a => ['A0', 'A1'].includes(a.access_class)).reduce((s, a) => s + a.n, 0), 'готовы к free-first')}
          ${App.kpi('Не проверено', (stats.by_access || []).filter(a => a.access_class === 'UNKNOWN').reduce((s, a) => s + a.n, 0), 'обязательная проверка перед PROD')}
        </div>
        ${App.card('Фильтры', `<div class="tbl-toolbar">
          <select id="s-cat"><option value="">все категории</option>${cats.map(c => `<option value="${esc(c.code)}" ${params.category === c.code ? 'selected' : ''}>${esc(c.code)} — ${esc(c.name)}</option>`).join('')}</select>
          <select id="s-acc"><option value="">любой доступ</option>${['A0', 'A1', 'A2', 'A3', 'A4', 'UNKNOWN'].map(a => `<option ${params.access === a ? 'selected' : ''}>${a}</option>`).join('')}</select>
          <select id="s-st"><option value="">любой статус</option>${['CANDIDATE', 'TESTED', 'CONNECTED', 'RESTRICTED', 'UNAVAILABLE'].map(a => `<option ${params.status === a ? 'selected' : ''}>${a}</option>`).join('')}</select>
          <select id="s-mk"><option value="">любой маркер</option>${['П', 'Р', 'Д'].map(a => `<option ${params.marker === a ? 'selected' : ''}>${a}</option>`).join('')}</select>
          <input type="text" id="s-co" placeholder="страна ISO2" value="${esc(params.country || '')}" style="width:110px">
          <input type="search" id="s-q" placeholder="поиск по названию/назначению" value="${esc(params.q || '')}" style="max-width:240px">
          <button class="btn sm primary" id="s-apply">Применить</button>
          <span class="tiny muted">найдено: ${d.total}</span></div>`)}
        ${App.card('Источники', '<div id="src-tbl"></div>')}
        <div class="grid g2">
          ${App.card('По категориям', Charts.bar((stats.by_category || []).map(c => ({label: c.category, value: c.n})), {unit: 'источников'}))}
          ${App.card('По классам доступа', Charts.bar((stats.by_access || []).map(c => ({label: c.access_class, value: c.n})), {unit: 'источников'}))}
        </div>
        ${App.card('Реестр коннекторов', '<div id="con-tbl"></div>', App.can('registry.write') ? '<button class="btn sm" id="con-check">Проверить все</button>' : '')}`;
      const apply = () => App.go('sources', {category: document.getElementById('s-cat').value, access: document.getElementById('s-acc').value,
        status: document.getElementById('s-st').value, marker: document.getElementById('s-mk').value,
        country: document.getElementById('s-co').value, q: document.getElementById('s-q').value});
      document.getElementById('s-apply').addEventListener('click', apply);
      document.getElementById('s-q').addEventListener('keydown', e => { if (e.key === 'Enter') apply(); });
      App.table('src-tbl', {
        rows: d.items, size: 25, export: 'sources',
        cols: [{k: 'code', t: 'Код'}, {k: 'name', t: 'Источник', r: s => `<b>${esc(s.name)}</b>`},
          {k: 'category', t: 'Кат.', r: s => esc(s.category)},
          {k: 'country_code', t: 'Страна'}, {k: 'access_class', t: 'Доступ', r: s => App.tag(s.access_class, s.access_class === 'A0' ? 'ok' : s.access_class === 'UNKNOWN' ? 'warn' : '')},
          {k: 'evidence_marker', t: 'Маркер'}, {k: 'integration_status', t: 'Статус', r: s => App.statusTag(s.integration_status)},
          {k: 'priority', t: 'Очередь'}, {k: 'api_type', t: 'API'},
          {k: 'connector_code', t: 'Коннектор', r: s => esc(s.connector_code || '—')},
          {k: 'last_verified_at', t: 'Проверен', r: s => App.donly(s.last_verified_at)}],
        onRow: s => App.modal(s.name + ' · ' + s.code, `
          ${App.kv({'Код': esc(s.code), 'Категория': esc(s.category + ' — ' + (s.category_name || '')),
            'Страна/охват': esc((s.country_code || 'международный') + ' / ' + (s.scope || '')),
            'Тип API': esc(s.api_type || '—'), 'Формат ответа': esc(s.response_format || '—'),
            'Класс доступа': esc(s.access_class) + ' — ' + esc(s.access_reason || ''),
            'Аутентификация': esc(s.auth_type || '—'), 'Маркер доказательности': esc(s.evidence_marker) + ' — ' + esc(s.marker_reason || ''),
            'Статус интеграции': App.statusTag(s.integration_status), 'Приоритет очереди': esc(s.priority || '—'),
            'Коннектор': esc(s.connector_code || 'нет'), 'Лицензия': esc(s.license || 'не указана'),
            'Раздел перечня': esc(s.registry_section || '—'),
            'Последняя проверка': App.donly(s.last_verified_at), 'Последний успех': App.donly(s.last_success_at),
            'HTTP': s.last_http_status ?? '—'})}
          <b class="tiny muted">Назначение</b><div class="tiny">${esc(s.purpose || '—')}</div>
          <b class="tiny muted">Эндпоинты</b><div class="tiny">${(s.endpoints || []).map(u => `<div><code>${esc(u)}</code></div>`).join('') || '—'}</div>
          <b class="tiny muted">Лимиты (из перечня, не зашиты в код)</b><pre class="tiny">${esc(JSON.stringify(s.limits || {}, null, 1))}</pre>
          <b class="tiny muted">Здоровье</b><pre class="tiny">${esc(JSON.stringify(s.health || {}, null, 1))}</pre>`),
      });
      const con = await App.get('/api/v1/connectors');
      App.table('con-tbl', {
        rows: con.items, size: 30, export: 'connectors',
        cols: [{k: 'code', t: 'Код'}, {k: 'name', t: 'Коннектор'}, {k: 'source_code', t: 'Источник'},
          {k: 'protocol', t: 'Протокол'}, {k: 'implementation', t: 'Реализация', r: c => App.tag(c.implementation, c.implementation === 'live' ? 'ok' : 'warn')},
          {k: 'requires_key', t: 'Ключ', r: c => c.requires_key ? (c.key_configured ? App.tag('задан', 'ok') : App.tag('требуется', 'warn')) : App.tag('не нужен', 'ok')},
          {k: 'health_status', t: 'Здоровье', r: c => App.statusTag(c.health_status)},
          {k: 'robots_policy', t: 'robots', r: c => esc(c.robots_policy || 'strict')},
          {k: 'limits', t: 'Лимиты', r: c => esc(App.short(JSON.stringify(c.limits || {}), 70))},
          {k: 'last_error', t: 'Ошибка', r: c => esc(App.short(c.last_error || '—', 60))}],
        onRow: c => App.ctxObject('Коннектор ' + c.code, {'Источник': esc(c.source_code), 'Базовый URL': esc(c.base_url),
          'Аутентификация': esc(c.auth_type), 'Политика robots': esc(c.robots_policy),
          'Документация': c.docs_url ? `<a href="${esc(c.docs_url)}" target="_blank">открыть ↗</a>` : '—',
          'Условия': c.tos_url ? `<a href="${esc(c.tos_url)}" target="_blank">открыть ↗</a>` : '—',
          'Резервный': esc(c.fallback_code || 'нет'), 'Заметки': esc(App.short(c.notes || '', 200))}),
      });
      document.getElementById('con-check')?.addEventListener('click', async e => {
        e.target.disabled = true; e.target.textContent = 'Проверка…';
        try { const r = await App.post('/api/v1/connectors/check', {}); App.toast('Проверено коннекторов: ' + r.items.length, 'ok'); App.render(); }
        catch (err) { App.toast(esc(err.message), 'error'); e.target.disabled = false; e.target.textContent = 'Проверить все'; }
      });
    },
  };

  // ============================================================ UI-22 Профили стран
  Screens.countries = {
    title: 'Профили стран и покрытие', ui: 'UI-22', module: 'M04', group: 'Поиск и источники', right: 'registry.read',
    async render(host) {
      const d = await App.get('/api/v1/countries');
      const cs = d.items || [];
      App.S.countries = cs;
      let coverage = [];
      if (App.S.researchId) {
        try { coverage = (await App.get(`/api/v1/analytics/${App.S.researchId}`)).coverage || []; } catch (e) { /* нет исследования */ }
      }
      const enabled = cs.filter(c => c.is_enabled).length;
      host.innerHTML = `
        <div class="grid g4">
          ${App.kpi('Стран в реестре', cs.length, 'требование ТЗ: 35 государств')}
          ${App.kpi('Включено', enabled, 'участвуют в поиске по умолчанию')}
          ${App.kpi('Национальных источников', cs.reduce((s, c) => s + c.sources, 0), 'привязано к странам')}
          ${App.kpi('Пробелов покрытия', coverage.filter(c => c.gap).length, 'стран без найденных документов')}
        </div>
        ${App.card('Управление охватом', `<div class="row">
          <button class="btn primary" id="all-countries">${enabled === cs.length ? 'Снять выбор со всех стран' : 'Выбрать все страны'}</button>
          <span class="tiny muted">Кнопка включает весь список доступных стран; повторное нажатие снимает выбор.</span></div>`)}
        ${App.card('Профили стран', '<div id="ct-tbl"></div>')}
        ${coverage.length ? App.card('Карта покрытия (heatmap)', Charts.heatmap(coverage)) : ''}
        ${coverage.length ? App.card('Карта пробелов', `<div class="row">${coverage.filter(c => c.gap).map(c => App.tag(c.iso2 + ' ' + c.name_ru, 'warn')).join(' ') || App.tag('пробелов нет', 'ok')}</div>
          ${App.alert('info', 'Страна с нулём документов попадает в «Карту пробелов»: это ограничение охвата источников, а не отсутствие научно-технической деятельности.')}`) : ''}`;
      App.table('ct-tbl', {
        rows: cs, size: 40, export: 'countries', sort: 'sources',
        cols: [{k: 'code', t: 'ISO2'}, {k: 'name_ru', t: 'Страна'}, {k: 'region', t: 'Регион'},
          {k: 'patent_office', t: 'Патентное ведомство'},
          {k: 'languages', t: 'Языки', r: c => esc((c.languages || []).join(', '))},
          {k: 'sources', t: 'Источников', cls: 'num'},
          {k: 'is_enabled', t: 'Включена', r: c => c.is_enabled ? App.tag('да', 'ok') : App.tag('нет', 'warn')},
          {k: 'act', t: 'Действие', r: c => App.can('registry.write') ? `<button class="btn sm" data-toggle="${esc(c.code)}" data-on="${c.is_enabled ? 0 : 1}">${c.is_enabled ? 'Отключить' : 'Включить'}</button>` : '—'}],
        after: el => el.querySelectorAll('[data-toggle]').forEach(b => b.addEventListener('click', async () => {
          await App.post(`/api/v1/countries/${b.dataset.toggle}/toggle`, {enabled: b.dataset.on === '1'}); App.render();
        })),
        onRow: c => App.ctxObject(c.name_ru, {'ISO2': esc(c.code), 'Регион': esc(c.region),
          'Патентное ведомство': esc(c.patent_office || '—'), 'Языки': esc((c.languages || []).join(', ')),
          'Источников': c.sources, 'Профиль': esc(JSON.stringify(c.profile || {}))}),
      });
      document.getElementById('all-countries').addEventListener('click', async e => {
        const target = enabled !== cs.length;
        e.target.disabled = true; e.target.textContent = 'Обновление…';
        try {
          for (const c of cs) if (!!c.is_enabled !== target) await App.post(`/api/v1/countries/${c.code}/toggle`, {enabled: target});
          App.toast(target ? 'Включены все страны (' + cs.length + ')' : 'Все страны отключены', 'ok');
        } catch (err) { App.toast(esc(err.message), 'error'); }
        App.render();
      });
    },
  };

  // ============================================================ UI-23 Мониторинг
  Screens.monitor = {
    title: 'Мониторинг заданий и источников', ui: 'UI-23', module: 'M30', group: 'Администрирование', right: 'research.read',
    async render(body, params) {
      const rid = params.rid || App.S.researchId;
      const [sys, con, prov] = await Promise.all([App.get('/api/v1/system'), App.get('/api/v1/connectors'), App.get('/api/v1/ai/providers')]);
      let st = null;
      if (rid) { try { st = await App.get(`/api/v1/researches/${rid}/status`); } catch (e) { st = null; } }
      const jobs = st ? st.jobs : [];
      const done = jobs.filter(j => j.status === 'completed').length;
      const failed = jobs.filter(j => j.status === 'failed').length;
      body.innerHTML = `
        <div class="grid g4">
          ${App.kpi('Этапов завершено', done + '/' + (jobs.length || 12), st ? 'исследование ' + esc(App.short(st.research.title, 30)) : 'исследование не выбрано')}
          ${App.kpi('Ошибок', failed, 'задания со статусом failed')}
          ${App.kpi('Коннекторов активно', con.items.filter(c => c.health_status === 'active').length + '/' + con.items.length, 'проверка здоровья')}
          ${App.kpi('Провайдеров активно', prov.items.filter(p => p.status === 'active').length + '/' + prov.items.length, 'статусы ИИ')}
        </div>
        ${App.card('Этапы исследования', rid ? '<div id="m-jobs"></div>' : App.empty('Выберите исследование в базе исследований', '📡'),
          rid && App.can('research.run') ? `<button class="btn sm primary" id="m-run">▶ Запустить</button><button class="btn sm" id="m-resume">⟳ Продолжить</button><button class="btn sm danger" id="m-cancel">■ Отменить</button>` : '')}
        ${App.card('Задания поиска по источникам', st && st.search_jobs.length ? '<div id="m-search"></div>' : App.empty('Заданий поиска нет', '🔎'))}
        <div class="grid g2">
          ${App.card('Квоты и лимиты (фактические)', '<div id="m-quota"></div>')}
          ${App.card('Здоровье коннекторов', '<div id="m-con"></div>', App.can('registry.write') ? '<button class="btn sm" id="m-check">Проверить</button>' : '')}
        </div>
        ${App.card('Живая лента событий (SSE)', '<div id="m-events">' + App.empty('Ожидание событий…', '📡') + '</div>')}`;
      if (rid) {
        App.table('m-jobs', {
          rows: jobs, size: 12, search: false, export: 'jobs',
          cols: [{k: 'name', t: 'Этап'}, {k: 'status', t: 'Статус', r: j => App.statusTag(j.status)},
            {k: 'progress', t: 'Прогресс', r: j => `<div class="progress" style="min-width:80px"><i style="width:${Math.round((j.progress || 0) * 100)}%"></i></div>`},
            {k: 'processed', t: 'Обработано', cls: 'num', r: j => `${j.processed || 0}/${j.total || 0}`},
            {k: 'attempts', t: 'Попыток', cls: 'num'},
            {k: 'error_code', t: 'Ошибка', r: j => j.error_code ? App.tag(j.error_code, 'err') : '—'},
            {k: 'error_message', t: 'Сообщение', r: j => esc(App.short(j.error_message || '', 80))}],
        });
        document.getElementById('m-run')?.addEventListener('click', () => App.runResearch(false));
        document.getElementById('m-resume')?.addEventListener('click', () => App.runResearch(true));
        document.getElementById('m-cancel')?.addEventListener('click', async () => { await App.post(`/api/v1/researches/${rid}/cancel`); App.render(); });
      }
      if (st && st.search_jobs.length) App.table('m-search', {
        rows: st.search_jobs, size: 15, export: 'search_jobs',
        cols: [{k: 'connector_code', t: 'Коннектор'}, {k: 'source_code', t: 'Источник'},
          {k: 'branch', t: 'Ветвь'}, {k: 'status', t: 'Статус', r: j => App.statusTag(j.status)},
          {k: 'found_count', t: 'Найдено', cls: 'num'}, {k: 'attempts', t: 'Попыток', cls: 'num'},
          {k: 'error_code', t: 'Ошибка', r: j => j.error_code ? App.tag(j.error_code, 'err') : '—'},
          {k: 'error_message', t: 'Причина', r: j => esc(App.short(j.error_message || '', 70))}],
      });
      App.table('m-quota', {
        rows: sys.quota || [], size: 12, export: 'quota',
        cols: [{k: 'scope', t: 'Область'}, {k: 'key', t: 'Ключ'}, {k: 'window', t: 'Окно'},
          {k: 'used', t: 'Использовано', cls: 'num'},
          {k: 'limit', t: 'Лимит', cls: 'num', r: r => r.limit == null ? 'неизвестно' : r.limit},
          {k: 'updated_at', t: 'Обновлено', r: r => App.dt(r.updated_at)}],
        empty: 'Обращений к внешним API ещё не было',
      });
      App.table('m-con', {
        rows: con.items, size: 12, export: 'connectors_health',
        cols: [{k: 'code', t: 'Коннектор'}, {k: 'health_status', t: 'Статус', r: c => App.statusTag(c.health_status)},
          {k: 'last_checked_at', t: 'Проверен', r: c => App.dt(c.last_checked_at)},
          {k: 'last_error', t: 'Причина', r: c => esc(App.short(c.last_error || '—', 60))}],
      });
      document.getElementById('m-check')?.addEventListener('click', async e => {
        e.target.disabled = true; e.target.textContent = 'Проверка…';
        try { await App.post('/api/v1/connectors/check', {}); App.toast('Проверка завершена', 'ok'); App.render(); }
        catch (err) { App.toast(esc(err.message), 'error'); }
      });
      const hist = await App.get('/api/v1/events', {research_id: rid, limit: 25});
      // Лента пишет через App.setHTML: узел ищется в момент записи, а не до
      // ожидания запроса — иначе после смены экрана получаем null.innerHTML.
      const render = items => App.setHTML('m-events', items.slice(0, 40).map(e => `<div class="evidence-item">
        <b>${esc(e.event_type)}</b> <span class="tiny muted">${App.dt(e.created_at)} · ${esc(e.severity)}</span>
        <div class="tiny">${esc(App.short(JSON.stringify(e.payload || {}), 200))}</div></div>`).join('') || App.empty('Событий нет', '📡'));
      let items = hist.items || [];
      render(items);
      const onEv = ev => { items.unshift(ev.detail); render(items); };
      window.addEventListener('isheika:event', onEv);
      // Слушатель снимается при ЛЮБОЙ перерисовке, а не только при смене маршрута:
      // иначе он переживал обновление экрана и писал в отсутствующий узел.
      App.onCleanup(() => window.removeEventListener('isheika:event', onEv));
      window.addEventListener('hashchange', () => window.removeEventListener('isheika:event', onEv), {once: true});
      App.ctxObject('Система', {'Профиль': esc(sys.profile), 'Методика': esc(sys.methodology_version),
        'Событий в журнале': sys.counters.events, 'Время сервера': App.dt(sys.server_time)});
    },
  };

  // ============================================================ UI-24 Журнал работы
  Screens.logs = {
    title: 'Подробный журнал работы', ui: 'UI-24', module: 'M30', group: 'Администрирование', right: 'logs.read',
    async render(host, params) {
      const kind = params.kind || 'all';
      const rid = params.scope === 'research' ? App.S.researchId : '';
      if (params.cid) {                                   // P6: сквозная трассировка запроса/запуска
        const t = await App.get('/api/v1/trace/' + encodeURIComponent(params.cid));
        host.innerHTML = App.alert('info', 'Трассировка связывает запрос → задание → этап → источник → расчёт. Идентификатор: <code>' + esc(t.correlation_id) + '</code>') +
          App.card('Сводка', App.kv({'Событий': (t.events || []).length, 'Вызовов API': (t.api_calls || []).length,
            'Записей аудита': (t.audit || []).length, 'Этапов': (t.jobs || []).length,
            'Исследования': (t.research_ids || []).map(x => `<a href="#/research/${esc(x)}">${esc(String(x).slice(0, 14))}</a>`).join(', ') || '—'})) +
          App.card('Этапы', (t.jobs || []).length ? '<div id="tr-jobs"></div>' : App.empty('Этапы не запускались', '🧭')) +
          App.card('События', (t.events || []).length ? '<div id="tr-ev"></div>' : App.empty('Событий нет', '📭')) +
          App.card('Вызовы внешних API', (t.api_calls || []).length ? '<div id="tr-api"></div>' : App.empty('Вызовов не было', '🔌')) +
          '<div class="row"><a class="btn sm" href="#/logs">← Весь журнал</a></div>';
        if ((t.jobs || []).length) App.table('tr-jobs', {rows: t.jobs, size: 20, search: false, export: 'trace_jobs',
          cols: [{k: 'stage', t: 'Этап'}, {k: 'status', t: 'Статус', r: r => App.statusTag(r.status)},
            {k: 'duration_ms', t: 'Длительность, мс', cls: 'num'},
            {k: 'started_at', t: 'Начало', r: r => App.dt(r.started_at)}, {k: 'finished_at', t: 'Завершение', r: r => App.dt(r.finished_at)}]});
        if ((t.events || []).length) App.table('tr-ev', {rows: t.events, size: 25, search: false, export: 'trace_events',
          cols: [{k: 'created_at', t: 'Время', r: r => App.dt(r.created_at)}, {k: 'event_type', t: 'Событие'},
            {k: 'severity', t: 'Важность', r: r => App.tag(r.severity, r.severity === 'error' ? 'err' : '')},
            {k: 'job_id', t: 'task_id', r: r => esc(r.job_id || '—')}]});
        if ((t.api_calls || []).length) App.table('tr-api', {rows: t.api_calls, size: 25, search: false, export: 'trace_api',
          cols: [{k: 'created_at', t: 'Время', r: r => App.dt(r.created_at)}, {k: 'target', t: 'Источник'},
            {k: 'http_status', t: 'HTTP', cls: 'num'}, {k: 'duration_ms', t: 'мс', cls: 'num'},
            {k: 'cached', t: 'Кэш', r: r => r.cached ? App.tag('из кэша', 'ok') : 'сеть'}]});
        return;
      }
      const d = await App.get('/api/v1/logs', {research_id: rid, kind, limit: 400});
      host.innerHTML = `
        ${App.card('Фильтры и выгрузка', `<div class="row">
          <select id="l-kind">${[['all', 'Все разделы'], ['events', 'События'], ['audit', 'Аудит действий'], ['api', 'Вызовы API'], ['states', 'История состояний']].map(([k, n]) => `<option value="${k}" ${kind === k ? 'selected' : ''}>${n}</option>`).join('')}</select>
          <select id="l-scope"><option value="all" ${rid ? '' : 'selected'}>Вся система</option><option value="research" ${rid ? 'selected' : ''}>Только текущее исследование</option></select>
          <a class="btn sm" href="${App.fileURL('/api/v1/logs/export', {research_id: rid, fmt: 'txt'})}">Экспорт TXT</a>
          <a class="btn sm" href="${App.fileURL('/api/v1/logs/export', {research_id: rid, fmt: 'json'})}">Экспорт JSON</a>
          <a class="btn sm" href="${App.fileURL('/api/v1/logs/export', {research_id: rid, fmt: 'csv'})}">Экспорт CSV</a>
        </div>`)}
        ${d.events ? App.card('События (' + d.events.length + ')', '<div id="l-ev"></div>') : ''}
        ${d.audit ? App.card('Аудит действий (' + d.audit.length + ')', '<div id="l-au"></div>') : ''}
        ${d.api_calls ? App.card('Вызовы внешних API (' + d.api_calls.length + ')', '<div id="l-api"></div>') : ''}
        ${d.state_history ? App.card('История состояний (' + d.state_history.length + ')', '<div id="l-st"></div>') : ''}`;
      const reload = () => App.go('logs', {kind: document.getElementById('l-kind').value, scope: document.getElementById('l-scope').value});
      document.getElementById('l-kind').addEventListener('change', reload);
      document.getElementById('l-scope').addEventListener('change', reload);
      if (d.events) App.table('l-ev', {
        rows: d.events, size: 25, export: 'events', sort: 'created_at',
        cols: [{k: 'created_at', t: 'Время', r: e => App.dt(e.created_at)}, {k: 'event_type', t: 'Событие'},
          {k: 'severity', t: 'Важность', r: e => App.tag(e.severity, e.severity === 'error' ? 'err' : e.severity === 'warning' ? 'warn' : '')},
          {k: 'research_id', t: 'Исследование', r: e => e.research_id ? `<a href="#/research/${esc(e.research_id)}">${esc(String(e.research_id).slice(0, 12))}</a>` : '—'},
          {k: 'job_id', t: 'task_id', r: e => esc(e.job_id || '—')},
          {k: 'correlation_id', t: 'Трассировка', r: e => e.correlation_id ? `<a href="#/logs?cid=${esc(e.correlation_id)}" title="Открыть сквозную трассировку"><code>${esc(String(e.correlation_id).slice(0, 14))}</code></a>` : '—'},
          {k: 'payload', t: 'Данные', r: e => `<span class="tiny">${esc(App.short(JSON.stringify(e.payload || {}), 150))}</span>`}],
      });
      if (d.audit) App.table('l-au', {
        rows: d.audit, size: 25, export: 'audit', sort: 'created_at',
        cols: [{k: 'created_at', t: 'Время', r: e => App.dt(e.created_at)}, {k: 'actor', t: 'Пользователь'},
          {k: 'action', t: 'Действие'}, {k: 'entity_kind', t: 'Объект'}, {k: 'entity_id', t: 'ID'},
          {k: 'payload', t: 'Данные', r: e => `<span class="tiny">${esc(App.short(JSON.stringify(e.payload || {}), 130))}</span>`}],
      });
      if (d.api_calls) App.table('l-api', {
        rows: d.api_calls, size: 25, export: 'api_calls', sort: 'created_at',
        cols: [{k: 'created_at', t: 'Время', r: e => App.dt(e.created_at)}, {k: 'kind', t: 'Тип'},
          {k: 'target', t: 'Источник/URL', r: e => esc(App.short(e.target || e.url || '', 60))},
          {k: 'http_status', t: 'HTTP', cls: 'num'}, {k: 'duration_ms', t: 'мс', cls: 'num'},
          {k: 'bytes', t: 'Байт', cls: 'num'},
          {k: 'cached', t: 'Кэш', r: e => e.cached ? App.tag('из кэша', 'ok') : 'сеть'},
          {k: 'error_code', t: 'Ошибка', r: e => e.error_code ? App.tag(e.error_code, 'err') : '—'}],
        empty: 'Вызовов внешних API не зафиксировано',
      });
      if (d.state_history) App.table('l-st', {
        rows: d.state_history, size: 25, export: 'states', sort: 'created_at',
        cols: [{k: 'created_at', t: 'Время', r: e => App.dt(e.created_at)}, {k: 'entity_kind', t: 'Тип'},
          {k: 'entity_id', t: 'Объект', r: e => esc(String(e.entity_id).slice(0, 20))},
          {k: 'from_state', t: 'Из', r: e => esc(e.from_state || '—')}, {k: 'to_state', t: 'В', r: e => App.statusTag(e.to_state)},
          {k: 'reason', t: 'Причина'}, {k: 'actor', t: 'Инициатор'}],
      });
    },
  };

  // ============================================================ UI-25 Настройки
  Screens.settings = {
    title: 'Настройки системы и ключи', ui: 'UI-25', module: 'M31', group: 'Администрирование', right: 'settings.read',
    async render(body, params) {
      const tab = params.tab || 'general';
      const [s, secrets, users] = await Promise.all([
        App.get('/api/v1/settings'), App.get('/api/v1/settings/secrets'),
        App.can('settings.read') ? App.get('/api/v1/users').catch(() => ({items: []})) : Promise.resolve({items: []})]);
      body.innerHTML = tabsHTML('settings', [{k: 'general', t: 'Политики и лимиты'}, {k: 'keys', t: 'Ключи API'}, {k: 'users', t: 'Пользователи и роли'}], tab) + '<div id="st-box"></div>';
      const box = document.getElementById('st-box');
      const writable = App.can('keys.write');
      if (tab === 'keys') {
        box.innerHTML = App.card('Ключи доступа (хранятся только на сервере, шифруются)', `
          <div id="sec-tbl"></div>
          ${writable ? `<div class="grid g3" style="margin-top:10px">
            <label class="fld"><span>Ссылка (secret_ref)</span><input type="text" id="sec-ref" placeholder="например: openalex_key"></label>
            <label class="fld"><span>Тип</span><select id="sec-kind"><option value="api_key">api_key</option><option value="oauth_client">oauth_client</option><option value="token">token</option></select></label>
            <label class="fld"><span>Значение</span><input type="password" id="sec-val" autocomplete="new-password"></label>
          </div><button class="btn primary" id="sec-save">Сохранить ключ</button>
          <span class="tiny muted">Значение не возвращается в браузер ни полностью, ни частично (кроме маски).</span>` : App.alert('warn', 'Изменение ключей доступно ролям администратор и руководитель исследования.')}`) +
          App.alert('info', 'Ключи не покидают сервер: UI получает только признак наличия и маску. Передача ключей в браузер, логи и отчёты запрещена.');
        App.table('sec-tbl', {
          rows: secrets.items || [], size: 20, export: 'secrets',
          cols: [{k: 'ref', t: 'Ссылка'}, {k: 'kind', t: 'Тип'}, {k: 'hint', t: 'Маска'},
            {k: 'created_at', t: 'Создан', r: x => App.dt(x.created_at)},
            {k: 'act', t: 'Действие', r: x => writable ? `<button class="btn sm danger" data-del="${esc(x.ref)}">Удалить</button>` : '—'}],
          empty: 'Ключи не заданы. Без ключей работают только источники класса A0.',
          after: el => el.querySelectorAll('[data-del]').forEach(b => b.addEventListener('click', async () => {
            await App.del('/api/v1/settings/secrets/' + encodeURIComponent(b.dataset.del)); App.toast('Ключ удалён', 'warn'); App.render();
          })),
        });
        document.getElementById('sec-save')?.addEventListener('click', async () => {
          const ref = document.getElementById('sec-ref').value.trim(), value = document.getElementById('sec-val').value;
          if (!ref || !value) { App.toast('Заполните ссылку и значение', 'warn'); return; }
          try { await App.post('/api/v1/settings/secrets', {ref, value, kind: document.getElementById('sec-kind').value}); App.toast('Ключ сохранён в зашифрованном хранилище', 'ok'); App.render(); }
          catch (e) { App.toast(esc(e.message), 'error'); }
        });
        return;
      }
      if (tab === 'users') {
        box.innerHTML = App.card('Пользователи', '<div id="u-tbl"></div>') +
          App.card('Роли и права (RBAC)', `<table class="tbl"><tr><th>Роль</th><th>Назначение</th></tr>
            <tr><td>admin</td><td>Полный доступ, ключи, настройки, реестры</td></tr>
            <tr><td>research_lead</td><td>Постановка исследований, запуск, отчёты, реестры, ключи</td></tr>
            <tr><td>analyst</td><td>Исследования, аналитика, доказательства, отчёты</td></tr>
            <tr><td>expert</td><td>Экспертная разметка и подтверждения доказательств</td></tr>
            <tr><td>observer</td><td>Только чтение результатов</td></tr>
            <tr><td>auditor</td><td>Чтение журнала, аудита и настроек</td></tr></table>`);
        App.table('u-tbl', {
          rows: users.items || [], size: 20, export: 'users',
          cols: [{k: 'login', t: 'Логин'}, {k: 'display_name', t: 'Имя'}, {k: 'role', t: 'Роль'},
            {k: 'is_active', t: 'Активен', r: u => u.is_active ? App.tag('да', 'ok') : App.tag('нет', 'warn')}],
          empty: 'Список пользователей недоступен для вашей роли',
        });
        return;
      }
      const flags = [['allow_paid_ai', 'Разрешить платные вызовы ИИ (по умолчанию выключено)'],
        ['allow_external_ai', 'Разрешить передачу данных внешним провайдерам'],
        ['network_enabled', 'Разрешить сетевые обращения к источникам'],
        ['respect_robots', 'Соблюдать robots.txt (кроме документированных API)']];
      box.innerHTML = `
        ${App.card('Политики', flags.map(([k, n]) => `<label class="fld row"><input type="checkbox" data-flag="${k}" ${s[k] ? 'checked' : ''} ${writable ? '' : 'disabled'} style="width:auto"> <span>${n}</span></label>`).join('') +
          `${s.profile === 'DEV' ? App.alert('warn', 'Профиль DEV: платные вызовы запрещены на уровне конфигурации независимо от переключателя.') : ''}
          ${App.alert('info', 'Платные вызовы требуют явного согласия: бюджет, лимит на вызов, период и журнал расходов. Без согласия провайдер получает статус paid_blocked.')}`)}
        ${App.card('Лимиты и режимы', `<div class="grid g3">
          <label class="fld"><span>Режим ИИ</span><select data-val="ai_mode" ${writable ? '' : 'disabled'}>${['auto', 'simulation', 'live'].map(v => `<option ${s.ai_mode === v ? 'selected' : ''}>${v}</option>`).join('')}</select></label>
          <label class="fld"><span>Максимальный класс приватности</span><select data-val="privacy_class_max" ${writable ? '' : 'disabled'}>${['public', 'internal', 'restricted'].map(v => `<option ${s.privacy_class_max === v ? 'selected' : ''}>${v}</option>`).join('')}</select></label>
          <label class="fld"><span>E-mail для polite pool (Crossref/Unpaywall)</span><input type="text" data-val="contact_email" value="${esc(s.contact_email || '')}" ${writable ? '' : 'disabled'}></label>
          <label class="fld"><span>Документов на источник</span><input type="number" data-val="max_docs_per_source" value="${s.max_docs_per_source}" ${writable ? '' : 'disabled'}></label>
          <label class="fld"><span>Параллельных загрузок</span><input type="number" data-val="max_parallel_fetch" value="${s.max_parallel_fetch}" ${writable ? '' : 'disabled'}></label>
          <label class="fld"><span>Таймаут HTTP, с</span><input type="number" step="0.5" data-val="http_timeout" value="${s.http_timeout}" ${writable ? '' : 'disabled'}></label>
        </div>${writable ? '<button class="btn primary" id="set-save">Сохранить настройки</button>' : ''}`)}
        ${App.card('Профиль развёртывания', App.kv({
          'Профиль': esc(s.profile), 'Версия методики': esc(s.methodology_version),
          'Порог прямого соответствия': s.relevance_direct, 'Порог смежного': s.relevance_adjacent,
          'Хранилище секретов': s.secrets_configured ? 'инициализировано' : 'не создано',
          'User-Agent': esc(s.user_agent)}))}
        ${App.card('Тема интерфейса', `<div class="row"><button class="btn" onclick="App.setTheme('light');App.render()">Светлая</button>
          <button class="btn" onclick="App.setTheme('dark');App.render()">Тёмная</button>
          <span class="tiny muted">Выбор сохраняется в браузере; цвет не является единственным носителем смысла.</span></div>`)}`;
      document.getElementById('set-save')?.addEventListener('click', async () => {
        const payload = {};
        box.querySelectorAll('[data-flag]').forEach(i => payload[i.dataset.flag] = i.checked);
        box.querySelectorAll('[data-val]').forEach(i => payload[i.dataset.val] = i.type === 'number' ? +i.value : i.value);
        try { const r = await App.post('/api/v1/settings', payload); App.toast('Сохранено параметров: ' + Object.keys(r.changed).length, 'ok'); await App.refreshSystem(); App.render(); }
        catch (e) { App.toast(esc(e.message), 'error'); }
      });
    },
  };

  // ============================================================ UI-26 Контроль качества
  Screens.quality = {
    title: 'Контроль качества и калибровка', ui: 'UI-26', module: 'M32', group: 'Администрирование', right: 'analytics.read',
    async render(body) {
      const host = await scaffold(body); if (!host) return;
      const rid = App.S.researchId;
      const [an, meth] = await Promise.all([App.get(`/api/v1/analytics/${rid}`), App.get('/api/v1/methodology')]);
      const q = an.quality || {};
      const dist = q.distribution || {};
      const targets = meth.validation_targets || {};
      const metricRow = (name, value, target, n, calibrated) => `<tr><td>${esc(name)}</td>
        <td class="num">${value == null ? App.tag('нет данных', 'warn') : App.num(value, 3)}</td>
        <td class="num">${esc(target)}</td><td class="num">${n ?? 0}</td>
        <td>${calibrated ? App.tag('выборка достаточна', 'ok') : App.tag('калибровка не завершена', 'warn')}</td></tr>`;
      host.innerHTML = `
        ${App.alert('warn', 'Статус методик: <b>' + esc(meth.status || 'калибровка не завершена') + '</b>. Все веса и пороги стартовые (ТЗ-03); до подтверждения на размеченной выборке метрики приводятся со статусом «калибровка не завершена».')}
        <div class="grid g4">
          ${App.kpi('DIRECT', dist.DIRECT ?? dist.direct ?? 0, 'R ≥ 0,80')}
          ${App.kpi('ADJACENT', dist.ADJACENT ?? dist.adjacent ?? 0, '0,60 ≤ R &lt; 0,80')}
          ${App.kpi('BELOW_THRESHOLD', dist.BELOW_THRESHOLD ?? dist.excluded ?? 0, 'R &lt; 0,60')}
          ${App.kpi('Прямых в топ-10', dist.top10_direct ?? 0, 'индикатор «мусора» в выдаче')}
        </div>
        ${App.card('Метрики поиска', `<table class="tbl"><tr><th>Метрика</th><th>Значение</th><th>Цель ТЗ-03</th><th>Выборка</th><th>Статус</th></tr>
          ${metricRow('Precision@10', (q.search || {}).precision_at_10, '≥ ' + targets.search.precision_at_10, (q.search || {}).n, (q.search || {}).calibrated)}
          ${metricRow('nDCG@10', (q.search || {}).ndcg_at_10, '≥ ' + targets.search.ndcg_at_10, (q.search || {}).n, (q.search || {}).calibrated)}
          ${metricRow('Precision@5', (q.search || {}).precision_at_5, '—', (q.search || {}).n, (q.search || {}).calibrated)}
          </table>${(q.search || {}).reason ? App.alert('info', esc(q.search.reason) + ' Разметка выполняется экспертом в карточках результатов (UI-04, кнопки 0/1/2).') : ''}`)}
        ${App.card('Метрики TRL и прогноза', `<table class="tbl"><tr><th>Метрика</th><th>Значение</th><th>Цель ТЗ-03</th><th>Выборка</th><th>Статус</th></tr>
          ${metricRow('TRL MAE (уровни)', (q.trl || {}).mae, '≤ ' + targets.trl.mae_levels, (q.trl || {}).n, (q.trl || {}).calibrated)}
          ${metricRow('Weighted kappa', (q.trl || {}).weighted_kappa, '≥ ' + targets.trl.weighted_kappa, (q.trl || {}).n, (q.trl || {}).calibrated)}
          ${metricRow('Brier score', (q.forecast || {}).brier, '≤ ' + targets.forecast.brier_score, (q.forecast || {}).n, (q.forecast || {}).calibrated)}
          ${metricRow('Покрытие 90 % интервалов', (q.forecast || {}).interval_coverage, targets.forecast.interval_coverage_90.join('–'), (q.forecast || {}).n, (q.forecast || {}).calibrated)}
          </table>`)}
        ${App.card('Проверки целостности', (q.integrity_checks || []).length ? `<table class="tbl"><tr><th>Проверка</th><th>Результат</th><th>Детали</th></tr>
          ${q.integrity_checks.map(c => `<tr><td>${esc(c.check)}</td><td>${c.ok ? App.tag('пройдена ✓', 'ok') : App.tag('нарушена ✕', 'err')}</td>
            <td class="tiny">${esc(JSON.stringify(Object.fromEntries(Object.entries(c).filter(([k]) => !['check', 'ok'].includes(k)))))}</td></tr>`).join('')}</table>` : App.empty('Проверки не выполнялись', '✅'))}
        ${App.card('Как завершить калибровку', `<ol class="tiny">
          <li>Разметить не менее 30 документов по релевантности (0/1/2) в UI-04 — появятся Precision@10 и nDCG@10.</li>
          <li>Собрать эталонные пары TRL (экспертная оценка vs расчёт) — появятся MAE и weighted kappa.</li>
          <li>Собрать ретроспективные прогнозы с известным исходом — появятся Brier score и покрытие интервалов.</li>
          <li>Зафиксировать новую версию методики и контрольные суммы; изменения журналируются.</li></ol>`)}`;
      App.ctxObject('Качество', {'Целостность': q.integrity_ok ? 'пройдена' : 'есть нарушения',
        'Калибровка': esc(q.calibration_status || 'не завершена'), 'Версия методики': esc(q.methodology_version)});
    },
  };
})();
