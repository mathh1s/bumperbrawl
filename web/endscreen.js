import { PALETTE } from './blobs.js';
import { esc } from './text.js';

// The results screen between rounds and after a match, laid over the podium (or the
// live island when nobody made it onto one). Same sticker style as the title screen:
// a big tilted headline, a standings card, your own result and the way out.

const PLACE = ['1st', '2nd', '3rd'];
const ordinal = (n) => PLACE[n - 1] ?? `${n}th`;

export class EndScreen {
  constructor(el, { onLeave }) {
    this.el = el;
    this.you = { rank: null, crowns: null };
    el.querySelector('#esLeave').addEventListener('click', () => onLeave());
  }

  get open() {
    return !this.el.hidden;
  }

  // rating and crowns arrive before the results are revealed, so they wait here
  noteRank(m) {
    this.you.rank = m;
    if (this.open) this.renderYou();
  }

  noteCrowns(m) {
    this.you.crowns = m;
    if (this.open) this.renderYou();
  }

  reset() {
    this.you = { rank: null, crowns: null };
    this.hide();
  }

  // kicker: small line above, title: the headline, sub: one line under it
  // standings: [{i, n, c, w, p}] in order; final marks the end of a match; awards: [{t, d, i, n, c}]
  show({ kicker, title, sub, tone = '', standings, final, awards = [], myId, leaveLabel }) {
    this.myId = myId;
    this.final = final;
    this.standings = standings;
    const q = (s) => this.el.querySelector(s);
    this.el.className = tone;
    q('.kicker').textContent = kicker;
    q('h2').innerHTML = title;
    q('.sub').textContent = sub ?? '';
    q('.esTable h3').textContent = final ? 'Final standings' : 'Match so far';
    const rows = final ? standings : standings.slice(0, 6);
    q('.esTable ol').innerHTML = rows.map((p, k) => {
      const stars = p.w ? `<span class="stars">${'★'.repeat(Math.min(p.w, 5))}${p.w > 5 ? `<small>×${p.w}</small>` : ''}</span>` : '';
      return `<li class="${p.i === myId ? 'me' : ''}"><span class="pos">${k + 1}</span>`
        + `<span class="dot" style="background:${PALETTE[p.c] ?? PALETTE[0]}"></span>`
        + `<span class="nm">${esc(p.n)}</span>${stars}</li>`;
    }).join('');
    q('.esTable').hidden = !standings.length;
    const aw = q('.esAwards');
    aw.hidden = !awards.length;
    aw.innerHTML = awards.map((a, k) =>
      `<li style="animation-delay:${0.6 + k * 0.4}s" class="${a.i === myId ? 'me' : ''}">`
      + `<b>${esc(a.t)}</b><span class="who"><span class="dot" style="background:${PALETTE[a.c] ?? PALETTE[0]}"></span>${esc(a.n)}</span>`
      + `<small>${esc(a.d)}</small></li>`,
    ).join('');
    q('#esLeave').textContent = leaveLabel;
    this.renderYou();
    this.el.hidden = false;
    document.body.classList.add('endscreen');
  }

  renderYou() {
    const chips = [];
    const place = this.standings?.findIndex((p) => p.i === this.myId) ?? -1;
    if (this.final && place >= 0) chips.push(`You finished <b>${ordinal(place + 1)}</b>`);
    const r = this.you.rank;
    if (r) {
      const d = r.new - r.old;
      chips.push(`Rating <b>${r.new}</b> <span class="${d >= 0 ? 'up' : 'down'}">${d >= 0 ? '+' : ''}${d}</span>`);
    }
    if (this.you.crowns) chips.push(`<b>+${this.you.crowns.got}</b> 👑`);
    const el = this.el.querySelector('.esYou');
    el.hidden = !chips.length;
    el.innerHTML = chips.map((c) => `<li>${c}</li>`).join('');
  }

  setCountdown(text) {
    this.el.querySelector('.esNext').innerHTML = text;
  }

  hide() {
    this.el.hidden = true;
    document.body.classList.remove('endscreen');
  }
}
