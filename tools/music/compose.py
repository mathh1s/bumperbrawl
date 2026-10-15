"""Composes and renders the Bumper Brawl soundtrack.

Every track is written as note grids and patterns below, played through a
soundfont, given a convolution reverb and encoded to mp3. The loops use
MuseScore General for its livelier brass and mallets, the victory jingle
GeneralUser GS, and synth parts from synth.py are layered over the band.

The target is the Fall Guys sound: high energy party music mixing happy
hardcore, slap bass funk, jungle breaks and console game melodies, squishy
synths, toy noises, nonsense vocal chops, and key changes that lift a section
and come back home for the loop.

Loops are cut from the middle of a three times render so the reverb and note
tails of the previous pass are already present at the loop start, which makes
the loop seamless. The loop points land in
web/music/tracks.json.

> setup      pip install --no-deps tinysoundfont && pip install numpy scipy numba
> soundfont  git clone --depth 1 https://github.com/mrbumpy409/GeneralUser-GS
> soundfont  https://ftp.osuosl.org/pub/musescore/soundfont/MuseScore_General/MuseScore_General.sf2
> run        python3 tools/music/compose.py GeneralUser-GS.sf2 MuseScore_General.sf2
> needs      ffmpeg with libmp3lame on PATH
"""

import copy
import json
import random
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import tinysoundfont
from scipy.signal import oaconvolve

from synth import PULSE, SAW, SINE, TRI, render_part

SR = 44100
PAD = 0.5
OUT = Path(__file__).resolve().parents[2] / "web" / "music"

# ==== notes and chords ====

NAMES = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6,
         "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}

QUALITIES = {"": [0, 4, 7], "m": [0, 3, 7], "7": [0, 4, 7, 10], "maj7": [0, 4, 7, 11], "m7": [0, 3, 7, 10],
             "sus": [0, 5, 7], "7sus": [0, 5, 7, 10], "dim": [0, 3, 6]}

DRUM = {"kick": 36, "rim": 37, "snare": 38, "clap": 39, "hat": 42, "ohat": 46, "ltom": 45, "mtom": 47,
        "htom": 50, "crash": 49, "ride": 51, "tamb": 54, "cowbell": 56, "hbongo": 60, "lbongo": 61,
        "shaker": 70}


def midi(name):
    return 12 * (int(name[-1]) + 1) + NAMES[name[:-1]]


def parse_chord(sym):
    sym, _, bass = sym.partition("/")
    root = sym[:2] if len(sym) > 1 and sym[1] in "#b" else sym[:1]
    return NAMES[root], QUALITIES[sym[len(root):]], NAMES[bass] if bass else None


def voicing(sym, center):
    root, ivs, _ = parse_chord(sym)
    notes = []
    for iv in ivs:
        n = root + iv
        n += 12 * round((center - n) / 12)
        notes.append(n)
    return sorted(notes)


def bass_root(sym, octave=2):
    root, _, slash = parse_chord(sym)
    return 12 * (octave + 1) + (slash if slash is not None else root)


def bar_chords(entry):
    parts = entry.split()
    return [(p, i * 4 / len(parts), 4 / len(parts)) for i, p in enumerate(parts)]


# ==== song ====

class Song:
    def __init__(self, bpm, bars):
        self.bpm = bpm
        self.bars = bars
        self.events = []
        self.channels = {}
        self.levels = {}
        self.synths = {}
        self.sf_level = None
        self.lifts = []
        self.swing = 0.0
        # round songs: part -> (first bar, bar after the last), see render_sections()
        self.sections = {}
        # set while rendering sections so every part uses the gains and peak of the whole song
        self.gains = None
        self.peak = None
        # reverb length, decay and send; every song gets its own room
        self.room = (1.7, 0.38, 0.22)
        self.color = []

    def channel(self, ch, preset, volume=100, pan=64, bank=0, drums=False, level=None):
        """level is the target loudness in dB while the part plays; None leaves the synth's own balance."""
        self.channels[ch] = (bank, preset, drums, volume, pan)
        if level is not None:
            self.levels[ch] = level

    def synth(self, name, patch, level, fx=None):
        """A synth part next to the soundfont channels; notes go to it by name like to a channel number."""
        self.synths[name] = (patch, fx or {})
        self.levels[name] = level

    def lift(self, first, last, semis):
        """A key change for bars first to last, written in the home key and moved up here."""
        self.lifts.append((first * 4, (last + 1) * 4, semis))

    def kit(self, prefix, drums):
        """Drums built from synth voices: name -> (patch, level, fx). Played with beat()."""
        for name, (patch, level, fx) in drums.items():
            self.synth(f"{prefix}.{name}", patch, level, fx)

    def beat(self, bar, pattern, prefix, step=0.25, key=60):
        """Like drums(), on a synth kit. X accent, x normal, o soft, '.' nothing."""
        for name, steps in pattern.items():
            for i, c in enumerate(steps.replace(" ", "")):
                if c in "Xxo":
                    vel = {"X": 120, "x": 96, "o": 62}[c] + random.uniform(-6, 6)
                    self.events.append((bar * 4 + i * step + self.swung(i * step), 0.1, f"{prefix}.{name}", key, int(vel)))

    def swung(self, beat):
        # pushes the second and fourth sixteenth of every beat late
        return self.swing * 0.25 if self.swing and abs(beat % 0.5 - 0.25) < 1e-6 else 0.0

    def note(self, ch, beat, dur, key, vel):
        beat += self.swung(beat)
        # drums never change key: channel 9 and kit parts, which are named kit.drum
        if ch != 9 and "." not in str(ch):
            key += sum(semis for a, b, semis in self.lifts if a <= beat < b)
        self.events.append((beat, dur, ch, key, max(1, min(127, int(vel)))))

    def line(self, ch, bar, text, vel=90, step=0.5, legato=0.92, octave=0):
        """Notes on a grid. A token is a note name, '-' to hold the previous note or '.' for a rest."""
        tokens = [t for t in text.split() if t != "|"]
        beat = bar * 4
        current = None
        for tok in tokens:
            if tok == "-" and current:
                current[1] += step
            else:
                if current:
                    self.note(ch, current[0], current[1] * legato, current[2], current[3])
                current = None if tok == "." else [beat, step, midi(tok) + 12 * octave, vel + random.uniform(-6, 6)]
            beat += step
        if current:
            self.note(ch, current[0], current[1] * legato, current[2], current[3])

    def chords(self, ch, bar, sym, positions, dur, center, vel):
        """Chord stabs at eighth note positions within one chord span."""
        for start, chord, span in self.spans(bar, sym):
            for p in positions:
                if p * 0.5 < span:
                    for k in voicing(chord, center):
                        self.note(ch, start + p * 0.5, dur, k, vel + random.uniform(-5, 5))

    def spans(self, bar, sym):
        return [(bar * 4 + off, chord, span) for chord, off, span in bar_chords(sym)]

    def bass(self, ch, bar, sym, pattern, vel, octave=2, step=0.5):
        """Bass on a grid, eighths unless step says otherwise. R root, 8 octave, 5 fifth, 3 third, 7 seventh,
        '-' hold, '.' rest."""
        for start, chord, span in self.spans(bar, sym):
            root = bass_root(chord, octave)
            _, ivs, _ = parse_chord(chord)
            tokens = pattern.split()[: int(span / step)]
            current = None
            for i, tok in enumerate(tokens):
                if tok == "-" and current:
                    current[1] += step
                    continue
                if current:
                    self.note(ch, *current)
                current = None
                if tok != ".":
                    off = {"R": 0, "8": 12, "5": 7, "3": ivs[1], "7": ivs[3] if len(ivs) > 3 else 10}[tok]
                    current = [start + i * step, step * 0.9, root + off, vel + random.uniform(-6, 4)]
            if current:
                self.note(ch, *current)

    def arp(self, ch, bar, sym, order, center, vel, step=0.25, legato=0.8):
        """Arpeggio through the chord, order indexes the chord tones with the octave above appended."""
        for start, chord, span in self.spans(bar, sym):
            tones = voicing(chord, center)
            tones += [k + 12 for k in tones]
            for j in range(int(span / step)):
                k = tones[order[j % len(order)] % len(tones)]
                self.note(ch, start + j * step, step * legato, k, vel + (10 if j % 4 == 0 else 0) + random.uniform(-6, 6))

    def pad(self, ch, bar, sym, center, vel, length=0.97):
        for start, chord, span in self.spans(bar, sym):
            for k in voicing(chord, center):
                self.note(ch, start, span * length, k, vel)

    def hits(self, ch, bar, sym, rhythm, center, vel, dur=0.2, step=0.25):
        """Hits on chord tones, sixteenths unless step says otherwise: a digit picks the tone of the chord
        playing at that moment."""
        steps = rhythm.replace(" ", "")
        for start, chord, span in self.spans(bar, sym):
            tones = voicing(chord, center)
            tones += [k + 12 for k in tones]
            first = round((start - bar * 4) / step)
            for j in range(first, first + round(span / step)):
                if steps[j].isdigit():
                    self.note(ch, bar * 4 + j * step, dur, tones[int(steps[j]) % len(tones)], vel + random.uniform(-6, 6))

    def drums(self, bar, pattern, ch=9, step=0.25):
        """One character per step for each instrument, sixteenths by default (twelve steps a bar for
        a triplet feel with step 1/3). X accent, x normal, o soft, '.' nothing."""
        for name, steps in pattern.items():
            for i, s in enumerate(steps.replace(" ", "")):
                if s in "Xxo":
                    self.note(ch, bar * 4 + i * step, 0.2, DRUM[name], {"X": 118, "x": 92, "o": 58}[s] + random.uniform(-6, 6))


