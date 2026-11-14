"""Lecture des formats audio NintendoWare : BFSTM (stream), BFWAV (wave), BFWAR (archive de waves)."""
import sys
from array import array
from dataclasses import dataclass, field

from .binio import Reader, detect_endian
from . import dspadpcm

ENC_PCM8, ENC_PCM16, ENC_DSPADPCM, ENC_IMAADPCM = 0, 1, 2, 3

# Types d'éléments (ElementType_* du code C++)
T_STRM_INFO, T_STRM_SEEK, T_STRM_DATA, T_STRM_REGN = 0x4000, 0x4001, 0x4002, 0x4003
T_WAV_INFO, T_WAV_DATA = 0x7000, 0x7001
T_WARC_INFO, T_WARC_FILE = 0x6800, 0x6801


@dataclass
class Audio:
    sample_rate: int
    channels: list                     # liste de array('h'), un par canal
    loop: bool = False
    loop_start: int = 0
    loop_end: int = 0
    encoding: int = ENC_DSPADPCM

    @property
    def frames(self):
        return len(self.channels[0]) if self.channels else 0


def _blocks(r: Reader, data, n_max=8):
    n = r.u16(16)
    out = {}
    for i in range(min(n, n_max)):
        base = 0x14 + 12 * i
        out[r.u16(base)] = (r.s32(base + 4), r.u32(base + 8))
    return out


def _pcm_to_array(raw, count, bits, endian):
    if bits == 8:
        a = array("b", bytes(raw[:count]))
        return array("h", [x << 8 for x in a])
    a = array("h")
    a.frombytes(bytes(raw[: count * 2]))
    if (endian == ">") != (sys.byteorder == "big"):
        a.byteswap()
    return a


def _decode_channel(raw, enc, nsamples, endian, coefs=None, yn1=0, yn2=0):
    if enc == ENC_DSPADPCM:
        return dspadpcm.decode(raw, nsamples, coefs, yn1, yn2)
    if enc == ENC_PCM16:
        return _pcm_to_array(raw, nsamples, 16, endian)
    if enc == ENC_PCM8:
        return _pcm_to_array(raw, nsamples, 8, endian)
    raise NotImplementedError("Encodage IMA-ADPCM non pris en charge")


def decode_bfstm(data: bytes) -> Audio:
    if data[:4] != b"FSTM":
        raise ValueError("Pas un BFSTM")
    e = detect_endian(data)
    r = Reader(data, e)
    blocks = _blocks(r, data)
    info_off = blocks[T_STRM_INFO][0]
    data_off = blocks[T_STRM_DATA][0]
    body = info_off + 8
    si = body + r.s32(body + 4)               # StreamSoundInfo
    ct = body + r.s32(body + 20)              # table des infos de canaux
    enc, loop, nch = r.u8(si), r.u8(si + 1), r.u8(si + 2)
    rate = r.u32(si + 4)
    loop_start = r.u32(si + 8)
    frames = r.u32(si + 12)
    block_count = r.u32(si + 16)
    one_bytes = r.u32(si + 20)
    last_padded = r.u32(si + 36)
    sample_off = data_off + 8 + r.s32(si + 52)

    # Désentrelacement : pour chaque bloc, pour chaque canal.
    bufs = [bytearray() for _ in range(nch)]
    pos = sample_off
    for b in range(block_count):
        size = last_padded if b == block_count - 1 else one_bytes
        for c in range(nch):
            bufs[c] += data[pos:pos + size]
            pos += size

    chans = []
    for c in range(nch):
        coefs, yn1, yn2 = None, 0, 0
        if enc == ENC_DSPADPCM:
            ci = ct + 4 + 8 * c
            ch_info = ct + r.s32(ci + 4)
            dsp = ch_info + r.s32(ch_info + 4)
            coefs = dspadpcm.read_coefs(data, dsp, e)
            yn1, yn2 = r.s16(dsp + 34), r.s16(dsp + 36)
        chans.append(_decode_channel(bufs[c], enc, frames, e, coefs, yn1, yn2))
    return Audio(rate, chans, bool(loop), loop_start, frames, enc)


def decode_bfwav(data: bytes) -> Audio:
    if data[:4] != b"FWAV":
        raise ValueError("Pas un BFWAV")
    e = detect_endian(data)
    r = Reader(data, e)
    version = r.u32(8)
    blocks = _blocks(r, data)
    ib = blocks[T_WAV_INFO][0] + 8
    data_body = blocks[T_WAV_DATA][0] + 8
    enc, loop = r.u8(ib), r.u8(ib + 1)
    rate = r.u32(ib + 4)
    loop_start = r.u32(ib + 8)
    loop_end = r.u32(ib + 12)               # = nombre d'échantillons
    tbl = ib + 20                           # la table suit toujours originalLoopStart (seule sa valeur dépend de la version)
    nch = r.u32(tbl)
    chans = []
    for c in range(nch):
        ci = tbl + r.s32(tbl + 4 + 8 * c + 4)
        start = data_body + r.s32(ci + 4)
        if enc == ENC_DSPADPCM:
            nbytes = dspadpcm.samples_to_bytes(loop_end)
        else:
            nbytes = loop_end * (2 if enc == ENC_PCM16 else 1)
        raw = data[start:start + nbytes]
        coefs, yn1, yn2 = None, 0, 0
        if enc == ENC_DSPADPCM:
            ai = r.s32(ci + 12)
            dsp = ci + ai
            coefs = dspadpcm.read_coefs(data, dsp, e)
            yn1, yn2 = r.s16(dsp + 34), r.s16(dsp + 36)
        chans.append(_decode_channel(raw, enc, loop_end, e, coefs, yn1, yn2))
    return Audio(rate, chans, bool(loop), loop_start, loop_end, enc)


def split_bfwar(data: bytes):
    """Renvoie la liste des fichiers BFWAV (bytes ou None) contenus dans un BFWAR."""
    if data[:4] != b"FWAR":
        raise ValueError("Pas un BFWAR")
    e = detect_endian(data)
    r = Reader(data, e)
    blocks = _blocks(r, data)
    info_off = blocks[T_WARC_INFO][0]
    file_body = blocks[T_WARC_FILE][0] + 8
    tbl = info_off + 8
    n = r.u32(tbl)
    out = []
    for i in range(n):
        o = tbl + 4 + 12 * i
        off, size = r.u32(o + 4), r.u32(o + 8)
        out.append(None if off == 0xFFFFFFFF else data[file_body + off:file_body + off + size])
    return out


def decode_any(data: bytes) -> Audio:
    magic = bytes(data[:4])
    if magic == b"FSTM":
        return decode_bfstm(data)
    if magic == b"FWAV":
        return decode_bfwav(data)
    raise ValueError(f"Format non décodable en audio : {magic!r}")
