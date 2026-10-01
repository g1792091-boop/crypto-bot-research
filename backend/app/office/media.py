"""데이터·미디어팀 도구 — SNS 여론(레딧·스톡트윗·공포탐욕), 유튜브, 인스타그램·커뮤니티, 웹 검색 (API 키 없이).

SNS·영상·게시글은 개인 의견·인기일 뿐이다. 결과 text 맨 앞에 그 점을 적어 AI 가 사실처럼 단정하지 않게 한다.
"""
from __future__ import annotations

import html
import json
import re
import time
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx

from .. import config

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
      "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"}
SUBS = ["CryptoCurrency", "Bitcoin", "ethereum", "solana", "CryptoMarkets"]
_cache: dict = {}


def _get(url, **kw):
    r = httpx.get(url, headers=UA, timeout=config.HTTP_TIMEOUT, follow_redirects=True, **kw)
    r.raise_for_status()
    return r


def _ttl(key, sec, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < sec:
        return hit[1]
    v = fn()
    _cache[key] = (time.time(), v)
    return v


def _offline():
    return config.DATA_SOURCE == "synthetic"


# ------------------------------------------------------------------ SNS
def sns_buzz(symbol: str = "BTC", subs: list[str] | None = None) -> dict:
    sym = (symbol or "BTC").upper().removesuffix("USDT")
    parts, sources, fg = [], [], None
    if _offline():
        return {"text": "SNS 데이터 없음 (테스트 모드)", "summary": "데이터 없음", "sources": [], "fear_greed": None}
    for sub in (subs or SUBS[:2] + ([{"ETH": "ethereum", "SOL": "solana"}[sym]] if sym in ("ETH", "SOL") else [])):
        try:
            d = _ttl(("reddit", sub), 600, lambda s=sub: _get(f"https://www.reddit.com/r/{s}/hot.json?limit=12").json())
            posts = [c["data"] for c in d["data"]["children"] if not c["data"].get("stickied")][:6]
            if posts:
                parts.append(f"[레딧 r/{sub}] 인기 글: " + " / ".join(f"{p['title'][:90]} (추천 {p.get('score', 0)}, 댓글 {p.get('num_comments', 0)})" for p in posts))
                sources += [{"title": p["title"][:90], "url": "https://www.reddit.com" + p["permalink"]} for p in posts[:2]]
        except Exception:  # noqa: BLE001
            continue
    try:
        d = _ttl(("st", sym), 300, lambda: _get(f"https://api.stocktwits.com/api/2/streams/symbol/{sym}.X.json").json())
        msgs = d.get("messages") or []
        bull = sum(1 for m in msgs if ((m.get("entities") or {}).get("sentiment") or {}).get("basic") == "Bullish")
        bear = sum(1 for m in msgs if ((m.get("entities") or {}).get("sentiment") or {}).get("basic") == "Bearish")
        if msgs:
            parts.append(f"[스톡트윗 {sym}] 최근 글 {len(msgs)}개 중 강세 {bull} · 약세 {bear}. 예: " + " / ".join((m.get("body") or "")[:80] for m in msgs[:4]))
    except Exception:  # noqa: BLE001
        pass
    try:
        d = _ttl(("fng",), 600, lambda: _get("https://api.alternative.me/fng/?limit=7&format=json").json())
        rows = d["data"]
        fg = int(rows[0]["value"])
        parts.append(f"[코인 공포·탐욕 지수] 오늘 {fg} ({rows[0]['value_classification']}) · 1주 흐름 " + "→".join(r["value"] for r in reversed(rows)))
    except Exception:  # noqa: BLE001
        pass
    if not parts:
        return {"text": "SNS 데이터를 가져오지 못했습니다(접속 제한일 수 있음). web_search로 대신 찾아보세요.", "summary": "가져오기 실패", "sources": [], "fear_greed": None}
    text = "[SNS 글은 개인 의견이다. 분위기·쏠림을 해설하되 사실처럼 단정하지 말 것]\n" + "\n".join(parts)
    return {"text": text[:5000], "summary": " · ".join(p.split("]")[0] + "]" for p in parts), "sources": sources[:6], "fear_greed": fg}


# ------------------------------------------------------------------ 웹 검색 (DuckDuckGo HTML → Bing)
def web_search(query: str, n: int = 8) -> list[dict]:
    if _offline():
        return []
    out = []
    try:
        r = _get("https://html.duckduckgo.com/html/?kl=kr-kr&q=" + quote_plus(query))
        for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>(.*?)(?:<a[^>]+class="result__snippet"[^>]*>(.*?)</a>)?', r.text, re.S):
            href = html.unescape(m.group(1))
            if "uddg=" in href:
                href = unquote(parse_qs(urlparse(href).query).get("uddg", [href])[0])
            out.append({"title": _strip(m.group(2)), "url": href, "snippet": _strip(m.group(4) or "")})
            if len(out) >= n:
                break
    except Exception:  # noqa: BLE001
        pass
    if not out:
        try:
            r = _get("https://www.bing.com/search?setlang=ko&cc=KR&q=" + quote_plus(query))
            for m in re.finditer(r'<li class="b_algo".*?<h2[^>]*><a[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?(?:<p[^>]*>(.*?)</p>)?', r.text, re.S):
                out.append({"title": _strip(m.group(2)), "url": html.unescape(m.group(1)), "snippet": _strip(m.group(3) or "")})
                if len(out) >= n:
                    break
        except Exception:  # noqa: BLE001
            pass
    return out


def _strip(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s or ""))).strip()