# ==== rendering ====

def reverb_ir(seconds=1.7, decay=0.38, predelay=0.018):
    seconds = max(seconds, decay * 4)
    rng = np.random.default_rng(7)
    n = int(seconds * SR)
    t = np.arange(n) / SR
    env = np.exp(-t / decay)
    ir = rng.standard_normal((n, 2)) * env[:, None]
    # darken the tail so it sits behind the dry signal
    for _ in range(3):
        ir[1:] = 0.55 * ir[1:] + 0.45 * ir[:-1]
    ir = np.concatenate([np.zeros((int(predelay * SR), 2)), ir])
    return ir / np.sqrt((ir ** 2).sum(axis=0))


def active_rms_db(audio, window=2048):
    frames = audio[: len(audio) // window * window].reshape(-1, window, 2)
    rms = np.sqrt((frames ** 2).mean(axis=(1, 2)))
    playing = rms[rms > 1e-4]
    return 20 * np.log10(playing.mean()) if len(playing) else -120.0


# Soundfont presets differ in loudness by 30 dB or more, so parts with a target
# level are rendered alone and set to that level before mixing. Songs without
# per channel levels render the soundfont in one go, optionally set to sf_level.
def render(song, soundfont, repeats, tail=3.0):
    sf_channels = [ch for ch in song.channels if ch in song.levels]
    stems = []
    if sf_channels:
        for ch in sf_channels:
            part = copy.copy(song)
            part.events = [e for e in song.events if e[2] == ch]
            part.channels = {ch: song.channels[ch]}
            stem, loop_samples = render_dry(part, soundfont, repeats, tail)
            stems.append((ch, stem, song.levels[ch]))
    else:
        part = copy.copy(song)
        part.events = [e for e in song.events if e[2] in song.channels]
        stem, loop_samples = render_dry(part, soundfont, repeats, tail)
        stems.append(("sf", stem, song.sf_level))
    total = len(stems[0][1])
    for name, (patch, fx) in song.synths.items():
        events = [(b, d, k, v) for b, d, ch, k, v in song.events if ch == name]
        stems.append((name, render_part(events, patch, fx, song.bpm, loop_samples, repeats, total), song.levels[name]))
    dry = None
    gains = {}
    for name, stem, level in stems:
        if song.gains is not None:
            gains[name] = song.gains.get(name, 1.0)
        elif level is not None and stem.any():
            gains[name] = 10 ** ((level - active_rms_db(stem)) / 20)
        else:
            gains[name] = 1.0
        stem = stem * gains[name]
        dry = stem if dry is None else dry + stem
    song.measured = gains
    seconds, decay, send = song.room
    ir = reverb_ir(seconds, decay)
    wet = np.stack([oaconvolve(dry[:, c], ir[:, c])[: len(dry)] for c in range(2)], axis=1)
    mix = dry + wet * send
    song.measured_peak = np.abs(mix).max()
    return colour(mix, song), loop_samples


def colour(audio, song):
    """Whole song processing that gives a track its character. Memoryless or clocked to the beat,
    so the loop stays periodic."""
    n = len(audio)
    t = np.arange(n) / SR
    for kind, *args in song.color:
        if kind == "crush":
            # fewer bits and a lower sample rate, a cheap console's output stage
            bits, rate = args
            hold = np.maximum(1, round(SR / rate))
            idx = (np.arange(n) // hold) * hold
            peak = song.peak or np.abs(audio).max()
            q = 2 ** (bits - 1)
            audio = np.round(audio[idx] / peak * q) / q * peak
        elif kind == "tape":
            # slow pitch drift from a delay line wobbling once every few beats
            depth_ms, beats = args
            d = (depth_ms * (0.5 + 0.5 * np.sin(2 * np.pi * t / (beats * 60 / song.bpm)))) * SR / 1000
            pos = np.clip(np.arange(n) - d, 0, n - 1)
            i0 = np.floor(pos).astype(int)
            fr = (pos - i0)[:, None]
            audio = audio[i0] * (1 - fr) + audio[np.minimum(i0 + 1, n - 1)] * fr
        elif kind == "lowpass":
            from synth import _svf
            audio = np.stack([_svf(audio[:, c], np.full(n, float(args[0])), 0.7, 0) for c in range(2)], axis=1)
        elif kind == "drive":
            audio = np.tanh(audio / (song.peak or np.abs(audio).max()) * args[0])
    return audio


def render_dry(song, soundfont, repeats, tail):
    synth = tinysoundfont.Synth(samplerate=SR)
    sfid = synth.sfload(soundfont)
    for ch, (bank, preset, drums, volume, pan) in song.channels.items():
        synth.program_select(ch, sfid, 128 if drums else bank, preset, is_drums=drums)
        synth.control_change(ch, 7, volume)
        synth.control_change(ch, 10, pan)

    # scheduling in whole samples makes every repeat bit identical, so the loop has no drift
    sps = 60 / song.bpm * SR
    loop_samples = round(song.bars * 4 * sps)
    timeline = []
    for r in range(repeats):
        for beat, dur, ch, key, vel in song.events:
            on = round(beat * sps) + r * loop_samples
            timeline.append((round((beat + dur) * sps) + r * loop_samples, 0, ch, key, 0))
            timeline.append((on, 1, ch, key, vel))
    timeline.sort(key=lambda e: (e[0], e[1]))

    total = repeats * loop_samples + int(tail * SR)
    chunks, cursor = [], 0
    for s, kind, ch, key, vel in timeline:
        if s > cursor:
            chunks.append(np.frombuffer(synth.generate(s - cursor), dtype=np.float32).reshape(-1, 2).copy())
            cursor = s
        if kind:
            synth.noteon(ch, key, vel)
        else:
            synth.noteoff(ch, key)
    chunks.append(np.frombuffer(synth.generate(total - cursor), dtype=np.float32).reshape(-1, 2).copy())
    return np.concatenate(chunks).astype(np.float64), loop_samples


def master(audio, target_rms=0.12):
    rms = np.sqrt((audio ** 2).mean())
    audio = audio * (target_rms / rms)
    # static gain plus a soft knee keeps the loop periodic, unlike a dynamic limiter
    # 0.84 ceiling leaves room for mp3 overshoot on decode
    return np.tanh(audio * 1.15) / np.tanh(1.15) * 0.84


def encode(audio, name):
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".f32") as tmp:
        audio.astype("<f4").tofile(tmp.name)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", tmp.name,
                        "-c:a", "libmp3lame", "-q:a", "3", str(OUT / f"{name}.mp3")], check=True)


def render_loop(song, soundfont, name):
    audio, loop = render(song, soundfont, repeats=3)
    pad = int(PAD * SR)
    cut = master(audio)[loop - pad: 2 * loop + pad]
    encode(cut, name)
    return {"file": f"music/{name}.mp3", "loopStart": pad / SR, "loopEnd": (pad + loop) / SR}


def section(song, first, end):
    part = copy.copy(song)
    part.events = [(b - first * 4, *rest) for b, *rest in song.events if first * 4 <= b < end * 4]
    part.bars = end - first
    return part


def render_sections(song, soundfont, name):
    """A round song as one file of four parts: the intro plays once, the loop repeats, and when the round
    is nearly over the game jumps on a bar line into the switch, which runs straight into the final loop.

    The loop and the final are cut from the middle of a three times render like render_loop(), so they wrap
    without a seam. Stem levels and the colour stage are measured once on the whole song and shared by all
    parts, so a quiet intro stays quiet instead of being turned up to match the loop."""
    render(song, soundfont, repeats=1, tail=0.5)
    song.gains, song.peak = song.measured, song.measured_peak
    parts = {}
    for part in ("intro", "loop", "switch", "final"):
        first, end = song.sections[part]
        cyclic = part in ("loop", "final")
        audio, length = render(section(song, first, end), soundfont, repeats=3 if cyclic else 1, tail=3.0 if cyclic else 0.0)
        parts[part] = audio[length: 2 * length] if cyclic else audio[:length]
    gain = 0.12 / np.sqrt((parts["loop"] ** 2).mean())
    pad = np.zeros((int(PAD * SR), 2))
    meta = {"file": f"music/{name}.mp3", "bar": 4 * 60 / song.bpm}
    out, pos = [pad], len(pad)
    for part in ("intro", "loop", "switch", "final"):
        x = np.tanh(parts[part] * gain * 1.15) / np.tanh(1.15) * 0.84
        meta[part] = [pos / SR, (pos + len(x)) / SR]
        out.append(x)
        pos += len(x)
    # trailing silence so the decoder never trims the end of the final loop
    out.append(pad)
    encode(np.concatenate(out), name)
    return meta


