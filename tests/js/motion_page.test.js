const {test} = require('node:test');
const assert = require('node:assert/strict');
const {loadPage, until, exposedText} = require('./harness.js');

const measured = {quality: {duration_s: 10, total_frames: 100, confident_frames: 95},
  features: {sit_to_stand_s: 1.2, trunk_sway: .04, step_cadence_spm: 60}};
class CaptureStub {
  static instances = [];
  constructor() { this.warms = 0; this.starts = 0; CaptureStub.instances.push(this); }
  async warm() { this.warms++; this.ready = true; }
  async capture() { this.starts++; return measured; }
  cancel() { this.ready = false; this.cancelled = true; }
}
const button = (h, text) => h.main.querySelectorAll('button').find((b) => b.textContent.includes(text));

test('motion permission controls have visible associated labels and a fieldset legend', async () => {
  const h = loadPage('/check?type=motion&patient=p1');
  h.window.MotionCapture = CaptureStub;
  await until(() => button(h, 'Get ready'));
  const permission = h.main.querySelector('fieldset');
  assert.equal(permission.querySelector('legend').textContent, 'Movement-check permission');
  for (const control of h.main.querySelectorAll('select').concat(
    h.main.querySelectorAll('input').filter((n) => n.getAttribute('type') === 'text'))) {
    assert.equal(control.parentNode.tagName, 'LABEL');
    assert.ok(control.parentNode.textContent.trim().length);
  }
  assert.equal(h.main.querySelector('video').getAttribute('aria-label'), 'Local camera preview');
  assert.equal(h.main.querySelector('[role=status]').textContent, 'Camera is off.');
  assert.equal(permission.hidden, false);
});

test('motion page requires taps and server consent, then posts derived numbers without media', async () => {
  const h = loadPage('/check?type=motion&patient=p1', {routes: {
    'GET /v1/patients/p1/motion-checks/readiness': () => ({ready: true}),
    'POST /v1/patients/p1/motion-checks': () => ({usable: true, ...measured})}});
  h.window.MotionCapture = CaptureStub;
  await until(() => button(h, 'Get ready'));
  const capture = CaptureStub.instances.at(-1);
  assert.equal(capture.warms, 0); assert.equal(capture.starts, 0);
  assert.equal(h.calls.some((c) => /readiness/.test(c.key)), false);
  const bootstrap = h.calls.find((c) => c.key === 'GET /demo/session');
  assert.equal(bootstrap.opts.headers['X-PM-Role'], undefined); // Judge path is care-team mode.
  button(h, 'Get ready').click();
  await until(() => !button(h, 'Start').disabled);
  button(h, 'Start').click();
  await until(() => h.calls.some((c) => c.key.startsWith('POST')));
  await until(() => /Time to half-rise/.test(h.main.textContent));
  const post = h.calls.find((c) => c.key === 'POST /v1/patients/p1/motion-checks');
  const body = JSON.parse(post.opts.body);
  assert.deepEqual(body.features, measured.features);
  assert.equal('frames' in body, false); assert.equal('video' in body, false);
  assert.equal('landmarks' in body, false); assert.equal('image' in body, false);
  assert.equal(h.calls.filter((c) => /readiness/.test(c.key)).length, 2);
  assert.ok(h.calls.every((c) => c.key.split(' ')[1].startsWith('/')));
  for (const f of h.window.listeners.pagehide || []) f();
  assert.ok(capture.cancelled);
});

test('resident/PSW motion view never exposes measurement values or assessment even if supplied', async () => {
  const h = loadPage('/check?type=motion&mode=resident&patient=p1', {routes: {
    'GET /v1/patients/p1/motion-checks/readiness': () => ({ready: true}),
    'POST /v1/patients/p1/motion-checks': () => ({usable: true, ...measured,
      assessment: {verdict: 'escalate', fused_z: 99}})}});
  h.window.MotionCapture = CaptureStub;
  await until(() => button(h, 'Get ready'));
  assert.equal(h.calls.find((c) => c.key === 'GET /demo/session').opts.headers['X-PM-Role'], 'psw');
  button(h, 'Get ready').click(); await until(() => !button(h, 'Start').disabled);
  button(h, 'Start').click(); await until(() => /Thank you/.test(h.main.textContent));
  assert.doesNotMatch(exposedText(h.main), /1\.20|60\.00|99|escalate|Time to half-rise|Trunk sway|Step cadence/);
  for (const f of h.window.listeners.pagehide || []) f();
});

test('cancel during consent preflight prevents delayed model initialization or capture', async () => {
  let ready;
  const h = loadPage('/check?type=motion&patient=p1', {routes: {
    'GET /v1/patients/p1/motion-checks/readiness': () => new Promise((r) => { ready = r; })}});
  h.window.MotionCapture = CaptureStub;
  await until(() => button(h, 'Get ready'));
  const capture = CaptureStub.instances.at(-1);
  button(h, 'Get ready').click(); await until(() => ready);
  button(h, 'Cancel').click(); ready({ready: true});
  await until(() => !button(h, 'Get ready').disabled);
  assert.equal(capture.warms, 0); assert.equal(capture.starts, 0);
  assert.ok(button(h, 'Start').disabled);
  assert.match(h.main.textContent, /Camera off/);
});

test('saved result with a missing or non-numeric feature shows Unknown instead of a failure', async () => {
  const h = loadPage('/check?type=motion&patient=p1', {routes: {
    'GET /v1/patients/p1/motion-checks/readiness': () => ({ready: true}),
    'POST /v1/patients/p1/motion-checks': () => ({usable: false,
      features: {sit_to_stand_s: 1.2, trunk_sway: 'n/a'}})}});
  h.window.MotionCapture = CaptureStub;
  await until(() => button(h, 'Get ready'));
  button(h, 'Get ready').click(); await until(() => !button(h, 'Start').disabled);
  button(h, 'Start').click();
  await until(() => /Step cadence/.test(h.main.textContent));
  assert.match(h.main.textContent, /Trunk sway: Unknown/);
  assert.match(h.main.textContent, /Step cadence: Unknown/);
  assert.match(h.main.textContent, /Measurements saved/);
  assert.doesNotMatch(h.main.textContent, /could not continue/);
  for (const f of h.window.listeners.pagehide || []) f();
});
