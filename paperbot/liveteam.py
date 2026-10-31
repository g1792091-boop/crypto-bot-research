"""실거래 분석 팀 (owners 10/19: "실거래봇인데 에이전트 팀 분석은 필요없어?" -> "만들어주고 실거래 대시보드 화면 안에").

Four AI members read what the live side recorded and explain it in plain Korean; they never trade. Everything they see is
a packet the code builds from the same readers as the dashboard's 실거래 screen (paperbot/dash/more/livebots.py: the
paper bot's database, both executors' databases, livecheck.db, liveimprove.db, the 5-year reference), read-only. They
have no tools (paperbot/agents/runner.py: Claude Code in print mode, ``--tools ""``, on the owners' subscription login),
no order key, no way to change a setting. What they write lands in their own database (``liveteam.db``), on the 실거래 ›
분석팀 tab and, the conclusion only, as a quiet message in the live bot's private chats.

The members (each one call per meeting, in this order; the lead reads the others):
    방패  리스크 담당   drawdown, losing runs, halts, the light, costs, what the executors did
    저울  통계 담당     is it luck? sample size, the honest band, the 5-year numbers (fitted vs unseen)
    나침반 시장 담당    regime, coin, time of day, side, the macro calendar
    등대  팀장          the conclusion: summary, good, worries, what to watch, at most three ideas to TEST

Meetings (code decides when; ``tick`` runs one due meeting at most):
    loss        the last two closed trades of a live executor both lost (closed within 3 days): once per pair
    checkpoint  the paper account reached 40, 80, 120 ... closed trades: once each (the A+C bot's 40-trade 88% / 82%
                rule only while its 5-year reference is the running config's; 규칙봇 15 has none: checkpoint_rule)
    weekly      Monday from 10:00 KST: the week before (Monday 09:00 to Monday 09:00); no closed trade = a quiet
                line without AI
The fixed rules are never up for discussion (fixed_rules: read from the running configs, the paper bot's and both
executors'; the owners' 10-19 decisions, FIXED, for a config that cannot be read), an idea is only ever a hypothesis
to test in the way the improvement ledger already does (2020-24 then 2025-26, then a shadow bot): the owners decide, by
hand.

추세판단 봇 (owners 10/21, docs/trend-bot-ko.md; the running paper bot's config has ``trend``: ``is_trend``): the packet
describes that bot instead (``facts_trend``), from the live site's own read-only readers (dash/more/livetrend.py 관제,
livereview.py 검토, livereplayref.py 재현 비교, livebots.py): its rules (TrendRules.describe() and the config) and the
owners' decisions (the 10-22 design: 18 entry members, 4h entries on the closed daily bar, 보류 허용, 바로 진입 with the
pullback wait compared in the shadow trend-wait; no 시간 정리 exit, no pauses or daily limit, the Nasdaq-open 22:00~23:00
KST window, real size about 40 % of each real wallet via qty_scale, the 2-week freeze to the review), its record since
its own start only (``trend_since``: the paper, its coin-flip twin, each executor; a trade entered before is the bot
before it's, kept apart as ``old_bot_trades``), each coin's trend now (1h, 4h and daily), the waits, where the signals
stopped (funnel), the supervisor's exits and the switch close, the costs split against the 7/1~10/20 replay and what the
replay leads to expect (labelled 가상), and the new rules' what-ifs (가상). No 5-year reference and no 40-trade 88 % rule:
a checkpoint is "N번째 거래 점검" on its own trades. The members' prompts (``system_prompt(role, trend=True)``) speak of
its parts (judgment, checks, the entry: at once or after a pullback as fixed_rules says, supervisor, costs); an idea is a
hypothesis to test with a shadow bot (deploy/combo.shadow-trend-*.json) or at the 2-week review. Any other config:
everything as before.

VWAP 개선판 (owners 10-25: "vwap 개선판봇 … 연구분석이나 손실 분석 … 전부 다 만들어줘"; docs/vwap-bot-ko.md 9): the second
paper bot and the executor that follows it (딥코인) get their own meetings, never mixed with the main bot's. Its facts
(``facts_vwap``) come from the live site's VWAP screens (dash/more/livevwap.py: 관제, 성적, 막은 신호; ``vwap_sources``):
its rules from its running config (the gates, the 2 ATR stop, the ladder, the hold limit, the pauses) and its
followers' executor rules (the size from the balance, the light), the owners' decisions (VWAP_DECISIONS), its record since
its own start (the paper, its coin-flip twin and each follower's trades while it followed this bot, apart), 운이냐
고장이냐 (paperbot/vwapband.py: the win rate, the losing run and the deepest drop against its own 5-year paper trades,
which lost per trade; the 17 days labelled as the picked best period), the costs (DeepCoin's taker against the research's
and what the live fills paid), the signals its gates kept out with their what-ifs (가상), the coins now, the splits.
    loss        an executor's last two closed trades made while it followed the VWAP bot both lost (closed within 3 days):
                once per pair, key "loss:vwap:…"; those trades never count for the main bot's loss meeting
    checkpoint  the VWAP paper's 50th, 100th … closed trade since its start (the guide's unit: 실거래 50번 · 80 %), and a
                follower's own 50th, 100th … live trade on it (the owners' moment to decide about money): once each
    weekly      the weekly report gets the VWAP bot's part (``vwap_bot``; the members answer it apart: ``vwap_points``, the
                lead's ``vwap``), the message tells it under its own name
Its members' instructions (``vwap_prompt``; ``vwap_section_prompt`` added to the weekly report's) name it, keep the trend
bot's numbers out, say the 5 years lost per trade and that "정상 범위" only means "as in the 5 years", and keep the fixed
rules and the owners' decisions out of discussion; an idea is a hypothesis to test (2020-24 then 2025-26, or a shadow
bot). Every message names the bot: "VWAP 개선판 · 딥코인 손실 회의".

Budget (the owners' Claude plan, shared with their chats): LIVETEAM_BUDGET="day=12,week=40,tokens_day=900000"
(calls per KST day, calls per 7 KST days, tokens per KST day). A meeting starts only when all its calls fit, each call
is charged at its worst case first (runner.call_charge) and at what it used after.

    python -m paperbot.liveteam tick [--dry-run]          the timer (deploy/paperbot-liveteam.timer, installed off)
    python -m paperbot.liveteam run weekly|loss|checkpoint [--force] [--dry-run] [--vwap]     --vwap: the VWAP bot's own
    python -m paperbot.liveteam preview weekly|loss|checkpoint [--vwap]   the packet and the prompts, no AI call, nothing written
    python -m paperbot.liveteam status
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sqlite3
import sys
import time
from typing import Any, Callable, Optional

from .notify import INFO

DB_DEFAULT = "/var/lib/paperbot/liveteam.db"
DB_ENV = "PAPERBOT_LIVETEAM_DB"
BUDGET_ENV = "LIVETEAM_BUDGET"
MODEL_ENV = "LIVETEAM_MODEL"
BUDGET_DEFAULT = {"day": 12, "week": 40, "tokens_day": 900_000}
MODEL_DEFAULT = "sonnet"
MIN = 60_000
HOUR = 3_600_000
DAY = 86_400_000
KST_MS = 9 * HOUR
CHECK_EVERY = 40                       # the owners' 40-trade decision, then every 40 more
LOSS_FRESH_MS = 3 * DAY                # a losing pair older than this when the team is turned on is left alone
WEEKLY_HOUR = 10                       # Monday from 10:00 KST (after liveimprove's 09:30 scorecard)
TEXT_MAX = 400                         # characters kept of one line a member wrote
LIST_MAX = 6
IDEAS_MAX = 3
SMALL_N = 20
DASH_HINT = "대시보드 › 실거래 › 분석팀"

ROLES = {
    "risk": {"name": "방패", "title": "리스크 담당",
             "focus": "잔고와 낙폭, 연속 손실, 실행기 멈춤·비상 정지, 실거래가 페이퍼를 제대로 따라갔는지(신호등은 켜져 있을 때만), "
                      "수수료·미끄러짐 같은 비용"},
    "stats": {"name": "저울", "title": "통계 담당",
              "focus": "이게 우연인지 아닌지. 거래 수가 충분한지, 본전 승률보다 높은지, 이 봇의 5년 기준표가 있으면 현실 기대 범위"
                       "(처음 보는 기간) 안인지와 맞춘 숫자(낙관)와 비교해 어떤지, 없으면 시작 근거와 비교해 어떤지. 다른 사람이 성급하게 "
                       "결론 내면 반박하는 역할"},
    "market": {"name": "나침반", "title": "시장 담당",
               "focus": "BTC 4시간 장세(강상승·약상승·강하락·약하락·횡보), 코인, 한국 시간대, 롱/숏, 다가오는 미국 경제 발표"},
    "lead": {"name": "등대", "title": "팀장",
             "focus": "팀원 셋의 말을 모아 두 분이 1분 안에 읽을 결론을 쓰는 역할. 팀원끼리 다르면 어느 쪽이 숫자에 맞는지 밝힘"},
}
KIND_ROLES = {"weekly": ("risk", "stats", "market", "lead"), "loss": ("risk", "stats", "lead"),
              "checkpoint": ("risk", "stats", "market", "lead")}
KIND_KO = {"weekly": "주간 보고", "loss": "손실 회의", "checkpoint": "판단 회의"}
VERDICTS = ("정상 범위", "지켜보기", "주의")
# The owners' fixed rules as the running configs say them (fixed_rules: the paper bot's config, both executors' configs).
# What a config that cannot be read would have said comes from the owners' 10-19 decisions for 규칙봇 15 (from 10-20):
FIXED_PAPER = ("매매법 15개(규칙봇 기본값, 30분·1시간)", "BTC 40배 · 나머지 30배", "증거금 잔고의 40%", "한 번에 포지션 하나",
               "시장가 진입", "손절 순ROE -50%(수수료·슬리피지 포함: 40배 가격 1.11%, 30배 가격 1.53%)",
               "계단 익절(순ROE 11%에서 10% 잠금, 15%에서 12%, 20%에서 17%, 그 뒤 5%마다 (닿은 순ROE - 3%))",
               "빠른 청산: 같은 매매법이 반대 신호를 내면 바로 청산(첫 잠금 전까지만)",
               "추격 진입 막기 4개 매매법(롱은 7일 범위 위 20%·24시간 고점 쪽 10% 안이면, 숏은 아래쪽이면 진입 안 함)",
               "코인 6개(BTC ETH SOL DOGE LTC BCH)", "한국 시간 주말 진입 없음", "미국 경제 발표 앞뒤 30분 진입 없음",
               "나스닥 개장 뒤 30분 진입 없음")
FIXED_EXEC = ("거래소에 거는 손절", "연패·낙폭으로 저절로 멈추지 않음(비상 정지 파일 /var/lib/paperbot/STOP으로만 멈춤)",
              "손절 한 번 최대 잔고의 35%", "신호등 없음(실거래는 페이퍼의 모든 진입을 따라감)")
FIXED = FIXED_PAPER + FIXED_EXEC
# ... and for the 추세판단 봇 (a trend config that cannot be read): the owners' 10-22 design (deploy/combo.trend.json)
FIXED_TREND_PAPER = ("진입 매매법 12개(30분 진입 3개는 끝난 1시간봉 추세, 1시간 진입 5개는 끝난 4시간봉 추세, 4시간 진입 4개는 끝난 일봉 "
                     "추세를 따름) · 판단만 하는 매매법 4개(V3.9 · EMA·DMI·ADX · OBV 추세형 · 일목·AO)는 진입 안 함",
                     "추세 판단: 판단 4개 중 3개 이상 같은 쪽 / ADX 20 이상, 40 넘고 꺾이면 끝물 / 보류여도 진입, 반대 방향만 막음",
                     "진입 전 검사: 상위 봉 EMA20에서 진입 방향 1.5 ATR 넘게 멀면 안 함 / 진입 봉 EMA20에서 1.5 ATR 안 / RSI 롱 70 미만·"
                     "숏 30 초과 / 돌파형(F3_BOS, F15_ORB, N06_MACD_ORB)은 추세 초입만 / 추격 막기 전체",
                     "진입: 검사를 통과한 신호의 그 분에 시장가(되돌림 안 기다림, 실행기도 그때 시장가로 따라감)",
                     "감독 청산: 첫 잠금 전에 상위 봉 추세 판단이 반대로 바뀌면 청산 · 시간 정리 없음",
                     "BTC 40배 · 나머지 30배", "증거금 잔고의 40%", "한 번에 포지션 하나",
                     "손절 순ROE -50%(수수료·슬리피지 포함: 40배 가격 1.11%, 30배 가격 1.53%)",
                     "계단 익절(순ROE 11%에서 10% 잠금, 15%에서 12%, 20%에서 17%, 그 뒤 5%마다 (닿은 순ROE - 3%))",
                     "빠른 청산: 같은 매매법이 반대 신호를 내면 바로 청산(첫 잠금 전까지만)",
                     "추격 진입 막기 12개 매매법(롱은 7일 범위 위 20%·24시간 고점 쪽 10% 안이면, 숏은 아래쪽이면 진입 안 함)",
                     "코인 6개(BTC ETH SOL DOGE LTC BCH)", "한국 시간 주말 진입 없음", "미국 경제 발표 앞뒤 30분 진입 없음",
                     "나스닥 개장 앞 30분·뒤 30분 진입 없음", "청산 뒤 반대로 갈아타지 않음")
# what the owners knew when they started a bot without a 5-year reference (keyed by its config name; its guide)
START_BASIS = {"규칙봇 15": ("docs/live15-start-ko.md '근거와 한계': 규칙봇의 지난 2주 실제 진입을 새 규칙으로 다시 판정하면 58승 4패(94%), "
                            "평일 하루 6.2번 진입, 최대 낙폭 20%(증거금 40%로 계산). 이 2주는 15개를 고를 때 쓴 바로 그 기간이라 앞으로는 "
                            "더 낮을 가능성이 큼. 같은 장에서 동전 던지기로 들어가도 75% 이김. 본전 승률 약 86%(복리) / 82~83%(단순 합계). "
                            "두 분은 첫 1~2주 페이퍼 승률을 이 숫자들과 비교해 판단")}
HOW_RARE_OLD = "현실 숫자(2025-26)로 2연패는 거래 1,000번에 약 47번, 3연패는 약 9번 나왔습니다(5년 기준표 streaks)"
HOW_RARE_NONE = "이 봇은 5년 기준표가 없어 연패가 얼마나 드문지 정한 숫자가 없습니다(페이퍼 승률과 본전 승률로만 봅니다)"
CHECK_RULE_OLD = "페이퍼 거래 40번에서 두 분이 판단: 88% 이상 금액 늘리기 검토 · 82~88% 지켜보기 · 82% 미만 멈추고 다시 생각"
CHECK_RULE_NONE = ("이 봇에는 40번 판단 기준(88%/82%)이 없음(그 숫자는 지난 봇의 5년 기준표로 정한 것). 두 분이 페이퍼 승률을 "
                   "본전 승률(bot.break_even)과 시작 근거(bot.start_basis)에 비교해 판단")

# ---- 추세판단 봇 (owners 10/21, docs/trend-bot-ko.md): its own words for the packet and the prompts
TREND_CHECK_KO = "거래 점검"           # a checkpoint of the trend bot: "40번째 거래 점검" (no 88 % / 82 % rule)
TREND_REVIEW_DAYS = 14                 # owners 10/21 (#13 추천대로): the rules stay 2 weeks from the start, then the review
TREND_PREV_BOT = "규칙봇 15"           # the bot before it on the same database (deploy/trend_switch.py)
TREND_JUDGES_KO = "V3.9 · EMA·DMI·ADX · OBV 추세형 · 일목·AO"
CHECK_RULE_TREND = ("새 규칙이라 40번 판단 기준(88%/82%)이 없음(그 숫자는 지난 봇 것). 거래 점검은 새 봇 시작 뒤 거래 40번마다 숫자를 "
                    "같이 보는 자리일 뿐: 규칙은 2주 검토(bot.review_kst) 전에는 바꾸지 않고, 그 뒤에도 두 분이 정함")
HOW_RARE_TREND = "새 규칙이라 연패가 얼마나 드문지 정한 숫자가 없습니다(5년 기준표 없음)"
TREND_WORDS = ("wins = 순손익이 0보다 큰 거래(실행기와 같은 셈). flip = 같은 순간 같은 크기로 들어가되 방향만 동전으로 정한 비교용 페이퍼 "
               "계좌(진짜 방향이 동전보다 나은지 보는 잣대). luck = 두 승률 차이가 운으로도 생기는 크기인지(90%). break_even = 이길 때 "
               "첫 잠금만큼, 질 때 손절만큼일 때 본전이 되는 승률. replay·whatif = 실제 거래가 아닌 다시 계산한 숫자(가상). "
               "entry_on_hold = 상위 봉 판단이 보류일 때 들어간 거래(보류 허용)")
TREND_IDEA_HOW_KO = "그림자 봇으로 나란히 보거나 2주 검토에서 두 분이 정해요"
TREND_ABOUT_KO = "추세판단 봇의 기록(새 봇 시작 뒤 페이퍼·동전 쌍둥이·두 실행기, 추세 판단, 걸린 신호, 감독 청산, 비용, 7/1~10/20 재현(가상))"
# what the owners decided for a trend config that cannot be read (docs/trend-bot-ko.md 2-3)
TREND_DESIGN_KO = ("새 설계(10/22): 진입 매매법 18개(30분 4개 · 1시간 7개 · 4시간 7개, 모두 추격 막기, 규칙봇 기본값 신호) · 성적과 "
                   "2주 검토는 새 설계 시작부터 새로 셈")
# owners 10/26 ("추세판단봇 … 피보나치 매매법들 다 빼주라", then "OTE도 빼줘"): the five F16_FIB members and F10_OTE@4h out
# of the 10/22 design, its name kept (deploy/trend_drop.py): 12 entry members, the record goes on from the design's start
TREND_OUT_1026 = (("F16_FIB382@30m", "피보나치 38.2% 30분"), ("F16_FIB382@1h", "피보나치 38.2% 1시간"),
                  ("F16_FIB500@1h", "피보나치 50% 1시간"), ("F16_FIB618@4h", "피보나치 61.8% 4시간"),
                  ("F16_FIB764@4h", "피보나치 76.4% 4시간"), ("F10_OTE@4h", "OTE 4시간"))
TREND_FIB_OUT_KO = ("10/26에 뺀 매매법('피보나치 매매법들 다 빼주라', 'OTE도 빼줘'): 피보나치 38.2% 30분 · 피보나치 38.2% 1시간 · "
                    "피보나치 50% 1시간 · 피보나치 61.8% 4시간 · 피보나치 76.4% 4시간 · OTE 4시간 → 진입 매매법 12개(30분 3개 · "
                    "1시간 5개 · 4시간 4개) · 설계 이름 그대로라 성적은 이어서 셈")


def trend_out_ko(members: list) -> Optional[str]:
    """The 10/26 line for a 10/22-design config: the members of TREND_OUT_1026 it no longer has, in the owners' words; None
    when it still has them all (nothing taken out yet)."""
    have = {f"{m.get('strategy')}@{m.get('tf')}" for m in members if isinstance(m, dict)}
    gone = [ko for label, ko in TREND_OUT_1026 if label not in have]
    if not gone:
        return None
    asked = "'피보나치 매매법들 다 빼주라', 'OTE도 빼줘'" if any(ko.startswith("OTE") for ko in gone) else "'피보나치 매매법들 다 빼주라'"
    return f"10/26에 뺀 매매법({asked}): {' · '.join(gone)} → 진입 매매법 {len(have)}개 · 설계 이름 그대로라 성적은 이어서 셈"
TREND_DAILY_KO = "4시간 진입은 끝난 일봉 추세로 판단(10/22 '일봉 추세보고 4시간봉 진입'; 30분 진입은 끝난 1시간봉, 1시간 진입은 끝난 4시간봉)"
TREND_HOLD_KO = "보류 허용(10/22): 상위 봉 판단이 보류여도 진입하고 반대 방향일 때만 막음(힘 약함·끝물·진입 전 검사는 그대로)"
TREND_NOW_KO = ("바로 진입(10/22 '바로 진입으로 가자'): 검사를 통과한 신호는 그 분에 진입 · 되돌림 기다림은 그림자 trend-wait로 나란히 "
                "비교(주문 없음)")
TREND_DECISIONS_FIXED = ("규칙 고정: 새 봇 시작부터 2주는 규칙을 바꾸지 않고 기록을 모은 다음 2주 검토에서 두 분이 정함",
                         TREND_DESIGN_KO, TREND_FIB_OUT_KO, TREND_DAILY_KO, TREND_HOLD_KO, TREND_NOW_KO,
                         "시간 정리 청산 없음(10/21 밤 '시간청산 빼줘'): 첫 잠금 전에는 손절·추세 뒤집힘 감독 청산·빠른 청산만",
                         "쉬기 없음: 손실 뒤 매매법·코인 쉬기 없음, 하루 손실 한도 없음(10/21 '쉬기는 빼주고', '10번은 없애고')",
                         "나스닥 개장 앞 30분·뒤 30분 진입 없음(10/21 밤 '나스닥 개장전 30분도 진입금지로 하자'): 미국 서머타임에는 "
                         "한국 22:00~23:00, 서머타임이 끝나면 23:00~24:00",
                         "실거래 크기: 각 실거래 지갑의 약 40%를 증거금으로(실행기 수량 = 페이퍼 수량 × qty_scale)")
# the members' focus on the trend bot (names and titles as ROLES; the lead's job is the same)
ROLES_TREND = {
    "risk": {"name": "방패", "title": "리스크 담당",
             "focus": "잔고와 낙폭, 연속 손실, 실행기 멈춤·비상 정지, 두 실행기가 페이퍼 진입을 따라갔는지(못 따라간 이유), 감독 청산"
                      "(추세 뒤집힘)·전환 전 포지션 정리·손절, 실거래 크기(각 지갑의 약 40%), 비용(미끄러짐·수수료)"},
    "stats": {"name": "저울", "title": "통계 담당",
              "focus": "이게 우연인지 아닌지. 새 봇 시작 뒤 거래 수가 충분한지, 같은 순간 방향만 동전으로 정한 쌍둥이보다 나은지(운 범위), "
                       "본전 승률, 7/1~10/20 재현(가상)의 보통 범위 안인지, 새 규칙이 도왔는지(가상 계산). 5년 기준표는 없음. 다른 사람이 "
                       "성급하게 결론 내면 반박하는 역할"},
    "market": {"name": "나침반", "title": "시장 담당",
               "focus": "코인별 1시간·4시간·일봉 추세 판단(상승·하락·보류, 힘 약함·끝물), 신호가 어디서 걸렸나(추세 판단·진입 자리 검사·"
                        "추격 막기·쉬는 시간), 코인·시간대·롱/숏, 다가오는 미국 경제 발표와 나스닥 개장. 되돌림 기다림·되돌림 안 옴은 "
                        "되돌림을 기다리는 설정(그림자 trend-wait)의 것"},
    "lead": dict(ROLES["lead"]),
}
# ---- VWAP 개선판 (owners 10-25, docs/vwap-bot-ko.md 9): the second paper bot and the executor that follows it (딥코인)
VWAP_NAME = "VWAP 개선판"
VWAP_CHECK_EVERY = 50                  # the guide's unit (6장: 실거래 50번 · 80 %): the paper's 거래 점검 every 50, the follower's too
VWAP_TRADES_KEEP = 40
VWAP_CARDS_KEEP = 12
# the owners' DeepCoin taker rate as passed on 10-25 (one side, market orders); the code's own cost tables still assume
# 0.05 % until the drill measures the account's own (executor.NET_COSTS, livecheck.ASSUMED_FEE): both are said
DEEPCOIN_TAKER = 0.0004
# research/vwap30/code/vwcommon.py COST_RT: the 5-year research's costs, a taker 0.05 % and a slippage 0.02 % each side
RESEARCH_TAKER, RESEARCH_SLIP = 0.0005, 0.0002
VWAP_APART_KO = ("추세판단 봇과 다른 봇: 매매법·손절·진입 조건이 다르고 페이퍼 기록(vwap.db)과 실거래 실행기도 따로예요. 두 봇 숫자를 "
                 "섞지 않아요")
VWAP_CHECK_RULE = ("docs/vwap-bot-ko.md 6장(두 분): 실거래 50번 동안 승률 80% 이상이고 페이퍼와 결과가 비슷하면 금액 늘리기 검토 · 함께 "
                   "볼 것: 순ROE 합 플러스, 페이퍼가 동전 쌍둥이보다 나음 · 승률이 본전 승률 아래로 이어지면 멈추고 다시 봄. 5년 기록에서는 "
                   "50번 80% 이상 뒤에도 다음 50번이 평균 손해였어요. 거래 점검은 페이퍼 50번마다(실거래 50번마다 따로) 숫자를 같이 보는 "
                   "자리일 뿐, 정하는 것은 두 분")
VWAP_DECISIONS = ("10/23 두 분: 'A + CMO 1시간 37승 3패가 제일 좋은 거 같네' → 매매법 VWAP 복귀 실패 30분 + CMO·샌드위치 캔들 1시간",
                  "10/23 두 분: '시드 비중은 40%, 비트도 30배' → 증거금 잔고의 40%, BTC도 30배",
                  "실거래는 세 번째 실행기(10/24 '그냥 다른거래소 쓸래' → 딥코인). 바이비트·WOO X Pro 실행기는 그대로 추세판단 봇을 따라감",
                  "실거래 크기(10/25 밤): 실행기는 진입할 때마다 자기 잔고의 증거금 비율만큼(sizing에 지금 숫자)",
                  "키우기·멈추기: checkpoint_rule 그대로 · 작게 시작해서 맞으면 키우는 순서(docs/vwap-bot-ko.md 3장)",
                  "10/29 두 분: 바이비트는 '바이비트 봇'(친구 매매법 2개, 스스로 거래: docs/mixbybit-ko.md), WOO X Pro는 레인지 봇"
                  "(추세 확인 = 친구 추세지표 1시간봉), 추세판단 봇은 끔. 딥코인의 VWAP 개선판은 그대로",
                  "10/31 밤 두 분: 레인지 봇 · 바이비트 봇 · 친구 15분 봇(WOO X Pro 2)의 추세는 30분봉 '추세 바' 종합 하나, 진입은 셋 "
                  "다 15분봉(15분봉 추세는 무시), 코인은 셋 다 SOL · ETH · XRP · BCH · ZEC · DOGE. 바이비트 봇은 OBV 진한색 + AC, 친구 "
                  "15분 봇과 레인지 봇은 히스토그램 0선 돌파. 레인지 봇은 WOO X Pro 첫 계정을 스스로 거래(docs/range-bot-ko.md 0장)")
VWAP_WORDS = ("band = 운이냐 고장이냐: 지금 기록을 같은 규칙의 5년 페이퍼에 대 본 것. win.p_low = 5년처럼 돈다면 이만큼 이하의 승수가 "
              "나올 확률, streak.share = 5년 연패 중 이만큼 길었던 비율, dd.share = 5년의 같은 거래 수 구간 중 이만큼 깊게 빠졌던 비율. "
              "verdict: 정상 범위(5% 이상) · 드묾(1~5%) · 아주 드묾(1% 미만: 설계와 다르게 돌고 있을 수 있음). roe = 그 거래 배율 기준 "
              "순ROE(수수료 뒤, 0.1 = 10%). flip = 같은 순간 방향만 동전으로 정한 비교용 페이퍼. breakeven = 평균 익절·손절로 본 본전 승률. "
              "blocked.virtual = 막지 않았다면(가상: 같은 엔진·같은 1분봉으로 다시 계산, 실제 체결 아님)")
VWAP_IDEA_HOW_KO = "2020-24로 고르고 2025-26에서 한 번 확인하거나(research/vwap30 방식), 그림자 봇으로 나란히 봐요"
ROLES_VWAP = {
    "risk": {"name": "방패", "title": "리스크 담당",
             "focus": "실거래 실행기(딥코인) 잔고와 낙폭, 연패(손절 한 번의 크기), 실행기 멈춤·비상 정지, 신호등이 거른 진입, 실행기가 "
                      "페이퍼를 제대로 따라갔는지(결과가 같은 거래·순ROE 차이·진입 미끄러짐), 크기(진입마다 잔고의 증거금 비율), "
                      "수수료(costs)"},
    "stats": {"name": "저울", "title": "통계 담당",
              "focus": "운이냐 고장이냐(band: 승률·연패·낙폭이 5년 페이퍼의 어디인지), 본전 승률, 동전 쌍둥이 비교, 키우기·멈추기 점검표"
                       "(실거래 50번), 거래 수가 충분한지. 5년이 거래당 손해였다는 것과 17일은 고른 기간이라는 것을 숨기지 않음. 다른 "
                       "사람이 성급하게 결론 내면 반박하는 역할"},
    "market": {"name": "나침반", "title": "시장 담당",
               "focus": "코인별 4시간 판단과 변동성 위치(now), 진입 조건이 막은 신호와 그 가상 결과(blocked), 매매법·코인·롱/숏·진입 때 "
                        "4시간 판단·변동성 위치·시간대·청산 이유·보유 시간 나눠 보기(splits), 쉬는 시간과 다가오는 미국 경제 발표"},
    "lead": dict(ROLES["lead"]),
}
SHADOW_TREND_GLOB = "combo.shadow-trend-*.json"   # the trend bot's shadow configs in deploy/ (read only, may not exist yet)
SHADOW_KEEP = 8
TRADE_KEEP = 60
SIG_ROWS = 12

SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    key TEXT NOT NULL UNIQUE,          -- weekly:<Monday, YYYY-MM-DD> | loss:<the pair> | checkpoint:40
    title TEXT NOT NULL,
    started_ts INTEGER NOT NULL,
    finished_ts INTEGER,
    state TEXT NOT NULL,               -- running | done | failed | quiet
    why TEXT,                          -- why it was held, or why it failed
    packet TEXT,                       -- the facts the members read (JSON)
    headline TEXT,
    verdict TEXT,
    result TEXT,                       -- the lead's answer (JSON)
    sent INTEGER,                      -- 1 sent, 0 not sent, NULL no message
    calls INTEGER NOT NULL DEFAULT 0,
    tokens INTEGER NOT NULL DEFAULT 0,
    dry INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,
    ts INTEGER NOT NULL,
    text TEXT NOT NULL,                -- the member's answer as shown (headline and points)
    data TEXT,                         -- the member's JSON
    model TEXT,
    tokens INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
CREATE TABLE IF NOT EXISTS ideas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    idea TEXT NOT NULL,
    why TEXT,
    test TEXT,
    status TEXT NOT NULL DEFAULT '제안'  -- the owners decide what happens next (liveimprove's ledger, by hand)
);
CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    day TEXT NOT NULL,                 -- KST date
    meeting INTEGER,
    role TEXT,
    calls INTEGER NOT NULL,
    tokens INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS state (k TEXT PRIMARY KEY, ts INTEGER NOT NULL, data TEXT);
"""


