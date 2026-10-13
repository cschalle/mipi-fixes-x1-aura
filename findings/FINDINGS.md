# IPU7 + IMX471 camera diagnosis — ThinkPad X1 Carbon Gen 14

Host: Fedora 44, kernel 7.2.8-200.fc44. Hardware: Intel IPU7 (8086:b05d, PCI 00:05.0),
Sony IMX471 at i2c 0-001a, 4 CSI-2 lanes on port 0, ACPI id `TBE20A0:00`.

## Provenance: the sensor driver is Fedora-downstream, not upstream

`drivers/media/i2c/imx471.c` **does not exist in the 7.2.8 upstream tarball**. It is carried
only in `patch-7.2-redhat.patch`, added by Kate Hsuan <hpa@redhat.com> explicitly for this
laptop. The IPU7 driver is in `drivers/staging/media/ipu7/` and logs
"module is from the staging directory". Relevant Fedora changelog entries:

    media: i2c: imx471: Add Sony IMX471 image sensor driver (Kate Hsuan)
    media: ipu-bridge: Add Sony IMX471 for Lenovo X1 Carbon G14 (Kate Hsuan)
    platform: int3472: discrete: con_id vana for Sony IMX471 as power enable (Kate Hsuan)
    media: i2c: imx471: Fix uninitialized error value in imx471_set_ctrl() (David Carlier)

So a Fedora kernel patch is the right vehicle, and the driver is new enough to be incomplete
in identifiable ways.

## Defect 1 (kernel, confirmed): V4L2_SEL_TGT_CROP returns -EINVAL

`imx471_get_selection()` uses `break` where every other case uses `return 0`:

    case V4L2_SEL_TGT_CROP:
            sel->r = *v4l2_subdev_state_get_crop(sd_state, sel->pad);
            break;              /* falls out of switch -> return -EINVAL */

libcamera reports this directly:

    ERROR V4L2 'imx471 0-001a': Unable to get rectangle 0 on pad 0/0: Invalid argument
    WARN CameraSensor 'imx471 0-001a': Failed to retrieve the sensor crop rectangle
    WARN CameraSensor 'imx471 0-001a': The sensor kernel driver needs to be fixed
    WARN CameraSensor 'imx471 0-001a': The analogue crop rectangle has been defaulted
                                       to the active area size

Consequence: libcamera believes readout covers the full 4656x3496 active area when it is
actually a 3856x2176 window. Lens-shading geometry, FOV metadata and ScalerCrop maths are
all computed against the wrong rectangle.

## Defect 2 (kernel, confirmed): the crop rectangle is never populated

`v4l2_subdev_state_get_crop` appears exactly **once** in the 957-line driver — the read in
`get_selection` above. Nothing ever writes it. `imx471_init_state()` only calls
`imx471_set_pad_format()`, which sets format and never touches crop.

So the stored crop is zero-initialised. **Fixing defect 1 alone is not enough** — it would
return a degenerate 0x0 rectangle, which is arguably worse than the error. The patch must
also populate crop.

True analogue crop, derived from `mode_1928x1088_regs`:

    X_ADD_STA=8     X_ADD_END=4647   -> readout 4640 wide
    Y_ADD_STA=408   Y_ADD_END=3051   -> readout 2644 tall
    X/Y_EVEN_INC = X/Y_ODD_INC = 1   -> no subsampling
    BINNING_MODE=1, BINNING_TYPE=0x22 -> 2x2  -> binned frame 2320 x 1322
    DIG_CROP_X_OFFSET=208, DIG_CROP_Y_OFFSET=108, 1928 x 1088

    => analogue crop = (8 + 208*2, 408 + 108*2) / (1928*2) x (1088*2)
                     = (424, 624) / 3856 x 2176

Roughly centred (centre 2351,1712 vs array centre 2328,1748).

## Defect 3 (kernel, confirmed by measurement): test pattern is a no-op

    #define IMX471_REG_TEST_PATTERN   CCI_REG8(0x0600)

On Sony IMX sensors `TEST_PATTERN_MODE` at 0x0600 is a 16-bit field. An 8-bit write puts the
value in the high byte, so mode 2 becomes 0x0200 — not a valid mode. The driver uses
`CCI_REG16` correctly for every other 16-bit Sony field (0x0202 exposure, 0x0204 gain,
0x0340 FLL, 0x020e digital gain); 0x0600 is the lone outlier.

Verified empirically: setting `test_pattern=2` both before streaming and mid-stream leaves
the output identical in shape to the live scene (same horizontal profile, same bright spot
in bucket 19). The control reads back as 2 while having no effect.

## Defect 4 (userspace): no libcamera support data for imx471

    WARN CameraSensorProperties  No static properties available for 'imx471'
    WARN CameraSensor            No sensor delays found in static properties.
                                 Assuming unverified defaults.
    WARN IPAProxy                Configuration file 'imx471.yaml' not found for IPA module
                                 'simple', falling back to '.../simple/uncalibrated.yaml'
    WARN IPASoft                 IPASoft: Failed to create camera sensor helper for imx471

