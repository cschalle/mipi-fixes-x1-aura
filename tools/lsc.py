#!/usr/bin/python3 -I
"""Decode the lens shading grids from an Intel .aiqb.

Record cmc_name_id_lens_shading_correction_4x4 (name 28). The IPU6-era headers
in ia_cmc_types.h only name this enum without defining its struct, so the layout
below was derived from the data and then validated:

    record header                       54 bytes
    then 9 light-source sets, each:
        4 grids of 63x47 uint16         4 * 5922 bytes
        inter-set descriptor            22 bytes
            u32 index; float rg; float bg; 8 zero bytes; u16 next index

Values are Q5.11 fixed point: gain = value / 2048. Per the header comment these
are absolute gains over the full native FOV ("x% grid divided by
NVM_calibration_grid" - the EEPROM table is the per-unit ratio that divides it).

Validation: every one of the 36 grids has its minimum exactly at the grid centre
(23,31) with value 2048 = gain 1.000, and the two green channels agree to three
decimal places, which confirms the RGGB channel order.
"""
import numpy as np

W, H = 63, 47
NBYTES = W * H * 2
HDR = 54
SET = 4 * NBYTES + 22
NSETS, NCHAN = 9, 4
SCALE = 2048.0

def record_offset(buf):
    """Offset of the name-28 record inside the LCMC section."""
    import struct
    o = 0x38 + 24
    end = 0x38 + struct.unpack_from('<I', buf, 0x38 + 4)[0]
    while o + 8 <= end:
        size, fmt, key, name = struct.unpack_from('<IBBH', buf, o)
        if size < 8 or o + size > end:
            break
        if name == 28:
            return o
        o += (size + 7) & ~7
    raise SystemExit('lens shading record (name 28) not found')

def grids(path):
    """Return gains[set][channel] as a 47x63 float array of absolute gains."""
    buf = open(path, 'rb').read()
    base = record_offset(buf) + HDR
    out = np.empty((NSETS, NCHAN, H, W), dtype=np.float64)
    for s in range(NSETS):
        for c in range(NCHAN):
            off = base + s * SET + c * NBYTES
            out[s, c] = np.frombuffer(buf, dtype='<u2', count=W * H,
                                      offset=off).reshape(H, W) / SCALE
    return out

if __name__ == '__main__':
    import sys
    g = grids(sys.argv[1])
    print(f'{g.shape[0]} light sources x {g.shape[1]} channels, {W}x{H} grids')
    for s in range(g.shape[0]):
        ch = ', '.join(f'{g[s, c].max():.2f}' for c in range(NCHAN))
        print(f'  set {s}: centre={g[s,0,23,31]:.3f}  max gain per channel: {ch}')
