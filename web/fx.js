import * as THREE from 'three';

const GEO = new THREE.IcosahedronGeometry(1, 0);
const BALL = new THREE.SphereGeometry(1, 8, 6);
const RING = new THREE.RingGeometry(0.7, 1, 40).rotateX(-Math.PI / 2);
const MAX_PARTS = 400;
const mats = new Map();

function mat(color, soft = false) {
  const key = color + soft;
  if (!mats.has(key)) {
    mats.set(key, soft
      ? new THREE.MeshLambertMaterial({ color, emissive: color, emissiveIntensity: 0.4 })
      : new THREE.MeshBasicMaterial({ color }));
  }
  return mats.get(key);
}

function starTexture() {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d');
  g.translate(64, 64);
  g.beginPath();
  for (let i = 0; i < 16; i++) {
    const r = i % 2 === 0 ? 60 : 16;
    const a = (i / 16) * Math.PI * 2;
    g.lineTo(Math.cos(a) * r, Math.sin(a) * r);
  }
  g.closePath();
  g.fillStyle = '#fff6c4';
  g.fill();
  g.lineWidth = 6;
  g.strokeStyle = '#ffb63b';
  g.stroke();
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

export class FX {
  constructor(scene) {
    this.scene = scene;
    this.parts = [];
    this.rings = [];
    this.stars = [];
    this.texts = [];
    this.starMap = starTexture();
  }

  text(x, y, z, str, color) {
    const c = document.createElement('canvas');
    c.width = 384;
    c.height = 96;
    const g = c.getContext('2d');
    g.font = '700 52px Fredoka, ui-rounded, sans-serif';
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    g.lineJoin = 'round';
    g.lineWidth = 12;
    g.strokeStyle = '#2d2440';
    g.strokeText(str, 192, 50);
    g.fillStyle = color;
    g.fillText(str, 192, 50);
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false, depthTest: false }));
    s.scale.set(4, 1, 1);
    s.position.set(x, y, z);
    s.renderOrder = 21;
    this.scene.add(s);
    this.texts.push({ s, life: 1.3, max: 1.3 });
  }

  burst(x, y, z, { colors = ['#ffffff'], n = 10, speed = 5, up = 4, life = 0.6, size = 0.15, gravity = 14, soft = false, grow = false } = {}) {
    for (let i = 0; i < n && this.parts.length < MAX_PARTS; i++) {
      const m = new THREE.Mesh(soft ? BALL : GEO, mat(colors[i % colors.length], soft));
      const a = Math.random() * Math.PI * 2;
      const s = speed * (0.4 + Math.random() * 0.6);
      m.position.set(x, y, z);
      m.rotation.set(Math.random() * 3, Math.random() * 3, 0);
      const sz = size * (0.6 + Math.random() * 0.8);
      m.scale.setScalar(grow ? sz * 0.3 : sz);
      this.scene.add(m);
      const l = life * (0.7 + Math.random() * 0.5);
      this.parts.push({
        m, sz, life: l, max: l, gravity, grow,
        vx: Math.sin(a) * s, vy: up * (0.5 + Math.random() * 0.8), vz: Math.cos(a) * s,
      });
    }
  }

  ring(x, z, color = '#ffffff', size = 2.5, y = 0.12) {
    const m = new THREE.Mesh(RING, new THREE.MeshBasicMaterial({ color, transparent: true, depthWrite: false }));
    m.position.set(x, y, z);
    this.scene.add(m);
    this.rings.push({ m, life: 0.45, max: 0.45, size });
  }

  star(x, y, z, size) {
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: this.starMap, transparent: true, depthWrite: false, depthTest: false }));
    s.position.set(x, y, z);
    s.renderOrder = 20;
    s.material.rotation = Math.random() * Math.PI;
    this.scene.add(s);
    this.stars.push({ s, life: 0.22, max: 0.22, size });
  }

  // ==== presets ====

  bump(x, z, power) {
    const k = Math.min(1, power / 20);
    this.star(x, 0.9, z, 0.7 + k * 1.1);
    this.burst(x, 0.9, z, { colors: ['#ffd43b', '#ffffff', '#ff922b'], n: 4 + Math.round(k * 8), speed: 3 + k * 4, up: 3, size: 0.11, life: 0.45 });
    if (power > 12) this.ring(x, z, '#ffffff', 2 + k * 2);
  }

  splash(x, z, scale = 1) {
    this.burst(x, -0.4, z, { colors: ['#ffffff', '#d9f6ff', '#7fe0f0'], n: Math.round(18 * scale), speed: 3.5 * scale, up: 9 * scale, life: 0.9, size: 0.18 * scale, gravity: 22, soft: true });
    this.ring(x, z, '#ffffff', 3 * scale, -0.55);
  }

  dust(x, y, z) {
    this.burst(x, y, z, { colors: ['#e8d3b0', '#d4b98e', '#f5ead6'], n: 7, speed: 1.6, up: 1.4, life: 0.8, size: 0.3, gravity: 1, soft: true, grow: true });
  }

  pound(x, z) {
    this.ring(x, z, '#ffffff', 6);
    this.ring(x, z, '#ff922b', 4.5);
    this.burst(x, 0.3, z, { colors: ['#e8d3b0', '#d4b98e', '#ffffff'], n: 18, speed: 7, up: 2, life: 0.7, size: 0.32, gravity: 3, soft: true, grow: true });
  }

  pickup(x, z, color) {
    this.burst(x, 1, z, { colors: [color, '#ffffff', '#ffd43b'], n: 16, speed: 3, up: 6, life: 0.7, size: 0.14 });
    this.ring(x, z, color, 2.5);
  }

  puff(x, z) {
    this.burst(x, 0.25, z, { colors: ['#ffffff', '#f1e3c8'], n: 6, speed: 2.2, up: 1.5, life: 0.5, size: 0.22, gravity: 2, soft: true, grow: true });
  }

  update(dt) {
    for (let i = this.parts.length - 1; i >= 0; i--) {
      const p = this.parts[i];
      p.life -= dt;
      if (p.life <= 0) {
        p.m.removeFromParent();
        this.parts.splice(i, 1);
        continue;
      }
      p.vy -= p.gravity * dt;
      p.vx *= 1 - dt * 1.5;
      p.vz *= 1 - dt * 1.5;
      p.m.position.x += p.vx * dt;
      p.m.position.y += p.vy * dt;
      p.m.position.z += p.vz * dt;
      p.m.rotation.x += dt * 6;
      const k = p.life / p.max;
      // grow particles swell first, then shrink away like a puff of smoke
      p.m.scale.setScalar(p.grow ? p.sz * Math.sin(Math.PI * Math.min(1, (1 - k) * 1.3 + 0.15)) : p.sz * k);
    }
    for (let i = this.rings.length - 1; i >= 0; i--) {
      const r = this.rings[i];
      r.life -= dt;
      if (r.life <= 0) {
        r.m.removeFromParent();
        r.m.material.dispose();
        this.rings.splice(i, 1);
        continue;
      }
      const k = 1 - r.life / r.max;
      r.m.scale.setScalar(0.4 + (1 - (1 - k) ** 2) * r.size);
      r.m.material.opacity = 1 - k;
    }
    for (let i = this.stars.length - 1; i >= 0; i--) {
      const s = this.stars[i];
      s.life -= dt;
      if (s.life <= 0) {
        s.s.removeFromParent();
        s.s.material.dispose();
        this.stars.splice(i, 1);
        continue;
      }
      const k = 1 - s.life / s.max;
      s.s.scale.setScalar(s.size * (k < 0.3 ? k / 0.3 : 1 - (k - 0.3) * 0.6));
      s.s.material.opacity = 1 - Math.max(0, k - 0.5) * 2;
    }
    for (let i = this.texts.length - 1; i >= 0; i--) {
      const tx = this.texts[i];
      tx.life -= dt;
      if (tx.life <= 0) {
        tx.s.removeFromParent();
        tx.s.material.map.dispose();
        tx.s.material.dispose();
        this.texts.splice(i, 1);
        continue;
      }
      const k = 1 - tx.life / tx.max;
      tx.s.position.y += dt * 1.4;
      tx.s.material.opacity = Math.min(1, (1 - k) / 0.4);
      const pop = k < 0.15 ? 0.6 + (k / 0.15) * 0.5 : 1.1 - Math.min(0.1, (k - 0.15));
      tx.s.scale.set(4 * pop, pop, 1);
    }
  }
}
