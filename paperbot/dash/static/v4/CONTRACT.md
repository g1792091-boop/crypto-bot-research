# Dashboard v4: the screen contract and builder assignments

The architect has built the shared foundation. Five builders now fill the screens in parallel. Read this file and `INVENTORY.md` first. Then read the owner-approved mockup in `scratchpad/mock/dashboard_v4_mock.html`; its markup uses the same class names as `components.css`. The worked example of everything below is `screens/_kit.js`, which is the component sheet on real data at `#/_kit`.

## 0. Hard rules (all builders)

### Files

- Write ONLY your own `screens/<name>.js` and `screens/<name>.css`. Extra helper modules go in `screens/<name>-<part>.js`.
- Do NOT edit:
  - `core/*`, `tokens.css`, `base.css`, `components.css`, `index.html`
  - `paperbot/dash/app.py` and anything else in `paperbot/dash/static/` (team P10 is editing those)
- If a shared piece is missing, write it locally in your screen and list it as **CORE CANDIDATE** in your report. The architect merges these.
- Do not `git add` or commit.

### Code

- Vanilla ES modules, no build step, no frameworks.
- Import shared code from `../core/pb.js` only.
- No outside hosts. Prices come from `/api/ticker` and `/api/candles` (no Binance WebSocket). Charts use the vendored lightweight-charts through `core/lwc.js`.
- The only outside links allowed are TradingView and Coinglass, as `target="_blank" rel="noopener"` anchors in `chart.js`. `tests/test_dash_v4.py` enforces this.

### Text safety

- Build DOM with `h()` / `s()`. Strings become text nodes.
- Never use `innerHTML`, `insertAdjacentHTML`, `outerHTML`, `DOMParser` or `eval`; the test fails on any of them. To empty a node, use `clear(el)` or `el.replaceChildren(...)`.
- Model text, staff messages, owner posts, account names and anything else from the server are text, always.

### Numbers

- Use only `fmt.*`: `money`, `usdt`, `pct` (input is a ratio), `price`, `int`, `compact`, `lev`.
- For times use `kst`, `hm`, `mmdd`, `date`, `dur`, `ago`.
- Never call `toLocaleString` or `Intl.NumberFormat`; the test enforces this. Use `toFixed` only for SVG coordinates.
- The minus sign is `−` (fmt does it). Everything is in Korea time.

### Lists

- Never render more than about 20 rows at once. Use `ui.pager` / `ui.searchList` (10 per page).
- The screenshot check fails a screen with more than 150 list rows.

### Storage

- Use `local.get/set` (try/catch inside), and only for per-viewer conveniences: last tab, filters, seen ids, a dismissed banner.

### Phones first

- Every screen must work at 390 px wide: no horizontal page scroll (the screenshot check fails it), 16 px side gutter (the shell gives it), and touch targets of 32 px or more.
- Wide tables go in `.tbl-wrap` (scrolls inside itself), or become `.lrow` rows on phones.

## 1. Honesty rules (non-negotiable)

1. **Never invent activity.**
   - No typing effect for finished messages.
   - No endless activity bars or spinners. Use a shimmer only while a request is really in flight.
   - `LIVE` / `회의 중` / `토론 중` come only from real state: `office.running`, `rooms[].running`, and `stream.live()` (stream connected AND heartbeat under 90 s).
   - Bubbles show only real stored lines. `motion.slideIn` / `popBubble` / `countTo` / `walkTo` run only when real data changed: a new id, a new value, a meeting that newly appeared in `office.running`.
2. **Every money number has the assumptions caption.**
   - `ui.assume()` prints `모의 · 실제 시세 · 수수료·펀딩·슬리피지 포함`, and goes under closed / realized money.
   - `ui.assume("open")` goes under unrealized P&L. That P&L is at the mark price and before the exit fee, and the caption says so.
   - The LED bar prints its own caption.
   - The screenshot check fails a screen that shows `USDT` without one.
3. **No pass/fail hint before the checkpoint verdict.**
   - Any comparison with coin flips is labelled 참고 and carries `ui.refNote(verdictTs)` ("판정은 30일째 … 지금 비교는 합격·불합격을 뜻하지 않습니다").
   - No p-values, no ✓ / ✕, no green/red "passes" before `/api/checkpoint` says `ready: true`.
   - DeepSeek (`kind: "ds200"`) accounts show nothing per account beyond a `pill("…", "ref")` (참고). Group-level DeepSeek medians are fine, with refNote.
