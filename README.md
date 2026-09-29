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

## How it works

- **Three.js** renders the ground, players and ball.
- Each delivery is simulated ahead of time with gravity, bounce, swing and spin.
- Your timing against the ball's arrival sets the power. Early timing pulls the ball to the leg side and late timing pushes it to the off side.
- Fielders work out whether they can reach the ball in time to catch it, stop it, or chase it to the rope.
- All input goes through `requestShot(direction)` and `setGuard(position)`, so new controllers can plug in without touching game logic.

## Modes

- **Chase 36 off 2 overs** with 3 wickets
- **Free nets**
- Three bowling levels: Club, Pro, International
- Right- or left-handed batting
