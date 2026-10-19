// 실거래 (#/livebots): the pieces every tab shares. Every number is the server's (/api/v4/livebots and its tabs,
// dash/more/livebots.py); a source that is not there yet says 수집 전, one that could not be read says 못 읽음 with its reason
// (never a zero). The three accounts: 페이퍼 (A+C 합본, COMBO@mix, 모의 · the one both executors follow), 바이비트 and MEXC
// (실거래, real money). Captions: paper money carries the shared paper captions (ui.ASSUME_*), real money ui.ASSUME_LIVE_KO.
import {h, ui, fmt, serverNow} from "../core/pb.js";
import {lightWords, lightCells, roeAt, netRoe} from "./livebots-calc.js";

/** The three accounts' names: ko for lists, s for the one-letter chips of a tight row, tip for the tooltip. */
export const ACCT = {
  // owners 10/19: next to the real accounts the paper account is always named 페이퍼(연습), never taken for real money
  paper: {ko: "페이퍼(연습)", s: "P", tip: "페이퍼(연습) A+C 합본 (모의 돈 · 두 실행기가 따라가는 계좌)"},
  bybit: {ko: "바이비트", s: "B", tip: "바이비트 실행기 (실거래 · 진짜 돈)"},
  mexc: {ko: "MEXC", s: "M", tip: "MEXC 실행기 (실거래 · 진짜 돈)"},
};
export const acctKo = (id) => (ACCT[id] ? ACCT[id].ko : id);
/** A small swatch + the account's name (its colour is a series token: lb-a-<id> in livebots.css). */
export const acctTag = (id, o = {}) => h("span", {class: ["lb-acct", "lb-a-" + id], title: (ACCT[id] || {}).tip || id},
  h("i", {class: "lb-sw", "aria-hidden": "true"}), o.short ? (ACCT[id] || {}).s || id : acctKo(id));

/** An executor's part of the real-money strip: its balance, or 수집 전 / 못 읽음 (never a zero for what is unknown). */
function realOf(a) {
  if (!a) return {bal: "—", pos: "—"};
  if (a.state === "missing" || a.state === "none") return {bal: "수집 전", pos: "수집 전", unk: true};
  if (a.state !== "ok") return {bal: "못 읽음", pos: "못 읽음", unk: true};
  return {bal: a.balance == null ? "—" : fmt.usd(a.balance), pos: `${a.position ? 1 : 0}/1`};
}

/**
 * The thin real-money strip over every 실거래 tab (owners 10/19): '진짜 돈 · 바이비트 $X · MEXC $Y · 포지션 n/1·n/1 · 보기만
 * 하는 화면(주문 버튼 없음)'. d: the summary answer (/api/v4/livebots), null before the first one (dashes, never a zero).
 */
export function realLine(d) {
  const by = Object.fromEntries(((d && d.accts) || []).map((a) => [a.id, a]));
  const ids = ["bybit", "mexc"].map((id) => ({id, ...realOf(d ? by[id] || {state: "missing"} : null)}));
  const sep = () => h("span", {class: "lb-real-s", "aria-hidden": "true"}, "·");
  return [h("b", {class: "lb-real-k"}, "진짜 돈"),
    ...ids.flatMap((x) => [sep(), h("span", {class: ["lb-real-a", x.unk ? "unk" : ""]}, `${ACCT[x.id].ko} `, h("b", {class: "num"}, x.bal))]),
    sep(), h("span", {class: "lb-real-a", title: `한 번에 포지션 하나 · ${ids.map((x) => `${ACCT[x.id].ko} ${x.pos}`).join(" · ")}`},
      "포지션 ", h("b", {class: "num"}, ids.map((x) => x.pos).join("·"))),
    sep(), h("span", {class: "lb-real-v"}, "보기만 하는 화면(주문 버튼 없음)")];
}

/** Exit reasons in the owners' words (the server sends reason_ko too; this is for the short tags of a dense row). */
export const EXIT_SHORT = {SL: "손절", LOCK: "잠금", LIQ: "청산", HALT: "멈춤", MANUAL: "수동", REV: "반대", TP: "익절", PAPER: "청산", OTHER: "청산", END: "끝"};

const ago = (ms) => fmt.ago(ms, serverNow());

/** A source that is not there yet (수집 전) or could not be read (못 읽음 + why). */
export function sourceState(src, what) {
  if (!src || src.state === "missing" || src.state === "none") {
    return h("div", {class: "lb-state"}, ui.notYet("수집 전", (src && src.reason_ko) || undefined),
      h("span", null, ` ${what}: ${(src && src.reason_ko) || "아직 기록이 없어요"}`));
  }
  return h("div", {class: "lb-state bad"}, ui.pill("못 읽음", "bad"), h("span", null, ` ${what}: ${src.reason_ko || "읽지 못했어요"}`),
    src.reason ? h("span", {class: "lb-raw", title: src.reason}, ` (${src.reason})`) : null);
}

