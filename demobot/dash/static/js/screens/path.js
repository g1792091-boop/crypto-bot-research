// #/path 졸업 길 (CONTRACT 9.8): every line (account × leverage) on its way to 실전 후보: "우리 기준" checks k/5 →
// 우리 기준 통과 → 확인 기간 (progress) → 실전 후보, closest first; and the luck map: a scatter of every line (x = closed
// trades n, y = mean R) over the coin-flip 95% limit (judge rows' luck_lim against n, drawn as a smooth fit
// a + b / √n), coloured AND shaped by stage; a tap shows the line. judge.json every 60 s. SVG built with s() (no markup).
import {h, s, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {isMissing} from "../api.js";
import {LEVS} from "../labels.js";
import {stageOf, closeness, ticks, robustLine} from "../g4.js";

const SHAPE = ["circle", "tri", "square", "diamond"];        // stage 0..3 (a failed confirmation: a cross)
const PTS_KO = ["기준 확인 중 (점 크기 = 넘은 개수)", "우리 기준 통과", "확인 기간", "실전 후보"];

export async function mount(el, ctx) {
  ctx.setTitle("졸업 길");
  const sum = h("div");
  const mapBox = h("div", {class: "g4-luck"});
  const info = h("div", {class: "g4-pick", "aria-live": "polite"}, h("span", {class: "muted"}, "점을 누르면 그 줄이 여기 나옵니다."));
  const legend = h("div");
  let lev = "all";
  const levSeg = ui.seg([{id: "all", label: "전체"}, ...LEVS.map((L) => ({id: String(L), label: `${L}배`}))], lev,
    (v) => { lev = v; paint(); }, {label: "배수"});
  const pager = ui.pager({size: 15, empty: "줄이 없습니다", render: (part, s0) => pathList(part, s0, ctx)});
  el.append(ui.screenHead("졸업 길", "줄마다 실전 후보까지 어디쯤인지"),
    sum,
    ui.card({plate: "운 지도", sub: "가로 = 닫힌 거래 수 · 세로 = 평균 R (수수료 후)", acts: levSeg}, mapBox, legend, info,
      ui.disclosure("이 지도 읽는 법", h("ul", {class: "dl-ul"},
        h("li", null, "점 하나 = 계좌 하나의 배수 한 줄입니다. 오른쪽일수록 거래가 많고, 위일수록 거래마다 많이 벌었습니다 (R = 손절 폭을 1로 본 손익)."),
        h("li", null, "흐린 띠 = 운으로도 나올 수 있는 높이입니다. 동전 던지기 계좌(아무 봉에서 아무 방향)를 같은 거래 수만큼 했을 때, 100번 중 95번은 이 선 아래에 머뭅니다."),
        h("li", null, "거래가 적으면 운만으로도 높게 나올 수 있어서 선이 높고, 거래가 많아질수록 선이 내려옵니다. 선 위에 있는 점이라야 운이 아닐 가능성이 큽니다 (우리 기준의 '운 기준선' 항목)."),
        h("li", null, "선은 판정 파일의 줄마다 운 한계(luck_lim)를 a + b ÷ √거래 수 모양으로 맞춘 것입니다. 배수·봉마다 조금씩 달라서 한 줄로 고르게 그렸습니다."),
        h("li", null, "모양과 색이 단계를 말합니다: ● 기준 확인 중 · ▲ 우리 기준 통과 · ■ 확인 기간 · ◆ 실전 후보 · ✕ 확인 실패.")))),
    ui.card({plate: "줄마다 단계", sub: "가까운 줄부터"}, pager.el,
      h("p", {class: "note"}, "앞 절반 → 뒤 절반: 닫힌 거래를 시간 순서로 반씩 나눈 평균 R (뒤가 크게 나빠졌으면 처음의 운이 다했을 수 있음). "
        + "⚠ = 버티는 수익 경고: 수익이 거래 몇 건 · 한두 코인에만 기대거나, 연속 손실이 깁니다. 자세한 것은 실전 준비 화면과 용어집에.")),
    ui.note("실전 후보가 나와도 실제 돈은 두 분이 정합니다. 단계: 우리 기준 5개를 모두 넘으면 '통과', 그때부터 4주(거래 20건 이상) 확인 기간, 그것까지 넘으면 '실전 후보'."));

  let data = null, seen = null, ro = null, lastW = 0;
  async function load() {
    let j;
    try { j = await ctx.api("/api/judge"); } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!data) put(mapBox, ui.errorBox(e, load));
      return;
    }
    const key = j && j.generated_ms;
    if (key === seen && data) return;
    seen = key;
    data = j;
    paint();
  }

  function lines() {
    const conf = new Map(((data && data.confirm) || []).map((c) => [`${c.id}|${c.L}`, c]));
    return ((data && data.rows) || []).map((r) => ({r, sg: stageOf(r, conf.get(`${r.id}|${r.L}`))}));
  }

  function paint() {
    if (!data || isMissing(data)) { put(sum); put(mapBox, ui.missing("판정 자료")); put(legend); pager.set([]); return; }
    const all = lines();
    const by = [0, 1, 2, 3].map((k) => all.filter((x) => x.sg.stage === k).length);
    const four = all.filter((x) => x.sg.stage === 0 && x.sg.ok === x.sg.of - 1).length;
    put(sum, h("div", {class: "stats dl-s4"},
      ui.stat("실전 후보", fmt.int(by[3]), "확인 기간까지 넘은 줄", by[3] ? "dl-good" : null),
      ui.stat("확인 기간", fmt.int(by[2]), "4주 다시 보는 줄"),
      ui.stat("우리 기준 통과", fmt.int(by[1]), "확인 기간 시작 전"),
      ui.stat("하나만 더", fmt.int(four), "5개 중 4개 넘은 줄")));
    const sorted = [...all].sort((a, b) => closeness(b.r, b.sg) - closeness(a.r, a.sg));
    pager.set(sorted, true);
    drawMap(all.filter((x) => lev === "all" || String(x.r.L) === lev));
  }

  function drawMap(items) {
    const W = Math.max(300, Math.floor(mapBox.clientWidth || el.clientWidth || 600));
    lastW = W;
    const H = W < 560 ? 280 : 360;
    const pad = {l: W < 560 ? 44 : 54, r: 12, t: 12, b: 38};
    const pts = items.filter((x) => x.r.n > 0 && x.r.mean_R != null && Number.isFinite(Number(x.r.mean_R)));
    if (!pts.length) { put(mapBox, ui.none("아직 닫힌 거래가 있는 줄이 없습니다")); put(legend); return; }
    // the luck limit's smooth fit: luck_lim ≈ a + b / √n (least squares over the rows that carry it)
    const lim = items.filter((x) => x.r.n >= 2 && x.r.luck_lim != null && Number.isFinite(Number(x.r.luck_lim)));
    let fit = null;
    if (lim.length >= 3) {
      const X = lim.map((x) => 1 / Math.sqrt(x.r.n)), Y = lim.map((x) => Number(x.r.luck_lim));
      const mx = X.reduce((a, b) => a + b, 0) / X.length, my = Y.reduce((a, b) => a + b, 0) / Y.length;
      const sxx = X.reduce((a, x) => a + (x - mx) ** 2, 0), sxy = X.reduce((a, x, i) => a + (x - mx) * (Y[i] - my), 0);
      const b = sxx > 0 ? sxy / sxx : 0;
      fit = {a: my - b * mx, b};
    }
    const nMax = Math.max(...pts.map((x) => x.r.n)) * 1.05;
    const nMin = 0;
    const ys = pts.map((x) => Number(x.r.mean_R));
    let yLo = Math.min(...ys, 0), yHi = Math.max(...ys, 0);
    const curve = (n) => (fit ? fit.a + fit.b / Math.sqrt(Math.max(n, 1)) : null);
    const n0 = Math.max(10, Math.min(...pts.map((x) => x.r.n)) * 0.8);
    if (fit) { yHi = Math.max(yHi, Math.min(curve(n0), yHi + 0.5)); yLo = Math.min(yLo, curve(nMax)); }
    const span = yHi - yLo || 1;
    yLo -= span * 0.06; yHi += span * 0.06;
    const X = (n) => pad.l + (n - nMin) / (nMax - nMin) * (W - pad.l - pad.r);
    const Y = (v) => pad.t + (yHi - v) / (yHi - yLo) * (H - pad.t - pad.b);
    const kids = [];
    // grid and axes
    for (const t of ticks(yLo, yHi, 5)) {
      kids.push(s("line", {x1: pad.l, x2: W - pad.r, y1: Y(t), y2: Y(t), class: t === 0 ? "g4-zero" : "g4-gridl"}),
        s("text", {x: pad.l - 6, y: Y(t) + 4, class: "g4-tick", "text-anchor": "end"}, fmt.num(t, Math.abs(t) < 1 && t !== 0 ? 2 : 1, true)));
    }
    for (const t of ticks(nMin, nMax, W < 560 ? 4 : 7)) {
      kids.push(s("line", {x1: X(t), x2: X(t), y1: pad.t, y2: H - pad.b, class: "g4-gridl"}),
        s("text", {x: X(t), y: H - pad.b + 16, class: "g4-tick", "text-anchor": "middle"}, fmt.int(t)));
    }
    kids.push(s("text", {x: W - pad.r, y: H - 6, class: "g4-axl", "text-anchor": "end"}, "닫힌 거래 수 →"),
      s("text", {x: pad.l + 4, y: pad.t + 12, class: "g4-axl"}, "↑ 평균 R"));
    // the luck band: from the bottom up to the 95% curve
    if (fit) {
      const xs = [];
      for (let i = 0; i <= 80; i++) xs.push(n0 + (nMax - n0) * i / 80);
      const pts2 = xs.map((n) => [X(n), Y(Math.max(yLo, Math.min(yHi, curve(n))))]);
      const line = pts2.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
      kids.push(s("path", {d: `${line} L${X(nMax).toFixed(1)} ${Y(yLo).toFixed(1)} L${X(n0).toFixed(1)} ${Y(yLo).toFixed(1)} Z`, class: "g4-band"}),
        s("path", {d: line, class: "g4-bandl"}),
        W >= 560 ? s("text", {x: X(nMax) - 4, y: Y(curve(nMax)) - 6, class: "g4-bandt", "text-anchor": "end"}, "운으로도 나오는 높이 (95%)") : null);
    }
    // the points: stage colour AND shape
    const order = [...pts].sort((a, b) => a.sg.stage - b.sg.stage);
    for (const x of order) {
      const cx = X(x.r.n), cy = Y(Number(x.r.mean_R));
      const st = x.sg.failed && x.sg.stage < 2 ? "failed" : `st${x.sg.stage}`;
      const r = x.sg.stage === 0 ? 2.2 + x.sg.ok * 0.6 : 5.2;
      const title = `${x.r.name || x.r.id} ${x.r.L}배 · 거래 ${x.r.n}건 · 평균 ${fmt.r(x.r.mean_R)} · 운 한계 ${fmt.r(x.r.luck_lim)} · ${stageText(x.sg)}`;
      const shape = x.sg.failed && x.sg.stage < 2 ? cross(cx, cy, 4.6) : mark(SHAPE[x.sg.stage], cx, cy, r);
      const g = s("g", {class: ["g4-pt", st], tabindex: x.sg.stage >= 1 ? "0" : null, role: x.sg.stage >= 1 ? "button" : null,
        "aria-label": x.sg.stage >= 1 ? title : null}, s("title", null, title), shape,
      s("circle", {cx, cy, r: 11, class: "g4-hit"}));
      const pick = () => showPick(x);
      g.addEventListener("click", pick);
      g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
      kids.push(g);
    }
    put(mapBox, s("svg", {class: "g4-svg", viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img",
      "aria-label": `운 지도: 줄 ${pts.length}개의 거래 수와 평균 R, 동전 던지기 95% 한계선`}, kids));
    put(legend, h("div", {class: "hm-legend"},
      PTS_KO.map((t, i) => h("span", {class: "dl-lg"}, s("svg", {width: 14, height: 14, viewBox: "0 0 14 14", class: ["g4-pt", `st${i}`], "aria-hidden": "true"}, mark(SHAPE[i], 7, 7, 5)), t)),
      h("span", {class: "dl-lg"}, s("svg", {width: 14, height: 14, viewBox: "0 0 14 14", class: "g4-pt failed", "aria-hidden": "true"}, cross(7, 7, 4.6)), "확인 실패"),
      fit ? h("span", {class: "dl-lg"}, h("i", {class: "g4-sw band"}), "운으로도 나오는 높이") : h("span", {class: "muted"}, "운 한계 자료 준비 중")));
    if (!ro && typeof ResizeObserver === "function") {
      ro = new ResizeObserver(() => { const w = Math.floor(mapBox.clientWidth); if (w && Math.abs(w - lastW) > 8) paint(); });
      ro.observe(mapBox);
    }
  }

  function showPick(x) {
    put(info, h("div", {class: "dl-evt"}, h("a", {href: ctx.href("account", x.r.id)}, `${x.r.name || x.r.id} ${fmt.lev(x.r.L)}`),
      ui.pill(stageText(x.sg), x.sg.stage === 3 ? "good" : x.sg.stage >= 1 ? "accent" : "thin")),
    h("p", {class: "dl-rmeta"}, `닫힌 거래 ${fmt.int(x.r.n)}건 · 평균 ${fmt.r(x.r.mean_R)} · 운 한계 ${fmt.r(x.r.luck_lim)}`,
      x.r.boot_low != null ? ` · 부트스트랩 하한 ${fmt.r(x.r.boot_low)}` : "",
      x.r.mean_R != null && x.r.luck_lim != null ? (Number(x.r.mean_R) > Number(x.r.luck_lim) ? " · 운 한계 위" : " · 운 한계 아래") : ""));
  }

  await load();
  ctx.every(60000, load);
  return () => { if (ro) ro.disconnect(); };
}

