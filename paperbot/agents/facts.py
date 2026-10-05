"""The run's facts for the agent staff, from ONE source (paper v4, owners 2026-10-05).

Every system prompt (``rooms.system_prompt`` fills ``{{RUN_FACTS}}`` / ``{{ORIGINALS}}`` / ``{{FIVE_M}}``), every
packet (``packets3`` meta), the lab's prior, the debate room and the shock text take their account counts,
timeframes and the 5m wording from here. Built from config (the run shape: V4_GROUPS and the totals computed from
it) and groups (the Korean names): no account count is typed anywhere in the agents' texts, so the next change of
the run shape cannot leave the staff repeating an old number ("156 accounts", "5m was removed").

Code only, no I/O. Not a trading file (the agents' code is outside every runinfo hash set).
"""

from __future__ import annotations

from functools import lru_cache

from ..config import (REEL_NAME, REEL_TF, V3_INITIAL, V3_STOP_ATR, Settings, V3_JUDGED_TFS, V3_TRADE_TFS, V4_ACCOUNTS, V4_GROUP_ACCOUNTS,
                      V4_GROUP_JUDGED, V4_GROUP_TF_COUNTS, V4_GROUPS, V4_JUDGED_ACCOUNTS, V4_TF_ACCOUNTS, V4_VERSION,
                      v4_exits, v4_tfs_of)
from ..groups import GROUP_KO, GROUP_LONG_KO, V4_ROLES

RULES_DOC = "docs/paper-v4-rules.md"
VERDICT_DOC = "docs/paper-v4-verdict.md"
LEVRULE_DOC = "docs/levrule-eval-v4.md"
# The exit rules in words (config.v4_exits decides which account has which; paperbot/policy.py and
# paperbot/reel_engine.py are the code). G5: the reel and the 5m coin flips never get the ladder's wording.
_S = Settings()
HOUSE_EXIT_KO = (f"하우스 청산: 손절 = 신호 봉 ATR14의 {V3_STOP_ATR:g}배, 익절 = 계단식 이익 잠금(+"
                 f"{(_S.ladder_first_lock + _S.ladder_trigger_gap) * 100:g}%에서 +{_S.ladder_first_lock * 100:g}% 잠금, 이후 "
                 f"{_S.ladder_step * 100:g}%마다), 시간 청산 없음")
REEL_EXIT_KO = ("자기 청산(사다리·잠금 없음): 손절 = 하단 이탈부터 신호 봉까지 최저가 − 0.05 × ATR14(5분봉), 익절 = 직전 "
                "5분봉 볼린저 윗선(5분마다 새 윗선으로 바뀜), 같은 봉에 둘 다면 손절 먼저, 96봉(8시간) 시간 청산")
FLIP5M_EXIT_KO = ("릴스와 같은 자기 청산(사다리·잠금 없음): 손절 = 직전 12개 5분봉 최저가 − 0.05 × ATR14, 익절 = 직전 "
                  "5분봉 볼린저 윗선, 96봉(8시간) 시간 청산")