# ---------------------------------------------------------------- small helpers
def kst_date(ms: int) -> str:
    return _dt.datetime.fromtimestamp((int(ms) + KST_MS) / 1000, _dt.timezone.utc).strftime("%Y-%m-%d")


def kst_text(ms: Optional[int]) -> Optional[str]:
    if ms is None:
        return None
    return _dt.datetime.fromtimestamp((int(ms) + KST_MS) / 1000, _dt.timezone.utc).strftime("%m-%d %H:%M")


def kst_md(ms: Optional[int]) -> Optional[str]:
    """"11/04" (KST month/day), None for None."""
    if ms is None:
        return None
    return _dt.datetime.fromtimestamp((int(ms) + KST_MS) / 1000, _dt.timezone.utc).strftime("%m/%d")


def monday_09(ms: int) -> int:
    """09:00 KST of the Monday of the KST week ``ms`` is in."""
    day = (int(ms) + KST_MS) // DAY
    dow = (day + 3) % 7                                    # Monday 0 .. Sunday 6 (day 0 was a Thursday)
    return (day - dow) * DAY - KST_MS + 9 * HOUR


def parse_budget(raw: Optional[str]) -> dict:
    """LIVETEAM_BUDGET "day=12,week=40,tokens_day=900000" (any subset); a bad part raises ValueError."""
    out = dict(BUDGET_DEFAULT)
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        k, _, v = part.partition("=")
        k = k.strip()
        if k not in out or not v.strip().isdigit():
            raise ValueError(f"{BUDGET_ENV}: '{part}' (쓸 수 있는 것: day=정수, week=정수, tokens_day=정수)")
        out[k] = int(v)
    return out


def _clip(x: Any, n: int = TEXT_MAX) -> str:
    s = " ".join(str(x).split()) if x is not None else ""
    return s if len(s) <= n else s[: n - 1] + "…"


def _list(x: Any, n: int = LIST_MAX) -> list:
    if isinstance(x, str):
        x = [x]
    return [_clip(v) for v in (x or []) if isinstance(v, (str, int, float)) and str(v).strip()][:n] if isinstance(x, list) else []


def connect(path: str) -> sqlite3.Connection:
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.executescript(SCHEMA)
    return conn


def get_state(conn, k: str) -> Optional[dict]:
    r = conn.execute("SELECT data FROM state WHERE k = ?", (k,)).fetchone()
    try:
        return json.loads(r[0]) if r and r[0] else None
    except ValueError:
        return None


def put_state(conn, k: str, now: int, data: dict) -> None:
    conn.execute("INSERT OR REPLACE INTO state VALUES (?,?,?)", (k, int(now), json.dumps(data, ensure_ascii=False, default=str)))
    conn.commit()


# ---------------------------------------------------------------- the running bot (its configs, read-only)
def bot_world(p: Optional[dict] = None) -> dict:
    """The configs the live side runs, read-only: the paper bot's (its own ``combo_run`` record, else the config file the
    live side runs: livecheck.combo_config), the executors' (livecheck.load_executors: plain JSON, never a key file; the
    dashboard's paths; the third, 딥코인, once installed: livebots.installed) and why the 5-year reference does not apply
    when it was made for another config (livecheck.usable_expected; '' = it applies)."""
    from . import livecheck as LC
    from .dash.more import livebots as L
    p = p or L.paths()
    conn = LC.open_ro(p.get("paper") or "")
    try:
        cfg, _where = LC.combo_config(LC.Sources(paper_db=p.get("paper") or LC.PAPER_DB), conn)
    finally:
        if conn is not None:
            conn.close()
    names = {ex for ex, _ko, _dk, _ck in L.installed(p)}
    specs = tuple((name, p.get(f"{name}_config") or path, unit, p.get(f"{name}_db") or db, n, share)
                  for name, path, unit, db, n, share in LC.EXECUTORS + LC.OPTIONAL_EXECUTORS if name in names)
    _exp, ref_ko = LC.usable_expected(LC.Sources())
    out = {"config": cfg, "infos": LC.load_executors(specs), "ref_ko": ref_ko}
    # owners 10-19 (docs/live15-mexc-ko.md): a second paper bot (규칙봇 15 at -35 %) and which executor follows which:
    # the paper database each executor's last start recorded (livecheck.PaperSet, paperbot/livepapers.py)
    second = second_paper(p.get("paper") or LC.PAPER_DB, out["infos"])
    if second:
        out["second"] = second
    # the 추세판단 봇 (owners 10/21): its first start on this database (livebots.trend_bot: state combo trend_since), and no
    # 5-year reference for its new rules (livebots.TREND_NO_REF_KO)
    tb = L.trend_bot(p.get("paper") or "")
    if tb is not None:
        out["trend"] = {k: tb.get(k) for k in ("name", "since", "freeze_until", "freeze_days")}
    if is_trend(out):
        out["ref_ko"] = L.TREND_NO_REF_KO
    return out


def is_trend(world: Optional[dict]) -> bool:
    """The running paper bot is the 추세판단 봇: its start record says so (``trend``), or the config it runs has ``trend``."""
    w = world or {}
    cfg = w.get("config")
    return bool(w.get("trend")) or (isinstance(cfg, dict) and cfg.get("trend") is not None)


COMBO2_CONFIG_ENV, COMBO2_CONFIG = "PAPERBOT_LIVE_COMBO2_CONFIG", "/etc/paperbot/combo-vwap.json"


def second_paper(main: str, infos: list) -> Optional[dict]:
    """{"config", "label", "first_label", "follows": {executor: its paper bot's short name}} when an executor follows
    another paper bot than ``main`` (its last start recorded it), else None."""
    from . import livecheck as LC
    from . import livepapers as LP
    ps = LC.PaperSet(main)
    cur = {}
    for ex in infos:
        c = LC.open_ro(ex.db)
        try:
            cur[ex.label] = LP.current(ps.segs(ex, c))
        finally:
            if c is not None:
                c.close()
    other = next((p for p in cur.values() if not LP.same(p, main)), None)
    if other is None:
        return None
    c2 = LC.open_ro(other)
    try:
        cfg2, _w = LC.combo_config(LC.Sources(paper_db=other, combo_config=os.environ.get(COMBO2_CONFIG_ENV) or COMBO2_CONFIG), c2)
    finally:
        if c2 is not None:
            c2.close()
    names = {LP.norm(main): LC.paper_name(main), LP.norm(other): LC.paper_name(other)}
    fol = lambda path: "·".join(k for k, v in cur.items() if LP.same(v, path))           # noqa: E731
    return {"config": cfg2, "label": f"{names[LP.norm(other)]} ({LP.josa(fol(other), '이', '가')} 따라감)",
            "first_label": f"{names[LP.norm(main)]}" + (f" ({LP.josa(fol(main), '이', '가')} 따라감)" if fol(main) else ""),
            "follows": {k: names.get(LP.norm(v), v) for k, v in cur.items()}}


def _combo(cfg: Optional[dict]):
    """paperbot.combo.ComboConfig of a config dict (a record may lack the paths), None when it cannot be read."""
    if not isinstance(cfg, dict):
        return None
    from . import combo as C
    try:
        return C.ComboConfig.from_dict({"paper_db": "", "db": "", **cfg, "members": list(cfg.get("members") or [])})
    except Exception:  # noqa: BLE001  an unreadable config: the owners' decisions are said instead
        return None


def _paper_rules(cfg: Optional[dict]) -> Optional[list]:
    c = _combo(cfg)
    if c is None or (c.ladder_spec is None and c.take_profit_roe is None):
        return None
    from . import combo as C
    try:
        stop = C.stop_text(c)
    except Exception:  # noqa: BLE001
        return None
    members = [m for m in (cfg.get("members") or [])]
    nc = sum(1 for m in members if isinstance(m, dict) and m.get("no_chase"))
    out = [f"매매법 {len(members)}개", f"BTC {c.lev_of('BTCUSDT')}배 · 나머지 {c.lev_of('ETHUSDT')}배",
           "증거금 " + ("배수%" if c.margin == "leverage" else f"잔고의 {float(c.margin):.0%}"), "한 번에 포지션 하나",
           "시장가 진입", f"손절 {stop}",
           C.take_profit_text(c) if c.take_profit_roe is not None else f"계단 익절({c.ladder_spec.describe()})",
           f"빠른 청산: {C.early_ko(c)}"
           + ("(첫 잠금 전까지만)" if c.early_exit and c.early_exit_until_lock else "")]
    if nc:
        out.append(f"추격 진입 막기 {nc}개 매매법(" + C.CHASE_KO.split("(", 1)[1])
    out.append(f"코인 {len(c.symbols)}개({' '.join(s.replace('USDT', '') for s in c.symbols)})")
    if c.no_weekend:
        out.append("한국 시간 주말 진입 없음")
    if c.macro_blackout_min:
        out.append(f"미국 경제 발표 앞뒤 {c.macro_blackout_min}분 진입 없음")
    if c.us_open_pause_min or c.us_open_pre_min:
        out.append(f"{C.us_open_ko(c.us_open_pause_min or 0, c.us_open_pre_min or 0)} 진입 없음")
    out += C.gate_lines(c)                  # 'VWAP 개선판' (owners 10-23): its entry gates and hold limit; others: none
    out += C.range_lines(c)                 # '레인지 봇' (owners 10-26): its supertrend checks and pullback; others: none
    return out


