import * as THREE from 'three';

export const POWERS = {
  1: { name: 'Heavy', color: '#9775fa', blurb: 'nobody moves you' },
  2: { name: 'Bouncy', color: '#51cf66', blurb: 'your hits launch' },
  3: { name: 'Ground pound', color: '#ff922b', blurb: 'slam!' },
};

function iconTexture(kind) {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d');
  g.fillStyle = '#c98b4f';
  g.fillRect(0, 0, 128, 128);
  g.strokeStyle = '#8a5a30';
  g.lineWidth = 10;
  g.strokeRect(5, 5, 118, 118);
  g.fillStyle = POWERS[kind].color;
  g.beginPath();
  g.arc(64, 64, 38, 0, Math.PI * 2);
  g.fill();
  g.lineWidth = 6;
  g.strokeStyle = '#2d2440';
  g.stroke();
  g.fillStyle = '#ffffff';
  g.strokeStyle = '#2d2440';
  g.lineWidth = 5;
  g.lineJoin = 'round';
  g.beginPath();
  if (kind === 1) {
    // kettlebell weight
    g.moveTo(44, 84); g.lineTo(84, 84); g.lineTo(78, 56); g.lineTo(50, 56); g.closePath();
    g.fill(); g.stroke();
    g.beginPath(); g.arc(64, 52, 10, Math.PI, 0); g.stroke();
  } else if (kind === 2) {
    // spring
    g.moveTo(48, 86);
    for (let i = 0; i < 5; i++) g.lineTo(i % 2 ? 48 : 80, 80 - i * 9);
    g.lineTo(64, 38);
    g.stroke();
  } else {
    // down arrow onto a line
    g.moveTo(56, 34); g.lineTo(72, 34); g.lineTo(72, 58); g.lineTo(82, 58); g.lineTo(64, 78); g.lineTo(46, 58); g.lineTo(56, 58); g.closePath();
    g.fill(); g.stroke();
    g.beginPath(); g.moveTo(40, 88); g.lineTo(88, 88); g.stroke();
  }
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

const BOX = new THREE.BoxGeometry(0.9, 0.9, 0.9);
const CANOPY = new THREE.SphereGeometry(1, 12, 6, 0, Math.PI * 2, 0, Math.PI / 2);
const SHADOW = new THREE.CircleGeometry(0.7, 20).rotateX(-Math.PI / 2);
const GLOW = new THREE.RingGeometry(0.75, 0.95, 32).rotateX(-Math.PI / 2);

export class Crates {
  constructor(scene, ramp) {
    this.scene = scene;
    this.ramp = ramp;
    this.items = new Map();
    this.mats = {};
    for (const k of [1, 2, 3]) this.mats[k] = new THREE.MeshToonMaterial({ map: iconTexture(k), gradientMap: ramp });
    this.canopyMat = new THREE.MeshToonMaterial({ color: '#fffaf0', gradientMap: ramp, side: THREE.DoubleSide });
    this.lineMat = new THREE.LineBasicMaterial({ color: '#2d2440' });
    this.shadowMat = new THREE.MeshBasicMaterial({ color: '#2d2440', transparent: true, opacity: 0.25, depthWrite: false });
  }

  make(kind) {
    const group = new THREE.Group();
    const box = new THREE.Mesh(BOX, this.mats[kind]);
    box.castShadow = true;
    box.position.y = 0.45;
    group.add(box);

    const chute = new THREE.Group();
    const canopy = new THREE.Mesh(CANOPY, this.canopyMat);
    canopy.scale.set(1.1, 0.6, 1.1);
    canopy.position.y = 2.1;
    const pts = [];
    for (const [x, z] of [[1, 1], [-1, 1], [1, -1], [-1, -1]]) {
      pts.push(new THREE.Vector3(x * 0.4, 0.9, z * 0.4), new THREE.Vector3(x * 1.0, 2.1, z * 1.0));
    }
    chute.add(canopy, new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts), this.lineMat));
    group.add(chute);

    const shadow = new THREE.Mesh(SHADOW, this.shadowMat.clone());
    const glow = new THREE.Mesh(GLOW, new THREE.MeshBasicMaterial({ color: POWERS[kind].color, transparent: true, depthWrite: false }));
    this.scene.add(group, shadow, glow);
    return { group, box, chute, shadow, glow, y: null };
  }

  sync(list, dt, t) {
    const seen = new Set();
    for (const [id, kind, x, z, y] of list) {
      seen.add(id);
      let it = this.items.get(id);
      if (!it) {
        it = this.make(kind);
        this.items.set(id, it);
      }
      it.y = it.y === null ? y : it.y + (y - it.y) * Math.min(1, dt * 12);
      const landed = it.y < 0.05;
      it.group.position.set(x, it.y + (landed ? Math.sin(t * 3 + id) * 0.06 : 0), z);
      it.group.rotation.y += dt * (landed ? 1.2 : 0.4);
      it.chute.visible = !landed;
      it.shadow.position.set(x, 0.03, z);
      it.shadow.visible = !landed;
      it.shadow.material.opacity = 0.35 * (1 - Math.min(1, it.y / 16));
      it.shadow.scale.setScalar(0.5 + 0.5 * (1 - Math.min(1, it.y / 16)));
      it.glow.position.set(x, 0.04, z);
      it.glow.visible = landed;
      it.glow.material.opacity = 0.55 + Math.sin(t * 5 + id) * 0.3;
    }
    for (const [id, it] of this.items) {
      if (seen.has(id)) continue;
      it.group.removeFromParent();
      it.shadow.removeFromParent();
      it.glow.removeFromParent();
      it.shadow.material.dispose();
      it.glow.material.dispose();
      it.chute.children[1].geometry.dispose();
      this.items.delete(id);
    }
  }
}
