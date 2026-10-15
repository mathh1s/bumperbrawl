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

    def note(self, ch, beat, dur, key, vel):
        if ch != 9:
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
            stems.append((stem, song.levels[ch]))
    else:
        part = copy.copy(song)
        part.events = [e for e in song.events if e[2] in song.channels]
        stem, loop_samples = render_dry(part, soundfont, repeats, tail)
        stems.append((stem, song.sf_level))
    total = len(stems[0][0])
    for name, (patch, fx) in song.synths.items():
        events = [(b, d, k, v) for b, d, ch, k, v in song.events if ch == name]
        stems.append((render_part(events, patch, fx, song.bpm, loop_samples, repeats, total), song.levels[name]))
    dry = None
    for stem, level in stems:
        if level is not None:
            stem = stem * 10 ** ((level - active_rms_db(stem)) / 20)
        dry = stem if dry is None else dry + stem
    ir = reverb_ir()
    wet = np.stack([oaconvolve(dry[:, c], ir[:, c])[: len(dry)] for c in range(2)], axis=1)
    return dry + wet * 0.22, loop_samples


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


def render_once(song, soundfont, name):
    audio, _ = render(song, soundfont, repeats=1, tail=2.5)
    # one-shots end on a sharp hit that overshoots after mp3 encoding, so they sit a little lower
    encode(master(audio, 0.1) * 0.85, name)
    return {"file": f"music/{name}.mp3"}


# ==== synth patches ====

SUPERSAW = {"osc": [(SAW, 0, 1.0)], "unison": 7, "detune": 38, "spread": 0.9, "amp": (0.003, 0.2, 0.3, 0.12),
            "filt": (0.001, 0.16, 0.15, 0.1), "cutoff": 900, "env_oct": 2.6, "res": 0.9}
DISCO_BASS = {"osc": [(SAW, 0, 1.0), (PULSE, 0, 0.5)], "sub": 0.7, "amp": (0.002, 0.25, 0.55, 0.04),
              "filt": (0.001, 0.11, 0.0, 0.05), "cutoff": 220, "env_oct": 2.8, "res": 1.6, "drive": 0.6}
SPARKLE = {"osc": [(SAW, 0, 0.6), (PULSE, 12, 0.4)], "amp": (0.001, 0.14, 0.0, 0.08),
           "filt": (0.001, 0.07, 0.0, 0.05), "cutoff": 1400, "env_oct": 2.4, "res": 2.6, "keytrack": 0.5}
SWEEP_PAD = {"osc": [(SAW, 0, 1.0), (SAW, 12, 0.3)], "unison": 5, "detune": 24, "spread": 1.0,
             "amp": (0.35, 1.0, 0.9, 0.5), "cutoff": 5200, "res": 1.8}
TALKBOX = {"osc": [(SAW, 0, 1.0), (PULSE, 0, 0.5)], "unison": 2, "detune": 9, "spread": 0.3, "formant": "oa",
           "amp": (0.012, 0.3, 0.85, 0.09), "glide": 0.055, "vib": (5.6, 22, 0.3), "drive": 0.4}
JUNO = {"osc": [(SAW, 0, 0.8), (PULSE, -12, 0.5)], "pwm": 0.2, "pwm_rate": 0.35, "amp": (0.22, 0.9, 0.75, 0.45),
        "cutoff": 1500, "keytrack": 0.4, "res": 0.8, "filt": (0.3, 1.2, 0.4, 0.4), "env_oct": 0.8}
BUBBLE = {"osc": [(SINE, 0, 1.0), (TRI, 12, 0.35)], "amp": (0.001, 0.16, 0.0, 0.1), "pitch": (9, 0.025),
          "cutoff": 6000}
CHIP = {"osc": [(PULSE, 0, 1.0)], "pw": 0.25, "pwm": 0.12, "pwm_rate": 0.4, "amp": (0.001, 0.08, 0.55, 0.02),
        "cutoff": 9000, "velsens": 0.4}
CHIP_LEAD = {"osc": [(PULSE, 0, 1.0)], "pw": 0.125, "amp": (0.002, 0.1, 0.7, 0.04), "cutoff": 8000,
             "vib": (6.5, 18, 0.12), "glide": 0.03}
BOING = {"osc": [(SINE, 0, 1.0), (TRI, 0, 0.5)], "amp": (0.001, 0.25, 0.0, 0.15), "pitch": (-14, 0.06),
         "vib": (14, 60, 0.04), "cutoff": 5000}
ACID = {"osc": [(SAW, 0, 1.0)], "amp": (0.002, 0.2, 0.7, 0.03), "filt": (0.001, 0.15, 0.0, 0.05),
        "cutoff": 260, "env_oct": 3.6, "res": 5.5, "drive": 1.6, "glide": 0.045, "velsens": 0.5}
GATE_SAW = {**SUPERSAW, "amp": (0.002, 0.09, 0.0, 0.03), "cutoff": 1600, "env_oct": 1.6}

# the jelly bean singers: short nonsense syllables, a closed vowel opening up on every note
CHOP = {"osc": [(PULSE, 0, 1.0), (SAW, 0, 0.6)], "pw": 0.3, "formant": "ua", "amp": (0.003, 0.1, 0.7, 0.05),
        "pitch": (-1.5, 0.03), "vib": (6, 15, 0.08), "drive": 0.3}
CHOP_YA = {**CHOP, "formant": "ia"}
SQUEAK = {"osc": [(SINE, 0, 1.0), (TRI, 0, 0.3)], "amp": (0.004, 0.18, 0.4, 0.05), "pitch": (-6, 0.09),
          "vib": (19, 70, 0.02), "cutoff": 7000}
LEAD_SAW = {"osc": [(SAW, 0, 1.0), (SAW, 12, 0.25)], "unison": 5, "detune": 22, "spread": 0.7,
            "amp": (0.004, 0.3, 0.8, 0.1), "cutoff": 3200, "keytrack": 0.3, "res": 1.0, "glide": 0.035,
            "vib": (5.8, 20, 0.25), "filt": (0.001, 0.2, 0.3, 0.1), "env_oct": 0.8}
