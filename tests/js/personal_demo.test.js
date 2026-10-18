'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {loadPage, until, FakeRecorder} = require('./harness');

const people = [{id: 'volunteer', name: 'Volunteer', capture_mode: 'live', scripted_cohort: false}];
const url = '/check?mode=live&demo=personal&enroll=1&patient=volunteer&device=demo-phone';
const posts = (page) => page.calls.filter((c) => c.key === 'POST /v1/patients/volunteer/checks');
const namedButton = (page, text) => page.main.querySelectorAll('button').find((b) => b.textContent === text);

test('personal recording adapts the single shared disclosure to measured volunteer checks', async () => {
  const page = loadPage(url, {patients: people});
  await until(() => page.main.querySelector('.bl-record'));
  const disclosure = page.doc.getElementById('nav-disclosure');
  assert.equal(disclosure.querySelector('summary').textContent, 'Live volunteer demo');
  assert(disclosure.textContent.includes('real voice analysis'));
  assert(disclosure.textContent.includes('personal baseline is unavailable'));
  assert.equal(page.doc.querySelectorAll('details').filter((node) => node.id === 'nav-disclosure').length, 1);
});

test('ordinary recording retains the teammate disclosure', async () => {
  const page = loadPage('/check?mode=live&patient=volunteer', {patients: people});
  await until(() => page.main.querySelector('.bl-record'));
  const disclosure = page.doc.getElementById('nav-disclosure');
  assert.equal(disclosure.querySelector('summary').textContent, 'Demo scenario');
  assert(disclosure.textContent.includes('Fictional residents and separate live volunteer records'));
});

test('personal nurse screen shows actual overview and a patient-scoped phone link without recording', async () => {
  const page = loadPage('/unit?demo=personal', {patients: people, routes: {
    'GET /v1/patients/volunteer/overview?days=30': () => ({latest_assessment: {
      ts: '2026-10-18T12:00:00Z', verdict: 'within_normal', modality: 'speech',
      change: {status: 'none', params: {baseline_checks: 5}, per_feature: {}},
    }}),
  }});
  try {
    await until(() => page.main.textContent.includes('5 eligible prior baseline checks used'));
    const disclosure = page.doc.getElementById('nav-disclosure');
    assert.equal(disclosure.querySelector('summary').textContent, 'Live volunteer demo');
    assert(disclosure.textContent.includes('Other residents and records are fictional'));
    assert(page.main.textContent.includes('Within normal'));
    assert(!page.main.textContent.includes('No data'));
    assert(page.main.querySelectorAll('a').some((a) => a.href === '/check?mode=resident&demo=personal&patient=volunteer'));
    assert(page.main.querySelectorAll('a').some((a) => a.href.includes('mode=live&demo=personal&enroll=1')));
    assert.equal(page.window.mediaCalls, 0);
    assert(!page.calls.some((c) => c.key.startsWith('POST ') || c.key.includes('/demo/handoff')));
  } finally { vm.runInContext('if (state.unitStop) state.unitStop()', page.ctx); }
});

test('old demo entry URLs lead to measured mode and discard old room credentials', () => {
  for (const path of ['/unit?demo=handoff#room=old&key=old', '/unit?demo=days', '/check?mode=live&demo=legacy-days']) {
    const page = loadPage(path);
    assert.equal(page.window.location.replaced, path.startsWith('/unit')
      ? '/unit?demo=personal' : '/check?mode=resident&demo=personal');
    assert.equal(page.calls.length, 0);
    assert.equal(page.window.mediaCalls, 0);
  }
});

test('existing personal phone links open the care-aide flow while preserving target and device', () => {
  const page = loadPage('/check?mode=live&demo=personal&patient=volunteer&device=same-phone');
  assert.equal(page.window.location.replaced,
    '/check?mode=resident&demo=personal&patient=volunteer&device=same-phone');
  assert.equal(page.calls.length, 0);
  assert.equal(page.window.mediaCalls, 0);
});

