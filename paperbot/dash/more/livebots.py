"""실거래 (#/livebots): 두 분의 실거래 봇 두 개(바이비트 · MEXC 주문 실행기)와 그 둘이 따라가는 페이퍼 계좌(A+C 합본,
``COMBO@mix``)를 보여 줍니다. 읽기만 합니다: 봇 쪽 코드(paperbot/combo.py, paperbot/executor.py)는 가져오지 않고, 그 봇들이
쓰는 표 모양(paperbot/store3.py SCHEMA, executor.py SCHEMA + MIGRATIONS)만 알고 그 모양에서 읽습니다. 주문 키 파일
(executor.env)은 열지 않습니다.

    GET /api/v4/livebots     요약(실거래 터미널): 세 계좌(페이퍼 · 바이비트 · MEXC)의 잔고 · 멈춤 · 열린 포지션 · 오늘 · 시간별
                             손익 · 달력, 체결 줄, 신호등, 40번 판단까지, 주의·긴급 기록 (5초 캐시)

어디서 읽나 (환경 변수로 바꿀 수 있음, 기본값 = 10/19 시작 안내 docs/live1019-start-ko.md):
    PAPERBOT_LIVE_PAPER_DB      /var/lib/paperbot/combo/live-ac.db              페이퍼 봇 (store3 표)
    PAPERBOT_LIVE_PAPER2_DB     /var/lib/paperbot/combo/vwap.db                 두 번째 페이퍼 봇 ('VWAP 개선판', 있을 때만 보임)
    PAPERBOT_LIVE_BYBIT_DB      /var/lib/paperbot/exec/executor-bybit-live.db   바이비트 실행기
    PAPERBOT_LIVE_MEXC_DB       /var/lib/paperbot/exec/executor-mexc-live.db    MEXC 실행기
    PAPERBOT_LIVE_BYBIT_CONFIG  /etc/paperbot/executor.json                     (키 없음: 계좌 · 신호등 · 크기 비율 · 위험 한도만 씀)
    PAPERBOT_LIVE_MEXC_CONFIG   /etc/paperbot/executor-mexc.json
    PAPERBOT_LIVE_DEEPCOIN_DB   /var/lib/paperbot/exec/executor-deepcoin-live.db 딥코인 실행기 (세 번째, 설치됐을 때만 보임)
    PAPERBOT_LIVE_DEEPCOIN_CONFIG /etc/paperbot/executor-deepcoin.json
    PAPERBOT_LIVE_WOOXPRO2_DB   /var/lib/paperbot/exec/executor-wooxpro2-live.db WOO X Pro 2 실행기 (네 번째, 설치됐을 때만 보임)
    PAPERBOT_LIVE_WOOXPRO2_CONFIG /etc/paperbot/executor-wooxpro2.json
    PAPERBOT_LIVE_PAPER3_DB     /var/lib/paperbot/combo/friend.db               세 번째 페이퍼 봇 ('친구 매매법': WOO X Pro 2가 따라감)
    PAPERBOT_LIVE_TOOBIT_DB     /var/lib/paperbot/exec/executor-toobit-live.db  투비트 실행기 (다섯 번째, 설치됐을 때만 보임)
    PAPERBOT_LIVE_TOOBIT_CONFIG /etc/paperbot/executor-toobit.json
    PAPERBOT_LIVE_RANGE_DB      /var/lib/paperbot/combo/range.db                레인지 봇 페이퍼 ('range': 그 설정에 range가 있을 때만)
    PAPERBOT_LIVE_CHECK_DB      /var/lib/paperbot/livecheck.db                  아침 점검 · 실시간 감시 · 손실 카드 (paperbot/livecheck.py)
    PAPERBOT_LIVE_IMPROVE_DB    /var/lib/paperbot/liveimprove.db                주간 성적표 · 개선 후보 장부 (paperbot/liveimprove.py)

5년 기준표(deploy/combo.live-ac.expected.json, combo.live-ac.likely.json)의 config_sha256이 PAPERBOT_LIVE_COMBO_CONFIG 파일의
sha256과 다르면(설정이 바뀜) 그 표는 지난 봇 것이라 쓰지 않습니다(livecheck.ref_config_problem): 순위의 5년 숫자, 성적표, 기대 범위 띠,
진입 가능성, 시작 안내의 참고선(REFS)과 40번 판단 기준(88% · 82%) 대신 그 이유 한 줄. 파일을 못 읽으면(개발 PC) 예전처럼 씁니다.

추세판단 봇 (10/21, docs/trend-bot-ko.md): 페이퍼 봇의 시작 기록(``combo_run``)의 설정에 ``trend``가 있으면 그 봇은 새 규칙이라
비교할 백테스트 기준이 아예 없습니다(``trend_bot``). 그때는 설정 파일을 못 읽어도 5년 기준표 · 참고선 · 88%/82% 기준을 쓰지 않고
(``live_ref`` / ``ref_problem``: TREND_NO_REF_KO), 성적 · 지도 · 순위는 그 봇이 이 기록 파일에서 처음 켜진 때(``trend_since``)부터의
거래만 셉니다. 그 봇이 아니면 모든 것이 예전 그대로입니다.

거래 · 성적 · 안전 탭은 그 둘도 읽습니다(읽기만):손실 카드(거래), 매매법 성적표와 개선 후보 장부(성적; 성적표는 liveimprove의
함수로 지금 계산: ``score`` 명령과 같은 숫자와 상태 말), 아침 점검 14일과 감시 알람(안전).

DB는 모두 ``mode=ro``(쓰는 쪽이 멈춘 WAL 파일은 immutable, paperbot.livepnl.open_ro) + ``query_only``로 열고, 한 번 읽는 동안
하나의 시점(BEGIN)으로 읽습니다.

못 읽은 것을 '없음'으로 보이지 않기 (CONTRACT §1.6), 출처마다:
    ``state: "missing"``  파일이나 표가 아직 없음 -> 화면은 '수집 전'
    ``state: "error"``    있는데 읽지 못함(권한, 망가짐, 잠김) -> '못 읽음' + 이유, 0이나 빈 목록으로 바뀌지 않음
    ``state: "ok"``

신호등은 실행기의 규칙(executor.Executor._light_ok, Paper3Source.recent)을 그대로 옮겼습니다: 실행기가 따라가는 페이퍼 계좌의
마지막 N번 닫힌 거래(exit_time, id 순으로 최신부터) 중 이긴(pnl > 0) 수가 N x 기준 이상이면 초록, 아니면 빨강, N번이 안 되면 근거
쌓는 중(모든 진입을 따라감), N = 0이면 꺼짐.

두 페이퍼 (owners 10/19, docs/live15-mexc-ko.md): 실행기마다 자기 페이퍼를 따로 짝지어요(paperbot/livepapers.py). 실행기 설정의
paper_db와, 실행기가 시작할 때마다 남기는 기록(start 이벤트의 paper_db)으로 "언제부터 어느 페이퍼를 따라갔는지"를 알고, 실거래 거래는
그때 따라간 페이퍼의 거래와만 비교해요. 두 실행기가 같은 페이퍼를 따라가면(10/20 상태) 모든 것이 예전과 같아요. 두 번째 페이퍼 봇
(PAPERBOT_LIVE_PAPER2_DB) 파일이 있거나 실행기가 다른 페이퍼를 따라가면 그 페이퍼도 계좌 하나로 보여요(``paper2``).

세 번째 실행기 (owners 10-24, docs/deepcoin-ko.md: 딥코인이 'VWAP 개선판'을 따라감; 10-23에 정한 플립스터는 API가 신청제라 바꿈):
그 칸(``deepcoin``)은 이 서버에 설치됐을 때만, 곧 그 설정 파일(PAPERBOT_LIVE_DEEPCOIN_CONFIG)이나 그 DB(PAPERBOT_LIVE_DEEPCOIN_DB)
중 하나라도 있을 때만 모든 화면에 나와요(``installed``; 실거래 점검 paperbot/livecheck.py와 같은 규칙). 둘 다 없으면 화면 · 답은
예전 그대로(실행기 두 개)예요. 칸 이름은 그 설정의 거래소(``EX_NAME``)를 따라요.

네 번째 실행기 (owners 10-24, docs/friend-bot-ko.md: 두 번째 WOO X Pro 계정이 '친구 매매법'을 따라감): 그 칸(``wooxpro2``)도
설치됐을 때만(PAPERBOT_LIVE_WOOXPRO2_CONFIG 또는 PAPERBOT_LIVE_WOOXPRO2_DB) 나오고, 이름은 그 설정의 ``label``("WOO X Pro 2"; 두
실행기가 WOO X Pro를 쓰니 거래소 이름만으로는 갈라지지 않아요)이에요. 그 실행기의 카드 · 거래 · 포지션은 다른 실행기와 같이 나와요.
그 페이퍼 봇(PAPERBOT_LIVE_PAPER3_DB, friend.db)은 계좌 칸으로 따로 나오지 않아요: 실행기가 따라가는 봇 이름으로만 나오고(``follows_ko``),
두 번째 페이퍼 봇('VWAP 개선판') 자리를 차지하지 않아요(``paper_bots``). 둘 다 없으면 모든 답이 예전 그대로예요.

다섯 번째 실행기 (owners 10-25, docs/toobit-ko.md: 투비트, $50; 따라갈 페이퍼 계좌는 나중에 정함, 규칙봇의 V3.9 1시간 계좌가 유력): 그
칸(``toobit``)도 설치됐을 때만(PAPERBOT_LIVE_TOOBIT_CONFIG 또는 PAPERBOT_LIVE_TOOBIT_DB) 나오고, 이름은 그 설정의 거래소(``EX_NAME``:
투비트)예요. 그 실행기가 따라가는 페이퍼(설정의 paper_db · account)는 계좌 칸으로 따로 나오지 않고 두 번째 페이퍼 봇 자리도 차지하지
않아요(``paper_bots``: ``SIDE_PAPER_EXECS``). 둘 다 없으면 모든 답이 예전 그대로예요.

레인지 봇 (owners 10-26, docs/range-bot-ko.md: WOO X Pro가 추세판단 봇에서 레인지 봇으로 옮김, 딥코인은 그대로 'VWAP 개선판'):
페이퍼 봇이 셋이 될 수 있어요(``paper_bots``: "paper" · "paper2" · "range", BOT_IDS). 레인지 봇은 이름이나 파일 이름이 아니라 그 봇의
시작 기록 설정에 ``range``가 있는지로만 알아요(``range_bot``). 그 봇이 없으면 페이퍼 하나 · 둘인 화면과 답은 예전 그대로예요.

시간은 UTC 밀리초, 비율은 비율(0.85 = 85%), 돈은 각 계좌의 단위(페이퍼 USDT, 실거래 거래소 USDT).
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import os
import sqlite3
import stat
import threading
import time
from typing import Any, Iterable, Optional

from ... import livepapers as LP

ACCOUNT = "COMBO@mix"                 # paperbot/combo.py ACCOUNT (the account both executors follow)
FLIP_ACCOUNT = "COMBOFLIP@mix"         # paperbot/combo.py FLIP_ACCOUNT (coin-flip twin: same moments, random side; 참고)
ENV = {
    "paper": ("PAPERBOT_LIVE_PAPER_DB", "/var/lib/paperbot/combo/live-ac.db"),
    # the second paper bot (owners 10-23, docs/vwap-bot-ko.md: 'VWAP 개선판', one executor follows it; before, 10-19:
    # 규칙봇 15 at -35 %, live15-mexc.db): shown next to the first one once its file exists, or once an executor follows
    # another paper database; nothing of it shows before (the one-paper page stays as it was)
    "paper2": ("PAPERBOT_LIVE_PAPER2_DB", "/var/lib/paperbot/combo/vwap.db"),
    "bybit_db": ("PAPERBOT_LIVE_BYBIT_DB", "/var/lib/paperbot/exec/executor-bybit-live.db"),
    "mexc_db": ("PAPERBOT_LIVE_MEXC_DB", "/var/lib/paperbot/exec/executor-mexc-live.db"),
    "bybit_config": ("PAPERBOT_LIVE_BYBIT_CONFIG", "/etc/paperbot/executor.json"),
    "mexc_config": ("PAPERBOT_LIVE_MEXC_CONFIG", "/etc/paperbot/executor-mexc.json"),
    # the third slot (owners 10-24: DeepCoin follows the 'VWAP 개선판' paper bot, docs/deepcoin-ko.md): on the page only
    # once it is installed (``installed``)
    "deepcoin_db": ("PAPERBOT_LIVE_DEEPCOIN_DB", "/var/lib/paperbot/exec/executor-deepcoin-live.db"),
    "deepcoin_config": ("PAPERBOT_LIVE_DEEPCOIN_CONFIG", "/etc/paperbot/executor-deepcoin.json"),
    # the fourth slot (owners 10-24: WOO X Pro 2, a second WOO X Pro account, follows '친구 매매법', docs/friend-bot-ko.md):
    # on the page only once it is installed; its paper bot's file is never a page account (paper_bots)
    "wooxpro2_db": ("PAPERBOT_LIVE_WOOXPRO2_DB", "/var/lib/paperbot/exec/executor-wooxpro2-live.db"),
    "wooxpro2_config": ("PAPERBOT_LIVE_WOOXPRO2_CONFIG", "/etc/paperbot/executor-wooxpro2.json"),
    "paper3": ("PAPERBOT_LIVE_PAPER3_DB", "/var/lib/paperbot/combo/friend.db"),
    # the fifth slot (owners 10-25: 투비트, a $50 executor; the paper account it follows is decided later,
    # docs/toobit-ko.md): on the page only once it is installed
    "toobit_db": ("PAPERBOT_LIVE_TOOBIT_DB", "/var/lib/paperbot/exec/executor-toobit-live.db"),
    "toobit_config": ("PAPERBOT_LIVE_TOOBIT_CONFIG", "/etc/paperbot/executor-toobit.json"),
}
# the 레인지 봇 (owners 10-26, docs/range-bot-ko.md: WOO X Pro follows it): a page account of its own ("range") next to the
# two paper bots of ENV once an executor follows it or its file is there, always told by its config (``range_bot``). Kept
# apart from ENV (callers that list ENV's files in full stay as they were); paths() reads both.
ENV_RANGE = {"range": ("PAPERBOT_LIVE_RANGE_DB", "/var/lib/paperbot/combo/range.db")}
# the executor slots a mix bot (paperbot/mixchop.py) trades by itself now (owners 10-29, docs/mixbybit-ko.md: the Bybit
# account is the 바이비트 봇's): once that bot's server config is there the old executor's slot leaves every page and
# every answer (installed), as it leaves the live checks (livecheck.REPLACED_BY); the summary names the bot that took it
# (``replaced``: 한눈에 shows that bot's own card). Its config path the same variable as dash/more/livemix.py's.
ENV_MIX = {"mixbybit_config": ("PAPERBOT_MIXBYBIT_CONFIG", "/etc/paperbot/mixbybit.json")}
REPLACED = {"bybit": {"key": "mixbybit_config", "bot": "bybit", "name_ko": "바이비트 봇", "account_ko": "바이비트",
                      "unit": "paperbot-mixbybit", "api": "/api/v4/livebots/mixbybit", "tab": "bybitbot"}}
# the second paper bot's file before 10-23 (규칙봇 15 at -35 %): the site's second bot while the VWAP bot's file is not there
# yet and no variable names one, so the page stays as it was until the owners start the VWAP bot (paths). Only the site:
# the live watcher reports a second bot only from the VWAP default (livecheck.paper2_default), never this old one.
LEGACY_PAPER2 = "/var/lib/paperbot/combo/live15-mexc.db"
# (id, Korean name, db key, config key): the two slots every page has
EXECS = (("bybit", "바이비트", "bybit_db", "bybit_config"), ("mexc", "MEXC", "mexc_db", "mexc_config"))
# the slots a server has only once they are installed (``installed``: their config file or their database is there);
# owners 10-24: the third, 딥코인, follows the 'VWAP 개선판' paper bot (docs/deepcoin-ko.md)
OPTIONAL_EXECS = (("deepcoin", "딥코인", "deepcoin_db", "deepcoin_config"),
                  # owners 10-24: the fourth, WOO X Pro 2 (its config's label), follows '친구 매매법'
                  ("wooxpro2", "WOO X Pro 2", "wooxpro2_db", "wooxpro2_config"),
                  # owners 10-25: the fifth, 투비트 (docs/toobit-ko.md)
                  ("toobit", "투비트", "toobit_db", "toobit_config"))
ALL_EXECS = EXECS + OPTIONAL_EXECS
# the slots whose paper bot is never one of the page's paper bots (paper_bots): 투비트 follows a paper account of its own
# (owners 10-25: most likely the rule bot's V3.9 1-hour account, decided later), never the second paper bot's place
SIDE_PAPER_EXECS = ("toobit",)
# the page's paper bots (paper_bots), in this order: the main one (PAPERBOT_LIVE_PAPER_DB, the 추세판단 봇), the second
# (owners 10-23: the 'VWAP 개선판'), the 레인지 봇 (owners 10-26). A page that lists paper accounts takes them all.
BOT_IDS = ("paper", "paper2", "range")
RANGE_NAME_KO = "레인지 봇"
# the exchange a slot's config names, in the owners' words (owners 10-20: the second slot runs WOO X Pro; its id, unit
# and config path stay "mexc" so every page and check keeps working). Flipster: the third slot's exchange of 10-23, still
# an exchange the executor can run (a slot config naming it reads 플립스터)
EX_NAME = {"bybit": "바이비트", "mexc": "MEXC", "wooxpro": "WOO X Pro", "binance": "바이낸스", "deepcoin": "딥코인",
           "flipster": "플립스터", "toobit": "투비트"}
LIGHT_N_DEFAULT = 0                    # executor.ExecConfig.signal_light_n: 0 = the light is off
LIGHT_MIN_DEFAULT = 0.85               # executor.ExecConfig.signal_light_min_win
MATCH_MS = 5 * 60_000                  # a live trade and a paper trade of the same coin and side within 5 minutes
EXEC_STALE_MS = 3 * 60_000             # the executor saves its state every loop (~3 s); a 418 wait is 2 minutes
PAPER_STALE_MS = 5 * 60_000            # the paper saves every stepped minute (its ts is the minute's open)
EVENTS_KEEP = 200                      # WARN / CRITICAL events per executor
FILLS_KEEP = 60                        # 실거래 체결 rows (entries and exits of the three accounts)
WHY_SCAN = 4000                        # recent events read for the reasons of a missed entry
CURVE_MAX = 300                        # points of an equity line (thinned, the last one always kept)
TTL_S = 5.0
HOUR = 3_600_000
DAY = 86_400_000
KST_MS = 9 * HOUR
SMALL = (20, 40)                       # 표본 적음 under 20, then under 40 closed trades (the page says which)
# 10/19 start guide (docs/live1019-start-ko.md "매일 볼 것"): reference win rates, 참고 only (not a promise)
REFS = {"backtest": 0.91, "shake": [0.84, 0.86], "breakeven": 0.78,
        "label_ko": "참고 · 10/19 시작 안내의 숫자예요. 지나간 기간의 시험 결과이지 약속이 아니에요"}
# owners 10/19: at 40 paper trades they decide (88 % or more: think about more money; 82-88 %: keep watching; below 82 %:
# stop and think again). Before 40 trades nothing is decided: the page shows the progress only.
CHECKPOINT = {"trades": 40, "up": 0.88, "low": 0.82,
              "up_ko": "88% 이상이면 금액 늘리기 검토", "mid_ko": "82~88%면 그대로 지켜보기", "low_ko": "82% 미만이면 멈추고 다시 생각"}
EXEC_TRADE_COLS = ("key", "symbol", "side", "qty", "leverage", "entry_ts", "entry_price", "stop_initial", "exit_ts",
                   "exit_reason", "pnl", "data", "pnl_source", "realized", "commission", "funding", "slippage")
# reasons a paper entry was not followed, strongest first (executor.py events carrying data.key)
WHY = (("light_red", "신호등 빨강이라 따라가지 않았어요"),
       # "own" (owners 10-20): its own position (거래소 기준) was still open; a missed signal, not an alarm
       ("own_busy", "실거래가 아직 자기 포지션(거래소 기준)을 들고 있어 따라가지 않았어요"),
       # liq_guard (owners 10-25 night): the stop would sit beyond the liquidation at its leverage; a missed signal
       ("liq_skip", "손절이 강제청산 가격보다 멀어 들어가지 않았어요"),
       # macro_block_min (owners 10-25 night): a US release (CPI, FOMC, NFP, PCE) within that many minutes
       ("macro_skip", "미국 경제 발표 앞뒤라 들어가지 않았어요"),
       # us_open_pre_min / us_open_pause_min (owners 10-26, "투비트도 나스닥 개장 앞뒤 30분 진입금지"): a missed signal
       ("us_open_skip", "나스닥 개장 앞뒤라 들어가지 않았어요"),
       ("late", "페이퍼 진입을 늦게 봐서 건너뛰었어요"),
       ("entry_check", "진입 검사에서 막혔어요"),
       ("entry_skip", "가격이 이미 손절선을 지나 들어가지 않았어요"),
       ("leverage_refused", "거래소가 레버리지 설정을 거절했어요"),
       ("entry_refused", "거래소가 진입 주문을 거절했어요"),
       ("entry_unfilled", "진입 주문이 체결되지 않았어요"),
       ("light_unread", "신호등이 페이퍼 기록을 읽지 못해 미뤘어요"),
       ("direct_skip", "빠른 진입을 건너뛰었어요"),
       # 잔고 바닥 (owners 10-24, docs/friend-bot-ko.md): an executor with a floor stops new entries until clear-floor
       ("floor_skip", "잔고 바닥 멈춤(새 진입 없음) 동안이라 따라가지 않았어요"))
WHY_KO = dict(WHY)
KIND_KO = {
    "halt": "멈춤", "halted": "멈춘 채 시작", "halt_cleared": "멈춤 풀림", "light_red": "신호등 빨강",
    "light_unread": "신호등 기록 못 읽음", "pnl_check": "거래소 기록과 다름", "unknown_position": "모르는 포지션",
    "wrong_side": "반대 방향 포지션", "protect_failed": "손절 못 걺", "not_flat": "닫았는데 남음", "no_stop": "손절 없음",
    "oversize": "크기 넘침", "paper_unreadable": "페이퍼 못 읽음", "paper_stale": "페이퍼 기록 멈춤", "late": "늦어서 건너뜀",
    "entry_check": "진입 검사 막힘", "entry_skip": "진입 안 함", "entry_refused": "진입 거절", "leverage_refused": "레버리지 거절",
    "entry_unfilled": "체결 안 됨", "entry_unknown": "진입 결과 모름", "entry_pending": "진입 확인 중", "partial_fill": "일부만 체결",
    "loop_error": "반복 오류", "rate_limit": "요청 한도", "move_failed": "손절 옮기기 실패", "exit": "청산", "transfer": "입출금",
    "db_error": "기록 실패", "fills_unread": "체결 기록 못 읽음", "time_sync": "서버 시간", "reconcile_failed": "대조 실패",
    "stop_size": "손절 크기", "stop_level": "손절 가격", "stop_would_trigger": "손절이 바로 걸릴 자리", "size_mismatch": "크기 다름",
    "cancel_failed": "취소 실패", "mainnet_refused": "실거래 관문 거절", "mainnet_unreachable": "관문 확인 못 함",
    "mainnet_unverified": "관문 확인 안 됨", "mode_refused": "포지션 모드 거절", "margin_refused": "격리 마진 거절",
    "margin": "격리 마진", "key_permission": "키 권한", "position_read": "포지션 못 읽음", "account_unread": "잔고 못 읽음",
    "transfers_unread": "입출금 못 읽음", "signal_read": "신호 못 읽음", "signal_mode_off": "빠른 진입 꺼짐",
    "oversize_retry": "크기 줄이기 다시", "cap_unchecked": "한도 확인 못 함", "recover": "복구", "direct_confirmed": "빠른 진입 확인",
    "own_prices": "거래소 1분봉 못 읽음", "own_lock": "거래소 기준 잠금", "own_stay": "거래소 기준으로 계속",
    "own_busy": "자기 포지션 중이라 안 따라감",
    # owners 10-25 night (투비트): 고정 익절 and the liquidation guard
    "own_tp": "고정 익절", "own_tp_price": "고정 익절 가격 못 읽음", "liq_skip": "손절이 청산가보다 멀어 안 들어감",
    "macro_skip": "경제 발표 앞뒤라 안 들어감", "us_open_skip": "나스닥 개장 앞뒤라 안 들어감",
    "paper_exit_unknown": "페이퍼 청산 이유 모름", "paper_exit_unread": "페이퍼 청산 기록 못 읽음",
    # 잔고 바닥 / 원금 회수 안내 / the key file (owners 10-24, docs/friend-bot-ko.md)
    "floor_hit": "잔고 바닥 멈춤", "floor_skip": "바닥 멈춤이라 안 따라감", "floor_start": "시작 금액 기록",
    "floor_cleared": "바닥 멈춤 풀림", "double": "원금 회수 안내", "key_untied": "키 묶음 풀림",
}
LEVEL_KO = {"WARN": "주의", "CRITICAL": "긴급"}
# exit reasons: the paper engine's codes (paperbot/combo.py KO_EXIT) and what an executor's close was
EXIT_KO = {"SL": "손절", "LOCK": "잠금 익절", "LIQ": "강제청산", "HALT": "멈춤 청산", "MANUAL": "수동 청산", "REV": "빠른 청산",
           "JUDGE": "감독 청산(추세 뒤집힘)", "TIME": "감독 청산(시간 정리)", "SWITCH": "전환 전 포지션 정리", "STALE": "잠금 전 시간 정리",
           "END": "끝냄", "TP": "익절", "PAPER": "페이퍼 따라 청산", "OTHER": "기타 청산"}
MISSING_KO = "아직 파일이 없어요 (봇을 아직 켜지 않았거나, 설정의 경로가 달라요)"
NO_TABLE_KO = "파일은 있지만 아직 기록 표가 없어요 (봇이 첫 기록을 쓰기 전)"

_lock = threading.Lock()
_cache: dict = {}


# ---------------------------------------------------------------- small helpers
def _f(x: Any) -> Optional[float]:
    """A finite float, else None."""
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _i(x: Any) -> Optional[int]:
    if x is None or isinstance(x, bool):
        return None
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _j(raw: Any) -> dict:
    try:
        d = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    except (TypeError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def paths(env: Optional[dict] = None) -> dict:
    """Where each source is: the environment variable when set, else the start guide's path. An executor's database:
    its variable when set, else the ``db`` its own config names (owners 10-20: the second slot's WOO X Pro executor has
    its own database), else the start guide's path."""
    env = os.environ if env is None else env
    out = {k: (env.get(var) or default) for k, (var, default) in {**ENV, **ENV_RANGE, **ENV_MIX}.items()}
    if not env.get(ENV["paper2"][0]) and not os.path.exists(out["paper2"]) and os.path.exists(LEGACY_PAPER2):
        out["paper2"] = LEGACY_PAPER2          # before the VWAP bot's file is there: the page as it was (the -35 % bot)
    for _ex, _ko, dk, ck in ALL_EXECS:
        if not env.get(ENV[dk][0]):
            db = _config_db(out[ck])
            if db:
                out[dk] = db
    return out


def replaced(p: dict) -> list:
    """The slots a mix bot trades now (REPLACED: its server config is there), in EXECS order."""
    return [ex for ex, _ko, _dk, _ck in ALL_EXECS
            if ex in REPLACED and p.get(REPLACED[ex]["key"]) and os.path.exists(p[REPLACED[ex]["key"]])]


def replaced_out(p: dict) -> list:
    """The summary's ``replaced``: [{id, bot, name_ko, account_ko, unit, api, tab}] (none: [])."""
    return [{"id": ex, **{k: v for k, v in REPLACED[ex].items() if k != "key"}} for ex in replaced(p)]


def installed(p: dict) -> tuple:
    """The executor slots of this server, in EXECS order: the two first always (but a slot a mix bot trades now,
    ``replaced``); an optional slot (the third, 딥코인) once its config file or its database is there (``p``: paths()).
    Neither there: the pages, the answers, the checks and the messages are as they were with two executors."""
    gone = set(replaced(p))
    return tuple(s for s in EXECS if s[0] not in gone) \
        + tuple(s for s in OPTIONAL_EXECS if any(p.get(k) and os.path.exists(p[k]) for k in (s[3], s[2])))


def shown_paths(p: dict) -> dict:
    """``p`` as an answer shows it: an optional slot's two paths only once it is installed, the third paper bot's file
    only once it is there (else as it was)."""
    have = {s[0] for s in installed(p)}
    drop = {k for s in OPTIONAL_EXECS if s[0] not in have for k in (s[2], s[3])}
    for k in ("paper3", "range", *ENV_MIX):             # the friend's, the 레인지 봇's and the mix configs once there
        if not (p.get(k) and os.path.exists(p[k])):
            drop.add(k)
    return {k: v for k, v in p.items() if k not in drop}


def _config_db(path: str) -> Optional[str]:
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return None
    db = raw.get("db") if isinstance(raw, dict) else None
    return db if isinstance(db, str) and db else None


def slots(configs: Optional[dict] = None) -> list:
    """EXECS with each slot's name taken from its config: its ``label`` when it has one (owners 10-24: "WOO X Pro 2"),
    else the exchange it names (the slot's own name when unread); an optional slot only when ``configs`` has it (the
    callers read the configs of ``installed`` slots; a slot a mix bot trades now is not there either). No configs: the
    two first slots."""
    out = []
    for ex, ko, dk, ck in ALL_EXECS:
        if ex not in (configs or {}) and ((ex, ko, dk, ck) in OPTIONAL_EXECS or configs):
            continue
        c = (configs or {}).get(ex) or {}
        name = (c.get("label") or EX_NAME.get(c.get("exchange"))) if c.get("state") == "ok" else None
        out.append((ex, name or ko, dk, ck))
    return out


# ``word`` with the Korean particle its last sound takes ("VWAP 개선판을", "추세판단 봇을", "딥코인은"; livepapers.josa)
josa = LP.josa


def thin(points: list, n: int = CURVE_MAX) -> list:
    """At most ``n`` points, evenly picked; the first and the last always kept."""
    if len(points) <= n:
        return list(points)
    step = (len(points) - 1) / (n - 1)
    idx = sorted({round(i * step) for i in range(n)} | {0, len(points) - 1})
    return [points[i] for i in idx]


def kst_day(ts: int) -> int:
    """The Korea-time day number of an epoch-ms time (days since 1970-01-01 KST; dash/more/flow.py's rule)."""
    return (int(ts) + KST_MS) // DAY


def kst_day_start(kd: int) -> int:
    return kd * DAY - KST_MS


def reason_ko(exc: BaseException, path: str = "") -> str:
    """A failed read in plain words (the raw text goes next to it, for whoever fixes it)."""
    msg = str(exc).lower()
    if "is not a file" in msg:
        return "그 자리에 파일이 아니라 다른 것(폴더 등)이 있어요"
    if isinstance(exc, PermissionError) or "permission" in msg or "unable to open" in msg or "readonly" in msg:
        if "/exec" in str(path):
            return ("대시보드가 이 파일을 읽을 권한이 없어요. 서버의 대시보드 서비스 설정(paperbot-dash.service)이 실행기 폴더"
                    "(/var/lib/paperbot/exec)를 막고 있으면 이렇게 보여요. 서버 설정을 바꾸는 쪽에 부탁해 주세요")
        return "대시보드가 이 파일을 읽을 권한이 없어요 (읽기 권한이나 위치를 확인해야 해요)"
    if "not a database" in msg or "malformed" in msg or "corrupt" in msg:
        return "기록 파일이 망가졌거나 데이터베이스 파일이 아니에요"
    if "locked" in msg or "busy" in msg:
        return "쓰는 쪽이 잡고 있어서 이번엔 못 읽었어요 (곧 다시 읽어요)"
    if "no such table" in msg or "no such column" in msg:
        return "기록 파일의 표 모양이 예상과 달라요"
    return "읽는 중 문제가 생겼어요"


def _err(path: str, exc: BaseException) -> dict:
    return {"state": "error", "path": path, "reason": f"{type(exc).__name__}: {exc}"[:300], "reason_ko": reason_ko(exc, path)}


def _missing(path: str, why: str = MISSING_KO) -> dict:
    return {"state": "missing", "path": path, "reason_ko": why}


def open_ro(path: str) -> sqlite3.Connection:
    """A read-only connection in autocommit mode (the caller opens one BEGIN for a consistent read). FileNotFoundError when
    nothing is there; PermissionError / OSError / sqlite3.Error when it cannot be read."""
    from ...livepnl import open_ro as livepnl_open_ro            # mode=ro; immutable for a WAL file whose writer stopped
    mode = os.stat(path).st_mode                                  # FileNotFoundError / PermissionError go up as they are
    if not stat.S_ISREG(mode):
        raise OSError(f"{path} is not a file")
    conn = livepnl_open_ro(path)
    try:
        conn.isolation_level = None
        conn.execute("PRAGMA query_only=ON")
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchall()
    except sqlite3.Error:
        conn.close()
        raise
    return conn


def _tables(conn: sqlite3.Connection) -> set:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _cols(conn: sqlite3.Connection, table: str) -> set:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def stats(pnls: Iterable[float]) -> dict:
    """Closed-trade record: count, wins (pnl > 0, the executor's rule), win share, net P&L."""
    xs = [p for p in (_f(v) for v in pnls) if p is not None]
    n = len(xs)
    wins = sum(1 for p in xs if p > 0)
    return {"trades": n, "wins": wins, "losses": n - wins, "win_rate": wins / n if n else None, "pnl": sum(xs) if n else 0.0,
            "small": n < SMALL[1], "small_floor": SMALL[0] if n < SMALL[0] else SMALL[1]}


# ---------------------------------------------------------------- the light (executor._light_ok, word for word)
def need_wins(n: int, min_win: float) -> int:
    """The fewest wins of the last n that keep the light green (wins >= min_win x n, the executor's 1e-9 slack)."""
    return int(math.ceil(float(min_win) * int(n) - 1e-9))


def light(n: Any, min_win: Any, pnl_newest_first: list) -> dict:
    """The light for a new entry right now. ``pnl_newest_first``: the paper account's closed-trade P&L, newest first (at
    least the last n). Fewer than n closed trades: no basis yet, every entry is followed (``building``)."""
    n = _i(n) or 0
    mw = _f(min_win)
    mw = LIGHT_MIN_DEFAULT if mw is None else mw
    if n <= 0:
        return {"state": "off", "n": 0, "min_win": mw}
    recent = [p > 0 for p in (_f(v) for v in pnl_newest_first[:n]) if p is not None]
    have, wins, need = len(recent), sum(recent), need_wins(n, mw)
    out = {"n": n, "min_win": mw, "need_wins": need, "have": have, "wins": wins, "recent": recent}
    if have < n:
        return {**out, "state": "building", "need_more": n - have, "share": wins / have if have else None}
    green = wins >= mw * n - 1e-9
    oldest_win = recent[-1]                      # the result that drops out of the window at the next close
    out.update(state="green" if green else "red", share=wins / n, spare=wins - need)
    if green:
        out["next_loss_red"] = (wins - (1 if oldest_win else 0)) < need
    else:
        out["next_win_green"] = (wins + 1 - (1 if oldest_win else 0)) >= need
    return out


# ---------------------------------------------------------------- the executors' configs (no secrets in them)
RISK_KEYS = ("max_consecutive_losses", "max_drawdown_pct", "daily_max_loss_usd", "max_loss_frac", "max_leverage",
             "max_notional_usd", "allowed_symbols", "kill_file")


