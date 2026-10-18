// Cross-device fictional demo. Only a receipt leaves the phone; outcomes are authored.
(function () {
  window.renderHandoff = async function (main, h) {
    const query = new URLSearchParams(location.search);
    const fragment = new URLSearchParams(location.hash.slice(1));
    const role = query.get('resident');
    const nurse = !role;
    main.setAttribute('data-workspace', 'demo');
    main.setAttribute('data-demo-role', nurse ? 'nurse' : 'phone');
    let room = fragment.get('room'), key = fragment.get('key');
    let stopped = false, timer = null, generation = 0, stream = null, recorder = null;
    let clipUrl = null, clip = null, sending = false;
    const title = h.el('h1', nurse ? 'Resident check-ins' : 'Your voice check');
    const info = h.el('details', '', {class: 'bl-handoff-info'});
    info.append(h.el('summary', 'Demo scenario'), h.el('p',
      'Live recording with supplied fictional baselines and authored findings. Audio stays on '
      + 'the recording device; only check-in receipts are shared. No voice analysis, clinical '
      + 'history writes or external alerts. Rooms expire after two hours or a server restart.'));
    const status = h.el('p', '', {role: 'status', 'aria-live': 'polite'});
    const content = h.el('div', '', {class: 'bl-handoff-content'});
    const disclosure = h.el('p', 'LIVE DEMO \u00b7 FICTIONAL FINDINGS', {class: 'demo-disclosure'});
    const introduction = h.el('p', nurse
      ? 'Connect the two phones, follow incoming check-ins, then review the supplied context.'
      : 'Take your time. Your recording stays on this phone; submitting shares a check-in receipt.',
      {class: 'demo-introduction'});
    main.replaceChildren(disclosure, title, introduction, info, status, content);
    async function request(path = '', method = 'GET', body) {
      // A dropped network rejects fetch; show the same retry message as a failed response.
      const response = await fetch('/demo/handoff' + (room ? '/' + room : '') + path, {
        method, headers: {Authorization: 'Bearer ' + key,
          ...(body === undefined ? {} : {'Content-Type': 'application/json'})},
        ...(body === undefined ? {} : {body: JSON.stringify(body)})}).catch(() => ({ok: false, status: 0}));
      if (!response.ok) {
        const error = new Error(response.status === 404
        ? 'This demo link expired or is invalid. Ask the nurse for a new link.'
        : response.status === 409 ? 'This scenario step is complete or out of order. Check the nurse screen.'
        : 'Connection failed. Try again; the same check-in will not be duplicated.');
        error.status = response.status;
        throw error;
      }
      return response.json();
    }
    // The "same check-in will not be duplicated" text is for the phone; a dropped network on the
    // nurse screen (status 0) gets its own wording.
    const nurseMessage = (error, offline) => error.status === 0 ? offline : error.message;
    function release() {
      generation++;
      clearTimeout(timer);
      if (recorder && recorder.state === 'recording') recorder.stop();
      if (stream) stream.getTracks().forEach(t => t.stop());
      stream = recorder = null;
      const audio = content.querySelector('audio');
      if (audio) { audio.pause(); audio.removeAttribute('src'); audio.load(); }
      if (clipUrl) URL.revokeObjectURL(clipUrl);
      clipUrl = clip = null;
    }
    window.addEventListener('pagehide', () => { stopped = true; release(); });
    const name = r => r === 'runner' ? 'Resident A · runner' : 'Resident B · Dee';
    function captureLink(r, value) {
      return location.origin + '/check?demo=handoff&resident=' + r
        + '#room=' + encodeURIComponent(room) + '&key=' + encodeURIComponent(value);
    }
    if (nurse) {
      try {
        if (!room || !key) {
          await h.bootstrap();
          const created = await h.api('/demo/handoff', {method: 'POST',
            headers: {'Content-Type': 'application/json'}, body: '{}'});
          if (stopped) return;
          room = created.room; key = created.keys.nurse;
          history.replaceState(null, '', '/unit?demo=handoff#room=' + room + '&key=' + key);
        }
        const links = h.el('details', '', {class: 'bl-card bl-handoff-links', open: ''});
        links.append(h.el('summary', 'Phone recording links'), h.el('p',
          'Share only the resident links below. Keep this nurse URL private.'));
        const cards = h.el('section', '', {'aria-label': 'Incoming resident check-ins'});
        const reset = h.el('button', 'Start a new rehearsal', {type: 'button'});
        reset.addEventListener('click', async () => {
          reset.disabled = true;
          try { await request('', 'DELETE'); location.replace('/unit?demo=handoff'); }
          catch (error) { status.textContent = nurseMessage(error, 'Connection failed. Try again.'); reset.disabled = false; }
        });
        content.append(links, cards, reset);
        let revision = -1;
        function draw(data) {
          if (revision === data.revision) return;
          revision = data.revision;
          if (data.checks.length) links.open = false;
          if (!links.querySelector('input')) {
            for (const r of ['runner', 'resident']) {
              const row = h.el('label', name(r));
              const input = h.el('input', '', {type: 'text', readonly: '',
                value: captureLink(r, data.capture_keys[r]), 'aria-label': name(r) + ' capture link'});
              const copy = h.el('button', 'Copy link', {type: 'button'});
              copy.addEventListener('click', async () => {
                try { await navigator.clipboard.writeText(input.value); copy.textContent = 'Copied'; }
                catch (_) { input.focus(); input.select(); status.textContent = 'Select and copy the resident link.'; }
              });
              row.append(input, copy); links.append(row);
            }
          }
          cards.replaceChildren();
          for (const r of ['runner', 'resident']) {
            const checks = data.checks.filter(c => c.resident === r);
            const latest = checks[checks.length - 1];
            const card = h.el('article', '', {class: 'bl-card', 'data-resident': r});
            card.append(h.el('h2', name(r)));
            if (!latest) { card.append(h.el('p', 'Waiting for a check-in from the phone…')); cards.append(card); continue; }
            card.append(h.chip(h.VERDICT_LABELS[latest.verdict], latest.verdict), h.el('p',
              `Check ${latest.take} received at ${new Date(latest.received_at).toLocaleTimeString()}`));
            const reasons = latest.verdict === 'explained' ? 'Recent exertion was supplied as context by the nurse.'
              : latest.verdict === 'escalate' ? 'Repeated change in speech timing with no supplied explanation.'
              : 'First change in speech timing. Review context and repeat the check.';
            card.append(h.el('p', reasons));
            const evidence = h.el('details');
            evidence.append(h.el('summary', 'Review baseline and finding'), h.el('p',
              'Supplied baseline: 145 words/min, 20% pause ratio, 0.40 s mean pause. '
              + (latest.verdict === 'escalate' ? 'Repeated finding: slower speech and longer/more pauses; '
                + 'two matching changes within 24 hours; scenario combined score 3.2.'
                : 'Finding: slower speech and longer/more pauses; repeat confirmation pending.')));
            card.append(evidence);
            if (r === 'runner' && !data.exertion) {
              const context = h.el('details');
              context.append(h.el('summary', 'Add context / possible explanation'));
              const label = h.el('label', 'Possible explanation');
              const select = h.el('select', '', {'aria-label': 'Possible explanation'});
              select.append(h.el('option', 'Recent exertion / just finished running', {value: 'exertion'}));
              label.append(select);
              const apply = h.el('button', 'Apply context and reassess', {type: 'button'});
              apply.addEventListener('click', async () => {
                apply.disabled = true;
                try { draw(await request('/context', 'POST', {tag: select.value})); status.textContent = 'Context added. Runner check-in is Explained.'; }
                catch (error) { status.textContent = nurseMessage(error, 'Connection failed. Try again.'); apply.disabled = false; }
              });
              context.append(label, apply); card.append(context);
            }
            if (latest.verdict === 'watch') card.append(h.el('p', 'Suggested: Recheck in 1 hour'));
            if (latest.verdict === 'explained') card.append(h.el('p', 'No escalation suggested for this scenario.'));
            if (latest.verdict === 'escalate') {
              const action = h.el('details', '', {class: 'bl-handoff-action'});
              action.append(h.el('summary', 'Run 4AT now'), h.el('h3', 'Review the proposed action and handoff'),
                h.el('p', 'Suggested: Run 4AT now. Review the repeated voice finding and available '
                  + 'context, then use your facility’s assessment workflow.'),
                h.el('h3', 'Handoff draft'), h.el('p', 'Resident B has repeated changes in speech timing '
                  + 'relative to the supplied baseline. No explaining context is recorded. '
                  + 'Review and assess using the facility workflow. This control sends no alert.'));
              card.append(action);
            }
            cards.append(card);
          }
        }
        async function poll() {
          try { const data = await request(); if (!stopped) { draw(data); status.textContent = 'Connected · checking for new submissions every 2 seconds'; } }
          catch (error) {
            if (!stopped) status.textContent = nurseMessage(error, 'Reconnecting…');
            if (error.status === 404) {
              cards.replaceChildren(); links.replaceChildren(); reset.disabled = true;
              content.append(h.el('a', 'Start a new demo room', {href: '/unit?demo=handoff'}));
              return;
            }
          }
          if (!stopped) timer = setTimeout(poll, 2000);
        }
        await poll();
      } catch (error) { status.textContent = error.message; }
      return;
    }
    if (!['runner', 'resident'].includes(role) || !room || !key) {
      status.textContent = 'Open the resident-specific link supplied by the nurse.'; return;
    }
    const record = h.el('button', 'Start recording', {type: 'button', class: 'bl-action bl-handoff-record'});
    const submit = h.el('button', 'Submit check-in', {type: 'button', disabled: '', class: 'bl-action bl-handoff-submit'});
    const preview = h.el('section');
    content.append(h.el('h2', name(role)), h.el('p', CHECK_PROMPT), h.el('p',
      'Tap Start, read the prompt, then Stop. Listen back before submitting. Up to 30 seconds.'),
      record, preview, submit);
    record.addEventListener('click', async () => {
      if (sending) return;
      if (recorder && recorder.state === 'recording') { recorder.stop(); return; }
      release(); preview.replaceChildren(); submit.disabled = record.disabled = true;
      const token = generation;
      status.textContent = 'Waiting for microphone permission…';
      try {
        const media = await navigator.mediaDevices.getUserMedia({audio: true});
        if (stopped || token !== generation) { media.getTracks().forEach(t => t.stop()); return; }
        stream = media;
        const mime = pickMimeType();
        if (mime === null) throw new Error('No supported recorder');
        const own = recorder = new MediaRecorder(media, mime ? {mimeType: mime} : undefined);
        const chunks = [], started = Date.now();
        own.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
        own.onstop = () => {
          media.getTracks().forEach(t => t.stop());
          if (stopped || token !== generation) return;
          clearTimeout(timer); stream = recorder = null;
          record.disabled = false; record.textContent = 'Record again';
          const audio = new Blob(chunks, {type: own.mimeType || mime || 'audio/webm'});
          if (!audio.size) { status.textContent = 'Empty recording. Please try again.'; return; }
          clipUrl = URL.createObjectURL(audio);
          clip = {request_id: crypto.randomUUID(), duration_s: Math.min(30, Math.max(.001, (Date.now() - started) / 1000))};
          const player = h.el('audio', '', {controls: '', src: clipUrl});
          player.addEventListener('error', () => {
            if (token !== generation) return;
            release(); submit.disabled = true; preview.replaceChildren();
            status.textContent = 'Could not play this recording. Please record again.';
          });
          preview.replaceChildren(player); submit.disabled = false;
          status.textContent = 'Recording ready. Audio stays on this phone; Submit sends the nurse a check-in receipt.';
        };
        own.onerror = () => {
          if (token !== generation) return;
          release(); record.disabled = false; record.textContent = 'Start recording';
          status.textContent = 'Recording failed. Please try again.';
        };
        own.start(); record.disabled = false; record.textContent = 'Stop recording';
        status.textContent = 'Recording…';
        timer = setTimeout(() => { if (token === generation && own.state === 'recording') own.stop(); }, 30000);
      } catch (_) {
        if (stopped || token !== generation) return;
        release(); record.disabled = false; record.textContent = 'Start recording';
        status.textContent = 'Could not record. Use HTTPS, allow microphone access, and try again.';
      }
    });
    submit.addEventListener('click', async () => {
      if (!clip || sending) return;
      sending = true; submit.disabled = record.disabled = true;
      status.textContent = 'Sending check-in…';
      try {
        const receipt = await request('/checks', 'POST', clip);
        if (!stopped) {
          release(); preview.replaceChildren(); record.disabled = receipt.remaining_checks === 0;
          record.textContent = record.disabled ? 'Check-ins complete' : 'Record next check';
          status.textContent = 'Check-in received by the nurse. Thank you.';
        }
      } catch (error) {
        if (!stopped) { status.textContent = error.message; submit.disabled = !clip; record.disabled = false; }
      } finally { sending = false; }
    });
  };
})();
