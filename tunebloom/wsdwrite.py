"""Écriture de BFWSD (wave sounds) et ajout de vagues à un BFWAR ; disposition validée sur de vrais fichiers."""
import struct
from .binio import detect_endian, align

INVALID = 0xFFFFFFFF


# ----------------------------------------------------------------------------- BFWSD
def parse_wsd(data):
    data = bytes(data)
    e = detect_endian(data)
    u32 = lambda o: struct.unpack_from(e + "I", data, o)[0]
    s32 = lambda o: struct.unpack_from(e + "i", data, o)[0]
    u16 = lambda o: struct.unpack_from(e + "H", data, o)[0]
    info = u32(0x18)
    body = info + 8
    wid = body + s32(body + 4)
    rt = body + s32(body + 12)
    nw, ns = u32(wid), u32(rt)
    refs = [(u16(rt + 4 + 8 * i), rt + s32(rt + 4 + 8 * i + 4)) for i in range(ns)]
    ends = [r[1] for r in refs[1:]] + [info + u32(0x1c)]
    items = [data[refs[i][1]:ends[i]] for i in range(ns)]
    return dict(e=e, padded=len(data) > info + u32(0x1c), header=data[:0x20], ref_types=(u16(body), u16(body + 8)), wave_ids=[(u32(wid + 4 + 8 * i), u32(wid + 8 + 8 * i)) for i in range(nw)],
                item_types=[r[0] for r in refs], items=items, wid_types=u16(wid - body + body) if False else 0)


def pack_wsd(w):
    e = w["e"]
    P = lambda v: struct.pack(e + "I", v)
    nw, ns = len(w["wave_ids"]), len(w["items"])
    wid = P(nw) + b"".join(struct.pack(e + "II", a, b) for a, b in w["wave_ids"])
    rt_off = 0x10 + len(wid)
    head = 4 + 8 * ns
    rt = P(ns)
    pos = head
    for t, it in zip(w["item_types"], w["items"]):
        rt += struct.pack(e + "HHi", t, 0, pos)
        pos += len(it)
    body = (struct.pack(e + "HHi", w["ref_types"][0], 0, 0x10) + struct.pack(e + "HHi", w["ref_types"][1], 0, rt_off)
            + wid + rt + b"".join(w["items"]))
    size = 8 + len(body)                     # taille de bloc exacte ; c'est le FICHIER qui est complété à 0x20
    info = b"INFO" + P(size) + body
    hdr = bytearray(w["header"])
    hdr[12:16] = P(0x20 + size)
    hdr[0x1c:0x20] = P(size)
    out = bytes(hdr) + info
    return out + (b"\0" * ((-len(out)) % 0x20) if w.get("padded", True) else b"")


def add_wave_sound_data(w, template_item, warc_id, wave_index):
    """Ajoute une vague à la table d'ids et un WaveSoundData (copie de `template_item`) qui la joue. Renvoie l'index du nouveau wave sound."""
    e = w["e"]
    wsd_i = len(w["items"])
    new_wid = len(w["wave_ids"])
    w["wave_ids"].append((warc_id, wave_index))
    it = bytearray(w["items"][template_item])
    nt_off = struct.unpack_from(e + "i", it, 20)[0]               # table des NoteInfo, relative à l'élément
    n_notes = struct.unpack_from(e + "I", it, nt_off)[0]
    if n_notes != 1:
        raise ValueError("Le wave sound modèle doit avoir exactement 1 note")
    note = nt_off + struct.unpack_from(e + "i", it, nt_off + 4 + 4)[0]
    struct.pack_into(e + "I", it, note, new_wid)                  # waveIdTableIndex
    w["items"].append(bytes(it))
    w["item_types"].append(w["item_types"][template_item])
    return wsd_i


# ----------------------------------------------------------------------------- BFWAR (ajout de vagues)
def append_waves_to_bfwar(orig, new_waves):
    """Ajoute des BFWAV à la fin d'un BFWAR. Renvoie (octets, [index des nouvelles vagues])."""
    orig = bytes(orig)
    e = detect_endian(orig)
    P = lambda v: struct.pack(e + "I", v)
    u32 = lambda o: struct.unpack_from(e + "I", orig, o)[0]
    u16 = lambda o: struct.unpack_from(e + "H", orig, o)[0]
    blocks = {u16(0x14 + 12 * i): (u32(0x14 + 12 * i + 4), u32(0x14 + 12 * i + 8)) for i in range(u16(16))}
    io_, isz = blocks[0x6800]
    fo, fsz = blocks[0x6801]
    n = u32(io_ + 8)
    entries = [(u32(io_ + 12 + 12 * i + 4), u32(io_ + 12 + 12 * i + 8)) for i in range(n)]
    body = bytearray(orig[fo + 8:fo + fsz])
    for w in new_waves:
        body += b"\0" * ((-(8 + len(body))) % 0x20)
        entries.append((len(body), len(w)))
        body += bytes(w)
    body += b"\0" * ((-(8 + len(body))) % 0x20)
    ib = P(len(entries)) + b"".join(struct.pack(e + "HHiI", 0x1F00, 0, off, size) for off, size in entries)
    isize = align(8 + len(ib), 0x20)
    info = b"INFO" + P(isize) + ib + b"\0" * (isize - 8 - len(ib))
    fsize = 8 + len(body)
    fileb = orig[fo:fo + 4] + P(fsize) + bytes(body)
    hdr = bytearray(orig[:0x40])
    hdr[12:16] = P(0x40 + isize + fsize)
    hdr[0x14 + 4:0x14 + 8] = P(0x40); hdr[0x14 + 8:0x14 + 12] = P(isize)
    hdr[0x20 + 4:0x20 + 8] = P(0x40 + isize); hdr[0x20 + 8:0x20 + 12] = P(fsize)
    return bytes(hdr) + info + fileb, list(range(n, len(entries)))