def _trend_rules(cfg: Optional[dict]) -> Optional[list]:
    """The 추세판단 봇's rules as its config says them: its members, the bot's own words for the judgment, the checks, the
    pullback, the pauses and the supervisor (trendjudge.TrendRules.describe(): the start message's and check-config's
    lines), then what it keeps of the combined bot (_paper_rules), the switch close and no reverse entry."""
    base = _paper_rules(cfg)
    if base is None:
        return None
    from .trendjudge import TrendRules
    try:
        said = TrendRules.from_dict(cfg.get("trend")).describe()
    except Exception:  # noqa: BLE001  an unreadable trend section: the combined bot's lines only
        return None
    members = [m for m in cfg.get("members") or [] if isinstance(m, dict)]
    # 4h entries on the closed daily bar since 10-22 (said only when the config has them)
    parts = [f"{ko} 진입 {n}개는 끝난 {hk} 추세" for ko, n, hk in
             (("30분", sum(1 for m in members if m.get("tf") == "30m"), "1시간봉"),
              ("1시간", sum(1 for m in members if m.get("tf") == "1h"), "4시간봉"),
              ("4시간", sum(1 for m in members if m.get("tf") == "4h"), "일봉")) if n or ko != "4시간"]
    out = [f"진입 매매법 {len(members)}개({', '.join(parts)}를 따름) · 판단만 하는 매매법 4개({TREND_JUDGES_KO})는 진입 안 함"] + list(said)
    waits = (cfg.get("trend") or {}).get("pullback_wait", True) is not False
    entry = ("진입: 되돌림 가격에 닿은 다음 분에 시장가(실행기도 그때 시장가로 따라감)" if waits
             else "진입: 검사를 통과한 신호의 그 분에 시장가(되돌림 안 기다림, 실행기도 그때 시장가로 따라감)")
    for r in base[1:]:
        out.append(entry if r == "시장가 진입" else r)
    out += ["전환 전 포지션 정리: 새 봇 시작 전에 예전 규칙으로 열린 포지션은 첫 잠금 전이면 바로 닫음",
            "청산 뒤 반대로 갈아타지 않음"]
    return out


def _exec_rules(infos: list) -> list:
    from . import livepapers as LP
    out = ["거래소에 거는 손절"]
    streaks = sorted({e.max_streak for e in infos if e.max_streak})
    dds = sorted({e.max_dd for e in infos if e.max_dd is not None})
    kill = infos[0].kill_file
    if not streaks and not dds:
        out.append(f"연패·낙폭으로 저절로 멈추지 않음(비상 정지 파일 {kill}으로만 멈춤)")
    else:
        out.append(" · ".join(([f"{'/'.join(map(str, streaks))}연패 멈춤"] if streaks else [])
                              + ([f"최고점에서 {'/'.join(f'{d:.0%}' for d in dds)} 빠지면 멈춤"] if dds else [])
                              + [f"비상 정지 파일 {kill}"]))
    losses = sorted({e.max_loss for e in infos if e.max_loss is not None})
    if losses:
        out.append(f"손절 한 번 최대 잔고의 {'/'.join(f'{x:.0%}' for x in losses)}")
    for e in infos:
        if getattr(e, "margin_frac", None):
            out.append(f"크기: {LP.josa(e.label, '은', '는')} 진입할 때마다 자기 잔고의 {e.margin_frac:.0%}를 증거금으로 "
                       "(손절이 멀어도 줄이지 않음)")
    lit = [e for e in infos if e.light_on]
    if not lit:
        out.append("신호등 없음(실거래는 페이퍼의 모든 진입을 따라감)")
    for e in lit:
        out.append(f"신호등: {LP.josa(e.label, '은', '는')} 페이퍼 최근 {e.light_n}번 중 {e.light_min:.0%} 이상 이겼을 때만 새 진입을 따라감")
    money = [f"{e.label} ${e.budget:,.0f}" for e in infos if e.budget]
    if money:
        out.append("실거래 금액 " + " · ".join(money))
    return out


def fixed_rules(cfg: Optional[dict], infos: Optional[list], second: Optional[dict] = None, trend_bot: bool = False) -> list:
    """The owners' fixed rules of the live side as the running configs say them (the paper bot's config, the executors'
    configs that could be read); a part whose config cannot be read: the owners' decisions (FIXED_PAPER / FIXED_EXEC; the
    추세판단 봇's, ``trend_bot`` or a ``trend`` config: FIXED_TREND_PAPER, the 10-22 design). ``second`` (bot_world, owners
    10-19): the second paper bot's rules where they differ from the first's (its stop), and which executor follows which
    paper bot. The 추세판단 봇's config (``trend``): its own rules (_trend_rules)."""
    readable = [e for e in (infos or []) if not e.problem]
    is_t = trend_bot or (isinstance(cfg, dict) and cfg.get("trend") is not None)
    trend = _trend_rules(cfg) if isinstance(cfg, dict) and cfg.get("trend") is not None else None
    out = list(trend or (FIXED_TREND_PAPER if is_t else _paper_rules(cfg) or FIXED_PAPER))
    if second:
        from . import livepapers as LP
        from .livecheck import family_of
        mine = _paper_rules(second.get("config")) or []
        f1, f2 = family_of(cfg), family_of(second.get("config"))
        if f2 is not None and f2 != f1:
            # a different bot (owners 10-23, 'VWAP 개선판': other strategies, its own gates and hold limit): all its rules
            mem = [f"{m.get('strategy')} {m.get('tf')}" for m in (second.get("config") or {}).get("members") or []
                   if isinstance(m, dict)]
            out.append(f"두 번째 페이퍼 봇 {second.get('label')}: 첫 번째와 다른 봇(매매법 {', '.join(mem)}) · "
                       + (" · ".join(r for r in mine if not r.startswith("매매법 ")) if mine else "규칙을 못 읽음"))
        else:
            diff = [r for r in mine if r not in out and not r.startswith("매매법 ")]
            out.append(f"두 번째 페이퍼 봇 {second.get('label')}: " + (" · ".join(diff) if diff else "규칙을 못 읽음")
                       + " (나머지 규칙은 첫 번째와 같음)")
        out.append("따라가는 페이퍼: " + " · ".join(f"{LP.josa(k, '은', '는')} {v}" for k, v in (second.get("follows") or {}).items()))
    return out + (_exec_rules(readable) if readable else list(FIXED_EXEC))


def bot_facts(world: Optional[dict]) -> dict:
    """The bot itself: its name, its strategies, its break-even win rate when the stop and the first lock are fixed net
    ROEs (a -50% stop and a +10% first lock: 50 / 60 = 83%, plain sum), whether a 5-year reference applies, and what
    the owners started it on (START_BASIS)."""
    w = world or {}
    cfg = w.get("config") if isinstance(w.get("config"), dict) else {}
    c = _combo(cfg) if cfg else None
    be = None
    if c is not None and c.stop_mode == "roe" and c.ladder_spec is not None:
        s, f = float(c.stop["roe"]), float(c.ladder_spec.first_lock)
        be = round(s / (s + f), 3)
    name = (cfg or {}).get("name") or None
    out = {"name": name or "(설정 이름 없음)", "strategies": len(cfg.get("members") or []) or None,
           "reference": w.get("ref_ko") or "5년 기준표 있음(expect)",
           "break_even": be, "break_even_words": ("본전 승률 = 이길 때 첫 잠금만큼, 질 때 손절만큼일 때 본전이 되는 승률(단순 합계, "
                                                  "수수료 포함 순ROE 기준; 복리로는 조금 더 높음)") if be is not None else None}
    if name in START_BASIS:
        out["start_basis"] = START_BASIS[name]
    sec = w.get("second") if isinstance(w.get("second"), dict) else None
    c2 = _combo(sec.get("config")) if sec else None
    if c2 is not None and c2.stop_mode == "roe" and c2.ladder_spec is not None:
        s2, f2 = float(c2.stop["roe"]), float(c2.ladder_spec.first_lock)
        out["second"] = {"name": (sec.get("config") or {}).get("name"), "label": sec.get("label"), "break_even": round(s2 / (s2 + f2), 3),
                         "why": "손절만 다른 같은 봇: 손절이 좁으면 지는 거래의 손실이 작고 지는 거래는 늘어요(본전 승률이 낮아짐)"}
    elif c2 is not None and (c2.vote_gate is not None or c2.vol_gate is not None):
        # 'VWAP 개선판' (owners 10-23): its stop is 2 ATR, so its break-even is not a config number; the research's 5 years
        # (research/vwap30/scale.json: 5,805 paper trades, average win +10.76 %, average loss -39.43 % net ROE) put it at 78.6 %
        out["second"] = {"name": (sec.get("config") or {}).get("name"), "label": sec.get("label"), "break_even": None,
                         "break_even_5y": 0.786,
                         "why": "다른 매매법의 다른 봇(VWAP 개선판): 손절이 2 ATR이라 본전 승률을 설정만으로 정할 수 없어요. 5년 연구 "
                                "기준(페이퍼 5,805번: 평균 이익 +10.76% · 평균 손실 -39.43%)으로는 78.6%이고, 두 분 기준은 실거래 "
                                "50번 승률 80% 이상이면 금액 늘리기(docs/vwap-bot-ko.md 6장)"}
    return out


# ---------------------------------------------------------------- 추세판단 봇: the bot, the owners' decisions, the size
def trend_bot_facts(world: Optional[dict], now: int) -> dict:
    """bot_facts for the 추세판단 봇: its start on this database (``trend_since``: trades entered before are the bot before
    it's), the 2-week freeze to the review, its members, and no 5-year reference (no start basis of another bot)."""
    from .dash.more import livebots as L
    w = world or {}
    out = bot_facts(w)
    out.pop("start_basis", None)
    cfg = w.get("config") if isinstance(w.get("config"), dict) else {}
    tb = w.get("trend") if isinstance(w.get("trend"), dict) else {}
    since = tb.get("since")
    members = [m for m in cfg.get("members") or [] if isinstance(m, dict)]
    out.update(kind="trend", name=out["name"] if out["name"] != "(설정 이름 없음)" else (tb.get("name") or "추세판단 봇"),
               entry_members=[f"{m.get('strategy')}@{m.get('tf')}" + (" (숏만)" if any(isinstance(c, dict) and c.get("side") == "short"
                                                                                       for c in m.get("when") or []) else "")
                              for m in members],
               judges=f"{TREND_JUDGES_KO} (판단만 하고 진입 안 함)", reference=w.get("ref_ko") or L.TREND_NO_REF_KO,
               since_kst=kst_text(since), review_kst=kst_md(int(since) + TREND_REVIEW_DAYS * DAY) if since else None,
               running_days=round((int(now) - int(since)) / DAY, 2) if since else None,
               old_bot=(f"{TREND_PREV_BOT}: 이 시각({kst_text(since)}) 전에 들어간 거래는 그 봇 것이라 이 봇 성적에 넣지 않음"
                        if since else None))
    if since is None:
        out["since_note"] = ("새 봇이 이 기록 파일에서 처음 켜진 시각(trend_since)을 읽지 못했어요: 거래를 새 봇·예전 봇으로 나누지 못해 "
                             "아래 거래는 어느 봇 것인지 모릅니다")
    return out


def _windows_ko(now: int, mins: int, pre: int) -> Optional[str]:
    """The Nasdaq-open entry pause in Korea time from the next days (liveinsight.us_open_windows: combo.us_open_pause's own
    minutes): "지금은 한국 22:00~23:00, 11/02부터 23:00~24:00" (when US summer time ends within the days looked at)."""
    try:
        from .dash.more import liveinsight as LI
        wins, err = LI.us_open_windows(int(now), int(mins), days=16, pre=int(pre))
    except Exception:  # noqa: BLE001  said without the hours
        return None
    if err or not wins:
        return None

    def hm(ms: int, end: bool) -> str:
        t = kst_text(ms)[-5:]
        return "24:00" if end and t == "00:00" else t
    spans, last = [], None
    for a, b in wins:
        if b <= now:
            continue
        txt = f"{hm(a, False)}~{hm(b, True)}"
        if txt != last:
            spans.append((a, txt))
            last = txt
    if not spans:
        return None
    return "지금은 한국 " + spans[0][1] + "".join(f", {kst_md(a)}부터 {t}" for a, t in spans[1:])


def trend_decisions(cfg: Optional[dict], now: int, since: Optional[int]) -> list:
    """The owners' decisions for the 추세판단 봇 as its config says them (docs/trend-bot-ko.md 2-3, the owners' words);
    TREND_DECISIONS_FIXED for a config that cannot be read."""
    if not isinstance(cfg, dict) or cfg.get("trend") is None:
        return list(TREND_DECISIONS_FIXED)
    from .trendjudge import TrendRules
    try:
        r = TrendRules.from_dict(cfg.get("trend"))
    except Exception:  # noqa: BLE001
        return list(TREND_DECISIONS_FIXED)
    review = kst_md(int(since) + TREND_REVIEW_DAYS * DAY) if since else None
    out = [f"규칙 고정: 새 봇 시작부터 2주는 규칙을 바꾸지 않고 기록을 모은 다음 {review + ' ' if review else ''}2주 검토에서 두 분이 정함"]
    # the 10-22 design, as far as this config has it
    members = [m for m in cfg.get("members") or [] if isinstance(m, dict)]
    if r.design:
        n = {tf: sum(1 for m in members if m.get("tf") == tf) for tf in ("30m", "1h", "4h")}
        out.append(f"새 설계({r.design}): 진입 매매법 {len(members)}개(30분 {n['30m']}개 · 1시간 {n['1h']}개 · 4시간 {n['4h']}개) · "
                   "성적과 2주 검토는 새 설계 시작부터 새로 셈")
        gone = trend_out_ko(members) if r.design == "2026-10-22" and members else None
        if gone:
            out.append(gone)                             # owners 10/26: the Fibonacci members and OTE taken out of this design
    if any(m.get("tf") == "4h" for m in members):
        out.append(TREND_DAILY_KO)
    if r.hold_entry:
        out.append(TREND_HOLD_KO)
    out.append(TREND_NOW_KO if not r.pullback_wait else
               "되돌림 진입: 검사를 통과한 신호는 진입 봉 하나 동안 되돌림을 기다렸다가 진입, 안 오면 버림")
    out.append("시간 정리 청산 없음(10/21 밤 '시간청산 빼줘'): 첫 잠금 전에는 손절(순ROE -50%)·추세 뒤집힘 감독 청산·빠른 청산만"
               if r.time_bars is None else f"설정에 시간 정리 청산이 있음: 진입 봉 {r.time_bars}개 안에 첫 잠금을 못 가면 청산")
    if r.member_losses is None and r.coin_pause_h is None and r.daily_loss is None:
        out.append("쉬기 없음: 손실 뒤 매매법·코인 쉬기 없음, 하루 손실 한도 없음(10/21 '쉬기는 빼주고', '10번은 없애고')")
    else:
        out.append("설정의 " + r.describe()[3])
    us, pre = int(cfg.get("us_open_pause_min") or 0), int(cfg.get("us_open_pre_min") or 0)
    if us or pre:
        from . import combo as C
        when = _windows_ko(now, us, pre)
        out.append(f"{C.us_open_ko(us, pre)} 진입 없음" + ("(10/21 밤 '나스닥 개장전 30분도 진입금지로 하자')" if pre else "")
                   + (f": {when}" if when else "") + " · 그 시간에도 추세 판단·" + ("되돌림 확인·" if r.pullback_wait else "")
                   + "감독 청산·손절·익절은 그대로")
    out.append("실거래 크기: 각 실거래 지갑의 약 40%를 증거금으로(실행기 수량 = 페이퍼 수량 × qty_scale, 또는 size_from \"equity\"면 "
               "진입할 때마다 자기 잔고 × margin_frac; sizing에 지금 숫자)")
    return out


def sizing_of(summary: Optional[dict], cfg: Optional[dict]) -> dict:
    """How big the live trades are against each real wallet now: margin share x paper wallet x qty_scale / real wallet (the
    owners' decision: about 40 % of each real wallet; the executor's quantity = the paper's x qty_scale)."""
    s = summary or {}
    margin = (cfg or {}).get("margin")
    margin = float(margin) if isinstance(margin, (int, float)) and not isinstance(margin, bool) else None
    bal = {a.get("id"): a.get("balance") for a in s.get("accts") or [] if isinstance(a, dict)}
    paper = bal.get("paper")
    rows = []
    for x in s.get("execs") or []:
        c = x.get("config") if isinstance(x.get("config"), dict) else {}
        q, real = c.get("qty_scale"), bal.get(x.get("id"))
        share = None
        mf = c.get("margin_frac")
        if c.get("size_from") == "equity" and isinstance(mf, (int, float)) and not isinstance(mf, bool):
            share = round(float(mf), 3)              # owners 10-25 night: each entry's margin is this share of its own wallet
        elif None not in (margin, q, paper, real) and real > 0:
            share = round(margin * float(paper) * float(q) / float(real), 3)
        rows.append({"executor": x.get("name_ko") or x.get("id"), "qty_scale": q, "real_wallet": real, "paper_wallet": paper,
                     "size_from": c.get("size_from") or "paper", "margin_share_now": share})
    return {"rule": "두 분 결정: 실거래 증거금은 각 실거래 지갑의 약 40% (qty_scale ≈ 실거래 지갑 ÷ 페이퍼 지갑일 때 그렇게 됨)",
            "paper_margin": margin, "execs": rows,
            "words": "margin_share_now = 페이퍼 증거금 비율 × 페이퍼 지갑 × qty_scale ÷ 실거래 지갑 (지금 지갑으로 계산한 대략값); "
                     "size_from \"equity\"인 실행기는 진입할 때마다 자기 잔고 × margin_frac (그 값 그대로)"}


def shadow_tests() -> dict:
    """The trend bot's shadow configs in this repository (deploy/combo.shadow-trend-*.json, read only): the ways an idea can be
    tested side by side without money. None there yet: an empty list, said so."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "deploy"
    out = []
    for path in sorted(root.glob(SHADOW_TREND_GLOB))[:SHADOW_KEEP]:
        try:
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(d, dict):
            out.append({"file": f"deploy/{path.name}", "name": d.get("name")})
    return {"how": "그림자 봇: 주문 없이 같은 시장에서 다른 규칙을 나란히 돌려 보는 비교용 봇(돈 안 듦, 텔레그램 없음). 켜고 끄는 것은 "
                   "두 분이 정함", "configs": out, "none": None if out else "아직 추세판단 봇용 그림자 설정이 없어요"}


# ---------------------------------------------------------------- the facts (the dashboard's own readers)
def sources(now: int, p: Optional[dict] = None) -> dict:
    """Everything the 실거래 screen shows, read once (read-only): the summary, 순위, 지도, 비용, 지금, 일정, 거래, the loss cards
    and the watcher's alarms."""
    from .dash.more import livebots as L
    p = p or L.paths()
    more = L.paths_more()
    out = {"now": now}
    for name, fn in (("summary", lambda: L.build(p, now)), ("rank", lambda: L.rank(p, now)), ("map", lambda: L.map_view(p, now)),
                     ("costs", lambda: L.costs(p, now)), ("whynow", lambda: L.whynow(p, now)), ("calendar", lambda: L.calendar(p, now)),
                     ("trades", lambda: L.trade_rows(p, now, more)), ("cards", lambda: L.read_cards(more["check_db"], now)),
                     ("safety", lambda: L.safety(p, now, more=more))):
        try:
            out[name] = fn()
        except Exception as exc:  # noqa: BLE001  one unreadable source is said, never fatal
            out[name] = {"state": "error", "reason": f"{type(exc).__name__}: {exc}"}
    try:
        out["bot"] = bot_world(p)
    except Exception as exc:  # noqa: BLE001  the rules then come from the owners' decisions (FIXED)
        out["bot"] = {"config": None, "infos": [], "ref_ko": "", "error": f"{type(exc).__name__}: {exc}"}
    if is_trend(out["bot"]):
        # the 추세판단 봇: the live site's own answers about it (관제, 검토, 재현 비교), read-only like the rest
        from .dash.more import livereplayref as X
        from .dash.more import livereview as LR
        from .dash.more import livetrend as LT
        for name, fn in (("trend", lambda: LT.build(p, now)), ("review", lambda: LR.build(p, now, more=more)),
                         ("replay", lambda: X.build(p, now))):
            try:
                out[name] = fn()
            except Exception as exc:  # noqa: BLE001  one unreadable source is said, never fatal
                out[name] = {"state": "error", "reason": f"{type(exc).__name__}: {exc}"}
    try:
        out["vwap"] = vwap_sources(p, now, more)
    except Exception as exc:  # noqa: BLE001  the VWAP bot's part is said, never fatal (the main bot's meetings as before)
        out["vwap"] = {"state": "error", "reason_ko": "VWAP 개선판 기록을 읽지 못했어요", "reason": f"{type(exc).__name__}: {exc}"}
    return out


