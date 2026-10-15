package main

import (
	"encoding/json"
	"math"
	"math/rand/v2"
	"slices"
	"strings"
	"sync"
	"unicode"
)

const (
	tickRate     = 60
	sendEvery    = 3 // 20 snapshots per second
	playerRadius = 0.8
	dashImpulse  = 15.0
	dashCooldown = 1.1
	dashTime     = 0.28
	dashMass     = 2.6
	chargeMax    = 0.9
	chargeSlow   = 0.35
	restitution  = 1.25
	bumpKick     = 2.5
	fallGravity  = 30.0
	respawnDelay = 1.8
	ghostTime    = 1.5
	creditWindow = 3.5
	arenaMax     = 15.0
	arenaMin     = 6.0
	minRoundTime = 30.0
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
	flagDash   = 1
	flagGhost  = 2
	flagFall   = 4
	flagCharge = 8
)

var botNames = []string{"Bonk", "Creamy", "Wobbles", "Sir Bump", "Jellybean", "Puddin", "Mochi", "Gloop", "Tofu", "Goofball", "Xx_OP_GAMER_xX", "iluvtsgame", "urmom", "nadamagafagabagerrager"}

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
	Ack      int64 // last input step the client numbered
	AckTicks int   // ticks simulated since that input arrived
	WantDash bool
	WantJump bool
	Airborne bool
	JumpCD   float64
	SweepCD  float64

	DashCD     float64
	DashT      float64
	DashPow    float64
	DashCDMax  float64
	Charging   bool
	ChargeT    float64
	ChargeStep int64
	Pow        int
	PowT       float64
	PoundT     float64
	Ghost      float64
	Ready      bool
	Elim       bool // knocked out of a knockout match
	OutAt      float64
	Stun       float64
	Falling    bool
	FallT      float64

	LastHitBy int
	LastHitT  float64

	Score    int
	Lives    int
	Out      bool
	HillT    float64
	Wins     int
	MatchPts int

	think      float64
	botRelease float64
}

type Client struct {
	send   chan []byte
	player *Player
	closed bool
}

type Game struct {
	mu        sync.Mutex
	players   map[int]*Player
	clients   map[*Client]struct{}
	nextID    int
	now       float64
	tick      int
	phase     int
	phaseT    float64
	radius    float64
	cfg       Config
	events    []map[string]any
	crates    []*Crate
	crateT    float64
	nextCrate int
	crownID   int
	code      string
	roundNo   int
	mode      int
	modeOrder []int
	hill      Hill
	coins     []Coin
	coinT     float64
	nextCoin  int
	sweepA    float64
	sweepDir  float64
	sweepOn   bool

	private  bool
	hostID   int
	counting bool
	forced   bool
	modes    []int
	format   int
	final    bool
	qualify  int
	koDone   bool
}

func NewGame(code string, cfg Config) *Game {
	cfg.RoundTime = math.Max(minRoundTime, cfg.RoundTime)
	cfg.MatchRounds = max(1, cfg.MatchRounds)
	g := &Game{
		code:    code,
		players: map[int]*Player{},
		clients: map[*Client]struct{}{},
		cfg:     cfg,
		modes:   slices.Clone(allModes),
		private: code != "",
	}
	if g.private {
		g.enterLobby()
		g.events = nil
		return g
	}
	g.newMatch()
	g.startRound()
	return g
}

// ==== lifecycle ====

func (g *Game) startRound() {
	g.roundNo++
	g.mode = g.modeOrder[(g.roundNo-1)%len(g.modeOrder)]
	if g.knockout() {
		g.startKnockoutRound()
	}
	g.phase = phasePlay
	g.phaseT = g.cfg.RoundTime
	g.radius = arenaMax
	g.clearCrates()
	g.resetSweeper()
	for _, p := range g.players {
		p.Score, p.Lives, p.Out = 0, 0, false
		g.respawn(p)
	}
	switch g.mode {
	case modeLast:
		g.startLast()
	case modeHill:
		g.startHill()
	case modeCoins:
		g.startCoins()
	}
	for _, p := range g.players {
		if p.Elim {
			g.bench(p)
		}
	}
	g.events = append(g.events, map[string]any{
		"k": "start", "m": g.mode, "r": g.roundNo, "of": g.cfg.MatchRounds, "fm": g.format, "kq": g.qualify, "fin": g.final,
	})
}

