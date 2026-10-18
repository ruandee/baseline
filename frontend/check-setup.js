// Nurse capture setup. Never mounted by the resident/PSW view and never grants by default.
window.checkSetup = async function(host, patientId, changed) {
  const section = el('section', '', {class: 'bl-check-setup', 'aria-label': 'Care-team counting setup'});
  const message = el('p', 'Loading counting setup...', {role: 'status'});
  const person = (state.session.patients || []).find(p => p.id === patientId);
  section.append(el('h2', 'Care-team counting setup'),
    el('p', `For ${person ? person.name : patientId}`), message);
  host.append(section);
  const controller = {ready: false, profile: null, generation: 0};
  let pendingMutations = 0, closed = false;
  const notify = (ready) => {
    controller.ready = Boolean(ready);
    controller.generation++;
    changed(controller.ready, pendingMutations > 0);
  };
  let consent;
  const profilePath = `/v1/patients/${patientId}/check-profile`;
  const consentPath = `/v1/patients/${patientId}/consent?scope=voice_check`;
  const update = () => {
    notify(controller.profile && controller.profile.state === 'ready' && consent
      && consent.state === 'granted');
  };
  const refresh = async () => {
    if (closed || pendingMutations) return false;
    notify(false);
    const generation = controller.generation;
    const stale = () => closed || pendingMutations > 0 || generation !== controller.generation;
    const profile = await api(profilePath);
    if (stale()) return false;
    if (!profile.can_configure || !profile.can_record_consent) {
      throw new Error('An assigned nurse must configure voice capture.');
    }
    const currentConsent = await api(consentPath);
    if (stale()) return false;
    controller.profile = profile;
    consent = currentConsent;
    update();
    return controller.ready;
  };
  controller.refresh = refresh;
  controller.dispose = () => { closed = true; notify(false); };
  try { await refresh(); }
  catch (error) { message.textContent = error.message; return controller; }
  const field = (label, control) => {
    const node = el('label', label, {class: 'bl-setup-field'}); node.append(control); return node;
  };
  const checkbox = (label) => {
    const input = el('input', '', {type: 'checkbox'});
    const node = el('label', label, {class: 'bl-setup-confirm'}); node.prepend(input);
    return [node, input];
  };
  const name = el('input', '', {type: 'text', maxlength: '80', 'aria-label': 'Explicit first name'});
  name.value = controller.profile.first_name || '';
  const locale = el('input', '', {type: 'text', maxlength: '35', 'aria-label': 'Preferred locale'});
  locale.value = controller.profile.preferred_locale || '';
  const [profileLabel, profileConfirmed] = checkbox(' I confirmed these resident details.');
  const saveProfile = el('button', 'Save counting profile', {type: 'button'});
  saveProfile.disabled = true;
  profileConfirmed.addEventListener('change', () => { saveProfile.disabled = !profileConfirmed.checked; });
  const profileForm = el('fieldset', '');
  profileForm.append(el('legend', 'Resident details'), field('Explicit first name (optional)', name),
    field('Preferred locale (en supports the English counting protocol)', locale),
    el('p', 'Blank means unconfigured. Other locales remain unsupported and block counting.'),
    profileLabel, saveProfile);
  const consentView = el('p', '');
  const decision = el('select', '', {'aria-label': 'Voice permission decision'});
  for (const [value, label] of [['', 'Choose a decision'], ['granted', 'The person agrees'],
    ['declined', 'The person declines'], ['withdrawn', 'Permission withdrawn']]) {
    decision.append(el('option', label, {value}));
  }
  const maker = el('select', '', {'aria-label': 'Voice decision maker'});
  for (const [value, label] of [['', 'Choose who decided'], ['resident', 'The person'],
    ['substitute_decision_maker', 'Substitute decision maker']]) maker.append(el('option', label, {value}));
  const reference = el('input', '', {type: 'text', maxlength: '200', 'aria-label': 'Voice SDM reference'});
  const [consentLabel, consentConfirmed] = checkbox(' I confirmed this voice-check permission decision.');
  const saveConsent = el('button', 'Record voice permission', {type: 'button'});
  saveConsent.disabled = true;
  consentConfirmed.addEventListener('change', () => { saveConsent.disabled = !consentConfirmed.checked; });
  const consentForm = el('fieldset', '');
  consentForm.append(el('legend', 'Voice-check permission'), consentView,
    field('Decision', decision), field('Decision maker', maker),
    field('SDM reference (required for a substitute decision maker)', reference), consentLabel, saveConsent);
  const show = () => {
    if (closed) return;
    consentView.textContent = `Stored permission: ${consent.state}`
      + (consent.recorded_at ? `, recorded ${consent.recorded_at}` : '') + '.';
    message.textContent = controller.ready ? 'Counting is ready. Recording starts only when you tap Record.'
      : `Recording blocked. Profile: ${controller.profile.state}; voice permission: ${consent.state}.`;
  };
  section.append(profileForm, consentForm); show();
  controller.refresh = async () => { const ready = await refresh(); show(); return ready; };
  saveProfile.addEventListener('click', async () => {
    if (closed || !profileConfirmed.checked) return;
    let pending = true;
    saveProfile.disabled = true; pendingMutations++; notify(false);
    try {
      await api(profilePath, {method: 'PUT', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({first_name: name.value.trim() || null, preferred_locale: locale.value.trim() || null})});
      pendingMutations--; pending = false; await refresh(); show();
    } catch (error) { if (!closed) { notify(false); message.textContent = `Profile not saved: ${error.message}`; } }
    finally {
      if (pending) pendingMutations--;
      profileConfirmed.checked = false; saveProfile.disabled = true;
    }
  });
  saveConsent.addEventListener('click', async () => {
    if (closed || !consentConfirmed.checked) return;
    let pending = true;
    saveConsent.disabled = true; pendingMutations++; notify(false);
    try {
      if (!decision.value || !maker.value) throw new Error('Choose the actual decision and decision maker.');
      const body = {scope: 'voice_check', status: decision.value, decided_by: maker.value};
      if (maker.value === 'substitute_decision_maker') {
        if (!reference.value.trim()) throw new Error('A substitute decision maker reference is required.');
        body.sdm_reference = reference.value.trim();
      }
      await api(`/v1/patients/${patientId}/consents`, {method: 'POST',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
      pendingMutations--; pending = false; await refresh(); show();
    } catch (error) { if (!closed) { notify(false); message.textContent = `Permission not recorded: ${error.message}`; } }
    finally {
      if (pending) pendingMutations--;
      consentConfirmed.checked = false; saveConsent.disabled = true; reference.value = '';
    }
  });
  return controller;
};
