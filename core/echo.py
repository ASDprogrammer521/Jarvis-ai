"""
Telling the user's voice apart from our own coming back through the speakers.

What it is used for today
-------------------------
The *echo tail*: for a moment after a reply ends, sound is still leaving the
speakers, because writing to an audio device returns when the buffer accepts the
audio and not when the room has finished with it. Streaming the microphone
during that gap is how an assistant hears its own last sentence and answers
itself. This module lets the tail drop our own voice while still passing a user
who replies instantly, instead of blanket-muting.

Interrupting mid-sentence by voice is the other thing it can do, and everything
needed for it is here and tested — but it depends on the listener's room, so it
stays switched off until it can be tried on real hardware. See the note in
`_listen_audio` for how little it takes to turn back on.

The problem with a level test
-----------------------------
Deciding "the microphone is louder than the echo" needs to know how loud the
echo *is*, and that is not a constant. It depends on the speaker volume, where
the microphone sits, the room, whether headphones are plugged in, and whether
the user happens to have a hand over the mic. A single tuned number is wrong for
almost everyone: too eager on a loud desktop speaker, too deaf on a quiet laptop.

What this does instead
----------------------
Two independent signals, neither of which needs tuning per machine:

1. **Content.** Echo is not merely loud — it is *the same sound we just played*.
   Both streams are reduced to a handful of band energies, and then — rather
   than merely compared — as much of the recent output as fits is *subtracted*
   from the microphone block. Pure echo cancels to almost nothing. A second
   voice cannot be cancelled by ours, because its formants sit in bands where
   ours were weak, so it survives the subtraction. That distinction holds even
   when the two arrive at the same loudness, which is exactly the case a level
   test gets wrong.

2. **A learned echo gain.** Whenever the content check says "that is definitely
   just echo", the observed mic-to-output ratio is folded into a running
   estimate. The system therefore calibrates itself to the actual room within a
   few seconds of the first sentence, and re-calibrates when the volume changes
   or a hand covers the microphone.

Band energies rather than raw spectra also make the comparison sample-rate
agnostic, which matters here: the microphone runs at 16 kHz and playback at
24 kHz.
"""

from __future__ import annotations

import time

import numpy as np

_BAND_EDGES = (200, 400, 700, 1100, 1700, 2600, 3800, 5200, 7000)

_HISTORY_S = 1.5
_MIN_LEVEL = 0.06

_MIN_USER = 0.15
_HEAD_Q = 97
_HEAD_MULT = 1.15

_UNRELIABLE_FLOOR = 0.22
_BLOCKS_NORMAL = 5
_BLOCKS_NOISY = 12

_FLOOR_WINDOW = 60
_FLOOR_Q = 35
_WARMUP = 16
_RELEARN_RUN = 28

def band_energies(pcm, sr: int) -> np.ndarray:
    """Raw energy per speech band — the fingerprint we compare.

    Left unnormalised on purpose: the decision below projects one of these onto
    another, and a projection needs real magnitudes.
    """
    x = np.asarray(pcm, dtype=np.float32)
    if x.size < 64:
        return np.zeros(len(_BAND_EDGES) - 1, dtype=np.float32)
    x = x - x.mean()
    n = 1 << (int(x.size) - 1).bit_length()
    mag = np.abs(np.fft.rfft(x * np.hanning(x.size), n=n))
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    out = np.empty(len(_BAND_EDGES) - 1, dtype=np.float32)
    for i in range(len(_BAND_EDGES) - 1):
        m = (freqs >= _BAND_EDGES[i]) & (freqs < _BAND_EDGES[i + 1])
        out[i] = float(mag[m].sum())
    return out

