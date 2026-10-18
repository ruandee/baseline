// BL-18 behaviour test: runs the real frontend/baseline.js /unit code in a minimal DOM.
// The watch-list payload comes from UNIT_WATCHLIST_FIXTURE (a live /v1/watchlist response captured
// by tests/contract/test_unit_watchlist_live.py) or the committed schema-shaped fixture.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';

const here = new URL('.', import.meta.url);
const SOURCE = readFileSync(new URL('../../frontend/baseline.js', here), 'utf8');
const FIXTURE = JSON.parse(readFileSync(
  process.env.UNIT_WATCHLIST_FIXTURE || new URL('fixtures/watchlist.json', here), 'utf8'));

class FakeNode {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.attributes = {};
    this.listeners = {};
    this.hidden = false;
    this.text = '';
  }
  set textContent(value) {
    this.children = [];
    this.text = String(value);
  }
  get textContent() {
    return this.text + this.children.map((c) => (typeof c === 'string' ? c : c.textContent)).join('');
  }
  set className(value) { this.attributes.class = value; }
  get dataset() {
    const node = this;
    return new Proxy({}, {
      get: (_, k) => node.attributes[`data-${k}`],
      set: (_, k, v) => { node.attributes[`data-${k}`] = String(v); return true; },
    });
  }
  setAttribute(name, value) {
    if (name === 'hidden') this.hidden = true;
    else this.attributes[name] = String(value);
  }
  getAttribute(name) { return this.attributes[name]; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; this.text = ''; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  click() { this.clicked = (this.clicked || 0) + 1; }
  matches(selector) {
    const attr = selector.match(/^\[([\w-]+)(?:=([\w-]+))?\]$/);
    if (attr) return attr[2] === undefined ? attr[1] in this.attributes
      : this.attributes[attr[1]] === attr[2];
    return this.tagName === selector.toUpperCase();
  }
  *walk() {
    for (const child of this.children) {
      if (typeof child === 'string') continue;
      yield child;
      yield* child.walk();
    }
  }
  querySelector(selector) {
    for (const node of this.walk()) if (node.matches(selector)) return node;
    return null;
  }
  querySelectorAll(selector) { return [...this.walk()].filter((n) => n.matches(selector)); }
}

function harness({visible = true, responses = [FIXTURE], patients = [], search = ''} = {}) {
  const main = new FakeNode('main');
  const root = new FakeNode('body');
  root.append(main);
  const docListeners = {};
  const document = {
    visibilityState: visible ? 'visible' : 'hidden',
    createElement: (tag) => new FakeNode(tag),
    createElementNS: (_, tag) => new FakeNode(tag),
    getElementById: (id) => (id === 'bl-main' ? main : null),
    querySelectorAll: (selector) => root.querySelectorAll(selector),
    addEventListener: (type, fn) => (docListeners[type] ||= []).push(fn),
    removeEventListener: (type, fn) => {
      docListeners[type] = (docListeners[type] || []).filter((f) => f !== fn);
    },
  };
  const intervals = new Map();
  let nextId = 1;
  const calls = [];
  let served = 0;
  const fetch = async (path, options = {}) => {
    calls.push({path, headers: options.headers || {}});
    if (path === '/demo/session') {
      return {ok: true, status: 200, json: async () => ({token: 'synthetic-token', patients})};
    }
    if (path === '/v1/watchlist') {
      const entry = responses[Math.min(served, responses.length - 1)];
      served += 1;
      const body = typeof entry === 'function' ? await entry() : entry;
      return {ok: !body.errorStatus, status: body.errorStatus || 200,
        json: async () => structuredClone(body)};
    }
    return {ok: false, status: 404, json: async () => ({})};
  };
  const context = vm.createContext({
    document, fetch, console, URLSearchParams, location: {pathname: '/unit', search},
    setInterval: (fn, ms) => { intervals.set(nextId, {fn, ms}); return nextId++; },
    clearInterval: (id) => { intervals.delete(id); },
  });
  vm.runInContext(SOURCE, context, {filename: 'frontend/baseline.js'});
  const settle = async () => { for (let i = 0; i < 20; i += 1) await new Promise(setImmediate); };
  return {
    main, intervals, calls, settle,
    constant: (name) => vm.runInContext(name, context),
    watchlistCalls: () => calls.filter((c) => c.path === '/v1/watchlist').length,
    tick: async () => { [...intervals.values()].forEach(({fn}) => fn()); await settle(); },
    setVisibility: async (state) => {
      document.visibilityState = state;
      (docListeners.visibilitychange || []).forEach((fn) => fn());
      await settle();
    },
    listenerCount: () => (docListeners.visibilitychange || []).length,
  };
}

