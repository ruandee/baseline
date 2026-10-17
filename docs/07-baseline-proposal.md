# Baseline: project proposal and plan

Oct 17, 2026 · @Danny Hu

## The idea

Baseline turns a 10-second conversation into a vital sign: it measures how a long-term care resident speaks, compares it with that resident's own normal, and when something shifts it tells the nurse why it matters, or stays quiet because the record already explains it.

**The problem.** In older adults, an infection often shows up first as confusion, not fever. That confusion (delirium) is easy to miss: in one study of residents with dementia, nurses recognised about 13% of delirium cases. Care aides usually notice that someone "seems off" days before anything reaches the chart, but "seems off" isn't something a system can track. On Ontario night shifts one nurse can cover 80 residents, and agency staff don't know what anyone's normal looks like.

**What Baseline does.**

1. During a routine moment, a care aide asks the resident to count to 20 and say the days of the week. It takes 10 seconds.
2. Baseline measures how they spoke: how fast, how many pauses, how long the pauses were, and their pitch.
3. It compares those numbers with the same resident's history, not with a population average.
4. If there's a real change, it checks the resident's record for context: a new medication, a note saying she was "quiet at lunch", a documented temperature, or something harmless like new dentures.
5. The nurse sees a short list: who changed, why it might matter, the evidence behind each point, and a suggested standard check (such as a 4AT delirium screen). Harmless changes are logged without paging anyone.

**Why it fits the PointClickCare challenge.** The prompt names "a confused moment" as an early warning sign, asks for an interface the care team can use, some form of AI, a real health scenario, and a bonus for explaining *why* something is flagged. Baseline is built around that last point: every flag comes with its evidence.

**Prizes we're entering.** PointClickCare Catch It Early (primary), Project KAZE (through the extension below), Best Healthcare & Well-being, AI for Social Impact, MLH Best Use of Gemini API, MLH Best Use of Tiger Data, and the overall Top 3.

## How it fits a real shift

Baseline only asks for checks when risk is higher, so a unit of 80 residents needs about 10 to 20 ten-second checks per shift, not 160.

- **Watch windows.** A 7-day window opens automatically when something in the record raises delirium risk: a new or changed high-risk medication, a fall, or a return from hospital. During the window, the resident gets one check a day at a moment that already happens, like the medication pass.
- **Keeping the baseline fresh.** Outside windows, one check a week keeps each resident's normal up to date.
- **Who does what.** Care aides (PSWs) do the check on a shared phone or tablet. The charge nurse sees the watch list and the evidence. A wellness director can see unit-level trends.
- **What the nurse gets.** A short, ranked list with a counter for interruptions ("1 of 3 escalations used this shift") so Baseline never floods anyone with alerts, plus a drafted handoff note (SBAR) they can edit.

## Responding to PointClickCare's feedback

PointClickCare mentors liked the idea and flagged integration and scope as the bottlenecks. They suggested four things: start from speech, add more signals over time, design for how residents and staff feel about being monitored, and position Baseline as an add-on to Vox Advantage. Here's how the plan absorbs each one without blowing up the build.

### 1. An add-on to Vox Advantage, not a separate app

