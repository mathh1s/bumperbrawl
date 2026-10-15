import * as THREE from 'three';
import { TEAMS } from './modes.js';

// Blob Ball props: the ball, both goals and the low fence that keeps the ball on the island.
// Sizes match server/mode_ball.go.

const BALL_R = 1.05;
const GOAL_X = 13.0;
const MOUTH = 3.0;
const FENCE_R = 15.0;
const OUTLINE = new THREE.MeshBasicMaterial({ color: '#2d2440', side: THREE.BackSide });

// a white icosphere with dark pentagons around the twelve original corners, like a football
function ballGeometry() {
  const geo = new THREE.IcosahedronGeometry(BALL_R, 2);
  const corners = new THREE.IcosahedronGeometry(1, 0).getAttribute('position');
  const dirs = [];
  for (let i = 0; i < corners.count; i++) {
    const v = new THREE.Vector3().fromBufferAttribute(corners, i).normalize();
    if (!dirs.some((d) => d.distanceTo(v) < 1e-3)) dirs.push(v);
  }
  const pos = geo.getAttribute('position');
  const colors = new Float32Array(pos.count * 3);
  const c = new THREE.Vector3();
  const dark = new THREE.Color('#2d2440'), light = new THREE.Color('#ffffff');
  for (let f = 0; f < pos.count; f += 3) {
    c.set(0, 0, 0);
    for (let k = 0; k < 3; k++) c.add(new THREE.Vector3().fromBufferAttribute(pos, f + k));
    c.normalize();
    const col = dirs.some((d) => d.dot(c) > 0.93) ? dark : light;
    for (let k = 0; k < 3; k++) col.toArray(colors, (f + k) * 3);
  }
  geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  return geo;
}

function goal(side, color, ramp) {
  const g = new THREE.Group();
  const mat = new THREE.MeshToonMaterial({ color, gradientMap: ramp });
  const post = new THREE.CylinderGeometry(0.16, 0.16, 2.6, 10);
  for (const z of [-MOUTH - 0.2, MOUTH + 0.2]) {
    const m = new THREE.Mesh(post, mat);
    m.position.set(0, 1.3, z);
    m.castShadow = true;
    g.add(m);
  }
  const bar = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.16, MOUTH * 2 + 0.4, 10).rotateX(Math.PI / 2), mat);
  bar.position.y = 2.6;
  bar.castShadow = true;
  const net = new THREE.Mesh(
    new THREE.BoxGeometry(1.6, 2.6, MOUTH * 2 + 0.4, 4, 6, 12),
    new THREE.MeshBasicMaterial({ color: '#ffffff', wireframe: true, transparent: true, opacity: 0.55 }),
  );
  net.position.set(side * 0.8, 1.3, 0);
  const line = new THREE.Mesh(
    new THREE.PlaneGeometry(0.22, MOUTH * 2).rotateX(-Math.PI / 2),
    new THREE.MeshBasicMaterial({ color: '#ffffff', transparent: true, opacity: 0.85 }),
  );
  // the goal frame stands just behind the scoring line, which is drawn on the grass
  line.position.set(-side * 0.9, 0.05, 0);
  g.add(bar, net, line);
  g.position.x = side * (GOAL_X + 0.9);
  return g;
}

export class BallPitch {
  constructor(scene, ramp) {
    this.group = new THREE.Group();
    this.group.visible = false;
    scene.add(this.group);

    this.ball = new THREE.Group();
    const mesh = new THREE.Mesh(ballGeometry(), new THREE.MeshToonMaterial({ vertexColors: true, gradientMap: ramp, flatShading: true }));
    mesh.castShadow = true;
    const outline = new THREE.Mesh(new THREE.SphereGeometry(BALL_R, 24, 16), OUTLINE);
    outline.scale.setScalar(1.07);
    this.spin = new THREE.Group();
    this.spin.add(mesh);
    this.ball.add(this.spin, outline);
    this.group.add(this.ball);

    // red attacks +x, so the goal there is blue's to defend
    this.group.add(goal(1, TEAMS[2].color, ramp), goal(-1, TEAMS[1].color, ramp));

    const gap = Math.asin(MOUTH / FENCE_R) + 0.04;
    const fenceMat = new THREE.MeshToonMaterial({ color: '#f1e3c6', gradientMap: ramp, side: THREE.DoubleSide });
    // cylinder angles start at +z, so +x sits at a quarter turn and -x at three quarters
    for (const start of [Math.PI / 2 + gap, Math.PI * 1.5 + gap]) {
      const fence = new THREE.Mesh(new THREE.CylinderGeometry(FENCE_R, FENCE_R, 0.55, 64, 1, true, start, Math.PI - gap * 2), fenceMat);
      fence.position.y = 0.27;
      fence.castShadow = true;
      this.group.add(fence);
    }
    this.last = null;
    this.pop = 1;
  }

  // bl is [x, z, y, hidden, red goals, blue goals] or undefined outside Blob Ball
  update(bl, dt) {
    this.group.visible = !!bl;
    if (!bl) {
      this.last = null;
      return;
    }
    const [x, z, y, hidden] = bl;
    this.ball.visible = !hidden;
    if (hidden) {
      this.last = null;
      this.pop = 0;
      return;
    }
    this.pop = Math.min(1, this.pop + dt * 4);
    this.ball.scale.setScalar(0.4 + 0.6 * this.pop);
    this.ball.position.set(x, BALL_R + y, z);
    if (this.last) {
      const dx = x - this.last.x, dz = z - this.last.z;
      const d = Math.hypot(dx, dz);
      // roll without slipping: turn about the horizontal axis across the motion
      if (d > 1e-4 && d < 3) this.spin.rotateOnWorldAxis(new THREE.Vector3(dz / d, 0, -dx / d), d / BALL_R);
    }
    this.last = { x, z };
  }
}