function renderedRows(main) {
  const body = main.querySelector('tbody');
  return body.children.map((row) => {
    const [name, verdict, , fused] = row.children;
    const link = name.children[0];
    return {href: link.getAttribute('href'), name: link.textContent,
            verdict: verdict.children[0].textContent, fused: fused.textContent,
            synthetic: name.children.some((c) => typeof c !== 'string'
                                           && c.getAttribute('class') === 'bl-synthetic'),
            syntheticChip: name.children.find((c) => typeof c !== 'string'
                                               && c.getAttribute('class') === 'bl-synthetic')};
  });
}

test('fixture is a non-empty watch list', () => {
  assert.ok(Array.isArray(FIXTURE.residents) && FIXTURE.residents.length > 0);
});

test('rendered rows follow the API order exactly, with labelled verdicts', async () => {
  const page = harness();
  await page.settle();
  const rows = renderedRows(page.main);
  assert.deepEqual(rows.map((r) => r.href),
                   FIXTURE.residents.map((r) => `/resident/${r.patient_id}`));
  assert.deepEqual(rows.map((r) => r.name), FIXTURE.residents.map((r) => r.display_name));
  const labels = page.constant('VERDICT_LABELS');
  FIXTURE.residents.forEach((resident, i) => {
    const expected = resident.latest_verdict === null ? 'Assessment unavailable'
      : resident.latest_verdict === 'escalate' && resident.over_budget ? 'Escalate (over budget)'
        : labels[resident.latest_verdict];
    assert.ok(expected, `no label for verdict ${resident.latest_verdict}`);
    assert.equal(rows[i].verdict, expected);
    assert.equal(rows[i].fused, typeof resident.fused_z === 'number'
      ? resident.fused_z.toFixed(1) : '—');
    assert.equal(rows[i].synthetic, resident.synthetic === true);
    // The chip stays in the DOM for label logic but the page shows one "Demo scenario" disclosure.
    if (rows[i].synthetic) assert.equal(rows[i].syntheticChip.hidden, true);
  });
  const shift = page.main.querySelector('[data-unit=shift]').textContent;
  assert.match(shift, new RegExp(`${FIXTURE.shift.escalations_used} of ` +
                                 `${FIXTURE.shift.escalation_budget} escalations used this shift`));
  assert.equal(page.main.querySelector('[data-unit=error]').hidden, true);
  assert.equal(page.main.querySelector('[data-unit=empty]').hidden, true);
  const auth = page.calls.find((c) => c.path === '/v1/watchlist').headers.Authorization;
  assert.equal(auth, 'Bearer synthetic-token');
});

test('the page never re-sorts: a reordered API response is rendered as returned', async () => {
  const reversed = {...FIXTURE, residents: [...FIXTURE.residents].reverse()};
  const page = harness({responses: [FIXTURE, reversed]});
  await page.settle();
  await page.tick();
  assert.deepEqual(renderedRows(page.main).map((r) => r.href),
                   reversed.residents.map((r) => `/resident/${r.patient_id}`));
});

test('summary counts follow the current visible roster when polling replaces it', async () => {
  const reduced = {...FIXTURE, residents: FIXTURE.residents.filter(
    (resident) => resident.latest_verdict !== 'escalate')};
  const page = harness({responses: [FIXTURE, reduced]});
  await page.settle();
  assert.equal(page.main.querySelector('[data-unit=count-total]').textContent,
               String(FIXTURE.residents.length));
  assert.equal(page.main.querySelector('[data-unit=count-escalate]').textContent,
               String(FIXTURE.residents.filter((r) => r.latest_verdict === 'escalate').length));
  await page.tick();
  assert.equal(page.main.querySelector('[data-unit=count-escalate]').textContent, '0');
  assert.equal(page.main.querySelector('[data-unit=count-total]').textContent,
               String(reduced.residents.length));
  assert.equal(renderedRows(page.main).length, reduced.residents.length);
});

