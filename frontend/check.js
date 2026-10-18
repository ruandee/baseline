// /check (BL-17): record the fixed prompt, upload with retries, show the speech decomposition.
// Built against the POST /v1/patients/{id}/checks shape in docs/06-baseline.md; ?mock=1 serves
// fixtures from check-fixtures.js instead of calling the API.
const CHECK_PROMPT = 'Count from one to twenty, then say the days of the week, starting with Monday.';
const CHECK_MAX_S = 15;
const CHECK_RETRY_MS = [1000, 3000, 9000];
const CHECK_MODES = ['resident', 'runner', 'live'];
const FEATURES = [
  {key: 'speech_rate_wpm', label: 'Speech rate', unit: 'wpm', digits: 0},
  {key: 'pause_ratio', label: 'Pause ratio', unit: '', digits: 2},
  {key: 'mean_pause_s', label: 'Mean pause', unit: 's', digits: 2},
  {key: 'f0_median_hz', label: 'Pitch (F0)', unit: 'Hz', digits: 0}];
const REASON_TEXT = {
  too_short: 'The recording was too short.',
  too_little_speech: 'There was not enough speech in the recording.',
  too_few_words: 'Too few words were picked up.',
  too_noisy: 'The room was too noisy.',
  clipped: 'The sound was too loud and distorted.',
  off_script: 'The words did not match the prompt.'};

function pickMimeType() {
  const options = ['audio/webm', 'audio/mp4'];  // webm where supported, mp4 on iOS Safari
  if (typeof MediaRecorder === 'undefined') return null;
  return options.find((t) => MediaRecorder.isTypeSupported(t)) || '';
}

function checkParams() {
  const q = new URLSearchParams(location.search);
  const mode = CHECK_MODES.includes(q.get('mode')) ? q.get('mode')
    : q.get('type') === 'motion' ? 'live' : 'resident';
  return {mode, patient: q.get('patient'), mock: q.get('mock') === '1',
          fixture: q.get('fixture') || 'change', lang: q.get('lang'),
          device: q.get('device')};
}

function checkPatientId(params, people) {
  const capture = people.find((person) => person.capture_mode === params.mode);
  // Hosted scripted residents never become an implicit live/runner recording target.
  const legacy = !people.some((person) => 'scripted_cohort' in person);
  return params.patient || (capture && capture.id) || (legacy && people[0] && people[0].id) || null;
}

// The engine prefers same-device history when picking a baseline, so device_id must be stable:
// ?device= wins, runner mode defaults to 'runner-phone' (docs/06-baseline.md), otherwise a
// random id remembered by this browser. Storage can be blocked; fall back to 'check-page'.
const DEVICE_KEY = 'bl-device-id';
function checkDeviceId(params, storage = () => window.localStorage) {
  const clean = (v) => (typeof v === 'string' ? v.replace(/[^\w.-]/g, '').slice(0, 64) : '');
  if (clean(params.device)) return clean(params.device);
  if (params.mode === 'runner') return 'runner-phone';
  try {
    const store = storage();
    const key = `${DEVICE_KEY}-${params.mode}`;
    let id = clean(store.getItem(key));
    if (!id) {
      id = `${params.mode}-device-${Math.random().toString(36).slice(2, 12)}`;
      store.setItem(key, id);
    }
    return id;
  } catch (error) {
    return 'check-page';
  }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Resolves with the 200 body, or throws. Client errors (4xx) are final; network and 5xx retry.
async function uploadCheck(blob, fields, onStatus, {delays = CHECK_RETRY_MS, send = postCheck} = {}) {
  for (let attempt = 0; ; attempt += 1) {
    onStatus(attempt === 0 ? 'Sending' : 'Retrying');
    try {
      const result = await send(blob, fields);
      onStatus('Sent');
      return result;
    } catch (error) {
      const status = error.status || 0;
      const final = status >= 400 && status < 500 && ![401, 408, 429].includes(status);
      if (final || attempt >= delays.length) throw error;
      await sleep(delays[attempt]);
    }
  }
}

async function postCheck(blob, fields) {
  const form = new FormData();
  form.append('audio', blob, blob.type.includes('mp4') ? 'check.m4a' : 'check.webm');
  Object.entries(fields).forEach(([k, v]) => { if (v !== undefined && v !== null) form.append(k, v); });
  try {
    return await api(`/v1/patients/${fields.patient_id}/checks`, {method: 'POST', body: form});
  } catch (error) {
    if (error.status !== 401) throw error;
    await bootstrap();  // the demo token expired mid-session; the retry loop re-sends
    throw error;
  }
}

function loadFixtures() {
  if (window.CHECK_FIXTURES) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = '/assets/check-fixtures.js';
    script.onload = resolve;
    script.onerror = () => reject(new Error('could not load check fixtures'));
    document.head.append(script);
  });
}

