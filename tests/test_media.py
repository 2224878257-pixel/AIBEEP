import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup
from PIL import Image
import media
import scraper


class MediaTests(unittest.TestCase):
    def test_ocr_numeric_claim_cannot_be_published_as_verified_summary(self):
        response=Mock()
        response.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':'{"relevant":true,"ch":"tx","cat":"platform","tag":"ad","title":"榜单","desc":"增长300%","reason":"推荐参考","content":"内容要点","score":80}'}}]}
        with patch.object(scraper,'request',return_value=response):
            with self.assertRaisesRegex(ValueError,'OCR numeric'):
                scraper._enrich_once({'body':'识别内容','ocr_used':True},'test')

    def test_image_order_lazy_loading_and_decorations(self):
        soup=BeautifulSoup('<img src="https://img.example/logo.png"><img data-src="//img.example/chart.png" src="data:image/png,base64,x" alt="图表"><img src="https://img.example/chart.png"><img src="/second.jpg"><img width="1" src="https://img.example/tiny.png"><img src="javascript:alert(1)">','html.parser')
        images=media.image_candidates(soup,'https://news.example/article')
        self.assertEqual([x['source_url'] for x in images],['https://img.example/chart.png','https://news.example/second.jpg'])
        self.assertEqual(images[0]['alt'],'图表')

    def test_private_image_destinations_rejected(self):
        with patch.object(media.socket,'getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(ValueError): media.public_url('https://image.example/a.png')

    def test_only_confident_ocr_words_retained(self):
        data={'text':['可信文字','错误数字','', '42'], 'conf':[95,20,-1,90]}
        with patch.object(media.pytesseract,'image_to_data',return_value=data):
            text,confidence=media.recognize(Image.new('RGB',(200,200),'white'))
        self.assertEqual(text,'可信文字 42')
        self.assertEqual(confidence,92.5)

    def test_images_saved_locally_and_ocr_failure_does_not_erase_images(self):
        article={'image_candidates':[{'source_url':'https://img.example/a.png','alt':'chart'}],'needs_ocr':True}
        with tempfile.TemporaryDirectory() as root, patch.object(media,'download_image',return_value=Image.new('RGB',(300,400),'white')), patch.object(media,'recognize',side_effect=RuntimeError('timeout')):
            result=media.prepare_media(article,root,Mock())
            self.assertEqual(len(result['images']),1)
            self.assertTrue((Path(root)/result['images'][0]['src']).is_file())
            self.assertIn('ocr_unavailable',result['media_issues'])
            self.assertFalse(result['ocr_used'])

    def test_html_response_not_accepted_as_image(self):
        response=Mock(status_code=200,headers={'Content-Type':'text/html'})
        session=Mock();session.get.return_value=response
        with patch.object(media,'public_url'):
            with self.assertRaises(ValueError):media.download_image('https://img.example/a.png',session)
        response.close.assert_called_once()
