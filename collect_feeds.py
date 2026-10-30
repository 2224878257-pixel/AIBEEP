"""Collect official public sources into a review queue; never auto-publish."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time

from deepseek_client import generate_json
from source_adapters import (
    SourceFetchError,
    content_fingerprint,
    fetch_source,
    normalize_url,
    parse_datetime,
    parse_feed,
)

BASE = Path(__file__).resolve().parent
BUSINESS_WORDS = (
    "advertis", "marketing", " ads", "ad campaign", "campaign", "conversion", "commerce",
    "customer", "creative", "lead gen", "merchant", "shopping", "attribution", "roi",
    "投放", "广告", "获客", "转化", "营销", "素材", "创意", "商家", "电商", "线索",
    "千川", "聚光", "商业化", "归因", "流量", "智投", "推广", "大促", "留资", "私信", "dmp",
)
PRIORITY_WORDS = (
    "规则", "政策", "公告", "更新", "上线", "产品手册", "审核", "案例", "优化",
    "成本", "出价", "定向", "效果", "线索", "转化", "归因", "roi", "aigc",
)
AI_WORDS = ("ai", "agent", "copilot", "automation", "模型", "智能", "自动化")


def relevance(entry):
    """Conservative metadata triage; official origin alone is not relevance."""
    title = entry.get("title", "").lower()
    text = " ".join([title, entry.get("excerpt", "").lower()])
    title_business = sum(token in title for token in BUSINESS_WORDS)
    business_hits = sum(token in text for token in BUSINESS_WORDS)
    title_priority = sum(token in title for token in PRIORITY_WORDS)
    # Navigation categories alone must not turn a generic help document into news.
    if not title_business and not (title_priority and business_hits):
        return 0
    priority_hits = sum(token in text for token in PRIORITY_WORDS)
    ai_hits = min(sum(token in text for token in AI_WORDS), 2)
    contextual_hits = max(0, business_hits - title_business)
    return min(100, title_business * 20 + min(contextual_hits, 2) * 6 + priority_hits * 12 + ai_hits * 8)


def likely_relevant(entry):
    return relevance(entry) >= 22


def draft(entry, token):
    return generate_json(
        (
            "根据提供的官方标题和资料摘录生成原创中文编辑稿。不得编造数据、效果或案例，"
            "不得声称阅读了未提供的材料，不得逐段翻译或复制原文。重点解释其对广告投放、"
            "企业获客或增长的实际影响。返回字段 title、summary、intro、sections；sections "
            "最多3项，各含 title 和 paragraphs 字符串数组。"
        ),
        {"title": entry["title"], "excerpt": entry["excerpt"], "source": entry["source"], "url": entry["url"]},
        token=token,
    )


def _all_sources(registry):
    sources = []
    for source in registry.get("feeds", []):
        sources.append({"type": source.get("type", "rss"), **source})
    sources.extend(registry.get("automatic_sources", []))
    sources.extend(registry.get("watch_pages", []))
    return sources


def _is_stale(entry, max_age_days, now):
    published = parse_datetime(entry.get("publishedAt"))
    return bool(published and published <= now and (now - published).days > max_age_days)


def _platform_totals(results):
    totals = {}
    for row in results:
        platform = row.get("platform") or "未分类"
        target = totals.setdefault(
            platform,
            {"fetched": 0, "newCandidates": 0, "duplicates": 0, "lowRelevance": 0, "stale": 0, "failures": 0},
        )
        for key in target:
            if key == "failures":
                target[key] += int(row.get("status") == "failed")
            else:
                target[key] += int(row.get(key, 0))
    return totals


def collect(options):
    started = datetime.now(timezone.utc)
    queue_path = BASE / "review_queue.json"
    old = json.loads(queue_path.read_text(encoding="utf-8")) if queue_path.exists() else {"candidates": []}
    previous_candidates = old.get("candidates", [])
    queue = {entry["id"]: entry for entry in previous_candidates}
    queue_changed = False
    known_urls = set()
    known_fingerprints = set()
    for entry in previous_candidates:
        try:
            known_urls.add(normalize_url(entry.get("url", "")))
        except ValueError:
            pass
        known_fingerprints.add(content_fingerprint(entry))

    registry = json.loads((BASE / "feed_sources.json").read_text(encoding="utf-8"))
    token = os.getenv("DEEPSEEK_API_KEY", "")
    if options.ai and not token:
        raise ValueError("--ai requires DEEPSEEK_API_KEY")
    selected = {value.lower() for value in options.source}
    outcomes = []

    for source in _all_sources(registry):
        if not source.get("enabled", True):
            continue
        if selected and source.get("name", "").lower() not in selected and source.get("platform", "").lower() not in selected:
            continue
        report = {
            "source": source["name"],
            "platform": source.get("platform", ""),
            "method": source.get("type", "rss"),
            "status": "manual" if source.get("type") == "manual_link" else "failed",
            "httpStatus": None,
            "fetched": 0,
            "newCandidates": 0,
            "duplicates": 0,
            "lowRelevance": 0,
            "stale": 0,
            "successRate": 0.0,
        }
        if source.get("type") == "manual_link":
            report["reason"] = source.get("note", "manual submission only")
            outcomes.append(report)
            continue
        desired_status = source.get("reviewStatus")
        if desired_status:
            for existing in queue.values():
                if existing.get("source") != source.get("name"):
                    continue
                if existing.get("reviewStatus") not in ("pending", "needs_review"):
                    continue
                desired_access = {
                    "status": source.get("evidenceAccess", "manual_required"),
                    "reason": source.get("note", "manual source evidence required"),
                }
                if existing.get("reviewStatus") == desired_status and existing.get("sourceAccess") == desired_access:
                    continue
                existing["reviewStatus"] = desired_status
                existing["publicationStatus"] = "withheld"
                existing["sourceAccess"] = desired_access
                queue_changed = True
        try:
            entries, http_status = fetch_source(source, options.limit)
            report["httpStatus"] = http_status
            report["fetched"] = len(entries)
            for entry in entries:
                entry["relevanceScore"] = relevance(entry)
                if _is_stale(entry, options.max_age_days, started):
                    report["stale"] += 1
                    continue
                fingerprint = content_fingerprint(entry)
                if entry["id"] in queue or entry["url"] in known_urls or fingerprint in known_fingerprints:
                    report["duplicates"] += 1
                    continue
                if not likely_relevant(entry):
                    report["lowRelevance"] += 1
                    continue
                if options.ai:
                    try:
                        entry["editorial"] = draft(entry, token)
                    except Exception as exc:
                        entry["draftError"] = f"{type(exc).__name__}: {str(exc)[:160]}"
                queue[entry["id"]] = entry
                queue_changed = True
                known_urls.add(entry["url"])
                known_fingerprints.add(fingerprint)
                report["newCandidates"] += 1
            report["status"] = "limited" if desired_status else "ok"
            if desired_status:
                report["reason"] = source.get("note", "manual source evidence required")
            report["successRate"] = 1.0
        except Exception as exc:
            report["httpStatus"] = getattr(exc, "http_status", None)
            report["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        outcomes.append(report)
        print(
            f"{report['source']}: {report['status']} http={report['httpStatus']} "
            f"fetched={report['fetched']} new={report['newCandidates']} "
            f"duplicate={report['duplicates']} filtered={report['lowRelevance']} stale={report['stale']}"
        )
        if options.delay:
            time.sleep(options.delay)

    candidates = list(queue.values())
    completed = datetime.now(timezone.utc)
    failures = [row for row in outcomes if row["status"] == "failed"]
    summary = {
        "fetched": sum(row["fetched"] for row in outcomes),
        "newCandidates": sum(row["newCandidates"] for row in outcomes),
        "duplicates": sum(row["duplicates"] for row in outcomes),
        "lowRelevance": sum(row["lowRelevance"] for row in outcomes),
        "stale": sum(row["stale"] for row in outcomes),
        "failedSources": len(failures),
    }
    run_report = {
        "schemaVersion": "1.0",
        "runId": started.strftime("%Y%m%dT%H%M%SZ"),
        "startedAt": started.isoformat(),
        "completedAt": completed.isoformat(),
        "status": "partial" if failures else "success",
        "collection": {**summary, "platforms": _platform_totals(outcomes)},
        "aiReview": {"requested": 0, "approved": 0, "needsHumanReview": 0, "rejected": 0, "failed": 0},
        "publication": {"eligible": 0, "actualAdded": 0, "mode": "manual-gate"},
        "sources": outcomes,
        "failures": [
            {"source": row["source"], "httpStatus": row.get("httpStatus"), "error": row.get("error", "unknown")}
            for row in failures
        ],
    }

    if queue_changed or candidates != previous_candidates:
        queue_path.write_text(
            json.dumps({"updatedAt": completed.isoformat(), "candidates": candidates}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    (BASE / "source_status.json").write_text(
        json.dumps(
            {
                "checkedAt": completed.isoformat(),
                "summary": summary,
                "results": outcomes,
                "manualCount": sum(row["status"] == "manual" for row in outcomes),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (BASE / "run_report.json").write_text(json.dumps(run_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("COLLECTION_SUMMARY " + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    print(f"Queued {len(queue)} candidates for editorial review; publication remains a separate gate")
    return run_report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ai", action="store_true", help="draft only; independent review remains separate")
    parser.add_argument("--limit", type=int, default=8, help="maximum relevant candidates considered per source")
    parser.add_argument("--max-age-days", type=int, default=180)
    parser.add_argument("--delay", type=float, default=0.75, help="polite delay between automatic sources")
    parser.add_argument("--source", action="append", default=[], help="limit collection to exact source or platform name")
    options = parser.parse_args()
    options.limit = max(1, min(options.limit, 30))
    options.max_age_days = max(1, options.max_age_days)
    options.delay = max(0, min(options.delay, 5))
    try:
        collect(options)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
