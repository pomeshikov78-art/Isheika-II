/* ИЩЕЙКА НТР AI — SVG-инфографика без внешних библиотек (ТЗ-04 §4).
   Каждый график имеет легенду, подписи, единицы измерения и текстовую альтернативу.
   Отсутствие данных не изображается нулём: разрыв линии и метка «нет данных». */
const Charts = (() => {
  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim() || '#888';
  const palette = ['#1f6feb','#1a7f4b','#9a6a00','#805ad5','#b3261e','#0f766e','#c2410c','#475569'];

  function wrap(svg, {legend = '', alt = '', unit = ''} = {}) {
    return `<div class="chart-box">${svg}
      ${unit ? `<div class="tiny muted">Единицы: ${esc(unit)}</div>` : ''}
      ${legend ? `<div class="legend">${legend}</div>` : ''}
      ${alt ? `<details class="acc"><summary>Текстовая альтернатива / исходные данные</summary><div class="tiny">${alt}</div></details>` : ''}
    </div>`;
  }

  /* Линейный график с пропусками (null = нет данных) */
  function line(series, opts = {}) {
    const W = opts.width || 720, H = opts.height || 220, P = {l: 44, r: 14, t: 14, b: 28};
    const xs = [...new Set(series.flatMap(s => s.points.map(p => p.x)))].sort((a, b) => a - b);
    if (!xs.length) return `<div class="state"><span class="ico">📉</span>Нет данных для графика</div>`;
    const vals = series.flatMap(s => s.points.map(p => p.y)).filter(v => v != null);
    const maxY = Math.max(1, ...vals), minY = 0;
    const sx = x => P.l + (xs.length === 1 ? (W - P.l - P.r) / 2 : (xs.indexOf(x) / (xs.length - 1)) * (W - P.l - P.r));
    const sy = y => H - P.b - ((y - minY) / (maxY - minY || 1)) * (H - P.t - P.b);
    let g = '';
    for (let i = 0; i <= 4; i++) {
      const y = P.t + i * (H - P.t - P.b) / 4, v = Math.round(maxY - i * (maxY - minY) / 4);
      g += `<line x1="${P.l}" y1="${y}" x2="${W - P.r}" y2="${y}" stroke="${css('--line')}"/>
            <text x="${P.l - 6}" y="${y + 4}" text-anchor="end" font-size="10" fill="${css('--muted')}">${v}</text>`;
    }
    const step = Math.ceil(xs.length / 12);
    xs.forEach((x, i) => { if (i % step === 0) g += `<text x="${sx(x)}" y="${H - 8}" text-anchor="middle" font-size="10" fill="${css('--muted')}">${esc(x)}</text>`; });
    series.forEach((s, si) => {
      const col = s.color || palette[si % palette.length];
      let d = '', open = false;
      xs.forEach(x => {
        const p = s.points.find(q => q.x === x);
        if (!p || p.y == null) { open = false; return; }
        d += (open ? ' L' : ' M') + sx(x) + ' ' + sy(p.y); open = true;
      });
      g += `<path d="${d}" fill="none" stroke="${col}" stroke-width="2"/>`;
      s.points.filter(p => p.y != null).forEach(p => { g += `<circle cx="${sx(p.x)}" cy="${sy(p.y)}" r="2.5" fill="${col}"><title>${esc(s.name)}: ${esc(p.x)} = ${esc(p.y)}</title></circle>`; });
    });
    const legend = series.map((s, i) => `<span><i style="background:${s.color || palette[i % palette.length]}"></i>${esc(s.name)}</span>`).join('');
    const alt = `<table class="tbl"><tr><th>${esc(opts.xLabel || 'X')}</th>${series.map(s => `<th>${esc(s.name)}</th>`).join('')}</tr>` +
      xs.map(x => `<tr><td>${esc(x)}</td>${series.map(s => { const p = s.points.find(q => q.x === x); return `<td>${p && p.y != null ? esc(p.y) : 'нет данных'}</td>`; }).join('')}</tr>`).join('') + '</table>';
    return wrap(`<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opts.title || 'График')}">${g}</svg>`,
      {legend, alt, unit: opts.unit});
  }

  /* Столбчатая диаграмма */
  function bar(items, opts = {}) {
    if (!items.length) return `<div class="state"><span class="ico">📊</span>Нет данных</div>`;
    const W = opts.width || 720, H = opts.height || 220, P = {l: 44, r: 12, t: 12, b: 46};
    const max = Math.max(1, ...items.map(i => i.value || 0));
    const bw = (W - P.l - P.r) / items.length;
    let g = '';
    for (let i = 0; i <= 4; i++) {
      const y = P.t + i * (H - P.t - P.b) / 4;
      g += `<line x1="${P.l}" y1="${y}" x2="${W - P.r}" y2="${y}" stroke="${css('--line')}"/>
            <text x="${P.l - 6}" y="${y + 4}" text-anchor="end" font-size="10" fill="${css('--muted')}">${Math.round(max - i * max / 4)}</text>`;
    }
    items.forEach((it, i) => {
      const h = ((it.value || 0) / max) * (H - P.t - P.b);
      const x = P.l + i * bw + bw * 0.15, y = H - P.b - h;
      g += `<rect x="${x}" y="${y}" width="${bw * 0.7}" height="${h}" fill="${it.color || palette[i % palette.length]}" rx="3"><title>${esc(it.label)}: ${esc(it.value)}</title></rect>
            <text x="${x + bw * 0.35}" y="${H - P.b + 14}" text-anchor="middle" font-size="10" fill="${css('--muted')}">${esc(String(it.label).slice(0, 10))}</text>
            <text x="${x + bw * 0.35}" y="${y - 3}" text-anchor="middle" font-size="10" fill="${css('--text')}">${esc(it.value)}</text>`;
    });
    const alt = `<table class="tbl"><tr><th>Категория</th><th>Значение</th></tr>${items.map(i => `<tr><td>${esc(i.label)}</td><td>${esc(i.value)}</td></tr>`).join('')}</table>`;
    return wrap(`<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opts.title || 'Диаграмма')}">${g}</svg>`, {alt, unit: opts.unit});
  }

  /* Radar chart — факторы реализуемости */
  function radar(items, opts = {}) {
    if (!items.length) return `<div class="state"><span class="ico">🕸️</span>Нет факторов</div>`;
    const S = opts.size || 300, c = S / 2, R = S / 2 - 46, n = items.length;
    const ang = i => (Math.PI * 2 * i) / n - Math.PI / 2;
    let g = '';
    for (let k = 1; k <= 4; k++) {
      const r = (R * k) / 4;
      g += `<circle cx="${c}" cy="${c}" r="${r}" fill="none" stroke="${css('--line')}"/>`;
    }
    const pts = items.map((it, i) => {
      const v = it.value == null ? 0 : it.value;
      return [c + Math.cos(ang(i)) * R * v, c + Math.sin(ang(i)) * R * v];
    });
    g += `<polygon points="${pts.map(p => p.join(',')).join(' ')}" fill="${css('--accent')}33" stroke="${css('--accent')}" stroke-width="2"/>`;
    items.forEach((it, i) => {
      const x = c + Math.cos(ang(i)) * (R + 16), y = c + Math.sin(ang(i)) * (R + 16);
      const anchor = Math.abs(x - c) < 12 ? 'middle' : (x > c ? 'start' : 'end');
      g += `<line x1="${c}" y1="${c}" x2="${c + Math.cos(ang(i)) * R}" y2="${c + Math.sin(ang(i)) * R}" stroke="${css('--line')}"/>
            <text x="${x}" y="${y}" text-anchor="${anchor}" font-size="10" fill="${it.value == null ? css('--warn') : css('--muted')}">${esc(it.label)}${it.value == null ? ' (?)' : ''}</text>
            <circle cx="${pts[i][0]}" cy="${pts[i][1]}" r="3" fill="${it.value == null ? css('--warn') : css('--accent')}"><title>${esc(it.label)}: ${it.value == null ? 'неизвестно' : esc(it.value)}</title></circle>`;
    });
    const alt = `<table class="tbl"><tr><th>Фактор</th><th>Оценка</th></tr>${items.map(i => `<tr><td>${esc(i.label)}</td><td>${i.value == null ? 'неизвестно (исключён из расчёта)' : esc(i.value)}</td></tr>`).join('')}</table>`;
    return wrap(`<svg class="chart" viewBox="0 0 ${S} ${S}" role="img" aria-label="Радар факторов">${g}</svg>`,
      {legend: '<span><i style="background:' + css('--accent') + '"></i>оценка фактора</span><span><i style="background:' + css('--warn') + '"></i>неизвестно</span>', alt});
  }

  /* Fan chart — сценарии прогноза с интервалами */
  function fan(horizons, scenarios, opts = {}) {
    if (!horizons || !horizons.length) return `<div class="state"><span class="ico">🔮</span>Нет прогноза</div>`;
    const W = opts.width || 760, H = opts.height || 260, P = {l: 44, r: 16, t: 14, b: 40};
    const sx = i => P.l + (i / Math.max(1, horizons.length - 1)) * (W - P.l - P.r);
    const sy = p => H - P.b - p * (H - P.t - P.b);
    let g = '';
    for (let i = 0; i <= 4; i++) {
      const y = P.t + i * (H - P.t - P.b) / 4;
      g += `<line x1="${P.l}" y1="${y}" x2="${W - P.r}" y2="${y}" stroke="${css('--line')}"/>
            <text x="${P.l - 6}" y="${y + 4}" text-anchor="end" font-size="10" fill="${css('--muted')}">${(1 - i / 4).toFixed(2)}</text>`;
    }
    horizons.forEach((h, i) => {
      g += `<text x="${sx(i)}" y="${H - P.b + 16}" text-anchor="middle" font-size="10" fill="${css('--muted')}">${h.from}–${h.to}</text>`;
      if (h.from >= 20) g += `<rect x="${sx(i) - 22}" y="${P.t}" width="44" height="${H - P.t - P.b}" fill="${css('--warn')}12"/>`;
    });
    g += `<text x="${W / 2}" y="${H - 6}" text-anchor="middle" font-size="10" fill="${css('--muted')}">горизонт, лет (зона 20–50 — только качественные сценарии)</text>`;
    const names = Object.keys(scenarios || {});
    const colors = {optimistic: '#1a7f4b', base: '#1f6feb', pessimistic: '#b3261e'};
    // интервал базового сценария
    const base = scenarios.base || [];
    let up = '', dn = '';
    base.forEach((p, i) => {
      if (!p.interval) return;
      up += (up ? ' L' : 'M') + sx(i) + ' ' + sy(p.interval[1]);
      dn = ' L' + sx(i) + ' ' + sy(p.interval[0]) + dn;
    });
    if (up) g += `<path d="${up}${dn} Z" fill="${css('--accent')}22" stroke="none"/>`;
    names.forEach(n => {
      let d = '', open = false;
      (scenarios[n] || []).forEach((p, i) => {
        if (p.probability == null) { open = false; return; }
        d += (open ? ' L' : 'M') + sx(i) + ' ' + sy(p.probability); open = true;
      });
      if (d) g += `<path d="${d}" fill="none" stroke="${colors[n] || css('--accent')}" stroke-width="2" ${n === 'pessimistic' ? 'stroke-dasharray="5 3"' : ''}/>`;
    });
    const legend = names.map(n => `<span><i style="background:${colors[n] || '#888'}"></i>${esc(n)}</span>`).join('') +
      '<span><i style="background:' + css('--accent') + '33"></i>интервал неопределённости</span>';
    const alt = `<table class="tbl"><tr><th>Горизонт</th>${names.map(n => `<th>${esc(n)}</th>`).join('')}</tr>` +
      horizons.map((h, i) => `<tr><td>${h.from}–${h.to} лет</td>${names.map(n => {
        const p = (scenarios[n] || [])[i] || {};
        return `<td>${p.probability != null ? p.probability.toFixed(2) + ' [' + p.interval.join('; ') + ']' : (p.qualitative || 'нет данных')}</td>`;
      }).join('')}</tr>`).join('') + '</table>';
    return wrap(`<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Сценарный прогноз">${g}</svg>`, {legend, alt, unit: 'P(T ≤ t), доля'});
  }

  /* Матрица рисков */
  function riskMatrix(items, opts = {}) {
    const S = opts.size || 300, P = 34, cell = (S - P - 10) / 5;
    let g = '';
    for (let i = 0; i < 5; i++) for (let j = 0; j < 5; j++) {
      const sev = (i + j) / 8;
      const col = sev > 0.66 ? '#b3261e' : sev > 0.33 ? '#9a6a00' : '#1a7f4b';
      g += `<rect x="${P + j * cell}" y="${S - P - (i + 1) * cell}" width="${cell - 2}" height="${cell - 2}" fill="${col}22" stroke="${css('--line')}"/>`;
    }
    (items || []).forEach((it, k) => {
      const j = Math.min(4, Math.floor((it.probability || 0) * 5)), i = Math.min(4, Math.floor((it.criticality || 0) * 5));
      g += `<circle cx="${P + j * cell + cell / 2}" cy="${S - P - (i + 1) * cell + cell / 2}" r="7" fill="${css('--accent')}"><title>${esc(it.title || it.barrier_type)}: критичность ${esc(it.criticality)}, вероятность ${esc(it.probability)}</title></circle>
            <text x="${P + j * cell + cell / 2}" y="${S - P - (i + 1) * cell + cell / 2 + 3}" text-anchor="middle" font-size="9" fill="#fff">${k + 1}</text>`;
    });
    for (let i = 0; i < 5; i++) {
      g += `<text x="${P + i * cell + cell / 2}" y="${S - P + 14}" text-anchor="middle" font-size="9" fill="${css('--muted')}">${(i / 5).toFixed(1)}–${((i + 1) / 5).toFixed(1)}</text>
            <text x="${P - 6}" y="${S - P - i * cell - cell / 2}" text-anchor="end" font-size="9" fill="${css('--muted')}">${(i / 5).toFixed(1)}</text>`;
    }
    g += `<text x="${S / 2}" y="${S - 4}" text-anchor="middle" font-size="10" fill="${css('--muted')}">вероятность →</text>
          <text x="10" y="${S / 2}" font-size="10" fill="${css('--muted')}" transform="rotate(-90 10 ${S / 2})">критичность →</text>`;
    const alt = `<ol class="tiny">${(items || []).map(i => `<li>${esc(i.title || i.barrier_type)} — критичность ${esc(i.criticality)}, вероятность ${esc(i.probability)}</li>`).join('')}</ol>`;
    return wrap(`<svg class="chart" viewBox="0 0 ${S} ${S}" role="img" aria-label="Матрица рисков">${g}</svg>`, {alt});
  }

  /* Heatmap покрытия стран */
  function heatmap(items, opts = {}) {
    if (!items || !items.length) return `<div class="state"><span class="ico">🗺️</span>Нет данных покрытия</div>`;
    const cols = opts.cols || 7, cw = 96, ch = 46, W = cols * cw + 10, H = Math.ceil(items.length / cols) * ch + 10;
    const max = Math.max(1, ...items.map(i => i.documents || 0));
    let g = '';
    items.forEach((it, k) => {
      const x = 5 + (k % cols) * cw, y = 5 + Math.floor(k / cols) * ch;
      const v = (it.documents || 0) / max;
      const fill = it.gap ? css('--warn') + '22' : `rgba(31,111,235,${0.12 + 0.6 * v})`;
      g += `<rect x="${x}" y="${y}" width="${cw - 6}" height="${ch - 6}" rx="6" fill="${fill}" stroke="${it.gap ? css('--warn') : css('--line')}"/>
            <text x="${x + 8}" y="${y + 17}" font-size="11" fill="${css('--text')}">${esc(it.iso2)} ${it.gap ? '⚠' : ''}</text>
            <text x="${x + 8}" y="${y + 32}" font-size="11" fill="${css('--muted')}">${esc(it.documents)} док.</text>
            <title>${esc(it.name_ru)}: ${esc(it.documents)} документов, класс П: ${esc(it.class_P)}</title>`;
    });
    const alt = `<table class="tbl"><tr><th>Страна</th><th>Документов</th><th>Класс П</th><th>Статус</th></tr>${items.map(i => `<tr><td>${esc(i.name_ru)}</td><td>${esc(i.documents)}</td><td>${esc(i.class_P)}</td><td>${i.gap ? 'ПРОБЕЛ' : 'есть данные'}</td></tr>`).join('')}</table>`;
    return wrap(`<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Карта покрытия стран">${g}</svg>`,
      {legend: '<span><i style="background:rgba(31,111,235,.6)"></i>есть данные</span><span><i style="background:' + css('--warn') + '22;border:1px solid ' + css('--warn') + '"></i>пробел покрытия</span>', alt});
  }

  /* Граф связей */
  function graph(nodes, links, opts = {}) {
    if (!nodes.length) return `<div class="state"><span class="ico">🕸️</span>Нет связей</div>`;
    const W = opts.width || 720, H = opts.height || 320, c = {x: W / 2, y: H / 2};
    const pos = {};
    nodes.forEach((n, i) => {
      const a = (2 * Math.PI * i) / nodes.length;
      const r = n.kind === 'center' ? 0 : Math.min(W, H) / 2 - 60;
      pos[n.id] = {x: c.x + Math.cos(a) * r, y: c.y + Math.sin(a) * r};
    });
    let g = '';
    links.forEach(l => {
      const a = pos[l.from], b = pos[l.to];
      if (!a || !b) return;
      g += `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke="${l.confirmed ? css('--ok') : css('--warn')}" stroke-width="1.5" ${l.confirmed ? '' : 'stroke-dasharray="4 3"'}/>`;
    });
    nodes.forEach(n => {
      const p = pos[n.id];
      g += `<circle cx="${p.x}" cy="${p.y}" r="${n.kind === 'center' ? 22 : 14}" fill="${n.kind === 'center' ? css('--accent') : css('--chip')}" stroke="${css('--line')}"><title>${esc(n.label)}</title></circle>
            <text x="${p.x}" y="${p.y + 30}" text-anchor="middle" font-size="10" fill="${css('--muted')}">${esc(String(n.label).slice(0, 22))}</text>`;
    });
    return wrap(`<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Граф связей">${g}</svg>`,
      {legend: '<span><i style="background:' + css('--ok') + '"></i>подтверждённая связь</span><span><i style="background:' + css('--warn') + '"></i>гипотетическая связь</span>'});
  }

  /* Граф связей документов (ИД-03): узлы — логические документы, рёбра — типизированные связи.
     Раскладка группирует документы по кластерам; узел открывает карточку документа. */
  const REL_COLORS = {
    EXACT_DUPLICATE: '#475569', ALTERNATIVE_HOSTING: '#1f6feb', PREPRINT_OF: '#805ad5',
    PUBLISHED_VERSION_OF: '#1a7f4b', REVISION_OF: '#9a6a00', TRANSLATION_OF: '#0f766e',
    SUMMARY_OF: '#c2410c', CITES: '#b3261e',
  };

  function network(nodes, links, opts = {}) {
    if (!nodes.length) return `<div class="state"><span class="ico">🕸️</span>Документов нет — граф не строится</div>`;
    const W = opts.width || 760, H = opts.height || 420, c = {x: W / 2, y: H / 2};
    const groups = {};
    nodes.forEach(n => { const k = n.cluster_id || ('solo:' + n.id); (groups[k] = groups[k] || []).push(n); });
    const keys = Object.keys(groups);
    const pos = {};
    keys.forEach((k, gi) => {
      const a = (2 * Math.PI * gi) / keys.length;
      const R = keys.length === 1 ? 0 : Math.min(W, H) / 2 - 80;
      const gc = {x: c.x + Math.cos(a) * R, y: c.y + Math.sin(a) * R};
      const members = groups[k];
      members.forEach((n, ni) => {
        const r = members.length === 1 ? 0 : 26 + 6 * Math.floor(ni / 8);
        const b = (2 * Math.PI * ni) / members.length;
        pos[n.id] = {x: gc.x + Math.cos(b) * r, y: gc.y + Math.sin(b) * r};
      });
    });
    let g = '';
    links.forEach(l => {
      const a = pos[l.source], b = pos[l.target];
      if (!a || !b) return;
      const col = REL_COLORS[l.type] || css('--muted');
      const dash = (l.confidence != null && l.confidence < 0.8) ? 'stroke-dasharray="5 3"' : '';
      g += `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke="${col}" stroke-width="1.6" ${dash} opacity="0.85"><title>${esc(l.type)} · уверенность ${l.confidence == null ? '—' : l.confidence}</title></line>`;
    });
    nodes.forEach(n => {
      const p = pos[n.id];
      if (!p) return;
      const fill = n.relevance_class === 'DIRECT' ? css('--ok') : n.relevance_class === 'ADJACENT' ? css('--warn') : css('--muted');
      g += `<a href="#/document/${esc(n.id)}" class="gnode"><circle cx="${p.x}" cy="${p.y}" r="9" fill="${fill}" stroke="${css('--line')}" stroke-width="1.2"><title>${esc(n.title)}\n${esc(n.doc_type || '')} · ${esc(n.relevance_class || 'без оценки')} · вхождений: ${n.occurrences == null ? '—' : n.occurrences}</title></circle>
            <text x="${p.x}" y="${p.y + 20}" text-anchor="middle" font-size="9" fill="${css('--muted')}">${esc(String(n.title || '').slice(0, 18))}</text></a>`;
    });
    const types = {};
    links.forEach(l => { types[l.type] = (types[l.type] || 0) + 1; });
    const legend = Object.entries(types).map(([t, n]) =>
      `<span><i style="background:${REL_COLORS[t] || '#888'}"></i>${esc(t)} (${n})</span>`).join('') +
      `<span><i style="background:${css('--ok')}"></i>DIRECT</span><span><i style="background:${css('--warn')}"></i>ADJACENT</span><span><i style="background:${css('--muted')}"></i>BELOW_THRESHOLD</span>`;
    const alt = links.length ? '<table class="tbl"><tr><th>Документ</th><th>Связь</th><th>Связан с</th><th>Уверенность</th></tr>' +
      links.map(l => {
        const na = nodes.find(n => n.id === l.source) || {}, nb = nodes.find(n => n.id === l.target) || {};
        return `<tr><td>${esc(na.title || l.source)}</td><td>${esc(l.type)}</td><td>${esc(nb.title || l.target)}</td><td>${l.confidence == null ? '—' : l.confidence}</td></tr>`;
      }).join('') + '</table>' : 'Связей не обнаружено: все документы независимы.';
    return wrap(`<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Граф связей документов">${g}</svg>`,
      {legend, unit: 'узел — логический документ; ребро — связь (пунктир — уверенность < 0,80)', alt});
  }

  /* Горизонтальная шкала с диапазоном (реализуемость) */
  function range(value, low, high, opts = {}) {
    const W = opts.width || 640, H = 74;
    if (value == null) return `<div class="state"><span class="ico">📏</span>Оценка невозможна: недостаточное покрытие факторов</div>`;
    const x = v => 20 + (v / 100) * (W - 40);
    let g = `<rect x="20" y="30" width="${W - 40}" height="12" rx="6" fill="${css('--chip')}"/>`;
    const zones = [[0,20,'#b3261e'],[20,40,'#c2410c'],[40,60,'#9a6a00'],[60,80,'#1f6feb'],[80,100,'#1a7f4b']];
    zones.forEach(([a,b,c]) => { g += `<rect x="${x(a)}" y="30" width="${x(b)-x(a)}" height="12" fill="${c}33"/>`; });
    if (low != null && high != null) g += `<rect x="${x(low)}" y="26" width="${x(high) - x(low)}" height="20" rx="6" fill="${css('--accent')}33" stroke="${css('--accent')}"/>`;
    g += `<line x1="${x(value)}" y1="18" x2="${x(value)}" y2="54" stroke="${css('--text')}" stroke-width="2"/>
          <text x="${x(value)}" y="14" text-anchor="middle" font-size="12" font-weight="bold" fill="${css('--text')}">${value}%</text>`;
    [0,20,40,60,80,100].forEach(v => { g += `<text x="${x(v)}" y="66" text-anchor="middle" font-size="10" fill="${css('--muted')}">${v}</text>`; });
    return wrap(`<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Шкала реализуемости">${g}</svg>`,
      {legend: '<span><i style="background:' + css('--accent') + '33;border:1px solid ' + css('--accent') + '"></i>диапазон неопределённости</span><span>вертикальная линия — точечная оценка F</span>', unit: '% (оценка возможности достижения состояния, не вероятность успеха)'});
  }

  return {line, bar, radar, fan, riskMatrix, heatmap, graph, network, range, palette, esc, REL_COLORS};
})();

/* Публикация модуля в window обязательна (BOOT-08).
   `const Charts` создаёт лексическую привязку глобальной области, а НЕ свойство
   window: соседние сценарии видят Charts, но `window.Charts === undefined`.
   Диагностика загрузки в index.html проверяла именно window.Charts и на
   полностью рабочем интерфейсе выдавала ложный «FAIL Объект Charts — не определён»,
   из-за чего экран журнала загрузки не скрывался (регрессия BOOT-08 / STAT-07).
   Тот же приём, что и window.App / window.Screens в остальных модулях. */
window.Charts = Charts;
