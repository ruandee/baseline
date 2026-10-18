// /resident/:id (BL-19): verdict card, small-multiple charts, evidence chain, SBAR, decision table.
// Uses the real overview/evidence contracts by default; ?mock=1 is explicitly fixture-only.
(function () {
  const SECTIONS = {S: 'Situation', B: 'Background', A: 'Assessment', R: 'Recommendation'};
  const SBAR_BADGE = {gemini: 'AI draft, verify', template: 'Template'};
  const KIND_LABEL = {amplifier: 'Amplifier', explainer: 'Explainer'};

  const MS_PER_DAY = 86400000;
  const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
  const num = (v, digits) => (isNum(v) ? v.toFixed(digits) : '—');

  // Feature values; pause_ratio is a fraction shown as a percentage.
  function fmt(feature, v) {
    if (!isNum(v)) return '—';
    if (feature === 'pause_ratio') return `${(v * 100).toFixed(0)}%`;
    return v.toFixed(feature === 'speech_rate_wpm' || feature === 'f0_median_hz' ? 0 : 2);
  }

  // Scale-like quantities (MAD, scale) share the feature's unit; pause_ratio stays a fraction.
  const fmtSpread = (feature, v) => num(v, feature === 'pause_ratio' ? 2 : 1);

  function emptyChart(h, text) {
    return h.el('p', text, {class: 'bl-muted bl-chart-empty'});
  }

  function chart(h, name, meta, data) {
    const {svgEl} = h;
    const [w, ht, pad] = [320, 140, 8];
    const series = data.series && data.series[name];
    const daily = (series && series.daily) || [];
    const checks = (series && series.checks) || [];
    const base = data.baseline && data.baseline.features && data.baseline.features[name];
    if (!daily.length) return emptyChart(h, 'Not enough data yet.');
    if (!base || !isNum(base.median) || !isNum(base.scale)) {
      return emptyChart(h, 'Baseline is still being built.');
    }
    // The band is median ± 2 × scale, where scale is the engine's floored robust spread.
    const band = [base.median - 2 * base.scale, base.median + 2 * base.scale];
    const all = [...daily.map((d) => d.median), ...checks.map((c) => c.value), ...band]
      .filter(isNum);
    const [lo, hi] = [Math.min(...all), Math.max(...all)];
    const t0 = new Date(daily[0].day).getTime();
    const t1 = new Date(daily[daily.length - 1].day).getTime() + MS_PER_DAY;
    const x = (t) => pad + ((t - t0) / (t1 - t0)) * (w - 2 * pad);
    const y = (v) => pad + (ht - 2 * pad) * (1 - (v - lo) / (hi - lo || 1));
    const svg = svgEl('svg', {viewBox: `0 0 ${w} ${ht}`, class: 'bl-chart', role: 'img',
      'aria-label': `${meta.label}, ${daily.length} days. Usual range ${fmt(name, band[0])} to ${fmt(name, band[1])}.`});
    svg.append(svgEl('rect', {x: pad, y: y(band[1]), width: w - 2 * pad, height: y(band[0]) - y(band[1]),
                              class: 'bl-band'}));
    checks.filter((c) => isNum(c.value)).forEach((c) => svg.append(svgEl('circle', {cx: x(new Date(c.ts).getTime()), cy: y(c.value),
                                                      r: 2, class: 'bl-dot'})));
    svg.append(svgEl('polyline', {class: 'bl-line', fill: 'none',
      points: daily.filter((d) => isNum(d.median)).map((d) => `${x(new Date(d.day).getTime() + MS_PER_DAY / 2)},${y(d.median)}`).join(' ')}));
    const changeAt = data.first_change_ts ? new Date(data.first_change_ts).getTime() : NaN;
    if (changeAt >= t0 && changeAt <= t1) {
      const cx = x(changeAt);
      svg.append(svgEl('line', {x1: cx, x2: cx, y1: pad, y2: ht - pad, class: 'bl-marker'}));
    }
    return svg;
  }

  function highlighted(h, reason) {
    const p = h.el('p', '', {class: 'bl-quote'});
    // Spans are Unicode code points, not UTF-16 units.
    const chars = Array.from(reason.quote);
    const [a, b] = reason.match || [0, 0];
    p.append(`“${chars.slice(0, a).join('')}`);
    if (b > a) p.append(h.el('mark', chars.slice(a, b).join('')));
    p.append(`${chars.slice(b).join('')}”`);
    return p;
  }

  async function openEvidence(h, ctx, evidenceId, target) {
    const request = String(Number(target.dataset.request || 0) + 1);
    target.dataset.request = request;
    target.replaceChildren(h.el('p', 'Loading source…'));
    try {
      const ev = ctx.mock ? window.RESIDENT_FIXTURE_EVIDENCE[evidenceId]
        : await h.api(`/v1/patients/${encodeURIComponent(ctx.id)}/evidence/${encodeURIComponent(evidenceId)}`);
      if (target.dataset.request !== request) return;
      if (!ev) throw new Error('404 evidence');
      target.replaceChildren(
        h.el('p', `${ev.source_kind} · ${ev.author_role} · recorded ${h.formatTime(ev.recorded_at)}`,
             {class: 'bl-muted'}),
        h.el('blockquote', ev.quote, {class: 'bl-source-quote'}));
    } catch (error) {
      if (target.dataset.request !== request) return;
      target.replaceChildren(h.el('p', `Could not open the source (${error.message}).`,
                                  {class: 'bl-status', 'data-state': 'error'}));
    }
  }

  function verdictCard(h, data) {
    const a = data.latest_assessment;
    const card = h.el('section', '', {class: 'bl-card'});
    if (!a) {
      card.append(h.chip('No assessment yet', 'enrolling'),
                  h.el('p', 'Waiting for enough voice checks to build a baseline.'));
      return card;
    }
    const overBudget = a.verdict === 'escalate' && a.over_budget;
    card.append(h.chip(overBudget ? 'Escalate (over budget)' : h.VERDICT_LABELS[a.verdict] || a.verdict,
                       overBudget ? 'watch' : a.verdict));
    if (data.watch_window && data.watch_window.open) {
      card.append(' ', h.el('span', `Day ${data.watch_window.day} of ${data.watch_window.of}`,
                            {class: 'bl-window'}));
    }
    if (a.suggested_action && a.suggested_action.id !== 'none') {
      const actionId = `action-${a.id}`;
      const button = h.el('button', a.suggested_action.label, {class: 'bl-action', type: 'button',
        'aria-expanded': 'false', 'aria-controls': actionId});
      const heading = h.el('h3', 'Review the proposed action and handoff', {tabindex: '-1'});
      const detail = h.el('section', '', {id: actionId, class: 'bl-action-detail', hidden: ''});
      detail.append(heading, h.el('p', `Suggested: ${a.suggested_action.label}. Review the evidence `
        + 'and draft below, then use your facility’s assessment workflow.'));
      button.addEventListener('click', () => {
        detail.hidden = !detail.hidden;
        button.setAttribute('aria-expanded', String(!detail.hidden));
        if (!detail.hidden) heading.focus();
      });
      card.append(button, detail);
      if (a.no_escalate_profile) {
        card.append(h.el('p', 'Would escalate, disabled for this profile.', {class: 'bl-muted'}));
      }
    }
    return card;
  }

  async function openCheckEvidence(h, ctx, initial, evidenceId, target) {
    const request = String(Number(target.dataset.request || 0) + 1);
    target.dataset.request = request;
    target.replaceChildren(h.el('p', 'Loading voice check…'));
    try {
      // Reauthorize readback, and refuse to mix a newer assessment with the displayed draft.
      const current = ctx.mock ? initial : await load(h, ctx);
      const assessment = current.latest_assessment;
      if (!assessment || assessment.id !== initial.latest_assessment.id
          || !assessment.check || `check:${assessment.check.id}` !== evidenceId) {
        throw new Error('Check evidence changed or unavailable; reload the resident.');
      }
      if (target.dataset.request !== request) return;
      const panel = h.el('section', '', {class: 'bl-check-evidence'});
      panel.append(h.el('h3', 'Stored voice check'),
        h.el('p', `Recorded ${h.formatTime(assessment.check.ts)}`),
        h.el('p', assessment.check.synthetic
          ? 'Authored synthetic measurements; no audio or source-document quote.'
          : 'Voice-derived measurements; no source-document quote.'));
      Object.entries(assessment.change.per_feature || {}).forEach(([name, feature]) => {
        const meta = current.features[name] || {label: name, unit: ''};
        panel.append(h.el('p', `${meta.label}: ${fmt(name, feature.value)}`
          + (name === 'pause_ratio' ? '' : ` ${meta.unit}`)));
      });
      target.replaceChildren(panel);
    } catch (error) {
      if (target.dataset.request !== request) return;
      target.replaceChildren(h.el('p', `Could not open the voice check (${error.message}).`,
        {class: 'bl-status', 'data-state': 'error'}));
    }
  }

  function evidenceChain(h, ctx, data) {
    const section = h.el('section', '', {class: 'bl-section'});
    section.append(h.el('h2', 'Evidence'));
    const reasons = (data.latest_assessment && data.latest_assessment.reasons) || [];
    if (!reasons.length) section.append(h.el('p', 'No current context evidence supplied for this assessment.', {class: 'bl-muted'}));
    reasons.forEach((r) => {
      const row = h.el('div', '', {class: 'bl-reason'});
      const open = h.el('button', 'Open source', {type: 'button', class: 'bl-link',
        'data-evidence-id': r.evidence_id});
      const detail = h.el('div', '', {class: 'bl-source', hidden: ''});
      open.addEventListener('click', async () => {
        detail.hidden = false;
        await openEvidence(h, ctx, r.evidence_id, detail);
      });
      row.append(h.el('span', KIND_LABEL[r.kind] || r.kind, {class: 'bl-kind', 'data-kind': r.kind}),
                 ' ', h.el('strong', r.label), highlighted(h, r),
                 h.el('p', `${r.source_kind} · ${h.formatTime(r.recorded_at)}`, {class: 'bl-muted'}),
                 open, detail);
      section.append(row);
    });
    const observations = data.documented_observations || [];
    section.append(h.el('h3', 'Documented observations'));
    if (!observations.length) section.append(h.el('p', 'No temperature measurement available in this view.', {class: 'bl-muted'}));
    observations.forEach((observation) => {
      const row = h.el('div', '', {class: 'bl-observation'});
      const open = h.el('button', 'Open source', {type: 'button', class: 'bl-link bl-observation-source',
        'data-evidence-id': observation.evidence_id});
      const detail = h.el('div', '', {class: 'bl-source', hidden: ''});
      open.addEventListener('click', async () => {
        detail.hidden = false;
        await openEvidence(h, ctx, observation.evidence_id, detail);
      });
      row.append(h.el('p', `${observation.label} · ${observation.source_kind} · recorded ${h.formatTime(observation.recorded_at)}`), open, detail);
      section.append(row);
    });
    return section;
  }

  function sbarPanel(h, ctx, data) {
    const sbar = data.latest_assessment && data.latest_assessment.sbar;
    if (!sbar) return null;
    const section = h.el('section', '', {class: 'bl-section'});
    section.append(h.el('h2', 'SBAR draft'),
                   h.el('span', SBAR_BADGE[sbar.source] || sbar.source, {class: 'bl-badge', 'data-source': sbar.source}));
    const sourcePanel = h.el('div', '', {class: 'bl-source', hidden: ''});
    const order = [...new Set(sbar.sentences.flatMap((s) => s.evidence_ids).filter((id) => !id.startsWith('check:')))];
    Object.entries(SECTIONS).forEach(([key, label]) => {
      const lines = sbar.sentences.filter((s) => s.section === key);
      if (!lines.length) return;
      section.append(h.el('h3', label));
      lines.forEach((s) => {
        const p = h.el('p', s.text);
        s.evidence_ids.forEach((id) => {
          if (id.startsWith('check:')) {  // the check itself, not a source document
            const check = h.el('button', 'check', {type: 'button', class: 'bl-cite bl-check-cite',
              title: 'Open stored voice-check measurements', 'data-evidence-id': id});
            check.addEventListener('click', () => {
              sourcePanel.hidden = false;
              openCheckEvidence(h, ctx, data, id, sourcePanel);
            });
            p.append(' ', check);
            return;
          }
          const chipButton = h.el('button', `source ${order.indexOf(id) + 1}`,
                                  {type: 'button', class: 'bl-cite', title: 'Open the source quote',
                                    'data-evidence-id': id});
          chipButton.addEventListener('click', () => {
            sourcePanel.hidden = false;
            openEvidence(h, ctx, id, sourcePanel);
          });
          p.append(' ', chipButton);
        });
        section.append(p);
      });
    });
    section.append(sourcePanel);
    return section;
  }

  function decisionTable(h, data) {
    const a = data.latest_assessment;
    const details = h.el('details', '', {class: 'bl-section'});
    details.append(h.el('summary', 'How this was decided'));
    if (!a || !a.change) {
      details.append(h.el('p', 'No change analysis yet.', {class: 'bl-muted'}));
      return details;
    }
    const table = document.createElement('table');
    table.className = 'bl-table';
    const head = document.createElement('tr');
    ['Feature', 'Value', 'Median', 'Scale', 'z', 'EWMA', 'CUSUM']
      .forEach((t) => head.append(h.el('th', t, {scope: 'col'})));
    const thead = document.createElement('thead');
    thead.append(head);
    const body = document.createElement('tbody');
    Object.entries(a.change.per_feature || {}).forEach(([name, f]) => {
      const tr = document.createElement('tr');
      [((data.features || {})[name] || {}).label || name, fmt(name, f.value), fmt(name, f.median),
       fmtSpread(name, f.scale), num(f.z, 2), num(f.ewma, 2),
       num(f.cusum, 2)].forEach((t) => tr.append(h.el('td', t)));
      body.append(tr);
    });
    table.append(thead, body);
    const params = JSON.stringify(a.change.params || {}, null, 2);
    details.append(h.el('p', `Status ${a.change.status} · mode ${a.change.mode} · fused z ${num(a.change.fused_z, 1)}`),
                   table, h.el('pre', params, {class: 'bl-muted bl-parameters', 'aria-label': 'Engine parameters'}));
    return details;
  }

  async function load(h, ctx) {
    if (ctx.mock) {
      const data = window.RESIDENT_FIXTURES[ctx.id];
      if (!data) throw new Error(`404 no fixture for "${ctx.id}"`);
      return data;
    }
    return h.api(`/v1/patients/${encodeURIComponent(ctx.id)}/overview?days=30`);
  }

  window.renderResident = async function (main, id, h) {
    const ctx = {id, mock: h.mock};
    main.replaceChildren(h.el('p', 'Loading…'));
    let data;
    try {
      data = await load(h, ctx);
    } catch (error) {
      main.replaceChildren(h.el('h1', 'Resident'),
        h.el('div', `Could not load this resident (${error.message}).`, {class: 'bl-status', 'data-state': 'error'}));
      return;
    }
    const title = h.el('h1', data.display_name);
    if (data.synthetic) title.append(' ', h.el('span', 'synthetic', {class: 'bl-synthetic'}));
    const grid = h.el('div', '', {class: 'bl-charts'});
    Object.entries(data.features || {}).forEach(([name, meta]) => {
      const fig = h.el('figure', '', {class: 'bl-fig'});
      fig.append(h.el('figcaption', `${meta.label} (${meta.unit})`), chart(h, name, meta, data));
      grid.append(fig);
    });
    const legend = h.el('p', 'Line: daily median · dots: each check · green band: usual range (median ± 2 × scale) · dashed line: first change', {class: 'bl-muted'});
    const sbar = sbarPanel(h, ctx, data);
    main.replaceChildren(title, verdictCard(h, data), h.el('h2', 'Last 30 days'), grid, legend,
                         evidenceChain(h, ctx, data), ...(sbar ? [sbar] : []),
                         decisionTable(h, data));
    if (!ctx.mock && data.latest_assessment && data.latest_assessment.sbar && window.noteExportPanel) {
      main.append(window.noteExportPanel(h, ctx.id, data.latest_assessment.id));
    }
  };
})();
