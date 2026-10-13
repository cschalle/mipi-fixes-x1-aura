# Analysis tools

Scripts used to investigate the camera. They assume the 1928x1088 RG10 stream
this sensor produces; `raw.py` holds the geometry in one place.

    raw.py           shared loader: stride 3904, 10 bits in 16-bit LE words
    capraw           capture raw frames, recording the control state alongside
    rawstat.py       per-Bayer-channel histogram statistics
    bayer-check.py   determine Bayer order from a saturated red subject
    topng.py         render raw captures to viewable PNGs
    profile.py       horizontal and vertical profiles, for spotting structure
    camshot          capture through libcamera with a chosen tuning file
    aiqb.py          parse Intel .aiqb files (CPFF container, CMC records)
    lsc.py           decode the lens shading grids from an .aiqb
    gen-tuning.py    build a libcamera tuning file from an .aiqb

A capture is meaningless without the controls that produced it, so `capraw`
always writes a `.meta` file beside the data.

Two things worth knowing before using these:

**Let AWB converge.** libcamera's grey world AWB is damped and needs roughly 60
frames to settle. Shorter captures produce colour measurements that look like
real casts but are not. Verify convergence from the logged gains rather than
assuming it.

**Read controls back after setting them.** A `--set-ctrl` issued while libcamera
holds the device can silently fail. The giveaway for a sensor stuck in test
pattern mode is red and blue means being exactly equal.
