// Explicit presentation simulation: local recording, no API, no patient history or clock changes.
(function () {
  const DAYS = [
    {verdict: 'watch', label: 'Watch', action: 'Recheck in 1 hour',
      change: 'First shifted check; repeat pending.',
      reason: 'Speech timing differs from the fictional baseline. No explaining context is supplied yet.',
      quote: null, values: ['118 words/min', '30%', '0.56 s', '196 Hz']},
    {verdict: 'explained', label: 'Explained', action: 'No action',
      change: 'Repeated speech timing change with explaining context.',
      reason: 'The fictional record documents new dentures, providing an explanation for the change.',
      quote: 'New dentures fitted yesterday; speech sounds different while getting used to them.',
      values: ['119 words/min', '31%', '0.57 s', '195 Hz']},
    {verdict: 'escalate', label: 'Escalate', action: 'Run 4AT now',
      change: 'Speech timing change with amplifying context.',
      reason: 'New high-risk medication and poor intake outweigh the earlier explaining context.',
      quote: 'New oxybutynin order documented. Quiet at lunch and did not finish the meal.',
      values: ['116 words/min', '32%', '0.59 s', '196 Hz']},
  ];
  const FEATURES = ['Speech rate', 'Pause ratio', 'Mean pause', 'Pitch'];
  const BASELINE = ['145 words/min', '20%', '0.40 s', '195 Hz'];

  window.renderDemoDays = function (main, h) {
    let day = 0;
    let epoch = 0;
    let stream = null;
    let recorder = null;
    let limit = null;
    let clipUrl = null;
    let receipt = null;
    const completed = new Set();
    const title = h.el('h1', 'Three-day voice demo');
    const banner = h.el('section', '', {class: 'bl-demo-banner'});
    banner.append(h.el('strong', 'SIMULATED DEMO RESULTS'), h.el('p',
      'Record a real clip, then explore a fictional resident over three simulated days. '
      + 'Results and measurements are scripted; they are not computed from your voice.'));
    const timeline = h.el('ol', '', {class: 'bl-demo-timeline', 'aria-label': 'Simulated days'});
    const heading = h.el('h2', '', {tabindex: '-1', class: 'bl-demo-day'});
    const prompt = h.el('p', CHECK_PROMPT, {class: 'bl-prompt'});
    const record = h.el('button', 'Record live', {type: 'button', class: 'bl-action bl-demo-record'});
    const uploadLabel = h.el('label', 'Or load a prerecorded clip (up to 30 seconds)', {class: 'bl-demo-file-label'});
    const file = h.el('input', '', {type: 'file', accept: 'audio/*,.wav,.webm,.mp4,.m4a', class: 'bl-demo-file'});
    uploadLabel.append(file);
    const status = h.el('p', '', {role: 'status', class: 'bl-demo-status'});
    const preview = h.el('section', '', {class: 'bl-demo-preview'});
    const result = h.el('section', '', {class: 'bl-demo-result'});
    const next = h.el('button', 'Next simulated day', {type: 'button', class: 'bl-action bl-demo-next'});
    const reset = h.el('button', 'Restart scenario', {type: 'button', class: 'bl-demo-reset'});
    const controls = h.el('div', '', {class: 'bl-demo-controls'});
    controls.append(next, reset);
    const capture = h.el('section', '', {class: 'bl-card bl-demo-capture'});
    capture.append(heading, prompt, record, uploadLabel, status, preview);
    main.replaceChildren(title, banner, timeline, capture, result, controls,
      h.el('p', 'Audio stays in this tab. No upload, ASR, real baseline comparison, alerts or clinical '
        + 'history writes occur in this mode. Restarting or leaving clears the recording.', {class: 'bl-muted'}));

    function release() {
      epoch += 1;
      clearTimeout(limit);
      if (recorder && recorder.state === 'recording') recorder.stop();
      if (stream) stream.getTracks().forEach((track) => track.stop());
      stream = recorder = null;
      const audio = preview.querySelector('audio');
      if (audio) {
        if (typeof audio.pause === 'function') audio.pause();
        audio.removeAttribute('src');
        if (typeof audio.load === 'function') audio.load();
      }
      preview.replaceChildren();
      if (clipUrl) URL.revokeObjectURL(clipUrl);
      clipUrl = null;
      receipt = null;
    }

    function render() {
      heading.textContent = `Simulated day ${day + 1} of 3 — fictional resident`;
      timeline.replaceChildren(...DAYS.map((scenario, index) => h.el('li',
        `Day ${index + 1}: ${scenario.label}${completed.has(index) ? ' · shown' : ''}`,
        {'aria-current': index === day ? 'step' : 'false'})));
      preview.replaceChildren();
      result.replaceChildren();
      result.removeAttribute('data-verdict');
      status.textContent = 'Tap Record or load a clip. Stop when finished; auto-stop is 30 seconds.';
      record.textContent = 'Record live';
      record.disabled = file.disabled = false;
      file.value = '';
      next.disabled = true;
      next.textContent = day === 2 ? 'Scenario complete' : 'Next simulated day';
    }

    function showScenario() {
      const scenario = DAYS[day];
      result.replaceChildren(h.el('h2', 'Simulated demo result'),
        h.chip(scenario.label, scenario.verdict),
        h.el('p', 'Scripted scenario — not an assessment of the person in the recording.', {class: 'bl-demo-disclosure'}),
        h.el('p', scenario.change), h.el('p', scenario.reason),
        h.el('p', `Simulated suggested action: ${scenario.action}. No action is performed.`));
      const table = h.el('table', '', {class: 'bl-table'});
      const header = h.el('tr', '');
      ['Illustrative feature', 'Authored baseline', `Authored day ${day + 1}`].forEach((name) => header.append(h.el('th', name, {scope: 'col'})));
      table.append(header);
      FEATURES.forEach((name, index) => {
        const row = h.el('tr', '');
        [name, BASELINE[index], scenario.values[index]].forEach((value) => row.append(h.el('td', value)));
        table.append(row);
      });
      result.append(table);
      if (scenario.quote) {
        const source = h.el('details', '', {class: 'bl-demo-source'});
        source.append(h.el('summary', 'View fictional scenario note'), h.el('blockquote', scenario.quote),
          h.el('p', 'Authored demo text; no real source record or evidence API is used.', {class: 'bl-muted'}));
        result.append(source);
      }
      completed.add(day);
      timeline.children[day].textContent = `Day ${day + 1}: ${scenario.label} · shown`;
      next.disabled = day === 2;
      result.dataset.verdict = scenario.verdict;
    }

    function showClip(blob, label, recordedAt, duration) {
      if (!blob.size) {
        status.textContent = 'The clip is empty. Record again or load a different file.';
        record.disabled = file.disabled = false;
        return;
      }
      const token = epoch;
      clipUrl = URL.createObjectURL(blob);
      const audio = h.el('audio', '', {controls: '', preload: 'metadata', src: clipUrl});
      const receiptText = h.el('p', '', {class: 'bl-demo-receipt'});
      preview.replaceChildren(audio, receiptText);
      function accept(seconds) {
        if (token !== epoch) return;
        receipt = {day, source: label, recordedAt};
        receiptText.textContent = `${label} · ${seconds.toFixed(1)} s · `
          + (recordedAt ? `recorded ${new Date(recordedAt).toLocaleTimeString()}` : 'original recording time unknown');
        status.textContent = 'Clip ready locally. The result below is simulated; this audio was not analyzed or uploaded.';
        record.disabled = file.disabled = false;
        showScenario();
      }
      audio.addEventListener('error', () => {
        if (token !== epoch) return;
        release(); preview.replaceChildren(); result.replaceChildren(); next.disabled = true;
        result.removeAttribute('data-verdict');
        status.textContent = 'Could not play this clip. Please choose a supported audio file.';
      });
      if (duration !== undefined) accept(duration);
      else audio.addEventListener('loadedmetadata', () => {
        if (token !== epoch) return;
        if (!Number.isFinite(audio.duration) || audio.duration <= 0 || audio.duration > h.maxSeconds) {
          release(); preview.replaceChildren(); result.replaceChildren(); next.disabled = true;
          status.textContent = 'Choose a playable clip no longer than 30 seconds (WAV or MP4 if duration is unavailable).';
          record.disabled = file.disabled = false;
          return;
        }
        accept(audio.duration);
      });
    }

    record.addEventListener('click', async () => {
      if (recorder && recorder.state === 'recording') { recorder.stop(); return; }
      release(); render();
      const token = epoch;
      record.disabled = file.disabled = true;
      status.textContent = 'Waiting for microphone permission…';
      try {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || typeof MediaRecorder === 'undefined') {
          throw new Error('unavailable');
        }
        const media = await navigator.mediaDevices.getUserMedia({audio: true});
        if (token !== epoch) { media.getTracks().forEach((track) => track.stop()); return; }
        stream = media;
        const mime = pickMimeType();
        if (mime === null) throw new Error('unsupported');
        const ownRecorder = recorder = new MediaRecorder(stream, mime ? {mimeType: mime} : undefined);
        const chunks = [];
        const started = Date.now();
        const recordedAt = new Date(started).toISOString();
        ownRecorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
        ownRecorder.onstop = () => {
          media.getTracks().forEach((track) => track.stop());
          if (token !== epoch) return;
          clearTimeout(limit); // Only the admitted capture owns the current auto-stop timer.
          stream = recorder = null;
          record.textContent = 'Record live';
          showClip(new Blob(chunks, {type: ownRecorder.mimeType || mime || 'audio/webm'}),
            'Captured live in this browser', recordedAt, Math.max(0, (Date.now() - started) / 1000));
        };
        ownRecorder.onerror = () => {
          if (token !== epoch) return;
          release(); render(); status.textContent = 'Recording failed. Please try again or load a clip.';
        };
        ownRecorder.start(); record.disabled = false; record.textContent = 'Stop recording';
        status.textContent = 'Recording locally — tap Stop when finished (up to 30 seconds).';
        limit = setTimeout(() => { if (token === epoch && ownRecorder.state === 'recording') ownRecorder.stop(); }, h.maxSeconds * 1000);
      } catch (error) {
        if (token !== epoch) return;
        release(); render();
        status.textContent = 'Could not start recording. Check microphone permission and use HTTPS or localhost, or load a clip.';
      }
    });
    file.addEventListener('change', () => {
      const clip = file.files && file.files[0];
      if (!clip) return;
      release(); render();
      if (clip.size > 20 * 1024 * 1024 || !(String(clip.type).startsWith('audio/')
          || /\.(wav|webm|mp4|m4a)$/i.test(clip.name))) {
        status.textContent = 'Choose an audio file smaller than 20 MB.'; return;
      }
      status.textContent = 'Checking local clip…';
      showClip(clip, `Loaded prerecorded clip: ${clip.name}`, null);
    });
    next.addEventListener('click', () => {
      if (!receipt || day >= 2) return;
      release(); day += 1; render(); heading.focus();
    });
    reset.addEventListener('click', () => { release(); day = 0; completed.clear(); render(); heading.focus(); });
    window.addEventListener('pagehide', () => { release(); day = 0; completed.clear(); render(); });
    render();
  };
})();
