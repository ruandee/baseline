'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {loadPage, until, tick, FakeRecorder} = require('./harness');

const start = () => loadPage('/check?mode=live&demo=archived-days');
const q = (page, selector) => page.main.querySelector(selector);
function loadClip(page, duration = 24.94) {
  const input = q(page, '.bl-demo-file');
  const clip = new Blob(['local-audio'], {type: 'audio/wav'});
  clip.name = 'normal.wav';
  input.files = [clip];
  input.dispatchEvent({type: 'change'});
  const audio = q(page, 'audio');
  audio.duration = duration;
  audio.dispatchEvent({type: 'loadedmetadata'});
}

test('three simulated days reveal watch/explained/escalate with no session, API or persistence', () => {
  const page = start();
  assert(q(page, '.bl-demo-next').disabled);
  assert.match(page.main.textContent, /SIMULATED DEMO RESULTS/);
  assert.match(page.main.textContent, /not computed from your voice/);
  for (const [index, verdict] of ['watch', 'explained', 'escalate'].entries()) {
    assert.match(q(page, '.bl-demo-day').textContent, new RegExp(`day ${index + 1}`));
    assert.equal(q(page, '.bl-demo-result').getAttribute('data-verdict'), null);
    loadClip(page);
    assert.equal(q(page, '.bl-demo-result').dataset.verdict, verdict);
    assert.match(q(page, '.bl-demo-receipt').textContent, /Loaded prerecorded clip/);
    assert.match(q(page, '.bl-demo-receipt').textContent, /recording time unknown/);
    assert.match(q(page, '.bl-demo-result').textContent, /not an assessment of the person/);
    assert.match(q(page, '.bl-demo-result').textContent, /Authored baseline/);
    if (index < 2) {
      assert(!q(page, '.bl-demo-next').disabled);
      q(page, '.bl-demo-next').click();
      assert.equal(q(page, 'audio'), null, 'prior-day audio must be cleared');
      assert(q(page, '.bl-demo-next').disabled);
    }
  }
  assert(q(page, '.bl-demo-next').disabled);
  q(page, '.bl-demo-reset').click();
  assert.match(q(page, '.bl-demo-day').textContent, /day 1/);
  assert.equal(q(page, 'audio'), null);
  assert.equal(q(page, '.bl-demo-result').textContent, '');
  assert.equal(page.calls.length, 0);
  assert.equal(page.window.stored.size, 0);
});

test('an overlong clip reveals no result and cannot advance the simulated day', () => {
  const page = start();
  loadClip(page, 31);
  assert.match(q(page, '.bl-demo-status').textContent, /no longer than 30 seconds/);
  assert.equal(q(page, '.bl-demo-result').textContent, '');
  assert(q(page, '.bl-demo-next').disabled);
  assert.equal(page.calls.length, 0);
});

test('resident mode does not accidentally enter the scored fictional presentation', async () => {
  const page = loadPage('/check?mode=resident&demo=archived-days&patient=p1');
  await until(() => q(page, '.bl-record'));
  assert.equal(q(page, '.bl-demo-banner'), null);
  assert(page.calls.some((call) => call.key === 'GET /demo/session'));
});

test('reset while microphone permission is pending discards the eventual stream', async () => {
  const page = start();
  let allow;
  let stopped = 0;
  const previous = FakeRecorder.last;
  page.window.navigator.mediaDevices.getUserMedia = () => new Promise((resolve) => { allow = resolve; });
  q(page, '.bl-demo-record').click();
  q(page, '.bl-demo-reset').click();
  allow({getTracks: () => [{stop() { stopped += 1; }}]});
  await tick(20);
  assert.equal(FakeRecorder.last, previous);
  assert.equal(stopped, 1);
  assert.equal(q(page, 'audio'), null);
  assert.equal(q(page, '.bl-demo-result').textContent, '');
  assert.equal(page.calls.length, 0);
});

test('microphone denial stays on the current day without fabricating a recording or result', async () => {
  const page = start();
  page.window.navigator.mediaDevices.getUserMedia = async () => { throw new Error('denied'); };
  q(page, '.bl-demo-record').click();
  await until(() => q(page, '.bl-demo-status').textContent.includes('Could not start'));
  assert.equal(q(page, '.bl-demo-result').textContent, '');
  assert(q(page, '.bl-demo-next').disabled);
  assert.equal(page.calls.length, 0);
});

