// Client-side prediction for your own blob.
//
// The client runs the same 60 Hz movement rules as the server (server/movement.go)
// on its own inputs, so the blob reacts on the frame you press instead of a round
// trip later. Every input is numbered with the step it applies on. The server
// echoes the last number it has seen and how many ticks it has simulated since,
// along with the exact state of the blob; the client rewinds to that state and
// replays the inputs the server had not caught up with yet. Whatever the server
// did that the client could not know about (bumps, the log, slams) shows up as a
// small correction that is blended out over a few frames.

const STEP = 1 / 60;
const FALL_GRAVITY = 30;
const SNAP_DIST = 2.5;

export class Predictor {
  constructor(cfg, send) {
    this.c = cfg;
    this.send = send;
    this.step = 0;
    this.acc = 0;
    this.hist = [];
    this.st = null;
    this.input = { x: 0, z: 0 };
    this.lastSentStep = -10;
    this.queued = [];
    this.off = { x: 0, y: 0, z: 0 };
    this.heavy = false;
    this.mode = 'off'; // 'move', 'fall' or 'off' (waiting, out of the round)
  }

  // jump, charge and dash are sent right away, tagged with the step that will apply them
  press(kind) {
    this.send({ t: kind, s: this.step + 1 });
    this.queued.push(kind);
  }

  canDash() {
    return this.mode === 'move' && this.st.dashCD === 0;
  }

  canJump() {
    return this.mode === 'move' && !this.st.airborne && this.st.jumpCD === 0;
  }

  // flags come from the newest snapshot: falling, pound, out and the heavy power aren't predicted
  setFlags(flags) {
    this.heavy = !!(flags & 16);
    const mode = flags & 128 ? 'off' : flags & 4 ? 'fall' : 'move';
    if (mode !== this.mode && mode === 'off') this.st = null;
    this.mode = mode;
    this.pound = !!(flags & 64);
  }

  // m is the server's "me" message
  reconcile(m) {
    const [x, z, y, vx, vz, vy, stun, dashT, dashCD, chargeT, jumpCD] = m.st;
    const server = {
      x, z, y, vx, vz, vy, stun, dashT, dashCD, chargeT, jumpCD,
      charging: !!(m.b & 1), airborne: !!(m.b & 2), angle: this.st?.angle ?? 0,
    };
    // the server state is the result of the client's steps up to this one
    const upTo = m.s + m.k - 1;
    const before = this.st ? { x: this.st.x, y: this.st.y, z: this.st.z } : null;
    if (upTo > this.step || !this.st) {
      this.step = Math.max(this.step, upTo);
      this.hist.length = 0;
      this.st = server;
    } else {
      while (this.hist.length && this.hist[0].n <= upTo) this.hist.shift();
      this.st = server;
      for (const h of this.hist) this.simulate(h);
    }
    if (!before) return;
    this.off.x += before.x - this.st.x;
    this.off.y += before.y - this.st.y;
    this.off.z += before.z - this.st.z;
    // respawns and other teleports snap instead of sliding across the island
    if (Math.hypot(this.off.x, this.off.z) > SNAP_DIST) this.off.x = this.off.y = this.off.z = 0;
  }

  // advance in fixed steps; stick is the current input vector
  update(dt, stick) {
    this.acc = Math.min(this.acc + dt, 0.25);
    while (this.acc >= STEP) {
      this.acc -= STEP;
      this.step++;
      // only send the stick when it really moved, at most every other step; the step
      // that sends it is the step that applies it, so both sides use the same value
      const moved = Math.hypot(stick.x - this.input.x, stick.z - this.input.z) > 0.03;
      const settled = (stick.x === 0 && stick.z === 0) !== (this.input.x === 0 && this.input.z === 0);
      if ((moved || settled) && this.step - this.lastSentStep >= 2) {
        this.input = { x: stick.x, z: stick.z };
        this.lastSentStep = this.step;
        this.send({ t: 'in', x: stick.x, z: stick.z, s: this.step });
      }
      const h = { n: this.step, x: this.input.x, z: this.input.z, q: this.queued };
      this.queued = [];
      this.hist.push(h);
      if (this.hist.length > 240) this.hist.shift();
      if (this.st) this.simulate(h);
    }
    const k = Math.exp(-dt * 12);
    this.off.x *= k;
    this.off.y *= k;
    this.off.z *= k;
  }

