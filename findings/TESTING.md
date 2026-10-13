# Before/after test record

BEFORE captured on the stock Fedora kernel, with the patched kernel building.
Artifacts in `captures/before/`.

## Kernel under test

    before: 7.2.8-200.fc44.x86_64            (stock)
    after : 7.2.8-200.imx471fix.fc44.x86_64  (3 patches, built from the Fedora SRPM)

## Patch 1 - V4L2_SEL_TGT_CROP

BEFORE (`captures/before/selection.txt`):

    crop           VIDIOC_SUBDEV_G_SELECTION: failed: Invalid argument
    crop_bounds    Left 8,  Top 8,   Width 4656, Height 3496
    crop_default   Left 8,  Top 8,   Width 4656, Height 3496
    native_size    Left 0,  Top 0,   Width 4672, Height 3512

Three targets work, CROP alone fails. EXPECTED AFTER: crop returns
Left 424, Top 624, Width 3856, Height 2176.

libcamera BEFORE (`captures/before/libcamera.txt`):

    ERROR V4L2 'imx471 0-001a': Unable to get rectangle 0 on pad 0/0: Invalid argument
    WARN  CameraSensor 'imx471 0-001a': Failed to retrieve the sensor crop rectangle
    WARN  CameraSensor 'imx471 0-001a': The sensor kernel driver needs to be fixed
    WARN  CameraSensor 'imx471 0-001a': The analogue crop rectangle has been defaulted
                                        to the active area size

EXPECTED AFTER: these four lines gone. The remaining warnings (no static
properties, no imx471.yaml, no sensor helper) are the libcamera half and will
stay until that work is done.

### Note: v4l2-compliance does NOT catch this

`v4l2-compliance -d /dev/v4l-subdev4` reports **46/46 passed, 0 failed** on the
*buggy* kernel, because it reads the EINVAL as the driver legitimately not
offering the target:

    test Cropping: OK (Not Supported)

So compliance is not proof of the bug. The signal to watch is that line
changing from "Not Supported" to supported after the fix. The direct ioctl
failure above is the real evidence.

## Patch 2 - test pattern

BEFORE (`captures/before/testpattern-2.bin`): with test_pattern=2 ("Eight
Vertical Colour Bars") the capture is still the live scene - smooth horizontal
profile, no bar structure, mean 121.8:

    83 89 94 113 142 165 162 151 149 136 112 127 147 137 152 165 161 176 ...

EXPECTED AFTER: eight flat-topped bands (white, yellow, cyan, green, magenta,
red, blue, black). This also gives us an instrument to re-confirm Bayer order
independently of the red-can test.

## Patch 3 - analogue gain

BEFORE: control range `analogue_gain: min=0 max=800`, i.e. 4.57x ceiling.
Reference capture at the old maximum (`captures/before/ref-gain800.bin`):

    R  med=112  Gr med=134  Gb med=134  B med=88
    white balance (black level removed): R/G=0.689  B/G=0.355

EXPECTED AFTER: range becomes max=960; setting code 960 should give 16.0x,
i.e. 3.5x more signal than code 800. The gain law was already measured over
0..800 and matched 1024/(1024-code) to within a few percent.

## Build verification

The build tree's `drivers/media/i2c/imx471.c` is byte-identical to our patched
mainline file; all three changes confirmed present (ANA_GAIN_MAX 960,
CCI_REG16 test pattern, crop rect + `return 0`).

---

# AFTER: results on 7.2.8-200.imx471fix.fc44.x86_64

All three patches verified on the affected hardware.

## Patch 1 - V4L2_SEL_TGT_CROP: PASS

    BEFORE  crop  VIDIOC_SUBDEV_G_SELECTION: failed: Invalid argument
    AFTER   crop  Left 424, Top 624, Width 3856, Height 2176

Exactly the value derived from the mode register sequence. `media-ctl -p` now
reports `crop:(424,624)/3856x2176` in the topology where it previously showed
only `crop.bounds`.

libcamera: all four crop complaints gone, including "The sensor kernel driver
needs to be fixed" and both `ERROR V4L2 ... Unable to get rectangle` lines. The
five remaining warnings are the libcamera-side gaps (static properties, sensor
delays, imx471.yaml, sensor helper) and are unaffected by kernel changes.

## Patch 2 - test pattern: PASS

With `test_pattern=2` the sensor now emits a real pattern instead of the live
scene. Per Bayer position, across the frame:

    bars   R     G     B      colour
    0-1    1023  1023  1023   white
    3-4    1023  1023  0      yellow
    5-6    0     1023  1023   cyan
    7      0     1023  0      green

White, yellow, cyan, green is the standard colour bar order, and it only reads
that way if (0,0) is red. **This independently confirms SRGGB from the sensor's
own reference pattern** - the most authoritative of the four confirmations
(red-can test, Gr==Gb, Intel's `color_order = 1 = RGGB`, and now this).

Only the first four bars are visible because the pattern spans the full array
while the mode reads out a crop of it.

## Patch 3 - analogue gain: PASS

Control range is now `analogue_gain: min=0 max=960`, and libcamera sees it:

    IPASoft: Exposure 1-1290, gain 0-960 (1)

Measured, median of the green channels with black level removed:

    code	predicted	measured
       0	  1.000x	  1.000x
     512	  2.000x	  2.000x
     800	  4.571x	  4.571x
     960	 16.000x	 16.071x

960 over the old 800 ceiling: measured 3.48x, predicted 3.50x. The 16x endpoint
is now measured rather than inferred from vendor data, and the commit message
has been updated to drop that caveat.

## Note: a false alarm worth recording

After the reboot, STREAMON failed with -EPIPE and this initially looked like a
regression from the patches. It was not. A fresh boot leaves the pipeline
unconfigured - the video node defaults to 1920x1080 BG12 and the CSI2 pads to
SGRBG10_1X10/4096x3072, none of which match the sensor's 1928x1088 SRGGB10, so
`link_validate` in ipu7-isys-video.c correctly rejects the pipeline. Before the
reboot the pipeline had been configured by an earlier libcamera run and that
subdev state had persisted.

Running libcamera once (`cam -c1 --capture=2`) configures it, after which raw
v4l2 captures work. Kernel config was also compared: ours differs from stock in
16 lines, all BTF/debuginfo and BUILD_SALT, nothing camera related.
