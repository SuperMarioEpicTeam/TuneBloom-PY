"""Écriture de BFSTM (DSP-ADPCM, version 3.0.0 / SM3DW) : disposition validée sur un vrai fichier."""
import struct
from .binio import detect_endian, align
from . import dspadpcm

ONE_BLOCK_BYTES = 0x2000
ONE_BLOCK_SAMPLES = ONE_BLOCK_BYTES // 8 * 14          # 0x3800


def parse_raw(data):
    """Extrait d'un BFSTM tout ce qu'il faut pour le reconstruire."""
    data = bytes(data)
    e = detect_endian(data)
    u32 = lambda o: struct.unpack_from(e + "I", data, o)[0]
    s32 = lambda o: struct.unpack_from(e + "i", data, o)[0]
    u16 = lambda o: struct.unpack_from(e + "H", data, o)[0]
    s16 = lambda o: struct.unpack_from(e + "h", data, o)[0]
    blocks = {u16(0x14 + 12 * i): (u32(0x14 + 12 * i + 4), u32(0x14 + 12 * i + 8)) for i in range(u16(16))}
    info = blocks[0x4000][0] + 8
    si = info + s32(info + 4)
    nch, rate, frames = data[si + 2], u32(si + 4), u32(si + 12)
    out = dict(endian=e, version=u32(8), loop=data[si + 1], loop_start=u32(si + 8), rate=rate, frames=frames, nch=nch,
               header=data[:0x40])
    nblk, one, last_padded = u32(si + 16), u32(si + 20), u32(si + 36)
    sample_off = blocks[0x4002][0] + 8 + s32(si + 52)
    ct = info + s32(info + 20)
    chans = [bytearray() for _ in range(nch)]
    pos = sample_off
    for b in range(nblk):
        size = last_padded if b == nblk - 1 else one
        for c in range(nch):
            chans[c] += data[pos:pos + size]; pos += size
    out["adpcm"] = [bytes(c) for c in chans]
    ch = []
    for c in range(nch):
        ci = ct + s32(ct + 4 + 8 * c + 4)               # ChannelInfo
        dsp = ci + s32(ci + 4)                          # DspAdpcmChannelInfo
        ch.append(dict(coefs=list(struct.unpack_from(e + "16h", data, dsp)), ps=u16(dsp + 32), yn1=s16(dsp + 34), yn2=s16(dsp + 36),
                       lps=u16(dsp + 38), l1=s16(dsp + 40), l2=s16(dsp + 42)))
    out["ch"] = ch
    sk = blocks[0x4001][0] + 8
    out["seek"] = [[struct.unpack_from("<hh", data, sk + (b * nch + c) * 4) for c in range(nch)] for b in range(nblk)]   # int16 little-endian
    out["last_samples"] = u32(si + 32)
    return out


