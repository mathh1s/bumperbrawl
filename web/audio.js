// Sound effects are rendered offline by tools/music/sfx.py and played as buffers.
// Each play nudges the pitch a little so repeated bonks don't sound like a machine gun.

const NAMES = ['bonk', 'bonk_big', 'dash', 'dash_big', 'charge', 'jump', 'land', 'splash', 'fell', 'ko', 'out',
  'start', 'coin', 'pickup', 'pound', 'crown', 'log_land', 'tick', 'click'];

let ctx = null;
let master = null;
const buffers = new Map();
let charge = null;

export function initAudio() {
  if (!ctx) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    ctx = new AC();
    master = ctx.createGain();
    master.gain.value = 0.7;
    master.connect(ctx.destination);
    for (const name of NAMES) load(name);
  }
  ctx.resume();
  return ctx;
}

async function load(name) {
  try {
    const res = await fetch(`sfx/${name}.mp3`);
    const data = await res.arrayBuffer();
    // the callback form also works on older Safari
    buffers.set(name, await new Promise((ok, fail) => ctx.decodeAudioData(data, ok, fail)));
  } catch {
    // a missing effect just stays silent
  }
}

function play(name, { vol = 1, rate = 1, spread = 0.06, delay = 0 } = {}) {
  const buf = buffers.get(name);
  if (!ctx || !buf || vol <= 0) return null;
  const src = ctx.createBufferSource();
  src.buffer = buf;
  src.playbackRate.value = rate * (1 + (Math.random() * 2 - 1) * spread);
  const g = ctx.createGain();
  g.gain.value = vol;
  src.connect(g).connect(master);
  src.start(ctx.currentTime + delay);
  return { src, g };
}

export const sfx = {
  // power runs from about 4 for a nudge to 20+ for a charged hit
  bump(power, near) {
    const k = Math.min(1, power / 20);
    const v = (0.35 + k * 0.65) * (near ? 0.9 : 0.3);
    if (power > 12) play('bonk_big', { vol: v, rate: 1.15 - k * 0.2 });
    else play('bonk', { vol: v, rate: 1.2 - k * 0.3, spread: 0.1 });
  },
  dash(power = 0) {
    if (power > 0.5) play('dash_big', { vol: 0.5 + power * 0.3, rate: 0.9 + power * 0.15, spread: 0.03 });
    else play('dash', { vol: 0.55, spread: 0.1 });
  },
  chargeStart() {
    sfx.chargeStop();
    charge = play('charge', { vol: 0.22, spread: 0 });
  },
  chargeStop() {
    if (!charge) return;
    const t = ctx.currentTime;
    charge.g.gain.setValueAtTime(charge.g.gain.value, t);
    charge.g.gain.linearRampToValueAtTime(0.0001, t + 0.05);
    charge.src.stop(t + 0.06);
    charge = null;
  },
  splash(near) {
    play('splash', { vol: near ? 0.6 : 0.2, spread: 0.1 });
  },
  ko() {
    play('ko', { vol: 0.9, spread: 0 });
  },
  fell() {
    play('fell', { vol: 0.28, spread: 0.04 });
  },
  out() {
    play('out', { vol: 0.5, spread: 0 });
  },
  crown() {
    play('crown', { vol: 0.6, spread: 0 });
  },
  jump() {
    play('jump', { vol: 0.4, spread: 0.08 });
  },
  land() {
    play('land', { vol: 0.35, spread: 0.12 });
  },
  coin() {
    play('coin', { vol: 0.28, spread: 0.02 });
  },
  pickup() {
    play('pickup', { vol: 0.45, spread: 0 });
  },
  pound(near) {
    play('pound', { vol: near ? 0.75 : 0.3, spread: 0.05 });
  },
  logLand() {
    play('log_land', { vol: 0.65, spread: 0.03 });
  },
  start() {
    play('start', { vol: 0.5, spread: 0 });
  },
  tick(last) {
    play('tick', { vol: last ? 0.6 : 0.4, rate: last ? 1.5 : 1, spread: 0 });
  },
  click() {
    play('click', { vol: 0.3, spread: 0.05 });
  },
};
