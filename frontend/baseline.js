// Baseline shell: path router, shared demo-session bootstrap and API health check.
// /unit lives here (BL-18); /check is in check.js (BL-17); /resident/:id lands with BL-19.
const POLL_MS = 10000;
const VERDICT_LABELS = {escalate: 'Escalate', watch: 'Watch', explained: 'Explained',
                        within_normal: 'Within normal', enrolling: 'Enrolling'};
const UNIT_COLUMNS = ['Resident', 'Status', 'Follow-up window', 'Change score',
                      'Speech trend', 'Last check'];
const state = {session: null, unitStop: null};

async function api(path, options = {}) {
  const headers = {...(state.session ? {Authorization: `Bearer ${state.session.token}`} : {}),
                   ...options.headers};
  const response = await fetch(path, {...options, headers});
  if (!response.ok) {
    const error = new Error(`${response.status} ${path}`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

async function bootstrap() {
  const psw = location.pathname === '/check' && typeof checkParams === 'function'
    && checkParams().mode === 'resident';
  const kaze = location.pathname === '/out' || location.pathname.startsWith('/out/session/');
  state.session = await api('/demo/session', {headers: {'X-PM-Demo': '1',
    ...(kaze ? {'X-PM-Role': 'kaze'} : psw ? {'X-PM-Role': 'psw'} : {})}});
  // BL-31: /check resident mode acts as the PSW, whose token never receives scores.
  if (state.session.psw_token && location.pathname === '/check'
      && typeof checkParams === 'function' && checkParams().mode === 'resident') {
    state.session.token = state.session.psw_token;
  }
}

function route() {
  const path = location.pathname;
  const resident = path.match(/^\/resident\/([^/]+)$/);
  const out = path.match(/^\/out\/session\/([^/]+)$/);
  if (path === '/out' || out) return {name: 'out', title: 'Baseline Out', id: out ? out[1] : null};
  if (path === '/unit') return {name: 'unit', title: 'Unit watch list', ticket: 'BL-18'};
  if (path === '/check') return {name: 'check', title: 'Voice check', ticket: 'BL-17'};
  if (resident) return {name: 'resident', title: 'Resident', ticket: 'BL-19', id: resident[1]};
  return {name: 'unknown', title: 'Page not found', ticket: ''};
}

function el(tag, text, attrs = {}) {
  const node = document.createElement(tag);
  node.textContent = text;
  Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
  return node;
}

function svgEl(tag, attrs) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
  return node;
}

function sparkline(points) {
  const values = points.map((p) => p.speech_rate_wpm).filter((v) => typeof v === 'number');
  const [w, h] = [96, 28];
  const svg = svgEl('svg', {viewBox: `0 0 ${w} ${h}`, width: w, height: h, class: 'bl-spark',
                            role: 'img', 'aria-label': values.length
                              ? `Speech rate, ${values.length} readings: ${values.map(Math.round).join(', ')} words per minute`
                              : 'No speech-rate data yet'});
  if (values.length < 2) return svg;
  const [lo, hi] = [Math.min(...values), Math.max(...values)];
  const span = hi - lo || 1;
  const coords = values.map((v, i) => [2 + (i * (w - 4)) / (values.length - 1),
                                       2 + (h - 4) * (1 - (v - lo) / span)]);
  svg.append(svgEl('polyline', {points: coords.map((c) => c.join(',')).join(' '), fill: 'none',
                                class: 'bl-spark-line'}));
  const last = coords[coords.length - 1];
  svg.append(svgEl('circle', {cx: last[0], cy: last[1], r: 2.5, class: 'bl-spark-end'}));
  return svg;
}

function chip(text, verdict) {
  return el('span', text, {class: 'bl-chip', 'data-verdict': verdict});
}

function verdictChip(resident) {
  // Over-budget escalations are watch-list items, not interruptive (docs/06-baseline.md).
  if (resident.latest_verdict === 'escalate' && resident.over_budget) {
    return chip('Escalate (over budget)', 'watch');
  }
  return chip(VERDICT_LABELS[resident.latest_verdict] || resident.latest_verdict || 'No data',
              resident.latest_verdict || 'within_normal');
}

function windowChip(window) {
  return window && window.open
    ? el('span', `Day ${window.day} of ${window.of}`, {class: 'bl-window', title: window.reason || ''})
    : el('span', '—', {class: 'bl-muted', title: (window && window.reason) || 'No watch window open'});
}

function formatTime(iso) {
  if (!iso) return 'No checks yet';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso
    : date.toLocaleString([], {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'});
}

function unitRow(resident) {
  const row = document.createElement('tr');
  row.setAttribute('data-verdict', resident.latest_verdict || 'unknown');
  const name = document.createElement('td');
  const link = el('a', resident.display_name, {href: `/resident/${resident.patient_id}`,
                                               class: 'bl-name',
                                               'aria-label': `Open details for ${resident.display_name}`});
  name.append(link);
  if (resident.synthetic) name.append(' ', el('span', 'synthetic', {class: 'bl-synthetic'}));
  let column = 1;
  const cell = (...children) => {
    const td = document.createElement('td');
    td.setAttribute('data-label', UNIT_COLUMNS[column++]);
    td.append(...children);
    return td;
  };
  row.append(name, cell(verdictChip(resident)), cell(windowChip(resident.watch_window)),
             cell(el('span', typeof resident.fused_z === 'number' ? resident.fused_z.toFixed(1) : '—')),
             cell(sparkline(resident.sparkline || [])),
             cell(el('span', formatTime(resident.last_check_ts))));
  row.addEventListener('click', (event) => {
    if (event.target !== link) link.click();
  });
  return row;
}

function unitHeader(shift) {
  const fmt = (iso) => new Date(iso).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
  const valid = shift && !Number.isNaN(new Date(shift.start).getTime())
    && !Number.isNaN(new Date(shift.end).getTime())
    && Number.isInteger(shift.escalations_used) && Number.isInteger(shift.escalation_budget);
  if (!valid) return 'Shift information unavailable';
  return `Shift ${fmt(shift.start)}–${fmt(shift.end)} · ` +
    `${shift.escalations_used} of ${shift.escalation_budget} escalations used this shift`;
}

function renderUnitData(body, data) {
  const headerText = body.querySelector('[data-unit=shift]');
  headerText.textContent = unitHeader(data.shift);
  const rows = body.querySelector('tbody');
  rows.replaceChildren(...data.residents.map(unitRow));
  body.querySelector('[data-unit=empty]').hidden = data.residents.length > 0;
  ['escalate', 'watch', 'explained'].forEach((verdict) => {
    body.querySelector(`[data-unit=count-${verdict}]`).textContent =
      String(data.residents.filter((resident) => resident.latest_verdict === verdict).length);
  });
  body.querySelector('[data-unit=count-total]').textContent = String(data.residents.length);
}

async function renderUnit(main) {
  if (state.unitStop) state.unitStop();
  main.replaceChildren();
  const body = document.createElement('section');
  body.className = 'bl-unit';
  const table = document.createElement('table');
  table.className = 'bl-table';
  const head = document.createElement('thead');
  const headRow = document.createElement('tr');
  UNIT_COLUMNS
    .forEach((label) => headRow.append(el('th', label, {scope: 'col'})));
  head.append(headRow);
  table.append(head, document.createElement('tbody'));
  const notice = el('div', '', {class: 'bl-status', 'data-state': 'error', 'data-unit': 'error', hidden: ''});
  const heading = el('div', '', {class: 'bl-page-heading'});
  const introduction = el('div', '');
  introduction.append(el('p', 'CARE TEAM', {class: 'bl-eyebrow'}),
    el('h1', 'Your unit, at a glance'),
    el('p', 'See who needs a closer look. Open a resident to understand the change.',
       {class: 'bl-intro'}));
  heading.append(introduction, el('a', 'Start voice checks',
    {href: '/check?mode=resident', class: 'bl-primary-link'}));
  const summary = el('div', '', {class: 'bl-unit-summary', 'aria-label': 'Unit summary'});
  [['escalate', 'Needs review', 'Flagged for nurse review'],
   ['watch', 'On watch', 'A change to follow up'],
   ['explained', 'Context available', 'An explanation to consider'],
   ['total', 'Residents', 'Visible to your care team']].forEach(([key, label, hint]) => {
    const card = el('div', '', {class: 'bl-stat', 'data-summary': key});
    card.append(el('span', label, {class: 'bl-stat-label'}),
      el('strong', '\u2014', {'data-unit': `count-${key}`}),
      el('span', hint, {class: 'bl-stat-hint'}));
    summary.append(card);
  });
  const listHeading = el('div', '', {class: 'bl-list-heading'});
  listHeading.append(el('h2', 'Resident watchlist'),
    el('p', 'Listed in review order. Measurements and source records are inside.',
       {class: 'bl-muted'}));
  body.append(heading, summary, listHeading,
              el('p', 'Loading…', {class: 'bl-shift', 'data-unit': 'shift'}),
              notice, table,
              el('p', 'No residents are visible to this account.', {'data-unit': 'empty', hidden: ''}));
  main.append(body);

  let timer = null;
  let inFlight = false;
  let stopped = false;
  let loaded = false;
  async function refresh() {
    if (inFlight || stopped) return;
    inFlight = true;
    try {
      let data;
      try {
        data = await api('/v1/watchlist');
      } catch (error) {
        if (error.status !== 401) throw error;
        await bootstrap();  // the demo token expired while the page stayed open
        data = await api('/v1/watchlist');
      }
      if (stopped) return;
      renderUnitData(body, data);
      loaded = true;
      notice.hidden = true;
    } catch (error) {
      notice.textContent = loaded
        ? `Could not refresh the watch list (${error.message}). The rows shown may be out of date.`
        : `Could not load the watch list (${error.message}).`;
      notice.hidden = false;
    } finally {
      inFlight = false;
    }
  }
  function stopTimer() {
    clearInterval(timer);
    timer = null;
  }
  function onVisibility() {
    stopTimer();
    if (document.visibilityState === 'visible') {
      refresh();
      timer = setInterval(refresh, POLL_MS);
    }
  }
  document.addEventListener('visibilitychange', onVisibility);
  state.unitStop = () => {
    stopped = true;
    stopTimer();
    document.removeEventListener('visibilitychange', onVisibility);
  };
  refresh();  // load once even if the tab opened in the background
  if (document.visibilityState === 'visible') timer = setInterval(refresh, POLL_MS);
}

async function renderPage(current, renderer) {
  document.querySelectorAll('[data-route]').forEach((a) => {
    if (a.dataset.route === current.name) a.setAttribute('aria-current', 'page');
  });
  const main = document.getElementById('bl-main');
  try {
    await bootstrap();
    await renderer(main);
  } catch (error) {
    main.replaceChildren(el('h1', current.title),
      el('div', `API check failed: ${error.message}`, {class: 'bl-status', 'data-state': 'error'}));
  }
}

async function render() {
  const current = route();
  if (current.name === 'out') {
    await renderPage(current, (main) => renderKaze(main, current.id));
    return;
  }
  if (current.name === 'unit') {
    await renderPage(current, renderUnit);
    return;
  }
  if (current.name === 'check') {
    await renderPage(current, renderCheck);
    return;
  }
  if (current.name === 'resident') {
    document.querySelectorAll('[data-route]').forEach((a) => a.removeAttribute('aria-current'));
    const main = document.getElementById('bl-main');
    try {
      const mock = new URLSearchParams(location.search).get('mock') === '1';
      if (!mock) await bootstrap();
      await window.renderResident(main, current.id,
        {api, el, svgEl, chip, formatTime, VERDICT_LABELS, mock});
    } catch (error) {
      main.replaceChildren(el('h1', current.title),
        el('div', `API check failed: ${error.message}`, {class: 'bl-status', 'data-state': 'error'}));
    }
    return;
  }
  document.querySelectorAll('[data-route]').forEach((a) => {
    if (a.dataset.route === current.name) a.setAttribute('aria-current', 'page');
  });
  const main = document.getElementById('bl-main');
  const status = el('div', 'Checking API connection…', {class: 'bl-status', 'data-state': 'pending'});
  main.replaceChildren(el('h1', current.title),
    el('p', current.ticket ? `Coming with ${current.ticket}.` : 'This page does not exist.'), status);
  try {
    await api('/v1/health/live');
    await bootstrap();
    // /v1/health/ready is administrator-only, so prove the nurse token with a patient read.
    const patient = state.session.patients[0];
    if (!patient) throw new Error('no demo patients in the session');
    await api(`/v1/patients/${patient.id}/timeline`);
    status.textContent = 'API reachable and the demo token is accepted.';
    status.dataset.state = 'ok';
  } catch (error) {
    status.textContent = `API check failed: ${error.message}`;
    status.dataset.state = 'error';
  }
}

render();
