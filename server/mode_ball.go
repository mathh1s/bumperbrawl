package main

import (
	"math"
	"math/rand/v2"
	"sort"
)

// Blob Ball: two teams, one big ball, a goal at each end of the island.
// Red attacks the goal at +x, blue the one at -x. Every player's round score
// is their team's goal count, so the whole winning team takes the round.

const (
	modeBall = 4

	teamRed  = 1
	teamBlue = 2

	ballRadius     = 1.05
	ballMass       = 0.55
	ballDrag       = 0.75
	ballBounce     = 0.85 // restitution against blobs
	ballKick       = 1.5  // flat extra push so even a slow touch moves it
	ballMaxReach   = 1.6  // blobs higher than this jump over the ball
	goalLine       = 13.0 // the ball scores once its centre crosses this x inside the mouth
	goalHalfWidth  = 3.0
	ballResetDelay = 1.6
	ballFallGrav   = 30.0
	ballBotBehind  = 1.7
	ballWall       = 13.9 // a low fence keeps the ball on the island everywhere but the goal mouths
	ballWallBounce = 0.75
)

type Ball struct {
	X, Z, Y    float64
	VX, VZ, VY float64
	Falling    bool
	Hidden     bool // between a goal or splash and the next kickoff
	ResetT     float64
	LastTouch  int
}

func (g *Game) startBall() {
	g.teamGoals = [3]int{}
	g.kickoff()
	// spread humans over both teams first so friends aren't all stuck with the bots
	list := make([]*Player, 0, len(g.players))
	for _, p := range g.players {
		list = append(list, p)
	}
	sort.Slice(list, func(i, j int) bool {
		if list[i].Bot != list[j].Bot {
			return !list[i].Bot
		}
		return list[i].ID < list[j].ID
	})
	first := teamRed + rand.IntN(2)
	for i, p := range list {
		p.Team = first
		if i%2 == 1 {
			p.Team = teamRed + teamBlue - first
		}
		g.placeOnSide(p)
	}
}

// joinBall puts a latecomer on the smaller team
func (g *Game) joinBall(p *Player) {
	n := [3]int{}
	for _, o := range g.players {
		if o != p {
			n[o.Team]++
		}
	}
	p.Team = teamRed
	if n[teamBlue] < n[teamRed] {
		p.Team = teamBlue
	}
	p.Score = g.teamGoals[p.Team]
	g.placeOnSide(p)
}

// placeOnSide moves a blob onto its own half so kickoffs start fair
func (g *Game) placeOnSide(p *Player) {
	side := -1.0
	if p.Team == teamBlue {
		side = 1
	}
	if p.X*side < 1 {
		p.X = side * (2 + rand.Float64()*6)
	}
	p.Angle = math.Atan2(-side, 0)
}

func (g *Game) kickoff() {
	g.ball = Ball{}
}

func (g *Game) updateBall(dt float64) {
	if g.mode != modeBall || g.phase != phasePlay {
		return
	}
	b := &g.ball
	if b.Hidden {
		b.ResetT -= dt
		if b.ResetT <= 0 {
			g.kickoff()
			g.events = append(g.events, map[string]any{"k": "kick"})
		}
		return
	}
	if b.Falling {
		b.VY -= ballFallGrav * dt
		b.Y += b.VY * dt
		b.X += b.VX * dt
		b.Z += b.VZ * dt
		if b.Y < -4 {
			b.Hidden, b.ResetT = true, ballResetDelay*0.6
		}
		return
	}

	g.ballHits()
	damp := 1 - ballDrag*dt
	b.VX *= damp
	b.VZ *= damp
	b.X += b.VX * dt
	b.Z += b.VZ * dt

	if math.Abs(b.X) > goalLine && math.Abs(b.Z) < goalHalfWidth {
		team := teamRed
		if b.X < 0 {
			team = teamBlue
		}
		g.goal(team)
		return
	}
	if d := math.Hypot(b.X, b.Z); d > ballWall && math.Abs(b.Z) >= goalHalfWidth {
		nx, nz := b.X/d, b.Z/d
		b.X, b.Z = nx*ballWall, nz*ballWall
		if vn := b.VX*nx + b.VZ*nz; vn > 0 {
			b.VX -= (1 + ballWallBounce) * vn * nx
			b.VZ -= (1 + ballWallBounce) * vn * nz
			g.events = append(g.events, map[string]any{"k": "bw", "x": r2(b.X), "z": r2(b.Z), "p": r2(vn)})
		}
	}
	if math.Hypot(b.X, b.Z) > g.radius+0.2 {
		b.Falling, b.VY = true, 2
		g.events = append(g.events, map[string]any{"k": "bsp", "x": r2(b.X), "z": r2(b.Z)})
	}
}

