// /check resident and PSW experience (BL-31). Loaded before check.js; check.js hands resident
// mode to renderResidentLanding (no patient: the PSW "due now" list) or renderResidentCheck.
// Residents and PSWs never see scores, verdicts, features or technical errors: the resident view
// reads only `usable` from a check result. Consent is NOT enforced here; the server-side contract
// is proposed in docs/decisions/017-resident-experience-consent-language.md and still pending.

// Only languages with a registered prompt_version are offered. count20-days-v1 is the English
// protocol (English ASR and on-script check), so other languages wait for their own prompt.
const RESIDENT_PROMPTS = {
  en: {label: 'English', promptVersion: 'count20-days-v1', title: "Let's count together",
       spoken: "Let's count together. Count from one to twenty, then say the days of the week, " +
               'starting with Monday. Tap the big button when you are ready.'},
};

const RESIDENT_TEXT = {
  thanks: (name) => (name ? `Thank you, ${name}.` : 'Thank you.'),
  done: "That's all for today.",
  again: "Thank you. Let's try once more.",
  skipped: "That's okay, we'll skip today.",
  help: "Let's stop here for now. Please ask a staff member to help.",
  listening: "I'm listening…",
  sending: 'Saving…',
};

function residentLanguage(code) {
  return Object.prototype.hasOwnProperty.call(RESIDENT_PROMPTS, code) ? code : 'en';
}

function firstNameOf(patientId) {
  const patients = (state.session && state.session.patients) || [];
  const found = patients.find((p) => p.id === patientId);
  return found && found.name ? found.name.trim().split(/\s+/)[0] : null;
}

// One-retry rule (docs/06-baseline.md): first unusable clip earns one more try, a second
// unusable clip is accepted (the server already stored both for audit) and the flow ends.
function residentStep(flow, usable) {
  if (flow.done) return {flow, view: 'done'};
  if (usable) return {flow: {...flow, done: true}, view: 'thanks'};
  const unusable = flow.unusable + 1;
  return unusable >= 2 ? {flow: {...flow, unusable, done: true}, view: 'accepted'}
    : {flow: {...flow, unusable}, view: 'retry'};
}

// A check is due when the resident has no check since local midnight. Projects the watch list
// down to name and last-check time so no verdict, z or feature value reaches the page.
function dueNowItems(residents, sessionPatients, now = new Date()) {
  const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const names = new Map((sessionPatients || []).map((p) => [p.id, p.name]));
  return (residents || []).map((r) => {
    const last = r.last_check_ts ? new Date(r.last_check_ts).getTime() : null;
    return {patient_id: r.patient_id, name: names.get(r.patient_id) || r.display_name || 'Resident',
            last_check_ts: Number.isFinite(last) ? r.last_check_ts : null,
            due: !Number.isFinite(last) || last < midnight,
            // Proposed server-computed field (ADR 017); absent today, so never shown.
            observation_helped: r.observation_helped === true};
  }).sort((a, b) => (a.due === b.due ? (a.last_check_ts || '').localeCompare(b.last_check_ts || '')
    : a.due ? -1 : 1));
}

function residentLink(params, patientId) {
  const q = new URLSearchParams({mode: 'resident'});
  if (patientId) q.set('patient', patientId);
  if (params.lang && params.lang !== 'en') q.set('lang', params.lang);
  if (params.mock) { q.set('mock', '1'); q.set('fixture', params.fixture); }
  return `/check?${q}`;
}

