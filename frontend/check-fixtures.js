// Fixture responses for POST /v1/patients/{id}/checks, shaped like docs/06-baseline.md.
// Used only when /check is opened with ?mock=1 (BL-07 has not landed); never contacts the API.
(function () {
  const WORDS = ['one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten',
                 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen',
                 'eighteen', 'nineteen', 'twenty', 'Monday', 'Tuesday', 'Wednesday', 'Thursday',
                 'Friday', 'Saturday', 'Sunday'];
  const words = WORDS.map((w, i) => {
    const start = +(0.3 + i * 0.34 + (i >= 20 ? 0.5 : 0)).toFixed(2);
    return {w, start, end: +(start + 0.26).toFixed(2)};
  });
  const pauses = [{start: 7.1, end: 7.8}, {start: 9.4, end: 10.0}];
  const timings = {normalize: 180, vad: 40, asr: 2900, prosody: 300, engine: 15, verdict: 20};
  const usableQuality = {duration_s: 10.4, speech_s: 8.1, snr_db: 21.5, clipped: false, reasons: []};
  const feature = (value, median, mad, z, ewma, cusum) => ({value, median, mad, z, ewma, cusum});
  const params = {z_threshold: 2.0, provisional_z: 3.0, min_features: 2, consecutive: 2,
                  mad_floor_pct: 0.05};
  const base = {check_id: 'fixture-check', ts: '2026-10-18T14:12:03Z', usable: true,
                quality: usableQuality, words, pauses, timings_ms: timings};

  window.CHECK_FIXTURES = {
    normal: {...base,
      features: {speech_rate_wpm: 158.0, pause_ratio: 0.2, mean_pause_s: 0.4, f0_median_hz: 214.0},
      change: {status: 'none', mode: 'rolling', fused_z: 0.3, params, per_feature: {
        speech_rate_wpm: feature(158.0, 158.0, 6.1, 0.0, 0.1, 0.2),
        pause_ratio: feature(0.2, 0.21, 0.02, -0.5, 0.0, 0.0),
        mean_pause_s: feature(0.4, 0.4, 0.04, 0.0, 0.0, 0.0),
        f0_median_hz: feature(214.0, 212.0, 4.0, 0.5, 0.2, 0.1)}}},
    change: {...base,
      features: {speech_rate_wpm: 132.0, pause_ratio: 0.31, mean_pause_s: 0.55, f0_median_hz: 214.0},
      change: {status: 'change', mode: 'enrolled', fused_z: 2.7, params, per_feature: {
        speech_rate_wpm: feature(132.0, 158.0, 6.1, -2.84, -2.1, 3.9),
        pause_ratio: feature(0.31, 0.21, 0.02, 3.2, 2.0, 3.1),
        mean_pause_s: feature(0.55, 0.4, 0.04, 2.4, 1.6, 2.0),
        f0_median_hz: feature(214.0, 212.0, 4.0, 0.5, 0.2, 0.1)}},
      assessment: {id: 'fixture-assessment', verdict: 'explained', suggested_action: 'none',
        reasons: [{kind: 'explainer', tag: 'exertion', context_tag_id: 'fixture-tag',
                   label: 'Running the Toronto marathon'}]}},
    escalate: {...base,
      features: {speech_rate_wpm: 118.0, pause_ratio: 0.34, mean_pause_s: 0.6, f0_median_hz: 205.0},
      change: {status: 'change', mode: 'rolling', fused_z: 3.1, params, per_feature: {
        speech_rate_wpm: feature(118.0, 158.0, 6.1, -4.4, -3.0, 5.0),
        pause_ratio: feature(0.34, 0.21, 0.02, 4.1, 3.0, 4.0),
        mean_pause_s: feature(0.6, 0.4, 0.04, 3.3, 2.1, 2.5),
        f0_median_hz: feature(205.0, 212.0, 4.0, -1.1, -0.4, 0.6)}},
      assessment: {id: 'fixture-assessment', verdict: 'escalate', suggested_action: '4at_now',
        reasons: [{kind: 'amplifier', tag: 'high_risk_med_new', context_tag_id: 'fixture-tag',
                   label: 'Oxybutynin started 2 days ago'}]}},
    enrolling: {...base,
      features: {speech_rate_wpm: 150.0, pause_ratio: 0.22, mean_pause_s: 0.42, f0_median_hz: 190.0},
      change: {status: 'enrolling', mode: 'enrolled', fused_z: null,
               params: {...params, baseline_checks: 2, min_baseline: 3},
               per_feature: {}},
      assessment: {id: 'fixture-assessment', verdict: 'enrolling', suggested_action: 'none',
                   reasons: []}},
    unusable: {check_id: 'fixture-check', ts: '2026-10-18T14:12:03Z', usable: false,
      quality: {duration_s: 4.2, speech_s: 2.0, snr_db: 8.0, clipped: false,
                reasons: ['too_short', 'too_noisy']},
      features: null, words: [], pauses: [], timings_ms: {normalize: 120, vad: 20}},
  };
})();