test('care-aide demo records as PSW against the live baseline device and offers a fresh repeat', async () => {
  const page = loadPage('/check?mode=resident&demo=personal', {patients: people, routes: {
    'POST /v1/patients/volunteer/checks': () => ({usable: true, assessment: {verdict: 'watch'},
      features: {speech_rate_wpm: 42}, change: {status: 'change'}}),
  }});
  await until(() => page.main.querySelector('.bl-record') && !page.main.querySelector('.bl-record').disabled);
  page.window.stored.set('bl-device-id-live', 'original-baseline-phone');
  page.main.querySelector('.bl-record').click();
  await until(() => FakeRecorder.last && FakeRecorder.last.state === 'recording');
  page.main.querySelector('.bl-record').click();
  await until(() => page.main.querySelector('[data-demo-repeat]')?.hidden === false);
  const sent = posts(page);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].opts.headers.Authorization, 'Bearer psw-t');
  assert.equal(sent[0].opts.body.get('mode'), 'resident');
  assert.equal(sent[0].opts.body.get('device_id'), 'original-baseline-phone');
  assert.equal(sent[0].opts.body.get('is_baseline'), 'false');
  assert.equal(page.main.querySelector('[data-demo-repeat]').href,
    '/check?mode=resident&patient=volunteer&demo=personal');
  assert(page.main.textContent.includes('Thank you'));
  assert(!page.main.textContent.includes('Watch'));
  assert(!page.main.textContent.includes('Speech rate'));
  assert(!page.calls.some((c) => c.key.includes('/overview') || c.key.includes('/consent?')));
  assert.equal(page.main.querySelector('.bl-back').href, '/check?mode=resident');
});

test('care-aide demo refuses fictional, missing and mock targets before recording', async () => {
  for (const [suffix, patients] of [
    ['', []], ['', [{...people[0], scripted_cohort: true}]], ['&mock=1', people],
    ['&patient=someone-else', people],
  ]) {
    const page = loadPage('/check?mode=resident&demo=personal' + suffix, {patients});
    await until(() => page.main.textContent.includes('Voice check unavailable'));
    assert.equal(page.main.querySelector('.bl-record'), null);
    assert.equal(page.window.mediaCalls, 0);
    assert.equal(posts(page).length, 0);
  }
});

test('care-aide demo never resends a recording after an ambiguous upload', async () => {
  const page = loadPage('/check?mode=resident&demo=personal', {patients: people, routes: {
    'POST /v1/patients/volunteer/checks': () => { throw {status: 503}; },
  }});
  await until(() => page.main.querySelector('.bl-record') && !page.main.querySelector('.bl-record').disabled);
  page.main.querySelector('.bl-record').click();
  await until(() => FakeRecorder.last?.state === 'recording');
  page.main.querySelector('.bl-record').click();
  await until(() => page.main.textContent.includes('check whether this recording was saved'));
  assert.equal(posts(page).length, 1);
  assert(page.main.querySelector('.bl-retry').hidden);
  assert(page.main.querySelector('[data-demo-repeat]').hidden);
});

test('missing volunteer never falls back to a scripted resident', async () => {
  const page = loadPage('/unit?demo=personal', {patients: [{id: 'fictional', name: 'Fictional', scripted_cohort: true}]});
  await until(() => page.main.textContent.includes('No live volunteer record'));
  assert(!page.calls.some((c) => c.key.includes('/v1/patients/')));
});

test('nurse read failure clears an earlier measured result and retains a retry control', async () => {
  let fail = false;
  const page = loadPage('/unit?demo=personal', {patients: people, routes: {
    'GET /v1/patients/volunteer/overview?days=30': () => {
      if (fail) throw {status: 404};
      return {latest_assessment: {verdict: 'watch', ts: '2026-10-18T12:00:00Z',
        change: {status: 'provisional', params: {baseline_checks: 5}, per_feature: {}}}};
    },
  }});
  try {
    await until(() => page.main.textContent.includes('5 eligible prior baseline checks used'));
    fail = true;
    namedButton(page, 'Refresh result').click();
    await until(() => page.main.textContent.includes('current result is unavailable'));
    assert(!page.main.textContent.includes('5 eligible prior baseline checks used'));
    assert(!namedButton(page, 'Refresh result').disabled);
  } finally { vm.runInContext('if (state.unitStop) state.unitStop()', page.ctx); }
});

test('nurse polls every two seconds while visible and stops polling while hidden', async () => {
  const page = loadPage('/unit?demo=personal', {patients: people, routes: {
    'GET /v1/patients/volunteer/overview?days=30': () => ({latest_assessment: null}),
  }});
  const timers = new Map();
  page.window.setInterval = (fn, ms) => { const id = {}; timers.set(id, {fn, ms}); return id; };
  page.window.clearInterval = (id) => timers.delete(id);
  try {
    await until(() => timers.size === 1);
    assert.equal([...timers.values()][0].ms, 2000);
    page.doc.visibilityState = 'hidden';
    page.doc.listeners.visibilitychange.forEach((fn) => fn());
    assert.equal(timers.size, 0);
    page.doc.visibilityState = 'visible';
    page.doc.listeners.visibilitychange.forEach((fn) => fn());
    assert.equal(timers.size, 1);
  } finally { vm.runInContext('if (state.unitStop) state.unitStop()', page.ctx); }
});

