"""Séquenceur MML hors-ligne : BFSEQ + BFBNK + BFWAV -> audio. Nécessite numpy (pip install numpy).
Port simplifié du pilote d'origine (src/snd-ply : MmlParser, SequenceTrack, CurveAdshr)."""
import math, struct
from .mml import SeqFile, _var
from .bank import Bank
from . import formats

ATTACK = [0.9992175, 0.9984326, 0.9976452, 0.9968553, 0.9960629, 0.9952679, 0.9944704, 0.9936704, 0.9928677, 0.9920625, 0.9912546, 0.9904441,
          0.9896309, 0.9888151, 0.9879965, 0.9871752, 0.9863512, 0.9855244, 0.9846949, 0.9838625, 0.9830273, 0.9821893, 0.9813483, 0.9805045,
          0.9796578, 0.9788081, 0.9779555, 0.9770999, 0.9762413, 0.9753797, 0.9745150, 0.9736472, 0.9727763, 0.9719023, 0.9710251, 0.9701448,
          0.9692612, 0.9683744, 0.9674844, 0.9665910, 0.9656944, 0.9647944, 0.9638910, 0.9629842, 0.9620740, 0.9611604, 0.9602433, 0.9593226,
          0.9583984, 0.9574706, 0.9565392, 0.9556042, 0.9546655, 0.9537231, 0.9527769, 0.9518270, 0.9508732, 0.9499157, 0.9489542, 0.9479888,
          0.9470195, 0.9460462, 0.9450689, 0.9440875, 0.9431020, 0.9421124, 0.9411186, 0.9401206, 0.9391184, 0.9381118, 0.9371009, 0.9360856,
          0.9350659, 0.9340417, 0.9330131, 0.9319798, 0.9309420, 0.9298995, 0.9288523, 0.9278004, 0.9267436, 0.9256821, 0.9246156, 0.9235442,
          0.9224678, 0.9213864, 0.9202998, 0.9192081, 0.9181112, 0.9170091, 0.9159016, 0.9147887, 0.9136703, 0.9125465, 0.9114171, 0.9102821,
          0.9091414, 0.9079949, 0.9068427, 0.9056845, 0.9045204, 0.9033502, 0.9021740, 0.9009916, 0.8998029, 0.8986080, 0.8974066, 0.8961988,
          0.8949844, 0.8900599, 0.8824622, 0.8759247, 0.8691861, 0.8636406, 0.8535788, 0.8430189, 0.8286135, 0.8149099, 0.8002172, 0.7780663,
          0.7554750, 0.7242125, 0.6828239, 0.6329169, 0.5592135, 0.4551411, 0.3298770, 0.0]


def calc_release(r):
    if r == 127: return 65535.0
    if r == 126: return 120 / 5.0
    if r < 50: return ((r << 1) + 1) / 128.0 / 5.0
    return (60.0 / (126 - r)) / 5.0


def decibel_square(s):          # cDecibelSquareTable : 10 * 20*log10((s/127)^2), borné à -723
    if s <= 0: return -723.0
    return max(-723.0, 400.0 * math.log10(s / 127.0))


def envelope(adshr, gate_ms, sr_ms=1):
    """Courbe ADSHR (dB) échantillonnée à la ms, porté de CurveAdshr::update. Renvoie la liste des dB (<=0)."""
    a, d, s, h, r = adshr
    att, hold, dec, sus, rel = ATTACK[a], (h + 1) * (h + 1) // 4, calc_release(d), s, calc_release(r)
    sus_db = decibel_square(sus)
    val, status, hc, out = -904.0, "A", 0, []
    n = 0
    while True:
        if n >= gate_ms and status != "R":
            status = "R"
        if status == "A":
            val = 0.0 if att == 0.0 else val * att
            if att == 0.0 or val > -1.0 / 32.0:
                val, status, hc = 0.0, "H", hold
        elif status == "H":
            if hc > 0: hc -= 1
            else: status = "D"
        elif status == "D":
            val -= dec
            if val < sus_db: val, status = sus_db, "S"
        elif status == "R":
            val -= rel
            if val < -900.0: break
        out.append(val / 10.0)
        n += 1
        if n > 20000 + gate_ms: break
    return out


class Track:
    def __init__(self, tid, pos):
        self.id, self.pos, self.wait, self.alive = tid, pos, 0, True
        self.prg, self.bank = 0, 0
        self.vol, self.vol2, self.pan, self.trans, self.bend, self.bendrange = 127, 127, 64, 0, 0, 2
        self.notewait, self.tie = True, False
        self.env = [None] * 5           # attack, decay, sustain, hold, release (None = valeur de la région)
        self.stack, self.loops, self.cond = [], [], True
        self.vars = {}
        self.last_note = None


