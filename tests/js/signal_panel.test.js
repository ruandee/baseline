const {test} = require('node:test');
const assert = require('node:assert/strict');
const {loadPage, until} = require('./harness');
const data = () => ({latest_assessment: {id: 'a1', corroborated: true, modalities: {
  vitals: {status: 'change', ts: '2026-10-17T12:00:00Z', current: true, evidence_ids: ['fact1'],
    per_feature: {resting_rr_bpm: {value: 26}}, params: {threshold_status: 'engineering_unvalidated',
      feature_meta: {resting_rr_bpm: {label: 'Resting respiratory rate', unit: 'breaths/min'},
        resting_hr_bpm: {label: 'Resting heart rate', unit: 'beats/min'}}, unavailable_features: ['resting_hr_bpm']}}}}});

async function panel(changed = false) {
  const page = loadPage('/check?mode=live&mock=1');
  await until(() => page.main.querySelector('.bl-record'));
  const calls = [];
  const h = {el: page.ctx.el, formatTime: (value) => value, api: async (path) => {
    calls.push(path);
    if (path.includes('/overview')) return changed ? {latest_assessment: null} : data();
    return {source_kind: 'observation', author_role: 'system', recorded_at: '2026-10-17T12:01:00Z',
      quote: 'resting_rr_bpm: 26.0 breaths/min'};
  }};
  const section = page.window.signalPanel(h, {id: 'p1'}, data());
  page.main.replaceChildren(section);
  return {section, calls};
}

test('nurse sees exact RR, unknown HR, measurement time and unvalidated provenance', async () => {
  const {section, calls} = await panel();
  assert.match(section.textContent, /Resting respiratory rate: 26 breaths\/min/);
  assert.match(section.textContent, /Resting heart rate: unavailable/);
  assert.match(section.textContent, /Corroborated by current/);
  assert.match(section.textContent, /clinical validation has not been performed/);
  section.querySelector('.bl-signal-source').click();
  await until(() => section.querySelector('.bl-source-quote'));
  assert.equal(section.querySelector('.bl-source-quote').textContent, 'resting_rr_bpm: 26.0 breaths/min');
  assert.equal(calls.length, 2);
});

test('assessment invalidation withholds source readback rather than opening stale values', async () => {
  const {section, calls} = await panel(true);
  section.querySelector('.bl-signal-source').click();
  await until(() => !section.querySelector('.bl-signal-source').disabled);
  assert.match(section.textContent, /Assessment changed/);
  assert.equal(section.querySelector('.bl-source-quote'), null);
  assert.equal(calls.length, 1);
});