class EchoGuard:
    """Classifies microphone blocks while the assistant is speaking.

    Usage: `note_output()` from the playback path, `is_user_speech()` from the
    microphone callback. Both are cheap enough to sit in an audio thread — one
    small FFT each.
    """

    def __init__(self) -> None:
        self._hist: list[tuple[float, np.ndarray, float]] = []
        self._gain = 0.6
        self._seen = 0
        self._last_sim = 0.0
        self._last_expected = 0.0
        self._residuals: list[float] = []
        self._floor = 0.10
        self._run = 0
        self._head = 0.13

    @property
    def gain(self) -> float:
        return self._gain

    @property
    def calibrated(self) -> bool:
        """True once the estimate rests on enough real echo to be trusted."""
        return self._seen >= 8

    @property
    def floor(self) -> float:
        """Residual left by this room's own echo. Higher = harder to separate."""
        return self._floor

    @property
    def reliable(self) -> bool:
        """False when the acoustics are too poor to judge on content alone.

        Speakers turned up in a reverberant room leave an echo that survives the
        subtraction almost as well as a quiet voice does. Rather than guess, the
        guard says so and starts demanding corroborating evidence.
        """
        return self._floor < _UNRELIABLE_FLOOR

    @property
    def threshold(self) -> float:
        """The residual a block must clear right now to count as a voice."""
        return max(_MIN_USER, self._head * _HEAD_MULT)

    @property
    def required_blocks(self) -> int:
        """Consecutive positive blocks before an interruption is believed."""
        return _BLOCKS_NORMAL if self.reliable else _BLOCKS_NOISY

    @property
    def last_similarity(self) -> float:
        """1.0 = fully explained by our own output, 0.0 = nothing to do with it."""
        return self._last_sim

    def reset(self) -> None:
        """Playback stopped — drop the history, keep what was learned."""
        self._hist.clear()
        self._last_sim = 0.0

    def note_output(self, pcm, sr: int, level: float, when: float | None = None) -> None:
        """Record a slice of what is being played, for later comparison."""
        try:
            t = time.monotonic() if when is None else when
            self._hist.append((t, band_energies(pcm, sr), float(level)))
            cutoff = t - _HISTORY_S
            if len(self._hist) > 8:
                self._hist = [h for h in self._hist if h[0] >= cutoff]
        except Exception:
            pass

    def is_user_speech(self, pcm, sr: int, level: float,
                       when: float | None = None) -> bool:
        """True if this microphone block is a different voice, not our echo."""
        try:
            if level < _MIN_LEVEL:
                if self._hist and max(h[2] for h in self._hist) > 0.15:
                    self._residuals.append(0.0)
                    if len(self._residuals) > _FLOOR_WINDOW:
                        del self._residuals[:-_FLOOR_WINDOW]
                    if len(self._residuals) >= _WARMUP:
                        self._floor = float(np.percentile(self._residuals, _FLOOR_Q))
                        self._head = float(np.percentile(self._residuals, _HEAD_Q))
                self._run = 0
                return False
            if not self._hist:
                return True

            t = time.monotonic() if when is None else when
            bands = band_energies(pcm, sr)
            total = float(bands.sum())
            if total <= 1e-9:
                return False

            best_res, best_level = 1.0, 0.0
            for ts, ref, ref_level in self._hist:
                if ts > t or t - ts > _HISTORY_S:
                    continue
                denom = float(np.dot(ref, ref))
                if denom < 1e-12:
                    continue
                alpha = max(0.0, float(np.dot(bands, ref)) / denom)
                residual = np.maximum(bands - alpha * ref, 0.0)
                ratio = float(residual.sum()) / total
                if ratio < best_res:
                    best_res, best_level = ratio, ref_level
            self._last_sim = 1.0 - best_res

            if best_level <= 0.0:
                return True

            warming = len(self._residuals) < _WARMUP
            thr = self.threshold
            speech = (not warming) and best_res >= thr

            if speech:
                self._run += 1
                if self._run > _RELEARN_RUN:
                    self._residuals.clear()
                    self._run = 0
                    return False
                return True

            self._run = 0
            self._residuals.append(best_res)
            if len(self._residuals) > _FLOOR_WINDOW:
                del self._residuals[:-_FLOOR_WINDOW]
            if len(self._residuals) >= _WARMUP:
                self._floor = float(np.percentile(self._residuals, _FLOOR_Q))
                self._head = float(np.percentile(self._residuals, _HEAD_Q))
            if warming:
                return False

            if best_res <= self._floor * 1.15 and best_level > 0.05:
                obs = level / max(best_level, 1e-6)
                self._gain += (min(obs, 3.0) - self._gain) * 0.08
                self._seen = min(self._seen + 1, 999)
            return False
        except Exception:
            return False

# by ASDcuber521
