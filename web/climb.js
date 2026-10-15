import * as THREE from 'three';

// King of the Hill: the mountain course, its spinning arms, the summit flag and the rising
// slime. The course comes from the server (server/mode_climb.go) and groundAt mirrors its
// height lookup, so your own predicted blob stands on the slope at the right height.

const OUTLINE = new THREE.MeshBasicMaterial({ color: '#2d2440', side: THREE.BackSide });
const THICK = 1.0;
const RAMP_COLORS = ['#ff8fab', '#b197fc'];

// segments arrive as [ax, az, bx, bz, w, ay, by], with 1000 added to by on landings
function decode(list) {
  let start = 0;
  return list.map(([ax, az, bx, bz, w, ay, by]) => {
    const landing = by >= 500;
    const s = { ax, az, bx, bz, w, ay, by: landing ? by - 1000 : by, landing, start };
    s.len = Math.hypot(bx - ax, bz - az);
    start += s.len;
    return s;
  });
}

function onSeg(s, x, z) {
  const dx = s.bx - s.ax, dz = s.bz - s.az;
  const along = ((x - s.ax) * dx + (z - s.az) * dz) / s.len;
  const perp = Math.abs((x - s.ax) * dz - (z - s.az) * dx) / s.len;
  const pad = s.landing ? s.w / 2 : 0;
  if (along < -pad || along > s.len + pad || perp > s.w / 2) return null;
  const t = Math.max(0, Math.min(1, along / s.len));
  return s.ay + (s.by - s.ay) * t;
}

export class Climb {
  constructor(scene, ramp) {
    this.scene = scene;
    this.ramp = ramp;
    this.group = new THREE.Group();
    this.group.visible = false;
    scene.add(this.group);
    this.segs = [];
    this.armMeshes = [];
    this.key = '';

    this.slime = new THREE.Mesh(
      new THREE.PlaneGeometry(400, 400).rotateX(-Math.PI / 2),
      new THREE.MeshToonMaterial({ color: '#7ee35f', emissive: '#2f7d1c', gradientMap: ramp, transparent: true, opacity: 0.92 }),
    );
    this.slime.renderOrder = 2;
    this.group.add(this.slime);
    this.t = 0;
  }

  // the height of the course under a point, preferring the stretch nearest the given height
  groundAt(x, z, near) {
    let best = Infinity, out = null;
    for (const s of this.segs) {
      const h = onSeg(s, x, z);
      if (h !== null && Math.abs(h - near) <= best + 0.01) {
        best = Math.min(best, Math.abs(h - near));
        out = h;
      }
    }
    return out;
  }

  build(segs, arms) {
    for (const m of this.built ?? []) m.removeFromParent();
    this.built = [];
    this.segs = decode(segs);
    const toon = (color) => new THREE.MeshToonMaterial({ color, gradientMap: this.ramp });
    let rampNo = 0;
    this.segs.forEach((s, i) => {
      const last = i === this.segs.length - 1;
      const color = last ? '#ffc61a' : s.landing ? '#ffe066' : RAMP_COLORS[rampNo++ % 2];
      const len = s.len + (s.landing ? s.w : 0);
      const geo = new THREE.BoxGeometry(len, THICK, s.w);
      const mesh = new THREE.Mesh(geo, toon(color));
      mesh.castShadow = mesh.receiveShadow = true;
      const outline = new THREE.Mesh(geo, OUTLINE);
      outline.scale.set(1 + 0.12 / len, 1.12, 1 + 0.12 / s.w);
      const g = new THREE.Group();
      g.add(mesh, outline);
      g.position.set((s.ax + s.bx) / 2, (s.ay + s.by) / 2 - THICK / 2, (s.az + s.bz) / 2);
      g.rotation.order = 'YZX';
      g.rotation.set(0, Math.atan2(-(s.bz - s.az), s.bx - s.ax), Math.atan2(s.by - s.ay, s.len));
      this.group.add(g);
      this.built.push(g);
    });

    // a flag on the summit
    const top = this.segs[this.segs.length - 1];
    const flag = new THREE.Group();
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.08, 3.4, 8), toon('#fffaf0'));
    pole.position.y = 1.7;
    const cloth = new THREE.Mesh(new THREE.PlaneGeometry(1.4, 0.9), new THREE.MeshToonMaterial({ color: '#ff6b6b', gradientMap: this.ramp, side: THREE.DoubleSide }));
    cloth.position.set(0.7, 2.95, 0);
    flag.add(pole, cloth);
    flag.position.set(top.bx, top.by, top.bz);
    this.flag = cloth;
    this.group.add(flag);
    this.built.push(flag);

    this.armMeshes = arms.map(([x, z, y, len]) => {
      const g = new THREE.Group();
      g.position.set(x, y, z);
      const post = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.34, 1.1, 10), toon('#495057'));
      post.position.y = 0.3;
      const bar = new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.35, len * 2, 12).rotateZ(Math.PI / 2), toon('#ff6b6b'));
      bar.position.y = 0.55;
      bar.castShadow = true;
      for (const s of [-1, 1]) {
        const cap = new THREE.Mesh(new THREE.SphereGeometry(0.42, 12, 8), toon('#fffaf0'));
        cap.position.set(s * len, 0.55, 0);
        g.add(cap);
      }
      g.add(post, bar);
      this.group.add(g);
      this.built.push(g);
      return g;
    });
  }

  // cr is {s: segments, a: [[x, z, y, len, angle]], sl: slime height}, or undefined outside the mode
  update(cr, dt) {
    this.group.visible = !!cr;
    if (!cr) return;
    const key = `${cr.s.length}:${cr.a.length}`;
    if (key !== this.key) {
      this.key = key;
      this.build(cr.s, cr.a);
    }
    this.t += dt;
    cr.a.forEach(([, , , , angle], i) => {
      if (this.armMeshes[i]) this.armMeshes[i].rotation.y = -angle;
    });
    this.slime.position.y = cr.sl + Math.sin(this.t * 1.7) * 0.06;
    this.flag.rotation.y = Math.sin(this.t * 3) * 0.25;
  }
}
