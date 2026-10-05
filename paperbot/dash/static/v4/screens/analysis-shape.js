// 분석, wave 3 (visual pass): two pictures from GET /api/v4/tradeshape (dash/more/tradeshape.py), one request for both.
//   heatCard  (코인·시간대): the 기존 36's trades by entry weekday x hour (Korea time), 7 x 24 cells; faded under 10 trades;
//             modes 평균 결과 / 이긴 비율 / 거래 수 / 동전 봇 (counts and win share only). 168 cells: description only.
//   outcomeCard (손익비·위험): each trade's result against the balance before it, in bins fixed in advance: the 36 as
//             bars, the same timeframes' coin flips as an outline (shares, 참고).
// Tapping a cell writes its numbers under the grid (phones have no hover). Money: assume(); comparisons: refNote.
import {h, put, ui, fmt, motion} from "../core/pb.js";
import {dimSeg} from "./analysis-kit.js";

const API = "/api/v4/tradeshape";
const FRESH_MS = 5 * 60 * 1000;
const WD = ["월", "화", "수", "목", "금", "토", "일"];
const FULL_R = 0.02;            // a cell's mean result of 2 % per trade or more gets the full tint
let cache = null;               // {at, p}: one request serves both cards (and a quick revisit)

function ensureCss() {
  if (document.querySelector("link[data-an-shape]")) return;
  document.head.append(h("link", {rel: "stylesheet", href: "/static/v4/screens/analysis-shape.css", dataset: {anShape: "1"}}));
}
function load(env) {
  if (!cache || Date.now() - cache.at > FRESH_MS) {
    const p = env.ctx.api(API);
    cache = {at: Date.now(), p};
    p.catch(() => { if (cache && cache.p === p) cache = null; });
  }
  return cache.p;
}
/** A card that fills itself when the answer comes (a shimmer until then; a short line when the route is missing). */
function lazyCard(env, opts, fill) {
  ensureCss();
  const body = h("div", {class: "ash-body"}, motion.shimmer(4, true));
  const card = ui.card(opts, body);
  load(env).then((d) => {
    if (!env.ctx.alive()) return;
    if (!d || !d.ready) { put(body, ui.empty((d && d.why) || "아직 끝난 거래가 없습니다.")); return; }
    put(body, ...fill(d));
  }).catch((e) => {
    put(body, h("p", {class: "muted"}, e && e.status === 404 ? "준비 중입니다 (서버 업데이트 뒤에 보입니다)." : "불러오지 못했습니다. 잠시 뒤 다시 봅니다."));
  });
  return card;
}

// ---------------------------------------------------------------- 요일 x 시간 열지도
const MODES = [{id: "r", label: "거래당 결과"}, {id: "w", label: "이긴 비율"}, {id: "n", label: "거래 수"}, {id: "flip", label: "동전 봇 (참고)"}];
export function heatCard(env) {
  return lazyCard(env, {plate: "요일 × 시간", cls: "ash-heat", sub: "진입한 때 (한국 시간)"}, (d) => {
    const small = d.small_n || 10;
    const detail = h("p", {class: "ash-detail"}, "칸을 누르면 그 시간의 숫자가 여기에 나옵니다.");
    const grid = h("div", {class: "ash-grid", role: "grid", "aria-label": "요일과 시간별 거래"});
    let sel = null;
    const seg = dimSeg("ash-heat", MODES, "r", () => paint(true), false);
    function cellOf(mode, wd, hr) {
      const c = mode === "flip" ? d.heat.flip[wd][hr] : d.heat.core[wd][hr];
      if (!c || !c.n) return {cls: "none", a: 0, c: null};
      let tone = "acc", a;
      if (mode === "r") { tone = c.r >= 0 ? "up" : "down"; a = Math.min(1, Math.abs(c.r) / FULL_R); }
      else if (mode === "w" || mode === "flip") { const w = c.w / c.n; tone = w >= .5 ? "up" : "down"; a = Math.min(1, Math.abs(w - .5) / .3); }
      else a = 0;
      return {cls: tone + (c.n < small ? " few" : ""), a, c};
    }
    function say(mode, wd, hr) {
      const c = mode === "flip" ? d.heat.flip[wd][hr] : d.heat.core[wd][hr];
      const when = `${WD[wd]}요일 ${String(hr).padStart(2, "0")}시`;
      if (!c || !c.n) return `${when} · 거래 없음`;
      const base = `${when} · ${mode === "flip" ? "동전 봇 " : "기존 36 "}거래 ${fmt.int(c.n)}건 · 이긴 비율 ${fmt.pct(c.w / c.n, 0, false)}`;
      const more = mode === "flip" ? "" : ` · 거래당 ${fmt.pct(c.r, 2)} · 손익 ${fmt.money(c.pnl, true)}`;
      return base + more + (c.n < small ? ` · 표본 적음 (${fmt.int(small)}건 미만)` : "");
    }
    function paint(anim) {
      const mode = seg.get();
      const maxN = Math.max(1, ...d.heat[mode === "flip" ? "flip" : "core"].flat().map((c) => (c ? c.n : 0)));
      const rows = [h("div", {class: "ash-row ash-hrs", role: "row", "aria-hidden": "true"}, h("span", {class: "ash-k"}),
        Array.from({length: 24}, (_, hr) => h("span", {class: "ash-hr"}, hr % 6 === 0 ? String(hr) : "")))];
      for (let wd = 0; wd < 7; wd++) {
        rows.push(h("div", {class: "ash-row", role: "row"}, h("span", {class: "ash-k", role: "rowheader"}, WD[wd]),
          Array.from({length: 24}, (_, hr) => {
            const x = cellOf(mode, wd, hr);
            const a = mode === "n" ? (x.c ? Math.max(.12, x.c.n / maxN) : 0) : x.a;
            const label = say(mode, wd, hr);
            return h("button", {type: "button", class: `ash-c ${mode === "n" && x.c ? "acc" + (x.c.n < small ? " few" : "") : x.cls}${sel && sel[0] === wd && sel[1] === hr ? " sel" : ""}`,
              role: "gridcell", style: {"--a": a.toFixed(3)}, title: label, "aria-label": label,
              onclick: (e) => { sel = [wd, hr]; detail.textContent = label; for (const b of grid.querySelectorAll(".ash-c.sel")) b.classList.remove("sel"); e.currentTarget.classList.add("sel"); }});
          })));
      }
      put(grid, ...rows);
      if (sel) detail.textContent = say(mode, sel[0], sel[1]);
      if (anim) motion.swap(grid);
    }
    paint(false);
    const tot = d.trades || {};
    return [seg.el, h("div", {class: "ash-scroll"}, grid), detail,
      h("p", {class: "an-note"}, `기존 36 끝난 거래 ${fmt.int(tot.core || 0)}건 · 같은 봉 동전 봇 ${fmt.int(tot.flip || 0)}건 (동전 봇은 거래 수와 이긴 비율만). `,
        `흐린 칸 = ${fmt.int(small)}건 미만. 168칸을 하나하나 시험하지 않았습니다: 눈에 띄는 칸도 우연일 수 있는 설명용 그림입니다.`),
      ui.refNote(env.verdictTs), ui.assume()];
  });
}

