// BL-31: resident and PSW experience on /check. Run with `node --test tests/js`.
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {loadPage, until, exposedText} = require('./harness');

// Anything that would reveal a score, verdict, feature or technical failure to a resident.
const LEAKS = [/\d/, /escalat/i, /\bwatch\b/i, /explained/i, /within normal/i, /enrolling/i,
  /baseline/i, /score/i, /risk/i, /\bz\b/i, /wpm/i, /hz\b/i, /pause/i, /speech rate/i, /pitch/i,
  /error/i, /fail/i, /could not/i, /unusable/i, /noisy/i, /permission/i, /microphone/i, /4AT/i,
  /oxybutynin/i, /\b(4|5)\d\d\b/];

function assertNoLeak(main) {
  const text = exposedText(main);
  for (const pattern of LEAKS) assert.doesNotMatch(text, pattern, `resident view leaked ${pattern}: "${text}"`);
}

const q = (page, sel) => page.main.querySelector(sel);
const message = (page) => q(page, '.bl-resident-message').textContent;

async function record(page) {
  q(page, '.bl-record').click();
  await until(() => page.main.querySelector('.bl-check-card').dataset.state === 'listening');
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
               suggested_action_label: 'Run 4AT now',
               reasons: [{kind: 'amplifier', label: 'Oxybutynin started', quote: 'oxybutynin 5 mg'}]}};
const UNUSABLE = {...ESCALATE, usable: false, change: null, assessment: null,
  quality: {...ESCALATE.quality, reasons: ['too_noisy']}};

test('resident check with a real API escalation shows only a warm thank-you', async () => {
  const page = loadPage('/check?mode=resident&patient=p1',
                        {routes: {'POST /v1/patients/p1/checks': () => ESCALATE}});
  await until(() => q(page, '.bl-record'));
  assert.equal(q(page, 'h1').textContent, "Let's count together");
  assert.match(q(page, '.bl-prompt').textContent, /Count from one to twenty/);
  assert.equal(q(page, '.bl-skip').hidden, false, 'Skip today is visible from the start');
  assert.equal(page.calls.filter((c) => c.key.startsWith('POST')).length, 0, 'no recording without a tap');
  await record(page);
  await until(() => !q(page, '.bl-back').hidden);
  assert.equal(page.calls.filter((c) => c.key === 'POST /v1/patients/p1/checks').length, 1);
  assert.match(message(page), /Thank you, Alex\./);
  assert.equal(q(page, '.bl-record').hidden, true);
  assert.equal(page.doc.activeElement, q(page, 'h1'), 'focus moves to the heading for screen readers');
  // The listening countdown has digits; once done the whole page must have none.
  assertNoLeak(page.main);
});

test('one retry after an unusable clip, then a second unusable clip is accepted, never looped', async () => {
  const page = loadPage('/check?mode=resident&patient=p2&mock=1&fixture=unusable,unusable');
  await until(() => q(page, '.bl-record'));
  await record(page);
  await until(() => q(page, '.bl-check-card').dataset.state === 'retry');
  assert.match(message(page), /try once more/i);
  assert.equal(q(page, '.bl-record').textContent, 'Try once more');
  assertNoLeak(page.main);
  await record(page);
  await until(() => !q(page, '.bl-back').hidden);
  assert.equal(q(page, '.bl-check-card').dataset.state, 'accepted');
  assert.match(message(page), /Thank you, Jamie\./);
  assert.equal(q(page, '.bl-record').hidden, true, 'no third attempt is offered');
  assertNoLeak(page.main);
});

test('a usable second attempt ends with thanks', async () => {
  const page = loadPage('/check?mode=resident&patient=p1&mock=1&fixture=unusable,escalate');
  await until(() => q(page, '.bl-record'));
  await record(page);
  await until(() => q(page, '.bl-check-card').dataset.state === 'retry');
  await record(page);
  await until(() => q(page, '.bl-check-card').dataset.state === 'thanks');
  assertNoLeak(page.main);
});

test('skip (refusal) records nothing and never asks for the microphone', async () => {
  let micAsked = false;
  const page = loadPage('/check?mode=resident&patient=p3',
                        {routes: {'POST /v1/patients/p3/checks': () => ESCALATE}});
  await until(() => q(page, '.bl-skip'));
  const original = page.window.navigator.mediaDevices.getUserMedia;
  page.window.navigator.mediaDevices.getUserMedia = async () => { micAsked = true; return original(); };
  q(page, '.bl-skip').click();
  assert.equal(micAsked, false);
  assert.equal(page.calls.filter((c) => c.key.startsWith('POST')).length, 0);
  assert.match(message(page), /skip today/i);
  assert.match(message(page), /Thank you, Sam\./);
  assert.equal(q(page, '.bl-back').hidden, false);
  assert.match(q(page, '.bl-back').href, /^\/check\?mode=resident$/);
  assertNoLeak(page.main);
});

test('skip while listening discards the clip instead of uploading it', async () => {
  const page = loadPage('/check?mode=resident&patient=p1',
                        {routes: {'POST /v1/patients/p1/checks': () => ESCALATE}});
  await until(() => q(page, '.bl-record'));
  q(page, '.bl-record').click();
  await until(() => q(page, '.bl-check-card').dataset.state === 'listening');
  q(page, '.bl-skip').click();
  await new Promise((r) => setTimeout(r, 30));
  assert.equal(page.calls.filter((c) => c.key.startsWith('POST')).length, 0);
  assert.equal(q(page, '.bl-check-card').dataset.state, 'skipped');
});

