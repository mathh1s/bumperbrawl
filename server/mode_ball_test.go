package main

import (
	"math"
	"testing"
)

func ballGame(players int) *Game {
	g := testGame()
	for range players {
		g.newPlayer("p", 0, 0, true)
	}
	g.modeOrder[0] = modeBall
	g.roundNo = 0
	g.startRound()
	return g
}

func TestBallTeamsAreBalanced(t *testing.T) {
	g := ballGame(5)
	n := [3]int{}
	for _, p := range g.players {
		n[p.Team]++
	}
	if n[0] != 0 || math.Abs(float64(n[teamRed]-n[teamBlue])) > 1 {
		t.Fatalf("teams should split evenly, got %v", n)
	}
	late := g.newPlayer("late", 0, 0, false)
	if n[late.Team] > n[teamRed+teamBlue-late.Team] {
		t.Fatal("a latecomer joins the smaller team")
	}
}

func TestBallGoalScoresForTheTeam(t *testing.T) {
	g := ballGame(4)
	var striker *Player
	for _, p := range g.players {
		if p.Team == teamRed {
			striker = p
		}
	}
	g.ball = Ball{X: goalLine - 0.1, VX: 8, LastTouch: striker.ID}
	g.updateBall(1.0 / tickRate)
	if g.teamGoals[teamRed] != 1 || !g.ball.Hidden {
		t.Fatalf("ball over the +x line scores for red, goals %v", g.teamGoals)
	}
	for _, p := range g.players {
		want := 0
		if p.Team == teamRed {
			want = 1
		}
		if p.Score != want {
			t.Fatalf("every red blob should share the goal, %d has %d", p.ID, p.Score)
		}
	}
	runFor(g, ballResetDelay+0.1)
	if g.ball.Hidden || g.ball.X != 0 {
		t.Fatal("kickoff from the centre after a goal")
	}
}

func TestBallPastTheGoalComesBack(t *testing.T) {
	g := ballGame(0)
	g.ball = Ball{X: g.radius + 0.5}
	runFor(g, 3)
	if g.ball.Hidden || g.ball.Falling || g.ball.X != 0 {
		t.Fatalf("a ball in the sea is put back in the middle, %+v", g.ball)
	}
	if g.teamGoals[teamRed] != 1 {
		t.Fatal("a ball beyond the line in the mouth is a goal")
	}
}

func TestDashKicksTheBall(t *testing.T) {
	g := ballGame(0)
	p := g.newPlayer("p", 0, 0, false)
	p.X, p.Z, p.Ghost = -3, 0, 0
	p.Angle = math.Pi / 2
	p.WantDash = true
	g.ball = Ball{}
	runFor(g, 0.5)
	if g.ball.X < 1.5 {
		t.Fatalf("a dash into the ball should send it well forward, ball at %.2f", g.ball.X)
	}
}

func TestBotsPlayBlobBall(t *testing.T) {
	g := ballGame(6)
	runFor(g, 100)
	if g.teamGoals[teamRed]+g.teamGoals[teamBlue] == 0 {
		t.Fatal("six bots should manage at least one goal in 100 seconds")
	}
	if g.radius != arenaMax || g.sweepOn {
		t.Fatal("no crumbling or log on the pitch")
	}
}

func TestFenceKeepsTheBallIn(t *testing.T) {
	g := ballGame(0)
	g.ball = Ball{Z: 12, VZ: 20}
	runFor(g, 0.5)
	if g.ball.Falling || g.ball.Hidden || g.ball.VZ >= 0 {
		t.Fatalf("the fence should bounce the ball back, %+v", g.ball)
	}
}
