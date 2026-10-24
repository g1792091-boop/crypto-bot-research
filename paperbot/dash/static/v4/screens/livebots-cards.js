// 실거래 › 거래: the loss card of a losing paper trade (livecheck.db loss_cards, made by the watcher a few minutes after the
// exit; /api/v4/livebots/trades sends it with the trade, and with a live trade the card of its paper partner). Opened in
// place under the trade: the cause label as a chip (실거래-페이퍼 차이 > 평소보다 큰 손실 > 연속 손실 N번째 > 백테스트에서도
// 약한 자리 > 정상 범위 손실, the watcher's own order), the trade against the backtest reference (its win rate, the unseen
// 2025-26 one, the usual and the worst loss, this regime and this coin), the place in the losing streak, the noise-stop
// check four hours after the exit (once known), what each executor did, and the card's own message behind 펼치기.
// HONESTY: the card's own fields only; what the card does not have is left out; a check not done yet says so.
import {h, ui, fmt} from "../core/pb.js";
import {acctTag, countKo} from "./livebots-kit.js";

/** The labels in the watcher's order (the server's `cards.kinds`; this copy only when an answer has none). */
export const KINDS = [{id: "gap", ko: "실거래-페이퍼 차이", tone: "bad"}, {id: "bigger", ko: "평소보다 큰 손실", tone: "bad"},
  {id: "streak", ko: "연속 손실", tone: "warn"}, {id: "weak", ko: "백테스트에서도 약한 자리", tone: "warn"},
  {id: "normal", ko: "정상 범위 손실", tone: "thin"}];
const toneOf = (kind, kinds = KINDS) => ((kinds || KINDS).find((k) => k.id === kind) || {tone: "thin"}).tone;

/** The cause label as a chip (its full words: '연속 손실 2번째'). */
export const cardChip = (c, kinds) => ui.pill(c.label || "판정 없음", ["lb-cchip", toneOf(c.kind, kinds)].join(" "), "손실 카드의 판정");

/** {id: count} of the loss cards among the rows (a card counted once), in the watcher's order: [{id, ko, tone, n}]. */
export function cardCounts(rows, kinds = KINDS) {
  const seen = new Set(), by = {};
  for (const r of rows || []) {
    const c = r && r.card;
    if (!c || seen.has(c.key)) continue;
    seen.add(c.key);
    by[c.kind] = (by[c.kind] || 0) + 1;
  }
  const out = (kinds || KINDS).filter((k) => by[k.id]).map((k) => ({...k, n: by[k.id]}));
  if (by.other) out.push({id: "other", ko: "기타", tone: "thin", n: by.other});
  return out;
}

const pc = (x, d = 1, sign = true) => (x == null ? "—" : fmt.pct(x, d, sign));
const bps = (x) => `${fmt.num(x, 1, true)}bps`;

/** One executor's line on the card: followed (its net ROE and its prices against the paper's), blocked by the light, or
 *  not followed (its own words). */
function execLine(o) {
  const st = o.status;
  const word = st === "followed" ? ["따라감", "good"] : st === "open" ? ["닫는 중", "thin"] : st === "blocked" ? ["신호등이 막음", "warn"]
    : st === "not_followed" ? ["안 따라감", "warn"] : ["기록 없음", "thin"];
  const kids = [];
  if (st === "followed") {
    kids.push(h("span", {class: ["num", fmt.tone(o.roe)]}, ` 순ROE ${pc(o.roe)}`));
    const px = [o.entry_bps != null ? `진입 ${bps(o.entry_bps)}` : null, o.exit_bps != null ? `청산 ${bps(o.exit_bps)}` : null].filter(Boolean);
    if (px.length) kids.push(h("span", {class: "muted"}, ` · 페이퍼 가격보다 ${px.join(" / ")} (+면 불리)`));
  } else if (st === "open") kids.push(h("span", {class: "muted"}, " 실거래 쪽은 아직 닫는 중이었어요"));
  else if (st === "blocked") kids.push(h("span", {class: "muted"}, " 신호등이 빨강이라 따라가지 않았어요"));
  else if (st === "not_followed") kids.push(h("span", {class: "muted lb-cwhy"}, o.why ? ` ${o.why}` : " 실행기 기록에 이유가 없어요"));
  else kids.push(h("span", {class: "muted"}, " 그때 실행기 기록을 못 읽었어요"));
  return h("li", {class: "lb-cex"}, acctTag(o.name || ""), ui.pill(word[0], word[1]), ...kids);
}

/** The noise-stop check: four hours after the exit, did the price come back to +11 % net ROE from the entry? */
export function noiseLine(n) {
  const s = (n && n.state) || "wait";
  if (s === "noise") return h("p", {class: "lb-cnoise warn-t"}, `노이즈 손절이었어요: 청산 뒤 4시간 안에 순ROE ${pc(n.roe)}까지 돌아갔어요`);
  if (s === "not") return h("p", {class: "lb-cnoise"}, `노이즈 손절은 아니에요${n.roe != null ? ` (4시간 안 최고 순ROE ${pc(n.roe)})` : ""}`);
  if (s === "unknown") return h("p", {class: "lb-cnoise muted"}, "노이즈 손절은 확인 못 했어요 (그때 1분봉 기록이 없어요)");
  if (s === "checking") return h("p", {class: "lb-cnoise muted"}, "노이즈 손절은 확인 중이에요");
  return h("p", {class: "lb-cnoise muted"}, "노이즈 손절은 청산 4시간 뒤에 확인해요");
}

