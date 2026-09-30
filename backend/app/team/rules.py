"""AI 키가 없거나 AI 가 실패했을 때: 같은 출력 형식을 규칙으로 만든다 (근거 경로도 똑같이 단다)."""
from __future__ import annotations

NAME = {"long": "롱", "short": "숏", "both": "양방향", "none": "쉬기", "neutral": "중립"}


def _c(s: str) -> str:
    return s.replace("USDT", "")


def _f(claim, ev, kind="fact", sev="info"):
    return {"claim": claim, "kind": kind, "severity": sev, "evidence": ev if isinstance(ev, list) else [ev]}


def _bias(m: dict) -> str:
    r = m.get("regime") or {}
    s = sum((r.get(tf) or {}).get("score", 0) * w for tf, w in (("15m", .15), ("1h", .3), ("4h", .35), ("1d", .2)))
    return "long" if s >= 25 else "short" if s <= -25 else "neutral"


def chart(g):
    F, calls = [], []
    for s, m in (g.get("market") or {}).items():
        if "regime" not in m:
            continue
        b = _bias(m)
        tfs = " · ".join(f"{tf} {v['label']}" for tf, v in m["regime"].items())
        F.append(_f(f"{_c(s)}: {tfs} (ATR {m.get('atr_1h_pct')}%)", [f"market.{s}.regime", f"market.{s}.atr_1h_pct"],
                    "fact", "warn" if b == "neutral" else "info"))
        calls.append({"symbol": s, "bias": b, "evidence": [f"market.{s}.regime"]})
    lo = [c["symbol"] for c in calls if c["bias"] == "long"]
    sh = [c["symbol"] for c in calls if c["bias"] == "short"]
    head = f"롱 우위 {len(lo)} · 숏 우위 {len(sh)} · 중립 {len(calls) - len(lo) - len(sh)}"
    msg = f"여러 봉을 합친 장세입니다. {head}." + (f" 롱 쪽은 {', '.join(map(_c, lo))}." if lo else "") + (f" 숏 쪽은 {', '.join(map(_c, sh))}." if sh else "") \
        + " @전략가 여러 봉이 엇갈리는 코인은 쉬는 게 좋겠습니다."
    return {"message": msg, "headline": head, "findings": F, "calls": calls, "proposals": [], "data_gaps": []}


def flow(g):
    F = []
    for s, d in (g.get("flow") or {}).items():
        fr = d.get("funding_pct")
        if fr is not None and abs(fr) >= 0.03:
            F.append(_f(f"{_c(s)} 펀딩비 {fr:+.3f}% — {'롱' if fr > 0 else '숏'} 쏠림, 반대 급변 주의", f"flow.{s}.funding_pct", "fact", "warn"))
        oi = d.get("oi_change_24h_pct")
        if oi is not None and abs(oi) >= 5:
            F.append(_f(f"{_c(s)} 미결제약정 24시간 {oi:+.1f}% — 새 포지션이 {'많이 들어옴' if oi > 0 else '많이 빠짐'}", f"flow.{s}.oi_change_24h_pct"))
        im = d.get("ob_imbalance_0_5pct")
        if im is not None and abs(im) >= 0.2:
            F.append(_f(f"{_c(s)} 호가 ±0.5% 불균형 {im * 100:+.0f}% ({'매수' if im > 0 else '매도'} 호가가 두꺼움)", f"flow.{s}.ob_imbalance_0_5pct", "hypothesis"))
        ht = d.get("hyperliquid_top")
        if ht and ht.get("long_share_pct") is not None and (ht["long_share_pct"] >= 70 or ht["long_share_pct"] <= 30):
            F.append(_f(f"{_c(s)} Hyperliquid 고수 금액의 {ht['long_share_pct']}%가 롱", f"flow.{s}.hyperliquid_top.long_share_pct", "hypothesis"))
    hot = [f for f in F if f["severity"] == "warn"]
    head = f"과열·쏠림 경고 {len(hot)}건" if hot else "뚜렷한 과열 없음"
    return {"message": head + ("." if not hot else f" — {hot[0]['claim']}. @리스크 책임자 참고해 주세요."), "headline": head,
            "findings": F, "calls": [], "proposals": [], "data_gaps": [] if F else ["파생 데이터가 비었거나 변화가 작음"]}