def render_once(song, soundfont, name):
    audio, _ = render(song, soundfont, repeats=1, tail=2.5)
    # one-shots end on a sharp hit that overshoots after mp3 encoding, so they sit a little lower
    encode(master(audio, 0.1) * 0.85, name)
    return {"file": f"music/{name}.mp3"}


# ==== drum voices ====
# Every song builds its own kit from these, tuned and shaped its own way, so no two share drums.

def semis(hz, key=60):
    return 12 * np.log2(hz / (440 * 2 ** ((key - 69) / 12)))


def kick(hz=50, punch=30, decay=0.32, click=0.05, drive=0.6):
    return {"osc": [(SINE, semis(hz), 1.0)], "pitch": (punch, 0.028), "amp": (0.0005, decay, 0.0, 0.05),
            "noise": click, "cutoff": 6000, "drive": drive, "velsens": 0.4}


def snare(hz=190, decay=0.16, snap=0.9, tone=0.6, bright=4200):
    return {"osc": [(TRI, semis(hz), tone)], "pitch": (4, 0.02), "noise": snap, "amp": (0.0005, decay, 0.0, 0.05),
            "cutoff": bright, "res": 0.8, "velsens": 0.5}


def clap(decay=0.14, bright=1300):
    return {"osc": [], "noise": 1.0, "amp": (0.002, decay, 0.0, 0.06), "cutoff": bright, "res": 1.6, "mode": 1,
            "velsens": 0.5}


def hat(decay=0.04, bright=7500, metal=0.7):
    # six square waves at the inharmonic ratios of a classic drum machine, high passed into a hiss
    freqs = (205.3, 304.4, 369.6, 522.7, 540, 800)
    return {"osc": [(PULSE, semis(f), metal / 3) for f in freqs], "noise": 0.35, "amp": (0.0005, decay, 0.0, 0.03),
            "cutoff": bright, "res": 0.9, "mode": 2, "velsens": 0.6}


def tom(hz=110, decay=0.22):
    return {"osc": [(SINE, semis(hz), 1.0), (TRI, semis(hz), 0.3)], "pitch": (9, 0.05),
            "amp": (0.0005, decay, 0.0, 0.05), "cutoff": 4000}


def shaker(decay=0.05):
    return {"osc": [], "noise": 1.0, "amp": (0.008, decay, 0.0, 0.03), "cutoff": 6500, "mode": 2, "velsens": 0.7}


def block(hz=900, decay=0.06):
    return {"osc": [], "fm": (2.76, 2.5, 0.02), "tune": semis(hz), "pitch": (2, 0.01),
            "amp": (0.0005, decay, 0.0, 0.03), "cutoff": 9000}


def click(bright=3000, decay=0.012):
    # a dry mechanical tick: a burst of band passed noise with no pitch, so it can't chirp
    return {"osc": [], "noise": 1.0, "amp": (0.0003, decay, 0.0, 0.006), "cutoff": bright, "res": 1.1, "mode": 1,
            "velsens": 0.5}


def rim(decay=0.03):
    # a rimshot: a short low knock under a noise crack
    return {"osc": [(TRI, semis(420), 0.5)], "noise": 0.8, "amp": (0.0003, decay, 0.0, 0.01), "cutoff": 2400,
            "res": 0.9, "mode": 1, "velsens": 0.6}


def cowbell(decay=0.18):
    return {"osc": [(PULSE, semis(540), 0.6), (PULSE, semis(800), 0.6)], "amp": (0.0005, decay, 0.1, 0.05),
            "cutoff": 2600, "res": 2.0, "mode": 1}


def chip_noise(rate, decay, level=1.0):
    return {"osc": [], "noise": level, "noise_rate": rate, "amp": (0.0005, decay, 0.0, 0.01), "cutoff": 16000}


def chip_kick(decay=0.12):
    return {"osc": [(TRI, semis(70), 1.0)], "pitch": (24, 0.03), "amp": (0.0005, decay, 0.0, 0.02),
            "cutoff": 16000}


# ==== effects ====

def riser(seconds):
    """White noise through a band pass that opens over the note, the swell into a new section."""
    return {"osc": [], "noise": 0.6, "amp": (seconds * 0.9, 1, 1, 0.08), "filt": (seconds, 1, 1, 0.1),
            "cutoff": 250, "env_oct": 5, "res": 2.0, "mode": 1}


# ==== tracks ====
# Each song has its own sound world: its own kit, its own synths, its own room and finish, and only
# the jam, the gumball and the final use soundfont instruments, each a different section of the band.


def menu():
    """Blob Lounge: menu and between rounds. Swung Eb major kids album funk in the Thundercat vein,
    no soundfont at all: a dusty drum machine, a bulbous bass that solos in the middle, an FM electric
    piano, a music box and the talk box singing. Finished on wobbly tape. Shape: a two bar intro,
    the song, a six bar bass solo over a half time beat, the song again with the music box, and a two
    bar stop that slides back into the top."""
    s = Song(112, 26)
    s.swing = 0.32
    s.room = (1.0, 0.25, 0.16)
    s.color = [("tape", 1.6, 8), ("lowpass", 9500)]
    s.kit("dust", {
        "kick": (kick(56, punch=16, decay=0.24, click=0.0, drive=0.2), -15, {}),
        "snare": (snare(215, decay=0.11, snap=0.55, bright=2600), -19, {}),
        "rim": (block(1650, decay=0.03), -25, {}),
        "hat": (hat(0.03, bright=6200, metal=0.3), -26, {}),
        "shk": (shaker(0.06), -28, {}),
    })
    s.synth("bass", {"osc": [(SINE, 0, 1.0), (SAW, 0, 0.4)], "amp": (0.003, 0.3, 0.7, 0.06), "glide": 0.05,
                     "cutoff": 650, "env_oct": 1.9, "filt": (0.001, 0.16, 0.2, 0.1), "res": 1.6, "drive": 0.3},
            -16, {})
    s.synth("ep", {"osc": [], "fm": (1.0, 2.4, 0.4), "amp": (0.002, 1.4, 0.25, 0.3), "cutoff": 5000,
                   "velsens": 0.8}, -22, {"chorus": (0.5, 4, 8), "hp": 140})
    s.synth("box", {"osc": [], "fm": (3.5, 3.2, 0.3), "amp": (0.001, 0.9, 0.0, 0.4), "cutoff": 9000},
            -25, {"delay": (0.3, 0.75, 0.35)})
    s.synth("talk", {"osc": [(SAW, 0, 1.0), (PULSE, 0, 0.5)], "unison": 2, "detune": 9, "spread": 0.3,
                     "formant": "oa", "amp": (0.012, 0.3, 0.85, 0.09), "glide": 0.06, "vib": (5.4, 24, 0.3),
                     "drive": 0.4}, -18, {"hp": 200, "delay": (0.16, 0.75, 0.3)})
    s.synth("ooh", {"osc": [(SAW, 0, 1.0)], "unison": 3, "detune": 14, "spread": 0.8, "formant": "u",
                    "amp": (0.25, 0.5, 0.9, 0.4)}, -25, {"hp": 250, "chorus": (0.5, 5, 8)})

    intro = ["Ebmaj7", "Bb7"]
    song = ["Ebmaj7", "Cm7", "Fm7", "Bb7", "Gm7", "C7", "Fm7 Bb7", "Ebmaj7"]
    solo = ["Abmaj7", "Bb7", "Gm7", "C7", "Fm7", "Bb7"]
    tag = ["Ebmaj7", "Bb7"]
    prog = intro + song + solo + song + tag

    melody = ["G5 . Bb5 . D6 - C6 Bb5", "G5 - - . Eb5 F5 G5 .", "Ab5 . C6 . Eb6 - D6 C6", "D6 - Bb5 - F5 . Ab5 .",
              "Bb5 . D6 . F6 - Eb6 D6", "E6 - C6 - G5 . Bb5 .", "Ab5 . G5 . F5 . D5 .", "Eb5 - - - . . . ."]
    box = ["D6 . . Bb6 . . G6 .", ". . Eb6 . G6 . . .", "C7 . . Ab6 . . F6 .", ". . D7 . Bb6 . . .",
           "F6 . . D7 . . Bb6 .", ". . G6 . E7 . . .", "C7 . Ab6 . D7 . Bb6 .", "G6 - - - . . . ."]
    solo_bass = ["Ab3 . C4 Eb4 G4 . Eb4 C4", "Bb3 . D4 F4 Ab4 . F4 D4", "G3 . Bb3 D4 F4 . D4 Bb3",
                 "C4 . E4 G4 Bb4 . G4 E4", "F3 . Ab3 C4 Eb4 . C4 Ab3", "Bb3 D4 F4 Ab4 Bb4 - - ."]
    solo_talk = ["C6 - - - - - - -", "D6 - - - - - - -", "D6 - - - Bb5 - - -", "E6 - - - - - - -",
                 "Eb6 - - - C6 - - -", "D6 - - - F6 - - -"]

    s.line("talk", 0, ". . . . . . G5 Bb5", 80, legato=0.98)
    for i in range(8):
        s.line("talk", 2 + i, melody[i], 92, legato=0.98)
        s.line("talk", 16 + i, melody[i], 96, legato=0.98)
        s.line("box", 16 + i, box[i], 84, legato=0.5)
    for i in range(6):
        s.line("bass", 10 + i, solo_bass[i], 104, legato=0.95)
        s.line("talk", 10 + i, solo_talk[i], 74, legato=0.98)

    for bar, chord in enumerate(prog):
        s.chords("ep", bar, chord, [0, 3] if bar % 2 else [1, 4, 6], 0.6, 63, 80)
        if bar < 2:
            s.pad("ooh", bar, chord, 64, 80)
        elif bar < 10 or 16 <= bar < 24:
            s.bass("bass", bar, chord, "R . . R 8 . 5 . R . 3 . 5 . 8 7", 100, step=0.25)
        elif bar < 16:
            s.pad("ooh", bar, chord, 60, 76)
        else:
            s.bass("bass", bar, chord, "R . . . . . . .", 104)
    # the bass slides up out of the stop into the loop
    s.line("bass", 25, ". . . . Bb2 C3 D3 Eb3", 100, legato=0.99)

    for bar in range(26):
        if bar < 2:
            s.beat(bar, {"hat": "x.x.x.x.x.x.x.xo", "rim": "....x.......x..."}, "dust")
        elif bar < 10 or 16 <= bar < 24:
            p = {"kick": "X.....x...X..o..", "snare": "....X.......X...", "hat": "xoxoxoxoxoxoxoxo",
                 "rim": "..o.....o..o...."}
            if bar % 8 == 1:
                p["snare"] = "....X.......X.oo"
            s.beat(bar, p, "dust")
        elif bar < 16:
            s.beat(bar, {"kick": "X.........x.....", "snare": "........X.......", "shk": "oxoxoxoxoxoxoxox"}, "dust")
        elif bar == 24:
            s.beat(bar, {"kick": "X...............", "snare": "X..............."}, "dust")
        else:
            s.beat(bar, {"snare": "....x.x.xxxxXXXX", "kick": "X......."}, "dust")
    return s


