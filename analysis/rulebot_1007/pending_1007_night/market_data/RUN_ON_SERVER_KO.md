# 토요일(10/10) 서버에서 시장 자료 내보내기 (읽기 전용)

무엇을 하나: `/var/lib/paperbot`의 시장 기록(강제청산 `liq.db`, 미결제약정·롱숏·테이커·프리미엄 `flow.db`, 옛 기록기 `market.db`의 펀딩,
`paper3.db`의 호가 체결 비용 `fill_costs`와 1분봉 `live_bars`)과 `data/macro_events.csv`를 zip 하나로 묶어 `/root`에 둡니다.
없는 DB는 "없음"이라고 적고 넘어갑니다. 그것 자체가 답입니다(예: `flow.db 없음` = 롱숏·미결제약정 실시간 기록이 없다는 뜻).

안전:
- 모든 DB를 읽기 전용으로 엽니다. 아무도 열고 있지 않은 DB는 `immutable`로 열어 `-wal`/`-shm` 파일도 만들지 않습니다.
- 결과는 `/root`에만 씁니다. `/var/lib/paperbot`·`/opt/crypto-bot-research` 안에는 쓰지 않고, 끝에 "자료 폴더에 새로 생긴 파일: 없음"을 확인해 출력합니다.
- 네트워크·바이낸스 요청 없음. 서비스·타이머·설정을 바꾸지 않습니다(`systemctl show`로 상태만 읽음).
- 같은 이름 파일이 있으면 덮어쓰지 않고, `/root` 남은 공간이 300 MB 미만이면 멈춥니다.

언제: **토요일 10/10 오후(예: 14:15 KST).** 피할 시간: 매일 08:30~09:40 KST(백업·매일 점검), 그리고 매시 05~12분(flow 기록 시각).

예상 크기: 약 1~15 MB(가운데 3~8 MB). 강제청산이 며칠치 쌓였는지, `flow.db`가 있는지에 따라 달라집니다. 시간은 보통 1분 안.

## 1. 붙여 넣기 (한 덩어리 전부)

```bash
sudo -i
```

그다음 아래 상자를 통째로 붙여 넣습니다(`cat`부터 `EOF`까지).

