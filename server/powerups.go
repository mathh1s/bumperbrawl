package main

import (
	"math"
	"math/rand/v2"
)

const (
	powNone   = 0
	powHeavy  = 1
	powBounce = 2
	powPound  = 3

	heavyTime    = 6.0
	heavyMass    = 3.0
	heavyRadius  = 1.05
	heavySlow    = 0.85
	bounceTime   = 8.0
	bounceKick   = 1.8
	poundAir     = 0.45
	poundHeight  = 1.8
	poundRadius  = 4.5
	poundForce   = 18.0
	crateEvery   = 9.0
	crateMax     = 2
	crateStartY  = 16.0
	crateFall    = 5.0
	pickRange    = 1.3
	pickHeight   = 1.2
	crateMargin  = 0.4
	botCrateSeek = 9.0
)

const (
	flagHeavy  = 16
	flagBounce = 32
	flagPound  = 64
)

type Crate struct {
	ID   int
	Kind int
	X, Z float64
	Y    float64
}

func (p *Player) radius() float64 {
	if p.Pow == powHeavy {
		return heavyRadius
	}
	return playerRadius
}

func (g *Game) clearCrates() {
	g.crates = nil
	g.crateT = crateEvery
}

func (g *Game) updateCrates(dt float64) {
	// crates are for the island; the pitch keeps to the ball
	if g.phase == phasePlay && len(g.players) > 0 && g.mode != modeBall {
		g.crateT -= dt
		if g.crateT <= 0 && len(g.crates) < crateMax {
			g.crateT = crateEvery * (0.75 + rand.Float64()*0.5)
			a := rand.Float64() * math.Pi * 2
			d := math.Sqrt(rand.Float64()) * g.radius * 0.7
			g.nextCrate++
			g.crates = append(g.crates, &Crate{
				ID: g.nextCrate, Kind: 1 + rand.IntN(3),
				X: math.Sin(a) * d, Z: math.Cos(a) * d, Y: crateStartY,
			})
		}
	}

	kept := g.crates[:0]
	for _, c := range g.crates {
		c.Y = math.Max(0, c.Y-crateFall*dt)
		if math.Hypot(c.X, c.Z) > g.radius-crateMargin {
			g.events = append(g.events, map[string]any{"k": "cg", "x": r2(c.X), "z": r2(c.Z)})
			continue
		}
		if p := g.crateTaker(c); p != nil {
			g.givePower(p, c)
			continue
		}
		kept = append(kept, c)
	}
	g.crates = kept
}

func (g *Game) crateTaker(c *Crate) *Player {
	if c.Y > pickHeight {
		return nil
	}
	for _, p := range g.players {
		if !p.Falling && p.PoundT == 0 && math.Hypot(p.X-c.X, p.Z-c.Z) < pickRange {
			return p
		}
	}
	return nil
}

func (g *Game) givePower(p *Player, c *Crate) {
	switch c.Kind {
	case powHeavy:
		p.Pow, p.PowT = powHeavy, heavyTime
	case powBounce:
		p.Pow, p.PowT = powBounce, bounceTime
	case powPound:
		p.PoundT = poundAir
		p.Airborne, p.VY = false, 0
		p.Charging, p.ChargeT = false, 0
	}
	g.events = append(g.events, map[string]any{"k": "pk", "i": p.ID, "c": c.Kind})
}

func (g *Game) updatePower(p *Player, dt float64) {
	if p.PowT > 0 {
		p.PowT -= dt
		if p.PowT <= 0 {
			p.Pow, p.PowT = powNone, 0
		}
	}
	if p.PoundT > 0 {
		p.PoundT -= dt
		if p.PoundT <= 0 {
			p.PoundT, p.Y = 0, 0
			g.slam(p)
			return
		}
		p.Y = math.Sin(math.Pi*(1-p.PoundT/poundAir)) * poundHeight
	}
}

func (g *Game) slam(p *Player) {
	for _, o := range g.players {
		if o == p || o.Falling || o.Ghost > 0 || o.PoundT > 0 {
			continue
		}
		dx, dz := o.X-p.X, o.Z-p.Z
		d := math.Hypot(dx, dz)
		if d >= poundRadius {
			continue
		}
		if d < 1e-6 {
			dx, dz, d = 1, 0, 1
		}
		f := (poundForce*(1-d/poundRadius) + 4) / o.mass()
		o.shove(dx/d*f, dz/d*f)
		o.LastHitBy, o.LastHitT = p.ID, g.now
	}
	g.events = append(g.events, map[string]any{"k": "pd", "i": p.ID, "x": r2(p.X), "z": r2(p.Z)})
}

// Bots without a power walk to a crate that is landing nearby instead of brawling
func (g *Game) botCrateTarget(b *Player) (float64, float64, bool) {
	if b.Pow != powNone {
		return 0, 0, false
	}
	best := botCrateSeek
	var tx, tz float64
	found := false
	for _, c := range g.crates {
		if c.Y > 6 {
			continue
		}
		if d := math.Hypot(c.X-b.X, c.Z-b.Z); d < best {
			best, tx, tz, found = d, c.X, c.Z, true
		}
	}
	return tx, tz, found
}

func (g *Game) crateList() [][5]float64 {
	list := make([][5]float64, 0, len(g.crates))
	for _, c := range g.crates {
		list = append(list, [5]float64{float64(c.ID), float64(c.Kind), r2(c.X), r2(c.Z), r2(c.Y)})
	}
	return list
}
