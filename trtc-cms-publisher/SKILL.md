---
name: trtc-cms-publisher
description: Publish or import blog articles into the Tencent RTC internal CMS through the Import Article API. Use when the user wants to send Markdown content, a local Markdown file, or a finished blog post into the CMS backend as a draft or a published article. Trigger on requests about CMS publishing, importing articles, TRTC blog posting, route_name or slug setup, CMS article metadata, the Import Article API, or Chinese requests such as 发布到CMS, 导入文章, 发布博客, 导入后台.
---

# TRTC CMS Publisher

Use this skill to turn Markdown into a CMS article and send it to the Tencent RTC internal CMS import endpoint.

## Quick Start

Prefer a Markdown file with optional frontmatter. Use the bundled script:

```bash
python3 /Users/wangshuoxin/Claude-Internal/CMS/trtc-cms-publisher/scripts/import_article.py \
  --input /absolute/path/to/article.md
```

Preview the payload before a live import:

```bash
python3 /Users/wangshuoxin/Claude-Internal/CMS/trtc-cms-publisher/scripts/import_article.py \
  --input /absolute/path/to/article.md \
  --dry-run
```

If the user gives content inline instead of a file, write it to a temporary Markdown file in the workspace or pipe it over stdin and then run the script.

## Poster Workflow

Every blog should include a poster that follows the layout in `references/poster_example.png`.

- Keep the background and overall frame style unchanged
- Replace the left-side title with the blog topic
- Replace the right-side image with a blog-relevant image
- Treat `poster_right_image` as the right-side visual only, not a full poster screenshot
- Name the poster file clearly with the article keywords, preferably using the article slug such as `simultaneous-interpretation-technology-poster.png`
- Pass the generated poster back through `poster_file`, or let the import script generate it automatically from `poster_right_image`
- When the article body should begin with the cover image, use a hosted `poster_body_url` in `rich_content` rather than embedding a base64 data URI, otherwise CMS may reject the request as too large
- Use keyword-rich alt text for the body cover image based on the article title and leading SEO keywords

Generate a poster directly:

```bash
python3 /Users/wangshuoxin/Claude-Internal/CMS/trtc-cms-publisher/scripts/generate_poster.py \
  --title "The Definitive Guide to Simultaneous Interpretation Technology" \
  --right-image /absolute/path/to/right-image.png \
  --output /absolute/path/to/poster.png
```

## Preferred Article Format

Use Markdown with simple frontmatter when metadata is available:

```markdown
---
title: TRTC Quick Start Guide
route_name: trtc-quick-start-guide
description: Learn how to publish your first TRTC article.
language: English
seo_title: TRTC Quick Start Guide | TRTC Blog
seo_desc: Learn how to publish your first TRTC article.
seo_keys: TRTC, quick start, RTC
category: Tutorial
labels: [RTC, Video]
author: TRTC Team
publishedAt: 2026-03-19T00:00:00.000Z
poster_right_image: /absolute/path/to/right-image.png
poster_body_url: https://your-cdn.example.com/path/to/poster.png
---

Article body in Markdown...
```

Supported frontmatter keys:

- `title`
- `route_name`
- `description`
- `language`
- `seo_title`
- `seo_desc`
- `seo_keys`
- `category`
- `labels`
- `author`
- `publishedAt`
- `poster`
- `poster_file`
- `poster_right_image`
- `poster_body_url`

The script will:

- Use the first Markdown `# Heading` as `title` when `title` is missing
- Generate a slug from `title` when `route_name` is missing
- Default `category` to `Products and Solutions` when it is not provided
- Convert `poster_file` into a base64 data URI automatically
- Reuse the article slug in the auto-generated poster filename so the file name stays clear and searchable
- Generate a template-based poster automatically when `poster_right_image` is provided
- Remove the article H1 from `rich_content` so the title does not appear twice
- Insert the poster once at the top of `rich_content` before the article body begins when `poster_body_url` is provided
- Use the article title and SEO keywords to generate a meaningful body-image alt text instead of leaving the image description blank
- Save as a draft by default when `publishedAt` is omitted

## Workflow

1. Read [references/import-article-api.md](references/import-article-api.md) if field mapping or API behavior is unclear.
2. Confirm whether the user wants a draft or immediate publish.
3. Prepare a Markdown file with frontmatter, or supply metadata as CLI flags.
4. Ensure the article has a poster. Prefer `poster_right_image` so the script can generate one from the reference template.
5. Keep the poster filename human-readable and keyword-rich. Prefer the article slug plus `-poster.png`.
6. Ensure the body content starts with the poster image URL and then the article body, without repeating the title as an H1.
7. Run the script with `--dry-run` first when the payload or slug looks risky.
8. Run the live import.
9. Report the CMS response clearly, including `id`, `route_name`, `language`, and whether `publishedAt` is null.

## Publishing Commands

Import a draft from Markdown:

```bash
python3 /Users/wangshuoxin/Claude-Internal/CMS/trtc-cms-publisher/scripts/import_article.py \
  --input /absolute/path/to/article.md
```

Publish immediately with the current UTC time:

```bash
python3 /Users/wangshuoxin/Claude-Internal/CMS/trtc-cms-publisher/scripts/import_article.py \
  --input /absolute/path/to/article.md \
  --poster-right-image /absolute/path/to/right-image.png \
  --publish-now
```

Override metadata from the command line:

```bash
python3 /Users/wangshuoxin/Claude-Internal/CMS/trtc-cms-publisher/scripts/import_article.py \
  --input /absolute/path/to/article.md \
  --title "TRTC Best Practices for Video Calling" \
  --route-name "trtc-best-practices-video-calling" \
  --language English \
  --category Tutorial \
  --label RTC \
  --label Video \
  --author "TRTC Team"
```

## Operational Notes

- Default API URL: `https://trtc-cms.woa.com/api/import/article`
- No authentication is required according to the API doc.
- `title` and `route_name` must be unique within the same language.
- Valid languages: `English`, `Japanese`, `Korean`, `Chinese`
- The API accepts Markdown in `rich_content`; it converts to CMS HTML automatically.
- If the command fails because the environment blocks outbound network access, rerun with escalated permissions.
- Do not promise success before reading the API response. Surface API validation errors verbatim when possible.