async function mockCheck(fixture) {
  await loadFixtures();
  await sleep(400);
  const found = window.CHECK_FIXTURES[fixture];
  if (!found) throw new Error(`unknown fixture "${fixture}"`);
  return JSON.parse(JSON.stringify(found));
}

async function drawWaveform(canvas, blob) {
  const ctx = canvas.getContext('2d');
  const [w, h] = [canvas.width, canvas.height];
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = getComputedStyle(document.body).getPropertyValue('--chart-line') || '#236752';
  ctx.beginPath();
  let peaks = null;
  try {
    const Context = window.AudioContext || window.webkitAudioContext;
    const audio = new Context();
    const decoded = await audio.decodeAudioData(await blob.arrayBuffer());
    audio.close();
    const data = decoded.getChannelData(0);
    const step = Math.max(1, Math.floor(data.length / w));
    peaks = Array.from({length: w}, (_, x) => {
      let max = 0;
      for (let i = x * step; i < Math.min(data.length, (x + 1) * step); i += 1) {
        max = Math.max(max, Math.abs(data[i]));
      }
      return max;
    });
  } catch (error) {
    peaks = null;  // undecodable clip: leave a flat line rather than fail the result view
  }
  if (peaks) {
    const top = Math.max(...peaks, 0.01);
    peaks.forEach((p, x) => {
      const half = (p / top) * (h / 2 - 2);
      ctx.moveTo(x + 0.5, h / 2 - half);
      ctx.lineTo(x + 0.5, h / 2 + half);
    });
  } else {
    ctx.moveTo(0, h / 2);
    ctx.lineTo(w, h / 2);
  }
  ctx.stroke();
}

function timeline(result) {
  const end = Math.max(result.quality.duration_s || 0,
                       ...result.words.map((x) => x.end), ...result.pauses.map((x) => x.end), 1);
  const [w, h] = [640, 150];
  const x = (t) => (t / end) * w;
  const svg = svgEl('svg', {viewBox: `0 0 ${w} ${h}`, class: 'bl-timeline', role: 'img',
    'aria-label': `${result.words.length} words and ${result.pauses.length} pauses over ${end.toFixed(1)} seconds`});
  result.pauses.forEach((p) => svg.append(svgEl('rect', {x: x(p.start), y: 0, width: x(p.end) - x(p.start),
                                                         height: h, class: 'bl-pause'})));
  result.words.forEach((word, i) => {
    const wx = x(word.start);
    const row = i % 5;  // five staggered rows keep neighbouring labels from overlapping
    svg.append(svgEl('rect', {x: wx, y: 6 + row * 22, width: Math.max(2, x(word.end) - wx), height: 18,
                              rx: 4, class: 'bl-word'}));
    const label = svgEl('text', {x: wx + 2, y: 19 + row * 22, class: 'bl-word-text'});
    label.textContent = word.w;
    svg.append(label);
  });
  for (let t = 0; t <= Math.floor(end); t += 2) {
    const tick = svgEl('text', {x: x(t), y: h - 4, class: 'bl-tick'});
    tick.textContent = `${t}s`;
    svg.append(tick);
  }
  return svg;
}

function changeOf(result) {
  const change = result.change || {};
  const params = change.params || {};  // engine contract: params.baseline_checks / min_baseline
  return {status: change.status, count: params.baseline_checks, of: params.min_baseline,
          perFeature: change.per_feature || {}};
}

function featureCell(feature, result) {
  const value = result.features[feature.key];
  const change = changeOf(result);
  const stat = change.perFeature[feature.key];
  const cell = el('div', '', {class: 'bl-feature'});
  const shown = typeof value === 'number' ? `${value.toFixed(feature.digits)} ${feature.unit}`.trim() : '—';
  cell.append(el('div', feature.label, {class: 'bl-muted'}), el('div', shown, {class: 'bl-feature-value'}));
  if (stat && typeof stat.median === 'number' && typeof value === 'number') {
    const delta = value - stat.median;
    const arrow = Math.abs(delta) < 10 ** -feature.digits / 2 ? '→' : delta > 0 ? '↑' : '↓';
    cell.append(el('div', `${arrow} ${delta > 0 ? '+' : ''}${delta.toFixed(feature.digits)} vs baseline ` +
                          `${stat.median.toFixed(feature.digits)}`, {class: 'bl-delta'}));
  } else {
    const n = change.count;
    cell.append(el('div', change.status === 'enrolling'
      ? `building baseline${Number.isInteger(n) && Number.isInteger(change.of)
        ? ` ${n} of ${change.of} eligible prior checks` : ''}`
      : 'no baseline yet',
      {class: 'bl-delta bl-muted'}));
  }
  return cell;
}

