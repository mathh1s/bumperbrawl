package main

import (
	"math"
	"math/rand/v2"
	"strings"
)

// Hex Drop: every tile you stand on cracks and drops away a moment later, so you
// have to keep moving. Dropped tiles float back up after a while, until the last
// thirty seconds when they stay gone. Two falls and you're out; the last blob
// standing wins.
// The tile grid is the island's own (web/world.js builds it the same way).

const (
	modeTiles = 5

	hexSize      = 1.25
	tileCrumble  = 1.0  // seconds between stepping on a tile and it dropping
	tileGrace    = 2.0  // nothing cracks right at the start of the round
	tileRegrow   = 4.0  // seconds a dropped tile stays gone
	tileNoRegrow = 30.0 // in the last this many seconds, gone is gone
	tileBotRange = 6.0

	tileLives     = 2
	tileBumpScale = 0.5 // Hex Drop is about footwork, so bumps only nudge

	tileSolid    = 0
	tileCracking = 1
	tileGone     = 2
)

type Tile struct {
	X, Z  float64
	Q, R  int
	State int
	T     float64
}

type hexKey struct{ q, r int }

// buildTiles lays out the island grid in the same order as the client, so tile i is the same tile on both sides
func buildTiles() ([]Tile, map[hexKey]int) {
	var tiles []Tile
	index := map[hexKey]int{}
	n := int(math.Ceil((arenaMax+2)/(hexSize*math.Sqrt(3)))) + 1
	for q := -n; q <= n; q++ {
		for r := -n; r <= n; r++ {
			x := hexSize * math.Sqrt(3) * (float64(q) + float64(r)/2)
			z := hexSize * 1.5 * float64(r)
			if math.Hypot(x, z) > arenaMax+0.6 {
				continue
			}
			index[hexKey{q, r}] = len(tiles)
			tiles = append(tiles, Tile{X: x, Z: z, Q: q, R: r})
		}
	}
	return tiles, index
}

// tileAt finds the tile under a point by rounding to the nearest hex; -1 when there is none
func (g *Game) tileAt(x, z float64) int {
	r := z / (hexSize * 1.5)
	q := x/(hexSize*math.Sqrt(3)) - r/2
	// cube rounding: round all three coordinates, then fix the one that moved the most
	cx, cz := q, r
	cy := -cx - cz
	rx, ry, rz := math.Round(cx), math.Round(cy), math.Round(cz)
	dx, dy, dz := math.Abs(rx-cx), math.Abs(ry-cy), math.Abs(rz-cz)
	switch {
	case dx > dy && dx > dz:
		rx = -ry - rz
	case dy <= dz:
		rz = -rx - ry
	}
	i, ok := g.tileIndex[hexKey{int(rx), int(rz)}]
	if !ok {
		return -1
	}
	return i
}

func (g *Game) solidAt(x, z float64) bool {
	i := g.tileAt(x, z)
	return i >= 0 && g.tiles[i].State != tileGone
}

func (g *Game) startTiles() {
	for i := range g.tiles {
		g.tiles[i].State, g.tiles[i].T = tileSolid, 0
	}
	g.tileGraceT = tileGrace
	g.startLast()
	for _, p := range g.players {
		p.Lives, p.Score = tileLives, tileLives
	}
}

func (g *Game) updateTiles(dt float64) {
	if g.mode != modeTiles || g.phase != phasePlay {
		return
	}
	g.tileGraceT = math.Max(0, g.tileGraceT-dt)
	for i := range g.tiles {
		t := &g.tiles[i]
		switch t.State {
		case tileCracking:
			t.T -= dt
			if t.T <= 0 {
				t.State, t.T = tileGone, tileRegrow
			}
		case tileGone:
			if g.phaseT > tileNoRegrow {
				t.T -= dt
				if t.T <= 0 {
					t.State = tileSolid
				}
			}
		}
	}
	for _, p := range g.players {
		if p.Falling || p.Out || p.Airborne || p.PoundT > 0 {
			continue
		}
		i := g.tileAt(p.X, p.Z)
		if i < 0 || g.tiles[i].State == tileGone {
			g.knockOut(p)
			continue
		}
		if g.tiles[i].State == tileSolid && g.tileGraceT == 0 {
			g.tiles[i].State, g.tiles[i].T = tileCracking, tileCrumble
		}
	}
}

// tileState is one character per tile: 0 solid, 1 cracking, 2 gone
func (g *Game) tileState() string {
	var b strings.Builder
	b.Grow(len(g.tiles))
	for _, t := range g.tiles {
		b.WriteByte(byte('0' + t.State))
	}
	return b.String()
}

