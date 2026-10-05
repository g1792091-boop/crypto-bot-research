// 숫자(파라미터) 시험 결과 (매매법 상세 #/strategies/<id>, v4 addition): what the five-year research already said
// about this strategy's numbers. GET /api/v4/params/<id> (dash/more/params.py) reads the committed research files only:
//   the 36     one row per timeframe x parameter: shape (평평 / 완만 / 뾰족 / 표본 부족), variants, positive in all 3 periods
//   the reel   its choice variants (moving average, breach, sides) and timeframes: configurations positive per period
//   DeepSeek   "이 매매법은 숫자 변형 시험 없음" + its timeframe x exit rows as COUNTS only (no money, owners D10 / D11)
// HONESTY: everything is 5년 과거 시험 (참고); no pass / fail colours (a variant positive in all three periods is a plain
// count, never green); the explanation says why the best past number is a trap and how new numbers get tested (the AI
// lab's 3-period test, then a separate new paper account; a running account's numbers never change). Texts come from
// the server so the page and the agents' packets say the same. Rows are a 3-column list (name | middle | all three
// periods) so the key column stays on screen at 390 px; the details sit on a second small line under the name.
import {h, s, put, ui, fmt, motion} from "../core/pb.js";

const GLYPH = {
  flat: "M2 8 L34 8",
  smooth: "M2 11 C10 11 13 5 18 5 C23 5 26 11 34 11",
  sharp: "M2 12 L14 12 L18 2 L22 12 L34 12",
  thin: "M2 8 L34 8",
};

/** The shape as a small drawn sign (a meaning sign, not a data line) + its word. */
export function shapeTag(shape, ko) {
  const g = s("svg", {class: "strat-pm-glyph", viewBox: "0 0 36 14", width: "36", height: "14", "aria-hidden": "true"},
    s("path", {d: GLYPH[shape] || GLYPH.thin}));
  return h("span", {class: ["strat-pm-shape", "is-" + (GLYPH[shape] ? shape : "thin")]}, g, h("span", null, ko || "—"));
}

const per3 = (o, f = (x) => fmt.int(x)) => (o ? ["is", "cf", "pre"].map((k) => (o[k] == null ? "—" : f(o[k]))).join(" · ") : "—");
const stat = (k, v, sub) => h("div", {class: "strat-pm-stat"}, h("span", {class: "k"}, k), h("b", {class: "num"}, v), sub ? h("span", {class: "s"}, sub) : null);

/** groups: [{title, rows: [{name, code, pill, sub, mid, end}]}]; heads: [name, mid, end] labels. */
function rowList(heads, groups) {
  return h("div", {class: "strat-pm-list", role: "table"},
    h("div", {class: "strat-pm-row strat-pm-head", role: "row"}, heads.map((x) => h("span", {role: "columnheader"}, x))),
    groups.map((g) => [
      g.title ? h("div", {class: "strat-pm-group", role: "row"}, h("b", {role: "rowheader"}, g.title)) : null,
      g.rows.map((r) => h("div", {class: "strat-pm-row", role: "row"},
        h("span", {class: "strat-pm-nm", role: "cell"}, h("span", null, r.name), r.pill || null,
          r.code ? h("span", {class: "muted mono strat-pm-code"}, r.code) : null,
          r.sub ? h("span", {class: "muted strat-pm-sub"}, r.sub) : null),
        h("span", {class: "strat-pm-mid", role: "cell"}, r.mid),
        h("span", {class: ["strat-pm-end num", r.hit ? "strat-pm-hit" : "muted"], role: "cell"}, r.end))),
    ]));
}

function why(d, lead) {
  return h("div", {class: "strat-pm-why"},
    h("b", null, "이게 무슨 뜻이냐면"),
    [lead, d.trap_ko, d.lab_ko].filter(Boolean).map((t) => h("p", null, t)));
}

function legend(d) {
  return h("ul", {class: "strat-pm-legend", "aria-label": "모양 뜻"},
    (d.shapes_ko || []).map((x) => h("li", null, shapeTag(x.shape, x.ko), h("span", {class: "muted"}, x.note_ko))));
}

function foot(d, extra) {
  return h("p", {class: "note"}, `${d.label_ko || "5년 과거 시험 (참고)"} · 설명 자료이지 규칙이나 실력 증거가 아닙니다.`, extra ? ` ${extra}` : "");
}

const byKey = (rows, key) => {
  const out = [];
  for (const r of rows || []) { const k = r[key]; if (!out.length || out[out.length - 1].k !== k) out.push({k, rows: []}); out[out.length - 1].rows.push(r); }
  return out;
};

