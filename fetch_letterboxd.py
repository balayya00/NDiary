import requests
import re
import json
import os
from xml.etree import ElementTree as ET

LB_USER    = 'a__tharun'
LB_RSS     = f'https://letterboxd.com/{LB_USER}/rss/'
CACHE_FILE = 'letterboxd_cache.json'

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/rss+xml, application/xml, text/xml, */*',
}

PROXIES = [
    lambda u: (
        f'https://api.allorigins.win/raw?url={requests.utils.quote(u)}'
    ),
    lambda u: f'https://corsproxy.io/?{requests.utils.quote(u)}',
    lambda u: (
        f'https://api.codetabs.com/v1/proxy?quest={requests.utils.quote(u)}'
    ),
]


def fetch_rss_text():
    try:
        r = requests.get(LB_RSS, headers=HEADERS, timeout=12)
        if r.ok and '<item>' in r.text:
            print('  Letterboxd: direct fetch OK')
            return r.text
        print(f'  Letterboxd direct: status={r.status_code}')
    except Exception as e:
        print(f'  Letterboxd direct failed: {e}')

    for i, proxy_fn in enumerate(PROXIES):
        try:
            r = requests.get(
                proxy_fn(LB_RSS), headers=HEADERS, timeout=12
            )
            if r.ok and '<item>' in r.text:
                print(f'  Letterboxd: proxy {i+1} OK')
                return r.text
            print(f'  Letterboxd proxy {i+1}: status={r.status_code}')
        except Exception as e:
            print(f'  Letterboxd proxy {i+1} failed: {e}')

    return None


def ns_text(el, local_name):
    for child in el.iter():
        tag   = child.tag
        local = tag.split('}')[-1] if '}' in tag else tag
        if local == local_name:
            t = (child.text or '').strip()
            if t:
                return t
    return ''


def parse_rss(xml_text):
    xml_text = re.sub(r'<\?xml[^>]+\?>', '', xml_text).strip()

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f'  XML parse error: {e}')
        xml_text2 = re.sub(r'<!\[CDATA\[', '', xml_text)
        xml_text2 = re.sub(r'\]\]>', '', xml_text2)
        try:
            root = ET.fromstring(xml_text2)
        except Exception as e2:
            print(f'  XML parse error 2: {e2}')
            return []

    items = root.findall('.//item')
    if not items:
        print('  No <item> elements found in RSS')
        return []

    print(f'  Found {len(items)} RSS items')
    entries = []

    for i, item in enumerate(items):
        film_title    = ns_text(item, 'filmTitle')
        film_year     = ns_text(item, 'filmYear')
        member_rating = ns_text(item, 'memberRating')
        watched_date  = ns_text(item, 'watchedDate')

        if not film_title:
            raw = (item.findtext('title') or '').strip()
            raw = re.sub(
                r'^[^,\-]+(?:watched|logged|reviewed)\s+',
                '', raw, flags=re.I,
            )
            raw = re.sub(r',\s*\d{4}.*$', '', raw)
            raw = re.sub(r'\s*[-]\s*\d{4}.*$', '', raw)
            film_title = raw.strip()

        if not film_title:
            continue

        pub_date = (item.findtext('pubDate') or '').strip()
        date_str = watched_date[:10] if watched_date else ''
        if not date_str and pub_date:
            try:
                from email.utils import parsedate_to_datetime
                dt       = parsedate_to_datetime(pub_date)
                date_str = dt.strftime('%Y-%m-%d')
            except Exception:
                date_str = pub_date[:10] if len(pub_date) >= 10 else ''

        rating = float(member_rating) if member_rating else None

        entries.append({
            'id':           item.findtext('link') or f'lb-{i}',
            'title':        film_title,
            'year':         film_year,
            'rating':       rating,
            'watched_date': date_str,
            'type':         'film',
            'source':       'letterboxd',
        })

    return entries


def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_cache(entries):
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def fetch_letterboxd():
    print('📡 Fetching Letterboxd RSS...')
    xml = fetch_rss_text()

    if not xml:
        print('❌ All Letterboxd fetches failed — using cache')
        return load_cache()

    entries = parse_rss(xml)
    if not entries:
        print('❌ No entries parsed — using cache')
        return load_cache()

    save_cache(entries)
    print(f'✅ Letterboxd: {len(entries)} entries saved')
    return entries


if __name__ == '__main__':
    fetch_letterboxd()