SUB_DROP = {"osc": [(SINE, 0, 1.0)], "amp": (0.002, 1.2, 0.0, 0.3), "pitch": (24, 0.18), "cutoff": 3000,
            "drive": 0.5}
FAT_PAD = {"osc": [(SAW, 0, 1.0), (SAW, 7, 0.4)], "unison": 6, "detune": 28, "spread": 1.0,
           "amp": (0.15, 1.0, 0.85, 0.4), "cutoff": 2400, "res": 0.9}

KAZOO = {"osc": [(SAW, 0, 1.0), (PULSE, 0, 0.5)], "pw": 0.2, "formant": "uou", "amp": (0.02, 0.2, 0.9, 0.06),
         "vib": (6.2, 30, 0.15), "glide": 0.04, "drive": 0.9}
SLIDE_WHISTLE = {"osc": [(SINE, 0, 1.0), (TRI, 0, 0.15)], "noise": 0.015, "amp": (0.03, 0.3, 0.9, 0.08),
                 "glide": 0.22, "vib": (6.5, 25, 0.2), "cutoff": 6000}
BOUNCE_BASS = {"osc": [(SINE, 0, 1.0), (TRI, 0, 0.6), (SAW, 0, 0.25)], "amp": (0.002, 0.18, 0.5, 0.04),
               "pitch": (5, 0.02), "cutoff": 900, "filt": (0.001, 0.08, 0.0, 0.05), "env_oct": 1.5, "res": 1.2,
               "drive": 0.4}


def wobble_bass(period):
    return {"osc": [(SAW, 0, 1.0), (SAW, -12, 0.6)], "sub": 0.6, "amp": (0.004, 0.3, 0.9, 0.05),
            "cutoff": 2200, "lfo": (period, 3.6, 0), "res": 2.4, "drive": 1.2}


def riser(seconds):
    return {"osc": [], "noise": 0.6, "amp": (seconds * 0.9, 1, 1, 0.08), "filt": (seconds, 1, 1, 0.1),
            "cutoff": 250, "env_oct": 5, "res": 2.0, "mode": 1}


# ==== tracks ====

DRUMS = {
    # four on the floor with busy sixteenth hats, the party default
    "four": {"kick": "X...X...X...X...", "clap": "....X.......X...", "snare": "......o.......o.",
             "hat": "xoxxxoxxxoxxxoxx", "ohat": "..x...x...x...x."},
    # jungle style breaks, two bars that alternate
    "break": {"kick": "X.X.......X..X..", "snare": "....X..o.o..X..o", "hat": "x.x.x.x.x.x.x.x.",
              "tamb": "..o...o...o...o."},
    "break2": {"kick": "X.........XX....", "snare": "....X..o.o.oX.o.", "hat": "x.x.x.x.x.x.x.x.",
               "tamb": "..o...o...o...o."},
    # happy hardcore: the kick on every beat, open hats on the offbeats, breaks ghosting underneath
    "hardcore": {"kick": "X...X...X...X...", "clap": "....X.......X...", "snare": "..o....o.o....o.",
                 "ohat": "..X...X...X...X.", "hat": "x.x.x.x.x.x.x.x."},
    "half": {"kick": "X.........X.....", "clap": "........X.......", "shaker": "oxoxoxoxoxoxoxox"},
    "ska": {"kick": "X.......X.......", "snare": "....X.......X...", "hat": "..x...x...x...x.",
            "shaker": "oxoxoxoxoxoxoxox"},
}
FILL = {"snare": "........x.xxXXXX", "htom": "........x.......", "mtom": "..........x.....", "ltom": "............x..."}


def groove(s, bar, style, fill=False, crash=False, extra=None):
    p = dict(DRUMS[style])
    if fill:
        p.update(FILL)
        p["hat"] = p.get("hat", "")[:8].ljust(16, ".")
    if crash:
        p["crash"] = "X..............."
    p.update(extra or {})
    s.drums(bar, p)


