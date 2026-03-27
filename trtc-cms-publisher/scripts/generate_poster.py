#!/usr/bin/env python3
"""
Generate a CMS poster that matches the provided reference layout.
"""

from __future__ import annotations

import argparse
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_TEMPLATE = SCRIPT_DIR.parent / "references" / "poster_example.png"
DEFAULT_OUTPUT = Path.cwd() / "generated-poster.png"

TITLE_COVER_BOX = (36, 250, 430, 250)
TITLE_TEXT_BOX = (58, 286, 350, 220)
RIGHT_IMAGE_BOX = (529, 147, 991, 653)
RIGHT_IMAGE_RADIUS = 28
TITLE_COLOR = (255, 255, 255, 255)
LINE_SPACING_FACTOR = 0.16
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Helvetica.ttf",
]


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def wrap_title(draw: ImageDraw.ImageDraw, title: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = title.split()
    if not words:
        return [title]

    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def fit_title(draw: ImageDraw.ImageDraw, title: str, box_width: int, box_height: int) -> tuple[ImageFont.ImageFont, list[str], int]:
    for font_size in range(82, 35, -2):
        font = load_font(font_size)
        lines = wrap_title(draw, title, font, box_width)
        if len(lines) > 4:
            continue
        line_height = draw.textbbox((0, 0), "Ag", font=font)[3]
        spacing = max(8, int(font_size * LINE_SPACING_FACTOR))
        total_height = len(lines) * line_height + max(0, len(lines) - 1) * spacing
        if total_height <= box_height:
            return font, lines, spacing

    font = load_font(36)
    wrapped = textwrap.wrap(title, width=18)[:4] or [title]
    return font, wrapped, 8


def make_rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
    return mask


def make_soft_mask(size: tuple[int, int], radius: int, blur_radius: int) -> Image.Image:
    mask = make_rounded_mask(size, radius)
    if blur_radius > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(blur_radius))
    return mask


def make_title_background(crop: Image.Image) -> Image.Image:
    width, height = crop.size
    source = crop.convert("RGBA")
    src = source.load()
    patch = Image.new("RGBA", (width, height))
    out = patch.load()
    edge_width = 28

    for y in range(height):
        left = [0, 0, 0, 0]
        right = [0, 0, 0, 0]
        for x in range(edge_width):
            lp = src[x, y]
            rp = src[width - 1 - x, y]
            for i in range(4):
                left[i] += lp[i]
                right[i] += rp[i]
        left = [int(channel / edge_width) for channel in left]
        right = [int(channel / edge_width) for channel in right]

        for x in range(width):
            ratio = x / max(1, width - 1)
            pixel = tuple(
                int(left[i] * (1 - ratio) + right[i] * ratio)
                for i in range(4)
            )
            out[x, y] = pixel

    patch = patch.filter(ImageFilter.GaussianBlur(4))
    return patch


def render_poster(title: str, right_image_path: str | Path, output_path: str | Path, template_path: str | Path = DEFAULT_TEMPLATE) -> Path:
    template = Image.open(template_path).convert("RGBA")
    right_image = Image.open(right_image_path).convert("RGBA")

    poster = template.copy()
    draw = ImageDraw.Draw(poster)

    # Rebuild the background under the title so the original title disappears
    # without introducing a visible solid box.
    cover_x, cover_y, cover_w, cover_h = TITLE_COVER_BOX
    original_cover = poster.crop((cover_x, cover_y, cover_x + cover_w, cover_y + cover_h))
    cover_region = make_title_background(original_cover)
    cover_mask = make_soft_mask((cover_w, cover_h), radius=34, blur_radius=6)
    poster.paste(cover_region, (cover_x, cover_y), cover_mask)

    image_x, image_y, image_w, image_h = RIGHT_IMAGE_BOX
    fitted = ImageOps.fit(right_image, (image_w, image_h), method=Image.Resampling.LANCZOS)
    image_mask = make_rounded_mask((image_w, image_h), RIGHT_IMAGE_RADIUS)
    poster.paste(fitted, (image_x, image_y), image_mask)

    text_x, text_y, text_w, text_h = TITLE_TEXT_BOX
    font, lines, spacing = fit_title(draw, title, text_w, text_h)
    cursor_y = text_y
    for line in lines:
        draw.text((text_x, cursor_y), line, font=font, fill=TITLE_COLOR)
        line_height = draw.textbbox((0, 0), line, font=font)[3]
        cursor_y += line_height + spacing

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    poster.save(output)
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a poster from the CMS reference template.")
    parser.add_argument("--title", required=True, help="Poster title shown on the left.")
    parser.add_argument("--right-image", required=True, help="Image placed in the right-side frame.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output PNG path.")
    parser.add_argument("--template", default=str(DEFAULT_TEMPLATE), help="Template PNG path.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    output = render_poster(
        title=args.title,
        right_image_path=args.right_image,
        output_path=args.output,
        template_path=args.template,
    )
    print(output)


if __name__ == "__main__":
    main()
