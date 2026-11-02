import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from datetime import datetime, timedelta

import scraper as s


class PlatformDiscoveryTests(unittest.TestCase):
    def test_yunyingpai_publication_field_survives_malformed_jsonld(self):
        html='<html><h1>快手投放案例</h1><script type="application/ld+json">{"images":["image",],"pubDate":"2026-10-30T10:10:48"}</script><article>'+('真实投放经验与方法。'*100)+'</article></html>'
        collector=s.Collector()
        source={'ch':'general','hosts':['www.yunyingpai.com'],'pattern':'/news/'}
        with patch.object(collector,'html',return_value=html):
            result=collector.article('https://www.yunyingpai.com/news/1.html',source)
        self.assertEqual(result['published_at'],'2026-10-30T10:10:48+08:00')

    def test_tencent_webview_follows_only_public_wechat_body(self):
        response=Mock()
        response.json.return_value={'code':0,'data':{'title':'腾讯投放指南','created_at':'2026-11-02',
            'content':json.dumps({'content':[{'type':'webview','url':'https://mp.weixin.qq.com/s/test'}]})}}
        linked=Mock(url='https://mp.weixin.qq.com/s/test')
        linked.content=('<div id="js_content">'+('具体投放方法。'*60)+'</div>').encode()
        source={'adapter':'tencent','hosts':['e.qq.com'],'pattern':'/latestnews/detail'}
        with patch.object(s,'request',side_effect=[response,linked]) as request:
            result=s.Collector().article('https://e.qq.com/latestnews/detail?pid=1',source)
        self.assertIn('具体投放方法',result['body'])
        self.assertEqual(result['published_at'],'2026-11-02T00:00:00+08:00')
        response.json.return_value['data']['content']=json.dumps({'content':[{'type':'webview','url':'https://private.example/s/test'}]})
        with patch.object(s,'request',return_value=response) as request:
            with self.assertRaises(ValueError):
                s.Collector().article('https://e.qq.com/latestnews/detail?pid=1',source)
            self.assertEqual(request.call_count,1)

    def test_site_search_keeps_platform_searches_interleaved(self):
        source={'adapter':'site_search','url':'https://example.com/','hosts':['example.com'],
                'pattern':'/news/','search_terms':['快手','千川']}
        def response(url,**kwargs):
            ids=[1,2] if kwargs['params']['s']=='快手' else [3]
            return Mock(content=''.join(f'<h2><a href="/news/{i}">文章</a></h2>' for i in ids).encode())
        with patch.object(s,'request',side_effect=response):
            self.assertEqual(s.Collector().discover(source,3),['https://example.com/news/1','https://example.com/news/3','https://example.com/news/2'])

    def test_expired_articles_survive_archive_but_leave_recent_feed(self):
        with tempfile.TemporaryDirectory() as d, patch.object(s, 'ROOT', Path(d)):
            stamp=(datetime.now(s.TZ)-timedelta(days=20)).isoformat()
            old=dict(id=123,url='https://example.com/old',title='old',desc='old',published_at=stamp)
            (Path(d)/'data.json').write_text(json.dumps([old]))
            (Path(d)/'sources.json').write_text('[{"name":"test","ch":"hw"}]')
            collector=Mock()
            collector.discover.return_value=[]
            with patch.dict(s.os.environ,{'DEEPSEEK_API_KEY':'test'}):
                s.run(Mock(check_sources=False,limit=1),collector)
                s.run(Mock(check_sources=False,limit=1),collector)
            self.assertEqual(json.loads((Path(d)/'data.json').read_text()),[])
            archive=json.loads((Path(d)/'archive.json').read_text())
            self.assertEqual(len(archive),1)
            self.assertEqual(archive[0]['id'],123)
            self.assertEqual(archive[0]['t'],'archive')

    def test_image_only_tencent_article_is_explicitly_unsupported(self):
        response = Mock()
        response.json.return_value = {'code': 0, 'data': {'title': '图片榜单',
            'content': '<p><img src="https://example.com/chart.jpg"></p>', 'created_at': '2026-11-01'}}
        with patch.object(s, 'request', return_value=response):
            with self.assertRaises(s.UnsupportedArticle):
                s.Collector().article('https://e.qq.com/latestnews/detail?pid=1',
                    {'adapter': 'tencent', 'hosts': ['e.qq.com'], 'pattern': '/latestnews/detail'})

    def test_search_interleaves_platforms_and_preserves_dates(self):
        collector = s.Collector()
        source = dict(url='https://example.com/api', hosts=['example.com'],
                      pattern='/[0-9]+', adapter='wordpress_search', search_terms=['抖音', '快手'])
        def response(url, **kwargs):
            ids = [1, 2] if kwargs['params']['search'] == '抖音' else [3]
            result = Mock()
            result.json.return_value = [dict(link=f'https://example.com/{i}', date_gmt='2026-11-01T00:00:00') for i in ids]
            return result
        with patch.object(s, 'request', side_effect=response):
            self.assertEqual(collector.discover(source, 3), ['https://example.com/1', 'https://example.com/3', 'https://example.com/2'])
        self.assertEqual(s.date_value(collector.metadata['https://example.com/3']).hour, 8)

    def test_old_rss_candidates_do_not_consume_read_budget(self):
        with tempfile.TemporaryDirectory() as d, patch.object(s, 'ROOT', Path(d)):
            (Path(d) / 'data.json').write_text('[]')
            (Path(d) / 'sources.json').write_text('[{"name":"test","ch":"hw"}]')
            collector = s.Collector()
            collector.metadata = {'https://example.com/old': '2020-01-01T00:00:00Z'}
            collector.discover = Mock(return_value=list(collector.metadata))
            collector.article = Mock()
            with patch.dict(s.os.environ, {'DEEPSEEK_API_KEY': 'test'}):
                s.run(Mock(check_sources=False, limit=1), collector)
            collector.article.assert_not_called()


