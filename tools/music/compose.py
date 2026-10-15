"""Composes and renders the Bumper Brawl soundtrack.

Every track is written as note grids and patterns below, played through a
soundfont, given a convolution reverb and encoded to mp3. The round themes
use MuseScore General for its livelier brass and mallets; the rest use
GeneralUser GS. Loops are cut from the middle of a three times render so the
reverb and note tails of the previous pass are already present at the loop
start, which makes the loop seamless. The loop points land in
web/music/tracks.json.

> setup      pip install --no-deps tinysoundfont && pip install numpy scipy
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

    def channel(self, ch, preset, volume=100, pan=64, bank=0, drums=False, level=None):
        """level is the target loudness in dB while the part plays; None leaves the synth's own balance."""
        self.channels[ch] = (bank, preset, drums, volume, pan)
        if level is not None:
            self.levels[ch] = level

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
# level are rendered alone and set to that level before mixing.
def render(song, soundfont, repeats, tail=3.0):
    if song.levels:
        dry = None
        for ch in song.channels:
            part = copy.copy(song)
            part.events = [e for e in song.events if e[2] == ch]
            part.channels = {ch: song.channels[ch]}
            part.levels = {}
            stem, loop_samples = render_dry(part, soundfont, repeats, tail)
            if ch in song.levels:
                stem *= 10 ** ((song.levels[ch] - active_rms_db(stem)) / 20)
            dry = stem if dry is None else dry + stem
    else:
        dry, loop_samples = render_dry(song, soundfont, repeats, tail)
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


# ==== tracks ====

def jam():
    """Jelly Jam: round theme, C major disco with a marimba hook and a horn section.
    Played on MuseScore General, whose brass and mallets come closest to a live party band."""
    s = Song(126, 32)
    s.channel(0, 13, 100, 44, level=-19)          # xylophone hook
    s.channel(1, 12, 100, 84, level=-22)          # marimba doubling an octave down
    s.channel(2, 56, 100, 58, level=-18)          # trumpet lead
    s.channel(3, 61, 100, 70, bank=8, level=-20)  # horn section stabs
    s.channel(4, 28, 100, 30, bank=8, level=-25)  # funk guitar chops
    s.channel(5, 33, 100, 64, level=-16)          # fingered bass
    s.channel(6, 45, 100, 96, level=-24)          # pizzicato strings in the breakdown
    s.channel(7, 57, 100, 40, level=-21)          # trombone under the trumpet
    s.channel(9, 8, 100, 64, drums=True, level=-14)

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
        if bar < 24:
            s.bass(5, bar, chord, "R 8 R 8 R 8 R 8", 104)
            s.chords(4, bar, chord, [1, 3, 5, 7], 0.12, 64, 76)
            # horn stabs answer the melody on the and of 2 and on 4
            if bar % 2 == 1 or bar >= 16:
                s.chords(3, bar, chord, [3, 6], 0.25, 64, 98)
        elif bar < 28:
            s.bass(5, bar, chord, "R - - - . . 5 8", 98)
        else:
            s.bass(5, bar, chord, "R R R R R R R R", 100)
            s.chords(3, bar, chord, [0, 3, 6], 0.3, 64, 102)

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
    """Wobble Run: round theme, F major ska bounce with an oompah tuba and a trumpet and trombone pair."""
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
        s.line(2, 16 + i, mel, 54, legato=0.4, octave=1)
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
    """Blob Lounge: menu and between rounds, F major funk at strutting pace."""
    s = Song(112, 16)
    s.channel(0, 80, 100, 46, level=-19)    # square lead, gentle
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
        s.line(0, bar, mel, 84, legato=0.6)
        s.line(1, bar, mel, 72, legato=0.7)
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
    """Crumble!: last thirty seconds, D minor, urgent but still playful."""
    s = Song(150, 16)
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
        p = {"kick": "X...x...X...x...", "snare": "....X.......X.o.", "hat": "xoxoxoxoxoxoxoxo"}
        if bar in (7, 15):
            p.update(snare="....X.......xxxx", htom="........xx......", ltom="..........xx....")
        if bar in (0, 8):
            p["crash"] = "X..............."
        s.drums(bar, p)
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
