"""
Build the playable pages from src/game.html.

  python3 tools/build_page.py [extra-output.html ...]

Embeds tools/build/batsman.glb and fielder.glb as base64 so the game stays a
single file, and writes index.html (a full standalone page for GitHub Pages or
opening from disk). Any extra paths get the same page without the
<html>/<head> wrapper (for hosts that add their own).
"""
import base64
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def voice_tag():
    """Commentary: the text of every line (tools/voice_lines.py), plus any recorded clips found in
    sounds/voice/<group>/<id>.mp3, embedded as base64. Lines without a clip use the device's speech voice."""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    from voice_lines import LINES
    clips, n = {}, 0
    for group, lines in LINES.items():
        for line_id in lines:
            f = os.path.join(ROOT, "sounds", "voice", group, line_id + ".mp3")
            if os.path.exists(f) and os.path.getsize(f) > 0:
                clips.setdefault(group, {})[line_id] = base64.b64encode(open(f, "rb").read()).decode("ascii")
                n += 1
    print("commentary clips embedded:", n, "of", sum(len(v) for v in LINES.values()))
    return ("<script>window.AC_LINES=" + json.dumps(LINES, ensure_ascii=False, separators=(",", ":")) +
            ";window.AC_VOICE=" + json.dumps(clips, separators=(",", ":")) + ";</script>")


def main():
    src = open(os.path.join(ROOT, "src", "game.html"), encoding="utf-8").read()
    assets = {}
    for k in ("batsman", "fielder"):
        with open(os.path.join(ROOT, "tools", "build", k + ".glb"), "rb") as f:
            assets[k] = base64.b64encode(f.read()).decode("ascii")
    tag = "<script>window.AC_ASSETS={" + ",".join(f'{k}:"{v}"' for k, v in assets.items()) + "};</script>"
    tag += voice_tag()
    assert "<!--ASSETS-->" in src
    body = src.replace("<!--ASSETS-->", tag, 1)

    marker = '<div id="stage"></div>'
    full = ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
            + body.replace(marker, "</head>\n<body>\n" + marker, 1) + "\n</body>\n</html>\n")
    with open(os.path.join(ROOT, "index.html"), "w", encoding="utf-8") as f:
        f.write(full)
    for extra in sys.argv[1:]:
        with open(extra, "w", encoding="utf-8") as f:
            f.write(full if extra.endswith("-camera.html") else body)
    print("index.html", len(full) // 1024, "KB")


if __name__ == "__main__":
    main()