func (g *Game) endRound() {
	g.phase = phaseEnd
	g.clearCrates()
	top := g.podium()
	ev := map[string]any{"k": "end", "m": g.mode, "r": g.roundNo, "of": g.cfg.MatchRounds, "fm": g.format, "s": 0}
	// knockout rounds before the final are about qualifying, not winning
	var winners []*Player
	if !g.knockout() || g.final {
		winners = g.awardRound()
	}
	if g.knockout() {
		g.endKnockoutRound(ev)
	}
	ev["w"], ev["top"], ev["st"], ev["mo"] = names(winners), top, g.standings(), g.matchOver()
	if len(winners) > 0 {
		ev["s"] = winners[0].Score
	}
	g.phaseT = intermission
	if g.matchOver() {
		g.phaseT = matchIntermission
		ev["ch"] = names(g.champions())
		ev["top"] = g.matchPodium()
	}
	g.events = append(g.events, ev)
}

func (g *Game) arenaRadius() float64 {
	switch g.phase {
	case phaseEnd:
		return arenaMin
	case phaseLobby:
		return arenaMax
	}
	elapsed := g.cfg.RoundTime - g.phaseT
	if elapsed < shrinkDelay {
		return arenaMax
	}
	f := (elapsed - shrinkDelay) / (g.cfg.RoundTime - shrinkDelay)
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
	p.Charging, p.ChargeT = false, 0
	p.Pow, p.PowT, p.PoundT = powNone, 0, 0
	p.Airborne, p.JumpCD, p.SweepCD, p.Stun = false, 0, 0, 0
	p.LastHitBy = 0
	p.Angle = math.Atan2(-p.X, -p.Z)
}

// ==== simulation ====

func (g *Game) step(dt float64) {
	g.now += dt
	g.tick++
	if g.phase == phaseLobby {
		g.stepLobby(dt)
	} else if g.phaseT -= dt; g.phaseT <= 0 {
		switch {
		case g.phase == phasePlay:
			g.endRound()
		case g.matchOver() && g.private:
			g.enterLobby()
			g.broadcast(g.roomMsg())
		case g.matchOver():
			g.newMatch()
			g.startRound()
		default:
			g.startRound()
		}
	}
	g.radius = g.arenaRadius()

	g.thinkBots(dt)

	for _, p := range g.players {
		// eliminated blobs finish their fall into the sea, then sit out the round
		if p.Out && p.FallT > respawnDelay {
			continue
		}
		if p.Falling {
			p.FallT += dt
			p.VY -= fallGravity * dt
			p.Y += p.VY * dt
			p.X += p.VX * dt
			p.Z += p.VZ * dt
			p.VX *= 1 - 1.5*dt
			p.VZ *= 1 - 1.5*dt
			if p.FallT > respawnDelay {
				if p.Out {
					p.Y = outParkedAt
				} else {
					g.respawn(p)
				}
			}
			continue
		}
		p.Ghost = math.Max(0, p.Ghost-dt)
		p.DashCD = math.Max(0, p.DashCD-dt)
		p.DashT = math.Max(0, p.DashT-dt)
		g.updatePower(p, dt)
		g.updateJump(p, dt)

		p.move(dt)
	}

	g.collide()
	g.updateSweeper(dt)
	g.updateCrates(dt)
	g.updateHill(dt)
	g.updateCoins(dt)

	for _, p := range g.players {
		// jumps and ground pounds are airborne, so leaving the island only counts once they land
		if !p.Falling && p.PoundT == 0 && !p.Airborne && math.Hypot(p.X, p.Z) > g.radius {
			g.knockOut(p)
		}
	}
	g.updateCrown()
	for _, p := range g.players {
		p.AckTicks++
	}
	if g.phase == phasePlay && g.mode == modeLast && g.lastStandingDone() {
		g.endRound()
	}
}

func (p *Player) mass() float64 {
	m := 1.0
	if p.DashT > 0 {
		m = dashMass * (1 + 0.7*p.DashPow)
	}
	if p.Pow == powHeavy {
		m *= heavyMass
	}
	return m
}

func (g *Game) collide() {
	list := make([]*Player, 0, len(g.players))
	for _, p := range g.players {
		if !p.Falling && p.Ghost == 0 && p.PoundT == 0 {
			list = append(list, p)
		}
	}
	for i := 0; i < len(list); i++ {
		for j := i + 1; j < len(list); j++ {
			a, b := list[i], list[j]
			if math.Abs(a.Y-b.Y) > 1 {
				continue
			}
			dx, dz := b.X-a.X, b.Z-a.Z
			d := math.Hypot(dx, dz)
			overlap := a.radius() + b.radius() - d
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
			ka, kb := kick, kick
			if b.Pow == powBounce {
				ka *= bounceKick
			}
			if a.Pow == powBounce {
				kb *= bounceKick
			}
			a.shove(-nx*ka*ia, -nz*ka*ia)
			b.shove(nx*kb*ib, nz*kb*ib)

			a.LastHitBy, a.LastHitT = b.ID, g.now
			b.LastHitBy, b.LastHitT = a.ID, g.now
			if j > 6 {
				g.events = append(g.events, map[string]any{
					"k": "b", "x": r2(a.X + nx*a.radius()), "z": r2(a.Z + nz*a.radius()), "p": r2(math.Max(ka, kb)),
				})
			}
		}
	}
}

