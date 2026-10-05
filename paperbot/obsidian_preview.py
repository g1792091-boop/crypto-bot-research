"""A static single-file HTML preview of a built vault (paperbot/obsidian_export.py preview): the home note, one strategy
note and the link graph, in the vault's Catppuccin palette, so the owners can see roughly what Obsidian will show without
installing it. Reads the Markdown files of the vault only; writes ``index.html`` into the output folder. No network is
needed except for the optional Mermaid script (diagrams show as plain text without it).
"""

from __future__ import annotations

import html
import os
import re
from typing import Optional

import numpy as np

from .obsidian_util import LATTE, MOCHA, TYPE_COLORS

FM = re.compile(r"\A---\n(.*?)\n---\n", re.S)
WIKI = re.compile(r"\[\[([^\]\n|#^\\]+)(?:#[^\]\n|\\]*)?(?:\\?\|([^\]\n]*))?\]\]")
ALLOWED = re.compile(r'<span class="pb-badge pb-\w+">[^<]*</span>|<progress value="\d+" max="\d+"></progress>'
                     r'|<div class="pb-stamp">[^<]*</div>')
FENCE = re.compile(r"^(```|~~~).*?^\1[^\n]*$", re.S | re.M)


def read_notes(vault: str) -> dict:
    notes = {}
    for root, dirs, files in os.walk(vault):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for f in sorted(files):
            if not f.endswith(".md"):
                continue
            p = os.path.join(root, f)
            rel = os.path.relpath(p, vault).replace(os.sep, "/")
            with open(p, "r", encoding="utf-8") as fh:
                text = fh.read()
            fm, body = {}, text
            m = FM.match(text)
            if m:
                body = text[m.end():]
                for ln in m.group(1).split("\n"):
                    k, _, v = ln.partition(":")
                    fm[k.strip()] = v.strip()
            notes[f[:-3]] = {"path": rel, "fm": fm, "body": body}
    return notes


def links_of(body: str) -> list[str]:
    plain = re.sub(r"`[^`\n]*`", "", FENCE.sub("", body))
    return [m.group(1).strip() for m in WIKI.finditer(plain)]


def note_type(fm: dict) -> str:
    m = re.search(r'tags:\s*\["([^"]+)"', fm.get("tags", "") if "tags" in fm else "")
    return m.group(1) if m else "허브"


# ------------------------------------------------------------------ mini markdown
def inline(t: str, known: set) -> str:
    keep: list = []

    def hold(m):
        keep.append(m.group(0))
        return f"\x00{len(keep) - 1}\x00"
    t = ALLOWED.sub(hold, t)
    t = html.escape(t, quote=False)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![\*\w])\*(?!\s)(.+?)(?<!\s)\*(?![\*\w])", r"<em>\1</em>", t)

    def wl(m):
        name = m.group(1).strip()
        label = m.group(2) or name
        cls = "wl" if name in known else "wl dead"
        return f'<a class="{cls}" title="{html.escape(name)}">{label}</a>'
    t = WIKI.sub(wl, t)
    return re.sub(r"\x00(\d+)\x00", lambda m: keep[int(m.group(1))], t)


