import * as THREE from 'three';
import { Blob } from './blobs.js';

export class Preview {
  constructor(canvas, ramp) {
    this.canvas = canvas;
    this.ramp = ramp;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(28, 1, 0.1, 50);
    this.camera.position.set(0, 2.0, 7);
    this.camera.lookAt(0, 0.8, 0);
    this.scene.add(new THREE.HemisphereLight('#ffffff', '#b59a7a', 1.8));
    const sun = new THREE.DirectionalLight('#fff0d6', 2.4);
    sun.position.set(3, 6, 5);
    this.scene.add(sun);

    const stand = new THREE.Mesh(
      new THREE.CylinderGeometry(1.15, 1.05, 0.25, 6),
      new THREE.MeshToonMaterial({ color: '#86d05e', gradientMap: ramp }),
    );
    stand.position.y = -0.125;
    this.scene.add(stand);

    this.t = 0;
    this.blob = null;
    canvas.addEventListener('pointerdown', () => this.blob?.bump(14));
  }

  set(color, hat) {
    this.blob?.dispose();
    this.blob = new Blob({ name: '', color, hat, ramp: this.ramp, label: false });
    this.blob.jellyV = 4;
    this.scene.add(this.blob.group);
  }

  render(dt) {
    if (!this.blob || !this.canvas.offsetParent) return;
    const w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    if (this.canvas.width !== Math.round(w * this.renderer.getPixelRatio())) {
      this.renderer.setSize(w, h, false);
      this.camera.aspect = w / h;
      this.camera.updateProjectionMatrix();
    }
    this.t += dt;
    this.blob.update({ x: 0, z: 0, y: 0, a: Math.sin(this.t * 0.8) * 0.6, flags: 0 }, dt, this.t);
    this.renderer.render(this.scene, this.camera);
  }
}