// clearPath checks that a straight walk from a to b only crosses solid tiles, apart from
// the one the walker is already on
func (g *Game) clearPath(ax, az, bx, bz float64) bool {
	from := g.tileAt(ax, az)
	d := math.Hypot(bx-ax, bz-az)
	steps := int(d/0.6) + 1
	for k := 1; k <= steps; k++ {
		f := float64(k) / float64(steps)
		i := g.tileAt(ax+(bx-ax)*f, az+(bz-az)*f)
		if i < 0 || (i != from && g.tiles[i].State != tileSolid) || g.tiles[i].State == tileGone {
			return false
		}
	}
	return true
}

// botTileTarget heads for a solid tile it can walk to without crossing a hole, preferring
// ones with plenty of solid ground around them
func (g *Game) botTileTarget(b *Player) (float64, float64, bool) {
	best, bx, bz := math.Inf(-1), 0.0, 0.0
	for _, t := range g.tiles {
		if t.State != tileSolid {
			continue
		}
		d := math.Hypot(t.X-b.X, t.Z-b.Z)
		if d > tileBotRange || d < 2 || !g.clearPath(b.X, b.Z, t.X, t.Z) {
			continue
		}
		around := 0
		for _, o := range [6][2]int{{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, -1}, {-1, 1}} {
			if j, ok := g.tileIndex[hexKey{t.Q + o[0], t.R + o[1]}]; ok && g.tiles[j].State == tileSolid {
				around++
			}
		}
		// turning around costs a stop on a cracking tile, so keep heading roughly the same way
		ahead := 0.0
		if v := math.Hypot(b.VX, b.VZ); v > 1 {
			ahead = ((t.X-b.X)*b.VX + (t.Z-b.Z)*b.VZ) / (d * v)
		}
		// the rim is where a bump sends you into the sea, so stay towards the middle
		rim := math.Max(0, math.Hypot(t.X, t.Z)-9)
		score := float64(around) + ahead*4 - math.Abs(d-4)*0.5 - rim*1.2 - g.crowdAt(b, t.X, t.Z)*3 + rand.Float64()
		if score > best {
			best, bx, bz = score, t.X, t.Z
		}
	}
	return bx, bz, !math.IsInf(best, -1)
}

// botTiles steers a bot around Hex Drop: keep walking between safe tiles, and when cornered
// head for the nearest solid tile and hop the gap
func (g *Game) botTiles(b *Player) {
	// stick with the current goal until it's reached or no longer safe
	tx, tz, ok := b.goalX, b.goalZ, b.hasGoal
	if ok {
		i := g.tileAt(tx, tz)
		ok = i >= 0 && g.tiles[i].State == tileSolid && math.Hypot(tx-b.X, tz-b.Z) > 1.5 && g.clearPath(b.X, b.Z, tx, tz)
	}
	if !ok {
		tx, tz, ok = g.botTileTarget(b)
	}
	b.goalX, b.goalZ, b.hasGoal = tx, tz, ok
	if !ok {
		best := math.Inf(1)
		for _, t := range g.tiles {
			if d := math.Hypot(t.X-b.X, t.Z-b.Z); t.State == tileSolid && d > 1.2 && d < best {
				best, tx, tz = d, t.X, t.Z
			}
		}
	}
	dx, dz := tx-b.X, tz-b.Z
	if l := math.Hypot(dx, dz); l > 0 {
		dx, dz = dx/l, dz/l
	}
	// sidestep anyone close, since a bump here usually means landing on a cracked tile
	for _, o := range g.players {
		if o == b || o.Falling || o.Out {
			continue
		}
		ox, oz := b.X-o.X, b.Z-o.Z
		if d := math.Hypot(ox, oz); d < 2.6 && d > 1e-6 {
			w := (2.6 - d) / 2.6 * 1.5
			dx += ox / d * w
			dz += oz / d * w
		}
	}
	if l := math.Hypot(dx, dz); l > 0 {
		b.InX, b.InZ = dx/l, dz/l
	}
	if !b.Airborne && !g.solidAt(b.X+b.InX*1.4, b.Z+b.InZ*1.4) && g.solidAt(b.X+b.InX*3, b.Z+b.InZ*3) {
		b.WantJump = true
	}
}

// crowdAt counts the other blobs near a spot
func (g *Game) crowdAt(b *Player, x, z float64) float64 {
	n := 0.0
	for _, o := range g.players {
		if o != b && !o.Falling && !o.Out && math.Hypot(o.X-x, o.Z-z) < 2.5 {
			n++
		}
	}
	return n
}
