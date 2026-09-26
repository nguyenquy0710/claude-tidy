"""Generates the app icon assets under claude_tidy/webui/static/.

Drawn procedurally with Pillow (no SVG toolchain / extra dependency needed
just to ship a static asset) — a broom sweeping dust, with sparkles for
balance, on the app's accent-blue rounded tile (colors sampled from
claude_tidy/webui/static/app.css's --ct-accent design token).

Small sizes (16/32) use a simplified silhouette — the bristle notches, dust
trail and sparkles turn to noise below ~48px, so they're dropped rather than
left to blur.

Re-run after changing the design: .venv/Scripts/python .bin/gen_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

STATIC_DIR = Path(__file__).resolve().parent.parent / "claude_tidy" / "webui" / "static"

RENDER_SIZE = 1024
ACCENT = (31, 111, 197, 255)       # --ct-accent
ACCENT_DARK = (18, 74, 135, 255)   # ferrule shade
WHITE = (255, 255, 255, 255)


def _rounded_square(size: int, radius_ratio: float, fill: tuple[int, int, int, int]) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=int(size * radius_ratio), fill=fill
    )
    return img


def _sparkle(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, alpha: int) -> None:
    fill = (255, 255, 255, alpha)
    d.polygon([(cx, cy - r), (cx + r * 0.28, cy), (cx, cy + r), (cx - r * 0.28, cy)], fill=fill)
    d.polygon([(cx - r, cy), (cx, cy + r * 0.28), (cx + r, cy), (cx, cy - r * 0.28)], fill=fill)


def _broom_layer(size: int, *, detailed: bool) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = size // 2

    d.rounded_rectangle([cx - 34, 70, cx + 34, 620], radius=30, fill=WHITE)
    d.rounded_rectangle([cx - 158, 592, cx + 158, 646], radius=15, fill=ACCENT_DARK)
    d.polygon(
        [(cx - 84, 622), (cx + 84, 622), (cx + 164, 850), (cx - 164, 850)],
        fill=WHITE,
    )

    if not detailed:
        return img

    # Bristle notches cut into the bottom edge — only worth it at 48px+.
    bottom_y = 850
    left_x, right_x = cx - 164, cx + 164
    n = 6
    step = (right_x - left_x) / n
    notch_h = 38
    for i in range(n):
        x0 = left_x + i * step
        x1 = x0 + step
        mid = (x0 + x1) / 2
        d.polygon([(x0, bottom_y), (mid, bottom_y - notch_h), (x1, bottom_y)], fill=(0, 0, 0, 0))

    for dx, dy, r, alpha in [(90, 20, 28, 235), (155, 60, 19, 175), (205, 100, 12, 120)]:
        x, y = cx + 164 + dx, 850 + dy
        d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, alpha))

    _sparkle(d, cx - 195, 190, 46, 230)
    _sparkle(d, cx - 115, 300, 24, 160)
    return img


def render(size: int, *, detailed: bool) -> Image.Image:
    bg = _rounded_square(RENDER_SIZE, 0.22, ACCENT)
    broom = _broom_layer(RENDER_SIZE, detailed=detailed).rotate(
        -16, resample=Image.BICUBIC, center=(RENDER_SIZE / 2, RENDER_SIZE / 2)
    )
    bg.alpha_composite(broom)
    return bg.resize((size, size), Image.LANCZOS)


def main() -> None:
    master = render(512, detailed=True)
    master.save(STATIC_DIR / "icon.png")

    ico_sizes = [16, 32, 48, 64, 128, 256]
    frames = [render(s, detailed=s >= 48) for s in ico_sizes]
    frames[-1].save(
        STATIC_DIR / "icon.ico",
        sizes=[(s, s) for s in ico_sizes],
        append_images=frames[:-1],
    )
    print(f"wrote {STATIC_DIR / 'icon.png'} and {STATIC_DIR / 'icon.ico'}")


if __name__ == "__main__":
    main()
