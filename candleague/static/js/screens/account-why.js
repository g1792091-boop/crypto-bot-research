// 계좌 자세히 › '왜 이 수익률인가' card, copied and adapted from the rule bot's v4 account-why.js (nothing imported from it). Built only from
// the account's closed trades the screen already loads (/api/trades/<id>, the newest 200) and the snapshot's wallet numbers:
//   ① where the return stands: start (the snapshot's equity0) → now
//   ② by exit reason: count, money and the mean 증거금 대비 (손절 · 계단 잠금 · 규칙 청산 · 익절 · 강제청산)
//   ③ the win rate against the win rate the average win and average loss need to break even
//   ④ the three biggest losses with their share of all losses, each with its 거래 다시보기
// HONESTY: money only where the server sent it (a hidden DeepSeek account gets the counts only); a missing number reads "—", never 0;
// under 30 closed trades the card says 표본 적음; the league's trade record keeps the net result only (no fee / funding split), so there is
// no fee waterfall and the card says so. Read-only; every string reaches the page as a text node.
import {h} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as LK from "../lk.js";
import {reasonKo, coinOf, coinShort, sideKo} from "../labels.js";
import {replayHref} from "../why.js";

export const SMALL = 30;                                    // 표본 적음 below the checkpoints' own floor
const ORDER = ["SL", "LOCK", "RULE", "TP", "LIQ"];
const fin = (x) => x != null && x !== "" && typeof x !== "boolean" && Number.isFinite(Number(x));
const BIG = 3;

/** The card's numbers from closed trades (pure, no DOM). o: {start (equity0), wallet (the snapshot's, or null), total (the account's closed
 *  trade count from the snapshot), hidden (the server sent no money: counts only)}. */
export function whyStats(trades, o = {}) {
  const rows = (trades || []).filter((t) => t && typeof t === "object");
  const n = rows.length;
  const money = !o.hidden && rows.some((t) => fin(t.pnl));
  const priced = money ? rows.filter((t) => fin(t.pnl)) : [];
  const wins = priced.filter((t) => Number(t.pnl) > 0), losses = priced.filter((t) => Number(t.pnl) < 0);
  const avgWin = wins.length ? wins.reduce((s, t) => s + Number(t.pnl), 0) / wins.length : null;
  const avgLoss = losses.length ? -losses.reduce((s, t) => s + Number(t.pnl), 0) / losses.length : null;
  const by = new Map();
  for (const t of rows) {
    const k = String(t.exit_reason || "?");
    const r = by.get(k) || {reason: k, n: 0, pnl: 0, pn: 0, roe: 0, rn: 0};
    r.n += 1;
    if (money && fin(t.pnl)) { r.pnl += Number(t.pnl); r.pn += 1; }
    if (money && fin(t.roe)) { r.roe += Number(t.roe); r.rn += 1; }
    by.set(k, r);
  }
  const rank = (k) => (ORDER.indexOf(k) >= 0 ? ORDER.indexOf(k) : 99);
  const byReason = [...by.values()].sort((a, b) => rank(a.reason) - rank(b.reason) || b.n - a.n)
    .map((r) => ({reason: r.reason, n: r.n, pnl: r.pn ? r.pnl : null, roe: r.rn ? r.roe / r.rn : null}));
  const lossSum = -losses.reduce((s, t) => s + Number(t.pnl), 0);
  const big = [...losses].sort((a, b) => Number(a.pnl) - Number(b.pnl)).slice(0, BIG);
  const bigSum = -big.reduce((s, t) => s + Number(t.pnl), 0);
  const start = fin(o.start) && Number(o.start) > 0 ? Number(o.start) : null;
  const wallet = fin(o.wallet) ? Number(o.wallet) : null;
  const total = fin(o.total) && Number(o.total) > n ? Number(o.total) : n;
  return {n, total, capped: total > n, money, nPriced: priced.length, wins: wins.length, losses: losses.length,
    winRate: priced.length ? wins.length / priced.length : null, avgWin, avgLoss,
    breakeven: avgWin != null && avgLoss != null && avgWin + avgLoss > 0 ? avgLoss / (avgWin + avgLoss) : null,
    byReason, big, bigShare: lossSum > 0 ? bigSum / lossSum : null, start, wallet,
    ret: start != null && wallet != null ? wallet / start - 1 : null, small: n < SMALL};
}

const signed = (x) => (fin(x) ? fmt.money(x, true) : "—");

