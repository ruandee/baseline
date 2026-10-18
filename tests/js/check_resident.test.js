// BL-31: resident and PSW experience on /check. Run with `node --test tests/js`.
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {loadPage, until, exposedText, FakeRecorder, tick} = require('./harness');

// Anything that would reveal a score, verdict, feature or technical failure to a resident.
const LEAKS = [/\d/, /escalat/i, /\bwatch\b/i, /explained/i, /within normal/i, /enrolling/i,
  /baseline/i, /score/i, /risk/i, /\bz\b/i, /wpm/i, /hz\b/i, /pause/i, /speech rate/i, /pitch/i,
  /error/i, /fail/i, /could not/i, /unusable/i, /noisy/i, /permission/i, /microphone/i, /4AT/i,
  /oxybutynin/i, /verdict/i];

function assertNoLeak(main) {
  const text = exposedText(main);
  for (const pattern of LEAKS) assert.doesNotMatch(text, pattern, `resident view leaked ${pattern}: "${text}"`);
}

const q = (page, sel) => page.main.querySelector(sel);
const message = (page) => q(page, '.bl-resident-message').textContent;
const posts = (page, path) => page.calls.filter((c) => c.key === `POST ${path}`);
const cardState = (page) => q(page, '.bl-check-card') && q(page, '.bl-check-card').dataset.state;

test('skip while permission is pending stops the eventual stream without recording/upload', async () => {
  const page = loadPage('/check?mode=resident&patient=p1', {routes: {
    'POST /v1/patients/p1/checks/skips': () => ({skip_id: 's'})}});
  await ready(page);
  let release;
  let stopped = 0;
  let asked = 0;
  const previousRecorder = FakeRecorder.last;
  page.window.navigator.mediaDevices.getUserMedia = () => {
    asked += 1;
    return new Promise((resolve) => { release = resolve; });
  };
  q(page, '.bl-record').click();
  q(page, '.bl-record').click();
  await until(() => asked === 1);
  assert.equal(asked, 1, 'only one outstanding permission request');
  q(page, '.bl-skip').click();
  q(page, '[data-reason=declined]').click();
  await until(() => cardState(page) === 'skipped');
  release({getTracks: () => [{stop() { stopped += 1; }}]});
  await tick(25);
  assert.equal(stopped, 1);
  assert.equal(FakeRecorder.last, previousRecorder, 'no recorder constructed after refusal');
  assert.equal(cardState(page), 'skipped');
  assert.equal(posts(page, '/v1/patients/p1/checks').length, 0);
  assertNoLeak(page.main);
});

async function ready(page) {
  await until(() => q(page, '.bl-record') && !q(page, '.bl-record').disabled);
}

async function record(page) {
  q(page, '.bl-record').click();
  await until(() => cardState(page) === 'listening');
  assert.equal(q(page, '.bl-listening').hidden, false, 'listening indicator is visible');
  assert.match(q(page, '.bl-listening').textContent, /listening/i);
  q(page, '.bl-record').click();  // Stop
}

const ESCALATE = {check_id: 'c', ts: '2026-10-17T10:00:00Z', usable: true,
  quality: {duration_s: 10, speech_s: 8, snr_db: 20, clipped: false, reasons: []},
  features: {speech_rate_wpm: 118, pause_ratio: 0.34, mean_pause_s: 0.6, f0_median_hz: 205},
  words: [{w: 'one', start: 0.1, end: 0.3}], pauses: [{start: 1, end: 2}], timings_ms: {asr: 2900},
  change: {status: 'change', mode: 'rolling', fused_z: 3.1, per_feature: {}, params: {baseline_checks: 14}},
  assessment: {id: 'a', verdict: 'escalate', suggested_action: '4at_now',
               suggested_action_label: 'Run 4AT now', over_budget: false,
               reasons: [{kind: 'amplifier', label: 'Oxybutynin started', quote: 'oxybutynin 5 mg'}]}};

