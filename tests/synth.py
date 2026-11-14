"""Générateurs de fichiers synthétiques (BFSTM / BFWAV / BFWAR / BFSAR) pour les tests.
Ils ne valident que la cohérence avec NOTRE lecture du format, pas des fichiers réels."""
import struct

P = lambda fmt, *a: struct.pack(">" + fmt, *a)
COEFS = [2048, 0] + [0] * 14  # prédicteur 0 : y = (scale*nib<<11)>>11  (pas de prédiction)


def adpcm_frames(nibbles_per_frame_list, scale=0):
    """Chaque trame = 1 octet d'en-tête (pred 0, scale) + 7 octets (14 nibbles)."""
    out = b""
    for nibs in nibbles_per_frame_list:
        nibs = list(nibs) + [0] * (14 - len(nibs))
        out += bytes([scale]) + bytes((nibs[i] << 4) | nibs[i + 1] for i in range(0, 14, 2))
    return out


def dsp_param():
    return struct.pack(">16H3H3H", *[c & 0xFFFF for c in COEFS], 0, 0, 0, 0, 0, 0)


def bfstm(frames_data: bytes, nsamples: int, rate=32000):
    """1 canal DSP-ADPCM, 1 seul bloc."""
    n = len(frames_data)
    si = bytearray(76)
    si[0:4] = bytes([2, 0, 1, 0])
    for off, v in ((4, rate), (8, 0), (12, nsamples), (16, 1), (20, n), (24, nsamples),
                   (28, n), (32, nsamples), (36, n)):
        si[off:off + 4] = P("I", v)
    si[48:56] = P("HHi", 0x1F00, 0, 0x18)             # données à +0x18 du corps du bloc DATA
    ctab = P("I", 1) + P("HHi", 0x4102, 0, 12)        # table de canaux
    chinfo = P("HHi", 0x0300, 0, 8)                   # ChannelInfo -> DSP à +8
    dsp = dsp_param() + P("HHH", 0, 0, 0)
    body = P("HHi", 0x4100, 0, 0x18) + P("HHi", 0x0101, 0, 0x18) + P("HHi", 0x0101, 0, 0x18 + 76)
    body += bytes(si) + ctab + chinfo + dsp
    info = b"INFO" + P("I", 8 + len(body)) + body
    info += b"\x00" * ((-len(info)) % 0x20)
    data_body = b"\x00" * 0x18 + frames_data
    data = b"DATA" + P("I", 8 + len(data_body)) + data_body
    data += b"\x00" * ((-len(data)) % 0x20)
    hdr_len = 0x40
    header = b"FSTM" + P("HHIIHH", 0xFEFF, hdr_len, 0x00040000, hdr_len + len(info) + len(data), 2, 0)
    header += P("HHiI", 0x4000, 0, hdr_len, len(info)) + P("HHiI", 0x4002, 0, hdr_len + len(info), len(data))
    header += b"\x00" * (hdr_len - len(header))
    return header + info + data


def bfwav(frames_data: bytes, nsamples: int, rate=22050, enc=2):
    ib = bytearray()
    ib += bytes([enc, 0, 0, 0]) + P("IIII", rate, 0, nsamples, 0)       # +0..+19
    ib += P("I", 1) + P("HHi", 0x7100, 0, 12)                            # table de canaux @+20
    ib += P("HHi", 0x1F00, 0, 0x14 if False else 0) + P("HHi", 0x0300, 0, 12) + P("I", 0)   # ChannelInfo @+32
    ib += dsp_param() + P("HHH", 0, 0, 0)
    info = b"INFO" + P("I", 8 + len(ib)) + bytes(ib)
    info += b"\x00" * ((-len(info)) % 0x20)
    data_body = frames_data
    data = b"DATA" + P("I", 8 + len(data_body)) + data_body
    data += b"\x00" * ((-len(data)) % 0x20)
    hdr_len = 0x30
    header = b"FWAV" + P("HHIIHH", 0xFEFF, hdr_len, 0x00010200, hdr_len + len(info) + len(data), 2, 0)
    header += P("HHiI", 0x7000, 0, hdr_len, len(info)) + P("HHiI", 0x7001, 0, hdr_len + len(info), len(data))
    header += b"\x00" * (hdr_len - len(header))
    return header + info + data


def bfwar(waves):
    n = len(waves)
    off, entries, blob = 0, b"", b""
    for w in waves:
        w2 = w + b"\x00" * ((-len(w)) % 0x20)
        entries += P("HHiI", 0x1F00, 0, off, len(w))
        blob += w2
        off += len(w2)
    info_body = P("I", n) + entries
    info = b"INFO" + P("I", 8 + len(info_body)) + info_body
    info += b"\x00" * ((-len(info)) % 0x20)
    fileb = b"FILE" + P("I", 8 + len(blob)) + blob
    hdr_len = 0x40
    header = b"FWAR" + P("HHIIHH", 0xFEFF, hdr_len, 0x00010000, hdr_len + len(info) + len(fileb), 2, 0)
    header += P("HHiI", 0x6800, 0, hdr_len, len(info)) + P("HHiI", 0x6801, 0, hdr_len + len(info), len(fileb))
    header += b"\x00" * (hdr_len - len(header))
    return header + info + fileb


