package main

import "testing"

func TestAwardsGoToTheMostAndOncePerPlayer(t *testing.T) {
	g := testGame()
	a := g.newPlayer("Ann", 0, 0, false)
	b := g.newPlayer("Ben", 1, 0, false)
	a.Stats = Stats{Bonks: 7, Falls: 9, Jumps: 40}
	b.Stats = Stats{Bonks: 2, Falls: 5}
	got := g.matchAwards()
	if len(got) != 2 {
		t.Fatalf("want two awards, got %v", got)
	}
	if got[0]["t"] != "Bonk machine" || got[0]["i"] != a.ID || got[0]["d"] != "7 bonks" {
		t.Fatalf("Ann has the most bonks: %v", got[0])
	}
	// Ann fell most too, but she already has a title, so the faller award goes to Ben
	if got[1]["t"] != "Professional faller" || got[1]["i"] != b.ID {
		t.Fatalf("second title should go to Ben: %v", got[1])
	}
}

func TestNoAwardsBelowTheBar(t *testing.T) {
	g := testGame()
	p := g.newPlayer("Ann", 0, 0, false)
	p.Stats = Stats{Bonks: 1, Falls: 1}
	if got := g.matchAwards(); len(got) != 0 {
		t.Fatalf("a quiet match gives no titles, got %v", got)
	}
}

func TestMatchEndCarriesAwards(t *testing.T) {
	g := brawlGame()
	p := g.newPlayer("Ann", 0, 0, false)
	for r := 1; r <= g.cfg.MatchRounds; r++ {
		p.Stats.Bonks = 5
		p.Score = 1
		g.endRound()
		if r < g.cfg.MatchRounds {
			g.startRound()
		}
	}
	ev := g.events[len(g.events)-1]
	if aw, _ := ev["aw"].([]map[string]any); len(aw) == 0 {
		t.Fatalf("match end should list awards, got %v", ev["aw"])
	}
}
