#!/usr/bin/env python3
"""Build Maowen Tang's static site using only the Python standard library."""

from __future__ import annotations

import datetime as dt
import html
import json
import re
import shutil
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def load(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def render(template: str, values: dict[str, object]) -> str:
    missing = sorted(
        set(re.findall(r"{{([a-zA-Z0-9_]+)}}", template)) - values.keys()
    )
    if missing:
        raise ValueError(f"Missing template values: {', '.join(missing)}")
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", str(value))
    return template


def clean_text(markup: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", markup)).strip()


def date_value(value: str) -> dt.date:
    return dt.date.fromisoformat(value[:10])


def date_display(value: str) -> str:
    return date_value(value).strftime("%B %-d, %Y")


def reading_time(markup: str) -> int:
    words = re.findall(r"[A-Za-z0-9]+|[\u3400-\u9fff]", clean_text(markup))
    return max(1, round(len(words) / 220))


def nav_html(config: dict, current: str) -> str:
    if current in {"/", "/about/"}:
        current = "/#about"
    elif current == "/archive/" or current.startswith(("/posts/", "/tags/")):
        current = "/#archive"
    links = []
    for item in config["nav"]:
        active = current == item["url"]
        aria = ' aria-current="page"' if active else ""
        links.append(
            f'<a href="{html.escape(item["url"], quote=True)}"{aria}>'
            f'{html.escape(item["label"])}</a>'
        )
    return "".join(links)


def base_page(config: dict, body: str, *, page_title: str, description: str,
              path: str, og_type: str = "website", canonical_path: str | None = None) -> str:
    canonical = config["base_url"].rstrip("/") + (canonical_path or path)
    return render(load(ROOT / "templates/base.html"), {
        **config,
        "page_title": html.escape(page_title),
        "page_description": html.escape(description, quote=True),
        "canonical_url": html.escape(canonical, quote=True),
        "og_type": og_type,
        "nav_html": nav_html(config, path),
        "content": body,
        "year": dt.date.today().year,
    })


def write_page(relative: str, content: str) -> None:
    target = DIST / relative.lstrip("/")
    if target.suffix != ".html":
        target /= "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def load_posts() -> list[dict]:
    posts: list[dict] = []
    for path in sorted((ROOT / "content/posts").glob("*.json")):
        post = json.loads(load(path))
        required = {"title", "slug", "summary", "published_at", "content_html"}
        missing = required - post.keys()
        if missing:
            raise ValueError(f"{path}: missing {', '.join(sorted(missing))}")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", post["slug"]):
            raise ValueError(f"{path}: unsafe slug {post['slug']!r}")
        post.setdefault("tags", [])
        post.setdefault("featured", False)
        posts.append(post)
    if any(post.get("source") == "notion" for post in posts):
        posts = [post for post in posts if not post.get("sample")]
    return sorted(posts, key=lambda post: post["published_at"], reverse=True)


def post_card(post: dict) -> str:
    return (
        f'<a class="post-card" href="/posts/{post["slug"]}/">'
        f'<time class="post-date" datetime="{post["published_at"][:10]}">'
        f'{date_display(post["published_at"])}</time>'
        f'<div class="post-copy"><h3>{html.escape(post["title"])}</h3>'
        f'<p>{html.escape(post["summary"])}</p></div>'
        '<span class="post-arrow" aria-hidden="true">→</span></a>'
    )


def toc_for(markup: str) -> str:
    rows = []
    pattern = r'<h([23])\s+id="([^"]+)"[^>]*>(.*?)</h\1>'
    for level, anchor, label in re.findall(pattern, markup, flags=re.I | re.S):
        rows.append(
            f'<a data-level="{level}" href="#{html.escape(anchor, quote=True)}">'
            f'{html.escape(clean_text(label))}</a>'
        )
    return "".join(rows)


def tags_html(tags: list[str]) -> str:
    links = "".join(
        f'<a class="tag" href="/tags/{quote(tag.lower().replace(" ", "-"))}/">'
        f'{html.escape(tag)}</a>' for tag in tags
    )
    return f'<div class="tags">{links}</div>'


def reading_experience(post: dict) -> tuple[str, int]:
    long_content = post["content_html"]
    coffee_content = post.get("coffee_html", "").strip()
    long_minutes = reading_time(long_content)
    coffee_minutes = reading_time(coffee_content) if coffee_content else None
    if coffee_content:
        reading_switcher = (
            '<div class="reading-switcher" role="tablist" aria-label="Reading version">'
            f'<button type="button" role="tab" aria-selected="true" data-reading-mode="coffee" data-reading-minutes="{coffee_minutes}">'
            f'<span>Coffee Time</span><small>{coffee_minutes} min</small></button>'
            f'<button type="button" role="tab" aria-selected="false" data-reading-mode="long" data-reading-minutes="{long_minutes}">'
            f'<span>Long Read</span><small>{long_minutes} min</small></button></div>'
        )
        coffee_toc = f'<div data-reading-toc="coffee">{toc_for(coffee_content)}</div>'
        long_toc = f'<div data-reading-toc="long" hidden>{toc_for(long_content)}</div>'
        panels = (
            f'<div class="prose" data-reading-panel="coffee">{coffee_content}</div>'
            f'<div class="prose" data-reading-panel="long" hidden>{long_content}</div>'
        )
        default_minutes = coffee_minutes
    else:
        reading_switcher = ""
        coffee_toc = ""
        long_toc = toc_for(long_content)
        panels = f'<div class="prose">{long_content}</div>'
        default_minutes = long_minutes
    experience = (
        f'{reading_switcher}<div class="article-layout">'
        f'<aside class="toc" aria-label="On this page">{coffee_toc}{long_toc}</aside>'
        f'<div class="reading-panels">{panels}</div></div>'
    )
    return experience, default_minutes


def build_posts(config: dict, posts: list[dict]) -> None:
    template = load(ROOT / "templates/post.html")
    for post in posts:
        experience, default_minutes = reading_experience(post)
        body = render(template, {
            "post_title": html.escape(post["title"]),
            "summary": html.escape(post["summary"]),
            "date_iso": post["published_at"][:10],
            "date_display": date_display(post["published_at"]),
            "default_reading_time": default_minutes,
            "reading_experience": experience,
            "tags_html": tags_html(post["tags"]),
        })
        path = f'/posts/{post["slug"]}/'
        write_page(path, base_page(
            config, body,
            page_title=f'{post["title"]} — {config["title"]}',
            description=post["summary"], path=path, og_type="article"
        ))


def render_archive(posts: list[dict], standalone: bool = False) -> str:
    chunks: list[str] = []
    active_year = None
    year_tag = "h2" if standalone else "h3"
    for post in posts:
        date = date_value(post["published_at"])
        if date.year != active_year:
            active_year = date.year
            chunks.append(f'<{year_tag} class="archive-year">{active_year}</{year_tag}>')
        chunks.append(
            f'<a class="archive-row" href="/posts/{post["slug"]}/">'
            f'<time datetime="{date.isoformat()}">{date.strftime("%b %-d")}</time>'
            f'<strong>{html.escape(post["title"])}</strong></a>'
        )
    return render(load(ROOT / "templates/archive.html"), {
        "archive_heading_tag": "h1" if standalone else "h2",
        "archive_rows": "".join(chunks),
    })


def build_archive(config: dict, posts: list[dict]) -> None:
    body = render_archive(posts, standalone=True)
    write_page("/archive/", base_page(
        config, body, page_title=f'Archive — {config["title"]}',
        description=f'All writing by {config["author"]}.', path="/archive/", canonical_path="/"
    ))


def build_about(config: dict, posts: list[dict]) -> None:
    profile_links = "".join(
        f'<a href="{html.escape(config[key], quote=True)}" rel="noreferrer">{label}</a>'
        for key, label in (("linkedin_url", "LinkedIn"), ("github_url", "GitHub"))
        if config.get(key)
    )
    body = render(load(ROOT / "templates/about.html"), {
        "profile_name": html.escape(config["profile_name"]),
        "profile_links": profile_links,
        "about_content": load(ROOT / "content/about.html"),
        "archive_content": render_archive(posts),
    })
    page = base_page(
        config, body, page_title=config["title"],
        description=f'About {config["profile_name"]}.', path="/"
    )
    write_page("/index.html", page)
    write_page("/about/", page)


def build_tags(config: dict, posts: list[dict]) -> None:
    by_tag: dict[str, list[dict]] = {}
    for post in posts:
        for tag in post["tags"]:
            by_tag.setdefault(tag, []).append(post)
    for tag, tagged_posts in by_tag.items():
        body = (
            f'<section class="page-head"><p class="eyebrow">Topic</p><h1>{html.escape(tag)}</h1></section>'
            f'<section class="writing"><div class="post-list">'
            f'{"".join(post_card(post) for post in tagged_posts)}</div></section>'
        )
        slug = quote(tag.lower().replace(" ", "-"))
        path = f"/tags/{slug}/"
        write_page(path, base_page(
            config, body, page_title=f'{tag} — {config["title"]}',
            description=f'Writing about {tag}.', path=path
        ))


def build_machine_files(config: dict, posts: list[dict]) -> None:
    items = []
    for post in posts:
        url = f'{config["base_url"]}/posts/{post["slug"]}/'
        items.append(
            "<item>"
            f"<title>{html.escape(post['title'])}</title>"
            f"<link>{url}</link><guid>{url}</guid>"
            f"<pubDate>{date_value(post['published_at']).strftime('%a, %d %b %Y 00:00:00 +0000')}</pubDate>"
            f"<description>{html.escape(post['summary'])}</description></item>"
        )
    rss = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel>'
        f'<title>{html.escape(config["title"])}</title>'
        f'<link>{config["base_url"]}</link>'
        f'<description>{html.escape(config["description"])}</description>'
        f'{"".join(items)}</channel></rss>'
    )
    (DIST / "feed.xml").write_text(rss, encoding="utf-8")

    paths = ["/"] + [f'/posts/{p["slug"]}/' for p in posts]
    sitemap = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(
        f'<url><loc>{config["base_url"]}{path}</loc></url>' for path in paths
    ) + "</urlset>"
    (DIST / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    (DIST / "robots.txt").write_text(f'User-agent: *\nAllow: /\nSitemap: {config["base_url"]}/sitemap.xml\n', encoding="utf-8")
    search = [{
        "title": p["title"], "summary": p["summary"], "tags": p["tags"],
        "url": f'/posts/{p["slug"]}/'
    } for p in posts]
    (DIST / "search.json").write_text(json.dumps(search, ensure_ascii=False), encoding="utf-8")
    (DIST / ".nojekyll").touch()


def main() -> None:
    config = json.loads(load(ROOT / "site.json"))
    posts = load_posts()
    if not posts:
        raise SystemExit("No published posts found")
    if DIST.exists():
        shutil.rmtree(DIST)
    shutil.copytree(ROOT / "assets", DIST / "assets")
    shutil.copy2(ROOT / "assets/favicon.svg", DIST / "favicon.svg")
    shutil.copy2(ROOT / "assets/favicon.ico", DIST / "favicon.ico")
    notion_assets = ROOT / "static/notion"
    if notion_assets.exists():
        shutil.copytree(notion_assets, DIST / "assets/notion", dirs_exist_ok=True)
    build_about(config, posts)
    build_posts(config, posts)
    build_archive(config, posts)
    build_tags(config, posts)
    build_machine_files(config, posts)
    print(f"Built {len(posts)} post(s) into {DIST}")


if __name__ == "__main__":
    main()
