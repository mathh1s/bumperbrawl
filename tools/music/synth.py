"""Subtractive synth voices and effects for the soundtrack, rendered straight to numpy.

The soundfonts carry the band; these carry the electronic side: supersaws, plucks,
chip pulses, a talk box lead, wobble and acid basses, risers. Everything that moves
over time (filter LFOs, chorus, sidechain pumping) runs on the song clock rather than
the note clock, so a part repeats bit for bit every loop and the loop stays seamless.

> patch      a dict of the keys in DEFAULT, see voice() for what each one does
> part       events (beat, beats, key, velocity) plus a patch and an fx dict
> fx keys    hp, sidechain, chorus, delay, width (see effects())
"""

import numpy as np
from numba import njit

SR = 44100

SAW, PULSE, TRI, SINE = 0, 1, 2, 3

DEFAULT = {
    "osc": [(SAW, 0.0, 1.0)],      # (shape, semitones, level) per oscillator
    "unison": 1,                    # voices per oscillator
    "detune": 0.0,                  # cents across the unison voices
    "spread": 0.0,                  # stereo width of the unison voices, 0 to 1
    "sub": 0.0,                     # sine an octave down
    "noise": 0.0,
    "noise_rate": 0.0,              # hold each noise value this many times a second, the crunchy console noise
    "fm": None,                     # (ratio, index, seconds the index takes to fall) two operator FM tone
    "pw": 0.5, "pwm": 0.0, "pwm_rate": 0.0,
    "amp": (0.004, 0.25, 1.0, 0.06),     # attack, decay, sustain, release in seconds
    "filt": (0.0, 0.2, 0.0, 0.1),        # same shape for the filter envelope
    "cutoff": 2500.0, "env_oct": 0.0, "keytrack": 0.0, "res": 0.8, "mode": 0,  # 0 low, 1 band, 2 high pass
    "lfo": None,                    # (period in beats, depth in octaves, offset in beats) on the cutoff
    "vib": (5.5, 0.0, 0.25),        # rate, depth in cents, fade in seconds
    "tune": 0.0,                    # semitones added to every note
    "pitch": (0.0, 0.05),           # semitones the note starts away by, and how fast it settles
    "glide": 0.0,                   # seconds to slide from the previous note when legato
    "formant": None,                # vowels to morph through over the note, e.g. "oa"
    "drive": 0.0,
    "velsens": 0.7,
}

VOWELS = {"a": (800, 1150, 2900), "e": (450, 1900, 2600), "i": (330, 2200, 3000),
          "o": (480, 820, 2800), "u": (350, 650, 2500)}
FORMANT_GAIN = (1.0, 0.55, 0.3)


# ==== dsp kernels ====

@njit(cache=True)
def _blep(t, dt):
    if t < dt:
        t /= dt
        return t + t - t * t - 1.0
    if t > 1.0 - dt:
        t = (t - 1.0) / dt
        return t * t + t + t + 1.0
    return 0.0


@njit(cache=True)
def _osc(freq, shape, pw, phase):
    n = len(freq)
    out = np.empty(n)
    ph = phase
    for i in range(n):
        dt = freq[i] / SR
        if shape == 0:
            v = 2.0 * ph - 1.0 - _blep(ph, dt)
        elif shape == 1:
            p = pw[i]
            v = 1.0 if ph < p else -1.0
            v += _blep(ph, dt)
            t2 = ph - p
            if t2 < 0.0:
                t2 += 1.0
            v -= _blep(t2, dt)
        elif shape == 2:
            v = 4.0 * abs(ph - 0.5) - 1.0
        else:
            v = np.sin(2.0 * np.pi * ph)
        out[i] = v
        ph += dt
        while ph >= 1.0:
            ph -= 1.0
    return out


@njit(cache=True)
def _svf(x, cutoff, q, mode):
    # topology preserving state variable filter, stable under fast cutoff changes
    out = np.empty(len(x))
    ic1 = 0.0
    ic2 = 0.0
    k = 1.0 / q
    for i in range(len(x)):
        fc = min(max(cutoff[i], 20.0), SR * 0.45)
        g = np.tan(np.pi * fc / SR)
        a1 = 1.0 / (1.0 + g * (g + k))
        a2 = g * a1
        a3 = g * a2
        v3 = x[i] - ic2
        v1 = a1 * ic1 + a2 * v3
        v2 = ic2 + a2 * ic1 + a3 * v3
        ic1 = 2.0 * v1 - ic1
        ic2 = 2.0 * v2 - ic2
        if mode == 0:
            out[i] = v2
        elif mode == 1:
            out[i] = v1 * k
        else:
            out[i] = x[i] - k * v1 - v2
    return out


