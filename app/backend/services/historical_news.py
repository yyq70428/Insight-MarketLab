from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
import json
import re
import time
from html import unescape
import requests
from bs4 import BeautifulSoup
from ..config import get_settings
from .time_boundary import anchor_cutoff
from .market_data import cache


def verify_article(article: dict, cutoff: datetime) -> tuple[bool, str]:
    """Validate immutable source identity and both article timestamps before scoring."""
    required = ("id", "url", "type", "publishedAt", "modifiedAt")
    if any(not article.get(key) for key in required):
        return False, "來源缺少必要識別或發佈時間"
    if article["type"] not in {"stock", "market"}:
        return False, "來源分類不合法"
    if urlparse(article["url"]).scheme not in {"http", "https"}:
        return False, "來源網址不合法"
    try:
        published = datetime.fromisoformat(str(article["publishedAt"]).replace("Z", "+00:00"))
        modified = datetime.fromisoformat(str(article["modifiedAt"]).replace("Z", "+00:00"))
    except ValueError:
        return False, "時間無法驗證"
    if published.tzinfo is None or modified.tzinfo is None:
        return False, "來源時間缺少時區"
    if published >= cutoff or modified >= cutoff:
        return False, "來源在錨點截止時間之後發佈或修改"
    if modified < published:
        return False, "修改時間早於發佈時間，來源時間矛盾"
    if article.get("paywalled"):
        return False, "付費文章不可驗證"
    return True, ""


def interleave_verified(stock: list[dict], market: list[dict], cutoff: datetime, limit: int = 8):
    verified = {"stock": [], "market": []}; excluded = []
    seen = set()
    for kind, rows in (("stock", stock), ("market", market)):
        for row in rows:
            valid, reason = verify_article(row, cutoff)
            if not valid or row["id"] in seen:
                excluded.append({"id": row.get("id"), "reason": reason or "重複來源"}); continue
            seen.add(row["id"]); verified[kind].append(row)
    output=[]
    while len(output)<limit and (verified["stock"] or verified["market"]):
        for kind in ("stock", "market"):
            if verified[kind] and len(output)<limit: output.append(verified[kind].pop(0))
    return output, excluded


def identify_symbol(symbol: str, name: str | None = None) -> dict:
    aliases = [symbol, symbol.split('.')[0]]
    if symbol.endswith((".TW", ".TWO")):
        settings = get_settings()
        def directory():
            response = requests.get(settings.twse_codequery_url, params={"query":symbol.split('.')[0], "owncode": symbol.split('.')[0], "stockname": "", "isincode": ""},
                                    headers={"User-Agent": settings.upstream_user_agent}, timeout=settings.news_timeout)
            response.raise_for_status()
            try:
                for value in response.json().get('suggestions', []):
                    code, _, company = value.partition('\t')
                    if code == symbol.split('.')[0] and company: return company
            except (ValueError, AttributeError): pass
            response.encoding = response.apparent_encoding
            soup = BeautifulSoup(response.text, "html.parser")
            code = symbol.split('.')[0]
            for tr in soup.select('tr'):
                cells = [td.get_text(' ', strip=True) for td in tr.select('td')]
                if code in cells:
                    idx = cells.index(code)
                    if idx + 1 < len(cells):
                        return cells[idx + 1]
            endpoint = settings.tpex_directory_url if symbol.endswith('.TWO') else settings.twse_directory_url
            fallback = requests.get(endpoint, headers={'User-Agent': settings.upstream_user_agent}, timeout=settings.news_timeout)
            fallback.raise_for_status()
            for row in fallback.json():
                if str(row.get('公司代號','')).strip() == symbol.split('.')[0]:
                    return row.get('公司簡稱') or row.get('公司名稱') or ''
            return ''
        try:
            official = cache.get(f"tw-identity:{symbol}", 86400, directory)
            if official: aliases.append(official)
        except requests.RequestException:
            pass
    if name and name.strip(): aliases.append(name.strip()[:120])
    return {"symbol": symbol, "name": aliases[-1], "aliases": list(dict.fromkeys(aliases))}


def classify(title: str, body: str, identity: dict) -> str | None:
    # Publisher/category SEO suffixes are not evidence about the article topic.
    title = re.split(r'\s*[|｜]\s*鉅亨網', title)[0]
    content = title + ' ' + body
    for alias in identity['aliases']:
        pattern = r'(?<![A-Za-z0-9])' + re.escape(alias) + r'(?![A-Za-z0-9])'
        if re.search(pattern, content, re.I): return 'stock'
    if any(word in title for word in ('盤中速報', '盤中快訊', '即時股價')): return None
    if any(word in title for word in ('營收速報', '焦點股', '新股掛牌', '承銷價')): return None
    terms = ('台股', '加權指數', '大盤', '央行', '三大法人', '臺灣50指數', '台灣50指數') if identity['symbol'].endswith(('.TW', '.TWO')) else ('美股', '道瓊', '那斯達克', '標普', '聯準會', 'Fed', '比特幣', '加密貨幣')
    return 'market' if any(term.lower() in title.lower() for term in terms) else None


def _metadata(nodes):
    for node in nodes:
        if isinstance(node, list): yield from _metadata(node)
        elif isinstance(node, dict):
            if node.get('datePublished'): yield node
            if '@graph' in node: yield from _metadata(node['@graph'])