def render_sound(arc, sound, max_seconds=75, sr=32000):
    import numpy as np
    seqf = SeqFile(arc.file_bytes(sound.file_id))
    body = seqf.body
    banks = []
    for bid in sound.extra.get("bank_ids", [])[:4]:
        k = bid & 0xFFFFFF
        if (bid >> 24) == 3 and k < len(arc.banks):
            blob = arc.file_bytes(arc.banks[k].file_id)
            if blob is None:
                raise LookupError(f"Banque {arc.banks[k].label} indisponible : ses données sont dans un BFGRP externe "
                                  f"(menu File > Add BFGRP, ou --grp en ligne de commande)")
            banks.append(Bank(blob))
        else:
            banks.append(None)
    start = sound.extra.get("start_offset") or 0
    vol_sound = sound.extra.get("volume", 127) / 127.0
    wave_cache = {}

    def get_wave(warc_id, idx):
        key = (warc_id, idx)
        if key not in wave_cache:
            warc = arc.warcs[warc_id & 0xFFFFFF]
            if warc.file_id not in arc._warc_cache:
                blob = arc.file_bytes(warc.file_id)
                if blob is None:
                    raise LookupError(f"archive de vagues {warc.label} indisponible")
                arc._warc_cache[warc.file_id] = formats.split_bfwar(blob)
            au = formats.decode_bfwav(arc._warc_cache[warc.file_id][idx])
            pcm = np.mean([np.asarray(c, dtype=np.float32) for c in au.channels], axis=0) / 32768.0
            wave_cache[key] = (pcm, au.sample_rate, au.loop, au.loop_start, au.loop_end)
        return wave_cache[key]

    tempo, timebase = 120, 48
    gvars = {}
    tracks = [Track(0, start)]
    events = []                       # (tick_start, tick_len, wave, params)
    tick, tick_time, t_acc = 0, 0.0, 0.0          # temps cumulé en secondes (tempo variable)
    tick_times = []
    steps = 0
    limit_t = max_seconds
    while tracks and any(t.alive for t in tracks) and t_acc < limit_t and steps < 400000:
        tick_times.append(t_acc)
        for t in list(tracks):
            if not t.alive: continue
            if t.wait > 0:
                t.wait -= 1
                if t.wait > 0: continue
            guard = 0
            while t.alive and t.wait == 0 and guard < 2000:
                guard += 1
                try:
                    cmd = body[t.pos]
                except IndexError:
                    t.alive = False; break
                p = t.pos + 1
                cond_ok = True
                if cmd == 0xa2:
                    cond_ok = t.cond; cmd = body[p]; p += 1
                t2 = None
                if cmd in (0xa3, 0xa4, 0xa5):
                    t2 = cmd; cmd = body[p]; p += 1
                pre = None
                if cmd in (0xa0, 0xa1):
                    pre = cmd; cmd = body[p]; p += 1

                def rd(kind):
                    nonlocal p
                    if pre == 0xa0:
                        mn, mx = struct.unpack_from(">hh", body, p); p += 4
                        return (mn + mx) // 2
                    if pre == 0xa1:
                        v = body[p]; p += 1
                        return (gvars if v >= 16 else t.vars).get(v, 0)
                    if kind == "u8": v = body[p]; p += 1; return v
                    if kind == "s8": v = struct.unpack_from(">b", body, p)[0]; p += 1; return v
                    if kind == "s16": v = struct.unpack_from(">h", body, p)[0]; p += 2; return v
                    v, p = _var(body, p); return v

                if t2 == 0xa3: p += 2
                elif t2 == 0xa4: p += 4
                elif t2 == 0xa5: p += 1
                if cmd < 0x80:
                    vel = body[p]; p += 1
                    ln = rd("vmidi")
                    if cond_ok:
                        key = max(0, min(127, cmd + t.trans))
                        ln_t = ln if ln > 0 else 1
                        events.append((len(tick_times) - 1, ln_t, t, key, vel, t.prg, t.bank, t.vol, t.vol2, t.pan, t.bend, t.bendrange, tuple(t.env), t.tie))
                        if t.notewait:
                            t.wait = ln_t
                    t.pos = p
                    if t.wait: break
                    continue
                n_b = None
                if cmd == 0x80:
                    w = rd("vmidi"); t.pos = p
                    if cond_ok: t.wait = w
                elif cmd == 0x81:
                    v = rd("vmidi"); t.pos = p
                    if cond_ok: t.prg = v
                elif cmd == 0x88:
                    n_b = body[p]; off = int.from_bytes(body[p + 1:p + 4], "big"); p += 4; t.pos = p
                    if cond_ok:
                        nt = Track(n_b, off); nt.bank, nt.vol, nt.vol2, nt.trans = t.bank, t.vol, t.vol2, t.trans
                        tracks.append(nt)
                elif cmd in (0x89, 0x8a):
                    off = int.from_bytes(body[p:p + 3], "big"); p += 3
                    if cond_ok:
                        if cmd == 0x8a: t.stack.append(("c", p))
                        t.pos = off
                    else: t.pos = p
                elif cmd in (0xb2, 0xbf, 0xc7, 0xc8, 0xce, 0xdf):
                    v = body[p]; p += 1; t.pos = p
                    if cond_ok and cmd == 0xc7: t.notewait = bool(v)
                    if cond_ok and cmd == 0xc8: t.tie = bool(v)
                elif 0xb0 <= cmd <= 0xdf:
                    a = rd("s8" if cmd in (0xc3, 0xc4) else "u8")
                    if t2 == 0xa3: pass
                    t.pos = p
                    if cond_ok:
                        if cmd == 0xb0: timebase = a or 48
                        elif cmd == 0xc1: t.vol = a
                        elif cmd == 0xd5: t.vol2 = a
                        elif cmd == 0xc2: pass
                        elif cmd == 0xc0: t.pan = a
                        elif cmd == 0xc3: t.trans = a
                        elif cmd == 0xc4: t.bend = a
                        elif cmd == 0xc5: t.bendrange = a
                        elif cmd == 0xb6: t.bank = a
                        elif cmd == 0xd0: t.env[0] = a
                        elif cmd == 0xd1: t.env[1] = a
                        elif cmd == 0xd2: t.env[2] = a
                        elif cmd == 0xb1: t.env[3] = a
                        elif cmd == 0xd3: t.env[4] = a
                        elif cmd == 0xd4:
                            t.loops.append([p, a])            # loop_start n : n répétitions (0 = infini)
                elif cmd in (0xe0, 0xe1, 0xe3, 0xe4):
                    a = rd("s16"); t.pos = p
                    if cond_ok and cmd == 0xe1: tempo = max(1, a)
                elif cmd == 0xfb:
                    t.env = [None] * 5; t.pos = p
                elif cmd == 0xfc:
                    t.pos = p
                    if cond_ok and t.loops:
                        lp = t.loops[-1]
                        if lp[1] == 0: t.pos = lp[0]
                        else:
                            lp.append(0) if len(lp) == 2 else None
                            lp[2] += 1
                            if lp[2] < lp[1]: t.pos = lp[0]
                            else: t.loops.pop()
                elif cmd == 0xfd:
                    t.pos = p
                    if cond_ok and t.stack: t.pos = t.stack.pop()[1]
                elif cmd == 0xfe:
                    p += 2; t.pos = p
                elif cmd == 0xff:
                    t.pos = p
                    if cond_ok: t.alive = False
                elif cmd == 0xf0:
                    x = body[p]; p += 1; hi = x & 0xF0
                    if hi in (0xa0, 0xb0): p += 1
                    elif hi == 0xe0: rd("s16")
                    elif hi in (0x80, 0x90):
                        vn = body[p]; p += 1; a = rd("s16")
                        store = gvars if vn >= 16 else t.vars
                        cur = store.get(vn, 0)
                        if x == 0x80: store[vn] = a
                        elif x == 0x81: store[vn] = cur + a
                        elif x == 0x82: store[vn] = cur - a
                        elif x == 0x83: store[vn] = cur * a
                        elif x == 0x84: store[vn] = int(cur / a) if a else cur
                        elif x == 0x86: store[vn] = a
                        elif x == 0x87: store[vn] = cur & a
                        elif x == 0x88: store[vn] = cur | a
                        elif x == 0x89: store[vn] = cur ^ a
                        elif x == 0x90: t.cond = cur == a
                        elif x == 0x91: t.cond = cur >= a
                        elif x == 0x92: t.cond = cur > a
                        elif x == 0x93: t.cond = cur <= a
                        elif x == 0x94: t.cond = cur < a
                        elif x == 0x95: t.cond = cur != a
                    t.pos = p
                else:
                    t.pos = p
        # avance du temps : une tick dure 60 / (tempo * timebase) secondes
        t_acc += 60.0 / (tempo * timebase)
        steps += 1
    tick_times.append(t_acc)
    total_end = t_acc
    if not events:
        raise LookupError("Cette séquence ne joue aucune note (séquence de contrôle ou notes hors région)")
    return _mix(banks, vol_sound, events, tick_times, total_end, get_wave, sr)


