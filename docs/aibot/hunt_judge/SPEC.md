# Hunt judge: AI shadow beside the trend-hunt paper bot (builder spec)

Status: design only, written 2026-10-11 (KST). Nothing is built, installed or called until the owners say "좋아".
Owner-facing summary (Korean): `DESIGN_KO.md` in this folder. All costs are estimates, not measurements.

Sources this spec builds on (read them; do not re-derive what they fix):

| Source | What is taken from it |
|---|---|
| `research/hunt/PREREG_HUNT.md` (DRAFT) | the machine: bars, entries E1-E3, gate G1, fills, first stop, adds, chandelier, intrabar order, portfolio caps, costs (sections 4-9); section 17 (AI only as a forward shadow) |
| `docs/aibot/AIBOT_DESIGN_V3_KO.md` | safety principles (9-1), key handling (9-2), "AI never orders" layers (9-3), failure table (9-4), off/pause (9-5), one writer per DB (2-2), late-signal rule (2-3, 5-1 item 7), screen check (4-5), one locked schema + code-side checks (4-8), zero retries and no fallbacks (4-9), budget ledger / reservation / 95% stop (8-1), lock manifest (7-1) |
| claude-api skill, `/tmp/claude-0/bundled-skills/2.1.296/f14aa290d24f440d46c4d45d14ef7497/claude-api/` (cited below as `skill:<path>`). `skill:SKILL.md` is the skill's main page as served by the Skill tool (it is not extracted to disk); every price used here is also in an on-disk file: `shared/models.md`, `shared/prompt-caching.md`, `shared/model-migration.md`. The 2.1.289 copy named in the task has the same Fable 5.1 / Opus 5.5 prices and cache multipliers (checked) | model ids, prices, caching rules, structured outputs, effort/thinking parameters, SDK call shapes |

Owners (2026-10-11): cost does not matter; they want an AI that judges like a person in real time, entering against the
rule when it looks right and staying out when it does not. First as a recorded shadow, start about 2026-10-20, judged
2026-11-15.

---

## 1. Scope

Three stages, all **shadows** (records only; no orders anywhere; the hunt paper bot never waits for or reads the AI):

| Stage | When | AI output | Judged by |
|---|---|---|---|
| **S1 filter** | every event of the hunt pick (gated **G** and gate-blocked **N**) | TAKE/SKIP, confidence 0-100, reason (<= 2 lines), invalidation | mean R(TAKE) - mean R(SKIP) on G (section 15) |
| **S2 size** | same S1 call | size multiplier 0.5 / 1.0 / 1.5 | sized vs unsized mean R on G |
| **S3 discretionary** | every 4h close (00, 04, ... 20 UTC) | 0-3 own entries on the 30 coins | AI entry R vs same-coin same-time coin-flip R |

Not in scope: exits by the AI, web search, tools, real money, changes to the hunt study or to any other bot, the AI
trader of `AIBOT_DESIGN_V3_KO.md` (separate system, separate workspace and key).

## 2. Architecture (new Vultr instance, section 17)

```
 [hunt-paper]  user hunt      writes /var/lib/hunt/hunt.db        (hunt paper bot; public Binance data only; no keys)
      | hunt.db (read-only, mode=ro)
      v
 [hunt-judge]  user huntai    writes /var/lib/huntai/judge.db     (packets, API calls, answers, ledger; ONLY holder of the Anthropic key)
      | judge.db (ro)                    ^ hunt.db (ro)
      v                                  |
 [hunt-book]   user huntbook  writes /var/lib/huntbook/book.db    (standalone R, coin-flip R, late-fill R, shadow accounts)
 [hunt-eval]   user huntbook  oneshot: weekly rehearsal ("ran/failed" only), looks on 2026-11-15 and 2026-12-27
 [hunt-dash]   user huntdash  read-only GET screens over the three DBs (optional)
```

* One writer per DB; every other process opens it `mode=ro`. The judge never writes hunt.db; the hunt bot never opens
  judge.db or book.db.
* `hunt-judge` units: `After=hunt-paper.service` only (no `Wants`/`Requires`/`BindsTo`), `ProtectSystem=strict`,
  `ReadWritePaths=/var/lib/huntai`, `ReadOnlyPaths=/var/lib/hunt /var/lib/huntbook`, `InaccessiblePaths=/etc/huntjudge`
  after the env is loaded, `NoNewPrivileges=yes`, `MemoryMax=1G`, `OOMScoreAdjust=500`, `Nice=5`, watchdog.
* Key: `/etc/huntjudge/judge.env` (root:huntai 0640), loaded by systemd `EnvironmentFile=`. The process reads
  `ANTHROPIC_API_KEY` once into the client. Logs never contain request or response headers; every log/exception string
  passes `redact()`. Status commands print "set / empty" only. The builder (Claude) builds and tests against a fake API
  server and never receives, prints or asks for the key; the owners place it with `sudoedit` (DESIGN_KO 8, step 9).
