'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {loadPage, until, FakeRecorder} = require('./harness');

const people = [{id: 'volunteer', name: 'Volunteer', capture_mode: 'live', scripted_cohort: false}];
const url = '/check?mode=live&demo=personal&patient=volunteer&device=demo-phone';
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
  assert(disclosure.textContent.includes('authored for this demo'));
});

test('personal nurse overview adapts the disclosure while keeping genuine watchlist polling', async () => {
  const page = loadPage('/unit?demo=personal', {patients: people, routes: {
    'GET /v1/watchlist': () => ({shift: {}, residents: []}),
  }});
  try {
    await until(() => page.calls.some((c) => c.key === 'GET /v1/watchlist'));
    const disclosure = page.doc.getElementById('nav-disclosure');
    assert.equal(disclosure.querySelector('summary').textContent, 'Live volunteer demo');
    assert(disclosure.textContent.includes('Other residents and records are fictional'));
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
