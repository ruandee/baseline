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
    can_configure: false, can_record_consent: false, voice_consent_state: 'granted'};
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

for (const mutation of ['consent', 'profile']) {
  for (const outcome of ['blocked', 'ready', 'failure', 'ready_before_mic']) {
    test(`${mutation} save held during permission (${outcome}) invalidates capture until a new tap`, async () => {
      let finishMutation, releaseMic, stopped = 0, asked = 0;
      let profile = {state: 'ready', preferred_locale: 'en', protocol_locale: 'en',
        prompt_version: 'count20-days-v1', first_name: 'Alex', version: 'v1',
        can_configure: true, can_record_consent: true};
      let consent = {state: 'granted'};
      const before = FakeRecorder.last;
      const savePath = mutation === 'consent' ? 'POST /v1/patients/p1/consents'
        : 'PUT /v1/patients/p1/check-profile';
      const h = loadPage('/check?mode=live&patient=p1', {routes: {
        'GET /v1/patients/p1/check-profile': () => profile,
        'GET /v1/patients/p1/consent?scope=voice_check': () => consent,
        [savePath]: () => new Promise((resolve, reject) => {
          finishMutation = () => {
            if (outcome === 'failure') { reject({status: 503}); return; }
            if (outcome === 'blocked') {
              if (mutation === 'consent') consent = {state: 'withdrawn'};
              else profile = {...profile, state: 'unsupported', preferred_locale: 'fr'};
            }
            // Keep the same profile version to prove readiness generations, not only version
            // mismatch, invalidate pending callbacks even when a later read is ready again.
            resolve(mutation === 'consent' ? consent : profile);
          };
        })}});
      await until(() => button(h, 'Record') && !button(h, 'Record').disabled);
      h.window.navigator.mediaDevices.getUserMedia = () => {
        asked++;
        return new Promise(resolve => { releaseMic = () => resolve({getTracks: () => [{stop() { stopped++; }}]}); });
      };
      button(h, 'Record').click();
      await until(() => releaseMic);
      const forms = h.main.querySelectorAll('fieldset');
      if (mutation === 'consent') {
        choose(select(h, 'Voice permission decision'), outcome === 'blocked' ? 'withdrawn' : 'granted');
        choose(select(h, 'Voice decision maker'), 'resident');
      }
      confirm(forms[mutation === 'consent' ? 1 : 0]);
      button(h, mutation === 'consent' ? 'Record voice permission' : 'Save counting profile').click();
      await until(() => finishMutation);
      assert.equal(button(h, 'Record').disabled, true, 'mutation synchronously blocks capture');
      if (outcome === 'ready_before_mic') {
        finishMutation();
        await until(() => !button(h, 'Record').disabled);
      }
      releaseMic();
      await until(() => stopped === 1);
      assert.equal(FakeRecorder.last, before, 'no recorder while save is pending or after ready returns');
      if (outcome !== 'ready_before_mic') finishMutation();
      await until(() => outcome === 'failure'
        ? h.main.textContent.includes(mutation === 'consent' ? 'Permission not recorded:' : 'Profile not saved:')
        : outcome === 'blocked' ? h.main.textContent.includes(mutation === 'consent' ? 'voice permission: withdrawn' : 'Profile: unsupported')
          : !button(h, 'Record').disabled);
      await tick(20);
      assert.equal(FakeRecorder.last, before, 'save completion never resumes invalidated capture');
      assert.equal(asked, 1);
      assert(!h.calls.some(c => c.key === 'POST /v1/patients/p1/checks'));
      if (outcome.startsWith('ready')) {
        button(h, 'Record').click();
        await until(() => asked === 2); // Only a separate deliberate tap requests a new stream.
        for (const handler of h.window.listeners.pagehide || []) handler();
      } else assert.equal(button(h, 'Record').disabled, true);
    });
  }
}

test('a confirmed setup save stops an active stream and discards its late stop callback', async () => {
  let stopped = 0;
  const h = loadPage('/check?mode=live&patient=p1', {routes: {
    'POST /v1/patients/p1/consents': () => ({state: 'granted'})}});
  await until(() => button(h, 'Record') && !button(h, 'Record').disabled);
  h.window.navigator.mediaDevices.getUserMedia = async () => ({getTracks: () => [{stop() { stopped++; }}]});
  button(h, 'Record').click();
  await until(() => FakeRecorder.last && FakeRecorder.last.state === 'recording');
  choose(select(h, 'Voice permission decision'), 'granted');
  choose(select(h, 'Voice decision maker'), 'resident');
  confirm(h.main.querySelectorAll('fieldset')[1]); button(h, 'Record voice permission').click();
  assert(stopped > 0, 'tracks stop synchronously when mutation begins');
  await until(() => button(h, 'Record') && !button(h, 'Record').disabled);
  await tick(30);
  assert.equal(FakeRecorder.last.state, 'inactive');
  assert(!h.calls.some(c => c.key === 'POST /v1/patients/p1/checks'));
});

