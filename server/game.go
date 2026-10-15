package main

import (
	"encoding/json"
	"math"
	"math/rand/v2"
	"strings"
	"sync"
	"unicode"
)

const (
	tickRate     = 60
	sendEvery    = 3 // 20 snapshots per second
	playerRadius = 0.8
	accel        = 34.0
	drag         = 3.2
	dashImpulse  = 15.0
	dashCooldown = 1.1
	dashTime     = 0.28
	dashMass     = 2.6
	restitution  = 1.25
	bumpKick     = 2.5
	fallGravity  = 30.0
	respawnDelay = 1.8
	ghostTime    = 1.5
	creditWindow = 3.5
	arenaMax     = 15.0
	arenaMin     = 6.0
	roundTime    = 120.0
	shrinkDelay  = 15.0
	intermission = 8.0
	maxHumans    = 16
	paletteSize  = 8
	hatCount     = 9
)

const (
	phasePlay = 0
	phaseEnd  = 1
)

const (
	flagDash  = 1
	flagGhost = 2
	flagFall  = 4
)

var botNames = []string{"Bonk", "Wobbles", "Sir Bump", "Jellybean", "Puddin", "Mochi", "Gloop", "Tofu"}

type Player struct {
	ID    int
	Name  string
	Color int
	Hat   int
	Bot   bool

	X, Z, Y    float64
	VX, VZ, VY float64
	Angle      float64

	InX, InZ float64
	WantDash bool

	DashCD  float64
	DashT   float64
	Ghost   float64
	Falling bool
	FallT   float64

	LastHitBy int
	LastHitT  float64

	Score int

	think float64
}

type Client struct {
	send   chan []byte
	player *Player
	closed bool
}

type Game struct {
	mu         sync.Mutex
	players    map[int]*Player
	clients    map[*Client]struct{}
	nextID     int
	now        float64
	tick       int
	phase      int
	phaseT     float64
	radius     float64
	minPlayers int
	events     []map[string]any
}

func NewGame(minPlayers int) *Game {
	g := &Game{
		players:    map[int]*Player{},
		clients:    map[*Client]struct{}{},
		minPlayers: minPlayers,
	}
	g.startRound()
	return g
}

// ==== lifecycle ====

func (g *Game) startRound() {
	g.phase = phasePlay
	g.phaseT = roundTime
	g.radius = arenaMax
	for _, p := range g.players {
		p.Score = 0
		g.respawn(p)
	}
	g.events = append(g.events, map[string]any{"k": "start"})
}

func (g *Game) endRound() {
	g.phase = phaseEnd
	g.phaseT = intermission
	var best *Player
	tie := false
	for _, p := range g.players {
		switch {
		case best == nil || p.Score > best.Score:
			best, tie = p, false
		case p.Score == best.Score:
			tie = true
		}
	}
	ev := map[string]any{"k": "end", "w": "", "s": 0}
	if best != nil && best.Score > 0 && !tie {
		ev["w"], ev["s"] = best.Name, best.Score
	}
	g.events = append(g.events, ev)
}

func (g *Game) arenaRadius() float64 {
	if g.phase == phaseEnd {
		return arenaMin
	}
	elapsed := roundTime - g.phaseT
	if elapsed < shrinkDelay {
		return arenaMax
	}
	f := (elapsed - shrinkDelay) / (roundTime - shrinkDelay)
	return arenaMax - (arenaMax-arenaMin)*math.Min(f, 1)
}

