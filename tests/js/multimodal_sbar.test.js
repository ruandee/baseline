'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const {readFileSync} = require('node:fs');
const {loadPage, until} = require('./harness');

test('multimodal draft opens actual current and baseline voice captures and clears expired evidence', async () => {
  const captured = process.env.MULTIMODAL_FIXTURE
    ? JSON.parse(readFileSync(process.env.MULTIMODAL_FIXTURE, 'utf8')) : null;
  let page, stale = false;
  const overview = () => {
    if (captured) return captured.overview;
    const data = structuredClone(page.window.RESIDENT_FIXTURES['mrs-k']);
    const latest = data.latest_assessment;
    latest.check = null;
    latest.draft_status = 'multimodal_template';
    latest.cited_checks = {
      'current-voice': {id: 'current-voice', ts: latest.ts, synthetic: true,
        features: {speech_rate_wpm: 123}},
      'baseline-voice': {id: 'baseline-voice', ts: latest.ts, synthetic: true,
        features: {speech_rate_wpm: 160}},
    };
    latest.sbar.sentences.forEach((sentence) => {
      sentence.evidence_ids = sentence.evidence_ids.map((id) => id.startsWith('check:') ? 'check:current-voice' : id);
    });
    latest.sbar.sentences[0].evidence_ids = ['check:current-voice', 'check:baseline-voice'];
    return data;
  };
  const pid = captured ? captured.overview.patient_id : 'mrs-k';
  const routes = {[`GET /v1/patients/${pid}/overview?days=30`]: () => {
    const data = overview();
    return stale ? {...data, latest_assessment: {...data.latest_assessment, sbar: null, cited_checks: {}}} : data;
  }};
  page = loadPage(`/resident/${pid}`, {routes, patients: [{id: pid, name: 'Synthetic'}]});
  await until(() => page.main.querySelector('.bl-check-cite'));
  const expected = overview().latest_assessment.cited_checks;
  const buttons = page.main.querySelectorAll('.bl-check-cite');
  assert(buttons.length >= 2);
  for (const button of buttons) {
    const cid = button.getAttribute('data-evidence-id').slice('check:'.length);
    button.click();
    await until(() => page.main.querySelector('.bl-check-evidence'));
    const text = page.main.querySelector('.bl-check-evidence').textContent;
    assert.match(text, /Stored voice check/);
    assert(text.includes(String(Math.round(expected[cid].features.speech_rate_wpm))));
  }
  assert(!page.calls.some((call) => call.key.includes('/evidence/check:')));
  stale = true;
  buttons[0].click();
  await until(() => page.main.textContent.includes('Check evidence changed or unavailable'));
  assert.equal(page.main.querySelector('.bl-check-evidence'), null);
});
