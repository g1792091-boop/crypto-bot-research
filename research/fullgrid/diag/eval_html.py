"""Browsable page of STRATEGY_EVAL_KO.md: every strategy as a collapsible card with grade filters and search.

    python research/fullgrid/diag/eval_html.py STRATEGY_EVAL_KO.md OUT.html

Needs the `markdown` package. The page carries no DeepSeek money figures because the source document has none.
"""

import html
import re
import sys

import markdown

GRADES = ("★★★", "★★", "★", "✕")
CSS = """
/* Layout: one reading column, filters pinned under the header, each strategy a collapsible card. */
:root {
  --bg: #f3f5f8; --surface: #ffffff; --fg: #17202c; --muted: #5d6878; --line: #dbe0e7;
  --accent: #1f5e8c; --pos: #1d7a4c; --neg: #b13a3a; --gold: #9a700f; --chip: #e8edf3;
  --display: "IBM Plex Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", system-ui, sans-serif;
  --body: "IBM Plex Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", system-ui, sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #0f141b; --surface: #161d27; --fg: #e5e9ef; --muted: #9aa4b2; --line: #2a3340;
  --accent: #7fb2dd; --pos: #5cc08b; --neg: #e57b7b; --gold: #e0b44a; --chip: #1f2833; color-scheme: dark; } }
:root[data-theme="dark"] {
  --bg: #0f141b; --surface: #161d27; --fg: #e5e9ef; --muted: #9aa4b2; --line: #2a3340;
  --accent: #7fb2dd; --pos: #5cc08b; --neg: #e57b7b; --gold: #e0b44a; --chip: #1f2833; color-scheme: dark; }
body { background: var(--bg); color: var(--fg); font-family: var(--body); font-size: 15px; line-height: 1.65; }
.wrap { max-width: 980px; margin: 0 auto; padding-inline: 16px; padding-block: 24px 64px; }
h1, h2, h3 { font-family: var(--display); text-wrap: balance; line-height: 1.3; }
h1 { font-size: 1.75rem; font-weight: 700; margin: 0 0 6px; }
h2 { font-size: 1.25rem; font-weight: 600; margin: 32px 0 10px; padding-top: 12px; border-top: 1px solid var(--line); }
h3 { font-size: 1.05rem; margin: 0; }
p, li { max-width: 72ch; }
a { color: var(--accent); }
code { font-family: var(--mono); font-size: .88em; background: var(--chip); padding: 1px 5px; border-radius: 4px; }
.lede { color: var(--muted); margin: 0 0 18px; }
.bar { position: sticky; top: env(safe-area-inset-top, 0px); z-index: 5; background: var(--bg);
  display: flex; flex-wrap: wrap; gap: 8px; align-items: center; padding-block: 10px; border-bottom: 1px solid var(--line); }
.bar input { flex: 1 1 200px; min-width: 0; font: inherit; padding: 7px 10px; border: 1px solid var(--line);
  border-radius: 8px; background: var(--surface); color: var(--fg); }
.chip { font: inherit; font-size: .88rem; padding: 6px 11px; border: 1px solid var(--line); border-radius: 999px;
  background: var(--surface); color: var(--fg); cursor: pointer; }
.chip[aria-pressed="true"] { background: var(--accent); border-color: var(--accent); color: var(--bg); }
.chip:focus-visible, .bar input:focus-visible, summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.count { color: var(--muted); font-size: .85rem; font-variant-numeric: tabular-nums; }
.tw { overflow-x: auto; margin: 10px 0 16px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); }
table { border-collapse: collapse; font-size: .86rem; width: 100%; }
th, td { padding: 6px 9px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; white-space: nowrap; }
th { color: var(--muted); font-weight: 600; background: var(--chip); }
td { font-variant-numeric: tabular-nums; }
tr:last-child td { border-bottom: 0; }
.pos { color: var(--pos); } .neg { color: var(--neg); }
details.strat { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; margin: 10px 0; }
details.strat > summary { list-style: none; cursor: pointer; padding: 12px 14px; display: flex; flex-wrap: wrap;
  gap: 6px 10px; align-items: baseline; }
details.strat > summary::-webkit-details-marker { display: none; }
details.strat[open] > summary { border-bottom: 1px solid var(--line); }
.body { padding: 4px 14px 14px; min-width: 0; }
.g { font-family: var(--mono); font-weight: 600; color: var(--gold); min-width: 3.2em; }
.g.g2 { color: var(--accent); } .g.g1, .g.gx { color: var(--muted); }
.code { font-family: var(--mono); font-size: .8rem; color: var(--muted); }
.lab { font-size: .8rem; padding: 1px 8px; border-radius: 999px; background: var(--chip); color: var(--muted); }
.tools { display: flex; gap: 8px; flex-wrap: wrap; margin: 8px 0 0; }
@media (prefers-reduced-motion: no-preference) { details.strat > summary { transition: background .15s; } }
details.strat > summary:hover { background: var(--chip); }
"""
JS = """
(function () {
  var cards = Array.prototype.slice.call(document.querySelectorAll('details.strat'));
  var chips = Array.prototype.slice.call(document.querySelectorAll('.chip[data-grade]'));
  var q = document.getElementById('q');
  var count = document.getElementById('count');
  var grade = 'all';
  function apply() {
    var term = (q.value || '').trim().toLowerCase();
    var shown = 0;
    cards.forEach(function (c) {
      var ok = (grade === 'all' || c.dataset.grade === grade) && (!term || c.dataset.name.indexOf(term) >= 0);
      c.hidden = !ok; if (ok) shown++;
    });
    count.textContent = shown + '개 보임';
  }
  chips.forEach(function (b) {
    b.addEventListener('click', function () {
      grade = b.dataset.grade;
      chips.forEach(function (x) { x.setAttribute('aria-pressed', String(x === b)); });
      apply();
    });
  });
  q.addEventListener('input', apply);
  document.getElementById('openall').addEventListener('click', function () {
    cards.forEach(function (c) { if (!c.hidden) c.open = true; });
  });
  document.getElementById('closeall').addEventListener('click', function () {
    cards.forEach(function (c) { c.open = false; });
  });
  function openHash() {
    var id = location.hash.slice(1);
    var el = id && document.getElementById(id);
    if (el && el.tagName === 'DETAILS') { el.hidden = false; el.open = true; el.scrollIntoView(); }
  }
  window.addEventListener('hashchange', openHash);
  apply(); openHash();
})();
"""


