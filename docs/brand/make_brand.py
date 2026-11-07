"""Cut the supplied LogiTrack logo into web assets. Uses only the original pixels:

* icon      - the cyan rounded square with the truck, corners made transparent
* full      - icon + "LogiTrack" + "Operations Portal", original layout
* compact   - icon + "LogiTrack", name centred on the icon at the original scale
* on-light  - original navy / slate lettering
* on-dark   - the same letter shapes in white (subtitle at 80 % opacity)

Lettering is extracted as an alpha mask from its contrast with the flat background, so the
letter shapes, weight and spacing are exactly those of the supplied artwork.

Rebuild (needs Pillow, which the backend environment has):

    cd backend && uv run python ../docs/brand/make_brand.py ../docs/brand/logitrack-logo.png \
        ../frontend/src/assets/brand ../frontend/public /tmp/logitrack-brand-proof.png
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw

SRC, OUT, PUBLIC = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
OUT.mkdir(parents=True, exist_ok=True)
im = Image.open(SRC).convert("RGB")

ICON = (83, 349, 486, 748)  # measured: cyan rounded square, 403 x 399
RADIUS = 88
NAME = (544, 396, 1373, 591)  # "LogiTrack" incl. the g descender
SUB = (544, 591, 1304, 687)  # "Operations Portal" incl. the p descender
GAP = NAME[0] - ICON[2]  # original icon-to-text gap (58 px)
NAVY, SLATE = (2, 34, 63), (58, 80, 103)
BG = (250, 251, 252)


def icon() -> Image.Image:
    crop = im.crop(ICON).convert("RGBA")
    w, h = crop.size
    s = 4  # supersampled, anti-aliased rounded-rectangle mask, inset to drop the light fringe
    inset = 2.6  # px: removes the anti-aliased light fringe of the white backdrop
    mask = Image.new("L", (w * s, h * s), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (inset * s, inset * s, (w - inset) * s, (h - inset) * s), radius=(RADIUS - inset) * s, fill=255
    )
    crop.putalpha(mask.resize((w, h), Image.LANCZOS))
    # The artwork is 403 x 399: centre it on a transparent square instead of stretching it.
    side = max(w, h)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.alpha_composite(crop, ((side - w) // 2, (side - h) // 2))
    return square


def text_mask(box: tuple[int, int, int, int], ink: tuple[int, int, int]) -> Image.Image:
    """Coverage 0..1 of the lettering: how far each pixel moved from background to ink."""
    crop = im.crop(box)
    lum = crop.convert("L")
    bg_l = sum(BG) / 3
    ink_l = 0.299 * ink[0] + 0.587 * ink[1] + 0.114 * ink[2]
    scale = 255 / (bg_l - ink_l)
    return lum.point(lambda v: max(0, min(255, round((bg_l - v) * scale))))


def colour(mask: Image.Image, rgb: tuple[int, int, int], opacity: float = 1.0) -> Image.Image:
    layer = Image.new("RGBA", mask.size, (*rgb, 0))
    alpha = mask if opacity == 1 else mask.point(lambda v: round(v * opacity))
    layer.putalpha(alpha)
    return layer


ic = icon()
name_m, sub_m = text_mask(NAME, NAVY), text_mask(SUB, SLATE)
TONES = {
    "on-light": ((NAVY, 1.0), (SLATE, 1.0)),
    "on-dark": (((255, 255, 255), 1.0), ((255, 255, 255), 0.8)),
}


def compose(tone: str, with_sub: bool) -> Image.Image:
    (n_rgb, n_op), (s_rgb, s_op) = TONES[tone]
    iw, ih = ic.size
    if with_sub:  # exact original geometry
        w = max(NAME[2], SUB[2]) - ICON[0]
        canvas = Image.new("RGBA", (w, ih), (0, 0, 0, 0))
        canvas.alpha_composite(ic, (0, 0))
        canvas.alpha_composite(colour(name_m, n_rgb, n_op), (NAME[0] - ICON[0], NAME[1] - ICON[1]))
        canvas.alpha_composite(colour(sub_m, s_rgb, s_op), (SUB[0] - ICON[0], SUB[1] - ICON[1]))
    else:  # icon + name, name centred vertically on the icon, original scale and gap
        w = iw + GAP + name_m.size[0]
        canvas = Image.new("RGBA", (w, ih), (0, 0, 0, 0))
        canvas.alpha_composite(ic, (0, 0))
        y = (ih - name_m.size[1]) // 2 + 14  # optical centre: the g descender hangs below
        canvas.alpha_composite(colour(name_m, n_rgb, n_op), (iw + GAP, y))
    return canvas


def save(img: Image.Image, path: Path, height: int) -> None:
    w = round(img.size[0] * height / img.size[1])
    out = img.resize((w, height), Image.LANCZOS)
    if path.suffix == ".webp":
        # High-quality lossy colour, exact alpha: invisible at display size, a fraction of the bytes.
        out.save(path, quality=92, alpha_quality=100, method=6)
    else:
        out.save(path, optimize=True)
    print(f"{path.name:32} {w}x{height}  {path.stat().st_size / 1024:.1f} KB")


# In-app assets: ~3x the largest display height, so they stay sharp on high-density screens.
save(ic, OUT / "logitrack-icon.webp", 192)
for tone in TONES:
    save(compose(tone, True), OUT / f"logitrack-full-{tone}.webp", 216)
    save(compose(tone, False), OUT / f"logitrack-compact-{tone}.webp", 144)

# Browser and home-screen icons.
save(ic, PUBLIC / "favicon-32.png", 32)
save(ic, PUBLIC / "favicon-64.png", 64)
# iOS rounds home-screen icons itself and shows transparent corners as black: fill them
# with the icon's own lower-edge cyan so the square reads as one shape.
touch = Image.new("RGBA", ic.size, (*im.getpixel((ICON[0] + 200, ICON[3] - 6)), 255))
touch.alpha_composite(ic)
save(touch, PUBLIC / "apple-touch-icon.png", 180)
save(ic, PUBLIC / "icon-192.png", 192)

# Quick visual proof on both backgrounds.
proof = Image.new("RGBA", (1400, 760), (255, 255, 255, 255))
d = ImageDraw.Draw(proof)
d.rectangle((0, 380, 1400, 760), fill=(8, 39, 54, 255))
for i, tone in enumerate(("on-light", "on-dark")):
    full = Image.open(OUT / f"logitrack-full-{tone}.webp")
    comp = Image.open(OUT / f"logitrack-compact-{tone}.webp")
    proof.alpha_composite(full, (40, 30 + 380 * i))
    proof.alpha_composite(comp, (800, 200 + 380 * i))
    proof.alpha_composite(Image.open(OUT / "logitrack-icon.webp").resize((64, 64), Image.LANCZOS), (1100, 60 + 380 * i))
    proof.alpha_composite(Image.open(PUBLIC / "favicon-32.png"), (1200, 76 + 380 * i))
proof.convert("RGB").save(Path(sys.argv[4]))
print("proof", sys.argv[4])
