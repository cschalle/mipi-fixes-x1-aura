#!/usr/bin/python3 -I
"""Generate a libcamera softisp tuning file for the IMX471 from Intel's .aiqb.

Lens shading grids are resampled from the 63x47 CMC grids onto the 17x17 grid
the software ISP uses, and written with 1024 representing unity gain, the same
convention the rkisp1 tuning files use. Colour correction matrices come from the
advanced_color_matrices record. Shading sets are matched to CCM illuminants by
chromaticity so the two use a consistent set of light sources.
"""
import struct, sys
import numpy as np
sys.path.insert(0, '/home/cschalle/projects/mipi-camera/tools')
import lsc

GRID = 17
UNITY = 1024.0
ACTIVE_W, ACTIVE_H = 4656, 3496   # imx471 active pixel array


def fit_polynomial(grid):
    """Fit gain = 1 + sum(k[i] * r^(2i+2)) with r normalised so the active
    array corner is 1.0, which is the model libipa's LscPolynomial evaluates.

    Points pinned at the 7.0 encoding ceiling are excluded: they are clamped
    rather than measured, and including them drags the fit.
    """
    h, w = grid.shape
    X, Y = np.meshgrid(np.linspace(0, 1, w), np.linspace(0, 1, h))
    m = np.hypot(ACTIVE_W / 2, ACTIVE_H / 2)
    R = np.hypot(ACTIVE_W * (X - 0.5), ACTIVE_H * (Y - 0.5)) / m

    mask = grid < 6.99
    A = np.stack([R[mask] ** (2 * (i + 1)) for i in range(5)], axis=1)
    k, *_ = np.linalg.lstsq(A, grid[mask] - 1.0, rcond=None)
    resid = (1.0 + A @ k) - grid[mask]
    return k, float(np.sqrt((resid ** 2).mean()))

def ccms(buf):
    o = 0x38 + 24
    end = 0x38 + struct.unpack_from('<I', buf, 0x38 + 4)[0]
    while o + 8 <= end:
        size, fmt, key, name = struct.unpack_from('<IBBH', buf, o)
        if size < 8 or o + size > end:
            break
        if name == 25:
            ls, sec = struct.unpack_from('<HH', buf, o + 8)
            p = o + 12 + 4 * sec
            out = []
            for _ in range(ls):
                chrom = struct.unpack_from('<2f', buf, p + 4)
                cct, = struct.unpack_from('<I', buf, p + 20)
                p += 24
                out.append((cct, chrom, struct.unpack_from('<9f', buf, p)))
                p += 36 * (sec + 1)
            return out
        o += (size + 7) & ~7
    raise SystemExit('colour matrices not found')

def shading_chromaticities(buf):
    o = lsc.record_offset(buf)
    out = [struct.unpack_from('<2f', buf, o + 36)]
    for s in range(1, lsc.NSETS):
        gap = o + lsc.HDR + s * lsc.SET - 22
        out.append(struct.unpack_from('<2f', buf, gap + 4))
    return out

def resample(g):
    """63x47 -> GRIDxGRID, bilinear, over the same full-array extent."""
    h, w = g.shape
    yy = np.linspace(0, h - 1, GRID)
    xx = np.linspace(0, w - 1, GRID)
    y0 = np.clip(yy.astype(int), 0, h - 2); x0 = np.clip(xx.astype(int), 0, w - 2)
    fy = (yy - y0)[:, None]; fx = (xx - x0)[None, :]
    a = g[y0][:, x0]; b = g[y0][:, x0 + 1]
    c = g[y0 + 1][:, x0]; d = g[y0 + 1][:, x0 + 1]
    return a * (1 - fy) * (1 - fx) + b * (1 - fy) * fx + c * fy * (1 - fx) + d * fy * fx

def table(vals):
    out = []
    flat = (vals * UNITY).round().astype(int).ravel()
    for i in range(0, len(flat), GRID):
        out.append('              ' + ', '.join(f'{v:5d}' for v in flat[i:i + GRID]) + ',')
    body = '\n'.join(out)
    return '[\n' + body.rstrip(',') + ' ]'

path = sys.argv[1]
buf = open(path, 'rb').read()
grids = lsc.grids(path)
sc = shading_chromaticities(buf)
cm = ccms(buf)

# pair each CCM illuminant with the shading set of nearest chromaticity
pairs = []
for cct, chrom, mat in cm:
    d = [np.hypot(chrom[0] - s[0], chrom[1] - s[1]) for s in sc]
    pairs.append((cct, int(np.argmin(d)), mat, min(d)))

L = []
L.append('# SPDX-License-Identifier: CC0-1.0')
L.append('%YAML 1.1')
L.append('---')
L.append('# Sony IMX471 as fitted to the Lenovo ThinkPad X1 Carbon Gen 14.')
L.append('#')
L.append('# Black level is the sensor pedestal of 64 DN at 10 bits, in the 16 bit')
L.append('# units the BlackLevel algorithm expects (64 << 6).')
L.append('#')
L.append('# Lens shading gains use 1024 for unity, as the rkisp1 tuning files do.')
L.append('# The grids cover the full active pixel array; libipa resamples them for')
L.append('# whatever the sensor reports as its analogue crop.')
L.append('#')
L.append('# Colour matrices are applied after white balance and each row sums to')
L.append('# one, so a neutral input stays neutral.')
L.append('version: 1')
L.append('algorithms:')
L.append('  - BlackLevel:')
L.append('      blackLevel: 4096')
L.append('  - LensShadingCorrection:')
L.append('      # Polynomial rather than tabular: LscTable cannot resample its')
L.append('      # grids for the sensor\'s analogue crop, and this sensor reads')
L.append('      # out 3856x2176 of its 4656x3496 array.')
L.append('      type: polynomial')
L.append('      sets:')
fits = []
for cct, idx, _, dist in pairs:
    L.append(f'        - ct: {cct}')
    for key, ch in (('r', 0), ('gr', 1), ('gb', 2), ('b', 3)):
        k, rms = fit_polynomial(grids[idx][ch])
        fits.append((cct, key, rms))
        L.append(f'          {key}:')
        L.append( '            cx: 0.5')
        L.append( '            cy: 0.5')
        for i in range(5):
            L.append(f'            k{i}: {k[i]:.6f}')
L.append('  - Awb:')
L.append('  - Ccm:')
L.append('      ccms:')
for cct, _, m, _ in pairs:
    L.append(f'        - ct: {cct}')
    L.append(f'          ccm: [ {m[0]: .4f}, {m[1]: .4f}, {m[2]: .4f},')
    L.append(f'                 {m[3]: .4f}, {m[4]: .4f}, {m[5]: .4f},')
    L.append(f'                 {m[6]: .4f}, {m[7]: .4f}, {m[8]: .4f} ]')
L.append('  - Adjust:')
L.append('  - Agc:')
L.append('...')
open(sys.argv[2], 'w').write('\n'.join(L) + '\n')
print('pairing of CCM illuminant -> shading set (by chromaticity distance):')
for cct, idx, _, dist in pairs:
    print(f'  {cct:5d}K -> shading set {idx}  (distance {dist:.4f})')
print('polynomial fit residuals (RMS gain error over the active array):')
for cct, key, rms in fits:
    print(f'  {cct:5d}K {key:>2}: {rms:.4f}')
