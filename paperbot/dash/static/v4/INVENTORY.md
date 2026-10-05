# Dashboard v4: inventory of the old dashboard and where everything moves

The old UI is `paperbot/dash/static/index.html` and its 14 scripts. It is served at `/` and stays untouched (team P10 owns it).
The new UI is `/static/v4/index.html`, behind the same login, and it calls the same `/api/*` routes.

Rule: **nothing may be lost.** Every row below has a new home, checked against the built screens (integration pass). A few rows are changed on purpose; those are marked **CHANGED**, with the reason. The old UI itself stays one tap away: **예전 화면** at the end of the 서버 group's menu opens `/v3` (`/` serves this page).

`tests/test_dash_v4.py` keeps this honest in code: every `/api` route the old UI called is still called by v4 (or listed with its reason), every route v4 calls exists on the server (or is a listed NEEDS SERVER probe), every file v4 references exists and every file is reachable.

Builders (CONTRACT.md):
- **A** home, board, checkpoint
- **B** account, positions, chart, market
- **C** strategies, analysis
- **D** office, rooms, digest, debate
- **E** server, alerts, signals, howto, faq

Sample answers of every GET route were recorded on the synthetic fixture world, which has the 331-account v4 shape and no real data, in `scratchpad/v4ui/api_samples/*.json`. `INDEX.json` lists them. `stream_event.txt` is one `/api/stream` event. Long lists are cut to 3 items in the samples.

## 1. Shell (every screen)

