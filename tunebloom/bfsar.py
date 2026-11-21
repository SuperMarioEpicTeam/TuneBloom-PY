"""Lecture / modification d'un BFSAR (Binary caFe Sound ARchive), port de snd_SoundArchiveFile.h."""
import os
import struct
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
        self._ext_groups = []       # BFGRP externes attachés : dict(path, data, dirty)
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

    def _reset_caches(self):
        self.external, self._warc_cache, self._file_group, self._internal_groups_done = {}, {}, {}, False
        for g in self._ext_groups:                         # les BFGRP externes restent attachés
            self.external.update(read_bfgrp(g["data"]))

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
        self.replace_any_file(warc.file_id, new_warc)

    def _locate_in_group(self, gid, fid):
        """Offset absolu (dans self.data) du fichier fid stocké dans le BFGRP interne gid, ou None."""
        gfe = self.files[gid]
        gstart = self.blocks[T_FILE_BLOCK]["off"] + 8 + gfe.offset
        g = self.data
        e = self.endian
        u32 = lambda o: struct.unpack_from(e + "I", g, gstart + o)[0]
        s32 = lambda o: struct.unpack_from(e + "i", g, gstart + o)[0]
        u16 = lambda o: struct.unpack_from(e + "H", g, gstart + o)[0]
        info = fbody = None
        for i in range(u16(16)):
            t = u16(0x14 + 12 * i)
            if t == 0x7800: info = u32(0x14 + 12 * i + 4) + 8
            if t == 0x7801: fbody = u32(0x14 + 12 * i + 4) + 8
        for i in range(u32(info)):
            a = info + s32(info + 4 + 8 * i + 4)
            if u32(a) == fid:
                off, size = u32(a + 8), u32(a + 12)
                return None if off == INVALID else (gstart + fbody + off, size)
        return None

    def _internal_group_ids(self):
        return [g.file_id for g in self.groups if g.file_id != INVALID and g.file_id < len(self.files)
                and self.files[g.file_id].internal and self.files[g.file_id].offset != INVALID]

    def replace_any_file(self, fid: int, data: bytes):
        """Remplace un fichier dans TOUTES ses copies : BFGRP externes attachés, BFGRP internes qui le contiennent, copie directe du
        BFSAR. (Un même fichier peut exister à plusieurs endroits ; la lecture préfère les groupes, d'où cette cohérence.)"""
        from .bfwar import rebuild_bfgrp
        data = bytes(data)
        done = False
        for g in self._ext_groups:                           # 1) BFGRP externes (réécrits à la sauvegarde)
            if fid in read_bfgrp(g["data"]):
                g["data"] = rebuild_bfgrp(g["data"], {fid: data})
                g["dirty"] = True
                done = True
        for gid in self._internal_group_ids():               # 2) BFGRP internes contenant ce fichier
            loc = self._locate_in_group(gid, fid)
            if not loc:
                continue
            done = True
            if loc[1] == len(data):
                self.data[loc[0]:loc[0] + len(data)] = data
            else:
                fe_g = self.files[gid]
                gstart = self.blocks[T_FILE_BLOCK]["off"] + 8 + fe_g.offset
                grp = bytes(self.data[gstart:gstart + fe_g.size])
                self.replace_file(gid, rebuild_bfgrp(grp, {fid: data}))
        fe = self.files[fid]
        if fe.internal and fe.offset != INVALID:             # 3) copie directe
            if fe.size == len(data):
                start = self.blocks[T_FILE_BLOCK]["off"] + 8 + fe.offset
                self.data[start:start + len(data)] = data
            else:
                self.replace_file(fid, data)
            done = True
        if not done:
            raise BfsarError("Fichier introuvable (BFGRP externe non chargé ?)")
        self._reset_caches()

    def set_sound_start_offset(self, sound, value: int):
        """Écrit l'offset de départ d'un son séquence (valeur déjà présente dans l'option bitflag)."""
        a = self._ref_table("sound")[sound.index]
        detail = a + self.r.s32(a + 16)
        if not self.r.u32(detail + 12) & 1:
            raise BfsarError("Offset de départ absent de ce son")
        self.data[detail + 16:detail + 20] = value.to_bytes(4, "big" if self.endian == ">" else "little")
        sound.extra["start_offset"] = value

    def attach_group(self, grp_data: bytes, path=None) -> int:
        """Charge un BFGRP externe : fournit les fichiers dont le BFSAR ne contient pas les données. Renvoie le nombre de fichiers.
        Si `path` est donné, les modifications de ses fichiers seront réécrites dedans à la sauvegarde."""
        grp_data = bytes(grp_data)
        files = read_bfgrp(grp_data)
        self._ext_groups.append(dict(path=path, data=grp_data, dirty=False))
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
        self._reset_caches()
        self._parse()

    def save(self, path):
        with open(path, "wb") as f:
            f.write(self.data)
        for g in self._ext_groups:                         # BFGRP externes modifiés : réécrits à leur emplacement d'origine
            if g["dirty"] and g["path"]:
                with open(g["path"], "wb") as f:
                    f.write(g["data"])
                g["dirty"] = False

    def dirty_groups(self):
        return [g["path"] for g in self._ext_groups if g["dirty"]]


