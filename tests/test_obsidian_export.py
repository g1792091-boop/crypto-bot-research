"""The Obsidian vault exporter (paperbot/obsidian_export.py): a read-only, regenerable Markdown view of the databases
and documents. Synthetic paper3 / daily3 / agents3 / checkpoint / inbox databases and a small fake repo."""
import hashlib
import html.parser
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from paperbot import obsidian_export as X
from paperbot import obsidian_notes as N
from paperbot import obsidian_preview as PV
from paperbot import obsidian_util as U
from paperbot.agents import rooms_db as R
from paperbot.agents.roster3 import GROUP_SPECIALISTS, ROLES, STRATEGY_KO, TEAMS
from paperbot.store3 import SCHEMA as PAPER_SCHEMA

KST = timezone(timedelta(hours=9))
REPO = Path(__file__).resolve().parent.parent
START = int(datetime(2026, 10, 5, 10, 46, tzinfo=KST).timestamp() * 1000)
DAY = 86_400_000
NOW = START + 3 * DAY + 20 * 3_600_000
SCRATCH = Path("/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/review3c/bk/lib")

SECRETS = ["sk-ant-api03-AbCdEfGhIjKlMnOpQr123456", "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw0",
           "chat_id: -1001234567890", "100.64.12.34", "/etc/paperbot/agents.env", "boss@example.com",
           "token=abcdef1234567890"]
SECRET_TEXT = " 비밀 " + " ".join(SECRETS) + " 끝"


# ------------------------------------------------------------------ the synthetic world
def trade(strat, tf, i, tier, pnl, roe, lev=30, reason="SL", t0=START):
    t = t0 + i * 3_600_000
    return (f"{strat}@{tf}", "BTCUSDT", t, t + 1_800_000, reason, lev, pnl, roe, 5000 + pnl,
            json.dumps({"strategy_id": strat, "timeframe": tf, "tier": tier, "margin": 1500.0, "leverage": lev,
                        "tp_price": float("nan"), "pnl": pnl, "roe": roe, "exit_reason": reason}))


