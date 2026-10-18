const assert = require('node:assert/strict');
const {test} = require('node:test');
const capture = require('../../frontend/kaze-capture.js');
const core = require('../../frontend/kaze-core.js');
const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };
const defer = () => {
  let resolve, reject;
  const promise = new Promise((a, b) => { resolve = a; reject = b; });
  return {resolve, reject, promise};
};

function setup(opts = {}) {
  let time = 1000, stopped = 0, locations = 0, reads = 0;
  let session = {id: 'session-one', status: 'arming', ends_at: new Date(100000).toISOString()};
  const uploads = [], states = [], timers = [];
  const media = {getTracks: () => [{stop() { stopped++; }}]};
  let recorder;
  class Recorder {
    constructor() { recorder = this; this.state = 'inactive'; this.mimeType = 'audio/webm'; }
    start() { this.state = 'recording'; }
    stop() { this.state = 'inactive'; this.ondataavailable({data: new Blob(['synthetic'])}); this.onstop(); }
  }
  const controller = capture({getSession: opts.getSession || (async () => { reads++; return session; }),
    getMedia: opts.getMedia || (async () => media), Recorder,
    locate: opts.locate || (async () => { locations++; return {coords: {latitude: 1, longitude: 2, accuracy: 3}}; }),
    upload: async (blob, fields) => { uploads.push(fields); return {usable: true}; },
    onState: (text) => states.push(text), now: () => time,
    later: (fn, ms) => { timers.push({fn, ms}); return timers.length; }, cancelLater: () => {}});
  return {controller, uploads, states, timers, media, expire: () => { time = 100000; },
    change: (updates) => { session = {...session, ...updates}; },
    reads: () => reads, stopped: () => stopped, locations: () => locations,
    recorder: () => recorder,
    recording: () => recorder && recorder.state === 'recording'};
}

test('baseline capture sends session and baseline fields, without requesting location by default', async () => {
  const h = setup(); await h.controller.start(false); assert.ok(h.recording());
  assert.equal(h.timers[0].ms, 15000);
  h.controller.stop(); await flush();
  assert.equal(h.uploads.length, 1);
  assert.equal(h.uploads[0].session_id, 'session-one');
  assert.equal(h.uploads[0].is_baseline, 'true');
  assert.equal(h.locations(), 0); assert.equal('lat' in h.uploads[0], false);
  assert.ok(h.stopped() > 0); assert.equal(h.reads(), 2);
});

test('active check-in includes location only after explicit opt-in', async () => {
  const h = setup(); h.change({status: 'active'});
  await h.controller.start(true); h.controller.stop(); await flush();
  assert.equal(h.uploads[0].is_baseline, 'false');
  assert.equal(h.locations(), 1); assert.equal(h.uploads[0].lat, 1);
});

test('pending microphone permission resolving after end is stopped without recording or uploading', async () => {
  const pending = defer(); const h = setup({getMedia: () => pending.promise});
  const start = h.controller.start(false); await flush();
  h.controller.cancel(); pending.resolve(h.media); await start;
  assert.equal(h.recording(), undefined); assert.equal(h.uploads.length, 0); assert.ok(h.stopped() > 0);
});

test('clock expiry during microphone permission prevents recording even before server refresh', async () => {
  const pending = defer(); const h = setup({getMedia: () => pending.promise});
  const start = h.controller.start(false); await flush(); h.expire(); pending.resolve(h.media); await start;
  assert.equal(h.uploads.length, 0); assert.ok(h.stopped() > 0); assert.equal(h.recording(), undefined);
});

test('obsolete first session read cannot release the next active capture', async () => {
  const oldRead = defer(); let reads = 0;
  const valid = {id: 'session-one', status: 'active', ends_at: new Date(100000).toISOString()};
  const h = setup({getSession: () => ++reads === 1 ? oldRead.promise : Promise.resolve(valid)});
  const first = h.controller.start(false); await flush(); h.controller.cancel();
  await h.controller.start(false); assert.ok(h.recording());
  const before = h.stopped(); oldRead.resolve(valid); await first;
  assert.equal(h.stopped(), before); assert.ok(h.recording()); h.controller.cancel();
});

