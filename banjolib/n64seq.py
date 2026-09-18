"""Reader for the Nintendo 64 'compressed MIDI' sequence format.

The layout is sixteen track offsets followed by the division. Each track is
ordinary MIDI with running status, except that a note-on carries its duration
instead of being matched by a note-off, and the byte stream sits on top of a
small back-reference scheme: 0xFE introduces a repeat of an earlier run of
bytes, and 0xFE 0xFE escapes a literal 0xFE.

This mirrors __getTrackByte and __n_alCSeqGetTrackEvent in the game's own
sequence player (core1/n_audio/n_csq.c).
"""
import struct
from dataclasses import dataclass, field
from typing import List, Tuple

HEADER_SIZE = 0x44

BLOCK_CODE = 0xFE
META = 0xFF
META_TEMPO = 0x51
META_EOT = 0x2F
META_LOOPSTART = 0x2E
META_LOOPEND = 0x2D

DIVISIONS = (48, 96, 120, 144, 192, 240, 384, 480, 960)


@dataclass
class Note:
    tick: int
    channel: int
    key: int
    velocity: int
    duration: int


@dataclass
class Sequence:
    division: int = 384
    notes: List[Note] = field(default_factory=list)
    programs: List[Tuple[int, int, int]] = field(default_factory=list)
    controls: List[Tuple[int, int, int, int]] = field(default_factory=list)
    bends: List[Tuple[int, int, int]] = field(default_factory=list)
    tempos: List[Tuple[int, int]] = field(default_factory=list)
    end_tick: int = 0

    @property
    def seconds(self) -> float:
        """Length using the tempo map."""
        if not self.notes and not self.end_tick:
            return 0.0
        events = sorted(self.tempos) or [(0, 500000)]
        total, prev_tick, us = 0.0, 0, events[0][1]
        for tick, value in events:
            if tick > prev_tick:
                total += (tick - prev_tick) / self.division * us / 1e6
                prev_tick = tick
            us = value
        total += (self.end_tick - prev_tick) / self.division * us / 1e6
        return max(total, 0.0)


class _TrackReader:
    """Byte stream for one track, unwrapping the back-reference scheme."""

    def __init__(self, data: bytes, pos: int, end: int):
        self.d = data
        self.pos = pos
        self.end = end
        self.bu_ptr = 0
        self.bu_len = 0
        self.finished = False

    def byte(self) -> int:
        if self.bu_len:
            b = self.d[self.bu_ptr]
            self.bu_ptr += 1
            self.bu_len -= 1
            return b
        if self.pos >= self.end:
            self.finished = True
            return META            # forces a clean stop upstream
        b = self.d[self.pos]
        self.pos += 1
        if b != BLOCK_CODE:
            return b
        nxt = self.d[self.pos]
        self.pos += 1
        if nxt == BLOCK_CODE:      # escaped literal 0xFE
            return BLOCK_CODE
        hi, lo = nxt, self.d[self.pos]
        self.pos += 1
        length = self.d[self.pos]
        self.pos += 1
        backup = (hi << 8) | lo
        self.bu_ptr = self.pos - (backup + 4)
        self.bu_len = length
        if self.bu_ptr < 0 or not self.bu_len:
            self.finished = True
            return META
        b = self.d[self.bu_ptr]
        self.bu_ptr += 1
        self.bu_len -= 1
        return b

    def varlen(self) -> int:
        value = self.byte()
        if value & 0x80:
            value &= 0x7F
            while True:
                c = self.byte()
                value = (value << 7) + (c & 0x7F)
                if not c & 0x80:
                    break
        return value

    @property
    def done(self) -> bool:
        return self.finished or (self.pos >= self.end and not self.bu_len)


def looks_like_sequence(data: bytes) -> bool:
    if len(data) <= HEADER_SIZE or data[:4] != b'\x00\x00\x00\x44':
        return False
    if struct.unpack_from('>I', data, 64)[0] not in DIVISIONS:
        return False
    tracks = [t for t in struct.unpack_from('>16I', data, 0) if t]
    return tracks == sorted(tracks) and all(HEADER_SIZE <= t <= len(data) for t in tracks)


def parse(data: bytes, follow_loops: bool = False) -> Sequence:
    offsets = struct.unpack_from('>16I', data, 0)
    seq = Sequence(division=struct.unpack_from('>I', data, 64)[0])
    for off in offsets:
        if off:
            end = min([o for o in offsets if o > off] + [len(data)])
            _read_track(data, off, end, seq, follow_loops)
    seq.notes.sort(key=lambda n: n.tick)
    seq.tempos.sort()
    seq.programs.sort()
    seq.controls.sort()
    seq.end_tick = max([n.tick + n.duration for n in seq.notes] + [seq.end_tick, 1])
    return seq


def _read_track(data, start, end, seq, follow_loops, budget=250000):
    r = _TrackReader(data, start, end)
    tick = 0
    status = 0
    steps = 0
    while not r.done and steps < budget:
        steps += 1
        tick += r.varlen()
        if r.done:
            break
        b = r.byte()
        if b == META:
            kind = r.byte()
            if kind == META_EOT:
                break
            if kind == META_TEMPO:
                seq.tempos.append((tick, (r.byte() << 16) | (r.byte() << 8) | r.byte()))
                status = 0
                continue
            if kind == META_LOOPSTART:
                r.byte()
                r.byte()
                status = 0
                continue
            if kind == META_LOOPEND:
                # loopCount, currentCount, then a 32-bit backwards offset. The
                # counters live in the stream itself, so a player mutates them;
                # rendering once through is what an export wants.
                r.byte()
                r.byte()
                offset = (r.byte() << 24) | (r.byte() << 16) | (r.byte() << 8) | r.byte()
                if follow_loops and not r.bu_len and 0 < offset <= r.pos - start:
                    r.pos -= offset
                status = 0
                continue
            break                      # unknown meta: stop this track cleanly

        if b & 0x80:
            status = b
            b = r.byte()
        if not status:
            break
        kind, chan = status & 0xF0, status & 0x0F
        if kind in (0xC0, 0xD0):       # program change / channel pressure
            if kind == 0xC0:
                seq.programs.append((tick, chan, b))
            continue
        b2 = r.byte()
        if kind == 0x90:
            duration = r.varlen()
            if b2:
                seq.notes.append(Note(tick, chan, b, b2, max(duration, 1)))
        elif kind == 0xB0:
            seq.controls.append((tick, chan, b, b2))
        elif kind == 0xE0:
            seq.bends.append((tick, chan, (b | (b2 << 7)) - 8192))
    seq.end_tick = max(seq.end_tick, tick)
