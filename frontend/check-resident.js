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
  again: "Thank you. Would you like to try once more? You can skip today instead.",
  skipped: "That's okay, we'll skip today.",
  help: "Let's stop here for now. Please ask a staff member to help.",
  consent: 'We need to check with the nurse before we start.',
  listening: "I'm listening…",
  sending: 'Saving…',
};

const SKIP_REASONS = [['declined', "Doesn't want to today"], ['asleep', 'Asleep'],
                      ['unwell', 'Unwell'], ['not_available', 'Not available'], ['other', 'Other']];

function residentLanguage(code) {
  return Object.prototype.hasOwnProperty.call(RESIDENT_PROMPTS, code) ? code : null;
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

const DUE_ORDER = {due: 0, consent_needed: 1, language_unavailable: 2, skipped: 3, done: 4};

// Rows of GET /v1/checks/due, named from the demo session where possible. Only fields that
// carry no score are copied, so nothing else can be rendered by accident.
function dueNowItems(residents, sessionPatients) {
  const names = new Map((sessionPatients || []).map((p) => [p.id, p.name]));
  return (residents || []).map((r) => ({
    patient_id: r.patient_id,
    name: names.get(r.patient_id) || r.display_name || 'Resident',
    status: Object.prototype.hasOwnProperty.call(DUE_ORDER, r.status) ? r.status : 'consent_needed',
    last_check_ts: r.last_check_ts || null,
    profile_state: r.check_profile && r.check_profile.state,
    // Server-computed and currently always null (unknown); shown only when exactly true.
    observation_helped: r.observation_helped === true,
  })).sort((a, b) => (DUE_ORDER[a.status] - DUE_ORDER[b.status])
    || (a.last_check_ts || '').localeCompare(b.last_check_ts || ''));
}

function residentLink(params, patientId) {
  const q = new URLSearchParams({mode: 'resident'});
  if (patientId) q.set('patient', patientId);
  if (params.device) q.set('device', params.device);
  if (params.careAideDemo && patientId) q.set('demo', 'personal');
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
  const liveVolunteer = (id) => (state.session.patients || []).some((p) =>
    p.id === id && p.capture_mode === 'live' && p.scripted_cohort !== true);
  const list = (rows, linked) => {
    const ul = el('ul', '', {class: 'bl-due-list'});
    rows.forEach((item) => {
      const li = el('li', '');
      const repeatDemo = item.status === 'done' && liveVolunteer(item.patient_id);
      const row = linked || repeatDemo
        ? el('a', item.name, {href: residentLink({...params, careAideDemo: params.careAideDemo || repeatDemo}, item.patient_id), class: 'bl-due-item'})
        : el('div', item.name, {class: 'bl-due-blocked'});
      if (!linked && item.status === 'consent_needed') {
        row.append(el('span', 'Consent not recorded. Ask the nurse.', {class: 'bl-due-note'}));
      }
      if (!linked && item.status === 'language_unavailable') {
        row.append(el('span', item.profile_state === 'unsupported'
          ? 'This language is not supported yet. Ask the nurse.'
          : 'Language not configured. Ask the nurse.', {class: 'bl-due-note'}));
      }
      if (item.observation_helped) row.append(el('span', 'Your observation helped', {class: 'bl-helped'}));
      if (repeatDemo) row.append(el('span', 'Demo: record another check', {class: 'bl-due-note'}));
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
  if (of('language_unavailable').length) section.append(el('h2', 'Needs language setup'), list(of('language_unavailable'), false));
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
  let disposed = false, disposeCapture = () => {};
  window.addEventListener('pagehide', () => { disposed = true; disposeCapture(); }, {once: true});
  let profile;
  try {
    // Mock mode declares an English protocol explicitly; roster text is never a given name.
    profile = params.mock ? {state: 'ready', protocol_locale: 'en', prompt_version: 'count20-days-v1',
      first_name: null, version: 'mock', voice_consent_state: 'granted'} : await api(`/v1/patients/${patientId}/check-profile`);
  } catch (_) { profile = {state: 'unconfigured'}; }
  if (disposed) return;
  const lang = residentLanguage(profile.protocol_locale);
  if (profile.state !== 'ready' || !lang || profile.prompt_version !== RESIDENT_PROMPTS[lang].promptVersion
      || (params.lang && params.lang !== lang)) {
    const blocked = el('section', '', {class: 'bl-check-card', 'data-mode': 'resident', 'data-state': 'language_unavailable'});
    blocked.append(el('h1', "Let's pause here"), el('p',
      profile.state === 'unsupported' || (params.lang && params.lang !== lang)
        ? 'This language is not supported yet. Please ask a staff member to help.'
        : 'The counting language needs to be set up. Please ask a staff member to help.',
      {class: 'bl-resident-message', role: 'status'}),
    el('a', 'Back to the list', {href: residentLink(params, null), class: 'bl-back'}));
    main.replaceChildren(blocked);
    return;
  }
  const prompt = RESIDENT_PROMPTS[lang];
  const name = profile.first_name;
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
  reasons.append(el('p', 'For staff: record why we are skipping today.', {class: 'workspace-muted'}));
  SKIP_REASONS.forEach(([code, label]) => {
    const b = el('button', label, {type: 'button', 'data-reason': code});
    reasons.append(b);
  });
  const back = el('a', 'Back to the list', {href: residentLink(params, null), class: 'bl-back', hidden: ''});
  const repeat = el('a', 'Record another demo check', {href: residentLink(params, patientId),
    class: 'workspace-secondary', 'data-demo-repeat': '', hidden: ''});
  const actions = el('div', '', {class: 'bl-resident-actions'});
  actions.append(record, skip);
  const drawing = el('img', '', {src: '/assets/resident-together.svg', alt: '',
    class: 'resident-together', width: '142', height: '95'});
  const purpose = el('p', 'This records your voice for your care team. It is sent when you stop or after half a minute. You can choose Skip today to stop without sending.',
    {class: 'resident-purpose'});
  if (params.careAideDemo) card.append(el('p', name ? `Voice check for ${name}` : 'Live volunteer voice check', {class: 'workspace-eyebrow'}));
  card.append(drawing, heading, purpose, text, hear, languageLabel, actions, reasons, listening, message, resend, repeat, back);
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
  let operation = 0;
  disposeCapture = () => {
    operation++; discard = true; kept = null;
    if (stream) stream.getTracks().forEach(t => t.stop());
    stop();
    if (canSpeak) window.speechSynthesis.cancel();
  };

  const say = (lines) => {
    message.replaceChildren(...lines.map((line) => el('p', line)));
  };
  const finish = (lines, view) => {
    operation++;
    flow = {...flow, done: true};
    card.dataset.state = view;
    purpose.hidden = true;
    text.hidden = true;
    record.hidden = true;
    skip.hidden = true;
    hear.hidden = true;
    resend.hidden = true;
    listening.hidden = true;
    reasons.hidden = true;
    back.hidden = false;
    repeat.hidden = !params.careAideDemo || !['thanks', 'accepted'].includes(view);
    say(lines);
    heading.focus();
  };
  const needHelp = (error) => {
    if (disposed) return;
    if (error) console.error(error);  // technical detail stays in the console, never on screen
    if (flow.done || skipping) return;
    card.dataset.state = 'help';
    listening.hidden = true;
    say([RESIDENT_TEXT.help]);
  };
  // The server refuses checks without granted consent (403 consent_required); mirror that so
  // nobody is asked to speak for a clip that would be refused.
  const consentBlocked = () => {
    operation++; kept = null; record.disabled = true;
    card.dataset.state = 'consent';
    purpose.hidden = true;
    text.hidden = true;
    record.hidden = true;
    hear.hidden = true;
    resend.hidden = true;
    listening.hidden = true;
    say([RESIDENT_TEXT.consent]);
    heading.focus();
  };
  const validateSetup = async (op) => {
    const current = await api(`/v1/patients/${patientId}/check-profile`);
    if (disposed || flow.done || skipping || op !== operation) return false;
    if (current.voice_consent_state !== 'granted') { consentBlocked(); return false; }
    if (current.state !== 'ready' || current.version !== profile.version) {
      kept = null;
      finish(['The counting setup changed. Please ask a staff member to reload this page.'], 'help');
      return false;
    }
    return true;
  };

  function stop() {
    clearInterval(timer);
    clearTimeout(limit);
    if (recorder && recorder.state !== 'inactive') recorder.stop();
  }

  async function submit(blob) {
    if (disposed || flow.done || skipping) return;
    const op = ++operation;
    resend.hidden = true;
    record.disabled = true;
    card.dataset.state = 'sending';
    say([RESIDENT_TEXT.sending]);
    const fields = {patient_id: patientId, mode: 'resident', device_id: checkDeviceId(params),
                    device_ts: new Date().toISOString(), is_baseline: 'false',
                    profile_version: profile.version, protocol_locale: lang};
    let data;
    try {
      const fixtures = params.fixture.split(',');
      data = params.mock
        ? await mockCheck(fixtures[Math.min(attempt, fixtures.length - 1)])
        : await uploadCheck(blob, fields, () => {}, {...(params.careAideDemo ? {delays: []} : {}), send: async (audio, values) => {
          if (!await validateSetup(op)) {
            const error = new Error('Counting setup no longer admits this attempt.');
            error.status = 409; throw error;
          }
          return postCheck(audio, values);
        }});
    } catch (error) {
      if (disposed || flow.done || skipping || op !== operation) return;
      record.disabled = false;
      if (error.status === 409) {
        kept = null;
        finish(['The counting setup changed. Please ask a staff member to reload this page.'], 'help');
        return;
      }
      if (error.status === 403) { console.error(error); consentBlocked(); return; }
      needHelp(error);
      resend.hidden = Boolean(params.careAideDemo);
      if (params.careAideDemo) {
        kept = null;
        finish(['Ask the nurse to check whether this recording was saved before starting another check.'], 'help');
      }
      return;
    }
    if (disposed || flow.done || skipping || op !== operation) return;
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
      finish([RESIDENT_TEXT.thanks(name), params.careAideDemo
        ? 'Your check has been sent to the care team.' : RESIDENT_TEXT.done], step.view);
    }
  }

  record.addEventListener('click', async () => {
    if (recorder && recorder.state === 'recording') { stop(); return; }
    if (disposed || flow.done || skipping || capturePending) return;
    const op = ++operation;
    kept = null; resend.hidden = true;
    if (canSpeak) window.speechSynthesis.cancel();  // never record the spoken prompt
    const mimeType = pickMimeType();
    if (mimeType === null || !navigator.mediaDevices) { needHelp(new Error('no MediaRecorder')); return; }
    try {
      capturePending = true;
      record.disabled = true;
      if (!params.mock) {
        if (!await validateSetup(op)) return;
      }
      if (disposed || flow.done || skipping || op !== operation) return;
      stream = await navigator.mediaDevices.getUserMedia({audio: true});
    } catch (error) {
      needHelp(error);  // permission denied or no microphone
      return;
    } finally {
      capturePending = false;
      record.disabled = disposed || flow.done || skipping || op !== operation;
    }
    if (disposed || flow.done || skipping || op !== operation) { stream.getTracks().forEach((t) => t.stop()); return; }
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
      if (discard || disposed || flow.done || skipping || op !== operation) return;
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
    operation++;
    skipping = true;  // invalidates an in-flight permission request before it resolves
    kept = null;
    record.hidden = true;
    resend.hidden = true;
    if (recorder && recorder.state === 'recording') { discard = true; stop(); }
    if (canSpeak) window.speechSynthesis.cancel();
    say([RESIDENT_TEXT.skipped]);
    purpose.hidden = true; text.hidden = true;
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
    if (profile.voice_consent_state === 'granted') record.disabled = false;
    else consentBlocked();
  }
}
