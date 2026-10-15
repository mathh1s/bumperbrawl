// Mode ids match the server (match.go and the mode files next to it)

export const OUT = 128;

export const MODES = {
  0: {
    name: 'Bonk Brawl',
    rule: 'Knock blobs off the island. Every bonk scores.',
    unit: (n) => `${n} bonk${n === 1 ? '' : 's'}`,
    cell: (p) => String(p.score),
  },
  1: {
    name: 'Last Blob Standing',
    rule: 'Three lives each. Be the last blob on the island.',
    unit: (n) => `${n} li${n === 1 ? 'fe' : 'ves'} left`,
    cell: (p) => (p.flags & OUT ? '<span class="out">out</span>' : `<span class="hearts">${'♥'.repeat(p.score)}</span>`),
  },
  2: {
    name: 'King of the Hill',
    rule: 'Get closest to the centre of the glowing ring. Holding it alone scores twice as fast.',
    unit: (n) => `${n} second${n === 1 ? '' : 's'} on the hill`,
    cell: (p) => String(p.score),
  },
  3: {
    name: 'Coin Rush',
    rule: 'Grab the coins. Get knocked off and you spill half of yours.',
    unit: (n) => `${n} coin${n === 1 ? '' : 's'}`,
    cell: (p) => `<span class="coin"></span>${p.score}`,
  },
  4: {
    name: 'Blob Ball',
    rule: 'Two teams, one ball. Bonk it into the other team\'s goal.',
    unit: (n) => `${n} goal${n === 1 ? '' : 's'}`,
    cell: (p) => `<span class="team" style="background:${TEAMS[p.team]?.color ?? '#ccc'}"></span>${p.score}`,
  },
};

export const TEAMS = {
  1: { name: 'Red', color: '#ff4d4d' },
  2: { name: 'Blue', color: '#3b8cff' },
};

export function modeOf(id) {
  return MODES[id] ?? MODES[0];
}
