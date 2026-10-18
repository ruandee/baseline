'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {loadPage, until} = require('./harness');

function pageFor({enabled = true, fail = false} = {}) {
  let page, saved = false;
  page = loadPage('/resident/mrs-l', {patients: [{id: 'mrs-l', name: 'Mrs. L', can_add_demo_context: enabled}], routes: {
    'GET /v1/patients/mrs-l/overview?days=30': () => {
      const fixture = page.window.RESIDENT_FIXTURES['mrs-k'];
      return {...fixture, display_name: 'Mrs. L', latest_assessment: {...fixture.latest_assessment,
        verdict: saved ? 'explained' : 'watch'}};
    },
    'POST /demo/residents/mrs-l/context': () => {
      if (fail) throw {status: 409};
      saved = true; return {verdict: 'explained'};
    },
  }});
  return page;
}

async function fill(page) {
  await until(() => page.main.querySelector('[data-explain=panel]'));
  const panel = page.main.querySelector('[data-explain=panel]');
  const select = panel.querySelector('select');
  select.value = 'dentures'; select.dispatchEvent({type: 'change'});
  const note = panel.querySelector('textarea');
  note.value = 'Synthetic observation: loose dentures noted during this check.';
  note.dispatchEvent({type: 'input'});
  const checkbox = panel.querySelector('input');
  const confirm = panel.querySelectorAll('input').find((input) => input.getAttribute('type') === 'checkbox');
  assert(checkbox);
  const button = panel.querySelector('button');
  assert(button.disabled, 'observation is not auto-confirmed');
  confirm.checked = true; confirm.dispatchEvent({type: 'change'});
  assert(!button.disabled);
  return button;
}

test('Mrs. L context requires an explicit observation and confirmation, then reloads actual verdict', async () => {
  const page = pageFor();
  const button = await fill(page);
  assert(!page.calls.some((call) => call.key.startsWith('POST ')));
  button.click(); button.click();
  await until(() => page.main.textContent.includes('Context saved.'));
  const sent = page.calls.filter((call) => call.key === 'POST /demo/residents/mrs-l/context');
  assert.equal(sent.length, 1);
  const body = JSON.parse(sent[0].opts.body);
  assert.equal(body.kind, 'explainer'); assert.equal(body.tag, 'dentures');
  assert.equal(body.assessment_id, 'asm-1');
  assert(sent[0].opts.headers['Idempotency-Key']);
  assert.equal(page.main.querySelector('.bl-chip').textContent, 'Explained');
});

test('other residents have no demo explanation control', async () => {
  const page = pageFor({enabled: false});
  await until(() => page.main.querySelector('.bl-card'));
  assert.equal(page.main.querySelector('[data-explain=panel]'), null);
});

test('stale assessment leaves the current verdict visible and asks for reload', async () => {
  const page = pageFor({fail: true});
  (await fill(page)).click();
  await until(() => page.main.textContent.includes('The assessment changed.'));
  assert.equal(page.main.querySelector('.bl-chip').textContent, 'Watch');
  assert(!page.main.textContent.includes('Context saved.'));
});