class ScraperTests(unittest.TestCase):
    def test_tmall_is_not_tencent_and_themes_are_independent(self):
        row=s.classify_row({'title':'天猫母婴双11观察','ch':'tx','cat':'case','src':'运营派 · 作者经验','source_kind':'community'})
        self.assertEqual(row['ch'],'tmall')
        self.assertEqual(row['cat'],'case')
        self.assertEqual(row['content_type'],'analysis')
        self.assertEqual(row['src'],'运营派')
        multi=s.classify_row({'title':'抖音、视频号新规则','source_kind':'community'})
        self.assertEqual(multi['ch'],'multi')
        self.assertEqual(multi['platforms'],['dj','wx'])
        generic=s.classify_row({'title':'潜客跟进七步法','ch':'hw','cat':'acq','source_kind':'community'})
        self.assertEqual(generic['ch'],'general')
        self.assertEqual(generic['content_type'],'experience')

    def test_body_sketch_dedupes_rewritten_titles(self):
        text='投放优化案例需要分别衡量素材点击率、实际转化成本和后续成交情况。' * 30
        a=dict(title='第一版标题：一次完整的广告素材优化复盘',desc='首个摘要',source_kind='community',published_at='2026-11-01',url='https://a.example/1',src='A',body_sketch=s.body_sketch(text))
        b={**a,'title':'标题完全改写：提升转化的实战方法','desc':'不同摘要','url':'https://b.example/1'}
        # Diverse text gives enough shingles for reliable content comparison.
        a['body_sketch']=s.body_sketch(''.join(str(i)+text for i in range(100)))
        b['body_sketch']=a['body_sketch'][:]
        rows,count=s.deduplicate_rows([a,b])
        self.assertEqual((len(rows),count),(1,1))

    def test_cached_front_items_do_not_consume_new_article_budget(self):
        with tempfile.TemporaryDirectory() as d, patch.object(s,'ROOT',Path(d)):
            stamp=datetime.now(s.TZ).isoformat()
            urls=[f'https://example.com/{i}' for i in range(4)]
            old=[dict(url=u,title=u,desc='description',published_at=stamp) for u in urls[:3]]
            (Path(d)/'data.json').write_text(json.dumps(old))
            (Path(d)/'sources.json').write_text('[{"name":"test","ch":"tx"}]')
            collector=Mock()
            collector.discover.return_value=urls
            collector.article.return_value=dict(url=urls[3],title='new',body='text',published_at=stamp)
            ai=dict(title='new',desc='summary',content='body',reason='reason',cat='data',tag='ad',score=80)
            with patch.dict(s.os.environ,{'DEEPSEEK_API_KEY':'test'}),patch.object(s,'enrich',return_value=ai) as enrich:
                s.run(Mock(check_sources=False,limit=1),collector)
            collector.discover.assert_called_once_with({'name':'test','ch':'tx'},5)
            self.assertEqual(enrich.call_count,1)
            self.assertEqual(len(json.loads((Path(d)/'data.json').read_text())),4)

    def test_recent_rejections_skipped_without_ai_cost(self):
        with tempfile.TemporaryDirectory() as d, patch.object(s,'ROOT',Path(d)):
            stamp=datetime.now(s.TZ).isoformat()
            (Path(d)/'data.json').write_text('[]')
            (Path(d)/'sources.json').write_text('[{"name":"test","ch":"general","kind":"community"}]')
            url='https://example.com/rejected'
            (Path(d)/'screening_cache.json').write_text(json.dumps({url:{'checked_at':stamp,'quality_version':s.QUALITY_VERSION}}))
            collector=Mock()
            collector.discover.return_value=[url]
            with patch.dict(s.os.environ,{'DEEPSEEK_API_KEY':'test'}),patch.object(s,'enrich') as enrich:
                s.run(Mock(check_sources=False,limit=1),collector)
            enrich.assert_not_called()
            collector.article.assert_not_called()
            self.assertEqual(json.loads((Path(d)/'run_report.json').read_text())['sources'][0]['rejected_cached'],1)

    def test_one_bad_candidate_does_not_block_valid_filter_results(self):
        with tempfile.TemporaryDirectory() as d, patch.object(s,'ROOT',Path(d)):
            (Path(d)/'data.json').write_text('[]')
            (Path(d)/'sources.json').write_text('[{"name":"test","ch":"general","kind":"community"}]')
            urls=['https://example.com/a','https://example.com/b']
            collector=Mock()
            collector.discover.return_value=urls
            collector.article.side_effect=[{'url':u,'title':'test','body':u,'published_at':datetime.now(s.TZ).isoformat()} for u in urls]
            with patch.dict(s.os.environ,{'DEEPSEEK_API_KEY':'test'}), patch.object(s,'enrich',side_effect=[ValueError('bad JSON'),{'relevant':False,'score':50}]):
                self.assertEqual(s.run(Mock(check_sources=False,limit=3),collector),0)
            result=json.loads((Path(d)/'collection_status.json').read_text())
            self.assertEqual(result['status'],'partial')
            self.assertEqual(result['ai_failures'],1)

    def test_cross_site_repost_merges_but_distinct_articles_remain(self):
        a={'title':'生活服务别抢关键词，用场景内容抢需求形成的时间差','desc':'通过场景内容抢需求形成的时间差，提前种草建立信任','source_kind':'community','published_at':'2026-10-31T10:00:00+08:00','src':'A','url':'https://a.example/1'}
        b={**a,'title':'生活服务投放别只抢关键词：用场景内容抢需求形成的时间差','src':'B','url':'https://b.example/1'}
        c={**a,'title':'Google Ads预算与出价设置的六个操作步骤','url':'https://a.example/2'}
        rows,count=s.deduplicate_rows([a,b,c])
        self.assertEqual(count,1)
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['also_reported_by'][0]['url'],b['url'])

    def test_retry_truncated_ai_output_then_succeed(self):
        data = dict(title='test',desc='summary',content='body',reason='reason',cat='case',tag='ad',ch='hw',score=80,relevant=True)
        bad, good = Mock(), Mock()
        bad.json.return_value = {'choices':[{'finish_reason':'length','message':{'content':'{'}}]}
        good.json.return_value = {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(data)}}]}
        with patch.object(s,'request',side_effect=[bad,good]) as request, patch.object(s.time,'sleep'):
            result=s.enrich({},'test')
        self.assertEqual(result['_attempts'],2)
        self.assertEqual(request.call_args.kwargs['json']['thinking'],{'type':'disabled'})

    def test_history_accumulates_daily_totals(self):
        with tempfile.TemporaryDirectory() as d, patch.object(s,'ROOT',Path(d)):
            report={'added':2,'sources':[{'source':'test','errors':[],'filtered':1,'duplicates':3,'cached':4}]}
            s.collection_status(report)
            s.collection_status(report)
            history=json.loads((Path(d)/'collection_history.json').read_text())
            self.assertEqual(len(history['days']),1)
            self.assertEqual(history['days'][0]['added'],4)
            self.assertEqual(history['days'][0]['duplicates'],6)
            self.assertEqual(history['days'][0]['runs'],2)

    def test_expanded_gate_accepts_relevant_analysis(self):
        base = {'relevant':True,'practical':True,'score':80,'actions':['在相同预算下对比两组素材的获客成本']}
        self.assertTrue(s.community_passes(base))
        self.assertTrue(s.community_passes({**base,'practical':False,'actions':[],'score':60}))
        self.assertFalse(s.community_passes({**base,'score':59}))
        self.assertFalse(s.community_passes({**base,'relevant':False}))

    def test_public_status_preserves_last_success_on_failure(self):
        with tempfile.TemporaryDirectory() as d, patch.object(s, 'ROOT', Path(d)):
            s.collection_status({'sources':[{'errors':['timeout']}],'added':2,'updated':1})
            good = json.loads((Path(d)/'collection_status.json').read_text())
            self.assertEqual(good['status'], 'partial')
            self.assertEqual(good['added'], 2)
            s.collection_status({}, failed=True)
            bad = json.loads((Path(d)/'collection_status.json').read_text())
            self.assertEqual(bad['status'], 'failed')
            self.assertEqual(bad['last_success_at'], good['last_success_at'])

    def test_specialist_platform_outranks_model_label(self):
        row = s.publish_row({'url':'https://www.wordstream.com/blog/test','body':'text','published_at':'2026-10-31'},
                            {'detected_ch':'dj','relevant':True,'title':'Google Ads'},
                            {'ch':'hw','kind':'community','name':'WordStream'})
        self.assertEqual(row['ch'], 'hw')

    def test_ai_multiple_labels_choose_supported_primary(self):
        data = dict(title='test', desc='summary', content='body', reason='reason', cat=['case','acq'], tag=['ad'], ch=['hw','general'], score=80, relevant=True)
        response = Mock()
        response.json.return_value = {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(data)}}]}
        with patch.object(s, 'request', return_value=response):
            result = s.enrich({'source_kind': 'community'}, 'test')
        self.assertEqual(result['detected_ch'], 'hw')
        self.assertEqual(result['cat'], 'case')

    def test_feed_filters_topics_and_external_links(self):
        response = Mock()
        response.content = b'<rss><channel><item><title>Meta Ads testing</title><link>https://www.jonloomer.com/testing/</link><pubDate>Sat, 31 Oct 2026 08:00:00 +0000</pubDate></item><item><title>Meta Ads fake</title><link>https://evil.example/testing/</link></item><item><title>Weather today</title><link>https://www.jonloomer.com/weather/</link></item></channel></rss>'
        source = {'adapter': 'rss', 'url': 'https://www.jonloomer.com/feed/', 'hosts': ['www.jonloomer.com'], 'pattern': '/.+'}
        with patch.object(s, 'request', return_value=response):
            collector = s.Collector()
            self.assertEqual(collector.discover(source, 3), ['https://www.jonloomer.com/testing'])
            self.assertIsNotNone(s.date_value(collector.metadata['https://www.jonloomer.com/testing']))

    def test_community_relevance_gate(self):
        with tempfile.TemporaryDirectory() as d, patch.object(s, 'ROOT', Path(d)):
            (Path(d) / 'data.json').write_text('[]')
            (Path(d) / 'sources.json').write_text('[{"name":"author","ch":"general","kind":"community"}]')
            article = {'url': 'https://www.jonloomer.com/test', 'title': 'test', 'body': 'body', 'published_at': datetime.now(s.TZ).isoformat()}
            collector = Mock()
            collector.discover.return_value = [article['url']]
            collector.article.return_value = article
            ai = dict(title='test', desc='summary', content='body', reason='reason', cat='data', tag='ad', score=90, relevant=False, detected_ch='hw')
            with patch.dict(s.os.environ, {'DEEPSEEK_API_KEY': 'test'}), patch.object(s, 'enrich', return_value=ai):
                s.run(Mock(check_sources=False, limit=1), collector)
            self.assertEqual(json.loads((Path(d) / 'data.json').read_text()), [])
            self.assertEqual(json.loads((Path(d) / 'run_report.json').read_text())['sources'][0]['filtered'], 1)

    def test_demo_placeholder_does_not_block_collection(self):
        with tempfile.TemporaryDirectory() as d, patch.object(s, 'ROOT', Path(d)):
            (Path(d) / 'data.json').write_text('[{"id":1,"url":"#","title":"demo"}]')
            (Path(d) / 'sources.json').write_text('[{"name":"test","ch":"tx"}]')
            article = {'url': 'https://e.qq.com/latestnews/detail?pid=2', 'title': 'real', 'body': 'body', 'published_at': datetime.now(s.TZ).isoformat()}
            collector = Mock()
            collector.discover.return_value = [article['url']]
            collector.article.return_value = article
            ai = dict(title='real', desc='summary', content='body', reason='reason', cat='data', tag='ad', score=80)
            with patch.dict(s.os.environ, {'DEEPSEEK_API_KEY': 'test'}), patch.object(s, 'enrich', return_value=ai):
                self.assertEqual(s.run(Mock(check_sources=False, limit=1), collector), 0)
            rows = json.loads((Path(d) / 'data.json').read_text(encoding='utf-8'))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['url'], article['url'])

    def test_xiaohongshu_document_is_labelled_as_update(self):
        response = Mock()
        response.json.return_value = {'success': True, 'data': {'result': {'title': '投放规范', 'content': json.dumps({'children': [{'text': '规范正文' * 60}]})}}}
        source = {'adapter': 'xiaohongshu', 'ch': 'xhs', 'hosts': ['ad.xiaohongshu.com'], 'pattern': '/next_help/docs/'}
        url = 'https://ad.xiaohongshu.com/next_help/docs/123'
        collector = s.Collector()
        collector.metadata[url] = 1793318400000
        with patch.object(s, 'request', return_value=response):
            row = collector.article(url, source)
        self.assertEqual(row['title'], '投放规范')
        self.assertGreater(len(row['body']), 180)

    def test_tencent_detail_extracts_rich_text(self):
        response = Mock()
        response.json.return_value = {'code': 0, 'data': {'title': '腾讯广告更新', 'created_at': '2026-10-30 08:00:00', 'content': json.dumps({'content': [{'type': 'rich_text', 'content': '<p>' + '广告正文内容' * 60 + '</p>'}]})}}
        source = {'adapter': 'tencent', 'ch': 'tx', 'hosts': ['e.qq.com'], 'pattern': '/latestnews/detail'}
        with patch.object(s, 'request', return_value=response):
            row = s.Collector().article('https://e.qq.com/latestnews/detail?pid=42', source)
        self.assertIn('广告正文', row['body'])
        self.assertEqual(row['published_at'], '2026-10-30T08:00:00+08:00')

    def test_canonical_and_official_domain(self):
        self.assertEqual(s.canonical('https://e.qq.com/latestnews/detail?utm_source=x&pid=42#top'), 'https://e.qq.com/latestnews/detail?pid=42')
        source = {'hosts': ['e.qq.com'], 'pattern': '/latestnews/detail'}
        self.assertFalse(s.allowed('https://e.qq.com.evil.org/latestnews/detail', source))

    def test_reject_bad_ai(self):
        response = Mock()
        response.json.return_value = {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"cat":"made-up"}'}}]}
        with patch.object(s, 'request', return_value=response), self.assertRaises(ValueError):
            s.enrich({'body': 'public text'}, 'test-key')

    def test_missing_key_preserves_data(self):
        with patch.dict(s.os.environ, {'DEEPSEEK_API_KEY': ''}), self.assertRaises(ValueError):
            s.run(Mock(check_sources=False), Mock())

    def test_failure_preserves_snapshot_and_reports(self):
        with tempfile.TemporaryDirectory() as d, patch.object(s, 'ROOT', Path(d)):
            old = '[{"url":"https://e.qq.com/latestnews/detail?pid=1"}]'
            (Path(d) / 'data.json').write_text(old)
            (Path(d) / 'sources.json').write_text('[{"name":"test"}]')
            collector = Mock()
            collector.discover.side_effect = ValueError('unavailable')
            with patch.dict(s.os.environ, {'DEEPSEEK_API_KEY': 'test'}):
                self.assertEqual(s.run(Mock(check_sources=False, limit=1), collector), 1)
            self.assertEqual((Path(d) / 'data.json').read_text(), old)

    def test_recent_article_publishes_schema(self):
        with tempfile.TemporaryDirectory() as d, patch.object(s, 'ROOT', Path(d)):
            (Path(d) / 'data.json').write_text('[]')
            (Path(d) / 'sources.json').write_text('[{"name":"test","ch":"tx"}]')
            article = {'url': 'https://e.qq.com/latestnews/detail?pid=2', 'title': 'test', 'body': '正文', 'published_at': datetime.now(s.TZ).isoformat()}
            collector = Mock()
            collector.discover.return_value = [article['url']]
            collector.article.return_value = article
            ai = dict(title='标题', desc='摘要', content='正文', reason='理由', cat='data', tag='ad', score=80)
            with patch.dict(s.os.environ, {'DEEPSEEK_API_KEY': 'test'}), patch.object(s, 'enrich', return_value=ai):
                s.run(Mock(check_sources=False, limit=1), collector)
            row = json.loads((Path(d) / 'data.json').read_text(encoding='utf-8'))[0]
            self.assertEqual(row['t'], 'today')
            self.assertEqual(row['orig'], '')
            self.assertIsInstance(row['id'], int)


if __name__ == '__main__':
    unittest.main()
