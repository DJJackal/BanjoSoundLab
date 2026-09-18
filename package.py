"""Builds the distributable: one self-contained exe, containing no game data.

    py package.py          # build the exe
    py package.py --zip    # also build the source zip
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXE_NAME = 'Banjo Sound Lab'

SOURCE_FILES = [
    'player.pyw', 'extract.py', 'make_bg.py', 'package.py',
    'requirements.txt', 'README.md', 'Banjo Sound Lab.cmd',
    'banjolib/__init__.py', 'banjolib/albank.py', 'banjolib/bkrom.py',
    'banjolib/library.py', 'banjolib/n64seq.py', 'banjolib/paths.py',
    'banjolib/synth.py', 'banjolib/vadpcm.py', 'banjolib/names_bk.json',
    'assets/background.png', 'assets/bg.png', 'assets/app.ico',
]

# Nothing that came out of a cartridge ships.
FORBIDDEN = {'.z64', '.n64', '.v64', '.wav', '.mp3', '.ogg', '.flac'}


def check(names):
    missing = [n for n in names if not (HERE / n).exists()]
    if missing:
        raise SystemExit('missing: %s' % ', '.join(missing))
    bad = [n for n in names if Path(n).suffix.lower() in FORBIDDEN]
    if bad:
        raise SystemExit('refusing to package game data: %s' % ', '.join(bad))


def build_exe():
    check(SOURCE_FILES)
    for stale in ('build', 'dist'):
        shutil.rmtree(HERE / stale, ignore_errors=True)
    cmd = [
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--windowed',
        '--name', EXE_NAME,
        '--icon', 'assets/app.ico',
        '--add-data', 'assets/bg.png;assets',
        '--add-data', 'banjolib/names_bk.json;banjolib',
        '--exclude-module', 'PIL',
        '--exclude-module', 'matplotlib',
        '--exclude-module', 'scipy',
        '--exclude-module', 'setuptools',
        'player.pyw',
    ]
    subprocess.run(cmd, cwd=HERE, check=True)
    exe = HERE / 'dist' / (EXE_NAME + '.exe')
    shutil.rmtree(HERE / 'build', ignore_errors=True)
    (HERE / (EXE_NAME + '.spec')).unlink(missing_ok=True)
    print('\nbuilt %s  (%.1f MB)' % (exe, exe.stat().st_size / 1e6))
    return exe


def build_zip():
    check(SOURCE_FILES)
    out = HERE.parent / 'BanjoSoundLab-source.zip'
    out.unlink(missing_ok=True)
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in SOURCE_FILES:
            z.write(HERE / name, 'BanjoSoundLab/' + name)
    print('built %s  (%.0f KB)' % (out, out.stat().st_size / 1024))


if __name__ == '__main__':
    build_exe()
    if '--zip' in sys.argv:
        build_zip()
