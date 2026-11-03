import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch

import scraper as s
from positioning import upgrade, editorial_score, POLICY


class PositioningTests(unittest.TestCase):
    def test_high_scoring_technical_demo_is_not_reader_relevant(self):
        data=dict(title='技术演示',desc='演示',content='演示步骤',reason='演示参考',cat='ai',tag='ai',ch='general',
                  score=100,score_breakdown=dict(POLICY['weights']),column='methods',topics=['实用工具'],
                  reader_fit='technical_demo',reader_task='未披露',relevant=True)
        response=Mock()
        response.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(data)}}]}
        with patch.object(s,'request',return_value=response):
            ai=s.enrich({'source_kind':'community'},'test')
        self.assertFalse(ai['relevant'])
        self.assertFalse(s.community_passes(ai))

    def test_unchanged_body_must_be_reviewed_after_policy_version_change(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(s,'ROOT',Path(tmp)):
            root=Path(tmp);stamp=datetime.now(s.TZ).isoformat();url='https://example.com/article';body='原文实际内容'
            old={'id':42,'url':url,'title':'旧分类','source_kind':'community','published_at':stamp,'quality_version':0,
                 'media_version':s.MEDIA_VERSION,'content_hash':s.hashlib.sha256(s.re.sub(r'\W+','',body).encode()).hexdigest()}
            (root/'data.json').write_text(json.dumps([old]))
            (root/'sources.json').write_text('[{"name":"test","ch":"general","kind":"community","hosts":["example.com"],"pattern":"/article"}]')
            collector=Mock();collector.discover.return_value=[url]
            collector.article.return_value={'url':url,'title':'原文','body':body,'published_at':stamp}
            ai=dict(title='重新审核后的工具',desc='摘要',content='要点',reason='用途',cat='ai',tag='ai',score=80,relevant=True,discovery_relevant=True,discovery_category='tool')
            with patch.dict(s.os.environ,{'DEEPSEEK_API_KEY':'test'}),patch.object(s,'enrich',return_value=ai) as enrich:
                s.run(Mock(check_sources=False,limit=1),collector)
            enrich.assert_called_once()
            row=json.loads((root/'archive.json').read_text(encoding='utf-8'))[0]
            self.assertEqual(row['id'],42)
            self.assertEqual(row['quality_version'],s.QUALITY_VERSION)

    def test_score_is_sum_of_bounded_components_not_model_total(self):
        parts=dict(POLICY['weights'])
        self.assertEqual(editorial_score({'score':1,'score_breakdown':parts}),100)
        with self.assertRaises(ValueError):
            editorial_score({'score_breakdown':{**parts,'evidence':26}})
        with self.assertRaises(ValueError):
            editorial_score({'score':99})

    def test_ai_cannot_create_owner_experiments(self):
        row={'id':42,'url':'https://example.com/original','section':'discovery','discovery_category':'project'}
        upgraded=upgrade(row,{'column':'experiments','topics':['副业项目','保证收益']})
        self.assertEqual(upgraded['column'],'opportunity')
        self.assertEqual(upgraded['topics'],['副业项目'])
        self.assertEqual(upgraded['id'],42)
        self.assertEqual(upgraded['url'],'https://example.com/original')
        row.update(owner_confirmed=True,experiment_record='owner supplied record',column='experiments')
        self.assertEqual(upgrade(row)['column'],'experiments')

    def test_missing_business_facts_not_inferred(self):
        row=upgrade({'section':'discovery','discovery_category':'project'},
                    {'business_details':{'product_service':'公开模板'}})
        self.assertEqual(row['business_details']['inputs'],'未披露')
        self.assertEqual(row['business_details']['payment_model'],'未披露')

    def test_claims_are_pending_and_keep_metric_and_period(self):
        row=upgrade({'section':'discovery','review_status':'published','discovery_category':'tool'},
                    {'income_claims':[{'metric':'营收','amount':'$100','period':'累计','attribution':'作者自述'}]})
        self.assertEqual(row['review_status'],'pending')
        self.assertEqual(row['evidence_status'],'author_reported_unverified')
        self.assertEqual(row['income_claims'][0]['metric'],'营收')
        self.assertEqual(row['income_claims'][0]['period'],'累计')

    def test_total_model_failure_preserves_exact_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(s,'ROOT',Path(tmp)):
            root=Path(tmp)
            content=json.dumps([{'id':1,'url':'https://example.com/old','published_at':datetime.now(s.TZ).isoformat()}])
            (root/'data.json').write_text(content)
            (root/'archive.json').write_text(content)
            (root/'sources.json').write_text('[{"name":"test","ch":"general","kind":"community"}]')
            collector=Mock()
            collector.discover.return_value=['https://example.com/new']
            collector.article.return_value={'url':'https://example.com/new','title':'new','body':'specific public body','published_at':datetime.now(s.TZ).isoformat()}
            with patch.dict(s.os.environ,{'DEEPSEEK_API_KEY':'test'}),patch.object(s,'enrich',side_effect=ValueError('model unavailable')):
                self.assertEqual(s.run(Mock(check_sources=False,limit=1),collector),1)
            self.assertEqual((root/'data.json').read_text(),content)
            self.assertEqual((root/'archive.json').read_text(),content)

    def test_one_failed_source_does_not_block_next_source(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(s,'ROOT',Path(tmp)):
            root=Path(tmp)
            (root/'data.json').write_text('[]')
            (root/'sources.json').write_text('[{"name":"broken"},{"name":"working"}]')
            collector=Mock()
            collector.discover.side_effect=[ValueError('source unavailable'),[]]
            with patch.dict(s.os.environ,{'DEEPSEEK_API_KEY':'test'}):
                self.assertEqual(s.run(Mock(check_sources=False,limit=1),collector),0)
            report=json.loads((root/'run_report.json').read_text())
            self.assertEqual(len(report['sources']),2)
            self.assertTrue(report['sources'][1]['discovery_ok'])

    def test_atom_publication_uses_published_not_updated(self):
        response=Mock(content=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Tool</title><link rel="alternate" href="https://example.com/tool"/><published>2026-11-01T00:00:00Z</published><updated>2026-11-03T00:00:00Z</updated></entry></feed>')
        collector=s.Collector()
        with patch.object(s,'request',return_value=response):
            self.assertEqual(collector.discover({'adapter':'rss','url':'https://example.com/feed','hosts':['example.com'],'pattern':'/tool'},1),['https://example.com/tool'])
        self.assertEqual(collector.metadata['https://example.com/tool'],'2026-11-01T00:00:00Z')