def jam():
    """Jelly Jam: round theme, C major disco house at full tilt. MuseScore General plays the band,
    the synths the club: pumping supersaws, a filtered octave bass, an arp, jelly bean vocal chops
    and toy squeaks. The last eight bars jump up a whole step, Eurovision style, then a turnaround
    bar walks back home for the loop."""
    s = Song(140, 40)
    s.channel(0, 13, 100, 44, level=-20)          # xylophone hook
    s.channel(1, 12, 100, 84, level=-22)          # marimba doubling an octave down
    s.channel(2, 56, 100, 58, level=-18)          # trumpet lead
    s.channel(3, 61, 100, 70, bank=8, level=-19)  # horn section stabs
    s.channel(4, 28, 100, 30, bank=8, level=-25)  # funk guitar chops
    s.channel(5, 36, 100, 64, level=-19)          # slap bass
    s.channel(6, 0, 100, 96, level=-23)           # piano stabs
    s.channel(7, 57, 100, 40, level=-21)          # trombone under the trumpet
    s.channel(9, 8, 100, 64, drums=True, level=-13)
    s.synth("saw", SUPERSAW, -20, {"sidechain": (0.7, 0.35), "hp": 180, "width": 1.3})
    s.synth("disco", DISCO_BASS, -17, {"sidechain": (0.4, 0.3)})
    s.synth("spark", SPARKLE, -24, {"delay": (0.35, 0.75, 0.4), "hp": 300})
    s.synth("lead", LEAD_SAW, -21, {"delay": (0.22, 0.75, 0.3), "hp": 250})
    s.synth("sweep", {**SWEEP_PAD, "lfo": (32, 3.4, 96)}, -21, {"chorus": (0.5, 4, 8), "hp": 150})
    s.synth("chop", CHOP, -21, {"delay": (0.25, 0.5, 0.3), "hp": 250})
    s.synth("squeak", SQUEAK, -25, {"delay": (0.2, 0.75, 0.3)})
    s.synth("rise", riser(8 * 60 / 140), -26, {"hp": 200})
    s.synth("drop", SUB_DROP, -20, {})
    s.lift(32, 38, 2)

    a = ["C", "Am7", "Dm7", "G7", "C", "Am7", "Dm7 G7", "C"]
    b = ["F", "G", "Em7", "Am7", "Dm7", "G", "E7", "Am7 G7"]
    c = ["Am7", "F", "Dm7", "G", "F", "G", "Ab", "G7"]
    prog = a + a + b + c + a[:7] + ["G7"]

    hook = ["E5 . G5 . C6 . G5 A5", "G5 . E5 . C5 - . .", "F5 . A5 . D6 . C6 A5", "B5 - G5 - . F5 E5 D5",
            "E5 . G5 . C6 . E6 .", "D6 . C6 . A5 . G5 .", "F5 A5 D6 . B5 . G5 .", "C6 - - - . G5 A5 B5"]
    verse = ["A5 - - C6 - - A5 -", "B5 - - D6 - - B5 -", "G5 . G5 . B5 . E6 -", "C6 - - - . . . .",
             "A5 - - D6 - - F6 -", "D6 - - B5 - - G5 -", "G#5 . B5 . D6 . E6 -", "C6 - - - B5 - - -"]
    breakdown = ["A5 . E5 . A5 . C6 .", "A5 . F5 . C5 . F5 .", "D5 . F5 . A5 . D6 .", "B5 . G5 . D5 . G5 ."]
    build = ["C5 - - - F5 - - -", "D5 - - - G5 - - -", "Eb5 - - - Ab5 - - -", "B5 - - - D6 - F6 -"]

    for i, mel in enumerate(hook):
        s.line(0, i, mel, 92, legato=0.5)
        s.line(1, i, mel, 80, legato=0.6, octave=-1)
        # second time round the trumpet takes the hook and the mallets answer softly
        s.line(2, 8 + i, mel, 96, legato=0.55, octave=-1)
        s.line(0, 8 + i, mel, 60, legato=0.5)
        # the lifted climax: synth lead and trumpet together, an octave apart
        if i < 7:
            s.line("lead", 32 + i, mel, 100, legato=0.9, octave=-1)
            s.line(2, 32 + i, mel, 92, legato=0.55, octave=-1)
            s.line(0, 32 + i, mel, 70, legato=0.5)
    for i, mel in enumerate(verse):
        s.line(2, 16 + i, mel, 100, legato=0.85, octave=-1)
        s.line(7, 16 + i, mel, 86, legato=0.85, octave=-2)
        s.line(0, 16 + i, mel, 58, legato=0.4)
    for i, mel in enumerate(breakdown):
        s.line(1, 24 + i, mel, 86, legato=0.5)
        s.line("chop", 24 + i, mel, 90, legato=0.5)
    for i, mel in enumerate(build):
        s.line(2, 28 + i, mel, 98, legato=0.8, octave=-1)
        s.line(7, 28 + i, mel, 90, legato=0.8, octave=-2)
    s.line(0, 31, "G5 A5 B5 C6 D6 E6 F6 G6", 84, legato=0.6)
    s.line("lead", 39, "G4 . B4 . D5 . F5 G5", 96, legato=0.8)

    for bar, chord in enumerate(prog):
        full = bar < 24 or bar >= 32
        if 8 <= bar < 24 or bar >= 28:
            s.chords("saw", bar, chord, [1, 3, 5, 7], 0.22, 67, 96)
        if 16 <= bar < 24 or bar >= 28:
            s.arp("spark", bar, chord, [0, 2, 4, 2, 1, 3, 5, 3], 74, 82)
        if 24 <= bar < 28:
            s.pad("sweep", bar, chord, 64, 100)
            s.bass(5, bar, chord, "R - - - . . 5 8", 98)
        if full:
            s.bass("disco", bar, chord, "R 8 R 8 R 8 R 8", 108)
            s.bass(5, bar, chord, "R . 8 R . R 8 .", 104)
            s.chords(4, bar, chord, [1, 3, 5, 7], 0.12, 64, 76)
            s.chords(6, bar, chord, [1, 3, 5, 7], 0.2, 72, 86)
            # horn stabs answer the melody on the and of 2 and on 4
            if bar % 2 == 1 or bar >= 16:
                s.chords(3, bar, chord, [3, 6], 0.25, 64, 98)
        if bar >= 28 and bar < 32:
            s.bass("disco", bar, chord, "R 8 R 8 R 8 R 8", 112)
            s.chords(3, bar, chord, [0, 3, 6], 0.3, 64, 102)
        # the singers answer the hook at the end of every other bar
        if bar % 2 == 1 and full:
            s.hits("chop", bar, chord, "........ 2.3.4.3.", 72, 92, dur=0.18)
        if bar % 8 == 5:
            s.note("squeak", bar * 4 + 3.5, 0.4, midi("G6"), 100)
    s.note("rise", 30 * 4, 8, 60, 120)
    s.note("drop", 32 * 4, 4, midi("C1"), 120)
    s.note("drop", 0, 4, midi("C1"), 110)

    for bar in range(40):
        fill = bar % 8 == 7
        crash = bar % 8 == 0
        if bar < 8:
            groove(s, bar, "four", fill, crash)
        elif bar < 16:
            groove(s, bar, "four", fill, crash, {"tamb": "..o...o...o...o.", "cowbell": "..x...x...x...x." if bar % 4 == 3 else ""})
        elif bar < 24:
            groove(s, bar, "break" if bar % 2 == 0 else "break2", fill, crash, {"kick": "X...X...X...X..."})
        elif bar < 28:
            groove(s, bar, "half", False, crash)
        elif bar < 31:
            groove(s, bar, "four", False, crash, {"snare": "x.x.x.x.x.x.x.x."})
        elif bar == 31:
            groove(s, bar, "four", False, False, {"snare": "xxxxxxxxxxxxXXXX"})
        else:
            groove(s, bar, "hardcore", fill, crash, {"tamb": "oxoxoxoxoxoxoxox"})
    return s


