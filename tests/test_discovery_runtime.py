import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import Mock,patch
from urllib.parse import urlsplit
import socket

import public_web as web
import search_discovery as search
from discovery_runtime import DEFAULT, select_publications, finish_provenance


class PublicURLTests(unittest.TestCase):
    def test_private_loopback_metadata_and_mixed_dns_are_rejected(self):
        for ip in ('127.0.0.1','10.0.0.1','169.254.169.254','192.168.1.1','::1','fc00::1'):
            with patch.object(socket,'getaddrinfo',return_value=[(0,0,0,'',(ip,443))]):
                with self.assertRaises(ValueError):web.public_url('https://example.com/a')
        with patch.object(socket,'getaddrinfo',return_value=[(0,0,0,'',('1.1.1.1',443)),(0,0,0,'',('10.0.0.1',443))]):
            with self.assertRaises(ValueError):web.public_url('https://example.com/a')

    def test_localhost_credentials_scheme_and_nonstandard_ports_rejected(self):
        for url in ('https://localhost/x','http://test.local/x','file:///etc/passwd','https://user:pw@example.com/','https://example.com:8000/'):
            with self.assertRaises(ValueError):web.public_url(url)

    def test_redirect_is_checked_before_second_request(self):
        raw=Mock(status=302,headers={'Location':'http://169.254.169.254/latest/meta-data/'})
        pool=Mock();pool.urlopen.return_value=raw
        def addresses(host,port,**kwargs):
            return [(0,0,0,'',('169.254.169.254' if host=='169.254.169.254' else '1.1.1.1',port))]
        with patch.object(socket,'getaddrinfo',side_effect=addresses),patch.object(web.urllib3,'HTTPSConnectionPool',return_value=pool) as factory:
            with self.assertRaises(ValueError):web.public_get('https://example.com/',delay=0)
        self.assertEqual(pool.urlopen.call_count,1)
        self.assertEqual(factory.call_args.args[0],'1.1.1.1')
        self.assertEqual(factory.call_args.kwargs['server_hostname'],'example.com')


class SearchTests(unittest.TestCase):
    def test_no_search_key_does_not_use_development_search(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(search.os.environ,{'BRAVE_SEARCH_API_KEY':''}),patch.object(search.requests,'get') as request:
            results,report=search.discover(DEFAULT,root=Path(tmp))
        self.assertEqual(results,[]);self.assertEqual(report['state'],'not_configured');request.assert_not_called()

    def test_storage_rights_required_before_persisting_search_results(self):
        with patch.dict(search.os.environ,{'BRAVE_SEARCH_API_KEY':'test','BRAVE_ALLOW_RESULT_STORAGE':''}),patch.object(search.requests,'get') as request:
            results,report=search.discover(DEFAULT)
        self.assertEqual(report['state'],'storage_rights_not_confirmed');request.assert_not_called()

    def test_query_budget_cache_and_provenance_without_snippet_as_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'discovery_keywords.json').write_text(json.dumps([{'id':'failure','zh':['获客失败'],'en':['no customers']}]))
            provider=Mock();provider.search.return_value=[{'url':'https://example.com/a','title':'Story','snippet':'Search lead only'}]
            with patch.object(search,'public_url',return_value='1.1.1.1'):
                results,report=search.discover({**DEFAULT,'max_search_queries':1},provider,root)
                cached,again=search.discover({**DEFAULT,'max_search_queries':1},provider,root)
            self.assertEqual(provider.search.call_count,1);self.assertEqual(report['queries'],1)
            self.assertEqual(again['cache_hits'],1);self.assertNotIn('body',results[0])
            self.assertEqual(results[0]['discovery_path'],'search');self.assertEqual(results[0]['query_group'],'failure')

    def test_domain_hit_never_automatically_becomes_subscription(self):
        with patch.object(search,'public_url',return_value='1.1.1.1'):
            pool=search.candidate_sources([{'url':'https://example.com/a','language':'en'}],[],'2026-11-03')
        self.assertFalse(pool[0]['approved_for_subscription']);self.assertEqual(pool[0]['quality_passed_samples'],[])


class PublicationBudgetTests(unittest.TestCase):
    def test_existing_article_refresh_does_not_consume_new_publication_budget(self):
        refresh={'row':{'src':'A','source_domain':'a.example','score':80},'refresh_only':True}
        accepted,held=select_publications([refresh],[],{**DEFAULT,'max_publications_per_day':0},datetime.now(timezone.utc))
        self.assertEqual(accepted,[refresh])
        self.assertEqual(held,[])

    def test_daily_cap_and_source_share_hold_completed_items(self):
        staged=[{'row':{'src':'A','source_domain':'a.example','score':100-n}} for n in range(5)]+[{'row':{'src':'B','source_domain':'b.example','score':80}}]
        accepted,held=select_publications(staged,[],{**DEFAULT,'max_publications_per_day':5},datetime.now(timezone.utc))
        self.assertEqual(len(accepted),2);self.assertEqual(len(held),4)
        self.assertEqual(len({r['row']['source_domain'] for r in accepted}),2)
        accepted,held=select_publications(staged,[],{**DEFAULT,'max_publications_per_day':0},datetime.now(timezone.utc))
        self.assertEqual(accepted,[]);self.assertEqual(len(held),6)

    def test_fact_sources_must_have_been_read(self):
        row={};article={'url':'https://example.com/a','canonical_url':'https://example.com/a','evidence_pages':[{'url':'https://product.example/pricing','label':'pricing','status':'read_public_page_not_independent_verification'}]}
        finish_provenance(row,article,{'fact_sources':[{'fact':'price','url':'https://product.example/pricing'},{'fact':'fake proof','url':'https://unread.example/'}]})
        self.assertEqual(len(row['fact_sources']),1)
        self.assertEqual(row['fact_sources'][0]['url'],'https://product.example/pricing')
