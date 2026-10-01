# Maowen Tang — Technical Notes

A lightweight, content-first personal site hosted on GitHub Pages. Articles and
the About Me biography can be authored in Notion and converted to static HTML
during the GitHub Actions build.

## Local preview

```bash
python3 scripts/build.py
python3 -m http.server 8000 --directory dist
```

Open `http://localhost:8000`.

## Pages and profile

The homepage starts with About and continues directly into the chronological
Archive. Navigation links scroll to `/#about` and `/#archive`; there is no
separate Writing page. The display name and LinkedIn/GitHub links
are configured in `site.json`. Biography paragraphs are synced from the Notion
page configured as `notion_about_page_id`; `content/about.html` is the local
fallback when previewing without Notion credentials. The existing
`/about/` and `/archive/` addresses remain available and point search engines to
the homepage. Published article addresses and RSS links stay unchanged.

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
Build and deploy → Run workflow**, or wait for the scheduled sync, configured
every six hours at minute 17 (UTC). GitHub may delay scheduled runs. Changes
appear after that workflow successfully builds and deploys.

### Editing About Me

Open the dedicated **About Me** record in the same shared Notion database and
edit its page body. Paragraphs, links, and supported formatting use the same
converter as articles. Its database `Status` is ignored: the biography syncs
even while Draft, and that record is excluded from articles, Archive, and RSS
even if set to Published. The website heading, name, and profile
links remain configured separately in `site.json`.

Current editor: [About Me in Notion](https://www.notion.so/3ec86f31679a80dcbce6c8479891d6a5).

`notion_about_page_id` in `site.json` identifies this record by its page ID,
with or without hyphens. It is not a secret and requires no additional token;
the existing integration must have access to the record. A configured page
that is inaccessible, archived, in the trash, or has no readable body text
fails the sync and prevents deployment of that run. The script finishes all
Notion reads before replacing generated articles or the biography.

Without Notion credentials, local preview keeps the saved biography and local
article content. If `notion_about_page_id` is absent or empty, only articles
sync and the saved biography remains unchanged. Successful logs distinguish
`Synced About Me from Notion.` from the missing-credentials fallback message.

For a live sync check without publication, run **Build and deploy** with
`validate_only` enabled. This still reads Notion, builds the site, runs tests,
and uploads the preview artifact. Deployment is restricted to `main` runs with
that option disabled. Validation runs use a separate concurrency group from
production deployments.

The integration is read-only: it reads the configured biography and published
articles and never modifies Notion.
