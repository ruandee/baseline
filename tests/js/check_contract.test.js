const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {loadPage, until} = require('./harness.js');
const response = process.env.CHECK_RESPONSE_FIXTURE
  ? JSON.parse(fs.readFileSync(process.env.CHECK_RESPONSE_FIXTURE, 'utf8'))
  : {usable: true, quality: {duration_s: 10, reasons: []}, words: [], pauses: [],
    features: {}, timings_ms: {asr: 7, engine: 12, verdict: 25},
    change: {status: 'enrolling', params: {baseline_checks: 2, min_baseline: 3}},
    assessment: {verdict: 'enrolling', reasons: []}};

test('live check renders actual engine enrollment metadata and measured timing fields', async () => {
  const h = loadPage('/check?mode=live&patient=p1', {routes: {
    'POST /v1/patients/p1/checks': () => response}});
  await until(() => h.main.querySelector('.bl-record'));
  h.main.querySelector('.bl-record').click();
  await new Promise((resolve) => setTimeout(resolve, 20));
  h.main.querySelector('.bl-record').click();
  await until(() => h.main.querySelector('.bl-features'));
  const params = response.change.params;
  if (response.change.status === 'enrolling') {
    assert.match(h.main.textContent, new RegExp(
      `building baseline ${params.baseline_checks} of ${params.min_baseline} eligible prior checks`));
  } else {
    assert.doesNotMatch(h.main.textContent, /building baseline/);
  }
  const timing = h.main.querySelector('.bl-timings').textContent;
  assert.match(timing, /engine 12 ms/); assert.match(timing, /verdict 25 ms/);
  assert.match(timing, /asr 7 ms/);
});
