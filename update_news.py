#!/usr/bin/env python3
"""
Daily News Digest Updater
Fetches RSS feeds, filters by recency, injects fresh articles into index.html.
Priority: last 7 days → last 30 days → any (fallback).
"""

import re
import html as html_lib
from datetime import datetime, timezone, timedelta

try:
    import feedparser
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'feedparser'])
    import feedparser

# ── Feed sources per category ─────────────────────────────────
CATEGORIES = [
    {
        'p': 0, 'tag': 'tech', 'cat': 'Tech & AI',
        'feeds': [
            'https://techcrunch.com/feed/',
            'https://www.theverge.com/rss/ai-artificial-intelligence/index.xml',
            'https://www.technologyreview.com/feed/',
            'https://feeds.arstechnica.com/arstechnica/technology-lab',
        ]
    },
    {
        'p': 1, 'tag': 'business', 'cat': 'Business',
        'feeds': [
            'https://rss.nytimes.com/services/xml/rss/nyt/Business.xml',
            'https://feeds.reuters.com/reuters/businessNews',
            'https://www.cnbc.com/id/10001147/device/rss/rss.html',
        ]
    },
    {
        'p': 2, 'tag': 'biotech', 'cat': 'Biotech',
        'feeds': [
            'https://www.statnews.com/feed/',
            'https://www.biopharmadive.com/feeds/news/',
            'https://www.fiercebiotech.com/rss/xml',
            'https://www.nature.com/subjects/biotechnology.rss',
        ]
    },
    {
        'p': 3, 'tag': 'aesthetics', 'cat': 'Med Aesthetics',
        'feeds': [
            'https://www.dermatologytimes.com/rss',
            'https://www.medestheticsmag.com/rss',
            'https://theindustry.beauty/feed/',
            'https://www.plasticsurgery.org/rss.aspx',
        ]
    },
]

# ── Date helpers ──────────────────────────────────────────────
def get_entry_date(entry):
    """Return UTC datetime from RSS entry, or None."""
    for field in ('published_parsed', 'updated_parsed', 'created_parsed'):
        t = getattr(entry, field, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None

def format_date(dt):
    """E.g. 'Apr 24' or 'Apr 24, 2025'."""
    if dt is None:
        return ''
    now = datetime.now(timezone.utc)
    if dt.year == now.year:
        return dt.strftime('%-m/%-d')       # e.g. 4/24
    return dt.strftime('%-m/%-d/%Y')        # e.g. 4/24/2025

def days_ago(dt):
    if dt is None:
        return 9999
    return (datetime.now(timezone.utc) - dt).days

# ── Text helpers ──────────────────────────────────────────────
def strip_html(text, max_len=220):
    text = re.sub(r'<[^>]+>', ' ', text or '')
    text = html_lib.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) > max_len:
        text = text[:max_len].rsplit(' ', 1)[0].rstrip('.,;:') + '…'
    return text

def js_escape(s):
    return (str(s)
            .replace('\\', '\\\\')
            .replace("'", "\\'")
            .replace('\n', ' ')
            .replace('\r', '')
            .replace('</', '<\\/'))

def source_name(feed, url):
    name = getattr(feed.feed, 'title', None)
    if not name:
        name = re.sub(r'^www\.', '', url.split('/')[2])
    return name[:50]

