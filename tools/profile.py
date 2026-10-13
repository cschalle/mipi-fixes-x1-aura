import sys, numpy as np
W, H, STRIDE = 1928, 1088, 3904
FRAME = STRIDE * (H + 1)
def load(path):
    buf = np.fromfile(path, dtype=np.uint8)
    n = len(buf)//FRAME
    f = buf[FRAME*(n-1):][:FRAME]
    return f[:STRIDE*H].reshape(H, STRIDE)[:, :W*2].view(np.uint16).astype(np.float32), n
for path in sys.argv[1:]:
    px, n = load(path)
    print(f"\n===== {path.split('/')[-1]}  ({n} frames) =====")
    print(f"overall mean={px.mean():.1f} min={px.min():.0f} max={px.max():.0f} std={px.std():.1f}")
    g = px[0::2,1::2]                                  # one green plane
    cols = g.shape[1]//24
    prof = [g[:, i*cols:(i+1)*cols].mean() for i in range(24)]
    print("horizontal profile (24 buckets, green):")
    print("  " + " ".join(f"{v:5.0f}" for v in prof))
    rows = g.shape[0]//12
    vprof = [g[i*rows:(i+1)*rows, :].mean() for i in range(12)]
    print("vertical profile (12 buckets, green):")
    print("  " + " ".join(f"{v:5.0f}" for v in vprof))
    print(f"column-to-column variation: std of profile = {np.std(prof):.1f}")