def blocks(lines: list[str], known: set) -> str:
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue
        if ln.lstrip().startswith("```"):
            lang = ln.strip()[3:].strip()
            j = i + 1
            code = []
            while j < n and not lines[j].lstrip().startswith("```"):
                code.append(lines[j])
                j += 1
            body = html.escape("\n".join(code))
            out.append(f'<pre class="mermaid">{body}</pre>' if lang == "mermaid" else f"<pre><code>{body}</code></pre>")
            i = j + 1
            continue
        m = re.match(r"^(#{1,6}) (.*)$", ln)
        if m:
            lv = len(m.group(1))
            out.append(f"<h{lv}>{inline(m.group(2), known)}</h{lv}>")
            i += 1
            continue
        if ln.startswith(">"):
            j = i
            q = []
            while j < n and lines[j].startswith(">"):
                q.append(re.sub(r"^> ?", "", lines[j]))
                j += 1
            out.append(callout(q, known))
            i = j
            continue
        if ln.startswith("|") and i + 1 < n and re.match(r"^\|[\s:\-|]+\|$", lines[i + 1].strip()):
            hdr = [c.strip() for c in ln.strip().strip("|").split("|")]
            al = [("right" if c.strip().endswith(":") and not c.strip().startswith(":") else
                   "center" if c.strip().startswith(":") and c.strip().endswith(":") else "left")
                  for c in lines[i + 1].strip().strip("|").split("|")]
            j = i + 2
            rows = []
            while j < n and lines[j].startswith("|"):
                rows.append(re.split(r"(?<!\\)\|", lines[j].strip().strip("|")))
                j += 1
            th = "".join(f'<th style="text-align:{al[k] if k < len(al) else "left"}">{inline(c.strip(), known)}</th>'
                         for k, c in enumerate(hdr))
            tb = "".join("<tr>" + "".join(f'<td style="text-align:{al[k] if k < len(al) else "left"}">'
                                          f"{inline(c.strip(), known)}</td>" for k, c in enumerate(r)) + "</tr>" for r in rows)
            out.append(f"<div class=\"tw\"><table><thead><tr>{th}</tr></thead><tbody>{tb}</tbody></table></div>")
            i = j
            continue
        if re.match(r"^\s*([-*]|\d+\.) ", ln):
            j = i
            items = []
            ordered = bool(re.match(r"^\s*\d+\. ", ln))
            while j < n and re.match(r"^\s*([-*]|\d+\.) ", lines[j]):
                items.append(re.sub(r"^\s*([-*]|\d+\.) ", "", lines[j]))
                j += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(x, known)}</li>" for x in items) + f"</{tag}>")
            i = j
            continue
        if re.match(r"^-{3,}$", ln.strip()):
            out.append("<hr>")
            i += 1
            continue
        if re.fullmatch(r'<div class="pb-stamp">[^<]*</div>', ln.strip()):
            out.append(ln.strip())
            i += 1
            continue
        j = i
        para = []
        while j < n and lines[j].strip() and not re.match(r"^(#{1,6} |>|\||```|\s*([-*]|\d+\.) )", lines[j]):
            para.append(lines[j])
            j += 1
        if j == i:
            para = [ln]
            j = i + 1
        out.append("<p>" + "<br>".join(inline(x, known) for x in para) + "</p>")
        i = j
    return "\n".join(out)


def callout(q: list[str], known: set) -> str:
    m = re.match(r"^\[!([\w-]+)\]([+-]?)\s*(.*)$", q[0]) if q else None
    if not m:
        return f"<blockquote>{blocks(q, known)}</blockquote>"
    kind, fold, title = m.group(1), m.group(2), m.group(3)
    inner = blocks(q[1:], known)
    head = f'<div class="ct">{inline(title, known)}</div>'
    if fold:
        return (f'<details class="callout c-{kind}"{" open" if fold == "+" else ""}><summary>{inline(title, known)}</summary>'
                f"{inner}</details>")
    return f'<div class="callout c-{kind}">{head}{inner}</div>'


# ------------------------------------------------------------------ graph
def layout(names: list, edges: list, seed: int = 7, iters: int = 160) -> np.ndarray:
    n = len(names)
    rng = np.random.default_rng(seed)
    pos = rng.random((n, 2)) * 2 - 1
    if n < 2:
        return pos
    k = (4.0 / n) ** 0.5
    t = 0.2
    ei = np.array([a for a, b in edges] or [0])
    ej = np.array([b for a, b in edges] or [0])
    for _ in range(iters):
        delta = pos[:, None, :] - pos[None, :, :]
        dist = np.sqrt((delta ** 2).sum(-1)) + 1e-3
        disp = ((k * k / dist ** 2)[:, :, None] * delta).sum(1)
        if edges:
            d = pos[ei] - pos[ej]
            dl = np.sqrt((d ** 2).sum(-1)) + 1e-3
            f = (dl / k)[:, None] * d
            np.add.at(disp, ei, -f)
            np.add.at(disp, ej, f)
        disp -= pos * 0.6
        ln = np.sqrt((disp ** 2).sum(-1)) + 1e-9
        pos += disp / ln[:, None] * np.minimum(ln, t)[:, None]
        t *= 0.975
    pos -= pos.min(0)
    span = pos.max(0)
    span[span == 0] = 1
    return pos / span