def macro(g):
    m, F = g.get("macro") or {}, []
    for s, c in (m.get("corr_btc_60d") or {}).items():
        if c is not None and c >= 0.8:
            F.append(_f(f"{_c(s)} 는 BTC 와 상관 {c} — 같은 방향 동시 진입은 사실상 한 번의 큰 베팅", f"macro.corr_btc_60d.{s}", "fact", "warn"))
    rk = m.get("rank_7d") or []
    if rk:
        F.append(_f(f"7일 상대강도 1위 {_c(rk[0])}, 꼴찌 {_c(rk[-1])}", ["macro.rank_7d.0", f"macro.rank_7d.{len(rk) - 1}"]))
    fg = m.get("fear_greed") or {}
    if fg.get("value") is not None:
        F.append(_f(f"공포·탐욕 지수 {fg['value']} ({fg.get('label') or ''})", "macro.fear_greed.value"))
    head = f"코인끼리 상관이 높은 쌍 {sum(f['severity'] == 'warn' for f in F)}개" if F else "매크로 데이터 부족"
    return {"message": head + (f", 강한 쪽은 {_c(rk[0])}." if rk else "."), "headline": head, "findings": F, "calls": [], "proposals": [],
            "data_gaps": [] if F else ["도미넌스·공포탐욕 데이터 없음"]}


def news(g):
    n, F = g.get("news") or {}, []
    for i, e in enumerate(n.get("events") or []):
        F.append(_f(f"{e['in_hours']}시간 뒤 {e['title']} — 발표 전후 변동성 확대", f"news.events.{i}.title", "fact", "warn"))
    keys = ("hack", "해킹", "SEC", "ETF", "규제", "ban", "exploit", "상장폐지", "delist", "liquidat")
    for i, h in enumerate(n.get("headlines") or []):
        if any(k.lower() in h.lower() for k in keys):
            F.append(_f(f"주목할 헤드라인: {h[:90]}", f"news.headlines.{i}", "hypothesis", "warn"))
    head = f"24~48시간 일정 {len(n.get('events') or [])}건 · 주목 헤드라인 {sum(1 for f in F if '헤드라인' in f['claim'])}건"
    return {"message": head + ".", "headline": head, "findings": F[:8], "calls": [], "proposals": [],
            "data_gaps": [] if n.get("headlines") else ["헤드라인을 불러오지 못함"]}


def analog(g):
    F = []
    for s, a in (g.get("analog") or {}).items():
        if a.get("prob_up") is None:
            continue
        F.append(_f(f"{_c(s)} 과거 비슷한 구간 {a['horizon_bars']}봉 뒤 상승 {a['prob_up']}%, 중간값 {a['median_ret_pct']:+.2f}% (신뢰도 {a['reliability']})",
                    [f"analog.{s}.prob_up", f"analog.{s}.reliability"], "hypothesis"))
    return {"message": "과거 유사 구간 분포입니다. 기준률로만 참고하세요 (신호 아님).", "headline": f"{len(F)}개 코인 유사 패턴 분포",
            "findings": F, "calls": [], "proposals": [], "data_gaps": []}


def strategist(g):
    rows, focus = [], []
    calls = {c["symbol"]: c["bias"] for c in ((g.get("analysts") or {}).get("chart") or {}).get("calls", [])}
    for s, m in (g.get("market") or {}).items():
        if "regime" not in m:
            continue
        b = calls.get(s) or _bias(m)
        v = (m.get("verdict") or {}).get("score", 0)
        d = "none"
        if b == "long" and v > -25:
            d = "long"
        elif b == "short" and v < 25:
            d = "short"
        rows.append({"symbol": s, "direction": d, "reason": f"장세 {NAME[b]}, 종합 판단 {m.get('verdict', {}).get('label', '-')}",
                     "evidence": [f"market.{s}.regime", f"market.{s}.verdict"] if m.get("verdict") else [f"market.{s}.regime"]})
    for name, b in (g.get("bots") or {}).items():
        focus.append(f"봇 {name}: {b['symbol']} {b['interval']} — {'가동 중' if b['running'] else '정지'}")
    act = [f"{_c(r['symbol'])} {NAME[r['direction']]}" for r in rows if r["direction"] != "none"]
    msg = ("오늘 허용범위 초안입니다: " + (", ".join(act) if act else "모든 코인 쉬기") + ". 장세와 종합 판단이 같은 방향일 때만 열었습니다. @반론 검토관 반대 근거 부탁합니다.")
    return {"message": msg, "headline": f"허용 {len(act)}개 코인", "allowed": rows, "focus": focus, "findings": [], "data_gaps": []}


