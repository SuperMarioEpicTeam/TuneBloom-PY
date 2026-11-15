"""NintendoWare binary container reader with conservative, lossless handling.

The layout follows TuneBloom's own snd/ut/ut_BinaryFileFormat.h and
bfsar/writer/FileWriter.cpp. Unknown blocks and padding are retained verbatim.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct
from pathlib import Path


class BinaryFormatError(ValueError):
    """Raised when a NintendoWare binary container is malformed or truncated."""


@dataclass(frozen=True)
class BlockReference:
    type_id: int
    offset: int
    size: int
    table_index: int


@dataclass(frozen=True)
class BinaryBlock:
    reference: BlockReference
    magic: str
    declared_size: int
    data: bytes


class NintendoWareFile:
    """Parsed NintendoWare file; source bytes are kept for safe round-tripping."""

    HEADER_SIZE = 0x14
    REFERENCE_SIZE = 0x0C

    def __init__(self, raw: bytes):
        self.raw = bytes(raw)
        if len(raw) < self.HEADER_SIZE:
            raise BinaryFormatError("File is shorter than the 0x14-byte NintendoWare header")
        self.magic = raw[:4].decode("ascii", errors="replace")
        bom = raw[4:6]
        if bom == b"\xfe\xff":
            self.endian = ">"
            self.byte_order = "big-endian"
        elif bom == b"\xff\xfe":
            self.endian = "<"
            self.byte_order = "little-endian"
        else:
            raise BinaryFormatError(f"Invalid byte-order mark: {bom.hex(' ')}")
        self.header_size, = self._unpack("H", 6)
        self.version, self.file_size, self.block_count, self.reserved = self._unpack("IIHH", 8)
        if self.header_size < self.HEADER_SIZE + self.block_count * self.REFERENCE_SIZE:
            raise BinaryFormatError("Header size is too small for its block-reference table")
        if self.header_size > len(raw):
            raise BinaryFormatError("Header extends beyond end of file")
        if self.file_size < self.header_size or self.file_size > len(raw):
            raise BinaryFormatError(
                f"Declared file size 0x{self.file_size:X} is outside available data (0x{len(raw):X})"
            )
        self.trailing_data = raw[self.file_size:]
        self.references: list[BlockReference] = []
        self.blocks: list[BinaryBlock] = []
        self._parse_blocks()

    @classmethod
    def from_path(cls, path: str | Path) -> "NintendoWareFile":
        return cls(Path(path).read_bytes())

    def _unpack(self, fmt: str, offset: int):
        size = struct.calcsize(self.endian + fmt)
        if offset < 0 or offset + size > len(self.raw):
            raise BinaryFormatError(f"Read outside file at 0x{offset:X} (size 0x{size:X})")
        return struct.unpack_from(self.endian + fmt, self.raw, offset)

    def _parse_blocks(self) -> None:
        for index in range(self.block_count):
            pos = self.HEADER_SIZE + index * self.REFERENCE_SIZE
            type_id, _padding, offset, size = self._unpack("HH i I", pos)
            ref = BlockReference(type_id, offset, size, index)
            self.references.append(ref)
            if offset == -1 or size == 0xFFFFFFFF:
                self.blocks.append(BinaryBlock(ref, "", 0, b""))
                continue
            if offset < self.header_size or size < 8 or offset + size > self.file_size:
                raise BinaryFormatError(
                    f"Block #{index} has invalid range offset=0x{offset:X}, size=0x{size:X}"
                )
            magic = self.raw[offset:offset + 4].decode("ascii", errors="replace")
            declared_size, = self._unpack("I", offset + 4)
            if declared_size < 8 or declared_size > size:
                raise BinaryFormatError(
                    f"Block #{index} ({magic}) declares invalid size 0x{declared_size:X}; table says 0x{size:X}"
                )
            block_data = self.raw[offset:offset + size]
            self.blocks.append(BinaryBlock(ref, magic, declared_size, block_data))

    def blocks_by_magic(self, magic: str) -> list[BinaryBlock]:
        return [block for block in self.blocks if block.magic == magic]

    def block_by_type(self, type_id: int) -> BinaryBlock | None:
        return next((b for b in self.blocks if b.reference.type_id == type_id), None)

    def summary(self) -> dict:
        return {
            "magic": self.magic,
            "byte_order": self.byte_order,
            "header_size": self.header_size,
            "version": f"0x{self.version:08X}",
            "file_size": self.file_size,
            "block_count": self.block_count,
            "blocks": [
                {"type_id": f"0x{b.reference.type_id:04X}", "magic": b.magic or "(null)",
                 "offset": b.reference.offset, "size": b.reference.size}
                for b in self.blocks
            ],
        }

    def replace_block_same_size(self, index: int, block_bytes: bytes) -> bytes:
        """Patch one block without moving anything or invalidating relative offsets.

        Resizing is deliberately rejected: inner NintendoWare references may be
        relative to structures inside a block and cannot safely be relocated here.
        """
        ref = self.references[index]
        if ref.offset < 0:
            raise BinaryFormatError("Cannot replace a null block")
        if len(block_bytes) != ref.size:
            raise BinaryFormatError("Safe patch requires exactly the original block size")
        if block_bytes[:4] != self.raw[ref.offset:ref.offset + 4]:
            raise BinaryFormatError("Block magic cannot be changed by a same-size patch")
        declared, = struct.unpack(self.endian + "I", block_bytes[4:8])
        if declared < 8 or declared > len(block_bytes):
            raise BinaryFormatError("Replacement block has an invalid declared size")
        patched = bytearray(self.raw)
        patched[ref.offset:ref.offset + ref.size] = block_bytes
        return bytes(patched)


def read_nintendo_file(path: str | Path) -> NintendoWareFile:
    return NintendoWareFile.from_path(path)
