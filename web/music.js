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
    for (const name of ['menu', 'battle', 'final', 'victory']) {
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
    const src = this.ctx.createBufferSource();
    src.buffer = buffer;
    src.loop = true;
    src.loopStart = this.meta[name].loopStart;
    src.loopEnd = this.meta[name].loopEnd;
    const gain = this.ctx.createGain();
    gain.gain.setValueAtTime(0, now);
    gain.gain.linearRampToValueAtTime(1, now + FADE);
    src.connect(gain).connect(this.bus);
    src.start(now);
    this.current = { name, src, gain };
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
    const { src, gain } = this.current;
    const now = this.ctx.currentTime;
    gain.gain.cancelScheduledValues(now);
    gain.gain.setValueAtTime(gain.gain.value, now);
    gain.gain.linearRampToValueAtTime(0, now + seconds);
    src.stop(now + seconds + 0.05);
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
