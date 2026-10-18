const {test} = require('node:test');
const assert = require('node:assert/strict');
const {loadPage, until, FakeRecorder} = require('./harness.js');

test('/out uses the KAZE bootstrap and renders a complete arm form without tokens in the URL', async () => {
  const h = loadPage('/out', {kaze: true, routes: {'GET /v1/patients/p1/sessions': () => ({sessions: []})}});
  await until(() => h.main.querySelector('form'));
  const bootstrap = h.calls.find((c) => c.key === 'GET /demo/session');
  assert.equal(bootstrap.opts.headers['X-PM-Role'], 'kaze');
  assert.match(h.main.textContent, /Contact 1/);
  assert.match(h.main.textContent, /Contact 2/);
  assert.match(h.main.textContent, /5 minutes overdue/);
  assert.equal(h.main.querySelector('[name=interval]').value, '45');
  assert.equal(h.calls.some((c) => /watchlist|overview/.test(c.key)), false);
});

test('judge timeline shows actual server delivery and acknowledgement timing; ended cannot record', async () => {
  const session = {id: 's1', status: 'ended', interval_min: 45, episode: 1,
    created_at: '2026-10-17T01:00:00Z', ends_at: '2026-10-17T02:00:00Z',
    ended_at: '2026-10-17T02:00:00Z', end_reason: 'expired', baseline: {required: 3, usable: 3},
    contacts: [{contact_index: 1, name: 'Contact'}], checks: [], escalations: [
      {channel: 'sms', level: 2, episode: 1, contact_index: 1, trigger: 'missed_checkin',
        delivery: 'logged', sent_at: '2026-10-17T01:50:00Z', ack_at: '2026-10-17T01:51:00Z'}]};
  const h = loadPage('/out/session/s1', {kaze: true, routes: {
    'GET /v1/patients/p1/sessions': () => ({sessions: [session]}),
    'GET /v1/patients/p1/sessions/s1': () => session}});
  await until(() => /Session timeline/.test(h.main.textContent));
  assert.match(h.main.textContent, /no SMS was sent/);
  assert.doesNotMatch(h.main.textContent, /after the first text|Text to Contact/);
  assert.match(h.main.textContent, /acknowledged 1 min after first contact escalation attempt/);
  assert.equal(h.main.querySelector('.kaze-record').disabled, true);
  h.main.querySelector('.kaze-record').click();
  assert.equal(h.calls.some((c) => /checks$/.test(c.key)), false);
  for (const f of h.window.listeners.pagehide || []) f();
});

test('three actual page recordings enroll then switch to normal check-in fields', async () => {
  const session = {id: 's1', status: 'arming', interval_min: 45, episode: 0,
    created_at: new Date().toISOString(), ends_at: new Date(Date.now() + 3600000).toISOString(),
    baseline: {required: 3, usable: 0}, contacts: [], checks: [], escalations: []};
  const received = [];
  const h = loadPage('/out', {kaze: true, routes: {
    'GET /v1/patients/p1/sessions': () => ({sessions: [session]}),
    'GET /v1/patients/p1/sessions/s1': () => session,
    'POST /v1/patients/p1/checks': (opts) => {
      received.push(Object.fromEntries(opts.body.entries()));
      if (session.status === 'arming') {
        session.baseline.usable++;
        if (session.baseline.usable === 3) {
          session.status = 'active'; session.activated_at = new Date().toISOString();
          session.next_due_at = new Date(Date.now() + 2700000).toISOString();
        }
      }
      return {usable: true, quality: {duration_s: 15, reasons: []}, timings_ms: {}, features: {},
        words: [], pauses: [], change: {status: 'enrolling', params: {baseline_checks: session.baseline.usable}},
        assessment: {verdict: 'enrolling', reasons: []}};
    }}});
  try {
    await until(() => /Record baseline/.test(h.main.textContent));
    assert.match(h.main.textContent, /Count from one to twenty/);
    for (let n = 1; n <= 4; n++) {
      const button = h.main.querySelector('.kaze-record'); button.click();
      await until(() => FakeRecorder.last && FakeRecorder.last.state === 'recording');
      button.click();
      await until(() => received.length === n && /Check-in saved/.test(h.main.textContent));
      // Let the post-result refresh complete before the next recording.
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
    assert.deepEqual(received.map((r) => r.is_baseline), ['true', 'true', 'true', 'false']);
    assert.ok(received.every((r) => r.session_id === 's1' && !('lat' in r)));
    assert.match(h.main.textContent, /Next check-in/);
  } finally { for (const f of h.window.listeners.pagehide || []) f(); }
});

test('a stale in-flight session read cannot reopen recording after the end response', async () => {
  const active = {id: 's1', status: 'active', ends_at: new Date(Date.now() + 3600000).toISOString(),
    created_at: new Date().toISOString(), interval_min: 45, episode: 0,
    baseline: {required: 3, usable: 3}, contacts: [], checks: [], escalations: []};
  let resolveRead;
  const pending = new Promise((resolve) => { resolveRead = resolve; });
  const h = loadPage('/out', {kaze: true, routes: {
    'GET /v1/patients/p1/sessions': () => ({sessions: [active]}),
    'GET /v1/patients/p1/sessions/s1': () => pending,
    'POST /v1/patients/p1/sessions/s1/end': () => ({...active, status: 'ended'})}});
  try {
    await until(() => h.main.querySelector('.kaze-record'));
    const end = [...h.main.querySelectorAll('button')].find((b) => b.textContent === 'End session');
    end.click(); await until(() => /Session ended/.test(h.main.textContent));
    resolveRead(active); await new Promise((resolve) => setTimeout(resolve, 30));
    assert.equal(h.main.querySelector('.kaze-record').disabled, true);
    assert.match(h.main.textContent, /Session ended/);
    assert.doesNotMatch(h.main.textContent, /Loading session/);
  } finally { for (const f of h.window.listeners.pagehide || []) f(); }
});


test('recording hint follows stored loud-venue context only while the session is open', async () => {
  for (const [context_tags, status, expected] of [
    [[], 'active', false], [['exertion'], 'active', false],
    [['loud_venue'], 'active', true], [['loud_venue'], 'arming', true],
    [['loud_venue'], 'ended', false],
  ]) {
    const session = {id: 's1', status, interval_min: 45, episode: 0, context_tags,
      created_at: new Date().toISOString(), ends_at: new Date(Date.now() + 3600000).toISOString(),
      next_due_at: new Date(Date.now() + 2700000).toISOString(),
      baseline: {required: 3, usable: status === 'arming' ? 0 : 3},
      contacts: [], checks: [], escalations: []};
    const h = loadPage('/out/session/s1', {kaze: true, routes: {
      'GET /v1/patients/p1/sessions': () => ({sessions: [session]}),
      'GET /v1/patients/p1/sessions/s1': () => session}});
    try {
      await until(() => /Session timeline/.test(h.main.textContent));
      assert.equal(h.main.textContent.includes('Step outside to answer'), expected);
    } finally {
      for (const f of h.window.listeners.pagehide || []) f();
    }
  }
});