def risk_limits(risk: dict, budget: Any = None, size_from: Any = "paper") -> list:
    """The limits a config REALLY has, in the owners' words, in a fixed order; a limit the config does not set is left out
    (owners 10/19: the $40 daily limit and the wallet check were taken out, so they must not show up as if they held).
    An executor sized from its balance (``size_from`` "equity", owners 10-25 night) never cuts an entry for its stop, so
    its risk.max_loss_frac is left out too."""
    out = []
    v = _i(risk.get("max_consecutive_losses"))
    if v:
        out.append({"key": "max_consecutive_losses", "value": v, "ko": f"{v}연패면 멈춤", "what_ko": "연속 손실"})
    v = _f(risk.get("max_drawdown_pct"))
    if v:
        out.append({"key": "max_drawdown_pct", "value": v, "ko": f"최고점에서 {round(v * 100)}% 빠지면 멈춤", "what_ko": "낙폭"})
    v = _f(risk.get("daily_max_loss_usd"))
    if v:
        out.append({"key": "daily_max_loss_usd", "value": v, "ko": f"하루 ${v:,.0f} 잃으면 멈춤", "what_ko": "하루 손실"})
    v = _f(risk.get("max_loss_frac"))
    if v and size_from != "equity":
        out.append({"key": "max_loss_frac", "value": v, "ko": f"손절 한 번에 잔고의 최대 {round(v * 100)}%", "what_ko": "손절 한 번"})
    v = _i(risk.get("max_leverage"))
    if v:
        out.append({"key": "max_leverage", "value": v, "ko": f"최대 {v}배", "what_ko": "최대 배수"})
    v = _f(risk.get("max_notional_usd"))
    if v:
        out.append({"key": "max_notional_usd", "value": v, "ko": f"포지션 크기 최대 ${v:,.0f}", "what_ko": "포지션 크기"})
    syms = risk.get("allowed_symbols")
    if isinstance(syms, list) and syms:
        names = [str(s).upper().replace("USDT", "") for s in syms]
        out.append({"key": "allowed_symbols", "value": names, "ko": f"코인 {len(names)}개만 ({' · '.join(names)})", "what_ko": "코인"})
    b = _f(budget)
    if b:
        out.append({"key": "budget_usd", "value": b, "ko": f"정한 금액 ${b:,.0f}", "what_ko": "정한 금액"})
    return out


def size_ko(cfg: Optional[dict]) -> str:
    """How an executor sizes its entries, in the owners' words (executor.ExecConfig ``size_from``): "equity" (owners 10-25
    night: each entry's margin = ``margin_frac`` of the live balance; qty_scale stays in the file, unused for size) "진입할
    때마다 실거래 잔고의 40%를 증거금으로", else "paper" "실거래 크기 = 페이퍼 수량 × 0.1" (its qty_scale)."""
    c = cfg or {}
    if c.get("size_from") == "equity":
        mf = _f(c.get("margin_frac"))
        return f"진입할 때마다 실거래 잔고의 {mf:.0%}를 증거금으로" if mf else "진입할 때마다 실거래 잔고로 증거금을 정해요 (margin_frac 없음)"
    qs = _f(c.get("qty_scale"))
    return f"실거래 크기 = 페이퍼 수량 × {qs:g}" if qs is not None else "실거래 크기 = 페이퍼 수량 × (qty_scale 없음)"


def size_scale(cfg: Optional[dict], live_qty: Any = None, paper_qty: Any = None) -> Optional[float]:
    """The factor a paper trade's P&L is multiplied by to set it next to the live trade that followed it: the config's
    qty_scale (size_from "paper"); for size_from "equity" (qty_scale unused for size) that trade's own live qty / paper qty
    (both rows carry ``qty``). None when it cannot be told (never a made-up 1)."""
    c = cfg or {}
    if c.get("size_from") == "equity":
        lq, pq = _f(live_qty), _f(paper_qty)
        return lq / pq if lq and pq else None
    return _f(c.get("qty_scale")) or None


def read_config(path: str) -> dict:
    """The few settings this page needs from an executor config: account, paper_db, db, exchange, mode, the light, the
    size ratio (and how it sizes: ``size_from`` / ``margin_frac``, size_ko), the risk limits it really has, the kill file.
    Nothing else of the file is passed on."""
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        return _missing(path, "실행기 설정 파일이 아직 없어요")
    except ValueError as exc:
        return {**_err(path, exc), "reason_ko": "실행기 설정 파일이 JSON 모양이 아니에요"}
    except OSError as exc:
        return _err(path, exc)
    if not isinstance(raw, dict):
        return {"state": "error", "path": path, "reason": "not an object", "reason_ko": "실행기 설정 파일의 모양이 달라요"}
    risk = raw.get("risk") if isinstance(raw.get("risk"), dict) else {}
    n = _i(raw.get("signal_light_n"))
    mw = _f(raw.get("signal_light_min_win"))
    kill = risk.get("kill_file") if isinstance(risk.get("kill_file"), str) else None
    out = {"state": "ok", "path": path,
           "account": raw.get("account") if isinstance(raw.get("account"), str) else None,
           "paper_db": raw.get("paper_db") if isinstance(raw.get("paper_db"), str) else None,
           "db": raw.get("db") if isinstance(raw.get("db"), str) else None,
           "exchange": raw.get("exchange") if isinstance(raw.get("exchange"), str) else "binance",
           "mode": raw.get("mode") if isinstance(raw.get("mode"), str) else None,
           "entry_source": raw.get("entry_source") if isinstance(raw.get("entry_source"), str) else "paper",
           "ladder_from": raw.get("ladder_from") if raw.get("ladder_from") in ("paper", "own") else "paper",
           "signal_light_n": LIGHT_N_DEFAULT if n is None else n,
           "signal_light_min_win": LIGHT_MIN_DEFAULT if mw is None else mw,
           "qty_scale": _f(raw.get("qty_scale")), "budget_usd": _f(raw.get("budget_usd")),
           "size_from": raw.get("size_from") if isinstance(raw.get("size_from"), str) else "paper",
           "margin_frac": _f(raw.get("margin_frac")),
           "max_consecutive_losses": _i(risk.get("max_consecutive_losses")),
           "limits": risk_limits(risk, raw.get("budget_usd"), raw.get("size_from")), "kill_file": None}
    if kill:
        try:
            present = os.path.exists(kill)
        except OSError:
            present = None
        out["kill_file"] = {"path": kill, "present": present}
    if isinstance(raw.get("label"), str) and raw["label"].strip():     # its own name (owners 10-24); else nothing new
        out["label"] = raw["label"].strip()
    out["size_ko"] = size_ko(out)
    out["limits"] += fixed_rules(raw)          # owners 10-25 night: only a config that has them; else nothing new
    return out


def fixed_rules(raw: dict) -> list:
    """An executor config's fixed leverage (``leverage_by_symbol``: {"BTCUSDT": 40, "*": 30}), fixed take-profit
    (``take_profit_roe``: 0.15, with ``ladder_from`` "own"), stop scale (``stop_scale``: 1.25), liquidation guard
    (``liq_guard``) and US-release block (``macro_block_min``) (owners 10-25 night, the Toobit executor) as more entries
    of its limits, in the owners' words; [] for a config without them (every other executor: as before)."""
    out = []
    m = raw.get("leverage_by_symbol")
    if isinstance(m, dict) and m:
        named = [f"{str(k).upper().replace('USDT', '')} {_i(v)}배" for k, v in m.items() if k != "*" and _i(v)]
        rest = _i(m.get("*"))
        words = " · ".join(named + ([f"{'나머지' if named else '모든 코인'} {rest}배"] if rest else []))
        if words:
            out.append({"key": "leverage_by_symbol", "value": dict(m), "ko": f"배수 고정: {words} (페이퍼 배수 대신)",
                        "what_ko": "고정 배수"})
    tp = _f(raw.get("take_profit_roe"))
    if tp and raw.get("ladder_from") == "own":
        roe = "화면 ROE" if raw.get("ladder_basis") == "gross" else "순ROE"
        tail = "계단 없음" if raw.get("ladder") is None else "계단도 함께"
        out.append({"key": "take_profit_roe", "value": tp, "ko": f"익절: {roe} +{tp * 100:g}%에서 시장가로 전부 닫음 ({tail})",
                    "what_ko": "고정 익절"})
    s = _f(raw.get("stop_scale"))              # owners 10-25 night, later: "손절 2.5 ATR로"
    if s and raw.get("stop_from", "ratio") == "ratio":
        out.append({"key": "stop_scale", "value": s, "ko": f"손절: 페이퍼 손절 거리 × {s:g} (2 ATR → {2 * s:g} ATR), 자기 체결가 기준",
                    "what_ko": "손절 거리"})
    if raw.get("liq_guard") is True:
        out.append({"key": "liq_guard", "value": True, "ko": "손절이 강제청산 가격보다 멀면 그 진입은 안 함 (놓친 신호, 알람 아님)",
                    "what_ko": "청산가 확인"})
    mb = _i(raw.get("macro_block_min"))
    if mb:
        out.append({"key": "macro_block_min", "value": mb, "ko": f"미국 경제 발표(CPI·FOMC·NFP·PCE) 앞뒤 {mb}분 새 진입 안 함",
                    "what_ko": "경제 발표"})
    uo = us_open_window(raw)                    # owners 10-26: the NYSE open too (us_open_pre_min / us_open_pause_min)
    if uo:
        out.append({"key": "us_open", "value": list(uo), "ko": f"{us_open_words(*uo)} 새 진입 안 함", "what_ko": "나스닥 개장"})
    return out


def us_open_window(raw: Any) -> Optional[tuple]:
    """An executor config's (minutes before, minutes after) the NYSE open with no new entry (``us_open_pre_min``,
    ``us_open_pause_min``: ints 1..240 or null; owners 10-26), or None (off, or a value its check-config refuses: the
    executor's own us_open_window rule, read here from the config dict)."""
    vals = []
    for k in ("us_open_pre_min", "us_open_pause_min"):
        m = raw.get(k) if isinstance(raw, dict) else None
        if m is not None and (isinstance(m, bool) or not isinstance(m, int) or not 1 <= m <= 240):
            return None
        vals.append(int(m or 0))
    return tuple(vals) if any(vals) else None


def us_open_words(pre: int, post: int) -> str:
    """"나스닥 개장 앞 30분·뒤 30분" (combo.us_open_ko's words)."""
    parts = ([f"앞 {pre}분"] if pre else []) + ([f"뒤 {post}분"] if post else [])
    return "나스닥 개장 " + "·".join(parts)


# ---------------------------------------------------------------- the paper bot (paperbot.store3 tables)
def _paper_trade(r: tuple) -> dict:
    tid, sym, et, xt, why, lev, pnl, roe, eq, data = r
    d = _j(data)
    return {"id": _i(tid), "symbol": sym, "side": _i(d.get("side")), "entry_time": _i(et), "exit_time": _i(xt),
            "exit_reason": why, "leverage": _i(lev), "pnl": _f(pnl), "roe": _f(roe), "equity_after": _f(eq),
            "entry_price": _f(d.get("entry_price")), "exit_price": _f(d.get("exit_price")), "qty": _f(d.get("qty")),
            "margin": _f(d.get("margin")), "fees": _f(d.get("fees")), "funding": _f(d.get("funding")),
            "strategy_id": d.get("strategy_id"), "timeframe": d.get("timeframe"), "lock_roe": _f(d.get("lock_roe")),
            "stop_initial": _f(d.get("stop_initial")), "stop_price": _f(d.get("stop_price")), "liq_price": _f(d.get("liq_price")),
            # the trend bot's supervisor writes why it closed (감독 청산: 추세 뒤집힘 / 시간 정리) into the trade's context
            "exit_why": (d.get("context") or {}).get("exit_why") if isinstance(d.get("context"), dict) else None}


def round_trip(taker_fee: Any) -> float:
    """The paper rules' round-trip cost as a share of notional (taker fee + slippage, both ways), as the engine's ladder
    uses it (the dashboard's Data._round_trip)."""
    from ...config import v3_settings
    fee = _f(taker_fee)
    return v3_settings(**({"taker_fee": fee} if fee else {})).round_trip_cost


def next_lock(lock_roe: Optional[float], ladder: dict) -> Optional[dict]:
    """The next ladder step: the net ROE that arms it and the lock it sets (paperbot/ladder2.py ComboLadder.next_after:
    both forms, the rule bot's 'every step' and the two-part one with next_trigger / next_gap). None when the config's
    ladder lacks first_lock, step or trigger_gap."""
    from ...ladder2 import ComboLadder
    spec = ComboLadder.of(ladder)
    if spec is None:
        return None
    lock, at = spec.next_after(lock_roe)
    return {"lock": lock, "at": at}


LADDER_KEYS = ("first_lock", "step", "trigger_gap")     # every form (paperbot/ladder2.py ComboLadder)
LADDER_KEYS2 = ("next_trigger", "next_gap")             # the two-part form only


def ladder_numbers(lad: Optional[dict]) -> dict:
    """A config's ladder for the page: first_lock, step, trigger_gap (None when missing), plus next_trigger and next_gap
    only when the config has both (the two-part form; an old config's answer keeps its three keys)."""
    lad = lad if isinstance(lad, dict) else {}
    out = {k: _f(lad.get(k)) for k in LADDER_KEYS}
    two = {k: _f(lad.get(k)) for k in LADDER_KEYS2}
    if None not in two.values():
        out.update(two)
    return out


def roe_price(side: int, entry: Optional[float], lev: Optional[int], roe: float, rt: float = 0.0, ff: float = 0.0) -> Optional[float]:
    """The price at which the paper's net ROE reaches ``roe`` (paperbot/ladder.py: entry x (1 + side x (roe / lev + round
    trip + funding / notional)))."""
    if not entry or not lev or not side:
        return None
    return entry * (1 + side * (roe / lev + rt + ff))


def _paper_position(aid: str, e: dict, rt: float, ladder: dict) -> Optional[dict]:
    p = e.get("position") if isinstance(e.get("position"), dict) else None
    if not p:
        return None
    sig = p.get("signal") if isinstance(p.get("signal"), dict) else {}
    meta = sig.get("meta") if isinstance(sig.get("meta"), dict) else {}
    sym, side = p.get("symbol"), _i(p.get("side")) or 0
    qty, entry, lev = _f(p.get("qty")), _f(p.get("entry_price")), _i(p.get("leverage"))
    fund = _f(p.get("funding_paid")) or 0.0
    notional = (qty or 0) * (entry or 0)
    ff = fund / notional if notional else 0.0
    mark = _f((e.get("last_mark") or {}).get(sym)) if isinstance(e.get("last_mark"), dict) else None
    roe = lev * (side * (mark / entry - 1.0) - rt - ff) if (mark and entry and lev) else None
    lock = _f(p.get("lock_roe"))
    nx = next_lock(lock, ladder)
    if nx:
        nx["price"] = roe_price(side, entry, lev, nx["at"], rt, ff)
        nx["lock_price"] = roe_price(side, entry, lev, nx["lock"], rt, ff)
        nx["then"] = next_lock(nx["lock"], ladder)       # the step after it (the gauge's 그다음; two-part: 15 % -> 12 %)
    return {"key": f"{aid}|{sym}|{_i(p.get('entry_time'))}", "symbol": sym, "side": side, "qty": qty, "leverage": lev,
            "entry": entry, "entry_time": _i(p.get("entry_time")), "stop": _f(p.get("stop_price")),
            "stop_initial": _f(p.get("stop_initial")), "lock_roe": lock, "locked": lock is not None,
            "liq": _f(p.get("liq_price")), "margin": _f(p.get("margin_initial")) or _f(p.get("margin")), "funding_paid": fund,
            "funding_frac": ff, "round_trip": rt, "last_mark": mark, "last_mark_roe_net": roe, "next_lock": nx,
            "strategy_id": sig.get("strategy_id"), "timeframe": sig.get("timeframe"), "member": meta.get("member"),
            "member_order": _i(meta.get("member_order")), "stop_rule": meta.get("stop_rule"), "status": "open"}


def read_paper(path: str, accounts: Iterable[str], now_ms: int) -> dict:
    """The paper database: each asked account's engine state and closed trades, the run's settings (one snapshot)."""
    accounts = list(dict.fromkeys(accounts))
    try:
        conn = open_ro(path)
    except FileNotFoundError:
        return _missing(path)
    except (OSError, sqlite3.Error) as exc:
        return _err(path, exc)
    try:
        conn.execute("BEGIN")
        tables = _tables(conn)
        if not {"state", "trades"} <= tables:
            return _missing(path, NO_TABLE_KO)
        st = conn.execute("SELECT ts, data FROM state WHERE k = 'accounts'").fetchone()
        run = conn.execute("SELECT ts, data FROM state WHERE k = 'combo_run'").fetchone()
        created = {}
        if "accounts" in tables:
            created = {a: _i(t) for a, t in conn.execute("SELECT account_id, created_ts FROM accounts")}
        rows = {a: [_paper_trade(r) for r in conn.execute(
            "SELECT id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, equity_after, data FROM trades "
            "WHERE account_id = ? ORDER BY exit_time, id", (a,))] for a in accounts}
    except sqlite3.Error as exc:
        return _err(path, exc)
    finally:
        conn.close()
    ts = _i(st[0]) if st else None
    engines = _j(st[1]).get("engines") if st else None
    engines = engines if isinstance(engines, dict) else {}
    run_d = _j(run[1]) if run else {}
    cfg = run_d.get("config") if isinstance(run_d.get("config"), dict) else {}
    rt = round_trip(run_d.get("taker_fee"))
    ladder = cfg.get("ladder") if isinstance(cfg.get("ladder"), dict) else {}
    init_cfg = _f(cfg.get("initial_equity"))
    out_acc = {}
    for a in accounts:
        e = engines.get(a) if isinstance(engines.get(a), dict) else None
        trades = rows.get(a, [])
        first = trades[0] if trades else None
        initial = init_cfg if init_cfg is not None else (
            first["equity_after"] - first["pnl"] if first and first["equity_after"] is not None and first["pnl"] is not None else None)
        curve = []
        if trades and initial is not None:
            curve.append([first["entry_time"], initial])
            curve += [[t["exit_time"], t["equity_after"]] for t in trades if t["equity_after"] is not None]
        out_acc[a] = {
            "account": a, "known": e is not None or bool(trades), "since_ms": created.get(a),
            "wallet": _f(e.get("wallet")) if e else None, "initial": initial,
            "halted": bool(e.get("halted")) if e else None, "halt_reason": (e or {}).get("halt_reason") or "",
            "bust": bool(e.get("bust")) if e else None, "max_drawdown": _f(e.get("max_drawdown")) if e else None,
            "position": _paper_position(a, e, rt, ladder) if e else None,
            "stats": {**stats(t["pnl"] for t in trades), "fees": sum(t["fees"] or 0 for t in trades),
                      "funding": sum(t["funding"] or 0 for t in trades)},
            "curve": thin(curve), "trades": trades,
        }
    return {"state": "ok", "path": path, "as_of_ms": ts, "stale": ts is None or now_ms - ts > PAPER_STALE_MS,
            # the config's name; the trend bot's without one is still the trend bot (never the old A+C label)
            "name_ko": cfg.get("name") if isinstance(cfg.get("name"), str) and cfg.get("name")
            else TREND_NAME_KO if cfg.get("trend") is not None else None, "round_trip": rt,
            "stop": cfg.get("stop") if isinstance(cfg.get("stop"), dict) else None,
            "ladder": ladder_numbers(ladder) if ladder else None,
            "leverage": cfg.get("leverage") if isinstance(cfg.get("leverage"), dict) else None, "margin": _f(cfg.get("margin")),
            "taker_fee": _f(run_d.get("taker_fee")), "started_ms": _i(run[0]) if run else None, "accounts": out_acc,
            # the whole config the bot runs, for this module's own words (its TIME exit, twins): never sent to a page
            "_cfg": cfg}


def cfg_of(read: Optional[dict]) -> dict:
    """The config of the paper bot behind a read_paper answer (its start record ``combo_run``), {} when unknown."""
    c = (read or {}).get("_cfg") if (read or {}).get("state") == "ok" else None
    return c if isinstance(c, dict) else {}


def no_private(d: dict) -> dict:
    """A read_paper answer without what is only for this module (``_cfg``)."""
    return {k: v for k, v in d.items() if not str(k).startswith("_")}


def hold_bot(cfg: Optional[dict]) -> bool:
    """A bot whose TIME exit is its hold limit (``max_hold_bars``, no trend supervisor: the 'VWAP 개선판')."""
    return LP.time_exit_ko(cfg) == LP.TIME_HOLD_KO


def exit_words(reason: Any, cfg: Optional[dict] = None, why: Any = None) -> str:
    """A paper exit reason in words by the bot that made it (livepapers.exit_ko with EXIT_KO): TIME is the trend bot's
    감독 청산(시간 정리), or a hold-limit bot's 보유 한도 청산 with its why ("96봉(48시간) 지남", combo.exit_text's words).
    Without a config (or for any other reason) EXIT_KO's word, as always."""
    words = LP.exit_ko(reason, cfg, EXIT_KO)
    if reason == "TIME" and hold_bot(cfg) and isinstance(why, str) and why:
        return f"{words}({why})"
    return words


# ---------------------------------------------------------------- the order executors (executor.py tables)
def parse_key(key: Any) -> Optional[tuple]:
    """'COMBO@mix|BTCUSDT|1760000000000' -> (account, symbol, paper entry ms); None for another shape."""
    if not isinstance(key, str):
        return None
    parts = key.rsplit("|", 2)
    if len(parts) != 3:
        return None
    t = _i(parts[2])
    return (parts[0], parts[1], t) if t is not None else None


def live_exit(reason: Any, data: dict, side: int, entry: Optional[float]) -> str:
    """What closed an executor trade, from its own words (executor.py _finish reasons): its exchange stop firing (a stop
    already on the profit side of the entry is a lock: 잠금 익절), following the paper's close (the paper's reason is
    added by the caller when the paper trade is known), a halt, or something else."""
    r = str(reason or "")
    stop = _f(data.get("stop"))
    locked = bool(stop and entry and side and (stop - entry) * side > 0)
    if data.get("exit_code") == "TP" or r.startswith("고정 익절"):
        return "TP"                    # 고정 익절 (owners 10-25 night, take_profit_roe): closed at market at its +15 %
    if "발동" in r or "이미 지나" in r:
        return "LOCK" if locked else "SL"
    if "paper 청산" in r:
        return "PAPER"
    if "멈" in r or "비상" in r or "정지" in r:
        return "HALT"
    return "OTHER"


def _live_trade(d: dict) -> dict:
    data = _j(d.get("data"))
    k = parse_key(d.get("key"))
    side = _i(d.get("side")) or 0
    entry, qty, lev, pnl = _f(d.get("entry_price")), _f(d.get("qty")), _i(d.get("leverage")), _f(d.get("pnl"))
    margin = entry * qty / lev if entry and qty and lev else None
    src = d.get("pnl_source") or "wallet"
    return {"key": d.get("key"), "symbol": d.get("symbol"), "side": side, "qty": qty, "leverage": lev,
            "entry_ts": _i(d.get("entry_ts")), "entry_price": entry, "stop_initial": _f(d.get("stop_initial")),
            "stop_final": _f(data.get("stop")), "exit_ts": _i(d.get("exit_ts")), "exit_raw": d.get("exit_reason"),
            "exit_reason": live_exit(d.get("exit_reason"), data, side, entry) if d.get("exit_ts") else None,
            "exit_ref": _f(data.get("exit_ref")), "pnl": pnl, "margin": margin,
            "roe": pnl / margin if pnl is not None and margin else None, "pnl_source": src, "est": src != "fills",
            "commission": _f(d.get("commission")), "funding": _f(d.get("funding")), "slippage": _f(d.get("slippage")),
            "paper_entry": _f(data.get("paper_entry")), "paper_time": k[2] if k else (_i(data.get("entry_time")) or _i(d.get("entry_ts"))),
            "account": k[0] if k else None}


def _own_view(t: dict) -> Optional[dict]:
    """An executor's "own" ladder record of its open trade (executor.py ``_own_state``, owners 10-20 "거래소 기준"): the
    lock it reached on its own position, its best price and net ROE (its own exchange's 1m candles), the next step,
    the costs and the ladder it is judged with, and whether it stays open after the paper's price exit. None for a
    trade that follows the paper's lock steps."""
    o = t.get("own")
    if not isinstance(o, dict):
        return None
    nx = o.get("next") if isinstance(o.get("next"), dict) else None
    px = t.get("paper_exit") if isinstance(t.get("paper_exit"), dict) else {}
    cost = o.get("cost") if isinstance(o.get("cost"), dict) else {}
    return {"lock": _f(o.get("lock")), "lock_price": _f(o.get("lock_price")), "best": _f(o.get("best")),
            "best_roe": _f(o.get("best_roe")), "src": o.get("src") if isinstance(o.get("src"), str) else None,
            "round_trip": _f(o.get("rt")), "cost_round_trip": _f(o.get("cost_rt")) if o.get("cost_rt") is not None
            else _f(o.get("rt")), "basis": "gross" if o.get("basis") == "gross" else "net",
            "taker_fee": _f(cost.get("taker_fee")), "slippage": _f(cost.get("slippage")),
            "exchange": o.get("exchange") if isinstance(o.get("exchange"), str) else None,
            "ladder": o.get("ladder") if isinstance(o.get("ladder"), dict) else None,
            "tp": _f(o.get("tp")),          # 고정 익절 (take_profit_roe, the 레인지 봇's executor): its own net ROE
            "next": {k: _f(nx.get(k)) for k in ("lock", "at", "price", "lock_price")} if nx else None,
            "staying": px.get("action") == "stay", "paper_reason": px.get("reason") if px.get("action") == "stay" else None,
            "paper_exit_time": _i(px.get("exit_time")) if px.get("action") == "stay" else None}


def _live_position(t: Optional[dict]) -> Optional[dict]:
    if not isinstance(t, dict) or t.get("status") not in ("open", "entering"):
        return None
    side, entry, stop = _i(t.get("side")) or 0, _f(t.get("entry_price")), _f(t.get("stop"))
    qty, lev = _f(t.get("qty")), _i(t.get("leverage"))
    own = _own_view(t)
    return {"key": t.get("key"), "status": t.get("status"), "symbol": t.get("symbol"), "side": side, "qty": qty,
            "leverage": lev, "entry": entry, "entry_time": _i(t.get("entry_ts")), "stop": stop,
            "stop_initial": _f(t.get("stop_initial")), "locked": bool(entry and stop and (stop - entry) * side > 0),
            "lock_roe": own["lock"] if own else None, "liq": None,
            "margin": entry * qty / lev if entry and qty and lev else None,
            "stop_order": t.get("stop_algo_id"), "paper_entry": _f(t.get("paper_entry")),
            "paper_time": (parse_key(t.get("key")) or (None, None, _i(t.get("entry_time"))))[2], "own": own}


def read_exec(path: str, now_ms: int) -> dict:
    """One executor's database: its saved state (halt, open trade, last equity), closed trades, equity samples, halts and
    its WARN / CRITICAL events (one snapshot)."""
    try:
        conn = open_ro(path)
    except FileNotFoundError:
        return _missing(path)
    except (OSError, sqlite3.Error) as exc:
        return _err(path, exc)
    try:
        conn.execute("BEGIN")
        tables = _tables(conn)
        if not {"state", "events", "trades"} <= tables:
            return _missing(path, NO_TABLE_KO)
        bot = conn.execute("SELECT ts, data FROM state WHERE k = 'bot'").fetchone()
        meta = conn.execute("SELECT data FROM state WHERE k = 'meta'").fetchone()
        have = _cols(conn, "trades")
        cols = [c for c in EXEC_TRADE_COLS if c in have]
        cur = conn.execute(f"SELECT {', '.join(cols)} FROM trades ORDER BY entry_ts, key")
        trades = [dict(zip(cols, r)) for r in cur.fetchall()]
        eq = []
        if "equity" in tables:
            tcol = "COALESCE(transfers, 0)" if "transfers" in _cols(conn, "equity") else "0"
            eq = conn.execute(f"SELECT ts, equity, wallet, {tcol} FROM equity ORDER BY ts").fetchall()
        halts = conn.execute("SELECT ts, action, reason FROM halts ORDER BY id").fetchall() if "halts" in tables else []
        events = conn.execute("SELECT id, ts, level, kind, text FROM events WHERE level IN ('WARN', 'CRITICAL') "
                              "AND kind != 'retry' ORDER BY id DESC LIMIT ?", (EVENTS_KEEP,)).fetchall()
        why = conn.execute("SELECT id, ts, level, kind, text, data FROM events WHERE kind IN "
                           f"({', '.join('?' * len(WHY))}) ORDER BY id DESC LIMIT ?", (*WHY_KO, WHY_SCAN)).fetchall()
        retry = conn.execute("SELECT COUNT(*) FROM events WHERE kind = 'retry' AND ts >= ?", (now_ms - DAY,)).fetchone()[0]
        first_start = conn.execute("SELECT MIN(ts) FROM events WHERE kind = 'start'").fetchone()[0]
        starts = LP.starts_of(conn)                      # which paper database each start followed (livepapers)
    except sqlite3.Error as exc:
        return _err(path, exc)
    finally:
        conn.close()
    st = _j(bot[1]) if bot else {}
    meta_d = _j(meta[0]) if meta else {}
    risk = st.get("risk") if isinstance(st.get("risk"), dict) else {}
    ts = _i(bot[0]) if bot else None
    live = [_live_trade(t) for t in trades]
    closed = [t for t in live if t["exit_ts"] is not None and t["pnl"] is not None]
    pos = _live_position(st.get("trade"))
    by_key: dict = {}
    for _id, ets, lvl, kind, text, data in why:          # newest first: the first seen per key and kind is the latest
        k = _j(data).get("key")
        if isinstance(k, str):
            if kind == "entry_check" and lvl == "INFO":
                continue                                    # an entry check that passed is not a reason
            by_key.setdefault(k, {}).setdefault(kind, {"ts": _i(ets), "text": text})
    eqs = [(_i(r[0]), _f(r[1]), _f(r[2]), _f(r[3]) or 0.0) for r in eq if _f(r[1]) is not None]
    first_eq = eqs[0] if eqs else None
    last_eq = _f(risk.get("last_equity"))
    if last_eq is None and eqs:
        last_eq = eqs[-1][1]
    # the change since the first recorded balance, deposits and withdrawals left out (executor.equity 'transfers')
    base = None
    if first_eq is not None:
        base = first_eq[1] + ((_f(risk.get("transfers")) if risk.get("transfers") is not None else eqs[-1][3]) - first_eq[3])
    return {
        "state": "ok", "path": path, "as_of_ms": ts, "stale": ts is None or now_ms - ts > EXEC_STALE_MS,
        "mode": st.get("mode") or meta_d.get("mode"), "account": st.get("account") or meta_d.get("account"),
        "exchange": meta_d.get("exchange") or ("binance" if meta_d else None),
        "since_ms": _i(meta_d.get("live_since")) or _i(first_start) or _i(meta_d.get("since")),
        "halted": bool(risk.get("halted")), "halt_reason": risk.get("halt_reason") or "", "halted_ts": _i(risk.get("halted_ts")),
        "consecutive_losses": _i(risk.get("consecutive_losses")),
        "last_equity": last_eq, "first_equity": first_eq[1] if first_eq else None, "first_equity_ts": first_eq[0] if first_eq else None,
        "base_equity": base, "equity_ts": eqs[-1][0] if eqs else None,
        "position": pos,
        "stats": {**stats(t["pnl"] for t in closed), "commission": sum(t["commission"] or 0 for t in closed),
                  "funding": sum(t["funding"] or 0 for t in closed), "estimated": sum(1 for t in closed if t["est"])},
        "curve": thin([[t, e - (tr - (first_eq[3] if first_eq else 0.0))] for t, e, _w, tr in eqs]),
        "trades": closed, "halts": [{"ts": _i(r[0]), "action": r[1], "reason": r[2]} for r in halts],
        "events": [{"id": _i(i), "ts": _i(t), "level": lvl, "kind": k, "kind_ko": KIND_KO.get(k, k), "level_ko": LEVEL_KO.get(lvl, lvl),
                    "text": txt} for i, t, lvl, k, txt in events],
        "retry_24h": int(retry or 0), "why": by_key, "starts": [[t, pdb] for t, pdb in starts],
    }


# ---------------------------------------------------------------- 페이퍼 vs 실거래 (the matching every tab uses)
def match(paper: list, live: list, window: int = MATCH_MS) -> dict:
    """{live key: paper trade id}: same coin, same side, paper entry time within ``window``; the closest pairs first, each
    trade used once."""
    cand = []
    for lt in live:
        if lt.get("paper_time") is None:
            continue
        for pt in paper:
            if pt.get("symbol") == lt.get("symbol") and pt.get("side") == lt.get("side") and pt.get("entry_time") is not None:
                gap = abs(int(pt["entry_time"]) - int(lt["paper_time"]))
                if gap <= window:
                    cand.append((gap, str(lt.get("key")), pt["id"]))
    out, used = {}, set()
    for gap, lk, pid in sorted(cand):
        if lk in out or pid in used:
            continue
        out[lk] = pid
        used.add(pid)
    return out


