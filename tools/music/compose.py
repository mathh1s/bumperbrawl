"""Composes and renders the Bumper Brawl soundtrack.

Every track is written as note grids and patterns below, played through a
soundfont, given a convolution reverb and encoded to mp3. The round themes
use MuseScore General for its livelier brass and mallets; the rest use
GeneralUser GS. Synth parts from synth.py are layered on top of the band. Loops are cut from the middle of a three times render so the
reverb and note tails of the previous pass are already present at the loop
start, which makes the loop seamless. The loop points land in
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

    def channel(self, ch, preset, volume=100, pan=64, bank=0, drums=False, level=None):
        """level is the target loudness in dB while the part plays; None leaves the synth's own balance."""
        self.channels[ch] = (bank, preset, drums, volume, pan)
        if level is not None:
            self.levels[ch] = level

    def synth(self, name, patch, level, fx=None):
        """A synth part next to the soundfont channels; notes go to it by name like to a channel number."""
        self.synths[name] = (patch, fx or {})
        self.levels[name] = level

    def note(self, ch, beat, dur, key, vel):
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

    def bass(self, ch, bar, sym, pattern, vel, octave=2):
        """Eighth note bass. R root, 8 octave, 5 fifth, 3 third, '-' hold, '.' rest."""
        for start, chord, span in self.spans(bar, sym):
            root = bass_root(chord, octave)
            _, ivs, _ = parse_chord(chord)
            tokens = pattern.split()[: int(span * 2)]
            current = None
            for i, tok in enumerate(tokens):
                if tok == "-" and current:
                    current[1] += 0.5
                    continue
                if current:
                    self.note(ch, *current)
                current = None
                if tok != ".":
                    off = {"R": 0, "8": 12, "5": 7, "3": ivs[1]}[tok]
                    current = [start + i * 0.5, 0.45, root + off, vel + random.uniform(-6, 4)]
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

    def drums(self, bar, pattern, ch=9):
        """Sixteen steps per instrument. X accent, x normal, o soft, '.' nothing."""
        for name, steps in pattern.items():
            for i, s in enumerate(steps.replace(" ", "")):
                if s in "Xxo":
                    self.note(ch, bar * 4 + i * 0.25, 0.2, DRUM[name], {"X": 118, "x": 92, "o": 58}[s] + random.uniform(-6, 6))


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


def wobble_bass(period):
    return {"osc": [(SAW, 0, 1.0), (SAW, -12, 0.6)], "sub": 0.6, "amp": (0.004, 0.3, 0.9, 0.05),
            "cutoff": 2200, "lfo": (period, 3.6, 0), "res": 2.4, "drive": 1.2}


def riser(seconds):
    return {"osc": [], "noise": 0.6, "amp": (seconds * 0.9, 1, 1, 0.08), "filt": (seconds, 1, 1, 0.1),
            "cutoff": 250, "env_oct": 5, "res": 2.0, "mode": 1}


# ==== tracks ====

