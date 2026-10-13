# What the Windows driver package contains

Source: Lenovo catalog for machine type 21V8, `https://download.lenovo.com/catalog/21V8_Win11.xml`
(42 packages). Three camera packages downloaded, SHA256-verified against Lenovo's published
sums (`vendor/downloads/SHA256SUMS`). All are Inno Setup installers, unpacked with
`innoextract` (decompress only, nothing executed).

| package | title | verdict |
|---|---|---|
| `n4oce17w_v2.exe` | Intel MIPI Camera Driver | **this is ours** |
| `n4ocd07w.exe` | Integrated Camera Driver | Realtek + Sunplus UVC, other SKUs - irrelevant |
| `n4ocv01w.exe` | Camera + Computer Vision Firmware | Realtek + Sunplus UVC - irrelevant |

## Confirmed: TBE0020A0 is our sensor

`TBE0020A0.inf` binds `ACPI\TBE20A0`, exactly matching our kernel log
(`Found supported sensor TBE20A0:00`). DriverVer 03/07/2026, 71.26100.0.20574.
`TBE0020A0_extension_Lenovo.inf` names it "LENOVO Camera Front Extension", so TBE20A0 is
the front RGB camera.

Files of interest in `vendor/intel-mipi/code$GetExtractPath$/IPU_QS/`:

    TBE0020A0.sys                     sensor driver binary (mode tables, EEPROM logic)
    TBE0020A0_<MODULE>_PTL.aiqb       tuning blob, 5 files / 3 distinct
    TBE0020A0_<MODULE>_PTL.cpf        small HAL block, 248 B, 2 distinct
    graph_settings_TBE0020A0_<MODULE>_PTL.bin
    iaisp64.sys / iacamera64.sys / iactrllogic64.sys   Intel IPU7 stack
    intelic_data.bin, IntelDeviceMFT64.dll, libia_cp64.dll

MODULE is one of AAJH5-D, CBG802N3A, CBG802N3AP, CJFPE90, CJFPE90P. "PTL" = Panther Lake.
The P/non-P pairs are byte-identical, so there are three real tunings:

    AAJH5-D      349396 B   (also the odd one out on .cpf)
    CBG802N3A*   803574 B
    CJFPE90*     802686 B

## The .aiqb is a CPFF container and looks decodable

    00000000: 4350 4646 7e3f 0c00 ...   CPFF, size 0x0c3f7e
    00000010: ...       4c43 4d43 ...   LCMC
    00000020: ...       4446 4c54 ...   DFLT
    00000030: ...       4149 5142 ...   AIQB
    plus LTHR, LMOD, LAIQ

Tagged sections with sizes. **LCMC is almost certainly CMC (Camera Module
Characterization)** - in Intel's AIQ stack that is where colour matrices, black level and
lens shading live. Intel published the type definitions (`ia_cmc_types.h`) in the
open-source ipu6-camera-hal, so decoding this is a realistic prospect rather than blind
reverse engineering. This is the main lead for the libcamera tuning file.

## Per-unit calibration lives in an EEPROM on the module, not in the package

Strings in `TBE0020A0.sys` show the driver reads module data over i2c:

    [ReadModuleInfoFromEEPROM] MagicNumber / FormatVersion / Length / EEPROMFormat
    [GetModuleInfoOffsetInEEPROM] lsc_width x lsc_width, lsc_element_size, n_lights
    [GetModuleInfoOffsetInEEPROM] n_pos, vcm_bits, vcm_af_start/near/far/end
    [GetModuleInfoOffsetInEEPROM] Has PDAF data. (currently not supported!!!)

So **lens shading (LSC) is per-unit calibration stored in the module's EEPROM**, keyed by
illuminant (`n_lights`). The .aiqb carries the per-module-type tuning; the EEPROM carries
this sensor's own measured shading. A complete libcamera tuning wants both.

