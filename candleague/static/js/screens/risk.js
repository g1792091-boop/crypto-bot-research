// #/risk 위험 점검 (owners 10/13): the owners want a low drawdown at 20-50x leverage. The loss autopsy says the real tail risk is not one bad trade
// but many positions on the SAME side of correlated coins (five or six coins on one side all lose 13.5% of the time against 0.5% if they were
// independent). This screen only COUNTS: it never says what to do and never passes or fails anything.
// Top to bottom: what this screen is (always, even before the data exists), one sentence from the server (counts only), then three compact cards
// per account kind: 쏠림 지금 (the open positions: long vs short as a two-colour bar with both numbers written, the largest same-side cluster, the
// margin used and what every open stop would cost at once, as separate wallets and as ONE shared wallet), 지금까지 가장 나빴던 것 (the worst closed
// trade against its wallet, the longest losing streak, the drawdown, forced liquidations, the share ended by the stop) and 같은 방향이 몰린 날 (the
// share of days when the day's entries were >= 80% one side). A table (cards on a phone), a word list for beginners and the limits.
// Data: the snapshot's ``risk`` (candleague/riskview.py risk_views, next to ``decision`` in the owner-exit league).
// HONESTY: every number carries its n; a flag is always a WORD (never colour alone); every number may be null and then reads "—", never 0; the
// sentence and the limits come from the server; money is shown against ``equity0`` of the snapshot, never a typed-in wallet; DeepSeek money is left
// out of the figures unless the money switch is on (the server does that, a note says so).
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {eunNeun, hasLineup, notReady, oldLeagueBox} from "./pairs.js";
import {pc, startTxt} from "./versus.js";

export const css = ["scr/kinds.css", "scr/risk.css"];

export const DEFAULTS = {same_side: 0.8, min_open: 10, min_day_trades: 10};
/** The rules as the server writes them (candleague/riskview.risk_rules_ko, same order and words); used when the snapshot has none. */
export const RULES_DEFAULT = [
  "무엇을 보여 주나: 포지션이 한쪽 방향에 몰려 있는지, 지금까지 가장 나빴던 일이 얼마였는지를 숫자로만 보여 줍니다. 무엇을 하라는 말은 없습니다.",
  `쏠림 표시: 열린 포지션이 ${DEFAULTS.min_open}개 이상이고 그중 ${Math.round(DEFAULTS.same_side * 100)}% 이상이 같은 방향(롱 또는 숏)이면 표시합니다.`,
  "한 지갑이면: 계좌는 모두 따로인 모의 지갑입니다. ‘한 지갑이면’은 같은 포지션들을 지갑 하나에 모두 담았다고 가정한 계산입니다.",
  "가장 나빴던 것: 닫힌 거래만으로 셉니다 (지갑 대비 한 거래 최악 · 연속으로 진 횟수 · 낙폭 · 강제청산). 열려 있는 거래의 평가손익은 들어 있지 않습니다.",
  `같은 방향이 몰린 날: 그날 들어간 거래가 ${DEFAULTS.min_day_trades}건 이상이고 ${Math.round(DEFAULTS.same_side * 100)}% 이상이 같은 방향인 날의 비율입니다 (UTC 날짜 기준).`,
  "모든 숫자 옆에 거래 수나 계좌 수를 같이 씁니다. 적으면 우연일 수 있습니다.",
];

const num = (x) => (fmt.bad(x) ? null : Number(x));
const obj = (x) => (x && typeof x === "object" && !Array.isArray(x) ? x : {});
const SIDE_KO = {1: "롱", "-1": "숏"};
/** Big fractions as words people can read: 4.73 -> "473%" (one decimal under 100%). */
const P = (f, sign = false) => (num(f) == null ? "—" : Math.abs(Number(f)) >= 1 ? pc(f, sign, 0) : pc(f, sign));
/** "지갑의 4.7배" for a share of one wallet at or over 100%, "" otherwise. */
const times = (f) => (num(f) != null && Math.abs(Number(f)) >= 1 ? `지갑의 ${fmt.num(Math.abs(Number(f)), 1)}배` : "");

