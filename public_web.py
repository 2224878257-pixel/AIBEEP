"""Restricted, bounded HTTP reader for URLs discovered outside a fixed allowlist."""
import ipaddress
import socket
import time
from urllib.parse import urlsplit, urljoin
import requests
import urllib3


def public_url(url):
    p=urlsplit(url)
    if p.scheme not in {'http','https'} or not p.hostname or p.username or p.password or p.port not in {None,80,443}:
        raise ValueError('Only public HTTP(S) URLs on standard ports are allowed')
    host=p.hostname.rstrip('.').lower()
    if host=='localhost' or host.endswith(('.localhost','.local','.internal')):
        raise ValueError('Local hostname rejected')
    addresses=socket.getaddrinfo(host,p.port or (443 if p.scheme=='https' else 80),type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError('Private, local, reserved or metadata address rejected')
    return addresses[0][4][0]


_last={}


def public_get(url, timeout=12, delay=1, max_bytes=3_000_000, retries=1):
    """Validate every redirect before requesting it; never use ambient credentials."""
    for hop in range(5):
        address=public_url(url)
        parsed=urlsplit(url)
        domain=parsed.hostname
        time.sleep(max(0,delay-(time.monotonic()-_last.get(domain,0))))
        pool_class=urllib3.HTTPSConnectionPool if parsed.scheme=='https' else urllib3.HTTPConnectionPool
        options={'assert_hostname':domain,'server_hostname':domain} if parsed.scheme=='https' else {}
        # Connect to the address we validated, with the original Host/SNI and TLS checks.
        # This prevents a second DNS lookup from rebinding the request into a private network.
        pool=pool_class(address,port=parsed.port or (443 if parsed.scheme=='https' else 80),
                        timeout=urllib3.Timeout(connect=5,read=timeout),**options)
        target=parsed.path or '/'
        if parsed.query:
            target+='?'+parsed.query
        try:
            for attempt in range(retries+1):
                raw=pool.urlopen('GET',target,headers={'Host':domain,'User-Agent':'AIBEEP/2.0 (+https://aibeep.cn)'},
                                 redirect=False,preload_content=False,retries=False)
                _last[domain]=time.monotonic()
                if raw.status in {429,500,502,503,504} and attempt<retries:
                    raw.close();time.sleep(2**attempt);continue
                break
            response=requests.Response()
            response.status_code=raw.status
            response.url=url
            response.headers=requests.structures.CaseInsensitiveDict(raw.headers)
            response.encoding=requests.utils.get_encoding_from_headers(response.headers)
            if response.is_redirect:
                location=response.headers.get('Location','')
                raw.close()
                url=urljoin(url,location)
                continue
            response.raise_for_status()
            data=bytearray()
            for block in raw.stream(65536,decode_content=True):
                data.extend(block)
                if len(data)>max_bytes:
                    raise ValueError('Public page exceeds size limit')
            response._content=bytes(data)
            response._content_consumed=True
            return response
        finally:
            if 'raw' in locals():raw.close()
            pool.close()
    raise ValueError('Redirect limit exceeded')
