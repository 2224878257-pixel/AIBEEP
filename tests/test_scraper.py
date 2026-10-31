import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from datetime import datetime

import scraper as s


class ScraperTests(unittest.TestCase):
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
        self.assertTrue(row['title'].startswith('帮助文档更新：'))
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
