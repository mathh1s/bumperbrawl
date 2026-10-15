package main

import (
	"math"
	"math/rand/v2"
)

// King of the Hill: a race up a switchback mountain, like Slime Climb in Fall Guys.
// Spinning arms sweep the ramps and have to be jumped, falling off the side puts you
// back at the last landing you reached, and slime rises from the bottom and takes
// anyone it catches. The first blob to the summit wins the round on the spot; if
// nobody makes it, whoever climbed highest does.
//
// The course replaces the island for the round. Blobs keep their usual Y as height
// above the ground under them and GroundY carries the course height, so jumps and
// falls work as everywhere else.

const (
	modeClimb = 6

	climbRows      = 6    // ramps zigzagging up the mountain
	climbRowLen    = 20.0 // length of a ramp along x
	climbRowGap    = 8.5  // distance between rows along z
	climbRise      = 3.0  // height gained per ramp
	climbRampW     = 5.5
	climbLandingW  = 7.0
	climbStartW    = 9.0
	climbStartZ    = 12.0
	climbEdgeX     = 14.0 // x of the landings that join the rows
	climbArmLen    = 3.4
	climbArmR      = 0.35 // thickness of an arm, added to the blob radius for hits
	climbArmClear  = 0.9  // jump at least this high to pass over an arm
	climbArmPush   = 13.0
	climbArmCD     = 0.6
	slimeStart     = -3.0
	slimeDelay     = 10.0 // seconds before the slime starts to rise
	slimeRate      = 0.3  // units per second
	climbFinishBon = 1000 // finishing outscores any amount of climbing
	climbBotAhead  = 4.0
)

// Seg is a stretch of course: a centreline from A to B, a width, and the ground height at each end
type Seg struct {
	AX, AZ, BX, BZ float64
	W              float64
	AY, BY         float64
	Landing        bool    // a flat checkpoint between ramps
	Start          float64 // course distance at A, for progress
}

type Arm struct {
	X, Z, Y float64
	Len     float64
	Speed   float64
	Phase   float64
}

func (s Seg) length() float64 { return math.Hypot(s.BX-s.AX, s.BZ-s.AZ) }

// buildCourse lays out the start pad, then ramps that go back and forth along x, each
// one higher and further from the camera, joined by landings at alternating ends
func buildCourse() ([]Seg, []Arm) {
	var segs []Seg
	add := func(s Seg) {
		if n := len(segs); n > 0 {
			s.Start = segs[n-1].Start + segs[n-1].length()
		}
		segs = append(segs, s)
	}
	half := climbRowLen / 2
	add(Seg{AX: -half, AZ: climbStartZ, BX: half, BZ: climbStartZ, W: climbStartW, Landing: true})
	y, dir := 0.0, 1.0
	z := climbStartZ
	var arms []Arm
	for row := 0; row < climbRows; row++ {
		// the landing at the end of this row, turning towards the next one
		edge := dir * climbEdgeX
		add(Seg{AX: dir * half, AZ: z, BX: edge, BZ: z, W: climbLandingW, AY: y, BY: y, Landing: true})
		add(Seg{AX: edge, AZ: z, BX: edge, BZ: z - climbRowGap, W: climbLandingW, AY: y, BY: y, Landing: true})
		z -= climbRowGap
		// the next ramp runs back the other way and climbs
		ramp := Seg{AX: edge, AZ: z, BX: -dir * half, BZ: z, W: climbRampW, AY: y, BY: y + climbRise}
		add(ramp)
		// one arm on the early ramps, two higher up
		count := 1 + row/3
		for k := 0; k < count; k++ {
			f := float64(k+1) / float64(count+1)
			ax := ramp.AX + (ramp.BX-ramp.AX)*f
			speed := 1.7 + 0.25*float64(row)
			if (row+k)%2 == 1 {
				speed = -speed
			}
			arms = append(arms, Arm{X: ax, Z: z, Y: y + climbRise*f, Len: climbArmLen, Speed: speed, Phase: float64(row*2+k) * 1.3})
		}
		y += climbRise
		dir = -dir
	}
	// the summit pad at the end of the last ramp
	topX := dir * half
	add(Seg{AX: topX, AZ: z, BX: topX + dir*6, BZ: z, W: climbLandingW + 1, AY: y, BY: y, Landing: true})
	return segs, arms
}

