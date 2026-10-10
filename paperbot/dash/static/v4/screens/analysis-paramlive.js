// 분석 › 커스텀값 비교 (owners' "2번", 2026-10-10; the 36 only): GET /api/v4/paramlive (dash/more/paramlive.py) reads
// the nightly custom-value shadow's summary (paperbot/paramshadow.py, 10:00 KST). Head: the job's own totals in one line
// (변형 N개 중 기본값보다 번 것 M · ★ S (우연으로도 최대 E) · 재계산 일치 P%), then the 36 x 4 map: one cell per strategy x
// timeframe with "기본값보다 번 변형 / 신호가 달라진 변형" and the ★ count, lightly tinted by that share (the neutral
// comparison colour, never up / down), each name and cell a link to the strategy's own table (#/strategies/<id>?tf=).
// HONESTY: a shadow and a reference, never a verdict; the job's texts (what, base, luck, parity, caution) as they are; a
// cell whose recomputed default has fewer trades than the job's star floor is dashed (표본 적음); no pass / fail words.
import {h, ui, fmt} from "../core/pb.js";
import {viewHead} from "./analysis-kit.js";
import {TFS, stateLines, metaLine, texts, multKo} from "./strategies-paramlive.js";

/** better / k -> the tint step 0..4 ("" for a cell with no variant that changed a signal). */
export function step(better, k) {
  if (!k) return "";
  const r = (better || 0) / k;
  return r <= 0 ? "0" : r < 0.25 ? "1" : r < 0.5 ? "2" : r < 0.75 ? "3" : "4";
}

function cellTitle(c, name, minT) {
  const b = c.base || {}, best = c.best;
  return [`${name} · ${fmt.tfKo(c.tf)}`,
    c.k ? `신호가 달라진 변형 ${fmt.int(c.k)}개 중 기본값보다 번 것 ${fmt.int(c.better || 0)}개 · ★ ${fmt.int(c.stars || 0)}` : "숫자를 바꿔도 신호가 하나도 달라지지 않음",
    `기본값(재계산) 거래 ${fmt.int(b.trades || 0)}건 · 손익 ${fmt.money(b.pnl, true)}${(b.trades || 0) < minT ? ` (${fmt.int(minT)}건 미만: ★ 없음)` : ""}`,
    best && c.k && best.diff_pnl > 0 ? `가장 많이 더 번 변형: ${best.param_ko || best.param || best.key} ${best.mult != null ? multKo(best.mult) : ""} (기본값 대비 ${fmt.money(best.diff_pnl, true)})` : null,
    "누르면 이 매매법의 변형 표"].filter(Boolean).join(" · ");
}

function cell(ctx, c, name, minT) {
  if (!c) return h("span", {class: "an-pl-cell is-none", role: "cell"}, h("b", null, "—"));
  const thin = (c.base && c.base.trades || 0) < minT;
  const title = cellTitle(c, name, minT);
  return h("a", {class: ["an-pl-cell", c.k ? "" : "is-none", thin ? "is-thin" : ""], role: "cell", href: ctx.href("strategies", c.strategy, {tf: c.tf}),
    dataset: {b: step(c.better, c.k)}, title, "aria-label": title},
  h("b", {class: "num"}, c.k ? `${fmt.int(c.better || 0)}/${fmt.int(c.k)}` : "—"),
  h("small", {class: ["num", c.stars ? "is-on" : ""]}, c.k ? `★${fmt.int(c.stars || 0)}` : "같음"));
}

function legend() {
  const words = ["0", "~25%", "~50%", "~75%", "75%+"];
  return h("div", {class: "an-pl-legend", "aria-label": "색 뜻"},
    h("span", {class: "muted"}, "기본값보다 번 변형 비율"),
    words.map((w, i) => h("span", {class: "an-pl-sw"}, h("i", {class: "an-pl-cell", dataset: {b: String(i)}, "aria-hidden": "true"}), w)),
    h("span", {class: "an-pl-sw"}, h("i", {class: "an-pl-cell is-thin", "aria-hidden": "true"}), "기본값 거래 적음"));
}

