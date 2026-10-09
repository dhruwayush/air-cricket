---
name: player-animation
description: Add or change Air Cricket player animations, from the Blender script (tools/players.py) to playing them in three.js (src/game.html). Use when adding a new shot, fielding move or bowling action, tweaking a pose, fixing a clip that looks wrong or mistimed, or changing the player models. Covers the pose helpers, the fixed contact frame rule, previews, export, and how the game plays clips with three.js r128.
---

# Player animation

Players are built, rigged and animated in code by `tools/players.py` (Blender as a Python module), exported as `tools/build/batsman.glb` and `fielder.glb`, embedded into the page by `tools/build_page.py`, and played in `src/game.html` with three.js **r128**'s `GLTFLoader`, `SkeletonUtils` and `AnimationMixer`. Nothing is hand-keyed in the Blender UI. Every pose is data in `players.py`.

If you use the three.js skill, translate its examples to r128: `THREE.GLTFLoader` / `THREE.SkeletonUtils` are globals from `examples/js/`, not imports from `three/addons/`.

## The rules that keep the game in sync

1. **Every batting shot meets the ball at `CONTACT = 5 / FPS`** (0.167 s at 30 fps). The game assumes this as `CLIP_CONTACT = 5 / 30` in `src/game.html` and sets the clip's playback speed so that frame lands exactly when the ball arrives (`playShot()`: `speed = CLIP_CONTACT / sw.cd`). A shot whose bat reaches the ball at any other time looks early or late however well the player times it. Build batting shots with `shot(...)` so contact sits on that key.
2. **The bowler lets go at `RELEASE = 0.55` s** into `"bowl"`, mirrored as `CLIP_RELEASE` in the game. The run-up and the ball's release point are timed from it.
3. **The keeper takes the ball at 0.3 s** into `"gather"`.
4. If you ever change one of these numbers, change it on **both** sides (`players.py` and `src/game.html`) in the same commit.
5. **Clip names are the contract.** The dict key in `BATSMAN_CLIPS` / `FIELDER_CLIPS` becomes the glTF animation name, and the game looks it up by that string (`actor.play('pull')`, `SHOTS[...].clip`). Renaming one side breaks the other silently: `clipAction(undefined)` throws when that clip is first played.
6. **Poses change gameplay too.** The ball collides with capsules between the striker's animated bones (`BODY_PARTS` in `src/game.html`: pads, thighs, body, `head`/`neck`), so moving the legs or head in a clip changes what hits the pads and what's LBW. `handPos()` reads `hand.R` / `hand.L` for where fielders hold the ball. Don't rename bones.

## Coordinates and pose helpers (`tools/players.py`)

Blender frame: the character faces −Y, its left (`.L`) is +X, up is +Z. For the batsman the **bowler is at +X**, the **off side is −Y** and the stumps are behind at −X (a right-hander; left-handers are the same clips mirrored in the game with `mirror.scale.x = -1`).

**Batsman** poses are IK targets, built with `P(base=None, **overrides)` on top of `BAT_BASE`:

| Key | Value |
| --- | --- |
| `bat` | `((x, y, z) grip-top position, (rx, ry, rz) bat rotation)`. The hands follow the grip. |
| `footL`, `footR` | `((x, y, z) toe position, yaw)` |
| `kneeL/R`, `elbowL/R` | `(x, y, z)` pole targets that set which way the joint bends |
| `hips` | `((dx, dy, dz) offset, (rx, ry, rz) rotation)` |
| `spine`, `chest`, `neck`, `head` | `(rx, ry, rz)` |

Reuse the shared body shapes (`FRONT`, `THRU`, `BACKFOOT`, `BACKLIFT`, `SWEEP_BODY`, `SCOOP_BODY`…) with `**dict(FRONT, head=...)` rather than writing every joint again.

**Fielder** poses are plain FK, built with `F(base=None, **overrides)` on top of `F_BASE`: `hips`, `spine`, `chest`, `neck`, `head`, upper arms `uaL/uaR = (forward, out)`, forearms `faL/faR`, hands `hL/hR`, thighs `thL/thR = (forward, out)`, shins `shL/shR`, feet `ftL/ftR` (angles in radians).

