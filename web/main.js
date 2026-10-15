import * as THREE from 'three';
import { World, makeRamp } from './world.js';
import { Blob, PALETTE, HATS, FREE_HATS, HAT_PRICES } from './blobs.js';
import { Preview } from './preview.js';
import { Podium } from './podium.js';
import { Sweeper } from './sweeper.js';
import { HillRing } from './hill.js';
import { Coins } from './coins.js';
import { BallPitch } from './ball.js';
import { Bubbles, EMOTES } from './emotes.js';
import { TimeWarp } from './timewarp.js';
import { FX } from './fx.js';
import { Crates, POWERS } from './crates.js';
import { modeOf, OUT, TEAMS } from './modes.js';
import { Input } from './input.js';
import { initAudio, sfx } from './audio.js';
import { Predictor } from './predict.js';
import { Music } from './music.js';
import { LobbyPanel } from './lobby.js';
import { esc } from './text.js';
import { tierBadge, tierOf, playerKey } from './rank.js';

const INTERP_MS = 110;
const ARENA_MAX = 15;
const $ = (id) => document.getElementById(id);

const requestedRoom = (new URLSearchParams(location.search).get('room') ?? '').toUpperCase();
const ROOM = /^[A-Z]{4,6}$/.test(requestedRoom) ? requestedRoom : '';

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
const crates = new Crates(scene, ramp);
const podium = new Podium(ramp);
const sweeper = new Sweeper(scene, ramp, fx);
const hillRing = new HillRing(scene);
const coins = new Coins(scene, ramp);
const pitch = new BallPitch(scene, ramp);
const bubbles = new Bubbles($('bubbles'));
const bubbleVec = new THREE.Vector3();
const warp = new TimeWarp();
// the last knockout, so a round that ends on one can replay it slowly
let lastKo = null;
let focus = null;
const lastScores = new Map();
const arrowPos = new THREE.Vector3();
sweeper.onLand = () => {
  shake = 0.5;
  if (joined) sfx.logLand();
};

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
let predictor = null;
let roomState = null;

