const VOLUME = 0.5;
const FADE = 1.2;
const VICTORY_HOLD = 3.6;

export class Music {
  constructor() {
    this.ctx = null;
    this.meta = null;
    this.buffers = {};
    this.current = null;
    this.blockUntil = 0;
    this.enabled = true;
    try {
      this.enabled = localStorage.getItem('bb.music') !== '0';
    } catch { /* storage blocked, default on */ }
  }

  init(ctx) {
    if (this.ctx || !ctx) return;
    this.ctx = ctx;
    this.bus = ctx.createGain();
    this.bus.gain.value = this.enabled ? VOLUME : 0;
    this.bus.connect(ctx.destination);
    this.load().catch((e) => console.warn('music failed to load', e));
  }

  async load() {
    this.meta = await (await fetch('music/tracks.json')).json();
    // menu first so something plays quickly, the rest streams in behind it
    for (const name of ['menu', 'jam', 'wobble', 'gumball', 'sugar', 'victory']) {
      const data = await (await fetch(this.meta[name].file)).arrayBuffer();
      this.buffers[name] = await new Promise((res, rej) => this.ctx.decodeAudioData(data, res, rej));
    }
  }

  // Idempotent: called every frame with the track the game state wants
  play(name) {
    if (!this.ctx || this.current?.name === name || this.ctx.currentTime < this.blockUntil) return;
    const buffer = this.buffers[name];
    if (!buffer) return;
    this.fadeOut();
    const now = this.ctx.currentTime;
    const meta = this.meta[name];
    const gain = this.ctx.createGain();
    gain.gain.setValueAtTime(0, now);
    gain.gain.linearRampToValueAtTime(1, now + FADE);
    gain.connect(this.bus);
    this.current = { name, gain, srcs: [], start: now, final: false };
    // round songs play their intro once and then repeat the loop; the menu is a plain loop
    if (meta.intro) this.voice(meta.loop, meta.intro[0], now);
    else this.voice([meta.loopStart, meta.loopEnd], 0, now);
  }

  // one pass through the song's file, looping between the two times in loop
  voice(loop, offset, at) {
    const cur = this.current;
    const src = this.ctx.createBufferSource();
    src.buffer = this.buffers[cur.name];
    src.loop = true;
    [src.loopStart, src.loopEnd] = loop;
    const fade = this.ctx.createGain();
    src.connect(fade).connect(cur.gain);
    src.start(at, offset);
    cur.srcs.push({ src, fade });
  }

  // Idempotent: sends a round song into its final part at the next bar line, through the switch
  final() {
    const cur = this.current;
    const meta = cur && this.meta[cur.name];
    if (!meta?.final || cur.final) return;
    cur.final = true;
    const now = this.ctx.currentTime;
    const intro = meta.intro[1] - meta.intro[0];
    // how far into the playing part we are; the intro and the loop both start on a bar line
    let into = now - cur.start;
    if (into >= intro) into = (into - intro) % (meta.loop[1] - meta.loop[0]);
    let wait = Math.ceil(into / meta.bar - 1e-6) * meta.bar - into;
    if (wait < 0.05) wait += meta.bar;
    const at = now + wait;
    for (const { src, fade } of cur.srcs) {
      // a few milliseconds of fade so cutting mid waveform doesn't click
      fade.gain.setValueAtTime(1, at);
      fade.gain.linearRampToValueAtTime(0, at + 0.012);
      src.stop(at + 0.02);
    }
    cur.srcs = [];
    // the switch sits right before the final in the file, so playback runs from one into the other
    this.voice(meta.final, meta.switch[0], at);
  }

  victory() {
    const buffer = this.buffers.victory;
    if (!this.ctx || !buffer) return;
    this.fadeOut(0.3);
    const src = this.ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(this.bus);
    src.start();
    this.blockUntil = this.ctx.currentTime + VICTORY_HOLD;
  }

  fadeOut(seconds = FADE) {
    if (!this.current) return;
    const { srcs, gain } = this.current;
    const now = this.ctx.currentTime;
    gain.gain.cancelScheduledValues(now);
    gain.gain.setValueAtTime(gain.gain.value, now);
    gain.gain.linearRampToValueAtTime(0, now + seconds);
    for (const { src } of srcs) src.stop(now + seconds + 0.05);
    this.current = null;
  }

  setEnabled(on) {
    this.enabled = on;
    try {
      localStorage.setItem('bb.music', on ? '1' : '0');
    } catch { /* storage blocked, not important */ }
    if (!this.bus) return;
    const now = this.ctx.currentTime;
    this.bus.gain.cancelScheduledValues(now);
    this.bus.gain.setValueAtTime(this.bus.gain.value, now);
    this.bus.gain.linearRampToValueAtTime(on ? VOLUME : 0, now + 0.3);
  }
}
