// 분석 › 커스텀값 비교 (owners' "2번", 2026-10-10; the 36 only): GET /api/v4/paramlive (dash/more/paramlive.py) reads
// the nightly custom-value shadow's summary (paperbot/paramshadow.py, 10:00 KST). Head: the job's own totals in one line
// (변형 N개 중 기본값보다 번 것 M · ★ 붙은 칸 S (우연으로도 최대 E칸) · 재계산 일치 P%), then the 36 x 4 map: one cell per strategy x
// timeframe with "기본값보다 번 변형 / 신호가 달라진 변형" and the ★ count, lightly tinted by that share (the neutral
// comparison colour, never up / down), each name and cell a link to the strategy's own table (#/strategies/<id>?tf=).
// HONESTY: a shadow and a reference, never a verdict; the job's texts (what, base, luck, parity, caution) as they are; a
// cell whose recomputed default has fewer trades than the job's star floor is dashed (표본 적음); no pass / fail words.
// At a glance (second round, 10/10): first 지켜볼 후보, the server's ``candidates`` (up to 8 variants closest to the luck
// line: 매매법 · 봉 · "숫자 기본값→바꾼 값" · 기본값 대비 · "운 기준선까지 NN%" with the card's bar · ★; each row opens that
// strategy's table on that timeframe) under "판단할 수 있는 칸 (기본값 거래 20건 이상): N / 144" (``cells_ready``); a map
// cell's tooltip starts with the server's one-line reading of that cell (``summary_ko``).
// Two numbers at once (the job's version 2): a pair names both changes ("슈퍼트렌드 배수 6→4.5 + ROC 길이 9→11 (×0.75 ·
// ×1.25)") in 지켜볼 후보 and in a map cell's best variant; the totals say how many of each (하나씩 N · 두 숫자 함께 M).
import {h, ui, fmt} from "../core/pb.js";
import {viewHead} from "./analysis-kit.js";
import {TFS, stateLines, metaLine, texts, multKo, luckBar, luckPct, changeKo} from "./strategies-paramlive.js";

/** A variant's change and its multipliers: ["슈퍼트렌드 배수 6→4.5 + ROC 길이 9→11", "×0.75 · ×1.25"] (a version-1 row: its own
 *  param / default / value / mult). */
export function changeWords(v) {
  if (!v) return ["—", ""];
  const parts = Array.isArray(v.parts) && v.parts.length ? v.parts
    : v.param ? [{param: v.param, param_ko: v.param_ko, default: v.default, value: v.value, mult: v.mult}] : [];
  return [v.change_ko || changeKo(parts) || v.key || "—", parts.filter((p) => p.mult != null).map((p) => multKo(p.mult)).join(" · ")];
}

/** better / k -> the tint step 0..4 ("" for a cell with no variant that changed a signal). */
export function step(better, k) {
  if (!k) return "";
  const r = (better || 0) / k;
  return r <= 0 ? "0" : r < 0.25 ? "1" : r < 0.5 ? "2" : r < 0.75 ? "3" : "4";
}

