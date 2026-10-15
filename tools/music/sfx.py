"""Designs and renders the Bumper Brawl sound effects.

Each effect is built from a few synth layers (pitch sweeps, filtered noise)
plus soundfont instruments where a real sample sounds better, then written
to web/sfx/NAME.mp3 at the same peak level. Loudness per effect is set in
the client, which also varies the pitch a little on every play.

> run   python3 tools/music/sfx.py path/to/GeneralUser-GS.sf2
> needs the same setup as compose.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt

from compose import DRUM, SR, Song, midi, render_dry

OUT = Path(__file__).resolve().parents[2] / "web" / "sfx"
PEAK = 0.8
rng = np.random.default_rng(3)

# ==== building blocks ====


def times(seconds):
    return np.arange(int(seconds * SR)) / SR


def glide(f0, f1, seconds):
    """Frequency curve that moves exponentially from f0 to f1."""
    return f0 * (f1 / f0) ** (times(seconds) / seconds)


def tone(freq, harmonics=(1.0,)):
    phase = 2 * np.pi * np.cumsum(freq) / SR
    return sum(a * np.sin(phase * (i + 1)) for i, a in enumerate(harmonics))


def envelope(n, attack, decay):
    t = np.arange(n) / SR
    return np.minimum(1, t / max(attack, 1e-4)) * np.exp(-np.maximum(0, t - attack) / decay)


def noise(seconds):
    return rng.standard_normal(int(seconds * SR))


def lowpass(x, fc, order=2):
    return sosfilt(butter(order, fc, "low", fs=SR, output="sos"), x)


def bandpass(x, lo, hi, order=2):
    return sosfilt(butter(order, [lo, hi], "band", fs=SR, output="sos"), x)


def sweep_lowpass(x, f0, f1):
    """One-pole lowpass whose cutoff glides from f0 to f1, for whooshes."""
    cut = f0 * (f1 / f0) ** np.linspace(0, 1, len(x))
    a = np.exp(-2 * np.pi * cut / SR)
    y = np.empty_like(x)
    prev = 0.0
    for i, v in enumerate(x):
        prev = (1 - a[i]) * v + a[i] * prev
        y[i] = prev
    return y


def mix(length, *parts):
    """Lays (offset seconds, signal, gain) parts into one buffer."""
    out = np.zeros(int(length * SR))
    for offset, sig, gain in parts:
        start = int(offset * SR)
        end = min(len(out), start + len(sig))
        out[start:end] += sig[: end - start] * gain
    return out


def instrument(soundfont, notes, length, drums=False, preset=0):
    """Plays (time, duration, key, velocity) notes on one soundfont preset, times in seconds."""
    song = Song(60, 1)
    song.channel(9 if drums else 0, preset, 110, 64, drums=drums)
    for at, dur, key, vel in notes:
        song.note(9 if drums else 0, at, dur, key, vel)
    audio, _ = render_dry(song, soundfont, 1, length)
    return audio.mean(axis=1)


# ==== effects ====


def bonk(sf):
    body = tone(glide(520, 180, 0.16), (1, 0.3)) * envelope(int(0.16 * SR), 0.002, 0.05)
    squish = bandpass(noise(0.03), 900, 2200) * envelope(int(0.03 * SR), 0.001, 0.008)
    wood = instrument(sf, [(0, 0.1, DRUM_WOOD_LOW, 110)], 0.2, drums=True)
    return mix(0.25, (0, body, 1), (0, squish, 0.4), (0, wood, 0.8))


def bonk_big(sf):
    body = tone(glide(360, 85, 0.26), (1, 0.4, 0.15)) * envelope(int(0.26 * SR), 0.002, 0.08)
    thump = lowpass(noise(0.12), 380) * envelope(int(0.12 * SR), 0.001, 0.03)
    wood = instrument(sf, [(0, 0.1, DRUM_WOOD_LOW, 127)], 0.2, drums=True)
    return np.tanh(mix(0.35, (0, body, 1.2), (0, thump, 1.5), (0, wood, 0.8)) * 1.4)


def dash(_sf, seconds=0.28, top=4200):
    n = noise(seconds)
    shaped = sweep_lowpass(n, 500, top) * np.sin(np.pi * np.linspace(0, 1, len(n))) ** 1.5
    return shaped


def dash_big(sf):
    whoosh = dash(sf, 0.45, 3200)
    swoop = tone(glide(180, 520, 0.4), (1, 0.2)) * np.sin(np.pi * np.linspace(0, 1, int(0.4 * SR))) * 0.25
    return mix(0.45, (0, whoosh, 1), (0, swoop, 1))


def charge(_sf):
    n = int(1.0 * SR)
    t = times(1.0)
    freq = glide(170, 720, 1.0)
    trem = 0.75 + 0.25 * np.sin(2 * np.pi * np.cumsum(np.linspace(12, 34, n)) / SR)
    whirr = tone(freq, (1, 0.35, 0.15)) * trem * np.minimum(1, t / 0.08)
    return whirr


def jump(_sf):
    t = times(0.3)
    freq = glide(210, 540, 0.3) * (1 + 0.06 * np.sin(2 * np.pi * 22 * t) * t / 0.3)
    return tone(freq, (1, 0.5, 0.25)) * envelope(len(t), 0.004, 0.12)


def land(_sf):
    thud = tone(glide(150, 60, 0.1)) * envelope(int(0.1 * SR), 0.001, 0.035)
    puff = lowpass(noise(0.06), 320) * envelope(int(0.06 * SR), 0.001, 0.02)
    return mix(0.12, (0, thud, 1), (0, puff, 1.2))


def splash(_sf):
    wash = lowpass(noise(0.7), 2600) * envelope(int(0.7 * SR), 0.004, 0.18)
    parts = [(0, wash, 1)]
    for i in range(7):
        f0 = rng.uniform(380, 650)
        b = tone(glide(f0, f0 * 2.4, 0.035)) * envelope(int(0.035 * SR), 0.002, 0.012)
        parts.append((0.08 + i * rng.uniform(0.03, 0.06), b, 0.35))
    return mix(0.75, *parts)


def fell(_sf):
    t = times(0.75)
    freq = glide(1500, 330, 0.75) * (1 + 0.03 * np.sin(2 * np.pi * 7 * t))
    whistle = tone(freq, (1, 0.08)) * np.minimum(1, t / 0.03) * np.minimum(1, (0.75 - t) / 0.08)
    breath = bandpass(noise(0.75), 1200, 4000) * 0.05
    return whistle + breath


def ko(sf):
    return instrument(sf, [(0, 0.3, midi("G6"), 110), (0.07, 0.3, midi("B6"), 110), (0.14, 0.6, midi("D7"), 120)],
                      0.9, preset=9)


def out(sf):
    notes = [(0, 0.38, midi("G3"), 100), (0.42, 0.38, midi("F#3"), 100), (0.84, 0.38, midi("F3"), 100),
             (1.26, 1.1, midi("E3"), 105)]
    horn = instrument(sf, notes, 2.6, preset=57)
    # the classic wobble on the last note
    t = np.arange(len(horn)) / SR
    wobble = np.where(t > 1.35, 1 + 0.35 * np.sin(2 * np.pi * 6 * (t - 1.35)), 1)
    return horn * wobble


def start(sf):
    t = times(0.5)
    pea = 0.6 + 0.4 * np.abs(np.sin(2 * np.pi * 34 * t))
    whistle = (np.sin(2 * np.pi * 2900 * t) + 0.7 * np.sin(2 * np.pi * 3120 * t)) * pea
    whistle *= np.minimum(1, t / 0.01) * np.minimum(1, (0.5 - t) / 0.05)
    breath = bandpass(noise(0.5), 2400, 3800) * 0.12
    hit = instrument(sf, [(0, 0.4, k, 115) for k in (midi("G4"), midi("B4"), midi("D5"), midi("G5"))], 0.8, preset=61)
    return mix(1.3, (0, (whistle + breath) * 0.5, 1), (0.52, hit, 1))


def coin(_sf):
    def square(freq, seconds):
        t = times(seconds)
        return lowpass(np.sign(np.sin(2 * np.pi * freq * t)), 5000)
    a = square(988, 0.07) * 0.8
    b = square(1319, 0.3) * envelope(int(0.3 * SR), 0.001, 0.09)
    return mix(0.37, (0, a, 1), (0.07, b, 1))


def pickup(sf):
    notes = [(i * 0.05, 0.4, midi(k), 115) for i, k in enumerate(["C6", "E6", "G6", "C7", "E7"])]
    bells = instrument(sf, notes, 0.9, preset=8)
    shimmer = bandpass(noise(0.6), 6000, 12000) * envelope(int(0.6 * SR), 0.05, 0.15) * 0.08
    return mix(0.9, (0, bells, 1), (0.1, shimmer, 1))


def pound(sf):
    boom = tone(glide(95, 32, 0.6), (1, 0.3)) * envelope(int(0.6 * SR), 0.002, 0.18)
    thump = lowpass(noise(0.2), 260) * envelope(int(0.2 * SR), 0.001, 0.05)
    crash = instrument(sf, [(0, 1, DRUM["crash"], 90)], 0.9, drums=True)
    return np.tanh(mix(0.9, (0, boom, 1.4), (0, thump, 1.6), (0, crash, 0.35)) * 1.3)


def crown(sf):
    notes = [(0, 0.08, midi("C5"), 105), (0.08, 0.08, midi("E5"), 105), (0.16, 0.08, midi("G5"), 105),
             (0.26, 0.5, midi("C6"), 118)]
    brass = instrument(sf, notes, 1.0, preset=61)
    sparkle = instrument(sf, [(0.26 + i * 0.06, 0.3, midi(k), 100) for i, k in enumerate(["C7", "E7", "G7"])], 1.0, preset=9)
    return mix(1.0, (0, brass, 1), (0, sparkle, 0.5))


def log_land(sf):
    boom = tone(glide(72, 30, 0.7), (1, 0.4)) * envelope(int(0.7 * SR), 0.002, 0.22)
    clack = instrument(sf, [(0, 0.2, DRUM_WOOD_LOW, 127)], 0.3, drums=True)
    rumble = lowpass(noise(0.5), 180) * envelope(int(0.5 * SR), 0.005, 0.15)
    return np.tanh(mix(0.8, (0, boom, 1.4), (0, clack, 0.9), (0, rumble, 1.5)) * 1.2)


def tick(sf):
    return instrument(sf, [(0, 0.1, DRUM_WOOD_HIGH, 110)], 0.15, drums=True)


def click(_sf):
    return tone(glide(650, 1050, 0.045)) * envelope(int(0.045 * SR), 0.001, 0.015)


DRUM_WOOD_HIGH = 76
DRUM_WOOD_LOW = 77

EFFECTS = [bonk, bonk_big, dash, dash_big, charge, jump, land, splash, fell, ko, out, start, coin, pickup,
           pound, crown, log_land, tick, click]


def encode(sig, name):
    sig = sig / np.abs(sig).max() * PEAK
    # soundfont notes ring on for seconds below hearing; cut the tail with a short fade
    loud = np.nonzero(np.abs(sig) > PEAK * 0.003)[0]
    end = min(len(sig), loud[-1] + int(0.02 * SR))
    fade = min(end, int(0.03 * SR))
    sig = sig[:end].copy()
    sig[-fade:] *= np.linspace(1, 0, fade)
    with tempfile.NamedTemporaryFile(suffix=".f32") as tmp:
        sig.astype("<f4").tofile(tmp.name)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", tmp.name,
                        "-c:a", "libmp3lame", "-q:a", "4", str(OUT / f"{name}.mp3")], check=True)


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: sfx.py GeneralUser-GS.sf2")
    OUT.mkdir(parents=True, exist_ok=True)
    for fx in EFFECTS:
        encode(fx(sys.argv[1]), fx.__name__)
        print(fx.__name__)


if __name__ == "__main__":
    main()
