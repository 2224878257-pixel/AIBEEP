"""Promote explicitly approved RSS candidates to AIBEEP static content.

Usage:
  python3 publish_reviewed.py                  # validate + preview only
  python3 publish_reviewed.py --apply          # update dist/*.json

AI approval is necessary but not sufficient. Reviewers must also set
publicationStatus to "approved" and provide humanApproval {approvedBy,
approvedAt}. Items without two-step approval are never published.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent

def check_article(record):
    note = record.get("editorial") or {}
    sections = note.get("sections")
    audit = record.get("audit") or {}
    human = record.get("humanApproval") or {}
    evidence = audit.get("supported_facts") or []
    if not (
        record.get("reviewStatus") == "approved"
        and audit.get("decision") == "approved"
        and record.get("publicationStatus") == "approved"
        and isinstance(human.get("approvedBy"), str) and human["approvedBy"].strip()
        and isinstance(human.get("approvedAt"), str) and human["approvedAt"].strip()
        and isinstance(evidence, list) and len(evidence) >= 2
        and all(isinstance(fact, str) and len(fact.strip()) >= 12 for fact in evidence[:2])
        and isinstance(sections, list) and sections
    ):
        return None
    if not all(isinstance(note.get(k), str) and note[k].strip() for k in ("title", "summary", "intro")):
        return None
    if len(note["summary"]) > 350 or len(note["title"]) > 160:
        return None
    for section in sections:
        if not isinstance(section, dict) or not isinstance(section.get("title"), str) or not section["title"].strip():
            return None
        if not isinstance(section.get("paragraphs"), list) or not section["paragraphs"] or not all(isinstance(s, str) and s.strip() for s in section["paragraphs"]):
            return None
    link = record.get("url", "")
    parts = urlsplit(link)
    if parts.scheme != "https" or not parts.netloc or not re.fullmatch(r"[a-f0-9]{16}", record.get("id", "")):
        return None
    return note

def promoted(queue, content, articles):
    """Pure conversion function for testing; no filesystem changes."""
    updated = {x["id"]: x for x in content["items"]}
    existing_urls = {x.get("url", "").split("#")[0].rstrip("/") for x in content["items"]}
    bodies = articles.setdefault("articles", {})
    added = []
    for record in queue.get("candidates", []):
        note = check_article(record)
        audit = record.get("audit") or {}
        url_key = record.get("url", "").split("#")[0].rstrip("/")
        if not note or record["id"] in updated or url_key in existing_urls:
            continue
        updated[record["id"]] = {
            "id": record["id"], "title": note["title"].strip(),
            "category": record.get("category", "行业动态"),
            "source": record.get("source", "官方资料"), "url": record["url"],
            "summary": note["summary"].strip(),
            "publishedAt": record.get("publishedAt") or record.get("published") or None,
            "reviewStatus": "approved",
            "evidence": [fact.strip() for fact in audit.get("supported_facts", [])[:5] if isinstance(fact, str) and fact.strip()],
            "audit": {
                "decision": "approved",
                "auditedAt": audit.get("auditedAt"),
                "relevance": audit.get("relevance"),
                "fidelity": audit.get("fidelity"),
            },
            "humanApproval": {
                "approvedBy": (record.get("humanApproval") or {}).get("approvedBy"),
                "approvedAt": (record.get("humanApproval") or {}).get("approvedAt"),
            },
            "addedAt": datetime.now(timezone.utc).isoformat()
        }
        bodies[record["id"]] = {"intro": note["intro"], "sections": note["sections"]}
        existing_urls.add(url_key)
        added.append(record["id"])
    content["items"] = sorted(updated.values(), key=lambda x: x.get("addedAt", ""), reverse=True)
    if added:
        content["updatedAt"] = datetime.now(timezone.utc).isoformat()
        content["editorialNote"] = "基于官方信息来源的中文原创整理，经 AI 自动审核；不代表来源机构立场。"
    return added

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    queue_path = ROOT / "review_queue.json"
    if not queue_path.exists():
        print("No review_queue.json found. Run collect_feeds.py first.")
        return
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    content_path = ROOT / "dist" / "content.json"
    articles_path = ROOT / "dist" / "articles.json"
    content = json.loads(content_path.read_text(encoding="utf-8"))
    articles = json.loads(articles_path.read_text(encoding="utf-8"))
    added = promoted(queue, content, articles)
    print(f"Validated {len(added)} newly approved articles: {', '.join(added) or 'none'}")
    if not args.apply:
        report_path = ROOT / "run_report.json"
        if report_path.exists():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["publication"] = {"eligible": len(added), "actualAdded": 0, "mode": "manual-gate"}
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Dry run only. Use --apply after reviewing sources and Chinese drafts.")
        return
    content_path.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    articles_path.write_text(json.dumps(articles, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path = ROOT / "run_report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["publication"] = {"eligible": len(added), "actualAdded": len(added), "mode": "human-approved-apply"}
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Updated static content; redeploy the private Site to publish.")

if __name__ == "__main__":
    main()
