"""Call Claude Code in print mode, on the owners' subscription login.

Command (one call per role):
    claude -p "<instruction>" --model <sonnet|opus> --output-format stream-json --verbose
           --tools "" --safe-mode --strict-mcp-config --no-session-persistence
           --system-prompt-file <role prompt>
with the data packet on stdin.

Why these flags:
- ``--tools ""`` removes every tool: the agent cannot run commands or reach
  the network, and it cannot read files ITSELF. Claude Code still expands an
  ``@<path>`` mention anywhere in the -p prompt (stdin included) into a file
  read that is sent to the model, whatever the flags: ``call`` therefore
  sends every '@' of the packet as its JSON escape (``\\u0040``), so no packet
  text (an owner post, a model's earlier line) can name a file to attach.
  The agent only sees its packet.
- ``CLAUDE_CODE_MAX_OUTPUT_TOKENS`` (``MAX_OUTPUT_TOKENS``) bounds the output
  of each model request (thinking included); without it the CLI asks for 128k.
  It does NOT bound a call by itself: when an answer reaches that ceiling,
  Claude Code asks the model again ("Output token limit hit. Resume
  directly…", up to 3 more times, each re-sending the whole input), and once
  more when an answer shows no text. ``call`` therefore reads the CLI's
  stream-json events and kills the CLI (its whole process group) at the first
  sign of such a further request (``_Stream``): a synthetic 'user' event
  (written just before it) or an answer with a new message id. At most one
  more request can have started, so one call uses at most
  ``call_charge(input)`` tokens (2 x input + 3 x the ceiling), which the rooms'
  pre-call budget check charges: no call runs past a token cap. A call stopped
  this way raises AgentCallError with the tokens it may have used (the model
  ran: its turn is skipped, never taken for an outage).
- ``--safe-mode`` skips CLAUDE.md, skills, plugins, hooks and MCP servers;
  login works normally. ``--bare`` is NOT used: in bare mode Claude Code
  ignores the subscription login and only accepts ANTHROPIC_API_KEY.
- The child process gets a minimal environment. ANTHROPIC_API_KEY,
  ANTHROPIC_AUTH_TOKEN and cloud-provider switches are removed, because in
  print mode an API key in the environment is always used and billed
  separately. Exchange and Telegram secrets are removed too.

- ``--setting-sources ""`` ignores the user/project/local settings files: an
  ``env`` block in ~/.claude/settings.json (e.g. an ANTHROPIC_API_KEY) would
  otherwise switch the child to pay-per-token API billing. Login still works.
  A Console API key stored by ``/login`` in ~/.claude.json is used whatever
  the flags; ``auth_preflight`` refuses to run when one is configured.

Login on the server: run ``claude setup-token`` once (browser sign-in to the
subscription), put the printed token in the agents' env file as
CLAUDE_CODE_OAUTH_TOKEN (chmod 600). Never choose "Anthropic Console account"
when logging in as the paperbot user. Calls count against the same plan
usage limits as chats and other Claude Code sessions.
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import weakref
from dataclasses import dataclass
from typing import Callable, Optional, Protocol

# Only these variables reach the child process.
ENV_ALLOW = ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "USER", "TMPDIR",
             "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR", "HTTPS_PROXY", "HTTP_PROXY",
             "NO_PROXY", "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE")
# Output ceiling of every model request (thinking plus the small JSON answer), set in the child's
# environment: the CLI otherwise asks for max_tokens=128000.
MAX_OUTPUT_TOKENS = 16_000
MAX_OUTPUT_ENV = "CLAUDE_CODE_MAX_OUTPUT_TOKENS"
# Model requests one call can make: the answer and, at worst, one more that the CLI started (to resume an
# answer cut at the ceiling, or one with no text) before ``call`` stopped it.
MAX_REQUESTS_PER_CALL = 2


def call_charge(est_input: int) -> int:
    """Most tokens one call can use, for the pre-call budget check (``ClassBudget.call``). Request k re-sends
    the input and the k-1 answers before it (each at most the ceiling) and writes at most the ceiling:
    for MAX_REQUESTS_PER_CALL = 2 that is 2 x input + 3 x MAX_OUTPUT_TOKENS."""
    n, est = MAX_REQUESTS_PER_CALL, max(0, int(est_input))
    return n * est + MAX_OUTPUT_TOKENS * n * (n + 1) // 2


# Present in the parent -> warn: would switch billing or leak secrets if passed.
ENV_BILLING = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK",
               "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")

# Plan usage / rate limits in the CLI's error text (e.g. "5-hour limit reached ∙ resets 3pm",
# "You've hit your limit · resets 3pm", "You've hit your Sonnet limit · resets …" (the Sonnet weekly
# limit of Max plans), "You're out of extra usage · resets …", "API Error: 429 rate_limit_error").
LIMIT_RE = re.compile(r"(session|weekly|usage|rate|hour|opus|sonnet)[ -]?limit|limit reached"
                      r"|hit your (?:\w+ )?limit|out of extra usage|rate_limit_error|\b429\b", re.I)


class UsageLimitReached(RuntimeError):
    tokens = 0          # usage the CLI still reported for the failed call (then it ran and is counted)


class AgentCallError(RuntimeError):
    tokens = 0          # usage the CLI still reported for the failed call


USAGE_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
MODEL_USAGE_KEYS = ("inputTokens", "cacheCreationInputTokens", "cacheReadInputTokens", "outputTokens")


def _sum(d, keys) -> int:
    if not isinstance(d, dict):
        return 0
    try:
        return sum(max(0, int(d.get(k) or 0)) for k in keys)
    except (TypeError, ValueError):
        return 0


def _usage_dict(envelope) -> dict:
    """The envelope's ``usage`` (budget.tokens_of's fields); when its ``modelUsage`` (every model request of
    the call, per model) adds up to more, as in an error envelope whose ``usage`` is empty or covers only
    the first request, that total in the same fields. {} when neither is there."""
    if not isinstance(envelope, dict):
        return {}
    u = envelope.get("usage") if isinstance(envelope.get("usage"), dict) else {}
    per = envelope.get("modelUsage") if isinstance(envelope.get("modelUsage"), dict) else {}
    tot = {k: sum(_sum(m, (mk,)) for m in per.values()) for k, mk in zip(USAGE_KEYS, MODEL_USAGE_KEYS)}
    if sum(tot.values()) > _sum(u, USAGE_KEYS):
        return tot
    return {k: u[k] for k in USAGE_KEYS if k in u}


def _usage_tokens(envelope) -> int:
    """Tokens the CLI envelope reports for the whole call (``usage`` or, when larger, ``modelUsage``), 0 when
    absent."""
    return _sum(_usage_dict(envelope), USAGE_KEYS)


class AgentTimeout(AgentCallError):
    """The call ran out of time (the CLI was stopped); it probably used tokens that are never reported.
    ``tokens``: what the events show the model may have used (0 when it never showed any activity)."""


class _Stream:
    """Claude Code's stream-json events of one call (``--output-format stream-json --verbose``; a single
    JSON envelope of ``--output-format json`` reads as the result too). ``feed`` returns True when the CLI
    has started, or is about to start, another model request for this call:
    - a 'user' event: the CLI's own "Output token limit hit. Resume directly…" (after an answer cut at the
      output ceiling) or "no visible output" nudge; with no tools there is no other user turn, and it is
      written just before the request;
    - an answer (assistant event) with a new message id: a further request already streaming;
    - an API retry after the model already streamed (the request is sent again).
    API error messages (a plan limit, 'response exceeded the output token maximum') are not answers."""

    def __init__(self) -> None:
        self.result: Optional[dict] = None   # the 'result' event (or the whole JSON envelope)
        self.inputs: dict = {}               # message id -> input tokens of that model request
        self.active = False                  # the model streamed something (thinking or an answer block)
        self.more = False                    # another request was started or is about to be
        self.lines: list[str] = []

    def feed(self, line: str) -> bool:
        line = (line or "").strip()
        if not line:
            return False
        self.lines.append(line)
        try:
            ev = json.loads(line)
        except (ValueError, RecursionError):
            return False
        if not isinstance(ev, dict):
            return False
        t = ev.get("type")
        if t == "result" or (t is None and ("result" in ev or "is_error" in ev)):
            self.result = ev
            return False
        if t == "user":
            if ev.get("isSynthetic") or self.inputs or self.active:
                self.more = True
        elif t == "system":
            sub = ev.get("subtype")
            if sub == "thinking_tokens":
                self.active = True
            elif sub == "api_retry" and (self.inputs or self.active):
                self.more = True
        elif t == "assistant" and not (ev.get("error") or ev.get("is_api_error_message") or ev.get("api_error")):
            msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}
            self.active = True
            mid = msg.get("id")
            if isinstance(mid, str) and mid not in self.inputs:
                if self.inputs:
                    self.more = True
                self.inputs[mid] = _sum(msg.get("usage"), USAGE_KEYS[:3])
        return self.more

    def worst(self, est: int) -> int:
        """Most tokens the requests seen so far can have used: each at its input plus the output ceiling
        (the first at the estimate when its input was never shown, once the model showed activity) and,
        when a further request may have been sent before the CLI was stopped, one more at the input
        (the estimate, or the largest input seen) plus the ceiling (the first answer, re-sent)."""
        c, est = MAX_OUTPUT_TOKENS, max(0, int(est))
        spent = sum(i + c for i in self.inputs.values())
        if not self.inputs and (self.active or self.more):
            spent = est + c
        if self.more and len(self.inputs) < MAX_REQUESTS_PER_CALL:
            spent += max([est, *self.inputs.values()]) + c
        return spent


def _kill(proc) -> None:
    """Stop the CLI and anything it started (its own process group, ``start_new_session``) at once."""
    if isinstance(proc, subprocess.Popen):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        proc.kill()
    except (ProcessLookupError, OSError):
        pass


@dataclass
class CallResult:
    text: str
    data: Optional[dict]  # parsed JSON object from the answer, if any
    meta: dict


class Runner(Protocol):
    def call(self, model: str, system_prompt: str, instruction: str, packet: dict) -> CallResult: ...


def child_env(parent: Optional[dict] = None) -> dict:
    parent = dict(os.environ if parent is None else parent)
    return {k: v for k, v in parent.items() if k in ENV_ALLOW}


def call_env(parent: Optional[dict] = None) -> dict:
    """The child's environment: the allowlisted variables plus the fixed output ceiling."""
    return {**child_env(parent), MAX_OUTPUT_ENV: str(MAX_OUTPUT_TOKENS)}


