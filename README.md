# Andrea Tang — Technical Notes

A lightweight, content-first personal site hosted on GitHub Pages. Articles are
authored in Notion and converted to static HTML during the GitHub Actions build.

## Local preview

```bash
python3 scripts/build.py
python3 -m http.server 8000 --directory dist
```

Open `http://localhost:8000`.

## Pages and profile

The homepage is About, with profile text and LinkedIn/GitHub links configured in
`site.json` and biography paragraphs in `content/about.html`. The existing
`/about/` address remains available and points search engines to the homepage.
Writing lives at `/writing/`, with the chronological archive at `/archive/`.
Published article addresses and RSS links stay unchanged.

## Presentation and motion

The site uses a white, text-only layout with persistent desktop navigation and
a compact mobile header. Internal pages transition in place; their original
URLs, metadata, and standard HTML links remain available. Browser history
preserves reading positions, and reduced-motion preferences disable animations.
All styling and motion use local CSS and JavaScript, without added libraries.
Article content continues to come from the existing Notion publishing workflow.

## Notion publishing

Create a Notion data source with these properties:

| Property | Type | Required |
| --- | --- | --- |
| `Title` | Title | Yes |
| `Status` | Status or Select (`Published`) | Yes |
| `Slug` | Rich text | No |
| `Summary` | Rich text | No |
| `Published At` | Date | No |
| `Tags` | Multi-select | No |
| `Featured` | Checkbox | No |

Then add these repository secrets in **Settings → Secrets and variables →
Actions**:

- `NOTION_API_KEY`: the Notion integration token
- `NOTION_DATA_SOURCE_ID`: the data source ID

Share the parent Notion database with the integration. Trigger **Actions →
Build and deploy → Run workflow**, or wait for the scheduled sync.

The integration is read-only: it reads published pages and never modifies
Notion.