def jam():
    """Jelly Jam: round theme, C major disco house with a marimba hook and a horn section.
    The band is MuseScore General; the synths give it the club side: pumping supersaw stabs,
    a filtered octave bass, a resonant arp and a pad that opens up through the breakdown."""
    s = Song(126, 32)
    s.channel(0, 13, 100, 44, level=-19)          # xylophone hook
    s.channel(1, 12, 100, 84, level=-22)          # marimba doubling an octave down
    s.channel(2, 56, 100, 58, level=-18)          # trumpet lead
    s.channel(3, 61, 100, 70, bank=8, level=-20)  # horn section stabs
    s.channel(4, 28, 100, 30, bank=8, level=-25)  # funk guitar chops
    s.channel(5, 33, 100, 64, level=-19)          # fingered bass, the synth bass carries the low end
    s.channel(6, 45, 100, 96, level=-24)          # pizzicato strings in the breakdown
    s.channel(7, 57, 100, 40, level=-21)          # trombone under the trumpet
    s.channel(9, 8, 100, 64, drums=True, level=-14)
    s.synth("saw", SUPERSAW, -21, {"sidechain": (0.7, 0.35), "hp": 180, "width": 1.3})
    s.synth("disco", DISCO_BASS, -18, {"sidechain": (0.4, 0.3)})
    s.synth("spark", SPARKLE, -25, {"delay": (0.35, 0.75, 0.4), "hp": 300})
    s.synth("sweep", {**SWEEP_PAD, "lfo": (32, 3.4, 96)}, -21, {"chorus": (0.5, 4, 8), "hp": 150})
    s.synth("rise", riser(8 * 60 / 126), -27, {"hp": 200})

    a = ["C", "Am7", "Dm7", "G7", "C", "Am7", "Dm7 G7", "C"]
    b = ["F", "G", "Em7", "Am7", "Dm7", "G", "E7", "Am7 G7"]
    c = ["Am7", "F", "Dm7", "G", "F", "G", "Ab", "G7"]
    prog = a + a + b + c

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
    for i, mel in enumerate(verse):
        s.line(2, 16 + i, mel, 100, legato=0.85, octave=-1)
        s.line(7, 16 + i, mel, 86, legato=0.85, octave=-2)
        s.line(0, 16 + i, mel, 58, legato=0.4)
    for i, mel in enumerate(breakdown):
        s.line(1, 24 + i, mel, 86, legato=0.5)
        s.line(6, 24 + i, mel, 80, legato=0.4, octave=-1)
    for i, mel in enumerate(build):
        s.line(2, 28 + i, mel, 98, legato=0.8, octave=-1)
        s.line(7, 28 + i, mel, 90, legato=0.8, octave=-2)
    s.line(0, 31, "G5 A5 B5 C6 D6 E6 F6 G6", 84, legato=0.6)

    for bar, chord in enumerate(prog):
        if 8 <= bar < 24 or bar >= 28:
            s.chords("saw", bar, chord, [1, 3, 5, 7], 0.22, 67, 96)
        if 16 <= bar < 24 or bar >= 28:
            s.arp("spark", bar, chord, [0, 2, 4, 2, 1, 3, 5, 3], 74, 82)
        if 24 <= bar < 28:
            s.pad("sweep", bar, chord, 64, 100)
        if bar < 24:
            s.bass("disco", bar, chord, "R 8 R 8 R 8 R 8", 108)
            s.bass(5, bar, chord, "R 8 R 8 R 8 R 8", 104)
            s.chords(4, bar, chord, [1, 3, 5, 7], 0.12, 64, 76)
            # horn stabs answer the melody on the and of 2 and on 4
            if bar % 2 == 1 or bar >= 16:
                s.chords(3, bar, chord, [3, 6], 0.25, 64, 98)
        elif bar < 28:
            s.bass(5, bar, chord, "R - - - . . 5 8", 98)
        else:
            s.bass(5, bar, chord, "R R R R R R R R", 100)
            s.bass("disco", bar, chord, "R 8 R 8 R 8 R 8", 112)
            s.chords(3, bar, chord, [0, 3, 6], 0.3, 64, 102)
    # white noise swells into the top of the loop
    s.note("rise", 30 * 4, 8, 60, 120)

    for bar in range(32):
        last = bar % 8 == 7
        if bar < 8:
            p = {"kick": "X...x...X...x...", "clap": "....X.......X...", "hat": "xoxoxoxoxoxoxoxo", "ohat": "..o...o...o...o."}
        elif bar < 24:
            p = {"kick": "X...x...X...x...", "clap": "....X.......X...", "snare": "....o.......o..o",
                 "hat": "xoxoxoxoxoxoxoxo", "ohat": "..x...x...x...x.", "tamb": "..o...o...o...o."}
        elif bar < 28:
            p = {"kick": "X.......x.......", "clap": "........X.......", "shaker": "oxoxoxoxoxoxoxox"}
        elif bar < 31:
            p = {"kick": "X...x...X...x...", "snare": "x.x.x.x.x.x.x.x.", "shaker": "oxoxoxoxoxoxoxox"}
        else:
            p = {"kick": "X...x...X...x...", "snare": "xxxxxxxxxxxxXXXX"}
        if last and bar < 24:
            p.update(htom="........x.x.....", mtom="..........x.x...", ltom="............x.x.", ohat="..x...x.........")
        if bar % 8 == 0:
            p["crash"] = "X..............."
        if bar in (3, 11, 19):
            p["cowbell"] = "..x...x...x...x."
        s.drums(bar, p)
    return s


