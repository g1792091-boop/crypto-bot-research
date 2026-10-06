// 계좌 · '왜 이 수익률인가' card (review addition 3: "이 계좌 왜 −90%야?" answered on one card, under the profile).
// Everything comes from the account's own closed trades (/api/account/<id>: pnl, fees, funding, exit_reason) and the
// board (wallet, the same-timeframe coin flips' median wallet); nothing new is asked of the server:
//   ① where the return stands: start → now, and the same-timeframe coin flips' median as 참고 (the 36 and the reel only)
//   ② a waterfall: the closed trades before costs → fees → funding → what they really made (pnl = before − fees − funding)
//   ③ by exit reason: count and money (손절 / 익절 잠금 / 강제청산 …)
//   ④ win rate vs the rate the average win / loss needs to break even
//   ⑤ the biggest three losses, their share of all losses, each with its replay (and the meeting about it, when one
//      stored its trade id: account-links.js)
// HONESTY: DeepSeek accounts get exit-reason COUNTS only (no money, owners' D10 / D11, CONTRACT §1.3), coin flips are
// the yardstick (no comparison with themselves), extra accounts are counted apart (no coin-flip line); the trades are
// the server's latest 500 at most, and the card says so when the account has more; small samples say so.
import {h, ui, fmt} from "../core/pb.js";

const ORDER = ["SL", "LOCK", "LIQ", "TP", "BAND", "TIME", "END"];
const num = (x) => (Number.isFinite(Number(x)) ? Number(x) : 0);

/**
 * The card's numbers from closed trades (pure, no DOM). o: {initial, wallet, flipMed (the same-timeframe coin flips'
 * median wallet or null), total (the account's real number of closed trades, from the board)}.
 */
export function whyStats(trades, o = {}) {
  const rows = (trades || []).filter((t) => t && Number.isFinite(Number(t.pnl)));
  const n = rows.length;
  const net = rows.reduce((s, t) => s + num(t.pnl), 0);
  const fees = rows.reduce((s, t) => s + num(t.fees), 0);
  const funding = rows.reduce((s, t) => s + num(t.funding), 0);      // paid > 0 (engine: net = gross − fees − funding)
  const gross = net + fees + funding;
  const wins = rows.filter((t) => num(t.pnl) > 0), losses = rows.filter((t) => num(t.pnl) < 0);
  const avgWin = wins.length ? wins.reduce((s, t) => s + num(t.pnl), 0) / wins.length : null;
  const avgLoss = losses.length ? -losses.reduce((s, t) => s + num(t.pnl), 0) / losses.length : null;
  const breakeven = avgWin != null && avgLoss != null && avgWin + avgLoss > 0 ? avgLoss / (avgWin + avgLoss) : null;
  const by = new Map();
  for (const t of rows) {
    const k = String(t.exit_reason || "?");
    const r = by.get(k) || {reason: k, n: 0, pnl: 0};
    r.n += 1; r.pnl += num(t.pnl);
    by.set(k, r);
  }
  const byReason = [...by.values()].sort((a, b) => (ORDER.indexOf(a.reason) + 1 || 99) - (ORDER.indexOf(b.reason) + 1 || 99) || b.n - a.n);
  const lossSum = -losses.reduce((s, t) => s + num(t.pnl), 0);
  const big = [...losses].sort((a, b) => num(a.pnl) - num(b.pnl)).slice(0, 3);
  const bigSum = -big.reduce((s, t) => s + num(t.pnl), 0);
  const init = num(o.initial) || 5000;
  const ret = o.wallet != null && Number.isFinite(Number(o.wallet)) ? Number(o.wallet) / init - 1 : null;
  const flipRet = o.flipMed != null && Number.isFinite(Number(o.flipMed)) ? Number(o.flipMed) / init - 1 : null;
  const total = o.total != null && Number(o.total) > n ? Number(o.total) : n;
  return {n, total, capped: total > n, wins: wins.length, losses: losses.length, winRate: n ? wins.length / n : null,
    avgWin, avgLoss, breakeven, gross, fees, funding, net, byReason, big, bigShare: lossSum > 0 ? bigSum / lossSum : null,
    lossSum, ret, flipRet, rest: ret != null && flipRet != null ? ret - flipRet : null, initial: init,
    wallet: o.wallet != null ? Number(o.wallet) : null};
}

