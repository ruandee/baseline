// Session-only recorder. Reuses the normal MIME/upload helpers; no location outside a session.
// A generation counter invalidates asynchronous mic, location and stop callbacks on cancel.
function kazeCapture({getSession, getMedia, Recorder, upload, locate, onState,
                       now = () => Date.now(), later = setTimeout, cancelLater = clearTimeout}) {
  let generation = 0, recorder = null, stream = null, timer = null, busy = false;
  const open = (s) => s && s.status !== 'ended' && new Date(s.ends_at).getTime() > now();
  const release = () => { if (stream) stream.getTracks().forEach((t) => t.stop()); stream = null; };
  function cancel() {
    generation += 1;
    cancelLater(timer);
    if (recorder && recorder.state !== 'inactive') recorder.stop();
    release(); busy = false;
  }
  async function start(shareLocation) {
    if (busy) return;
    busy = true;
    const turn = ++generation;
    const current = () => turn === generation;
    let session;
    try {
      onState('Requesting microphone permission');
      session = await getSession();
      if (!current() || !open(session)) throw new Error('Session ended');
      const baseline = session.status === 'arming';
      const acquired = await getMedia();
      if (!current() || !open(session)) {
        acquired.getTracks().forEach((t) => t.stop());
        if (current()) onState('Session ended');
        if (current()) busy = false; return;
      }
      stream = acquired;
      const chunks = [];
      recorder = new Recorder(stream);
      recorder.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
      recorder.onerror = () => { cancel(); onState('Recording failed. Please try again.'); };
      recorder.onstop = async () => {
        cancelLater(timer); release();
        if (!current()) return;
        try {
          onState('Saving check-in');
          const fresh = await getSession();
          if (!current() || !open(fresh) || (fresh.status === 'arming') !== baseline) {
            throw new Error('Session ended or baseline changed; record a new clip');
          }
          const fields = {session_id: session.id, mode: 'live',
            device_id: 'kaze-phone',
            device_ts: new Date(now()).toISOString(), is_baseline: baseline ? 'true' : 'false'};
          if (shareLocation) {
            onState('Waiting for location permission');
            const position = await locate();
            if (!current() || !open(fresh)) throw new Error('Session ended');
            if (position) Object.assign(fields, {lat: position.coords.latitude,
              lon: position.coords.longitude, accuracy_m: position.coords.accuracy});
          }
          if (!current() || !open(fresh)) throw new Error('Session ended');
          const result = await upload(new Blob(chunks, {type: recorder.mimeType || 'audio/webm'}), fields);
          if (current()) onState(result.usable ? 'Check-in saved' : 'Clip not usable; please try again', result);
        } catch (error) {
          if (current()) onState(error.status === 409 ? 'Session ended' : 'Could not save. Please check the session and try again.');
        } finally { if (current()) busy = false; }
      };
      recorder.start();
      onState('Listening — tap Stop when finished');
      timer = later(() => { if (current()) stop(); }, Math.min(15000, new Date(session.ends_at).getTime() - now()));
    } catch (error) {
      release();
      if (current()) { busy = false; onState('Could not start. Check microphone permission and session end time.'); }
    }
  }
  function stop() { if (recorder && recorder.state === 'recording') recorder.stop(); }
  return {start, stop, cancel, isBusy: () => busy,
    isRecording: () => recorder && recorder.state === 'recording'};
}

if (typeof module !== 'undefined' && module.exports) module.exports = kazeCapture;
