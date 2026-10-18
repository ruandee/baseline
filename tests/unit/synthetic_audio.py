import numpy as np

SAMPLE_RATE = 16000


def voiced(seconds, f0=140.0):
    """Harmonic-rich, syllable-modulated tone that webrtcvad treats as speech."""
    t = np.arange(round(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    phase = 2 * np.pi * np.cumsum(f0 * (1 + 0.03 * np.sin(2 * np.pi * 5 * t))) / SAMPLE_RATE
    tone = sum(np.sin(k * phase) / k for k in range(1, 30))
    am = 0.6 + 0.4 * np.abs(np.sin(2 * np.pi * 4 * t))
    return 0.3 * tone / np.max(np.abs(tone)) * am


def silence(seconds, rng, noise=0.003):
    """Quiet room noise; a pure-zero floor hides the startup burst real recordings show."""
    return noise * rng.standard_normal(round(seconds * SAMPLE_RATE))


SPEAKER_F0 = {"resident": 140.0, "staff": 230.0, "other": 190.0}


def encounter(segments, tail=0.5, seed=0):
    """A synthetic mixed-speaker conversation laid out on the segments' timeline.

    Each turn is 1.4 s syllable runs with 0.4 s pauses at its speaker's pitch, so resident-only
    extraction can be checked by F0. Overlapping turns are summed, like crosstalk.
    """
    rng = np.random.default_rng(seed)
    total = max(s["end"] for s in segments) + tail
    audio = silence(total, rng)
    for s in segments:
        offset, end = round(s["start"] * SAMPLE_RATE), round(s["end"] * SAMPLE_RATE)
        cursor = offset + round(0.3 * SAMPLE_RATE)
        while cursor < end:
            run = voiced(1.4, SPEAKER_F0[s["speaker"]])[:end - cursor]
            audio[cursor:cursor + len(run)] += run
            cursor += len(run) + round(0.4 * SAMPLE_RATE)
    return np.clip(audio, -0.95, 0.95).astype(np.float32)


def clip(plan, seed=0):
    """Concatenate ("v"|"s", seconds) segments into a float32 mono 16 kHz signal."""
    rng = np.random.default_rng(seed)
    parts = [voiced(d) if kind == "v" else silence(d, rng) for kind, d in plan]
    return np.concatenate(parts).astype(np.float32)
