# Air Cricket rooms

The room server behind **Play a friend**. It's a Cloudflare Worker with one Durable Object per room. Each
room remembers who is in it and how each player is getting on, and passes updates between them over
WebSockets. The cricket itself runs on each phone; only room codes, names and scores travel.

The free Workers plan covers this comfortably: a match sends roughly one small message per ball per player.

## Deploy it (once)

You need a free Cloudflare account and Node 18 or later.

```sh
cd server
npm install
npx wrangler login        # opens a browser to sign in to Cloudflare
npx wrangler deploy       # prints https://air-cricket-rooms.<your-subdomain>.workers.dev
```

Then point the game at it: in `src/game.html` set

```js
const ROOMS_URL = 'wss://air-cricket-rooms.<your-subdomain>.workers.dev';
```

(note `wss://`, not `https://`), rebuild with `python3 tools/build_page.py`, and push. Until `ROOMS_URL`
is set, Play a friend is hidden from the mode picker.

## Try it locally

```sh
cd server && npx wrangler dev --port 8787        # the room server on your machine
python3 -m http.server 8000                       # from the repo root, in another terminal
```

Open `http://localhost:8000/?rooms=ws://127.0.0.1:8787` in two browser windows (use a private window for
the second, so it counts as a different player). Create a room in one and join it from the other.
The `?rooms=` address also travels in Invite links, so you can test a server before setting `ROOMS_URL`.

## How a room works

| Client sends | Room sends to everyone |
| --- | --- |
| `hello { pid, name, mode: 'create' \| 'join' }` | `roster { code, host, round, match, players }` |
| `start { level }` (host only) | `start { code, level, round }`: a new chase code for everyone |
| `ball { round, runs, wkts, balls, mark }` after every ball | `ball { pid, ... }` |
| `done { round, runs, wkts, balls, res }` at the end of an innings | `done { pid, ... }` |
| `leave {}` | an updated `roster` |

- Codes are four characters without I, O, 0 or 1. A room holds up to four players.
- A player who drops shows as away and can rejoin with the same id (one per browser tab) and keep their score.
- If the host leaves, the next player becomes host. If the host is away, whoever presses Start takes over.
- An empty room is forgotten after an hour.
- Scores are reported by each phone and trusted, which is fine between friends. A public leaderboard would
  need the server to check results.
