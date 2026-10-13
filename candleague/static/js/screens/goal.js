// #/goal 목표 진척도 (owners 10/13): the owners' goals as progress cards, for the 실전 후보 (kind "fq") and the 대조 (-ld) side by
// side: 승률 70%+, 하루 진입 1번 이상 (3번이면 더 좋음), 거래당 순수익 +10%, 한 달 환산 수익률 x4 (+300%), 낙폭이 낮게 (the 대조보다).
// Each card: the big current number, the target, a bar with the target marked, one word (달성 / 가까움 / 멀다 / 아직 몰라요) and,
// for a small sample (under 100 closed trades), one honest line. Under 30 trades nothing is judged. The month figure is only a
// projection of the wallet so far (compounded) and only from 7 days on ("7일 뒤부터" before). Data: the snapshot's ``kinds``
// (versus.js gate); an old league gets a note, a snapshot without kinds a "데이터 준비 중" card.
// HONESTY: nothing here is a promise; every figure may be null (DeepSeek money hidden, no trade yet) and then reads "—".
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {gate, gateNode, controlOf, roleOf, totalTrades, val, pc, cnt, sampleNote, startTxt, EARLY_N, SMALL_N, LIVE_ROLE} from "./versus.js";

export const css = "scr/kinds.css";

const DAY = 86400000;
const MONTH_DAYS = 30;
const WORD_CLS = {"달성": "good", "가까움": "warn", "멀다": "bad", "아직 몰라요": "thin", "기준": "thin"};
const BAR_CLS = {"달성": "good", "가까움": "warn", "멀다": "bad", "아직 몰라요": "thin", "기준": "thin"};

const days = (d) => (d && d.start_ms && d.done_ms ? Math.max(0, (d.done_ms - d.start_ms) / DAY) : null);
/** 달성 / 가까움 / 멀다, or 아직 몰라요 (no number, or under 30 trades). */
function judge(v, n, ok, near) {
  if (v == null || n < EARLY_N) return "아직 몰라요";
  return v >= ok ? "달성" : v >= near ? "가까움" : "멀다";
}
const frac = (v, scale) => (v == null || !(scale > 0) ? 0 : Math.max(0, Math.min(1, v / scale)));

