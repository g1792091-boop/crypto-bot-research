// #/leverage 레버리지 비교: "30배이던 포지션이 40배나 50배였다면?" The league has two research families that differ only in the leverage: the quick stop (-fq)
// against -fq40 / -fq50, and the original way (-ld) against -ld40 / -ld50. They take the same signals and exit by the same rule; -fq and -ld size
// by the signal-quality rule (50x / 40x for good spots, 30x otherwise), the other four use ONE leverage for every entry (40x with margin 40%, 50x with
// margin 50%) and the 15% stop-loss-size check is lifted so that they take the same trades.
// Data: the snapshot's own blocks only, nothing is computed from trades here: ``kinds`` (accounts, trades, win_rate, mean_roe, wallet_return_pct,
// reasons.LIQ), ``accounts`` (each wallet's max_dd), ``losses.kinds`` (worst_loss_roe), ``risk.kinds`` (now.lev_mean: the open positions).
// HONESTY: the screen only states differences, never a verdict; fewer than 30 trades in a kind reads 표본 적음; a missing number reads "—", never 0;
// a family that is not in the snapshot (an older record) reads 준비 중.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {hasLineup, kindOf, notReady, oldLeagueBox} from "./pairs.js";
import {pc} from "./versus.js";

export const css = ["scr/kinds.css", "scr/leverage.css"];

export const MIN_TRADES = 30;
/** The two families: the base kind (sizing by signal quality) and the same kind at one leverage. */
export const FAMILIES = [
  {id: "fq", ko: "빠른 손절 계열", base: "fq", others: [["fq40", 40], ["fq50", 50]]},
  {id: "ld", ko: "원래 방식 계열", base: "ld", others: [["ld40", 40], ["ld50", 50]]},
];
const FALLBACK = {fq: "빠른 손절", fq40: "빠른 손절 40배", fq50: "빠른 손절 50배", ld: "원래 방식", ld40: "원래 방식 40배", ld50: "원래 방식 50배"};
const SAME = 0.0005;                                   // 0.05 %p reads as "같다" (as the server's pair counts do)

const num = (x) => (fmt.bad(x) ? null : Number(x));
const obj = (x) => (x && typeof x === "object" && !Array.isArray(x) ? x : {});
const arr = (x) => (Array.isArray(x) ? x.filter((v) => v && typeof v === "object") : []);
const P = (f, sign = false) => (num(f) == null ? "—" : pc(f, sign));
const PP = (f) => (num(f) == null ? "—" : `${fmt.num(Number(f) * 100, 1, true)}%p`);
const abs1 = (f) => `${fmt.num(Math.abs(Number(f)) * 100, 1)}%p`;

const nameOf = (d, role) => {
  const k = kindOf(d, role);
  return String((k && (k.short_ko || k.label_ko)) || FALLBACK[role] || role);
};

/** One kind's numbers from the snapshot, null when the kind is not in it: {role, name, accounts, trades, win, mean, ret, worst, dd, liq, lev, small}. */
export function kindFacts(d, role) {
  const k = arr(d && d.kinds).find((x) => x.role === role);
  if (!k) return null;
  const rows = arr(d.accounts).filter((r) => r.role === role);
  const dds = rows.map((r) => num(r.max_dd)).filter((v) => v != null);
  const lk = arr(obj(d.losses).kinds).find((x) => x.role === role && x.pooled !== true);
  const rk = arr(obj(d.risk).kinds).find((x) => x.role === role && x.pooled !== true);
  const trades = num(k.trades);
  const liq = num(obj(k.reasons).LIQ);
  return {role, name: nameOf(d, role), accounts: num(k.accounts), trades, win: num(k.win_rate), mean: num(k.mean_roe), ret: num(k.wallet_return_pct),
    worst: lk ? num(lk.worst_loss_roe) : null, dd: dds.length ? Math.max(...dds) : null, liq: trades == null ? null : liq, lev: rk ? num(obj(rk.now).lev_mean) : null,
    small: trades == null || trades < MIN_TRADES};
}

