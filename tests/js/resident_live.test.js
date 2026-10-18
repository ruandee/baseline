'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const {readFileSync} = require('node:fs');
const {loadPage, until} = require('./harness');

test('live resident route: charts, actual evidence, action, editable preliminary export', async () => {
  const captured = process.env.RESIDENT_LIVE_FIXTURE
    ? JSON.parse(readFileSync(process.env.RESIDENT_LIVE_FIXTURE, 'utf8')) : null;
  let page;
  const pid = captured ? captured.overview.patient_id : 'mrs-k';
  const overview = () => captured ? captured.overview : page.window.RESIDENT_FIXTURES['mrs-k'];
  const evidence = captured ? captured.evidence : null;
  let readback = 'current';
  const note = captured ? captured.note : {resourceType: 'DocumentReference', id: 'note',
    meta: {tag: []}, identifier: [{system: 'urn:baseline:assessment', value: 'asm-1'}],
    status: 'current', docStatus: 'preliminary', subject: {reference: `Patient/${pid}`},
    content: [{attachment: {contentType: 'text/plain', data: btoa('S: Synthetic original draft')}}]};
  const routes = {
    [`GET /v1/patients/${pid}/overview?days=30`]: () => {
      if (readback === 'revoked') throw {status: 404};
      const data = overview();
      if (readback === 'check-changed') return {...data,
        latest_assessment: {...data.latest_assessment, check: {...data.latest_assessment.check, id: 'other-check'}}};
      return readback === 'changed'
        ? {...data, latest_assessment: {...data.latest_assessment, id: 'new-assessment'}} : data;
    },
  };
  // API handlers intentionally serve the same payload whether captured from real DB or offline.
  const allEvidence = evidence || Object.fromEntries(['1', '2', '3'].map((n) => [
    `00000000-0000-4000-8000-00000000000${n}`, null]));
  Object.keys(allEvidence).forEach((id) => {
    routes[`GET /v1/patients/${pid}/evidence/${id}`] = () => evidence ? evidence[id]
      : page.window.RESIDENT_FIXTURE_EVIDENCE[id];
  });
  routes[`GET /v1/patients/${pid}/assessments/${captured ? captured.overview.latest_assessment.id : 'asm-1'}/note`] = () => note;
  page = loadPage(`/resident/${pid}`, {routes, patients: [{id: pid, name: 'Mrs. K'}]});
  await until(() => page.main.querySelector('.bl-parameters'));
  assert.equal(page.main.querySelectorAll('.bl-chart').length, 4);
  assert.equal(page.main.querySelectorAll('.bl-band').length, 4);
  assert.equal(page.main.querySelectorAll('.bl-marker').length, 4);
  assert(!page.main.textContent.includes('[object Object]'));
  assert.match(page.main.querySelector('.bl-parameters').textContent, /z_threshold/);
  const action = page.main.querySelector('.bl-action');
  assert.equal(action.tagName, 'BUTTON');
  assert.equal(action.textContent, overview().latest_assessment.suggested_action.label);
  action.click();
  assert.equal(action.getAttribute('aria-expanded'), 'true');
  assert.equal(page.main.querySelector('.bl-action-detail').hidden, false);
  assert.match(page.main.textContent, /37.1/);
  const references = page.main.querySelectorAll('[data-evidence-id]');
  assert(references.length > 5);
  assert(page.main.querySelectorAll('.bl-cite').every((node) => node.tagName === 'BUTTON'));
  for (const reference of references) {
    const id = reference.getAttribute('data-evidence-id');
    const before = page.calls.length;
    reference.click();
    if (id.startsWith('check:')) {
      await until(() => page.main.querySelector('.bl-check-evidence'));
      const detail = page.main.querySelector('.bl-check-evidence').textContent;
      assert.match(detail, /Stored voice check/);
      assert.match(detail, /Authored synthetic measurements; no audio or source-document quote/);
      assert.match(detail, new RegExp(String(Math.round(overview().latest_assessment.change.per_feature.speech_rate_wpm.value))));
      assert(page.calls.slice(before).some((call) => call.key.endsWith('/overview?days=30')));
      assert(!page.calls.slice(before).some((call) => call.key.includes('/evidence/check')));
    } else {
      const expected = evidence ? evidence[id] : page.window.RESIDENT_FIXTURE_EVIDENCE[id];
      await until(() => page.main.querySelectorAll('.bl-source-quote').some((node) => node.textContent === expected.quote));
      assert(page.calls.slice(before).some((call) => call.key.endsWith(`/evidence/${id}`)));
    }
  }
  const send = page.main.querySelectorAll('button').find((n) => n.textContent === 'Send to sign-off queue (preview)');
  send.click();
  await until(() => page.main.querySelector('.bl-note-editor'));
  assert.equal(page.main.querySelector('.bl-note-text').textContent,
    Buffer.from(note.content[0].attachment.data, 'base64').toString('utf8'));
  page.main.querySelector('.bl-note-editor').value = 'S: Human draft <review required>';
  page.main.querySelector('.bl-edit-preview').click();
  await until(() => page.main.querySelector('.bl-human-note-json'));
  assert.match(page.main.textContent, /Human-edited, unverified/);
  assert(page.calls.every((c) => c.key.startsWith('GET ')));
  assert(page.calls.some((c) => c.key.includes('/overview?days=30')));
  for (const state of ['changed', 'check-changed', 'revoked']) {
    readback = state;
    page.main.querySelector('.bl-check-cite').click();
    await until(() => !page.main.querySelector('.bl-check-evidence')
      && page.main.textContent.includes('Could not open the voice check'));
    assert.match(page.main.textContent, state === 'revoked' ? /404/ : /reload the resident/);
  }
  assert.equal(page.errors.length, 0);
});