def critic(g):
    F = []
    st = g.get("strategist") or {}
    mk = g.get("market") or {}
    for i, a in enumerate(st.get("allowed") or []):
        s, m = a["symbol"], mk.get(a["symbol"]) or {}
        if a["direction"] in ("long", "short"):
            r1 = (m.get("regime") or {}).get("15m", {}).get("score", 0)
            if (a["direction"] == "long" and r1 < 0) or (a["direction"] == "short" and r1 > 0):
                F.append(_f(f"{_c(s)} {NAME[a['direction']]} 허용인데 15분봉은 반대 ({r1:+d}) — 단기 진입 타이밍이 나쁨", [f"strategist.allowed.{i}.direction", f"market.{s}.regime.15m.score"], "hypothesis", "warn"))
            rsi = m.get("rsi_1h")
            if rsi is not None and ((a["direction"] == "long" and rsi >= 70) or (a["direction"] == "short" and rsi <= 30)):
                F.append(_f(f"{_c(s)} 1시간 RSI {rsi} — 이미 많이 간 자리", [f"strategist.allowed.{i}.direction", f"market.{s}.rsi_1h"], "hypothesis", "warn"))
    for s, m in mk.items():
        if m.get("atr_1h_pct") and m["atr_1h_pct"] >= 1.2:
            F.append(_f(f"{_c(s)} 1시간 ATR {m['atr_1h_pct']}% — 변동이 커서 손절이 쉽게 닿음", f"market.{s}.atr_1h_pct", "fact", "warn"))
    if len(F) < 3:
        for s, m in list(mk.items())[:3 - len(F)]:
            if m.get("verdict"):
                F.append(_f(f"{_c(s)} 종합 판단 근거 일치 {m['verdict']['agree']} — 근거가 모두 한쪽은 아님", f"market.{s}.verdict.agree", "hypothesis"))
    return {"message": f"@전략가 반론 {len(F)}개입니다. " + (F[0]["claim"] if F else "") + ".", "headline": f"반론 {len(F)}개",
            "findings": F, "calls": [], "proposals": [], "data_gaps": []}


def risk(g):
    st, bk = g.get("strategist") or {}, g.get("book") or {}
    F, decs, acts = [], [], []
    lvl = "normal"
    dd = bk.get("max_drawdown_pct")
    if dd is not None and dd >= 20:
        lvl = "danger" if dd >= 40 else "caution"
        F.append(_f(f"내 계좌 최대 낙폭 {dd}%", "book.max_drawdown_pct", "fact", "warn"))
    for i, p in enumerate(bk.get("positions") or []):
        if not p.get("stop"):
            lvl = "caution" if lvl == "normal" else lvl
            F.append(_f(f"{_c(p['symbol'])} {NAME[p['side']]} {p['leverage']}배 포지션에 손절 없음", f"book.positions.{i}.stop", "fact", "warn"))
            acts.append({"action": "reduce", "target": p["symbol"], "reason": "손절 없는 포지션 — 손절을 걸거나 줄이세요", "evidence": [f"book.positions.{i}.stop"]})
    tod = bk.get("today") or {}
    if tod.get("max_losing_streak", 0) >= 3:
        lvl = "caution" if lvl == "normal" else lvl
        F.append(_f(f"오늘 최대 연속 손실 {tod['max_losing_streak']}번", "book.today.max_losing_streak", "fact", "warn"))
    crit = [f for a in (g.get("analysts") or {}).values() for f in a.get("findings", []) if f.get("severity") == "critical"]
    if crit:
        lvl = "danger"
    for i, a in enumerate(st.get("allowed") or []):
        decs.append({"symbol": a["symbol"], "direction": a["direction"] if lvl != "danger" else "none",
                     "reason": "승인" if lvl != "danger" else "위험 수준 — 모두 쉬기", "evidence": [f"strategist.allowed.{i}.direction"]})
    for name, b in (g.get("bots") or {}).items():
        if (b.get("max_drawdown_pct") or 0) >= 30:
            acts.append({"action": "pause_strategy", "target": name, "reason": f"봇 낙폭 {b['max_drawdown_pct']}%", "evidence": [f"bots.{name}.max_drawdown_pct"]})
    if not acts:
        acts.append({"action": "keep", "target": "전체", "reason": "한도 안", "evidence": ["meta.rules"]})
    head = {"normal": "정상", "caution": "주의", "danger": "위험"}[lvl]
    msg = f"위험 수준 {head}. " + (("허용범위 그대로 승인합니다." if lvl != "danger" else "오늘은 전부 쉬기로 좁힙니다.") if st.get("allowed") else "") + \
          (f" 조치 권고 {sum(a['action'] != 'keep' for a in acts)}건 — 적용은 사람이 결정해 주세요." if any(a['action'] != 'keep' for a in acts) else "")
    return {"message": msg, "headline": f"위험 수준 {head}", "risk_level": lvl, "decisions": decs, "actions": acts, "findings": F, "data_gaps": []}