/** The card. a: the account row; book: /api/trades/<id>'s answer (or null when it failed); returns a card element. */
export function whyCard(a, book, o = {}) {
  const hidden = !!o.hidden;
  const plate = "왜 이 수익률인가";
  if (!book) return ui.card({plate}, ui.none("거래 기록을 불러오지 못했습니다 (잠시 뒤 다시)"));
  const s = whyStats(book.trades, {start: o.start, wallet: a.wallet, total: a.trades, hidden});
  if (!s.n) return ui.card({plate, sub: "이 계좌의 닫힌 거래로만 계산"}, ui.empty("아직 닫힌 거래가 없습니다 · 첫 거래가 끝나면 이유가 채워집니다"));
  const kids = [];
  const capNote = s.capped ? h("p", {class: "note"}, `서버가 최근 ${fmt.int(s.n)}번까지만 보냅니다 (전체 ${fmt.int(s.total)}번 중) · 잔고와 수익률은 전체 기준`) : null;
  // ① where the return stands
  kids.push(h("div", {class: "rp-wy-sec"}, h("p", {class: "rp-wy-k"}, "지금 어디까지 왔나"),
    h("p", {class: "rp-wy-big"}, h("span", {class: "num"}, s.start == null ? "—" : fmt.money(s.start, false)), " → ",
      hidden && s.wallet == null ? h("b", {class: "muted"}, "숨김")
        : h("b", {class: ["num", fmt.tone(s.ret)]}, s.wallet == null ? "—" : fmt.money(s.wallet, false)),
      s.ret != null ? h("span", {class: ["num", fmt.tone(s.ret)]}, ` (${fmt.pct(s.ret * 100, true, 1)})`) : null),
    h("p", {class: "note"}, "시작 잔고에서 닫힌 거래가 쌓인 지금 잔고까지입니다 (열린 포지션의 평가손익은 빠짐).")));
  // ② by exit reason
  kids.push(h("div", {class: "rp-wy-sec"}, h("p", {class: "rp-wy-k"}, "나간 이유별"),
    h("div", {class: "rp-wy-chips"}, s.byReason.map((r) => h("span", {class: ["rp-wy-chip", r.reason === "LIQ" ? "bad" : ""],
      title: `${reasonKo(r.reason)} ${fmt.int(r.n)}번${s.money && r.pnl != null ? ` · 합계 ${signed(r.pnl)}` : ""}`},
    `${reasonKo(r.reason)} ${fmt.int(r.n)}번`,
    s.money ? [" ", h("b", {class: ["num", fmt.tone(r.pnl)]}, r.pnl == null ? "—" : signed(r.pnl)),
      h("span", {class: ["num", fmt.tone(r.roe)]}, ` · 평균 증거금 대비 ${r.roe == null ? "—" : fmt.pct(r.roe * 100, true, 1)}`)] : null))),
    s.money ? null : h("p", {class: "note"}, "딥시크 금액 숨김 설정이라 나간 이유의 개수만 보여 드립니다.")));
  if (s.money) {
    // ③ win rate vs the rate the average win / loss needs to break even
    const wr = s.winRate, be = s.breakeven;
    kids.push(h("div", {class: "rp-wy-sec"}, h("p", {class: "rp-wy-k"}, "이긴 비율과 본전에 필요한 비율"),
      h("p", {class: "rp-wy-line"}, "이긴 비율 ", h("b", {class: "num"}, wr == null ? "—" : fmt.pct(wr * 100, false, 0)),
        " · 본전에 필요한 비율 ", h("b", {class: "num"}, be == null ? "—" : fmt.pct(be * 100, false, 0)), " ", LK.smallN(s.n, SMALL)),
      be != null ? h("div", {class: "rp-wy-wr", role: "img", "aria-label": `이긴 비율 ${fmt.pct(wr * 100, false, 0)}, 본전에 필요한 비율 ${fmt.pct(be * 100, false, 0)}`},
        h("i", {class: ["rp-wy-bar", wr >= be ? "up" : "down"], style: {width: `${(Math.max(0, Math.min(1, wr)) * 100).toFixed(1)}%`}}),
        h("i", {class: "rp-wy-mark", style: {left: `${(Math.max(0, Math.min(1, be)) * 100).toFixed(1)}%`}, title: "본전에 필요한 비율"})) : null,
      h("p", {class: "note"}, s.avgWin != null && s.avgLoss != null
        ? `평균 이익 ${signed(s.avgWin)} · 평균 손실 ${signed(-s.avgLoss)}: 한 번 질 때 잃는 돈이 이길 때 버는 돈의 ${fmt.num(s.avgLoss / (s.avgWin || 1), 1)}배라 ${fmt.pct(be * 100, false, 0)} 넘게 이겨야 본전입니다.`
        : s.wins ? "아직 진 거래가 없어 본전에 필요한 비율을 계산하지 않았습니다." : "아직 이긴 거래가 없어 본전에 필요한 비율을 계산하지 않았습니다.")));
    // ④ the biggest losses
    if (s.big.length) {
      kids.push(h("div", {class: "rp-wy-sec"}, h("p", {class: "rp-wy-k"}, `가장 큰 손실 ${fmt.int(s.big.length)}번이 전체 손실의 `, h("b", {class: "num"}, s.bigShare == null ? "—" : fmt.pct(s.bigShare * 100, false, 0))),
        h("div", {class: "rp-wy-big3", role: "list"}, s.big.map((t) => h("div", {class: "rp-wy-brow", role: "listitem"},
          h("span", {class: "rp-wy-bt"}, fmt.kst(t.exit_time)), h("span", null, `${coinShort(coinOf(t.symbol))} ${sideKo(t.side)} · ${reasonKo(t.exit_reason)}`),
          h("b", {class: "num down"}, signed(t.pnl)),
          t.entry_time != null ? h("a", {class: "btn-line sm", href: replayHref(a.id, t.entry_time), title: "이 거래를 봉 하나씩 다시 보기"}, "▶ 다시보기") : null)))));
    }
  }
  return ui.card({plate, sub: `닫힌 거래 ${fmt.int(s.n)}번으로 계산 ${s.small ? "· 표본 적음" : ""}`.trim(), cls: "rp-why"}, kids, capNote,
    h("p", {class: "note"}, "후보 리그의 거래 기록은 수수료·펀딩을 나누지 않고 순손익만 남깁니다. 그래서 수수료 폭포는 그리지 않습니다. 거래 한 건이나 표본이 적은 숫자로 매매법이 좋다·나쁘다를 말할 수 없습니다."));
}