// ==== network ====

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws${ROOM ? `?room=${ROOM}` : ''}`);
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
    predictor = null;
    roomState = null;
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
    case 'roster': {
      const before = new Map(roster);
      roster.clear();
      for (const p of m.p) roster.set(p.i, p);
      for (const [id, p] of roster) {
        if (!before.has(id) && !p.b && id !== myId && before.size) addFeed(`<b>${esc(p.n)}</b> joined`);
      }
      for (const [id, p] of before) {
        if (!roster.has(id) && !p.b) addFeed(`<b>${esc(p.n)}</b> left`);
      }
      for (const [id, b] of blobs) {
        if (!roster.has(id)) { b.dispose(); blobs.delete(id); }
      }
      renderLobby();
      renderWho();
      break;
    }
    case 'rank': {
      const d = m.new - m.old;
      const t = tierOf(m.new);
      addFeed(`Rating <b>${m.new}</b> (${d >= 0 ? '+' : ''}${d})${tierOf(m.old) !== t ? ` · now <b>${t.name}</b>!` : ''}`);
      break;
    }
    case 'crowns':
      profile.crowns = m.total;
      $('crowns').querySelector('b').textContent = m.total;
      addFeed(`+${m.got} 👑 for that match`);
      break;
    case 'kicked':
      backToMenu('The host removed you from the room.');
      break;
    case 'room':
      roomState = m;
      renderLobby();
      break;
    case 'welcome':
      myId = m.id;
      joined = true;
      predictor = new Predictor(m.cfg.mv, send);
      $('menu').hidden = true;
      $('hud').hidden = false;
      $('touch').hidden = !isTouch;
      break;
    case 'full':
      wantJoin = null;
      setStatus(m.why === 'rooms' ? 'Too many rooms open right now, try the public one.' : 'This room is full, try again in a bit.');
      break;
    case 's':
      onSnapshot(m);
      break;
    case 'me':
      if (predictor) {
        predictor.setFlags(latest?.players.get(myId)?.flags ?? 0);
        predictor.reconcile(m);
      }
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
    players.set(a[0], { x: a[1], z: a[2], y: a[3], a: a[4], flags: a[5], cd: a[6], score: a[7], ch: a[8] ?? 0, pw: a[9] ?? 0, wins: a[10] ?? 0, team: a[11] ?? 0 });
  }
  const t = m.now * 1000 + clockOffset;
  const snap = { t, r: m.r, ph: m.ph, tl: m.tl, players, crates: m.c ?? [], cw: m.cw ?? 0, sw: m.sw, md: m.md ?? 0, rn: m.rn ?? 1, rm: m.rm ?? 1, fm: m.fm ?? 0, kq: m.kq ?? 0, fin: !!m.fin, hl: m.hl, co: m.co, bl: m.bl, pt: !!m.pt, hx: m.hx };
  snaps.push(snap);
  if (snaps.length > 60) snaps.shift();
  const phaseChanged = latest?.ph !== snap.ph;
  latest = snap;
  if (phaseChanged) renderWho();
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
      pw: pb.pw,
      team: pb.team,
    });
  }
  const sw = a.sw && b.sw ? [lerpAngle(a.sw[0], b.sw[0], k), a.sw[1] + (b.sw[1] - a.sw[1]) * k] : b.sw;
  // the ball snaps on kickoff instead of sliding back from the goal
  let bl = b.bl;
  if (a.bl && b.bl && !a.bl[3] && !b.bl[3] && Math.hypot(b.bl[0] - a.bl[0], b.bl[1] - a.bl[1]) < 4) {
    bl = [a.bl[0] + (b.bl[0] - a.bl[0]) * k, a.bl[1] + (b.bl[1] - a.bl[1]) * k, a.bl[2] + (b.bl[2] - a.bl[2]) * k, 0, b.bl[4], b.bl[5]];
  }
  return { r: a.r + (b.r - a.r) * k, ph: b.ph, tl: b.tl, players, crates: b.crates, cw: b.cw, sw, hl: b.hl, co: b.co, bl, pt: b.pt, hx: b.hx };
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
        // a big hit you're part of freezes the picture for a few frames, so it lands
        if (joined && near && e.p >= 16) {
          warp.hitStop(performance.now(), 75);
          shake = Math.max(shake, 0.35);
        }
        break;
      }
      case 'ko': {
        lastKo = { id: e.v, rt };
        const a = `<b>${esc(nameOf(e.a))}</b>`, v = `<b>${esc(nameOf(e.v))}</b>`;
        addFeed(!e.a ? `${v} fell off` : e.cr ? `${a} dethroned ${v} <span class="bounty">+2</span>` : `${a} bonked ${v}`);
        if (!joined || podium.active) break;
        if (e.v === myId) {
          banner(e.a ? `Bonked!<small>by ${esc(nameOf(e.a))}</small>` : 'Splash!<small>you fell off</small>', 1600);
          sfx.fell();
        } else if (e.a === myId) {
          if (latest?.md === 0) banner(e.cr ? `+2<small>you dethroned ${esc(nameOf(e.v))}</small>` : `+1<small>bonked ${esc(nameOf(e.v))}</small>`, 1100);
          else banner(`Bonk!<small>you knocked off ${esc(nameOf(e.v))}</small>`, 1100);
          sfx.ko();
        }
        break;
      }
      case 'out':
        addFeed(`<b>${esc(nameOf(e.i))}</b> is out!`);
        if (joined && e.i === myId) {
          banner('You\'re out!<small>watch who survives</small>', 2200);
          sfx.out();
        }
        break;
      case 'crown':
        addFeed(`<b>${esc(nameOf(e.i))}</b> takes the crown`);
        if (joined && e.i === myId) {
          banner('Crowned!<small>everyone is after you now</small>', 1500);
          sfx.crown();
        }
        break;
      case 'pk': {
        const p = playerPos(e.i, view);
        const info = POWERS[e.c];
        if (p && info) {
          fx.pickup(p.x, p.z, info.color);
          fx.text(p.x, 3.4, p.z, `${info.name}!`, info.color);
        }
        if (joined) sfx.pickup();
        if (e.i === myId && info) banner(`${info.name}!<small>${info.blurb}</small>`, 1200);
        break;
      }
      case 'pd': {
        fx.pound(e.x, e.z);
        for (const [id, b] of blobs) {
          const p = playerPos(id, view);
          if (p && id !== e.i && Math.hypot(p.x - e.x, p.z - e.z) < 4.5) b.bump(14);
        }
        const near = me ? Math.hypot(me.x - e.x, me.z - e.z) < 7 : false;
        if (joined) sfx.pound(near);
        if (near) shake = 0.7;
        break;
      }
      case 'sws':
        if (joined) banner(`Log incoming!<small>${isTouch ? 'tap Jump' : 'press Space'} to hop over it</small>`, 2200);
        break;
      case 'swh': {
        fx.bump(e.x, e.z, 10);
        for (const [id, b] of blobs) {
          const p = playerPos(id, view);
          if (p && Math.hypot(p.x - e.x, p.z - e.z) < 1.2) b.bump(16);
        }
        if (joined) sfx.bump(16, me ? Math.hypot(me.x - e.x, me.z - e.z) < 2 : false);
        break;
      }
      case 'cp': {
        fx.burst(e.x, 0.6, e.z, { colors: ['#ffd43b', '#fff6c4'], n: 8, speed: 2.5, up: 4, size: 0.1, life: 0.45 });
        if (e.i === myId) {
          const p = playerPos(e.i, view);
          if (p) fx.text(p.x, 3.3, p.z, '+1', '#ffd43b');
        }
        if (joined && (e.i === myId || (me && Math.hypot(me.x - e.x, me.z - e.z) < 6))) sfx.coin();
        break;
      }
      case 'spill':
        coins.spill(e.ids, e.x, e.z);
        if (e.i === myId && joined) banner(`-${e.ids.length}<small>your coins went flying</small>`, 1400);
        break;
      case 'em':
        // your own bubble already went up when you pressed the key
        if (e.i !== myId) bubbles.show(e.i, e.e);
        break;
      case 'goal': {
        const team = TEAMS[e.t];
        const by = e.by ? nameOf(e.by) : null;
        fx.burst(e.x, 1.5, e.z, { colors: [team.color, '#ffffff', '#ffd43b'], n: 40, speed: 7, up: 8, size: 0.16, life: 1.2 });
        addFeed(by ? `<b>${esc(by)}</b> ${e.own ? 'scored an own goal' : 'scored'} for ${team.name}` : `Goal for ${team.name}`);
        if (!joined) break;
        const mine = latest?.players.get(myId)?.team === e.t;
        banner(`GOAL!<small>${by ? `${esc(by)} for ` : ''}${team.name}</small>`, 2000);
        sfx.start();
        if (mine) sfx.crown();
        shake = 0.4;
        break;
      }
      case 'bw':
        fx.dust(e.x, 0.6, e.z);
        if (joined && me && Math.hypot(me.x - e.x, me.z - e.z) < 6) sfx.bump(e.p * 2, false);
        break;
      case 'hm':
        fx.ring(e.x, e.z, '#ffffff', 3.5);
        break;
      case 'cg':
        fx.dust(e.x, 0.4, e.z);
        break;
      case 'lobby':
        podium.hide();
        hideAwards();
        lastEnd = null;
        $('standings').hidden = true;
        document.body.classList.remove('standings');
        if (joined) banner('Back to the lobby<small>ready up for another match</small>', 2600);
        break;
      case 'start': {
        podium.hide();
        hideAwards();
        lastEnd = null;
        $('standings').hidden = true;
        document.body.classList.remove('standings');
        const mode = modeOf(e.m);
        if (joined) {
          const team = e.m === 4 ? TEAMS[latest?.players.get(myId)?.team] : null;
          const side = team ? `<br>You're on <span style="color:${team.color}">${team.name}</span>` : '';
          banner(`<small>${roundLabel(e)}</small>${mode.name}<small>${mode.rule}${side}</small>`, 3600);
          sfx.start();
        }
        break;
      }
      case 'end': {
        lastEnd = e;
        // a round decided by a knockout plays that fall in slow motion, close up, before the results
        const replay = lastKo && rt - lastKo.rt < 1200;
        if (replay) {
          warp.slowMo(performance.now(), 1300, 0.3);
          focus = { id: lastKo.id, until: performance.now() + 1700 };
        }
        lastKo = null;
        if (!joined) break;
        const mode = modeOf(e.m);
        let text;
        if (e.mo && e.fm === KNOCKOUT) {
          text = e.ch ? `${esc(e.ch)} ${verb(e.ch)} the show!<small>last blob standing in the final</small>` : 'Show over!<small>nobody survived the final</small>';
        } else if (e.mo) {
          text = e.ch ? `${esc(e.ch)} ${verb(e.ch)} the match!<small>most rounds won</small>` : 'Match over!<small>nobody won a round</small>';
        } else if (e.fm === KNOCKOUT) {
          // qualifying rounds are about who goes through, so that is all the banner says
          addFeed(`${e.q.length} qualified, ${e.x.length} eliminated`);
          if (e.q.includes(myId)) {
            banner('Qualified!<small>on to the next round</small>', 3500);
            sfx.crown();
          } else if (e.x.includes(myId)) {
            banner('Eliminated!<small>stick around and watch the rest</small>', 3500);
            sfx.out();
          }
          showStandings(e.st ?? [], false);
          break;
        } else {
          text = e.w ? `${esc(e.w)} ${verb(e.w)} round ${e.r}!<small>${mode.unit(e.s)}</small>` : `Round ${e.r} over!<small>nobody scored</small>`;
        }
        const reveal = () => {
          // a new round may already have started if the break was cut short
          if (lastEnd !== e) return;
          if (e.top?.length) {
            podium.show(e.top, e.mo ? '★' : '');
            banner(text, e.mo ? 9000 : 6500, 'high');
          } else {
            banner(text, 4000);
          }
          showStandings(e.st ?? [], e.mo);
          if (e.mo) showAwards(e.aw ?? []);
          music.victory();
        };
        if (replay) setTimeout(reveal, 1500);
        else reveal();
        break;
      }
    }
  }
}