/** The plain sentence about what one leverage changed against the base kind. Only differences, never a verdict; null when the means are missing. */
export function diffLine(base, other, lev) {
  if (!base || !other || base.mean == null || other.mean == null) return null;
  const dm = other.mean - base.mean;
  const first = Math.abs(dm) < SAME ? "거래당 평균은 차이가 없었고" : `거래당 평균 ${PP(dm)} ${dm > 0 ? "더 벌었고" : "덜 벌었고"}`;
  let second = "";
  if (base.worst != null && other.worst != null) {
    const dw = other.worst - base.worst;             // worst loss ROE is negative: a negative difference is a deeper loss
    second = Math.abs(dw) < SAME ? ", 가장 큰 손실은 차이가 없었습니다" : dw < 0 ? `, 가장 큰 손실은 ${PP(dw)} 더 깊었습니다` : `, 가장 큰 손실은 ${PP(dw)} 덜 깊었습니다`;
  } else second = ", 가장 큰 손실은 비교할 숫자가 없습니다";
  const bits = [];
  if (base.ret != null && other.ret != null) bits.push(Math.abs(other.ret - base.ret) < SAME ? "총 수익률은 차이가 없었습니다" : `총 수익률은 ${PP(other.ret - base.ret)} ${other.ret > base.ret ? "높았습니다" : "낮았습니다"}`);
  if (base.liq != null && other.liq != null) {
    const dl = other.liq - base.liq;
    bits.push(dl === 0 ? "강제청산 횟수는 같았습니다" : `강제청산은 ${fmt.int(Math.abs(dl))}번 ${dl > 0 ? "더 많았습니다" : "더 적었습니다"}`);
  }
  const tail = base.small || other.small ? " 거래가 적어 우연일 수 있습니다 (표본 적음)." : "";
  return `${lev}배 계좌는 같은 신호에서 ${first}${second}.${bits.length ? ` ${bits.join(", ")}.` : ""}${tail}`;
}

/** The whole screen's data: {state, fams}.  wait  no snapshot   old  no lineup   prep  the new league without these kinds   ok  at least one kind here */
export function gate(d) {
  if (!d || !d.accounts) return {state: "wait", fams: []};
  if (!hasLineup(d)) return {state: "old", fams: []};
  const fams = FAMILIES.map((f) => ({...f, baseFacts: kindFacts(d, f.base), list: f.others.map(([role, lev]) => ({role, lev, facts: kindFacts(d, role)}))}));
  const any = fams.some((f) => f.list.some((o) => o.facts));
  return {state: any ? "ok" : "prep", fams};
}

/** The one-line answer for 한눈 지도: the first family that has a 50배 (else 40배) kind and a base. */
export function headline(d) {
  try {
    const g = gate(d);
    if (g.state !== "ok") return null;
    for (const f of g.fams) {
      const o = [...f.list].reverse().find((x) => x.facts);
      const line = f.baseFacts && o ? diffLine(f.baseFacts, o.facts, o.lev) : null;
      if (line) return `${f.ko}: ${line}`;
    }
  } catch (e) { return null; }
  return null;
}

// ---------------------------------------------------------------- the cards
function factList(f) {
  const rows = [
    ["accounts", "계좌", f.accounts == null ? "—" : `${fmt.int(f.accounts)}개`],
    ["trades", "거래", f.trades == null ? "—" : `${fmt.int(f.trades)}건`],
    ["win", "이긴 비율", P(f.win)],
    ["mean", "거래당 평균 ROE", P(f.mean, true)],
    ["ret", "총 수익률 (계좌 합침)", P(f.ret, true)],
    ["worst", "가장 큰 손실 (ROE)", P(f.worst, true)],
    ["dd", "최대 낙폭 (가장 나쁜 계좌)", P(f.dd)],
    ["liq", "강제청산", f.liq == null ? "—" : `${fmt.int(f.liq)}번`],
    ["lev", "열린 포지션 평균 배수", f.lev == null ? "—" : `${fmt.num(f.lev, 1)}배`],
  ];
  return h("dl", {class: "lg-facts"}, rows.map(([k, label, v]) => h("div", {dataset: {fact: k}}, h("dt", null, label), h("dd", {class: "num"}, v))));
}
function col(f, role, name, lev) {
  if (!f) {
    return h("div", {class: "lg-col lg-miss", dataset: {role, state: "prep"}}, h("h3", {class: "lg-h"}, name), h("p", {class: "muted"}, "준비 중 · 이 종류는 아직 기록에 없습니다"));
  }
  return h("div", {class: "lg-col", dataset: {role, state: "ok"}},
    h("h3", {class: "lg-h"}, name, " ", f.small ? ui.pill("표본 적음", "thin", `거래가 ${MIN_TRADES}건 미만입니다. 우연일 수 있어 결론을 내지 않습니다`) : null,
      lev ? ui.pill(`${lev}배 고정`, "accent", `모든 진입이 ${lev}배 (증거금 ${lev}%)`) : ui.pill("신호 품질 규칙", "thin", "좋은 자리 50배 · 40배, 그 밖에는 30배 (30배 미만은 없음)")),
    factList(f));
}
function famCard(f, d) {
  const cols = [col(f.baseFacts, f.base, nameOf(d, f.base), null), ...f.list.map((o) => col(o.facts, o.role, nameOf(d, o.role), o.lev))];
  const lines = f.list.map((o) => {
    const t = diffLine(f.baseFacts, o.facts, o.lev);
    return t ? h("p", {class: "dl-vline lg-diff", dataset: {diff: o.role}}, t) : null;
  }).filter(Boolean);
  return ui.card({plate: f.ko, sub: `${nameOf(d, f.base)} · 40배 · 50배를 나란히`, cls: "lg-fam", id: `lg-${f.id}`},
    h("div", {class: "lg-cols"}, cols),
    lines.length ? h("div", {class: "lg-reading"}, h("h3", {class: "lg-h"}, "차이만 읽으면"), lines)
      : h("p", {class: "muted", dataset: {diff: "none"}}, "비교할 숫자가 아직 모자랍니다 (준비 중 이거나 거래가 없습니다)"));
}

