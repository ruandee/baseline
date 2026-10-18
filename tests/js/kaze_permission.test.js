const {test} = require('node:test');
const assert = require('node:assert/strict');
const {loadPage, until, FakeRecorder, tick} = require('./harness');

const button = (h, name) => h.main.querySelectorAll('button').find(n => n.textContent === name);
const choose = (h, value) => {
  const select = h.main.querySelectorAll('select').find(n => n.getAttribute('aria-label') === 'My voice permission decision');
  select.children.forEach(n => {
    n.removeAttribute('selected'); if (n.getAttribute('value') === value) n.setAttribute('selected', '');
  });
  select.dispatchEvent({type: 'change'});
  const box = h.main.querySelectorAll('input').find(n => n.getAttribute('aria-label') === 'Confirm my voice decision');
  box.checked = true; box.dispatchEvent({type: 'change'});
};
const active = {id: 's1', status: 'active', ends_at: '2099-01-01T00:00:00Z', interval_min: 45,
  episode: 0, ladder_level: 0, next_due_at: '2099-01-01T00:00:00Z', context_tags: [],
  checks: [], escalations: [], contacts: [], baseline: {usable: 3, required: 3}};
const leave = h => { for (const fn of h.window.listeners.pagehide || []) fn(); };

test('unknown permission never grants on load, checkbox or arm; explicit self decision enables setup', async () => {
  let state = 'unknown'; const writes = [];
  const h = loadPage('/out', {kaze: true, routes: {
    'GET /v1/patients/p1/sessions': () => ({sessions: []}),
    'GET /v1/patients/p1/consent?scope=voice_check': () => ({state}),
    'POST /v1/patients/p1/consents': opts => {
      const body = JSON.parse(opts.body); writes.push(body); state = body.status; return {state};
    }}});
  await until(() => button(h, 'Arm session'));
  assert.equal(button(h, 'Arm session').disabled, true);
  assert.equal(button(h, 'Save my voice permission').disabled, true);
  assert.equal(writes.length, 0);
  assert(h.main.textContent.includes('Arming or ending a session does not grant or withdraw'));
  for (const decision of ['granted', 'declined', 'withdrawn']) {
    choose(h, decision); assert.equal(writes.length, ['granted', 'declined', 'withdrawn'].indexOf(decision));
    button(h, 'Save my voice permission').click();
    await until(() => button(h, 'Save my voice permission').disabled && writes.length > 0
      && h.main.textContent.includes(`Stored voice permission: ${decision}.`));
    assert.equal(button(h, 'Arm session').disabled, decision !== 'granted');
  }
  assert.deepEqual(writes, ['granted', 'declined', 'withdrawn'].map(status =>
    ({scope: 'voice_check', status, decided_by: 'resident'})));
  assert(!h.calls.some(c => c.key.endsWith('/sessions') && c.key.startsWith('POST')));
  assert(!h.calls.some(c => c.key.includes('check-profile')));
  assert(!h.main.textContent.includes('SDM'));
  leave(h);
});

test('a held withdrawal request invalidates a pending microphone immediately, even if grant later returns', async () => {
  let state = 'granted', mic, finishSave, stopped = 0;
  const h = loadPage('/out/session/s1', {kaze: true, routes: {
    'GET /v1/patients/p1/sessions': () => ({sessions: [active]}),
    'GET /v1/patients/p1/sessions/s1': () => active,
    'GET /v1/patients/p1/consent?scope=voice_check': () => ({state}),
    'POST /v1/patients/p1/consents': () => new Promise(resolve => { finishSave = resolve; })}});
  await until(() => h.main.querySelector('.kaze-record') && !h.main.querySelector('.kaze-record').disabled);
  const before = FakeRecorder.last;
  h.window.navigator.mediaDevices.getUserMedia = () => new Promise(resolve => { mic = resolve; });
  h.main.querySelector('.kaze-record').click(); await until(() => mic);
  choose(h, 'withdrawn'); button(h, 'Save my voice permission').click(); await until(() => finishSave);
  mic({getTracks: () => [{stop() { stopped++; }}]}); await tick(20);
  assert.equal(stopped, 1); assert.equal(FakeRecorder.last, before);
  assert.equal(h.main.querySelector('.kaze-record').disabled, true);
  state = 'granted'; finishSave({state}); await tick(20);
  assert.equal(FakeRecorder.last, before, 'a later valid state must require a new Record tap');
  assert(!h.calls.some(c => c.key.endsWith('/checks') && c.key.startsWith('POST')));
  leave(h);
});

