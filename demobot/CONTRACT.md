# Demo lab bot ("데모 랩"): component contract

Owners approved the design on 2026-10-09 ("좋아"). This file fixes the interfaces between the three parts so they
can be built in parallel:

* **engine** (`demobot/*.py` except `notify.py` and `dash/`): Binance public data, signals of every grid setting,
  trade outcomes, the live ranking, the 48 accounts, the pass judgment. Writes the SQLite DB and the snapshot files.
* **dashboard** (`demobot/dash/`): read-only web view of the snapshot files, same look as the rule bot's v4 dashboard.
* **notify + deploy** (`demobot/notify.py`, `deploy/demobot/`, `docs/demobot/`): Telegram (a new room) and the
  server install.

The demo bot is fully separate from the rule bot (paperbot): its own code copy, user, venv, database, services,
dashboard port, Telegram bot. It never places an order and needs no exchange key (Binance public market data only).
It never reads or writes anything under `/var/lib/paperbot` or `/etc/paperbot`.

## 1. What it runs

* Strategies (locked code `research/entry_study/param_defs/*.py`, hash-checked): `S2_ST_ROC` (short `S2`),
  `N02_ST_KST` (`N02`), `N04_ST_KLINGER` (`N04`). Grid exactly as `research/st_custom/PREREG.md`
  (343 / 735 / 588 settings; `demobot/grid.py`).
* Coins: `BTCUSD ETHUSD SOLUSD DOGEUSD LTCUSD BCHUSD XRPUSD` (Binance USDT-M symbols `BTCUSDT` ...).
  Timeframes `15m`, `30m` (30m bars are built from 15m bars).
