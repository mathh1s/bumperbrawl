package main

import "sort"

const (
	crownBounty   = 2
	crownBotPull  = 4.0
	podiumEntries = 3
)

// The crown goes to the sole leader. A tie keeps it with whoever already had
// it, so the crown never flickers between players on equal points.
func (g *Game) updateCrown() {
	best, tie := 0, false
	var lead *Player
	for _, p := range g.players {
		switch {
		case p.Score > best:
			best, lead, tie = p.Score, p, false
		case p.Score == best && best > 0:
			tie = true
		}
	}
	next := 0
	holder := g.players[g.crownID]
	switch {
	case best == 0:
	case holder != nil && holder.Score == best:
		next = holder.ID
	case !tie:
		next = lead.ID
	}
	if next != g.crownID {
		g.crownID = next
		if next != 0 {
			g.events = append(g.events, map[string]any{"k": "crown", "i": next})
		}
	}
}

func (g *Game) podium() []map[string]any {
	list := make([]*Player, 0, len(g.players))
	for _, p := range g.players {
		if p.Score > 0 {
			list = append(list, p)
		}
	}
	sort.Slice(list, func(i, j int) bool {
		if list[i].Score != list[j].Score {
			return list[i].Score > list[j].Score
		}
		return list[i].ID < list[j].ID
	})
	if len(list) > podiumEntries {
		list = list[:podiumEntries]
	}
	out := make([]map[string]any, 0, len(list))
	for _, p := range list {
		out = append(out, map[string]any{"i": p.ID, "n": p.Name, "c": p.Color, "h": p.Hat, "s": p.Score})
	}
	return out
}