def wobble():
    """Wobble Run: round theme, F major ska punk at a sprint, oompah tuba and a trumpet and trombone
    pair crossed with an 8 bit console: pulse wave arps and lead, chops, boings, and a wobble bass
    bridge. The second tune goes up a semitone and the bridge drops back home."""
    s = Song(164, 32)
    s.channel(0, 56, 100, 52, level=-17)          # trumpet lead
    s.channel(1, 57, 100, 76, level=-21)          # trombone, melody an octave down
    s.channel(2, 13, 100, 40, level=-20)          # xylophone runs
    s.channel(3, 58, 100, 64, level=-16)          # tuba bass
    s.channel(4, 27, 100, 92, level=-23)          # clean guitar skank
    s.channel(5, 17, 100, 36, level=-25)          # percussive organ skank
    s.channel(6, 115, 100, 64, bank=1, level=-24)  # temple blocks
    s.channel(7, 61, 100, 64, level=-20)          # brass pads in the bridge
    s.channel(9, 0, 100, 64, drums=True, level=-13)
    s.synth("chip", CHIP, -25, {"hp": 250, "width": 1.2})
    s.synth("lead", CHIP_LEAD, -22, {"delay": (0.4, 0.75, 0.35), "hp": 300})
    s.synth("wob", wobble_bass(1), -17, {"hp": 35})
    s.synth("wob2", wobble_bass(0.5), -17, {"hp": 35})
    s.synth("boing", BOING, -22, {"delay": (0.25, 0.5, 0.3)})
    s.synth("chop", CHOP_YA, -21, {"delay": (0.25, 0.75, 0.3), "hp": 250})
    s.synth("rise", riser(8 * 60 / 164), -26, {"hp": 200})
    s.lift(16, 23, 1)

    a = ["F", "C7", "F", "Bb", "F", "C7", "Bb C7", "F"]
    b = ["Dm", "A7", "Dm", "Gm C7", "F", "D7", "Gm C7", "F"]
    c = ["Bb", "F", "C7", "F", "Bb", "F", "G7", "C7"]
    prog = a + b + a + c

    tune = ["C5 . F5 . A5 . F5 .", "G5 . E5 . C5 - . .", "A5 . C6 . A5 . F5 .", "D6 - - - Bb5 - . .",
            "C6 . A5 . F5 . A5 .", "Bb5 . G5 . E5 . G5 .", "D6 . Bb5 . E5 . G5 .", "F5 - - - . . C5 E5"]
    runs = ["D5 F5 A5 D6 . A5 F5 D5", "C#5 E5 A5 C#6 . A5 E5 C#5", "D5 F5 A5 D6 F6 - D6 .", "D6 . Bb5 . C6 . E5 .",
            "F5 A5 C6 F6 . C6 A5 F5", "F#5 A5 C6 D6 . C6 A5 F#5", "G5 Bb5 D6 G6 . E6 C6 Bb5", "A5 - F5 - C5 - . ."]
    bridge = ["D6 - - - F6 - - -", "C6 - - - A5 - - -", "Bb5 - - - G5 - - -", "A5 - - - C6 - - -",
              "D6 - - - F6 - - -", "C6 - - - A5 - - -", "B5 - - - D6 - - -", "E6 - - - G6 - - -"]

    for i, mel in enumerate(tune):
        s.line(0, i, mel, 96, legato=0.5)
        s.line(0, 16 + i, mel, 100, legato=0.5)
        s.line(1, 16 + i, mel, 90, legato=0.5, octave=-1)
        s.line("lead", 16 + i, mel, 96, legato=0.7, octave=1)
    for i, mel in enumerate(runs):
        s.line(2, 8 + i, mel, 92, legato=0.5)
        s.line(1, 8 + i, mel.split()[0] + " - - - . . . .", 80, octave=-1)
    for i, mel in enumerate(bridge):
        s.line(0, 24 + i, mel, 92, legato=0.9, octave=-1)
        s.line(2, 24 + i, mel, 70, legato=0.3)
        s.line("chop", 24 + i, mel, 84, legato=0.4)
    s.line(2, 31, "C5 E5 G5 Bb5 C6 E6 G6 Bb6", 86, legato=0.6)

    for bar, chord in enumerate(prog):
        # oompah: tuba on the beats, the band on the offbeats
        s.bass(3, bar, chord, "R . 5 . R . 5 .", 104, octave=1)
        s.chords(4, bar, chord, [1, 3, 5, 7], 0.18, 62, 82)
        s.chords(5, bar, chord, [1, 3, 5, 7], 0.18, 70, 64)
        if bar % 4 == 3:
            s.line(6, bar, ". . . . D4 D4 C4 Bb3", 90, legato=0.5)
        if bar < 24:
            s.arp("chip", bar, chord, [0, 1, 2, 3, 2, 1] if bar < 16 else [0, 2, 1, 3, 2, 4], 72, 86)
            if bar % 2 == 1:
                s.hits("chop", bar, chord, "........ ..2.3.4.", 72, 90, dur=0.16)
        else:
            # the bridge drops the skank feel into a wobble, twice as fast in its second half
            for start, ch, span in s.spans(bar, chord):
                s.note("wob" if bar < 28 else "wob2", start, span * 0.98, bass_root(ch, 2), 104)
                for k in voicing(ch, 62):
                    s.note(7, start, span * 0.95, k, 76)
        if bar % 4 == 1:
            s.note("boing", bar * 4 + 3.5, 0.4, midi("F5"), 104)
    s.note("rise", 30 * 4, 8, 60, 120)

    for bar in range(32):
        fill = bar % 8 == 7
        crash = bar % 8 == 0
        if bar < 8:
            groove(s, bar, "ska", fill, crash, {"kick": "X...X...X...X..."})
        elif bar < 16:
            groove(s, bar, "break" if bar % 2 == 0 else "break2", fill, crash)
        elif bar < 24:
            groove(s, bar, "hardcore", fill, crash)
        else:
            groove(s, bar, "four", fill, crash, {"ride": "x.x.x.x.x.x.x.x.", "hat": "................"})
    return s


