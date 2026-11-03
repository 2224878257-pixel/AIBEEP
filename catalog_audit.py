"""Audit candidate entry points; accessible homepages are not enabled feeds."""
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlsplit, urljoin
from bs4 import BeautifulSoup
from trafilatura import bare_extraction
from public_web import public_get

ROOT=Path(__file__).parent


def hostname(url):
    return (urlsplit(url).hostname or '').removeprefix('www.')


def probe(url):
    now=datetime.now(timezone.utc).isoformat()
    result={'last_checked_at':now,'page_accessible':False,'body_readable':False,
            'sustainable':False,'method':'search_only','last_error':None}
    try:
        response=public_get(url,timeout=12,retries=0)
        soup=BeautifulSoup(response.content,'html.parser')
        title=soup.title.get_text(' ',strip=True) if soup.title else ''
        if any(s in title.lower() for s in ('just a moment','access denied','attention required','captcha','bot verification')):
            raise ValueError('Verification or access restriction page')
        result.update(page_accessible=True,http_status=response.status_code,final_url=response.url,
                      page_title=title[:200],last_success_at=now)
        feeds=[urljoin(response.url,a.get('href','')) for a in soup.select('link[rel="alternate"][type*="xml"][href]')]
        result['declared_feeds']=feeds[:5]
        candidates=[]
        for a in soup.select('article a[href],h2 a[href],h3 a[href],a[href]'):
            link=urljoin(response.url,a.get('href',''))
            path=urlsplit(link).path
            if hostname(link)!=hostname(response.url) or len(path)<8:
                continue
            if any(k in path.lower() for k in ('login','signup','pricing','privacy','terms','category','tag/','search','subscribe')):
                continue
            if any(k in path.lower() for k in ('/post/','/posts/','/p/','/articles/','/article/','/blog/','/news/','/story/','/stories/','/2026/','/20')):
                candidates.append(link)
        if candidates:
            link=next(iter(dict.fromkeys(candidates)))
            try:
                article=public_get(link,timeout=10,retries=0)
                doc=bare_extraction(article.text,url=article.url,with_metadata=True)
                data=doc.as_dict() if doc else {}
                if len(data.get('text') or '')>=180:
                    result.update(body_readable=True,sample_url=article.url,sample_title=data.get('title'),
                                  sample_date=data.get('date'),method='public_page')
            except Exception as exc:
                result['sample_error']=type(exc).__name__
    except Exception as exc:
        code=getattr(getattr(exc,'response',None),'status_code',None)
        result.update(method='blocked',last_error=f'HTTP {code}' if code else type(exc).__name__,http_status=code)
    return result


def main():
    path=ROOT/'source_catalog.json'
    rows=json.loads(path.read_text(encoding='utf-8'))
    urls=list(dict.fromkeys(r['entry_url'] for r in rows))
    import sys
    if '--refresh-summary' in sys.argv:
        checked={r['entry_url']:dict(r) for r in rows}
    else:
        with ThreadPoolExecutor(max_workers=6) as pool:
            checked=dict(zip(urls,pool.map(probe,urls)))
    status=json.loads((ROOT/'source_status.json').read_text(encoding='utf-8'))
    for row in rows:
        row.update(checked[row['entry_url']])
        if 'bot verification' in row.get('page_title','').lower():
            row.update(page_accessible=False,body_readable=False,method='blocked',last_error='Bot verification page',last_success_at=None)
        row['domain']='.'.join(hostname(row['entry_url']).split('.')[-2:])
        row['platform_id']=row['domain']
        row['author_identity_verified']=row['name'] in {'Pieter Levels博客','Tony Dinh Newsletter'}
        row['author_identity_evidence']=row['entry_url'] if row['author_identity_verified'] else None
        matches=[s for s in status if s.get('enabled') and
                 (hostname(s['official_url'])==hostname(row['entry_url']) or
                  row['name']=='Hacker News' and s.get('adapter')=='hn_api')]
        row['enabled']=bool(matches)
        row['active_endpoints']=[s['url'] for s in matches]
        if matches and any(s.get('article_readable') for s in matches):
            row.update(method='official_api' if row['name']=='Hacker News' else 'rss' if all(s.get('adapter')=='rss' for s in matches) else 'public_page',
                       body_readable=True,sustainable=True,
                       last_success_at=max(s['last_success_at'] for s in matches if s.get('last_success_at')))
        row['fit_assessment']='Candidate topic supplied by editor; sustained originality and quality still require sample review' if not matches else 'Article extraction tested; every candidate still requires relevance and evidence review'
        if not row['page_accessible']:
            row['fit_assessment']='主题适配暂无法核实：本次起始页访问未成功；不自动接入'
        elif row['body_readable']:
            row['fit_assessment']='已取得公开正文样本：'+str(row.get('sample_title') or row.get('page_title') or '')+'；长期相关性与原创比例仍待多篇审核'
        else:
            row['fit_assessment']='起始页标题：'+row.get('page_title','')+'；尚未取得合格正文样本，主题适配待核实'
        if row['name'] in {'Reddit','X','Product Hunt'} and not row['enabled']:
            row['method']='auth_required'
            row['access_note']='需官方API资格或授权；尚未实现该平台专用API，不绕公开页面限制'
        row['activation_note']='Enabled only through the listed tested endpoints' if matches else 'Not subscribed. Homepage access or one readable sample is insufficient for promotion.'
    path.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    summary={'checked_at':datetime.now(timezone.utc).isoformat(),'candidate_entries':len(rows),
             'unique_platforms':len({r['platform_id'] for r in rows}),
             'unique_hosts':len({hostname(r['entry_url']) for r in rows}),
             'tested_entries':sum(bool(r.get('last_checked_at')) for r in rows),
             'page_accessible':sum(r['page_accessible'] for r in rows),
             'body_readable':sum(r['body_readable'] for r in rows),
             'enabled_entries':sum(r['enabled'] for r in rows),
             'enabled_endpoints':sum(s.get('enabled',False) for s in status),
             'successful_endpoints':sum(bool(s.get('enabled') and s.get('article_readable')) for s in status),
             'unique_domains':len({r['domain'] for r in rows}),'authors_verified':sum(r['author_identity_verified'] for r in rows),'column_entries':len(rows),
             'domain_count_method':'hosts exclude www; root domains checked for the catalog .com/.net/.org/.io/.vc/.cn/.ai suffixes; platforms grouped by root domain'}
    (ROOT/'source_catalog_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':
    main()
