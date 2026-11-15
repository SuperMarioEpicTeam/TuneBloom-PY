"""BFSEQ : lecture des labels + désassembleur MML (syntaxe du TuneBloom d'origine : `dn2 104, 15`, `wait 3`…)."""
import struct
from .binio import detect_endian

NOTE = ["cn", "cs", "dn", "ds", "en", "fn", "fs", "gn", "gs", "an", "as", "bn"]


def note_name(k):
    o = k // 12 - 1
    return NOTE[k % 12] + ("m1" if o < 0 else str(o))


NAME_U8 = {0xb0: "timebase", 0xb1: "env_hold", 0xb3: "velocity_range", 0xb4: "biquad_type", 0xb5: "biquad_value",
           0xb6: "bank_select", 0xbd: "mod_phase", 0xbe: "mod_curve", 0xc0: "pan", 0xc1: "volume", 0xc2: "main_volume",
           0xc3: "transpose", 0xc4: "pitchbend", 0xc5: "bendrange", 0xc6: "prio", 0xc9: "porta", 0xca: "mod_depth",
           0xcb: "mod_speed", 0xcc: "mod_type", 0xcd: "mod_range", 0xcf: "porta_time", 0xd0: "attack", 0xd1: "decay",
           0xd2: "sustain", 0xd3: "release", 0xd4: "loop_start", 0xd5: "volume2", 0xd6: "printvar", 0xd7: "span",
           0xd8: "lpf_cutoff", 0xd9: "fxsend_a", 0xda: "fxsend_b", 0xdb: "mainsend", 0xdc: "init_pan", 0xdd: "mute",
           0xde: "fxsend_c"}
BOOL = {0xb2: ("monophonic_on", "monophonic_off"), 0xbf: ("frontbypass_on", "frontbypass_off"),
        0xc7: ("notewait_on", "notewait_off"), 0xc8: ("tieon", "tieoff"), 0xce: ("porta_on", "porta_off"),
        0xdf: ("damper_on", "damper_off")}
NAME_S16 = {0xe0: "mod_delay", 0xe1: "tempo", 0xe3: "sweep_pitch", 0xe4: "mod_period"}
NAME_0 = {0xfb: "env_reset", 0xfc: "loop_end", 0xfd: "ret", 0xff: "fin"}
EX = {0x80: "setvar", 0x81: "addvar", 0x82: "subvar", 0x83: "mulvar", 0x84: "divvar", 0x85: "shiftvar", 0x86: "randvar",
      0x87: "andvar", 0x88: "orvar", 0x89: "xorvar", 0x8a: "notvar", 0x8b: "modvar", 0x90: "cmp_eq", 0x91: "cmp_ge",
      0x92: "cmp_gt", 0x93: "cmp_le", 0x94: "cmp_lt", 0x95: "cmp_ne"}


class SeqFile:
    def __init__(self, data):
        data = bytes(data)
        if data[:4] != b"FSEQ":
            raise ValueError("Pas un BFSEQ")
        self.e = detect_endian(data)
        self.d = data
        u16 = lambda o: struct.unpack_from(self.e + "H", data, o)[0]
        u32 = lambda o: struct.unpack_from(self.e + "I", data, o)[0]
        s32 = lambda o: struct.unpack_from(self.e + "i", data, o)[0]
        blocks = {u16(0x14 + 12 * i): (u32(0x14 + 12 * i + 4), u32(0x14 + 12 * i + 8)) for i in range(u16(16))}
        doff, dsize = blocks[0x5000]
        self.body = data[doff + 8:doff + dsize]
        self.labels = []                       # (offset, nom)
        if 0x5001 in blocks:
            lb = blocks[0x5001][0] + 8
            for i in range(u32(lb)):
                a = lb + s32(lb + 4 + 8 * i + 4)
                ln = u32(a + 8)
                self.labels.append((s32(a + 4), data[a + 12:a + 12 + ln].split(b"\0")[0].decode("ascii", "replace")))

    def label_offset(self, name):
        for o, n in self.labels:
            if n == name:
                return o
        return None


def _var(b, p):
    v = 0
    while True:
        c = b[p]; p += 1
        v = (v << 7) | (c & 0x7F)
        if not c & 0x80:
            return v, p


