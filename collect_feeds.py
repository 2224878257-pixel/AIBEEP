"""Collect official RSS/Atom metadata into a review queue; no automatic publication.

Run `python3 collect_feeds.py`. Optional `--ai` with DEEPSEEK_API_KEY for original
Chinese summaries based only on feed excerpts, never third-party full articles.
"""
import argparse
import datetime as dt
import hashlib
import html
import json
import os
from pathlib import Path
import re
import urllib.request
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
from deepseek_client import generate_json

BASE = Path(__file__).resolve().parent
ATOM = "{http://www.w3.org/2005/Atom}"
BUSINESS_WORDS = (
    "advertis", "marketing", "ads ", "ad campaign", "campaign", "conversion", "commerce",
    "customer", "creative", "lead gen", "business", "merchant", "shopping", "attribution",
    "投放", "广告", "获客", "转化", "营销", "素材", "商家", "电商", "线索", "千川", "聚光"
)
AI_WORDS = ("ai", "agent", "copilot", "automation", "模型", "智能", "自动化")


def relevance(entry):
    """Conservative metadata triage; DeepSeek audits actual source later."""
    text = " ".join([entry.get("title", ""), entry.get("excerpt", "")]).lower()
    business_hits = sum(token in text for token in BUSINESS_WORDS)
    ai_hits = sum(token in text for token in AI_WORDS)
    return min(100, business_hits * 22 + min(ai_hits, 2) * 10)


def likely_relevant(entry):
    return relevance(entry) >= 22

def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()

def value(node, tag):
    child = node.find(tag)
    return "" if child is None else "".join(child.itertext()).strip()

def parse_feed(xml_bytes, source):
    root = ET.fromstring(xml_bytes)
    items = root.findall(".//item") or root.findall(f".//{ATOM}entry")
    found = []
    for node in items:
        atom = node.tag.endswith("entry")
        title = clean(value(node, f"{ATOM}title" if atom else "title"))
        if atom:
            link = next((e.attrib.get("href", "") for e in node.findall(f"{ATOM}link") if e.attrib.get("rel", "alternate") == "alternate"), "")
            summary = value(node, f"{ATOM}summary") or value(node, f"{ATOM}content")
            pub = value(node, f"{ATOM}published") or value(node, f"{ATOM}updated")
        else:
            link, summary, pub = value(node, "link"), value(node, "description"), value(node, "pubDate")
        if not title or not link.startswith("https://"):
            continue
        ident = hashlib.sha256(link.split("#")[0].rstrip("/").encode()).hexdigest()[:16]
        found.append({"id": ident, "title": title, "url": link, "source": source["name"], "category": source["category"], "excerpt": clean(summary)[:1000], "published": pub, "reviewStatus": "pending"})
    return found

def draft(entry, token):
    return generate_json(
        "根据提供的标题和资料摘录生成原创中文编辑稿，不得编造数据，不得声称阅读了更多材料，不得逐段翻译或复制第三方全文。返回字段 title、summary、intro、sections；sections 最多3项，各含 title 和 paragraphs 字符串数组。",
        {"title": entry["title"], "excerpt": entry["excerpt"], "source": entry["source"]},
        token=token,
    )

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ai", action="store_true")
    ap.add_argument("--limit", type=int, default=8)
    opt = ap.parse_args()
    token = os.getenv("DEEPSEEK_API_KEY", "")
    if opt.ai and not token:
        ap.error("--ai requires DEEPSEEK_API_KEY")
    path = BASE / "review_queue.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"candidates": []}
    previous_candidates = old.get("candidates", [])
    queue = {e["id"]: e for e in previous_candidates}
    registry = json.loads((BASE / "feed_sources.json").read_text(encoding="utf-8"))
    outcomes = []
    for source in registry["feeds"]:
        if not source.get("enabled", True):
            continue
        report = {"source":source["name"], "platform":source.get("platform", ""),"status":"failed", "fetched":0,"new":0,"filtered":0}
        try:
            if urlsplit(source["url"]).scheme != "https":
                raise ValueError("feed must use HTTPS")
            req = urllib.request.Request(source["url"], headers={"User-Agent": "AIBEEP editorial RSS reader"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                entries = parse_feed(resp.read(2_000_000), source)[:opt.limit]
            report["fetched"] = len(entries)
            for entry in entries:
                if entry["id"] in queue:
                    continue
                entry["relevanceHint"] = relevance(entry)
                entry["platform"] = source.get("platform", "")
                entry["region"] = source.get("region", "")
                if not likely_relevant(entry):
                    report["filtered"] += 1
                    continue
                if opt.ai:
                    try:
                        entry["editorial"] = draft(entry, token)
                    except Exception as exc:
                        entry["draftError"] = str(exc)[:200]
                queue[entry["id"]] = entry
                report["new"] += 1
            report["status"] = "ok"
            print(f"{source['name']}: {len(entries)} fetched")
        except Exception as exc:
            report["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
            print(f"{source['name']}: unavailable ({type(exc).__name__}: {exc})")
        outcomes.append(report)
    candidates = list(queue.values())
    # A successful poll with no new candidate must not create a meaningless bot commit.
    if candidates != previous_candidates:
        path.write_text(json.dumps({"updatedAt": dt.datetime.now(dt.timezone.utc).isoformat(), "candidates": candidates}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (BASE / "source_status.json").write_text(json.dumps({"checkedAt":dt.datetime.now(dt.timezone.utc).isoformat(),"results":outcomes,"watchCount":len(registry.get("watch_pages", []))},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"Queued {len(queue)} candidates for editorial review")

if __name__ == "__main__":
    main()
