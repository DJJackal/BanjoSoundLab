"""VADPCM decoder (Nintendo 64 nine-byte / sixteen-sample ADPCM frames).

The stored codebook holds `order` rows of eight coefficients per predictor.
Decoding expands each predictor into an 8 x (order + 8) matrix so that every
sample in a half-frame can be produced from the history plus the residuals
that precede it, which is how the N64 audio library does it.
"""
import numpy as np

FRAME_BYTES = 9
FRAME_SAMPLES = 16

_NIBBLE = np.array([v - 16 if v >= 8 else v for v in range(16)], dtype=np.int32)


def expand_book(book: np.ndarray, order: int) -> np.ndarray:
    """book: (npredictors, order, 8) int16 -> (npredictors, 8, order + 8) int64."""
    npred = book.shape[0]
    out = np.zeros((npred, 8, order + 8), dtype=np.int64)
    for p in range(npred):
        te = out[p]
        for j in range(order):
            for k in range(8):
                te[k][j] = int(book[p][j][k])
        for k in range(1, 8):
            te[k][order] = te[k - 1][order - 1]
        te[0][order] = 1 << 11
        for k in range(1, 8):
            for j in range(k):
                te[j][k + order] = 0
            for j in range(k, 8):
                te[j][k + order] = te[j - k][order]
    return out


def decode(data: bytes, book: np.ndarray, order: int = 2) -> np.ndarray:
    """Decode VADPCM bytes into int16 PCM."""
    if book is None:
        return np.frombuffer(data, dtype='>i2').astype(np.int16)
    table = expand_book(book, order).copy()
    # Row i must not consume its own residual here; it is added separately
    # after the shift, exactly as the audio library does.
    for _i in range(8):
        table[:, _i, order + _i] = 0
    npred = table.shape[0]
    nframes = len(data) // FRAME_BYTES
    if nframes == 0:
        return np.zeros(0, dtype=np.int16)

    raw = np.frombuffer(data[:nframes * FRAME_BYTES], dtype=np.uint8)
    raw = raw.reshape(nframes, FRAME_BYTES)
    headers = raw[:, 0].astype(np.int32)
    shifts = headers >> 4
    preds = np.minimum(headers & 0x0F, npred - 1)

    packed = raw[:, 1:].astype(np.int32)
    nib = np.empty((nframes, 16), dtype=np.int32)
    nib[:, 0::2] = _NIBBLE[packed >> 4]
    nib[:, 1::2] = _NIBBLE[packed & 0x0F]
    ix_all = nib << shifts[:, None]

    state = np.zeros(16, dtype=np.int64)
    out = np.empty(nframes * FRAME_SAMPLES, dtype=np.int64)
    in_vec = np.zeros(order + 8, dtype=np.int64)

    # Columns beyond `order + i` of row i are zero by construction, so the whole
    # half-frame is one matrix-vector product.
    for f in range(nframes):
        ix = ix_all[f].astype(np.int64)
        tab = table[preds[f]]
        for half in (0, 1):
            top = 16 if half == 0 else 8
            in_vec[:order] = state[top - order:top]
            in_vec[order:] = ix[half * 8:half * 8 + 8]
            state[half * 8:half * 8 + 8] = (tab.dot(in_vec) >> 11) + in_vec[order:]
        out[f * FRAME_SAMPLES:(f + 1) * FRAME_SAMPLES] = state
    return np.clip(out, -32768, 32767).astype(np.int16)
