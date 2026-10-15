package main

import "testing"

func TestBuyingAHat(t *testing.T) {
	store, _ := OpenStore("")
	id, _ := store.lookup(keyA, "Ann")
	if _, err := store.buy(keyA, freeHats); err != errTooPoor {
		t.Fatalf("buying without crowns should fail, got %v", err)
	}
	store.addCrowns(id, 100)
	prof, err := store.buy(keyA, freeHats)
	if err != nil || prof.Crowns != 100-hatPrices[0] || !store.owns(id, freeHats) {
		t.Fatalf("buy should take crowns and unlock the hat: %+v %v", prof, err)
	}
	if _, err := store.buy(keyA, freeHats); err != errOwned {
		t.Fatal("a hat can only be bought once")
	}
	if _, err := store.buy(keyA, 2); err != errNotForSale {
		t.Fatal("free hats aren't for sale")
	}
	if _, err := store.buy(keyB, freeHats); err != errNoProfile {
		t.Fatal("unknown keys can't buy")
	}
}

func TestLockedHatFallsBackOnJoin(t *testing.T) {
	store, _ := OpenStore("")
	g := testGame()
	g.store = store
	c := &Client{send: make(chan []byte, 64)}
	g.addClient(c)
	g.handle(c, inMsg{T: "join", N: "Ann", K: keyA, H: freeHats + 1})
	if c.player.Hat != 0 {
		t.Fatal("a hat you don't own isn't worn")
	}
	store.addCrowns(c.player.Key, 500)
	store.buy(keyA, freeHats+1)
	c2 := &Client{send: make(chan []byte, 64)}
	g.addClient(c2)
	g.handle(c2, inMsg{T: "join", N: "Ann", K: keyA, H: freeHats + 1})
	if c2.player.Hat != freeHats+1 {
		t.Fatal("an unlocked hat is worn")
	}
}

func TestMatchesPayCrowns(t *testing.T) {
	store, _ := OpenStore("")
	g, a, b := ratedGame(t, store)
	for r := 1; r <= g.cfg.MatchRounds; r++ {
		a.player.Score = 3
		g.endRound()
		if r < g.cfg.MatchRounds {
			g.startRound()
		}
	}
	pa, _ := store.get(a.player.Key)
	pb, _ := store.get(b.player.Key)
	want := crownsForMatch + crownsPerRound*g.cfg.MatchRounds + crownsForWin
	if pa.Crowns != want || pb.Crowns != crownsForMatch {
		t.Fatalf("winner should get %d and the other %d, got %d and %d", want, crownsForMatch, pa.Crowns, pb.Crowns)
	}
}

func TestSoloPrivateRoomsPayNothing(t *testing.T) {
	store, _ := OpenStore("")
	g, cs := privateGame(t, 1)
	g.store = store
	cs[0].player.Key, _ = store.lookup(keyA, "Ann")
	cs[0].player.RoundsPlayed = 10
	g.payCrowns(nil, nil)
	if p, _ := store.get(cs[0].player.Key); p.Crowns != 0 {
		t.Fatal("a private room with only bots doesn't pay crowns")
	}
}
