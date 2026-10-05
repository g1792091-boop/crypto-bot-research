"""Small helpers of the Obsidian vault exporter (paperbot/obsidian_export.py): palette, Korean time,
file names, YAML front matter, defensive redaction, callouts. No I/O, no database.

Palette: Catppuccin Mocha (dark) with Catppuccin Latte as the light fallback. The same names are used in the shipped
CSS (paperbot/obsidian_vault/template/.obsidian/snippets), the graph colour groups and the static preview.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

KST = timezone(timedelta(hours=9))
DAY_MS = 86_400_000

# ------------------------------------------------------------------ palette
MOCHA = {
    "rosewater": "#f5e0dc", "flamingo": "#f2cdcd", "pink": "#f5c2e7", "mauve": "#cba6f7", "red": "#f38ba8",
    "maroon": "#eba0ac", "peach": "#fab387", "yellow": "#f9e2af", "green": "#a6e3a1", "teal": "#94e2d5",
    "sky": "#89dceb", "sapphire": "#74c7ec", "blue": "#89b4fa", "lavender": "#b4befe", "text": "#cdd6f4",
    "subtext1": "#bac2de", "subtext0": "#a6adc8", "overlay2": "#9399b2", "overlay1": "#7f849c",
    "overlay0": "#6c7086", "surface2": "#585b70", "surface1": "#45475a", "surface0": "#313244",
    "base": "#1e1e2e", "mantle": "#181825", "crust": "#11111b",
}
LATTE = {
    "rosewater": "#dc8a78", "flamingo": "#dd7878", "pink": "#ea76cb", "mauve": "#8839ef", "red": "#d20f39",
    "maroon": "#e64553", "peach": "#fe640b", "yellow": "#df8e1d", "green": "#40a02b", "teal": "#179299",
    "sky": "#04a5e5", "sapphire": "#209fb5", "blue": "#1e66f5", "lavender": "#7287fd", "text": "#4c4f69",
    "subtext1": "#5c5f77", "subtext0": "#6c6f85", "overlay2": "#7c7f93", "overlay1": "#8c8fa1",
    "overlay0": "#9ca0b0", "surface2": "#acb0be", "surface1": "#bcc0cc", "surface0": "#ccd0da",
    "base": "#eff1f5", "mantle": "#e6e9ef", "crust": "#dce0e8",
}

# note type -> (graph colour name, tag)
TYPE_COLORS = {
    "허브": "yellow", "전략": "mauve", "회의": "blue", "교훈": "green", "가설": "peach", "연구": "teal",
    "규칙": "red", "직원": "pink", "점검": "sky", "시험": "maroon", "실험": "lavender",
}


def rgb_int(hex_color: str) -> int:
    return int(hex_color.lstrip("#"), 16)


# ------------------------------------------------------------------ time
def kst_dt(ms: Optional[int]) -> Optional[datetime]:
    if ms is None:
        return None
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).astimezone(KST)


def kst_day(ms: int) -> str:
    return kst_dt(ms).strftime("%Y-%m-%d")


def kst_min(ms: Optional[int]) -> str:
    d = kst_dt(ms)
    return "-" if d is None else d.strftime("%Y-%m-%d %H:%M")


def kst_hm(ms: Optional[int]) -> str:
    d = kst_dt(ms)
    return "-" if d is None else d.strftime("%H:%M")


def kst_stamp(ms: int) -> str:
    return kst_dt(ms).strftime("%Y-%m-%d %H:%M KST")


def iso_week(day: str) -> str:
    d = datetime.strptime(day, "%Y-%m-%d")
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


# ------------------------------------------------------------------ numbers
def num(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None


def pct(x: Any, digits: int = 1, sign: bool = True) -> str:
    v = num(x)
    if v is None:
        return "-"
    return f"{v * 100:+.{digits}f}%" if sign else f"{v * 100:.{digits}f}%"


def usd(x: Any, digits: int = 0) -> str:
    v = num(x)
    if v is None:
        return "-"
    return f"-${abs(v):,.{digits}f}" if v < 0 else f"${v:,.{digits}f}"


def fnum(x: Any, digits: int = 2) -> str:
    v = num(x)
    return "-" if v is None else f"{v:,.{digits}f}"


def mean(xs: Iterable[Any]) -> Optional[float]:
    v = [num(x) for x in xs]
    v = [x for x in v if x is not None]
    return sum(v) / len(v) if v else None


# ------------------------------------------------------------------ small-sample rule (riskreward.SMALL_N)
SMALL_N = 10        # = paperbot.agents.riskreward.SMALL_N (a test keeps them equal)
VERDICT_N = 30      # the checkpoint's minimum number of trades for a first verdict


def small_flag(n: int) -> str:
    if n < SMALL_N:
        return f"표본 적음 ({n}건 < {SMALL_N})"
    if n < VERDICT_N:
        return f"30건 미만 ({n}건)"
    return ""


def is_small(n: int) -> bool:
    return n < SMALL_N


# ------------------------------------------------------------------ names, links
_BAD = re.compile(r'[\\/:*?"<>|#^\[\]]')


def safe_name(s: str, limit: int = 80) -> str:
    """A file name part that is legal on Windows/Android and safe inside a [[wikilink]]."""
    s = unicodedata.normalize("NFC", str(s))
    s = _BAD.sub(" ", s)
    s = re.sub(r"[\x00-\x1f]", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    return (s[:limit].rstrip(" .")) or "무제"


def link(name: str, alias: Optional[str] = None) -> str:
    name = name.replace("|", "-")
    return f"[[{name}|{alias}]]" if alias and alias != name else f"[[{name}]]"


# ------------------------------------------------------------------ redaction
_REDACT = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{12,}"), "[비밀값 삭제]"),
    (re.compile(r"\b(?:ghp|gho|ghs|github_pat|xox[abprs]|AKIA)[A-Za-z0-9_\-]{12,}"), "[비밀값 삭제]"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]*"), "[비밀값 삭제]"),
    (re.compile(r"\b\d{6,}:[A-Za-z0-9_\-]{30,}"), "[봇 토큰 삭제]"),
    (re.compile(r"(?i)\b(api[_ -]?key|api[_ -]?secret|secret|token|password|passwd|oauth[_-]?token)\b"
                r"([\"']?\s*[:=]\s*[\"']?)[^\s\"',;)]{6,}"), r"\1\2[삭제]"),
    (re.compile(r"(?i)\bchat[_ ]?ids?\b([\"']?\s*[:=]?\s*[\"'\[]?)\s*-?\d{5,}(?:\s*,\s*-?\d{5,})*"), r"chat id [삭제]"),
    (re.compile(r"(?<![\w.])-100\d{8,}\b"), "[채팅 번호 삭제]"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[IP 삭제]"),
    (re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b"), "[IP 삭제]"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}\b"), "[이메일 삭제]"),
    (re.compile(r"(?<![\w.])/(?:etc|var|opt|root|home|srv|usr|tmp|mnt)/[\w.@/\-]*"), "[서버 경로 삭제]"),
]


def redact(text: Any) -> str:
    s = "" if text is None else str(text)
    for rx, rep in _REDACT:
        s = rx.sub(rep, s)
    return s


# ------------------------------------------------------------------ embedding foreign text safely
_TAG = re.compile(r"(?<=[\s(])#(?=[^\s#\d])")


def sanitize(text: Any, limit: Optional[int] = None, marker: str = " …(이하 생략)") -> str:
    """Text of an agent or a document that goes into a note: redacted, no wikilinks / tags / code fences of its
    own (they would add links, tags or break the note), cut at ``limit`` characters with a marker."""
    s = redact(text)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("[[", "[ [").replace("]]", "] ]").replace("```", "'''").replace("~~~", "'''").replace("%%", "% %")
    s = _TAG.sub(r"\\#", s)
    s = re.sub(r"(?m)^---\s*$", "- - -", s)
    if limit is not None and len(s) > limit:
        s = s[:limit].rstrip() + marker
    return s


def quote(text: str) -> str:
    return "\n".join(("> " + ln) if ln.strip() else ">" for ln in str(text).split("\n"))


def callout(kind: str, title: str, body: str = "", fold: str = "") -> str:
    """> [!kind]+- title  (fold '' / '+' / '-') then the body quoted."""
    head = f"> [!{kind}]{fold} {title}".rstrip()
    return head + ("\n" + quote(body) if body else "") + "\n"


def badge(kind: str) -> str:
    """Inline label: where a number or a sentence comes from (CSS styles it; plain text without the CSS)."""
    label = {"code": "코드 계산", "ai": "AI 작성", "doc": "원문 문서", "mixed": "코드 계산 + AI 작성",
             "small": "표본 적음", "none": "아직 없음"}[kind]
    return f'<span class="pb-badge pb-{kind}">{label}</span>'


# ------------------------------------------------------------------ YAML front matter
def _yv(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return json.dumps(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_yv(x) for x in v) + "]"
    s = str(v)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    return json.dumps(s, ensure_ascii=False)


def frontmatter(props: dict) -> str:
    """Valid YAML (JSON-style scalars, flow lists). None values are left out; keys keep insertion order."""
    lines = ["---"]
    for k, v in props.items():
        if v is None:
            continue
        lines.append(f"{k}: {_yv(v)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ tables
def md_cell(x: Any) -> str:
    s = "-" if x is None or x == "" else str(x)
    return s.replace("|", "\\|").replace("\n", " ")


def table(headers: list[str], rows: list[list[Any]], align: Optional[list[str]] = None) -> str:
    if not rows:
        return ""
    align = align or ["l"] * len(headers)
    sep = {"l": "---", "r": "---:", "c": ":---:"}
    out = ["| " + " | ".join(md_cell(h) for h in headers) + " |",
           "|" + "|".join(sep[a] for a in align) + "|"]
    for r in rows:
        out.append("| " + " | ".join(md_cell(c) for c in r) + " |")
    return "\n".join(out) + "\n"


def mermaid(code: str) -> str:
    return "```mermaid\n" + code.strip("\n") + "\n```\n"


def bar(frac: float, width: int = 20) -> str:
    frac = max(0.0, min(1.0, frac))
    k = int(round(frac * width))
    return "█" * k + "░" * (width - k)


def normalize_md(text: str) -> str:
    """Blank lines where Markdown needs them (before headings, tables and callouts, and after a quote block), outside
    code fences, so a note renders the same in Obsidian's reading view, live preview and on a phone."""
    out: list[str] = []
    fence = False
    for ln in text.split("\n"):
        if ln.lstrip().startswith("```"):
            if not fence and out and out[-1].strip():
                out.append("")
            fence = not fence
            out.append(ln)
            continue
        if not fence and out and out[-1].strip():
            prev = out[-1]
            if (ln.startswith("#") and re.match(r"#{1,6} ", ln)) or \
               (ln.startswith("|") and not prev.startswith("|")) or \
               (ln.startswith("> [!") and not prev.startswith(">")) or \
               (prev.startswith(">") and ln.strip() and not ln.startswith(">")) or \
               (prev.startswith("|") and ln.strip() and not ln.startswith("|")):
                out.append("")
        out.append(ln)
    return "\n".join(out)
