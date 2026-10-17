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
  const mode = CHECK_MODES.includes(q.get('mode')) ? q.get('mode') : 'resident';
  return {mode, patient: q.get('patient'), mock: q.get('mock') === '1',
          fixture: q.get('fixture') || 'change'};
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
      const final = /^4\d\d /.test(error.message) && !error.message.startsWith('401');
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
    if (!error.message.startsWith('401')) throw error;
    await bootstrap();  // the demo token expired mid-session; the retry loop re-sends
    throw error;
  }
}

function mockCheck(fixture) {
  const found = window.CHECK_FIXTURES && window.CHECK_FIXTURES[fixture];
  return sleep(400).then(() => {
    if (!found) throw new Error(`500 unknown fixture "${fixture}"`);
    return JSON.parse(JSON.stringify(found));
  });
}

async function drawWaveform(canvas, blob) {
  const ctx = canvas.getContext('2d');
  const [w, h] = [canvas.width, canvas.height];
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = getComputedStyle(document.body).getPropertyValue('--chart-line') || '#236752';
  ctx.beginPath();
  ctx.moveTo(0, h / 2);
  let peaks = null;
  try {
    const Audio = window.AudioContext || window.webkitAudioContext;
    const audio = new Audio();
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
    ctx.lineTo(w, h / 2);
  }
  ctx.stroke();
}

function timeline(result) {
  const end = Math.max(result.quality.duration_s || 0,
                       ...result.words.map((x) => x.end), ...result.pauses.map((x) => x.end), 1);
  const [w, h] = [640, 96];
  const x = (t) => (t / end) * w;
  const svg = svgEl('svg', {viewBox: `0 0 ${w} ${h}`, class: 'bl-timeline', role: 'img',
    'aria-label': `${result.words.length} words and ${result.pauses.length} pauses over ${end.toFixed(1)} seconds`});
  result.pauses.forEach((p) => svg.append(svgEl('rect', {x: x(p.start), y: 0, width: x(p.end) - x(p.start),
                                                         height: h, class: 'bl-pause'})));
  result.words.forEach((word, i) => {
    const wx = x(word.start);
    svg.append(svgEl('rect', {x: wx, y: 8 + (i % 3) * 26, width: Math.max(2, x(word.end) - wx), height: 20,
                              rx: 4, class: 'bl-word'}));
    const label = svgEl('text', {x: wx, y: 22 + (i % 3) * 26, class: 'bl-word-text'});
    label.textContent = word.w;
    svg.append(label);
  });
  return svg;
}

function featureCell(feature, result) {
  const value = result.features[feature.key];
  const stat = result.change && result.change.per_feature && result.change.per_feature[feature.key];
  const cell = el('div', '', {class: 'bl-feature'});
  const shown = typeof value === 'number' ? `${value.toFixed(feature.digits)} ${feature.unit}`.trim() : '—';
  cell.append(el('div', feature.label, {class: 'bl-muted'}), el('div', shown, {class: 'bl-feature-value'}));
  if (stat && typeof stat.median === 'number' && typeof value === 'number') {
    const delta = value - stat.median;
    const arrow = Math.abs(delta) < 10 ** -feature.digits / 2 ? '→' : delta > 0 ? '↑' : '↓';
    cell.append(el('div', `${arrow} ${delta > 0 ? '+' : ''}${delta.toFixed(feature.digits)} vs baseline ` +
                          `${stat.median.toFixed(feature.digits)}`, {class: 'bl-delta'}));
  } else {
    const status = result.change && result.change.status;
    const n = result.change && result.change.baseline_count;
    cell.append(el('div', status === 'enrolling'
      ? `building baseline${Number.isInteger(n) ? ` ${n} of 3` : ''}` : 'no baseline yet',
      {class: 'bl-delta bl-muted'}));
  }
  return cell;
}