func (g *Game) respawn(p *Player) {
	r := g.arenaRadius()
	best, bestDist := [2]float64{}, -1.0
	// pick the candidate spot farthest from everyone so nobody spawns inside a fight
	for range 12 {
		a := rand.Float64() * math.Pi * 2
		d := math.Sqrt(rand.Float64()) * r * 0.6
		x, z := math.Sin(a)*d, math.Cos(a)*d
		nearest := math.Inf(1)
		for _, o := range g.players {
			if o == p || o.Falling {
				continue
			}
			nearest = math.Min(nearest, math.Hypot(o.X-x, o.Z-z))
		}
		if nearest > bestDist {
			best, bestDist = [2]float64{x, z}, nearest
		}
	}
	p.X, p.Z, p.Y = best[0], best[1], 0
	p.VX, p.VZ, p.VY = 0, 0, 0
	p.Falling, p.FallT = false, 0
	p.Ghost = ghostTime
	p.DashCD, p.DashT = 0, 0
	p.LastHitBy = 0
	p.Angle = math.Atan2(-p.X, -p.Z)
}

// ==== simulation ====

func (g *Game) step(dt float64) {
	g.now += dt
	g.tick++
	g.phaseT -= dt
	if g.phaseT <= 0 {
		if g.phase == phasePlay {
			g.endRound()
		} else {
			g.startRound()
		}
	}
	g.radius = g.arenaRadius()

	g.thinkBots(dt)

	for _, p := range g.players {
		if p.Falling {
			p.FallT += dt
			p.VY -= fallGravity * dt
			p.Y += p.VY * dt
			p.X += p.VX * dt
			p.Z += p.VZ * dt
			p.VX *= 1 - 1.5*dt
			p.VZ *= 1 - 1.5*dt
			if p.FallT > respawnDelay {
				g.respawn(p)
			}
			continue
		}
		p.Ghost = math.Max(0, p.Ghost-dt)
		p.DashCD = math.Max(0, p.DashCD-dt)
		p.DashT = math.Max(0, p.DashT-dt)

		inLen := math.Hypot(p.InX, p.InZ)
		if inLen > 0.1 {
			p.Angle = math.Atan2(p.InX, p.InZ)
		}
		p.VX += p.InX * accel * dt
		p.VZ += p.InZ * accel * dt

		if p.WantDash && p.DashCD == 0 {
			p.VX += math.Sin(p.Angle) * dashImpulse
			p.VZ += math.Cos(p.Angle) * dashImpulse
			p.DashCD = dashCooldown
			p.DashT = dashTime
			p.Ghost = 0
		}
		p.WantDash = false

		damp := 1 - drag*dt
		p.VX *= damp
		p.VZ *= damp
		p.X += p.VX * dt
		p.Z += p.VZ * dt
	}

	g.collide()

	for _, p := range g.players {
		if !p.Falling && math.Hypot(p.X, p.Z) > g.radius {
			g.knockOut(p)
		}
	}
}

func (p *Player) mass() float64 {
	if p.DashT > 0 {
		return dashMass
	}
	return 1
}

func (g *Game) collide() {
	list := make([]*Player, 0, len(g.players))
	for _, p := range g.players {
		if !p.Falling && p.Ghost == 0 {
			list = append(list, p)
		}
	}
	for i := 0; i < len(list); i++ {
		for j := i + 1; j < len(list); j++ {
			a, b := list[i], list[j]
			dx, dz := b.X-a.X, b.Z-a.Z
			d := math.Hypot(dx, dz)
			overlap := playerRadius*2 - d
			if overlap <= 0 {
				continue
			}
			if d < 1e-6 {
				dx, dz, d = 1, 0, 1
			}
			nx, nz := dx/d, dz/d
			ia, ib := 1/a.mass(), 1/b.mass()
			a.X -= nx * overlap * ia / (ia + ib)
			a.Z -= nz * overlap * ia / (ia + ib)
			b.X += nx * overlap * ib / (ia + ib)
			b.Z += nz * overlap * ib / (ia + ib)

			vn := (b.VX-a.VX)*nx + (b.VZ-a.VZ)*nz
			if vn >= 0 {
				continue
			}
			j := -(1 + restitution) * vn / (ia + ib)
			// flat kick on top of the impulse so even slow touches feel like a bonk
			kick := j + bumpKick
			a.VX -= nx * kick * ia
			a.VZ -= nz * kick * ia
			b.VX += nx * kick * ib
			b.VZ += nz * kick * ib

			a.LastHitBy, a.LastHitT = b.ID, g.now
			b.LastHitBy, b.LastHitT = a.ID, g.now
			if j > 6 {
				g.events = append(g.events, map[string]any{
					"k": "b", "x": r2(a.X + nx*playerRadius), "z": r2(a.Z + nz*playerRadius), "p": r2(j),
				})
			}
		}
	}
}

