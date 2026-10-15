package main

import (
	"math"
	"testing"
)

func tilesGame(bots int) *Game {
	g := testGame()
	for range bots {
		g.newPlayer("b", 0, 0, true)
	}
	g.modeOrder[0] = modeTiles
	g.roundNo = 0
	g.startRound()
	return g
}

func TestTileLookupMatchesTheGrid(t *testing.T) {
	g := testGame()
	for i, tile := range g.tiles {
		if got := g.tileAt(tile.X, tile.Z); got != i {
			t.Fatalf("tile %d at its own centre looked up as %d", i, got)
		}
		// a point well inside the hex still finds it
		if got := g.tileAt(tile.X+0.5, tile.Z-0.4); got != i {
			t.Fatalf("tile %d off-centre looked up as %d", i, got)
		}
	}
	if g.tileAt(arenaMax+5, 0) != -1 {
		t.Fatal("nothing past the island")
	}
}

func TestStandingStillDropsYou(t *testing.T) {
	g := tilesGame(0)
	p := g.newPlayer("p", 0, 0, false)
	other := g.newPlayer("q", 0, 0, false)
	other.X, other.Z = -8, 0
	p.X, p.Z = 5, 0
	lives := p.Lives
	runFor(g, tileGrace-0.1)
	if g.tiles[g.tileAt(5, 0)].State != tileSolid {
		t.Fatal("nothing cracks during the grace period")
	}
	runFor(g, 0.2+tileCrumble+0.3)
	if !p.Falling || p.Lives != lives-1 {
		t.Fatalf("standing on one tile until it drops should cost a life, lives %d falling %v", p.Lives, p.Falling)
	}
}

func TestJumpingDoesNotCrackTiles(t *testing.T) {
	g := tilesGame(0)
	p := g.newPlayer("p", 0, 0, false)
	p.X, p.Z = 3, 3
	runFor(g, tileGrace+0.05)
	i := g.tileAt(3, 3)
	g.tiles[i].State = tileSolid
	p.Airborne, p.Y = true, 1
	g.updateTiles(1.0 / tickRate)
	if g.tiles[i].State != tileSolid {
		t.Fatal("a tile only cracks under a blob standing on it")
	}
}

func TestBotsSurviveAWhile(t *testing.T) {
	g := tilesGame(6)
	runFor(g, 8)
	alive := 0
	for _, p := range g.players {
		if !p.Out {
			alive++
		}
	}
	if alive < 2 {
		t.Fatalf("bots should dodge holes for a while, only %d left after 8s", alive)
	}
	gone := 0
	for _, tl := range g.tiles {
		if tl.State == tileGone {
			gone++
		}
	}
	if gone == 0 || math.IsNaN(float64(gone)) {
		t.Fatal("tiles should be dropping")
	}
}

func TestDroppedTilesComeBackUntilTheEnd(t *testing.T) {
	g := tilesGame(0)
	g.tiles[0].State, g.tiles[0].T = tileGone, tileRegrow
	g.updateTiles(tileRegrow + 0.1)
	if g.tiles[0].State != tileSolid {
		t.Fatal("a dropped tile floats back after a while")
	}
	g.phaseT = tileNoRegrow - 1
	g.tiles[0].State, g.tiles[0].T = tileGone, tileRegrow
	g.updateTiles(tileRegrow + 0.1)
	if g.tiles[0].State != tileGone {
		t.Fatal("near the end of the round tiles stay gone")
	}
}

func TestEdgeOfATileHoldsYou(t *testing.T) {
	g := tilesGame(0)
	p := g.newPlayer("p", 0, 0, false)
	i := g.tileAt(0, 0)
	tile := g.tiles[i]
	// drop every tile except the one at the middle
	for k := range g.tiles {
		if k != i {
			g.tiles[k].State = tileGone
		}
	}
	// just past the tile's flat edge, most of the blob is still over it
	p.X, p.Z = tile.X+hexSize*math.Sqrt(3)/2+0.15, tile.Z
	if !g.supported(p) {
		t.Fatal("a blob hanging just over the edge should stay up")
	}
	p.X = tile.X + hexSize*math.Sqrt(3)/2 + 0.6
	if g.supported(p) {
		t.Fatal("a blob mostly over the hole should fall")
	}
}

func TestHangingOnAnEdgeStillCracksIt(t *testing.T) {
	g := tilesGame(0)
	p := g.newPlayer("p", 0, 0, false)
	g.tileGraceT = 0
	i := g.tileAt(0, 0)
	tile := g.tiles[i]
	p.X, p.Z = tile.X+hexSize*math.Sqrt(3)/2+0.15, tile.Z
	j := g.tileAt(p.X, p.Z)
	g.tiles[j].State, g.tiles[j].T = tileGone, tileRegrow
	g.updateTiles(1.0 / tickRate)
	if g.tiles[i].State != tileCracking {
		t.Fatal("the tile you're hanging on should crack")
	}
}
