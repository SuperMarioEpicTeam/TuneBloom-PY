"""Décodeur DSP-ADPCM (GameCube/Wii/Wii U), port de src/dsp/decode.cpp."""
from array import array
import struct, sys

SAMPLES_PER_FRAME = 14
BYTES_PER_FRAME = 8
_NIB = [n - 16 if n >= 8 else n for n in range(16)]


def bytes_to_samples(nbytes: int) -> int:
    s = (nbytes // 8) * 14
    frac = nbytes % 8
    if frac:
        s += (frac - 1) * 2
    return s


def samples_to_bytes(samples: int) -> int:
    b = (samples // 14) * 8
    frac = samples % 14
    if frac:
        b += ((frac + 1) >> 1) + 1
    return b


def decode(data, nsamples: int, coefs, yn1: int = 0, yn2: int = 0) -> array:
    """coefs : 16 entiers signés. Renvoie array('h') de nsamples échantillons."""
    out = array("h")
    append = out.append
    nib = _NIB
    h1, h2 = yn1, yn2
    pos = 0
    remaining = nsamples
    nframes = (nsamples + 13) // 14
    for _ in range(nframes):
        hdr = data[pos]
        pos += 1
        pred = (hdr >> 4) & 7
        scale = 1 << (hdr & 15)
        c1 = coefs[pred * 2]
        c2 = coefs[pred * 2 + 1]
        n = 14 if remaining > 14 else remaining
        for s in range(n):
            b = data[pos]
            if s & 1:
                v = nib[b & 15]
                pos += 1
            else:
                v = nib[b >> 4]
            x = (((scale * v) << 11) + 1024 + c1 * h1 + c2 * h2) >> 11
            if x > 32767:
                x = 32767
            elif x < -32768:
                x = -32768
            h2 = h1
            h1 = x
            append(x)
        if n & 1:  # nombre impair d'échantillons dans la dernière trame : octet partiel
            pos += 1
        remaining -= n
    return out


def read_coefs(buf: bytes, offset: int, endian: str):
    return list(struct.unpack_from(endian + "16h", buf, offset))