def graph_svg(notes: dict) -> tuple[str, int, int]:
    names = sorted(notes)
    idx = {n: i for i, n in enumerate(names)}
    edges = set()
    for n, nt in notes.items():
        for t in links_of(nt["body"]):
            if t in idx and t != n:
                a, b = sorted((idx[n], idx[t]))
                edges.add((a, b))
    edges = sorted(edges)
    deg = np.zeros(len(names))
    for a, b in edges:
        deg[a] += 1
        deg[b] += 1
    pos = layout(names, edges)
    W, Hh, pad = 920, 640, 28
    px = pad + pos[:, 0] * (W - 2 * pad)
    py = pad + pos[:, 1] * (Hh - 2 * pad)
    parts = [f'<svg viewBox="0 0 {W} {Hh}" class="graph" role="img" aria-label="링크 그래프">']
    parts.append('<g class="edges">' + "".join(
        f'<line x1="{px[a]:.1f}" y1="{py[a]:.1f}" x2="{px[b]:.1f}" y2="{py[b]:.1f}"/>' for a, b in edges) + "</g>")
    order = np.argsort(deg)
    top = set(np.argsort(-deg)[:14].tolist())
    for i in order:
        t = note_type(notes[names[i]]["fm"])
        color = MOCHA[TYPE_COLORS.get(t, "overlay1")] if t in TYPE_COLORS else MOCHA["overlay1"]
        r = 2.6 + (deg[i] ** 0.5) * 1.5
        parts.append(f'<circle cx="{px[i]:.1f}" cy="{py[i]:.1f}" r="{r:.1f}" fill="{color}"><title>{html.escape(names[i])}</title></circle>')
        if i in top:
            parts.append(f'<text x="{px[i] + r + 3:.1f}" y="{py[i] + 4:.1f}">{html.escape(names[i][:16])}</text>')
    parts.append("</svg>")
    return "".join(parts), len(names), len(edges)


