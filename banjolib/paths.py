"""Where things live, whether running from source or from the packaged exe."""
import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, 'frozen', False))


def resource_dir() -> Path:
    """Read-only files shipped with the program."""
    if FROZEN:
        return Path(getattr(sys, '_MEIPASS'))
    return Path(__file__).resolve().parent.parent


def app_dir() -> Path:
    """The folder the program itself sits in."""
    if FROZEN:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """Somewhere writable for the extracted library.

    Next to the program when that is writable, so the whole thing stays
    self-contained and portable; otherwise the usual per-user location, which
    is what happens if someone drops the exe in Program Files.
    """
    base = app_dir()
    probe = base / '.write-test'
    try:
        probe.write_bytes(b'')
        probe.unlink()
        return base
    except OSError:
        fallback = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'BanjoSoundLab'
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback
