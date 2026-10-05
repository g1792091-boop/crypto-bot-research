// 5년 시험 vs 지금 vs 동전 봇 (v4 additions wave 2 ⑨): on the strategy page, one small table per timeframe: the 5-year
// numbers (the same card the page shows below), this timeframe's live account and the same-timeframe coin flips'
// median, with a neutral word per row (비슷 / 다름 / 적음 / 표본 적음). GET /api/v4/vs5y/<strategy> (dash/more/vs5y.py).
// Purpose: a sanity check ("does the live account behave like the research?"), never a verdict.
// HONESTY: live numbers are 참고 (interim, refNote); the coin-flip column is the baseline; DeepSeek gets counts only
// (trades, per day: no per-account ROE / win rate, no coin-flip column); under 20 live trades a row says 표본 적음;
// realized trades carry the assumptions caption; the reel and DeepSeek compare at 1x (ROE ÷ leverage), the research's
// unit, and the card says so.
import {h, put, ui, fmt, motion} from "../core/pb.js";

const WORD = {similar: ["비슷", "thin"], differs: ["다름", "warn"], fewer: ["적음", "thin"], small: ["표본 적음", "thin"]};
const ROWS = [
  {k: "per_day", ko: "하루 거래", fmt: (v) => fmt.num(v, v != null && v < 10 ? 2 : 1)},
  {k: "roe", ko: "거래당 ROE", fmt: (v) => (v == null ? "—" : fmt.pct(v, 2))},
  {k: "win", ko: "이긴 비율", fmt: (v) => (v == null ? "—" : fmt.pct(v, 0, false))},
  {k: "hold_h", ko: "보유 (중간)", fmt: (v) => (v == null ? "—" : `${fmt.num(v, v < 10 ? 1 : 0)}시간`)},
  {k: "lock", ko: "잠금 청산", fmt: (v) => (v == null ? "—" : fmt.pct(v, 0, false))},
];

/**
 * vs5yCard(ctx, name, kind, {tf, verdictTs}) -> {el, load(), setTf(tf)}: the card (section.card).
 */
