"""Generate LaunchFlow's Windows ICO from the existing workbench logo motif."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_ROOT / "assets" / "launchflow.ico"


def _interpolate(start: tuple[int, int, int], end: tuple[int, int, int], ratio: float) -> tuple[int, int, int, int]:
    return tuple(round(a + (b - a) * ratio) for a, b in zip(start, end)) + (255,)


def build_icon_canvas(size: int = 1024) -> Image.Image:
    """Render the blue workflow-grid and green run-arrow logo at high resolution."""
    scale = size / 128
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    outer_box = tuple(round(value * scale) for value in (10, 10, 118, 118))
    for y in range(outer_box[1], outer_box[3]):
        ratio = (y - outer_box[1]) / max(1, outer_box[3] - outer_box[1] - 1)
        draw.rounded_rectangle(
            (outer_box[0], y, outer_box[2], outer_box[3]),
            radius=round(26 * scale),
            fill=_interpolate((96, 165, 250), (37, 99, 235), ratio),
        )

    panel = tuple(round(value * scale) for value in (24, 24, 104, 104))
    draw.rounded_rectangle(panel, radius=round(18 * scale), fill="#F8FAFC", outline="#D6E4FF", width=max(1, round(2 * scale)))
    draw.rectangle(tuple(round(value * scale) for value in (34, 34, 94, 44)), fill="#DBEAFE")

    colors = ["#60A5FA", "#93C5FD", "#BFDBFE", "#A78BFA", "#C4B5FD", "#DDD6FE"]
    positions = [(36, 52), (56, 52), (76, 52), (36, 70), (56, 70), (76, 70)]
    block = round(12 * scale)
    for (x, y), color in zip(positions, colors):
        left, top = round(x * scale), round(y * scale)
        draw.rectangle((left, top, left + block, top + block), fill=color)

    draw.polygon(
        [
            (round(56 * scale), round(92 * scale)),
            (round(56 * scale), round(104 * scale)),
            (round(70 * scale), round(98 * scale)),
        ],
        fill="#10B981",
    )
    return image


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    canvas = build_icon_canvas()
    canvas.save(
        OUTPUT_PATH,
        format="ICO",
        sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"generated={OUTPUT_PATH}")


if __name__ == "__main__":
    main()
