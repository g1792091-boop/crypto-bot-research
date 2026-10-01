"""사무실 직원이 회의 중에 부르는 도구 (모델이 <tool name="이름">{json}</tool> 로 부르고 결과를 받는다).

도구는 {"text": 모델이 읽을 결과, "summary": 화면 한 줄, "sources": [{title,url}]} 를 돌려준다. 실패해도 예외 대신 text 로 알린다.
"""
from __future__ import annotations

import json
import re
import time

from .. import indicators as ind
from ..data import market, news
from . import flow, media, quantlab

LEV_HINT = "코인 선물은 1~125배"


def _sym(s: str | None) -> str:
    s = (s or "BTCUSDT").upper().replace("-", "").replace("/", "").replace("KRW", "")
    names = {"비트코인": "BTCUSDT", "이더리움": "ETHUSDT", "리플": "XRPUSDT", "솔라나": "SOLUSDT", "도지": "DOGEUSDT", "도지코인": "DOGEUSDT"}
    s = names.get(s, s)
    return s if s.endswith("USDT") else s + "USDT"


_IV = {"1": "1m", "5": "5m", "15": "15m", "60": "1h", "240": "4h", "D": "1d", "W": "1w"}


def _iv(x: str | None) -> str:
    x = str(x or "1h")
    return _IV.get(x, x if x in market.INTERVALS else "1h")


def market_quote(symbols=None, **_):
    syms = [_sym(s) for s in (symbols if isinstance(symbols, list) else [symbols or "BTCUSDT"])][:8]
    rows, src = market.tickers(syms)
    out = [{"종목": r["symbol"], "현재가": r["price"], "변동%": round(r["change_pct"], 2), "고가": r["high"], "저가": r["low"],
            "거래대금": round(r.get("quote_volume", 0))} for r in rows]
    return {"text": json.dumps(out, ensure_ascii=False), "summary": " · ".join(f"{r['종목'].removesuffix('USDT')} {r['변동%']:+.2f}%" for r in out),
            "data": out}


def market_analyze(market_: str | None = None, timeframe: str | None = None, **kw):
    sym, iv = _sym(market_ or kw.get("symbol")), _iv(timeframe or kw.get("interval"))
    c, src = market.candles(sym, iv, 400)
    cl = [b["close"] for b in c]
    rsi, atr = ind.rsi(cl, 14)[-1], ind.atr(c, 14)[-1]
    m20, m60, m120 = (ind.sma(cl, n)[-1] for n in (20, 60, 120))
    bb = ind.bbands(cl, 20, 2)
    mh = ind.macd(cl)["hist"][-1]
    hi, lo = max(b["high"] for b in c[-60:]), min(b["low"] for b in c[-60:])
    pc = lambda k: round((cl[-1] / cl[-1 - k] - 1) * 100, 2) if len(cl) > k else None
    d = {"종목": sym, "봉": iv, "가격": cl[-1], "변동%": {"5봉": pc(5), "20봉": pc(20), "60봉": pc(60)}, "MA20": m20, "MA60": m60, "MA120": m120,
         "RSI14": round(rsi, 1) if rsi else None, "MACD히스토": mh, "볼린저": {"상단": bb["upper"][-1], "하단": bb["lower"][-1], "폭%": bb["width"][-1]},
         "ATR%": round(atr / cl[-1] * 100, 2) if atr else None, "거래량/평균": round(c[-1]["volume"] / (sum(b["volume"] for b in c[-21:-1]) / 20 or 1), 2),
         "60봉 고가": hi, "60봉 저가": lo, "최근 20종가": cl[-20:], "데이터": src}
    try:
        der = market.derivatives(sym, iv, 50)
        f = der.get("funding") or []
        o = der.get("open_interest") or []
        ls = der.get("long_short") or []
        d["펀딩비%"] = f[-1]["value"] if f else None
        d["미결제약정"] = o[-1]["value"] if o else None
        d["롱숏계정비율"] = ls[-1]["value"] if ls else None
    except Exception:  # noqa: BLE001
        pass
    return {"text": json.dumps(d, ensure_ascii=False, default=float)[:3500],
            "summary": f"{sym} {iv} {cl[-1]:,.4g} · RSI {d['RSI14']} · 20봉 {d['변동%']['20봉']:+}%" if d["변동%"]["20봉"] is not None else sym,
            "chart": {"symbol": sym, "interval": iv}}