// ==== hud ====

const isTouch = matchMedia('(pointer: coarse)').matches;
if (isTouch) document.body.classList.add('touch');

function setStatus(s) {
  $('status').textContent = s;
}

let bannerTimer = 0;
function banner(html, ms, cls = '') {
  const el = $('banner');
  el.innerHTML = html;
  el.className = cls;
  el.classList.add('show');
  clearTimeout(bannerTimer);
  bannerTimer = setTimeout(() => el.classList.remove('show'), ms);
}

function addFeed(html) {
  if (!joined) return;
  const li = document.createElement('li');
  li.innerHTML = html;
  const feed = $('feed');
  feed.prepend(li);
  while (feed.children.length > 5) feed.lastChild.remove();
  setTimeout(() => li.classList.add('fade'), 4000);
  setTimeout(() => li.remove(), 4600);
}

let lastEnd = null;

const KNOCKOUT = 1;

function roundLabel({ r, of, fm, kq, fin }) {
  if (fm !== KNOCKOUT) return `Round ${r} of ${of}`;
  return fin ? 'The final' : `Round ${r} · top ${kq} go through`;
}

// the server joins co-winners with an ampersand
const verb = (who) => (who.includes(' & ') ? 'win' : 'wins');

function showStandings(list, final) {
  const el = $('standings');
  el.hidden = !list.some((p) => p.w > 0);
  document.body.classList.toggle('standings', !el.hidden);
  el.querySelector('h3').textContent = final ? 'Final standings' : 'Match standings';
  el.querySelector('ol').innerHTML = list.slice(0, 6).map((p) =>
    `<li class="${p.i === myId ? 'me' : ''}"><span class="dot" style="background:${PALETTE[p.c]}"></span>`
    + `<span class="nm">${esc(p.n)}</span><span class="stars">${'★'.repeat(Math.min(p.w, 5))}${p.w > 5 ? `×${p.w}` : ''}</span></li>`,
  ).join('');
}

