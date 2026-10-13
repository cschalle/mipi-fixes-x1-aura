# libcamera patches

Two changes to libcamera's software ISP, here backported to 0.7.1 so they can be
built as a Fedora package. Both were developed against master first.

    software_isp: Add lens shading correction
    software_isp: Normalise statistics sums to 8 bits

## Lens shading correction

The software ISP had no lens shading support for any sensor; upstream's TODO
lists it as unimplemented. This adds:

- a 17x17 gain grid per Bayer channel in `DebayerParams` (fixed size, because
  the struct is shared memory; 17x17 is what the rkisp1 hardware uses)
- a `LensShadingCorrection` IPA algorithm using the same tuning schema as the
  rkisp1, ipu3 and mali-c55 modules
- CPU debayer support, by transforming the lookup table index
  (`idx' = black + (idx - black) * gain`), which is exactly equivalent to
  applying the gain in linear space because the tables already fold black level,
  gains and gamma together. Gains are resampled once per line, leaving one
  multiply-add per channel in the inner loop
- GPU support, uploading the grid as a small 8-bit texture so `GL_LINEAR` does
  the bilinear interpolation in hardware

`lscEnabled` is a template parameter, so with lens shading off the branch
compiles out and the existing code path is unchanged.

The tuning data uses the **polynomial** form rather than tables: `LscTable`
cannot resample its grids for the sensor's analogue crop, and this sensor reads
out 3856x2176 of a 4656x3496 array. The polynomial form resamples correctly, and
it only knows the right rectangle because of kernel patch 0001.

## AWB statistics fix

`SwStatsCpu` accumulates per-channel sums in the sensor's native bit depth, but
`Awb::process` subtracts a black level held in a `uint8_t`. For a 10-bit sensor
black is under-subtracted by a factor of four, which inflates all three channels
by the same absolute amount and so pulls every gain towards unity.

On this camera the gains were 1.035/1.070 where grey world requires 1.316/1.806.
After the fix they are 1.283/1.760, and red/green at the output goes from 0.871
to 1.001 against a USB webcam reference of 0.99.

**This affects every RAW10 and RAW12 sensor using the software ISP**, not just
the IMX471, and is worth upstreaming on its own.

## Tuning file

`tuning/imx471.yaml` carries the black level, five lens shading sets and five
colour matrices spanning 2694K to 5694K, all extracted from Intel's Windows
driver package. Install it as:

    /usr/share/libcamera/ipa/simple/imx471.yaml      # libcamera 0.7.x
    /usr/share/libcamera/ipa/softisp/imx471.yaml     # libcamera master
