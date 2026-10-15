package main

import (
	"math"
	"math/rand/v2"
)

const (
	modeCoins = 3

	coinTarget     = 10
	coinSpawnEvery = 0.6
	coinPickRange  = 1.0
	coinPickHeight = 1.5
	coinSpill      = 0.5
	coinMaxSpill   = 12
	coinEdgeMargin = 0.8
	botCoinSeek    = 10.0
	botRichPull    = 0.3
)

type Coin struct {
	ID   int
	X, Z float64
}

func (g *Game) startCoins() {
	g.coins = g.coins[:0]
	g.coinT = 0
	for range coinTarget / 2 {
		g.addCoin(g.coinSpot())
	}
}

func (g *Game) coinSpot() (float64, float64) {
	a := rand.Float64() * math.Pi * 2
	d := math.Sqrt(rand.Float64()) * math.Max(0, g.radius-coinEdgeMargin) * 0.85
	return math.Cos(a) * d, math.Sin(a) * d
}

func (g *Game) addCoin(x, z float64) int {
	g.nextCoin++
	g.coins = append(g.coins, Coin{ID: g.nextCoin, X: x, Z: z})
	return g.nextCoin
}

func (g *Game) updateCoins(dt float64) {
	if g.mode != modeCoins || g.phase != phasePlay {
		return
	}
	g.coinT -= dt
	if g.coinT <= 0 && len(g.coins) < coinTarget {
		g.coinT = coinSpawnEvery
		g.addCoin(g.coinSpot())
	}
	kept := g.coins[:0]
	for _, c := range g.coins {
		if math.Hypot(c.X, c.Z) > g.radius-coinEdgeMargin*0.5 {
			continue
		}
		if p := g.coinTaker(c); p != nil {
			p.Score++
			p.Stats.Coins++
			g.events = append(g.events, map[string]any{"k": "cp", "i": p.ID, "x": r2(c.X), "z": r2(c.Z)})
			continue
		}
		kept = append(kept, c)
	}
	g.coins = kept
}

func (g *Game) coinTaker(c Coin) *Player {
	for _, p := range g.players {
		if !p.Falling && p.Y < coinPickHeight && math.Hypot(p.X-c.X, p.Z-c.Z) < coinPickRange {
			return p
		}
	}
	return nil
}

// Getting knocked off spills half your coins back onto the island for anyone to grab.
func (g *Game) spillCoins(victim *Player) {
	n := min(coinMaxSpill, int(math.Ceil(float64(victim.Score)*coinSpill)))
	if n == 0 {
		return
	}
	victim.Score -= n
	ids := make([]int, n)
	for i := range ids {
		ids[i] = g.addCoin(g.coinSpot())
	}
	g.events = append(g.events, map[string]any{"k": "spill", "i": victim.ID, "x": r2(victim.X), "z": r2(victim.Z), "ids": ids})
}

func (g *Game) botCoinTarget(b *Player) (float64, float64, bool) {
	if g.mode != modeCoins || g.phase != phasePlay {
		return 0, 0, false
	}
	best := botCoinSeek
	var tx, tz float64
	found := false
	for _, c := range g.coins {
		if d := math.Hypot(c.X-b.X, c.Z-b.Z); d < best {
			best, tx, tz, found = d, c.X, c.Z, true
		}
	}
	return tx, tz, found
}

func (g *Game) coinList() [][3]float64 {
	list := make([][3]float64, 0, len(g.coins))
	for _, c := range g.coins {
		list = append(list, [3]float64{float64(c.ID), r2(c.X), r2(c.Z)})
	}
	return list
}
