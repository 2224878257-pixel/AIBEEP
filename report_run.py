"""Validate and print the latest machine-readable automation report."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_report(path=None):
    target = Path(path) if path else ROOT / "run_report.json"
    report = json.loads(target.read_text(encoding="utf-8"))
    for key in ("runId", "status", "collection", "aiReview", "publication", "sources"):
        if key not in report:
            raise ValueError(f"run report missing {key}")
    return report


def markdown(report):
    collection = report["collection"]
    ai = report["aiReview"]
    publication = report["publication"]
    lines = [
        "## AIBEEP V16.1 运行汇总",
        "",
        f"- 运行：`{report['runId']}`（{report['status']}）",
        f"- 抓取：{collection['fetched']}；新增候选：{collection['newCandidates']}；重复：{collection['duplicates']}",
        f"- 低相关过滤：{collection['lowRelevance']}；过期过滤：{collection['stale']}；失败信源：{collection['failedSources']}",
        f"- AI 审核：{ai['requested']}；通过：{ai['approved']}；待人工：{ai['needsHumanReview']}；拒绝：{ai['rejected']}；失败：{ai['failed']}",
        f"- 可人工发布：{publication['eligible']}；实际新增文章：{publication['actualAdded']}；模式：{publication['mode']}",
        "",
        "### 平台明细",
        "",
        "| 平台 | 抓取 | 新增 | 重复 | 低相关 | 失败 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for platform, row in collection.get("platforms", {}).items():
        lines.append(
            f"| {platform} | {row['fetched']} | {row['newCandidates']} | {row['duplicates']} | "
            f"{row['lowRelevance']} | {row['failures']} |"
        )
    if report.get("failures"):
        lines.extend(["", "### 失败信源", ""])
        for failure in report["failures"]:
            lines.append(f"- {failure['source']}：HTTP {failure.get('httpStatus')}；{failure.get('error')}")
    return "\n".join(lines) + "\n"


def main():
    report = load_report()
    text = markdown(report)
    print(text)
    print("RUN_REPORT_JSON " + json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write(text)


if __name__ == "__main__":
    main()
