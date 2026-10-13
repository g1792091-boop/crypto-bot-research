// #/signals 신호: when each account kind last ENTERED a trade, per coin. It shows ENTRIES (a position that was opened), not the strategy's conditions: a strategy can be
// "on" without an entry (a filter said no, the account was busy). Read-only: the snapshot's ``signals`` (candleague/signalview.py) is counted from the closed trades and the
// positions open right now. Top to bottom: what this is, one sentence, a coin x kind table (cards on a phone) with the side, how long ago and whether it is still open,
// then the entries today (UTC) / in the last 24 hours / open now per kind. Counts only; no advice.
import {h} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {sideChip} from "./pairs.js";
import {cnt, hero, kindView, legend, mountBlock, nameOf, num, obj, strs} from "./kit4.js";

export const css = ["scr/kinds.css", "scr/s4.css"];
/** The rules as the server writes them (candleague/signalview.signal_rules_ko, same order and words); used when the snapshot has none. */
export const RULES_DEFAULT = [
  "무엇을 보여 주나: 계좌 종류가 마지막으로 언제 어느 코인에 들어갔는지(진입)만 보여 줍니다. 전략의 조건이 지금 켜져 있는지는 아닙니다.",
  "진입이 없었다고 신호가 없었다는 뜻은 아닙니다. 필터가 막았거나, 계좌가 이미 포지션을 들고 있었거나, 다른 이유가 있을 수 있습니다.",
  "기준: 이미 닫힌 거래의 진입 시각과 지금 열려 있는 포지션의 진입 시각입니다. 오늘은 UTC 0시부터, 24시간은 스냅샷 시각 기준 직전 24시간입니다.",
  "모든 숫자는 세기만 합니다. 무엇을 하라는 말은 없습니다.",
];
const ago = (ms) => (num(ms) == null ? "—" : `${fmt.dur(Number(ms) / 1000)} 전`);

export function normSignals(d) {
  const x = d && d.signals;
  if (!x || typeof x !== "object" || Array.isArray(x) || !Array.isArray(x.kinds) || !x.kinds.length) return null;
  const kinds = x.kinds.filter((k) => k && typeof k === "object").map((k) => ({...k, coins: Array.isArray(k.coins) ? k.coins.filter((c) => c && typeof c === "object") : []}));
  return {headline: typeof x.headline_ko === "string" ? x.headline_ko : "", rules: strs(x.rules_ko).length ? strs(x.rules_ko) : null, notes: strs(x.note_ko), dsIn: x.ds_in_stats === true,
    coins: strs(x.coins), last: Array.isArray(x.last) ? x.last.filter((c) => c && typeof c === "object") : [], kinds, refMs: num(x.ref_ms)};
}
/** One coin's last entry as a table cell: {has, side, ago, kst, state, n}; has false when the kind never entered the coin. */
export function lastCell(c) {
  const c0 = obj(c);
  if (num(c0.ms) == null) return {has: false, side: null, ago: "—", kst: "", state: "진입 기록 없음", n: ""};
  const open = c0.open === true, n = num(c0.n_at) || 0;
  return {has: true, side: c0.side, ago: ago(c0.age_ms), kst: fmt.kst(c0.ms), state: open ? "아직 열려 있음" : "이미 닫힘", open,
    n: n > 1 ? `같은 순간 ${fmt.int(n)}개 계좌` : "", opens: num(c0.open_n) || 0};
}
function cellNode(c, who) {
  const x = lastCell(c);
  if (!x.has) return h("div", {class: "sg-cell none"}, h("span", {class: "muted"}, "—"), h("small", {class: "s4-cs"}, x.state));
  return h("div", {class: "sg-cell", dataset: {open: x.open ? "1" : "0"}}, h("span", {class: "sg-top"}, sideChip(x.side), h("b", {class: "num"}, x.ago)),
    h("small", {class: "s4-cs"}, `${x.kst} KST · ${x.state}${x.n ? ` · ${x.n}` : ""}${who ? ` · ${who}` : ""}`));
}
function picks(B) {
  const f = B.kinds.find((k) => k.suffix === "-fq") || B.kinds.find((k) => k.live === true);
  const c = B.kinds.find((k) => k.suffix === "-ld");
  return {f, c};
}
function coinView(B, view) {
  const {f, c} = picks(B);
  const cellOf = (k, coin) => (k ? k.coins.find((x) => x.coin === coin) : null);
  const lastOf = (coin) => B.last.find((x) => x.coin === coin) || null;
  const cols = [f ? {label: `${nameOf(f)} (실전 후보)`, node: (coin) => cellNode(cellOf(f, coin))} : null, c ? {label: `${nameOf(c)} (대조)`, node: (coin) => cellNode(cellOf(c, coin))} : null,
    {label: "가장 최근 (모든 종류)", node: (coin) => { const l = lastOf(coin); return cellNode(l, l && l.name_ko ? l.name_ko : "");}}].filter(Boolean);
  const coins = B.coins.length ? B.coins : B.last.map((x) => x.coin);
  if (view === "card") {
    return h("div", {class: "kd-cards"}, coins.map((coin) => h("article", {class: "kd-kcard sg-coin", "aria-label": coin, dataset: {coin}},
      h("div", {class: "kd-kh"}, h("b", null, fmt.coin(coin))),
      h("dl", {class: "kd-kgrid s4-facts"}, cols.map((k) => h("div", null, h("dt", null, k.label), h("dd", null, k.node(coin))))))));
  }
  return h("div", {class: "tbl-wrap"}, h("table", {class: "tbl kd-tbl s4-tbl"}, h("caption", {class: "sr"}, "코인별 마지막 진입"),
    h("thead", null, h("tr", null, h("th", {class: "l", scope: "col"}, "코인"), cols.map((k) => h("th", {class: "l", scope: "col"}, k.label)))),
    h("tbody", null, coins.map((coin) => h("tr", {class: "kd-row sg-row", dataset: {coin}}, h("td", {class: "l kd-nm"}, h("b", null, fmt.coin(coin))),
      cols.map((k) => h("td", {class: "l"}, k.node(coin))))))));
}
export const COLS = [
  {key: "today", label: "오늘 진입 (UTC)", help: "UTC 0시부터 지금까지 새로 들어간 포지션 수 (닫힌 것과 열린 것 모두)", cell: (k) => ({v: cnt(k.today, "건"), sub: ""})},
  {key: "h24", label: "최근 24시간 진입", help: "스냅샷 시각 기준 직전 24시간에 새로 들어간 포지션 수", cell: (k) => ({v: cnt(k.h24, "건"), sub: ""})},
  {key: "open", label: "지금 열린 포지션", help: "지금 열려 있는 포지션이 있는 계좌 수", cell: (k) => ({v: cnt(k.open_n, "개"), sub: ""})},
  {key: "total", label: "기록 전체 진입", help: "이 스냅샷이 아는 모든 진입 (닫힌 거래 + 열린 포지션)", cell: (k) => ({v: cnt(k.total, "건"), sub: ""})},
];

