// Synthetic KAZE pages. The server supplies a separate self-custody session token in memory.
async function renderKaze(main, requestedId) {
  const person = state.session.patients[0];
  if (!person) throw new Error('KAZE person unavailable');
  const base = `/v1/patients/${person.id}/sessions`;
  main.replaceChildren(el('h1', 'Baseline Out'),
    el('p', 'Synthetic safety-session prototype. Keep this page open for reminders. No automatic calls.'));
  const content = el('section', '', {class: 'kaze-panel'});
  main.append(content);
  const list = await api(base);
  const selected = requestedId || ((KazeCore.openSession(list.sessions) || {}).id);
  if (!selected) { renderKazeArm(content, base); return; }
  await renderKazeSession(content, base, selected, Boolean(requestedId));
}

function renderKazeArm(host, base) {
  const form = el('form', '', {class: 'kaze-form'});
  const fields = {};
  const input = (key, label, type, value = '') => {
    const node = el('input', '', {type, value, id: `kaze-${key}`, name: key});
    fields[key] = node;
    const wrap = el('label', label, {for: `kaze-${key}`});
    wrap.append(node); form.append(wrap); return node;
  };
  input('name', 'Your first name', 'text');
  const end = new Date(Date.now() + 3 * 3600000);
  input('end', 'Expected end time (your local clock)', 'time',
    `${String(end.getHours()).padStart(2, '0')}:${String(end.getMinutes()).padStart(2, '0')}`);
  const interval = input('interval', 'Check-in interval in minutes', 'number', '45');
  interval.setAttribute('min', '1'); interval.setAttribute('max', '180');
  for (const n of [1, 2]) {
    input(`name${n}`, `Contact ${n} name${n === 2 ? ' (optional)' : ''}`, 'text');
    input(`phone${n}`, `Contact ${n} phone with country code`, 'tel');
  }
  const exertion = input('exertion', 'I expect physical exertion', 'checkbox');
  const loud = input('loud', 'I expect a loud venue', 'checkbox');
  form.append(el('p', 'A loud venue can make recording unusable. Step somewhere quiet before speaking.'));
  const enabled = input('enabled', 'Allow contact texts for this session', 'checkbox');
  enabled.checked = true;
  const permission = input('permission', 'I agree to voice checks for this session', 'checkbox');
  const status = el('p', '', {role: 'status'});
  const button = el('button', 'Arm session', {type: 'submit'});
  form.append(button, status,
    el('p', 'Reminders: due now, then 2.5 minutes overdue. Contact escalation starts at 5 minutes overdue, then 10 minutes per further level. A one-minute check interval does not shorten those delays.'));
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!permission.checked) { status.textContent = 'Please confirm permission for voice checks.'; return; }
    const parsed = KazeCore.validateArm({displayName: fields.name.value,
      endClock: fields.end.value, intervalMin: fields.interval.value,
      contacts: [1, 2].map((n) => ({name: fields[`name${n}`].value, phone: fields[`phone${n}`].value})),
      contextTags: [exertion.checked && 'exertion', loud.checked && 'loud_venue'].filter(Boolean),
      escalationEnabled: enabled.checked}, new Date());
    if (parsed.errors) { status.textContent = parsed.errors.join(' '); return; }
    button.disabled = true;
    try {
      const session = await api(base, {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(parsed.body)});
      // Phone values are no longer needed after submission; never retain them in browser storage.
      for (const n of [1, 2]) fields[`phone${n}`].value = '';
      await renderKazeSession(host, base, session.id, false);
    } catch (error) { status.textContent = 'Could not arm. Check consent with the operator and try again.'; }
    finally { button.disabled = false; }
  });
  host.replaceChildren(form);
}

