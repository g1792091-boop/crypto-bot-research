// 실거래 (#/livebots): the pieces every tab shares. Every number is the server's (/api/v4/livebots and its tabs,
// dash/more/livebots.py); a source that is not there yet says 수집 전, one that could not be read says 못 읽음 with its reason
// (never a zero). The three accounts: 페이퍼 (COMBO@mix, 모의 · the one both executors follow: 추세판단 봇 from 10/21, A+C
// 합본 before; paperBotKo), 바이비트 and MEXC (실거래, real money). Captions: paper money carries the shared paper captions
// (ui.ASSUME_*), real money ui.ASSUME_LIVE_KO. The executor slots of a page: execIds / execsNow (the third, 플립스터, only
// while the server has it installed; else the two as before).
import {h, ui, fmt, serverNow, bus} from "../core/pb.js";
import {lightWords, lightCells, roeAt, netRoe} from "./livebots-calc.js";

/** The three accounts' names: ko for lists, s for the one-letter chips of a tight row, tip for the tooltip. */
export const ACCT = {
  // owners 10/19: next to the real accounts the paper account is always named 페이퍼(연습), never taken for real money
  paper: {ko: "페이퍼(연습)", s: "P", tip: "페이퍼(연습): 두 실행기가 따라가는 모의 계좌 (모의 돈)"},     // two bots: setPapers
  bybit: {ko: "바이비트", s: "B", tip: "바이비트 실행기 (실거래 · 진짜 돈)"},
  mexc: {ko: "WOO X Pro", s: "W", tip: "WOO X Pro 실행기 (실거래 · 진짜 돈)"},
  // the second paper bot (owners 10/19, docs/live15-mexc-ko.md): only on the page while there is one (the summary's papers)
  paper2: {ko: "페이퍼 2(연습)", s: "P2", tip: "두 번째 페이퍼(연습) 봇 (모의 돈)"},
  // the third executor (owners 10/23, docs/flipster-ko.md: it follows the VWAP 개선판): only on the page while the server has
  // it installed (execIds)
  flipster: {ko: "플립스터", s: "F", tip: "플립스터 실행기 (실거래 · 진짜 돈)"},
};
/** Every executor slot the page knows, in the server's order (dash/more/livebots.py ALL_EXECS). Which of them a server has
 *  (livebots.installed: the third, 플립스터, once its config file or its database is there): execIds / execsNow. */
export const EXEC_SLOTS = ["bybit", "mexc", "flipster"];
const EXECS0 = ["bybit", "mexc"];
let EXECS_NOW = EXECS0, execsKey = EXECS0.join();
/** The executor ids of the last summary (setExecs); the two before the first one. */
export const execsNow = () => EXECS_NOW;
/** The summary's executors (its ``execs``), called with every summary: a tab that built its parts for two adds the third
 *  when it comes (bus "lb:execs"); without it every list stays the two as before. */
export function setExecs(execs) {
  const ids = Array.isArray(execs) ? EXEC_SLOTS.filter((id) => execs.some((x) => x && x.id === id)) : [];
  const now = ids.length ? ids : EXECS0;
  if (now.join() === execsKey) return;
  execsKey = now.join();
  EXECS_NOW = now;
  bus.emit("lb:execs", EXECS_NOW);
}
/** The executor ids of an answer, in the server's order: its own ``execs`` ([{id}] or ids), else its accounts (``accts``:
 *  a list or a map by id); an answer that names none: execsNow(). */