def market_list(sort: str = "volume", top: int = 10, **_):
    rows = market.heatmap(200)
    key = {"volume": lambda r: -r["quote_volume"], "gain": lambda r: -r["change_pct"], "loss": lambda r: r["change_pct"]}.get(sort, lambda r: -r["quote_volume"])
    rows = sorted(rows, key=key)[:max(1, min(30, int(top or 10)))]
    return {"text": json.dumps([{"종목": r["symbol"], "변동%": round(r["change_pct"], 2), "거래대금": round(r["quote_volume"])} for r in rows], ensure_ascii=False),
            "summary": " · ".join(f"{r['symbol'].removesuffix('USDT')} {r['change_pct']:+.1f}%" for r in rows[:5])}


_CAT = {"crypto": None, "futures": re.compile(r"futures|liquidat|funding|open interest|선물|청산|펀딩|미결제", re.I),
        "regulation": re.compile(r"SEC|regulat|law|ban|court|규제|법|당국|금지|소송|ETF", re.I)}


def market_news(category: str = "crypto", symbol: str | None = None, **_):
    items = news.headlines(60)["items"]
    rx = _CAT.get(category)
    if rx:
        items = [x for x in items if rx.search(x["title"])] or items
    if symbol:
        s = symbol.upper().removesuffix("USDT")
        items = [x for x in items if s in x["title"].upper()] or items
    items = items[:12]
    text = "[아래 기사들을 제목 목록으로 옮기지 말고, 큰 줄기로 묶어 해설하라. 근거 문장 끝에만 [번호]]\n" + "\n".join(
        f"[{i}] {x['title']} ({x['source']}, {time.strftime('%m-%d %H:%M', time.localtime(x['time'])) if x.get('time') else '-'})" for i, x in enumerate(items, 1))
    return {"text": text[:3000] if items else "뉴스를 가져오지 못했습니다.", "summary": f"기사 {len(items)}건",
            "sources": [{"title": x["title"][:90], "url": x["url"]} for x in items[:5]]}


def indicator_all(market_: str | None = None, timeframe: str | None = None, **kw):
    sym, iv = _sym(market_ or kw.get("symbol")), _iv(timeframe or kw.get("interval"))
    c, _ = market.candles(sym, iv, 400)
    s = quantlab.snapshot(c)
    return {"text": f"{sym} {iv} 최근 봉 기준\n{s['text']}\n\n[지표 값]\n{json.dumps(s['ind'], ensure_ascii=False, default=float)[:3500]}",
            "summary": s["text"].split("\n")[0][:120]}


def _spec(spec):
    from ..strategy import StrategySpec
    from .engine import normalize_spec
    return StrategySpec.model_validate(normalize_spec(spec))


def strategy_backtest(spec=None, market_: str | None = None, timeframe: str | None = None, **kw):
    sp = _spec({**(spec or {}), **({"symbol": _sym(market_)} if market_ else {}), **({"interval": _iv(timeframe)} if timeframe else {})})
    c, _ = market.candles(sp.symbol, sp.interval, 1500)
    g = quantlab.gate(sp, c)
    f = lambda s: f"수익 {s.get('ret')}% · 최대낙폭 {s.get('dd')}% · 승률 {s.get('win')}% · 손익비 {s.get('pf')} · 거래 {s.get('n')}회"
    text = (f"[{sp.name}] {sp.symbol} {sp.interval} · 캔들 {len(c)}개\n전체: {f(g['all'])}\n개발 구간(앞 70%): {f(g['is'])}\n검증 구간(뒤 30%): {f(g['oos'])}\n"
            f"판정: {'통과' if g['pass'] else '불통과'} — " + " / ".join(g["reasons"]))
    return {"text": text, "summary": f"{sp.name}: {'통과' if g['pass'] else '불통과'} · 검증 {g['oos'].get('ret')}%"}


def history_backtest(spec=None, market_: str | None = None, interval: str | None = None, **kw):
    sp = _spec({**(spec or {}), **({"symbol": _sym(market_)} if market_ else {}), **({"interval": _iv(interval)} if interval else {})})
    c, note = quantlab.history(sp.symbol, sp.interval)
    g = quantlab.gate(sp, c)
    sc = quantlab.scenarios(sp, c, sig=g["sig"])
    return {"text": f"[{sp.name}] {note}\n판정: {'통과' if g['pass'] else '불통과'} — " + " / ".join(g["reasons"]) + "\n\n" + sc["text"],
            "summary": f"{sp.name}: {'통과' if g['pass'] else '불통과'} · 시나리오 {sc['grade']}"}