def fetch_article(item: dict, identity: dict, cutoff: datetime, start: datetime, round_index: int) -> dict:
    identifier = str(item.get('newsId') or item.get('id') or '')
    if not identifier.isdigit(): raise ValueError('來源識別無效')
    settings = get_settings()
    url = f'https://news.cnyes.com/news/id/{identifier}'
    def load():
        response = requests.get(url, headers={'User-Agent': settings.upstream_user_agent}, timeout=settings.news_timeout, allow_redirects=False)
        response.raise_for_status()
        if len(response.content) > 2_000_000: raise ValueError('文章超過大小上限')
        soup = BeautifulSoup(response.text, 'html.parser')
        objects = []
        for script in soup.select('script[type="application/ld+json"]'):
            try: objects.extend(_metadata([json.loads(script.get_text())]))
            except (ValueError, TypeError): continue
        node = next((o for o in objects if 'Article' in str(o.get('@type', ''))), None)
        if not node: raise ValueError('原頁沒有可驗證的文章結構化時間')
        body = node.get('articleBody') or ''
        if not body:
            article = soup.select_one('article')
            body = ' '.join(p.get_text(' ', strip=True) for p in article.select('p')) if article else ''
        body = BeautifulSoup(unescape(body), 'html.parser').get_text(' ', strip=True)
        if not body.strip(): raise ValueError('原頁正文不可讀取')
        return {'id': f'cnyes-{identifier}', 'url': url, 'title': node.get('headline') or item.get('title', ''),
                'publishedAt': node.get('datePublished'), 'modifiedAt': node.get('dateModified'), 'body': body[:1500],
                'paywalled': node.get('isAccessibleForFree') in (False, 'False', 'false'), 'publisher': '鉅亨網'}
    article = dict(cache.get(f'article:{identifier}', settings.news_cache_ttl, load))
    if not article.get('modifiedAt'): raise ValueError('原頁缺少修改時間')
    article['type'] = classify(article['title'], article['body'], identity)
    article['round'] = round_index
    valid, reason = verify_article(article, cutoff)
    if not valid: raise ValueError(reason)
    if datetime.fromisoformat(article['publishedAt'].replace('Z', '+00:00')) < start:
        raise ValueError('原文發佈時間不在回看範圍')
    return article


def historical_news(symbol: str, anchor: str, lookback_days: int = 30, rounds: int = 3, name: str | None = None) -> dict:
    settings = get_settings(); began = time.monotonic()
    cutoff = anchor_cutoff(symbol, anchor); start = cutoff - timedelta(days=lookback_days)
    identity = identify_symbol(symbol, name)
    # A legacy keyword endpoint cannot be used as a category archive.
    base = settings.anue_news_url if '/category' in settings.anue_news_url else 'https://api.cnyes.com/media/api/v1/newslist/category'
    category = 'tw_stock' if symbol.endswith(('.TW', '.TWO')) else 'wd_stock'

    def search_round(index):
        lower = start + (cutoff-start) * index / rounds
        upper = start + (cutoff-start) * (index+1) / rounds
        verified, excluded = [], []
        pages = 0
        for page in range(1, min(settings.news_max_pages_per_round, 10)+1):
            pages = page
            try:
                def load_page():
                    response = requests.get(f'{base.rstrip("/")}/{category}', params={'page': page, 'limit': 30,
                        'startAt': int(lower.timestamp()), 'endAt': int(upper.timestamp())-1},
                        headers={'User-Agent': settings.upstream_user_agent}, timeout=settings.news_timeout)
                    response.raise_for_status(); return response.json()
                data = cache.get(f'news-page:{category}:{int(lower.timestamp())}:{int(upper.timestamp())}:{page}', settings.news_cache_ttl, load_page)
                items = data.get('items', {}).get('data', [])
                if not items: break
                for item in items:
                    published = item.get('publishAt') or item.get('publishedAt')
                    try:
                        stamp = datetime.fromtimestamp(float(published), timezone.utc)
                    except (TypeError, ValueError, OverflowError): continue
                    if not lower <= stamp < upper: continue
                    title = item.get('title', '')
                    kind = classify(title, BeautifulSoup(unescape(item.get('content', '')), 'html.parser').get_text(' ', strip=True), identity)
                    if not kind or sum(s['type'] == kind for s in verified) >= 2: continue
                    try:
                        article = fetch_article(item, identity, cutoff, start, index+1)
                        if sum(s['type'] == article['type'] for s in verified) < 2:
                            verified.append(article)
                    except (ValueError, requests.RequestException) as exc:
                        excluded.append({'id': str(item.get('newsId', '')), 'reason': str(exc) if isinstance(exc, ValueError) else '原頁取得失敗'})
                if all(sum(s['type'] == kind for s in verified) >= 2 for kind in ('stock', 'market')): break
                if page >= data.get('items', {}).get('last_page', page): break
            except (requests.RequestException, ValueError, AttributeError):
                excluded.append({'id': None, 'reason': '分類歷史來源暫時不可用'}); break
        return verified, excluded, {'round': index+1, 'pages': pages, 'verified': len(verified), 'start': lower.isoformat(), 'end': upper.isoformat()}

    with ThreadPoolExecutor(max_workers=rounds) as pool:
        results = list(pool.map(search_round, range(rounds)))
    # Round-robin across both rounds and kinds, independent of completion order.
    stock, market, audit, searches = [], [], [], []
    for kind, target in (('stock', stock), ('market', market)):
        groups = [[s for s in rows if s['type'] == kind] for rows, _, _ in results]
        for index in range(max((len(g) for g in groups), default=0)):
            target.extend(g[index] for g in groups if len(g) > index)
    sources, duplicate_audit = interleave_verified(stock, market, cutoff, min(settings.news_max_articles, 8))
    for _, excluded, search in results: audit.extend(excluded); searches.append(search)
    return {'sources': sources, 'excluded': (audit+duplicate_audit)[:100], 'search': searches,
            'identity': {'symbol': symbol, 'anchor': anchor}, 'symbolIdentity': identity,
            'cutoff': cutoff.isoformat(), 'fetchSeconds': round(time.monotonic()-began, 2)}
