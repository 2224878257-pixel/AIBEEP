"""Batch budgets, candidate provenance, evidence links and daily diversity caps."""
import json
import hashlib
import math
from collections import Counter
from datetime import datetime, timedelta
from urllib.parse import urlsplit, urljoin
from pathlib import Path
from bs4 import BeautifulSoup
from public_web import public_get, public_url
from search_discovery import discover, candidate_sources

DEFAULT=json.loads((Path(__file__).parent/'collection_config.json').read_text(encoding='utf-8'))


def load_json(path,default):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def prepare(root,now,check_only=False):
    config={**DEFAULT,**load_json(root/'collection_config.json',{})}
    results,search=discover(config,root=root,now=now) if not check_only and (root/'discovery_keywords.json').exists() else ([],{'state':'check_only','enabled':False,'queries':0,'discovered_urls':0})
    for item in load_json(root/'manual_submissions.json',[]):
        try:
            public_url(item['url'])
            results.append({'url':item['url'],'language':item.get('language','unknown'),
                            'discovery_path':'manual','max_age_days':365})
        except (ValueError,OSError,KeyError,TypeError):
            continue
    pool=candidate_sources(results,load_json(root/'candidate_sources.json',[]),now.isoformat())
    grouped={}
    for result in results:
        host=urlsplit(result['url']).hostname
        grouped.setdefault(host,[]).append(result)
    sources=[{'name':host,'ch':'general','kind':'community','url':items[0]['url'],
              'hosts':[host],'pattern':'/.+','adapter':'discovered_urls','dynamic':True,
              'http_only':True,'results':items,'limit':5,'web_limits':{'timeout':config['search_request_timeout'],'delay':config['domain_delay_seconds'],'retries':config['request_retries']}} for host,items in grouped.items()]
    return config,sources,search,pool


def evidence_links(html,url):
    soup=BeautifulSoup(html,'html.parser')
    scope=soup.select_one('article,.article-content,.entry-content,.post-content') or soup
    result=[]
    for a in scope.select('a[href]'):
        target=urljoin(url,a['href'])
        label=a.get_text(' ',strip=True)
        if any(k in (target+' '+label).lower() for k in ('pricing','changelog','documentation','官网','定价','官方文档','原文','原作者','github.com/')):
            result.append({'url':target,'label':label[:160]})
    return list({r['url']:r for r in result if r['url']!=url}.values())[:8]


def verify_links(article,config,budget):
    """Read small primary evidence pages; link existence alone is not corroboration."""
    pages=[]
    for ref in article.get('evidence_candidates',[])[:config['max_evidence_pages']]:
        if budget['read_urls']>=config['max_new_urls']:
            break
        try:
            public_url(ref['url'])
            budget['read_urls']+=1
            response=public_get(ref['url'],timeout=10,retries=0,delay=config['domain_delay_seconds'])
            soup=BeautifulSoup(response.content,'html.parser')
            body=soup.select_one('article,main') or soup
            for tag in body.select('script,style,nav,footer'):
                tag.decompose()
            text=body.get_text(' ',strip=True)
            if len(text)>=180 and not any(k in text[:200].lower() for k in ('captcha','access denied','just a moment')):
                pages.append({'url':response.url,'label':ref['label'],'excerpt':text[:1800],
                              'status':'read_public_page_not_independent_verification'})
        except Exception:
            continue
    article['evidence_pages']=pages


def provenance(article,source,context,now):
    article.update(original_url=context.get('url',article['url']),canonical_url=article['url'],
                   discovery_path=context.get('discovery_path','subscription'),
                   search_provider=context.get('search_provider'),search_query=context.get('search_query'),
                   query_group=context.get('query_group'),body_obtained=True,
                   collected_at=now.isoformat(),source_domain=urlsplit(article['url']).hostname)


def finish_provenance(row,article,ai):
    # DOM context is internal extraction metadata, not a public article mirror.
    row['images']=[{k:v for k,v in image.items() if k not in {'context_before','context_after'}} for image in row.get('images',[])]
    for key in ('original_url','canonical_url','discovery_path','search_provider','search_query','query_group','body_obtained','collected_at','source_domain'):
        row[key]=article.get(key)
    row['event_id']=hashlib.sha256((article.get('canonical_url') or article['url']).encode()).hexdigest()[:16]
    # Model-proposed references can only cite URLs whose full pages were actually read.
    available={article['url']}|{r['url'] for r in article.get('evidence_pages',[])}
    row['fact_sources']=[{'fact':str(r.get('fact',''))[:400],'url':r['url']}
                        for r in ai.get('fact_sources',[]) if isinstance(r,dict) and r.get('url') in available][:8]
    row['evidence_links']=[{'url':r['url'],'label':r['label'],'status':r['status']} for r in article.get('evidence_pages',[])]


def select_publications(staged,existing,config,now):
    """Existing editorial/history is preserved; caps apply to new automated additions."""
    today=[]
    for row in existing:
        try:
            if row.get('score_type')=='editorial_ranking' and datetime.fromisoformat(row['collected_at']).astimezone(now.tzinfo).date()==now.date():
                today.append(row)
        except (KeyError,TypeError,ValueError):
            pass
    remaining=max(0,config['max_publications_per_day']-len(today))
    refreshes=[entry for entry in staged if entry.get('refresh_only')]
    ordered=sorted([entry for entry in staged if not entry.get('refresh_only')],key=lambda r:r['row'].get('score',0),reverse=True)
    target=min(config['max_publications_per_day'],len(today)+len(ordered))
    # Integer rounding permits one item when there are fewer than five selections.
    per_source=max(1,math.floor(target*config['max_source_share']))
    counts=Counter(r.get('source_domain') or r.get('src') for r in today)
    accepted,held=[],[]
    for entry in ordered:
        host=entry['row'].get('source_domain') or entry['row']['src']
        if len(accepted)<remaining and counts[host]<per_source:
            accepted.append(entry);counts[host]+=1
        else:
            held.append(entry)
    # Tighten the cap after selection so uneven supply cannot inflate its denominator.
    while accepted:
        cap=max(1,math.floor((len(today)+len(accepted))*config['max_source_share']))
        counts=Counter(r.get('source_domain') or r.get('src') for r in today)
        kept=[]
        for entry in accepted:
            host=entry['row'].get('source_domain') or entry['row']['src']
            if counts[host]<cap:
                kept.append(entry);counts[host]+=1
            else:
                held.append(entry)
        if len(kept)==len(accepted):
            break
        accepted=kept
    return refreshes+accepted,held