def ops_auditor(g):
    o, F = g.get("ops") or {}, []
    if o.get("data_source") == "synthetic":
        F.append(_f("데이터가 가상(synthetic)입니다 — 실제 시장 판단에 쓰면 안 됨", "ops.data_source", "fact", "warn"))
    if (o.get("scanner") or {}).get("errors"):
        F.append(_f(f"스캐너 오류 {o['scanner']['errors']}건", "ops.scanner.errors", "fact", "warn"))
    if o.get("bot_errors"):
        F.append(_f(f"봇 로그 오류: {', '.join(o['bot_errors'])}", "ops.bot_errors", "fact", "warn"))
    if o.get("ai") == "none":
        F.append(_f("AI 키가 없어 팀이 규칙 분석으로 동작 중", "ops.ai"))
    rep = ((g.get("book") or {}).get("whatif") or {}).get("reproduction_ok")
    if rep is False:
        F.append(_f("가정 실험실이 장부를 재현하지 못함 — 모의 엔진 정확도 점검 필요", "book.whatif.reproduction_ok", "fact", "critical"))
    head = "운영 이상 없음" if not F else f"운영 점검 항목 {len(F)}개"
    return {"message": head + (f" — {F[0]['claim']}" if F else "."), "headline": head, "findings": F, "calls": [], "proposals": [], "data_gaps": []}


def performance(g):
    bk, F = g.get("book") or {}, []
    for k, nm in (("today", "오늘"), ("week", "7일"), ("cumulative", "누적")):
        s = bk.get(k) or {}
        if s.get("trades"):
            F.append(_f(f"{nm} {s['trades']}건 · 승률 {s['win_rate_pct']}% · 손익 {s['net_pnl']:+} · 손익비 {s.get('profit_factor')}",
                        [f"book.{k}.trades", f"book.{k}.win_rate_pct"], "fact" if s.get("status") == "ok" else "hypothesis"))
    for name, b in (g.get("bots") or {}).items():
        F.append(_f(f"봇 {name}: 수익 {b['return_pct']}% · {b['trades']}건 · 낙폭 {b['max_drawdown_pct']}%", [f"bots.{name}.return_pct", f"bots.{name}.trades"],
                    "fact" if b.get("status") == "ok" else "hypothesis"))
    cu = (bk.get("cumulative") or {}).get("trades", 0)
    head = f"누적 {cu}건" + (" — 판단 기준(30건)까지 표본 부족" if cu < 30 else "")
    return {"message": head + ".", "headline": head, "findings": F, "calls": [], "proposals": [], "data_gaps": []}


def synergy(g):
    sy, F = g.get("synergy") or {}, []
    for k, v in (sy.get("corr") or {}).items():
        if v.get("corr") is not None:
            F.append(_f(f"{k}: 일간 수익 상관 {v['corr']} ({v['n_days']}일), 같은 날 동시 손실 {v['both_loss_days']}일",
                        f"synergy.corr.{k}.corr", "fact" if v["status"] == "ok" else "hypothesis", "warn" if v["corr"] >= 0.7 else "info"))
    for x in sy.get("same_coin_opposite_positions") or []:
        F.append(_f(f"같은 코인 반대 포지션: {x} — 서로 상쇄", "synergy.same_coin_opposite_positions", "fact", "warn"))
    head = "봇이 2개 미만 — 조합 분석 표본 부족" if (sy.get("bots") or 0) < 2 else f"봇 조합 {len(sy.get('corr') or {})}쌍 분석"
    return {"message": head + ".", "headline": head, "findings": F, "calls": [], "proposals": [], "data_gaps": []}


