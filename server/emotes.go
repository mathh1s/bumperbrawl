package main

import "math/rand/v2"

// Emotes are quick reactions shown as a bubble over a blob. The server only checks
// the id and a cooldown; the client decides what each id looks like (web/emotes.js).

const (
	emoteCount    = 8
	emoteCooldown = 1.2
	botGloat      = 0.3 // chance a bot reacts after knocking someone off

	emoteLaugh = 1
	emoteGG    = 6
)

func (g *Game) emote(p *Player, id int) {
	if id < 0 || id >= emoteCount || g.now < p.EmoteAt {
		return
	}
	p.EmoteAt = g.now + emoteCooldown
	g.events = append(g.events, map[string]any{"k": "em", "i": p.ID, "e": id})
}

// botReact lets a bot laugh at a knockout now and then, so emotes show up even with few humans
func (g *Game) botReact(killer *Player) {
	if killer == nil || !killer.Bot || rand.Float64() >= botGloat {
		return
	}
	g.emote(killer, []int{emoteLaugh, emoteGG}[rand.IntN(2)])
}
