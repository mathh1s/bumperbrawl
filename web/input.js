const DASH_KEYS = new Set(['ShiftLeft', 'ShiftRight', 'KeyE', 'KeyJ']);
const JUMP_KEYS = new Set(['Space', 'KeyK']);
const STICK_RANGE = 55;

export class Input {
  constructor({ onDashDown, onDashUp, onJump }) {
    this.keys = new Set();
    this.touch = { x: 0, z: 0 };
    this.onDashDown = onDashDown;
    this.onDashUp = onDashUp;
    this.onJump = onJump;
    this.dashHeld = false;

    addEventListener('keydown', (e) => {
      if (e.target instanceof HTMLInputElement) return;
      if (DASH_KEYS.has(e.code)) {
        e.preventDefault();
        if (!e.repeat) this.pressDash();
      }
      if (JUMP_KEYS.has(e.code)) {
        e.preventDefault();
        if (!e.repeat) this.onJump();
      }
      this.keys.add(e.code);
    });
    addEventListener('keyup', (e) => {
      this.keys.delete(e.code);
      if (DASH_KEYS.has(e.code) && ![...DASH_KEYS].some((k) => this.keys.has(k))) this.releaseDash();
    });
    addEventListener('blur', () => {
      this.keys.clear();
      this.releaseDash();
    });
  }

  pressDash() {
    if (this.dashHeld) return;
    this.dashHeld = true;
    this.onDashDown();
  }

  releaseDash() {
    if (!this.dashHeld) return;
    this.dashHeld = false;
    this.onDashUp();
  }

  vector() {
    const k = this.keys;
    let x = 0, z = 0;
    if (k.has('KeyA') || k.has('ArrowLeft')) x -= 1;
    if (k.has('KeyD') || k.has('ArrowRight')) x += 1;
    if (k.has('KeyW') || k.has('ArrowUp')) z -= 1;
    if (k.has('KeyS') || k.has('ArrowDown')) z += 1;
    x += this.touch.x;
    z += this.touch.z;
    const l = Math.hypot(x, z);
    if (l > 1) { x /= l; z /= l; }
    return { x, z };
  }

  bindTouch({ pad, stick, knob, dashBtn, jumpBtn, canvas }) {
    // iOS Safari ignores user-scalable=no, so pinch and double-tap zoom must be cancelled on the raw touch events
    const block = (e) => e.preventDefault();
    for (const el of [pad, dashBtn, jumpBtn, canvas]) {
      for (const type of ['touchstart', 'touchmove', 'touchend']) el.addEventListener(type, block, { passive: false });
    }
    for (const type of ['gesturestart', 'gesturechange', 'gestureend']) document.addEventListener(type, block);

    let active = null;
    let ox = 0, oy = 0;
    const home = { left: stick.style.left, bottom: stick.style.bottom };

    pad.addEventListener('pointerdown', (e) => {
      if (active !== null) return;
      active = e.pointerId;
      pad.setPointerCapture(e.pointerId);
      const r = pad.getBoundingClientRect();
      ox = e.clientX;
      oy = e.clientY;
      stick.style.left = `${e.clientX - r.left}px`;
      stick.style.bottom = `${r.bottom - e.clientY}px`;
    });
    pad.addEventListener('pointermove', (e) => {
      if (e.pointerId !== active) return;
      let dx = e.clientX - ox, dy = e.clientY - oy;
      const l = Math.hypot(dx, dy);
      if (l > STICK_RANGE) { dx *= STICK_RANGE / l; dy *= STICK_RANGE / l; }
      knob.style.transform = `translate(${dx}px, ${dy}px)`;
      this.touch = { x: dx / STICK_RANGE, z: dy / STICK_RANGE };
    });
    const release = (e) => {
      if (e.pointerId !== active) return;
      active = null;
      knob.style.transform = '';
      stick.style.left = home.left;
      stick.style.bottom = home.bottom;
      this.touch = { x: 0, z: 0 };
    };
    pad.addEventListener('pointerup', release);
    pad.addEventListener('pointercancel', release);

    dashBtn.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      dashBtn.setPointerCapture(e.pointerId);
      this.pressDash();
    });
    for (const type of ['pointerup', 'pointercancel']) dashBtn.addEventListener(type, () => this.releaseDash());

    jumpBtn.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      this.onJump();
    });
  }
}
