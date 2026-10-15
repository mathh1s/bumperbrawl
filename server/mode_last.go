package main

const (
	modeLast = 1

	startLives  = 3
	lateLives   = 1
	flagOut     = 128
	outParkedAt = -50.0
)

func (g *Game) startLast() {
	for _, p := range g.players {
		p.Lives, p.Out = startLives, false
		p.Score = p.Lives
	}
}

// A blob joining mid-round still gets to play, just with less margin than everyone else.
func (g *Game) joinLast(p *Player) {
	p.Lives, p.Out = lateLives, false
	p.Score = p.Lives
}

func (g *Game) knockOutLast(victim *Player) {
	victim.Lives = max(0, victim.Lives-1)
	victim.Score = victim.Lives
	if victim.Lives == 0 {
		victim.Out, victim.OutAt = true, g.now
		g.events = append(g.events, map[string]any{"k": "out", "i": victim.ID})
	}
}

// The round ends as soon as at most one blob is left, but a lone player
// practising on an empty island keeps playing until the clock runs out.
func (g *Game) lastStandingDone() bool {
	if len(g.players) < 2 {
		return false
	}
	alive := 0
	for _, p := range g.players {
		if !p.Out {
			alive++
		}
	}
	return alive <= 1
}
