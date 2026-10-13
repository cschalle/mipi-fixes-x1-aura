#!/usr/bin/python3 -I
"""Render a raw Bayer capture to viewable PNGs.

Bayer order is SRGGB (verified empirically, see FINDINGS.md), so each 2x2 block
gives R at (0,0), two greens at (0,1)/(1,0) and B at (1,1). Binning those to one
RGB pixel is a half-resolution but artifact-free alternative to a real demosaic
- fine for judging framing and colour, and it invents nothing.

Writes two files on purpose:
  -linear.png    black level removed, one fixed scale factor, no gamma.
                 Shows the TRUE brightness the sensor delivered. Looks black.
  -viewable.png  grey-world white balance, autoscaled, sRGB gamma.
                 What a working pipeline would roughly show.
"""
import sys, numpy as np
from PIL import Image
sys.path.insert(0, '/home/cschalle/projects/mipi-camera/tools')
from raw import frame, BLACK, FULL

src = sys.argv[1]
stem = src.rsplit('.', 1)[0]
px, n = frame(src)

# 2x2 bin -> RGB planes
R = px[0::2, 0::2]
G = (px[0::2, 1::2] + px[1::2, 0::2]) / 2.0
B = px[1::2, 1::2]
rgb = np.clip(np.dstack([R, G, B]) - BLACK, 0, None)
h, w, _ = rgb.shape
print(f"{src.split('/')[-1]}: {n} frames -> {w}x{h} RGB (2x2 binned)")
print(f"  channel means (black level removed): R={R.mean()-BLACK:.1f} "
      f"G={G.mean()-BLACK:.1f} B={B.mean()-BLACK:.1f}")

# --- linear: true brightness, no gamma, no WB ---
lin = np.clip(rgb / (FULL - BLACK) * 255.0, 0, 255).astype(np.uint8)
Image.fromarray(lin).save(f"{stem}-linear.png")

# --- viewable: grey-world WB, autoscale to the 99.5th pct, sRGB gamma ---
means = rgb.reshape(-1, 3).mean(axis=0)
wb = rgb * (means.mean() / np.maximum(means, 1e-6))
scale = np.percentile(wb, 99.5)
norm = np.clip(wb / max(scale, 1e-6), 0, 1)
srgb = np.where(norm <= 0.0031308, norm * 12.92,
                1.055 * np.power(norm, 1 / 2.4) - 0.055)
Image.fromarray((srgb * 255).astype(np.uint8)).save(f"{stem}-viewable.png")

print(f"  white balance gains applied: "
      f"R={means.mean()/means[0]:.2f} G={means.mean()/means[1]:.2f} B={means.mean()/means[2]:.2f}")
print(f"  autoscale: 99.5th percentile = {scale:.0f} of {FULL-BLACK} "
      f"({scale/(FULL-BLACK)*100:.1f}% of range) -> digital boost {(FULL-BLACK)/max(scale,1):.1f}x")
# --- nowb: no white balance, just autoscale + gamma ---
# Grey-world is actively misleading on a strongly coloured subject: it drags the
# frame mean toward neutral and desaturates the very thing under test.
scale2 = np.percentile(rgb, 99.5)
n2 = np.clip(rgb / max(scale2, 1e-6), 0, 1)
s2 = np.where(n2 <= 0.0031308, n2 * 12.92, 1.055 * np.power(n2, 1 / 2.4) - 0.055)
Image.fromarray((s2 * 255).astype(np.uint8)).save(f"{stem}-nowb.png")
print(f"  wrote {stem}-linear.png, {stem}-viewable.png, {stem}-nowb.png")
