import * as THREE from 'three';

export const PALETTE = ['#ff6b6b', '#ffa94d', '#ffd43b', '#69db7c', '#38d9a9', '#4dabf7', '#9775fa', '#f783ac'];
export const HATS = ['Sprout', 'Party hat', 'Viking', 'Propeller', 'Top hat', 'Cowboy', 'Beanie', 'Flower', 'Chef'];

const BODY = new THREE.SphereGeometry(0.8, 28, 20);
const EYE = new THREE.SphereGeometry(0.2, 16, 12);
const PUPIL = new THREE.SphereGeometry(0.1, 12, 8);
const SHINE = new THREE.SphereGeometry(0.035, 6, 4);
const SQUINT = new THREE.BoxGeometry(0.17, 0.045, 0.05);
const SMILE = new THREE.TorusGeometry(0.1, 0.028, 6, 14, Math.PI).rotateZ(Math.PI);
const MOUTH_O = new THREE.SphereGeometry(0.075, 10, 8);
const CHEEK = new THREE.CircleGeometry(0.085, 16);
const FOOT = new THREE.SphereGeometry(0.21, 12, 8);
const MARK = new THREE.RingGeometry(0.95, 1.18, 40).rotateX(-Math.PI / 2);

const OUTLINE = new THREE.MeshBasicMaterial({ color: '#2d2440', side: THREE.BackSide });
const WHITE = new THREE.MeshBasicMaterial({ color: '#ffffff' });
const INK = new THREE.MeshBasicMaterial({ color: '#2d2440' });
const BLUSH = new THREE.MeshBasicMaterial({ color: '#ff7a95', transparent: true, opacity: 0.5, depthWrite: false });
const MARK_MAT = new THREE.MeshBasicMaterial({ color: '#fffaf0', transparent: true, opacity: 0.85, depthWrite: false });

const BOUNCE_GLOW = new THREE.Color('#51cf66');
const GLOW_TMP = new THREE.Color();

const EYE_Y = 0.2;
const EYE_X = 0.27;

// ==== hats ====

