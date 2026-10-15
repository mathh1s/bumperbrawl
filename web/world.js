import * as THREE from 'three';

const HEX = 1.25;
const SQ3 = Math.sqrt(3);
const WATER_Y = -0.75;

export const SKY = {
  top: '#3d8fe0',
  horizon: '#ffe1bd',
  sunDir: new THREE.Vector3(-0.35, 0.12, -1).normalize(),
};

export function makeRamp() {
  const tex = new THREE.DataTexture(new Uint8Array([110, 190, 255]), 3, 1, THREE.RedFormat);
  tex.minFilter = tex.magFilter = THREE.NearestFilter;
  tex.needsUpdate = true;
  return tex;
}

// ==== geometry helpers ====

// Merging the tile body and its decorations keeps the island at one draw call per tile.
// A part's color is either a THREE.Color or a function of (y, normalY) for gradients.
function merge(parts) {
  const pos = [], nor = [], col = [];
  const c = new THREE.Color();
  for (const { geo, matrix, color } of parts) {
    const g = (geo.index ? geo.toNonIndexed() : geo.clone()).applyMatrix4(matrix ?? new THREE.Matrix4());
    g.computeVertexNormals();
    const p = g.attributes.position.array;
    const n = g.attributes.normal.array;
    for (let i = 0; i < p.length; i += 3) {
      pos.push(p[i], p[i + 1], p[i + 2]);
      nor.push(n[i], n[i + 1], n[i + 2]);
      c.copy(typeof color === 'function' ? color(p[i + 1], n[i + 1]) : color);
      col.push(c.r, c.g, c.b);
    }
    g.dispose();
  }
  const out = new THREE.BufferGeometry();
  out.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  out.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3));
  out.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
  return out;
}

function at(x, y, z, sx = 1, sy = 1, sz = 1, rx = 0, rz = 0) {
  const m = new THREE.Matrix4();
  m.compose(new THREE.Vector3(x, y, z), new THREE.Quaternion().setFromEuler(new THREE.Euler(rx, 0, rz)), new THREE.Vector3(sx, sy, sz));
  return m;
}

function randOnTop(r = 0.75) {
  const a = Math.random() * Math.PI * 2;
  const d = Math.sqrt(Math.random()) * r;
  return [Math.sin(a) * d, Math.cos(a) * d];
}

const TUFT = new THREE.ConeGeometry(0.06, 0.32, 4);
const PETAL = new THREE.IcosahedronGeometry(0.075, 0);
const PEBBLE = new THREE.DodecahedronGeometry(0.1, 0);

function tileGeometry(grass, decor) {
  const lip = new THREE.Color(grass).multiplyScalar(0.82);
  const dirtTop = new THREE.Color('#b07a4f');
  const dirtLow = new THREE.Color('#5e3b28');
  const parts = [
    { geo: new THREE.CylinderGeometry(HEX * 0.985, HEX * 0.96, 0.2, 6), matrix: at(0, -0.1, 0), color: (y, ny) => (ny > 0.5 ? new THREE.Color(grass) : lip) },
    {
      geo: new THREE.CylinderGeometry(HEX * 0.93, HEX * 0.86, 3.8, 6, 4),
      matrix: at(0, -2.1, 0),
      color: (y) => dirtTop.clone().lerp(dirtLow, THREE.MathUtils.clamp((-y - 0.2) / 2.2, 0, 1)),
    },
  ];
  if (decor === 'grass' || decor === 'flowers') {
    const tuftColor = new THREE.Color(grass).multiplyScalar(0.72);
    for (let k = 0; k < 3; k++) {
      const [x, z] = randOnTop();
      for (let b = 0; b < 3; b++) {
        parts.push({ geo: TUFT, matrix: at(x + (b - 1) * 0.06, 0.14, z, 1, 0.7 + Math.random() * 0.6, 1, (Math.random() - 0.5) * 0.6, (b - 1) * 0.35), color: tuftColor });
      }
    }
  }
  if (decor === 'flowers') {
    const petals = ['#ffffff', '#ffe066', '#ff8fab', '#b197fc'];
    for (let k = 0; k < 4; k++) {
      const [x, z] = randOnTop();
      const s = 0.8 + Math.random() * 0.5;
      parts.push({ geo: PETAL, matrix: at(x, 0.08, z, s, s * 0.6, s), color: new THREE.Color(petals[(Math.random() * petals.length) | 0]) });
    }
  }
  if (decor === 'pebbles') {
    for (let k = 0; k < 3; k++) {
      const [x, z] = randOnTop();
      const s = 0.7 + Math.random() * 0.8;
      parts.push({ geo: PEBBLE, matrix: at(x, 0.03, z, s, s * 0.55, s), color: new THREE.Color('#c3c8d4') });
    }
  }
  return merge(parts);
}