def make_paper(path):
    c = sqlite3.connect(path)
    c.executescript(PAPER_SCHEMA)
    for s in ("S2_ST_ROC", "N22_VORTEX_PSAR"):
        for tf in ("15m", "30m", "1h", "4h"):
            c.execute("INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?)", (f"{s}@{tf}", s, tf, "strategy", START, "paper-v3", None, "{}"))
    for k in (1, 2, 3):
        c.execute("INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?)", (f"RANDOM_{k}@15m", f"RANDOM_{k}", "15m", "random", START, "paper-v3", None, "{}"))
    rows = [trade("S2_ST_ROC", "15m", i, "best" if i % 2 else "normal", 50.0 if i % 3 else -80.0, 0.1 if i % 3 else -0.2,
                  lev=50 if i % 2 else 30, reason="LOCK" if i % 3 else "SL") for i in range(12)]
    rows += [trade("N22_VORTEX_PSAR", "1h", i, "normal", -40.0, -0.1) for i in range(3)]
    c.executemany("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, equity_after, data)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    for aid, eq in (("S2_ST_ROC@15m", 5100.0), ("N22_VORTEX_PSAR@1h", 4880.0), ("RANDOM_1@15m", 4500.0)):
        c.execute("INSERT INTO equity VALUES (?,?,?,?)", (aid, NOW, eq, 0.1))
    eng = {"S2_ST_ROC@15m": {"wallet": 5100.0, "max_drawdown": 0.12, "halted": False, "bust": False},
           "RANDOM_1@15m": {"wallet": 4500.0, "max_drawdown": 0.3, "halted": False, "bust": False}}
    c.execute("INSERT INTO state VALUES ('accounts', ?, ?)", (NOW, json.dumps({"engines": eng})))
    c.execute("INSERT INTO state VALUES ('run', ?, ?)", (START, json.dumps({"initial_equity": 5000.0, "settings": "paper-v3"})))
    c.execute("INSERT INTO state VALUES ('heartbeat', ?, ?)", (NOW, json.dumps({"steps": 5})))
    c.execute("INSERT INTO runs (started_ts, data) VALUES (?, ?)", (START, json.dumps({"commit": "abc123def456", "dirty": False})))
    c.commit()
    c.close()


def make_daily(path):
    from paperbot.daily3 import SCHEMA
    c = sqlite3.connect(path)
    c.executescript(SCHEMA)
    for k, day in enumerate(("2026-10-06", "2026-10-07")):
        rep = {"day": day, "steps": 1440, "strength": {"checked": 100, "failed": 0},
               "parity": {"accounts": 156, "mismatched_accounts": 1 if k else 0,
                          "live_bars": {"bars": 8640, "mismatched": 0}},
               "shadows": {"limit_signals": 10, "limit_filled": 6, "limit_mean_roe": 0.02, "skipped": 3,
                           "stop_variants": {"1.5": {"losing_trades": 4, "mean_roe": -0.2, "turned_positive": 1, "better_than_actual": 3}},
                           "trade_variants": {"closed": 12, "base": {"trades": 12, "resolved": 12, "mean_roe": -0.01},
                                              "lock15": {"trades": 12, "resolved": 11, "mean_roe": 0.02}, "curves": {"busts": []}}},
               "data_quality": {"BTCUSDT": {"missing": 0, "zero_volume": 0, "extreme_ranges": 0}, "max_abs_funding_pct": 0.01},
               "fill_costs": {"rows": [{"event": "entry", "slip_median": 1e-5}], "recorded": 40},
               "stop_slippage": {"overall": {"exits": 5, "measured": 0}}}
        c.execute("INSERT INTO reports VALUES (?,?,?)", (day, NOW, json.dumps(rep)))
    for i in range(6):
        key = f"2026-10-06|{{}}|S2_ST_ROC@15m|BTCUSDT|{START + i * 3_600_000}"
        c.execute("INSERT INTO shadows VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (key.format("base"), "2026-10-06", "base", "S2_ST_ROC@15m", "BTCUSDT", "15m", 1, None, 0.1, "LOCK", 1, json.dumps({"pnl_equity": 0.01})))
        c.execute("INSERT INTO shadows VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (key.format("lock15"), "2026-10-06", "lock15", "S2_ST_ROC@15m", "BTCUSDT", "15m", 1, None, 0.2, "LOCK", 1, json.dumps({"pnl_equity": 0.02})))
    c.commit()
    c.close()


def make_agents(path):
    conn = R.open_agents(path)
    R.ensure_rooms(conn, ts=START)
    d1 = START + 21 * 3_600_000          # 2026-10-06 07:46 KST
    def rnd(room, trig, ts, day, summary, status="done", calls=2):
        cur = conn.execute("INSERT INTO rounds (room_id, trigger, trigger_data, started_ts, ended_ts, status, decision, calls, tokens)"
                           " VALUES (?,?,?,?,?,?,?,?,?)",
                           (room, trig, json.dumps({"kst_day": day, "summary_ko": trig}), ts, ts + 1000, status,
                            json.dumps({"action": "note", "summary_ko": summary}), calls, 1000))
        conn.commit()
        return int(cur.lastrowid)
    r1 = rnd("team:market", "morning", d1, "2026-10-06", "아침 회의 끝\n- 최근 24시간(코드 집계): 끝난 거래 15건 S2_ST_ROC")
    R.post(conn, "team:market", r1, "morning", "chart_regime", None, "analysis", "BTC는 박스권입니다. N22_VORTEX_PSAR 는 신호가 적음. [[가짜 링크]] #태그" + SECRET_TEXT, ts=d1)
    R.post(conn, "team:market", r1, "morning", "team_lead", None, "summary", "1. 박스권\n2. 관망\n3. 표본 적음\n" + "길게 " * 600, ts=d1 + 5)
    R.post(conn, "team:market", r1, "morning", "code", None, "decision", "회의 끝", ts=d1 + 9)
    r2 = rnd("strat:S2_ST_ROC", "loss_cluster", d1 + 3_600_000, "2026-10-06", "손실 묶음 복기 끝: 새 손실 3건")
    R.post(conn, "strat:S2_ST_ROC", r2, "loss", "spec_S2_ST_ROC", None, "analysis", "추세 반대 진입이 많음", ts=d1 + 3_600_001)
    R.post(conn, "strat:S2_ST_ROC", r2, "loss", "code", None, "action", "메모 #1을 남겼습니다", ts=d1 + 3_600_002)
    rnd("team:lab", "research", d1 + 7_200_000, "2026-10-06", "새 매매법 시험 1개")
    rnd("strat:N22_VORTEX_PSAR", "weekly", d1 + 8_000_000, "2026-10-06", "주간 검토")
    rnd("team:market", "checkpoint", d1 + 9_000_000, "2026-10-06", "체크포인트 미리 보기")
    R.add_note(conn, "strat:S2_ST_ROC", "S2_ST_ROC", "교훈: 횡보장 진입 손실이 많다 (표본 3건)" + SECRET_TEXT, r2, ts=d1)
    R.add_note(conn, "strat:N22_VORTEX_PSAR", "N22_VORTEX_PSAR", "공통 메모", r2, ts=d1)
    pred = {"metric": "win_rate", "timeframe": "15m", "direction": "above", "value": 0.5, "after_trades": 30}
    h1 = R.add_trial(conn, "strat:S2_ST_ROC", "S2_ST_ROC", "hypothesis",
                     {"text": "승률이 50%를 넘을 것", "how_to_confirm": "30건 뒤", "prediction": pred, "by": "spec_S2_ST_ROC"}, ts=d1)
    R.add_trial_result(conn, h1, "graded", {"status": "graded", "correct": True, "value": 0.58, "n": 30, "prediction": pred}, ts=d1 + 1)
    R.add_trial(conn, "strat:S2_ST_ROC", "S2_ST_ROC", "hypothesis", {"text": "예측 없는 가설"}, ts=d1)
    t1 = R.add_trial_with_result(conn, "team:lab", None, "newlab", {"v": "newlab-v1", "timeframe": "4h", "entry": {"family": "keltner_break"}},
                                 "failed", {"ledger": {"test_number": 1, "gate": {"pass": False}}, "gate": {"pass": False, "test_number": 1}}, ts=d1)
    R.add_trial_with_result(conn, "strat:S2_ST_ROC", "S2_ST_ROC", "test", {"template": "skip_tag", "timeframe": "15m"},
                            "failed", {"gate": {"pass": False}}, ts=d1)
    R.add_proposal(conn, "strat:S2_ST_ROC", "S2_ST_ROC", None, {"kind": "copy", "timeframe": "15m"}, {"pass": False}, "blocked_gate", "code", ts=d1)
    conn.executescript("CREATE TABLE IF NOT EXISTS committee_calls (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, day TEXT NOT NULL, "
                       "round_id INTEGER, symbol TEXT NOT NULL, status TEXT NOT NULL, direction TEXT, confidence INTEGER, ref_ts INTEGER, "
                       "ref_price REAL, due_ts INTEGER, end_price REAL, move REAL, correct INTEGER, graded_ts INTEGER, data TEXT, UNIQUE (day, symbol));")
    conn.execute("INSERT INTO committee_calls (ts, day, symbol, status, direction, confidence, move, correct) VALUES (?,?,?,?,?,?,?,?)",
                 (d1, "2026-10-06", "BTCUSDT", "graded", "상승", 2, 0.012, 1))
    conn.execute("INSERT INTO agent_calls VALUES (?,?,?,?,?,?,?)", (d1, "2026-10-06", "scheduled", "chart_regime", "sonnet", 1, 1200))
    conn.commit()
    conn.close()


def make_checkpoint(path):
    from paperbot.checkpoint import SCHEMA
    c = sqlite3.connect(path)
    c.executescript(SCHEMA)
    c.execute("INSERT INTO verdicts VALUES (?,?,?,?)", ("2026-11-04", START + 30 * DAY, "ab" * 32, json.dumps({"accounts": {}})))
    c.execute("INSERT INTO verdict_accounts VALUES (?,?,?,?,?,?,?)",
              ("2026-11-04", "S2_ST_ROC@15m", "판단 보류", "1차", 0.4, 0.9, json.dumps({"trades_total": 12, "equity": 5100.0, "reason": "거래 30건 미만"})))
    c.commit()
    c.close()


def make_inbox(path):
    conn = R.open_inbox_rw(path)
    R.add_owner_message(conn, "team:lead", "owner1", "오늘 요약 부탁해요 " + SECRET_TEXT, ts=START + 21 * 3_600_000)
    R.add_approval(conn, 1, "reject", "owner1", "아직", ts=START + 22 * 3_600_000)
    conn.close()


def make_repo(root: Path, secrets=True) -> Path:
    def w(rel, text):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p
    extra = ("\n서버 설정은 /etc/paperbot/live.env 에 있고 토큰 " + SECRETS[1] + " 입니다. [[링크]] #해시태그\n") if secrets else ""
    p = w("docs/paper-v3-rules.md", "# 규칙 본문\n\n## 결론\n- 손절 2 ATR\n" + extra)
    (root / "docs/paper-v3-rules.sha256").write_text(hashlib.sha256(p.read_bytes()).hexdigest() + "  docs/paper-v3-rules.md\n")
    w("docs/paper-v3-rules-change-1.md", "# 변경 1\n\n레버리지 규칙 B\n")
    (root / "docs/paper-v3-rules-change-1.sha256").write_text("0" * 64 + "  docs/paper-v3-rules-change-1.md\n")
    w("docs/levrule-eval.md", "# 평가\n\n방법\n")
    w("research/strategy_profiles/PROFILES.md",
      "# 카드\n\n## 먼저 알아둘 것\n- 냉정하게\n\n## 슈퍼트렌드·ROC (S2_ST_ROC)\n\n- 성격: **추세 따라가기** (추세 비율 0.80) · 차이 없음\n"
      "- 5년 기준 가장 덜 나쁜 봉: 1시간\n\n| 봉 | 하루 신호 | 평균 ROE |\n|---|---|---|\n| 5분 | 1.0 | -5% |\n| 15분 | 0.5 | -3% |\n")
    w("research/famous/RESULTS_FAMOUS.md", "# 유명 매매법\n\n## 한 줄 결론\n**대부분 마이너스.** S2_ST_ROC 포함\n")
    w("research/deepseek200/CLASSIFICATION.md", "# 200개 분류\n\n## 요약\nA 12개\n")
    w("research/exitstyle/out/SUMMARY_KO.md", "# 익절 방식\n\n## 한 줄 결론\n계단 잠금 유지\n")
    return root


@pytest.fixture
def world(tmp_path):
    w = {"dir": tmp_path, "paper": str(tmp_path / "paper3.db"), "daily": str(tmp_path / "daily3.db"),
         "agents": str(tmp_path / "agents3.db"), "cp": str(tmp_path / "checkpoint.db"), "inbox": str(tmp_path / "inbox.db"),
         "repo": str(make_repo(tmp_path / "repo")), "out": str(tmp_path / "vault")}
    make_paper(w["paper"])
    make_daily(w["daily"])
    make_agents(w["agents"])
    make_checkpoint(w["cp"])
    make_inbox(w["inbox"])
    return w


def run(w, **kw):
    args = dict(paper_db=w["paper"], daily_db=w["daily"], agents_db=w["agents"], checkpoint_db=w["cp"],
                inbox_db=w["inbox"], repo_dir=w["repo"], now_ms=NOW)
    args.update(kw)
    return X.build(w["out"], **args)


def vault_files(out):
    res = {}
    for root, dirs, files in os.walk(out):
        for f in files:
            p = os.path.join(root, f)
            res[os.path.relpath(p, out).replace(os.sep, "/")] = open(p, "rb").read()
    return res


def md_files(out):
    return {p: b.decode("utf-8") for p, b in vault_files(out).items()
            if p.endswith(".md") and not p.startswith(".") and not p.startswith("99 ")}


# ------------------------------------------------------------------ structure
def test_tree_has_the_folders_and_the_key_notes(world):
    rep = run(world)
    assert rep["broken_links"] == 0 and rep["written"]
    files = vault_files(world["out"])
    for folder in ("00 홈", "01 실험", "02 매매법", "03 직원", "04 회의", "05 교훈·가설", "06 연구", "07 매일 점검", "08 규칙·문서", "99 내 메모"):
        assert any(p.startswith(folder + "/") for p in files), folder
    for p in ("00 홈/홈.md", "00 홈/읽는 법.md", "00 홈/시스템 지도.md", "00 홈/시스템 지도.canvas", "01 실험/타임라인.md", "01 실험/레버리지 계단.md",
              "01 실험/체크포인트 판정.md", "02 매매법/매매법 목록.md", "02 매매법/동전 던지기 봇.md", "03 직원/직원 목록.md",
              "03 직원/조직도.md", "03 직원/조직도.canvas", "03 직원/직원 성적표.md", "04 회의/회의 목록.md", "05 교훈·가설/교훈과 가설.md",
              "05 교훈·가설/시험 장부.md", "05 교훈·가설/가설 장부.md", "06 연구/연구 지도.md", "07 매일 점검/매일 점검 목록.md",
              "08 규칙·문서/규칙 문서 목록.md", "99 내 메모/메모 시작.md", ".obsidian/graph.json", ".obsidian/snippets/paperbot.css",
              ".obsidian/snippets/paperbot-palette.css", X.MANIFEST):
        assert p in files, p
    v4 = ("02 매매법/딥시크/", "02 매매법/릴스 5분 단타.md", "02 매매법/딥시크·릴스.md")
    assert sum(p.startswith("02 매매법/") and "매매법 목록" not in p and "동전" not in p and "추가" not in p
               and not p.startswith(v4) for p in files) == 36
    # paper v4 (A2): one note per DeepSeek family, the reel's note and their hub; the five group specialists
    assert sum(p.startswith("02 매매법/딥시크/") for p in files) == 17
    assert "02 매매법/릴스 5분 단타.md" in files and "02 매매법/딥시크·릴스.md" in files
    assert sum(p.startswith("03 직원/역할/") for p in files) == len(ROLES) + len(GROUP_SPECIALISTS) == 41
    assert sum(p.startswith("03 직원/팀/") for p in files) == len(TEAMS) == 12
    assert "04 회의/일일/회의 2026-10-06.md" in files and "07 매일 점검/일일/점검 2026-10-06.md" in files
    assert any(p.startswith("04 회의/주간/") for p in files)
    assert "08 규칙·문서/규칙 본문 v3.md" in files and "06 연구/DeepSeek 200개 분류.md" in files


def test_every_wikilink_resolves(world):
    run(world)
    files = vault_files(world["out"])
    assert X.broken_links({p: b for p, b in files.items() if not p.startswith("99 ")}) == []
    # the checker does see a broken link
    assert X.broken_links({"a.md": "[[없는 노트]] `[[코드 안]]`\n```\n[[펜스 안]]\n```\n".encode(), "b.md": b"x"}) == [("a.md", "없는 노트")]
    assert X.broken_links({"a.md": "| [[b\\|별칭]] |".encode(), "b.md": b"x"}) == []


def test_front_matter_is_valid_yaml_with_the_properties(world):
    yaml = pytest.importorskip("yaml")
    run(world)
    seen = set()
    for p, t in md_files(world["out"]).items():
        m = re.match(r"\A---\n(.*?)\n---\n", t, re.S)
        assert m, p
        fm = yaml.safe_load(m.group(1))
        assert isinstance(fm, dict) and fm["type"] and isinstance(fm["tags"], list) and fm["tags"], p
        assert fm["source"] in ("code", "ai", "mixed", "doc") and isinstance(fm["cssclasses"], list), p
        seen.add(fm["type"])
    assert {"허브", "전략", "회의", "교훈", "가설", "연구", "규칙", "직원", "점검", "시험", "실험"} <= seen
    t = md_files(world["out"])["02 매매법/S2_ST_ROC 슈퍼트렌드·ROC.md"]
    fm = yaml.safe_load(re.match(r"\A---\n(.*?)\n---\n", t, re.S).group(1))
    assert fm["strategy"] == "S2_ST_ROC" and fm["n_trades"] == 12 and fm["small_sample"] is False
    assert fm["timeframe"] == ["15m", "30m", "1h", "4h"] and "전략" in fm["tags"]
    t = md_files(world["out"])["02 매매법/N22_VORTEX_PSAR 볼텍스·PSAR.md"]
    assert yaml.safe_load(re.match(r"\A---\n(.*?)\n---\n", t, re.S).group(1))["small_sample"] is True
    # tiny fallback check that does not need PyYAML: every front matter line is key: value
    for p, t in md_files(world["out"]).items():
        head = re.match(r"\A---\n(.*?)\n---\n", t, re.S).group(1)
        assert all(re.match(r"^[A-Za-z_0-9]+: \S", ln) for ln in head.split("\n")), p


KNOWN_DIAGRAMS = ("flowchart", "gantt", "pie", "graph", "sequenceDiagram")


def test_mermaid_blocks_are_well_formed(world):
    run(world)
    n = 0
    for p, t in md_files(world["out"]).items():
        assert t.count("```") % 2 == 0, p
        for m in re.finditer(r"^```mermaid\n(.*?)\n```$", t, re.S | re.M):
            n += 1
            code = m.group(1)
            first = code.split()[0]
            assert first in KNOWN_DIAGRAMS, (p, first)
            if first == "gantt":
                assert "dateFormat" in code and re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", code), p
            if first == "flowchart":
                assert code.count("[") == code.count("]") and code.count("(") == code.count(")") and code.count("{") == code.count("}"), p
                assert code.count('"') % 2 == 0, p
                if "subgraph" in code:
                    assert code.count("subgraph") == len(re.findall(r"^\s*end\s*$", code, re.M)), p
    assert n >= 5          # org chart, ladder, timeline gantt, data flow (home and system map), pie


def test_canvas_and_obsidian_json_are_valid(world):
    run(world)
    files = vault_files(world["out"])
    for p, b in files.items():
        if p.endswith(".canvas"):
            c = json.loads(b)
            ids = {n["id"] for n in c["nodes"]}
            assert len(ids) == len(c["nodes"]) and c["nodes"]
            for e in c["edges"]:
                assert e["fromNode"] in ids and e["toNode"] in ids
            for n in c["nodes"]:
                assert {"id", "type", "x", "y", "width", "height"} <= set(n)
                if n["type"] == "file":
                    assert n["file"] in files, n["file"]
    for p, b in files.items():
        if p.startswith(".obsidian/") and p.endswith(".json"):
            json.loads(b)
    g = json.loads(files[".obsidian/graph.json"])
    assert g["colorGroups"][0]["query"] == "tag:#허브" and all(isinstance(x["color"]["rgb"], int) for x in g["colorGroups"])
    assert len({x["color"]["rgb"] for x in g["colorGroups"]}) == len(g["colorGroups"])
    ap = json.loads(files[".obsidian/appearance.json"])
    assert ap["theme"] == "obsidian" and ap["cssTheme"] == ""
    for s in ap["enabledCssSnippets"]:
        assert f".obsidian/snippets/{s}.css" in files
    cp = json.loads(files[".obsidian/core-plugins.json"])
    assert all(cp[k] for k in ("graph", "backlink", "outgoing-link", "tag-pane", "properties", "global-search", "canvas", "outline")) \
        and cp["daily-notes"] is False
    css = files[".obsidian/snippets/paperbot.css"].decode()
    assert css.count("{") == css.count("}") and "--ctp-mauve" in css and ".theme-light" in css and "#1e1e2e" in files[".obsidian/snippets/paperbot-palette.css"].decode()
    assert "AnuPpuccin" in css and "pb-hero" in css
    # the graph colours are the Catppuccin Mocha ones of the CSS
    assert {x["color"]["rgb"] for x in g["colorGroups"]} <= {U.rgb_int(v) for v in U.MOCHA.values()}


# ------------------------------------------------------------------ content and honesty
def test_numbers_flags_and_labels(world):
    run(world)
    md = md_files(world["out"])
    s2 = md["02 매매법/S2_ST_ROC 슈퍼트렌드·ROC.md"]
    assert "| 15분 | 운영 중 | $5,100 |" in s2 and "| 12 |" in s2 and "코드 계산" in s2 and "AI 작성" in s2
    assert "좋은 자리 (best)" in s2 and "그림자 비교" in s2 and "`lock15` 첫 잠금 15%" in s2 and "| 6 |" in s2
    assert "| 5분 |" not in s2 and "| 15분 | 0.5 | -3% |" in s2                   # the removed 5-minute row is left out
    assert "30일 체크포인트" in s2 and "결론 아님" in s2
    n22 = md["02 매매법/N22_VORTEX_PSAR 볼텍스·PSAR.md"]
    assert "표본 적음 (3건 < 10)" in n22
    meet = md["04 회의/일일/회의 2026-10-06.md"]
    assert "AI 작성" in meet and "코드 집계" in meet and "[[02 매매법" not in meet
    assert "[[S2_ST_ROC 슈퍼트렌드·ROC|슈퍼트렌드·ROC]]" in meet and "총괄" not in meet.split("회의 한눈에")[0]
    assert "…(이하 생략)" in meet or "…" in meet                                       # the long summary is cut
    assert max(len(s) for s in meet.split("\n")) < 2000
    for p, t in md.items():
        assert re.search(r'<div class="pb-stamp">자동 생성 \d{4}-\d{2}-\d{2} \d{2}:\d{2} KST · 자료 기준 ', t), p
    home = md["00 홈/홈.md"]
    assert "30일 전에는 결론이 없습니다" in home and "4일째 / 30일" in home and "2026-10-26" in home and "2026-11-04" in home
    tl = md["01 실험/타임라인.md"]
    assert "2026-10-05 10:46" in tl and "2026-10-26 10:46" in tl and "2026-11-04 09:00" in tl
    ladder = md["01 실험/레버리지 계단.md"]
    assert "50배 · 증거금 50%" in ladder and "30배 · 증거금 30%" in ladder
    cp = md["01 실험/체크포인트 판정.md"]
    assert "2026-11-04" in cp and "판단 보류" in cp
    daily = md["07 매일 점검/일일/점검 2026-10-07.md"]
    assert "paper와 재계산이 다릅니다" in daily
    assert "paper와 재계산이 일치합니다" in md["07 매일 점검/일일/점검 2026-10-06.md"]
    rules = md["08 규칙·문서/규칙 본문 v3.md"]
    assert "해시 확인: 일치" in rules and "해시 확인: 불일치" in md["08 규칙·문서/규칙 변경 1 (2026-10-04).md"]
    assert "해시 파일 없음" in md["08 규칙·문서/레버리지 규칙 B 평가 방법.md"]
    assert "[[가짜 링크]]" not in "".join(md.values()) and "[[링크]]" not in "".join(md.values())


def test_hypotheses_trials_and_multiple_testing_count(world):
    run(world)
    md = md_files(world["out"])
    led = md["05 교훈·가설/가설 장부.md"]
    assert "승률이 50%를 넘을 것" in led and "맞음" in led and "표본 적음" in led and "채점 안 함" in led
    hyp = [p for p in md if p.startswith("05 교훈·가설/가설/")]
    assert len(hyp) == 2
    h = md["05 교훈·가설/가설/가설 0001 S2_ST_ROC.md"]
    assert "측정 0.580 (거래 30건)" in h and "AI 작성" in h and "코드가 채점" in h
    tri = md["05 교훈·가설/시험 장부.md"]
    assert "새 매매법 시험은 모든 방을 합쳐 지금까지 **1번**" in tri and "0.0250" in tri and "5년 시험(copy" not in tri
    assert "blocked_gate" in tri and "reject" in tri
    deb = md["05 교훈·가설/낙관·비관 토론 채점.md"]
    assert "채점 1개 중 1개 맞음" in deb and "표본이 적어" in deb
    sc = md["03 직원/직원 성적표.md"]
    assert "표본 적음" in sc
    les = md["05 교훈·가설/교훈/교훈 2026-10-06.md"]
    assert "횡보장 진입 손실" in les and "AI 작성" in les


def test_no_secrets_anywhere_in_the_vault(world):
    run(world)
    blob = "\n".join(b.decode("utf-8", "replace") for p, b in vault_files(world["out"]).items() if not p.startswith("99 "))
    for s in SECRETS:
        assert s not in blob, s
    for pat in (r"sk-[A-Za-z0-9_\-]{12,}", r"\b\d{6,}:[A-Za-z0-9_\-]{30,}", r"\b(?:\d{1,3}\.){3}\d{1,3}\b", r"/etc/paperbot",
                r"/etc/", r"(?i)chat[_ ]?id\D{0,4}-?\d{6,}", r"-100\d{8,}", r"[\w.]+@example\.com", r"(?i)token\s*=\s*\w{8,}"):
        assert not re.search(pat, blob), pat
    assert "[비밀값 삭제]" in blob and "[서버 경로 삭제]" in blob and "[IP 삭제]" in blob


def test_redact_unit():
    t = U.redact("키 sk-ant-api03-abcdefghijk12345 토큰 987654321:AAH1234567890abcdefghijklmnopqrstuvw 서버 10.1.2.3 /etc/paperbot/x.env "
                 "/var/lib/paperbot/paper3.db chat_id=-1009876543210 api_key = abcdef123456 BTC 84433.0 V3.9 S2_ST_ROC@15m")
    assert not re.search(r"sk-ant|987654321|10\.1\.2\.3|/etc/|/var/lib|1009876543210|abcdef123456", t)
    assert "84433.0" in t and "V3.9" in t and "S2_ST_ROC@15m" in t
    assert U.sanitize("[[a]] #tag ``` x") == "[ [a] ] \\#tag ''' x"


# ------------------------------------------------------------------ the writer
def test_user_files_and_unknown_files_are_never_touched(world):
    out = Path(world["out"])
    (out / "99 내 메모").mkdir(parents=True)
    mine = out / "99 내 메모" / "내 글.md"
    mine.write_text("소중한 글", encoding="utf-8")
    other = out / "뭔가.txt"
    other.write_text("keep", encoding="utf-8")
    colliding = out / "00 홈" / "홈.md"                 # the owners already had a note with a generated name
    colliding.parent.mkdir(parents=True)
    colliding.write_text("내 홈 노트", encoding="utf-8")
    obs = out / ".obsidian"
    obs.mkdir()
    (obs / "appearance.json").write_text('{"theme":"moonstone","cssTheme":"AnuPpuccin"}', encoding="utf-8")
    rep = run(world)
    assert "00 홈/홈.md" in rep["skipped_user_file"] and ".obsidian/appearance.json" in rep["skipped_user_file"]
    assert mine.read_text(encoding="utf-8") == "소중한 글" and other.read_text(encoding="utf-8") == "keep"
    assert colliding.read_text(encoding="utf-8") == "내 홈 노트"
    assert json.loads((obs / "appearance.json").read_text())["cssTheme"] == "AnuPpuccin"
    assert (obs / "graph.json").exists()                  # a missing .obsidian file is created
    # second run: owners add a file inside a generated folder and edit a generated note; both survive
    extra = out / "02 매매법" / "내가 만든 매매법 메모.md"
    extra.write_text("메모", encoding="utf-8")
    note = out / "02 매매법" / "S2_ST_ROC 슈퍼트렌드·ROC.md"
    note.write_text(note.read_text(encoding="utf-8") + "\n내 필기\n", encoding="utf-8")
    rep = run(world, now_ms=NOW + 3600_000)
    assert "02 매매법/S2_ST_ROC 슈퍼트렌드·ROC.md" in rep["kept_user_edit"] and "내 필기" in note.read_text(encoding="utf-8")
    assert extra.read_text(encoding="utf-8") == "메모" and mine.read_text(encoding="utf-8") == "소중한 글"
    man = json.loads((out / X.MANIFEST).read_text())
    assert not any(p.startswith("99 ") for p in man["files"]) and "02 매매법/내가 만든 매매법 메모.md" not in man["files"]
    st = X.status(world["out"])
    assert st["edited_by_owners"] == ["02 매매법/S2_ST_ROC 슈퍼트렌드·ROC.md"] and st["owner_files_in_99"] == 1


def test_99_folder_is_created_once_and_never_rewritten(world):
    run(world)
    p = Path(world["out"]) / "99 내 메모" / "메모 시작.md"
    assert p.exists()
    p.write_text("고침", encoding="utf-8")
    run(world, now_ms=NOW + 10)
    assert p.read_text(encoding="utf-8") == "고침"
    p.unlink()                                             # the owners may delete it; it is not made again
    run(world, now_ms=NOW + 20)
    assert not p.exists() and (Path(world["out"]) / "99 내 메모").is_dir()


def test_second_run_is_idempotent_and_only_the_time_line_differs(world):
    run(world)
    first = vault_files(world["out"])
    stamps = {p: os.stat(os.path.join(world["out"], p)).st_mtime_ns for p in first}
    time.sleep(0.02)
    rep = run(world, now_ms=NOW + 5 * 3600_000)             # later: only the generation-time line would change
    assert rep["written"] == [] and rep["removed"] == [] and len(rep["unchanged"]) == rep["files"]
    after = vault_files(world["out"])
    assert after == first
    assert all(os.stat(os.path.join(world["out"], p)).st_mtime_ns == stamps[p] for p in first)
    # the bytes are a function of the input: a fresh vault built at another time differs only in the time line
    other = Path(world["dir"]) / "vault2"
    X.build(str(other), paper_db=world["paper"], daily_db=world["daily"], agents_db=world["agents"], checkpoint_db=world["cp"],
            inbox_db=world["inbox"], repo_dir=world["repo"], now_ms=NOW + 9 * 3600_000)
    second = vault_files(other)
    assert set(second) == set(first)
    for p in first:
        if p.startswith("99 ") or p == X.MANIFEST:
            continue
        a, b = first[p], second[p]
        assert X.strip_stamp(a) == X.strip_stamp(b), p
    changed = [p for p in first if p.endswith(".md") and not p.startswith("99 ") and first[p] != second[p]]
    assert changed and all("자동 생성" in first[p].decode() for p in changed)


def test_data_change_rewrites_only_what_changed(world):
    run(world)
    conn = R.open_agents(world["agents"])
    R.add_note(conn, "strat:S2_ST_ROC", "S2_ST_ROC", "새 교훈입니다", None, ts=START + 2 * DAY)
    conn.close()
    rep = run(world, now_ms=NOW + 3600_000)
    assert "05 교훈·가설/교훈/교훈 2026-10-07.md" in rep["written"]
    assert 0 < len(rep["written"]) < 20 and len(rep["unchanged"]) > 100


def test_obsolete_generated_files_are_removed_only_when_unmodified(world):
    run(world)
    out = Path(world["out"])
    man = json.loads((out / X.MANIFEST).read_text())
    man["files"]["02 매매법/옛 노트.md"] = hashlib.sha256(b"old").hexdigest()
    man["files"]["02 매매법/고친 옛 노트.md"] = hashlib.sha256(b"old2").hexdigest()
    (out / "02 매매법" / "옛 노트.md").write_bytes(b"old")
    (out / "02 매매법" / "고친 옛 노트.md").write_bytes(b"edited by owners")
    (out / X.MANIFEST).write_text(json.dumps(man))
    rep = run(world)
    assert rep["removed"] == ["02 매매법/옛 노트.md"] and rep["forgotten"] == ["02 매매법/고친 옛 노트.md"]
    assert not (out / "02 매매법" / "옛 노트.md").exists() and (out / "02 매매법" / "고친 옛 노트.md").exists()


def test_dry_run_writes_nothing(world, capsys):
    rep = run(world, dry_run=True)
    assert rep["dry_run"] and rep["written"] and not os.path.exists(world["out"])
    out = Path(world["out"])
    out.mkdir()
    (out / "x.md").write_text("a")
    before = vault_files(world["out"])
    run(world, dry_run=True)
    assert vault_files(world["out"]) == before
    code = X.main(["build", "--out", world["out"], "--paper-db", world["paper"], "--daily-db", world["daily"], "--agents-db", world["agents"],
                   "--checkpoint-db", world["cp"], "--inbox-db", world["inbox"], "--repo-dir", world["repo"], "--dry-run"])
    txt = capsys.readouterr().out
    assert code == 0 and "DRY RUN" in txt and "would write: 00 홈/홈.md" in txt
    assert vault_files(world["out"]) == before


def test_status_command(world, capsys):
    assert X.status(world["out"])["exists"] is False
    run(world)
    assert X.main(["status", "--out", world["out"]]) == 0
    st = json.loads(capsys.readouterr().out)
    assert st["generated_files"] > 100 and st["edited_by_owners"] == [] and st["sources"]["agents3"] is True


def test_databases_are_never_written(world):
    def digest(p):
        return hashlib.sha256(open(p, "rb").read()).hexdigest()
    before = {k: digest(world[k]) for k in ("paper", "daily", "agents", "cp", "inbox")}
    run(world)
    assert before == {k: digest(world[k]) for k in ("paper", "daily", "agents", "cp", "inbox")}
    # and the connections are read-only
    conn = R.open_ro(world["agents"])
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM notes")
    conn.close()


# ------------------------------------------------------------------ day 0, missing and broken inputs
def test_works_with_no_databases_at_all(tmp_path):
    out = str(tmp_path / "vault")
    rep = X.build(out, paper_db=None, daily_db=None, agents_db=None, checkpoint_db=None, inbox_db=None,
                  repo_dir=str(tmp_path / "norepo"), now_ms=NOW)
    assert rep["broken_links"] == 0 and rep["present"] == {k: False for k in rep["present"]}
    md = md_files(out)
    assert len([p for p in md if p.startswith("02 매매법/") and re.search(r"^02 매매법/(S|N|V|O|D)", p)]) >= 36
    home = md["00 홈/홈.md"]
    assert "30일 전에는 결론이 없습니다" in home and "아직 없음" in home
    assert "표본 적음" in md["02 매매법/S2_ST_ROC 슈퍼트렌드·ROC.md"] or "거래가 없" in md["02 매매법/S2_ST_ROC 슈퍼트렌드·ROC.md"]
    assert "예정 시각" in md["01 실험/타임라인.md"]
    assert "아직 판정이 없습니다" in md["01 실험/체크포인트 판정.md"]
    assert X.broken_links({p: b for p, b in vault_files(out).items() if not p.startswith("99 ")}) == []


def test_works_with_empty_schema_only_databases(tmp_path):
    p, d, a, c, i = (str(tmp_path / n) for n in ("paper3.db", "daily3.db", "agents3.db", "checkpoint.db", "inbox.db"))
    sqlite3.connect(p).executescript(PAPER_SCHEMA)
    from paperbot.daily3 import SCHEMA as DS
    from paperbot.checkpoint import SCHEMA as CS
    sqlite3.connect(d).executescript(DS)
    sqlite3.connect(c).executescript(CS)
    R.open_agents(a).close()
    R.open_inbox_rw(i).close()
    out = str(tmp_path / "vault")
    rep = X.build(out, paper_db=p, daily_db=d, agents_db=a, checkpoint_db=c, inbox_db=i, repo_dir=str(tmp_path), now_ms=NOW)
    assert rep["broken_links"] == 0 and all(rep["present"].values())
    assert "아직 회의가 없습니다" in md_files(out)["04 회의/회의 목록.md"] or "0번" in md_files(out)["04 회의/회의 목록.md"]


def test_a_garbage_database_file_counts_as_missing(tmp_path):
    bad = tmp_path / "paper3.db"
    bad.write_bytes(b"this is not a database" * 100)
    out = str(tmp_path / "vault")
    rep = X.build(out, paper_db=str(bad), daily_db=None, agents_db=None, checkpoint_db=None, inbox_db=None,
                  repo_dir=str(tmp_path), now_ms=NOW)
    assert rep["present"]["paper3"] is False and rep["broken_links"] == 0


def test_a_vanished_database_does_not_wipe_the_vault(world):
    run(world)
    first = vault_files(world["out"])
    os.remove(world["agents"])
    with pytest.raises(SystemExit) as e:
        run(world)
    assert "agents3" in str(e.value)
    assert vault_files(world["out"]) == first
    run(world, allow_empty=True)                         # the owners can force it


def test_staging_leftovers_are_cleaned(world):
    out = Path(world["out"])
    (out / X.STAGING).mkdir(parents=True)
    (out / X.STAGING / "junk").write_text("x")
    run(world)
    assert not (out / X.STAGING).exists()


# ------------------------------------------------------------------ size, speed, preview, constants
def test_runtime_and_size_bounds(world):
    t0 = time.time()
    rep = run(world)
    assert time.time() - t0 < 30
    total = sum(len(b) for b in vault_files(world["out"]).values())
    assert total < 3_000_000 and rep["largest"][0][0] < 120_000


def test_long_ai_text_is_cut_and_the_day_budget_holds(world):
    conn = R.open_agents(world["agents"])
    d = START + 2 * DAY
    for i in range(80):
        cur = conn.execute("INSERT INTO rounds (room_id, trigger, trigger_data, started_ts, status, decision, calls, tokens) VALUES (?,?,?,?,?,?,?,?)",
                           ("strat:S2_ST_ROC", "loss_cluster", json.dumps({"kst_day": "2026-10-08"}), d + i * 1000, "done",
                            json.dumps({"action": "note", "summary_ko": "결론 " * 400}), 2, 10))
        for k in range(5):
            R.post(conn, "strat:S2_ST_ROC", int(cur.lastrowid), "loss", "spec_S2_ST_ROC", None, "analysis", "아주 긴 글 " * 700, ts=d + i * 1000 + k)
    conn.close()
    run(world)
    t = md_files(world["out"])["04 회의/일일/회의 2026-10-08.md"]
    assert len(t) < 130_000 and "분량 한도로 생략" in t and "이하 생략" in t


def test_constants_follow_the_repo():
    from paperbot.agents import riskreward
    from paperbot.config import V4_ACCOUNTS, V4_GROUP_ACCOUNTS, V3_TRADE_TFS
    from paperbot.obsidian_sources import TFS
    assert TFS == V3_TRADE_TFS and U.SMALL_N == riskreward.SMALL_N == 10
    # paper v4 (G9): the export counts the v4 shape (config's computed totals; the home reads the accounts table)
    assert len(STRATEGY_KO) == 36 and V4_ACCOUNTS == sum(V4_GROUP_ACCOUNTS.values())
    assert N.OBSERVE_DAYS == 21 and N.PERIOD_DAYS == 30


class _Balanced(html.parser.HTMLParser):
    VOID = {"br", "hr", "meta", "link", "input", "img", "line", "path"}

    def __init__(self):
        super().__init__()
        self.stack = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append((tag, self.stack[-3:]))
        else:
            self.stack.pop()


def test_static_preview_has_home_strategy_and_graph(world, tmp_path):
    run(world)
    path = PV.render_preview(world["out"], str(tmp_path / "preview"))
    page = Path(path).read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>") and "홈" in page and "S2_ST_ROC" in page and "<svg" in page and "<circle" in page
    assert "#1e1e2e" in page and "#eff1f5" in page and "http" not in page.replace("https://cdn.jsdelivr.net/npm/mermaid", "")
    p = _Balanced()
    p.feed(page)
    assert p.errors == [] and p.stack == []
    assert "<script>alert" not in page


def test_real_data_sample_if_present(tmp_path):
    if not (SCRATCH / "paper3.db").exists():
        pytest.skip("no rehearsal databases here")
    out = str(tmp_path / "vault")
    t0 = time.time()
    rep = X.build(out, paper_db=str(SCRATCH / "paper3.db"), daily_db=str(SCRATCH / "daily3.db"), agents_db=str(SCRATCH / "agents3.db"),
                  checkpoint_db=str(SCRATCH / "checkpoint.db"), inbox_db=str(SCRATCH / "inbox.db"), repo_dir=str(REPO))
    assert time.time() - t0 < 120 and rep["broken_links"] == 0 and rep["notes"] > 150
    blob = "\n".join(t for t in md_files(out).values())
    assert not re.search(r"sk-ant|/etc/paperbot|\b(?:\d{1,3}\.){3}\d{1,3}\b", blob)
    rep2 = X.build(out, paper_db=str(SCRATCH / "paper3.db"), daily_db=str(SCRATCH / "daily3.db"), agents_db=str(SCRATCH / "agents3.db"),
                   checkpoint_db=str(SCRATCH / "checkpoint.db"), inbox_db=str(SCRATCH / "inbox.db"), repo_dir=str(REPO))
    assert rep2["written"] == []


def test_deploy_unit_and_timer():
    dep = REPO / "deploy"
    svc = (dep / "paperbot-obsidian.service").read_text(encoding="utf-8")
    tim = (dep / "paperbot-obsidian.timer").read_text(encoding="utf-8")
    for needle in ("Type=oneshot", "User=paperbot", "OnFailure=paperbot-failed@%n.service", "ProtectSystem=strict", "NoNewPrivileges=yes",
                   "PrivateNetwork=yes", "ReadOnlyPaths=", "-m paperbot.obsidian_export build --out /var/lib/paperbot/obsidian",
                   "InaccessiblePaths=-/etc/paperbot"):
        assert needle in svc, needle
    assert "EnvironmentFile" not in re.sub(r"(?m)^#.*$", "", svc)
    assert "OnCalendar=*-*-* 00:50:00 UTC" in tim and "Persistent=true" in tim and "WantedBy=timers.target" in tim
    assert "paperbot-agents.service" in svc


# ------------------------------------------------------------------ paper v4 groups (A2)
def test_group_rooms_and_meetings_have_korean_names_and_file_as_loss_meetings():
    from paperbot import obsidian_notes as N
    from paperbot import obsidian_notes_b as NB
    from paperbot.agents import rooms_db as R
    from paperbot.agents.triggers import GROUP_TRIGGERS
    assert set(N.GROUP_ROOM_TITLES) == set(R.GROUP_ROOMS) and N.GROUP_ROOM_TITLES == R.GROUP_ROOM_TITLES
    assert N.room_name_ko("team:ds_structure") == "구조·유동성 담당 방"
    assert NB.room_label("team:reel_5m") == "[[5분봉 단타 담당|5분봉 단타 담당 방]]"
    for t in GROUP_TRIGGERS:
        assert N.trigger_ko(t) != t and N.group_of(t) == "loss"


def test_plain_rules_cover_every_deepseek_definition_and_the_reel():
    from paperbot import obsidian_notes as N
    from paperbot.config import DS200_IDS
    pr = N.plain_rules()
    assert set(pr["defs"]) == set(DS200_IDS) and all(pr["defs"][d] for d in DS200_IDS)
    assert len(pr["families"]) == 17 and set(pr["names"]) == set(DS200_IDS)
    assert any("38.2%" in x for x in pr["defs"]["F16_FIB382"]) and not any("${" in x for v in pr["defs"].values() for x in v)
    assert len(pr["reel"]["lines"]) >= 3 and pr["reel"]["desc"]


def test_deepseek_family_notes_count_only_and_the_specialists_are_in_the_staff_notes(world):
    c = sqlite3.connect(world["paper"])
    c.execute("INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?)", ("F3_BOS@15m", "F3_BOS", "15m", "ds200", START, "paper-v4", None, "{}"))
    c.execute("INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?)", ("REEL_H1@5m", "REEL_H1", "5m", "reel", START, "paper-v4", None, "{}"))
    c.executemany("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, equity_after, data)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?)", [trade("F3_BOS", "15m", i, "normal", 777.77, 0.3) for i in range(2)])
    c.commit()
    c.close()
    rep = run(world)
    assert rep["broken_links"] == 0
    files = md_files(world["out"])
    f3 = files["02 매매법/딥시크/딥시크 F3 구조 돌파·공급수요.md"]
    assert "F3_BOS" in f3 and "오름 구조에서 마지막 스윙 고점" in f3 and "777" not in f3 and "$" not in f3
    assert "| 2 |" in f3 or "trades: 2" in f3
    assert "[[구조·유동성 담당]]" in f3 or "[[구조·유동성 담당|" in f3
    reel = files["02 매매법/릴스 5분 단타.md"]
    assert "200봉 평균선" in reel and "동전 던지기" in reel
    role = files["03 직원/역할/구조·유동성 담당.md"]
    assert "딥시크 F9" in role and "구조·유동성 담당 방" in role
    spec = files["03 직원/팀/" + next(n for t, n in TEAMS if t == "specialist").split(" ", 1)[-1] + ".md"]
    assert all(g[1] in spec for g in GROUP_SPECIALISTS)
    hub = files["02 매매법/딥시크·릴스.md"]
    assert "$" not in hub and "F17" in hub