def pack_bfstm(raw, endian=">"):
    """raw : dict comme celui de parse_raw (adpcm par canal, ch, seek, loop, rate, frames…)."""
    e = endian
    P32 = lambda v: struct.pack(e + "I", v)
    nch, frames = raw["nch"], raw["frames"]
    nblk = (frames + ONE_BLOCK_SAMPLES - 1) // ONE_BLOCK_SAMPLES
    last_samples = frames - (nblk - 1) * ONE_BLOCK_SAMPLES
    last_bytes = dspadpcm.samples_to_bytes(last_samples)
    last_padded = align(last_bytes, 0x20)
    # --- INFO ---
    si = bytearray(68)
    si[0:4] = bytes([2, 1 if raw["loop"] else 0, nch, 0])
    for off, v in ((4, raw["rate"]), (8, raw["loop_start"]), (12, frames), (16, nblk), (20, ONE_BLOCK_BYTES), (24, ONE_BLOCK_SAMPLES),
                   (28, last_bytes), (32, last_samples), (36, last_padded), (40, 4), (44, ONE_BLOCK_SAMPLES)):
        si[off:off + 4] = P32(v)
    si[48:56] = struct.pack(e + "HHi", 0x1F00, 0, 0x18)
    si[56:60] = struct.pack(e + "HH", 0x100, 0)
    si[60:68] = struct.pack(e + "HHi", 0, 0, -1)           # région absente
    ct = P32(nch) + b"".join(struct.pack(e + "HHi", 0x4102, 0, 4 + 8 * nch + 8 * i) for i in range(nch))
    cinfo = b"".join(struct.pack(e + "HHi", 0x0300, 0, 8 * (nch - i) + 46 * i) for i in range(nch))
    dsp = b""
    for c in raw["ch"]:
        dsp += struct.pack(e + "16hHhhHhhH", *c["coefs"], c["ps"], c["yn1"], c["yn2"], c["lps"], c["l1"], c["l2"], 0)
    body = (struct.pack(e + "HHi", 0x4100, 0, 0x18) + struct.pack(e + "HHi", 0, 0, -1) + struct.pack(e + "HHi", 0x0101, 0, 0x18 + 68)
            + bytes(si) + ct + cinfo + dsp)
    info_size = align(8 + len(body), 0x20)
    info = b"INFO" + P32(info_size) + body + b"\0" * (info_size - 8 - len(body))
    # --- SEEK ---
    sk = b"".join(struct.pack("<hh", a, b) for blk in raw["seek"] for (a, b) in blk)
    seek_size = align(8 + len(sk), 0x20)
    seek = b"SEEK" + P32(seek_size) + sk + b"\0" * (seek_size - 8 - len(sk))
    # --- DATA ---
    out = bytearray(b"\0" * 0x18)
    for b in range(nblk):
        size = last_padded if b == nblk - 1 else ONE_BLOCK_BYTES
        for c in range(nch):
            seg = raw["adpcm"][c][b * ONE_BLOCK_BYTES:b * ONE_BLOCK_BYTES + size]
            out += seg + b"\0" * (size - len(seg))
    data_size = align(8 + len(out), 0x20)
    data = b"DATA" + P32(data_size) + bytes(out) + b"\0" * (data_size - 8 - len(out))
    hdr = bytearray(0x40)
    hdr[0:4] = b"FSTM"
    hdr[4:8] = struct.pack(e + "HH", 0xFEFF, 0x40)
    hdr[8:12] = P32(raw.get("version", 0x00030000))
    hdr[12:16] = P32(0x40 + len(info) + len(seek) + len(data))
    hdr[16:20] = struct.pack(e + "HH", 3, 0)
    hdr[0x14:0x20] = struct.pack(e + "HHiI", 0x4000, 0, 0x40, len(info))[:12]
    hdr[0x20:0x2c] = struct.pack(e + "HHiI", 0x4001, 0, 0x40 + len(info), len(seek))[:12]
    hdr[0x2c:0x38] = struct.pack(e + "HHiI", 0x4002, 0, 0x40 + len(info) + len(seek), len(data))[:12]
    return bytes(hdr) + info + seek + data


def build_bfstm(channels, rate, loop_start=None, endian=">"):
    """channels : listes d'échantillons int16 (un par canal, même longueur). Encode en DSP-ADPCM (encodeur identique au C++).
    loop_start (en échantillons) est arrondi à un multiple de 14 (frame ADPCM). Renvoie (octets, loop_start_effectif)."""
    from .nwlib import encode_dsp_adpcm
    nch, frames = len(channels), len(channels[0])
    if any(len(c) != frames for c in channels):
        raise ValueError("Tous les canaux doivent avoir la même longueur")
    loop = loop_start is not None
    ls = (loop_start // 14) * 14 if loop else 0
    nblk = (frames + ONE_BLOCK_SAMPLES - 1) // ONE_BLOCK_SAMPLES
    adpcm, ch = [], []
    for pcm in channels:
        r = encode_dsp_adpcm(list(pcm))
        data = bytes(r.data)[:dspadpcm.samples_to_bytes(frames)]
        coefs = [v for pair in r.coefficients for v in pair]
        dec = dspadpcm.decode(data, frames, coefs, 0, 0)
        c = dict(coefs=coefs, ps=data[0], yn1=0, yn2=0, lps=0, l1=0, l2=0)
        if loop and ls > 0:
            c.update(lps=data[ls // 14 * 8], l1=dec[ls - 1], l2=dec[ls - 2])
        elif loop:
            c.update(lps=data[0])
        adpcm.append(data); ch.append(c)
    seek = [[(0, 0)] * nch]
    for b in range(1, nblk):
        i = b * ONE_BLOCK_SAMPLES
        seek.append([(channels[c][i - 1], channels[c][i - 2]) for c in range(nch)])
    raw = dict(nch=nch, frames=frames, rate=rate, loop=loop, loop_start=ls, adpcm=adpcm, ch=ch, seek=seek)
    return pack_bfstm(raw, endian), ls