def decode(seq, p):
    """Décode UNE commande à l'offset p. Renvoie (texte, taille, cible_label|None, mnémonique, args)."""
    b = seq
    start = p
    cmd = b[p]; p += 1
    cond = ""
    if cmd == 0xa2:
        cmd = b[p]; p += 1; cond = "_if "
    t2 = None
    if cmd in (0xa3, 0xa4, 0xa5):
        t2 = cmd; cmd = b[p]; p += 1
    pre = None
    if cmd in (0xa0, 0xa1):
        pre = cmd; cmd = b[p]; p += 1

    def arg(default):
        nonlocal p
        if pre == 0xa0:
            mn, mx = struct.unpack_from(">hh", b, p); p += 4
            return f"{mn}, {mx}", "_r"
        if pre == 0xa1:
            v = b[p]; p += 1
            return f"var{v}", "_v"
        if default == "u8":
            v = b[p]; p += 1; return str(v), ""
        if default == "s8":
            v = struct.unpack_from(">b", b, p)[0]; p += 1; return str(v), ""
        if default == "s16":
            v = struct.unpack_from(">h", b, p)[0]; p += 2; return str(v), ""
        v, p = _var(b, p); return str(v), ""

    def targ():
        nonlocal p
        if t2 == 0xa3:
            v = struct.unpack_from(">h", b, p)[0]; p += 2; return f", {v}", "_t"
        if t2 == 0xa4:
            mn, mx = struct.unpack_from(">hh", b, p); p += 4; return f", {mn}, {mx}", "_tr"
        if t2 == 0xa5:
            v = b[p]; p += 1; return f", var{v}", "_tv"
        return "", ""

    target = None
    if cmd < 0x80:
        vel = b[p]; p += 1
        ln, suf = arg("vmidi")
        text = f"{cond}{note_name(cmd)}{suf} {vel}, {ln}"
        return text, p - start, None
    if cmd == 0x80:
        a, s = arg("vmidi"); text = f"{cond}wait{s} {a}"
    elif cmd == 0x81:
        a, s = arg("vmidi"); text = f"{cond}prg{s} {a}"
    elif cmd == 0x88:
        n = b[p]; off = int.from_bytes(b[p + 1:p + 4], "big"); p += 4
        text = f"{cond}opentrack {n}, @{off}"; target = off
    elif cmd in (0x89, 0x8a):
        off = int.from_bytes(b[p:p + 3], "big"); p += 3
        text = f"{cond}{'jump' if cmd == 0x89 else 'call'} @{off}"; target = off
    elif cmd in BOOL:
        v = b[p]; p += 1
        text = f"{cond}{BOOL[cmd][0 if v else 1]}"
    elif cmd in NAME_U8:
        sg = "s8" if cmd in (0xc3, 0xc4) else "u8"
        a, s = arg(sg); ex, ts = targ()
        text = f"{cond}{NAME_U8[cmd]}{s}{ts} {a}{ex}"
    elif cmd in NAME_S16:
        a, s = arg("s16"); ex, ts = targ()
        text = f"{cond}{NAME_S16[cmd]}{s}{ts} {a}{ex}"
    elif cmd == 0xf0:
        x = b[p]; p += 1
        hi = x & 0xF0
        if hi in (0xa0, 0xb0):
            v = b[p]; p += 1; text = f"{cond}ex_{x:02x} {v}"
        elif hi == 0xe0:
            a, s = arg("s16"); text = f"{cond}ex_{x:02x}{s} {a}"
        elif hi in (0x80, 0x90):
            vn = b[p]; p += 1
            a, s = arg("s16")
            text = f"{cond}{EX.get(x, 'ex_%02x' % x)}{s} var{vn}, {a}"
        else:
            text = f"{cond}ex_{x:02x}"
    elif cmd == 0xfe:
        v = struct.unpack_from(">H", b, p)[0]; p += 2; text = f"{cond}alloctrack {v:#06x}"
    elif cmd in NAME_0:
        text = f"{cond}{NAME_0[cmd]}"
    else:
        text = f"{cond}.byte {cmd:#04x}"
    return text, p - start, target


def disassemble(seqfile):
    """Texte complet avec labels (LABL + cibles de jump/call/opentrack), lignes [(offset, texte, kind)]."""
    body = seqfile.body
    names = {}
    for o, n in seqfile.labels:
        names.setdefault(o, n)
    # première passe : cibles
    insns, p = [], 0
    while p < len(body):
        try:
            text, size, tgt = decode(body, p)
        except Exception:
            text, size, tgt = f".byte {body[p]:#04x}", 1, None
        insns.append((p, text, tgt)); p += size
    for _, _, tgt in insns:
        if tgt is not None and tgt not in names:
            names[tgt] = f"Label_{tgt:04X}"
    out = []
    for off, text, tgt in insns:
        if off in names:
            out.append((off, names[off] + ":", "label"))
        if tgt is not None:
            text = text.replace(f"@{tgt}", names[tgt])
        out.append((off, text, "insn"))
    return out