# Claude Code's own part of every request (its short system preamble, the environment block, the
# instruction): counted with the packet in every input estimate.
CLI_OVERHEAD_TOKENS = 1_000


def input_estimate(payload: str, system_prompt: str = "", instruction: str = "") -> int:
    """Rough input tokens of one request: UTF-8 bytes / 3 (a Korean-heavy packet, about one token per Hangul
    character of three bytes, is not undercounted) plus the CLI's own part."""
    n = sum(len((x or "").encode("utf-8", "replace")) for x in (payload, system_prompt, instruction))
    return n // 3 + CLI_OVERHEAD_TOKENS


def escape_mentions(payload: str) -> str:
    """Claude Code expands '@<path>' anywhere in the -p prompt (stdin included) into a file read sent to
    the model, even with --tools "": send '@' as its JSON escape. '@' only ever occurs inside JSON
    strings of the packet, so this is lossless (json.loads gives back the same packet)."""
    return payload.replace("@", "\\u0040")


def billing_warnings(parent: Optional[dict] = None) -> list[str]:
    parent = os.environ if parent is None else parent
    return [k for k in ENV_BILLING if parent.get(k)]


def extract_json(text: str) -> Optional[dict]:
    """First JSON object in the text (tolerates code fences and prose)."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        # NaN / Infinity are not JSON numbers: they become null, never reach code
                        obj = json.loads(text[start:i + 1], parse_constant=lambda _c: None)
                    except (ValueError, RecursionError):
                        break
                    return obj if isinstance(obj, dict) else None
        start = text.find("{", start + 1)
    return None


class ClaudeCodeRunner:
    def __init__(self, claude_bin: str = "claude", timeout: float = 900.0,
                 workdir: Optional[str] = None, env: Optional[dict] = None,
                 run: Optional[Callable] = None, popen: Callable = subprocess.Popen):
        self.bin = claude_bin
        self.timeout = timeout
        self.workdir = workdir or tempfile.mkdtemp(prefix="paperbot-agent-")
        if workdir is None:             # our own scratch folder: removed with the runner (or at exit)
            weakref.finalize(self, shutil.rmtree, self.workdir, True)
        self.env = call_env(env)
        self._run = run                 # tests: a subprocess.run stand-in (whole output at once, no stop)
        self._popen = popen

    def command(self, model: str, prompt_file: str, instruction: str) -> list[str]:
        return [self.bin, "-p", instruction, "--model", model, "--output-format", "stream-json", "--verbose",
                "--safe-mode", "--strict-mcp-config", "--no-session-persistence", "--setting-sources", "",
                "--system-prompt-file", prompt_file, "--tools", ""]

    def _stream(self, cmd: list[str], payload: str, st: _Stream) -> tuple[Optional[int], str, str]:
        """Run the CLI, feeding its stdout lines to ``st`` as they come. Returns (exit code, stderr, why):
        why is '' when it ended by itself, 'more' when it was stopped because it started another model
        request, 'timeout' when it ran out of time (then it was stopped too)."""
        with tempfile.TemporaryFile(dir=self.workdir) as err:
            proc = self._popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, text=True,
                               encoding="utf-8", errors="replace", cwd=self.workdir, env=self.env,
                               start_new_session=True)
            lines: queue.Queue = queue.Queue()
            done = object()

            def feed() -> None:             # a large packet never blocks the reading below
                try:
                    proc.stdin.write(payload)
                    proc.stdin.close()
                except (OSError, ValueError):
                    pass

            def read() -> None:
                try:
                    for line in proc.stdout:
                        lines.put(line)
                except (OSError, ValueError):
                    pass
                finally:
                    lines.put(done)

            threading.Thread(target=feed, daemon=True).start()
            threading.Thread(target=read, daemon=True).start()
            deadline = time.monotonic() + self.timeout
            why = ""
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    why = "timeout"
                    break
                try:
                    line = lines.get(timeout=min(left, 1.0))
                except queue.Empty:
                    continue
                if line is done:
                    break
                if st.feed(line):
                    why = "more"
                    break
                if st.result is not None:   # the call's last event: the CLI is exiting
                    break
            if why:
                _kill(proc)
            try:
                code = proc.wait(timeout=max(1.0, min(30.0, deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                _kill(proc)
                code = proc.wait(timeout=10)
            try:
                err.seek(0)
                stderr = err.read().decode("utf-8", "replace")
            except (OSError, ValueError):
                stderr = ""
        return code, stderr, why

    def call(self, model: str, system_prompt: str, instruction: str, packet: dict) -> CallResult:
        with tempfile.NamedTemporaryFile("w", suffix=".md", dir=self.workdir, delete=False,
                                         encoding="utf-8") as fh:
            fh.write(system_prompt)
            prompt_file = fh.name
        st = _Stream()
        try:
            payload = json.dumps(packet, ensure_ascii=False, default=str)
            payload = payload.encode("utf-8", "replace").decode("utf-8")    # a lone surrogate never breaks stdin
            payload = escape_mentions(payload)       # no packet text can make the CLI attach a local file
            est = input_estimate(payload, system_prompt, instruction)
            cmd = self.command(model, prompt_file, instruction)
            if self._run is not None:
                try:
                    proc = self._run(cmd, input=payload, capture_output=True, text=True, timeout=self.timeout,
                                     cwd=self.workdir, env=self.env)
                except subprocess.TimeoutExpired as exc:
                    raise AgentTimeout(f"timed out after {self.timeout:.0f}s") from exc
                for line in (proc.stdout or "").splitlines():
                    st.feed(line)
                code, err, why = proc.returncode, proc.stderr or "", ""
            else:
                code, err, why = self._stream(cmd, payload, st)
        finally:
            os.unlink(prompt_file)
        envelope = st.result
        if why == "timeout":
            exc = AgentTimeout(f"timed out after {self.timeout:.0f}s")
            exc.tokens = max(st.worst(est) if st.active or st.inputs else 0, _usage_tokens(envelope))
            raise exc
        if why == "more":
            exc = AgentCallError("Claude Code started another model request for this call (the answer reached "
                                 f"the {MAX_OUTPUT_TOKENS} output token ceiling or had no text): stopped")
            exc.tokens = max(st.worst(est), _usage_tokens(envelope))
            raise exc
        text = envelope.get("result", "") if isinstance(envelope, dict) else "\n".join(st.lines)
        text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False, default=str)
        failed = code != 0 or (isinstance(envelope, dict) and envelope.get("is_error"))
        if failed:
            blob = f"{text}\n{err}"
            exc = (UsageLimitReached(blob.strip()[:300]) if LIMIT_RE.search(blob)
                   else AgentCallError(f"exit {code}: {blob.strip()[:300]}"))
            exc.tokens = _usage_tokens(envelope)
            raise exc
        meta = {}
        if isinstance(envelope, dict):
            meta = {k: envelope.get(k) for k in ("duration_ms", "num_turns", "session_id")
                    if k in envelope}
            u = _usage_dict(envelope)
            if u:
                meta["usage"] = u
        data = envelope.get("structured_output") if isinstance(envelope, dict) else None
        if not isinstance(data, dict):
            data = extract_json(text)
        return CallResult(text, data, meta)


def auth_preflight(claude_bin: str = "claude", env: Optional[dict] = None, run: Callable = subprocess.run,
                   timeout: float = 30.0) -> tuple[bool, str]:
    """Before a real tick: is Claude Code logged in with the subscription (not an API key)?
    Runs ``claude --setting-sources "" auth status --json`` (no model call) with the child's own
    environment. Refuses when not logged in, when the answer names an ``apiKeySource`` (an
    ANTHROPIC_API_KEY reaching the child, or a Console key stored by /login in ~/.claude.json),
    when authMethod is 'api_key', or when the provider is not first-party (Bedrock, Vertex: authMethod
    'third_party' or an apiProvider other than 'firstParty'): any of these bills per token, outside
    the plan's limits.
    Returns (ok, reason)."""
    cmd = [claude_bin, "--setting-sources", "", "auth", "status", "--json"]
    try:
        proc = run(cmd, capture_output=True, text=True, timeout=timeout, env=call_env(env))
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"claude auth status failed: {type(exc).__name__}: {str(exc)[:200]}"
    try:
        st = json.loads(proc.stdout or "")
    except ValueError:
        st = None
    if not isinstance(st, dict):
        return False, f"claude auth status gave no JSON (exit {proc.returncode}): {(proc.stderr or '')[:200]}"
    if st.get("loggedIn") is not True:
        return False, "Claude Code is not logged in for this user (run `claude setup-token`)"
    if "apiKeySource" in st:
        return False, (f"Claude Code would use an API key ({st.get('apiKeySource')}), billed per token outside "
                       "the subscription; remove it (ANTHROPIC_API_KEY, or the Console login in ~/.claude.json)")
    if st.get("authMethod") == "api_key":
        return False, "Claude Code is logged in with an API key, not the subscription"
    # Bedrock / Vertex / Foundry (e.g. a root-managed settings env): billed to a cloud account per token
    if st.get("authMethod") == "third_party" or st.get("apiProvider") not in (None, "firstParty"):
        return False, (f"Claude Code would use a third-party provider ({st.get('apiProvider') or st.get('authMethod')}), "
                       "billed per token outside the subscription")
    return True, str(st.get("authMethod") or "")


class FakeRunner:
    """Returns canned answers per role (tests and --dry-run)."""

    def __init__(self, answers: Optional[dict] = None, fail: Optional[dict] = None):
        self.answers = answers or {}
        self.fail = fail or {}
        self.calls: list[dict] = []

    def call(self, model: str, system_prompt: str, instruction: str, packet: dict) -> CallResult:
        rid = packet.get("role")
        self.calls.append({"role": rid, "model": model, "packet": packet})
        if rid in self.fail:
            raise self.fail[rid]
        ans = self.answers.get(rid)
        if callable(ans):
            ans = ans(packet)
        if ans is None:
            ans = default_dry_answer(rid)
        text = ans if isinstance(ans, str) else json.dumps(ans, ensure_ascii=False)
        return CallResult(text, extract_json(text), {"fake": True})


def default_dry_answer(rid: Optional[str]) -> dict:
    if rid == "team_lead":
        return {"summary": ["(dry-run) 오늘 요약", "(dry-run) 주요 문제 없음",
                            "(dry-run) 위험 수준 정상"],
                "human_actions": [], "glossary": [], "watch_next": []}
    base = {"headline": f"(dry-run) {rid}", "findings": [], "data_gaps": [],
            "questions_for_humans": []}
    if rid == "risk_officer":
        base.update({"risk_level": "normal", "actions": []})
    else:
        base["proposals"] = []
    return base