The module variant (which of the three tunings applies) is also identified from this EEPROM
- the .sys contains the strings CBG802N3A/CBG802N3AP/CJFPE90/CJFPE90P but notably **not**
AAJH5-D. Reading the EEPROM needs an i2c scan of bus 0 for the EEPROM address, which needs
root via camdbg.

## There is a second camera Linux never touches

    TBE20A0:00  status=15  \_SB_.LNK0  i2c-0   <- imx471 bound here
    TBE20A1:00  status=15  \_SB_.LNK1  i2c-1   <- nothing bound

Both ACPI devices report status 15 (present, enabled, functioning) and both have i2c
physical nodes, but the kernel logged "Connected 1 cameras". The package ships
`TBE0020A1.sys` and TBE0020A1 tunings for the same module vendors. Most likely the IR
camera used for Windows Hello. Out of scope for the image-quality work, but it is a real
Linux gap worth noting.

## Still unanswered

The INF does not list sensor modes - those are inside `TBE0020A0.sys`, which needs
disassembly to confirm whether Windows uses a wider/higher-resolution mode than our single
1928x1088. Max analogue gain likewise.

# The module EEPROM — read and decoded

`camdbg` installed, so the i2c side is now reachable.

## It only answers while the sensor is powered

An idle scan of i2c-0 shows nothing but `UU` at 0x1a (the bound imx471). The camera module
is unpowered at rest, so its EEPROM does not respond. Holding a stream open and rescanning:

    50: 50 -- -- -- ...        <- EEPROM at 0x50 on i2c-0, visible only while streaming

Any EEPROM access therefore has to run concurrently with an active stream.

## Size: 8 KB, of which 2320 bytes are used

Reading the full 16-bit address space returns 64 KB that mirrors at 8192, so the device is
8 KB and the rest is wrap-around. Within it, real data spans 0x0000..0x090f (2320 bytes);
everything after is 0xff. Note 0xfd (253) is a *value*, not padding — it is the table's
saturation cap.

## Layout: 40-byte header + 8 lens-shading planes

    40 + 8 planes x 15 rows x 19 cols x 1 byte = 2320 bytes   (exactly the data extent)

    header: 01 08 01 00 0a a4 01 46 01 64 00 84 03 02 bd 56 8e 54 13 0f 05 fd*5 c3 8c 71
            63 60 63 6e 8a c3 fd*5

Every plane minimises at (row 6, col 9) for planes 0-3 and (row 6, col 10) for planes 4-7 —
the optical centre, with the one-column shift between the two groups being the Bayer phase.
That is **4 Bayer channels x 2 illuminants**, consistent with the `n_lights` field the
driver's strings refer to.

Plane 0, centre rows, showing the radial bowl:

    253 253 217  72  46  29  16   8   3   1   3   7  14  26  42  66 113 253 253
    253 253 199  70  44  27  14   6   2   0   1   5  13  24  40  64 109 253 253
    253 253 207  72  46  29  16   8   3   2   3   7  14  26  42  65 115 253 253

Values run 0 at the optical centre up to the 253 cap at the edges, i.e. they are gain
*offsets* rather than absolute gains. The outermost two columns are 253 throughout, which
is consistent with the 19x15 grid spanning the full 4:3 array while we only read a 16:9
crop of it.

**This is this specific camera's own measured shading data** — exactly what libcamera needs
and cannot otherwise obtain, and better than a generic per-model table.

## Still open: which module variant