function stageText(sg) {
  if (sg.stage === 3) return "실전 후보";
  if (sg.stage === 2) return `확인 기간 ${fmt.num(sg.progress * 100, 0)}%`;
  if (sg.stage === 1) return "우리 기준 통과";
  return `기준 ${sg.ok}/${sg.of}${sg.failed ? " · 확인 실패 뒤" : ""}`;
}

function mark(kind, cx, cy, r) {
  if (kind === "square") return s("rect", {x: cx - r * 0.85, y: cy - r * 0.85, width: r * 1.7, height: r * 1.7, class: "g4-m"});
  if (kind === "tri") return s("path", {d: `M${cx} ${cy - r} L${cx + r * 0.95} ${cy + r * 0.75} L${cx - r * 0.95} ${cy + r * 0.75} Z`, class: "g4-m"});
  if (kind === "diamond") return s("path", {d: `M${cx} ${cy - r * 1.15} L${cx + r * 1.15} ${cy} L${cx} ${cy + r * 1.15} L${cx - r * 1.15} ${cy} Z`, class: "g4-m"});
  return s("circle", {cx, cy, r, class: "g4-m"});
}
const cross = (cx, cy, r) => s("path", {d: `M${cx - r} ${cy - r} L${cx + r} ${cy + r} M${cx + r} ${cy - r} L${cx - r} ${cy + r}`, class: "g4-x"});

