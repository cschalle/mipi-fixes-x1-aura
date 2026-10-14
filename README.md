# MIPI camera fixes for the ThinkPad X1 Carbon Gen 14 (Aura Edition)

Kernel and libcamera fixes for the integrated camera on the Lenovo ThinkPad X1
Carbon Gen 14 — a Sony **IMX471** behind an **Intel IPU7**, where all image
processing is done by libcamera's software ISP.

Out of the box the camera is dark, heavily vignetted and has a strong
yellow-green cast. This repository contains the fixes, the measurements behind
them, and the tooling used to find them.

**Project page with before/after images:** https://cschalle.github.io/mipi-fixes-x1-aura/

## What was wrong, and what each fix does

| # | Component | Problem | Effect |
|---|-----------|---------|--------|
| 1 | kernel, `imx471` | `V4L2_SEL_TGT_CROP` ended its case with `break` and fell through to `return -EINVAL`, and no crop rectangle was ever stored | libcamera could not learn the readout geometry and assumed the full pixel array |
| 2 | kernel, `imx471` | `TEST_PATTERN_MODE` declared `CCI_REG8` when 0x0600 is a 16-bit register | test pattern generator produced nothing |
| 3 | kernel, `imx471` | `IMX471_ANA_GAIN_MAX` capped at 800 | 4.57x analogue gain instead of the sensor's 16x — 1.8 stops of sensitivity lost |
| 4 | libcamera, software ISP | no lens shading correction existed at all | corners ~2.7 stops down; vignetting 2.78x |
| 5 | libcamera, software ISP | AWB statistics summed in the sensor's native bit depth while the black level subtracted from them was 8-bit | black under-subtracted 4x, pulling every white balance gain towards unity |

A sixth issue is documented but **not fixed here**, and it is userspace, not
the driver: libcamera leaves the sensor's vertical blanking at its 220-line
minimum (52.5 fps), which pins exposure at 1290 lines / 18.8 ms. The kernel
side is correct — vblank ranges 220..64447 and raising it properly extends
`exposure_max` — but libcamera's simple pipeline never pulls that lever. In a
dim room auto-exposure saturates at that ceiling *and* the full 16x gain and
still falls ~4x short of a USB webcam. Dropping to 30 fps would buy ~0.8 stop.

Fix 5 is **not IMX471 specific** — it affects every RAW10/RAW12 sensor using
libcamera's software ISP.

## Measured results

Channel ratios at the output, against a USB webcam on the same machine as a
reference. 1.000 is neutral.

A controlled low-light pair — same seat, same lamps, laptop not moved, stock
side recaptured on a stock kernel with stock libcamera reinstalled, both held
400 frames so AGC and AWB fully settled. Measured on a flat painted ceiling at
identical coordinates in both frames:

| Configuration | R/G | B/G | frame brightness |
|---------------|-----|-----|------------------|
| stock | 0.890 | 0.672 | 31.1 |
| all five fixes | **1.047** | 0.823 | **90.9** |
| USB webcam reference | 1.052 | 0.989 | — |

Measured AWB gains in that scene were `1.098 / 1.220` stock against
`1.387 / 2.260` fixed — fix 5 visible directly.

In brighter light, with the vignetting column from the controlled flat-field pair:

| Configuration | R/G | B/G | vignetting |
|---------------|-----|-----|-----------|
| stock | 0.871 | 0.667 | 2.78x |
| + lens shading | 0.974 | 0.855 | **1.09x** |
| + AWB fix and colour matrix | **1.001** | **0.870** | 1.09x |
| USB webcam reference | 0.99 | 0.97 | — |

Blue remains ~17% short in low light. That residue is a grey-world AWB
limitation, and the colour matrix amplifies it rather than causing it: blue
measures 0.910 with the matrix disabled and 0.823 with it enabled, against
0.838 predicted from the 3615K blue row.

## Layout

    kernel/patches/      three patches against mainline, ready for linux-media
    libcamera/patches/   lens shading + AWB fix, backported to libcamera 0.7.1
    libcamera/tuning/    imx471.yaml: black level, lens shading, colour matrices
    tools/               the analysis scripts used throughout
    findings/            the full investigation, including the wrong turns
    docs/                project page (GitHub Pages)

Prebuilt RPMs for Fedora 44 are attached to the
[releases](../../releases) rather than committed here.

## Where the tuning data came from

The lens shading grids and colour matrices were extracted from Intel's Windows
camera driver package, which ships per-module tuning blobs in a CPFF container.
`tools/aiqb.py` and `tools/lsc.py` decode them; `findings/WINDOWS-DRIVER.md`
documents the format, which the publicly available ipu6-camera-bins headers only
partially describe.

Independent confirmation that the decoding is right: libcamera master already
carries a `CameraSensorHelperImx471` with `gain = 1024 / (1024 - code)` and a
black level of 64 DN, arrived at separately, and both match what was decoded
here.

## Status

The kernel patches are tested on hardware and ready to send to linux-media. The
libcamera work is tested as a Fedora package; the lens shading feature and the
AWB fix are both candidates for upstream, and the AWB fix is worth sending on its
own since it is not specific to this sensor.

## Credit

The IMX471 driver and its IPU7 bridge support were written by Kate Hsuan
<hpa@redhat.com>. These are fixes on top of that work.
