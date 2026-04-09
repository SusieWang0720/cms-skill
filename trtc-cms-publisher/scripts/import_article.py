#!/usr/bin/env python3
"""
Import a Markdown article into the Tencent RTC CMS.

Features:
- Read Markdown from a file or stdin
- Parse simple frontmatter
- Derive title from the first H1 when missing
- Derive route_name from title when missing
- Convert a local poster image into a base64 data URI
- Preview the outgoing payload with --dry-run
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from generate_poster import DEFAULT_IMAGE_ASPECT_RATIO
from generate_poster import DEFAULT_IMAGE_MODEL
from generate_poster import DEFAULT_IMAGE_QUALITY
from generate_poster import DEFAULT_IMAGE_SIZE
from generate_poster import DEFAULT_MAX_TOKENS
from generate_poster import DEFAULT_TEMPLATE as DEFAULT_POSTER_TEMPLATE
from generate_poster import DEFAULT_VENUS_BASE_URL
from generate_poster import generate_ai_right_image
from generate_poster import render_poster

DEFAULT_API_URL = "https://trtc-cms.woa.com/api/import/article"
DEFAULT_CATEGORY = "Products and Solutions"
DEFAULT_AUTHOR = "Tencent RTC"
VALID_LANGUAGES = {"English", "Japanese", "Korean", "Chinese"}
DISALLOWED_ROUTE_CHARS = set('@#$%^&*<>《》「」{}')


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import a Markdown article into the Tencent RTC CMS."
    )
    parser.add_argument("--input", help="Path to a Markdown file with optional frontmatter.")
    parser.add_argument("--title", help="Article title.")
    parser.add_argument("--route-name", help="Article route_name / slug.")
    parser.add_argument("--description", help="Article summary.")
    parser.add_argument("--language", choices=sorted(VALID_LANGUAGES), help="Article language.")
    parser.add_argument("--seo-title", help="SEO title.")
    parser.add_argument("--seo-desc", help="SEO description.")
    parser.add_argument("--seo-keys", help="SEO keywords.")
    parser.add_argument("--category", help="Category name.")
    parser.add_argument("--label", action="append", default=[], help="Label name. Repeatable.")
    parser.add_argument("--author", help="Author name.")
    parser.add_argument("--published-at", help="ISO 8601 publish time.")
    parser.add_argument(
        "--publish-now",
        action="store_true",
        help="Publish immediately with the current UTC timestamp when publishedAt is missing.",
    )
    parser.add_argument("--poster", help="Poster as base64 or a data URI string.")
    parser.add_argument("--poster-file", help="Path to a local poster image file.")
    parser.add_argument(
        "--poster-body-url",
        help="Hosted poster URL inserted at the top of rich_content. Use this instead of embedding a data URI in the body.",
    )
    parser.add_argument(
        "--poster-right-image",
        help="Image used in the right-side poster frame only. If provided without --poster-file, the poster is generated automatically.",
    )
    parser.add_argument(
        "--poster-scene-prompt",
        help="Extra art direction for AI-generated right-side poster scenes.",
    )
    parser.add_argument(
        "--poster-scene-output",
        help="Path to save the AI-generated right-side poster scene.",
    )
    parser.add_argument(
        "--poster-template",
        default=str(DEFAULT_POSTER_TEMPLATE),
        help="Poster template image path used when generating a poster automatically.",
    )
    parser.add_argument("--venus-token", dest="ai_api_key", help="Override VENUS_API_KEY or VENUS_TOKEN for AI poster scene generation.")
    parser.add_argument("--openai-api-key", dest="ai_api_key", help=argparse.SUPPRESS)
    parser.add_argument("--venus-base-url", dest="ai_base_url", default=DEFAULT_VENUS_BASE_URL, help="Venus OpenAI-compatible base URL.")
    parser.add_argument("--openai-base-url", dest="ai_base_url", help=argparse.SUPPRESS)
    parser.add_argument("--poster-image-model", default=DEFAULT_IMAGE_MODEL, help="Image model used for AI poster scenes.")
    parser.add_argument("--poster-image-size", default=DEFAULT_IMAGE_SIZE, help="Gemini image size such as 1K, 2K, or 4K.")
    parser.add_argument("--poster-image-aspect-ratio", default=DEFAULT_IMAGE_ASPECT_RATIO, help="Gemini image aspect ratio such as 4:5.")
    parser.add_argument("--poster-image-quality", default=DEFAULT_IMAGE_QUALITY, help="Reserved image quality label for AI poster scenes.")
    parser.add_argument("--poster-image-max-tokens", type=int, default=DEFAULT_MAX_TOKENS, help="Max output tokens for Venus image generation.")
    parser.add_argument("--poster-image-timeout", type=int, default=90, help="HTTP timeout in seconds for AI poster scene generation.")
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="Import API URL.")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds.")
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Generate or resolve poster assets and stop before sending anything to CMS.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the request payload instead of sending it.",
    )
    return parser


def strip_matching_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def parse_frontmatter(markdown_text: str) -> tuple[dict[str, Any], str]:
    if not markdown_text.startswith("---\n"):
        return {}, markdown_text

    lines = markdown_text.splitlines()
    if len(lines) < 3:
        return {}, markdown_text

    end_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break

    if end_index is None:
        return {}, markdown_text

    metadata_lines = lines[1:end_index]
    body = "\n".join(lines[end_index + 1 :]).lstrip("\n")
    metadata = parse_simple_yaml(metadata_lines)
    return metadata, body


def parse_simple_yaml(lines: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    current_list_key: str | None = None

    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        stripped = line.lstrip()
        if stripped.startswith("- "):
            if not current_list_key:
                raise ValueError(f"List item found without a key: {raw_line}")
            result.setdefault(current_list_key, []).append(parse_scalar(stripped[2:].strip()))
            continue

        current_list_key = None
        if ":" not in line:
            raise ValueError(f"Invalid frontmatter line: {raw_line}")

        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if not key:
            raise ValueError(f"Invalid frontmatter key: {raw_line}")

        if not value:
            result[key] = []
            current_list_key = key
            continue

        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            if not inner:
                result[key] = []
            else:
                parts = [parse_scalar(part.strip()) for part in inner.split(",") if part.strip()]
                result[key] = parts
            continue

        result[key] = parse_scalar(value)

    return result


def parse_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered in {"null", "none"}:
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return strip_matching_quotes(value)


def read_markdown(input_path: str | None) -> tuple[dict[str, Any], str]:
    if input_path:
        text = Path(input_path).read_text(encoding="utf-8")
        return parse_frontmatter(text)

    if sys.stdin.isatty():
        raise SystemExit("Provide --input or pipe Markdown over stdin.")

    return parse_frontmatter(sys.stdin.read())


def first_h1(markdown_text: str) -> str | None:
    for line in markdown_text.splitlines():
        if line.startswith("# "):
            heading = line[2:].strip()
            if heading:
                return heading
    return None


def slugify(value: str) -> str:
    slug = value.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug, flags=re.UNICODE)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-")


def validate_language(language: str | None) -> None:
    if language and language not in VALID_LANGUAGES:
        allowed = ", ".join(sorted(VALID_LANGUAGES))
        raise SystemExit(f"language must be one of: {allowed}")


def validate_route_name(route_name: str) -> None:
    if not route_name.strip():
        raise SystemExit("route_name cannot be empty")
    if any(char in DISALLOWED_ROUTE_CHARS for char in route_name):
        bad = next(char for char in route_name if char in DISALLOWED_ROUTE_CHARS)
        raise SystemExit(f'route_name includes special character: "{bad}"')
    if re.search(r"\s", route_name):
        raise SystemExit("route_name cannot contain whitespace")


def to_data_uri(image_path: str) -> str:
    path = Path(image_path)
    raw = path.read_bytes()
    mime_type, _ = mimetypes.guess_type(path.name)
    mime_type = mime_type or "image/png"
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def normalize_poster_value(poster: str | None) -> str | None:
    if not poster:
        return None
    if poster.startswith("data:") or poster.startswith("http://") or poster.startswith("https://"):
        return poster
    return f"data:image/png;base64,{poster}"


def poster_output_path(input_path: str | None, route_name: str) -> Path:
    if input_path:
        base_dir = Path(input_path).resolve().parent
    else:
        base_dir = Path.cwd()
    return base_dir / f"{route_name}-poster.png"


def scene_output_path(input_path: str | None, route_name: str) -> Path:
    if input_path:
        base_dir = Path(input_path).resolve().parent
    else:
        base_dir = Path.cwd()
    return base_dir / f"{route_name}-scene.png"


def build_poster_alt_text(title: str, seo_keys: str | None) -> str:
    keywords: list[str] = []
    if seo_keys:
        keywords = [item.strip() for item in seo_keys.split(",") if item.strip()]
    keyword_text = ", ".join(keywords[:3])
    if keyword_text:
        return f"{title} cover image - {keyword_text}"
    return f"{title} cover image"


def promote_heading_levels(body: str) -> str:
    promoted_lines: list[str] = []
    for line in body.splitlines():
        if line.startswith("### "):
            promoted_lines.append(f"## {line[4:]}")
        elif line.startswith("## "):
            promoted_lines.append(f"# {line[3:]}")
        else:
            promoted_lines.append(line)
    return "\n".join(promoted_lines)


def strip_leading_title(body: str, title: str) -> tuple[str, bool]:
    lines = body.splitlines()
    if not lines:
        return body, False

    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1

    if index < len(lines) and lines[index].startswith("# "):
        heading = lines[index][2:].strip()
        if heading == title.strip():
            index += 1
            while index < len(lines) and not lines[index].strip():
                index += 1
            return "\n".join(lines[index:]).lstrip("\n"), True
    return body, False


def inject_cover_image(body: str, poster_for_body: str | None, alt_text: str) -> str:
    if not poster_for_body:
        return body
    body = body.lstrip("\n")
    image_line = f"![{alt_text}]({poster_for_body})"
    if not body:
        return image_line
    return f"{image_line}\n\n{body}"


def compact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, list) and not value:
            continue
        cleaned[key] = value
    return cleaned


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def resolve_article_metadata(
    frontmatter: dict[str, Any], args: argparse.Namespace, body: str
) -> tuple[str, str, str, str, str | None, str | None, list[str], str | None]:
    title = args.title or frontmatter.get("title") or first_h1(body)
    if not title:
        raise SystemExit("title is required. Pass --title or add a first-level Markdown heading.")

    route_name = args.route_name or frontmatter.get("route_name") or slugify(title)
    if not route_name:
        raise SystemExit("route_name is required and could not be generated from title.")
    validate_route_name(route_name)

    body, removed_title = strip_leading_title(body, title)
    if removed_title:
        body = promote_heading_levels(body)

    language = args.language or frontmatter.get("language") or "English"
    validate_language(language)

    description = args.description or frontmatter.get("description")
    seo_keys = args.seo_keys or frontmatter.get("seo_keys")

    labels = list(frontmatter.get("labels", []))
    if isinstance(frontmatter.get("labels"), str):
        labels = [frontmatter["labels"]]
    labels.extend(args.label)

    published_at = args.published_at or frontmatter.get("publishedAt")
    if args.publish_now and not published_at:
        published_at = iso_now()

    return title, route_name, body, language, description, seo_keys, labels, published_at


def resolve_poster_assets(
    frontmatter: dict[str, Any],
    args: argparse.Namespace,
    body: str,
    title: str,
    route_name: str,
    description: str | None,
    seo_keys: str | None,
) -> dict[str, str | None]:
    poster = args.poster or frontmatter.get("poster")
    poster_file = args.poster_file or frontmatter.get("poster_file")
    poster_right_image = args.poster_right_image or frontmatter.get("poster_right_image")
    poster_scene_prompt = args.poster_scene_prompt or frontmatter.get("poster_scene_prompt")
    poster_scene_output = args.poster_scene_output or frontmatter.get("poster_scene_output")
    poster_body_url = args.poster_body_url or frontmatter.get("poster_body_url")

    if not poster and not poster_file:
        if not poster_right_image:
            poster_right_image = str(
                poster_scene_output or scene_output_path(args.input, route_name)
            )
            generate_ai_right_image(
                output_path=poster_right_image,
                title=title,
                description=description,
                seo_keys=seo_keys,
                body=body,
                scene_prompt=poster_scene_prompt,
                api_key=args.ai_api_key,
                model=args.poster_image_model,
                size=args.poster_image_size,
                aspect_ratio=args.poster_image_aspect_ratio,
                quality=args.poster_image_quality,
                base_url=args.ai_base_url,
                max_tokens=args.poster_image_max_tokens,
                timeout=args.poster_image_timeout,
            )

        poster_file = str(poster_output_path(args.input, route_name))
        render_poster(
            title=title,
            right_image_path=str(poster_right_image),
            output_path=poster_file,
            template_path=args.poster_template,
        )

    return {
        "poster": normalize_poster_value(poster),
        "poster_file": str(poster_file) if poster_file else None,
        "poster_right_image": str(poster_right_image) if poster_right_image else None,
        "poster_body_url": str(poster_body_url) if poster_body_url else None,
    }


def merge_metadata(frontmatter: dict[str, Any], args: argparse.Namespace, body: str) -> dict[str, Any]:
    (
        title,
        route_name,
        body,
        language,
        description,
        seo_keys,
        labels,
        published_at,
    ) = resolve_article_metadata(frontmatter, args, body)

    assets = resolve_poster_assets(
        frontmatter=frontmatter,
        args=args,
        body=body,
        title=title,
        route_name=route_name,
        description=description,
        seo_keys=seo_keys,
    )

    poster = assets["poster"]
    poster_file = assets["poster_file"]
    poster_body_url = assets["poster_body_url"]
    if poster_file:
        poster = to_data_uri(str(poster_file))
    poster = normalize_poster_value(poster)
    if not poster_body_url and isinstance(poster, str) and poster.startswith(("http://", "https://")):
        poster_body_url = poster
    poster_alt_text = build_poster_alt_text(title, seo_keys)
    body = inject_cover_image(body, poster_body_url, poster_alt_text)

    payload = {
        "title": title,
        "route_name": route_name,
        "rich_content": body,
        "description": description,
        "language": language,
        "seo_title": args.seo_title or frontmatter.get("seo_title"),
        "seo_desc": args.seo_desc or frontmatter.get("seo_desc"),
        "seo_keys": seo_keys,
        "category": args.category or frontmatter.get("category") or DEFAULT_CATEGORY,
        "labels": labels,
        "author": args.author or frontmatter.get("author") or DEFAULT_AUTHOR,
        "publishedAt": published_at,
        "poster": poster,
    }
    return compact_payload(payload)


def build_prepare_summary(frontmatter: dict[str, Any], args: argparse.Namespace, body: str) -> dict[str, Any]:
    (
        title,
        route_name,
        cleaned_body,
        language,
        description,
        seo_keys,
        labels,
        published_at,
    ) = resolve_article_metadata(frontmatter, args, body)

    assets = resolve_poster_assets(
        frontmatter=frontmatter,
        args=args,
        body=cleaned_body,
        title=title,
        route_name=route_name,
        description=description,
        seo_keys=seo_keys,
    )

    return compact_payload(
        {
            "mode": "prepare_only",
            "title": title,
            "route_name": route_name,
            "language": language,
            "description": description,
            "seo_keys": seo_keys,
            "category": args.category or frontmatter.get("category") or DEFAULT_CATEGORY,
            "labels": labels,
            "author": args.author or frontmatter.get("author") or DEFAULT_AUTHOR,
            "publishedAt": published_at,
            "poster_right_image": assets["poster_right_image"],
            "poster_file": assets["poster_file"],
            "poster_body_url": assets["poster_body_url"],
            "status": "Poster assets ready. Review the poster with the user before rerunning without --prepare-only.",
        }
    )


def send_request(api_url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        api_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"error": {"message": body or str(exc)}}
        raise SystemExit(json.dumps(parsed, ensure_ascii=False, indent=2))
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Network error while reaching {api_url}: {exc.reason}. "
            "If this environment blocks outbound access, rerun with escalated permissions."
        )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    frontmatter, body = read_markdown(args.input)

    if args.prepare_only:
        summary = build_prepare_summary(frontmatter, args, body)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    payload = merge_metadata(frontmatter, args, body)

    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    response = send_request(args.api_url, payload, args.timeout)
    print(json.dumps(response, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
