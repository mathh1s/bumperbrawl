package main

import "testing"

func privateGame(t *testing.T, humans int) (*Game, []*Client) {
	t.Helper()
	g := NewGame("ROOMX", testCfg)
	var cs []*Client
	for range humans {
		c := &Client{send: make(chan []byte, 256)}
		g.addClient(c)
		g.handle(c, inMsg{T: "join", N: "p"})
		cs = append(cs, c)
	}
	return g, cs
}

func runFor(g *Game, seconds float64) {
	for range int(seconds * tickRate) {
		g.step(1.0 / tickRate)
	}
}

func TestPrivateRoomWaitsForReady(t *testing.T) {
	g, cs := privateGame(t, 2)
	if g.phase != phaseLobby {
		t.Fatalf("private rooms open in the lobby, phase %d", g.phase)
	}
	if g.hostID != cs[0].player.ID {
		t.Fatal("first player in is the host")
	}
	runFor(g, 10)
	if g.phase != phaseLobby {
		t.Fatal("the lobby must not start a match on its own")
	}

	g.handle(cs[0], inMsg{T: "ready", V: true})
	if g.counting {
		t.Fatal("one of two ready must not start the countdown")
	}
	g.handle(cs[1], inMsg{T: "ready", V: true})
	if !g.counting {
		t.Fatal("everyone ready starts the countdown")
	}
	g.handle(cs[1], inMsg{T: "ready", V: false})
	if g.counting {
		t.Fatal("backing out stops the countdown")
	}
	g.handle(cs[1], inMsg{T: "ready", V: true})
	runFor(g, lobbyCountdown+0.1)
	if g.phase != phasePlay || g.roundNo != 1 {
		t.Fatalf("countdown must start round 1, phase %d round %d", g.phase, g.roundNo)
	}
}

func TestHostControlsSettingsAndStart(t *testing.T) {
	g, cs := privateGame(t, 2)
	set := RoomSettings{Rounds: 2, Modes: []bool{false, false, false, true}, Fill: 5, Time: 90}

	g.handle(cs[1], inMsg{T: "settings", Set: &set})
	if g.cfg.MatchRounds == 2 {
		t.Fatal("only the host may change settings")
	}
	g.handle(cs[0], inMsg{T: "settings", Set: &set})
	if g.cfg.MatchRounds != 2 || g.cfg.RoundTime != 90 || len(g.modes) != 1 || g.modes[0] != modeCoins {
		t.Fatalf("settings not applied: %+v modes %v", g.cfg, g.modes)
	}
	if len(g.players) != 5 {
		t.Fatalf("bots fill to 5 players, have %d", len(g.players))
	}

	none := RoomSettings{Rounds: 99, Modes: []bool{false, false, false, false}, Fill: -3, Time: 5}
	g.handle(cs[0], inMsg{T: "settings", Set: &none})
	if g.cfg.MatchRounds != maxRounds || g.cfg.RoundTime != minRoundSecs || g.cfg.MinPlayers != 0 || len(g.modes) != 1 {
		t.Fatalf("settings must be clamped and keep a mode: %+v modes %v", g.cfg, g.modes)
	}

	g.handle(cs[1], inMsg{T: "start"})
	if g.counting {
		t.Fatal("only the host may force a start")
	}
	g.handle(cs[0], inMsg{T: "start"})
	if !g.counting {
		t.Fatal("host start begins the countdown without anyone ready")
	}
	g.handle(cs[0], inMsg{T: "start"})
	if g.counting {
		t.Fatal("pressing start again calls it off")
	}
}