**A clip** is a list of `(time_seconds, pose)` keys. A batting shot uses:

```python
"my_shot": shot(contact_pose, follow_pose, hold_pose_or_None, extra=[(t, pose), ...]),
# keys: 0.0 backlift -> CONTACT contact -> 0.45 follow -> 0.9 hold -> 1.4 back to BAT_BASE
```

Add new batting clips in the `BATSMAN_CLIPS.update({...})` block and fielding ones in `FIELDER_CLIPS`. `author()` lays every clip out on one timeline, `bake_and_split()` bakes them into one NLA track per clip, and the export keeps only rotations (plus location on `hips` and `bat`). Root motion and scale are dropped, so the game moves players by moving `actor.root`.

## Workflow

```sh
pip install bpy==4.2.0                     # Blender as a module, Python 3.11 only

# 1. preview while posing: contact sheets in tools/preview/<kind>_<clip>.png (seconds into each clip)
python3 tools/players.py bat my_shot,pull 0,0.167,0.45,0.9    # batsman: game camera + side-on views
python3 tools/players.py field throw 0,0.2,0.38,0.65          # fielder
python3 tools/players.py field keep 0,0.5 --gear              # include the keeper's pads and gauntlets

# 2. export both models (bakes ambient occlusion with Cycles; slow)
python3 tools/players.py                   # -> tools/build/batsman.glb, fielder.glb, prints the clip names

# 3. embed into the page
python3 tools/build_page.py                # -> index.html
```

**Always look at the preview at the contact time (0.167)** for a batting shot. The bat face should be at the ball's height and position for that shot's line and length, square to where the shot goes. `tools/preview/` is git-ignored, so show the user the images instead of committing them.

Commit `tools/players.py`, both `.glb` files and the rebuilt `index.html` together. Check the `.glb` sizes before and after (`ls -la tools/build`: about 1.7 MB batsman, 1.0 MB fielder in October 2026). They're embedded as base64 into the page, so every extra MB is about 1.33 MB more for players to download.

## Using a new clip in the game (`src/game.html`)

- `Actor` wraps one cloned model (`THREE.SkeletonUtils.clone`, which keeps the skeleton separate per player) and one `THREE.AnimationMixer`. Play a clip with:

  ```js
  actor.play('name', { loop, speed, fade, from, restart });
  // loop: LoopRepeat instead of LoopOnce (one-shot clips clamp on their last frame)
  // fade: cross-fade seconds from the current clip (default 0.15; 0 = cut)
  // from: start time in seconds; speed: timeScale; restart: replay even if it's already playing
  ```

  `actor.done` is true once a one-shot clip reaches its end. `actor.t` is the current time.
- **A new batting shot:** add the clip in `players.py`, then add or point an entry in the `SHOTS` table at it (`clip: 'my_shot'`, with its direction `az`, elevation `el`, speed, and `lo`/`hi`, the range of ball heights in metres at the bat that the shot can reach). `playShot()` handles the timing. Don't call `play()` for shots yourself.
- **A new fielding move:** call `a.play(...)` from the fielding logic where the decision is made (see how `dive`, `pickup` and `throw` are chosen), and set `f.anim` if that code tracks it.
- Keep cross-fades short around contact and catches (0.03–0.1 s) so the key frame isn't blended away.

## Checking it in the game

Serve the repo (`python3 -m http.server 8123`), open `index.html` in Playwright/Chromium (launch with `--use-angle=swiftshader --enable-unsafe-swiftshader`), start a match with `#btn-start` and trigger the move with the keys from the README (for example `ArrowLeft` for square shots). Then check:

- no console errors (a missing clip name shows up here),
- the bat meets the ball for the new shot at good timing, and the ball goes where the `SHOTS` entry says,
- right- **and** left-handed (the menu's "You bat" option) both look right,
- `.claude/skills/mobile-performance/measure.mjs` shows no change in draw calls (a new clip should add none; new mesh parts on the players would).
