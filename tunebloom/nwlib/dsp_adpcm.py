"""Nintendo DSP ADPCM decoder ported from TuneBloom's dsp/decode.cpp.

NintendoWare DSP ADPCM stores 14 signed samples per 8-byte frame.  The
predictor/scale nibble and history update order intentionally match the C++
implementation supplied with TuneBloom.
"""
from __future__ import annotations

from .binary import BinaryFormatError

SAMPLES_PER_FRAME = 14
BYTES_PER_FRAME = 8


def decode_dsp_adpcm(
    data: bytes,
    coefficients: tuple[tuple[int, int], ...],
    predictor_scale: int,
    yn1: int,
    yn2: int,
    sample_count: int,
) -> list[int]:
    """Decode one channel to signed 16-bit PCM samples.

    `sample_count` is explicit because BFWAV channel data is frame-padded and
    the exact useful sample count is represented by the INFO loop-end field.
    """
    if sample_count < 0:
        raise BinaryFormatError("DSP ADPCM sample count cannot be negative")
    if len(coefficients) != 8:
        raise BinaryFormatError("DSP ADPCM requires exactly eight predictor coefficient pairs")
    required = ((sample_count + SAMPLES_PER_FRAME - 1) // SAMPLES_PER_FRAME) * BYTES_PER_FRAME
    if len(data) < required:
        raise BinaryFormatError(
            f"DSP ADPCM channel is truncated: need {required} bytes for {sample_count} samples, got {len(data)}"
        )

    hist1 = _s16(yn1)
    hist2 = _s16(yn2)
    out: list[int] = []
    remaining = sample_count
    cursor = 0

    while remaining:
        frame_header = data[cursor]
        cursor += 1
        predictor = frame_header >> 4
        scale = 1 << (frame_header & 0x0F)
        coef1, coef2 = coefficients[predictor]
        take = min(SAMPLES_PER_FRAME, remaining)
        for sample_index in range(take):
            packed = data[cursor + sample_index // 2]
            nibble = (packed >> 4) & 0x0F if sample_index % 2 == 0 else packed & 0x0F
            signed_nibble = nibble - 16 if nibble >= 8 else nibble
            sample = (((scale * signed_nibble) << 11) + 1024 + (coef1 * hist1 + coef2 * hist2)) >> 11
            sample = max(-32768, min(32767, sample))
            hist2, hist1 = hist1, sample
            out.append(sample)
        cursor += 7
        remaining -= take

    return out


def _s16(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value >= 0x8000 else value


def get_dsp_adpcm_loop_context(
    data: bytes,
    coefficients: tuple[tuple[int, int], ...],
    predictor_scale: int,
    yn1: int,
    yn2: int,
    sample_count: int,
) -> tuple[int, int, int]:
    """Port of TuneBloom's getLoopContext() from dsp/decode.cpp.

    Returns (loop_pred_scale, loop_yn1, loop_yn2) after decoding exactly
    `sample_count` samples. The predictor/scale byte is the header of the
    frame containing the final decoded sample, matching the original C++.
    """
    if sample_count < 0:
        raise BinaryFormatError("DSP ADPCM loop context sample count cannot be negative")
    if sample_count == 0:
        return predictor_scale & 0xFF, _s16(yn1), _s16(yn2)
    if len(coefficients) != 8:
        raise BinaryFormatError("DSP ADPCM requires exactly eight predictor coefficient pairs")
    full_frames, extra_samples = divmod(sample_count, SAMPLES_PER_FRAME)
    required = full_frames * BYTES_PER_FRAME + ((extra_samples + 1) // 2 + 1 if extra_samples else 0)
    if len(data) < required:
        raise BinaryFormatError(f"DSP ADPCM data is truncated: need {required} bytes, got {len(data)}")
    hist1, hist2 = _s16(yn1), _s16(yn2)
    cursor = 0
    remaining = sample_count
    loop_ps = predictor_scale & 0xFF
    while remaining:
        loop_ps = data[cursor]
        predictor = loop_ps >> 4
        scale = 1 << (loop_ps & 0x0F)
        coef1, coef2 = coefficients[predictor]
        cursor += 1
        take = min(SAMPLES_PER_FRAME, remaining)
        for sample_index in range(take):
            packed = data[cursor + sample_index // 2]
            nibble = (packed >> 4) & 0xF if sample_index % 2 == 0 else packed & 0xF
            signed_nibble = nibble - 16 if nibble >= 8 else nibble
            sample = (((scale * signed_nibble) << 11) + 1024 + coef1 * hist1 + coef2 * hist2) >> 11
            hist2, hist1 = hist1, max(-32768, min(32767, sample))
        cursor += 7
        remaining -= take
    return loop_ps, hist1, hist2


# The C++ helper uses these exact Nintendo DSP frame-size formulas.
def dsp_adpcm_bytes_for_samples(samples: int) -> int:
    if samples < 0:
        raise BinaryFormatError("Sample count cannot be negative")
    frames, extra = divmod(samples, SAMPLES_PER_FRAME)
    return frames * BYTES_PER_FRAME + ((extra + 1) // 2 + 1 if extra else 0)


def dsp_adpcm_bytes_for_buffer(samples: int) -> int:
    if samples < 0:
        raise BinaryFormatError("Sample count cannot be negative")
    return ((samples + SAMPLES_PER_FRAME - 1) // SAMPLES_PER_FRAME) * BYTES_PER_FRAME