# ── Fetch all entries from a category's feeds ─────────────────
def fetch_all_entries(cat):
    """Return list of dicts with title/url/summary/src/date, sorted newest-first."""
    entries = []
    for feed_url in cat['feeds']:
        try:
            feed = feedparser.parse(
                feed_url,
                request_headers={'User-Agent': 'Mozilla/5.0 (compatible; NewsBot/1.0)'}
            )
            src = source_name(feed, feed_url)
            for entry in feed.entries:
                title   = strip_html(entry.get('title', ''), 120)
                url     = entry.get('link', '')
                raw_sum = (entry.get('summary', '')
                           or entry.get('description', '')
                           or (entry.get('content') or [{}])[0].get('value', ''))
                summary = strip_html(raw_sum, 220)
                dt      = get_entry_date(entry)
                if title and url:
                    entries.append({
                        'p':       cat['p'],
                        'tag':     cat['tag'],
                        'cat':     cat['cat'],
                        'src':     src,
                        'url':     url,
                        'title':   title,
                        'summary': summary or title,
                        'dt':      dt,
                        'date':    format_date(dt),
                        'age':     days_ago(dt),
                    })
        except Exception as exc:
            print(f'  ✗ {feed_url}: {exc}')

    # Sort newest-first (unknown dates go last)
    entries.sort(key=lambda e: e['dt'] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return entries

def pick_articles(entries):
    """
    Balanced tiered selection — 6 articles per category:
      Tier 1: up to 3 from ≤  7 days  (fresh this week)
      Tier 2: up to 2 from ≤ 30 days  (recent this month)
      Tier 3: up to 1 from ≤ 90 days  (important but older)
    Unused quota rolls over to the next tier.
    """
    QUOTAS  = [(7, 3), (30, 2), (90, 1)]
    result  = []
    seen    = set()
    surplus = 0

    def add(e):
        if e['url'] not in seen:
            seen.add(e['url'])
            result.append(e)
            return True
        return False

    for max_days, quota in QUOTAS:
        want  = quota + surplus
        added = 0
        for e in entries:
            if added >= want:
                break
            if e['age'] <= max_days and e['url'] not in seen:
                if add(e):
                    added += 1
        surplus = want - added   # carry leftover to next tier

    return result

# ── Inject into index.html ────────────────────────────────────
def build_news_js(all_news, today_str):
    lines = [f"  // Last updated: {today_str}"]
    for item in all_news:
        age_label = ''
        if item['age'] == 0:
            age_label = 'Today'
        elif item['age'] == 1:
            age_label = 'Yesterday'
        elif item['age'] <= 7:
            age_label = f"{item['age']}d ago"
        elif item['date']:
            age_label = item['date']

        lines.append(
            f"  {{p:{item['p']},tag:'{js_escape(item['tag'])}',cat:'{js_escape(item['cat'])}',src:'{js_escape(item['src'])}',"
            f"url:'{js_escape(item['url'])}',"
            f"title:'{js_escape(item['title'])}',"
            f"summary:'{js_escape(item['summary'])}',"
            f"age:'{js_escape(age_label)}'}},"
        )
    return '\n'.join(lines)

def update_html(all_news, today_str):
    with open('index.html', 'r', encoding='utf-8') as f:
        content = f.read()

    news_js  = build_news_js(all_news, today_str)
    new_block = f'// @@NEWS_START@@\nconst NEWS = [\n{news_js}\n];\n// @@NEWS_END@@'
    pattern   = r'// @@NEWS_START@@.*?// @@NEWS_END@@'
    new_content = re.sub(pattern, new_block, content, flags=re.DOTALL)

    if new_content == content:
        print('⚠️  Markers not found — index.html not updated')
        return False

    new_content = re.sub(
        r'(<span id="lastUpdated">)[^<]*(</span>)',
        rf'\g<1>{today_str}\g<2>',
        new_content
    )

    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(new_content)
    return True

# ── Main ──────────────────────────────────────────────────────
def main():
    today_str = datetime.utcnow().strftime('%B %d, %Y')
    print(f'📰 Daily Digest Update — {today_str}\n')

    all_news = []
    for cat in CATEGORIES:
        print(f'Fetching {cat["cat"]}…')
        entries  = fetch_all_entries(cat)
        articles = pick_articles(entries)

        # Log freshness for transparency
        for a in articles:
            flag = '🟢' if a['age'] <= 7 else ('🟡' if a['age'] <= 30 else '🔴')
            print(f'  {flag} [{a["age"]:>3}d] {a["title"][:60]}')

        all_news.extend(articles)

    if not all_news:
        print('\n❌ No articles fetched. Skipping update.')
        return

    fresh   = sum(1 for a in all_news if a['age'] <= 7)
    stale   = sum(1 for a in all_news if a['age'] > 30)
    print(f'\nTotal: {len(all_news)} articles  |  🟢 ≤7d: {fresh}  |  🔴 >30d: {stale}')

    if update_html(all_news, today_str):
        print('✅ index.html updated successfully')
    else:
        print('❌ Failed to update index.html')

if __name__ == '__main__':
    main()