function hatBuilder(ramp) {
  const toon = (color) => new THREE.MeshToonMaterial({ color, gradientMap: ramp });
  const mesh = (geo, mat, x = 0, y = 0, z = 0) => {
    const m = new THREE.Mesh(geo, mat);
    m.position.set(x, y, z);
    m.castShadow = true;
    return m;
  };
  const dome = (r, mat) => mesh(new THREE.SphereGeometry(r, 18, 9, 0, Math.PI * 2, 0, Math.PI / 2), mat);

  return [
    () => {
      const g = new THREE.Group();
      const green = toon('#5cbf4a');
      g.add(mesh(new THREE.CylinderGeometry(0.035, 0.045, 0.3, 6), green, 0, 0.15, 0));
      for (const s of [-1, 1]) {
        const leaf = mesh(new THREE.SphereGeometry(0.13, 10, 6), green, s * 0.13, 0.3, 0);
        leaf.scale.set(1.4, 0.45, 0.8);
        leaf.rotation.z = s * 0.5;
        g.add(leaf);
      }
      return g;
    },
    () => {
      const g = new THREE.Group();
      const cone = mesh(new THREE.ConeGeometry(0.3, 0.7, 18), toon('#ff6bcb'), 0, 0.35, 0);
      g.add(cone);
      g.add(mesh(new THREE.TorusGeometry(0.27, 0.05, 8, 20).rotateX(Math.PI / 2), toon('#ffd43b'), 0, 0.06, 0));
      g.add(mesh(new THREE.SphereGeometry(0.1, 10, 8), toon('#ffd43b'), 0, 0.72, 0));
      g.rotation.z = -0.25;
      return g;
    },
    () => {
      const g = new THREE.Group();
      g.add(dome(0.5, toon('#b8c0cc')));
      g.add(mesh(new THREE.TorusGeometry(0.49, 0.05, 8, 24).rotateX(Math.PI / 2), toon('#e0a83a'), 0, 0.03, 0));
      const hornMat = toon('#f3e9d2');
      for (const s of [-1, 1]) {
        const horn = mesh(new THREE.ConeGeometry(0.1, 0.5, 10), hornMat, s * 0.52, 0.28, 0);
        horn.rotation.z = -s * 0.75;
        g.add(horn);
      }
      return g;
    },
    () => {
      const g = new THREE.Group();
      g.add(dome(0.46, toon('#4dabf7')));
      const visor = mesh(new THREE.CylinderGeometry(0.3, 0.3, 0.04, 16, 1, false, -Math.PI / 2, Math.PI), toon('#ff6b6b'), 0, 0.02, 0.32);
      g.add(visor);
      g.add(mesh(new THREE.CylinderGeometry(0.025, 0.025, 0.2, 6), INK, 0, 0.52, 0));
      const prop = new THREE.Group();
      prop.position.y = 0.63;
      const bladeMat = toon('#ffd43b');
      for (const s of [-1, 1]) prop.add(mesh(new THREE.BoxGeometry(0.5, 0.025, 0.11), bladeMat, s * 0.26, 0, 0));
      g.add(prop);
      g.userData.spinner = prop;
      return g;
    },
    () => {
      const g = new THREE.Group();
      const black = toon('#2d2440');
      g.add(mesh(new THREE.CylinderGeometry(0.5, 0.5, 0.05, 24), black, 0, 0.02, 0));
      g.add(mesh(new THREE.CylinderGeometry(0.3, 0.32, 0.55, 20), black, 0, 0.3, 0));
      g.add(mesh(new THREE.CylinderGeometry(0.322, 0.322, 0.1, 20), toon('#ff6b6b'), 0, 0.1, 0));
      g.rotation.z = 0.12;
      return g;
    },
    () => {
      const g = new THREE.Group();
      const brown = toon('#b8773f');
      const brim = mesh(new THREE.CylinderGeometry(0.62, 0.62, 0.05, 24), brown, 0, 0.03, 0);
      brim.scale.z = 0.85;
      g.add(brim);
      g.add(mesh(new THREE.CylinderGeometry(0.27, 0.33, 0.34, 18), brown, 0, 0.2, 0));
      g.add(mesh(new THREE.CylinderGeometry(0.335, 0.335, 0.07, 18), toon('#5e3b28'), 0, 0.08, 0));
      return g;
    },
    () => {
      const g = new THREE.Group();
      const knit = dome(0.5, toon('#ff6b6b'));
      knit.scale.y = 0.85;
      g.add(knit);
      g.add(mesh(new THREE.CylinderGeometry(0.52, 0.52, 0.14, 20), toon('#ffe8e8'), 0, 0.05, 0));
      g.add(mesh(new THREE.SphereGeometry(0.14, 10, 8), toon('#ffffff'), 0, 0.48, 0));
      return g;
    },
    () => {
      const g = new THREE.Group();
      const petal = toon('#ff8fab');
      for (let i = 0; i < 6; i++) {
        const a = (i / 6) * Math.PI * 2;
        const p = mesh(new THREE.SphereGeometry(0.12, 10, 6), petal, Math.cos(a) * 0.17, 0, Math.sin(a) * 0.17);
        p.scale.set(1.3, 0.35, 0.8);
        p.rotation.y = -a;
        g.add(p);
      }
      const center = mesh(new THREE.SphereGeometry(0.1, 10, 8), toon('#ffd43b'), 0, 0.03, 0);
      center.scale.y = 0.6;
      g.add(center);
      g.position.set(0.3, 0.02, 0.15);
      g.rotation.set(0.3, 0, -0.5);
      return g;
    },
    () => {
      const g = new THREE.Group();
      const white = toon('#ffffff');
      g.add(mesh(new THREE.CylinderGeometry(0.34, 0.36, 0.3, 20), white, 0, 0.15, 0));
      for (const [x, z] of [[0.15, 0.1], [-0.15, 0.1], [0, -0.15], [0, 0.05]]) {
        g.add(mesh(new THREE.SphereGeometry(0.24, 12, 10), white, x, 0.4, z));
      }
      return g;
    },
  ];
}

