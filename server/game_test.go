package main

import (
	"math"
	"testing"
)

var testCfg = Config{MinPlayers: 0, RoundTime: 120, MatchRounds: 3}

func testGame() *Game { return NewGame("", testCfg) }

// brawlGame pins every round to Bonk Brawl so scores mean bonks
func brawlGame() *Game {
	g := testGame()
	for i := range g.modeOrder {
		g.modeOrder[i] = modeBrawl
	}
	g.mode = modeBrawl
	return g
}

func newTestLobby() *Lobby {
	return &Lobby{rooms: map[string]*room{}, cfg: testCfg}
}

func TestNormalizeCode(t *testing.T) {
	cases := map[string]string{"abcde": "ABCDE", " QWER ": "QWER", "AB": "", "ABCDEFG": "", "AB1DE": "", "": ""}
	for in, want := range cases {
		if got := normalizeCode(in); got != want {
			t.Errorf("normalizeCode(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestRoomsAreIsolatedAndReaped(t *testing.T) {
	l := newTestLobby()
	a, b := &Client{send: make(chan []byte, 64)}, &Client{send: make(chan []byte, 64)}
	ga, err := l.join("ROOMA", a)
	if err != nil {
		t.Fatal(err)
	}
	gb, _ := l.join("ROOMB", b)
	if ga == gb {
		t.Fatal("different codes must give different games")
	}
	if again, _ := l.join("ROOMA", &Client{send: make(chan []byte, 64)}); again != ga {
		t.Fatal("same code must give the same game")
	}

	l.reapOnce(roomIdleTime)
	if len(l.rooms) != 2 {
		t.Fatalf("rooms with clients must survive, have %d", len(l.rooms))
	}

	gb.removeClient(b)
	l.reapOnce(roomIdleTime / 2)
	if _, ok := l.rooms["ROOMB"]; !ok {
		t.Fatal("room must not be reaped before it has been idle long enough")
	}
	l.reapOnce(roomIdleTime / 2)
	if _, ok := l.rooms["ROOMB"]; ok {
		t.Fatal("idle room must be reaped")
	}
	if _, ok := l.rooms["ROOMA"]; !ok {
		t.Fatal("busy room must stay")
	}
}

func TestRoomLimit(t *testing.T) {
	l := newTestLobby()
	for i := 0; i < maxRooms; i++ {
		l.rooms[string(rune('a'+i%26))+string(rune('a'+i/26))] = &room{game: brawlGame(), stop: make(chan struct{})}
	}
	if _, err := l.join("NEWONE", &Client{send: make(chan []byte, 64)}); err != errTooManyRooms {
		t.Fatalf("expected room limit error, got %v", err)
	}
}

func TestCrownGoesToSoleLeaderAndStaysOnTie(t *testing.T) {
	g := brawlGame()
	a := g.newPlayer("a", 0, 0, false)
	b := g.newPlayer("b", 0, 0, false)

	g.updateCrown()
	if g.crownID != 0 {
		t.Fatal("no crown without points")
	}
	a.Score = 2
	g.updateCrown()
	if g.crownID != a.ID {
		t.Fatal("sole leader gets the crown")
	}
	b.Score = 2
	g.updateCrown()
	if g.crownID != a.ID {
		t.Fatal("a tie keeps the crown with its holder")
	}
	b.Score = 3
	g.updateCrown()
	if g.crownID != b.ID {
		t.Fatal("overtaking takes the crown")
	}
}

func TestCrownBounty(t *testing.T) {
	g := brawlGame()
	king := g.newPlayer("king", 0, 0, false)
	hunter := g.newPlayer("hunter", 0, 0, false)
	king.Score = 3
	g.updateCrown()

	king.LastHitBy, king.LastHitT = hunter.ID, g.now
	g.knockOut(king)
	if hunter.Score != crownBounty {
		t.Fatalf("knocking off the crown holder is worth %d, got %d", crownBounty, hunter.Score)
	}
}

func TestPodiumOrder(t *testing.T) {
	g := brawlGame()
	for i, s := range []int{1, 5, 0, 3, 5} {
		g.newPlayer(string(rune('a'+i)), 0, 0, false).Score = s
	}
	top := g.podium()
	if len(top) != 3 {
		t.Fatalf("podium has %d entries", len(top))
	}
	if top[0]["s"] != 5 || top[1]["s"] != 5 || top[2]["s"] != 3 {
		t.Fatalf("wrong order: %v", top)
	}
	if top[0]["i"].(int) > top[1]["i"].(int) {
		t.Fatal("ties are ordered by join order")
	}
}

func TestChargedDashGoesFurther(t *testing.T) {
	travel := func(charge float64) float64 {
		g := brawlGame()
		p := g.newPlayer("p", 0, 0, false)
		p.X, p.Z, p.Ghost, p.Angle = 0, 0, 0, 0
		if charge > 0 {
			p.Charging, p.ChargeT = true, charge
		}
		p.WantDash = true
		for i := 0; i < 30; i++ {
			g.step(1.0 / tickRate)
		}
		return p.Z
	}
	tap, full := travel(0), travel(chargeMax)
	if full < tap*1.5 {
		t.Fatalf("full charge travelled %.2f, tap %.2f", full, tap)
	}
}

func sweepGame(t *testing.T) (*Game, *Player) {
	t.Helper()
	g := brawlGame()
	g.phaseT = 20
	g.sweepDir = 1
	g.sweepA = -0.05
	p := g.newPlayer("p", 0, 0, false)
	p.X, p.Z, p.Ghost = 4, 0, 0
	return g, p
}

func countEvents(g *Game, kind string) int {
	n := 0
	for _, e := range g.events {
		if e["k"] == kind {
			n++
		}
	}
	return n
}

func TestLogHitsGroundedPlayer(t *testing.T) {
	g, p := sweepGame(t)
	for i := 0; i < 10; i++ {
		g.updateSweeper(1.0 / tickRate)
	}
	if countEvents(g, "swh") == 0 || p.VZ <= 0 {
		t.Fatalf("grounded player must be swept along the log's motion, vz=%.2f", p.VZ)
	}
}

func TestLogMissesJumpingPlayer(t *testing.T) {
	g, p := sweepGame(t)
	p.Y, p.Airborne = logClear+0.2, true
	for i := 0; i < 10; i++ {
		g.updateSweeper(1.0 / tickRate)
	}
	if countEvents(g, "swh") != 0 || p.VZ != 0 {
		t.Fatal("a player above the log must not be hit")
	}
}

func TestHeavyResistsLog(t *testing.T) {
	g, p := sweepGame(t)
	g.updateSweeper(4.0 / tickRate)
	light := math.Hypot(p.VX, p.VZ)

	g2, h := sweepGame(t)
	h.Pow = powHeavy
	g2.updateSweeper(4.0 / tickRate)
	if heavy := math.Hypot(h.VX, h.VZ); heavy >= light {
		t.Fatalf("heavy %.2f should be pushed less than light %.2f", heavy, light)
	}
}

// finishRound runs the clock out on the current round.
func finishRound(g *Game) {
	g.phaseT = 0
	g.step(1.0 / tickRate)
}

func lastEvent(g *Game, kind string) map[string]any {
	for i := len(g.events) - 1; i >= 0; i-- {
		if g.events[i]["k"] == kind {
			return g.events[i]
		}
	}
	return nil
}

func TestRoundWinsAndMatchChampion(t *testing.T) {
	g := brawlGame()
	a := g.newPlayer("a", 0, 0, false)
	b := g.newPlayer("b", 0, 0, false)

	a.Score, b.Score = 3, 1
	finishRound(g)
	if a.Wins != 1 || b.Wins != 0 {
		t.Fatalf("round 1 wins a=%d b=%d", a.Wins, b.Wins)
	}
	if ev := lastEvent(g, "end"); ev["w"] != "a" || ev["mo"] != false {
		t.Fatalf("round 1 end event %v", ev)
	}

	finishRound(g) // intermission over, round 2 starts with fresh scores
	if g.roundNo != 2 || a.Score != 0 {
		t.Fatalf("round 2 should start clean, round=%d score=%d", g.roundNo, a.Score)
	}
	a.Score, b.Score = 2, 2
	finishRound(g)
	if a.Wins != 2 || b.Wins != 1 {
		t.Fatalf("a tie gives both a win, a=%d b=%d", a.Wins, b.Wins)
	}

	finishRound(g)
	b.Score = 5
	finishRound(g)
	ev := lastEvent(g, "end")
	if ev["mo"] != true {
		t.Fatal("third round of a three round match ends the match")
	}
	// 2 wins each; b has more points over the match (1+2+5 vs 3+2+0)
	if ev["ch"] != "b" {
		t.Fatalf("champion should be b on match points, got %v", ev["ch"])
	}

	finishRound(g)
	if g.roundNo != 1 || a.Wins != 0 || b.Wins != 0 {
		t.Fatalf("a new match starts at round 1 with no wins, round=%d", g.roundNo)
	}
}

func TestScorelessRoundHasNoWinner(t *testing.T) {
	g := brawlGame()
	a := g.newPlayer("a", 0, 0, false)
	finishRound(g)
	if a.Wins != 0 || lastEvent(g, "end")["w"] != "" {
		t.Fatal("nobody wins a round where nobody scored")
	}
}

func TestModeOrderCoversEveryMode(t *testing.T) {
	g := NewGame("", Config{RoundTime: 120, MatchRounds: len(allModes) + 1})
	seen := map[int]bool{}
	for i, m := range g.modeOrder {
		seen[m] = true
		if i > 0 && len(allModes) > 1 && m == g.modeOrder[i-1] {
			t.Fatalf("mode %d repeats back to back in %v", m, g.modeOrder)
		}
	}
	if len(seen) != len(allModes) {
		t.Fatalf("every mode should appear, order %v", g.modeOrder)
	}
}

func lastGame(t *testing.T, n int) (*Game, []*Player) {
	t.Helper()
	g := brawlGame()
	ps := make([]*Player, n)
	for i := range ps {
		ps[i] = g.newPlayer(string(rune('a'+i)), 0, 0, false)
	}
	g.mode = modeLast
	g.startLast()
	return g, ps
}

func TestLastBlobLivesAndElimination(t *testing.T) {
	g, ps := lastGame(t, 3)
	a := ps[0]
	for i := 0; i < startLives; i++ {
		if a.Out {
			t.Fatalf("out after only %d knockouts", i)
		}
		g.knockOut(a)
	}
	if !a.Out || a.Score != 0 || countEvents(g, "out") != 1 {
		t.Fatalf("three knockouts eliminate: out=%v score=%d", a.Out, a.Score)
	}
	for i := 0; i < 200; i++ {
		g.step(1.0 / tickRate)
	}
	if a.Y != outParkedAt || !a.Falling {
		t.Fatalf("an eliminated blob stays parked out of play, y=%.1f", a.Y)
	}
	if g.phase != phasePlay {
		t.Fatal("two blobs are still in, the round goes on")
	}
}

func TestLastBlobEndsWithOneLeft(t *testing.T) {
	g, ps := lastGame(t, 2)
	for i := 0; i < startLives; i++ {
		g.knockOut(ps[1])
	}
	g.step(1.0 / tickRate)
	if g.phase != phaseEnd {
		t.Fatal("round ends once one blob is left")
	}
	if ps[0].Wins != 1 || ps[1].Wins != 0 {
		t.Fatalf("the survivor wins the round, wins=%d/%d", ps[0].Wins, ps[1].Wins)
	}
}

func TestLastBlobSoloKeepsPlaying(t *testing.T) {
	g, ps := lastGame(t, 1)
	for i := 0; i < startLives; i++ {
		g.knockOut(ps[0])
	}
	g.step(1.0 / tickRate)
	if g.phase != phasePlay {
		t.Fatal("a lone player is not ended early")
	}
}

func TestLateJoinerGetsOneLife(t *testing.T) {
	g, _ := lastGame(t, 2)
	late := g.newPlayer("late", 0, 0, false)
	if late.Lives != lateLives || late.Out {
		t.Fatalf("late joiner lives=%d out=%v", late.Lives, late.Out)
	}
}

func hillGame(t *testing.T) (*Game, *Player, *Player) {
	t.Helper()
	g := brawlGame()
	a := g.newPlayer("a", 0, 0, false)
	b := g.newPlayer("b", 0, 0, false)
	g.mode = modeHill
	g.startHill()
	g.hill.X, g.hill.Z, g.hill.T = 0, 0, hillMoveEvery
	for _, p := range []*Player{a, b} {
		p.Ghost, p.X, p.Z = 0, 10, 0
	}
	return g, a, b
}

func TestHillScoresTheSoleOccupant(t *testing.T) {
	g, a, _ := hillGame(t)
	a.X = 0.5
	for i := 0; i < tickRate*3; i++ {
		g.updateHill(1.0 / tickRate)
	}
	if a.Score != 3 || g.hill.Owner != a.ID {
		t.Fatalf("three seconds alone in the ring is 3 points, got %d", a.Score)
	}
}

func TestContestedHillScoresClosestAtHalfRate(t *testing.T) {
	g, a, b := hillGame(t)
	a.X, b.X = 0.3, -1.5
	for i := 0; i < tickRate*4; i++ {
		g.updateHill(1.0 / tickRate)
	}
	if a.Score != 2 || b.Score != 0 || !g.hill.Contested || g.hill.Owner != a.ID {
		t.Fatalf("contested ring scores the closest blob at half rate, a=%d b=%d", a.Score, b.Score)
	}
}

func TestHillMovesAndStaysOnTheIsland(t *testing.T) {
	g, _, _ := hillGame(t)
	g.hill.T = 0
	g.updateHill(1.0 / tickRate)
	if g.hill.T != hillMoveEvery || countEvents(g, "hm") == 0 {
		t.Fatal("the ring moves when its timer runs out")
	}
	g.radius = arenaMin
	for i := 0; i < 50; i++ {
		g.hill.X, g.hill.Z = 10, 0
		g.updateHill(1.0 / tickRate)
		if math.Hypot(g.hill.X, g.hill.Z)+hillRadius > g.radius {
			t.Fatalf("ring at %.1f,%.1f hangs off an island of radius %.1f", g.hill.X, g.hill.Z, g.radius)
		}
	}
}
