"""The only things an agent round can make happen. Code runs them; agent answers are data.

A room's final proposal is checked by ``validate`` and, if it passes, executed by one of
the functions below. Nothing else is callable: no orders, no exchange calls, no shell,
no file writes, no change to the original 195 accounts, the rules documents, the pass
criteria or any code. An unknown action name, or an allowed name with values outside
the fixed lists, becomes ``no_action`` (the room is told why).

    note           a line in the room's notes (notes table)
    hypothesis     an untested idea in the hypothesis ledger (trials, kind 'hypothesis')
    request_test   code runs one fixed 5-year test (labtests.TEMPLATES) for the room's
                   strategy, records trial + result, and applies the code gate
    propose_copy   a copy-account proposal for a trial whose test passed the gate;
                   status by code: blocked_gate / blocked_cap / rejected / awaiting_owner /
                   approved. The approver agent can never overturn the gate or the cap. Only when
                   paper3.db can be read and the parent account (strategy x timeframe) is not bust
                   and has closed at least 30 trades; the caps count active proposals and running
                   copy accounts together.
    flag_owners    a short Telegram message to the owners (INFO or WARN, 3 per KST day)
    no_action      nothing

The new-strategy lab (team:lab, rooms._lab_round) has no model action: code checks each spec the
researcher wrote (``newlab.normalize_spec``, a repeat by hash is shown, never re-run), runs it
(``newlab_test``), stores every counted test as an append-only 'newlab' trial, and for a pass writes a
proposal row of kind 'newlab' for the owners (``newlab_propose``: always 'awaiting_owner', the proposal and
the trial's 'proposed' result in one transaction, never while the new-strategy cap is full) and tells them
once by Telegram.

No account is created here. Every proposal row carries ``change.kind`` and ``change.account``, the
account's definition built by code from the trial row (agents/extra_accounts.py). The live runner (the only
writer of paper3.db) reads approved rows read-only, re-checks them itself and starts the extra paper account
at its next 5-minute boundary; an account that started is never stopped or changed from here.
All texts for the owners are Korean and written by code from stored numbers. A line posted
as role 'code' never quotes model text (the model's words stay in its own message), so a
model cannot write something that looks like a code result.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Optional

from ..notify import INFO, WARN, Notifier, NullNotifier
from . import extra_accounts as X
from . import rooms_db as R

try:  # the lab stream (5-year tests); the engine works without it (tests are then "no data")
    from . import labtests as _lab
except ImportError:  # pragma: no cover - only while the lab module is missing
    _lab = None
try:  # the new-strategy lab (newlab.py); without it the lab room cannot test
    from . import newlab as _nl
except ImportError:  # pragma: no cover
    _nl = None

ALLOWED_ACTIONS = ("note", "hypothesis", "request_test", "propose_copy", "flag_owners", "no_action")
# The five v4 specialist rooms (G7): note, flag_owners, no_action only (defined with the roles, roster3)
from .roster3 import GROUP_ACTIONS, GROUP_ACTIONS_KO  # noqa: E402,F401  (re-exported)
ACTION_KO = {"note": "메모 남기기", "hypothesis": "가설 기록", "request_test": "5년 시험 요청",
             "propose_copy": "복제 계좌 제안", "flag_owners": "두 분께 알림", "no_action": "행동 없음"}
FLAG_LEVELS = (INFO, WARN)
MAX_NOTE = 1_000
MAX_FLAG = 300
MAX_REASON = 500

# Documented in the lab interface; used only when paperbot.agents.labtests is not importable.
FALLBACK_TEMPLATES = {
    "stop_atr": {"k": [1.5, 2.5, 3.0]},
    "lock_start": {"first_lock": [0.15, 0.20, 0.30]},
    "skip_tag": {"tag": ["추세 반대 진입", "상위 봉 추세 반대", "횡보장 진입", "추세 약함 (ADX 20 미만)",
                         "DI 방향 반대", "많이 오른/내린 뒤 추격", "최근 범위 끝에서 진입"]},
    "timeframe_only": {},
}
FALLBACK_TFS = ("5m", "15m", "30m", "1h", "4h")
FALLBACK_DESCRIPTIVE = ("timeframe_only",)
TEMPLATE_KO = {"stop_atr": "손절 거리(ATR 배수) 바꾸기", "lock_start": "첫 익절 잠금 높이 바꾸기",
               "skip_tag": "특정 특징의 진입 건너뛰기", "timeframe_only": "봉별 성적 보기(설명용)"}


def lab_module():
    return _lab


def templates() -> dict:
    """{template: {param: [allowed values]}} -- what request_test may ask for (plus a
    ``timeframe``, required except for descriptive templates)."""
    t = getattr(_lab, "TEMPLATES", None) if _lab is not None else None
    if not isinstance(t, dict) or not t:
        t = FALLBACK_TEMPLATES
    out = {}
    for name, params in t.items():
        if isinstance(params, dict):
            out[name] = {k: list(v) if isinstance(v, (list, tuple, set, frozenset)) else [v]
                         for k, v in params.items() if not str(k).startswith("_")}
        else:
            out[name] = {}
    return out


def timeframes() -> tuple:
    return tuple(getattr(_lab, "TFS", FALLBACK_TFS))


def descriptive() -> tuple:
    return tuple(getattr(_lab, "DESCRIPTIVE", FALLBACK_DESCRIPTIVE))


def test_rules() -> dict:
    """What the packet tells the specialist about request_test (all fixed by code)."""
    help_ko = getattr(_lab, "TEMPLATE_HELP_KO", None) or TEMPLATE_KO
    return {"templates": templates(), "timeframes": list(timeframes()), "descriptive": list(descriptive()),
            "help": dict(help_ko),
            "format": {"template": "stop_atr", "timeframe": "1h", "k": 2.5},
            "note": "timeframe은 설명용(timeframe_only)이 아니면 꼭 필요. 전략은 코드가 이 방의 전략으로 정함"}


# ---------------------------------------------------------------- validation (pure)
def _text(v: Any, n: int) -> str:
    return R.clean_text(v.strip()[:n]) if isinstance(v, str) else ""


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        try:
            return math.isclose(float(a), float(b), rel_tol=0, abs_tol=1e-9)
        except OverflowError:                       # a huge int from a model answer
            return False
    return a == b


MAX_ID = 2 ** 63                                    # SQLite INTEGER


def _row_id(v: Any) -> Optional[int]:
    """A real positive row number from a model answer, or None (NaN, Infinity, 1e26, "1", true...)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, float):
        if not math.isfinite(v) or not v.is_integer():
            return None
        v = int(v)
    return v if isinstance(v, int) and 0 < v < MAX_ID else None


