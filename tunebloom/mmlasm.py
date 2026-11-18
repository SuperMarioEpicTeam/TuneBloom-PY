"""Assembleur MML (inverse exact de mml.disassemble) + reconstruction d'un BFSEQ."""
import re, struct
from .binio import detect_endian, align
from . import mml

KEYS = {n: i for i, n in enumerate(mml.NOTE)}
NOTE_RE = re.compile(r"^(cn|cs|dn|ds|en|fn|fs|gn|gs|an|as|bn)(m1|\d)$")
AUTO_LABEL = re.compile(r"^(Label|Entry)_[0-9A-F]{4}$")
U8 = {v: k for k, v in mml.NAME_U8.items()}
S16 = {v: k for k, v in mml.NAME_S16.items()}
Z0 = {v: k for k, v in mml.NAME_0.items()}
BOOLS = {}
for _c, (_on, _off) in mml.BOOL.items():
    BOOLS[_on] = (_c, 1); BOOLS[_off] = (_c, 0)
EXV = {v: k for k, v in mml.EX.items()}
SUFFIXES = ["", "_r", "_v", "_t", "_tr", "_tv", "_r_t", "_r_tr", "_r_tv", "_v_t", "_v_tr", "_v_tv"]


class AsmError(Exception):
    def __init__(self, line, msg):
        super().__init__(f"ligne {line}: {msg}")
        self.line, self.msg = line, msg


def vmidi(v):
    if v < 0:
        raise ValueError("valeur négative")
    out = [v & 0x7F]
    v >>= 7
    while v:
        out.append((v & 0x7F) | 0x80)
        v >>= 7
    return bytes(reversed(out))


def split_mn(mn):
    """'pan_r' -> ('pan', '_r', '') ; 'tempo_t' -> ('tempo', '', '_t') ..."""
    known = set(U8) | set(S16) | set(Z0) | set(BOOLS) | {"wait", "prg", "opentrack", "jump", "call", "alloctrack"} | set(EXV)
    for suf in sorted(SUFFIXES, key=len, reverse=True):
        if suf and mn.endswith(suf) and (mn[:-len(suf)] in known or NOTE_RE.match(mn[:-len(suf)])):
            argsuf = ""; tsuf = ""
            for a in ("_r", "_v"):
                if suf.startswith(a):
                    argsuf = a; suf2 = suf[len(a):]
                    break
            else:
                suf2 = suf
            tsuf = suf2
            return mn[:-len(suf)], argsuf, tsuf
    return mn, "", ""


def _num(tok, line):
    tok = tok.strip()
    try:
        return int(tok, 0)
    except ValueError:
        raise AsmError(line, f"nombre invalide : {tok!r}")


def _arg(tok, argsuf, kind, line):
    """-> (octets_préfixe, octets_opérande)"""
    if argsuf == "_r":
        a, b = [x.strip() for x in tok.split(",")]
        return b"\xa0", struct.pack(">hh", _num(a, line), _num(b, line))
    if argsuf == "_v":
        m = re.fullmatch(r"var(\d+)", tok.strip())
        if not m:
            raise AsmError(line, "variable attendue (varN)")
        return b"\xa1", bytes([int(m.group(1))])
    v = _num(tok, line)
    if kind == "u8":
        if not 0 <= v <= 255: raise AsmError(line, f"u8 hors limites : {v}")
        return b"", bytes([v])
    if kind == "s8":
        if not -128 <= v <= 127: raise AsmError(line, f"s8 hors limites : {v}")
        return b"", struct.pack(">b", v)
    if kind == "s16":
        if not -32768 <= v <= 32767: raise AsmError(line, f"s16 hors limites : {v}")
        return b"", struct.pack(">h", v)
    try:
        return b"", vmidi(v)
    except ValueError as e:
        raise AsmError(line, str(e))


def _split_args(rest, argsuf, tsuf, line):
    """Sépare l'argument principal des arguments de temps. Renvoie (tok_principal, bytes_time_prefix, bytes_time)."""
    parts = [p.strip() for p in rest.split(",")] if rest.strip() else []
    n_main = 2 if argsuf == "_r" else 1
    main = ", ".join(parts[:n_main])
    tp, tb = b"", b""
    ex = parts[n_main:]
    if tsuf == "_t":
        tp, tb = b"\xa3", struct.pack(">h", _num(ex[0], line))
    elif tsuf == "_tr":
        tp, tb = b"\xa4", struct.pack(">hh", _num(ex[0], line), _num(ex[1], line))
    elif tsuf == "_tv":
        m = re.fullmatch(r"var(\d+)", ex[0])
        tp, tb = b"\xa5", bytes([int(m.group(1))])
    return main, tp, tb


