// #/pairs 같은 신호 짝 비교: 메인 계좌(새 청산 방법)와 대조 계좌(원래 계단 청산)가 같은 신호에서 낸 거래를 짝으로 묶어 비교한다.
// 짝 = 같은 코인 · 같은 방향 · 같은 진입 시각의 거래 두 개 (a = 메인 계좌, b = 대조 계좌, 차이 = a − b, ROE 분수). 같은 신호끼리만
// 비교하면 들어간 자리가 같아서 차이가 "나오는 방법"에서만 생긴다 (전체 잔고 비교는 거래 횟수와 운이 섞인다).
// 맨 위 한 문장 · 종류마다 카드(짝 수, 낫다/같다/못하다 막대, 평균 차이, 돈으로 본 차이) · 최근 짝 표(종류별 필터) · 짝 설명 상자.
// Data: the shared snapshot's ``pairs`` ({control, by_role, recent}) and ``lineup`` (the accounts' kinds). ROE null = hidden or
// unknown: "—", never 0. An older snapshot (no lineup, the 190-account league) gets a short note. Every string is a text node.
// The small helpers at the top (kinds of the lineup, ROE words, the old-league note) are shared with events.js and judge.js.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as LK from "../lk.js";
import {reasonKo, coinShort, tfKo} from "../labels.js";

// ---------------------------------------------------------------- shared helpers (events.js, judge.js)
/** A difference under this (0.05 %p of ROE) reads as 같다, as the server counts it (summary.SAME_DIFF): the table never shows "+0.0%p 낫다". */
export const SAME_EPS = 0.0005;
const ok = (x) => !fmt.bad(x);

/** The snapshot names the owners' league's account kinds in ``lineup``; an older snapshot (190 accounts) has none. */
export const hasLineup = (d) => !!d && Array.isArray(d.lineup) && d.lineup.some((x) => x && x.role);
export const lineupOf = (d) => (hasLineup(d) ? d.lineup.filter((x) => x && x.role) : []);
export const kindOf = (d, role) => lineupOf(d).find((x) => x.role === role) || null;
/** The short Korean name of a kind ("빠른 손절"), else its role id. */
export const kindName = (d, role) => {
  const k = kindOf(d, role);
  return String((k && (k.short_ko || k.label_ko)) || role || "—");
};
const labelOf = (k) => String((k && k.label_ko) || "");
export const isMain = (k) => /^메인/.test(labelOf(k));
export const isResearch = (k) => /^연구/.test(labelOf(k));
/** "메인" / "연구" for a kind of the lineup (the others are controls and the old comparison accounts). */
export const tagOf = (k) => (isMain(k) ? "메인" : isResearch(k) ? "연구" : null);
export const tagPill = (k) => (tagOf(k) ? ui.pill(tagOf(k), isMain(k) ? "accent" : "thin", isMain(k) ? "새로 시험하는 청산 방법" : "비교용 연구 계좌 (실전 후보 아님)") : null);

/** 은 / 는 after a Korean word. */
export function eunNeun(word) {
  const k = String(word || "").trim().slice(-1).charCodeAt(0) - 0xac00;
  if (!(k >= 0 && k <= 11171)) return "은(는)";
  return k % 28 ? "은" : "는";
}

/** An ROE (a fraction) as a percent: 0.1732 -> "17%", -0.052 -> "−5.2%"; null -> "—" (never 0). */
export function pc(x, sign = false) {
  if (!ok(x)) return "—";
  const v = Number(x) * 100;
  return fmt.pct(v, sign, Math.abs(v) >= 10 ? 0 : 1);
}
/** A difference of two ROEs in percentage points: "+3.2%p". */
export const pp = (x) => (ok(x) ? `${fmt.num(Number(x) * 100, 1, true)}%p` : "—");
/** A coloured ROE (text, tone by sign; "—" muted). */
export function roeSpan(x, sign = true) {
  if (!ok(x)) return h("span", {class: "muted"}, "—");
  const t = pc(x, sign);
  return h("span", {class: ["num", fmt.tone(x, t)]}, t);
}
/** 낫다 / 못하다 / 같다 for a difference (a − b), null when unknown. */
export function diffWord(d) {
  if (!ok(d)) return null;
  const v = Number(d);
  return v >= SAME_EPS ? "낫다" : v <= -SAME_EPS ? "못하다" : "같다";
}
export const WORD_CLS = {"낫다": "good", "못하다": "bad", "같다": "thin"};
export const wordPill = (w, title) => (w ? ui.pill(w, WORD_CLS[w] || "thin", title) : h("span", {class: "muted"}, "—"));