/** The account's position in one line for a tooltip: entry, stop / lock, next lock step, liquidation (paper only). */
export function posTip(a, mark) {
  const p = a.position;
  if (!p) return `${acctKo(a.id)}: 포지션 없음`;
  const roe = roeAt(p, mark), net = a.kind === "paper" ? netRoe(p, mark) : null;
  const nx = p.next_lock;
  return [`${acctKo(a.id)} ${fmt.coin(p.symbol)} ${fmt.sideKo(p.side)} ${fmt.lev(p.leverage)}`, `진입 ${fmt.price(p.entry)}`,
    `${p.locked ? "잠금선" : "손절선"} ${fmt.price(p.stop)}`, p.stop_initial && p.locked ? `첫 손절 ${fmt.price(p.stop_initial)}` : null,
    nx && nx.price ? `다음 잠금: 순ROE ${fmt.pct(nx.at, 0, false)} (${fmt.price(nx.price)})에서 ${fmt.pct(nx.lock, 0, false)}${nx.from === "paper" ? " · 페이퍼 기준" : ""}` : null,
    p.liq ? `청산가 ${fmt.price(p.liq)}` : a.kind === "live" ? "청산가는 거래소 앱에서 (실행기 기록에 없음)" : null,
    roe != null ? `ROE ${fmt.pct(roe, 1)} (마크 ${fmt.price(mark)}, 나갈 때 수수료 전)` : "마크 가격 없음",
    net != null ? `순ROE ${fmt.pct(net, 1)} (수수료·펀딩 뒤, 잠금 계산과 같은 식)` : null,
    p.status === "entering" ? "진입 확인 중" : null].filter(Boolean).join(" · ");
}

const NEAR = 0.0005;                    // entries this close share one line (chart-lines.js posLines' rule)
/**
 * The chart deck's lines of the accounts' positions on one coin (core/chartfx.js setLines): an entry line per price (the
 * paper and the executors that followed it usually share one: 'P·B 롱 40배 · B +1.2% · P +1.3%'), each account's stop or
 * lock line (dashed), the paper's first stop once locked and its NEXT ladder step (the price where the paper's net ROE
 * reaches the next trigger: 11 %, then every 3 %).
 */
export function liveLines(accts, sym, mark) {
  const xs = (accts || []).filter((a) => a && a.state === "ok" && a.position && a.position.symbol === sym && a.position.entry > 0)
    .map((a) => ({a, p: a.position})).sort((x, y) => x.p.entry - y.p.entry);
  const groups = [];
  for (const x of xs) {
    const g = groups[groups.length - 1];
    if (g && g.side === x.p.side && Math.abs(x.p.entry - g.price) / g.price < NEAR) g.items.push(x);
    else groups.push({price: x.p.entry, side: x.p.side, items: [x]});
  }
  const out = [];
  for (const g of groups) {
    g.items.sort((x, y) => (x.a.kind === "live" ? 0 : 1) - (y.a.kind === "live" ? 0 : 1));        // real money first
    const id = "lv:e:" + g.items.map((x) => x.a.id).join(",");
    const roes = g.items.map((x) => ({id: x.a.id, roe: roeAt(x.p, mark)}));
    const lead = roes.find((r) => r.roe != null);
    const tone = !lead ? "flat" : lead.roe >= 0 ? "up" : "down";
    const kids = [];
    for (const {a, p} of g.items) {
      if (p.stop) {
        kids.push({id: `lv:s:${a.id}`, parent: id, group: "risk", price: p.stop, tone: p.locked ? "up" : "down", dash: 1, alpha: 0.55, axis: false,
          label: `${ACCT[a.id].s} ${p.locked ? "잠금" : "손절"}`});
      }
      if (a.kind === "paper" && p.locked && p.stop_initial) {
        kids.push({id: `lv:f:${a.id}`, parent: id, group: "risk", price: p.stop_initial, tone: "down", dash: 2, alpha: 0.35, axis: false, label: "첫 손절"});
      }
      if (a.kind === "paper" && p.next_lock && p.next_lock.price) {
        kids.push({id: `lv:n:${a.id}`, parent: id, group: "risk", price: p.next_lock.price, tone: "accent", dash: 2, alpha: 0.5, axis: false,
          label: `다음 잠금 ${fmt.pct(p.next_lock.at, 0, false)}`});
      }
    }
    const p0 = g.items[0].p, letters = g.items.map((x) => ACCT[x.a.id].s).join("·");
    const locked = g.items.some((x) => x.p.locked);
    out.push({id, group: "pos", price: g.price, tone, dash: 0, alpha: 0.75, axis: true,
      pill: {text: [`${letters} ${fmt.sideKo(p0.side)} ${fmt.lev(p0.leverage)}`,
        roes.filter((r) => r.roe != null).map((r) => (g.items.length > 1 ? `${ACCT[r.id].s} ` : "") + fmt.pct(r.roe, 1)).join(" · ") || null,
        locked ? "잠금" : "손절"].filter(Boolean).join(" · "),
        short: `${letters} ${fmt.sideKo(p0.side)}`, title: g.items.map((x) => posTip(x.a, mark)).join(" / "),
        chips: kids.length ? [{text: locked ? "잠금" : "손절", ids: kids.map((k) => k.id), title: "손절·잠금·다음 잠금 선 보이기·숨기기"}] : []}});
    out.push(...kids);
  }
  return out;
}

