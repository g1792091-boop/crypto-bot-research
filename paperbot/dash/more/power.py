"""판정 감도 (30일 판정 화면, ranked #4 '30일 판정으로 알 수 있는 것'): how strict the verdict rule is. Read-only.

    GET /api/v4/power

From the committed Monte Carlo result research/power/out/power.json (research/power/power.py, version 2; the same
file the agents' meetings read through paperbot/agents/power.py): if an account had a true edge of +X net ROE per
trade, the chance it passes the first check by day 30 / 60 / 90 under the run's rule (the owners' D5 (b) "split"
scheme: the 36 at FDR 7 %, the reel alone at 0.5 %, 10,000 coin flips each), per timeframe. DeepSeek has no table:
one fixed line (agents/power.py deepseek_line_ko). The answer is small (5 timeframes x 5 edges x 3 numbers) and is
read again only when the file changes (mtime).
"""
from __future__ import annotations

import os
import threading
from typing import Optional

EDGES = (0.0, 0.01, 0.02, 0.05, 0.1)               # the page's rows: +0 / 1 / 2 / 5 / 10 % per trade
TFS = ("15m", "30m", "1h", "5m")                    # judged timeframes (4h is observation only)
SCHEME = "split"


def view(doc: Optional[dict], deepseek: str = "") -> dict:
    """power.json -> the page's answer; {"ready": False, "note"} when the file is missing or of another version."""
    if not isinstance(doc, dict) or doc.get("version") != 2:
        return {"ready": False, "note": "판정 감도 계산 파일이 없습니다 (research/power/out/power.json)"}
    key = f"scheme_{SCHEME}"
    res = doc.get("results") or {}
    tfs: dict = {}
    for tf in TFS:
        v = res.get(tf) or {}
        rows = []
        for r in v.get("rows") or []:
            e = r.get("edge_roe")
            if e is None or not any(abs(float(e) - x) < 1e-9 for x in EDGES) or key not in r:
                continue
            f = r[key]
            rows.append({"edge": float(e), "d30": f.get("p_pass1_by_d30", f.get("p_pass1_d30")),
                         "d60": f.get("p_pass1_by_d60"), "d90": f.get("p_pass1_by_d90")})
        if not rows:
            continue
        pool = v.get("pool") or {}
        tfs[tf] = {"rows": sorted(rows, key=lambda x: x["edge"]), "trades_per_30d": pool.get("trades_per_30d"),
                   "coin_flip_mean_roe": pool.get("coin_flip_mean_roe"), "reel": tf == "5m"}
    sc = (doc.get("schemes") or {}).get(SCHEME) or {}
    rsc = (doc.get("reel_schemes") or {}).get(SCHEME) or {}
    if not tfs:
        return {"ready": False, "note": f"판정 감도 파일에 '{SCHEME}' 방식 행이 없습니다"}
    return {"ready": True, "generated": doc.get("generated"), "scheme": SCHEME, "edges": list(EDGES), "tfs": tfs,
            "core": {"family": sc.get("family"), "alpha": sc.get("alpha"), "n_bots": sc.get("n_bots")},
            "reel": {"family": rsc.get("family"), "alpha": rsc.get("alpha"), "n_bots": rsc.get("n_bots")},
            "checkpoints": doc.get("checkpoints") or [30, 60, 90],
            "deepseek": deepseek,
            "assumptions": [str(a) for a in (doc.get("assumptions") or [])][:8],
            "note": ("코드 계산(몬테카를로): 거래는 서로 독립, 엣지는 모든 거래에 같음, 다른 계좌는 엣지 없음, 동전 봇 거래 모양은 "
                     "2020-21 자료. 판정 규칙이 얼마나 엄격한지 보여 줄 뿐 판정이 아닙니다.")}


def register(app, ctx) -> dict:
    from ...agents import power as P
    path = getattr(ctx, "power_json", None) or P.POWER_JSON
    cache: dict = {}
    lock = threading.Lock()

    @app.get("/api/v4/power")
    def get_power():
        """The verdict rule's power per true edge and timeframe (research/power/out/power.json), re-read on change."""
        from ..app import json_finite
        try:
            mt = os.path.getmtime(path)
        except OSError:
            mt = None
        hit = cache.get("v")
        if hit and hit[0] == mt:
            return hit[1]
        with lock:
            v = json_finite(view(P.load(path) if mt is not None else None, P.deepseek_line_ko()))
            cache["v"] = (mt, v)
        return v

    return {"routes": ["/api/v4/power"], "cache": cache}
