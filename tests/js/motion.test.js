const {test} = require('node:test');
const assert = require('node:assert/strict');
const core = require('../../frontend/motion-core.js');
const {MotionCapture} = require('../../frontend/motion-capture.js');

function fixture({rise = true, steps = true} = {}) {
  return Array.from({length: 100}, (_, i) => {
    const t = i / 10;
    const points = Array.from({length: 33}, () => ({x: .5, y: .5, visibility: .99, presence: .99}));
    const hip = rise ? .7 - .25 * Math.min(1, Math.max(0, (t - 2) / 2)) : .7;
    points[23].y = points[24].y = hip;
    points[11].x = .4 + .01 * Math.sin(t * 2);
    points[12].x = .6 + .01 * Math.sin(t * 2);
    for (const [index, times] of [[27, [5, 7]], [28, [6]]]) {
      const lift = steps ? Math.max(...times.map((peak) => Math.max(0, 1 - Math.abs(t - peak) / .4))) : 0;
      points[index].y = .95 - lift * .08;
    }
    return {t, landmarks: points};
  });
}

test('known synthetic chair rise and three ankle peaks produce three bounded measurements', () => {
  const result = core.measure(fixture(), 10);
  assert.equal(result.quality.confident_frames, 100);
  assert.ok(result.features.sit_to_stand_s >= .5 && result.features.sit_to_stand_s <= 1.2);
  assert.ok(result.features.trunk_sway > .01 && result.features.trunk_sway < .1);
  assert.ok(Math.abs(result.features.step_cadence_spm - 60) < .01);
  assert.deepEqual(Object.keys(result).sort(), ['features', 'quality']);
});

test('incomplete rise or steps remain unknown and low confidence cannot fabricate numbers', () => {
  assert.equal(core.measure(fixture({rise: false}), 10).features.sit_to_stand_s, null);
  assert.equal(core.measure(fixture({steps: false}), 10).features.step_cadence_spm, null);
  for (const invalid of [20, 21]) {
    const frames = fixture();
    for (let i = 0; i < invalid; i++) frames[i].landmarks[27].visibility = .1;
    const measured = core.measure(frames, 10);
    assert.equal(measured.quality.confident_frames, 100 - invalid);
    if (invalid === 20) assert.notEqual(measured.features.step_cadence_spm, null);
    else assert.deepEqual(Object.values(measured.features), [null, null, null]);
  }
  const missing = fixture(); missing[0].landmarks[11].x = NaN;
  assert.equal(core.measure(missing, 10).quality.confident_frames, 99);
});

class WorkerStub {
  constructor(url, options) { this.url = url; this.options = options; this.messages = []; }
  postMessage(data) {
    this.messages.push(data);
    if (data.bitmap) data.bitmap.close();
    queueMicrotask(() => this.onmessage({data: {id: data.id, ready: true, landmarks: null}}));
  }
  terminate() { this.terminated = true; }
}

test('camera capture requests no audio, stops every track, and only local geometry leaves capture', async () => {
  let now = 0, stopped = 0, bitmapClosed = 0, options;
  const video = {currentTime: 0, readyState: 2, play: async () => {}};
  const capture = new MotionCapture(video, {Worker: WorkerStub, core,
    now: () => now,
    mediaDevices: {getUserMedia: async (value) => {
      options = value; return {getTracks: () => [{stop: () => stopped++}]};
    }}, bitmap: async () => ({close: () => bitmapClosed++}),
    nextFrame: async () => { now += 100; video.currentTime += .1; }});
  await capture.warm();
  assert.equal(capture.worker.url, '/assets/motion-worker.js');
  const result = await capture.capture();
  assert.equal(options.audio, false);
  assert.equal(stopped, 1); assert.equal(video.srcObject, null);
  assert.equal(bitmapClosed, 100);
  assert.deepEqual(Object.keys(result).sort(), ['features', 'quality']);
  assert.equal(result.quality.duration_s, 10);
  assert.equal('frames' in result, false); assert.equal('landmarks' in result, false);
  capture.cancel(); assert.equal(capture.worker.terminated, true);
});

test('cancellation during permission prompt stops a late stream without analyzing it', async () => {
  let allow, stopped = 0;
  const video = {play: async () => { throw new Error('must not play'); }};
  const capture = new MotionCapture(video, {Worker: WorkerStub, core,
    mediaDevices: {getUserMedia: () => new Promise((resolve) => { allow = resolve; })}});
  await capture.warm();
  const pending = capture.capture(); capture.cancel();
  allow({getTracks: () => [{stop: () => stopped++}]});
  assert.equal(await pending, null); assert.equal(stopped, 1);
  assert.equal(capture.pending.size, 0);
});
