# Air Cricket

A 3D night-match cricket batting game that runs in the browser. Bat with the keyboard, touch buttons, or your camera.

**Play:** https://dhruwayush.github.io/air-cricket/

## Controls

Aim with the arrow keys. The length of the ball decides front foot or back foot, so the same key plays a drive to a full ball and a punch or cut to a short one.

| Input | What it plays |
| --- | --- |
| `↑` or `Space` | Straight: straight drive, or back-foot punch |
| `↑` + `←` / `→` (together) | Drive: cover drive, on drive, back-foot drive |
| `←` / `→` | Square: square drive, cut, flick, pull (hook to a bouncer) |
| `↓` + `←` / `→` (together) | Fine: late cut, leg glance, glance off the hips |
| `↓` | Block: forward or back-foot defence |
| Hold `Shift` | In the air: lofted drives, slog, hook, upper cut, slog sweep |
| `Q` / `E` / `R` | Sweep (with `↓`: paddle sweep), reverse sweep, scoop over the keeper |
| `A` / `D` | Step across the crease |
| `M` | Show or hide the field map |
| `C` | Recentre camera tracking |

Leave a bouncer and the batsman ducks under it. On touch screens the pad has the same 8 directions plus Loft, Sweep, Rev and Scoop.

### Camera modes

- **Camera · hand** uses MediaPipe hand tracking (loads from the internet the first time).
- **Camera · object as bat** tracks a brightly coloured object you hold. It needs no download.

Swipe flat left or right to play square, down and across to drive to that side, and straight down for a straight drive. A rising swipe hits it in the air, and a faster swipe hits harder. Push toward the camera to block. Drift sideways slowly to step across the crease.

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
  - The batsman has 27 clips: stance, backlift, straight/cover/on/square drives, lofted drives, slog, flick, leg glance, back-foot punch and defence, forward defence, cut, late cut, upper cut, pull, hook, sweep, slog sweep, reverse sweep, scoop, leave, duck, running and non-striker idle. In every shot the bat meets the ball on the same frame, so the animation stays in sync with the timing.
  - Fielders have idle, ready, run, catch, dive, pick-up, throw and a full bowling action. The keeper adds a squat and a take, and wears pads and gauntlets (a second mesh on the fielder skeleton).
- Each delivery is simulated ahead of time with gravity, bounce, swing and spin. Pace bowlers mix in yorkers and bouncers, and some overs follow a short-ball plan.
- **The line varies, so leaving is a real decision.** Bowlers aim at the stumps, the corridor just outside off, wide of off, and now and then down the leg side or past the wide guideline. Death bowlers go for wide yorkers. Leave a straight one and you can be bowled or LBW; chase a wide one and you're likely to edge it. Leave a ball well outside off and you get a "Good leave". Club bowlers are wilder than International ones.
- **Wides.** The wide guidelines are painted 0.89 m either side of middle stump. A ball you don't touch is a wide if it passes outside the guideline, down the leg side without hitting you, or over head height. It's 1 run and the ball is bowled again. Step across toward it (A / D) and it has to be further out to count as a wide. If you get bat on it, it's a legal ball.
- **No balls and free hits.** Sometimes the bowler's front foot lands over the popping crease. A red NO BALL badge appears the moment he lets go and the far crease turns red, so you know you can't be out and can swing freely. You get 1 run plus whatever you hit, the ball is bowled again, and that ball is a **free hit**: you can't be bowled, caught or LBW, and the captain can't change the field. A wide doesn't use up the free hit.
- **Bat on ball is a real collision.** The bat has a mass and a swing speed, the ball bounces off the face with a coefficient of restitution, and friction on the face puts spin on it. So:
  - faster bowling comes off the bat faster, and glances and late cuts use the bowler's pace;
  - the sweet spot matters: hit it off the toe or the splice and the ball comes off slower and lower;
  - the ball meeting the side of the blade is an edge, and its direction comes from the geometry, which is why outside edges fly to the slips and inside edges can go on to the stumps (played on);
  - a horizontal bat to a ball that bounces higher than expected gives a top edge;
  - lofted shots get backspin and carry further (Magnus lift), and drives with topspin kick on after they land;
  - timing turns the face: early goes to the leg side, late to the off side, and late on a drive sends it up.