def menu():
    """Blob Lounge: menu and between rounds, F major slap funk at a bounce, sung by a talk box lead
    over a chorused poly pad, with jelly bean chops, toy squeaks and a lift up a semitone for the
    last eight bars that slides back home into the loop."""
    s = Song(126, 24)
    s.channel(1, 11, 100, 82, level=-22)    # vibraphone doubling
    s.channel(2, 36, 100, 64, level=-17)    # slap bass
    s.channel(3, 4, 100, 38, level=-24)     # electric piano
    s.channel(4, 7, 100, 92, level=-24)     # clavinet
    s.channel(5, 62, 100, 64, level=-20)    # synth brass
    s.channel(9, 0, 100, 64, drums=True, level=-15)
    s.synth("talk", TALKBOX, -18, {"hp": 200, "delay": (0.18, 0.75, 0.3)})
    s.synth("juno", JUNO, -25, {"chorus": (0.6, 5, 8), "hp": 160, "sidechain": (0.35, 0.3)})
    s.synth("bub", BUBBLE, -26, {"delay": (0.35, 0.75, 0.4)})
    s.synth("chop", CHOP, -22, {"delay": (0.25, 0.75, 0.3), "hp": 250})
    s.synth("squeak", SQUEAK, -25, {"delay": (0.2, 0.75, 0.3)})
    s.lift(16, 23, 1)

    prog = ["Fmaj7", "Em7 A7", "Dm7", "G7 C7", "Fmaj7", "Em7 A7", "Dm7 G7", "C7sus C7",
            "Bbmaj7", "Am7", "Gm7", "C7", "Bbmaj7", "Am7 D7", "Gm7 C7", "Fmaj7"]
    melody = ["A5 . C6 . A5 G5 F5 .", "E5 . G5 . A5 - C#6 .", "D6 - C6 A5 F5 . A5 .", "G5 - B5 - C6 - Bb5 .",
              "A5 . C6 . F6 . E6 .", "D6 . C6 . A5 - G5 .", "F5 . A5 . B5 . D6 .", "C6 - - - Bb5 - G5 -",
              "D6 . F6 . D6 C6 Bb5 .", "C6 - A5 - G5 . E5 .", "F5 . G5 . Bb5 . D6 .", "E6 - - - C6 - Bb5 -",
              "A5 . Bb5 . D6 . F6 .", "E6 - C6 - F#5 - A5 -", "G5 . Bb5 . E5 . G5 .", "F5 - - - . . . ."]
    # the lifted section replays the opening, and its last bar is a C7 in the home key to lead back
    prog += prog[:7] + ["C7"]
    melody += melody[:7] + ["C6 - Bb5 - G5 - E5 -"]
    for bar, (chord, mel) in enumerate(zip(prog, melody)):
        s.line("talk", bar, mel, 90, legato=0.98)
        s.line(1, bar, mel, 64, legato=0.7)
        s.pad("juno", bar, chord, 60, 90)
        s.chords(3, bar, chord, [3, 7], 0.45, 62, 66)
        s.chords(4, bar, chord, [1, 3, 5, 6], 0.1, 67, 60)
        s.bass(2, bar, chord, "R . R 8 . R . 5 R . 8 R . 7 8 .", 102, step=0.25)
        if bar % 4 == 3:
            for k in voicing(chord.split()[0], 64):
                s.note(5, bar * 4, 0.35, k, 92)
        if bar % 2 == 1:
            tones = voicing(chord.split()[-1], 79)
            for j, k in enumerate(tones):
                s.note("bub", bar * 4 + 2.5 + j * 0.5, 0.2, k, 92)
        else:
            s.hits("chop", bar, chord, "........ ..1.2.3.", 70, 88, dur=0.16)
        if bar % 8 == 3:
            s.note("squeak", bar * 4 + 3.5, 0.35, midi("A6"), 96)
        fill = bar % 8 == 7
        groove(s, bar, "four", fill, bar % 8 == 0, {"tamb": "..o...o...o...o."} if bar >= 8 else None)
    return s