// One goal: ev(kind, X) -> {big, tone, v, st, bar, ticks, sub}. X = {d, days, ctl, rel (the kind is the 대조)}.
const GOALS = [
  {id: "win", title: "승률", target: "70% 이상", ev: (k) => {
    const v = k.n ? val(k.win_rate) : null, scale = Math.max(0.875, v ?? 0);
    return {big: v == null ? "—" : pc(v, false, 1), v, st: judge(v, k.n, 0.7, 0.6), bar: frac(v, scale), ticks: [0.7 / scale],
      sub: v == null ? "" : `이긴 거래 ${fmt.int(k.wins)}건 / 거래 ${fmt.int(k.n)}건`};
  }},
  {id: "tpd", title: "하루 진입 수", target: "하루 1번 이상 (3번 이상이면 더 좋음)", ev: (k, X) => {
    const v = val(k.trades_per_day), scale = Math.max(3.75, v ?? 0);
    let sub = "하루가 지나야 계산합니다";
    if (v != null) {
      sub = v >= 3 ? "이상 목표 3번도 넘었습니다" : v >= 1 ? `최소 목표 1번은 넘음 · 3번까지 ${fmt.num(3 - v, 1)}번 모자람` : `1번까지 ${fmt.num(1 - v, 1)}번 모자람`;
    }
    const fewer = X.ctl && k !== X.ctl && val(k.accounts) != null && val(X.ctl.accounts) != null && Number(k.accounts) < Number(X.ctl.accounts);
    return {big: v == null ? "—" : `${fmt.num(v, 1)}번`, v, st: judge(v, k.n, 1, 0.5), bar: frac(v, scale), ticks: [1 / scale, 3 / scale], sub,
      extra: fewer ? `이 종류는 ${fmt.int(k.accounts)}개 매매법만 돌아서 대조(${fmt.int(X.ctl.accounts)}개)보다 적게 나올 수 있습니다` : null};
  }},
  {id: "roe", title: "거래당 순수익", target: "+10% 정도 (거래 한 번에 증거금 대비)", ev: (k) => {
    const v = k.n ? val(k.mean_roe) : null, scale = Math.max(0.125, v ?? 0);
    return {big: v == null ? "—" : pc(v, true, 1), tone: v == null ? "" : fmt.tone(v), v, st: judge(v, k.n, 0.1, 0.05), bar: frac(v, scale),
      ticks: [0.1 / scale], sub: "수수료 뺀 뒤, 거래 한 번의 평균"};
  }},
  {id: "month", title: "한 달 환산 수익률", target: "x4 (+300%)", ev: (k, X) => {
    const scale0 = 3.75;
    if (X.days == null || X.days < 7) {
      return {big: "7일 뒤부터", tone: "dim", v: null, st: "아직 몰라요", bar: 0, ticks: [3 / scale0],
        sub: `시작한 지 ${X.days == null ? "—" : fmt.num(X.days, 1)}일 · 7일이 지나야 한 달 속도를 어림잡습니다`};
    }
    const wr = val(k.wallet_return_pct);
    if (wr == null) return {big: "—", v: null, st: "아직 몰라요", bar: 0, ticks: [3 / scale0], sub: "잔고 수익률이 아직 없습니다 (딥시크 금액 숨김이거나 거래 없음)"};
    const mult = 1 + wr > 0 ? Math.pow(1 + wr, MONTH_DAYS / X.days) : 0;
    const v = mult - 1, scale = Math.max(scale0, v);
    return {big: mult > 999 ? "x999+" : `x${fmt.num(mult, 2)}`, tone: fmt.tone(v), v, st: judge(v, k.n, 3, 1.5), bar: frac(v, scale), ticks: [3 / scale],
      sub: `지금 속도로 ${MONTH_DAYS}일 이어지면 ${pc(v, true, 0)} · 지금까지 ${pc(wr, true, 1)} (${startTxt(X.d)} 대비, ${fmt.num(X.days, 1)}일)`};
  }},
  {id: "dd", title: "낙폭", target: "대조보다 낮게 (낮을수록 좋음)", ev: (k, X) => {
    const v = val(k.max_dd_mean), ref = X.ctl ? val(X.ctl.max_dd_mean) : null;
    const scale = Math.max(0.2, 1.25 * Math.max(v ?? 0, ref ?? 0));
    let st = "아직 몰라요";
    if (k === X.ctl) st = v == null ? "아직 몰라요" : "기준";
    else if (v != null && ref != null && k.n >= EARLY_N) st = v <= ref ? "달성" : v <= ref * 1.25 ? "가까움" : "멀다";
    return {big: v == null ? "—" : pc(v, false, 1), v, st, bar: frac(v, scale), ticks: ref == null ? [] : [ref / scale],
      sub: k === X.ctl ? "비교 기준 (실전 후보가 이보다 낮아야 합니다)" : ref == null ? "대조의 낙폭이 아직 없습니다" : `대조는 ${pc(ref, false, 1)}`};
  }},
];

function cell(g, k, role, X) {
  const live = role === "live";
  const who = h("div", {class: "kd-gwho"}, live ? ui.pill("실전 후보", "accent") : ui.pill("대조", ""), h("b", null, k ? k.name : "—"));
  if (!k) return h("div", {class: ["kd-gcell", live ? "kd-live" : ""]}, who, h("p", {class: "kd-gnote"}, "이 종류 계좌가 기록에 없습니다"));
  const m = g.ev(k, X);
  const note = k.n === 0 ? "아직 거래가 없습니다" : sampleNote(k.n);
  const label = `${g.title}: 지금 ${m.big}, 목표 ${g.target}, ${m.st}`;
  return h("div", {class: ["kd-gcell", live ? "kd-live" : ""], dataset: {goal: g.id, role: k.role}},
    who,
    h("p", {class: ["kd-gnum", m.tone || (m.st === "아직 몰라요" ? "dim" : "")]}, m.big),
    m.sub ? h("p", {class: "kd-gsub"}, m.sub) : null,
    h("div", {class: ["kd-gbar", BAR_CLS[m.st]], role: "img", "aria-label": label},
      h("i", {style: {"--p": `${(m.bar * 100).toFixed(1)}%`}}), m.ticks.map((t) => h("b", {class: "kd-tick", style: {"--at": `${(Math.min(1, t) * 100).toFixed(1)}%`}, title: `목표 ${g.target}`}))),
    h("div", {class: "kd-gword"}, ui.pill(m.st, WORD_CLS[m.st], m.st === "아직 몰라요" ? "거래가 30건 전이거나 숫자가 아직 없어 판단하지 않습니다" : null)),
    m.extra ? h("p", {class: "kd-gnote"}, m.extra) : null,
    note ? h("p", {class: "kd-gnote"}, note) : null);
}