// onSeg says whether a point is over segment s, and the ground height and course progress there.
// Ramps end square at both ends; landings reach half their width past them so corners join up.
func (s Seg) onSeg(x, z float64) (bool, float64, float64) {
	dx, dz := s.BX-s.AX, s.BZ-s.AZ
	l := math.Hypot(dx, dz)
	along := ((x-s.AX)*dx + (z-s.AZ)*dz) / l
	perp := math.Abs((x-s.AX)*dz-(z-s.AZ)*dx) / l
	pad := 0.0
	if s.Landing {
		pad = s.W / 2
	}
	if along < -pad || along > l+pad || perp > s.W/2 {
		return false, 0, 0
	}
	t := math.Max(0, math.Min(1, along/l))
	return true, s.AY + (s.BY-s.AY)*t, s.Start + l*t
}

// groundAt finds the course under a point, preferring the stretch nearest the height
// the blob is at so a ramp never grabs someone on the landing beside it
func (g *Game) groundAt(x, z, near float64) (seg int, y, prog float64, ok bool) {
	best := math.Inf(1)
	for i, s := range g.course {
		on, h, pr := s.onSeg(x, z)
		// where pieces overlap at the same height, the one further along counts, for checkpoints and progress
		if d := math.Abs(h - near); on && d <= best+0.01 {
			best, seg, y, prog, ok = math.Min(d, best), i, h, pr, true
		}
	}
	return
}

func (g *Game) slimeLevel() float64 {
	elapsed := g.cfg.RoundTime - g.phaseT
	return slimeStart + math.Max(0, elapsed-slimeDelay)*slimeRate
}

func (g *Game) armAngle(a Arm) float64 { return a.Phase + a.Speed*g.now }

func (g *Game) startClimb() {
	g.climbDone = false
	for _, p := range g.players {
		p.Check, p.Score, p.Out = 0, 0, false
		g.placeOnCourse(p, 0)
	}
}

// placeOnCourse puts a blob somewhere on landing seg, spread out so the start isn't a pile-up
func (g *Game) placeOnCourse(p *Player, seg int) {
	s := g.course[seg]
	t := 0.15 + rand.Float64()*0.7
	if !s.Landing {
		t = 0.5
	}
	nx, nz := -(s.BZ - s.AZ), s.BX-s.AX
	l := math.Hypot(nx, nz)
	side := (rand.Float64() - 0.5) * s.W * 0.6
	p.X = s.AX + (s.BX-s.AX)*t + nx/l*side
	p.Z = s.AZ + (s.BZ-s.AZ)*t + nz/l*side
	p.GroundY = s.AY + (s.BY-s.AY)*t
	p.Y = 0
	// face up the course
	if seg+1 < len(g.course) {
		n := g.course[seg+1]
		p.Angle = math.Atan2(n.BX-p.X, n.BZ-p.Z)
	}
}

func (g *Game) updateClimb(dt float64) {
	if g.mode != modeClimb || g.phase != phasePlay {
		return
	}
	slime := g.slimeLevel()
	var winner *Player
	for _, p := range g.players {
		if p.Out {
			continue
		}
		if p.Falling {
			// a fall off the side respawns on the last landing, unless the slime has already covered it
			if g.course[p.Check].AY < slime {
				g.slimed(p)
			}
			continue
		}
		seg, h, prog, on := g.groundAt(p.X, p.Z, p.GroundY)
		switch {
		case on && p.Airborne:
			// keep the blob's height in the world while the ground under it changes
			p.Y -= h - p.GroundY
			p.GroundY = h
		case on:
			p.GroundY = h
		case !p.Airborne && p.PoundT == 0:
			g.knockOut(p)
			continue
		}
		if on {
			if g.course[seg].Landing && seg > p.Check {
				p.Check = seg
			}
			p.Score = max(p.Score, int(prog))
			if seg == len(g.course)-1 && winner == nil {
				winner = p
			}
		}
		if p.GroundY+p.Y < slime {
			g.knockOut(p)
			g.slimed(p)
		}
	}
	g.climbArms()
	if winner != nil {
		winner.Score += climbFinishBon
		g.events = append(g.events, map[string]any{"k": "summit", "i": winner.ID})
		g.climbDone = true
	}
}