def _fallback_spec(test: dict, strategy: str) -> tuple[Optional[dict], str]:
    tmpl = templates()
    name = test.get("template")
    if not isinstance(name, str) or name not in tmpl:
        return None, f"없는 시험 종류 (가능한 것: {', '.join(tmpl)})"
    if test.get("strategy") not in (None, "", strategy):
        return None, "이 방의 전략만 시험할 수 있음"
    spec: dict = {"template": name, "strategy": strategy}
    tf = test.get("timeframe")
    if tf not in (None, "") or name not in descriptive():
        if tf not in timeframes():
            return None, f"timeframe은 {', '.join(timeframes())} 중 하나"
        spec["timeframe"] = tf
    for k, values in tmpl[name].items():
        hit = [v for v in values if k in test and _same(test[k], v)]
        if not hit:
            return None, f"{name}.{k}는 {values} 중 하나"
        spec[k] = hit[0]
    return spec, ""


def _test_spec(test: Any, strategy: Optional[str]) -> tuple[Optional[dict], str]:
    """A request_test's ``test``: exactly one template with allowed values, for this room's
    strategy (labtests.normalize_spec when available). Returns the normalised spec."""
    if not isinstance(test, dict):
        return None, "test가 객체가 아님"
    if not strategy:
        return None, "시험은 매매법 방에서만 요청할 수 있음"
    norm = getattr(_lab, "normalize_spec", None) if _lab is not None else None
    if norm is None:
        return _fallback_spec(test, strategy)
    try:
        return dict(norm(test, strategy)), ""
    except (ValueError, TypeError, OverflowError) as exc:
        return None, str(exc)[:200]


def validate(prop: Any, *, strategy: Optional[str] = None,
             allow: tuple = ALLOWED_ACTIONS) -> tuple[dict, list[str]]:
    """Clean a proposal object from a model answer. Anything not allowed becomes
    ``{"action": "no_action", "invalid": True, ...}``; problems explain why (Korean).
    ``strategy`` is the room's strategy (a test is always for that strategy)."""
    if prop is None:
        return {"action": "no_action", "reason": ""}, []
    if not isinstance(prop, dict):
        return {"action": "no_action", "invalid": True, "reason": "제안이 객체가 아님"}, ["제안이 JSON 객체가 아님"]
    a = prop.get("action")
    # 'reason' is fixed text by code (it is shown in code lines); what the model wrote stays in 'asked'
    if not isinstance(a, str) or a not in allow:
        shown = str(a)[:40]
        return ({"action": "no_action", "invalid": True, "asked": shown,
                 "reason": "허용 목록에 없는 행동"}, [f"허용되지 않은 행동: {shown!r}"])
    bad = lambda why: ({"action": "no_action", "invalid": True, "asked": a, "reason": why},  # noqa: E731
                       [f"{a}: {why}"])
    if a == "no_action":
        return {"action": "no_action", "reason": _text(prop.get("reason"), MAX_REASON)}, []
    if a == "note":
        t = _text(prop.get("text"), MAX_NOTE)
        return ({"action": "note", "text": t}, []) if t else bad("메모 내용이 비어 있음")
    if a == "hypothesis":
        t = _text(prop.get("text"), MAX_NOTE)
        if not t:
            return bad("가설 내용이 비어 있음")
        out = {"action": "hypothesis", "text": t, "how_to_confirm": _text(prop.get("how_to_confirm"), MAX_REASON)}
        from .scorecard import clean_prediction
        pred, why = clean_prediction(prop.get("prediction"))
        if pred is not None:
            out["prediction"] = pred
        return out, ([f"hypothesis: 예측은 채점할 수 없어 뺐음 ({why})"] if why else [])
    if a == "request_test":
        spec, why = _test_spec(prop.get("test"), strategy)
        if spec is None:
            got = bad("허용된 시험 형식이 아님 (시험 종류·시간봉·값은 목록에서만)")
            got[0]["detail"] = why
            return got[0], [f"{a}: {why}"]
        return {"action": "request_test", "test": spec,
                "propose_copy_if_pass": prop.get("propose_copy_if_pass") is True,
                "why": _text(prop.get("why"), MAX_REASON)}, []
    if a == "propose_copy":
        tid = _row_id(prop.get("trial_id"))
        if tid is None:
            return bad("trial_id가 올바른 번호가 아님")
        return {"action": "propose_copy", "trial_id": tid, "why": _text(prop.get("why"), MAX_REASON)}, []
    if a == "flag_owners":
        lvl = prop.get("level", INFO)
        if lvl not in FLAG_LEVELS:
            got = bad("알림 수준은 INFO 또는 WARN만 가능")
            got[0]["detail"] = str(lvl)[:20]
            return got[0], got[1]
        t = " ".join(_text(prop.get("text"), MAX_FLAG).split())     # one line: it follows code's own prefix
        return ({"action": "flag_owners", "level": lvl, "text": t}, []) if t else bad("알림 내용이 비어 있음")
    return bad("처리할 수 없음")  # pragma: no cover


# ---------------------------------------------------------------- execution
@dataclass
class ActionEnv:
    conn: sqlite3.Connection            # agents3.db, the tick's writer connection
    room_id: str
    strategy: Optional[str]
    round_id: Optional[int]
    meeting: str
    now_ms: int
    room_title: str = ""
    notifier: Notifier = field(default_factory=NullNotifier)
    lab: Any = None                     # labtests.LabData or None
    owner_ok_required: bool = True
    observing: str = ""                 # the observation period's last day while it lasts: no copy proposals
    copy_cap_per_strategy: int = 1
    copy_cap_total: int = 10
    flag_max_per_day: int = 3
    proposer: str = ""                  # role id whose proposal is being carried out (named, never quoted)
    evidence_key: str = ""              # the meeting's trigger key: a retried meeting never re-sends its flag
    # paper3.db, read-only (None: missing or unreadable): the copy's parent account, running extra accounts
    # (the caps count them) and whether the runner's extra-account feature is deployed. Nothing is proposed
    # without it.
    paper_ro: Optional[sqlite3.Connection] = None
    newlab_cap_total: int = X.NEWLAB_CAP_TOTAL

    def post(self, kind: str, text: str, data: Any = None, role: str = "code") -> int:
        return R.post(self.conn, self.room_id, self.round_id, self.meeting, role, None, kind, text, data,
                      ts=self.now_ms)

    def by(self) -> str:
        return f" (제안: {R.role_name(self.proposer)})" if self.proposer else ""


def _done(action: str, ok: bool, text: str, **extra) -> dict:
    return {"action": action, "ok": ok, "text": text, **extra}


