"""Генерация иконок приложения (запускать из корня проекта)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "ymrpc" / "assets"

BACKGROUND_TOP = (27, 30, 38, 255)
BACKGROUND_BOTTOM = (14, 16, 20, 255)
BORDER = (58, 63, 76, 255)
ACCENT = (255, 204, 0, 255)


def _gradient(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size))
    pixels = image.load()
    for y in range(size):
        ratio = y / max(1, size - 1)
        color = tuple(
            int(BACKGROUND_TOP[index] + (BACKGROUND_BOTTOM[index] - BACKGROUND_TOP[index]) * ratio)
            for index in range(4)
        )
        for x in range(size):
            pixels[x, y] = color
    return image


def build(size: int = 2048) -> Image.Image:
    scale = size / 1024
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=int(230 * scale), fill=255
    )
    image.alpha_composite(Image.composite(_gradient(size), Image.new("RGBA", (size, size)), mask))

    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (int(14 * scale), int(14 * scale), size - int(14 * scale), size - int(14 * scale)),
        radius=int(216 * scale),
        outline=BORDER,
        width=max(2, int(10 * scale)),
    )

    # Пара нот: перекладина, ножки и головки.
    draw.rounded_rectangle(
        (int(418 * scale), int(292 * scale), int(798 * scale), int(366 * scale)),
        radius=int(18 * scale),
        fill=ACCENT,
    )
    draw.rounded_rectangle(
        (int(430 * scale), int(320 * scale), int(484 * scale), int(726 * scale)),
        radius=int(24 * scale),
        fill=ACCENT,
    )
    draw.rounded_rectangle(
        (int(732 * scale), int(320 * scale), int(786 * scale), int(652 * scale)),
        radius=int(24 * scale),
        fill=ACCENT,
    )
    draw.ellipse(
        (int(318 * scale), int(640 * scale), int(512 * scale), int(796 * scale)),
        fill=ACCENT,
    )
    draw.ellipse(
        (int(620 * scale), int(566 * scale), int(814 * scale), int(722 * scale)),
        fill=ACCENT,
    )
    draw.ellipse(
        (int(368 * scale), int(676 * scale), int(462 * scale), int(750 * scale)),
        fill=BACKGROUND_BOTTOM,
    )
    draw.ellipse(
        (int(670 * scale), int(602 * scale), int(764 * scale), int(676 * scale)),
        fill=BACKGROUND_BOTTOM,
    )

    # Маленький треугольник «play» в правом нижнем углу.
    draw.ellipse(
        (int(704 * scale), int(704 * scale), int(936 * scale), int(936 * scale)),
        fill=BACKGROUND_TOP,
        outline=ACCENT,
        width=max(2, int(14 * scale)),
    )
    draw.polygon(
        [
            (int(806 * scale), int(758 * scale)),
            (int(806 * scale), int(882 * scale)),
            (int(902 * scale), int(820 * scale)),
        ],
        fill=ACCENT,
    )
    return image


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    master = build()
    master.resize((1024, 1024), Image.Resampling.LANCZOS).save(ASSETS / "icon.png")
    master.resize((256, 256), Image.Resampling.LANCZOS).save(
        ASSETS / "icon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Готово: {ASSETS / 'icon.png'}, {ASSETS / 'icon.ico'}")


if __name__ == "__main__":
    main()