`/usr/share/libcamera/ipa/simple/` contains only `uncalibrated.yaml`. There is no CCM, no
lens-shading table, no black-level, no gamma tuning, and no gain-code<->gain model.

## The image is ~3.8 stops underexposed, with the sensor already maxed out

Raw capture off /dev/video0 (RG10, 1928x1088, stride 3904, 10-bit in 16-bit LE):

    black level  : min 62, p0.1 ~64-66   (Sony 64-LSB pedestal present, as expected)
    median       : R 113   Gr 135   Gb 135   B 89
    after -64    : R  49   G   71         B  25   out of a 959 usable range
    => median green at 7.4% of full scale (~3.8 stops under)
    p99 green 347 (29% of scale); only 0.58% of pixels at/near saturation
    raw channel means: R/G = 0.840, B/G = 0.665
    Gr == Gb to within 0.3% (consistent Bayer phase; 48B/line padding is all zero)

## Bayer order: SRGGB CONFIRMED (not merely consistent)

Defect 3 blocks the colour-bar test, so verified physically instead with a saturated red
subject (Coca-Cola Zero can, filling the frame, held close). Subject tile, black level
removed:

    (0,0) = 33.9   (0,1) = 15.9   (1,0) = 15.4   (1,1) = 4.0
    (0,0)/green = 2.17        (0,0)/(1,1) = 8.45

Red sits at grid (0,0), so `MEDIA_BUS_FMT_SRGGB10_1X10` is correct. The two green
positions track each other to 3%. A colour matrix built on the claimed order is safe.

Note the test needs both gates: an ordinary warm-lit room gives (0,0)/(1,1) = 2.69 while
(0,0)/green stays at 0.89, so the R/B ratio alone would "confirm" SRGGB against any scene.
Requiring the dominant position to exceed green is what makes it a real test.

## No exposure headroom remains anywhere

The red-can capture was taken with the sensor fully maxed out -- `exposure = 1290` (max),
`analogue_gain = 800` (max), `digital_gain = 256` (1.0x, untouched), `vblank = 220`
(minimum, i.e. 52.5 fps). Under those conditions a *saturated red object filling the frame*
put its red channel at only 33.9 above black, i.e. **3.5% of the 959-count usable range**;
green sat at 1.6%.

Caveat: the can also shadowed the scene (whole-frame green fell from 80.8 to 27.5 versus the
room shot), so this is not a calibrated bright target and the 3.5% figure is not purely a
sensor-side failure. The room capture -- median green at 7.4% with only 0.58% of pixels near
saturation -- remains the cleaner evidence. What the can shot adds is that the sensor was
already pinned at maximum exposure and maximum analogue gain while imaging it. Trading frame
rate for integration time via VBLANK is the only real lever, and userspace is not pulling
it.

Control state during capture: `exposure = 1290` (its maximum) and `analogue_gain = 800`
(its maximum), while `digital_gain = 256` (1.0x, untouched).

**The exposure ceiling is a userspace failure, not a kernel limit.** The kernel's VBLANK
logic is correct: VBLANK ranges 220..64447 and raising it correctly extends exposure_max to
`height + vblank - 18`. At the default VBLANK of 220:

    line time   = llp 2328 / 160 MHz          = 14.55 us
    frame       = 2328 x 1308                 = 52.5 fps
    exposure max = 1088 + 220 - 18 = 1290 lines = 18.8 ms

Dropping to 30 fps (VBLANK 1203) would allow 33 ms — +0.8 stop. VBLANK can reach 64447,
i.e. ~950 ms. libcamera is leaving VBLANK at the 52 fps default and then running out of
analogue gain, which is exactly what defect 4's missing sensor helper would cause.

## Single mode, and ~17% of horizontal FOV discarded

`imx471_modes[]` has exactly one entry: 1928x1088, fll 1308, llp 2328. From a 4656x3496
(16 MP) array we get 2.1 MP, using 82.8% of width and 62.2% of height. The vertical crop is
inherent to 16:9 from a 4:3 array, but the horizontal crop is not — a full-width 2x2-binned
mode (4656 -> 2328 x 1310, still 16:9) would be both wider and higher-resolution.
Worth measuring Windows' FOV against this.

## Open questions

- `IMX471_ANA_GAIN_MAX = 800`. If the Sony formula is 1024/(1024-code) that is only 4.57x.
  Needs a datasheet or Windows cross-check to know whether the cap is correct.
- `intel-ipu7 0000:00:05.0: Failed to get runtime PM` fires on every resume from suspend
  (6 of 6 cycles this boot), immediately before `PM: suspend exit`. Cause unknown.
- CONFIG_VIDEO_ADV_DEBUG is not set, so sensor registers cannot be read via
  VIDIOC_DBG_G_REGISTER; only forced i2c, or a custom kernel build.
