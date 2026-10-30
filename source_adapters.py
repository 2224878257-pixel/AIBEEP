"""Source adapters for official, public AIBEEP inputs.

Only public HTTPS endpoints are supported.  The adapters deliberately do not
handle authentication, CAPTCHA challenges, paywalls, or anti-bot bypasses.
"""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
from html.parser import HTMLParser
import html
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
import urllib.request
import xml.etree.ElementTree as ET

ATOM = "{http://www.w3.org/2005/Atom}"
USER_AGENT = "AIBEEP/16.1 official-source monitor (+https://github.com/2224878257-pixel/AIBEEP)"
TRACKING_KEYS = {"from", "source", "spm", "timestamp", "visitor_source"}


class SourceFetchError(RuntimeError):
    def __init__(self, message, *, http_status=None):
        super().__init__(message)
        self.http_status = http_status


def clean_text(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value or ""))).strip()


def normalize_url(value):
    """Canonicalize a public URL without changing its destination."""
    parts = urlsplit((value or "").strip())
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("source URL must be absolute HTTPS")
    query = []
    for key, val in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in TRACKING_KEYS:
            continue
        query.append((key, val))
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit(("https", parts.netloc.lower(), path, urlencode(query), ""))


def entry_id(url):
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()[:16]


def content_fingerprint(entry):
    title = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", entry.get("title", "").lower())
    excerpt = re.sub(r"\s+", "", entry.get("excerpt", "").lower())[:300]
    return hashlib.sha256(f"{title}|{excerpt}".encode("utf-8")).hexdigest()


def _allowed_hosts(source):
    configured = source.get("allowed_domains") or []
    if configured:
        return {x.lower() for x in configured}
    return {urlsplit(source["url"]).hostname.lower()}


