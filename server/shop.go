package main

import (
	"errors"
	"slices"
)

// Crowns are earned by finishing matches and spent on extra hats. The first
// freeHats hats are everyone's; the rest are unlocked per profile, and the
// server checks ownership when you join so a hat can't just be asked for.

const (
	freeHats = 9

	crownsForMatch  = 10
	crownsPerRound  = 5
	crownsForWin    = 15
	crownsPerAward  = 5
	crownsMinHumans = 2 // private rooms only pay out with company, so bot rooms can't be farmed
)

// hatPrices are indexed from freeHats; web/blobs.js lists the same hats in the same order
var hatPrices = []int{60, 80, 100, 120, 150, 180, 220, 300}

func hatPrice(hat int) (int, bool) {
	i := hat - freeHats
	if i < 0 || i >= len(hatPrices) {
		return 0, false
	}
	return hatPrices[i], true
}

var (
	errNoProfile  = errors.New("no profile")
	errNotForSale = errors.New("not for sale")
	errOwned      = errors.New("already unlocked")
	errTooPoor    = errors.New("not enough crowns")
)

func (s *Store) owns(id string, hat int) bool {
	if hat < freeHats {
		return true
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	p, ok := s.m[id]
	return ok && slices.Contains(p.Owned, hat)
}

func (s *Store) buy(key string, hat int) (Profile, error) {
	price, ok := hatPrice(hat)
	if !ok {
		return Profile{}, errNotForSale
	}
	s.mu.Lock()
	p, found := s.m[hashKey(key)]
	if !found {
		s.mu.Unlock()
		return Profile{}, errNoProfile
	}
	switch {
	case slices.Contains(p.Owned, hat):
		s.mu.Unlock()
		return *p, errOwned
	case p.Crowns < price:
		s.mu.Unlock()
		return *p, errTooPoor
	}
	p.Crowns -= price
	p.Owned = append(p.Owned, hat)
	out := *p
	s.mu.Unlock()
	go s.save()
	return out, nil
}

func (s *Store) addCrowns(id string, n int) int {
	s.mu.Lock()
	p, ok := s.m[id]
	if !ok {
		s.mu.Unlock()
		return 0
	}
	p.Crowns += n
	total := p.Crowns
	s.mu.Unlock()
	return total
}

// payCrowns hands out crowns at the end of a match to everyone who played at least half of it
func (g *Game) payCrowns(champs []*Player, awards []map[string]any) {
	if g.store == nil {
		return
	}
	var finishers []*Player
	for _, p := range g.players {
		if !p.Bot && p.Key != "" && p.RoundsPlayed*2 >= g.cfg.MatchRounds {
			finishers = append(finishers, p)
		}
	}
	if g.private && g.humanCount() < crownsMinHumans {
		return
	}
	won := map[*Player]bool{}
	for _, c := range champs {
		won[c] = true
	}
	titles := map[int]int{}
	for _, a := range awards {
		titles[a["i"].(int)]++
	}
	for _, p := range finishers {
		n := crownsForMatch + crownsPerRound*p.Wins + crownsPerAward*titles[p.ID]
		if won[p] {
			n += crownsForWin
		}
		total := g.store.addCrowns(p.Key, n)
		for c := range g.clients {
			if c.player == p {
				g.queue(c, mustJSON(map[string]any{"t": "crowns", "got": n, "total": total}))
			}
		}
	}
	go g.store.save()
}
