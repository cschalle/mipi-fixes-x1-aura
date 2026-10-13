# libcamera side: state, results, and why the CCM is blocked

## Already upstream (master), not needed from us

libcamera master already carries two things 0.7.1 lacks, and they independently
corroborate our reverse engineering of Intel's tuning blob:

    CameraSensorHelperImx471:
        blackLevel_ = 4096;                            /* 64 DN at 10 bit */
        gain_ = AnalogueGainLinear{ 0, 1024, -1, 1024 };

Those are exactly the constants we decoded from the .aiqb independently. There is
also a `camera_sensor_properties.cpp` entry with the test pattern modes mapped
(`sensorDelays` is left empty, which is the one remaining warning).

## What is missing: a tuning file

Only `uncalibrated.yaml` ships. We generated `libcamera-work/imx471.yaml` from the
decoded CMC records: black level 4096 (16 bit units) plus five illuminant CCMs
from 2694 K to 5694 K. It parses, loads, and every matrix maps neutral to neutral
exactly (0.0% deviation), as a CCM must.

## Measured result: the CCM makes things worse, and that is informative

Interleaved A/B passes, repeatable to ~0.5%. "dev" is how far a white ceiling
patch sits from neutral; "skin sat" is saturation on a forehead patch.

| configuration             | dev   | skin sat |
|---------------------------|-------|----------|
| 0.7.1  uncalibrated       | 13.0% | 24-31%   |
| 0.7.1  + our CCM          | 78.1% | 93%      |
| master uncalibrated       | 23.3% | 31-34%   |
| master + our CCM          | 48.8% | 65%      |

Two negative results:

1. **The sensor helper did not improve white balance.** master is *worse* at
   neutral than 0.7.1 on this scene (23.3% vs 13.0%). The helper fixes AE's gain
   model, not AWB's accuracy.
2. **The CCM amplifies the existing cast.** A CCM boosts saturation; it cannot
   white balance, because it preserves neutral by construction. Applied on top of
   a pipeline that is already ~23% off neutral, it scales that error up.

## A false lead worth recording

Transposing the matrices appeared to fix it - master went to 11.9% dev, better
than the 23.3% uncalibrated baseline. It is wrong. The transposed matrix maps
neutral (1,1,1) to (1.2929, 0.4083, 1.2988), i.e. it suppresses green by 59%.
It only "improved" the number because it happened to cancel the pipeline's green
cast on that one scene. It would fail under different illumination and distorts
everything else. Discarded.

## The actual blocker

libcamera's software ISP has these algorithms and no others:

    adjust  agc  awb  blc  ccm

**There is no lens shading algorithm.** Two consequences:

- The per-unit LSC table we read out of the module EEPROM (19x15, 4 Bayer
  channels, 2 illuminants) **cannot currently be used**. Writing an LSC algorithm
  for the soft ISP is a prerequisite.
- Uncorrected vignetting leaves the frame periphery darker and colour shifted,
  which biases grey-world AWB statistics. master's AWB logs "No AWB algorithm
  specified, using grey world". That is very likely feeding the residual cast the
  CCM then amplifies.

## Recommendation

Do not ship `imx471.yaml` as it stands. The data in it is correct; it is arriving
ahead of the thing it depends on. Order of work:

1. Lens shading algorithm for the soft ISP, fed by the EEPROM table. Fixes
   vignetting directly and removes the main AWB bias at its source.
2. Re-measure AWB once shading is corrected.
3. Re-evaluate the CCM. It should become a net win once its input is neutral.

---

# Lens shading data: decoded from the .aiqb, not the EEPROM

## The EEPROM table was the wrong source

The 19x15 EEPROM table is real, but it is the *per-unit calibration ratio*, and
its encoding could not be solved: values run 0 at centre to a hard 253 at the
edges, and four flat-field attempts could not separate the lens falloff from the
illumination falloff of a close source on a ~95 degree lens. (Attempt 4 did give
a clean symmetric field, but its 55x centre-to-edge ratio is dominated by the
source geometry, not the lens.)

The header comment in ia_cmc_types.h explains the relationship:

    CMC_Lens Shading Correction
    - Full native FOV
    - Absolute gain values
    - x% grid "divided by" NVM_calibration_grid (=ratio) - if no NVM use ones