test('priority cards keep server order and link to records without inventing clinical context', async () => {
  const reversed = {...FIXTURE, residents: [...FIXTURE.residents].reverse()};
  const page = harness({responses: [FIXTURE, reversed]});
  await page.settle();
  const priorityIds = () => page.main.querySelector('[data-unit=priority]').children
    .map((card) => card.getAttribute('data-priority'));
  const eligible = (data) => data.residents.filter((r) =>
    ['escalate', 'watch', 'explained'].includes(r.latest_verdict));
  assert.deepEqual(priorityIds(), eligible(FIXTURE).map((r) => r.patient_id));
  const cards = page.main.querySelector('[data-unit=priority]').children;
  cards.forEach((card, i) => {
    assert.equal(card.querySelector('a').getAttribute('href'),
                 `/resident/${eligible(FIXTURE)[i].patient_id}`);
    assert.match(card.textContent, /source records inside/);
    assert(!card.textContent.includes('dentures'), 'overview does not have source-level context');
    const overBudget = eligible(FIXTURE)[i].latest_verdict === 'escalate'
      && eligible(FIXTURE)[i].over_budget;
    assert.equal(card.textContent.includes('shift interruption budget has been reached'),
                 Boolean(overBudget));
  });
  await page.tick();
  assert.deepEqual(priorityIds(), eligible(reversed).map((r) => r.patient_id));
  assert.equal(page.main.querySelector('[data-unit=roster]').getAttribute('open'), undefined);
  assert.equal(renderedRows(page.main).length, FIXTURE.residents.length);
});

test('over-budget escalation warning follows its own row and clears after a new response', async () => {
  const resident = {...FIXTURE.residents[0], latest_verdict: 'escalate', over_budget: true};
  const data = {...FIXTURE, residents: [resident]};
  const refreshed = {...data, residents: [{...resident, over_budget: false}]};
  const page = harness({responses: [data, refreshed]});
  await page.settle();
  const card = () => page.main.querySelector('[data-unit=priority]').children[0];
  assert.match(card().textContent, /Escalate \(over budget\)/);
  assert.match(card().textContent, /shift interruption budget has been reached/);
  assert.equal(card().getAttribute('data-priority'), resident.patient_id);
  await page.tick();
  assert(!card().textContent.includes('over budget'));
  assert(!card().textContent.includes('shift interruption budget has been reached'));
  assert.match(card().textContent, /Open the assessment before deciding what to do/);
  assert.equal(card().getAttribute('data-priority'), resident.patient_id);
});

test('live volunteers join unit priority with measured verdicts; runner identities remain separate', async () => {
  const capture = {...FIXTURE.residents[0], patient_id: 'arbitrary-capture-id', display_name: 'Person A', latest_verdict: 'watch'};
  const runner = {...FIXTURE.residents[0], patient_id: 'runner-id', display_name: 'Runner A'};
  const namedRunner = {...FIXTURE.residents[0], patient_id: 'ordinary-resident', display_name: 'Runner Capture'};
  const data = {...FIXTURE, residents: [capture, runner, namedRunner, ...FIXTURE.residents]};
  const refreshed = {...data, residents: data.residents.map((r) => r.patient_id === capture.patient_id
    ? {...r, latest_verdict: 'within_normal'} : r)};
  const page = harness({responses: [data, refreshed], patients: [
    {id: capture.patient_id, capture_mode: 'live', name: 'Volunteer A', scripted_cohort: false},
    {id: runner.patient_id, capture_mode: 'runner'},
  ]});
  await page.settle();
  const ids = page.main.querySelector('[data-unit=priority]').children.map((c) => c.getAttribute('data-priority'));
  assert(ids.includes(capture.patient_id));
  assert(!ids.includes(runner.patient_id));
  assert(ids.includes(namedRunner.patient_id), 'a display name must not determine identity type');
  const list = page.main.querySelector('[data-unit=capture-list]');
  assert.equal(list.children.length, 1);
  assert.equal(list.children[0].getAttribute('data-capture'), runner.patient_id);
  assert.match(list.textContent, /Runner capture/);
  const volunteer = page.main.querySelector('[data-unit=priority]').children.find((card) =>
    card.getAttribute('data-priority') === capture.patient_id);
  assert.equal(volunteer.querySelector('h3').textContent, 'Volunteer A');
  assert.match(volunteer.textContent, /Watch/);
  assert.match(volunteer.textContent, /Live volunteer/);
  assert.equal(page.main.querySelector('[data-unit=count-watch]').textContent,
               String(data.residents.filter((r) => r.latest_verdict === 'watch').length));
  assert.deepEqual([...page.intervals.values()].map((interval) => interval.ms), [2000]);
  assert.deepEqual(renderedRows(page.main).map((r) => r.href), data.residents.map((r) => `/resident/${r.patient_id}`));
  assert.equal(page.main.querySelector('[data-unit=count-escalate]').textContent,
               String(data.residents.filter((r) => r.latest_verdict === 'escalate').length - 1));
  await page.tick();
  assert(!page.main.querySelector('[data-unit=priority]').children.some((card) =>
    card.getAttribute('data-priority') === capture.patient_id), 'no forced Watch when the measured result changes');
  assert.equal(renderedRows(page.main).find((row) => row.href.endsWith(capture.patient_id)).verdict, 'Within normal');
});

