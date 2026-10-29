"""AIBEEP local API and persistent article store (Python stdlib only).

Start with `python3 backend.py`; bind to loopback by default. The public API
reads articles; writes require an owner-only token. Docker can run the same app.
"""
import hmac
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
DB_PATH = Path(os.getenv("AIBEEP_DB_PATH", str(ROOT / "data" / "aibeep.sqlite3")))
ARTICLE_ID = re.compile(r"^[a-zA-Z0-9_-]{8,100}$")


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB_PATH), timeout=20)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=20000")
    db.row_factory = sqlite3.Row
    return db


def initialize():
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS articles (
            id TEXT PRIMARY KEY, source_url TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL, category TEXT NOT NULL, source TEXT NOT NULL,
            summary TEXT NOT NULL, added_at TEXT NOT NULL,
            body_json TEXT NOT NULL, review_status TEXT NOT NULL DEFAULT 'approved',
            audit_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS articles_added_idx ON articles(added_at DESC)")
        db.execute("""CREATE TABLE IF NOT EXISTS job_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT DEFAULT CURRENT_TIMESTAMP,
            kind TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL
        )""")


def validate_item(item, body):
    if not isinstance(item, dict) or not isinstance(body, dict):
        raise ValueError("item and body must be objects")
    if not ARTICLE_ID.fullmatch(str(item.get("id", ""))):
        raise ValueError("invalid article id")
    for key in ("title", "category", "source", "summary", "addedAt"):
        if not isinstance(item.get(key), str) or not item[key].strip():
            raise ValueError(f"missing {key}")
    url = urlparse(item.get("url", ""))
    if url.scheme != "https" or not url.hostname:
        raise ValueError("source must be HTTPS")
    if not isinstance(body.get("intro"), str) or not isinstance(body.get("sections"), list):
        raise ValueError("invalid article body")
    if len(json.dumps(body, ensure_ascii=False)) > 120_000:
        raise ValueError("article body too large")
    return True


def save_article(item, body, audit=None):
    validate_item(item, body)
    with connect() as db:
        cur = db.execute("""INSERT OR IGNORE INTO articles
            (id,source_url,title,category,source,summary,added_at,body_json,review_status,audit_json)
            VALUES (?,?,?,?,?,?,?,?,?,?)""", (
                item["id"], item["url"], item["title"], item["category"],
                item["source"], item["summary"], item["addedAt"],
                json.dumps(body, ensure_ascii=False), "approved",
                json.dumps(audit or {}, ensure_ascii=False)
            ))
        return cur.rowcount == 1


def seed_existing():
    source = json.loads((DIST / "content.json").read_text(encoding="utf-8"))
    bodies = json.loads((DIST / "articles.json").read_text(encoding="utf-8")).get("articles", {})
    count = 0
    for item in source.get("items", []):
        body = bodies.get(item["id"]) or {"intro": item["summary"], "sections": [{"title": "主要信息", "paragraphs": [item["summary"]]}]}
        count += save_article(item, body)
    return count


def get_content(limit=100):
    with connect() as db:
        rows = db.execute("SELECT * FROM articles WHERE review_status='approved' ORDER BY added_at DESC LIMIT ?", (min(max(int(limit), 1), 200),)).fetchall()
    return {"version": 2, "items": [{
        "id": r["id"], "title": r["title"], "category": r["category"],
        "source": r["source"], "summary": r["summary"],
        "url": r["source_url"], "addedAt": r["added_at"]
    } for r in rows]}


def get_bodies(limit=200):
    with connect() as db:
        rows = db.execute("SELECT id,body_json FROM articles WHERE review_status='approved' ORDER BY added_at DESC LIMIT ?", (limit,)).fetchall()
    return {"articles": {r["id"]: json.loads(r["body_json"]) for r in rows}}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST), **kwargs)

    def json_response(self, status, obj):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def authorized(self):
        token = os.getenv("AIBEEP_ADMIN_TOKEN", "")
        supplied = self.headers.get("Authorization", "")
        return len(token) >= 32 and hmac.compare_digest(supplied, "Bearer " + token)

    def do_GET(self):
        route = urlparse(self.path)
        if route.path == "/api/health":
            return self.json_response(200, {"ok": True, "service": "aibeep"})
        if route.path == "/api/content":
            try:
                lim = int(parse_qs(route.query).get("limit", [100])[0])
                return self.json_response(200, get_content(lim))
            except ValueError:
                return self.json_response(400, {"error": "invalid limit"})
        if route.path == "/api/article-bodies":
            return self.json_response(200, get_bodies())
        if route.path == "/api/sources":
            catalog = json.loads((ROOT / "feed_sources.json").read_text(encoding="utf-8"))
            return self.json_response(200, {"feeds": [{"name": f["name"], "platform": f.get("platform"), "region": f.get("region"), "status": "rss"} for f in catalog["feeds"]], "watchPages": [{"name": w["name"], "platform": w.get("platform"), "region": w.get("region"), "status": "pending-integration"} for w in catalog.get("watch_pages", [])]})
        if route.path == "/api/admin/jobs":
            if not self.authorized():
                return self.json_response(401, {"error": "unauthorized"})
            with connect() as db:
                jobs = [dict(r) for r in db.execute("SELECT * FROM job_runs ORDER BY id DESC LIMIT 50")]
            return self.json_response(200, {"jobs": jobs})
        if route.path == "/api/admin/status":
            if not self.authorized():
                return self.json_response(401, {"error": "unauthorized"})
            source_status = ROOT / "source_status.json"
            status = json.loads(source_status.read_text(encoding="utf-8")) if source_status.exists() else {"results":[],"state":"not-run"}
            with connect() as db:
                totals = {"published": db.execute("SELECT count(*) FROM articles WHERE review_status='approved'").fetchone()[0], "pipelineRuns": db.execute("SELECT count(*) FROM job_runs").fetchone()[0]}
            return self.json_response(200, {"sources":status, "totals":totals})
        if route.path.startswith("/api/"):
            return self.json_response(404, {"error": "not found"})
        return super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path != "/api/admin/ingest":
            return self.json_response(404, {"error": "not found"})
        if not self.authorized():
            return self.json_response(401, {"error": "unauthorized"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 150_000:
                return self.json_response(413, {"error": "invalid size"})
            data = json.loads(self.rfile.read(length))
            if data.get("reviewStatus") != "approved":
                return self.json_response(422, {"error": "only approved articles accepted"})
            inserted = save_article(data["item"], data["body"], data.get("audit"))
            return self.json_response(201 if inserted else 200, {"inserted": inserted})
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            return self.json_response(422, {"error": str(exc)[:140]})


if __name__ == "__main__":
    initialize()
    print(f"Seeded {seed_existing()} existing articles", flush=True)
    host = os.getenv("AIBEEP_HOST", "127.0.0.1")
    port = int(os.getenv("AIBEEP_PORT", "8080"))
    print(f"AIBEEP serving http://{host}:{port}", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