  // the predicted blob for rendering, or null when the server's view should be used
  view() {
    if (!this.st || this.mode === 'off') return null;
    const s = this.st;
    return { x: s.x + this.off.x, y: s.y + this.off.y, z: s.z + this.off.z, a: s.angle, charging: s.charging, ch: s.chargeT / this.c.chargeMax, dashing: s.dashT > 0 };
  }

  simulate(h) {
    const s = this.st;
    const c = this.c;
    const dt = STEP;
    if (this.mode === 'fall') {
      s.vy -= FALL_GRAVITY * dt;
      s.y += s.vy * dt;
      s.x += s.vx * dt;
      s.z += s.vz * dt;
      s.vx *= 1 - 1.5 * dt;
      s.vz *= 1 - 1.5 * dt;
      return;
    }
    let wantJump = false, wantDash = false;
    for (const q of h.q) {
      if (q === 'charge' && s.dashCD === 0 && !s.charging) { s.charging = true; s.chargeT = 0; }
      if (q === 'jump') wantJump = true;
      if (q === 'dash') wantDash = true;
    }
    s.dashCD = Math.max(0, s.dashCD - dt);
    s.dashT = Math.max(0, s.dashT - dt);

    // server/sweeper.go updateJump
    s.jumpCD = Math.max(0, s.jumpCD - dt);
    if (wantJump && !s.airborne && !this.pound && s.jumpCD === 0) {
      s.airborne = true;
      s.vy = c.jumpSpeed;
    }
    if (s.airborne) {
      s.vy -= c.jumpGravity * dt;
      s.y += s.vy * dt;
      if (s.y <= 0) {
        s.y = 0; s.vy = 0; s.airborne = false;
        s.jumpCD = c.jumpCooldown;
      }
    }

    // server/movement.go move
    s.stun = Math.max(0, s.stun - dt);
    const inLen = Math.hypot(h.x, h.z);
    if (inLen > 0.1) s.angle = Math.atan2(h.x, h.z);
    let top = c.runSpeed;
    if (this.heavy) top *= c.heavySlow;
    if (s.charging) {
      s.chargeT = Math.min(c.chargeMax, s.chargeT + dt);
      top *= c.chargeSlow;
    }
    const speed = Math.hypot(s.vx, s.vz);
    if (s.stun > 0 || s.dashT > 0 || speed > top + 0.01) {
      s.vx += h.x * c.looseAccel * dt;
      s.vz += h.z * c.looseAccel * dt;
      const damp = 1 - c.drag * dt;
      s.vx *= damp;
      s.vz *= damp;
    } else {
      let acc = c.runAccel;
      if (s.airborne) acc = c.airAccel;
      else if (inLen < 0.1) acc = c.brakeAccel;
      let dx = h.x * top - s.vx, dz = h.z * top - s.vz;
      const d = Math.hypot(dx, dz);
      if (d > acc * dt) { dx = dx / d * acc * dt; dz = dz / d * acc * dt; }
      s.vx += dx;
      s.vz += dz;
    }
    if (wantDash && s.dashCD === 0) {
      const pow = s.charging ? s.chargeT / c.chargeMax : 0;
      const imp = c.dashImpulse * (1 + 0.9 * pow);
      s.vx += Math.sin(s.angle) * imp;
      s.vz += Math.cos(s.angle) * imp;
      s.dashCD = c.dashCooldown + 0.6 * pow;
      s.dashT = c.dashTime * (1 + 0.6 * pow);
      s.charging = false;
      s.chargeT = 0;
    }
    s.x += s.vx * dt;
    s.z += s.vz * dt;
  }
}