def note(env: ActionEnv, a: dict) -> dict:
    nid = R.add_note(env.conn, env.room_id, env.strategy, a["text"], env.round_id, ts=env.now_ms)
    env.post("action", f"📝 메모 #{nid}을 방 메모에 남겼습니다{env.by()}.",
             {"action": "note", "note_id": nid, "text": a["text"], "proposer": env.proposer})
    return _done("note", True, "메모를 남김", note_id=nid)


def hypothesis(env: ActionEnv, a: dict) -> dict:
    spec = {"text": a["text"], "how_to_confirm": a.get("how_to_confirm", "")}
    if a.get("prediction"):
        spec.update(prediction=a["prediction"], by=env.proposer)     # graded later by code (scorecard.py)
    old = R.find_trial(env.conn, env.strategy, spec, kind="hypothesis")
    if old is not None:
        env.post("action", f"같은 가설이 이미 장부에 있습니다 (#{old['id']}). 새로 적지 않았습니다.",
                 {"action": "hypothesis", "trial_id": old["id"], "duplicate": True})
        return _done("hypothesis", True, "이미 있는 가설", trial_id=old["id"], duplicate=True)
    tid = R.add_trial(env.conn, env.room_id, env.strategy, "hypothesis", spec, env.round_id, ts=env.now_ms)
    from .scorecard import describe_ko
    graded = (f" 채점할 예측: {describe_ko(a['prediction'])}." if a.get("prediction")
              else " 예측이 없어 채점하지 않습니다.")
    env.post("action", f"🧪 가설 #{tid}을 가설 장부에 적었습니다 (아직 시험 전){env.by()}.{graded}",
             {"action": "hypothesis", "trial_id": tid, "text": a["text"], "proposer": env.proposer})
    return _done("hypothesis", True, "가설을 장부에 기록", trial_id=tid)


# links and @mentions in model-written words (Telegram makes them clickable): never sent as such. Any
# scheme (https://, tg://), www., any name.tld (every top-level domain, not a fixed list, internationalised
# ones such as .рф or .한국 included), IPv4 addresses (with a port or a path), @names.
_LINK = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://\S+|\bwww\.\S+"
                   r"|(?<![\w.])[\w-]+(?:\.[\w-]+)*\.[^\W\d_]{2,24}\b(?::\d+)?(?:/\S*)?"
                   r"|(?<![\w.])\d{1,3}(?:\.\d{1,3}){3}\b(?::\d+)?(?:/\S*)?"
                   r"|(?<![\w.])@\w{3,}")


def telegram_safe(text: str) -> str:
    """Model-written words bound for Telegram: links and @mentions replaced by '(링크 생략)'.
    Full-width and other look-alike forms are normalised first (NFKC), so 'ｅｖｉｌ．ｃｏｍ' is a link too;
    NFKC keeps the ideographic full stop (and maps the half-width one to it), so 'evil。com' becomes
    'evil.com' before the check. Invisible format characters (Unicode category Cf: bidi overrides and
    isolates such as U+202E, zero-width spaces and joiners) are removed first: they could reorder the line
    as shown in Telegram or hide a link from the check ('evil\u200b.com')."""
    t = unicodedata.normalize("NFKC", text or "").replace("\u3002", ".")
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Cf")
    return _LINK.sub("(링크 생략)", t)


def flag_owners(env: ActionEnv, a: dict) -> dict:
    key = f"flag_owners:{R.kst_day(env.now_ms)}"
    # a meeting run again for the same evidence (the pass was killed after the flag, or the meeting failed
    # or stopped later) sends no second Telegram
    sent_key = f"flag_sent:{env.room_id}:{env.evidence_key}" if env.evidence_key else ""
    if sent_key and R.get_cursor(env.conn, sent_key) is not None:
        env.post("system", "이 회의 계기로 이미 두 분께 알림을 보냈습니다(다시 연 회의). 다시 보내지 않았습니다.",
                 {"action": "flag_owners", "sent": False, "reason": "already_sent"})
        return _done("flag_owners", False, "이미 보낸 알림", sent=False, duplicate=True)
    used = int(R.get_cursor(env.conn, key, 0) or 0)
    if used >= env.flag_max_per_day:
        env.post("system", f"오늘 두 분께 보낼 수 있는 알림 {env.flag_max_per_day}번을 다 써서 보내지 않았습니다.",
                 {"action": "flag_owners", "sent": False, "reason": "daily_limit"})
        return _done("flag_owners", False, "하루 알림 한도", sent=False)
    title = env.room_title or env.room_id
    text = f"에이전트 알림 · {title}\n\n{telegram_safe(a['text'])}"
    if sent_key:                        # before the send, like the day's count: a kill after it still counts
        R.set_cursor(env.conn, sent_key, env.now_ms, commit=False)
    R.set_cursor(env.conn, key, used + 1)
    try:
        ok = env.notifier.send(a["level"], text)
    except Exception as exc:  # delivery must not break the round
        ok, why = False, type(exc).__name__
    else:
        why = "텔레그램이 받지 않음"
    if ok is False:           # never claim a message was sent when it was not
        env.post("system", f"알림 전송 실패: {why}", {"action": "flag_owners", "sent": False})
        return _done("flag_owners", False, "전송 실패", sent=False)
    env.post("action", f"📣 두 분께 텔레그램 알림({a['level']})을 보냈습니다{env.by()}. 오늘 {used + 1}번째.",
             {"action": "flag_owners", "sent": True, "level": a["level"], "n_today": used + 1, "text": a["text"],
              "proposer": env.proposer})
    return _done("flag_owners", True, "알림 보냄", sent=True, level=a["level"])


def no_action(env: ActionEnv, a: dict) -> dict:
    return _done("no_action", True, "행동 없음", reason=a.get("reason", ""))


# ---------------------------------------------------------------- 5-year tests
def _num(x: Any, fmt: str) -> str:
    try:
        return format(float(x), fmt)
    except (TypeError, ValueError):
        return "-"


def _periods(result: Any) -> list[tuple[str, dict]]:
    per = result.get("periods") if isinstance(result, dict) else None
    if isinstance(per, dict):
        return [(str(k), v) for k, v in per.items() if isinstance(v, dict)]
    return []


def _same_gate(a: Any, b: Any) -> bool:
    if not (isinstance(a, dict) and isinstance(b, dict)):
        return False
    return (a.get("pass") is True) == (b.get("pass") is True) and a.get("n_trials") == b.get("n_trials")


