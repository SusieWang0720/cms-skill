# Import Article API Reference

## Endpoint

- Method: `POST`
- URL: `https://trtc-cms.woa.com/api/import/article`
- Content-Type: `application/json`
- Auth: not required

## Request Fields

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `title` | string | Yes | Must be unique within the same language |
| `route_name` | string | Yes | Slug, must be unique within the same language |
| `rich_content` | string | Yes | Raw Markdown |
| `description` | string | No | Summary |
| `language` | string | No | `English` by default; also `Japanese`, `Korean`, `Chinese` |
| `seo_title` | string | No | SEO title |
| `seo_desc` | string | No | SEO description |
| `seo_keys` | string | No | SEO keywords |
| `category` | string | No | Matches existing category names only |
| `labels` | string[] | No | Matches existing label names only |
| `author` | string | No | Matches existing author names only |
| `publishedAt` | string | No | ISO 8601 string; omit for draft |
| `poster` | string | No | Base64 or data URI |

## Publishing Behavior

- Omit `publishedAt`: save as draft
- Provide `publishedAt`: publish immediately

## Markdown Conversion Notes

- `# Heading` becomes `<h2>`
- `## Heading` becomes `<h3>`
- `### Heading` becomes `<h4>`
- `*italic*` becomes `<i>`
- Images are wrapped in CKEditor `figure.image`
- Links receive `target="_blank"` and `rel`

## Error Patterns

- Missing required field:
  `{ "error": { "message": "title is required and must be a string" } }`
- Duplicate slug:
  `{ "error": { "message": "route_name \"xxx\" already exists for language English" } }`
- Invalid character in slug:
  `{ "error": { "message": "route_name includes special character: \"@\"" } }`
- Invalid language:
  `{ "error": { "message": "language must be one of: English, Japanese, Korean, Chinese" } }`

## Practical Guidance

- Prefer `--dry-run` before live publishing when `title` or `route_name` was auto-generated.
- If `category`, `labels`, or `author` do not exist in the CMS database, the API skips them without failing.
- The CMS triggers Strapi `beforeCreate` lifecycles during article creation.