def jam():
    """Jelly Jam: round theme, C major synth funk at 132, all synth: a slap bass, a bouncy square lead,
    the jelly bean singers, plucks, pumping supersaws and a disco kit.

    > intro    the slap bass alone with claps, then the drums and a taste of the chorus hook
    > loop     verse on four on the floor, a call and answer section on funk breaks, the chorus with
               pumping supersaws, then a half time breakdown on a music box that builds back up
               through a snare roll into a gap
    > switch   one big hit, everything dives in pitch, the singers shout and a roll launches the final
    > final    the chorus a whole step up with the lead stacked on a supersaw an octave down and the
               singers in harmony, then a sixteenth note variation with a hoover, a fast arp and a ride,
               ending on a run that climbs back into the top
    """
    s = Song(132, 54)
    s.room = (1.2, 0.3, 0.17)
    s.sections = {"intro": (0, 4), "loop": (4, 36), "switch": (36, 38), "final": (38, 54)}
    s.lift(38, 53, 2)
    s.kit("jelly", {
        "kick": (kick(58, punch=26, decay=0.24, click=0.08, drive=0.6), -13, {}),
        "boom": (kick(48, punch=14, decay=0.6, click=0.05, drive=0.8), -14, {}),
        "snare": (snare(205, decay=0.16, snap=1.0, bright=6500), -18, {}),
        "clap": (clap(0.16, 1400), -19, {}),
        "hat": (hat(0.03, bright=8500), -25, {}),
        "ohat": (hat(0.2, bright=7500, metal=0.8), -25, {}),
        "tamb": (shaker(0.07), -27, {}),
        "ride": (hat(0.45, bright=5500, metal=1.0), -28, {}),
        "crash": (hat(1.0, bright=4500, metal=1.0), -23, {}),
        "tom": (tom(130, 0.2), -20, {}),
        "ltom": (tom(90, 0.26), -20, {}),
    })
    # every melodic synth starts right on its note: fast attack, no scoop, no glide
    s.synth("slap", {"osc": [(SAW, 0, 1.0), (PULSE, 0, 0.5)], "sub": 0.5, "amp": (0.001, 0.18, 0.45, 0.04),
                     "cutoff": 340, "env_oct": 3.2, "filt": (0.001, 0.07, 0.05, 0.04), "res": 2.0, "drive": 0.8},
            -15, {"sidechain": (0.25, 0.25)})
    s.synth("lead", {"osc": [(PULSE, 0, 1.0), (PULSE, 12, 0.25)], "pw": 0.4, "amp": (0.001, 0.15, 0.75, 0.05),
                     "cutoff": 3600, "env_oct": 1.0, "filt": (0.001, 0.1, 0.3, 0.05), "res": 1.2,
                     "vib": (5.5, 16, 0.25)}, -17, {"hp": 200, "delay": (0.15, 0.75, 0.25)})
    s.synth("saw", {"osc": [(SAW, 0, 1.0), (SAW, 12, 0.3)], "unison": 7, "detune": 30, "spread": 0.8,
                    "amp": (0.001, 0.2, 0.75, 0.05), "cutoff": 4200, "keytrack": 0.3, "res": 1.0,
                    "vib": (6, 12, 0.25)}, -19, {"hp": 200})
    vox = {"osc": [(PULSE, 0, 1.0), (SAW, 0, 0.6)], "pw": 0.3, "formant": "ua", "amp": (0.001, 0.1, 0.7, 0.04),
           "vib": (6, 12, 0.1), "drive": 0.3}
    s.synth("vox", vox, -18, {"hp": 250, "delay": (0.15, 0.75, 0.25)})
    s.synth("vox2", {**vox, "formant": "ia"}, -21, {"hp": 250, "width": 1.4})
    s.synth("pluck", {"osc": [(SAW, 0, 0.8), (PULSE, 0, 0.5)], "amp": (0.001, 0.14, 0.0, 0.06), "cutoff": 900,
                      "env_oct": 2.4, "filt": (0.001, 0.08, 0.0, 0.05), "res": 1.4, "unison": 2, "detune": 12,
                      "spread": 0.8}, -21, {"hp": 200})
    s.synth("stab", {"osc": [(SAW, 0, 1.0)], "unison": 7, "detune": 38, "spread": 0.9,
                     "amp": (0.001, 0.18, 0.25, 0.08), "filt": (0.001, 0.14, 0.15, 0.08), "cutoff": 1000,
                     "env_oct": 2.6, "res": 0.9}, -20, {"sidechain": (0.6, 0.3), "hp": 180, "width": 1.3})
    s.synth("pad", {"osc": [(SAW, 0, 1.0), (SAW, 7, 0.3)], "unison": 5, "detune": 24, "spread": 1.0,
                    "amp": (0.15, 1.0, 0.85, 0.35), "cutoff": 2000, "res": 0.8}, -24,
            {"sidechain": (0.5, 0.3), "hp": 160, "chorus": (0.4, 4, 8)})
    s.synth("rising", {"osc": [(SAW, 0, 1.0)], "unison": 5, "detune": 24, "spread": 1.0,
                       "amp": (0.05, 1.0, 0.9, 0.2), "cutoff": 300, "env_oct": 3.5, "filt": (7.0, 1.0, 1.0, 0.2),
                       "res": 1.6}, -22, {"hp": 160})
    s.synth("box", {"osc": [], "fm": (3.5, 3.0, 0.4), "amp": (0.001, 0.9, 0.0, 0.4), "cutoff": 9000},
            -20, {"delay": (0.35, 0.75, 0.4), "hp": 300})
    s.synth("arp", {"osc": [(PULSE, 0, 1.0), (SAW, 12, 0.3)], "pw": 0.3, "amp": (0.001, 0.08, 0.0, 0.04),
                    "cutoff": 2200, "env_oct": 1.2, "filt": (0.001, 0.05, 0.0, 0.03), "res": 1.8, "keytrack": 0.4},
            -23, {"hp": 300, "delay": (0.25, 0.75, 0.3)})
    s.synth("hoover", {"osc": [(SAW, 0, 1.0), (PULSE, -12, 0.6)], "unison": 5, "detune": 40, "spread": 1.0,
                       "pwm": 0.3, "pwm_rate": 2.0, "pitch": (-2, 0.012), "amp": (0.001, 0.25, 0.85, 0.05),
                       "cutoff": 2600, "res": 1.2, "drive": 0.8}, -20, {"hp": 120, "width": 1.2})
    s.synth("squeak", {"osc": [(SINE, 0, 1.0), (TRI, 0, 0.3)], "amp": (0.002, 0.15, 0.3, 0.04), "pitch": (-5, 0.06),
                       "vib": (18, 60, 0.02), "cutoff": 7000}, -25, {"delay": (0.2, 0.75, 0.3)})
    s.synth("dive", {"osc": [(SAW, 0, 1.0)], "unison": 5, "detune": 30, "spread": 1.0, "pitch": (24, 0.3),
                     "amp": (0.001, 0.9, 0.0, 0.2), "cutoff": 3000}, -19, {"hp": 80})
    s.synth("rise", riser(8 * 60 / 132), -24, {"hp": 200})
    s.synth("rise1", riser(4 * 60 / 132), -24, {"hp": 200})
    s.synth("impact", {"osc": [(SINE, 0, 1.0)], "amp": (0.001, 1.0, 0.0, 0.3), "pitch": (24, 0.15),
                       "cutoff": 3000, "drive": 0.5}, -16, {})

    IN, LP, SW, FN = 0, 4, 36, 38
    verse = ["C", "Am7", "Dm7", "G7", "C", "Am7", "Dm7 G7", "C"]
    answer = ["F", "G", "Em7", "Am7", "Dm7", "G", "E7", "E7"]
    chorus = ["F", "G", "Em7", "Am7", "Dm7", "G", "C", "C"]
    down = ["Am", "F", "C", "G", "Am", "F", "G", "G7"]
    prog = ["C", "Am7", "F", "G"] + verse + answer + chorus + down + ["G7", "G7"] + chorus + chorus

    verse_mel = ["G5 . E5 G5 . C6 . G5", "A5 . . G5 E5 . C5 .", "F5 . D5 F5 . A5 . F5", "G5 - - - F5 . D5 .",
                 "G5 . E5 G5 . C6 . E6", "D6 . C6 . A5 . G5 .", "F5 . A5 . B5 . D6 .", "C6 - - - . . . ."]
    call = ["A5 . C6 . . . . .", "B5 . D6 . . . . .", "G5 . B5 . . . . .", "C6 - - - . . . .",
            "F5 . A5 . . . . .", "G5 . B5 . . . . .", "G#5 . B5 . D6 . E6 .", "G#5 - - - B5 - D6 -"]
    reply = [". . . . C6 A5 F5 .", ". . . . D6 B5 G5 .", ". . . . E6 D6 B5 .", ". . . . A5 G5 E5 .",
             ". . . . D6 C6 A5 .", ". . . . D6 B5 G5 .", "", ""]
    hook = ["C6 . A5 C6 . F6 . E6", "D6 . B5 . G5 - . .", "B5 . G5 B5 . E6 . D6", "C6 . A5 . E5 - . .",
            "F5 . A5 . C6 . D6 .", "F6 . E6 . D6 . B5 .", "C6 - - - G5 . E5 .", "C6 - - - . . . ."]
    harm = ["A5 . F5 A5 . C6 . C6", "B5 . G5 . D5 - . .", "G5 . E5 G5 . B5 . B5", "A5 . E5 . C5 - . .",
            "D5 . F5 . A5 . B5 .", "D6 . C6 . B5 . G5 .", "E5 - - - E5 . C5 .", "E5 - - - . . . ."]
    box = ["E6 . C6 . A5 . . .", "F6 . C6 . A5 . . .", "G6 . E6 . C6 . . .", "D6 . B5 . G5 . . ."]
    climb = ["A5 - - - C6 - - -", "C6 - - - F6 - - -", "D6 - - - G6 - - -", "B5 - D6 - F6 - . ."]
    hook16 = ["C6 . C6 A5 C6 . F6 . A6 - G6 - F6 - E6 -", "D6 . D6 B5 D6 . G6 . B6 - A6 - G6 - D6 -",
              "B5 . B5 G5 B5 . E6 . G6 - F6 - E6 - D6 -", "C6 . C6 A5 C6 . E6 . A6 - - - E6 - C6 -",
              "D6 . D6 F6 . A6 . D7 - - C7 - A6 - F6 -", "B6 - - - G6 - - - D6 - - - B5 - - -",
              "C7 - - - G6 - E6 - C6 - - - G5 - - -", "G5 - A5 - B5 - C6 - D6 - E6 - F6 - G6 -"]

    # ---- intro: slap riff alone, then the band, with the chorus hook teased on top
    s.line("vox", IN + 1, ". . . . G5 . C6 .", 96)
    s.line("lead", IN + 2, hook[0], 96)
    s.line("lead", IN + 3, hook[1], 96)
    s.note("rise1", (IN + 3) * 4, 4, 60, 120)

    # ---- loop
    for i in range(8):
        a, b, c, d = LP + i, LP + 8 + i, LP + 16 + i, LP + 24 + i
        s.line("lead", a, verse_mel[i], 100)
        s.line("lead", b, call[i], 102)
        if reply[i]:
            s.line("vox", b, reply[i], 98)
        s.line("lead", c, hook[i], 104)
        s.line("vox", c, hook[i], 86, octave=-1)
        s.line("vox2", c, harm[i], 80)
        if i < 4:
            s.line("box", d, box[i], 96)
        else:
            s.line("lead", d, climb[i - 4], 92 + i * 2)
    s.note("rise", (LP + 30) * 4, 7.5, 60, 120)
    for at in (3, 7):
        s.note("squeak", (LP + at) * 4 + 3.5, 0.3, midi("G6"), 100)

    # ---- switch: a hit, the dive, a shout, and a roll
    for k in voicing("G7", 62):
        s.note("stab", SW * 4, 0.5, k, 120)
        s.note("dive", SW * 4, 2.5, k - 12, 110)
    s.line("vox", SW, ". . . . . . G5 C6", 110)
    s.note("rise1", (SW + 1) * 4, 4, 60, 120)
    s.note("impact", SW * 4, 4, midi("G1"), 120)

    # ---- final, a whole step up
    for i in range(8):
        a, b = FN + i, FN + 8 + i
        s.line("lead", a, hook[i], 108)
        s.line("saw", a, hook[i], 100, octave=-1)
        s.line("vox", a, harm[i], 94)
        s.line("lead", b, hook16[i], 110, step=0.25)
        s.line("saw", b, hook16[i], 100, step=0.25, octave=-1)
        s.hits("vox2", b, prog[b], "..2...2...2...2.", 79, 82, dur=0.1)
        for start, ch, span in s.spans(b, prog[b]):
            s.note("hoover", start, span * 0.95, bass_root(ch, 3), 100)
    s.note("impact", FN * 4, 4, midi("C1"), 120)
    s.note("impact", (FN + 8) * 4, 4, midi("C1"), 110)

    # ---- harmony and bass, section by section
    for bar, chord in enumerate(prog):
        if bar < LP:
            s.bass("slap", bar, chord, "R . . R 8 . R . . R . 8 R . 5 .", 106, step=0.25)
            if bar >= IN + 2:
                s.chords("pluck", bar, chord, [1, 3, 5, 7], 0.15, 67, 80)
        elif bar < LP + 8:
            s.bass("slap", bar, chord, "R . . R 8 . R . . R . 8 R . 5 .", 106, step=0.25)
            s.chords("pluck", bar, chord, [1, 3, 5, 7], 0.15, 67, 84)
        elif bar < LP + 16:
            s.bass("slap", bar, chord, "R . . . . . R 8 . . R . . . 8 .", 108, step=0.25)
            s.pad("pad", bar, chord, 62, 80)
        elif bar < LP + 24:
            s.bass("slap", bar, chord, "R . R 8 . R 8 . R . R 8 . 5 8 7", 110, step=0.25)
            s.chords("stab", bar, chord, [1, 3, 5, 7], 0.2, 67, 98)
        elif bar < LP + 28:
            s.bass("slap", bar, chord, "R - - - - - - - R - - - . . . .", 100, step=0.25)
            s.pad("pad", bar, chord, 62, 90)
        elif bar < SW:
            s.bass("slap", bar, chord, "R . R . R . R . R . R . R . R ." if bar < SW - 1 else "R . R . R . R . R . R . R . . .",
                   104 + (bar - LP - 28) * 3, step=0.25)
            s.pad("rising", bar, chord, 62, 96)
        elif bar < FN:
            continue
        else:
            s.bass("slap", bar, chord, "R . 8 R 8 . R 8 R . 8 R 8 . R 8", 112, step=0.25)
            s.chords("stab", bar, chord, [1, 3, 5, 7], 0.2, 67, 104)
            s.pad("pad", bar, chord, 62, 90)
            if bar >= FN + 8:
                s.arp("arp", bar, chord, [0, 1, 2, 3, 4, 3, 2, 1], 79, 84)

    # ---- drums
    disco = {"kick": "X...X...X...X...", "snare": "....X.......X...", "clap": "....X.......X...",
             "hat": "xoxoxoxoxoxoxoxo", "ohat": "..x...x...x...x."}
    fill = {"snare": "....X...x.xxXXXX", "tom": "........x.x.....", "ltom": "..........x.x..."}
    for bar in range(54):
        p = None
        if bar == IN:
            p = {"clap": "....X.......X..."}
        elif bar == IN + 1:
            p = {"clap": "....X.......X...", "hat": "x.x.x.x.x.x.x.x."}
        elif bar == IN + 2:
            p = {**disco, "crash": "X..............."}
        elif bar == IN + 3:
            p = {**disco, **fill}
        elif bar < LP + 8:
            p = dict(disco)
            if bar == LP:
                p["crash"] = "X..............."
            if bar == LP + 7:
                p.update(fill)
        elif bar < LP + 16:
            # beat switch: funk breaks under the call and answer
            p = {"kick": "X..X......X..X..", "snare": "....X..o.o..X...", "hat": "x.x.x.x.x.x.x.x.",
                 "tamb": "oxoxoxoxoxoxoxox"}
            if bar % 2:
                p.update(kick="X.........X.X...", snare="....X..o.o..X.oo")
            if bar == LP + 15:
                p["snare"] = "....X...xxxxXXXX"
        elif bar < LP + 24:
            p = {**disco, "tamb": "oxoxoxoxoxoxoxox", "ohat": "..X...X...X...X."}
            if bar in (LP + 16, LP + 20):
                p["crash"] = "X..............."
            if bar == LP + 23:
                p.update(fill)
        elif bar < LP + 28:
            # beat switch: half time breakdown
            p = {"boom": "X.........X.....", "clap": "........X.......", "tamb": "oxoxoxoxoxoxoxox"}
            if bar == LP + 24:
                p["crash"] = "X..............."
        elif bar < SW:
            k = bar - LP - 28
            roll = ["x...x...x...x...", "x.x.x.x.x.x.x.x.", "xxxxxxxxxxxxxxxx"]
            if k < 3:
                p = {"kick": "X...X...X...X...", "snare": roll[k], "hat": "x.x.x.x.x.x.x.x."}
            else:
                # thirty seconds that stop half a beat early, the gap before the loop comes round
                s.beat(bar, {"kick": "X.......X.......X.......", "snare": "xxxxxxxxxxxxxxxxXXXXXXXXXXXX...."},
                       "jelly", step=0.125)
                continue
        elif bar == SW:
            p = {"kick": "X...............", "crash": "X..............."}
        elif bar == SW + 1:
            s.beat(bar, {"kick": "X...............", "snare": "x.x.x.x.x.x.x.x.xxxxxxxxXXXXXXXX"}, "jelly", step=0.125)
            continue
        else:
            p = {"kick": "X...X...X...X...", "clap": "....X.......X...", "snare": "..o....o.o....o.",
                 "hat": "xoxoxoxoxoxoxoxo", "ohat": "..X...X...X...X."}
            if (bar - FN) % 4 == 0:
                p["crash"] = "X..............."
            if bar >= FN + 8:
                p.update(ride="x.x.x.x.x.x.x.x.", tamb="oxoxoxoxoxoxoxox")
            if bar == FN + 15:
                p.update(fill)
        s.beat(bar, p, "jelly")
    return s