| Old | Where it was | New home |
|---|---|---|
| 12 top tabs (트레이드 … 서버 상태) | index.html `#nav` | 5 groups 홈 · 거래 · 매매법 · 에이전트 · 서버 (top on a PC, bottom tab bar on a phone) + sub tabs (core/shell.js, core/routes.js) |
| (the old dashboard itself) | `/v3` | **예전 화면 ↗** at the end of the 서버 group's sub tabs (core/shell.js), same login; also linked from server (E) |
| Three status chips: 봇 연결 / 시세 / 에이전트 (+ agent chip states from rooms.js `aiChip`) | app.js `chip()`, rooms.js | **one health dot** (core/shell.js): red when the bot heartbeat or 1m data is stale, the stream is down for more than 30 s, or `/api/analysis/health` says `bad`; amber for `warn`. Tap → 서버·비용. Agent-stopped detail → rooms (D) and server (E) |
| Critical toasts (BUST, LIQUIDATED, blocked, data gap) | app.js `toastWorthy` | **sticky red banner** (core/alerts.js `criticalLines`): busts of the last 6 h folded into ONE line ("파산 n개 계좌 · 최근 …", acknowledged until a newer bust), liquidation burst (≥ 3 LIQ exits in 15 min among 기존 36 · 5분봉 · 추가 계좌, the groups whose every trade is announced; DeepSeek and coin flips at 20-50x would light it on every wick), feed stale (heartbeat / 1m data). Bust and burst lines can be acknowledged (localStorage); stale lines stay while true |
| Toast for every closed trade | app.js `stream()` | **CHANGED**: with 331 accounts this was noise. Closed trades become `[거래]` console lines in office (D) (home shows the server's per-group day count and a three-line 최근 회의 strip instead of a console); the account screen (B) refreshes when its account trades |
| Experiment strip (D+n, first verdict, observation, rules change 1 + 원문) | summary.js `expbar` | top chip `D+n/30 · 판정 MM/DD · 관찰 ~MM/DD` (the 판정 date at every width; 관찰 drops only under 380 px); tapping it expands the rules (at most 60% of the screen, scrolls inside, 닫기 button, closes on a route change or when the page is scrolled on): verdict method, 4h = observation, observation period, rules change 1 + `/api/doc/rules-change-1` |
| Theme button 밝게/어둡게 | app.js `themeInit` | **CHANGED**: two dark skins instead (owners 10/05, "미래 AI 느낌"): **AI** (default: charcoal, teal accent, mint up / pink down, faint grid) and **클래식** (the first navy + yellow look), a token swap in tokens.css (`<html data-skin>`, core/skin.js). The switch "화면 색 AI / 클래식" sits at the end of the 서버 group's tabs, next to 예전 화면; remembered per device. No light theme |
| 로그아웃 | index.html `#logout` | faq (E) and server (E): a button that POSTs `/api/logout`, then goes to `/login` |
| Rooms nav dot (new messages) | rooms.js `navDot` | `setBadge("rooms", true)` puts a dot on the 에이전트 group and the 에이전트 방 tab (D) |
| Server clock skew (`/api/time`) | charts.js `syncClock` | core/api.js `syncClock` / `serverNow()` |
| Binance WebSockets (mark price, 24h ticker, kline) in the browser | app.js `marketStream`, `klineStream` | **CHANGED** (no outside hosts): `/api/ticker` every 5 s (store key `ticker`) and `/api/candles?limit=2` every 5 s for the forming bar. These were the old UI's own fallbacks |
| PWA manifest, icons, theme colour | index.html head | same links in v4/index.html |

## 2. 트레이드 tab (app.js, charts.js, panels.js, pos.js `bookUse`)

| Old | New home |
|---|---|
| Ticker strip: last price, 24h change / high / low / quote volume, mark, funding + time to next funding, bar-close countdown, this coin's position count, KST session + US open countdown | chart (B); `core/bars.js` `closeIn`, `session`, `usMarket` |
| Watchlist of 7 coins (XRP marked 기록) | chart (B) |
| GH Coin 판단 table (state, confidence, TA rating per coin) | market (B) card "GH Coin 지금 판단", shown only while the recorder runs (`features.ghcoin`) |
| 오늘·일정 panel: today's trades, P&L, wins, liquidations; funding countdown; US market; next macro releases; next checkpoint; observation end | market (B) 오늘·일정 card; the today figures also go on home (A) |
| 봇 차트: 15 intervals, account picker filtered by TF, entries and exits of the chosen account, position price lines grouped within 0.05 % with live P&L, entry / stop / liq lines, S/R levels (`/api/levels`), GH Coin plan lines, macro release markers (`/api/events`), OHLC legend, level note | chart (B), using `core/lwc.js` (the vendored lightweight-charts, same origin) |
| Toggles 진입·청산 / 포지션 선 / 지지·저항 / GH Coin 타점 / 경제지표 (remembered) | chart (B), remembered with `local` |
| Countdown strip for every interval (● on traded TFs, highlight under 1 min) | chart (B) |
| 거래소 차트 (TradingView embed, `s3.tradingview.com/tv.js`) | **CHANGED**: no outside scripts allowed. A "트레이딩뷰에서 열기 (새 탭)" link in chart (B), and since 10/06 the opt-in **거래소 차트** tab as a sandboxed iframe (§17) |
| Coinglass links (차트, 청산 지도, 히트맵, 파생 정보) | chart (B), as new-tab links (no requests made by the page) |
| Side tabs: 이 코인 포지션 / 체결 / 신호 | chart (B) |
| Side tabs: 호가 (order book) / 시장 강제청산 (`/api/liq`) / 가격 알림 (list, add, delete, rearm, sender status) | chart (B). 강제청산 only while `features.liq` |
| Bottom tabs: 전체 포지션 | positions (B) |
| Bottom tabs: 최근 체결 | positions (B) 체결 기록 tab (오늘 or the last 1,000; filters 결과 / 묶음 / 코인; total line) + chart (B) 체결 tab |
| Bottom tabs: 봉별 요약 (per TF: accounts, positions, busts, median wallet, best account, best coin flip, 동전 봇보다 나음; extras in their own line) | board (A) 봉별 요약 card ('참고') |
| Row buttons 차트 / 매매법 / tap → account | links to chart (B), strategies (C), account (B) everywhere |
| The whole 트레이드 tab on one PC screen (watchlist, ticker strip, bot chart, side panels, bottom position tabs) | **terminal** (거래 › 터미널, wave 2; the landing screen on a window ≥ 1200 px wide, off the phone menu): reuses `core/lwc.js`, positions-kit / positions-book (`normPos`, `bookPanel`, `countdown`, `fundPct`), flow-kit / flow-cal (`prep`, race and calendar answers) |

## 3. 포지션 tab (pos.js)

| Old | New home |
|---|---|
| Coin strip, summary (count, unrealized total, long / short), coin head + order book | positions (B) |
| Tabs 포지션 / 손절·잠금 주문 / 오늘 체결; sort by profit / loss / newest / nearest liquidation | positions (B): tabs 포지션 / 손절·잠금 주문 / 체결 기록, the same four sorts, plus a 묶음 filter (기존 36 / 딥시크 / 5분봉 / 동전 봇 / 추가). Rows open smoothly into the full card, 8 per page |
| Position row: unrealized P&L and ROI at the mark price (before the exit fee), size, margin, entry / mark / liq, stop, profit lock | positions (B). Money uses `ui.assume("open")` |
| 왜 N배 (levwhy: group, score, rejected candidates; `/api/levwhy`) | positions (B) and account (B), **plus the entry-time liquidation distance** (`derive.liqDistance`), as the owners asked |

## 4. 마켓 tab (market.js)

| Old | New home |
|---|---|
| Fear & greed (now, yesterday, a week ago, bar), dominance, total market cap, Nasdaq / S&P / DXY / 10y with 5-day sparklines, stale marks, macro calendar with D-days, calendar problems, the "outside context only" note | market (B) |

## 5. 매매법 tab (strat.js)

| Old | New home |
|---|---|
| List of 36 with filter 전체 / 추세 / 되돌림, live record | strategies (C): groups 기존 36 / 딥시크 44 / 5분봉, search |
| Strategy, TF and coin pickers; chart with its overlays and panes (`/api/strategy/<s>`); this account's entries and exits; last-bar conditions; last signal marks | strategies (C) detail `#/strategies/<name>` |
| 5-year profile card + live risk (`/api/profile/<s>`) | strategies (C) |
| Its 4 TF accounts (wallet, trades, W-L) → account | strategies (C) |
| 손실 카드 / 손실 패턴 (`/api/cards`, `/api/cards/stats`) | strategies (C) |

## 6. 순위표 tab (app.js renderBoard, summary.js, checkpoint.js, breakdown.js, ghcoin.js, overlap)

| Old | New home |
|---|---|
| 오늘 요약 card (since 00:00 KST; trades, strategy P&L, wins, liquidations, best and worst accounts) | home (A) 오늘 card: per group (the server's `summary.today.by_group`) trades, wins, P&L, liquidations, busts. **CHANGED**: the separate best / worst accounts of the day are dropped (owners: less clutter); the group's top 5 / bottom 5 right above cover the same question |
| Tiles (accounts, open positions, above 5,000, beats coin flips, busts) | home (A) group cards + board (A) |
| Filters TF / kind / sort; table with rank, wallet, return, trades, win rate, W-L, MDD, status, 동전 봇 대비 | board (A): group cards → top 5 / bottom 5 → searchable, paginated list. Coin-flip comparison is shown as **참고** only; DeepSeek rows get nothing beyond 참고 |
| Extra account pills (복제 / 새 / 멈춤 / 정지 / 제안 상태와 달리 실행 중) | board (A) and account (B) |
| 순위표 / 전체 거래 엑셀(CSV) | board (A) (`/api/export/board.csv`, `/api/export/trades.csv`) |
| 체크포인트 판정 card (progress before the verdict; counts, p, q, reasons after it) | checkpoint (A); home (A) shows it as one line in the headline card ("판정 대상 241 · 30건 넘음 9 →", after the verdict its counts) |
| 코인별 · 요일·시간대별 성적 (`/api/breakdown`) | analysis (C) tab 코인·시간대 |
| GH Coin 타점 비교 (`/api/ghcoin`) | analysis (C) tab GH Coin, shown only while `features.ghcoin` |
| 계좌 겹침 · 최근 7일 (`/api/overlap`) | analysis (C) tab 계좌 겹침 |

## 7. 분석 tab (analysis.js)

| Old sub tab | New home |
|---|---|
| 건강 점검 (`/api/analysis/health`) | server (E) |
| 손익비·위험, 실전 준비도, 충격 테스트, 코인·장세 지도, 진입 순간, 조합 시너지, 좋은 자리 vs 보통, 그림자 비교 (+ curves, per-account picker) | analysis (C) sub tabs |
| 45개 질문 | analysis (C), **hidden while the list is empty** (`features.questions`) |
| (new) 상황 태그: tags on wins and losses (`/api/cards/stats`) | analysis (C) view 상황 태그 |
| 알림 기록 (`/api/analysis/alerts`, level filter) | alerts (E) |

## 8. 계좌 tab (app.js openAccount)

| Old | New home |
|---|---|
| Tiles (wallet, trades / win rate, lock exits, MDD / bust, signals entered / skipped / rejected / filtered), extra-account card (rule, proposal, trial, events), open position with live P&L and why-leverage, equity curve with start line, candle chart with markers for each coin, trade table with why lines, CSV | account (B) `#/account/<id>`. The trade list is paged |

## 9. 에이전트 방 (rooms.js)

| Old | New home |
|---|---|
| Room list (전체 / 팀 / 매매법, search, unread dots, last line), auto-debate note | rooms (D) |
| Chat: day separators, kinds (trigger, analysis, challenge, code_result + gate pill, decision, action, system, owner), evidence, older messages, new-message button, "토론 중" indicator | rooms (D). "토론 중" comes only from `rooms[].running` |
| Owner post (optional) with @mention autocomplete, 1,000 chars, Enter on a PC (not during Hangul composition), pending posts, hints | rooms (D) |
| Side: proposals waiting for the owners with approve / reject + confirm + note, re-approve, stale gate, past proposals, schedule, members and duties, notes, hypothesis ledger (lab counts, passes, research totals, scorecard), today's AI usage with class bars | rooms (D) |
| Agents stopped / AI failing banners (`agentsState`) | rooms (D) + server (E) |

## 10. 회의실 (office.js) and the 24-hour debate card (analysis.js)

| Old | New home |
|---|---|
| Office floor: one zone per team room + a shared strategy-room zone, staff at desks, meeting participants at the table, real last lines as bubbles, 💭 next turn only when the meeting's order says so, walking when the place changes, today's counts, fixed meeting hours, running meetings with turns, today's finished meetings, the honesty note | office (D): warm wooden pixel office (team rooms, 전문가실 with a +N chip, 대표실 with real KST / UTC / NYC clocks), the agent console, and step strips that light only real steps |
| 24시간 토론방 card (state, spend vs cap, rounds, hypotheses, scoreboard, ideas) | debate (D), shown only once the debate room has run (`features.debate`). Its spend also goes on server (E) |

## 11. 회의 요약 (digest.js)

| Old | New home |
|---|---|
| 회의 결론 (day navigation), 직원 성적표 (1 / 7 / 30 days), 주간 성적표 (+ Telegram preview), 봉 비교 | digest (D) |

## 12. 신호, 서버 상태

| Old | New home |
|---|---|
| 신호 table with TF filter (incl. 1d record) | signals (E), paged |
| 서버 상태: heartbeat, accounts, taker fee, leverage brackets (example or exchange), 24h signals per TF / status with average delay, alerts table | server (E) (signals per TF vs limit, run facts) + alerts (E) |

## 13. New in v4 (owners' items, not in the old UI)

| Item | Where |
|---|---|
| Headline card: strategy-account median vs coin-flip median, W-L vs the same-TF coin median (참고), thin curves | home (A). Since the v4 additions the head card's lines are the group race (`/api/v4/flow/race`: 기존 36 · 딥시크 · 5분봉 medians, the coin flips' middle 50 % band and dashed median) and its legend is the lines' right ends (U1); designed empty road until two real points |
| Group summary cards 기존 36 / 딥시크 44 / 5분봉 / 동전 봇 | home (A), board (A); `core/derive.js groupStats` |
| 어떻게 돌아가나 step page | howto (E) |
| First-visit guided tour (7 steps, skippable, remembered) | core/tour.js: the steps open their screens and point at real elements: the D+n chip, the health dot, the headline card, the group cards (홈), the first position's why-leverage line (포지션), the pixel office (회의실), the 예전 화면 link (서버). 건너뛰기 or 끝 returns to where it started. Restart from faq (E) and home (A) |
| FAQ + what costs money (free / Max subscription / paid API) | faq (E) |
| 서버·비용: CPU, memory, disk, signal time vs limit, DB size / growth, AI calls / tokens vs caps, debate spend vs cap, Telegram count | server (E). What no endpoint sends yet shows `수집 전` (NEEDS SERVER) |
| One number format | core/fmt.js |

## 14. Every /api route

GET routes (sample files in `api_samples/`):

| Route | Answer (top level) | Old user | New screen(s) |
|---|---|---|---|
| `/api/board` | {ts, accounts[] (+ group, family, exits, name_ko), best_random, initial, extras_runtime, strategy_ko, names_ko, group_ko, family_ko, default_groups, run_shape} | many | store `board`: home, board, positions, chart, account, strategies. `strategy_ko` + `names_ko` feed every account name (fmt.stratKo) |
| `/api/summary` | {now, start, period_days, day, next_checkpoint, observe_until, observing, restart, today, events} | summary.js, panels.js | store `summary`: chip, home, market, checkpoint |
| `/api/status` | {now, heartbeat, run, alerts, signals_24h, limits} | 서버 상태 | store `status`: banner, server, alerts, signals (`limits` = the signal time limits) |
| `/api/time` | {now} | charts.js | core/api.js |
| `/api/checkpoint` | {ready, …verdict} | checkpoint.js | checkpoint |
| `/api/levwhy` | {positions: {id: {group, group_ko, score, leverage, short_ko, entry_time}}} | pos.js | positions, account |
| `/api/account/{id}` | {account, state, trades[], equity[], equity_points, signals, extra, position_why} | 계좌 | account |
| `/api/signals?tf&symbol&limit` | [{id, bar_close, timeframe, strategy, symbol, side, ref_price, delay_ms, status, …}] | 신호, side tab, strat.js | signals, chart, strategies |
| `/api/trades?symbol&tf&limit` | [{id, account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, equity_after, strategy, timeframe, kind, side, entry_price, exit_price}] | many | positions, chart, strategies, banner |
| `/api/agents/roster` | {teams, roles, meetings} | — | office, howto |
| `/api/agents/feed?limit` | [{id, ts, meeting, role, kind, text, data}] | — (unused) | **not used**: no room id / speaker name yet, so the console is built from `/api/office` + room messages (NEEDS SERVER #3) |
| `/api/v4/server` (arrived) | server (E) | — | polled every 60 s; a 404 (an older server) keeps CPU, memory, disk, DB size and the Telegram count at `수집 전` |
| `/api/v4/curves` (arrived) | 홈 LED bar | — | the total of every wallet, hourly, for the LED bar's line (the head card's lines now come from `/api/v4/flow/race`); until two real points (or on a 404) the `잔고 곡선 수집 전` pill stays |
| `/api/v4/flow/*`, `/api/v4/grid*`, `/api/v4/story`, `/api/v4/since`, `/api/v4/replay/*`, `/api/v4/params/*` (additions) | see §16 | — | flow, grid, strategies, account, story, home (ring, race card, 1:3 card), since sheet, replay, board (row lines) |
| `/api/cards`, `/api/cards/stats` | loss cards / {trades, losses, wins, tags} | strat.js | strategies |
| `/api/overlap?days` | {window, rules, accounts, exposure, pairs, groups, …} | 순위표 | analysis |
| `/api/breakdown` | {trades, min_n, by_coin, sessions, volatility, note} | 순위표 | analysis |
| `/api/ghcoin`, `/api/ghcoin/board` | calls and net R / {coins, alive} | 순위표, 트레이드 | analysis, market, chart (feature) |
| `/api/strategies` | [{strategy, name_ko, style, hold, rare}] | strat.js | strategies |
| `/api/strategy/{s}?tf&symbol` | {strategy, timeframe, bar_close, overlays, panes, conditions, last_signal} | strat.js | strategies (404 "no chart view" for DeepSeek / reel → shown as 준비 전) |
| `/api/profile/{s}` | {…5-year card, rows, live_risk} | strat.js | strategies |
| `/api/rooms` | {ready, now, last_tick, ai, tick_every_ms, rounds_per_room_day, max_id, rooms[], hours} | rooms.js | store `rooms`: rooms, office |
| `/api/rooms/{id}/messages?after_id&before_id&limit` | {room_id, messages[], pending_owner, has_more, max_id, room} | rooms.js | rooms, office |
| `/api/rooms/{id}/notes` | [{id, ts, room_id, strategy, text, round_id}] | rooms.js | rooms |
| `/api/trials`, `/api/proposals` | ledger / proposals | rooms.js | rooms |
| `/api/agents/usage` | {day, calls, tokens, cap_calls, cap_tokens, classes[], week, caps_source} | rooms.js | rooms, server |
| `/api/office` | {ready, now, day, zones, strategy_members, running[], recent[], latest_strategy, today, schedule, roles} | office.js | store `office`: office, home |
| `/api/digest/day`, `/staff`, `/week`, `/tf` | see samples | digest.js | digest |
| `/api/market` | {fng, global, indexes[], events, events_total, events_problems} | market.js | market |
| `/api/price-alerts` | {alerts, sender_alive, sender_hb, max} | panels.js | chart |
| `/api/candles?symbol&interval&limit` | [{time, open, high, low, close}] | charts | chart, account, strategies |
| `/api/depth?symbol` | {bids, asks, T} | pos.js | positions, chart |
| `/api/liq?symbol&minutes` | {symbol, minutes, long_usd, short_usd, n, rows, recorder} | panels.js | chart (feature `liq`) |
| `/api/levels?symbol&tf` | {close, atr, levels[], bar} | app.js | chart |
| `/api/events?days_back&days_ahead` | {events[], problems} | app.js | chart |
| `/api/ticker` | {SYM: {c, p, h, l, q, mark, r, T}} | app.js fallback | store `ticker`: positions, chart, account |
| `/api/analysis/health` | {now, bot, agents, usage, nightly, checkpoint, job_failures, problems, warnings, level} | analysis.js | store `health`: health dot, banner, server |
| `/api/analysis/alerts` | {sources, not_stored, bot, mismatches, nightly, checkpoint_jobs, agents_tick, agents_ai, job_failures, price_alerts_fired} | analysis.js | alerts |
| `/api/analysis/` risk, readiness, shock, map, entry, synergy, levrule, shadows | see samples (heavy ones may answer {pending: true} first) | analysis.js | analysis |
| `/api/analysis/questions` | {ready, questions[], counts, total, note} | analysis.js | analysis (feature `questions`) |
| `/api/debate` | {ready, state, state_ko, reason, spend, rounds, hypotheses, scoreboard, ideas, caution, …} | analysis.js | debate (feature), server |
| `/api/doc/rules-change-1`, `/api/doc/levrule-eval` | plain text | summary.js link | chip rules, faq |
| `/api/export/board.csv`, `/api/export/trades.csv?account` | CSV | 순위표, 계좌 | board, account |
| `/api/stream` (SSE) | every 3 s {ts, changed{id: [wallet, trades, bust, position]}, trades[], alerts[], heartbeat, room_msg, rooms{}} | app.js | core/api.js `startStream` (one connection; bus events) |

POST routes, unchanged and used by the same screens:
- `/api/login`, `/api/logout`
- `/api/price-alerts`, `/api/price-alerts/{id}/{delete|rearm}` (chart)
- `/api/rooms/{id}/say` (rooms)
- `/api/proposals/{id}/decide` (rooms)

## 15. Server data for v4: what arrived, what is still missing (details under NEEDS SERVER in CONTRACT.md)

Arrived while v4 was built (team P10, `app.py`), and already read by the page:
- `/api/board` rows carry `group`, `family`, `exits`, `name_ko`; the board carries `names_ko` (the Telegram names of the DeepSeek definitions and the reel). Lists name DeepSeek, the reel and the coin flips with the short plain-Korean names of `core/names.js` (the server's "딥시크 F15_OPEN0930 (세션 레인지·시가 편향)" is cut before the timeframe on a phone), the timeframe in its own box first (`ui.acctLabel`); the code and family show on the account page.
- `/api/board` positions carry the reel's `tp` and `time_exit`: 포지션 and 차트 read them from the board (no per-account calls).
- `/api/board.run_shape.judged_by_group` gives the judged timeframes (home and 판정 read it; the old copy stays as the fallback).
- `/api/status.limits` (signal time limits) is read by server and signals.
- `/api/summary.today.by_group` is read through `fmt.SERVER_GROUP` by home's 오늘 card and the balance bar (no trade download any more). Its split puts the three 5m coin flips with the coin flips, so that card labels its rows "5분봉 단타" (the reel) and "동전 봇 (5분 포함)".
- The live stream's `changed` map patches the cached board (wallet, trades, bust, position); the full board comes with the 60 s poll (it is about 220 KB).

Still missing:
- No median equity series (`/api/v4/curves`): the headline card's thin curves and the LED curve show `수집 전`.
- `/api/agents/feed` has no room id / speaker name: the console is built from `/api/office` and room messages instead.
- No CPU / memory / disk / DB size / Telegram count endpoint (`/api/v4/server`): those show `수집 전`.
- `/api/strategy/<name>` answers 404 for DeepSeek and the reel: their strategy pages show the rule in words and the record, and "차트 보기 준비 전".
- `/login` sends the owners to `/` (the old UI); v4 is at `/static/v4/index.html` until the owners switch. v4 now sends an expired session to `/login?next=<the v4 screen>`; the login page still has to honour it.
- `/api/levwhy` says "위 단계가 안 된 이유 기록 못 찾음" for DeepSeek and 5m accounts, which always trade at the 보통 multiple: the page shows "딥시크·5분봉은 규칙상 늘 보통 배수" instead.
- No compression: `/api/board` (about 220 KB) and `/api/trades` travel uncompressed.

## 16. v4 additions (after the first build; dashboard only, no experiment reset)

| Addition | Screen / place | Server (dash/more, read-only) |
|---|---|---|
| 묶음 레이스 · 수익 달력 | flow (홈 › 흐름); `raceMini` card on home (screens/flow-kit.js) | dash/more/flow.py: `/api/v4/flow/race?step=`, `/api/v4/flow/calendar?season=` (race 60 s, calendar 120 s cache; incremental, read-only) |
| 매매법 × 봉 지도 · 매매법 프로필 카드 | grid (매매법 › 한눈 지도); `profileCard` in the strategies list, at the top of `#/strategies/<name>` and on the account page | dash/more/grid.py: `/api/v4/grid?days=`, `/api/v4/grid/sparks?days=`, `/api/v4/grid/profile/<account id or strategy>?days=` (60 s cache) |
| 오늘의 하이라이트 | story (`#/story[/<YYYY-MM-DD>]`, 7 pages); `storyRing` at the top of home (screens/story-kit.js) | dash/more/story.py: `/api/v4/story?day=` (today 60 s, earlier days 30 min cache) |
| 지난번 본 뒤로 바뀐 것 | core/since.js (sheet when the app opens after ≥ 30 min away; started from core/main.js) | dash/more/since.py: `/api/v4/since?after=<ms>` (clamped to the run start / 7 days, per-minute cache) |
| 거래 다시보기 | replay (`#/replay/<trade id>`), opened from closed-trade rows (positions, account) | dash/more/replay.py: `/api/v4/replay/<trade id>`, `/api/v4/replay/sparks?ids=` (board row lines) |
| 움직임 다듬기 | core/motion.js (countTo flash, flash, floatChip, ring, drawIn), core/ui.js (miniSpark, rankDelta, liveNum flash), screens/board-motion.js (rank arrows on board and home lists) | none |
| 터미널 (PC one screen) | terminal (`#/terminal`, 거래 › first sub tab; `feature: "wide"` = windows ≥ 760 px; landing at ≥ 1200 px, `routes.landing()`). Top bar: coin, price (motion.tickPrice), 24 h high / low / volume, mark, funding + countdown, session, KST clock, a slow line of the latest finished AI meetings' decisions (`/api/office` recent; 회의 중 from `running`). Left: watchlist (7 coins, GH Coin call while `features.ghcoin`), 우리 봇 체결 (closed trades + entries from board updates; 기존 36 / 5분봉 / 추가 named, 딥시크 / 동전 봇 folded into count rows; new rows `motion.fillIn`), 시장 강제청산 while `features.liq` (ratio bar). Centre: chart (our entry / stop lines, recent trade marks, S/R, macro marks with a tooltip, price tag + bar-close countdown, breathing last-candle dot while `stream.live()`), table 포지션 / 체결 / 손절 주문 with the long / short / 대기 bar. Right: this coin's positions (live ROE, liquidation price), 호가, chosen group's median return line + daily bars + profit calendar (참고). Short windows (< 940 px tall) switch 포지션↔호가 and 체결↔청산 in one place | no new routes: `/api/ticker` (store 5 s), `/api/candles` (500 + forming bar 5 s), `/api/trades`, `/api/levels` (2 min), `/api/events` (10 min), `/api/depth` (3 s, on screen only), `/api/liq` (10 s), `/api/ghcoin/board` (5 min), `/api/v4/flow/race`, `/api/v4/flow/calendar` (5 min), `/api/office` (store, 30 s) |
| 릴스 1:3 대결 | home 5분봉 group card (펼치기) and the top of `#/strategies/REEL_H1` (screens/reel-duel.js) | reuses `/api/v4/flow/race` (reel + 5m flips' medians), `/api/v4/grid/profile/` (balance curves) |

## gapA. 분석 탭 묶음 필터 (dashboard only, no experiment reset)

| Addition | Screen / place | Server (dash/analysis.py, read-only) |
|---|---|---|
| 묶음 고르기 기존 36 / 딥시크 44 / 5분봉 (remembered, local `an-group`; `#/analysis/<view>?group=` opens one). No coin-flip group (the flips stay the 참고 baseline line inside each view) and no mixed 전체 (different exits, different flips, DeepSeek money not shown) | analysis (매매법 › 분석), a row under the view tabs; hidden on 상황 태그 / GH Coin / 45개 질문 (not about a group) | `?group=core\|ds200\|reel` (groups.py keys); no `?group=` = the 36 exactly as before (same cache key); anything else 400 |
| 손익비·위험 per group: the group's trades against ITS coin flips (36 and DeepSeek: 15m–4h flips, house exits; 5분봉: the three 5m flips, the reel's own exits 목표가 / 손절 / 시간 청산, no ladder line); 5분봉 lists REEL_H1 | analysis › 손익비·위험 | `/api/analysis/risk?group=` (`group_risk_view`, 15 min cache per group) |
| 코인·장세 지도 per group (entry buckets only for the 36) | analysis › 코인·장세 지도 | `/api/analysis/map?group=` (15 min cache per group) |
| 코인·시간대 per group (the 36 keep `/api/breakdown`) | analysis › 코인·시간대 | new `/api/analysis/breakdown?group=` (`group_breakdown`, breakdown.py's cells and session table on the group's rows; 10 min cache) |
| DeepSeek honesty (CONTRACT §1): counts and rates only. The server drops every money key (`no_money`: pnl, equity, worst day, dd in $, best accounts), the page shows "돈 숫자 없음" (ref pill), no 최악의 날 column, no assumptions caption, no per-definition / per-account list ("정의별" card says so) | the three grouped views | `no_money: true` in the answer |
| Views computed for the 36 only (진입 순간, 좋은 자리 vs 보통, 그림자 비교, 계좌 겹침, 조합 시너지, 충격 테스트, 실전 준비도) under 딥시크 / 5분봉: one card "이 보기는 기존 36만 계산합니다" with 기존 36으로 보기 and the grouped views as buttons, never the 36's numbers under another name | analysis | none (not fetched) |
## Gap batch B (gapB, 10/05 night: three items the owners were promised; dashboard only, no experiment reset)

| Addition | Screen / place | Server |
|---|---|---|
| 딥시크 17계열 요약 | strategies (매매법 › 딥시크 44 › **전체 요약**, the first DeepSeek view: tapping the 딥시크 group starts there, `#/strategies?g=ds&fam=all`); screens/strategies-dsfam.js. One row per family F1–F17: 정의 / 계좌 / 거래 / 승률 / 파산, then 딥시크 전체 and the same-timeframe coin flips (15분·30분·1시간·4시간; the 5m flips stay with the reel) as the 참고 baseline. **Counts only: no money** (CONTRACT §1 rule 3), 표본 적음 under 30 trades, refNote, a note that a high win rate can still lose money. A row opens its family's definitions; the family card carries its own count line and a 17계열 요약 button. Linked from 한눈 지도's DeepSeek tab (함께 보기) | none: counted from the shared `/api/board` rows (store, repainted with the board; no extra polling) |
| 진입선·손절선 은은한 빛 | terminal chart (screens/terminal-chart.js `placeGlows`, terminal.css `.term-glow`): lightweight-charts price lines cannot glow, so a thin overlay band sits at each of our entry / stop lines (기존 36 · 5분봉 · 추가 계좌, the same lines as before) in the line's meaning colour (`--up-glow` / `--down-glow`, `--accent-glow` before a mark price), moved with the price tag on scroll / zoom / resize / the 1 s tick. Static (no loop); a line that is new after the first paint draws its glow in once (`motion.drawIn`, nothing under reduced motion or on a hidden page). No position on the coin: no line, no glow | none |
| 🔊 한 번 누르면 소리 시작 | core/sound.js `startOnTap`: a tap on the speaker that opens the menu turns an off sound on (`setCfg({on: true})` + `unlock()`, the tap itself lets the browser play) and the menu shows it ticked; a tap that closes the menu never switches it on, so unticking it there keeps the quiet. Still off by default until that first tap; the sounds themselves are unchanged | none |
## 17. 거래소 차트 (TradingView opt-in)

Owners' choice (10/06 00:25 KST): the old 거래소 차트 comes back, opt-in, without any outside script in our page. `tests/test_dash_tvopt.py` keeps it that way.

| Old | New home | How (security) |
|---|---|---|
| 거래소 차트 (v3 charts.js: `s3.tradingview.com/tv.js` loaded into our page; Korean, Korea time, Binance perpetual `.P`, drawing tools) | chart (B): tab **우리 차트 · 거래소 차트** at the top of the chart card (screens/chart-tv.js). 우리 차트 is the default on every visit (the choice is not remembered). The interval strip and the coin strip drive the frame (`BINANCE:<COIN>USDT.P`, interval 1 … M, e.g. 5 / 15 / 30 / 60 / 240); the account picker, toggles and line notes hide on that tab; picking an account switches back to 우리 차트. Caption under it: "트레이딩뷰 화면 (바깥 사이트) · 우리 봇의 진입·손절선은 '우리 차트' 탭에". The new-tab links (트레이딩뷰에서 열기 ↗, Coinglass) stay | a cross-origin `<iframe>` of `https://s.tradingview.com/widgetembed/?…` (theme dark, timezone Asia/Seoul, locale kr, side toolbar on), `sandbox="allow-scripts allow-same-origin allow-popups"`, `referrerpolicy="no-referrer"`. Built only when the tab is opened, rebuilt (new element) on a coin / interval change, removed when the tab is left and on unmount. No `<script src=http…>` anywhere in v4. The page's CSP needs `frame-src https://s.tradingview.com https://www.tradingview-widget.com` (app.py, at merge) |
| 숫자(파라미터) 시험 결과 | `#/strategies/<id>`: a card right after 5년 성적 (screens/strategies-params.js, placed by one line in strategies-detail.js). The 36: one row per timeframe × parameter (shape sign + word 평평 / 완만 / 뾰족 / 표본 부족, variants positive in all three periods / variants tested); the reel: its choice variants and timeframes (configurations positive per period); DeepSeek: "이 매매법은 숫자 변형 시험 없음" + its timeframe × exit rows as counts only. One plain paragraph: no magic number, why the best past number is a trap, new numbers go through the AI lab's 3-period test and run as a separate new paper account. All 5년 과거 시험 (참고) | dash/more/params.py: `/api/v4/params/<strategy>` (reads agents/research_prior.json, agents/ds_prior.json, research/reel5m/out/per_variant.csv, per_tf.csv, summary.json; mtime cache; 404 for an unknown id) |
## 대시보드 다듬기 7가지

Owner-approved small polish (dashboard only, no new server route, no bot stop; ships with update-dash). Counts and links
only where money would mislead (DeepSeek, coin flips, funding).

| # | Item | Screen / place | Data |
|---|---|---|---|
| 1 | 같은 매매법 | account (`#/account/<id>`): a strip under the profile card with the same strategy's own timeframe accounts (same kind, 5m → 4h; this one marked 지금) and their return now; DeepSeek and the coin flips show only each account's closed-trade count with one 참고 pill (counted, never money: CONTRACT §1.3); bust / open position per tile; buttons 규칙·지표 차트 보기 (`#/strategies/<id>?tf=<tf>`, not for coin flips) and 담당 AI 방 (`#/rooms/strat:<id>`, only when that room exists: the 36). Copies / new-lab extras: no strip | store `board` (accounts[].strategy / kind / timeframe / wallet / trades / bust / position), store `rooms` |
| 2 | 회의 요약 다듬기 | digest › 직원 성적표: each staff row has a one-line colour bar of the replies it gave (동의 teal `--term-cyan`, 반대 pink `--down`, 보완 yellow `--term-yellow`; counts in the label; "반응 아직 없음" when none) with a key line. digest › 회의 결론: chips per meeting kind of that day (`meetings[].trigger` through `triggerKo`: 아침 회의, 손실 묶음 복기, 새 매매법 연구, 순위 검토, 봉 비교 회의 …, each with its count; the kinds text left the summary line) and a 결정 난 것만 toggle (`status: "done"`); an empty day or filter says 아직 없음 | `/api/digest/staff` (`staff[].replies.agree / disagree / add`), `/api/digest/day` (`meetings[].trigger / status`) |
| 3 | 달력 › 그날로 가기 | flow › 수익 달력: the picked day's panel ends with 그날 하이라이트 (`#/story/<YYYY-MM-DD>`, story.js reads the day from its argument; closing the story comes back to 흐름 through story-kit `nav.from`) and 그날 회의 결론 (`#/digest/day?d=<YYYY-MM-DD>`, digest-day.js reads `?d=`), also on a day without a record | none (links only) |
| 4 | 용어 사전 | new `screens/faq-terms.js` (+ `faq-terms.css`, @imported by faq.css and account.css): 레버리지, 증거금, 청산가, 손절·잠금 (lock numbers from positions-kit `LADDER`), ROE, 최대 낙폭, 승률, 펀딩비, 중앙값, two plain lines each, as the first card of 자주 묻는 질문 (rows open smoothly; `#/faq?q=<term>` or an alias such as ROI / MDD / 손절 opens that term, scrolls to it and tints it once). account: small "?" chips (`termify`, about a 34 px touch area) after 최대 낙폭 / 승률 (profile card, kept through its redraws), 익절 잠금 청산, 청산가 / 손절가·잠금선 / 증거금 / ROI / 왜 N배 (open position card) and 중앙값 (참고 line), each linking to `#/faq?q=<term>`. faq-items.js unchanged | none |
| 5 | 코인별 롱·숏 개수 | positions: each coin chip shows its open positions as "BTC 9↑ 3↓" (롱 ↑ · 숏 ↓, following the group filter) and an amber dot 한 방향 몰림 when one side holds 80 % or more of at least 5 positions (positions-kit `sideCounts` / `oneSided`, `SKEW_MIN` 5, `SKEW_SHARE` 0.8); a one-line key under the strip. Counts only, no money | store `board` (accounts[].position.symbol / side) |
| 6 | 펀딩 · 우리 모의 계좌 | market: a card under 오늘·일정 with one row per trading coin: the funding rate, "다음 펀딩(n분 뒤)" from the ticker's `T`, and "우리 모의 계좌 롱 n개는 내고 숏 m개는 받음" (r > 0: longs pay; r < 0 the other way; 0: nothing changes hands) from the board's open positions; counts only (no money: the amount depends on each size), a 펀딩비 "?" chip. A row opens `#/positions?coin=<SYM>`: positions.js now reads `?coin=` and opens on that coin (remembered like a chip tap) | store `ticker` (`r`, `T`), store `board` (positions' symbol / side) |
| 7 | 알림 접기 · 새 알림 줄 | alerts › 경고: alerts with the same level AND the same text fold into one row ("×12 · 처음 03:10 · 마지막 05:40"; a tap opens every time, up to 30 + "외 n번"; different texts never merge), new screen helper `screens/alerts-group.js` (`groupAlerts`, `newSince`, `withDivider`, pure); a "▲ 여기부터 위로 새 알림 n개" line after the rows that came since this device's last look (`local` key `alerts-seen`, per viewer, wrapped storage; none on the first visit); the card's note counts the folded rows and the new alerts. A live alert still slides in once | `/api/analysis/alerts` (`bot`), store `status` (`alerts`), bus `alerts` |
## 17. Wave 2 part B (w2b): cost check, verdict stage, coin flips on the board, signals by group, jobs

| Addition | Screen / place | Server (dash/more, read-only) |
|---|---|---|
| 비용 점검 (ranked #8) | 매매법 › 분석 › 비용 (`#/analysis/costs`, screens/analysis-costs.js): waterfall 수수료 전 → 수수료 → 펀딩 → 실제 (USDT, 기존 36 / 5분봉 / 추가 계좌 only); 거래 한 번에 (per trade as a share of margin, every group, coin flips dashed and neutral right under the strategies; DeepSeek and coin flips never summed in money); 봉별 (the 36 vs same-bar coin flips, 참고 + refNote); 실제 호가였다면 (stop slippage and order-book cost vs the paper's 2 bp, every number marked 추정); 홈 › 오늘 card: one line (`costLine`: the 36's fees / before / after per trade and the same-bar coin flips' after, 참고, → 분석 › 비용) | dash/more/costs.py: `/api/v4/costs` (per-account sums read incrementally by trade id, a smaller max id = a new database; daily3.db `stop_slips`, paper3.db `fill_costs`; 5 min cache) |
| 판정 무대 (ranked #4) | 판정 (`#/checkpoint`, screens/checkpoint-stage.js): 좌석표 (one seat per judged account, filled by trades / 30 in the neutral accent; from day 3 the part to the verdict at today's pace and a dashed edge for seats that would reach 30; head "판정 날 30건 넘을 것 약 N~M개" = pace ± one Poisson sigma; DeepSeek seats unnamed); 30일 판정으로 알 수 있는 것 (+0 / 1 / 2 / 5 / 10 % per trade → chance to pass by day 30 / 60 / 90 per timeframe, the DeepSeek line, assumptions); after `/api/checkpoint` ready only: the stamp and the luck dots (luck_passed, the first ⌈lucky_expected⌉ hollow) | dash/more/power.py: `/api/v4/power` (research/power/out/power.json via agents/power.py, scheme "split"; re-read when the file changes) |
| 동전 봇 끼워 보기 (ranked #5) | 순위표 list (`rankList(ctx, {flips: true})`, home-shared.js `withFlips` / `flipRow` / `flipFoot`; board only, home unchanged): sorted by 수익률, the same-bar coin flips sit at their real place as dimmed dashed rows with a coin and no rank number (기존 36: 12 flips, 5분봉: its three 5m flips, 딥시크: one median line); a search hides them; foot "동전 봇 12개 자리 · 같은 봉 동전 봇 중앙값보다 위 N/M개 (참고)" | none (`/api/board`) |
| 묶음별 신호 (v4_missing A8) | 신호 (`#/signals`): group × timeframe table from `status.signals_by_group` (count, 늦음), `·` where the group has no account; a 0 next to another timeframe of the same group with signals is orange (4h / 1d excluded) | none (`/api/status`) |
| 예약 작업: 켜짐·꺼짐 (v4_missing A9) | 서버·비용 › 예약 작업 (server-jobs.js `setJobs`, polled 60 s; a 404 stops it): 꺼짐 / 설치 안 됨 / 지난번 실패 / 도는 중 pills, systemd's last and next run where the dashboard has no record; without systemd the rows keep 수집 전 and the calendar | dash/more/jobs.py: `/api/v4/jobs` (`systemctl show` of a fixed unit list, TZ=UTC, 2 s timeout, 60 s cache; `{available: false, reason}` when systemctl is missing / refuses / times out) |
## 17. Wave 2 part C (w2c): meeting board, pixel characters, Korea-time office, 5년 시험 vs 지금 (dashboard only)

| Addition | Screen / place | Server (dash/more, read-only) |
|---|---|---|
| 오늘의 회의 결론 보고판 (ranked #11) | home: the card that replaced '최근 회의' (screens/meetboard-kit.js `meetBoard`): counts 회의 · 결정 · 갈린 의견, the newest three finished meetings' conclusion lines (the lead's first summary line, else the code summary), amber 갈린 의견, 회의 중 only from `/api/office` running, a row opens `#/digest/day?r=<round>`; 회의실 › 대표실: the report on the owners' desk (`deskReport`: a paper stack, 보고서 N → 회의 결론) | dash/more/brief.py: `/api/v4/brief/meetings` (today, cached 30 s; agents3.db rounds + the finished meetings' summary turns) |
| 매매법 픽셀 캐릭터 (visual pass) | core/figure.js `stratFigure` / `stratHue` (pb.js): one fixed head-and-shoulders character per strategy: body colour by family (the 36 by code, DeepSeek by family, the reel magenta, coin flips grey), six hair / cap shapes from the code, DeepSeek a numbered cap (its place in the 44), the reel a phone, a coin flip a coin head. Shown in 홈 상위·하위 and 순위표 rows (home-shared.js rankRow), the 매매법 list rows, the rooms list (a strategy room's avatar, replacing the 'S5' letters) and everywhere grid-kit.js `identicon` was (한눈 지도, profile cards, the account page head). No idle motion in lists | none |
| 창문이 한국 시간을 따름 (visual pass) | core/figure.js `windowArt` / `skyPhase`: 새벽 05-07 · 낮 07-17 · 저녁 17-19 · 밤 19-05 (sky, low sun, moon and stars, lit city windows), checked with the clocks every 15 s, never animated. 회의실: a wall plate '지금 유럽장 · 미국 증시 …' (core/bars.js session / usMarket, each minute), team floors tinted by TEAM_HUE, a lamp lit only in a room with a real meeting (`running`), rooms without a meeting dim after dark | none |
| 5년 시험 vs 지금 vs 동전 봇 (visual pass) | `#/strategies/<name>`: one small table per timeframe (screens/vs5y-kit.js): 하루 거래, 거래당 ROE (DeepSeek / reel at 1x = ROE ÷ 배수, the research's unit), 이긴 비율, 보유, 잠금 청산 for 5년 시험 / 지금 (this timeframe's account) / 동전 봇 (same-timeframe median, 참고), a neutral word per row (비슷 / 다름 / 적음 / 표본 적음); DeepSeek: counts only, no coin-flip column; refNote + assume | dash/more/vs5y.py: `/api/v4/vs5y/<strategy>` (cached 60 s; the strategy's and the same-timeframe flips' closed trades, the 5-year card rows) |