- Your timing against the ball's arrival sets how cleanly you middle it.
- Fielders work out whether they can reach the ball in time to catch it, stop it, or chase it to the rope. Harder-hit balls are harder to stop, and sharp chances at slip or back at the bowler go down more often than skiers.
- **Dynamic fields.** There are 11 players: a keeper, the bowler and nine named fielders. The captain sets a field for pace or spin and for the situation: attacking with slips and close catchers after a wicket or when little is needed, boundary riders when you need a lot, a ring field to save the single, and a short-ball trap for bouncer overs. After you find a gap more than once, he moves someone there. No more than five fielders stand outside the 30-yard circle, which is marked on the grass.
- Fielders walk in with the bowler and jog to their new positions when the field changes. A field map in the corner shows where everyone is and where your last shot went.
- Low catches are taken crouching with hands together, high ones with the hands up. A dropped catch pops out of the hands, falls, and is picked up and thrown back.
- The ball collides with the batsman's animated pads, thighs, body and helmet and rebounds. LBW is decided like ball tracking: where it pitched, whether the impact was in line (or outside off with no shot offered), and whether it would have gone on to hit the stumps.
- Balls you leave or miss carry through to the keeper's gloves.
- **A living crowd.** The stands are drawn seat by seat in team colours. The crowd jumps with excitement, does a Mexican wave after a six, and fills with camera flashes on big moments, while flags wave along the front rows.
- **Stadium sound, all synthesised in the browser with no audio files.** A murmuring crowd builds as the bowler runs in and hushes at the moment of delivery. It oohs at a play-and-miss, rises as a skier hangs in the air, groans at a dropped catch and roars for sixes and wickets, with applause, whistles, dhol drums and horns. The bat sounds different off the middle, the toe and the edge, and there are footsteps, bounces, pads, helmet knocks, stumps and gloves. Use the Sound button to mute.
- **Built for phones.** The timing meter is a slim vertical gauge on the left edge. On touch screens the view is framed in the space above the controls, and the keeper and slips fade while they stand in front of the lens.
- The batsmen run between the wickets, and fielders pick up and throw back.
- A perfectly timed shot gets a short hit-stop, a slow-motion moment and camera shake. On Club level the spot where the ball will pitch is shown as it is bowled.
- All input goes through `requestShot(direction)` and `setGuard(position)`, so new controllers can plug in without touching game logic.

## Modes

- **Daily challenge.** A new chase every day at midnight, and everyone in the world faces the same deliveries. The day's date seeds the random number generator, so every ball's line, length, pace, swing and spin, each over's bowler and the captain's plan come out identically on every device. The level is fixed at Pro. Only your first go counts: it's saved with your winning streak, and later goes are practice. **Share result** copies (or on a phone, shares) your score and a ball-by-ball line like `4 1 . 6 W 2 | 4 wd 1 nb4 6 .` (`wd` is a wide, `nb4` a no ball you hit for four). A wide or no ball is bowled again from the same seed, so everyone who got one faces the same extra ball too.
- **Chase 36** off 2 overs with 3 wickets.
- **Random chase.** A random target (6 to 24 balls, 1 to 3 wickets, and a bowling attack of pace, spin, mixed or death bowling) with a replay code. Replay the same code, or give it to a friend, and you both face the same balls.
- **Super Over.** Six balls, two wickets, against a death-bowling attack of yorkers, bouncers and slower balls, with the field back. The opposition's score is set first; tie it and you go to another Super Over.
- **Free nets** with no target.
- Three bowling levels: Club, Pro, International
- Right- or left-handed batting

Your daily results, streak and wins in each mode are kept in the browser (`localStorage`).

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