def _cost_of(trades: list) -> dict:
    """What an executor's closed live trades paid (its own records, livebots.read_exec): n, the commission and funding sums,
    the fee rate measured on both sides of the notional (commission / (2 x entry notional), roughly), the mean commission as
    a share of the margin (in net ROE), and how many P&Ls are estimates (not from the exchange's fills)."""
    rows = [t for t in trades if t.get("commission") is not None and t.get("entry_price") and t.get("qty")]
    notional = sum(float(t["entry_price"]) * float(t["qty"]) for t in rows)
    comm = sum(float(t["commission"]) for t in rows)
    on_margin = [float(t["commission"]) / float(t["margin"]) for t in rows if t.get("margin")]
    return {"n": len(trades), "measured_n": len(rows), "commission": _r(comm), "funding": _r(sum(float(t.get("funding") or 0) for t in trades)),
            "fee_rate_side": _r(comm / (2 * notional), 6) if notional > 0 else None,
            "fee_roe_mean": _r(sum(on_margin) / len(on_margin)) if on_margin else None,
            "estimated": sum(1 for t in trades if t.get("est"))}


def vwap_sources(p: dict, now: int, more: Optional[dict] = None) -> dict:
    """The 'VWAP 개선판' (docs/vwap-bot-ko.md) as the live site's VWAP screens read it (dash/more/livevwap.py: 관제, 성적 with
    운이냐 고장이냐, 막은 신호), read-only, with the executors that follow or followed it: their segments (a trade entered
    while one followed this bot is this bot's, never the main bot's) and what their live trades on it paid. {"state":
    "off"} without the bot (the one-paper world: every meeting as before)."""
    from . import livepapers as LP
    from .dash.more import livebots as L
    from .dash.more import livevwap as VW
    more = more or L.paths_more()
    loc = VW.locate(p, now, more)
    if loc["state"] == "off":
        return {"state": "off"}
    bot = loc.get("bot") or {}
    path = bot.get("path")
    out = {"state": loc["state"], "reason_ko": loc.get("reason_ko"), "path": path, "bot_id": bot.get("id"), "followers": []}
    for x in loc["execs"]:
        stretches = VW.segs_of(x, path) if path else []
        now_on = bool(path) and LP.same(x["paper_path"], path)
        if not stretches and not now_on:
            continue
        cfg = x["config"] if isinstance(x.get("config"), dict) else {}
        era = VW.era_trades(x, path) if x["record"].get("state") == "ok" else []
        out["followers"].append({"id": x["id"], "name_ko": x["name_ko"], "now": now_on, "segs": x["segs"],
                                 "since_ms": stretches[-1][0] if stretches else None, "exchange": cfg.get("exchange"),
                                 "size_from": cfg.get("size_from"), "margin_frac": cfg.get("margin_frac"), "budget_usd": cfg.get("budget_usd"),
                                 "qty_scale": cfg.get("qty_scale"), "light": [cfg.get("signal_light_n"), cfg.get("signal_light_min_win")],
                                 "record_state": x["record"].get("state"), "costs": _cost_of(era)})
    if loc["state"] != "ok":
        return out
    for name, fn in (("control", VW.control), ("perf", VW.perf), ("blocked", VW.blocked)):
        try:
            out[name] = fn(p, now, more)
        except Exception as exc:  # noqa: BLE001  one unreadable answer is said, never fatal
            out[name] = {"state": "error", "reason_ko": "읽지 못했어요", "reason": f"{type(exc).__name__}: {exc}"}
    return out


def vwap_apart(src: dict) -> Optional[dict]:
    """The VWAP bot as another bot than the main one (its own paper database: the second paper bot): its source, else None
    (no VWAP bot, or it is the main paper bot itself: nothing is set apart)."""
    vs = src.get("vwap")
    if not isinstance(vs, dict) or vs.get("state") in (None, "off") or not vs.get("path") or vs.get("bot_id") == "paper":
        return None
    return vs


def on_vwap(vs: Optional[dict], ex: str, t: Optional[int]) -> bool:
    """Did executor ``ex`` follow the VWAP bot when it entered at ``t`` (its own start records)?"""
    if vs is None:
        return False
    from . import livepapers as LP
    f = next((f for f in vs.get("followers") or [] if f.get("id") == ex), None)
    return f is not None and t is not None and LP.followed_at(f.get("segs") or [], vs["path"], t)


def _acct_line(a: dict) -> dict:
    st = a.get("stats") or {}
    return {"id": a.get("id"), "name": a.get("label_ko") or a.get("name_ko"),
            "kind": "페이퍼(연습)" if a.get("kind") == "paper" else "실거래(진짜 돈)",
            "state": a.get("state"), "balance": a.get("balance"), "start": a.get("initial"), "halted": a.get("halted"),
            "halt_reason": a.get("halt_reason") or None, "losing_run": a.get("consecutive_losses"),
            "trades": st.get("trades"), "wins": st.get("wins"), "pnl": st.get("pnl"), "today": a.get("today"),
            "reason": a.get("reason_ko") if a.get("state") != "ok" else None}


def _trade_line(r: dict) -> dict:
    live = {}
    for ex, c in (r.get("live") or {}).items():
        if not isinstance(c, dict):
            continue
        live[ex] = ({"followed": True, "pnl": c.get("pnl"), "slip": c.get("slip")} if c.get("state") == "matched"
                    else {"followed": False, "why": c.get("why_ko") or c.get("state")})
    card = r.get("card") or {}
    return {"time_kst": kst_text(r.get("entry_time")), "coin": r.get("symbol"), "side": "롱" if (r.get("side") or 0) > 0 else "숏",
            "strategy": r.get("strategy_id"), "tf": r.get("timeframe"), "roe": r.get("roe"), "pnl": r.get("pnl"),
            "exit": r.get("reason_ko"), "minutes": round((r["exit_time"] - r["entry_time"]) / MIN) if r.get("exit_time") and r.get("entry_time") else None,
            "loss_card": card.get("label") if card else None, "live": live}


def facts(src: dict, kind: str, window: Optional[tuple] = None, focus: Optional[dict] = None) -> dict:
    """The packet every member of one meeting reads: numbers only, with their meaning in words. The 추세판단 봇
    (``is_trend``): its own packet (facts_trend)."""
    if is_trend(src.get("bot")):
        return facts_trend(src, kind, window, focus)
    now = src["now"]
    summ = src.get("summary") or {}
    accts = [_acct_line(a) for a in summ.get("accts") or []]
    mp = src.get("map") or {}
    band = (mp.get("band") or {})
    rank = src.get("rank") or {}
    strategies = []
    for r in rank.get("rows") or []:
        pp, sg, bt, sc = r.get("paper") or {}, (r.get("sig") or {}).get("week") or {}, r.get("bt") or {}, r.get("status") or {}
        if not (pp.get("n") or sg.get("signals") or r.get("open")):
            continue
        strategies.append({"strategy": r.get("strategy"), "type": bt.get("type_ko"), "in_config": r.get("in_config"),
                           "paper_n": pp.get("n"), "paper_wins": pp.get("wins"), "paper_pnl": pp.get("pnl"), "status": sc.get("status"),
                           "fit_win": bt.get("win"), "honest_win": bt.get("honest_win"), "week_signals": sg.get("signals"),
                           "week_entered": sg.get("entered"), "holding_now": bool(r.get("open"))})
    cuts = {}
    for cut, rows in (mp.get("cuts") or {}).items():
        cuts[cut] = [{"label": x.get("label"), "n": x.get("n"), "win": x.get("win"), "bt_win": x.get("bt_win"), "status": x.get("status")}
                     for x in rows if x.get("n")]
    costs = {}
    for ex, c in ((src.get("costs") or {}).get("accts") or {}).items():
        costs[ex] = ({k: c.get(k) for k in ("n", "matched", "slip_avg", "fees", "funding", "diff_total", "roe_gap_avg", "est_n")}
                     | {"missed": [{"why": m.get("ko"), "n": m.get("n")} for m in c.get("missed") or []]}) if c.get("state") == "ok" \
            else {"state": c.get("state"), "reason": c.get("reason_ko")}
    wn = src.get("whynow") or {}
    cal = src.get("calendar") or {}
    world = src.get("bot") or {}
    ref_ko = world.get("ref_ko") or ""
    words = ("fit = 5년에 맞춘 숫자(낙관), honest = 2020-24에만 맞춘 쌍둥이가 처음 본 2025-26에서 낸 숫자(현실), "
             "break_even = 본전 승률. p_under_honest = 현실 승률대로라면 지금보다 적게 이길 확률(작을수록 현실보다 못함)")
    if ref_ko:
        words = (f"{ref_ko}. 이 봇은 5년 숫자(fit·honest)가 없습니다: 지난 봇 숫자를 쓰지 말고, 페이퍼 승률을 본전 승률"
                 "(bot.break_even)과 시작 근거(bot.start_basis)에 비교합니다")
    out = {"meeting": KIND_KO.get(kind, kind), "now_kst": kst_text(now),
           "fixed_rules": fixed_rules(world.get("config"), world.get("infos"), world.get("second")), "bot": bot_facts(world),
           "accounts": accts,
           "expect": {"fit_win": band.get("fit"), "honest_win": band.get("honest"), "break_even": band.get("break_even"),
                      "so_far": {k: {"n": v.get("n"), "wins": v.get("wins"), "rate": v.get("rate"), "p_under_honest": v.get("p_honest")}
                                 for k, v in (band.get("accounts") or {}).items()},
                      "words": words},
           "strategies": strategies[:30], "cuts": cuts, "costs": costs,
           "now": {"head": wn.get("head_ko"), "blocked": [i.get("ko") for i in wn.get("items") or [] if i.get("ok") is False]},
           "next_releases": [{"when_kst": kst_text(x.get("ts")), "what": x.get("kind_ko")} for x in cal.get("items") or []
                             if x.get("when") in ("now", "soon", "later")][:6],
           "checkpoint_rule": CHECK_RULE_NONE if ref_ko else CHECK_RULE_OLD}
    rows = ((src.get("trades") or {}).get("accts") or {}).get("paper") or {}
    prow = rows.get("rows") or [] if isinstance(rows, dict) else []
    if window:
        a, b = window
        out["window_kst"] = [kst_text(a), kst_text(b)]
        out["trades"] = [_trade_line(r) for r in prow if r.get("exit_time") is not None and a <= r["exit_time"] < b][:60]
        rows2 = ((src.get("trades") or {}).get("accts") or {}).get("paper2")
        if isinstance(rows2, dict) and rows2.get("rows") is not None:    # the second paper bot's (its own executors' cells)
            out["trades_paper2"] = {"label": rows2.get("label_ko"), "rows": [_trade_line(r) for r in rows2["rows"]
                                    if r.get("exit_time") is not None and a <= r["exit_time"] < b][:60]}
        out["loss_cards"] = _cards_in(src, a, b)
        out["alarms"] = _alarms_in(src, a, b)
    if focus:
        out["focus"] = focus
    return out


def _cards_in(src: dict, a: int, b: int) -> list:
    """The watcher's loss cards of the trades closed in [a, b) (livecheck.db, read by the 거래 tab's reader)."""
    cards = (src.get("cards") or {}).get("cards") or []
    return [{"label": c.get("label"), "strategy": c.get("strategy"), "tf": c.get("tf"), "coin": c.get("symbol"),
             "roe": c.get("roe"), "regime": c.get("reg5_ko"), "noise": (c.get("noise") or {}).get("state"),
             "text": _clip(c.get("text") or "", 300)}
            for c in cards if c.get("exit_time") is not None and a <= int(c["exit_time"]) < b][:12]


def _alarms_in(src: dict, a: int, b: int) -> list:
    alarms = []
    for x in (((src.get("safety") or {}).get("checks") or {}).get("watch") or {}).get("items") or []:
        if x.get("ts") is not None and a <= x["ts"] < b:
            alarms.append({"when_kst": kst_text(x["ts"]), "level": x.get("level_ko"), "what": x.get("title")})
    return alarms[:20]


def _releases(src: dict) -> list:
    cal = src.get("calendar") or {}
    return [{"when_kst": kst_text(x.get("ts")), "what": x.get("kind_ko")} for x in cal.get("items") or []
            if x.get("when") in ("now", "soon", "later")][:6]


def _now_line(src: dict) -> dict:
    wn = src.get("whynow") or {}
    return {"head": wn.get("head_ko"), "blocked": [i.get("ko") for i in wn.get("items") or [] if i.get("ok") is False]}


# ---------------------------------------------------------------- 추세판단 봇: the packet (the live site's own answers)
def meeting_label(kind: str, focus: Optional[dict] = None, trend: bool = False) -> str:
    """The meeting's name: KIND_KO; a checkpoint of the 추세판단 봇 is "40번째 거래 점검" (no 88 % rule)."""
    if trend and kind == "checkpoint":
        k = (focus or {}).get("milestone")
        return f"{int(k)}번째 {TREND_CHECK_KO}" if isinstance(k, int) and not isinstance(k, bool) and k > 0 else TREND_CHECK_KO
    return KIND_KO.get(kind, kind)


def kind_ko(kind: str, key: Optional[str] = None) -> str:
    """A stored meeting's kind in words (the 분석팀 tab): the trend bot's checkpoints (key checkpoint:trend-...) say 거래 점검;
    the VWAP bot's meetings name it ("VWAP 손실 회의", "VWAP 거래 점검", "VWAP 실거래 점검", "VWAP 주간 보고")."""
    k = str(key or "")
    if kind == "checkpoint" and k.startswith("checkpoint:trend"):
        return TREND_CHECK_KO
    if k.startswith("checkpoint:vwap-live"):
        return "VWAP 실거래 점검"
    if k.startswith(("loss:vwap", "checkpoint:vwap", "weekly:vwap:")) or (kind == "weekly" and k.endswith(":vwap")):
        return "VWAP " + (TREND_CHECK_KO if kind == "checkpoint" else KIND_KO.get(kind, kind))
    return KIND_KO.get(kind, kind)


def roles(trend: bool = False) -> dict:
    """The members as the running bot needs them (ROLES_TREND for the 추세판단 봇)."""
    return ROLES_TREND if trend else ROLES


def _ok(x: Any) -> bool:
    return isinstance(x, dict) and x.get("state") == "ok"


def _not_ok(x: Any) -> dict:
    """An answer that could not be used, said (never a zero): {"state", "reason"}."""
    x = x if isinstance(x, dict) else {}
    return {"state": x.get("state") or "missing", "reason": x.get("reason_ko") or x.get("reason") or "자료 없음"}


def _r(x: Any, nd: int = 4) -> Optional[float]:
    return round(float(x), nd) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _coin(sym: Any) -> Optional[str]:
    return str(sym).replace("USDT", "") if sym else None


def _side(side: Any) -> Optional[str]:
    try:
        return None if not side else ("롱" if int(side) > 0 else "숏")
    except (TypeError, ValueError):
        return None


def _acct_now(a: dict) -> dict:
    """An account now (its wallet and state); its record is ``record`` (since the bot's start only)."""
    return {"id": a.get("id"), "name": a.get("label_ko") or a.get("name_ko"),
            "kind": "페이퍼(연습)" if a.get("kind") == "paper" else "실거래(진짜 돈)", "state": a.get("state"),
            "wallet": a.get("balance"), "halted": a.get("halted"), "halt_reason": a.get("halt_reason") or None,
            "reason": a.get("reason_ko") if a.get("state") != "ok" else None}


def _trend_record(rv: dict, lt: dict) -> dict:
    """Since the bot's start: the paper account, its coin-flip twin and the luck between them, each executor (검토), the
    exits by reason (관제)."""
    if not _ok(rv):
        return _not_ok(rv)
    rec = rv.get("record") or {}

    def pick(r):
        if not isinstance(r, dict):
            return None
        return {k: (r.get(k) if k in ("n", "wins", "losses") else _r(r.get(k)))
                for k in ("n", "wins", "losses", "win_rate", "pnl", "roe_sum", "roe_mean", "best", "worst")}
    luck = rec.get("luck") or {}
    out = {"paper": pick(rec.get("real")), "flip": pick(rec.get("flip")) if rec.get("flip_on") else None,
           "luck": {"ko": luck.get("ko"), "where": luck.get("where"), "flip_band": [_r(x) for x in luck.get("band_rate") or []] or None},
           "execs": [{"name": x.get("name_ko"), "state": x.get("state"), "real_money": x.get("real"), "n": x.get("n"), "wins": x.get("wins"),
                      "pnl": _r(x.get("pnl")), "open_now": x.get("open"), "halted": x.get("halted"), "wallet": _r(x.get("balance")),
                      "reason": x.get("reason_ko")} for x in rv.get("execs") or []],
           "small_n": SMALL_N}
    if _ok(lt):
        out["by_exit"] = [{"exit": b.get("ko"), "n": b.get("n"), "wins": b.get("wins"), "pnl": _r(b.get("pnl"))}
                          for b in (lt.get("record") or {}).get("by_exit") or []]
    return out


ENTRY_KO = {"30m": "30분", "1h": "1시간", "4h": "4시간"}


def _trend_now(lt: dict) -> dict:
    """Each coin's last closed 1h, 4h and daily judgment (the bot's own, state ``trend``; 1d since 10-22, the 4h entries
    read it) and the directions it takes now (보류 허용: a 보류 takes both sides)."""
    if not _ok(lt):
        return _not_ok(lt)
    from .dash.more import livetrend as LT
    coins = lt.get("coins") or {}
    cells = {}
    for sym, row in coins.items():
        cell = {}
        for tf in LT.JUDGED:
            j = row.get(tf) if isinstance(row, dict) else None
            if j is None and tf == "1d":
                continue                                  # a bot before 10-22 wrote no daily judgment
            cell[tf] = (j.get("text") or (f"못 읽음: {_clip(j.get('error'), 120)}" if j.get("error") else None)) if isinstance(j, dict) else None
        cells[_coin(sym)] = cell
    hold = bool(lt.get("hold_entry"))
    entries = {m.get("tf") for m in lt.get("members") or [] if m.get("tf")} or None
    taking = [f"{_coin(x['symbol'])} {ENTRY_KO.get(x['entry'], x['entry'])} 진입 "
              + (f"{_side(x['side'])}만" if x["side"] else "롱·숏(보류 허용)") for x in LT.taking_now({"coins": coins}, entries, hold)]
    bot = lt.get("bot") or {}
    return {"as_of_kst": kst_text(lt.get("ts")), "coins": cells,
            "taking_now": taking or [f"지금 진입을 받는 추세가 없음(모두 {'' if hold else '보류·'}힘 약함·끝물)"],
            "paper_bot_stale": bot.get("stale"),
            "words": "상승·하락 = 판단 4개 중 3개 이상 같은 쪽(유지 확인됨), 보류 = "
                     + ("반대 방향만 아니면 진입(보류 허용)" if hold else "진입 안 함")
                     + ". ADX 20 미만 = 힘 약함, 40 넘고 꺾이면 끝물(진입 안 함). taking_now = 지금 진입을 받는 코인·방향(30분 진입은 "
                       "1시간 판단, 1시간 진입은 4시간 판단, 4시간 진입은 일봉 판단)"}


def _trend_position(lt: dict) -> Optional[dict]:
    p = lt.get("position") if _ok(lt) else None
    if not isinstance(p, dict):
        return None
    j = p.get("judge") if isinstance(p.get("judge"), dict) else {}
    return {"coin": _coin(p.get("symbol")), "side": _side(p.get("side")), "member": f"{p.get('strategy')}@{p.get('tf')}",
            "role": p.get("role"), "entry_kst": kst_text(p.get("entry_time")), "leverage": p.get("leverage"),
            "locked": p.get("locked"), "lock_roe": _r(p.get("lock_roe")), "entry_judge": p.get("entry_judge"),
            "entry_on_hold": bool(p.get("entry_held")),
            "higher_bar_now": j.get("text") or j.get("error"), "against_now": p.get("judge_against"),
            "supervised": p.get("supervised"), "old_bot": bool(p.get("inherited")), "old_bot_ko": p.get("inherited_ko"),
            "executors": [{"name": f.get("name_ko"), "state": f.get("state"), "what": f.get("ko")} for f in p.get("follow") or []] or None}


