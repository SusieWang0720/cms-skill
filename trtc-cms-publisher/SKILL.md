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

Generate the poster first and stop before CMS import:

```bash
python3 /Users/wangshuoxin/Claude-Internal/CMS/trtc-cms-publisher/scripts/import_article.py \
  --input /absolute/path/to/article.md \
  --prepare-only
```

## Poster Workflow

Every blog should include a poster that follows the layout in `references/poster_example.png`.

- Keep the background and overall frame style unchanged
- Replace the left-side title with the blog topic
- Replace the right-side image with an AI-generated blog-relevant scene by default
- Treat `poster_right_image` as the right-side visual only, not a full poster screenshot
- Use the article title, description, SEO keywords, and body excerpt to guide the AI scene so the visual matches the article topic
- Do not generate text inside the right-side scene. The AI image should be scene-only, while the left side continues to hold the title copy
- Keep `poster_right_image` as a manual override when the user already has a specific right-side image they want to use
- Name the poster file clearly with the article keywords, preferably using the article slug such as `simultaneous-interpretation-technology-poster.png`
- Name the AI-generated right-side scene clearly too, preferably using the article slug such as `simultaneous-interpretation-technology-scene.png`
- Pass the generated poster back through `poster_file`, or let the import script generate it automatically from `poster_right_image`
- When the article body should begin with the cover image, use a hosted `poster_body_url` in `rich_content` rather than embedding a base64 data URI, otherwise CMS may reject the request as too large
- Use keyword-rich alt text for the body cover image based on the article title and leading SEO keywords
- The AI scene flow uses Tencent Venus's OpenAI-compatible `chat/completions` proxy by default with a Gemini image model
- Set `VENUS_API_KEY` or `VENUS_TOKEN` before running, or set `ENV_VENUS_OPENAPI_SECRET_ID` and let the script auto-append the default `@3701` suffix
- Optionally override `VENUS_BASE_URL`, `--poster-image-model`, `--poster-image-size`, or `--poster-image-aspect-ratio`

Generate a poster directly:

```bash
VENUS_API_KEY=your_venus_token_here \
python3 /Users/wangshuoxin/Claude-Internal/CMS/trtc-cms-publisher/scripts/generate_poster.py \
  --title "The Definitive Guide to Simultaneous Interpretation Technology" \
  --description "Everything you need to know about AI-powered simultaneous interpretation." \
  --seo-keys "simultaneous interpretation, real-time translation, AI interpretation" \
  --body-file /absolute/path/to/article.md \
  --save-right-image /absolute/path/to/simultaneous-interpretation-technology-scene.png \
  --output /absolute/path/to/poster.png
```

If you already have a right-side image and want to skip AI generation, keep using `--right-image /absolute/path/to/right-image.png`.

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
poster_scene_prompt: A keynote speaker on stage with floating translated captions and multilingual audience devices.
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
- `poster_scene_prompt`
- `poster_body_url`

The script will:

- Use the first Markdown `# Heading` as `title` when `title` is missing
- Generate a slug from `title` when `route_name` is missing
- Default `category` to `Products and Solutions` when it is not provided
- Default `author` to `Tencent RTC` when it is not provided
- Convert `poster_file` into a base64 data URI automatically
- Reuse the article slug in the auto-generated poster filename so the file name stays clear and searchable
- Reuse the article slug in the AI-generated right-side scene filename so the scene asset stays clear and searchable
- Generate an AI right-side scene automatically when `poster_right_image` is not provided
- Let `poster_scene_prompt` add art direction for the AI scene without changing the fixed poster background or left-side title copy
- Use Tencent Venus `chat/completions` with an image-capable Gemini model to generate the right-side scene, so the flow can run on the company proxy instead of the official OpenAI image endpoint
- Support a two-step confirmation flow through `--prepare-only`: first generate the scene and poster assets, show them to the user, then rerun the import after the user confirms the image is acceptable
- Remove the article H1 from `rich_content` so the title does not appear twice
- Insert the poster once at the top of `rich_content` before the article body begins when `poster_body_url` is provided
- Use the article title and SEO keywords to generate a meaningful body-image alt text instead of leaving the image description blank
- Save as a draft by default when `publishedAt` is omitted