EXTRA_EXIT_KO = "하우스 청산(복제 계좌는 바꾼 한 가지만 다름)"
TF_KO = {"5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}
# the board's own population (packets3 sections league, pass_check, by_strategy, by_coin, execution, exits, today):
# the 36 locked strategies and the 12 coin flips on the core timeframes, as in v3. Every other original account is
# counted per group in the board's ``groups`` section, never mixed into these numbers.
BOARD_SCOPE_KO = ("이 표(league·pass_check·by_strategy·by_coin·execution·exits·today)는 잠긴 매매법 36개와 같은 봉의 "
                  "동전 12개만 셈. 딥시크·릴스 5분 단타·5분봉 동전은 groups에 그룹별로 따로 있고 섞지 않음")


def _tfs_ko(tfs) -> str:
    return "·".join(TF_KO.get(tf, tf) for tf in tfs)


def _ds_split() -> list[tuple[int, tuple]]:
    """[(how many DeepSeek definitions, their timeframes)] in the order of their timeframe sets, e.g.
    [(39, 15m..4h), (5, 15m..1h)]."""
    out: dict[tuple, int] = {}
    for name in V4_GROUPS["ds200"]["names"]:
        tfs = tuple(v4_tfs_of("ds200", name))
        out[tfs] = out.get(tfs, 0) + 1
    return sorted(((n, tfs) for tfs, n in out.items()), key=lambda x: -len(x[1]))


def exits_ko() -> dict:
    """{group: one Korean exit line} from config.v4_exits per (kind, timeframe) of every group (owners' D2 (ii), D4):
    the house exits, the reel's own exits, and for the coin flips both (5m: the reel's; 15m..4h: the house's)."""
    out = {}
    for g, spec in V4_GROUPS.items():
        rules: dict[str, list] = {}
        for tf in spec["tfs"]:
            rules.setdefault(v4_exits(spec["kind"], tf), []).append(tf)
        parts = []
        for rule, tfs in rules.items():
            text = HOUSE_EXIT_KO if rule == "house" else (REEL_EXIT_KO if g == "reel" else FLIP5M_EXIT_KO)
            parts.append((f"{_tfs_ko(tfs)}봉은 " if len(rules) > 1 else "") + text)
        out[g] = f"{GROUP_KO[g]}: " + " / ".join(parts)
    out["extra"] = f"{GROUP_KO['extra']}: {EXTRA_EXIT_KO}"
    return out


def _checkpoint():
    try:
        from .. import checkpoint as CP
    except Exception:  # noqa: BLE001  (a text only: the built line below says the same from config)
        return None
    return CP


def method_ko() -> str:
    """The day-30 verdict method in one Korean line (G18): ``checkpoint.method_ko`` when the checkpoint has one, else
    built from the checkpoint's own numbers (N_BOTS, FAMILY_ALPHA, judged timeframes per family from config), so the
    staff never repeat an old bot count or one FDR for the whole run."""
    CP = _checkpoint()
    fn = getattr(CP, "method_ko", None)
    if callable(fn):
        try:
            t = fn()
        except TypeError:
            try:
                t = " · ".join(str(fn(g)) for g in getattr(CP, "FAMILY_ALPHA", {}))
            except Exception:  # noqa: BLE001
                t = None
        except Exception:  # noqa: BLE001
            t = None
        if isinstance(t, str) and t.strip():
            return t.strip()
    n = int(getattr(CP, "N_BOTS", 0) or 0)
    alpha = dict(getattr(CP, "FAMILY_ALPHA", {}) or {})
    parts = []
    for g, a in alpha.items():
        judged = V4_GROUPS.get(g, {}).get("judged") or ()
        parts.append(f"{GROUP_KO.get(g, g)} {a * 100:g}%({_tfs_ko(judged)})")
    head = f"계좌마다 같은 봉 동전 봇 {n:,}개와 비교(p값)" if n else "계좌마다 같은 봉 동전 봇과 비교(p값)"
    if parts:
        head += (f", 그룹마다 따로 벤저미니-호크버그 보정(잘못 고를 위험 한도 {' · '.join(parts)}, "
                 f"합 {sum(alpha.values()) * 100:g}%)")
    return head + f" ({VERDICT_DOC})"


@lru_cache(maxsize=1)
def facts() -> dict:
    """The run shape for packets: totals, groups (kind, names, timeframes, judged), the 5m accounts, the docs."""
    groups = {}
    for g, spec in V4_GROUPS.items():
        groups[g] = {"name_ko": GROUP_KO[g], "long_ko": GROUP_LONG_KO[g], "kind": spec["kind"],
                     "names": spec["n_names"], "timeframes": list(spec["tfs"]), "judged_timeframes": list(spec["judged"]),
                     "accounts": V4_GROUP_ACCOUNTS[g], "judged_accounts": V4_GROUP_JUDGED[g],
                     "by_timeframe": dict(V4_GROUP_TF_COUNTS[g])}
    return {"version": V4_VERSION, "rules": RULES_DOC, "verdict": VERDICT_DOC, "levrule": LEVRULE_DOC,
            "method_ko": method_ko(), "exits_ko": exits_ko(), "accounts": V4_ACCOUNTS,
            "judged_accounts": V4_JUDGED_ACCOUNTS, "initial_usdt": V3_INITIAL, "groups": groups,
            "by_timeframe": dict(V4_TF_ACCOUNTS), "core_timeframes": list(V3_TRADE_TFS),
            "core_judged_timeframes": list(V3_JUDGED_TFS),
            "five_minute": {"timeframe": REEL_TF, "accounts": V4_TF_ACCOUNTS.get(REEL_TF, 0),
                            "groups": [g for g, v in V4_GROUP_TF_COUNTS.items() if v.get(REEL_TF)]},
            "specialist_rooms": [{"key": k, "title_ko": ko, "families": list(f), "ids": list(i)}
                                 for k, ko, f, i in V4_ROLES]}


def five_m_ko() -> str:
    """The 5m sentence (replaces v3's "5분봉은 뺐음"): who trades 5m in this run, and that the 36's 5m rows of the
    5-year research are history."""
    f = facts()
    n5 = f["five_minute"]["accounts"]
    reel = V4_GROUP_TF_COUNTS["reel"].get(REEL_TF, 0)
    flips = V4_GROUP_TF_COUNTS["flip"].get(REEL_TF, 0)
    return (f"5분봉: 이번 실행의 5분봉 계좌는 {n5}개뿐(릴스 5분 단타 {REEL_NAME} {reel}개, 롱만 하는 5분봉 동전 {flips}개). "
            f"잠긴 매매법 {V4_GROUPS['core']['n_names']}개와 딥시크는 5분봉 계좌가 없음(36개의 5분봉은 2026-10-04 두 분 결정으로 "
            "실험에서 빠짐: 5년 자료 거래당 −2.3%, 36칸 중 34칸 유의한 손실). 5년 자료·연구의 36개 매매법 5분봉 줄은 과거 기록")


def originals_ko() -> str:
    """'원본 N개 계좌' as the prompts say it."""
    return f"원본 {V4_ACCOUNTS}개 계좌"


def run_facts_ko() -> list[str]:
    """The run's account facts as prompt bullet lines (Korean)."""
    f, g = facts(), facts()["groups"]
    core, ds, reel, flip = g["core"], g["ds200"], g["reel"], g["flip"]
    ds_parts = " + ".join(f"{n}개 × 봉 {len(tfs)}개({_tfs_ko(tfs)})" for n, tfs in _ds_split())
    return [
        f"이번 실행({f['version']}, `{f['rules']}`): 계좌 {f['accounts']}개, 계좌마다 ${f['initial_usdt']:,.0f}, 충전 없음. "
        f"30일 판정 대상은 {f['judged_accounts']}개이고 그룹마다 따로 셉니다.",
        f"{core['name_ko']}(잠긴 {core['names']}개) × 봉 {len(core['timeframes'])}개({_tfs_ko(core['timeframes'])}) = "
        f"{core['accounts']}개. 판정은 {_tfs_ko(core['judged_timeframes'])} {core['judged_accounts']}개, 4시간봉은 관찰용.",
        f"{ds['name_ko']}(딥시크 200 정의 {ds['names']}개): {ds_parts} = {ds['accounts']}개. 판정은 "
        f"{_tfs_ko(ds['judged_timeframes'])} {ds['judged_accounts']}개, 4시간봉은 관찰용. 5년 자료에서 342개 설정 중 통과 0개였던 "
        "정의들이라 손실·파산이 많아도 놀랄 일이 아님.",
        f"{reel['name_ko']}({REEL_NAME}, 인스타 릴스 볼린저 20·2 + 200선) {reel['accounts']}개: {_tfs_ko(reel['timeframes'])}봉만, "
        "롱만, 사전 등록한 자기 청산(손절 = 돌파 뒤 최저가 − 0.05 ATR, 익절 = 직전 5분봉 위 밴드, 96봉 시간 청산). 판정 대상.",
        f"{flip['name_ko']} {flip['accounts']}개: {_tfs_ko(flip['timeframes'])} × {flip['names']}개, 비교용(판정 대상 아님). "
        "5분봉 동전은 롱만, 릴스와 같은 청산, 진입 품질 best 없음.",
        five_m_ko() + ".",
        "복제·새 매매법 계좌(추가 계좌)는 원본과 따로 셉니다.",
    ]


def run_facts_block() -> str:
    return "\n".join(f"- {line}" for line in run_facts_ko())


def exits_block() -> str:
    """One exit line per group (prompt bullets, G5)."""
    return "\n".join(f"- 청산 · {line}" for line in facts()["exits_ko"].values())


def method_text() -> str:
    return facts()["method_ko"]


# rule B in one sentence (docs/paper-v4-rules.md; the rooms' long form is rooms_common.md's 레버리지·증거금 line): the
# debate prompt's {{RULE_B}}
RULE_B_KO = ("레버리지·증거금(규칙 B): 증거금 = 레버리지 %. 진입 품질 `best` 신호는 50%×50배 → 40%×40배 → 30%×30배 → "
             "20%×20배, 나머지 신호는 30%×30배 → 20%×20배를 차례로 시도해 거래소 구간·손절이 청산가보다 1 ATR 이상 안쪽·"
             "손절 손실 ≤ 자금 15%를 처음 통과한 후보로 들어감(모두 안 되면 진입 안 함). 딥시크와 릴스는 진입 품질 점수가 "
             f"없어 늘 보통. 낙폭 정지는 없고 자금 $10 미만이면 파산. 규칙 B는 30일 체크포인트에서 `{LEVRULE_DOC}` 방법으로 "
             "한 번만 판정하고, 창 중간에는 바꾸지 않음")


def rule_b_ko() -> str:
    return RULE_B_KO


PLACEHOLDERS = {"{{RUN_FACTS}}": run_facts_block, "{{ORIGINALS}}": originals_ko, "{{FIVE_M}}": five_m_ko,
                "{{EXITS}}": exits_block, "{{METHOD}}": method_text, "{{RULE_B}}": rule_b_ko}


def fill(text: str) -> str:
    """A prompt with the facts filled in (plain replacement: braces elsewhere in the prompt stay as they are)."""
    for k, fn in PLACEHOLDERS.items():
        if k in text:
            text = text.replace(k, fn())
    return text
