"""v4 readability (owners 10/06: "디자인은 마음에 드는데 예전 대시보드보다 내용이 작아 보이고 보기 힘들다").

- no px font-size below 12px in any v4 css file (a font shorthand counts too);
- every font size in v4 css reads a --t-* token (or calc(Npx * var(--ts)) for the big LED digits); the few exceptions
  are listed here by file and value;
- tokens.css defines the three 글자 크기 steps on <html data-text="md|lg|xl"> and none of them goes below 12px;
- the 글자 크기 control (core/textsize.js) sits in the header next to 화면 색, is applied at boot and is remembered per
  device through dom.js `local` (try/catch);
- --muted and --ink-2 read at 4.5:1 or better on --bg, --surface, --surface-2 and --console in both skins.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")

# font sizes that are not a --t-* token, on purpose: relative sizes and the replay LED that fits a phone's width
EXCEPTIONS = {
    ("screens/home-shared.css", ".9em"),
    ("screens/replay.css", "9.5vw"),
    ("screens/replay.css", "7vw"),
    ("screens/flow.css", "0"),          # a phone calendar cell's tag shrinks to a 6px dot: no text is shown
}


def _read(rel):
    with open(os.path.join(V4, rel), encoding="utf-8") as f:
        return f.read()


def _css_files():
    out = []
    for d, _, fs in os.walk(V4):
        for f in fs:
            if f.endswith(".css"):
                out.append(os.path.relpath(os.path.join(d, f), V4).replace(os.sep, "/"))
    return sorted(out)


def _nocomment(s):
    return re.sub(r"/\*.*?\*/", "", s, flags=re.S)


def _sizes(css):
    """(value) of every font-size declaration and of the size part of every font shorthand."""
    out = []
    for m in re.finditer(r"font-size:\s*([^;}]+)", css):
        out.append(m.group(1).strip())
    for m in re.finditer(r"(?<![-\w])font:\s*([^;}]+)", css):
        v = m.group(1).strip()
        if v.startswith(("inherit", "var(")):
            continue
        v = re.sub(r"^(?:(?:italic|normal|bold|\d00)\s+)*", "", v)
        size = re.match(r"(calc\((?:[^()]|\([^()]*\))*\)|min\((?:[^()]|\([^()]*\))*\)|var\([^)]*\)|[\d.]+[a-z%]*)", v)
        out.append(size.group(1) if size else v)
    return out


def test_no_px_font_size_below_12px_in_any_v4_css():
    bad = []
    for f in _css_files():
        css = _nocomment(_read(f))
        for m in re.finditer(r"font(?:-size)?:[^;}]*?(?<![\w.-])(\d+(?:\.\d+)?)px", css):
            px = float(m.group(1))
            if px < 12:
                bad.append((f, m.group(0)[:80]))
    # and the tokens themselves, in every 글자 크기 step
    tok = _nocomment(_read("tokens.css"))
    for m in re.finditer(r"--t-(2xs|xs|sm|md|lg|xl|2xl|led):\s*([\d.]+)px", tok):
        if float(m.group(2)) < 12:
            bad.append(("tokens.css", m.group(0)))
    assert not bad, bad


def test_v4_font_sizes_use_tokens():
    bad = []
    for f in _css_files():
        if f == "tokens.css":
            continue
        for v in _sizes(_nocomment(_read(f))):
            if "var(--t" in v:
                continue
            if (f, v) in EXCEPTIONS:
                continue
            bad.append((f, v))
    assert not bad, bad


def test_js_font_sizes_use_tokens():
    bad = []
    for d in ("core", "screens"):
        for fn in os.listdir(os.path.join(V4, d)):
            if not fn.endswith(".js"):
                continue
            src = _read(f"{d}/{fn}")
            for m in re.finditer(r"(fontSize|font):\s*\"[^\"]*?(\d+(?:\.\d+)?)px", src):
                bad.append((fn, m.group(0)))
    assert not bad, bad
    assert 'fontSize: parseFloat(tok("--t-xs"))' in _read("core/lwc.js")


def test_tokens_define_three_text_sizes():
    tok = _nocomment(_read("tokens.css"))
    root = re.search(r":root \{(.*?)\n\}", tok, re.S).group(1)
    base = dict(re.findall(r"(--t-(?:2xs|xs|sm|md|lg|xl|2xl|led)):\s*([\d.]+)px", root))
    assert float(base["--t-2xs"]) == 12 and float(base["--t-xs"]) >= 13 and float(base["--t-sm"]) >= 14
    assert float(base["--t-xl"]) > 21          # key numbers bigger than v3's 21px
    assert re.search(r"--ts:\s*1;", root)
    assert re.search(r'html\[data-text="md"\]\s*\{[^}]*--ts:\s*1;', tok)
    for step, ts in (("lg", 1.12), ("xl", 1.25)):
        block = re.search(r'html\[data-text="%s"\]\s*\{(.*?)\}' % step, tok, re.S).group(1)
        vals = dict(re.findall(r"(--t-(?:2xs|xs|sm|md|lg|xl|2xl|led)):\s*([\d.]+)px", block))
        assert set(vals) == set(base), step
        assert float(re.search(r"--ts:\s*([\d.]+)", block).group(1)) == ts
        for k, v in vals.items():
            assert float(v) > float(base[k]), (step, k)
            assert abs(float(v) / float(base[k]) - ts) < 0.06, (step, k, v)


def test_text_size_control_is_in_the_header_and_per_device():
    js = _read("core/textsize.js")
    assert '"보통"' in js and '"크게"' in js and '"아주 크게"' in js
    assert '"aria-label": "글자 크기"' in js and "글자 크기" in js
    assert 'import {h, local} from "./dom.js"' in js and "localStorage" not in js
    assert "local.get(KEY" in js and "local.set(KEY" in js
    assert "root.dataset.text" in js
    dom = _read("core/dom.js")
    assert re.search(r"get\(k, d = null\)\s*\{\s*try \{ const v = localStorage.getItem", dom)
    assert re.search(r"set\(k, v\)\s*\{\s*try \{ localStorage.setItem", dom)
    shell = _read("core/shell.js")
    assert 'import {textSwitch} from "./textsize.js"' in shell and "textSwitch(() => remount())" in shell
    # next to the skin switch
    i, j = shell.index("textSwitch(() => remount())"), shell.index("skinSwitch(() => remount())")
    assert 0 < j - i < 120
    main = _read("core/main.js")
    assert "applyText();" in main and main.index("applyText();") < main.index("startShell(")


def _hex_lum(h):
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _ratio(a, b):
    x, y = _hex_lum(a), _hex_lum(b)
    return (max(x, y) + 0.05) / (min(x, y) + 0.05)


def _skins():
    tok = _nocomment(_read("tokens.css"))
    classic = dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6});", re.search(r":root \{(.*?)\n\}", tok, re.S).group(1)))
    ai_block = re.search(r':root:not\(\[data-skin="classic"\]\) \{(.*?)\n\}', tok, re.S).group(1)
    ai = {**classic, **dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6});", ai_block))}
    return {"classic": classic, "ai": ai}


def test_small_text_contrast_both_skins():
    worst = []
    for name, t in _skins().items():
        for fg in ("--muted", "--ink-2"):
            for bg in ("--bg", "--surface", "--surface-2", "--console"):
                r = _ratio(t[fg], t[bg])
                if r < 4.5:
                    worst.append((name, fg, bg, round(r, 2)))
    assert not worst, worst
