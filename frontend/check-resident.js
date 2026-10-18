// /check resident and PSW experience (BL-31). Loaded before check.js; check.js hands resident
// mode to renderResidentLanding (no patient: the PSW "due now" list) or renderResidentCheck.
// Residents and PSWs never see scores, verdicts, features or technical errors: the landing reads
// the score-free GET /v1/checks/due, and the check view reads only `usable` from a result.
// Consent is enforced by the server (decision 017); the page only mirrors it so nobody records
// a clip that would be refused.

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
  consent: 'We need to check with the nurse before we start.',
  listening: "I'm listening…",
  sending: 'Saving…',
};

const SKIP_REASONS = [['declined', "Doesn't want to today"], ['asleep', 'Asleep'],
                      ['unwell', 'Unwell'], ['not_available', 'Not available'], ['other', 'Other']];

function residentLanguage(code) {
  return Object.prototype.hasOwnProperty.call(RESIDENT_PROMPTS, code) ? code : 'en';
}

function firstNameOf(patientId) {
  const patients = (state.session && state.session.patients) || [];
  const found = patients.find((p) => p.id === patientId);
  const first = found && found.name ? found.name.trim().split(/\s+/)[0] : '';
  // An honorific or anonymized initial is not a given name. Keep the close warm without
  // addressing someone as "Mrs." or guessing a name that the roster does not supply.
  return !first || /^(?:mr|mrs|ms|miss|mx|dr)\.?$/i.test(first)
    || /^\p{L}\.?$/u.test(first) ? null : first;
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

const DUE_ORDER = {due: 0, consent_needed: 1, skipped: 2, done: 3};

// Rows of GET /v1/checks/due, named from the demo session where possible. Only fields that
// carry no score are copied, so nothing else can be rendered by accident.
function dueNowItems(residents, sessionPatients) {
  const names = new Map((sessionPatients || []).map((p) => [p.id, p.name]));
  return (residents || []).map((r) => ({
    patient_id: r.patient_id,
    name: names.get(r.patient_id) || r.display_name || 'Resident',
    status: Object.prototype.hasOwnProperty.call(DUE_ORDER, r.status) ? r.status : 'consent_needed',
    last_check_ts: r.last_check_ts || null,
    // Server-computed and currently always null (unknown); shown only when exactly true.
    observation_helped: r.observation_helped === true,
  })).sort((a, b) => (DUE_ORDER[a.status] - DUE_ORDER[b.status])
    || (a.last_check_ts || '').localeCompare(b.last_check_ts || ''));
}

function residentLink(params, patientId) {
  const q = new URLSearchParams({mode: 'resident'});
  if (patientId) q.set('patient', patientId);
  if (params.lang && params.lang !== 'en') q.set('lang', params.lang);
  if (params.device) q.set('device', params.device);
  if (params.mock) { q.set('mock', '1'); q.set('fixture', params.fixture); }
  return `/check?${q}`;
}

async function renderResidentLanding(main, params) {
  main.replaceChildren();
  const section = el('section', '', {class: 'bl-due', 'data-mode': 'resident'});
  const status = el('p', 'Loading…', {class: 'bl-due-status', role: 'status'});
  section.append(el('h1', 'Due now'), status);
  main.append(section);
  let residents;
  try {
    // Mock mode lists the session's synthetic residents as due and calls no patient API.
    residents = params.mock
      ? (state.session.patients || []).map((p) => ({patient_id: p.id, display_name: p.name,
                                                    status: 'due'}))
      : (await api('/v1/checks/due')).residents;
  } catch (error) {
    console.error(error);
    status.textContent = 'The list could not be loaded. Please try again or ask the nurse.';
    return;
  }
  const items = dueNowItems(residents, state.session.patients);
  const list = (rows, linked) => {
    const ul = el('ul', '', {class: 'bl-due-list'});
    rows.forEach((item) => {
      const li = el('li', '');
      const row = linked
        ? el('a', item.name, {href: residentLink(params, item.patient_id), class: 'bl-due-item'})
        : el('div', item.name, {class: 'bl-due-blocked'});
      if (!linked && item.status === 'consent_needed') {
        row.append(el('span', 'Consent not recorded. Ask the nurse.', {class: 'bl-due-note'}));
      }
      if (item.observation_helped) row.append(el('span', 'Your observation helped', {class: 'bl-helped'}));
      li.append(row);
      ul.append(li);
    });
    return ul;
  };
  const of = (s) => items.filter((i) => i.status === s);
  const due = of('due');
  status.textContent = due.length ? `${due.length === 1 ? 'One resident' : `${due.length} residents`} ` +
    'still to check today.' : 'Nobody is waiting for a check right now.';
  if (due.length) section.append(list(due, true));
  if (of('consent_needed').length) section.append(el('h2', 'Needs consent'), list(of('consent_needed'), false));
  if (of('skipped').length) section.append(el('h2', 'Skipped today'), list(of('skipped'), true));
  if (of('done').length) section.append(el('h2', 'Done today'), list(of('done'), false));
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
  const reasons = el('div', '', {class: 'bl-skip-reasons', role: 'group',
                                 'aria-label': 'Why are we skipping today?', hidden: ''});
  SKIP_REASONS.forEach(([code, label]) => {
    const b = el('button', label, {type: 'button', 'data-reason': code});
    reasons.append(b);
  });
  const back = el('a', 'Back to the list', {href: residentLink(params, null), class: 'bl-back', hidden: ''});
  const actions = el('div', '', {class: 'bl-resident-actions'});
  actions.append(record, skip);
  card.append(heading, text, hear, languageLabel, actions, reasons, listening, message, resend, back);
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
  let capturePending = false;
  let skipping = false;

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
    reasons.hidden = true;
    back.hidden = false;
    say(lines);
    heading.focus();
  };
  const needHelp = (error) => {
    if (error) console.error(error);  // technical detail stays in the console, never on screen
    if (flow.done || skipping) return;
    card.dataset.state = 'help';
    listening.hidden = true;
    say([RESIDENT_TEXT.help]);
  };
  // The server refuses checks without granted consent (403 consent_required); mirror that so
  // nobody is asked to speak for a clip that would be refused.
  const consentBlocked = () => {
    card.dataset.state = 'consent';
    record.hidden = true;
    hear.hidden = true;
    resend.hidden = true;
    listening.hidden = true;
    say([RESIDENT_TEXT.consent]);
    heading.focus();
  };

  function stop() {
    clearInterval(timer);
    clearTimeout(limit);
    if (recorder && recorder.state !== 'inactive') recorder.stop();
  }

  async function submit(blob) {
    if (flow.done || skipping) return;
    resend.hidden = true;
    record.disabled = true;
    card.dataset.state = 'sending';
    say([RESIDENT_TEXT.sending]);
    const fields = {patient_id: patientId, mode: 'resident', device_id: checkDeviceId(params),
                    device_ts: new Date().toISOString(), is_baseline: 'false'};
    let data;
    try {
      const fixtures = params.fixture.split(',');
      data = params.mock
        ? await mockCheck(fixtures[Math.min(attempt, fixtures.length - 1)])
        : await uploadCheck(blob, fields, () => {});
    } catch (error) {
      if (flow.done || skipping) return;
      record.disabled = false;
      if (error.status === 403) { console.error(error); consentBlocked(); return; }
      needHelp(error);
      resend.hidden = false;  // staff can resend the kept clip; it is not a new attempt
      return;
    }
    if (flow.done || skipping) return;  // skipped while the clip was being sent
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
    if (flow.done || skipping || capturePending) return;
    if (canSpeak) window.speechSynthesis.cancel();  // never record the spoken prompt
    const mimeType = pickMimeType();
    if (mimeType === null || !navigator.mediaDevices) { needHelp(new Error('no MediaRecorder')); return; }
    try {
      capturePending = true;
      record.disabled = true;
      stream = await navigator.mediaDevices.getUserMedia({audio: true});
    } catch (error) {
      needHelp(error);  // permission denied or no microphone
      return;
    } finally {
      capturePending = false;
      record.disabled = false;
    }
    if (flow.done || skipping) { stream.getTracks().forEach((t) => t.stop()); return; }
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
      if (discard || flow.done || skipping) return;
      kept = new Blob(chunks, {type: recorder.mimeType || mimeType || 'audio/webm'});
      submit(kept);
    };
    say([]);
    reasons.hidden = true;
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
    skipping = true;  // invalidates an in-flight permission request before it resolves
    kept = null;
    record.hidden = true;
    resend.hidden = true;
    if (recorder && recorder.state === 'recording') { discard = true; stop(); }
    if (canSpeak) window.speechSynthesis.cancel();
    reasons.hidden = false;  // staff pick why; the skip is logged once a reason is chosen
    reasons.querySelector('button').focus();
  });

  reasons.addEventListener('click', async (event) => {
    const code = event.target && event.target.getAttribute && event.target.getAttribute('data-reason');
    if (!code || flow.done || reasons.dataset.saving === 'true') return;
    reasons.dataset.saving = 'true';
    if (!params.mock) {
      try {
        await api(`/v1/patients/${patientId}/checks/skips`, {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({reason: code, device_ts: new Date().toISOString()})});
      } catch (error) {
        console.error(error);
        card.dataset.state = 'help';
        say([RESIDENT_TEXT.help]);  // reasons stay visible so staff can try again
        reasons.dataset.saving = 'false';
        return;
      }
    }
    finish([RESIDENT_TEXT.skipped, RESIDENT_TEXT.thanks(name)], 'skipped');
  });

  card.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && recorder && recorder.state === 'recording') stop();
  });
  heading.focus();

  if (!params.mock) {
    record.disabled = true;  // until the server confirms consent
    try {
      const due = await api('/v1/checks/due');
      const consent = (due.residents || []).find((r) => r.patient_id === patientId);
      if (flow.done || skipping) return;
      if (consent && consent.consent_state === 'granted') record.disabled = false;
      else consentBlocked();
    } catch (error) {
      console.error(error);
      consentBlocked();  // unknown is not granted; the server would refuse the clip anyway
    }
  }
}
