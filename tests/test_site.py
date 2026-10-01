import importlib.util
import html
from html.parser import HTMLParser
import io
import json
import subprocess
import sys
import tempfile
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
        self.section_ids = []
        self.heading_tags = []
        self.navigation_links = []
        self.in_navigation = False
        self.feed(markup)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "nav" and attrs.get("aria-label") == "Primary navigation":
            self.in_navigation = True
        if tag == "a" and self.in_navigation:
            self.navigation_links.append(attrs.get("href"))
        if tag == "a" and attrs.get("aria-current") == "page":
            self.current.append(attrs.get("href"))
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonical = attrs.get("href")
        if "data-page-section" in attrs:
            self.section_ids.append(attrs.get("id"))
        if tag in {"h1", "h2", "h3"}:
            self.heading_tags.append(tag)

    def handle_endtag(self, tag):
        if tag == "nav":
            self.in_navigation = False


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
        self.assertIn("Maowen Tang", homepage)
        self.assertIn('rel="canonical"', homepage)

    def test_home_flows_from_about_to_archive_without_a_writing_page(self):
        config = json.loads((ROOT / "site.json").read_text())
        homepage = (ROOT / "dist/index.html").read_text()
        about_alias = (ROOT / "dist/about/index.html").read_text()
        archive = (ROOT / "dist/archive/index.html").read_text()
        self.assertIn(html.escape(config["profile_name"]), homepage)
        self.assertIn((ROOT / "content/about.html").read_text(), homepage)
        self.assertEqual(homepage, about_alias)
        for markup in (homepage, about_alias, archive):
            self.assertEqual(PageLinks(markup).canonical, config["base_url"] + "/")
            self.assertEqual(PageLinks(markup).heading_tags.count("h1"), 1)
        self.assertEqual(PageLinks(homepage).section_ids, ["about", "archive"])
        self.assertEqual(PageLinks(archive).section_ids, ["archive"])
        self.assertEqual(homepage.count('id="about"'), 1)
        self.assertEqual(homepage.count('id="archive"'), 1)
        self.assertFalse((ROOT / "dist/writing").exists())
        for post in build.load_posts():
            for markup in (homepage, archive):
                self.assertIn(html.escape(post["title"]), markup)
                self.assertIn(f'href="/posts/{post["slug"]}/"', markup)

    def test_navigation_tracks_about_archive_and_articles(self):
        expected = {
            "index.html": "/#about", "about/index.html": "/#about",
            "archive/index.html": "/#archive",
        }
        for directory in ("posts", "tags"):
            for path in (ROOT / "dist" / directory).glob("*/index.html"):
                expected[str(path.relative_to(ROOT / "dist"))] = "/#archive"
        for path, active in expected.items():
            with self.subTest(path=path):
                markup = (ROOT / "dist" / path).read_text()
                self.assertEqual(PageLinks(markup).current, [active])
                self.assertEqual(PageLinks(markup).navigation_links, ["/#about", "/#archive"])
                self.assertIn('href="/#about"', markup)
                self.assertIn('href="/#archive"', markup)
                self.assertNotIn('href="/writing/"', markup)

    def test_article_return_links_go_to_the_homepage_archive(self):
        for post in build.load_posts():
            markup = (ROOT / "dist/posts" / post["slug"] / "index.html").read_text()
            self.assertIn('<a class="back-link" href="/#archive">← Archive</a>', markup)
            self.assertIn('<a href="/#archive">Back to archive →</a>', markup)

    def test_sitemap_lists_canonical_pages_and_rss_keeps_article_urls(self):
        config = json.loads((ROOT / "site.json").read_text())
        base_url = config["base_url"]
        sitemap = ET.parse(ROOT / "dist/sitemap.xml")
        urls = [node.text for node in sitemap.findall(".//{*}loc")]
        self.assertIn(base_url + "/", urls)
        self.assertNotIn(base_url + "/writing/", urls)
        self.assertNotIn(base_url + "/archive/", urls)
        self.assertNotIn(base_url + "/about/", urls)
        expected_posts = [f'{base_url}/posts/{post["slug"]}/' for post in build.load_posts()]
        self.assertEqual(urls, [base_url + "/"] + expected_posts)
        rss = ET.parse(ROOT / "dist/feed.xml")
        self.assertEqual([node.text for node in rss.findall("./channel/item/link")], expected_posts)

    def test_profile_configuration_is_escaped_in_html(self):
        config = json.loads((ROOT / "site.json").read_text())
        config.update({
            "profile_name": '<Name & "Alias">', "profile_focus": "Research < learning",
            "linkedin_url": 'https://example.com/?name="Alias"&topic=<research>',
        })
        with patch.object(build, "write_page") as write:
            build.build_about(config, build.load_posts())
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