// ---------------------------------------------------------------- the snapshot's ``risk``
/** The risk block with every missing part empty; null when it is absent or malformed. */
export function normRisk(x) {
  if (!x || typeof x !== "object" || Array.isArray(x) || !Array.isArray(x.kinds)) return null;
  const t = obj(x.thresholds);
  return {
    equity0: num(x.equity0), dsIn: x.ds_in_stats === true,
    thr: {same_side: num(t.same_side) ?? DEFAULTS.same_side, min_open: num(t.min_open) ?? DEFAULTS.min_open, min_day_trades: num(t.min_day_trades) ?? DEFAULTS.min_day_trades},
    headline: typeof x.headline_ko === "string" ? x.headline_ko : "",
    rules: Array.isArray(x.rules_ko) && x.rules_ko.length ? x.rules_ko.map(String) : null,
    notes: Array.isArray(x.note_ko) ? x.note_ko.map(String) : [],
    kinds: x.kinds.filter((k) => k && typeof k === "object").map((k) => ({...k, now: obj(k.now), worst: obj(k.worst), days: obj(k.days)})),
  };
}
/** What the screen can show: {state, R}.  wait  no snapshot yet   old  the old league (no lineup): this screen is for the new one
 *  prep  the new league, the engine has not written ``risk`` (or it has no kind yet)   ok  the risk block is here */
export function gate(d) {
  if (!d || !d.accounts) return {state: "wait", R: null};
  const R = normRisk(d.risk);
  if (R && R.kinds.length) return {state: "ok", R};
  return {state: hasLineup(d) ? "prep" : "old", R: null};
}

// ---------------------------------------------------------------- pieces
const nameOf = (k) => String(k.name_ko || k.short_ko || k.label_ko || k.role || "—");
const sideWord = (s) => SIDE_KO[String(Number(s))] || "—";
const cnt = (n, unit) => (num(n) == null ? "—" : `${fmt.int(n)}${unit}`);

/** The two-colour bar: long (--up) and short (--down) with both numbers written inside the segments (when wide enough) and in ``aria-label``. */
export function sideBar(lg, sh, unit = "개", words = ["롱", "숏"]) {
  const a = Math.max(0, num(lg) ?? 0), b = Math.max(0, num(sh) ?? 0), t = a + b;
  if (!(t > 0)) return h("span", {class: "rv-bar none", role: "img", "aria-label": `${words[0]} 0${unit}, ${words[1]} 0${unit}`});
  const seg = (n, cls, w) => (n > 0 ? h("i", {class: cls, style: {flex: `${n} 1 0`}}, n / t >= 0.2 ? `${w} ${fmt.int(n)}` : null) : null);
  return h("span", {class: "rv-bar", role: "img", "aria-label": `${words[0]} ${fmt.int(a)}${unit}, ${words[1]} ${fmt.int(b)}${unit}`},
    seg(a, "rv-l", words[0]), seg(b, "rv-s", words[1]));
}
const splitTxt = (a, b, unit = "", words = ["롱", "숏"]) => `${words[0]} ${cnt(a, unit)} · ${words[1]} ${cnt(b, unit)}`;

function flagPill(k, R) {
  const n = k.now;
  const open = num(n.open) ?? 0;
  const share = pc(R.thr.same_side, false, 0);
  if (n.crowded === true) return ui.pill("쏠림 표시", "bad", `열린 포지션 ${fmt.int(open)}개 중 ${share} 이상이 같은 방향입니다`);
  if (open < R.thr.min_open) return ui.pill(`${fmt.int(R.thr.min_open)}개 미만`, "thin", `열린 포지션이 ${fmt.int(R.thr.min_open)}개 미만이라 쏠림을 따지지 않습니다 (표시 없음)`);
  return ui.pill("표시 없음", "thin", `열린 포지션 ${fmt.int(open)}개 중 ${share} 이상 같은 방향이 아닙니다`);
}
const livePill = (k) => (k.live === true ? ui.pill("실전 후보", "accent") : null);
const poolPill = (k) => (k.pooled === true ? ui.pill("모두 합침", "thin", "메인 종류를 전부 합친 숫자입니다. 같은 신호가 종류마다 반복되어 들어 있습니다") : null);
const subName = (k) => (k.pooled === true ? `메인 종류 합계 · 계좌 ${cnt(k.accounts, "개")}` : `${k.suffix || ""} · 계좌 ${cnt(k.accounts, "개")}`);