4. **Escape all model text.** See section 0: h() only.
5. **Small samples say so.** Use `ui.smallSample(n, min)`, default min 20 trades. For graded predictions use the server's own `small` flags.
6. **What the server does not send is `ui.notYet()` (수집 전), never a made-up number.** Use it for CPU, memory, disk, DB size, the Telegram count, and the median curves until the NEEDS SERVER routes exist.
7. **Hide features that are not active.**
   - The router and the nav already hide `debate` until `features.debate`.
   - Inside a screen, hide:
     - the 45-question tab unless `features.questions`
     - GH Coin parts unless `features.ghcoin`
     - market liquidations unless `features.liq`
     - the 토론 console tab unless `features.debateRunning`

## 2. Design rules

- Colours: only the tokens in `tokens.css`, never a hex value in a screen. Dark navy surfaces, ONE yellow accent (`--accent`), green/red only for meaning (up/down, ok/bad).
- Signature pieces (`components.css`):
  - `ui.plate("이름")`: the ◆ label plate
  - `ui.bubble({...})`: the white 2 px pixel speech bubble, tails `tl` / `tr` / `lft`
  - `consolePanel()`: the dark "◆ 에이전트 콘솔 ◆" terminal. Yellow event lines, cyan staff lines, amber disagreement boxes; tabs 전체 / 에이전트 / 토론; tapping a meeting-start line filters to that meeting; long lines clamp to two lines with 더 보기
  - `ui.ledBar()`: the green LED balance bar
  - `figure({team, kind})`: the pixel person (office.js recipe), `clock(label, tz)` real clocks, `windowArt()`
  - `ui.stepStrip(steps, {done, now})`: lights ONLY the steps that really happened
  - `ui.gauge()`: 서버·비용 bars with the 60 % / 85 % marks
- Office look (builder D): warm wooden floor (`--wood*`), walls (`--wall*`), desks (`--desk*`), table (`--table*`), plates on rooms. See mockup section 05 and the reference images 39, 44 and 30–33.
- Motion (all off under prefers-reduced-motion; CSS and the helpers already obey it):
  - about 180 ms screen and tab transitions (the router swaps screens; use `motion.swap(el)` for tab content)
  - new console lines slide in and fade from the highlight
  - bubbles pop in
  - balance / P&L numbers count to new values over about 600 ms (`motion.countTo` / `ui.liveNum`)
  - idle figures breathe 1 px over 3 s (`figure({breathe: true})`, ambient only)
  - members walk to the table only when a real meeting starts (`motion.walkTo`)
  - smooth expand / collapse (`motion.expand`, `ui.disclosure`)
  - shimmer skeletons while loading (`motion.shimmer`)
- Calm, not cluttered (the owners' complaint about today's UI):
  - one main idea per card
  - at most two levels of nesting
  - secondary detail behind 더 보기 / 펼치기
  - no walls of chips
  - Korean plain words, the 두 분 voice

## 3. The screen module

```js
// screens/<name>.js
import {h, ui, fmt, derive, motion, store} from "../core/pb.js";

export async function mount(el, ctx) {        // el: <div class="scr" data-screen="<name>"> (empty)
  ctx.setTitle("화면 이름");
  el.append(ui.screenHead("화면 이름", "한 줄 설명"));
  ctx.watch("board", (b) => { if (b) render(b); });            // shared, polled while watched, stream-refreshed
  const d = await ctx.api("/api/whatever");                    // aborted automatically when the screen is left
  ctx.every(30000, refresh);                                   // paused while the page is hidden, stopped on leave
  ctx.on("trades", (rows) => ...);                             // live stream events
}
export function unmount() {}                                   // optional extra cleanup (ctx already cleans its own)
export function update(params) {}                              // OPTIONAL: same screen, new #/<name>/<arg>: update in place
```

Rules:
- Keep per-mount state inside `mount` (module-level variables survive between visits).
- Guard late async work with `ctx.alive()`.
- `mount` may be async. The router shows a shimmer until its first await settles, then fades the screen in.
- CSS: prefix every class with the screen name (`.home-…`, `.rooms-…`), or scope under `[data-screen="<name>"]`. The file is loaded once, on first use, and never unloaded.
- Links: `ctx.href(name, arg, query)` → `#/name/arg?k=v`, and `ctx.go(...)` navigates. Account ids contain `@`: `ctx.go("account", "S5_DONCHIAN_MFI@15m")`.

### ctx