* SDK: the official `anthropic` Python SDK (1.x, built on `httpx2`, `skill:python/claude-api/README.md`) in a dedicated
  venv `/opt/huntjudge/venv`. Version pinned and hashed in the lock manifest. (V3 avoided the SDK only to protect the
  rule bot's shared venv; this server has no shared venv.)
* Outbound hosts allowed by the judge: `api.anthropic.com`, `api.telegram.org`. The hunt bot: `fapi.binance.com`,
  `fstream.binance.com`, `data.binance.vision`. No redirects followed.

## 3. Interface required from the hunt paper bot (`hunt.db`)

The judge can only ask about what the hunt bot records. The hunt bot must write, before B+30 s for an event whose
signal bar closes at B:

* `events`: `event_id` (int PK), `system` (e.g. `E1-1h`), `symbol`, `tf`, `side` (LONG/SHORT), `bar_close_ms`,
  `detected_ms`, `entry_values` (json: E1 channel level and volume ratio; E2 bandwidth, its 120-bar percentile, band;
  E3 ATR14/ATR100), `regime_code` (the pick's tf label), `gated` (0/1), `rule_action` (OPENED, BLOCKED_GATE,
  BLOCKED_COIN_BUSY, BLOCKED_CAP, CUT_*, SKIPPED_*), `atr14`, `d0`, `engine_hash`. **Every event of the pick on all 30
  coins, both sides, every class** (not only the ones it opens).
* `bars_5m` (`symbol`, `open_ms`, o, h, l, c, quote_vol) with >= 400 days of history (the 365-day ATR% percentile of
  the gate needs it); `funding` (`symbol`, `calc_ms`, `rate`); `oi` (`symbol`, `ts_ms`, `oi`) at 5m resolution;
  `heartbeat`.
* `universe30.json` and the pick (`pick.json`) from the hunt study, hashed.

`rule_action` and anything about positions are **never** put in a packet (BLOCKED_COIN_BUSY would reveal an open
position).

## 4. Packets

All numbers are formatted deterministically (fixed column order, fixed decimals: prices to 5 significant digits,
ratios to 2 decimals, UTC times `MM-DD HH:MM`), so identical inputs give identical bytes (needed for caching and for
the audit hash). Keys are short English; the system prompt explains them once.

### 4.1 S1 request layout (render order tools -> system -> messages, `skill:shared/prompt-caching.md`)

| Block | Content | Same bytes for | Cache | Tokens (estimate) |
|---|---|---|---|---|
| system `S1-v1` | role; the hunt machine in plain words (entries, gate, D0, adds, one-unit open risk, chandelier, costs); what TAKE/SKIP mean for G and N; confidence and size meaning; packet keys; answer rules (Korean reason, two short lines; invalidation as a close beyond a price); "you see data up to the bar close only and will never be told outcomes". No dates, no names, no versions in the text | every S1 call | breakpoint 1, `{"type": "ephemeral"}` (5 min) | ~3,000 |
| user block A `market` | bar close time; BTCUSDT 1h last 24 rows and 4h last 30 rows; BTC regime labels 1h/4h; breadth line (of the 30: count with 4h close > EMA50; count by regime code on the pick tf) | every S1 call at this bar close | breakpoint 2, 5 min | ~2,500 |
| user block B `signal` | class G/N; system; symbol; side; entry values; last close at B (not P0: P0 is after B); ATR14 (value, %); D0 (price, %); first stop; add levels; chandelier multiple; regime labels of both tfs with components (ADX14, DI+, DI-, EMA50 10-bar slope in ATR, ATR14% percentile in trailing 365 d); ATR14/ATR100; BB bandwidth and its 120-bar percentile; distance to the 55-bar high/low in ATR; funding: last 6 rates and next funding time; OI change 1h/4h/24h %; coin 1h last 72 rows; coin 4h last 60 rows (`t,o,h,l,c,vr`, vr = volume / mean of previous 20 bars); this coin's last 10 events (time, system, side, class; no outcome, no rule_action) | one call | none | ~6,000 |

Measured with `messages.count_tokens` (`skill:shared/token-counting.md`) on the start-gate replay; budget: total <= 14,000
input tokens, block B <= 8,000. Over budget: drop 1h rows to 48, then 4h rows to 40 (fixed order, locked before D0).

### 4.2 S3 request layout

| Block | Content | Tokens (estimate) |
|---|---|---|
| system `S3-v1` | as S1 plus: "propose 0-3 entries outside the rules; each is run by the same machine; code drops coins you already hold and entries over the portfolio limits; an empty list is a valid answer" | ~3,500 |
| user | 4h bar close time; BTC block as S1; breadth; then per coin in `universe30.json` order: summary line (labels 1h/4h, ADX14, DI+/-, EMA50 slope, ATR14 %, ATR14/ATR100, BB bandwidth percentile, distance to 55-bar high/low), 4h last 30 rows, 1h last 12 rows, funding last 3, OI change 4h/24h, last 5 events (no outcome) | ~48,500 |

Budget: total <= 60,000. Over: 1h rows to 8, then 4h rows to 24. No cache benefit (4h gaps); the system block still
carries a breakpoint (harmless).

## 5. Anti-leakage (strict; checked in code before every send)

1. Every series used has `max(bar close) <= B`; funding `calc_ms <= B`; OI `ts_ms <= B`; event rows `bar_close_ms <= B`.
2. Packets are built only from `bars_5m`, `funding`, `oi` and the columns (`event_id`, `system`, `symbol`, `tf`, `side`,
   `bar_close_ms`, `gated`) of `events`. Never from positions, trades, equity, `rule_action`, book.db or past answers.
3. The user blocks are scanned for a locked forbidden-token list (`pnl`, `profit`, `loss`, `equity`, `balance`, `win`,
   `R=`, `손익`, `수익`, `손실`, `잔고`, `승률`, account and model names). The system prompt is excluded from the scan.
4. Every call is a fresh single user turn: no history, no memory tool, no tools, no web search, no Files API.
5. The S1 twin's answer, S1 answers and S3 answers are never shown to any model.
6. A failed check means the call is not sent; the ask is recorded `screen_check` (counts as no answer).
7. No backtest of the AI on archived data, ever: the models may remember 2020-2026 prices (PREREG_HUNT 17). Archived
   packets are used only in the start gate for latency, format, token count and cost; no outcome is computed for them.

## 6. Model calls

### 6.1 Parameters

| Call | Model id | Effort (start of ladder) | max_tokens | Transport | Deadline |
|---|---|---|---|---|---|
| S1 primary | `claude-fable-5-1` | `high` | 16,000 | `client.messages.stream(...)` in a worker thread, `stream.get_final_message()` | logged by B+60 s (answer cut at B+55 s) |
| S1 twin | `claude-opus-5-5` | same as primary (set explicitly: its default is `medium`, `skill:SKILL.md`) | 16,000 | same | same; never delays the primary |
| S3 | `claude-fable-5-1` | `high` | 64,000 (stream, `skill:SKILL.md` Common Pitfalls) | same | logged by B4h+60 s (fallback 300 s, 14.3) |
| warm-up | stage's model | stage's effort | stage's | same | none; one per model and stage at service start (schemas compile once and are cached 24 h, `skill:shared/tool-use-concepts.md`); kind `warm`, excluded |

Common to all calls:

* `thinking={"type": "adaptive", "display": "summarized"}`; thinking cannot be disabled on these models and
  `budget_tokens` is rejected (`skill:SKILL.md` Thinking & Effort). The summary is stored for audit only.
* `output_config={"effort": ..., "format": {"type": "json_schema", "schema": ...}}` (`skill:python/claude-api/tool-use.md`,
  Raw Schema).
* `system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}]`; S1 user content
  `[{"type": "text", "text": A, "cache_control": {"type": "ephemeral"}}, {"type": "text", "text": B}]`.
* Client `anthropic.Anthropic(max_retries=0)`: the SDK otherwise retries 429/5xx twice, which can bill a call several
  times and blows the deadline (`skill:python/claude-api/README.md` Retries; V3 4-9).
* No `temperature`/`top_p`/`top_k` (400 on these models), no tools, no `tool_choice`, no `fallbacks`, no betas, except
  the ladder's last S1 rung (14.3): fast mode = `client.beta.messages...` with `betas=["fast-mode-2026-02-01"]` and
  `speed="fast"` (Claude API only; `skill:SKILL.md` Fast Mode). Switching speed invalidates the cache; irrelevant here.
* **Fallbacks deliberately off.** The skill recommends opting into server-side refusal fallbacks by default; here a
  refused question answered by another model would mix models inside the judged series (same reason as V3 4-9). A
  refusal is a no answer; the twin's answer exists anyway as a separate record. The owners may reverse this before D0.
* Fable 5.1 needs the org's data retention to allow it (30-day retention; a zero-retention org gets
  `400 invalid_request_error`, `skill:shared/model-migration.md` Data retention requirement). Seen at the start gate ->
  Opus 5.5 becomes the S1 primary and S3 model (14.3).