// ---------------------------------------------------------------- (1) 쏠림 지금
function coinChips(k) {
  const cs = Array.isArray(k.now.coins) ? k.now.coins.filter((c) => c && typeof c === "object") : [];
  if (!cs.length) return h("span", {class: "muted"}, "열린 포지션 없음");
  return h("span", {class: "rv-coins"}, cs.map((c) => h("span", {class: "rv-coin", dataset: {coin: c.coin}}, h("b", null, String(c.coin ?? "—")),
    ` 롱 ${cnt(c.long, "")} · 숏 ${cnt(c.short, "")}`)));
}
/** The four money facts of a kind: [{key, label, value, sub, help}] (margin and "everything hits its stop at once", as separate wallets and as ONE wallet). */
export function moneyFacts(k) {
  const m = obj(k.now.margin), s = obj(k.now.stop);
  if (!(num(k.now.open) > 0)) return [];
  const loss = (f) => (num(f) == null ? "—" : f > 0 ? P(-f, true) : "0%");
  const wallets = num(k.accounts);
  return [
    {key: "margin_sep", label: `증거금 · 지갑 ${cnt(wallets, "개")} 따로`, value: num(m.separate_pct) == null ? "—" : `지갑 평균 ${P(m.separate_pct)}`, sub: "",
      help: "열린 포지션들의 증거금 합계 ÷ 이 종류 지갑 잔고 합계"},
    {key: "margin_one", label: "증거금 · 한 지갑이면", value: P(m.shared_pct), sub: times(m.shared_pct),
      help: "같은 포지션들을 지갑 하나에 모두 담았다고 가정한 증거금 합계 ÷ 지갑 한 개. 100%를 넘으면 증거금이 모자라 다 담을 수 없습니다"},
    {key: "stop_sep", label: `전부 손절되면 · 지갑 ${cnt(wallets, "개")} 따로`, value: num(s.separate_pct) == null ? "—" : `지갑 평균 ${loss(s.separate_pct)}`,
      sub: num(s.worst_acct_pct) > 0 ? `가장 크게 맞는 지갑 ${loss(s.worst_acct_pct)}` : "",
      help: "손절선이 아직 손실 쪽에 있는 포지션이 한꺼번에 손절될 때의 손실 합계 ÷ 이 종류 지갑 잔고 합계 (수수료 · 미끄러짐 제외)"},
    {key: "stop_one", label: "전부 손절되면 · 한 지갑이면", value: loss(s.shared_pct), sub: times(s.shared_pct) && num(s.shared_pct) > 0 ? `${times(s.shared_pct)}를 잃음` : "",
      help: "같은 손실 합계 ÷ 지갑 한 개. 100%를 넘으면 지갑 전부를 잃고도 모자랍니다"},
  ];
}
function stopBasis(k) {
  const m = obj(k.now.margin), s = obj(k.now.stop);
  if (!(num(k.now.open) > 0)) return "";
  const bits = [`손절 계산 ${cnt(s.n, "개")}`];
  if (num(s.locked) > 0) bits.push(`손절선이 이미 이익 쪽인 ${cnt(s.locked, "개")}는 뺌`);
  if (num(s.no_stop) > 0) bits.push(`손절선 없는 ${cnt(s.no_stop, "개")}는 뺌`);
  if (num(m.missing) > 0) bits.push(`크기를 못 구한 ${cnt(m.missing, "개")}는 뺌`);
  if (num(k.now.lev_mean) != null) bits.push(`배수 평균 ${fmt.num(k.now.lev_mean, 0)}배${num(k.now.lev_max) != null ? ` (최대 ${fmt.num(k.now.lev_max, 0)}배)` : ""}`);
  return bits.join(" · ");
}
function factsList(k, cls = "rv-facts") {
  const f = moneyFacts(k);
  if (!f.length) return h("p", {class: "note"}, "열린 포지션이 없어 증거금과 손절 손실은 0입니다.");
  return [h("dl", {class: cls}, f.map((x) => h("div", {dataset: {fact: x.key}}, h("dt", {title: x.help}, x.label),
    h("dd", {class: "num"}, x.value, x.sub ? h("small", {class: "rv-cs"}, x.sub) : null)))),
  h("p", {class: "note"}, stopBasis(k))];
}
const clusterTxt = (k) => (k.now.cluster && typeof k.now.cluster === "object" && k.now.cluster.text_ko ? String(k.now.cluster.text_ko) : null);
const shareTxt = (k) => (num(k.now.same_side_share) == null ? "" : `한 방향 ${pc(k.now.same_side_share, false, 0)}`);

