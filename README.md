# Air Cricket

A 3D night-match cricket batting game that runs in the browser. Bat with the keyboard, touch buttons, or your camera.

**Play:** https://dhruwayush.github.io/air-cricket/

## Controls

| Input | Shot |
| --- | --- |
| `←` / `→` | Hit to the left or right side |
| `↑` or `Space` | Straight drive |
| `↓` | Block |
| Hold `Shift` | Hit it in the air |
| `A` / `D` | Step across the crease |
| `C` | Recentre camera tracking |

### Camera modes

- **Camera · hand** uses MediaPipe hand tracking (loads from the internet the first time).
- **Camera · object as bat** tracks a brightly coloured object you hold. It needs no download.

Swipe left or right fast to play to that side, and angle the swipe upward to go aerial. Swipe down for a straight drive. Push toward the camera to block. Drift sideways slowly to step across the crease.

The camera only works on an `https://` page, so play from the GitHub Pages link rather than a downloaded file.

## Android app

Every push to `main` builds an APK on GitHub Actions. Download the latest from
**Releases → Android APK (latest)** (`air-cricket.apk`), open it on your phone and allow installing from that source.

- The game, three.js and fonts are bundled, so it plays offline. Hand tracking still downloads its model the first time.
- The camera modes work in the app (Android asks for camera permission the first time).
- New builds install over the old one, no uninstall needed.

To build locally you need Node 22, JDK 21 and the Android SDK:

```sh
npm install
npm run apk      # -> android/app/build/outputs/apk/debug/app-debug.apk
```

`tools/prepare-www.mjs` copies `index.html` into `www/` and swaps the CDN scripts and Google Fonts for local copies; `npm run sync` copies that into `android/`.

## How it works

- **Three.js** renders the ground, players and ball.
- **Players are modelled and animated in Blender** by a script (`tools/players.py`): a padded, helmeted batsman and a capped fielder, both rigged with a skeleton.
  - The batsman has stance, backlift, straight drive, cover drive, flick, pull, cut, block, lofted drive, leave, running and non-striker idle. In every shot the bat meets the ball on the same frame, so the animation stays in sync with the timing.
  - Fielders have idle, ready, run, catch, dive, pick-up, throw and a full bowling action. The keeper adds a squat and a take, and wears pads and gauntlets (a second mesh on the fielder skeleton).
- Each delivery is simulated ahead of time with gravity, bounce, swing and spin.
- Your timing against the ball's arrival sets the power. Early timing pulls the ball to the leg side and late timing pushes it to the off side. Drives go into the gaps, and cuts and pulls go square.
- Fielders work out whether they can reach the ball in time to catch it, stop it, or chase it to the rope. Harder-hit balls are harder to stop. Only fielders you can see on the field take part, including a padded wicket-keeper and a first slip.
- Low catches are taken crouching with hands together, high ones with the hands up. A dropped catch pops out of the hands, falls, and is picked up and thrown back.
- The ball collides with the batsman's animated pads, thighs, body and helmet and rebounds. LBW is decided like ball tracking: where it pitched, whether the impact was in line (or outside off with no shot offered), and whether it would have gone on to hit the stumps.
- Balls you leave or miss carry through to the keeper's gloves.
- The batsmen run between the wickets, and fielders pick up and throw back.
- A perfectly timed shot gets a short hit-stop, a slow-motion moment and camera shake. On Club level the spot where the ball will pitch is shown as it is bowled.
- All input goes through `requestShot(direction)` and `setGuard(position)`, so new controllers can plug in without touching game logic.

## Modes

- **Chase 36 off 2 overs** with 3 wickets
- **Free nets**
- Three bowling levels: Club, Pro, International
- Right- or left-handed batting

## Working on it

| Path | What it is |
| --- | --- |
| `src/game.html` | The game source |
| `tools/players.py` | Builds, rigs and animates the players in Blender and exports `tools/build/*.glb` |
| `tools/build_page.py` | Embeds the models into `src/game.html` and writes `index.html` |

```sh
pip install bpy==4.2.0            # Blender as a Python module (Python 3.11)
python3 tools/players.py           # rebuild the players -> tools/build/
python3 tools/players.py bat pull,cut 0.167,0.45   # render preview frames to tools/preview/
python3 tools/build_page.py        # rebuild index.html
```