So the .aiqb carries the absolute gains and the EEPROM carries a per-unit ratio
that divides them. The absolute grid is what an LSC algorithm needs, and it can
be used on its own ("if no NVM use ones").

## Record 28 layout, derived and validated

The IPU6-era headers name `cmc_name_id_lens_shading_correction_4x4` (28) and
`..._4x4_ratio` (33) but do not define their structs, so the layout was derived
from the data:

    record header                   54 bytes
    9 light-source sets, each:
        4 grids of 63x47 uint16     4 x 5922 bytes
        inter-set descriptor        22 bytes
            u32 index; float rg; float bg; 8 zero bytes; u16 next index

    values are Q5.11: gain = value / 2048

Decoder: `tools/lsc.py`.

Three independent checks that the layout is right:

1. Every one of the 36 grids has its minimum exactly at the geometric centre
   (23,31) of the 47x63 grid, with value 2048, i.e. **gain exactly 1.000**.
2. The two middle channels agree to three decimal places (mean gain 3.507 vs
   3.505), which identifies them as the two greens and confirms RGGB order.
3. Channel falloff is ordered R > G > B (mean gain 3.869 / 3.507 / 3.505 /
   3.375), which is the physically expected behaviour.

## What it says about this camera

Within the 1928x1088 readout (grid cols 5.5..56.9, rows 8.1..36.7):

| channel | max gain needed | clipped at 7.0 |
|---------|-----------------|----------------|
| R       | 6.35x           | 0.0%           |
| Gr      | 5.49x           | 0.0%           |
| Gb      | 5.49x           | 0.0%           |
| B       | 5.27x           | 0.0%           |

Two things follow:

- **The corners are about 2.7 stops down.** That is severe, and it is the single
  largest image-quality defect found in this whole investigation.
- **R needs 6.35x where B needs 5.27x**, a 20% differential. Uncorrected, that
  produces a radial colour cast which biases grey-world AWB statistics - the
  mechanism behind the green cast that made the CCM look harmful.

The 7.0 clipping in the full grid is confined to the extreme corners of the 4:3
native FOV, which this 16:9 mode never reads out. **Nothing is clipped within
our crop**, so the data is complete for this resolution.

## Validation against measurement

Applying the decoded grid to the flat-field capture, by radial zone:

| chan | uncorrected centre/edge | LSC applied |
|------|------------------------|-------------|
| R    | 7.2x                   | 3.4x        |
| Gr   | 6.9x                   | 3.3x        |
| Gb   | 6.9x                   | 3.3x        |
| B    | 6.6x                   | 3.2x        |

It halves the falloff, consistently across all four channels. It does not flatten
completely, and should not be expected to: the residual ~3.3x is the close-range
source's own geometry, which no sensor-side correction can remove. The right
confirmation would be a large evenly lit wall at ~1 m, which fills the field of
view without contributing its own falloff.

---

# LSC implementation for the software ISP

Implemented in the libcamera master checkout (`libcamera/`), 12 files,
+270/-104. It builds clean and does not regress the existing paths.

## What was written

**`DebayerParams`** carries a fixed 17x17 gain grid per Bayer channel (~4.7 kB).
Fixed size because the struct is a `SharedMemObject`; 17x17 is what the rkisp1
hardware uses for the same job. `width == 0` disables it, so sensors without
shading data are untouched.

**`LensShadingCorrection`** (`src/ipa/softisp/algorithms/lsc.{h,cpp}`) is built on
libipa's shared `LscAlgorithm`, the same one rkisp1, ipu3 and mali-c55 use, so it
reuses their tuning file parsing, colour temperature interpolation and crop
resampling, and uses the same YAML schema. Gains are written with 1024 as unity
(`UQ<6, 10>`), matching the rkisp1 tuning files.

**`lscEnabled`** is plumbed exactly as the existing `ccmEnabled` is: set by the
algorithm, returned from the IPA over IPC, handed to the backend at configure
time so the template variant is chosen once.

**The CPU debayer** applies it by transforming the lookup table index:

    idx' = black + (idx - black) * gain

Shading is a gain on signal above black level, and the tables already fold
black level -> gains -> gamma, so transforming the index is exactly equivalent
without needing per-pixel gamma maths. Gains are resampled once per line, not
per pixel, leaving one multiply-add per channel in the inner loop. The rows live
on `DebayerCpuThread` because debayering is multi threaded. `lscEnabled` is a
template parameter, so with LSC off the branch compiles out entirely.