export function makeCrown(ramp) {
  const g = new THREE.Group();
  const gold = new THREE.MeshToonMaterial({ color: '#ffc61a', gradientMap: ramp, emissive: '#5c3b00' });
  const band = new THREE.Mesh(new THREE.CylinderGeometry(0.34, 0.3, 0.22, 10, 1, true), gold);
  band.material.side = THREE.DoubleSide;
  g.add(band);
  const gem = new THREE.MeshBasicMaterial({ color: '#ff4d6d' });
  for (let i = 0; i < 5; i++) {
    const a = (i / 5) * Math.PI * 2;
    const spike = new THREE.Mesh(new THREE.ConeGeometry(0.08, 0.24, 6), gold);
    spike.position.set(Math.sin(a) * 0.31, 0.22, Math.cos(a) * 0.31);
    const ball = new THREE.Mesh(new THREE.SphereGeometry(0.045, 8, 6), gold);
    ball.position.set(Math.sin(a) * 0.31, 0.36, Math.cos(a) * 0.31);
    const stone = new THREE.Mesh(new THREE.SphereGeometry(0.05, 8, 6), gem);
    stone.position.set(Math.sin(a + 0.63) * 0.33, 0, Math.cos(a + 0.63) * 0.33);
    g.add(spike, ball, stone);
  }
  g.traverse((o) => { o.castShadow = o.isMesh; });
  return g;
}

let hatFactories = null;
export function makeHat(index, ramp) {
  hatFactories ??= hatBuilder(ramp);
  return (hatFactories[index] ?? hatFactories[0])();
}

// ==== blob ====

export class Blob {
  constructor({ name, color, hat = 0, me = false, ramp, label = true }) {
    this.group = new THREE.Group();
    this.pivot = new THREE.Group();
    this.pivot.position.y = 0.72;
    this.group.add(this.pivot);

    const base = new THREE.Color(PALETTE[color] ?? PALETTE[0]);
    this.mat = new THREE.MeshToonMaterial({ color: base, gradientMap: ramp });
    this.footMat = new THREE.MeshToonMaterial({ color: base.clone().multiplyScalar(0.72), gradientMap: ramp });

    const body = new THREE.Mesh(BODY, this.mat);
    body.scale.y = 0.9;
    body.castShadow = true;
    this.outline = new THREE.Mesh(BODY, OUTLINE);
    this.outline.scale.set(1.06, 0.9 * 1.06, 1.06);
    this.pivot.add(body, this.outline);

    this.face = new THREE.Group();
    this.pivot.add(this.face);
    this.eyes = [];
    for (const s of [-1, 1]) {
      const open = new THREE.Group();
      open.position.set(s * EYE_X, EYE_Y, 0.62);
      const white = new THREE.Mesh(EYE, WHITE);
      white.scale.set(1, 1.25, 0.7);
      const pupil = new THREE.Mesh(PUPIL, INK);
      pupil.position.set(0, -0.02, 0.12);
      pupil.scale.set(1, 1.25, 0.6);
      const shine = new THREE.Mesh(SHINE, WHITE);
      shine.position.set(-0.035, 0.05, 0.18);
      open.add(white, pupil, shine);

      const squint = new THREE.Group();
      squint.position.set(s * EYE_X, EYE_Y, 0.74);
      for (const k of [-1, 1]) {
        const bar = new THREE.Mesh(SQUINT, INK);
        bar.position.y = k * 0.04;
        bar.rotation.z = -s * k * 0.5;
        squint.add(bar);
      }
      squint.visible = false;
      this.face.add(open, squint);
      this.eyes.push({ open, pupil, squint });
    }

    this.smile = new THREE.Mesh(SMILE, INK);
    this.smile.position.set(0, -0.08, 0.76);
    this.mouthO = new THREE.Mesh(MOUTH_O, INK);
    this.mouthO.position.set(0, -0.12, 0.74);
    this.mouthO.scale.set(1, 1.3, 0.5);
    this.mouthO.visible = false;
    this.face.add(this.smile, this.mouthO);
    for (const s of [-1, 1]) {
      const cheek = new THREE.Mesh(CHEEK, BLUSH);
      cheek.position.set(s * 0.47, -0.04, 0.6);
      cheek.rotation.y = s * 0.65;
      this.face.add(cheek);
    }

    this.feet = [];
    for (const s of [-1, 1]) {
      const f = new THREE.Mesh(FOOT, this.footMat);
      f.scale.set(1, 0.55, 1.35);
      f.castShadow = true;
      this.pivot.add(f);
      this.feet.push({ mesh: f, side: s });
    }

    this.hat = makeHat(hat, ramp);
    this.hat.position.y += 0.6;
    this.pivot.add(this.hat);

    if (label) {
      this.label = makeLabel(name, me);
      this.group.add(this.label);
    }
    if (me) {
      this.mark = new THREE.Mesh(MARK, MARK_MAT);
      this.mark.position.y = 0.04;
      this.group.add(this.mark);
    }

    this.seed = Math.random() * 10;
    this.speed = 0;
    this.prev = null;
    this.ghost = false;
    this.wasDashing = false;
    this.lastCharge = 0;
    this.size = 1;
    this.hitT = 0;
    this.blinkT = 2 + Math.random() * 3;
    // jelly spring: positive squashes, negative stretches
    this.jelly = 0;
    this.jellyV = 0;
  }

