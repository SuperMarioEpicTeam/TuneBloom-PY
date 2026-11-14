"""Petits utilitaires de lecture binaire (endianness gérée par l'en-tête NintendoWare)."""
import struct


def detect_endian(data: bytes) -> str:
    """Octets 4-5 de l'en-tête : FE FF = big endian (Wii U), FF FE = little endian."""
    bom = bytes(data[4:6])
    if bom == b"\xfe\xff":
        return ">"
    if bom == b"\xff\xfe":
        return "<"
    raise ValueError("Marque d'ordre des octets (BOM) invalide")


class Reader:
    def __init__(self, data, endian: str = ">"):
        self.d = data
        self.e = endian

    def u8(self, o):  return self.d[o]
    def u16(self, o): return struct.unpack_from(self.e + "H", self.d, o)[0]
    def s16(self, o): return struct.unpack_from(self.e + "h", self.d, o)[0]
    def u32(self, o): return struct.unpack_from(self.e + "I", self.d, o)[0]
    def s32(self, o): return struct.unpack_from(self.e + "i", self.d, o)[0]
    def f32(self, o): return struct.unpack_from(self.e + "f", self.d, o)[0]

    def cstr(self, o):
        end = self.d.index(b"\x00", o)
        return bytes(self.d[o:end]).decode("utf-8", "replace")

    def bitflag(self, addr, bit):
        """Équivalent de Util::BitFlag::GetValue : renvoie la valeur u32 ou None."""
        flag = self.u32(addr)
        if not (flag >> bit) & 1:
            return None
        count = bin(flag & ((1 << (bit + 1)) - 1)).count("1")
        return self.u32(addr + count * 4)


def align(v, a):
    return (v + a - 1) // a * a