export function execIds(d) {
  let have = null;
  if (d && Array.isArray(d.execs)) have = d.execs.map((x) => (x && typeof x === "object" ? x.id : x));
  else if (d && Array.isArray(d.accts)) have = d.accts.map((a) => a && a.id);
  else if (d && d.accts && typeof d.accts === "object") have = Object.keys(d.accts);
  const ids = have ? EXEC_SLOTS.filter((id) => have.includes(id)) : [];
  return ids.length ? ids : EXECS_NOW;
}
/** The executors' names in one line ("바이비트 · WOO X Pro", "… · 플립스터"). */
export const execsKo = (ids = EXECS_NOW, sep = " · ") => ids.map((id) => acctKo(id)).join(sep);
/** "두 실행기가 따라가는" (with the third installed "세 실행기가 따라가는"): who follows the one paper bot. */
export const allFollowKo = () => `${EXECS_NOW.length > 2 ? "세" : "두"} 실행기가 따라가는`;
/** "세 계좌" / "네 계좌" / "다섯 계좌": the accounts a page lists (three: one paper bot and two executors, as before). */
export const acctsKo = (n) => `${{4: "네", 5: "다섯", 6: "여섯"}[n] || "세"} 계좌`;
const ACCT0 = {paper: {...ACCT.paper}, paper2: {...ACCT.paper2}};
let PAPERS = null, papersKey = "null";
/** The summary's two paper bots (setPapers), null with one (owners 10/23: the 추세판단 봇 and the 'VWAP 개선판'). */
export const papersNow = () => PAPERS;
/** "바이비트 · WOO X Pro가 따라가는" for the main paper bot, by who follows it (two bots: only its own followers; "따라가는
 *  실행기 없는" when none); null with one paper bot (a page keeps its own words). */
export function mainFollowKo() {
  if (!PAPERS) return null;
  const b = PAPERS.find((x) => x.id === "paper") || {};
  const f = b.followers || [];
  return f.length ? `${f.join(" · ")}가 따라가는` : "따라가는 실행기 없는";
}
/**
 * Two paper bots (the summary's ``papers``, null with one): each paper account takes its bot's name (short_ko: "추세판단 봇",
 * "VWAP 개선판"; the 10/19 twins "규칙봇 15", "규칙봇 15 −35%") and says who follows it in its tooltip; with one paper bot the
 * names are the usual ones again. Called with every summary.
 */
export function setPapers(papers) {
  const key = JSON.stringify(papers || null);
  if (key !== papersKey) {                              // a page that names who follows which redraws its words (ctx.on "lb:papers")
    papersKey = key;
    PAPERS = Array.isArray(papers) && papers.length > 1 ? papers : null;
    bus.emit("lb:papers", PAPERS);
  }
  for (const id of ["paper", "paper2"]) Object.assign(ACCT[id], ACCT0[id]);
  for (const b of papers || []) {
    if (!ACCT[b.id]) continue;
    const short = b.short_ko || (b.label_ko || "").split(" (")[0] || ACCT0[b.id].ko;
    ACCT[b.id].ko = short;
    const who = (b.followers || []).length ? `${b.followers.join("·")}가 따라감` : "따라가는 실행기 없음";
    ACCT[b.id].tip = `${short} 페이퍼(연습)${b.name && b.name !== short ? ` ${b.name}` : ""}${b.stop_ko ? ` · 손절 ${b.stop_ko}` : ""} · ${who}`;
  }
}
export const acctKo = (id) => (ACCT[id] ? ACCT[id].ko : id);
/** The two paper bots of the summary (papers) in one line for a page's head: who follows which ("바이비트 → 추세판단 봇 ·
 *  WOO X Pro → VWAP 개선판"); null with one paper bot (the page's own words stay). */
export function followLine(papers) {
  if (!Array.isArray(papers) || papers.length < 2) return null;
  const parts = [];
  for (const b of papers) for (const f of b.followers || []) parts.push(`${f} → ${b.short_ko || (b.label_ko || "").split(" (")[0]}`);
  return parts.length ? parts.join(" · ") : null;
}
/** 을 / 를 after a name (its last syllable's final consonant; a digit or % by how it is read: "VWAP 개선판을", "추세판단
 *  봇을", "규칙봇 15 −35%를"). */
export function josaObj(w) {
  const t = String(w || "").trim(), c = t.slice(-1), code = c ? c.charCodeAt(0) : 0;
  if (code >= 0xac00 && code <= 0xd7a3) return (code - 0xac00) % 28 ? "을" : "를";
  if (/[0-9]/.test(c)) return "013678".includes(c) ? "을" : "를";
  return "를";
}
/** An executor's own light in one line ("근거 쌓는 중 6/20 · 기준: 최근 20번 중 75% 이상 (15번 이상 이김)"): the 목표
 *  card of an executor on the other paper bot (its config's light, not the trend bot's). */
