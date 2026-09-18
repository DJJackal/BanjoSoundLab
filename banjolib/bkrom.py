"""Banjo-Kazooie ROM reader: byte order, asset table, Rare deflate, sound banks."""
import struct
import zlib
from dataclasses import dataclass
from typing import List, Optional

from .albank import BankFile

RARE_MAGIC = b'\x11\x72'


def to_big_endian(data: bytes) -> bytes:
    """Accept .z64 / .n64 / .v64 and return big-endian bytes."""
    if data[:4] == b'\x80\x37\x12\x40':
        return data
    if data[:4] == b'\x37\x80\x40\x12':          # byte-swapped (v64/n64)
        b = bytearray(data)
        b[0::2], b[1::2] = data[1::2], data[0::2]
        return bytes(b)
    if data[:4] == b'\x40\x12\x37\x80':          # little-endian
        b = bytearray(len(data))
        b[0::4], b[1::4], b[2::4], b[3::4] = data[3::4], data[2::4], data[1::4], data[0::4]
        return bytes(b)
    raise ValueError('not a recognised Nintendo 64 ROM image')


def rare_inflate(blob: bytes) -> bytes:
    """Rare's container: 0x1172 magic, big-endian u32 size, then raw deflate."""
    if blob[:2] != RARE_MAGIC:
        return blob
    size = struct.unpack_from('>I', blob, 2)[0]
    out = zlib.decompressobj(-zlib.MAX_WBITS).decompress(blob[6:])
    return out[:size] if size and len(out) >= size else out


@dataclass
class Asset:
    index: int
    rom_start: int
    rom_end: int
    kind: int
    flags: int


class SoundBank:
    """A .ctl/.tbl pair found in the ROM."""

    def __init__(self, rom: bytes, ctl_off: int):
        self.ctl_off = ctl_off
        ctl_len = self._measure_ctl(rom, ctl_off)
        tbl_off = (ctl_off + ctl_len + 15) & ~15
        probe = BankFile(rom[ctl_off:ctl_off + ctl_len], b'')
        tbl_len = 0
        for bank in probe.banks:
            insts = list(bank.instruments) + ([bank.percussion] if bank.percussion else [])
            for inst in insts:
                for snd in inst.sounds:
                    tbl_len = max(tbl_len, snd.wavetable.offset + snd.wavetable.length)
        self.tbl_off, self.tbl_len, self.ctl_len = tbl_off, tbl_len, ctl_len
        self.file = BankFile(rom[ctl_off:ctl_off + ctl_len],
                             rom[tbl_off:tbl_off + tbl_len])

    @staticmethod
    def _measure_ctl(rom: bytes, base: int) -> int:
        """Walk every structure to find where the control file ends."""
        def u32(o):
            return struct.unpack_from('>I', rom, base + o)[0]

        def s16(o):
            return struct.unpack_from('>h', rom, base + o)[0]

        end = 4
        for i in range(s16(2)):
            bo = u32(4 + 4 * i)
            n = s16(bo)
            end = max(end, bo + 12 + 4 * n)
            offs = [u32(bo + 12 + 4 * j) for j in range(n)]
            if u32(bo + 8):
                offs.append(u32(bo + 8))
            for io in offs:
                sn = s16(io + 14)
                end = max(end, io + 16 + 4 * sn)
                for k in range(sn):
                    so = u32(io + 16 + 4 * k)
                    end = max(end, so + 16)
                    for fo, sz in ((u32(so), 16), (u32(so + 4), 8)):
                        if fo:
                            end = max(end, fo + sz)
                    wo = u32(so + 8)
                    end = max(end, wo + 20)
                    lo, bo2 = u32(wo + 12), u32(wo + 16)
                    if lo:
                        end = max(end, lo + 44)
                    if bo2:
                        end = max(end, bo2 + 8 + 16 * u32(bo2) * u32(bo2 + 4))
        return end


class BanjoKazooieRom:
    SEQ_DIVISIONS = (48, 96, 120, 144, 192, 240, 384, 480, 960)

    def __init__(self, path):
        self.path = str(path)
        with open(path, 'rb') as fh:
            self.rom = to_big_endian(fh.read())
        self.title = self.rom[0x20:0x34].decode('latin1').strip('\x00 ')
        self.assets = self._find_assets()
        self.banks = self._find_banks()

    # -- assets ---------------------------------------------------------
    def _find_assets(self) -> List[Asset]:
        rom = self.rom
        for t in range(0x1000, 0x20000, 8):
            if rom[t:t + 4] != b'\x00\x00\x00\x00':
                continue
            if struct.unpack_from('>H', rom, t + 4)[0] > 1:
                continue
            entries, o, prev = [], t, -1
            while o < 0x20000:
                off, kind, flags = struct.unpack_from('>IHH', rom, o)
                if off < prev or kind > 1 or flags > 4:
                    break
                entries.append((off, kind, flags))
                prev = off
                o += 8
            if len(entries) > 1000:
                base = o
                out = []
                for i in range(len(entries) - 1):
                    off, kind, flags = entries[i]
                    out.append(Asset(i, base + off, base + entries[i + 1][0], kind, flags))
                self.asset_base = base
                return out
        raise ValueError('could not locate the asset table')

    def asset_data(self, index: int) -> bytes:
        a = self.assets[index]
        if a.rom_end <= a.rom_start:
            return b''
        return rare_inflate(self.rom[a.rom_start:a.rom_end])

    # -- sound banks ----------------------------------------------------
    def _find_banks(self) -> List[SoundBank]:
        rom, found = self.rom, []
        for o in range(0, len(rom) - 16, 4):
            if rom[o] == 0x42 and rom[o + 1] == 0x31:
                cnt = struct.unpack_from('>h', rom, o + 2)[0]
                if 1 <= cnt <= 128:
                    offs = struct.unpack_from('>%dI' % cnt, rom, o + 4)
                    if all(4 + cnt * 4 <= x < 0x400000 for x in offs):
                        try:
                            found.append(SoundBank(rom, o))
                        except Exception:
                            pass
        return found

    @property
    def sfx_bank(self) -> Optional[SoundBank]:
        """The bank holding the one-shot sound effects (one huge instrument)."""
        best = None
        for b in self.banks:
            n = max((len(i.sounds) for bank in b.file.banks for i in bank.instruments),
                    default=0)
            if best is None or n > best[0]:
                best = (n, b)
        return best[1] if best else None

    @property
    def music_bank(self) -> Optional[SoundBank]:
        """The bank holding the melodic instruments used by the sequences."""
        best = None
        for b in self.banks:
            n = sum(len(bank.instruments) for bank in b.file.banks)
            if best is None or n > best[0]:
                best = (n, b)
        return best[1] if best else None

    # -- sequences ------------------------------------------------------
    def sequence_indices(self) -> List[int]:
        out = []
        for a in self.assets:
            data = self.asset_data(a.index)
            if len(data) <= 68 or data[:4] != b'\x00\x00\x00\x44':
                continue
            div = struct.unpack_from('>I', data, 64)[0]
            tracks = [t for t in struct.unpack_from('>16I', data, 0) if t]
            if div in self.SEQ_DIVISIONS and tracks == sorted(tracks) \
                    and all(0x44 <= t <= len(data) for t in tracks):
                out.append(a.index)
        return out
