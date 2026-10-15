// Mode ids match the server (match.go and the mode files next to it)
export const MODES = {
  0: {
    name: 'Bonk Brawl',
    rule: 'Knock blobs off the island. Every bonk scores.',
    unit: (n) => `${n} bonk${n === 1 ? '' : 's'}`,
    cell: (p) => String(p.score),
  },
};

export function modeOf(id) {
  return MODES[id] ?? MODES[0];
}
