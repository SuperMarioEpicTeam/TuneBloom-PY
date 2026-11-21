"""Bloc STRG d'un BFSAR : table de chaînes + arbre Patricia, reconstruction exacte."""
import struct
from .binio import align
from .patricia import Tree


def build_string_block(strings, tree, endian=">"):
    e = endian
    n = len(strings)
    entries, blob, off = [], b"", 4 + 12 * n
    for s in strings:
        b = s.encode() + b"\0"
        entries.append(struct.pack(e + "HHiI", 0x1F01, 0, off, len(b)))
        blob += b
        off += len(b)
    table = struct.pack(e + "I", n) + b"".join(entries) + blob
    table += b"\0" * ((-len(table)) % 4)
    sec0 = 0x10
    sec1 = sec0 + len(table)
    body = struct.pack(e + "HHi", 0x2400, 0, sec0) + struct.pack(e + "HHi", 0x2401, 0, sec1) + table + tree.pack(e)
    size = align(8 + len(body), 0x20)
    return b"STRG" + struct.pack(e + "I", size) + body + b"\0" * (size - 8 - len(body))


def read_tree(arc):
    """Arbre Patricia du BFSAR + ordre d'insertion (ordre de création des feuilles)."""
    r = arc.r
    blk = arc.blocks[0x2000]
    body = blk["off"] + 8
    t = Tree.unpack(arc.data, body + r.s32(body + 12), arc.strings, arc.endian)
    order = [n.sid for n in t.nodes if n.flags & 1]
    iid = {n.sid: n.iid for n in t.nodes if n.flags & 1}
    return t, order, iid


def rebuild_tree(strings, order, iid):
    t = Tree()
    for sid in order:
        t.insert(strings[sid], sid, iid[sid])
    return t