/** The waterfall's steps: [{key, label, from, to}] in money (from → to), the last one the real result. */
export function waterfall(s) {
  const a = s.gross, b = a - s.fees, c = b - s.funding;
  return [{key: "gross", label: "수수료·펀딩 전", from: 0, to: a}, {key: "fees", label: "수수료", from: a, to: b},
    {key: "funding", label: s.funding >= 0 ? "펀딩 (낸 것)" : "펀딩 (받은 것)", from: b, to: c},
    {key: "net", label: "실제 손익", from: 0, to: c}];
}

const signed = (x) => fmt.money(x, true);

function fallRow(st, lo, hi) {
  const span = hi - lo || 1, x0 = (Math.min(st.from, st.to) - lo) / span, x1 = (Math.max(st.from, st.to) - lo) / span;
  const d = st.to - st.from;
  const tone = st.key === "gross" || st.key === "net" ? fmt.tone(st.to) : d < 0 ? "cost" : "gain";
  const val = st.key === "gross" || st.key === "net" ? signed(st.to) : signed(d);
  return h("div", {class: "acw-frow", title: `${st.label} ${val} USDT`},
    h("span", {class: "acw-fk"}, st.label),
    h("span", {class: "acw-ftrack"}, h("i", {class: ["acw-fbar", tone], style: {left: (x0 * 100).toFixed(2) + "%", width: Math.max(0.6, (x1 - x0) * 100).toFixed(2) + "%"}}),
      lo < 0 && hi > 0 ? h("i", {class: "acw-fzero", style: {left: ((-lo / span) * 100).toFixed(2) + "%"}}) : null),
    h("b", {class: ["acw-fv", "num", st.key === "gross" || st.key === "net" ? fmt.tone(st.to) : ""]}, val));
}

/**
 * The card. a: the account row (kind, timeframe, group), d: /api/account answer, o: {initial, wallet, flipMed, total,
 * href (ctx.href), countOnly (DeepSeek), links: {trade id: [meeting]} (account-links.js; optional), linkChip(meeting)}.
 */
