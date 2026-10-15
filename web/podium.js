import * as THREE from 'three';
import { Blob, PALETTE } from './blobs.js';
import { SKY } from './world.js';

const PLACES = [
  { x: 0, h: 1.6, color: '#ffc61a', label: '1' },
  { x: -2.4, h: 1.05, color: '#c9d2dc', label: '2' },
  { x: 2.4, h: 0.65, color: '#e09a5b', label: '3' },
];
const CONFETTI = 160;

function numberTexture(text, color) {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d');
  g.fillStyle = color;
  g.fillRect(0, 0, 128, 128);
  g.font = '700 84px Fredoka, ui-rounded, sans-serif';
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  g.lineWidth = 10;
  g.strokeStyle = '#2d2440';
  g.strokeText(text, 64, 70);
  g.fillStyle = '#ffffff';
  g.fillText(text, 64, 70);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function skyTexture() {
  const c = document.createElement('canvas');
  c.width = 2;
  c.height = 256;
  const g = c.getContext('2d');
  const grad = g.createLinearGradient(0, 0, 0, 256);
  grad.addColorStop(0, SKY.top);
  grad.addColorStop(1, SKY.horizon);
  g.fillStyle = grad;
  g.fillRect(0, 0, 2, 256);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

export class Podium {
  constructor(ramp) {
    this.ramp = ramp;
    this.active = false;
    this.scene = new THREE.Scene();
    this.scene.background = skyTexture();
    this.camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100);
    this.scene.add(new THREE.HemisphereLight('#d6ecff', '#8a6a4a', 1.5));
    const sun = new THREE.DirectionalLight('#fff0d6', 2.6);
    sun.position.set(4, 10, 8);
    sun.castShadow = true;
    sun.shadow.mapSize.set(1024, 1024);
    this.scene.add(sun);

    const ground = new THREE.Mesh(new THREE.CylinderGeometry(7, 7.4, 0.6, 6), new THREE.MeshToonMaterial({ color: '#86d05e', gradientMap: ramp }));
    ground.position.y = -0.3;
    ground.receiveShadow = true;
    this.scene.add(ground);

    for (const p of PLACES) {
      const side = new THREE.MeshToonMaterial({ color: p.color, gradientMap: ramp });
      const front = new THREE.MeshToonMaterial({ map: numberTexture(p.label, p.color), gradientMap: ramp });
      const block = new THREE.Mesh(new THREE.BoxGeometry(2.1, p.h, 1.8), [side, side, side, side, front, side]);
      block.position.set(p.x, p.h / 2, 0);
      block.castShadow = block.receiveShadow = true;
      this.scene.add(block);
    }

    const geo = new THREE.PlaneGeometry(0.14, 0.24);
    this.confetti = [];
    for (let i = 0; i < CONFETTI; i++) {
      const m = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: PALETTE[i % PALETTE.length], side: THREE.DoubleSide }));
      this.scene.add(m);
      this.confetti.push({ m, spin: new THREE.Vector3(Math.random() * 6, Math.random() * 6, Math.random() * 6) });
    }
    this.blobs = [];
  }

  show(top, suffix = '') {
    this.hide();
    top.slice(0, PLACES.length).forEach((e, i) => {
      const b = new Blob({ name: `${e.n}  ${e.s}${suffix}`, color: e.c, hat: e.h, ramp: this.ramp });
      b.group.position.set(PLACES[i].x, PLACES[i].h, 0.1);
      if (i === 0) b.setCrown(true, this.ramp);
      this.scene.add(b.group);
      this.blobs.push({ b, base: PLACES[i].h, x: PLACES[i].x, hopT: 0.4 + i * 0.3 });
    });
    for (const c of this.confetti) {
      c.m.position.set((Math.random() - 0.5) * 12, 3 + Math.random() * 10, (Math.random() - 0.5) * 6);
    }
    this.t = 0;
    this.active = true;
    document.body.classList.add('podium');
  }

  hide() {
    for (const { b } of this.blobs) b.dispose();
    this.blobs = [];
    this.active = false;
    document.body.classList.remove('podium');
  }

  render(renderer, dt) {
    this.t += dt;
    const aspect = renderer.domElement.clientWidth / renderer.domElement.clientHeight;
    this.camera.aspect = aspect;
    this.camera.fov = aspect < 1 ? 55 : 40;
    this.camera.updateProjectionMatrix();
    // back off until all three pedestals fit the screen width, which matters on portrait phones
    const halfH = Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2));
    const dist = Math.max(9.5, 4.4 / (halfH * aspect));
    this.camera.position.set(Math.sin(this.t * 0.25) * 1.2, 2.2 + dist * 0.13, dist);
    this.camera.lookAt(0, 2.3, 0);

    for (const e of this.blobs) {
      e.hopT -= dt;
      if (e.hopT <= 0) {
        e.hopT = 0.9 + Math.random() * 0.8;
        e.vy = 5;
        e.b.bump(6);
      }
      e.vy = (e.vy ?? 0) - 18 * dt;
      e.y = Math.max(0, (e.y ?? 0) + e.vy * dt);
      e.b.update({ x: e.x, z: 0.1, y: e.base + e.y, a: Math.sin(this.t + e.x) * 0.3, flags: 0, ch: 0 }, dt, this.t);
    }
    for (const c of this.confetti) {
      c.m.position.y -= dt * 2.2;
      c.m.position.x += Math.sin(this.t * 2 + c.spin.x) * dt * 0.6;
      c.m.rotation.x += c.spin.x * dt;
      c.m.rotation.y += c.spin.y * dt;
      if (c.m.position.y < -0.2) c.m.position.y = 10 + Math.random() * 3;
    }
    renderer.render(this.scene, this.camera);
  }
}
