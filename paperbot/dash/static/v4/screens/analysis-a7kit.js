// 분석 ana7a: the small pieces the four ana7a views share (좋은 수치 찾기, 강제청산 직후, 들고 있었다면, GH Coin 방향).
//   cellLine  "n건 · 이긴 비율 · 평균 ROE" (+ 표본 적음); DeepSeek (noMoney) without the ROE
//   cmpRows   rows "label → 우리 묶음 / 동전 봇" with the plain cell lines (phones: stacked, analysis-kit cmpList style)
//   divBar    a bar that grows left (worse) or right (better) from the middle line
//   fetchInto a box that fills itself from one more route ({pending: true}: shimmer, asked again after 3 s)
// Every server string is text (h()); numbers only through fmt.
import {h, put, ui, fmt, motion} from "../core/pb.js";

export const RETRY_MS = 3000;
export const pc = (x, d = 0) => (x == null ? "—" : fmt.pct(x, d, false));
export const sp = (x, d = 1) => (x == null ? "—" : fmt.pct(x, d, true));
export const rr = (x, d = 2) => (x == null ? "—" : `${fmt.num(x, d, true)}R`);

/** One cell as words: c = {n, wr, mean_roe, small}. noMoney: counts and shares only. */
export function cellLine(c, noMoney, min = 10) {
  const n = (c && c.n) || 0;
  if (!n) return h("span", {class: "muted"}, "0건");
  const small = c.small || n < min;
  return h("span", {class: "a7-cell"},
    h("b", {class: "num"}, `${fmt.int(n)}건`), h("span", {class: "a7-dot", "aria-hidden": "true"}, " · "),
    h("span", {class: "num"}, `이긴 비율 ${pc(c.wr)}`),
    !noMoney && c.mean_roe != null ? [h("span", {class: "a7-dot", "aria-hidden": "true"}, " · "),
      h("span", {class: ["num", fmt.tone(c.mean_roe)]}, `평균 ROE ${sp(c.mean_roe)}`)] : null,
    small ? [" ", ui.pill("표본 적음", "thin")] : null);
}

/** Rows: {label, sub, a: Node, b: Node}; heads: {k, a, b}. */
export function cmpRows(rows, heads) {
  return h("div", {class: "a7-cmp", role: "list"},
    h("div", {class: "a7-cmprow a7-cmphead", "aria-hidden": "true"}, h("span", null, heads.k || ""), h("span", null, heads.a), h("span", null, heads.b)),
    rows.map((r) => h("div", {class: "a7-cmprow", role: "listitem"},
      h("span", {class: "a7-cmpk"}, h("b", null, r.label), r.sub ? h("small", null, r.sub) : null),
      h("span", {class: "a7-cmpv"}, h("i", {class: "a7-tag"}, heads.a), r.a),
      h("span", {class: "a7-cmpv"}, h("i", {class: "a7-tag"}, heads.b), r.b))));
}

/** A bar from the middle line: v on the scale ``top`` (|v| = top fills one half); tone "up" | "down" | "flat". */
export function divBar(v, top, tone = "flat", label = "") {
  const w = v == null || !top ? 0 : Math.min(1, Math.abs(v) / top) * 50;
  return h("span", {class: "a7-div", role: "img", "aria-label": label || (v == null ? "—" : String(v))},
    h("i", {class: "a7-mid"}),
    w > 0 ? h("i", {class: ["a7-fill", tone, v < 0 ? "neg" : "pos"], style: {"--w": w.toFixed(1) + "%"}}) : null);
}

/** A box filled from ``path`` by ``render(d) -> [Node]``: shimmer first, {pending} asks again, an error offers 다시. */
export function fetchInto(env, path, plate, render) {
  const box = h("div", {class: "stack a7-box", "aria-live": "polite"}, ui.card({plate}, motion.shimmer(4, true)));
  let dead = false;
  env.track(() => { dead = true; });
  const ask = () => {
    env.ctx.api(path).then((d) => {
      if (dead || !env.ctx.alive()) return;
      if (d && d.pending) {
        put(box, ui.card({plate}, h("p", {class: "muted"}, d.note || "서버가 계산하는 중입니다. 잠시 뒤 다시 봅니다."), motion.shimmer(3)));
        env.ctx.timeout(() => { if (!dead) ask(); }, RETRY_MS);
        return;
      }
      let nodes;
      try { nodes = render(d || {}); } catch (e) {
        console.error(e);
        nodes = [ui.card({plate}, h("p", {class: "muted"}, "이 부분을 그리지 못했습니다 (자료 모양이 바뀌었을 수 있음)."))];
      }
      put(box, ...nodes);
      motion.swap(box);
    }).catch(() => {
      if (dead || !env.ctx.alive()) return;
      put(box, ui.card({plate}, ui.errorBox(null, () => { put(box, motion.shimmer(3, true)); ask(); })));
    });
  };
  ask();
  return box;
}

/** "10/06 03:35" or "—". */
export const when = (ms) => (ms ? fmt.kst(ms) : "—");

/** The no-money line under a DeepSeek view's head. */
export const noMoneyLine = () => h("p", {class: "an-read"}, ui.pill("돈 숫자 없음", "ref"), " 딥시크는 거래 수와 이긴 비율만 봅니다 (손익·수익률은 딥시크 화면에서).");
