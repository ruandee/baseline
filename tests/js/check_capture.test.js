'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {loadPage, until, FakeRecorder} = require('./harness');

for (const mode of ['live', 'runner', 'resident']) {
  test(`${mode} capture stays active past 15 seconds and stops/uploads once at 30`, async () => {
    const page = loadPage(`/check?mode=${mode}&patient=p1&device=dee-demo-phone`, {routes: {
      'POST /v1/patients/p1/checks': () => ({usable: false, quality: {reasons: ['too_little_speech']}}),
    }});
    await until(() => page.main.querySelector('.bl-record'));
    const timers = [];
    const intervals = [];
    let now = Date.now();
    page.window.Date = class extends Date { static now() { return now; } };
    page.window.setTimeout = (fn, ms) => { const t = {fn, ms}; timers.push(t); return t; };
    page.window.clearTimeout = (t) => { if (t) t.cancelled = true; };
    page.window.setInterval = (fn) => { intervals.push(fn); return fn; };
    page.window.clearInterval = () => {};
    page.main.querySelector('.bl-record').click();
    await until(() => FakeRecorder.last && FakeRecorder.last.state === 'recording');
    const limit = timers.find((t) => t.ms === 30000);
    assert(limit, 'capture must schedule the 30-second limit');
    const posts = () => page.calls.filter((c) => c.key === 'POST /v1/patients/p1/checks');
    now += 15000;
    intervals.forEach((fn) => fn());
    assert.equal(FakeRecorder.last.state, 'recording');
    assert.equal(posts().length, 0);
    now += 15000;
    limit.fn();
    await until(() => posts().length === 1);
    assert.equal(FakeRecorder.last.state, 'inactive');
    assert.equal(posts()[0].opts.body.get('is_baseline'), 'false');
    assert.equal(posts()[0].opts.body.get('device_id'), 'dee-demo-phone');
  });
}