* Entry: at the close of the signal bar (the next 15m bar's open). Costs: taker 0.05% + slippage 0.02% per side;
  funding 0.01% per 8 h in the ranking (same as the 5-year study), real Binance funding in the accounts.
* Exits (13), index order fixed:
  `0 house` (rule bot exit: 2 x ATR14 stop + the paperbot ladder) then the 12 fixed take-profit / stop pairs
  `tp{TP}R_sl{K}atr` for K in (1.5, 2, 3) and TP in (1, 1.5, 2, 3), K-major:
  `1 tp1R_sl1.5atr, 2 tp1.5R_sl1.5atr, 3 tp2R_sl1.5atr, 4 tp3R_sl1.5atr, 5 tp1R_sl2atr, ... 12 tp3R_sl3atr`.
  Korean labels: `house` = "사다리(규칙봇 방식)", `tp1.5R_sl2atr` = "익절 1.5R · 손절 2ATR".
* Leverage lines: 20, 30, 40, 50 (each account has 4 separate wallets, $1,000 each). Sizing = the owners' rule:
  margin = L% of the wallet, one position per coin, rule-bot entry checks (stop must sit inside the liquidation
  buffer, bracket max leverage), liquidation price from the coin's first bracket tier. A wallet below 10% ($100)
  is ruined: the ruin is counted (`ruins`) and that wallet restarts at $1,000 so the record keeps going.

## 2. The 48 accounts (`id`, Korean name)

| kind | ids | rule |
|---|---|---|
| `fixed` / `default` | `fx-def-{S2,N02,N04}-{15m,30m}` | "S2 기본값 · 15분": defaults (ST 10/6 ...) |
| `fixed` / `friend` | `fx-fr-{S2,N04}-{15m,30m}` | "S2 친구 값 · 15분": S2 8/3 ROC 37, N04 8/3 |
| `fixed` / `pick` | `fx-pk-{S2,N02,N04}-{15m,30m}` | "S2 5년 1등 값 · 15분": study pooled rank-1 pick |
| `adaptive` / `r26` | `ad-r26-{S,tf}` | "자동 · 5거래마다(26주)": every 5 closed trades, best plateau setting (all coins together) on the last 26 weeks |
| `adaptive` / `r4` | `ad-r4-{S,tf}` | same on the last 4 weeks |
| `adaptive` / `r26c` | `ad-r26c-{S,tf}` | same, but each coin gets its own best setting (that coin's trades) |
| `adaptive` / `wk` | `ad-wk-{S,tf}` | every Monday 00:00 UTC (09:00 KST), all coins together, last 26 weeks |
| `friend` / `rule` | `fr-{S,tf}` | "친구 규칙 · 매주": every Monday, per coin and per leverage line, among (setting x exit) that made money in the last 26 weeks at that leverage, the one with the smallest drawdown; run it for the week |
| `flip` / `flip` | `cf-15m`, `cf-30m` | "동전 던지기": random side at random bars, house exit (luck reference) |

`{S}` is the short strategy name (`S2`, `N02`, `N04`), `{tf}` is `15m` / `30m`.

## 3. Server layout

| what | where |
|---|---|
| code (sparse copy of this repo) | `/opt/demobot/app` (owner root, read-only for the services) |
| Python venv | `/opt/demobot/venv` (numpy, pandas, fastapi, uvicorn) |
| database | `/var/lib/demobot/demo.db` (SQLite WAL; owner `demobot`) |
| snapshots (engine -> dashboard) | `/var/lib/demobot/snap/` |
| env | `/etc/demobot/demobot.env` (root:demobot 640) |
| user | system user `demobot` (no shell, home `/var/lib/demobot`) |
| services | `demobot-live.service` (engine; CPUQuota=30%, MemoryMax=1200M, Nice=10), `demobot-dash.service` (dashboard; MemoryMax=300M), `demobot-rank.timer` + `demobot-rank.service` (the ranking, hourly at :07, its own process; CPUQuota=50%, MemoryMax=1500M) |
| dashboard | `http://<DASH_HOST>:8090` (DASH_HOST = the server's Tailscale address, like the rule bot's 8080) |

Env keys (`/etc/demobot/demobot.env`): `DEMOBOT_TG_TOKEN`, `DEMOBOT_TG_CHAT`, `DEMOBOT_DASH_PASSWORD_HASH`,
`DEMOBOT_DASH_SECRET`, `DEMOBOT_DASH_HOST`, `DEMOBOT_DASH_PORT` (default 8090), `DEMOBOT_DB`
(default `/var/lib/demobot/demo.db`), `DEMOBOT_SNAP` (default `/var/lib/demobot/snap`).

Commands (run as the `demobot` user, venv python, working dir `/opt/demobot/app`):
`python -m demobot warm` (first fill: 26 weeks of history, ~10 min), `python -m demobot run` (the service),
`python -m demobot rank` (the hourly ranking; never creates the database), `python -m demobot status`,
`python -m demobot.dash` (dashboard), `python -m demobot.dash hash` (password hash),
`python -m demobot.notify test` (sends one test message).

## 4. Snapshot files (engine writes, dashboard reads)

All files are written atomically (temp file + `os.replace`). Times are epoch milliseconds (UTC); money in USD;
`R` = profit in units of the stop distance. Units: `pnl_pct` is a percent (4.2 = 4.2%), `win_rate` and `max_dd`
are 0..1 ratios. File names use the short strategy name (`rank_S2_15m.npz`, `past5y_N04_30m.npz`). Account ids
match `^[A-Za-z0-9-]{3,40}$`. `status.proc` has `rss_mb` and `cpu_s` (process CPU seconds). Missing values are `null`. The dashboard must tolerate a missing file
(show "준비 중") and must never write into `snap/`.

### `status.json`
```json
{"generated_ms": 0, "version": "demobot-1", "phase": "warm|live|stopped",
 "live_start_ms": 0, "history_start_ms": 0, "last_bar_ms": {"15m": 0, "30m": 0}, "last_tick_ms": 0,
 "tick_seconds": 0.0, "next_tick_ms": 0, "data_ok": true, "data_issues": ["..."], "errors": ["..."],
 "coins": ["BTCUSD"], "tfs": ["15m", "30m"], "leverages": [20, 30, 40, 50], "seed": 1000.0,
 "costs": {"taker": 0.0005, "slippage": 0.0002, "funding_8h_ranking": 0.0001, "funding_accounts": "real"},
 "counts": {"settings": 1666, "players": 23324, "cells_open": 0, "cells_total": 0, "signals_24h": 0},
 "proc": {"rss_mb": 0.0, "cpu_pct": 0.0}, "db_mb": 0.0, "disk_free_mb": 0.0,
 "telegram": {"configured": true, "queued": 0, "last_ok_ms": 0, "last_error": null}}
```

### `accounts.json`
```json
{"generated_ms": 0, "live_start_ms": 0,
 "accounts": [{
   "id": "fx-def-S2-15m", "kind": "fixed", "sub": "default", "name": "S2 기본값 · 15분",
   "strategy": "S2_ST_ROC", "short": "S2", "tf": "15m", "rule_ko": "기본값 그대로 (ST 10/6, ROC 9)",
   "setting_ko": "ST 10/6 ROC 9",
   "lines": {"20": {"equity": 1000.0, "wallet": 1000.0, "pnl": 0.0, "pnl_pct": 0.0, "today_pnl": 0.0,
                    "trades": 0, "wins": 0, "win_rate": null, "mean_R": null, "max_dd": 0.0, "open": 0,
                    "liqs": 0, "skipped": 0, "worst_streak": 0, "ruined": false,
                    "ruins": 0, "setting_ko": "ST 10/6 ROC 9"},
             "30": {}, "40": {}, "50": {}},
   "switches": 0, "last_switch_ms": null}]}
```
`setting_ko` on the account is the current setting in one line (for per-coin accounts: "코인별 7개 (BTC ST 14/2 ROC 50, ...)");
per line it can differ (friend rule: per leverage).

### `acct/<id>.json` (one per account)
Same header fields as the account row, plus:
```json
{"curves": {"20": [[0, 1000.0]], "30": [], "40": [], "50": []},
 "trades": [{"key": "BTCUSD|15m|1760000000000|1|20", "L": 20, "coin": "BTCUSD", "side": 1,
             "signal_ms": 0, "entry_ms": 0, "entry": 0.0, "stop": 0.0, "exit_ms": null, "exit": null,
             "status": "open|closed", "reason": "stop|lock|liq|tp|open|time",
             "pnl": 0.0, "roe": 0.0, "R": 0.0, "margin": 0.0, "funding": 0.0,
             "setting_ko": "ST 10/6 ROC 9", "exit_ko": "사다리(규칙봇 방식)"}],
 "decisions": [{"t_ms": 0, "coin": "ALL", "L": null, "from_ko": "ST 10/6 ROC 9", "to_ko": "ST 20/2 ROC 50",
                "why_ko": "최근 26주 주변 평균 1등 (-0.05R, 1,234건)"}],
 "settings_now": [{"coin": "BTCUSD", "L": null, "setting_ko": "...", "exit_ko": "..."}]}
```
`curves` are wallet-plus-open-value points, at most 800 per line (downsampled). `trades` newest first, at most 600.

### `trades.json`
`{"generated_ms": 0, "trades": [ ...same trade objects plus "account": id, "name": "..." ... ]}` newest 300 (all accounts).
In `home.json`, `recent_switches` rows are decision rows plus `id` (account id) and `name`; `recent_trades` rows are
`trades.json` rows.

### `judge.json`
```json
{"generated_ms": 0, "verdict_ko": "실전 금지: 아직 통과한 계좌가 없습니다",
 "rules_ko": {"ours": ["실시간 거래 100건 이상", "..."], "friend": ["지난 26주에 수익 + 낙폭 최소 설정을 일주일 돌려 +", "..."]},
 "rows": [{"id": "fx-def-S2-15m", "name": "...", "L": 20,
           "ours": {"pass": false, "checks": [{"name_ko": "실시간 거래 100건 이상", "ok": false, "value_ko": "12건"}]},
           "friend": {"pass": null, "checks": []}}]}
```

### `home.json`
```json
{"generated_ms": 0, "live_days": 0.0, "phase": "live",
 "totals": {"accounts": 48, "open_positions": 0, "trades": 0, "passed": 0},
 "best": [{"id": "...", "name": "...", "L": 20, "pnl_pct": 0.0}], "worst": [],
 "by_kind": [{"kind": "fixed", "kind_ko": "고정", "mean_pnl_pct": {"20": 0.0, "30": 0.0, "40": 0.0, "50": 0.0}}],
 "leaders": [{"strategy": "S2_ST_ROC", "tf": "15m", "window": "26w", "exit": "house", "label": "ST 20/2 ROC 50",
              "n": 0, "mean_R": 0.0, "win_rate": 0.0, "luck95": 0.0, "beats_luck": false}],
 "recent_switches": [], "recent_trades": []}
```

### `rank_<S>_<tf>.npz` (+ `rank_meta.json`)
Written by the separate hourly process (`python -m demobot rank`), not by the engine loop.
The live ranking ("순위표") of one strategy and timeframe, every setting, every exit, every scope, three windows.
Arrays:

* `stats`: float32, shape `(W, E, S, C, K)`:
  W = windows `["live", "26w", "4w"]` (since the live start; the last 26 weeks incl. the history fill; the last
  4 weeks), E = 13 exits (order above), S = scopes `["ALL", "BTCUSD", ..., "XRPUSD"]` (ALL = 7 coins pooled),
  C = settings of the strategy (index = `demobot.grid` combo index), K = stats in this order:
  `n` (closed trades), `wins` (net R > 0), `mean_R` (net), `mean_G` (gross, before costs), `mdd_R` (largest fall
  of the cumulative net R in time order), `whip` (share of signals followed by an opposite signal of the same
  setting within 3 bars: the noise measure), `avg_win_R`, `avg_loss_R` (positive number), `plateau` (mean of
  `mean_R` over the setting and its +-1-step grid neighbours with >= 1 trade; NaN if `n` < the window minimum),
  `open` (open trades), `nsig` (signals).
* `luck95`: float32 `(W, E, S)`: 95th percentile of "the best of as many random players as there are settings
  meeting the window minimum" (random trades of the same pool, same trade counts; normal approximation): a setting
  with at least the minimum trades whose mean R is above it beats luck.
* `min_n`: int32 `(W, 2)`: minimum trades for `plateau` (pooled, per coin).
* `bounds_ms`: int64 `(W, 2)`: window start / end.
* `generated_ms`: int64 scalar.

Derived in the dashboard: win rate = wins / n; break-even win rate = avg_loss / (avg_win + avg_loss); cost =
mean_G - mean_R.

### `past5y_<S>_<tf>.npz` (static, shipped in `demobot/data/`, built from the 5-year study)
* `stats`: float32 `(P, E, S, C, 3)` with P = periods `["2020", "2021-23", "2024-26", "2020-03", "2022-05",
  "2022-11"]` (the last three: the COVID, LUNA and FTX crash months), stats `n`, `win_rate`, `mean_R` (net, house
  costs). Crash months may be NaN for an exit that was not computed.

## 5. Telegram (engine queues, `demobot.notify` formats and sends)

`notify.Outbox(conn)` (conn = sqlite3 connection to demo.db; the class creates its table `outbox` if missing):
`queue(kind: str, payload: dict) -> None`, `flush(token: str, chat: str, limit: int = 20) -> int` (sends
the oldest unsent rows, plain text, at most 1 message per second, marks sent / error, returns the number sent;
never raises on network errors). `render(kind, payload) -> str` (Korean text; pure function, tested).

Kinds and payload fields:

* `start`: `{"phase": "warm|live", "accounts": 48, "live_start_ms": int}`
* `tick`: `{"bar_ms": int, "opens": [T], "closes": [T]}` one bundled message per tick, only when something
  opened or closed in the `adaptive`, `friend` or `fixed/friend` accounts (the others are on the dashboard).
  T = `{"account": id, "name": str, "coin": "BTCUSD", "side": 1, "entry": float, "exit": float|null,
  "reason": str|null, "setting_ko": str, "exit_ko": str, "pnl_by_L": {"20": float, ...}|null,
  "R": float|null}` (one T per account trade; the leverage lines share entries).
* `switch`: `{"account": id, "name": str, "items": [{"coin": "ALL|BTCUSD", "L": int|null, "from_ko": str,
  "to_ko": str, "why_ko": str}]}`
* `daily`: `{"day": "2026-10-10", "live_days": float, "best": [...], "worst": [...], "by_kind": [...],
  "passed": int, "leaders": [...], "trades_24h": int}` sent 09:00 KST.
* `warn`: `{"what": "data|stalled|error|disk", "detail_ko": str}` (at most one per what per hour).
* `pass`: `{"account": id, "name": str, "L": int, "checks": [...]}` the first time an account passes "ours".

## 6. Rules both sides keep

* No order code, no exchange key, no paperbot path. Market data: `https://fapi.binance.com` public endpoints only.
* Text from the server is text in the page (DOM text nodes, never innerHTML), as in the rule bot's v4 tests.
* Private reference materials never enter this code or the repo.

## 7. Additions of 10/09 evening (owners: "넣을 수 있는 건 최대한 다 넣어서 돌리자")

### 7.1 Exit 14: half at 1R, stop to break-even, rest at 1.5R
`grid.EXITS` gains index 13 `half1R_be_1.5R` (Korean "반익반본: 1R 절반 · 본전 · 1.5R"; stop 2 x ATR14). Every exit array
dimension E becomes 14 (`rank_*.npz` stats/luck95, `past5y_*.npz` padded with NaN for the new exit, the friend rule's
candidates). Use `grid.NEXIT` / `grid.EXITS` / `grid.exit_ko(i)`; never hard-code 13.

### 7.2 Private strategy plug-ins (kind `private`)
The engine loads optional plug-in modules from `DEMOBOT_PLUGINS` (default `/etc/demobot/plugins`, root-owned,
read-only for the services). The public repository never contains a plug-in, its name or its rules. Each plug-in
adds accounts with `kind: "private"`, `sub: <plug-in key>`, ids `pv-<key>-<variant>` and its own Korean `name` /
`rule_ko`, four leverage lines like every account, the same owners' sizing and entry checks. In `accounts.json` and
`acct/<id>.json` they look like any account (their trades have `exit_ko` / `setting_ko` from the plug-in). Kind label
in the UI: "비공개 매매법". Judgment reference: the coin-flip account of the plug-in's timeframe.

### 7.3 View log ("관점 기록장")
Owners type a view into the demo lab Telegram group in one line; the engine records it, follows the market and
scores it. Only the group `DEMOBOT_TG_CHAT` is accepted (the bot needs privacy mode off: BotFather /setprivacy ->
Disable, or the bot as group admin).

Commands (Korean, one line):
* `관점 [MM/DD HH:MM] <COIN> <롱|숏> [A <x[-y]>] [B <x[-y]>] [C <x[-y]>] [손절 <x>] [목표 <x>[,<y>]] [메모 <text>]`
  numbers may have commas; ranges `x-y` or `x~y`; coin BTC/ETH/SOL/DOGE/LTC/BCH/XRP (with or without USDT); the time
  is KST and defaults to the message time. At least one zone is required.
* `취소 <id>` (cancel a view), `관점목록` (last 10), `관점도움` (usage).

Scoring (fixed before the first view, `demobot/views.py`):
* reference price = open of the first 15m bar after the view time; direction move (%) in the stated direction at
  +4h / +24h / +48h (15m closes); hit = move > 0.
* reached = a 15m bar touches the nearest zone edge within 48 h.
* follow "touch": a limit at the nearest zone edge (long: the zone's top; short: its bottom), maker entry;
  follow "confirm": after a touch, the first 15m close back on the trade side of that edge (long: close above the
  zone top), taker entry at that close. Both: stop = the given stop, else 0.3% beyond the farthest zone; targets =
  the given ones (first = half, second = rest), else half at 1R, stop to entry, rest at 2R; time cap 48 h after the
  entry; costs taker 0.05% + slippage 0.02% (maker 0.02% for limit fills); result in R and as % of the wallet at
  20x with the owners' rule. A view not entered within 48 h is "missed".
* verdict: below 30 finished views "표본 부족 (n/30)"; from 30: direction hit rate vs 50% (binomial one-sided
  p < 0.05) and each follow mode's mean R > 0 with the week-block bootstrap lower bound > 0.

Snapshot `views.json`:
```json
{"generated_ms": 0, "rules_ko": ["..."],
 "summary": {"n": 0, "n_done": 0, "need": 30, "verdict_ko": "표본 부족 (0/30)",
             "dir": {"4h": {"n": 0, "hit": 0, "rate": null, "p": null}, "24h": {}, "48h": {}},
             "reached_rate": null,
             "follow": {"touch": {"n": 0, "entered": 0, "mean_R": null, "win_rate": null, "sum_R": 0.0, "ci_low": null,
                                  "wallet20_pct": 0.0},
                        "confirm": {}}},
 "views": [{"id": 1, "t_ms": 0, "entered_ms": 0, "coin": "BTCUSD", "side": -1,
            "zones": {"A": null, "B": [84750.0, 84840.0], "C": [85300.0, 85300.0]}, "stop": 85600.0,
            "targets": [], "memo": "", "status": "watching|done|cancelled", "ref_price": 0.0,
            "dir": {"4h": null, "24h": null, "48h": null}, "reached": null, "reached_ms": null,
            "follow": {"touch": {"status": "waiting|open|closed|missed", "entry_ms": null, "entry": null,
                                 "stop": null, "exit_ms": null, "R": null, "wallet20_pct": null, "legs_ko": ""},
                       "confirm": {}}}]}
```
`views` newest first, at most 300.

Telegram kinds (engine queues, `notify.render` formats):
* `view_ack`: `{"id", "coin", "side", "t_ms", "zones", "stop", "targets", "memo", "notes_ko": [str]}` (reply to a
  recorded view; notes = assumptions the parser made, e.g. "시각 없음: 받은 시각 10/10 14:03 사용").
* `view_err`: `{"text_ko": str}` (why a line was not understood, plus the usage example).
* `view_cancel`: `{"id", "ok": bool}`.
* `view_list`: `{"views": [{"id", "t_ms", "coin", "side", "status", "dir24": pct|null, "touch_R": R|null}]}`.
* `view_help`: `{}`.
* `view_done`: `{"id", "coin", "side", "dir": {"4h", "24h", "48h"}, "reached": bool, "touch": {...}, "confirm": {...},
  "summary_ko": str}` (once, 48 h after the view or when both follow modes have closed).
`notify.poll_commands(token, chat, offset, timeout=25, get=None) -> (new_offset, [{"update_id", "text", "date_ms",
"from_name"}])`: Telegram getUpdates, only messages of `chat`, never raises (returns the old offset and [] on errors),
token redacted from errors.

## 8. Additions of 10/09 night, round 3 (owners: "2번 시작해주고 대시보드 ... 모두 추가")

Everything below is additive: a missing field or file means "준비 중" / "기록 없음" (older engine, or not enough data
yet). Numbers keep the units of section 4 (`pnl_pct` percent, `max_dd` / `win_rate` / shares 0..1 ratios, `bps` =
1/100 of a percent). The dashboard stays read-only.

### 8.1 Confirmation period after a pass ("확인 기간")
A line (account x leverage) that passes "우리 기준" for the first time starts a confirmation: from that tick (`start_ms`)
only the trades **entered at/after `start_ms`** count. It ends at `start_ms + 28 days` when the window holds >= 20
closed trades, otherwise when it reaches 20 closed trades, at the latest at `start_ms + 56 days`. Result `confirmed`
when all of: >= 20 closed trades, mean R > 0, window P&L > 0, window max drawdown < 30%, no ruin and no liquidation
in the window. Otherwise `failed` (with `why_ko`). A `failed` line can start a new confirmation the next time it
passes. `confirmed` = "실전 후보" (the owners still decide; real money stays forbidden until they do). Stored in the
DB table `passes` (history kept; restarts do not reset it).

`judge.json` gains:
```json
{"lines_judged": 224,
 "multi_note_ko": "224줄을 한꺼번에 보면 실력이 없어도 몇 줄은 운으로 통과할 수 있어서, 통과 뒤 4주 확인 기간을 둡니다",
 "confirm": [{"id": "fx-def-S2-15m", "name": "...", "L": 20, "status": "confirming|confirmed|failed",
              "start_ms": 0, "end_ms": 0, "min_end_ms": 0, "max_end_ms": 0, "decided_ms": null,
              "progress": 0.0, "n": 0, "need_n": 20, "mean_R": null, "pnl": 0.0, "pnl_pct": 0.0, "max_dd": 0.0,
              "liqs": 0, "ruins": 0, "why_ko": "..."}],
 "candidates": [{"id": "...", "name": "...", "L": 20, "decided_ms": 0, "window": {"n": 0, "mean_R": 0.0,
                 "pnl_pct": 0.0, "max_dd": 0.0}, "costs": {"entry_bps": null, "roundtrip_pct_of_pnl": null},
                 "stops": {"pnl_pct": 0.0, "max_dd": 0.0}}]}
```
`progress` = 0..1 (time and trades, whichever is further behind). Each `rows[]` item gains `"confirm": {"status": ...,
"start_ms": ..., "end_ms": ...} | null` (the line's latest confirmation). `verdict_ko` mentions candidates first.
`home.json` `totals` gains `confirming`, `candidates`.

Telegram: `pass` payload gains `"confirm_end_ms": int` (the earliest end). New kind `confirm_done`:
`{"account": id, "name": str, "L": int, "result": "confirmed|failed", "start_ms": int, "decided_ms": int,
"window": {"n": int, "mean_R": float|null, "pnl": float, "pnl_pct": float, "max_dd": float}, "why_ko": str}`.

### 8.2 Stop-rule lines ("정지 규칙")
Every account line is also simulated with the real-money stop rules (same entries, same sizing; the rules only block
NEW entries, open positions run to their own exits):
* account stop: realized wallet <= 80% of the $1,000 start -> no new entries ever again (`halted_ms`);
* day stop: realized P&L of the KST day <= -5% of the wallet at the day's first event -> no new entries until the
  next KST day 00:00;
* losing streak: 5 closed losing trades in a row -> no new entries for 24 h after the 5th loss's close (streak resets).

`accounts.json` each line gains `"stops": {"equity": 0.0, "pnl": 0.0, "pnl_pct": 0.0, "max_dd": 0.0, "trades": 0,
"mean_R": null, "blocked": 0, "halted_ms": null, "day_pauses": 0, "streak_pauses": 0}`. `acct/<id>.json` gains
`"curves_stops": {"20": [[t, v]], ...}` (same downsampling) and `"stop_events": [{"t_ms": 0, "L": 20,
"what": "halt|day|streak", "until_ms": 0|null, "wallet": 0.0}]` (newest first, at most 200).
`judge.json` rows gain `"stops": {"pnl_pct": 0.0, "max_dd": 0.0, "ours_pass": bool}` ("우리 기준" on the stop line).
Rule text for the UI: `judge.json` `stop_rules_ko`: ["계좌 -20%: 새 진입 영구 정지", "하루 -5%: 그날 새 진입 정지",
"5연패: 24시간 새 진입 쉼"].

### 8.3 Real costs from the order book ("미끄러짐 기록")
Each tick (just after the new bars, about 25-40 s after the 15m open, when a real bot would send its order) the
engine reads the Binance order book (`/fapi/v1/depth`, 500 levels) of the 7 coins and stores per coin the cost of a
market order of each size `SIZES = [500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000]` USD:
`cost_bps` = (VWAP - mid) / mid x 10,000 in the order's adverse direction (includes half the spread), for buys and
sells; `null` when the 500 levels did not cover the size. DB table `depth` (kept; backed up).

The engine's assumed cost per side is 2 bps of slippage on the bar open (plus the taker fee, which is real and not
part of this). For every live trade whose entry bar has a book (entry at a 15m open after logging began), the
measured entry cost at the trade's notional (`qty x fill`, linear between sizes) is compared with the assumption:
`extra_bps` = measured cost_bps - 2. The exit is assumed to cost the same (`roundtrip`). Maker (limit) entries of the
private plug-ins are not book-priced; instead their fill bar is checked: `through_bps` = how far the bar traded
beyond the limit (long: (limit - low) / limit x 10,000). `touch_only` = through_bps < 1 (a limit that was only
touched may not have filled).

Snapshot `costs.json`:
```json
{"generated_ms": 0, "since_ms": 0, "assumed_bps": 2.0, "sizes": [500, 1000],
 "coins": [{"coin": "BTCUSD", "n": 0, "last_ms": 0, "spread_bps": {"last": 0.0, "median": 0.0},
            "buy_bps": {"median": [0.0], "p90": [0.0], "last": [0.0]},
            "sell_bps": {"median": [0.0], "p90": [0.0], "last": [0.0]}}],
 "series": [{"coin": "BTCUSD", "points": [[0, 0.0, 0.0]]}],
 "lines": [{"id": "...", "name": "...", "L": 20, "n": 0, "mean_extra_bps": null, "mean_extra_R": null,
            "pnl": 0.0, "pnl_adj": 0.0, "pnl_adj_pct": 0.0}],
 "maker": [{"id": "pv-...", "name": "...", "L": 20, "n": 0, "touch_only": 0, "touch_share": null, "pnl": 0.0,
            "pnl_strict": 0.0}],
 "notes_ko": ["..."]}
```
`series` points: `[t_ms, spread_bps, buy_bps at 10,000 USD]`, at most 800 per coin (downsampled). `lines`: one row per
account line with >= 1 measured trade; `pnl_adj` = P&L minus the measured extra round-trip cost; `pnl_strict` =
P&L without the touch-only fills. `acct/<id>.json` trades gain `"cost_bps": float|null` (measured entry cost) and
`"through_bps": float|null` (maker entries).

### 8.4 P&L breakdown
Each line in `accounts.json` gains `"parts": {"gross": 0.0, "fees": 0.0, "funding": 0.0, "open": 0.0}` with
pnl = gross - fees + funding + open: gross / fees / funding over the CLOSED trades (`funding` signed: positive =
received), `open` = the unrealized P&L of open positions. `fees` = taker/maker fees plus the assumed 2 bps slippage
per side. Trades gain `"fee": float` and `"notional": float`; a trade's `"funding"` is the funding of the whole hold
(signed, + = received; 0 while open).

### 8.5 Market regime ("시장 국면")
Per coin and 15m bar, from closed bars only: trend from 4h bars (built from 15m): EMA50 slope over the last 6
4h bars divided by the 4h ATR14: `up` > +0.5, `down` < -0.5, else `range`. Volatility: 15m ATR14 / close against
its own last 90 days: `high` above the 70th percentile, `low` below the 30th, else `normal`. Labels: up "상승 추세",
down "하락 추세", range "횡보", high "변동 큼", normal "보통", low "변동 작음".

Snapshot `regime.json`:
```json
{"generated_ms": 0,
 "now": [{"coin": "BTCUSD", "trend": "up", "vol": "normal", "slope": 0.0, "atr_pct": 0.0, "since_ms": 0}],
 "history": [{"coin": "BTCUSD", "points": [[0, "up", "normal"]]}],
 "lines": [{"id": "...", "name": "...", "L": 20,
            "trend": {"up": {"n": 0, "mean_R": null, "pnl": 0.0}, "down": {}, "range": {}},
            "vol": {"high": {}, "normal": {}, "low": {}}}]}
```
`history` points: one per change (regime start), live period plus 7 days. Trades in `acct/<id>.json` gain
`"trend": "up|down|range|null"`, `"vol": "high|normal|low|null"` (at entry).

### 8.6 Bars for trade charts
`snap/bars/<COIN>.npz` (one per coin, rewritten each tick): `ts` int64 (15m open ms), `o`, `h`, `l`, `c` float64,
15m bars from `live_start - 7 days`. The dashboard builds 30m bars by pairing (hh:00+hh:15, hh:30+hh:45) and draws a
trade with its entry, stop and exit; for `exit_ko` of a fixed pair "익절 xR · 손절 yATR" the target is
entry + side x x x |entry - stop|.

### 8.7 Goal line (12/31)
`home.json` gains:
```json
{"goal": {"deadline_ms": 0, "days_left": 0, "stage": 0, "stages_ko": ["설치", "데모 진행", "우리 기준 통과",
          "확인 기간", "실전 후보"], "closest": {"id": "...", "name": "...", "L": 20, "ok": 3, "of": 5,
          "missing_ko": ["..."]}, "line_ko": "12/31까지 83일: 데모 진행 중, 가장 가까운 줄 S2 ... (5개 중 3개 통과)"},
 "regime_now": [ ...regime.json now... ], "costs_now": {"median_entry_bps": null, "assumed_bps": 2.0}}
```
`deadline_ms` = 2026-12-31 24:00 KST. `stage` = index of the furthest stage reached by any line.

### 8.8 Backup and outside watch (separate processes; `demobot/backup.py`, `demobot/watch.py`)
* Nightly backup (`demobot-backup.timer`, 04:40 KST = 19:40 UTC): copies only the records that cannot be rebuilt
  from Binance (tables `views`, `decisions`, `passes`, `depth`, `notified`, `meta`, `outbox` last 7 days) into a
  small SQLite file, gzip, optional openssl AES-256 encryption when `DEMOBOT_BACKUP_PASSPHRASE` is set, and sends
  it with Telegram `sendDocument` to `DEMOBOT_BACKUP_CHAT` (default `DEMOBOT_TG_CHAT`). Writes `snap/backup.json`:
  `{"last_ok_ms": 0, "last_try_ms": 0, "bytes": 0, "tables": {"views": 0}, "encrypted": false, "error_ko": null}`.
  `python -m demobot.backup send|restore FILE|now` (restore: service stopped, INSERT OR REPLACE into demo.db).
* Watch (`demobot-watch.timer`, every 10 min): reads `snap/status.json` and systemd state; warns in Telegram
  (`warn` kinds `dead`: no tick for 45 min or demobot-live not active; `rank`: no ranking for 3 h or the last run
  failed; `backup`: no good backup for 36 h), at most one per what per 3 h, and a `warn_clear` when it recovers.
  Writes `snap/watch.json`: `{"checked_ms": 0, "ok": true, "items": [{"what": "dead", "ok": true, "detail_ko": "..."}]}`.
* Dead-man ping: when `DEMOBOT_DEADMAN_URL` is set (a healthchecks.io check), the engine GETs it after every tick
  that processed new bars (timeout 10 s, never raises). If the server stops, healthchecks.io alerts the owners.
* `status.json` gains `"deadman": {"configured": bool, "last_ok_ms": 0|null, "last_error": null}`.
* New env keys (all optional): `DEMOBOT_DEADMAN_URL`, `DEMOBOT_BACKUP_CHAT`, `DEMOBOT_BACKUP_PASSPHRASE`.
* New Telegram kinds: `warn` gains whats `dead|rank|backup`; `warn_clear`: `{"what": str, "detail_ko": str}`;
  `backup` is not a queued kind (the backup process sends its own document with a Korean caption).

### 8.9 Daily summary additions
`daily` payload gains `"confirming": int, "candidates": int, "costs": {"median_entry_bps": float|null,
"assumed_bps": 2.0}, "regime": [{"coin": "BTCUSD", "trend": "up", "vol": "normal"}]`.

### 8.10 Weekly review ("주간 회의록", made by code, no AI, no cost)
`snap/review.json`: the current week so far plus finished weeks (KST Monday 00:00 to Sunday 24:00), newest first, at
most 26. Finished weeks are kept in the DB (meta `reviews`) and backed up.
```json
{"generated_ms": 0,
 "weeks": [{"week_ko": "10/12~10/18", "start_ms": 0, "end_ms": 0, "final": false,
   "numbers": {"trades": 0, "accounts_up": 0, "accounts_down": 0, "best": [{"id": "", "name": "", "L": 20,
               "pnl_pct": 0.0}], "worst": [], "by_kind": [{"kind_ko": "고정", "mean_pnl_pct": 0.0}]},
   "judge": {"passed": 0, "confirming": 0, "candidates": 0, "closer": [{"id": "", "name": "", "L": 20, "ok_from": 2,
             "ok_to": 3}], "further": []},
   "stops": {"saved": [{"id": "", "name": "", "L": 20, "diff_pct": 0.0}], "cost": [], "net_pct": 0.0},
   "costs": {"median_entry_bps": null, "assumed_bps": 2.0, "eaten": [{"id": "", "name": "", "L": 20,
             "share": 0.0}]},
   "regime": [{"coin": "BTCUSD", "trend": "up", "vol": "normal", "share": {"up": 0.0, "down": 0.0, "range": 0.0}}],
   "views": {"n": 0, "done": 0, "dir24_rate": null},
   "decide_ko": ["..."], "summary_ko": ["..."]}]}
```
Week `pnl_pct` / `diff_pct` are the week's P&L as a percent of the $1,000 start (like `pnl_pct` everywhere; a line
that was ruined and restarted can lose more than 100%). `summary_ko`: 3-6 plain sentences (what happened this week). `decide_ko`: what the owners have to decide or check
(empty list = nothing). Telegram kind `weekly`: `{"week": <the finished week object above>}` sent Monday 09:00 KST
for the week that just ended (silent).

### 8.11 Telegram history ("알림 기록")
`snap/telegram.json`: `{"generated_ms": 0, "items": [{"id": 0, "ts_ms": 0, "kind": "tick", "status": "sent|queued|error",
"text": "..."}]}` newest first, at most 300 (the rendered text exactly as sent).

### 8.12 Dashboard-only screens (no new engine data)
* "설정 지도": heatmap of a strategy's settings from `rank_<S>_<tf>.npz` + `/api/grid` (two chosen parameters on the
  axes, the others fixed or averaged; colour = mean_R or plateau; cells below the window minimum greyed).
* "코인별 보기": per coin, every account line's P&L and trades on that coin (from `acct/<id>.json` trades).

### 8.13 The shared server ("서버 같이 쓰기")
The demo lab runs on the rule bot's server. `status.json` gains `"server": {"mem_total_mb": 0.0, "mem_avail_mb": 0.0,
"swap_used_mb": 0.0, "load": [1.0, 1.0, 1.0], "cpus": 4, "rule_bot": [{"unit": "paperbot-live3.service",
"active": "active", "mem_mb": 0.0}]}` (refreshed at most every 5 minutes; any field may be null; `rule_bot` lists
the rule bot's main services that exist). The status screen shows whether the rule bot still has room.
