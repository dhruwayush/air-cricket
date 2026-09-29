"""
Build the playable pages from src/game.html.

  python3 tools/build_page.py [extra-output.html ...]

Embeds tools/build/batsman.glb and fielder.glb as base64 so the game stays a
single file, and writes index.html (a full standalone page for GitHub Pages or
opening from disk). Any extra paths get the same page without the
<html>/<head> wrapper (for hosts that add their own).
"""
import base64
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    src = open(os.path.join(ROOT, "src", "game.html"), encoding="utf-8").read()
    assets = {}
    for k in ("batsman", "fielder"):
        with open(os.path.join(ROOT, "tools", "build", k + ".glb"), "rb") as f:
            assets[k] = base64.b64encode(f.read()).decode("ascii")
    tag = "<script>window.AC_ASSETS={" + ",".join(f'{k}:"{v}"' for k, v in assets.items()) + "};</script>"
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