function grid(ctx, d) {
  const minT = d.min_trades || 20;
  const cells = d.cells || [];
  const at = new Map(cells.map((c) => [`${c.strategy}@${c.tf}`, c]));
  const names = [];
  for (const c of cells) if (!names.includes(c.strategy)) names.push(c.strategy);
  const nameOf = (s) => ((cells.find((c) => c.strategy === s) || {}).name_ko) || fmt.stratKo(s);
  const sum = (tf, key) => cells.filter((c) => c.tf === tf).reduce((a, c) => a + (c[key] || 0), 0);
  return h("div", {class: "an-pl-grid", role: "table", "aria-label": "매매법 × 봉: 기본값보다 번 변형 수"},
    h("div", {class: "an-pl-row an-pl-head", role: "row"}, h("span", {role: "columnheader"}, "매매법"),
      TFS.map((tf) => h("span", {role: "columnheader"}, fmt.tfKo(tf)))),
    names.map((s) => h("div", {class: "an-pl-row", role: "row"},
      h("a", {class: "an-pl-nm", role: "rowheader", href: ctx.href("strategies", s), title: s}, nameOf(s)),
      TFS.map((tf) => cell(ctx, at.get(`${s}@${tf}`), nameOf(s), minT)))),
    h("div", {class: "an-pl-row an-pl-foot", role: "row"}, h("span", {role: "rowheader"}, "합계"),
      TFS.map((tf) => h("span", {class: "num", role: "cell", title: `${fmt.tfKo(tf)}: 신호가 달라진 변형 ${fmt.int(sum(tf, "k"))}개 중 기본값보다 번 것 ${fmt.int(sum(tf, "better"))}개, ★ ${fmt.int(sum(tf, "stars"))}`},
        h("b", null, `${fmt.int(sum(tf, "better"))}/${fmt.int(sum(tf, "k"))}`), h("small", null, `★${fmt.int(sum(tf, "stars"))}`)))));
}

export function paramlive(d, env) {
  const ctx = env.ctx;
  const out = [viewHead({plate: "커스텀값 비교", q: "숫자 하나만 바꿨다면, v4 시작부터 지금까지 어땠을까",
    meta: d.available ? `${metaLine(d)} · 매일 10:00 갱신` : null,
    read: d.available && "칸 = 그 매매법 · 봉에서 신호가 달라진 변형 중 기본값(재계산)보다 돈을 더 번 변형 수 / 신호가 달라진 변형 수, ★ = 운 기준선을 넘고 앞뒤 절반 모두 더 번 변형 수. 색이 진할수록 더 번 변형이 많은 칸입니다 (참고, 판정 아님). 매매법 이름이나 칸을 누르면 그 매매법의 변형 표로 갑니다.",
    warn: stateLines(d)})];
  if (!d.available) {
    out.push(ui.card({plate: "커스텀값 비교"}, h("p", {class: "pl-none"}, d.none_ko || "아직 첫 계산 전입니다"), d.about_ko ? h("p", {class: "note"}, d.about_ko) : null));
    return out;
  }
  const o = d.overview || {};
  out.push(ui.card({plate: "한눈에", sub: `${fmt.int(o.cells || 0)}칸 · 변형마다 그림자 계좌 하나`, cls: "an-pl-top"},
    h("div", {class: "an-pl-stats"},
      ui.stat("변형", `${fmt.int(o.variants || 0)}개`, "신호가 기본값과 달라진 변형"),
      ui.stat("기본값보다 번 것", `${fmt.int(o.better || 0)}개`, o.variants ? `변형의 ${fmt.pct((o.better || 0) / o.variants, 0, false)}` : "—"),
      ui.stat("★ 붙은 변형", `${fmt.int(o.stars || 0)}개`, `우연으로도 최대 ${fmt.num(o.stars_by_luck || 0, 1)}개`),
      ui.stat("재계산 일치", o.parity == null ? "—" : fmt.pct(o.parity, 0, false), "기본값 재계산 vs 실제 계좌 진입")),
    h("p", {class: "an-pl-line"}, `변형 ${fmt.int(o.variants || 0)}개 중 기본값보다 번 것 ${fmt.int(o.better || 0)} · ★ ${fmt.int(o.stars || 0)} (우연으로도 최대 ${fmt.num(o.stars_by_luck || 0, 1)}) · 재계산 일치 ${o.parity == null ? "—" : fmt.pct(o.parity, 0, false)}`),
    ...texts(d, ["luck"])));
  out.push(ui.card({plate: "매매법 × 봉", sub: "기본값보다 번 변형 / 신호가 달라진 변형 · ★", cls: "an-pl-map"},
    grid(ctx, d), legend(),
    h("p", {class: "note"}, `점선 칸 = 기본값(재계산) 거래가 ${fmt.int(d.min_trades || 20)}건 미만이라 ★를 매기지 않는 칸. '같음' = 숫자를 바꿔도 신호가 하나도 달라지지 않은 칸.`)));
  out.push(ui.card({plate: "읽는 법"}, ...texts(d, ["what", "base", "parity", "caution"]),
    (d.notes || []).length ? ui.disclosure(`계산 메모 ${fmt.int(d.notes.length)}개`, h("div", {class: "stack tight"}, d.notes.map((n) => h("p", {class: "note"}, n)))) : null,
    h("p", {class: "note"}, d.label_ko || "그림자 계좌 · 참고용 (판정 아님)")));
  return out;
}