func (g *Game) slimed(p *Player) {
	if p.Out {
		return
	}
	p.Out, p.OutAt = true, g.now
	g.events = append(g.events, map[string]any{"k": "out", "i": p.ID})
}

// climbArms sweeps blobs off the ramps when a spinning arm catches them on the ground
func (g *Game) climbArms() {
	for _, p := range g.players {
		p.ArmCD = math.Max(0, p.ArmCD-1.0/tickRate)
	}
	for _, a := range g.arms {
		ang := g.armAngle(a)
		ux, uz := math.Cos(ang), math.Sin(ang)
		for _, p := range g.players {
			if p.Falling || p.Out || p.Ghost > 0 || p.ArmCD > 0 || p.Y > climbArmClear {
				continue
			}
			rx, rz := p.X-a.X, p.Z-a.Z
			along := rx*ux + rz*uz
			if along < -a.Len || along > a.Len {
				continue
			}
			perp := -rx*uz + rz*ux
			if math.Abs(perp) > climbArmR+p.radius() {
				continue
			}
			// push the way the arm is moving at that point
			side := math.Copysign(1, a.Speed*along)
			push := (climbArmPush + math.Abs(a.Speed*along)) / p.mass()
			p.shove(-uz*side*push, ux*side*push)
			p.ArmCD = climbArmCD
			g.events = append(g.events, map[string]any{"k": "swh", "x": r2(p.X), "z": r2(p.Z)})
		}
	}
}

// climbState is the course for the client: segments, arm angles and the slime level
func (g *Game) climbState() map[string]any {
	segs := make([][7]float64, len(g.course))
	for i, s := range g.course {
		land := 0.0
		if s.Landing {
			land = 1
		}
		segs[i] = [7]float64{s.AX, s.AZ, s.BX, s.BZ, s.W, s.AY, s.BY + land*1000}
	}
	arms := make([][5]float64, len(g.arms))
	for i, a := range g.arms {
		arms[i] = [5]float64{r2(a.X), r2(a.Z), r2(a.Y), a.Len, r2(g.armAngle(a))}
	}
	return map[string]any{"s": segs, "a": arms, "sl": r2(g.slimeLevel())}
}

// botClimbInput walks a bot up the centreline a few steps ahead of where it is, and hops the arms
func (g *Game) botClimbInput(b *Player) (float64, float64) {
	seg, _, _, on := g.groundAt(b.X, b.Z, b.GroundY)
	if !on {
		seg = b.Check
	}
	s := g.course[seg]
	dx, dz := s.BX-s.AX, s.BZ-s.AZ
	l := math.Hypot(dx, dz)
	t := ((b.X-s.AX)*dx + (b.Z-s.AZ)*dz) / (l * l)
	ahead := t + climbBotAhead/l
	tx, tz := s.AX+dx*ahead, s.AZ+dz*ahead
	// drifting towards an edge, head back to the middle of the path first
	ct := math.Max(0, math.Min(1, t))
	cx, cz := s.AX+dx*ct, s.AZ+dz*ct
	if off := math.Hypot(b.X-cx, b.Z-cz); off > s.W*0.3 {
		return cx - b.X + (tx-b.X)*0.3, cz - b.Z + (tz-b.Z)*0.3
	}
	if ahead > 1 && seg+1 < len(g.course) {
		n := g.course[seg+1]
		left := (ahead - 1) * l / n.length()
		tx, tz = n.AX+(n.BX-n.AX)*math.Min(left, 1), n.AZ+(n.BZ-n.AZ)*math.Min(left, 1)
	}
	if !b.Airborne {
		for _, a := range g.arms {
			ang := g.armAngle(a)
			rx, rz := b.X-a.X, b.Z-a.Z
			if math.Hypot(rx, rz) > a.Len+1 {
				continue
			}
			perp := math.Abs(-rx*math.Sin(ang) + rz*math.Cos(ang))
			if perp < 1.6 && rand.Float64() < 0.5 {
				b.WantJump = true
			}
		}
	}
	return tx - b.X, tz - b.Z
}
