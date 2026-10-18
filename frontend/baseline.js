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
  const nurseWorkspace = location.pathname === '/check'
    && new URLSearchParams(location.search).get('nurse') === '1';
  const psw = location.pathname === '/check' && typeof checkParams === 'function'
    && checkParams().mode === 'resident' && !nurseWorkspace;
  const kaze = location.pathname === '/out' || location.pathname.startsWith('/out/session/');
  state.session = await api('/demo/session', {headers: {'X-PM-Demo': '1',
    ...(kaze ? {'X-PM-Role': 'kaze'} : psw ? {'X-PM-Role': 'psw'} : {})}});
  // BL-31: /check resident mode acts as the PSW, whose token never receives scores.
  if (state.session.psw_token && location.pathname === '/check'
      && typeof checkParams === 'function' && checkParams().mode === 'resident' && !nurseWorkspace) {
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
  const capture = unitCapture(resident);
  if (capture) name.append(el('span', `${capture.capture_mode} capture identity`,
                              {class: 'unit-identity-label'}));
  let column = 1;
  const cell = (...children) => {
    const td = document.createElement('td');
    td.setAttribute('data-label', UNIT_COLUMNS[column++]);
    td.append(...children);
    return td;
  };
  row.append(name, cell(unitVerdict(resident)), cell(windowChip(resident.watch_window)),
             cell(el('span', typeof resident.fused_z === 'number' ? resident.fused_z.toFixed(1) : '—')),
             cell(sparkline(resident.sparkline || [])),
             cell(el('span', formatTime(resident.last_check_ts))));
  row.addEventListener('click', (event) => {
    if (event.target !== link) link.click();
  });
  return row;
}

function unitCapture(resident) {
  return ((state.session && state.session.patients) || []).find((person) =>
    person.id === resident.patient_id && ['live', 'runner'].includes(person.capture_mode));
}

function unitVerdict(resident) {
  return resident.latest_verdict ? verdictChip(resident) : chip('Assessment unavailable', 'unknown');
}

