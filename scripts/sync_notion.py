#!/usr/bin/env python3
"""Read published Notion pages and store safe, build-ready article JSON."""

from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.notion.com/v1"
VERSION = "2026-03-11"
TOKEN = os.environ.get("NOTION_API_KEY", "").strip()
DATA_SOURCE_ID = os.environ.get("NOTION_DATA_SOURCE_ID", "").strip()
MAX_IMAGE_BYTES = 12 * 1024 * 1024
IMAGE_TYPES = {
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def request(path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API + path,
        data=data,
        method="POST" if data is not None else "GET",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Notion-Version": VERSION,
            "Content-Type": "application/json",
            "User-Agent": "AndreaTangSite/1.0",
        },
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 429 and attempt < 3:
                time.sleep(int(error.headers.get("Retry-After", "1")))
                continue
            detail = error.read().decode(errors="replace")
            raise RuntimeError(f"Notion API {error.code}: {detail}") from error
    raise RuntimeError("Notion API request exhausted retries")


def paginated(path: str, body: dict | None = None) -> list[dict]:
    results: list[dict] = []
    cursor = None
    while True:
        if body is not None:
            payload = {**body, "page_size": 100}
            if cursor:
                payload["start_cursor"] = cursor
            data = request(path, payload)
        else:
            suffix = "?page_size=100"
            if cursor:
                suffix += "&start_cursor=" + urllib.parse.quote(cursor)
            data = request(path + suffix)
        results.extend(data.get("results", []))
        if not data.get("has_more"):
            return results
        cursor = data["next_cursor"]


def safe_url(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https", "mailto"}:
        return ""
    return html.escape(value, quote=True)


def validated_image_url(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("image URL must be public HTTPS")
    if parsed.port not in {None, 443}:
        raise ValueError("image URL uses a non-HTTPS port")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise ValueError("image hostname cannot be resolved") from error
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("image URL resolves to a non-public address")
    return value


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validated_image_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def rich_text(items: list[dict]) -> str:
    parts = []
    for item in items:
        text = html.escape(item.get("plain_text", ""))
        annotations = item.get("annotations", {})
        if annotations.get("code"):
            text = f"<code>{text}</code>"
        if annotations.get("bold"):
            text = f"<strong>{text}</strong>"
        if annotations.get("italic"):
            text = f"<em>{text}</em>"
        if annotations.get("strikethrough"):
            text = f"<s>{text}</s>"
        if annotations.get("underline"):
            text = f"<u>{text}</u>"
        href = safe_url(item.get("href") or "")
        if href:
            text = f'<a href="{href}" rel="noreferrer">{text}</a>'
        parts.append(text)
    return "".join(parts)


def plain_property(prop: dict) -> str:
    kind = prop.get("type")
    if kind in {"title", "rich_text"}:
        return "".join(item.get("plain_text", "") for item in prop.get(kind, []))
    if kind in {"status", "select"}:
        return (prop.get(kind) or {}).get("name", "")
    return ""


def slugify(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or fallback.replace("-", "")[:12]


def block_children(block_id: str) -> list[dict]:
    blocks = paginated(f"/blocks/{block_id}/children")
    for block in blocks:
        if block.get("has_children"):
            block["_children"] = block_children(block["id"])
    return blocks


def download_image(url: str, page_id: str) -> str:
    url = validated_image_url(url)
    target_dir = ROOT / "static/notion" / page_id.replace("-", "")
    target_dir.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "AndreaTangSite/1.0"})
    opener = urllib.request.build_opener(SafeRedirectHandler())
    with opener.open(req, timeout=20) as response:
        validated_image_url(response.geturl())
        content_type = response.headers.get_content_type()
        if content_type not in IMAGE_TYPES:
            raise ValueError(f"unsupported image type: {content_type}")
        content_length = int(response.headers.get("Content-Length", "0") or "0")
        if content_length > MAX_IMAGE_BYTES:
            raise ValueError("image exceeds the size limit")
        body = response.read(MAX_IMAGE_BYTES + 1)
        if len(body) > MAX_IMAGE_BYTES:
            raise ValueError("image exceeds the size limit")
    signatures = {
        "image/gif": body.startswith((b"GIF87a", b"GIF89a")),
        "image/jpeg": body.startswith(b"\xff\xd8\xff"),
        "image/png": body.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": body.startswith(b"RIFF") and body[8:12] == b"WEBP",
    }
    if not signatures[content_type]:
        raise ValueError("image bytes do not match the declared type")
    name = hashlib.sha256(url.encode()).hexdigest()[:16] + IMAGE_TYPES[content_type]
    target = target_dir / name
    target.write_bytes(body)
    return f'/assets/notion/{page_id.replace("-", "")}/{name}'


def render_blocks(blocks: list[dict], page_id: str) -> str:
    output: list[str] = []
    list_type = ""

    def close_list() -> None:
        nonlocal list_type
        if list_type:
            output.append(f"</{list_type}>")
            list_type = ""

    for block in blocks:
        kind = block.get("type", "")
        data = block.get(kind, {})
        children = block.get("_children", [])
        if kind in {"bulleted_list_item", "numbered_list_item"}:
            wanted = "ul" if kind == "bulleted_list_item" else "ol"
            if list_type != wanted:
                close_list()
                output.append(f"<{wanted}>")
                list_type = wanted
            nested = render_blocks(children, page_id) if children else ""
            output.append(f'<li>{rich_text(data.get("rich_text", []))}{nested}</li>')
            continue
        close_list()

        text = rich_text(data.get("rich_text", []))
        nested = render_blocks(children, page_id) if children else ""
        if kind == "paragraph":
            output.append(f"<p>{text}</p>{nested}" if text else nested)
        elif kind in {"heading_1", "heading_2", "heading_3"}:
            level = {"heading_1": 2, "heading_2": 2, "heading_3": 3}[kind]
            anchor = slugify(re.sub(r"<[^>]+>", "", text), block["id"][:8])
            output.append(f'<h{level} id="{anchor}">{text}</h{level}>{nested}')
        elif kind == "quote":
            output.append(f"<blockquote><p>{text}</p>{nested}</blockquote>")
        elif kind == "callout":
            icon = data.get("icon", {})
            emoji = html.escape(icon.get("emoji", "")) if icon.get("type") == "emoji" else ""
            output.append(f'<aside class="callout">{emoji} {text}{nested}</aside>')
        elif kind == "code":
            language = re.sub(r"[^a-zA-Z0-9_+-]", "", data.get("language", "text"))
            output.append(f'<pre><code class="language-{language}">{text}</code></pre>')
        elif kind == "equation":
            expression = html.escape(data.get("expression", ""))
            output.append(f'<pre class="equation"><code>{expression}</code></pre>')
        elif kind == "divider":
            output.append("<hr>")
        elif kind == "to_do":
            checked = " checked" if data.get("checked") else ""
            output.append(f'<div class="todo"><input type="checkbox" disabled{checked}> {text}</div>{nested}')
        elif kind == "toggle":
            output.append(f"<details><summary>{text}</summary>{nested}</details>")
        elif kind == "image":
            image = data.get(data.get("type", ""), {})
            source = image.get("url", "")
            if source:
                try:
                    source = download_image(source, page_id)
                except (OSError, ValueError, urllib.error.URLError) as error:
                    print(f"warning: could not download image: {error}", file=sys.stderr)
                    source = ""
                if not source:
                    continue
                caption = rich_text(data.get("caption", []))
                alt = html.escape(re.sub(r"<[^>]+>", "", caption) or "Article image", quote=True)
                output.append(f'<figure><img src="{source}" alt="{alt}" loading="lazy">')
                if caption:
                    output.append(f"<figcaption>{caption}</figcaption>")
                output.append("</figure>")
        elif kind in {"bookmark", "embed", "video", "file", "pdf", "audio"}:
            if kind in {"bookmark", "embed"}:
                raw_url = data.get("url", "")
            else:
                media_type = data.get("type", "")
                raw_url = data.get(media_type, {}).get("url", "")
            url = safe_url(raw_url)
            if url:
                caption = rich_text(data.get("caption", []))
                label = caption or html.escape(kind.replace("_", " ").title())
                output.append(f'<p><a href="{url}" rel="noreferrer">{label}</a></p>')
        elif kind == "table":
            rows = []
            has_header = bool(data.get("has_column_header"))
            for index, row in enumerate(children):
                cells = row.get("table_row", {}).get("cells", [])
                cell_tag = "th" if has_header and index == 0 else "td"
                rows.append("<tr>" + "".join(
                    f"<{cell_tag}>{rich_text(cell)}</{cell_tag}>" for cell in cells
                ) + "</tr>")
            output.append("<table>" + "".join(rows) + "</table>")
        elif kind in {"column_list", "column", "synced_block", "table_row"}:
            output.append(nested)
        else:
            output.append(nested)
    close_list()
    return "".join(output)


def page_to_post(page: dict) -> dict | None:
    properties = page.get("properties", {})
    status = plain_property(properties.get("Status", {})).lower()
    if status != "published":
        return None
    title = plain_property(properties.get("Title", {}))
    if not title:
        print(f"warning: skipping {page['id']} without Title", file=sys.stderr)
        return None
    slug = slugify(plain_property(properties.get("Slug", {})) or title, page["id"])
    summary = plain_property(properties.get("Summary", {}))
    date_prop = properties.get("Published At", {})
    published = (date_prop.get("date") or {}).get("start") or page["created_time"]
    tags_prop = properties.get("Tags", {})
    tags = [item["name"] for item in tags_prop.get("multi_select", [])]
    featured = bool(properties.get("Featured", {}).get("checkbox", False))
    content = render_blocks(block_children(page["id"]), page["id"])
    if not summary:
        summary = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", content)).strip()[:180]
    return {
        "title": title,
        "slug": slug,
        "summary": summary,
        "published_at": published,
        "updated_at": page["last_edited_time"],
        "tags": tags,
        "featured": featured,
        "source": "notion",
        "notion_page_id": page["id"],
        "content_html": content,
    }


def main() -> None:
    if not TOKEN or not DATA_SOURCE_ID:
        print("Notion secrets are not configured; keeping local sample content.")
        return
    pages = paginated(f"/data_sources/{DATA_SOURCE_ID}/query", {"sorts": [{
        "timestamp": "last_edited_time", "direction": "descending"
    }]})
    output_dir = ROOT / "content/posts"
    for old in output_dir.glob("notion-*.json"):
        old.unlink()
    published = 0
    for page in pages:
        if page.get("object") != "page":
            continue
        post = page_to_post(page)
        if not post:
            continue
        path = output_dir / f'notion-{page["id"].replace("-", "")}.json'
        path.write_text(json.dumps(post, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        published += 1
    print(f"Synced {published} published Notion page(s).")


if __name__ == "__main__":
    main()