def wobble():
    """Wobble Run: round theme, nothing but a cheap game console. A major at 168 with pulse wave leads
    whose duty cycle changes per section, a triangle bass, noise drums and chord arpeggios too fast to
    hear as notes, crushed to 8 bits. Shaped like level music rather than a song: a two bar start
    jingle, the level tune, the tune again higher with an echo, a six bar underground section where the
    bass takes the melody, an F sharp minor boss fight in triplets, and a pause jingle with a run back
    to the start."""
    s = Song(168, 34)
    s.room = (0.3, 0.06, 0.04)
    s.color = [("crush", 8, 22050)]
    s.kit("nes", {
        "kick": (chip_kick(0.1), -15, {}),
        "snare": (chip_noise(9000, 0.11), -19, {}),
        "hat": (chip_noise(30000, 0.025, 0.7), -26, {}),
        "crash": (chip_noise(14000, 0.5, 0.8), -25, {}),
    })
    sq = {"osc": [(PULSE, 0, 1.0)], "amp": (0.001, 0.1, 0.75, 0.02), "cutoff": 16000, "velsens": 0.3,
          "vib": (6.5, 25, 0.18), "glide": 0.03}
    s.synth("lead25", {**sq, "pw": 0.25}, -19, {})
    s.synth("lead12", {**sq, "pw": 0.125}, -20, {"delay": (0.45, 0.75, 0.3)})
    s.synth("lead50", {**sq, "pw": 0.5, "vib": (7, 40, 0.1)}, -20, {})
    s.synth("arp", {"osc": [(PULSE, 0, 1.0)], "pw": 0.5, "amp": (0.001, 0.05, 0.6, 0.01), "cutoff": 16000},
            -26, {})
    s.synth("tri", {"osc": [(TRI, 0, 1.0)], "amp": (0.001, 0.1, 0.9, 0.02), "cutoff": 16000, "glide": 0.02},
            -15, {})

    intro = ["A", "E7"]
    level = ["A", "E/G#", "F#m", "D", "A", "E", "D E", "A"]
    under = ["Bm", "E", "C#m", "F#m", "Bm", "E7"]
    boss = ["F#m", "D", "E", "C#m", "F#m", "D", "B7", "E"]
    prog = intro + level + level + under + boss + ["A", "E"]

    tune = ["E5 . A5 . C#6 . E6 C#6", "B5 . G#5 . E5 - . .", "F#5 . A5 . C#6 . F#6 E6", "D6 - - - A5 - F#5 -",
            "E5 . A5 . C#6 . E6 F#6", "G#6 - E6 - B5 - G#5 -", "F#6 . E6 . D6 . B5 .", "A5 - - - - - . ."]
    under_bass = ["B2 . D3 F#3 B3 . A3 F#3", "E3 . G#3 B3 E4 . D4 B3", "C#3 . E3 G#3 C#4 . B3 G#3",
                  "F#3 . A3 C#4 F#4 . E4 C#4", "B2 . D3 F#3 B3 . D4 F#4", "E4 - D4 - B3 - G#3 -"]
    boss_tune = ["F#5 G#5 A5 C#6 - - A5 - - F#5 - -", "F#5 A5 D6 F#6 - - D6 - - A5 - -",
                 "G#5 B5 E6 G#6 - - E6 - - B5 - -", "G#6 - - E6 - - C#6 - - G#5 - -",
                 "A6 - - F#6 - - C#6 - - A5 - -", "F#6 - - D6 - - A5 - - F#5 - -",
                 "D#6 F#6 A6 B6 - - A6 - - F#6 - -", "G#6 - - - - - E6 - - B5 - -"]

    s.line("lead50", 0, "A5 C#6 E6 A6 - - . .", 100, step=0.25)
    s.line("lead50", 0, ". . . . . . . . E6 - - - . . . .", 100, step=0.25)
    s.line("lead50", 1, "G#5 - B5 - D6 - E6 -", 100)
    for i in range(8):
        s.line("lead25", 2 + i, tune[i], 100, legato=0.85)
        s.line("lead12", 10 + i, tune[i], 100, legato=0.85, octave=1)
        s.line("lead50", 24 + i, boss_tune[i], 100, step=1 / 3, legato=0.9)
    for i in range(6):
        s.line("tri", 18 + i, under_bass[i], 100, legato=0.9)
        s.line("lead12", 18 + i, under_bass[i].split()[0][:-1] + "5 - - - - - - -", 70, legato=0.9)
    s.line("lead25", 32, "E6 C#6 A5 E5 . . . .", 100, legato=0.8)
    s.line("lead25", 33, "B4 C#5 D5 E5 F#5 G#5 A5 B5", 100, legato=0.9)

    for bar, chord in enumerate(prog):
        if not 18 <= bar < 24:
            s.bass("tri", bar, chord, "R . 8 . R . 8 ." if bar < 24 else "R 8 R 8 R 8 R 8", 100)
        # chords as arpeggios in 32nds, the way consoles fake a chord
        if 2 <= bar < 18 or bar >= 24:
            s.arp("arp", bar, chord, [0, 1, 2], 72, 80, step=0.125, legato=0.9)

    for bar in range(34):
        if bar < 2 or bar >= 32:
            s.beat(bar, {"kick": "X.......X.......", "snare": "........x.x.xxxx" if bar % 2 else ""}, "nes")
        elif bar < 18:
            p = {"kick": "X.......X.......", "snare": "....X.......X...", "hat": "x.x.x.x.x.x.x.x."}
            if bar in (2, 10):
                p["crash"] = "X..............."
            if bar % 8 == 1:
                p["snare"] = "....X.......xxxx"
            s.beat(bar, p, "nes")
        elif bar < 24:
            s.beat(bar, {"kick": "X.........X.....", "snare": "........X.......", "hat": "..x...x...x...x."}, "nes")
        else:
            p = {"kick": "X...X...X...X...", "snare": "....X..x....X.x.", "hat": "xxxxxxxxxxxxxxxx"}
            if bar % 4 == 0:
                p["crash"] = "X..............."
            s.beat(bar, p, "nes")
    return s