function nowTable(R) {
  const body = [];
  for (const k of R.kinds) {
    const n = k.now;
    body.push(h("tr", {class: ["kd-row", n.crowded === true ? "rv-crowded" : ""], dataset: {suffix: k.suffix || k.role, crowded: n.crowded === true ? "1" : "0", pooled: k.pooled === true ? "1" : "0"}},
      h("td", {class: "l kd-nm"}, h("div", {class: "kd-nmh"}, h("b", null, nameOf(k)), livePill(k), poolPill(k)), h("small", {class: "muted"}, subName(k))),
      h("td", {class: "num"}, h("span", {class: "kd-v"}, cnt(n.open, "개"))),
      h("td", {class: "rv-split"}, sideBar(n.long, n.short), h("small", {class: "rv-sn"}, splitTxt(n.long, n.short), shareTxt(k) ? ` · ${shareTxt(k)}` : "")),
      h("td", {class: "l"}, clusterTxt(k) ? h("span", {class: "kd-v"}, clusterTxt(k)) : h("span", {class: "muted"}, "—")),
      h("td", null, flagPill(k, R))));
    body.push(h("tr", {class: "kd-reason rv-sub"}, h("td", {class: "l", colspan: "5"}, h("div", {class: "rv-subbox"},
      h("div", {class: "rv-coinrow"}, h("span", {class: "kd-kl"}, "코인별"), coinChips(k)), factsList(k)))));
  }
  return h("div", {class: "tbl-wrap"}, h("table", {class: "tbl kd-tbl rv-tbl"}, h("caption", {class: "sr"}, "계좌 종류별 열린 포지션의 쏠림"),
    h("thead", null, h("tr", null, h("th", {class: "l", scope: "col"}, "종류"), h("th", {scope: "col", title: "지금 포지션을 들고 있는 계좌 수"}, "열린 포지션"),
      h("th", {scope: "col", title: "롱과 숏의 개수"}, "롱 · 숏"), h("th", {class: "l", scope: "col", title: "한 방향에서 가장 많이 몰린 코인 3개"}, "가장 큰 쏠림"),
      h("th", {scope: "col", title: `열린 포지션이 ${R.thr.min_open}개 이상이고 ${pc(R.thr.same_side, false, 0)} 이상이 같은 방향이면 표시`}, "쏠림 표시"))),
    h("tbody", null, body)));
}
function nowCards(R) {
  return h("div", {class: "kd-cards"}, R.kinds.map((k) => {
    const n = k.now;
    return h("article", {class: ["kd-kcard", k.live === true ? "kd-live" : "", n.crowded === true ? "rv-crowded" : ""], "aria-label": nameOf(k),
      dataset: {suffix: k.suffix || k.role, crowded: n.crowded === true ? "1" : "0", pooled: k.pooled === true ? "1" : "0"}},
    h("div", {class: "kd-kh"}, h("b", null, nameOf(k)), livePill(k), poolPill(k), flagPill(k, R), h("small", {class: "muted"}, subName(k))),
    h("div", {class: "kd-kbig"}, h("span", {class: "kd-kl"}, "열린 포지션"), h("b", {class: "num"}, cnt(n.open, "개"))),
    sideBar(n.long, n.short),
    h("p", {class: "rv-sn"}, splitTxt(n.long, n.short), shareTxt(k) ? ` · ${shareTxt(k)}` : ""),
    clusterTxt(k) ? h("p", {class: "kd-rtext"}, h("span", {class: "kd-kl"}, "가장 큰 쏠림 "), h("b", null, clusterTxt(k))) : null,
    h("div", {class: "rv-coinrow"}, h("span", {class: "kd-kl"}, "코인별"), coinChips(k)),
    factsList(k, "kd-kgrid rv-facts"));
  }));
}