func TestPrivateMatchReturnsToLobby(t *testing.T) {
	g, cs := privateGame(t, 1)
	g.handle(cs[0], inMsg{T: "settings", Set: &RoomSettings{Rounds: 1, Modes: []bool{true, false, false, false}, Fill: 0, Time: 60}})
	g.handle(cs[0], inMsg{T: "ready", V: true})
	runFor(g, lobbyCountdown+0.1)
	if g.phase != phasePlay {
		t.Fatal("match should be running")
	}
	runFor(g, 60+matchIntermission+0.2)
	if g.phase != phaseLobby {
		t.Fatalf("after the match the room goes back to the lobby, phase %d", g.phase)
	}
	if cs[0].player.Ready {
		t.Fatal("ready resets for the next match")
	}
	g.handle(cs[0], inMsg{T: "ready", V: true})
	if !g.counting {
		t.Fatal("a new match can be started from the lobby")
	}
}

func TestHostPassesOnWhenLeaving(t *testing.T) {
	g, cs := privateGame(t, 3)
	g.removeClient(cs[0])
	if g.hostID != cs[1].player.ID {
		t.Fatalf("host should pass to the next oldest player, got %d", g.hostID)
	}
}

func TestPublicRoomHasNoLobby(t *testing.T) {
	g := testGame()
	c := &Client{send: make(chan []byte, 64)}
	g.addClient(c)
	g.handle(c, inMsg{T: "join"})
	g.handle(c, inMsg{T: "start"})
	if g.phase != phasePlay || g.hostID != 0 {
		t.Fatal("the public room plays continuously and has no host")
	}
}

func TestHostCanKick(t *testing.T) {
	g, cs := privateGame(t, 3)
	target := cs[2].player.ID
	g.handle(cs[1], inMsg{T: "kick", I: target})
	if cs[2].player == nil {
		t.Fatal("only the host may kick")
	}
	g.handle(cs[0], inMsg{T: "kick", I: cs[0].player.ID})
	if cs[0].player == nil {
		t.Fatal("the host can't kick themselves")
	}
	g.handle(cs[0], inMsg{T: "kick", I: target})
	if cs[2].player != nil || g.players[target] != nil {
		t.Fatal("kicked player should be back to watching")
	}
	g.handle(cs[2], inMsg{T: "join", N: "again"})
	if cs[2].player == nil {
		t.Fatal("a kicked player can join again from the menu")
	}
}

func TestRoomInfo(t *testing.T) {
	l := newTestLobby()
	c := &Client{send: make(chan []byte, 64)}
	g, _ := l.join("INFOX", c)
	g.handle(c, inMsg{T: "join", N: "Mia"})
	info, ok := l.info("INFOX")
	if !ok || len(info.Players) != 1 || info.Players[0] != "Mia" || info.Playing {
		t.Fatalf("unexpected room info %+v %v", info, ok)
	}
	if _, ok := l.info("NOPEX"); ok {
		t.Fatal("unknown codes are not rooms")
	}
	if _, ok := l.info(""); ok {
		t.Fatal("the public room is not looked up by code")
	}
}

func TestEmotesAreRateLimited(t *testing.T) {
	g := testGame()
	c := &Client{send: make(chan []byte, 64)}
	g.addClient(c)
	g.handle(c, inMsg{T: "join"})
	g.events = nil
	g.handle(c, inMsg{T: "emote", I: 2})
	g.handle(c, inMsg{T: "emote", I: 3})
	g.handle(c, inMsg{T: "emote", I: 99})
	if len(g.events) != 1 || g.events[0]["e"] != 2 {
		t.Fatalf("one emote per cooldown and only known ids, got %v", g.events)
	}
	runFor(g, emoteCooldown+0.1)
	g.events = nil
	g.handle(c, inMsg{T: "emote", I: 3})
	if len(g.events) != 1 {
		t.Fatal("emotes work again after the cooldown")
	}
}

func TestLeavingGoesBackToWatching(t *testing.T) {
	g, cs := privateGame(t, 2)
	id := cs[0].player.ID
	g.handle(cs[0], inMsg{T: "leave"})
	if cs[0].player != nil || g.players[id] != nil {
		t.Fatal("leaving removes your blob")
	}
	if g.hostID != cs[1].player.ID {
		t.Fatal("the host passes on when the host leaves")
	}
}