def gumball():
    """Gumball Gallop: round theme, a G major circus shuffle in 12/8, every beat split in three. The only
    folk band of the soundtrack: accordion, banjo, pizzicato strings, celesta, glockenspiel and a muted
    trumpet, with a kazoo, a slide whistle, a clown horn and a toy drum kit in a small wooden room.
    A rondo: the accordion tune comes back three times between a kazoo song in E minor and a slide
    whistle interlude lifted a minor third, where the drums go straight against the band's triplets."""
    s = Song(150, 40)
    t = 1 / 3
    s.room = (0.8, 0.17, 0.14)
    s.channel(0, 21, 100, 48, level=-18)          # accordion
    s.channel(1, 105, 100, 84, level=-23)         # banjo
    s.channel(2, 45, 100, 36, level=-23)          # pizzicato strings
    s.channel(3, 8, 100, 76, level=-24)           # celesta
    s.channel(4, 59, 100, 58, level=-19)          # muted trumpet
    s.channel(5, 9, 100, 92, level=-25)           # glockenspiel
    s.kit("toy", {
        "kick": (kick(64, punch=14, decay=0.2, click=0.0, drive=0.0), -16, {}),
        "snare": (snare(330, decay=0.08, snap=0.8, tone=0.3, bright=7500), -19, {}),
        "hi": (block(1100, 0.05), -21, {}),
        "lo": (block(760, 0.06), -21, {}),
        "splash": (hat(0.4, bright=6000, metal=1.0), -25, {}),
        "tom": (tom(150, 0.18), -21, {}),
    })
    s.synth("kazoo", {"osc": [(SAW, 0, 1.0), (PULSE, 0, 0.5)], "pw": 0.2, "formant": "uou",
                      "amp": (0.02, 0.2, 0.9, 0.06), "vib": (6.2, 30, 0.15), "glide": 0.04, "drive": 0.9},
            -20, {"hp": 200})
    s.synth("slide", {"osc": [(SINE, 0, 1.0), (TRI, 0, 0.15)], "noise": 0.015, "amp": (0.03, 0.3, 0.9, 0.08),
                      "glide": 0.22, "vib": (6.5, 25, 0.2), "cutoff": 6000}, -21, {"delay": (0.3, 1, 0.35)})
    s.synth("tuba", {"osc": [(SAW, 0, 1.0), (PULSE, 0, 0.4)], "formant": "o", "amp": (0.01, 0.15, 0.6, 0.05),
                     "pitch": (-1, 0.03)}, -17, {})
    s.synth("honk", {"osc": [(PULSE, 0, 1.0)], "pw": 0.35, "formant": "ae", "pitch": (3, 0.06),
                     "amp": (0.004, 0.2, 0.6, 0.06), "drive": 1.5}, -22, {})
    s.lift(24, 31, 3)

    a = ["G", "D/F#", "Em", "C", "G", "D", "C D", "G"]
    b = ["Em", "B7", "Em", "Am D", "G", "C", "Am B7", "Em"]
    c = ["C", "D", "G", "Em", "C", "D", "Am7", "D7"]
    prog = a + b + a + c + a

    tune = ["B4 - D5 G5 - B5 D6 - B5 G5 - D5", "A5 - F#5 D5 - A4 F#5 - . . . .",
            "G5 - E5 B4 - E5 G5 - B5 E6 - .", "C6 - B5 A5 - G5 E5 - . G5 A5 B5",
            "D6 - B5 G5 - B5 D6 - G6 D6 - .", "F#6 - E6 D6 - A5 F#5 - A5 D6 - .",
            "E6 - C6 G5 - C6 F#6 - D6 A5 - F#5", "G5 - - - - - . . . D5 E5 F#5"]
    song = ["E5 - - G5 - - B5 - - E6 - -", "D#6 - - B5 - - F#5 - - A5 - -",
            "G5 - - E5 - - B5 - A5 G5 - -", "A5 - - C6 - - D6 - - F#6 - -",
            "G6 - - D6 - - B5 - - G5 - -", "E6 - - C6 - - G5 - - E5 - -",
            "A5 - - C6 - B5 A5 - - F#5 - D#5", "E5 - - - - - . . . D5 E5 F#5"]
    whistle = ["E5 - - - - - G5 - - - - -", "F#5 - - - - - A5 - - - - -", "B5 - - - - - D6 - - - - -",
               "E6 - - - - - - - - - - -", "G6 - - - - - E6 - - - - -", "F#6 - - - - - D6 - - - - -",
               "C6 - - - - - A5 - - - - -", "D6 - - C6 - - A5 - - F#5 - -"]

    for i in range(8):
        s.line(0, i, tune[i], 96, step=t, legato=0.8)
        s.line(4, 16 + i, tune[i], 98, step=t, legato=0.7, octave=-1)
        s.line(0, 16 + i, tune[i], 70, step=t, legato=0.6)
        s.line("kazoo", 8 + i, song[i], 96, step=t, legato=0.98)
        s.line(3, 8 + i, song[i], 64, step=t, legato=0.5, octave=1)
        s.line("slide", 24 + i, whistle[i], 96, step=t, legato=0.99)
        s.line(0, 24 + i, whistle[i], 64, step=t, legato=0.9, octave=-1)
        s.line(0, 32 + i, tune[i], 100, step=t, legato=0.8)
        s.line("kazoo", 32 + i, tune[i], 90, step=t, legato=0.9, octave=-1)
        s.line(5, 32 + i, tune[i], 80, step=t, legato=0.5)

    for bar, chord in enumerate(prog):
        for start, ch, span in s.spans(bar, chord):
            for beat in range(int(span)):
                for k in voicing(ch, 64):
                    for off in (t, 2 * t):
                        s.note(1, start + beat + off, 0.25, k, 76 if off == t else 66)
        s.bass("tuba", bar, chord, "R . . 5 . . R . . 5 . .", 104, step=t)
        if 8 <= bar < 16 or bar >= 24:
            s.arp(3 if bar < 16 else 5, bar, chord, [0, 1, 2, 3, 2, 1], 76, 70, step=t, legato=0.6)
            s.bass(2, bar, chord, ". 8 . . 8 . . 8 . . 8 .", 84, octave=3, step=t)
        if bar % 8 in (3, 7) and not 24 <= bar < 32:
            s.hits("honk", bar, chord, ". . . . . . . . . 0 . 0", 64, 100, dur=0.25, step=t)
    s.line("slide", 23, ". . . . . . G4 - - G6 - -", 96, step=t, legato=0.99)

    for bar in range(40):
        if 24 <= bar < 32:
            # two against three: straight sixteenths under the triplet band
            p = {"kick": "X...X...X...X...", "snare": "....X.......X...", "hi": "x.xxx.xxx.xxx.xx"}
            if bar == 24:
                p["splash"] = "X..............."
            s.beat(bar, p, "toy")
            continue
        gallop = bar >= 32 or 8 <= bar < 16
        p = {"kick": "X..x..X..x.." if gallop else "X.....x..x..", "snare": "...X.....X..",
             "hi": "x.xx.xx.xx.x", "lo": "..x..x..x..x" if gallop else ""}
        if bar % 8 == 7:
            p.update(snare="......xxxXXX", tom="......x..x..")
        if bar % 8 == 0:
            p["splash"] = "X..........."
        s.beat(bar, p, "toy", step=t)
    return s