def _trend_funnel(lt: dict, rv: dict, window: Optional[tuple]) -> dict:
    """Where the signals went: today (관제), since the start and in the meeting's window (검토's days)."""
    def blocked(f):
        return [{"why": b.get("ko"), "n": b.get("n")} for b in f.get("blocked") or []]
    waits = not _ok(lt) or lt.get("pullback_wait") is not False
    out = {"words": "signals = 진입 매매법 신호, passed = 추세 판단·진입 자리 검사를 통과한 신호("
                    + ("되돌림을 기다린 신호" if waits else "그 분에 바로 들어간 신호: 이 봇은 되돌림을 기다리지 않음") + "), touched = 되돌림 "
                    "가격에 닿음(되돌림을 기다리는 설정만), entered = 진입, blocked = 나머지가 걸린 곳(한 번에 하나 = 이미 포지션이 있어 못 탐)"}
    f = lt.get("funnel") if _ok(lt) else None
    if isinstance(f, dict):
        out["today"] = {**{k: f.get(k) for k in ("signals", "passed", "touched", "entered")}, "from_kst": kst_text(f.get("from")),
                        "blocked": blocked(f)}
    if not _ok(rv):
        out["since_start"] = _not_ok(rv)
        return out
    f = rv.get("funnel")
    if isinstance(f, dict):
        out["since_start"] = {**{k: f.get(k) for k in ("signals", "passed", "touched", "entered")}, "blocked": blocked(f)}
    if window and rv.get("days"):
        a, b = window
        days = [d for d in rv["days"] if a <= d.get("d0", 0) + DAY and d.get("d0", 0) < b]
        out["window"] = {k: sum(int(d.get(k) or 0) for d in days) for k in ("signals", "passed", "touched", "entered")}
    return out


def _trend_signals(lt: dict) -> dict:
    """The last 24 h of signals (from the start when younger) by what became of them, with the bot's own reasons."""
    if not _ok(lt):
        return _not_ok(lt)
    sg = lt.get("signals") or {}
    rows = sg.get("rows") or []
    names = {r.get("cat"): r.get("cat_ko") for r in rows}
    counts = [{"what": names.get(k) or k, "n": n} for k, n in sorted((sg.get("counts") or {}).items(), key=lambda kv: -kv[1])]
    recent = [{"time_kst": kst_text(r.get("bar_close")), "coin": _coin(r.get("symbol")), "side": _side(r.get("side")),
               "member": r.get("member"), "what": r.get("cat_ko"), "why": _clip(r.get("why"), 160) if r.get("why") else None}
              for r in rows[:SIG_ROWS]]
    return {"from_kst": kst_text(sg.get("from")), "counts": counts, "recent": recent}


def _trend_members(lt: dict) -> list:
    if not _ok(lt):
        return []
    from .dash.more import livebots as L
    return [{"member": m.get("label"), "role": m.get("role"), "side_only": {"short": "숏만", "long": "롱만"}.get(m.get("side_only")),
             "signals_today": m.get("today"), "trades": m.get("trades"), "wins": m.get("wins"), "roe_sum": _r(m.get("roe_sum")),
             "last_exit": L.EXIT_KO.get((m.get("last") or {}).get("exit_reason"), (m.get("last") or {}).get("exit_reason"))}
            for m in lt.get("members") or []]


def _trend_supervisor(lt: dict) -> dict:
    if not _ok(lt):
        return _not_ok(lt)
    return {"exits_7d": [{"time_kst": kst_text(x.get("exit_time")), "coin": _coin(x.get("symbol")), "side": _side(x.get("side")),
                          "member": f"{x.get('strategy')}@{x.get('tf')}", "exit": x.get("reason_ko"), "why": x.get("why"),
                          "roe": _r(x.get("roe")), "old_bot": bool(x.get("inherited"))} for x in (lt.get("sup") or [])[:10]],
            "switch_closed_24h": [{"coin": _coin(x.get("symbol")), "side": _side(x.get("side")), "member": f"{x.get('strategy')}@{x.get('tf')}",
                                   "entered_kst": kst_text(x.get("entry_time")), "closed_kst": kst_text(x.get("exit_time")),
                                   "exit": x.get("reason_ko"), "roe": _r(x.get("roe"))} for x in (lt.get("prev") or {}).get("closed") or []],
            "words": "감독 청산 = 첫 잠금(+10%) 전에 상위 봉 추세 판단이 반대로 바뀌어 닫은 것. 전환 전 포지션 정리 = 예전 봇이 연 "
                     "포지션을 새 봇이 시작하며 닫은 것(예전 봇 거래라 이 봇 성적이 아님)"}


def _trend_costs(rp: dict) -> dict:
    """비용 쪼개기 (재현 비교): per trade, before costs -> slippage -> fees -> funding -> net; the replay's (가상), the paper's,
    each executor's from its exchange fills."""
    if not _ok(rp):
        return _not_ok(rp)
    c = rp.get("costs") or {}

    def pick(x):
        if not isinstance(x, dict):
            return None
        return {"n": x.get("n"), "of": x.get("of"), **{k: _r(x.get(k)) for k in ("before", "slip", "fee", "funding", "net", "cost")}}
    return {"words": "거래당 평균 순ROE(비율, 0.01 = 1%p): before(비용 전) → slip(미끄러짐) → fee(수수료) → funding(펀딩) → net(순). "
                     "cost = 비용 합. n = 비용을 잰 거래, of = 닫힌 거래",
            "replay": {"label": "가상(7/1~10/20 재현)", **(pick(c.get("replay")) or {})}, "replay_ko": c.get("ko"),
            "paper": pick(c.get("paper")), "paper_ko": c.get("paper_ko"), "paper_note": c.get("paper_slip_ko"),
            "execs": [{"name": x.get("name_ko"), "costs": pick(x.get("costs")), "ko": x.get("costs_ko")}
                      for x in (rp.get("results") or {}).get("execs") or []],
            "exec_note": c.get("exec_before_ko")}


def _trend_replay(rp: dict) -> dict:
    """What the 7/1~10/20 replay leads to expect (가상), against what the live bot did since its start (재현 비교)."""
    if not _ok(rp):
        return _not_ok(rp)
    ref, e, res, fn = (rp.get(k) or {} for k in ("ref", "entries", "results", "funnel"))
    live, band = e.get("live") or {}, e.get("band") or {}

    def rec(r, verdict=True):
        out = {"n": r.get("n"), "win_rate": _r(r.get("win_rate")), "roe_mean": _r(r.get("roe_mean")),
               "exits": [{"exit": x.get("ko"), "n": x.get("n"), "roe_mean": _r(x.get("roe_mean"))} for x in r.get("exits") or []]}
        if verdict:
            out["verdict"] = (r.get("verdict") or {}).get("ko")
        return out
    stages = lambda xs: [{"stage": x.get("ko"), "n": x.get("n"), "share": _r(x.get("share"), 3)} for x in xs or []]  # noqa: E731
    return {"label": "가상: 7/1~10/20 실제 1분봉으로 이 봇 규칙을 다시 돌린 결과(실제 거래 아님)", "what": ref.get("what"),
            "honest": ref.get("honest_ko"),
            "entries": {"ko": e.get("ko"), "replay_per_weekday": (e.get("replay") or {}).get("per_weekday"),
                        "live_per_weekday": _r(live.get("per_weekday"), 3), "live_entries": live.get("all"),
                        "band": {k: band.get(k) for k in ("lo", "hi", "where")} if band else None, "weekend_ko": e.get("weekend_ko")},
            "results": {"replay": rec(res.get("replay") or {}, False), "paper": rec(res.get("paper") or {}),
                        "execs": [{"name": x.get("name_ko"), **(rec(x.get("record")) if isinstance(x.get("record"), dict) else
                                                               {"state": x.get("state"), "reason": x.get("reason_ko")})}
                                  for x in res.get("execs") or []],
                        "band_how": res.get("band_how_ko")},
            "funnel": {"replay": stages(fn.get("replay")), "live": stages(fn.get("live")),
                       "replay_blocked": [{"why": b.get("ko"), "n": b.get("n")} for b in fn.get("replay_blocked") or []]}}


def _trend_whatif(rv: dict) -> dict:
    """새 규칙이 도왔나? (검토, 가상): each new rule's virtual result against the bot's own trades held the same way."""
    if not _ok(rv):
        return _not_ok(rv)
    wi = rv.get("whatif") or {}
    items = []
    for it in wi.get("items") or []:
        x = {"rule": it.get("ko"), "what": it.get("rule_ko"), "how": it.get("how_ko"), "n": it.get("n"),
             "verdict": (it.get("verdict") or {}).get("ko")}
        for k, name in (("virt", "blocked_virtual"), ("base", "bot_held_virtual")):
            v = it.get(k)
            if isinstance(v, dict) and it.get("n"):
                x[name] = {"decided": v.get("decided"), "won": v.get("won"), "win_rate": _r(v.get("win_rate"))}
        items.append(x)
    return {"label": "가상: 규칙봇 1분봉으로 다시 계산한 결과(실제 체결 아님)", "note": wi.get("note_ko"), "items": items,
            "pending": (wi.get("work") or {}).get("pending")}


def _trend_cuts(mp: Any) -> dict:
    """지도 for the trend bot (livebots.trend_map): the paper's trades since the start by the judgment it entered on, coin,
    KST 4-hour block, side and entry bar."""
    out = {}
    for cut, rows in ((mp or {}).get("cuts") or {}).items() if isinstance(mp, dict) else ():
        out[cut] = [{"label": x.get("label"), "n": x.get("n"), "win": _r(x.get("win")), "avg_roe": _r(x.get("avg_roe"))}
                    for x in rows if x.get("n")]
    return out


def _trend_trades(src: dict, window: tuple, since: Optional[int], lt: dict) -> tuple:
    """(the bot's trades closed in the window, the trades of the bot before it closed in the window): a trade entered before
    ``since`` is never the bot's (the switch close, 전환 전 포지션 정리). The bot's carry the judgment it entered on and why
    the supervisor closed it (관제's trades)."""
    a, b = window
    rows = ((src.get("trades") or {}).get("accts") or {}).get("paper") or {}
    closed = [r for r in (rows.get("rows") or [] if isinstance(rows, dict) else []) if r.get("exit_time") is not None and a <= r["exit_time"] < b]
    if since is None:
        return [_trade_line(r) for r in closed][:TRADE_KEEP], []
    seen = {(t.get("symbol"), t.get("entry_time")): t for t in (lt.get("trades") or [] if _ok(lt) else [])}
    mine = []
    for r in closed:
        if (r.get("entry_time") or 0) < int(since):
            continue
        line = _trade_line(r)
        t = seen.get((r.get("symbol"), r.get("entry_time")))
        if t:
            line.update(entry_judge=t.get("entry_judge"), exit_why=t.get("why"))
            if t.get("entry_held"):
                line["entry_on_hold"] = True               # entered on a 보류 judgment (10-22 보류 허용)
        mine.append(line)
    old = [{**_trade_line(r), "bot": f"예전 봇({TREND_PREV_BOT}): 이 봇 성적 아님"} for r in closed if (r.get("entry_time") or 0) < int(since)]
    return mine[:TRADE_KEEP], old[:12]


def facts_trend(src: dict, kind: str, window: Optional[tuple] = None, focus: Optional[dict] = None) -> dict:
    """The packet of the 추세판단 봇 (module docstring): numbers only, with their meaning in words; the bot's own record since
    its start, the replay and the what-ifs labelled 가상."""
    now = src["now"]
    world = src.get("bot") or {}
    cfg = world.get("config") if isinstance(world.get("config"), dict) else None
    since = (world.get("trend") or {}).get("since")
    summ = src.get("summary") or {}
    lt, rv, rp = (src.get(k) if isinstance(src.get(k), dict) else {"state": "missing", "reason_ko": "읽지 않았어요"}
                  for k in ("trend", "review", "replay"))
    pause = lt.get("pause") if _ok(lt) else None
    nxt = ((lt.get("next") or {}).get("pause") if _ok(lt) else None) or {}
    out = {"meeting": meeting_label(kind, focus, True), "now_kst": kst_text(now), "bot": trend_bot_facts(world, now),
           "fixed_rules": fixed_rules(cfg, world.get("infos"), world.get("second"), trend_bot=True),
           "owners_decisions": trend_decisions(cfg, now, since), "sizing": sizing_of(summ, cfg),
           "accounts": [_acct_now(a) for a in summ.get("accts") or []], "record": _trend_record(rv, lt),
           "trend_now": _trend_now(lt),
           "waits": [{"coin": _coin(w.get("symbol")), "side": _side(w.get("side")), "member": w.get("member"), "level": w.get("level"),
                      "until_kst": kst_text(w.get("until")), "judge": w.get("judge")} for w in (lt.get("waits") or [] if _ok(lt) else [])],
           "position": _trend_position(lt), "funnel": _trend_funnel(lt, rv, window), "signals_24h": _trend_signals(lt),
           "members": _trend_members(lt), "supervisor": _trend_supervisor(lt), "costs": _trend_costs(rp),
           "replay": _trend_replay(rp), "whatif": _trend_whatif(rv), "cuts": _trend_cuts(src.get("map")),
           "now": {**_now_line(src), "pause": pause.get("ko") if isinstance(pause, dict) else None},
           "next_pause": {"what": nxt.get("ko"), "from_kst": kst_text(nxt.get("from")), "until_kst": kst_text(nxt.get("until"))} if nxt else None,
           "next_releases": _releases(src), "checkpoint_rule": CHECK_RULE_TREND, "tests_available": shadow_tests(),
           "words": TREND_WORDS}
    if window:
        a, b = window
        out["window_kst"] = [kst_text(a), kst_text(b)]
        out["trades"], out["old_bot_trades"] = _trend_trades(src, window, since, lt)
        out["loss_cards"] = _cards_in(src, a, b)
        out["alarms"] = _alarms_in(src, a, b)
    if focus:
        out["focus"] = focus
    return out


# ---------------------------------------------------------------- VWAP 개선판: its packet (the live site's VWAP screens)
def vwap_label(vs: Optional[dict], ex_ko: Optional[str] = None) -> str:
    """"VWAP 개선판 · 딥코인" (the executor(s) following it now, or ``ex_ko``), "VWAP 개선판 (페이퍼만)" with none."""
    names = [ex_ko] if ex_ko else [f["name_ko"] for f in (vs or {}).get("followers") or [] if f.get("now")]
    return f"{VWAP_NAME} · {'·'.join(names)}" if names else f"{VWAP_NAME} (페이퍼만)"


def vwap_meeting_label(kind: str, focus: Optional[dict], vs: Optional[dict]) -> str:
    """The meeting's name, the bot named first: "VWAP 개선판 · 딥코인 손실 회의", "… 50번째 거래 점검(페이퍼)", "VWAP 개선판 ·
    딥코인 실거래 50번 점검", "… 주간 보고"."""
    f = focus or {}
    k = f.get("milestone")
    k = int(k) if isinstance(k, int) and not isinstance(k, bool) and k > 0 else None
    if kind == "loss":
        return f"{vwap_label(vs, f.get('executor_ko'))} 손실 회의"
    if kind == "checkpoint" and f.get("what") == "live":
        return f"{vwap_label(vs, f.get('executor_ko'))} 실거래 {k}번 점검" if k else f"{vwap_label(vs, f.get('executor_ko'))} 실거래 점검"
    if kind == "checkpoint":
        return f"{vwap_label(vs)} {k}번째 거래 점검(페이퍼)" if k else f"{vwap_label(vs)} 거래 점검"
    return f"{vwap_label(vs)} {KIND_KO.get(kind, kind)}"


def _vw_rec(a: Any) -> Any:
    if not _ok(a):
        return _not_ok(a)
    return {**{k: a.get(k) for k in ("n", "wins", "losses")},
            **{k: _r(a.get(k)) for k in ("win_rate", "avg_win", "avg_loss", "breakeven", "pf", "roe_sum", "pnl", "max_dd", "wallet",
                                         "initial", "change")}, "small": a.get("small")}


def _vw_record(prf: dict) -> dict:
    """Since the bot's start: the paper, its coin-flip twin, 실력 vs 운, each follower's live trades on this bot (성적's
    checklist: n of 50, its record, its break-even win rate, the checks, how close to the paper)."""
    if not _ok(prf):
        return _not_ok(prf)
    live = []
    for c in prf.get("checklist") or []:
        be, stp, pv = c.get("breakeven") or {}, c.get("stop") or {}, c.get("pairs") or {}
        live.append({"name": c.get("name_ko"), "since_kst": kst_text(c.get("since_ms")), "n": c.get("n"), "goal": c.get("goal"),
                     "record": {**{k: (c.get("record") or {}).get(k) for k in ("n", "wins", "losses")},
                                **{k: _r((c.get("record") or {}).get(k)) for k in ("win_rate", "avg_win", "avg_loss", "pf", "pnl", "roe_sum")}},
                     "breakeven": _r(be.get("value")), "breakeven_from": be.get("ko"), "stop_line": {"state": stp.get("state"), "ko": stp.get("value_ko")},
                     "checks": [{"what": r.get("ko"), "state": r.get("state"), "value": r.get("value_ko")} for r in c.get("rows") or []],
                     "vs_paper": {"pairs": pv.get("n"), "same_result": pv.get("same"), "roe_diff_mean": _r(pv.get("diff_mean")),
                                  "entry_slip_mean": _r(pv.get("slip_mean"), 6)},
                     "record_state": c.get("record_state"), "reason": c.get("reason_ko")})
    return {"paper": _vw_rec(prf.get("paper")), "flip": _vw_rec(prf.get("flip")), "skill": (prf.get("skill") or {}).get("ko"),
            "live": live, "small_n": SMALL_N}


def _vw_band_one(b: dict) -> dict:
    if not isinstance(b, dict) or b.get("state") != "ok":
        return {"state": (b or {}).get("state") or "missing", "words": (b or {}).get("ko") or (b or {}).get("reason_ko")}
    w, s, d = b.get("win") or {}, b.get("streak") or {}, b.get("dd") or {}
    return {"verdict": b.get("verdict_ko"), "n": b.get("n"), "small": b.get("small"),
            "win": {"words": w.get("ko"), "p_low": _r(w.get("p_low")), "verdict": w.get("verdict"), "real_stretches": (w.get("emp") or {}).get("ko")},
            "streak": {"words": s.get("ko"), "now": s.get("now"), "share": _r(s.get("share")), "verdict": s.get("verdict")},
            "dd": {"words": d.get("ko"), "deepest": _r(d.get("deepest")), "now": _r(d.get("now")), "share": _r(d.get("share")),
                   "verdict": d.get("verdict"), "how": d.get("how_ko")}}


def _vw_band(prf: dict) -> dict:
    """운이냐 고장이냐 (성적's band, paperbot/vwapband.py): the paper and each follower apart, the yardstick in words."""
    bd = (prf.get("band") or {}) if _ok(prf) else {}
    if bd.get("state") != "ok":
        return {"state": bd.get("state") or "missing", "reason": bd.get("reason_ko") or "자료 없음"}
    ref = bd.get("ref") or {}
    return {"paper": _vw_band_one(bd.get("paper")),
            "live": [{"name": x.get("name_ko"), **_vw_band_one(x)} for x in bd.get("live") or []],
            "yardstick": {"five_years": {"trades": ref.get("trades"), "win_rate": ref.get("win_rate"), "breakeven": ref.get("breakeven_win"),
                                         "roe_per_trade": ref.get("roe_per_trade"), "losing_runs": ref.get("runs"), "longest_run": ref.get("longest")},
                          "honest": ref.get("honest_ko"), "pick17": (ref.get("pick17") or {}).get("ko"), "rule": ref.get("rule_ko"),
                          "src": ref.get("src")}}


def _vw_costs(vs: dict, cfg: dict) -> dict:
    """비용: the round trip on the exchange (DeepCoin's taker as the owners passed it on, both sides) against the 5-year
    research's (taker + slippage both sides), each in net ROE at the bot's leverage; what the code still assumes (until
    the drill measures it); what each follower's live trades on this bot really paid (its own fills)."""
    from . import livecheck as LC
    lev = ((cfg or {}).get("leverage") or {}).get("default") if isinstance((cfg or {}).get("leverage"), dict) else None
    lev = lev if isinstance(lev, (int, float)) and not isinstance(lev, bool) else None
    rt_r = 2 * (RESEARCH_TAKER + RESEARCH_SLIP)
    out = {"words": "왕복 = 진입·청산 두 번의 비율(0.0008 = 0.08%). roe_at_leverage = 왕복 × 배율 = 거래마다 순ROE에서 빠지는 몫",
           "leverage": lev,
           "research": {"taker_side": RESEARCH_TAKER, "slippage_side": RESEARCH_SLIP, "round_trip": _r(rt_r, 6),
                        "roe_at_leverage": _r(rt_r * lev) if lev else None, "src": "research/vwap30/code/vwcommon.py COST_RT"},
           "execs": []}
    for f in vs.get("followers") or []:
        ex = f.get("exchange") or ""
        x = {"name": f["name_ko"], "exchange": LC.EX_KO.get(ex, ex), "code_assumes_taker": LC.ASSUMED_FEE.get(ex),
             "live_measured": f.get("costs")}
        if ex == "deepcoin":
            x["taker_told"] = {"taker_side": DEEPCOIN_TAKER, "round_trip": 2 * DEEPCOIN_TAKER,
                               "roe_at_leverage": _r(2 * DEEPCOIN_TAKER * lev) if lev else None,
                               "words": "딥코인 테이커 수수료 0.04%(한쪽, 시장가) · 코드의 비용 계산은 드릴이 재기 전까지 code_assumes_taker를 씀"}
        out["execs"].append(x)
    return out


