"""Replaceable search discovery. Search snippets are never article bodies."""
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit
import requests
from public_web import public_url

ROOT=Path(__file__).parent


class SearchProvider:
    def search(self, query, count=5, language='en', country='US', freshness='pw'):
        raise NotImplementedError


class BraveSearch(SearchProvider):
    def __init__(self,key,timeout=15):
        self.key=key
        self.timeout=timeout

    def search(self,query,count=5,language='en',country='US',freshness='pw'):
        response=requests.get('https://api.search.brave.com/res/v1/web/search',
            headers={'X-Subscription-Token':self.key,'Accept':'application/json'},
            params={'q':query,'count':min(count,10),'search_lang':'zh-hans' if language=='zh' else 'en',
                    'country':country,'freshness':freshness,'safesearch':'moderate'},timeout=self.timeout)
        response.raise_for_status()
        return [{'url':r['url'],'title':r.get('title',''),'snippet':r.get('description','')}
                for r in response.json().get('web',{}).get('results',[]) if r.get('url')]


def plan_queries(groups,slot):
    """Every batch includes both failure and demand queries, in both languages."""
    queries=[]
    for group in groups:
        for language in ('zh','en'):
            terms=group[language]
            query=terms[slot%len(terms)]
            domains=group.get('domains',[])
            # Half of batches stay open-web; half also explore a named domain.
            if slot%2 and domains:
                query+=' site:'+domains[(slot//2)%len(domains)]
            queries.append({'query':query,'group':group['id'],'language':language,
                            'country':'CN' if language=='zh' else 'US',
                            'freshness':'py' if group['id'] in {'first_customer','small_business','failure','digital_products'} else 'pw'})
    # Reserve early slots for business projects/methods; keep failure and demand
    # ahead of auxiliary workflow/platform updates even under reduced budgets.
    order=('first_customer','small_business','failure','demand','digital_products','platform_change','workflow')
    return [q for group in order for q in queries if q['group']==group]



def discover(config,provider=None,root=ROOT,now=None):
    now=now or datetime.now(timezone.utc)
    provider_name=config.get('search_provider','brave')
    key=os.getenv('BRAVE_SEARCH_API_KEY','')
    report={'provider':provider_name,'enabled':False,'queries':0,'cache_hits':0,'discovered_urls':0,'errors':[],'state':'not_configured'}
    if provider is None:
        if provider_name!='brave':
            report.update(state='unsupported_provider',errors=['Only the Brave adapter is implemented; select brave'])
            return [],report
        if not key:
            return [],report
        if os.getenv('BRAVE_ALLOW_RESULT_STORAGE','').lower() not in {'true','1','yes'}:
            report['state']='storage_rights_not_confirmed'
            return [],report
        provider=BraveSearch(key,config['search_request_timeout'])
    report.update(enabled=True,state='running')
    path=root/'search_cache.json'
    cache=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    groups=json.loads((root/'discovery_keywords.json').read_text(encoding='utf-8'))
    slot=int(now.timestamp()//43200)
    results=[]
    for spec in plan_queries(groups,slot)[:config['max_search_queries']]:
        cache_key=hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()
        cached=cache.get(cache_key)
        try:
            if cached and datetime.fromisoformat(cached['at'])>now-timedelta(hours=config['search_cache_hours']):
                items=cached['results'];report['cache_hits']+=1
            else:
                report['queries']+=1
                items=provider.search(spec['query'],config['results_per_query'],spec['language'],spec['country'],spec['freshness'])
                cache[cache_key]={'at':now.isoformat(),'results':items}
            for item in items[:config['results_per_query']]:
                try:
                    public_url(item['url'])
                    results.append({**item,'discovery_path':'search','search_provider':provider_name,
                                    'search_query':spec['query'],'query_group':spec['group'],
                                    'language':spec['language'],'max_age_days':config.get('evergreen_article_days',365) if spec['freshness']=='py' else config.get('max_article_days',7)})
                except (ValueError,OSError):
                    report['errors'].append({'group':spec['group'],'error':'Unsafe or unresolved result URL'})
        except Exception as exc:
            # Never persist response bodies, request URLs with credentials, or headers.
            code=getattr(getattr(exc,'response',None),'status_code',None)
            report['errors'].append({'group':spec['group'],'error':f'HTTP {code}' if code else type(exc).__name__})
            if code in {401,402,403,429}:
                break
    root.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(dict(list(cache.items())[-300:]),ensure_ascii=False),encoding='utf-8');tmp.replace(path)
    unique={r['url']:r for r in results}
    report.update(state='partial' if report['errors'] else 'success',discovered_urls=len(unique))
    return list(unique.values()),report


def candidate_sources(results,previous,now):
    """Unknown domains stay candidates; one search hit never creates a subscription."""
    pool={r['domain']:r for r in previous}
    for result in results:
        try:
            public_url(result['url'])
        except (ValueError,OSError):
            continue
        domain=urlsplit(result['url']).hostname
        row=pool.setdefault(domain,{'name':domain,'domain':domain,'language':result.get('language','unknown'),
            'topics':[],'discovery_method':result.get('discovery_path','search'),'sample_articles':[],
            'accessibility':'not_read','promotion_tendency':'not_assessed','priority':'review',
            'approved_for_subscription':False,'quality_passed_samples':[]})
        row['last_discovered_at']=now
        row['topics']=list(dict.fromkeys(row['topics']+[result.get('query_group','unknown')]))[:10]
        row['sample_articles']=list(dict.fromkeys(row['sample_articles']+[result['url']]))[-10:]
    return list(pool.values())[-1000:]
