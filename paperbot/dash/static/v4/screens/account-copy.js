// 계좌 · 원본 vs 복제 (review addition 10): an approved copy account next to its parent over the SAME period, from the
// copy's start (GET /api/v4/copycmp/<id>, dash/more/copycmp.py). The board compares each account from its own start,
// so "바꾼 게 더 나았나?" could not be read anywhere; here both lines start at 0 % on the copy's first day (closed-trade
// balance, as the board), the trades each one closed since then sit side by side, and the one changed rule is named. The same-timeframe coin flips over
// the same period are a 참고 line. HONESTY: below 30 trades the card says 표본 적음; nothing here is a verdict; a failed
// load is an error box with a retry (never "없음"); a copy of a DeepSeek account (none today) would get counts only.
import {h, ui, fmt, motion} from "../core/pb.js";

const pp = (x) => (x == null ? "—" : `${fmt.num(x * 100, 1, true)}%p`);

/** The comparison rows [{k, parent, copy, tone, pv, cv}] of a /api/v4/copycmp answer (pure). No row says which side
 *  "won": the numbers side by side, the money ones in the up / down colours only. */
export function copyRows(d) {
  const p = (d && d.parent) || {}, c = (d && d.copy) || {};
  const trades = {k: "거래 (이 기간에 끝난 것)", parent: fmt.int(p.trades || 0) + "건", copy: fmt.int(c.trades || 0) + "건"};
  const win = {k: "이긴 비율", parent: p.win_rate == null ? "—" : fmt.pct(p.win_rate, 0, false), copy: c.win_rate == null ? "—" : fmt.pct(c.win_rate, 0, false)};
  const liq = {k: "강제청산", parent: fmt.int(p.liquidations || 0) + "건", copy: fmt.int(c.liquidations || 0) + "건"};
  if (!d || d.count_only) return [trades, win, liq];
  return [
    {k: "기간 수익률", parent: fmt.pct(p.ret, 1), copy: fmt.pct(c.ret, 1), tone: true, pv: p.ret, cv: c.ret},
    trades, win,
    {k: "거래당 ROE (평균)", parent: fmt.pct(p.mean_roe, 1), copy: fmt.pct(c.mean_roe, 1), tone: true, pv: p.mean_roe, cv: c.mean_roe},
    {k: "수수료 (시작 잔고 대비)", parent: fmt.pct(p.fees_share, 1, false), copy: fmt.pct(c.fees_share, 1, false)},
    {k: "펀딩 (시작 잔고 대비)", parent: fmt.pct(p.funding_share, 2, false), copy: fmt.pct(c.funding_share, 2, false)},
    liq];
}

