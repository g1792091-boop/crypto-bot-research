"""AI 사무실 조직 — 4개 팀 24명 (다른 연구 세션의 'AI 팀 사무실'에서 코인 관련 팀만 옮김).

누가 말할지는 코드가 정한다(AI 는 말만 한다). 회의 순서: 담당 분석가 → (투자·실행 판단이면) 전략 총괄 → 반론 검토관 → 리스크 책임자 → 정리 담당.
원본의 CEO(한결)는 이 4개 팀 밖이라, 정리·시간별 발표는 전략·리스크팀장 민재(CSO)가 맡는다.
"""
from __future__ import annotations

import re

TEAMS = [
    {"id": "coin", "name": "코인팀", "desc": "현물 · 선물·파생 · 온체인·고래 · 알트코인 · 코인 뉴스", "color": "#f0a020"},
    {"id": "quant", "name": "퀀트 연구소", "desc": "매매법 개발 · 백테스트 검증 · 시그널 추적 · 머신러닝·딥러닝 · 커스텀 지표", "color": "#2e9e6b"},
    {"id": "strat", "name": "전략·리스크팀", "desc": "전략 총괄 · 반론 · 리스크 · 포트폴리오 · 시나리오 · 컴플라이언스", "color": "#d0465a"},
    {"id": "data", "name": "데이터·미디어팀", "desc": "SNS 여론 · 유튜브 · 인스타·커뮤니티 · 데이터 수집 · 시각화 · 파일 작업", "color": "#c2185b"},
]
TEAM_BY = {t["id"]: t for t in TEAMS}