/** The light of one executor as a compact block: dot, state, the 20 squares, the next step in words. */
export function lightRow(x) {
  const w = lightWords(x.light);
  const cells = lightCells(x.light);
  const last = x.light && x.light.last_event;
  return h("div", {class: ["lb-light", w.tone]},
    h("div", {class: "lb-lhead"}, h("span", {class: ["lb-dot", w.tone], "aria-hidden": "true"}), h("b", null, x.name_ko),
      h("span", {class: ["lb-lstate", w.tone]}, w.head)),
    h("p", {class: "lb-lline"}, w.line),
    cells.length ? h("div", {class: "lb-cells", role: "img", "aria-label": `최근 ${cells.length}칸: 이김 ${cells.filter((v) => v === true).length}, 짐 ${cells.filter((v) => v === false).length}, 아직 없음 ${cells.filter((v) => v == null).length}`},
      cells.map((v) => h("i", {class: v == null ? "none" : v ? "win" : "loss"}))) : null,
    w.next ? h("p", {class: "note"}, w.next) : null,
    last ? h("p", {class: "note"}, `마지막 ${last.kind_ko}: ${fmt.kst(last.ts)}`) : null);
}

/** One account's balance as the green LED bar (ui.ledBar): its caption, LIVE only while its record is fresh. */
export function acctLed(a, led) {
  const live = a.kind === "live";
  const st = a.stats || {};
  led.update({total: a.balance, initialTotal: a.initial, live: a.state === "ok" && !a.stale,
    curve: (a.curve || []).length > 1 ? a.curve.map((x) => x[1]) : null,
    stats: [live ? (a.initial_ts ? `첫 잔고 기록 ${fmt.kst(a.initial_ts)} 대비 · 입출금 뺌` : null) : `시작 ${fmt.money(a.initial)} USDT`,
      a.as_of_ms ? `마지막 기록 ${fmt.hm(a.as_of_ms)}` : null].filter(Boolean),
    right: [{k: "닫힌 거래 순손익", v: st.trades ? st.pnl : null}, {k: "닫힌 거래", text: st.trades ? `${fmt.int(st.trades)}번 · 승률 ${fmt.pct(st.win_rate, 1, false)}` : "아직 없음"}],
    caption: live ? ui.ASSUME_LIVE_KO : ui.ASSUME_KO});
}

/** An account card for the 요약 tab's account row: name, LED bar, halt / stale pills, notes. */
export function acctCard(a, led, notes) {
  const o = {title: acctKo(a.id), sub: a.kind === "paper" ? `${a.sub_ko || "A+C 합본"} · 모의` : a.sub_ko || "실행기", cls: "lb-now"};
  if (a.state !== "ok") return ui.card(o, sourceState(a, a.kind === "paper" ? "페이퍼 DB" : `${acctKo(a.id)} 실행기 DB`), notesEl(notes));
  acctLed(a, led);
  const kill = a.kill_file && a.kill_file.present;
  return ui.card(o, led,
    h("div", {class: "lb-pills"},
      a.halted ? ui.pill(`멈춤: ${a.halt_reason || "이유 기록 없음"}`, "bad") : ui.pill("멈춤 아님", "good"),
      a.bust ? ui.pill("파산", "bad") : null,
      kill ? ui.pill("비상 정지 파일 있음", "bad", a.kill_file.path) : null,
      a.stale ? ui.pill(`기록 멈춤 · ${ago(a.as_of_ms)}`, "warn", a.kind === "paper" ? "페이퍼 봇은 1분마다 기록해요: 꺼져 있을 수 있어요"
        : "실행기는 몇 초마다 기록해요: 꺼져 있거나 멈췄을 수 있어요") : null,
      a.consecutive_losses != null ? h("span", {class: "lb-meta"}, `연속 손실 ${fmt.int(a.consecutive_losses)}번`
        + (a.max_consecutive_losses ? ` (한도 ${fmt.int(a.max_consecutive_losses)})` : "")) : null),
    a.halted && a.kind === "live" ? h("p", {class: "lb-halt"}, `멈춘 이유: ${a.halt_reason || "기록 없음"}`,
      a.halted_ts ? ` · ${fmt.kst(a.halted_ts)}부터` : "", " · 사람이 풀 때까지 새 진입 없음") : null,
    notesEl(notes));
}

export const notesEl = (notes) => (notes && notes.length ? h("div", {class: "lb-notes"}, notes.map((t) => h("p", {class: "lb-warn"}, t))) : null);