function whyBox() {
  return ui.card({plate: "이 화면은 무엇인가요", sub: "위험을 비교합니다 · 우위의 증거가 아닙니다", cls: "kd-rule", id: "lg-rules"},
    h("ol", {class: "kd-list kd-rules"},
      h("li", null, h("b", null, "무엇을 보여 주나"), ": 같은 신호 · 같은 청산 규칙에서 배수만 다른 계좌 종류를 나란히 놓고, 30배이던 포지션이 40배나 50배였다면 어땠는지 숫자로 보여 줍니다."),
      h("li", null, h("b", null, "한 줄 읽기"), ": 두 종류의 차이만 적습니다. 어느 쪽이 낫다고 말하지 않습니다."),
      h("li", null, h("b", null, "표본 적음"), `: 거래가 ${MIN_TRADES}건 미만인 종류는 우연일 수 있어 결론을 내지 않습니다.`)),
    ui.disclosure("왜 배수를 바꾸면 포지션 크기가 달라지나요", h("div", {class: "lg-why"},
      h("p", null, "이 리그의 증거금은 배수와 같은 퍼센트입니다 (30배면 증거금이 지갑의 30%, 50배면 50%). 그래서 배수를 올리면 같은 지갑으로 훨씬 큰 포지션을 듭니다."),
      h("ul", {class: "kd-list"},
        h("li", null, "30배: 증거금 30% × 30배 = 지갑의 약 9배를 듭니다."),
        h("li", null, "40배: 증거금 40% × 40배 = 지갑의 약 16배를 듭니다."),
        h("li", null, "50배: 증거금 50% × 50배 = 지갑의 약 25배를 듭니다.")),
      h("p", null, "그래서 같은 가격 움직임에도 이기든 지든 손익이 훨씬 크게 나옵니다. 이 화면은 위험이 얼마나 커지는지 비교하는 것이지, 높은 배수가 더 낫다는 증거가 아닙니다."),
      h("p", null, "원래 계좌(빠른 손절 · 원래 방식)는 신호 품질 규칙으로 좋은 자리에 50배 · 40배, 그 밖에는 30배를 쓰고 30배보다 낮추지 않습니다. 40배 · 50배 계좌는 모든 진입에 한 배수만 쓰고, 손절폭이 지갑의 15%를 넘는 신호를 거르는 검사를 풀어서 같은 거래를 받습니다."))));
}
function limits() {
  return [
    h("p", {class: "note"}, "열린 포지션 평균 배수는 지금 열려 있는 포지션만의 평균이라 닫힌 거래 전체의 평균이 아닙니다. 열린 포지션이 없으면 —로 적습니다."),
    h("p", {class: "assume"}, "모든 계좌는 모의 계좌입니다 (가상 돈). 실제 주문은 넣지 않습니다. 앞으로를 약속하는 숫자가 아닙니다."),
  ];
}
function missingBox(g, d) {
  if (g.state === "old") return oldLeagueBox(d, "레버리지 비교 화면은 아직 없습니다.");
  if (g.state === "prep") return ui.card({plate: "준비 중"}, h("p", {class: "dl-vline"}, "40배 · 50배 계좌가 아직 기록에 없습니다. 위 설명은 그대로 적용됩니다."),
    h("p", {class: "note"}, "엔진이 이 계좌들을 시작하고 기록을 쓰면 (5분마다) 저절로 나타납니다."));
  return notReady("후보 리그 기록이 아직 없습니다.");
}

export async function mount(el, ctx) {
  el.classList.add("kd");
  const root = h("div", {class: "kd-root"});
  el.append(ui.screenHead("레버리지 비교", "30배이던 포지션이 40배나 50배였다면? · 같은 신호 · 같은 청산"), root);
  put(root, whyBox(), ui.missing("레버리지 비교 기록"));
  ctx.onLeague((d) => {
    const g = gate(d);
    if (g.state !== "ok") { put(root, whyBox(), missingBox(g, d)); return; }
    put(root, whyBox(), g.fams.map((f) => famCard(f, d)), limits());
  });
}
