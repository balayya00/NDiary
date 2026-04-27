import asyncio
import json
import os
import re
import time
import requests
import nest_asyncio
nest_asyncio.apply()

from playwright.async_api import async_playwright
from datetime import datetime

SZ_USER      = 'tharun123'
CACHE_FILE   = 'serializd_cache.json'
CURRENT_YEAR = str(datetime.now().year)
WIKI_HEADERS = {
    'User-Agent': 'DiaryApp/1.0 Python-Requests/2.28'
}

_wiki_cache = {}


# ── Wikipedia ─────────────────────────────────────────────────────────────────

def extract_year_range_from_wiki(raw):
    def get_year(text):
        m = re.search(r'(?:19|20)\d{2}', text)
        return m.group(0) if m else None

    first = re.search(r'first_aired\s*=\s*(.+)', raw, re.IGNORECASE)
    last  = re.search(r'last_aired\s*=\s*(.+)', raw, re.IGNORECASE)

    if first:
        start = get_year(first.group(1))
        end   = None
        if last:
            if 'present' in last.group(1).lower():
                end = CURRENT_YEAR
            else:
                end = get_year(last.group(1))
        if start and end:
            return start if start == end else f'{start}–{end}'
        elif start:
            return start

    original = re.search(
        r'original[_ ]release\s*=\s*(.+)', raw, re.IGNORECASE
    )
    if original:
        text  = original.group(1)
        years = re.findall(r'(?:19|20)\d{2}|present', text.lower())
        years = [CURRENT_YEAR if y == 'present' else y for y in years]
        if years:
            years = sorted(set(years))
            return (
                years[0] if len(years) == 1
                else f'{years[0]}–{years[-1]}'
            )

    released = re.search(r'released\s*=\s*(.+)', raw, re.IGNORECASE)
    if released:
        year = get_year(released.group(1))
        if year:
            return year

    years = re.findall(r'(?:19|20)\d{2}', raw[:2000])
    if years:
        return years[0]

    return None


def get_wiki_year(show_name):
    if show_name in _wiki_cache:
        return _wiki_cache[show_name]

    base = 'https://en.wikipedia.org/w/api.php'
    try:
        search = requests.get(
            base,
            params={
                'action':   'query',
                'list':     'search',
                'srsearch': f'{show_name} TV series',
                'format':   'json',
            },
            headers=WIKI_HEADERS,
            timeout=8,
        ).json()

        results = search.get('query', {}).get('search', [])
        if not results:
            _wiki_cache[show_name] = None
            return None

        title = results[0]['title']
        time.sleep(0.3)

        content = requests.get(
            base,
            params={
                'action':  'query',
                'prop':    'revisions',
                'rvprop':  'content',
                'titles':  title,
                'format':  'json',
            },
            headers=WIKI_HEADERS,
            timeout=8,
        ).json()

        page = list(content['query']['pages'].values())[0]
        raw  = page['revisions'][0]['*']
        year = extract_year_range_from_wiki(raw)

        _wiki_cache[show_name] = year
        return year

    except Exception as e:
        print(f'  Wiki failed for [{show_name}]: {e}')
        _wiki_cache[show_name] = None
        return None


# ── Playwright scraper ────────────────────────────────────────────────────────

async def scrape_serializd():
    url      = f'https://www.serializd.com/user/{SZ_USER}/diary'
    captured = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-extensions',
                '--disable-setuid-sandbox',
                '--single-process',
                '--no-zygote',
            ],
        )
        ctx = await browser.new_context(
            user_agent=(
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            )
        )
        page = await ctx.new_page()

        await page.route(
            '**/*.{png,jpg,jpeg,gif,svg,webp,woff,woff2,ttf,eot,mp4,mp3}',
            lambda route: route.abort(),
        )
        for pat in (
            '**/analytics**', '**/hotjar**',
            '**/googletagmanager**', '**/ads**',
        ):
            await page.route(pat, lambda r: r.abort())

        async def handle_response(response):
            u = response.url.lower()
            if response.status == 200 and (
                'diary'  in u or
                'review' in u or
                'log'    in u
            ):
                try:
                    j = await response.json()
                    if j:
                        captured.append(j)
                        print(f'  Captured: {response.url}')
                except Exception:
                    pass

        page.on('response', handle_response)

        try:
            await page.goto(
                url,
                timeout=60000,
                wait_until='domcontentloaded',
            )
            await page.wait_for_timeout(5000)

            for _ in range(10):
                await page.evaluate(
                    'window.scrollTo(0, document.body.scrollHeight)'
                )
                await page.wait_for_timeout(1500)

        except Exception as e:
            print(f'  Serializd page error: {e}')
        finally:
            await browser.close()

    return captured


# ── Parse ─────────────────────────────────────────────────────────────────────

def parse_serializd(raw_data):
    clean = []
    seen  = set()

    for batch in raw_data:
        reviews = (
            batch.get('reviews')
            or (batch.get('diary') or {}).get('reviews', [])
            or batch.get('entries')
            or batch.get('items')
            or batch.get('data')
            or []
        )
        if isinstance(reviews, dict):
            reviews = (
                reviews.get('items')
                or reviews.get('results')
                or []
            )
        if not isinstance(reviews, list):
            continue

        for item in reviews:
            item_id = item.get('id')
            if item_id is None or item_id in seen:
                continue
            seen.add(item_id)

            rating_raw = item.get('rating')
            rating = (
                round(float(rating_raw) / 2, 1)
                if rating_raw else None
            )

            watched_date = None
            for key in (
                'backdate', 'watchedDate', 'watched_date',
                'createdAt', 'created_at', 'loggedDate',
            ):
                val = item.get(key)
                if val:
                    watched_date = str(val)[:10]
                    break

            title = ''
            for tkey in (
                'showName', 'show_name', 'name',
                'title', 'seriesName',
            ):
                tval = item.get(tkey)
                if tval:
                    title = str(tval).strip()
                    break

            if not title:
                continue

            clean.append({
                'id':           str(item_id),
                'title':        title,
                'year':         '',
                'rating':       rating,
                'watched_date': watched_date,
                'type':         'tv',
                'source':       'serializd',
                'show_id':      (
                    item.get('showId') or item.get('show_id')
                ),
            })

    return clean


def enrich_years(entries):
    unique_titles = list(
        dict.fromkeys(e['title'] for e in entries if e['title'])
    )
    print(f'   Looking up {len(unique_titles)} shows on Wikipedia…')
    year_map = {}
    for i, title in enumerate(unique_titles):
        year = get_wiki_year(title)
        year_map[title] = year or ''
        print(
            f'   [{i+1}/{len(unique_titles)}] '
            f'{title} → {year or "not found"}'
        )
    for e in entries:
        e['year'] = year_map.get(e['title'], '')
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


def fetch_serializd():
    print('🎭 Scraping Serializd...')
    try:
        raw = asyncio.run(scrape_serializd())
        print(f'   Got {len(raw)} API response batches')

        entries = parse_serializd(raw)
        print(f'   Parsed {len(entries)} unique entries')

        if not entries:
            print('⚠️  No entries — using cache')
            return load_cache()

        entries = enrich_years(entries)
        save_cache(entries)
        print(f'✅ Serializd: {len(entries)} entries saved')
        return entries

    except Exception as e:
        print(f'❌ Serializd failed: {e}')
        return load_cache()


if __name__ == '__main__':
    fetch_serializd()
