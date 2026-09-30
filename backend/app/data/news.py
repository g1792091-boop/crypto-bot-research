"""크립토 뉴스 RSS + 경제 지표 캘린더."""
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import httpx

from .. import config

RSS_FEEDS = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Cointelegraph": "https://cointelegraph.com/rss",
    "Decrypt": "https://decrypt.co/feed",
    "The Block": "https://www.theblock.co/rss.xml",
}

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
            items.append({"source": source, "title": title, "url": link, "time": ts})
    return items


def headlines(limit: int = 40) -> dict:
    def fetch():
        items, errors = [], {}
        for name, url in RSS_FEEDS.items():
            try:
                r = httpx.get(url, timeout=config.HTTP_TIMEOUT, follow_redirects=True,
                              headers={"User-Agent": "Mozilla/5.0 crypto-terminal"})
                r.raise_for_status()
                items.extend(_parse_rss(name, r.text))
            except Exception as e:
                errors[name] = str(e)
        items.sort(key=lambda x: x["time"] or 0, reverse=True)
        return {"items": items, "errors": errors}
    data = _ttl("news", 180, fetch)
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