func (g *Game) knockOut(p *Player) {
	p.Falling = true
	p.FallT = 0
	p.VY = 3
	killer := 0
	if p.LastHitBy != 0 && g.now-p.LastHitT < creditWindow {
		if k, ok := g.players[p.LastHitBy]; ok && k != p {
			killer = k.ID
			if g.phase == phasePlay {
				k.Score++
			}
		}
	}
	g.events = append(g.events, map[string]any{"k": "ko", "a": killer, "v": p.ID})
}

// ==== bots ====

func (g *Game) syncBots() {
	humans, bots := 0, []*Player{}
	for _, p := range g.players {
		if p.Bot {
			bots = append(bots, p)
		} else {
			humans++
		}
	}
	want := 0
	if humans > 0 {
		want = max(0, g.minPlayers-humans)
	}
	for len(bots) > want {
		delete(g.players, bots[len(bots)-1].ID)
		bots = bots[:len(bots)-1]
	}
	for len(bots) < want {
		p := g.newPlayer(g.freeBotName(), rand.IntN(paletteSize), rand.IntN(hatCount), true)
		bots = append(bots, p)
	}
}

func (g *Game) freeBotName() string {
	used := map[string]bool{}
	for _, p := range g.players {
		used[p.Name] = true
	}
	for _, i := range rand.Perm(len(botNames)) {
		if !used[botNames[i]] {
			return botNames[i]
		}
	}
	return botNames[rand.IntN(len(botNames))]
}

func (g *Game) thinkBots(dt float64) {
	for _, b := range g.players {
		if !b.Bot || b.Falling {
			continue
		}
		b.think -= dt
		if b.think > 0 {
			continue
		}
		b.think = 0.15 + rand.Float64()*0.2

		var target *Player
		best := math.Inf(1)
		for _, o := range g.players {
			if o == b || o.Falling || o.Ghost > 0 {
				continue
			}
			if d := math.Hypot(o.X-b.X, o.Z-b.Z); d < best {
				best, target = d, o
			}
		}

		dx, dz := -b.X, -b.Z
		if target != nil {
			// aim slightly past the target on the far side from center to push it outward
			dx, dz = target.X-b.X+target.X*0.15, target.Z-b.Z+target.Z*0.15
		}
		dx += (rand.Float64() - 0.5) * 3
		dz += (rand.Float64() - 0.5) * 3

		fromCenter := math.Hypot(b.X, b.Z)
		edgeDanger := fromCenter - (g.radius - 2.5)
		if edgeDanger > 0 {
			w := edgeDanger * 3
			dx -= b.X / fromCenter * w
			dz -= b.Z / fromCenter * w
		}
		if l := math.Hypot(dx, dz); l > 0 {
			b.InX, b.InZ = dx/l, dz/l
		}

		if target != nil && best < 3.4 && edgeDanger < -1 && rand.Float64() < 0.25 {
			b.WantDash = true
		}
	}
}

// ==== players and clients ====

func (g *Game) newPlayer(name string, color, hat int, bot bool) *Player {
	g.nextID++
	p := &Player{ID: g.nextID, Name: name, Color: color, Hat: hat, Bot: bot}
	g.players[p.ID] = p
	g.respawn(p)
	return p
}

func (g *Game) humanCount() int {
	n := 0
	for _, p := range g.players {
		if !p.Bot {
			n++
		}
	}
	return n
}

func (g *Game) addClient(c *Client) {
	g.mu.Lock()
	defer g.mu.Unlock()
	g.clients[c] = struct{}{}
	g.queue(c, g.rosterMsg())
}