def color_numbers(h: str) -> str:
    def cell(m):
        inner = m.group(2)
        inner = re.sub(r"(?<![\w.])(\+\d[\d,.]*%)", r'<span class="pos">\1</span>', inner)
        inner = re.sub(r"(?<![\w.])([−-]\d[\d,.]*%)", r'<span class="neg">\1</span>', inner)
        return m.group(1) + inner + m.group(3)
    return re.sub(r"(<td>)(.*?)(</td>)", cell, h, flags=re.S)


def render(md_text: str) -> str:
    out = markdown.markdown(md_text, extensions=["tables"])
    out = out.replace("<table>", '<div class="tw"><table>').replace("</table>", "</table></div>")
    return color_numbers(out)


def main(src: str, dst: str) -> None:
    text = open(src, encoding="utf-8").read()
    head, _, rest = text.partition("\n## 규칙봇 36개: 매매법별 평가")
    rest = "## 규칙봇 36개: 매매법별 평가" + rest
    title_line, _, head_body = head.partition("\n")
    parts = re.split(r"^(## .+|### .+)$", rest, flags=re.M)
    body = []
    i = 1
    while i < len(parts):
        line, chunk = parts[i], parts[i + 1] if i + 1 < len(parts) else ""
        if line.startswith("## "):
            body.append(f"<h2>{html.escape(line[3:])}</h2>")
            body.append(render(chunk))
        else:
            m = re.match(r"### (\S+) (.+) \(([A-Za-z0-9_]+)\) — (.+)$", line)
            if not m:
                body.append(render(line + chunk))
            else:
                g, name, code, lab = m.groups()
                gcls = {"★★★": "g3", "★★": "g2", "★": "g1"}.get(g, "gx")
                key = html.escape(f"{name} {code}".lower())
                body.append(
                    f'<details class="strat" id="{code}" data-grade="{html.escape(g)}" data-name="{key}">'
                    f'<summary><span class="g {gcls}">{html.escape(g)}</span><h3>{html.escape(name)}</h3>'
                    f'<span class="code">{code}</span><span class="lab">{html.escape(lab)}</span></summary>'
                    f'<div class="body">{render(chunk)}</div></details>')
        i += 2
    chips = "".join(f'<button class="chip" data-grade="{g}" aria-pressed="false">{g}</button>' for g in GRADES)
    page = f"""<title>매매법 80개 평가</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans+KR:wght@400;600;700&display=swap">
<style>{CSS}</style>
<div class="wrap">
<h1>{html.escape(title_line.lstrip('# ').strip())}</h1>
<p class="lede">규칙봇 36개와 딥시크 44개, 15분·30분·1시간·4시간봉 315칸의 5년 백테스트를 매매법마다 정리했습니다. 딥시크는 두 분 결정(D11)대로 돈 숫자를 가렸습니다.</p>
{render(head_body)}
<div class="bar" role="search">
<input id="q" type="search" placeholder="매매법 이름이나 코드로 찾기" aria-label="매매법 찾기">
<button class="chip" data-grade="all" aria-pressed="true">전체</button>{chips}
<span class="count" id="count"></span>
</div>
<div class="tools"><button class="chip" id="openall" type="button">보이는 것 모두 펼치기</button><button class="chip" id="closeall" type="button">모두 접기</button></div>
{''.join(body)}
</div>
<script>{JS}</script>
"""
    open(dst, "w", encoding="utf-8").write(page)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
