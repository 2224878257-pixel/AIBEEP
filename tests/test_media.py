import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup
from PIL import Image
import media
import scraper
import zxingcpp


class MediaTests(unittest.TestCase):
    def qr_image(self):
        qr=zxingcpp.create_barcode('fixture-only',zxingcpp.BarcodeFormat.QRCode).to_image(scale=8)
        return Image.frombytes('L',(qr.shape[1],qr.shape[0]),bytes(qr))

    def test_qr_pixels_are_detected_even_in_long_poster(self):
        qr=self.qr_image()
        self.assertTrue(media.contains_qr(qr))
        poster=Image.new('RGB',(600,4000),'white');poster.paste(qr,(120,3200))
        self.assertTrue(media.contains_qr(poster))
        self.assertFalse(media.contains_qr(Image.new('RGB',(600,800),'white')))

    def test_qr_is_not_saved_or_ocr_processed(self):
        article={'image_candidates':[{'source_url':'https://img.example/random-name.png'}],'needs_ocr':True}
        with tempfile.TemporaryDirectory() as root, patch.object(media,'download_image',return_value=self.qr_image()), patch.object(media,'recognize') as ocr:
            result=media.prepare_media(article,root,Mock())
            self.assertEqual(result['images'],[])
            self.assertEqual(result['cover'],'')
            self.assertFalse(list(Path(root).rglob('*.webp')))
            ocr.assert_not_called()

    def test_qr_caption_skipped_before_download(self):
        soup=BeautifulSoup('<img src="https://img.example/opaque.png" alt="扫码加好友"><img src="https://img.example/chart.png" alt="投放流程图">','html.parser')
        self.assertEqual(len(media.image_candidates(soup,'https://example.com/')),1)

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