function hero(fq, X, d) {
  const dd = X.days;
  const head = h("div", {class: "s2a-hrow"}, ui.plate("실전 후보 한눈에"),
    h("span", {class: "muted s2a-small"}, dd == null ? "" : `시작한 지 ${fmt.num(dd, 1)}일`));
  if (!fq) {
    return h("section", {class: "card hero dl-verdict s2a-hero kd-hero", "aria-label": "한 줄 결론"}, head,
      h("p", {class: "dl-vbig warn"}, "실전 후보 계좌가 아직 기록에 없습니다"),
      h("p", {class: "note"}, "엔진이 실전 후보 종류의 숫자를 쓰면 저절로 나타납니다. 아래에는 대조만 보입니다."));
  }
  if (fq.n === 0) {
    return h("section", {class: "card hero dl-verdict s2a-hero kd-hero", "aria-label": "한 줄 결론"}, head,
      h("p", {class: "dl-vbig warn"}, "아직 거래가 없습니다"),
      h("p", {class: "note"}, "실전 후보의 첫 거래가 닫히면 목표 진척도가 나옵니다."));
  }
  const sts = GOALS.map((g) => g.ev(fq, X).st);
  const count = (w) => sts.filter((s) => s === w).length;
  const known = fq.n >= EARLY_N;
  const big = !known
    ? h("p", {class: "dl-vbig warn"}, "아직 판단하기 이릅니다 ", h("small", {class: "kd-need"}, `(실전 후보 거래 ${cnt(fq.n)} · ${EARLY_N}건부터 봅니다)`))
    : h("p", {class: ["dl-vbig", count("달성") ? "ok" : "warn"]}, count("달성") ? `목표 ${GOALS.length}개 중 ${count("달성")}개를 달성했습니다 ` : "아직 달성한 목표가 없습니다 ",
      h("small", {class: "kd-need"}, `(실전 후보 거래 ${cnt(fq.n)})`));
  const small = sampleNote(fq.n);
  return h("section", {class: "card hero dl-verdict s2a-hero kd-hero", "aria-label": "한 줄 결론"}, head, big,
    h("p", {class: "dl-vline"}, `달성 ${count("달성")} · 가까움 ${count("가까움")} · 멀다 ${count("멀다")} · 아직 몰라요 ${count("아직 몰라요")}`),
    small ? h("p", {class: "note"}, small) : null,
    h("p", {class: "note"}, "이 숫자는 모의 거래 기록일 뿐 앞으로를 약속하지 않습니다. 목표에 가까워 보여도 거래가 쌓이면 달라질 수 있습니다."),
    h("div", {class: "row wrap"}, h("a", {class: "btn-line", href: "#/versus"}, "메인 vs 대조"), h("a", {class: "btn-line", href: "#/reasons"}, "청산 이유"),
      h("a", {class: "btn-line", href: "#/events"}, "규칙이 한 일")));
}

export async function mount(el, ctx) {
  el.classList.add("kd");
  const root = h("div", {class: "kd-root"});
  el.append(ui.screenHead("목표 진척도", "두 분의 목표에 실전 후보가 얼마나 가까운지 (대조와 나란히)"), root);
  put(root, ui.missing("종류별 숫자"));

  function paint(d) {
    const g = gate(d);
    if (g.state !== "ok") { put(root, gateNode(g)); return; }
    const kinds = g.kinds;
    const ctl = controlOf(kinds, d), fq = roleOf(kinds, LIVE_ROLE);
    const X = {d, days: days(d), ctl};
    put(root, hero(fq, X, d),
      h("div", {class: "kd-goals"}, GOALS.map((goal) => ui.card({plate: goal.title, sub: `목표 ${goal.target}`, cls: "kd-gcard"},
        h("div", {class: "kd-g2"}, cell(goal, fq, "live", X), cell(goal, ctl, "control", X))))),
      h("p", {class: "assume"}, `달성 · 가까움 · 멀다는 목표에 대한 거리일 뿐 판정이 아닙니다. 거래 ${fmt.int(EARLY_N)}건 전에는 ‘아직 몰라요’, ${fmt.int(SMALL_N)}건 전에는 운일 수 있다는 줄을 붙입니다. 한 달 환산은 지금까지 잔고의 변화를 ${MONTH_DAYS}일로 늘려 본 것(복리)이라 거래가 적을 땐 크게 틀립니다.${totalTrades(kinds) === 0 ? " 아직 거래가 없습니다." : ""}`));
  }
  ctx.onLeague(paint);
}