test('late file metadata after reset cannot restore a recording or scripted result', () => {
  const page = start();
  const input = q(page, '.bl-demo-file');
  const clip = new Blob(['clip'], {type: 'audio/wav'});
  clip.name = 'normal.wav'; input.files = [clip]; input.dispatchEvent({type: 'change'});
  const staleAudio = q(page, 'audio');
  q(page, '.bl-demo-reset').click();
  staleAudio.duration = 25; staleAudio.dispatchEvent({type: 'loadedmetadata'});
  assert.equal(q(page, 'audio'), null);
  assert.equal(q(page, '.bl-demo-result').textContent, '');
  assert(q(page, '.bl-demo-next').disabled);
});

test('live capture auto-stops at 30 seconds, has real recording time, and clears tracks/URLs on exit', async () => {
  const page = start();
  let stopped = 0;
  let timer;
  const revoked = [];
  const NativeURL = page.window.URL;
  page.window.URL = {createObjectURL: (blob) => NativeURL.createObjectURL(blob),
    revokeObjectURL: (url) => { revoked.push(url); NativeURL.revokeObjectURL(url); }};
  page.window.navigator.mediaDevices.getUserMedia = async () => ({getTracks: () => [{stop() { stopped += 1; }}]});
  page.window.setTimeout = (fn, ms) => { timer = {fn, ms}; return timer; };
  page.window.clearTimeout = () => {};
  q(page, '.bl-demo-record').click();
  await until(() => timer);
  assert.equal(timer.ms, 30000);
  timer.fn();
  await until(() => q(page, '.bl-demo-receipt'));
  assert.match(q(page, '.bl-demo-receipt').textContent, /Captured live in this browser/);
  assert.match(q(page, '.bl-demo-receipt').textContent, /recorded/);
  assert.equal(q(page, '.bl-demo-result').dataset.verdict, 'watch');
  assert(stopped > 0);
  page.window.listeners.pagehide.forEach((fn) => fn());
  assert.equal(revoked.length, 1);
  assert.equal(q(page, 'audio'), null);
  assert.equal(q(page, '.bl-demo-result').textContent, '');
  assert.equal(page.calls.length, 0);
});

test('late old recorder stop cannot cancel the new recording auto-stop after restart', async () => {
  const page = start();
  const timers = [];
  const tracks = [];
  const revoked = [];
  const NativeURL = page.window.URL;
  page.window.URL = {createObjectURL: blob => NativeURL.createObjectURL(blob),
    revokeObjectURL: url => { revoked.push(url); NativeURL.revokeObjectURL(url); }};
  page.window.setTimeout = (fn, ms) => {
    const timer = {fn, ms, cancelled: false}; timers.push(timer); return timer;
  };
  page.window.clearTimeout = timer => { if (timer) timer.cancelled = true; };
  page.window.navigator.mediaDevices.getUserMedia = async () => {
    const track = {stops: 0, stop() { this.stops++; }}; tracks.push(track);
    return {getTracks: () => [track]};
  };
  q(page, '.bl-demo-record').click();
  await until(() => timers.length === 1);
  const old = FakeRecorder.last;
  let lateStop;
  old.stop = () => { old.state = 'inactive'; lateStop = () => old.onstop(); };
  q(page, '.bl-demo-reset').click();
  assert(timers[0].cancelled);
  q(page, '.bl-demo-record').click();
  await until(() => timers.length === 2);
  const current = FakeRecorder.last;
  assert.notEqual(current, old);
  const timer = timers[1];
  assert.equal(timer.ms, 30000);
  lateStop();
  assert.equal(timer.cancelled, false, 'discarded callback must not touch the current timer');
  assert.equal(current.state, 'recording');
  assert.equal(tracks[1].stops, 0, 'discarded callback must not stop the new stream');
  assert.equal(q(page, '.bl-demo-result').textContent, '');
  timer.fn();
  await until(() => q(page, '.bl-demo-result').dataset.verdict === 'watch');
  assert.equal(current.state, 'inactive');
  assert(tracks[0].stops > 0 && tracks[1].stops > 0);
  page.window.listeners.pagehide.forEach(fn => fn());
  assert.equal(q(page, 'audio'), null);
  assert.equal(revoked.length, 1);
  assert.equal(page.calls.length, 0);
});
