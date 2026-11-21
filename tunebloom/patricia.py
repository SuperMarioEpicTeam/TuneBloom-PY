"""Arbre Patricia des noms d'un BFSAR (port de PatriciaTree : recherche + construction par insertion)."""
import struct

LEAF = 1


class Node:
    __slots__ = ("flags", "bit", "left", "right", "sid", "iid")

    def __init__(self, flags=0, bit=0xFFFF, left=0xFFFFFFFF, right=0xFFFFFFFF, sid=0xFFFFFFFF, iid=0xFFFFFFFF):
        self.flags, self.bit, self.left, self.right, self.sid, self.iid = flags, bit, left, right, sid, iid

    def key(self):
        return (self.flags, self.bit, self.left, self.right, self.sid, self.iid)


def _bit(key: bytes, bit: int) -> int:
    pos = bit >> 3
    return 1 if pos < len(key) and key[pos] & (1 << (7 - (bit & 7))) else 0


class Tree:
    def __init__(self):
        self.nodes, self.root, self.keys = [], 0, {}      # keys : stringId -> octets (pour comparer lors des insertions)

    def search_leaf(self, key: bytes) -> Node:
        n = self.nodes[self.root]
        while not n.flags & LEAF:
            n = self.nodes[n.right if _bit(key, n.bit) else n.left]
        return n

    def find(self, name: str):
        """-> (stringId, itemId) si le nom est présent."""
        if not self.nodes:
            return None
        k = name.encode()
        n = self.search_leaf(k)
        return (n.sid, n.iid) if self.keys.get(n.sid) == k else None

    def insert(self, name: str, sid: int, iid: int):
        k = name.encode()
        self.keys[sid] = k
        if not self.nodes:
            self.nodes.append(Node(LEAF, 0xFFFF, sid=sid, iid=iid)); self.root = 0
            return
        other = self.keys[self.search_leaf(k).sid]
        # premier bit différent (les octets absents valent 0, comme dans la recherche)
        n_bits = max(len(k), len(other)) * 8
        diff = next((b for b in range(n_bits) if _bit(k, b) != _bit(other, b)), None)
        if diff is None:
            raise ValueError(f"Nom en double : {name}")
        parent, side, cur = None, None, self.root
        while not self.nodes[cur].flags & LEAF and self.nodes[cur].bit < diff:
            parent = cur
            side = _bit(k, self.nodes[cur].bit)
            cur = self.nodes[cur].right if side else self.nodes[cur].left
        leaf = len(self.nodes)
        self.nodes.append(Node(LEAF, 0xFFFF, sid=sid, iid=iid))
        inner = len(self.nodes)
        nn = Node(0, diff)
        if _bit(k, diff):
            nn.left, nn.right = cur, leaf
        else:
            nn.left, nn.right = leaf, cur
        self.nodes.append(nn)
        if parent is None:
            self.root = inner
        elif side:
            self.nodes[parent].right = inner
        else:
            self.nodes[parent].left = inner

    def pack(self, endian=">"):
        e = endian
        out = struct.pack(e + "II", self.root, len(self.nodes))
        for n in self.nodes:
            out += struct.pack(e + "HHIIII", n.flags, n.bit, n.left, n.right, n.sid, n.iid)
        return out

    @classmethod
    def unpack(cls, data, off, strings, endian=">"):
        e = endian
        t = cls()
        t.root, n = struct.unpack_from(e + "II", data, off)
        for i in range(n):
            f, b, l, r, s, it = struct.unpack_from(e + "HHIIII", data, off + 8 + 20 * i)
            t.nodes.append(Node(f, b, l, r, s, it))
            if f & LEAF and s != 0xFFFFFFFF:
                t.keys[s] = strings[s].encode()
        return t
