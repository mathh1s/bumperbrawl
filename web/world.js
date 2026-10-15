import * as THREE from 'three';

const HEX = 1.25;
const SQ3 = Math.sqrt(3);

export function makeRamp() {
  const tex = new THREE.DataTexture(new Uint8Array([110, 190, 255]), 3, 1, THREE.RedFormat);
  tex.minFilter = tex.magFilter = THREE.NearestFilter;
  tex.needsUpdate = true;
  return tex;
}

export class World {
  constructor(scene, ramp, arenaMax) {
    this.scene = scene;
    this.ramp = ramp;
    this.max = arenaMax;
    this.t = 0;
    this.addSky();
    this.addLights();
    this.addWater();
    this.addIsland();
    this.addScenery();
  }

  toon(color) {
    return new THREE.MeshToonMaterial({ color, gradientMap: this.ramp });
  }

  // ==== sky and light ====

  addSky() {
    const mat = new THREE.ShaderMaterial({
      side: THREE.BackSide,
      depthWrite: false,
      fog: false,
      uniforms: {
        top: { value: new THREE.Color('#4fa9f0') },
        bottom: { value: new THREE.Color('#ffe2c4') },
      },
      vertexShader: `
        varying vec3 vDir;
        void main() {
          vDir = normalize(position);
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }`,
      fragmentShader: `
        uniform vec3 top;
        uniform vec3 bottom;
        varying vec3 vDir;
        void main() {
          float h = smoothstep(-0.05, 0.55, vDir.y);
          gl_FragColor = vec4(mix(bottom, top, h), 1.0);
          #include <colorspace_fragment>
        }`,
    });
    this.sky = new THREE.Mesh(new THREE.SphereGeometry(300, 32, 16), mat);
    this.sky.renderOrder = -1;
    this.scene.add(this.sky);
    this.scene.fog = new THREE.Fog('#ffe2c4', 70, 190);
  }

  addLights() {
    this.scene.add(new THREE.HemisphereLight('#ffffff', '#7aa36a', 1.6));
    const sun = new THREE.DirectionalLight('#fff1dc', 2.6);
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
    const geo = new THREE.PlaneGeometry(260, 260, 90, 90);
    geo.rotateX(-Math.PI / 2);
    this.waterPos = geo.attributes.position;
    this.waterBase = Float32Array.from(this.waterPos.array);
    const mat = new THREE.MeshLambertMaterial({ color: '#4cc2d9', flatShading: true });
    this.water = new THREE.Mesh(geo, mat);
    this.water.position.y = -0.75;
    this.water.receiveShadow = true;
    this.scene.add(this.water);
  }

  updateWater() {
    const a = this.waterPos.array;
    const b = this.waterBase;
    const t = this.t;
    for (let i = 0; i < a.length; i += 3) {
      const x = b[i], z = b[i + 2];
      a[i + 1] = Math.sin(x * 0.32 + t * 1.1) * 0.22 + Math.cos(z * 0.27 + t * 1.4) * 0.18;
    }
    this.waterPos.needsUpdate = true;
  }

  // ==== island ====

  addIsland() {
    const geo = new THREE.CylinderGeometry(HEX * 0.96, HEX * 0.96, 4, 6);
    geo.translate(0, -2, 0);
    const side = this.toon('#b0794f');
    const grass = ['#8fd16a', '#7cc45a', '#9edb7a'].map((c) => this.toon(c));
    const sand = this.toon('#f3dc94');
    this.warnMat = this.toon('#f2935f');

    this.tiles = [];
    const n = Math.ceil((this.max + 2) / (HEX * SQ3)) + 1;
    for (let q = -n; q <= n; q++) {
      for (let r = -n; r <= n; r++) {
        const x = HEX * SQ3 * (q + r / 2);
        const z = HEX * 1.5 * r;
        const d = Math.hypot(x, z);
        if (d > this.max + 0.6) continue;
        const top = d > this.max - 2.2 ? sand : grass[Math.abs(q * 7 + r * 13) % 3];
        const mesh = new THREE.Mesh(geo, [side, top, side]);
        mesh.position.set(x, 0, z);
        mesh.receiveShadow = true;
        this.scene.add(mesh);
        this.tiles.push({
          mesh, x, z, d, top,
          state: 'ok',
          vy: 0,
          spinX: (Math.random() - 0.5) * 3,
          spinZ: (Math.random() - 0.5) * 3,
          phase: Math.random() * 10,
        });
      }
    }
  }

