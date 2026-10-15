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
};

export function modeOf(id) {
  return MODES[id] ?? MODES[0];
}
