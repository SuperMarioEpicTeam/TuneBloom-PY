"""Lecture / modification d'un BFSAR (Binary caFe Sound ARchive), port de snd_SoundArchiveFile.h."""
import os
from dataclasses import dataclass, field
from typing import Optional

from .binio import Reader, detect_endian, align

# ElementType
T_STRING_BLOCK, T_INFO_BLOCK, T_FILE_BLOCK = 0x2000, 0x2001, 0x2002
T_SND_STRM, T_SND_WAVE, T_SND_SEQ = 0x2201, 0x2202, 0x2203
T_FILE_INTERNAL, T_FILE_EXTERNAL = 0x220C, 0x220D

ITEM_SOUND, ITEM_SOUNDGROUP, ITEM_BANK, ITEM_PLAYER, ITEM_WARC, ITEM_GROUP = 1, 2, 3, 4, 5, 6
ITEM_NAMES = {1: "Sound", 2: "SoundGroup", 3: "Bank", 4: "Player", 5: "WaveArchive", 6: "Group"}
SOUND_TYPE_NAMES = {T_SND_STRM: "Stream", T_SND_WAVE: "Wave", T_SND_SEQ: "Sequence"}
MAGIC_EXT = {b"FSTM": ".bfstm", b"FWAV": ".bfwav", b"FWAR": ".bfwar", b"FSEQ": ".bfseq",
             b"FBNK": ".bfbnk", b"FWSD": ".bfwsd", b"FGRP": ".bfgrp", b"FSTP": ".bfstp"}
INVALID = 0xFFFFFFFF


@dataclass
class Item:
    kind: int                      # ITEM_*
    index: int
    name: Optional[str]
    file_id: int = INVALID
    sound_type: int = 0            # T_SND_* pour les sons
    extra: dict = field(default_factory=dict)

    @property
    def item_id(self):
        return (self.kind << 24) | self.index

    @property
    def label(self):
        return self.name or f"{ITEM_NAMES[self.kind]}_{self.index}"


@dataclass
class FileEntry:
    index: int
    internal: bool
    offset: int = 0                # relatif au corps du bloc FILE
    size: int = 0
    path: str = ""                 # pour les fichiers externes
    ref_addr: int = 0              # adresse (dans le BFSAR) de la ReferenceWithSize interne


class BfsarError(Exception):
    pass


def read_bfgrp(data: bytes) -> dict:
    """BFGRP -> {fileId du BFSAR: bytes}. Les entrées « lien » (offset = -1) sont ignorées."""
    if data[:4] != b"FGRP":
        raise BfsarError("Pas un BFGRP")
    data = memoryview(data)
    r = Reader(data, detect_endian(data))
    blocks = {}
    for i in range(r.u16(16)):
        b = 0x14 + 12 * i
        blocks[r.u16(b)] = r.s32(b + 4)
    info = blocks[0x7800] + 8
    fbody = blocks[0x7801] + 8
    out = {}
    for i in range(r.u32(info)):
        a = info + r.s32(info + 4 + 8 * i + 4)
        file_id, off, size = r.u32(a), r.u32(a + 8), r.u32(a + 12)
        if off != INVALID:
            out[file_id] = data[fbody + off:fbody + off + size]
    return out


