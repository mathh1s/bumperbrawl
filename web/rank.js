// Rating tiers for the public room. Ratings start at 1000 (server/profiles.go).

const TIERS = [
  { min: 1350, name: 'Legend', color: '#b197fc' },
  { min: 1200, name: 'Brawler', color: '#ffd43b' },
  { min: 1075, name: 'Bonker', color: '#74c0fc' },
  { min: 950, name: 'Bouncy', color: '#8ce99a' },
  { min: -Infinity, name: 'Wobbly', color: '#e9c46a' },
];

export function tierOf(rating) {
  return TIERS.find((t) => rating >= t.min);
}

export function tierBadge(rating) {
  const t = tierOf(rating);
  return `<span class="tier" style="background:${t.color}" title="${t.name} · ${rating}">${t.name}</span>`;
}

// a random key made once per browser; it identifies your rating, so there is no password to forget
export function playerKey() {
  try {
    let k = localStorage.getItem('bb.key');
    if (!k) {
      const bytes = crypto.getRandomValues(new Uint8Array(16));
      k = [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('');
      localStorage.setItem('bb.key', k);
    }
    return k;
  } catch {
    return '';
  }
}