function checkVerdict(result) {
  const verdict = result.assessment ? result.assessment.verdict
    : (result.change && result.change.status === 'enrolling' ? 'enrolling' : 'within_normal');
  const box = el('div', '', {class: 'bl-verdict'});
  box.append(chip(VERDICT_LABELS[verdict] || verdict, verdict));
  (result.assessment ? result.assessment.reasons : []).forEach((r) =>
    box.append(' ', el('span', `${r.kind}: ${r.label}`, {class: 'bl-muted'})));
  return box;
}

function renderResult(host, result, blob) {
  host.replaceChildren();
  if (!result.usable) {
    const reasons = result.quality.reasons.map((r) => REASON_TEXT[r] || r);
    host.append(el('h2', 'That recording could not be used'),
                ...reasons.map((r) => el('p', r)));
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

function isSaturday() { return new Date().getDay() === 6; }

async function renderCheck(main) {
  const params = checkParams();
  const patientId = params.patient || (state.session.patients[0] && state.session.patients[0].id);
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
  baselineLabel.hidden = !(params.mode === 'runner' && isSaturday());
  card.append(el('h1', 'Voice check'), prompt, button, countdown, status, retry, baselineLabel);
  main.append(card, result);

  const setStatus = (text, kind = 'pending') => {
    status.textContent = text;
    status.dataset.state = kind;
    status.hidden = !text;
  };
  if (!patientId) { setStatus('No resident selected.', 'error'); button.disabled = true; return; }
  if (params.mock) setStatus('Mock mode: showing fixture results, nothing is uploaded.', 'pending');

  let recorder = null;
  let stream = null;
  let timer = null;
  let lastBlob = null;

  async function submit(blob) {
    retry.hidden = true;
    button.disabled = true;
    const fields = {patient_id: patientId, mode: params.mode, device_id: 'check-page',
                    device_ts: new Date().toISOString(),
                    is_baseline: baselineBox.checked ? 'true' : 'false'};
    try {
      const data = params.mock
        ? await mockCheck(params.fixture)
        : await uploadCheck(blob, fields, (s) => setStatus(s));
      setStatus(params.mock ? 'Sent (mock)' : 'Sent', 'ok');
      if (params.mode === 'live') renderResult(result, data, blob);
      else result.replaceChildren(el('p', data.usable ? 'Thank you.' : 'Please try again.',
                                     {class: 'bl-thanks'}));
      if (!data.usable) retry.hidden = false;
    } catch (error) {
      setStatus(`Could not send the recording (${error.message}). It is kept here; tap Try again.`, 'error');
      retry.hidden = false;
    } finally {
      button.disabled = false;
    }
  }

  function stop() {
    clearInterval(timer);
    if (recorder && recorder.state !== 'inactive') recorder.stop();
  }

  button.addEventListener('click', async () => {
    if (recorder && recorder.state === 'recording') { stop(); return; }
    const mimeType = pickMimeType();
    if (mimeType === null || !navigator.mediaDevices) {
      setStatus('This browser cannot record audio. Use HTTPS and a current browser.', 'error');
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({audio: true});  // permission on first tap
    } catch (error) {
      setStatus('Microphone access was not allowed.', 'error');
      return;
    }
    const chunks = [];
    recorder = new MediaRecorder(stream, mimeType ? {mimeType} : undefined);
    recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    recorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      button.textContent = 'Record';
      countdown.textContent = '';
      lastBlob = new Blob(chunks, {type: recorder.mimeType || mimeType || 'audio/webm'});
      submit(lastBlob);
    };
    result.replaceChildren();
    setStatus('');
    recorder.start();
    button.textContent = 'Stop';
    let left = CHECK_MAX_S;
    countdown.textContent = `Listening… ${left} s`;
    timer = setInterval(() => {
      left -= 1;
      countdown.textContent = `Listening… ${left} s`;
      if (left <= 0) stop();  // auto-stop at 15 s
    }, 1000);
  });
  retry.addEventListener('click', () => {
    result.replaceChildren();
    if (lastBlob && status.dataset.state === 'error') submit(lastBlob);  // resend the kept clip
    else { setStatus(''); retry.hidden = true; }
  });
}
