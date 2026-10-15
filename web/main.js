import * as THREE from 'three';
import { World, makeRamp } from './world.js';
import { Blob, PALETTE, HATS } from './blobs.js';
import { Preview } from './preview.js';
import { FX } from './fx.js';
import { Input } from './input.js';
import { initAudio, sfx } from './audio.js';
import { Music } from './music.js';

const INTERP_MS = 110;
const ARENA_MAX = 15;
const $ = (id) => document.getElementById(id);

// ==== renderer and scene ====

const canvas = $('game');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 600);
camera.position.set(0, 30, 30);

const ramp = makeRamp();
const fx = new FX(scene);
const world = new World(scene, ramp, ARENA_MAX, fx);

function resize() {
  const w = innerWidth, h = innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
addEventListener('resize', resize);
resize();

// ==== state ====

let ws = null;
let myId = null;
let joined = false;
let wantJoin = null;
const roster = new Map();
const blobs = new Map();
const snaps = [];
const pending = [];
let clockOffset = null;
let latest = null;

// ==== network ====

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => {
    setStatus('');
    $('play').disabled = false;
    if (wantJoin) send(wantJoin);
  };
  ws.onmessage = (e) => onMessage(JSON.parse(e.data));
  ws.onclose = () => {
    $('play').disabled = true;
    setStatus('Disconnected, retrying…');
    myId = null;
    snaps.length = 0;
    clockOffset = null;
    setTimeout(connect, 1500);
  };
}