# ---------------------------------------------------------------- the three accounts of the terminal
def hours_of(trades: list, t_key: str = "exit_time") -> list:
    """[[hour END ms, realized P&L, trades, wins, losses]] of the hours in which something closed (dash/more/termpnl.py's
    rule: a close at exactly 13:00:00 belongs to the hour ending 13:00; a win is pnl > 0, a loss pnl < 0)."""
    by: dict = {}
    for t in trades:
        ts, p = _i(t.get(t_key)), _f(t.get("pnl"))
        if ts is None or p is None:
            continue
        e = -(-ts // HOUR) * HOUR
        b = by.setdefault(e, [e, 0.0, 0, 0, 0])
        b[1] += p
        b[2] += 1
        b[3] += 1 if p > 0 else 0
        b[4] += 1 if p < 0 else 0
    return [by[k] for k in sorted(by)]


def calendar_of(trades: list, key: str, since: Optional[int], now: int, t_key: str = "exit_time") -> dict:
    """The current Korea-time month as the terminal's 수익 캘린더 reads it (dash/more/flow.py calendar shape): every day with
    ``state`` future / empty (before the account's first record: no record, never a zero) / done / today, and for a day
    with a record ``g[key] = {pnl, trades, wins}`` of the trades that closed that day."""
    today = kst_day(now)
    epoch = _dt.date(1970, 1, 1)
    d = epoch + _dt.timedelta(days=today)
    first = (_dt.date(d.year, d.month, 1) - epoch).days
    last = ((_dt.date(d.year + 1, 1, 1) if d.month == 12 else _dt.date(d.year, d.month + 1, 1)) - epoch).days - 1
    by: dict = {}
    for t in trades:
        ts, p = _i(t.get(t_key)), _f(t.get("pnl"))
        if ts is None or p is None:
            continue
        g = by.setdefault(kst_day(ts), {"pnl": 0.0, "trades": 0, "wins": 0})
        g["pnl"] += p
        g["trades"] += 1
        g["wins"] += 1 if p > 0 else 0
    start = kst_day(since) if since else None
    days = []
    for kd in range(first, last + 1):
        e = {"d": time.strftime("%Y-%m-%d", time.gmtime(kd * 86_400)), "ts": kst_day_start(kd), "dow": (kd + 3) % 7}
        if kd > today:
            e["state"] = "future"
        elif (start is None or kd < start) and kd not in by:
            e["state"] = "empty"
        else:
            e["state"] = "today" if kd == today else "done"
            e["g"] = {key: by.get(kd, {"pnl": 0.0, "trades": 0, "wins": 0})}
        days.append(e)
    return {"ready": True, "now": now, "today": time.strftime("%Y-%m-%d", time.gmtime(today * 86_400)), "keys": [key], "days": days}


def today_of(trades: list, now: int, t_key: str = "exit_time") -> dict:
    t0 = kst_day_start(kst_day(now))
    xs = [t for t in trades if (_i(t.get(t_key)) or 0) >= t0 and _f(t.get("pnl")) is not None]
    return {"trades": len(xs), "wins": sum(1 for t in xs if t["pnl"] > 0), "losses": sum(1 for t in xs if t["pnl"] < 0),
            "pnl": sum(t["pnl"] for t in xs), "from_ms": t0}


def checkpoint(trades: list, rule_ko: str = "") -> dict:
    """Progress to the owners' 40-trade look (paper closed trades of this database). Nothing is judged before 40.
    ``rule_ko`` (ref_problem: the 5-year reference, and with it the 88 % / 82 % rule, is another config's): the count
    only, no rule and no zone, and ``rule_ko`` says why."""
    st = stats(t.get("pnl") for t in trades)
    n, goal = st["trades"], CHECKPOINT["trades"]
    rule = {k: None for k in ("up", "low", "up_ko", "mid_ko", "low_ko")} if rule_ko else {}
    out = {**CHECKPOINT, **rule, "n": n, "left": max(0, goal - n), "win_rate": st["win_rate"], "ready": n >= goal, "zone": None}
    if rule_ko:
        out["rule_ko"] = rule_ko
    if n >= goal:
        last = [t.get("pnl") for t in trades[-goal:]]
        w = sum(1 for p in last if (_f(p) or 0) > 0) / goal
        out["last_win_rate"] = w
        if not rule_ko:
            out["zone"] = "up" if w >= CHECKPOINT["up"] - 1e-9 else "mid" if w >= CHECKPOINT["low"] - 1e-9 else "low"
    return out


def ref_problem(paper_path: Optional[str] = None) -> str:
    """'' when the 5-year reference (deploy/combo.live-ac.expected.json) may be shown against the live bot, else the
    guard's Korean reason (livecheck.ref_config_problem: made for another config than PAPERBOT_LIVE_COMBO_CONFIG's file).
    The start guide's reference lines (REFS) and the owners' 40-trade rule (CHECKPOINT) are that old config's too: they
    go with it. A reference that cannot be read says nothing here (its own readers say so). The trend bot running at
    ``paper_path`` (default: PAPERBOT_LIVE_PAPER_DB): never usable (TREND_NO_REF_KO; a new rule set has no backtest)."""
    from ... import livecheck as LC
    from ... import liveimprove as LI
    if trend_bot(paper_path or paths()["paper"]) is not None:
        return TREND_NO_REF_KO
    try:
        LI.load_ref(combo_config=paths_more()["combo_config"])
    except LC.RefConfigMismatch as exc:
        return str(exc)
    except (OSError, ValueError):
        return ""
    return ""


# ---------------------------------------------------------------- 추세판단 봇 (owners 10-21, docs/trend-bot-ko.md)
TREND_NAME_KO = "추세판단 봇"
TREND_FREEZE_DAYS = 14                 # owners 10-21 (#13 추천대로): the rules stay 2 weeks from the start, then the review
# a new, untested rule set: no backtest, no start guide lines, no 88 % / 82 % rule (the owners decide at the review)
TREND_NO_REF_KO = "새 규칙이라 비교할 백테스트 기준이 없어요 · 2주 뒤 검토"
TREND_RULE_KO = "새 규칙이라 88%·82% 같은 판단 기준이 없어요 · 2주 뒤 검토에서 두 분이 정해요"
# the entry members' roles (owners 10-21: 눌림 · 자리 · 돌파 · 횡보; 10-22: 추세 for F7_RF_TRIPLE), in their words
# (livetrend.ROLE is this); the 10-21 design's members stay so their trades still show a role
TREND_ROLE = {"N08_ICHI_WR": "눌림", "F9_FVG": "눌림", "V39_ALL": "눌림", "N05_PSAR_POC": "자리", "F9_IFVG": "자리", "F9_OB": "자리",
              "F16_FIB382": "자리", "F16_FIB500": "자리", "F16_FIB618": "자리", "F16_FIB764": "자리", "F6_VWAP_FAIL": "자리",
              "F10_OTE": "자리", "F3_BOS": "돌파", "F15_ORB": "돌파", "N06_MACD_ORB": "돌파", "S3_CMO_SANDWICH": "횡보",
              "N20_EMA9_CHOP": "횡보", "F7_RF_TRIPLE": "추세"}
TREND_ROLES = ("눌림", "자리", "돌파", "횡보", "추세")
TREND_ROLE_SUB_KO = {"눌림": "추세 속 되돌림에서 들어가는 매매법", "자리": "가격이 모인 자리에서 들어가는 매매법",
                     "돌파": "추세 초입의 돌파 (상위 ADX 30 미만이고 오를 때만)", "횡보": "쉬던 가격이 움직일 때 들어가는 매매법",
                     "추세": "레인지 필터·하이킨아시·상위 봉 하이킨아시 방향이 처음 같이 맞춰질 때 따라 들어가는 매매법"}
TREND_HTF = {"30m": "1h", "1h": "4h", "4h": "1d"}  # the entry bar -> the closed higher bar its trend is judged on (4h: 10-22)
TREND_TF_KO = {"30m": "30분 진입", "1h": "1시간 진입", "4h": "4시간 진입"}
TREND_TF_SUB_KO = {"30m": "끝난 1시간봉 추세로 판단", "1h": "끝난 4시간봉 추세로 판단", "4h": "끝난 일봉 추세로 판단"}
TREND_JUDGED_TFS = ("1h", "4h", "1d")  # the higher bars the bot judges (state ``trend`` coins; 1d since 10-22)
TREND_ENTRY_OF = {v: k for k, v in TREND_HTF.items()}   # a judged bar -> the entries that read it


def trend_waits(cfg: Optional[dict]) -> bool:
    """The trend bot at ``cfg`` waits for a pullback after a signal passes (``trend.pullback_wait``, true when missing:
    the 10-21 design; the owners' config since 10-22 enters at once, the shadow trend-wait still waits)."""
    t = (cfg or {}).get("trend") if isinstance(cfg, dict) else None
    return bool(t.get("pullback_wait", True)) if isinstance(t, dict) else True
TREND_NO_PAUSE_KO = "쉬기 없음 · 하루 손실 한도 없음"
TREND_LEDGER_KO = "개선 후보 장부는 예전 봇의 5년 기준표로 찾은 후보라 추세판단 봇에는 쓰지 않아요 · 2주 뒤 검토에서 새로 봐요"


def trend_bot(path: Optional[str]) -> Optional[dict]:
    """The trend bot's identity when the paper bot whose database is ``path`` runs it (its start record ``combo_run`` has a
    config with a non-null ``trend``: livetrend.build's ``trend_on``), else None (another bot, or nothing readable: every
    page then stays as it was). {name, since (its first start on this database: state ``combo`` trend_since, else state
    ``trend`` since, else the start record's time), freeze_until (since + 2 weeks), rules (state ``trend`` rules: the
    bot's own words), numbers, members [{order, label, strategy, tf, role, htf, side_only, no_chase}], config}."""
    if not path:
        return None
    try:
        conn = open_ro(path)
    except (OSError, sqlite3.Error):
        return None
    try:
        if "state" not in _tables(conn):
            return None
        got = {k: (_i(ts), _j(d)) for k, ts, d in conn.execute(
            "SELECT k, ts, data FROM state WHERE k IN ('combo_run', 'combo', 'trend')").fetchall()}
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    run_ts, run = got.get("combo_run") or (None, {})
    cfg = run.get("config") if isinstance(run.get("config"), dict) else None
    if not cfg or cfg.get("trend") is None:
        return None
    combo = (got.get("combo") or (None, {}))[1]
    tr = (got.get("trend") or (None, {}))[1]
    since = _i(combo.get("trend_since")) or _i(tr.get("since")) or run_ts
    members = []
    for i, m in enumerate(cfg.get("members") or [], 1):
        if not isinstance(m, dict):
            continue
        name, tf = m.get("strategy") or m.get("pick"), m.get("tf")
        side_only = next((c["side"] for c in m.get("when") or [] if isinstance(c, dict) and c.get("side") in ("long", "short")), None)
        members.append({"order": i, "label": f"{name}@{tf}", "strategy": name, "tf": tf, "role": TREND_ROLE.get(name),
                        "htf": TREND_HTF.get(tf), "side_only": side_only, "no_chase": bool(m.get("no_chase"))})
    return {"name": cfg.get("name") or TREND_NAME_KO, "since": since,
            "freeze_until": since + TREND_FREEZE_DAYS * DAY if since else None, "freeze_days": TREND_FREEZE_DAYS,
            "rules": [str(x) for x in tr.get("rules") or [] if isinstance(x, str)],
            "numbers": tr.get("numbers") if isinstance(tr.get("numbers"), dict) else {}, "members": members, "config": cfg}


def trend_out(tb: Optional[dict]) -> Optional[dict]:
    """The trend bot as a page shows it (no config): None for another bot."""
    if tb is None:
        return None
    t = (tb.get("config") or {}).get("trend")
    return {"trend": True, "name": tb["name"], "since": tb["since"], "freeze_until": tb["freeze_until"],
            "freeze_days": tb["freeze_days"], "no_ref_ko": TREND_NO_REF_KO,
            # its entry style (10-22: 바로 진입, 보류 허용), so a page says what this config does, never the 10-21 design's
            "pullback_wait": trend_waits(tb.get("config")), "hold_entry": bool(isinstance(t, dict) and t.get("hold_entry")),
            "members": [{k: m[k] for k in ("order", "strategy", "tf", "role", "side_only")} for m in tb["members"]]}


def trend_since(trades: list, since: Optional[int], key: str = "entry_time") -> list:
    """The trades entered at or after ``since`` (the trend bot's own trades; the database keeps the bots before it)."""
    if since is None:
        return list(trades)
    return [t for t in trades if (_i(t.get(key)) or 0) >= int(since)]


# 성적 · 지도 before the trend bot's first closed trade (owners 10-21 night: tables of zeros on the first day)
TREND_EMPTY_KO = "새 봇 거래 아직 없음 · 첫 거래가 닫히면 채워져요"


def trend_empty(tb: Optional[dict], n: int) -> Optional[dict]:
    """The one empty state of a page while the trend bot has no closed trade of its own (``n``: its closed trades since its
    start): {ko, since, expect (the 7/1~10/20 replay's expectation, 가상: livetrend.expect_of with the running config)}.
    None for another bot or from the first closed trade on (the page as before)."""
    if tb is None or n >= 1:
        return None
    from . import livetrend as LT                          # (livetrend imports this module)
    return {"ko": TREND_EMPTY_KO, "since": tb["since"], "expect": LT.expect_of(tb.get("config"))}


def live_ref(paper_path: Optional[str] = None) -> dict:
    """The 5-year reference for the bot running at ``paper_path`` (liveimprove.load_ref and its config guard), or
    livecheck.RefConfigMismatch (TREND_NO_REF_KO) when that bot is the trend bot: a new rule set has no backtest."""
    from ... import livecheck as LC
    from ... import liveimprove as LI
    if trend_bot(paper_path or paths()["paper"]) is not None:
        raise LC.RefConfigMismatch(TREND_NO_REF_KO)
    return LI.load_ref()


def acct_paper(paper: dict, account: str, now: int, id_: str = "paper", label: Optional[dict] = None) -> dict:
    """The paper account (A+C 합본) as one of the terminal's three accounts; ``id_`` "paper2" with its ``label``
    (paper_bots) for the second paper bot (owners 10-19: 규칙봇 15 at -35 %)."""
    base = {"id": id_, "name_ko": "페이퍼(연습)", "kind": "paper", "account": account}     # never taken for real money
    if label:
        base.update(label_ko=label.get("label_ko"), stop_ko=label.get("stop_ko"), bot_ko=label.get("name"), followers=label.get("followers"))
    if paper.get("state") != "ok":
        return {**base, "state": paper.get("state"), "reason_ko": paper.get("reason_ko"), "reason": paper.get("reason"), "path": paper.get("path")}
    a = (paper.get("accounts") or {}).get(account) or {}
    if not a.get("known"):
        return {**base, "state": "missing", "reason_ko": "페이퍼 DB에 이 계좌의 기록이 아직 없어요", "path": paper.get("path")}
    trades = a.get("trades") or []
    since = a.get("since_ms") or paper.get("started_ms")
    return {**base, "state": "ok", "sub_ko": paper.get("name_ko") or "A+C 합본", "as_of_ms": paper.get("as_of_ms"),
            "stale": paper.get("stale"), "balance": a.get("wallet"), "initial": a.get("initial"), "halted": bool(a.get("halted")),
            "halt_reason": a.get("halt_reason") or "", "bust": bool(a.get("bust")), "position": a.get("position"),
            "stats": a.get("stats"), "today": today_of(trades, now), "since_ms": since,
            "hours": hours_of(trades), "start": since, "calendar": calendar_of(trades, id_, since, now),
            "curve": a.get("curve")}


def acct_exec(x: dict, paper_pos: Optional[dict], now: int) -> dict:
    """An executor as one of the terminal's three accounts. Its open position borrows the paper position's next lock step
    when it follows that very paper position (the executor moves its stop when the paper's lock moves); an executor that
    runs its own ladder ("own", owners 10-20 "거래소 기준") shows its own next step instead."""
    r, cfg = x["record"], x["config"] or {}
    base = {"id": x["id"], "name_ko": x["name_ko"], "kind": "live", "account": x["follows"]}
    if r.get("state") != "ok":
        return {**base, "state": r.get("state"), "reason_ko": r.get("reason_ko"), "reason": r.get("reason"), "path": r.get("path")}
    trades = r.get("trades") or []
    pos = r.get("position")
    if pos:
        pos = dict(pos)
        own = pos.get("own")
        if own and own.get("next"):
            # 거래소 기준 (owners 10-20): its own next step on its own fill and costs, never the paper's
            pos["next_lock"] = {**own["next"], "from": "exchange"}
            if paper_pos and pos.get("key") == paper_pos.get("key"):
                pos["paper_lock_roe"] = paper_pos.get("lock_roe")
        elif paper_pos and pos.get("key") == paper_pos.get("key") and paper_pos.get("next_lock"):
            pos["next_lock"] = {**paper_pos["next_lock"], "from": "paper"}
            pos["paper_lock_roe"] = paper_pos.get("lock_roe")
    since = r.get("since_ms")
    return {**base, "state": "ok", "sub_ko": "실거래 실행기" if r.get("mode") == "mainnet" else f"실행기 · {r.get('mode') or '모드 모름'}",
            "as_of_ms": r.get("as_of_ms"), "stale": r.get("stale"), "balance": r.get("last_equity"), "initial": r.get("base_equity"),
            "initial_ts": r.get("first_equity_ts"), "halted": bool(r.get("halted")), "halt_reason": r.get("halt_reason") or "",
            "halted_ts": r.get("halted_ts"), "consecutive_losses": r.get("consecutive_losses"),
            "max_consecutive_losses": cfg.get("max_consecutive_losses"), "kill_file": cfg.get("kill_file"),
            "budget_usd": cfg.get("budget_usd"), "position": pos, "stats": r.get("stats"),
            "today": today_of(trades, now, "exit_ts"), "since_ms": since, "hours": hours_of(trades, "exit_ts"), "start": since,
            "calendar": calendar_of(trades, x["id"], since, now, "exit_ts"), "curve": r.get("curve")}


def fills_of(paper: dict, execs: list, account: str, limit: int = FILLS_KEEP, papers: Optional[list] = None) -> list:
    """실거래 체결: every entry and exit of the three accounts, newest first. A live exit that followed the paper's close takes
    the reason of the paper trade it followed (손절 / 잠금 익절; its own paper bot's, pairs_of) when the two trades are
    matched; the reason is never guessed from the P&L. ``papers`` (paper_bots): the second paper bot's fills too, as
    "paper2", while an executor follows it."""
    out = []
    srcs = [("paper", paper)] + [(b["id"], b["read"]) for b in (papers or []) if b["id"] != "paper" and b.get("followers")]
    for aid, pr in srcs:
        a = (pr.get("accounts") or {}).get(account) if pr.get("state") == "ok" else None
        cfg = cfg_of(pr)                                 # its own words for TIME (the trend bot's supervisor / a hold limit)
        for t in (a or {}).get("trades") or []:
            base = {"acct": aid, "symbol": t["symbol"], "side": t["side"], "lev": t["leverage"]}
            out.append({**base, "key": f"{aid}:e:{t['id']}", "kind": "entry", "t": t["entry_time"], "price": t["entry_price"]})
            out.append({**base, "key": f"{aid}:x:{t['id']}", "kind": "exit", "t": t["exit_time"], "price": t["exit_price"], "pnl": t["pnl"],
                        "roe": t["roe"], "reason": t["exit_reason"], "reason_ko": exit_words(t["exit_reason"], cfg, t.get("exit_why"))})
        p = (a or {}).get("position")
        if p:
            out.append({"acct": aid, "symbol": p["symbol"], "side": p["side"], "lev": p["leverage"], "key": f"{aid}:e:{p['key']}",
                        "kind": "entry", "t": p["entry_time"], "price": p["entry"], "open": True})
    for x in execs:
        r = x["record"]
        if r.get("state") != "ok":
            continue
        pairs = pairs_of(x)
        for t in r.get("trades") or []:
            base = {"acct": x["id"], "symbol": t["symbol"], "side": t["side"], "lev": t["leverage"]}
            reason, pt = t["exit_reason"], pairs.get(str(t["key"]))
            if reason == "PAPER" and pt:
                reason = pt["exit_reason"] or reason
            words = exit_words(reason, cfg_of(_paper_of(x, pt["paper_path"])), pt.get("exit_why")) if pt and reason == pt["exit_reason"] \
                else EXIT_KO.get(reason, reason)
            out.append({**base, "key": f"{x['id']}:e:{t['key']}", "kind": "entry", "t": t["entry_ts"], "price": t["entry_price"]})
            out.append({**base, "key": f"{x['id']}:x:{t['key']}", "kind": "exit", "t": t["exit_ts"], "price": t["exit_ref"], "pnl": t["pnl"],
                        "roe": t["roe"], "est": t["est"], "reason": reason, "reason_ko": words})
        q = r.get("position")
        if q and q.get("entry_time"):
            out.append({"acct": x["id"], "symbol": q["symbol"], "side": q["side"], "lev": q["leverage"], "key": f"{x['id']}:e:{q['key']}",
                        "kind": "entry", "t": q["entry_time"], "price": q["entry"], "open": True})
    out = [f for f in out if f.get("t") is not None]
    out.sort(key=lambda f: (-(f["t"] or 0), 0 if f["kind"] == "exit" else 1, f["key"]))
    return out[:limit]


def marks_of(paper: dict, execs: list, account: str, sym_limit: int = 12, papers: Optional[list] = None) -> list:
    """Recent closed trades of every account for the chart's entry / exit marks: {acct, symbol, side, entry_time, exit_time,
    pnl}, newest first, at most ``sym_limit`` per coin (the second paper bot's while an executor follows it)."""
    out, per = [], {}
    rows = []
    srcs = [("paper", paper)] + [(b["id"], b["read"]) for b in (papers or []) if b["id"] != "paper" and b.get("followers")]
    for aid, pr in srcs:
        a = (pr.get("accounts") or {}).get(account) if pr.get("state") == "ok" else None
        rows += [(aid, t["symbol"], t["side"], t["entry_time"], t["exit_time"], t["pnl"]) for t in (a or {}).get("trades") or []]
    for x in execs:
        r = x["record"]
        if r.get("state") == "ok":
            rows += [(x["id"], t["symbol"], t["side"], t["entry_ts"], t["exit_ts"], t["pnl"]) for t in r.get("trades") or []]
    for acct, sym, side, et, xt, pnl in sorted(rows, key=lambda r: -(r[4] or 0)):
        if et is None or xt is None or per.get(sym, 0) >= sym_limit:
            continue
        per[sym] = per.get(sym, 0) + 1
        out.append({"acct": acct, "symbol": sym, "side": side, "entry_time": et, "exit_time": xt, "pnl": pnl})
    return out


# ---------------------------------------------------------------- the whole answer
def _paper_of(x: dict, path: Optional[str] = None) -> dict:
    """The read_paper answer of ``path`` (default: the paper database the executor follows now), read once per request."""
    return x["_papers"].get(LP.norm(path or x["paper_path"])) or _missing(path or x["paper_path"])


def own_account(x: dict) -> Optional[dict]:
    """The paper account the executor follows now, in its own paper database (read_paper's account answer)."""
    pa = _paper_of(x)
    a = (pa.get("accounts") or {}).get(x["follows"]) if pa.get("state") == "ok" else None
    return a if a and a.get("known") else None


def pairs_of(x: dict) -> dict:
    """{live trade key: the paper trade it followed}: each closed live trade against the paper database the executor
    followed when it entered (livepapers segments), the same coin and side within MATCH_MS (match). A paper trade carries
    ``paper_path`` (its database). With one paper bot this is match(paper trades, live trades), as it always was."""
    if "_pairs" in x:
        return x["_pairs"]
    r = x["record"]
    out: dict = {}
    if r.get("state") == "ok":
        groups: dict = {}
        for lt in r.get("trades") or []:
            path = LP.paper_at(x["segs"], lt.get("entry_ts"))
            groups.setdefault(LP.norm(path), (path, []))[1].append(lt)
        for path, lts in groups.values():
            pa = _paper_of(x, path)
            acc = (pa.get("accounts") or {}).get(x["follows"]) if pa.get("state") == "ok" else None
            pts = (acc or {}).get("trades") or []
            by = {t["id"]: t for t in pts}
            for lk, pid in match(pts, lts).items():
                out[lk] = {**by[pid], "paper_path": path}
    x["_pairs"] = out
    return out


def rev_pairs(x: dict) -> dict:
    """{(paper database, paper trade id): live trade key} of pairs_of."""
    return {(LP.norm(pt["paper_path"]), pt["id"]): lk for lk, pt in pairs_of(x).items()}


def followed_at(x: dict, path: str, t: Optional[int]) -> bool:
    """Did the executor follow the paper database ``path`` at ``t``?"""
    return LP.followed_at(x["segs"], path, t)


def era_trades(x: dict, path: str, since: Optional[int] = None, key: str = "entry_ts") -> list:
    """The executor's closed trades entered while it followed the paper database ``path`` (livepapers segments: owners
    10-23, one executor may move to the 'VWAP 개선판' and its trades from then on are that bot's), from ``since`` on. With
    one paper bot every trade is the main bot's and this is trend_since."""
    r = x["record"]
    if r.get("state") != "ok":
        return []
    return [t for t in r.get("trades") or [] if followed_at(x, path, t.get(key))
            and (since is None or (_i(t.get(key)) or 0) >= int(since))]


def era_of(x: dict, path: str, bots: Optional[list] = None) -> Optional[dict]:
    """When the executor followed another paper bot than ``path`` at some time (owners 10-23): {other_ko (that bot's
    short name: the one it follows now when it is another), now_other (it follows another one now), since (when it moved
    to the one it follows now, else None), other_n (its closed trades on another bot, left out of ``path``'s numbers)};
    None while every segment is ``path`` (one paper bot: the pages as before)."""
    segs = x.get("segs") or []
    if all(LP.same(sp, path) for _f, sp in segs):
        return None
    r = x["record"]
    trades = (r.get("trades") or []) if r.get("state") == "ok" else []
    other = [t for t in trades if not followed_at(x, path, t.get("entry_ts"))]
    cur = LP.current(segs)
    now_other = not LP.same(cur, path)
    ref = cur if now_other else next((sp for _f, sp in reversed(segs) if not LP.same(sp, path)), None)
    b = next((b for b in bots or [] if LP.same(b["path"], ref)), None)
    return {"other_ko": (b or {}).get("short_ko") or "다른 페이퍼 봇", "now_other": now_other,
            "since": segs[-1][0] if now_other else None, "other_n": len(other)}


def other_cell(x: dict, label_ko: Optional[str]) -> dict:
    """A paper trade of a paper bot the executor did not follow then (owners 10-19: two paper bots)."""
    return {"state": "other", "why_ko": f"이때 {josa(x['name_ko'], '은', '는')} {josa(label_ko or '다른 페이퍼', '을', '를')} 따라갔어요"}


def range_bot(cfg: Any) -> bool:
    """A config of the 레인지 봇 (owners 10-26, paperbot/rangebot.py): its ``range`` section (never the file name alone)."""
    return isinstance(cfg, dict) and isinstance(cfg.get("range"), dict)


def paper_bots(p: dict, paper: dict, execs: list) -> list:
    """The paper bots on the page: [{"id": "paper" | "paper2" | "range", "path", "read", "name", "stop", "stop_short",
    "stop_ko", "followers", "label_ko"}] in BOT_IDS order. "range": the 레인지 봇 (owners 10-26), told by its own config
    (``range_bot``: its start record's ``range`` section), the database an executor follows that is one, else its file
    (PAPERBOT_LIVE_RANGE_DB) once it is there and is one. "paper2": another paper database an executor follows now (not the
    레인지 봇's), else the second bot's file (PAPERBOT_LIVE_PAPER2_DB) once it is there. One paper bot: one item (the page as
    before); without a 레인지 봇 the one- and two-bot pages are as they were."""
    main = p["paper"]
    # the third paper bot's file (owners 10-24, '친구 매매법' that WOO X Pro 2 follows) never takes the second's place, nor
    # the paper 투비트 follows (owners 10-25, SIDE_PAPER_EXECS)
    third = p.get("paper3") if p.get("paper3") and not LP.same(p.get("paper3"), p.get("paper2")) else None
    papers = execs[0]["_papers"] if execs else {LP.norm(main): paper}
    cands: list = []
    for x in execs:
        path = x["paper_path"]
        if LP.same(path, main) or LP.same(path, third) or x["id"] in SIDE_PAPER_EXECS or any(LP.same(path, c) for c in cands):
            continue
        cands.append(path)

    def is_range(path: Optional[str]) -> bool:
        return bool(path) and range_bot(cfg_of(papers.get(LP.norm(path))))
    rng = next((c for c in cands if is_range(c)), None)
    if rng is None and p.get("range") and not LP.same(p["range"], main) and is_range(p["range"]):
        rng = p["range"]                                 # its file, read by sources() once it is there
    second = next((c for c in cands if not LP.same(c, rng)), None)
    if second is None and p.get("paper2") and not LP.same(p["paper2"], main) and not LP.same(p["paper2"], rng) \
            and os.path.exists(p["paper2"]):
        second = p["paper2"]
    out = []
    for pid, path in (("paper", main), ("paper2", second), ("range", rng)):
        if path is None:
            continue
        pr = papers.get(LP.norm(path)) or paper
        fol = [x["name_ko"] for x in execs if LP.same(x["paper_path"], path)]
        stop = pr.get("stop") if pr.get("state") == "ok" else None
        out.append({"id": pid, "path": path, "read": pr, "name": pr.get("name_ko"), "stop": stop, "stop_short": LP.stop_short(stop),
                    "stop_ko": LP.stop_words(stop), "followers": fol, "follower_ids": [x["id"] for x in execs if LP.same(x["paper_path"], path)],
                    "label_ko": LP.label(stop, fol, pr.get("name_ko")), "short_ko": LP.bot_short(pr.get("name_ko"), stop)})
    return out


def bot_id(bots: list, path: Optional[str]) -> Optional[str]:
    """"paper" / "paper2" / "range": which paper bot on the page ``path`` is (None: none of them)."""
    return next((b["id"] for b in bots if LP.same(b["path"], path)), None)


def papers_out(bots: list) -> Optional[list]:
    """The paper bots for the page (no records): None with one paper bot (nothing new on the page)."""
    if len(bots) < 2:
        return None
    return [{k: b.get(k) for k in ("id", "path", "name", "stop", "stop_short", "stop_ko", "followers", "follower_ids", "label_ko", "short_ko")}
            | {"state": b["read"].get("state"), "as_of_ms": b["read"].get("as_of_ms"), "stale": b["read"].get("stale")} for b in bots]


PARTED_KEEP = 30                       # parted shared entries listed (newest first)


def _eq_before(trades: list, ms: Optional[int], initial: Optional[float]) -> Optional[float]:
    """The closed-trade equity just before ``ms``: the last equity_after of a trade closed by then, else the start."""
    eq = initial
    for t in trades:
        if ms is not None and (t.get("exit_time") or 0) <= ms and t.get("equity_after") is not None:
            eq = t["equity_after"]
    return eq


def members_key(cfg: Optional[dict]) -> Optional[tuple]:
    """A config's entry members as a sorted tuple of (strategy, timeframe); None when the config or its members are not
    known."""
    ms = [m for m in (cfg or {}).get("members") or [] if isinstance(m, dict)]
    if not ms:
        return None
    return tuple(sorted((str(m.get("strategy") or m.get("pick")), str(m.get("tf"))) for m in ms))


def twins(bots: list) -> bool:
    """The two paper bots are twins (owners 10-19: 규칙봇 15 at -50 % and at -35 %): the same entry members in both
    configs, so they enter on the same signals and only the stop tells them apart. Two different bots (owners 10-23: the
    추세판단 봇 and the 'VWAP 개선판') or a config not known yet: False (no stop-only words, no shared entries)."""
    if len(bots) < 2:
        return False
    keys = [members_key(cfg_of(b["read"])) for b in bots[:2]]
    return keys[0] is not None and keys[0] == keys[1]


# 두 봇 나란히 (owners 10-23): two different bots have different signals; their numbers side by side, nothing paired
PLAIN_WORDS_KO = "두 봇 나란히: 매매법이 서로 달라요 · 같은 기간의 숫자만 나란히 보여요 (같은 진입을 짝짓지 않아요)"
PLAIN_NOTE_KO = ("두 봇은 매매법·손절·진입 조건이 모두 달라요. 어느 쪽이 낫다고 정하지 않아요 · 거래가 적을 때는 대부분 운이에요")
TWIN_NOTE_KO = "두 봇은 같은 신호로 들어가고 손절 자리만 달라요. 한쪽이 먼저 손절되면 그 뒤 다른 진입을 혼자 할 수 있어요 (한 번에 포지션 하나)"


def compare_papers(bots: list) -> Optional[dict]:
    """두 페이퍼 비교 (owners 10-19, docs/live15-mexc-ko.md): the two paper bots side by side since the second one started
    (its account's first record): closed trades, wins, win rate, net ROE sum, equity then and now, the deepest drop of the
    closed-trade equity, and for twins (``twins``: the same members, only the stop differs) the entries both made (same
    coin, side and entry minute) whose results parted (one won where the other lost, or another exit). Two different bots
    (owners 10-23): the same numbers side by side (``twin`` False), no shared entries (their signals are their own). None
    with one paper bot."""
    if len(bots) < 2:
        return None
    accs = []
    for b in bots[:2]:
        pr = b["read"]
        a = (pr.get("accounts") or {}).get(ACCOUNT) if pr.get("state") == "ok" else None
        accs.append(a if a and a.get("known") else None)
    if accs[1] is None or accs[0] is None:
        b = bots[1] if accs[1] is None else bots[0]
        st = b["read"]
        return {"state": st.get("state") if st.get("state") != "ok" else "missing", "path": b["path"],
                "reason_ko": st.get("reason_ko") if st.get("state") != "ok" else "이 페이퍼 DB에 아직 계좌 기록이 없어요"}
    since = accs[1].get("since_ms") or bots[1]["read"].get("started_ms") \
        or min((t["entry_time"] for t in accs[1].get("trades") or [] if t.get("entry_time") is not None), default=None)
    if cfg_of(bots[0]["read"]).get("trend") is not None:  # the trend bot: from its own start (never the bot before it on its file)
        tb = trend_bot(bots[0]["path"])
        if tb and tb.get("since") is not None and (since is None or tb["since"] > since):
            since = tb["since"]
    rows, mine = [], []
    for b, a in zip(bots, accs):
        allt = sorted(a.get("trades") or [], key=lambda t: (t.get("exit_time") or 0, t.get("id") or 0))
        ts = [t for t in allt if since is None or (t.get("entry_time") or 0) >= since]
        mine.append(ts)
        st = stats(t.get("pnl") for t in ts)
        eq0 = _eq_before(allt, since, a.get("initial"))
        peak, dd = eq0, 0.0
        for t in ts:
            e = t.get("equity_after")
            if e is None:
                continue
            peak = e if peak is None or e > peak else peak
            if peak:
                dd = max(dd, 1 - e / peak)
        wallet = a.get("wallet")
        rows.append({"id": b["id"], "label_ko": b["label_ko"], "name": b.get("name"), "stop_short": b.get("stop_short"),
                     "stop_ko": b.get("stop_ko"), "n": st["trades"], "wins": st["wins"], "losses": st["losses"], "win_rate": st["win_rate"],
                     "roe_sum": sum(t.get("roe") or 0.0 for t in ts), "pnl": st["pnl"], "start_equity": eq0, "equity": wallet,
                     "change": (wallet / eq0 - 1) if wallet is not None and eq0 else None, "max_dd": dd, "open": bool(a.get("position"))})
    if not twins(bots):                                  # two different bots: side by side only (their names, no stop-only words)
        for r, b in zip(rows, bots):
            r["short_ko"] = b.get("short_ko")
        return {"state": "ok", "twin": False, "since_ms": since, "rows": rows, "shared": None, "parted": None, "only": None,
                "parted_rows": [], "words_ko": PLAIN_WORDS_KO, "note_ko": PLAIN_NOTE_KO}
    key = lambda t: (t.get("symbol"), t.get("side"), t.get("entry_time"))           # noqa: E731
    by0, by1 = {key(t): t for t in mine[0]}, {key(t): t for t in mine[1]}
    shared = [k for k in by0 if k in by1]
    parted = []
    for k in shared:
        x, y = by0[k], by1[k]
        if ((x.get("pnl") or 0) > 0) != ((y.get("pnl") or 0) > 0) or x.get("exit_reason") != y.get("exit_reason"):
            parted.append({"symbol": k[0], "side": k[1], "entry_time": k[2], "strategy_id": x.get("strategy_id"), "timeframe": x.get("timeframe"),
                           bots[0]["id"]: {f: x.get(f) for f in ("exit_reason", "roe", "pnl", "exit_time")},
                           bots[1]["id"]: {f: y.get(f) for f in ("exit_reason", "roe", "pnl", "exit_time")}})
    parted.sort(key=lambda r: -(r["entry_time"] or 0))
    only = {bots[0]["id"]: sum(1 for k in by0 if k not in by1), bots[1]["id"]: sum(1 for k in by1 if k not in by0)}
    s0, s1 = rows[0]["stop_short"] or "첫 페이퍼", rows[1]["stop_short"] or "두 번째 페이퍼"
    words = (f"같은 진입 {len(shared)}번 중 결과가 갈린 거래 {len(parted)}번"
             + (f" · 한쪽만 들어간 거래: {s0} {only[bots[0]['id']]}번, {s1} {only[bots[1]['id']]}번" if any(only.values()) else ""))
    return {"state": "ok", "since_ms": since, "rows": rows, "shared": len(shared), "parted": len(parted), "only": only,
            "parted_rows": parted[:PARTED_KEEP], "words_ko": words, "note_ko": TWIN_NOTE_KO}


def sources(p: dict, now: int) -> tuple:
    """(configs, follows, paper, execs): every source read once, in one snapshot each. ``paper`` is the main paper bot
    (PAPERBOT_LIVE_PAPER_DB); each executor carries the paper database it follows now (``paper_path``), when it followed
    which (``segs``, livepapers.segments from its own start records) and every paper database it ever followed
    (``_papers``, read once and shared; with the second paper bot's file when it is there)."""
    configs = {ex: read_config(p[ck]) for ex, _ko, _dk, ck in installed(p)}
    follows = {ex: (c.get("account") if c.get("state") == "ok" and c.get("account") else ACCOUNT) for ex, c in configs.items()}
    want = [ACCOUNT, FLIP_ACCOUNT, *follows.values()]
    paper = read_paper(p["paper"], want, now)
    papers = {LP.norm(p["paper"]): paper}

    def get(path: str) -> dict:
        k = LP.norm(path)
        if k not in papers:
            papers[k] = read_paper(path, want, now)
        return papers[k]
    for k in ("paper2", "range"):                       # the second bot's and the 레인지 봇's files once they are there
        if p.get(k) and os.path.exists(p[k]):
            get(p[k])
    execs = []
    for ex, ko, dk, _ck in slots(configs):
        cfg = configs[ex]
        rec = read_exec(p[dk], now)
        cfg_paper = cfg.get("paper_db") if cfg.get("state") == "ok" else None
        starts = (rec.get("starts") or []) if rec.get("state") == "ok" else []
        started = any(pdb for _t, pdb in starts)        # a start of this code (it names its paper database)
        segs = LP.segments(starts, p["paper"], cfg_paper)
        for path in LP.paths_of(segs):
            get(path)
        cur = LP.current(segs)
        own = get(cur)
        acc = (own.get("accounts") or {}).get(follows[ex]) or {}
        if cfg.get("state") != "ok":
            lt = {"state": "unknown", "reason_ko": "실행기 설정을 읽지 못해 신호등 기준을 몰라요" if cfg.get("state") == "error"
                  else "실행기 설정 파일이 아직 없어 신호등 기준을 몰라요", "config_state": cfg.get("state")}
        elif own.get("state") != "ok":
            lt = {"state": "unknown", "reason_ko": "페이퍼 기록을 읽지 못해 신호등을 계산하지 못해요", "paper_state": own.get("state"),
                  "n": cfg["signal_light_n"], "min_win": cfg["signal_light_min_win"]}
        else:                                           # the executor's own rule on the paper it follows now
            newest = [t["pnl"] for t in sorted(acc.get("trades") or [], key=lambda t: (t["exit_time"] or 0, t["id"] or 0), reverse=True)]
            lt = light(cfg["signal_light_n"], cfg["signal_light_min_win"], newest)
        if rec.get("state") == "ok":
            last = next((e for e in rec.get("events") or [] if e["kind"] in ("light_red", "light_unread")), None)
            lt["last_event"] = last
        notes = []
        if cfg.get("state") == "ok":
            if LP.config_differs(segs, cfg_paper):
                notes.append(f"실행기 설정의 페이퍼 DB({cfg_paper})는 실행기를 (다시) 켜야 적용돼요. 지금은 {cur}를 따라가요"
                             + ("" if started else " (이 실행기 기록에 페이퍼 DB를 남긴 시작이 아직 없어요)"))
            if cfg.get("db") and os.path.abspath(cfg["db"]) != os.path.abspath(p[dk]):
                notes.append(f"실행기 설정의 DB({cfg['db']})와 이 화면이 읽는 DB({p[dk]})가 달라요")
            if follows[ex] != ACCOUNT:
                notes.append(f"이 실행기는 {follows[ex]} 계좌를 따라가요")
        if rec.get("state") == "ok" and rec.get("account") and rec["account"] != follows[ex]:
            notes.append(f"실행기 기록의 계좌({rec['account']})와 설정의 계좌({follows[ex]})가 달라요")
        execs.append({"id": ex, "name_ko": ko, "follows": follows[ex], "config": cfg, "record": rec, "light": lt, "notes": notes,
                      "segs": segs, "paper_path": cur, "_papers": papers})
    bots = paper_bots(p, paper, execs)
    if len(bots) > 1:                                   # two paper bots: each executor names the one it follows
        for x in execs:
            b = next((b for b in bots if LP.same(b["path"], x["paper_path"])), None)
            x["paper_id"] = b["id"] if b else None
            x["follows_ko"] = b["short_ko"] if b else _bot_ko(x)
            if len(x["segs"]) > 1:
                x["switched_ms"] = x["segs"][-1][0]
    else:                                               # one paper bot on the page: an executor on another (the third's)
        for x in execs:                                 # still names its own
            if not LP.same(x["paper_path"], p["paper"]):
                x["follows_ko"] = _bot_ko(x)
    return configs, follows, paper, execs


def _bot_ko(x: dict) -> str:
    """The short name of the paper bot an executor follows that is not one of the page's paper bots (owners 10-24:
    '친구 매매법'), from its own record; its path when that cannot be read. A record without a bot's name or stop whose
    account is not the combined bots' (owners 10-25: 투비트 may follow a rule-bot account such as V39_ALL@1h): "페이퍼"
    with that account, never a bare "페이퍼" that reads like the page's own."""
    pr = _paper_of(x)
    if pr.get("state") != "ok":
        return x["paper_path"]
    ko = LP.bot_short(pr.get("name_ko"), pr.get("stop"))
    if ko == "페이퍼" and x.get("follows") and x["follows"] != ACCOUNT:
        return f"페이퍼 {x['follows']}"
    return ko


def public(x: dict) -> dict:
    """An executor's entry of sources() without the shared paper reads (``_papers``, ``_pairs``)."""
    return {k: v for k, v in x.items() if not k.startswith("_")}


def build(p: Optional[dict] = None, now_ms: Optional[int] = None) -> dict:
    """GET /api/v4/livebots: the terminal's answer."""
    p = p or paths()
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    _configs, _follows, paper, execs = sources(p, now)
    pa = (paper.get("accounts") or {}).get(ACCOUNT) if paper.get("state") == "ok" else None
    bots = paper_bots(p, paper, execs)
    # each executor borrows the next lock of the paper position IT follows (its own paper bot's)
    accts = [acct_paper(paper, ACCOUNT, now, label=bots[0] if len(bots) > 1 else None)]
    accts += [acct_paper(b["read"], ACCOUNT, now, b["id"], b) for b in bots[1:]]
    accts += [acct_exec(x, (own_account(x) or {}).get("position"), now) | ({"follows_ko": x["follows_ko"]} if x.get("follows_ko") else {})
              for x in execs]                            # two paper bots: each executor says which one it follows
    fills = fills_of(paper, execs, ACCOUNT, papers=bots)
    marks = marks_of(paper, execs, ACCOUNT, papers=bots)
    events = sorted(((dict(e, ex=x["id"], ex_ko=x["name_ko"])) for x in execs for e in (x["record"].get("events") or [])),
                    key=lambda e: (e["ts"] or 0, e["id"] or 0), reverse=True)[:2 * EVENTS_KEEP]
    ref_ko = ref_problem(p["paper"])
    tb = trend_bot(p["paper"])
    # the trend bot: its own trades only, and no 88 % / 82 % rule (TREND_RULE_KO)
    cp = checkpoint(trend_since((pa or {}).get("trades") or [], tb["since"]) if tb else (pa or {}).get("trades") or [],
                    TREND_RULE_KO if tb else ref_ko) if pa else None
    flip = (paper.get("accounts") or {}).get(FLIP_ACCOUNT) if paper.get("state") == "ok" else None
    execs = [public(x) for x in execs]
    for x in execs:                                      # the page needs neither the raw reasons nor the full trade list here
        # which of the page's paper bots it follows now ("paper" / "paper2", None: one of its own such as 투비트's): the
        # 봇별 screens (owners 10-26) show each bot with its own executors only
        x["bot"] = bot_id(bots, x.get("paper_path"))
        rec = x["record"] = dict(x["record"])
        rec.pop("why", None)
        rec.pop("events", None)
        if rec.get("trades") is not None:
            rec["trades_n"] = len(rec.pop("trades"))
        rec.pop("curve", None)
    paper_out = {k: v for k, v in no_private(paper).items() if k != "accounts"}
    if paper.get("state") == "ok":
        paper_out["accounts"] = {}
        for aid, a in paper["accounts"].items():
            paper_out["accounts"][aid] = {k: v for k, v in a.items() if k not in ("trades", "curve")}
    return {"now_ms": now, "paths": shown_paths(p), "account": ACCOUNT, "flip_account": FLIP_ACCOUNT, "paper": paper_out, "execs": execs,
            "accts": accts, "fills": fills, "marks": marks, "events": events, "checkpoint": cp,
            "flip": {"stats": flip.get("stats")} if flip and flip.get("known") else None,
            "refs": None if ref_ko else REFS, "refs_ko": ref_ko or None, "match_ms": MATCH_MS, "small": list(SMALL),
            "papers": papers_out(bots), "trend_bot": trend_out(tb), "replaced": replaced_out(p)}


# ================================================================ the other tabs (거래 · 신호 · 성적 · 안전 · 그림자 · 설정)
TF_KO = {"5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간", "1d": "일봉"}
TF_ORDER = {"5m": 0, "15m": 1, "30m": 2, "1h": 3, "4h": 4, "1d": 5}
SIDE_KO = {1: "롱", -1: "숏"}
COINS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")      # paperbot/rmember.py SYMS (the index of `sym`)
DOW_KO = "월화수목금토일"
REG_KO = {0: "상승장", 1: "하락장", 2: "횡보장"}
REG5_KO = {0: "강한 상승", 1: "약한 상승", 2: "강한 하락", 3: "약한 하락", 4: "횡보"}
POS_KO = {0: "7일 범위 아래 밖", 1: "7일 범위 아래 20%", 2: "7일 범위 가운데", 3: "7일 범위 위 20%", 4: "7일 범위 위 밖"}
SESSION_KO = {0: "아시아(09-17시)", 1: "유럽(17-22시)", 2: "미국(22-06시)", 3: "새벽(06-09시)"}
DIM_KO = {"sym": "코인", "side": "방향", "symside": "코인x방향", "hb": "4시간대", "hr": "시각", "dow": "요일", "wk": "주말", "btc": "BTC추세",
          "ctr4": "코인4h추세", "mom24": "24h모멘텀", "vol3": "변동성", "fund": "펀딩", "reg": "장세", "regwk": "장세x주말",
          "regside": "장세x방향", "reg5": "추세세기", "reg5side": "추세세기x방향", "pos": "7일위치", "posside": "7일위치x방향",
          "oi24": "미결제약정"}                                  # paperbot/rmember.py KO_DIM
FILTER_KO = {"session": "시간대", "weekend": "주말", "btc": "BTC 4시간 추세", "ctr4": "코인 4시간 추세", "mom24": "24시간 흐름", "vol3": "변동성",
             "fund": "펀딩", "side": "방향"}
SIGNALS_KEEP = 200                     # recent signal rows sent (the page pages them 10 at a time)
TRADES_KEEP = 500                      # closed trades per account sent to 거래 (newest first)
SHADOWS = (("b", "shadow-b.db", "그림자 B 안정형"), ("nocut", "shadow-nocut.db", "그림자 끄는 구간 없음"), ("ac32", "shadow-ac32.db", "그림자 32개"),
           ("chase", "shadow-chase.db", "그림자 어중간한 추격 막기"), ("trend4h", "shadow-trend4h.db", "그림자 4시간 역추세만"),
           ("rule15", "shadow-rule15.db", "그림자 규칙봇 15(옛 규칙)"),
           ("trend-time", "shadow-trend-time.db", "그림자 시간 정리 있음(10/21 추세판단 봇)"),
           ("trend-now", "shadow-trend-now.db", "그림자 되돌림 없이 바로 진입(10/21 추세판단 봇)"),
           ("trend-vote4", "shadow-trend-vote4.db", "그림자 판단 4개 모두 같은 쪽(10/21 추세판단 봇)"))
# the old bots' shadows above (A+C 합본 · 규칙봇 15 · the 10/21 추세판단 봇's three, configs gone with the 10/22 design); the
# live 추세판단 봇's own are dash/more/liveshadow.py TREND_SHADOWS
# the live checks' own files (read-only here): paperbot/livecheck.py (morning check, watcher, loss cards) and
# paperbot/liveimprove.py (weekly scorecard, the improvement ledger)
ENV_MORE = {"shadow_dir": ("PAPERBOT_LIVE_SHADOW_DIR", "/var/lib/paperbot/combo"),
            "combo_config": ("PAPERBOT_LIVE_COMBO_CONFIG", "/etc/paperbot/combo.json"),
            # the second paper bot's config file (its database's combo_run is read first; docs/live15-mexc-ko.md)
            "combo2_config": ("PAPERBOT_LIVE_COMBO2_CONFIG", "/etc/paperbot/combo-vwap.json"),
            # the 레인지 봇's config file (owners 10-26, docs/range-bot-ko.md 3장 B; its database's combo_run is read first)
            "range_config": ("PAPERBOT_LIVE_RANGE_CONFIG", "/etc/paperbot/combo-range.json"),
            "check_db": ("PAPERBOT_LIVE_CHECK_DB", "/var/lib/paperbot/livecheck.db"),
            "improve_db": ("PAPERBOT_LIVE_IMPROVE_DB", "/var/lib/paperbot/liveimprove.db"),
            "rule_db": ("PAPERBOT_LIVE_RULE_DB", "/var/lib/paperbot/paper3.db")}


def paths_more(env: Optional[dict] = None) -> dict:
    env = os.environ if env is None else env
    return {k: (env.get(var) or default) for k, (var, default) in ENV_MORE.items()}


def combo_fallback(more: dict, bot: Optional[str]) -> str:
    """The config file a paper bot's settings are read from before its first start record (read_combo's fallback): the
    main bot's (PAPERBOT_LIVE_COMBO_CONFIG), the 레인지 봇's (PAPERBOT_LIVE_RANGE_CONFIG), else the second bot's
    (PAPERBOT_LIVE_COMBO2_CONFIG); "-" (nothing) when ``more`` names none."""
    key = "combo_config" if bot == "paper" else "range_config" if bot == "range" else "combo2_config"
    return (more or {}).get(key) or "-"


def dim_value_ko(dim: str, v: Any) -> str:
    """One ``off`` bucket in the owners' words (paperbot/rmember.py definitions)."""
    v = _i(v)
    if v is None:
        return "?"
    coin = lambda i: COINS[i].replace("USDT", "") if 0 <= i < len(COINS) else str(i)          # noqa: E731
    ls = lambda x: "롱" if x else "숏"                                                         # noqa: E731
    if dim == "sym":
        return coin(v)
    if dim == "side":
        return SIDE_KO.get(v, str(v))
    if dim == "symside":
        return f"{coin(v // 2)} {ls(v % 2)}"
    if dim == "hb":
        return f"{v * 4:02d}~{v * 4 + 4:02d}시"
    if dim == "hr":
        return f"{v:02d}시"
    if dim == "dow":
        return DOW_KO[v] + "요일" if 0 <= v < 7 else str(v)
    if dim == "wk":
        return "주말" if v else "평일"
    if dim in ("btc", "ctr4", "mom24"):
        return "같은 방향" if v else "반대 방향"
    if dim == "vol3":
        return {0: "낮음", 1: "보통", 2: "높음"}.get(v, str(v))
    if dim == "fund":
        return "이 방향이 펀딩을 냄" if v else "펀딩을 안 냄"
    if dim == "reg":
        return REG_KO.get(v, str(v))
    if dim == "regwk":
        return f"{REG_KO.get(v // 2, v // 2)} {'주말' if v % 2 else '평일'}"
    if dim == "regside":
        return f"{REG_KO.get(v // 2, v // 2)} {ls(v % 2)}"
    if dim == "reg5":
        return REG5_KO.get(v, str(v))
    if dim == "reg5side":
        return f"{REG5_KO.get(v // 2, v // 2)} {ls(v % 2)}"
    if dim == "pos":
        return POS_KO.get(v, str(v))
    if dim == "posside":
        return f"{POS_KO.get(v // 2, v // 2)} {ls(v % 2)}"
    if dim == "oi24":
        return {0: "미결제약정 줄어듦(-5% 아래)", 1: "미결제약정 비슷", 2: "미결제약정 늘어남(+5% 위)", 3: "미결제약정 모름"}.get(v, str(v))
    return str(v)


def filter_ko(tag: str, v: Any) -> str:
    v = _i(v)
    if tag == "session":
        return f"시간대 {SESSION_KO.get(v, v)}"
    if tag == "weekend":
        return "주말만" if v else "평일만"
    if tag == "side":
        return "롱만" if v == 1 else "숏만"
    if tag == "vol3":
        return f"변동성 {({0: '낮음', 1: '보통', 2: '높음'}).get(v, v)}"
    if tag == "fund":
        return "그 방향이 펀딩을 낼 때" if v else "그 방향이 펀딩을 안 낼 때"
    return f"{FILTER_KO.get(tag, tag)} {'같은 방향' if v else '반대 방향'}"


def stop_ko(stop: Any, cfg_stop: Optional[dict] = None) -> dict:
    """A member's stop rule in words: its own research stop, or the config's house stop."""
    if isinstance(stop, (list, tuple)) and len(stop) == 2:
        mode, k = str(stop[0]), _f(stop[1])
        ko = {"atr": f"ATR {k:g}배 (강제청산 안쪽에 안 맞으면 당김, 최소 ATR 1배)" if k else "ATR",
              "pct": f"진입가의 {k:g}% (강제청산 안쪽으로 당김)" if k else "%", "swing": f"스윙 {k:g}봉 너머 +0.1% (최소 0.3%)" if k else "스윙"}.get(mode, mode)
        return {"mode": mode, "value": k, "ko": ko}
    c = cfg_stop or {}
    mode, k = c.get("mode", "atr"), _f(c.get("atr"))
    if mode == "roe":
        net = c.get("net") is True              # combo.py stop_net: the loss after both sides' fees and slippage
        return {"mode": "roe", "value": _f(c.get("roe")), "net": net,
                "ko": f"{'순' if net else ''}ROE -{(_f(c.get('roe')) or 0) * 100:g}%" + (" (수수료·슬리피지 포함)" if net else "")}
    return {"mode": mode, "value": k, "ko": f"ATR {k:g}배" + (" (안 맞으면 당김)" if mode == "atr_fit" else "") if k else "ATR"}


# a member with "no_chase": true (paperbot/combo.py Member.no_chase, CHASE_KO; the file is not imported here)
NO_CHASE_KO = "추격 진입 막기"
NO_CHASE_WHY_KO = "롱은 7일 범위 위 20%·24시간 고점 쪽 10% 안이면, 숏은 아래쪽이면 진입 안 함"


def describe_member(sp: dict, order: int, cfg_stop: Optional[dict] = None) -> dict:
    """One setting of the combined bot's config (a ``members`` item) in the owners' words."""
    sp = sp if isinstance(sp, dict) else {}
    off = [{"dim": str(o[0]), "dim_ko": DIM_KO.get(str(o[0]), str(o[0])), "value": o[1], "ko": f"{DIM_KO.get(str(o[0]), o[0])}: {dim_value_ko(str(o[0]), o[1])}"}
           for o in sp.get("off") or [] if isinstance(o, (list, tuple)) and len(o) == 2]
    flt = [{"tag": str(f[0]), "value": f[1], "ko": filter_ko(str(f[0]), f[1])} for f in sp.get("filter") or [] if isinstance(f, (list, tuple)) and len(f) == 2]
    disp = sp.get("disp")
    disp_ko = None
    if isinstance(disp, (list, tuple)) and len(disp) == 2:
        disp_ko = {"range": f"신호봉 높이 ATR {disp[1]:g}배 이상", "body": f"신호봉 몸통 ATR {disp[1]:g}배 이상",
                   "small": f"신호봉 높이 ATR {disp[1]:g}배 미만"}.get(str(disp[0]), str(disp[0]))
    numbers = sp.get("numbers") if isinstance(sp.get("numbers"), dict) else None
    return {"order": order, "strategy": sp.get("strategy") or sp.get("pick"), "tf": sp.get("tf"), "tf_ko": TF_KO.get(sp.get("tf"), sp.get("tf")),
            "numbers": numbers, "custom": numbers is not None, "entry": sp.get("entry", "now"),
            "entry_ko": "돌파 확인" if sp.get("entry") == "break" else "즉시", "invert": bool(sp.get("invert")),
            "stop": stop_ko(sp.get("stop"), cfg_stop), "filter": flt, "disp": disp_ko, "off": off, "cell": sp.get("cell"),
            "when": sp.get("when"), "no_chase": bool(sp.get("no_chase")),
            "no_chase_ko": f"{NO_CHASE_KO} ({NO_CHASE_WHY_KO})" if sp.get("no_chase") else None}


def member_of(members: list, order: Any, strategy: Any = None, tf: Any = None) -> Optional[dict]:
    """The setting a recorded entry came from: the one at its recorded number (``member_order``, from 1) when it is the same
    strategy and timeframe; else the only setting of that strategy and timeframe in the config now (a setting taken out of
    the list moves the ones after it up a number: owners 10/20 took 레인지 필터만 out); else None. Without a strategy: by
    the number alone."""
    o = _i(order)
    m = members[o - 1] if o and 0 < o <= len(members) else None
    if strategy is None:
        return m
    if m is not None and m.get("strategy") == strategy and (tf is None or m.get("tf") == tf):
        return m
    same = [x for x in members if x.get("strategy") == strategy and (tf is None or x.get("tf") == tf)]
    return same[0] if len(same) == 1 else None


def read_combo(paper_path: str, cfg_path: str) -> dict:
    """The combined bot's settings: the config it really runs (combo_run in its database) or, before its first start,
    the config file (/etc/paperbot/combo.json). Nothing is computed from strategy code."""
    run = None
    try:
        conn = open_ro(paper_path)
        try:
            if "state" in _tables(conn):
                r = conn.execute("SELECT ts, data FROM state WHERE k = 'combo_run'").fetchone()
                run = (_i(r[0]), _j(r[1])) if r else None
        finally:
            conn.close()
    except (OSError, sqlite3.Error):
        run = None
    if run and isinstance(run[1].get("config"), dict):
        return {"state": "ok", "source": "db", "path": paper_path, "since_ms": run[0], "config": run[1]["config"],
                "describe": run[1].get("members") if isinstance(run[1].get("members"), list) else None, "taker_fee": _f(run[1].get("taker_fee"))}
    try:
        with open(cfg_path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        return _missing(cfg_path, "합친 봇 설정이 아직 없어요 (봇의 DB에도, 설정 파일에도)")
    except ValueError as exc:
        return {**_err(cfg_path, exc), "reason_ko": "합친 봇 설정 파일이 JSON 모양이 아니에요"}
    except OSError as exc:
        return _err(cfg_path, exc)
    if not isinstance(raw, dict):
        return {"state": "error", "path": cfg_path, "reason": "not an object", "reason_ko": "합친 봇 설정 파일의 모양이 달라요"}
    return {"state": "ok", "source": "file", "path": cfg_path, "since_ms": None, "config": raw, "describe": None, "taker_fee": None}


def members_of(combo: dict) -> list:
    cfg = combo.get("config") or {}
    return [describe_member(sp, i, cfg.get("stop")) for i, sp in enumerate(cfg.get("members") or [], 1)]


# the entry gates and the hold limit of a combined bot ('VWAP 개선판', owners 10-23): the same words as the bot's own start
# message (paperbot/combo.py gate_lines with entrygates.vote_text / vol_text), worked out here from the config dict (this
# module reads the bots' records, never their code); tests/test_dash_live_vwap_existing.py holds them to gate_lines
GATE_TF_KO = {"15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간", "1d": "일봉"}
HOLD_TF_MIN = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}          # combo.TF_MIN: a member's bar in minutes


def hold_ko(minutes: int) -> str:
    """combo.hold_ko: "48시간" / "90분"."""
    return f"{minutes // 60}시간" if minutes % 60 == 0 else f"{minutes}분"


def gate_words(c: Optional[dict]) -> list:
    """[{id, ko}] of the config's entry gates (``vote_gate``, ``vol_gate``) and hold limit (``max_hold_bars``) in the
    owners' words (combo.gate_lines); [] when it has none (every bot before the 'VWAP 개선판')."""
    c = c if isinstance(c, dict) else {}
    out = []
    v = c.get("vote_gate")
    if isinstance(v, dict):
        v = {"tf": "4h", "vote_min": 3, **v}
        out.append({"id": "vote_gate", "ko": f"{GATE_TF_KO.get(v['tf'], v['tf'])} 추세 판단이 반대면 진입 안 함"
                                              f"(4개 중 {v['vote_min']}개 반대; 보류는 진입)"})
    v = c.get("vol_gate")
    if isinstance(v, dict):
        v = {"atr": 14, "days": 30, "q": 0.8, **v}
        q = float(v["q"])
        out.append({"id": "vol_gate", "ko": f"변동성(ATR{v['atr']}%)이 지난 {v['days']}일의 {q:.0%} 위치보다 크면 진입 안 함"
                                             f"(상위 {1 - q:.0%} 금지)"})
    n = c.get("max_hold_bars")
    if isinstance(n, int) and not isinstance(n, bool):
        tfs = sorted({str(m.get("tf")) for m in c.get("members") or [] if isinstance(m, dict) and m.get("tf") in HOLD_TF_MIN},
                     key=lambda tf: HOLD_TF_MIN[tf])
        each = " · ".join(f"{GATE_TF_KO[tf]} {hold_ko(n * HOLD_TF_MIN[tf])}" for tf in tfs)
        out.append({"id": "max_hold", "ko": f"보유 한도 {n}봉" + (f"({each})" if each else "") + ", 넘으면 시장가 청산"})
    return out


def rules_of(combo: dict) -> dict:
    """The fixed rules every setting shares, from the config. A config with entry gates or a hold limit (the 'VWAP
    개선판') carries them too (``vote_gate``, ``vol_gate``, ``max_hold_bars`` and their words ``gates``); every other config's
    answer is as it was."""
    c = combo.get("config") or {}
    lev = c.get("leverage") if isinstance(c.get("leverage"), dict) else {"BTCUSDT": 40, "default": 30}
    lad = c.get("ladder") if isinstance(c.get("ladder"), dict) else {}
    margin = c.get("margin", "leverage")
    out = {"leverage_btc": _i(lev.get("BTCUSDT")), "leverage_alt": _i(lev.get("default")), "margin": margin if isinstance(margin, str) else _f(margin),
           "ladder": ladder_numbers(lad), "max_loss_frac": _f(c.get("max_loss_frac")),
           "no_weekend": bool(c.get("no_weekend")), "macro_blackout_min": _i(c.get("macro_blackout_min")),
           "us_open_pause_min": _i(c.get("us_open_pause_min")), "us_open_pre_min": _i(c.get("us_open_pre_min")),
           "early_exit": c.get("early_exit"),
           "one_position": True, "initial_equity": _f(c.get("initial_equity")), "name": c.get("name"),
           "stop": stop_ko(None, c.get("stop") if isinstance(c.get("stop"), dict) else None),
           "rank": c.get("rank"), "flip_twin": bool(c.get("flip_twin", True))}
    gates = gate_words(c)
    if gates:
        out.update(vote_gate=c.get("vote_gate") if isinstance(c.get("vote_gate"), dict) else None,
                   vol_gate=c.get("vol_gate") if isinstance(c.get("vol_gate"), dict) else None,
                   max_hold_bars=_i(c.get("max_hold_bars")), gates=gates, time_ko=LP.time_exit_ko(c))
    rw = range_words(c)
    if rw:                                               # the 레인지 봇 (owners 10-26): its own rules and its fixed take-profit
        out.update(range=c.get("range"), range_rules=rw, take_profit_roe=_f(c.get("take_profit_roe")))
    return out


# the 레인지 봇's rule numbers when its config leaves one out (paperbot/rangebot.py RangeRules)
RANGE_DEFAULTS = {"pullback_atr": 0.2, "wait_min": 60, "coin_st": True, "btc_st": True, "st_period": 10, "st_mult": 3.0,
                  "liq_check": True, "liq_mmr": 0.005, "friend_tf": None}
# the friend's trend indicator check (owners 10-29, paperbot/rangebot.py FRIEND_WORDS)
RANGE_FRIEND_KO = ("친구 추세지표 1시간봉(하늘·보라 선·EMA RSI·찹존·슈퍼트렌드)이 신호와 같은 방향일 때만: 같은 추세 2개 이상이면 "
                   "그 추세, 횡보(찹존·슈퍼트렌드 노랑) 2개 이상이나 상승 2·하락 2면 진입 안 함")


def range_words(c: Any) -> list:
    """[{id, ko}] of a 레인지 봇 config's own rules in the owners' words (paperbot/rangebot.py RangeRules.describe, worked out
    here from the config dict: this module reads the bots' records, never their code; tests hold them to describe());
    [] for any other config."""
    r = c.get("range") if isinstance(c, dict) else None
    if not isinstance(r, dict):
        return []
    r = {**RANGE_DEFAULTS, **r}
    who = [w for w, on in (("코인", r["coin_st"]), ("BTC", r["btc_st"])) if on]
    st = " · ".join(([RANGE_FRIEND_KO] if r.get("friend_tf") else [])
                    + ([f"{'·'.join(who)} 1시간 슈퍼트렌드({r['st_period']}, {float(r['st_mult']):g})가 신호와 같은 방향일 때만"]
                       if who else [])) or "슈퍼트렌드 확인 없음"
    syms = [str(s).replace("USDT", "") for s in c.get("symbols") or [] if isinstance(s, str)] or ["BTC", "ETH", "SOL", "DOGE", "LTC", "BCH"]
    out = [{"id": "range_st", "ko": f"추세 확인: {st}"},
           {"id": "range_pull", "ko": f"되돌림 진입: 신호 1시간봉 종가에서 {float(r['pullback_atr']):g} ATR(14, 1시간) 되돌림을 최대 "
                                      f"{int(r['wait_min'])}분 기다림, 닿은 5분봉 다음 5분봉 시가에 시장가(안 오면 버림)"},
           {"id": "range_one", "ko": f"한 신호씩: 기다리는 동안·포지션 있는 동안 다른 신호 안 받음(같은 시각이면 {'→'.join(syms)} 순서)"}]
    if r["liq_check"]:
        out.append({"id": "range_liq", "ko": f"강제청산 여유: 손절 거리 + 1시간 ATR이 (1/배수 - {float(r['liq_mmr']):.1%}) 안쪽일 때만"})
    out.append({"id": "range_none", "ko": "진 뒤 쉬기·시간 청산·반대 신호 청산·신호등 없음"})
    return out


# ---------------------------------------------------------------- the paper bot's signals and outcomes (신호 · 거래)
# the 'VWAP 개선판' gates' reasons (paperbot/entrygates.py EntryGates._vote_block / _vol_block: "4시간 추세 반대: …",
# "4시간 추세 판단을 못 읽음(진입 안 함): …", "변동성 높음: ATR …"), their own categories (never the trend bot's judge)
GATE_TFS = ("15분 ", "30분 ", "1시간 ", "4시간 ", "일봉 ")
VOL_GATE_KO = "변동성 높음 (VWAP 조건)"


def why_cat(status: str, why: str) -> tuple:
    """(category id, Korean) of a FILTERED / WAITING / BROKE signal_log row (paperbot/combo.py: _allowed, _submit_due,
    _research_signal, _research_entry, _breaks)."""
    w = str(why or "")
    if status == "WAITING":
        if w.startswith("되돌림 기다림"):                 # the trend bot's pullback wait (paperbot/trendbot.py _divert)
            return "pullback_wait", "되돌림 기다림"
        return "waiting", "돌파 기다림"
    if status == "BROKE":
        if w.startswith("되돌림 확인"):
            return "pulled", "되돌림 확인 (진입 신호로 바뀜)"
        return "broke", "돌파 확인 (진입 신호로 바뀜)"
    # the 'VWAP 개선판' entry gates (paperbot/entrygates.py, owners 10-23): the higher bar's vote against the side (3 of 4,
    # never the trend bot's 보류 · 힘 약함 · 끝물) and a volatile signal bar; a gate that could not read its bars blocks too
    if w.startswith(GATE_TFS) and " 추세 반대: " in w:
        return "vote_gate", f"{w.split(' ', 1)[0]} 추세 반대 (VWAP 조건)"
    if w.startswith(GATE_TFS) and "추세 판단을 못 읽음" in w:
        return "trend_unread", "추세 판단 못 읽음"
    if w.startswith("변동성 높음"):
        return "vol_high", VOL_GATE_KO
    # the 레인지 봇 (owners 10-26, paperbot/rangebot.py _divert): one signal at a time, the supertrends, the liquidation room
    if w.startswith("한 신호씩"):
        return "range_one", "한 신호씩 (기다림·포지션 중)"
    if w.startswith("추세 확인: 친구 추세지표"):            # owners 10-29: the friend's trend indicator (1h)
        return "range_friend", "추세 확인 (친구 추세지표 반대·진입 금지)"
    if w.startswith("추세 확인:"):
        return "range_st", "추세 확인 (슈퍼트렌드 반대)"
    if w.startswith("강제청산 여유 부족"):
        return "range_liq", "강제청산 여유 부족"
    if w.startswith("슈퍼트렌드를 못 읽어"):
        return "range_unread", "슈퍼트렌드 못 읽음"
    if w.startswith("친구 추세지표를 못 읽어"):
        return "range_unread", "친구 추세지표 못 읽음"
    # the trend bot (paperbot/trendbot.py, trendjudge.check): its waits, its judge, its entry checks, its pauses
    if w.startswith("되돌림 안 옴"):
        return "nopull", "되돌림 안 옴"
    if w.startswith("되돌림 확인이 늦음"):
        return "late", "늦음"
    if w.startswith("추세 판단을 못 읽어") or w.startswith("추세 판단에 쓸 가격"):
        return "trend_unread", "추세 판단 못 읽음"
    if w.startswith(("1시간 추세", "4시간 추세", "일봉 추세")):          # 일봉: the 4h entries (10-22)
        return "trend", "추세 판단 (보류·반대·힘 약함·끝물)"
    if w.startswith("돌파형은 추세 초입만") or "EMA20에서" in w or " RSI " in f" {w}":
        return "spot", "진입 자리 검사"
    if w.startswith("하루 손실 한도"):
        return "daily", "하루 손실 한도"
    if "번 연속: " in w and "까지 쉼" in w:
        return "member_pause", "매매법 쉬는 중"
    if "손실 뒤" in w and "시간 쉼" in w:
        return "coin_pause", "코인·방향 쉬는 중"
    if w.startswith("추세판단 봇은"):
        return "config", "설정이 바뀜"
    if w.startswith("연구 조건 밖"):
        return "research", "연구 조건 밖"
    if w.startswith("끈 구간"):
        return "off", "끈 구간"
    if w.startswith("주말"):
        return "weekend", "주말 진입 안 함"
    if w.startswith("경제 발표"):
        return "macro", "경제 발표 앞뒤"
    if w.startswith("나스닥 개장"):                       # combo.py us_open_pause (us_open_pause_min): a pause like the two above
        return "usopen", "나스닥 개장 앞뒤" if w.startswith("나스닥 개장 앞") else "나스닥 개장 뒤"    # (us_open_pre_min, 10-21 night)
    if w.startswith("추격 진입 막기"):                     # combo.py _chase_block: a no_chase member's chase
        return "chase", "추격 진입 막기"
    if w.startswith("추격 판단"):                          # ... or one it could not tell (no entry either; before '못 읽음')
        return "chase_unread", "추격 판단 못 함"
    if w.startswith("돌파 없음"):
        return "nobreak", "돌파 없음"
    if w.startswith("돌파 확인이 늦음"):
        return "late", "늦음"
    if "못 읽음" in w:
        return "unread", "조건을 못 읽음"
    if w.startswith("조건 밖"):
        return "when", "조건 밖"
    if w.startswith("설정에 없는") or w.startswith("설정이 바뀌어"):
        return "config", "설정이 바뀜"
    return "other", w or "이유 기록 없음"


def why_words(why: Any) -> Optional[str]:
    """The bot's why of a filtered signal with its bucket codes in words ('끈 구간: hr=5, symside=7' -> '끈 구간: 시각 05시 · 코인x방향
    DOGE 롱'; '연구 조건 밖: weekend=0' -> '연구 조건 밖 (필요: 평일만)'); any other text as it is."""
    w = str(why or "")
    for head, kind in (("끈 구간: ", "off"), ("연구 조건 밖: ", "filter")):
        if not w.startswith(head):
            continue
        parts = []
        for item in w[len(head):].split(", "):
            k, sep, v = item.partition("=")
            if not sep:
                return w
            if kind == "off":
                parts.append(f"{DIM_KO.get(k, k)} {'읽기 실패' if v == '읽기 실패' else dim_value_ko(k, v)}")
            else:
                parts.append(filter_ko(k, v))
        return f"끈 구간: {' · '.join(parts)}" if kind == "off" else f"연구 조건 밖 (필요: {' · '.join(parts)})"
    return w or None


def outcome_cat(status: str, reason: str) -> tuple:
    """(category id, Korean) of an engine outcome (paperbot/engine.py _record, combo.py)."""
    r = str(reason or "")
    if status == "ENTERED":
        return "entered", "진입"
    if r == "in position":
        return "held", "포지션 있음 (한 번에 하나)"
    if r.startswith("lower score"):
        return "lost", "같은 때 다른 신호에 밀림"
    if r == "late":
        return "late", "늦음"
    if r == "stop rule":
        return "stoprule", "손절 자리가 안 맞음"
    if r == "sizing":
        return "sizing", "크기 계산 거절"
    if r.startswith("halted"):
        return "halted", "페이퍼 멈춤"
    if r.startswith("early exit"):
        return "early", "빠른 청산 분"
    if r.startswith("guard"):
        return "guard", "보호 장치"
    return "other", r or "이유 기록 없음"


def read_signals(path: str, account: str, now: int, keep: int = SIGNALS_KEEP) -> dict:
    """신호: every signal_log row of the combined bot and what became of it (its outcome for the account), counted per
    reason for today (KST) and the last 7 days, and the newest ``keep`` rows. The 추세판단 봇 (trend_bot): the counts start
    at its start (``bot_since``); the rows before it stay in the list flagged ``prev`` (the bot before it, 전환 전)."""
    tb = trend_bot(path)
    bot_since = tb["since"] if tb else None
    try:
        conn = open_ro(path)
    except FileNotFoundError:
        return _missing(path)
    except (OSError, sqlite3.Error) as exc:
        return _err(path, exc)
    since = kst_day_start(kst_day(now)) - 6 * DAY
    try:
        conn.execute("BEGIN")
        tables = _tables(conn)
        if "signal_log" not in tables:
            return _missing(path, NO_TABLE_KO)
        rows = conn.execute("SELECT id, bar_close, timeframe, strategy, symbol, side, status, data FROM signal_log WHERE bar_close >= ? "
                            "ORDER BY bar_close, id", (since,)).fetchall()
        outs = conn.execute("SELECT step_ts, status, reason, symbol, data FROM outcomes WHERE account_id = ? AND step_ts >= ? ORDER BY id",
                            (account, since)).fetchall() if "outcomes" in tables else []
    except sqlite3.Error as exc:
        return _err(path, exc)
    finally:
        conn.close()
    oc: dict = {}
    for step, st, reason, sym, data in outs:
        d = _j(data)
        sig = d.get("signal") if isinstance(d.get("signal"), dict) else {}
        meta = sig.get("meta") if isinstance(sig.get("meta"), dict) else {}
        k = (_i(sig.get("ts")), sig.get("timeframe"), meta.get("member") or sig.get("strategy_id"), sym)
        if k[0] is None:
            continue
        oc[(k[0] + 1, k[1], k[2], k[3])] = (st, reason, _i(step), meta.get("gates"))
    t0 = kst_day_start(kst_day(now))
    out_rows, counts = [], {"today": {}, "week": {}}
    for _id, bc, tf, strat, sym, side, status, data in rows:
        d = _j(data)
        o = None
        if status in ("FILTERED", "WAITING", "BROKE"):
            cat, ko = why_cat(status, d.get("why"))
            stage = "filtered" if status == "FILTERED" else status.lower()
        elif status == "SUBMITTED":
            o = oc.get((_i(bc), tf, strat, sym))
            if o:
                cat, ko = outcome_cat(o[0], o[1])
                stage = "entered" if o[0] == "ENTERED" else "skipped" if o[0] == "SKIPPED" else "rejected"
            else:
                cat, ko, stage = "pending", "제출됨 (결과 기록 전)", "submitted"
        else:
            cat, ko, stage = "other", str(status), "other"
        name = d.get("strategy") or str(strat).split("@")[0]
        row = {"id": _i(_id), "t": _i(bc), "tf": tf, "member": strat, "strategy": name, "symbol": sym, "side": _i(side), "status": status,
               "stage": stage, "cat": cat, "ko": ko, "why": d.get("why"), "why_ko": why_words(d.get("why")) if d.get("why") else None,
               "source": d.get("source"), "prev": bool(bot_since) and (_i(bc) or 0) < bot_since}
        g = d.get("gates") if isinstance(d.get("gates"), dict) else (o[3] if o else None)
        if isinstance(g, dict):                          # what the 'VWAP 개선판' gates read (only its rows have it)
            row["gates_ko"] = gates_text(g)
        out_rows.append(row)
        if row["prev"]:
            continue                                       # the bot before it: listed, never counted as this one's
        for span in ("week",) + (("today",) if (_i(bc) or 0) >= t0 else ()):
            c = counts[span].setdefault(cat, {"cat": cat, "ko": ko, "stage": stage, "n": 0})
            c["n"] += 1
    stages = {}
    for span in ("today", "week"):
        st_ = {"signals": 0, "filtered": 0, "entered": 0, "skipped": 0, "rejected": 0, "waiting": 0}
        for r in out_rows:
            if (span == "today" and (r["t"] or 0) < t0) or r["prev"]:
                continue
            if r["status"] == "BROKE":
                continue                                   # its entry signal is a SUBMITTED row of its own
            st_["signals"] += 1
            if r["stage"] in st_:
                st_[r["stage"]] += 1
        stages[span] = st_
    return {"state": "ok", "path": path, "since_ms": since, "today_ms": t0, "bot_since": bot_since,
            "counts": {k: sorted(v.values(), key=lambda c: -c["n"]) for k, v in counts.items()}, "stages": stages,
            "rows": out_rows[::-1][:keep], "n": len(out_rows)}


def gates_text(g: Any) -> Optional[str]:
    """What the 'VWAP 개선판' gates read for a signal (its row's ``gates``: combo.gates_text's words, "4시간 상승(상승 3·
    하락 0·중립 1) · 변동성 30분 ATR 0.45% (30일 80% 위치 0.62%)"), None when the row has none."""
    if not isinstance(g, dict):
        return None
    parts = [str((g.get(k) or {}).get("text") or "") for k in ("vote", "vol") if isinstance(g.get(k), dict)]
    return " · ".join(x for x in parts if x) or None


def bots_out(bots: list) -> list:
    """The paper bots a page can switch between: [{id, short_ko, label_ko}] (two only)."""
    return [{"id": b["id"], "short_ko": b["short_ko"], "label_ko": b["label_ko"]} for b in bots]


def signals(p: dict, now: int, bot: str = "paper") -> dict:
    """GET /api/v4/livebots/signals?bot=paper|paper2: read_signals of the main paper bot, or of the second one (owners
    10-23: the 'VWAP 개선판', its filtered signals with the gates' words). With one paper bot: exactly read_signals of the
    main one (``bot`` ignored). With two: plus ``bot`` (the one shown) and ``bots`` (the switch); a VWAP row carries the
    gates' words (``gates_ko``)."""
    _c, _f2, paper, execs = sources(p, now)
    bots = paper_bots(p, paper, execs)
    if len(bots) < 2:
        return read_signals(p["paper"], ACCOUNT, now)
    b = next((x for x in bots if x["id"] == bot), bots[0])
    out = read_signals(b["path"], ACCOUNT, now)
    out.update(bot=b["id"], bot_ko=b["short_ko"], bots=bots_out(bots))
    return out


def entered_meta(path: str, account: str) -> dict:
    """{(symbol, entry ms): the entered signal's meta} of the account: which setting (member, its order in the config),
    the stop rule, the score, the research tags. Read from the ENTERED outcomes (their step is the entry minute)."""
    try:
        conn = open_ro(path)
    except (OSError, sqlite3.Error):
        return {}
    try:
        if "outcomes" not in _tables(conn):
            return {}
        rows = conn.execute("SELECT step_ts, symbol, data FROM outcomes WHERE account_id = ? AND status = 'ENTERED'", (account,)).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    out = {}
    for step, sym, data in rows:
        d = _j(data)
        sig = d.get("signal") if isinstance(d.get("signal"), dict) else {}
        meta = sig.get("meta") if isinstance(sig.get("meta"), dict) else {}
        det = d.get("detail") if isinstance(d.get("detail"), dict) else {}
        tr = meta.get("trend") if isinstance(meta.get("trend"), dict) else {}      # the trend bot's judgment at the entry
        out[(sym, _i(step))] = {"member": meta.get("member"), "member_order": _i(meta.get("member_order")), "stop_rule": meta.get("stop_rule"),
                                "score": _f(sig.get("score")), "source": meta.get("source"), "fill": _f(det.get("fill")),
                                "ref_price": _f(meta.get("ref_price")), "break_level": _f(meta.get("break_level")),
                                "trend_strength": _i(tr.get("strength")), "trend_htf": tr.get("htf")}
    return out


# ---------------------------------------------------------------- 거래
def trade_rows(p: dict, now: int, more: Optional[dict] = None) -> dict:
    """GET /api/v4/livebots/trades: every closed trade of the three accounts (newest first, at most TRADES_KEEP each) with
    its setting, its reason, its costs and its partners on the other side (live <-> paper: same coin and side, entry within
    5 minutes; slippage = the live entry against the paper's, in the trade's favour positive). A losing paper trade carries
    its loss card (livecheck.db ``loss_cards``, made by the watcher a few minutes after the exit); a live trade carries the
    card of its paper partner."""
    more = more or paths_more()
    _configs, _follows, paper, execs = sources(p, now)
    bots = paper_bots(p, paper, execs)
    combo = read_combo(p["paper"], more["combo_config"])
    combos = {LP.norm(p["paper"]): combo}
    cards = read_cards(more["check_db"], now)
    card_by = {c["key"]: c for c in cards.get("cards") or []}

    def card_of(t: Optional[dict], path: Optional[str] = None) -> Optional[dict]:
        """The loss card of a paper trade: the main paper bot's under its key, the second's under its own (livecheck.card_key)."""
        if not t:
            return None
        from ... import livecheck as LC
        c = card_by.get(LC.card_key(ACCOUNT, t.get("symbol"), t.get("entry_time"), None if LP.same(path or p["paper"], p["paper"]) else path))
        if c is not None and c.get("exit_reason") == "TIME":       # its own bot's words (a hold limit is no supervisor)
            pr = (execs[0]["_papers"] if execs else {}).get(LP.norm(path or p["paper"])) or paper
            c = {**c, "exit_ko": exit_words("TIME", cfg_of(pr))}
        return c
    metas: dict = {}

    def meta_of(path: str) -> dict:
        k = LP.norm(path)
        if k not in metas:
            pr = (execs[0]["_papers"] if execs else {}).get(k) or (paper if LP.same(path, p["paper"]) else {})
            metas[k] = entered_meta(path, ACCOUNT) if pr.get("state") == "ok" else {}
        return metas[k]

    def members_at(path: str) -> list:
        k = LP.norm(path)
        if k not in combos:
            combos[k] = read_combo(path, more.get("combo2_config") or "-")
        c = combos[k]
        return members_of(c) if c.get("state") == "ok" else []
    members = members_at(p["paper"])
    rev = {x["id"]: rev_pairs(x) for x in execs}
    live_by = {x["id"]: {str(t["key"]): t for t in x["record"].get("trades") or []} for x in execs if x["record"].get("state") == "ok"}

    def setting(sym, et, path=None, strategy=None, tf=None):
        path = path or p["paper"]
        m = meta_of(path).get((sym, et)) or {}
        order = m.get("member_order")
        mem = member_of(members_at(path), order, strategy, tf)
        return {"member": m.get("member"), "order": order, "stop_rule": m.get("stop_rule"), "score": m.get("score"), "setting": mem,
                "break_level": m.get("break_level")}

    def paper_rows(b: dict) -> dict:
        """One paper bot's closed trades with, per executor, its partner (it followed this bot then), why not, or "other"
        (it followed the other paper bot then)."""
        pr, path = b["read"], b["path"]
        a = (pr.get("accounts") or {}).get(ACCOUNT) if pr.get("state") == "ok" else None
        if a is None:
            return {k: pr.get(k) for k in ("state", "reason_ko", "reason", "path")} if pr.get("state") != "ok" else \
                {"state": "missing", "reason_ko": "페이퍼 DB에 이 계좌의 기록이 아직 없어요"}
        ptrades = a.get("trades") or []
        rows = []
        for t in reversed(ptrades[-TRADES_KEEP:]):
            cells = {}
            for x in execs:
                lk = rev.get(x["id"], {}).get((LP.norm(path), t["id"]))
                if x["record"].get("state") != "ok":
                    cells[x["id"]] = {"state": "unknown"}
                elif lk is not None:
                    lt = live_by[x["id"]][lk]
                    sc = size_scale(x["config"], lt.get("qty"), t.get("qty"))      # size_from "equity": this trade's own ratio
                    cells[x["id"]] = {"state": "matched", "key": lt["key"], "pnl": lt["pnl"], "est": lt["est"], "entry_price": lt["entry_price"],
                                      "slip": (lt["side"] * (t["entry_price"] - lt["entry_price"]) / t["entry_price"]) if t.get("entry_price") and lt.get("entry_price") else None,
                                      "diff": (lt["pnl"] - t["pnl"] * sc) if lt.get("pnl") is not None and t.get("pnl") is not None and sc else None}
                elif not followed_at(x, path, t.get("entry_time")):
                    other = next((o for o in bots if LP.same(o["path"], LP.paper_at(x["segs"], t.get("entry_time")))), None)
                    cells[x["id"]] = other_cell(x, (other or {}).get("short_ko") or None)
                else:
                    cells[x["id"]] = why_missed(x["record"], t, ACCOUNT)
            rows.append({**{k: t.get(k) for k in ("id", "symbol", "side", "entry_time", "exit_time", "exit_reason", "leverage", "pnl", "roe",
                                                   "entry_price", "exit_price", "qty", "margin", "fees", "funding", "strategy_id", "timeframe",
                                                   "lock_roe", "stop_initial", "stop_price", "liq_price")},
                         "key": f"{b['id']}:{t['id']}", "reason_ko": exit_words(t["exit_reason"], cfg_of(pr), t.get("exit_why")),
                         "win": (t["pnl"] or 0) > 0,
                         "why": {"bot": b["id"], "symbol": t["symbol"], "entry": t["entry_time"]} if t.get("entry_time") is not None else None,
                         **setting(t["symbol"], t["entry_time"], path, t.get("strategy_id"), t.get("timeframe")), "live": cells,
                         "card": card_of(t, path)})
        return {"state": "ok", "rows": rows, "n": len(ptrades)}

    have = {s[0] for s in installed(p)}                 # (the Bybit slot only while no mix bot took it, owners 10-29)
    out = {"paper": None, **{ex: None for ex, _ko, _dk, _ck in EXECS if ex in have}}
    out["paper"] = paper_rows(bots[0])
    for b in bots[1:]:
        out[b["id"]] = {**paper_rows(b), "label_ko": b["label_ko"], "path": b["path"]}
    for x in execs:
        r = x["record"]
        if r.get("state") != "ok":
            out[x["id"]] = {k: r.get(k) for k in ("state", "reason_ko", "reason", "path")}
            continue
        rows = []
        pairs = pairs_of(x)
        for t in reversed((r.get("trades") or [])[-TRADES_KEEP:]):
            pt = pairs.get(str(t["key"]))
            reason = t["exit_reason"]
            if reason == "PAPER" and pt:
                reason = pt["exit_reason"] or reason
            # the paper's reason in its own bot's words (a TIME of the trend bot's supervisor or of a hold limit)
            words = exit_words(reason, cfg_of(_paper_of(x, pt["paper_path"])), pt.get("exit_why")) \
                if pt and reason == pt["exit_reason"] else EXIT_KO.get(reason, reason)
            scale = size_scale(x["config"], t.get("qty"), pt.get("qty") if pt else None)     # size_from "equity": this trade's own
            slip = (t["side"] * (pt["entry_price"] - t["entry_price"]) / pt["entry_price"]) if pt and pt.get("entry_price") and t.get("entry_price") else None
            rows.append({**{k: t.get(k) for k in ("key", "symbol", "side", "qty", "leverage", "entry_price", "pnl", "roe", "margin", "est",
                                                   "commission", "funding", "slippage", "stop_initial", "stop_final", "exit_raw")},
                         "entry_time": t["entry_ts"], "exit_time": t["exit_ts"], "exit_reason": reason, "reason_ko": words,
                         "win": (t["pnl"] or 0) > 0, "locked": bool(t.get("stop_final") and t.get("entry_price") and (t["stop_final"] - t["entry_price"]) * t["side"] > 0),
                         "paper": ({k: pt.get(k) for k in ("id", "entry_time", "exit_time", "entry_price", "exit_price", "pnl", "roe", "exit_reason", "lock_roe",
                                                             "strategy_id", "timeframe", "fees", "funding", "qty")}
                                   | ({"paper_id": bot_id(bots, pt["paper_path"])} if len(bots) > 1 else {}) if pt else None),
                         "paper_scaled": pt["pnl"] * scale if pt and pt.get("pnl") is not None and scale else None,
                         # a size_from "equity" trade's own factor (live qty / paper qty); "paper": the account's qty_scale
                         "size_scale": scale if x["config"].get("size_from") == "equity" else None,
                         "diff": (t["pnl"] - pt["pnl"] * scale) if pt and pt.get("pnl") is not None and t.get("pnl") is not None and scale else None,
                         "slip_vs_paper": slip, "gap_ms": abs(pt["entry_time"] - t["paper_time"]) if pt and t.get("paper_time") is not None else None,
                         "strategy_id": pt.get("strategy_id") if pt else None, "timeframe": pt.get("timeframe") if pt else None,
                         **(setting(pt["symbol"], pt["entry_time"], pt["paper_path"], pt.get("strategy_id"), pt.get("timeframe")) if pt
                            else {"member": None, "order": None, "setting": None}),
                         "card": card_of(pt, pt["paper_path"] if pt else None),
                         # 진입 근거: the paper entry this trade followed (dash/more/livewhy.py)
                         "why": {"bot": bot_id(bots, pt["paper_path"]), "symbol": pt["symbol"], "entry": pt["entry_time"]}
                         if pt and pt.get("entry_time") is not None and bot_id(bots, pt["paper_path"]) else None})
        out[x["id"]] = {"state": "ok", "rows": rows, "n": len(r.get("trades") or []), "qty_scale": x["config"].get("qty_scale"),
                        "size_from": x["config"].get("size_from") or "paper", "margin_frac": x["config"].get("margin_frac"),
                        "size_ko": size_ko(x["config"])}
    return {"now_ms": now, "accts": out, "match_ms": MATCH_MS, "combo_state": combo.get("state"), "members_n": len(members),
            "cards": {**{k: cards.get(k) for k in ("state", "reason_ko", "reason", "path")}, "n": len(card_by),
                      "kinds": [{"id": k, "ko": ko, "tone": tone} for k, ko, tone in CARD_KINDS]},
            # the 추세판단 봇's start: the page tags the trades entered before it (전환 전, the bot before it)
            "trend_bot": trend_out(trend_bot(p["paper"]))}


def why_missed(rec: dict, pt: dict, account: str) -> dict:
    """Why a paper trade has no live trade on this executor, from its own records (never a guess)."""
    since = rec.get("since_ms")
    if since and pt.get("entry_time") is not None and pt["entry_time"] < since:
        return {"state": "before", "why_ko": "실행기가 시작하기 전의 페이퍼 거래예요"}
    key = f"{account}|{pt.get('symbol')}|{pt.get('entry_time')}"
    pos = rec.get("position")
    if pos and pos.get("key") == key:
        return {"state": "open", "why_ko": "실거래 쪽은 아직 닫는 중이에요"}
    found = (rec.get("why") or {}).get(key) or {}
    for kind, ko in WHY:
        if kind in found:
            return {"state": "missed", "why_kind": kind, "why_ko": ko, "why_text": found[kind].get("text")}
    last = None
    for hh in rec.get("halts") or []:
        if hh.get("ts") is not None and pt.get("entry_time") is not None and hh["ts"] <= pt["entry_time"]:
            last = hh.get("action")
    if last == "halt":
        return {"state": "missed", "why_kind": "halted", "why_ko": "그때 실행기가 멈춰 있었어요"}
    return {"state": "missed", "why_kind": None, "why_ko": "실행기 기록에 이유가 없어요 (그때 실행기가 꺼져 있었을 수 있어요)"}


# ---------------------------------------------------------------- 성적
def rolling(trades: list, n: int) -> list:
    """[[exit ms, win share of the last n closed trades]] from the n-th trade on (fewer than n: no point)."""
    out, wins = [], []
    for t in trades:
        wins.append(1 if (_f(t.get("pnl")) or 0) > 0 else 0)
        if len(wins) >= n:
            out.append([_i(t.get("exit_time") if t.get("exit_time") is not None else t.get("exit_ts")), sum(wins[-n:]) / n])
    return thin(out)


def breakdown(trades: list, key) -> list:
    by: dict = {}
    for t in trades:
        k = key(t)
        if k is None:
            continue
        b = by.setdefault(k, [])
        b.append(t.get("pnl"))
    return sorted(({"key": k, **stats(v)} for k, v in by.items()), key=lambda r: (-r["trades"], str(r["key"])))


def perf_of(trades: list, t_entry: str = "entry_time", t_exit: str = "exit_time", roles: bool = False) -> dict:
    """The record of one account: totals, the rolling 20 / 40 win share, and per strategy, coin, timeframe, side and KST hour
    of the entry (표본 적음 flags from stats: under 20, then under 40); ``roles`` (the trend bot): per role too (TREND_ROLE:
    눌림 · 자리 · 돌파 · 횡보)."""
    norm = [{**t, "exit_time": t.get(t_exit), "entry_time": t.get(t_entry)} for t in trades]
    hour = lambda t: ((int(t["entry_time"]) + KST_MS) // HOUR) % 24 if t.get("entry_time") is not None else None   # noqa: E731
    out = {"stats": stats(t.get("pnl") for t in norm), "roll20": rolling(norm, 20), "roll40": rolling(norm, 40),
           "by_strategy": breakdown(norm, lambda t: t.get("strategy_id")), "by_coin": breakdown(norm, lambda t: t.get("symbol")),
           "by_tf": breakdown(norm, lambda t: t.get("timeframe")), "by_side": breakdown(norm, lambda t: t.get("side")),
           "by_hour": breakdown(norm, hour), "curve": thin([[t["exit_time"], c] for t, c in zip(norm, _cum(norm))])}
    if roles:
        out["by_role"] = breakdown(norm, lambda t: TREND_ROLE.get(t.get("strategy_id")) if t.get("strategy_id") else None)
    return out


def review_of(tb: dict, trades: list, now: int) -> dict:
    """The trend bot's 2-week review (owners 10-21: the rules stay unchanged 2 weeks from the start, then they look):
    the trades so far and the days left. No threshold: a new rule set has none (TREND_RULE_KO)."""
    st = stats(t.get("pnl") for t in trades)
    fu = tb.get("freeze_until")
    return {"since": tb.get("since"), "until": fu, "days": tb.get("freeze_days"), "n": st["trades"], "wins": st["wins"],
            "win_rate": st["win_rate"], "pnl": st["pnl"], "left_ms": (fu - now) if fu else None,
            "done": bool(fu and now >= fu), "rule_ko": TREND_RULE_KO}


def _cum(trades: list) -> list:
    c, out = 0.0, []
    for t in trades:
        c += _f(t.get("pnl")) or 0.0
        out.append(c)
    return out


def perf(p: dict, now: int, more: Optional[dict] = None) -> dict:
    """GET /api/v4/livebots/perf: the records, plus 매매법 성적표 (``scorecard``: liveimprove's own functions over the paper
    database now) and 개선 후보 장부 (``ledger``: liveimprove.db, read-only). The trend bot before its first closed trade:
    ``empty`` (trend_empty: the page shows one empty state with the replay's expectation, not tables of zeros)."""
    more = more or paths_more()
    _configs, _follows, paper, execs = sources(p, now)
    tb = trend_bot(p["paper"])
    since = tb["since"] if tb else None                    # the trend bot: its own trades only (the database keeps the bots before it)
    out = {}
    a = (paper.get("accounts") or {}).get(ACCOUNT) if paper.get("state") == "ok" else None
    mine = trend_since((a or {}).get("trades") or [], since)
    if a is not None:
        out["paper"] = {"state": "ok", **perf_of(mine, roles=bool(tb))}
    else:
        out["paper"] = {k: paper.get(k) for k in ("state", "reason_ko", "reason", "path")} if paper.get("state") != "ok" else {"state": "missing", "reason_ko": "기록 없음"}
    bots = paper_bots(p, paper, execs)
    for x in execs:
        r = x["record"]
        if r.get("state") != "ok":
            out[x["id"]] = {k: r.get(k) for k in ("state", "reason_ko", "reason", "path")}
            continue
        m = pairs_of(x)                                    # its own paper bot's trades (livepapers)
        # the trend bot's numbers: the trades it entered while it followed the trend bot (owners 10-23: an executor moved
        # to the 'VWAP 개선판' keeps its trend-bot trades here, its VWAP trades are that bot's)
        its = era_trades(x, p["paper"], since) if tb else trend_since(r.get("trades") or [], since, "entry_ts")
        live = []
        for t in its:                                      # the live trade takes its paper partner's strategy and timeframe
            pt = m.get(str(t["key"]))
            live.append({**t, "strategy_id": pt.get("strategy_id") if pt else None, "timeframe": pt.get("timeframe") if pt else None})
        out[x["id"]] = {"state": "ok", **perf_of(live, "entry_ts", "exit_ts", roles=bool(tb))}
        era = era_of(x, p["paper"], bots) if tb else None
        if era:
            out[x["id"]]["era"] = era
    for b in bots[1:]:                                     # the second paper bot's record next to the first's
        a2 = (b["read"].get("accounts") or {}).get(ACCOUNT) if b["read"].get("state") == "ok" else None
        out[b["id"]] = ({"state": "ok", **perf_of(a2.get("trades") or [])} if a2 and a2.get("known")
                        else {k: b["read"].get(k) for k in ("state", "reason_ko", "reason", "path")}) | {"label_ko": b["label_ko"],
                                                                                                       "short_ko": b["short_ko"]}
    flip = (paper.get("accounts") or {}).get(FLIP_ACCOUNT) if paper.get("state") == "ok" else None
    ref_ko = ref_problem(p["paper"])
    return {"now_ms": now, "accts": out, "refs": None if ref_ko else REFS, "refs_ko": ref_ko or None,
            "checkpoint": (checkpoint(mine, TREND_RULE_KO if tb else ref_ko) if a else None),
            "review": review_of(tb, mine, now) if tb and a is not None else None, "trend_bot": trend_out(tb),
            # the trend bot before its first closed trade: one empty state instead of tables of zeros
            "empty": trend_empty(tb, len(mine)) if a is not None else None,
            "flip": {"state": "ok", **perf_of(trend_since(flip.get("trades") or [], since))} if flip and flip.get("known") else None,
            "small": list(SMALL), "scorecard": scorecard(p, execs),
            # the ledger's candidates were found against the old bots' 5-year reference: not this bot's (TREND_LEDGER_KO)
            "ledger": {"state": "missing", "reason_ko": TREND_LEDGER_KO} if tb else read_ledger(more["improve_db"]), "papers": papers_out(bots),
            "compare": compare_papers(bots)}


# ---------------------------------------------------------------- 안전
def safety(p: dict, now: int, keep: int = 500, more: Optional[dict] = None) -> dict:
    """GET /api/v4/livebots/safety: per executor its halt, the limits its config really has, the kill file, the light now and
    every light_red / light_unread event, the halt log and its WARN / CRITICAL log (newest ``keep``); and the live checks
    (``checks``, livecheck.db read-only): the morning check's last 14 days and the watcher's alarm log."""
    more = more or paths_more()
    _configs, _follows, paper, execs = sources(p, now)
    out = []
    for x in execs:
        r, cfg = x["record"], x["config"]
        lights, log = [], []
        if r.get("state") == "ok":
            try:
                conn = open_ro(r["path"])
                try:
                    lights = [{"id": _i(i), "ts": _i(t), "kind": k, "kind_ko": KIND_KO.get(k, k), "text": txt, "data": _j(dd)} for i, t, k, txt, dd in conn.execute(
                        "SELECT id, ts, kind, text, data FROM events WHERE kind IN ('light_red', 'light_unread') ORDER BY id DESC LIMIT 200")]
                    log = [{"id": _i(i), "ts": _i(t), "level": lv, "level_ko": LEVEL_KO.get(lv, lv), "kind": k, "kind_ko": KIND_KO.get(k, k), "text": txt}
                           for i, t, lv, k, txt in conn.execute("SELECT id, ts, level, kind, text FROM events WHERE level IN ('WARN', 'CRITICAL') "
                                                                "AND kind != 'retry' ORDER BY id DESC LIMIT ?", (keep,))]
                finally:
                    conn.close()
            except (OSError, sqlite3.Error) as exc:
                r = {**r, "log_error": _err(r["path"], exc)}
        out.append({"id": x["id"], "name_ko": x["name_ko"], "config": cfg, "light": x["light"], "notes": x["notes"],
                    "record": {k: r.get(k) for k in ("state", "reason_ko", "reason", "path", "as_of_ms", "stale", "mode", "halted", "halt_reason",
                                                     "halted_ts", "consecutive_losses", "since_ms", "halts", "retry_24h", "log_error")},
                    "lights": lights, "log": log})
    return {"now_ms": now, "execs": out, "paper": {k: paper.get(k) for k in ("state", "reason_ko", "path", "as_of_ms", "stale")},
            "checks": read_checks(more["check_db"], now)}


# ---------------------------------------------------------------- 그림자
OLD_ERA_KO = "예전 봇(A+C 합본 · 규칙봇 15)의 설정을 바꾼 그림자예요. 지금 추세판단 봇과는 견주지 않아요"


def shadows(p: dict, now: int, units=None) -> dict:
    """GET /api/v4/livebots/shadows: ``trend`` the 추세판단 봇's own shadows, each next to the live paper bot from its own
    start, by trade and net ROE (dash/more/liveshadow.py); ``shadows`` the old bots' shadows (other settings of the
    combined bot before it, same database shape, account COMBO@mix) next to the live paper bot, each counted from the same
    start (the later of the two first records). While the live paper runs the trend bot an old shadow is compared only
    over the old bot's days (``until_ms``: the trend bot's start; ``no_overlap`` when it started later: its own record
    only)."""
    from . import liveshadow as LS                            # (liveshadow imports this module)
    more = paths_more()
    main = read_paper(p["paper"], [ACCOUNT], now)
    ma = (main.get("accounts") or {}).get(ACCOUNT) if main.get("state") == "ok" else None
    tb = trend_bot(p["paper"])
    end = tb["since"] if tb else None
    before = lambda ts: [t for t in ts if end is None or (t.get("entry_time") or 0) < end]   # noqa: E731
    out = []
    for sid, fname, ko in SHADOWS:
        path = os.path.join(more["shadow_dir"], fname)
        sh = read_paper(path, [ACCOUNT], now)
        row = {"id": sid, "name_ko": ko, "path": path, "state": sh.get("state"), "reason_ko": sh.get("reason_ko"), "reason": sh.get("reason")}
        sa = (sh.get("accounts") or {}).get(ACCOUNT) if sh.get("state") == "ok" else None
        if sh.get("state") == "ok" and not (sa and sa.get("known")):
            row.update(state="missing", reason_ko="이 그림자 DB에 아직 계좌 기록이 없어요")
        elif sa:
            start = max(x for x in (sa.get("since_ms"), (ma or {}).get("since_ms"), 0) if x is not None)
            apart = end is not None and start >= end             # turned on after the old bot ended: nothing to compare
            st_ = [t for t in sa.get("trades") or [] if (t.get("entry_time") or 0) >= start]
            st_ = st_ if apart else before(st_)
            mt = before([t for t in (ma or {}).get("trades") or [] if (t.get("entry_time") or 0) >= start]) if ma and not apart else None
            row.update(since_ms=start, as_of_ms=sh.get("as_of_ms"), stale=sh.get("stale"), name_cfg=sh.get("name_ko"),
                       stats=stats(t["pnl"] for t in st_), curve=thin([[t["exit_time"], c] for t, c in zip(st_, _cum(st_))]),
                       main=({"stats": stats(t["pnl"] for t in mt), "curve": thin([[t["exit_time"], c] for t, c in zip(mt, _cum(mt))])} if mt is not None else None),
                       position=sa.get("position"), until_ms=None if apart else end, no_overlap=apart,
                       later=(sum(1 for t in sa.get("trades") or [] if (t.get("entry_time") or 0) >= end) if end is not None and not apart else None))
        out.append(row)
    return {"now_ms": now, "trend": LS.trend_shadows(p, now, more["shadow_dir"], units),
            "vwap": LS.vwap_shadows(p, now, more["shadow_dir"], units), "shadows": out,
            "old_until_ms": end, "old_ko": OLD_ERA_KO,
            "main": {"state": main.get("state"), "reason_ko": main.get("reason_ko"),
            "since_ms": (ma or {}).get("since_ms"), "stats": (ma or {}).get("stats")},
            "start_ko": "sudo systemctl start " + " ".join(f"paperbot-combo-shadow@{sid}" for sid, _f, _k in SHADOWS),
            "dir": more["shadow_dir"]}


# ---------------------------------------------------------------- 설정
def _groups(members: list, roles: bool = False) -> list:
    """The settings grouped by strategy, the most settings first (a trend bot's carry their role)."""
    groups: dict = {}
    for m in members:
        groups.setdefault(m["strategy"], []).append({**m, "role": TREND_ROLE.get(m["strategy"])} if roles else m)
    return [{"strategy": k, "n": len(v), "tfs": sorted({m["tf"] for m in v}), "members": v}
            for k, v in sorted(groups.items(), key=lambda kv: (-len(kv[1]), str(kv[0])))]


def settings(p: dict, now: int) -> dict:
    """GET /api/v4/livebots/settings: the combined bot's fixed rules and its settings grouped by strategy (from the config it
    runs), each executor's light threshold and risk limits. With a second paper bot (owners 10-23: the 'VWAP 개선판' next to
    the 추세판단 봇) also its rules and settings (``bots``: its own config, its entry gates and hold limit in words) and
    which bot each executor follows (``follows_ko``); with one paper bot the answer is as before."""
    more = paths_more()
    combo = read_combo(p["paper"], more["combo_config"])
    configs = {ex: read_config(p[ck]) for ex, _ko, _dk, ck in installed(p)}
    execs = [{"id": ex, "name_ko": ko, "config": configs[ex]} for ex, ko, _dk, _ck in slots(configs)]
    _c, _f2, paper, srcs = sources(p, now)
    bots = paper_bots(p, paper, srcs)
    second = []
    if len(bots) > 1:                                    # who follows which bot, and the second bot's own rules
        by_ex = {x["id"]: x for x in srcs}
        for e in execs:
            x = by_ex.get(e["id"]) or {}
            if x.get("follows_ko"):
                e["follows_ko"] = x["follows_ko"]
        for b in bots[1:]:
            c2 = read_combo(b["path"], combo_fallback(more, b["id"]))
            item = {"id": b["id"], "short_ko": b["short_ko"], "label_ko": b["label_ko"], "followers": b["followers"],
                    "combo": {k: c2.get(k) for k in ("state", "reason_ko", "reason", "path", "source", "since_ms")}}
            if c2.get("state") == "ok":
                m2 = members_of(c2)
                item.update(rules=rules_of(c2), n_settings=len(m2), groups=_groups(m2),
                            n_strategies=len({m["strategy"] for m in m2}))
            second.append(item)
    if combo.get("state") != "ok":
        out = {"now_ms": now, "combo": {k: combo.get(k) for k in ("state", "reason_ko", "reason", "path")}, "execs": execs}
        return {**out, "bots": second} if second else out
    members = members_of(combo)
    tb = trend_bot(p["paper"]) if combo.get("source") == "db" else None
    groups = _groups(members, roles=bool(tb))
    out = {"now_ms": now, "combo": {"state": "ok", "source": combo["source"], "path": combo["path"], "since_ms": combo.get("since_ms")},
           "rules": rules_of(combo), "execs": execs, "n_settings": len(members), "n_strategies": len(groups),
           "groups": groups, "trend": trend_rules(tb)}
    if second:
        out.update(bots=second, name_ko=bots[0]["short_ko"])
    return out


def trend_rules(tb: Optional[dict]) -> Optional[dict]:
    """설정 › 추세 판단 규칙 (the trend bot only): its rules in its own words (state ``trend`` rules: TrendRules.describe), the
    numbers they come from, the members with their role and entry bar (30분 진입: the closed 1h bar's trend, 1시간 진입: the
    4h bar's, 4시간 진입: the daily bar's), and the pauses it does not have (owners 10-21 night "쉬기는 빼주고", "10번은 없애고")."""
    if tb is None:
        return None
    nums = tb.get("numbers") or {}
    no_pause = nums.get("member_losses") is None and nums.get("coin_pause_h") is None and nums.get("daily_loss") is None
    return {"name": tb["name"], "since": tb["since"], "freeze_until": tb["freeze_until"], "freeze_days": tb["freeze_days"],
            "rules": tb["rules"], "rules_ko": None if tb["rules"] else "봇이 아직 규칙을 기록하지 않았어요 (켠 뒤 1~2분)",
            "numbers": nums, "no_pause": no_pause if nums else None, "no_pause_ko": TREND_NO_PAUSE_KO if nums and no_pause else None,
            "members": [{**m, "tf_ko": TREND_TF_KO.get(m["tf"], TF_KO.get(m["tf"], m["tf"])),
                         "htf_ko": TREND_TF_SUB_KO.get(m["tf"])} for m in tb["members"]],
            "roles": [{"id": r, "sub_ko": TREND_ROLE_SUB_KO[r], "n": sum(1 for m in tb["members"] if m.get("role") == r)}
                      for r in TREND_ROLES],
            "pullback_wait": trend_waits(tb.get("config"))}


# ---------------------------------------------------------------- 순위 (매매법 순위표, owners 10/19)
RANK_SIG_KEEP = 100_000                # every signal row of the 7 days is counted (the page shows counts, not rows)
WEEKS_PER_MONTH = 30.44 / 7


def _bt_strategy(ref: Optional[dict], name: Any) -> Optional[dict]:
    """One strategy's 5-year numbers from deploy/combo.live-ac.expected.json ('fit' = fitted on the whole period, optimistic;
    'honest' = the twin fitted on 2020-24 only, read on unseen 2025-26)."""
    s = ((ref or {}).get("strategies") or {}).get(name) if isinstance(ref, dict) else None
    if not isinstance(s, dict):
        return None
    hon = s.get("honest_2025_26") if isinstance(s.get("honest_2025_26"), list) and len(s["honest_2025_26"]) == 2 else None
    w25 = s.get("win_2025_26") if isinstance(s.get("win_2025_26"), list) and len(s["win_2025_26"]) == 2 else None
    pm = _f(s.get("per_month"))
    return {"type_ko": s.get("type") or None, "trades": _i(s.get("trades")), "per_week": pm / WEEKS_PER_MONTH if pm is not None else None,
            "win": _f(s.get("win")), "contrib": _f(s.get("contrib")),
            "recent_n": _i(w25[0]) if w25 else None, "recent_win": _f(w25[1]) if w25 else None,
            "honest_n": _i(hon[0]) if hon else None, "honest_win": _f(hon[1]) if hon else None,
            "loss_roe_median": _f(s.get("loss_roe_median")), "win_roe_mean": _f(s.get("win_roe_mean")),
            "hours_to_win_median": _f(s.get("hours_to_win_median")), "hours_to_stop_median": _f(s.get("hours_to_stop_median")),
            "long_share": _f(s.get("long_share"))}


def _bt_member(ref: Optional[dict], order: Any) -> Optional[dict]:
    """A setting's own 5-year numbers (expected json ``members`` is keyed by the config position from 0; describe_member's
    order counts from 1)."""
    o = _i(order)
    m = ((ref or {}).get("members") or {}).get(str(o - 1)) if isinstance(ref, dict) and o else None
    if not isinstance(m, dict):
        return None
    return {"trades": _i(m.get("trades")), "win": _f(m.get("win")), "contrib": _f(m.get("contrib"))}


def _record(trades: list) -> dict:
    """n, wins, losses, net P&L, mean net ROE and the last exit of some closed trades."""
    s = stats(t.get("pnl") for t in trades)
    roes = [r for r in (_f(t.get("roe")) for t in trades) if r is not None]
    exits = [x for x in (_i(t.get("exit_time") if t.get("exit_time") is not None else t.get("exit_ts")) for t in trades) if x is not None]
    return {"n": s["trades"], "wins": s["wins"], "losses": s["losses"], "win_rate": s["win_rate"], "pnl": s["pnl"],
            "roe_avg": sum(roes) / len(roes) if roes else None, "last_exit_ms": max(exits) if exits else None}


def signals_by_strategy(sig: dict) -> dict:
    """{strategy: {week: {signals, <stage>: n}, today: {…}, last_ms, last_stage, last_ko}} of read_signals' rows."""
    sig_by: dict = {}
    if sig.get("state") != "ok":
        return sig_by
    t0 = sig.get("today_ms") or 0
    for r in sig.get("rows") or []:
        if r.get("status") == "BROKE":
            continue                                   # its entry signal is a SUBMITTED row of its own (as 신호 counts)
        s = sig_by.setdefault(r.get("strategy"), {"week": {}, "today": {}, "last_ms": None, "last_stage": None, "last_ko": None})
        for span in ("week",) + (("today",) if (r.get("t") or 0) >= t0 else ()):
            c = s[span]
            c["signals"] = c.get("signals", 0) + 1
            c[r.get("stage") or "other"] = c.get(r.get("stage") or "other", 0) + 1
        if s["last_ms"] is None or (r.get("t") or 0) > s["last_ms"]:
            s["last_ms"], s["last_stage"], s["last_ko"] = r.get("t"), r.get("stage"), r.get("ko")
    return sig_by


def rank(p: dict, now: int) -> dict:
    """GET /api/v4/livebots/rank: 매매법 순위표. Per strategy of the combined bot (from the config it runs): the paper account's
    closed trades and open position, each executor's followed trades (a live trade takes its paper partner's strategy),
    its signals of the last 7 KST days and what became of them, its 5-year numbers, and 매매법 성적표's status word. Nothing
    is ranked here: the page sorts (a ranking of few trades is mostly luck; it says so)."""
    combo = read_combo(p["paper"], paths_more()["combo_config"])
    if combo.get("state") != "ok":
        return {"now_ms": now, "combo": {k: combo.get(k) for k in ("state", "reason_ko", "reason", "path")}}
    _configs, _follows, paper, execs = sources(p, now)
    from ... import livecheck as LC
    ref_ko = None
    try:
        ref, ref_err = live_ref(p["paper"]), None
    except LC.RefConfigMismatch as exc:              # another config's reference: no 5-year numbers at all
        ref, ref_err, ref_ko = None, None, str(exc)
    except (OSError, ValueError) as exc:
        ref, ref_err = None, f"{type(exc).__name__}: {exc}"
    members = members_of(combo)
    tb = trend_bot(p["paper"])
    since = tb["since"] if tb else None                  # the trend bot: its own trades only (the bots before it are not it)
    groups: dict = {}
    for m in members:
        groups.setdefault(m["strategy"], []).append({**m, "bt": _bt_member(ref, m["order"]),
                                                     **({"role": TREND_ROLE.get(m["strategy"])} if tb else {})})
    acc = (paper.get("accounts") or {}).get(ACCOUNT) if paper.get("state") == "ok" else None
    ptrades = trend_since((acc or {}).get("trades") or [], since)
    pos = (acc or {}).get("position")
    live: dict = {}
    for x in execs:
        r = x["record"]
        if r.get("state") != "ok":
            continue
        m = pairs_of(x)                                  # a live trade takes the strategy of the paper trade IT followed
        for t in trend_since(r.get("trades") or [], since, "entry_ts"):
            pt = m.get(str(t["key"]))
            if pt is not None and not LP.same(pt["paper_path"], p["paper"]):
                continue            # it followed another paper bot then (owners 10-23: S3_CMO / F6_VWAP are in both bots)
            if pt is None and not followed_at(x, p["paper"], t.get("entry_ts")):
                continue
            live.setdefault((x["id"], pt.get("strategy_id") if pt else None), []).append(t)
    sig = read_signals(p["paper"], ACCOUNT, now, keep=RANK_SIG_KEEP)
    sig_by = signals_by_strategy(sig)
    card = scorecard(p, execs)
    status = {r.get("key"): r for r in card.get("rows") or []} if card.get("state") == "ok" else {}
    contribs = sorted(((s.get("contrib") or 0.0), k) for k, s in ((ref or {}).get("strategies") or {}).items() if k in groups)
    bt_rank = {k: i for i, (_c, k) in enumerate(reversed(contribs), 1)}
    rows = []
    for name, ms in groups.items():
        sc = status.get(name) or {}
        rows.append({
            "strategy": name, "in_config": True, "n_settings": len(ms), "tfs": sorted({m["tf"] for m in ms}, key=lambda t: TF_ORDER.get(t, 99)),
            "members": ms, "paper": _record([t for t in ptrades if t.get("strategy_id") == name]),
            "open": {k: pos.get(k) for k in ("symbol", "side", "leverage", "entry_time", "timeframe", "member", "last_mark_roe_net", "locked")}
            if pos and pos.get("strategy_id") == name else None,
            "live": {x["id"]: _record(live.get((x["id"], name), [])) for x in execs if x["record"].get("state") == "ok"},
            "sig": sig_by.get(name) or {"week": {}, "today": {}, "last_ms": None, "last_stage": None, "last_ko": None},
            "bt": _bt_strategy(ref, name), "bt_rank": bt_rank.get(name),
            "status": {k: sc.get(k) for k in ("status", "n", "win", "fit", "honest", "p")} if sc else None,
            **({"role": TREND_ROLE.get(name)} if tb else {})})
    unknown = sorted(k for k in {t.get("strategy_id") for t in ptrades} if k and k not in groups)
    for name in unknown:                   # traded under an earlier config: listed, marked, never mixed into the 27
        rows.append({"strategy": name, "in_config": False, "n_settings": 0, "tfs": sorted({t.get("timeframe") for t in ptrades if t.get("strategy_id") == name and t.get("timeframe")},
                                                                                         key=lambda t: TF_ORDER.get(t, 99)),
                     "members": [], "paper": _record([t for t in ptrades if t.get("strategy_id") == name]), "open": None,
                     "live": {x["id"]: _record(live.get((x["id"], name), [])) for x in execs if x["record"].get("state") == "ok"},
                     "sig": sig_by.get(name) or {"week": {}, "today": {}, "last_ms": None, "last_stage": None, "last_ko": None},
                     "bt": _bt_strategy(ref, name), "bt_rank": None,
                     "status": {k: (status.get(name) or {}).get(k) for k in ("status", "n", "win", "fit", "honest", "p")} if status.get(name) else None})
    return {"now_ms": now, "combo": {"state": "ok", "source": combo["source"], "path": combo["path"], "since_ms": combo.get("since_ms")},
            "paper": {k: paper.get(k) for k in ("state", "reason_ko", "reason", "path", "as_of_ms", "stale")},
            "signals": {k: sig.get(k) for k in ("state", "reason_ko", "reason", "path", "since_ms", "today_ms")},
            "ref": {"state": "ok" if ref is not None else "missing" if ref_ko else "error", "reason": ref_err,
                    "reason_ko": None if ref is not None else ref_ko or "5년 기준표(deploy/combo.live-ac.expected.json)를 못 읽었어요",
                    "break_even": _f((ref or {}).get("break_even_win")), "fit_win": _f((((ref or {}).get("overall") or {}).get("fit") or {}).get("win")),
                    "honest_win": _f((((ref or {}).get("overall") or {}).get("honest") or {}).get("win_2025_26"))},
            "scorecard": {k: card.get(k) for k in ("state", "reason_ko", "reason", "words", "small_n", "problems")},
            "execs": [{"id": x["id"], "name_ko": x["name_ko"], "state": x["record"].get("state")} for x in execs],
            "n_settings": len(members), "n_strategies": len(groups), "small": list(SMALL), "rows": rows,
            "unknown_strategies": unknown, "trend_bot": trend_out(tb),
            "open": {k: pos.get(k) for k in ("strategy_id", "symbol", "side", "timeframe", "entry_time")} if pos else None}


# ---------------------------------------------------------------- 일정 (경제 일정과 진입 쉬는 시간, owners 10/19)
CAL_BACK_DAYS = 3
CAL_AHEAD_DAYS = 21
CAL_TIMELINE_DAYS = 7
CAL_LOW_DAYS = 45                      # fewer registered days ahead than this: the page asks for next year's dates
KIND_INFO_KO = {"CPI": "미국 물가 발표. 예상과 다르면 금리 전망이 바뀌어 크게 움직이기 쉬워요",
                "FOMC": "미국 기준금리 결정. 발표 뒤 의장 기자회견(30분 뒤)까지 흔들리기 쉬워요",
                "NFP": "미국 일자리 숫자. 매달 첫 금요일 무렵, 크게 출렁이기 쉬워요",
                "PCE": "연준이 가장 보는 물가 지표. CPI보다는 덜하지만 움직일 수 있어요"}


def kst_weekend(ms: int) -> bool:
    """paperbot/combo.py kst_weekend, word for word (Saturday and Sunday, Korean time)."""
    return ((int(ms) + KST_MS) // DAY + 3) % 7 >= 5


def weekend_span(ms: int) -> tuple:
    """(start, end) of the KST weekend at or after ``ms`` (the one ms is in, if any): Saturday 00:00 to Monday 00:00 KST."""
    day = (int(ms) + KST_MS) // DAY
    dow = (day + 3) % 7                                    # Monday 0 .. Sunday 6
    sat = day + (5 - dow) if dow < 5 else day - (dow - 5)
    return sat * DAY - KST_MS, (sat + 2) * DAY - KST_MS


def calendar(p: dict, now: int) -> dict:
    """GET /api/v4/livebots/calendar: the US macro releases around now (data/macro_events.csv: the same file and the same
    ±macro_blackout_min window the paper bot uses), the KST weekend, the pause around each Nasdaq open when the running
    config has one (us_open_pre_min / us_open_pause_min: combo.us_open_pause's windows, ``usopen``), whether an entry may
    be made now by these rules, the pause windows of the next 7 days and how far ahead the release file reaches. The bot's own rules only: signals, the
    light and an open position decide the rest."""
    combo = read_combo(p["paper"], paths_more()["combo_config"])
    cfg = combo.get("config") or {} if combo.get("state") == "ok" else {}
    mins = _i(cfg.get("macro_blackout_min")) if combo.get("state") == "ok" else 30
    no_weekend = bool(cfg.get("no_weekend", True)) if combo.get("state") == "ok" else True
    # the Nasdaq open (owners 10-19 "개장하고 30분", 10-21 night "개장전 30분도": combo.us_open_pause): only when the running
    # config has it (an unread config draws the two rules above, said so on the page)
    us_min, us_pre = (_i(cfg.get("us_open_pause_min")) or 0, _i(cfg.get("us_open_pre_min")) or 0)
    w = (mins or 0) * 60_000
    try:
        from ... import events as EV
        evs, problems, ev_err = EV.all_events(), EV.problems(), None
    except Exception as exc:  # noqa: BLE001  the page says it could not be read
        evs, problems, ev_err = [], [], f"{type(exc).__name__}: {exc}"
    kind_ko = getattr(EV, "KIND_KO", {}) if ev_err is None else {}
    items = []
    for e in evs:
        if not (now - CAL_BACK_DAYS * DAY <= e.ts_ms <= now + CAL_AHEAD_DAYS * DAY):
            continue
        a, b = e.ts_ms - w, e.ts_ms + w
        items.append({"ts": e.ts_ms, "kind": e.kind, "kind_ko": kind_ko.get(e.kind, e.kind), "info_ko": KIND_INFO_KO.get(e.kind),
                      "pause_from": a if w else None, "pause_to": b if w else None, "url": getattr(e, "source_url", None),
                      "when": "past" if b < now else "now" if a <= now <= b and w else "soon" if e.ts_ms <= now + DAY else "later",
                      "weekend": kst_weekend(e.ts_ms)})
    macro_now = next((x for x in items if w and x["pause_from"] <= now <= x["pause_to"]), None)
    wk_now = no_weekend and kst_weekend(now)
    wk_a, wk_b = weekend_span(now)
    # the pause windows of the next 7 days, by start (overlapping ones are not merged here: the page merges them)
    spans = []
    if no_weekend:
        a, b = wk_a, wk_b
        while a < now + CAL_TIMELINE_DAYS * DAY:
            spans.append({"from": a, "to": b, "why": "weekend", "ko": "주말(토·일, 한국 시간)"})
            a, b = a + 7 * DAY, b + 7 * DAY
    for x in items:
        if w and x["pause_to"] >= now and x["pause_from"] < now + CAL_TIMELINE_DAYS * DAY:
            spans.append({"from": x["pause_from"], "to": x["pause_to"], "why": "macro", "ko": f"{x['kind_ko']} 앞뒤 {mins}분", "kind": x["kind"]})
    us_now, us_err = None, None
    if us_min or us_pre:
        from ... import combo as C
        from .liveinsight import us_open_windows        # (liveinsight imports this module)
        wins, us_err = us_open_windows(now, us_min, days=CAL_TIMELINE_DAYS + 1, pre=us_pre)
        for a, b in wins:
            sp = {"from": a, "to": b, "why": "usopen", "ko": C.us_open_ko(us_min, us_pre)}
            if a <= now < b:
                us_now = sp
            if b >= now and a < now + CAL_TIMELINE_DAYS * DAY:
                spans.append(sp)
    spans.sort(key=lambda s: s["from"])
    ends = [x for x in ((macro_now or {}).get("pause_to"), wk_b if wk_now else None, (us_now or {}).get("to")) if x is not None]
    edge = max([now] + ends)
    nxt = next((s for s in spans if s["from"] > edge), None)        # the next pause after the one now (if any)
    last = max((e.ts_ms for e in evs), default=None)
    paused = bool(wk_now or macro_now or us_now)
    pause_ko = None
    if paused:
        pause_ko = ("주말이라 진입 쉬는 중" if wk_now else f"{macro_now['kind_ko']} 발표 앞뒤 {mins}분이라 진입 쉬는 중" if macro_now
                    else f"{us_now['ko']}이라 진입 쉬는 중")
    return {"now_ms": now, "combo": {k: combo.get(k) for k in ("state", "reason_ko", "path", "source")},
            "rules": {"macro_blackout_min": mins, "no_weekend": no_weekend,
                      **({"us_open_pause_min": us_min or None, "us_open_pre_min": us_pre or None, "us_error": us_err}
                         if us_min or us_pre else {})},
            "events": {"state": "error" if ev_err else "ok", "reason": ev_err, "problems": problems,
                       "reason_ko": "경제 발표 일정 파일(data/macro_events.csv)을 못 읽었어요" if ev_err else None,
                       "last_ms": last, "days_left": (last - now) / DAY if last is not None else None,
                       "low": last is None or last - now < CAL_LOW_DAYS * DAY, "low_days": CAL_LOW_DAYS},
            "now": {"weekend": wk_now, "macro": macro_now, "usopen": us_now, "paused": paused,
                    "pause_until": max(ends) if paused else None, "pause_ko": pause_ko, "next": nxt},
            "weekend": {"from": wk_a, "to": wk_b}, "items": items, "spans": spans,
            "timeline": {"from": now, "to": now + CAL_TIMELINE_DAYS * DAY}}


# ---------------------------------------------------------------- 지도 (기대 범위 띠 + 장세 · 코인 · 시간대, owners 10/19)
BAND_MIN_N = 40                        # the band is drawn at least this far (the 40-trade checkpoint)
BAND_AHEAD = 20                        # and this many trades past the last closed trade
BAND_POINTS = 160                      # binomial quantiles are worked out at most at this many trade counts
BAND_QS = (0.05, 0.5, 0.95)
MAP_CUTS = ("reg5", "coin", "hb", "side")
REF_SPLIT = {"reg5": "by_reg5", "coin": "by_sym", "hb": "by_hb", "side": "by_side"}


def _logpmf(n: int, k: int, p: float) -> float:
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1) + k * math.log(p) + (n - k) * math.log1p(-p)


def binom_cdf(n: int, k: int, p: float) -> float:
    """P(X <= k), X ~ Binomial(n, p), summed in log space (exact; no scipy on the server)."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    return min(1.0, sum(math.exp(_logpmf(n, j, p)) for j in range(0, k + 1)))


def binom_quantiles(n: int, p: float, qs: tuple = BAND_QS) -> list:
    """The smallest k with P(X <= k) >= q for each q (X ~ Binomial(n, p)), one pass over k."""
    out, c, i = [], 0.0, 0
    qs = sorted(qs)
    for k in range(0, n + 1):
        c += math.exp(_logpmf(n, k, p))
        while i < len(qs) and c >= qs[i] - 1e-12:
            out.append(k)
            i += 1
        if i == len(qs):
            break
    while len(out) < len(qs):
        out.append(n)
    return out


def band_ns(n_max: int, points: int = BAND_POINTS) -> list:
    """Trade counts the band is worked out at: every count up to 60, then evenly spaced, the last always in."""
    if n_max <= points:
        return list(range(1, n_max + 1))
    head = list(range(1, 61))
    step = (n_max - 60) / (points - 60)
    tail = sorted({min(n_max, int(round(60 + step * i))) for i in range(1, points - 59)})
    return head + [n for n in tail if n > 60] + ([n_max] if tail[-1:] != [n_max] else [])


def cum_wins(trades: list, t_exit: str) -> list:
    """[[trade number, wins so far, exit ms]] in closing order."""
    out, w = [], 0
    for i, t in enumerate(sorted(trades, key=lambda t: (_i(t.get(t_exit)) or 0, str(t.get("id") or t.get("key") or ""))), 1):
        w += 1 if (_f(t.get("pnl")) or 0) > 0 else 0
        out.append([i, w, _i(t.get(t_exit))])
    return out


def band(ref: Optional[dict], lines: dict) -> dict:
    """기대 범위 띠: for trade counts 1..N, the 5th / 50th / 95th percentile of wins if each trade wins with the fitted rate
    (optimistic) and with the honest twin's unseen-2025-26 rate, the break-even line, and each account's wins so far.
    Below the honest band's 5th percentile is the drift alarm's line (livecheck drift_conditions)."""
    ov = (ref or {}).get("overall") or {}
    fit = _f((ov.get("fit") or {}).get("win"))
    hon = _f((ov.get("honest") or {}).get("win_2025_26"))
    be = _f((ref or {}).get("break_even_win"))
    n_max = max([BAND_MIN_N] + [len(v) + BAND_AHEAD for v in lines.values()])
    ns = band_ns(n_max)
    out = {"n_max": n_max, "ns": ns, "fit": fit, "honest": hon, "break_even": be, "qs": list(BAND_QS)}
    for name, p in (("fit_band", fit), ("honest_band", hon)):
        out[name] = [binom_quantiles(n, p) for n in ns] if p and 0 < p < 1 else None
    acts = {}
    for k, v in lines.items():
        n, w = (v[-1][0], v[-1][1]) if v else (0, 0)
        acts[k] = {"points": v, "n": n, "wins": w, "rate": w / n if n else None,
                   # how unusual the wins so far are under each rate (P(X <= wins)): small = fewer wins than that rate makes likely
                   "p_honest": binom_cdf(n, w, hon) if n and hon and 0 < hon < 1 else None,
                   "p_fit": binom_cdf(n, w, fit) if n and fit and 0 < fit < 1 else None}
    out["accounts"] = acts
    return out


def map_view(p: dict, now: int) -> dict:
    """GET /api/v4/livebots/map: 기대 범위 띠 (paper and each executor's wins so far against the 5-year bands) and the paper
    account's record by BTC 4h regime, coin, KST 4-hour block and side, each next to its 5-year number (liveimprove's
    own cuts: the same numbers and status words as ``score``). The trend bot (``trend_bot``): no band and no 5-year column
    (a new rule set has no backtest: ``band_ko`` says so), its own trades since its start split by the judgment it entered
    on, coin, KST 4-hour block, side and entry bar (``trend_map``)."""
    _configs, _follows, paper, execs = sources(p, now)
    tb = trend_bot(p["paper"])
    if tb is not None:
        return trend_map(p, now, tb, paper, execs)
    got = live_card(p, execs, MAP_CUTS)
    ref = got.get("ref") if got.get("state") == "ok" else None
    if ref is None:
        try:
            from ... import liveimprove as LI
            ref = LI.load_ref()
        except (OSError, ValueError):
            ref = None
    a = (paper.get("accounts") or {}).get(ACCOUNT) if paper.get("state") == "ok" else None
    lines = {}
    if a is not None:
        lines["paper"] = cum_wins(a.get("trades") or [], "exit_time")
    for x in execs:
        if x["record"].get("state") == "ok":
            lines[x["id"]] = cum_wins(x["record"].get("trades") or [], "exit_ts")
    bands = band(ref, lines) if ref else None
    fit = ((ref or {}).get("overall") or {}).get("fit") or {}
    cuts = {}
    for cut in MAP_CUTS:
        live_rows = {str(r.get("key")): r for r in (got["card"]["cuts"].get(cut) or [])} if got.get("state") == "ok" else {}
        split = dict(fit.get(REF_SPLIT[cut]) or {})
        if cut == "coin":                              # the reference counts coins by their place in ``symbols``
            syms = (ref or {}).get("symbols") or []
            split = {(syms[int(k)] if str(k).isdigit() and int(k) < len(syms) else k): v for k, v in split.items()}
        keys = list(split.keys()) + [k for k in live_rows if k not in split]
        rows = []
        for k in keys:
            bt = split.get(k)
            lr = live_rows.get(k) or {}
            rows.append({"key": k, "label": lr.get("label") or _map_label(ref, cut, k),
                         "bt_n": _i(bt[0]) if isinstance(bt, list) and len(bt) == 2 else None,
                         "bt_win": _f(bt[1]) if isinstance(bt, list) and len(bt) == 2 else None,
                         **{f: lr.get(f) for f in ("n", "wins", "win", "avg_roe", "pnl", "fit", "honest", "status", "p")},
                         "exec": {name: {kk: e.get(kk) for kk in ("n", "wins", "live_roe", "paper_roe")} for name, e in (lr.get("exec") or {}).items()}})
        cuts[cut] = rows
    return {"now_ms": now, "paper": {k: paper.get(k) for k in ("state", "reason_ko", "reason", "path", "as_of_ms")},
            "card": {k: got.get(k) for k in ("state", "reason_ko", "reason", "path", "problems")},
            "execs": [{"id": x["id"], "name_ko": x["name_ko"], "state": x["record"].get("state"), "reason_ko": x["record"].get("reason_ko")}
                      for x in execs],
            "band": bands, "cuts": cuts, "symbols": (ref or {}).get("symbols"), "reg5_names": (ref or {}).get("reg5_names")}


def _map_label(ref: Optional[dict], cut: str, k: Any) -> str:
    syms = (ref or {}).get("symbols") or []
    reg = (ref or {}).get("reg5_names") or list(REG5_CARD_KO)
    i = _i(k)
    if cut == "reg5" and i is not None and 0 <= i < len(reg):
        return reg[i]
    if cut == "coin":
        return str(syms[i] if i is not None and 0 <= i < len(syms) else k).replace("USDT", "")
    if cut == "hb" and i is not None:
        return f"{i * 4:02d}~{i * 4 + 4:02d}시"
    if cut == "side" and i is not None:
        return "롱" if i > 0 else "숏"
    return str(k)


# the trend bot's own split (no 5-year column: a new rule set has no backtest): id, title, subtitle
TREND_MAP_CUTS = (("judge", "진입 때 추세 판단", "판단 4개 중 진입 방향과 같은 쪽이 몇 개였나"), ("coin", "코인", "6개 코인"),
                  ("hb", "시간대", "한국 시간 4시간씩"), ("side", "방향", "롱 · 숏"), ("tf", "진입 봉", "30분 · 1시간 · 4시간 진입"))
TREND_MAP_MIN_N = 10                   # the map's own floor (liveimprove SMALL_N): fewer trades in a row = 표본 적음, grey


def _cut_row(key: Any, label: str, trades: list, pnl_key: str = "pnl", roe_key: str = "roe") -> dict:
    s = stats(t.get(pnl_key) for t in trades)
    roes = [r for r in (_f(t.get(roe_key)) for t in trades) if r is not None]
    return {"key": key, "label": label, "n": s["trades"], "wins": s["wins"], "losses": s["losses"], "win": s["win_rate"],
            "pnl": s["pnl"] if s["trades"] else None, "avg_roe": sum(roes) / len(roes) if roes else None,
            "small": s["trades"] < TREND_MAP_MIN_N}


def trend_map(p: dict, now: int, tb: dict, paper: dict, execs: list) -> dict:
    """지도 for the trend bot: each account's wins so far (no band: TREND_NO_REF_KO), and the paper account's trades since
    the trend bot's start by the judgment it entered on (4 of 4 judges or 3 of 4 on its side: the ENTERED signal's
    ``trend.strength``), coin, KST 4-hour block, side and entry bar. Live split only, small samples flagged. Before its
    first closed trade ``empty`` (trend_empty) says so once, with the replay's expectation."""
    since = tb["since"]
    a = (paper.get("accounts") or {}).get(ACCOUNT) if paper.get("state") == "ok" else None
    trades = sorted(trend_since((a or {}).get("trades") or [], since), key=lambda t: (_i(t.get("exit_time")) or 0, _i(t.get("id")) or 0))
    meta = entered_meta(p["paper"], ACCOUNT) if a is not None else {}
    vote_min = _i((tb.get("numbers") or {}).get("vote_min")) or 3
    syms = [s for s in (tb["config"].get("symbols") or COINS)]
    tfs = sorted({m["tf"] for m in tb["members"] if m.get("tf")} | {t.get("timeframe") for t in trades if t.get("timeframe")},
                 key=lambda t: TF_ORDER.get(t, 99))

    def strength(t):
        v = (meta.get((t.get("symbol"), _i(t.get("entry_time")))) or {}).get("trend_strength")
        return None if v is None else str(v)
    keyf = {"judge": strength, "coin": lambda t: t.get("symbol"),
            "hb": lambda t: str(((int(t["entry_time"]) + KST_MS) // HOUR % 24) // 4) if t.get("entry_time") is not None else None,
            "side": lambda t: str(int(t["side"])) if t.get("side") is not None else None, "tf": lambda t: t.get("timeframe")}
    keys = {"judge": [str(k) for k in range(4, vote_min - 1, -1)], "coin": syms, "hb": [str(k) for k in range(6)], "side": ["1", "-1"],
            "tf": tfs}
    # fewer than vote_min on its side: the entry went on a 보류 (owners 10-22 보류 허용: trend.hold_entry)
    label = {"judge": lambda k: "4개 모두 같은 쪽" if k == "4" else f"4개 중 {k}개" + (" (보류 진입)" if str(k).isdigit() and int(k) < vote_min else ""),
             "coin": lambda k: str(k).replace("USDT", ""),
             "hb": lambda k: f"{int(k) * 4:02d}~{int(k) * 4 + 4:02d}시", "side": lambda k: "롱" if k == "1" else "숏",
             "tf": lambda k: TREND_TF_KO.get(k, TF_KO.get(k, k))}
    cuts = {}
    for cut, _ko, _sub in TREND_MAP_CUTS:
        by: dict = {}
        for t in trades:
            by.setdefault(keyf[cut](t), []).append(t)
        ks = keys[cut] + sorted((str(k) for k in by if k is not None and str(k) not in keys[cut]), reverse=cut == "judge")
        rows = [_cut_row(k, label[cut](k), by.get(k, [])) for k in ks]
        if by.get(None):                                     # a trade whose cut could not be read: said, never dropped silently
            rows.append({**_cut_row(None, "기록 없음", by[None]), "unknown": True})
        cuts[cut] = rows
    lines = {}
    if a is not None:
        lines["paper"] = cum_wins(trades, "exit_time")
    bots = paper_bots(p, paper, execs)
    for b in bots[1:]:                                   # the second paper bot's own wins so far, next to the others (owners 10-23)
        a2 = (b["read"].get("accounts") or {}).get(ACCOUNT) if b["read"].get("state") == "ok" else None
        if a2 and a2.get("known"):
            lines[b["id"]] = cum_wins(a2.get("trades") or [], "exit_time")
    eras = {}
    for x in execs:
        if x["record"].get("state") == "ok":            # its trades while it followed the trend bot (era_trades)
            lines[x["id"]] = cum_wins(era_trades(x, p["paper"], since), "exit_ts")
            era = era_of(x, p["paper"], bots)
            if era:
                eras[x["id"]] = era
    n_max = max([10] + [v[-1][0] + 5 for v in lines.values() if v])
    acts = {k: {"points": v, "n": v[-1][0] if v else 0, "wins": v[-1][1] if v else 0,
                "rate": v[-1][1] / v[-1][0] if v else None, "p_honest": None, "p_fit": None} for k, v in lines.items()}
    for b in bots[1:]:
        if b["id"] in acts:
            acts[b["id"]]["label_ko"] = b["short_ko"]
    return {"now_ms": now, "kind": "trend", "trend_bot": trend_out(tb),
            "paper": {k: paper.get(k) for k in ("state", "reason_ko", "reason", "path", "as_of_ms")},
            "card": {"state": "ok"}, "band_ko": TREND_NO_REF_KO,
            "execs": [{"id": x["id"], "name_ko": x["name_ko"], "state": x["record"].get("state"), "reason_ko": x["record"].get("reason_ko"),
                       **({"era": eras[x["id"]]} if x["id"] in eras else {})} for x in execs],
            "band": {"trend": True, "n_max": n_max, "ns": [], "fit": None, "honest": None, "break_even": None, "qs": list(BAND_QS),
                     "fit_band": None, "honest_band": None, "accounts": acts},
            "cuts": cuts, "cut_defs": [{"id": c, "ko": ko, "sub": sub} for c, ko, sub in TREND_MAP_CUTS],
            "min_n": TREND_MAP_MIN_N, "small_n": SMALL[0], "n": len(trades), "symbols": syms, "reg5_names": None,
            "empty": trend_empty(tb, len(trades)) if a is not None else None}


# ---------------------------------------------------------------- 비용 (실거래가 페이퍼보다 얼마나 덜 버나, owners 10/19)
def costs(p: dict, now: int) -> dict:
    """GET /api/v4/livebots/costs: per executor, its closed trades next to the paper trade each followed: entry price gap
    (in the trade's favour positive), fees, funding, and the live P&L minus the paper's scaled to the live size. Plus the
    paper trades it did not follow and why (its own records). Read from the 거래 tab's own rows (trade_rows). Since 10/19
    night also 체결 비교 per executor (``gaps``: fill_gaps) and 진입 방식 판단 (``entry_judge``); since 10/21 night 수수료 줄이기
    (``fees``: dash/more/livefees.py)."""
    tr = trade_rows(p, now)
    accts = tr.get("accts") or {}
    out = {}
    have = installed(p)
    for ex, _ko, _dk, _ck in have:
        a = accts.get(ex) or {}
        if a.get("state") != "ok":
            out[ex] = {k: a.get(k) for k in ("state", "reason_ko", "reason", "path")}
            continue
        rows = a.get("rows") or []
        matched = [r for r in rows if r.get("paper")]
        slips = [r["slip_vs_paper"] for r in matched if r.get("slip_vs_paper") is not None]
        diffs = [r["diff"] for r in matched if r.get("diff") is not None]
        fees = [r["commission"] for r in rows if r.get("commission") is not None]
        fund = [r["funding"] for r in rows if r.get("funding") is not None]
        roe_gap = [(r["roe"] - r["paper"]["roe"]) for r in matched if r.get("roe") is not None and (r.get("paper") or {}).get("roe") is not None]
        by_coin: dict = {}
        for r in matched:
            c = by_coin.setdefault(r.get("symbol"), {"symbol": r.get("symbol"), "n": 0, "slip": [], "diff": 0.0})
            c["n"] += 1
            if r.get("slip_vs_paper") is not None:
                c["slip"].append(r["slip_vs_paper"])
            c["diff"] += r.get("diff") or 0.0
        coins = [{"symbol": c["symbol"], "n": c["n"], "slip_avg": sum(c["slip"]) / len(c["slip"]) if c["slip"] else None, "diff": c["diff"]}
                 for c in sorted(by_coin.values(), key=lambda c: -c["n"])]
        missed: dict = {}
        for pid in BOT_IDS:                              # each paper bot's trades it was following then (others say "other")
            for r in ((accts.get(pid) or {}).get("rows") or []):
                cell = (r.get("live") or {}).get(ex) or {}
                if cell.get("state") == "missed":        # before the executor's start, or still closing: not a miss
                    k = cell.get("why_kind") or "none"
                    m = missed.setdefault(k, {"kind": k, "ko": cell.get("why_ko") or k, "n": 0})
                    m["n"] += 1
        out[ex] = {"state": "ok", "n": len(rows), "matched": len(matched), "qty_scale": a.get("qty_scale"),
                   "size_from": a.get("size_from") or "paper", "margin_frac": a.get("margin_frac"), "size_ko": a.get("size_ko"),
                   "slip_avg": sum(slips) / len(slips) if slips else None, "slip_worst": min(slips) if slips else None,
                   "fees": sum(fees) if fees else None, "funding": sum(fund) if fund else None,
                   "diff_total": sum(diffs) if diffs else None, "diff_avg": sum(diffs) / len(diffs) if diffs else None,
                   "roe_gap_avg": sum(roe_gap) / len(roe_gap) if roe_gap else None,
                   "est_n": sum(1 for r in rows if r.get("est")), "coins": coins,
                   "missed": sorted(missed.values(), key=lambda m: -m["n"]),
                   "rows": [{k: r.get(k) for k in ("key", "symbol", "side", "entry_time", "exit_time", "pnl", "roe", "commission", "funding",
                                                   "slip_vs_paper", "diff", "paper_scaled", "est", "strategy_id", "timeframe", "reason_ko")}
                            | {"paper_roe": (r.get("paper") or {}).get("roe"), "qty": r.get("qty"), "entry_price": r.get("entry_price"),
                               "notional": r["qty"] * r["entry_price"] if r.get("qty") and r.get("entry_price") else None,
                               "paper_fees": (r.get("paper") or {}).get("fees"), "paper_funding": (r.get("paper") or {}).get("funding")}
                            for r in rows[:60]]}
    pa = accts.get("paper") or {}
    configs = {ex: read_config(p[ck]) for ex, _ko, _dk, ck in have}
    for ex, _ko, dk, _ck in have:                       # 체결 비교 (owners 10/19 night): added, nothing above changes
        if (out.get(ex) or {}).get("state") == "ok":
            cfg = configs[ex] if configs[ex].get("state") == "ok" else {}
            out[ex]["gaps"] = fill_gaps(p[dk], (accts.get(ex) or {}).get("rows") or [], cfg.get("exchange") or ex,
                                        cfg.get("ladder_from") or "paper")
    from . import livefees as LF                         # 수수료 줄이기 (owners 10/21 night): added, nothing above changes
    return {"now_ms": now, "paper": {"state": pa.get("state"), "n": pa.get("n"), "reason_ko": pa.get("reason_ko")},
            "execs": [{"id": ex, "name_ko": ko} for ex, ko, _dk, _ck in slots(configs)], "accts": out, "match_ms": MATCH_MS,
            "entry_judge": entry_judge(out, configs), "fees": LF.fees(p, now)}


# ---------------------------------------------------------------- 체결 비교 (owners 10/19 night: each live fill against the paper's)
PAPER_TAKER, PAPER_SLIP = 0.0005, 0.0002   # the paper rules' fee and slippage per side (paperbot/livepnl.py, config.v3_settings)
ENTRY_JUDGE_N = (10, 20)                   # owners 10/19: after 10-20 measured trades they decide whether the executors enter at
                                           # the signal time instead of following the paper's fill (the page shows numbers only)
WIN_REF = 0.10                             # a +10 % win (the first lock): the share of it an entry gap eats


def _avg(xs: list) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def fill_gaps(path: str, rows: list, exchange: str, ladder_from: str = "paper") -> dict:
    """Per executor (its 거래 rows, trade_rows): each closed trade's entry and exit fill against its paper partner's
    (paperbot/livecheck.py cost_row on the executor's own fills; the entry falls back to the trade's recorded entry
    price): the price gap in the trade's favour positive, the same in net ROE points at the trade's leverage (gap x
    leverage), the fee it really paid per side against the paper's 0.05 % (+ 0.02 % slippage, in the paper's fill
    already), and the averages. A gap that was not measured is None (체결 기록 전), never 0. An "own" executor's exit on
    its own stop or lock (``ladder_from`` "own", owners 10-20 "거래소 기준") is no fill gap: that exit is left out
    (``own_exit``), its entry counts."""
    from ... import livecheck as LC
    info = LC.ExecInfo(name=exchange, config="-", unit="-", db=path, light_n=0, light_min=0.0, exchange=exchange,
                       ladder_from=ladder_from)
    try:
        conn = open_ro(path)
    except FileNotFoundError:
        return _missing(path)
    except (OSError, sqlite3.Error) as exc:
        return _err(path, exc)
    out = []
    try:
        has = "fills" in _tables(conn)
        for r in rows:
            pt = r.get("paper")
            et = {"key": r.get("key"), "symbol": r.get("symbol"), "side": r.get("side"), "entry_ts": r.get("entry_time"),
                  "exit_ts": r.get("exit_time"), "entry_price": r.get("entry_price"), "commission": r.get("commission"),
                  "funding": r.get("funding"), "pnl": r.get("pnl"), "exit_reason": r.get("exit_raw")}
            fills = LC.exec_fills(conn, str(r.get("key"))) if has else []
            c = LC.cost_row(info, et, {"entry_price": pt.get("entry_price"), "exit_price": pt.get("exit_price"), "roe": pt.get("roe"),
                                       "strategy": pt.get("strategy_id") or "", "tf": pt.get("timeframe") or ""} if pt else None, fills)
            lev = _f(r.get("leverage"))
            ein = -c["entry_bps"] / 1e4 if c.get("entry_bps") is not None else None
            eout = -c["exit_bps"] / 1e4 if c.get("exit_bps") is not None else None
            fee = _f(c.get("fee_rate"))
            out.append({"key": r.get("key"), "symbol": r.get("symbol"), "side": r.get("side"), "leverage": r.get("leverage"),
                        "exit_time": r.get("exit_time"), "matched": pt is not None, "fills": c.get("fills"),
                        "own_exit": bool(c.get("own_exit")),
                        "entry_gap": ein, "exit_gap": eout, "entry_roe": ein * lev if ein is not None and lev else None,
                        "exit_roe": eout * lev if eout is not None and lev else None, "fee_rate": fee, "notional": _f(c.get("notional")),
                        "commission": _f(c.get("commission")),
                        "fee_roe": (PAPER_TAKER - fee) * 2 * lev if fee is not None and lev else None})
    except sqlite3.Error as exc:
        return _err(path, exc)
    finally:
        conn.close()
    fee_rows = [x for x in out if x["fee_rate"] is not None and x["notional"]]
    notional = sum(x["notional"] for x in fee_rows)
    s = {"n": len(out), "matched": sum(1 for x in out if x["matched"]),
         "entry_n": sum(1 for x in out if x["entry_gap"] is not None), "exit_n": sum(1 for x in out if x["exit_gap"] is not None),
         "fee_n": len(fee_rows), "entry_gap": _avg([x["entry_gap"] for x in out]), "exit_gap": _avg([x["exit_gap"] for x in out]),
         "entry_roe": _avg([x["entry_roe"] for x in out]), "exit_roe": _avg([x["exit_roe"] for x in out]),
         "fee_rate": sum(x["commission"] for x in fee_rows) / notional if notional else None,
         "fee_roe": _avg([x["fee_roe"] for x in out])}
    parts = [s["entry_roe"], s["exit_roe"], s["fee_roe"]]
    s["total_roe"] = sum(x for x in parts if x is not None) if any(x is not None for x in parts) else None
    s["total_parts"] = sum(1 for x in parts if x is not None)
    return {"state": "ok", "path": path, "exchange": exchange, **s, "rows": out[:60],
            "assumed": {"taker": PAPER_TAKER, "slip": PAPER_SLIP, "exchange_fee": LC.ASSUMED_FEE.get(exchange, LC.ASSUMED_FEE["binance"])}}


def gap_rows(x: dict, since: Optional[int] = None) -> list:
    """An executor's closed trades in fill_gaps' shape (trade_rows' fields), each with the paper trade it followed
    (pairs_of: its own paper bot's), entered from ``since`` on."""
    pairs = pairs_of(x)
    out = []
    for t in x["record"].get("trades") or []:
        if since is not None and (t.get("entry_ts") or 0) < since:
            continue
        pt = pairs.get(str(t["key"]))
        out.append({"key": t["key"], "symbol": t["symbol"], "side": t["side"], "entry_time": t["entry_ts"], "exit_time": t["exit_ts"],
                    "entry_price": t["entry_price"], "commission": t["commission"], "funding": t["funding"], "pnl": t["pnl"],
                    "leverage": t["leverage"], "exit_raw": t.get("exit_raw"),
                    "paper": {k: pt.get(k) for k in ("entry_price", "exit_price", "roe", "strategy_id", "timeframe", "pnl")} if pt else None})
    return out


def entry_judge(accts: dict, configs: dict) -> dict:
    """진입 방식 판단 (owners 10/19: after 10-20 trades they decide whether to enter at the signal time instead of following
    the paper fill): per executor how many entries were measured, the average entry gap in net ROE points and the share
    of a +10 % win it eats. Numbers only: no threshold, the decision is the owners'."""
    out = []
    for ex, ko, _dk, _ck in slots(configs):
        g = (accts.get(ex) or {}).get("gaps") or {}
        cfg = configs.get(ex) or {}
        er = g.get("entry_roe") if g.get("state") == "ok" else None
        out.append({"id": ex, "name_ko": ko, "state": g.get("state") or (accts.get(ex) or {}).get("state"), "n": g.get("entry_n") or 0,
                    "entry_roe": er, "entry_gap": g.get("entry_gap") if g.get("state") == "ok" else None,
                    "share_of_win": (-er / WIN_REF) + 0.0 if er is not None else None,     # + 0.0: never a "-0"
                    "entry_source": cfg.get("entry_source") if cfg.get("state") == "ok" else None})
    return {"need": list(ENTRY_JUDGE_N), "win_ref": WIN_REF, "rows": out,
            "who_ko": "판단은 두 분이 해요: 이 화면은 숫자만 보여 드려요"}


# ---------------------------------------------------------------- 분석팀 (실거래 분석 팀, owners 10/19)
TEAM_UNIT = "paperbot-liveteam.timer"
TEAM_KEEP = 40
TEAM_ON_KO = "sudo systemctl enable --now paperbot-liveteam.timer"
TEAM_OFF_KO = "sudo systemctl disable --now paperbot-liveteam.timer"


def team(p: dict, now: int, units=None) -> dict:
    """GET /api/v4/livebots/team: the 실거래 분석 팀 (paperbot/liveteam.py) read-only from its own liveteam.db: the members,
    the newest meetings with every member's words, the lead's conclusion and the ideas, the AI used today and in 7 days,
    whether its timer is on, the login check, and when the next meetings come. The 추세판단 봇 (trend_bot): the members'
    focus on it (liveteam.roles), its own trades for the next 거래 점검 (no 88 % rule), ``bot`` for the tab's words."""
    from ... import liveteam as T
    path = os.environ.get(T.DB_ENV) or T.DB_DEFAULT
    tb = trend_bot(p["paper"])                           # the 추세판단 봇: its members' focus, its own trades, 거래 점검
    roster = [{"id": k, **v} for k, v in T.roles(tb is not None).items()]
    try:
        budget, budget_err = T.parse_budget(os.environ.get(T.BUDGET_ENV)), None
    except ValueError as exc:
        budget, budget_err = dict(T.BUDGET_DEFAULT), str(exc)
    if units is None:
        from ... import livecheck as LC
        units = LC.unit_state
    active, enabled = units(TEAM_UNIT)
    timer = {"unit": TEAM_UNIT, "active": active or None, "enabled": enabled or None, "on": active == "active",
             "on_cmd": TEAM_ON_KO, "off_cmd": TEAM_OFF_KO}
    m9 = T.monday_09(now)
    nxt = m9 + 7 * DAY + (T.WEEKLY_HOUR - 9) * HOUR if now >= m9 + (T.WEEKLY_HOUR - 9) * HOUR else m9 + (T.WEEKLY_HOUR - 9) * HOUR
    paper_n = None
    try:
        pc = open_ro(p["paper"])
        try:
            if "trades" not in _tables(pc):
                got = None
            elif tb:                                     # the trend bot's own trades (entered since its start)
                got = pc.execute("SELECT COUNT(*) FROM trades WHERE account_id = ? AND entry_time >= ?",
                                 (ACCOUNT, int(tb["since"] or 0))).fetchone()
            else:
                got = pc.execute("SELECT COUNT(*) FROM trades WHERE account_id = ?", (ACCOUNT,)).fetchone()
            paper_n = _i(got[0]) if got else None
        finally:
            pc.close()
    except (OSError, sqlite3.Error):
        paper_n = None
    when = {"weekly_next_ms": nxt, "paper_n": paper_n, "checkpoint_every": T.CHECK_EVERY,
            "checkpoint_next": ((paper_n or 0) // T.CHECK_EVERY + 1) * T.CHECK_EVERY if paper_n is not None else None,
            "loss_rule_ko": "실거래 실행기의 마지막 닫힌 거래 2개가 모두 손실이면 (3일 안)",
            "checkpoint_ko": T.TREND_CHECK_KO if tb else T.KIND_KO["checkpoint"]}
    if tb:
        when.update(checkpoint_sub_ko=f"새 봇 시작 뒤 페이퍼 닫힌 거래 {T.CHECK_EVERY}번마다 · 88% 같은 기준 없음",
                    loss_rule_ko="실거래 실행기의 마지막 닫힌 거래 2개가 모두 손실이면 (3일 안, 새 봇 시작 뒤 거래만)")
    base = {"now_ms": now, "path": path, "roster": roster, "kinds": T.KIND_KO, "verdicts": list(T.VERDICTS), "timer": timer,
            "budget": budget, "budget_error": budget_err, "when": when, "small_n": T.SMALL_N,
            "bot": {"trend": True, "name": tb["name"], "since": tb["since"], "about_ko": T.TREND_ABOUT_KO,
                    "idea_how_ko": T.TREND_IDEA_HOW_KO} if tb else None}
    try:
        conn = open_ro(path)
    except FileNotFoundError:
        return {**base, **_missing(path, "분석팀 기록 파일이 아직 없어요 (분석팀을 켜고 첫 회의가 열리면 생겨요)")}
    except (OSError, sqlite3.Error) as exc:
        return {**base, **_err(path, exc)}
    try:
        conn.execute("BEGIN")
        if "meetings" not in _tables(conn):
            return {**base, **_missing(path, NO_TABLE_KO)}
        ms = conn.execute("SELECT id, kind, key, title, started_ts, finished_ts, state, why, headline, verdict, result, sent, calls, "
                          "tokens, dry FROM meetings ORDER BY id DESC LIMIT ?", (TEAM_KEEP,)).fetchall()
        ids = [m[0] for m in ms] or [-1]
        q = ",".join("?" * len(ids))
        msgs = conn.execute(f"SELECT meeting, seq, role, ts, text, error, tokens FROM messages WHERE meeting IN ({q}) ORDER BY meeting, seq",
                            ids).fetchall()
        ideas = conn.execute(f"SELECT id, meeting, ts, idea, why, test, status FROM ideas WHERE meeting IN ({q}) ORDER BY id", ids).fetchall()
        day = T.kst_date(now)
        u_day = conn.execute("SELECT COALESCE(SUM(calls),0), COALESCE(SUM(tokens),0) FROM usage WHERE day = ?", (day,)).fetchone()
        u_week = conn.execute("SELECT COALESCE(SUM(calls),0) FROM usage WHERE ts >= ?", (now - 7 * DAY,)).fetchone()
        st = {r[0]: (_i(r[1]), _j(r[2])) for r in conn.execute("SELECT k, ts, data FROM state")}
    except sqlite3.Error as exc:
        return {**base, **_err(path, exc)}
    finally:
        conn.close()
    by_m: dict = {}
    for mid, seq, role, ts, text, error, tok in msgs:
        r = T.ROLES.get(role) or {}
        by_m.setdefault(mid, []).append({"seq": _i(seq), "role": role, "name": r.get("name"), "title": r.get("title"), "ts": _i(ts),
                                         "text": text or "", "error": error, "tokens": _i(tok)})
    idea_by: dict = {}
    trend_ms = {m[0] for m in ms if tb and (_i(m[4]) or 0) >= int(tb["since"] or 0)}     # meetings held on the trend bot
    vwap_ms = {m[0] for m in ms if T.kind_ko(m[1], m[2]).startswith("VWAP")}             # the VWAP bot's own (owners 10-25)
    for iid, mid, ts, idea, why, test, status in ideas:
        how = T.VWAP_IDEA_HOW_KO if mid in vwap_ms else T.TREND_IDEA_HOW_KO if mid in trend_ms else None
        idea_by.setdefault(mid, []).append({"id": _i(iid), "ts": _i(ts), "idea": idea, "why": why, "test": test, "status": status,
                                            **({"how_ko": how} if how else {})})
    meetings = []
    for mid, kind, key, title, s0, s1, state, why, head, verdict, result, sent, calls, tokens, dry in ms:
        meetings.append({"id": _i(mid), "kind": kind, "kind_ko": T.kind_ko(kind, key), "key": key, "title": title, "started_ts": _i(s0),
                         "finished_ts": _i(s1), "state": state, "why": why, "headline": head, "verdict": verdict, "result": _j(result),
                         "sent": None if sent is None else bool(sent), "calls": _i(calls), "tokens": _i(tokens), "dry": bool(dry),
                         "messages": by_m.get(mid, []), "ideas": idea_by.get(mid, [])})
    auth = st.get("auth")
    tick = st.get("tick")
    return {**base, "state": "ok", "meetings": meetings,
            "usage": {"day_calls": _i(u_day[0]), "day_tokens": _i(u_day[1]), "week_calls": _i(u_week[0])},
            "auth": {"ts": auth[0], **(auth[1] or {})} if auth else None, "last_tick": {"ts": tick[0], **(tick[1] or {})} if tick else None,
            "ideas_open": sum(1 for v in idea_by.values() for i in v if i["status"] == "제안")}


# ---------------------------------------------------------------- ⏳ 진입 대기 (owners 10/19)
TF_MS_LB = {"15m": 15 * 60_000, "30m": 30 * 60_000, "1h": HOUR, "4h": 4 * HOUR}


def pending(p: dict, now: int, members: Optional[list] = None, trend: bool = False, pull: bool = True) -> dict:
    """진입 대기: the combined bot's signals still waiting (paperbot/livecheck.py pending_entries: ``kind`` "break" — the
    level the price must trade beyond — or "pullback" — the 추세판단 봇's level the price must come back to —, the last 1m
    close, how far to go, the deadline), and when each timeframe's next bar closes (when the bot next looks for signals)
    with how many settings run on it ("now" / "break"; with ``trend`` every member enters on a pullback, "pull", when its
    config waits (``pull``: trend_waits), else at its signal, "now": the owners' config since 10-22)."""
    from ... import livecheck as LC
    more = paths_more()
    try:
        pc = open_ro(p["paper"])
    except FileNotFoundError:
        return {**_missing(p["paper"]), "waits": [], "closes": []}
    except (OSError, sqlite3.Error) as exc:
        return {**_err(p["paper"], exc), "waits": [], "closes": []}
    rc, rule_state = None, "ok"
    try:
        rc = open_ro(more["rule_db"])
    except FileNotFoundError:
        rule_state = "missing"
    except (OSError, sqlite3.Error):
        rule_state = "error"
    try:
        pc.execute("BEGIN")
        waits = LC.pending_entries(pc, rc, now) if "signal_log" in _tables(pc) else []
    finally:
        pc.close()
        if rc is not None:
            rc.close()
    for w in waits:
        w["left_ms"] = w["until"] - now
    by_tf: dict = {}
    for m in members or []:
        t = m.get("tf")
        if t in TF_MS_LB:
            c = by_tf.setdefault(t, {"tf": t, "now": 0, "break": 0, "pull": 0})
            c[("pull" if pull else "now") if trend else "break" if m.get("entry") == "break" else "now"] += 1
    closes = [{**c, "next_ms": (now // TF_MS_LB[t] + 1) * TF_MS_LB[t]} for t, c in sorted(by_tf.items(), key=lambda kv: TF_MS_LB[kv[0]])]
    return {"state": "ok", "waits": waits, "closes": closes, "rule_state": rule_state, "rule_path": more["rule_db"]}


# ---------------------------------------------------------------- 지금 (왜 지금 진입 안 하나, owners 10/19)
def whynow(p: dict, now: int) -> dict:
    """GET /api/v4/livebots/now: what stands between now and the next live entry, in the order the bots check it: the
    weekend, macro and Nasdaq-open pause (calendar), the paper bot alive, a position already open (one at a time), each executor
    running, not halted, its light, then the only thing left: a signal. Read-only; never a guess."""
    from ... import livecheck as LC
    configs, follows, paper, execs = sources(p, now)
    cal = calendar(p, now)
    items = []

    def add(id_, ok, ko, detail=None, who=None, tone=None):
        items.append({"id": id_, "ok": ok, "ko": ko, "detail": detail, "who": who, "tone": tone or ("ok" if ok else "warn" if ok is None else "stop")})

    cn = cal.get("now") or {}
    rules = cal.get("rules") or {}
    if rules.get("no_weekend"):
        add("weekend", not cn.get("weekend"), "주말이 아님" if not cn.get("weekend") else "주말(토·일 한국 시간)이라 진입 쉼",
            None if not cn.get("weekend") else {"until": (cal.get("weekend") or {}).get("to")})
    if rules.get("macro_blackout_min"):
        m = cn.get("macro")
        add("macro", m is None, "미국 경제 발표 앞뒤 시간이 아님" if m is None else f"{m['kind_ko']} 발표 앞뒤 {rules['macro_blackout_min']}분이라 진입 쉼",
            {"until": m["pause_to"], "ts": m["ts"]} if m else None)
    if rules.get("us_open_pause_min") or rules.get("us_open_pre_min"):
        u = cn.get("usopen")
        add("usopen", u is None, "나스닥 개장 앞뒤 시간이 아님" if u is None else f"{u['ko']}이라 진입 쉼", {"until": u["to"]} if u else None)
    if cal.get("events", {}).get("state") != "ok":
        add("macro_file", None, "경제 발표 일정 파일을 못 읽음(봇도 같은 파일을 봐요)")
    if paper.get("state") != "ok":
        add("paper", False, "페이퍼 봇 기록을 못 읽음", {"reason_ko": paper.get("reason_ko")})
    else:
        add("paper", not paper.get("stale"), "페이퍼 봇이 돌고 있음" if not paper.get("stale") else "페이퍼 봇 기록이 멈춤(5분 넘게 새 기록 없음)",
            {"as_of": paper.get("as_of_ms")})
        acc = (paper.get("accounts") or {}).get(ACCOUNT) or {}
        pos = acc.get("position")
        add("position", pos is None, "포지션이 비어 있음" if pos is None else "이미 포지션이 있어 새 진입 안 함(한 번에 하나)",
            {k: pos.get(k) for k in ("symbol", "side", "strategy_id", "timeframe", "entry_time", "last_mark_roe_net")} if pos else None)
        if acc.get("halted"):
            add("paper_halt", False, "페이퍼 계좌가 멈춤", {"reason": acc.get("halt_reason")})
    for b in paper_bots(p, paper, execs)[1:]:            # the other paper bots (the second, the 레인지 봇), while an executor follows
        if not b["follower_ids"]:
            continue
        pr, who, nm = b["read"], ",".join(b["follower_ids"]), b["short_ko"]
        bw = nm if str(nm).endswith("봇") else f"{nm} 봇"     # "VWAP 개선판 봇", "레인지 봇" (one 봇)
        pid, posid = b["id"], "position2" if b["id"] == "paper2" else f"position_{b['id']}"
        if pr.get("state") != "ok":
            add(pid, False, f"{bw} 기록을 못 읽음", {"reason_ko": pr.get("reason_ko")}, who=who)
            continue
        add(pid, not pr.get("stale"), f"{bw}이 돌고 있음" if not pr.get("stale") else f"{bw} 기록이 멈춤(5분 넘게 새 기록 없음)",
            {"as_of": pr.get("as_of_ms")}, who=who)
        pos2 = ((pr.get("accounts") or {}).get(ACCOUNT) or {}).get("position")
        add(posid, pos2 is None, f"{nm} 포지션이 비어 있음" if pos2 is None else f"{nm}에 이미 포지션이 있어 새 진입 안 함(한 번에 하나)",
            {k: pos2.get(k) for k in ("symbol", "side", "strategy_id", "timeframe", "entry_time", "last_mark_roe_net")} if pos2 else None, who=who)
    for x in execs:
        r, ko = x["record"], x["name_ko"]
        if r.get("state") != "ok":
            add("exec", False, f"{ko} 실행기 기록을 못 읽음", {"reason_ko": r.get("reason_ko")}, who=x["id"])
            continue
        add("exec", not r.get("stale"), f"{ko} 실행기가 돌고 있음" if not r.get("stale") else f"{ko} 실행기 기록이 멈춤", {"as_of": r.get("as_of_ms")}, who=x["id"])
        halted = bool(r.get("halted"))
        add("halt", not halted, f"{ko} 멈춤 아님" if not halted else f"{ko} 실행기가 멈춤(사람이 풀어야 함)",
            {"reason": r.get("halt_reason")} if halted else None, who=x["id"])
        lt = x.get("light") or {}
        st = lt.get("state")
        add("light", st != "red", {"green": f"{ko} 신호등 초록", "red": f"{ko} 신호등 빨강이라 따라가지 않음", "building": f"{ko} 신호등 근거 쌓는 중(모두 따라감)",
                                  "off": f"{ko} 신호등 꺼짐(모두 따라감)"}.get(st, f"{ko} 신호등 모름"),
            {k: lt.get(k) for k in ("n", "wins", "need_wins", "min_win", "have")}, who=x["id"], tone="ok" if st in ("green", "building", "off") else "stop" if st == "red" else "warn")
    sig = read_signals(p["paper"], ACCOUNT, now, keep=1)
    last = (sig.get("rows") or [None])[0] if sig.get("state") == "ok" else None
    combo = read_combo(p["paper"], paths_more()["combo_config"])
    members = members_of(combo) if combo.get("state") == "ok" else []
    trend_on = combo.get("state") == "ok" and isinstance(combo.get("config"), dict) and combo["config"].get("trend") is not None
    pend = pending(p, now, members, trend=trend_on, pull=trend_on and trend_waits(combo.get("config")))
    try:
        lk = likely_rows(load_likely(), now, members, pend.get("waits") or [])
        lk = {"state": "ok", **{k: lk[k] for k in ("cell", "bot", "note_ko")}, "top": lk["rows"][:LIKELY_TOP]}
    except FileNotFoundError:
        lk = _missing(str(LIKELY_FILE), LIKELY_MISSING_KO)
    except LC.RefConfigMismatch as exc:                  # another config's frequencies: none shown
        lk = _missing(str(LIKELY_FILE), str(exc))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        lk = _err(str(LIKELY_FILE), exc)
    if lk.get("state") == "missing" and trend_on:         # the trend bot: never a bare 수집 전
        lk = likely_trend(p["paper"], lk.get("reason_ko"))
    blocked = [i for i in items if i["ok"] is False]
    head = ("지금 진입할 수 있어요 · 신호를 기다리는 중" if not blocked else
            "지금은 새 진입 안 해요: " + blocked[0]["ko"])
    return {"now_ms": now, "ready": not blocked, "head_ko": head, "items": items,
            "last_signal": {k: last.get(k) for k in ("t", "strategy", "tf", "symbol", "side", "stage", "ko")} if last else None,
            "signals": {k: sig.get(k) for k in ("state", "reason_ko", "stages")}, "next_pause": cn.get("next"),
            "pause_until": cn.get("pause_until"), "pending": pend, "likely": lk,
            "pending_blocked_ko": next((i["ko"] for i in items if i["ok"] is False and i["id"] in ("weekend", "macro", "usopen", "position", "paper")), None)}


# ---------------------------------------------------------------- 진입 가능성 (owners 10/19 "각 매매법마다 진입 가능성 몇%, 순위별로")
LIKELY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir, os.pardir, "deploy",
                           "combo.live-ac.likely.json")
LIKELY_GROUP = ("mt", "mt", "mt", "mt", "fri", "sat", "sun")     # KST weekday (Monday 0) → the file's day group
LIKELY_TOP = 5
LIKELY_MISSING_KO = "진입 가능성 기준표(deploy/combo.live-ac.likely.json)가 없어요"
LIKELY_NOTE_KO = ("5년 백테스트(지금 설정 95개, 실거래 규칙)에서 같은 요일·같은 한국 시각 뒤 1·4·24시간 안에 그 매매법의 진입 신호가 나온 "
                  "비율이에요. '최근'은 2025~26년만. 포지션이 비어 있을 때 기준이고, 예측이 아니라 과거 빈도예요. 오늘의 경제 발표 쉬는 "
                  "시간은 따로 빼지 않았어요.")
# the trend bot (owners 10-21): the file is the old A+C bot's 5-year run (source.config); the trend bot enters only after its trend judge, its
# entry checks (and the pullback, when its config waits: likely_trend_note), so a signal's frequency is more than its entries
# (said, never hidden)
LIKELY_TREND_NOTE_HEAD_KO = ("예전 봇(A+C 합본, 설정 95개)의 5년 백테스트에서 같은 요일·같은 한국 시각 뒤 1·4·24시간 안에 그 매매법의 신호가 "
                             "나온 비율이에요. ")
LIKELY_TREND_NOTE_TAIL_KO = ("실제 진입은 이 숫자보다 꽤 적어요(봉도 다를 수 있어요). 새 규칙의 진입 빈도는 아직 잰 적이 없어요. 과거 빈도일 뿐 "
                             "예측이 아니에요.")
LIKELY_TREND_NOTE_KO = (LIKELY_TREND_NOTE_HEAD_KO + "추세판단 봇은 신호가 나와도 추세 판단(1시간·4시간·일봉 추세)·진입 전 검사·되돌림을 모두 "
                        "통과해야 들어가서, " + LIKELY_TREND_NOTE_TAIL_KO)
_likely_ref: dict = {}


def likely_trend_note(tb: Optional[dict]) -> str:
    """진입 가능성's note for the trend bot ``tb`` (trend_bot): the judged bars its members read and the pullback only when
    its config waits (trend_waits; the owners' config since 10-22 enters at once)."""
    tb = tb or {}
    htfs = sorted({m.get("htf") for m in tb.get("members") or [] if m.get("htf")}, key=lambda t: TF_ORDER.get(t, 99))
    judged = "·".join(TF_KO.get(t, t) for t in htfs) or "상위 봉"
    pull = trend_waits(tb.get("config"))
    return (LIKELY_TREND_NOTE_HEAD_KO + f"추세판단 봇은 신호가 나와도 추세 판단({judged} 추세)·진입 전 검사"
            + ("·되돌림을 모두 통과해야" if pull else "를 통과해야") + " 들어가서, " + LIKELY_TREND_NOTE_TAIL_KO)


# the 추세판단 봇: its new rules have no 5-year signal frequencies; 진입 가능성 shows what the trend takes now and the replay
LIKELY_TREND_KO = "추세판단 봇은 새 규칙이라 매매법별 5년 신호 빈도표가 없어요 · 대신 지금 추세가 받는 방향과 재현(가상)의 진입 빈도예요"


def likely_trend(path: str, reason_ko: Optional[str] = None) -> dict:
    """진입 가능성 for the trend bot (no frequency table for its rules): {state "trend", reason_ko, taking, expect, ts}."""
    from . import livetrend as LT                          # (livetrend imports this module)
    now_ = LT.trend_now(path)
    if now_ is None:
        return _missing(path, "추세판단 봇이 아직 첫 판단을 기록하지 않았어요 (켠 뒤 1~2분)")
    return {"state": "trend", "reason_ko": LIKELY_TREND_KO, "table_ko": reason_ko, **now_}


def load_likely(path: Optional[str] = None) -> dict:
    """deploy/combo.live-ac.likely.json (the research script likely27.py, from the same 5-year backtest as the expected file):
    per strategy and for the whole bot, by KST day group (월~목 · 금 · 토 · 일) and KST hour, the share of past hours after
    which an entry signal came within 1 / 4 / 24 hours, and the share of the next entry each strategy gave. Cached by mtime.
    livecheck.RefConfigMismatch (a ValueError, the Korean reason) when its ``source.config_sha256`` is not the running
    config's (livecheck.ref_config_problem; checked on every call: the config can change without this file)."""
    from ... import livecheck as LC
    path = os.path.normpath(path or LIKELY_FILE)
    mt = os.stat(path).st_mtime_ns
    c = _likely_ref.get(path)
    if c and c[0] == mt:
        d = c[1]
    else:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d.get("strategies"), dict) or not isinstance(d.get("bot"), dict):
            raise ValueError("strategies / bot missing")
        _likely_ref[path] = (mt, d)
    why = LC.ref_config_problem(d, paths_more()["combo_config"])
    if why:
        raise LC.RefConfigMismatch(why)
    return d


def kst_cell(ms: int) -> tuple:
    """(day group, KST hour) of a moment."""
    return LIKELY_GROUP[int(((ms + KST_MS) // DAY + 3) % 7)], int((ms + KST_MS) // HOUR % 24)


def _lk(block: Optional[dict], period: str, key: str, g: str, h: int) -> Optional[float]:
    try:
        return _f(block[period][key][g][h])
    except (KeyError, IndexError, TypeError):
        return None


def likely_rows(ref: dict, now: int, members: list, waits: list) -> dict:
    """The strategies the bot runs, most likely to enter first: a strategy with a break signal waiting now leads (closest to
    its level first), then by the recent (2025-26) share of past hours like this one followed by its entry signal within 4
    hours, then within 24 hours. Each row: those shares (recent and 5 years) for 1 / 4 / 24 hours and the share of next
    entries, the next 24 hours' 1-hour shares (when it tends to come), and its waits."""
    g, h = kst_cell(now)
    strategies = ref.get("strategies") or {}
    names = sorted({m["strategy"] for m in members}) if members else sorted(strategies)
    n_set: dict = {}
    tfs: dict = {}
    for m in members:
        n_set[m["strategy"]] = n_set.get(m["strategy"], 0) + 1
        tfs.setdefault(m["strategy"], set()).add(m.get("tf"))
    by_wait: dict = {}
    for w in waits:
        by_wait.setdefault(w.get("strategy"), []).append({k: w.get(k) for k in ("symbol", "side", "tf", "level", "last", "to_go", "touched",
                                                                                 "until", "left_ms", "t0")})
    hour0 = now // HOUR * HOUR
    cells = [(hour0 + k * HOUR,) + kst_cell(hour0 + k * HOUR) for k in range(24)]

    def shares(e):
        return {key: {per: _lk(e, per, key, g, h) for per in ("recent", "all")} for key in ("w1", "w4", "w24", "next")}

    rows = []
    for s in names:
        e = strategies.get(s)
        ws = sorted(by_wait.get(s) or [], key=lambda w: (not w.get("touched"), w["to_go"] if w.get("to_go") is not None else 9.0))
        rows.append({"strategy": s, "known": e is not None, "type": (e or {}).get("type"),
                     "n_settings": n_set.get(s, (e or {}).get("settings")),
                     "tfs": sorted(tfs.get(s) or (e or {}).get("tfs") or [], key=lambda t: TF_ORDER.get(t, 99)),
                     "p": shares(e), "hours": [{"t": t, "p": _lk(e, "recent", "w1", gg, hh)} for t, gg, hh in cells],
                     "signals_5y": ((e or {}).get("signals") or {}).get("all"), "waits": ws})

    def order(r):
        w = r["waits"]
        lead = (0, 0 if w[0].get("touched") else 1, w[0]["to_go"] if w[0].get("to_go") is not None else 9.0) if w else (1, 1, 9.0)
        neg = lambda x: -x if x is not None else 1.0                                                  # noqa: E731
        return lead + (neg(r["p"]["w4"]["recent"]), neg(r["p"]["w24"]["recent"]), neg(r["p"]["next"]["recent"]), r["strategy"])
    rows.sort(key=order)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    bot = ref.get("bot") or {}
    samples = ref.get("samples") or {}
    return {"cell": {"group": g, "hour": h, "samples": {per: (samples.get(per) or {}).get(g) for per in ("recent", "all")}},
            "bot": {**{key: {per: _lk(bot, per, key, g, h) for per in ("recent", "all")} for key in ("w1", "w4", "w24")},
                    "next_h_median": {per: _lk(bot, per, "next_h_median", g, h) for per in ("recent", "all")},
                    "hours": [{"t": t, "p": _lk(bot, "recent", "w1", gg, hh)} for t, gg, hh in cells]},
            "note_ko": LIKELY_NOTE_KO, "source": ref.get("source"), "rows": rows}


def likely(p: dict, now: int) -> dict:
    """GET /api/v4/livebots/likely: 진입 가능성 순위. Every strategy the bot runs with how often, in the 5-year backtest, an
    hour like this one (KST day group and hour) was followed by its entry signal within 1 / 4 / 24 hours (recent 2025-26 and
    all 5 years), its waits now, its signals of the last 7 days, and what stops an entry now (/now's checks). Past
    frequency, never a forecast; read-only."""
    from ... import livecheck as LC

    def none(why: str) -> dict:
        tb = trend_bot(p["paper"])
        if tb is None:
            return {"now_ms": now, **_missing(os.path.normpath(LIKELY_FILE), why), "rows": []}
        w = whynow(p, now)                               # the trend bot: what it takes now, the replay, what stops it
        return {"now_ms": now, **likely_trend(p["paper"], why), "rows": [], "trend_bot": trend_out(tb),
                "blocked_ko": w.get("pending_blocked_ko"), "next_pause": w.get("next_pause"), "pause_until": w.get("pause_until")}
    try:
        ref = load_likely()
    except FileNotFoundError:
        return none(LIKELY_MISSING_KO)
    except LC.RefConfigMismatch as exc:                  # another config's frequencies: none shown
        return none(str(exc))
    except (OSError, ValueError) as exc:
        return {"now_ms": now, **_err(os.path.normpath(LIKELY_FILE), exc), "rows": []}
    w = whynow(p, now)
    combo = read_combo(p["paper"], paths_more()["combo_config"])
    members = members_of(combo) if combo.get("state") == "ok" else []
    out = likely_rows(ref, now, members, ((w.get("pending") or {}).get("waits")) or [])
    tb = trend_bot(p["paper"])
    if tb is not None:
        out["note_ko"] = likely_trend_note(tb)
    sig = read_signals(p["paper"], ACCOUNT, now, keep=RANK_SIG_KEEP)
    sig_by = signals_by_strategy(sig)
    for r in out["rows"]:
        s = sig_by.get(r["strategy"]) or {}
        r["sig"] = {"week": (s.get("week") or {}).get("signals", 0), "today": (s.get("today") or {}).get("signals", 0),
                    "entered_week": (s.get("week") or {}).get("entered", 0), "last_ms": s.get("last_ms"), "last_ko": s.get("last_ko")}
    return {"now_ms": now, "state": "ok", **out, "trend_bot": trend_out(tb),
            "combo": {k: combo.get(k) for k in ("state", "reason_ko", "path")},
            "signals": {k: sig.get(k) for k in ("state", "reason_ko", "since_ms")},
            "ready": w.get("ready"), "head_ko": w.get("head_ko"), "blocked_ko": w.get("pending_blocked_ko"),
            "pending": {k: (w.get("pending") or {}).get(k) for k in ("state", "rule_state", "closes")},
            "next_pause": w.get("next_pause"), "pause_until": w.get("pause_until")}


# ================================================================ the live checks (livecheck.db, liveimprove.db; read-only)
# loss card labels (paperbot/livecheck.py build_card, strongest first): id, the label as the card says it, the chip's tone
CARD_KINDS = (("gap", "실거래-페이퍼 차이", "bad"), ("bigger", "평소보다 큰 손실", "bad"), ("streak", "연속 손실", "warn"),
              ("weak", "백테스트에서도 약한 자리", "warn"), ("normal", "정상 범위 손실", "thin"))
CARDS_KEEP = 1000
NOISE_MS = 4 * HOUR                    # livecheck NOISE_MS: the noise stop is checked 4 hours after the exit
REG5_CARD_KO = ("강상승", "약상승", "강하락", "약하락", "횡보")      # livecheck REG5_KO (BTC 4h regime)
CHECK_MISSING_KO = "점검 파일이 아직 안 생겼어요 (아침 점검이나 실시간 감시가 아직 한 번도 돌지 않았어요)"
IMPROVE_MISSING_KO = "장부 파일이 아직 안 생겼어요 (월요일 09:30 주간 점검이 처음 돌면 생겨요)"
MORNING_DAYS = 14
WATCH_KEEP = 200
WATCH_STALE_MS = 10 * 60_000           # the watcher runs every 2 minutes (deploy/paperbot-livewatch.timer)
# the watcher's condition keys (paperbot/livecheck.py watch_conditions, drift_conditions, health_conditions) in words
WATCH_KO = {"paper_stale": "페이퍼 기록 멈춤", "rule_bars": "규칙봇 1분봉 멈춤", "stale": "실행기 기록 멈춤", "stop": "손절 기록 없음",
            "dd": "잔고 낙폭", "good": "잔고 좋은 소식", "halt": "실행기 멈춤", "vs_paper": "페이퍼가 이긴 거래에서 짐",
            "follow": "페이퍼를 안 따라감", "drift": "기대 범위 밑", "drift_note": "기대 범위 참고", "strat": "매매법 연속 손실 참고",
            "disk": "디스크 부족", "memory": "메모리 부족"}
WATCH_EX_KEYS = ("stale", "stop", "dd", "good", "halt", "vs_paper", "follow")
# liveimprove's commands as the start guide writes them on the server (docs/live1019-start-ko.md 13)
SERVER_CD = "cd /opt/crypto-bot-research"
SERVER_PY = "sudo -u paperbot /opt/paperbot/venv/bin/"


def card_kind(label: Any) -> str:
    s = str(label or "")
    if s.startswith("연속 손실"):
        return "streak"
    return next((k for k, ko, _t in CARD_KINDS if ko == s), "other")


def _card(row: tuple, now: int) -> dict:
    """One loss card as the page shows it: the stored card (livecheck build_card's fields) and its noise check."""
    key, tid, made, label, loud, streak, weak, noise, nroe, nts, sent, text, data = row
    d = _j(data)
    exit_t, entry_t = _i(d.get("exit_time")), _i(d.get("entry_time"))
    n = _i(noise)
    if n is None:
        nstate = "wait" if exit_t is None or now < exit_t + NOISE_MS + 10 * 60_000 else "checking"
    else:
        nstate = {1: "noise", 0: "not"}.get(n, "unknown")
    reg5 = _i(d.get("reg5"))
    hon = d.get("honest") if isinstance(d.get("honest"), list) and len(d["honest"]) == 2 else None
    cell = lambda v: [_i(v[0]), _f(v[1])] if isinstance(v, list) and len(v) == 2 else None      # noqa: E731
    execs = []
    for o in d.get("executors") or []:
        if isinstance(o, dict):
            execs.append({"name": o.get("name"), "label": o.get("label"), "status": o.get("status"), "roe": _f(o.get("roe")),
                          "pnl": _f(o.get("pnl")), "entry_bps": _f(o.get("entry_bps")), "exit_bps": _f(o.get("exit_bps")),
                          "why": o.get("why") or ""})
    stop_pct = _f(d.get("stop_pct"))
    return {"key": key, "trade_id": _i(tid), "made_ts": _i(made), "label": label, "kind": card_kind(label), "loud": bool(loud),
            "streak": _i(streak), "weak_cell": bool(weak), "sent": None if sent is None else bool(sent), "text": text or "",
            "strategy": d.get("strategy"), "tf": d.get("tf"), "member_order": _i(d.get("member_order")), "type": d.get("type") or "",
            "symbol": d.get("symbol"), "side": _i(d.get("side")), "entry_time": entry_t, "exit_time": exit_t,
            "hold_ms": exit_t - entry_t if exit_t is not None and entry_t is not None else None, "roe": _f(d.get("roe")),
            "pnl": _f(d.get("pnl")), "exit_reason": d.get("exit_reason"), "exit_ko": EXIT_KO.get(d.get("exit_reason"), d.get("exit_reason")),
            "stop_type": d.get("stop_type") or "", "stop_dist": stop_pct / 100 if stop_pct is not None else None,
            "reg5": reg5, "reg5_ko": REG5_CARD_KO[reg5] if reg5 is not None and 0 <= reg5 < len(REG5_CARD_KO) else None,
            "hour": _i(d.get("hour")), "mfe_roe": _f(d.get("mfe_roe")), "fit_win": _f(d.get("fit_win")),
            "honest": [_i(hon[0]), _f(hon[1])] if hon else None, "loss_median": _f(d.get("loss_median")),
            "loss_worst": _f(d.get("loss_worst")), "hours_median": _f(d.get("hours_median")), "hours_p90": _f(d.get("hours_p90")),
            "reg5_cell": cell(d.get("reg5_cell")), "sym_cell": cell(d.get("sym_cell")),
            "weak": [str(w) for w in d.get("weak") or []], "fit_longest": _i(d.get("fit_longest")),
            "honest_longest": _i(d.get("honest_longest")), "gap": bool(d.get("gap")), "bigger": bool(d.get("bigger")),
            "ref_ko": d.get("ref_ko") or None,              # livecheck build_card: why it has no 5-year numbers
            "executors": execs, "noise": {"state": nstate, "roe": _f(nroe), "ts": _i(nts)}}


def read_cards(path: str, now: int) -> dict:
    """livecheck.db ``loss_cards`` (newest exits first): {state, cards}."""
    try:
        conn = open_ro(path)
    except FileNotFoundError:
        return _missing(path, CHECK_MISSING_KO)
    except (OSError, sqlite3.Error) as exc:
        return _err(path, exc)
    try:
        conn.execute("BEGIN")
        if "loss_cards" not in _tables(conn):
            return _missing(path, "점검 파일은 있지만 손실 카드 표는 아직 안 생겼어요 (감시가 첫 기록을 쓰기 전)")
        rows = conn.execute("SELECT key, trade_id, ts, label, loud, streak, weak, noise, noise_roe, noise_ts, sent, text, data "
                            "FROM loss_cards ORDER BY exit_time DESC, key LIMIT ?", (CARDS_KEEP,)).fetchall()
    except sqlite3.Error as exc:
        return _err(path, exc)
    finally:
        conn.close()
    return {"state": "ok", "path": path, "cards": [_card(r, now) for r in rows]}


def _score_row(r: dict) -> dict:
    keep = ("key", "label", "n", "wins", "win", "avg_roe", "losses", "loss_roe_median", "pnl", "fit", "honest", "honest_src", "status",
            "p", "family", "tfs")
    ex = {}
    for name, e in (r.get("exec") or {}).items():
        ex[name] = {k: e.get(k) for k in ("n", "wins", "pnl", "live_roe", "paper_roe", "leak")}
    return {**{k: r.get(k) for k in keep}, "exec": ex}


def scorecard(p: dict, execs: list) -> dict:
    """매매법 성적표, computed now with liveimprove's own functions (read_paper, exec_follow, scorecard: the same numbers and
    status words as ``python -m paperbot.liveimprove score``) over the paper database and the executors' followed trades,
    against deploy/combo.live-ac.expected.json. Every database read-only (mode=ro, query_only)."""
    got = live_card(p, execs, ("strategy",))
    if got.get("state") != "ok":
        return got
    card, trades, problems, follow, LI = got["card"], got["trades"], got["problems"], got["follow"], got["LI"]
    o = card["overall"]
    return {"state": "ok", "path": p["paper"], "source": "live", "n": len(trades),
            "since_ms": min((t["entry_time"] for t in trades), default=None),
            "overall": {**_score_row(o), "break_even": o.get("break_even"), "roll": {str(k): v for k, v in (o.get("roll") or {}).items()}},
            "rows": [_score_row(r) for r in card["cuts"]["strategy"]],
            "words": [LI.SMALL, LI.OK, LI.WATCH, LI.BAD], "small_n": LI.SMALL_N, "check_n": LI.CHECK_N, "family": LI.family_size(got["ref"], "strategy"),
            "luck_ko": LI.LUCK_NOTE, "how_ko": list(LI.READ_HOW[1:]), "problems": problems,
            "execs": [{"id": x["id"], "name_ko": x["name_ko"], "state": x["record"].get("state"),
                       "followed": follow.get(x["id"]) is not None} for x in execs],
            "cmd": f"{SERVER_PY}python -m paperbot.liveimprove score"}


def live_card(p: dict, execs: list, cuts: tuple) -> dict:
    """liveimprove's scorecard over the paper database now (read-only), with the asked cuts: {"state": "ok", "card", "trades",
    "ref", "follow", "problems", "LI"} or the honest state of what could not be read."""
    from ... import livecheck as LC
    from ... import liveimprove as LI
    path = p["paper"]
    try:
        ref = live_ref(path)
    except LC.RefConfigMismatch as exc:              # another config's reference (or the trend bot's: none): no scorecard
        return _missing(str(LI.EXPECTED), str(exc))
    except (OSError, ValueError) as exc:
        return {**_err(str(LI.EXPECTED), exc), "reason_ko": "백테스트 기준표(deploy/combo.live-ac.expected.json)를 못 읽었어요"}
    try:
        conn = open_ro(path)
    except FileNotFoundError:
        return _missing(path)
    except (OSError, sqlite3.Error) as exc:
        return _err(path, exc)
    try:
        conn.execute("BEGIN")
        if "trades" not in _tables(conn):
            return _missing(path, NO_TABLE_KO)
        trades = LI.read_paper(conn, ref)
        _ts, run = LC.get_state(conn, "combo_run")
    except (sqlite3.Error, ValueError, TypeError, KeyError) as exc:
        return _err(path, exc)
    finally:
        conn.close()
    problems = []
    why = LI.ref_mismatch((run or {}).get("config") if isinstance(run, dict) else None, ref)
    if why:
        problems.append(f"기준표가 페이퍼 봇의 지금 설정과 다름({why}): 세팅별 줄과 손절·진입 구분은 믿지 마세요")
    infos = [LC.ExecInfo(name=x["id"], config=(x["config"] or {}).get("path") or "-", unit="-", db=x["record"].get("path") or "",
                         light_n=0, light_min=0.0, exchange=(x["config"] or {}).get("exchange") or x["id"], account=x["follows"])
             for x in execs]
    try:
        follow = LI.exec_follow(infos, trades, paper_db=path)       # each executor's trades on THIS paper bot
        card = LI.scorecard(trades, ref, follow, cuts=cuts)
    except (sqlite3.Error, ValueError, TypeError, KeyError) as exc:
        return _err(path, exc)
    return {"state": "ok", "card": card, "trades": trades, "ref": ref, "follow": follow, "problems": problems, "LI": LI}


def ledger_cmds(row: dict) -> list:
    """The exact server commands of a ledger item's next step (liveimprove.next_step's own commands, run as the start
    guide writes them)."""
    from ... import liveimprove as LI
    full = LI.next_step(row, full=True)
    if " → " not in full:
        return []
    out = []
    for part in full.split(" → ", 1)[1].split(" / "):
        i = part.find("python -m ")
        if i >= 0:
            out.append(SERVER_PY + part[i:].strip())
    return out


def read_ledger(path: str) -> dict:
    """개선 후보 장부 (liveimprove.db ``ledger``, ``ledger_log``, the latest ``weeks`` row): open items first, each with its
    question, its evidence when found and now, the next step and its exact command. Read-only: a status moves only by the
    command (liveimprove set_status)."""
    from ... import liveimprove as LI
    try:
        conn = open_ro(path)
    except FileNotFoundError:
        return _missing(path, IMPROVE_MISSING_KO)
    except (OSError, sqlite3.Error) as exc:
        return _err(path, exc)
    try:
        conn.execute("BEGIN")
        tables = _tables(conn)
        if "ledger" not in tables:
            return _missing(path, "장부 파일은 있지만 장부 표는 아직 안 생겼어요")
        cur = conn.execute("SELECT * FROM ledger ORDER BY id")
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        logs = conn.execute("SELECT item, ts, day, old, new, note, who FROM ledger_log ORDER BY id").fetchall() if "ledger_log" in tables else []
        week = conn.execute("SELECT week, ts, since, trades, wins, tested, flagged, new_items, level, sent FROM weeks "
                            "ORDER BY week DESC LIMIT 1").fetchone() if "weeks" in tables else None
    except sqlite3.Error as exc:
        return _err(path, exc)
    finally:
        conn.close()
    by_item: dict = {}
    for item, ts, day, old, new, note, who in logs:
        by_item.setdefault(_i(item), []).append({"ts": _i(ts), "day": day, "old": old, "new": new, "note": note or "", "who": who or ""})
    items = []
    for r in rows:
        latest = _j(r.get("latest"))
        r = {**r, "latest": latest}
        is_open = r.get("status") in LI.OPEN
        items.append({"id": _i(r.get("id")), "cell": r.get("cell"), "kind": r.get("kind"), "kind_ko": LI.KIND_KO.get(r.get("kind"), r.get("kind")),
                      "label": r.get("label"), "found": r.get("found"), "found_ts": _i(r.get("found_ts")), "n": _i(r.get("n")),
                      "wins": _i(r.get("wins")), "expected": _f(r.get("expected")), "expected_src": r.get("expected_src"), "p": _f(r.get("p")),
                      "family": _i(r.get("family")), "question": r.get("question") or "", "status": r.get("status"),
                      "status_ts": _i(r.get("status_ts")), "rule_b": bool(r.get("rule_b")), "rule_c": bool(r.get("rule_c")),
                      "latest": {k: latest.get(k) for k in ("ts", "n", "wins", "expected", "p")}, "rule_a": LI.rule_a(latest),
                      "note": r.get("note") or "", "open": is_open,
                      "next_ko": LI.next_step(r, full=False) if is_open else "끝난 항목",
                      "cmds": ledger_cmds(r) if is_open else [], "log": by_item.get(_i(r.get("id")), [])})
    items.sort(key=lambda x: (0, x["id"] or 0) if x["open"] else (1, -(x["status_ts"] or 0)))
    wk = None
    if week:
        try:
            new_items = json.loads(week[7]) if isinstance(week[7], str) else []
        except ValueError:
            new_items = []
        wk = {"week": week[0], "ts": _i(week[1]), "since_ms": _i(week[2]), "trades": _i(week[3]), "wins": _i(week[4]), "tested": _i(week[5]),
              "flagged": _i(week[6]), "new_items": new_items if isinstance(new_items, list) else [],
              "level": week[8], "sent": None if week[9] is None else bool(week[9])}
    return {"state": "ok", "path": path, "items": items, "n": len(items), "open_n": sum(1 for x in items if x["open"]), "week": wk,
            "statuses": list(LI.STATUSES), "adopt_rule": list(LI.ADOPT_RULE), "cd": SERVER_CD,
            "list_cmd": f"{SERVER_PY}python -m paperbot.liveimprove ledger list"}


def _loud_reasons(text: str, n: int) -> list:
    """The morning check's loud reasons as its message lists them (livecheck.compose: the head line, the span, a blank
    line, then one '- reason' line each)."""
    if not n:
        return []
    out = []
    for ln in (text or "").split("\n")[3:]:
        if not ln.startswith("- "):
            break
        out.append(ln[2:])
    return out[:n]


def _morning_item(row: tuple) -> dict:
    day, ts, level, loud, text, report, sent = row
    rep = _j(report)
    paper = rep.get("paper") if isinstance(rep.get("paper"), dict) else None
    pday = (paper or {}).get("day") if isinstance((paper or {}).get("day"), dict) else None
    par = rep.get("parity") if isinstance(rep.get("parity"), dict) else {}
    ex = []
    for r in rep.get("executors") or []:
        if isinstance(r, dict):
            ex.append({"name": r.get("name"), "label": r.get("label"), "missing": bool(r.get("missing")), "exists": r.get("exists"),
                       "n": _i(r.get("day_trades")), "pnl": _f(r.get("day_pnl")), "halted": r.get("halted")})
    lines = (text or "").split("\n")
    return {"day": day, "state": "ok", "ts": _i(ts), "level": level, "loud_n": _i(loud) or 0,
            "reasons": _loud_reasons(text, _i(loud) or 0), "head": lines[0].lstrip("📋🚨 ") if lines else "", "text": text or "",
            "sent": None if sent is None else bool(sent),
            "summary": {"paper": {"n": _i(pday.get("n")), "wins": _i(pday.get("wins")), "pnl": _f(pday.get("pnl"))} if pday else None,
                        "execs": ex, "parity_flags": _i(par.get("flags")), "parity_error": par.get("error") or None}}


def _watch_kind(key: str) -> dict:
    parts = str(key).split(":")
    kind = parts[0]
    return {"kind": kind, "kind_ko": WATCH_KO.get(kind, kind), "ex": parts[1] if kind in WATCH_EX_KEYS and len(parts) > 1 else None}


def read_checks(path: str, now: int) -> dict:
    """livecheck.db, one snapshot: ``morning`` (the morning check's last 14 KST check days, newest first: level, the loud
    reasons, a summary, the whole message; a day without a record says so) and ``watch`` (every alarm the watcher sent:
    time, level, its message, whether it is still on, cleared (and so re-armed) or a once-only note; the watcher's last
    pass)."""
    try:
        conn = open_ro(path)
    except FileNotFoundError:
        m = _missing(path, CHECK_MISSING_KO)
        return {**m, "morning": m, "watch": m}
    except (OSError, sqlite3.Error) as exc:
        e = _err(path, exc)
        return {**e, "morning": e, "watch": e}
    try:
        conn.execute("BEGIN")
        tables = _tables(conn)
        days = conn.execute("SELECT day, ts, level, loud, text, report, sent FROM days ORDER BY day DESC LIMIT 60").fetchall() \
            if "days" in tables else None
        log = conn.execute("SELECT ts, key, event, level, text, sent FROM watch_log ORDER BY ts, rowid").fetchall() \
            if "watch_log" in tables else None
        w = conn.execute("SELECT key, active, first_ts, last_ts, cleared_ts, level, text, recover, once FROM watch").fetchall() \
            if "watch" in tables else []
        seen = conn.execute("SELECT MAX(ts), COUNT(*) FROM seen").fetchone() if "seen" in tables else (None, 0)
    except sqlite3.Error as exc:
        e = _err(path, exc)
        return {**e, "morning": e, "watch": e}
    finally:
        conn.close()
    return {"state": "ok", "path": path, "morning": _morning(days, now), "watch": _watch(log, w, seen, now)}


def _morning(days: Optional[list], now: int) -> dict:
    if days is None:
        return _missing("", "점검 파일은 있지만 아침 점검 표는 아직 안 생겼어요")
    if not days:
        return _missing("", "아침 점검이 아직 한 번도 돌지 않았어요 (매일 09:10)")
    from ... import livecheck as LC
    by = {r[0]: r for r in days}
    last = LC.default_day(now)
    first = min(by)
    epoch = _dt.date(1970, 1, 1)
    d_last = _dt.date.fromisoformat(last)
    want = [(d_last - _dt.timedelta(days=i)).isoformat() for i in range(MORNING_DAYS)]
    want = sorted({d for d in want if d >= first} | {d for d in by if d > last}, reverse=True)
    items = []
    for day in want:
        w0 = (_dt.date.fromisoformat(day) - epoch).days * DAY
        base = {"day": day, "day_ko": LC.kst_day(w0), "w0": w0, "w1": w0 + DAY}
        if day in by:
            items.append({**base, **_morning_item(by[day])})
        elif now < w0 + DAY + 45 * 60_000:
            items.append({**base, "state": "pending", "why_ko": "아직 점검 전이에요 (매일 09:10에 돌아요)"})
        else:
            items.append({**base, "state": "none", "why_ko": "그날 점검 기록이 없어요 (점검이 돌지 않았거나 실패했어요)"})
    return {"state": "ok", "items": items, "last_day": last, "first_day": first, "loud_days": sum(1 for x in items if x.get("loud_n"))}


def _watch(log: Optional[list], w: list, seen: tuple, now: int) -> dict:
    if log is None:
        return _missing("", "점검 파일은 있지만 감시 기록 표는 아직 안 생겼어요")
    last_seen, passes = _i(seen[0]), _i(seen[1]) or 0
    if not passes and not log:
        return _missing("", "실시간 감시가 아직 한 번도 돌지 않았어요 (2분마다 돌아요)")
    cond = {r[0]: {"active": bool(r[1]), "first_ts": _i(r[2]), "last_ts": _i(r[3]), "cleared_ts": _i(r[4]), "once": bool(r[8])} for r in w}
    fires, open_fire = [], {}
    for ts, key, event, level, text, sent in log:
        if event == "fire":
            f = {"ts": _i(ts), "key": key, **_watch_kind(key), "level": level, "level_ko": "긴급" if level == "CRITICAL" else "조용한 알림",
                 "title": (text or "").split("\n")[0], "text": text or "", "sent": None if sent is None else bool(sent),
                 "cleared_ts": None, "recover": ""}
            fires.append(f)
            if f["sent"] is not False:
                open_fire[key] = f
        elif event == "clear":
            f = open_fire.pop(key, None)
            if f is not None:
                f["cleared_ts"], f["recover"] = _i(ts), text or ""
    for f in fires:
        c = cond.get(f["key"]) or {}
        if f["sent"] is False:
            f["state"] = "unsent"
        elif f["cleared_ts"] is not None:
            f["state"] = "cleared"
        elif c.get("once"):
            f["state"] = "once"
        elif c.get("active") and c.get("first_ts") == f["ts"]:
            f["state"], f["last_ts"] = "active", c.get("last_ts")
        else:
            f["state"] = "unknown"
    items = sorted(fires, key=lambda f: -(f["ts"] or 0))[:WATCH_KEEP]
    return {"state": "ok", "items": items, "n": len(fires), "active_n": sum(1 for f in fires if f["state"] == "active"),
            "last_seen_ms": last_seen, "passes": passes,
            "stale": last_seen is None or now - last_seen > WATCH_STALE_MS}


def _cached(key: str, make) -> dict:
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit is not None and now - hit[0] < TTL_S:
            return hit[1]
    out = make()
    with _lock:
        _cache[key] = (now, out)
        if len(_cache) > 64:
            for k in sorted(_cache, key=lambda k: _cache[k][0])[:16]:
                _cache.pop(k, None)
    return out


def register(app, ctx) -> dict:
    from ..app import json_finite

    def key(name: str, p: dict) -> str:
        return name + ":" + json.dumps([p, paths_more()], sort_keys=True)

    @app.get("/api/v4/livebots")
    def get_livebots():
        """실거래 요약 (터미널): the two live executors and the paper account they follow (read-only, 5 s cache, honest states)."""
        p = paths()
        return _cached(key("sum", p), lambda: json_finite(build(p)))

    @app.get("/api/v4/livebots/trades")
    def get_livebots_trades():
        """실거래 › 거래: the three accounts' closed trades with their settings, reasons, costs, partners and loss cards (5 s cache)."""
        p = paths()
        return _cached(key("trades", p), lambda: json_finite(trade_rows(p, int(time.time() * 1000))))

    @app.get("/api/v4/livebots/signals")
    def get_livebots_signals(bot: str = "paper"):
        """실거래 › 신호: the combined bot's signals of the last 7 KST days and what became of each; ``bot`` paper2: the second
        paper bot's (5 s cache)."""
        p = paths()
        b = bot if bot in BOT_IDS else "paper"
        return _cached(key("signals:" + b, p), lambda: json_finite(signals(p, int(time.time() * 1000), b)))

    @app.get("/api/v4/livebots/perf")
    def get_livebots_perf():
        """실거래 › 성적: rolling win shares and the breakdowns of each account, 매매법 성적표, 개선 후보 장부 (5 s cache)."""
        p = paths()
        return _cached(key("perf", p), lambda: json_finite(perf(p, int(time.time() * 1000))))

    @app.get("/api/v4/livebots/safety")
    def get_livebots_safety():
        """실거래 › 안전: halts, the limits each config has, the kill file, the lights' history, the WARN / CRITICAL log, the
        morning checks and the watcher's alarms."""
        p = paths()
        return _cached(key("safety", p), lambda: json_finite(safety(p, int(time.time() * 1000))))

    @app.get("/api/v4/livebots/shadows")
    def get_livebots_shadows():
        """실거래 › 그림자: the shadow paper bots next to the live paper bot, from the same start (5 s cache)."""
        p = paths()
        return _cached(key("shadows", p), lambda: json_finite(shadows(p, int(time.time() * 1000))))

    @app.get("/api/v4/livebots/settings")
    def get_livebots_settings():
        """실거래 › 설정: the fixed rules, the settings grouped by strategy, the lights and the limits (5 s cache)."""
        p = paths()
        return _cached(key("settings", p), lambda: json_finite(settings(p, int(time.time() * 1000))))

    @app.get("/api/v4/livebots/rank")
    def get_livebots_rank():
        """실거래 › 순위: per strategy its paper and live record, 7-day signals, 5-year numbers and status word (5 s cache)."""
        p = paths()
        return _cached(key("rank", p), lambda: json_finite(rank(p, int(time.time() * 1000))))

    @app.get("/api/v4/livebots/calendar")
    def get_livebots_calendar():
        """실거래 › 일정: US macro releases with the bot's pause windows, the weekend, whether entries may be made now (5 s cache)."""
        p = paths()
        return _cached(key("calendar", p), lambda: json_finite(calendar(p, int(time.time() * 1000))))

    @app.get("/api/v4/livebots/map")
    def get_livebots_map():
        """실거래 › 지도: wins so far against the 5-year bands, and the record by regime, coin, KST block and side (5 s cache)."""
        p = paths()
        return _cached(key("map", p), lambda: json_finite(map_view(p, int(time.time() * 1000))))

    @app.get("/api/v4/livebots/costs")
    def get_livebots_costs():
        """실거래 › 비용: how far each executor's trades fall behind the paper trades they followed, and why some were not (5 s cache)."""
        p = paths()
        return _cached(key("costs", p), lambda: json_finite(costs(p, int(time.time() * 1000))))

    @app.get("/api/v4/livebots/team")
    def get_livebots_team():
        """실거래 › 분석팀: the 실거래 분석 팀's meetings, words, conclusions and ideas, its AI use and its switch (5 s cache)."""
        p = paths()
        return _cached(key("team", p), lambda: json_finite(team(p, int(time.time() * 1000))))

    @app.get("/api/v4/livebots/now")
    def get_livebots_now():
        """실거래 (관제 · 지금): what stands between now and the next live entry (5 s cache)."""
        p = paths()
        return _cached(key("now", p), lambda: json_finite(whynow(p, int(time.time() * 1000))))

    @app.get("/api/v4/livebots/likely")
    def get_livebots_likely():
        """실거래 › 순위 · 진입 가능성: each strategy's past entry frequency at this KST day and hour, its waits now (5 s cache)."""
        p = paths()
        return _cached(key("likely", p), lambda: json_finite(likely(p, int(time.time() * 1000))))

    return {"routes": ["/api/v4/livebots", "/api/v4/livebots/trades", "/api/v4/livebots/signals", "/api/v4/livebots/perf",
                       "/api/v4/livebots/safety", "/api/v4/livebots/shadows", "/api/v4/livebots/settings", "/api/v4/livebots/rank",
                       "/api/v4/livebots/calendar", "/api/v4/livebots/map", "/api/v4/livebots/costs", "/api/v4/livebots/now",
                       "/api/v4/livebots/team", "/api/v4/livebots/likely"], "paths": paths}
