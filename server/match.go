package main

import (
	"math/rand/v2"
	"slices"
	"sort"
	"strings"
)

const (
	modeBrawl = 0

	defaultMatchRounds = 5
	matchIntermission  = 13.0
)

// modes playable in a match; each match shuffles them and repeats as needed
var allModes = []int{modeBrawl, modeLast, modeHill, modeCoins, modeBall, modeTiles}

type Config struct {
	MinPlayers  int
	RoundTime   float64
	MatchRounds int
}

func (g *Game) newMatch() {
	g.roundNo = 0
	g.modeOrder = g.modeOrder[:0]
	for len(g.modeOrder) < g.cfg.MatchRounds {
		batch := slices.Clone(g.modes)
		rand.Shuffle(len(batch), func(i, j int) { batch[i], batch[j] = batch[j], batch[i] })
		// never play the same mode twice in a row across a batch boundary
		if n := len(g.modeOrder); n > 0 && len(batch) > 1 && batch[0] == g.modeOrder[n-1] {
			batch[0], batch[1] = batch[1], batch[0]
		}
		g.modeOrder = append(g.modeOrder, batch...)
	}
	g.modeOrder = g.modeOrder[:g.cfg.MatchRounds]
	for _, p := range g.players {
		p.Wins, p.MatchPts, p.Elim, p.RoundsPlayed = 0, 0, false, 0
		p.Stats = Stats{}
	}
	g.final, g.qualify, g.koDone = false, 0, false
}

func (g *Game) matchOver() bool {
	if g.knockout() {
		return g.koDone
	}
	return g.roundNo >= g.cfg.MatchRounds
}

// Every player tied on the best round score takes the round, as long as someone scored.
func (g *Game) awardRound() []*Player {
	best := 0
	for _, p := range g.players {
		best = max(best, p.Score)
	}
	var winners []*Player
	for _, p := range g.players {
		if p.Elim {
			continue
		}
		p.MatchPts += p.Score
		if best > 0 && p.Score == best {
			p.Wins++
			winners = append(winners, p)
		}
	}
	sort.Slice(winners, func(i, j int) bool { return winners[i].ID < winners[j].ID })
	return winners
}

func (g *Game) standingsOrder() []*Player {
	list := make([]*Player, 0, len(g.players))
	for _, p := range g.players {
		list = append(list, p)
	}
	sort.Slice(list, func(i, j int) bool {
		a, b := list[i], list[j]
		if a.Wins != b.Wins {
			return a.Wins > b.Wins
		}
		if a.MatchPts != b.MatchPts {
			return a.MatchPts > b.MatchPts
		}
		return a.ID < b.ID
	})
	return list
}

func (g *Game) standings() []map[string]any {
	out := []map[string]any{}
	for _, p := range g.standingsOrder() {
		out = append(out, map[string]any{"i": p.ID, "n": p.Name, "c": p.Color, "h": p.Hat, "w": p.Wins, "p": p.MatchPts})
	}
	return out
}

// Champions have the most round wins; total points over the match break ties.
func (g *Game) champions() []*Player {
	list := g.standingsOrder()
	if len(list) == 0 || list[0].Wins == 0 {
		return nil
	}
	top := list[0]
	var out []*Player
	for _, p := range list {
		if p.Wins == top.Wins && p.MatchPts == top.MatchPts {
			out = append(out, p)
		}
	}
	return out
}

func (g *Game) matchPodium() []map[string]any {
	out := []map[string]any{}
	for _, p := range g.standingsOrder() {
		if p.Wins == 0 || len(out) == podiumEntries {
			break
		}
		out = append(out, map[string]any{"i": p.ID, "n": p.Name, "c": p.Color, "h": p.Hat, "s": p.Wins})
	}
	return out
}

func names(ps []*Player) string {
	n := make([]string, len(ps))
	for i, p := range ps {
		n[i] = p.Name
	}
	return strings.Join(n, " & ")
}
