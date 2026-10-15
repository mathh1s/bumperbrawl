// Quick reactions shown as a bubble over a blob. Ids match server/emotes.go.

export const EMOTES = ['👋 Hi!', '😂', '😭', '😤', '❤️', 'Nice!', 'GG', 'Oops!'];

const SHOW_FOR = 2400;
const HEAD = 2.7;

export class Bubbles {
  constructor(el) {
    this.el = el;
    this.live = new Map();
  }

  show(id, emote) {
    const text = EMOTES[emote];
    if (text === undefined) return;
    this.live.get(id)?.node.remove();
    const node = document.createElement('div');
    node.className = 'bubble';
    node.textContent = text;
    this.el.append(node);
    this.live.set(id, { node, until: performance.now() + SHOW_FOR });
  }

  // positions maps player id to {x, y, z}; v is a scratch Vector3
  update(camera, positions, v) {
    const now = performance.now();
    for (const [id, b] of this.live) {
      const p = positions.get(id);
      if (!p || now > b.until) {
        b.node.remove();
        this.live.delete(id);
        continue;
      }
      v.set(p.x, Math.max(p.y, 0) + HEAD, p.z).project(camera);
      const hidden = v.z > 1;
      b.node.style.visibility = hidden ? 'hidden' : 'visible';
      b.node.style.transform = `translate(${(v.x * 0.5 + 0.5) * innerWidth}px, ${(-v.y * 0.5 + 0.5) * innerHeight}px) translate(-50%, -100%)`;
      b.node.classList.toggle('fade', b.until - now < 300);
    }
  }
}