# ======================================================================================
#  Édition structurelle : renommer / dupliquer / ajouter des sons  (STRG + tables INFO)
# ======================================================================================
_TABLES = ("sound", "soundgroup", "bank", "warc", "group", "player", "file", "playerinfo")
_NAME_ADDR = {ITEM_SOUND: 20, ITEM_SOUNDGROUP: 24, ITEM_BANK: 12, ITEM_WARC: 8, ITEM_GROUP: 4, ITEM_PLAYER: 4}
_KIND_TABLE = {ITEM_SOUND: "sound", ITEM_SOUNDGROUP: "soundgroup", ITEM_BANK: "bank", ITEM_WARC: "warc", ITEM_GROUP: "group", ITEM_PLAYER: "player"}


def _pk(self, fmt, *a):
    return struct.pack(("<" if self.endian == "<" else ">") + fmt, *a)


def _set_block(self, btype, new):
    """Remplace un bloc entier (STRG / INFO) et décale les blocs suivants, puis ré-analyse."""
    blk = self.blocks[btype]
    delta = len(new) - blk["size"]
    d = self.data
    P = lambda v: self._pk("I", v)
    d[blk["off"]:blk["off"] + blk["size"]] = new
    for t, b in self.blocks.items():
        if t == btype:
            d[b["ref"] + 8:b["ref"] + 12] = P(len(new))
        elif b["off"] > blk["off"]:
            d[b["ref"] + 4:b["ref"] + 8] = P(b["off"] + delta)
    d[12:16] = P(len(d))
    self._reset_caches()
    self._parse()


def _string_id(self, kind, index):
    a = self._ref_table(_KIND_TABLE[kind])[index]
    return self.r.bitflag(a + _NAME_ADDR[kind], 0)


def _apply_strings(self, strings, order, iid):
    from .strblock import build_string_block, rebuild_tree
    self._set_block(T_STRING_BLOCK, build_string_block(strings, rebuild_tree(strings, order, iid), self.endian))


def _tree_state(self):
    from .strblock import read_tree
    _, order, iid = read_tree(self)
    return list(self.strings), order, iid


def _check_name(name):
    if not name or any(ord(c) > 126 or ord(c) < 33 for c in name):
        raise BfsarError("Nom invalide : caractères ASCII visibles uniquement, sans espace")


def rename_item(self, kind, index, newname):
    """Renomme un élément (son, banque, archive, groupe, player…) : met à jour la table de chaînes ET l'arbre de recherche."""
    _check_name(newname)
    sid = _string_id(self, kind, index)
    if sid is None:
        raise BfsarError("Cet élément n'a pas de nom stocké")
    strings, order, iid = _tree_state(self)
    if newname == strings[sid]:
        return
    if newname in strings:
        raise BfsarError(f"Le nom {newname} existe déjà")
    strings[sid] = newname
    _apply_strings(self, strings, order, iid)