func (g *Game) knockOut(p *Player) {
	p.Falling = true
	p.Charging = false
	p.Airborne = false
	p.Pow, p.PowT, p.PoundT = powNone, 0, 0
	p.FallT = 0
	p.VY = 3
	ev := map[string]any{"k": "ko", "v": p.ID, "a": 0}
	var killer *Player
	if p.LastHitBy != 0 && g.now-p.LastHitT < creditWindow {
		if k, ok := g.players[p.LastHitBy]; ok && k != p {
			killer = k
			ev["a"] = k.ID
		}
	}
	if g.phase == phasePlay {
		g.scoreKnockOut(p, killer, ev)
	}
	g.events = append(g.events, ev)
}

func (g *Game) scoreKnockOut(victim, killer *Player, ev map[string]any) {
	switch g.mode {
	case modeLast:
		g.knockOutLast(victim)
		return
	case modeCoins:
		g.spillCoins(victim)
		return
	}
	if g.mode != modeBrawl || killer == nil {
		return
	}
	if victim.ID == g.crownID {
		killer.Score += crownBounty
		ev["cr"] = true
	} else {
		killer.Score++
	}
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
		want = max(0, g.cfg.MinPlayers-humans)
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
		g.botJump(b)
		if b.Charging {
			b.botRelease -= dt
			if b.botRelease <= 0 {
				b.WantDash = true
			}
		}
		b.think -= dt
		if b.think > 0 {
			continue
		}
		b.think = 0.15 + rand.Float64()*0.2

		var target *Player
		best, pick := math.Inf(1), math.Inf(1)
		for _, o := range g.players {
			if o == b || o.Falling || o.Ghost > 0 {
				continue
			}
			d := math.Hypot(o.X-b.X, o.Z-b.Z)
			score := d
			if o.ID == g.crownID {
				score -= crownBotPull
			}
			if g.mode == modeHill && o.inHill(g.hill) {
				score -= hillBotPull
			}
			if g.mode == modeCoins {
				score -= float64(o.Score) * botRichPull
			}
			if score < pick {
				pick, best, target = score, d, o
			}
		}

		dx, dz := -b.X, -b.Z
		if target != nil {
			// aim slightly past the target on the far side from center to push it outward
			dx, dz = target.X-b.X+target.X*0.15, target.Z-b.Z+target.Z*0.15
		}
		if tx, tz, ok := g.botCrateTarget(b); ok {
			dx, dz = tx-b.X, tz-b.Z
		} else if tx, tz, ok := g.botHillTarget(b); ok {
			dx, dz = tx-b.X, tz-b.Z
		} else if tx, tz, ok := g.botCoinTarget(b); ok {
			dx, dz = tx-b.X, tz-b.Z
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

		if b.Charging || b.DashCD > 0 || target == nil || edgeDanger >= -1 {
			continue
		}
		switch {
		case best < 3.4 && rand.Float64() < 0.25:
			b.WantDash = true
		case best < 6 && rand.Float64() < 0.12:
			b.Charging, b.ChargeT = true, 0
			b.botRelease = 0.3 + rand.Float64()*0.6
		}
	}
}

// ==== players and clients ====

func (g *Game) newPlayer(name string, color, hat int, bot bool) *Player {
	g.nextID++
	p := &Player{ID: g.nextID, Name: name, Color: color, Hat: hat, Bot: bot}
	g.players[p.ID] = p
	g.respawn(p)
	switch {
	case g.knockout() && g.phase != phaseLobby:
		// a knockout field is fixed once it starts, so latecomers watch until the next match
		g.bench(p)
	case g.phase == phasePlay && g.mode == modeLast:
		g.joinLast(p)
	}
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

func (g *Game) clientCount() int {
	g.mu.Lock()
	defer g.mu.Unlock()
	return len(g.clients)
}

func (g *Game) addClient(c *Client) {
	g.mu.Lock()
	defer g.mu.Unlock()
	g.clients[c] = struct{}{}
	g.queue(c, g.rosterMsg())
	if g.private {
		g.queue(c, g.roomMsg())
	}
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
		g.roomChanged()
	}
}

type inMsg struct {
	T string  `json:"t"`
	N string  `json:"n"`
	C int     `json:"c"`
	H int     `json:"h"`
	X float64 `json:"x"`
	Z float64 `json:"z"`
	S int64   `json:"s"`
	V bool    `json:"v"`

	Set *RoomSettings `json:"set"`
}

