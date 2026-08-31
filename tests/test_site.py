import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = load_module("site_build", "scripts/build.py")
notion = load_module("notion_sync", "scripts/sync_notion.py")


class BuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run([sys.executable, "scripts/build.py"], cwd=ROOT, check=True)

    def test_expected_pages_and_metadata_exist(self):
        expected = [
            "index.html", "about/index.html", "archive/index.html",
            "favicon.ico", "feed.xml", "sitemap.xml", "search.json",
        ]
        for relative in expected:
            self.assertTrue((ROOT / "dist" / relative).exists(), relative)
        homepage = (ROOT / "dist/index.html").read_text()
        self.assertIn("Andrea Tang", homepage)
        self.assertIn('rel="canonical"', homepage)

    def test_search_index_matches_generated_post_pages(self):
        data = json.loads((ROOT / "dist/search.json").read_text())
        self.assertTrue(data, "search index should contain at least one post")
        for post in data:
            self.assertRegex(post["url"], r"^/posts/[a-z0-9-]+/$")
            generated = ROOT / "dist" / post["url"].lstrip("/") / "index.html"
            self.assertTrue(generated.exists(), post["url"])

    def test_dual_reading_modes_are_rendered_when_coffee_content_exists(self):
        article = (ROOT / "dist/posts/a-place-for-durable-thoughts/index.html").read_text()
        self.assertIn('data-reading-mode="coffee"', article)
        self.assertIn('data-reading-mode="long"', article)
        self.assertIn('data-reading-panel="coffee"', article)
        self.assertIn('data-reading-panel="long"', article)

    def test_unsafe_slug_is_rejected(self):
        self.assertFalse(build.re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", "../bad"))

    def test_literal_template_syntax_in_article_does_not_break_render(self):
        self.assertEqual(build.render("<p>{{content}}</p>", {"content": "{{name}}"}),
                         "<p>{{name}}</p>")


class NotionConversionTests(unittest.TestCase):
    def test_rich_text_escapes_markup_and_rejects_script_urls(self):
        result = notion.rich_text([{
            "plain_text": "<script>",
            "href": "javascript:alert(1)",
            "annotations": {"bold": True},
        }])
        self.assertEqual(result, "<strong>&lt;script&gt;</strong>")

    def test_image_fetch_rejects_local_network(self):
        with self.assertRaises(ValueError):
            notion.validated_image_url("https://127.0.0.1/private.png")

    def test_blocks_render_headings_lists_and_tables(self):
        blocks = [
            {"id": "heading-id", "type": "heading_2", "heading_2": {
                "rich_text": [{"plain_text": "A heading", "annotations": {}}]
            }},
            {"id": "list-id", "type": "bulleted_list_item", "bulleted_list_item": {
                "rich_text": [{"plain_text": "An item", "annotations": {}}]
            }},
            {"id": "table-id", "type": "table", "table": {"has_column_header": True},
             "_children": [{"type": "table_row", "table_row": {"cells": [
                 [{"plain_text": "Column", "annotations": {}}]
             ]}}]},
        ]
        result = notion.render_blocks(blocks, "page-id")
        self.assertIn('<h2 id="a-heading">A heading</h2>', result)
        self.assertIn("<ul><li>An item</li></ul>", result)
        self.assertIn("<table><tr><th>Column</th></tr></table>", result)

    def test_nested_notion_media_url_is_rendered(self):
        blocks = [{
            "id": "file-id", "type": "file", "file": {
                "type": "external",
                "external": {"url": "https://example.com/paper.pdf"},
                "caption": [{"plain_text": "Paper", "annotations": {}}],
            }
        }]
        result = notion.render_blocks(blocks, "page-id")
        self.assertIn('href="https://example.com/paper.pdf"', result)
        self.assertIn(">Paper</a>", result)

    def test_coffee_toggle_is_split_from_long_read(self):
        page = {
            "id": "page-id",
            "created_time": "2026-08-31T00:00:00Z",
            "last_edited_time": "2026-08-31T00:00:00Z",
            "properties": {
                "Title": {"type": "title", "title": [{"plain_text": "Two Versions"}]},
                "Status": {"type": "status", "status": {"name": "Published"}},
            },
        }
        blocks = [
            {"id": "coffee", "type": "toggle", "toggle": {
                "rich_text": [{"plain_text": "Coffee Time"}]}, "_children": [
                {"id": "short", "type": "paragraph", "paragraph": {
                    "rich_text": [{"plain_text": "Short version", "annotations": {}}]}}
            ]},
            {"id": "long", "type": "paragraph", "paragraph": {
                "rich_text": [{"plain_text": "Long version", "annotations": {}}]}},
        ]
        original = notion.block_children
        notion.block_children = lambda _page_id: blocks
        try:
            post = notion.page_to_post(page)
        finally:
            notion.block_children = original
        self.assertIn("Short version", post["coffee_html"])
        self.assertNotIn("Short version", post["content_html"])
        self.assertIn("Long version", post["content_html"])


if __name__ == "__main__":
    unittest.main()
