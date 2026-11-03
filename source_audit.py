"""Probe configured public discovery endpoints and one full article, without AI."""
import json
from datetime import datetime, timezone
from pathlib import Path
from scraper import Collector, atomic_json, safe_error

ROOT = Path(__file__).parent


def audit_source(source, collector=None):
    collector = collector or Collector()
    now = datetime.now(timezone.utc).isoformat()
    result = dict(source)
    result.update(last_checked_at=now, discovery_count=0, article_readable=False)
    if not source.get('enabled'):
        return result
    try:
        urls = collector.discover(source, 3)
        result['discovery_count'] = len(urls)
        if not urls:
            raise ValueError('No matching article links in current public listing')
        errors = []
        for url in urls:
            try:
                article = collector.article(url, source)
                result.update(last_success_at=now, last_error=None, article_readable=True,
                              sample_url=article['url'], sample_title=article['title'],
                              sample_published_at=article['published_at'])
                break
            except Exception as exc:
                errors.append(safe_error(exc))
        if not result['article_readable']:
            raise ValueError('; '.join(errors))
    except Exception as exc:
        result.update(last_error=safe_error(exc), last_error_at=now)
    return result


def main():
    from concurrent.futures import ThreadPoolExecutor
    sources = json.loads((ROOT/'discovery_sources.json').read_text(encoding='utf-8'))
    status_path = ROOT/'source_status.json'
    previous = {s['name']:s for s in json.loads(status_path.read_text(encoding='utf-8'))} if status_path.exists() else {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        rows = list(pool.map(audit_source, sources))
    for row in rows:
        if not row.get('last_success_at'):
            row['last_success_at'] = previous.get(row['name'],{}).get('last_success_at')
    atomic_json(status_path, rows)
    for row in rows:
        print(json.dumps({k:row.get(k) for k in ('name','enabled','discovery_count','article_readable','last_error')},ensure_ascii=False))


if __name__ == '__main__':
    main()