for (const mutation of ['consent', 'profile']) {
  test(`held preflight read cannot publish ready during a ${mutation} write`, async () => {
    let reads = 0, releaseRead, finishWrite, asked = 0;
    const savePath = mutation === 'consent' ? 'POST /v1/patients/p1/consents'
      : 'PUT /v1/patients/p1/check-profile';
    const h = loadPage('/check?mode=live&patient=p1', {routes: {
      'GET /v1/patients/p1/consent?scope=voice_check': () => ++reads === 2
        ? new Promise(resolve => { releaseRead = () => resolve({state: 'granted'}); }) : {state: 'granted'},
      [savePath]: () => new Promise(resolve => { finishWrite = () => resolve({}); })}});
    await until(() => button(h, 'Record') && !button(h, 'Record').disabled);
    h.window.navigator.mediaDevices.getUserMedia = () => { asked++; throw Error('must not request'); };
    button(h, 'Record').click(); await until(() => releaseRead);
    if (mutation === 'consent') {
      choose(select(h, 'Voice permission decision'), 'withdrawn');
      choose(select(h, 'Voice decision maker'), 'resident');
    }
    confirm(h.main.querySelectorAll('fieldset')[mutation === 'consent' ? 1 : 0]);
    button(h, mutation === 'consent' ? 'Record voice permission' : 'Save counting profile').click();
    await until(() => finishWrite);
    releaseRead(); await tick(30);
    assert.equal(button(h, 'Record').disabled, true);
    assert.equal(asked, 0, 'a stale granted read cannot admit while a mutation is unresolved');
    finishWrite(); await until(() => !button(h, 'Record').disabled);
    await tick(20); assert.equal(asked, 0, 'mutation completion does not resume the old tap');
  });
}

test('nurse resend refreshes effective consent before upload and sends no withdrawn clip', async () => {
  let state = 'granted', uploads = 0;
  const h = loadPage('/check?mode=runner&patient=p1', {routes: {
    'GET /v1/patients/p1/consent?scope=voice_check': () => ({state}),
    'POST /v1/patients/p1/checks': () => { uploads++; throw {status: 400}; }}});
  await until(() => button(h, 'Record') && !button(h, 'Record').disabled);
  button(h, 'Record').click(); await until(() => button(h, 'Stop'));
  button(h, 'Stop').click();
  await until(() => button(h, 'Try again') && !button(h, 'Try again').hidden);
  assert.equal(uploads, 1);
  state = 'withdrawn'; button(h, 'Try again').click();
  await until(() => h.main.textContent.includes('voice permission: withdrawn'));
  assert.equal(uploads, 1);
  assert.equal(button(h, 'Record').disabled, true);
});

for (const phase of ['record', 'upload']) {
  test(`pagehide during held nurse ${phase} preflight makes no late mic/upload or repaint`, async () => {
    let reads = 0, releaseRead, asked = 0, uploads = 0;
    const h = loadPage('/check?mode=live&patient=p1', {routes: {
      'GET /v1/patients/p1/consent?scope=voice_check': () => ++reads === (phase === 'record' ? 2 : 3)
        ? new Promise(resolve => { releaseRead = () => resolve({state: 'granted'}); }) : {state: 'granted'},
      'POST /v1/patients/p1/checks': () => { uploads++; return {usable: true}; }}});
    await until(() => button(h, 'Record') && !button(h, 'Record').disabled);
    const original = h.window.navigator.mediaDevices.getUserMedia;
    h.window.navigator.mediaDevices.getUserMedia = (...args) => { asked++; return original(...args); };
    button(h, 'Record').click();
    if (phase === 'upload') {
      await until(() => button(h, 'Stop')); button(h, 'Stop').click();
    }
    await until(() => releaseRead);
    for (const handler of h.window.listeners.pagehide || []) handler();
    const text = h.main.textContent;
    releaseRead(); await tick(40);
    assert.equal(asked, phase === 'record' ? 0 : 1);
    assert.equal(uploads, 0);
    assert.equal(button(h, 'Record').disabled, true);
    assert.equal(h.main.textContent, text, 'late response does not repaint an exited capture');
  });
}