def web_fetch(url: str, max_chars: int = 4000) -> str:
    if _offline():
        return ""
    r = _get(url)
    t = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", r.text)
    return _strip(t)[:max_chars]


# ------------------------------------------------------------------ 유튜브 (키 없이 검색 페이지의 ytInitialData)
_NUM = {"억": 1e8, "만": 1e4, "천": 1e3, "K": 1e3, "M": 1e6, "B": 1e9}


def _views(s: str | None) -> int | None:
    if not s:
        return None
    m = re.search(r"([\d.,]+)\s*([억만천KMB]?)", s)
    if not m:
        return None
    try:
        return int(float(m.group(1).replace(",", "")) * _NUM.get(m.group(2), 1))
    except ValueError:
        return None


def _balanced(src: str, start: int) -> str | None:
    depth, i, instr, esc = 0, start, False, False
    while i < len(src):
        ch = src[i]
        if instr:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                instr = False
        elif ch == '"':
            instr = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
        i += 1
    return None


def _txt(o) -> str:
    if not o:
        return ""
    if isinstance(o, str):
        return o
    if "simpleText" in o:
        return o["simpleText"]
    if "runs" in o:
        return "".join(r.get("text", "") for r in o["runs"])
    if "content" in o:
        return o["content"]
    return ""


def youtube_search(query: str, n: int = 10) -> dict:
    if _offline():
        return {"items": [], "via": "offline", "note": "테스트 모드"}
    items, via = [], "youtube"
    try:
        page = _get(f"https://www.youtube.com/results?search_query={quote_plus(query)}&hl=ko&gl=KR").text
        k = page.find("var ytInitialData = ")
        blob = _balanced(page, page.find("{", k)) if k >= 0 else None
        data = json.loads(blob) if blob else {}

        def walk(o, d=0):
            if d > 40 or len(items) >= n:
                return
            if isinstance(o, dict):
                if "videoRenderer" in o:
                    v = o["videoRenderer"]
                    vt = _txt(v.get("viewCountText"))
                    items.append({"videoId": v.get("videoId"), "title": _txt(v.get("title")), "channel": _txt(v.get("ownerText") or v.get("longBylineText")),
                                  "views": vt, "viewCount": _views(vt), "published": _txt(v.get("publishedTimeText")), "length": _txt(v.get("lengthText")),
                                  "url": f"https://www.youtube.com/watch?v={v.get('videoId')}"})
                    return
                for v in o.values():
                    walk(v, d + 1)
            elif isinstance(o, list):
                for v in o:
                    walk(v, d + 1)
        walk(data)
    except Exception:  # noqa: BLE001
        pass
    if not items:
        via = "web"
        for r in web_search(f"site:youtube.com {query}", n):
            if "youtube.com/watch" in r["url"] or "youtu.be" in r["url"]:
                items.append({"title": r["title"], "url": r["url"], "channel": "", "views": "", "viewCount": None, "published": "", "length": ""})
    return {"items": items[:n], "via": via, "note": "" if items else "검색 결과 없음(접속 제한일 수 있음)"}


def instagram_search(query: str, n: int = 6) -> dict:
    seen, items = set(), []
    tag = query.replace(" ", "")
    for q in (f"site:instagram.com {query}", f'site:instagram.com "#{tag}"'):
        for r in web_search(q, 8):
            if "instagram.com" not in r["url"] or r["url"] in seen:
                continue
            seen.add(r["url"])
            kind = "릴스" if "/reel" in r["url"] else "게시물" if "/p/" in r["url"] else "해시태그" if "/tags/" in r["url"] else "계정"
            items.append({**r, "kind": kind, "source": "인스타그램"})
    return {"items": items[:n], "via": "web", "note": "" if items else "검색 결과 없음"}


COMMUNITY = {"코인판": "coinpan.com", "비트코인갤": "gall.dcinside.com", "클리앙": "clien.net", "뽐뿌": "ppomppu.co.kr",
             "네이버블로그": "blog.naver.com", "티스토리": "tistory.com", "bitcointalk": "bitcointalk.org", "레딧": "reddit.com"}


def community_search(query: str, sites: list[str] | None = None, n: int = 4) -> dict:
    items = []
    for name in (sites or ["코인판", "비트코인갤", "네이버블로그", "bitcointalk"]):
        host = COMMUNITY.get(name, name)
        for r in web_search(f"site:{host} {query}", n):
            items.append({**r, "source": name})
    return {"items": items[:16], "via": "web", "note": "" if items else "검색 결과 없음"}


def media_text(res: dict, kind: str) -> str:
    items = res.get("items") or []
    lines = [f"[{kind}] {len(items)}건 · {res.get('via', '')}{(' · ' + res['note']) if res.get('note') else ''}",
             "※ 조회수·게시글은 인기·개인 의견이지 사실 확인이 아니다. 내용을 인용할 때는 원 출처로 확인할 것."]
    for i, x in enumerate(items, 1):
        meta = " · ".join(v for v in (x.get("source") or x.get("kind"), x.get("channel"), x.get("views"), x.get("published"), x.get("length")) if v)
        sn = "" if kind.startswith("유튜브") else (" — " + (x.get("snippet") or "")[:110] if x.get("snippet") else "")
        lines.append(f"{i}. {x.get('title', '')[:100]} ({meta}){sn}\n   {x.get('url', '')}")
    return "\n".join(lines)[:1790]
