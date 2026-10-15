let ctx = null;
let master = null;
let noise = null;
let charge = null;

export function initAudio() {
  if (!ctx) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    ctx = new AC();
    master = ctx.createGain();
    master.gain.value = 0.35;
    master.connect(ctx.destination);
    noise = ctx.createBuffer(1, ctx.sampleRate * 0.5, ctx.sampleRate);
    const d = noise.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
  }
  ctx.resume();
  return ctx;
}

function tone(f0, f1, dur, { type = 'sine', vol = 0.5, delay = 0 } = {}) {
  if (!ctx) return;
  const t = ctx.currentTime + delay;
  const o = ctx.createOscillator();
  const g = ctx.createGain();
  o.type = type;
  o.frequency.setValueAtTime(f0, t);
  o.frequency.exponentialRampToValueAtTime(Math.max(1, f1), t + dur);
  g.gain.setValueAtTime(vol, t);
  g.gain.exponentialRampToValueAtTime(0.001, t + dur);
  o.connect(g).connect(master);
  o.start(t);
  o.stop(t + dur + 0.02);
}

function hiss(dur, freq, vol) {
  if (!ctx) return;
  const t = ctx.currentTime;
  const s = ctx.createBufferSource();
  s.buffer = noise;
  const f = ctx.createBiquadFilter();
  f.type = 'lowpass';
  f.frequency.setValueAtTime(freq, t);
  f.frequency.exponentialRampToValueAtTime(200, t + dur);
  const g = ctx.createGain();
  g.gain.setValueAtTime(vol, t);
  g.gain.exponentialRampToValueAtTime(0.001, t + dur);
  s.connect(f).connect(g).connect(master);
  s.start(t);
  s.stop(t + dur);
}

export const sfx = {
  bump(power, near) {
    const v = Math.min(1, power / 20) * (near ? 0.9 : 0.35);
    tone(240 + Math.random() * 60, 70, 0.18, { type: 'sine', vol: v });
    tone(520, 180, 0.08, { type: 'triangle', vol: v * 0.4 });
  },
  dash(power = 0) {
    hiss(0.18 + power * 0.2, 2500 + power * 2000, 0.25 + power * 0.25);
    tone(300, 600 + power * 500, 0.12 + power * 0.1, { type: 'triangle', vol: 0.15 + power * 0.1 });
  },
  chargeStart() {
    if (!ctx) return;
    sfx.chargeStop();
    const t = ctx.currentTime;
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.type = 'triangle';
    o.frequency.setValueAtTime(180, t);
    o.frequency.linearRampToValueAtTime(620, t + 0.9);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.linearRampToValueAtTime(0.13, t + 0.12);
    o.connect(g).connect(master);
    o.start(t);
    charge = { o, g };
  },
  chargeStop() {
    if (!charge) return;
    const t = ctx.currentTime;
    charge.g.gain.cancelScheduledValues(t);
    charge.g.gain.setValueAtTime(charge.g.gain.value, t);
    charge.g.gain.linearRampToValueAtTime(0.0001, t + 0.05);
    charge.o.stop(t + 0.06);
    charge = null;
  },
  splash(near) {
    hiss(0.45, near ? 3000 : 1400, near ? 0.6 : 0.2);
  },
  ko() {
    [523, 659, 784].forEach((f, i) => tone(f, f, 0.12, { type: 'square', vol: 0.12, delay: i * 0.07 }));
  },
  fell() {
    tone(500, 120, 0.5, { type: 'triangle', vol: 0.3 });
  },
  start() {
    [392, 523, 659, 784].forEach((f, i) => tone(f, f * 1.01, 0.16, { type: 'square', vol: 0.1, delay: i * 0.09 }));
  },
};