/** +1 long, -1 short, 0 unknown (the snapshot writes 1 / -1; words are accepted too). */
export function sideNum(x) {
  if (typeof x === "string") {
    const t = x.trim().toLowerCase();
    if (/^(long|buy|롱|l)$/.test(t)) return 1;
    if (/^(short|sell|숏|s)$/.test(t)) return -1;
  }
  const n = Number(x);
  return Number.isFinite(n) && n !== 0 ? Math.sign(n) : 0;
}
export const sideWord = (x) => (sideNum(x) > 0 ? "롱" : sideNum(x) < 0 ? "숏" : "—");
export const sideChip = (x) => (sideNum(x) ? h("span", {class: ["side", sideNum(x) > 0 ? "long" : "short"]}, sideWord(x)) : h("span", {class: "muted"}, "—"));
export const coinOf = (sym) => (sym ? coinShort(sym) : "—");

// The strategies' Korean names and plain explanations (GET /api/judge = candleague/data/native_ko.json), loaded once: the 11 picks
// whose strategy the meta file does not name show their code otherwise.
let JUDGE = null;
/** The ``strategies`` of /api/judge ({name: {kind, name_ko, bet_ko, native, long_broken_ko, short_broken_ko, notes_ko}}), cached;
 *  null when the answer is empty ({}), a thrown error when the request fails. */
export async function loadJudge(ctx, force = false) {
  if (JUDGE && !force) return JUDGE;
  const r = await ctx.api("/api/judge");
  const s = r && typeof r === "object" && r.strategies && typeof r.strategies === "object" && !Array.isArray(r.strategies) ? r.strategies : null;
  if (s && Object.keys(s).length) JUDGE = s;
  return s && Object.keys(s).length ? s : null;
}
/** The strategy's Korean name: the meta file's, else judge's ``name_ko``, else its code. */
export function nameKo(name) {
  const k = LK.stratKo(name);
  const j = JUDGE && JUDGE[name];
  return k !== name ? k : (j && j.name_ko) || name;
}
/** The engine has not written this part yet. */
export function notReady(what) {
  return h("div", {class: "dl-missing"}, h("b", null, "준비 중"), h("span", null, ` · ${what} 엔진이 기록을 쓰면 저절로 나타납니다.`));
}
/** The 190-account league (no lineup): this screen is for the owners' new league. */
export function oldLeagueBox(d, what) {
  const n = d && Array.isArray(d.accounts) ? d.accounts.length : 0;
  return h("div", {class: "dl-missing"}, h("b", null, "새 리그 전용"),
    h("span", null, ` · 지금 기록은 이전 리그${n ? `(계좌 ${fmt.int(n)}개)` : ""}라서 ${what} 새 리그(메인 계좌와 대조 계좌)가 시작되면 저절로 나타납니다.`));
}
/** The account page of a kind's account for a pick (pick id + the kind's suffix), null when unknown. */
export function accountId(d, pick, role) {
  const k = kindOf(d, role);
  return k && k.suffix && pick ? `${pick}${k.suffix}` : null;
}
/** A big plain sentence (the page's one-line takeaway). */
export const bigLine = (...kids) => h("p", {class: "dl-vline", style: {fontSize: "var(--t-lg)", fontWeight: "800", lineHeight: "1.45"}}, ...kids);

// ---------------------------------------------------------------- this screen
/** The roles of ``by_role`` in the lineup's order (then any other). */
export function pairRoles(d, by) {
  const have = Object.keys(by || {});
  const order = lineupOf(d).map((k) => k.role).filter((r) => have.includes(r));
  return order.concat(have.filter((r) => !order.includes(r)));
}
/** The kind the sentence is about: the live candidate (-fq, 빠른 손절), else the first 메인 kind that has pairs. */
export function focusRole(d, by) {
  const roles = pairRoles(d, by);
  const fq = lineupOf(d).find((k) => k.suffix === "-fq" && roles.includes(k.role));
  if (fq) return fq.role;
  const main = lineupOf(d).find((k) => isMain(k) && roles.includes(k.role));
  return main ? main.role : roles[0] || null;
}
const count = (s) => {
  const b = Number(s && s.better) || 0, w = Number(s && s.worse) || 0, e = Number(s && s.same) || 0;
  const n = ok(s && s.n) ? Number(s.n) : b + w + e;
  // ``n_shown``: the pairs whose ROE is shown (DeepSeek pairs only with the money switch on); better / worse / same are over those
  const shown = ok(s && s.n_shown) ? Number(s.n_shown) : n;
  return {b, w, e, n, shown};
};