// silly titles from the match, dealt onto the podium screen one after another
function showAwards(list) {
  const el = $('awards');
  el.hidden = !list.length;
  document.body.classList.toggle('awards', list.length > 0);
  el.innerHTML = list.map((a, i) =>
    `<li style="animation-delay:${1.2 + i * 0.45}s" class="${a.i === myId ? 'me' : ''}">`
    + `<b>${esc(a.t)}</b><span class="who"><span class="dot" style="background:${PALETTE[a.c]}"></span>${esc(a.n)}</span>`
    + `<small>${esc(a.d)}</small></li>`,
  ).join('');
}

function hideAwards() {
  $('awards').hidden = true;
  document.body.classList.remove('awards');
}

const CROWN_SVG = '<svg class="crown" viewBox="0 0 24 18"><path d="M2 16h20l1-11-6 4-5-8-5 8-6-4z"/></svg>';

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

    const kind = me.flags & 16 ? 1 : me.flags & 32 ? 2 : 0;
    $('power').hidden = !kind;
    if (kind) {
      $('power').style.setProperty('--c', POWERS[kind].color);
      $('powerName').textContent = POWERS[kind].name;
      $('powerBar').style.width = `${Math.min(100, (me.pw / (kind === 1 ? 6 : 8)) * 100)}%`;
    }
  }

  hudTimer -= dt;
  if (hudTimer > 0) return;
  hudTimer = 0.2;

  const tl = Math.ceil(latest.tl);
  countdownTick(tl);
  const inLobby = latest.ph === 2;
  $('timer').hidden = inLobby;
  $('board').hidden = inLobby;
  renderLobby();
  if (inLobby) return;
  $('time').textContent = `${Math.floor(tl / 60)}:${String(tl % 60).padStart(2, '0')}`;
  const crumbling = latest.ph === 0 && view && view.r < ARENA_MAX - 0.01;
  $('phase').textContent = latest.ph === 1
    ? (lastEnd?.mo ? (ROOM ? 'Lobby in' : 'New match in') : 'Next round')
    : `${roundLabel({ r: latest.rn, of: latest.rm, fm: latest.fm, kq: latest.kq, fin: latest.fin })} · ${
      latest.bl ? `Red ${latest.bl[4]} : ${latest.bl[5]} Blue` : modeOf(latest.md).name}`;
  $('timer').classList.toggle('crumble', !!crumbling);

  const rows = [...latest.players.entries()]
    .filter(([id]) => roster.has(id))
    .sort((a, b) => b[1].score - a[1].score || b[1].wins - a[1].wins)
    .slice(0, 8);
  const roomRow = ROOM ? `<li class="room" data-invite>Room <b>${ROOM}</b> · invite</li>` : '';
  $('board').innerHTML = roomRow + rows.map(([id, p]) => {
    const r = roster.get(id);
    const crown = id === latest.cw ? CROWN_SVG : '';
    const wins = p.wins ? `<span class="wins">★${p.wins}</span>` : '';
    return `<li class="${id === myId ? 'me' : ''}"><span class="dot" style="background:${PALETTE[r.c]}"></span>`
      + `<span class="nm">${esc(r.n)}</span>${r.r ? tierBadge(r.r) : ''}${crown}${r.b ? '<span class="bot">bot</span>' : ''}${wins}`
      + `<span class="sc">${p.flags & OUT ? '<span class="out">out</span>' : modeOf(latest.md).cell(p)}</span></li>`;
  }).join('');
}