# ------------------------------------------------------------------ page
CSS = """
:root{%(dark)s --shadow:0 6px 22px rgba(0,0,0,.35)}
@media (prefers-color-scheme: light){:root{%(light)s --shadow:0 6px 18px rgba(76,79,105,.18)}}
*{box-sizing:border-box}
body{margin:0;background:var(--base);color:var(--text);font:16px/1.8 "Pretendard","Noto Sans KR","Malgun Gothic","Apple SD Gothic Neo",system-ui,sans-serif;word-break:keep-all}
header{position:sticky;top:0;z-index:5;background:var(--mantle);border-bottom:1px solid var(--surface0);padding:10px 16px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
header b{color:var(--mauve);margin-right:8px}
header button{background:var(--surface0);color:var(--text);border:1px solid var(--surface1);border-radius:999px;padding:6px 16px;font:inherit;cursor:pointer}
header button.on{background:var(--mauve);color:var(--crust);border-color:var(--mauve);font-weight:700}
main{max-width:860px;margin:0 auto;padding:18px 16px 80px}
section{display:none}section.on{display:block}
.banner{height:84px;border-radius:16px;margin:0 0 14px;box-shadow:var(--shadow);background:radial-gradient(circle at 12%% 120%%,rgba(255,255,255,.22),transparent 42%%),repeating-linear-gradient(135deg,rgba(255,255,255,.06) 0 2px,transparent 2px 14px),linear-gradient(120deg,var(--mauve),var(--blue) 60%%,var(--teal))}
.banner.strat{background:radial-gradient(circle at 12%% 120%%,rgba(255,255,255,.22),transparent 42%%),repeating-linear-gradient(135deg,rgba(255,255,255,.06) 0 2px,transparent 2px 14px),linear-gradient(120deg,var(--mauve),var(--pink))}
h1,h2,h3,h4{line-height:1.3}h2{color:var(--blue);margin-top:1.9em;padding-bottom:.25em;border-bottom:2px solid;border-image:linear-gradient(90deg,var(--blue),transparent 70%%) 1}
h3{color:var(--teal)}h4{color:var(--peach)}strong{color:var(--rosewater)}
a.wl{color:var(--blue);border-bottom:1px dotted var(--blue);cursor:default}a.dead{color:var(--red)}
code{background:var(--surface0);color:var(--peach);border-radius:6px;padding:0 .35em;font-family:"D2Coding","Cascadia Mono",Consolas,monospace;font-size:.9em}
pre{background:var(--mantle);border-radius:12px;padding:12px;overflow:auto}
.mermaid{text-align:center;background:rgba(128,128,150,.07);border-radius:12px;padding:.6em;overflow-x:auto;white-space:pre;font-size:.8em}
.stamp,.pb-stamp{font-size:.74em;color:var(--overlay1);border-bottom:1px dashed var(--surface1);padding-bottom:.4em;margin-bottom:1.1em}
.pb-badge{display:inline-block;font-size:.72em;font-weight:700;line-height:1.6;padding:0 .75em;border-radius:999px;vertical-align:middle;border:1px solid}
.pb-code{color:var(--green);border-color:var(--green)}.pb-ai{color:var(--peach);border-color:var(--peach)}.pb-doc{color:var(--blue);border-color:var(--blue)}.pb-mixed{color:var(--mauve);border-color:var(--mauve)}.pb-small{color:var(--yellow);border-color:var(--yellow)}.pb-none{color:var(--overlay1);border-color:var(--overlay1)}
.callout{border-radius:14px;border:1px solid color-mix(in srgb,var(--cc) 40%%,transparent);background:color-mix(in srgb,var(--cc) 10%%,transparent);padding:12px 16px;margin:12px 0;--cc:var(--lavender)}
.callout .ct,.callout summary{font-weight:700;margin-bottom:4px;cursor:default}
.c-info{--cc:var(--blue)}.c-abstract{--cc:var(--teal)}.c-tip,.c-success{--cc:var(--green)}.c-warning,.c-question{--cc:var(--peach)}.c-danger{--cc:var(--red)}.c-quote{--cc:var(--overlay1)}
.c-pb-hero{--cc:var(--mauve);background:linear-gradient(135deg,color-mix(in srgb,var(--mauve) 22%%,transparent),color-mix(in srgb,var(--blue) 12%%,transparent));padding:18px 22px;border-radius:18px;box-shadow:var(--shadow)}
.c-pb-hero .ct{font-size:1.55em;font-weight:850}.c-pb-hero p{color:var(--subtext0);margin:.2em 0 0}
.c-pb-stat{--cc:var(--blue)}.c-pb-ai{--cc:var(--peach)}.c-pb-code{--cc:var(--green)}.c-pb-soft{--cc:var(--overlay1)}
.c-pb-stat table{border:0;margin:.2em 0}.c-pb-stat thead th{background:transparent;color:var(--subtext0);font-size:.82em;font-weight:600;border:0}
.c-pb-stat td{font-size:1.3em;font-weight:800;border:0!important;background:transparent!important}
.tw{overflow-x:auto;margin:1em 0}
table{border-collapse:separate;border-spacing:0;width:100%%;border:1px solid var(--surface1);border-radius:12px;overflow:hidden;font-size:.9em}
thead th{background:color-mix(in srgb,var(--mauve) 16%%,transparent);font-weight:700;white-space:nowrap}
th,td{padding:7px 12px;border-bottom:1px solid color-mix(in srgb,var(--overlay1) 22%%,transparent)}
tbody tr:nth-child(even) td{background:color-mix(in srgb,var(--overlay1) 7%%,transparent)}tbody tr:last-child td{border-bottom:0}td:first-child{font-weight:600}
progress{width:100%%;height:12px;accent-color:var(--mauve)}
ul>li::marker{color:var(--mauve)}
.graph{width:100%%;height:auto;background:var(--mantle);border-radius:16px;box-shadow:var(--shadow)}
.graph .edges line{stroke:var(--surface1);stroke-width:.7;opacity:.7}.graph text{fill:var(--subtext1);font-size:11px}
.legend{display:flex;flex-wrap:wrap;gap:6px 14px;margin:12px 0;font-size:.85em;color:var(--subtext0)}.legend i{display:inline-block;width:10px;height:10px;border-radius:50%%;margin-right:5px}
.note{color:var(--subtext0);font-size:.85em}
@media (max-width:600px){main{padding:12px}.banner{height:56px}table{font-size:.8em}}
"""