def final():
    """Crumble!: the last thirty seconds, D minor happy hardcore at 174. Each eight bars goes up a
    semitone, so the round ends two key changes higher than it started: jungle breaks, then the four
    on the floor, then everything. Strings, brass, choir, timpani and orchestra hits from the band,
    acid bass, a supersaw lead, hardcore piano stabs and a gated saw from the synths."""
    s = Song(174, 24)
    s.channel(0, 48, 100, 40, level=-21)    # strings ostinato
    s.channel(1, 61, 100, 70, level=-18)    # brass section
    s.channel(2, 9, 100, 30, level=-24)     # glockenspiel
    s.channel(3, 38, 100, 64, level=-19)    # synth bass
    s.channel(4, 47, 100, 64, level=-17)    # timpani
    s.channel(5, 55, 100, 64, level=-17)    # orchestra hit
    s.channel(6, 52, 100, 64, level=-21)    # choir
    s.channel(7, 0, 100, 88, level=-21)     # hardcore piano stabs
    s.channel(8, 56, 100, 52, level=-19)    # trumpet over the top
    s.channel(9, 0, 100, 64, drums=True, level=-12)
    s.synth("acid", ACID, -19, {"hp": 40, "delay": (0.15, 0.75, 0.25)})
    s.synth("gate", GATE_SAW, -23, {"sidechain": (0.5, 0.3), "hp": 200, "width": 1.3})
    s.synth("lead", LEAD_SAW, -19, {"delay": (0.25, 0.75, 0.3), "hp": 250})
    s.synth("pad", FAT_PAD, -24, {"sidechain": (0.6, 0.3), "hp": 200, "chorus": (0.4, 4, 8)})
    s.synth("chop", CHOP, -21, {"delay": (0.25, 0.5, 0.3), "hp": 250})
    s.synth("rise", riser(8 * 60 / 174), -24, {"hp": 200})
    s.synth("drop", SUB_DROP, -18, {})
    s.lift(8, 15, 1)
    s.lift(16, 23, 2)

    prog = ["Dm", "Bb", "Gm", "A7", "Dm", "Bb", "Gm A7", "Dm"]
    prog = prog + ["Dm", "Bb", "C", "A7", "Dm", "Bb", "Gm", "A7"] + ["Bb", "C", "Dm", "Dm", "Bb", "C", "A7", "A7"]
    first = ["D5 - - A4 D5 - F5 -", "F5 - E5 - D5 - Bb4 -", "G4 - - Bb4 D5 - G5 -", "E5 - - - C#5 - A4 -",
             "D5 - - A4 D5 - F5 -", "A5 - G5 - F5 - D5 -", "G5 - F5 - E5 - C#5 -", "D5 - - - - - . ."]
    second = ["F5 - - D5 F5 - A5 -", "Bb5 - A5 - G5 - F5 -", "G5 - - C6 - - E5 -", "C#6 - - - A5 - - -",
              "D6 - - A5 F5 - D5 -", "F5 - G5 - A5 - Bb5 -", "Bb5 - A5 - G5 - E5 -", "A5 - - - - - . ."]
    third = ["F5 - - G5 A5 - D6 -", "D6 - C6 - Bb5 - A5 -", "C6 - - - E6 - - -", "D6 - - - F6 - - -",
             "F6 - - E6 D6 - A5 -", "C6 - - D6 E6 - G6 -", "E6 - - - C#6 - - -", "A5 - B5 - C#6 - E6 -"]

    acid = [(0, 118), None, (12, 90), (0, 80), (10, 100), (0, 76), (12, 120), (7, 86),
            (0, 110), (0, 72), None, (12, 104), (0, 78), (15, 96), (12, 116), (10, 90)]
    for bar, chord in enumerate(prog):
        sec = bar // 8
        mel = (first, second, third)[sec][bar % 8]
        # the tune moves up the band as the round runs out: brass, then the lead, then everyone
        s.line(1, bar, mel, 102, legato=0.8, octave=-1 if sec == 0 else 0)
        if sec >= 1:
            s.line("lead", bar, mel, 100, legato=0.9)
            s.line(2, bar, mel, 72)
        if sec == 2:
            s.line(8, bar, mel, 104, legato=0.7)
            s.line("lead", bar, mel, 90, legato=0.9, octave=-1)
            s.pad(6, bar, chord, 64, 96)
        if sec == 1:
            s.pad(6, bar, chord, 60, 80)
        s.pad("pad", bar, chord, 60, 96)

        tones = voicing(chord.split()[0], 62)
        pattern = [0, 0, 2, 0, 1, 0, 2, 0]
        for j in range(16):
            k = tones[pattern[j % 8]] + (12 if j % 8 == 2 else 0)
            s.note(0, bar * 4 + j * 0.25, 0.2, k, 90 if j % 4 == 0 else 70)
        s.bass(3, bar, chord, "R R 8 R R R 8 R", 100, octave=1)
        root2 = bass_root(chord.split()[0], 2)
        for j, step in enumerate(acid):
            if step:
                # loud steps open the filter further; every fourth step slides into the next
                s.note("acid", bar * 4 + j * 0.25, 0.26 if j % 4 == 3 else 0.16, root2 + step[0], step[1])
        s.chords(7, bar, chord, [1, 3, 5, 7], 0.22, 70, 96 if sec else 80)
        if sec >= 1:
            for j, on in enumerate("x.xxx.xxx.xx.xxx"):
                if on == "x":
                    for k in voicing(chord.split()[min(j // 8, len(chord.split()) - 1)], 67):
                        s.note("gate", bar * 4 + j * 0.25, 0.14, k, 100 if j % 4 == 0 else 80)
        if bar % 2 == 1:
            s.hits("chop", bar, chord, "........ 4.3.2.0.", 74, 96, dur=0.15)

        root = bass_root(chord.split()[0], 1) + 12
        s.note(4, bar * 4, 1.5, root, 108)
        if bar % 8 in (3, 7):
            for j in range(8):
                s.note(4, bar * 4 + 2 + j * 0.25, 0.25, root, 70 + j * 6)
        if bar % 8 == 0 or sec == 2 and bar % 2 == 0:
            for k in voicing(chord, 60):
                s.note(5, bar * 4, 1, k, 104)
        if bar % 8 == 0:
            s.note("drop", bar * 4, 4, bass_root("D", 1), 120)

        fill = bar % 8 == 7
        crash = bar % 8 == 0 or sec == 2 and bar % 4 == 0
        if sec == 0:
            groove(s, bar, "break" if bar % 2 == 0 else "break2", fill, crash)
        elif sec == 1:
            groove(s, bar, "hardcore", fill, crash)
        else:
            groove(s, bar, "hardcore", fill, crash, {"snare": "..o.X..o.o..X.o.", "tamb": "oxoxoxoxoxoxoxox"})
    for at in (6, 14, 22):
        s.note("rise", at * 4, 8, 60, 120)
    return s


def gumball():
    """Gumball Gallop: round theme, G major circus shuffle in 12/8, every beat split in three. A rondo
    rather than verse and chorus: the accordion tune comes back three times between a kazoo song in
    E minor and a slide whistle interlude lifted a minor third, where the drums switch to straight
    sixteenths against the band's triplets before everything gallops home."""
    s = Song(150, 40)
    t = 1 / 3
    s.channel(0, 21, 100, 48, level=-18)          # accordion lead
    s.channel(1, 105, 100, 84, level=-23)         # banjo strums
    s.channel(2, 45, 100, 36, level=-23)          # pizzicato strings
    s.channel(3, 8, 100, 76, level=-24)           # celesta, the toy piano
    s.channel(4, 59, 100, 58, level=-19)          # muted trumpet
    s.channel(5, 9, 100, 92, level=-25)           # glockenspiel
    s.channel(6, 32, 100, 64, level=-20)          # upright bass
    s.channel(9, 0, 100, 64, drums=True, level=-14)
    s.synth("kazoo", KAZOO, -20, {"hp": 200, "delay": (0.15, 1, 0.25)})
    s.synth("slide", SLIDE_WHISTLE, -21, {"delay": (0.3, 1, 0.35)})
    s.synth("bounce", BOUNCE_BASS, -17, {"sidechain": (0.3, 0.3)})
    s.synth("chop", CHOP, -21, {"delay": (0.2, 0.67, 0.3), "hp": 250})
    s.synth("squeak", SQUEAK, -24, {"delay": (0.2, 0.67, 0.3)})
    s.synth("rise", riser(8 * 60 / 150), -26, {"hp": 200})
    s.synth("drop", SUB_DROP, -19, {})
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
        # last time round: accordion, kazoo an octave down, glockenspiel on top
        s.line(0, 32 + i, tune[i], 100, step=t, legato=0.8)
        s.line("kazoo", 32 + i, tune[i], 90, step=t, legato=0.9, octave=-1)
        s.line(5, 32 + i, tune[i], 80, step=t, legato=0.5)

    for bar, chord in enumerate(prog):
        # oom pa pa on every beat: bass on the first triplet, the banjo on the other two
        for start, ch, span in s.spans(bar, chord):
            for beat in range(int(span)):
                for k in voicing(ch, 64):
                    for off in (t, 2 * t):
                        s.note(1, start + beat + off, 0.25, k, 76 if off == t else 66)
        s.bass("bounce", bar, chord, "R . 8 5 . 8 R . 8 5 . 8", 106, step=t)
        s.bass(6, bar, chord, "R . . 5 . . R . . 5 . .", 96, step=t)
        if 8 <= bar < 16 or bar >= 24:
            s.arp(3 if bar < 16 else 5, bar, chord, [0, 1, 2, 3, 2, 1], 76, 70, step=t, legato=0.6)
            s.bass(2, bar, chord, ". 8 . . 8 . . 8 . . 8 .", 84, octave=3, step=t)
        # hey! on the last beat of every other bar of the tune
        if bar % 8 in (1, 3, 5) and (bar < 8 or bar >= 16) and not 24 <= bar < 32:
            s.hits("chop", bar, chord, ". . . . . . . . . 4 . 4", 72, 100, dur=0.2, step=t)
        if bar % 8 == 7 and bar < 24:
            s.note("squeak", bar * 4 + 2, 0.5, midi("D6"), 100)
    # the slide whistle swoops into the interlude and back out of it
    s.line("slide", 23, ". . . . . . G4 - - G6 - -", 96, step=t, legato=0.99)
    s.note("rise", 22 * 4, 8, 60, 120)
    s.note("rise", 30 * 4, 8, 60, 120)
    s.note("drop", 32 * 4, 4, midi("G1"), 120)
    s.note("drop", 0, 4, midi("G1"), 100)

    shuffle = {"kick": "X.....x..x..", "snare": "...X.....X..", "hat": "x.xx.xx.xx.x"}
    gallop = {"kick": "X..x..X..x..", "snare": "...X.....X.o", "ride": "x.xx.xx.xx.x", "tamb": "..x..x..x..x"}
    for bar in range(40):
        fill = bar % 8 == 7
        if 24 <= bar < 32:
            # two against three: the drums go straight under the triplet band
            groove(s, bar, "four", fill, bar == 24, {"tamb": "oxoxoxoxoxoxoxox"})
            continue
        p = dict(gallop if bar >= 32 or 8 <= bar < 16 else shuffle)
        if fill:
            p.update(snare="......xxxXXX", htom="......x.....", ltom="........x...")
        if bar % 8 == 0:
            p["crash"] = "X..........."
        s.drums(bar, p, step=t)
    return s


def sugar():
    """Sugar Rush: round theme, a Dreamcast style breakbeat pop song led by the jelly bean singers.
    It is shaped like a song, not a loop of one tune: an intro, an A minor verse on breaks,
    a stop time pre chorus where the band only hits and lets the singers carry it, a C major chorus,
    a six bar half time bridge in Eb, the chorus again a minor third up, and two bars that turn
    back to A minor for the loop."""
    s = Song(150, 40)
    s.channel(0, 36, 100, 64, level=-17)          # slap bass
    s.channel(1, 7, 100, 30, level=-24)           # clavinet
    s.channel(2, 61, 100, 70, level=-19)          # horn section
    s.channel(3, 0, 100, 96, level=-22)           # piano
    s.channel(4, 56, 100, 52, level=-20)          # trumpet countermelody
    s.channel(5, 11, 100, 84, level=-23)          # vibraphone
    s.channel(6, 55, 100, 64, level=-19)          # orchestra hit
    s.channel(9, 0, 100, 64, drums=True, level=-13)
    s.synth("voice", CHOP_YA, -18, {"delay": (0.2, 0.75, 0.3), "hp": 220})
    s.synth("voice2", CHOP, -24, {"hp": 220, "width": 1.4})
    s.synth("saw", SUPERSAW, -21, {"sidechain": (0.7, 0.35), "hp": 180, "width": 1.3})
    s.synth("lead", LEAD_SAW, -21, {"delay": (0.2, 0.75, 0.3), "hp": 250})
    s.synth("spark", SPARKLE, -25, {"delay": (0.35, 0.75, 0.4), "hp": 300})
    s.synth("talk", TALKBOX, -19, {"hp": 200, "delay": (0.2, 0.75, 0.3)})
    s.synth("sweep", {**SWEEP_PAD, "lfo": (24, 3.0, 96)}, -22, {"chorus": (0.5, 4, 8), "hp": 150})
    s.synth("rise", riser(8 * 60 / 150), -25, {"hp": 200})
    s.synth("drop", SUB_DROP, -18, {})
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
    counter = ["A5 - - - - - - -", "B5 - - - - - - -", "G5 - - - B5 - - -", "A5 - - - C6 - - -",
               "A5 - - - - - - -", "D6 - - - B5 - - -", "G5 - - - - - - -", "E5 - - - G5 - C6 -"]
    bridge_mel = ["C6 - - - Eb6 - - -", "D6 - - - F6 - - -", "D6 - Bb5 - G5 - - -", "Eb6 - - - G6 - - -",
                  "F6 - Eb6 - C6 - Ab5 -", "D6 - - - F6 - Bb5 -"]

    for i in range(4):
        s.hits("voice", i, intro[i], "0.0.2.0. 3.2.0...", 72, 88, dur=0.18)
    for i, mel in enumerate(verse_mel):
        s.line("voice", 4 + i, mel, 98, legato=0.7)
    for i, mel in enumerate(pre_mel):
        s.line("voice", 12 + i, mel, 100, legato=0.95)
        s.line("voice2", 12 + i, mel, 86, legato=0.95, octave=-1)
    for i, mel in enumerate(hook):
        for bar in (16 + i, 30 + i):
            s.line("lead", bar, mel, 100, legato=0.85)
            s.line("voice", bar, mel, 96, legato=0.6)
            s.line(5, bar, mel, 70, legato=0.5)
        s.line(4, 30 + i, counter[i], 98, legato=0.8)
    for i, mel in enumerate(bridge_mel):
        s.line("talk", 24 + i, mel, 92, legato=0.98)
    s.line("lead", 38, "A5 - G5 - F5 - E5 -", 96, legato=0.9)
    s.line("lead", 39, "G#5 - - - B5 - D6 -", 100, legato=0.9)

    for bar, chord in enumerate(prog):
        if bar < 4:
            s.bass(0, bar, chord, "R . . R . . 8 .", 96)
        elif bar < 12:
            s.bass(0, bar, chord, "R . R 8 . R . 5 R . 8 R . 7 8 .", 104, step=0.25)
            s.chords(1, bar, chord, [1, 2, 5, 6], 0.1, 66, 72)
            if bar % 2 == 1:
                s.hits("voice2", bar, chord, "........ ....2.3.", 74, 86, dur=0.15)
        elif bar < 16:
            # stop time: only the band hits, the singers hold the line
            s.bass(0, bar, chord, "R . . R . . . .", 110)
            s.chords(2, bar, chord, [0, 3], 0.3, 64, 106)
            s.chords(3, bar, chord, [0, 3], 0.3, 70, 96)
        elif bar < 24 or 30 <= bar < 38:
            s.bass(0, bar, chord, "R . R 8 R . 8 R", 108)
            s.chords("saw", bar, chord, [1, 3, 5, 7], 0.22, 67, 96)
            s.chords(3, bar, chord, [1, 3, 5, 7], 0.2, 72, 84)
            s.arp("spark", bar, chord, [0, 2, 4, 2, 1, 3, 5, 3], 74, 80)
            if bar % 2 == 1:
                s.chords(2, bar, chord, [3, 6], 0.25, 64, 100)
        elif bar < 30:
            s.pad("sweep", bar, chord, 64, 100)
            s.bass(0, bar, chord, "R - - - . . 5 8", 100)
            s.chords(1, bar, chord, [3, 7], 0.12, 66, 70)
        else:
            s.chords(2, bar, chord, [0, 3, 6], 0.3, 64, 104)
            s.bass(0, bar, chord, "R R R R R R R R", 104)
        if bar in (16, 30):
            for k in voicing(chord, 60):
                s.note(6, bar * 4, 1, k, 108)
    s.note("rise", 14 * 4, 8, 60, 120)
    s.note("rise", 28 * 4, 8, 60, 120)
    s.note("drop", 16 * 4, 4, midi("A1"), 120)
    s.note("drop", 30 * 4, 4, midi("A1"), 120)

    stop = {"kick": "X.....X.........", "clap": "....X.......X..."}
    for bar in range(40):
        fill = bar in (11, 23, 37, 39)
        if bar < 4:
            groove(s, bar, "half", bar == 3, False, {"hat": "x.x.x.x.x.x.x.x."})
        elif bar < 12:
            groove(s, bar, "break" if bar % 2 == 0 else "break2", fill, bar == 4)
        elif bar < 16:
            p = dict(stop)
            if bar == 15:
                p["snare"] = "x.x.x.x.xxxxXXXX"
            s.drums(bar, p)
        elif bar < 24 or 30 <= bar < 38:
            groove(s, bar, "hardcore", fill, bar in (16, 20, 30, 34), {"tamb": "oxoxoxoxoxoxoxox"} if bar >= 30 else None)
        elif bar < 30:
            groove(s, bar, "half", bar == 29, bar == 24)
        else:
            groove(s, bar, "four", True, False)
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


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: compose.py GeneralUser-GS.sf2 MuseScore_General.sf2")
    gugs, msg = sys.argv[1:]
    tracks = {}
    for name, make, sf, once in [("menu", menu, msg, False), ("jam", jam, msg, False), ("wobble", wobble, msg, False),
                                 ("gumball", gumball, msg, False), ("sugar", sugar, msg, False), ("final", final, msg, False), ("victory", victory, gugs, True)]:
        # seeded per track so changing one track leaves the others' humanizing alone
        random.seed(name)
        tracks[name] = (render_once if once else render_loop)(make(), sf, name)
    (OUT / "tracks.json").write_text(json.dumps(tracks, indent=2) + "\n")
    for name, t in tracks.items():
        print(name, t)


if __name__ == "__main__":
    main()