function send(obj) {
  if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

function onMessage(m) {
  switch (m.t) {
    case 'roster':
      roster.clear();
      for (const p of m.p) roster.set(p.i, p);
      for (const [id, b] of blobs) {
        if (!roster.has(id)) { b.dispose(); blobs.delete(id); }
      }
      break;
    case 'welcome':
      myId = m.id;
      joined = true;
      $('menu').hidden = true;
      $('hud').hidden = false;
      $('touch').hidden = !isTouch;
      break;
    case 'full':
      wantJoin = null;
      setStatus('Server is full, try again in a bit.');
      break;
    case 's':
      onSnapshot(m);
      break;
  }
}

function onSnapshot(m) {
  const recv = performance.now();
  const offset = recv - m.now * 1000;
  // track the fastest arrival so jitter only ever delays, never rewinds, the timeline
  if (clockOffset === null || offset < clockOffset) clockOffset = offset;
  else clockOffset += (offset - clockOffset) * 0.01;

  const players = new Map();
  for (const a of m.p) {
    players.set(a[0], { x: a[1], z: a[2], y: a[3], a: a[4], flags: a[5], cd: a[6], score: a[7], ch: a[8] ?? 0 });
  }
  const t = m.now * 1000 + clockOffset;
  const snap = { t, r: m.r, ph: m.ph, tl: m.tl, players };
  snaps.push(snap);
  if (snaps.length > 60) snaps.shift();
  latest = snap;
  for (const e of m.e ?? []) pending.push({ t, e });
}

// ==== interpolation ====

function lerpAngle(a, b, k) {
  let d = b - a;
  while (d > Math.PI) d -= Math.PI * 2;
  while (d < -Math.PI) d += Math.PI * 2;
  return a + d * k;
}

function sample(rt) {
  if (snaps.length === 0) return null;
  while (snaps.length > 2 && snaps[1].t <= rt) snaps.shift();
  const a = snaps[0];
  const b = snaps[1] ?? a;
  const k = b === a ? 0 : THREE.MathUtils.clamp((rt - a.t) / (b.t - a.t), 0, 1);
  const players = new Map();
  for (const [id, pb] of b.players) {
    const pa = a.players.get(id);
    // teleports (respawns) snap instead of sliding across the island
    if (!pa || Math.hypot(pb.x - pa.x, pb.z - pa.z) > 4) {
      players.set(id, pb);
      continue;
    }
    players.set(id, {
      x: pa.x + (pb.x - pa.x) * k,
      z: pa.z + (pb.z - pa.z) * k,
      y: pa.y + (pb.y - pa.y) * k,
      a: lerpAngle(pa.a, pb.a, k),
      flags: k < 0.5 ? pa.flags : pb.flags,
      cd: pb.cd,
      score: pb.score,
      ch: pa.ch + (pb.ch - pa.ch) * k,
    });
  }
  return { r: a.r + (b.r - a.r) * k, ph: b.ph, tl: b.tl, players };
}

// ==== events ====

function nameOf(id) {
  return roster.get(id)?.n ?? '???';
}

function playerPos(id, view) {
  return view?.players.get(id);
}

function fireEvents(rt, view) {
  while (pending.length && pending[0].t <= rt) {
    const { e } = pending.shift();
    const me = myId !== null ? playerPos(myId, view) : null;
    switch (e.k) {
      case 'b': {
        fx.bump(e.x, e.z, e.p);
        for (const [id, b] of blobs) {
          const p = playerPos(id, view);
          if (p && Math.hypot(p.x - e.x, p.z - e.z) < 1.4) b.bump(e.p);
        }
        const near = me ? Math.hypot(me.x - e.x, me.z - e.z) < 2 : false;
        if (joined) sfx.bump(e.p, near);
        break;
      }
      case 'ko': {
        addFeed(e.a, e.v);
        if (!joined) break;
        if (e.v === myId) {
          banner(e.a ? `Bonked!<small>by ${esc(nameOf(e.a))}</small>` : 'Splash!<small>you fell off</small>', 1600);
          sfx.fell();
        } else if (e.a === myId) {
          banner(`+1<small>bonked ${esc(nameOf(e.v))}</small>`, 1100);
          sfx.ko();
        }
        break;
      }
      case 'start':
        if (joined) { banner('Brawl!', 1200); sfx.start(); }
        break;
      case 'end':
        if (joined) {
          banner(e.w ? `${esc(e.w)} wins!<small>${e.s} bonk${e.s === 1 ? '' : 's'}</small>` : 'Round over!<small>nobody takes it</small>', 4000);
          music.victory();
        }
        break;
    }
  }
}

// ==== hud ====

const isTouch = matchMedia('(pointer: coarse)').matches;
if (isTouch) document.body.classList.add('touch');

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

function setStatus(s) {
  $('status').textContent = s;
}

let bannerTimer = 0;
function banner(html, ms) {
  const el = $('banner');
  el.innerHTML = html;
  el.classList.add('show');
  clearTimeout(bannerTimer);
  bannerTimer = setTimeout(() => el.classList.remove('show'), ms);
}

function addFeed(a, v) {
  if (!joined) return;
  const li = document.createElement('li');
  li.innerHTML = a
    ? `<b>${esc(nameOf(a))}</b> bonked <b>${esc(nameOf(v))}</b>`
    : `<b>${esc(nameOf(v))}</b> fell off`;
  const feed = $('feed');
  feed.prepend(li);
  while (feed.children.length > 5) feed.lastChild.remove();
  setTimeout(() => li.classList.add('fade'), 4000);
  setTimeout(() => li.remove(), 4600);
}

let hudTimer = 0;
function updateHud(dt, view) {
  if (!joined || !latest) return;
  const me = latest.players.get(myId);
  if (me) {
    const charging = (me.flags & 8) !== 0;
    $('dashRing').style.strokeDashoffset = String(119.4 * (charging ? 1 - me.ch : me.cd));
    $('dash').classList.toggle('ready', me.cd === 0 && !charging);
    $('dash').classList.toggle('charging', charging);
    $('dashBtn').style.setProperty('--fill', String(charging ? me.ch : 0));
    $('dashBtn').classList.toggle('cool', me.cd > 0);
  }

  hudTimer -= dt;
  if (hudTimer > 0) return;
  hudTimer = 0.2;

  const tl = Math.ceil(latest.tl);
  $('time').textContent = `${Math.floor(tl / 60)}:${String(tl % 60).padStart(2, '0')}`;
  const crumbling = latest.ph === 0 && view && view.r < ARENA_MAX - 0.01;
  $('phase').textContent = latest.ph === 1 ? 'Next round' : crumbling ? 'Island crumbling' : 'Round';
  $('timer').classList.toggle('crumble', !!crumbling);

  const rows = [...latest.players.entries()]
    .filter(([id]) => roster.has(id))
    .sort((a, b) => b[1].score - a[1].score)
    .slice(0, 8);
  $('board').innerHTML = rows.map(([id, p]) => {
    const r = roster.get(id);
    return `<li class="${id === myId ? 'me' : ''}"><span class="dot" style="background:${PALETTE[r.c]}"></span>`
      + `<span class="nm">${esc(r.n)}</span>${r.b ? '<span class="bot">bot</span>' : ''}<span class="sc">${p.score}</span></li>`;
  }).join('');
}

// ==== input ====

function dashReady() {
  const me = latest?.players.get(myId);
  return me && me.cd === 0 && !(me.flags & 4) ? me : null;
}

const input = new Input({
  onDashDown() {
    if (!joined) return;
    if (dashReady()) sfx.chargeStart();
    send({ t: 'charge' });
  },
  onDashUp() {
    if (!joined) return;
    sfx.chargeStop();
    const me = dashReady();
    if (me) {
      sfx.dash(me.flags & 8 ? me.ch : 0);
      const b = blobs.get(myId);
      if (b) fx.puff(b.group.position.x, b.group.position.z);
    }
    send({ t: 'dash' });
  },
});
if (isTouch) input.bindTouch({ pad: $('pad'), stick: $('stick'), knob: $('knob'), dashBtn: $('dashBtn'), canvas });

let lastSent = { x: 0, z: 0 };
let sendClock = 0;
let keepAlive = 0;
function pumpInput(dt) {
  sendClock += dt;
  keepAlive += dt;
  if (!joined || sendClock < 1 / 30) return;
  sendClock = 0;
  const v = input.vector();
  if (Math.hypot(v.x - lastSent.x, v.z - lastSent.z) > 0.03 || keepAlive > 0.5) {
    send({ t: 'in', x: +v.x.toFixed(3), z: +v.z.toFixed(3) });
    lastSent = v;
    keepAlive = 0;
  }
}

// ==== menu ====

let chosenColor = Math.floor(Math.random() * PALETTE.length);
let chosenHat = Math.floor(Math.random() * HATS.length);
try {
  $('name').value = localStorage.getItem('bb.name') ?? '';
  const c = localStorage.getItem('bb.color');
  const h = localStorage.getItem('bb.hat');
  if (c !== null) chosenColor = Number(c) % PALETTE.length;
  if (h !== null) chosenHat = Number(h) % HATS.length;
} catch { /* storage blocked, keep random picks */ }

const preview = new Preview($('preview'), ramp);
function refreshLook() {
  $('hatName').textContent = HATS[chosenHat];
  preview.set(chosenColor, chosenHat);
}

const colorsEl = $('colors');
PALETTE.forEach((c, i) => {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'swatch';
  b.style.background = c;
  b.setAttribute('aria-label', `Color ${i + 1}`);
  b.setAttribute('aria-pressed', String(i === chosenColor));
  b.onclick = () => {
    chosenColor = i;
    [...colorsEl.children].forEach((el, k) => el.setAttribute('aria-pressed', String(k === i)));
    refreshLook();
  };
  colorsEl.append(b);
});
$('hatPrev').onclick = () => { chosenHat = (chosenHat + HATS.length - 1) % HATS.length; refreshLook(); };
$('hatNext').onclick = () => { chosenHat = (chosenHat + 1) % HATS.length; refreshLook(); };
refreshLook();

// ==== audio ====

const music = new Music();
// browsers only allow audio after a gesture; touchend and click are the ones iOS accepts
function unlockAudio() {
  music.init(initAudio());
}
for (const type of ['pointerup', 'touchend', 'click', 'keydown']) document.addEventListener(type, unlockAudio, true);

function renderMusicButton() {
  $('musicBtn').classList.toggle('off', !music.enabled);
  $('musicBtn').setAttribute('aria-pressed', String(music.enabled));
}
$('musicBtn').addEventListener('click', () => {
  music.setEnabled(!music.enabled);
  renderMusicButton();
});
renderMusicButton();

function pickTrack(view) {
  if (!joined || !view || view.ph === 1) return 'menu';
  return view.tl <= 30 ? 'final' : 'battle';
}

$('play').disabled = true;
$('joinForm').addEventListener('submit', (e) => {
  e.preventDefault();
  const name = $('name').value.trim();
  try {
    localStorage.setItem('bb.name', name);
    localStorage.setItem('bb.color', String(chosenColor));
    localStorage.setItem('bb.hat', String(chosenHat));
  } catch { /* storage blocked, not important */ }
  wantJoin = { t: 'join', n: name, c: chosenColor, h: chosenHat };
  send(wantJoin);
  $('name').blur();
});

// ==== camera ====

const camTarget = new THREE.Vector3();
const lookAt = new THREE.Vector3();
let menuAngle = 0;

// Low three-quarter view so the horizon stays on screen; portrait screens pull back to keep the island in frame
function updateCamera(dt, view) {
  const portrait = camera.aspect < 1;
  const dist = portrait ? 1.6 : 1;
  const me = joined && view ? view.players.get(myId) : null;
  if (me) {
    if (!(me.flags & 4)) camTarget.set(me.x * 0.6, 0, me.z * 0.6);
    const k = 1 - Math.exp(-dt * 4);
    camera.position.lerp(new THREE.Vector3(camTarget.x, 12 * dist, camTarget.z + 17 * dist), k);
    lookAt.lerp(new THREE.Vector3(camTarget.x, 0, camTarget.z - 2), k);
  } else {
    menuAngle += dt * 0.06;
    camera.position.set(Math.sin(menuAngle) * 36 * dist, 13 * dist, Math.cos(menuAngle) * 36 * dist);
    lookAt.set(0, 1, 0);
  }
  camera.lookAt(lookAt);
}

// ==== loop ====

let last = performance.now();
let t = 0;

function frame(now) {
  requestAnimationFrame(frame);
  const dt = Math.min(0.05, (now - last) / 1000);
  last = now;
  t += dt;

  const rt = now - INTERP_MS;
  const view = sample(rt);
  fireEvents(rt, view);

  if (view) {
    for (const [id, s] of view.players) {
      const info = roster.get(id);
      if (!info) continue;
      let b = blobs.get(id);
      if (!b) {
        b = new Blob({ name: info.n, color: info.c, hat: info.h, me: id === myId, ramp });
        blobs.set(id, b);
        scene.add(b.group);
      }
      if (s.flags & 8 && s.ch > 0.95 && Math.random() < dt * 14) {
        const a = Math.random() * Math.PI * 2;
        fx.burst(s.x + Math.sin(a) * 0.9, 0.4 + Math.random(), s.z + Math.cos(a) * 0.9, { colors: ['#ffd43b', '#fff6c4'], n: 2, speed: 0.6, up: 2, size: 0.09, life: 0.4, gravity: 2 });
      }
      if (b.update(s, dt, t) === 'splash') {
        fx.splash(s.x, s.z, 1.2);
        if (joined) {
          const me = view.players.get(myId);
          sfx.splash(id === myId || (me && Math.hypot(me.x - s.x, me.z - s.z) < 8));
        }
      }
    }
    for (const [id, b] of blobs) b.group.visible = view.players.has(id);
  }

  world.update(dt, view?.r ?? null, camera);
  fx.update(dt);
  pumpInput(dt);
  updateCamera(dt, view);
  updateHud(dt, view);
  music.play(pickTrack(view));
  renderer.render(scene, camera);
  if (!joined) preview.render(dt);
}

// labels are drawn to canvas once, so wait for the font before any blob exists
document.fonts.load('600 38px Fredoka').catch(() => {}).finally(() => {
  connect();
  requestAnimationFrame(frame);
});