def request_bytes(source, *, data=None, method="GET", content_type=None, max_bytes=2_000_000):
    """Fetch one public endpoint with bounded retries, timeout, and size."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, application/atom+xml, application/rss+xml, text/html;q=0.9, */*;q=0.5",
    }
    if content_type:
        headers["Content-Type"] = content_type
    if source.get("referer"):
        headers["Referer"] = source["referer"]
    timeout = max(3, min(int(source.get("timeout", 18)), 30))
    retries = max(0, min(int(source.get("retries", 2)), 2))
    last_error = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(source["url"], data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                final_url = response.geturl()
                final = urlsplit(final_url)
                if final.scheme != "https" or final.hostname.lower() not in _allowed_hosts(source):
                    raise SourceFetchError("redirected outside configured official domains", http_status=response.status)
                payload = response.read(max_bytes + 1)
                if len(payload) > max_bytes:
                    raise SourceFetchError("response exceeded size limit", http_status=response.status)
                return payload, response.status, final_url, response.headers.get("Content-Type", "")
        except HTTPError as exc:
            last_error = SourceFetchError(f"HTTP {exc.code}", http_status=exc.code)
            if exc.code != 429 and exc.code < 500:
                raise last_error from None
        except (URLError, TimeoutError, OSError) as exc:
            last_error = SourceFetchError(f"{type(exc).__name__}: {str(exc)[:160]}")
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))
    raise last_error or SourceFetchError("request failed")


def _base_entry(source, title, url, published_at="", excerpt=""):
    url = normalize_url(url)
    return {
        "id": entry_id(url),
        "title": clean_text(title),
        "url": url,
        "source": source["name"],
        "platform": source.get("platform", ""),
        "region": source.get("region", ""),
        "publishedAt": published_at or None,
        "collectedAt": datetime.now(timezone.utc).isoformat(),
        "excerpt": clean_text(excerpt)[:1000],
        "relevanceScore": 0,
        "reviewStatus": source.get("reviewStatus", "pending"),
        "category": source.get("category", "行业动态"),
    }


def _value(node, tag):
    child = node.find(tag)
    return "" if child is None else "".join(child.itertext()).strip()


def parse_feed(xml_bytes, source):
    root = ET.fromstring(xml_bytes)
    items = root.findall(".//item") or root.findall(f".//{ATOM}entry")
    found = []
    for node in items:
        atom = node.tag.endswith("entry")
        title = clean_text(_value(node, f"{ATOM}title" if atom else "title"))
        if atom:
            link = next(
                (e.attrib.get("href", "") for e in node.findall(f"{ATOM}link") if e.attrib.get("rel", "alternate") == "alternate"),
                "",
            )
            summary = _value(node, f"{ATOM}summary") or _value(node, f"{ATOM}content")
            published = _value(node, f"{ATOM}published") or _value(node, f"{ATOM}updated")
        else:
            link = _value(node, "link")
            summary = _value(node, "description")
            published = _value(node, "pubDate")
        if not title or not link.startswith("https://"):
            continue
        try:
            found.append(_base_entry(source, title, link, published, summary))
        except ValueError:
            continue
    return found


def fetch_feed(source, limit):
    payload, status, _, _ = request_bytes(source)
    return parse_feed(payload, source)[:limit], status


def fetch_tencent_latestnews(source, limit):
    body = json.dumps(
        {
            "tag_ids": [],
            "resources_ids": [],
            "info_ids": [],
            "tech_ids": [],
            "page": 1,
            "per_page": min(max(limit * 3, 12), 30),
            "merge": False,
            "type": 6,
        }
    ).encode("utf-8")
    payload, status, _, _ = request_bytes(
        source, data=body, method="POST", content_type="application/json", max_bytes=3_000_000
    )
    response = json.loads(payload)
    rows = ((response.get("data") or {}).get("data") or []) if response.get("code") == 0 else []
    if not isinstance(rows, list):
        raise SourceFetchError("unexpected Tencent Ads response", http_status=status)
    entries = []
    for row in rows:
        post_id = row.get("post_id")
        title = row.get("title")
        if not post_id or not title:
            continue
        catalogs = row.get("catalogs") or []
        published = (catalogs[0].get("first_publish_at") if catalogs else "") or row.get("created_at")
        tags = " ".join(x.get("name", "") for x in row.get("tags") or [] if isinstance(x, dict))
        excerpt = " ".join(x for x in (row.get("sub_title"), row.get("memo"), tags) if x)
        url = f"https://e.qq.com/latestnews/detail?pid={post_id}"
        entries.append(_base_entry(source, title, url, published, excerpt))
    return entries[: limit * 3], status


def _walk_xhs_menu(value):
    if isinstance(value, dict):
        if value.get("docInfoType") == 1 and value.get("shortcutId") and value.get("title"):
            yield value
        for child in value.values():
            yield from _walk_xhs_menu(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_xhs_menu(child)


def fetch_xiaohongshu_help(source, limit):
    payload, status, _, _ = request_bytes(source, max_bytes=3_000_000)
    response = json.loads(payload)
    menu = ((response.get("data") or {}).get("menu") or []) if response.get("msg") == "ok" else []
    rows = sorted(_walk_xhs_menu(menu), key=lambda x: int(x.get("updateTime") or 0), reverse=True)
    entries = []
    seen = set()
    for row in rows:
        shortcut = row["shortcutId"]
        if shortcut in seen:
            continue
        seen.add(shortcut)
        timestamp = int(row.get("updateTime") or 0)
        published = datetime.fromtimestamp(timestamp / 1000, timezone.utc).isoformat() if timestamp else ""
        url = f"https://ad.xiaohongshu.com/next_help/docs/{shortcut}"
        excerpt = " / ".join(row.get("directory") or [])
        entries.append(_base_entry(source, row["title"], url, published, excerpt))
        if len(entries) >= limit * 3:
            break
    return entries, status


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.current = None
        self.depth = 0
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a" and self.current is None:
            self.current = {"href": dict(attrs).get("href", ""), "text": []}
            self.depth = 1
        elif self.current is not None:
            self.depth += 1

    def handle_endtag(self, tag):
        if self.current is None:
            return
        self.depth -= 1
        if tag == "a" and self.depth == 0:
            self.links.append((self.current["href"], clean_text("".join(self.current["text"]))))
            self.current = None

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"].append(data)


def fetch_public_webpage(source, limit):
    payload, status, final_url, content_type = request_bytes(source, max_bytes=3_000_000)
    if "html" not in content_type.lower():
        raise SourceFetchError("public webpage did not return HTML", http_status=status)
    parser = LinkParser()
    parser.feed(payload.decode("utf-8", errors="replace"))
    prefixes = tuple(source.get("item_path_prefixes") or [])
    by_url = {}
    for href, raw_text in parser.links:
        absolute = urljoin(final_url, href)
        parts = urlsplit(absolute)
        if parts.scheme != "https" or parts.hostname.lower() not in _allowed_hosts(source):
            continue
        if prefixes and not parts.path.startswith(prefixes):
            continue
        if len(raw_text) < 8 or raw_text in {"查看全部", "更多", "立即登录"}:
            continue
        try:
            canonical = normalize_url(absolute)
        except ValueError:
            continue
        if len(raw_text) > len(by_url.get(canonical, "")):
            by_url[canonical] = raw_text
    entries = []
    date_re = re.compile(r"(20\d{2}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}))?")
    for url, raw_text in by_url.items():
        match = date_re.search(raw_text)
        published = (match.group(1) + (f"T{match.group(2)}:00+08:00" if match.group(2) else "T00:00:00+08:00")) if match else ""
        title = raw_text[: match.start()] if match else raw_text
        title = re.sub(r"^(?:未开始|已结束|回放|直播中)[·\s]*", "", title)
        title = re.sub(r"\d+人(?:参与|学习过)", "", title).strip(" ·-")
        if len(title) < 6:
            continue
        entries.append(_base_entry(source, title, url, published, raw_text))
    entries.sort(key=lambda x: x.get("publishedAt") or "", reverse=True)
    return entries[: limit * 3], status


def fetch_source(source, limit):
    kind = source.get("type", "rss")
    if kind in ("rss", "atom"):
        return fetch_feed(source, limit)
    if kind == "official_api":
        adapter = source.get("adapter")
        if adapter == "tencent_latestnews":
            return fetch_tencent_latestnews(source, limit)
        if adapter == "xiaohongshu_help":
            return fetch_xiaohongshu_help(source, limit)
        raise ValueError(f"unknown official_api adapter: {adapter}")
    if kind == "public_webpage":
        return fetch_public_webpage(source, limit)
    if kind == "manual_link":
        return [], None
    raise ValueError(f"unsupported source type: {kind}")


def parse_datetime(value):
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