@njit(cache=True)
def _pingpong(x, delay, feedback, tone):
    # feedback alternates sides and loses a little top end on every pass
    n = x.shape[0]
    out = np.zeros((n, 2))
    lp_l = 0.0
    lp_r = 0.0
    for i in range(delay, n):
        src_l = x[i - delay, 0] + x[i - delay, 1] * 0.5 + out[i - delay, 1] * feedback
        src_r = out[i - delay, 0] * feedback
        lp_l += tone * (src_l - lp_l)
        lp_r += tone * (src_r - lp_r)
        out[i, 0] = lp_l
        out[i, 1] = lp_r
    return out


# ==== voices ====

def adsr(n, gate, a, d, s, r):
    t = np.arange(n) / SR
    a = max(a, 1e-4)
    env = np.where(t < a, t / a, s + (1 - s) * np.exp(-(t - a) / max(d, 1e-4)))
    tg = gate / SR
    at_off = tg / a if tg < a else s + (1 - s) * np.exp(-(tg - a) / max(d, 1e-4))
    env[gate:] = at_off * np.exp(-(t[gate:] - tg) / max(r, 1e-4))
    return env


def voice(p, key, vel, dur, start, beat, rng, slide_from=None):
    """One note. dur and start are seconds, beat is the length of a beat in seconds."""
    gate = max(1, int(dur * SR))
    n = gate + int(p["amp"][3] * 5 * SR) + 64
    t = np.arange(n) / SR

    semis = np.full(n, float(key) + p["tune"])
    if p["pitch"][0]:
        semis += p["pitch"][0] * np.exp(-t / p["pitch"][1])
    if slide_from is not None and p["glide"]:
        semis += (slide_from - key) * np.exp(-t / p["glide"])
    rate, cents, fade = p["vib"]
    if cents:
        semis += cents / 100 * np.sin(2 * np.pi * rate * t) * np.minimum(1, t / fade)
    freq = 440 * 2 ** ((semis - 69) / 12)

    pw = np.full(n, p["pw"])
    if p["pwm"]:
        pw += p["pwm"] * np.sin(2 * np.pi * p["pwm_rate"] * (start + t))

    out = np.zeros((n, 2))
    uni = p["unison"]
    for shape, offset, level in p["osc"]:
        for u in range(uni):
            f = (u / (uni - 1) - 0.5) if uni > 1 else 0.0
            det = 2 ** ((offset + f * p["detune"] / 100) / 12)
            sig = _osc(freq * det, shape, pw, rng.random()) * level / np.sqrt(uni)
            pan = 0.5 + f * p["spread"]
            out[:, 0] += sig * np.cos(pan * np.pi / 2) * np.sqrt(2)
            out[:, 1] += sig * np.sin(pan * np.pi / 2) * np.sqrt(2)
    if p["sub"]:
        sub = _osc(freq / 2, SINE, pw, 0.0) * p["sub"]
        out += sub[:, None]
    if p["fm"]:
        ratio, index, fall = p["fm"]
        carrier = np.cumsum(freq) / SR
        depth = index * np.exp(-t / fall) * (vel / 127)
        tone = np.sin(2 * np.pi * carrier + depth * np.sin(2 * np.pi * carrier * ratio))
        out += tone[:, None]
    if p["noise"]:
        if p["noise_rate"]:
            held = np.sign(rng.standard_normal((int(n * p["noise_rate"] / SR) + 2, 1)))
            out += held[(t * p["noise_rate"]).astype(int)] * p["noise"]
        else:
            out += rng.standard_normal((n, 2)) * p["noise"]

    if p["formant"]:
        # a talk box: the same source through three vowel resonances that move over the note
        vs = [VOWELS[c] for c in p["formant"]]
        pos = np.minimum(1, t / max(dur, 1e-3)) * (len(vs) - 1)
        lo = np.minimum(pos.astype(int), len(vs) - 2) if len(vs) > 1 else np.zeros(n, int)
        frac = pos - lo
        shaped = np.zeros_like(out)
        for j in range(3):
            table = np.array([v[j] for v in vs], float)
            fc = table[lo] + (table[np.minimum(lo + 1, len(vs) - 1)] - table[lo]) * frac
            for c in range(2):
                shaped[:, c] += _svf(out[:, c], fc, 7.0, 1) * FORMANT_GAIN[j]
        out = shaped * 2.2
    else:
        fenv = adsr(n, gate, *p["filt"])
        velf = (vel / 127) ** 0.5
        cut = p["cutoff"] * 2 ** (p["keytrack"] * (key - 60) / 12) * 2 ** (p["env_oct"] * fenv * velf)
        if p["lfo"]:
            period, depth, offset = p["lfo"]
            phase = ((start + t) / beat - offset) / period
            cut = cut * 2 ** (depth * (0.5 - 0.5 * np.cos(2 * np.pi * phase)) - depth)
        for c in range(2):
            out[:, c] = _svf(out[:, c], cut, p["res"], p["mode"])

    if p["drive"]:
        out = np.tanh(out * (1 + p["drive"])) / np.tanh(1 + p["drive"])
    gain = (vel / 127) ** (2 * p["velsens"])
    return out * adsr(n, gate, *p["amp"])[:, None] * gain


