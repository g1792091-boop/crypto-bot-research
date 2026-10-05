"""v4 skins (owners 10/05, "미래 AI 느낌"): the "ai" skin is the default look of the whole dashboard, "classic" (the first
navy + yellow look) is one tap away (서버 group menu, remembered per device). Checks on the page files:

- tokens.css: the ai block overrides the chrome only (the pixel office scene keeps its tokens), its text colours pass
  WCAG AA (4.5:1) on both panel colours, the comparison pair and the group colours never fall back on up / down or on
  one another;
- the skin is applied at boot before the shell draws, the switch sits in the shell, the choice goes through the wrapped
  local storage helper;
- no screen or core script writes a literal colour (every colour is a token, so both skins hold everywhere).
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")


def _read(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as f:
        return f.read()


def _blocks():
    src = re.sub(r"/\*.*?\*/", "", _read("tokens.css"), flags=re.S)
    out = {}
    for sel, body in re.findall(r"(:root[^{]*)\{([^}]*)\}", src):
        out[sel.strip()] = dict(re.findall(r"(--[\w-]+):\s*([^;]+);", body))
    return out


def _lum(hx):
    hx = hx.lstrip("#")
    rgb = [int(hx[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    f = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]


def _ratio(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_ai_skin_is_the_default_and_keeps_the_office_tokens():
    b = _blocks()
    base, ai = b[":root"], b[':root:not([data-skin="classic"])']
    assert ai["--bg"] == "#121519" and ai["--surface"] == "#1a1e23" and ai["--accent"] == "#19c3b1" and ai["--up"] == "#22c9a4"
    assert base["--accent"] == "#f6c445" and base["--bg"] == "#0a1020"            # classic kept as the base block
    office = [k for k in base if re.match(r"--(wood|wall|desk|monitor|screen|table|bubble|sky|sun|city|window|clock|px-|av-)", k)]
    assert len(office) > 20
    assert not set(office) & set(ai), "the pixel office scene must look the same in both skins"
    # the group colours and the neutral comparison pair have their own hues in the ai skin (its accent is teal)
    assert ai["--series-core"] != ai["--accent"] and ai["--series-core"] != ai["--series-ds"]
    assert ai["--cmp-hi"] != ai["--cmp-lo"] and not {ai["--cmp-hi"], ai["--cmp-lo"]} & {ai["--up"], ai["--down"], ai["--accent"]}


def test_ai_skin_text_passes_aa_on_both_panels():
    ai = _blocks()[':root:not([data-skin="classic"])']
    for panel in (ai["--surface"], ai["--surface-2"]):
        for k in ("--ink", "--ink-2", "--muted", "--accent", "--up", "--down", "--warn", "--term-yellow", "--term-cyan"):
            assert _ratio(ai[k], panel) >= 4.5, (k, panel, round(_ratio(ai[k], panel), 2))
    assert _ratio(ai["--accent-ink"], ai["--accent"]) >= 4.5


def test_skin_is_applied_at_boot_and_switchable_from_the_shell():
    skin, main, shell, base = _read("core", "skin.js"), _read("core", "main.js"), _read("core", "shell.js"), _read("base.css")
    assert 'export const DEFAULT_SKIN = "ai";' in skin and "local.get(KEY, DEFAULT_SKIN)" in skin and "local.set(KEY, x.id)" in skin
    assert "localStorage" not in skin                                        # only through dom.js local (try/catch)
    assert main.index("applySkin();") < main.index("startShell();")
    assert "skinSwitch(() => remount())" in shell and "export function remount()" in _read("core", "router.js")
    assert ':root:not([data-skin="classic"]) body {' in base and "background: var(--botbar);" in base
    assert '<meta name="theme-color" content="#121519">' in _read("index.html")
    # no animation from the skin: glows are static
    tail = base[base.index(':root:not([data-skin="classic"]) body {'):]
    assert "animation" not in tail and "@keyframes" not in tail


def test_no_script_writes_a_literal_colour():
    bad = []
    for sub in ("screens", "core"):
        for name in sorted(os.listdir(os.path.join(V4, sub))):
            if not name.endswith(".js"):
                continue
            src = re.sub(r"^\s*//.*$", "", _read(sub, name), flags=re.M)
            for m in re.finditer(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b(?![\w-])|\brgba?\(\s*\d", src):
                line = src[: m.start()].count("\n") + 1
                bad.append(f"{sub}/{name}:{line}: {m.group(0)}")
    assert not bad, bad
