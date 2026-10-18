// KAZE pages (BL-28): pure logic shared by /out and /out/session/:sid, with no DOM or network.
// Field names follow decision 018 (docs/decisions/018-kaze-session-model.md). Loaded as a classic
// script in the browser (global KazeCore) and with require() by tests/js/kaze_pages.test.js.
// Wording rules: neutral, never diagnostic, and never a coordinate on screen.
const KazeCore = (() => {
  const E164 = /^\+[1-9][0-9]{7,14}$/;
  const CONTEXT_TAGS = ['exertion', 'loud_venue'];
  const OPEN = ['arming', 'active', 'escalating', 'acknowledged'];
  const MAX_SPAN_MS = 24 * 3600 * 1000;
  const SLACK_MS = 60 * 1000;  // the server checks the window on its own clock, a moment later

  const CHANGE_TEXT = {
    none: 'Similar to tonight\'s baseline',
    provisional: 'Possibly different from tonight\'s baseline',
    change: 'Different from tonight\'s baseline',
    enrolling: 'Baseline still building'};
  const TRIGGER_TEXT = {
    missed_checkin: 'Check-in missed',
    speech_change: 'Speech differed from tonight\'s baseline'};
  const DELIVERY_TEXT = {
    pending: 'Sending',
    logged: 'Logged by the demo sender; no SMS was sent',
    sent: 'Accepted by SMS provider; delivery unconfirmed',
    failed: 'Could not be sent'};
  const CONTEXT_TEXT = {exertion: 'exertion', loud_venue: 'loud venue'};

  function normalizePhone(raw) {
    return String(raw || '').replace(/[\s().-]/g, '');
  }

  // Next local occurrence of "HH:MM" strictly after now.
  function endFromClock(hhmm, now) {
    const m = /^(\d{1,2}):(\d{2})$/.exec(String(hhmm || '').trim());
    if (!m || Number(m[1]) > 23 || Number(m[2]) > 59) return null;
    const end = new Date(now.getTime());
    end.setHours(Number(m[1]), Number(m[2]), 0, 0);
    if (end.getTime() <= now.getTime()) end.setDate(end.getDate() + 1);
    return end;
  }

  // Mirrors SessionArm and window_error() so most mistakes are caught before the request.
  function validateArm(input, now) {
    const errors = [];
    const displayName = String(input.displayName || '').trim();
    if (!displayName || displayName.length > 40) errors.push('Enter your first name (up to 40 characters).');
    const interval = Number(input.intervalMin);
    if (!Number.isInteger(interval) || interval < 1 || interval > 180) {
      errors.push('Check-in interval must be a whole number of minutes from 1 to 180.');
    }
    const contacts = [];
    (input.contacts || []).forEach((c, i) => {
      const name = String(c.name || '').trim();
      const phone = normalizePhone(c.phone);
      if (!name && !phone) return;
      const label = `Contact ${i + 1}`;
      if (!name || name.length > 40) errors.push(`${label}: enter a name (up to 40 characters).`);
      if (!E164.test(phone)) errors.push(`${label}: enter the phone number with its country code, e.g. +1 555 010 0100.`);
      contacts.push({name, phone_e164: phone});
    });
    if (contacts.length === 0) errors.push('Add at least one trusted contact.');
    if (contacts.length > 2) errors.push('Add at most two contacts.');
    if (new Set(contacts.map((c) => c.phone_e164)).size !== contacts.length) {
      errors.push('The two contacts need different phone numbers.');
    }
    const end = endFromClock(input.endClock, now);
    if (!end) {
      errors.push('Choose the time you expect to be back.');
    } else if (Number.isInteger(interval)) {
      if (end.getTime() < now.getTime() + interval * 60000 + SLACK_MS) {
        errors.push('The end time must be at least one check-in interval from now.');
      }
      if (end.getTime() > now.getTime() + MAX_SPAN_MS - SLACK_MS) {
        errors.push('A session can last at most 24 hours.');
      }
    }
    const tags = (input.contextTags || []).filter((t) => CONTEXT_TAGS.includes(t));
    if (errors.length) return {errors};
    return {body: {display_name: displayName, ends_at: end.toISOString(), interval_min: interval,
                   contacts, context_tags: [...new Set(tags)],
                   escalation_enabled: input.escalationEnabled !== false}};
  }

  function openSession(sessions) {
    return (sessions || []).find((s) => OPEN.includes(s.status)) || null;
  }

  function clock(totalSeconds) {
    const s = Math.max(0, Math.floor(totalSeconds));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = String(s % 60).padStart(2, '0');
    return h ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`;
  }

  function duration(totalSeconds) {
    const s = Math.max(0, Math.round(totalSeconds));
    if (s < 60) return `${s} s`;
    const m = Math.floor(s / 60);
    if (m < 60) return s % 60 ? `${m} min ${s % 60} s` : `${m} min`;
    return `${Math.floor(m / 60)} h ${m % 60} min`;
  }

  // Level 0 of the ladder is client side: count down to next_due_at and buzz when it passes.
  function countdown(nextDueAt, now) {
    if (!nextDueAt) return null;
    const ms = new Date(nextDueAt).getTime() - now.getTime();
    if (Number.isNaN(ms)) return null;
    return ms > 0
      ? {overdue: false, seconds: Math.ceil(ms / 1000), label: `Next check-in in ${clock(Math.ceil(ms / 1000))}`}
      : {overdue: true, seconds: Math.floor(-ms / 1000), label: `Check-in due ${clock(Math.floor(-ms / 1000))} ago`};
  }

  function contactName(session, index) {
    const found = (session.contacts || []).find((c) => c.contact_index === index);
    return found ? found.name : `Contact ${index}`;
  }

  function episodeTexts(session, episode) {
    return (session.escalations || []).filter((e) => e.channel === 'sms' && e.episode === episode);
  }

  // What the person sees on their own phone. Driven only by server fields; the client never
  // advances the ladder itself (BL-26 does).
  function personView(session) {
    const s = session;
    const textsOff = s.escalation_enabled === false
      ? ' Texts are off for this session: you get reminders only.' : '';
    if (s.status === 'arming') {
      const b = s.baseline || {usable: 0, required: 3};
      return {screen: 'arming', tone: 'pending', headline: 'Record tonight\'s baseline',
              detail: `${b.usable} of ${b.required} usable clips recorded. The timer starts after the last one.`};
    }
    if (s.status === 'ended') {
      return {screen: 'ended', tone: 'pending', headline: 'Session ended',
              detail: 'Your check-ins and any locations from this session are deleted 24 hours after it ended.'};
    }
    if (s.status === 'acknowledged') {
      const acked = episodeTexts(s, s.episode).find((e) => e.ack_at);
      const who = acked ? contactName(s, acked.contact_index) : 'A contact';
      return {screen: 'status', tone: 'ok', headline: `${who} is on it`,
              detail: `${who} opened the acknowledgement link. Check in to let everyone know you are OK.`};
    }
    if (s.status === 'escalating') {
      const texts = episodeTexts(s, s.episode);
      const names = [...new Set(texts.map((e) => contactName(s, e.contact_index)))];
      return {screen: 'status', tone: 'alert', headline: texts.some((e) => e.delivery === 'sent') ? 'SMS provider accepted text' : 'Contact escalation recorded',
              detail: (names.length ? `Contacts: ${names.join(', ')}. ` : '') +
                      'Check in now. A logged demo event is not a delivered SMS.'};
    }
    if (s.ladder_level >= 1) {
      return {screen: 'status', tone: 'watch', headline: 'Time to check in',
              detail: 'A reminder was recorded.' + (s.escalation_enabled === false ? textsOff
                : ' If you do not check in, contact escalation will be attempted.')};
    }
    return {screen: 'status', tone: 'ok', headline: 'Session active',
            detail: `Check in every ${s.interval_min} min until ${timeOfDay(s.ends_at)}.` + textsOff};
  }

  function timeOfDay(iso) {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '—' : d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
  }

  // Message text as stored by BL-27, with any link or coordinate pair removed before display.
  function redactMessage(text) {
    if (!text) return '';
    return String(text)
      .replace(/\bhttps?:\/\/\S+/gi, '[link]')
      .replace(/\bgeo:\S+/gi, '[location]')
      .replace(/-?\d{1,3}(?:\.\d+)?\s*,\s*-?\d{1,3}(?:\.\d+)?/g, '[location]');
  }

  // Time from the first SMS escalation attempt, including logged or failed attempts.
  // Provider acceptance is not delivery; this clock must never imply a text was received.
  function timeToAck(session) {
    const episodes = [...new Set((session.escalations || []).map((e) => e.episode))].sort((a, b) => a - b);
    return episodes.map((episode) => {
      const texts = episodeTexts(session, episode);
      if (!texts.length) return null;
      const first = Math.min(...texts.map((e) => new Date(e.sent_at).getTime()));
      const acks = (session.escalations || []).filter((e) => e.episode === episode && e.ack_at)
        .map((e) => ({at: new Date(e.ack_at).getTime(), by: contactName(session, e.contact_index)}))
        .sort((a, b) => a.at - b.at);
      return acks.length
        ? {episode, firstTextAt: new Date(first).toISOString(), ackAt: new Date(acks[0].at).toISOString(),
           by: acks[0].by, seconds: (acks[0].at - first) / 1000}
        : {episode, firstTextAt: new Date(first).toISOString(), ackAt: null, by: null, seconds: null};
    }).filter(Boolean);
  }

  const ORDER = {armed: 0, baseline: 1, active: 2, checkin: 3, nudge: 4, text: 5, ack: 6, ended: 7};

  // Judge-facing timeline: checks, triggers, texts, acknowledgements and the end, oldest first.
  function timeline(session) {
    const s = session;
    const events = [];
    const tags = (s.context_tags || []).map((t) => CONTEXT_TEXT[t] || t);
    events.push({ts: s.created_at, kind: 'armed', label: 'Session armed',
                 detail: `Check-ins every ${s.interval_min} min until ${timeOfDay(s.ends_at)}; ` +
                         `texts ${s.escalation_enabled === false ? 'off' : 'on'}` +
                         (tags.length ? `; context: ${tags.join(', ')}` : '')});
    let baselineN = 0;
    (s.checks || []).forEach((c) => {
      const where = c.has_location ? 'location attached' : 'no location';
      if (c.is_baseline) {
        if (c.usable) baselineN += 1;
        events.push({ts: c.ts, kind: 'baseline',
                     label: c.usable ? `Baseline clip ${baselineN}` : 'Baseline clip not usable',
                     detail: c.usable ? where : 'Did not count towards the baseline'});
      } else {
        events.push({ts: c.ts, kind: 'checkin', label: c.usable ? 'Check-in' : 'Check-in not usable',
                     detail: c.usable
                       ? `${CHANGE_TEXT[c.change_status] || 'No comparison available'}; ${where}`
                       : 'Did not count as a check-in'});
      }
    });
    if (s.activated_at) {
      events.push({ts: s.activated_at, kind: 'active', label: 'Session active',
                   detail: 'Baseline complete; check-in timer started'});
    }
    const firstText = {};
    (s.escalations || []).forEach((e) => {
      const trigger = TRIGGER_TEXT[e.trigger] || e.trigger;
      if (e.channel === 'nudge') {
        events.push({ts: e.sent_at, kind: 'nudge', label: `Reminder (level ${e.level})`, detail: trigger});
        return;
      }
      const who = contactName(s, e.contact_index);
      const t = new Date(e.sent_at).getTime();
      if (!(e.episode in firstText) || t < firstText[e.episode]) firstText[e.episode] = t;
      events.push({ts: e.sent_at, kind: 'text', label: `Contact escalation for ${who} (level ${e.level})`,
                   detail: `${trigger}. ${DELIVERY_TEXT[e.delivery] || e.delivery}.`,
                   message: redactMessage(e.message)});
    });
    (s.escalations || []).filter((e) => e.ack_at).forEach((e) => {
      const who = contactName(s, e.contact_index);
      const since = e.episode in firstText
        ? `${duration((new Date(e.ack_at).getTime() - firstText[e.episode]) / 1000)} after the first contact escalation attempt`
        : '';
      events.push({ts: e.ack_at, kind: 'ack', label: `${who} acknowledged`,
                   detail: since + (e.episode === s.episode ? '' : (since ? '; ' : '') + 'earlier episode')});
    });
    if (s.ended_at) {
      events.push({ts: s.ended_at, kind: 'ended', label: 'Session ended',
                   detail: (s.end_reason === 'expired' ? 'Reached its end time' : 'Ended by the person') +
                           (s.delete_after ? `; data deleted after ${timeOfDay(s.delete_after)}` : '')});
    }
    return events
      .map((e, i) => ({...e, i, t: new Date(e.ts).getTime()}))
      .sort((a, b) => a.t - b.t || ORDER[a.kind] - ORDER[b.kind] || a.i - b.i)
      .map(({i, t, ...e}) => e);
  }

  return {normalizePhone, endFromClock, validateArm, openSession, clock,
          duration, countdown, personView, redactMessage, timeToAck, timeline, timeOfDay,
          CHANGE_TEXT, TRIGGER_TEXT, DELIVERY_TEXT};
})();

if (typeof module !== 'undefined' && module.exports) module.exports = KazeCore;
