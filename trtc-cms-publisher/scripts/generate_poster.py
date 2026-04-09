#!/usr/bin/env python3
"""
Generate a CMS poster that matches the provided reference layout.

The left side always uses the fixed template background plus the blog title.
The right side can either come from a local image or from an AI-generated
scene that is derived from the article context.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import tempfile
import textwrap
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_TEMPLATE = SCRIPT_DIR.parent / "references" / "poster_example.png"
DEFAULT_OUTPUT = Path.cwd() / "generated-poster.png"
DEFAULT_VENUS_BASE_URL = "http://v2.open.venus.oa.com/llmproxy"
DEFAULT_IMAGE_MODEL = "gemini-3-pro-image"
DEFAULT_IMAGE_SIZE = "2K"
DEFAULT_IMAGE_ASPECT_RATIO = "4:5"
DEFAULT_IMAGE_QUALITY = "standard"
DEFAULT_MAX_TOKENS = 1024
DEFAULT_VENUS_TOKEN_SUFFIX = "@3701"
DEFAULT_IMAGE_RETRIES = 2
DEFAULT_IMAGE_RETRY_DELAY = 3.0

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
SCENE_PROMPT_EXCERPT_LIMIT = 900


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


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def markdown_to_plain_text(markdown_text: str) -> str:
    text = markdown_text
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[>*_~#|]", " ", text)
    return normalize_whitespace(text)


def summarize_body_for_prompt(body: str | None) -> str:
    if not body:
        return ""
    plain = markdown_to_plain_text(body)
    return plain[:SCENE_PROMPT_EXCERPT_LIMIT].strip()


def build_scene_prompt(
    title: str,
    description: str | None = None,
    seo_keys: str | None = None,
    body: str | None = None,
    scene_prompt: str | None = None,
) -> str:
    excerpt = summarize_body_for_prompt(body)
    keywords = normalize_whitespace((seo_keys or "").replace(",", ", "))
    prompt_parts = [
        "Create a premium lifestyle editorial scene for the right-side image area of a technology blog poster.",
        "The final image will be cropped into a tall rounded rectangle, so keep the main subject centered with safe margins.",
        "Do not include any text, letters, captions, logos, UI screenshots, or watermarks.",
        "Use a polished, modern, human-centered visual style suited to Tencent RTC product marketing.",
        "Favor realistic photography-inspired or lightly stylized editorial art, natural people, believable environments, and emotionally warm composition.",
        "Prefer real-life usage scenes such as conferences, meetings, livestream viewing, classrooms, or global collaboration moments instead of abstract sci-fi concepts.",
        "Keep technology cues subtle and supportive. Avoid futuristic holograms, glowing AI brains, floating chat bubbles, fantasy interfaces, or generic sci-fi spectacle.",
        "Use colors that complement a deep blue technology background, especially cyan, teal, navy, white, and soft neutral tones.",
        f"Article title: {title}.",
    ]
    if description:
        prompt_parts.append(f"Article summary: {normalize_whitespace(description)}.")
    if keywords:
        prompt_parts.append(f"Key topics: {keywords}.")
    if excerpt:
        prompt_parts.append(f"Article context: {excerpt}.")
    if scene_prompt:
        prompt_parts.append(f"Additional art direction: {normalize_whitespace(scene_prompt)}.")
    prompt_parts.append(
        "Return a single cohesive scene image only. No split layout, no poster frame, and no embedded typography."
    )
    return " ".join(prompt_parts)


def ensure_venus_token_suffix(token: str, suffix: str = DEFAULT_VENUS_TOKEN_SUFFIX) -> str:
    stripped = token.strip()
    if not stripped:
        return stripped
    if "@" in stripped:
        return stripped
    return f"{stripped}{suffix}"


def resolve_venus_token(explicit_token: str | None) -> str | None:
    suffix = os.environ.get("VENUS_TOKEN_SUFFIX", DEFAULT_VENUS_TOKEN_SUFFIX)
    if explicit_token:
        return explicit_token.strip()

    venus_token = os.environ.get("VENUS_API_KEY") or os.environ.get("VENUS_TOKEN")
    if venus_token:
        return venus_token.strip()

    venus_secret_id = os.environ.get("ENV_VENUS_OPENAPI_SECRET_ID")
    if venus_secret_id:
        return ensure_venus_token_suffix(venus_secret_id, suffix=suffix)

    openai_compat_token = os.environ.get("OPENAI_API_KEY")
    if openai_compat_token:
        return openai_compat_token.strip()

    return None


def decode_data_uri(data_uri: str) -> bytes:
    if "," not in data_uri:
        raise SystemExit("Invalid data URI returned by Venus image model.")
    _, encoded = data_uri.split(",", 1)
    return base64.b64decode(encoded)


def extract_image_bytes_from_venus_response(data: dict[str, object]) -> bytes:
    choices = data.get("choices")
    if not isinstance(choices, list):
        raise SystemExit("Venus image response did not include choices.")

    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "venus_multimodal_url":
                continue
            media = item.get("venus_multimodal_url")
            if not isinstance(media, dict):
                continue
            url = media.get("url")
            if isinstance(url, str) and url.startswith("data:"):
                return decode_data_uri(url)
            encoded = media.get("encoded")
            if isinstance(encoded, str) and encoded.strip():
                return base64.b64decode(encoded)

    raise ValueError("Venus image model did not return an image payload.")


def generate_ai_right_image(
    output_path: str | Path,
    title: str,
    description: str | None = None,
    seo_keys: str | None = None,
    body: str | None = None,
    scene_prompt: str | None = None,
    api_key: str | None = None,
    model: str = DEFAULT_IMAGE_MODEL,
    size: str = DEFAULT_IMAGE_SIZE,
    aspect_ratio: str = DEFAULT_IMAGE_ASPECT_RATIO,
    quality: str = DEFAULT_IMAGE_QUALITY,
    base_url: str = DEFAULT_VENUS_BASE_URL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: int = 90,
    retries: int = DEFAULT_IMAGE_RETRIES,
    retry_delay: float = DEFAULT_IMAGE_RETRY_DELAY,
) -> tuple[Path, str]:
    resolved_key = resolve_venus_token(api_key)
    if not resolved_key:
        raise SystemExit(
            "A Venus token is required to generate the poster scene automatically. "
            "Set VENUS_API_KEY or VENUS_TOKEN directly, or set ENV_VENUS_OPENAPI_SECRET_ID so the script can derive "
            "the bearer token automatically, or pass a local --right-image instead."
        )

    prompt = build_scene_prompt(
        title=title,
        description=description,
        seo_keys=seo_keys,
        body=body,
        scene_prompt=scene_prompt,
    )
    system_prompt = (
        "You generate a single polished marketing image for a Tencent RTC blog poster. "
        "Return the image only."
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "image_config": {
            "aspect_ratio": aspect_ratio,
            "image_size": size,
        },
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {resolved_key}",
        },
        method="POST",
    )
    last_error: str | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))

            output = Path(output_path)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(extract_image_bytes_from_venus_response(data))
            return output, prompt
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(body_text)
            except json.JSONDecodeError:
                parsed = {"error": {"message": body_text or str(exc)}}
            last_error = json.dumps(parsed, ensure_ascii=False, indent=2)
            if exc.code not in {408, 425, 429, 500, 502, 503, 504} or attempt >= retries:
                raise SystemExit(last_error)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            message = getattr(exc, "reason", str(exc))
            last_error = str(message)
            if attempt >= retries:
                raise SystemExit(
                    "AI poster scene generation failed after retries. "
                    f"Last error: {last_error}. "
                    "Retry later or provide --right-image / --poster-right-image as a manual fallback."
                )

        time.sleep(retry_delay)

    raise SystemExit(
        "AI poster scene generation failed unexpectedly. "
        f"Last error: {last_error or 'unknown error'}. "
        "Retry later or provide --right-image / --poster-right-image as a manual fallback."
    )


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
    parser.add_argument("--right-image", help="Image placed in the right-side frame.")
    parser.add_argument("--description", help="Article summary used to guide AI scene generation.")
    parser.add_argument("--seo-keys", help="SEO keywords used to guide AI scene generation.")
    parser.add_argument("--body-file", help="Markdown file used as additional context for AI scene generation.")
    parser.add_argument("--scene-prompt", help="Extra art direction for the AI-generated right-side scene.")
    parser.add_argument(
        "--save-right-image",
        help="Optional path to save the AI-generated right-side image before it is composed into the poster.",
    )
    parser.add_argument("--venus-token", dest="ai_api_key", help="Override VENUS_API_KEY or VENUS_TOKEN for AI scene generation.")
    parser.add_argument("--openai-api-key", dest="ai_api_key", help=argparse.SUPPRESS)
    parser.add_argument("--venus-base-url", dest="ai_base_url", default=DEFAULT_VENUS_BASE_URL, help="Venus OpenAI-compatible base URL.")
    parser.add_argument("--openai-base-url", dest="ai_base_url", help=argparse.SUPPRESS)
    parser.add_argument("--image-model", default=DEFAULT_IMAGE_MODEL, help="Image model used for AI scene generation.")
    parser.add_argument("--image-size", default=DEFAULT_IMAGE_SIZE, help="Gemini image size such as 1K, 2K, or 4K.")
    parser.add_argument("--image-aspect-ratio", default=DEFAULT_IMAGE_ASPECT_RATIO, help="Gemini image aspect ratio such as 4:5.")
    parser.add_argument("--image-quality", default=DEFAULT_IMAGE_QUALITY, help="Reserved image quality field for prompt labeling.")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS, help="Max output tokens for Venus image generation.")
    parser.add_argument("--timeout", type=int, default=90, help="HTTP timeout for AI scene generation.")
    parser.add_argument("--retries", type=int, default=DEFAULT_IMAGE_RETRIES, help="Retry count for Venus image generation.")
    parser.add_argument("--retry-delay", type=float, default=DEFAULT_IMAGE_RETRY_DELAY, help="Delay in seconds between Venus image retries.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output PNG path.")
    parser.add_argument("--template", default=str(DEFAULT_TEMPLATE), help="Template PNG path.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    right_image_path = args.right_image
    temp_dir: tempfile.TemporaryDirectory[str] | None = None

    if not right_image_path:
        body_text = ""
        if args.body_file:
            body_text = Path(args.body_file).read_text(encoding="utf-8")
        if args.save_right_image:
            right_image_path = args.save_right_image
        else:
            temp_dir = tempfile.TemporaryDirectory(prefix="cms-poster-scene-")
            right_image_path = str(Path(temp_dir.name) / "right-scene.png")
        generate_ai_right_image(
            output_path=right_image_path,
            title=args.title,
            description=args.description,
            seo_keys=args.seo_keys,
            body=body_text,
            scene_prompt=args.scene_prompt,
            api_key=args.ai_api_key,
            model=args.image_model,
            size=args.image_size,
            aspect_ratio=args.image_aspect_ratio,
            quality=args.image_quality,
            base_url=args.ai_base_url,
            max_tokens=args.max_tokens,
            timeout=args.timeout,
            retries=args.retries,
            retry_delay=args.retry_delay,
        )

    output = render_poster(
        title=args.title,
        right_image_path=right_image_path,
        output_path=args.output,
        template_path=args.template,
    )
    if temp_dir is not None:
        temp_dir.cleanup()
    print(output)


if __name__ == "__main__":
    main()
