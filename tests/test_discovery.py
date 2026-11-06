import unittest
from discovery import apply_schema

class DiscoveryTests(unittest.TestCase):
    def row(self):return {'id':42,'url':'https://example.com/original','content':'内容'}
    def test_tools_never_inherit_claimed_verified_or_sponsored_flags(self):
        r=apply_schema(self.row(),{'discovery_relevant':True,'discovery_category':'ai_tool','tested_status':'tested','verification_status':'verified','sponsorship_status':'not_sponsored'}, {'title':'工具更新','body':'可导出文本'})
        self.assertEqual(r['review_status'],'pending')
        self.assertEqual(r['verification_status'],'unverified')
        self.assertEqual(r['tested_status'],'unknown')
        self.assertEqual(r['sponsorship_status'],'unknown')
        self.assertEqual(r['url'],'https://example.com/original')
    def test_money_projects_without_business_evidence_require_review(self):
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
    def test_advertising_industry_observation_stays_in_legacy(self):
        r=apply_schema(self.row(),{'discovery_relevant':True,'discovery_category':'information'},{'title':'品牌总监的工作重心转向投流','body':'广告行业观察'})
        self.assertEqual(r['section'],'legacy')

    def test_technical_demonstration_without_business_process_is_not_auto_case(self):
        row=apply_schema(self.row(),{'discovery_relevant':True,'discovery_category':'ai_tool','column':'case','business_details':{'target_need':'未披露','product_service':'未披露'}},{'title':'作者技术实验','body':'代码移植'})
        self.assertEqual(row['review_status'],'pending')
        self.assertEqual(row['hold_reason'],'insufficient_business_process')

    def test_grounded_project_and_method_can_publish_without_profit_claim(self):
        for category in ('project','method'):
            ai={'discovery_relevant':True,'discovery_category':category,'business_focus':'earning_project',
                'business_details':{'product_service':'出售数字模板','payment_model':'按份收费'},
                'business_source_quotes':{'product_service':'I sell digital templates for freelancers.',
                                          'payment_model':'Customers pay per template download.'}}
            article={'body':'I sell digital templates for freelancers. Customers pay per template download.'}
            row=apply_schema(self.row(),ai,article)
            self.assertEqual(row['review_status'],'published')
            self.assertEqual(row['verification_status'],'unverified')
            ai['business_source_quotes']['payment_model']='Invented quote about paying customers.'
            self.assertEqual(apply_schema(self.row(),ai,article)['review_status'],'pending')

    def test_generic_sdk_cannot_qualify_with_invented_earning_context(self):
        from discovery import business_evidence
        ai={'business_focus':'business_support','business_details':{'product_service':'销售应用','acquisition':'接单'},
            'business_source_quotes':{'product_service':'Sell an app to customers','acquisition':'Find clients through outreach'}}
        self.assertFalse(business_evidence(ai,{'body':'Account Kit SDK implements silent sign in.'}))
