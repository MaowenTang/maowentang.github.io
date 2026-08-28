# Andrea Tang — Technical Notes

A lightweight, content-first personal site hosted on GitHub Pages. Articles are
authored in Notion and converted to static HTML during the GitHub Actions build.

## Local preview

```bash
python3 scripts/build.py
python3 -m http.server 8000 --directory dist
```

Open `http://localhost:8000`.

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