def render_result_ko(spec: dict, result: Any, gate: Optional[dict], n_trials: Optional[int],
                     rejudged: bool = False) -> str:
    """Code-written Korean summary of a test result (numbers only from the result). Uses the
    lab's own ``summary_ko`` when it has one; when ``gate`` (the verdict code gives now) differs from
    the one stored in the result, the summary is written again with ``gate`` (never the old verdict).
    ``rejudged``: the gate was judged again with the room's current number of tests."""
    if isinstance(result, dict) and isinstance(result.get("summary_ko"), str) and result.get("summary_ko"):
        text = result["summary_ko"]
        if gate is not None and not _same_gate(result.get("gate"), gate):
            redo = None
            fn = getattr(_lab, "summary_ko", None) if _lab is not None else None
            if fn is not None:
                try:
                    redo = fn({**result, "gate": gate})
                except Exception:  # a stored result the lab cannot render: the plain table below
                    redo = None
            if isinstance(redo, str) and redo:
                return redo
            result = {k: v for k, v in result.items() if k != "summary_ko"}
        else:
            return text
    name = spec.get("template")
    vals = ", ".join(f"{k}={v}" for k, v in spec.items() if k not in ("template", "strategy"))
    lines = [f"[5년 시험] {TEMPLATE_KO.get(name, name)}" + (f" ({vals})" if vals else "")]
    for pid, p in _periods(result):
        b = p.get("baseline") if isinstance(p.get("baseline"), dict) else {}
        v = p.get("variant") if isinstance(p.get("variant"), dict) else {}
        if not p.get("available", True) or not b:
            lines.append(f"- {pid}기간: 자료 없음")
            continue
        lines.append(f"- {pid}기간: 거래 {b.get('trades', '-')}→{v.get('trades', '-')}건, 거래당 평균 ROE "
                     f"{_num(b.get('mean_roe'), '+.2%')} → {_num(v.get('mean_roe'), '+.2%')} "
                     f"(차이 {_num(p.get('diff'), '+.2%')}, p={_num(p.get('p'), '.4f')})")
    if gate is not None:
        where = ((f" (지금 이 방 시험 {n_trials}번 기준)" if rejudged else f" (이 방 시험 {n_trials}번째)")
                 if n_trials else "")
        lines.append("판정: " + ("통과" if gate.get("pass") is True else "통과 못함") + where)
        lines += [f"  {str(r)[:200]}" for r in (gate.get("reasons") or [])[:6]]
    return "\n".join(lines)


def _stored(trial: Optional[dict]) -> tuple[Optional[str], dict]:
    res = (trial or {}).get("result") or {}
    body = res.get("result") if isinstance(res.get("result"), dict) else {}
    return res.get("status"), body


FINAL_TEST_STATUSES = ("passed", "failed", "described")   # a trial with one of these is never re-run


def lab_strategies() -> tuple:
    """The names the 5-year lab can test: the 36 locked strategies (strategy_view_defs.NAMES), never a DeepSeek
    definition, the reel or a coin flip (its data and its gate are the 36's; G7)."""
    from ..strategy_view_defs import NAMES
    return tuple(NAMES)


