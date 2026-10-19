"""The combined bot's take-profit ladder, a second form next to the rule bot's (paperbot/ladder.py, pinned for the
30-day verdict and never edited for the live bot).

Form 1 (``paperbot.ladder.LadderSpec``, the rule bot's and the first live bot's): lock ``first_lock`` net ROE once the
best net ROE reaches ``first_lock + trigger_gap``, then one lock ``step`` higher per ``step`` more.

Form 2 (owners 2026-10-19, the 15-strategy live bot): the same first lock, then the later locks sit ``next_gap`` under
their trigger and the triggers start at ``next_trigger`` and climb by ``step``:

    best net ROE >= 11%  ->  lock 10%
    best net ROE >= 15%  ->  lock 12%
    best net ROE >= 20%  ->  lock 17%
    best net ROE >= 25%  ->  lock 22%   ... and so on every 5% ("30%되면 27% 계속 그렇게").

``ComboLadder`` answers both forms with LadderSpec's interface (``lock_for``, ``first_lock``, ``step``,
``trigger_gap``) plus the trigger of a lock and the next step, so the engine, the dashboard's next-lock line and the
trade replay rebuild the same stop path. Net ROE has the engine's definition (paperbot/ladder.py ``net_roe``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

EPS = 1e-9


@dataclass(frozen=True)
class ComboLadder:
    first_lock: float = 0.10
    step: float = 0.05
    trigger_gap: float = 0.01
    next_trigger: Optional[float] = None     # form 2: the second trigger (0.15); None = form 1
    next_gap: Optional[float] = None         # form 2: each later lock sits this far under its trigger (0.03)

    @classmethod
    def of(cls, d: Optional[dict]) -> Optional["ComboLadder"]:
        """From a config's ``ladder`` dict; None when it lacks the three form-1 numbers."""
        if not isinstance(d, dict):
            return None
        try:
            first, step, gap = float(d["first_lock"]), float(d["step"]), float(d["trigger_gap"])
        except (KeyError, TypeError, ValueError):
            return None
        nt, ng = d.get("next_trigger"), d.get("next_gap")
        try:          # one of the two alone stays visible to problems() (lock_for then keeps form 1)
            return cls(first, step, gap, None if nt is None else float(nt), None if ng is None else float(ng))
        except (TypeError, ValueError):
            return None

    @property
    def two_part(self) -> bool:
        return self.next_trigger is not None and self.next_gap is not None

    @property
    def first_trigger(self) -> float:
        return self.first_lock + self.trigger_gap

    def lock_for(self, best_roe: float) -> Optional[float]:
        """Highest lock armed by ``best_roe`` (net), or None below the first trigger."""
        if not best_roe >= self.first_trigger - 1e-12:
            return None
        if not self.two_part:
            n = math.floor((best_roe - self.first_trigger) / self.step + EPS)
            return self.first_lock + self.step * n
        if not best_roe >= self.next_trigger - 1e-12:
            return self.first_lock
        n = math.floor((best_roe - self.next_trigger) / self.step + EPS)
        return self.next_trigger - self.next_gap + self.step * n

    def trigger_of(self, lock: float) -> float:
        """The best net ROE that arms ``lock``."""
        if self.two_part and lock > self.first_lock + EPS:
            return lock + self.next_gap
        return lock + self.trigger_gap

    def next_after(self, lock: Optional[float]) -> tuple[float, float]:
        """(the next lock, the best net ROE that arms it) after ``lock`` (None: nothing locked yet)."""
        if lock is None:
            return self.first_lock, self.first_trigger
        if self.two_part and lock <= self.first_lock + EPS:
            return self.next_trigger - self.next_gap, self.next_trigger
        nxt = lock + self.step
        return nxt, self.trigger_of(nxt)

    def index(self, lock: Optional[float]) -> int:
        """0 before the first lock, 1 at the first lock, then one more per step (the dashboard's step count)."""
        if lock is None:
            return 0
        if self.two_part:
            if lock <= self.first_lock + EPS:
                return 1
            return 2 + int(round((lock - (self.next_trigger - self.next_gap)) / self.step))
        return 1 + int(round((lock - self.first_lock) / self.step))

    def problems(self) -> list[str]:
        out = []
        if not (0 < self.first_lock < 1 and 0 < self.step < 1 and 0 < self.trigger_gap < 1):
            out.append("ladder의 first_lock, step, trigger_gap은 0~1 사이 비율입니다")
        if (self.next_trigger is None) != (self.next_gap is None):
            out.append("ladder의 next_trigger와 next_gap은 둘 다 적거나 둘 다 빼야 합니다")
        elif self.two_part:
            if not (0 < self.next_gap < 1 and 0 < self.next_trigger < 1):
                out.append("ladder의 next_trigger, next_gap은 0~1 사이 비율입니다")
            elif not self.next_trigger > self.first_trigger + EPS:
                out.append("ladder의 next_trigger는 첫 잠금이 걸리는 순ROE(first_lock + trigger_gap)보다 커야 합니다")
            elif not self.next_trigger - self.next_gap > self.first_lock + EPS:
                out.append("ladder의 두 번째 잠금(next_trigger - next_gap)은 첫 잠금보다 높아야 합니다")
        return out

    def describe(self) -> str:
        """Korean, for check-config and the start message."""
        first = f"순ROE {self.first_trigger:.0%}에서 {self.first_lock:.0%} 잠금"
        if not self.two_part:
            return f"{first}, 이후 {self.step:.0%}씩"
        t2, l2 = self.next_trigger, self.next_trigger - self.next_gap
        t3, l3 = t2 + self.step, l2 + self.step
        return (f"{first}, {t2:.0%}에서 {l2:.0%}, {t3:.0%}에서 {l3:.0%}, 그 뒤 {self.step:.0%}마다 "
                f"(닿은 순ROE - {self.next_gap:.0%})")