def encode(text, line, labels_fix):
    """Encode une instruction. labels_fix : liste où l'on enregistre (position_dans_insn, nom_label) à résoudre."""
    t = text.strip()
    cond = b""
    if t.startswith("_if "):
        cond = b"\xa2"; t = t[4:].strip()
    m = re.match(r"^(\S+)\s*(.*)$", t)
    mn, rest = m.group(1), m.group(2)
    if mn == ".byte":
        return bytes([_num(rest, line)]), []
    base, argsuf, tsuf = split_mn(mn)
    # note ?
    nm = NOTE_RE.match(base)
    if nm:
        key = KEYS[nm.group(1)] + 12 * ((-1 if nm.group(2) == "m1" else int(nm.group(2))) + 1)
        if not 0 <= key <= 127:
            raise AsmError(line, "note hors limites")
        parts = rest.split(",", 1)
        vel = _num(parts[0], line)
        pre, ln = _arg(parts[1], argsuf, "vmidi", line)
        return cond + pre + bytes([key, vel]) + ln, []
    fix = []
    if base in ("jump", "call"):
        op = bytes([0x89 if base == "jump" else 0x8a])
        fix.append((len(cond) + 1, rest.strip()))
        return cond + op + b"\0\0\0", fix
    if base == "opentrack":
        n, lab = [x.strip() for x in rest.split(",", 1)]
        fix.append((len(cond) + 2, lab))
        return cond + bytes([0x88, _num(n, line)]) + b"\0\0\0", fix
    if base == "wait" or base == "prg":
        main, tp, tb = _split_args(rest, argsuf, tsuf, line)
        pre, op = _arg(main, argsuf, "vmidi", line)
        return cond + tp + pre + bytes([0x80 if base == "wait" else 0x81]) + op + tb, []
    if base in BOOLS:
        c, v = BOOLS[base]
        return cond + bytes([c, v]), []
    if base in U8:
        main, tp, tb = _split_args(rest, argsuf, tsuf, line)
        cmd = U8[base]
        pre, op = _arg(main, argsuf, "s8" if cmd in (0xc3, 0xc4) else "u8", line)
        return cond + tp + pre + bytes([cmd]) + op + tb, []
    if base in S16:
        main, tp, tb = _split_args(rest, argsuf, tsuf, line)
        pre, op = _arg(main, argsuf, "s16", line)
        return cond + tp + pre + bytes([S16[base]]) + op + tb, []
    if base in Z0:
        return cond + bytes([Z0[base]]), []
    if base == "alloctrack":
        return cond + b"\xfe" + struct.pack(">H", _num(rest, line)), []
    if base in EXV:                                   # setvar var3, 5 / cmp_eq var1, 2
        a, b = [x.strip() for x in rest.split(",", 1)]
        vn = int(re.fullmatch(r"var(\d+)", a).group(1))
        pre, op = _arg(b, argsuf, "s16", line)
        return cond + pre + bytes([0xf0, EXV[base], vn]) + op, []
    m2 = re.fullmatch(r"ex_([0-9a-f]{2})", base)
    if m2:
        x = int(m2.group(1), 16); hi = x & 0xF0
        if hi in (0xa0, 0xb0):
            return cond + bytes([0xf0, x, _num(rest, line)]), []
        if hi == 0xe0:
            pre, op = _arg(rest, argsuf, "s16", line)
            return cond + pre + bytes([0xf0, x]) + op, []
        return cond + bytes([0xf0, x]), []
    raise AsmError(line, f"instruction inconnue : {mn}")


def assemble(text):
    """Texte -> (code, [(offset, nom)] dans l'ordre du texte). Les labels auto « Label_XXXX » sont aussi renvoyés."""
    code = bytearray()
    pend, names = [], {}
    order = []
    for ln, raw in enumerate(text.split("\n"), 1):
        line = raw.split(";")[0].replace("·", " ").strip() if False else raw.strip()
        if not line:
            continue
        if line.endswith(":") and " " not in line:
            nm = line[:-1]
            if nm in names:
                raise AsmError(ln, f"label en double : {nm}")
            names[nm] = len(code); order.append((len(code), nm))
            continue
        try:
            data, fix = encode(line, ln, None)
        except AsmError:
            raise
        except (IndexError, ValueError, AttributeError, TypeError, struct.error):
            raise AsmError(ln, f"opérande manquant ou invalide : {line.strip()}")
        for pos, lab in fix:
            pend.append((len(code) + pos, lab, ln))
        code += data
    for pos, lab, ln in pend:
        if lab not in names:
            raise AsmError(ln, f"label inconnu : {lab}")
        code[pos:pos + 3] = names[lab].to_bytes(3, "big")
    return bytes(code), order


def rebuild_bfseq(orig, code, order):
    """Réécrit un BFSEQ : orig fournit l'en-tête ; order = labels du texte [(offset, nom)]."""
    orig = bytes(orig)
    e = detect_endian(orig)
    P32 = lambda v: struct.pack(e + "I", v)
    old = mml.SeqFile(orig)
    old_names = [n for _, n in old.labels]
    in_text = {n: o for o, n in order if not AUTO_LABEL.match(n)}
    table = [(in_text[n], n) for n in old_names if n in in_text]            # ordre d'origine conservé
    table += [(o, n) for o, n in order if not AUTO_LABEL.match(n) and n not in old_names]
    data_size = align(8 + len(code), 0x20)
    data = b"DATA" + P32(data_size) + code + b"\0" * (data_size - 8 - len(code))
    cnt = len(table)
    entries, offs, pos = [], [], 4 + 8 * cnt
    for off, name in table:
        nb = name.encode("ascii")
        ent = struct.pack(e + "HHI", 0x1F00, 0, off) + P32(len(nb)) + nb + b"\0"
        ent += b"\0" * ((-len(ent)) % 4)
        offs.append(pos); pos += len(ent); entries.append(ent)
    body = P32(cnt) + b"".join(struct.pack(e + "HHI", 0x5100, 0, o) for o in offs) + b"".join(entries)
    labl_size = align(8 + len(body), 0x20)
    labl = b"LABL" + P32(labl_size) + body + b"\0" * (labl_size - 8 - len(body))
    hdr = bytearray(orig[:0x40])
    hdr[0x1c:0x20] = P32(data_size)
    hdr[0x24:0x28] = P32(0x40 + data_size)
    hdr[0x28:0x2c] = P32(labl_size)
    hdr[12:16] = P32(0x40 + data_size + labl_size)
    return bytes(hdr) + data + labl, table