export async function mount(el, ctx) {
  return mountBlock(el, ctx, {
    id: "signals", title: "신호", sub: "계좌 종류가 마지막으로 들어간 때 (진입 기록)", rules: RULES_DEFAULT, norm: normSignals, seg: true, viewKey: "signals-view",
    what: "신호 화면은 아직 없습니다.", prep: ["진입 기록은 아직 없습니다. 위 설명은 그대로 적용됩니다.", "엔진이 기록을 쓰면 (5분마다) 저절로 나타납니다. 진입한 거래가 있어야 숫자가 생깁니다."],
    hero: (B) => hero(B.headline || "진입 기록을 세는 중입니다", "이 화면은 ‘진입’을 보여 줍니다. 전략의 조건이 지금 켜져 있는지는 아닙니다.", "세기만 합니다. 어떤 행동도 권하지 않습니다."),
    body: (B, view) => [
      ui.card({plate: "코인별 마지막 진입", sub: "실전 후보 · 대조 · 가장 최근", cls: "kd-tcard s4-card", id: "sg-coins"},
        h("p", {class: "note"}, "‘이미 닫힘’은 그 진입이 끝난 뒤라는 뜻이고, 지금 신호가 없다는 말이 아닙니다. 같은 신호에 여러 계좌가 함께 들어가면 계좌 수만큼 진입으로 셉니다."), coinView(B, view)),
      ui.card({plate: "종류별 진입 개수", sub: "오늘(UTC) · 최근 24시간 · 지금 열림", cls: "kd-tcard s4-card", id: "sg-counts"}, kindView(B.kinds, COLS, view, "계좌 종류별 진입 개수"))],
    words: () => legend([
      ["진입", "새 포지션을 연 것입니다. 이미 닫힌 거래의 진입도, 지금 열려 있는 포지션도 같이 셉니다."],
      ["신호와 진입", "전략의 조건이 맞아도 필터가 막거나 계좌가 이미 포지션을 들고 있으면 진입하지 않습니다. 이 화면은 진입만 보여 줍니다."],
      ["롱 · 숏", "롱은 오를 때 이기는 쪽, 숏은 내릴 때 이기는 쪽입니다."],
      ["UTC 오늘", "UTC 0시(한국 시각 오전 9시)부터 센 하루입니다."],
      ["같은 순간 N개 계좌", "같은 시각에 같은 코인에 들어간 계좌 수입니다. 한 번의 신호를 여러 계좌가 나눠 쓰기 때문입니다."]]),
  });
}
