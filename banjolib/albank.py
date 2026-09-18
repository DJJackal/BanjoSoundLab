"""Parser for the Nintendo 64 SDK ALBankFile (.ctl) instrument-bank format."""
import struct
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

AL_BANK_VERSION = 0x4231  # 'B1'


@dataclass
class Envelope:
    attack_time: int
    decay_time: int
    release_time: int
    attack_volume: int
    decay_volume: int


@dataclass
class KeyMap:
    velocity_min: int
    velocity_max: int
    key_min: int
    key_max: int
    key_base: int
    detune: int


@dataclass
class Wavetable:
    offset: int          # byte offset into the .tbl blob
    length: int          # length in bytes
    type: int            # 0 = ADPCM, 1 = raw 16-bit
    book: Optional[np.ndarray] = None    # (npredictors, order, 8) int16
    order: int = 2
    loop_start: int = 0
    loop_end: int = 0
    loop_count: int = 0
    loop_state: Optional[List[int]] = None


@dataclass
class Sound:
    envelope: Optional[Envelope]
    keymap: Optional[KeyMap]
    wavetable: Wavetable
    sample_pan: int
    sample_volume: int
    flags: int


@dataclass
class Instrument:
    volume: int
    pan: int
    priority: int
    bend_range: int
    sounds: List[Sound] = field(default_factory=list)


@dataclass
class Bank:
    sample_rate: int
    percussion: Optional[Instrument]
    instruments: List[Instrument] = field(default_factory=list)


class BankFile:
    """An ALBankFile plus the raw sample table that accompanies it."""

    def __init__(self, ctl: bytes, tbl: bytes):
        self.ctl = ctl
        self.tbl = tbl
        self.banks: List[Bank] = []
        self._parse()

    # -- little helpers -------------------------------------------------
    def _u32(self, o): return struct.unpack_from('>I', self.ctl, o)[0]
    def _s32(self, o): return struct.unpack_from('>i', self.ctl, o)[0]
    def _u16(self, o): return struct.unpack_from('>H', self.ctl, o)[0]
    def _s16(self, o): return struct.unpack_from('>h', self.ctl, o)[0]

    def _parse(self):
        if self._u16(0) != AL_BANK_VERSION:
            raise ValueError('not an ALBankFile (bad revision)')
        count = self._s16(2)
        self._wt_cache = {}
        for i in range(count):
            self.banks.append(self._bank(self._u32(4 + 4 * i)))

    def _bank(self, o):
        inst_count = self._s16(o)
        rate = self._s32(o + 4)
        perc_off = self._u32(o + 8)
        insts = [self._inst(self._u32(o + 12 + 4 * i)) for i in range(inst_count)]
        perc = self._inst(perc_off) if perc_off else None
        return Bank(sample_rate=rate, percussion=perc, instruments=insts)

    def _inst(self, o):
        vol, pan, pri = self.ctl[o], self.ctl[o + 1], self.ctl[o + 2]
        bend = self._s16(o + 12)
        n = self._s16(o + 14)
        sounds = [self._sound(self._u32(o + 16 + 4 * i)) for i in range(n)]
        return Instrument(volume=vol, pan=pan, priority=pri, bend_range=bend, sounds=sounds)

    def _sound(self, o):
        env_off, km_off, wt_off = self._u32(o), self._u32(o + 4), self._u32(o + 8)
        env = None
        if env_off:
            env = Envelope(self._s32(env_off), self._s32(env_off + 4), self._s32(env_off + 8),
                           self.ctl[env_off + 12], self.ctl[env_off + 13])
        km = None
        if km_off:
            km = KeyMap(self.ctl[km_off], self.ctl[km_off + 1], self.ctl[km_off + 2],
                        self.ctl[km_off + 3], self.ctl[km_off + 4],
                        struct.unpack_from('>b', self.ctl, km_off + 5)[0])
        return Sound(env, km, self._wavetable(wt_off),
                     self.ctl[o + 12], self.ctl[o + 13], self.ctl[o + 14])

    def _wavetable(self, o):
        if o in self._wt_cache:
            return self._wt_cache[o]
        base, length, typ = self._u32(o), self._s32(o + 4), self.ctl[o + 8]
        wt = Wavetable(offset=base, length=length, type=typ)
        loop_off, book_off = self._u32(o + 12), self._u32(o + 16)
        if typ == 0:   # ADPCM
            if book_off:
                order = self._s32(book_off)
                npred = self._s32(book_off + 4)
                n = order * npred * 8
                coef = np.frombuffer(self.ctl, dtype='>i2', count=n,
                                     offset=book_off + 8).astype(np.int16)
                wt.book = coef.reshape(npred, order, 8)
                wt.order = order
            if loop_off:
                wt.loop_start = self._u32(loop_off)
                wt.loop_end = self._u32(loop_off + 4)
                wt.loop_count = self._u32(loop_off + 8)
                wt.loop_state = list(struct.unpack_from('>16h', self.ctl, loop_off + 12))
        else:          # raw 16-bit
            if loop_off:
                wt.loop_start = self._u32(loop_off)
                wt.loop_end = self._u32(loop_off + 4)
                wt.loop_count = self._u32(loop_off + 8)
        self._wt_cache[o] = wt
        return wt

    def sample_bytes(self, wt: Wavetable) -> bytes:
        return self.tbl[wt.offset:wt.offset + wt.length]
