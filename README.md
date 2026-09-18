# Banjo Sound Lab

A player for every sound in Banjo-Kazooie: the sound effects and character
voices, the instrument samples, and all 173 music tracks. Search them, play
them, and save any of them out as WAV or MP3.

## Getting started from source

Install Python on Windows, then run `Banjo Sound Lab.cmd` (which installs
`numpy` and `pygame` if needed and launches `player.pyw`). Alternatively:

```powershell
py -m pip install -r requirements.txt
py player.pyw
```

The app prompts for a copy of the Banjo-Kazooie ROM that you provide yourself,
then generates the local `library/` on first run. No ROM or extracted audio is
included in this source repository. Keep your ROM available for on-demand music
rendering. The interface works with a plain background when the optional
`assets/bg.png` image is absent.

**Source-only note:** This repository deliberately omits all artwork, icons,
compiled executables and extracted audio. `make_bg.py` and `package.py` are
preserved as original source scripts but need their original `assets/` inputs
(or suitable replacements) before they can regenerate artwork or build an exe.

## What you get

| Category | Count | Where it comes from |
|---|---|---|
| Sound Effects | 402 | The effects bank, decoded from the cartridge's ADPCM |
| Instrument Samples | 159 | The music bank's instruments, one sample each |
| Music | 173 | Sequence data, played through the instrument bank |

Every name comes from the game's own source symbols, so `SFX_EA_GRUNTY_LAUGH_1`
shows up as "Grunty Laugh 1" and you can search either spelling.

## Using it

- Type to search; **Ctrl+F** jumps to the search box.
- **Enter** or double-click plays, **Esc** stops.
- **Loop** repeats the selection, which is how the looping samples are meant
  to be heard.
- **Save this sound...** writes the selection to a file. **Export everything
  listed...** writes out whatever the current search shows, so searching
  "grunty" and exporting gives you all 42 of her clips in one go.
- WAV always works. MP3, OGG and FLAC appear as options when ffmpeg is on the
  machine (it is found automatically at `C:\ffmpeg` or on PATH).

Music is stored in the cartridge as sequences rather than as audio, so the
first time you play a track it is rendered through the instrument bank. That
takes a second or two; after that it is cached in `library/music/` and plays
instantly.

## Rebuilding the library

```bash
py extract.py "path\to\Banjo-Kazooie.z64"
```

Delete the `library` folder to start over.

## How it works

- `banjolib/bkrom.py` — finds the asset table, the sound banks and the
  sequences in the ROM, and unpacks Rare's deflate container.
- `banjolib/vadpcm.py` — the ADPCM decoder. It is bit-exact: the cartridge
  stores a decoder snapshot at each looping sample's loop point, and the
  decoder reproduces 69 of the 71 of them exactly.
- `banjolib/albank.py` — the instrument bank format (samples, key maps,
  envelopes, loop points).
- `banjolib/n64seq.py` — the sequence format, including the back-reference
  compression the byte stream sits on.
- `banjolib/synth.py` — renders a sequence by voicing each note from the bank,
  matching how the game's sequence player picks samples and pitches them.
- `player.pyw` — the window.
- `make_bg.py` — regenerates the window background from `assets/background.png`.
  Drop in any image of that name and re-run it to reskin the app. Needs Pillow.

Two details worth knowing if you poke at the code. Effects are not played at
the bank's 22050 Hz: the sound driver derives each one's rate from its key map
as `22050 * 2 ** ((keyBase * 100 + detune - 6000) / 1200)`, which is why most
of them are really 11025 Hz. And a sample's `loop_end` names the last sample of
the loop rather than one past it — treating it as exclusive puts a small step
at every wrap, which across a dense track is audible as a constant crackle.

## Not included

Banjo-Tooie. Its asset table and audio region are located, but Tooie replaced
the standard sound bank format with something of Rare's own, and that has not
been decoded yet.

No ROM, and no audio extracted from one, is distributed with this. The
background image is Rare's cover art; swap `assets/background.png` and re-run
`make_bg.py` if you would rather it were not.
