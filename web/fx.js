import * as THREE from 'three';

const GEO = new THREE.IcosahedronGeometry(1, 0);
const RING = new THREE.RingGeometry(0.7, 1, 36).rotateX(-Math.PI / 2);
const MAX_PARTS = 500;
const mats = new Map();

function mat(color) {
  if (!mats.has(color)) mats.set(color, new THREE.MeshBasicMaterial({ color }));
  return mats.get(color);
}

export class FX {
  constructor(scene) {
    this.scene = scene;
    this.parts = [];
    this.rings = [];
  }

  burst(x, y, z, { colors = ['#ffffff'], n = 10, speed = 5, up = 4, life = 0.6, size = 0.15, gravity = 14 } = {}) {
    for (let i = 0; i < n && this.parts.length < MAX_PARTS; i++) {
      const m = new THREE.Mesh(GEO, mat(colors[i % colors.length]));
      const a = Math.random() * Math.PI * 2;
      const s = speed * (0.4 + Math.random() * 0.6);
      m.position.set(x, y, z);
      m.rotation.set(Math.random() * 3, Math.random() * 3, 0);
      const sz = size * (0.6 + Math.random() * 0.8);
      m.scale.setScalar(sz);
      this.scene.add(m);
      this.parts.push({
        m, sz, life, max: life, gravity,
        vx: Math.sin(a) * s, vy: up * (0.5 + Math.random() * 0.8), vz: Math.cos(a) * s,
      });
    }
  }

  ring(x, z, color = '#ffffff', size = 2.5) {
    const m = new THREE.Mesh(RING, new THREE.MeshBasicMaterial({ color, transparent: true, depthWrite: false }));
    m.position.set(x, 0.12, z);
    this.scene.add(m);
    this.rings.push({ m, life: 0.4, max: 0.4, size });
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
      p.m.position.x += p.vx * dt;
      p.m.position.y += p.vy * dt;
      p.m.position.z += p.vz * dt;
      p.m.rotation.x += dt * 6;
      p.m.scale.setScalar(p.sz * (p.life / p.max));
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
      r.m.scale.setScalar(0.4 + k * r.size);
      r.m.material.opacity = 1 - k;
    }
  }
}