def wobble():
    """Wobble Run: round theme, F major ska bounce with an oompah tuba and a trumpet and trombone pair,
    crossed with an 8 bit console: pulse wave arps and lead, boings, and a wobble bass in the bridge."""
    s = Song(152, 32)
    s.channel(0, 56, 100, 52, level=-17)          # trumpet lead
    s.channel(1, 57, 100, 76, level=-21)          # trombone, melody an octave down
    s.channel(2, 13, 100, 40, level=-20)          # xylophone runs
    s.channel(3, 58, 100, 64, level=-15)          # tuba bass
    s.channel(4, 27, 100, 92, level=-23)          # clean guitar skank
    s.channel(5, 17, 100, 36, level=-26)          # percussive organ skank
    s.channel(6, 115, 100, 64, bank=1, level=-24)  # temple blocks
    s.channel(7, 61, 100, 64, level=-20)          # brass pads in the bridge
    s.channel(9, 0, 100, 64, drums=True, level=-15)
    s.synth("chip", CHIP, -26, {"hp": 250, "width": 1.2})
    s.synth("lead", CHIP_LEAD, -23, {"delay": (0.4, 0.75, 0.35), "hp": 300})
    s.synth("wob", wobble_bass(1), -18, {"hp": 35})
    s.synth("wob2", wobble_bass(0.5), -18, {"hp": 35})
    s.synth("boing", BOING, -23, {"delay": (0.25, 0.5, 0.3)})

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
    s.line(2, 31, "C5 E5 G5 Bb5 C6 E6 G6 Bb6", 86, legato=0.6)

    for bar, chord in enumerate(prog):
        # oompah: tuba on the beats, the band on the offbeats
        s.bass(3, bar, chord, "R . 5 . R . 5 .", 104, octave=1)
        s.chords(4, bar, chord, [1, 3, 5, 7], 0.18, 62, 82)
        s.chords(5, bar, chord, [1, 3, 5, 7], 0.18, 70, 64)
        if bar >= 24:
            for start, ch, span in s.spans(bar, chord):
                for k in voicing(ch, 62):
                    s.note(7, start, span * 0.95, k, 76)
        if bar % 4 == 3:
            s.line(6, bar, ". . . . D4 D4 C4 Bb3", 90, legato=0.5)
        if bar < 24:
            s.arp("chip", bar, chord, [0, 1, 2, 3, 2, 1] if bar < 16 else [0, 2, 1, 3, 2, 4], 72, 86)
        else:
            # the bridge drops the skank feel into a wobble, twice as fast in its second half
            for start, ch, span in s.spans(bar, chord):
                s.note("wob" if bar < 28 else "wob2", start, span * 0.98, bass_root(ch, 2), 104)
        if bar % 4 == 1:
            s.note("boing", bar * 4 + 3.5, 0.4, midi("F5"), 104)

    for bar in range(32):
        p = {"kick": "x.......x.......", "snare": "....X.......X...", "hat": "..x...x...x...x."}
        if 8 <= bar < 16:
            p.update(snare="....X.......X..o", tamb="oxoxoxoxoxoxoxox")
        if bar >= 24:
            p.update(ride="x.x.x.x.x.x.x.x.", hat="................")
        if bar % 8 == 7:
            p.update(snare="....X...x.x.xxxx", htom="........x.......", ltom="..........x.....")
        if bar % 8 == 0:
            p["crash"] = "X..............."
        s.drums(bar, p)
    return s


