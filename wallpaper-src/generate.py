#!/usr/bin/env python3
"""Sticker-bomb "Omarchy" wallpaper in the Dracula palette.

Usage: generate.py [--dark] [seed] [out.png]
  --dark  fewer, bigger stickers with thick dark slabs and neon edges
Requires ImageMagick 7 (`magick`). Fonts live in ./fonts.
"""
import os
import random
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
FONTS = sorted((HERE / "fonts").glob("*.ttf"))
W, H = 3840, 2160
WORD = "Omarchy"

BG = "#282a36"
DARK = "#191a21"
WHITE = "#f8f8f2"
SELECTION = "#44475a"
COLORS = ["#bd93f9", "#50fa7b", "#ff79c6", "#f1fa8c", "#ff5555", "#8be9fd"]

# Gap filling: the canvas is sampled on a CELL px grid; a cell counts as bare
# when more than BARE of it is darker than LUMA (background or shadow).
CELL, LUMA, BARE, FILL_PASSES = 60, "20%", 0.45, 6

args = sys.argv[1:]
DARK_MODE = "--dark" in args
args = [a for a in args if a != "--dark"]
seed = int(args[0]) if args else 1897  # year Dracula was published
default_out = "2-sticker-bomb-dark.png" if DARK_MODE else "1-sticker-bomb.png"
out = Path(args[1]) if len(args) > 1 else HERE.parent / "backgrounds" / default_out
# Dark variant: rings drawn this much thicker, and sticker size ranges for the
# base layer and the gap fill.
THICK = 1.7 if DARK_MODE else 1.0
BASE_W, FILL_W = ((1100, 2100), (800, 1300)) if DARK_MODE else ((480, 1250), (420, 850))
rng = random.Random(seed)
# One ImageMagick thread per process; parallelism comes from rendering stickers concurrently.
ENV = {**os.environ, "MAGICK_THREAD_LIMIT": "1"}


def magick(*args, raw=False):
    r = subprocess.run(["magick", *map(str, args)], check=True, capture_output=True, env=ENV)
    return r.stdout if raw else r.stdout.decode()


def text_width(font, pointsize=100):
    return int(magick("-background", "none", "-font", font, "-pointsize", pointsize, f"label:{WORD}", "-format", "%w", "info:"))


def style():
    """Pick text fill, optional glyph stroke, and halo rings (inner → outer)."""
    c, c2 = rng.sample(COLORS, 2)
    if DARK_MODE:
        return rng.choice([
            (c, None, [(22, DARK), (8, c)]),             # neon text on a black slab
            (c, None, [(24, BG), (6, DARK), (6, c2)]),   # neon text, two-tone edge
            (DARK, c, [(22, BG), (8, c)]),               # outlined black letters
            (WHITE, None, [(22, SELECTION), (8, DARK), (6, c)]),  # light text on grey slab
            (c, DARK, [(20, DARK), (10, SELECTION)]),    # neon with grey keyline
        ])
    return rng.choice([
        (c, None, [(14, WHITE)]),                    # classic die-cut
        (c, None, [(10, DARK), (10, WHITE)]),        # die-cut with dark keyline
        (BG, None, [(26, c), (12, WHITE)]),          # dark text on color blob
        (WHITE, None, [(24, c), (10, DARK)]),        # light text on color blob
        (c, None, [(20, DARK), (10, c2)]),           # neon on black
        (c, c2, [(16, BG), (10, WHITE)]),            # two-tone lettering
        (DARK, c, [(18, c2), (10, WHITE)]),          # outlined letters on color
    ])


def sticker_spec(width, cx, cy):
    """Draw every random choice up front so parallel rendering stays reproducible."""
    font = rng.choice(FONTS)
    fill, stroke, rings = style()
    return dict(font=font, width=width, fill=fill, stroke=stroke, rings=rings,
                angle=rng.uniform(-28, 28), cx=cx, cy=cy)