## Tuning file

`tools/gen-tuning.py` generates `libcamera-work/imx471.yaml` from the .aiqb:
black level, five lens shading sets, five colour matrices. Shading sets are
matched to CCM illuminants by chromaticity (distances 0.011 to 0.052) so both
use a consistent set of light sources. Verified: 289 values per grid, centre gain
exactly 1.000.

## Two blockers, neither of them this code

### 1. The CPU debayer segfaults, in upstream master

Forcing `software_isp.mode = cpu` crashes immediately. Bisected by stashing all
of the above and rebuilding: **pristine libcamera master segfaults identically**.
This is a pre-existing upstream bug, not a regression from this work, and it is
plausibly unnoticed because the GPU path is the default wherever EGL is
available.

It does block measuring the CPU implementation, since that is the only path that
currently consumes the gain map.

### 2. Tabular LSC does not resample for the analogue crop

    WARN LscTable: Tabular LSC data doesn't support resampling

`LscTable::sampleForCrop()` returns its data unchanged and warns. That matters
specifically for this sensor: it reads a 3856x2176 crop of a 4656x3496 array, so
a full-array grid *must* be resampled onto the crop or the correction is applied
at the wrong scale. Only the polynomial form (`type: polynomial`) resamples.

Since the shading here is a smooth radial falloff, fitting polynomials to the
decoded grids should work well, and is the correct form for any sensor that
crops. That is the next change to make.

## What is known to work

With the tuning file loaded on the GPU path, the IPA parses and runs without
error ("Using table-based Lsc", no grid errors, correct interpolation setup).
The EGL backend accepts `lscEnabled` and ignores the grid, so there is no visible
change yet - the shader implementation is still outstanding.

## Polynomial conversion (resolves blocker 2)

`LscPolynomial` evaluates

    gain(x, y) = 1 + sum_i k_i * r^(2i+2),  i = 0..4

with r measured from (cx, cy) and normalised so the corner of the reference
image is 1.0. Tuning entries are `cx, cy, k0..k4` per component.

`tools/gen-tuning.py` now fits that model to the decoded 63x47 grids by linear
least squares, excluding points pinned at the 7.0 encoding ceiling since those
are clamped rather than measured. Fit residuals, as RMS gain error:

| region | RMS | worst case |
|--------|-----|-----------|
| whole active array | 0.08 - 0.15 | up to 1.74 |
| within the 1928x1088 readout | **0.05 (~2.2%)** | **0.27** |

The large worst-case errors are all in the extreme corners of the 4:3 array,
outside what this 16:9 mode reads. Within the actual readout the model holds to
about 2%, i.e. a few percent error on a correction of up to 6.35x. Good enough,
and the only form that resamples.

Confirmed at runtime: "Using polynomial Lsc", and the
"doesn't support resampling" warning is gone, so the grids are now being sampled
for the sensor's analogue crop as intended. The tuning file also drops from 47 kB
to 5.4 kB and is far easier to read.

## Remaining work

1. The upstream CPU debayer segfault, which blocks measuring the correction.
2. The EGL shader, which is the default path and currently ignores the grid.

Neither is in the LSC code itself: the IPA half parses, fits the crop,
interpolates by colour temperature and publishes the gain grid correctly.

## EGL shader implementation, and the measurement

The gain grid is uploaded as a 17x17 8 bit RGB texture on texture unit 7, with
gains stored as (gain - 1) / scale and `scale` passed as a uniform, so no float
texture extension is needed - the shader environment is `#version 100`, i.e.
GLES2. GL_LINEAR does the bilinear interpolation between grid nodes in hardware.
The shader applies it immediately after black level removal and before white
balance, guarded by `#define LSC_ENABLED`, so builds without shading data are
unchanged.

Quantising against the measured range rather than a fixed maximum keeps the step
at about 0.02 for a 6.35x corner gain, well under the ~2% error already present
in the polynomial fit.

### Results

| configuration | vignetting (centre/corner) | neutral dev | skin sat |
|---------------|---------------------------|-------------|----------|
| baseline      | 2.75x                     | 22.3%       | 20.4%    |
| **LSC only**  | **1.30x**                 | 22.8%       | 20.1%    |
| LSC + CCM     | 1.33x                     | 53.9%       | 47.0%    |