def sugar():
    """Sugar Rush: round theme in the lo-fi electronica corner, sung by the jelly bean singers. No
    soundfont: an 808 style kit with hat rolls, a sub bass that glides, FM bells and marimba, vocal
    chord stabs and a breathy pad, slightly crushed. Shaped like a pop song: intro, an A minor verse on
    breaks, a stop time pre chorus where only the singers keep going, a C major chorus, a six bar half
    time bridge in Eb, the chorus a minor third up, and a turnaround back to A minor."""
    s = Song(150, 40)
    s.room = (1.4, 0.32, 0.2)
    s.color = [("crush", 12, 32000), ("lowpass", 12500)]
    s.kit("808", {
        "kick": (kick(46, punch=14, decay=0.55, click=0.02, drive=0.8), -14, {}),
        "snare": (snare(240, decay=0.13, snap=1.1, tone=0.4, bright=7000), -18, {}),
        "clap": (clap(0.18, 1100), -19, {}),
        "hat": (hat(0.025, bright=9000, metal=0.5), -25, {}),
        "ohat": (hat(0.18, bright=8000, metal=0.6), -26, {}),
    })
    vowel = {"osc": [(PULSE, 0, 1.0), (SAW, 0, 0.6)], "pw": 0.3, "formant": "ia", "amp": (0.003, 0.1, 0.7, 0.05),
             "pitch": (-1.5, 0.03), "vib": (6, 15, 0.08), "drive": 0.3}
    s.synth("voice", vowel, -18, {"delay": (0.22, 0.75, 0.3), "hp": 220})
    s.synth("harm", {**vowel, "formant": "ua"}, -23, {"hp": 220, "width": 1.4})
    s.synth("stab", {**vowel, "formant": "a", "unison": 3, "detune": 18, "spread": 0.9,
                     "amp": (0.004, 0.25, 0.0, 0.1)}, -21, {"hp": 250})
    s.synth("sub", {"osc": [(SINE, 0, 1.0), (TRI, 0, 0.2)], "amp": (0.003, 0.4, 0.85, 0.06), "glide": 0.06,
                    "cutoff": 2000, "drive": 0.5}, -15, {"sidechain": (0.3, 0.3)})
    s.synth("bell", {"osc": [], "fm": (3.5, 2.8, 0.5), "amp": (0.001, 1.0, 0.0, 0.35), "cutoff": 9000},
            -21, {"delay": (0.3, 0.75, 0.35), "hp": 300})
    s.synth("mallet", {"osc": [], "fm": (4.0, 1.6, 0.06), "amp": (0.001, 0.25, 0.0, 0.1), "cutoff": 7000},
            -22, {"hp": 200})
    s.synth("pad", {"osc": [(SAW, 0, 1.0)], "unison": 4, "detune": 20, "spread": 1.0, "noise": 0.08,
                    "amp": (0.3, 1.0, 0.85, 0.5), "cutoff": 1400, "res": 0.8, "lfo": (24, 2.2, 96)},
            -24, {"sidechain": (0.55, 0.35), "hp": 160, "chorus": (0.5, 4, 8)})
    s.synth("rise", riser(8 * 60 / 150), -25, {"hp": 200})
    s.lift(30, 37, 3)

    intro = ["Am", "F", "G", "E7"]
    verse = ["Am", "F", "G", "Em", "Am", "F", "G", "Em"]
    pre = ["Dm", "Em", "F", "G7"]
    chorus = ["F", "G", "Em", "Am", "F", "G", "C", "C"]
    bridge = ["Ab", "Bb", "Gm", "Cm", "Ab", "Bb"]
    prog = intro + verse + pre + chorus + bridge + chorus + ["F", "E7"]

    verse_mel = ["A4 . C5 . E5 . D5 C5", "C5 - A4 - . . F4 A4", "B4 . D5 . G5 . F5 E5", "E5 - - - . . . .",
                 "A4 . C5 . E5 . A5 G5", "F5 - E5 - C5 - A4 C5", "D5 . B4 . G4 . B4 D5", "E5 - - - . . E5 F5"]
    pre_mel = ["F5 - - - . . . .", "G5 - - - . . . .", "A5 - - - . . . .", "B5 - - - D6 - F6 -"]
    hook = ["C6 . A5 . C6 . D6 C6", "B5 - G5 - D5 . G5 B5", "B5 . G5 . B5 . E6 D6", "C6 - A5 - E5 . A5 C6",
            "F6 . E6 . D6 . C6 A5", "B5 . C6 . D6 . G6 -", "E6 - - - D6 - C6 -", "C6 - - - . . G5 A5"]
    counter = ["A6 - - - - - - -", "B6 - - - - - - -", "G6 - - - B6 - - -", "A6 - - - C7 - - -",
               "A6 - - - - - - -", "D7 - - - B6 - - -", "G6 - - - - - - -", "E6 - - - G6 - C7 -"]
    bridge_mel = ["C6 - - - Eb6 - - -", "D6 - - - F6 - - -", "D6 - Bb5 - G5 - - -", "Eb6 - - - G6 - - -",
                  "F6 - Eb6 - C6 - Ab5 -", "D6 - - - F6 - Bb5 -"]

    for i in range(4):
        s.hits("voice", i, intro[i], "0.0.2.0. 3.2.0...", 72, 88, dur=0.18)
    for i, mel in enumerate(verse_mel):
        s.line("voice", 4 + i, mel, 98, legato=0.7)
    for i, mel in enumerate(pre_mel):
        s.line("voice", 12 + i, mel, 100, legato=0.95)
        s.line("harm", 12 + i, mel, 86, legato=0.95, octave=-1)
    for i, mel in enumerate(hook):
        for bar in (16 + i, 30 + i):
            s.line("voice", bar, mel, 100, legato=0.7)
            s.line("harm", bar, mel, 80, legato=0.7, octave=-1)
            s.line("mallet", bar, mel, 76, legato=0.5)
        s.line("bell", 30 + i, counter[i], 90, legato=0.8)
    for i, mel in enumerate(bridge_mel):
        s.line("bell", 24 + i, mel, 96, legato=0.9)
        s.line("voice", 24 + i, mel, 70, legato=0.98, octave=-1)
    s.line("voice", 38, "A5 - G5 - F5 - E5 -", 96, legato=0.9)
    s.line("voice", 39, "G#5 - - - B5 - D6 -", 100, legato=0.9)

    for bar, chord in enumerate(prog):
        if bar < 4:
            s.bass("sub", bar, chord, "R - - R - - 8 -", 96)
        elif bar < 12:
            s.bass("sub", bar, chord, "R - - R . . 5 8", 104)
            s.arp("mallet", bar, chord, [0, 2, 1, 2], 72, 70, step=0.5, legato=0.5)
            if bar % 2 == 1:
                s.hits("harm", bar, chord, "........ ....2.3.", 74, 86, dur=0.15)
        elif bar < 16:
            s.bass("sub", bar, chord, "R . . R . . . .", 110)
            s.chords("stab", bar, chord, [0, 3], 0.3, 66, 110)
        elif bar < 24 or 30 <= bar < 38:
            s.bass("sub", bar, chord, "R - - R - R 8 -", 108)
            s.chords("stab", bar, chord, [1, 3, 5, 7] if bar % 2 else [1, 3, 6], 0.2, 67, 92)
            s.pad("pad", bar, chord, 60, 90)
        elif bar < 30:
            s.pad("pad", bar, chord, 64, 100)
            s.bass("sub", bar, chord, "R - - - - - 5 -", 100)
        else:
            s.chords("stab", bar, chord, [0, 3, 6], 0.3, 64, 104)
            s.bass("sub", bar, chord, "R R R R R R R R", 104)
    s.note("rise", 14 * 4, 8, 60, 120)
    s.note("rise", 28 * 4, 8, 60, 120)

    for bar in range(40):
        if bar < 4:
            s.beat(bar, {"kick": "X.........X.....", "hat": "x.x.x.x.x.x.xxxx" if bar == 3 else "x.x.x.x.x.x.x.x."}, "808")
        elif bar < 12:
            p = {"kick": "X.X.......X..X..", "snare": "....X..o.o..X..o", "hat": "x.x.x.x.x.x.x.x."}
            if bar % 2:
                p.update(kick="X.........XX....", hat="x.x.x.x.x.x.xxxx")
            s.beat(bar, p, "808")
        elif bar < 16:
            p = {"kick": "X.....X.........", "clap": "....X.......X..."}
            if bar == 15:
                p["snare"] = "x.x.x.x.xxxxXXXX"
            s.beat(bar, p, "808")
        elif bar < 24 or 30 <= bar < 38:
            p = {"kick": "X...X...X...X...", "clap": "....X.......X...", "hat": "x.x.x.x.x.x.x.x.",
                 "ohat": "..x...x...x...x."}
            if bar % 4 == 3:
                p["hat"] = "x.x.x.x.x.xxxxxx"
            s.beat(bar, p, "808")
        elif bar < 30:
            s.beat(bar, {"kick": "X.........X.....", "clap": "........X.......", "hat": "x.xxx.xxx.xxx.xx"}, "808")
        else:
            s.beat(bar, {"kick": "X...X...X...X...", "snare": "....x.x.xxxxXXXX"}, "808")
    return s