  setCrown(on, ramp) {
    if (on && !this.crown) {
      this.crown = makeCrown(ramp);
      this.group.add(this.crown);
    }
    if (this.crown) this.crown.visible = on;
  }

  bump(power) {
    this.jellyV += Math.min(power, 25) * 0.35;
    this.hitT = 0.45;
  }

  setExpression(t, dt, falling, dashing) {
    this.hitT = Math.max(0, this.hitT - dt);
    this.blinkT -= dt;
    if (this.blinkT < -0.12) this.blinkT = 2 + Math.random() * 3.5;
    const blinking = this.blinkT < 0;
    const squint = this.hitT > 0 && !falling;
    const scared = falling;

    for (const e of this.eyes) {
      e.open.visible = !squint;
      e.squint.visible = squint;
      const sy = blinking ? 0.12 : scared ? 1.25 : dashing ? 0.7 : 1;
      e.open.scale.set(scared ? 1.2 : 1, sy, 1);
      e.pupil.scale.setScalar(scared ? 0.55 : 1);
      e.pupil.scale.y *= 1.25;
      e.pupil.position.x = Math.sin(t * 0.7 + this.seed) * 0.03;
    }
    this.smile.visible = !scared && !squint;
    this.mouthO.visible = scared || squint;
    this.mouthO.scale.set(squint ? 0.8 : 1.1, squint ? 0.6 : 1.5, 0.5);
  }