/** cardBlock(card, {kinds, of}) -> the card opened under its trade. `of: "paper"`: shown under a live trade (the card is
 *  its paper partner's). */
export function cardBlock(c, o = {}) {
  const head = h("div", {class: "lb-chead"}, cardChip(c, o.kinds),
    h("b", null, `손실 카드 · ${c.strategy ? fmt.stratKo(c.strategy) : "매매법 모름"} ${c.tf ? fmt.tfKo(c.tf) : ""}`.trim()),
    c.member_order ? h("span", {class: "muted"}, `${fmt.int(c.member_order)}번 설정`) : null, c.type ? ui.pill(c.type, "thin") : null,
    o.of === "paper" ? h("span", {class: "muted"}, "페이퍼 거래의 카드") : null);
  const trade = [`순ROE ${pc(c.roe)}`, c.exit_ko || null, c.hold_ms != null ? `${fmt.dur(c.hold_ms / 1000)} 보유` : null,
    c.stop_type ? `손절 ${c.stop_type}${c.stop_dist != null ? `, 거리 ${fmt.pct(c.stop_dist, 2, false)}` : ""}` : null].filter(Boolean).join(" · ");
  const when = [c.reg5_ko ? `BTC 4시간 장세 ${c.reg5_ko}` : null, c.hour != null ? `진입 ${String(c.hour).padStart(2, "0")}시 (한국)` : null,
    c.mfe_roe != null && c.mfe_roe > 0 ? `먼저 순ROE ${pc(c.mfe_roe)}까지 갔어요` : null].filter(Boolean).join(" · ");
  const bt = [];
  if (c.fit_win != null) {
    bt.push(h("li", null, `백테스트 승률 ${pc(c.fit_win, 1, false)}`, c.honest ? ` · 처음 보는 2025-26 ${pc(c.honest[1], 0, false)} (${fmt.int(c.honest[0])}번)` : ""));
    if (c.loss_median != null && c.loss_worst != null) {
      bt.push(h("li", null, `손실은 보통 ${pc(c.loss_median, 0)}, 최악 ${pc(c.loss_worst, 0)}`,
        c.hours_median != null ? ` · 손절까지 보통 ${fmt.num(c.hours_median, 1)}시간` : "", c.bigger ? h("b", {class: "down"}, " → 최악보다 큰 손실") : ""));
    }
    const cells = [c.reg5_cell ? `이 장세 ${pc(c.reg5_cell[1], 0, false)} (${fmt.int(c.reg5_cell[0])}번)` : null,
      c.sym_cell ? `이 코인 ${pc(c.sym_cell[1], 0, false)} (${fmt.int(c.sym_cell[0])}번)` : null].filter(Boolean);
    if (cells.length) bt.push(h("li", null, cells.join(" · "), c.weak && c.weak.length ? h("b", {class: "warn-t"}, ` → 백테스트에서도 약한 자리 (${c.weak.join("·")})`) : ""));
  } else bt.push(h("li", {class: "muted"}, c.ref_ko || "백테스트 기준표에 이 매매법이 없어요 (비교 못 함)"));
  if (c.streak != null) {
    bt.push(h("li", null, `연속 손실 ${fmt.int(c.streak)}번째`, c.fit_longest != null ? ` (백테스트 최장 ${fmt.int(c.fit_longest)}번` : "",
      c.honest_longest != null ? `, 처음 보는 기간 ${fmt.int(c.honest_longest)}번)` : c.fit_longest != null ? ")" : ""));
  }
  const ex = (c.executors || []).length ? h("ul", {class: "lb-cexs"}, c.executors.map(execLine)) : h("p", {class: "note"}, "실행기 기록이 카드에 없어요");
  return h("div", {class: ["lb-lcard", c.kind || ""], role: "group", "aria-label": `손실 카드: ${c.label || ""}`},
    head,
    h("p", {class: "lb-cline num"}, trade),
    when ? h("p", {class: "lb-cline muted"}, when) : null,
    h("h4", {class: "lb-ch4"}, "백테스트와 비교"), h("ul", {class: "lb-cbt"}, bt),
    h("h4", {class: "lb-ch4"}, "노이즈 손절 (청산 뒤 4시간)"), noiseLine(c.noise),
    h("h4", {class: "lb-ch4"}, `실행기 ${countKo((c.executors || []).length)} 개`), ex,
    c.text ? ui.disclosure(c.sent ? "텔레그램으로 간 카드 글 보기" : "카드 글 보기", h("pre", {class: "lb-ctext"}, c.text)) : null);
}

/** The loss cards among the shown rows by label: '손실 카드 3장 · [정상 범위 손실 2] [연속 손실 1] · 10/15~10/19'. */
export function cardSummary(rows, kinds, src) {
  if (src && src.state && src.state !== "ok") return null;
  const counts = cardCounts(rows, kinds);
  const n = counts.reduce((s, k) => s + k.n, 0);
  const ts = (rows || []).map((r) => r.exit_time).filter((t) => t != null);
  const span = ts.length ? `${fmt.mmdd(Math.min(...ts))}~${fmt.mmdd(Math.max(...ts))}` : null;
  if (!n) return h("p", {class: "lb-csum muted"}, `손실 카드 없음${span ? ` · ${span}` : ""}`);
  return h("p", {class: "lb-csum"}, h("b", null, `손실 카드 ${fmt.int(n)}장`), span ? h("span", {class: "muted"}, ` · ${span}`) : null,
    ...counts.map((k) => ui.pill(`${k.ko} ${fmt.int(k.n)}`, k.tone)));
}
