"""Dashboard v4 포지션 summary lines: an optional part that is absent must not print the word "null".

`el.replaceChildren(a, null)` writes the text "null" (unlike dom.js put() / h(), which skip null), so the 포지션
screen showed '... USDTnull' under the open positions when no DeepSeek / coin-flip position was open (seen in the
nav-top review, 10/06). The summary line and the best / worst line filter their optional parts first."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")


def test_positions_summary_lines_never_pass_null_to_replace_children():
    src = open(os.path.join(V4, "screens", "positions.js"), encoding="utf-8").read()
    for name in ("line", "bestLine"):
        i = src.index(f"    {name}.replaceChildren(")
        call = src[i:src.index(";\n", i)]
        assert call.startswith(f"    {name}.replaceChildren(...[") and call.endswith("].filter(Boolean))"), call
    # no other replaceChildren in the file ends with a bare `: null)` argument
    assert not re.search(r"replaceChildren\([^;]*: null\);", src)