No ASCII module name appears anywhere in the EEPROM, so the `AAJH5-D` / `CBG802N3A` /
`CJFPE90` question is not answered this way. Either the 40-byte header encodes it
numerically, or it lives in the sensor OTP (the driver's strings mention both "Failed to
Read EEPROM data" and "Failed to Read OTP data"). The ACPI tables are now dumped to
`captures/acpi/` (30 SSDTs) and Lenovo's IpuSsdt SSDB is the other place to look.

# The .aiqb decoded

`tools/aiqb.py` parses the format. Structure, verified against Intel's own headers
(downloaded to `vendor/intel-headers/` from intel/ipu6-camera-bins,
`include/ipu6epmtl/ia_imaging/`):

    CPFF container, 4-char tag + u32 size, sections nested  L??? > DFLT > AIQB
    the AIQB block is an ia_mkn_header (24 B)
    followed by ia_mkn_record_header records (8 B):
        u32 size; u8 data_format_id; u8 key_id; u16 data_name_id
    data_name_id values are cmc_name_id from ia_cmc_types.h
    records are padded to 64-bit alignment

Top-level sections: LCMC (436096 B, 18 records), LAIQ (22432), LISP (343918), LTHR (216).

## Windows runs the sensor at 2328x1748, not 1928x1088

`cmc_name_id_general_data` decodes to:

    sensor native width x height : 2328 x 1748
    bit_depth                    : 10 (packed 10)
    color_order                  : 1 -> RGGB

and every tuning file's ProjectName is
`Lenovo_Avon_imx471_2328x1748_<MODULE>_PTL.IPU75XA`, tagged `[WFOV]` (wide FOV).

2328x1748 is exactly the full 2x2-binned frame (4656/2 x 3496/2). So Windows uses the
**whole** binned field; Linux's single mode takes a 1928x1088 crop of it.

    Linux   1928 x 1088 = 2.10 MP   82.8% of width, 62.2% of height
    Windows 2328 x 1748 = 4.07 MP   100% of both

Nearly double the pixels and the full field of view. This is hard evidence for adding a
mode to the kernel driver.

`color_order = RGGB` is also a third independent confirmation of the Bayer order, after the
red-can test and Gr==Gb.

## Colour correction matrices - 5 illuminants, extracted

`cmc_name_id_advanced_color_matrices` (4728 B) holds 5 light sources x 25 matrices
(1 base + 24 hue sectors). Record layout:

    12 B info (light_sources_count=5, sector_count=24)
    + 24 x u32 sector start hues (15,30,...,360)
    + 5 x [ u32 src_type; float chromaticity[2]; float src_cie_xy[2]; u32 cct;
            25 x float[9] ]
    = 12 + 96 + 5*924 = 4728   (exact)

Base CCM per illuminant:

| # | type | CCT | R/G | B/G | CIE x,y |
|---|---|---|---|---|---|
| 0 | 1  | 2694 K | 0.9011 | 0.3173 | 0.4610, 0.4120 |
| 1 | 12 | 2784 K | 0.8241 | 0.3263 | 0.4520, 0.4070 |
| 2 | 19 | 3615 K | 0.6522 | 0.4079 | 0.4020, 0.3960 |
| 3 | 4  | 4656 K | 0.5841 | 0.5149 | 0.3570, 0.3700 |
| 4 | 6  | 5694 K | 0.5043 | 0.6068 | 0.3280, 0.3440 |

    2694 K:  1.5632 -0.3171 -0.2461 / -0.4703  1.6967 -0.2264 /  0.0009 -0.9716  1.9707
    5694 K:  1.5414 -0.4120 -0.1293 / -0.2660  1.6099 -0.3438 / -0.0014 -0.5417  1.5431

Every row sums to exactly 1.0000 (the documented invariant), R/G falls and B/G rises
monotonically with CCT, and the CIE coordinates track the Planckian locus. These are sound
and directly usable in a libcamera tuning file.

### Cross-check against our own capture

Our room capture gives, with the 64-LSB pedestal removed, R/G = 0.712 and B/G = 0.398.
That sits between illuminant 1 (2784 K) and 2 (3615 K) on *both* ratios independently,
i.e. ~3400 K warm indoor light. Our raw pipeline and Intel's chromaticity data agree.

(An earlier figure of R/G = 0.840, B/G = 0.665 was wrong: `rawstat.py` was computing the
ratios without removing the pedestal, which on signals this dark badly compresses them and
made the two ratios imply different colour temperatures. Fixed.)

## Black level: 64, confirmed a fourth time

`cmc_name_id_black_level` holds four per-channel values as 16-bit fixed point:

    0x4007 0x4010 0x400b 0x4004  ->  /256 = 64.03, 64.06, 64.04, 64.02

0x4000 = 64.0 in 10-bit. Matches the measured p0.1 of ~64-66 and the "BLC64" note in the
tuning changelog.

## Optics

`cmc_name_id_optics_and_mechanics`: effective focal length 1.84 mm, pixel size quoted as
1.00 x 1.00 um, sensor total 2328 x 1748, no actuator (fixed focus, as expected).

Caution: the pixel size is the *native* 1.0 um while the frame is the *binned* 2328x1748,
so a FOV computed naively from these fields is wrong by 2x. Binned pixels are effectively
2.0 um, giving ~4.66 x 3.50 mm and a much wider FOV than the naive 64.6 deg. Do not quote
a FOV from these numbers without resolving that.

## Still to decode

`multi_gain_conversions` (184 B, num_gains=2) holds the analogue gain model - the thing
that would answer whether IMX471_ANA_GAIN_MAX = 800 is right, and would give libcamera its
missing CameraSensorHelper gain mapping. The struct uses pointer unions that are zeroed in
the file, so the arrays follow the 32-byte head and need their stride working out.
`lens_shading_correction_4x4` (213 KB) is also undecoded.

# The analogue gain model — decoded, and it exposes a kernel bug

`cmc_name_id_multi_gain_conversions` (184 B) decodes as `num_gains=2`: one analogue
(`gain_type=0`, segment-based) and one digital (`gain_type=1`, fixed-point). The pointer
unions are zeroed in the file; the arrays simply follow the 32-byte head and the two
40-byte `cmc_gain_conversion_t` structs, at record offset +112.

## Analogue: SMIA segment

    gain range : 1.0 .. 16.0
    code range : 0 .. 960, step 1
    M0=0  C0=1024  M1=-1  C1=1024

    gain(code) = (M0*code + C0) / (M1*code + C1) = 1024 / (1024 - code)

Self-consistent: 1024/(1024-960) = 16.0, exactly the declared `gain_end`.

## The Linux driver throws away 1.8 stops

| code | gain | |
|---|---|---|
| 0   |  1.00x | |
| 512 |  2.00x | |
| **800** | **4.57x** | **`IMX471_ANA_GAIN_MAX` in the Fedora driver** |
| 896 |  8.00x | |
| **960** | **16.00x** | **Intel's `code_max` for this exact module** |

`IMX471_ANA_GAIN_MAX = 800` limits analogue gain to 4.57x where Intel's tuning for this
same sensor, module and platform uses 960 for 16x. That is **log2(16/4.57) = 1.81 stops**
of low-light sensitivity discarded.

This is a direct contributor to the measured underexposure: AE had already pegged
`analogue_gain` at 800 and still could not expose the scene. Worth confirming there is no
deliberate reason for the 800 cap before patching, but Intel's own tuning is strong
evidence it is simply wrong.

## Digital gain

    gain_min=256  gain_max=2048  step=1  fraction_bits=8   ->  1.0x .. 8.0x

The Linux driver allows 256..4095 (1.0x..16.0x). A wider range than Intel uses, but
digital gain above 8x has no SNR value, so this is a difference rather than a defect.

## This hands libcamera its missing CameraSensorHelper

`ipa_soft_simple.so` registers `CameraSensorHelperImx219`, `Imx258`, `Imx290`, `Imx477`,
`Imx708` and ~25 others, but **no `Imx471`** — which is exactly the
"Failed to create camera sensor helper for imx471" warning.

libcamera's linear model is the same SMIA form, so the constants drop straight in. IMX219
is the precedent, using 256/(256-code); ours is 1024/(1024-code):

    gainType_ = AnalogueGainLinear;
    gainConstants_.linear = { 0, 1024, -1, 1024 };   /* m0, c0, m1, c1 */

That is a small, well-precedented libcamera patch, and it is what lets AE reason about the
exposure/gain trade-off instead of guessing.