test('no priority flags keeps unknown and enrolling explicit instead of implying normal', async () => {
  const data = {...FIXTURE, residents: FIXTURE.residents.filter((r) =>
    !['escalate', 'watch', 'explained'].includes(r.latest_verdict))};
  const page = harness({responses: [data]});
  await page.settle();
  assert.equal(page.main.querySelector('[data-unit=priority]').children.length, 0);
  assert.equal(page.main.querySelector('[data-unit=quiet]').hidden, false);
  assert.match(page.main.querySelector('[data-unit=quiet]').textContent, /Assessments may still be incomplete/);
  assert.match(page.main.querySelector('[data-unit=incomplete]').textContent, /not a normal finding/);
  const unknown = page.main.querySelector('tbody').children.find((row) => row.getAttribute('data-verdict') === 'unknown');
  assert.equal(unknown.children[1].children[0].getAttribute('data-verdict'), 'unknown');
  assert.match(unknown.textContent, /Assessment unavailable/);
  assert.equal(renderedRows(page.main).length, data.residents.length);
});

test('first-load failure offers retry without zero counts or a fabricated empty roster', async () => {
  const page = harness({responses: [{errorStatus: 503}, FIXTURE]});
  await page.settle();
  assert.equal(page.main.querySelector('[data-unit=error]').hidden, false);
  assert.equal(page.main.querySelector('[data-unit=empty]').hidden, true);
  assert.equal(page.main.querySelector('[data-unit=count-total]').textContent, '—');
  assert.match(page.main.querySelector('[data-unit=priority-note]').textContent, /No normal finding/);
  await page.main.querySelector('[data-unit=retry]').listeners.click[0]();
  await page.settle();
  assert.equal(page.main.querySelector('[data-unit=error]').hidden, true);
  assert.equal(renderedRows(page.main).length, FIXTURE.residents.length);
});

test('pending initial load shows loading rather than an empty or normal conclusion', async () => {
  let release;
  const page = harness({responses: [() => new Promise((resolve) => { release = resolve; })]});
  await page.settle();
  assert.match(page.main.querySelector('[data-unit=freshness]').textContent, /Loading/);
  assert.equal(page.main.querySelector('[data-unit=quiet]').hidden, true);
  assert.equal(page.main.querySelector('[data-unit=empty]').hidden, true);
  assert.equal(page.main.querySelector('[data-unit=count-total]').textContent, '—');
  release(FIXTURE);
  await page.settle();
  assert.equal(renderedRows(page.main).length, FIXTURE.residents.length);
});

test('failed refresh marks retained rows stale, but authorization denial removes prior records', async () => {
  const page = harness({responses: [FIXTURE, {errorStatus: 503}, {errorStatus: 403}]});
  await page.settle();
  await page.tick();
  assert.equal(renderedRows(page.main).length, FIXTURE.residents.length);
  assert.match(page.main.querySelector('[data-unit=freshness]').textContent, /out of date/);
  await page.tick();
  assert.equal(renderedRows(page.main).length, 0);
  assert.equal(page.main.querySelector('[data-unit=priority]').children.length, 0);
  assert.equal(page.main.querySelector('[data-unit=roster]').hidden, true);
  assert.equal(page.main.querySelector('[data-unit=count-total]').textContent, '—');
});

test('an empty authorized response is explicit and can recover on the next refresh', async () => {
  const page = harness({responses: [{...FIXTURE, residents: []}, FIXTURE]});
  await page.settle();
  assert.equal(page.main.querySelector('[data-unit=empty]').hidden, false);
  assert.equal(page.main.querySelector('[data-unit=count-total]').textContent, '0');
  assert.equal(page.main.querySelector('[data-unit=roster]').hidden, true);
  await page.tick();
  assert.equal(page.main.querySelector('[data-unit=empty]').hidden, true);
  assert.equal(page.main.querySelector('[data-unit=roster]').hidden, false);
});