```bash
cat > /root/rb_export_market.py <<'EOF'
#!/usr/bin/env python3
"""READ-ONLY market-data export for the AI-screen check (liq.db, flow.db, market.db, paper3.db fill_costs/live_bars,
macro_events.csv). Standard library only. Run as root with nice/ionice (RUN_ON_SERVER_KO.md).

Safety: every database is opened read-only. A WAL database whose -wal file is missing (nobody has it open, everything
is in the main file) is opened with immutable=1, so SQLite never creates -wal/-shm files in the data folder; a WAL
database with a -wal but no -shm is skipped. The zip goes to /root (never under PB_ROOT or PB_APP); the script refuses
to overwrite a file or to run with less than 300 MB free, and at the end checks that no new file appeared in the
folders it read. Nothing is fetched from the network.

Env (all optional): PB_ROOT=/var/lib/paperbot  PB_APP=/opt/crypto-bot-research  PB_OUT=/root/paperbot_market_<UTC>.zip
PB_SINCE=2026-10-01T15:00:00Z (10/02 00:00 KST)  PB_FLOW_SINCE=2026-09-28T00:00:00Z (1 day overlap with the repo's
public metrics)  PB_BARS_SINCE=2026-10-07T06:00:00Z (after the 10/07 export)  PB_LIQ_RAW_MAX=1500000
"""
import csv, glob, hashlib, io, json, os, shutil, sqlite3, subprocess, sys, time, zipfile
from datetime import datetime, timezone
from urllib.parse import quote


def ms(s):
    return int(datetime.strptime(s.strip().replace("Z", ""), "%Y-%m-%dT%H:%M:%S" if "T" in s else "%Y-%m-%d")
               .replace(tzinfo=timezone.utc).timestamp() * 1000)


ROOT = os.path.realpath(os.environ.get("PB_ROOT", "/var/lib/paperbot"))
APP = os.path.realpath(os.environ.get("PB_APP", "/opt/crypto-bot-research"))
OUT = os.path.realpath(os.environ.get("PB_OUT", f"/root/paperbot_market_{time.strftime('%Y%m%d_%H%M', time.gmtime())}.zip"))
SINCE = ms(os.environ.get("PB_SINCE", "2026-10-01T15:00:00Z"))
FLOW_SINCE = ms(os.environ.get("PB_FLOW_SINCE", "2026-09-28T00:00:00Z"))
BARS_SINCE = ms(os.environ.get("PB_BARS_SINCE", "2026-10-07T06:00:00Z"))
LIQ_RAW_MAX = int(os.environ.get("PB_LIQ_RAW_MAX", "1500000"))
COINS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "LTCUSDT", "BCHUSDT", "DOGEUSDT", "XRPUSDT")
QC = ",".join("?" * len(COINS))
FLOW_TABLES = ("oi5m", "ls_global5m", "ls_top_account5m", "ls_top_position5m", "taker5m", "premium5m")
UNITS = ("paperbot-liq.service", "paperbot-flow.timer", "paperbot-flow.service", "paperbot-record.timer",
         "paperbot-record.service", "paperbot-live3.service")
log, notes, opened_dirs = [], [], set()


def iso(t):
    return None if t is None else datetime.fromtimestamp(t / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")


def under(p, d):
    return p == d or p.startswith(d.rstrip("/") + "/")


def ro(path):
    """(connection, how) for a read-only connection that never creates a file next to ``path``."""
    with open(path, "rb") as f:
        hdr = f.read(100)
    wal = len(hdr) >= 20 and hdr[18] == 2 and hdr[19] == 2
    has_wal, has_shm = os.path.exists(path + "-wal"), os.path.exists(path + "-shm")
    if wal and has_wal and not has_shm:
        raise RuntimeError("WAL 파일은 있는데 -shm 이 없음: 파일을 새로 만들지 않으려고 건너뜀")
    how = "immutable" if wal and not has_wal else "ro"
    q = "immutable=1" if how == "immutable" else "mode=ro"
    c = sqlite3.connect(f"file:{quote(path)}?{q}", uri=True, timeout=30)
    c.execute("PRAGMA query_only=1")
    opened_dirs.add(os.path.dirname(path))
    return c, how


def tables(c):
    return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def cols(c, t):
    return [r[1] for r in c.execute(f"PRAGMA table_info({t})")]


def put(z, name, header, rows):
    n = 0
    with z.open(name, "w", force_zip64=True) as f:
        t = io.TextIOWrapper(f, encoding="utf-8", newline="")
        w = csv.writer(t)
        w.writerow(header)
        for r in rows:
            w.writerow(r)
            n += 1
        t.flush()
        t.detach()
    log.append(f"{name}: {n}")
    return n


def listing():
    out = {}
    for d in sorted(opened_dirs | {ROOT} | {os.path.dirname(p) for p in glob.glob(f"{ROOT}/archive/run-*/paper3.db")}):
        try:
            out[d] = set(os.listdir(d))
        except OSError:
            out[d] = set()
    return out


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


# ---------------------------------------------------------------- sections
def sec_env(z):
    rows = []
    for u in UNITS:
        try:
            r = subprocess.run(["systemctl", "show", u, "-p", "LoadState,UnitFileState,ActiveState,SubState,Result,"
                                "ActiveEnterTimestamp,ExecMainStartTimestamp,LastTriggerUSec,NextElapseUSecRealtime"],
                               capture_output=True, text=True, timeout=15)
            d = dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l)
        except Exception as e:  # noqa: BLE001
            d = {"error": f"{type(e).__name__}"}
        rows.append([u] + [d.get(k, "") for k in ("LoadState", "UnitFileState", "ActiveState", "SubState", "Result",
                                                    "ActiveEnterTimestamp", "ExecMainStartTimestamp", "LastTriggerUSec",
                                                    "NextElapseUSecRealtime", "error")])
    put(z, "env/units.csv", ["unit", "load", "enabled", "active", "sub", "result", "active_since", "main_start",
                             "last_trigger", "next", "error"], rows)
    files = []
    for p in sorted(glob.glob(f"{ROOT}/*.db") + glob.glob(f"{ROOT}/*/*.db") + glob.glob(f"{ROOT}/archive/*/*.db")):
        st = os.stat(p)
        files.append([os.path.relpath(p, ROOT), st.st_size, iso(int(st.st_mtime * 1000)),
                      int(os.path.exists(p + "-wal")), int(os.path.exists(p + "-shm"))])
    put(z, "env/db_files.csv", ["path", "bytes", "mtime_utc", "wal", "shm"], files)
    ver = {}
    try:
        ver = json.load(open(os.path.join(APP, "VERSION.json")))
    except Exception as e:  # noqa: BLE001
        ver = {"error": type(e).__name__}
    try:
        ver["liqstream_STREAM"] = [l.strip()[:120] for l in open(os.path.join(APP, "paperbot/liqstream.py"))
                                   if l.startswith("STREAM")]
    except OSError:
        pass
    z.writestr("env/version.json", json.dumps(ver, indent=1))


def sec_liq(z):
    p = os.path.join(ROOT, "liq.db")
    if not os.path.exists(p):
        notes.append("liq.db 없음: 강제청산 기록 없음")
        return
    c, how = ro(p)
    usd = "filled_qty * COALESCE(NULLIF(avg_price, 0), price)"
    put(z, "liq/liq_coverage_daily.csv", ["day_utc", "rows", "symbols", "usd", "rows_7coins", "usd_7coins",
                                          "first_utc", "last_utc"],
        ([iso(r[0])[:10]] + list(r[1:6]) + [iso(r[6]), iso(r[7])] for r in c.execute(
            f"SELECT (trade_ts/86400000)*86400000 d, COUNT(*), COUNT(DISTINCT symbol), ROUND(SUM({usd})), "
            f"SUM(symbol IN ({QC})), ROUND(SUM(CASE WHEN symbol IN ({QC}) THEN {usd} END)), MIN(trade_ts), "
            f"MAX(trade_ts) FROM liq GROUP BY d ORDER BY d", COINS + COINS)))
    put(z, "liq/liq_conn_log.csv", ["ts", "utc", "event", "detail"],
        ([r[0], iso(r[0]), r[1], (r[2] or "")[:300]] for r in c.execute("SELECT ts, event, detail FROM conn_log ORDER BY ts")))
    n = put(z, "liq/liq_raw_7coins.csv", ["event_ts", "trade_ts", "symbol", "side", "order_type", "tif", "qty", "price",
                                          "avg_price", "status", "last_qty", "filled_qty", "received_ts"],
            c.execute(f"SELECT event_ts, trade_ts, symbol, side, order_type, tif, qty, price, avg_price, status, "
                      f"last_qty, filled_qty, received_ts FROM liq WHERE symbol IN ({QC}) AND trade_ts >= ? "
                      f"ORDER BY trade_ts LIMIT ?", COINS + (SINCE, LIQ_RAW_MAX)))
    if n >= LIQ_RAW_MAX:
        notes.append(f"liq_raw_7coins 가 {LIQ_RAW_MAX}행에서 잘림 (1분 합계는 전부 있음)")
    put(z, "liq/liq_1m_7coins.csv", ["minute_ts", "symbol", "side", "n", "qty", "usd", "max_usd"],
        c.execute(f"SELECT (trade_ts/60000)*60000 m, symbol, side, COUNT(*), SUM(filled_qty), ROUND(SUM({usd}), 2), "
                  f"ROUND(MAX({usd}), 2) FROM liq WHERE symbol IN ({QC}) AND trade_ts >= ? GROUP BY m, symbol, side "
                  f"ORDER BY m", COINS + (SINCE,)))
    put(z, "liq/liq_1m_all.csv", ["minute_ts", "side", "n", "symbols", "usd"],
        c.execute(f"SELECT (trade_ts/60000)*60000 m, side, COUNT(*), COUNT(DISTINCT symbol), ROUND(SUM({usd}), 2) "
                  f"FROM liq WHERE trade_ts >= ? GROUP BY m, side ORDER BY m", (SINCE,)))
    last = c.execute("SELECT MAX(trade_ts), COUNT(*) FROM liq").fetchone()
    notes.append(f"liq.db ({how}): 전체 {last[1]}행, 마지막 청산 {iso(last[0])} UTC")
    c.close()


def sec_flow(z):
    p = os.path.join(ROOT, "flow.db")
    if not os.path.exists(p):
        notes.append("flow.db 없음: 미결제약정·롱숏·테이커·프리미엄 실시간 기록 없음 (paperbot-flow.timer 미설치 추정)")
        return
    c, how = ro(p)
    t = tables(c)
    cov = []
    for tb in FLOW_TABLES:
        if tb not in t:
            continue
        cl = cols(c, tb)
        put(z, f"flow/{tb}.csv", cl, c.execute(f"SELECT {', '.join(cl)} FROM {tb} WHERE ts >= ? ORDER BY symbol, ts",
                                               (FLOW_SINCE,)))
        cov += [[tb] + list(r[:2]) + [iso(r[0])[:10]] + list(r[2:]) for r in c.execute(
            f"SELECT (ts/86400000)*86400000 d, symbol, COUNT(*), MIN(received_ts - ts), MAX(received_ts - ts) "
            f"FROM {tb} WHERE ts >= ? GROUP BY d, symbol ORDER BY d, symbol", (FLOW_SINCE,))]
        mx = c.execute(f"SELECT MIN(ts), MAX(ts) FROM {tb}").fetchone()
        notes.append(f"flow.db {tb} ({how}): {iso(mx[0])} ~ {iso(mx[1])} UTC")
    put(z, "flow/flow_coverage_daily.csv", ["table", "day_ms", "symbol", "day_utc", "rows_of_288", "min_lag_ms",
                                            "max_lag_ms"], cov)
    for tb, q, a in (("revisions", "SELECT * FROM revisions ORDER BY ts", ()),
                     ("gaps", "SELECT * FROM gaps ORDER BY ts", ()),
                     ("sync_log", "SELECT * FROM sync_log WHERE ts >= ? ORDER BY ts", (FLOW_SINCE,))):
        if tb in t:
            put(z, f"flow/flow_{tb}.csv", cols(c, tb), c.execute(q, a))
    if "system_log" in t:
        put(z, "flow/flow_system_log_tail.csv", ["ts", "utc", "event", "detail"],
            ([r[0], iso(r[0]), r[1], (r[2] or "")[:300]] for r in
             c.execute("SELECT ts, event, detail FROM system_log ORDER BY ts DESC LIMIT 50")))
    c.close()
    if how == "immutable" and os.path.exists(p + "-wal"):
        notes.append("flow.db 를 읽는 동안 기록이 시작됨: 매시 05~12분을 피해 다시 실행 권장")


def sec_market(z):
    p = os.path.join(ROOT, "market.db")
    if not os.path.exists(p):
        notes.append("market.db 없음 (옛 신호 기록기)")
        return
    c, how = ro(p)
    t = tables(c)
    cov = []
    for tb, k in (("kline5m", "open_time"), ("mark5m", "open_time"), ("funding", "funding_time")):
        if tb in t:
            cov += [[tb, r[0], iso(r[1]), iso(r[2]), r[3]] for r in c.execute(
                f"SELECT symbol, MIN({k}), MAX({k}), SUM({k} >= ?) FROM {tb} GROUP BY symbol", (SINCE,))]
    put(z, "market/market_coverage.csv", ["table", "symbol", "first_utc", "last_utc", "rows_since"], cov)
    if "funding" in t:
        put(z, "market/market_funding.csv", ["symbol", "funding_time", "rate", "mark_price", "received_ts"],
            c.execute("SELECT symbol, funding_time, rate, mark_price, received_ts FROM funding WHERE funding_time >= ? "
                      "ORDER BY funding_time, symbol", (FLOW_SINCE,)))
    if "sync_log" in t:
        put(z, "market/market_sync_log_tail.csv", cols(c, "sync_log"),
            c.execute("SELECT * FROM sync_log ORDER BY ts DESC LIMIT 40"))
    mx = c.execute("SELECT MAX(open_time) FROM kline5m").fetchone()[0] if "kline5m" in t else None
    notes.append(f"market.db ({how}): 5분봉 마지막 {iso(mx)} UTC")
    c.close()


def fc_rows(c, tag):
    for r in c.execute("SELECT id, ts, account_id, symbol, event, status, notional, slip_best, data FROM fill_costs "
                       "WHERE ts >= ? ORDER BY id", (SINCE,)):
        try:
            d = json.loads(r[8] or "{}")
        except ValueError:
            d = {}
        bk = d.get("book") or []
        best = d.get("best")
        try:
            kept = sum(float(p) * float(q) for p, q in bk)
            far = abs(float(bk[-1][0]) - float(best)) / float(best) if bk and best else None
        except (TypeError, ValueError, IndexError):
            kept, far = None, None
        yield [tag] + list(r[:8]) + [d.get(k) for k in ("slip_mid", "spread", "best", "levels", "enough",
                                                         "order_side", "book_ts", "assumed_slip", "filled_notional")] + \
            [len(bk), None if kept is None else round(kept, 2), None if far is None else round(far, 6)]


def sec_paper(z):
    srcs = [(os.path.basename(os.path.dirname(p)), p) for p in sorted(glob.glob(f"{ROOT}/archive/run-*/paper3.db"))]
    srcs.append(("current", os.path.join(ROOT, "paper3.db")))
    allfc, allbars = [], []
    for tag, p in srcs:
        if not os.path.exists(p):
            continue
        try:
            c, how = ro(p)
        except Exception as e:  # noqa: BLE001
            log.append(f"{tag}/paper3.db: 건너뜀 {e}")
            continue
        t = tables(c)
        if "fill_costs" in t:
            allfc.append((tag, c))
        if "live_bars" in t:
            allbars.append((tag, c))
    put(z, "paper/fill_costs_detail.csv", ["run", "id", "ts", "account_id", "symbol", "event", "status", "notional",
                                           "slip_best", "slip_mid", "spread", "best", "levels", "enough", "order_side",
                                           "book_ts", "assumed_slip", "filled_notional", "book_levels_kept",
                                           "book_notional_kept", "book_far_frac"],
        (row for tag, c in allfc for row in fc_rows(c, tag)))
    put(z, "paper/live_bars.csv", ["run", "ts", "symbol", "open", "high", "low", "close", "volume", "mark_open",
                                   "mark_high", "mark_low", "mark_close", "close_time", "processed_at"],
        ([tag] + list(r) for tag, c in allbars for r in c.execute(
            "SELECT ts, symbol, open, high, low, close, volume, mark_open, mark_high, mark_low, mark_close, close_time, "
            "processed_at FROM live_bars WHERE ts >= ? ORDER BY ts, symbol", (BARS_SINCE,))))
    for _tag, c in {id(c): (t, c) for t, c in allfc + allbars}.values():
        c.close()
    p = os.path.join(ROOT, "paper.db")
    if os.path.exists(p):
        try:
            c, how = ro(p)
            if "book" in tables(c):
                r = c.execute("SELECT MIN(ts), MAX(ts), SUM(ts >= ?) FROM book", (SINCE,)).fetchone()
                notes.append(f"paper.db(v2) book 최우선호가: {iso(r[0])} ~ {iso(r[1])} UTC, 기간 안 {r[2]}행 (내보내지 않음)")
            c.close()
        except Exception as e:  # noqa: BLE001
            notes.append(f"paper.db: {type(e).__name__}: {e}")


def sec_macro(z):
    seen = {}
    for p in (os.path.join(APP, "data/macro_events.csv"), "/root/crypto-bot-research/data/macro_events.csv"):
        if os.path.exists(p):
            h = sha(p)
            seen.setdefault(h, p)
            st = os.stat(p)
            log.append(f"macro {p}: sha256 {h[:16]} {st.st_size}B mtime {iso(int(st.st_mtime * 1000))}")
    for i, (h, p) in enumerate(seen.items()):
        z.write(p, "macro/macro_events.csv" if i == 0 else f"macro/macro_events_{i}.csv")
    if not seen:
        notes.append("macro_events.csv 를 찾지 못함")


def main():
    if under(OUT, ROOT) or under(OUT, APP):
        sys.exit(f"거부: 출력 {OUT} 이 자료 폴더 안입니다")
    if os.path.exists(OUT):
        sys.exit(f"거부: {OUT} 이 이미 있습니다 (덮어쓰지 않음)")
    free = shutil.disk_usage(os.path.dirname(OUT)).free
    if free < 300e6:
        sys.exit(f"거부: {os.path.dirname(OUT)} 남은 공간 {free / 1e6:.0f} MB < 300 MB")
    if 5 <= time.gmtime().tm_min <= 12:
        print("참고: 매시 07분 flow 기록 시각 근처입니다. flow.db 가 열려 있지 않으면 13분 이후 다시 실행을 권합니다.")
    t0 = time.time()
    before = listing()
    part = OUT + ".part"
    try:
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for name, fn in (("env", sec_env), ("liq", sec_liq), ("flow", sec_flow), ("market", sec_market),
                             ("paper", sec_paper), ("macro", sec_macro)):
                try:
                    fn(z)
                except Exception as e:  # noqa: BLE001
                    log.append(f"{name}: 실패 {type(e).__name__}: {e}")
            after = listing()
            new = sorted(os.path.join(d, f) for d in after for f in after[d] - before.get(d, set()))
            notes.append("자료 폴더에 새로 생긴 파일: " + (", ".join(new) if new else "없음"))
            head = [time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
                    f"since {iso(SINCE)}  flow_since {iso(FLOW_SINCE)}  bars_since {iso(BARS_SINCE)}  root {ROOT}  app {APP}",
                    f"python {sys.version.split()[0]}  sqlite {sqlite3.sqlite_version}  {time.time() - t0:.0f}s"]
            z.writestr("manifest.txt", "\n".join(head + [""] + log + [""] + notes) + "\n")
        os.replace(part, OUT)
    except BaseException:
        if os.path.exists(part):
            os.remove(part)
        raise
    print("\n".join(log + [""] + notes))
    print(f"\n완료: {OUT}  ({os.path.getsize(OUT) / 1e6:.2f} MB, {time.time() - t0:.0f}초)")


if __name__ == "__main__":
    main()
EOF
sha256sum /root/rb_export_market.py | cut -c1-16
```

