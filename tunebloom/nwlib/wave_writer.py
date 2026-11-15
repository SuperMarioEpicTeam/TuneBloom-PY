"""BFWAV writer following TuneBloom's WaveFile::doWrite/FileWriter layout."""
from __future__ import annotations

import struct
from .binary import BinaryFormatError, NintendoWareFile
from .dsp_adpcm import dsp_adpcm_bytes_for_buffer, get_dsp_adpcm_loop_context
from .dsp_encode import encode_dsp_adpcm

INFO_BLOCK_TYPE = 0x7000
DATA_BLOCK_TYPE = 0x7001
CHANNEL_INFO_TYPE = 0x7100
DSP_ADPCM_INFO_TYPE = 0x0300
BYTE_STREAM_TYPE = 0x1F00


def _align(value: int, alignment: int) -> int:
    return (value + alignment - 1) & ~(alignment - 1)


def _pack(fmt: str, *values: int, endian: str) -> bytes:
    return struct.pack(endian + fmt, *values)


def build_bfwav(
    channels: list[list[int] | tuple[int, ...]],
    sample_rate: int,
    encoding: int = 1,
    *,
    loop_enabled: bool = False,
    loop_start: int = 0,
    loop_end: int | None = None,
    endian: str = ">",
    encoded_dsp_channels: list[bytes] | None = None,
    dsp_parameters: list[tuple[tuple[tuple[int, int], ...], int, int, int, int, int, int]] | None = None,
) -> bytes:
    """Build a BFWAV using TuneBloom's two-block FWAV layout.

    PCM8 input values are signed -128..127; PCM16 and DSP ADPCM input values
    are signed -32768..32767. Channel samples are planar. DSP ADPCM is encoded
    independently per channel using TuneBloom's exact coefficient/quantizer
    algorithm. For lossless container conversion, callers may instead supply
    already encoded DSP frames and their original channel parameters; those
    bytes and predictor states are preserved without decoding/re-encoding.
    The result uses FWAV version 1.2.0, whose INFO includes the original-loop-
    start field written by TuneBloom.
    """
    if endian not in (">", "<"):
        raise BinaryFormatError("BFWAV endian must be '>' or '<'")
    if not 1 <= len(channels) <= 2:
        raise BinaryFormatError("TuneBloom supports BFWAV files with one or two channels")
    if sample_rate <= 0 or sample_rate > 0xFFFFFFFF:
        raise BinaryFormatError("Invalid BFWAV sample rate")
    if encoding not in (0, 1, 2):
        raise BinaryFormatError("BFWAV encoding must be PCM8 (0), PCM16 (1), or DSP ADPCM (2)")
    lengths = {len(channel) for channel in channels}
    if len(lengths) != 1 or not next(iter(lengths), 0):
        raise BinaryFormatError("All BFWAV channels must contain the same non-zero sample count")
    sample_count = next(iter(lengths))
    if encoded_dsp_channels is not None or dsp_parameters is not None:
        if encoding != 2 or encoded_dsp_channels is None or dsp_parameters is None:
            raise BinaryFormatError("Pre-encoded DSP data and parameters must be supplied together for DSP ADPCM")
        if len(encoded_dsp_channels) != len(channels) or len(dsp_parameters) != len(channels):
            raise BinaryFormatError("Pre-encoded DSP channel count does not match sample channels")
    loop_end = sample_count if loop_end is None else loop_end
    if not 0 <= loop_start < loop_end <= sample_count:
        raise BinaryFormatError("BFWAV loop range must satisfy 0 <= loop_start < loop_end <= sample count")
    if not loop_enabled:
        loop_start = 0
        loop_end = sample_count

    encoded_channels: list[bytes] = []
    adpcm_records: list[tuple[tuple[tuple[int, int], ...], int, int, int, int, int, int]] = []
    for channel_index, channel in enumerate(channels):
        if encoding == 0:
            if any(int(v) < -128 or int(v) > 127 for v in channel):
                raise BinaryFormatError(f"PCM8 channel {channel_index} contains a sample outside signed 8-bit range")
            encoded_channels.append(bytes(int(v) & 0xFF for v in channel))
        elif encoding == 1:
            if any(int(v) < -32768 or int(v) > 32767 for v in channel):
                raise BinaryFormatError(f"PCM16 channel {channel_index} contains a sample outside signed 16-bit range")
            encoded_channels.append(b"".join(_pack("h", int(v), endian=endian) for v in channel))
        else:
            padded_size = dsp_adpcm_bytes_for_buffer(sample_count)
            if encoded_dsp_channels is not None and dsp_parameters is not None:
                encoded = bytes(encoded_dsp_channels[channel_index])
                if len(encoded) != padded_size:
                    raise BinaryFormatError(
                        f"Pre-encoded DSP channel {channel_index} has {len(encoded)} bytes; {padded_size} required"
                    )
                record = dsp_parameters[channel_index]
                if len(record[0]) != 8:
                    raise BinaryFormatError(f"DSP channel {channel_index} must have eight coefficient pairs")
                encoded_channels.append(encoded)
                adpcm_records.append(record)
            else:
                result = encode_dsp_adpcm(channel)
                encoded_channels.append(result.data.ljust(padded_size, b"\0"))
                loop_ps, loop_yn1, loop_yn2 = get_dsp_adpcm_loop_context(
                    result.data, result.coefficients, result.predictor_scale,
                    result.yn1, result.yn2, loop_start,
                )
                adpcm_records.append((result.coefficients, result.predictor_scale, result.yn1,
                                      result.yn2, loop_ps, loop_yn1, loop_yn2))

    # INFO block body fixed header: encoding, loop flag, padding, sample rate,
    # loop start/end, and the original loop start (FWAV v1.2.0).
    info_body = bytearray()
    info_body += bytes((encoding, 1 if loop_enabled else 0)) + b"\0\0"
    info_body += _pack("IIII", sample_rate, loop_start, loop_end, loop_start, endian=endian)
    table_base = len(info_body)  # offset base is the reference-table count field
    info_body += _pack("I", len(channels), endian=endian)
    channel_ref_positions = []
    for i in range(len(channels)):
        channel_ref_positions.append(len(info_body))
        channel_info_offset = 4 + 8 * len(channels) + 20 * i
        info_body += _pack("HHi", CHANNEL_INFO_TYPE, 0, channel_info_offset, endian=endian)
    channel_info_starts = []
    for _ in channels:
        channel_info_starts.append(len(info_body))
        # Samples reference + AdpcmInfo reference + reserved u32.
        info_body += b"\0" * 20

    for i in range(len(channels)):
        channel_start = channel_info_starts[i]
        # Samples references are patched in DATA after the data block layout is known.
        sample_ref = channel_start
        # Reference offsets are relative to the start of the channel-info struct.
        info_body[sample_ref:sample_ref + 8] = _pack("HHi", BYTE_STREAM_TYPE, 0, 0, endian=endian)
        adpcm_ref = channel_start + 8
        if encoding == 2:
            adpcm_offset = len(info_body) - channel_start
            info_body[adpcm_ref:adpcm_ref + 8] = _pack("HHi", DSP_ADPCM_INFO_TYPE, 0, adpcm_offset, endian=endian)
            coefficients, pred_scale, yn1, yn2, loop_ps, loop_yn1, loop_yn2 = adpcm_records[i]
            for coef_pair in coefficients:
                info_body += _pack("hh", coef_pair[0], coef_pair[1], endian=endian)
            info_body += _pack("hhhhhhh", pred_scale, yn1, yn2, loop_ps, loop_yn1, loop_yn2, 0, endian=endian)
        else:
            info_body[adpcm_ref:adpcm_ref + 8] = _pack("HHi", 0, 0, -1, endian=endian)
    info_block_size = _align(8 + len(info_body), 0x20)
    info_block = bytearray(b"INFO" + _pack("I", info_block_size, endian=endian) + info_body)
    info_block.extend(b"\0" * (info_block_size - len(info_block)))

    # DATA block: samples references are relative to the DATA block body base.
    data_body = bytearray()
    data_body.extend(b"\0" * (_align(8, 0x20) - 8))
    data_body_base_pos = 8
    for i, sample_bytes in enumerate(encoded_channels):
        block_relative_pos = _align(8 + len(data_body), 0x20)
        data_body.extend(b"\0" * (block_relative_pos - (8 + len(data_body))))
        sample_relative = block_relative_pos - data_body_base_pos
        channel_start = channel_info_starts[i]
        info_body[channel_start:channel_start + 8] = _pack("HHi", BYTE_STREAM_TYPE, 0, sample_relative, endian=endian)
        data_body.extend(sample_bytes)
    # INFO block is already materialized; patch sample refs in its copy.
    info_block[8:8 + len(info_body)] = info_body
    data_block_size = 8 + len(data_body)
    data_block = b"DATA" + _pack("I", data_block_size, endian=endian) + bytes(data_body)

    header_size = _align(0x14 + 2 * 0x0C, 0x20)
    info_offset = header_size
    data_offset = info_offset + len(info_block)
    file_size = data_offset + len(data_block)
    header = bytearray(b"FWAV")
    header += b"\xfe\xff" if endian == ">" else b"\xff\xfe"
    header += _pack("HIIHH", header_size, 0x00010200, file_size, 2, 0, endian=endian)
    header += _pack("HHiI", INFO_BLOCK_TYPE, 0, info_offset, len(info_block), endian=endian)
    header += _pack("HHiI", DATA_BLOCK_TYPE, 0, data_offset, len(data_block), endian=endian)
    header.extend(b"\0" * (header_size - len(header)))
    result = bytes(header) + bytes(info_block) + data_block
    # Parse our own output before returning; this is a structural invariant.
    parsed = NintendoWareFile(result)
    if parsed.magic != "FWAV" or len(parsed.blocks) != 2:
        raise BinaryFormatError("Internal BFWAV writer validation failed")
    return result
