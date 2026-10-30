"""Offline regression checks: python3 -m unittest test_pipeline.py -v"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import backend
import ai_review
import deepseek_client
import report_run
import source_adapters
from publish_reviewed import promoted
from collect_feeds import likely_relevant, parse_feed, relevance
from scheduler import approved_item


class PipelineTests(unittest.TestCase):
    def test_relevance_gate(self):
        self.assertTrue(likely_relevant({"title":"Google Ads conversion campaign update", "excerpt":""}))
        self.assertFalse(likely_relevant({"title":"University health research", "excerpt":"New academic publication"}))
        self.assertGreater(relevance({"title":"广告素材投放更新", "excerpt":""}), 22)

    def test_rss_parsing(self):
        data = b'<rss><channel><item><title>Ads campaign update</title><link>https://example.com/story</link><description>conversion details</description></item></channel></rss>'
        items = parse_feed(data, {"name":"Test", "category":"广告平台"})
        self.assertEqual(len(items), 1)
        self.assertEqual(len(items[0]["id"]), 16)
        self.assertEqual(items[0]["reviewStatus"], "pending")
        self.assertIn("publishedAt", items[0])
        self.assertIn("collectedAt", items[0])

    def test_url_normalization_and_content_fingerprint(self):
        clean = source_adapters.normalize_url("https://Example.com/story/?utm_source=x&b=2&a=1#part")
        self.assertEqual(clean, "https://example.com/story?b=2&a=1")
        a = {"title": "广告 投放更新", "excerpt": "同一内容"}
        b = {"title": "广告投放更新！", "excerpt": "同一内容"}
        self.assertEqual(source_adapters.content_fingerprint(a), source_adapters.content_fingerprint(b))

    def test_official_api_adapters_and_public_webpage(self):
        tencent_data = json.dumps({"code": 0, "data": {"data": [{
            "post_id": 123, "title": "腾讯广告转化产品更新", "created_at": "2026-10-20 10:00:00",
            "tags": [{"name": "产品"}], "catalogs": []
        }]}}).encode()
        xhs_data = json.dumps({"msg": "ok", "data": {"menu": [{"menu": [{
            "docInfoType": 1, "shortcutId": "a" * 32, "title": "聚光广告规则更新",
            "updateTime": 1792466967000, "directory": ["物料审核规范"]
        }]}]}}).encode()
        page = b'<a href="/live/123">\xe3\x80\x90\xe5\xb7\xa8\xe9\x87\x8f\xe5\xad\xa6\xe3\x80\x91AI\xe8\x90\xa5\xe9\x94\x80\xe6\x8a\x95\xe6\x94\xbe\xe6\x96\xb0\xe5\xb7\xa5\xe5\x85\xb72026-10-27 06:00</a><a href="/login">login</a>'
        with patch.object(source_adapters, "request_bytes", return_value=(tencent_data, 200, "https://e.qq.com/api", "application/json")):
            items, status = source_adapters.fetch_tencent_latestnews({"name":"腾讯","url":"https://e.qq.com/api","platform":"腾讯广告","region":"cn"}, 3)
        self.assertEqual(status, 200)
        self.assertEqual(items[0]["url"], "https://e.qq.com/latestnews/detail?pid=123")
        with patch.object(source_adapters, "request_bytes", return_value=(xhs_data, 200, "https://ad.xiaohongshu.com/api", "application/json")):
            items, _ = source_adapters.fetch_xiaohongshu_help({"name":"小红书","url":"https://ad.xiaohongshu.com/api","platform":"小红书聚光","region":"cn"}, 3)
        self.assertEqual(items[0]["url"], "https://ad.xiaohongshu.com/next_help/docs/" + "a" * 32)
        webpage_source = {"name":"巨量学","url":"https://school.oceanengine.com/","platform":"巨量引擎","region":"cn","allowed_domains":["school.oceanengine.com"],"item_path_prefixes":["/live/"],"reviewStatus":"needs_manual_source"}
        with patch.object(source_adapters, "request_bytes", return_value=(page, 200, "https://school.oceanengine.com/", "text/html")):
            items, _ = source_adapters.fetch_public_webpage(webpage_source, 3)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["publishedAt"], "2026-10-27T06:00:00+08:00")
        self.assertEqual(items[0]["reviewStatus"], "needs_manual_source")

    def test_news_search_discovers_but_does_not_trust_external_results(self):
        payload = json.dumps({"articles": [
            {"title": "Google Ads launches campaign update", "url": "https://blog.google/products/ads-commerce/update/", "seendate": "20261030T030000Z", "domain": "blog.google", "language": "English"},
            {"title": "Commentary about advertising", "url": "https://news.example.com/story?utm_source=test", "seendate": "20261030T020000Z", "domain": "news.example.com", "language": "English"},
        ]}).encode()
        source = {
            "name": "Discovery", "url": "https://api.gdeltproject.org/api/v2/doc/doc", "platform": "行业搜索",
            "query": '("Google Ads" OR "Tencent Ads")', "allowed_domains": ["api.gdeltproject.org"],
            "official_domains": ["blog.google"], "domain_platforms": {"blog.google": "Google Ads"},
        }
        with patch.object(source_adapters, "request_bytes", return_value=(payload, 200, source["url"], "application/json")):
            items, status = source_adapters.fetch_gdelt_doc(source, 8)
        self.assertEqual(status, 200)
        self.assertEqual(items[0]["reviewStatus"], "pending")
        self.assertEqual(items[0]["platform"], "Google Ads")
        self.assertTrue(items[0]["discovery"]["verifiedPrimarySource"])
        self.assertEqual(items[1]["reviewStatus"], "needs_source_verification")
        self.assertEqual(items[1]["publicationStatus"], "withheld")
        self.assertFalse(items[1]["discovery"]["verifiedPrimarySource"])

    def test_collection_does_not_rewrite_unchanged_queue(self):
        import collect_feeds
        prior = collect_feeds.BASE
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                queue = {"updatedAt": "2026-01-01T00:00:00+00:00", "candidates": []}
                (root / "review_queue.json").write_text(json.dumps(queue), encoding="utf-8")
                (root / "feed_sources.json").write_text(json.dumps({"feeds": [], "watch_pages": []}), encoding="utf-8")
                before = (root / "review_queue.json").read_bytes()
                collect_feeds.BASE = root
                with patch("sys.argv", ["collect_feeds.py"]):
                    collect_feeds.main()
                self.assertEqual((root / "review_queue.json").read_bytes(), before)
        finally:
            collect_feeds.BASE = prior

    def test_ai_gate(self):
        item = {"reviewStatus":"approved", "audit":{"decision":"needs_review"}}
        self.assertIsNone(approved_item(item))
        item["audit"]["decision"] = "approved"
        self.assertIsNone(approved_item(item))

    def test_backend_ingest_requires_approved_audit_with_evidence(self):
        with self.assertRaises(ValueError):
            backend.validate_approved_audit(None)
        with self.assertRaises(ValueError):
            backend.validate_approved_audit({"decision": "needs_review", "supported_facts": ["a", "b"]})
        with self.assertRaises(ValueError):
            backend.validate_approved_audit({"decision": "approved", "supported_facts": ["only one"]})
        self.assertTrue(backend.validate_approved_audit({"decision": "approved", "supported_facts": ["官方资料支持事实一。", "官方资料支持事实二。"]}))

    def test_deepseek_json_retries_without_real_key(self):
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *args): return False

        replies = [FakeResponse(), FakeResponse()]
        payload = {"choices": [{"finish_reason": "stop", "message": {"content": '{"ok": true}'}}]}
        with patch.object(deepseek_client.urllib.request, "urlopen", side_effect=replies) as opened, \
             patch.object(deepseek_client.json, "load", side_effect=[{"choices": [{"finish_reason": "stop", "message": {"content": ""}}]}, payload]), \
             patch.object(deepseek_client.time, "sleep"):
            self.assertEqual(deepseek_client.generate_json("Return JSON", {"x": 1}, token="dummy"), {"ok": True})
            self.assertEqual(opened.call_count, 2)
            request = opened.call_args.args[0]
            self.assertEqual(json.loads(request.data)["model"], "deepseek-flash")

    def test_ai_audit_automatic_approval_and_fail_closed(self):
        candidate = {"id": "0123456789abcdef", "url": "https://blog.google/example", "source": "Google", "category": "广告平台", "title": "Google Ads 新功能", "excerpt": "广告素材管理" , "reviewStatus": "pending"}
        editorial = {"title": "广告平台更新", "summary": "官方公布投放工具更新。", "intro": "此次更新包含新能力。", "sections": [{"title": "功能", "paragraphs": ["支持广告优化流程。"]}]}
        audit = {"relevance": 90, "fidelity": 98, "duplicate_or_redundant": False, "unsupported_claims": False, "sensitive_or_legal_risk": False, "copyrighted_reproduction": False, "material_errors": [], "editorial_notes": ["可以补充一项非必要背景。"], "supported_facts": ["官方公布新的广告管理能力。", "更新介绍了具体的操作路径。"]}
        with patch.object(ai_review, "fetch_evidence", return_value="e" * 1200), \
             patch.object(ai_review, "draft", return_value=editorial), \
             patch.object(ai_review, "model_review", return_value=audit):
            self.assertEqual(ai_review.run({"candidates": [candidate]}, "dummy", 1), 1)
        self.assertEqual(candidate["reviewStatus"], "approved")
        self.assertEqual(candidate["publicationStatus"], "pending_human")
        self.assertIsNone(approved_item(candidate))
        candidate["publicationStatus"] = "approved"
        candidate["humanApproval"] = {"approvedBy": "editor", "approvedAt": "2026-10-29T10:00:00+08:00"}
        self.assertIsNotNone(approved_item(candidate))
        flagged = {**audit, "unsupported_claims": True}
        self.assertEqual(ai_review.decision(candidate, flagged)[0], "needs_review")
        material = {**audit, "material_errors": ["草稿把15%写成了50%。"]}
        self.assertEqual(ai_review.decision(candidate, material)[0], "needs_review")
        self.assertEqual(ai_review.decision(candidate, audit)[0], "approved")
        candidate["reviewStatus"] = "pending"
        with patch.object(ai_review, "fetch_evidence", side_effect=ValueError("offline")):
            ai_review.run({"candidates": [candidate]}, "dummy", 1)
        self.assertEqual(candidate["reviewStatus"], "needs_review")
        self.assertIsNone(approved_item(candidate))

    def test_seed_and_sources(self):
        prior = backend.DB_PATH
        try:
            with tempfile.TemporaryDirectory() as tmp:
                backend.DB_PATH = Path(tmp) / "test.sqlite3"
                backend.initialize()
                self.assertEqual(backend.seed_existing(), 9)
                self.assertEqual(backend.seed_existing(), 0)
                self.assertEqual(len(backend.get_content()["items"]), 9)
                self.assertEqual(len(backend.get_bodies()["articles"]), 9)
                catalog = json.loads((backend.ROOT / "feed_sources.json").read_text(encoding="utf-8"))
                self.assertEqual(len(catalog["feeds"]), 3)
                self.assertEqual(len(catalog["automatic_sources"]), 4)
                self.assertGreaterEqual(len(catalog["watch_pages"]), 3)
        finally:
            backend.DB_PATH = prior

    def test_ai_review_prioritizes_one_item_per_p0_platform(self):
        candidates = [
            {"id": "global", "platform": "Google Ads", "reviewStatus": "pending", "relevanceHint": 99},
            {"id": "xhs-low", "platform": "小红书聚光/千帆", "reviewStatus": "pending", "relevanceScore": 40},
            {"id": "ocean", "platform": "巨量引擎", "reviewStatus": "pending", "relevanceScore": 65},
            {"id": "tencent", "platform": "腾讯广告", "reviewStatus": "pending", "relevanceScore": 55},
            {"id": "xhs-high", "platform": "小红书聚光/千帆", "reviewStatus": "pending", "relevanceScore": 88},
            {"id": "held", "platform": "腾讯广告", "reviewStatus": "needs_review", "relevanceScore": 100},
        ]
        selected = ai_review.select_pending(candidates, 3)
        self.assertEqual([item["id"] for item in selected], ["tencent", "ocean", "xhs-high"])
        candidates[2]["reviewStatus"] = "needs_manual_source"
        self.assertNotIn("ocean", [item["id"] for item in ai_review.select_pending(candidates, 4)])
        candidates.append({"id": "approved-reaudit", "platform": "腾讯广告", "reviewStatus": "pending_reaudit", "relevanceScore": 1})
        self.assertEqual(ai_review.select_pending(candidates, 1)[0]["id"], "approved-reaudit")

    def test_successful_reaudit_unlocks_only_explicit_human_approval(self):
        candidate = {
            "id": "abcdef0123456789", "url": "https://e.qq.com/example", "source": "腾讯广告", "platform": "腾讯广告",
            "title": "腾讯广告更新", "reviewStatus": "pending_reaudit", "publicationStatus": "pending_ai",
            "humanApproval": {"approvedBy": "owner", "approvedAt": "2026-10-30T11:00:00+08:00"},
            "editorial": {"title": "更新", "summary": "官方更新摘要。", "intro": "官方更新说明。", "sections": [{"title": "事实", "paragraphs": ["官方公布了更新内容。"]}]},
        }
        audit = {"relevance": 95, "fidelity": 99, "duplicate_or_redundant": False, "unsupported_claims": False,
                 "sensitive_or_legal_risk": False, "copyrighted_reproduction": False, "material_errors": [], "editorial_notes": [],
                 "supported_facts": ["官方公布了广告产品更新内容。", "官方资料说明了功能适用范围。"]}
        with patch.object(ai_review, "fetch_evidence", return_value="e" * 1200), \
             patch.object(ai_review, "draft", side_effect=AssertionError("reaudit must preserve revised draft")), \
             patch.object(ai_review, "model_review", return_value=audit):
            self.assertEqual(ai_review.run({"candidates": [candidate]}, "dummy", 1), 1)
        self.assertEqual(candidate["reviewStatus"], "approved")
        self.assertEqual(candidate["publicationStatus"], "approved")

    def test_static_publish_requires_two_matching_approvals(self):
        base = {"id": "0123456789abcdef", "url": "https://blog.google/example", "source": "Google", "category": "广告平台", "reviewStatus": "approved",
                "editorial": {"title": "广告更新", "summary": "产品更新摘要", "intro": "产品更新简介", "sections": [{"title": "说明", "paragraphs": ["官方描述了更新。"]}]}}
        content, bodies = {"items": []}, {"articles": {}}
        self.assertEqual(promoted({"candidates": [{**base, "audit": {"decision": "needs_review"}}]}, content, bodies), [])
        approved = {**base, "publishedAt": "2026-10-29T08:00:00+00:00", "publicationStatus": "approved",
                    "humanApproval": {"approvedBy": "editor", "approvedAt": "2026-10-29T09:00:00+00:00"}, "audit": {
            "decision": "approved", "relevance": 91, "fidelity": 98,
            "supported_facts": ["官方发布了广告产品更新。", "公告说明了功能适用范围。"],
        }}
        self.assertEqual(promoted({"candidates": [approved]}, content, bodies), [base["id"]])
        self.assertEqual(len(content["items"]), 1)
        self.assertEqual(content["items"][0]["reviewStatus"], "approved")
        self.assertEqual(content["items"][0]["evidence"], approved["audit"]["supported_facts"])
        self.assertEqual(content["items"][0]["publishedAt"], approved["publishedAt"])

    def test_run_report_validation_and_summary(self):
        report = {
            "runId":"r1", "status":"success",
            "collection":{"fetched":1,"newCandidates":1,"duplicates":0,"lowRelevance":0,"stale":0,"failedSources":0,"platforms":{}},
            "aiReview":{"requested":0,"approved":0,"needsHumanReview":0,"rejected":0,"failed":0},
            "publication":{"eligible":0,"actualAdded":0,"mode":"manual-gate"}, "sources":[]
        }
        self.assertIn("运行汇总", report_run.markdown(report))


if __name__ == "__main__":
    unittest.main()