def _vw_blocked(blk: dict) -> dict:
    """막은 신호 (its own FILTERED signals by reason: today, 7 days, since its start) and 막지 않았다면 per reason (가상)."""
    if not _ok(blk):
        return _not_ok(blk)
    c = blk.get("counts") or {}
    v = blk.get("virtual") or {}
    out = {"counts": [{"why": g.get("ko"), "today": g.get("today"), "week": g.get("week"), "since_start": g.get("all")}
                      for g in c.get("groups") or []], "total": c.get("total"),
           "label": "가상: 막지 않았다면 (같은 엔진·같은 1분봉으로 다시 계산, 계좌가 비어 있었다고 침, 실제 체결 아님)"}
    if _ok(v):
        out["virtual"] = [{"why": k.get("ko"), "group": k.get("grp_ko"), "n": k.get("n"), "closed": k.get("closed"), "wins": k.get("wins"),
                           "losses": k.get("losses"), "roe_sum": _r(k.get("roe_sum")), "small": k.get("small"), "read": k.get("read_ko"),
                           "paper_result_not_virtual": bool(k.get("paper_result"))} for k in v.get("kinds") or []]
        g = v.get("gate") or {}
        out["gates_virtual"] = {k: (_r(g.get(k)) if k == "roe_sum" else g.get(k)) for k in ("n", "closed", "wins", "losses", "roe_sum", "small")}
    else:
        out["virtual"] = _not_ok(v)
    return out


def _vw_now(ctl: dict) -> dict:
    """관제: running or not, the position (with the gates it passed and the hold limit left), every coin's 4h judgment and
    which side a signal could take now, the entry pauses, the last 48 h of signals by what became of them."""
    if not _ok(ctl):
        return _not_ok(ctl)
    b = ctl.get("bot") or {}
    pos = ctl.get("position")
    p = None
    if isinstance(pos, dict):
        p = {"coin": _coin(pos.get("symbol")), "side": _side(pos.get("side")), "strategy": pos.get("strategy_ko"),
             "entry_kst": kst_text(pos.get("entry_time")), "roe_now": _r(pos.get("roe_now")), "locked": pos.get("locked"),
             "lock_roe": _r(pos.get("lock_roe")), "hold_left": pos.get("left_ko"), "gates_at_entry": (pos.get("gates") or {}).get("text"),
             "executors": [{"name": f.get("name_ko"), "same": f.get("pos_state")} for f in ctl.get("followers") or [] if f.get("state") == "following"]}
    pic = ctl.get("picture") or {}
    coins = {}
    for r in pic.get("rows") or [] if pic.get("state") == "ok" else []:
        v = r.get("vote") or {}
        coins[_coin(r.get("symbol"))] = {"4h": v.get("text") or (f"못 읽음: {_clip(v.get('error'), 100)}" if v.get("error") else None),
                                         "sides": {s.get("member_ko"): s.get("ko") for s in r.get("sides") or []}}
    pz = ctl.get("pause") or {}
    sg = ctl.get("signals") or {}
    return {"running": b.get("running"), "position": p, "as_of_kst": kst_text(pic.get("at")) if pic.get("state") == "ok" else None,
            "coins": coins or {"state": pic.get("state"), "words": pic.get("ko")},
            "pause_now": (pz.get("now") or {}).get("ko"), "next_pause": ({"what": (pz.get("next") or {}).get("ko"),
                                                                          "from_kst": kst_text((pz.get("next") or {}).get("from"))}
                                                                         if pz.get("next") else None),
            "signals_48h": sg.get("counts")}


def _vw_splits(prf: dict) -> dict:
    """나눠 보기 of the paper (성적): strategy, coin, side, the 4h judgment and the volatility at the entry, KST session,
    exit, hold; rows with trades only."""
    if not _ok(prf):
        return {}
    out = {}
    for sp in (prf.get("splits") or {}).get("paper") or []:
        rows = [{"label": r.get("ko"), "n": r.get("n"), "wins": r.get("wins"), "win_rate": _r(r.get("win_rate")),
                 "roe_sum": _r(r.get("roe_sum")), "small": r.get("small")} for r in sp.get("rows") or [] if r.get("n")]
        if rows:
            out[sp.get("ko") or sp.get("id")] = rows
    return out


def _vw_trades(prf: dict, a: int, b: int) -> list:
    """The paper's trades closed in [a, b) (성적's rows: the gates read at the entry, how deep each went, each executor's part)."""
    out = []
    for t in (prf.get("trades") or []) if _ok(prf) else []:
        if t.get("exit_time") is None or not a <= t["exit_time"] < b:
            continue
        live = {}
        for ex, c in (t.get("live") or {}).items():
            if not isinstance(c, dict):
                continue
            live[ex] = ({"followed": True, "roe": _r(c.get("roe")), "pnl": _r(c.get("pnl")), "slip": _r(c.get("slip"), 6)}
                        if c.get("state") == "matched" else {"followed": False, "why": c.get("why_ko") or c.get("state")})
        out.append({"time_kst": kst_text(t.get("entry_time")), "closed_kst": kst_text(t.get("exit_time")), "coin": _coin(t.get("symbol")),
                    "side": _side(t.get("side")), "strategy": t.get("member_ko"), "roe": _r(t.get("roe")), "exit": t.get("reason_ko"),
                    "exit_why": t.get("why"), "minutes": round(t["hold_ms"] / MIN) if t.get("hold_ms") is not None else None,
                    "gates_at_entry": (t.get("gates") or {}).get("text"), "worst_roe": _r(t.get("mae")), "best_roe": _r(t.get("mfe")),
                    "live": live})
        if len(out) >= VWAP_TRADES_KEEP:
            break
    return out


def _vw_cards(src: dict, vs: dict, a: int, b: int) -> list:
    """The watcher's loss cards of the VWAP bot's trades closed in [a, b) (keys "COMBO@mix#vwap|…": livecheck.card_key)."""
    tag = f"#{os.path.splitext(os.path.basename(vs.get('path') or ''))[0]}|"
    cards = (src.get("cards") or {}).get("cards") or []
    return [{"label": c.get("label"), "strategy": c.get("strategy"), "tf": c.get("tf"), "coin": c.get("symbol"), "roe": c.get("roe"),
             "text": _clip(c.get("text") or "", 300)}
            for c in cards if tag in str(c.get("key") or "") and c.get("exit_time") is not None and a <= int(c["exit_time"]) < b][:VWAP_CARDS_KEEP]


def _vw_alarms(src: dict, vs: dict, a: int, b: int) -> list:
    """The watcher's alarms in [a, b) that name this bot or one of its executors."""
    names = [VWAP_NAME, "paperbot-combo-vwap"] + [f["name_ko"] for f in vs.get("followers") or []]
    return [x for x in _alarms_in(src, a, b) if any(n and n in str(x.get("what") or "") for n in names)]


def _vw_rules(ctl: dict, infos: list) -> list:
    """The bot's rules as its running config says them (관제's rules: its combo_run, in the bot's own words), then its
    followers' executor rules (_exec_rules: the exchange stop, halts, the light, the size from the balance, the money)."""
    lines = list((ctl.get("rules") or {}).get("lines") or []) if _ok(ctl) else []
    if not lines:
        lines = ["규칙을 읽지 못했어요(자료 없음): docs/vwap-bot-ko.md 2장이 두 분이 정한 규칙"]
    return lines + (_exec_rules(infos) if infos else ["따라가는 실행기 없음(페이퍼만)"])


def _vw_sizing(vs: dict) -> dict:
    """How each follower sizes its entries and its light (its own config)."""
    rows = []
    for f in vs.get("followers") or []:
        rows.append({"executor": f["name_ko"], "following_now": f.get("now"), "size_from": f.get("size_from") or "paper",
                     "margin_frac": f.get("margin_frac"), "budget_usd": f.get("budget_usd"), "qty_scale": f.get("qty_scale"),
                     "light": {"n": (f.get("light") or [None, None])[0], "min_win": (f.get("light") or [None, None])[1]}})
    return {"execs": rows, "words": "size_from \"equity\" = 진입할 때마다 자기 잔고 × margin_frac를 증거금으로 · light = 페이퍼 최근 n번 중 "
                                    "min_win 이상 이겼을 때만 새 진입을 따라감(그 전 n번 미만은 모두 따라감)"}


def _vw_research(prf: dict) -> dict:
    r = (prf.get("research") or {}) if _ok(prf) else {}
    y, p = r.get("five_year") or {}, r.get("pick17") or {}
    return {"five_years": {k: y.get(k) for k in ("trades", "win_rate", "avg_win_roe", "avg_loss_roe", "breakeven_win", "share_80",
                                                  "next_win_80", "next_roe_80", "next_mult_80")},
            "per_trade_price": y.get("per_trade"), "months": y.get("months"), "words": y.get("ko"),
            "pick17": {k: p.get(k) for k in ("n", "wins", "losses", "win_rate", "span_ko", "ko")}, "src": y.get("src")}


def vwap_bot_facts(vs: dict, prf: dict, now: int) -> dict:
    since = prf.get("since_ms") if _ok(prf) else None
    ref = ((prf.get("band") or {}).get("ref") or {}) if _ok(prf) else {}
    return {"kind": "vwap", "name": VWAP_NAME, "label": vwap_label(vs), "apart": VWAP_APART_KO, "since_kst": kst_text(since),
            "running_days": round((int(now) - int(since)) / DAY, 2) if since else None,
            "followers": [{"name": f["name_ko"], "following_now": f.get("now"), "since_kst": kst_text(f.get("since_ms"))}
                          for f in vs.get("followers") or []],
            "break_even_5y": ref.get("breakeven_win"),
            "reference": ("5년 기준표 있음(band.yardstick: 같은 규칙의 5년 페이퍼) · 5년은 승률이 본전 승률보다 낮아 거래당 손해 · 17일은 "
                          "고를 때 본 가장 좋은 기간이라 기대치 아님"), "small_n": SMALL_N}


def facts_vwap(src: dict, kind: str, window: Optional[tuple] = None, focus: Optional[dict] = None, section: bool = False) -> dict:
    """The packet of the 'VWAP 개선판' (its own meetings, or ``section``: its part of the weekly report): numbers only,
    with their meaning in words, from the live site's VWAP screens (vwap_sources); its fixed rules from its running config,
    its record since its own start (the paper and each follower apart, never the main bot's), the band against its 5
    years, the costs, the signals its gates kept out with their what-ifs (가상)."""
    now = src["now"]
    vs = src.get("vwap") if isinstance(src.get("vwap"), dict) else {"state": "missing"}
    ctl, prf, blk = (vs.get(k) if isinstance(vs.get(k), dict) else {"state": vs.get("state") or "missing",
                                                                   "reason_ko": vs.get("reason_ko") or "읽지 않았어요"}
                     for k in ("control", "perf", "blocked"))
    world = src.get("bot") or {}
    ids = {f["id"] for f in vs.get("followers") or [] if f.get("now")}
    infos = [e for e in world.get("infos") or [] if getattr(e, "name", None) in ids and not getattr(e, "problem", "")]
    cfg = ((ctl.get("rules") or {}) if _ok(ctl) else {})
    run_cfg = {"leverage": cfg.get("leverage")} if cfg else {}
    out = {"meeting": vwap_meeting_label(kind, focus, vs), "now_kst": kst_text(now), "bot": vwap_bot_facts(vs, prf, now),
           "fixed_rules": _vw_rules(ctl, infos), "owners_decisions": list(VWAP_DECISIONS), "sizing": _vw_sizing(vs),
           "record": _vw_record(prf), "band": _vw_band(prf), "costs": _vw_costs(vs, run_cfg), "blocked": _vw_blocked(blk),
           "now": _vw_now(ctl), "splits": _vw_splits(prf), "research": _vw_research(prf), "next_releases": _releases(src),
           "checkpoint_rule": VWAP_CHECK_RULE, "words": VWAP_WORDS}
    if section:
        out["meeting"] = f"{vwap_label(vs)} 주간 보고(같은 회의의 다른 봇 칸)"
        for k in ("next_releases", "research"):           # the main packet says the releases; the research stays in band
            out.pop(k, None)
    if window:
        a, b = window
        out["window_kst"] = [kst_text(a), kst_text(b)]
        out["trades"] = _vw_trades(prf, a, b)
        out["loss_cards"] = _vw_cards(src, vs, a, b)
        out["alarms"] = _vw_alarms(src, vs, a, b)
    if focus:
        out["focus"] = focus
    return out


def vwap_section(src: dict, window: tuple) -> Optional[dict]:
    """The VWAP bot's part of the weekly report (owners 10-25: its own section), None without it."""
    vs = vwap_apart(src)
    if vs is None or vs.get("state") != "ok":
        return None
    return facts_vwap(src, "weekly", window=window, section=True)


# ---------------------------------------------------------------- when a meeting is due
def due_loss(src: dict) -> Optional[tuple]:
    """(key, focus) when a live executor's last two closed trades both lost, closed within LOSS_FRESH_MS; one meeting per
    pair (by the paper trades they followed, so both executors losing the same pair is one meeting)."""
    now = src["now"]
    tr = (src.get("trades") or {}).get("accts") or {}
    trend = is_trend(src.get("bot"))
    since = trend_since_of(src) if trend else None
    vs = vwap_apart(src)                                 # a trade entered while following the VWAP bot is its (due_loss_vwap)
    from .dash.more import livebots as L
    for ex, _ko, _dk, _ck in L.ALL_EXECS:                # the third (딥코인) has rows only once installed
        a = tr.get(ex) or {}
        rows = [r for r in (a.get("rows") or []) if r.get("exit_time") is not None and r.get("pnl") is not None
                and (since is None or (r.get("entry_time") or 0) >= since)      # the trend bot: its own trades only
                and not on_vwap(vs, ex, r.get("entry_time"))]
        rows.sort(key=lambda r: (r["exit_time"], str(r.get("key"))))
        if len(rows) < 2:
            continue
        last2 = rows[-2:]
        if all(r["pnl"] <= 0 for r in last2) and now - last2[-1]["exit_time"] <= LOSS_FRESH_MS:
            ids = [str((r.get("paper") or {}).get("id") or r.get("key")) for r in last2]
            focus = {"executor": ex, "losses": [{"coin": r.get("symbol"), "side": "롱" if (r.get("side") or 0) > 0 else "숏",
                                                  "strategy": r.get("strategy_id"), "tf": r.get("timeframe"), "pnl": r.get("pnl"),
                                                  "roe": r.get("roe"), "paper_roe": (r.get("paper") or {}).get("roe"),
                                                  "exit": r.get("reason_ko"), "closed_kst": kst_text(r.get("exit_time")),
                                                  "loss_card": (r.get("card") or {}).get("label")} for r in last2],
                     "how_rare": how_rare_trend(src) if trend else HOW_RARE_NONE if (src.get("bot") or {}).get("ref_ko") else HOW_RARE_OLD}
            return "loss:" + "+".join(sorted(ids)), focus
    return None


def trend_since_of(src: dict) -> Optional[int]:
    """The 추세판단 봇's first start on its database (bot_world's ``trend``), None when it cannot be read."""
    s = ((src.get("bot") or {}).get("trend") or {}).get("since")
    return int(s) if isinstance(s, (int, float)) and not isinstance(s, bool) else None


def how_rare_trend(src: dict) -> str:
    """No 5-year streak numbers for a new rule set; the replay's win rate (가상) as the only yardstick, said as such."""
    rr = (((src.get("replay") or {}).get("results") or {}).get("replay") or {}) if _ok(src.get("replay")) else {}
    wr = rr.get("win_rate")
    if not isinstance(wr, (int, float)) or isinstance(wr, bool):
        return HOW_RARE_TREND
    both = (1 - float(wr)) ** 2
    return (f"{HOW_RARE_TREND}. 참고(가상): 7/1~10/20 재현의 이긴 비율 {wr:.0%}로 치면 거래 두 번이 둘 다 질 확률은 약 "
            f"{both:.0%}입니다" + ("(드문 일이 아님)" if both >= 0.1 else ""))