def code_reviewer(g):
    o, P = g.get("ops") or {}, []
    for s in ((o.get("scanner") or {}).get("error_samples") or [])[:2]:
        P.append({"change": f"스캐너 오류 원인 수정: {s[:80]}", "reason": "반복 오류", "evidence": ["ops.scanner.error_samples"], "how_to_confirm": "다음 스캔 30회 동안 오류 0"})
    if o.get("bot_errors"):
        P.append({"change": "봇 로그 오류 재현·수정", "reason": "봇 오류 발생", "evidence": ["ops.bot_errors"], "how_to_confirm": "개발 세션에서 재현 테스트 추가 후 1주 관찰"})
    head = "고칠 코드 문제 없음" if not P else f"개발 세션에서 볼 문제 {len(P)}개"
    return {"message": head + " (앱 안에서는 코드를 고치지 않습니다).", "headline": head, "findings": [], "calls": [], "proposals": P, "data_gaps": []}


def test_writer(g):
    o, P = g.get("ops") or {}, []
    if ((g.get("book") or {}).get("whatif") or {}).get("reproduction_ok") is False:
        P.append({"change": "가정 실험실 C0 재현 테스트", "reason": "재현 실패", "evidence": ["book.whatif.reproduction_ok"], "how_to_confirm": "같은 거래로 C0 ROE 가 장부와 수수료 범위 안에서 같음"})
    if (o.get("scanner") or {}).get("errors"):
        P.append({"change": "스캐너가 없는 종목·데이터 끊김에서도 다른 코인을 계속 검사하는지 테스트", "reason": "스캐너 오류", "evidence": ["ops.scanner.errors"], "how_to_confirm": "한 코인 오류 시 나머지 결과 정상"})
    return {"message": f"테스트 시나리오 {len(P)}개 제안." if P else "새로 필요한 테스트 없음.", "headline": f"테스트 제안 {len(P)}개",
            "findings": [], "calls": [], "proposals": P, "data_gaps": []}


def pnl(g):
    bk, F = g.get("book") or {}, []
    for i, t in enumerate((bk.get("trades_recent") or [])[-6:]):
        j = len(bk["trades_recent"]) - min(6, len(bk["trades_recent"])) + i
        F.append(_f(f"{t['who']} {_c(t['symbol'])} {NAME[t['side']]} {t['roe_pct']:+.1f}% — {t['cause']}" + (f" / 진입: {', '.join(t['pre'])}" if t["pre"] else ""),
                    [f"book.trades_recent.{j}.cause", f"book.trades_recent.{j}.roe_pct"], "fact", "warn" if t["cause"].startswith(("LIQ", "T1")) else "info"))
    top = sorted((bk.get("causes") or {}).items(), key=lambda kv: -kv[1])
    head = "최근 끝난 거래 없음 — 신호가 없었거나 포지션이 아직 열려 있음" if not F else f"최근 거래 {len(F)}건 복기 · 가장 많은 원인 {top[0][0]}"
    return {"message": head + ".", "headline": head, "findings": F, "calls": [], "proposals": [], "data_gaps": [] if F else ["끝난 거래가 없음"]}


def whatif(g):
    w = ((g.get("book") or {}).get("whatif") or {})
    F = []
    if w.get("reproduction_ok") is False:
        F.append(_f("가정 실험실이 장부를 재현하지 못함 — 결과를 해석하지 않음", "book.whatif.reproduction_ok", "fact", "critical"))
    else:
        for p, v in (w.get("policies") or {}).items():
            if v.get("verdict") in ("better", "worse"):
                F.append(_f(f"{p}: 실제보다 거래당 ROE {v['delta_mean_roe_pct']:+}%p ({v['verdict']}, {v['n']}건)", f"book.whatif.policies.{p}.verdict", "hypothesis",
                            "info"))
    n = w.get("n") or 0
    head = f"가정 실험 {n}건" + (" — 30건 미만이라 판정 보류" if n < 30 else "")
    return {"message": head + ". 좋아 보여도 앞으로의 거래로 확인하기 전엔 바꾸지 않습니다.", "headline": head, "findings": F, "calls": [], "proposals": [], "data_gaps": []}