// ---------------------------------------------------------------- the 36
function coreBody(d) {
  const c = d.core;
  const shapes = c.shapes || {};
  const groups = byKey(c.rows, "tf").map((g) => ({
    title: `${fmt.tfKo(g.k)}봉`,
    rows: g.rows.map((r) => ({
      name: r.param_ko || r.param, code: r.param_ko ? r.param : null, mid: shapeTag(r.shape, r.shape_ko),
      end: `${fmt.int(r.positive_all3)} / ${fmt.int(r.variants)}`, hit: r.positive_all3 > 0,
      sub: r.positive_all3 ? `세 기간 플러스였던 값: ${r.positive_values.map((x) => `${x.value}${x.mult != null ? ` (×${fmt.num(x.mult, Number.isInteger(x.mult * 10) ? 1 : 2)} 변형)` : ""}`).join(", ")}` : null,
    })),
  }));
  const anyHit = (c.rows || []).some((r) => r.positive_all3);
  const st = c.study || {};
  const ss = st.shapes || {};
  return [
    h("div", {class: "strat-pm-stats"},
      stat("숫자 변형 시험", `${fmt.int(c.variants)}개`, `숫자 ${fmt.int((c.rows || []).length)}줄 × 4`),
      stat("세 기간 모두 플러스", `${fmt.int(c.positive_all3)}개`, `채택 ${fmt.int(c.adopted)}개`),
      stat("뾰족 (위험 신호)", `${fmt.int(shapes.sharp || 0)}개`, `평평 ${fmt.int(shapes.flat || 0)} · 완만 ${fmt.int(shapes.smooth || 0)} · 표본 부족 ${fmt.int(shapes.thin || 0)}`)),
    why(d, c.meaning_ko),
    rowList(["숫자", "모양", "세 기간 모두 +"], groups),
    h("p", {class: "note"}, "오른쪽 = 세 기간 모두 플러스였던 변형 수 / 시험한 변형 수 (기본값의 0.5 · 0.75 · 1.25 · 1.5배)."),
    anyHit ? h("p", {class: "note"}, c.positive_note_ko) : null,
    c.untested_ko ? h("p", {class: "note"}, c.untested_ko) : null,
    legend(d),
    ui.disclosure("어떻게 시험했나", h("div", {class: "stack tight strat-pm-how"},
      h("p", null, c.how_ko),
      h("p", null, d.periods_ko),
      st.variants ? h("p", null, `36개 매매법 전체: 숫자 ${fmt.int(st.params)}줄, 변형 ${fmt.int(st.variants)}개, 세 기간 모두 플러스 ${fmt.int(st.positive_all3)}개, 뾰족 ${fmt.int(ss.sharp || 0)}개 (평평 ${fmt.int(ss.flat || 0)} · 완만 ${fmt.int(ss.smooth || 0)} · 표본 부족 ${fmt.int(ss.thin || 0)}).`) : null,
      c.conclusion_ko ? h("p", {class: "muted"}, `연구 결론: ${c.conclusion_ko}`) : null,
      h("p", {class: "muted mono"}, c.source))),
    foot(d),
  ];
}

// ---------------------------------------------------------------- the reel
function reelBody(d) {
  const r = d.reel;
  const live = (x) => (x.live ? ui.pill("지금 계좌", "accent") : null);
  const vgroups = byKey(r.rows, "dimension").map((g) => ({
    title: g.rows[0].dimension_ko,
    rows: g.rows.map((x) => ({
      name: x.variant_ko || x.variant, pill: live(x), mid: per3(x.positive), end: `${fmt.int(x.all3_positive)} / ${fmt.int(x.configs)}`,
      hit: x.all3_positive > 0, sub: `거래당 ${per3(x.per_trade_pct, (v) => `${fmt.num(v, 3, true)}%`)}`,
    })),
  }));
  const tgroups = [{title: null, rows: (r.by_tf || []).map((x) => ({
    name: `${fmt.tfKo(x.tf)}봉`, pill: live(x), mid: per3(x.positive), end: `${fmt.int(x.all3_positive)} / ${fmt.int(x.configs)}`, hit: x.all3_positive > 0}))}];
  const heads = ["선택", "플러스 (1·2·3기)", "세 기간 모두 +"];
  return [
    h("div", {class: "strat-pm-stats"},
      stat("설정 시험", r.configs == null ? "—" : `${fmt.int(r.configs)}개`, "선택을 바꾼 조합"),
      stat("세 기간 모두 플러스", r.all3_positive == null ? "—" : `${fmt.int(r.all3_positive)}개`, `통과 ${r.candidates == null ? "—" : fmt.int(r.candidates)}개`),
      stat("지금 설정 (H1) 5년 시험", r.h1_pass == null ? "—" : r.h1_pass ? "통과" : "불통과", "사전 등록 시험 · 30일 판정 아님")),
    why(d, r.meaning_ko),
    h("p", {class: "note"}, r.how_ko),
    rowList(heads, vgroups),
    h("p", {class: "note"}, "가운데 = 그 선택이 들어간 설정 중 기간마다 플러스였던 수. 오른쪽 = 세 기간 모두 플러스 / 설정 수. ", r.unit_ko),
    (r.by_tf || []).length ? ui.disclosure("봉별로 보기", rowList(["봉", "플러스 (1·2·3기)", "세 기간 모두 +"], tgroups)) : null,
    ui.disclosure("어떻게 시험했나", h("div", {class: "stack tight strat-pm-how"},
      h("p", null, d.periods_ko), h("p", {class: "muted mono"}, r.source))),
    foot(d),
  ];
}