test('microphone permission failure asks for staff help without technical detail', async () => {
  const page = loadPage('/check?mode=resident&patient=p1', {mic: 'denied'});
  await until(() => q(page, '.bl-record'));
  q(page, '.bl-record').click();
  await until(() => q(page, '.bl-check-card').dataset.state === 'help');
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
  await until(() => q(page, '.bl-record'));
  await record(page);
  await until(() => q(page, '.bl-check-card').dataset.state === 'help');
  assert.equal(q(page, '.bl-retry').hidden, false);
  assertNoLeak(page.main);
  fail = false;
  q(page, '.bl-retry').click();
  await until(() => q(page, '.bl-check-card').dataset.state === 'thanks');
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

test('only languages with a prompt version are offered; unknown ?lang falls back to English', async () => {
  const page = loadPage('/check?mode=resident&patient=p1&lang=fr');
  await until(() => q(page, '.bl-prompt'));
  assert.equal(q(page, '.bl-prompt').getAttribute('lang'), 'en');
  const options = page.main.querySelectorAll('option').map((o) => o.getAttribute('value'));
  assert.deepEqual(options, ['en']);
});

test('keyboard: every control is a native button or link, Escape stops listening', async () => {
  const page = loadPage('/check?mode=resident&patient=p1&mock=1&fixture=normal');
  await until(() => q(page, '.bl-record'));
  for (const sel of ['.bl-record', '.bl-skip', '.bl-hear', '.bl-retry']) {
    const node = q(page, sel);
    assert.equal(node.tagName, 'BUTTON', sel);
    assert.equal(node.getAttribute('type'), 'button', sel);
  }
  assert.equal(q(page, '.bl-back').tagName, 'A');
  q(page, '.bl-record').click();
  await until(() => q(page, '.bl-check-card').dataset.state === 'listening');
  assert.equal(q(page, '.bl-record').getAttribute('aria-pressed'), 'true');
  q(page, '.bl-check-card').dispatchEvent({type: 'keydown', key: 'Escape'});
  await until(() => q(page, '.bl-check-card').dataset.state === 'thanks');
});

test('PSW landing lists who is due now with no scores, from the real watch list', async () => {
  const today = new Date();
  const yesterday = new Date(today.getTime() - 36 * 3600 * 1000);
  const page = loadPage('/check?mode=resident', {routes: {'GET /v1/watchlist': () => ({
    shift: {start: today.toISOString(), end: today.toISOString(), escalations_used: 1, escalation_budget: 3},
    residents: [
      {patient_id: 'p1', display_name: 'synthetic-1', latest_verdict: 'escalate', fused_z: 3.4,
       last_check_ts: yesterday.toISOString(), sparkline: [{day: '2026-10-16', speech_rate_wpm: 120}],
       watch_window: {open: true, day: 2, of: 7}},
      {patient_id: 'p2', display_name: 'synthetic-2', latest_verdict: 'within_normal', fused_z: 0.4,
       last_check_ts: today.toISOString(), sparkline: [], watch_window: null},
      {patient_id: 'p3', display_name: 'synthetic-3', latest_verdict: null, fused_z: null,
       last_check_ts: null, sparkline: [], watch_window: null}]})}});
  await until(() => q(page, '.bl-due-list'));
  const lists = page.main.querySelectorAll('ul');
  const names = (ul) => ul.querySelectorAll('a').map((a) => a.textContent);
  assert.deepEqual(names(lists[0]), ['Sam Rivera', 'Alex Morgan'], 'never-checked first, then oldest');
  assert.deepEqual(names(lists[1]), ['Jamie Chen']);
  assert.equal(lists[0].querySelector('a').href, '/check?mode=resident&patient=p3');
  assert.equal(page.main.querySelector('.bl-helped'), null, 'no unsupported "observation helped" claim');
  assert.match(exposedText(page.main), /consent/i);
  const shown = exposedText(page.main).replace(/\b(One resident|\d+ residents) still to check today\./, '');
  for (const pattern of LEAKS) assert.doesNotMatch(shown, pattern);
});

test('"Your observation helped" appears only when the server says so', () => {
  const page = loadPage('/check?mode=live&mock=1');
  const items = page.ctx.dueNowItems([
    {patient_id: 'a', display_name: 'A', last_check_ts: null, observation_helped: true},
    {patient_id: 'b', display_name: 'B', last_check_ts: null, observation_helped: 'yes'},
    {patient_id: 'c', display_name: 'C', last_check_ts: null}], []);
  assert.deepEqual(items.map((i) => i.observation_helped), [true, false, false]);
});

test('PSW landing load failure shows a plain message', async () => {
  const page = loadPage('/check?mode=resident', {routes: {'GET /v1/watchlist': () => {
    throw Object.assign(new Error('boom'), {status: 500}); }}});
  await until(() => q(page, '.bl-due-status')
    && /could not be loaded/.test(q(page, '.bl-due-status').textContent));
  assert.doesNotMatch(exposedText(page.main), /500|boom|watchlist/);
});

test('mock landing keeps the synthetic fixture path and carries mock params to each check', async () => {
  const page = loadPage('/check?mode=resident&mock=1&fixture=unusable,normal');
  await until(() => q(page, '.bl-due-list'));
  assert.equal(page.calls.filter((c) => c.key === 'GET /v1/watchlist').length, 0);
  const href = q(page, '.bl-due-item').href;
  assert.equal(new URLSearchParams(href.split('?')[1]).get('fixture'), 'unusable,normal');
});

test('live mode still shows the decomposition and reads params.baseline_checks', async () => {
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