/** The card; loads by itself (ctx.api is aborted when the screen is left). onData(d): the caller may reuse the answer. */
export function copyCard(ctx, id, onData) {
  const body = h("div", {class: "acc-body"}, motion.shimmer(3, true));
  // the money caption said once on 계좌 (CONTRACT 1, "Say it once"; the page's line at the bottom): an ⓘ in the head
  // carries this card's exact caption once its money numbers are drawn (none for a count-only copy)
  const tip = h("span", {class: "acc-tip"});
  const el = ui.card({plate: "원본 vs 복제 · 같은 기간", cls: "acc", acts: [tip]}, body);
  async function load() {
    body.replaceChildren(motion.shimmer(3, true));
    let d;
    try { d = await ctx.api(`/api/v4/copycmp/${encodeURIComponent(id)}`); }
    catch (e) {
      if (e && e.name === "AbortError") return;
      body.replaceChildren(ui.errorBox(e, load));
      return;
    }
    if (!ctx.alive()) return;
    if (onData) onData(d);
    body.replaceChildren(...render(d));
  }
  function render(d) {
    const tf = fmt.tfKo(d.timeframe);
    tip.replaceChildren(...(d.count_only ? [] : [ui.infoTip(`${ui.ASSUME_KO} · 기간 수익률 = 복제 시작 때 잔고 대비 지금 잔고`, "원본 vs 복제의 돈 숫자")]));
    const head = h("p", {class: "acc-rule"}, "바꾼 규칙 하나: ", h("b", null, d.rule_ko || "—"),
      h("span", {class: "muted"}, ` · 원본 ${fmt.idName(d.parent_id)} · 복제 시작 ${fmt.kst(d.since)}부터 지금까지`));
    const small = (d.copy && d.copy.small) || (d.parent && d.parent.small);
    const out = [head];
    if (!d.count_only && d.curve) {
      const toPct = (xs) => (xs || []).map((v) => (v == null ? null : v * 100));
      out.push(h("div", {class: "acc-legend"}, h("span", {class: "acc-k cp"}, "━ 복제 (이 계좌)"), h("span", {class: "acc-k pa"}, "┅ 원본"),
        h("span", {class: "muted"}, "둘 다 복제 시작 때 잔고 = 0%")),
      ui.curves({series: [{values: toPct(d.curve.parent), cls: "lc", label: "원본"}, {values: toPct(d.curve.copy), cls: "ls", label: "복제"}],
        base: 0, height: 170, yfmt: (v) => `${fmt.num(v, Math.abs(v) < 10 ? 1 : 0, true)}%`,
        xlabels: [fmt.mmdd(d.since), null, "지금"], label: `원본과 복제의 같은 기간 수익률: 원본 ${fmt.pct(d.parent.ret, 1)}, 복제 ${fmt.pct(d.copy.ret, 1)}`}));
    }
    const rows = copyRows(d);
    out.push(h("div", {class: "tbl-wrap"}, h("table", {class: "tbl acc-tbl"},
      h("thead", null, h("tr", null, h("th", {class: "l"}, "같은 기간"), h("th", null, "원본"), h("th", null, "복제"))),
      h("tbody", null, rows.map((r) => h("tr", null, h("td", {class: "l"}, r.k),
        h("td", {class: ["num", r.tone ? fmt.tone(r.pv) : ""]}, r.parent),
        h("td", {class: ["num", r.tone ? fmt.tone(r.cv) : ""]}, r.copy)))))));
    if (!d.count_only && d.diff != null) {
      // the difference stays in the plain ink colour (no green / red): it is not a verdict on the changed rule
      out.push(h("p", {class: "acc-line"}, "같은 기간 복제 − 원본: ", h("b", {class: "num"}, pp(d.diff)), " · 판정 아님 ",
        small ? ui.smallSample(Math.min(d.copy.trades || 0, d.parent.trades || 0), d.small_n || 30) : null,
        small ? h("span", {class: "muted"}, ` 거래가 ${fmt.int(d.small_n || 30)}건 넘게 쌓여야 차이를 믿을 수 있습니다.`) : null));
    }
    if (!d.count_only && d.flips && d.flips.median_ret != null) {
      out.push(h("p", {class: "acc-line"}, ui.pill("", "ref"), ` 같은 기간 ${d.timeframe === "5m" ? "5분봉" : `${tf}봉`} 동전 봇 ${fmt.int(d.flips.n)}개 중앙값 `,
        h("b", {class: ["num", fmt.tone(d.flips.median_ret)]}, fmt.pct(d.flips.median_ret, 1)), " · 판정 아님"),
        ui.refNote(null, "복제 계좌는 시작하고 30일이 지난 뒤의 판정 날에 따로 판정합니다."));
    }
    out.push(h("p", {class: "note"}, "둘 다 복제가 시작한 뒤 끝난 거래만 셉니다 (원본이 그때 열어 둔 거래 하나는 들어갈 수 있음). 바꾼 규칙이 나았는지는 거래가 쌓인 뒤에 봅니다 (지금 차이는 판정이 아님)."),
      d.count_only ? h("p", {class: "note"}, ui.pill("딥시크는 개수만", "ref"), " 돈 숫자는 딥시크 묶음 화면에서 봅니다.")
        : ui.note("기간 수익률 = 복제 시작 때 잔고 대비 지금 잔고"));
    return out;
  }
  load();
  return el;
}