def menu():
    """Blob Lounge: menu and between rounds, F major funk at strutting pace, sung by a talk box lead
    over a chorused poly pad, with bubbly blips at the end of every other bar."""
    s = Song(112, 16)
    s.synth("talk", TALKBOX, -19, {"hp": 200, "delay": (0.18, 0.75, 0.3)})
    s.synth("juno", JUNO, -25, {"chorus": (0.6, 5, 8), "hp": 160})
    s.synth("bub", BUBBLE, -27, {"delay": (0.35, 0.75, 0.4)})
    s.channel(1, 11, 100, 82, level=-21)    # vibraphone doubling
    s.channel(2, 36, 100, 64, level=-18)   # slap bass
    s.channel(3, 4, 100, 38, level=-24)     # electric piano
    s.channel(4, 7, 100, 92, level=-25)     # clavinet
    s.channel(5, 62, 100, 64, level=-20)    # synth brass
    s.channel(9, 0, 100, 64, drums=True, level=-17)

    prog = ["Fmaj7", "Em7 A7", "Dm7", "G7 C7", "Fmaj7", "Em7 A7", "Dm7 G7", "C7sus C7",
            "Bbmaj7", "Am7", "Gm7", "C7", "Bbmaj7", "Am7 D7", "Gm7 C7", "Fmaj7"]
    melody = ["A5 . C6 . A5 G5 F5 .", "E5 . G5 . A5 - C#6 .", "D6 - C6 A5 F5 . A5 .", "G5 - B5 - C6 - Bb5 .",
              "A5 . C6 . F6 . E6 .", "D6 . C6 . A5 - G5 .", "F5 . A5 . B5 . D6 .", "C6 - - - Bb5 - G5 -",
              "D6 . F6 . D6 C6 Bb5 .", "C6 - A5 - G5 . E5 .", "F5 . G5 . Bb5 . D6 .", "E6 - - - C6 - Bb5 -",
              "A5 . Bb5 . D6 . F6 .", "E6 - C6 - F#5 - A5 -", "G5 . Bb5 . E5 . G5 .", "F5 - - - . . . ."]
    for bar, (chord, mel) in enumerate(zip(prog, melody)):
        s.line("talk", bar, mel, 90, legato=0.98)
        s.line(1, bar, mel, 64, legato=0.7)
        s.pad("juno", bar, chord, 60, 90)
        if bar % 2 == 1:
            tones = voicing(chord.split()[-1], 79)
            for j, k in enumerate(tones):
                s.note("bub", bar * 4 + 2.5 + j * 0.5, 0.2, k, 92)
        s.chords(3, bar, chord, [3, 7], 0.45, 62, 66)
        s.chords(4, bar, chord, [1, 3, 5, 6], 0.1, 67, 60)
        s.bass(2, bar, chord, "R . . R . 8 R .", 100)
        if bar % 4 == 3:
            for k in voicing(chord.split()[0], 64):
                s.note(5, bar * 4, 0.35, k, 92)
        p = {"kick": "x...x...x...x...", "clap": "....x.......x...", "hat": "oxoxoxoxoxoxoxox", "ohat": "..o...o...o...o."}
        if bar == 15:
            p.update(htom="........x.x.....", mtom="..........x.x...", ltom="............x.x.")
        if bar % 8 == 0:
            p["crash"] = "o..............."
        s.drums(bar, p)
    return s