// ==== input ====

const input = new Input({
  onDashDown() {
    if (!predictor) return;
    if (predictor.canDash()) sfx.chargeStart();
    predictor.press('charge');
  },
  onJump() {
    if (!predictor) return;
    if (predictor.canJump()) sfx.jump();
    predictor.press('jump');
  },
  onDashUp() {
    if (!predictor) return;
    sfx.chargeStop();
    if (predictor.canDash()) {
      const st = predictor.st;
      sfx.dash(st.charging ? st.chargeT / predictor.c.chargeMax : 0);
      const b = blobs.get(myId);
      if (b) fx.puff(b.group.position.x, b.group.position.z);
    }
    predictor.press('dash');
  },
});
if (isTouch) input.bindTouch({ pad: $('pad'), stick: $('stick'), knob: $('knob'), dashBtn: $('dashBtn'), jumpBtn: $('jumpBtn'), canvas });

// your own blob is drawn where the predictor has it, not where the last snapshot did
function applyPrediction(view) {
  const pv = predictor?.view();
  const s = view?.players.get(myId);
  if (!pv || !s) return;
  let flags = s.flags & ~(1 | 8);
  if (pv.charging) flags |= 8;
  if (pv.dashing) flags |= 1;
  view.players.set(myId, { ...s, x: pv.x, y: pv.y, z: pv.z, a: pv.a, ch: pv.ch, flags });
}

// ==== emotes ====

let emoteReady = 0;
function sendEmote(i) {
  if (!joined || performance.now() < emoteReady) return;
  // matches the server cooldown, so a bubble shown here is one the others see too
  emoteReady = performance.now() + 1250;
  bubbles.show(myId, i);
  send({ t: 'emote', i });
  sfx.click();
  showEmotePicker(false);
}

function showEmotePicker(open) {
  $('emotePicker').hidden = !open;
  $('emoteBtn').setAttribute('aria-expanded', String(open));
}

$('emotePicker').innerHTML = EMOTES.map((t, i) => `<button type="button" role="menuitem" data-e="${i}"><kbd>${i + 1}</kbd>${t}</button>`).join('');
$('emotePicker').addEventListener('click', (e) => {
  const b = e.target.closest('[data-e]');
  if (b) sendEmote(Number(b.dataset.e));
});
$('emoteBtn').addEventListener('click', () => showEmotePicker($('emotePicker').hidden));
addEventListener('keydown', (e) => {
  if (e.target instanceof HTMLInputElement || e.repeat) return;
  const n = Number(e.key);
  if (n >= 1 && n <= EMOTES.length) sendEmote(n - 1);
  if (e.key === 'Escape') showEmotePicker(false);
});

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
// what you own comes from the server; until it answers only the free hats count
let profile = { crowns: 0, owned: [] };
const owns = (hat) => hat < FREE_HATS || profile.owned.includes(hat);

function refreshLook() {
  const locked = !owns(chosenHat);
  $('hatName').innerHTML = `${HATS[chosenHat]}${locked ? '<span class="lock" aria-label="locked">🔒</span>' : ''}`;
  const price = HAT_PRICES[chosenHat - FREE_HATS];
  $('unlockBtn').hidden = !locked;
  if (locked) {
    const short = price - profile.crowns;
    $('unlockBtn').disabled = short > 0;
    $('unlockBtn').textContent = short > 0 ? `Unlock for 👑 ${price} (${short} more to go)` : `Unlock for 👑 ${price}`;
  }
  preview.set(chosenColor, chosenHat);
}

function showProfile(p) {
  profile = { crowns: p.crowns ?? 0, owned: p.owned ?? [] };
  $('crowns').querySelector('b').textContent = profile.crowns;
  $('myRank').innerHTML = p.rated ? `${tierBadge(p.r)} #${p.pos}` : '';
  refreshLook();
}

async function loadProfile() {
  try {
    const res = await fetch('/api/me', { method: 'POST', body: JSON.stringify({ k: playerKey() }) });
    showProfile(await res.json());
  } catch {
    // the menu still works with the free hats
  }
}

$('unlockBtn').addEventListener('click', async () => {
  try {
    const res = await fetch('/api/buy', { method: 'POST', body: JSON.stringify({ k: playerKey(), hat: chosenHat }) });
    const body = await res.json();
    if (!res.ok) {
      setStatus(body.error === 'no profile' ? 'Finish a match first to start earning crowns.' : `Couldn't unlock it: ${body.error}.`);
      return;
    }
    showProfile(body);
    sfx.crown();
  } catch {
    setStatus('Could not reach the server, try again.');
  }
});

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

// ticks for the last seconds of a round and of the break before the next one
let lastTick = null;
function countdownTick(tl) {
  const from = latest.ph === 1 ? 3 : 5;
  const key = `${latest.ph}:${tl}`;
  if (!joined || tl < 1 || tl > from || key === lastTick) return;
  lastTick = key;
  sfx.tick(tl === 1);
  if (latest.ph === 2) banner(`<small>Match starts in</small>${tl}`, 900);
}

