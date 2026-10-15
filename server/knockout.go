package main

import (
	"math"
	"math/rand/v2"
	"sort"
)

// Knockout is a match format for private rooms, like a Fall Guys show: after
// every round only the best part of the field qualifies, everyone else watches
// the rest of the match, and once a few are left they play a Last Blob
// Standing final for the win.

const (
	formatPoints   = 0
	formatKnockout = 1

	qualifyShare = 0.6
	finalSize    = 3 // the final starts once this many contenders or fewer are left
)

func (g *Game) knockout() bool { return g.format == formatKnockout }

func (g *Game) contenders() []*Player {
	var list []*Player
	for _, p := range g.players {
		if !p.Elim {
			list = append(list, p)
		}
	}
	return list
}

// qualifyCount is how many of n contenders go through; at least one always drops out
func qualifyCount(n int) int {
	return max(1, min(n-1, int(math.Round(float64(n)*qualifyShare))))
}

// bench parks an eliminated blob under the sea for the rest of the match
func (g *Game) bench(p *Player) {
	p.Elim, p.Out = true, true
	p.Falling, p.FallT = true, respawnDelay+1
	p.X, p.Z, p.Y = 0, 0, outParkedAt
	p.VX, p.VZ, p.VY = 0, 0, 0
	p.Score, p.Lives = 0, 0
}

// startKnockoutRound picks the final once the field is small and keeps the eliminated benched
func (g *Game) startKnockoutRound() {
	n := len(g.contenders())
	g.final = n <= finalSize
	g.qualify = 0
	if g.final {
		g.mode = modeLast
		return
	}
	// a team round can't say who of the team qualifies, so knockouts swap Blob Ball for another mode
	if g.mode == modeBall {
		var solo []int
		for _, m := range g.modes {
			if m != modeBall {
				solo = append(solo, m)
			}
		}
		g.mode = modeBrawl
		if len(solo) > 0 {
			g.mode = solo[rand.IntN(len(solo))]
		}
	}
	g.qualify = qualifyCount(n)
}

// endKnockoutRound sends the best of the field through. Equal scores at the cutoff are settled
// by a coin flip so every round eliminates someone.
func (g *Game) endKnockoutRound(ev map[string]any) {
	field := g.contenders()
	rand.Shuffle(len(field), func(i, j int) { field[i], field[j] = field[j], field[i] })
	sort.SliceStable(field, func(i, j int) bool {
		a, b := field[i], field[j]
		if a.Score != b.Score {
			return a.Score > b.Score
		}
		// in Last Blob Standing whoever lasted longer ranks higher
		return a.Out && b.Out && a.OutAt > b.OutAt
	})
	if g.final || len(field) <= 1 {
		g.koDone = true
		return
	}
	keep := qualifyCount(len(field))
	qualified, out := []int{}, []int{}
	for i, p := range field {
		if i < keep {
			p.Wins++
			qualified = append(qualified, p.ID)
		} else {
			g.bench(p)
			out = append(out, p.ID)
		}
	}
	sort.Ints(qualified)
	sort.Ints(out)
	ev["q"], ev["x"] = qualified, out
}