// ---------------------------------------------------------------- 거래 결과 분포
const EDGE_KO = ["−20", "−10", "−5", "−2", "0", "+2", "+5", "+10", "+20"];
export function outcomeCard(env) {
  return lazyCard(env, {plate: "거래 결과 분포", cls: "ash-dist", sub: "거래 한 번이 계좌 잔고를 몇 % 바꿨나"}, (d) => {
    const x = d.dist || {}, cs = x.core_share || [], fs = x.flip_share || [], bins = x.bins || [];
    const top = Math.max(0.0001, ...cs, ...fs);
    const tot = d.trades || {}, wins = d.wins || {}, liq = d.liq || {};
    const detail = h("p", {class: "ash-detail"}, "막대를 누르면 그 구간의 숫자가 나옵니다.");
    const say = (i) => `${bins[i]} · 기존 36 ${fmt.pct(cs[i] || 0, 1, false)} (${fmt.int((x.core || [])[i] || 0)}건) · 동전 봇 ${fmt.pct(fs[i] || 0, 1, false)} (${fmt.int((x.flip || [])[i] || 0)}건, 참고)`;
    const cols = h("div", {class: "ash-bars", role: "list", "aria-label": "거래 결과 구간별 비율"}, bins.map((b, i) => {
      const loss = (x.edges || [])[i] != null ? x.edges[i] <= 0 && i < 5 : i < 5;
      return h("button", {type: "button", class: "ash-bin " + (loss ? "loss" : "gain"), role: "listitem", title: say(i), "aria-label": say(i),
        onclick: (e) => { detail.textContent = say(i); for (const z of cols.querySelectorAll(".ash-bin.sel")) z.classList.remove("sel"); e.currentTarget.classList.add("sel"); }},
        h("i", {class: "ash-fill", style: {"--h": ((cs[i] || 0) / top * 100).toFixed(1) + "%"}}),
        h("i", {class: "ash-flip", style: {"--h": ((fs[i] || 0) / top * 100).toFixed(1) + "%"}}));
    }));
    const axis = h("div", {class: "ash-axis", "aria-hidden": "true"}, EDGE_KO.map((t, i) => h("span", {style: {"--x": ((i + 1) / bins.length * 100).toFixed(2) + "%"}}, t)));
    const share = (g) => (tot[g] ? fmt.pct((wins[g] || 0) / tot[g], 0, false) : "—");
    return [h("div", {class: "ash-legend"}, h("span", null, h("i", {class: "sw loss"}), h("i", {class: "sw gain"}), ` 기존 36 (${fmt.int(tot.core || 0)}건: 손실 · 이익)`),
      h("span", null, h("i", {class: "sw flip"}), ` 같은 봉 동전 봇 (${fmt.int(tot.flip || 0)}건, 참고)`)),
    h("div", {class: "ash-plot"}, cols, axis), h("p", {class: "ash-unit"}, "가로: 거래 한 번의 결과 (거래 전 잔고 대비 %) · 세로: 그 묶음 거래 중 비율"),
    detail,
    ui.kv([["기존 36", `이긴 거래 ${share("core")} · 강제청산 ${fmt.int(liq.core || 0)}건`],
      ["같은 봉 동전 봇 (참고)", `이긴 거래 ${share("flip")} · 강제청산 ${fmt.int(liq.flip || 0)}건`]]),
    h("p", {class: "an-note"}, "구간은 숫자를 보기 전에 정해 두었습니다. 수수료·펀딩이 들어간 실제 결과입니다. 동전 봇은 같은 봉(15분·30분·1시간·4시간)만, 5분 동전 봇은 5분봉 단타와 비교하므로 뺐습니다."),
    ui.refNote(env.verdictTs), ui.assume()];
  });
}