function pathList(rows, s0, ctx) {
  return h("ol", {class: "g4-path", start: String(s0 + 1)}, rows.map(({r, sg}) => {
    const fails = ((r.ours && r.ours.checks) || []).filter((c) => !c.ok);
    const steps = [
      {ko: `기준 ${sg.ok}/${sg.of}`, st: sg.stage >= 1 ? "done" : "now", frac: sg.stage >= 1 ? 1 : sg.ok / sg.of},
      {ko: "기준 통과", st: sg.stage >= 1 ? "done" : "todo"},
      {ko: sg.stage === 2 ? `확인 ${fmt.num(sg.progress * 100, 0)}%` : "확인 기간", st: sg.stage > 2 ? "done" : sg.stage === 2 ? "now" : "todo",
        frac: sg.stage === 2 ? sg.progress : null},
      {ko: "실전 후보", st: sg.stage === 3 ? "done" : "todo"},
    ];
    const c = sg.conf;
    return h("li", {class: ["g4-pl", `s${sg.stage}`]},
      h("div", {class: "g4-plh"}, h("a", {href: ctx.href("account", r.id), class: "dl-aname"}, r.name || r.id),
        h("span", {class: "dl-levtag", dataset: {lev: r.L}}, `${r.L}배`),
        sg.failed ? ui.pill("확인 실패 뒤 다시 보는 중", "bad") : null,
        h("span", {class: "grow"}),
        h("span", {class: "muted num"}, `거래 ${fmt.int(r.n)} · ${fmt.r(r.mean_R)}`)),
      h("div", {class: "g4-track", role: "list", "aria-label": "단계"}, steps.map((x) => h("span", {class: ["g4-st", x.st], role: "listitem"},
        x.frac != null && x.st === "now" ? h("i", {style: {"--p": `${(x.frac * 100).toFixed(0)}%`}}) : null, h("span", null, x.ko)))),
      sg.stage === 2 && c ? h("p", {class: "dl-rmeta"}, `확인 기간 ${fmt.mmdd(c.start_ms)}부터 · 거래 ${fmt.int(c.n)}/${fmt.int(c.need_n)} · 평균 ${fmt.r(c.mean_R)} · 손익 ${fmt.pct(c.pnl_pct, true)}`,
        c.min_end_ms ? ` · 빨라도 ${fmt.mmdd(c.min_end_ms)} 끝` : "") : null,
      sg.stage === 0 && fails.length ? h("p", {class: "dl-rmeta"}, h("span", {class: "down"}, "✗ "), fails.map((f) => `${f.name_ko} (${f.value_ko})`).join(" · ")) : null,
      robustLine(r.robust));
  }));
}
