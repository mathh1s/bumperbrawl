package main

import (
	"math"
	"math/rand/v2"
)

const (
	modeHill = 2

	hillRadius     = 2.6
	hillMoveEvery  = 14.0
	hillMinJump    = 5.0
	hillEdgeMargin = 0.6
	hillMaxHeight  = 1.2
	hillBotPull    = 3.0
	hillShareRate  = 0.5
)

type Hill struct {
	X, Z      float64
	T         float64
	Owner     int
	Contested bool
}

func (g *Game) startHill() {
	g.hill = Hill{}
	g.placeHill()
	for _, p := range g.players {
		p.HillT = 0
	}
}

// Picks a fresh spot that fits inside the current island and, when there is room, is a real move away.
func (g *Game) placeHill() {
	reach := math.Max(0, g.radius-hillRadius-hillEdgeMargin) * 0.8
	var x, z float64
	for try := 0; try < 12; try++ {
		a := rand.Float64() * math.Pi * 2
		d := math.Sqrt(rand.Float64()) * reach
		x, z = math.Cos(a)*d, math.Sin(a)*d
		if math.Hypot(x-g.hill.X, z-g.hill.Z) >= math.Min(hillMinJump, reach) {
			break
		}
	}
	g.hill.X, g.hill.Z, g.hill.T = x, z, hillMoveEvery
	g.events = append(g.events, map[string]any{"k": "hm", "x": r2(x), "z": r2(z)})
}

func (p *Player) inHill(h Hill) bool {
	return !p.Falling && p.Ghost == 0 && p.Y < hillMaxHeight && math.Hypot(p.X-h.X, p.Z-h.Z) < hillRadius
}

func (g *Game) updateHill(dt float64) {
	if g.mode != modeHill || g.phase != phasePlay {
		return
	}
	g.hill.T -= dt
	if g.hill.T <= 0 || math.Hypot(g.hill.X, g.hill.Z)+hillRadius+hillEdgeMargin > g.radius {
		g.placeHill()
	}
	// the blob nearest the centre holds the ring; company only slows its scoring
	var owner *Player
	inside, best := 0, math.Inf(1)
	for _, p := range g.players {
		if !p.inHill(g.hill) {
			continue
		}
		inside++
		if d := math.Hypot(p.X-g.hill.X, p.Z-g.hill.Z); d < best {
			best, owner = d, p
		}
	}
	g.hill.Contested = inside > 1
	g.hill.Owner = 0
	if owner == nil {
		return
	}
	g.hill.Owner = owner.ID
	rate := 1.0
	if g.hill.Contested {
		rate = hillShareRate
	}
	owner.HillT += dt * rate
	// summing many small ticks lands a hair under whole seconds, which must still count
	for owner.HillT >= 1-1e-9 {
		owner.HillT--
		owner.Score++
	}
}

// Bots without a crate to chase walk back into the ring.
func (g *Game) botHillTarget(b *Player) (float64, float64, bool) {
	if g.mode != modeHill || g.phase != phasePlay || b.inHill(g.hill) {
		return 0, 0, false
	}
	return g.hill.X, g.hill.Z, true
}

func (g *Game) hillState() []float64 {
	contested := 0.0
	if g.hill.Contested {
		contested = 1
	}
	return []float64{r2(g.hill.X), r2(g.hill.Z), hillRadius, float64(g.hill.Owner), contested}
}
