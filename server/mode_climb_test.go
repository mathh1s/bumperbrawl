package main

import (
	"math"
	"testing"
)

func climbGame(bots int) *Game {
	g := testGame()
	for range bots {
		g.newPlayer("b", 0, 0, true)
	}
	g.modeOrder[0] = modeClimb
	g.roundNo = 0
	g.startRound()
	return g
}

func TestCourseIsOneWalkablePath(t *testing.T) {
	g := testGame()
	prevH, prevProg := 0.0, -1.0
	for i, s := range g.course {
		for k := 0; k <= 20; k++ {
			f := float64(k) / 20
			x, z := s.AX+(s.BX-s.AX)*f, s.AZ+(s.BZ-s.AZ)*f
			_, h, prog, ok := g.groundAt(x, z, prevH)
			if !ok {
				t.Fatalf("segment %d has no ground at %.2f along", i, f)
			}
			if math.Abs(h-prevH) > 0.5 {
				t.Fatalf("segment %d jumps in height from %.2f to %.2f", i, prevH, h)
			}
			if prog < prevProg-0.01 {
				t.Fatalf("progress goes backwards on segment %d", i)
			}
			prevH, prevProg = h, prog
		}
	}
	if top := g.course[len(g.course)-1].AY; top != climbRise*climbRows {
		t.Fatalf("the summit should be %.0f high, is %.1f", climbRise*climbRows, top)
	}
}

func TestReachingTheSummitWinsTheRound(t *testing.T) {
	g := climbGame(2)
	p := g.newPlayer("p", 0, 0, false)
	top := g.course[len(g.course)-1]
	p.X, p.Z, p.GroundY = (top.AX+top.BX)/2, top.AZ, top.AY
	p.Ghost = 0
	runFor(g, 0.1)
	if g.phase != phaseEnd {
		t.Fatal("the round ends when someone reaches the summit")
	}
	for _, o := range g.players {
		if o != p && o.Score >= p.Score {
			t.Fatal("the climber who made it has the best score")
		}
	}
}

func TestFallingOffGoesBackToTheLastLanding(t *testing.T) {
	g := climbGame(0)
	p := g.newPlayer("p", 0, 0, false)
	// stand on the second landing, then step off its side
	land := g.course[2]
	p.X, p.Z, p.GroundY, p.Ghost = land.AX, (land.AZ+land.BZ)/2, land.AY, 0
	runFor(g, 0.05)
	if p.Check != 2 {
		t.Fatalf("the landing should count as a checkpoint, have %d", p.Check)
	}
	p.X += 10
	runFor(g, respawnDelay+0.2)
	if p.Falling || p.Out {
		t.Fatal("a fall early on just costs time")
	}
	if seg, _, _, ok := g.groundAt(p.X, p.Z, p.GroundY); !ok || seg != 2 {
		t.Fatalf("respawn should be on the checkpoint, got seg %d ok %v", seg, ok)
	}
}

func TestSlimeTakesStragglers(t *testing.T) {
	g := climbGame(0)
	p := g.newPlayer("p", 0, 0, false)
	q := g.newPlayer("q", 0, 0, false)
	q.Ghost = 0
	// q waits at the start; let the slime rise past the start pad
	for g.slimeLevel() <= 0.1 && g.phase == phasePlay {
		p.X, p.Z, p.GroundY = g.course[4].AX, g.course[4].AZ, g.course[4].AY
		g.step(1.0 / tickRate)
	}
	g.step(1.0 / tickRate)
	if !q.Out {
		t.Fatal("the slime takes whoever it reaches")
	}
}

func TestArmsSweepBlobsOnTheGround(t *testing.T) {
	g := climbGame(0)
	p := g.newPlayer("p", 0, 0, false)
	a := g.arms[0]
	ang := g.armAngle(a)
	p.X, p.Z, p.Ghost = a.X+math.Cos(ang)*1.5, a.Z+math.Sin(ang)*1.5, 0
	g.climbArms()
	if p.ArmCD == 0 || math.Hypot(p.VX, p.VZ) < 5 {
		t.Fatal("an arm should knock a blob standing in its way")
	}
	q := g.newPlayer("q", 0, 0, false)
	q.X, q.Z, q.Ghost, q.Y = p.X, p.Z, 0, climbArmClear+0.5
	g.climbArms()
	if q.ArmCD > 0 {
		t.Fatal("jumping clears the arm")
	}
}

func TestBotsClimb(t *testing.T) {
	g := climbGame(6)
	best := 0
	for range 45 * tickRate {
		g.step(1.0 / tickRate)
		if g.mode != modeClimb || g.phase != phasePlay {
			break
		}
		for _, p := range g.players {
			best = max(best, p.Score)
		}
	}
	if best < 60 {
		t.Fatalf("bots should make real progress in 45 seconds, best got to %d", best)
	}
}
