"""Call Claude Code in print mode, on the owners' subscription login.

Command (one call per role):
    claude -p "<instruction>" --model <sonnet|opus> --output-format json
           --tools "" --safe-mode --strict-mcp-config --no-session-persistence
           --system-prompt-file <role prompt>
with the data packet on stdin.

Why these flags:
- ``--tools ""`` removes every tool: the agent cannot read files, run
  commands or reach the network. It only sees its packet.
- ``--safe-mode`` skips CLAUDE.md, skills, plugins, hooks and MCP servers;
  login works normally. ``--bare`` is NOT used: in bare mode Claude Code
  ignores the subscription login and only accepts ANTHROPIC_API_KEY.
- The child process gets a minimal environment. ANTHROPIC_API_KEY,
  ANTHROPIC_AUTH_TOKEN and cloud-provider switches are removed, because in
  print mode an API key in the environment is always used and billed
  separately. Exchange and Telegram secrets are removed too.

Login on the server: run ``claude setup-token`` once (browser sign-in to the
subscription), put the printed token in the agents' env file as
CLAUDE_CODE_OAUTH_TOKEN (chmod 600). Calls count against the same plan
usage limits as chats and other Claude Code sessions.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Callable, Optional, Protocol

# Only these variables reach the child process.
ENV_ALLOW = ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "USER", "TMPDIR",
             "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR", "HTTPS_PROXY", "HTTP_PROXY",
             "NO_PROXY", "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE")
# Present in the parent -> warn: would switch billing or leak secrets if passed.
ENV_BILLING = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK",
               "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")

LIMIT_RE = re.compile(r"(session|weekly|usage|rate)[ -]limit", re.I)


class UsageLimitReached(RuntimeError):
    pass


class AgentCallError(RuntimeError):
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
                        obj = json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
                    return obj if isinstance(obj, dict) else None
        start = text.find("{", start + 1)
    return None


class ClaudeCodeRunner:
    def __init__(self, claude_bin: str = "claude", timeout: float = 900.0,
                 workdir: Optional[str] = None, env: Optional[dict] = None,
                 run: Callable = subprocess.run):
        self.bin = claude_bin
        self.timeout = timeout
        self.workdir = workdir or tempfile.mkdtemp(prefix="paperbot-agent-")
        self.env = child_env(env)
        self._run = run

    def command(self, model: str, prompt_file: str, instruction: str) -> list[str]:
        return [self.bin, "-p", instruction, "--model", model, "--output-format", "json",
                "--safe-mode", "--strict-mcp-config", "--no-session-persistence",
                "--system-prompt-file", prompt_file, "--tools", ""]

    def call(self, model: str, system_prompt: str, instruction: str, packet: dict) -> CallResult:
        with tempfile.NamedTemporaryFile("w", suffix=".md", dir=self.workdir, delete=False,
                                         encoding="utf-8") as fh:
            fh.write(system_prompt)
            prompt_file = fh.name
        try:
            proc = self._run(self.command(model, prompt_file, instruction),
                             input=json.dumps(packet, ensure_ascii=False, default=str),
                             capture_output=True, text=True, timeout=self.timeout,
                             cwd=self.workdir, env=self.env)
        except subprocess.TimeoutExpired as exc:
            raise AgentCallError(f"timed out after {self.timeout:.0f}s") from exc
        finally:
            os.unlink(prompt_file)
        out, err = proc.stdout or "", proc.stderr or ""
        try:
            envelope = json.loads(out)
        except json.JSONDecodeError:
            envelope = None
        text = envelope.get("result", "") if isinstance(envelope, dict) else out
        failed = proc.returncode != 0 or (isinstance(envelope, dict) and envelope.get("is_error"))
        if failed:
            blob = f"{text}\n{err}"
            if LIMIT_RE.search(blob):
                raise UsageLimitReached(blob.strip()[:300])
            raise AgentCallError(f"exit {proc.returncode}: {blob.strip()[:300]}")
        meta = {}
        if isinstance(envelope, dict):
            meta = {k: envelope.get(k) for k in ("duration_ms", "num_turns", "session_id", "usage")
                    if k in envelope}
        data = envelope.get("structured_output") if isinstance(envelope, dict) else None
        if not isinstance(data, dict):
            data = extract_json(text)
        return CallResult(text, data, meta)


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
