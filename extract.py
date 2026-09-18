"""Build the sound library from a Banjo-Kazooie ROM.

    py extract.py "path\to\Banjo-Kazooie (USA).z64"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from banjolib.library import build

HERE = Path(__file__).resolve().parent


def main():
    if len(sys.argv) > 1:
        rom = Path(sys.argv[1])
    else:
        print('usage: py extract.py <rom file>')
        return 1
    if not rom.exists():
        print('no such file:', rom)
        return 1

    def report(done, total):
        pct = 100.0 * done / max(total, 1)
        sys.stdout.write('\r  decoding %d/%d (%.0f%%)' % (done, total, pct))
        sys.stdout.flush()

    print('reading', rom.name)
    index = build(rom, HERE / 'library', report)
    print()
    for label, entries in index['categories'].items():
        print('  %-20s %d sounds' % (label, len(entries)))
    print('library written to', HERE / 'library')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
