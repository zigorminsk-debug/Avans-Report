#!/usr/bin/env python3
"""Генерация иконки автономной версии (installer/windows/standalone.ico).

Запуск:  python installer/windows/make_icon.py
Требуется Pillow:  pip install pillow
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
SIZE = 1024
TEAL_TOP = (47, 158, 143)
TEAL_BOTTOM = (18, 88, 82)


def _gradient(size: int) -> Image.Image:
    image = Image.new("RGB", (size, size), TEAL_TOP)
    pixels = image.load()
    for y in range(size):
        ratio = y / max(1, size - 1)
        color = tuple(
            round(TEAL_TOP[i] + (TEAL_BOTTOM[i] - TEAL_TOP[i]) * ratio) for i in range(3)
        )
        for x in range(size):
            pixels[x, y] = color
    return image


def build() -> Image.Image:
    size = SIZE
    base = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gradient = _gradient(size).convert("RGBA")

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=int(size * 0.22), fill=255
    )
    base.paste(gradient, (0, 0), mask)
    draw = ImageDraw.Draw(base)

    # Лист документа
    left, top, right, bottom = 268, 214, 690, 780
    fold = 108
    page = [(left, top), (right - fold, top), (right, top + fold), (right, bottom), (left, bottom)]
    draw.polygon(page, fill=(255, 255, 255, 255))
    draw.polygon([(right - fold, top), (right, top + fold), (right - fold, top + fold)],
                 fill=(203, 224, 234, 255))

    # Строки текста
    line_color = (176, 199, 212, 255)
    for index, width in enumerate((260, 300, 236, 282)):
        y = top + 180 + index * 82
        draw.rounded_rectangle((left + 58, y, left + 58 + width, y + 24), radius=12, fill=line_color)

    # Зелёная отметка об утверждении
    cx, cy, radius = 700, 726, 150
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=(255, 255, 255, 255))
    draw.ellipse(
        (cx - radius + 16, cy - radius + 16, cx + radius - 16, cy + radius - 16),
        fill=(224, 138, 43, 255),
    )
    draw.line(
        [(cx - 62, cy + 4), (cx - 14, cy + 54), (cx + 70, cy - 44)],
        fill=(255, 255, 255, 255),
        width=30,
        joint="curve",
    )
    return base


def main() -> None:
    image = build()
    png_path = HERE / "standalone-icon.png"
    ico_path = HERE / "standalone.ico"
    image.resize((512, 512), Image.LANCZOS).save(png_path, format="PNG")
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]
    image.save(ico_path, format="ICO", sizes=sizes)
    print(f"Готово: {png_path.name}, {ico_path.name}")


if __name__ == "__main__":
    main()
