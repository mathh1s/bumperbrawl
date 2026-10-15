import * as THREE from 'three';

const LOG_Y = 0.48;
const LOG_R = 0.46;
const DROP_TIME = 0.6;

function logGeometry() {
  const geo = new THREE.CylinderGeometry(LOG_R, LOG_R, 1, 14, 12).toNonIndexed();
  geo.rotateZ(Math.PI / 2);
  geo.computeVertexNormals();
  const pos = geo.attributes.position;
  const nor = geo.attributes.normal;
  const colors = [];
  const bark = [new THREE.Color('#8a5a3c'), new THREE.Color('#74492f')];
  const cut = new THREE.Color('#e3b97c');
  const ring = new THREE.Color('#b5824f');
  const c = new THREE.Color();
  for (let i = 0; i < pos.count; i++) {
    if (Math.abs(nor.getX(i)) > 0.9) {
      // end caps: a darker ring near the rim around the pale cut wood
      const r = Math.hypot(pos.getY(i), pos.getZ(i));
      c.copy(r > LOG_R * 0.75 ? ring : cut);
    } else {
      c.copy(bark[Math.floor((pos.getX(i) + 0.5) * 12 + 0.01) % 2]);
    }
    colors.push(c.r, c.g, c.b);
  }
  geo.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
  return geo;
}

export class Sweeper {
  constructor(scene, ramp, fx) {
    this.fx = fx;
    this.pivot = new THREE.Group();
    this.log = new THREE.Mesh(logGeometry(), new THREE.MeshToonMaterial({ vertexColors: true, gradientMap: ramp }));
    this.log.castShadow = true;
    this.pivot.add(this.log);
    this.pivot.visible = false;
    scene.add(this.pivot);
    this.dropT = 0;
    this.roll = 0;
    this.dustT = 0;
  }

  // sw is [angle, half length] from the server, or undefined while no log is out
  update(sw, dt) {
    if (!sw) {
      this.pivot.visible = false;
      this.dropT = 0;
      return;
    }
    const [angle, half] = sw;
    if (!this.pivot.visible) {
      this.pivot.visible = true;
      this.dropT = DROP_TIME;
      this.landed = false;
    }
    this.dropT = Math.max(0, this.dropT - dt);
    const k = this.dropT / DROP_TIME;
    this.pivot.position.y = LOG_Y + k * k * 12;
    if (!this.landed && this.dropT === 0) {
      this.landed = true;
      this.onLand?.();
      for (const s of [-1, 1]) this.fx.dust(Math.cos(angle) * (half - 0.6) * s, 0.3, Math.sin(angle) * (half - 0.6) * s);
    }

    const prev = this.pivot.rotation.y;
    this.pivot.rotation.y = -angle;
    this.log.scale.set(half * 2, 1, 1);
    const spun = Math.abs(Math.atan2(Math.sin(prev + angle), Math.cos(prev + angle)));
    this.roll += spun * half * 0.6;
    this.log.rotation.x = this.roll;

    this.dustT -= dt;
    if (this.landed && this.dustT <= 0) {
      this.dustT = 0.12;
      const s = Math.random() < 0.5 ? -1 : 1;
      this.fx.dust(Math.cos(angle) * (half - 0.6) * s, 0.15, Math.sin(angle) * (half - 0.6) * s);
    }
  }
}
