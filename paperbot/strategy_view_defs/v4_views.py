"""The paper v4 chart views: strategy id -> module in this folder, for the 44 DeepSeek-200 definitions and the reel.

Kept apart from ``NAMES`` (the 36 locked strategies' views; tests, the research prior and the monthly re-check read
NAMES as "the 36"). paperbot.strategy_views reads ``V4_VIEWS`` and imports each module only when a view is asked
for; a module that is not written yet (or fails to import) is skipped there, never an error.

    DeepSeek definition "F9_FVG" -> module "DS_F9_FVG", function ``view_DS_F9_FVG(df, tf)``
    the reel "REEL_H1"           -> module "REEL_H1",   function ``view_REEL_H1(df, tf)``

The DeepSeek ids are lib_c.DEFS of research/deepseek200/lib_c.py, read from its source with ``ast`` (the file is never
executed here: importing lib_c changes sys.path and the warnings filters). config.DS200_IDS is the same list
(tests/test_v4_shape.py checks it against lib_c.DEFS) and is the fallback when the file cannot be read.
"""

from __future__ import annotations

import ast
import os
from typing import Optional

from ..config import DS200_IDS, REEL_NAME

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIB_C = os.path.join(ROOT, "research", "deepseek200", "lib_c.py")
DS_PREFIX = "DS_"


def lib_c_ids(path: str = LIB_C) -> Optional[tuple[str, ...]]:
    """The definition ids of ``DEFS = [(id, family, tfs), ...]`` in lib_c.py, in its order; None when the file is
    missing or its DEFS is not a literal list of tuples whose first item is a string."""
    try:
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
    except (OSError, SyntaxError, ValueError):
        return None
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "DEFS" and isinstance(node.value, (ast.List, ast.Tuple))):
            ids = []
            for el in node.value.elts:
                if not (isinstance(el, ast.Tuple) and el.elts and isinstance(el.elts[0], ast.Constant)
                        and isinstance(el.elts[0].value, str)):
                    return None
                ids.append(el.elts[0].value)
            return tuple(ids) if ids else None
    return None


def module_of(strategy: str) -> str:
    """The module name of a v4 strategy's view ("F9_FVG" -> "DS_F9_FVG", "REEL_H1" -> "REEL_H1")."""
    return strategy if strategy == REEL_NAME else DS_PREFIX + strategy


DS_IDS: tuple[str, ...] = lib_c_ids() or DS200_IDS
V4_VIEWS: dict[str, str] = {**{d: module_of(d) for d in DS_IDS}, REEL_NAME: module_of(REEL_NAME)}