def _insert_info_item(self, table, item: bytes):
    """Ajoute un élément à la fin d'une table INFO (la table ne doit pas être la dernière)."""
    r = self.r
    blk = self.blocks[T_INFO_BLOCK]
    ib = blk["off"] + 8
    offs = {k: r.s32(ib + 8 * i + 4) for i, k in enumerate(_TABLES)}
    later = sorted(v for v in offs.values() if v > offs[table])
    if not later:
        raise BfsarError("Insertion dans la dernière table non gérée")
    t, t_end = ib + offs[table], ib + later[0]
    n = r.u32(t)
    old = bytes(self.data[t:t_end])
    refs = [(r.u16(t + 4 + 8 * i), r.s32(t + 4 + 8 * i + 4)) for i in range(n)]
    head, items = 4 + 8 * n, old[4 + 8 * n:]
    item = item + b"\0" * ((-len(item)) % 4)
    new = self._pk("I", n + 1)
    for typ, off in refs:
        new += self._pk("HHi", typ, 0, off + 8)
    new += self._pk("HHi", refs[-1][0] if refs else 0x2200, 0, 4 + 8 * (n + 1) + len(items)) + items + item
    delta = len(new) - len(old)
    content_end = offs["playerinfo"] + 0x14                     # dernière table : structure fixe de 0x14 octets
    body = bytearray(self.data[ib:ib + content_end])
    body[t - ib:t_end - ib] = new
    for i, k in enumerate(_TABLES):
        if offs[k] > offs[table]:
            body[8 * i + 4:8 * i + 8] = self._pk("i", offs[k] + delta)
    size = align(8 + len(body), 0x20)
    block = b"INFO" + self._pk("I", size) + bytes(body) + b"\0" * (size - 8 - len(body))
    self._set_block(T_INFO_BLOCK, block)


def _item_span(self, table, index):
    r = self.r
    ib = self.blocks[T_INFO_BLOCK]["off"] + 8
    offs = {k: r.s32(ib + 8 * i + 4) for i, k in enumerate(_TABLES)}
    t = ib + offs[table]
    n = r.u32(t)
    later = sorted(v for v in offs.values() if v > offs[table])
    end = ib + later[0]
    s = t + r.s32(t + 4 + 8 * index + 4)
    e = t + r.s32(t + 4 + 8 * (index + 1) + 4) if index + 1 < n else end
    return s, e


def duplicate_sound(self, index, newname):
    """Copie un son (même fichier audio/séquence, nouveau nom) ; renvoie le nouvel index."""
    _check_name(newname)
    strings, order, iid = _tree_state(self)
    if newname in strings:
        raise BfsarError(f"Le nom {newname} existe déjà")
    s, e = _item_span(self, "sound", index)
    item = bytearray(self.data[s:e])
    flag = struct.unpack_from(self.endian + "I", item, 20)[0]
    if not flag & 1:
        raise BfsarError("Le son modèle n'a pas de nom (copie impossible)")
    new_index = len(self.sounds)
    sid = len(strings)
    item[24:28] = self._pk("I", sid)
    strings.append(newname)
    order.append(sid)
    iid[sid] = (ITEM_SOUND << 24) | new_index
    _insert_info_item(self, "sound", bytes(item))
    _apply_strings(self, strings, order, iid)
    return new_index


def add_stream_sound(self, newname, stream_path, template_index=None, channels=None):
    """Ajoute un son Stream pointant vers un nouveau fichier externe `stream_path` (relatif au BFSAR)."""
    _check_name(newname)
    tmpl = None
    if template_index is not None:
        tmpl = self.sounds[template_index]
    else:
        tmpl = next((x for x in self.sounds if x.sound_type == T_SND_STRM and not self.files[x.file_id].internal), None)
    if tmpl is None or tmpl.sound_type != T_SND_STRM or self.files[tmpl.file_id].internal:
        raise BfsarError("Aucun son Stream externe modèle disponible dans cette archive")
    strings, order, iid = _tree_state(self)
    if newname in strings:
        raise BfsarError(f"Le nom {newname} existe déjà")
    # 1) nouvelle entrée de fichier (copie de celle du modèle avec un nouveau chemin)
    fs, fe = _item_span(self, "file", tmpl.file_id)
    finfo = bytearray(self.data[fs:fe])
    loc = struct.unpack_from(self.endian + "i", finfo, 4)[0]
    finfo = bytes(finfo[:loc]) + stream_path.encode() + b"\0"
    new_file_id = len(self.files)
    _insert_info_item(self, "file", finfo)
    # 2) nouveau son (copie du modèle : file id, nom, nombre de canaux)
    s, e = _item_span(self, "sound", tmpl.index)
    item = bytearray(self.data[s:e])
    flag = struct.unpack_from(self.endian + "I", item, 20)[0]
    if not flag & 1:
        raise BfsarError("Le son modèle n'a pas de nom")
    sid, new_index = len(strings), len(self.sounds)
    item[0:4] = self._pk("I", new_file_id)
    item[24:28] = self._pk("I", sid)
    if channels:
        detail = struct.unpack_from(self.endian + "i", item, 16)[0]
        item[detail + 2:detail + 4] = self._pk("H", channels)
    strings.append(newname); order.append(sid); iid[sid] = (ITEM_SOUND << 24) | new_index
    _insert_info_item(self, "sound", bytes(item))
    _apply_strings(self, strings, order, iid)
    return new_index, new_file_id


