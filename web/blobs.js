import * as THREE from 'three';

export const PALETTE = ['#ff6b6b', '#ffa94d', '#ffd43b', '#69db7c', '#38d9a9', '#4dabf7', '#9775fa', '#f783ac'];

const BODY = new THREE.SphereGeometry(0.8, 24, 18);
const EYE = new THREE.SphereGeometry(0.21, 12, 10);
const PUPIL = new THREE.SphereGeometry(0.11, 10, 8);
const STALK = new THREE.CylinderGeometry(0.04, 0.05, 0.42, 6);
const TIP = new THREE.SphereGeometry(0.14, 10, 8);
const MARK = new THREE.RingGeometry(0.95, 1.18, 40).rotateX(-Math.PI / 2);

const OUTLINE = new THREE.MeshBasicMaterial({ color: '#2d2440', side: THREE.BackSide });
const WHITE = new THREE.MeshBasicMaterial({ color: '#ffffff' });
const INK = new THREE.MeshBasicMaterial({ color: '#2d2440' });
const MARK_MAT = new THREE.MeshBasicMaterial({ color: '#fffaf0', transparent: true, opacity: 0.85, depthWrite: false });

export class Blob {
  constructor({ name, color, me, ramp }) {
    this.group = new THREE.Group();
    this.pivot = new THREE.Group();
    this.pivot.position.y = 0.72;
    this.group.add(this.pivot);

    const base = new THREE.Color(PALETTE[color] ?? PALETTE[0]);
    this.mat = new THREE.MeshToonMaterial({ color: base, gradientMap: ramp });
    this.tipMat = new THREE.MeshToonMaterial({ color: base.clone().lerp(new THREE.Color('#ffffff'), 0.45), gradientMap: ramp });

    const body = new THREE.Mesh(BODY, this.mat);
    body.scale.y = 0.9;
    body.castShadow = true;
    this.outline = new THREE.Mesh(BODY, OUTLINE);
    this.outline.scale.set(1.07, 0.9 * 1.07, 1.07);
    this.pivot.add(body, this.outline);

    for (const s of [-1, 1]) {
      const eye = new THREE.Mesh(EYE, WHITE);
      eye.position.set(s * 0.3, 0.2, 0.6);
      const pupil = new THREE.Mesh(PUPIL, INK);
      pupil.position.set(s * 0.3, 0.2, 0.78);
      this.pivot.add(eye, pupil);
    }
    const stalk = new THREE.Mesh(STALK, INK);
    stalk.position.y = 0.88;
    const tip = new THREE.Mesh(TIP, this.tipMat);
    tip.position.y = 1.12;
    tip.castShadow = true;
    this.pivot.add(stalk, tip);

    this.label = makeLabel(name, me);
    this.group.add(this.label);

    if (me) {
      this.mark = new THREE.Mesh(MARK, MARK_MAT);
      this.mark.position.y = 0.04;
      this.group.add(this.mark);
    }

    this.seed = Math.random() * 10;
    this.speed = 0;
    this.squash = 0;
    this.prev = null;
    this.ghost = false;
  }

  bump(power) {
    this.squash = Math.min(1, this.squash + power * 0.08);
  }

  // Returns 'splash' on the frame the blob hits the water
  update(s, dt, t) {
    let result = null;
    if (this.prev && dt > 0) {
      const sp = Math.hypot(s.x - this.prev.x, s.z - this.prev.z) / dt;
      this.speed += (sp - this.speed) * Math.min(1, dt * 10);
      if (this.prev.y > -0.75 && s.y <= -0.75) result = 'splash';
    }
    this.prev = { x: s.x, y: s.y, z: s.z };

    const falling = (s.flags & 4) !== 0;
    const dashing = (s.flags & 1) !== 0;
    const ghost = (s.flags & 2) !== 0;

    this.group.position.set(s.x, Math.max(s.y, -30), s.z);
    this.group.rotation.y = s.a;

    this.squash = Math.max(0, this.squash - dt * 4);
    const sq = this.squash * Math.sin(t * 40) * 0.5 + this.squash * 0.5;
    let sx = 1 + sq * 0.3, sy = 1 - sq * 0.35, sz = 1 + sq * 0.3;
    if (dashing) { sx *= 0.82; sy *= 0.85; sz *= 1.32; }
    this.pivot.scale.x += (sx - this.pivot.scale.x) * Math.min(1, dt * 18);
    this.pivot.scale.y += (sy - this.pivot.scale.y) * Math.min(1, dt * 18);
    this.pivot.scale.z += (sz - this.pivot.scale.z) * Math.min(1, dt * 18);

    const hop = falling ? 0 : Math.abs(Math.sin(t * 13 + this.seed)) * 0.16 * Math.min(this.speed / 7, 1);
    this.pivot.position.y = 0.72 + hop;
    this.pivot.rotation.x = falling ? this.pivot.rotation.x + dt * 9 : this.pivot.rotation.x * Math.max(0, 1 - dt * 12);
    this.pivot.rotation.z = Math.sin(t * 13 + this.seed) * 0.08 * Math.min(this.speed / 7, 1);

    if (ghost !== this.ghost) {
      this.ghost = ghost;
      this.mat.transparent = ghost;
      this.mat.needsUpdate = true;
      this.outline.visible = !ghost;
      if (!ghost) this.mat.opacity = 1;
    }
    if (ghost) this.mat.opacity = 0.45 + Math.sin(t * 22) * 0.2;

    if (this.mark) this.mark.visible = !falling;
    this.label.visible = s.y > -2;
    return result;
  }

  dispose() {
    this.group.removeFromParent();
    this.mat.dispose();
    this.tipMat.dispose();
    this.label.material.map.dispose();
    this.label.material.dispose();
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
  sprite.position.y = 2.35;
  sprite.renderOrder = 10;
  return sprite;
}
