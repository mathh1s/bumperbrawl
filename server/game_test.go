package main

import (
	"math"
	"testing"
)

func newTestLobby() *Lobby {
	return &Lobby{rooms: map[string]*room{}, minPlayers: 0, roundTime: 120}
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
		l.rooms[string(rune('a'+i%26))+string(rune('a'+i/26))] = &room{game: NewGame("", 0, 120), stop: make(chan struct{})}
	}
	if _, err := l.join("NEWONE", &Client{send: make(chan []byte, 64)}); err != errTooManyRooms {
		t.Fatalf("expected room limit error, got %v", err)
	}
}

func TestCrownGoesToSoleLeaderAndStaysOnTie(t *testing.T) {
	g := NewGame("", 0, 120)
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
	g := NewGame("", 0, 120)
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
	g := NewGame("", 0, 120)
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
		g := NewGame("", 0, 120)
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
	g := NewGame("", 0, 120)
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