### 6.2 Fan-out at one bar close (cache)

A cache entry becomes readable only after the first response begins streaming; parallel identical prefixes all pay the
write (`skill:shared/prompt-caching.md` Concurrent-request timing). Per model and bar close: the first ask is the
**leader**; the others start at the leader's first stream event or 2.0 s after it was sent, whichever is first. The
primary and twin series run independently (caches are per model). The keep-alive (`max_tokens: 0`) trick is not used:
it is rejected together with `output_config.format` (`skill:shared/prompt-caching.md` Pre-warming). Expected saving of
caching at this cadence is about 1% of the bill (section 19); it is kept because it costs nothing.

### 6.3 Output schemas (one per stage, locked; `additionalProperties: false` everywhere)

Structured outputs do not support `minimum`/`maximum`, `minLength`/`maxLength` or array-length limits
(`skill:shared/tool-use-concepts.md` JSON Schema Limitations); those are enforced in code (6.4).

S1 (`S1-schema-v1`):

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["decision", "confidence", "size", "basis", "reason", "invalidation"],
  "properties": {
    "decision": {"type": "string", "enum": ["TAKE", "SKIP"]},
    "confidence": {"type": "integer"},
    "size": {"type": "string", "enum": ["0.5", "1.0", "1.5"]},
    "basis": {"type": "string", "enum": ["trend_strength", "breakout_quality", "volatility", "btc_context",
                                          "funding_oi", "extended_move", "structure", "other"]},
    "reason": {"type": "string"},
    "invalidation": {
      "type": "object",
      "additionalProperties": false,
      "required": ["kind", "timeframe", "price", "note"],
      "properties": {
        "kind": {"type": "string", "enum": ["close_below", "close_above", "none"]},
        "timeframe": {"type": "string", "enum": ["1h", "4h"]},
        "price": {"type": "number"},
        "note": {"type": "string"}
      }
    }
  }
}
```

S3 (`S3-schema-v1`): `{"entries": [...], "market_note": string}`, each entry
`{"coin": enum(the 30 symbols of universe30.json), "side": enum(LONG, SHORT), "confidence": integer,
"size": enum("0.5","1.0","1.5"), "reason": string, "invalidation": <same object as S1>}`; both top-level fields required.

Meaning (stated in the system prompt): `confidence` = how sure the AI is that its decision is right (0 = coin toss,
100 = certain); `size` = the multiplier it would use if the trade is taken (asked for TAKE and SKIP alike, so S2 can be
measured on all G); `invalidation` = the close that would show the idea wrong (for SKIP: the close that would have made
it a TAKE).

### 6.4 Validation order and no-answer codes (first failure wins; the whole answer is discarded; never re-asked)

| # | Check | Code |
|---|---|---|
| 1 | judge picked the event up by B+35 s (V3 late-signal rule, shortened for the 60 s window) | `late_pickup` (not asked) |
| 2 | screen check (section 5) | `screen_check` (not sent) |
| 3 | budget reservation (section 12) | `budget` (not sent) |
| 4 | circuit breaker closed (section 13) | `circuit_open` (not sent) |
| 5 | final message received by the answer cut | `late` |
| 6 | HTTP / transport | `http_429`, `http_5xx`, `http_529`, `network`, `auth`, `billing`, `not_found` |
| 7 | `stop_reason == "end_turn"` | `refusal:<stop_details.category>`, `max_tokens` |
| 8 | `response.model ==` locked id | `model_mismatch` |
| 9 | first text block parses as JSON and matches the schema | `schema` |
| 10 | every `confidence` an integer in 0..100; every `price > 0` unless `kind == "none"` | `range` |
| 11 | logged (row committed) by the deadline | `late` |

Not failures (recorded as flags): reason cut to 2 lines / 160 chars, note to 100 chars; invalidation on the "wrong"
side for the decision; S3 entries beyond 3 (kept: first 3 in answer order; rest `over_limit`); an S3 coin named
twice in one answer (first kept; later copy `dup_answer`).

A late answer that still arrives is read to the end (until B+180 s) only to record usage, cost and its content
(`late_answer`, never used in any statistic).

Error classes are caught most-specific first (`skill:shared/error-codes.md`): 401/403 and 402 (`billing_error`) and 404
stop **all** calls until restart (CRITICAL); 429, 5xx, 529, connection and timeout errors are a no answer for that ask.

## 7. Timing

S1 (1h example; 4h identical at 4h closes):

| Time | Step |
|---|---|
| B | signal bar closes. The hunt bot fills its own accounts at the 5m open at B (rule; never waits) |
| B+1..6 s | hunt bot writes the event |
| B+6..8 s | judge sees it (polls `events` every 0.25 s), builds packets, sends primary and twin |
| B+55 s | answer cut |
| **B+60 s** | logged or `late` |

S3: same at each 4h close; deadline B+60 s; fallback 300 s only by the ladder rule (14.3), reported as "slow S3".

The clock is `chrony`-synced; offset > 1 s WARN, > 5 s stops new asks (`clock`). Restarts of the judge avoid
B-60 s..B+120 s around every hour (max wait 3 min) unless `--now`.

## 8. Outcomes (`hunt-book`)

* **Standalone R** of an event: one position from that signal alone, run by the pinned hunt code's position functions
  (PREREG_HUNT 7.1-7.6 and 9: fill at P0 = open of the first 5m bar after B, slippage and taker, D0, three adds with the
  one-unit stop move, chandelier, intrabar order, funding), wallet $5,000, r = 0.5% (U = $25), **no section-8 portfolio
  caps**, per-position liquidity and margin cuts as in 7.2-7.3. R = net P&L / U. Imported read-only; the judge never
  re-implements the machine. Its own side: `R`; for S3 also the opposite side.
* **Marking** at a look cutoff: last 5m close before the cutoff minus exit taker + slippage; status `marked`.
* **Late-fill shadow** (read only): same signal entered at the open of the first 5m bar with open time >= logged_at.
* **S3 entries**: fill at the open of the first 5m bar with open time >= logged_at; D0 from the last completed bar of
  the pick's timeframe at the 4h close; everything else as the pick's machine. Per proposal: `R_ai`, `R_long`,
  `R_short` (standalone, same fill time, same D0).
* Hourly incremental computation; nightly full recompute must match within 1e-9, else WARN and the nightly value wins.
* **Shadow accounts** (section-8 portfolio rules, $5,000, r = 0.5%, reported as reads, never as the test):
  `AI_FILTER` (G and TAKE; G and no answer -> rule, i.e. enter), `AI_FILTER_SIZED` (same with m x U),
  `AI_FILTER_OVR` (`AI_FILTER` + N and TAKE), `AI_DISC` (S3 proposals kept after caps, 1x), `AI_DISC_SIZED` (read),
  `FLIP_DISC_s` for s = 1..100 (AI_DISC's coins and fill times, side by seeded coin), `RANDCOIN_DISC_s` for s = 1..100
  (AI_DISC's fill times, coin uniform over the 30 not held, side by coin; read), `RULE_REPLAY` (the hunt rule rebuilt
  from `events`; must match the hunt bot's own positions: parity check).

## 9. S3 account rules

* One scan per 4h close. Kept proposals (<= 3, answer order) enter `AI_DISC` unless the coin is already held (`held`),
  a section-8 cap blocks it (`cap`), or a cut applies (`cut_*`). Dropped proposals keep their standalone R (the test
  uses every valid proposal, 15.5).
* Exits only by code (chandelier, stop). The AI never manages or closes a position in v1.
* The AI is not shown what `AI_DISC` holds (section 5).

## 10. Audit log

`judge.db` (writer: hunt-judge):

| Table | Columns (summary) |
|---|---|
| `asks` | ask_id, stage (S1, S3, warm, replay, rehearsal), event_id or scan_close_ms, class, symbol, side, bar_close_ms, picked_ms, deadline_ms, packet_sha256, market_sha256, system_version, schema_version, status |
| `packets` | sha256 PK, stage, compressed text, counted_tokens (start gate), created_ms (each distinct packet once) |
| `calls` | call_id, ask_id, model, role (primary, twin), effort, state (`sending` committed **before** the request so a restart never bills one ask twice), sent_ms, first_event_ms, done_ms, http_status, error_kind, stop_reason, refusal_category, request_id, response_model, usage (input, cache_write_5m, cache_write_1h, cache_read, output), cost_usd, cost_basis (usage, estimate), price_table_version |
| `answers` | call_id, valid, fail_code, raw_json, decision, confidence, size, basis, reason, inv_kind, inv_tf, inv_price, inv_note, flags, thinking_summary, logged_ms, late |
| `s3_proposals` | call_id, rank, coin, side, confidence, size, reason, invalidation, kept, drop_code |
| `events_log` | ts, kind (start, stop, pause, resume, circuit, budget, ladder_lock, lock_check, config), detail |
| `spend` | utc_day, utc_month, stage, model, usd, reservations |
| `tg_outbox` | queued Telegram lines (sending never blocks a decision) |

`book.db` (writer: hunt-book): `outcomes` (event_id, side, R, status, exit_ms, adds, fees, funding, engine_hash,
computed_ms), `s3_outcomes` (proposal_id, R_ai, R_long, R_short, R_late), `accounts`, `positions`, `trades`, `equity`,
`parity`. View `v_decision` joins ask, primary and twin answers, outcomes and codes in one row per ask.

Retention: nothing deleted before 2027-03-31. Nightly `VACUUM INTO` backups (14 days), off-site copy to the owners'
Telegram backup chat (as `docs/offsite-backup.md`), Vultr automatic backups on. Keys and env files are never backed up.
A nightly `secrets-check` counts key-shaped strings in journals, DBs and backups; must be 0.

## 11. Locks and changes

`LOCK_MANIFEST.json` (sha256 of): system prompts S1-v1/S3-v1, schemas, packet builder, screen check and forbidden list,
validation, ladder result, price table, book code and the hunt code it imports, eval code, `universe30.json`,
`pick.json`, SDK version, this file's section 15. `PREREG_JUDGE.md` = section 15 copied verbatim, pinned before D0
(commit, tag `prereg-hunt-judge-v1`, hashes to the owners' Telegram, D0 row in `events_log`). After D0 nothing in the
manifest changes. A bug fix in book or eval code is listed in an addendum, and every number is recomputed from the raw
answers (no model is asked again). A changed prompt, packet, schema, model or effort is a **v2** with a new D0 and
its own pre-registration.

## 12. Budget, caps and ledger

Prices (USD per million tokens; base input / output / cache read; cache write 1.25x base input for 5-minute entries,
2x for 1-hour):

| Model | Input | Output | Cache read | Source |
|---|---|---|---|---|
| `claude-fable-5-1` | 10.00 | 50.00 | 0.25 | `skill:SKILL.md` (Current Models table); `skill:shared/models.md` (Fable 5.1 description); `skill:shared/prompt-caching.md` (Economics: 0.025x) |
| `claude-opus-5-5` | 4.00 | 20.00 | 0.20 | `skill:SKILL.md`; `skill:shared/models.md`; `skill:shared/prompt-caching.md` (0.05x) |
| `claude-opus-5-5` fast mode (ladder only) | 8.00 | 40.00 | – | `skill:SKILL.md` (Fast Mode); `skill:shared/model-migration.md` (Migrating to Claude Opus 5.5) |
| cache write multipliers | 1.25x (5 min), 2x (1 h) | | | `skill:shared/prompt-caching.md` (Economics) |

Prices sit in an env-overridable, versioned table; owners re-check them in the console before D0.

* Ledger per call: `usd = (input*in + w5m*1.25*in + w1h*2*in + read*rd + output*out) / 1e6` from `response.usage`
  (`cache_creation.ephemeral_5m_input_tokens` / `ephemeral_1h_input_tokens`, `skill:shared/prompt-caching.md`). No usage
  (timeout, cut connection): conservative estimate = packet tokens at full input price + max_tokens at output price,
  `cost_basis = estimate`.
* Reservation before send: worst case (S1 Fable 11,500 x $10 + 16,000 x $50 = $0.92; S3 52,000 x $10 + 64,000 x $50 =
  $3.72). Not sent (`budget`) if month spend + open reservations + this > 95% of the monthly cap, or day spend + this >
  daily cap.
* Caps (owners may change before D0): console workspace `hunt-judge` monthly limit **$700**; code: stop all calls at
  95% ($665), daily **$45**. Month and day boundaries are UTC (09:00 KST), as V3 8-1.
* Shedding order when projected month-end > 95%: S1 twin first; then nothing else is shed before the 95% stop.
* Workspace limit (HTTP 400 "workspace API usage limits") or org limit (HTTP 429 `enforced_spend_limit_reached`) =
  `BUDGET_STOP` for all calls, CRITICAL (V3 8-1 item 5). Weekly, the owners compare console usage with the ledger
  (start gate +-5%, live +-10%).

## 13. Failure handling (from V3 9-4; the hunt bot is never affected)

| Failure | Automatic | People |
|---|---|---|
| API 5xx/529/network | that ask: no answer. Circuit breaker: 10 consecutive primary failures, or >= 50% of the last 40 in 10 min -> open; probe with the next real ask after 120 s, then 300 s, 600 s; WARN on open, INFO on close | none unless > 1 h |
| slow (`late`) | no answer, cost booked; > 10% late in an hour -> twin paused for the next hour (primary unchanged) | > 6 h: check |
| 429 rate limit | no answer, no retry; twin paused for `retry-after` | > 2%/day: check limits |
| schema / range | no answer; >= 20% of the last 50 -> that stage paused 30 min + CRITICAL | builder checks; prompts are locked |
| refusal | no answer (`refusal:<category>`), no fallback model | > 1%/day: check categories |
| 401/403/402/404 | CRITICAL once, all calls stop until restart | owners: key, credit, model |
| budget stop | all calls stop; resumes next UTC month | owners only raise caps |
| double start | flock + DB lease (10 s renew, 60 s expiry); second instance exits 2; `sending` row prevents double billing | none |
| reboot | units start; in-flight asks become `service_down` | `status` once |
| hunt bot late or down | events seen after B+35 s are `late_pickup`; missing events found by the nightly replay are `missed` | none |
| data stale (no new 5m bar for 3 min), disk < 15%, clock > 5 s | no new asks | fix and resume |
| Telegram down | outbox queues; decisions never wait | none |

Off / pause (one line each): `huntjudge.sh pause` (file flag: no new calls within 1 s, book keeps computing),
`resume`, `off` (`systemctl disable --now hunt-judge`), console key disable when the server is unreachable.
Pauses are for operational reasons only and are written with a reason; their total counts toward invalidity (15.6).

## 14. Start gate (before D0) and the ladder lock

14.1 **Replay** (operational only; no outcome is computed or looked at; no prompt change may be based on outcomes):
the most recent 200 events of the pick (G and N mixed) up to 2026-10-15 rebuilt as packets from the archive, sent to
both models at the current ladder rung with a simulated B; then 30 S3 scans. Measured: end-to-end time B -> logged,
schema-valid share, refusal share, `count_tokens` and usage tokens, cost per call. Budget cap for the gate: $150.

14.2 **Rehearsal**: 24 h live on the new server with real events (stage `rehearsal`, excluded from every statistic).

14.3 **Ladder** (fixed now; decided by speed and format only):
S1 rungs: Fable 5.1 high -> Fable 5.1 medium -> Opus 5.5 high -> Opus 5.5 medium -> Opus 5.5 medium with fast mode.
The first rung with p95(B -> logged) <= 45 s, late <= 2%, schema-valid >= 99% and refusals <= 1% is locked; the twin is
the other model at the same effort (Opus 5.5 high when Fable is primary). If no rung passes, the last rung is used and
the gap is reported. S3 rungs: Fable 5.1 high -> medium -> low -> Opus 5.5 medium; criterion p95 <= 50 s and late <= 5%;
if none passes, S3 uses the first rung with p95 <= 240 s and a 300 s deadline, labelled "slow S3" in every report.
A Fable `400 invalid_request_error` caused by data retention skips all Fable rungs.

14.4 **Gate checks** (all): rung locked; schema-valid >= 99%; secrets-check = 0; `RULE_REPLAY` parity with the hunt bot
on the rehearsal day; clock offset < 1 s; ledger vs console within +-5% for the replay; restore drill of the morning
backup reproduces the day's outcomes. Failing a check delays D0 by a day; no gate number is changed to pass.

14.5 **Pin** (section 11), then D0 = the first full UTC hour after the pin. The hunt bot starts on its own schedule and
never waits for the judge.

## 15. Pre-registered evaluation (copied verbatim into `PREREG_JUDGE.md` and pinned before D0)

15.1 **Definitions.**
* D0: as 14.5. Block anchor A = D0 floored to 00:00 UTC.
* Looks: **L1 cutoff 2026-11-15 00:00 UTC (09:00 KST)**; **L2 cutoff 2026-12-27 00:00 UTC**. A look uses items whose
  signal bar (S3: scan bar) closed in [D0, cutoff - 24 h). Open positions are marked at the cutoff (section 8).
* Week blocks: block(i) = floor((bar_close_i - A) / 7 days); a last block shorter than 3 days merges into the previous.
* R: standalone net R (section 8). For S3: `R_ai`, `R_long`, `R_short`.
* Valid answer: a primary answer passing 6.4 (codes 1-11). Twin answers never enter a decision.
* G_valid: S1 asks of class G with a valid answer. T = TAKE in G_valid, S = SKIP in G_valid. N_valid and O = TAKE in
  N_valid likewise. E = valid S3 proposals (<= 3 per scan, including those dropped by `held`/`cap`/`cut`).
* Seeds: `int.from_bytes(sha256(f"hunt_judge|{stage}|{look}|{kind}").digest()[:8], "big")`, numpy PCG64.
* Bootstrap: resample the eligible blocks (blocks holding >= 1 item of the set) with replacement, same count,
  B = 10,000; statistic on the pooled items; a resample where the statistic is undefined counts as <= 0.
  One-sided p = (1 + #{stat* <= 0}) / 10,001 (the PREREG_HUNT 13 form).
* alpha per stage per look = **0.025** one-sided (two looks: <= 0.05 per stage).

15.2 **S1 filter.** Delta1 = mean_T(R) - mean_S(R). p_boot as 15.1. p_perm: within each block permute the TAKE/SKIP
labels among that block's G_valid items (counts kept), 10,000 times; p_perm = (1 + #{Delta1_perm >= Delta1}) / 10,001.
**S1 PASS** = minimum counts (15.6) and Delta1 > 0 and p_boot < 0.025 and p_perm < 0.025 and sum_S(R) < 0 and
mean_T(R) > 0 and operational validity (15.6). Baseline reported beside it: mean and sum of R over all G (the rule),
over G_valid, and over the G asks without a valid answer.

15.3 **S1-N overrides** (tested only at a look where S1 PASSES, fixed sequence, no extra alpha):
**PASS** = |O| >= 10 and mean_O(R) > 0 with p_boot (statistic mean_O(R)) < 0.025 and mean_O(R) > mean_{N_valid}(R).

15.4 **S2 size.** On G_valid with sizes m_i in {0.5, 1.0, 1.5}: Delta2 = sum(m R) / sum(m) - mean(R).
**PASS** = counts (15.6) and Delta2 > 0 and p_boot < 0.025 and operational validity. Read: the same within T.

15.5 **S3 discretionary.** d_i = R_ai,i - (R_long,i + R_short,i) / 2 (exact coin-flip expectation at the same coin,
time and stop; no seeds). Delta3 = mean_E(d). **PASS** = counts (15.6) and Delta3 > 0 and p_boot < 0.025 and
mean_E(R_ai) > 0 and S3 validity (15.6). Reads: `AI_DISC` equity vs the 100 `FLIP_DISC` accounts (rank), vs
`RANDCOIN_DISC`, share of proposals that coincide with a hunt event (same coin and side within 4 h).

15.6 **Minimum counts and validity** (evaluated per look; below minimum = **INSUFFICIENT**, not a fail):
S1: |T| >= 15, |S| >= 10, >= 3 eligible blocks. S1-N: |O| >= 10. S2: |G_valid| >= 30 with >= 5 at 0.5 and >= 5 at 1.5.
S3: |E| >= 20, >= 3 eligible blocks.
Operational validity (else **INVALID**): S1 primary no-answer share over G asks <= 5% (all codes of 6.4, including
`late_pickup` and `screen_check`; excluding only pause/budget time); paused or budget-stopped time <= 3 days in total;
S3 no-answer share over scans <= 10%; lock hashes match.

15.7 **Labels and actions.**

| Label | Action |
|---|---|
| S1 PASS | from the next 00:00 UTC, `AI_FILTER` becomes the main paper line (G and TAKE only; no answer -> rule). The hunt rule accounts continue unchanged as the control; the hunt v1 review is unaffected |
| S1-N PASS | the main line becomes `AI_FILTER_OVR` (adds N and TAKE) |
| S2 PASS | the main line applies m x U, inside the 4% open-risk cap |
| S3 PASS | `AI_DISC` continues as a named paper account beside the hunt bot (never mixed into it) |
| INSUFFICIENT at L1 | keep recording; the stage is evaluated at L2 with the same rules |
| FAIL | recorded with every number; no tuning; a changed AI is a v2 |
| INVALID | reported with the cause; a fix is a v2 |
| any | **real money only by an explicit owners' decision**, after the hunt's own review allows real money at all |

A stage that passes at L1 is acted on at L1 and is not re-tested at L2. A stage that fails at L1 is still evaluated at
L2 (the alpha split allows it).

15.8 **Reads, never decisions:** the twin's Delta1/Delta2 and its agreement with the primary; Spearman correlation
between signed confidence (+c for TAKE, -c for SKIP) and R; invalidation hit share and R after a hit; late-fill R minus
R; per entry type, per side, per class; account equity curves; no-answer bias (mean R of G asks without a valid answer vs
G_valid); cost per decision; "does the AI change after a run of outcomes" is not measurable because it never sees any.

15.9 **Before the look date** the eval code runs weekly on live data and prints only "ran / failed". No p-value and no
pass status is computed, shown or sent before a look.

15.10 **Power (stated now).** Trend-system R per signal is fat-tailed (many -1R, a few > +10R); assume a standard
deviation of 3-5R. With |T| = 26 and |S| = 14 at L1 (about the mid case of a 1h pick), the 80%-power minimum detectable
Delta1 at one-sided 0.025 is about 2.8 x sd x sqrt(1/26 + 1/14), i.e. about 3-5R. With 3-4 week blocks the bootstrap is
coarse, which is why the within-block permutation test must agree. The most likely L1 result is INSUFFICIENT or FAIL
for S1 and S2; S3 accumulates fastest (6 scans a day, 0-3 proposals each).

15.11 **Family-wise note.** Three independent stage families (S1 with S1-N nested, S2, S3), each <= 0.05 over both looks:
the chance that at least one passes by luck when the AI adds nothing is at most about 15%. A pass changes paper
accounts only.

## 16. Reporting (silent Telegram, chat "추세 사냥 AI"; Korean; no ranking, no p before a look)

* Per S1 decision (optional, default on): one line `코인 방향 G/N · TAKE/SKIP 확신 크기 · 이유`.
* Daily 23:00 KST: asks by class and decision, no-answer by code, latency p50/p95, spend (USD and KRW at 1,400) vs caps,
  circuit and budget events.
* Weekly (Sunday evening): counts and mean R per set with n, account equity reads, cost per decision, operations.
  Footer: "판정 아님. 판정은 11/15 (부족하면 12/27)".
* Dashboard (optional): read-only GET screens; reason text escaped; no buttons that change state.

## 17. Server: new Vultr instance

Why separate: the existing paper bot server runs the rule bot (in its verdict period), the candidate league and the
demo lab as guests; their verdicts must not be disturbed by CPU, memory, disk, restarts or Binance request weight
shared on one IP. The Anthropic key for this work then lives only here. Note: PREREG_HUNT section 15 says the forward
paper bot runs "on the paper bot server"; that line needs changing before the hunt pin (owners / main session; this
spec does not edit that file). Leverage brackets (`exchange30.json`, PREREG_HUNT Q3) are exported once on the server
that has the read key and copied over; they contain no secret.

| Resource | Recommendation | Reasoning |
|---|---|---|
| CPU | 4 vCPU, dedicated if offered (Optimized Cloud Compute, General Purpose); else Shared CPU 4 vCPU | real load is light (30 coins x indicators at 1h/4h closes; the judge is I/O bound; bootstrap 10,000 x a few hundred items takes seconds). 4 cores keep the bar-close burst (hunt signals + packets + book + dashboard + backup compression) inside a few seconds; dedicated avoids neighbour stalls inside the 60 s window |
| RAM | 8 GB minimum, 16 GB recommended | hunt bot with 400 days of 5m bars for 30 coins in numpy (~0.2 GB) plus Python overhead; 4-5 services ~2-3 GB peak; the rest is SQLite page cache and room for the planned wider hunt |
| Disk | NVMe/SSD 80 GB minimum, 160 GB recommended | 5m bars ~3.2 M rows/year for 30 coins (~0.3-0.5 GB with indexes); judge packets ~10 MB/month (S1) + ~35 MB/month (S3); 14 daily backups; OS and two venvs ~6 GB |
| Region | Tokyo; else Seoul; else Singapore. Never a US region (Binance blocks it) | Binance USD-M is widely reported to be served from Tokyo; nearest for websockets and REST |
| OS | Ubuntu 24.04 LTS x64 | same as the existing servers |
| Price | **check the Vultr pricing page** | no source file in this repo for current Vultr prices |

Server setup (by the install guide, later): users `hunt`, `huntai`, `huntbook`, `huntdash`; `chrony`; `ufw` deny
inbound except SSH and Tailscale; Tailscale for the dashboard; unattended security updates **without** automatic
reboot; SSH key login then password login off (as `docs/server-setup-v3.md`); healthchecks.io ping from the judge every
hour and from the hunt bot every 5 minutes. Owners' click-by-click creation steps: `DESIGN_KO.md` section 8.

## 18. Tests (all against synthetic bars and a fake API server; no key)

* Packets: same inputs -> same bytes; a bar after B injected -> `screen_check`; forbidden token in block B ->
  `screen_check`; `rule_action` never present; token budget trimming order.
* Calls: fake server injecting latency (deadline and `late`), 429, 5xx, 529, refusal with category, `max_tokens`,
  wrong `model`, malformed JSON, out-of-range confidence, duplicate S3 coin, > 3 entries; `sending` row prevents a
  second bill after a crash between send and response; leader-follower start rule; circuit breaker timings; budget
  reservation, daily cap, 95% stop, spend-limit responses.
* Isolation: AST test that nothing under the judge, book or eval packages imports exchange order code or reads hunt.db
  in write mode; the judge process cannot open `/etc/huntjudge` after start.
* Outcomes: standalone R equals the hunt code on synthetic paths (adds, stop moves, chandelier, intrabar order, funding
  sign); exact coin-flip expectation; marking; late-fill.
* Evaluation on simulated data, 2,000 runs: AI with no skill -> S1/S2/S3 PASS share <= 2.5% each; strong AI (Delta1 = 6R,
  60 signals, R sd 3R) -> PASS >= 80%; counts below minimum -> INSUFFICIENT; no-answer 6% -> INVALID; same seed twice -> byte-
  identical output; S1-N not evaluated unless S1 passes.

## 19. Volume and cost derivation (estimates)

Signal rate: PREREG_HUNT gives floors only (>= 2 positions a month for eligibility, P0 >= 66 positions in 33 months),
and no study data was opened for this spec. Textbook-order guesses per coin on 1h bars: E1 (fresh 55-bar breakout with
volume >= 2x) about 0.1-0.2 events a day; E2 (squeeze release) about 0.2-0.4; E3 (ATR ratio crossing 1.5) about
0.1-0.3. Times 30 coins: a 1h pick gives about 3-12 events a day (4h: 1-3); G1 passes about 15-40% of them. S1 asks
every event (G and N): **low 2 a day (4h pick), mid 8 (1h pick), high 15** (above the top of the guess, as margin). S3: 6 scans a day = 182 a month. The hunt
select output (events and gated signals per month of the pick) replaces these numbers before D0.

Tokens per call: S1 input 11,500 (5,500 cached prefix: system 3,000 + market 2,500; coin block 6,000), 1.5 asks per
model per active bar close (leader writes, followers read); output (thinking + answer) short / mid / long =
1,000 / 3,000 / 8,000. S3 input 52,000 (no cache benefit), output 3,000 / 8,000 / 20,000. Month = 30.4 days; +5% for
late or failed answers that still bill.

Per call (mid thinking): S1 Fable $0.256, S1 Opus twin $0.103, S3 Fable $0.92.

Monthly, USD and KRW at **1 USD = 1,400 KRW**:

| S1 volume \ thinking | short | mid | long |
|---|---|---|---|
| low (61 asks) | $142 / 199,000 | $199 / 279,000 | $336 / 471,000 |
| **mid (243 asks)** | $184 / 258,000 | **$268 / 375,000** | $472 / 661,000 |
| high (456 asks) | $233 / 326,000 | $348 / 487,000 | $631 / 883,000 |

Mid/mid split: S1 primary + twin $87, S3 $168, reserve $13. Without caching mid/mid would be $271 (caching saves ~1%
at this cadence). One-time start gate (200 S1 packets x 2 models + 30 S3 scans): about $99 (139,000 KRW), capped at $150.
Everything is console spend before tax; card charges add tax, foreign-payment fees and the day's exchange rate.

## 20. Open questions and dependencies

1. Primary model: Fable 5.1 (strongest; chosen because the owners accept cost) or Opus 5.5 (the skill's default). Default
   Fable 5.1 with the Opus 5.5 twin recorded.
2. Server-side refusal fallbacks: off by design (6.1). Default off.
3. Ask N-class (gate-blocked) events in S1: default yes; requires the hunt bot to record every event (section 3).
4. S3 with web search as a separate second discretionary account: default no in v1 (needs its own pre-registration).
5. Caps $700/month, $45/day: default as written. The org-wide spend limit is shared with the V3 AI trader and the debate
   room if they run in the same org: owners check the console (tier, org limit, data retention for Fable 5.1).
6. Key: default a new workspace `hunt-judge` with its own key and spend limit, placed by the owners with `sudoedit`.
   (Copying the existing server's key file server-to-server is possible but shares that workspace's limit.)
7. PREREG_HUNT section 15 "paper bot server" -> the new server: must be changed before the hunt pin.
8. If hunt v1 fails: the judge attaches to the "v1 failed" paper shadow if the owners run it; if no hunt paper bot runs,
   S1/S2 do not start and S3 could run alone on the hunt bot's data feed (owners decide).
9. Dependency: the hunt study's select/test (10/15-10/17) gives the pick, its timeframe and the real event rate; the
   cost table and the token budgets are recomputed then. If the hunt grows into the wider version (more entries and
   timeframes), S1 volume and cost scale with the number of events asked.
10. Fable 5.1 latency inside 60 s is unknown until the start gate; the ladder (14.3) decides without owner input.
