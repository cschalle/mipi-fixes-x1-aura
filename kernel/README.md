# Kernel patches

Three fixes to `drivers/media/i2c/imx471.c`, against mainline. The driver is
upstream as of v7.3; these apply cleanly to it and to the Fedora 7.2.8 package,
whose copy is byte-identical.

    0001  Fix V4L2_SEL_TGT_CROP returning -EINVAL
    0002  Fix test pattern register width
    0003  Raise the analogue gain limit to the sensor maximum

`0000-cover-letter.patch` is the series cover letter.

## Applying

    git am kernel/patches/000[123]-*.patch

Or into a Fedora kernel SRPM, by concatenating them into the
`linux-kernel-test.patch` source that the spec already applies:

    cat kernel/patches/000[123]-*.patch > ~/rpmbuild/SOURCES/linux-kernel-test.patch

## Verification

Each patch was tested on the affected hardware:

**Crop.** Before, `VIDIOC_SUBDEV_G_SELECTION` failed with `Invalid argument` for
`crop` while `crop_bounds`, `crop_default` and `native_size` all worked. After,
it returns `(424, 624)/3856x2176`, which matches the mode's register sequence:
readout rows 408..3051 and columns 8..4647, binned 2x2, then digitally cropped
1928x1088 at (208,108). libcamera's four complaints about the crop rectangle
disappear.

Note that `v4l2-compliance` passes 46/46 both before and after: it reads the
`EINVAL` as the driver legitimately not offering the target, and reports
`test Cropping: OK (Not Supported)`. It is not a useful detector for this bug.

**Test pattern.** Before, selecting a pattern changed nothing: the control read
back correctly while the output stayed a live scene. After, the generator
produces colour bars. The bar order also independently confirms the SRGGB Bayer
order the driver advertises.

**Analogue gain.** The gain law is `gain = 1024 / (1024 - code)`, verified on
hardware against the median of the green channels:

    code    predicted   measured
       0      1.000x      1.000x
     512      2.000x      2.000x
     800      4.571x      4.571x
     960     16.000x     16.071x

The previous limit of 800 therefore gave up 1.8 stops.