# (id, 이름, 팀, 직함, 역할(reason=추론 자리), 스킬, [머리색, 옷색], 긴머리, 할 일)
_STAFF = [
    ("coin_fut", "레오", "coin", "코인팀장 · 선물", "general", ["crypto_futures"], ["#3a2a1a", "#e2483d"], False,
     "바이낸스 무기한 선물의 펀딩비·미결제약정·롱숏비율·청산가로 과열과 쏠림을 해석한다."),
    ("coin_spot", "코코", "coin", "현물 애널리스트", "general", ["crypto_spot"], ["#f5c542", "#f08a24"], True,
     "바이낸스 현물·선물 차트(추세·지지저항·거래량·도미넌스)를 실제 도구로 확인해 해석한다."),
    ("deriv", "지안", "coin", "선물·파생 애널리스트", "general", ["crypto_futures"], ["#2b1d0e", "#ff7043"], False,
     "펀딩·미결제약정·롱숏·청산 지도와 호가·고래 흐름(futures_flow, orderbook, whale_trades)으로 쏠림을 해설한다."),
    ("onchain", "도하", "coin", "온체인·고래 애널리스트", "general", ["crypto_spot"], ["#1b1b1b", "#00897b"], False,
     "고래 체결·대형 주문벽·거래소 흐름을 추적해 큰손의 진입·이탈을 보고한다."),
    ("alt", "윤슬", "coin", "알트코인 애널리스트", "general", ["crypto_spot"], ["#8d6e63", "#ab47bc"], True,
     "알트코인 순위·거래대금 급증·섹터(레이어1·AI·밈) 순환을 분석한다."),
    ("coinnews", "하람", "coin", "코인 뉴스·규제 애널리스트", "general", ["news", "crypto_spot"], ["#212121", "#26a69a"], False,
     "코인 뉴스·규제·해킹·상장 공지를 찾아 시장 영향으로 해설한다."),

    ("qa", "준호", "quant", "퀀트 연구소장 · 추세 전략", "reason", ["backtest", "crypto_futures"], ["#1d1d2b", "#2f9e6b"], False,
     "보조지표 29종(indicator_all)·호가·고래·선물 수급과 연구 카드를 보고 추세추종 매매법을 만들고, history_backtest로 가장 오래된 과거부터 모든 레버리지·장세 시나리오까지 직접 시험한다."),
    ("qb", "세라", "quant", "퀀트 연구원 · 역추세·변동성", "reason", ["backtest", "crypto_spot"], ["#a0522d", "#c2185b"], True,
     "과매수·과매도, 밴드 이탈, 변동성 수축·확장, 고래 체결·호가 불균형을 노리는 매매법을 만들고 history_backtest로 전체 과거·모든 레버리지 시나리오를 시험한다."),
    ("val", "다온", "quant", "백테스트 검증관", "reason", ["backtest"], ["#444444", "#607d8b"], False,
     "백테스트 결과의 과최적화 위험을 따진다(검증 구간 성과, 거래 수, 낙폭, 수수료). 코드 판정을 쉬운 말로 설명하고 통과·불통과를 뒤집지 않는다."),
    ("trader", "현우", "quant", "시그널 추적 트레이더", "general", ["crypto_futures"], ["#2e2e2e", "#f57c00"], False,
     "검증을 통과한 전략 시그널의 가상 체결 장부(paper_status)와 호가·고래 체결(orderbook, whale_trades)을 보고 포지션·손익과 다음 대응을 보고한다. 실제 주문은 하지 않는다."),
    ("ml", "유진", "quant", "머신러닝·딥러닝 리서처", "general", ["backtest"], ["#212121", "#5c6bc0"], True,
     "보조지표 26개를 특징으로 로지스틱 회귀·신경망·부스팅·딥 신경망·1D 합성곱 신경망을 학습해 방향을 예측하고 롤링 재학습(워크포워드)으로 검증한다."),
    ("cind", "강민", "quant", "커스텀 지표 개발자", "general", ["backtest"], ["#3e2723", "#ffca28"], False,
     "거래소 기본 지표가 아닌 자체 수식 지표를 만들어 전략에 넣고 시험한다."),

    ("strat", "민재", "strat", "전략 총괄(CSO)", "reason", ["backtest"], ["#3b2f2f", "#334e9e"], False,
     "분석가들의 의견으로 실행 계획(진입 조건·손절·목표·기간)이나 전략 초안을 만들고, 필요하면 백테스트로 확인한다. 회의 마지막에는 사용자에게 줄 최종 답을 정리한다."),
    ("devil", "수아", "strat", "반론 검토관", "reason", [], ["#7a1f2b", "#444444"], True,
     "앞의 의견과 계획에 대한 반대 근거를 최소 3개 든다. 마지막 줄에 '판정: 동의' / '판정: 반대' / '판정: 추가 확인 필요' 중 하나만 쓴다."),
    ("risk", "태오", "strat", "리스크 책임자(CRO)", "reason", [], ["#111111", "#b8860b"], False,
     "손실 한도·비중·레버리지·최악의 시나리오를 숫자로 점검한다. 계획을 승인·축소·거부할 수 있지만 키우지는 않는다. 마지막 줄에 '리스크 판정: 승인' / '축소' / '거부' 중 하나를 쓴다."),
    ("pm", "예린", "strat", "포트폴리오 매니저", "general", [], ["#4e342e", "#8d6e63"], True,
     "추적 중인 전략 시그널들의 비중·상관·합산 낙폭을 관리한다."),
    ("scen", "정우", "strat", "시나리오 플래너", "general", [], ["#212121", "#5e35b1"], False,
     "급락·펀딩 급등·거래소 사고 같은 시나리오별 영향과 대응을 준비하고, 방향 예측 장부를 관리한다."),
    ("comp", "아린", "strat", "컴플라이언스 책임자", "general", [], ["#5d4037", "#e57373"], True,
     "코인 파생상품 규제·투자 권유 표현·고레버리지 경고 같은 법·윤리 위험을 점검한다."),

    ("sns", "유나", "data", "데이터·미디어팀장 · SNS 여론", "general", ["news"], ["#d4a017", "#8e24aa"], True,
     "레딧·스톡트윗·공포탐욕지수(sns_buzz)로 사람들의 분위기와 쏠림을 읽고, 뉴스와 비교해 과열·공포를 해설한다."),
    ("eng", "태민", "data", "데이터 엔지니어(파일 작업)", "code", ["coding"], ["#3e2723", "#455a64"], False,
     "사무실 전용 폴더에서 보고서·거래 기록·전략 파일을 만들고 거래 통계를 계산한다."),
    ("yt", "지호", "data", "유튜브 리서처", "general", ["news"], ["#1b1b1b", "#f44336"], False,
     "유튜브에서 코인 영상 흐름과 인기 주제를 찾아 요약한다."),
    ("insta", "나연", "data", "인스타·SNS 리서처", "general", ["news"], ["#8d6e63", "#e91e63"], True,
     "인스타그램·코인 커뮤니티에서 유행과 대중 심리를 살핀다."),
    ("crawl", "시우", "data", "데이터 수집 엔지니어", "code", ["coding"], ["#263238", "#43a047"], False,
     "거래소 공개 데이터(바이낸스·바이비트·OKX)를 모으고 빈 봉·지연·거래소 차이 같은 품질을 점검한다."),
    ("viz", "보라", "data", "데이터 시각화 디자이너", "general", [], ["#4a148c", "#ba68c8"], True,
     "연구·예측·시그널 결과를 표와 차트로 정리해 발표 자료를 만든다."),
]