test('resident check shows only a warm thank-you, as the PSW, with a stable device id', async () => {
  const page = loadPage('/check?mode=resident&patient=p1',
                        {routes: {'POST /v1/patients/p1/checks': () => ESCALATE}});
  await ready(page);
  assert.equal(q(page, 'h1').textContent, "Let's count together");
  assert.match(q(page, '.bl-prompt').textContent, /Count from one to twenty/);
  assert.equal(q(page, '.bl-skip').hidden, false, 'Skip today is visible from the start');
  assert.equal(page.calls.filter((c) => c.key.startsWith('POST')).length, 0, 'no recording without a tap');
  await record(page);
  await until(() => !q(page, '.bl-back').hidden);
  const sent = posts(page, '/v1/patients/p1/checks');
  assert.equal(sent.length, 1);
  assert.equal(sent[0].opts.headers.Authorization, 'Bearer psw-t', 'resident mode uses the PSW token');
  const device = sent[0].opts.body.get('device_id');
  assert.match(device, /^resident-device-[a-z0-9]+$/);
  assert.equal(page.window.stored.get('bl-device-id-resident'), device, 'kept for the next check');
  assert.match(message(page), /Thank you, Alex\./);
  assert.equal(q(page, '.bl-record').hidden, true);
  assert.equal(page.doc.activeElement, q(page, 'h1'), 'focus moves to the heading for screen readers');
  assertNoLeak(page.main);  // the listening countdown had digits; the finished page has none
});

test('an honorific or anonymized initial gets a warm close without a guessed given name', async () => {
  for (const name of ['Mrs. K', 'Mr T', 'Dr. Lee', 'K.', '']) {
    const page = loadPage('/check?mode=resident&patient=p1&mock=1&fixture=escalate', {
      patients: [{id: 'p1', name}],
    });
    await ready(page);
    await record(page);
    await until(() => cardState(page) === 'thanks');
    assert.match(message(page), /^Thank you\./);
    assert.doesNotMatch(message(page), /Thank you,/);
    assertNoLeak(page.main);
  }
});

test('one retry after an unusable clip, then a second unusable clip is accepted, never looped', async () => {
  const page = loadPage('/check?mode=resident&patient=p2&mock=1&fixture=unusable,unusable');
  await ready(page);
  await record(page);
  await until(() => cardState(page) === 'retry');
  assert.match(message(page), /try once more/i);
  assert.equal(q(page, '.bl-record').textContent, 'Try once more');
  assertNoLeak(page.main);
  await record(page);
  await until(() => !q(page, '.bl-back').hidden);
  assert.equal(cardState(page), 'accepted');
  assert.match(message(page), /^Thank you\./); // Mock protocol supplies no explicit given name.
  assert.equal(q(page, '.bl-record').hidden, true, 'no third attempt is offered');
  assertNoLeak(page.main);
});

test('a usable second attempt ends with thanks', async () => {
  const page = loadPage('/check?mode=resident&patient=p1&mock=1&fixture=unusable,escalate');
  await ready(page);
  await record(page);
  await until(() => cardState(page) === 'retry');
  await record(page);
  await until(() => cardState(page) === 'thanks');
  assertNoLeak(page.main);
});

test('skip (refusal) logs a reason, records no audio and never asks for the microphone', async () => {
  let micAsked = false;
  let skipBody = null;
  const page = loadPage('/check?mode=resident&patient=p3', {routes: {
    'POST /v1/patients/p3/checks': () => ESCALATE,
    'POST /v1/patients/p3/checks/skips': (opts) => { skipBody = JSON.parse(opts.body); return {skip_id: 's'}; }}});
  await ready(page);
  const original = page.window.navigator.mediaDevices.getUserMedia;
  page.window.navigator.mediaDevices.getUserMedia = async () => { micAsked = true; return original(); };
  q(page, '.bl-skip').click();
  assert.equal(q(page, '.bl-skip-reasons').hidden, false, 'staff choose a reason');
  page.main.querySelectorAll('button').find((b) => b.getAttribute('data-reason') === 'declined').click();
  await until(() => cardState(page) === 'skipped');
  assert.equal(micAsked, false);
  assert.equal(posts(page, '/v1/patients/p3/checks').length, 0);
  assert.equal(skipBody.reason, 'declined');
  assert.match(message(page), /skip today/i);
  assert.match(message(page), /Thank you, Sam\./);
  assert.match(q(page, '.bl-back').href, /^\/check\?mode=resident$/);
  assertNoLeak(page.main);
});