  // Returns 'splash' on the frame the blob hits the water
  update(s, dt, t) {
    let result = null;
    if (this.prev && dt > 0) {
      const sp = Math.hypot(s.x - this.prev.x, s.z - this.prev.z) / dt;
      this.speed += (sp - this.speed) * Math.min(1, dt * 10);
      if (this.prev.y > -0.75 && s.y <= -0.75) result = 'splash';
      if (this.prev.y > 0.05 && s.y <= 0.01 && !(s.flags & 4)) {
        result = 'land';
        this.jellyV += 5;
      }
    }
    this.prev = { x: s.x, y: s.y, z: s.z };

    const falling = (s.flags & 4) !== 0;
    const dashing = (s.flags & 1) !== 0;
    const ghost = (s.flags & 2) !== 0;
    const charge = s.flags & 8 ? s.ch : 0;
    const heavy = (s.flags & 16) !== 0;
    const bouncy = (s.flags & 32) !== 0;
    const pounding = (s.flags & 64) !== 0;
    this.size += ((heavy ? 1.3 : 1) - this.size) * Math.min(1, dt * 8);
    this.group.scale.setScalar(this.size);
    if (dashing && !this.wasDashing) this.jellyV -= 6 + this.lastCharge * 8;
    this.wasDashing = dashing;
    this.lastCharge = charge || (dashing ? this.lastCharge : 0);

    // squat, tremble and glow while charging so everyone can see a big hit coming
    const tremble = Math.sin(t * 70) * 0.035 * charge;
    this.group.position.set(s.x + tremble, Math.max(s.y, -30), s.z);
    this.mat.emissive.copy(this.mat.color).multiplyScalar(0.45 * charge);
    if (bouncy) this.mat.emissive.add(GLOW_TMP.copy(BOUNCE_GLOW).multiplyScalar(0.3 + Math.sin(t * 9) * 0.15));
    this.group.rotation.y = s.a;

    this.jellyV += (-260 * this.jelly - 10 * this.jellyV) * dt;
    this.jelly += this.jellyV * dt;
    const j = THREE.MathUtils.clamp(this.jelly, -0.35, 0.4);
    let sx = 1 + j * 0.45, sy = 1 - j, sz = 1 + j * 0.45;
    if (dashing) { sx *= 0.86; sy *= 0.88; sz *= 1.25; }
    sx *= 1 + 0.12 * charge; sy *= 1 - 0.22 * charge; sz *= 1 + 0.12 * charge;
    if (pounding) { sx *= 0.9; sy *= 0.8; sz *= 0.9; }
    const airborne = s.y > 0.05 && !falling && !pounding;
    if (airborne) { sx *= 0.94; sy *= 1.12; sz *= 0.94; }
    this.pivot.scale.set(sx, sy, sz);

    const move = Math.min(this.speed / 7, 1);
    const hop = falling || airborne ? 0 : Math.abs(Math.sin(t * 13 + this.seed)) * 0.14 * move;
    this.pivot.position.y = 0.72 + hop;
    if (falling) {
      this.pivot.rotation.x += dt * 9;
    } else {
      const lean = dashing ? 0.25 : move * 0.08;
      const r = Math.atan2(Math.sin(this.pivot.rotation.x), Math.cos(this.pivot.rotation.x));
      this.pivot.rotation.x = r + (lean - r) * Math.min(1, dt * 12);
    }
    this.pivot.rotation.z = Math.sin(t * 13 + this.seed) * 0.08 * move;

    for (const f of this.feet) {
      const phase = Math.sin(t * 13 + this.seed + (f.side > 0 ? Math.PI : 0));
      f.mesh.position.set(f.side * 0.32, -0.66 - hop + Math.max(0, phase) * 0.12 * move, 0.08 + phase * 0.16 * move);
    }

    if (this.hat.userData.spinner) this.hat.userData.spinner.rotation.y += dt * (8 + this.speed * 3);
    if (this.crown?.visible) {
      // the crown floats above the hat in group space so it stays level while the body wobbles
      this.crown.position.y = 2.05 + this.pivot.position.y - 0.72 + Math.sin(t * 3) * 0.06;
      this.crown.rotation.y += dt * 1.5;
    }
    this.setExpression(t, dt, falling, dashing || charge > 0);

    if (ghost !== this.ghost) {
      this.ghost = ghost;
      this.mat.transparent = ghost;
      this.mat.needsUpdate = true;
      this.outline.visible = !ghost;
      if (!ghost) this.mat.opacity = 1;
    }
    if (ghost) this.mat.opacity = 0.45 + Math.sin(t * 22) * 0.2;

    if (this.mark) this.mark.visible = !falling;
    if (this.label) this.label.visible = s.y > -2;
    return result;
  }

  dispose() {
    this.group.removeFromParent();
    this.mat.dispose();
    this.footMat.dispose();
    for (const part of [this.hat, this.crown]) {
      part?.traverse((o) => {
        if (o.isMesh && o.material !== INK) {
          o.geometry.dispose();
          o.material.dispose();
        }
      });
    }
    if (this.label) {
      this.label.material.map.dispose();
      this.label.material.dispose();
    }
  }
}

function makeLabel(text, me) {
  const c = document.createElement('canvas');
  c.width = 320;
  c.height = 72;
  const g = c.getContext('2d');
  g.font = '600 38px Fredoka, ui-rounded, sans-serif';
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  g.lineJoin = 'round';
  g.lineWidth = 9;
  g.strokeStyle = 'rgba(45, 36, 64, 0.9)';
  g.strokeText(text, 160, 38);
  g.fillStyle = me ? '#ffe066' : '#ffffff';
  g.fillText(text, 160, 38);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthWrite: false }));
  sprite.scale.set(3.4, 0.765, 1);
  sprite.position.y = 2.6;
  sprite.renderOrder = 10;
  return sprite;
}