AGENTS = [{"id": i, "name": n, "team": t, "title": ti, "role": r, "skills": sk, "look": lk, "long": lg, "duty": d}
          for i, n, t, ti, r, sk, lk, lg, d in _STAFF]
TEAM_LEAD = {"coin": "coin_fut", "quant": "qa", "strat": "strat", "data": "sns"}
for a in AGENTS:
    a["lead"] = TEAM_LEAD[a["team"]] == a["id"]
BY_ID = {a["id"]: a for a in AGENTS}
CLOSER = "strat"                      # 회의 정리 · 시간별 발표 (원본의 CEO 자리)
MEMBERS = {t["id"]: [a["id"] for a in AGENTS if a["team"] == t["id"]] for t in TEAMS}

SKILL_AGENT = {"crypto_spot": "coin_spot", "crypto_futures": "coin_fut", "backtest": "strat", "news": "coinnews"}
MARKET = {"coin_spot", "coin_fut", "deriv", "onchain", "alt", "strat", "qa", "qb", "trader"}
DECIDE = re.compile(r"사도|살까|팔까|매수|매도|진입|청산|롱|숏|레버리지|포지션|투자|전략|백테스트|들어가|비중|손절|익절|전망|어때|괜찮|해도 될까|할까")
PLAN = re.compile(r"전략|백테스트|진입|계획|매수|매도|롱|숏|포지션")
SKILL_RE = {
    "crypto_futures": re.compile(r"선물|롱|숏|레버리지|펀딩|청산|미결제|무기한|perp|포지션", re.I),
    "crypto_spot": re.compile(r"코인|비트|이더|리플|솔라나|알트|도지|현물|btc|eth|xrp|sol\b|doge", re.I),
    "news": re.compile(r"뉴스|기사|규제|해킹|상장|발표|이슈"),
    "backtest": re.compile(r"백테스트|매매법|전략|보조지표|승률|손익비"),
}

