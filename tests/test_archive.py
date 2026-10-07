import importlib.util
from html.parser import HTMLParser
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("archive_build", ROOT / "scripts/build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class Markup(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
            "meta", "param", "source", "track", "wbr"}

    def __init__(self, source):
        super().__init__()
        self.nodes = []
        self.stack = []
        self.nested_links = False
        self.feed(source)

    def handle_starttag(self, tag, attributes):
        if tag == "a" and any(node["tag"] == "a" for node in self.stack):
            self.nested_links = True
        node = {"tag": tag, "attrs": dict(attributes), "text": "", "parents": self.stack[:]}
        self.nodes.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1]["tag"] == tag:
            self.stack.pop()

    def handle_data(self, text):
        for node in self.stack:
            node["text"] += text

    def with_attribute(self, name):
        return [node for node in self.nodes if name in node["attrs"]]

    def with_class(self, name):
        return [node for node in self.nodes if name in node["attrs"].get("class", "").split()]


def post(slug, published_at, tags, title=None, summary="A useful summary."):
    return {"slug": slug, "title": title or slug.title(), "published_at": published_at,
            "summary": summary, "tags": tags, "content_html": "<p>Body-only search sentinel.</p>"}


class ArchiveTests(unittest.TestCase):
    def mixed_posts(self):
        return [
            post("older", "2025-12-02", []),
            post("first-on-day", "2026-08-10", ["Writing", " writing ", "Essay", "essay"]),
            post("newest", "2026-09-01", ["Essay"]),
            post("second-on-day", "2026-08-10", [" "]),
        ]

    def test_year_month_groups_counts_and_existing_post_order(self):
        posts = self.mixed_posts()
        original = json.dumps(posts)
        page = Markup(build.render_archive(posts))
        self.assertEqual(json.dumps(posts), original)
        years = page.with_attribute("data-archive-year-group")
        months = page.with_attribute("data-archive-month-group")
        self.assertEqual([node["attrs"]["data-archive-year-group"] for node in years], ["2026", "2025"])
        self.assertEqual([node["attrs"]["data-archive-month-group"] for node in months],
                         ["2026-09", "2026-08", "2025-12"])
        counts = page.with_attribute("data-archive-group-count")
        self.assertEqual([node["text"] for node in counts], ["3", "1", "2", "1", "1"])
        self.assertEqual([node["attrs"]["href"] for node in page.with_class("archive-entry-title")], [
            "/posts/newest/", "/posts/first-on-day/", "/posts/second-on-day/", "/posts/older/",
        ])
        self.assertEqual([node["text"] for node in page.with_class("archive-entry-date")],
                         ["September 1", "August 10", "August 10", "December 2"])
        self.assertEqual([node["tag"] for node in page.with_class("archive-year")], ["h3", "h3"])
        self.assertEqual([node["tag"] for node in page.with_class("archive-month")], ["h4"] * 3)
        legacy = Markup(build.render_archive(posts, standalone=True))
        self.assertEqual([node["tag"] for node in legacy.with_class("archive-year")], ["h2", "h2"])
        self.assertEqual([node["tag"] for node in legacy.with_class("archive-month")], ["h3"] * 3)
        options = [node for node in page.nodes if node["tag"] == "option" and node["attrs"].get("value")]
        self.assertEqual([(node["attrs"]["value"], node["text"]) for node in options],
                         [("2026", "2026 (3)"), ("2025", "2025 (1)")])

    def test_topic_counts_deduplicate_article_tags_and_keep_untagged_articles(self):
        page = Markup(build.render_archive(self.mixed_posts()))
        filters = page.with_attribute("data-archive-filter")
        self.assertEqual([(node["attrs"]["data-archive-filter"], node["text"]) for node in filters],
                         [("", "All 4"), ("essay", "Essay 2"), ("writing", "Writing 1")])
        self.assertEqual(page.with_attribute("data-archive-untagged")[0]["text"], "Untagged 2")
        entries = page.with_attribute("data-archive-entry")
        self.assertEqual([json.loads(node["attrs"]["data-tags"]) for node in entries],
                         [["essay"], ["essay", "writing"], [], []])
        self.assertEqual(len(entries), 4)
        same_name = Markup(build.render_archive([post("named", "2026-01-02", ["Untagged"]),
                                                post("none", "2026-01-01", [])]))
        self.assertEqual([node["attrs"]["data-archive-filter"] for node in same_name.with_attribute("data-archive-filter")],
                         ["", "untagged"])
        self.assertEqual(len(same_name.with_attribute("data-archive-untagged")), 1)

    def test_search_uses_escaped_metadata_and_tag_links_are_separate(self):
        tags = ["C++", 'a" onclick="bad', "水"]
        title = '<script>alert("x")</script> ＡＩ'
        summary = '  Data  & "Quality" <b>notes</b> '
        source = build.render_archive([post("safe-post", "2026-08-28", tags, title, summary)])
        page = Markup(source)
        entry = page.with_attribute("data-archive-entry")[0]
        self.assertEqual(json.loads(entry["attrs"]["data-tags"]), sorted(tag.casefold() for tag in tags))
        self.assertIn('data & "quality" <b>notes</b>', entry["attrs"]["data-search"])
        self.assertIn(" ai ", entry["attrs"]["data-search"])
        self.assertNotIn("body-only", entry["attrs"]["data-search"])
        self.assertNotIn("<script>", source)
        self.assertFalse(any("onclick" in node["attrs"] for node in page.nodes))
        self.assertEqual(page.with_class("archive-entry-title")[0]["text"], title)
        self.assertEqual(page.with_class("archive-entry-summary")[0]["text"], summary)
        self.assertEqual(len(page.with_class("tag")), 3)
        self.assertFalse(page.nested_links)

    def test_tag_paths_preserve_common_urls_without_colliding_on_punctuation(self):
        self.assertEqual(build.tag_path("Writing"), "/tags/writing/")
        self.assertEqual(build.tag_path(" Essay "), "/tags/essay/")
        self.assertEqual(build.tag_path("Machine  Learning"), build.tag_path(" machine learning "))
        names = ["C++", "C#", "C", "水", "火", "A/B", "A B", "A-B"]
        paths = [build.tag_path(name) for name in names]
        self.assertEqual(len(set(paths)), len(names))
        for path in paths:
            self.assertRegex(path, r"^/tags/[a-z0-9-]+/$")
            self.assertNotIn("..", path)
        hashed_slug = build.tag_path("C++").split("/")[2]
        self.assertNotEqual(build.tag_path(hashed_slug), build.tag_path("C++"))

    def test_tag_links_match_generated_pages_and_duplicate_labels_do_not_repeat_posts(self):
        posts = [post("first", "2026-08-28", ["Writing", " writing ", "C++", "C#", "水"]),
                 post("second", "2026-08-27", ["WRITING", "A/B", "A B", "A-B"])]
        config = json.loads((ROOT / "site.json").read_text())
        with tempfile.TemporaryDirectory() as directory, patch.object(build, "DIST", Path(directory)):
            build.build_tags(config, posts)
            for item in posts:
                for link in Markup(build.tags_html(item["tags"])).with_class("tag"):
                    target = Path(directory) / link["attrs"]["href"].lstrip("/") / "index.html"
                    self.assertTrue(target.is_file(), link["attrs"]["href"])
            writing = Markup((Path(directory) / "tags/writing/index.html").read_text())
            self.assertEqual([node["attrs"]["href"] for node in writing.with_class("post-card")],
                             ["/posts/first/", "/posts/second/"])
            self.assertEqual(len(list((Path(directory) / "tags").glob("*/index.html"))), 7)

    def test_empty_archive_has_a_readable_message_and_zero_count(self):
        source = build.render_archive([])
        page = Markup(source)
        self.assertIn("No published articles yet.", source)
        self.assertEqual(page.with_attribute("data-archive-entry"), [])
        self.assertEqual(page.with_attribute("data-archive-year-group"), [])
        self.assertEqual(page.with_attribute("data-archive-filter")[0]["text"], "All 0")
        self.assertEqual(page.with_attribute("data-archive-untagged"), [])


if __name__ == "__main__":
    unittest.main()
