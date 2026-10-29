"""Run the official-feed -> DeepSeek independent audit -> SQLite pipeline.

No DeepSeek token means ingest is disabled (fail closed). Held/rejected drafts
are never served publicly. Feed polling itself can still work without a token.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import backend
from publish_reviewed import check_article

ROOT = Path(__file__).resolve().parent
QUEUE_PATH = ROOT / "review_queue.json"


def job(kind, status, detail):
    with backend.connect() as db:
        db.execute("INSERT INTO job_runs(kind,status,detail) VALUES(?,?,?)", (kind, status, detail[:1500]))


def approved_item(candidate):
    audit = candidate.get("audit", {})
    if candidate.get("reviewStatus") != "approved" or audit.get("decision") != "approved":
        return None
    if not check_article(candidate):
        return None
    if not all(candidate.get(key) for key in ("id", "url", "source", "category")):
        return None
    editorial = candidate.get("editorial", {})
    if not isinstance(editorial, dict):
        return None
    if not all(editorial.get(key) for key in ("title", "summary", "intro", "sections")):
        return None
    published = candidate.get("published", "")
    # The feed timestamp may use RFC-822. Use the audited date for consistent sorting.
    from email.utils import parsedate_to_datetime
    try:
        added = parsedate_to_datetime(published).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        added = audit.get("auditedAt") or datetime.now(timezone.utc).isoformat()
    item = {"id": candidate["id"], "title": editorial.get("title"),
            "category": candidate.get("category"), "source": candidate.get("source"),
            "summary": editorial.get("summary"), "url": candidate.get("url"), "addedAt": added}
    body = {"intro": editorial.get("intro", ""), "sections": editorial.get("sections", [])}
    return item, body, audit


def run_once():
    backend.initialize()
    seeded = backend.seed_existing()
    subprocess.run([sys.executable, str(ROOT / "collect_feeds.py")], cwd=ROOT, check=True, timeout=120)
    if not os.getenv("DEEPSEEK_API_KEY"):
        job("pipeline", "held", f"seeded={seeded}; DeepSeek token missing, no AI review or publication")
        return 0
    # Eight sequential evidence fetches + two model calls each can exceed five minutes.
    subprocess.run([sys.executable, str(ROOT / "ai_review.py"), "--limit", "8"], cwd=ROOT, check=True, timeout=1500)
    candidates = json.loads(QUEUE_PATH.read_text(encoding="utf-8")).get("candidates", [])
    inserted = 0
    held = 0
    for candidate in candidates:
        approved = approved_item(candidate)
        if not approved:
            held += 1
            continue
        try:
            inserted += backend.save_article(*approved)
        except (ValueError, KeyError, TypeError) as exc:
            held += 1
            print(f"Withheld invalid approved candidate: {exc}", flush=True)
    job("pipeline", "ok", f"seeded={seeded}; inserted={inserted}; held={held}")
    return inserted


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval-hours", type=float, default=6)
    args = parser.parse_args()
    if not args.once and not 1 <= args.interval_hours <= 24:
        parser.error("interval-hours must be 1..24")
    backend.initialize()
    while True:
        try:
            print(f"Pipeline starting {datetime.now(timezone.utc).isoformat()}", flush=True)
            print(f"Inserted {run_once()} articles", flush=True)
        except Exception as exc:
            job("pipeline", "error", f"{type(exc).__name__}: {str(exc)[:400]}")
            print(f"Pipeline failed closed: {exc}", file=sys.stderr, flush=True)
        if args.once:
            break
        time.sleep(args.interval_hours * 3600)


if __name__ == "__main__":
    main()