def render(spec, path):
    scale = spec["width"] / 900  # ring sizes are tuned for a ~900 px sticker
    rings = [(max(3, round(r * scale * THICK)), col) for r, col in spec["rings"]]
    pad = sum(r for r, _ in rings) + 40
    pointsize = 100 * spec["width"] / widths[spec["font"]]

    cmd = ["-background", "none", "-font", spec["font"], "-pointsize", f"{pointsize:.1f}", "-fill", spec["fill"]]
    if spec["stroke"]:
        cmd += ["-stroke", spec["stroke"], "-strokewidth", max(2, round(4 * scale))]
    cmd += [f"label:{WORD}", "-bordercolor", "none", "-border", pad]
    for i, (r, col) in enumerate(rings):
        src = ["-clone", "0", "-alpha", "extract"] if i == 0 else [f"mpr:m{i - 1}"]
        # Grow the previous mask by r px with a distance transform (100 units per px);
        # unlike Dilate Disk:r, its cost doesn't grow with the radius.
        cmd += ["(", *src, "-threshold", "50%", "-negate", "-morphology", "Distance", "Euclidean:4",
                "-level", f"{r * 100 - 50},{r * 100 + 50}", "-negate", "-write", f"mpr:m{i}",
                "-background", col, "-alpha", "shape", ")"]
    shadow = max(4, round(10 * scale))
    cmd += ["-reverse", "-background", "none", "-layers", "merge",
            "(", "+clone", "-background", "#08070c", "-shadow", f"65x{shadow}+{shadow}+{round(shadow * 1.4)}", ")",
            "+swap", "-background", "none", "-layers", "merge", "+repage",
            "-rotate", f"{spec['angle']:.1f}", "-trim", "+repage", path]
    magick(*cmd)
    w, h = map(int, magick(path, "-format", "%w %h", "info:").split())
    return ["-geometry", f"{spec['cx'] - w // 2:+d}{spec['cy'] - h // 2:+d}", "-composite"]


def paint(canvas, specs, tmp, tag):
    paths = [Path(tmp) / f"{tag}-{i:03d}.png" for i in range(len(specs))]
    with ThreadPoolExecutor(os.cpu_count()) as pool:
        geoms = list(pool.map(render, specs, paths))
    layers = [arg for p, g in zip(paths, geoms) for arg in (p, *g)]
    magick(canvas, *layers, canvas)


def bare_cells(canvas):
    """Cells sorted barest-first, as (bareness, x, y) pixel centers."""
    cols, rows = W // CELL, H // CELL
    data = magick(canvas, "-colorspace", "gray", "-threshold", LUMA, "-negate",
                  "-scale", f"{cols}x{rows}!", "-depth", "8", "gray:-", raw=True)
    cells = [(v / 255, (i % cols) * CELL + CELL // 2, (i // cols) * CELL + CELL // 2)
             for i, v in enumerate(data) if v / 255 > BARE]
    return sorted(cells, reverse=True)


widths = {f: text_width(f) for f in FONTS}

# Jittered, staggered grid so the whole canvas gets covered, then a random
# scatter on top for the layered sticker-bomb look.
centers = []
row_h, col_w = (360, 1150) if DARK_MODE else (215, 640)
for r, y in enumerate(range(-60, H + 120, row_h)):
    for x in range(-200 + (r % 2) * col_w // 2, W + 300, col_w):
        centers.append((x + rng.randint(-160, 160), y + rng.randint(-80, 80)))
rng.shuffle(centers)
centers += [(rng.randint(0, W), rng.randint(0, H)) for _ in range(len(centers) // 2)]

with tempfile.TemporaryDirectory() as tmp:
    canvas = Path(tmp) / "canvas.png"
    magick("-size", f"{W}x{H}", f"xc:{BG}", canvas)
    paint(canvas, [sticker_spec(rng.randint(*BASE_W), x, y) for x, y in centers], tmp, "base")
    total = len(centers)

    # Patch whatever is still bare with smaller stickers centered on the gaps.
    # (The dark variant skips this: its slabs are as dark as the background,
    # so the luminance test can't tell a gap from a sticker.)
    for n in range(0 if DARK_MODE else FILL_PASSES):
        picks = []
        for _, x, y in bare_cells(canvas):
            if all(abs(x - px) > 320 or abs(y - py) > 140 for px, py in picks):
                picks.append((x, y))
        print(f"fill pass {n + 1}: {len(picks)} gaps", flush=True)
        if not picks:
            break
        paint(canvas, [sticker_spec(rng.randint(*FILL_W), x + rng.randint(-40, 40), y + rng.randint(-20, 20))
                       for x, y in picks], tmp, f"fill{n}")
        total += len(picks)

    out.parent.mkdir(parents=True, exist_ok=True)
    magick(canvas, out)

print(f"{total} stickers → {out}")