func (g *Game) goal(team int) {
	g.teamGoals[team]++
	for _, p := range g.players {
		p.Score = g.teamGoals[p.Team]
	}
	ev := map[string]any{"k": "goal", "t": team, "x": r2(g.ball.X), "z": r2(g.ball.Z), "by": 0, "own": false}
	if p, ok := g.players[g.ball.LastTouch]; ok {
		ev["by"] = p.ID
		ev["own"] = p.Team != team
	}
	g.events = append(g.events, ev)
	g.ball.Hidden, g.ball.ResetT = true, ballResetDelay
}

// ballHits resolves blob contacts like blob collisions, with the ball much lighter
// so blobs push through it and a dash sends it flying
func (g *Game) ballHits() {
	b := &g.ball
	for _, p := range g.players {
		if p.Falling || p.Ghost > 0 || p.PoundT > 0 || p.Y > ballMaxReach {
			continue
		}
		dx, dz := b.X-p.X, b.Z-p.Z
		d := math.Hypot(dx, dz)
		overlap := p.radius() + ballRadius - d
		if overlap <= 0 {
			continue
		}
		if d < 1e-6 {
			dx, dz, d = 1, 0, 1
		}
		nx, nz := dx/d, dz/d
		im, ib := 1/p.mass(), 1/ballMass
		b.X += nx * overlap * ib / (im + ib)
		b.Z += nz * overlap * ib / (im + ib)
		p.X -= nx * overlap * im / (im + ib)
		p.Z -= nz * overlap * im / (im + ib)

		vn := (b.VX-p.VX)*nx + (b.VZ-p.VZ)*nz
		if vn >= 0 {
			continue
		}
		j := -(1+ballBounce)*vn/(im+ib) + ballKick*ballMass
		b.VX += nx * j * ib
		b.VZ += nz * j * ib
		p.VX -= nx * j * im
		p.VZ -= nz * j * im
		b.LastTouch = p.ID
	}
}

func (g *Game) ballState() []float64 {
	b := g.ball
	hidden := 0.0
	if b.Hidden {
		hidden = 1
	}
	return []float64{r2(b.X), r2(b.Z), r2(b.Y), hidden, float64(g.teamGoals[teamRed]), float64(g.teamGoals[teamBlue])}
}

// botBallInput steers a bot to the far side of the ball from the goal it attacks, then drives
// through it and sometimes dashes
func (g *Game) botBallInput(p *Player) (dx, dz float64, dash bool) {
	b := g.ball
	if b.Hidden || b.Falling {
		// wait on your own half for the kickoff
		side := -4.0
		if p.Team == teamBlue {
			side = 4
		}
		return side - p.X, -p.Z * 0.5, false
	}
	gx := goalLine + 1
	if p.Team == teamBlue {
		gx = -gx
	}
	ax, az := gx-b.X, -b.Z
	l := math.Hypot(ax, az)
	ax, az = ax/l, az/l
	// how far the bot already is behind the ball, along the attack line
	behind := (b.X-p.X)*ax + (b.Z-p.Z)*az
	if behind < 0.4 {
		// on the wrong side: loop around the ball rather than through it
		sx, sz := b.X-ax*ballBotBehind, b.Z-az*ballBotBehind
		side := -az*(p.X-b.X) + ax*(p.Z-b.Z)
		px, pz := -az, ax
		if side < 0 {
			px, pz = az, -ax
		}
		return sx + px*1.8 - p.X, sz + pz*1.8 - p.Z, false
	}
	tx, tz := b.X-ax*0.4-p.X, b.Z-az*0.4-p.Z
	d := math.Hypot(b.X-p.X, b.Z-p.Z)
	aligned := behind/math.Max(d, 1e-6) > 0.8
	return tx, tz, aligned && d < 3 && rand.Float64() < 0.35
}
