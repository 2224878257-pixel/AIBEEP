import unittest
from discovery import apply_schema

class DiscoveryTests(unittest.TestCase):
    def row(self):return {'id':42,'url':'https://example.com/original','content':'内容'}
    def test_tools_never_inherit_claimed_verified_or_sponsored_flags(self):
        r=apply_schema(self.row(),{'discovery_relevant':True,'discovery_category':'ai_tool','tested_status':'tested','verification_status':'verified','sponsorship_status':'not_sponsored'}, {'title':'工具更新','body':'可导出文本'})
        self.assertEqual(r['review_status'],'published')
        self.assertEqual(r['verification_status'],'unverified')
        self.assertEqual(r['tested_status'],'unknown')
        self.assertEqual(r['sponsorship_status'],'unknown')
        self.assertEqual(r['url'],'https://example.com/original')
    def test_all_money_projects_and_methods_require_human_review(self):
        for cat in ('project','method'):
            r=apply_schema(self.row(),{'discovery_relevant':True,'discovery_category':cat},{'body':'一个可研究的创作方法'})
            self.assertEqual(r['review_status'],'pending')
    def test_promises_in_tool_source_or_ai_output_cannot_auto_publish(self):
        for ai,article in [({'discovery_relevant':True,'discovery_category':'tool'},{'body':'保证收益'}),({'discovery_relevant':True,'discovery_category':'tool','discovery_details':{'purpose':'日入一千'}},{'body':'工具'})]:
            r=apply_schema(self.row(),ai,article)
            self.assertEqual(r['review_status'],'pending')
            self.assertEqual(r['income_claim_status'],'unverified')
    def test_missing_new_fields_remain_legacy_compatible(self):
        r=apply_schema(self.row(),{}, {'body':'旧广告经验'})
        self.assertEqual(r['section'],'legacy')
        self.assertEqual(r['id'],42)