// ---------------------------------------------------------------- (2) 지금까지 가장 나빴던 것
const tradeTxt = (t) => {
  const bits = [t.coin, t.side ? sideWord(t.side) : null, num(t.lev) != null ? `${fmt.num(t.lev, 0)}배` : null, t.reason ? ({SL: "손절", LOCK: "잠금", RULE: "규칙", TP: "익절", LIQ: "강제청산"}[t.reason] || t.reason) : null]
    .filter(Boolean);
  return bits.join(" · ");
};
/** The cells of the "worst" card for a kind: [{key, label, value (node|text), sub, help}]. */
export function worstCells(k) {
  const w = k.worst, t = obj(w.trade), st = obj(w.streak), dd = obj(w.dd);
  const n = num(w.trades) ?? 0;
  const none = n === 0;
  return [
    {key: "trade", label: "한 거래 최악", help: "거래 하나의 손익 ÷ 그 거래 직전의 지갑 잔고", value: none || num(t.pct) == null ? "—" : `지갑의 ${P(t.pct, true)}`,
      sub: none || num(t.pct) == null ? "" : `${tradeTxt(t)}${num(t.pnl) != null ? ` · ${fmt.money(t.pnl, true)}` : ""}`},
    {key: "streak", label: "연속으로 진 최다", help: "거래가 연달아 손실로 끝난 가장 긴 횟수 (계좌마다 따로 세서 가장 긴 것)", value: none || num(st.max) == null ? "—" : `${fmt.int(st.max)}번`,
      sub: none ? "" : `계좌들의 보통 ${num(st.median) == null ? "—" : fmt.num(st.median, 1)}번 · 지금 이어지는 최다 ${cnt(st.now_max, "번")}`},
    {key: "dd", label: "낙폭 (닫힌 거래 기준)", help: "잔고가 고점에서 가장 많이 빠진 비율. 평균 지갑은 계좌 전부를 같은 비중으로 섞은 것", value: none || num(dd.basket) == null ? "—" : `평균 지갑 ${pc(dd.basket)}`,
      sub: none || num(dd.acct_worst) == null ? "" : `가장 나빴던 지갑 하나는 ${pc(dd.acct_worst)}`},
    {key: "liq", label: "강제청산 · 파산", help: "증거금이 모자라 거래소가 강제로 닫은 거래 수 · 잔고가 바닥난 계좌 수", value: none ? "—" : `${cnt(w.liq_n, "건")} · ${cnt(w.bust, "계좌")}`,
      sub: ""},
    {key: "stop", label: "손절로 끝난 거래", help: "닫힌 거래 중 손절선에 닿아 끝난 비율 (이익을 잠근 뒤 나간 것은 따로)", value: none || num(w.stop_share) == null ? "—" : pc(w.stop_share),
      sub: none ? "" : `${cnt(w.sl_n, "건")}${num(w.lock_n) > 0 ? ` · 잠금 ${cnt(w.lock_n, "건")}은 따로` : ""}`},
  ];
}
const nCell = (k) => h("small", {class: "muted"}, `닫힌 거래 ${cnt(k.worst.trades, "건")} · 계좌 ${cnt(k.worst.accounts, "개")}에 거래`);
function worstTable(R) {
  const rows = R.kinds.map((k) => {
    const cells = worstCells(k);
    return h("tr", {class: "kd-row", dataset: {suffix: k.suffix || k.role, pooled: k.pooled === true ? "1" : "0"}},
      h("td", {class: "l kd-nm"}, h("div", {class: "kd-nmh"}, h("b", null, nameOf(k)), livePill(k), poolPill(k)), h("small", {class: "muted"}, subName(k)), nCell(k)),
      cells.map((c) => h("td", {class: "num", dataset: {cell: c.key}}, h("span", {class: ["kd-v", c.key === "trade" && num(k.worst.trade && k.worst.trade.pct) < 0 ? "down" : ""]}, c.value),
        c.sub ? h("small", {class: "rv-cs"}, c.sub) : null)));
  });
  const heads = worstCells({worst: {}});
  return h("div", {class: "tbl-wrap"}, h("table", {class: "tbl kd-tbl rv-tbl"}, h("caption", {class: "sr"}, "계좌 종류별 지금까지 가장 나빴던 것"),
    h("thead", null, h("tr", null, h("th", {class: "l", scope: "col"}, "종류"), heads.map((c) => h("th", {scope: "col", title: c.help}, c.label)))),
    h("tbody", null, rows)));
}
function worstCards(R) {
  return h("div", {class: "kd-cards"}, R.kinds.map((k) => h("article", {class: ["kd-kcard", k.live === true ? "kd-live" : ""], "aria-label": nameOf(k),
    dataset: {suffix: k.suffix || k.role, pooled: k.pooled === true ? "1" : "0"}},
  h("div", {class: "kd-kh"}, h("b", null, nameOf(k)), livePill(k), poolPill(k), h("small", {class: "muted"}, subName(k))),
  nCell(k),
  h("dl", {class: "kd-kgrid rv-facts"}, worstCells(k).map((c) => h("div", {dataset: {cell: c.key}}, h("dt", {title: c.help}, c.label), h("dd", {class: "num"}, c.value,
    c.sub ? h("small", {class: "rv-cs"}, c.sub) : null)))))));
}