def ml_predict(market_: str | None = None, interval: str | None = None, model: str = "logreg", **kw):
    from ..quant import ml
    sym, iv = _sym(market_ or kw.get("symbol")), _iv(interval or kw.get("timeframe"))
    c, _ = market.candles(sym, iv, 3000)
    res = ml.cached(c, model=model if model in ml.MODELS else "logreg", horizon=1)
    last = next((p for p in reversed(res["prob"]) if p is not None), None)
    return {"text": ml.text(res) + (f"\n지금 봉 기준 다음 봉 상승 확률: {last:.2f}" if last is not None else ""),
            "summary": f"{ml.MODEL_KO.get(res['model'])} {sym}: {res['edge']} · 정확도 {res['metrics']['accuracy']}"}


def paper_status(**_):
    from .engine import book_text
    t = book_text()
    return {"text": t, "summary": t.split("\n")[0][:120]}


def research_cards(symbol: str | None = None, interval: str | None = None, **_):
    from .. import knowledge
    return {"text": knowledge.brief(_sym(symbol) if symbol else None, interval), "summary": "연구 카드 확인"}


def calculate(expression: str = "", **_):
    from ..quant import customind
    v = customind.evaluate(str(expression), [{"time": 0, "open": 0, "high": 0, "low": 0, "close": 0, "volume": 0}], {})[0]
    return {"text": f"{expression} = {v}", "summary": f"= {v}"}


def _wrap(fn):
    def w(**kw):
        r = fn(**kw)
        return r if isinstance(r, dict) else {"text": str(r), "summary": ""}
    return w


def sns_buzz(symbol: str = "BTC", **_):
    return media.sns_buzz(symbol)


def youtube_search(query: str = "비트코인 전망", n: int = 8, **_):
    r = media.youtube_search(query, n)
    return {"text": media.media_text(r, "유튜브 영상"), "summary": f"영상 {len(r['items'])}건",
            "sources": [{"title": x["title"][:90], "url": x["url"]} for x in r["items"][:4]]}


def community_search(query: str = "비트코인", **_):
    r = media.community_search(query)
    return {"text": media.media_text(r, "커뮤니티·블로그"), "summary": f"글 {len(r['items'])}건",
            "sources": [{"title": x["title"][:90], "url": x["url"]} for x in r["items"][:4]]}


def web_search(query: str = "", n: int = 6, **_):
    rs = media.web_search(query, int(n or 6))
    return {"text": "\n".join(f"[{i}] {r['title']} — {r['snippet'][:160]}\n{r['url']}" for i, r in enumerate(rs, 1)) or "검색 결과 없음",
            "summary": f"결과 {len(rs)}건", "sources": [{"title": r["title"][:90], "url": r["url"]} for r in rs[:4]]}


def web_fetch(url: str = "", max: int = 4000, **_):
    t = media.web_fetch(url, int(max or 4000))
    return {"text": t or "본문을 가져오지 못했습니다.", "summary": f"{len(t)}자", "sources": [{"title": url[:80], "url": url}]}


def _flow(fn):
    def w(symbol: str | None = None, **kw):
        r = fn(_sym(symbol or kw.get("market")))
        return {"text": r.get("text", ""), "summary": r.get("summary", "")}
    return w


