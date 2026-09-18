"""Renders a parsed sequence to audio using the game's own instrument bank.

Notes are voiced exactly the way the sequence player does it: the key map
picks a sample and the pitch ratio, the envelope shapes it, and looped samples
sustain by cycling their loop region.
"""
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import vadpcm
from .albank import Bank, Instrument, Sound

OUT_RATE = 44100
MAX_SECONDS = 420.0
# Every envelope in the bank has a zero-length attack, and 28 of the samples
# begin at a non-zero value. Starting or stopping one cold puts a step into
# the mix, which across a busy track reads as a constant crackle, so each
# voice gets a ramp far shorter than anything audible as a fade.
EDGE_FADE = 0.0025


def _cents_to_ratio(cents: float) -> float:
    return 2.0 ** (cents / 1200.0)


class Voicer:
    """Decodes and caches the bank's samples."""

    def __init__(self, bank_file, bank: Bank):
        self.bank_file = bank_file
        self.bank = bank
        self.rate = bank.sample_rate or 22050
        self._pcm: Dict[int, np.ndarray] = {}

    def pcm(self, wt) -> np.ndarray:
        key = wt.offset
        if key not in self._pcm:
            data = self.bank_file.sample_bytes(wt)
            try:
                if wt.type == 0:
                    out = vadpcm.decode(data, wt.book, wt.order)
                else:
                    out = np.frombuffer(data, dtype='>i2').astype(np.int16)
            except Exception:
                out = np.zeros(0, dtype=np.int16)
            self._pcm[key] = out.astype(np.float32) / 32768.0
        return self._pcm[key]

    def instrument(self, program: int) -> Optional[Instrument]:
        insts = self.bank.instruments
        if not insts:
            return None
        return insts[program] if 0 <= program < len(insts) else insts[0]

    @staticmethod
    def pick(inst: Instrument, key: int, velocity: int) -> Optional[Sound]:
        fallback = None
        for snd in inst.sounds:
            km = snd.keymap
            if km is None:
                fallback = fallback or snd
                continue
            lo, hi = sorted((km.key_min, km.key_max))
            vlo, vhi = sorted((km.velocity_min, km.velocity_max))
            if lo <= key <= hi and (vlo <= velocity <= vhi or vhi <= vlo):
                return snd
            fallback = fallback or snd
        return fallback or (inst.sounds[0] if inst.sounds else None)


def _envelope(n: int, env, out_rate: int, release_samples: int) -> np.ndarray:
    """Piecewise-linear attack / decay / sustain / release over n + release."""
    total = n + release_samples
    g = np.zeros(total, dtype=np.float32)
    if env is None:
        g[:n] = 1.0
        if release_samples:
            g[n:] = np.linspace(1.0, 0.0, release_samples, dtype=np.float32)
        return g

    a = max(0, int(env.attack_time * 1e-6 * out_rate))
    d = max(0, int(env.decay_time * 1e-6 * out_rate))
    av = env.attack_volume / 255.0
    dv = env.decay_volume / 255.0

    pos = 0
    if a and pos < n:
        take = min(a, n - pos)
        g[pos:pos + take] = np.linspace(0.0, av, take, dtype=np.float32)
        pos += take
    elif pos < n:
        g[pos] = av
    if d and pos < n:
        take = min(d, n - pos)
        g[pos:pos + take] = np.linspace(av, dv, take, dtype=np.float32)
        pos += take
    if pos < n:
        g[pos:n] = dv

    if release_samples:
        start = g[n - 1] if n else av
        g[n:] = np.linspace(start, 0.0, release_samples, dtype=np.float32)
    return g


def _interpolate(pcm: np.ndarray, pos: np.ndarray) -> np.ndarray:
    """Catmull-Rom interpolation.

    Straight linear interpolation of a 22 kHz source leaves a lot of imaging
    above 11 kHz, which is audible as hiss once a few dozen voices pile up.
    """
    n = len(pcm)
    i1 = np.floor(pos).astype(np.int64)
    frac = (pos - i1).astype(np.float32)
    i0 = np.clip(i1 - 1, 0, n - 1)
    i2 = np.clip(i1 + 1, 0, n - 1)
    i3 = np.clip(i1 + 2, 0, n - 1)
    i1 = np.clip(i1, 0, n - 1)
    p0, p1, p2, p3 = pcm[i0], pcm[i1], pcm[i2], pcm[i3]
    return (p1 + 0.5 * frac * ((p2 - p0)
            + frac * ((2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3)
                      + frac * (3.0 * (p1 - p2) + p3 - p0)))).astype(np.float32)