/** The one sentence at the top. */
export function takeaway(d, P) {
  const by = (P && P.by_role) || {};
  const role = focusRole(d, by);
  if (!role) return {text: "아직 같은 신호 짝이 없습니다", sub: "메인 계좌와 대조 계좌가 같은 신호로 거래를 마친 것이 아직 없습니다. 거래가 쌓이면 여기에 한 문장으로 나옵니다."};
  const name = kindName(d, role), c = count(by[role]);
  if (!c.n) return {text: `${name}${eunNeun(name)} 아직 대조와 짝을 이룬 거래가 없습니다`, sub: "같은 신호로 둘 다 거래를 마치면 비교가 시작됩니다."};
  if (!c.shown) return {text: `${name}${eunNeun(name)} 같은 신호 짝이 ${fmt.int(c.n)}개 있지만, 금액 숨김 설정이라 낫고 못한 횟수는 숨겼습니다`, sub: "딥시크 금액을 보이게 하면 비교가 나옵니다."};
  return {text: `${name}${eunNeun(name)} 같은 신호에서 대조보다 ${fmt.int(c.b)}번 낫고 ${fmt.int(c.w)}번 못했습니다 (평균 ${pp(by[role].mean_diff_roe)})`,
    sub: `짝 ${fmt.int(c.shown)}개${c.e ? ` · 같은 건 ${fmt.int(c.e)}번` : ""}${c.shown < c.n ? ` (전체 ${fmt.int(c.n)}개 중 ROE가 보이는 것)` : ""}${c.shown < 30 ? " · 짝이 30개가 안 되면 우연일 수 있습니다" : ""}`};
}

/** 낫다 / 같다 / 못하다 as a bar (never colour alone: the words and counts are under it). */
export function resultBar(c) {
  const seg = (n, color) => (n ? h("i", {style: {flex: `${n} 1 0`, display: "block", background: color}}) : null);
  return h("div", {class: "stack tight"},
    h("span", {role: "img", "aria-label": `낫다 ${c.b}번, 같다 ${c.e}번, 못하다 ${c.w}번`,
      style: {display: "flex", gap: "2px", height: "10px", borderRadius: "5px", overflow: "hidden", background: "var(--surface-3)"}},
    seg(c.b, "var(--up)"), seg(c.e, "var(--muted)"), seg(c.w, "var(--down)")),
    h("div", {class: "row wrap", style: {gap: "4px 14px"}},
      h("span", {class: "up"}, `낫다 ${fmt.int(c.b)}번`), h("span", {class: "muted"}, `같다 ${fmt.int(c.e)}번`), h("span", {class: "down"}, `못하다 ${fmt.int(c.w)}번`)));
}

function kindBox(d, role, s, focus) {
  const k = kindOf(d, role), c = count(s);
  const mean = s ? s.mean_diff_roe : null, word = diffWord(mean);
  const money = s ? s.sum_diff_pct_of_wallet : null;
  const mt = pp(mean);
  const mm = ok(money) ? `${fmt.num(Number(money) * 100, 1, true)}%` : "—";
  return h("div", {class: ["cl-cp", focus ? "now" : ""], dataset: {role}, style: focus ? {borderColor: "var(--accent-line)"} : null},
    h("div", {class: "cl-cph"}, h("b", null, kindName(d, role)), tagPill(k), focus ? ui.pill("실전 후보", "good", "지금 실전에 쓸지 가장 유력한 청산 방법") : null),
    k && k.why_ko ? h("p", {class: "note"}, k.why_ko) : null,
    !c.n ? ui.none("아직 짝 없음") : !c.shown ? [bigLine("짝 ", h("span", {class: "num"}, `${fmt.int(c.n)}개`)), h("p", {class: "note"}, "금액 숨김 설정이라 ROE 비교는 숨겼습니다")] : [
      bigLine("짝 ", h("span", {class: "num"}, `${fmt.int(c.shown)}개`), " · 평균 ", h("span", {class: ["num", fmt.tone(mean, mt)]}, mt), word ? ` ${word}` : ""),
      c.shown < c.n ? h("p", {class: "note"}, `전체 ${fmt.int(c.n)}개 중 ROE가 보이는 짝 기준 (딥시크 금액 숨김 설정)`) : null,
      resultBar(c),
      h("div", {class: "stats cl-stats3"},
        ui.stat("평균 차이", h("b", {class: ["num", fmt.tone(mean, mt)]}, mt), "메인 ROE − 대조 ROE · 짝 평균"),
        ui.stat("돈으로 (계좌 대비)", h("b", {class: ["num", fmt.tone(money, mm)]}, mm), `짝 전체의 차이를 합친 값 · 계좌는 ${LK.startUsd()}에서 시작`))]);
}

