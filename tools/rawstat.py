import sys, numpy as np
path, W, H, STRIDE = sys.argv[1], 1928, 1088, 3904
FRAME = STRIDE * (H + 1)                      # Size Image = 4251456 = 3904*1089
buf = np.fromfile(path, dtype=np.uint8)
n = len(buf) // FRAME
print(f"file={len(buf)} bytes  frames={n}  frame={FRAME}")
for idx in (0, n - 1):                        # first vs last (AE settled)
    f = buf[idx*FRAME:(idx+1)*FRAME]
    rows = f[:STRIDE*H].reshape(H, STRIDE)
    px   = rows[:, :W*2].view(np.uint16).astype(np.float32)   # 10-bit in 16-bit LE
    pad  = rows[:, W*2:]
    ch = {'R ':px[0::2,0::2], 'Gr':px[0::2,1::2], 'Gb':px[1::2,0::2], 'B ':px[1::2,1::2]}
    print(f"\n--- frame {idx} ---  overall min={px.min():.0f} max={px.max():.0f} mean={px.mean():.1f}")
    print(f"    line padding ({pad.shape[1]}B/line): min={pad.min()} max={pad.max()}")
    for k, v in ch.items():
        p = np.percentile(v, [0.1, 1, 50, 99, 99.9])
        print(f"    {k}: min={v.min():6.0f} p0.1={p[0]:6.0f} p1={p[1]:6.0f} "
              f"med={p[2]:6.0f} p99={p[3]:6.0f} p99.9={p[4]:6.0f} max={v.max():6.0f} mean={v.mean():7.1f}")
    # Black level MUST come off before any ratio: the 64-LSB pedestal is a large
    # fraction of these very dark signals and compresses the ratios badly.
    BL = 64
    r = ch['R '].mean()-BL; g = (ch['Gr'].mean()+ch['Gb'].mean())/2-BL; b = ch['B '].mean()-BL
    print(f"    white balance (black level removed): R/G={r/g:.3f}  B/G={b/g:.3f}")
    print(f"    10-bit range used: {px.max()/1023*100:.1f}% of full scale")
    sat = (px >= 1020).mean()*100; blk = (px <= 64).mean()*100
    print(f"    pixels at/near saturation(>=1020): {sat:.3f}%   at/below 64: {blk:.3f}%")
