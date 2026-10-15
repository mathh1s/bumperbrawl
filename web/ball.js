import * as THREE from 'three';
import { TEAMS } from './modes.js';

// The Blob Ball stadium: a walled pitch that replaces the island for the round,
// the ball, and a goal at each end. Sizes match server/mode_ball.go.

const BALL_R = 1.05;
const HALF_X = 17.0;
const HALF_Z = 10.5;
const MOUTH = 3.2;
const NET_DEPTH = 2.4;
const WALL_H = 1.1;
const WALL_T = 0.6;
const RIM = 1.6; // deck around the walls
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

// mown stripes and white markings, drawn once onto a canvas
function pitchTexture() {
  const px = 40;
  const w = HALF_X * 2 * px, h = HALF_Z * 2 * px;
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const g = c.getContext('2d');
  const stripes = 12;
  for (let i = 0; i < stripes; i++) {
    g.fillStyle = i % 2 ? '#7cc957' : '#8bd463';
    g.fillRect((i * w) / stripes, 0, w / stripes + 1, h);
  }
  g.strokeStyle = 'rgba(255,255,255,0.9)';
  g.lineWidth = 0.18 * px;
  const m = 0.6 * px;
  g.strokeRect(m, m, w - 2 * m, h - 2 * m);
  g.beginPath();
  g.moveTo(w / 2, m);
  g.lineTo(w / 2, h - m);
  g.stroke();
  g.beginPath();
  g.arc(w / 2, h / 2, 3.2 * px, 0, Math.PI * 2);
  g.stroke();
  g.fillStyle = 'rgba(255,255,255,0.9)';
  g.beginPath();
  g.arc(w / 2, h / 2, 0.3 * px, 0, Math.PI * 2);
  g.fill();
  // a box in front of each goal
  const boxD = 4.5 * px, boxW = (MOUTH + 2.6) * 2 * px;
  g.strokeRect(m, h / 2 - boxW / 2, boxD, boxW);
  g.strokeRect(w - m - boxD, h / 2 - boxW / 2, boxD, boxW);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  return tex;
}

function goal(side, color, ramp) {
  const g = new THREE.Group();
  const mat = new THREE.MeshToonMaterial({ color: '#ffffff', gradientMap: ramp });
  const post = new THREE.CylinderGeometry(0.17, 0.17, 2.6, 10);
  for (const z of [-MOUTH, MOUTH]) {
    const m = new THREE.Mesh(post, mat);
    m.position.set(0, 1.3, z);
    m.castShadow = true;
    g.add(m);
  }
  const bar = new THREE.Mesh(new THREE.CylinderGeometry(0.17, 0.17, MOUTH * 2, 10).rotateX(Math.PI / 2), mat);
  bar.position.y = 2.6;
  bar.castShadow = true;
  const net = new THREE.Mesh(
    new THREE.BoxGeometry(NET_DEPTH, 2.6, MOUTH * 2, 5, 6, 12),
    new THREE.MeshBasicMaterial({ color: '#ffffff', wireframe: true, transparent: true, opacity: 0.5 }),
  );
  net.position.set(side * NET_DEPTH / 2, 1.3, 0);
  // the floor of the goal in the colour of the team defending it
  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(NET_DEPTH, MOUTH * 2).rotateX(-Math.PI / 2),
    new THREE.MeshToonMaterial({ color, gradientMap: ramp }),
  );
  floor.position.set(side * NET_DEPTH / 2, 0.02, 0);
  floor.receiveShadow = true;
  g.add(bar, net, floor);
  g.position.x = side * HALF_X;
  return g;
}

// wall pieces along the edges, leaving the goal mouths open
function walls(ramp) {
  const g = new THREE.Group();
  const board = new THREE.MeshToonMaterial({ color: '#fffaf0', gradientMap: ramp });
  const rail = new THREE.MeshToonMaterial({ color: '#2d2440', gradientMap: ramp });
  const add = (x, z, sx, sz, color) => {
    const mat = color ? new THREE.MeshToonMaterial({ color, gradientMap: ramp }) : board;
    const m = new THREE.Mesh(new THREE.BoxGeometry(sx, WALL_H, sz), mat);
    m.position.set(x, WALL_H / 2, z);
    m.castShadow = true;
    m.receiveShadow = true;
    const top = new THREE.Mesh(new THREE.BoxGeometry(sx + 0.04, 0.16, sz + 0.04), rail);
    top.position.set(x, WALL_H, z);
    g.add(m, top);
  };
  const longX = HALF_X * 2 + WALL_T * 2;
  // the side walls are split at halfway into each team's colour
  for (const s of [-1, 1]) {
    const z = s * (HALF_Z + WALL_T / 2);
    add(-longX / 4, z, longX / 2, WALL_T, TEAMS[1].color);
    add(longX / 4, z, longX / 2, WALL_T, TEAMS[2].color);
  }
  const endLen = HALF_Z - MOUTH;
  for (const sx of [-1, 1]) {
    for (const sz of [-1, 1]) add(sx * (HALF_X + WALL_T / 2), sz * (MOUTH + endLen / 2), WALL_T, endLen);
    // the back of the goal is walled too, so the net isn't the only thing behind it
    add(sx * (HALF_X + NET_DEPTH + WALL_T / 2), 0, WALL_T, MOUTH * 2 + WALL_T * 2);
    for (const sz of [-1, 1]) add(sx * (HALF_X + NET_DEPTH / 2), sz * (MOUTH + WALL_T / 2), NET_DEPTH, WALL_T);
  }
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
    this.group.add(goal(1, TEAMS[2].color, ramp), goal(-1, TEAMS[1].color, ramp), walls(ramp));

    const grass = new THREE.Mesh(
      new THREE.PlaneGeometry(HALF_X * 2, HALF_Z * 2).rotateX(-Math.PI / 2),
      new THREE.MeshToonMaterial({ map: pitchTexture(), gradientMap: ramp }),
    );
    grass.receiveShadow = true;
    // a raised deck under it all, so the stadium floats on the sea like the island does
    const deckX = HALF_X + NET_DEPTH + WALL_T + RIM, deckZ = HALF_Z + WALL_T + RIM;
    const deck = new THREE.Mesh(
      new THREE.BoxGeometry(deckX * 2, 2.4, deckZ * 2),
      [
        new THREE.MeshToonMaterial({ color: '#a8754a', gradientMap: ramp }),
        new THREE.MeshToonMaterial({ color: '#a8754a', gradientMap: ramp }),
        new THREE.MeshToonMaterial({ color: '#d9c7a3', gradientMap: ramp }),
        new THREE.MeshToonMaterial({ color: '#8a5d3a', gradientMap: ramp }),
        new THREE.MeshToonMaterial({ color: '#a8754a', gradientMap: ramp }),
        new THREE.MeshToonMaterial({ color: '#a8754a', gradientMap: ramp }),
      ],
    );
    deck.position.y = -1.21;
    deck.receiveShadow = true;
    grass.position.y = 0.005;
    this.group.add(deck, grass);
    this.last = null;
    this.pop = 1;
  }

  // pitch says whether the stadium is up; bl is [x, z, y, hidden, red goals, blue goals] while the ball is in play
  update(pitch, bl, dt) {
    this.group.visible = !!pitch;
    this.ball.visible = !!bl && !bl[3];
    if (!bl || bl[3]) {
      this.last = null;
      this.pop = 0;
      return;
    }
    const [x, z, y] = bl;
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
