#!/usr/bin/python3 -I
"""Settle the Bayer order empirically from a capture of a known-red subject.

The driver claims MEDIA_BUS_FMT_SRGGB10_1X10, i.e. R at grid (0,0) and B at
(1,1). If R and B are actually swapped the order is SBGGR and every colour
matrix built on top of the claimed order would be wrong.
"""
import sys, numpy as np
sys.path.insert(0, '/home/cschalle/projects/mipi-camera/tools')
from raw import frame, positions, BLACK

path = sys.argv[1]
px, n = frame(path)
pos = positions(px)
H2, W2 = pos['(0,0)'].shape

# Locate the subject rather than averaging the whole scene: tile the frame and
# pick the tile with the largest spread between the two candidate colour
# positions, which is where the red object is most dominant.
TY, TX = 6, 6
best, bestscore = None, -1.0
for ty in range(TY):
    for tx in range(TX):
        ys, xs = slice(ty*H2//TY, (ty+1)*H2//TY), slice(tx*W2//TX, (tx+1)*W2//TX)
        a = max(pos['(0,0)'][ys, xs].mean() - BLACK, 0.0)
        b = max(pos['(1,1)'][ys, xs].mean() - BLACK, 0.0)
        score = abs(a - b) / max(min(a, b), 1.0)
        if score > bestscore:
            bestscore, best = score, (ys, xs, ty, tx)
ys, xs, ty, tx = best

print(f"{path.split('/')[-1]}: {n} frames, analysing last one")
print(f"subject tile: row {ty+1}/{TY}, col {tx+1}/{TX}\n")
for label, region in (("whole frame", (slice(None), slice(None))), ("subject tile", (ys, xs))):
    v = {k: max(p[region].mean() - BLACK, 0.0) for k, p in pos.items()}
    g = (v['(0,1)'] + v['(1,0)']) / 2
    print(f"--- {label} (black level {BLACK} removed) ---")
    for k in pos:
        print(f"    {k}: {v[k]:8.1f}")
    print(f"    green positions (0,1) vs (1,0): {v['(0,1)']:.1f} vs {v['(1,0)']:.1f} "
          f"(differ by {abs(v['(0,1)']-v['(1,0)'])/max(g,1)*100:.1f}%)")
    if label == "subject tile":
        hi, lo = v['(0,0)'], v['(1,1)']
        print(f"\n    (0,0)/green = {hi/max(g,1):.2f}   (1,1)/green = {lo/max(g,1):.2f}")
        ratio = hi / max(lo, 1.0)
        print(f"    (0,0)/(1,1) = {ratio:.2f}")
        print()
        # Two independent gates. A warm-lit ordinary scene already gives
        # (0,0)/(1,1) ~2.7 while (0,0)/green stays below 1, so the ratio alone
        # proves nothing. Demand that one candidate position actually EXCEEDS
        # green, which only a saturated red (or blue) subject can do.
        dom = max(hi, lo) / max(g, 1.0)
        if dom < 1.3:
            print(f"    VERDICT: INCONCLUSIVE - subject is not saturated enough.")
            print(f"             Brightest candidate position is only {dom:.2f}x green;")
            print(f"             a red subject filling the frame should exceed 1.3x.")
            print(f"             Hold the can closer, fill the frame, add light.")
        elif ratio > 3.0:
            print(f"    VERDICT: (0,0) is {ratio:.1f}x (1,1) and {hi/max(g,1):.2f}x green")
            print(f"             -> R sits at (0,0). SRGGB is CORRECT; driver agrees.")
        elif ratio < 0.33:
            print(f"    VERDICT: (1,1) is {1/ratio:.1f}x (0,0) and {lo/max(g,1):.2f}x green")
            print(f"             -> R sits at (1,1). Order is SBGGR;")
            print(f"                the driver's SRGGB claim is WRONG.")
        else:
            print(f"    VERDICT: INCONCLUSIVE - subject saturated ({dom:.2f}x green) but")
            print(f"             R/B separation is weak ({ratio:.2f}). Try a purer red.")