document.addEventListener('click', (e) => {
  if (e.target.closest('button')) sfx.click();
});

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
  if (!joined || !view || view.ph !== 0) return 'menu';
  if (view.tl <= 30) return 'final';
  // the two round themes take turns so a match doesn't loop one song
  return (latest?.rn ?? 1) % 2 ? 'jam' : 'wobble';
}

// ==== rooms ====

const lobbyPanel = new LobbyPanel($('lobby'), { send, onInvite: invite });

function renderLobby() {
  const show = joined && !!roomState && latest?.ph === 2;
  $('lobby').hidden = !show;
  document.body.classList.toggle('lobby', show);
  if (!show) return;
  const countdown = roomState.counting ? Math.max(1, Math.ceil(latest.tl)) : null;
  lobbyPanel.render({ room: roomState, roster, myId, code: ROOM, countdown });
}

async function invite() {
  const url = `${location.origin}/?room=${ROOM}`;
  try {
    if (navigator.share) {
      await navigator.share({ title: 'Bumper Brawl', text: `Join my Bumper Brawl room ${ROOM}`, url });
      return;
    }
    await navigator.clipboard.writeText(url);
    flashInvite('Link copied!');
  } catch (err) {
    // a dismissed share sheet is not an error worth showing
    if (err?.name !== 'AbortError') flashInvite(url);
  }
}

function flashInvite(text) {
  if (joined) banner(`<small>${esc(text)}</small>`, 1400);
  else setStatus(text);
}

if (ROOM) {
  $('publicRooms').hidden = true;
  $('ranksBtn').hidden = true;
  $('roomInfo').hidden = false;
  $('leaveRoom').hidden = false;
  $('roomCode').innerHTML = [...ROOM].map((c) => `<span>${c}</span>`).join('');
  $('roomCode').setAttribute('aria-label', ROOM);
  $('play').querySelector('.big').textContent = 'Join room';
}
// desktop browsers without a share sheet just copy the link
if (!navigator.share) $('inviteBtn').textContent = 'Copy link';
$('inviteBtn').addEventListener('click', invite);

// who is around, shown under the play button while you're still in the menu
function renderWho() {
  if (joined) return;
  const names = [...roster.values()].filter((p) => !p.b).map((p) => `<b>${esc(p.n)}</b>`);
  if (!ROOM) {
    const n = names.length;
    $('who').innerHTML = n ? `${n} blob${n === 1 ? '' : 's'} playing right now` : 'Nobody here yet, bots will keep you company';
    return;
  }
  if (!names.length) {
    $('who').textContent = 'Nobody here yet. Share the code with your friends!';
    return;
  }
  const busy = latest && latest.ph !== 2 ? '<br>A match is running, you can jump right in' : '';
  $('who').innerHTML = `In this room: ${names.join(', ')}${busy}`;
}

// accepts a bare code or a whole invite link
function codeFrom(text) {
  const t = text.trim();
  const fromLink = t.match(/[?&]room=([A-Za-z]+)/);
  return (fromLink ? fromLink[1] : t).toUpperCase().replace(/[^A-Z]/g, '');
}

async function joinByCode() {
  const code = codeFrom($('codeInput').value);
  if (!/^[A-Z]{4,6}$/.test(code)) {
    setStatus('Room codes are 4 to 6 letters.');
    return;
  }
  try {
    const res = await fetch(`/api/rooms/${code}`);
    if (res.status === 404) {
      setStatus(`There is no room ${code}. Check the code or create a room.`);
      return;
    }
    if (!res.ok) throw new Error(res.statusText);
    location.href = `/?room=${code}`;
  } catch {
    setStatus('Could not reach the server, try again.');
  }
}
$('codeBtn').addEventListener('click', joinByCode);
$('codeInput').addEventListener('keydown', (e) => {
  // Enter here means join this room, not submit the play form
  if (e.key === 'Enter') {
    e.preventDefault();
    joinByCode();
  }
});

// ==== leaderboard ====

async function loadRanks() {
  try {
    const [top, me] = await Promise.all([
      fetch('/api/leaderboard').then((res) => res.json()),
      fetch('/api/me', { method: 'POST', body: JSON.stringify({ k: playerKey() }) }).then((res) => res.json()),
    ]);
    showProfile(me);
    $('rankList').innerHTML = top.top.length
      ? top.top.map((p, i) => `<li><span class="pos">${i + 1}</span><span class="nm">${esc(p.n)}</span>${tierBadge(p.r)}<span class="rt">${p.r}</span></li>`).join('')
      : '<li class="empty">No rated matches yet. Play one!</li>';
  } catch {
    $('rankList').innerHTML = '<li class="empty">Could not load the leaderboard</li>';
  }
}
function showRanks(open) {
  $('ranks').hidden = !open;
  if (open) {
    loadRanks();
    $('ranksClose').focus();
  }
}
$('ranksBtn').addEventListener('click', () => showRanks(true));
$('ranksClose').addEventListener('click', () => showRanks(false));
addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !$('ranks').hidden) showRanks(false);
});
loadProfile();