def researcher(g):
    H = []
    for s, m in list((g.get("market") or {}).items())[:4]:
        b = _bias(m) if "regime" in m else "neutral"
        if b == "long":
            H.append({"name": f"{_c(s)} 눌림 롱", "rule": "1시간봉 EMA 20 위에서 RSI 14 가 40 아래로 내려갔다가 다시 40 위로 올라오면 롱, RSI 70 넘으면 청산, 손절 2%",
                      "symbol": s, "interval": "1h", "why": "상승 장세의 되돌림", "evidence": [f"market.{s}.regime"]})
        elif b == "short":
            H.append({"name": f"{_c(s)} 반등 숏", "rule": "1시간봉 EMA 20 아래에서 RSI 14 가 60 위로 올라갔다가 다시 60 아래로 내려오면 숏, RSI 30 아래면 청산, 손절 2%",
                      "symbol": s, "interval": "1h", "why": "하락 장세의 반등", "evidence": [f"market.{s}.regime"]})
        else:
            H.append({"name": f"{_c(s)} 박스 역추세", "rule": "1시간봉 볼린저 밴드 20 2 하단 아래로 종가가 내려가면 롱, 중심선 위면 청산, 손절 1.5%",
                      "symbol": s, "interval": "1h", "why": "횡보 장세", "evidence": [f"market.{s}.regime"]})
        if len(H) >= 2:
            break
    return {"message": f"가설 {len(H)}개 올립니다. 코드가 바로 백테스트해 주세요.", "headline": f"새 매매법 가설 {len(H)}개", "hypotheses": H, "data_gaps": []}


def miner(g):
    sc, F = g.get("scan") or {}, []
    for i, r in enumerate((sc.get("top") or [])[:3]):
        F.append(_f(f"{r['bot']} 를 {_c(r['symbol'])} {r['interval']} 로 돌리면 수익 {r['return_pct']}% ({r['trades']}건)", f"scan.top.{i}.return_pct", "hypothesis"))
    tried = sc.get("tried") or 0
    head = f"{tried}개 조합을 시험 — 많이 시험할수록 우연히 좋아 보이는 결과가 늘어납니다" if tried else "시험할 봇이 없음"
    return {"message": head + ".", "headline": head, "findings": F, "calls": [], "proposals": [], "data_gaps": []}


def improver(g):
    P = []
    for i, c in enumerate(g.get("candidates") or []):
        if c.get("kind") == "improve" and (c.get("gate") or {}).get("passed"):
            P.append({"change": f"{c['target']}: {' / '.join(c.get('changes') or [])}", "reason": "검증 구간에서 개선", "evidence": [f"candidates.{i}.gate.passed"],
                      "how_to_confirm": "적용 후 새 거래 30건에서 손익비 비교"})
    return {"message": f"수정안 {len(P)}개 — 전략 검증관 확인 부탁합니다." if P else "검증 구간에서 나아지는 수정안이 없습니다.", "headline": f"수정안 {len(P)}개",
            "findings": [], "calls": [], "proposals": P, "data_gaps": []}


def validator(g):
    V = []
    for i, c in enumerate(g.get("candidates") or []):
        gt = c.get("gate") or {}
        v = "pass" if gt.get("passed") else ("need_more_data" if (gt.get("test_trades") or 0) < 20 else "fail")
        V.append({"candidate": c["id"], "verdict": v, "reason": gt.get("reason", ""), "evidence": [f"candidates.{i}.gate"]})
    return {"message": f"후보 {len(V)}개 판정: 통과 {sum(v['verdict'] == 'pass' for v in V)}개.", "headline": f"통과 {sum(v['verdict'] == 'pass' for v in V)}/{len(V)}",
            "verdicts": V, "findings": [], "data_gaps": []}