async function renderResidentLanding(main, params) {
  main.replaceChildren();
  const section = el('section', '', {class: 'bl-due', 'data-mode': 'resident'});
  const status = el('p', 'Loading…', {class: 'bl-due-status', role: 'status'});
  section.append(el('h1', 'Due now'),
    el('p', 'Consent is not yet tracked by this system. Follow your facility\'s consent ' +
            'process before each check.', {class: 'bl-muted bl-consent-note'}),
    status);
  main.append(section);
  let residents;
  try {
    // Mock mode lists the session's synthetic residents as due and calls no patient API.
    residents = params.mock
      ? (state.session.patients || []).map((p) => ({patient_id: p.id, display_name: p.name}))
      : (await api('/v1/watchlist')).residents;
  } catch (error) {
    console.error(error);
    status.textContent = 'The list could not be loaded. Please try again or ask the nurse.';
    return;
  }
  const items = dueNowItems(residents, state.session.patients);
  const list = (rows) => {
    const ul = el('ul', '', {class: 'bl-due-list'});
    rows.forEach((item) => {
      const li = el('li', '');
      const link = el('a', item.name, {href: residentLink(params, item.patient_id),
                                       class: 'bl-due-item'});
      if (item.observation_helped) link.append(el('span', 'Your observation helped', {class: 'bl-helped'}));
      li.append(link);
      ul.append(li);
    });
    return ul;
  };
  const due = items.filter((i) => i.due);
  const done = items.filter((i) => !i.due);
  status.textContent = due.length ? `${due.length === 1 ? 'One resident' : `${due.length} residents`} ` +
    'still to check today.' : 'Everyone has been checked today.';
  if (due.length) section.append(list(due));
  if (done.length) section.append(el('h2', 'Done today'), list(done));
}

function speakPrompt(text, lang) {
  const synth = window.speechSynthesis;
  if (!synth || typeof SpeechSynthesisUtterance === 'undefined') return false;
  synth.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = lang;
  utterance.rate = 0.85;  // slower than default for older listeners
  const voice = (synth.getVoices() || []).find((v) => (v.lang || '').toLowerCase().startsWith(lang));
  if (voice) utterance.voice = voice;
  synth.speak(utterance);
  return true;
}

