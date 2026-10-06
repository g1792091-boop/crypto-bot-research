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
| (new) 글자 크기 | — | **NEW** (owners 10/06, "예전 대시보드보다 글자가 작다"): every v4 font size is a `--t-*` token, nothing visible below 12px, tables 13-14px; the control "글자 크기 보통 / 크게 / 아주 크게" (core/textsize.js, `<html data-text>`, about 100 / 112 / 125 %) sits at the end of every group's tabs, before 화면 색 (on a phone a one-button "가" at the start of the tab row cycles the three); remembered per device. To keep the bigger type readable the 터미널 drops low-value columns at narrower widths: the open-positions table hides 마크 and 진입 (time) below 1600 px, and 배수 and 진입가 at 1200-1439 px (and at 크게 / 아주 크게 below 1600 px); 이 코인 포지션 hides 배수 below 1600 px and at 크게 / 아주 크게. All of them stay on 포지션, the account page and the fills feed. At 크게 / 아주 크게 the 터미널's side columns are wider |
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
| 바탕음 = 실제 체결 (aggTrade) | core/sound.js: the continuous layer follows real Binance USD-M market trades of the 7 coins (buy = the upper notes, sell = the lower, size bucket 1-4 = louder, 3-4 a short run; the same queue, spacing and 빈도 setting, ~0.75 / s at 보통). EventSource only while the sound is on, unlocked, the page visible and not in the night mute (closed 00-07 KST when that is ticked, opened again by itself). Not live (server socket down / blocked, a refused answer, nothing for 15 s): the /api/ticker price changes feed the layer again by themselves. The approved sounds and the six motifs are unchanged; the browser still talks only to our server (connect-src 'self') | `/api/v4/ticks` (dash/more/ticks.py): ONE shared `wss://fstream.binance.com/stream?streams=<coin>usdt@aggTrade` socket, opened by the first listener and closed a minute after the last, at most ~2 events / s for every page together, reconnect backoff 1-60 s, bounded memory, stopped with the app; no REST call |
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
## 17. ana8A: strategy page (honest 5-year label, how it ended, earlier tests)

Dashboard only, no experiment reset. Day 0 (no closed trades) shows `아직 없음 · 끝난 거래가 10건쯤 쌓이면 …` and still the 5-year reference.

