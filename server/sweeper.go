package main

import (
	"math"
	"math/rand/v2"
)

const (
	sweepStart   = 30.0
	sweepSpeed0  = 0.8
	sweepSpeed1  = 1.5
	logRadius    = 0.46
	logClear     = 0.9
	logOverhang  = 0.6
	sweepPush    = 15.0
	sweepImmune  = 0.6
	jumpSpeed    = 10.0
	jumpGravity  = 24.0
	footprint    = 0.6
	jumpCooldown = 0.15
	botJumpEarly = 0.16
	botJumpLate  = 0.02
)

func (g *Game) sweeperActive() bool {
	return g.phase == phasePlay && g.phaseT <= sweepStart
}

func (g *Game) resetSweeper() {
	g.sweepA = rand.Float64() * math.Pi * 2
	g.sweepDir = 1.0
	if rand.IntN(2) == 0 {
		g.sweepDir = -1
	}
	g.sweepOn = false
}

func (g *Game) sweepOmega() float64 {
	f := 1 - math.Max(0, g.phaseT)/sweepStart
	return g.sweepDir * (sweepSpeed0 + (sweepSpeed1-sweepSpeed0)*math.Max(0, math.Min(1, f)))
}

func (g *Game) sweepHalf() float64 { return g.radius + logOverhang }

// a round blob touches the ground with a narrower base than its widest point
func sweepReach(p *Player) float64 { return logRadius + p.radius()*footprint }

func (g *Game) updateSweeper(dt float64) {
	if !g.sweeperActive() {
		g.sweepOn = false
		return
	}
	if !g.sweepOn {
		g.sweepOn = true
		g.events = append(g.events, map[string]any{"k": "sws"})
	}
	omega := g.sweepOmega()
	g.sweepA = math.Mod(g.sweepA+omega*dt+2*math.Pi, 2*math.Pi)
	ux, uz := math.Cos(g.sweepA), math.Sin(g.sweepA)
	half := g.sweepHalf()

	for _, p := range g.players {
		p.SweepCD = math.Max(0, p.SweepCD-dt)
		if p.Falling || p.Ghost > 0 || p.Y > logClear || p.SweepCD > 0 {
			continue
		}
		along := p.X*ux + p.Z*uz
		perp := -p.X*uz + p.Z*ux
		reach := sweepReach(p)
		if math.Abs(along) > half+p.radius() || math.Abs(perp) >= reach {
			continue
		}
		// the log shoves along its own motion; near the hub, where it barely moves, it pushes you off whichever side you are on
		speed := along * omega
		side := math.Copysign(1, speed)
		if math.Abs(speed) < 1 {
			side = math.Copysign(1, perp)
		}
		impulse := (sweepPush + math.Abs(speed)*1.5) / p.mass()
		shift := side*reach - perp
		p.X += -uz * shift
		p.Z += ux * shift
		p.VX += -uz * side * impulse
		p.VZ += ux * side * impulse
		p.SweepCD = sweepImmune
		g.events = append(g.events, map[string]any{"k": "swh", "x": r2(p.X), "z": r2(p.Z)})
	}
}

func (g *Game) updateJump(p *Player, dt float64) {
	p.JumpCD = math.Max(0, p.JumpCD-dt)
	if p.WantJump && !p.Airborne && p.PoundT == 0 && p.JumpCD == 0 {
		p.Airborne = true
		p.VY = jumpSpeed
	}
	p.WantJump = false
	if !p.Airborne {
		return
	}
	p.VY -= jumpGravity * dt
	p.Y += p.VY * dt
	if p.Y <= 0 {
		p.Y, p.VY, p.Airborne = 0, 0, false
		p.JumpCD = jumpCooldown
	}
}

// Bots jump when the log is about to reach them; the timing window is short,
// so they clear it most of the time but not always.
func (g *Game) botJump(b *Player) {
	if !g.sweepOn || b.Airborne || b.PoundT > 0 {
		return
	}
	dist := math.Hypot(b.X, b.Z)
	if dist > g.sweepHalf() {
		return
	}
	omega := g.sweepOmega()
	gap := math.Mod(math.Atan2(b.Z, b.X)-g.sweepA, math.Pi)
	if omega < 0 {
		gap = -gap
	}
	if gap < 0 {
		gap += math.Pi
	}
	// the log is thick, so contact starts this much angle before its centre line arrives
	contact := math.Asin(math.Min(1, sweepReach(b)/math.Max(dist, 1e-6)))
	eta := (gap - contact) / math.Abs(omega)
	if eta > botJumpLate && eta < botJumpEarly && rand.Float64() < 0.3 {
		b.WantJump = true
	}
}