func (g *Game) handle(c *Client, m inMsg) {
	g.mu.Lock()
	defer g.mu.Unlock()
	if p := c.player; p != nil && m.S > p.Ack {
		p.Ack, p.AckTicks = m.S, 0
	}
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
			"t": "welcome", "id": c.player.ID, "room": g.code, "private": g.private,
			"cfg": map[string]any{"pr": playerRadius, "max": arenaMax, "min": arenaMin, "cd": dashCooldown, "mv": movementConfig()},
		}))
		g.broadcast(g.rosterMsg())
		g.roomChanged()
	case "ready", "settings", "start":
		if c.player != nil {
			g.handleRoom(c.player, m)
		}
	case "in":
		if c.player == nil || math.IsNaN(m.X) || math.IsNaN(m.Z) {
			return
		}
		x, z := m.X, m.Z
		if l := math.Hypot(x, z); l > 1 {
			x, z = x/l, z/l
		}
		c.player.InX, c.player.InZ = x, z
	case "charge":
		if p := c.player; p != nil && !p.Falling && p.DashCD == 0 && !p.Charging {
			p.Charging, p.ChargeT, p.ChargeStep = true, 0, m.S
		}
	case "jump":
		if c.player != nil {
			c.player.WantJump = true
		}
	case "dash":
		if p := c.player; p != nil {
			p.WantDash = true
			// time the charge by the client's steps so its prediction launches with the same power;
			// arrival times jitter by a tick or two. It can't claim more than it actually held.
			if p.Charging && p.ChargeStep > 0 && m.S > p.ChargeStep {
				held := float64(m.S-p.ChargeStep) / tickRate
				p.ChargeT = math.Min(chargeMax, math.Min(held, p.ChargeT+0.1))
			}
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
	ps := make([][11]float64, 0, len(g.players))
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
		if p.Charging {
			flags |= flagCharge
		}
		switch p.Pow {
		case powHeavy:
			flags |= flagHeavy
		case powBounce:
			flags |= flagBounce
		}
		if p.PoundT > 0 {
			flags |= flagPound
		}
		if p.Out {
			flags |= flagOut
		}
		cd := 0.0
		if p.DashCDMax > 0 {
			cd = p.DashCD / p.DashCDMax
		}
		ps = append(ps, [11]float64{
			float64(p.ID), r2(p.X), r2(p.Z), r2(p.Y), r2(p.Angle),
			float64(flags), r2(cd), float64(p.Score), r2(p.ChargeT / chargeMax), r2(p.PowT),
			float64(p.Wins),
		})
	}
	msg := map[string]any{
		"t": "s", "now": r2(g.now), "r": r2(g.radius),
		"ph": g.phase, "tl": r2(math.Max(0, g.phaseT)), "p": ps, "c": g.crateList(), "cw": g.crownID,
		"md": g.mode, "rn": g.roundNo, "rm": g.cfg.MatchRounds, "fm": g.format, "kq": g.qualify, "fin": g.final,
	}
	if g.mode == modeHill && g.phase == phasePlay {
		msg["hl"] = g.hillState()
	}
	if g.mode == modeCoins && g.phase == phasePlay {
		msg["co"] = g.coinList()
	}
	if g.sweepOn {
		msg["sw"] = [2]float64{r2(g.sweepA), r2(g.sweepHalf())}
	}
	if len(g.events) > 0 {
		msg["e"] = g.events
		g.events = nil
	}
	return mustJSON(msg)
}

// selfStates tells each client the full physics state of its own blob. The client predicts its blob
// ahead of the snapshots and, with these, replays the inputs the server had not seen yet.
func (g *Game) selfStates() {
	for c := range g.clients {
		p := c.player
		if p == nil {
			continue
		}
		bits := 0
		if p.Charging {
			bits |= 1
		}
		if p.Airborne {
			bits |= 2
		}
		g.queue(c, mustJSON(map[string]any{
			"t": "me", "s": p.Ack, "k": p.AckTicks, "b": bits,
			"st": [11]float64{r3(p.X), r3(p.Z), r3(p.Y), r3(p.VX), r3(p.VZ), r3(p.VY),
				r3(p.Stun), r3(p.DashT), r3(p.DashCD), r3(p.ChargeT), r3(p.JumpCD)},
		}))
	}
}

func r3(v float64) float64 { return math.Round(v*1000) / 1000 }

func r2(v float64) float64 { return math.Round(v*100) / 100 }

func mustJSON(v any) []byte {
	b, err := json.Marshal(v)
	if err != nil {
		panic(err)
	}
	return b
}