class Bfsar:
    def __init__(self, data: bytes, path: Optional[str] = None):
        if data[:4] != b"FSAR":
            raise BfsarError("Signature FSAR absente : ce n'est pas un BFSAR")
        self.data = bytearray(data)
        self.path = path
        self.external = {}          # file_id -> données, alimenté par les BFGRP chargés
        self._internal_groups_done = False
        self._warc_cache = {}
        self._file_group = {}       # fileId -> fileId du BFGRP interne qui le contient
        self.endian = detect_endian(data)
        self.r = Reader(self.data, self.endian)
        self.version = self.r.u32(8)
        self._parse()

    # ---------- chargement ----------
    @classmethod
    def open(cls, path):
        with open(path, "rb") as f:
            return cls(f.read(), path)

    def _parse(self):
        r = self.r
        self.blocks = {}
        for i in range(r.u16(16)):
            b = 0x14 + 12 * i
            self.blocks[r.u16(b)] = dict(ref=b, off=r.s32(b + 4), size=r.u32(b + 8))
        for need in (T_INFO_BLOCK, T_FILE_BLOCK):
            if need not in self.blocks:
                raise BfsarError("Bloc INFO ou FILE manquant")
        self.strings = self._read_strings()
        ib = self.blocks[T_INFO_BLOCK]["off"] + 8
        tables = {}
        for k, name in enumerate(("sound", "soundgroup", "bank", "warc", "group", "player", "file", "playerinfo")):
            off = r.s32(ib + 8 * k + 4)
            tables[name] = (ib + off) if off > 0 else None
        self.tables = tables
        self.sounds = self._read_items(ITEM_SOUND, "sound")
        self.soundgroups = self._read_items(ITEM_SOUNDGROUP, "soundgroup")
        self.banks = self._read_items(ITEM_BANK, "bank")
        self.warcs = self._read_items(ITEM_WARC, "warc")
        self.groups = self._read_items(ITEM_GROUP, "group")
        self.players = self._read_items(ITEM_PLAYER, "player")
        self.files = self._read_files()

    def _read_strings(self):
        blk = self.blocks.get(T_STRING_BLOCK)
        if not blk:
            return []
        r = self.r
        body = blk["off"] + 8
        tbl = body + r.s32(body + 4)
        out = []
        for i in range(r.u32(tbl)):
            off = r.s32(tbl + 4 + 12 * i + 4)
            out.append(r.cstr(tbl + off))
        return out

    def _name(self, string_id):
        if string_id is None or string_id == INVALID or string_id >= len(self.strings):
            return None
        return self.strings[string_id]

    def _ref_table(self, name):
        t = self.tables.get(name)
        if t is None:
            return []
        r = self.r
        return [t + r.s32(t + 4 + 8 * i + 4) for i in range(r.u32(t))]

    def _read_items(self, kind, table):
        r = self.r
        items = []
        for idx, a in enumerate(self._ref_table(table)):
            it = Item(kind, idx, None)
            if kind == ITEM_SOUND:
                it.file_id = r.u32(a)
                it.extra["player_id"] = r.u32(a + 4)
                it.extra["volume"] = r.u8(a + 8)
                it.sound_type = r.u16(a + 12)
                detail = a + r.s32(a + 16)
                it.name = self._name(r.bitflag(a + 20, 0))
                if it.sound_type == T_SND_STRM:
                    it.extra["channels"] = r.u16(detail + 2)
                    it.extra["pitch"] = r.f32(detail + 12)
                    ext_off = r.s32(detail + 28)
                    if r.u16(detail + 24) == 0x2210 and ext_off != -1:
                        ext = detail + ext_off
                        it.extra["loop"] = (r.u32(ext) >> 8) & 0xFF == 1
                        it.extra["loop_start"] = r.u32(ext + 4)
                        it.extra["loop_end"] = r.u32(ext + 8)
                elif it.sound_type == T_SND_WAVE:
                    it.extra["wsd_index"] = r.u32(detail)
                elif it.sound_type == T_SND_SEQ:
                    tbl = detail + r.s32(detail + 4)
                    it.extra["bank_ids"] = [r.u32(tbl + 4 + 4 * i) for i in range(r.u32(tbl))]
                    it.extra["start_offset"] = r.bitflag(detail + 12, 0)
            elif kind == ITEM_BANK:
                it.file_id = r.u32(a)
                it.name = self._name(r.bitflag(a + 12, 0))
                tbl = a + r.s32(a + 8)
                it.extra["warc_ids"] = [r.u32(tbl + 4 + 4 * i) for i in range(r.u32(tbl))]
            elif kind == ITEM_WARC:
                it.file_id = r.u32(a)
                it.extra["load_individual"] = bool(r.u8(a + 4))
                it.name = self._name(r.bitflag(a + 8, 0))
                it.extra["wave_count"] = r.bitflag(a + 8, 1)
            elif kind == ITEM_GROUP:
                it.file_id = r.u32(a)
                it.name = self._name(r.bitflag(a + 4, 0))
            elif kind == ITEM_PLAYER:
                it.extra["playable_sound_max"] = r.u32(a)
                it.name = self._name(r.bitflag(a + 4, 0))
            elif kind == ITEM_SOUNDGROUP:
                it.extra["start_id"], it.extra["end_id"] = r.u32(a), r.u32(a + 4)
                it.name = self._name(r.bitflag(a + 24, 0))
                it.extra["wave"] = r.u16(a + 16) == 0x2205
                if it.extra["wave"]:
                    det = a + r.s32(a + 20)
                    t = det + r.s32(det + 4)
                    it.extra["warc_ids"] = [r.u32(t + 4 + 4 * i) for i in range(r.u32(t))]
            items.append(it)
        return items

    def _read_files(self):
        r = self.r
        files = []
        for idx, a in enumerate(self._ref_table("file")):
            typ = r.u16(a)
            loc = a + r.s32(a + 4) if r.s32(a + 4) != -1 else None
            if typ == T_FILE_INTERNAL and loc is not None:
                files.append(FileEntry(idx, True, r.u32(loc + 4), r.u32(loc + 8), ref_addr=loc))
            elif typ == T_FILE_EXTERNAL and loc is not None:
                files.append(FileEntry(idx, False, path=r.cstr(loc)))
            else:
                files.append(FileEntry(idx, False))
        return files

    # ---------- accès aux fichiers ----------
    def file_bytes(self, file_id) -> Optional[bytes]:
        if file_id == INVALID or file_id >= len(self.files):
            return None
        fe = self.files[file_id]
        if file_id in self.external:
            return self.external[file_id]
        if fe.internal and fe.offset == INVALID and not self._internal_groups_done:
            self._attach_internal_groups()
            if file_id in self.external:
                return self.external[file_id]
        if fe.internal:
            if fe.offset == INVALID:
                return None
            start = self.blocks[T_FILE_BLOCK]["off"] + 8 + fe.offset
            return bytes(self.data[start:start + fe.size])
        if fe.path and self.path:
            base = os.path.dirname(os.path.abspath(self.path))
            for cand in (os.path.join(base, fe.path.replace("\\", "/")),
                         os.path.join(base, os.path.basename(fe.path)),
                         os.path.join(os.path.dirname(base), fe.path.replace("\\", "/"))):
                if os.path.isfile(cand):
                    with open(cand, "rb") as f:
                        return f.read()
        return None

    def _attach_internal_groups(self):
        """Les BFGRP stockés dans le BFSAR (ex. NSMBU) fournissent les fichiers dont l'offset est invalide."""
        self._internal_groups_done = True
        for g in self.groups:
            if g.file_id != INVALID and g.file_id < len(self.files) and self.files[g.file_id].internal \
                    and self.files[g.file_id].offset != INVALID:
                blob = self.file_bytes(g.file_id)
                if blob and bytes(blob[:4]) == b"FGRP":
                    try:
                        for fid, v in read_bfgrp(blob).items():
                            self.external.setdefault(fid, v)
                            self._file_group.setdefault(fid, g.file_id)
                    except Exception:
                        pass

    def wave_blobs_for_sound(self, sound):
        """Pour un son de type Wave : liste des BFWAV (un par « note »), résolus via BFWSD -> BFWAR."""
        from .wsd import read_bfwsd
        from .formats import split_bfwar
        wsd = self.file_bytes(sound.file_id)
        if not wsd:
            raise BfsarError("BFWSD indisponible (fournissez le BFGRP correspondant)")
        wave_ids, sounds = read_bfwsd(wsd)
        idx = sound.extra.get("wsd_index", 0)
        out = []
        for wid_index in sounds[idx]:
            warc_id, wave_index = wave_ids[wid_index]
            warc = self.warcs[warc_id & 0xFFFFFF]
            if warc.file_id not in self._warc_cache:
                blob = self.file_bytes(warc.file_id)
                if not blob:
                    raise BfsarError(f"Archive de vagues {warc.label} indisponible (BFGRP manquant)")
                self._warc_cache[warc.file_id] = split_bfwar(blob)
            waves = self._warc_cache[warc.file_id]
            if wave_index >= len(waves) or waves[wave_index] is None:
                raise BfsarError(f"Vague {wave_index} absente de {warc.label}")
            out.append(waves[wave_index])
        return out

    def wave_location(self, sound):
        """(warc, index_vague) de la première note d'un son Wave."""
        from .wsd import read_bfwsd
        wsd = self.file_bytes(sound.file_id)
        if not wsd:
            raise BfsarError("BFWSD indisponible")
        wave_ids, sounds = read_bfwsd(wsd)
        warc_id, wave_index = wave_ids[sounds[sound.extra.get("wsd_index", 0)][0]]
        return self.warcs[warc_id & 0xFFFFFF], wave_index

    def replace_wave(self, sound, new_bfwav: bytes):
        """Remplace la vague d'un son Wave : reconstruit le BFWAR (et le BFGRP interne si besoin) puis le BFSAR."""
        from .bfwar import rebuild_bfwar, rebuild_bfgrp
        warc, idx = self.wave_location(sound)
        old = self.file_bytes(warc.file_id)
        if old is None:
            raise BfsarError("Archive de vagues indisponible")
        new_warc = rebuild_bfwar(old, {idx: new_bfwav})
        fe = self.files[warc.file_id]
        if fe.internal and fe.offset != INVALID:
            self.replace_file(warc.file_id, new_warc)
            return
        self.file_bytes(warc.file_id)                      # force le chargement des groupes internes
        gid = self._file_group.get(warc.file_id)
        if gid is None:
            raise BfsarError("Cette archive de vagues est dans un BFGRP externe : modifiez le .bfgrp (commande replace-in-grp)")
        new_grp = rebuild_bfgrp(self.file_bytes(gid), {warc.file_id: new_warc})
        self.replace_file(gid, new_grp)

    def attach_group(self, grp_data: bytes) -> int:
        """Charge un BFGRP externe : fournit les fichiers dont le BFSAR ne contient pas les données. Renvoie le nombre de fichiers."""
        files = read_bfgrp(grp_data)
        self.external.update(files)
        return len(files)

    @staticmethod
    def extension_for(blob: bytes) -> str:
        return MAGIC_EXT.get(bytes(blob[:4]), ".bin")

    def all_items(self):
        return (self.sounds + self.soundgroups + self.banks + self.warcs + self.groups + self.players)

    # ---------- modification : remplacement d'un fichier interne ----------
    def replace_file(self, file_id: int, new_data: bytes, alignment: int = 0x20):
        """Remplace un fichier interne et décale tous les suivants. Le bloc FILE doit être le dernier du BFSAR."""
        fe = self.files[file_id]
        if not fe.internal or fe.offset == INVALID:
            raise BfsarError("Ce fichier n'est pas interne au BFSAR (fichier externe) : remplacez-le directement sur le disque")
        fb = self.blocks[T_FILE_BLOCK]
        if any(b["off"] > fb["off"] for k, b in self.blocks.items() if k != T_FILE_BLOCK):
            raise BfsarError("Le bloc FILE n'est pas le dernier du BFSAR : cas non géré")
        body_start = fb["off"] + 8
        body_len = fb["size"] - 8
        internal = [f for f in self.files if f.internal and f.offset != INVALID]
        old_off = fe.offset
        later = sorted({f.offset for f in internal if f.offset > old_off})
        old_end = later[0] if later else body_len
        new_span = align(len(new_data), alignment)
        delta = new_span - (old_end - old_off)

        d = self.data
        w = lambda o, v: d.__setitem__(slice(o, o + 4), v.to_bytes(4, "big" if self.endian == ">" else "little"))
        # 1) mettre à jour les entrées FileInfo
        for f in internal:
            if f.offset == old_off:
                w(f.ref_addr + 8, len(new_data))
            elif f.offset > old_off:
                w(f.ref_addr + 4, f.offset + delta)
        # 2) reconstruire le corps du bloc FILE
        body = bytes(d[body_start:body_start + body_len])
        new_body = body[:old_off] + new_data + b"\x00" * (new_span - len(new_data)) + body[old_end:]
        # 3) tailles : bloc FILE, entrée d'en-tête, taille du fichier
        new_blk_size = fb["size"] + delta
        w(fb["ref"] + 8, new_blk_size)
        w(body_start - 4, new_blk_size)
        tail = bytes(d[fb["off"] + fb["size"]:])
        self.data = bytearray(bytes(d[:body_start]) + new_body + tail)
        self.r = Reader(self.data, self.endian)
        w2 = lambda o, v: self.data.__setitem__(slice(o, o + 4), v.to_bytes(4, "big" if self.endian == ">" else "little"))
        w2(12, len(self.data))
        self.external, self._warc_cache, self._file_group, self._internal_groups_done = {}, {}, {}, False
        self._parse()

    def save(self, path):
        with open(path, "wb") as f:
            f.write(self.data)
