import importlib.util
import html
from html.parser import HTMLParser
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = load_module("site_build", "scripts/build.py")
notion = load_module("notion_sync", "scripts/sync_notion.py")


class PageLinks(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.current = []
        self.canonical = None
        self.feed(markup)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "a" and attrs.get("aria-current") == "page":
            self.current.append(attrs.get("href"))
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonical = attrs.get("href")


class BuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run([sys.executable, "scripts/build.py"], cwd=ROOT, check=True)

    def test_expected_pages_and_metadata_exist(self):
        expected = [
            "index.html", "about/index.html", "writing/index.html", "archive/index.html",
            "favicon.ico", "feed.xml", "sitemap.xml", "search.json",
        ]
        for relative in expected:
            self.assertTrue((ROOT / "dist" / relative).exists(), relative)
        homepage = (ROOT / "dist/index.html").read_text()
        self.assertIn("Andrea Tang", homepage)
        self.assertIn('rel="canonical"', homepage)

    def test_about_is_home_and_writing_has_its_own_address(self):
        config = json.loads((ROOT / "site.json").read_text())
        homepage = (ROOT / "dist/index.html").read_text()
        about_alias = (ROOT / "dist/about/index.html").read_text()
        writing = (ROOT / "dist/writing/index.html").read_text()
        self.assertIn(html.escape(config["profile_name"]), homepage)
        self.assertIn((ROOT / "content/about.html").read_text(), homepage)
        self.assertEqual(homepage, about_alias)
        self.assertEqual(PageLinks(homepage).canonical, config["base_url"] + "/")
        self.assertEqual(PageLinks(writing).canonical, config["base_url"] + "/writing/")
        self.assertIn("A Piece", writing)
        self.assertNotIn("A Piece<br>", homepage)
        for post in build.load_posts():
            self.assertIn(html.escape(post["title"]), writing)

    def test_navigation_tracks_about_writing_archive_and_articles(self):
        expected = {
            "index.html": "/", "about/index.html": "/",
            "writing/index.html": "/writing/", "archive/index.html": "/archive/",
        }
        for directory in ("posts", "tags"):
            for path in (ROOT / "dist" / directory).glob("*/index.html"):
                expected[str(path.relative_to(ROOT / "dist"))] = "/writing/"
        for path, active in expected.items():
            with self.subTest(path=path):
                markup = (ROOT / "dist" / path).read_text()
                self.assertEqual(PageLinks(markup).current, [active])

    def test_article_return_links_go_to_writing(self):
        for post in build.load_posts():
            markup = (ROOT / "dist/posts" / post["slug"] / "index.html").read_text()
            self.assertIn('<a class="back-link" href="/writing/">← Writing</a>', markup)
            self.assertIn('<a href="/writing/">More writing →</a>', markup)

    def test_sitemap_lists_canonical_pages_and_rss_keeps_article_urls(self):
        config = json.loads((ROOT / "site.json").read_text())
        base_url = config["base_url"]
        sitemap = ET.parse(ROOT / "dist/sitemap.xml")
        urls = [node.text for node in sitemap.findall(".//{*}loc")]
        self.assertIn(base_url + "/", urls)
        self.assertIn(base_url + "/writing/", urls)
        self.assertIn(base_url + "/archive/", urls)
        self.assertNotIn(base_url + "/about/", urls)
        expected_posts = [f'{base_url}/posts/{post["slug"]}/' for post in build.load_posts()]
        self.assertTrue(set(expected_posts).issubset(urls))
        rss = ET.parse(ROOT / "dist/feed.xml")
        self.assertEqual([node.text for node in rss.findall("./channel/item/link")], expected_posts)

    def test_profile_configuration_is_escaped_in_html(self):
        config = json.loads((ROOT / "site.json").read_text())
        config.update({
            "profile_name": '<Name & "Alias">', "profile_focus": "Research < learning",
            "linkedin_url": 'https://example.com/?name="Alias"&topic=<research>',
        })
        with patch.object(build, "write_page") as write:
            build.build_about(config)
        markup = write.call_args_list[0].args[1]
        self.assertIn(html.escape(config["profile_name"]), markup)
        self.assertIn(html.escape(config["profile_focus"]), markup)
        self.assertIn(f'href="{html.escape(config["linkedin_url"], quote=True)}"', markup)
        self.assertNotIn(config["profile_name"], markup)

    def test_search_index_matches_generated_post_pages(self):
        data = json.loads((ROOT / "dist/search.json").read_text())
        self.assertTrue(data, "search index should contain at least one post")
        for post in data:
            self.assertRegex(post["url"], r"^/posts/[a-z0-9-]+/$")
            generated = ROOT / "dist" / post["url"].lstrip("/") / "index.html"
            self.assertTrue(generated.exists(), post["url"])

    def test_dual_reading_modes_are_rendered_when_coffee_content_exists(self):
        experience, default_minutes = build.reading_experience({
            "coffee_html": "<p>Short version.</p>",
            "content_html": "<p>Long version.</p>",
        })
        self.assertEqual(default_minutes, 1)
        self.assertIn('data-reading-mode="coffee"', experience)
        self.assertIn('data-reading-mode="long"', experience)
        self.assertIn('data-reading-panel="coffee"', experience)
        self.assertIn('data-reading-panel="long"', experience)

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