function backToMenu(reason) {
  joined = false;
  myId = null;
  predictor = null;
  wantJoin = null;
  podium.hide();
  hideAwards();
  $('menu').hidden = false;
  $('hud').hidden = true;
  $('touch').hidden = true;
  $('lobby').hidden = true;
  document.body.classList.remove('lobby', 'standings');
  setStatus(reason);
  renderWho();
}
$('board').addEventListener('click', (e) => {
  if (e.target.closest('[data-invite]')) invite();
});
$('friendsBtn').addEventListener('click', async () => {
  try {
    const res = await fetch('/api/rooms', { method: 'POST' });
    const { code } = await res.json();
    location.href = `/?room=${code}`;
  } catch {
    setStatus('Could not create a room, try again.');
  }
});

$('play').disabled = true;
$('joinForm').addEventListener('submit', (e) => {
  e.preventDefault();
  const name = $('name').value.trim();
  try {
    localStorage.setItem('bb.name', name);
    localStorage.setItem('bb.color', String(chosenColor));
    localStorage.setItem('bb.hat', String(chosenHat));
  } catch { /* storage blocked, not important */ }
  // a hat you're only trying on isn't worn into the game
  if (!owns(chosenHat)) {
    chosenHat = 0;
    refreshLook();
  }
  wantJoin = { t: 'join', n: name, c: chosenColor, h: chosenHat, k: playerKey() };
  send(wantJoin);
  $('name').blur();
});

// ==== camera ====

const camTarget = new THREE.Vector3();
const lookAt = new THREE.Vector3();
let menuAngle = 0;
let shake = 0;

// an arrow on the screen edge while the ring is out of view
function pointToHill(hl) {
  const el = $('hillArrow');
  if (!hl || !joined || podium.active) {
    el.hidden = true;
    return;
  }
  arrowPos.set(hl[0], 1, hl[1]).project(camera);
  const behind = arrowPos.z > 1;
  const onScreen = !behind && Math.abs(arrowPos.x) < 0.92 && Math.abs(arrowPos.y) < 0.88;
  el.hidden = onScreen;
  if (onScreen) return;
  let { x, y } = arrowPos;
  if (behind) { x = -x; y = -y; }
  const k = 0.86 / Math.max(Math.abs(x), Math.abs(y), 1e-6);
  x *= k; y *= k;
  const px = (x * 0.5 + 0.5) * innerWidth, py = (-y * 0.5 + 0.5) * innerHeight;
  const angle = Math.atan2(x, y);
  el.style.transform = `translate(${px - 14}px, ${py - 13}px) rotate(${angle}rad)`;
  el.style.borderBottomColor = hl[3] ? PALETTE[roster.get(hl[3])?.c ?? 0] : '#ffd43b';
}

// a +1 over the ring holder each time their score ticks up
function popHillPoints(view) {
  for (const [id, p] of view.players) {
    const before = lastScores.get(id);
    if (before !== undefined && p.score > before) {
      fx.text(p.x, 3.3, p.z, '+1', PALETTE[roster.get(id)?.c ?? 0]);
      if (id === myId) sfx.pickup();
    }
    lastScores.set(id, p.score);
  }
}

// once out, follow the crowned blob, or anyone still standing
// once you're out, you pick who to watch; it starts on the crowned blob, or anyone still standing
let watching = null;

function watchable(view) {
  return [...view.players.entries()]
    .filter(([id, p]) => id !== myId && !(p.flags & (OUT | 4)))
    .map(([id]) => id)
    .sort((a, b) => a - b);
}

function spectateTarget(view) {
  const ids = watchable(view);
  if (!ids.includes(watching)) watching = ids.includes(view.cw) ? view.cw : ids[0] ?? null;
  return watching === null ? null : view.players.get(watching);
}

function cycleWatching(step) {
  const view = sample(performance.now() - INTERP_MS);
  if (!view) return;
  const ids = watchable(view);
  if (!ids.length) return;
  const i = ids.indexOf(watching);
  watching = ids[(i + step + ids.length) % ids.length];
}

function updateSpectateBar(view) {
  const me = joined && view ? view.players.get(myId) : null;
  const out = !!me && !!(me.flags & OUT) && view.ph === 0;
  $('spectate').hidden = !out || watching === null;
  if (!$('spectate').hidden) $('watchName').textContent = nameOf(watching);
}

$('watchPrev').addEventListener('click', () => cycleWatching(-1));
$('watchNext').addEventListener('click', () => cycleWatching(1));
addEventListener('keydown', (e) => {
  if ($('spectate').hidden || e.target instanceof HTMLInputElement) return;
  if (e.key === 'q' || e.key === 'ArrowLeft') cycleWatching(-1);
  if (e.key === 'e' || e.key === 'ArrowRight') cycleWatching(1);
});