**Lens shading correction works.** Centre-to-corner falloff drops from 2.75x to
1.30x, corners nearly doubling in brightness. This is the largest image quality
improvement found in the whole investigation, and it is now applied by the
default GPU path.

### The AWB hypothesis was wrong

Earlier it was argued that uncorrected shading was biasing grey-world AWB, and
that this was why the CCM looked harmful. That is now disproven: with shading
corrected, the neutral deviation is unchanged (22.3% -> 22.8%). The colour cast
has some other cause, and the CCM still roughly doubles it.

So the CCM remains unsuitable for shipping, and the reason is still open. Likely
candidates are the grey-world AWB implementation itself, or the missing
`colourGains` tuning parameter it warns about. That is the next thing to
investigate, and it is now cleanly separable from shading.

## Correction: the colour cast was unconverged AWB, not a real cast

Logging the AWB gains showed them still climbing frame to frame:

    gains R=1.126 B=1.275   temp 3895K
    gains R=1.226 B=1.495   temp 3896K
    gains R=1.307 B=1.669   temp 3903K

From the channel means (R 19.78, G 32.23, B 13.63) grey-world needs R 1.63 and
B 2.37. The algorithm is damped and had not reached them. Every colour
measurement above this section was taken on 5 to 12 frame captures, i.e. before
AWB settled, and is therefore invalid.

Repeated with 60 frame captures:

| configuration | vignetting | neutral dev (was) |
|---------------|-----------|-------------------|
| baseline      | 2.74x     | **3.7%** (22.3%)  |
| LSC only      | 1.29x     | 4.3% (22.8%)      |
| LSC + CCM     | 1.31x     | **7.1%** (53.9%)  |

What survives and what does not:

- **Lens shading correction still works**, and is unaffected: 2.74x -> 1.29x.
  That measurement never depended on AWB convergence.
- **The green cast was an artefact of short captures.** There is no large cast to
  explain, and the earlier hypothesis that shading was biasing AWB was testing
  something that did not exist.
- **The CCM verdict needs redoing.** It still roughly doubles the neutral
  deviation (3.7% -> 7.1%), but both figures are now small, and a white ceiling
  under warm light is not a true grey card, so a well-formed CCM can legitimately
  move it. Judging this properly needs a known neutral target rather than a wall.

The skin saturation column was dropped from these runs: the sample region was
chosen around a face that is no longer in the same place, so it no longer
measures what it was named for.

Lesson for any future measurement here: let AWB converge, and verify convergence
from the logged gains rather than assuming it.

## The CCM is correct; the neutral test was the wrong test

Two checks, neither needing a reference target.

**1. The matrices preserve neutral, as their construction requires.** Feeding a
perfect neutral through the 3900 K interpolated matrix:

    0.2 -> [0.199995 0.200000 0.200000]   deviation 0.0018%
    0.5 -> [0.499986 0.500000 0.500000]   deviation 0.0018%
    0.8 -> [0.799978 0.800000 0.800000]   deviation 0.0018%

Rows sum to 1.0000, so neutral in gives neutral out to within rounding.

**2. The measured change is exactly what the matrix predicts.** Taking the
LSC-only capture, linearising out the shader's gamma, applying the same
interpolated matrix and re-encoding:

    measured before CCM : R=0.4799 G=0.4687 B=0.4483   dev 4.3%
    PREDICTED after CCM : R=0.4891 G=0.4689 B=0.4357   dev 7.1%
    measured after CCM  : R=0.4875 G=0.4659 B=0.4326   dev 7.1%
    prediction error    : 0.8/255

So the CCM is doing precisely what the arithmetic says it should.

### What this means

The deviation grew from 4.3% to 7.1% because **the patch was not neutral going
in**. A CCM increases saturation; applied to an input that is 4.3% off neutral it
produces an output further off neutral. That is unavoidable and correct
behaviour for any well-formed CCM, not a defect.

The earlier verdict - "the CCM makes the image worse, do not ship it" - was
measuring AWB's residual error, not the CCM. **That verdict is withdrawn.**