마지막 줄이 `f6bc6eaf965de70f` 이면 정확히 붙여 넣어진 것입니다. 다르면 파일을 지우고(`rm /root/rb_export_market.py`) 다시 붙여 넣습니다.

## 2. 실행

```bash
df -h /root
cd /root && nice -n 19 ionice -c3 python3 -I /root/rb_export_market.py 2>&1 | tee /root/rb_export_market.log
ls -la /root/paperbot_market_*.zip
```

- 끝에 `완료: /root/paperbot_market_<날짜_시각>.zip (x.xx MB, n초)`가 나오면 성공입니다.
- 화면에 나온 줄(파일별 행 수, 그리고 `liq.db ...`, `flow.db ...`, `market.db ...`, `자료 폴더에 새로 생긴 파일: 없음`)도 그대로 보내 주세요. `/root/rb_export_market.log`에도 같은 내용이 있습니다.
- `참고: 매시 07분 ...`이 나오면 13분 이후에 한 번 더 돌려도 됩니다(새 파일 이름으로 만들어짐).

## 3. 보내기

- zip 파일 하나와 `rb_export_market.log`를 지난번 내보내기(10/7) 파일을 옮긴 방법 그대로 보내 주세요.
- zip 안에 비밀 값은 없습니다: DB 내용 중 시장 자료·모의 체결 비용·1분봉, 서비스 상태(켜짐/꺼짐·시각), DB 파일 크기, 설치된 코드 커밋(`VERSION.json`), `macro_events.csv`만 들어 있습니다. 환경 파일(`/etc/paperbot/*.env`)은 읽지 않습니다.

