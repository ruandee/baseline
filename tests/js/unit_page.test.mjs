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

function harness({visible = true, responses = [FIXTURE]} = {}) {
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
      return {ok: true, status: 200, json: async () => ({token: 'synthetic-token', patients: []})};
    }
    if (path === '/v1/watchlist') {
      const body = responses[Math.min(served, responses.length - 1)];
      served += 1;
      return {ok: true, status: 200, json: async () => structuredClone(body)};
    }
    return {ok: false, status: 404, json: async () => ({})};
  };
  const context = vm.createContext({
    document, fetch, console, location: {pathname: '/unit'},
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
    const expected = resident.latest_verdict === null ? 'No data'
      : resident.latest_verdict === 'escalate' && resident.over_budget ? 'Escalate (over budget)'
        : labels[resident.latest_verdict];
    assert.ok(expected, `no label for verdict ${resident.latest_verdict}`);
    assert.equal(rows[i].verdict, expected);
    assert.equal(rows[i].fused, typeof resident.fused_z === 'number'
      ? resident.fused_z.toFixed(1) : '—');
    assert.equal(rows[i].synthetic, resident.synthetic === true);
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