def approver(g):
    A = []
    verd = {v["candidate"]: v["verdict"] for v in g.get("verdicts") or []}
    for i, c in enumerate(g.get("candidates") or []):
        ok = verd.get(c["id"]) == "pass" and (c.get("gate") or {}).get("passed")
        A.append({"candidate": c["id"], "decision": "approve" if ok else "reject", "reason": "관문·검증 통과" if ok else "관문 또는 검증 미통과",
                  "evidence": [f"candidates.{i}.gate"]})
    n = sum(a["decision"] == "approve" for a in A)
    auto = (g.get("meta") or {}).get("pipeline") == "autopilot"
    return {"message": f"승인 {n}개 · 거부 {len(A) - n}개. " + ("승인한 매매법은 오토파일럿이 페이퍼 봇으로 돌립니다 (모의 매매)." if auto else "승인한 것도 사람이 '적용'을 눌러야 반영됩니다."),
            "headline": f"승인 {n}개", "approvals": A, "data_gaps": []}


def cio(g):
    bots, W = g.get("bots") or {}, []
    score = {n: max(0.1, (b.get("return_pct") or 0) + 10) * (1 if b.get("status") == "ok" else 0.3) for n, b in bots.items()}
    tot = sum(score.values()) or 1
    for n in bots:
        W.append({"bot": n, "weight_pct": round(score[n] / tot * 100, 1), "reason": "수익·표본 기준 비례", "evidence": [f"bots.{n}.return_pct"]})
    return {"message": "봇 가중치 제안입니다 (표본이 적은 봇은 작게)." if W else "배분할 봇이 없습니다.", "headline": f"봇 {len(W)}개 배분안", "weights": W,
            "findings": [], "data_gaps": []}


def learning(g):
    w, M = ((g.get("book") or {}).get("whatif") or {}), []
    for p, v in (w.get("policies") or {}).items():
        if v.get("verdict") in ("better", "worse", "no_difference", "insufficient") and p != "C0":
            if v.get("verdict") == "better":
                M.append({"text": f"청산 규칙 {p} 가 실제보다 나았음 (거래당 {v['delta_mean_roe_pct']:+}%p, {v['n']}건)", "n": v["n"], "evidence": [f"book.whatif.policies.{p}.verdict"]})
    lessons = ((g.get("knowledge") or {}).get("memos") or [])
    P = [{"memo_id": m["id"], "reason": "표본 충족 · 반복 관찰", "evidence": []} for m in lessons if m.get("n", 0) >= 30 and m.get("seen", 1) >= 2][:2]
    return {"message": f"관찰 메모 {len(M)}개 기록" + (f", 교훈 승격 요청 {len(P)}개." if P else ".") + " 메모는 검증 전까지 판단에 쓰지 않습니다.",
            "headline": f"메모 {len(M)}개", "memos": M, "promote": P, "expire": [], "data_gaps": []}


def lead(g):
    st, rk = g.get("strategist") or {}, g.get("risk") or {}
    an = g.get("analysts") or {}
    s1 = st.get("headline") or next((a.get("headline") for a in an.values() if a.get("headline")), "분석 완료")
    warn = [f["claim"] for a in an.values() for f in a.get("findings", []) if f.get("severity") in ("warn", "critical")]
    s2 = warn[0] if warn else "특이사항 없음"
    s3 = f"리스크: {rk.get('headline', '판정 없음')}"
    acts = [f"{a['action']} {a['target']}: {a['reason']}" for a in rk.get("actions", []) if a.get("action") != "keep"]
    if g.get("failed"):
        s2 = f"실패한 역할 {', '.join(g['failed'])} · " + s2
    return {"message": f"정리합니다. {s1} / {s2}" + (f" / 사람이 할 일 {len(acts)}개" if acts else ""), "summary": [s1, s2, s3], "human_actions": acts,
            "glossary": [{"term": "ROE", "meaning": "증거금 대비 수익률"}, {"term": "ATR", "meaning": "평균 변동폭 (봉 하나가 보통 움직이는 크기)"}],
            "watch_next": warn[1:3]}


RULES = {k: v for k, v in globals().items() if callable(v) and k in (
    "chart", "flow", "macro", "news", "analog", "strategist", "critic", "risk", "ops_auditor", "performance", "synergy", "code_reviewer",
    "test_writer", "pnl", "whatif", "researcher", "miner", "improver", "validator", "approver", "cio", "learning", "lead")}