test('obsolete rejected microphone permission cannot release the next active capture', async () => {
  const pending = defer(); let requests = 0;
  let stopped = 0;
  const h = setup({getMedia: () => ++requests === 1 ? pending.promise : Promise.resolve({
    getTracks: () => [{stop() { stopped++; }}]})});
  const first = h.controller.start(false); await flush(); h.controller.cancel();
  await h.controller.start(false); assert.ok(h.recording());
  pending.reject(new Error('old permission failed')); await first;
  assert.equal(stopped, 0); assert.ok(h.recording()); h.controller.cancel();
});

test('delayed stop and error callbacks from a cancelled recorder cannot stop its replacement', async () => {
  const h = setup(); await h.controller.start(false);
  const obsolete = h.recorder();
  obsolete.stop = function() { this.state = 'inactive'; }; // browser queues stop asynchronously
  h.controller.cancel(); await h.controller.start(false);
  const before = h.stopped();
  await obsolete.onstop(); obsolete.onerror(); await flush();
  assert.equal(h.stopped(), before); assert.ok(h.recording()); assert.equal(h.uploads.length, 0);
  h.controller.cancel();
});

test('ending while location permission is pending never submits the recording or coordinates', async () => {
  const pending = defer(); const h = setup({locate: () => pending.promise});
  await h.controller.start(true); h.controller.stop(); await flush(); h.controller.cancel();
  pending.resolve({coords: {latitude: 1, longitude: 2, accuracy: 3}}); await flush();
  assert.equal(h.uploads.length, 0);
});

test('expiry before stop, ended server state and changed enrollment all prevent publication', async () => {
  for (const update of ['clock', 'ended', 'active']) {
    const h = setup(); await h.controller.start(false);
    if (update === 'clock') h.expire(); else h.change({status: update});
    h.controller.stop(); await flush(); assert.equal(h.uploads.length, 0, update);
  }
});

test('denied location continues without coordinates; denied microphone cannot upload', async () => {
  const h = setup({locate: async () => null}); await h.controller.start(true); h.controller.stop(); await flush();
  assert.equal(h.uploads.length, 1); assert.equal('lat' in h.uploads[0], false);
  const denied = setup({getMedia: async () => { throw new Error('denied'); }});
  await denied.controller.start(true); assert.equal(denied.uploads.length, 0);
});

test('countdown uses server due time and does not compress five-minute escalation', () => {
  const now = new Date('2026-10-18T00:00:00Z');
  assert.equal(core.countdown('2026-10-18T00:01:00Z', now).seconds, 60);
  assert.equal(core.countdown('2026-10-17T23:59:00Z', now).overdue, true);
});

test('timeline labels log-only delivery honestly and removes location and acknowledgement links', () => {
  const s = {status: 'escalating', episode: 1, interval_min: 45, created_at: '2026-10-18T00:00:00Z',
    ends_at: '2026-10-18T03:00:00Z', contacts: [{contact_index: 1, name: 'Contact'}],
    escalations: [{episode: 1, channel: 'sms', level: 2, trigger: 'missed_checkin', delivery: 'logged',
      contact_index: 1, sent_at: '2026-10-18T00:50:00Z', ack_at: '2026-10-18T00:51:00Z',
      message: 'Check https://host/ack/secret https://maps.google.com/?q=43.65,-79.38'}]};
  const rows = core.timeline(s); const text = rows.find((r) => r.kind === 'text');
  assert.match(text.detail, /no SMS was sent/); assert.doesNotMatch(text.message, /secret|43.65/);
  assert.equal(core.timeToAck(s)[0].seconds, 60);
  assert.doesNotMatch(core.personView(s).headline, /sent|alerted/);
});