async function renderResidentCheck(main, params, patientId) {
  const lang = residentLanguage(params.lang);
  const prompt = RESIDENT_PROMPTS[lang];
  const name = firstNameOf(patientId);
  main.replaceChildren();
  const card = el('section', '', {class: 'bl-check-card', 'data-mode': 'resident', 'data-state': 'ready'});
  const heading = el('h1', prompt.title, {tabindex: '-1'});
  const text = el('p', CHECK_PROMPT, {class: 'bl-prompt', lang});
  const hear = el('button', 'Hear the instructions', {type: 'button', class: 'bl-hear'});
  const language = el('select', '', {id: 'bl-lang', class: 'bl-lang'});
  Object.entries(RESIDENT_PROMPTS).forEach(([code, p]) => {
    const option = el('option', p.label, {value: code});
    if (code === lang) option.setAttribute('selected', '');
    language.append(option);
  });
  const languageLabel = el('label', 'Language ', {for: 'bl-lang', class: 'bl-lang-label'});
  languageLabel.append(language);
  const record = el('button', 'Start', {type: 'button', class: 'bl-record'});
  const listening = el('div', '', {class: 'bl-listening', role: 'status', 'aria-live': 'polite', hidden: ''});
  const message = el('div', '', {class: 'bl-resident-message', role: 'status', 'aria-live': 'polite'});
  const resend = el('button', 'Send again', {type: 'button', class: 'bl-retry', hidden: ''});
  const skip = el('button', 'Skip today', {type: 'button', class: 'bl-skip'});
  const back = el('a', 'Back to the list', {href: residentLink(params, null), class: 'bl-back', hidden: ''});
  const actions = el('div', '', {class: 'bl-resident-actions'});
  actions.append(record, skip);
  card.append(heading, text, hear, languageLabel, actions, listening, message, resend, back);
  main.append(card);

  const canSpeak = typeof window.speechSynthesis !== 'undefined'
    && typeof SpeechSynthesisUtterance !== 'undefined';
  hear.hidden = !canSpeak;
  languageLabel.hidden = Object.keys(RESIDENT_PROMPTS).length < 2;
  hear.addEventListener('click', () => speakPrompt(prompt.spoken, lang));
  language.addEventListener('change', () => {
    location.search = new URLSearchParams({...Object.fromEntries(new URLSearchParams(location.search)),
                                           lang: residentLanguage(language.value)}).toString();
  });

  let flow = {unusable: 0, done: false};
  let attempt = 0;
  let recorder = null;
  let stream = null;
  let timer = null;
  let limit = null;
  let kept = null;
  let discard = false;

  const say = (lines) => {
    message.replaceChildren(...lines.map((line) => el('p', line)));
  };
  const finish = (lines, view) => {
    flow = {...flow, done: true};
    card.dataset.state = view;
    record.hidden = true;
    skip.hidden = true;
    hear.hidden = true;
    resend.hidden = true;
    listening.hidden = true;
    back.hidden = false;
    say(lines);
    heading.focus();
  };
  const needHelp = (error) => {
    if (error) console.error(error);  // technical detail stays in the console, never on screen
    card.dataset.state = 'help';
    listening.hidden = true;
    say([RESIDENT_TEXT.help]);
  };

  function stop() {
    clearInterval(timer);
    clearTimeout(limit);
    if (recorder && recorder.state !== 'inactive') recorder.stop();
  }

  async function submit(blob) {
    resend.hidden = true;
    record.disabled = true;
    card.dataset.state = 'sending';
    say([RESIDENT_TEXT.sending]);
    const fields = {patient_id: patientId, mode: 'resident', device_id: 'check-page',
                    device_ts: new Date().toISOString(), is_baseline: 'false'};
    let data;
    try {
      const fixtures = params.fixture.split(',');
      data = params.mock
        ? await mockCheck(fixtures[Math.min(attempt, fixtures.length - 1)])
        : await uploadCheck(blob, fields, () => {});
    } catch (error) {
      needHelp(error);
      resend.hidden = false;  // staff can resend the kept clip; it is not a new attempt
      record.disabled = false;
      return;
    }
    if (flow.done) return;  // skipped while the clip was being sent
    attempt += 1;
    kept = null;
    record.disabled = false;
    const step = residentStep(flow, data.usable === true);  // read nothing else from the result
    flow = step.flow;
    if (step.view === 'retry') {
      card.dataset.state = 'retry';
      record.textContent = 'Try once more';
      say([RESIDENT_TEXT.again]);
      record.focus();
    } else {
      finish([RESIDENT_TEXT.thanks(name), RESIDENT_TEXT.done], step.view);
    }
  }

  record.addEventListener('click', async () => {
    if (recorder && recorder.state === 'recording') { stop(); return; }
    if (flow.done) return;
    if (canSpeak) window.speechSynthesis.cancel();  // never record the spoken prompt
    const mimeType = pickMimeType();
    if (mimeType === null || !navigator.mediaDevices) { needHelp(new Error('no MediaRecorder')); return; }
    try {
      stream = await navigator.mediaDevices.getUserMedia({audio: true});
    } catch (error) {
      needHelp(error);  // permission denied or no microphone
      return;
    }
    const chunks = [];
    discard = false;
    recorder = new MediaRecorder(stream, mimeType ? {mimeType} : undefined);
    recorder.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    recorder.onerror = (e) => { discard = true; stop(); needHelp(e && e.error); };
    recorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      clearInterval(timer);
      listening.hidden = true;
      record.textContent = flow.unusable ? 'Try once more' : 'Start';
      record.setAttribute('aria-pressed', 'false');
      if (discard) return;
      kept = new Blob(chunks, {type: recorder.mimeType || mimeType || 'audio/webm'});
      submit(kept);
    };
    say([]);
    recorder.start();
    card.dataset.state = 'listening';
    record.textContent = 'Stop';
    record.setAttribute('aria-pressed', 'true');
    listening.hidden = false;
    const startedAt = Date.now();
    const tick = () => {
      const left = Math.max(0, Math.ceil(CHECK_MAX_S - (Date.now() - startedAt) / 1000));
      listening.replaceChildren(el('span', '', {class: 'bl-listening-dot', 'aria-hidden': 'true'}),
                                el('span', `${RESIDENT_TEXT.listening} ${left} s`));
    };
    tick();
    timer = setInterval(tick, 250);
    limit = setTimeout(stop, CHECK_MAX_S * 1000);
  });

  resend.addEventListener('click', () => { if (kept) submit(kept); });

  skip.addEventListener('click', () => {
    if (recorder && recorder.state === 'recording') { discard = true; stop(); }
    if (canSpeak) window.speechSynthesis.cancel();
    // Not logged server-side yet: the skip-log endpoint is part of the ADR 017 proposal.
    finish([RESIDENT_TEXT.skipped, RESIDENT_TEXT.thanks(name)], 'skipped');
  });

  card.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && recorder && recorder.state === 'recording') stop();
  });
  heading.focus();
}
