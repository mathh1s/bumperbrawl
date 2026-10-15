import { PALETTE } from './blobs.js';
import { MODES } from './modes.js';
import { esc } from './text.js';

// The private room lobby: who is in, who is ready, the match settings and the start button.
// The host edits the settings; everyone else sees them read-only.

const MODE_IDS = [0, 1, 2, 3];
const KNOCKOUT = 1;
const FORMATS = [
  { id: 0, name: 'Points', blurb: 'Most round wins takes the match' },
  { id: KNOCKOUT, name: 'Knockout', blurb: 'The best 60% go through each round, the last few play a final' },
];
const STEPPERS = [
  // a knockout runs until the final, so it has no round count
  { key: 'r', label: 'Rounds', min: 1, max: 10, step: 1, show: (v) => String(v), hide: (set) => set.f === KNOCKOUT },
  { key: 't', label: 'Round length', min: 60, max: 240, step: 30, show: (v) => `${Math.floor(v / 60)}:${String(v % 60).padStart(2, '0')}` },
  { key: 'b', label: 'Bots fill to', min: 0, max: 8, step: 1, show: (v) => (v ? `${v} players` : 'no bots') },
];

const CROWN = '<svg class="host" viewBox="0 0 20 14" aria-label="host"><path d="M2 12 L1 3 L6 7 L10 1 L14 7 L19 3 L18 12 Z"/></svg>';

export class LobbyPanel {
  constructor(el, { send, onInvite }) {
    this.el = el;
    this.send = send;
    this.state = null;
    this.collapsed = false;
    el.addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (!btn) {
        if (e.target.closest('header')) this.toggle();
        return;
      }
      // keep focus off the button so Space still jumps instead of clicking it again
      btn.blur();
      const { act, key, dir, mode } = btn.dataset;
      if (act === 'invite') onInvite();
      if (act === 'collapse') this.toggle();
      if (act === 'ready') this.send({ t: 'ready', v: !this.meReady });
      if (act === 'start') this.send({ t: 'start' });
      if (act === 'step') this.change({ [key]: this.state.set[key] + Number(dir) * STEPPERS.find((s) => s.key === key).step });
      if (act === 'format') this.change({ f: Number(btn.dataset.format) });
      if (act === 'mode') {
        const m = [...this.state.set.m];
        m[Number(mode)] = !m[Number(mode)];
        this.change({ m });
      }
    });
  }

  toggle() {
    this.collapsed = !this.collapsed;
    this.el.classList.toggle('min', this.collapsed);
  }

  change(patch) {
    const set = { ...this.state.set, ...patch };
    for (const s of STEPPERS) set[s.key] = Math.min(s.max, Math.max(s.min, set[s.key]));
    this.send({ t: 'settings', set });
  }

  // room is the server's room message, roster the players by id, countdown the seconds left or null
  render({ room, roster, myId, code, countdown }) {
    this.state = room;
    if (!room) return;
    const isHost = room.host === myId;
    const ready = new Set(room.ready);
    this.meReady = ready.has(myId);
    const humans = [...roster.values()].filter((p) => !p.b);
    const waiting = humans.filter((p) => !ready.has(p.i)).length;

    const players = [...roster.values()]
      .sort((a, b) => Number(a.b) - Number(b.b) || a.i - b.i)
      .map((p) => {
        const tag = p.b ? '<span class="tag bot">bot</span>'
          : ready.has(p.i) ? '<span class="tag ok">ready</span>' : '<span class="tag wait">not ready</span>';
        return `<li class="${p.i === myId ? 'me' : ''}"><span class="dot" style="background:${PALETTE[p.c]}"></span>`
          + `<span class="nm">${esc(p.n)}</span>${p.i === room.host ? CROWN : ''}${tag}</li>`;
      }).join('');

    const steppers = STEPPERS.filter((s) => !s.hide?.(room.set)).map((s) => {
      const v = room.set[s.key];
      const ctl = isHost
        ? `<button data-act="step" data-key="${s.key}" data-dir="-1" ${v <= s.min ? 'disabled' : ''} aria-label="less">−</button>`
          + `<b>${s.show(v)}</b>`
          + `<button data-act="step" data-key="${s.key}" data-dir="1" ${v >= s.max ? 'disabled' : ''} aria-label="more">+</button>`
        : `<b>${s.show(v)}</b>`;
      return `<div class="row"><span>${s.label}</span><span class="ctl">${ctl}</span></div>`;
    }).join('');
    const format = FORMATS.find((f) => f.id === room.set.f) ?? FORMATS[0];
    const formats = FORMATS.map((f) => `<button data-act="format" data-format="${f.id}" aria-pressed="${f.id === format.id}" ${isHost ? '' : 'disabled'}>${f.name}</button>`).join('');
    const modes = MODE_IDS.map((id) => {
      const on = !!room.set.m[id];
      return `<button data-act="mode" data-mode="${id}" aria-pressed="${on}" ${isHost ? '' : 'disabled'}>${MODES[id].name}</button>`;
    }).join('');

    let status;
    if (countdown !== null) status = `Starting in <b>${countdown}</b>`;
    else if (waiting) status = `Waiting for ${waiting} player${waiting === 1 ? '' : 's'} to ready up`;
    else status = 'Everyone is ready';

    const start = !isHost ? ''
      : `<button class="ghost" data-act="start">${room.forced && room.counting ? 'Cancel start' : 'Start now'}</button>`;

    const html = `
      <header><span>Room <b>${esc(code)}</b></span>
        <button class="ghost small" data-act="invite">Invite</button>
        <button class="fold" data-act="collapse" aria-label="Fold">${this.collapsed ? '▾' : '▴'}</button></header>
      <div class="body">
        <ul class="players">${players}</ul>
        <div class="settings"><div class="modes format">${formats}</div><p class="note">${format.blurb}</p>
          ${steppers}<div class="modes">${modes}</div>
          ${isHost ? '' : '<p class="note">The host picks the settings</p>'}</div>
      </div>
      <p class="status">${status}</p>
      <div class="actions">
        <button class="readyBtn ${this.meReady ? 'on' : ''}" data-act="ready">${this.meReady ? 'Ready!' : 'Ready up'}</button>
        ${start}
      </div>`;
    // rebuilding on every HUD tick would swallow clicks that land between mousedown and mouseup
    if (html !== this.html) {
      this.html = html;
      this.el.innerHTML = html;
    }
  }
}