test('polls every 10 s while visible, stops when hidden and resumes when visible', async () => {
  const page = harness();
  await page.settle();
  assert.equal(page.constant('POLL_MS'), 10000);
  assert.equal(page.watchlistCalls(), 1);
  assert.deepEqual([...page.intervals.values()].map((i) => i.ms), [10000]);
  await page.tick();
  assert.equal(page.watchlistCalls(), 2);

  await page.setVisibility('hidden');
  assert.equal(page.intervals.size, 0, 'no polling timer while the tab is hidden');
  await page.tick();
  assert.equal(page.watchlistCalls(), 2, 'no requests while hidden');

  await page.setVisibility('visible');
  assert.equal(page.watchlistCalls(), 3, 'refreshes immediately on becoming visible');
  assert.deepEqual([...page.intervals.values()].map((i) => i.ms), [10000]);
  await page.tick();
  assert.equal(page.watchlistCalls(), 4);
  assert.equal(page.listenerCount(), 1);
});

test('a page opened in a background tab loads once and does not poll until visible', async () => {
  const page = harness({visible: false});
  await page.settle();
  assert.equal(page.watchlistCalls(), 1);
  assert.equal(page.intervals.size, 0);
  assert.equal(renderedRows(page.main).length, FIXTURE.residents.length);
  await page.setVisibility('visible');
  assert.equal(page.watchlistCalls(), 2);
  assert.deepEqual([...page.intervals.values()].map((i) => i.ms), [10000]);
});


test('search finds stable residents in a large roster without sorting or changing unit totals', async () => {
  const data = structuredClone(FIXTURE);
  data.residents = Array.from({length: 64}, (_, index) => ({...FIXTURE.residents[0],
    patient_id: `ward-${index}`, display_name: `Resident ${String(index).padStart(2, '0')}`,
    latest_verdict: index % 4 ? 'within_normal' : 'watch'})).reverse();
  const page = harness({responses: [data]});
  await page.settle();
  const search = page.main.querySelector('[data-unit=search]');
  search.value = '  RESIDENT 1  ';
  search.listeners.input[0]();
  const expected = data.residents.filter((row) => row.display_name.includes('Resident 1'));
  assert.deepEqual(renderedRows(page.main).map((row) => row.href),
    expected.map((row) => `/resident/${row.patient_id}`));
  assert.equal(expected.length, 10);
  assert.equal(page.main.querySelector('[data-unit=count-total]').textContent, '64');
  assert.equal(page.main.querySelector('[data-unit=count-watch]').textContent, '16');
  assert.equal(page.main.querySelector('[data-unit=roster]').open, true);
  assert.match(page.main.querySelector('[data-unit=search-status]').textContent, /10 of 64/);
  assert.equal(page.watchlistCalls(), 1);
  search.value = '';
  search.listeners.input[0]();
  assert.equal(renderedRows(page.main).length, 64);
});

test('reference search persists over polling and has a distinct no-match state', async () => {
  const first = structuredClone(FIXTURE), next = structuredClone(FIXTURE);
  const target = first.residents[0];
  next.residents = next.residents.filter((row) => row.patient_id !== target.patient_id);
  const page = harness({responses: [first, next], patients: [
    {id: target.patient_id, reference: 'WARD-REFERENCE-42'}]});
  await page.settle();
  const search = page.main.querySelector('[data-unit=search]');
  search.value = 'reference-42'; search.listeners.input[0]();
  assert.equal(renderedRows(page.main).length, 1);
  await page.tick();
  assert.equal(search.value, 'reference-42');
  assert.equal(renderedRows(page.main).length, 0);
  assert.equal(page.main.querySelector('[data-unit=no-match]').hidden, false);
  assert.equal(page.main.querySelector('[data-unit=empty]').hidden, true);
});

test('authorization denial clears the searchable snapshot so typing cannot restore old residents', async () => {
  const page = harness({responses: [FIXTURE, {errorStatus: 403}]});
  await page.settle();
  await page.tick();
  const search = page.main.querySelector('[data-unit=search]');
  search.value = FIXTURE.residents[0].display_name; search.listeners.input[0]();
  assert.equal(renderedRows(page.main).length, 0);
  assert.match(page.main.querySelector('[data-unit=search-status]').textContent, /Load the overview/);
});