## 4. 선택 (기본값으로 충분함)

필요할 때만 실행 줄 앞에 붙입니다. 예: `PB_FLOW_SINCE=2026-09-01T00:00:00Z nice -n 19 ionice -c3 python3 -I /root/rb_export_market.py`

| 값 | 기본 | 뜻 |
|---|---|---|
| `PB_SINCE` | 2026-10-01T15:00:00Z (10/02 00:00 KST) | 강제청산·호가 비용의 시작 |
| `PB_FLOW_SINCE` | 2026-09-28T00:00:00Z | flow.db 5분 자료·market.db 펀딩의 시작(저장소 공개 자료 마지막 날 9/28과 하루 겹쳐 대조용) |
| `PB_BARS_SINCE` | 2026-10-07T06:00:00Z | 1분봉 시작(10/7 내보내기에 이미 있는 부분은 뺌) |
| `PB_LIQ_RAW_MAX` | 1500000 | 7개 코인 강제청산 원본 행 상한(넘으면 1분 합계만 전부) |
| `PB_OUT` | /root/paperbot_market_<UTC 시각>.zip | 결과 파일(자료 폴더 안이면 거부) |

## 5. zip 안에 들어가는 것

| 파일 | 내용 |
|---|---|
| `manifest.txt` | 실행 시각, 파일별 행 수, 요약(각 DB의 첫·마지막 시각), 새로 생긴 파일 확인 |
| `env/units.csv` | paperbot-liq / flow / record / live3 서비스·타이머 상태 |
| `env/db_files.csv` | `/var/lib/paperbot`의 DB 파일 이름·크기·수정 시각 |
| `env/version.json` | 설치된 코드 커밋, 강제청산 수집 주소 줄(`/market` 고침이 배포됐는지) |
| `liq/liq_coverage_daily.csv` | 강제청산 기록 날짜별 행 수·금액(전 기간) |
| `liq/liq_conn_log.csv` | 수집기 연결·끊김 기록 |
| `liq/liq_raw_7coins.csv` | 7개 코인 강제청산 원본(10/02부터) |
| `liq/liq_1m_7coins.csv`, `liq/liq_1m_all.csv` | 1분 합계(코인·방향별 / 시장 전체) |
| `flow/*.csv` | 미결제약정, 롱숏 3종, 테이커, 프리미엄 5분 원본 + 날짜별 개수(하루 288이 정상)·받은 시각 지연 + 수정·구멍 기록 |
| `market/*.csv` | 옛 기록기의 펀딩 정산값과 마지막 기록 시각 |
| `paper/fill_costs_detail.csv` | 모의 진입·청산 때 호가로 잰 비용(스프레드, 미끄러짐, 채운 칸 수, 남긴 호가 금액) — v3a·v3b·v4 |
| `paper/live_bars.csv` | 6개 코인 1분봉(가격·거래량·마크) 10/7 06:00 UTC 이후 |
| `macro/macro_events.csv` | 서버에 설치된 발표 일정 파일 |