def request_test(env: ActionEnv, a: dict) -> dict:
    """Run (or reuse) one fixed test for the room's strategy. Returns trial_id, status
    (passed / failed / described / no_data / error), result, gate, n_trials and whether an
    earlier identical test was reused. The gate is labtests.gate with this room's test count
    (Bonferroni); nobody can change it afterwards. A room whose strategy is not one of the 36
    (``lab_strategies``) is refused before anything is recorded: no trial, no test number (G7)."""
    if env.strategy not in lab_strategies():
        return _done("request_test", False, "5년 시험은 잠긴 매매법 36개만 할 수 있습니다(이 방의 매매법은 시험 대상 아님)",
                     refused=True, strategy=env.strategy)
    spec = dict(a["test"])
    spec["strategy"] = env.strategy          # always the room's strategy, never the model's
    old = R.find_trial(env.conn, env.strategy, spec, kind="test")
    st, body = _stored(old)
    if old is not None and st in FINAL_TEST_STATUSES:
        # a stored pass is judged again with the room's CURRENT number of tests (Bonferroni), exactly
        # like the copy step does, so the room, the validator and the summary see one verdict
        if st == "passed":
            gate, n_now = current_gate(env, old)
            st_now = "passed" if gate.get("pass") is True else "failed"
        else:
            gate, n_now, st_now = body.get("gate"), body.get("n_trials"), st
        again = st == "passed"
        text = (f"같은 시험을 이미 했습니다 (시험 #{old['id']}). 다시 돌리지 않고 저장된 결과를 씁니다"
                + (" (판정은 이 방의 지금 시험 수로 다시 계산)" if again else "") + ".\n"
                + render_result_ko(spec, body.get("result"), gate, n_now, rejudged=again))
        env.post("code_result", text, {"trial_id": old["id"], "spec": spec, "reused": True, **body, "gate": gate,
                                       "n_trials": n_now, "status": st_now, "stored_status": st,
                                       "n_trials_at_test": body.get("n_trials"), "rejudged": again})
        return _done("request_test", True, "이전 시험 결과 재사용", trial_id=old["id"], status=st_now, reused=True,
                     spec=spec, result=body.get("result"), gate=gate, n_trials=n_now, rejudged=again,
                     n_trials_at_test=body.get("n_trials"))
    # a trial that could not run (no data / error) keeps its number: asking again runs it then
    tid = old["id"] if old is not None else R.add_trial(env.conn, env.room_id, env.strategy, "test", spec,
                                                         env.round_id, ts=env.now_ms)
    n_trials = R.trial_count(env.conn, room_id=env.room_id, kinds=("test",))
    lab = _lab
    no_gate = {"pass": False, "reasons": ["시험 결과가 없어 통과할 수 없습니다."]}
    if lab is None or not hasattr(lab, "run_test") or env.lab is None:
        body = {"result": None, "gate": no_gate, "n_trials": n_trials}
        R.add_trial_result(env.conn, tid, "no_data", body, ts=env.now_ms)
        env.post("code_result", f"🔬 시험 #{tid}을 장부에 적었지만, 이 서버에 5년 시험 데이터가 없어 돌리지 못했습니다. "
                 "데이터가 준비된 뒤 같은 시험을 다시 요청하면 그때 돌립니다.",
                 {"trial_id": tid, "spec": spec, "status": "no_data", **body})
        return _done("request_test", False, "시험 데이터 없음", trial_id=tid, status="no_data", spec=spec,
                     result=None, gate=no_gate, n_trials=n_trials)
    try:
        result = lab.run_test(spec, env.lab, n_trials=n_trials, strategy=env.strategy)
        # the lab's own gate is never trusted: code re-runs it (a failed run has no gate at all)
        gate = lab.gate(result, n_trials) if isinstance(result, dict) and result.get("ok") else no_gate
    except Exception as exc:  # recorded; asking for the same test later re-runs it under the same number
        result = {"ok": False, "status": "error", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        gate = no_gate
    gate = {**gate, "pass": gate.get("pass") is True, "reasons": [str(r) for r in (gate.get("reasons") or [])]}
    if not result.get("ok"):
        status = "no_data" if result.get("status") == "no_data" else "error"
        body = {"result": result, "gate": gate, "n_trials": n_trials}
        R.add_trial_result(env.conn, tid, status, body, ts=env.now_ms)
        why = result.get("error") or result.get("summary_ko") or status
        env.post("code_result", f"🔬 시험 #{tid}을 돌리지 못했습니다: {str(why)[:300]}",
                 {"trial_id": tid, "spec": spec, "status": status, **body})
        return _done("request_test", False, f"시험 못 함: {str(why)[:120]}", trial_id=tid, status=status, spec=spec,
                     result=result, gate=gate, n_trials=n_trials)
    status = "described" if spec.get("template") in descriptive() else ("passed" if gate["pass"] else "failed")
    body = {"result": result, "gate": gate, "n_trials": n_trials}
    R.add_trial_result(env.conn, tid, status, body, ts=env.now_ms)
    env.post("code_result", f"🔬 시험 #{tid} (코드 계산)\n" + render_result_ko(spec, result, gate, n_trials),
             {"trial_id": tid, "spec": spec, "status": status, **body})
    return _done("request_test", True, "시험 실행", trial_id=tid, status=status, spec=spec, result=result, gate=gate,
                 n_trials=n_trials)


# ---------------------------------------------------------------- copy proposals
def current_gate(env: ActionEnv, t: dict) -> tuple[dict, int]:
    """The code gate of a stored test, re-computed now with the room's CURRENT number of tests
    (Bonferroni over every test the room has run, also those after this one). Fails closed: a
    trial that did not end 'passed', or whose stored result cannot be re-judged, does not pass.
    Returns (gate, n_trials used)."""
    st, body = _stored(t)
    n_now = max(R.trial_count(env.conn, room_id=env.room_id, kinds=("test",)), _row_id(body.get("n_trials")) or 1)
    result = body.get("result")
    judge = getattr(_lab, "gate", None) if _lab is not None else None
    if st != "passed":
        stored = body.get("gate") if isinstance(body.get("gate"), dict) else {}
        return {**stored, "pass": False, "reasons": [str(r) for r in stored.get("reasons") or []]
                or [f"시험 상태가 '{st}'라 통과가 아님"]}, n_now
    if judge is None or not isinstance(result, dict) or result.get("ok") is not True:
        return {"pass": False, "n_trials": n_now,
                "reasons": ["저장된 시험 결과를 지금 기준으로 다시 판정할 수 없어 통과로 보지 않습니다."]}, n_now
    try:
        g = judge(result, n_now)
    except Exception as exc:  # a broken stored result never passes
        return {"pass": False, "n_trials": n_now, "reasons": [f"다시 판정하지 못함: {type(exc).__name__}"]}, n_now
    g = dict(g) if isinstance(g, dict) else {}
    return {**g, "pass": g.get("pass") is True, "reasons": [str(r) for r in g.get("reasons") or []],
            "n_trials": n_now}, n_now


PAPER_UNREADABLE_KO = "paper3를 읽지 못해 제안하지 않음"


def copy_check(env: ActionEnv, trial_id: int) -> dict:
    """What code knows before any approver speaks: does the trial exist for this room's
    strategy, does its test pass the gate NOW (re-judged with the room's current test count),
    was it proposed before, can paper3.db be read (no proposal without it), is the parent account
    (the test's strategy x timeframe) not bust and with at least 30 closed trades, is a copy slot
    free (active proposals and running copy accounts together, extra_accounts.slots)."""
    t = R.get_trial(env.conn, trial_id)
    if t is None or t.get("kind") != "test" or t.get("strategy") != env.strategy:
        return {"ok": False, "why": "이 방의 시험 번호가 아님", "trial": None, "gate": None}
    st, body = _stored(t)
    gate, n_now = current_gate(env, t)
    prev = [p for p in R.list_proposals(env.conn, strategy=env.strategy, limit=1000) if p.get("trial_id") == trial_id]
    live = [p for p in prev if p["status"] != "blocked_cap"]
    if live:
        return {"ok": False, "why": f"이미 제안된 시험 (제안 #{live[0]['id']}, {live[0]['status']})", "trial": t,
                "gate": gate, "duplicate": True}
    no = lambda why: {"ok": False, "why": why, "trial": t, "gate": gate}  # noqa: E731
    extras = X.paper_extras(env.paper_ro)
    if extras is None:
        return no(PAPER_UNREADABLE_KO)
    acc = X.copy_account(t)
    if acc is not None:
        f = X.parent_facts(env.paper_ro, acc["parent"])
        if f is None:
            return no(PAPER_UNREADABLE_KO)
        if not f["exists"] or f["kind"] != "strategy":
            return no("원본 계좌가 paper3에 없어 복제하지 않음")
        if f["bust"]:
            return no("원본 계좌가 파산해 복제하지 않음")
        if f["trades"] < X.PARENT_MIN_TRADES:
            return no(f"원본 계좌 거래 {f['trades']}건 < {X.PARENT_MIN_TRADES}건")
    used_s = X.slots(env.conn, env.paper_ro, "copy", env.strategy, extras)
    used = X.slots(env.conn, env.paper_ro, "copy", None, extras)
    cap = ""
    if used_s >= env.copy_cap_per_strategy:
        cap = f"이 매매법은 이미 진행 중인 제안·복제 계좌가 {env.copy_cap_per_strategy}개 있음"
    elif used >= env.copy_cap_total:
        cap = f"전체 진행 중인 제안·복제 계좌가 한도 {env.copy_cap_total}개에 도달"
    return {"ok": True, "trial": t, "gate": gate, "gate_pass": st == "passed" and gate.get("pass") is True,
            "result_status": st, "cap": cap, "n_trials": n_now, "n_trials_at_test": body.get("n_trials"),
            "slots": {"strategy": used_s, "total": used}}


def propose_copy(env: ActionEnv, trial_id: int, why: str, check: dict, approver: Optional[dict]) -> dict:
    """Record the proposal. Status is decided by code in this order: gate failed ->
    blocked_gate; copy cap full -> blocked_cap; approver said no -> rejected; approver said
    yes -> awaiting_owner (owners' OK required) or approved. ``approver`` is the checked
    answer {approve: bool, reason} or None when it was not asked (gate/cap already block).
    During the owners' observation period nothing is recorded (the test stays in the ledger)."""
    if env.observing:
        why_not = f"관찰 기간({env.observing}까지)이라 복제 제안을 만들지 않습니다. 시험 결과는 장부에 남고, 기간이 끝나면 제안할 수 있습니다"
        env.post("system", why_not + ".", {"action": "propose_copy", "trial_id": trial_id, "created": False,
                                           "observing": env.observing})
        return _done("propose_copy", False, why_not, created=False)
    if not check.get("ok"):
        env.post("system", f"복제 제안을 만들지 않았습니다: {check.get('why')}",
                 {"action": "propose_copy", "trial_id": trial_id, "created": False})
        return _done("propose_copy", False, check.get("why", ""), created=False)
    t, gate = check["trial"], dict(check["gate"])
    gate.update({"trial_id": trial_id, "n_trials": check.get("n_trials")})
    if not check.get("gate_pass"):
        status, by = "blocked_gate", "code"
    elif check.get("cap"):
        status, by = "blocked_cap", "code"
    elif approver is None:
        env.post("system", "승인관 답이 없어 이번에는 제안을 기록하지 않았습니다.",
                 {"action": "propose_copy", "trial_id": trial_id, "created": False})
        return _done("propose_copy", False, "승인관 답 없음", created=False)
    elif approver.get("approve") is not True:
        status, by = "rejected", "approver"
    else:
        status, by = ("awaiting_owner", None) if env.owner_ok_required else ("approved", "approver")
    # kind and account: code-written from the trial row (the runner reads only these, never 'why' or 'approver')
    change = {"kind": "copy", "account": X.copy_account(t), "strategy": env.strategy, "test": t.get("spec"),
              "why": why,
              "approver": None if approver is None else {"approve": approver.get("approve") is True,
                                                         "reason": str(approver.get("reason", ""))[:MAX_REASON]}}
    R.add_trial(env.conn, env.room_id, env.strategy, "copy_proposal", {"from_trial": trial_id, "test": t.get("spec")},
                env.round_id, ts=env.now_ms)
    pid = R.add_proposal(env.conn, env.room_id, env.strategy, trial_id, change, gate, status, by, ts=env.now_ms)
    msg = {"blocked_gate": "코드 관문을 통과하지 못해 막혔습니다 (누구도 뒤집을 수 없음)",
           "blocked_cap": f"복제 계좌 한도 때문에 막혔습니다 ({check.get('cap')})",
           "rejected": "승인관이 거부했습니다",
           "awaiting_owner": "승인관이 승인했고, 두 분의 확인을 기다립니다 (대시보드에서 승인/거절)",
           "approved": "자율 승인관이 승인했습니다(두 분 확인 없이: 설정, 또는 기본 설정에서 운영 61일째부터)"}[status]
    waits = (" " + start_text(env.paper_ro) if status in ("awaiting_owner", "approved") else "")
    env.post("action", f"📄 복제 계좌 제안 #{pid} (시험 #{trial_id}): {msg}.{waits}",
             {"action": "propose_copy", "proposal_id": pid, "trial_id": trial_id, "status": status})
    return _done("propose_copy", status in ("awaiting_owner", "approved"), msg, created=True, proposal_id=pid,
                 status=status, trial_id=trial_id)


def runtime_ready(paper_ro: Optional[sqlite3.Connection]) -> bool:
    """Is the live runner's extra-account feature deployed (its state 'extras' in paper3.db)?"""
    return X.runner_state(paper_ro) is not None


def start_text(paper_ro: Optional[sqlite3.Connection]) -> str:
    """What an approval does now (Korean, code-written)."""
    if runtime_ready(paper_ro):
        from ..config import V3_ACCOUNTS
        return ("승인이 반영되면 live 실행기가 코드로 다시 확인한 뒤 다음 봉 경계에 새 paper 계좌로 시작합니다"
                f"(원본 계좌와 같은 시작 자금, 원본 {V3_ACCOUNTS}개 계좌는 그대로). 시작된 계좌는 거절로 멈출 수 없습니다.")
    return ("live 실행기의 추가 계좌 기능이 아직 켜지지 않아 지금은 계좌를 만들지 않습니다. 기능이 켜진 뒤 두 분이 한 번 더 "
            "승인하면 그때 시작합니다.")


SIMPLE = {"note": note, "hypothesis": hypothesis, "flag_owners": flag_owners, "no_action": no_action}


def run_simple(env: ActionEnv, a: dict) -> dict:
    """note / hypothesis / flag_owners / no_action (request_test and propose_copy need the
    room's validator/approver turns, see rooms.py)."""
    fn = SIMPLE.get(a.get("action"))
    if fn is None:
        return no_action(env, {"reason": "처리할 수 없는 행동"})
    return fn(env, a)


def summary_numbers(res: dict) -> dict:
    """Numbers for the round summary, from code results only."""
    return json.loads(json.dumps({k: res.get(k) for k in ("trial_id", "status", "proposal_id", "n_trials")
                                  if res.get(k) is not None}, default=str))


# ---------------------------------------------------------------- the new-strategy lab (team:lab)
NEWLAB = "newlab"                       # trial kind (rooms_db.TRIAL_KINDS)


def newlab_module():
    return _nl


def newlab_count(conn: Optional[sqlite3.Connection]) -> int:
    """Counted new-strategy tests in ALL rooms: the ``n`` of the lab's gate (docs/newlab-prereg.md 5)."""
    return R.trial_count(conn, kinds=(NEWLAB,))


def newlab_exhausted(conn: Optional[sqlite3.Connection]) -> bool:
    """No further test can pass gate (a) any more (``newlab.gate``'s can_pass_at_this_n is n <= max_passable_n):
    the lab stops testing."""
    return _nl is None or newlab_count(conn) > _nl.max_passable_n()


def newlab_hashes(conn: sqlite3.Connection) -> dict:
    """{spec hash: latest trial id} of every counted test (the stored spec is newlab's canonical form, so the
    ledger's spec_hash is newlab.spec_hash)."""
    return {h: int(i) for h, i in conn.execute("SELECT spec_hash, MAX(id) FROM trials WHERE kind = ? "
                                               "GROUP BY spec_hash", (NEWLAB,)).fetchall()}


_GATE_KEYS = ("start", "end", "cache", "available", "why", "trades", "mean_roe", "win_rate", "mean_pnl_equity", "p",
              "coins_pos", "coins_n", "signals", "long_trades")


def _gate_input(result: dict) -> dict:
    """The periods as ``newlab.gate`` reads them (no per-coin arrays): enough to judge the stored test
    again with a later count."""
    out = {}
    for pid, row in (result.get("periods") or {}).items():
        if not isinstance(row, dict):
            continue
        r = {k: row[k] for k in _GATE_KEYS if k in row}
        cf = row.get("coinflip") if isinstance(row.get("coinflip"), dict) else None
        if cf is not None:
            r["coinflip"] = {k: cf.get(k) for k in ("mean_roe", "trades", "diff", "p")}
        out[str(pid)] = r
    return out


def _newlab_body(result: dict, idea: str = "") -> dict:
    return {"ledger": _nl.ledger_row(result), "gate": result.get("gate"), "gate_input": _gate_input(result),
            "description_ko": result.get("description_ko"), "summary_ko": result.get("summary_ko"),
            "notes": result.get("notes") or ({"idea": idea} if idea else {}),
            "test_number": result.get("test_number"), "n_tests_so_far": result.get("n_tests_so_far"),
            "runtime_s": result.get("runtime_s"), "proposal": None}


def newlab_stored(trial: Optional[dict]) -> tuple[Optional[str], dict]:
    """(latest status, body) of a stored 'newlab' trial."""
    return _stored(trial)


def newlab_gate_now(conn: sqlite3.Connection, trial: dict) -> tuple[dict, int]:
    """The gate of a stored test judged with the count NOW: n = every other counted test (at least the n it
    was run with). Fails closed."""
    st, body = _stored(trial)
    n_then = _row_id(body.get("n_tests_so_far")) or 0
    n_now = max(n_then, newlab_count(conn) - 1)
    gi = body.get("gate_input")
    if _nl is None or not isinstance(gi, dict) or not gi:
        return {"pass": False, "reasons": ["저장된 결과를 다시 판정할 수 없어 통과로 보지 않습니다."]}, n_now
    try:
        g = _nl.gate({"ok": True, "status": "done", "periods": gi}, n_now)
    except Exception as exc:  # a broken stored result never passes
        return {"pass": False, "reasons": [f"다시 판정하지 못함: {type(exc).__name__}"]}, n_now
    return {**g, "pass": g.get("pass") is True}, n_now


def newlab_test(env: ActionEnv, spec: dict, *, idea: str = "") -> dict:
    """Run one canonical spec (already checked and not in the ledger) on the lab cache, with n = the global
    count. A counted test is stored as a 'newlab' trial with its result in one transaction and posted as a
    code result; a run that did not count (no data, a repeat, an error) is posted and stored nowhere.
    Never raises. Returns {status: passed|failed|not_counted|error, trial_id?, result?, ...}."""
    if _nl is None:
        env.post("system", "새 매매법 시험 엔진(newlab.py)이 없어 시험하지 못했습니다.", {"newlab": True, "status": "error"})
        return {"status": "error", "counted": False}
    n = newlab_count(env.conn)
    run = {**spec, **({"idea": idea[:500]} if idea else {})}
    try:
        result = _nl.run_new_strategy(run, env.lab, n, tested_hashes=newlab_hashes(env.conn))
    except Exception as exc:  # a bug or a bad cache: told, not counted, the tick goes on
        why = f"{type(exc).__name__}: {str(exc)[:200]}"
        env.post("system", f"🔬 새 매매법 시험 중 오류가 나서 멈췄습니다({why}). 결과를 보지 못했으므로 시험 수에 넣지 "
                           "않습니다.", {"newlab": True, "status": "error", "spec": spec, "error": why})
        return {"status": "error", "counted": False, "error": why, "spec": spec}
    if not _nl.counts_as_test(result):
        env.post("system", f"🔬 {result.get('summary_ko') or '시험하지 못했습니다'} (시험 수에 넣지 않음)",
                 {"newlab": True, "status": result.get("status"), "spec": spec, "error": result.get("error")})
        return {"status": "not_counted", "counted": False, "why": result.get("status"), "spec": spec,
                "error": result.get("error")}
    gate = result.get("gate") or {}
    status = "passed" if gate.get("pass") is True else "failed"
    body = _newlab_body(result, idea)
    try:
        tid = R.add_trial_with_result(env.conn, env.room_id, None, NEWLAB, result["spec"], status, body,
                                      env.round_id, ts=env.now_ms)
    except sqlite3.Error as exc:     # e.g. an agents3.db made before the 'newlab' kind: told, not counted
        env.post("system", f"🔬 새 매매법 시험 결과를 장부에 적지 못했습니다({type(exc).__name__}). 이 서버의 agents3.db가 "
                           "새 매매법 장부보다 오래된 것일 수 있습니다(docs/agent-rooms.md).",
                 {"newlab": True, "status": "error", "spec": spec})
        return {"status": "error", "counted": False, "spec": spec}
    env.post("code_result", f"🔬 새 매매법 시험 결과 (장부 #{tid}, 코드 계산)\n{result.get('summary_ko', '')}",
             {"newlab": True, "trial_id": tid, "status": status, "spec": result["spec"], "spec_hash": result.get("spec_hash"),
              "gate": gate, "ledger": body["ledger"], "test_number": result.get("test_number")})
    return {"status": status, "counted": True, "trial_id": tid, "spec": result["spec"], "gate": gate,
            "test_number": result.get("test_number"), "description_ko": result.get("description_ko"),
            "ledger": body["ledger"]}


def newlab_pending(conn: sqlite3.Connection) -> list[dict]:
    """Counted tests that passed when they ran and were never proposed (oldest first)."""
    return R.trials_by_status(conn, NEWLAB, ("passed",), limit=200)[::-1]


def newlab_live_proposal(conn: sqlite3.Connection, trial_id: int) -> Optional[dict]:
    """The proposal row of this lab trial that is not 'blocked_cap', if any (a trial is proposed once)."""
    for p in R.list_proposals(conn, room_id=R.LAB_ROOM, limit=1000):
        if p.get("trial_id") == trial_id and p.get("status") != "blocked_cap":
            return p
    return None


def newlab_propose(env: ActionEnv, trial: dict) -> dict:
    """A stored pass: judged again with the count NOW (newlab_gate_now); still passing -> a proposal row of kind
    'newlab' (``change.account`` built by code from the trial row; ``change.proposal`` = newlab.proposal_of, no
    model words) for the owners, always 'awaiting_owner', written in ONE transaction with the trial's
    'proposed' result; then the room line and one Telegram. Failing now -> a 'lapsed' result. The new-strategy
    cap (active proposals and running new-strategy accounts together, ``newlab_cap_total``) full -> nothing is
    written: the room is told once and the pass waits ('passed') for a free slot. paper3.db unreadable or
    during the observation period: nothing (the pass waits in the ledger). A trial whose proposal already
    exists is never proposed again (a 'passed' latest result is repaired to 'proposed')."""
    tid = int(trial["id"])
    st, body = _stored(trial)
    if st != "passed":
        return {"proposed": False, "why": st}
    if env.observing:
        return {"proposed": False, "why": "observing"}
    old = newlab_live_proposal(env.conn, tid)
    if old is not None:                                      # proposed before (its result is missing): repair
        R.add_trial_result(env.conn, tid, "proposed", {**body, "proposal": (old.get("change") or {}).get("proposal"),
                                                       "proposal_id": old["id"], "repaired": True,
                                                       "proposed_ts": env.now_ms}, ts=env.now_ms)
        return {"proposed": False, "why": "already_proposed", "proposal_id": old["id"]}
    extras = X.paper_extras(env.paper_ro)
    if extras is None:
        return {"proposed": False, "why": "paper_unreadable"}
    gate, n_now = newlab_gate_now(env.conn, trial)
    desc = body.get("description_ko") or ""
    if gate.get("pass") is not True:
        R.add_trial_result(env.conn, tid, "lapsed", {**body, "gate_now": gate, "n_tests_now": n_now}, ts=env.now_ms)
        env.post("system", f"새 매매법 장부 #{tid}({desc})는 시험 때 관문을 통과했지만, 지금까지의 새 매매법 시험 수({n_now:,}개 "
                           f"뒤)로 다시 판정하면 통과하지 못해 제안하지 않습니다(기준 p < {0.05 / (n_now + 1):.3g}).",
                 {"newlab": True, "trial_id": tid, "status": "lapsed", "gate": gate, "n_tests_now": n_now})
        return {"proposed": False, "why": "lapsed", "gate": gate}
    like = {"ok": True, "status": "done", "spec": trial["spec"], "spec_hash": trial.get("spec_hash"),
            "description_ko": desc, "summary_ko": body.get("summary_ko") or "", "periods": body.get("gate_input")}
    prop = _nl.proposal_of(like, n_tests_now=n_now)
    account = X.newlab_account(trial)
    if prop is None or account is None:                      # cannot happen when gate passed; fail closed
        return {"proposed": False, "why": "no_proposal"}
    prop = {k: v for k, v in prop.items() if k not in ("idea", "name")}     # code-written fields only
    used = X.slots(env.conn, env.paper_ro, "newlab", None, extras)
    if used is None:
        return {"proposed": False, "why": "paper_unreadable"}
    if used >= env.newlab_cap_total:
        key = f"newlab_cap_note:{tid}"
        if R.get_cursor(env.conn, key) is None:
            env.post("system", f"새 매매법 장부 #{tid}({desc})는 관문을 통과했지만, 새 매매법 계좌 자리({env.newlab_cap_total}개: "
                               "두 분 확인을 기다리는 제안과 돌고 있는 계좌를 합해서)가 차서 지금은 제안하지 않습니다. 자리가 "
                               "나면 코드가 그때의 시험 수로 다시 판정해 제안합니다.",
                     {"newlab": True, "trial_id": tid, "status": "cap", "used": used, "cap": env.newlab_cap_total})
            R.set_cursor(env.conn, key, env.now_ms)
        return {"proposed": False, "why": "cap", "used": used}
    pgate = {**gate, "pass": True, "trial_id": tid, "n_tests": n_now}
    change = {"kind": "newlab", "account": account, "proposal": prop}
    try:                                       # the proposal and the trial's 'proposed' result: one transaction
        pid = R.add_proposal(env.conn, R.LAB_ROOM, None, tid, change, pgate, "awaiting_owner", ts=env.now_ms,
                             commit=False)
        R.add_trial_result(env.conn, tid, "proposed", {**body, "proposal": prop, "proposal_id": pid,
                                                       "n_tests_now": n_now, "proposed_ts": env.now_ms},
                           ts=env.now_ms, commit=False)
        env.conn.commit()
    except BaseException:
        env.conn.rollback()
        raise
    env.post("action", f"📄 새 매매법 제안 #{pid} (장부 #{tid}): {desc}\n5년 시험 관문을 통과했습니다(새 매매법 시험 {n_now + 1:,}번 "
                       "기준으로 다시 판정해도 통과). 같은 규칙(paper v4 매매법 그룹: 청산·크기·비용 그대로)의 새 paper 계좌로 새 자료에서 "
                       "확인하자는 제안이며, 두 분 OK가 있어야 시작합니다. 대시보드 '에이전트 방' → 새 매매법 연구실에서 "
                       "승인/거절할 수 있습니다. " + start_text(env.paper_ro),
             {"newlab": True, "action": "newlab_proposal", "trial_id": tid, "proposal_id": pid, "proposal": prop})
    sent = newlab_alert(env, tid, prop, body.get("test_number"), pid)
    return {"proposed": True, "trial_id": tid, "proposal_id": pid, "proposal": prop, "telegram": sent}


def newlab_alert(env: ActionEnv, trial_id: int, proposal: dict, test_number: Any = None,
                 proposal_id: Optional[int] = None) -> bool:
    """One Telegram message per pass (never twice for the same strategy: the mark is written before the send).
    Code-written text only (the spec's Korean description from code); not counted in the daily flag limit."""
    key = f"newlab_alert:{proposal.get('spec_hash') or trial_id}"
    if R.get_cursor(env.conn, key) is not None:
        return False
    R.set_cursor(env.conn, key, env.now_ms)
    num = f", 시험 {int(test_number):,}번째" if _row_id(test_number) else ""
    pnum = f" #{int(proposal_id)}" if _row_id(proposal_id) else ""
    after = ("승인하면 다음 봉 경계에 계좌 시작" if runtime_ready(env.paper_ro) else
             "추가 계좌 기능이 켜지기 전이라 승인해도 아직 계좌는 안 만들어짐")
    desc = telegram_safe(str(proposal.get('description_ko') or '')).strip()
    text = (f"승인 요청 · 새 매매법 제안{pnum}\n\n" + (f"{desc}\n" if desc else "")
            + f"5년 시험 통과 (장부 #{trial_id}{num})\n새 paper 계좌로 새 자료에서 확인하자는 제안\n{after}\n"
            f"→ 대시보드 '에이전트 방' → {env.room_title or '새 매매법 연구실'}")
    try:
        ok = env.notifier.send(WARN, text)
    except Exception as exc:  # delivery must not break the round
        ok, why = False, type(exc).__name__
    else:
        why = "텔레그램이 받지 않음"
    if ok is False:
        env.post("system", f"새 매매법 통과 알림 전송 실패: {why}", {"newlab": True, "trial_id": trial_id, "sent": False})
        return False
    env.post("action", f"📣 두 분께 새 매매법 통과 알림(텔레그램, {WARN})을 보냈습니다 (장부 #{trial_id}).",
             {"action": "newlab_alert", "trial_id": trial_id, "sent": True, "level": WARN})
    return True