What these checks do not establish is whether the matrices improve colour
*accuracy*; a neutral patch cannot answer that, because every neutral-preserving
matrix passes it. Answering that needs known colour references. But the blocker
is gone: the data is Intel's own characterisation of this sensor and module, it
is mathematically sound, and it behaves as designed on real captures.

---

# AWB investigation: grey-world does not neutralise its own output

Starting point: the USB webcam reference reads R/G 0.99, B/G 0.97 on a white
surface; the MIPI camera reads R/G 0.865, B/G 0.62. The yellow-green cast is a
white balance error, not shading and not the colour matrix.

## The colour matrix is not at fault

Logged at runtime with a *valid* tuning file, the matrix reaching the shader is

    [ 2.10926  -0.430557  -0.229396 ]
    [ -0.415762  1.54725  -0.39345  ]
    [ 0.000115  -0.572568  2.60024  ]

which is exactly CCM(4400K) x diag(1.343, 1.0, 1.654), i.e. the AWB gains are
correctly folded in and the right colour temperature is selected. Feeding it the
AWB-neutral raw ratios returns (1.001, 0.999, 1.000). The CCM is correct.

An earlier measurement here claimed "CCM only -> B/G 0.065, the CCM destroys
blue". That test file had no `Awb` section: the variant was produced by slicing
the YAML between the shading and matrix sections, and `Awb` sat between them. The
conclusion drawn from it was wrong and is withdrawn.

Similarly, the earlier claim that lens shading shifts colour balance does not
hold up. Measured properly, LSC is colour neutral (B/G 0.835 -> 0.830 encoded).

## What is actually wrong

Measured in linear space (gamma 0.4545 confirmed at runtime, contrastExp 1 so
the contrast curve is identity):

| tuning       | linear R/G | linear B/G |
|--------------|-----------|------------|
| none (stock) | 0.842     | **0.696**  |
| LSC only     | 0.874     | 0.687      |
| LSC + CCM    | 0.757     | 0.460      |

The first row is the stock code path with no tuning data, so this is not
something this work introduced.

Grey-world computes, from raw Bayer statistics with black level removed,

    gain_B = (sumG - blackLevel * N) / (sumB - blackLevel * N)

and the shader computes

    out_B = (raw_B / 255 - 0.0627) * gain_B

Those compose to a linear mean ratio of exactly 1.0. The measured value is 0.696,
a systematic shortfall of about 1.44x in blue.

Ruled out so far: gain clamping (the 4.0 clamp is never reached, gains settle at
1.343 / 1.654); a sample-count mismatch between the Y histogram and the channel
sums used for the black level offset (both are incremented in the same loop);
lens shading; the colour matrix; and the contrast curve.

Still open: where the factor enters between the statistics and the output. The
sensor test pattern, which the kernel patch in this project repaired, would make
a good instrument here - it provides a known input with exact expected ratios,
removing all scene ambiguity.

## Correction: the gains themselves are correct

Computing grey-world directly from a clean raw capture and comparing against what
the IPA logged:

    grey-world from raw : gain_R = 1.256   gain_B = 1.632
    AWB logged          : gain_R = 1.236   gain_B = 1.591

They agree to within 3%, the remainder being scene drift between the two
captures. So AWB is computing the right gains from the right statistics, and
those gains are correctly folded into the matrix that reaches the shader (shown
above). Two of the three links in the chain are verified sound.

Note on method: two earlier attempts at this comparison were invalid because the
sensor was still in test pattern mode. A `--set-ctrl test_pattern=0` issued while
libcamera held the device silently did not take, so the "raw" captures were
colour bars. The signature was R and B means being exactly equal with green
clipped. Always read the control back after setting it.

## What remains unexplained

Within a single capture, the linear output ratio is B/G 0.696 where the applied
gains should produce 1.0. Ruled out: gain clamping, histogram/sum sample
mismatch, lens shading, the colour matrix, the contrast curve (contrastExp is 1),
and highlight or shadow clipping (excluding clipped and floored pixels moves the
figure only from 0.696 to 0.687).

The gap is between "the gains are right" and "the output is not neutral", and the
remaining candidate is the statistics being gathered over a different population
than the output frame - the stats sample every other 2x2 block within a window,
while the measurement covers the full frame. Confirming that needs the raw frame
and the gains from the *same* run, which is the next thing to measure.