# 관찰(코드만, AI 호출 없음) — 자리에서 무엇을 보는지
WATCH = {
    "coin_fut": [("quote", "BTCUSDT"), ("whale", "BTCUSDT"), ("book", "BTCUSDT"), ("news", "futures")],
    "coin_spot": [("quote", "BTCUSDT"), ("quote", "ETHUSDT"), ("quote", "XRPUSDT"), ("quote", "SOLUSDT"), ("news", "crypto")],
    "deriv": [("flow", "BTCUSDT"), ("flow", "ETHUSDT"), ("liq", "BTCUSDT")],
    "onchain": [("whale", "BTCUSDT"), ("whale", "ETHUSDT"), ("book", "ETHUSDT")],
    "alt": [("movers", ""), ("quote", "DOGEUSDT"), ("quote", "SOLUSDT")],
    "coinnews": [("news", "crypto"), ("news", "regulation")],
    "qa": [("indicators", "BTCUSDT")], "qb": [("indicators", "ETHUSDT")], "cind": [("indicators", "SOLUSDT")],
    "ml": [("indicators", "BTCUSDT")], "val": [("research", "")], "trader": [("whale", "BTCUSDT"), ("book", "ETHUSDT"), ("paper", "")],
    "strat": [("quote", "BTCUSDT"), ("flow", "BTCUSDT")], "risk": [("book", "BTCUSDT"), ("liq", "BTCUSDT")],
    "devil": [("news", "crypto")], "pm": [("paper", "")], "scen": [("liq", "ETHUSDT")], "comp": [("news", "regulation")],
    "sns": [("fng", "")], "yt": [("news", "crypto")], "insta": [("fng", "")], "crawl": [("sources", "")], "viz": [("research", "")],
    "eng": [("paper", "")],
}
RELATED = {
    "coin_spot": ["coin_fut", "strat", "alt"], "coin_fut": ["coin_spot", "risk", "deriv"], "deriv": ["coin_fut", "onchain", "risk"],
    "onchain": ["deriv", "coin_fut", "trader"], "alt": ["coin_spot", "sns", "coinnews"], "coinnews": ["comp", "coin_spot", "sns"],
    "strat": ["devil", "coin_spot", "risk"], "risk": ["strat", "coin_fut", "pm"], "devil": ["strat", "risk"], "pm": ["risk", "trader"],
    "scen": ["risk", "deriv"], "comp": ["coinnews", "strat"], "qa": ["qb", "val", "ml"], "qb": ["qa", "cind"], "val": ["qa", "qb"],
    "trader": ["onchain", "pm"], "ml": ["qa", "cind"], "cind": ["ml", "qb"], "sns": ["insta", "yt", "alt"], "yt": ["sns", "insta"],
    "insta": ["sns", "yt"], "crawl": ["eng", "viz"], "viz": ["crawl", "pm"], "eng": ["crawl", "trader"],
}
IDLE = {"coin": ["🪙 코인 차트 보는 중", "🐋 고래 체결 지켜보는 중"], "quant": ["🧪 백테스트 결과 보는 중", "🧠 모델 특징 고르는 중"],
        "strat": ["⚖️ 포트폴리오 비중 점검 중", "🧯 최악의 시나리오 그려 보는 중"], "data": ["📥 데이터 수집 점검 중", "📈 발표용 차트 그리는 중"]}

AGENDA = [
    {"id": "coin", "room": "coin", "title": "코인-브리핑",
     "topic": "지금 비트코인·이더리움의 현물과 선물 상황을 점검하고, 오늘 주목할 점과 대응 방법을 이야기해 주세요.", "agents": ["coin_spot", "coin_fut", "deriv"]},
    {"id": "strat", "room": "strat", "title": "주간-전략회의",
     "topic": "지금 시장에서 쓸 만한 매매 전략 하나를 골라 조건·손절·목표를 정하고 위험을 따져 주세요.", "agents": ["strat", "coin_spot"]},
    {"id": "news", "room": "coin", "title": "오늘의-코인뉴스",
     "topic": "오늘 코인 시장의 주요 뉴스·규제·상장 소식을 찾아 큰 줄기로 묶어 해설해 주세요.", "agents": ["coinnews", "sns"]},
    {"id": "deriv", "room": "coin", "title": "파생-수급-점검",
     "topic": "선물 펀딩·미결제약정·롱숏 쏠림과 고래 체결, 예상 청산 구간을 점검하고 위험한 쪽을 짚어 주세요.", "agents": ["deriv", "onchain"]},
    {"id": "alt", "room": "coin", "title": "알트-순환-점검",
     "topic": "거래대금이 몰리는 알트코인과 섹터 순환을 점검하고, 비트코인 대비 강약을 이야기해 주세요.", "agents": ["alt", "coin_spot"]},
    {"id": "quant", "room": "quant", "title": "연구-리뷰",
     "topic": "최근 퀀트 연구소가 시험한 매매법·머신러닝 결과를 돌아보고, 다음에 무엇을 시험할지 정해 주세요.", "agents": ["qa", "val", "ml"]},
]