| Addition | Screen / place | Server |
|---|---|---|
| 5-year card label: `v3 크기 규칙 (모든 신호 50배부터)` instead of `같은 규칙` (the card was sized with the v3 tiers, every signal tier "best"); one line that ROE and lock share depend on leverage and that v4 normal spots start at 30x, so compare per-trade net in 1x price % (ROE ÷ leverage), as the reel 1:3 card does. DeepSeek / reel cards say `과거 연구 · 레버리지 없이 가격 %` | `#/strategies/<name>` 5년 성적 card (strategies-detail.js sub, strategies-panels.js profileBody); old UI strat.js the same words | none |
| 어떻게 끝났나: closed trades split by 나간 이유 (손절 / 잠금 +N% per `lock_roe` step, +30% and up in one row / 강제청산; the reel: 손절 / 윗밴드 익절 / 시간 (96봉)), 레버리지 (what the sizing gave), 평일·주말 (KST), 펀딩 ±10분 (00/08/16 UTC), 미국장 개장 ±60분 (09:30 New York, weekdays, DST rule) — the windows of paperbot/sessions.py ported to JS and checked against zoneinfo in tests. Under 나간 이유: the 5-year reference (the 36: the card's `lock_share` per timeframe next to the live lock share, with why they differ; the reel: its study's `exit_reason_pct` per period next to now; DeepSeek: none, its study used other exits). DeepSeek rows are counts only (no money); money rows carry `assume()`; cells under 10 trades say 표본 적음 | `#/strategies/<name>`, new card after 이긴 거래 · 진 거래 (screens/strategies-exits.js) | none: the trades already loaded from `/api/account/<id>` (`exit_reason`, `leverage`, `lock_roe`, `entry_time`), `/api/profile/<name>` (`rows[].lock_share`; reel `rows[0].periods[].exit_reason_pct`, already sent by ds_profiles) |
| 이미 해 본 시험: the 36's own entry-study results (지지·저항 tests and what stayed, 진입 수치 tests and per live timeframe the numbers whose direction was the same in all 3 periods, with why that means little; 추세선 tests), the study's `conclusion_ko` (설명용). Parameters are left to their own panel. DeepSeek: `이 매매법은 진입 연구 … 대상이 아닙니다` + the DeepSeek-200 rows (configs, all-3-positive, candidates, the family's gauntlet, per-config net per trade behind 펼치기); the reel: the pre-registered H1 line and the 40-config grid count. No p-values, no pass / fail marks | `#/strategies/<name>`, under the 5년 성적 card (screens/strategies-prior.js) | `/api/profile/<name>` gains `research_prior` (= agents/packets3.research_prior: agents/research_prior.json for the 36, agents/ds_prior.json for DeepSeek and the reel; `null` on a read error, never a 500) |
## Wave 3 (w3): 결재함 종 · 가동 기록 · 요일×시간 열지도 · 거래 결과 분포 · 30칸 픽셀 길

| Addition | Screen / place | Server (dash/more, read-only) |
|---|---|---|
| 결재함 종 (ranked #7, the bell part) | header, before the speaker (core/bell.js + core/bell.css, linked by index.html; started from core/shell.js). Count badge of the proposals waiting for the owners; tap = the newest five with a link to each room. Approving stays in the room's side panel (confirm step). Rings once only when the count really went up; on a phone (< 460 px) the bell shows only while something waits | dash/more/bell.py: `/api/v4/bell` (same rule as the side panel: `awaiting_owner` and not yet decided; 30 s cache; asked every 60 s, paused while hidden, and 2 s after a real room change, at most every 20 s) |
| 가동 기록 30일 (ranked #14) | 서버·비용, card under the tiles (screens/server-uptime.js/.css, @imported by server.css). 7 / 30 Korea-time days x 24 hour cells by stepped minutes (60분 다 · 일부 빠짐 · 멈춤 · 시작 전/아직), restart ticks, a night-check column (N/N 일치), '7일 가동 99.6% · 멈춤 n번 (총 m분)', the last five stops; tap a cell for its numbers | dash/more/uptime.py: `/api/v4/uptime?days=7\|30` (live_bars distinct minutes, runs, daily3 reports; a stop = 3+ minutes in a row; 120 s cache) |
| 요일 × 시간 열지도 (visual pass) | 분석 › 코인·시간대, card under 나눠 보기 (screens/analysis-shape.js `heatCard`, analysis-shape.css @imported by analysis.css). 7 x 24 by entry time (KST); modes 거래당 결과 / 이긴 비율 / 거래 수 / 동전 봇 (counts and win share only); cells under 10 trades dashed and faded; '168칸은 시험 안 함' + refNote + assume | dash/more/tradeshape.py: `/api/v4/tradeshape` (one request for both cards; 10 min cache) |
| 거래 결과 분포 (visual pass) | 분석 › 손익비·위험, last card (`outcomeCard`). Each trade's result against the balance before it in 10 bins fixed in advance: the 36 as bars (loss / gain colours), the same-timeframe coin flips (15m-4h; the 5m flips belong to the reel) as an outline, shares per group; win share and liquidations per group; refNote + assume | same route (`dist`) |
| 30칸 픽셀 길 (ranked #6) | home headline card in place of the progress bar, and the top of 판정 as its own card (screens/road-kit.js/.css, @imported by home.css and checkpoint.css; class prefix `proad-`, since `rd-` is the reel duel's). One cell per KST day of the season (start day to verdict day): tint = that day's 기존 36 median change (참고, light), hatched = 기록 없음, dashed = ahead; the two owners stand on today (one step when the day really changes; none under reduced motion); marks: verdict flag, US macro releases, the day the observation ends, busts that day; a past cell opens `#/story/<day>` | no new route: `/api/v4/flow/calendar` (120 s cache server side; asked every 5 min, paused while hidden), `/api/events` (once), store `summary` (observe_until) |

Not in w3 (left for later): the bell does not count replies / busts / verdict-ready yet (approval only); no '가동' one-liner on home (the home headline is already full; the server card has it); no 대표실 desk papers.
## 17. ana8B: 45 questions, limit entry, entry drift, per-strategy shadows, streak context (dashboard only)

| Addition | Screen / place | Server (read-only) |
|---|---|---|
| 45개 질문 filled | 분석 › 45개 질문 (shown once `features.questions` sees rows): 45 rows from the 10/04 audit, every status re-checked against the code at 3cd850a (not copied); an item only the 36 core strategies answer is 일부 (v4 groups); a new status **확인 중** (`checking`) for an item not verified yet, never a guessed status | `paperbot/dash/questions45.json` (`source`, `updated`, rows `{n, q, status, where, note, group}`); `analysis.STATUSES` gains `checking` |
| 지정가 진입 | 분석 › 그림자 비교, a card under the curves (screens/analysis-limit.js): per group 기존 36 / 딥시크 / 5분 단타, signals, fill rate, filled mean net ROE, the same signals' market entry (base) side by side, missed share and the missed signals' market result. ROE and counts only; DeepSeek counts and shares only (`counted_only`, no ROE: D11); 아직 없음 per group until the nightly check writes rows | `/api/analysis/shadows` `.limit_entry` (dash/more/shadowplus.py `limit_entry`: daily3.db shadows kind 'limit' joined to kind 'base' by `<account>|<symbol>|<bar close>`) |
| 진입 가격 차이 | 분석 › 그림자 비교, a card after 지정가 진입 (screens/analysis-drift.js): per group and timeframe median / 90% drift in bp, minus the same timeframe's coin flips, by delay (< 5 s, 5-20, 20-60, > 60 s, behind 펼치기); a median over 3 bp (1.5 x the 0.02% assumption) carries a neutral `가정보다 큼` pill; `ui.refNote` (참고: a coin-flip comparison) | `/api/v4/drift` (dash/more/drift.py, 10 min cache): read-only SQL over signal_log status 'SUBMITTED', `side x (ref_price / data.close - 1) x 1e4`, `data.close` via json_extract |
| 이 매매법 그림자 | `#/strategies/<name>` (the 36 only), the last card (screens/strategies-shadows.js, one import + one line in strategies-detail.js): this strategy's nightly shadow rows vs its own base (paged), its 5-year leverage x stop-width cells (30x / 50x, stops 1.5-3 ATR, live timeframes, labelled 5년), link to the pooled 그림자 비교 | `/api/analysis/shadows?strategy=<name>` (shadowplus `strategy_view`: riskreward.shadow_summary(strategies=[name]) + agents.levstop cells) |
| 연패 맥락 | 분석 › 손익비·위험, a card before 매매법별 (screens/analysis-streak.js, one import + one line in analysis-risk.js): per group the longest losing run, the run going on now, the chance of a run that long at that account's win rate and trade count (exact, Schilling 1990), the chance some account of the group has one, the coin flips' longest runs as the band (5m flips for the reel; for a named account the flips of its own timeframe). Counts and rates only; DeepSeek shows one unnamed row (group level only, §1.3); 아직 없음 until trades; 표본 적음 under 20 trades | `/api/analysis/risk` `.streaks` (dash/more/streaks.py `streak_context`) |
## #88 agent scoring, CSP, NYSE holidays (after the restart; dashboard + agents, no experiment reset)

| Addition | Screen / place | Server |
|---|---|---|
| 토론방 성적: 방 전체만 · 동전 던지기 50% · 우연히 맞을 기대치 · 쉬운 예측 따로 · 표본 적음 빨간 띠 (직원별 성적은 빼고 한 줄로 이유) | debate (에이전트 › 토론방), 가설 card (screens/debate.js) | `/api/debate` `scoreboard`: `coin_flip_rate`, `p_vs_coin_flip`, `expected_hits`, `expected_rate`, `easy` (agents/debate_grade.py) |
| 미국 증시 휴장일 2026-2027 · 단축 마감 13:00 | `bars.usMarket` (market 오늘·일정 card, chart, terminal top title): "휴장 (추수감사절) · 다음 개장 11월 27일 밤 (한국)", "(단축 마감)" | none (browser list `bars.NYSE_HOLIDAYS` = `paperbot/sessions.py` `NYSE_HOLIDAYS`; tests/test_88_csp_nyse.py keeps them equal) |
| AI 회의 구조와 한계 (FAQ 기본) | faq: "AI 회의 구조는 어디서 왔고, 한계는요?" → link | `/api/doc/tradingagents-limits` (docs/tradingagents-limits.md) |
| Content-Security-Policy | every answer (app.py `CSP`): scripts only from this server, Google Fonts allowed, TradingView chart iframe (`frame-src` s.tradingview.com, www.tradingview-widget.com), `frame-ancestors 'none'`; the old `/v3` page keeps `frame-ancestors 'none'` only (`CSP_V3`) | login.html's script moved to `/static/login.js` (public path) |

## 첫날 다듬기

What the owners see on the first morning after the v4 reset (dashboard only; ships with deploy/update-dash.sh). Tests: tests/test_dash_firstday.py.

| Addition | Screen / place | Server |
|---|---|---|
| 시작한 날 밤 점검 = 정상 | 서버 tile '밤 점검': "시작한 날 · 재계산 없음 (정상, 첫 재계산 내일 09:20)", grey (`st: none`); 알림 기록 › 밤 점검 the same line, muted; no health warning | `/api/analysis/health` `.nightly.start_day`, `/api/analysis/alerts` `.nightly[].start_day` (report['start_day'] from daily3) |
| 딥시크 돈은 딥시크 화면에서만 (D11) | 홈 LED: 합계에서 딥시크 빠짐 (캡션이 말함), 오른쪽 딥시크 칸 = "N계좌 (손익은 딥시크 화면에서)"; 오늘 card: 딥시크 줄은 거래·이김·강제청산·파산만; profile card (grid-kit `dsCounts`) and a DeepSeek strategy page: 거래 수 · 이긴 거래 · 파산, link to 순위표 딥시크; 순위표 전체 표의 딥시크 줄 최고 계좌 = "딥시크 화면에서" | `/api/v4/curves` `total` leaves DeepSeek out |
| 첫날 순위 없음 | 거래 0건 + 포지션 없음 = 순위 없음 (`derive.unranked`): 상위·하위 5, 최고 계좌, 흐름 가장 많이 오른·내린 계좌에서 빠짐; 한 줄 "아직 거래 없는 계좌 N개 · 첫 거래 뒤부터 순위"; 순위표 목록에선 맨 뒤 "—"; ▲▼ 기억은 순위 있는 계좌만 | none |
| 하이라이트 N일째 | 홈 하이라이트 rings and the story day picker: "N일째" (한국 날짜, 시작한 날 = 1일째, 흐름과 같음), so 오늘 and 어제 differ; 홈 head line: "D+는 매일 한국 09:00에 +1" | `/api/story` `days[].n` (dash/more/story.py `run_days`) |
| 상황 태그 범위 | 분석 › 상황 태그: 기존 36 + 5분봉만, caption shows the real window ("최근 2,000건이라 MM/DD부터" when capped) | `/api/cards/stats` (no strategy): kinds strategy + reel, `from_ts`, `capped`, `cap` |
| 조합 시너지 첫날 | 분석 › 조합 시너지: no ranked list until the 36 average 5 closed trades per account: "거래가 쌓이면 (계좌당 5건 이상) 보여 드립니다" | `/api/analysis/synergy` `waiting`, `note` (dash/analysis.py `SYNERGY_MIN_TRADES`) |
| 알림 기록 읽은 곳 | 알림 기록 footer: 봇 경고 · 밤 점검 보고 · 판정 작업 기록 (no file names) | none |
| 화면 켜두기 | 🔊 menu: "화면 켜두기" (Screen Wake Lock while the sound is on; off by default, this device only; asks again when the page comes back; "이 기기는 지원 안 함" without the API); FAQ 화면: "휴대폰에서 앱처럼 쓰려면요?" (브라우저 메뉴 → 홈 화면에 추가) | none |

## 터미널 살아 있게

Owners 10/06 03:48 on the live PC `#/terminal`: "마음에 드는데 뭔가 부족하다, 빛나거나 막 움직이는 게 안 보인다". Dashboard only (ships with deploy/update-dash.sh, the bot keeps running). Every light answers one real message; nothing under prefers-reduced-motion; the stream is closed while the page is hidden. Tests: tests/test_dash_punch.py.

| Addition | Screen / place | Server |
|---|---|---|
| 실시간 큰 체결 | 터미널 left column under 우리 봇 체결 (while the liquidation recorder runs it shares one place with 시장 강제청산: a 큰 체결 · 청산 switch on every PC window): large market orders of the whole Binance market, labelled "바이낸스 시장 전체 체결 (우리 봇 아님)"; time (KST, seconds), coin, 매수 / 매도 (taker side), price (wide windows), notional, ×threshold or a 고래 badge (4x); a new row slides in with a green / pink glow; the bar = taker buy / sell notional of those orders in the last 5 minutes ("최근 N분" right after the relay connected) | `/api/v4/ticks` messages carry `big` {rows, buy, sell, n, span; first message also min, whale_x} (dash/more/ticks.py `Big`: one taker order = its aggTrades with the same coin, side and trade ms; BTC $150k, ETH $80k, others $30k; last 40 kept) |
| 우리 봇 체결 shrinks on day 0 | fewer than 6 rows: the panel takes only what it needs and 실시간 큰 체결 gets the room | none |
| Live ticks light the screen | each relay event (≤ ~2 a second for all coins): that coin's 관심 종목 row shows the traded price and lights (≤ 2 a second per row); the selected coin's big price and the chart's price tag light and the forming candle takes the trade price (kept against the 5 s candle poll for 6 s); the KST clock's dot = relay state, one pulse per message with trades | `/api/v4/ticks` `ev` (unchanged) |
| Neon at rest | panels: a soft teal edge light (AI skin; the classic skin keeps its plain edge), an accent wash on the heads, glowing 미실현 합계 / 누적 손익 / top price; each panel head's underline runs a light once when that panel really got data (≤ once per 1.2 s) | none |
| 소리 켜기 hint | 터미널 top bar: "소리 켜기" (sound off) or "한 번 누르면 소리 시작" (on, waiting for the browser's first tap); opens the header speaker's menu (the same switch); gone while the sound plays | none |
| 이 코인 포지션 not empty | no position on the coin: its latest large market orders and (with the recorder) market liquidations, labelled "바이낸스 시장 전체 · 우리 봇 아님" | same stream, `/api/liq` |
| 신호 레이더 · 다음 신호까지 | 매매법 목록 (기존 36) top card (screens/strategies-radar.js `radarCard`): coin + 15분/30분/1시간/4시간 picker (BTC 1시간 first, remembered on this device), the 36 closest-to-firing first, each condition a lamp (lit = on), "한 칸 남음" rows glow, "조건 모두 켜짐", "신호!" only when signal_log has a signal on that bar; the bar it is from + countdown to the next close, re-read after each close; a row opens #/strategies/<name>?tf&sym; PC top 18, phone top 12 + 모두 보기; "예측이 아닙니다" note | `/api/v4/radar?tf&symbol` (dash/more/radar.py: strategy_views.render on the same closed bars as `/api/strategy/<name>`, once per bar; per timeframe and coin the full window once, then one 5-bar request per new bar (weight 1); the page asks 45 s after the close, once more for an all-on row without a logged signal) |
| 코인 × 봉 조건 지도 | 매매법 상세 (the 36), under 지금 조건 (`radarMatrix`): 6 coins × 15분/30분/1시간/4시간 cells "롱 2/3 · 숏 0/3", the closest cells glow, the cell on the chart is outlined, a tap moves the chart there (setChart); countdown per timeframe; cells not computed yet say so ("…", "나머지 N칸 계산 중") | `/api/v4/radar/strategy/<name>` (3 new cells per call, `pending`) |
| 곧 신호 대기실 | 서버 › 신호, top (`waitRoom`): one timeframe (picker, remembered), the 36 on all 6 coins, the 15 closest (coin, strategy, closer side's lamps, 한 칸 남음 / 조건 모두 켜짐 / 신호!), counts of 한 칸 남음 and this bar's signals; no DeepSeek, no coin flips (said in the note) | `/api/v4/radar?tf&symbol` × 6 |
| 24시간 신호 지도 | 서버 › 신호, next to 대기실 (signals.js `heatCard`): coin × 15분/30분/1시간/4시간 (+ 5분 when 5분 signals exist) signal counts of the last 24 h (long · short, 늦음), deeper colour = more, a cell flashes once when its count really rises, a live countdown to each timeframe's next close; counts only (no money); "최근 1,000개까지만" when capped | `/api/signals?limit=1000` |

## fill-home: 홈을 살아 있게 (dashboard + one read-only server change; tests/test_dash_fill_home.py)

| Addition | Screen / place | Server |
|---|---|---|
| 촘촘한 레이스 | 홈 head card race, 흐름 hero, 홈 group-card lines: a point every 5분 (run < 2일), 15분 (< 7일), then 1시간 / 4시간 / 하루; label "D+1 · 5분마다" | `/api/v4/flow/race?step=auto` (more/flow.py auto_step; 5- / 15-minute steps read from the 5-minute equity rows, finished steps kept) |
| LED 잔고 곡선 첫날부터 | 홈 LED bar line: 5분 steps while the run is under 2 days, 15분 under 7 days, then hourly | `/api/v4/curves?step=300000` / `900000` (app.py CURVE_STEPS gains 300000) |
| 시장 지금 | 홈 top band beside the story rings: 7 coins' price (glow on change), 24h %, 펀딩, 정산까지 countdown to the server's next funding time; phone: one sideways row | store `ticker` (`/api/ticker`, existing 5 s cache) |
| 지금 열린 포지션 | 홈 under the head card: 기존 36 / 5분봉 / 추가 계좌 positions (봉·매매법, 코인, 롱/숏 + 배수, 진입, 손절 or 잠금 ROE, live ROE at the mark, tint on change), ROE order, row opens the account; "그 밖에 딥시크 n · 동전 봇 n 포지션 (개수만)" | `/api/board` positions + store `ticker` mark |
| 방금 끝난 거래 + 오늘 잘한·못한 계좌 | 홈 full-width card: last 12 closed trades (newest close first) of 기존 36 / 5분봉 / 추가 (시각, 봉·매매법, 코인, 방향 + 배수, 익절 잠금 / 손절 / 시간, ROE, USDT), new rows slide in on the stream's trade event; 오늘 가장 잘한 / 못한 계좌 3 (기존 36, USDT, 참고, 표본 적음 under 30 trades) | `/api/trades?group=main&limit=12`, `/api/trades?group=core&limit=2000` (existing) |
| 회의 카운트다운 + 오늘 일정 | 홈 '오늘 회의 일정' (ticking countdown to the next fixed meeting; each meeting 예정 / 진행 중 / 끝 / 지남 with one line on what it reviews); the 0 / 0 / 0 board comes back once a meeting ran today; 회의 요약 › 회의 결론 shows the same card on a day without meetings | `/api/office` schedule / running / recent (existing) |

## 거래 화면 채우기 (fill-trade)

Market-native data and wide layouts for 거래 and 알림 기록 (dashboard + read-only server). Tests: tests/test_dash_fill_trade.py.

| Addition | Screen / place | Server (read-only) |
|---|---|---|
| 코인 온도판 | 시장, top: 7 tiles (price glows only when it really moved, 24h %, place inside the 24h low-high range, 24h 거래대금, funding with countdown; XRP 기록만); a tile opens 차트 | none (store ticker, /api/ticker) |
| 시장 파생 지표판 | 시장 (screens/market-live.js `flowBoard`): per traded coin 미결제약정 USDT with 1h / 24h change, 24h sparklines of OI and 롱/숏, 롱/숏 (전체 계좌) now vs 24h ago, 고수 포지션 롱/숏, 테이커 매수/매도 1시간, 프리미엄; plain hints (롱 쏠림, 미결제 급증 ...) with their fixed rules shown; no flow.db = 수집 전 | `/api/v4/flowlive` (dash/more/flowlive.py `flow_live`, flow.db `mode=ro`, 60 s cache) |
| 시장 강제청산 보드 | 시장 (market-live.js `liqBoard`): per coin long vs short liquidated USDT over 1h and 24h as split bars, the biggest single one, the latest 5 (new ones slide in); stale recorder (2 h without a row) says so; 1-per-second undercount note | `/api/v4/flowlive/liq` (flowlive.py `liq_board`, liq.db `mode=ro`, 20 s cache) |
| 경제발표 일정 'null' 고침 | 시장 › 미국 경제발표 일정: no stray "null" text under the list | none |
| 포지션 펼쳐 보기 | 포지션 at 1280 px and wider: every card open in a 2-3 column grid (v3 포지션), 12 per page; a phone keeps the accordion | none (/api/board + ticker) |
| 위험 사다리 | 포지션 side column (screens/positions-risk.js): open positions ranked by % distance from the mark to the liquidation price, with the distance to the stop / lock line; bars move with the 5 s mark, a row within 1 % pulses; distances only, no money (DeepSeek and coin flips listed with their group) | none |
| 알림 진입·청산 한국어 | 알림 기록 rows and every `alertKo` user: the engine's ENTRY / EXIT lines as "V4.4_TREND · 4시간 진입: LTC 숏 30배 (보통 자리)" with chips 증거금 / 손절 / 청산가 (exit: 손익 / ROE / 잔고); DeepSeek (F*) and coin flips (RANDOM_*) without margin, P&L, ROE or balance (D10/D11) | none (core/alerts.js `tradeAlert`) |
| 알림 24시간 막대 | 알림 기록, right column at 1500 px+ (below on a phone): hourly bars of 긴급 / 주의 / 정보 and of 진입 / 청산 alert lines for the last 24 h; hours older than the newest 500 rows are hatched (모름, not 0) | `/api/analysis/alerts?limit=500` |
| 차트 패널 쌓기 | 차트 at 1280 px+: 이 코인 포지션, 최근 신호, 시장 강제청산, 가격 알림 as stacked cards; 체결 / 호가 stay as tabs; a phone keeps one tab at a time | none |
| 이 코인 시장 지표 | 차트, under 시세: the chosen coin's 미결제약정 (1h / 24h), 롱/숏, 고수 포지션, 테이커, 강제청산 1h / 24h and the biggest one, OI sparkline, hints; link to 시장 | `/api/v4/flowlive`, `/api/v4/flowlive/liq` |

## fill-strat: 매매법 차트·목록·한눈 지도·분석 채우기 (owners 10/06 "화면들은 부족한 게 좀 있어 보여")

Dashboard only (one read-only route). Tests: tests/test_dash_fill_strat.py.

| Addition | Screen / place | Server |
|---|---|---|
| 차트 표시 말 (v3 계좌 차트처럼) | 매매법 상세 · 딥시크 · 릴스 차트: 진입 화살표 '롱 30배' / '숏 20배', 청산 점 '익절 잠금 +15%' / '손절 −22%' / '시간 청산' (딥시크: 이유만, 돈 숫자 없음); 그 코인의 모든 봉 계좌 거래, 다른 봉은 작은 봉 표시 · 회색; 최근 180봉이 보이게 | `/api/account/<id>` (기존) |
| 차트 실시간 봉 | 마지막 봉과 가격선이 공용 시세(5초)로 움직임, 가격 글자 오르면 초록·내리면 빨강 반짝; 봉이 닫히면 한 번 다시 불러 조건표도 새로 | `/api/ticker` (store, 기존) |
| 매매법 36개 한눈에 | 매매법 목록 ≥1280px: 페이지 없이 2단(≥1680px 3단) 모두; 포지션 열린 줄은 빛나는 테두리 + ● 코인·방향·배수 + 지금 평가 ROE (마크, 미실현 캡션); 딥시크 줄은 포지션만 | `/api/board` + store ticker |
| 방금 나온 신호 | 매매법 목록 옆(폰: 아래): 모든 매매법의 최신 신호 12개 (시각·매매법·코인·봉·롱숏·진입 / 건너뜀 + 이유), 30초마다, 새 신호만 미끄러져 들어옴; 누르면 그 매매법 차트 그 코인·봉 | `/api/signals?limit=12` (기존) |
| 한눈 지도 '5년 시험' 색 | 기존 36 · 딥시크 44: 칸 = 5년 과거 시험의 거래 한 건 평균 (36: 증거금 대비 ROE, 딥시크: 레버리지 없이 가격 %) + 승률, 초록/빨강, '5년 과거 시험 · 참고'; 자료 없는 칸은 점선 | `/api/v4/grid/y5` (dash/more/grid.py, vs5y.five_year, 1시간 캐시) |
| 한눈 지도 '지금 포지션' 색 | 포지션 열린 칸만 빛남: 지금 평가 ROE (5초마다) + 코인·방향·배수; 열린 칸 수 · 평가 이익/손실 칸 수 | `/api/v4/grid` `open` + board + store ticker |
| 분석 '채워지는 중' | 손익비·위험 / 계좌 겹침 / 조합 시너지: 실제 기준과 지금 진행을 채워지는 막대로 ('계좌마다 거래 20건 필요 · 지금 가장 많은 계좌 8건 · 20건 넘은 계좌 0/144', '같이 쌓인 기록 7일 필요 · 지금 1.2일째'), 그 사이 볼 수 있는 5년 과거 시험(한눈 지도 › 5년 시험) 링크 | 기존 답의 `drawdown.min_trades`, `rules.min_trades/min_days`, `min_trades` + board |
| 다시보기 첫 화면 자동 재생 | #/replay: 기존 36·5분봉에서 가장 최근 닫힌 거래가 목록 위에서 저절로 한 번 재생 (움직임 줄이기 설정이면 멈춘 채), '이 거래만 크게 보기' | `/api/v4/replay/<id>` (기존) |
| 순위표 실시간 ROE (fill-people) | 순위표 열린 포지션 칩 '● LTC 숏 30배 +20.4%' + 빛남: 기존 36 · 5분봉 · 추가만 (딥시크·동전 봇은 칩만, 손익 없음) | `/api/board` position + `/api/ticker` mark (derive.livePnl) |
| 순위표 카드 / 표 (fill-people) | 전체 목록 '카드 · 표' 전환 (이 기기에 기억): 표 = 한 쪽 50줄, 머리글 눌러 정렬, 순위·계좌·잔고·수익률·거래·승률(n승 n패)·최대 낙폭·상태(실시간 ROE)·동전 봇 대비(참고); 섞인 목록에서 딥시크·동전 봇은 개수만 | `/api/board`, `/api/ticker` |
| 순위표 → 분석 (fill-people) | 순위표 목록 아래 '더 보기 (분석)': 코인별 · 시간대별 성적, 코인·장세 지도, 계좌 겹침, 손익비·위험 (v3 순위표 아래에 있던 것) | links only |
| 계좌 차트·고르기 (fill-people) | 계좌: 코인별 진입·청산 차트가 프로필 카드 바로 아래 전체 폭, 열린 포지션 또는 마지막 거래 코인으로 열림, 첫 거래 40봉 전부터 지금까지 확대, 붐비면 짧은 글씨; 프로필 카드가 곡선을 그리면 자본 곡선 칸 없음; #/account (id 없음) = 찾기 있는 계좌 고르기 (지난번 본 계좌 또는 저장된 묶음 1위 먼저) | `/api/account/<id>`, `/api/candles`, `/api/board` |
| 회의실 상황판 (fill-people) | 대표실 옆 픽셀 상황판: 코인 시세(바뀔 때만 반짝), 오늘 닫힌 거래·승패 (기존 36·5분봉·추가는 손익, 딥시크·동전 봇은 개수만), 지금 열린 포지션 수, 오늘 손실 카드 수, 다음 정기 회의까지 남은 시간; 상태 줄에도 남은 시간 | `/api/v4/people/today` (dash/more/people.py), `/api/ticker`, `/api/board`, `/api/office` schedule.next.at_ms |
| 판정 거래 많은 계좌 (fill-people) | 판정 무대 좌석표 옆: 닫힌 거래가 가장 많은 판정 계좌 5개 'V4.0_TREND · 4시간 9/30' + '지금 속도면 10/21쯤 30건' (참고, 합격·불합격 아님, 이틀 전엔 표본 적음; 딥시크는 이름 없음) | `/api/board`, `/api/summary` start |
| 매매법 방 회의 전 (fill-people) | 에이전트 방: 첫 회의 전 매매법 방 목록 줄 = 그 매매법의 가장 최근 실제 일 (닫힌 거래 또는 신호); 빈 대화 칸에 코드 기록 상자 (오늘 봉별 거래·승패·손익, 지금 열린 포지션, 최근 거래, 최근 신호) | `/api/v4/people/strats`, `/api/v4/people/strat?name=`, `/api/board` |
| 토론방 꺼짐 탭 (fill-people) | 에이전트 › 토론방 탭이 늘 보임 (꺼져 있으면 흐린 '꺼짐' 표); #/debate = '아직 시작 전 · 켜면 하루 종일 토론' 카드 (홈으로 튕기지 않음) | `/api/debate` ready / state |
| 개수만 (fill-fix) | 포지션 카드·합계·손절 주문·체결 기록, 차트 '이 코인 포지션'·체결·가격선 이름표: 묶음을 딥시크/동전 봇으로 고르지 않으면 딥시크·동전 봇은 방향·배수·가격·거리만 (손익·ROI·증거금·크기 없음, 진입 뒤 가격 선은 회색), 합계 줄에 '딥시크·동전 봇 n개 (개수만, 합계에서 뺌)' | `/api/board`, `/api/trades` (positions-kit `countOnly`, derive `countOnlyIn`) |
| 전체 순위 개수만 (fill-fix) | 순위표·홈 '전체' (카드·표): 딥시크·동전 봇은 순위 없이 맨 뒤 (딥시크, 동전 봇 순, 이름순), 잔고·수익률·낙폭·반짝임·순위 화살표·작은 선 없음 | `/api/board` (derive `mixedOrder`) |
| 위험 사다리 깜빡임 (fill-fix) | 청산가 또는 손해 보는 손절선 0.5% 안일 때만 깜빡임; 수익 쪽 잠금선은 초록 '잠금까지', 깜빡이지 않음 | `/api/board`, `/api/ticker` |
| 작은 말 바로잡기 (fill-fix) | 홈 잘한·못한 계좌 줄마다 '표본 적음' + 2,000건에서 잘리면 '최근 2,000건만'; 방 코드 기록 신호 0건 = '아직 없음' (못 읽음만 '수집 전'); 강제청산 시각 어제면 '어제 06:52'; 차트 거래대금·강제청산 만/억; 한눈 지도 5년 시험·지금 포지션 칸 글씨 12px; 매매법 목록 PC 2열·이름 한 줄; 빈 방 일정 문장 한 번만; people.py 읽기 오류 = error 필드 | — |

## 터미널 v2 (term-v2: the HelloQuant reference, "읽기 편하게")

Owners 10/06: they like the HelloQuant terminal and find ours hard to read. The side, top and bottom areas were reworked
toward that clarity; the chart itself (terminal-chart.js) is unchanged, it only got more room. Dashboard plus one
read-only route. Supersedes the 터미널 rows above where they differ (the watchlist column, the 큰 체결 · 청산 switch,
이 코인 포지션's market rows, the group median card). Tests: tests/test_dash_term_v2.py.

| Part | What it shows | Server |
|---|---|---|
| Top strip | one line: coin, big price, 24 h %, 24 h 거래대금 (high / low / mark in its title), 펀딩 + countdown, then **시장 전체 (우리 봇 아님)** · 급등 · 급락 · 음펀비 (top 24 h gainer, top loser, most negative funding over every Binance USD-M perpetual; the top 3 of each in the title; "수집 전" before the first answer, the time of the last good answer when Binance failed), the session and the KST clock; the AI 회의 결론 line under it (hidden under 820 px tall). The label comes first so a narrow window cuts the last mover, never the label | `/api/v4/movers` (dash/more/movers.py: ONE all-symbol `/fapi/v1/ticker/24hr` (weight 40) + ONE `/fapi/v1/premiumIndex` (weight 10) per 60 s for every viewer, via app `_get_json`; perpetuals only, frozen / dust symbols left out; stale on failure); the page asks once a minute |
| Coin strip | the 7 coins over the chart (price, 24 h %, GH 판단 while `features.ghcoin`); a tap picks the coin; a real relay tick lights that coin | `/api/ticker`, `/api/v4/ticks` (unchanged) |
| Left column | three stacked dense lists, no switch, each with its ratio bar beneath, flex-shared on short windows: **실시간 큰 체결** (▲/▼ coin · price · 고래 · $ · age; rows tinted by side, whales filled and badged; 매수 / 매도 % and $ of the last 5 minutes; "바이낸스 시장 전체 체결 (우리 봇 아님)"), **시장 강제청산** (LONG / SHORT · price · $ · age for the chosen coin, ≥ $100k highlighted; 롱 / 숏 % and $ of the last hour; "바이낸스 시장 전체 (우리 봇 아님)"; hidden unless `features.liq`), **우리 봇 체결** (age · 진입 / 손절 / 잠금 / 청산 · account · coin side · P&L or price; DeepSeek / coin flips as count rows; recent entries 롱 / 숏 %). Ages ('6s', '4m', '2h') repaint on the 1 s clock tick (text only) | `/api/v4/ticks`, `/api/liq` (10 s), `/api/trades` + stream (unchanged) |
| Right column | **이 코인 포지션** (ours: 기존 36 · 5분봉 · 추가; ROE, 청산가; DeepSeek / coin flips counted only; "주문 버튼 없음" caption; 호가 behind its switch), **수익 차트** (기존 36 realized P&L: cumulative line from the run start + daily bars; 참고), **오늘 수익** (today's realized sum, trades, wins), **수익 캘린더** (each KST day's realized P&L of the 36 in its cell, green / red by sign, 기록 없음 days blank) | `/api/v4/flow/calendar` (`g.core.pnl / trades / wins`, 5 min) |
| Positions table | one head line: 포지션 n / 체결 / 손절 주문, **ALL** (= 기존 36 · 5분봉 · 추가) or one group, 롱 / 숏 share bar with %, 열린 n, 미실현 합계; dense aligned rows; foot: the open-P&L caption, "딥시크 n · 동전 봇 n개 열림 (건수만)" | `/api/board`, `/api/trades` (unchanged) |
| Not shown | whale on-chain transfers (HelloQuant's "Whale Transfer") need a paid on-chain source: not faked, not shown | — |
## 클릭 줄이기 (nav-rail; owners 10/06 "들어가는 클릭버튼이 너무 많아서 들어가서 보는게 귀찮다"; tests/test_dash_nav.py)

- **왼쪽 아이콘 줄** (`core/rail.js`, `core/nav.css`): 창이 1200px 이상이면 다섯 묶음의 모든 화면이 왼쪽 세로 줄에 아이콘으로 바로 나옵니다 (묶음 사이 얇은 선, 마우스·키보드 초점에 이름과 단축키, 지금 화면은 강조색, 새 소식 점 그대로). 한 번 누르면 어느 화면이든 갑니다. 그 폭에서는 묶음 막대와 아래 탭 줄이 숨고 (`--sub-h: 0`), 위 막대에 "묶음 › 화면"이 나옵니다. 글자 크기 · 화면 색 · 예전 화면(v3)은 줄의 맨 아래. 1200px 아래는 예전 그대로 (묶음 막대 + 탭, 폰은 아래 막대).
- **옆 창** (`core/drawer.js`, `screens/account-peek.js`): 어디서든 계좌 · 매매법 · 닫힌 거래(다시보기) 링크나 줄을 누르면 페이지를 떠나지 않고 오른쪽 옆 창(PC 약 540px, 폰은 화면 전체)에 요약, 진입·청산이 찍힌 작은 봉 차트, 열린 포지션, 최근 거래가 나옵니다. '전체 화면으로'는 원래 페이지. Esc · 바깥 누르기 · ✕ · 뒤로 가기(폰 포함)로 닫힙니다 (옆 창은 기록 한 칸: 뒤로 가기는 창만 닫음). 이미 그 화면에 있으면 (계좌 화면의 다른 계좌 링크 등) 링크는 원래대로. 각 페이지의 조각을 그대로 씁니다 (positions-kit, account-pick, grid-kit 프로필 카드, strategies-calc/panels). **정직**: 섞인 목록에서 연 딥시크·동전 봇 계좌는 개수만 (잔고·수익률·손익·ROE 없음, 청산 점은 회색, 참고 표시); 그 묶음만 고른 화면(`?g=ds` / `?g=coin`)에서 열면 그 묶음 규칙대로.
- **찾기** (`core/find.js`, `core/search.js`): `/` 또는 위 막대의 찾기(폰은 탭 줄 맨 앞). 화면 · 매매법 · 계좌를 한글 이름, 코드, 초성(ㅅㅇㅍ → 순위표)으로 찾고, 계좌·매매법은 옆 창으로 엽니다.
- **숫자 키** (`core/navkeys.js`): 1 터미널 · 2 홈 · 3 포지션 · 4 매매법 · 5 순위표 · 6 회의실 · 7 차트 · 8 시장 · 9 서버 (입력 칸에서는 안 먹음).
- **폰 옆으로 밀기**: 화면을 좌우로 밀면 같은 묶음의 다음 / 이전 화면 (차트, 옆으로 스크롤되는 표·탭, 입력 칸 위에서는 안 함). 아래 막대 + 탭으로 어느 화면이든 두 번 안에.
- 첫 화면은 그대로: PC(1200px 이상) 터미널, 폰 홈.
