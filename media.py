"""Bounded public image collection and local Chinese/English OCR."""
import hashlib
import io
from html import escape
import ipaddress
from pathlib import Path
import re
import socket
from urllib.parse import urljoin, urlsplit

from PIL import Image, ImageOps
import pytesseract
from bs4 import BeautifulSoup

MEDIA_VERSION = 1
MAX_IMAGES = 6
Image.MAX_IMAGE_PIXELS = 24_000_000


def json_image_candidates(value, page_url):
    urls = []
    def visit(node):
        if isinstance(node, dict):
            image = node.get('image')
            if isinstance(image, str):
                urls.append(image)
            elif isinstance(image, dict):
                urls.append(image.get('src') or image.get('url') or '')
            if node.get('type') == 'image':
                attrs = node.get('attrs') or node
                urls.append(attrs.get('src') or attrs.get('url') or '')
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)
    visit(value)
    soup = BeautifulSoup(''.join(f'<img src="{escape(u, quote=True)}">' for u in urls if u), 'html.parser')
    return image_candidates(soup, page_url)


def image_candidates(scope, page_url):
    result = []
    if scope is None:
        return result
    for img in scope.select('img'):
        raw = img.get('data-src') or img.get('data-original') or img.get('data-lazy-src') or img.get('src') or ''
        url = urljoin(page_url, raw)
        if urlsplit(url).scheme != 'https' or not urlsplit(url).hostname:
            continue
        if re.search(r'avatar|logo|qrcode|qr-code|emoji|icon|loading|spacer', url, re.I):
            continue
        if any(img.get(k, '').isdigit() and int(img[k]) < 100 for k in ('width', 'height')):
            continue
        if any(r['source_url'] == url for r in result):
            continue
        result.append({'source_url': url, 'alt': (img.get('alt') or '')[:160], 'source_page': page_url})
        if len(result) == MAX_IMAGES:
            break
    return result


def public_url(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('Invalid public image URL')
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(r[4][0]).is_global for r in addresses):
        raise ValueError('Image URL must resolve to public addresses')


def download_image(url, session):
    for _ in range(4):
        public_url(url)
        response = session.get(url, timeout=(8, 15), stream=True, allow_redirects=False)
        try:
            if response.status_code in (301, 302, 303, 307, 308):
                url = urljoin(url, response.headers.get('Location', ''))
                continue
            response.raise_for_status()
            if not response.headers.get('Content-Type', '').lower().startswith('image/'):
                raise ValueError('Not an image response')
            data = bytearray()
            for chunk in response.iter_content(65536):
                data.extend(chunk)
                if len(data) > 8_000_000:
                    raise ValueError('Image exceeds download limit')
            with Image.open(io.BytesIO(data)) as original:
                if original.width * original.height > Image.MAX_IMAGE_PIXELS:
                    raise ValueError('Image exceeds pixel limit')
                image = ImageOps.exif_transpose(original).convert('RGB')
                if min(image.size) < 100:
                    raise ValueError('Decorative image')
                return image
        finally:
            response.close()
    raise ValueError('Too many image redirects')


def recognize(image):
    # Split long posters in reading order; bound runtime and reject uncertain words.
    if image.width > 2000:
        image = image.resize((2000, int(image.height * 2000 / image.width)))
    lines, all_conf = [], []
    for y in range(0, min(image.height, 10800), 1800):
        part = image.crop((0, y, image.width, min(y+1800, image.height)))
        data = pytesseract.image_to_data(part, lang='chi_sim+eng', config='--psm 11',
                                        output_type=pytesseract.Output.DICT, timeout=15)
        for text, confidence in zip(data['text'], data['conf']):
            text = text.strip()
            conf = float(confidence)
            if text and conf >= 65:
                lines.append(text)
                all_conf.append(conf)
    return ' '.join(lines)[:12000], round(sum(all_conf)/len(all_conf), 1) if all_conf else 0


def prepare_media(article, root, session):
    images, extracted, issues = [], [], []
    for candidate in article.get('image_candidates', [])[:MAX_IMAGES]:
        try:
            image = download_image(candidate['source_url'], session)
            buffer = io.BytesIO()
            image.save(buffer, 'WEBP', quality=92, method=4)
            blob = buffer.getvalue()
            name = hashlib.sha256(blob).hexdigest()[:32] + '.webp'
            directory = Path(root) / 'assets' / 'images'
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / name
            if not target.exists():
                target.write_bytes(blob)
            item = {**candidate, 'src': 'assets/images/'+name, 'width': image.width, 'height': image.height}
            if article.get('needs_ocr'):
                try:
                    text, confidence = recognize(image)
                    item.update(ocr_characters=len(text), ocr_confidence=confidence)
                    if text:
                        extracted.append(text)
                except (RuntimeError, pytesseract.TesseractNotFoundError, pytesseract.TesseractError):
                    issues.append('ocr_unavailable')
            images.append(item)
        except Exception:
            issues.append('image_download_failed')
    ocr_text = '\n'.join(extracted)[:20000]
    return {'images': images, 'cover': images[0]['src'] if images else '', 'ocr_text': ocr_text,
            'ocr_used': bool(ocr_text), 'media_version': MEDIA_VERSION if not issues else 0,
            'media_issues': sorted(set(issues))}


def prune_unreferenced(root, rows):
    directory = (Path(root)/'assets'/'images').resolve()
    referenced = {i.get('src') for row in rows for i in row.get('images', [])}
    for path in directory.glob('*.webp'):
        if path.resolve().parent == directory and re.fullmatch(r'[a-f0-9]{32}\.webp', path.name):
            if 'assets/images/'+path.name not in referenced:
                path.unlink()
