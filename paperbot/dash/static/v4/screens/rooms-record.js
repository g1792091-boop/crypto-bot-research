// 에이전트 방 · before a strategy room's first meeting (fill-people): what the strategy itself is really doing, from
// the code's records (/api/v4/people/strats and /api/v4/people/strat, read-only over paper3.db; /api/board for the
// open positions). The 36 only (their rooms); P&L of the 36 may show (CONTRACT §1: only DeepSeek / coin flips are
// counted-only).
import {h, put, fmt, store} from "../core/pb.js";

const TF = ["15m", "30m", "1h", "4h"];

/** The strategy behind a room id ("strat:V4.3_TREND" -> "V4.3_TREND"); null for a team room. */
export const stratOf = (id, r) => (r && r.strategy) || (String(id || "").startsWith("strat:") ? String(id).slice(6) : null);

/** One plain line for a trade: "1시간 LTC 롱 익절 잠금 +15%". */
export function tradeKo(t) {
  if (!t) return "";
  return [fmt.tfKo(t.timeframe), fmt.coin(t.symbol), t.side ? fmt.sideKo(t.side) : null, fmt.reasonKo(t.exit_reason), fmt.pct(t.roe, 0)].filter(Boolean).join(" ");
}
/** One plain line for a signal: "30분 BTC 롱 신호 (진입 신호)". */
export function signalKo(s) {
  if (!s) return "";
  return `${fmt.tfKo(s.timeframe)} ${fmt.coin(s.symbol)} ${Number(s.side) > 0 ? "롱" : "숏"} 신호 (${s.status_ko || s.status})`;
}

/** The list line of a strategy room with no meeting yet: its newest real event (closed trade or signal) or null. */
export function latestEventKo(x) {
  if (!x) return null;
  const t = x.trade, s = x.signal;
  const tt = t ? t.exit_time : 0, st = s ? s.bar_close : 0;
  if (!tt && !st) return null;
  return tt >= st ? {ts: tt, text: `최근 거래 · ${tradeKo(t)}`} : {ts: st, text: `최근 ${signalKo(s)}`};
}

/** The code record box of a strategy room (filled once its data arrives). */
export function recordBox(ctx, name) {
  const body = h("div", {class: "rm-rec-body"}, h("p", {class: "muted"}, "코드 기록 불러오는 중"));
  const box = h("section", {class: "rm-rec", "aria-label": "코드 기록"},
    h("div", {class: "rm-rec-h"}, h("b", null, "코드 기록"), h("span", {class: "muted"}, `${name} · 회의 전에도 매매법은 돌고 있습니다`)), body);
  ctx.api(`/api/v4/people/strat?name=${encodeURIComponent(name)}`).then((d) => {
    if (!ctx.alive()) return;
    const b = store.get("board");
    const open = ((b && b.accounts) || []).filter((a) => a.kind === "strategy" && a.strategy === name && a.position);
    const today = d.today || {};
    const tfs = TF.map((tf) => {
      const x = today[tf];
      return h("div", {class: "rm-rec-tf"}, h("span", null, fmt.tfKo(tf)), h("b", {class: "num"}, `${fmt.int(x ? x.n : 0)}건`),
        h("small", {class: x && x.n ? fmt.tone(x.pnl) : "muted"}, x && x.n ? `${fmt.int(x.wins)}승 ${fmt.int(x.n - x.wins)}패 · ${fmt.usdt(x.pnl, true)}` : "아직 없음"));
    });
    put(body,
      h("p", {class: "rm-rec-k"}, "오늘 닫힌 거래 (한국 0시부터) · 모두 ", h("b", null, `${fmt.int(d.closed || 0)}건`)),
      h("div", {class: "rm-rec-tfs"}, tfs),
      h("p", {class: "rm-rec-k"}, "지금 열린 포지션"),
      open.length ? h("ul", {class: "rm-rec-ul"}, open.map((a) => h("li", null, h("a", {href: ctx.href("account", a.account_id)},
        `${fmt.tfKo(a.timeframe)} ${fmt.coin(a.position.symbol)} ${fmt.sideKo(a.position.side)} ${fmt.lev(a.position.leverage)}`))))
        : h("p", {class: "muted"}, "없음"),
      h("p", {class: "rm-rec-k"}, "최근 거래"),
      (d.trades || []).length ? h("ul", {class: "rm-rec-ul"}, d.trades.slice(0, 4).map((t) => h("li", null, h("time", null, fmt.hm(t.exit_time)), " ",
        h("span", {class: fmt.tone(t.roe)}, tradeKo(t))))) : h("p", {class: "muted"}, "아직 없음"),
      h("p", {class: "rm-rec-k"}, "최근 신호"),
      (d.signals || []).length ? h("ul", {class: "rm-rec-ul"}, d.signals.slice(0, 4).map((s) => h("li", null, h("time", null, fmt.hm(s.bar_close)), " ", signalKo(s))))
        : h("p", {class: "muted"}, Array.isArray(d.signals) ? "아직 없음" : "수집 전"),      // 수집 전 only when the source is missing
      h("p", {class: "muted rm-rec-foot"}, `코드가 기록한 그대로 · ${d.computed_at ? fmt.hm(d.computed_at) : ""} 기준 · 모의 계좌`));
  }).catch((e) => { if (!(e && e.name === "AbortError")) put(body, h("p", {class: "muted"}, "코드 기록을 불러오지 못했습니다")); });
  return box;
}
