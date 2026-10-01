"""US macro release times (CPI, FOMC, NFP, PCE) from data/macro_events.csv.

One line per event: ``ts_utc,kind,source_url``. ``ts_utc`` is ISO 8601 in UTC (for example
``2026-10-14T12:30:00Z``), ``kind`` is one of KINDS, ``source_url`` is the official page the
date was read from (federalreserve.gov, bls.gov, bea.gov). Lines starting with ``#`` and blank
lines are ignored. Usual release times in US Eastern: CPI, NFP and PCE 08:30, FOMC statement
14:00; ``et_to_utc`` converts with daylight saving time (zoneinfo America/New_York), and
``python -m paperbot.events line CPI 2026-10-14 <url>`` prints a ready line.

The file is read once, on first use. A missing file means no events (``near`` returns []);
a bad line is skipped and reported in ``problems()`` and by ``python -m paperbot.events check``.
"""

from __future__ import annotations

import bisect
import csv
import io
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

PATH = Path(__file__).resolve().parent.parent / "data" / "macro_events.csv"
KINDS = ("CPI", "FOMC", "NFP", "PCE")
KIND_KO = {"CPI": "소비자물가(CPI)", "FOMC": "FOMC 금리 결정", "NFP": "고용보고서(NFP)", "PCE": "PCE 물가"}
ET_TIME = {"CPI": "08:30", "NFP": "08:30", "PCE": "08:30", "FOMC": "14:00"}
NEW_YORK = ZoneInfo("America/New_York")
COLUMNS = ("ts_utc", "kind", "source_url")


@dataclass(frozen=True)
class Event:
    ts_ms: int
    kind: str
    source_url: str

    @property
    def ts_utc(self) -> str:
        return datetime.fromtimestamp(self.ts_ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def as_dict(self) -> dict:
        return {"kind": self.kind, "name_ko": KIND_KO.get(self.kind, self.kind), "ts_utc": self.ts_utc,
                "ts_ms": self.ts_ms, "source_url": self.source_url}


def parse_ts(s: str) -> int:
    """ISO 8601 -> epoch ms. A time without an offset is taken as UTC."""
    s = s.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def et_to_utc(day: str, hhmm: Optional[str] = None, kind: Optional[str] = None) -> str:
    """'2026-10-14' + '08:30' US Eastern (or the usual time of ``kind``) -> '2026-10-14T12:30:00Z'."""
    hhmm = hhmm or ET_TIME[kind]
    h, m = (int(x) for x in hhmm.split(":"))
    local = datetime.combine(date.fromisoformat(day), time(h, m), tzinfo=NEW_YORK)
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(text: str) -> tuple[list[Event], list[str]]:
    """CSV text -> (events sorted by time, one message per skipped line)."""
    lines = [(n, ln) for n, ln in enumerate(text.splitlines(), 1) if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        return [], []
    rows = list(csv.reader(io.StringIO("\n".join(ln for _, ln in lines))))
    header = [h.strip() for h in rows[0]]
    if tuple(header[:3]) != COLUMNS:
        return [], [f"line {lines[0][0]}: header must be {','.join(COLUMNS)}"]
    events, problems, seen = [], [], set()
    for (n, _), row in zip(lines[1:], rows[1:]):
        row = [x.strip() for x in row]
        if len(row) < 3:
            problems.append(f"line {n}: need ts_utc,kind,source_url")
            continue
        ts, kind, url = row[0], row[1].upper(), row[2]
        if kind not in KINDS:
            problems.append(f"line {n}: kind {row[1]!r} is not one of {', '.join(KINDS)}")
            continue
        if not url.startswith(("https://", "http://")):
            problems.append(f"line {n}: source_url missing")
            continue
        try:
            ms = parse_ts(ts)
        except ValueError:
            problems.append(f"line {n}: bad ts_utc {ts!r}")
            continue
        if (ms, kind) in seen:
            problems.append(f"line {n}: duplicate {kind} {ts}")
            continue
        seen.add((ms, kind))
        events.append(Event(ms, kind, url))
    events.sort(key=lambda e: (e.ts_ms, e.kind))
    return events, problems


_cache: Optional[tuple[list[Event], list[int], list[str]]] = None


def _loaded() -> tuple[list[Event], list[int], list[str]]:
    global _cache
    if _cache is None:
        try:
            text = Path(PATH).read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            text = ""
        evs, problems = parse(text)
        _cache = (evs, [e.ts_ms for e in evs], problems)
    return _cache


def reset() -> None:
    """Forget the loaded file (next call reads PATH again)."""
    global _cache
    _cache = None


def all_events() -> list[Event]:
    return list(_loaded()[0])


def problems() -> list[str]:
    return list(_loaded()[2])


def near(ts_ms: int, before_ms: int, after_ms: int) -> list[Event]:
    """Events whose time t has t - before_ms <= ts_ms <= t + after_ms (edges included):
    ``ts_ms`` lies from ``before_ms`` before the release to ``after_ms`` after it."""
    evs, keys, _ = _loaded()
    lo = bisect.bisect_left(keys, ts_ms - after_ms)
    hi = bisect.bisect_right(keys, ts_ms + before_ms)
    return evs[lo:hi]


def main(argv: list[str]) -> int:
    if argv[:1] == ["line"] and len(argv) in (4, 5):
        kind, day, url = argv[1].upper(), argv[2], argv[-1]
        if kind not in KINDS:
            print(f"kind must be one of {', '.join(KINDS)}", file=sys.stderr)
            return 2
        print(f"{et_to_utc(day, argv[3] if len(argv) == 5 else None, kind)},{kind},{url}")
        return 0
    if argv[:1] == ["check"]:
        evs, probs = all_events(), problems()
        for p in probs:
            print(p)
        by = {k: sum(e.kind == k for e in evs) for k in KINDS}
        span = f"{evs[0].ts_utc} .. {evs[-1].ts_utc}" if evs else "-"
        print(f"{PATH}: {len(evs)} events {by} {span}")
        return 1 if probs else 0
    print("usage: python -m paperbot.events line KIND YYYY-MM-DD [HH:MM_ET] SOURCE_URL\n"
          "       python -m paperbot.events check", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
