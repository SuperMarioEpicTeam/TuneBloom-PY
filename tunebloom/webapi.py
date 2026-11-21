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


def _stereo_preview(au):
    """Plus de 2 canaux (pistes superposées d'un BFSTM) : mélange pistes paires -> G, impaires -> D."""
    if len(au.channels) <= 2:
        return au
    from array import array
    from .formats import Audio
    n = au.frames
    L, R = array("h", bytes(n * 2)), array("h", bytes(n * 2))
    ev, od = au.channels[0::2], au.channels[1::2]
    for i in range(n):
        L[i] = max(-32768, min(32767, sum(c[i] for c in ev) // len(ev) * 3 // 2 if len(ev) > 1 else ev[0][i]))
        R[i] = max(-32768, min(32767, sum(c[i] for c in od) // len(od) * 3 // 2 if len(od) > 1 else od[0][i]))
    return Audio(au.sample_rate, [L, R], au.loop, au.loop_start, au.loop_end, au.encoding)


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
                arc.attach_group(f.read(), g)
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
            add(dict(t="combo", label="Player", v=f"[{ex['player_id'] & 0xFFFFFF}] {pl.label}" if pl else "[-] (none)", ro=False, nav=True, key="player", n=len(a.players), cur=ex["player_id"] & 0xFFFFFF))
            add(dict(t="num", label=f"Volume ({ex['volume'] / 127:.3f})", v=ex["volume"], key="volume"))
            add(dict(t="num", label="Remote Filter", v=self._remote_filter(s), key="remote_filter"))
            pm, pc = self._opt_byte(s, 1, 0), self._opt_byte(s, 1, 1)
            pr, ac = self._opt_byte(s, 2, 0), self._opt_byte(s, 2, 1)
            MODES, CURVES = ["Dual", "Balance"], ["Sqrt", "Sin Cos", "Linear"]
            add(dict(t="check", label="Enable Pan Param", v=pm is not None, ro=True))
            add(dict(t="combo", label="Pan Mode", v=MODES[pm] if pm is not None and pm < 2 else "Dual", key="pan_mode", cyc=pm is not None, cur=pm or 0, n=2))
            add(dict(t="combo", label="Pan Curve", v=CURVES[pc] if pc is not None and pc < 3 else "Sqrt", key="pan_curve", cyc=pc is not None, cur=pc or 0, n=3))
            add(dict(t="check", label="Enable Player Param", v=pr is not None, ro=True))
            add(dict(t="num", label="Player Priority", v=pr if pr is not None else 64, key="priority", ro=pr is None))
            add(dict(t="num", label="Actor Player Id", v=ac if ac is not None else 0, key="actor", ro=ac is None))
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
                add(dict(t="slider", label="Pitch", v=ex.get("pitch", 1.0), min=0, max=4, key="pitch"))
                sv = self._send_values(s)
                for n_, (k, lab) in enumerate((("send0", "Main Send"), ("send1", "Fx Send 0"), ("send2", "Fx Send 1"), ("send3", "Fx Send 2"))):
                    add(dict(t="num", label=lab, v=sv[n_] if sv else (127 if n_ == 0 else 0), key=k, ro=sv is None))
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

    def _opt_addr(self, s, bit):
        """Adresse de la valeur u32 du paramètre optionnel `bit` du son, ou None s'il est absent."""
        a = self.arc
        base = self._sound_addr(s) + 20
        flag = a.r.u32(base)
        if not (flag >> bit) & 1:
            return None
        return base + 4 * bin(flag & ((1 << (bit + 1)) - 1)).count("1")

    def _opt_byte(self, s, bit, idx):
        addr = self._opt_addr(s, bit)
        if addr is None:
            return None
        v = self.arc.r.u32(addr)
        return (v >> (8 * idx)) & 0xFF

    def _send_addr(self, s):
        """Adresse des 4 octets (main, fx0, fx1, fx2) d'un son stream, ou None."""
        a = self.arc
        if s.sound_type != 0x2201:
            return None
        sa = self._sound_addr(s)
        detail = sa + a.r.s32(sa + 16)
        off = a.r.s32(detail + 20)
        return None if off == -1 else detail + off

    def _send_values(self, s):
        addr = self._send_addr(s)
        return list(self.arc.data[addr:addr + 4]) if addr is not None else None

    def _remote_filter(self, s):
        return self.arc.r.u8(self._sound_addr(s) + 9)

    # ---------- édition ----------
    def set_value(self, cat, i, key, value):
        a = self.arc
        s = a.sounds[i]
        addr = self._sound_addr(s)
        value = float(value) if key == "pitch" else int(value)
        if key == "volume":
            a.data[addr + 8] = max(0, min(127, value)); s.extra["volume"] = a.data[addr + 8]
        elif key == "player":
            n = len(a.players)
            if n == 0: raise ValueError("Aucun player")
            v = value % n
            a.data[addr + 4:addr + 8] = ((4 << 24) | v).to_bytes(4, "big" if a.endian == ">" else "little")
            s.extra["player_id"] = (4 << 24) | v
        elif key == "pitch":
            if s.sound_type != 0x2201: raise ValueError("Pitch : sons stream uniquement")
            detail = addr + a.r.s32(addr + 16)
            a.data[detail + 12:detail + 16] = struct.pack(a.endian + "f", float(value))
            s.extra["pitch"] = float(value)
        elif key in ("pan_mode", "pan_curve", "priority", "actor"):
            bit, idx = {"pan_mode": (1, 0), "pan_curve": (1, 1), "priority": (2, 0), "actor": (2, 1)}[key]
            pos = self._opt_addr(s, bit)
            if pos is None:
                raise ValueError("Ce paramètre n'est pas stocké pour ce son (valeur par défaut) : non modifiable")
            lim = {"pan_mode": 1, "pan_curve": 2, "priority": 127, "actor": 255}[key]
            x = struct.unpack_from(a.endian + "I", a.data, pos)[0]
            x = (x & ~(0xFF << (8 * idx))) | (max(0, min(lim, value)) << (8 * idx))
            struct.pack_into(a.endian + "I", a.data, pos, x)
        elif key.startswith("send"):
            pos = self._send_addr(s)
            if pos is None:
                raise ValueError("Valeurs d'envoi absentes pour ce son")
            a.data[pos + int(key[4:])] = max(0, min(127, value))
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
        write_wav(_stereo_preview(au), bio)             # le navigateur ne lit que mono/stéréo
        data = bio.getvalue()
        self._wavecache[key] = (data, au)
        return self._wavecache[key]

    def note_wav(self, bank, prg, key, vel):
        from . import seqplay
        au = seqplay.render_note(self.arc, bank, prg, key, vel)
        bio = io.BytesIO()
        write_wav(au, bio)
        return bio.getvalue()

    # ---------- remplacement / export (menu contextuel de l'original) ----------
    def replace_sound(self, i, path, loop_start=None):
        from .wavio import wav_to_bfwav, wav_to_bfstm
        a = self.arc
        s = a.sounds[i]
        low = path.lower()
        if s.sound_type == 0x2201:
            if low.endswith(".bfstm"):
                data = open(path, "rb").read(); note = ""
            else:
                data, ls = wav_to_bfstm(path, loop_start); note = f" (boucle à {ls})" if loop_start is not None else ""
            fe = a.files[s.file_id]
            if fe.internal and fe.offset != INVALID:
                a.replace_any_file(s.file_id, data)
            elif fe.path and a.path:
                target = os.path.join(os.path.dirname(os.path.abspath(a.path)), fe.path.replace("\\", "/"))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as f:
                    f.write(data)
                note += f" -> écrit dans {target}"
            else:
                raise LookupError("Destination du stream introuvable")
            try:                                   # recaler le nombre de canaux alloués du son dans le BFSAR
                from .bfstm_write import parse_raw
                nch = parse_raw(data)["nch"]
                addr = a._ref_table("sound")[s.index]
                detail = addr + a.r.s32(addr + 16)
                a.data[detail + 2:detail + 4] = nch.to_bytes(2, "big" if a.endian == ">" else "little")
                s.extra["channels"] = nch
            except Exception:
                pass
            self.dirty = True
            self._wavecache.clear()
            return dict(ok=True, note="Stream remplacé" + note)
        if s.sound_type == 0x2202:
            data = open(path, "rb").read() if low.endswith(".bfwav") else wav_to_bfwav(path, "dspadpcm", loop_start)
            a.replace_wave(s, data)
            self.dirty = True
            self._wavecache.clear()
            return dict(ok=True, note="Son remplacé")
        raise ValueError("Seuls les sons Stream et Wave peuvent être remplacés par un fichier audio")

    _KIND = {"allsounds": 1, "stream": 1, "wave": 1, "seq": 1, "allsets": 2, "wavesets": 2, "seqsets": 2,
             "banks": 3, "players": 4, "warcs": 5, "groups": 6}

    def rename(self, cat, i, name):
        if cat not in self._KIND:
            raise ValueError("Cet élément ne peut pas être renommé")
        self.arc.rename_item(self._KIND[cat], i, name)
        self.dirty = True
        self._wavecache.clear()

    def delete_sound(self, i):
        name = self.arc.sounds[i].label
        self.arc.delete_sound(i)
        self.dirty = True
        self._wavecache.clear()
        return name

    def duplicate(self, i, name):
        n = self.arc.duplicate_sound(i, name)
        self.dirty = True
        return n

    def add_stream(self, name, path, loop=None, template=None):
        """Nouveau son Stream : encode/copie le BFSTM à côté du BFSAR (stream/<nom>.bfstm) et ajoute les entrées INFO + chaîne."""
        from .wavio import wav_to_bfstm
        from .bfstm_write import parse_raw
        a = self.arc
        if not a.path:
            raise ValueError("Enregistrez d'abord le projet (chemin inconnu pour écrire le stream)")
        if path.lower().endswith(".bfstm"):
            data = open(path, "rb").read()
        else:
            data, _ = wav_to_bfstm(path, loop)
        try:
            nch = parse_raw(data)["nch"]
        except Exception:
            nch = None
        rel = f"stream/{name}.bfstm"
        idx, fid = a.add_stream_sound(name, rel, template, nch)           # lève une erreur AVANT d'écrire le fichier si le nom est invalide
        target = os.path.join(os.path.dirname(os.path.abspath(a.path)), rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as f:
            f.write(data)
        self.dirty = True
        return dict(ok=True, index=idx, note=f"Son {name} ajouté ({rel})")

    def add_wave(self, name, path, template=None):
        from .wavio import wav_to_bfwav
        data = open(path, "rb").read() if path.lower().endswith(".bfwav") else wav_to_bfwav(path, "dspadpcm")
        idx, widx = self.arc.add_wave_sound(name, data, template)
        self.dirty = True
        self._wavecache.clear()
        return dict(ok=True, index=idx, note=f"Son Wave {name} ajouté (vague {widx})")

    def add_seq(self, name, code, template=None):
        idx, off = self.arc.add_sequence_sound(name, code, template)
        self.dirty = True
        return dict(ok=True, index=idx, note=f"Son Séquence {name} ajouté (label à l'offset {off})")

    def export_wav(self, i):
        s = self.arc.sounds[i]
        data, au = self.audio_wav("sound", i)
        bio = io.BytesIO()
        write_wav(au, bio)                 # export complet (tous les canaux)
        return s.label, bio.getvalue()

    # ---------- séquences / banques ----------
    def _entry_offsets(self, fid):
        return sorted({s.extra.get("start_offset") for s in self.arc.sounds
                       if s.sound_type == 0x2203 and s.file_id == fid and s.extra.get("start_offset") is not None})

    def seq_view(self, kind, i):
        a = self.arc
        if kind == "sound":
            s = a.sounds[i]
            fid, start = s.file_id, s.extra.get("start_offset")
            banks = [self._bank_label(b) for b in (s.extra.get("bank_ids", []) + [INVALID] * 4)[:4]]
        else:
            fid, start, banks = i, None, [self._bank_label(INVALID)] * 4
        sf = SeqFile(a.file_bytes(fid))
        lines = disassemble(sf, self._entry_offsets(fid))
        start_label = next((n for o, n in sf.labels if o == start), None)
        return dict(file=fid, banks=banks, labels=[n for _, n in sf.labels], start_label=start_label or "",
                    lines=[dict(o=o, t=t, k=k) for o, t, k in lines])

    def seq_apply(self, kind, i, text):
        """Compile le texte MML, remplace le BFSEQ dans l'archive et recale les offsets de départ des sons."""
        from .mmlasm import assemble, rebuild_bfseq, AsmError
        a = self.arc
        fid = a.sounds[i].file_id if kind == "sound" else i
        old = bytes(a.file_bytes(fid))
        oldseq = SeqFile(old)
        users = [s for s in a.sounds if s.sound_type == 0x2203 and s.file_id == fid]
        old_start = {}
        for s in users:
            so = s.extra.get("start_offset")
            old_start[s.index] = next((n for o, n in oldseq.labels if o == so), f"Entry_{so:04X}" if so is not None else None)
        try:
            code, order = assemble(text)
        except AsmError as e:
            raise ValueError(str(e))
        new, table = rebuild_bfseq(old, code, order)
        newoff = {n: o for o, n in order}
        warn = []
        a.replace_any_file(fid, new)
        for s in a.sounds:
            if s.index in old_start:
                nm = old_start[s.index]
                if nm and nm in newoff:
                    a.set_sound_start_offset(s, newoff[nm])
                elif nm:
                    warn.append(f"{s.label} : label de départ {nm} supprimé, offset inchangé")
        self.dirty = True
        self._wavecache.clear()
        v = self.seq_view(kind, i)
        v["warnings"] = warn
        return v

    def bank_set(self, bank, ins, reg, field, value):
        """Modifie une valeur déjà présente d'une région de banque (octets existants, même taille de fichier)."""
        a = self.arc
        bk = a.banks[bank]
        raw = bytearray(a.file_bytes(bk.file_id))
        B = Bank(bytes(raw))
        regs = [v for kr in B.instruments[ins].regions for v in kr.velocities]
        v = regs[reg]
        e = B.e
        if field.startswith("adshr"):
            n = int(field[5:])
            if "adshr" not in v.addr or not 0 <= n < 5:
                raise ValueError("Courbe ADSHR absente de cette région")
            raw[v.addr["adshr"][0] + n] = max(0, min(127, int(value)))
        else:
            if field not in v.addr:
                raise ValueError("Ce champ n'est pas stocké dans cette région (valeur par défaut) : non modifiable")
            addr, bi = v.addr[field]
            if bi == "f":
                raw[addr:addr + 4] = struct.pack(e + "f", float(value))
            else:
                x = struct.unpack_from(e + "I", raw, addr)[0]
                x = (x & ~(0xFF << (8 * bi))) | ((max(0, min(127 if field != "key_group" else 255, int(value))) & 0xFF) << (8 * bi))
                struct.pack_into(e + "I", raw, addr, x)
        a.replace_any_file(bk.file_id, bytes(raw))
        self.dirty = True
        self._wavecache.clear()
        return self.bank_view(bank)

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
                                     adshr=list(v.adshr), editable=sorted(v.addr), warc=(v.warc_id & 0xFFFFFF), wave=v.wave_in_warc,
                                     name=f"{self._warc_label(v.warc_id)}/wave_{v.wave_in_warc}"))
            inst.append(dict(p=ins.program, regions=regs))
        return dict(name=b.label, instruments=inst)

    def _warc_label(self, wid):
        k = wid & 0xFFFFFF
        return self.arc.warcs[k].label if k < len(self.arc.warcs) else f"warc{k}"