def render_note(arc, bank_index, prg, key, vel=100, gate=1.2, sr=32000):
    """Joue une seule note d'une banque (clavier de l'éditeur de banque)."""
    bk = Bank(arc.file_bytes(arc.banks[bank_index].file_id))
    wave_cache = {}
    import numpy as np

    def get_wave(warc_id, idx):
        key_ = (warc_id, idx)
        if key_ not in wave_cache:
            warc = arc.warcs[warc_id & 0xFFFFFF]
            if warc.file_id not in arc._warc_cache:
                blob = arc.file_bytes(warc.file_id)
                if blob is None:
                    raise LookupError(f"archive de vagues {warc.label} indisponible (BFGRP manquant : File > Add BFGRP)")
                arc._warc_cache[warc.file_id] = formats.split_bfwar(blob)
            au = formats.decode_bfwav(arc._warc_cache[warc.file_id][idx])
            pcm = np.mean([np.asarray(c, dtype=np.float32) for c in au.channels], axis=0) / 32768.0
            wave_cache[key_] = (pcm, au.sample_rate, au.loop, au.loop_start, au.loop_end)
        return wave_cache[key_]

    t = Track(0, 0)
    ev = [(0, 1, t, key, vel, prg, 0, 127, 127, 64, 0, 2, (None,) * 5, False)]
    return _mix([bk], 1.0, ev, [0.0, gate], gate, get_wave, sr)