export async function mount(el, ctx) {
  try { await ctx.meta(); } catch (e) { /* names fall back to the codes */ }
  const q = ctx.params.query || {};
  const st = {kind: q.kind || "all", key: ""};
  const hero = h("section", {class: "card hero", "aria-label": "한 줄 결론"});
  const explain = h("div");
  const cards = h("div");
  const chips = h("div"), countLine = h("p", {class: "note"});
  const pg = ui.pager({size: 12, empty: "이 종류의 짝은 아직 없습니다", render: (rows) => tableOf(rows)});
  const tableCard = ui.card({plate: "최근 짝", sub: "새 것부터 · 메인과 대조의 청산 이유와 ROE를 나란히"}, chips, countLine, pg.el);
  tableCard.hidden = true;
  el.append(ui.screenHead("같은 신호 짝 비교", "같은 신호에서 메인 계좌와 대조 계좌가 어떻게 달랐나"), hero, explain, cards, tableCard);

  let doc = null, rows = [];
  const save = () => ctx.setQuery(st.kind === "all" ? {} : {kind: st.kind});

  function tableOf(part) {
    return ui.table([
      {label: "매매법", l: true, get: (r) => nameCell(r)},
      {label: "끝난 때", title: "메인 계좌의 거래가 끝난 시각 (KST)", get: (r) => fmt.kst(r.exit_time || r.entry_time)},
      {label: "방향", get: (r) => sideChip(r.side)},
      {label: "메인 청산", title: "메인 계좌가 나온 이유와 ROE", get: (r) => exitCell(r.a_reason, r.a_roe)},
      {label: "대조 청산", title: "대조 계좌가 나온 이유와 ROE", get: (r) => exitCell(r.b_reason, r.b_roe)},
      {label: "차이 (메인 − 대조)", title: "메인 ROE − 대조 ROE, %p", get: (r) => diffCell(r.diff_roe)},
    ], part, {caption: "같은 신호 짝: 메인 계좌와 대조 계좌의 청산 비교"});
  }
  function nameCell(r) {
    const nm = h("span", {class: ["an", "cl-an"], title: `${r.name} · ${r.pick || ""}`}, h("span", {class: "an-tf"}, tfKo(r.tf)), h("span", {class: "an-n"}, nameKo(r.name)));
    const id = accountId(doc, r.pick, r.role);
    return h("span", {class: "row wrap", style: {gap: "4px 8px"}}, id ? h("a", {class: "cl-plain", href: `#/account/${encodeURIComponent(id)}`, title: "메인 계좌 자세히"}, nm) : nm,
      h("small", {class: "muted"}, `${coinOf(r.symbol)} · ${kindName(doc, r.role)}`));
  }
  const exitCell = (reason, roe) => h("span", null, h("small", {class: "muted"}, reasonKo(reason)), " ", roeSpan(roe));
  const diffCell = (dv) => h("span", null, ok(dv) ? h("span", {class: ["num", fmt.tone(dv, pp(dv))]}, pp(dv)) : h("span", {class: "muted"}, "—"), " ", wordPill(diffWord(dv)));

  function paintTable(d, P, roles) {
    const all = Array.isArray(P.recent) ? P.recent.filter((r) => r && typeof r === "object") : [];
    const at = (r) => Number(r.exit_time) || Number(r.entry_time) || 0;            // the server lists them by the main trade's exit time
    rows = all.slice().sort((a, b) => at(b) - at(a));
    if (!rows.length) { tableCard.hidden = true; return; }
    const present = roles.filter((r) => rows.some((x) => x.role === r));
    if (st.kind !== "all" && !present.includes(st.kind)) st.kind = "all";
    const key = JSON.stringify([present, st.kind]);
    if (key !== st.key) {
      st.key = key;
      put(chips, present.length > 1 ? h("div", {class: "dl-fields"}, ui.field("종류", ui.seg(
        [{id: "all", label: `전체 ${fmt.int(rows.length)}`}, ...present.map((r) => ({id: r, label: `${kindName(d, r)} ${fmt.int(rows.filter((x) => x.role === r).length)}`}))],
        st.kind, (v) => { st.kind = v; st.key = ""; save(); pg.set(shown(), false); countText(); }, {label: "종류"}))) : null);
    }
    pg.set(shown(), true);
    countText();
    tableCard.hidden = false;
  }
  const shown = () => (st.kind === "all" ? rows : rows.filter((r) => r.role === st.kind));
  function countText() {
    const n = shown().length;
    countLine.textContent = rows.length ? `${fmt.int(n)}개 보는 중${st.kind === "all" ? "" : ` (${kindName(doc, st.kind)})`} · 낫다 = 메인이 대조보다 ROE가 높음 · ROE는 증거금 대비 수익률` : "";
  }

  const explainCard = () => ui.card({plate: "짝이 뭔가요?", sub: "같은 신호끼리만 비교해야 공평합니다"},
    h("div", {class: "stack tight"},
      h("h3", {class: "cl-h3"}, "짝이란"),
      h("p", null, "같은 신호로 들어간 거래 두 개입니다. 메인 계좌의 거래 하나와, 같은 코인 · 같은 방향 · 같은 진입 시각에 대조 계좌가 한 거래를 묶어 둡니다. ",
        "대조 계좌는 원래 방식(계단 익절 · 손절 최대 2 ATR)으로 나오는 계좌입니다."),
      h("h3", {class: "cl-h3"}, "왜 같은 신호끼리만 비교하나요?"),
      h("p", null, `계좌마다 거래한 횟수와 때가 달라서 잔고만 비교하면 운이 섞입니다. 같은 신호로 같은 때 들어간 거래는 들어간 자리가 같으니, 결과 차이는 “어떻게 나왔나”에서만 생깁니다. 모든 계좌는 ${LK.startUsd()}에서 시작합니다.`),
      h("h3", {class: "cl-h3"}, "읽는 법"),
      h("p", null, "차이 = 메인 ROE − 대조 ROE (%p). 플러스면 메인이 낫고, 마이너스면 못합니다. 숫자가 “—”이면 아직 모르거나 숨긴 값입니다. 짝이 적을 때는 한두 번에 결과가 크게 달라지니 참고만 하세요.")));

  function paint(d) {
    doc = d;
    LK.setEquity(d && d.equity0);                    // the start wallet in the text below ($1,000 or $5,000) is this snapshot's
    put(explain, explainCard());
    if (!d || !d.accounts) { put(hero, ui.plate("같은 신호 짝"), notReady("후보 리그 기록이 아직 없습니다.")); put(cards, null); tableCard.hidden = true; return; }
    if (!hasLineup(d)) { put(hero, ui.plate("같은 신호 짝"), oldLeagueBox(d, "같은 신호 짝 비교는 아직 없습니다.")); put(cards, null); tableCard.hidden = true; return; }
    const P = d.pairs && typeof d.pairs === "object" ? d.pairs : null;
    if (!P) { put(hero, ui.plate("같은 신호 짝"), notReady("같은 신호 짝 기록이 아직 없습니다.")); put(cards, null); tableCard.hidden = true; return; }
    const by = P.by_role && typeof P.by_role === "object" ? P.by_role : {};
    const roles = pairRoles(d, by);
    const t = takeaway(d, P);
    put(hero, ui.plate("한 줄 결론"), bigLine(t.text), h("p", {class: "note"}, t.sub));
    const focus = focusRole(d, by);
    put(cards, roles.length ? ui.card({plate: "종류마다 한눈에", sub: "메인 계좌 종류별 · 같은 신호에서 대조와 비교"},
      h("div", {class: "cl-cps"}, roles.map((r) => kindBox(d, r, by[r], r === focus)))) : null);
    paintTable(d, P, roles);
  }
  ctx.onLeague(paint);
  loadJudge(ctx).then(() => { if (ctx.alive() && doc) paint(doc); }).catch(() => { /* codes stay */ });
}
