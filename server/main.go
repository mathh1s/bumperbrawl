package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/coder/websocket"
)

func main() {
	addr := ":" + env("PORT", "8080")
	minPlayers, _ := strconv.Atoi(env("MIN_PLAYERS", "4"))
	roundSeconds, err := strconv.ParseFloat(env("ROUND_SECONDS", "120"), 64)
	if err != nil {
		roundSeconds = 120
	}
	webDir := env("WEB_DIR", "")
	if webDir == "" {
		webDir = "../web"
		if _, err := os.Stat("web"); err == nil {
			webDir = "web"
		}
	}
	var origins []string
	if o := env("ALLOWED_ORIGINS", ""); o != "" {
		origins = strings.Split(o, ",")
	}

	lobby := NewLobby(minPlayers, roundSeconds)

	mux := http.NewServeMux()
	mux.Handle("/", http.FileServer(http.Dir(webDir)))
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) { w.Write([]byte("ok")) })
	mux.HandleFunc("POST /api/rooms", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"code": lobby.newCode()})
	})
	mux.HandleFunc("/ws", func(w http.ResponseWriter, r *http.Request) { lobby.serveWS(w, r, origins) })

	log.Printf("bumper brawl listening on %s (web: %s)", addr, webDir)
	log.Fatal(http.ListenAndServe(addr, mux))
}

func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func (g *Game) run(stop <-chan struct{}) {
	t := time.NewTicker(time.Second / tickRate)
	defer t.Stop()
	for {
		select {
		case <-stop:
			return
		case <-t.C:
		}
		g.mu.Lock()
		g.step(1.0 / tickRate)
		if g.tick%sendEvery == 0 && len(g.clients) > 0 {
			g.broadcast(g.snapshot())
		}
		g.mu.Unlock()
	}
}

func (l *Lobby) serveWS(w http.ResponseWriter, r *http.Request, origins []string) {
	conn, err := websocket.Accept(w, r, &websocket.AcceptOptions{OriginPatterns: origins})
	if err != nil {
		return
	}
	defer conn.CloseNow()
	conn.SetReadLimit(2048)

	ctx, cancel := context.WithCancel(r.Context())
	defer cancel()

	c := &Client{send: make(chan []byte, 64)}
	g, err := l.join(normalizeCode(r.URL.Query().Get("room")), c)
	if err != nil {
		wctx, wcancel := context.WithTimeout(ctx, 5*time.Second)
		defer wcancel()
		conn.Write(wctx, websocket.MessageText, mustJSON(map[string]any{"t": "full", "why": "rooms"}))
		conn.Close(websocket.StatusTryAgainLater, "too many rooms")
		return
	}
	defer g.removeClient(c)

	go func() {
		defer cancel()
		for {
			select {
			case msg, ok := <-c.send:
				if !ok {
					return
				}
				wctx, wcancel := context.WithTimeout(ctx, 5*time.Second)
				err := conn.Write(wctx, websocket.MessageText, msg)
				wcancel()
				if err != nil {
					return
				}
			case <-ctx.Done():
				return
			}
		}
	}()

	for {
		_, data, err := conn.Read(ctx)
		if err != nil {
			return
		}
		var m inMsg
		if json.Unmarshal(data, &m) == nil {
			g.handle(c, m)
		}
	}
}