test('skip while listening discards the clip instead of uploading it', async () => {
  const page = loadPage('/check?mode=resident&patient=p1',
                        {routes: {'POST /v1/patients/p1/checks': () => ESCALATE}});
  await ready(page);
  q(page, '.bl-record').click();
  await until(() => cardState(page) === 'listening');
  q(page, '.bl-skip').click();
  await new Promise((r) => setTimeout(r, 30));
  assert.equal(posts(page, '/v1/patients/p1/checks').length, 0);
});

test('a failed skip save asks for staff help and lets them choose again', async () => {
  const page = loadPage('/check?mode=resident&patient=p1', {routes: {
    'POST /v1/patients/p1/checks/skips': () => { throw Object.assign(new Error('x'), {status: 503}); }}});
  await ready(page);
  q(page, '.bl-skip').click();
  page.main.querySelectorAll('button').find((b) => b.getAttribute('data-reason') === 'asleep').click();
  await until(() => cardState(page) === 'help');
  assert.equal(q(page, '.bl-skip-reasons').hidden, false);
  assertNoLeak(page.main);
});

test('without granted consent the page never offers recording', async () => {
  for (const state of ['unknown', 'withdrawn', 'expired']) {
    const page = loadPage('/check?mode=resident&patient=p1', {consent: {p1: state}});
    await until(() => cardState(page) === 'consent');
    assert.equal(q(page, '.bl-record').hidden, true, state);
    assert.equal(q(page, '.bl-skip').hidden, false, 'skip stays available');
    assert.match(message(page), /check with the nurse/);
    assertNoLeak(page.main);
  }
});

test('a 403 consent_required during upload (withdrawn meanwhile) shows the consent view', async () => {
  const page = loadPage('/check?mode=resident&patient=p1', {routes: {
    'POST /v1/patients/p1/checks': () => { throw Object.assign(new Error('x'), {status: 403}); }}});
  await ready(page);
  await record(page);
  await until(() => cardState(page) === 'consent');
  assert.equal(posts(page, '/v1/patients/p1/checks').length, 1, '403 is final, never retried');
  assertNoLeak(page.main);
});

test('microphone permission failure asks for staff help without technical detail', async () => {
  const page = loadPage('/check?mode=resident&patient=p1', {mic: 'denied'});
  await ready(page);
  q(page, '.bl-record').click();
  await until(() => cardState(page) === 'help');
  assert.match(message(page), /ask a staff member/i);
  assert.equal(page.errors.length, 1, 'the real error goes to the console');
  assert.equal(q(page, '.bl-skip').hidden, false, 'skip stays available');
  assert.equal(q(page, '.bl-record').disabled, false, 'staff can fix permission and tap again');
  assertNoLeak(page.main);
});

test('server errors stay hidden; staff can resend the kept clip without using the retry', async () => {
  let fail = true;
  const page = loadPage('/check?mode=resident&patient=p1', {routes: {
    'POST /v1/patients/p1/checks': () => { if (fail) throw Object.assign(new Error('x'), {status: 422}); return ESCALATE; }}});
  await ready(page);
  await record(page);
  await until(() => cardState(page) === 'help');
  assert.equal(q(page, '.bl-retry').hidden, false);
  assertNoLeak(page.main);
  fail = false;
  q(page, '.bl-retry').click();
  await until(() => cardState(page) === 'thanks');
  assertNoLeak(page.main);
});

