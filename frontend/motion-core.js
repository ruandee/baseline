// Client-derived geometry only. No diagnosis, video serialization or network access.
(function(root) {
  'use strict';
  const REQUIRED = [11, 12, 23, 24, 27, 28];
  const median = (values) => {
    const v = [...values].sort((a, b) => a - b);
    const m = Math.floor(v.length / 2);
    return v.length ? (v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2) : null;
  };
  function confident(landmarks) {
    return landmarks && REQUIRED.every((i) => {
      const p = landmarks[i];
      return p && Number.isFinite(p.x) && Number.isFinite(p.y)
        && p.x >= 0 && p.x <= 1 && p.y >= 0 && p.y <= 1
        && p.visibility >= .5 && p.presence >= .5;
    });
  }
  function smooth(values) {
    return values.map((_, i) => median(values.slice(Math.max(0, i - 1), i + 2)));
  }
  function measure(frames, durationS) {
    const ordered = frames.filter((f) => Number.isFinite(f.t) && f.t >= 0 && f.t <= 10)
      .filter((f, i, a) => i === 0 || f.t > a[i - 1].t);
    const valid = ordered.filter((f) => confident(f.landmarks));
    const quality = {duration_s: Math.min(12, Math.max(0, durationS)),
      total_frames: ordered.length, confident_frames: valid.length};
    const features = {sit_to_stand_s: null, trunk_sway: null, step_cadence_spm: null};
    if (valid.length < 20 || valid.length / Math.max(1, ordered.length) < .8)
      return {quality, features};
    const hip = smooth(valid.map((f) => (f.landmarks[23].y + f.landmarks[24].y) / 2));
    const start = median(hip.filter((_, i) => valid[i].t <= valid[0].t + .8));
    const finish = median(hip.filter((_, i) => valid[i].t >= valid.at(-1).t - .8));
    const travel = start - finish;
    let stoodAt = null;
    if (travel >= .05) {
      const onset = hip.findIndex((y, i) => valid[i].t >= .8 && y <= start - .1 * travel);
      const halfway = hip.findIndex((y, i) => i > onset && y <= start - .5 * travel);
      if (onset >= 0 && halfway > onset) {
        const elapsed = valid[halfway].t - valid[onset].t;
        if (elapsed > 0 && elapsed <= 10) {
          features.sit_to_stand_s = elapsed;
          stoodAt = valid[halfway].t;
        }
      }
    }
    if (stoodAt === null) return {quality, features};
    const standing = valid.filter((f) => f.t >= stoodAt);
    const widths = standing.map((f) => Math.abs(f.landmarks[11].x - f.landmarks[12].x));
    const width = median(widths);
    if (standing.length >= 3 && width >= .03) {
      const x = standing.map((f) => (f.landmarks[11].x + f.landmarks[12].x) / 2);
      const mean = x.reduce((a, b) => a + b, 0) / x.length;
      const sway = Math.sqrt(x.reduce((a, b) => a + (b - mean) ** 2, 0) / x.length) / width;
      if (sway <= 5) features.trunk_sway = sway;
    }
    const peaks = [];
    for (const ankle of [27, 28]) {
      const heights = smooth(standing.map((f) => -f.landmarks[ankle].y));
      let last = -Infinity;
      for (let i = 1; i < heights.length - 1; i++) {
        if (heights[i] > heights[i - 1] && heights[i] >= heights[i + 1]
            && heights[i] - Math.min(...heights.slice(Math.max(0, i - 4), i)) >= .01
            && standing[i].t - last >= .25) {
          peaks.push(standing[i].t); last = standing[i].t;
        }
      }
    }
    const distinct = peaks.sort((a, b) => a - b).filter((t, i, a) => !i || t - a[i - 1] >= .2);
    if (distinct.length >= 3) {
      const cadence = 60 * (distinct.length - 1) / (distinct.at(-1) - distinct[0]);
      if (Number.isFinite(cadence) && cadence > 0 && cadence <= 360)
        features.step_cadence_spm = cadence;
    }
    return {quality, features};
  }
  const api = {measure, confident};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.MotionCore = api;
})(typeof window !== 'undefined' ? window : globalThis);