def css() -> str:
    dark = "".join(f"--{k}:{v};" for k, v in MOCHA.items())
    light = "".join(f"--{k}:{v};" for k, v in LATTE.items())
    return CSS % {"dark": dark, "light": light}


def pick_strategy(notes: dict) -> Optional[str]:
    best, bn = None, -1
    for name, nt in notes.items():
        if nt["fm"].get("type") == '"전략"' and nt["fm"].get("strategy"):
            try:
                n = int(float(nt["fm"].get("n_trades", "0")))
            except ValueError:
                n = 0
            if n > bn or (n == bn and best is not None and name < best):
                best, bn = name, n
    return best


def render_preview(vault: str, out_dir: str) -> str:
    notes = read_notes(vault)
    known = set(notes)
    home = notes.get("홈")
    strat = pick_strategy(notes)
    svg, n_nodes, n_edges = graph_svg(notes) if notes else ("", 0, 0)

    def page(name: str, banner: str = "") -> str:
        nt = notes.get(name)
        if not nt:
            return f"<p class='note'>{html.escape(name)} 노트가 아직 없습니다.</p>"
        return f'<div class="banner {banner}"></div><h1>{html.escape(name)}</h1>' + blocks(nt["body"].split("\n"), known)
    legend = "".join(f'<span><i style="background:{MOCHA[c]}"></i>{t}</span>' for t, c in TYPE_COLORS.items())
    doc = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Paper v3 볼트 미리보기</title><style>{css()}</style></head><body>
<header><b>Paper v3 볼트 미리보기</b><button class="on" data-t="home">홈</button><button data-t="strat">매매법 카드 예시</button><button data-t="graph">그래프</button></header>
<main>
<p class="note">옵시디언 없이 보는 정적 미리보기입니다 (같은 색·같은 노트 내용). 실제 옵시디언에서는 링크를 눌러 이동하고 그래프를 돌려 볼 수 있습니다.</p>
<section id="home" class="on">{page("홈")}</section>
<section id="strat">{page(strat, "strat") if strat else "<p class='note'>매매법 노트가 없습니다.</p>"}</section>
<section id="graph"><h1>그래프 (노트 {n_nodes}개, 링크 {n_edges}개)</h1><div class="legend">{legend}</div>{svg}
<p class="note">점 하나가 노트 하나입니다. 색은 종류, 큰 점은 연결이 많은 목록 노트입니다. 옵시디언의 그래프 뷰도 같은 색 규칙으로 시작합니다.</p></section>
</main>
<script>
document.querySelectorAll("header button").forEach(b=>b.onclick=()=>{{document.querySelectorAll("header button").forEach(x=>x.classList.toggle("on",x===b));
document.querySelectorAll("section").forEach(s=>s.classList.toggle("on",s.id===b.dataset.t));window.scrollTo(0,0);}});
</script>
<script type="module">
try {{ const m = await import("https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs");
  m.default.initialize({{startOnLoad:false,theme:matchMedia("(prefers-color-scheme: light)").matches?"default":"dark"}});
  for (const s of document.querySelectorAll("section")) {{ const was=s.classList.contains("on"); s.classList.add("on");
    try {{ await m.default.run({{nodes:s.querySelectorAll(".mermaid")}}); }} catch(e) {{}} if(!was) s.classList.remove("on"); }}
}} catch (e) {{ /* offline: the diagrams stay as text */ }}
</script></body></html>
"""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "index.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return path
