// Fixture for GET /v1/patients/{id}/overview?days=30, shaped from docs/06-baseline.md.
// BL-13 has not landed, so the field names below are this page's assumed contract.
// Used only when /resident/<id> is opened with ?mock=1; never contacts the API.
(function () {
  const DAY = 86400000;  // ms
  const start = Date.UTC(2026, 8, 18);
  const FEATURES = {
    speech_rate_wpm: {label: 'Speech rate', unit: 'words/min', base: 158, mad: 6, floor: 5, drift: -34, digits: 0},
    pause_ratio: {label: 'Pause ratio', unit: '%', base: 0.21, mad: 0.02, floor: 0.02, drift: 0.11, digits: 2},
    mean_pause_s: {label: 'Mean pause', unit: 's', base: 0.4, mad: 0.04, floor: 0.05, drift: 0.18, digits: 2},
    f0_median_hz: {label: 'Pitch (F0)', unit: 'Hz', base: 212, mad: 4, floor: 5, drift: 0, digits: 0},
  };
  const noise = (i, k) => Math.sin(i * 12.9898 + k * 78.233) * 0.5;
  const series = {};
  const baseline = {};
  Object.entries(FEATURES).forEach(([name, f], k) => {
    // scale = max(1.4826 × MAD, 5% of median, abs_floor), as the engine computes it (docs/06-baseline.md)
    baseline[name] = {median: f.base, mad: f.mad, scale: +Math.max(1.4826 * f.mad, 0.05 * f.base, f.floor).toFixed(4)};
    series[name] = {daily: [], checks: []};
    for (let d = 0; d < 30; d++) {
      const ramp = d >= 25 ? (d - 24) / 5 : 0;  // drift starts on day 25
      const day = new Date(start + d * DAY).toISOString().slice(0, 10);
      const value = f.base + noise(d, k) * f.mad + ramp * f.drift;
      series[name].daily.push({day, median: +value.toFixed(3)});
      [0, 1].forEach((n) => series[name].checks.push({
        ts: new Date(start + d * DAY + (8 + n * 6) * 3600000).toISOString(),
        value: +(value + noise(d + n * 7, k + 3) * f.mad * 1.2).toFixed(3)}));
    }
  });
  const firstChange = new Date(start + 27 * DAY + 8 * 3600000).toISOString();
  window.RESIDENT_FIXTURES = {
    'mrs-k': {
      patient_id: 'mrs-k', display_name: 'Mrs. K', synthetic: true,
      watch_window: {open: true, day: 3, of: 7, reason: 'high_risk_med_new'},
      series, baseline: {mode: 'enrolled', n_checks: 5, features: baseline},
      first_change_ts: firstChange,
      features: FEATURES,
      latest_assessment: {
        id: 'asm-1', ts: new Date(start + 29 * DAY + 8 * 3600000).toISOString(),
        verdict: 'escalate', over_budget: false, suggested_action: {id: '4at', label: 'Run 4AT now'},
        no_escalate_profile: false,
        reasons: [
          {kind: 'amplifier', tag: 'new_anticholinergic', label: 'New anticholinergic started Tuesday',
           evidence_id: '00000000-0000-4000-8000-000000000001',
           quote: 'Started oxybutynin 5 mg nightly for urgency.', match: [8, 18],
           source_kind: 'medication_order', recorded_at: new Date(start + 26 * DAY).toISOString()},
          {kind: 'amplifier', tag: 'confusion_note', label: 'PSW note: not her usual chatty self',
           evidence_id: '00000000-0000-4000-8000-000000000002',
           quote: 'Quieter than usual at lunch, not her usual chatty self.', match: [29, 55],
           source_kind: 'progress_note', recorded_at: new Date(start + 28 * DAY).toISOString()}],
        change: {status: 'change', mode: 'enrolled', fused_z: 3.1,
          params: {z_threshold: 2.0, provisional_z: 3.0, min_features: 2, consecutive: 2, mad_floor_pct: 0.05},
          per_feature: {
            speech_rate_wpm: {value: 124, median: 158, mad: 6.1, z: -3.7, ewma: -2.9, cusum: 5.1},
            pause_ratio: {value: 0.31, median: 0.21, mad: 0.02, z: 3.3, ewma: 2.4, cusum: 4.2},
            mean_pause_s: {value: 0.57, median: 0.4, mad: 0.04, z: 2.9, ewma: 2.0, cusum: 3.5},
            f0_median_hz: {value: 213, median: 212, mad: 4, z: 0.2, ewma: 0.1, cusum: 0.0}}},
        sbar: {source: 'template', sentences: [
          {section: 'S', text: "Mrs. K's speech differs from her usual: speech rate 124 vs 158 words per minute, pauses 31% vs 21%.", evidence_ids: ['asm-1']},
          {section: 'B', text: 'New anticholinergic started Tuesday; PSW note: not her usual chatty self.', evidence_ids: ['00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000002']},
          {section: 'A', text: 'Meets the change threshold; new anticholinergic present.', evidence_ids: ['asm-1']},
          {section: 'R', text: 'Suggest Run 4AT now.', evidence_ids: ['asm-1']}]}},
    },
  };
  // An enrolling resident: no series, no baseline, no assessment. Exercises every empty state.
  window.RESIDENT_FIXTURES['new-resident'] = {
    patient_id: 'new-resident', display_name: 'Mr. N', synthetic: true, watch_window: {open: false},
    series: {}, baseline: {mode: 'enrolling', n_checks: 0, features: {}}, features: FEATURES,
    latest_assessment: null};
  window.RESIDENT_FIXTURE_EVIDENCE = {
    '00000000-0000-4000-8000-000000000001': {evidence_id: '00000000-0000-4000-8000-000000000001',
      source_kind: 'medication_order', author_role: 'physician', recorded_at: '2026-10-14T15:00:00Z',
      ingested_at: '2026-10-14T15:01:00Z', quote: 'Started oxybutynin 5 mg nightly for urgency.', start: 0, end: 44},
    '00000000-0000-4000-8000-000000000002': {evidence_id: '00000000-0000-4000-8000-000000000002',
      source_kind: 'progress_note', author_role: 'psw', recorded_at: '2026-10-16T17:30:00Z',
      ingested_at: '2026-10-16T17:31:00Z', quote: 'Quieter than usual at lunch, not her usual chatty self.', start: 0, end: 56},
  };
})();