export function lightLine(l) {
  const w = lightWords(l);
  return `${w.short} · ${w.next || w.line}`;
}
/** An executor's other paper bot in words (the server's ``era``: it follows, or followed, another bot whose trades are left
 *  out of the numbers beside it; owners 10/23): "WOO X Pro는 10/22 14:00부터 VWAP 개선판을 따라가요 · 그 봇 거래 3번은 여기
 *  안 셈"; null without one (one paper bot: nothing new on the page). */
export function eraWords(name, era) {
  if (!era) return null;
  const bot = era.other_ko || "다른 페이퍼 봇";
  const n = era.other_n ? ` · 그 봇 거래 ${fmt.int(era.other_n)}번은 여기 안 셈` : "";
  return era.now_other ? `${name}는 ${era.since != null ? `${fmt.kst(era.since)}부터 ` : ""}${bot}${josaObj(bot)} 따라가요${n}`
    : `${name}는 한때 ${bot}${josaObj(bot)} 따라갔어요${n}`;
}
/** The paper bot's name where a page labels it (tb: the server's trend_bot): the 추세판단 봇's own name, else the paper's
 *  own config name (name: the summary's paper.name_ko), else the old label 'A+C 합본' as before. */
export const paperBotKo = (tb, name) => (tb ? tb.name || "추세판단 봇" : name || "A+C 합본");
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
 * 하는 화면(주문 버튼 없음)' (플립스터 $Z too while the server has it). d: the summary answer (/api/v4/livebots), null before
 * the first one (dashes, never a zero).
 */
export function realLine(d) {
  const by = Object.fromEntries(((d && d.accts) || []).map((a) => [a.id, a]));
  const ids = execIds(d).map((id) => ({id, ...realOf(d ? by[id] || {state: "missing"} : null)}));
  const sep = () => h("span", {class: "lb-real-s", "aria-hidden": "true"}, "·");
  return [h("b", {class: "lb-real-k"}, "진짜 돈"),
    ...ids.flatMap((x) => [sep(), h("span", {class: ["lb-real-a", x.unk ? "unk" : ""]}, `${ACCT[x.id].ko} `, h("b", {class: "num"}, x.bal))]),
    sep(), h("span", {class: "lb-real-a", title: `한 번에 포지션 하나 · ${ids.map((x) => `${ACCT[x.id].ko} ${x.pos}`).join(" · ")}`},
      "포지션 ", h("b", {class: "num"}, ids.map((x) => x.pos).join("·"))),
    sep(), h("span", {class: "lb-real-v"}, "보기만 하는 화면(주문 버튼 없음)")];
}

/** Exit reasons in the owners' words (the server sends reason_ko too; this is for the short tags of a dense row). */
export const EXIT_SHORT = {SL: "손절", LOCK: "잠금", LIQ: "청산", HALT: "멈춤", MANUAL: "수동", REV: "반대", JUDGE: "감독", TIME: "시간", TP: "익절", PAPER: "청산", OTHER: "청산", END: "끝"};

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
 * reaches the next trigger: the server's next_lock, from the config's ladder in either form).
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
          label: `${(ACCT[a.id] || {s: a.id}).s} ${p.locked ? "잠금" : "손절"}`});
      }
      if (a.kind === "paper" && p.locked && p.stop_initial) {
        kids.push({id: `lv:f:${a.id}`, parent: id, group: "risk", price: p.stop_initial, tone: "down", dash: 2, alpha: 0.35, axis: false, label: "첫 손절"});
      }
      if (a.kind === "paper" && p.next_lock && p.next_lock.price) {
        kids.push({id: `lv:n:${a.id}`, parent: id, group: "risk", price: p.next_lock.price, tone: "accent", dash: 2, alpha: 0.5, axis: false,
          label: `다음 잠금 ${fmt.pct(p.next_lock.at, 0, false)}`});
      }
    }
    const p0 = g.items[0].p, letters = g.items.map((x) => (ACCT[x.a.id] || {s: x.a.id}).s).join("·");
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
  // two paper bots (owners 10/23): the title is the bot's name already, so the sub says what it is and who follows it
  const pb = a.kind === "paper" && PAPERS ? PAPERS.find((b) => b.id === a.id) : null;
  const o = {title: acctKo(a.id), sub: pb ? `페이퍼(연습) · ${(pb.followers || []).length ? `${pb.followers.join("·")}가 따라감` : "따라가는 실행기 없음"} · 모의`
    : a.kind === "paper" ? `${a.sub_ko || paperBotKo(null)} · 모의` : a.sub_ko || "실행기", cls: "lb-now"};
  if (a.kind === "live" && a.follows_ko) o.sub = `${o.sub} · ${a.follows_ko} 따라감`;       // two paper bots: which one it follows
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

