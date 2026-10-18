'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {loadPage, until, FakeRecorder, tick} = require('./harness');
const button = (h, name) => h.main.querySelectorAll('button').find(b => b.textContent === name);
const select = (h, label) => h.main.querySelectorAll('select').find(n => n.getAttribute('aria-label') === label);
const choose = (node, value) => node.children.forEach(n => {
  n.removeAttribute('selected'); if (n.getAttribute('value') === value) n.setAttribute('selected', '');
});
const confirm = (fieldset) => {
  const box = fieldset.querySelectorAll('input').find(n => n.getAttribute('type') === 'checkbox');
  box.checked = true; box.dispatchEvent({type: 'change'});
};

test('nurse explicitly configures profile and consent; unknown remains blocked until both saved', async () => {
  let profile = {state: 'unconfigured', preferred_locale: null, first_name: null, version: 'v0',
    can_configure: true, can_record_consent: true};
  let consent = {scope: 'voice_check', state: 'unknown'};
  const writes = [];
  const h = loadPage('/check?mode=live&patient=p1', {routes: {
    'GET /v1/patients/p1/check-profile': () => profile,
    'GET /v1/patients/p1/consent?scope=voice_check': () => consent,
    'PUT /v1/patients/p1/check-profile': opts => {
      const body = JSON.parse(opts.body); writes.push(body);
      profile = {...profile, ...body, state: body.preferred_locale === 'en' ? 'ready' : 'unsupported',
        protocol_locale: 'en', prompt_version: 'count20-days-v1', version: 'v1'}; return profile;
    },
    'POST /v1/patients/p1/consents': opts => {
      const body = JSON.parse(opts.body); writes.push(body); consent = {scope: 'voice_check', state: body.status}; return consent;
    }}});
  await until(() => button(h, 'Save counting profile'));
  assert.equal(button(h, 'Record').disabled, true);
  assert.equal(writes.length, 0);
  assert.equal(button(h, 'Record voice permission').disabled, true);
  const forms = h.main.querySelectorAll('fieldset');
  const inputs = forms[0].querySelectorAll('input');
  inputs.find(n => n.getAttribute('aria-label') === 'Explicit first name').value = 'Mary Ann';
  inputs.find(n => n.getAttribute('aria-label') === 'Preferred locale').value = 'en';
  confirm(forms[0]); button(h, 'Save counting profile').click();
  await until(() => writes.length === 1 && button(h, 'Save counting profile').disabled);
  assert.equal(button(h, 'Record').disabled, true, 'profile save does not imply consent');
  choose(select(h, 'Voice permission decision'), 'granted');
  choose(select(h, 'Voice decision maker'), 'substitute_decision_maker');
  confirm(forms[1]); button(h, 'Record voice permission').click();
  await until(() => h.main.textContent.includes('reference is required'));
  assert.equal(writes.length, 1, 'missing SDM reference sends nothing');
  forms[1].querySelectorAll('input').find(n => n.getAttribute('aria-label') === 'Voice SDM reference').value = 'synthetic-sdm-ref';
  confirm(forms[1]); button(h, 'Record voice permission').click();
  await until(() => !button(h, 'Record').disabled);
  assert.deepEqual(writes[1], {scope: 'voice_check', status: 'granted',
    decided_by: 'substitute_decision_maker', sdm_reference: 'synthetic-sdm-ref'});
  assert(h.main.textContent.includes('Stored permission: granted'));
  assert.equal(h.calls.filter(c => c.key.endsWith('/checks') && c.key.startsWith('POST')).length, 0);
});

test('PSW resident and forged live URLs never show setup/SDM forms or retrieve consent details', async () => {
  const profile = {state: 'ready', preferred_locale: 'en', protocol_locale: 'en',
    prompt_version: 'count20-days-v1', first_name: null, version: 'v1',
    can_configure: false, can_record_consent: false};
  for (const mode of ['resident', 'live']) {
    const h = loadPage(`/check?mode=${mode}&patient=p1`, {routes: {
      'GET /v1/patients/p1/check-profile': () => profile}});
    await until(() => h.main.querySelector(mode === 'resident' ? '.bl-record' : '.bl-check-setup'));
    await until(() => h.calls.some(c => c.key.endsWith('/check-profile')));
    assert.equal(h.main.querySelector('fieldset'), null);
    assert(!h.calls.some(c => c.key.includes('/consent?')));
    assert(!h.main.textContent.includes('SDM'));
  }
});

test('withdrawn consent is rechecked before microphone access and does not start capture', async () => {
  let state = 'granted', microphone = 0;
  const h = loadPage('/check?mode=runner&patient=p1', {routes: {
    'GET /v1/patients/p1/consent?scope=voice_check': () => ({state})}});
  await until(() => button(h, 'Record') && !button(h, 'Record').disabled);
  state = 'withdrawn';
  h.window.navigator.mediaDevices.getUserMedia = () => { microphone++; throw Error('must not call'); };
  button(h, 'Record').click();
  await until(() => h.main.textContent.includes('Recording blocked'));
  assert.equal(microphone, 0);
  assert.equal(button(h, 'Record').disabled, true);
});

test('withdrawal while microphone permission is pending disposes stream without recording', async () => {
  let state = 'granted', release, stopped = 0;
  const before = FakeRecorder.last;
  const h = loadPage('/check?mode=live&patient=p1', {routes: {
    'GET /v1/patients/p1/consent?scope=voice_check': () => ({state}),
    'POST /v1/patients/p1/consents': () => { state = 'withdrawn'; return {state}; }}});
  await until(() => button(h, 'Record') && !button(h, 'Record').disabled);
  h.window.navigator.mediaDevices.getUserMedia = () => new Promise(resolve => { release = resolve; });
  button(h, 'Record').click();
  await until(() => release);
  choose(select(h, 'Voice permission decision'), 'withdrawn');
  choose(select(h, 'Voice decision maker'), 'resident');
  confirm(h.main.querySelectorAll('fieldset')[1]); button(h, 'Record voice permission').click();
  await until(() => h.main.textContent.includes('voice permission: withdrawn'));
  release({getTracks: () => [{stop() { stopped++; }}]});
  await tick(30);
  assert.equal(stopped, 1);
  assert.equal(FakeRecorder.last, before);
  assert.equal(button(h, 'Record').disabled, true);
  assert(!h.calls.some(c => c.key === 'POST /v1/patients/p1/checks'));
});
