package main

import "slices"

// Private rooms open in a lobby: everyone roams the island while the host picks
// the match settings, and the match starts once every player is ready or the
// host starts it. After the match the room returns to the lobby.

const (
	phaseLobby     = 2
	lobbyCountdown = 5.0

	minRounds    = 1
	maxRounds    = 10
	maxBotFill   = 8
	minRoundSecs = 60
	maxRoundSecs = 240
)

type RoomSettings struct {
	Rounds int    `json:"r"`
	Modes  []bool `json:"m"` // indexed by mode id
	Fill   int    `json:"b"` // bots top the room up to this many players
	Time   int    `json:"t"` // round length in seconds
}

func (g *Game) settings() RoomSettings {
	modes := make([]bool, len(allModes))
	for _, m := range g.modes {
		modes[m] = true
	}
	return RoomSettings{Rounds: g.cfg.MatchRounds, Modes: modes, Fill: g.cfg.MinPlayers, Time: int(g.cfg.RoundTime)}
}

func (g *Game) applySettings(s RoomSettings) {
	g.cfg.MatchRounds = min(maxRounds, max(minRounds, s.Rounds))
	g.cfg.MinPlayers = min(maxBotFill, max(0, s.Fill))
	g.cfg.RoundTime = float64(min(maxRoundSecs, max(minRoundSecs, s.Time)))
	var modes []int
	for _, m := range allModes {
		if m < len(s.Modes) && s.Modes[m] {
			modes = append(modes, m)
		}
	}
	// a match needs at least one mode, so turning the last one off is ignored
	if len(modes) > 0 {
		g.modes = modes
	}
	g.syncBots()
}

func (g *Game) enterLobby() {
	g.phase = phaseLobby
	g.phaseT = 0
	g.counting, g.forced = false, false
	g.mode = modeBrawl
	g.roundNo = 0
	g.clearCrates()
	g.resetSweeper()
	g.crownID = 0
	for _, p := range g.players {
		p.Ready = false
		p.Score, p.Lives, p.Out = 0, 0, false
		g.respawn(p)
	}
	g.events = append(g.events, map[string]any{"k": "lobby"})
}

func (g *Game) stepLobby(dt float64) {
	if !g.counting {
		return
	}
	g.phaseT -= dt
	if g.phaseT <= 0 {
		g.newMatch()
		g.startRound()
		g.broadcast(g.roomMsg())
	}
}

// updateCountdown starts the countdown once every human is ready or the host forced it,
// and stops it again if someone backs out of an unforced start
func (g *Game) updateCountdown() {
	if g.phase != phaseLobby {
		return
	}
	humans, ready := 0, 0
	for _, p := range g.players {
		if !p.Bot {
			humans++
			if p.Ready {
				ready++
			}
		}
	}
	want := humans > 0 && (g.forced || ready == humans)
	if want && !g.counting {
		g.counting, g.phaseT = true, lobbyCountdown
	} else if !want && g.counting {
		g.counting, g.phaseT = false, 0
	}
}

// the host is the longest-standing human in the room
func (g *Game) pickHost() {
	if h, ok := g.players[g.hostID]; ok && !h.Bot {
		return
	}
	g.hostID = 0
	for _, p := range g.players {
		if !p.Bot && (g.hostID == 0 || p.ID < g.hostID) {
			g.hostID = p.ID
		}
	}
}

// roomChanged recomputes the host and countdown and tells everyone
func (g *Game) roomChanged() {
	if !g.private {
		return
	}
	g.pickHost()
	g.updateCountdown()
	g.broadcast(g.roomMsg())
}

func (g *Game) roomMsg() []byte {
	ready := []int{}
	for _, p := range g.players {
		if p.Ready {
			ready = append(ready, p.ID)
		}
	}
	slices.Sort(ready)
	return mustJSON(map[string]any{
		"t": "room", "host": g.hostID, "ready": ready, "set": g.settings(),
		"counting": g.counting, "forced": g.forced,
	})
}

func (g *Game) handleRoom(p *Player, m inMsg) {
	if !g.private || g.phase != phaseLobby {
		return
	}
	switch m.T {
	case "ready":
		p.Ready = m.V
	case "settings":
		if p.ID != g.hostID || m.Set == nil {
			return
		}
		g.applySettings(*m.Set)
		g.broadcast(g.rosterMsg())
	case "start":
		if p.ID != g.hostID {
			return
		}
		// pressing it again during a forced countdown calls the start off
		g.forced = !(g.forced && g.counting)
	}
	g.roomChanged()
}