SKILL_PROMPT = {
    "crypto_spot": "- 코인 현물·선물 차트를 다룬다. market_analyze로 실제 지표를 확인하고, 필요하면 market_news(category:\"crypto\")로 최근 흐름을 본다.\n"
                   "- 해설: 지금 가격이 추세의 어디쯤인지(이동평균 위·아래, 지지·저항까지 거리), 거래량이 무엇을 말하는지, 비트코인 도미넌스 같은 코인 시장 특유의 맥락을 말로 풀어 준다.\n"
                   "- 그 다음 상승·하락·횡보 시나리오와 각 시나리오에서의 대응(분할 진입 구간, 손절 기준, 목표 구간)을 이야기하듯 설명한다.",
    "crypto_futures": "- 코인 무기한 선물을 분석한다(펀딩비·미결제약정·롱숏비율 포함, futures_flow·orderbook·whale_trades).\n"
                      "- 해설: 펀딩비가 양(+)이면 롱이 숏에게 비용을 내는 과열 신호인지, 미결제약정이 가격과 같이 늘었는지(새 돈 유입) 줄었는지(청산·정리), 롱숏비율이 한쪽으로 쏠렸는지를 연결해서 '지금 선물 시장 참여자들이 어떤 상태인지' 이야기로 풀어 준다.\n"
                      "- 레버리지별 청산가 계산(calculate)과 포지션 크기(계좌의 1~2% 손실 한도)를 꼭 설명한다.",
    "backtest": "- 전략은 strategy_backtest·history_backtest로 실제 시험한다. 조건을 비교할 땐 2~3번 돌린다.\n"
                "- 해설이 핵심이다: 수익률 숫자를 나열하지 말고, 이 전략이 어떤 장세에서 벌고 잃었는지, 그냥 보유한 것보다 나았거나 못했던 이유, 최대낙폭이 견딜 만한지, 거래 횟수와 수수료의 영향, 과최적화 위험, 구체적인 개선 아이디어를 전문가가 설명하듯 풀어서 말한다.",
    "news": "- market_news(category: crypto|futures|regulation)로 최신 기사를 모으고, 중요한 기사는 web_fetch로 본문을 읽는다.\n"
            "- 절대로 기사 제목을 목록으로 늘어놓지 않는다. '지금 무슨 일이 있었고, 왜 그렇고, 시장에 어떤 의미인지'를 하나의 흐름 있는 해설로 말한다.\n"
            "- 여러 기사를 엮어 큰 줄기 2~3개로 묶고, 근거 문장 끝에만 [1]처럼 출처 번호를 단다. 오래된 기사는 그렇다고 밝힌다.",
    "coding": "- 데이터·파일 작업은 정확하게. 계산은 calculate 로 확인한다.",
}
RISK_LINE = "확률적으로 말하고 확정적 예언을 하지 않는다. 투자 판단과 책임은 본인에게 있다는 점을 잊지 않는다."
SKILL_TOOLS = {
    "crypto_spot": ["terminal_consensus", "market_quote", "market_analyze", "market_list", "market_news", "indicator_all", "sns_buzz", "orderbook", "whale_trades", "youtube_search"],
    "crypto_futures": ["terminal_consensus", "market_analyze", "market_quote", "market_list", "market_news", "calculate", "indicator_all", "sns_buzz", "strategy_backtest",
                       "orderbook", "whale_trades", "futures_flow"],
    "backtest": ["market_analyze", "calculate", "strategy_backtest", "history_backtest", "indicator_all", "paper_status", "ml_predict"],
    "news": ["market_news", "web_search", "web_fetch", "sns_buzz", "youtube_search", "community_search"],
    "coding": ["web_search", "calculate"],
}
CORE_TOOLS = ["web_search", "web_fetch", "calculate", "research_cards"]


def tools_for(agent_id: str) -> list[str]:
    a = BY_ID[agent_id]
    out = []
    for s in a["skills"]:
        out += SKILL_TOOLS.get(s, [])
    if agent_id in ("pm", "trader", "risk"):
        out += ["paper_status", "futures_flow"]
    if agent_id in ("risk", "scen", "deriv"):
        out += ["liquidation_map"]
    if agent_id in ("devil", "risk", "scen", "comp"):
        out += ["market_analyze", "market_news"]
    return list(dict.fromkeys(out + CORE_TOOLS))


def find_mentions(text: str, exclude: set[str] | None = None) -> list[str]:
    ex = exclude or set()
    out = []
    for a in AGENTS:
        if a["id"] in ex:
            continue
        if f"@{a['name']}" in text or f"@{a['title']}" in text or f"@{a['title'].split(' · ')[0]}" in text:
            out.append(a["id"])
    return out
