const {test} = require('node:test');
const assert = require('node:assert/strict');
const {loadPage, until, tick} = require('./harness');

const overview = {baseline: {n_checks: 5}, latest_assessment: {
  modality: 'speech', modalities: {speech: {current: true, status: 'none',
    params: {prompt_version: 'count20-days-v1', baseline_checks: 5},
    per_feature: {speech_rate_wpm: {z: 0, median: 100, scale: 5}}}},
}};
const path = '/check?nurse=1&patient=p1';
const overviewRoute = {'GET /v1/patients/p1/overview?days=30': () => overview};

test('nurse workspace requests nurse identity and shows evidence-based preparation without microphone', async () => {
  const page = loadPage(path, {pswToken: 'psw-private', routes: overviewRoute});
  await until(() => page.main.textContent.includes('Open recorder'));
  const bootstrap = page.calls.find((call) => call.key === 'GET /demo/session');
  assert.equal(bootstrap.opts.headers['X-PM-Role'], undefined);
  assert(page.calls.every((call) => call.opts.headers.Authorization !== 'Bearer psw-private'));
  assert(page.main.textContent.includes('Granted'));
  assert(page.main.textContent.includes('5 prior checks'));
  const link = page.main.querySelectorAll('a').find((a) => a.textContent === 'Open recorder');
  assert.equal(link.href, '/check?mode=live&patient=p1&from=nurse');
  assert(!page.calls.some((call) => call.key.includes('/checks/due')));
  assert(!page.calls.some((call) => !call.key.startsWith('GET ')));
  assert.equal(page.window.mediaCalls, 0);
});

for (const permission of ['unknown', 'declined', 'withdrawn', 'expired']) {
  test(`nurse ${permission} permission offers setup, never recording or a baseline promise`, async () => {
    const page = loadPage(path, {consent: {p1: permission}, routes: {
      'GET /v1/patients/p1/overview?days=30': () => ({baseline: {n_checks: 0}, latest_assessment: null}),
    }});
    await until(() => page.main.textContent.includes('Review recording setup'));
    assert(!page.main.textContent.includes('Open recorder'));
    assert(page.main.textContent.includes('recording is blocked'));
    assert(page.main.textContent.includes('Not established'));
    assert(!page.calls.some((call) => call.key.startsWith('POST')));
  });
}

test('unsupported profile blocks recorder and exposes honest setup step', async () => {
  const page = loadPage(path, {routes: {...overviewRoute,
    'GET /v1/patients/p1/check-profile': () => ({state: 'unsupported', can_configure: true, can_record_consent: true}),
  }});
  await until(() => page.main.textContent.includes('Review recording setup'));
  assert(page.main.textContent.includes('Language is not supported'));
  assert(!page.main.textContent.includes('Open recorder'));
});

for (const [name, speech] of [
  ['stale speech', {...overview.latest_assessment.modalities.speech, current: false}],
  ['another prompt', {...overview.latest_assessment.modalities.speech, params: {prompt_version: 'vox-v1', baseline_checks: 5}}],
]) {
  test(`${name} never becomes a current counting comparison`, async () => {
    const page = loadPage(path, {routes: {'GET /v1/patients/p1/overview?days=30': () => ({
      baseline: {n_checks: 5}, latest_assessment: {modality: 'motion', modalities: {speech}},
    })}});
    await until(() => page.main.textContent.includes('Open recorder'));
    assert(page.main.textContent.includes('Not established for this counting prompt'));
    assert(!page.main.textContent.includes('5 prior checks'));
  });
}

test('unavailable readiness has a working explicit retry and no recording link', async () => {
  let failed = true;
  const page = loadPage(path, {routes: {
    'GET /v1/patients/p1/overview?days=30': () => { if (failed) throw {status: 503}; return overview; },
  }});
  await until(() => page.main.textContent.includes('could not be checked'));
  assert(!page.main.textContent.includes('Open recorder'));
  failed = false;
  page.main.querySelectorAll('button').find((b) => b.textContent === 'Try again').click();
  await until(() => page.main.textContent.includes('Open recorder'));
});

test('late selection response cannot replace another person readiness', async () => {
  let release;
  const held = new Promise((resolve) => { release = resolve; });
  const page = loadPage(path, {routes: {
    'GET /v1/patients/p1/overview?days=30': () => held,
    'GET /v1/patients/p2/overview?days=30': () => overview,
  }});
  await until(() => page.calls.some((call) => call.key.includes('/p1/overview')));
  const select = page.doc.getElementById('nurse-person');
  // Minimal stand-in stores selection on options rather than browser selectedIndex.
  select.children.forEach((option) => option.removeAttribute('selected'));
  select.children.find((option) => option.getAttribute('value') === 'p2').setAttribute('selected', '');
  select.dispatchEvent({type: 'change'});
  await until(() => page.main.textContent.includes('Jamie Chen'));
  release(overview); await tick(20);
  const links = page.main.querySelectorAll('a');
  assert(links.some((link) => link.href === '/check?mode=live&patient=p2&from=nurse'));
  assert(!links.some((link) => link.href === '/check?mode=live&patient=p1&from=nurse'));
});

test('resident landing remains PSW and never retrieves nurse overview', async () => {
  const page = loadPage('/check');
  await until(() => page.calls.some((call) => call.key.includes('/checks/due')));
  assert.equal(page.calls.find((call) => call.key === 'GET /demo/session').opts.headers['X-PM-Role'], 'psw');
  assert(!page.calls.some((call) => call.key.includes('/overview')));
  assert(!page.main.textContent.includes('Personal comparison'));
});