def due_checkpoint(src: dict) -> Optional[tuple]:
    if is_trend(src.get("bot")):
        return due_checkpoint_trend(src)
    rows = (((src.get("trades") or {}).get("accts") or {}).get("paper") or {})
    n = rows.get("n") if isinstance(rows, dict) else None
    if not n or n < CHECK_EVERY:
        return None
    k = (int(n) // CHECK_EVERY) * CHECK_EVERY
    pr = [r for r in (rows.get("rows") or []) if r.get("pnl") is not None]
    wins = sum(1 for r in pr[:k] if r["pnl"] > 0) if len(pr) >= k else None
    return f"checkpoint:{k}", {"paper_closed": n, "milestone": k,
                               "last_k_wins": wins, "last_k_rate": wins / k if wins is not None else None}


def due_checkpoint_trend(src: dict) -> Optional[tuple]:
    """The 추세판단 봇: every CHECK_EVERY of its own closed paper trades (entered since its start) is a 거래 점검, once each;
    no 88 % / 82 % rule. Its key names the start, so the bot before it's checkpoints never stand in for it."""
    since = trend_since_of(src)
    if since is None:
        return None                                       # its own trades cannot be told apart: no checkpoint
    rows = (((src.get("trades") or {}).get("accts") or {}).get("paper") or {})
    pr = [r for r in (rows.get("rows") or [] if isinstance(rows, dict) else [])
          if r.get("pnl") is not None and (r.get("entry_time") or 0) >= since]          # newest first
    lt = src.get("trend")
    n = (lt.get("record") or {}).get("n") if _ok(lt) else None
    n = n if isinstance(n, int) and not isinstance(n, bool) else len(pr)
    if n < CHECK_EVERY:
        return None
    k = (n // CHECK_EVERY) * CHECK_EVERY
    wins = sum(1 for r in pr[:k] if r["pnl"] > 0) if len(pr) >= k else None
    return f"checkpoint:trend-{kst_date(since)}:{k}", {"paper_closed_since_start": n, "milestone": k, "since_kst": kst_text(since),
                                                      "last_k_wins": wins, "last_k_rate": wins / k if wins is not None else None}


def due_weekly(src: dict) -> Optional[tuple]:
    now = src["now"]
    m9 = monday_09(now)
    if now < m9 + (WEEKLY_HOUR - 9) * HOUR:
        return None
    return f"weekly:{kst_date(m9)}", {"window": [m9 - 7 * DAY, m9]}


# ---------------------------------------------------------------- VWAP 개선판: when its own meetings are due
def _vwap_paper_trade(vs: dict, pid: Any) -> Optional[dict]:
    """The VWAP bot's paper trade ``pid`` as 성적 shows it (its gates, how deep it went), None when not among them."""
    prf = vs.get("perf") if _ok(vs.get("perf")) else {}
    return next((t for t in prf.get("trades") or [] if pid is not None and str(t.get("id")) == str(pid)), None)


def _vwap_band_of(vs: dict, ex: Optional[str] = None) -> dict:
    """The band of the paper (``ex`` None) or of a follower's live trades on this bot (성적's 운이냐 고장이냐)."""
    bd = ((vs.get("perf") or {}).get("band") or {}) if _ok(vs.get("perf")) else {}
    if bd.get("state") != "ok":
        return {"state": bd.get("state") or "missing", "reason_ko": bd.get("reason_ko") or "5년 비교를 읽지 못했어요"}
    if ex is None:
        return bd.get("paper") or {"state": "missing"}
    return next((b for b in bd.get("live") or [] if b.get("id") == ex), {"state": "missing", "reason_ko": "이 실행기의 비교가 없어요"})


def due_loss_vwap(src: dict) -> Optional[tuple]:
    """(key, focus) when the last two closed trades an executor made while following the VWAP bot both lost, closed within
    LOSS_FRESH_MS (the same rule as every executor's); one meeting per pair, its key apart from the main bot's
    ("loss:vwap:<the VWAP paper trades they followed>"). How rare: the losing run against the 5 years (band)."""
    vs = vwap_apart(src)
    if vs is None or vs.get("state") != "ok":
        return None
    now = src["now"]
    tr = (src.get("trades") or {}).get("accts") or {}
    for f in vs.get("followers") or []:
        rows = [r for r in ((tr.get(f["id"]) or {}).get("rows") or []) if r.get("exit_time") is not None and r.get("pnl") is not None
                and on_vwap(vs, f["id"], r.get("entry_time"))]
        rows.sort(key=lambda r: (r["exit_time"], str(r.get("key"))))
        if len(rows) < 2:
            continue
        last2 = rows[-2:]
        if not (all(r["pnl"] <= 0 for r in last2) and now - last2[-1]["exit_time"] <= LOSS_FRESH_MS):
            continue
        ids = [str((r.get("paper") or {}).get("id") or r.get("key")) for r in last2]
        losses = []
        for r in last2:
            pt = _vwap_paper_trade(vs, (r.get("paper") or {}).get("id")) or {}
            losses.append({"coin": _coin(r.get("symbol")), "side": _side(r.get("side")),
                           "strategy": pt.get("member_ko") or r.get("strategy_id"), "tf": r.get("timeframe"), "pnl": _r(r.get("pnl")),
                           "roe": _r(r.get("roe")), "paper_roe": _r((r.get("paper") or {}).get("roe")), "exit": r.get("reason_ko"),
                           "closed_kst": kst_text(r.get("exit_time")), "gates_at_entry": (pt.get("gates") or {}).get("text"),
                           "worst_roe": _r(pt.get("mae")), "best_roe": _r(pt.get("mfe")), "exit_why": pt.get("why")})
        b = _vwap_band_of(vs, f["id"])
        from . import vwapband as VB
        return "loss:vwap:" + "+".join(sorted(ids)), {
            "bot": "vwap", "executor": f["id"], "executor_ko": f["name_ko"], "losses": losses,
            "how_rare": VB.streak_ko(b) or "5년 비교를 아직 못 했어요(자료 없음)", "band_verdict": b.get("verdict_ko")}
    return None


def due_checkpoint_vwap(src: dict) -> Optional[tuple]:
    """The VWAP paper's 거래 점검 every VWAP_CHECK_EVERY closed trades since its start (the guide's unit), once each; its
    followers' checklists ride along (no rule of the meeting's own: the owners decide)."""
    vs = vwap_apart(src)
    prf = (vs or {}).get("perf")
    if vs is None or not _ok(prf) or not _ok(prf.get("paper")):
        return None
    n = prf["paper"].get("n") or 0
    since = prf.get("since_ms")
    if n < VWAP_CHECK_EVERY or since is None:
        return None
    k = (int(n) // VWAP_CHECK_EVERY) * VWAP_CHECK_EVERY
    ts = prf.get("trades") or []                                      # newest first
    wins = sum(1 for t in ts[:k] if t.get("win")) if len(ts) >= k else None
    return f"checkpoint:vwap-{kst_date(since)}:{k}", {
        "bot": "vwap", "what": "paper", "paper_closed": n, "milestone": k, "since_kst": kst_text(since),
        "last_k_wins": wins, "last_k_rate": wins / k if wins is not None else None,
        "live": [{"name": c.get("name_ko"), "n": c.get("n"), "goal": c.get("goal")} for c in prf.get("checklist") or []]}


def due_checkpoint_vwap_live(src: dict) -> Optional[tuple]:
    """A follower's own 50th, 100th … closed live trade on the VWAP bot (the guide's 실거래 50번: the owners' moment to
    decide about money), once each per follower and start of following."""
    vs = vwap_apart(src)
    prf = (vs or {}).get("perf")
    if vs is None or not _ok(prf):
        return None
    for c in prf.get("checklist") or []:
        n = c.get("n") or 0
        if n < VWAP_CHECK_EVERY or c.get("since_ms") is None:
            continue
        k = (int(n) // VWAP_CHECK_EVERY) * VWAP_CHECK_EVERY
        rec = c.get("record") or {}
        return f"checkpoint:vwap-live-{c.get('id')}-{kst_date(c['since_ms'])}:{k}", {
            "bot": "vwap", "what": "live", "executor": c.get("id"), "executor_ko": c.get("name_ko"), "live_closed": n, "milestone": k,
            "since_kst": kst_text(c["since_ms"]), "win_rate": _r(rec.get("win_rate")), "roe_sum": _r(rec.get("roe_sum")),
            "checks": [{"what": r.get("ko"), "state": r.get("state"), "value": r.get("value_ko")} for r in c.get("rows") or []]}
    return None


# ---------------------------------------------------------------- the members
def system_prompt(role: str, trend: bool = False) -> str:
    if trend:
        return trend_prompt(role)
    r = ROLES[role]
    common = (f"당신은 두 분(코딩과 통계를 모르는 한국인 운영자)의 암호화폐 실거래 봇을 지켜보는 '실거래 분석 팀'의 {r['title']} "
              f"'{r['name']}'입니다. 맡은 것: {r['focus']}.\n\n"
              "지킬 것:\n"
              "1. 읽기만 합니다. 매매 권한이 없습니다. 진입·청산·건너뛰기·크기·레버리지·코인을 바꾸라는 말은 하지 않습니다.\n"
              "2. 고정 규칙(fixed_rules)은 두 분이 정한 것이라 바꾸자고 하지 않습니다.\n"
              "3. 패킷(JSON)에 있는 숫자만 씁니다. 없는 숫자는 '자료 없음'이라고 씁니다. 추측한 숫자를 만들지 않습니다.\n"
              f"4. 거래가 {SMALL_N}번보다 적으면 결론을 내리지 말고 '아직 우연이 큰 단계'라고 분명히 씁니다.\n"
              "5. 5년 기준표가 있을 때만 숫자 둘을 구분해 씁니다: fit(맞춘 숫자, 낙관)과 honest(처음 보는 기간, 현실). 기준표가 없다고 "
              "적혀 있으면(bot.reference) 5년 숫자를 만들거나 지난 봇 숫자를 빌려 오지 않고, 본전 승률(break_even)과 시작 근거"
              "(start_basis)에 비교합니다.\n"
              "6. 페이퍼(연습 돈)와 실거래(진짜 돈)를 섞지 않습니다.\n"
              "7. 쉬운 한국어로, 짧게. 전문용어는 풀어서. 매매법은 코드 그대로 부릅니다(화면이 이름으로 바꿔 보여줍니다).\n")
    if role == "lead":
        return common + (
            "8. 팀원들의 말(team)을 읽고, 숫자와 맞지 않는 말은 고칩니다. 아이디어는 '시험해 볼 가설'로만 씁니다: 무엇을 2020-24 자료로 "
            "고르고 2025-26 자료로 한 번 확인할지, 또는 그림자 봇으로 볼지. 채택은 두 분이 정해진 순서로만 합니다.\n\n"
            "답은 JSON 하나만: {\"headline\": \"한 줄 결론\", \"verdict\": \"정상 범위|지켜보기|주의\", \"summary\": [\"3~5줄\"], "
            "\"good\": [\"잘된 점\"], \"worries\": [\"걱정되는 점\"], \"watch_next\": [\"다음에 볼 것\"], "
            "\"ideas\": [{\"idea\": \"가설\", \"why\": \"근거 숫자\", \"test\": \"시험 방법\"}] (최대 3개, 없으면 [])}")
    return common + ("\n답은 JSON 하나만: {\"headline\": \"한 줄\", \"points\": [\"2~4줄, 숫자와 함께\"], "
                     "\"worry\": \"가장 걱정되는 한 가지 또는 null\", \"luck\": \"이게 우연일 수 있는 정도를 한 줄로\"}")


def trend_prompt(role: str) -> str:
    """The members' instructions on the 추세판단 봇: its parts (judgment, checks, pullback, supervisor, costs), its own
    yardsticks (the coin-flip twin, break-even, the replay labelled 가상), the fixed rules and the owners' decisions never
    up for discussion, an idea only a hypothesis to test with a shadow bot or at the 2-week review."""
    r = ROLES_TREND[role]
    common = (f"당신은 두 분(코딩과 통계를 모르는 한국인 운영자)의 암호화폐 실거래 봇 '추세판단 봇'을 지켜보는 '실거래 분석 팀'의 "
              f"{r['title']} '{r['name']}'입니다. 맡은 것: {r['focus']}.\n\n"
              "이 봇: 판단만 하는 매매법 4개가 끝난 1시간봉·4시간봉·일봉으로 코인마다 추세(상승·하락·보류)를 정하고(30분 진입은 "
              "1시간봉, 1시간 진입은 4시간봉, 4시간 진입은 일봉), 진입 매매법(bot.entry_members)의 신호 중 그 추세를 거스르지 않는 "
              "쪽만(보류도 받는지는 fixed_rules의 추세 판단 줄) 진입 전 검사(EMA20에서 너무 뻗었나·RSI·돌파형은 추세 초입만·추격 "
              "막기)를 거쳐 들어갑니다. 그 분에 바로 들어가는지, 진입 봉 하나 동안 되돌림을 기다렸다가 들어가는지는 fixed_rules의 "
              "'진입' 줄 그대로입니다. 첫 잠금 전에는 감독이 상위 봉 추세가 반대로 바뀌면 닫습니다. 손절·계단 익절과 숫자는 "
              "fixed_rules 그대로. 거래마다 비용(미끄러짐·수수료)이 얼마나 빠지는지는 costs에 있습니다(재현 숫자는 가상).\n\n"
              "지킬 것:\n"
              "1. 읽기만 합니다. 매매 권한이 없습니다. 진입·청산·건너뛰기·크기·레버리지·코인을 바꾸라는 말은 하지 않습니다.\n"
              "2. 고정 규칙(fixed_rules)과 두 분의 결정(owners_decisions: 10/22 새 설계와 그 보류 허용·진입 방식, 시간 정리 청산 없음, "
              "쉬기·하루 손실 한도 없음, 나스닥 개장 앞뒤 진입 없음, 실거래 크기 각 지갑의 약 40%)은 두 분이 정한 것이라 바꾸자고 "
              "하지 않습니다. 규칙은 2주 검토"
              "(bot.review_kst) 전에는 그대로입니다.\n"
              "3. 패킷(JSON)에 있는 숫자만 씁니다. 없는 숫자는 '자료 없음'이라고 씁니다. 추측한 숫자를 만들지 않습니다.\n"
              f"4. 새 봇 시작 뒤 거래가 {SMALL_N}번보다 적으면 결론을 내리지 말고 '아직 우연이 큰 단계'라고 분명히 씁니다.\n"
              "5. 이 봇은 새 규칙이라 5년 기준표가 없습니다. 5년 숫자를 만들거나 지난 봇(규칙봇 15 · A+C) 숫자를 빌려 오지 않습니다. "
              "비교는 셋으로만: 같은 순간 방향만 동전으로 정한 쌍둥이(record.flip, record.luck), 본전 승률(bot.break_even), 7/1~10/20 "
              "재현(replay). 재현과 whatif 숫자는 실제 거래가 아니라서 쓸 때마다 '가상'이라고 붙입니다.\n"
              "6. 페이퍼(연습 돈)와 실거래(진짜 돈)를 섞지 않습니다. 새 봇 시작(bot.since_kst) 전에 들어간 거래는 예전 봇 것이라"
              "(old_bot_trades) 이 봇 성적에 넣지 않습니다.\n"
              "7. 쉬운 한국어로, 짧게. 전문용어는 풀어서. 매매법은 코드 그대로 부릅니다(화면이 이름으로 바꿔 보여줍니다).\n"
              "8. 이 봇의 부품으로 말합니다: 추세 판단, 진입 전 검사, 진입 방식(바로 진입 또는 되돌림 기다림: fixed_rules), 감독 청산, "
              "비용. 어느 부품이 신호를 막았는지는 "
              "funnel·signals_24h로, 도왔는지는 whatif(가상)로만 말합니다.\n")
    if role == "lead":
        return common + (
            "9. 팀원들의 말(team)을 읽고, 숫자와 맞지 않는 말은 고칩니다. 아이디어는 '시험해 볼 가설'로만 씁니다: 그림자 봇(주문 없이 "
            "같은 시장에서 나란히 돌리는 비교용 봇, tests_available의 deploy/combo.shadow-trend-*.json 같은 설정)으로 볼지, 2주 검토"
            "(bot.review_kst)에서 어떤 숫자로 볼지. 2주 검토 전에는 규칙을 바꾸지 않고, 채택은 두 분이 정합니다.\n\n"
            "답은 JSON 하나만: {\"headline\": \"한 줄 결론\", \"verdict\": \"정상 범위|지켜보기|주의\", \"summary\": [\"3~5줄\"], "
            "\"good\": [\"잘된 점\"], \"worries\": [\"걱정되는 점\"], \"watch_next\": [\"다음에 볼 것\"], "
            "\"ideas\": [{\"idea\": \"가설\", \"why\": \"근거 숫자\", \"test\": \"시험 방법(그림자 봇 또는 2주 검토)\"}] (최대 3개, 없으면 [])}")
    return common + ("\n답은 JSON 하나만: {\"headline\": \"한 줄\", \"points\": [\"2~4줄, 숫자와 함께\"], "
                     "\"worry\": \"가장 걱정되는 한 가지 또는 null\", \"luck\": \"이게 우연일 수 있는 정도를 한 줄로\"}")


LEAD_JSON = ("답은 JSON 하나만: {\"headline\": \"한 줄 결론\", \"verdict\": \"정상 범위|지켜보기|주의\", \"summary\": [\"3~5줄\"], "
             "\"good\": [\"잘된 점\"], \"worries\": [\"걱정되는 점\"], \"watch_next\": [\"다음에 볼 것\"], "
             "\"ideas\": [{\"idea\": \"가설\", \"why\": \"근거 숫자\", \"test\": \"시험 방법\"}] (최대 3개, 없으면 [])}")
MEMBER_JSON = ("\n답은 JSON 하나만: {\"headline\": \"한 줄\", \"points\": [\"2~4줄, 숫자와 함께\"], "
               "\"worry\": \"가장 걱정되는 한 가지 또는 null\", \"luck\": \"이게 우연일 수 있는 정도를 한 줄로\"}")


def vwap_prompt(role: str) -> str:
    """The members' instructions on the 'VWAP 개선판' (its own meetings): its parts (two strategies, two entry gates, the
    pauses, the 2 ATR stop, the ladder, the hold limit), its yardstick (the band against its own 5 years, which lost per
    trade; the 17 days the picked best period), never the main bot's numbers, the fixed rules and the owners' decisions
    never up for discussion, an idea only a hypothesis to test."""
    r = ROLES_VWAP[role]
    common = (f"당신은 두 분(코딩과 통계를 모르는 한국인 운영자)의 암호화폐 실거래 봇 '{VWAP_NAME}'을 지켜보는 '실거래 분석 팀'의 "
              f"{r['title']} '{r['name']}'입니다. 맡은 것: {r['focus']}.\n\n"
              "이 봇: 규칙봇의 두 매매법 신호(VWAP 복귀 실패 30분, CMO·샌드위치 캔들 1시간)로 들어갑니다. 진입 전 조건 두 개(그 코인 "
              "4시간 추세 판단이 신호 반대쪽이면 진입 안 함, 신호 봉 변동성이 지난 30일 기준으로 너무 크면 진입 안 함)와 쉬는 시간"
              "(주말·미국 경제 발표 앞뒤·나스닥 개장 앞뒤)이 신호를 막습니다. 손절은 ATR 기준, 이익은 계단 익절, 자기 봉 수가 보유 "
              "한도를 넘으면 시장가로 정리, 포지션은 한 번에 하나. 숫자는 fixed_rules 그대로입니다. 실거래는 이 봇을 따라가는 실행기"
              "(bot.label)가 하고, 신호등이 빨강이면 새 진입을 따라가지 않습니다.\n\n"
              "지킬 것:\n"
              "1. 읽기만 합니다. 매매 권한이 없습니다. 진입·청산·건너뛰기·크기·레버리지·코인을 바꾸라는 말은 하지 않습니다.\n"
              "2. 고정 규칙(fixed_rules)과 두 분의 결정(owners_decisions)은 두 분이 정한 것이라 바꾸자고 하지 않습니다.\n"
              "3. 패킷(JSON)에 있는 숫자만 씁니다. 없는 숫자는 '자료 없음'이라고 씁니다. 추측한 숫자를 만들지 않습니다.\n"
              f"4. 거래가 {SMALL_N}번보다 적으면 결론을 내리지 말고 '아직 우연이 큰 단계'라고 분명히 씁니다.\n"
              f"5. 이 봇은 추세판단 봇과 다른 봇입니다(bot.apart). 추세판단 봇과 그 봇을 따라가는 실행기의 숫자를 쓰거나 섞지 않고, 이 "
              f"봇을 말할 때는 '{VWAP_NAME}'(실거래는 bot.label에 적힌 실행기 이름)이라고 부릅니다.\n"
              "6. 이 봇의 잣대는 band(운이냐 고장이냐: 같은 규칙의 5년 페이퍼)입니다. 5년은 승률이 본전 승률보다 낮아 거래당 손해였다는 "
              "것을 숨기지 않습니다. band의 '정상 범위'는 5년처럼 돈다는 뜻이지 돈을 번다는 뜻이 아닙니다. 17일(pick17)은 고를 때 본 가장 "
              "좋은 기간이라 기대치로 쓰지 않습니다. '아주 드묾'이면 설계와 다르게 돌고 있을 수 있다고 분명히 씁니다.\n"
              "7. 페이퍼(연습 돈)와 실거래(진짜 돈)를 섞지 않습니다. blocked의 '막지 않았다면'은 실제 거래가 아니라서 쓸 때마다 '가상'이라고 "
              "붙입니다.\n"
              "8. 쉬운 한국어로, 짧게. 전문용어는 풀어서. 매매법은 패킷에 적힌 이름 그대로 부릅니다.\n")
    if role == "lead":
        return common + (
            "9. 팀원들의 말(team)을 읽고, 숫자와 맞지 않는 말은 고칩니다. 아이디어는 '시험해 볼 가설'로만 씁니다: 무엇을 2020-24 자료로 "
            "고르고 2025-26 자료로 한 번 확인할지(research/vwap30 방식), 또는 그림자 봇(주문 없이 같은 시장에서 나란히 돌리는 비교용 봇)"
            "으로 볼지. 채택은 두 분이 정합니다.\n\n" + LEAD_JSON)
    return common + MEMBER_JSON


def vwap_section_prompt(role: str) -> str:
    """Added to a weekly report's instructions when the packet has the VWAP bot's part (``vwap_bot``): another bot, its own
    yardstick, its own lines in the answer."""
    out = (f"\n\n[다른 봇: {VWAP_NAME}] 패킷에 vwap_bot이 있습니다. 위 봇과 다른 봇입니다(vwap_bot.bot.apart: 매매법·손절·진입 조건·"
           "페이퍼 기록·실행기가 모두 따로). 두 봇의 숫자를 섞지 않습니다. vwap_bot의 고정 규칙(vwap_bot.fixed_rules)과 두 분의 결정"
           "(vwap_bot.owners_decisions)도 바꾸자고 하지 않습니다. 이 봇의 잣대는 vwap_bot.band(같은 규칙의 5년 페이퍼)입니다: 5년은 거래당 "
           "손해였고, '정상 범위'는 5년처럼 돈다는 뜻일 뿐이며, 17일(pick17)은 고른 가장 좋은 기간이라 기대치가 아닙니다. 막지 않았다면 "
           "결과(vwap_bot.blocked)는 '가상'입니다.\n")
    if role == "lead":
        return out + (f"답 JSON에 \"vwap\": {{\"headline\": \"{VWAP_NAME} 한 줄 결론\", \"verdict\": \"정상 범위|지켜보기|주의\", "
                      "\"summary\": [\"2~4줄\"], \"worries\": [\"걱정되는 점\"], \"watch_next\": [\"다음에 볼 것\"], \"ideas\": [{\"idea\": \"가설\", "
                      "\"why\": \"근거 숫자\", \"test\": \"시험 방법\"}] (최대 2개)}를 따로 넣습니다(위 봇의 결론에는 섞지 않음).")
    return out + f"답 JSON에 \"vwap_points\": [\"{VWAP_NAME}에 대해 1~3줄, 숫자와 함께\"]를 따로 넣습니다(points에는 섞지 않음)."


def packet_vwap(packet: Optional[dict]) -> bool:
    """The packet describes the VWAP bot only (facts_vwap)."""
    return isinstance(packet, dict) and (packet.get("bot") or {}).get("kind") == "vwap"


def prompt_for(role: str, packet: Optional[dict]) -> str:
    """The instructions of ``role`` for this packet: the VWAP bot's own meeting (vwap_prompt), else the main bot's
    (system_prompt; the trend bot's when the packet is its) with the VWAP part's addition when the packet has one."""
    if packet_vwap(packet):
        return vwap_prompt(role)
    sp = system_prompt(role, packet_trend(packet))
    if isinstance(packet, dict) and isinstance(packet.get("vwap_bot"), dict):
        sp += vwap_section_prompt(role)
    return sp


def instruction(role: str, kind: str, label: Optional[str] = None) -> str:
    return (f"{label or KIND_KO.get(kind, kind)} 회의입니다. 표준입력의 JSON 패킷(facts: 사실, team: 앞 팀원들의 말)을 읽고 "
            f"'{ROLES[role]['name']}'({ROLES[role]['title']})로서 정해진 JSON 하나만 답하세요.")


def packet_trend(packet: Optional[dict]) -> bool:
    """The packet describes the 추세판단 봇 (facts_trend)."""
    return isinstance(packet, dict) and (packet.get("bot") or {}).get("kind") == "trend"


def member_text(role: str, data: Optional[dict], raw: str) -> str:
    if not isinstance(data, dict):
        return _clip(raw, 1200)
    if role == "lead":
        lines = [_clip(data.get("headline"))] + [f"· {x}" for x in _list(data.get("summary"))]
        v = data.get("vwap") if isinstance(data.get("vwap"), dict) else None
        if v:                                                 # the weekly report's VWAP part, named
            lines += [f"· [{VWAP_NAME}] {_clip(v.get('headline'))}"] + [f"· [{VWAP_NAME}] {x}" for x in _list(v.get("summary"), 4)]
        return "\n".join(x for x in lines if x)
    lines = [_clip(data.get("headline"))] + [f"· {x}" for x in _list(data.get("points"), 4)]
    lines += [f"· [{VWAP_NAME}] {x}" for x in _list(data.get("vwap_points"), 3)]     # the weekly report's VWAP part
    if data.get("worry"):
        lines.append(f"걱정: {_clip(data['worry'])}")
    if data.get("luck"):
        lines.append(f"우연일 정도: {_clip(data['luck'])}")
    return "\n".join(x for x in lines if x)


def lead_result(data: Optional[dict]) -> dict:
    d = data if isinstance(data, dict) else {}
    ideas = []
    for i in (d.get("ideas") or [])[:IDEAS_MAX] if isinstance(d.get("ideas"), list) else []:
        if isinstance(i, dict) and str(i.get("idea") or "").strip():
            ideas.append({"idea": _clip(i.get("idea")), "why": _clip(i.get("why")), "test": _clip(i.get("test"))})
    v = d.get("verdict") if d.get("verdict") in VERDICTS else "지켜보기"
    out = {"headline": _clip(d.get("headline")) or "(팀장 결론 없음)", "verdict": v, "summary": _list(d.get("summary")),
           "good": _list(d.get("good")), "worries": _list(d.get("worries")), "watch_next": _list(d.get("watch_next")), "ideas": ideas}
    vw = d.get("vwap")
    if isinstance(vw, dict):                                  # the weekly report's VWAP part (vwap_section_prompt)
        vi = [{"idea": _clip(i.get("idea")), "why": _clip(i.get("why")), "test": _clip(i.get("test"))}
              for i in (vw.get("ideas") if isinstance(vw.get("ideas"), list) else [])[:2]
              if isinstance(i, dict) and str(i.get("idea") or "").strip()]
        out["vwap"] = {"headline": _clip(vw.get("headline")) or f"({VWAP_NAME} 결론 없음)",
                       "verdict": vw.get("verdict") if vw.get("verdict") in VERDICTS else "지켜보기", "summary": _list(vw.get("summary")),
                       "worries": _list(vw.get("worries")), "watch_next": _list(vw.get("watch_next")), "ideas": vi}
    return out


# ---------------------------------------------------------------- budget
def used(conn, now: int) -> dict:
    day = kst_date(now)
    d = conn.execute("SELECT COALESCE(SUM(calls),0), COALESCE(SUM(tokens),0) FROM usage WHERE day = ?", (day,)).fetchone()
    w = conn.execute("SELECT COALESCE(SUM(calls),0) FROM usage WHERE ts >= ?", (now - 7 * DAY,)).fetchone()
    return {"day_calls": int(d[0]), "day_tokens": int(d[1]), "week_calls": int(w[0])}


def fits(conn, now: int, budget: dict, calls: int, tokens: int) -> Optional[str]:
    """None when ``calls`` more calls of at most ``tokens`` each fit the budget, else why not (in words)."""
    u = used(conn, now)
    if u["day_calls"] + calls > budget["day"]:
        return f"오늘 AI 호출 한도({budget['day']}번) 안에 들어가지 않아 다음으로 미룹니다"
    if u["week_calls"] + calls > budget["week"]:
        return f"최근 7일 AI 호출 한도({budget['week']}번) 안에 들어가지 않아 다음으로 미룹니다"
    if u["day_tokens"] + calls * tokens > budget["tokens_day"]:
        return f"오늘 AI 토큰 한도({budget['tokens_day']:,}) 안에 들어가지 않아 다음으로 미룹니다"
    return None


# ---------------------------------------------------------------- one meeting
def hold(conn, kind: str, key: str, packet: dict, runner, now: int, budget: dict, notifier=None, dry: bool = False,
         model: str = MODEL_DEFAULT, clock: Callable[[], int] = lambda: int(time.time() * 1000)) -> dict:
    """Hold one meeting: the members in order, then the lead; recorded as it goes (a member who fails is recorded and the
    others still speak; a plan limit stops the meeting). Returns the meeting row as a dict."""
    from .agents import runner as R
    roles = KIND_ROLES[kind]
    # the members' instructions for this packet (prompt_for: the 추세판단 봇's trend_prompt, the VWAP bot's vwap_prompt, the
    # weekly report's VWAP part added)
    label = packet.get("meeting") if isinstance(packet.get("meeting"), str) and packet.get("meeting") else KIND_KO[kind]
    title = f"{label} · {kst_text(now)}"
    est = R.call_charge(R.input_estimate(R.packet_payload({"role": "lead", "facts": packet, "team": [{"text": "x" * 1200}] * 3}),
                                         prompt_for("lead", packet), instruction("lead", kind, label)))
    why = None if dry else fits(conn, now, budget, len(roles), est)
    if why:
        return {"state": "deferred", "why": why, "key": key}
    cur = conn.execute("INSERT INTO meetings (kind, key, title, started_ts, state, why, packet, dry) VALUES (?,?,?,?,?,?,?,?)",
                       (kind, key, title, now, "running", None, json.dumps(packet, ensure_ascii=False, default=str), int(dry)))
    mid = cur.lastrowid
    conn.commit()
    team, calls, tokens, lead, failed = [], 0, 0, None, None
    for seq, role in enumerate(roles, 1):
        pkt = {"role": role, "meeting": kind, "facts": packet, "team": team}
        t0 = clock()
        try:
            res = runner.call(model, prompt_for(role, packet), instruction(role, kind, label), pkt)
            used_t = R._sum((res.meta or {}).get("usage"), R.USAGE_KEYS) if isinstance(res.meta, dict) else 0
            text, data, err = member_text(role, res.data, res.text), res.data, None
        except R.UsageLimitReached as exc:
            used_t, text, data, err = int(getattr(exc, "tokens", 0) or 0), "", None, f"AI 사용 한도: {_clip(exc, 200)}"
            failed = "AI 사용 한도에 걸려 회의를 멈췄습니다(다음에 다시 열지 않음)"
        except Exception as exc:  # noqa: BLE001  a member's failure is recorded, the others still speak
            used_t, text, data, err = int(getattr(exc, "tokens", 0) or 0), "", None, _clip(f"{type(exc).__name__}: {exc}", 300)
        calls += 1
        tokens += used_t
        if not dry:
            conn.execute("INSERT INTO usage (ts, day, meeting, role, calls, tokens) VALUES (?,?,?,?,?,?)",
                         (t0, kst_date(t0), mid, role, 1, used_t))
        conn.execute("INSERT INTO messages (meeting, seq, role, ts, text, data, model, tokens, error) VALUES (?,?,?,?,?,?,?,?,?)",
                     (mid, seq, role, t0, text or ("(답 없음: " + (err or "알 수 없음") + ")"),
                      json.dumps(data, ensure_ascii=False) if data is not None else None, model, used_t, err))
        conn.commit()
        if err is None:
            if role == "lead":
                lead = lead_result(data)
            else:
                team.append({"who": f"{ROLES[role]['name']}({ROLES[role]['title']})", "text": text})
        if failed:
            break
    if lead is None:
        why = failed or "팀장이 결론을 쓰지 못했습니다(아래 팀원 기록 참고)"
        conn.execute("UPDATE meetings SET state = 'failed', why = ?, finished_ts = ?, calls = ?, tokens = ? WHERE id = ?",
                     (why, clock(), calls, tokens, mid))
        conn.commit()
        return {"id": mid, "state": "failed", "why": why, "key": key}
    sec = packet.get("vwap_bot") if isinstance(packet.get("vwap_bot"), dict) else None
    if lead.get("vwap") is not None:
        if sec is None:
            lead.pop("vwap")                                  # no VWAP part in this packet: nothing of it is kept
        else:
            lead["vwap"]["label"] = (sec.get("bot") or {}).get("label") or VWAP_NAME
    for i in lead["ideas"] + [{**i, "idea": f"[{VWAP_NAME}] {i['idea']}"} for i in (lead.get("vwap") or {}).get("ideas") or []]:
        conn.execute("INSERT INTO ideas (meeting, ts, idea, why, test) VALUES (?,?,?,?,?)", (mid, now, i["idea"], i["why"], i["test"]))
    sent = None
    if notifier is not None and not dry:
        sent = int(bool(_send(notifier, message(kind, lead, label))))
    conn.execute("UPDATE meetings SET state = 'done', finished_ts = ?, headline = ?, verdict = ?, result = ?, sent = ?, calls = ?, "
                 "tokens = ? WHERE id = ?", (clock(), lead["headline"], lead["verdict"], json.dumps(lead, ensure_ascii=False), sent,
                                             calls, tokens, mid))
    conn.commit()
    return {"id": mid, "state": "done", "key": key, "lead": lead, "calls": calls, "tokens": tokens}


def quiet(conn, kind: str, key: str, now: int, why: str) -> dict:
    conn.execute("INSERT INTO meetings (kind, key, title, started_ts, finished_ts, state, why, headline) VALUES (?,?,?,?,?,?,?,?)",
                 (kind, key, f"{KIND_KO[kind]} · {kst_text(now)}", now, now, "quiet", why, why))
    conn.commit()
    return {"state": "quiet", "key": key, "why": why}


def message(kind: str, lead: dict, label: Optional[str] = None) -> str:
    """The conclusion's quiet message; a weekly report with the VWAP bot's part (``lead["vwap"]``) tells it under its own
    name ("— VWAP 개선판 · 딥코인 🟡 지켜보기"), never mixed into the main bot's lines."""
    icons = {"정상 범위": "🟢", "지켜보기": "🟡", "주의": "🟠"}
    icon = icons.get(lead.get("verdict"), "🟡")
    lines = [f"🧭 [실거래 분석팀] {label or KIND_KO.get(kind, kind)} {icon} {lead.get('verdict')}", lead.get("headline") or ""]
    lines += [f"· {x}" for x in (lead.get("summary") or [])[:4]]
    v = lead.get("vwap") if isinstance(lead.get("vwap"), dict) else None
    if v:
        lines += [f"— {v.get('label') or VWAP_NAME} {icons.get(v.get('verdict'), '🟡')} {v.get('verdict')}", v.get("headline") or ""]
        lines += [f"· {x}" for x in (v.get("summary") or [])[:3]]
    n_ideas = len(lead.get("ideas") or []) + len((v or {}).get("ideas") or [])
    if n_ideas:
        lines.append(f"시험해 볼 아이디어 {n_ideas}개 (결정은 두 분)")
    lines.append(f"자세히: {DASH_HINT} · AI 의견이라 참고만, 매매는 고정 규칙대로")
    return "\n".join(x for x in lines if x)


def _send(notifier, text: str) -> bool:
    try:
        r = notifier.send(INFO, text)
        return r is not False
    except Exception:  # noqa: BLE001  the meeting stands without its message
        return False


# ---------------------------------------------------------------- tick / run
DUE = {"loss": due_loss, "checkpoint": due_checkpoint, "weekly": due_weekly}
# the VWAP bot's own meetings (owners 10-25): its weekly part rides on the weekly report (vwap_section); "weekly" here is
# only for a meeting opened by hand (run weekly --vwap)
DUE_VWAP = {"loss": due_loss_vwap, "checkpoint": due_checkpoint_vwap,
            "weekly": lambda src: (lambda got: (got[0] + ":vwap", {**got[1], "bot": "vwap"}) if got else None)(due_weekly(src))}


def due(conn, src: dict) -> list:
    """[(kind, key, focus)] not held yet, strongest first (loss, checkpoint, weekly); the VWAP bot's loss after the main
    bot's, its follower's 실거래 50번 and its paper's 거래 점검 after the main bot's checkpoint."""
    out = []
    for kind, fn in (("loss", due_loss), ("loss", due_loss_vwap), ("checkpoint", due_checkpoint),
                     ("checkpoint", due_checkpoint_vwap_live), ("checkpoint", due_checkpoint_vwap), ("weekly", due_weekly)):
        got = fn(src)
        if got and not conn.execute("SELECT 1 FROM meetings WHERE key = ?", (got[0],)).fetchone():
            out.append((kind, got[0], got[1]))
    return out


def packet_for(src: dict, kind: str, focus: dict) -> dict:
    """The packet of a due meeting: the VWAP bot's own (``focus["bot"] == "vwap"``: facts_vwap), else the main bot's,
    the weekly report with the VWAP bot's part when it runs (``vwap_bot``: vwap_section)."""
    if (focus or {}).get("bot") == "vwap":
        now = src["now"]
        win = tuple(focus["window"]) if kind == "weekly" and focus.get("window") else \
            (now - 3 * DAY, now + 1) if kind == "loss" else (now - (7 if kind == "weekly" else 14) * DAY, now + 1)
        return facts_vwap(src, kind, window=win, focus=focus)
    if kind == "weekly":
        a, b = focus["window"]
        pk = facts(src, kind, window=(a, b))
        sec = vwap_section(src, (a, b))
        if sec is not None:
            pk["vwap_bot"] = sec
        return pk
    if kind == "loss":
        return facts(src, kind, window=(src["now"] - 3 * DAY, src["now"] + 1), focus=focus)
    return facts(src, kind, window=(src["now"] - 14 * DAY, src["now"] + 1), focus=focus)


def week_has_trades(packet: dict) -> bool:
    return bool(packet.get("trades")) or bool((packet.get("vwap_bot") or {}).get("trades"))


def tick(conn, src: dict, runner, budget: dict, notifier=None, dry: bool = False, model: str = MODEL_DEFAULT,
         only: Optional[str] = None, force: bool = False, clock: Optional[Callable[[], int]] = None,
         vwap: bool = False) -> Optional[dict]:
    """Hold the first due meeting (``only``: that kind; ``force``: hold it even if held before, under a new key; ``vwap``:
    the VWAP bot's own meeting of that kind; ``clock``: the time each call is charged at, the wall clock by default)."""
    more = {"clock": clock} if clock is not None else {}
    now = src["now"]
    items = due(conn, src) if not force else []
    if vwap and not force:
        items = [x for x in items if (x[2] or {}).get("bot") == "vwap"]
    if force and only:
        got = (DUE_VWAP if vwap else DUE)[only](src)
        focus = got[1] if got else ({"window": [now - 7 * DAY, now]} if only == "weekly" else {"note": "손으로 연 회의"})
        if vwap:
            focus = {**focus, "bot": "vwap"}
        items = [(only, f"{only}:{'vwap:' if vwap else ''}manual:{now}", focus)]
    for kind, key, focus in items:
        if only and kind != only:
            continue
        packet = packet_for(src, kind, focus)
        if kind == "weekly" and not week_has_trades(packet):
            return quiet(conn, kind, key, now, "지난주 닫힌 거래가 없어 AI 회의 없이 넘어갑니다")
        return hold(conn, kind, key, packet, runner, now, budget, notifier=notifier, dry=dry, model=model, **more)
    return None


def status_lines(conn, now: int, budget: dict) -> list:
    u = used(conn, now)
    out = [f"AI 사용: 오늘 {u['day_calls']}/{budget['day']}번 · 토큰 {u['day_tokens']:,}/{budget['tokens_day']:,} · 최근 7일 "
           f"{u['week_calls']}/{budget['week']}번"]
    for r in conn.execute("SELECT id, kind, title, state, headline, why FROM meetings ORDER BY id DESC LIMIT 10"):
        out.append(f"#{r[0]} {r[2]} [{r[3]}] {r[4] or r[5] or ''}")
    return out


def _runner(dry: bool):
    from .agents import runner as R
    if dry:
        return R.FakeRunner(answers={
            "lead": {"headline": "(연습) 결론", "verdict": "지켜보기", "summary": ["(연습) 요약"], "good": [], "worries": [],
                     "watch_next": [], "ideas": []}})
    return R.ClaudeCodeRunner(timeout=900.0)


def _notifier():
    from .notify import TelegramNotifier
    try:
        return TelegramNotifier()
    except KeyError:
        return None


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.liveteam", description="실거래 분석 팀 (읽기만, 매매 권한 없음)")
    ap.add_argument("--db", default=os.environ.get(DB_ENV) or DB_DEFAULT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tick")
    t.add_argument("--dry-run", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("kind", choices=sorted(KIND_ROLES))
    r.add_argument("--force", action="store_true")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--vwap", action="store_true", help=f"the {VWAP_NAME} bot's own meeting of that kind")
    pv = sub.add_parser("preview")
    pv.add_argument("kind", choices=sorted(KIND_ROLES))
    pv.add_argument("--vwap", action="store_true", help=f"the {VWAP_NAME} bot's own packet and its members' instructions")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    try:
        budget = parse_budget(os.environ.get(BUDGET_ENV))
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    model = os.environ.get(MODEL_ENV) or MODEL_DEFAULT
    now = int(time.time() * 1000)
    if a.cmd == "preview":
        src = sources(now)
        got = (DUE_VWAP if a.vwap else DUE)[a.kind](src)
        focus = got[1] if got else ({"window": [now - 7 * DAY, now]} if a.kind == "weekly" else {"note": "지금은 열릴 조건이 아님"})
        if a.vwap:
            focus = {**focus, "bot": "vwap"}
        pkt = packet_for(src, a.kind, focus)
        print(json.dumps(pkt, ensure_ascii=False, indent=1, default=str))
        for role in KIND_ROLES[a.kind]:
            print(f"\n===== {ROLES[role]['name']} ({ROLES[role]['title']})\n{prompt_for(role, pkt)}\n"
                  f"--- {instruction(role, a.kind, pkt.get('meeting'))}")
        return 0
    conn = connect(a.db)
    try:
        if a.cmd == "status":
            print("\n".join(status_lines(conn, now, budget)))
            return 0
        dry = bool(getattr(a, "dry_run", False))
        if not dry:
            from .agents import runner as R
            ok, why = R.auth_preflight(env=dict(os.environ))
            put_state(conn, "auth", now, {"ok": ok, "why": why})
            if not ok:
                print(f"Claude 로그인 확인 실패: {why}", file=sys.stderr)
                return 0                    # nothing held; the 분석팀 tab says why
        src = sources(now)
        got = tick(conn, src, _runner(dry), budget, notifier=None if dry else _notifier(), dry=dry, model=model,
                   only=getattr(a, "kind", None), force=bool(getattr(a, "force", False)), vwap=bool(getattr(a, "vwap", False)))
        put_state(conn, "tick", now, {"result": {k: v for k, v in (got or {}).items() if k != "lead"}, "dry": dry})
        print(json.dumps(got or {"state": "nothing due"}, ensure_ascii=False, default=str)[:2000])
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
