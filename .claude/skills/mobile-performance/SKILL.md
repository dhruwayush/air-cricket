---
name: mobile-performance
description: Keep Air Cricket running smoothly on phones. Use when adding or changing anything drawn by three.js in src/game.html (meshes, materials, lights, shadows, textures, shaders, the crowd, effects, players), when the game feels slow or Auto graphics drops to Fast, or before shipping a visual change. Covers measuring draw calls, triangles and shader programs, the High/Fast graphics levels, and the r128-specific rules.
---

# Mobile performance

Air Cricket is played mostly on phones, often in the Android app's WebView. Treat every new object, material and effect as a cost against a frame budget, and check the numbers before and after a change.

**three.js here is r128.** If you use the three.js skill or online examples, translate them to the r128 API (see "three.js is r128" in `CLAUDE.md`). Don't follow examples that use `outputColorSpace`, ES module imports or `three/addons/`.

## Measure first

`measure.mjs` (next to this file) opens the built game in headless Chromium at a phone viewport (412×915 at 2.6×, touch), starts a match, waits for the bowler to run in, and prints what the renderer drew in the last frame:

```sh
python3 tools/build_page.py                        # measure what you changed, not the old index.html
python3 -m http.server 8123 >/dev/null 2>&1 &
export NODE_PATH=$(npm root -g)                    # Playwright is installed globally
node .claude/skills/mobile-performance/measure.mjs http://localhost:8123/index.html high
node .claude/skills/mobile-performance/measure.mjs http://localhost:8123/index.html fast
```

The game runs inside a closure, so the script injects a hook after the three.js `<script>` tags that wraps `THREE.WebGLRenderer` and keeps the instance as `window.__renderer`. Use the same trick for any other probe. Don't add globals to the game for it.

**Baseline** (Chase 36, bowler running in, October 2026):

| Level | Draw calls | Triangles | Geometries | Textures | Shader programs | Pixel ratio | Shadows |
| --- | --- | --- | --- | --- | --- | --- | --- |
| High | 87 | ~156k | 62 | 58 | 21 | 2 | on |
| Fast | 87 | ~156k | 62 | 57 | 19 | 1.25 | off |

Notes on reading the numbers:

- In r128, `renderer.info` resets *after* the shadow pass, so the **draw calls exclude the shadow map**. Each shadow caster adds roughly one more draw per mesh on High.
- Swiftshader is a software renderer, so timings from headless Chromium mean nothing. Compare counts, not milliseconds. For real frame times, use Chrome remote debugging on an Android phone (`chrome://inspect`) with the APK or the Pages URL.
- Look at the screenshot it saves (`perf-high.png`) to be sure the scene was in play and not behind the menu.

Report the before and after numbers with any visual change. Rough budget on top of the baseline: **+10 draw calls, +30k triangles, +2 shader programs** per feature. Go over that only on purpose, with a Fast path.

## Where the cost is today

- **Pixels:** `renderer.setPixelRatio` is capped at 2 on High and 1.25 on Fast (`applyGfx()`). Fill rate is the biggest cost on phones, so never raise these caps.
- **Shadows:** one shadow-casting light (`key`, the floodlight behind the striker), 2048² PCF soft map, with its shadow camera fitted tightly round the pitch. Only players near the pitch get `castShadow` (`new Actor(kind, yaw, { shadow: true })`); everyone else gets a blob shadow plane. Fast turns shadows off.
- **Players:** `players.py` folds each player's materials into four finishes, so a player is a few draw calls. Players have `frustumCulled = false` (skinned meshes have stale bounds), so every player is drawn even when off screen. Fielders are made with `{ fade: true }` so the keeper and slips can fade when they stand in front of the lens. Each fielder gets its own material clones, which reuse the same shader programs.
- **Crowd:** the stands are one `ShaderMaterial` with a canvas texture of seats, animated in the vertex shader (bob, jump, the wave). Flashes are one `THREE.Points`. The crowd is one draw however big it looks, so keep it that way.
- **Textures:** all drawn on canvases with `canvasTex()`, with max anisotropy. A 2048×2048 canvas texture takes about 21 MB of GPU memory with mipmaps, so pick the smallest size that looks right.
- **Auto level:** `sampleGfx()` skips 30 frames, collects 180, and switches to Fast for good (saved in `localStorage` as `ac-gfx-auto`) if the median frame takes longer than 1/40 s. A change that makes High slower pushes more phones to Fast.

## Rules for new rendering work

1. **Give it a Fast path.** Anything costly (extra lights, shadows, post effects, dense geometry, big textures) must be switched or reduced in `applyGfx()` on the Fast level. After changing materials there, set `needsUpdate` (it already does so for the whole scene).
2. **Reuse materials.** Every distinct material *type and define combination* compiles a shader program, and each new program costs a hitch the first time it's drawn. Create materials once at load with `std()` / `basic()` and share them. Don't make a material per object or per frame.
3. **Batch repeated things.** For many copies of one mesh (boundary markers, stand rows, confetti), use `THREE.InstancedMesh` (r128 supports it; the 30-yard circle dots already use one) or one merged `BufferGeometry`. Don't add hundreds of `Mesh`es.
4. **Allocate nothing per frame.** Inside `tick()` and anything it calls, reuse module-level temporaries (`const _v2 = new THREE.Vector3()` and so on) instead of `new THREE.Vector3()`. Garbage-collection pauses show up as dropped frames on phones.
5. **Lights are expensive.** Every light is computed in every lit material's shader. Prefer baking into textures or vertex colours (as the players' ambient occlusion does), or an unlit `basic()` glow, over a new light.
6. **Keep shadow casters few.** Only add `castShadow` to things in the shadow camera's box near the pitch. Things outside it waste the shadow pass.
7. **Dispose what you replace.** If you rebuild geometry, textures or render targets at runtime, call `.dispose()` on the old ones. `info.memory` going up between balls means a leak.
8. **Mind transparency.** Transparent objects are sorted and drawn back to front, can't be batched and cause overdraw. Use `alphaTest` or opaque where you can, with `depthWrite: false` only when you must.

## Before you finish

- Run `measure.mjs` at `high` and `fast`, compare against the baseline, and include both tables in your summary.
- Confirm "errors: none" and check both screenshots.
- If a number went up, say why it's worth it, or cut it back.
- If you changed the baseline on purpose, update the table above.