async function renderKazeSession(host, base, sid, judge) {
  let session, stopped = false, busyRefresh = false;
  const heading = el('h2', 'Loading session');
  const detail = el('p', '');
  const countdown = el('p', '', {role: 'status', class: 'kaze-countdown'});
  const status = el('p', '', {role: 'status'});
  const record = el('button', 'Record', {type: 'button', class: 'kaze-record'});
  const location = el('input', '', {type: 'checkbox', id: 'kaze-location'});
  const locationLabel = el('label', 'Include my location with this session check-in', {for: 'kaze-location'});
  locationLabel.prepend(location);
  const ending = el('button', 'End session', {type: 'button'});
  const result = el('section', '');
  const events = el('section', '', {class: 'kaze-timeline'});
  const link = el('a', judge ? 'Back to check-in' : 'View session timeline',
    {href: judge ? '/out' : `/out/session/${encodeURIComponent(sid)}`});
  host.replaceChildren(heading, detail, countdown, status, el('p', CHECK_PROMPT, {class: 'bl-prompt'}),
    record, locationLabel, ending, link, result, events);
  const endpoint = `${base}/${encodeURIComponent(sid)}`;
  const fresh = async () => { session = await api(endpoint); return session; };
  const capture = kazeCapture({getSession: fresh,
    getMedia: () => navigator.mediaDevices.getUserMedia({audio: true}),
    Recorder: function(stream) {
      const mime = pickMimeType();
      if (mime === null) throw new Error('Recording unavailable');
      return new MediaRecorder(stream, mime ? {mimeType: mime} : undefined);
    },
    // No detached automatic retries: a cancelled/expired session must not resend a kept clip.
    upload: (blob, fields) => postCheck(blob,
      {patient_id: state.session.patients[0].id, ...fields}),
    locate: () => new Promise((resolve) => {
      if (!navigator.geolocation) { resolve(null); return; }
      navigator.geolocation.getCurrentPosition(resolve, () => resolve(null),
        {enableHighAccuracy: false, timeout: 8000, maximumAge: 0});
    }),
    onState: (text, data) => {
      status.textContent = text;
      record.textContent = capture.isRecording() ? 'Stop' : 'Record';
      if (data) { renderResult(result, data, null); refresh(); }
    }});
  let poll, clock, lastSignal = null;
  const ended = () => !session || session.status === 'ended' || Date.parse(session.ends_at) <= Date.now();
  function tick() {
    if (!session || stopped) return;
    if (ended()) {
      capture.cancel(); record.disabled = true; ending.disabled = true;
      location.disabled = true; countdown.textContent = 'Session ended';
      clearInterval(clock); clearInterval(poll); return;
    }
    const due = KazeCore.countdown(session.next_due_at, new Date());
    countdown.textContent = session.status === 'arming' ? 'Record three usable baseline clips to start.' : due ? due.label : '';
    const signal = `${session.episode}/${session.ladder_level}/${session.next_due_at}`;
    if (document.visibilityState !== 'hidden' && due && due.overdue && signal !== lastSignal) {
      lastSignal = signal;
      if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
      try {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        if (Ctx) {
          const ctx = new Ctx(), tone = ctx.createOscillator(), gain = ctx.createGain();
          gain.gain.value = .05; tone.connect(gain); gain.connect(ctx.destination);
          tone.start(); tone.stop(ctx.currentTime + .2); tone.onended = () => ctx.close();
        }
      } catch (_) { /* Visible reminder remains; browser may require a prior user gesture. */ }
    }
  }
  async function refresh() {
    if (busyRefresh || stopped) return;
    busyRefresh = true;
    try {
      await fresh();
      const view = KazeCore.personView(session);
      heading.textContent = view.headline; detail.textContent = view.detail;
      record.textContent = capture.isRecording() ? 'Stop' : session.status === 'arming'
        ? `Record baseline (${session.baseline.usable}/${session.baseline.required})` : 'Record check-in';
      events.replaceChildren(el('h2', 'Session timeline'));
      for (const event of KazeCore.timeline(session)) {
        const row = el('article', '', {class: 'kaze-event'});
        row.append(el('time', new Date(event.ts).toLocaleString()), el('h3', event.label),
          el('p', event.detail));
        if (event.message) row.append(el('p', event.message));
        events.append(row);
      }
      for (const ack of KazeCore.timeToAck(session)) {
        events.append(el('p', `Episode ${ack.episode}: ${ack.seconds === null ? 'not acknowledged' :
          `acknowledged after ${KazeCore.duration(ack.seconds)}`}`));
      }
      record.disabled = ended();
      tick();
    } catch (error) {
      // Fail closed: a failed refresh cannot leave an apparently valid recording session.
      status.textContent = 'Could not refresh this session. Reload before recording.';
      capture.cancel(); record.disabled = true;
    } finally { busyRefresh = false; }
  }
  record.addEventListener('click', () => {
    if (ended()) { tick(); return; }
    if (capture.isRecording()) capture.stop(); else capture.start(location.checked);
  });
  ending.addEventListener('click', async () => {
    capture.cancel(); record.disabled = true;
    try { session = await api(`${endpoint}/end`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'}); await refresh(); }
    catch (error) { status.textContent = 'Could not confirm the end. Reload to check.'; }
  });
  const cleanup = () => { stopped = true; capture.cancel(); clearInterval(poll); clearInterval(clock); };
  window.addEventListener('pagehide', cleanup, {once: true});
  await refresh();
  if (!ended()) {
    poll = setInterval(() => { if (document.visibilityState !== 'hidden') refresh(); }, 5000);
    clock = setInterval(tick, 1000);
  }
}