# ==== parts ====

def render_part(events, patch, fx, bpm, loop, repeats, total):
    """Renders one loop of a part, tiles it and runs the effects on the song clock."""
    p = {**DEFAULT, **patch}
    beat = 60 / bpm
    sps = beat * SR
    notes = []
    prev = None
    for i, (b, d, key, vel) in enumerate(sorted(events)):
        # a note that starts as the last one ends slides into it
        slide = prev[2] if prev and p["glide"] and b <= prev[0] + prev[1] + 0.01 else None
        rng = np.random.default_rng(i)
        notes.append((round(b * sps), voice(p, key, vel, d * beat, b * beat, beat, rng, slide)))
        prev = (b, d, key)
    longest = max((len(v) for _, v in notes), default=0)
    one = np.zeros((loop + longest, 2))
    for at, v in notes:
        one[at: at + len(v)] += v
    out = np.zeros((total, 2))
    for r in range(repeats):
        start = r * loop
        end = min(total, start + len(one))
        out[start:end] += one[: end - start]
    return effects(out, fx, bpm)


def effects(x, fx, bpm):
    beat = 60 / bpm
    n = len(x)
    t = np.arange(n) / SR
    if fx.get("hp"):
        cut = np.full(n, float(fx["hp"]))
        x = np.stack([_svf(x[:, c], cut, 0.7, 2) for c in range(2)], axis=1)
    if fx.get("chorus"):
        mix, depth_ms, period = fx["chorus"]
        wet = np.zeros_like(x)
        for c, off in ((0, 0.0), (1, 0.5)):
            d = (8 + depth_ms * (0.5 + 0.5 * np.sin(2 * np.pi * (t / (period * beat) + off)))) * SR / 1000
            pos = np.arange(n) - d
            i0 = np.clip(np.floor(pos).astype(int), 0, n - 1)
            fr = pos - np.floor(pos)
            src = x[:, c]
            wet[:, c] = src[i0] * (1 - fr) + src[np.minimum(i0 + 1, n - 1)] * fr
        x = x * (1 - mix * 0.5) + wet * mix
    if fx.get("width"):
        mid, side = (x[:, 0] + x[:, 1]) / 2, (x[:, 0] - x[:, 1]) / 2 * fx["width"]
        x = np.stack([mid + side, mid - side], axis=1)
    if fx.get("delay"):
        mix, beats, feedback = fx["delay"]
        x = x + _pingpong(x, round(beats * beat * SR), feedback, 0.35) * mix
    if fx.get("sidechain"):
        # ducks on every beat like a four on the floor kick is pressing it down
        depth, release = fx["sidechain"]
        since = (t / beat) % 1
        duck = depth * np.exp(-since / release) * np.minimum(1, since * beat / 0.004)
        x = x * (1 - duck)[:, None]
    return x
