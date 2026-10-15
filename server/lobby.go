package main

import (
	"errors"
	"math/rand/v2"
	"regexp"
	"strings"
	"sync"
	"time"
)

const (
	maxRooms     = 100
	roomIdleTime = 60 * time.Second
	reapEvery    = 15 * time.Second
	codeLetters  = "ABCDEFGHJKLMNPQRSTUVWXYZ"
	codeLength   = 5
)

var (
	roomCodeRe      = regexp.MustCompile(`^[A-Z]{4,6}$`)
	errTooManyRooms = errors.New("too many rooms")
)

type room struct {
	game *Game
	stop chan struct{}
	idle time.Duration
}

// Lobby owns the public room (code "") and any number of private rooms.
// Joining and reaping both hold the lobby lock, so a room is never torn
// down between being looked up and gaining its first client.
type Lobby struct {
	mu    sync.Mutex
	rooms map[string]*room
	cfg   Config
	store *Store
}

func NewLobby(cfg Config, store *Store) *Lobby {
	l := &Lobby{rooms: map[string]*room{}, cfg: cfg, store: store}
	l.rooms[""] = l.start("")
	go l.reap()
	return l
}

func (l *Lobby) start(code string) *room {
	g := NewGame(code, l.cfg)
	if code == "" {
		g.store = l.store
	}
	r := &room{game: g, stop: make(chan struct{})}
	go r.game.run(r.stop)
	return r
}

func normalizeCode(s string) string {
	s = strings.ToUpper(strings.TrimSpace(s))
	if !roomCodeRe.MatchString(s) {
		return ""
	}
	return s
}

func (l *Lobby) join(code string, c *Client) (*Game, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	r, ok := l.rooms[code]
	if !ok {
		if len(l.rooms) >= maxRooms {
			return nil, errTooManyRooms
		}
		r = l.start(code)
		l.rooms[code] = r
	}
	r.game.addClient(c)
	return r.game, nil
}

func (l *Lobby) newCode() string {
	l.mu.Lock()
	defer l.mu.Unlock()
	for {
		b := make([]byte, codeLength)
		for i := range b {
			b[i] = codeLetters[rand.IntN(len(codeLetters))]
		}
		if _, taken := l.rooms[string(b)]; !taken {
			return string(b)
		}
	}
}

func (l *Lobby) reap() {
	t := time.NewTicker(reapEvery)
	defer t.Stop()
	for range t.C {
		l.reapOnce(reapEvery)
	}
}

func (l *Lobby) reapOnce(elapsed time.Duration) {
	l.mu.Lock()
	defer l.mu.Unlock()
	for code, r := range l.rooms {
		if code == "" {
			continue
		}
		if r.game.clientCount() > 0 {
			r.idle = 0
			continue
		}
		r.idle += elapsed
		if r.idle >= roomIdleTime {
			close(r.stop)
			delete(l.rooms, code)
		}
	}
}

// RoomInfo is what the menu shows about a room before joining it
type RoomInfo struct {
	Code    string   `json:"code"`
	Players []string `json:"players"`
	Playing bool     `json:"playing"` // a match is running rather than the lobby
}

func (l *Lobby) info(code string) (RoomInfo, bool) {
	l.mu.Lock()
	r, ok := l.rooms[code]
	l.mu.Unlock()
	if !ok || code == "" {
		return RoomInfo{}, false
	}
	return r.game.info(), true
}
