package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io/fs"
	"log"
	"math"
	"os"
	"path/filepath"
	"slices"
	"sort"
	"sync"
	"time"
)

// Profiles keep a rating per player for matches in the public room. There are no
// accounts: the browser makes up a random key once and sends it when joining, and
// only a hash of that key is stored, next to the name and the numbers.

const (
	startRating = 1000.0
	botRating   = 1000.0
	ratingK     = 32.0
	minKeyLen   = 16
	maxKeyLen   = 64
	leaderSize  = 20
)

type Profile struct {
	Name    string    `json:"name"`
	Rating  float64   `json:"rating"`
	Matches int       `json:"matches"`
	Wins    int       `json:"wins"` // matches won
	Seen    time.Time `json:"seen"`
	Crowns  int       `json:"crowns"`
	Owned   []int     `json:"owned,omitempty"` // unlocked hats
}

type Store struct {
	mu     sync.Mutex
	saveMu sync.Mutex // one writer at a time for the file
	path   string
	m      map[string]*Profile
}

func hashKey(key string) string {
	sum := sha256.Sum256([]byte(key))
	return hex.EncodeToString(sum[:])
}

// OpenStore loads dir/profiles.json, starting empty when it doesn't exist yet.
// An empty dir keeps profiles in memory only.
func OpenStore(dir string) (*Store, error) {
	s := &Store{m: map[string]*Profile{}}
	if dir == "" {
		return s, nil
	}
	s.path = filepath.Join(dir, "profiles.json")
	data, err := os.ReadFile(s.path)
	if errors.Is(err, fs.ErrNotExist) {
		return s, nil
	}
	if err != nil {
		return nil, err
	}
	if err := json.Unmarshal(data, &s.m); err != nil {
		return nil, err
	}
	return s, nil
}

// lookup returns the profile for a raw key, creating it on first use; "" if the key is unusable
func (s *Store) lookup(key, name string) (string, Profile) {
	if len(key) < minKeyLen || len(key) > maxKeyLen {
		return "", Profile{}
	}
	id := hashKey(key)
	s.mu.Lock()
	defer s.mu.Unlock()
	p, ok := s.m[id]
	if !ok {
		p = &Profile{Rating: startRating}
		s.m[id] = p
	}
	p.Name, p.Seen = name, time.Now().UTC()
	return id, *p
}

func (s *Store) get(id string) (Profile, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	p, ok := s.m[id]
	if !ok {
		return Profile{}, false
	}
	return *p, true
}

// record applies the results of one rated match and saves the file in the background
func (s *Store) record(results map[string]Profile) {
	s.mu.Lock()
	for id, r := range results {
		if p, ok := s.m[id]; ok {
			p.Rating, p.Matches, p.Wins = r.Rating, r.Matches, r.Wins
		}
	}
	s.mu.Unlock()
	// file IO stays off the game loop
	go s.save()
}

func (s *Store) save() {
	if s.path == "" {
		return
	}
	s.saveMu.Lock()
	defer s.saveMu.Unlock()
	s.mu.Lock()
	data, err := json.Marshal(s.m)
	s.mu.Unlock()
	if err != nil {
		return
	}
	// write a temp file and rename it, so a crash mid-write never leaves half a file
	tmp := s.path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o644); err != nil {
		log.Printf("saving profiles: %v", err)
		return
	}
	if err := os.Rename(tmp, s.path); err != nil {
		log.Printf("saving profiles: %v", err)
	}
}

func (s *Store) leaderboard() []map[string]any {
	s.mu.Lock()
	defer s.mu.Unlock()
	list := make([]*Profile, 0, len(s.m))
	for _, p := range s.m {
		if p.Matches > 0 {
			list = append(list, p)
		}
	}
	sort.Slice(list, func(i, j int) bool { return list[i].Rating > list[j].Rating })
	if len(list) > leaderSize {
		list = list[:leaderSize]
	}
	out := make([]map[string]any, len(list))
	for i, p := range list {
		out[i] = map[string]any{"n": p.Name, "r": int(p.Rating + 0.5), "m": p.Matches, "w": p.Wins}
	}
	return out
}

// rateMatch updates ratings after a public match. Placements come from the match standings
// and every pair of finishers is scored like a chess game, bots counting as fixed opponents.
// Only humans who played at least half the rounds take part.
func (g *Game) rateMatch() {
	if g.store == nil || g.private {
		return
	}
	order := g.standingsOrder()
	type entry struct {
		p      *Player
		rating float64
		place  int
	}
	var field []entry
	place := 0
	for i, p := range order {
		// equal wins and points share a place
		if i > 0 && (p.Wins != order[i-1].Wins || p.MatchPts != order[i-1].MatchPts) {
			place = i
		}
		if p.RoundsPlayed*2 < g.cfg.MatchRounds {
			continue
		}
		r := botRating
		if !p.Bot {
			if p.Key == "" {
				continue
			}
			prof, ok := g.store.get(p.Key)
			if !ok {
				continue
			}
			r = prof.Rating
		}
		field = append(field, entry{p, r, place})
	}
	if len(field) < 2 {
		return
	}
	champs := map[*Player]bool{}
	for _, c := range g.champions() {
		champs[c] = true
	}
	k := ratingK / float64(len(field)-1)
	results := map[string]Profile{}
	for _, a := range field {
		if a.p.Bot {
			continue
		}
		delta := 0.0
		for _, b := range field {
			if a.p == b.p {
				continue
			}
			score := 0.5
			if a.place < b.place {
				score = 1
			} else if a.place > b.place {
				score = 0
			}
			expect := 1 / (1 + math.Pow(10, (b.rating-a.rating)/400))
			delta += k * (score - expect)
		}
		prof, _ := g.store.get(a.p.Key)
		prof.Rating = a.rating + delta
		prof.Matches++
		if champs[a.p] {
			prof.Wins++
		}
		results[a.p.Key] = prof
		a.p.Rating = prof.Rating
		for c := range g.clients {
			if c.player == a.p {
				g.queue(c, mustJSON(map[string]any{"t": "rank", "old": int(a.rating + 0.5), "new": int(prof.Rating + 0.5)}))
			}
		}
	}
	g.store.record(results)
}

// rank finds where a key stands among rated players, 1 being the top
func (s *Store) rank(key string) (Profile, int, bool) {
	id := hashKey(key)
	s.mu.Lock()
	defer s.mu.Unlock()
	me, ok := s.m[id]
	if !ok || me.Matches == 0 {
		return Profile{}, 0, false
	}
	pos := 1
	for _, p := range s.m {
		if p.Matches > 0 && p.Rating > me.Rating {
			pos++
		}
	}
	return *me, pos, true
}

// summary is what the menu shows about you: rank if rated, crowns and unlocked hats
func (s *Store) summary(key string) map[string]any {
	out := map[string]any{"rated": false, "crowns": 0, "owned": []int{}}
	if len(key) < minKeyLen || len(key) > maxKeyLen {
		return out
	}
	s.mu.Lock()
	p, ok := s.m[hashKey(key)]
	if ok {
		out["crowns"] = p.Crowns
		if p.Owned != nil {
			out["owned"] = slices.Clone(p.Owned)
		}
	}
	s.mu.Unlock()
	if prof, pos, rated := s.rank(key); rated {
		out["rated"], out["r"], out["m"], out["w"], out["pos"] = true, int(prof.Rating+0.5), prof.Matches, prof.Wins, pos
	}
	return out
}