def _resample(pcm: np.ndarray, ratio: float, count: int, wt) -> np.ndarray:
    """count output samples of pcm advanced by `ratio` per step, honouring loops."""
    if len(pcm) == 0 or count <= 0:
        return np.zeros(max(count, 0), dtype=np.float32)
    raw = np.arange(count, dtype=np.float64) * ratio
    pos = raw.copy()
    loop_start, loop_end = wt.loop_start, wt.loop_end
    if loop_end > loop_start + 1 and loop_end < len(pcm):
        # loop_end names the last sample of the loop, not one past it. Dropping
        # that sample leaves a step at every wrap, and with a loop this short
        # that is a few hundred small discontinuities a second once a handful
        # of voices are sounding.
        span = loop_end - loop_start + 1
        over = pos >= loop_start
        pos[over] = loop_start + np.mod(pos[over] - loop_start, span)
        return _interpolate(pcm, pos)
    pos = np.clip(pos, 0, len(pcm) - 1)
    out = _interpolate(pcm, pos)
    out[raw >= len(pcm) - 1] = 0.0
    return out


def _timeline(seq):
    """tick -> seconds, using the tempo map."""
    events = sorted(seq.tempos) or [(0, 500000)]
    if events[0][0] > 0:
        events.insert(0, (0, events[0][1]))
    ticks = np.array([e[0] for e in events], dtype=np.float64)
    us = np.array([e[1] for e in events], dtype=np.float64)
    secs = np.zeros(len(events), dtype=np.float64)
    for i in range(1, len(events)):
        secs[i] = secs[i - 1] + (ticks[i] - ticks[i - 1]) / seq.division * us[i - 1] / 1e6

    def to_seconds(tick):
        i = int(np.searchsorted(ticks, tick, 'right') - 1)
        i = max(0, min(i, len(events) - 1))
        return secs[i] + (tick - ticks[i]) / seq.division * us[i] / 1e6

    return to_seconds


def _state_at(events: List[Tuple], tick: int, channel: int, default: int) -> int:
    value = default
    for t, ch, v in events:
        if t > tick:
            break
        if ch == channel:
            value = v
    return value


def render(seq, voicer: Voicer, out_rate: int = OUT_RATE) -> np.ndarray:
    """Return interleaved stereo float32 in [-1, 1]."""
    to_seconds = _timeline(seq)
    volumes = [(t, ch, v) for t, ch, cc, v in seq.controls if cc == 7]
    pans = [(t, ch, v) for t, ch, cc, v in seq.controls if cc == 10]
    expression = [(t, ch, v) for t, ch, cc, v in seq.controls if cc == 11]

    total = min(to_seconds(seq.end_tick) + 2.0, MAX_SECONDS)
    n = int(total * out_rate) + out_rate
    left = np.zeros(n, dtype=np.float32)
    right = np.zeros(n, dtype=np.float32)

    prog_cache: Dict[Tuple[int, int], int] = {}
    for note in seq.notes:
        start = to_seconds(note.tick)
        if start >= total:
            continue
        dur = max(to_seconds(note.tick + note.duration) - start, 0.02)

        key = (note.tick, note.channel)
        if key not in prog_cache:
            prog_cache[key] = _state_at(seq.programs, note.tick, note.channel, 0)
        inst = voicer.instrument(prog_cache[key])
        if inst is None:
            continue
        snd = voicer.pick(inst, note.key, note.velocity)
        if snd is None:
            continue
        wt = snd.wavetable
        pcm = voicer.pcm(wt)
        if len(pcm) == 0:
            continue

        km = snd.keymap
        base = km.key_base if km else 60
        detune = km.detune if km else 0
        ratio = _cents_to_ratio((note.key - base) * 100 + detune) * voicer.rate / out_rate

        env = snd.envelope
        release = int(min(env.release_time if env else 120000, 1500000) * 1e-6 * out_rate)
        release = max(release, int(0.01 * out_rate))
        count = int(dur * out_rate)
        gain = _envelope(count, env, out_rate, release)
        body = _resample(pcm, ratio, len(gain), wt)
        body = body * gain
        edge = min(int(EDGE_FADE * out_rate), len(body) // 3)
        if edge > 1:
            body[:edge] *= np.linspace(0.0, 1.0, edge, dtype=np.float32)
            body[-edge:] *= np.linspace(1.0, 0.0, edge, dtype=np.float32)

        amp = (note.velocity / 127.0) * (inst.volume / 127.0) \
            * (snd.sample_volume / 127.0 if snd.sample_volume else 1.0)
        amp *= _state_at(volumes, note.tick, note.channel, 100) / 127.0
        amp *= _state_at(expression, note.tick, note.channel, 127) / 127.0
        pan = _state_at(pans, note.tick, note.channel, snd.sample_pan or inst.pan or 64)
        pan = min(max(pan / 127.0, 0.0), 1.0)

        offset = int(start * out_rate)
        end = min(offset + len(body), n)
        if end <= offset:
            continue
        seg = body[:end - offset] * amp
        left[offset:end] += seg * np.sqrt(1.0 - pan)
        right[offset:end] += seg * np.sqrt(pan)

    peak = max(float(np.abs(left).max()), float(np.abs(right).max()), 1e-6)
    if peak > 0.99:
        left *= 0.99 / peak
        right *= 0.99 / peak

    # trim the silent tail
    loud = np.nonzero((np.abs(left) > 2e-4) | (np.abs(right) > 2e-4))[0]
    if len(loud):
        cut = min(n, int(loud[-1]) + out_rate // 4)
        left, right = left[:cut], right[:cut]

    return np.stack([left, right], axis=1)
