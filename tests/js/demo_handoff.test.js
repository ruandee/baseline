'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {loadPage, until, tick} = require('./harness');
const q = (p, s) => p.main.querySelector(s);
const url = '/check?demo=archived-handoff&resident=runner#room=room1&key=runner-key';
function exit(page) { page.window.listeners.pagehide.forEach(fn => fn()); }
async function record(page) {
  q(page, '.bl-handoff-record').click();
  await until(() => q(page, '.bl-handoff-record').textContent === 'Stop recording');
  q(page, '.bl-handoff-record').click();
  await until(() => !q(page, '.bl-handoff-submit').disabled);
}

test('denied microphone never sends a check-in or requests clinical bootstrap', async () => {
  const page = loadPage(url, {mic: 'denied'});
  q(page, '.bl-handoff-record').click();
  await until(() => page.main.textContent.includes('Could not record'));
  assert(q(page, '.bl-handoff-submit').disabled);
  assert.equal(page.calls.length, 0);
  exit(page);
});

test('late microphone permission after leaving stops tracks without recording', async () => {
  const page = loadPage(url);
  let allow, stops = 0;
  page.window.navigator.mediaDevices.getUserMedia = () => new Promise(r => { allow = r; });
  q(page, '.bl-handoff-record').click();
  exit(page);
  allow({getTracks: () => [{stop() { stops++; }}]});
  await tick();
  assert.equal(stops, 1);
  assert.equal(page.calls.length, 0);
  assert(q(page, '.bl-handoff-submit').disabled);
});

test('retry retains the same receipt ID, sends metadata only and clears audio on success', async () => {
  let attempts = 0;
  const page = loadPage(url, {routes: {'POST /demo/handoff/room1/checks': () => {
    if (++attempts === 1) throw {status: 503};
    return {accepted: true, remaining_checks: 0};
  }}});
  await record(page);
  q(page, '.bl-handoff-submit').click();
  await until(() => page.main.textContent.includes('Connection failed'));
  assert(q(page, 'audio'));
  q(page, '.bl-handoff-submit').click();
  await until(() => page.main.textContent.includes('received by the nurse'));
  assert.equal(page.calls.length, 2);
  const [one, two] = page.calls;
  assert.equal(one.opts.body, two.opts.body);
  assert.equal(one.opts.headers.Authorization, 'Bearer runner-key');
  const body = JSON.parse(one.opts.body);
  assert.deepEqual(Object.keys(body).sort(), ['duration_s', 'request_id']);
  assert(body.duration_s > 0 && body.duration_s <= 30);
  assert.equal(q(page, 'audio'), null);
  assert(q(page, '.bl-handoff-record').disabled);
  assert.equal(page.window.stored.size, 0);
  exit(page);
});

test('a dropped network shows the friendly retry message, not the browser error', async () => {
  const page = loadPage(url);
  await record(page);
  page.window.fetch = async () => { throw new TypeError('Failed to fetch'); };
  q(page, '.bl-handoff-submit').click();
  await until(() => page.main.textContent.includes('Connection failed'));
  assert(!page.main.textContent.includes('Failed to fetch'));
  assert(q(page, 'audio'));
  assert(!q(page, '.bl-handoff-submit').disabled);
  exit(page);
});

test('nurse receives runner and must explicitly apply context to explain it', async () => {
  let revision = 1;
  const data = () => ({revision, exertion: revision === 2, capture_keys: {runner: 'r', resident: 'd'},
    checks: [{resident: 'runner', take: 1, received_at: '2026-10-18T03:00:00Z',
      verdict: revision === 2 ? 'explained' : 'watch'}]});
  const page = loadPage('/unit?demo=archived-handoff#room=room1&key=nurse-key', {routes: {
    'GET /demo/handoff/room1': data,
    'POST /demo/handoff/room1/context': () => { revision = 2; return data(); },
  }});
  await until(() => page.main.textContent.includes('Apply context and reassess'));
  assert(page.main.textContent.includes('Watch'));
  const card = q(page, '[data-resident=runner]');
  card.querySelector('button').click();
  await until(() => page.main.textContent.includes('Explained'));
  const post = page.calls.find(c => c.key.endsWith('/context'));
  assert.equal(post.opts.body, '{"tag":"exertion"}');
  assert.equal(post.opts.headers.Authorization, 'Bearer nurse-key');
  assert(!page.calls.some(c => c.key.includes('/v1/') || c.key.includes('/demo/session')));
  exit(page);
});

test('nurse screen says Reconnecting on a dropped network and recovers, without phone wording', async () => {
  const data = {revision: 1, exertion: false, capture_keys: {runner: 'r', resident: 'd'},
    checks: [{resident: 'runner', take: 1, received_at: '2026-10-18T03:00:00Z', verdict: 'watch'}]};
  const page = loadPage('/unit?demo=archived-handoff#room=room1&key=nurse-key', {routes: {
    'GET /demo/handoff/room1': () => data,
    'POST /demo/handoff/room1/context': () => data,
  }});
  await until(() => page.main.textContent.includes('Connected'));
  const working = page.window.fetch;
  page.window.fetch = async () => { throw new TypeError('Failed to fetch'); };
  await until(() => page.main.textContent.includes('Reconnecting'), 5000);
  assert(!page.main.textContent.includes('Failed to fetch'));
  assert(!page.main.textContent.includes('check-in will not be duplicated'));
  // A dropped network while applying context gets nurse wording, not the phone's retry text.
  q(page, '[data-resident=runner]').querySelector('button').click();
  await until(() => page.main.textContent.includes('Connection failed. Try again.'));
  assert(!page.main.textContent.includes('check-in will not be duplicated'));
  page.window.fetch = working;
  await until(() => page.main.textContent.includes('Connected'), 5000);
  exit(page);
});

test('expired nurse room removes stale findings and offers fresh setup', async () => {
  const page = loadPage('/unit?demo=archived-handoff#room=gone&key=old', {routes: {}});
  await until(() => page.main.textContent.includes('Start a new demo room'));
  assert(!page.main.textContent.includes('Run 4AT now'));
  assert.equal(page.calls.length, 1);
  exit(page);
});
