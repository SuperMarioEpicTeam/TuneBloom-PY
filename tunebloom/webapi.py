"""Couche données de l'interface : traduit un Bfsar en JSON pour le front-end."""
import io, os, struct, wave, threading
from .bfsar import Bfsar, INVALID, ITEM_SOUND, SOUND_TYPE_NAMES
from . import formats
from .audio import write_wav
from .mml import SeqFile, disassemble
from .bank import Bank

ST = {0x2201: "stream", 0x2202: "wave", 0x2203: "seq"}


def magic(b):
    return bytes(b[:4]) if b else b""


class Project:
    def __init__(self):
        self.arc = None
        self.path = None
        self.dirty = False
        self.lock = threading.Lock()
        self._wavecache = {}

    # ---------- ouverture ----------
    def open(self, path, grps=()):
        arc = Bfsar.open(path)
        for g in grps:
            with open(g, "rb") as f:
                arc.attach_group(f.read())
        self.arc, self.path, self.dirty = arc, path, False
        self._wavecache.clear()

    def close(self):
        self.arc = self.path = None

    # ---------- listes ----------
    def _files_by_magic(self, mg):
        out = []
        for fe in self.arc.files:
            b = self.arc.file_bytes(fe.index)
            if b is not None and magic(b) == mg:
                out.append(fe.index)
        return out

    def file_names(self):
        names = {}
        for it in self.arc.all_items():
            if it.file_id != INVALID:
                names.setdefault(it.file_id, it.label)
        return names

    def list(self, cat):
        a = self.arc
        L = []
        if cat in ("allsounds", "stream", "wave", "seq"):
            for s in a.sounds:
                t = ST.get(s.sound_type, "?")
                if cat in ("allsounds", t):
                    L.append(dict(i=s.index, name=s.label, icon=t))
        elif cat in ("allsets", "wavesets", "seqsets"):
            for g in a.soundgroups:
                w = g.extra.get("wave", False)
                if cat == "allsets" or (cat == "wavesets") == w:
                    L.append(dict(i=g.index, name=g.label, icon="wave" if w else "seq"))
        elif cat == "banks":
            L = [dict(i=b.index, name=b.label, icon="bank") for b in a.banks]
        elif cat == "warcs":
            L = [dict(i=b.index, name=b.label, icon="warc") for b in a.warcs]
        elif cat == "groups":
            L = [dict(i=b.index, name=b.label, icon="group") for b in a.groups]
        elif cat == "players":
            L = [dict(i=b.index, name=b.label, icon="player") for b in a.players]
        elif cat in ("wavefiles", "seqfiles", "bankfiles"):
            mg = {"seqfiles": b"FSEQ", "bankfiles": b"FBNK"}.get(cat)
            names = self.file_names()
            if cat == "wavefiles":
                for w in a.warcs:
                    blob = a.file_bytes(w.file_id) if w.file_id != INVALID else None
                    if blob and magic(blob) == b"FWAR":
                        try:
                            n = len(formats.split_bfwar(blob))
                        except Exception:
                            n = 0
                        for k in range(n):
                            L.append(dict(i=w.index * 100000 + k, name=f"{w.label}/wave_{k}", icon="wave"))
            else:
                for fid in self._files_by_magic(mg):
                    L.append(dict(i=fid, name=names.get(fid, f"file_{fid}"), icon="seq" if mg == b"FSEQ" else "bank"))
        return L

    # ---------- propriétés ----------
    def item(self, cat, i):
        a = self.arc
        R = []
        add = R.append
        if cat in ("allsounds", "stream", "wave", "seq"):
            s = a.sounds[i]
            t = ST.get(s.sound_type, "?")
            ex = s.extra
            add(dict(t="text", label="Name", v=s.label, ro=True))
            pl = a.players[ex["player_id"] & 0xFFFFFF] if (ex.get("player_id", INVALID) >> 24) == 4 and (ex["player_id"] & 0xFFFFFF) < len(a.players) else None
            add(dict(t="combo", label="Player", v=f"[{ex['player_id'] & 0xFFFFFF}] {pl.label}" if pl else "[-] (none)", ro=True, nav=True))
            add(dict(t="num", label=f"Volume ({ex['volume'] / 127:.3f})", v=ex["volume"], key="volume"))
            add(dict(t="num", label="Remote Filter", v=self._remote_filter(s), key="remote_filter"))
            add(dict(t="check", label="Enable Pan Param", v=True, ro=True))
            add(dict(t="combo", label="Pan Mode", v="Balance", ro=True))
            add(dict(t="combo", label="Pan Curve", v="Sqrt", ro=True))
            add(dict(t="check", label="Enable Player Param", v=True, ro=True))
            add(dict(t="num", label="Player Priority", v=64, ro=True))
            add(dict(t="num", label="Actor Player Id", v=0, ro=True))
            add(dict(t="section", label="User Param"))
            add(dict(t="check", label="Enable Front Bypass", v=False, ro=True, dim=True))
            add(dict(t="check", label="Front Bypass (?)", v=False, ro=True, dim=True))
            add(dict(t="check", label="Enable Sound 3D Info", v=True, ro=True))
            add(dict(t="section", label="Sound 3D Info"))
            add(dict(t="combo", label="Sound Type", v={"stream": "Stream", "wave": "Wave", "seq": "Sequence"}.get(t, "?"), ro=True))
            add(dict(t="tabs", tabs=["Sequence", "Stream", "Wave"], active={"seq": 0, "stream": 1, "wave": 2}.get(t, 1)))
            if t == "stream":
                fe = a.files[s.file_id] if s.file_id < len(a.files) else None
                add(dict(t="text", label="Path (?)", v=(fe.path if fe and not fe.internal else f"(interne) file_{s.file_id}"), ro=True))
                add(dict(t="slider", label="Pitch", v=ex.get("pitch", 1.0), min=0, max=4, ro=True))
                for k, lab in (("main", "Main Send"), ("fx0", "Fx Send 0"), ("fx1", "Fx Send 1"), ("fx2", "Fx Send 2")):
                    add(dict(t="num", label=lab, v=127 if k == "main" else 0, ro=True))
            elif t == "wave":
                add(dict(t="num", label="Wave Sound Index", v=ex.get("wsd_index", 0), ro=True))
                add(dict(t="num", label="File Id", v=s.file_id, ro=True))
            else:
                for n, bid in enumerate((ex.get("bank_ids", []) + [INVALID] * 4)[:4]):
                    add(dict(t="combo", label=f"Bank {n}", v=self._bank_label(bid), ro=True))
                add(dict(t="num", label="Start Offset", v=ex.get("start_offset") or 0, ro=True))
            return R
        if cat in ("allsets", "wavesets", "seqsets"):
            g = a.soundgroups[i]
            w = g.extra.get("wave", False)
            add(dict(t="text", label="Name", v=g.label, ro=True))
            add(dict(t="combo", label="Sound Type", v="Wave" if w else "Sequence", ro=True))
            if w:
                ids = g.extra.get("warc_ids", [])
                add(dict(t="combo", label="Wave Archive", v=(a.warcs[ids[0] & 0xFFFFFF].label if ids and (ids[0] & 0xFFFFFF) < len(a.warcs) else "Automatic (Shared)"), ro=True, nav=True))
            st, en = g.extra["start_id"] & 0xFFFFFF, g.extra["end_id"] & 0xFFFFFF
            add(dict(t="check", label="Is Empty", v=en < st, ro=True))
            add(dict(t="num", label="Start Id", v=st, ro=True))
            add(dict(t="num", label="End Id", v=en, ro=True))
            add(dict(t="soundlist", items=[dict(i=k, name=a.sounds[k].label, icon=ST.get(a.sounds[k].sound_type, "wave")) for k in range(st, min(en, len(a.sounds) - 1) + 1)]))
            return R
        if cat == "banks":
            b = a.banks[i]
            add(dict(t="text", label="Name", v=b.label, ro=True))
            add(dict(t="num", label="File Id", v=b.file_id, ro=True))
            for n, wid in enumerate(b.extra.get("warc_ids", [])):
                add(dict(t="combo", label=f"Wave Archive {n}", v=a.warcs[wid & 0xFFFFFF].label if (wid & 0xFFFFFF) < len(a.warcs) else "?", ro=True))
            return R
        if cat == "warcs":
            w = a.warcs[i]
            add(dict(t="text", label="Name", v=w.label, ro=True))
            add(dict(t="check", label="Load Individual", v=w.extra.get("load_individual", False), ro=True))
            add(dict(t="num", label="File Id", v=w.file_id if w.file_id != INVALID else -1, ro=True))
            return R
        if cat == "groups":
            g = a.groups[i]
            add(dict(t="text", label="Name", v=g.label, ro=True))
            add(dict(t="num", label="File Id", v=g.file_id if g.file_id != INVALID else -1, ro=True))
            return R
        if cat == "players":
            g = a.players[i]
            add(dict(t="text", label="Name", v=g.label, ro=True))
            add(dict(t="num", label="Playable Sound Max", v=g.extra.get("playable_sound_max", 0), ro=True))
            return R
        return R

    def _bank_label(self, bid):
        if bid == INVALID or (bid >> 24) != 3 or (bid & 0xFFFFFF) >= len(self.arc.banks):
            return "[-]  (none)"
        k = bid & 0xFFFFFF
        return f"[{k}]  {self.arc.banks[k].label}"

    def _sound_addr(self, s):
        return self.arc._ref_table("sound")[s.index]

    def _remote_filter(self, s):
        return self.arc.r.u8(self._sound_addr(s) + 9)

    # ---------- édition ----------
    def set_value(self, cat, i, key, value):
        a = self.arc
        s = a.sounds[i]
        addr = self._sound_addr(s)
        value = int(value)
        if key == "volume":
            a.data[addr + 8] = max(0, min(127, value)); s.extra["volume"] = a.data[addr + 8]
        elif key == "remote_filter":
            a.data[addr + 9] = max(0, min(127, value))
        else:
            raise ValueError("Champ non modifiable")
        self.dirty = True

    # ---------- audio ----------
    def audio_wav(self, kind, i, j=0):
        a = self.arc
        key = (kind, i, j)
        if key in self._wavecache:
            return self._wavecache[key]
        if kind == "sound":
            s = a.sounds[i]
            if s.sound_type == 0x2201:
                blob = a.file_bytes(s.file_id)
                if blob is None:
                    fe = a.files[s.file_id]
                    raise LookupError(f"Stream externe introuvable : {fe.path} (placez le dossier à côté du BFSAR)")
                au = formats.decode_bfstm(blob)
            elif s.sound_type == 0x2202:
                au = formats.decode_bfwav(a.wave_blobs_for_sound(s)[0])
            else:
                from . import seqplay
                au = seqplay.render_sound(a, s)
        elif kind == "wavefile":
            w = a.warcs[i // 100000]
            au = formats.decode_bfwav(formats.split_bfwar(a.file_bytes(w.file_id))[i % 100000])
        else:
            raise ValueError(kind)
        bio = io.BytesIO()
        write_wav(au, bio)
        data = bio.getvalue()
        self._wavecache[key] = (data, au)
        return self._wavecache[key]

    # ---------- séquences / banques ----------
    def seq_view(self, kind, i):
        a = self.arc
        if kind == "sound":
            s = a.sounds[i]
            fid, start = s.file_id, s.extra.get("start_offset")
            banks = [self._bank_label(b) for b in (s.extra.get("bank_ids", []) + [INVALID] * 4)[:4]]
        else:
            fid, start, banks = i, None, [self._bank_label(INVALID)] * 4
        sf = SeqFile(a.file_bytes(fid))
        lines = disassemble(sf)
        start_label = next((n for o, n in sf.labels if o == start), None)
        return dict(file=fid, banks=banks, labels=[n for _, n in sf.labels], start_label=start_label or "",
                    lines=[dict(o=o, t=t, k=k) for o, t, k in lines])

    def bank_view(self, i):
        a = self.arc
        b = a.banks[i]
        B = Bank(a.file_bytes(b.file_id))
        inst = []
        for ins in B.instruments:
            regs = []
            for kr in ins.regions:
                for v in kr.velocities:
                    regs.append(dict(kmin=kr.kmin, kmax=kr.kmax, vmin=v.vmin, vmax=v.vmax, key=v.original_key, vol=v.volume,
                                     pan=v.pan, pitch=v.pitch, ino=v.ignore_note_off, kg=v.key_group, interp=v.interpolation,
                                     adshr=list(v.adshr), warc=(v.warc_id & 0xFFFFFF), wave=v.wave_in_warc,
                                     name=f"{self._warc_label(v.warc_id)}/wave_{v.wave_in_warc}"))
            inst.append(dict(p=ins.program, regions=regs))
        return dict(name=b.label, instruments=inst)

    def _warc_label(self, wid):
        k = wid & 0xFFFFFF
        return self.arc.warcs[k].label if k < len(self.arc.warcs) else f"warc{k}"
