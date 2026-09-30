"""크립토 뉴스 RSS + 경제 지표 캘린더."""
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime

import httpx

from .. import config

RSS_FEEDS = {
    "블록미디어": "https://www.blockmedia.co.kr/feed",
    "토큰포스트": "https://www.tokenpost.kr/rss",
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Cointelegraph": "https://cointelegraph.com/rss",
    "Decrypt": "https://decrypt.co/feed",
    "The Block": "https://www.theblock.co/rss.xml",
}

# 알림을 띄울 만한 헤드라인 키워드 (소문자 비교). (태그, 키워드들)
IMPORTANT = [
    ("속보", ("breaking", "속보", "긴급", "just in")),
    ("금리·연준", ("fed ", "fomc", "powell", "rate cut", "rate hike", "금리", "연준", "파월")),
    ("물가·고용", ("cpi", "pce", "nonfarm", "payroll", "jobs report", "물가", "고용")),
    ("ETF", ("etf",)),
    ("규제", ("sec ", "lawsuit", "ban ", "regulat", "규제", "소송", "금지")),
    ("해킹", ("hack", "exploit", "drain", "해킹", "탈취")),
    ("청산·급변", ("liquidat", "plunge", "crash", "surge", "soar", "청산", "급락", "급등", "폭락", "폭등")),
    ("상장", ("listing", "delist", "상장", "상폐")),
]


def tag(title: str) -> list[str]:
    t = f" {title.lower()} "
    return [name for name, words in IMPORTANT if any(w in t for w in words)]


# ForexFactory 주간 캘린더 JSON 미러 (FOMC, CPI, 고용지표 등)
CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

_cache: dict[str, tuple[float, object]] = {}


def _ttl(key: str, ttl: float, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


def _parse_rss(source: str, xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = it.findtext("pubDate")
        ts = None
        if pub:
            try:
                ts = int(parsedate_to_datetime(pub).timestamp())
            except (TypeError, ValueError):
                ts = None
        if title:
            tags = tag(title)
            items.append({"id": link or title, "source": source, "title": title, "url": link, "time": ts,
                          "tags": tags, "important": bool(tags),
                          "lang": "ko" if any("\uac00" <= ch <= "\ud7a3" for ch in title) else "en"})
    return items


def headlines(limit: int = 40) -> dict:
    def fetch():
        items, errors = [], {}

        def one(name_url):
            name, url = name_url
            r = httpx.get(url, timeout=config.HTTP_TIMEOUT, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 crypto-terminal"})
            r.raise_for_status()
            return _parse_rss(name, r.text)

        with ThreadPoolExecutor(max_workers=len(RSS_FEEDS)) as ex:
            futs = {name: ex.submit(one, (name, url)) for name, url in RSS_FEEDS.items()}
            for name, f in futs.items():
                try:
                    items.extend(f.result())
                except Exception as e:
                    errors[name] = str(e)
        seen, uniq = set(), []
        for it in sorted(items, key=lambda x: x["time"] or 0, reverse=True):
            if it["id"] not in seen:
                seen.add(it["id"]); uniq.append(it)
        items = uniq
        return {"items": items, "errors": errors}
    data = _ttl("news", 60, fetch)
    return {"items": data["items"][:limit], "errors": data["errors"]}


def economic_calendar(min_impact: str = "High", currencies: tuple[str, ...] = ("USD",)) -> dict:
    def fetch():
        r = httpx.get(CALENDAR_URL, timeout=config.HTTP_TIMEOUT)
        r.raise_for_status()
        return r.json()
    try:
        rows = _ttl("calendar", 900, fetch)
    except Exception as e:
        return {"items": [], "error": str(e)}
    order = {"Low": 0, "Medium": 1, "High": 2}
    items = [{
        "title": r.get("title"), "country": r.get("country"), "date": r.get("date"),
        "impact": r.get("impact"), "forecast": r.get("forecast"), "previous": r.get("previous"),
    } for r in rows
        if r.get("country") in currencies and order.get(r.get("impact"), 0) >= order.get(min_impact, 2)]
    return {"items": items, "error": None}