| Member | What it does |
|---|---|
| `params` | `{name, arg, query}` from the hash |
| `api(path)` / `post(path, body)` | Same cookie as the old UI. A 401 goes to `/login`. Throws `ApiError {status, detail}` (detail is the server's Korean message for owner writes). Aborted on leave |
| `store` / `watch(key, fn)` | Shared data (below). `fn(value, key, err)` runs now when cached and after every refresh |
| `on(evt, fn)` | Bus events (below) |
| `every(ms, fn, {now})` | Polling |
| `timeout(fn, ms)` | — |
| `listen(el, evt, fn)` | DOM listeners outside `el` (window, document) |
| `track(disposer)` | Any other cleanup |
| `features` | `{debate, debateRunning, questions, ghcoin, liq, priceSender, probed}` |
| `toast(text)` | — |
| `setTitle(t)` | — |
| `alive()` | — |
| `signal` | The screen's AbortSignal |

### store keys (`core/store.js`; one fetch serves every screen)

| Key | Route | Polled every | Also refreshed by |
|---|---|---|---|
| board | /api/board | 60 s | stream changes and new trades (debounced 0.4 s) |
| summary | /api/summary | 60 s | — |
| health | /api/analysis/health | 60 s | — |
| status | /api/status | 60 s | new alerts |
| ticker | /api/ticker | 5 s | — (only while watched; `store.mark(sym)`) |
| office | /api/office | 6 s | room changes |
| rooms | /api/rooms | 20 s | room changes |
| usage | /api/agents/usage | 60 s | — |
| checkpoint | /api/checkpoint | 10 min | — |
| debate | /api/debate | 5 min | — |
| levwhy | /api/levwhy | 30 s | — |

`store.need(key, maxAgeMs)` returns a promise of the value.

### bus events (`core/api.js`; one `/api/stream` connection per page)

| Event | Payload |
|---|---|
| `board:changed` | `{account_id: [wallet, trades, bust, position]}` |
| `trades` | new closed trades: `[{id, account_id, symbol, exit_reason, roe, pnl, equity_after, exit_time, …}]` |
| `alerts` | `[{rid, ts, level, text}]` |
| `rooms` | `{room_id: newest message id}` |
| `heartbeat` | `[ts, {last_step}]` |
| `stream:state` | `"open"` / `"error"` |
| `route` | — |
| `features` | — |

`stream.live()` is true only while the stream is connected AND the bot heartbeat is fresh.

### pb.js exports (see each file's header comment)

- `h, s, $, $$, clear, put, text, on, esc, hueOf, local`: DOM (`core/dom.js`)
- `fmt`: number / time formats, `TF_KO`, `tfKo`, `coin`, `reasonKo`, `sideKo`, `GROUPS` (기존 36 / 딥시크 44 / 5분봉 / 동전 봇 / 추가 계좌), `groupOf(a)`, `acctName(a)`, `idName(id)`, `stratKo(s)`, `familyKo(a|code)`, `usd` (real dollars), `TF_ORDER`
- `ui`:
  - `assume`, `refNote`, `smallSample`, `notYet`, `note` (small grey note)
  - `plate`, `pill(text, "good"|"bad"|"warn"|"accent"|"thin"|"ref")`, `livePill`, `sideTag`
  - `empty`, `errorBox(err, retry)`, `avatar`, `liveNum`, `stat`, `kv`, `card({title, plate, sub, acts, hero})`, `screenHead`
  - `seg(options, value, onChange)`: tabs with arrow keys
  - `moreText(text, lines)`, `disclosure(label, content)`
  - `bubble({who, time, text, tail, fresh})`, `stepStrip`, `gauge`
  - `pager`, `searchList`, `table` (small tables only)
  - `sparkline`, `curves({series, base, xlabels})`: thin lines drawn at the real box width
  - `ledBar()` → `.update({total, initialTotal, live, curve, stats, right, caption})`
  - `toast`
- `motion`: `reduced`, `play`, `swap`, `slideIn`, `popBubble`, `countTo(el, v, {format, dec, sign, suffix, tone})`, `expand`, `shimmer`, `walkTo`
- `derive`: `median`, `groupStats(board)` (per group n, bust, open, medWallet, medRet, above / below the same-TF coin-flip median, sumWallet, pnl; strategy-wide and coin medians; totals), `ranked(board, group)`, `livePnl(pos, mark)`, `liqDistance(pos)` (entry → liquidation at entry, for the why-leverage line), `distTo(mark, level)`
- `figure`, `clock`, `windowArt`, `TEAM_HUE`
- `consolePanel({title, tabs, foot, maxHeight, max})` → `.setLines(lines)`, `.push(line)`, `.showEmpty(text)`, `.setFoot`, `.clearFilter`. A line is `{id, type: "ev"|"st"|"dis"|"bad", tabs: ["agent"|"trade"|"debate"], meeting, ts, who, text, start, onOpen}`
- `alertKo(text)` (English engine alerts → Korean), `criticalLines`
- `store`, `features`, `bus`, `api`, `apiText`, `post`, `serverNow`, `stream`, `ApiError`, `href`, `SCREENS`, `GROUPS`, `setBadge(screen, on)`, `startTour`
- `bars`: `ALL_TFS`, `SYMS`, `TRADE_SYMS`, `TF_MS`, `barEnd`, `closeIn`, `session`, `usMarket`
- `loadLwc`, `makeChart(el)` → `{chart, L, dispose}`, `chartOptions` (Korea-time axis), `candleOptions`, `tok`, `kstTick`, `priceDec`: lightweight-charts v4, same origin
- `DS_FAMILY_KO`, `DS_NAME_KO`, `dsFamilyOf`: the v4 name table (`core/names.js`)

## 4. Assignments and what each screen shows

Old features are mapped row by row in `INVENTORY.md`. Every row assigned to you is part of your scope. Group cards and lists read `derive.groupStats` / `derive.ranked`, so all screens agree.

### Builder A — 홈 group: `home`, `board`, `checkpoint`

**home (요약)**

1. Headline card (`card({hero: true})`, mockup screen 01):
   - plate 30일 실험
   - `D+n / 30` from `summary.restart`, with a progress bar
   - 동전 봇보다 나은 매매법이 있나?
   - first verdict date, days left, account count
   - **thin curves**: strategy-account median vs coin-flip median (`ui.curves`). The data needs NEEDS SERVER #2; until then show `notYet("곡선 수집 전")`, never a fake line.
   - legend: "매매법 N개 중앙값 5,075.20 +1.5%" vs "동전 봇 N개 중앙값 …" (`groupStats.strat`, `.coin`)
   - W-L: "같은 봉 동전 봇 중앙값보다 위 a · 아래 b", with a bar
   - `refNote` + `assume()`
2. LED balance bar:
   - total of every wallet vs the starting total
   - LIVE = `stream.live()`
   - right side: P&L per group (`groupStats.groups[g].pnl`)
   - stats: today's trades / wins / liquidations from `summary.today`. That sum covers kind `strategy` only; label it 기존 36.
3. Group cards: 기존 36 / 딥시크 44 / 5분봉 / 동전 봇 (+ 추가 계좌 when any). Each shows count, median return (`liveNum`), "동전 봇 중앙값보다 위 a/n (참고)" and busts. Tap → `#/board?g=<id>`.
4. Top 5 / bottom 5 of the chosen group, and a 전체 목록 link.
5. Today: best / worst accounts (`summary.today`) and next events (`summary.events`, `office.schedule.next`).
6. A short console: real events from `/api/office` (meeting starts / decisions) and `[거래]` lines from `trades`. It has a link to 회의실.

**board (순위표)**

- Group cards → top 5 / bottom 5 → `searchList`, 10 per page.
- Filters:
  - TF (5분 only when the group has it)
  - sort: 수익률 / 거래 수 / 승률 / 낙폭 작은 순 / 이름
- Row:
  - rank, name, return
  - meta: TF, group, trades, W-L, MDD, position status, `smallSample`, 파산
  - 참고 vs coin median: core group only; ds200 gets the 참고 pill only
- Tap → account.
- 봉별 요약 card. CSV links. Extra accounts card with pills.
- `?g=` query selects the group (from home).

**checkpoint (판정)**

- Before the verdict:
  - countdown
  - judged accounts with at least 30 trades, per TF ("진행 상황, 판정 아님", counts only)
  - how the verdict works (2,000 coin flips per account, FDR, 30-trade minimum → 보류, 4h observation, coin flips as yardstick)
- After the verdict, `/api/checkpoint` `ready`:
  - counts by status
  - luck numbers and warnings
  - paged rows with p, q, reason
  - snapshot hash

### Builder B — 거래 group: `positions`, `chart`, `market` + `account`

**positions (포지션)**

- Summary: count, unrealized total, long / short, coins line.
- Tabs: 포지션 / 손절·잠금 주문 / 오늘 체결. Sort by profit / loss / newest / nearest liquidation. Paged.
- Position card (mockup screen 02):
  - symbol, side tag, leverage, account name
  - LED unrealized P&L + ROI from `store.mark` (watch `ticker`; `countTo` on change)
  - **why-leverage line**, including the entry-time liquidation distance: "보통 자리 · 30배 · 증거금 30% · 진입 때 청산까지 2.9%" (levwhy `group_ko` / `short_ko` + `derive.liqDistance`)
  - kv: entry / mark / liq, size, margin, stop / lock
  - meter: now → stop → liq distances
  - lock rule in plain words
- Order book of the chosen coin.
- `ui.assume("open")`.

**chart (차트)**

- Everything in INVENTORY section 2 except the bottom tabs, with the vendored chart (`makeChart`).
- Live data:
  - `/api/ticker` (store) for prices
  - `/api/candles?limit=2` every 5 s for the forming bar
  - `serverNow()` for countdowns
- Side panels as tabs. Price alerts: add / delete / rearm via `post()`, showing the server's Korean error text.
- TradingView and Coinglass as new-tab links.
- On phones: chart first (height about 55vh), panels below as tabs.

**market (시장)**

- `/api/market` cards (fear & greed bar, dominance, mcap, indexes with sparklines, stale marks, calendar with D-days).
- 오늘·일정 card (`summary`, `bars.usMarket`, funding countdown from the ticker `T`).
- GH Coin current calls (feature).
- Note: outside context only.

**account (`#/account/<id>`, hidden tab)**

- Everything in INVENTORY section 8.
- Equity curve: `ui.curves` or lightweight-charts.
- Candle chart with markers per coin.
- Paged trades with the why line.
- CSV link. `update(params)` when the id changes.
- DeepSeek accounts: no per-account comparison beyond 참고.
- The reel (`kind: "reel"`) and the 5m flips use their own exits: swing-low stop, moving upper-band target, 96-bar time exit, no ladder. Do not describe a ladder lock for them.

### Builder C — 매매법 group: `strategies`, `analysis`

**strategies (매매법)**

- List: groups 기존 36 / 딥시크 44 / 5분봉; style filter (추세 / 되돌림); search; live record per strategy from the board (sum of its TF accounts, `smallSample`).
- Detail at `#/strategies/<name>` (implement `update`):
  - TF segment from its accounts' TFs, coin select
  - chart with overlays / panes from `/api/strategy/<name>`. A 404 is "차트 보기 준비 전" (DeepSeek / reel today).
  - its entries and exits, last-bar conditions checklist, last signal marks
  - 5-year profile + live risk
  - TF account tiles → account
  - 손실 카드 (paged) / 손실 패턴

**analysis (분석)**

- Sub tabs via `ui.seg(..., {scroll: true})`:
  - 손익비·위험, 실전 준비도, 충격 테스트, 코인·장세 지도, 진입 순간, 조합 시너지, 좋은 자리 vs 보통, 그림자 비교 (curves + account picker)
  - 코인·시간대 (`/api/breakdown`), 계좌 겹침 (`/api/overlap`), GH Coin (feature), 45개 질문 (feature)
- `{pending: true}` answers: shimmer, then retry after 3 s.
- Every table keeps its "how to read" line and its small-sample marks.
- Comparisons with coin flips get `refNote`. levrule says "30일 판정 전 결론 없음" until day 30.

### Builder D — 에이전트 group: `office`, `rooms`, `digest`, `debate`

**office (회의실)**

1. Status line:
   - `livePill` "지금 회의 N개" only from `office.running`
   - next scheduled meeting
   - today's meetings and AI calls
2. Warm wooden pixel office (mockup section 05, images 39 / 44):
   - one room per team zone, with a plate and a 오늘 N회 counter
   - **전문가실**: the 36 strategy specialists + the 5 new group specialists (구조·유동성, 추세·눌림, 세션·시가, 반전·되돌림, 5분봉 단타). Show about 5 figures + a "+N" chip.
   - **대표실**: window, real KST / UTC / NYC clocks (`clock()`), the two owners (`figure({kind: "owner"})`) at a big desk
   - quiet rooms (no meeting today) small and dimmed
   - a live room gets the yellow border
   - participants stand at the table; others sit at desks; staff in another room's meeting are faded
   - members `walkTo` the table only when a meeting id is new in `running` since the last poll
   - bubbles: the real last line of each speaker (`running[].lines`, first sentence), `popBubble` only when the line changed
   - "다음 차례" only when `next_role` is set
3. Agent console: events (meeting start / decision from `running` / `recent`, `[거래]` from `trades`), staff lines (turns), disagreement boxes (`/api/digest/day` disagreements). Tabs 전체 / 에이전트 / 토론 (토론 only if `features.debateRunning`). Tap a start line → only that meeting; 방 열기 → rooms.
4. Today's finished meetings with step strips that light only the kinds that happened (analysis → challenge → revision → verdict).
5. The honesty note (bubbles are stored lines, not typing).

The new group specialists are not in `/api/office` roles yet. Read them from `/api/agents/roster` when present; otherwise show the 36 and say "그룹 전담 5명: 준비 중". Never draw people who do not exist.

**rooms (에이전트 방)**

- Everything in INVENTORY section 9, as a console frame (mockup section 06). Room list → chat → info panes on a phone (`#/rooms/<room_id>`, `update`).
- Unread via `local` seen ids; `setBadge("rooms", …)` on new messages (bus `rooms`).
- Owner post, @mention, approve / reject with a confirm step and the server's message.
- Raw JSON behind 원문 보기 (`disclosure`), never shown by default.

**digest (회의 요약)**

- Tabs 회의 결론 / 직원 성적표 / 주간 성적표 / 봉 비교 (`#/digest/<tab>`).
- 회의 결론: collapsible rows (time, room, result: 결정 / 행동 없음 / 진행 중 only if running), the lead's lines, step strip, excerpt, amber disagreement, 방 열기.

**debate (토론방, feature)**

- State + reason, month spend vs cap (`assume` is not needed: API cost is not paper money; say "실제 비용 (유료 API)").
- Latest rounds (text nodes), skipped / errors, graded hypotheses, scoreboard with `smallSample`, ideas, the caution line.

### Builder E — 서버 group: `server`, `alerts`, `signals`, `howto`, `faq`

**server (서버·비용)** (mockup screen 08)

1. One summary line, ok / warn / bad, from `health` plus problems and warnings.
2. Gauges:
   - CPU, memory, disk, DB size / growth: `notYet` until NEEDS SERVER #4
   - signal time per boundary vs limit: `status.signals_24h` average delay per TF vs 180 s (5m: 60 s); limits from config until #5
   - AI calls / tokens vs caps, today and 7 days, plus per class (`usage`)
   - debate month spend vs cap: only while `features.debate`, else "꺼짐 · 0"
   - Telegram count: `notYet`
3. Health tiles: everything `/api/analysis/health` has (bot, 1m data, signals, alerts, agents tick, nightly parity with the early_kline label, checkpoint, AI, liq recorder, job failures).
4. Run facts (accounts from the board, taker fee, brackets).
5. 로그아웃 button.

**alerts (알림 기록)**

- `/api/analysis/alerts` with a level filter (긴급 / 주의 / 전부).
- `status.alerts` through `alertKo`.
- Price alerts fired. Paged.

**signals (신호)**

- `/api/signals` with a TF filter (5분, 15분, 30분, 1시간, 4시간, 일봉(기록)), paged.
- Per-TF counts and average delay for the last 24 h.

**howto (어떻게 돌아가나)** (mockup screen 04)

- Step tabs 01 신호 → 02 진입 → 03 레버리지 → 04 청산 → 05 손실 회의 → 06 판정. Each tab has two or three sentences and an example box in console style, labelled 예시.
- Cover:
  - the 36, DeepSeek, the 5m reel with its own exits, coin flips
  - AI never trades
  - everything is 모의

**faq (자주 묻는 질문)**

- Short questions with smooth expand. Include what '참고', '표본 적음' and '수집 전' mean.
- **what costs money** table:

  | Category | Items |
  |---|---|
  | 무료 | the paper bot, this dashboard, Binance public prices, Tailscale |
  | Max 구독 | the agents' meetings use the owners' Claude subscription, with daily / weekly caps |
  | 유료 API | the 24-hour debate room, its own key and monthly cap |
  | Other | the server rental (Vultr), listed as its own line |

- Rule documents (`/api/doc/rules-change-1`, `/api/doc/levrule-eval`).
- 안내 다시 보기 (`startTour()`).
- 로그아웃.

## 5. How to check your screens

```
cd scratchpad/v4ui
python fixture_server.py                       # http://127.0.0.1:8765/static/v4/index.html, password fixture-password-1234
python fixture_server.py --port 8766 --folder ./world_crit --critical --stale --quiet   # red banner, red dot, no meeting
node shoot.js --routes home,board              # 390x844 + 1280x800 screenshots in shots/, report.json
node shoot.js --routes office --full --motion  # full page, motion on
python fixture_server.py --dump                # re-record api_samples/*.json
python -m pytest tests/test_dash_v4.py -q
```

- The fixture runs the real `create_app` on a synthetic 331-account world (`fixture_world.py`), with fake Binance and market fetchers. A live loop updates the heartbeat every 5 s, closes a trade about every 25 s, and adds a staff line about every 90 s (`--still` turns it off). It never uses real server data.
- `shoot.js` fails a screen on any of these:
  - a page error or console error
  - a failed same-origin request, or any request to a host other than this server and Google Fonts
  - horizontal scroll at 390 px
  - visible HTML tags in text
  - `USDT` without a caption
  - more than 150 rows
- Google Fonts are blocked by default, to prove the fallbacks; `--fonts` lets them through.
- Done means:
  - no FAIL lines in `shoot.js` for your routes at both sizes
  - `pytest tests/test_dash_v4.py` green
  - you looked at both screenshots

## 5b. Integration pass (after the five builders)

What the integrator changed, so later work starts from the same place:

- **Shared now (core), local copies removed:**
  - `core/names.js`: the DeepSeek family names, the 44 short names and the reel's name. `fmt.stratKo` / `fmt.acctName` / `fmt.idName` / `fmt.familyKo` use it after the server's own names (`strategy_ko` + `names_ko` from `/api/board`, the names Telegram uses). `screens/strategies-defs.js` takes its names from it.
  - `core/lwc.js`: `kstTick` (Korea-time axis, now in every chart's options) and `priceDec`.
  - `fmt.usd` (real dollars: API spend, server rental), `fmt.TF_ORDER`, `ui.note` (one small grey note style; `.an-note`, `.pos-note`, `.rk-note`, `.server-note` are aliases of `.note`).
  - CSS: `.screen > .scr` and `.card` are one `minmax(0, 1fr)` column; `a.lrow` links; `--glass` for sticky bars.
  - Kit css (`server-kit.css`, `rooms-kit.css`) is `@import`ed by each screen's css, like `home-shared.css` and `positions-kit.css` (no JS loaders).
- **Wording:** the verdict compares each account with **10,000** same-bar coin flips (`checkpoint.N_BOTS`); `ui.refNote`, the rules panel, 판정 and FAQ all say so, and a test ties the number to `checkpoint.py`.
- **Tour (`core/tour.js`):** 7 steps across 홈 → 포지션 → 회의실 → 서버. A step names its screen (`go`) and its targets in order (`[data-tour="headline"|"groups"|"positions"|"office"]`, then a shell element). Keep those `data-tour` attributes when you change those screens.
- **Old UI link:** 예전 화면 ↗ at the end of the 서버 group's sub tabs (`core/shell.js`).
- **h():** `on*` attributes take functions only (a string handler is dropped); `srcdoc` / `formaction` are never set.
- **Tests** (`tests/test_dash_v4.py`): every import resolves to an export, every file is reachable (no dead copies), screens reach core through `pb.js` (pure data `names.js` excepted), screen css has no colour literals, every old `/api` route is still called, every called route exists or is a listed NEEDS SERVER probe that degrades to 수집 전, the tour's targets exist, the captions are the shared ones.

## 6. NEEDS SERVER (exact routes the UI wants; until then it degrades as described)

Status after the review pass (team P10 is adding these to `app.py`): **#1 arrived** (rows carry `group`, `family`, `exits`, `name_ko`; the board carries `names_ko`; `run_shape` is counted from the accounts table; positions carry the reel's `tp` / `time_exit`), **#5 arrived** (`status.limits`), **#6 arrived with one open choice** (`summary.today.by_group`, read through `fmt.SERVER_GROUP`; see the 5m-flip note under #6). Gap pass: **#2 and #4 arrived** (`/api/v4/curves` drawn on 홈, `/api/v4/server` on 서버); the verdict method and rules come from `summary.restart` (`method_ko`, `n_bots`, `rules_label`, `doc`; core/ui.js `botsKo` / `methodKo`), never typed in. Still open: #3, #7 (now answered for DeepSeek and the reel by their own ids), #8, #9, #10. `tests/test_dash_v4.py` keeps `NEEDS_SERVER` for any future probe.

1. **`/api/board` rows: the v4 account facts.** (arrived)
   - Add `group`, `family`, `name_ko`, `exits` from `accounts.data` (paper3.db, written by the runner) for kinds `ds200` / `reel`.
   - Replace `run_shape` with one counted from the accounts table: `{"groups": {"core": {"accounts": 144, "judged": 108}, "ds": {"accounts": 171, "judged": 132}, "m5": {"accounts": 4, "judged": 1}, "coin": {"accounts": 15, "judged": 0}}, "judged_tfs": {...per kind}}`.
   - Today the UI groups DeepSeek by kind only and names it by code.
   - Team P1's `paperbot/groups.py` already has `group_of(row)`, `shape_from_db(conn)`, `DS_FAMILY_KO` and the five `V4_ROLES`. The server should send exactly those.
   - **Decided (owners):** the three `RANDOM_k@5m` count in 동전 봇 everywhere (`groups.py` is the single source; `fmt.groupOf` reads the row's own `group` first). The 5분봉 card shows the reel and, inside it, its three 5m flips as its labelled comparison ("비교: 5분봉 동전 3개 (동전 봇에서 셈)").
2. **`GET /api/v4/curves?step=3600000`**
   - Answer: `{"initial": 5000, "t": [ms…], "median": {"strategy": […], "ds200": […], "reel": […], "random": […]}, "total": […]}`
   - Source: the paper3.db `equity` table. Each account's last value in each step, carried forward; the median per kind; the sum over all accounts. About 30 days × 24 points.
   - Until then the headline curves and the LED curve show 수집 전.
3. **Console feed with rooms.**
   - Either `GET /api/agents/feed?after_id=&limit=` with `room_id`, `round_id`, `speaker_name` added, or `GET /api/v4/console?after_id=&limit=` → `[{id, ts, room_id, round_id, meeting, role, speaker_name, kind, text}]`
   - Source: agents3.db `messages`.
   - Until then the console uses `/api/office` (first sentences of running meetings) + room messages.
4. **`GET /api/v4/server`**
   - `cpu`: `{"pct", "cores"}` (/proc/stat)
   - `mem`: `{"used_mb", "total_mb"}` (/proc/meminfo)
   - `disk`: `{"used_gb", "total_gb"}` (os.statvfs of the data dir)
   - `db`: `{"paper3_mb", "agents3_mb", "daily3_mb", "growth_mb_day"}` (file sizes + a daily size log)
   - `signal_time`: `[{"tf", "bar_close", "max_delay_ms", "limit_ms"}]` (paper3.db `signal_log`, the last 24 h of boundaries)
   - `telegram`: `{"today", "week"}` (needs a send counter: the Telegram senders have no table today)
   - `services`: `{"name": "active"|"failed"}` (systemctl, optional)
   - Until then these show 수집 전.
5. **(arrived)** **Signal limits in `/api/status`:** `"limits": {"max_delay_ms": 180000, "max_delay_ms_5m": 60000, "timeout_s": 120}`. Today they are copied from `sigservice.py` / `config.FIVE_M_MAX_DELAY_MS` into server.js.
6. **(arrived)** **`/api/summary.today.by_group`:** keys `core` / `ds200` / `reel` / `flip` / `extra` (`groups.group_of`), each `{"trades", "pnl", "wins", "liquidations", "best", "worst"}`. **Decided:** the three `RANDOM_k@5m` are `flip` (동전 봇) on the server and on the page; the today card's rows are plain 5분봉 / 동전 봇.
7. **Strategy views for DeepSeek and the reel:** `/api/strategy/<name>` answers 404. The plan has a reel view def; DeepSeek views are not planned.
8. **Entry point:** `/login` sends the owners to `/` (the old UI), and `/static/manifest.json` has `start_url: "/"`. v4 already sends an expired session to `/login?next=<path+hash>`. Server side: `login.html` honours `next` only when it starts with `/` and not `//` (else `/`); serve `static/v4/index.html` at `/` or add `GET /v4` when the owners switch, and point `manifest.start_url` there.
9. **`/api/levwhy` for DeepSeek and the 5m accounts:** `short_ko` says "N배 (위 단계가 안 된 이유 기록 못 찾음)", which reads like a fault; under rules change 1 they always trade at the 보통 multiple (`config.py`). Send `short_ko: "딥시크·5분봉은 규칙상 늘 보통 배수"` (or `fixed: "normal"`) for kinds `ds200`, `reel` and `random` at 5m. The page already replaces the text.
10. **Compression:** add Starlette `GZipMiddleware(minimum_size=1024)` (skip `text/event-stream`): `/api/board` is about 220 KB of JSON per poll. The page already patches the board from the stream's `changed` map instead of re-downloading it on every event.