test('unknown permission blocks microphone; remote withdrawal after permission stops the late stream', async () => {
  for (const initially of ['unknown', 'granted']) {
    let state = initially, microphones = 0, release, stopped = 0;
    const h = loadPage('/out/session/s1', {kaze: true, routes: {
      'GET /v1/patients/p1/sessions': () => ({sessions: [active]}),
      'GET /v1/patients/p1/sessions/s1': () => active,
      'GET /v1/patients/p1/consent?scope=voice_check': () => ({state})}});
    await until(() => h.main.querySelector('.kaze-record')
      && h.main.textContent.includes('Session timeline'));
    h.window.navigator.mediaDevices.getUserMedia = () => {
      microphones++; return new Promise(resolve => { release = resolve; });
    };
    h.main.querySelector('.kaze-record').click();
    if (initially === 'unknown') {
      await tick(20); assert.equal(microphones, 0);
    } else {
      await until(() => release); state = 'withdrawn';
      release({getTracks: () => [{stop() { stopped++; }}]});
      await until(() => stopped === 1);
      assert.equal(h.main.querySelector('.kaze-record').disabled, true);
    }
    assert(!h.calls.some(c => c.key.endsWith('/checks') && c.key.startsWith('POST')));
    leave(h);
  }
});

test('an older granted read cannot overwrite a newer withdrawn permission response', async () => {
  let held = false; const reads = [];
  const h = loadPage('/out', {kaze: true, routes: {
    'GET /v1/patients/p1/sessions': () => ({sessions: []}),
    'GET /v1/patients/p1/consent?scope=voice_check': () => held
      ? new Promise(resolve => reads.push(resolve)) : {state: 'granted'}}});
  await until(() => button(h, 'Arm session'));
  const host = h.doc.createElement('section'); h.main.append(host);
  const controller = await h.window.kazeVoicePermission(host, 'p1');
  held = true;
  const older = controller.refresh(), newer = controller.refresh();
  await until(() => reads.length === 2);
  reads[1]({state: 'withdrawn'}); await newer; assert.equal(controller.ready, false);
  reads[0]({state: 'granted'}); await older;
  assert.equal(controller.ready, false);
  assert(host.textContent.includes('Stored voice permission: withdrawn.'));
  leave(h);
});

test('a failed explicit withdrawal stays locally blocked across polls until an explicit successful save', async () => {
  let fail = true;
  const h = loadPage('/out', {kaze: true, routes: {
    'GET /v1/patients/p1/sessions': () => ({sessions: []}),
    'GET /v1/patients/p1/consent?scope=voice_check': () => ({state: 'granted'}),
    'POST /v1/patients/p1/consents': () => { if (fail) throw Error('synthetic network failure'); return {state: 'granted'}; }}});
  await until(() => button(h, 'Arm session'));
  const host = h.doc.createElement('section'); h.main.append(host);
  const controller = await h.window.kazeVoicePermission(host, 'p1');
  const scoped = {main: host};
  choose(scoped, 'withdrawn'); button(scoped, 'Save my voice permission').click();
  await until(() => host.textContent.includes('Could not record your decision'));
  assert.equal(controller.ready, false);
  await controller.refresh(); assert.equal(controller.ready, false);
  fail = false;
  choose(scoped, 'granted'); button(scoped, 'Save my voice permission').click();
  await until(() => controller.ready); assert.equal(controller.ready, true);
  leave(h);
});

test('late arm response after page exit cannot mount a session or begin polling', async () => {
  let finishArm;
  const h = loadPage('/out', {kaze: true, routes: {
    'GET /v1/patients/p1/sessions': () => ({sessions: []}),
    'POST /v1/patients/p1/sessions': () => new Promise(resolve => { finishArm = resolve; }),
    'GET /v1/patients/p1/sessions/s1': () => active}});
  await until(() => button(h, 'Arm session') && !button(h, 'Arm session').disabled);
  for (const [name, value] of [['name', 'Sam'], ['name1', 'Contact'], ['phone1', '+14165550101']]) {
    h.main.querySelector(`[name=${name}]`).value = value;
  }
  h.main.querySelector('[name=permission]').checked = true;
  h.main.querySelector('.kaze-form').dispatchEvent({type: 'submit', preventDefault() {}});
  await until(() => finishArm); leave(h); finishArm(active); await tick(30);
  assert.equal(h.main.querySelector('.kaze-record'), null);
  assert(!h.calls.some(c => c.key === 'GET /v1/patients/p1/sessions/s1'));
});

test('late initial session list after page exit cannot mount permission or recording controls', async () => {
  let finishList;
  const h = loadPage('/out', {kaze: true, routes: {
    'GET /v1/patients/p1/sessions': () => new Promise(resolve => { finishList = resolve; })}});
  await until(() => finishList); leave(h); finishList({sessions: []}); await tick(30);
  assert.equal(button(h, 'Save my voice permission'), undefined);
  assert.equal(h.main.querySelector('.kaze-form'), null);
  assert(!h.calls.some(c => c.key.includes('/consent?')));
});
