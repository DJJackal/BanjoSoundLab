"""Builds a folder of WAV files plus an index from a Banjo ROM."""
import json
import re
import struct
import wave
from pathlib import Path

import numpy as np

from . import n64seq, vadpcm
from .bkrom import BanjoKazooieRom
from .paths import resource_dir

NAMES = json.loads(
    (resource_dir() / 'banjolib' / 'names_bk.json').read_text())


def native_rate(snd, bank_rate: int) -> int:
    """The rate a sample is actually played back at.

    Banjo-Kazooie stores each sample's recorded rate in its key map: the sound
    driver builds the playback ratio as 2 ** ((keyBase * 100 + detune - 6000)
    / 1200) and multiplies the bank rate by it (core1/code_5650.c).
    """
    km = snd.keymap
    if km is None:
        return bank_rate
    cents = km.key_base * 100 + km.detune - 6000
    rate = int(round(bank_rate * (2.0 ** (cents / 1200.0))))
    return max(2000, min(48000, rate))


# Rare's symbols lean on level abbreviations; spell them out for readers.
PLACES = {
    'SM': 'Spiral Mountain', 'MM': "Mumbo's Mountain", 'TTC': 'Treasure Trove Cove',
    'CC': "Clanker's Cavern", 'BGS': 'Bubblegloop Swamp', 'FP': 'Freezeezy Peak',
    'GV': "Gobi's Valley", 'MMM': 'Mad Monster Mansion', 'RBB': 'Rusty Bucket Bay',
    'CCW': 'Click Clock Wood', 'GL': "Gruntilda's Lair", 'FF': 'Furnace Fun',
    'BK': 'Banjo-Kazooie', 'NPC': 'NPC', 'SFX': 'SFX',
}
KEEP = {'TV', 'UFO', 'HP'}
SMALL = {'a', 'an', 'and', 'the', 'of', 'in', 'on', 'to', 'for'}


def _word(w: str, first: bool) -> str:
    if w.upper() in PLACES:
        return PLACES[w.upper()]
    if w.upper() in KEEP:
        return w.upper()
    if any(ch.isdigit() for ch in w):
        return w.lower() if w[0].isdigit() else w.capitalize()
    if not first and w.lower() in SMALL:
        return w.lower()
    return w.capitalize()


def prettify(raw: str, index: int) -> str:
    """SFX_4_KAZOOIE_RUUUUUH -> 'Kazooie Ruuuuuh'; COMUSIC_2_MM -> "Mumbo's Mountain"."""
    if not raw:
        return 'Sound %03d' % index
    s = re.sub(r'^(SFXR?|COMUSIC|JINGLE)_', '', raw)
    s = re.sub(r'^[0-9A-Fa-f]{1,4}_', '', s)
    words = [w for w in s.split('_') if w]
    if not words:
        return 'Sound %03d' % index
    return ' '.join(_word(w, i == 0) for i, w in enumerate(words))


def write_wav(path: Path, pcm: np.ndarray, rate: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.astype('<i2').tobytes())


def _sounds(bank_file):
    seen = {}
    for bank in bank_file.banks:
        insts = list(bank.instruments) + ([bank.percussion] if bank.percussion else [])
        for inst in insts:
            for snd in inst.sounds:
                wt = snd.wavetable
                if wt.offset not in seen:
                    seen[wt.offset] = (snd, bank.sample_rate)
    return [seen[k] for k in sorted(seen)]


def build(rom_path, out_dir, progress=None) -> dict:
    rom = BanjoKazooieRom(rom_path)
    out_dir = Path(out_dir)
    index = {'game': 'Banjo-Kazooie', 'rom': str(rom_path), 'categories': {}}

    jobs = []
    sfx = rom.sfx_bank
    if sfx:
        ordered = []
        for bank in sfx.file.banks:
            for inst in bank.instruments:
                for i, snd in enumerate(inst.sounds):
                    ordered.append((i, snd, bank.sample_rate))
                break
            break
        jobs.append(('Sound Effects', 'effects', sfx.file, ordered, NAMES['sfx'], True))

    mus = rom.music_bank
    if mus:
        ordered = [(i, snd, rate) for i, (snd, rate) in enumerate(_sounds(mus.file))]
        jobs.append(('Instrument Samples', 'instruments', mus.file, ordered, {}, False))

    total = sum(len(j[3]) for j in jobs)
    done = 0
    for label, slug, bank_file, ordered, namemap, sfx_pitch in jobs:
        entries = []
        for i, snd, rate in ordered:
            wt = snd.wavetable
            data = bank_file.sample_bytes(wt)
            try:
                pcm = vadpcm.decode(data, wt.book, wt.order) if wt.type == 0 \
                    else np.frombuffer(data, dtype='>i2').astype(np.int16)
            except Exception:
                pcm = np.zeros(0, dtype=np.int16)
            if len(pcm) == 0:
                done += 1
                continue
            # The sound driver pitches effects by keyBase; the sequence player
            # instead plays an instrument at the bank rate when the note equals
            # its keyBase, so those samples are already at their recorded rate.
            if sfx_pitch:
                rate = native_rate(snd, rate)
            raw_name = namemap.get(str(i), '')
            name = prettify(raw_name, i)
            fn = '%03d_%s.wav' % (i, re.sub(r'[^A-Za-z0-9]+', '_', name).strip('_') or 'sound')
            write_wav(out_dir / slug / fn, pcm, rate)
            entries.append({
                'id': i,
                'name': name,
                'symbol': raw_name,
                'file': '%s/%s' % (slug, fn),
                'seconds': round(len(pcm) / rate, 3),
                'rate': rate,
                'looped': bool(wt.loop_state or wt.loop_end),
            })
            done += 1
            if progress and done % 10 == 0:
                progress(done, total)
        index['categories'][label] = entries

    # Music is held as sequence data, not audio; it is rendered on demand.
    tracks = []
    for slot, asset in enumerate(rom.sequence_indices()):
        try:
            seq = n64seq.parse(rom.asset_data(asset))
        except Exception:
            continue
        raw_name = NAMES['music'].get(str(slot), '')
        tracks.append({
            'id': slot,
            'name': prettify(raw_name, slot),
            'symbol': raw_name,
            'asset': asset,
            'notes': len(seq.notes),
            'seconds': round(min(seq.seconds, 420.0), 1),
            'rate': 44100,
            'render': True,
        })
    if tracks:
        index['categories']['Music'] = tracks
    index['rom'] = str(Path(rom_path).resolve())

    if progress:
        progress(total, total)
    (out_dir / 'index.json').write_text(json.dumps(index, indent=1))
    return index