## Workflow

1. Read [references/import-article-api.md](references/import-article-api.md) if field mapping or API behavior is unclear.
2. Confirm whether the user wants a draft or immediate publish.
3. Prepare a Markdown file with frontmatter, or supply metadata as CLI flags.
4. Ensure the article has a poster. Prefer the built-in AI scene generation so the script can create the right-side visual from the article context and then compose the final poster from the reference template.
5. Keep the poster filename human-readable and keyword-rich. Prefer the article slug plus `-poster.png`.
6. Ensure the body content starts with the poster image URL and then the article body, without repeating the title as an H1.
7. Run the script with `--prepare-only` first to generate the poster and pause for user confirmation.
8. Show the generated poster to the user and wait until the user says the image is OK.
9. Rerun the script without `--prepare-only`. Pass the generated `poster_file` if needed so the approved image is reused.
10. Use `--dry-run` when the payload or slug still looks risky.
11. Run the live import.
12. Report the CMS response clearly, including `id`, `route_name`, `language`, and whether `publishedAt` is null.

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

Import with AI-generated poster scene:

```bash
VENUS_API_KEY=your_venus_token_here \
python3 /Users/wangshuoxin/Claude-Internal/CMS/trtc-cms-publisher/scripts/import_article.py \
  --input /absolute/path/to/article.md \
  --poster-scene-prompt "A polished multilingual conference scene with real-time translation flowing across devices" \
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

Recommended two-step flow:

```bash
VENUS_API_KEY=your_venus_token_here \
python3 /Users/wangshuoxin/Claude-Internal/CMS/trtc-cms-publisher/scripts/import_article.py \
  --input /absolute/path/to/article.md \
  --poster-scene-prompt "A polished multilingual conference scene with real-time translation flowing across devices" \
  --prepare-only
```

After the user approves the generated poster, rerun with the approved poster file:

```bash
VENUS_API_KEY=your_venus_token_here \
python3 /Users/wangshuoxin/Claude-Internal/CMS/trtc-cms-publisher/scripts/import_article.py \
  --input /absolute/path/to/article.md \
  --poster-file /absolute/path/to/generated-poster.png
```

## Operational Notes

- Default API URL: `https://trtc-cms.woa.com/api/import/article`
- No authentication is required according to the API doc.
- Poster scene generation now defaults to Tencent Venus: `http://v2.open.venus.oa.com/llmproxy/chat/completions`
- The default image model is `gemini-3-pro-image`. If your应用组要求使用其他公共模型 `modelid`，请直接通过 `--poster-image-model` 传入模型列表里的 `model` 字段。
- Venus token can come from `VENUS_API_KEY` or `VENUS_TOKEN`.
- The script also supports the internal official pattern: if `ENV_VENUS_OPENAPI_SECRET_ID` is present, it will automatically derive the bearer token as `<secret_id>@3701`.
- If your app group uses a different suffix, set `VENUS_TOKEN_SUFFIX` to override the default `@3701`.
- For compatibility, the script still accepts `OPENAI_API_KEY`, but the recommended setup is the Venus env vars above.
- `title` and `route_name` must be unique within the same language.
- Valid languages: `English`, `Japanese`, `Korean`, `Chinese`
- The API accepts Markdown in `rich_content`; it converts to CMS HTML automatically.
- If the command fails because the environment blocks outbound network access, rerun with escalated permissions.
- If AI scene generation is enabled and the Venus token is missing, the script will stop and ask for either the Venus env vars or a manual `poster_right_image`.
- Do not promise success before reading the API response. Surface API validation errors verbatim when possible.
