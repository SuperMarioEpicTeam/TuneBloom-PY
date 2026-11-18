"""BFBNK : instruments -> key regions -> velocity regions (port de snd_BankFile.h)."""
import struct
from dataclasses import dataclass, field
from .binio import detect_endian

T_DIRECT, T_RANGE, T_INDEX = 0x6000, 0x6001, 0x6002
T_NULL = 0x5903


@dataclass
class VelRegion:
    vmin: int
    vmax: int
    wave_index: int            # index dans la table WaveId
    warc_id: int = 0
    wave_in_warc: int = 0
    original_key: int = 60
    volume: int = 127
    pan: int = 64
    pitch: float = 1.0
    ignore_note_off: bool = False
    key_group: int = 0
    interpolation: int = 0
    adshr: tuple = (127, 127, 127, 127, 127)
    addr: dict = field(default_factory=dict)      # champ -> (adresse u32, indice d'octet) ; 'adshr' -> (adresse, None)


@dataclass
class KeyRegion:
    kmin: int
    kmax: int
    velocities: list = field(default_factory=list)


@dataclass
class Instrument:
    program: int
    regions: list = field(default_factory=list)


class Bank:
    def __init__(self, data):
        data = bytes(data)
        if data[:4] != b"FBNK":
            raise ValueError("Pas un BFBNK")
        self.d = data
        e = self.e = detect_endian(data)
        self.u32 = lambda o: struct.unpack_from(e + "I", data, o)[0]
        self.s32 = lambda o: struct.unpack_from(e + "i", data, o)[0]
        self.u16 = lambda o: struct.unpack_from(e + "H", data, o)[0]
        info = None
        for i in range(self.u16(16)):
            if self.u16(0x14 + 12 * i) == 0x5800:
                info = self.u32(0x14 + 12 * i + 4)
        body = info + 8
        wt = body + self.s32(body + 4)
        self.wave_ids = [(self.u32(wt + 4 + 8 * i), self.u32(wt + 8 + 8 * i)) for i in range(self.u32(wt))]
        it = body + self.s32(body + 12)
        self.instruments = []
        for p in range(self.u32(it)):
            typ, off = self.u16(it + 4 + 8 * p), self.s32(it + 4 + 8 * p + 4)
            ins = Instrument(p)
            if typ != T_NULL and off not in (-1, 0xFFFFFFFF):
                a = it + off
                ins.regions = self._chunk(a + self.s32(a + 4), self.u16(a), key=True)
            self.instruments.append(ins)

    def _ranges(self, chunk_addr, typ):
        """-> [(min, max, adresse_de_region)] pour un chunk direct/range/index."""
        if typ == T_DIRECT:
            return [(0, 127, chunk_addr + self.s32(chunk_addr + 4))]
        if typ == T_RANGE:
            n = self.u32(chunk_addr)
            borders = list(self.d[chunk_addr + 4:chunk_addr + 4 + n])
            refs = chunk_addr + 4 + ((n + 3) & ~3)
            out, prev = [], 0
            for i, bd in enumerate(borders):
                out.append((prev, bd, chunk_addr + self.s32(refs + 8 * i + 4)))
                prev = bd + 1
            return out
        if typ == T_INDEX:
            mn, mx = self.d[chunk_addr], self.d[chunk_addr + 1]
            out = []
            for k in range(mn, mx + 1):
                r = chunk_addr + 4 + 8 * (k - mn)
                if self.u16(r) != T_NULL and self.s32(r + 4) not in (-1,):
                    out.append((k, k, chunk_addr + self.s32(r + 4)))
            return out
        return []

    def _chunk(self, addr, typ, key):
        res = []
        for lo, hi, reg in self._ranges(addr, typ):
            if key:                               # reg = KeyRegion -> chunk de vélocité
                kr = KeyRegion(lo, hi)
                kr.velocities = self._chunk(reg + self.s32(reg + 4), self.u16(reg), key=False)
                res.append(kr)
            else:                                 # reg = VelocityRegion
                res.append(self._velregion(lo, hi, reg))
        return res

    def _velregion(self, lo, hi, a):
        flag = self.u32(a + 4)
        def val(bit):
            if not (flag >> bit) & 1:
                return None
            return self.u32(a + 4 + bin(flag & ((1 << (bit + 1)) - 1)).count("1") * 4)
        wi = self.u32(a)
        v = VelRegion(lo, hi, wi)
        if wi < len(self.wave_ids):
            v.warc_id, v.wave_in_warc = self.wave_ids[wi]
        b8 = lambda x, i: (x >> (8 * i)) & 0xFF
        if flag == 0x20F:                         # RegionParameter inline (BASIC_PARAM_FLAG)
            rp = a + 4 + 4 * 6 if False else a + 8 + 4 * bin(flag).count("1")
        def vaddr(bit):
            return a + 4 + bin(flag & ((1 << (bit + 1)) - 1)).count("1") * 4
        k = val(0);  v.original_key = b8(k, 0) if k is not None else 60
        if k is not None: v.addr["original_key"] = (vaddr(0), 0)
        k = val(1);  v.volume = b8(k, 0) if k is not None else 127
        if k is not None: v.addr["volume"] = (vaddr(1), 0)
        k = val(2);  v.pan = b8(k, 0) if k is not None else 64
        if k is not None: v.addr["pan"] = (vaddr(2), 0)
        k = val(3);  v.pitch = struct.unpack(self.e + "f", struct.pack(self.e + "I", k))[0] if k is not None else 1.0
        if k is not None: v.addr["pitch"] = (vaddr(3), "f")
        k = val(4)
        if k is not None:
            v.ignore_note_off, v.key_group, v.interpolation = b8(k, 0) > 0, b8(k, 1), b8(k, 2)
            v.addr["ignore_note_off"], v.addr["key_group"], v.addr["interp"] = (vaddr(4), 0), (vaddr(4), 1), (vaddr(4), 2)
        k = val(9)
        if k is not None:                         # offset (depuis a) vers une Reference -> AdshrCurve (5 octets)
            ref = a + k
            cur = ref + self.s32(ref + 4)
            v.adshr = tuple(self.d[cur:cur + 5])
            v.addr["adshr"] = (cur, None)
        return v