class NotionAboutSyncTests(unittest.TestCase):
    ABOUT_ID = "a1234567-b89c-4d01-9234-56789abcdef0"
    ARTICLE_ID = "b1234567-b89c-4d01-9234-56789abcdef0"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "content/posts").mkdir(parents=True)
        self.about_path = self.root / "content/about.html"
        self.old_post = self.root / "content/posts/notion-previous.json"
        self.about_path.write_text("<p>Saved biography.</p>\n")
        self.old_post.write_text("previous generated article\n")
        self.save_config({"notion_about_page_id": self.ABOUT_ID})
        for name, value in (("ROOT", self.root), ("TOKEN", "test-token"),
                            ("DATA_SOURCE_ID", "test-data-source")):
            patcher = patch.object(notion, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.log = io.StringIO()
        output = patch("sys.stdout", self.log)
        output.start()
        self.addCleanup(output.stop)

    def save_config(self, values):
        (self.root / "site.json").write_text(json.dumps(values))

    def page(self, page_id, title="An article", status="Published"):
        return {
            "object": "page", "id": page_id, "archived": False, "in_trash": False,
            "created_time": "2026-10-01T00:00:00Z", "last_edited_time": "2026-10-01T01:00:00Z",
            "properties": {
                "Title": {"type": "title", "title": [{"plain_text": title}]},
                "Status": {"type": "status", "status": {"name": status}},
            },
        }

    def paragraph(self, text):
        return [{"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": text}]}}]

    def assert_saved_content_unchanged(self):
        self.assertEqual(self.about_path.read_text(), "<p>Saved biography.</p>\n")
        self.assertEqual(self.old_post.read_text(), "previous generated article\n")

    def test_about_body_syncs_with_formatting_and_never_exports_as_an_article(self):
        configured_id = self.ABOUT_ID.replace("-", "").upper()
        self.save_config({"notion_about_page_id": configured_id})
        blocks = [{"type": "paragraph", "paragraph": {"rich_text": [
            {"plain_text": "Useful systems", "annotations": {"bold": True}},
            {"plain_text": " & "},
            {"plain_text": "my work", "href": "https://example.com/?a=1&b=2"},
        ]}}]
        for status in ("Draft", "Published"):
            with self.subTest(status=status):
                about = self.page(self.ABOUT_ID, "About Me", status)
                article = self.page(self.ARTICLE_ID)
                with patch.object(notion, "request", return_value=about) as request, \
                        patch.object(notion, "paginated", return_value=[about, article]), \
                        patch.object(notion, "block_children", side_effect=[blocks, self.paragraph("Article body.")]) as children:
                    notion.main()
                request.assert_called_once_with(f"/pages/{configured_id}")
                self.assertEqual(children.call_count, 2)
                self.assertEqual(self.about_path.read_text(),
                                 '<p><strong>Useful systems</strong> &amp; '
                                 '<a href="https://example.com/?a=1&amp;b=2" rel="noreferrer">my work</a></p>\n')
                posts = list((self.root / "content/posts").glob("notion-*.json"))
                self.assertEqual(len(posts), 1)
                self.assertEqual(json.loads(posts[0].read_text())["notion_page_id"], self.ARTICLE_ID)
                self.assertIn("Synced About Me from Notion.", self.log.getvalue())

    def test_inaccessible_about_fails_without_replacing_local_content(self):
        with patch.object(notion, "request", side_effect=RuntimeError("Notion API 404")), \
                patch.object(notion, "paginated") as query:
            with self.assertRaisesRegex(RuntimeError, "Notion API 404"):
                notion.main()
        query.assert_not_called()
        self.assert_saved_content_unchanged()

    def test_biography_heading_ids_do_not_collide_with_homepage_sections(self):
        blocks = [{"id": "heading-block", "type": "heading_2", "heading_2": {
            "rich_text": [{"plain_text": "Archive"}],
        }}]
        with patch.object(notion, "request", return_value=self.page(self.ABOUT_ID)), \
                patch.object(notion, "block_children", return_value=blocks):
            biography = notion.read_about(self.ABOUT_ID)
        self.assertEqual(biography, '<h2 id="about-content-archive">Archive</h2>')
        self.assertEqual(notion.render_blocks(blocks, self.ARTICLE_ID),
                         '<h2 id="archive">Archive</h2>')
        config = json.loads((ROOT / "site.json").read_text())
        original_load = build.load
        with patch.object(build, "load", side_effect=lambda path:
                          biography if path == ROOT / "content/about.html" else original_load(path)), \
                patch.object(build, "write_page") as write:
            build.build_about(config, [])
        homepage = write.call_args_list[0].args[1]
        self.assertEqual(homepage.count('id="archive"'), 1)
        self.assertEqual(homepage.count('id="about-content-archive"'), 1)

    def test_archived_or_trashed_about_fails_without_replacing_local_content(self):
        for flag in ("archived", "in_trash"):
            with self.subTest(flag=flag):
                about = self.page(self.ABOUT_ID)
                about[flag] = True
                with patch.object(notion, "request", return_value=about), \
                        patch.object(notion, "block_children") as children:
                    with self.assertRaisesRegex(RuntimeError, "unavailable or archived"):
                        notion.main()
                children.assert_not_called()
                self.assert_saved_content_unchanged()

    def test_empty_about_fails_instead_of_silently_reusing_saved_biography(self):
        for blocks in ([], self.paragraph(" \n "), [{"type": "unsupported"}]):
            with self.subTest(blocks=blocks), \
                    patch.object(notion, "request", return_value=self.page(self.ABOUT_ID)), \
                    patch.object(notion, "block_children", return_value=blocks), \
                    patch.object(notion, "paginated") as query:
                with self.assertRaisesRegex(RuntimeError, "no readable body text"):
                    notion.main()
                query.assert_not_called()
                self.assert_saved_content_unchanged()

    def test_invalid_about_id_fails_before_network_or_content_changes(self):
        for invalid in (123, "https://notion.so/a-page", "../../other-page", "not-a-page-id"):
            with self.subTest(page_id=invalid):
                self.save_config({"notion_about_page_id": invalid})
                with patch.object(notion, "request") as request:
                    with self.assertRaisesRegex(ValueError, "notion_about_page_id"):
                        notion.main()
                request.assert_not_called()
                self.assert_saved_content_unchanged()

    def test_article_read_failure_also_preserves_the_biography_and_old_articles(self):
        with patch.object(notion, "request", return_value=self.page(self.ABOUT_ID)), \
                patch.object(notion, "paginated", return_value=[self.page(self.ARTICLE_ID)]), \
                patch.object(notion, "block_children", side_effect=[self.paragraph("Updated biography."), RuntimeError("Article access failed")]):
            with self.assertRaisesRegex(RuntimeError, "Article access failed"):
                notion.main()
        self.assert_saved_content_unchanged()

    def test_missing_about_configuration_preserves_legacy_article_only_sync(self):
        for config in ({}, {"notion_about_page_id": ""}):
            with self.subTest(config=config):
                self.save_config(config)
                with patch.object(notion, "request") as request, \
                        patch.object(notion, "paginated", return_value=[self.page(self.ARTICLE_ID)]), \
                        patch.object(notion, "block_children", return_value=self.paragraph("Article body.")):
                    notion.main()
                request.assert_not_called()
                self.assertEqual(self.about_path.read_text(), "<p>Saved biography.</p>\n")
                posts = list((self.root / "content/posts").glob("notion-*.json"))
                self.assertEqual(len(posts), 1)
                self.assertEqual(json.loads(posts[0].read_text())["notion_page_id"], self.ARTICLE_ID)

    def test_missing_credentials_retains_all_local_fallback_content(self):
        with patch.object(notion, "TOKEN", ""), patch.object(notion, "request") as request, \
                patch.object(notion, "paginated") as query:
            notion.main()
        request.assert_not_called()
        query.assert_not_called()
        self.assert_saved_content_unchanged()


if __name__ == "__main__":
    unittest.main()