/** The paper card's note while the 추세판단 봇 runs (the summary's trend_bot): its balance and closed trades are the
 *  whole account's, the bot before it included; the new bot's own count from the checkpoint (its trades only). */
export function paperSinceNote(d) {
  const tb = d && d.trend_bot;
  if (!tb || tb.since == null) return null;
  const n = d.checkpoint && d.checkpoint.n != null ? Number(d.checkpoint.n) : null;
  return [`${tb.name || "추세판단 봇"} ${fmt.kst(tb.since)} 시작 · 위 잔고와 닫힌 거래는 계좌 전체 (그 전 예전 봇 거래 포함)`
    + (n != null ? ` · 새 봇 닫힌 거래 ${fmt.int(n)}번` : "")];
}

const okNum = (x) => x != null && x !== "" && Number.isFinite(Number(x));
const MIN_MS = 60000, HOUR_MS = 3600000, DAY_MS = 86400000;
/** A wait in the owners' words: "40분" / "약 17시간" / "약 3일" (null: "—"). */
export function waitKo(ms) {
  if (!okNum(ms)) return "—";
  const m = Number(ms);
  if (m < HOUR_MS) return `${Math.max(1, Math.round(m / MIN_MS))}분`;
  if (m < 72 * HOUR_MS) return `약 ${Math.round(m / HOUR_MS)}시간`;
  return `약 ${Math.round(m / DAY_MS)}일`;
}
/** The 7/1~10/20 replay's expectation of a fresh start, as lines (dash/more/livetrend.py expect_of: 관제's next.expect,
 *  진입 가능성's expect, 성적 · 지도's empty.expect; [] when unread). 가상: the pages label it so. */
export function expectLines(x) {
  if (!x || x.state !== "ok") return [];
  const out = [];
  if (okNum(x.per_weekday)) {
    out.push(`평일 하루 약 ${Number(x.per_weekday).toFixed(1)}번 진입` + (okNum(x.zero_days) && okNum(x.weekdays)
      ? ` · 진입 없는 평일도 ${fmt.int(x.zero_days)}일 / ${fmt.int(x.weekdays)}일 (${fmt.pct(x.zero_share, 0, false)})` : ""));
  }
  if (okNum(x.wait_median_ms)) {
    out.push(`아무 평일 시각에서 다음 진입까지 가운데값 ${waitKo(x.wait_median_ms)}` + (okNum(x.wait_q1_ms) && okNum(x.wait_q3_ms)
      ? ` (4번 중 1번은 ${waitKo(x.wait_q1_ms)} 안, 4번 중 1번은 ${waitKo(x.wait_q3_ms)} 넘게)` : ""));
  }
  return out;
}
/** The replay's head line: '7/1~10/20 실제 1분봉으로 이 규칙을 다시 돌려 보면' (its window_kst; '지난 기간' without one). */
export function expectHead(x) {
  const win = ((x && x.window_kst) || []).map((d) => `${Number(String(d).slice(5, 7))}/${Number(String(d).slice(8, 10))}`).join("~");
  return `${win || "지난 기간"} 실제 1분봉으로 이 규칙을 다시 돌려 보면`;
}

export const notesEl = (notes) => (notes && notes.length ? h("div", {class: "lb-notes"}, notes.map((t) => h("p", {class: "lb-warn"}, t))) : null);