// ---------------------------------------------------------------- (3) 같은 방향이 몰린 날
export function daysCells(k, R) {
  const d = k.days, e = num(d.eligible) ?? 0;
  const ref = obj(d.coin_ref);
  const lop = obj(d.lopsided);
  return {
    eligible: e, total: num(d.total) ?? 0, crowded: num(d.crowded) ?? 0, share: num(d.share),
    lopsided: e && num(lop.share) != null ? `${fmt.mmdd(num(lop.day_ms))} · ${sideWord(lop.side)} ${pc(lop.share, false, 0)} (그날 ${cnt(lop.n, "건")})` : "—",
    ref: ref.suffix && num(ref.eligible) != null ? `‘${ref.name_ko || ref.suffix}’${eunNeun(ref.name_ko || ref.suffix)} ${cnt(ref.eligible, "일")} 중 ${cnt(ref.crowded, "일")}${num(ref.share) != null ? ` (${pc(ref.share, false, 0)})` : ""}` : null,
    min: R.thr.min_day_trades,
  };
}
function daysTable(R) {
  const rows = R.kinds.map((k) => {
    const c = daysCells(k, R), d = k.days;
    return h("tr", {class: "kd-row", dataset: {suffix: k.suffix || k.role, pooled: k.pooled === true ? "1" : "0"}},
      h("td", {class: "l kd-nm"}, h("div", {class: "kd-nmh"}, h("b", null, nameOf(k)), livePill(k), poolPill(k)), h("small", {class: "muted"}, subName(k))),
      h("td", {class: "num"}, h("span", {class: "kd-v"}, c.total ? cnt(c.eligible, "일") : "—"), h("small", {class: "rv-cs"}, `진입 ${R.thr.min_day_trades}건 이상인 날 (거래 있는 ${cnt(c.total, "일")} 중)`)),
      h("td", {class: "num"}, h("span", {class: "kd-v"}, c.eligible ? `${cnt(c.crowded, "일")}${c.share != null ? ` (${pc(c.share, false, 0)})` : ""}` : "—")),
      h("td", {class: "rv-split"}, sideBar(d.long, d.short, "일", ["롱 몰림", "숏 몰림"]), h("small", {class: "rv-sn"}, splitTxt(d.long, d.short, "일", ["롱 몰림", "숏 몰림"]))),
      h("td", {class: "num"}, c.lopsided),
      h("td", {class: "l"}, c.ref ? h("small", {class: "rv-cs"}, `동전 던지기 짝 ${c.ref}`) : h("span", {class: "muted"}, "—")));
  });
  return h("div", {class: "tbl-wrap"}, h("table", {class: "tbl kd-tbl rv-tbl"}, h("caption", {class: "sr"}, "계좌 종류별 같은 방향이 몰린 날"),
    h("thead", null, h("tr", null, h("th", {class: "l", scope: "col"}, "종류"), h("th", {scope: "col", title: "그날 들어간 거래가 충분한 날의 수"}, "따져 본 날"),
      h("th", {scope: "col", title: `그날 들어간 거래의 ${pc(R.thr.same_side, false, 0)} 이상이 같은 방향인 날`}, "몰린 날"), h("th", {scope: "col"}, "롱 · 숏"),
      h("th", {scope: "col", title: "가장 한쪽으로 쏠렸던 날 (UTC 날짜)"}, "가장 심했던 날"),
      h("th", {class: "l", scope: "col", title: "방향을 동전으로 정한 짝이 우연히 만드는 정도"}, "참고"))),
    h("tbody", null, rows)));
}
function daysCards(R) {
  return h("div", {class: "kd-cards"}, R.kinds.map((k) => {
    const c = daysCells(k, R), d = k.days;
    return h("article", {class: ["kd-kcard", k.live === true ? "kd-live" : ""], "aria-label": nameOf(k), dataset: {suffix: k.suffix || k.role, pooled: k.pooled === true ? "1" : "0"}},
      h("div", {class: "kd-kh"}, h("b", null, nameOf(k)), livePill(k), poolPill(k), h("small", {class: "muted"}, subName(k))),
      h("div", {class: "kd-kbig"}, h("span", {class: "kd-kl"}, `몰린 날 (진입 ${R.thr.min_day_trades}건 이상인 날 ${c.total ? cnt(c.eligible, "일") : "—"} 중)`),
        h("b", {class: "num"}, c.eligible ? `${cnt(c.crowded, "일")}${c.share != null ? ` (${pc(c.share, false, 0)})` : ""}` : "—")),
      sideBar(d.long, d.short, "일", ["롱 몰림", "숏 몰림"]), h("p", {class: "rv-sn"}, splitTxt(d.long, d.short, "일", ["롱 몰림", "숏 몰림"])),
      h("dl", {class: "kd-kgrid rv-facts"},
        h("div", null, h("dt", null, "가장 심했던 날"), h("dd", {class: "num"}, c.lopsided)),
        h("div", null, h("dt", null, "전체 거래 있는 날"), h("dd", {class: "num"}, cnt(c.total, "일")))),
      c.ref ? h("p", {class: "note"}, `참고: 동전 던지기 짝 ${c.ref}`) : null);
  }));
}

