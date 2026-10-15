package main

import (
	"fmt"
	"sort"
)

// Awards are the silly titles handed out on the podium at the end of a match,
// each going to whoever did the most of something during it.

const maxAwards = 4

type Stats struct {
	Bonks    int
	Falls    int
	Goals    int
	OwnGoals int
	Coins    int
	Hill     float64
	Jumps    int
	Dashes   int
}

type award struct {
	title string
	value func(s Stats) float64
	min   float64 // below this nobody gets it
	text  func(v float64) string
}

func plural(n float64, one, many string) string {
	if int(n) == 1 {
		return fmt.Sprintf("1 %s", one)
	}
	return fmt.Sprintf("%d %s", int(n), many)
}

// in order of how much they're worth showing; earlier ones win when a player qualifies for several
var awards = []award{
	{"Bonk machine", func(s Stats) float64 { return float64(s.Bonks) }, 3, func(v float64) string { return plural(v, "bonk", "bonks") }},
	{"Golden boot", func(s Stats) float64 { return float64(s.Goals) }, 2, func(v float64) string { return plural(v, "goal", "goals") }},
	{"Own goal royalty", func(s Stats) float64 { return float64(s.OwnGoals) }, 1, func(v float64) string { return plural(v, "own goal", "own goals") }},
	{"Professional faller", func(s Stats) float64 { return float64(s.Falls) }, 4, func(v float64) string { return "fell off " + plural(v, "time", "times") }},
	{"Coin hoarder", func(s Stats) float64 { return float64(s.Coins) }, 5, func(v float64) string { return plural(v, "coin", "coins") + " grabbed" }},
	{"King of the hill", func(s Stats) float64 { return s.Hill }, 10, func(v float64) string { return plural(v, "second", "seconds") + " on the hill" }},
	{"Dash addict", func(s Stats) float64 { return float64(s.Dashes) }, 25, func(v float64) string { return plural(v, "dash", "dashes") }},
	{"Frog mode", func(s Stats) float64 { return float64(s.Jumps) }, 25, func(v float64) string { return plural(v, "jump", "jumps") }},
}

// matchAwards picks up to maxAwards titles, at most one per player, ties going to the lower id
func (g *Game) matchAwards() []map[string]any {
	list := make([]*Player, 0, len(g.players))
	for _, p := range g.players {
		list = append(list, p)
	}
	sort.Slice(list, func(i, j int) bool { return list[i].ID < list[j].ID })
	taken := map[int]bool{}
	out := []map[string]any{}
	for _, a := range awards {
		var best *Player
		bestV := a.min - 1e-9
		for _, p := range list {
			if v := a.value(p.Stats); !taken[p.ID] && v > bestV {
				best, bestV = p, v
			}
		}
		if best == nil {
			continue
		}
		taken[best.ID] = true
		out = append(out, map[string]any{"t": a.title, "d": a.text(bestV), "i": best.ID, "n": best.Name, "c": best.Color, "h": best.Hat})
		if len(out) == maxAwards {
			break
		}
	}
	return out
}