function checkVerdict(result) {
  const box = el('div', '', {class: 'bl-verdict'});
  const assessment = result.assessment;
  if (!assessment || !assessment.verdict) {  // missing is unknown, never "within normal"
    box.append(chip('Verdict unavailable', 'unknown'));
    return box;
  }
  // Same rule as the unit page: an over-budget escalation is a watch-list item, not interruptive.
  box.append(assessment.verdict === 'escalate' && assessment.over_budget
    ? chip('Escalate (over budget)', 'watch')
    : chip(VERDICT_LABELS[assessment.verdict] || assessment.verdict, assessment.verdict));
  if (assessment.suggested_action && assessment.suggested_action !== 'none'
      && assessment.suggested_action_label) {
    box.append(' ', el('span', `Suggested: ${assessment.suggested_action_label}`,
                       {class: 'bl-action'}));
  }
  (assessment.reasons || []).forEach((r) =>
    box.append(' ', el('span', `${r.kind}: ${r.label}`, {class: 'bl-muted'})));
  return box;
}

function renderResult(host, result, blob) {
  host.replaceChildren();
  if (!result.usable) {
    const reasons = result.quality.reasons.map((r) => REASON_TEXT[r] || r);
    host.append(el('h2', 'That recording could not be used'),
                ...reasons.map((r) => el('p', r)));
    const again = el('button', 'Try again', {type: 'button', class: 'bl-retry'});
    again.addEventListener('click', () => {  // back to a fresh prompt; the next Record is a new clip
      host.replaceChildren();
      document.querySelector('.bl-record').focus();
    });
    host.append(again);
    return;
  }
  const canvas = el('canvas', '', {width: 640, height: 80, class: 'bl-wave', role: 'img',
                                   'aria-label': 'Waveform of the recording'});
  const grid = el('div', '', {class: 'bl-features'});
  grid.append(...FEATURES.map((f) => featureCell(f, result)));
  const timings = Object.entries(result.timings_ms || {}).map(([k, v]) => `${k} ${v} ms`).join(' · ');
  host.append(checkVerdict(result), canvas, timeline(result), grid,
              el('p', timings, {class: 'bl-muted bl-timings'}));
  if (blob) drawWaveform(canvas, blob);
}

