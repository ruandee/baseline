// Nurse workspace: read-only preparation, then the existing guarded recorder.
window.renderNurseChecks = async function(main, {api, el, session}) {
  main.replaceChildren();
  const page = el('section', '', {class: 'nurse-workspace'});
  const heading = el('header', '', {class: 'workspace-heading'});
  heading.append(el('p', 'NURSE WORKSPACE', {class: 'workspace-eyebrow'}),
    el('h1', 'Voice checks'),
    el('p', 'Compare how someone speaks with their own previous checks, then review the result alongside their records.',
      {class: 'workspace-intro'}));
  const steps = el('ol', '', {class: 'nurse-steps', 'aria-label': 'Voice check steps'});
  ['Choose a person', 'Review permission and setup', 'Record and review'].forEach((text) =>
    steps.append(el('li', text)));
  const panel = el('section', '', {class: 'workspace-panel nurse-person'});
  panel.append(el('h2', 'Who is this check for?'),
    el('p', 'Choose the person who will speak. Each person needs their own history.', {class: 'workspace-muted'}));
  const search = el('input', '', {type: 'search', id: 'nurse-person-search', placeholder: 'Search by name', autocomplete: 'off'});
  const searchLabel = el('label', 'Find a person', {for: search.id});
  const select = el('select', '', {id: 'nurse-person'});
  const selectLabel = el('label', 'Assigned person', {for: select.id});
  const people = session.patients || [];
  const query = new URLSearchParams(location.search);
  const details = el('section', '', {class: 'nurse-readiness', 'aria-live': 'polite', 'aria-label': 'Selected person readiness'});
  const hint = el('p', '', {class: 'workspace-muted', role: 'status'});
  let sequence = 0, disposed = false, selected = '';
  window.addEventListener('pagehide', () => { disposed = true; sequence++; }, {once: true});
  function options() {
    const matches = people.filter((person) => person.name.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase()));
    select.replaceChildren(el('option', 'Select a person', {value: ''}));
    matches.forEach((person) => select.append(el('option', person.name + (person.capture_mode ? ' · Demo capture' : ''),
      {value: person.id})));
    select.value = matches.some((person) => person.id === selected) ? selected : '';
    hint.textContent = !people.length ? 'No people are assigned to this account.'
      : !matches.length ? 'No matching people. Try a different name.'
        : `${matches.length} ${matches.length === 1 ? 'person' : 'people'} available. Demo capture identities are separate from the scripted residents.`;
  }
  const linkFor = (id) => `/check?mode=live&patient=${encodeURIComponent(id)}&from=nurse`;
  async function review() {
    const id = select.value;
    selected = id;
    const request = ++sequence;
    details.replaceChildren();
    if (!id || disposed) return;
    const person = people.find((entry) => entry.id === id);
    if (!person) return;
    details.append(el('p', 'Checking permission, counting profile and available history…', {role: 'status'}));
    try {
      const [profile, consent, overview] = await Promise.all([
        api(`/v1/patients/${id}/check-profile`),
        api(`/v1/patients/${id}/consent?scope=voice_check`),
        api(`/v1/patients/${id}/overview?days=30`),
      ]);
      if (disposed || request !== sequence) return;
      details.replaceChildren();
      details.append(el('h2', person.name), el('p', person.capture_mode
        ? 'Dedicated demo capture identity. Record only this person’s own speech.'
        : 'Resident record. New checks become part of this person’s history.', {class: 'workspace-muted'}));
      if (!profile.can_configure || !profile.can_record_consent) {
        details.append(el('p', 'An assigned nurse must review this person’s recording setup.', {class: 'workspace-notice'}));
        return;
      }
      const ready = profile.state === 'ready' && consent.state === 'granted';
      const list = el('dl', '', {class: 'readiness-list'});
      function item(label, value, status) {
        const row = el('div', '', {'data-readiness': status});
        row.append(el('dt', label), el('dd', value)); list.append(row);
      }
      item('Voice permission', consent.state === 'granted' ? 'Granted — rechecked before recording'
        : consent.state === 'unknown' ? 'No decision recorded — recording is blocked'
          : `${consent.state} — recording is blocked`, consent.state === 'granted' ? 'ready' : 'blocked');
      item('Counting profile', profile.state === 'ready' ? 'English counting prompt configured'
        : profile.state === 'unsupported' ? 'Language is not supported — recording is blocked'
          : 'Details need confirmation — recording is blocked', profile.state === 'ready' ? 'ready' : 'blocked');
      const assessment = overview.latest_assessment;
      const speech = assessment?.modalities?.speech;
      const hasComparison = speech?.current === true && profile.prompt_version
        && speech.params?.prompt_version === profile.prompt_version
        && ['none', 'provisional', 'change'].includes(speech.status)
        && Object.values(speech.per_feature || {}).some((feature) =>
          feature && Number.isFinite(feature.median) && Number.isFinite(feature.scale) && Number.isFinite(feature.z));
      item('Personal comparison', hasComparison
        ? `Available in the latest assessment${Number.isInteger(speech.params.baseline_checks) ? ` · ${speech.params.baseline_checks} prior checks` : ''}`
        : 'Not established for this counting prompt in the latest assessment. A new check may still be enrolling.', hasComparison ? 'ready' : 'unknown');
      details.append(list);
      const actions = el('div', '', {class: 'workspace-actions'});
      actions.append(el('a', ready ? 'Open recorder' : 'Review recording setup', {href: linkFor(id), class: 'workspace-primary'}),
        el('a', 'View history and evidence', {href: `/resident/${encodeURIComponent(id)}`, class: 'workspace-secondary'}));
      if (person.capture_mode === 'live' && person.scripted_cohort !== true) {
        actions.append(el('a', 'Personal demo: baseline and repeat checks',
          {href: linkFor(id) + '&demo=personal', class: 'workspace-secondary'}));
      }
      details.append(el('p', ready
        ? 'The recorder checks current permission again. If there is not enough comparable history, the result will say so.'
        : 'Review the actual permission decision and profile on the next screen. Opening setup does not start the microphone or grant permission.',
        {class: 'workspace-notice'}), actions);
    } catch (error) {
      if (disposed || request !== sequence) return;
      details.replaceChildren(el('h2', person.name),
        el('p', 'Readiness could not be checked. Recording is unavailable here until the current information can be loaded.',
          {class: 'workspace-notice', role: 'alert'}));
      const retry = el('button', 'Try again', {type: 'button', class: 'workspace-secondary'});
      retry.addEventListener('click', review); details.append(retry);
    }
  }
  search.addEventListener('input', () => {
    options();
    if (selected && select.value !== selected) { selected = ''; sequence++; details.replaceChildren(); }
  });
  select.addEventListener('change', review);
  panel.append(searchLabel, search, selectLabel, select, hint, details);
  const explainer = el('aside', '', {class: 'workspace-panel nurse-explainer'});
  explainer.append(el('h2', 'What happens in a voice check?'),
    el('p', 'Ask the person to count from one to twenty and say the days of the week. Stop when they finish; the recorder stops automatically at 30 seconds.'),
    el('h3', 'What you can review'),
    el('p', 'Speaking speed, pauses and pitch are compared with the same person’s available history. Open their record to review measurements and supporting evidence.'),
    el('h3', 'Keep it comfortable'),
    el('p', 'Explain the check, confirm permission and use a quiet space. The person can decline. The resident-facing screen stays score-free.'),
    el('a', 'Open care-aide recording flow', {href: '/check?mode=resident', class: 'workspace-text-link'}),
    el('p', 'Research prototype. A recording or change flag does not establish a diagnosis.', {class: 'workspace-muted'}));
  const grid = el('div', '', {class: 'nurse-grid'}); grid.append(panel, explainer);
  page.append(heading, steps, grid); main.append(page); options();
  if (query.get('patient')) {
    if (people.some((person) => person.id === query.get('patient'))) { select.value = query.get('patient'); await review(); }
    else details.append(el('p', 'This person is not available in your assigned list.', {role: 'alert', class: 'workspace-notice'}));
  }
};
