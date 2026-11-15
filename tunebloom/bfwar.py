"""Reconstruction d'un BFWAR (archive de vagues) avec remplacement de vagues ; disposition vérifiée sur un BFWAR réel."""
import struct
from .binio import detect_endian, align

T_INFO, T_FILE = 0x6800, 0x6801
INVALID = 0xFFFFFFFF


def _relayout(orig, file_block_type, entry_addrs, replacements, base=0) -> bytes:
    """Réécrit le bloc FILE d'un conteneur (BFWAR/BFGRP) : chaque entrée garde ses octets sauf remplacement ;
    entry_addrs(u32) -> liste de (adresse_offset, adresse_taille) ; données alignées sur 0x20 dans le fichier."""
    orig = bytes(orig)
    e = detect_endian(orig)
    U32 = struct.Struct(e + "I")
    u32 = lambda o: U32.unpack_from(orig, o)[0]
    u16 = lambda o: struct.unpack_from(e + "H", orig, o)[0]
    blocks = {}
    for i in range(u16(16)):
        b = 0x14 + 12 * i
        blocks[u16(b)] = (u32(b + 4), u32(b + 8), b)
    file_off, file_size, file_ref = blocks[file_block_type]
    addrs = entry_addrs(u32)
    n = len(addrs)
    entries = [(u32(o), u32(sz)) for o, sz in addrs]
    body = file_off + 8
    for k in replacements:
        if not 0 <= k < n:
            raise ValueError(f"Index de vague invalide : {k}")

    order = sorted((i for i in range(n) if entries[i][0] != INVALID), key=lambda i: entries[i][0])
    prefix = entries[order[0]][0] if order else 0x18
    new_body = bytearray(orig[body:body + prefix])           # préfixe d'alignement du bloc FILE conservé
    new_entries = list(entries)
    placed = {}
    for i in order:
        off, size = entries[i]
        if off in placed and i not in replacements:           # vagues partageant les mêmes données
            new_entries[i] = placed[off]
            continue
        data = bytes(replacements[i]) if i in replacements else orig[body + off:body + off + size]
        pad = (-(8 + len(new_body))) % 0x20                   # début de vague aligné sur 0x20 dans le fichier
        new_body += b"\x00" * pad
        new_entries[i] = (len(new_body), len(data))
        placed[off] = new_entries[i]
        new_body += data
    new_body += b"\x00" * ((-(8 + len(new_body))) % 0x20)

    out = bytearray(orig[:file_off])                          # en-tête + bloc INFO
    for (oa, sa), (off, size) in zip(addrs, new_entries):
        if off != INVALID or True:
            U32.pack_into(out, oa, off)
            U32.pack_into(out, sa, size)
    blk = orig[file_off:file_off + 4] + U32.pack(8 + len(new_body))
    out += blk + new_body
    U32.pack_into(out, file_ref + 8, 8 + len(new_body))
    delta = (8 + len(new_body)) - file_size
    tail = orig[file_off + file_size:]                        # blocs situés après le bloc FILE (ex. 0x7802 d'un BFGRP)
    for t, (boff, bsize, bref) in blocks.items():
        if boff > file_off:
            U32.pack_into(out, bref + 4, boff + delta)
    out += tail
    U32.pack_into(out, 12, len(out))
    return bytes(out)


def rebuild_bfwar(orig, replacements: dict) -> bytes:
    """orig : BFWAR existant ; replacements : {index_vague: bytes BFWAV}. Les autres vagues sont conservées telles quelles."""
    orig = bytes(orig)
    if orig[:4] != b"FWAR":
        raise ValueError("Pas un BFWAR")
    def addrs(u32):
        info = [u32(0x14 + 12 * i + 4) for i in range(2)][0]
        n = u32(info + 8)
        return [(info + 12 + 12 * i + 4, info + 12 + 12 * i + 8) for i in range(n)]
    return _relayout(orig, T_FILE, addrs, replacements)


def rebuild_bfgrp(orig, replacements: dict) -> bytes:
    """orig : BFGRP ; replacements : {fileId du BFSAR: nouvelles données}. Les entrées « lien » (offset invalide) sont conservées."""
    orig = bytes(orig)
    if orig[:4] != b"FGRP":
        raise ValueError("Pas un BFGRP")
    # Les replacements sont indexés par fileId : on les convertit en index d'entrée
    e = detect_endian(orig)
    U = lambda o: struct.unpack_from(e + "I", orig, o)[0]
    S = lambda o: struct.unpack_from(e + "i", orig, o)[0]
    info = None
    for i in range(struct.unpack_from(e + "H", orig, 16)[0]):
        b = 0x14 + 12 * i
        if struct.unpack_from(e + "H", orig, b)[0] == 0x7800:
            info = U(b + 4) + 8
    n = U(info)
    items = [info + S(info + 4 + 8 * i + 4) for i in range(n)]
    by_fid = {U(a): i for i, a in enumerate(items)}
    idx = {}
    for fid, data in replacements.items():
        if fid not in by_fid:
            raise ValueError(f"fileId {fid} absent de ce BFGRP")
        idx[by_fid[fid]] = data
    def addrs(u32):
        return [(a + 8, a + 12) for a in items]
    return _relayout(orig, 0x7801, addrs, idx)
