"""Browsable page of LIVE6D_KO.md: the summary sections as a page, every strategy as a collapsible card with a group
filter (규칙봇 / 딥시크) and search. Same look as research/fullgrid/diag/eval_html.py.

    python research/live_interim/live6d_html.py LIVE6D_KO.md OUT.html

Needs the `markdown` package. The source keeps DeepSeek money figures out (D11), so the page has none.
"""

import html
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fullgrid", "diag"))
import eval_html as E  # noqa: E402

JS = """
(function () {
  var cards = Array.prototype.slice.call(document.querySelectorAll('details.strat'));
  var chips = Array.prototype.slice.call(document.querySelectorAll('.chip[data-group]'));
  var q = document.getElementById('q');
  var count = document.getElementById('count');
  var group = 'all';
  function apply() {
    var term = (q.value || '').trim().toLowerCase();
    var shown = 0;
    cards.forEach(function (c) {
      var ok = (group === 'all' || c.dataset.group === group) && (!term || c.dataset.name.indexOf(term) >= 0);
      c.hidden = !ok; if (ok) shown++;
    });
    count.textContent = shown + '개 보임';
  }
  chips.forEach(function (b) {
    b.addEventListener('click', function () {
      group = b.dataset.group;
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
EXTRA_CSS = """
.verdict { font-size: .82rem; color: var(--muted); }
.lede strong { color: var(--fg); }
"""


def main(src: str, dst: str) -> None:
    text = open(src, encoding="utf-8").read()
    title_line, _, rest = text.partition("\n")
    parts = re.split(r"^(## .+|### .+)$", rest, flags=re.M)
    body = [E.render(parts[0])]
    group = None
    i = 1
    while i < len(parts):
        line, chunk = parts[i], parts[i + 1] if i + 1 < len(parts) else ""
        if line.startswith("## "):
            group = "core" if "규칙봇 36개" in line and "매매법별" in line else ("ds" if "딥시크 44개" in line else None)
            body.append(f"<h2>{html.escape(line[3:])}</h2>")
            if group == "core":
                body.append('<div class="bar" role="search"><input id="q" type="search" placeholder="매매법 이름이나 코드로 찾기" '
                            'aria-label="매매법 찾기"><button class="chip" data-group="all" aria-pressed="true">전체</button>'
                            '<button class="chip" data-group="core" aria-pressed="false">규칙봇 36개</button>'
                            '<button class="chip" data-group="ds" aria-pressed="false">딥시크 44개</button>'
                            '<span class="count" id="count"></span></div>'
                            '<div class="tools"><button class="chip" id="openall" type="button">보이는 것 모두 펼치기</button>'
                            '<button class="chip" id="closeall" type="button">모두 접기</button></div>')
            body.append(E.render(chunk))
        else:
            m = re.match(r"### (\S*)\s*(.+) \(([A-Za-z0-9_]+)\) — (.+)$", line)
            if not m:
                body.append(E.render(line + chunk))
            else:
                g, name, code, verdict = m.groups()
                gcls = {"★★★": "g3", "★★": "g2", "★": "g1"}.get(g, "gx")
                key = html.escape(f"{name} {code}".lower())
                body.append(
                    f'<details class="strat" id="{code}" data-group="{group or "core"}" data-name="{key}">'
                    f'<summary><span class="g {gcls}">{html.escape(g)}</span><h3>{html.escape(name)}</h3>'
                    f'<span class="code">{code}</span><span class="lab">{html.escape(verdict)}</span></summary>'
                    f'<div class="body">{E.render(chunk)}</div></details>')
        i += 2
    page = f"""<title>규칙봇 첫 6일 분석</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans+KR:wght@400;600;700&display=swap">
<style>{E.CSS}{EXTRA_CSS}</style>
<div class="wrap">
<h1>{html.escape(title_line.lstrip('# ').strip())}</h1>
{''.join(body)}
</div>
<script>{JS}</script>
"""
    open(dst, "w", encoding="utf-8").write(page)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