// Low three-quarter view so the horizon stays on screen; portrait screens pull back to keep the island in frame
function updateCamera(dt, view) {
  const portrait = camera.aspect < 1;
  const dist = portrait ? 1.6 : 1;
  let me = joined && view ? view.players.get(myId) : null;
  if (me && me.flags & OUT) me = spectateTarget(view) ?? me;
  const close = focus && performance.now() < focus.until ? view?.players.get(focus.id) : null;
  if (!close) focus = null;
  if (close) {
    // slow motion swoops in on the blob that just went off
    const k = 1 - Math.exp(-dt * 3);
    camTarget.lerp(new THREE.Vector3(close.x, 0, close.z), k);
    camera.position.lerp(new THREE.Vector3(camTarget.x, 6.5 * dist, camTarget.z + 9 * dist), k);
    lookAt.lerp(new THREE.Vector3(camTarget.x, Math.max(close.y, -2), camTarget.z - 1), k);
  } else if (me) {
    // the pitch is wider than the island, so follow further out to keep the goals in view
    const follow = view.pt ? 0.8 : 0.6;
    if (!(me.flags & 4)) camTarget.set(me.x * follow, 0, me.z * follow);
    const k = 1 - Math.exp(-dt * 4);
    camera.position.lerp(new THREE.Vector3(camTarget.x, 12 * dist, camTarget.z + 17 * dist), k);
    lookAt.lerp(new THREE.Vector3(camTarget.x, 0, camTarget.z - 2), k);
  } else {
    menuAngle += dt * 0.06;
    camera.position.set(Math.sin(menuAngle) * 36 * dist, 13 * dist, Math.cos(menuAngle) * 36 * dist);
    lookAt.set(0, 1, 0);
  }
  camera.lookAt(lookAt);
  if (shake > 0) {
    camera.position.x += (Math.random() - 0.5) * shake;
    camera.position.y += (Math.random() - 0.5) * shake;
    shake = Math.max(0, shake - dt * 2.5);
  }
}

// ==== loop ====

let last = performance.now();
let t = 0;

function frame(now) {
  requestAnimationFrame(frame);
  const raw = (now - last) / 1000;
  const dt = Math.min(0.05, raw);
  last = now;
  t += dt;

  if (joined && predictor) predictor.update(raw, input.vector());
  const rt = now - INTERP_MS - warp.update(now, raw * 1000);
  // animations follow the bent clock too, so a hit-stop really holds still
  const adt = dt * warp.scale;
  const view = sample(rt);
  applyPrediction(view);
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
      const happened = b.update(s, adt, t);
      if (happened === 'land') {
        fx.puff(s.x, s.z);
        if (joined && id === myId) sfx.land();
      }
      if (happened === 'splash') {
        fx.splash(s.x, s.z, 1.2);
        if (joined) {
          const me = view.players.get(myId);
          sfx.splash(id === myId || (me && Math.hypot(me.x - s.x, me.z - s.z) < 8));
        }
      }
    }
    for (const [id, b] of blobs) {
      const s = view.players.get(id);
      // eliminated blobs disappear once they have splashed down
      b.group.visible = !!s && !(s.flags & OUT && s.y < -2);
      b.setCrown(id === view.cw, ramp);
      b.setTeam(view.bl && s ? TEAMS[s.team]?.color : null);
    }
    if (view.ph !== 1 && (podium.active || !$('standings').hidden)) {
      podium.hide();
      hideAwards();
      $('standings').hidden = true;
      document.body.classList.remove('standings');
    }
  }

  // tiles use the newest snapshot: your own blob is predicted ahead of the interpolated view,
  // and a tile that looks solid under it after the server dropped it reads as falling through
  world.update(dt, view?.r ?? null, camera, view?.hx ? latest?.hx ?? view.hx : null);
  crates.sync(view?.crates ?? [], dt, t);
  sweeper.update(view?.sw, dt);
  hillRing.update(view?.hl, dt, t, (id) => roster.get(id)?.c ?? 0);
  coins.sync(view?.co, dt, t);
  pitch.update(view?.pt, view?.bl, dt);
  if (view) bubbles.update(camera, view.players, bubbleVec);
  world.setIslandVisible(!view?.pt);
  if (view?.hl) popHillPoints(view);
  // the same edge arrow points at the ball when it is off screen
  pointToHill(view?.hl ?? (view?.bl && !view.bl[3] ? [view.bl[0], view.bl[1]] : null));
  fx.update(adt);
  updateCamera(dt, view);
  updateSpectateBar(view);
  updateHud(dt, view);
  music.play(pickTrack(view));
  if (podium.active && joined) podium.render(renderer, dt);
  else renderer.render(scene, camera);
  if (!joined) preview.render(dt);
}

// labels are drawn to canvas once, so wait for the font before any blob exists
document.fonts.load('600 38px Fredoka').catch(() => {}).finally(() => {
  connect();
  requestAnimationFrame(frame);
});