async function record(page, expected) {
  const button = page.main.querySelector('.bl-record');
  button.click();
  await until(() => FakeRecorder.last?.state === 'recording');
  assert(namedButton(page, 'Start check-ins').disabled);
  button.click();
  await until(() => posts(page).length === expected && !button.disabled);
}

test('personal demo enrolls distinct fresh takes then repeats live checks with the same identity/device', async () => {
  const page = loadPage(url, {patients: people, routes: {
    'POST /v1/patients/volunteer/checks': () => ({usable: false, quality: {reasons: ['too_short']}}),
  }});
  await until(() => page.main.querySelector('.bl-record') && !page.main.querySelector('.bl-record').disabled);
  namedButton(page, 'Enroll rested baseline').click();
  await record(page, 1);
  await record(page, 2);
  assert.equal(posts(page)[0].opts.body.get('is_baseline'), 'true');
  assert.equal(posts(page)[1].opts.body.get('is_baseline'), 'true');
  assert(page.main.textContent.includes('0 usable rested takes saved this visit'));
  namedButton(page, 'Start check-ins').click();
  await record(page, 3);
  await record(page, 4);
  assert.equal(posts(page)[2].opts.body.get('is_baseline'), 'false');
  assert.equal(posts(page)[3].opts.body.get('is_baseline'), 'false');
  assert.equal(page.window.mediaCalls, 4);
  for (const post of posts(page)) {
    assert.equal(post.opts.body.get('device_id'), 'demo-phone');
    assert.equal(post.opts.body.get('mode'), 'live');
    assert.equal(post.opts.body.get('profile_version'), 'profile-volunteer');
  }
});

test('personal demo cannot enroll a scripted resident', async () => {
  const page = loadPage(url, {patients: [{...people[0], scripted_cohort: true}]});
  await until(() => page.main.textContent.includes('dedicated live volunteer'));
  assert(page.main.querySelector('.bl-record').disabled);
  assert.equal(page.window.mediaCalls, 0);
  assert.equal(posts(page).length, 0);
  assert.equal(page.doc.getElementById('nav-disclosure').querySelector('summary').textContent, 'Demo scenario');
});

test('personal demo refuses mock outcomes instead of labelling them measured', async () => {
  const page = loadPage(url + '&mock=1', {patients: people});
  await until(() => page.main.textContent.includes('mock mode is unavailable'));
  assert(page.main.querySelector('.bl-record').disabled);
  assert.equal(page.window.mediaCalls, 0);
  assert.equal(posts(page).length, 0);
});

test('personal enrollment counts only successful usable baseline receipts', async () => {
  const page = loadPage(url, {patients: people, routes: {
    'POST /v1/patients/volunteer/checks': () => ({usable: true, quality: {reasons: []},
      words: [], pauses: [], features: {}, change: {status: 'enrolling', params: {baseline_checks: 0}},
      assessment: {verdict: 'enrolling'}}),
  }});
  await until(() => page.main.querySelector('.bl-record') && !page.main.querySelector('.bl-record').disabled);
  namedButton(page, 'Enroll rested baseline').click();
  await record(page, 1);
  assert(page.main.textContent.includes('1 usable rested takes saved this visit'));
  assert.equal(page.main.querySelector('.bl-record').textContent, 'Record next rested take');
  namedButton(page, 'Start check-ins').click();
  await record(page, 2);
  assert.equal(page.main.querySelector('.bl-record').textContent, 'Record another demo check');
  assert.equal(posts(page)[1].opts.body.get('is_baseline'), 'false');
});

test('personal demo keeps consent admission and never automatically resends an ambiguous upload', async () => {
  const blocked = loadPage(url, {patients: people, consent: {volunteer: 'withdrawn'}});
  await until(() => blocked.main.textContent.includes('Recording blocked'));
  assert(blocked.main.querySelector('.bl-record').disabled);
  assert.equal(blocked.window.mediaCalls, 0);
  const page = loadPage(url, {patients: people, routes: {
    'POST /v1/patients/volunteer/checks': () => { throw {status: 503}; },
  }});
  await until(() => page.main.querySelector('.bl-record') && !page.main.querySelector('.bl-record').disabled);
  await record(page, 1);
  assert(page.main.textContent.includes('server may have saved this check'));
  assert(page.main.querySelector('.bl-retry').hidden);
  assert.equal(posts(page).length, 1);
});
