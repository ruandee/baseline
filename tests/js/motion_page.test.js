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

test('motion page requires taps and server consent, then posts derived numbers without media', async () => {
  const h = loadPage('/check?type=motion&patient=p1', {routes: {
    'GET /v1/patients/p1/motion-checks/readiness': () => ({ready: true}),
    'POST /v1/patients/p1/motion-checks': () => ({usable: true, ...measured})}});
  h.window.MotionCapture = CaptureStub;
  await until(() => button(h, 'Prepare local'));
  const capture = CaptureStub.instances.at(-1);
  assert.equal(capture.warms, 0); assert.equal(capture.starts, 0);
  assert.equal(h.calls.some((c) => /readiness/.test(c.key)), false);
  const bootstrap = h.calls.find((c) => c.key === 'GET /demo/session');
  assert.equal(bootstrap.opts.headers['X-PM-Role'], undefined); // Judge path is care-team mode.
  button(h, 'Prepare local').click();
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
  await until(() => button(h, 'Prepare local'));
  assert.equal(h.calls.find((c) => c.key === 'GET /demo/session').opts.headers['X-PM-Role'], 'psw');
  button(h, 'Prepare local').click(); await until(() => !button(h, 'Start').disabled);
  button(h, 'Start').click(); await until(() => /Thank you/.test(h.main.textContent));
  assert.doesNotMatch(exposedText(h.main), /1\.20|60\.00|99|escalate|Time to half-rise|Trunk sway|Step cadence/);
  for (const f of h.window.listeners.pagehide || []) f();
});

test('cancel during consent preflight prevents delayed model initialization or capture', async () => {
  let ready;
  const h = loadPage('/check?type=motion&patient=p1', {routes: {
    'GET /v1/patients/p1/motion-checks/readiness': () => new Promise((r) => { ready = r; })}});
  h.window.MotionCapture = CaptureStub;
  await until(() => button(h, 'Prepare local'));
  const capture = CaptureStub.instances.at(-1);
  button(h, 'Prepare local').click(); await until(() => ready);
  button(h, 'Cancel').click(); ready({ready: true});
  await until(() => !button(h, 'Prepare local').disabled);
  assert.equal(capture.warms, 0); assert.equal(capture.starts, 0);
  assert.ok(button(h, 'Start').disabled);
  assert.match(h.main.textContent, /Camera off/);
});
