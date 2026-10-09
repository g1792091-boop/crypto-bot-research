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