test('spoken prompt uses speechSynthesis in the resident language and is optional', async () => {
  const page = loadPage('/check?mode=resident&patient=p1');
  await until(() => q(page, '.bl-hear'));
  q(page, '.bl-hear').click();
  assert.equal(page.spoken.length, 1);
  assert.equal(page.spoken[0].lang, 'en');
  assert.match(page.spoken[0].text, /^Let's count together\./);
  const quiet = loadPage('/check?mode=resident&patient=p1', {speech: false});
  await until(() => q(quiet, '.bl-hear'));
  assert.equal(q(quiet, '.bl-hear').hidden, true, 'no speech engine: the button is hidden, the text stays');
});

test('unsupported requested language blocks without falling back to English', async () => {
  const page = loadPage('/check?mode=resident&patient=p1&lang=fr');
  await until(() => cardState(page) === 'language_unavailable');
  assert.match(page.main.textContent, /language is not supported/);
  assert.equal(q(page, '.bl-record'), null);
  assert.equal(q(page, '.bl-hear'), null);
  assert.equal(page.spoken.length, 0);
});

test('explicit full first name is used without splitting or using the roster display name', async () => {
  const page = loadPage('/check?mode=resident&patient=p1', {patients: [{id: 'p1', name: 'Mrs. K'}], routes: {
    'GET /v1/patients/p1/check-profile': () => ({state: 'ready', protocol_locale: 'en',
      prompt_version: 'count20-days-v1', first_name: 'Mary Ann', version: 'v1', voice_consent_state: 'granted'}),
    'POST /v1/patients/p1/checks': () => ESCALATE}});
  await ready(page);
  await record(page);
  await until(() => cardState(page) === 'thanks');
  assert.match(message(page), /Thank you, Mary Ann\./);
  const body = posts(page, '/v1/patients/p1/checks')[0].opts.body;
  assert.equal(body.get('profile_version'), 'v1');
  assert.equal(body.get('protocol_locale'), 'en');
});

test('unsupported or absent resident profile offers no recording or spoken English', async () => {
  for (const state of ['unsupported', 'unconfigured']) {
    const page = loadPage('/check?mode=resident&patient=p1', {routes: {
      'GET /v1/patients/p1/check-profile': () => ({state, first_name: null,
        protocol_locale: null, prompt_version: null, version: 'v1'})}});
    await until(() => cardState(page) === 'language_unavailable');
    assert.equal(q(page, '.bl-record'), null);
    assert.equal(q(page, '.bl-hear'), null);
    assert.equal(page.spoken.length, 0);
    assert.equal(posts(page, '/v1/patients/p1/checks').length, 0);
  }
});

test('profile changed before tap is blocked before asking for the microphone', async () => {
  let reads = 0, camera = 0;
  const page = loadPage('/check?mode=resident&patient=p1', {routes: {
    'GET /v1/patients/p1/check-profile': () => ({state: 'ready', protocol_locale: 'en',
      prompt_version: 'count20-days-v1', first_name: 'Mary Ann', voice_consent_state: 'granted', version: ++reads === 1 ? 'v1' : 'v2'})}});
  await ready(page);
  page.window.navigator.mediaDevices.getUserMedia = () => { camera++; throw Error('must not request'); };
  q(page, '.bl-record').click();
  await until(() => cardState(page) === 'help');
  assert.equal(camera, 0);
  assert.match(message(page), /setup changed/);
});

for (const attempt of ['idle', 'retry', 'resend']) {
  test(`effective consent is refreshed before resident ${attempt} without SDM retrieval`, async () => {
    let consent = 'granted', microphone = 0, uploads = 0;
    const page = loadPage('/check?mode=resident&patient=p1', {routes: {
      'GET /v1/patients/p1/check-profile': () => ({state: 'ready', protocol_locale: 'en',
        prompt_version: 'count20-days-v1', version: 'v1', first_name: null,
        voice_consent_state: consent}),
      'POST /v1/patients/p1/checks': () => {
        uploads++;
        if (attempt === 'resend') throw {status: 400};
        return {usable: false};
      }}});
    await ready(page);
    const original = page.window.navigator.mediaDevices.getUserMedia;
    page.window.navigator.mediaDevices.getUserMedia = (...args) => { microphone++; return original(...args); };
    if (attempt !== 'idle') {
      await record(page);
      await until(() => attempt === 'retry' ? cardState(page) === 'retry' : !q(page, '.bl-retry').hidden);
    }
    const before = {microphone, uploads};
    consent = 'withdrawn';
    q(page, attempt === 'resend' ? '.bl-retry' : '.bl-record').click();
    await until(() => cardState(page) === 'consent');
    assert.equal(microphone, before.microphone);
    assert.equal(uploads, before.uploads);
    assert.equal(q(page, '.bl-record').hidden, true);
    assert(!page.calls.some(c => c.key.includes('/consent?') || c.key.endsWith('/consent')));
    assertNoLeak(page.main);
  });
}

for (const action of ['skip', 'pagehide']) {
  test(`late resident preflight response cannot resume after ${action}`, async () => {
    let reads = 0, release, microphone = 0;
    const profile = {state: 'ready', protocol_locale: 'en', prompt_version: 'count20-days-v1',
      version: 'v1', first_name: null, voice_consent_state: 'granted'};
    const page = loadPage('/check?mode=resident&patient=p1', {routes: {
      'GET /v1/patients/p1/check-profile': () => ++reads === 1 ? profile
        : new Promise(resolve => { release = () => resolve(profile); }),
      'POST /v1/patients/p1/checks/skips': () => ({skip_id: 's'})}});
    await ready(page);
    page.window.navigator.mediaDevices.getUserMedia = () => { microphone++; throw Error('must not request'); };
    q(page, '.bl-record').click(); await until(() => release);
    if (action === 'skip') {
      q(page, '.bl-skip').click(); q(page, '[data-reason=asleep]').click();
      await until(() => cardState(page) === 'skipped');
    } else for (const handler of page.window.listeners.pagehide || []) handler();
    release(); await tick(30);
    assert.equal(microphone, 0);
    assert.equal(q(page, '.bl-record').disabled, true);
    assert.equal(posts(page, '/v1/patients/p1/checks').length, 0);
  });
}

test('keyboard: every control is a native button or link, Escape stops listening', async () => {
  const page = loadPage('/check?mode=resident&patient=p1&mock=1&fixture=normal');
  await ready(page);
  for (const sel of ['.bl-record', '.bl-skip', '.bl-hear', '.bl-retry']) {
    const node = q(page, sel);
    assert.equal(node.tagName, 'BUTTON', sel);
    assert.equal(node.getAttribute('type'), 'button', sel);
  }
  for (const b of q(page, '.bl-skip-reasons').querySelectorAll('button')) {
    assert.equal(b.getAttribute('type'), 'button');
  }
  assert.equal(q(page, '.bl-back').tagName, 'A');
  q(page, '.bl-record').click();
  await until(() => cardState(page) === 'listening');
  assert.equal(q(page, '.bl-record').getAttribute('aria-pressed'), 'true');
  q(page, '.bl-check-card').dispatchEvent({type: 'keydown', key: 'Escape'});
  await until(() => cardState(page) === 'thanks');
});

const DUE = {day_start: '2026-10-17T04:00:00Z', residents: [
  {patient_id: 'p1', display_name: 'synthetic-1', status: 'due', consent_state: 'granted',
   last_check_ts: '2026-10-16T10:00:00Z', skipped_today: false, observation_helped: null},
  {patient_id: 'p2', display_name: 'synthetic-2', status: 'done', consent_state: 'granted',
   last_check_ts: '2026-10-17T09:00:00Z', skipped_today: false, observation_helped: null},
  {patient_id: 'p3', display_name: 'synthetic-3', status: 'due', consent_state: 'granted',
   last_check_ts: null, skipped_today: false, observation_helped: null},
  {patient_id: 'p4', display_name: 'Pat Doe', status: 'consent_needed', consent_state: 'withdrawn',
   last_check_ts: null, skipped_today: false, observation_helped: null}]};

test('PSW landing reads the score-free due list, never the watch list', async () => {
  const page = loadPage('/check?mode=resident', {routes: {'GET /v1/checks/due': () => DUE}});
  await until(() => q(page, '.bl-due-list'));
  assert.equal(page.calls.filter((c) => c.key === 'GET /v1/watchlist').length, 0);
  const due = page.calls.find((c) => c.key === 'GET /v1/checks/due');
  assert.equal(due.opts.headers.Authorization, 'Bearer psw-t');
  const lists = page.main.querySelectorAll('ul');
  const names = (ul) => ul.querySelectorAll('a').map((a) => a.textContent);
  assert.deepEqual(names(lists[0]), ['Sam Rivera', 'Alex Morgan'], 'never-checked first, then oldest');
  assert.equal(lists[0].querySelector('a').href, '/check?mode=resident&patient=p3');
  assert.equal(lists[1].querySelectorAll('a').length, 0, 'no check link without consent');
  assert.match(lists[1].textContent, /Pat Doe.*Consent not recorded/);
  assert.equal(page.main.querySelector('.bl-helped'), null, 'observation_helped null is never shown');
  const shown = exposedText(page.main).replace(/\b(One resident|\d+ residents) still to check today\./, '');
  for (const pattern of LEAKS) assert.doesNotMatch(shown, pattern);
});

test('"Your observation helped" appears only when the server says exactly true', () => {
  const page = loadPage('/check?mode=live&mock=1');
  const items = page.ctx.dueNowItems([
    {patient_id: 'a', display_name: 'A', status: 'due', observation_helped: true},
    {patient_id: 'b', display_name: 'B', status: 'due', observation_helped: 'yes'},
    {patient_id: 'c', display_name: 'C', status: 'due', observation_helped: null}], []);
  assert.deepEqual(items.map((i) => i.observation_helped), [true, false, false]);
  assert.equal(page.ctx.dueNowItems([{patient_id: 'x', status: 'weird'}], [])[0].status,
               'consent_needed', 'an unexpected status is treated as blocked, not due');
});

test('PSW landing load failure shows a plain message', async () => {
  const page = loadPage('/check?mode=resident', {routes: {'GET /v1/checks/due': () => {
    throw Object.assign(new Error('boom'), {status: 500}); }}});
  await until(() => q(page, '.bl-due-status')
    && /could not be loaded/.test(q(page, '.bl-due-status').textContent));
  assert.doesNotMatch(exposedText(page.main), /500|boom|checks\/due/);
});

test('mock landing keeps the synthetic fixture path and carries mock params to each check', async () => {
  const page = loadPage('/check?mode=resident&mock=1&fixture=unusable,normal');
  await until(() => q(page, '.bl-due-list'));
  assert.equal(page.calls.filter((c) => c.key.startsWith('GET /v1/')).length, 0);
  const href = q(page, '.bl-due-item').href;
  assert.equal(new URLSearchParams(href.split('?')[1]).get('fixture'), 'unusable,normal');
});

test('device id: ?device= wins, runner defaults to runner-phone, blocked storage falls back', () => {
  const page = loadPage('/check?mode=live&mock=1');
  const id = page.ctx.checkDeviceId;
  assert.equal(id({mode: 'live', device: 'tablet-7'}), 'tablet-7');
  assert.equal(id({mode: 'live', device: 'bad id;<x>'}), 'badidx');
  assert.equal(id({mode: 'runner'}), 'runner-phone');
  assert.equal(id({mode: 'runner', device: 'runner-phone-2'}), 'runner-phone-2');
  const first = id({mode: 'live'});
  assert.match(first, /^live-device-/);
  assert.equal(id({mode: 'live'}), first, 'stable within a mode');
  assert.notEqual(id({mode: 'resident'}), first, 'separate ids per mode');
  const blocked = loadPage('/check?mode=live&mock=1', {storage: 'blocked'});
  assert.equal(blocked.ctx.checkDeviceId({mode: 'live'}), 'check-page');
});

test('live mode uses the runner/live device id, not a hard-coded one', async () => {
  const page = loadPage('/check?mode=runner&patient=p1', {routes: {'POST /v1/patients/p1/checks': () => ESCALATE}});
  await until(() => q(page, '.bl-record'));
  q(page, '.bl-record').click();
  await new Promise((r) => setTimeout(r, 20));
  q(page, '.bl-record').click();
  await until(() => posts(page, '/v1/patients/p1/checks').length === 1);
  const sent = posts(page, '/v1/patients/p1/checks')[0];
  assert.equal(sent.opts.body.get('device_id'), 'runner-phone');
  assert.equal(sent.opts.headers.Authorization, 'Bearer t', 'non-resident modes keep the nurse token');
});

async function liveResult(fixtureResult) {
  const page = loadPage('/check?mode=live&patient=p1',
                        {routes: {'POST /v1/patients/p1/checks': () => fixtureResult}});
  await until(() => q(page, '.bl-record'));
  q(page, '.bl-record').click();
  await new Promise((r) => setTimeout(r, 20));
  q(page, '.bl-record').click();
  await until(() => q(page, '.bl-features'));
  return page;
}

test('live verdict: a missing assessment is shown as unknown, never within normal', async () => {
  const page = await liveResult({...ESCALATE, assessment: null});
  const chip = q(page, '.bl-chip');
  assert.equal(chip.textContent, 'Verdict unavailable');
  assert.equal(chip.dataset.verdict, 'unknown');
  assert.doesNotMatch(q(page, '.bl-verdict').textContent, /within normal/i);
});

test('live verdict: over-budget escalation shows as watch, with the suggested action label', async () => {
  const page = await liveResult({...ESCALATE, assessment: {...ESCALATE.assessment, over_budget: true}});
  const chip = q(page, '.bl-chip');
  assert.equal(chip.textContent, 'Escalate (over budget)');
  assert.equal(chip.dataset.verdict, 'watch');
  assert.match(q(page, '.bl-verdict').textContent, /Suggested: Run 4AT now/);
  const plain = await liveResult(ESCALATE);
  assert.equal(q(plain, '.bl-chip').dataset.verdict, 'escalate');
  const none = await liveResult({...ESCALATE, assessment: {...ESCALATE.assessment,
    verdict: 'within_normal', suggested_action: 'none', suggested_action_label: 'No action'}});
  assert.doesNotMatch(q(none, '.bl-verdict').textContent, /Suggested/);
});

test('live mode reads params.baseline_checks for enrolment progress', async () => {
  const page = loadPage('/check?mode=live&patient=p1&mock=1&fixture=enrolling');
  await until(() => q(page, '.bl-record'));
  q(page, '.bl-record').click();
  await new Promise((r) => setTimeout(r, 20));
  q(page, '.bl-record').click();
  await until(() => q(page, '.bl-features'));
  assert.match(exposedText(page.main), /building baseline 2 of 3/);
});

test('residentStep never allows more than one retry', () => {
  const page = loadPage('/check?mode=live&mock=1');
  let flow = {unusable: 0, done: false};
  const views = [];
  for (let i = 0; i < 4; i += 1) {
    const step = page.ctx.residentStep(flow, false);
    flow = step.flow;
    views.push(step.view);
  }
  assert.deepEqual(views, ['retry', 'accepted', 'done', 'done']);
});

test('late microphone rejection after resident pagehide does not repaint the exited screen', async () => {
  let rejectMic;
  const page = loadPage('/check?mode=resident&patient=p1');
  await until(() => q(page, '.bl-record'));
  page.window.navigator.mediaDevices.getUserMedia = () => new Promise((resolve, reject) => { rejectMic = reject; });
  q(page, '.bl-record').click();
  await until(() => rejectMic);
  for (const handler of page.window.listeners.pagehide || []) handler();
  const text = page.main.textContent;
  rejectMic(new Error('synthetic held microphone rejection'));
  await new Promise(resolve => setTimeout(resolve, 40));
  assert.equal(page.main.textContent, text);
  assert.equal(q(page, '.bl-record').disabled, true);
  assert.equal(posts(page, '/v1/patients/p1/checks').length, 0);
});
