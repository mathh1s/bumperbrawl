package main

import "testing"

func TestQualifyCount(t *testing.T) {
	for n, want := range map[int]int{2: 1, 4: 2, 5: 3, 8: 5, 16: 10} {
		if got := qualifyCount(n); got != want {
			t.Errorf("qualifyCount(%d) = %d, want %d", n, got, want)
		}
	}
}

func TestKnockoutMatchNarrowsToAFinal(t *testing.T) {
	g, cs := privateGame(t, 1)
	g.handle(cs[0], inMsg{T: "settings", Set: &RoomSettings{Rounds: 3, Modes: []bool{true, false, true, true}, Fill: 8, Time: 60, Format: formatKnockout}})
	g.handle(cs[0], inMsg{T: "ready", V: true})
	runFor(g, lobbyCountdown+0.1)

	field := len(g.contenders())
	if field != 8 || g.final {
		t.Fatalf("knockout should open with the whole field, have %d final %v", field, g.final)
	}
	rounds := 0
	for !g.final {
		if g.phase != phasePlay {
			t.Fatalf("expected a round in play, phase %d", g.phase)
		}
		rounds++
		runFor(g, g.phaseT+0.05)
		left := len(g.contenders())
		if left != qualifyCount(field) {
			t.Fatalf("round %d: %d of %d should qualify, %d did", rounds, qualifyCount(field), field, left)
		}
		for _, p := range g.players {
			if p.Elim && (!p.Out || !p.Falling) {
				t.Fatal("eliminated blobs must stay benched")
			}
		}
		field = left
		runFor(g, intermission+0.05)
	}
	if g.mode != modeLast || len(g.contenders()) > finalSize {
		t.Fatalf("the final is Last Blob Standing for at most %d, got mode %d with %d", finalSize, g.mode, len(g.contenders()))
	}
	runFor(g, g.phaseT+0.05)
	if !g.matchOver() {
		t.Fatal("the final ends the match")
	}
	for _, c := range g.champions() {
		if c.Elim {
			t.Fatal("the champion must come from the final")
		}
	}
	runFor(g, matchIntermission+0.1)
	if g.phase != phaseLobby || len(g.contenders()) != len(g.players) {
		t.Fatal("back in the lobby everyone plays again")
	}
}

func TestLateJoinerWatchesKnockout(t *testing.T) {
	g, cs := privateGame(t, 1)
	g.handle(cs[0], inMsg{T: "settings", Set: &RoomSettings{Rounds: 3, Modes: []bool{true, false, false, false}, Fill: 4, Time: 60, Format: formatKnockout}})
	g.handle(cs[0], inMsg{T: "start"})
	runFor(g, lobbyCountdown+0.1)
	c := &Client{send: make(chan []byte, 256)}
	g.addClient(c)
	g.handle(c, inMsg{T: "join", N: "late"})
	if !c.player.Elim {
		t.Fatal("joining a running knockout means watching it")
	}
}