def delete_sound(self, index):
    """Supprime un son : retire son élément INFO, renumérote les sons suivants (plages des jeux de sons, noms, arbre de recherche).
    Les fichiers (audio, séquence, BFWSD) ne sont pas supprimés : ils restent dans l'archive, simplement inutilisés."""
    r = self.r
    if not 0 <= index < len(self.sounds):
        raise BfsarError("Son inexistant")
    sid = _string_id(self, ITEM_SOUND, index)
    strings, order, iid = _tree_state(self)
    blk = self.blocks[T_INFO_BLOCK]
    ib = blk["off"] + 8
    offs = {k: r.s32(ib + 8 * i + 4) for i, k in enumerate(_TABLES)}
    t = ib + offs["sound"]
    n = r.u32(t)
    t_end = ib + sorted(v for v in offs.values() if v > offs["sound"])[0]
    s, e = _item_span(self, "sound", index)
    old = bytes(self.data[t:t_end])
    refs = [(r.u16(t + 4 + 8 * i), r.s32(t + 4 + 8 * i + 4)) for i in range(n)]
    items = old[4 + 8 * n:]
    base = 4 + 8 * n
    new = self._pk("I", n - 1)
    for i, (typ, off) in enumerate(refs):
        if i == index:
            continue
        new += self._pk("HHi", typ, 0, off - 8 - ((e - s) if i > index else 0))
    new += items[:s - t - base] + items[e - t - base:]
    delta = len(new) - len(old)
    content_end = offs["playerinfo"] + 0x14
    body = bytearray(self.data[ib:ib + content_end])
    body[t - ib:t_end - ib] = new
    for i, k in enumerate(_TABLES):
        if offs[k] > offs["sound"]:
            body[8 * i + 4:8 * i + 8] = self._pk("i", offs[k] + delta)
    size = align(8 + len(body), 0x20)
    self._set_block(T_INFO_BLOCK, b"INFO" + self._pk("I", size) + bytes(body) + b"\0" * (size - 8 - len(body)))
    # --- noms : retirer la chaîne `sid` et décaler les identifiants de chaînes de tous les éléments ---
    r = self.r
    for kind, addr_off in _NAME_ADDR.items():
        for a in self._ref_table(_KIND_TABLE[kind]):
            fl = r.u32(a + addr_off)
            if fl & 1:
                v = r.u32(a + addr_off + 4)
                if v != INVALID and v > sid:
                    self.data[a + addr_off + 4:a + addr_off + 8] = self._pk("I", v - 1)
    # --- plages des jeux de sons (ids bruts type<<24 | index) ---
    for a in self._ref_table("soundgroup"):
        for off in (0, 4):
            v = r.u32(a + off)
            if (v & 0xFFFFFF) > index:
                self.data[a + off:a + off + 4] = self._pk("I", (v & 0xFF000000) | ((v & 0xFFFFFF) - 1))
        st, en = r.u32(a), r.u32(a + 4)
    strings.pop(sid)
    order = [x - 1 if x > sid else x for x in order if x != sid]
    new_iid = {}
    for k, v in iid.items():
        if k == sid:
            continue
        if (v >> 24) == ITEM_SOUND and (v & 0xFFFFFF) > index:
            v = (v & 0xFF000000) | ((v & 0xFFFFFF) - 1)
        new_iid[k - 1 if k > sid else k] = v
    self._parse()
    _apply_strings(self, strings, order, new_iid)