export function whyCard(a, d, o = {}) {
  const trades = (d && d.trades) || [];
  const s = whyStats(trades, o);
  const plate = s.ret != null && !o.countOnly ? `왜 ${fmt.pct(s.ret, 1)}인가` : "왜 이 결과인가";
  if (!s.n) return ui.card({plate, cls: "acw"}, ui.empty("아직 닫힌 거래가 없습니다 · 첫 거래가 끝나면 이유가 채워집니다"));
  const capNote = s.capped ? h("p", {class: "note"}, `최근 ${fmt.int(s.n)}건 기준 (전체 ${fmt.int(s.total)}건 중) · 잔고와 수익률은 전체 기준`) : null;
  if (o.countOnly) {
    // DeepSeek: exit-reason counts only (no money, no comparison: owners' D10 / D11)
    return ui.card({plate: "나간 이유", cls: "acw", sub: `닫힌 거래 ${fmt.int(s.n)}건`},
      h("div", {class: "acw-reasons"}, s.byReason.map((r) => h("span", {class: ["acw-chip", r.reason === "LIQ" ? "bad" : ""]},
        `${fmt.reasonKo(r.reason)} `, h("b", {class: "num"}, `${fmt.int(r.n)}건`)))),
      // (the profile card right above already says "딥시크는 여기서 개수만" and the win count: not repeated here)
      capNote);
  }
  const kids = [], secs = [];
  // ① where it stands
  const flipOk = s.flipRet != null && a.kind !== "random" && fmt.groupOf(a) !== "extra" && fmt.groupOf(a) !== "ds";
  kids.push(h("div", {class: "acw-head"},
    h("p", {class: "acw-big"}, h("span", {class: "num"}, fmt.money(s.initial)), " → ", h("b", {class: ["num", fmt.tone(s.ret)]}, s.wallet == null ? "—" : fmt.money(s.wallet)),
      s.ret != null ? h("span", {class: ["num", fmt.tone(s.ret)]}, ` (${fmt.pct(s.ret, 1)})`) : null),
    flipOk ? h("p", {class: "acw-line"}, ui.pill("", "ref"), ` 같은 ${a.timeframe === "5m" ? "5분봉 동전 3개" : `${fmt.tfKo(a.timeframe)}봉 동전 봇`} 중앙값 `,
      h("b", {class: ["num", fmt.tone(s.flipRet)]}, fmt.pct(s.flipRet, 1)), " (같은 시장·같은 청산 규칙으로 방향만 동전으로 정한 계좌) · 이 계좌와의 차이 ",
      h("b", {class: "num"}, `${fmt.num(s.rest * 100, 1, true)}%p`), " · 판정 아님") : null,
    a.kind === "random" ? h("p", {class: "acw-line"}, "이 계좌가 동전 봇(비교 기준)입니다. 방향을 동전으로 정해도 이만큼 움직였다는 기준선입니다.") : null));
  // ② the waterfall
  const steps = waterfall(s);
  const vals = steps.flatMap((x) => [x.from, x.to]);
  const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
  secs.push(h("div", {class: "acw-sec"}, h("p", {class: "acw-k"}, "닫힌 거래의 손익이 어디로 갔나"),
    h("div", {class: "acw-fall", role: "img", "aria-label": steps.map((x) => `${x.label} ${fmt.money(x.key === "gross" || x.key === "net" ? x.to : x.to - x.from, true)}`).join(", ")},
      steps.map((x) => fallRow(x, lo, hi))),
    h("p", {class: "note"}, `수수료는 ${fmt.int(s.n)}건 모두에서, 펀딩은 8시간마다 열린 포지션에서 나갑니다 (받은 펀딩은 +).`)));
  // ③ by exit reason
  secs.push(h("div", {class: "acw-sec"}, h("p", {class: "acw-k"}, "나간 이유별"),
    h("div", {class: "acw-reasons"}, s.byReason.map((r) => h("span", {class: ["acw-chip", r.reason === "LIQ" ? "bad" : ""], title: `${fmt.reasonKo(r.reason)} ${fmt.int(r.n)}건 합계 ${signed(r.pnl)} USDT`},
      `${fmt.reasonKo(r.reason)} ${fmt.int(r.n)}건 `, h("b", {class: ["num", fmt.tone(r.pnl)]}, signed(r.pnl)))))));
  // ④ win rate vs the break-even rate
  const wr = s.winRate, be = s.breakeven;
  secs.push(h("div", {class: "acw-sec"}, h("p", {class: "acw-k"}, "이긴 비율과 본전에 필요한 비율"),
    h("p", {class: "acw-line"}, "이긴 비율 ", h("b", {class: "num"}, fmt.pct(wr, 0, false)),
      be != null ? [" · 본전에 필요한 비율 ", h("b", {class: "num"}, fmt.pct(be, 0, false))] : null, " ", ui.smallSample(s.n)),
    be != null ? h("div", {class: "acw-wr", role: "img", "aria-label": `이긴 비율 ${fmt.pct(wr, 0, false)}, 본전에 필요한 비율 ${fmt.pct(be, 0, false)}`},
      h("i", {class: ["acw-wrbar", wr >= be ? "up" : "down"], style: {width: (Math.max(0, Math.min(1, wr)) * 100).toFixed(1) + "%"}}),
      h("i", {class: "acw-wrmark", style: {left: (Math.max(0, Math.min(1, be)) * 100).toFixed(1) + "%"}, title: "본전에 필요한 비율"})) : null,
    h("p", {class: "note"}, s.avgWin != null && s.avgLoss != null
      ? `평균 이익 ${signed(s.avgWin)} · 평균 손실 ${signed(-s.avgLoss)}: 한 번 질 때 잃는 돈이 이길 때 버는 돈의 ${fmt.num(s.avgLoss / (s.avgWin || 1), 1)}배라 ${fmt.pct(be, 0, false)}는 이겨야 본전입니다.`
      : s.wins ? "아직 진 거래가 없습니다." : "아직 이긴 거래가 없습니다.")));
  // ⑤ the biggest losses
  if (s.big.length) {
    const links = o.links || {};
    secs.push(h("div", {class: "acw-sec"}, h("p", {class: "acw-k"}, `가장 큰 손실 ${fmt.int(s.big.length)}건이 전체 손실의 `, h("b", {class: "num"}, fmt.pct(s.bigShare, 0, false))),
      h("div", {class: "acw-big3", role: "list"}, s.big.map((t) => h("div", {class: "acw-brow", role: "listitem"},
        h("span", {class: "acw-bt"}, fmt.kst(t.exit_time)), h("span", null, `${fmt.coin(t.symbol)} ${fmt.reasonKo(t.exit_reason)}`),
        h("b", {class: "num down"}, signed(t.pnl)),
        o.href && t.id != null ? h("a", {class: "acw-replay", href: o.href("replay", String(t.id)), title: "이 거래를 봉 차트에서 다시 보기"}, "▶ 다시보기") : null,
        o.linkChip && links[t.id] && links[t.id].length ? o.linkChip(links[t.id][0]) : null)))));
  }
  kids.push(h("div", {class: "acw-body"}, secs));
  return ui.card({plate, cls: "acw", sub: `닫힌 거래 ${fmt.int(s.n)}건으로 계산`}, kids, capNote, ui.assume("closed", "거래마다 나갈 때 수수료·펀딩 뒤"));
}