def bfsar(files, names):
    """Un seul son stream (fichier 0 = BFSTM), un WAVE ARCHIVE (fichier 1 = BFWAR). files = [bytes, bytes]."""
    strings = names                                     # ["SE_TEST", "WARC_TEST"]
    # --- bloc STRING ---
    st_entries, st_blob = b"", b""
    tbl_len = 4 + 12 * len(strings)
    pos = tbl_len
    for s in strings:
        b = s.encode() + b"\x00"
        st_entries += P("HHiI", 0x1F01, 0, pos, len(b))
        st_blob += b
        pos += len(b)
    st_table = P("I", len(strings)) + st_entries + st_blob
    st_body = P("HHi", 0x2400, 0, 0x10) + P("HHi", 0x2401, 0, -1) + st_table
    sblock = b"STRG" + P("I", 8 + len(st_body)) + st_body
    sblock += b"\x00" * ((-len(sblock)) % 0x20)

    # --- bloc INFO : on construit tables dans un buffer, offsets relatifs à leur table ---
    # SoundInfo : fileId, playerId, vol, rf, pad, ref detail, bitflag(1 bit : string id) + valeur
    detail = P("HH", 0, 1) + P("HHi", 0, 0, 0) + P("f", 1.0) + P("HHi", 0, 0, 0) + P("HHi", 0, 0, -1) + P("I", 0xFFFFFFFF)
    detail = bytearray(detail[:36])
    sound = P("IIBBH", 0, 0, 127, 0, 0) + P("HHi", 0x2201, 0, 28) + P("I", 1) + P("I", 0)   # string id 0
    sound_full = sound + bytes(detail)
    warc = P("I", 1) + P("BBH", 0, 0, 0) + P("I", 1) + P("I", 1)                    # fileId=1 ; bit0 -> strId 1
    # FileInfo : ref location, bitflag ; InternalFileInfo : refwithsize (type, pad, off, size) + ref groups
    def finfo(): return P("HHi", 0x220C, 0, 12) + P("I", 0)
    def intern(off, size): return P("HHiI", 0x1F00, 0, off, size) + P("HHi", 0, 0, -1)
    pad = lambda b: b + b"\x00" * ((-len(b)) % 4)

    def rtable(items):  # items: list of (type, bytes)
        n = len(items)
        head = 4 + 8 * n
        out, refs, off = b"", b"", head
        for typ, blob in items:
            refs += P("HHi", typ, 0, off)
            out += blob
            off += len(blob)
        return P("I", n) + refs + out

    fb_off0, fb_off1 = 0x10, 0x10 + ((len(files[0]) + 0x1F) // 0x20) * 0x20
    t_sound = rtable([(0x2200, sound_full)])
    t_group = rtable([])
    t_bank = rtable([])
    t_warc = rtable([(0x2207, warc)])
    t_grp = rtable([])
    t_player = rtable([])
    t_file = rtable([(0x220A, finfo() + intern(fb_off0, len(files[0]))),
                     (0x220A, finfo() + intern(fb_off1, len(files[1])))])
    t_pinfo = b"\x00" * 0x14
    tables = [(0x2100, t_sound), (0x2104, t_group), (0x2101, t_bank), (0x2103, t_warc),
              (0x2105, t_grp), (0x2102, t_player), (0x2106, t_file), (0x220B, t_pinfo)]
    refs, blob, off = b"", b"", 0x40
    for typ, t in tables:
        t = pad(t)
        refs += P("HHi", typ, 0, off)
        blob += t
        off += len(t)
    ibody = refs + blob
    iblock = b"INFO" + P("I", 8 + len(ibody)) + ibody
    iblock += b"\x00" * ((-len(iblock)) % 0x20)

    # --- bloc FILE ---
    f0 = files[0] + b"\x00" * ((-len(files[0])) % 0x20)
    f1 = files[1] + b"\x00" * ((-len(files[1])) % 0x20)
    fbody = b"\x00" * 0x10 + f0 + f1
    fblock = b"FILE" + P("I", 8 + len(fbody)) + fbody
    hdr_len = 0x40
    s_off, i_off = hdr_len, hdr_len + len(sblock)
    f_off = i_off + len(iblock)
    total = f_off + len(fblock)
    header = b"FSAR" + P("HHIIHH", 0xFEFF, hdr_len, 0x00020200, total, 3, 0)
    header += P("HHiI", 0x2000, 0, s_off, len(sblock)) + P("HHiI", 0x2001, 0, i_off, len(iblock)) + \
              P("HHiI", 0x2002, 0, f_off, len(fblock))
    header += b"\x00" * (hdr_len - len(header))
    return header + sblock + iblock + fblock