def final():
    """Crumble!: last thirty seconds, D minor, urgent but still playful. An acid bass squelches in
    after four bars and a gated supersaw stutters through the second half."""
    s = Song(150, 16)
    s.sf_level = -14
    s.synth("acid", ACID, -20, {"hp": 40, "delay": (0.15, 0.75, 0.25)})
    s.synth("gate", GATE_SAW, -24, {"sidechain": (0.5, 0.3), "hp": 200, "width": 1.3})
    s.synth("rise", riser(8 * 60 / 150), -26, {"hp": 200})
    acid = [(0, 118), None, (12, 90), (0, 80), (10, 100), (0, 76), (12, 120), (7, 86),
            (0, 110), (0, 72), None, (12, 104), (0, 78), (15, 96), (12, 116), (10, 90)]
    s.channel(0, 48, 86, 40)    # strings ostinato
    s.channel(1, 61, 96, 70)    # brass section
    s.channel(2, 9, 62, 30)     # glockenspiel
    s.channel(3, 38, 104, 64)   # synth bass
    s.channel(4, 47, 96, 64)    # timpani
    s.channel(5, 55, 74, 64)    # orchestra hit
    s.channel(9, 0, 104, 64, drums=True)

    prog = ["Dm", "Dm", "Bb", "C", "Dm", "Dm", "Bb", "A7", "Dm", "Bb", "Gm", "A7", "Dm", "Bb", "Gm", "A7"]
    melody = ["D5 - - A4 D5 - F5 -", "E5 - D5 - C5 - A4 -", "Bb4 - - D5 F5 - Bb5 -", "A5 - G5 - E5 - C5 -",
              "D5 - - A4 D5 - F5 -", "A5 - G5 - F5 - E5 -", "F5 - D5 - Bb4 - D5 -", "C#5 - - - E5 - A5 -",
              "F5 - - D5 F5 - A5 -", "Bb5 - A5 - G5 - F5 -", "G5 - - Bb5 - - D6 -", "C#6 - - - A5 - - -",
              "D6 - - A5 F5 - D5 -", "F5 - G5 - A5 - Bb5 -", "Bb5 - A5 - G5 - E5 -", "A5 - - - - - . ."]
    for bar, (chord, mel) in enumerate(zip(prog, melody)):
        s.line(1, bar, mel, 100, legato=0.8, octave=-1)
        s.line(2, bar, mel, 70)
        tones = voicing(chord, 62)
        pattern = [0, 0, 2, 0, 1, 0, 2, 0]
        for j in range(16):
            k = tones[pattern[j % 8]] + (12 if j % 8 == 2 else 0)
            s.note(0, bar * 4 + j * 0.25, 0.2, k, 84 if j % 4 == 0 else 66)
        s.bass(3, bar, chord, "R R 8 R R R 8 R", 100, octave=1)
        root = bass_root(chord, 1) + 12
        s.note(4, bar * 4, 1.5, root, 104)
        if bar in (7, 11, 15):
            for j in range(8):
                s.note(4, bar * 4 + 2 + j * 0.25, 0.25, root, 70 + j * 6)
        if bar in (0, 8):
            for k in voicing(chord, 60):
                s.note(5, bar * 4, 1, k, 96)
        root2 = bass_root(chord, 2)
        if bar >= 4:
            for j, step in enumerate(acid):
                if step:
                    # loud steps open the filter further; every fourth step slides into the next
                    s.note("acid", bar * 4 + j * 0.25, 0.26 if j % 4 == 3 else 0.16, root2 + step[0], step[1])
        if bar >= 8:
            for j, on in enumerate("x.xxx.xxx.xx.xxx"):
                if on == "x":
                    for k in voicing(chord, 67):
                        s.note("gate", bar * 4 + j * 0.25, 0.14, k, 100 if j % 4 == 0 else 80)
        p = {"kick": "X...x...X...x...", "snare": "....X.......X.o.", "hat": "xoxoxoxoxoxoxoxo"}
        if bar in (7, 15):
            p.update(snare="....X.......xxxx", htom="........xx......", ltom="..........xx....")
        if bar in (0, 8):
            p["crash"] = "X..............."
        s.drums(bar, p)
    s.note("rise", 14 * 4, 8, 60, 120)
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
    for name, make, sf, once in [("menu", menu, gugs, False), ("jam", jam, msg, False), ("wobble", wobble, msg, False),
                                 ("final", final, gugs, False), ("victory", victory, gugs, True)]:
        # seeded per track so changing one track leaves the others' humanizing alone
        random.seed(name)
        tracks[name] = (render_once if once else render_loop)(make(), sf, name)
    (OUT / "tracks.json").write_text(json.dumps(tracks, indent=2) + "\n")
    for name, t in tracks.items():
        print(name, t)


if __name__ == "__main__":
    main()
