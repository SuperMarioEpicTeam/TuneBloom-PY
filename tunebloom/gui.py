"""Interface Tkinter (bibliothèque standard) : parcourir, écouter, exporter, remplacer."""
import os, threading, traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .bfsar import Bfsar, ITEM_NAMES, SOUND_TYPE_NAMES, INVALID
from . import formats
from .audio import Player, write_wav


class App(tk.Tk):
    def __init__(self, path=None):
        super().__init__()
        self.title("TuneBloom-Py")
        self.geometry("980x620")
        self.arc = None
        self.player = Player()
        self.nodes = {}
        self._build()
        if path:
            self.load(path)

    def _build(self):
        m = tk.Menu(self)
        fm = tk.Menu(m, tearoff=0)
        fm.add_command(label="Ouvrir un BFSAR…", command=self.ask_open)
        fm.add_command(label="Enregistrer sous…", command=self.save_as)
        fm.add_separator()
        fm.add_command(label="Quitter", command=self.destroy)
        m.add_cascade(label="Fichier", menu=fm)
        self.config(menu=m)

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)
        left = ttk.Frame(paned)
        self.tree = ttk.Treeview(left, show="tree")
        sb = ttk.Scrollbar(left, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<<TreeviewOpen>>", self.on_open)
        paned.add(left, weight=1)

        right = ttk.Frame(paned)
        bar = ttk.Frame(right)
        bar.pack(fill="x", padx=6, pady=6)
        self.btn_play = ttk.Button(bar, text="▶ Écouter", command=self.play, state="disabled")
        self.btn_stop = ttk.Button(bar, text="■ Stop", command=self.player.stop)
        self.btn_wav = ttk.Button(bar, text="Exporter WAV…", command=self.export_wav, state="disabled")
        self.btn_raw = ttk.Button(bar, text="Exporter brut…", command=self.export_raw, state="disabled")
        self.btn_rep = ttk.Button(bar, text="Remplacer…", command=self.replace, state="disabled")
        for b in (self.btn_play, self.btn_stop, self.btn_wav, self.btn_raw, self.btn_rep):
            b.pack(side="left", padx=2)
        self.info = tk.Text(right, wrap="word", state="disabled")
        self.info.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.status = ttk.Label(right, text="Ouvrez un fichier .bfsar")
        self.status.pack(fill="x", padx=6, pady=(0, 6))
        paned.add(right, weight=3)

    def ask_open(self):
        p = filedialog.askopenfilename(filetypes=[("Wii U sound archive", "*.bfsar"), ("Tous", "*.*")])
        if p:
            self.load(p)

    def load(self, path):
        try:
            self.arc = Bfsar.open(path)
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de lire {path}\n{e}")
            return
        self.tree.delete(*self.tree.get_children())
        self.nodes.clear()
        arc = self.arc
        groups = [("Sons", arc.sounds), ("Banques", arc.banks), ("Archives de vagues", arc.warcs),
                  ("Groupes", arc.groups), ("Players", arc.players), ("Groupes de sons", arc.soundgroups)]
        for title, items in groups:
            top = self.tree.insert("", "end", text=f"{title} ({len(items)})")
            for it in items:
                iid = self.tree.insert(top, "end", text=it.label)
                self.nodes[iid] = dict(kind="item", item=it)
                if it.kind == 5 and it.file_id != INVALID:
                    self.tree.insert(iid, "end", text="…")
        ftop = self.tree.insert("", "end", text=f"Fichiers bruts ({len(arc.files)})")
        for fe in arc.files:
            iid = self.tree.insert(ftop, "end", text=f"file_{fe.index}" + ("" if fe.internal else f"  [externe: {fe.path}]"))
            self.nodes[iid] = dict(kind="file", file_id=fe.index)
        self.title(f"TuneBloom-Py — {os.path.basename(path)}")
        self.status.config(text=f"{len(arc.files)} fichiers, version 0x{arc.version:08X}")

    def on_open(self, _):
        iid = self.tree.focus()
        n = self.nodes.get(iid)
        if not n or n["kind"] != "item" or n["item"].kind != 5:
            return
        kids = self.tree.get_children(iid)
        if len(kids) == 1 and self.tree.item(kids[0], "text") == "…":
            self.tree.delete(kids[0])
            blob = self.arc.file_bytes(n["item"].file_id)
            try:
                waves = formats.split_bfwar(blob) if blob else []
            except Exception:
                waves = []
            for i, w in enumerate(waves):
                if w is None:
                    continue
                c = self.tree.insert(iid, "end", text=f"wave {i}")
                self.nodes[c] = dict(kind="wave", blob=w, label=f"{n['item'].label}_wave{i:04d}")

    def current_blob(self):
        n = self.nodes.get(self.tree.focus())
        if not n:
            return None, None
        if n["kind"] == "wave":
            return n["blob"], n["label"]
        if n["kind"] == "file":
            return self.arc.file_bytes(n["file_id"]), f"file_{n['file_id']}"
        it = n["item"]
        return self.arc.file_bytes(it.file_id), it.label

    def on_select(self, _):
        n = self.nodes.get(self.tree.focus())
        lines = []
        blob, label = self.current_blob()
        if n and n["kind"] == "item":
            it = n["item"]
            lines.append(f"{ITEM_NAMES[it.kind]} : {it.label}")
            lines.append(f"ID : 0x{it.item_id:08X}")
            if it.kind == 1:
                lines.append(f"Type : {SOUND_TYPE_NAMES.get(it.sound_type, '?')}")
            if it.file_id != INVALID:
                lines.append(f"Fichier : #{it.file_id}")
            for k, v in it.extra.items():
                lines.append(f"{k} : {v}")
            if it.kind == 1 and it.sound_type == 0x2202:
                lines.append("\n(Wave sound : le BFWSD n'est pas encore interprété ; utilisez l'archive de vagues correspondante.)")
        elif n and n["kind"] == "file":
            fe = self.arc.files[n["file_id"]]
            lines.append(f"Fichier #{fe.index} — {'interne' if fe.internal else 'externe'}")
            if fe.internal:
                lines.append(f"Offset (corps FILE) : 0x{fe.offset:X}\nTaille : {fe.size} octets")
        if blob:
            lines.append(f"Format : {bytes(blob[:4]).decode('latin1')}  ({len(blob)} octets)")
        elif n:
            lines.append("Données indisponibles (fichier externe introuvable à côté du BFSAR).")
        self._set_info("\n".join(lines))
        is_audio = bool(blob) and bytes(blob[:4]) in (b"FSTM", b"FWAV")
        self.btn_play.config(state="normal" if is_audio else "disabled")
        self.btn_wav.config(state="normal" if is_audio else "disabled")
        self.btn_raw.config(state="normal" if blob else "disabled")
        replaceable = bool(n) and (n["kind"] == "file" or (n["kind"] == "item" and n["item"].file_id != INVALID))
        self.btn_rep.config(state="normal" if replaceable else "disabled")

    def _set_info(self, text):
        self.info.config(state="normal")
        self.info.delete("1.0", "end")
        self.info.insert("1.0", text)
        self.info.config(state="disabled")

    def _decode_async(self, blob, then):
        self.status.config(text="Décodage…")
        def work():
            try:
                audio = formats.decode_any(blob)
                self.after(0, lambda: (self.status.config(text="Prêt"), then(audio)))
            except Exception as e:
                tb = traceback.format_exc()
                self.after(0, lambda: (self.status.config(text="Erreur de décodage"), messagebox.showerror("Décodage", f"{e}\n\n{tb}")))
        threading.Thread(target=work, daemon=True).start()

    def play(self):
        blob, _ = self.current_blob()
        def go(audio):
            try:
                self.player.play(audio)
            except Exception as e:
                messagebox.showerror("Lecture", str(e))
        self._decode_async(blob, go)

    def export_wav(self):
        blob, label = self.current_blob()
        p = filedialog.asksaveasfilename(initialfile=f"{label}.wav", defaultextension=".wav")
        if p:
            self._decode_async(blob, lambda a: (write_wav(a, p), self.status.config(text=f"Exporté : {p}")))

    def export_raw(self):
        blob, label = self.current_blob()
        ext = self.arc.extension_for(blob)
        p = filedialog.asksaveasfilename(initialfile=f"{label}{ext}", defaultextension=ext)
        if p:
            with open(p, "wb") as f:
                f.write(blob)
            self.status.config(text=f"Exporté : {p}")

    def replace(self):
        n = self.nodes.get(self.tree.focus())
        fid = n["file_id"] if n["kind"] == "file" else n["item"].file_id
        p = filedialog.askopenfilename(title="Nouveau fichier (même format : .bfstm, .bfwar, .bfseq…)")
        if not p:
            return
        try:
            with open(p, "rb") as f:
                self.arc.replace_file(fid, f.read())
        except Exception as e:
            messagebox.showerror("Remplacement", str(e))
            return
        self.status.config(text=f"Fichier #{fid} remplacé en mémoire — pensez à Enregistrer sous…")
        self.on_select(None)

    def save_as(self):
        if not self.arc:
            return
        p = filedialog.asksaveasfilename(defaultextension=".bfsar")
        if p:
            self.arc.save(p)
            self.status.config(text=f"Enregistré : {p}")


def main(path=None):
    App(path).mainloop()
