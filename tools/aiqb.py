#!/usr/bin/python3 -I
"""Parse an Intel .aiqb (CPFF container -> ia_mkn makernote -> CMC records).

Structure, verified against intel/ipu6-camera-bins headers:
  CPFF container: 4-char tag + u32 size, sections nested L??? > DFLT > AIQB
  AIQB block is an ia_mkn_header (24B): tag,size,system_version,enum_revision,
                                        config_bits,checksum
  then a stream of ia_mkn_record_header (8B):
      u32 size; u8 data_format_id; u8 key_id; u16 data_name_id
  data_name_id values are cmc_name_id (ia_cmc_types.h).
"""
import struct, sys

NAMES = {0:'reserved',1:'comment',2:'general_data',3:'black_level',
    4:'black_level_spatial',5:'saturation_level',6:'dynamic_range_and_linearity',
    7:'module_sensitivity',8:'defect_pixels',9:'noise',10:'lens_shading_correction',
    11:'lens_shading_correction_ratio',12:'geometric_distortion_correction',
    13:'optics_and_mechanics',14:'module_spectral_response',15:'chromaticity_response',
    16:'flash_chromaticity',17:'nvm_info',18:'color_matrices',
    19:'analog_gain_conversion',20:'digital_gain',21:'sensor_metadata',
    22:'geometric_distortion_correction2',23:'exposure_range',
    24:'multi_led_flash_chromaticity',25:'advanced_color_matrices',26:'hdr',
    27:'infrared_correction',28:'lens_shading_correction_4x4',
    29:'lateral_chromatic_aberration_correction',30:'phase_difference',
    31:'black_level_global',32:'valid_image_area',
    33:'lens_shading_correction_4x4_ratio',34:'multi_gain_conversions',
    35:'pipe_comp_decomp',36:'sensor_decomp',37:'media_format',38:'cbd'}

def sections(buf):
    """Yield (tag, offset, size) for top-level CPFF sections."""
    total, = struct.unpack_from('<I', buf, 4)
    o = 0x18
    while o + 8 <= min(total, len(buf)):
        tag = buf[o:o+4].decode('ascii', 'replace')
        size, = struct.unpack_from('<I', buf, o+4)
        if not tag.isalpha() or size < 8 or o + size > len(buf) + 16:
            break
        yield tag, o, size
        o += size

def records(buf, aiqb_off):
    """Walk ia_mkn records inside the AIQB block starting at aiqb_off."""
    hdr_size, = struct.unpack_from('<I', buf, aiqb_off + 4)
    end = min(aiqb_off + hdr_size, len(buf))
    o = aiqb_off + 24                      # past ia_mkn_header
    while o + 8 <= end:
        size, fmt, key, name = struct.unpack_from('<IBBH', buf, o)
        if size < 8 or o + size > end:
            break
        yield o, size, fmt, key, name
        o += (size + 7) & ~7               # records end on 64-bit alignment

if __name__ == '__main__':
    buf = open(sys.argv[1], 'rb').read()
    print(f"{sys.argv[1].split('/')[-1]}: {len(buf)} bytes\n")
    for tag, off, size in sections(buf):
        print(f"== section {tag} @0x{off:06x} size={size}")
        if tag == 'CPFF':
            continue
        # L??? > DFLT > AIQB, each 16 bytes further in
        aiqb = off + 32
        if buf[aiqb:aiqb+4] != b'AIQB':
            print("   (no AIQB block found)"); continue
        n = 0
        for ro, rs, fmt, key, name in records(buf, aiqb):
            label = NAMES.get(name, f'UNKNOWN({name})')
            print(f"   @0x{ro:06x} size={rs:7d} fmt={fmt:3d} key={key} "
                  f"name={name:3d} {label}")
            n += 1
        print(f"   -- {n} records\n")
