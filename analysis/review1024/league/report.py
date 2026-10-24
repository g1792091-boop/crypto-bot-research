"""Writes REPORT_KO.md (and APPENDIX_ACCOUNTS_KO.md) from out/results.json (+ out/fivey.json, out/engine_check.json when present).

    python3 report.py [--out DIR] [--dest DIR]

Every number in the report comes from those files; the sentences that judge ('운을 넘었다', '후보 없음') are computed from the same
numbers with the thresholds written next to them, so a newer export regenerates the whole report with one command (run_all.py).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

import lg_lib as L

HERE = os.path.dirname(os.path.abspath(__file__))

# what the live executor (paperbot/executor.py) can follow today. It mirrors ONE paper account of the rule bot / combined bot
# (paper3.db); it cannot read the league's database. A league account can only go live through the combined bot (paperbot/combo.py,
# docs/combo-bot-ko.md: custom-value picks allowed, ATR stop, ladder, fixed 40x BTC / 30x alts, conditions incl. btc_trend, REV exit).
EXEC = {
    "ld": ("근사 가능", "합친 봇에 이 픽을 넣으면 신호·2 ATR 손절·계단은 같음. 다만 합친 봇 계단은 순ROE 11%→10%(두 분 계단 13%→10%와 다름), 배수 BTC 40·알트 30 고정"),
    "ld1": ("근사 가능", "합친 봇 손절 1 ATR 설정으로. 계단·배수 차이는 위와 같음"),
    "ldp": ("근사 가능", "합친 봇 손절을 후보 ATR 배수로. 넓은 손절은 고정 배수에서 거절이 많음"),
    "l5": ("코드 필요", "합친 봇 계단은 시작 숫자를 바꿀 수 있으나(first_lock) 7%→5% 그대로인지 확인 필요"),
    "l20": ("코드 필요", "위와 같음"),
    "ldt": ("근사 가능", "합친 봇 조건 btc_trend: with (커스텀값봇 g1과 같은 계산)"),
    "ldv": ("코드 필요", "합친 봇에 '변동성 보통' 조건이 없음"),
    "fqt": ("코드 필요", "빠른 손절(구조 무너짐 청산)을 실행기·합친 봇이 못 함"),
    "fqv": ("코드 필요", "위와 같음 + 변동성 조건 없음"),
    "tp10": ("코드 필요", "실행기는 고정 익절 주문을 못 걺(10/17 분석)"),
    "sw": ("부분만", "합친 봇 REV(반대 신호 청산)는 있으나 반대로 다시 들어가지 않음"),
    "fq": ("코드 필요", "매매법 구조 무너짐 판단이 실행기·합친 봇에 없음"),
    "nv": ("코드 필요", "위와 같음"), "tg": ("코드 필요", "위와 같음"), "sb": ("코드 필요", "위와 같음"),
    "iv": ("코드 필요", "자체 무효화 가격 손절 없음"), "ot": ("코드 필요", "자체 목표가 익절 없음"),
    "e": ("코드 필요", "고정 익절 3R 주문 없음"), "gb": ("코드 필요", "수익 반납 보호 없음"), "ma": ("코드 필요", "이동평균 이탈 청산 없음"),
    "ts": ("근사 가능", "합친 봇 max_hold_bars(보유 한도)로 비슷하게"), "ch": ("코드 필요", "추적 손절 없음"),
    "oc": ("부분만", "합친 봇 REV로 비슷하게, 고정 익절 없는 것은 계단으로 대체"), "wk": ("근사 가능", "합친 봇 no_weekend"),
    "fqc": ("해당 없음", "동전 계좌"), "ldc": ("해당 없음", "동전 계좌"),
}


# ------------------------------------------------------------------------------------------------ formatting
def _ok(x) -> bool:
    return x is not None and not (isinstance(x, float) and (math.isnan(x) or math.isinf(x)))


def pct(x, d: int = 1, sign: bool = True) -> str:
    if not _ok(x):
        return "—"
    s = f"{x * 100:+.{d}f}%" if sign else f"{x * 100:.{d}f}%"
    return s.replace("-", "−")


def pp(x, d: int = 2) -> str:
    if not _ok(x):
        return "—"
    return f"{x * 100:+.{d}f}%p".replace("-", "−")


def usd(x, d: int = 0) -> str:
    if not _ok(x):
        return "—"
    s = f"${abs(x):,.{d}f}"
    return ("−" if x < 0 else "+") + s if round(x, d) != 0 else "$0"


def amt(x, d: int = 0) -> str:
    """An amount without a sign (costs, sizes)."""
    if not _ok(x):
        return "—"
    return f"${abs(x):,.{d}f}"


def num(x, d: int = 0) -> str:
    if not _ok(x):
        return "—"
    return f"{x:,.{d}f}".replace("-", "−")


def pv(p) -> str:
    if not _ok(p):
        return "—"
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def pf(x) -> str:
    if x is None:
        return "∞"
    if not _ok(x):
        return "—"
    return f"{x:.2f}"


def rr(x, d: int = 2) -> str:
    if not _ok(x):
        return "—"
    return f"{x:+.{d}f}R".replace("-", "−")


def bust_txt(d: dict) -> str:
    if not d.get("bust"):
        return ""
    m = d.get("months_to_bust")
    return f" · **파산({m:.0f}개월 만)**" if _ok(m) else " · **파산**"


def kname(sfx: str) -> str:
    return L.KINDS.get(sfx, (sfx,))[0]


def table(head: list, rows: list) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c).replace("|", "\\|").replace("\n", " ") for c in r) + " |")
    return "\n".join(out)


def acct_label(a: dict) -> str:
    return f"{a.get('strategy_ko')} {a.get('tf')} · {kname(a.get('suffix'))}"


def hopes(res, var, cvd, cond, acc, good):
    """Every place where something looks good, each with its catch (report 8-2)."""
    hope = []
    pk_good = [p for p in res["picks"] if p["trades"] >= 20 and p["traded"] and p["kinds_pos"] / p["traded"] >= 0.5 and p["total"] > 0]
    for p in sorted(pk_good, key=lambda p: -p["total"]):
        hope.append([f"후보 `{p['pick']}` ({p['strategy_ko']} {p['tf']})", f"26종류 합계 {usd(p['total'])}, 거래한 {p['traded']}종류 중 {p['kinds_pos']}종류 플러스, 대조 "
                     + (pct(p.get("ld_ret")) if p.get("ld_n") else "거래 없음") + f" (대조 거래 {p.get('ld_n')}번)",
                     "종류들이 같은 신호를 나눠 써서 사실상 거래 몇 번의 결과. 대조 동전 " + (pct(p.get("ldc_ret")) if p.get("ldc_n") else "거래 없음")])
    for r in var:
        if r.get("same_exit") or not r.get("n"):
            continue
        if (r.get("mean_d_wallet") or 0) > 0 and (r.get("half1") or 0) > 0 and (r.get("half2") or 0) > 0 and r["picks_better"] >= 2 * max(r["picks_worse"], 1):
            hope.append([f"청산 {kname(r['variant'])} (대 {kname(r['control'])})", f"같은 신호 거래당 {pp(r['mean_d_wallet'])}, 앞·뒤 절반 모두 +, 후보 {r['picks_better']}승 {r['picks_worse']}패",
                         f"보정 q {pv(r.get('q'))}로 운의 범위. 계좌 합계는 여전히 {usd(r['total_v'])}(손실)"])
    for title, rows_, f in (("코인", res["by_coin"], lambda x: x["key"].replace("USDT", "")), ("시간대", res["by_session"], lambda x: x["key"]),
                            ("요일", res["by_dow"], lambda x: x["key"] + "요일"), ("봉", res["by_tf"], lambda x: x["key"])):
        for x in rows_:
            if (x["ld"].get("mean_wallet") or -1) > 0 and (x["fq"].get("mean_wallet") or -1) > 0:
                hope.append([f"{title} {f(x)}", f"대조 {pct(x['ld']['mean_wallet'], 2)} ({x['ld']['n']}번), 빠른 손절 {pct(x['fq']['mean_wallet'], 2)} ({x['fq']['n']}번)",
                             f"동전 짝 {pct(x['coin'].get('mean_wallet'), 2)}. 칸을 많이 나누면 몇 칸은 우연히 플러스(리그 화면 조건별: 동전보다 확실히 나은 칸 0개)"])
    for r in (cvd.get("rows") or []):
        if r.get("q") is not None and r["q"] < 0.10 and (r.get("diff_r") or 0) > 0:
            hope.append([f"커스텀값 `{r['pick']}`", f"커스텀 {rr(r.get('r_custom'))} vs 기본값 {rr(r.get('r_default'))} (q {pv(r['q'])})",
                         f"커스텀 쪽 거래 {r['n_custom']}번뿐"])
    for aid in good:
        a = acc[aid]
        hope.append([f"계좌 `{aid}`", f"거래 {a['n']}번 · 수익률 {pct(a['ret'])} · 두 절반 + · 거래당 {pct(a.get('mean_wallet'), 2)}",
                     f"보정 q {pv(a.get('q'))}; 같은 후보 대조 동전 {pct((acc.get(a['pick'] + '-ldc') or {}).get('ret'))}"])
    if cond.get("by_dim"):
        sess = next((d for d in cond["by_dim"] if d["dim"].startswith("시간대")), None)
        if sess and sess["real_unique"].get("held_share", 0) >= 0.6:
            hope.append(["조건: 시간대", f"앞 절반에서 고른 시간대 칸 {sess['real_unique']['picked']}개 중 {sess['real_unique']['held']}개가 뒤 절반에도 +",
                         "칸 수가 적고 한 후보의 여러 종류가 겹침. 미리 정해서 다시 시험할 것"])
    return hope


# ------------------------------------------------------------------------------------------------ report
def build(res: dict, fivey: dict | None, echeck: dict | None) -> str:
    P = res["period"]
    lg = res["league"]
    cov = res["coverage"]
    acc = {a["account"]: a for a in res["accounts"]}
    kinds = {k["suffix"]: k for k in res["kinds"]}
    mkt = res.get("market") or {}
    days = P["days"]
    var = res["variants"]["rows"]
    coin = res["coin"]
    prot = res["protocol"]
    cvd = res.get("custom_vs_default") or {}
    st = res["stability"]
    luck = res["luck"]
    good = res.get("good", [])
    v17 = res["vs1017"]
    goal = res.get("goal") or {"rows": []}
    cond = res.get("cond") or {}
    gl = {r["account"]: r for r in goal["rows"]}
    out = []
    w = out.append

    beat_var = [r for r in var if r.get("q") is not None and r["q"] < 0.05 and (r.get("mean_d_wallet") or 0) > 0]
    beat_coin = [r for r in coin["kinds"] if (r.get("p2") is not None and r["p2"] < 0.05 and (r.get("mean_d_wallet") or 0) > 0)]
    prot_pass = [r for r in prot["rows"] if r.get("pass_now")]
    cvd_pooled = cvd.get("pooled_r") or {}
    best_var = sorted([r for r in var if r.get("p2") is not None and (r.get("mean_d_wallet") or 0) > 0], key=lambda r: r["p2"])[:4]

    # shortlist logic (fixed rules, written in section 10)
    short = []
    for aid in good:
        a = acc[aid]
        sfx = a["suffix"]
        twin = {"ld": "ldc", "fq": "fqc"}.get(sfx)
        g = gl.get(aid, {})
        fy = ((fivey or {}).get("windows") or {})
        f2426 = (fy.get("2024-2026") or {}).get(aid) or {}
        crit = {
            "n30": a.get("n", 0) >= 30,
            "luck": a.get("q") is not None and float(a["q"]) < 0.05,
            "halves": (a.get("pnl_h1") or 0) > 0 and (a.get("pnl_h2") or 0) > 0,
            "coin": None,
            "five": None,
            "exec": EXEC.get(sfx, ("코드 필요", ""))[0] == "근사 가능",
        }
        tw = acc.get(f"{a['pick']}-ldc") if sfx not in ("fqc", "ldc") else None
        if tw is not None:
            crit["coin"] = (a.get("ret") or 0) > (tw.get("ret") or 0)
        if f2426:
            if aid.startswith("ds-"):
                crit["five"] = f2426.get("mean_wallet_sign") == "+"
            else:
                crit["five"] = (f2426.get("mean_wallet") or 0) > 0
        short.append((aid, crit, tw))
    qualified = [s for s in short if all(v is True for v in s[1].values())]
    hope_rows = hopes(res, var, cvd, cond, acc, good)

    # =========================================================================================== header
    w("# 커스텀값봇(후보 리그) 11일치 전체 분석")
    w("")
    w(f"작성 2026-10-24 밤 (KST). 자료: 서버 내보내기 `{res['zip']}` ({res['zip_manifest'][0] if res.get('zip_manifest') else ''} 생성). "
      f"모든 숫자는 이 폴더의 스크립트가 그 압축 파일에서 다시 계산한 것이고, 명령 한 줄로 다시 만들 수 있습니다(15장).")
    w("")
    w(f"- **기간**: {L.kst(P['start_ms'], '%m/%d %H:%M')} ~ {L.kst(P['done_ms'], '%m/%d %H:%M')} KST, **{days:.2f}일** "
      "(지금 리그가 시작한 10/13 오후부터 엔진이 계산한 마지막 시각까지). 두 분이 말씀하신 \"11일치\"가 이 기간입니다.")
    w(f"- **규모**: 계좌 {num(cov['accounts'])}개(후보 {cov['picks']}개 × 청산 종류 26가지), 그중 거래한 계좌 {num(cov['traded'])}개, 끝난 거래 "
      f"{num(cov['trades'])}번, 끝에 열려 있던 포지션 {cov['open']}개. 모든 계좌는 $1,000에서 시작, 배수 50·40·30배만.")
    w("- **종이 매매**입니다. 실제 주문은 없고, 수수료·미끄러짐·펀딩은 엔진의 가정(시장가 0.05% + 미끄러짐 0.02%, 한쪽)으로 뺐습니다.")
    w("")

    # =========================================================================================== 0
    w("## 0. 결론")
    w("")
    cnt = [0]

    def nx():
        cnt[0] += 1
        return cnt[0]
    tot = lg["total"]
    w(f"{nx()}. **11일 동안 리그 전체가 잃었습니다.** {num(cov['accounts'])}계좌 합계 **{usd(tot)}** (계좌당 평균 {pct(tot / cov['accounts'] / L.EQUITY0)}). "
      f"계좌 종류 {res['kinds_with_trades']}가지 중 **{res['kinds_losing']}가지가 손실**입니다. 플러스로 끝난 계좌 {lg['pos_accounts']}개, "
      f"마이너스 {lg['neg_accounts']}개, 끝난 거래가 하나도 없는 계좌 {cov['accounts'] - cov['traded']}개(대부분 신호가 30배 규칙에 거절됨).")
    w(f"{nx()}. **손실의 큰 몫은 비용입니다. 그런데 비용을 빼기 전에도 마이너스입니다.** 수수료 {amt(lg['fees'])} + 미끄러짐(추정) {amt(lg['slip'])} = "
      f"{amt(lg['fees'] + lg['slip'])}. 비용 전 손익도 **{usd(lg['gross'])}** 입니다. 거래당 평균은 지갑의 {pct(lg['mean_wallet'], 2)}, "
      f"승률 {pct(lg['win'], 0, False)}, 손익비(PF) {pf(lg['pf'])}.")
    sides = {r["key"]: r for r in res["by_side"]}
    if mkt.get("index_ret") is not None and "숏" in sides:
        w(f"{nx()}. **시장이 내렸고, 숏이 덜 잃었습니다. 동전 던지기 계좌도 똑같았습니다.** 6코인 평균 {pct(mkt['index_ret'])}. 거래의 "
          f"{pct(lg['short_share'], 0, False)}가 숏이었고, 숏 거래당 {pct(sides['숏']['all']['mean_wallet'], 2)} vs 롱 {pct(sides['롱']['all']['mean_wallet'], 2)}. "
          f"방향을 동전으로 정한 짝 계좌도 숏 {pct(sides['숏']['coin']['mean_wallet'], 2)} vs 롱 {pct(sides['롱']['coin']['mean_wallet'], 2)}로 같은 모양입니다. "
          "방향을 맞힌 실력이 아니라 시장 흐름입니다.")
    w(f"{nx()}. **미리 정한 판정 4개(28일째 11/10에 한 번 판정, 지금은 미리보기): 지금 숫자로도 통과 {len(prot_pass)}개.** "
      f"빠른 손절은 대조보다 같은 신호에서 ROE {pp(prot['rows'][0].get('mean'))}, 동전 짝보다 {pp(prot['rows'][1].get('mean'))}; "
      f"대조도 동전 짝보다 {pp(prot['rows'][2].get('mean'))}. 지금 쌍은 {prot['rows'][0].get('n')}개(규칙은 300개 이상)이고 28일째에는 약 "
      f"{prot['rows'][0].get('n', 0) / max(days, 1) * 28:.0f}개로 예상되지만, 방향이 지금처럼 마이너스면 통과가 나올 수 없습니다.")
    w(f"{nx()}. **같은 신호로 청산만 바꾼 비교 {res['variants'].get('family', len(var))}개 중 운을 넘은 것 {len(beat_var)}개** (우연 보정 BH, q<0.05). "
      + ("가장 나아 보인 것: " + "; ".join(f"{kname(r['variant'])} − {kname(r['control'])} = 같은 신호 거래당 지갑 {pp(r['mean_d_wallet'])} (q {pv(r.get('q'))})"
                                    for r in best_var[:3]) + ". 보정 뒤에는 모두 운의 범위입니다." if best_var else ""))
    w(f"{nx()}. **계좌 하나씩 봐도 운을 넘은 계좌 {luck['q05']}개.** 거래 10번 이상인 {luck['tested']}계좌를 각각 시험했습니다. 보정 전 p<0.05는 "
      f"{luck['raw_p05']}개인데, 아무 실력이 없어도 {luck['expected_by_chance']:.1f}개쯤 나옵니다.")
    if cvd_pooled:
        w(f"{nx()}. **커스텀값이 기본값보다 낫다는 증거도 없습니다.** 같은 매매법·같은 봉에서 커스텀값봇 대조(-ld) 거래당 {rr(cvd.get('mean_r_custom'))} vs "
          f"규칙봇(기본값) {rr(cvd.get('mean_r_default'))}, 차이 {rr(cvd_pooled.get('diff'))} (90% 구간 {rr(cvd_pooled.get('lo'))} ~ {rr(cvd_pooled.get('hi'))}). "
          f"오히려 커스텀값 쪽이 약간 나빴습니다. 신호 수는 하루 {cvd.get('per_day_custom', 0):.0f}번 vs {cvd.get('per_day_default', 0):.0f}번.")
    after = v17["after"]["kinds"]
    fy_ = (fivey or {}).get("windows", {}).get("2024-2026") if fivey else None
    if fy_ is not None and good:
        npos_ = sum(1 for x in good if (fy_.get(x) or {}).get("n") and (((fy_.get(x) or {}).get("mean_wallet_sign") == "+") if x.startswith("ds-")
                                                                     else ((fy_.get(x) or {}).get("mean_wallet") or 0) > 0))
        nn_ = sum(1 for x in good if (fy_.get(x) or {}).get("n"))
        nb_ = sum(1 for x in good if (fy_.get(x) or {}).get("bust"))
        w(f"{nx()}. **5년 확인 (리그 엔진 그대로, 2024-01~2026-09, $1,000 · 같은 배수 규칙)**: 11일에 좋아 보인 {len(good)}계좌 중 그 기간 거래당 플러스였던 것 "
          f"**{npos_}/{nn_}개**, 잔고가 바닥난(파산) 것 **{nb_}개** (7장)."
          + (" 11일의 좋은 성적은 더 긴 기간에서 이어지지 않았습니다." if npos_ <= nn_ // 3 else ""))
    w(f"{nx()}. **10/17 분석 뒤 {v17['after']['days']:.1f}일(새 자료)에서도 {v17['kinds_losing_after']}/26 종류가 손실.** 10/17에 유일하게 좋아 보이던 "
      f"'BTC 추세 필터'(대조 기준 거래당 {pct(v17['read']['ldt_wallet'], 2)})는 그 뒤 {pct(after['ldt'].get('mean_wallet'), 2)}였습니다. "
      f"앞 절반 순위와 뒤 절반 순위의 상관은 {num(st.get('rank_corr_halves'), 2)}: 앞에서 잘한 계좌가 뒤에서 잘한다는 근거가 없습니다.")
    if qualified:
        w(f"{nx()}. **실거래 후보: {len(qualified)}개가 미리 적은 기준을 모두 넘었습니다** (10장).")
    else:
        top = good[:3]
        w(f"{nx()}. **실거래로 돌릴 계좌: 기준을 다 넘는 것 없음.** 플러스이면서 거래 10번 이상, 두 절반 모두 플러스인 계좌는 {len(good)}개뿐이고"
          + (f"(가장 좋은 것: {', '.join(top)})" if top else "")
          + ", 모두 거래 30번 미만이고 운 검사를 넘지 못했으며, 같은 픽의 동전 짝도 비슷하게 벌었습니다(10장).")
    gbest = sorted([r for r in goal["rows"] if r["account"] in good], key=lambda r: -(r["sims"].get("40%x50", {}).get("p_goal") or 0))
    if gbest:
        b = gbest[0]
        s50 = b["sims"]["40%x50"]
        tw = acc.get(f"{acc[b['account']]['pick']}-ldc")
        tws = (gl.get(tw["account"]) or {}).get("sims", {}).get("40%x50") if tw else None
        w(f"{nx()}. **목표(30일 +500%)까지의 거리.** 지금 기록을 그대로 30일 이어 붙여 보면(부트스트랩), 가장 좋아 보이는 계좌({b['account']}, 거래 {b['n']}번)를 "
          f"증거금 40% × 50배로 돌릴 때 30일 안에 ×6에 닿는 비율 {pct(s50['p_goal'], 0, False)}, 그 전에 반토막 {pct(s50['p_half_first'], 0, False)}. "
          + (f"하지만 같은 픽을 **동전 방향**으로 탄 짝 계좌도 {pct(tws['p_goal'], 0, False)}로 비슷합니다. " if tws else "")
          + "11일·거래 20번 안팎의 기록을 늘린 계산이라 실제 기대치가 아닙니다. 대부분의 계좌는 거래당 평균이 마이너스라 배수를 올리면 더 빨리 잃습니다(8장).")
    if hope_rows:
        w(f"{nx()}. **희망이 보이는 곳도 빠짐없이 적었습니다(8-2, {len(hope_rows)}곳).** 예: "
          + "; ".join(h[0].replace("`", "") + " — " + h[1] for h in
                      [next((h for h in hope_rows if h[0].startswith(t)), None) for t in ("청산", "후보", "계좌")] if h)
          + ". 다만 어느 것도 운의 범위를 넘지 못해, 돈을 걸 근거가 아니라 '미리 정해서 다음에 시험할 후보'입니다.")
    w("")
    w("**한 줄**: 11일 기록에서 \"이 계좌는 실력으로 번다\"고 할 만한 것은 없습니다. 이긴 계좌는 하락장에서 숏을 탄 것과 운으로 설명되고, "
      "커스텀값·새 청산 구조 모두 대조와 동전 던지기를 이기지 못했습니다. 정해 둔 28일째 판정(11/10)까지 그대로 두고 보는 것이 맞습니다.")
    w("")

    # =========================================================================================== 1
    w("## 1. 무엇을 봤나 (기록 파일 · 기간 · 계좌)")
    w("")
    w("### 1-1. 압축 파일 안의 기록 파일")
    w("")
    rows = []
    role_ko = {"current": "**지금 리그 (분석 대상)**", "backup": "지금 리그의 중간 사본", "set_aside": "옆으로 치운 리그",
               "set_aside_copy": "옆으로 치운 리그의 중간 사본"}
    for d in res["dbs"]:
        note = ""
        if d["role"] == "backup":
            s = d.get("same_as_current_prefix") or {}
            note = "지금 리그 앞부분과 거래·손익이 똑같음" if s.get("same") else "지금 리그와 다름(확인 필요)"
        elif d["role"] == "set_aside":
            note = f"진입 {d['entered']}번, 끝난 거래 {d['trades']}번"
        elif d["role"] == "set_aside_copy":
            s = d.get("same_as_prefix") or {}
            note = f"`{d.get('copy_of')}` 앞부분" + (" (같음)" if s.get("same") else " (다름: 확인 필요)")
        rows.append([f"`{d['name']}`", role_ko[d["role"]], f"{L.kst(d['start_ms'])} ~ {L.kst(d['done_ms'])}", num(d["accounts"]), num(d["trades"]),
                     usd(d["pnl"]), note])
    w(table(["파일", "무엇", "기간(KST)", "계좌", "끝난 거래", "손익", "메모"], rows))
    w("")
    w("- **분석 대상은 `league_exits.db` 하나**입니다. 이름에 `from_1013`이 붙은 세 파일은 업데이트 때 설치 스크립트가 남긴 같은 리그의 중간 "
      "사본입니다. 거래를 하나씩 맞춰 보니 지금 리그의 앞부분과 손익까지 똑같아서 따로 세지 않습니다(두 번 세면 안 됨).")
    w("- `20x_league_exits.db`와 `old_20261013_0810_*`은 10/13 오후 지금 리그를 켜기 전 1~2시간 돌다 멈춘 시험 리그입니다(12장).")
    w("- **이 압축 파일에 없는 것**: 10/11 12:00 ~ 10/13 오후의 첫 관찰 리그(`league.db`, 190계좌, $5,000, 기본값 계좌 포함)는 내보내기 "
      "대상이 아니라서 보지 못했습니다. 그래서 이 보고서의 '11일'은 10/13 오후부터입니다.")
    if res.get("prev"):
        pv_ = res["prev"]
        w(f"- 10/22에 받은 내보내기(`{pv_['zip']}`)의 같은 리그와 거래 {num(pv_.get('old_trades'))}번이 손익까지 모두 같았습니다(기록이 중간에 바뀌지 않음).")
    w("")
    w("### 1-2. 계좌 종류 (26가지)")
    w("")
    w("모든 종류가 **같은 신호**(같은 매매법 · 같은 커스텀값 · 같은 시각)로 들어가고, **나오는 방법(청산)** 이나 **방향**만 다릅니다. "
      "그래서 종류끼리는 서로 독립이 아니고, 같은 신호의 운을 함께 탑니다.")
    w("")
    rows = []
    for sfx in L.KIND_ORDER:
        k = kinds[sfx]
        rows.append([f"`-{sfx}`", k["name"], k["group"], k["desc"], k["accounts"]])
    w(table(["꼬리표", "이름", "묶음", "무엇이 다른가", "계좌"], rows))
    w("")
    bg = cov["by_group"]
    w(f"- 묶음별 계좌: 메인 {bg.get('메인', 0)} · 대조 {bg.get('대조', 0)} · 동전 {bg.get('동전', 0)} · 필터 {bg.get('필터', 0)} · 연구 {bg.get('연구', 0)}. "
      f"매매법 묶음: 규칙봇 쪽(core) {cov['core_accounts']}계좌, 딥시크 쪽(ds) {cov['ds_accounts']}계좌.")
    w(f"- 후보 {res['n_cands']}개 = 5년 연구의 관찰 후보 {res['cands_tier']['watch']}개 + 약한 단서 {res['cands_tier']['weak']}개 (`etc/candidates.json`).")
    w("- **이 리그에는 '기본값 쌍둥이' 계좌가 없습니다.** 10/13 재시작 때 1/4 크기 · 청산만 바꾼 기본값 · 기본값 계좌를 뺐습니다. 그래서 커스텀값 vs 기본값은 "
      "같은 기간의 **규칙봇(기본값) 계좌**와 비교했습니다(4-4).")
    w("- 1/4 크기 계좌도 없습니다. 크기 효과는 8장의 '목표 경로' 계산으로 대신 봅니다.")
    w(f"- **신호 처리**: 들어온 신호 {num(cov['offered'])}건 중 진입 {num(cov['entered'])} · 이미 포지션이 있어 건너뜀 {num(cov['skipped'])} · "
      f"**거절 {num(cov['rejected'])} ({pct(cov['rejected'] / max(cov['offered'], 1), 0, False)})**. 거절은 대부분 '배수 30배 아래 금지 + 손절 한 번 손실 15% 한도' "
      "때문입니다. 손절이 넓은 신호(긴 봉, 3~4 ATR 손절)는 30배에서 손실 한도를 넘어 들어가지 못합니다. 4시간봉 후보와 '지금 청산' 계열 계좌의 거래가 "
      "적은 이유입니다.")
    w("")

    # =========================================================================================== 2
    w("## 2. 리그 전체")
    w("")
    w("### 2-1. 한눈에")
    w("")
    rows = [["끝난 거래", num(lg["n"])], ["이긴 비율(승률)", pct(lg["win"], 1, False)], ["거래당 평균(지갑 대비)", pct(lg["mean_wallet"], 2)],
            ["거래당 평균(증거금 대비, ROE)", pct(lg["mean_roe"], 1)], ["거래당 평균(R: 처음 손절 거리 = 1)", rr(lg["mean_r"])],
            ["닫힌 거래 손익 합", usd(lg["realized"])], ["열린 포지션 평가손익(끝 시각 가격)", usd(lg["unreal"])], ["합계", usd(lg["total"])],
            ["수수료", usd(-lg["fees"])], ["미끄러짐(추정)", usd(-lg["slip"])], ["펀딩(받은 것 +)", usd(-lg["funding"])],
            ["비용 전 손익", usd(lg["gross"])], ["손익비(PF = 이긴 돈 ÷ 진 돈)", pf(lg["pf"])], ["강제청산", f"{lg['liq']}번"], ["파산 계좌", f"{lg['busts']}개"],
            ["보유 시간 가운데값", f"{lg['med_hold_h']:.1f}시간"]]
    w(table(["항목", "값"], rows))
    w("")
    w("### 2-2. 종류별 (26가지)")
    w("")
    w("'거래당'은 거래 하나가 그 순간 지갑을 몇 % 움직였는지의 평균입니다. '운 p'는 날짜를 통째로 다시 뽑는 부트스트랩으로 '거래당 평균이 0보다 크다'를 "
      "시험한 값(작을수록 운이 아닐 가능성)입니다. 종류끼리 같은 신호를 써서 서로 독립이 아닙니다.")
    w("")
    rows = []
    for sfx in L.KIND_ORDER:
        k = kinds[sfx]
        if not k.get("n"):
            rows.append([kname(sfx), k["accounts"], 0, "—", "—", "—", usd(k["total"]), "—", "—", "—"])
            continue
        rows.append([kname(sfx), f"{k['traded']} ({k['pos_accounts']}+ / {k['neg_accounts']}−)", k["n"], pct(k["win"], 0, False), pct(k["mean_wallet"], 2),
                     pf(k["pf"]), usd(k["total"]), usd(k["gross"]), usd(-(k["fees"] + k["slip"])), pv(k.get("p_pos"))])
    w(table(["종류", "거래한 계좌 (플러스/마이너스)", "거래", "승률", "거래당", "PF", "합계(열린 포함)", "비용 전", "비용", "운 p"], rows))
    w("")
    loss_kinds = sorted([k for k in res["kinds"] if k.get("n")], key=lambda k: k["mean_wallet"])
    best4 = ", ".join(kname(k["suffix"]) + " " + pct(k["mean_wallet"], 2) for k in loss_kinds[::-1][:4])
    worst4 = ", ".join(kname(k["suffix"]) + " " + pct(k["mean_wallet"], 2) for k in loss_kinds[:4])
    w(f"- 가장 덜 잃은 종류: {best4}. 가장 많이 잃은 종류: {worst4}.")
    w("- '지금 청산(후보 원래 청산: 3R 고정 익절 + 3~4 ATR 손절)' 계열(-e, -gb, -ma, -ts, -ch, -oc, -wk)은 30배에서 손절이 너무 멀어 신호의 80% 넘게 "
      "거절됐고, 들어간 거래는 승률 4~33%로 크게 잃었습니다. 5년 연구에서 고른 청산이 30배 · $1,000 조건에서는 맞지 않습니다.")
    w("- 동전 짝 두 종류(-ldc, -fqc)가 같은 청산의 진짜 계좌(-ld, -fq)보다 덜 잃었습니다(4-3).")
    w("")
    w("### 2-3. 시장 움직임과 그 영향")
    w("")
    if mkt.get("coins"):
        rows = [[c["symbol"].replace("USDT", ""), num(c["start"], 4 if c["start"] < 1 else 2), num(c["end"], 4 if c["end"] < 1 else 2), pct(c["ret"]),
                 num(c["high"], 4 if c["high"] < 1 else 2), num(c["low"], 4 if c["low"] < 1 else 2)] for c in mkt["coins"]]
        w(table(["코인", "시작 가격", "끝 가격", "변화", "최고", "최저"], rows))
        w("")
        dn = [d for d in mkt["days"] if d.get("index") is not None]
        w(f"- 6코인 평균 **{pct(mkt['index_ret'])}**. 하루(한국 09시 기준) 단위로 {len(dn)}일 중 {sum(1 for d in dn if d['index'] < 0)}일이 하락. "
          f"가격은 바이낸스 공개 1분봉(data.binance.vision)이고, 아직 공개되지 않은 마지막 날은 리그 엔진의 마지막 가격으로 채웠습니다.")
    sh, lo = sides.get("숏"), sides.get("롱")
    if sh and lo:
        w(f"- **숏 vs 롱 (리그 전체)**: 숏 {num(sh['all']['n'])}번 거래당 {pct(sh['all']['mean_wallet'], 2)} (비용 전 {usd(sh['all']['gross'])}), "
          f"롱 {num(lo['all']['n'])}번 {pct(lo['all']['mean_wallet'], 2)} (비용 전 {usd(lo['all']['gross'])}). "
          f"**동전 짝 계좌**: 숏 {pct(sh['coin']['mean_wallet'], 2)}, 롱 {pct(lo['coin']['mean_wallet'], 2)}. 방향을 무작위로 정해도 숏이 나았으므로, 숏이 나았던 것은 "
          "매매법 실력이 아니라 내리는 시장 때문입니다.")
    if lg.get("mkt_usd") is not None:
        w(f"- **시장 몫 나누기**: 거래마다 '들고 있던 동안 6코인 평균이 움직인 만큼 × 방향 × 포지션 크기'를 시장 몫으로 보면, 비용 전 손익 {usd(lg['gross'])} 중 "
          f"시장 몫 {usd(lg['mkt_usd'])}, 나머지(코인 고르기 · 진입·청산 타이밍) {usd(lg['resid_usd'])}입니다. 시장이 내린 기간인데도 시장 몫이 마이너스인 것은 "
          "**들고 있는 동안에는 시장이 포지션 반대로 움직인 때가 많았다**는 뜻입니다(숏을 잡으면 반등, 롱을 잡으면 하락). 여기에 비용 "
          f"{amt(lg['fees'] + lg['slip'])}가 더해져 합계 {usd(lg['realized'])}가 됐습니다. "
          f"(1분봉이 공개된 시각까지 끝난 거래 {num(mkt.get('trades_with_index'))}번 기준)")
    w("")
    w("하루씩 (한국 시각 09시 ~ 다음 날 09시, 시장은 6코인 평균):")
    w("")
    rows = []
    for d in st["days"]:
        rows.append([L.kst(d["day"], "%m/%d"), pct(d.get("index")), d["all"]["n"], usd(d["all"]["pnl"]), pct(d["all"].get("mean_wallet"), 2),
                     usd(d["fq"].get("pnl")), usd(d["ld"].get("pnl")), usd(d["fqc"].get("pnl")), usd(d["ldc"].get("pnl")),
                     pct(d["all"].get("short_share"), 0, False)])
    w(table(["날", "시장", "거래(전체)", "손익(전체)", "거래당", "빠른 손절", "대조", "빠른 손절 동전", "대조 동전", "숏 비율"], rows))
    w("")

    def grp_table(rows_, title, keyname=None):
        w(f"### {title}")
        w("")
        rr_ = []
        for x in rows_:
            a, ld_, fq_, cn = x["all"], x["ld"], x["fq"], x["coin"]
            rr_.append([keyname(x) if keyname else x["key"], num(a["n"]), pct(a["win"], 0, False), pct(a["mean_wallet"], 2), usd(a["pnl"]), usd(a["gross"]),
                        pct(a.get("short_share"), 0, False),
                        f"{pct(ld_.get('mean_wallet'), 2)} ({ld_.get('n', 0)})" if ld_.get("n") else "—",
                        f"{pct(fq_.get('mean_wallet'), 2)} ({fq_.get('n', 0)})" if fq_.get("n") else "—",
                        f"{pct(cn.get('mean_wallet'), 2)} ({cn.get('n', 0)})" if cn.get("n") else "—"])
        w(table(["구분", "거래", "승률", "거래당", "손익", "비용 전", "숏 비율", "대조 거래당 (수)", "빠른 손절 (수)", "동전 짝 (수)"], rr_))
        w("")

    w("아래 표들의 '전체'는 26종류를 모두 합친 것이라 같은 신호가 여러 번 들어 있습니다. 대조 · 빠른 손절 · 동전 짝 칸은 그 종류만 본 것입니다.")
    w("")
    fam = sorted(res["by_family"], key=lambda x: x["all"]["pnl"])
    grp_table(fam, "2-4. 매매법별 (27개)", lambda x: f"{x['name_ko']} ({'규칙봇' if x['pool'] == 'core' else '딥시크'})")
    grp_table(res["by_tf"], "2-5. 봉별")
    grp_table(res["by_side"], "2-6. 롱 · 숏")
    grp_table(res["by_coin"], "2-7. 코인별", lambda x: x["key"].replace("USDT", ""))
    grp_table(res["by_session"], "2-8. 시간대별 (진입 시각, 한국)")
    grp_table(res["by_hour"], "2-9. 3시간 단위 (진입 시각, 한국)", lambda x: f"{x['key']:02d}~{x['key'] + 3:02d}시")
    grp_table(res["by_weekend"], "2-10. 평일 · 주말")
    grp_table(res["by_dow"], "2-11. 요일별 (진입, 한국)")
    ex_name = {k: v for k, v in L.EXIT_KO.items()}
    grp_table(res["by_exit"], "2-12. 청산 이유", lambda x: ex_name.get(x["key"], x["key"]))
    w("- 계단 잠금(이익 확정)으로 나간 거래는 거의 다 이겼지만 한 번 평균이 작고(지갑 +4% 안팎), 손절 한 번이 지갑의 약 −10%라서 손절 1번을 메우려면 잠금 2~3번이 필요합니다.")
    w("")
    grp_table(res["by_lev"], "2-13. 배수", lambda x: f"{x['key']}배")
    grp_table(res["by_tier"], "2-14. 좋은 자리 · 보통 자리 (진입 강도 점수)", lambda x: {"best": "좋은 자리", "normal": "보통 자리"}.get(x["key"], x["key"]))
    w("### 2-15. 비용")
    w("")
    w(f"- 리그 전체 수수료 {amt(lg['fees'])}, 미끄러짐(추정, 시장가 한쪽 0.02%) {amt(lg['slip'])}, 펀딩 {usd(-lg['funding'])}(받은 것이 +). "
      f"비용 합계는 손실 합계({usd(lg['realized'])})의 {pct((lg['fees'] + lg['slip']) / abs(lg['realized']), 0, False)}입니다.")
    w("- 30배 · 증거금 30%면 왕복 비용(0.14%)이 증거금의 약 4.2%, 지갑의 약 1.3%입니다. 계단 잠금 한 번(+10% ROE)이 지갑 +3% 안팎이라 비용이 그 절반 가까이를 먹습니다.")
    w("")

    # =========================================================================================== 3
    w("## 3. 계좌별 (요약 · 전체 표는 부록)")
    w("")
    w("모든 계좌 1,188개의 표는 **`APPENDIX_ACCOUNTS_KO.md`** 에 있습니다(거래 · 승률 · 평균 이익/손실 · PF · 손익 · 거래당 · 최대 낙폭 · 롱/숏 · 앞/뒤 절반 · "
      "최장 연패 · 운 검사). 같은 내용이 `out/accounts.csv`에도 있습니다.")
    w("")
    traded = [a for a in res["accounts"] if a.get("n")]
    top = sorted(traded, key=lambda a: -a["ret"])[:20]
    bot = sorted(traded, key=lambda a: a["ret"])[:10]

    def arow(a):
        return [f"`{a['account']}`", acct_label(a), a["n"], pct(a.get("win_rate"), 0, False), pf(a.get("pf")), pct(a["ret"]), pct(a.get("mean_wallet"), 2),
                pct(a.get("mdd_engine"), 0, False), f"{usd(a.get('pnl_h1'))} / {usd(a.get('pnl_h2'))}", num(a.get("loss_streak")),
                f"{num(a.get('n_short'))}/{num(a.get('n'))}", pv(a.get("p_pos")) + (f" (q {pv(a.get('q'))})" if a.get("q") is not None else "")]
    head = ["계좌", "매매법 · 종류", "거래", "승률", "PF", "수익률", "거래당", "최대 낙폭", "앞 / 뒤 절반", "최장 연패", "숏/전체", "운 p (보정 q)"]
    w("### 3-1. 수익률 상위 20")
    w("")
    w(table(head, [arow(a) for a in top]))
    w("")
    w("### 3-2. 수익률 하위 10")
    w("")
    w(table(head, [arow(a) for a in bot]))
    w("")
    n_top_coin = sum(1 for a in top if a["suffix"] in ("fqc", "ldc"))
    picks_top = {}
    for a in top:
        picks_top[a["pick"]] = picks_top.get(a["pick"], 0) + 1
    w(f"- 상위 20개 중 끝난 거래가 10번 미만인 계좌가 {sum(1 for a in top if a['n'] < 10)}개입니다(예: 맨 위 `{top[0]['account']}`는 {top[0]['n']}번). "
      "거래 몇 번의 큰 익절은 운으로 얼마든지 나옵니다.")
    w(f"- 상위 20개 중 동전 계좌가 {n_top_coin}개입니다. 상위 20개는 {len(picks_top)}개 후보에서만 나왔습니다"
      f"({', '.join(f'{k} {v}개' for k, v in sorted(picks_top.items(), key=lambda x: -x[1])[:5])}). 같은 신호를 나눠 쓰는 종류들이 함께 올라온 것이라, "
      "20개의 서로 다른 증거가 아닙니다.")
    cr = coin.get("coin_ret") or {}
    w(f"- 비교 기준: 동전 계좌 {cr.get('n')}개(거래한 것)의 수익률 가운데값 {pct(cr.get('median'))}, 상위 10% {pct(cr.get('p90'))}, 최고 {pct(cr.get('max'))}, "
      f"플러스 {cr.get('pos')}개. 진짜 계좌의 상위권도 동전 계좌의 상위권과 크기가 비슷합니다.")
    w("")
    w("### 3-3. 후보(픽) 49개: 26종류를 합친 결과")
    w("")
    rows = []
    for p in sorted(res["picks"], key=lambda x: -x["total"]):
        rows.append([f"`{p['pick']}`", f"{p['strategy_ko']} {p['tf']}", "약한 단서" if p["tier"] == "weak" else "관찰", p["traded"], p["trades"], usd(p["total"]),
                     f"{p['kinds_pos']}/{p['traded']}", pct(p.get("ld_ret")) if p.get("ld_n") else "거래 없음",
                     pct(p.get("fq_ret")) if p.get("fq_n") else "거래 없음", pct(p.get("ldc_ret")) if p.get("ldc_n") else "거래 없음",
                     f"{p['rejected_ld']}/{p['offered_ld']}", pct(p.get("test_mean_5y"), 2) if p.get("test_mean_5y") is not None else "—"])
    w(table(["후보", "매매법", "구분", "거래한 계좌", "거래", "합계", "플러스 종류", "대조", "빠른 손절", "대조 동전", "대조 거절/신호", "5년 시험 거래당(원래 청산)"], rows))
    w("")
    w("- '5년 시험 거래당'은 후보를 고를 때의 숫자(2024~2026, 그 후보의 원래 청산 · $5,000 · 20배 허용)입니다. 딥시크는 두 분 규칙(D11)대로 금액을 적지 않습니다.")
    w("")

    # =========================================================================================== 4
    w("## 4. 맞대결: 리그가 만들어진 이유인 비교")
    w("")
    w("비교는 모두 **같은 신호 짝**으로 합니다: 같은 후보 · 같은 코인 · 같은 방향 · 같은 진입 분에 두 계좌가 다 들어간 거래끼리. "
      "들어간 자리가 같으니 차이는 청산(또는 방향)에서만 나옵니다. **운의 범위**는 날짜를 통째로 다시 뽑는 부트스트랩(90% 구간)과, "
      "'차이가 없다면 날마다의 차이 부호가 +든 −든 같다'는 부호 뒤집기 시험(정확 계산)으로 냅니다. 여러 개를 함께 보므로 **BH 보정(q)** 을 합니다. "
      "q<0.05여야 '운을 넘었다'고 씁니다.")
    w("")
    w("### 4-1. 미리 정한 판정 4개 (`docs/candleague-decision-protocol-ko.md`)")
    w("")
    w(f"판정은 **28일째({L.kst(prot.get('decide_ms'), '%m/%d') if prot.get('decide_ms') else '11/10'}) 한 번**입니다. 지금은 {days:.0f}일째 미리보기라 통과 · 실패를 말하지 않는 "
      "단계지만, 지금 숫자를 그 규칙(쌍 300개 이상, 홀름 보정 p<0.05, 평균 차이 플러스, 앞·뒤 절반 모두 플러스)에 대어 봤습니다.")
    w("")
    rows = []
    for r in prot["rows"]:
        rows.append([r["name"], r.get("n"), r.get("n_days"), pp(r.get("mean")), f"{pp(r.get('lo'))} ~ {pp(r.get('hi'))}", pv(r.get("p")), pv(r.get("p_holm")),
                     f"{pp(r.get('half1'))} / {pp(r.get('half2'))}", "통과 조건 충족" if r.get("pass_now") else "아니오"])
    w(table(["비교 (ROE 차이, 앞 − 뒤)", "쌍", "날", "평균 차이", "90% 구간", "p", "홀름 p", "앞 / 뒤 절반", "지금이면"], rows))
    w("")
    if prot.get("snapshot"):
        w("리그 대시보드가 같은 시각에 계산한 값(`snap/league.json` · decision):")
        w("")
        rows = [[f"{r['suffix']} vs {r['vs_suffix']}", r["n"], pp(r["mean_diff"]), f"{pp(r['ci_lo'])} ~ {pp(r['ci_hi'])}", pv(r["p_one_sided"]),
                 pv(r["p_holm"]), r["verdict_ko"]] for r in prot["snapshot"]]
        w(table(["비교", "쌍", "평균 차이", "90% 구간", "p", "홀름 p", "화면 판정"], rows))
        w("")
        w("평균 차이는 이 스크립트와 리그 화면이 소수점 끝까지 같습니다(구간과 p는 난수 씨앗이 달라 조금 다름).")
        w("")
    r4 = prot["rows"][3]
    w(f"- ④ BTC 추세 필터: 필터가 남긴 신호의 거래당 ROE {pct(r4.get('mean_kept'))} vs 버린 신호 {pct(r4.get('mean_dropped'))}. 남긴 쪽이 덜 잃었지만 둘 다 손실이고, "
      f"보정 뒤 p {pv(r4.get('p_holm'))}로 운의 범위입니다. 하락장에서 '추세 방향' = 대부분 숏이라 2-3의 시장 효과와 같은 것입니다.")
    proj = prot["rows"][0].get("n", 0) / max(days, 1) * 28
    proj4 = prot["rows"][3].get("n", 0) / max(days, 1) * 28
    w(f"- 지금 속도면 28일째 쌍 수는 ① 약 {proj:.0f}개, ④(버린 쪽) 약 {proj4:.0f}개로 예상됩니다"
      + (" — 300개 조건은 넘겠지만, 통과하려면 평균 차이가 플러스로 바뀌고 보정 뒤 p<0.05여야 합니다. 지금 방향(①②③ 마이너스)이면 통과 0이 될 가능성이 큽니다."
         if proj >= 300 else " — 300개에 못 미칠 수 있어 그러면 규칙상 '표본 부족 = 통과 아님'입니다."))
    w("")
    w(f"### 4-2. 청산 변형 vs 그 대조 ({len(var)}개, 보정 대상 {res['variants'].get('family', len(var))}개)")
    w("")
    w("대조: 계단 계열은 '대조(원래 방식, -ld)', 후보 원래 청산 계열은 '지금 청산(-e)', 빠른 손절 필터는 '빠른 손절(-fq)'. "
      "'같은 신호 거래당 차이'는 지갑 대비(%p). '후보별'은 계좌 전체 수익률로 본 승/패(같은 신호가 아닌 거래도 포함).")
    w("")
    rows = []
    for r in sorted(var, key=lambda r: -(r.get("mean_d_wallet") or -9)):
        rows.append([kname(r["variant"]), kname(r["control"]), r["n"], pp(r.get("mean_d_wallet")), f"{pp(r.get('ci_lo'))} ~ {pp(r.get('ci_hi'))}",
                     f"{r.get('better')}/{r.get('worse')}/{r.get('same')}", pv(r.get("p2")), "같은 청산" if r.get("same_exit") else pv(r.get("q")),
                     f"{pp(r.get('half1'))} / {pp(r.get('half2'))}",
                     f"{r['picks_better']}승 {r['picks_worse']}패 / {r['picks']}", f"{usd(r['total_v'])} vs {usd(r['total_c'])}"])
    w(table(["변형", "대조", "같은 신호 쌍", "거래당 차이", "90% 구간", "나음/나쁨/같음", "p(양쪽)", "BH q", "앞 / 뒤 절반", "후보별", "계좌 합계 (변형 vs 대조)"], rows))
    w("")
    w(f"- **운을 넘은 것: {len(beat_var)}개.** 필터 4개와 주말 쉬는 계좌는 같은 신호에서 청산이 똑같아 차이가 0이 정상이라 보정 대상에서 뺐습니다"
      "(필터의 효과는 '어떤 신호를 버렸나'라서 4-1의 ④와 '후보별' · '계좌 합계' 칸으로 봅니다). 필터 계좌는 신호를 덜 받아 계좌 합계로는 덜 잃었습니다.")
    w("- 고정 익절 +10%(-tp10)는 같은 신호에서 대조보다 거래당 조금 나았고(일찍 나와 큰 손실 전에 익절), 4시간 제한(-ts) · 추적 손절(-ch)은 '지금 청산'의 "
      "큰 손실을 줄였습니다. 하지만 보정 뒤에는 모두 운의 범위이고, 셋 다 **계좌 합계는 여전히 손실**입니다. 이전 분석(10/17)에서도 -tp10은 '페이퍼 비교 1순위'였는데, "
      "그 방향(조금 덜 잃음)은 그대로입니다.")
    w("")
    w("### 4-3. 진짜 계좌 vs 동전 짝 (방향 실력)")
    w("")
    w("동전 짝은 같은 신호 시각에 같은 청산으로 들어가되 롱/숏만 동전으로 정한 계좌입니다. 같은 코인 · 같은 진입 분으로 짝을 짓습니다(방향은 다를 수 있음).")
    w("")
    rows = []
    for r in coin["kinds"]:
        rows.append([kname(r["real"]), r["n"], pct(r.get("agree_share"), 0, False), pp(r.get("mean_d_wallet")), f"{pp(r.get('ci_lo'))} ~ {pp(r.get('ci_hi'))}",
                     pv(r.get("p_better")), pp(r.get("d_wallet_disagree")), f"{r['picks_better']}승 {r['picks_worse']}패 / {r['picks']}"])
    w(table(["진짜 계좌", "쌍", "방향이 같았던 비율", "거래당 차이(진짜 − 동전)", "90% 구간", "p(진짜가 낫다)", "방향이 달랐던 거래만", "후보별 수익률"], rows))
    w("")
    sig_c = [p for p in coin["picks"] if p.get("q") is not None and p["q"] < 0.05]
    w(f"- **진짜가 동전보다 나은 것: 종류 단위 {len(beat_coin)}개, 후보 단위(98개 비교, BH) {len(sig_c)}개.** 방향이 동전과 달랐던 거래만 보면 진짜 쪽이 더 나빴습니다. "
      "즉 매매법이 고른 방향이 무작위 방향보다 나았다는 증거가 없습니다(5년 연구의 결론과 같음).")
    w("")
    if cvd:
        w("### 4-4. 커스텀값 vs 기본값 (규칙봇과 비교)")
        w("")
        w(f"이 리그에는 기본값 계좌가 없어서, 같은 기간 규칙봇의 같은 매매법 · 같은 봉 계좌(기본값, 규칙봇 계단 12%→10%, 2 ATR 손절, 20~50배, $5,000)와 비교했습니다. "
          "커스텀값 쪽은 청산이 가장 비슷한 '대조(-ld)'입니다. 크기 · 배수가 달라서 **R(처음 손절 거리 = 1) 단위의 비용 후 손익**으로 비교합니다. "
          f"규칙봇 자료: `paperbot_export` (끝 {L.kst(cvd.get('rb_end_ms'))}).")
        w("")
        rows = [["커스텀값봇 대조(-ld)", num(cvd.get("n_custom")), f"{cvd.get('per_day_custom', 0):.1f}", pct(cvd.get("win_custom"), 0, False), rr(cvd.get("mean_r_custom"))],
                ["규칙봇(기본값)", num(cvd.get("n_default")), f"{cvd.get('per_day_default', 0):.1f}", pct(cvd.get("win_default"), 0, False), rr(cvd.get("mean_r_default"))]]
        w(table(["", "거래", "하루", "승률", "거래당 R"], rows))
        w("")
        pw = cvd.get("pooled_wallet") or {}
        w(f"- 차이(커스텀 − 기본): **{rr(cvd_pooled.get('diff'))}** (90% {rr(cvd_pooled.get('lo'))} ~ {rr(cvd_pooled.get('hi'))}, p(커스텀이 낫다) {pv(cvd_pooled.get('p_pos'))}). "
          f"지갑 대비로는 거래당 {pp(pw.get('diff'))}. 후보별로 커스텀이 나았던 것 {cvd.get('picks_better')}/{cvd.get('picks_compared')}개(동전 던지기 수준).")
        sigp = [r for r in cvd["rows"] if r.get("q") is not None and r["q"] < 0.05]
        w(f"- 후보별 비교 중 BH 보정 뒤 의미 있는 차이: {len(sigp)}개.")
        w("- 커스텀값은 신호가 적고(5년 연구에서 고른 숫자가 조건을 까다롭게 만듦) 손절이 넓어 30배 · 15% 손실 한도에서 거절이 많습니다. 10/17 분석의 결론"
          "(차이 없음 → 기본값)과 같은 방향이고, 이번에는 커스텀 쪽이 약간 나쁜 쪽으로 기울었습니다.")
        w("")
        rows = []
        for r in sorted(cvd["rows"], key=lambda r: -(r.get("diff_r") if r.get("diff_r") is not None else -99)):
            if not r.get("n_custom") and not r.get("n_default"):
                continue
            rows.append([f"`{r['pick']}`", r["strategy_ko"], r["n_custom"], r["n_default"], rr(r.get("r_custom")), rr(r.get("r_default")), rr(r.get("diff_r")),
                         pv(r.get("p2")), pv(r.get("q")), r.get("same_signal", "—")])
        w("<details><summary>후보별 표 (커스텀 vs 기본)</summary>")
        w("")
        w(table(["후보", "매매법", "커스텀 거래", "기본 거래", "커스텀 R", "기본 R", "차이", "p", "BH q", "같은 신호"], rows))
        w("")
        w("</details>")
        w("")
    w("### 4-5. 계좌 하나씩: 운을 넘은 계좌가 있나")
    w("")
    w(f"- 거래 10번 이상 계좌 {luck['tested']}개를 각각 '거래당 평균 > 0'으로 시험(날짜 묶음 부트스트랩).")
    w(f"- 보정 전 p<0.05: **{luck['raw_p05']}개** (아무 실력 없이도 약 {luck['expected_by_chance']:.1f}개 기대). BH 보정 뒤 q<0.05: **{luck['q05']}개**, q<0.10: {luck['q10']}개.")
    if luck.get("raw_p05_accounts"):
        rows = [[f"`{x['account']}`", x["n"], pct(x["mean_wallet"], 2), pv(x["p_pos"]), pv(x["q"]), pct(x["ret"])] for x in luck["raw_p05_accounts"]]
        w("")
        w(table(["계좌", "거래", "거래당", "p", "BH q", "수익률"], rows))
        w("")
        w("- 보정 전 p가 작은 계좌들은 모두 같은 후보(레인지 필터 3중 일치 1시간)의 다른 종류입니다. 같은 신호 16~19번의 결과라 사실상 증거 하나입니다.")
    w("")

    # =========================================================================================== 5
    w("## 5. 안정성: 앞 절반 · 뒤 절반 · 최근 3일")
    w("")
    w(f"기간 가운데({L.kst(st['mid_ms'])} KST)로 나눴습니다. 최근 3일은 {L.kst(P['done_ms'] - 3 * L.DAY_MS)} 이후 끝난 거래입니다.")
    w("")
    rows = []
    for k in st["kinds_halves"]:
        rows.append([kname(k["suffix"]), f"{k['h1'].get('n', 0)} · {usd(k['h1'].get('pnl'))} · {pct(k['h1'].get('mean_wallet'), 2)}",
                     f"{k['h2'].get('n', 0)} · {usd(k['h2'].get('pnl'))} · {pct(k['h2'].get('mean_wallet'), 2)}",
                     f"{k['last3'].get('n', 0)} · {usd(k['last3'].get('pnl'))} · {pct(k['last3'].get('mean_wallet'), 2)}"])
    w(table(["종류", "앞 절반 (거래 · 손익 · 거래당)", "뒤 절반", "최근 3일"], rows))
    w("")
    n_h = sum(1 for k in st["kinds_halves"] if (k["h1"].get("pnl") or 0) > 0 and (k["h2"].get("pnl") or 0) > 0)
    n_l3 = sum(1 for k in st["kinds_halves"] if (k["last3"].get("pnl") or 0) > 0)
    w(f"- 두 절반 모두 플러스인 종류: **{n_h}개**. 최근 3일 플러스인 종류: {n_l3}개 (최근 3일에는 시장이 크게 흔들려 계단 잠금이 많이 나왔습니다).")
    w(f"- 계좌 단위: 거래 10번 이상 {st['n10']}계좌 중 두 절반 모두 플러스 **{st['both_halves_pos']}개**. 앞 절반 거래당 순위와 뒤 절반 순위의 상관 "
      f"**{num(st.get('rank_corr_halves'), 2)}** ({st.get('rank_corr_n')}계좌, 각 절반 5번 이상). 앞 절반 상위 10개 중 뒤 절반에도 플러스: {st['top10_h1_pos_h2']}개.")
    w("- 즉 '지금까지 잘한 계좌를 고르면 앞으로도 잘한다'는 근거가 이 기록에는 없습니다. 10/17 분석(상관 −0.63)과 같은 방향입니다.")
    w("")

    # =========================================================================================== 6
    if cond.get("real"):
        w("## 6. 조건별로 고르면 나아지나? (앞 절반에서 고르고 뒤 절반에서 확인)")
        w("")
        w(f"계좌마다(거래 {cond['min_total']}번 이상, {cond['accounts']}계좌) 조건 칸을 나눴습니다: 방향 · 코인 · 시간대 · BTC 4시간 추세와 같은 방향인지 · "
          f"변동성 보통인지 · 평일/주말. **앞 절반에서 거래 {cond['min_cell']}번 이상이고 거래당 플러스인 칸을 '골랐다'고 정하고(규칙을 먼저 정함)**, 뒤 절반에서 "
          "그 칸이 어땠는지 봤습니다. 같은 일을 동전 계좌에도 해서 '운만으로 버티는 비율'을 함께 냅니다.")
        w("")
        ru, cc = cond["real_unique"], cond["coin_unique"]
        rows = [["진짜 계좌 (같은 신호 중복 뺌)", ru["picked"], f"{ru['held']} ({pct(ru['held_share'], 0, False)})", pct(ru["m1"], 2), pct(ru["m2"], 2), usd(ru["p2_sum"])],
                ["동전 계좌 (운의 기준)", cc["picked"], f"{cc['held']} ({pct(cc['held_share'], 0, False)})", pct(cc["m1"], 2), pct(cc["m2"], 2), usd(cc["p2_sum"])]]
        w(table(["", "고른 칸", "뒤 절반에도 플러스", "앞 절반 거래당", "뒤 절반 거래당", "뒤 절반 손익 합"], rows))
        w("")
        rows = []
        for d in cond["by_dim"]:
            x, y = d["real_unique"], d["coin"]
            rows.append([d["dim"], x.get("picked", 0), f"{x.get('held', 0)} ({pct(x.get('held_share'), 0, False)})", pct(x.get("m2"), 2),
                         f"{y.get('held', 0)}/{y.get('picked', 0)}" if y.get("picked") else "—"])
        w(table(["조건", "고른 칸(진짜)", "뒤 절반 플러스", "뒤 절반 거래당", "동전: 플러스/고른 칸"], rows))
        w("")
        w(f"- 앞 절반에서 좋아 보인 칸이 뒤 절반에도 플러스였던 비율은 진짜 계좌 {pct(ru['held_share'], 0, False)}, 동전 계좌 {pct(cc['held_share'], 0, False)}입니다. "
          "고른 칸들의 뒤 절반 거래당은 마이너스입니다. 조건으로 걸러서 이기는 계좌를 만들 수 있다는 근거는 이 11일에 없습니다.")
        sess = next((d for d in cond["by_dim"] if d["dim"].startswith("시간대")), None)
        if sess and sess["real_unique"].get("held_share", 0) >= 0.6:
            x = sess["real_unique"]
            w(f"- 예외처럼 보이는 것: **시간대** 칸은 {x['picked']}개 중 {x['held']}개가 뒤 절반에도 플러스였습니다(뒤 절반 거래당 {pct(x['m2'], 2)}). 대부분 "
              "'미국 시간(한국 22~06시)'이고, 2-8표처럼 리그 전체에서도 그 시간대가 가장 덜 잃었습니다. 칸 수가 적고(한 후보의 여러 종류가 겹침) 동전 계좌의 같은 "
              "시간대도 덜 잃었기 때문에, **다음에 미리 정해서 시험할 아이디어**이지 지금 쓸 규칙은 아닙니다.")
        bh_ = cond.get("both_halves") or {}
        w(f"- 두 절반 모두 플러스인 칸(각 5번 이상): 진짜 {bh_.get('real')}/{bh_.get('real_of')}칸, 동전 {bh_.get('coin')}/{bh_.get('coin_of')}칸. 비율이 비슷합니다.")
        w("")
        if cond.get("both_list"):
            rows = [[f"`{x['account']}`", x["dim"], x["cell"], f"{x['n1']} · {pct(x['m1'], 2)}", f"{x['n2']} · {pct(x['m2'], 2)}"] for x in cond["both_list"][:15]]
            w("<details><summary>두 절반 모두 플러스였던 칸 (상위 15)</summary>")
            w("")
            w(table(["계좌", "조건", "칸", "앞 절반 (거래 · 거래당)", "뒤 절반"], rows))
            w("")
            w("</details>")
            w("")
        w("칸 전체: `out/cond_cells.csv`.")
        w("")

    # =========================================================================================== 7
    w("## 7. 5년 기록과 대조 (좋아 보이는 계좌)")
    w("")
    w(f"'좋아 보이는 계좌'는 미리 정한 기준으로 고릅니다: **수익률 플러스, 거래 10번 이상, 앞·뒤 절반 모두 플러스.** {len(good)}개가 해당합니다: "
      + ", ".join(f"`{x}`" for x in good) + ".")
    w("")
    if echeck:
        allm = echeck["matched"] == echeck["real"] == echeck["replay"]
        extra_txt = "" if allm else f" (실제에만 {echeck['only_real']}번, 다시 돌린 쪽에만 {echeck['only_replay']}번)"
        w(f"**계산 도구 확인**: 5년 계산은 리그 엔진 코드를 그대로 씁니다. 같은 방법으로 리그 기간({L.kst(echeck['start_ms'])} ~ {L.kst(echeck['end_ms'])})을 다시 돌려 "
          f"실제 리그 기록과 맞춰 보니 {len(echeck.get('accounts', []))}계좌의 실제 거래 {echeck['real']}번 중 **{echeck['matched']}번이** 같은 진입(코인 · 방향 · 분)으로 "
          f"다시 나왔고{extra_txt}, 그중 같은 청산 이유 "
          f"{echeck['same_reason']}번, 청산 분까지 같은 것 {echeck['same_exit_minute']}번입니다. 손익 합은 {usd(echeck['sum_pnl_real'])} vs {usd(echeck['sum_pnl_replay'])}입니다. "
          "손익 차이는 10월 마크 가격 · 펀딩을 공개 자료에서 받지 못한 것에서 오고, 거래 하나가 빠지거나 더해지면 그 뒤 계좌 크기가 달라져 그 계좌의 손익이 "
          "조금씩 벌어집니다."
          + (" 짝이 안 맞은 거래는 " + ", ".join(sorted({u['account'] for u in echeck.get('unmatched', [])})) + "에서 나왔습니다(신호 하나가 자료 출처 — 거래소 실시간 봉 "
             "vs 공개 보관 봉 — 의 작은 차이로 다르게 나온 뒤 그 계좌의 다음 거래가 갈림)." if echeck.get("unmatched") else "")
          + " 진입과 청산의 모양은 같으므로, 5년 숫자는 리그가 그 기간에 돌았다면 냈을 숫자로 봐도 됩니다.")
        w("")
    if fivey and fivey.get("windows"):
        wins = [x for x in ("2020", "2021-2023", "2024-2026") if x in fivey["windows"]]
        w("창마다 $1,000에서 새로 시작(배수 50·40·30배, 손실 15% 한도, 서버와 같은 설정). 딥시크(ds-)는 두 분 규칙(D11)대로 금액 없이 "
          "부호(+/−) · 거래 수 · 승률 · 플러스였던 해만 적습니다(금액은 저장소 밖 파일에만).")
        w("")
        head = ["계좌", "11일 (거래 · 거래당)"] + [fivey.get("window_ko", {}).get(x, x) for x in wins]
        rows = []
        for aid in fivey["accounts"]:
            a = acc.get(aid, {})
            cells = [f"`{aid}`" + (" ★" if aid in good else ""), f"{a.get('n', 0)} · {pct(a.get('mean_wallet'), 2)}"]
            for x in wins:
                d = fivey["windows"][x].get(aid) or {}
                if not d or not d.get("n"):
                    cells.append("거래 없음")
                    continue
                yrs = f" · 플러스였던 해 {d.get('years_pos')}/{d.get('years')}(거래한 해)" if d.get("years") else ""
                if aid.startswith("ds-"):
                    cells.append(f"{d['n']}번 · 승률 {pct(d.get('win'), 0, False)} · 거래당 {d.get('mean_wallet_sign', '?')} · "
                                 f"{'늘어남' if d.get('grew') else '줄어듦'}{bust_txt(d)}{yrs}")
                else:
                    cells.append(f"{d['n']}번 · 승률 {pct(d.get('win'), 0, False)} · 거래당 {pct(d.get('mean_wallet'), 2)} · "
                                 f"$1,000→{usd(d.get('wallet')).replace('+', '')} · 낙폭 {pct(d.get('mdd'), 0, False)}{bust_txt(d)}{yrs}")
            rows.append(cells)
        w(table(head, rows))
        w("")
        w("★ = 11일 기록에서 좋아 보인 계좌. 같은 후보의 대조(-ld)와 대조 동전(-ldc)을 옆에 두었습니다.")
        w("")
        npos = 0
        nall = 0
        for aid in good:
            d = (fivey["windows"].get("2024-2026") or {}).get(aid) or {}
            if not d.get("n"):
                continue
            nall += 1
            if (aid.startswith("ds-") and d.get("mean_wallet_sign") == "+") or (not aid.startswith("ds-") and (d.get("mean_wallet") or 0) > 0):
                npos += 1
        w(f"- 좋아 보인 {len(good)}개 중 2024~2026(가장 최근 2년 9개월)에 거래당 플러스였던 것: **{npos}/{nall}개**.")
        for wn in wins:
            dd_ = fivey["windows"][wn]
            bl = [x for x in fivey["accounts"] if (dd_.get(x) or {}).get("bust")]
            ms_ = sorted((dd_.get(x) or {}).get("months_to_bust") for x in bl if _ok((dd_.get(x) or {}).get("months_to_bust")))
            pos_ = [x for x in fivey["accounts"] if (dd_.get(x) or {}).get("n") and (((dd_.get(x) or {}).get("mean_wallet_sign") == "+") if x.startswith("ds-")
                                                                                  else ((dd_.get(x) or {}).get("mean_wallet") or 0) > 0)]
            w(f"- {fivey.get('window_ko', {}).get(wn, wn)}: {len(fivey['accounts'])}계좌 중 거래당 플러스 {len(pos_)}개, 파산(잔고가 바닥) {len(bl)}개"
              + (f" (파산까지 가운데 {ms_[len(ms_) // 2]:.0f}개월)" if ms_ else "") + ".")
        drag = [(x, wn) for wn in wins for x in fivey["accounts"] if ((fivey["windows"][wn].get(x) or {}).get("mean_wallet_sign") == "+"
                                                                       and (fivey["windows"][wn].get(x) or {}).get("grew") is False)
                or (not x.startswith("ds-") and ((fivey["windows"][wn].get(x) or {}).get("mean_wallet") or 0) > 0
                    and ((fivey["windows"][wn].get(x) or {}).get("wallet") or 0) < 1000)]
        if drag:
            w(f"- **거래당 평균이 플러스여도 계좌는 줄 수 있습니다**: " + ", ".join(f"`{x}`({wn})" for x, wn in drag[:6])
              + "가 그렇습니다. +10%와 −10%를 번갈아 내면 평균은 0이지만 계좌는 1.1 × 0.9 = 0.99로 줄어듭니다. 손절 한 번에 지갑의 10~15%가 나가는 크기에서는 "
              "이 효과가 커서, 거래당 평균이 조금 플러스인 정도로는 계좌가 크지 않습니다.")
        w("- 파산은 엔진 규칙대로 잔고가 시작의 약 1%(약 $10) 아래로 내려가 더 들어갈 수 없게 된 것입니다. 거래 수는 파산 전까지만 셉니다.")
        w("- 주의: 이 후보들의 커스텀값은 2021~2023으로 골랐고, 관찰 후보 목록은 2024~2026과 2020 성적을 보고 골랐습니다(원래 청산 기준). 그래서 5년 숫자는 "
          "청산을 바꾼 것만 빼면 '이미 본 기간'입니다. 플러스여도 좋게 기운 숫자이고, 마이너스면 더 나쁜 신호입니다.")
        w("")
    else:
        w("5년 계산 결과 파일(`out/fivey.json`)이 아직 없습니다. `run_all.py`가 만듭니다(1분봉 5년 자료 필요).")
        w("")
    w("**후보를 고를 때의 5년 숫자 (원래 청산, `etc/candidates.json`)**: 좋아 보인 계좌의 후보 중 규칙봇 쪽만 금액을 적습니다.")
    w("")
    gp = sorted({acc[x]["pick"] for x in good})
    pk = {p["pick"]: p for p in res["picks"]}
    rows = []
    for p in gp:
        x = pk.get(p, {})
        rows.append([f"`{p}`", x.get("strategy_ko"), str(x.get("cand_exit") or "").replace("|", " · "), num(x.get("test_n_5y")),
                     pct(x.get("test_mean_5y"), 2) if x.get("test_mean_5y") is not None else ("딥시크: 금액 없음(D11)" if p.startswith("ds-") else "—")])
    w(table(["후보", "매매법", "원래 청산", "5년 시험 거래 수", "시험 기간 거래당"], rows))
    w("")

    # =========================================================================================== 8
    w("## 8. 목표 경로: 한 달 +500% (×6)에 닿을 수 있나")
    w("")
    w("두 분 목표는 '한 달 500% 이상'입니다. 그래서 '불가능' 한 마디 대신, 지금 기록으로 갈 수 있는 가장 좋은 길을 계산했습니다.")
    w("")
    w("**계산 방법** (쉬운 말):")
    w("- 계좌의 실제 거래를 그대로 씁니다. 거래 하나의 결과를 '포지션 크기 대비 순수익'(비용 포함)으로 바꿔 두고, 배수와 증거금을 바꾸면 지갑이 얼마나 "
      "움직였을지 다시 계산합니다. 지갑 변화 = 증거금 비율 × 배수 × 그 거래의 순수익.")
    w("- 그 거래가 들고 있는 동안 가장 불리했던 가격이 '그 배수의 강제청산 거리'(1 ÷ 배수 − 0.5%)에 닿았으면 강제청산으로 증거금 전부를 잃은 것으로 봅니다.")
    w(f"- 11일의 하루하루를 무작위로 뽑아 30일을 {goal.get('paths', 4000):,}번 만들어(부트스트랩) **30일 안에 ×6에 닿는 비율**, 그 전에 **반토막(−50%)·−90%가 먼저 오는 비율**, 30일 뒤 가운데값을 셉니다.")
    w("- 한계: 배수를 바꾸면 계단 잠금(ROE 기준)이 다른 가격에서 걸려 청산 자체가 달라지는데 그것은 반영하지 못합니다. 그리고 **11일 · 거래 10~25번을 30일로 늘린 것**이라, "
      "'지난 11일이 똑같이 반복된다면'의 계산일 뿐 예측이 아닙니다. 거래 30번 미만은 '표본 작음'으로 적습니다.")
    w("")
    n_pos = sum(1 for r in goal["rows"] if r["mean_x"] > 0)
    w(f"- 거래 10번 이상 {len(goal['rows'])}계좌 중 거래당 평균이 플러스인 계좌: **{n_pos}개**. 나머지 {len(goal['rows']) - n_pos}개는 배수를 올릴수록 더 빨리 잃습니다"
      "(어떤 배수도 ×6로 가는 길이 없음).")
    w("")
    rows = []
    cand_rows = sorted([r for r in goal["rows"] if r["mean_x"] > 0], key=lambda r: -r["sims"]["40%x50"]["p_goal"])[:20]
    for r in cand_rows:
        s30, s40, s50 = r["sims"]["40%x30"], r["sims"]["40%x40"], r["sims"]["40%x50"]
        ks = r["sims"].get("kelly") or {}
        rows.append([f"`{r['account']}`" + (" ★" if r["account"] in good else "") + (" (동전)" if r["account"].endswith(("-ldc", "-fqc")) else ""),
                     f"{r['n']}{' 표본 작음' if r['small'] else ''}", f"{r['per_day']:.1f}", pct(r["mean_x"], 3), pct(r["mean_wallet"], 2),
                     f"{pct(s30['p_goal'], 0, False)} / {pct(s30['p_half_first'], 0, False)} / ×{s30['median']:.1f}",
                     f"{pct(s40['p_goal'], 0, False)} / {pct(s40['p_half_first'], 0, False)} / ×{s40['median']:.1f}",
                     f"{pct(s50['p_goal'], 0, False)} / {pct(s50['p_half_first'], 0, False)} / {pct(s50['p_tenth_first'], 0, False)} / ×{s50['median']:.1f}",
                     f"{r['kelly_lev']:.0f}배: {pct(ks.get('p_goal'), 0, False)} / {pct(ks.get('p_half_first'), 0, False)} / ×{ks.get('median', 0):.1f}" if ks else "—",
                     f"{r['liq_lev']:.0f}배" if r.get("liq_lev") else "—",
                     (f"{r['need_lev_at40']:.0f}배" + (" (강제청산 배수보다 큼)" if r.get("liq_lev") and r["need_lev_at40"] > r["liq_lev"] else ""))
                     if r.get("need_lev_at40") else "—"])
    w(table(["계좌", "거래", "하루", "거래당(포지션 대비)", "거래당(지갑, 실제)", "40%×30배: ×6 / 반토막 먼저 / 30일 가운데",
             "40%×40배", "40%×50배: ×6 / 반토막 / −90% / 가운데", "가장 빨리 크는 배수(40%): ×6 / 반토막 / 가운데", "가장 나쁜 거래가 강제청산되는 배수",
             "평균대로만 가면 ×6에 필요한 배수(40%)"], rows))
    w("")
    w("★ = 7장의 좋아 보이는 계좌. '(동전)' = 동전 짝 계좌(방향 무작위). 마지막 칸은 운(흔들림)을 빼고 평균만으로 계산한 배수입니다: 30일 거래 수 × 거래당 평균 × "
      "(증거금 40% × 배수)가 ln 6(약 1.79)이 되는 배수. 흔들림이 있으면 실제로는 이보다 더 필요하고, 그 배수에서 가장 나빴던 거래가 강제청산되면 그 길은 막힙니다.")
    w("")
    twins = []
    for r in cand_rows[:8]:
        a = acc[r["account"]]
        tw = f"{a['pick']}-ldc"
        if tw != r["account"] and tw in gl:
            twins.append((r["account"], tw, r["sims"]["40%x50"]["p_goal"], gl[tw]["sims"]["40%x50"]["p_goal"]))
    if twins:
        w("- **같은 후보의 동전 짝과 비교** (40%×50배에서 30일 안에 ×6 비율): " + "; ".join(f"`{a}` {pct(p, 0, False)} vs 동전 `{b}` {pct(q, 0, False)}" for a, b, p, q in twins)
          + ". 방향을 무작위로 정해도 비슷한 확률이 나온다는 것은, 이 숫자가 매매법의 실력이 아니라 **그 후보가 들어간 시각 · 시장 흐름**에서 나왔다는 뜻입니다.")
    ms = next((x for x in (res.get("records") or {}).get("rows", []) if x["key"].startswith("league.json · monthsim")), None)
    if ms:
        w(f"- 리그 대시보드의 '한 달 시뮬'(종류 전체 평균, 지금 배수): {ms['shows']}")
    w("- 정리: 거래당 평균이 플러스인 몇 안 되는 계좌도 거래 10~25번뿐이고 동전 짝과 구별되지 않습니다. 이 기록만 보고 40~50배로 키우면, 계산상으로는 ×6 확률이 "
      "있어 보여도 그것은 '지난 11일이 반복된다'는 가정의 숫자입니다. 5년 기록(7장)과 리그 전체(2장)는 이 매매법들이 비용을 넘는 방향 실력이 없다고 말합니다. "
      "+500%/월을 노리려면 먼저 **동전 짝을 이기는 신호**가 있어야 하고, 그것이 생기면 배수는 '가장 빨리 크는 배수'의 절반 이하로 잡는 것이 보통입니다"
      "(그 배수에서는 반토막 확률이 급히 늘어남).")
    w("")
    w("전체 계좌의 값: `out/goal_path.csv`.")
    w("")
    # ------------------------------------------------------------------ 8-2: every hopeful sign, each with its catch
    w("### 8-2. 희망이 보이는 곳 전부 (그리고 각각의 함정)")
    w("")
    w("두 분 말씀대로 '안 된다'로 끝내지 않고, 11일 기록에서 조금이라도 좋아 보이는 곳을 빠짐없이 모았습니다. 다음 시험(미리 정해서)의 후보 목록으로 쓰시면 됩니다.")
    w("")
    w(table(["어디", "좋아 보이는 숫자", "함정"], hope_rows))
    w("")
    w("- 이 목록의 어느 것도 '운을 넘었다'는 기준(보정 q<0.05)을 넘지 못했습니다. 그래서 돈을 거는 근거가 아니라 **다음 시험에서 미리 정해 둘 후보**입니다. "
      "예: '레인지 필터 3중 일치 1시간 · OBV 추세형 · 쓰리 아웃사이드 1시간을 대조 청산으로, 11/10까지 거래 30번 이상 쌓이면 동전 짝과 비교'처럼 지금 적어 두고 "
      "그 뒤 기록으로만 판단하면, 11일 숫자를 보고 고른 함정을 피할 수 있습니다.")
    w("")

    # =========================================================================================== 9
    w("## 9. 10/17 분석 이후 무엇이 바뀌었나")
    w("")
    rc = v17["recomputed"]
    w(f"10/17 분석(`docs/live1019-analysis-ko.md` 7-3)은 {L.kst(P['start_ms'])} ~ {L.kst(v17['cut_ms'])} 기록을 봤습니다. 같은 구간을 이번 스크립트로 다시 계산하면 "
      f"거래 {rc['trades']}번 · 거래한 계좌 {rc['traded_accounts']}개로 그때와 같습니다(그때: {v17['read']['trades']}번, {v17['read']['traded_accounts']}개).")
    w("")
    rows = []
    for sfx, key in (("fq", "fq_wallet"), ("ld", "ld_wallet"), ("fqc", "fqc_wallet"), ("ldt", "ldt_wallet"), ("ldc", None), ("tp10", None), ("sw", None)):
        b = rc["kinds"][sfx]
        a_ = after[sfx]
        rows.append([kname(sfx), pct(v17["read"][key], 2) if key else "—", f"{b.get('n', 0)} · {pct(b.get('mean_wallet'), 2)}",
                     f"{a_.get('n', 0)} · {pct(a_.get('mean_wallet'), 2)}", usd(a_.get("pnl"))])
    w(table(["종류", "10/17 보고서 거래당", "10/17까지 (다시 계산)", f"그 뒤 {v17['after']['days']:.1f}일 (거래 · 거래당)", "그 뒤 손익"], rows))
    w("")
    w(f"- 10/17까지 손실 종류 {v17['kinds_losing_before']}/26 → 그 뒤 {v17['kinds_losing_after']}/26.")
    w(f"- 10/17의 '빠른 손절은 대조보다 나쁨'은 그 뒤 차이가 줄었지만(같은 신호 차이 4-1 ① {pp(prot['rows'][0].get('mean'))}) 여전히 대조보다 낫지 않습니다.")
    w(f"- 10/17의 'BTC 추세 필터 +0.55%(하락장 효과)'는 그 뒤 {pct(after['ldt'].get('mean_wallet'), 2)}로 사라졌습니다. 그때 말한 대로 하락장 효과였습니다.")
    w(f"- 계좌 순위: 10/17까지와 그 뒤(각 3번 이상, {v17.get('rank_n')}계좌)의 손익 순위 상관 {num(v17.get('rank_corr'), 2)}. 10/17까지 상위 10개 중 그 뒤 플러스 "
      f"{v17.get('top10_old_pos_new')}개.")
    if res.get("prev"):
        pa = res["prev"]["after_all"]
        w(f"- 10/22 내보내기 뒤 {res['prev']['after_days']:.1f}일(새로 받은 부분): 거래 {pa.get('n')}번, 거래당 {pct(pa.get('mean_wallet'), 2)}, 손익 {usd(pa.get('pnl'))}, "
          f"비용 전 {usd(pa.get('gross'))}. 이 구간은 시장이 크게 흔들리며 계단 잠금이 잘 나와 덜 잃었습니다.")
    w("- 바뀌지 않은 것: 커스텀값 ≈ 기본값(또는 약간 나쁨), 방향 실력 0(동전 짝과 같음), 비용이 손실의 대부분.")
    w("")

    # =========================================================================================== 10
    w("## 10. 실거래 후보 (있나?)")
    w("")
    w("**기준 (숫자를 보기 전에 정한 순서)**: ① 끝난 거래 30번 이상 ② 거래당 평균이 운을 넘음(BH q<0.05) ③ 앞·뒤 절반 모두 플러스 "
      "④ 같은 후보의 동전 짝보다 나음 ⑤ 5년(2024~2026, 같은 엔진)도 거래당 플러스 ⑥ 지금 실행기로 그 청산을 따라갈 수 있음.")
    w("")
    mark = {True: "✔", False: "✘", None: "—"}
    rows = []
    for aid, c, tw in short:
        a = acc[aid]
        rows.append([f"`{aid}`", acct_label(a), mark[c["n30"]] + f" {a['n']}", mark[c["luck"]] + f" q {pv(a.get('q'))}", mark[c["halves"]],
                     mark[c["coin"]] + (f" {pct(a['ret'])} vs {pct(tw['ret'])}" if tw else ""), mark[c["five"]],
                     mark[c["exec"]] + " " + EXEC.get(a["suffix"], ("", ""))[0]])
    w(table(["계좌", "매매법 · 종류", "① 30번", "② 운", "③ 두 절반", "④ 동전 짝", "⑤ 5년", "⑥ 실행기"], rows))
    w("")
    if short:
        w("**두 분 방식의 크기 표** (증거금 40%일 때 손절 한 번에 지갑의 몇 %가 나가나 = 0.4 × 배수 × (손절 거리 + 왕복 비용 0.14%)):")
        w("")
        rows = []
        for aid, c, tw in short:
            a = acc[aid]
            sp = a.get("stop_pct_med") or 0
            rows.append([f"`{aid}`", pct(sp, 2, False), *(pct(0.4 * L_ * (sp + 0.0014), 0, False) for L_ in (30, 40, 50)),
                         f"{100 / (sp * 100 + 0.5):.0f}배" if sp else "—", pct(a.get("mdd_engine"), 0, False), pf(a.get("pf")), num(a.get("loss_streak")),
                         EXEC.get(a["suffix"], ("", ""))[1]])
        w(table(["계좌", "손절 거리(가운데)", "손절 1번 @30배", "@40배", "@50배", "손절보다 강제청산이 먼저 오는 배수(대략)", "최대 낙폭(11일)", "PF",
                 "최장 연패", "실행기로 따라가기"], rows))
        w("")
    if qualified:
        w(f"**기준을 다 넘은 계좌: {', '.join(q[0] for q in qualified)}**")
    else:
        names = {"n30": "①(거래 30번)", "luck": "②(운 검사)", "halves": "③(두 절반)", "coin": "④(동전 짝)", "five": "⑤(5년)", "exec": "⑥(실행기)"}
        all_fail = [names[k] for k in names if short and all(c.get(k) is False for _a, c, _t in short)]
        w("**결론: 기준을 다 넘은 계좌는 없습니다.**" + (f" 모든 계좌가 {' · '.join(all_fail)}에서 걸립니다." if all_fail else "")
          + " 11일 · 거래 20번 안팎으로는 실력과 운을 가를 수 없습니다." + (" 같은 설정을 2024~2026에 돌리면 모두 잃었습니다." if "⑤(5년)" in all_fail else ""))
    w("")
    if short:
        # closest: most criteria true, then return
        def score(s):
            return (sum(1 for v in s[1].values() if v is True), acc[s[0]]["ret"])
        cl = sorted(short, key=score, reverse=True)[0]
        a = acc[cl[0]]
        s30 = 0.4 * 30 * ((a.get("stop_pct_med") or 0) + 0.0014)
        s50 = 0.4 * 50 * ((a.get("stop_pct_med") or 0) + 0.0014)
        w(f"**가장 가까운 것: `{cl[0]}` ({acct_label(a)})**")
        w("")
        w(f"- 11일: 거래 {a['n']}번, 승률 {pct(a.get('win_rate'), 0, False)}, PF {pf(a.get('pf'))}, 수익률 {pct(a['ret'])}, 거래당 지갑 {pct(a.get('mean_wallet'), 2)}, "
          f"최대 낙폭 {pct(a.get('mdd_engine'), 0, False)}(1분 시가평가), 최장 연패 {num(a.get('loss_streak'))}번, 숏 {num(a.get('n_short'))}/{a['n']}.")
        w(f"- **두 분 방식으로 크기를 말하면**: 손절 거리 가운데값이 가격의 {pct(a.get('stop_pct_med'), 2, False)}라서, 증거금 40%로 손절 한 번이면 "
          f"30배에서 지갑의 약 {pct(s30, 0, False)}, 50배에서 약 {pct(s50, 0, False)}를 잃습니다(비용 포함). 50배면 손절 4번 연속에 지갑이 "
          f"{pct((1 - s50) ** 4 - 1, 0)}입니다. 그리고 손절 거리가 1 ÷ 배수에 가까워지면 손절 전에 강제청산이 먼저 옵니다(50배는 약 1.5%).")
        g_ = gl.get(cl[0])
        if g_:
            s = g_["sims"]["40%x40"]
            w(f"- 8장 계산(40%×40배): 30일 안에 ×6 {pct(s['p_goal'], 0, False)}, 반토막 먼저 {pct(s['p_half_first'], 0, False)}, 가운데 ×{s['median']:.1f} — 표본이 작아 참고만.")
        w("- 과적합 점검: 이 계좌는 1,188개 중 '좋아 보이는 것'을 고른 결과입니다. 1,188개 중 하나를 고르면 실력 없이도 이 정도는 나옵니다(3-2의 동전 계좌 최고와 비교). "
          "5년 숫자는 이미 본 기간이고, 앞으로의 기록(11/10 판정)이 유일한 깨끗한 시험입니다.")
        w(f"- 실행기: {EXEC.get(a['suffix'], ('', ''))[1]}.")
        w("")
    w("**권하는 것**: 실거래로 옮기지 말고 리그를 정해 둔 대로 11/10(28일째)까지 그대로 두세요. 그때 판정 4개와 이 보고서의 계좌들(특히 위 계좌들)이 "
      "새 17일에서도 같은 모습인지 보면 됩니다. 그 전에 꼭 실거래로 시험하고 싶으시면, '돈 버는 시험'이 아니라 '체결 확인용'으로 잃어도 되는 금액 · 20배 이하 · "
      "합친 봇으로 근사 가능한 종류(대조 계열)에서만 하는 것이 맞습니다.")
    w("")

    # =========================================================================================== 11
    rec = (res.get("records") or {}).get("rows", [])
    if rec:
        w("## 11. 리그가 남긴 다른 기록들 (거래 말고)")
        w("")
        w("압축 파일 안의 거래 외 기록을 모두 열어 봤습니다. 각각 무엇이고 무엇을 말하는지:")
        w("")
        rows = []
        for r in rec:
            nums = r.get("numbers") or {}
            short_n = json.dumps(nums, ensure_ascii=False)
            if len(short_n) > 260:
                short_n = short_n[:257] + "…"
            rows.append([r["key"], r["what"], (r["shows"] or "").replace("|", "/").replace("\n", " "), f"`{short_n}`" if nums else ""])
        w(table(["기록", "무엇", "말하는 것", "숫자"], rows))
        w("")
        ev = next((x for x in rec if x["key"].startswith("league.json · events")), None)
        if ev and ev.get("numbers"):
            bits = []
            for k, v in ev["numbers"].items():
                role, kind_ = k.split(":", 1)
                bits.append(f"{kname(role)} {dict(rule_exit='규칙 청산', narrowed='손절 좁힘', switch='스위칭').get(kind_, kind_)} {v['n']}번 중 대조보다 나은 것 "
                            f"{v['better']}번(평균 ROE 차이 {pp(v.get('mean_diff'))})")
            w("- 발동 기록(events, 최근 200건): " + "; ".join(bits) + ". 규칙이 발동한 거래에서도 대조보다 나은 경우가 절반 안팎입니다.")
        w("- 경고등(judge): 49개 '지금 청산' 계좌 모두 '판단 안 함'입니다. 거래가 10번에 못 미쳐서입니다(30배에서 넓은 손절이 거의 다 거절됨). 5년 예상 범위(밴드)와 "
          "비교할 수 있는 계좌가 하나도 없었습니다.")
        w("- 텔레그램: 아침 요약 말고는 알림(파산 · 경고등 · 엔진 멈춤)이 없었습니다. 기록 점검(dataq)도 '정상'.")
        w("- 조건별(conditions): 리그 화면도 36칸 중 동전 짝보다 확실히 나은 칸 0개, 나쁜 칸 4개(우연만으로 2개쯤)라고 말합니다. 6장과 같은 결론입니다.")
        w("")

    # =========================================================================================== 12
    w("## 12. 옆으로 치운 리그와 사본")
    w("")
    for d in res["dbs"]:
        if d["role"] != "set_aside":
            continue
        kk = d.get("kinds") or {}
        w(f"### `{d['name']}`")
        w("")
        w(f"- {L.kst(d['start_ms'])} ~ {L.kst(d['done_ms'])} KST ({(d['done_ms'] - d['start_ms']) / 3.6e6:.1f}시간), 계좌 {num(d['accounts'])}개 "
          f"(종류 {len(kk)}가지; 빠른 손절 계열 {kk.get('fq', 0)}개 = 약한 단서 11개에 구조 기준이 생기기 전). 들어온 신호 {d['offered']}, 진입 {d['entered']}, 거절 {d['rejected']}, "
          f"끝난 거래 {d['trades']}번 ({usd(d['pnl'])}), 멈출 때 열린 포지션 {d['open_positions']}개.")
        if d.get("trade_detail"):
            for t in d["trade_detail"]:
                w(f"  - 끝난 거래: `{t['account']}` {t['symbol']} {'롱' if t['side'] > 0 else '숏'} {t['leverage']}배 {L.EXIT_KO.get(t['exit_reason'], t['exit_reason'])} {usd(t['pnl'])}")
        if d["name"].startswith("20x"):
            w("- 이름의 '20x'는 '20배까지 허용하던 설정으로 켰던 리그'라는 표시로 보입니다(10/13 오후 '최소 30배' 설정 전). 1시간 만에 바뀌어 끝난 거래가 없습니다.")
        w("- 너무 짧아서 성적으로 읽을 것은 없습니다. 지금 리그와 계좌 구성이 달라 이어 붙이지 않았습니다.")
        w("")
    cps = [d for d in res["dbs"] if d["role"] == "set_aside_copy"]
    if cps:
        w("- " + ", ".join(f"`{d['name']}`" for d in cps) + ": 위 옆으로 치운 리그의 더 짧은 사본"
          + (" (앞부분이 같음)." if all((d.get("same_as_prefix") or {}).get("same") for d in cps) else " (일부 다름)."))
    w("- `league_exits_from_1013_*.db` 3개: 지금 리그를 업데이트할 때 남긴 사본(10/13 17:15, 10/13 22:45, 10/15 12:25 KST까지). 거래가 지금 리그와 하나하나 "
      "같아서 따로 분석하지 않았습니다(1-1).")
    w("")

    # =========================================================================================== 13
    w("## 13. 말 풀이")
    w("")
    terms = [("ROE", "증거금 대비 수익률. 30배에서 가격 1% = ROE 30%."), ("지갑 대비(거래당)", "거래 하나가 그 순간 계좌 잔고를 몇 % 바꿨나. 증거금 30%면 ROE의 약 0.3배."),
             ("R", "처음 손절까지의 거리를 1로 본 단위. −1R = 손절 한 번."), ("PF(손익비)", "이긴 돈 합 ÷ 진 돈 합. 1보다 작으면 손실."),
             ("최대 낙폭", "계좌가 가장 높았던 때에서 가장 많이 내려간 비율(1분마다 시가평가)."), ("최장 연패", "연속으로 진 거래 수의 최댓값."),
             ("계단 잠금", "순수익이 +13%에 닿으면 +10%에 손절을 올려 이익을 잠그는 두 분 규칙(그 뒤 20→15, 25→20 …)."),
             ("동전 짝", "같은 시각 · 같은 청산으로 들어가되 롱/숏을 동전으로 정한 계좌. 이것보다 나아야 '방향 실력'."),
             ("같은 신호 짝", "두 계좌가 같은 후보 · 코인 · 방향 · 진입 분에 들어간 거래 한 쌍. 들어간 자리가 같아 청산 차이만 남음."),
             ("부트스트랩(날짜 묶음)", "하루를 한 덩어리로 보고 날짜를 다시 뽑아 수천 번 계산해 '운으로 얼마나 흔들리나'를 재는 방법. 같은 날 거래는 서로 닮아서 묶음."),
             ("p", "실력이 없어도 이만큼 좋은 결과가 나올 확률. 작을수록 운이 아닐 가능성."),
             ("BH 보정(q)", "여러 개를 함께 시험할 때 우연히 좋아 보이는 것을 걸러 주는 보정. q<0.05면 '운을 넘었다'."),
             ("홀름 보정", "판정 4개에 쓰는 더 엄격한 보정(미리 정한 규칙)."),
             ("비용 전", "수수료 · 미끄러짐 · 펀딩을 빼기 전 손익. 매매법 자체의 방향·타이밍 결과."),
             ("시장 몫", "포지션을 든 동안 6코인 평균이 움직인 만큼 × 방향 × 크기. 시장 전체 흐름으로 설명되는 부분.")]
    w(table(["말", "뜻"], [[a, b] for a, b in terms]))
    w("")

    # =========================================================================================== 14/15
    w("## 14. 파일")
    w("")
    w(table(["파일", "무엇"], [
        ["`REPORT_KO.md`", "이 보고서"], ["`APPENDIX_ACCOUNTS_KO.md`", "1,188계좌 전체 표"],
        ["`daily_pnl.csv`", "계좌 × 한국 날짜별 손익 · 거래 수 (account_id, day_kst, pnl, trades)"],
        ["`trades_norm.csv`", "거래 하나씩 (account_id, strategy, timeframe, symbol, side(+1 롱/−1 숏), entry_ms, exit_ms, entry_price, exit_price, pnl, return_on_margin, leverage, exit_reason)"],
        ["`out/results.json`", "모든 계산 결과"], ["`out/accounts.csv` · `out/trades.csv`", "계좌 표 · 거래 표(비용 · 시장 몫 포함)"],
        ["`out/variants_vs_control.csv` · `out/coin_twin_by_pick.csv` · `out/custom_vs_default.csv`", "맞대결 표"],
        ["`out/cond_cells.csv` · `out/goal_path.csv`", "조건별 칸 · 목표 경로"], ["`out/fivey.json` · `out/engine_check.json`", "5년 계산 · 엔진 재현 확인"],
        ["`run_all.py` → `analyze.py` · `extras.py` · `fivey.py` · `engine_check.py` · `report.py` · `lg_lib.py` · `market.py`", "스크립트"]]))
    w("")
    w("## 15. 다시 만들기 (새 내보내기를 받으면)")
    w("")
    w("```bash")
    w("cd analysis/review1024/league")
    w("python3 run_all.py --zip <새 league_export.zip> --rulebot-zip <같은 때 paperbot_export.zip> \\")
    w("    --work <새 빈 폴더> --fg1m <5년 1분봉 폴더(research/fullgrid/data.py의 1m)> [--prev-zip <이전 league_export.zip>]")
    w("```")
    w("- 압축 파일은 새 빈 폴더에만 풀고(이름 검사), 그 안의 어떤 것도 실행하지 않으며, 기록 파일은 읽기 전용으로만 엽니다.")
    w("- `--fg1m`이 없으면 5년 계산(7장)과 엔진 재현 확인을 건너뛰고 나머지는 그대로 만듭니다. 시세는 data.binance.vision 공개 1분봉을 받아 둡니다.")
    w("")
    return "\n".join(out) + "\n"


def appendix(res: dict) -> str:
    out = ["# 부록: 커스텀값봇 계좌 1,188개 전체 표", "",
           f"기간 {L.kst(res['period']['start_ms'])} ~ {L.kst(res['period']['done_ms'])} KST ({res['period']['days']:.2f}일). 종류별로 나눴고, 각 종류 안에서 수익률 순입니다. "
           "수익률·손익은 열린 포지션 평가손익(끝 시각 가격)을 포함합니다. '거래당'은 지갑 대비. '최대 낙폭'은 엔진의 1분 시가평가 값. "
           "'앞 / 뒤'는 기간 가운데 전후로 끝난 거래의 손익. '운 p'는 거래 10번 이상만(날짜 묶음 부트스트랩, '거래당 > 0'), q는 130계좌 BH 보정.", ""]
    accs = res["accounts"]
    for sfx in L.KIND_ORDER:
        rows_ = sorted([a for a in accs if a["suffix"] == sfx], key=lambda a: -a["ret"])
        out.append(f"## {kname(sfx)} (`-{sfx}`, {len(rows_)}계좌)")
        out.append("")
        out.append(f"{L.KINDS[sfx][2]}")
        out.append("")
        rr_ = []
        for a in rows_:
            if not a.get("n"):
                rr_.append([f"`{a['account']}`", f"{a['strategy_ko']} {a['tf']}", 0, "—", "—", "—", "—", pct(a["ret"]), "—", "—", "—", "—", "—",
                            f"신호 {a['offered']} · 거절 {a['rejected']}" + (" · 열림" if a.get("open") else "")])
                continue
            rr_.append([f"`{a['account']}`", f"{a['strategy_ko']} {a['tf']}", a["n"], pct(a.get("win_rate"), 0, False),
                        f"{pct(a.get('avg_win_roe'), 0)} / {pct(a.get('avg_loss_roe'), 0)}", f"{usd(a.get('avg_win_usd'))} / {usd(a.get('avg_loss_usd'))}",
                        pf(a.get("pf")), pct(a["ret"]), pct(a.get("mean_wallet"), 2), pct(a.get("mdd_engine"), 0, False),
                        f"{num(a.get('n_long'))}·{usd(a.get('pnl_long'))} / {num(a.get('n_short'))}·{usd(a.get('pnl_short'))}",
                        f"{usd(a.get('pnl_h1'))} / {usd(a.get('pnl_h2'))}", num(a.get("loss_streak")),
                        (pv(a.get("p_pos")) + (f" q{pv(a.get('q'))}" if a.get("q") is not None else "")) if a.get("p_pos") is not None else
                        f"신호 {a['offered']} · 거절 {a['rejected']}"])
        out.append(table(["계좌", "매매법", "거래", "승률", "평균 이익/손실 ROE", "평균 이익/손실 $", "PF", "수익률", "거래당", "최대 낙폭",
                          "롱(수·$) / 숏(수·$)", "앞 / 뒤 절반", "최장 연패", "운 p / 메모"], rr_))
        out.append("")
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--dest", default=HERE)
    a = ap.parse_args()
    res = L.read_json(os.path.join(a.out, "results.json"))
    fy = os.path.join(a.out, "fivey.json")
    ec = os.path.join(a.out, "engine_check.json")
    fivey = L.read_json(fy) if os.path.exists(fy) else None
    echeck = L.read_json(ec) if os.path.exists(ec) else None
    with open(os.path.join(a.dest, "REPORT_KO.md"), "w", encoding="utf-8") as f:
        f.write(build(res, fivey, echeck))
    with open(os.path.join(a.dest, "APPENDIX_ACCOUNTS_KO.md"), "w", encoding="utf-8") as f:
        f.write(appendix(res))
    print("보고서:", os.path.join(a.dest, "REPORT_KO.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