// ---------------------------------------------------------------- the boxes
function ruleBox(R) {
  const rules = (R && R.rules) || RULES_DEFAULT;
  return ui.card({plate: "이 화면은 무엇인가요", sub: "숫자만 보여 줍니다 · 권유하지 않습니다", cls: "kd-rule", id: "rv-rules"},
    h("ol", {class: "kd-list kd-rules"}, rules.map((t) => {
      const i = t.indexOf(": ");
      return h("li", null, i > 0 ? [h("b", null, t.slice(0, i)), `: ${t.slice(i + 2)}`] : t);
    })));
}
function hero(R) {
  const flagged = R.kinds.filter((k) => k.now.crowded === true);
  const names = flagged.map(nameOf);
  return h("section", {class: "card hero dl-verdict s2a-hero kd-hero rv-hero", "aria-label": "한 줄 결론"},
    h("div", {class: "s2a-hrow"}, ui.plate("한 줄 결론")),
    h("p", {class: ["dl-vbig", flagged.length ? "warn" : ""]}, R.headline || "열린 포지션과 가장 나빴던 거래를 계산 중입니다"),
    h("p", {class: "dl-vline"}, flagged.length ? `쏠림 표시가 켜진 종류: ${names.join(" · ")} (보는 ${fmt.int(R.kinds.length)}개 중 ${fmt.int(flagged.length)}개)`
      : `쏠림 표시가 켜진 종류는 없습니다 (보는 ${fmt.int(R.kinds.length)}개 기준)`),
    h("p", {class: "note"}, "모의 거래 기록입니다. 앞으로를 약속하는 숫자가 아닙니다. 어떤 행동도 권하지 않습니다."));
}
const sec = (view, tableFn, cardFn, R) => (view === "card" ? cardFn(R) : tableFn(R));

function nowCard(R, view) {
  return ui.card({plate: "쏠림 지금", sub: "지금 열려 있는 포지션이 한쪽으로 몰려 있나", cls: "kd-tcard rv-card", id: "rv-now"},
    h("p", {class: "note"}, `계좌 하나는 포지션을 하나만 듭니다. 증거금과 손절 손실은 크기 규칙으로 다시 계산한 추정입니다. 열린 포지션이 ${fmt.int(R.thr.min_open)}개 이상이고 ${pc(R.thr.same_side, false, 0)} 이상이 같은 방향이면 ‘쏠림 표시’를 켭니다.`),
    sec(view, nowTable, nowCards, R));
}
function worstCard(R, view) {
  return ui.card({plate: "지금까지 가장 나빴던 것", sub: "닫힌 거래 기준 · 평가손익은 빠짐", cls: "kd-tcard rv-card", id: "rv-worst"},
    h("p", {class: "note"}, "지갑 대비 비율로 봅니다. 거래가 적은 종류는 가장 나쁜 일이 아직 오지 않았을 수 있습니다."),
    sec(view, worstTable, worstCards, R));
}
function daysCard(R, view) {
  return ui.card({plate: "같은 방향이 몰린 날", sub: `그날 들어간 거래의 ${pc(R.thr.same_side, false, 0)} 이상이 롱이거나 숏인 날 · 숫자만 보여 줍니다`, cls: "kd-tcard rv-card", id: "rv-days"},
    h("p", {class: "note"}, `닫힌 거래를 들어간 날(UTC 날짜)로 묶어 셉니다. 그날 들어간 거래가 ${fmt.int(R.thr.min_day_trades)}건 미만이면 세지 않습니다.`),
    sec(view, daysTable, daysCards, R));
}