// ---------------------------------------------------------------- DeepSeek (counts only)
function dsBody(d) {
  const x = d.ds;
  if (!x) return [h("p", {class: "strat-pm-none"}, d.none_ko || "이 매매법은 숫자 변형 시험 없음"), foot(d)];
  const groups = byKey(x.rows, "tf").map((g) => ({
    title: `${fmt.tfKo(g.k)}봉`,
    rows: g.rows.map((r) => ({name: r.exit_ko, sub: `거래 ${per3(r.trades)}`, mid: `${fmt.int(r.positive_periods)} / 3 기간`,
      end: r.all3_positive ? "예" : "아니요", hit: r.all3_positive})),
  }));
  const fg = x.family_gauntlet;
  return [
    h("p", {class: "strat-pm-none"}, x.none_ko || d.none_ko),
    h("p", {class: "note"}, x.how_ko),
    rowList(["연구 청산", "플러스였던 기간", "세 기간 모두 +"], groups),
    h("p", {class: "small"}, x.summary_ko, fg ? ` 같은 계열(${x.family_ko || x.family}) 전체: 설정 ${fmt.int(fg.configs)}개, 세 기간 모두 플러스 ${fmt.int(fg.all3_positive)}개, 후보 ${fmt.int(fg.candidates)}개.` : ""),
    why(d, x.meaning_ko),
    x.exit_note_ko ? h("p", {class: "note"}, x.exit_note_ko) : null,
    ui.disclosure("어떻게 시험했나", h("div", {class: "stack tight strat-pm-how"},
      h("p", null, d.periods_ko), h("p", {class: "muted mono"}, x.source))),
    foot(d, "딥시크는 돈 숫자 없이 횟수만 보여 줍니다."),
  ];
}

/**
 * The panel for one strategy: a card (strat-o7, right after the 5-year card on phones and on PC). ``after``: the card
 * it is placed after once the detail view is put together (the detail builds its columns after its cards, so the
 * placement waits one microtask). ``scope``: the detail's scope (a late answer after the detail closed is dropped).
 */
export function paramsCard(ctx, name, kind, {after, scope} = {}) {
  const body = h("div", {class: "stack tight"}, motion.shimmer(3));
  const card = ui.card({plate: "숫자(파라미터) 시험 결과", sub: "5년 과거 시험 (참고)", cls: "strat-o7 strat-pm"}, body);
  const alive = () => (scope ? scope.alive() : ctx.alive());
  async function load() {
    put(body, motion.shimmer(3));
    let d = null, err = null;
    try { d = await ctx.api(`/api/v4/params/${encodeURIComponent(name)}`); } catch (e) { err = e; }
    if (!alive()) return;
    if (err && err.status === 404) { put(body, h("p", {class: "strat-pm-none"}, "이 매매법은 숫자 변형 시험 없음"), h("p", {class: "note"}, "5년 과거 시험 자료에 이 매매법이 없습니다.")); return; }
    if (!d) { put(body, ui.errorBox(err, load)); return; }
    const parts = d.group === "core" && d.core ? coreBody(d) : d.group === "reel" && d.reel ? reelBody(d) : d.group === "ds200" ? dsBody(d)
      : [h("p", {class: "strat-pm-none"}, d.none_ko || "이 매매법은 숫자 변형 시험 없음"), foot(d)];
    put(body, ...parts);
    motion.swap(body);
  }
  if (after) queueMicrotask(() => { if (after.parentNode && !card.parentNode) after.after(card); });
  load();
  return {el: card, load, kind};
}
