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

    def test_ai_gate(self):
        item = {"reviewStatus":"approved", "audit":{"decision":"needs_review"}}
        self.assertIsNone(approved_item(item))
        item["audit"]["decision"] = "approved"
        self.assertIsNone(approved_item(item))

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
        audit = {"relevance": 90, "fidelity": 98, "unsupported_claims": False, "sensitive_or_legal_risk": False, "copyrighted_reproduction": False, "issues": [], "supported_facts": ["官方公布新的广告管理能力。", "更新介绍了具体的操作路径。"]}
        with patch.object(ai_review, "fetch_evidence", return_value="e" * 1200), \
             patch.object(ai_review, "draft", return_value=editorial), \
             patch.object(ai_review, "model_review", return_value=audit):
            self.assertEqual(ai_review.run({"candidates": [candidate]}, "dummy", 1), 1)
        self.assertEqual(candidate["reviewStatus"], "approved")
        self.assertIsNotNone(approved_item(candidate))
        flagged = {**audit, "unsupported_claims": True}
        self.assertEqual(ai_review.decision(candidate, flagged)[0], "needs_review")
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
                self.assertGreaterEqual(len(catalog["watch_pages"]), 9)
        finally:
            backend.DB_PATH = prior

    def test_static_publish_requires_two_matching_approvals(self):
        base = {"id": "0123456789abcdef", "url": "https://blog.google/example", "source": "Google", "category": "广告平台", "reviewStatus": "approved",
                "editorial": {"title": "广告更新", "summary": "产品更新摘要", "intro": "产品更新简介", "sections": [{"title": "说明", "paragraphs": ["官方描述了更新。"]}]}}
        content, bodies = {"items": []}, {"articles": {}}
        self.assertEqual(promoted({"candidates": [{**base, "audit": {"decision": "needs_review"}}]}, content, bodies), [])
        self.assertEqual(promoted({"candidates": [{**base, "audit": {"decision": "approved"}}]}, content, bodies), [base["id"]])
        self.assertEqual(len(content["items"]), 1)


if __name__ == "__main__":
    unittest.main()