def victory():
    """Round winner fanfare in the same funk palette as the round theme."""
    s = Song(120, 3)
    s.channel(0, 80, 100, 40, level=-18)
    s.channel(1, 9, 100, 88, level=-20)
    s.channel(2, 61, 100, 64, level=-15)
    s.channel(4, 39, 100, 64, level=-18)
    s.channel(6, 55, 100, 64, level=-19)
    s.channel(9, 0, 100, 64, drums=True, level=-16)
    for j, k in enumerate(["G4", "B4", "D5"]):
        for ch in (0, 2):
            s.note(ch, j / 3, 0.28, midi(k), 98)
    hits = [(1, "G", 0.5), (2, "G", 0.25), (2.5, "C", 0.4), (3.5, "D", 0.4), (4.5, "G", 3.5)]
    for start, chord, dur in hits:
        for k in voicing(chord, 64):
            s.note(2, start, dur, k, 110)
        s.note(4, start, dur, bass_root(chord, 2), 108)
    for j, k in enumerate(["G5", "B5", "D6", "G6"]):
        s.note(1, 4.5 + j * 0.1, 2, midi(k), 92)
        s.note(0, 4.5 + j * 0.1, 0.4, midi(k) - 12, 80)
    for k in voicing("G", 60):
        s.note(6, 4.5, 1, k, 100)
    for j in range(8):
        s.note(9, j * 0.125, 0.1, DRUM["snare"], 60 + j * 7)
    for beat in (1, 4.5):
        s.note(9, beat, 1, DRUM["crash"], 120)
        s.note(9, beat, 0.5, DRUM["kick"], 120)
    for beat in (2, 2.5, 3.5):
        s.note(9, beat, 0.2, DRUM["clap"], 100)
    return s


def placeholder_sections(song):
    # stand in parts cut from a song written before sections existed, until it is rebuilt with its own
    n = song.bars
    song.sections = {"intro": (0, 2), "loop": (0, n), "switch": (n - 1, n), "final": (n - 8, n)}
    return song


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: compose.py GeneralUser-GS.sf2 MuseScore_General.sf2")
    gugs, msg = sys.argv[1:]
    tracks = {}
    for name, make, sf in [("menu", menu, msg), ("jam", jam, msg), ("wobble", wobble, msg),
                           ("gumball", gumball, msg), ("sugar", sugar, msg), ("victory", victory, gugs)]:
        # seeded per track so changing one track leaves the others' humanizing alone
        random.seed(name)
        song = make()
        if name == "victory":
            tracks[name] = render_once(song, sf, name)
        elif name == "menu":
            tracks[name] = render_loop(song, sf, name)
        else:
            if not song.sections:
                placeholder_sections(song)
            tracks[name] = render_sections(song, sf, name)
    (OUT / "tracks.json").write_text(json.dumps(tracks, indent=2) + "\n")
    for name, t in tracks.items():
        print(name, t)


if __name__ == "__main__":
    main()
