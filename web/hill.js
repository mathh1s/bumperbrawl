import * as THREE from 'three';
import { PALETTE } from './blobs.js';

const EMPTY = new THREE.Color('#ffd43b');
const CONTESTED = new THREE.Color('#ff4d4d');
const OWNED = new THREE.Color();

export class HillRing {
  constructor(scene) {
    this.uniforms = { uColor: { value: new THREE.Color() }, uTime: { value: 0 }, uAlpha: { value: 0.5 } };
    const beam = new THREE.Mesh(
      new THREE.CylinderGeometry(1, 1, 3.2, 48, 1, true),
      new THREE.ShaderMaterial({
        uniforms: this.uniforms,
        transparent: true,
        depthWrite: false,
        side: THREE.DoubleSide,
        vertexShader: `
          varying float vH;
          void main() {
            vH = position.y / 3.2 + 0.5;
            gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
          }`,
        fragmentShader: `
          uniform vec3 uColor;
          uniform float uTime;
          uniform float uAlpha;
          varying float vH;
          void main() {
            float fade = pow(1.0 - vH, 1.6);
            float bands = 0.7 + 0.3 * sin(vH * 22.0 - uTime * 5.0);
            gl_FragColor = vec4(uColor, fade * bands * uAlpha);
            #include <colorspace_fragment>
          }`,
      }),
    );
    beam.position.y = 1.6;
    beam.renderOrder = 5;

    this.edgeMat = new THREE.MeshBasicMaterial({ color: '#ffffff' });
    const edge = new THREE.Mesh(new THREE.RingGeometry(0.88, 1, 64).rotateX(-Math.PI / 2), this.edgeMat);
    edge.position.y = 0.05;
    const outline = new THREE.Mesh(new THREE.RingGeometry(1, 1.06, 64).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial({ color: '#2d2440' }));
    outline.position.y = 0.05;
    this.floorMat = new THREE.MeshBasicMaterial({ color: '#ffffff', transparent: true, opacity: 0.32, depthWrite: false });
    const floor = new THREE.Mesh(new THREE.CircleGeometry(0.88, 48).rotateX(-Math.PI / 2), this.floorMat);
    floor.position.y = 0.04;

    this.group = new THREE.Group();
    this.group.add(beam, edge, outline, floor);
    this.group.visible = false;
    scene.add(this.group);
    this.color = new THREE.Color();
  }

  // hl is [x, z, radius, ownerId, contested] from the server; colorOf maps a player id to its palette index
  update(hl, dt, t, colorOf) {
    if (!hl) {
      this.group.visible = false;
      return;
    }
    const [x, z, r, owner, contested] = hl;
    if (!this.group.visible) this.group.position.set(x, 0, z);
    this.group.visible = true;
    this.group.position.x += (x - this.group.position.x) * Math.min(1, dt * 6);
    this.group.position.z += (z - this.group.position.z) * Math.min(1, dt * 6);
    this.group.scale.set(r, 1, r);

    const target = contested
      ? (Math.sin(t * 14) > 0 ? CONTESTED : EMPTY)
      : owner ? OWNED.set(PALETTE[colorOf(owner)] ?? '#ffffff') : EMPTY;
    this.color.lerp(target, Math.min(1, dt * 10));
    this.uniforms.uColor.value.copy(this.color);
    this.uniforms.uTime.value = t;
    this.uniforms.uAlpha.value = owner || contested ? 0.85 : 0.6;
    this.edgeMat.color.copy(this.color);
    this.floorMat.color.copy(this.color);
  }
}
