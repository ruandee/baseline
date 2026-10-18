# 034: Local voice capture with three scripted demo days

Status: implemented for review after Dee requested Watch, Explained and Escalate with skipped
days. This supersedes decision 030's optional simulation plan, not the genuine checks API.

The operator opens `/check?mode=live&demo=days`. The mode is opt-in and distinct from ordinary
live, runner, resident, motion and KAZE flows. It uses only local authored scenario data and
does not bootstrap a session, retrieve records, upload audio, call ASR/providers, record a real
baseline, or write a verdict into patient history. Existing authorization/consent gates on real
APIs are unchanged. Five rested recordings are unnecessary for this presentation mode.

Each day requires a live browser recording or an explicitly prerecorded local file before its
scripted result is revealed. Day 1 is Watch, day 2 Explained (fictional dentures context), day 3
Escalate (fictional medication/intake context). Feature values, baseline and notes are authored
examples for a fictional resident, never attributed to the person in the recording. Persistent
and result-level simulation labels state that these values were not computed from the audio.
Only existing standard action labels are used; no action or clinical assessment is performed.

Next simulated day advances an in-memory index, clears the clip and never changes wall time,
server timestamps or actual historical knowledge. Restart and page exit stop/discard pending
capture, clear the scenario, release playback and revoke blob URLs. There is no audio/history
persistence, localStorage or real sign-off/export path. Microphone permission is requested only
after Record is tapped. A reset during a pending permission or file-metadata event cannot
restore a discarded recording. Missing permission, decode failure, overlong imported files or
empty files do not produce a successful receipt/result.

The 30-second browser timer applies to this local recorder. Imported audio must have a known
duration no greater than 30 seconds and a file size below 20 MB; the existing API's separate
2 MB limit is unchanged because this mode never uploads. The file picker accepts audio and
WAV/WebM/MP4/M4A extensions. Unsupported/unknown-duration files require a different local export.

Deterministic browser tests cover three-day transitions, no API/storage calls, permission and
reset races, overlong imports, timer stop and resource cleanup. Desktop and 390px phone viewport
Chrome tests load Dee's actual normal/slow/pausey WAVs locally through all three outcomes with
no API/session requests. Those files and screenshots remain ignored. This validates the staged
UI, not exertion detection, clinical change, the physical demo device or a deployed release.
