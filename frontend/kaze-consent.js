// Standing voice permission is separate from session setup. Never grant on page load or arm.
window.kazeVoicePermission = async function(host, patientId) {
  let generation = 0, readSequence = 0, disposed = false, saving = false, decisionBlocked = false;
  const listeners = new Set();
  const controller = {ready: false};
  const section = el('fieldset', '', {class: 'kaze-permission'});
  const stateView = el('p', 'Checking stored voice permission...', {role: 'status'});
  const message = el('p', '', {role: 'status'});
  const decision = el('select', '', {'aria-label': 'My voice permission decision'});
  for (const [value, label] of [['', 'Choose my decision'], ['granted', 'I agree'],
    ['declined', 'I decline'], ['withdrawn', 'I withdraw permission']]) {
    decision.append(el('option', label, {value}));
  }
  const confirmed = el('input', '', {type: 'checkbox', 'aria-label': 'Confirm my voice decision'});
  const confirmation = el('label', ' I confirm this is my voice-check permission decision.');
  confirmation.prepend(confirmed);
  const save = el('button', 'Save my voice permission', {type: 'button'});
  save.disabled = true;
  section.append(el('legend', 'Stored voice-check permission'), stateView,
    el('p', 'This permission stays recorded until you withdraw it or its recorded expiry. '
      + 'Arming or ending a session does not grant or withdraw permission.'),
    decision, confirmation, save, message);
  host.replaceChildren(section);
  const notify = (ready) => {
    controller.ready = Boolean(ready) && !saving && !disposed && !decisionBlocked;
    for (const listener of listeners) listener(controller.ready);
  };
  controller.watch = (listener) => {
    listeners.add(listener); listener(controller.ready);
    return () => listeners.delete(listener);
  };
  controller.refresh = async () => {
    const own = generation, read = ++readSequence;
    if (disposed || saving) return false;
    try {
      const stored = await api(`/v1/patients/${patientId}/consent?scope=voice_check`);
      if (disposed || saving || own !== generation || read !== readSequence) return false;
      stateView.textContent = `Stored voice permission: ${stored.state}.`;
      notify(stored.state === 'granted');
      return controller.ready;
    } catch (_) {
      if (!disposed && own === generation && read === readSequence) {
        stateView.textContent = 'Stored voice permission is unavailable. Recording is blocked.';
        notify(false);
      }
      return false;
    }
  };
  controller.requireGranted = async () => {
    const own = generation;
    if (!await controller.refresh() || disposed || saving || own !== generation) {
      throw new Error('Voice permission is not currently granted');
    }
  };
  const updateSave = () => { save.disabled = saving || !decision.value || !confirmed.checked; };
  decision.addEventListener('change', () => { confirmed.checked = false; updateSave(); });
  confirmed.addEventListener('change', updateSave);
  save.addEventListener('click', async () => {
    if (saving || disposed || !decision.value || !confirmed.checked) return;
    const own = ++generation;
    saving = true; decisionBlocked = true; notify(false); updateSave(); // Invalidate pending microphones before the POST.
    try {
      await api(`/v1/patients/${patientId}/consents`, {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({scope: 'voice_check', status: decision.value, decided_by: 'resident'})});
      if (disposed || own !== generation) return;
      saving = false; decisionBlocked = false;
      await controller.refresh();
      if (!disposed && own === generation) message.textContent = 'Your decision was recorded.';
    } catch (_) {
      if (!disposed && own === generation) {
        notify(false); message.textContent = 'Could not record your decision. Recording is blocked; try again.';
      }
    } finally {
      if (!disposed && own === generation) {
        saving = false; confirmed.checked = false; decision.value = ''; save.disabled = true;
      }
    }
  });
  window.addEventListener('pagehide', () => {
    disposed = true; generation++; notify(false); listeners.clear();
  }, {once: true});
  await controller.refresh();
  return controller;
};