# 이름 → (함수, 화면 라벨, 인자 예시)
TOOLS = {
    "market_quote": (market_quote, lambda a: f"{', '.join(map(str, a.get('symbols') or ['BTCUSDT']))} 시세", '{"symbols":["BTCUSDT","ETHUSDT"]}'),
    "market_analyze": (lambda **a: market_analyze(a.pop("market", None), a.pop("timeframe", None), **a), lambda a: f"{a.get('market') or a.get('symbol') or 'BTCUSDT'} {a.get('timeframe') or a.get('interval') or '1h'} 차트 분석", '{"market":"BTCUSDT","timeframe":"60"}'),
    "market_list": (market_list, lambda a: "코인 순위", '{"sort":"volume|gain|loss","top":10}'),
    "market_news": (market_news, lambda a: f"{a.get('category') or 'crypto'} 뉴스 모으기", '{"category":"crypto|futures|regulation","symbol":"선택"}'),
    "indicator_all": (lambda **a: indicator_all(a.pop("market", None), a.pop("timeframe", None), **a), lambda a: f"{a.get('market') or 'BTCUSDT'} 보조지표 29종 계산", '{"market":"BTCUSDT","timeframe":"60"}'),
    "orderbook": (_flow(flow.order_book), lambda a: f"{a.get('symbol') or 'BTCUSDT'} 호가창 보기", '{"symbol":"BTCUSDT"}'),
    "whale_trades": (_flow(flow.whale_trades), lambda a: f"{a.get('symbol') or 'BTCUSDT'} 고래 체결 보기", '{"symbol":"BTCUSDT"}'),
    "futures_flow": (lambda **a: (lambda f, l: {"text": f["text"] + "\n\n" + l["text"], "summary": f["summary"]})(_flow(flow.futures_flow)(**a), _flow(flow.liquidation_estimate)(**a)),
                     lambda a: f"{a.get('symbol') or 'BTCUSDT'} 선물 수급 보기", '{"symbol":"BTCUSDT"}'),
    "liquidation_map": (_flow(flow.liquidation_estimate), lambda a: f"{a.get('symbol') or 'BTCUSDT'} 예상 청산 구간", '{"symbol":"BTCUSDT"}'),
    "strategy_backtest": (lambda **a: strategy_backtest(a.pop("spec", None), a.pop("market", None), a.pop("timeframe", None), **a), lambda a: f"{(a.get('spec') or {}).get('name', '전략')} 백테스트", '{"spec":{전략 JSON},"market":"BTCUSDT","timeframe":"60"}'),
    "history_backtest": (lambda **a: history_backtest(a.pop("spec", None), a.pop("market", None), a.pop("interval", None), **a), lambda a: f"{a.get('market') or (a.get('spec') or {}).get('symbol', 'BTCUSDT')} 전체 과거 백테스트", '{"spec":{전략 JSON},"market":"BTCUSDT","interval":"4h"}'),
    "ml_predict": (lambda **a: ml_predict(a.pop("market", None), a.pop("interval", None), **a), lambda a: f"{a.get('market') or 'BTCUSDT'} 머신러닝 예측", '{"market":"BTCUSDT","interval":"1h","model":"logreg|mlp|gbs|dnn|cnn"}'),
    "paper_status": (paper_status, lambda a: "시그널 추적 장부 확인", "{}"),
    "sns_buzz": (sns_buzz, lambda a: f"{a.get('symbol') or 'BTC'} SNS 여론 확인", '{"symbol":"BTC"}'),
    "youtube_search": (youtube_search, lambda a: f"유튜브에서 ‘{a.get('query', '')}’ 검색", '{"query":"비트코인 전망","n":8}'),
    "community_search": (community_search, lambda a: f"커뮤니티에서 ‘{a.get('query', '')}’ 찾기", '{"query":"이더리움"}'),
    "web_search": (web_search, lambda a: f"‘{a.get('query', '')}’ 검색", '{"query":"검색어","n":6}'),
    "web_fetch": (web_fetch, lambda a: f"{(a.get('url') or '')[:40]} 읽기", '{"url":"https://..."}'),
    "calculate": (calculate, lambda a: f"계산 {str(a.get('expression', ''))[:40]}", '{"expression":"50000*(1-1/20+0.004)"}'),
    "research_cards": (research_cards, lambda a: "연구 카드 확인", '{"symbol":"BTCUSDT","interval":"1h"}'),
}
ICON = {"market_analyze": "📈", "market_quote": "💹", "market_news": "📰", "web_search": "🔎", "web_fetch": "📄", "calculate": "🧮",
        "strategy_backtest": "🧪", "history_backtest": "🧪", "orderbook": "📚", "whale_trades": "🐋", "futures_flow": "🌊", "liquidation_map": "💥",
        "sns_buzz": "📱", "youtube_search": "▶️", "community_search": "💬", "indicator_all": "📊", "ml_predict": "🧠", "paper_status": "📒",
        "market_list": "🏁", "research_cards": "🗂"}


def run(name: str, args: dict) -> dict:
    if name not in TOOLS:
        return {"text": f"없는 도구: {name}", "summary": "없는 도구", "error": True}
    try:
        r = TOOLS[name][0](**(args or {}))
        return r if isinstance(r, dict) else {"text": str(r), "summary": ""}
    except Exception as e:  # noqa: BLE001
        return {"text": f"도구 실패: {str(e)[:300]}", "summary": f"실패: {str(e)[:60]}", "error": True}


def describe(names: list[str]) -> str:
    return "\n".join(f"- {n}: {TOOLS[n][2]}" for n in names if n in TOOLS)