function unitPriorityCard(resident) {
  const card = el('article', '', {class: 'unit-priority-card',
    'data-priority': resident.patient_id, 'data-verdict': resident.latest_verdict});
  const heading = el('div', '', {class: 'unit-card-heading'});
  heading.append(el('h3', resident.display_name), unitVerdict(resident));
  const description = {
    escalate: resident.over_budget
      ? 'Flagged for review; the shift interruption budget has been reached.'
      : 'Flagged for nurse review. Open the assessment before deciding what to do.',
    watch: 'A change is being watched. Review the assessment and follow-up window.',
    explained: 'Explaining context was recorded. Review its source; this does not rule out other concerns.',
  };
  card.append(heading, el('p', description[resident.latest_verdict], {class: 'unit-card-description'}));
  const meta = el('div', '', {class: 'unit-card-meta'});
  meta.append(el('span', `Last check · ${formatTime(resident.last_check_ts)}`));
  if (resident.watch_window && resident.watch_window.open) meta.append(windowChip(resident.watch_window));
  card.append(meta, el('a', 'Open resident →', {href: `/resident/${encodeURIComponent(resident.patient_id)}`,
    class: 'unit-open', 'aria-label': `Open ${resident.display_name}: assessment and source records`}),
  el('p', 'Measurements, context and source records inside', {class: 'unit-card-footnote'}));
  return card;
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
  const roster = data.residents.filter((resident) => !unitCapture(resident));
  const priority = roster.filter((resident) => ['escalate', 'watch', 'explained'].includes(resident.latest_verdict));
  const incomplete = roster.filter((resident) => !['escalate', 'watch', 'explained', 'within_normal'].includes(resident.latest_verdict));
  body.querySelector('[data-unit=priority]').replaceChildren(...priority.map(unitPriorityCard));
  body.querySelector('[data-unit=quiet]').hidden = priority.length > 0 || !roster.length;
  body.querySelector('[data-unit=priority-note]').textContent = priority.length
    ? `${priority.length} residents to review · listed in server review order`
    : roster.length ? 'No review flags in the current response' : 'No roster residents in the current response';
  body.querySelector('[data-unit=incomplete]').textContent = incomplete.length
    ? `${incomplete.length} residents have an unavailable assessment or are still enrolling. This is not a normal finding.` : '';
  const captures = data.residents.filter(unitCapture);
  const captureList = body.querySelector('[data-unit=capture-list]');
  captureList.replaceChildren(...captures.map((resident) => {
    const item = el('li', '', {class: 'unit-capture-item', 'data-capture': resident.patient_id});
    const label = unitCapture(resident).capture_mode === 'runner' ? 'Runner capture' : 'Live voice capture';
    item.append(el('div', label, {class: 'unit-capture-kind'}),
      el('a', resident.display_name, {href: `/resident/${encodeURIComponent(resident.patient_id)}`}),
      unitVerdict(resident), el('span', `Last check · ${formatTime(resident.last_check_ts)}`));
    return item;
  }));
  body.querySelector('[data-unit=captures]').hidden = captures.length === 0;
  body.querySelector('[data-unit=roster-label]').textContent = `All visible residents and capture identities (${data.residents.length})`;
  body.querySelector('[data-unit=roster]').hidden = data.residents.length === 0;
  body.querySelector('[data-unit=empty]').hidden = data.residents.length > 0;
  ['escalate', 'watch', 'explained'].forEach((verdict) => {
    body.querySelector(`[data-unit=count-${verdict}]`).textContent =
      String(roster.filter((resident) => resident.latest_verdict === verdict).length);
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
    el('h1', 'Unit overview'),
    el('p', 'Start with the people who need a closer look. Read the evidence before deciding on a next step.',
       {class: 'bl-intro'}));
  heading.append(introduction, el('a', 'Start voice checks',
    {href: '/check?nurse=1', class: 'bl-primary-link'}));
  const summary = el('div', '', {class: 'bl-unit-summary', 'aria-label': 'Unit summary'});
  [['escalate', 'Needs review', 'Flagged for nurse review'],
   ['watch', 'On watch', 'A change to follow up'],
   ['explained', 'Context available', 'An explanation to consider'],
   ['total', 'Visible people', 'Roster and capture identities']].forEach(([key, label, hint]) => {
    const card = el('div', '', {class: 'bl-stat', 'data-summary': key});
    card.append(el('span', label, {class: 'bl-stat-label'}),
      el('strong', '\u2014', {'data-unit': `count-${key}`}),
      el('span', hint, {class: 'bl-stat-hint'}));
    summary.append(card);
  });
  const listHeading = el('div', '', {class: 'bl-list-heading'});
  listHeading.append(el('h2', 'Needs a closer look'),
    el('p', 'Loading the latest review list…', {'data-unit': 'priority-note', class: 'bl-muted'}));
  const roster = el('details', '', {class: 'unit-roster', 'data-unit': 'roster', hidden: ''});
  roster.append(el('summary', 'All visible residents and capture identities', {'data-unit': 'roster-label'}),
    el('p', 'The full list follows the server’s review order. No flag does not establish that a resident is well.',
       {class: 'unit-roster-note'}), table);
  const captures = el('section', '', {'data-unit': 'captures', class: 'unit-captures', hidden: ''});
  captures.append(el('h2', 'Separate capture identities'),
    el('p', 'Live and runner recording identities are shown separately from the resident roster. Their assessments are not scripted cohort cases.'),
    el('ul', '', {'data-unit': 'capture-list'}));
  const retry = el('button', 'Refresh overview', {type: 'button', class: 'unit-refresh', 'data-unit': 'retry'});
  const updates = el('div', '', {class: 'unit-update-bar'});
  const freshness = el('span', 'Loading current assessments…', {'data-unit': 'freshness', role: 'status'});
  updates.append(freshness, retry);
  body.append(heading, updates, notice, summary,
    el('p', 'Loading shift information…', {class: 'bl-shift', 'data-unit': 'shift'}), listHeading,
    el('div', '', {class: 'unit-priority-list', 'data-unit': 'priority'}),
    el('p', 'No residents are flagged for review. Assessments may still be incomplete; open the full roster to check.',
      {class: 'unit-quiet', 'data-unit': 'quiet', hidden: ''}),
    el('p', '', {class: 'unit-incomplete', 'data-unit': 'incomplete'}), captures, roster,
    el('p', 'No residents are visible to this account. Check the selected account or try refreshing.',
      {class: 'unit-quiet', 'data-unit': 'empty', hidden: ''}));
  main.append(body);

  let timer = null;
  let inFlight = false;
  let stopped = false;
  let loaded = false;
  async function refresh() {
    if (inFlight || stopped) return;
    inFlight = true;
    retry.disabled = true;
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
      freshness.textContent = `Updated ${new Date().toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})} · refreshes every 10 seconds while visible`;
    } catch (error) {
      if (stopped) return;
      if ([401, 403, 404].includes(error.status)) {
        // A denied refresh must not keep displaying a formerly authorized roster.
        body.querySelector('tbody').replaceChildren();
        body.querySelector('[data-unit=priority]').replaceChildren();
        body.querySelector('[data-unit=capture-list]').replaceChildren();
        ['roster', 'captures', 'quiet', 'empty'].forEach((key) => {
          body.querySelector(`[data-unit=${key}]`).hidden = true;
        });
        ['escalate', 'watch', 'explained', 'total'].forEach((key) => {
          body.querySelector(`[data-unit=count-${key}]`).textContent = '—';
        });
        body.querySelector('[data-unit=incomplete]').textContent = '';
        body.querySelector('[data-unit=shift]').textContent = 'Shift information unavailable';
        loaded = false;
      }
      notice.textContent = loaded
        ? `Could not refresh the watch list (${error.message}). The rows shown may be out of date.`
        : `Could not load the watch list (${error.message}).`;
      notice.hidden = false;
      freshness.textContent = loaded ? 'Update failed · the displayed assessments may be out of date' : 'Overview unavailable · try refreshing';
      if (!loaded) body.querySelector('[data-unit=priority-note]').textContent = 'Assessments could not be loaded. No normal finding can be inferred.';
    } finally {
      inFlight = false;
      if (!stopped) retry.disabled = false;
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
  retry.addEventListener('click', refresh);
  refresh();  // load once even if the tab opened in the background
  if (document.visibilityState === 'visible') timer = setInterval(refresh, POLL_MS);
}

async function renderPage(current, renderer) {
  const activeRoute = current.name === 'check' && new URLSearchParams(location.search).get('type') === 'motion'
    ? 'movement' : current.name;
  document.querySelectorAll('[data-route]').forEach((a) => {
    if (a.dataset.route === activeRoute) a.setAttribute('aria-current', 'page');
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
  document.title = `${current.title} | Baseline`;
  const demo = location.search ? new URLSearchParams(location.search).get('demo') : null;
  if ((current.name === 'unit' || current.name === 'check')
      && (demo === 'handoff' || demo === 'days')) {
    await window.renderHandoff(document.getElementById('bl-main'),
      {el, chip, bootstrap, api, VERDICT_LABELS});
    return;
  }
  if (current.name === 'out') {
    await renderPage(current, (main) => renderKaze(main, current.id));
    return;
  }
  if (current.name === 'unit') {
    await renderPage(current, renderUnit);
    return;
  }
  if (current.name === 'check') {
    const query = new URLSearchParams(location.search);
    if (query.get('nurse') === '1') {
      await renderPage(current, (main) => window.renderNurseChecks(main, {api, el, session: state.session}));
      return;
    }
    if (query.get('mode') === 'live' && query.get('demo') === 'legacy-days') {
      // Public fictional presentation only: no session bootstrap, retrieval or API writes.
      window.renderDemoDays(document.getElementById('bl-main'), {el, chip, maxSeconds: CHECK_MAX_S});
      return;
    }
    const motion = new URLSearchParams(location.search).get('type') === 'motion';
    await renderPage(current, async (main) => {
      await (motion ? window.renderMotion(main) : renderCheck(main));
      if (!motion && query.get('from') === 'nurse') {
        const person = (state.session.patients || []).find((entry) => entry.id === query.get('patient'));
        const context = el('header', '', {class: 'nurse-capture-context'});
        context.append(el('a', '← Voice checks', {href: '/check?nurse=1', class: 'workspace-text-link'}),
          el('h1', person ? person.name : 'Voice check'),
          el('p', 'Confirm setup and permission, record the fixed prompt, then review the actual result.',
            {class: 'workspace-muted'}));
        main.prepend(context);
      }
    });
    return;
  }
  if (current.name === 'resident') {
    document.querySelectorAll('[data-route]').forEach((a) => a.removeAttribute('aria-current'));
    const notesLink = document.querySelector('[data-route=notes]');
    if (notesLink) notesLink.setAttribute('href', `/?patient=${encodeURIComponent(current.id)}`);
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