[Vox Advantage](https://pointclickcare.com/?p=66310) is PointClickCare's ambient voice documentation tool. It captures care conversations on a phone, builds consent into every session, and drafts notes that a nurse signs off before they reach the chart. It's in limited availability since 12 Aug 2026, with commercial release planned for October 2026. Baseline fits on both ends of it:

- **In:** Vox already records conversations with residents, so the resident's own speech in those recordings is a free, passive signal. Most residents would never need a separate check. The 10-second counting check stays for watch windows, where a fixed prompt gives cleaner comparisons.
- **Out:** Baseline's handoff note becomes a draft that lands in the same nurse sign-off queue, matching Vox's "a human reviews every note" model.
- **Honest gap:** we found no public Vox API, so for the hackathon we simulate a Vox encounter (audio, transcript, who spoke when) through a mock adapter, and say so. A real integration would go through PointClickCare's partner Marketplace.

### 2. Speech first, more signals later

Speech stays the MVP. The engine is built so any signal can plug in, as long as it produces a few numbers per check that are compared with the person's own normal. When two signals change together, the flag is marked **corroborated**, which is stronger than either alone.

| Signal | Status | Why and how |
| --- | --- | --- |
| Speech timing and pitch | **MVP** | 10-second check or Vox conversations |
| Movement: standing up and first steps | **Stretch for this weekend** | 10-second phone video; pose tracking runs in the browser, so only body-point coordinates leave the phone, never video. Measures time to stand, sway and step rhythm, early signs of falls and delirium. Judges can try it at the table |
| Heart rate and breathing | Roadmap, partly free | Vitals already charted in PointClickCare can be compared with each resident's normal today; wearables and camera-based heart rate later |
| Facial expression | Roadmap, narrowly | We won't build emotion recognition: the science is contested and it's especially unreliable and undignified for people with dementia. Narrow facial movement measures could be studied later with clinicians |

### 3. Designed for the people being monitored

**Residents, including people with dementia:**

- It feels like a moment of conversation, not a test: "Let's count together", with the prompt spoken aloud in the resident's language.
- Residents never see scores, flags or "wrong" answers. The screen ends with a warm thank-you by name.
- No hidden or always-on recording. The screen shows clearly when it's listening, consent is recorded at admission (by a substitute decision-maker when needed), and "skip today" is always one tap.
- If someone can't finish the prompt, it accepts what it got once and never makes them repeat it over and over.

**Care aides (PSWs):**

- One tap from a list of who's due, done in about 15 seconds during something they're already doing, like the medication pass.
- They don't see risk scores, which avoids anxiety and second-guessing. When their note helped a nurse act, they see "Your observation helped".

**Nurses:**

- A short list with an interruption budget, the evidence behind every flag, and a handoff draft they edit instead of write.

### 4. Scope stays the same

The order after the core build: the resident-friendly check screen first (cheap, and it's what PointClickCare asked about), then the Vox adapter mock, then the KAZE minimum, then the movement check if time allows.

## How it works

Four steps, three possible outcomes; only one of them interrupts a nurse.

&#91;embedded content: How Baseline works · 4 steps, 3 outcomes\]

The runner demo lands in **Explained** (her context says she's running a marathon). Mrs. K lands in **Escalate** (a new medication with confusion risk plus an aide's note).

## What makes it different

Existing tools either score risk from what's already in the chart, or analyse voice for other conditions; nobody we found measures each resident against their own speech and checks the record before deciding whether to bother a nurse.

| Existing | What it does | What Baseline adds |
| --- | --- | --- |
| PointClickCare pRTH (return-to-hospital risk) | Population risk score from charted data, refreshed twice a day, with ranked reasons | A new signal that isn't in the chart, compared with each person's own history; could feed pRTH as one more factor |
| PointClickCare AI summaries and Vox ambient notes | Summarise or document what staff already wrote or said | Measures something staff can't easily see, then explains it with evidence |
| Voice-biomarker companies (Winterlight, Canary Speech, Sonde) | Dementia trials, mental health, respiratory and home wellness | Focused on sudden change in long-term care, tied into the care team's workflow |
| Fall detectors and smartwatch alerts | React after a fall or impact; known for false alarms | Looks for change days earlier and suppresses changes the record already explains |

**The core design idea.** Statistics decide whether something changed. Simple, visible rules decide what to do about it. AI (Gemini) is used only where it's genuinely good: reading free-text notes to find context, and drafting the handoff. Every claim it makes is checked against the actual records, so it can't invent evidence.

### Prior-art check (as of 17 Oct 2026)

The building blocks exist; the combination doesn't, as far as a focused search found. Be precise on stage: we're not the first to link voice and delirium.

| Closest existing work | What it does | How Baseline differs |
| --- | --- | --- |
| [SeVA (University of Arizona spin-out)](https://techlaunch-static.arizona.edu/startuphub/startup/seva-technology-llc) | Voice, heart-rate variability and sensor data to predict delirium in hospitals, nursing homes and home care; early-stage testing, no clearance listed | **Closest overlap.** Baseline adds per-person baselines on a fixed 10-second protocol, record-aware suppression with cited evidence, and risk-triggered watch windows |
| [Ceribell delirium monitoring](https://hitconsultant.net/2025/12/12/fda-clears-ceribells-ai-powered-eeg-as-first-device-for-continuous-delirium-monitoring/) | FDA-cleared (Dec 2025) EEG headband for continuous delirium monitoring in the ICU | Different signal and setting: EEG hardware in intensive care vs a phone in long-term care |
| [Tang et al. 2023 study](https://cdnsciencepub.com/doi/10.1503/jpn.230026) | Research: speech features classify delirium in 33 hospitalized older adults | Research, not a product; we cite it as evidence |
| [Scienza Health GIA](https://scienzahealth.com/blog/speech-patterns-anxiety-ltc) | Voice screen for 46 conditions in 40 seconds, marketed to post-acute and long-term care (anxiety example) | Population screening; no individual baseline, delirium focus or record context described |
| [Canary Speech](https://www.speechtechmag.com/Articles/News/Speech-Technology-News/Canary-Speech-Launches-Canary-Ambient-Continuous-Monitoring-to-Address-Workplace-Violence-in-Healthcare-172023.aspx) | Vocal biomarkers for mood, stress and energy; ambient monitoring for verbal aggression in hospitals (Oct 2025) | Different targets; no delirium or record-aware suppression described |
| Check-in safety apps (Kitestring, Apple Check In, many "I'm alive" apps) | Timer-based check-ins that alert contacts | Relevant to the KAZE extension below; none measure whether the person's response is normal for them |

**What's new in Baseline:** comparing each person only with themselves on a fixed, comparable prompt; checking the record before deciding to interrupt anyone; citing every piece of evidence; and limiting checks to risk windows so it fits a real shift. Hackathon rules allow ideas that exist elsewhere; this is our answer to the "authenticity" criterion. Our search was focused, not exhaustive.

## The demo

Judging is in person on Sunday between 10am and 1pm: a 4-minute demo and 1 minute of questions. While we present, one of our teammates is running the Toronto marathon, and her voice is part of the demo.

1. **Live check (35 s).** A teammate does the 10-second check on stage. The screen breaks the speech down: the waveform, each word on a timeline, the pauses shaded, and four numbers.
2. **Mrs. K (75 s, synthetic resident).** She tops the watch list. Her speech slowed and her pauses grew two days after a new bladder medication with known confusion risk, and an aide wrote that she was "quiet at lunch". Her temperature was documented as normal. Baseline escalates, shows each piece of evidence, drafts the handoff note and suggests a 4AT delirium screen.
3. **The runner (55 s, real person).** She recorded her normal voice on Saturday. On Sunday she sends two short clips from a water station mid-race. Her speech is measurably slower, more broken and higher-pitched than her normal. Baseline sees the change, finds "running a marathon" in her context, and decides not to page anyone. That's the point: it noticed, and it knew not to interrupt.
4. **How it works and why it's trustworthy (30 s),** then the close (15 s).

**Safety for the runner.** She never stops, looks at her phone mid-stride, or fakes anything. Escalation is switched off for her profile. If her clips don't arrive, we play a clip recorded Saturday after climbing stairs, clearly labelled as a backup.

## Extension: Project KAZE ("Baseline Out")

The same engine works outside care homes: someone heading out arms a session, and if they stop answering check-ins, or their answers stop sounding like them, help starts automatically with the people they chose. That's the KAZE challenge exactly: help initiated when the person can no longer initiate it.

**How it works.**

1. **Arm a session.** Before going out, the user picks 1 or 2 trusted contacts, an end time and a check interval (default every 45 minutes), then records 3 quick clips. Those clips are tonight's baseline, captured while they're clearly themselves.
2. **Check-ins.** The phone buzzes; the user says the same 10-second prompt. A normal answer resets the timer. Nothing is shared with anyone.
3. **Triggers.** Two signals start the ladder: a **missed check-in** (no usable answer after 2 nudges over 5 minutes), which is the main one, or an answer that has **changed sharply from tonight's baseline** with nothing to explain it.
4. **Escalation ladder.** Another nudge, then a text to contact 1 with the reason, the time and a live location link (location is shared only at this point). The contact taps "I'm on it" to take ownership. No answer in 10 minutes, contact 2 gets the text. If nobody acknowledges, the message tells contacts to call 911. Baseline never dials 911 itself.
5. **Session ends** at the chosen time or when the user ends it. Recordings and location are deleted.

**Built for the four KAZE values.** *Safety:* missed check-ins work even if the phone is in a pocket and the person can't speak. *Dignity:* texts say "Danny asked us to check on him if he missed a check-in", never guesses about drinks or drugs. *Privacy:* location and audio leave the phone only on escalation and are deleted after. *Autonomy:* the user chooses contacts, timing and when to arm; nothing runs without consent. It doesn't try to tell whether someone was drugged, which the challenge explicitly says isn't the goal.

**Demo for the KAZE judge (45 s).** A teammate has a session armed with dee as the contact. On stage, the teammate ignores a check-in. dee's phone buzzes with the text and location; she taps "I'm on it" and the session shows "acknowledged by dee, 0:41 after the missed check-in". The runner's marathon is also a live session: her check-ins come back "explained by exercise", so nobody gets texted.

**In the main pitch** it's a 20-second mention: "same engine, out of the care home". When the KAZE judge is at the table, the KAZE demo replaces the Mrs. K segment.

## The plan to Sunday

Everything that needs the whole team is done by 6pm Saturday; the two hard deadlines after that are the initial Devpost entry at 9pm and the final submission at 8am.

&#91;embedded content: Plan to Sunday · 7 phases, 6 checkpoints\]

The 2pm checkpoint is the one real decision: if the runner's practice clips don't move the measurements the way exertion should, or processing a clip takes more than about 5 seconds, we switch to the fallback. The fallback links new medications to new symptoms using the same backend and needs no audio. The full build plan, with every ticket and its acceptance criteria, is in the technical handoff.

## Honest limits

We say these out loud before a judge asks.

- **Change detection, not diagnosis.** Baseline doesn't detect delirium. It notices that someone's speech changed against their own normal and suggests a standard assessment that a nurse runs.
- **Early evidence.** The best study linking speech to delirium had 33 patients (strong result, small sample). We call it promising, not proven.
- **The runner proves the pipeline, not the medicine.** Her result shows the system measures real physical change against a personal baseline. It says nothing about delirium.
- **Synthetic residents.** All resident data is made up and labelled as such. No real patient data is used.
- **Privacy.** Only the measurements are kept; audio is deleted after processing. Voice is personal health information under Ontario law, so a real deployment would need consent and Canadian hosting.
- **Regulation.** We designed it as decision support that shows its reasoning. A real product that analyses voice and prompts action could still be classed as a medical device by Health Canada, so launch would need a classification review.