def add_sequence_sound(self, newname, mml_body, template_index=None):
    """Crée un son Séquence : ajoute un label `newname` (+ le code MML `mml_body`) à la fin du BFSEQ du son modèle,
    puis un son qui démarre sur ce label (mêmes banques/player que le modèle). Renvoie (index_du_son, offset_de_départ)."""
    from .mml import SeqFile, disassemble
    from .mmlasm import assemble, rebuild_bfseq
    _check_name(newname)
    tmpl = self.sounds[template_index] if template_index is not None else next((x for x in self.sounds if x.sound_type == T_SND_SEQ), None)
    if tmpl is None or tmpl.sound_type != T_SND_SEQ:
        raise BfsarError("Aucun son Séquence modèle disponible dans cette archive")
    strings, _, _ = _tree_state(self)
    if newname in strings:
        raise BfsarError(f"Le nom {newname} existe déjà")
    fid = tmpl.file_id
    old = bytes(self.file_bytes(fid))
    sf = SeqFile(old)
    users = sorted({x.extra.get("start_offset") for x in self.sounds if x.sound_type == T_SND_SEQ and x.file_id == fid
                    and x.extra.get("start_offset") is not None})
    lines = disassemble(sf, users)
    text = "\n".join(t if k == "label" else "    " + t for _, t, k in lines)
    body = "\n".join(("    " + ln.strip()) if ln.strip() and not ln.strip().endswith(":") else ln.strip() for ln in mml_body.strip().split("\n"))
    if not body.strip():
        raise BfsarError("Le code MML est vide")
    code, order = assemble(text + "\n" + newname + ":\n" + body + "\n")          # AsmError (ligne N) si le code est invalide
    # 1) copie du son modèle (nom + entrée INFO), 2) remplacement du BFSEQ, 3) recalage des offsets
    old_start = {x.index: next((n for o, n in sf.labels if o == x.extra.get("start_offset")), f"Entry_{x.extra.get('start_offset', 0):04X}")
                 for x in self.sounds if x.sound_type == T_SND_SEQ and x.file_id == fid}
    new_index = self.duplicate_sound(tmpl.index, newname)
    new_file, _ = rebuild_bfseq(old, code, order)
    self.replace_any_file(fid, new_file)
    newoff = {n: o for o, n in order}
    for x in self.sounds:
        if x.sound_type == T_SND_SEQ and x.file_id == fid:
            nm = newname if x.index == new_index else old_start.get(x.index)
            if nm in newoff:
                self.set_sound_start_offset(x, newoff[nm])
    return new_index, newoff[newname]


def add_wave_sound(self, newname, bfwav: bytes, template_index=None):
    """Crée un son Wave : ajoute la vague au BFWAR du son modèle, une entrée dans son BFWSD, puis le son. Renvoie (index_son, index_vague)."""
    from .wsd import read_bfwsd
    from .wsdwrite import parse_wsd, pack_wsd, add_wave_sound_data, append_waves_to_bfwar
    _check_name(newname)
    tmpl = self.sounds[template_index] if template_index is not None else next((x for x in self.sounds if x.sound_type == T_SND_WAVE), None)
    if tmpl is None or tmpl.sound_type != T_SND_WAVE:
        raise BfsarError("Aucun son Wave modèle disponible dans cette archive")
    strings, _, _ = _tree_state(self)
    if newname in strings:
        raise BfsarError(f"Le nom {newname} existe déjà")
    wsd_old = self.file_bytes(tmpl.file_id)
    warc, _ = self.wave_location(tmpl)
    old_warc = self.file_bytes(warc.file_id)
    if wsd_old is None or old_warc is None:
        raise BfsarError("BFWSD ou archive de vagues indisponible (BFGRP externe non chargé)")
    wave_ids, sounds = read_bfwsd(wsd_old)
    warc_raw_id = wave_ids[sounds[tmpl.extra.get("wsd_index", 0)][0]][0]
    new_warc, (widx,) = append_waves_to_bfwar(old_warc, [bfwav])
    w = parse_wsd(wsd_old)
    wsd_i = add_wave_sound_data(w, tmpl.extra.get("wsd_index", 0), warc_raw_id, widx)
    self.replace_any_file(warc.file_id, new_warc)
    self.replace_any_file(tmpl.file_id, pack_wsd(w))
    new_index = self.duplicate_sound(tmpl.index, newname)
    s = self.sounds[new_index]
    a_ = self._ref_table("sound")[new_index]
    detail = a_ + self.r.s32(a_ + 16)
    self.data[detail:detail + 4] = self._pk("I", wsd_i)              # index du wave sound dans le BFWSD
    s.extra["wsd_index"] = wsd_i
    wa = self._ref_table("warc")[warc.index]                          # compteur de vagues de l'archive (si stocké)
    flag = self.r.u32(wa + 8)
    if flag & 2:
        pos = wa + 8 + 4 * bin(flag & 3).count("1")
        self.data[pos:pos + 4] = self._pk("I", self.r.u32(pos) + 1)
    self._warc_cache.clear()
    return new_index, widx


for _f in (_pk, _set_block, _insert_info_item):
    setattr(Bfsar, _f.__name__, _f)
Bfsar.rename_item = rename_item
Bfsar.duplicate_sound = duplicate_sound
Bfsar.add_stream_sound = add_stream_sound
Bfsar.add_sequence_sound = add_sequence_sound
Bfsar.add_wave_sound = add_wave_sound
Bfsar.delete_sound = delete_sound