export function vs5yCard(ctx, name, kind, o = {}) {
  const st = {d: null, tf: o.tf || null, gone: false};
  const segBox = h("div", {class: "vs-seg"});
  const body = h("div", {class: "vs-body"}, motion.shimmer(3));
  const refBox = h("div");
  const el = ui.card({plate: "5년 시험 vs 지금", sub: kind === "ds200" ? "딥시크: 개수만" : "동전 봇과 나란히 · 참고", cls: "strat-o7 vs-card"},
    segBox, body, refBox);

  const one = (x, k) => (x && x[k] != null ? x[k] : null);
  function nowVal(t, k) {
    const nw = t.now || {};
    if (k === "roe") return st.d.unit === "1x" ? nw.roe_1x : nw.roe;
    return nw[k];
  }
  function flipVal(t, k) {
    const f = t.flips;
    if (!f) return null;
    if (k === "roe") return st.d.unit === "1x" ? f.roe_1x : f.roe;
    return f[k];
  }

  function table(t) {
    const d = st.d, counts = d.counts_only;
    const rows = ROWS.filter((r) => !(r.k === "lock" && (d.unit === "1x" || one(t.y5, "lock") == null && nowVal(t, "lock") == null)));
    const head = h("div", {class: "vs-row vs-head", role: "row"}, h("span", {role: "columnheader"}, ""),
      h("span", {role: "columnheader"}, "5년 시험"), h("span", {role: "columnheader"}, "지금"),
      counts ? null : h("span", {role: "columnheader"}, "동전 봇"), h("span", {role: "columnheader"}, ""));
    const line = (r) => {
      const nowHidden = counts && r.k !== "per_day";
      // 표본 적음 is said once under the table (a pill per row does not fit a phone); the row keeps a quiet mark
      const w = (t.words || {})[r.k];
      const [wko, wcls] = w === "small" ? [null, null] : WORD[w] || [null, null];
      return h("div", {class: "vs-row", role: "row"},
        h("span", {class: "vs-k", role: "rowheader"}, r.k === "roe" && d.unit === "1x" ? "거래당 (1배)" : r.ko),
        h("span", {class: "num vs-y5", role: "cell"}, r.fmt(one(t.y5, r.k))),
        h("span", {class: "num vs-now", role: "cell"}, nowHidden ? h("span", {class: "muted"}, "—") : r.fmt(nowVal(t, r.k))),
        counts ? null : h("span", {class: "num vs-flip", role: "cell"}, r.fmt(flipVal(t, r.k))),
        h("span", {class: "vs-w", role: "cell"}, wko ? ui.pill(wko, wcls) : w === "small" ? h("span", {class: "vs-small", title: "표본 적음"}, "·") : null));
    };
    const nw = t.now || {};
    const f = t.flips;
    const small = !counts && (nw.n || 0) < (d.min_n || 20);
    return [
      h("div", {class: ["vs-tbl", counts ? "counts" : ""], role: "table", "aria-label": `${fmt.tfKo(t.tf)} 5년 시험과 지금`}, head, rows.map(line)),
      small ? h("p", {class: "vs-smallnote"}, ui.pill("표본 적음", "thin"), ` 거래 ${fmt.int(nw.n || 0)}건: ${fmt.int(d.min_n || 20)}건이 되면 줄마다 비슷·다름이 나옵니다`) : null,
      h("p", {class: "note"}, `지금 = ${fmt.tfKo(t.tf)} 계좌의 끝난 거래 ${fmt.int(nw.n || 0)}건 (${fmt.num(nw.days || 0, 1)}일)`,
        counts ? " · 딥시크는 계좌마다 거래 수만 보여 드립니다" : f ? ` · 동전 봇 = 같은 봉 ${fmt.int(f.accounts)}개의 중간값 (거래 ${fmt.int(f.n)}건)` : " · 같은 봉 동전 봇 없음"),
    ];
  }

  function render() {
    if (st.gone) { put(body, ui.empty("이 매매법의 비교 자료가 아직 없습니다")); put(segBox); put(refBox); return; }
    const d = st.d;
    if (!d) return;
    const tfs = (d.tfs || []).map((t) => t.tf);
    if (!tfs.includes(st.tf)) st.tf = tfs[0];
    put(segBox, tfs.length > 1 ? ui.seg(tfs.map((tf) => ({id: tf, label: fmt.tfKo(tf)})), st.tf, (tf) => { st.tf = tf; renderBody(true); }, {label: "봉"}) : null);
    renderBody(false);
    const unitNote = d.unit === "1x" ? "거래당 = 진입가 대비 가격 % (배수 없이: 지금 계좌는 ROE ÷ 배수로 맞춤)"
      : "거래당 ROE = 증거금 대비 (5년 시험은 v3 배수 규칙)";
    const exitNote = d.y5_meta && d.y5_meta.exit && d.y5_meta.same_exits_as_live === false ? ` · 5년 연구 청산(${d.y5_meta.exit})은 지금 계좌 청산과 다름` : "";
    put(refBox, h("p", {class: "note"}, `${unitNote}${exitNote} · 5년 시험은 신호를 모두 따로 잡아서 지금 계좌(한 번에 한 포지션)보다 거래가 많은 게 보통입니다 (적음). 비슷·다름은 확인할 곳을 알려 줄 뿐 판정이 아닙니다.`),
      ui.refNote(o.verdictTs ? o.verdictTs() : null), ui.assume("closed", "지금 = 끝난 거래 기준"));
  }
  function renderBody(animate) {
    const t = (st.d.tfs || []).find((x) => x.tf === st.tf);
    put(body, t ? table(t) : ui.empty("이 봉 계좌가 없습니다"));
    if (animate) motion.swap(body);
  }

  async function load() {
    try { st.d = await ctx.api(`/api/v4/vs5y/${encodeURIComponent(name)}`); } catch (e) {
      if (e && e.name === "AbortError") return;
      if (e && e.status === 404) st.gone = true; else if (!st.d) { put(body, ui.errorBox(e, load)); return; }
    }
    render();
  }
  return {el, load, setTf(tf) { if (tf && tf !== st.tf) { st.tf = tf; if (st.d) render(); } }};
}