def _mix(banks, vol_sound, events, tick_times, total_end, get_wave, sr):
    import numpy as np
    first_error = None
    mixed = 0
    tail = 6.0
    n_total = int((total_end + tail) * sr)
    L = np.zeros(n_total, dtype=np.float32); R = np.zeros(n_total, dtype=np.float32)
    inst_cache = {}
    for (t0, ln, tr, key, vel, prg, bank, tvol, tvol2, tpan, bend, brange, tenv, tie) in events:
        bk = banks[bank] if bank < len(banks) else None
        if bk is None or prg >= len(bk.instruments): continue
        reg = None
        for kr in bk.instruments[prg].regions:
            if kr.kmin <= key <= kr.kmax:
                for vr in kr.velocities:
                    if vr.vmin <= vel <= vr.vmax:
                        reg = vr; break
            if reg: break
        if reg is None: continue
        try:
            pcm, wrate, wloop, ls, le = get_wave(reg.warc_id, reg.wave_in_warc)
        except Exception as e:
            first_error = first_error or e
            continue
        start_s = tick_times[min(t0, len(tick_times) - 1)]
        end_i = min(t0 + ln, len(tick_times) - 1)
        gate_s = max(0.001, tick_times[end_i] - start_s)
        adshr = [tenv[i] if tenv[i] is not None else reg.adshr[i] for i in range(5)]
        env_db = np.asarray(envelope(adshr, int(gate_s * 1000)), dtype=np.float32)
        env = np.power(10.0, env_db / 20.0)
        ratio = 2.0 ** ((key - reg.original_key) / 12.0 + (bend / 128.0) * brange / 12.0) * reg.pitch * wrate / sr
        n_env = int(len(env) * sr / 1000)
        pos = np.arange(n_env, dtype=np.float64) * ratio
        if wloop and le > ls:
            m = pos >= ls
            pos[m] = ls + np.mod(pos[m] - ls, le - ls)
            ok = np.ones(n_env, bool)
        else:
            ok = pos < len(pcm) - 1
        pos = pos[ok]; n = len(pos)
        if n == 0: continue
        i0 = pos.astype(np.int64); fr = (pos - i0).astype(np.float32)
        smp = pcm[i0] * (1 - fr) + pcm[np.minimum(i0 + 1, len(pcm) - 1)] * fr
        e = np.interp(np.arange(n) * 1000.0 / sr, np.arange(len(env)), env).astype(np.float32)
        amp = (vel / 127.0) ** 2 * (tvol / 127.0) ** 2 * (tvol2 / 127.0) ** 2 * (reg.volume / 127.0) * vol_sound
        p = max(-1.0, min(1.0, (tpan - 64 + reg.pan - 64) / 63.0))
        gl, gr = math.cos((p + 1) * math.pi / 4), math.sin((p + 1) * math.pi / 4)
        s0 = int(start_s * sr)
        seg = smp * e * amp * 0.5
        end = min(n_total, s0 + n)
        if end <= s0: continue
        L[s0:end] += seg[:end - s0] * gl
        R[s0:end] += seg[:end - s0] * gr
        mixed += 1
    if mixed == 0:
        raise LookupError("Aucune note audible : " + (str(first_error) if first_error else "instrument/région introuvable dans la banque")
                          + " (si les vagues sont dans un BFGRP externe, chargez-le via File > Add BFGRP)")
    peak = max(float(np.max(np.abs(L))), float(np.max(np.abs(R))), 1e-9)
    gain = 0.8 / peak                      # aperçu : normalisé (les séquences sont souvent très faibles)
    last = np.nonzero((np.abs(L) + np.abs(R)) > 1e-4)[0]
    n_out = int(last[-1]) + 1 if len(last) else n_total
    import array
    from .formats import Audio
    def i16(x):
        return array.array("h", (np.clip(x[:n_out] * gain, -1, 1) * 32767).astype(np.int16).tolist())
    return Audio(sr, [i16(L), i16(R)], False, 0, n_out)