  // Tiles follow the server radius: warn near the edge, drop once mostly outside, rebuild on a new round
  updateIsland(radius, dt) {
    const t = this.t;
    for (const tl of this.tiles) {
      const m = tl.mesh;
      const want = tl.d - 0.35 > radius ? 'down'
        : tl.d + 1.4 > radius && radius < this.max - 0.01 ? 'warn'
        : 'up';

      if (want === 'down' && tl.state !== 'falling' && tl.state !== 'gone') {
        tl.state = 'falling';
        tl.vy = 1.5;
        m.material[1] = this.warnMat;
      } else if (want === 'warn' && tl.state === 'ok') {
        tl.state = 'warn';
        m.material[1] = this.warnMat;
      } else if (want !== 'down' && (tl.state === 'falling' || tl.state === 'gone')) {
        tl.state = 'rising';
        m.material[1] = tl.top;
        m.visible = true;
        m.rotation.set(0, 0, 0);
        m.position.set(tl.x, -9 - Math.random() * 4, tl.z);
      } else if (want === 'up' && tl.state === 'warn') {
        tl.state = 'ok';
        m.material[1] = tl.top;
      }

      switch (tl.state) {
        case 'ok':
          m.position.set(tl.x, 0, tl.z);
          break;
        case 'warn':
          m.position.set(
            tl.x + Math.sin(t * 47 + tl.phase) * 0.03,
            Math.sin(t * 31 + tl.phase) * 0.04 - 0.05,
            tl.z,
          );
          break;
        case 'falling':
          tl.vy -= 22 * dt;
          m.position.y += tl.vy * dt;
          m.rotation.x += tl.spinX * dt;
          m.rotation.z += tl.spinZ * dt;
          // joining mid-round should show the island as it is, not replay every collapse at once
          if (m.position.y < -14 || !this.primed) {
            tl.state = 'gone';
            m.visible = false;
          }
          break;
        case 'rising':
          m.position.y += (0 - m.position.y) * Math.min(1, dt * 5);
          if (m.position.y > -0.01) tl.state = 'ok';
          break;
      }
    }
    this.primed = true;
  }

  // ==== decoration ====

  addScenery() {
    const sand = new THREE.MeshLambertMaterial({ color: '#f1d58c', flatShading: true });
    const leaf = new THREE.MeshLambertMaterial({ color: '#4fae5b', flatShading: true });
    const trunk = new THREE.MeshLambertMaterial({ color: '#8a5a3c', flatShading: true });
    const rock = new THREE.MeshLambertMaterial({ color: '#9aa3b5', flatShading: true });

    for (let i = 0; i < 9; i++) {
      const a = (i / 9) * Math.PI * 2 + Math.random() * 0.4;
      const r = 42 + Math.random() * 35;
      const g = new THREE.Group();
      g.position.set(Math.sin(a) * r, -0.6, Math.cos(a) * r);
      const s = 2.5 + Math.random() * 3;
      const base = new THREE.Mesh(new THREE.CylinderGeometry(s, s * 1.3, 1.6, 7), sand);
      g.add(base);
      const trees = 1 + Math.floor(Math.random() * 3);
      for (let k = 0; k < trees; k++) {
        const tx = (Math.random() - 0.5) * s, tz = (Math.random() - 0.5) * s;
        const h = 1.6 + Math.random() * 1.5;
        const tr = new THREE.Mesh(new THREE.CylinderGeometry(0.15, 0.22, h, 5), trunk);
        tr.position.set(tx, 0.8 + h / 2, tz);
        const top = new THREE.Mesh(new THREE.ConeGeometry(1 + Math.random() * 0.5, 2.2, 6), leaf);
        top.position.set(tx, 0.8 + h + 0.7, tz);
        g.add(tr, top);
      }
      if (Math.random() < 0.6) {
        const rk = new THREE.Mesh(new THREE.DodecahedronGeometry(0.8 + Math.random() * 0.6, 0), rock);
        rk.position.set(s * 0.5, 1, -s * 0.3);
        g.add(rk);
      }
      this.scene.add(g);
    }

    this.clouds = new THREE.Group();
    const cloudMat = new THREE.MeshLambertMaterial({ color: '#ffffff', flatShading: true, emissive: '#ffffff', emissiveIntensity: 0.25 });
    const puff = new THREE.IcosahedronGeometry(1, 0);
    for (let i = 0; i < 14; i++) {
      const a = Math.random() * Math.PI * 2;
      const r = 35 + Math.random() * 70;
      const c = new THREE.Group();
      c.position.set(Math.sin(a) * r, 16 + Math.random() * 16, Math.cos(a) * r);
      const parts = 3 + Math.floor(Math.random() * 3);
      for (let k = 0; k < parts; k++) {
        const p = new THREE.Mesh(puff, cloudMat);
        const s = 2 + Math.random() * 2.5;
        p.scale.set(s, s * 0.7, s);
        p.position.set((k - parts / 2) * 2.4, Math.random() * 1.2, (Math.random() - 0.5) * 2);
        p.rotation.set(Math.random() * 3, Math.random() * 3, 0);
        c.add(p);
      }
      this.clouds.add(c);
    }
    this.scene.add(this.clouds);
  }

  update(dt, radius, camera) {
    this.t += dt;
    this.sky.position.copy(camera.position);
    this.clouds.rotation.y += dt * 0.01;
    this.updateWater();
    if (radius !== null) this.updateIsland(radius, dt);
  }
}
