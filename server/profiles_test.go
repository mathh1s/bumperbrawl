package main

import (
	"encoding/json"
	"testing"
	"time"
)

const keyA, keyB = "aaaaaaaaaaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbbbbbbbbbb"

func ratedGame(t *testing.T, store *Store) (*Game, *Client, *Client) {
	t.Helper()
	g := NewGame("", Config{MinPlayers: 0, RoundTime: 60, MatchRounds: 2})
	g.store = store
	join := func(name, key string) *Client {
		c := &Client{send: make(chan []byte, 512)}
		g.addClient(c)
		g.handle(c, inMsg{T: "join", N: name, K: key})
		return c
	}
	return g, join("Ann", keyA), join("Ben", keyB)
}

func TestMatchMovesRatings(t *testing.T) {
	dir := t.TempDir()
	store, _ := OpenStore(dir)
	g, a, b := ratedGame(t, store)
	// Ann takes both rounds
	for range 2 {
		a.player.Score = 3
		g.endRound()
		if !g.matchOver() {
			g.startRound()
		}
	}
	pa, _ := store.get(a.player.Key)
	pb, _ := store.get(b.player.Key)
	if pa.Rating <= startRating || pb.Rating >= startRating {
		t.Fatalf("winner should gain and loser lose, got %.1f and %.1f", pa.Rating, pb.Rating)
	}
	if pa.Matches != 1 || pa.Wins != 1 || pb.Wins != 0 {
		t.Fatalf("match counts wrong: %+v %+v", pa, pb)
	}

	// the file is written in the background
	var again *Store
	for range 100 {
		again, _ = OpenStore(dir)
		if p, ok := again.get(a.player.Key); ok && p.Matches == 1 {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	if p, _ := again.get(a.player.Key); p.Rating != pa.Rating || p.Name != "Ann" {
		t.Fatalf("profiles should survive a restart, got %+v", p)
	}
	raw, _ := json.Marshal(again.m)
	if json.Valid(raw) && containsKey(string(raw)) {
		t.Fatal("raw keys must never be stored")
	}
}

func containsKey(s string) bool {
	for i := 0; i+len(keyA) <= len(s); i++ {
		if s[i:i+len(keyA)] == keyA || s[i:i+len(keyB)] == keyB {
			return true
		}
	}
	return false
}

func TestShortKeysAreNotRated(t *testing.T) {
	store, _ := OpenStore("")
	if id, _ := store.lookup("short", "x"); id != "" {
		t.Fatal("keys under the minimum length are ignored")
	}
}

func TestPrivateRoomsAreNotRated(t *testing.T) {
	store, _ := OpenStore("")
	g, cs := privateGame(t, 1)
	g.store = store
	g.rateMatch()
	if len(store.leaderboard()) != 0 || cs[0].player.Key != "" {
		t.Fatal("private rooms don't touch ratings")
	}
}
