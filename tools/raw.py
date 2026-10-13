"""Shared raw-Bayer loader for the IPU7/IMX471 1928x1088 RG10 stream.

Geometry comes from v4l2: 1928x1088, stride 3904 (1928*2 = 3856 payload plus
48 bytes of line padding, measured as all-zero), 10-bit values in 16-bit LE
words, and Size Image = 3904*1089 so each buffer carries one spare line.
"""
import numpy as np

W, H, STRIDE = 1928, 1088, 3904
FRAME = STRIDE * (H + 1)
BLACK = 64                      # Sony 10-bit pedestal, measured p0.1 ~64-66
FULL = 1023

def frames(path):
    buf = np.fromfile(path, dtype=np.uint8)
    return len(buf) // FRAME, buf

def frame(path, idx=-1):
    n, buf = frames(path)
    if n == 0:
        raise SystemExit(f"{path}: no complete frames")
    i = n - 1 if idx < 0 else idx
    f = buf[FRAME * i:FRAME * (i + 1)]
    rows = f[:STRIDE * H].reshape(H, STRIDE)
    return rows[:, :W * 2].view(np.uint16).astype(np.float32), n

def positions(px):
    """The four Bayer positions, named by grid offset rather than by colour -
    naming them R/G/B would assume the answer we are trying to verify."""
    return {'(0,0)': px[0::2, 0::2], '(0,1)': px[0::2, 1::2],
            '(1,0)': px[1::2, 0::2], '(1,1)': px[1::2, 1::2]}