function cellTitle(c, name, minT) {
  const b = c.base || {}, best = c.best;
  return [`${name} · ${fmt.tfKo(c.tf)}`, c.summary_ko,
    c.k ?`신호가 달라진 변형 ${fmt.int(c.k)}개 중 기본값보다 번 것 ${fmt.int(c.better || 0)}개 · ★ ${fmt.int(c.stars || 0)}` : "숫자를 바꿔도 신호가 하나도 달라지지 않음",
    `기본값(재계산) 거래 ${fmt.int(b.trades || 0)}건 · 손익 ${fmt.money(b.pnl, true)}${(b.trades || 0) < minT ? ` (${fmt.int(minT)}건 미만: ★ 없음)` : ""}`,
    best && c.k && best.diff_pnl > 0 ? (([w, m]) => `가장 많이 더 번 변형: ${w}${m ? ` (${m})` : ""} (기본값 대비 ${fmt.money(best.diff_pnl, true)})`)(changeWords(best)) : null,
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

// ---------------------------------------------------------------- 지켜볼 후보
function candRow(ctx, c) {
  const name = c.name_ko || fmt.stratKo(c.strategy);
  const [change, mults] = changeWords(c);
  const mx = mults ? ` (${mults})` : "";
  const luck = `운 기준선까지 ${fmt.int(luckPct(c.ratio))}%`;
  const diff = fmt.money(c.diff_pnl, true);
  return h("a", {class: ["an-pl-cand", c.star ? "is-star" : ""], role: "listitem", href: ctx.href("strategies", c.strategy, {tf: c.tf}),
    title: `${name} · ${fmt.tfKo(c.tf)} · ${change}${mx} · 거래 ${fmt.int(c.trades)}건 · 기본값 대비 ${diff} · ${luck}${c.star ? " · ★" : ""} · 누르면 이 매매법의 변형 표`},
  h("span", {class: "an-pl-cand-nm"}, h("b", null, name), h("span", {class: "muted"}, ` · ${fmt.tfKo(c.tf)}`)),
  h("span", {class: "an-pl-cand-p"}, change, h("span", {class: "muted"}, `${mx} · 거래 ${fmt.int(c.trades)}건`)),
  h("span", {class: "an-pl-cand-n"},
    h("span", {class: "an-pl-cand-d"}, h("span", {class: "muted"}, "기본값 대비 "), h("b", {class: ["num", fmt.tone(c.diff_pnl, diff)]}, diff)),
    h("span", {class: "an-pl-cand-l"}, luckBar(c.ratio), h("span", {class: "num"}, luck),
      c.star ? h("b", {class: "an-pl-cand-star", title: "★ = 거래 충분 · 운 기준선 위 · 앞뒤 절반 모두 기본값보다 많이 범 (참고, 판정 아님)"}, "★") : null)));
}

function candidatesCard(ctx, d) {
  const rows = d.candidates || [];
  const minT = d.min_trades || 20;
  const total = d.cells_total != null ? d.cells_total : (d.cells || []).length;
  return ui.card({plate: "지켜볼 후보", sub: "운 기준선에 가장 가까이 간 변형 · 참고 (판정 아님)", cls: "an-pl-cands"},
    h("p", {class: "an-pl-ready"}, `판단할 수 있는 칸 (기본값 거래 ${fmt.int(minT)}건 이상): `,
      h("b", {class: "num"}, `${fmt.int(d.cells_ready || 0)} / ${fmt.int(total)}`)),
    rows.length
      ? h("div", {class: "an-pl-clist", role: "list", "aria-label": "지켜볼 후보"}, rows.map((c) => candRow(ctx, c)))
      : h("p", {class: "an-pl-empty"}, "아직 운 기준선 가까이 간 변형이 없습니다 — 거래가 쌓이면 여기에 나타납니다"),
    h("p", {class: "note"}, "운 기준선까지 NN% = 기본값보다 거래당 더 번 정도를 운 기준선(칸마다 시험한 변형 수만큼 엄격하게)과 견준 값. 100%를 넘고 기간 앞·뒤 모두 나아야 ★. ★가 붙어도 바꿀지는 30일 판정 뒤 두 분이 정합니다. 줄을 누르면 그 매매법의 변형 표로 갑니다."),
    rows.length ? ui.assume() : null);
}

export function paramlive(d, env) {
  const ctx = env.ctx;
  const o = d.overview || {};
  const mix = o.pairs ? ` (하나씩 ${fmt.int(o.singles || 0)} · 두 숫자 함께 ${fmt.int(o.pairs)})` : "";
  const out = [viewHead({plate: "커스텀값 비교", q: o.pairs ? "숫자를 하나 또는 둘 바꿨다면, v4 시작부터 지금까지 어땠을까" : "숫자 하나만 바꿨다면, v4 시작부터 지금까지 어땠을까",
    meta: d.available ? `${metaLine(d)} · 매일 10:00 갱신` : null,
    read: d.available && "칸 = 그 매매법 · 봉에서 신호가 달라진 변형 중 기본값(재계산)보다 돈을 더 번 변형 수 / 신호가 달라진 변형 수, ★ = 운 기준선을 넘고 앞뒤 절반 모두 더 번 변형 수. 색이 진할수록 더 번 변형이 많은 칸입니다 (참고, 판정 아님). 매매법 이름이나 칸을 누르면 그 매매법의 변형 표로 갑니다.",
    warn: stateLines(d)})];
  if (!d.available) {
    out.push(ui.card({plate: "커스텀값 비교"}, h("p", {class: "pl-none"}, d.none_ko || "아직 첫 계산 전입니다"), d.about_ko ? h("p", {class: "note"}, d.about_ko) : null));
    return out;
  }
  out.push(candidatesCard(ctx, d));
  out.push(ui.card({plate: "한눈에", sub: `${fmt.int(o.cells || 0)}칸 · 변형마다 그림자 계좌 하나`, cls: "an-pl-top"},
    h("div", {class: "an-pl-stats"},
      ui.stat("변형", `${fmt.int(o.variants || 0)}개`, o.pairs ? `하나씩 ${fmt.int(o.singles || 0)} · 두 숫자 함께 ${fmt.int(o.pairs)}` : "신호가 기본값과 달라진 변형"),
      ui.stat("기본값보다 번 것", `${fmt.int(o.better || 0)}개`, o.variants ? `변형의 ${fmt.pct((o.better || 0) / o.variants, 0, false)}` : "—"),
      ui.stat("★ 붙은 칸", `${fmt.int(o.star_cells || 0)}칸`, `우연으로도 최대 ${fmt.num(o.stars_by_luck || 0, 1)}칸 · ★ 변형 ${fmt.int(o.stars || 0)}개`),
      ui.stat("재계산 일치", o.parity == null ? "—" : fmt.pct(o.parity, 0, false), "기본값 재계산 vs 실제 계좌 진입")),
    h("p", {class: "an-pl-line"}, `변형 ${fmt.int(o.variants || 0)}개${mix} 중 기본값보다 번 것 ${fmt.int(o.better || 0)} · ★ 붙은 칸 ${fmt.int(o.star_cells || 0)} (우연으로도 최대 ${fmt.num(o.stars_by_luck || 0, 1)}칸) · 재계산 일치 ${o.parity == null ? "—" : fmt.pct(o.parity, 0, false)}`),
    ...texts(d, ["luck"])));
  out.push(ui.card({plate: "매매법 × 봉", sub: "기본값보다 번 변형 / 신호가 달라진 변형 · ★", cls: "an-pl-map"},
    grid(ctx, d), legend(),
    h("p", {class: "note"}, `점선 칸 = 기본값(재계산) 거래가 ${fmt.int(d.min_trades || 20)}건 미만이라 ★를 매기지 않는 칸. '같음' = 숫자를 바꿔도 신호가 하나도 달라지지 않은 칸.`)));
  out.push(ui.card({plate: "읽는 법"}, ...texts(d, ["what", "base", "parity", "caution"]),
    (d.notes || []).length ? ui.disclosure(`계산 메모 ${fmt.int(d.notes.length)}개`, h("div", {class: "stack tight"}, d.notes.map((n) => h("p", {class: "note"}, n)))) : null,
    h("p", {class: "note"}, d.label_ko || "그림자 계좌 · 참고용 (판정 아님)")));
  return out;
}
