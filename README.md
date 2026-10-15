# Bumper Brawl

A small online 3D party brawler. Everyone is a squishy blob on a floating hex island. Bump and dash into other players to knock them into the sea. After 15 seconds the island starts crumbling from the edges, so the arena gets tighter until the round ends. A match is several rounds of different modes, and whoever wins the most rounds wins the match.

- Server: Go, authoritative physics at 60 Hz, state broadcast at 20 Hz over WebSockets
- Client: Three.js (vendored, no CDN), toon-shaded low-poly look, snapshot interpolation for other players and client-side prediction with server reconciliation for your own
- Bots top the lobby up to `MIN_PLAYERS` whenever at least one human is playing
- Works on desktop (WASD / arrows, Shift dash, Space jump) and touch (virtual stick, dash and jump buttons)
- Matches of several rounds, each in one of five modes; the most round wins takes the match:
  - Bonk Brawl: every knockout scores
  - Last Blob Standing: three lives each, last one on the island wins
  - King of the Hill: hold the moving ring, closest to its centre scores
  - Coin Rush: grab coins, getting knocked off spills half of yours
  - Blob Ball: two teams and a big ball, bonk it into the other team's goal (the island doesn't crumble and a fence keeps the ball in)
- Hold dash to charge a stronger launch; tap for a quick one
- Power-up crates: heavy, bouncy and ground pound
- In the last 30 seconds a giant log sweeps the island; jump it or get swept away
- The leader wears a crown worth 2 points to whoever knocks them off; rounds end on a podium
- Private rooms: "Play with friends" creates a room at `/?room=CODE` to share. It opens in a lobby that lists who joined and who is ready; the host (first one in) picks rounds, round length, bots and modes, and the match starts when everyone is ready or the host starts it. Private rooms can also play a Knockout match: after each round only the best 60% go through, the eliminated watch, and the last three or fewer play a Last Blob Standing final. After the match the room goes back to the lobby. Empty rooms close after a minute

## Run with Docker

```sh
cp .env.example .env    # pick a free HOST_PORT
docker compose up -d --build
```

Open `http://<host>:<HOST_PORT>`.

## Run locally without Docker

```sh
cd server
go run .
```

Then open http://localhost:8080. `PORT` changes the listen port.

## Config

| Variable          | Default | Meaning                                                        |
|-------------------|---------|----------------------------------------------------------------|
| `PORT`            | 8080    | Listen port inside the container / process                     |
| `MIN_PLAYERS`     | 4       | Bots fill up to this many players (0 = no bots)                |
| `ROUND_SECONDS`   | 120     | Round length, at least 30                                      |
| `MATCH_ROUNDS`    | 5       | Rounds per match                                               |
| `ALLOWED_ORIGINS` | empty   | Extra allowed WebSocket origins; same-origin always works      |
| `WEB_DIR`         | auto    | Static files directory                                         |

## Reverse proxy

The websocket lives at `/ws` on the same host as the page. Behind nginx or Caddy, make sure upgrade headers are forwarded (Caddy does this automatically). For nginx:

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
}
```

## Soundtrack and sound effects

The music in `web/music/` is composed in `tools/music/compose.py` and rendered with the
[GeneralUser GS](https://github.com/mrbumpy409/GeneralUser-GS) soundfont and, for the two round themes,
MuseScore General (MIT; S. Christian Collins, based on FluidR3 by Frank Wen). To change or regenerate it:

```sh
pip install --no-deps tinysoundfont && pip install numpy scipy
git clone --depth 1 https://github.com/mrbumpy409/GeneralUser-GS /tmp/gugs
curl -Lo /tmp/msg.sf2 https://ftp.osuosl.org/pub/musescore/soundfont/MuseScore_General/MuseScore_General.sf2
python3 tools/music/compose.py /tmp/gugs/GeneralUser-GS.sf2 /tmp/msg.sf2
```

This rewrites the mp3 files and `web/music/tracks.json` (loop points). The sound effects in `web/sfx/` come from
`python3 tools/music/sfx.py /tmp/gugs/GeneralUser-GS.sf2` the same way. ffmpeg with libmp3lame is required.

## Layout

```
server/  game.go   simulation, rounds, bots, snapshots
         movement.go  steering, dashes, knockback control (mirrored in web/predict.js)
         room.go      private room lobby: host, ready checks, settings
         knockout.go  knockout match format
         mode_ball.go Blob Ball: teams, ball physics, goals, bot play
         main.go   http server, websocket handling, game loop
web/     main.js   netcode, interpolation, camera, HUD
         predict.js  client-side prediction of your own blob
         lobby.js    private room lobby panel
         ball.js     Blob Ball ball, goals and fence
         world.js  sky, water, crumbling island, scenery
         blobs.js    player characters and hats
         preview.js  blob preview in the menu
         fx.js       particles
         audio.js    sound effect playback
         music.js    soundtrack playback and crossfades
         input.js    keyboard and touch controls
         music/      rendered soundtrack and loop points
         sfx/        rendered sound effects
tools/   music/compose.py  soundtrack composition and rendering
         music/sfx.py      sound effect design and rendering
```