func (g *Game) removeClient(c *Client) {
	g.mu.Lock()
	defer g.mu.Unlock()
	delete(g.clients, c)
	c.closed = true
	close(c.send)
	if c.player != nil {
		delete(g.players, c.player.ID)
		g.syncBots()
		g.broadcast(g.rosterMsg())
	}
}

type inMsg struct {
	T string  `json:"t"`
	N string  `json:"n"`
	C int     `json:"c"`
	H int     `json:"h"`
	X float64 `json:"x"`
	Z float64 `json:"z"`
}

func (g *Game) handle(c *Client, m inMsg) {
	g.mu.Lock()
	defer g.mu.Unlock()
	switch m.T {
	case "join":
		if c.player != nil {
			return
		}
		if g.humanCount() >= maxHumans {
			g.queue(c, mustJSON(map[string]any{"t": "full"}))
			return
		}
		color := m.C
		if color < 0 || color >= paletteSize {
			color = rand.IntN(paletteSize)
		}
		hat := m.H
		if hat < 0 || hat >= hatCount {
			hat = 0
		}
		c.player = g.newPlayer(cleanName(m.N), color, hat, false)
		g.syncBots()
		g.queue(c, mustJSON(map[string]any{
			"t": "welcome", "id": c.player.ID,
			"cfg": map[string]any{"pr": playerRadius, "max": arenaMax, "min": arenaMin, "cd": dashCooldown},
		}))
		g.broadcast(g.rosterMsg())
	case "in":
		if c.player == nil || math.IsNaN(m.X) || math.IsNaN(m.Z) {
			return
		}
		x, z := m.X, m.Z
		if l := math.Hypot(x, z); l > 1 {
			x, z = x/l, z/l
		}
		c.player.InX, c.player.InZ = x, z
	case "dash":
		if c.player != nil {
			c.player.WantDash = true
		}
	}
}

func cleanName(s string) string {
	s = strings.Map(func(r rune) rune {
		if unicode.IsControl(r) {
			return -1
		}
		return r
	}, s)
	s = strings.TrimSpace(s)
	if r := []rune(s); len(r) > 16 {
		s = string(r[:16])
	}
	if s == "" {
		s = "Blob"
	}
	return s
}

// ==== networking output ====

func (g *Game) queue(c *Client, msg []byte) {
	if c.closed {
		return
	}
	select {
	case c.send <- msg:
	default:
		// client is too slow; dropping a frame beats stalling the whole game loop
	}
}

func (g *Game) broadcast(msg []byte) {
	for c := range g.clients {
		g.queue(c, msg)
	}
}

func (g *Game) rosterMsg() []byte {
	list := make([]map[string]any, 0, len(g.players))
	for _, p := range g.players {
		list = append(list, map[string]any{"i": p.ID, "n": p.Name, "c": p.Color, "h": p.Hat, "b": p.Bot})
	}
	return mustJSON(map[string]any{"t": "roster", "p": list})
}

func (g *Game) snapshot() []byte {
	ps := make([][8]float64, 0, len(g.players))
	for _, p := range g.players {
		flags := 0
		if p.DashT > 0 {
			flags |= flagDash
		}
		if p.Ghost > 0 {
			flags |= flagGhost
		}
		if p.Falling {
			flags |= flagFall
		}
		ps = append(ps, [8]float64{
			float64(p.ID), r2(p.X), r2(p.Z), r2(p.Y), r2(p.Angle),
			float64(flags), r2(p.DashCD / dashCooldown), float64(p.Score),
		})
	}
	msg := map[string]any{
		"t": "s", "now": r2(g.now), "r": r2(g.radius),
		"ph": g.phase, "tl": r2(math.Max(0, g.phaseT)), "p": ps,
	}
	if len(g.events) > 0 {
		msg["e"] = g.events
		g.events = nil
	}
	return mustJSON(msg)
}

func r2(v float64) float64 { return math.Round(v*100) / 100 }

func mustJSON(v any) []byte {
	b, err := json.Marshal(v)
	if err != nil {
		panic(err)
	}
	return b
}