function crackTexture(seed) {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d');
  let s = seed * 9301 + 49297;
  const rnd = () => ((s = (s * 9301 + 49297) % 233280) / 233280);
  g.strokeStyle = 'rgba(70, 40, 25, 0.95)';
  g.lineCap = 'round';
  const branch = (x, y, a, len, w) => {
    if (w < 0.8 || len < 4) return;
    g.lineWidth = w;
    g.beginPath();
    g.moveTo(x, y);
    const nx = x + Math.cos(a) * len, ny = y + Math.sin(a) * len;
    g.lineTo(nx, ny);
    g.stroke();
    branch(nx, ny, a + (rnd() - 0.5) * 1.1, len * 0.8, w * 0.75);
    if (rnd() < 0.45) branch(nx, ny, a + (rnd() > 0.5 ? 1 : -1) * (0.6 + rnd() * 0.6), len * 0.6, w * 0.6);
  };
  for (let i = 0; i < 4; i++) branch(64, 64, (i / 4) * Math.PI * 2 + rnd(), 14 + rnd() * 8, 4);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

// ==== world ====

export class World {
  constructor(scene, ramp, arenaMax, fx) {
    this.scene = scene;
    this.ramp = ramp;
    this.max = arenaMax;
    this.fx = fx;
    this.t = 0;
    this.shore = arenaMax + 1.2;
    this.addSky();
    this.addLights();
    this.addIsland();
    this.addScenery();
    this.addWater();
  }

  // ==== sky and light ====

  addSky() {
    const mat = new THREE.ShaderMaterial({
      side: THREE.BackSide,
      depthWrite: false,
      fog: false,
      uniforms: {
        top: { value: new THREE.Color(SKY.top) },
        horizon: { value: new THREE.Color(SKY.horizon) },
        sunDir: { value: SKY.sunDir },
      },
      vertexShader: `
        varying vec3 vDir;
        void main() {
          vDir = normalize(position);
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }`,
      fragmentShader: `
        uniform vec3 top;
        uniform vec3 horizon;
        uniform vec3 sunDir;
        varying vec3 vDir;
        void main() {
          vec3 d = normalize(vDir);
          float h = smoothstep(-0.02, 0.6, d.y);
          vec3 col = mix(horizon, top, pow(h, 0.7));
          float sun = max(dot(d, sunDir), 0.0);
          col += vec3(1.0, 0.85, 0.6) * (pow(sun, 8.0) * 0.35 + pow(sun, 300.0) * 1.2);
          gl_FragColor = vec4(col, 1.0);
          #include <colorspace_fragment>
        }`,
    });
    this.sky = new THREE.Mesh(new THREE.SphereGeometry(320, 32, 16), mat);
    this.sky.renderOrder = -1;
    this.scene.add(this.sky);
    this.scene.fog = new THREE.Fog(SKY.horizon, 90, 260);
  }

  addLights() {
    this.scene.add(new THREE.HemisphereLight('#d6ecff', '#8a6a4a', 1.4));
    const sun = new THREE.DirectionalLight('#fff0d6', 2.8);
    sun.position.set(14, 30, 10);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    const c = sun.shadow.camera;
    c.left = c.bottom = -22;
    c.right = c.top = 22;
    c.near = 1;
    c.far = 80;
    sun.shadow.bias = -0.0005;
    sun.shadow.radius = 3;
    this.scene.add(sun);
  }

  // ==== water ====

  addWater() {
    const geo = new THREE.PlaneGeometry(640, 640, 180, 180);
    geo.rotateX(-Math.PI / 2);
    const islets = this.islets.map((i) => new THREE.Vector4(i.x, i.z, i.r, 0));
    this.waterUniforms = {
      uTime: { value: 0 },
      uShore: { value: this.shore },
      uIslets: { value: islets },
      uShallow: { value: new THREE.Color('#47dbd0') },
      uDeep: { value: new THREE.Color('#1c78c4') },
      uFoam: { value: new THREE.Color('#ffffff') },
      uFogColor: { value: new THREE.Color(SKY.horizon) },
      uFogNear: { value: 70 },
      uFogFar: { value: 290 },
    };
    const mat = new THREE.ShaderMaterial({
      uniforms: this.waterUniforms,
      vertexShader: `
        uniform float uTime;
        varying vec3 vWorld;
        varying float vWave;
        void main() {
          vec4 w = modelMatrix * vec4(position, 1.0);
          float h = sin(w.x * 0.32 + uTime * 1.1) * 0.16
                  + cos(w.z * 0.27 + uTime * 1.4) * 0.13
                  + sin((w.x + w.z) * 0.7 + uTime * 2.2) * 0.04;
          w.y += h;
          vWave = h;
          vWorld = w.xyz;
          gl_Position = projectionMatrix * viewMatrix * w;
        }`,
      fragmentShader: `
        uniform float uTime;
        uniform float uShore;
        uniform vec4 uIslets[${islets.length}];
        uniform vec3 uShallow;
        uniform vec3 uDeep;
        uniform vec3 uFoam;
        uniform vec3 uFogColor;
        uniform float uFogNear;
        uniform float uFogFar;
        varying vec3 vWorld;
        varying float vWave;

        float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
        float noise(vec2 p) {
          vec2 i = floor(p), f = fract(p);
          vec2 u = f * f * (3.0 - 2.0 * f);
          return mix(mix(hash(i), hash(i + vec2(1, 0)), u.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), u.x), u.y);
        }

        void main() {
          float d = length(vWorld.xz) - uShore;
          for (int i = 0; i < ${islets.length}; i++) {
            d = min(d, length(vWorld.xz - uIslets[i].xy) - uIslets[i].z);
          }
          vec3 col = mix(uShallow, uDeep, smoothstep(0.0, 16.0, d));

          float n = noise(vWorld.xz * 0.9 + vec2(uTime * 0.35, -uTime * 0.25));
          float foam = smoothstep(1.1, 0.15, d + n * 0.8 - 0.25 * sin(uTime * 2.0 - d * 2.5));
          float ring = smoothstep(0.94, 1.0, sin(d * 1.6 - uTime * 2.0) * 0.5 + 0.5) * smoothstep(3.0, 0.8, d);
          col = mix(col, uFoam, clamp(foam + ring * 0.3, 0.0, 1.0));

          float s = noise(vWorld.xz * 1.4 + uTime * 0.6) * noise(vWorld.xz * 1.1 - uTime * 0.45);
          col += smoothstep(0.62, 0.72, s) * 0.22;
          col += vWave * 0.35;

          float fd = length(vWorld - cameraPosition);
          col = mix(col, uFogColor, smoothstep(uFogNear, uFogFar, fd));
          gl_FragColor = vec4(col, 1.0);
          #include <colorspace_fragment>
        }`,
    });
    this.water = new THREE.Mesh(geo, mat);
    this.water.position.y = WATER_Y;
    this.scene.add(this.water);
  }

  // ==== island ====

  addIsland() {
    const grassTints = ['#86d05e', '#79c454', '#95da6c'];
    const decor = ['none', 'none', 'grass', 'grass', 'flowers', 'pebbles'];
    const variants = (tint) => decor.map((d) => tileGeometry(tint, d));
    const grassGeos = grassTints.map(variants);
    const sandGeos = [tileGeometry('#f3dc94', 'none'), tileGeometry('#f3dc94', 'pebbles')];

    this.tileMat = new THREE.MeshToonMaterial({ vertexColors: true, gradientMap: this.ramp });
    this.dryMat = new THREE.MeshToonMaterial({ vertexColors: true, gradientMap: this.ramp, color: '#d9c48c' });
    const crackMats = [1, 2, 3].map((s) => new THREE.MeshBasicMaterial({ map: crackTexture(s), transparent: true, depthWrite: false }));
    const crackGeo = new THREE.CircleGeometry(HEX * 0.92, 6).rotateX(-Math.PI / 2);

    this.tiles = [];
    this.island = new THREE.Group();
    this.scene.add(this.island);
    const n = Math.ceil((this.max + 2) / (HEX * SQ3)) + 1;
    for (let q = -n; q <= n; q++) {
      for (let r = -n; r <= n; r++) {
        const x = HEX * SQ3 * (q + r / 2);
        const z = HEX * 1.5 * r;
        const d = Math.hypot(x, z);
        if (d > this.max + 0.6) continue;
        const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
        const geo = d > this.max - 1.6 ? pick(sandGeos) : pick(pick(grassGeos));
        const mesh = new THREE.Mesh(geo, this.tileMat);
        mesh.position.set(x, 0, z);
        mesh.receiveShadow = true;
        const crack = new THREE.Mesh(crackGeo, pick(crackMats));
        crack.position.y = 0.012;
        crack.rotation.y = Math.random() * Math.PI * 2;
        crack.visible = false;
        mesh.add(crack);
        this.island.add(mesh);
        this.tiles.push({
          mesh, crack, x, z, d,
          state: 'ok',
          vy: 0,
          splashed: false,
          spinX: (Math.random() - 0.5) * 3,
          spinZ: (Math.random() - 0.5) * 3,
          phase: Math.random() * 10,
        });
      }
    }
  }

  // a whole ring of tiles can drop in one frame; a few effects read better than a wall of them
  fxReady(kind) {
    this.fxLast ??= {};
    if (this.t - (this.fxLast[kind] ?? -1) < 0.12) return false;
    this.fxLast[kind] = this.t;
    return true;
  }

  setTileLook(tl, cracked) {
    tl.mesh.material = cracked ? this.dryMat : this.tileMat;
    tl.crack.visible = cracked;
  }

  // Tiles follow the server radius: crack near the edge, drop once mostly outside, rebuild on a new round
  // tiles is Hex Drop's per-tile state from the server (0 solid, 1 cracking, 2 gone), same order as this.tiles
  updateIsland(radius, dt, tiles) {
    const t = this.t;
    let shore = 0;
    for (const [i, tl] of this.tiles.entries()) {
      const m = tl.mesh;
      const want = tiles ? ['up', 'warn', 'down'][tiles.charCodeAt(i) - 48] ?? 'up'
        : tl.d - 0.35 > radius ? 'down'
        : tl.d + 1.0 > radius && radius < this.max - 0.01 ? 'warn'
        : 'up';

      if (want === 'down' && tl.state !== 'falling' && tl.state !== 'gone') {
        tl.state = 'falling';
        // crumbling edges pop up first; a Hex Drop tile goes straight down so it never sits under a falling blob
        tl.vy = tiles ? -4 : 1.5;
        tl.splashed = false;
        this.setTileLook(tl, true);
        if (this.primed && this.fxReady('dust')) this.fx?.dust(tl.x, 0.2, tl.z);
      } else if (want === 'warn' && tl.state === 'ok') {
        tl.state = 'warn';
        this.setTileLook(tl, true);
      } else if (want !== 'down' && (tl.state === 'falling' || tl.state === 'gone')) {
        tl.state = 'rising';
        this.setTileLook(tl, false);
        m.visible = true;
        m.rotation.set(0, 0, 0);
        m.position.set(tl.x, -5 - Math.random() * 2, tl.z);
      } else if (want === 'up' && tl.state === 'warn') {
        tl.state = 'ok';
        this.setTileLook(tl, false);
      }

      switch (tl.state) {
        case 'ok':
          m.position.set(tl.x, 0, tl.z);
          break;
        case 'warn': {
          // wobble grows as the edge closes in so the next tile to fall is readable
          const urgency = tiles ? 0.9 : THREE.MathUtils.clamp(1 - (radius - tl.d + 0.35) / 1.35, 0, 1);
          const amp = 0.015 + urgency * 0.05;
          m.position.set(tl.x + Math.sin(t * 47 + tl.phase) * amp, Math.sin(t * 31 + tl.phase) * amp - urgency * 0.08, tl.z);
          break;
        }
        case 'falling':
          tl.vy -= 22 * dt;
          m.position.y += tl.vy * dt;
          m.rotation.x += tl.spinX * dt;
          m.rotation.z += tl.spinZ * dt;
          if (!tl.splashed && m.position.y < WATER_Y - 0.3 && this.primed) {
            tl.splashed = true;
            if (this.fxReady('splash')) this.fx?.splash(tl.x, tl.z, 0.6, false);
          }
          // joining mid-round should show the island as it is, not replay every collapse at once
          if (m.position.y < -14 || !this.primed) {
            tl.state = 'gone';
            m.visible = false;
          }
          break;
        case 'rising':
          m.position.y += (0 - m.position.y) * Math.min(1, dt * 9);
          if (m.position.y > -0.01) tl.state = 'ok';
          break;
      }
      if (tl.state !== 'falling' && tl.state !== 'gone' && m.position.y > WATER_Y - 0.4) shore = Math.max(shore, tl.d + HEX * 0.9);
    }
    this.shore = this.primed ? this.shore + (shore - this.shore) * Math.min(1, dt * 3) : shore;
    this.primed = true;
  }

  // ==== decoration ====

  addScenery() {
    const flat = (color) => new THREE.MeshLambertMaterial({ color, flatShading: true });
    const sand = flat('#f1d58c');
    const leaf = flat('#4fae5b');
    const leafDark = flat('#3f9150');
    const trunk = flat('#8a5a3c');
    const rock = flat('#9aa3b5');

    this.islets = [];
    for (let i = 0; i < 9; i++) {
      const a = (i / 9) * Math.PI * 2 + Math.random() * 0.4;
      const r = 42 + Math.random() * 40;
      const g = new THREE.Group();
      g.position.set(Math.sin(a) * r, -0.6, Math.cos(a) * r);
      const s = 2.5 + Math.random() * 3;
      g.add(new THREE.Mesh(new THREE.CylinderGeometry(s, s * 1.3, 1.6, 7), sand));
      const trees = 1 + Math.floor(Math.random() * 3);
      for (let k = 0; k < trees; k++) {
        const tx = (Math.random() - 0.5) * s, tz = (Math.random() - 0.5) * s;
        const h = 1.6 + Math.random() * 1.5;
        const tr = new THREE.Mesh(new THREE.CylinderGeometry(0.15, 0.22, h, 5), trunk);
        tr.position.set(tx, 0.8 + h / 2, tz);
        const top = new THREE.Mesh(new THREE.ConeGeometry(1 + Math.random() * 0.5, 2.2, 6), Math.random() < 0.5 ? leaf : leafDark);
        top.position.set(tx, 0.8 + h + 0.7, tz);
        g.add(tr, top);
      }
      if (Math.random() < 0.6) {
        const rk = new THREE.Mesh(new THREE.DodecahedronGeometry(0.8 + Math.random() * 0.6, 0), rock);
        rk.position.set(s * 0.5, 1, -s * 0.3);
        g.add(rk);
      }
      this.scene.add(g);
      this.islets.push({ x: g.position.x, z: g.position.z, r: s * 1.15 });
    }

    // far mountains give the horizon depth; pre-tinted toward the haze instead of fogged
    const far = new THREE.MeshLambertMaterial({ color: '#a9c4d6', flatShading: true, fog: false });
    const farSnow = new THREE.MeshLambertMaterial({ color: '#e8f1f7', flatShading: true, fog: false });
    for (let i = 0; i < 26; i++) {
      const a = (i / 26) * Math.PI * 2 + Math.random() * 0.2;
      const r = 230 + Math.random() * 30;
      const h = 14 + Math.random() * 26;
      const m = new THREE.Mesh(new THREE.ConeGeometry(18 + Math.random() * 16, h, 5 + (i % 3)), far);
      m.position.set(Math.sin(a) * r, h / 2 - 2, Math.cos(a) * r);
      m.rotation.y = Math.random() * 3;
      this.scene.add(m);
      if (h > 30) {
        const cap = new THREE.Mesh(new THREE.ConeGeometry(5, h * 0.22, 5), farSnow);
        cap.position.set(m.position.x, h - 2 - h * 0.11, m.position.z);
        cap.rotation.y = m.rotation.y;
        this.scene.add(cap);
      }
    }

    this.clouds = new THREE.Group();
    const cloudMat = new THREE.MeshLambertMaterial({ color: '#ffffff', flatShading: true, emissive: '#ffffff', emissiveIntensity: 0.35 });
    const puff = new THREE.IcosahedronGeometry(1, 0);
    for (let i = 0; i < 18; i++) {
      const a = Math.random() * Math.PI * 2;
      const r = 40 + Math.random() * 110;
      const c = new THREE.Group();
      c.position.set(Math.sin(a) * r, 18 + Math.random() * 22, Math.cos(a) * r);
      const parts = 3 + Math.floor(Math.random() * 4);
      for (let k = 0; k < parts; k++) {
        const p = new THREE.Mesh(puff, cloudMat);
        const s = 2.2 + Math.random() * 2.8;
        p.scale.set(s, s * 0.65, s);
        p.position.set((k - parts / 2) * 2.4, Math.random() * 1.2, (Math.random() - 0.5) * 2);
        p.rotation.set(Math.random() * 3, Math.random() * 3, 0);
        c.add(p);
      }
      this.clouds.add(c);
    }
    this.scene.add(this.clouds);
  }

  // Blob Ball plays in its own stadium, so the island steps aside for it
  setIslandVisible(on) {
    this.island.visible = on;
  }

  update(dt, radius, camera, tiles = null) {
    this.t += dt;
    this.sky.position.copy(camera.position);
    this.clouds.rotation.y += dt * 0.01;
    this.waterUniforms.uTime.value = this.t;
    if (radius !== null && this.island.visible) this.updateIsland(radius, dt, tiles);
    this.waterUniforms.uShore.value = this.shore;
  }
}