async function renderCheck(main) {
  const params = checkParams();
  if (params.mode === 'resident') {  // BL-31 resident and PSW experience, check-resident.js
    if (params.patient) return renderResidentCheck(main, params, params.patient);
    return renderResidentLanding(main, params);
  }
  const patientId = checkPatientId(params, state.session.patients || []);
  main.replaceChildren();
  const card = el('section', '', {class: 'bl-check-card'});
  const prompt = el('p', CHECK_PROMPT, {class: 'bl-prompt'});
  const button = el('button', 'Record', {class: 'bl-record', type: 'button'});
  const countdown = el('div', '', {class: 'bl-countdown', 'aria-live': 'off'});
  const status = el('div', '', {class: 'bl-status', 'data-state': 'pending', hidden: '', role: 'status'});
  const retry = el('button', 'Try again', {class: 'bl-retry', type: 'button', hidden: ''});
  const result = el('section', '', {class: 'bl-result'});
  const baselineBox = el('input', '', {type: 'checkbox', id: 'is-baseline'});
  const baselineLabel = el('label', ' Mark as baseline', {for: 'is-baseline', class: 'bl-baseline'});
  baselineLabel.prepend(baselineBox);
  baselineLabel.hidden = !(params.mode === 'runner' && new Date().getDay() === 6);
  card.append(el('h1', 'Voice check'), prompt, button, countdown, status, retry, baselineLabel);
  main.append(card, result);

  const resident = params.mode === 'resident';
  // Residents never see technical errors (docs/06-baseline.md, BL-31); the detail goes to the console.
  const failure = (text, error) => {
    if (error) console.error(error);
    setStatus(resident ? 'Something went wrong. Please ask a staff member.' : text, 'error');
  };
  const setStatus = (text, kind = 'pending') => {
    status.textContent = text;
    status.dataset.state = kind;
    status.hidden = !text;
  };
  if (!patientId) { failure('No resident selected.'); button.disabled = true; return; }
  if (params.mock && !resident) setStatus('Mock mode: showing fixture results, nothing is uploaded.', 'pending');

  let recorder = null;
  let stream = null;
  let timer = null;
  let limit = null;
  let lastBlob = null;
  let setup = null, captureProfile = null, capturePending = false, discard = false, disposed = false;
  window.addEventListener('pagehide', () => {
    disposed = true; discard = true;
    if (stream) stream.getTracks().forEach((track) => track.stop());
    stop();
  }, {once: true});
  if (!params.mock) {
    button.disabled = true;
    prompt.hidden = true;
    const setupHost = el('div', '');
    main.prepend(setupHost);
    setup = await window.checkSetup(setupHost, patientId, (ready) => {
      if (!ready && recorder && recorder.state === 'recording') { discard = true; stop(); }
      button.disabled = !ready;
      prompt.hidden = !ready;
    });
  }

  async function submit(blob) {
    retry.hidden = true;
    button.disabled = true;
    const fields = {patient_id: patientId, mode: params.mode, device_id: checkDeviceId(params),
                    device_ts: new Date().toISOString(),
                    is_baseline: baselineBox.checked ? 'true' : 'false',
                    ...(captureProfile ? {profile_version: captureProfile.version,
                                          protocol_locale: captureProfile.protocol_locale} : {})};
    try {
      const data = params.mock
        ? await mockCheck(params.fixture)
        : await uploadCheck(blob, fields, (s) => setStatus(s));
      setStatus(resident ? '' : params.mock ? 'Sent (mock)' : 'Sent', 'ok');
      if (params.mode === 'live') renderResult(result, data, blob);
      else result.replaceChildren(el('p', data.usable ? 'Thank you.' : 'Please tap Record to try again.',
                                     {class: 'bl-thanks'}));
    } catch (error) {
      failure(`Could not send the recording (${error.message}). It is kept here; tap Try again.`, error);
      retry.hidden = false;
    } finally {
      button.disabled = setup ? !setup.ready : false;
    }
  }

  function stop() {
    clearInterval(timer);
    clearTimeout(limit);
    if (recorder && recorder.state !== 'inactive') recorder.stop();
  }

  button.addEventListener('click', async () => {
    if (recorder && recorder.state === 'recording') { stop(); return; }
    if (capturePending) return;
    const mimeType = pickMimeType();
    if (mimeType === null || !navigator.mediaDevices) {
      failure('This browser cannot record audio. Use HTTPS and a current browser.');
      return;
    }
    try {
      capturePending = true;
      button.disabled = true;
      if (setup) {
        await setup.refresh();
        if (!setup.ready) { failure('Recording blocked. Check the current profile and voice permission.'); return; }
        captureProfile = {...setup.profile};
      }
      stream = await navigator.mediaDevices.getUserMedia({audio: true});  // permission on first tap
    } catch (error) {
      failure('Microphone access was not allowed.', error);
      return;
    } finally { capturePending = false; button.disabled = disposed || (setup ? !setup.ready : false); }
    if (disposed || (setup && (!setup.ready || setup.profile.version !== captureProfile.version))) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    discard = false;
    const chunks = [];
    recorder = new MediaRecorder(stream, mimeType ? {mimeType} : undefined);
    recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    recorder.onerror = () => { stop(); failure('Recording failed.'); };
    recorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      button.textContent = 'Record';
      countdown.textContent = '';
      if (discard) return;
      lastBlob = new Blob(chunks, {type: recorder.mimeType || mimeType || 'audio/webm'});
      submit(lastBlob);
    };
    result.replaceChildren();
    setStatus('');
    recorder.start();
    button.textContent = 'Stop';
    const startedAt = Date.now();
    const tick = () => {
      const left = Math.max(0, Math.ceil(CHECK_MAX_S - (Date.now() - startedAt) / 1000));
      countdown.textContent = `Listening… ${left} s`;
    };
    tick();
    timer = setInterval(tick, 250);
    limit = setTimeout(stop, CHECK_MAX_S * 1000);  // auto-stop at 15 s
  });
  retry.addEventListener('click', () => {
    result.replaceChildren();
    if (lastBlob) submit(lastBlob);  // resend the kept clip; shown only after a failed send
  });
}