function legend() {
  const row = (t, d) => h("div", null, h("dt", null, t), h("dd", null, d));
  return ui.card({plate: "낱말 뜻", sub: "처음 보는 분을 위한 설명", id: "rv-words"},
    h("dl", {class: "kd-legend"},
      row("롱 · 숏", "롱은 오를 때 이기는 쪽, 숏은 내릴 때 이기는 쪽입니다. 같은 방향이 몰리면 시장이 한쪽으로 움직일 때 한꺼번에 이기거나 한꺼번에 집니다."),
      row("쏠림", "열린 포지션 대부분이 롱이거나 대부분이 숏인 상태입니다. 코인이 달라도 같이 움직이는 일이 많아서, 여러 코인이 같은 방향이면 하나처럼 움직일 수 있습니다."),
      row("증거금", "포지션 하나를 열려고 지갑에서 묶어 두는 돈입니다. 배수(레버리지)가 클수록 같은 가격 변동에 손익이 크게 납니다."),
      row("손절", "가격이 반대로 가서 정해 둔 선에 닿으면 손실을 확정하고 나가는 것입니다."),
      row("한 지갑이면", "지금 계좌들은 따로인 모의 지갑입니다. 같은 포지션을 지갑 하나에 모두 담는다고 가정하면 손실이 몇 배로 모인다는 계산입니다. 100%가 넘으면 지갑이 모자랍니다."),
      row("낙폭", "잔고가 가장 높았던 때에서 가장 낮게 내려간 비율입니다. 작을수록 덜 흔들렸다는 뜻입니다."),
      row("연속으로 진 횟수", "거래가 연달아 손실로 끝난 횟수입니다. 손실이 아닌 거래가 나오면 처음부터 다시 셉니다."),
      row("강제청산", "증거금이 모자라 거래소가 강제로 닫은 것입니다. 파산은 계좌 잔고가 바닥난 것입니다. 0이어야 정상입니다."),
      row("몰린 날", "그날 새로 들어간 거래의 대부분이 한 방향이었던 날입니다. 동전 던지기 짝은 방향을 동전으로 정하므로, 우연히 몰리는 정도를 보는 기준입니다.")));
}
function closing(R, d) {
  const wallet = Number(d && d.equity0) > 0 ? `모든 계좌는 ${startTxt(d)}에서 시작하는 모의 계좌입니다 (가상 돈). ` : "모의 계좌입니다 (가상 돈). ";
  return [
    R.notes.length ? ui.card({plate: "이 숫자의 한계", sub: "읽기 전에 한 번", id: "rv-limits"}, h("ul", {class: "kd-list"}, R.notes.map((t) => h("li", null, t)))) : null,
    h("p", {class: "note"}, R.dsIn ? "이 숫자에는 딥시크 계좌도 들어 있습니다." : "이 숫자는 딥시크를 뺀 후보만으로 계산했습니다 (딥시크 금액은 숨김 설정이라 쓰지 않습니다)."),
    h("p", {class: "assume"}, `${wallet}실제 주문은 넣지 않습니다.`),
  ];
}

function missingBox(g, d) {
  if (g.state === "old") return oldLeagueBox(d, "위험 점검 화면은 아직 없습니다.");
  if (g.state === "prep") {
    return ui.card({plate: "데이터 준비 중"},
      h("p", {class: "dl-vline"}, "위험 점검 기록은 아직 없습니다. 위 규칙은 그대로 적용됩니다."),
      h("p", {class: "note"}, "엔진이 기록을 쓰면 (5분마다) 저절로 나타납니다. 열린 포지션이나 닫힌 거래가 있어야 숫자가 생깁니다."));
  }
  return notReady("후보 리그 기록이 아직 없습니다.");
}

export async function mount(el, ctx) {
  el.classList.add("kd");
  const root = h("div", {class: "kd-root"});
  const saved = local.get("risk-view", null);
  const st = {view: saved === "card" || saved === "table" ? saved : (typeof innerWidth === "number" && innerWidth < 760 ? "card" : "table"), d: null};
  const seg = ui.seg([{id: "table", label: "표"}, {id: "card", label: "카드"}], st.view, (v) => { st.view = v; local.set("risk-view", v); paint(); }, {label: "보기"});
  el.append(ui.screenHead("위험 점검", "같은 방향이 몰렸는지, 가장 나빴던 일이 얼마였는지"), root);
  put(root, ruleBox(null), ui.missing("위험 점검 기록"));

  function paint() {
    const d = st.d, g = gate(d);
    if (g.state !== "ok") { put(root, ruleBox(null), missingBox(g, d)); return; }
    const R = g.R;
    seg.set(st.view);
    put(root, ruleBox(R), hero(R),
      h("div", {class: "row wrap", style: {justifyContent: "flex-end"}}, seg),
      nowCard(R, st.view), worstCard(R, st.view), daysCard(R, st.view),
      legend(), closing(R, d));
  }
  ctx.onLeague((d) => { st.d = d; paint(); });
}
