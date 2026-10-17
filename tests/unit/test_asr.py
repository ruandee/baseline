import shutil
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from patient_memory.speech import asr
from patient_memory.speech.audio import load_pcm, normalize


def test_importing_asr_does_not_load_whisper():
    code = "import sys, patient_memory.speech.asr; assert 'faster_whisper' not in sys.modules"
    subprocess.run([sys.executable, "-I", "-c", code], check=True)


def test_transcribe_drains_the_lazy_segments_and_strips_words(monkeypatch):
    drained = []

    def segments():
        yield SimpleNamespace(words=[SimpleNamespace(word=" one", start=np.float64(0.1),
                                                     end=np.float64(0.4)),
                                     SimpleNamespace(word=" two", start=0.5, end=0.9)])
        drained.append(True)
        yield SimpleNamespace(words=[SimpleNamespace(word=" three", start=1.0, end=1.5)])
        drained.append(True)

    seen = {}

    class FakeModel:
        def transcribe(self, audio, **options):
            seen.update(options, audio=audio)
            return segments(), SimpleNamespace(language="en")

    monkeypatch.setattr(asr, "model", lambda: FakeModel())

    samples = np.zeros(16000, dtype=np.float32)
    words = asr.transcribe(samples)

    assert words == [asr.Word("one", 0.1, 0.4), asr.Word("two", 0.5, 0.9),
                     asr.Word("three", 1.0, 1.5)]
    assert drained == [True, True]
    assert all(type(w.start) is float and type(w.end) is float for w in words)
    assert seen.pop("audio") is samples  # an ndarray skips faster-whisper's own av decoding
    assert seen == {"beam_size": 1, "language": "en", "word_timestamps": True,
                    "vad_filter": False}


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("say") is None or shutil.which("ffmpeg") is None,
                    reason="needs macOS say and ffmpeg")
def test_real_whisper_returns_ordered_word_timestamps(tmp_path):
    spoken = tmp_path / "spoken.aiff"
    prompt = ("one, two, three, four, five, six, seven, eight, nine, ten, eleven, twelve, "
              "thirteen, fourteen, fifteen, sixteen, seventeen, eighteen, nineteen, twenty. "
              "Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday.")
    subprocess.run(["say", "-r", "150", "-o", str(spoken), prompt], check=True)
    wav = tmp_path / "spoken.wav"
    normalize(spoken, wav)

    words = asr.transcribe(load_pcm(wav))

    assert len(words) >= 20
    assert [w.start for w in words] == sorted(w.start for w in words)
    assert all(w.end > w.start for w in words)
    assert words[-1].w.strip(" .,").lower() == "sunday"
