import * as THREE from 'three';

const COIN = new THREE.CylinderGeometry(0.46, 0.46, 0.12, 24).rotateX(Math.PI / 2);
const RIM = new THREE.TorusGeometry(0.46, 0.045, 6, 24);
const OUTLINE = new THREE.MeshBasicMaterial({ color: '#2d2440', side: THREE.BackSide });
const SPILL_TIME = 0.7;
const POP_TIME = 0.25;

export class Coins {
  constructor(scene, ramp) {
    this.scene = scene;
    this.items = new Map();
    this.flights = new Map();
    this.mat = new THREE.MeshToonMaterial({ color: '#ffc61a', gradientMap: ramp, emissive: '#6b4500' });
    this.rimMat = new THREE.MeshToonMaterial({ color: '#e09a1a', gradientMap: ramp });
  }

  // coins with these ids fly out of a knocked-off blob instead of popping up in place
  spill(ids, x, z) {
    for (const id of ids) {
      // the snapshot with these coins can render a moment before the event that explains them
      const c = this.items.get(id);
      if (c && c.age < 0.2) {
        c.from = { x, z };
        c.age = 0;
      } else {
        this.flights.set(id, { x, z });
      }
    }
  }

  sync(list, dt, t) {
    const seen = new Set();
    for (const [id, x, z] of list ?? []) {
      seen.add(id);
      let c = this.items.get(id);
      if (!c) {
        const group = new THREE.Group();
        const face = new THREE.Mesh(COIN, this.mat);
        face.castShadow = true;
        const outline = new THREE.Mesh(COIN, OUTLINE);
        outline.scale.set(1.12, 1.12, 1.6);
        group.add(face, new THREE.Mesh(RIM, this.rimMat), outline);
        this.scene.add(group);
        c = { group, age: 0, from: this.flights.get(id) ?? null, phase: Math.random() * 6 };
        this.flights.delete(id);
        this.items.set(id, c);
      }
      c.age += dt;
      let px = x, py = 0.7 + Math.sin(t * 3 + c.phase) * 0.08, pz = z;
      let scale = Math.min(1, c.age / POP_TIME);
      if (c.from && c.age < SPILL_TIME) {
        const k = c.age / SPILL_TIME;
        px = c.from.x + (x - c.from.x) * k;
        pz = c.from.z + (z - c.from.z) * k;
        py = 0.7 + Math.sin(Math.PI * k) * 4;
        scale = 1;
      }
      c.group.position.set(px, py, pz);
      c.group.scale.setScalar(scale);
      c.group.rotation.y = t * 3 + c.phase;
    }
    for (const [id, c] of this.items) {
      if (seen.has(id)) continue;
      c.group.removeFromParent();
      this.items.delete(id);
    }
  }
}
