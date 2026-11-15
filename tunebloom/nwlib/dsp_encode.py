"""Nintendo DSP ADPCM encoder ported from TuneBloom's src/dsp/encode.cpp.

The coefficient analysis, predictor selection, quantizer, nibble packing and
initial ADPCM context follow the supplied C++ implementation. Integer
operations deliberately emulate C/C++ truncation and signed 16-bit wrapping.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from .binary import BinaryFormatError

SAMPLES_PER_FRAME = 14
BYTES_PER_FRAME = 8


@dataclass(frozen=True)
class AdpcmEncodeResult:
    data: bytes
    coefficients: tuple[tuple[int, int], ...]
    gain: int = 0
    predictor_scale: int = 0
    yn1: int = 0
    yn2: int = 0


def _trunc_div(a: int, b: int) -> int:
    return int(a / b)


def _s16(v: int) -> int:
    v &= 0xFFFF
    return v - 0x10000 if v >= 0x8000 else v


def _clamp16(v: int) -> int:
    return max(-32768, min(32767, v))


def _fdiv(a: float, b: float) -> float:
    """IEEE-754 division, matching C++ double division (including /0)."""
    if b != 0.0:
        return a / b
    if a == 0.0 or math.isnan(a):
        return math.nan
    sign = math.copysign(1.0, a) * math.copysign(1.0, b)
    return math.copysign(math.inf, sign)


def _lround(v: float) -> int:
    # On the target C runtime lround(NaN) returns LONG_MIN; narrowing that
    # value to int16_t produces zero, matching the original encoder output.
    if math.isnan(v):
        return 0
    if math.isinf(v):
        return 32767 if v > 0 else -32768
    return math.floor(v + 0.5) if v >= 0 else math.ceil(v - 0.5)


def _inner_product_merge(pcm: list[int]) -> list[float]:
    """`pcm` is the concatenated previous and current 14-sample history."""
    out = [0.0, 0.0, 0.0]
    for i in range(3):
        for x in range(14):
            out[i] -= pcm[14 + x - i] * pcm[14 + x]
    return out


def _outer_product_merge(pcm: list[int]) -> list[list[float]]:
    out = [[0.0] * 3 for _ in range(3)]
    for x in range(1, 3):
        for y in range(1, 3):
            for z in range(14):
                out[x][y] += pcm[14 + z - x] * pcm[14 + z - y]
    return out


def _analyze_ranges(mtx: list[list[float]]) -> tuple[bool, list[int]]:
    recips = [0.0, 0.0, 0.0]
    for x in (1, 2):
        val = max(abs(mtx[x][1]), abs(mtx[x][2]))
        if val < 2.220446049250313e-16:
            return True, [0, 0, 0]
        recips[x] = 1.0 / val
    indexes = [0, 0, 0]
    max_index = 0
    for i in (1, 2):
        for x in range(1, i):
            tmp = mtx[x][i]
            for y in range(1, x):
                tmp -= mtx[x][y] * mtx[y][i]
            mtx[x][i] = tmp
        val = 0.0
        for x in range(i, 3):
            tmp = mtx[x][i]
            for y in range(1, i):
                tmp -= mtx[x][y] * mtx[y][i]
            mtx[x][i] = tmp
            tmp = abs(tmp) * recips[x]
            if tmp >= val:
                val, max_index = tmp, x
        if max_index != i:
            for y in range(1, 3):
                mtx[max_index][y], mtx[i][y] = mtx[i][y], mtx[max_index][y]
            recips[max_index] = recips[i]
        indexes[i] = max_index
        if mtx[i][i] == 0.0:
            return True, indexes
        if i != 2:
            tmp = 1.0 / mtx[i][i]
            for x in range(i + 1, 3):
                mtx[x][i] *= tmp
    diag = [abs(mtx[i][i]) for i in (1, 2)]
    if min(diag) / max(diag) < 1.0e-10:
        return True, indexes
    return False, indexes


def _bidirectional_filter(mtx: list[list[float]], indexes: list[int], vec: list[float]) -> None:
    x = 0
    for i in (1, 2):
        index = indexes[i]
        tmp = vec[index]
        vec[index] = vec[i]
        if x != 0:
            for y in range(x, i):
                tmp -= vec[y] * mtx[i][y]
        elif tmp != 0.0:
            x = i
        vec[i] = tmp
    for i in (2, 1):
        tmp = vec[i]
        for y in range(i + 1, 3):
            tmp -= vec[y] * mtx[i][y]
        vec[i] = _fdiv(tmp, mtx[i][i])
    vec[0] = 1.0


def _quadratic_merge(vec: list[float]) -> bool:
    v2 = vec[2]
    tmp = 1.0 - v2 * v2
    if tmp == 0.0:
        return True
    v0 = (vec[0] - v2 * v2) / tmp
    v1 = (vec[1] - vec[1] * v2) / tmp
    vec[0], vec[1] = v0, v1
    return abs(v1) > 1.0


def _finish_record(src: list[float], dst: list[float]) -> None:
    for z in (1, 2):
        if src[z] >= 1.0:
            src[z] = 0.9999999999
        elif src[z] <= -1.0:
            src[z] = -0.9999999999
    dst[0] = 1.0
    dst[1] = src[2] * src[1] + src[1]
    dst[2] = src[2]


def _matrix_filter(src: list[float]) -> list[float]:
    mtx = [[0.0] * 3 for _ in range(3)]
    mtx[2][0] = 1.0
    for i in (1, 2):
        mtx[2][i] = -src[i]
    for i in (2, 1):
        val = 1.0 - mtx[i][i] * mtx[i][i]
        for y in range(1, i + 1):
            mtx[i - 1][y] = _fdiv(mtx[i][i] * mtx[i][y] + mtx[i][y], val)
    dst = [1.0, 0.0, 0.0]
    for i in (1, 2):
        for y in range(1, i + 1):
            dst[i] += mtx[i][y] * dst[i - y]
    return dst


def _merge_finish_record(src: list[float]) -> list[float]:
    dst = [0.0, 0.0, 0.0]
    tmp = [0.0, 0.0, 0.0]
    val = src[0]
    dst[0] = 1.0
    for i in (1, 2):
        v2 = 0.0
        for y in range(1, i):
            v2 += dst[y] * src[i - y]
        dst[i] = -_fdiv(v2 + src[i], val) if val > 0.0 else 0.0
        tmp[i] = dst[i]
        for y in range(1, i):
            dst[y] += dst[i] * dst[i - y]
        val *= 1.0 - dst[i] * dst[i]
    _finish_record(tmp, dst)
    return dst


def _contrast_vectors(a: list[float], b: list[float]) -> float:
    val = _fdiv(b[2] * b[1] - b[1], 1.0 - b[2] * b[2])
    val1 = a[0] * a[0] + a[1] * a[1] + a[2] * a[2]
    val2 = a[0] * a[1] + a[1] * a[2]
    val3 = a[0] * a[2]
    return val1 + 2.0 * val * val2 + 2.0 * (-b[1] * val - b[2]) * val3


def _filter_records(best: list[list[float]], exp: int, records: list[list[float]]) -> None:
    for _ in range(2):
        counts = [0] * exp
        sums = [[0.0, 0.0, 0.0] for _ in range(exp)]
        for record in records:
            index = 0
            value = 1.0e30
            for i in range(exp):
                temp = _contrast_vectors(best[i], record)
                if temp < value:
                    value, index = temp, i
            counts[index] += 1
            filtered = _matrix_filter(record)
            for i in range(3):
                sums[index][i] += filtered[i]
        for i in range(exp):
            if counts[i] > 0:
                sums[i] = [v / counts[i] for v in sums[i]]
        for i in range(exp):
            best[i] = _merge_finish_record(sums[i])


def correlate_coefficients(samples: list[int]) -> tuple[tuple[int, int], ...]:
    """Port of correlateCoefs() in TuneBloom/src/dsp/encode.cpp."""
    if not samples:
        raise BinaryFormatError("Cannot encode an empty DSP ADPCM stream")
    source_pos = 0
    hist = [[0] * 14 for _ in range(2)]
    records: list[list[float]] = []
    while source_pos < len(samples):
        block = samples[source_pos:source_pos + 0x3800]
        source_pos += len(block)
        for start in range(0, len(block), 14):
            current = block[start:start + 14]
            if len(current) < 14:
                current += [0] * (14 - len(current))
            hist[0] = hist[1]
            hist[1] = current
            # In C++, pcmBuf[-1/-2] reaches the preceding row in pcmHistBuffer.
            pcm = hist[0] + hist[1]
            vec1 = _inner_product_merge(pcm)
            if abs(vec1[0]) > 10.0:
                mtx = _outer_product_merge(pcm)
                failed, indexes = _analyze_ranges(mtx)
                if not failed:
                    _bidirectional_filter(mtx, indexes, vec1)
                    if not _quadratic_merge(vec1):
                        record = [0.0, 0.0, 0.0]
                        _finish_record(vec1, record)
                        records.append(record)
    if not records:
        # TuneBloom's C++ routine divides by zero in this degenerate case; on
        # its supported IEEE-754 build the resulting NaN coefficients narrow
        # to zero int16 values. Preserve the observable encoder result.
        return tuple((0, 0) for _ in range(8))
    vec1 = [1.0, 0.0, 0.0]
    for record in records:
        best0 = _matrix_filter(record)
        vec1[1] += best0[1]
        vec1[2] += best0[2]
    vec1[1] /= len(records)
    vec1[2] /= len(records)
    best = [_merge_finish_record(vec1)] + [[0.0, 0.0, 0.0] for _ in range(7)]
    exp = 1
    for w in range(3):
        vec2 = [0.0, -1.0, 0.0]
        for i in range(exp):
            best[exp + i] = [0.01 * vec2[y] + best[i][y] for y in range(3)]
        exp = 1 << (w + 1)
        _filter_records(best, exp, records)
    output: list[int] = []
    for z in range(8):
        for component in (1, 2):
            d = -best[z][component] * 2048.0
            value = _lround(d)
            output.append(max(-32768, min(32767, value)))
    return tuple((output[i], output[i + 1]) for i in range(0, 16, 2))


def _encode_frame(pcm: list[int], coefficients: tuple[tuple[int, int], ...], sample_count: int) -> tuple[list[int], bytes]:
    in_samples = [[0] * 16 for _ in range(8)]
    out_samples = [[0] * 14 for _ in range(8)]
    scales = [0] * 8
    distances = [0.0] * 8
    for i in range(8):
        c0, c1 = coefficients[i]
        in_samples[i][0], in_samples[i][1] = pcm[0], pcm[1]
        distance = 0
        for s in range(sample_count):
            v1 = _trunc_div(pcm[s] * c1 + pcm[s + 1] * c0, 2048)
            in_samples[i][s + 2] = v1
            v2 = pcm[s + 2] - v1
            v3 = max(-32768, min(32767, v2))
            if abs(v3) > abs(distance):
                distance = v3
        scale = 0
        while scale <= 12 and (distance > 7 or distance < -8):
            scale += 1
            distance = _trunc_div(distance, 2)
        scales[i] = -1 if scale <= 1 else scale - 2
        while True:
            scales[i] += 1
            distances[i] = 0.0
            index = 0
            for s in range(sample_count):
                v1 = in_samples[i][s] * c1 + in_samples[i][s + 1] * c0
                v2 = (pcm[s + 2] << 11) - v1
                denom = (1 << scales[i]) * 2048
                v3 = int(v2 / denom + (0.4999999 if v2 > 0 else -0.4999999))
                if v3 < -8:
                    if index < -8 - v3:
                        index = -8 - v3
                    v3 = -8
                elif v3 > 7:
                    if index < v3 - 7:
                        index = v3 - 7
                    v3 = 7
                out_samples[i][s] = v3
                v1 = (v1 + ((v3 * (1 << scales[i])) << 11) + 1024) >> 11
                in_samples[i][s + 2] = _clamp16(v1)
                err = pcm[s + 2] - in_samples[i][s + 2]
                distances[i] += err * float(err)
            x = index + 8
            while x > 256:
                scales[i] += 1
                if scales[i] >= 12:
                    scales[i] = 11
                x >>= 1
            if not (scales[i] < 12 and index > 1):
                break
    best_index = min(range(8), key=lambda i: distances[i])
    reconstructed = in_samples[best_index][2:2 + sample_count]
    packed = bytearray(8)
    packed[0] = ((best_index << 4) | (scales[best_index] & 0xF)) & 0xFF
    for s in range(sample_count, 14):
        out_samples[best_index][s] = 0
    for y in range(7):
        packed[y + 1] = ((out_samples[best_index][y * 2] << 4) | (out_samples[best_index][y * 2 + 1] & 0xF)) & 0xFF
    return reconstructed, bytes(packed)


def encode_dsp_adpcm(samples: list[int] | tuple[int, ...]) -> AdpcmEncodeResult:
    """Encode signed PCM16 samples into Nintendo DSP ADPCM frames."""
    pcm = [_s16(int(v)) for v in samples]
    if not pcm:
        raise BinaryFormatError("Cannot encode an empty DSP ADPCM stream")
    coefficients = correlate_coefficients(pcm)
    output = bytearray()
    history = [0, 0]
    for offset in range(0, len(pcm), SAMPLES_PER_FRAME):
        count = min(SAMPLES_PER_FRAME, len(pcm) - offset)
        frame_pcm = [history[0], history[1]] + pcm[offset:offset + count]
        frame_pcm += [0] * (16 - len(frame_pcm))
        # TuneBloom calls DSPEncodeFrame with the full 14-sample frame even
        # for the final partial frame; only the byte copy is shortened.
        reconstructed, frame = _encode_frame(frame_pcm, coefficients, 14)
        output.extend(frame[:((count // 2) + (count % 2) + 1) if count % 14 else 8])
        history = reconstructed[-2:]
    return AdpcmEncodeResult(bytes(output), coefficients, 0, output[0], 0, 0)
