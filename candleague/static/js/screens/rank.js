// #/rank 순위표 (RANK builder): the rule bot's v4 board (paperbot/dash/static/v4/screens/board.js, home-shared.js,
// board-table.js, board-motion.js) for the 후보 리그, top to bottom:
//   묶음 cards     후보 · 기존 36 / 후보 · 딥시크 / 비교 계좌 / 동전 던지기 (+ 전체 190개 보기): a click changes everything below
//   상위 · 하위    the 묶음's four tiles (계좌 · 포지션 중 · 시작보다 많은 계좌 · 파산) and its best / worst five by 잔고
//                  수익률, each row with its pixel character, small balance line, open-position pill (live ROE every 5 s)
//                  and the 동전 ▲▼ mark (참고)
//   전체 목록      the same rows, 10 a page, with search, 봉 / 종류 / 성격 / 정렬; or the dense 표 (the old table)
//   봉별 요약      per timeframe (참고) · CSV of the 묶음
// #/rank?g=<core|ds|cmp|flip|all>&sub=<quarter|exitonly|base> chooses the 묶음 (old ?role=&kind= links still work).
// Units (D-3): the rank and the big % are 잔고 수익률 (wallet / 5,000 - 1, closed trades); every ▲▼ comparison is on
// 한 번 평균 (the checkpoints' unit), so 순위표, 5계좌 비교 and 점검 진행 never contradict each other.
// HONESTY: comparisons are 참고, small samples say 표본 적음, live ROE is hidden while the engine replays from 10/01, its
// record is over 15 minutes old or the prices are over a minute old (poskit pricesLive); DeepSeek money follows the
// snapshot's switch (hidden = counted only, everywhere).
// 설치 뒤 진입만 (js/after.js, the switch under the head): the open-position pills on the rows, the 상위 · 하위 cards and
// the 표 show only positions entered after the install (one entered before reads "설치 전 진입 · 숨김"), and the position
// counts (포지션 중, the 묶음 cards' 포지션, 봉별 요약) are over those, labelled 설치 뒤만; the ranking, 잔고 수익률,
// balances and every comparison stay the full record from 10/01.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
import * as LK from "../lk.js";
import {serverNow, liveState as priceState} from "../live.js";
import {posPill, staleBanner, pricesLive, pxAgeKo} from "../poskit.js";
import {ROLES} from "../labels.js";
import {okGroup, okSub, groupKo, groupRows, ranking, hidden, walletRet, rankCards, rankTiles} from "./rank-cards.js";
import {rankRow, topBottom, listFilters, filterRows, sortRows, rankMemo, rankDeltas, motionNote} from "./rank-rows.js";
import {rankTable, tfSummary, csvRows, CSV_HEAD} from "./rank-table.js";
import {afterBar, openAfter, openBefore, beforeChip} from "../after.js";

export const css = "scr/rank.css";
const OLD_S = 15 * 60;                 // the snapshot is "old" (B8): no live ROE

/** The 묶음 an address asks for (new ?g=, or the old ?role=&kind= links). */
export function groupFromQuery(q = {}) {
  const g = okGroup(q.g);
  if (g) return {g, sub: g === "cmp" ? okSub(q.sub) : "all"};
  if (ROLES.includes(q.role)) {
    if (q.role === "cand") return {g: q.kind === "ds" ? "ds" : "core", sub: "all"};
    if (q.role === "flip") return {g: "flip", sub: "all"};
    return {g: "cmp", sub: okSub(q.role)};
  }
  return null;
}
/** May live ROE be shown for this snapshot (not replaying from 10/01, written in the last 15 minutes)? And the
 *  positions-doc shape poskit's banner and freshness line read. */
export function liveState(d, now = serverNow()) {
  if (!d || !d.accounts) return {allowed: false, doc: d ? {status: "준비 중"} : null};
  const age = d.generated_ms ? Math.max(0, (now - d.generated_ms) / 1000) : null;
  const doc = {done_ms: d.done_ms, generated_ms: d.generated_ms, catching_up: LK.catchingUp(d), old: age != null && age > OLD_S};
  return {allowed: !doc.catching_up && !doc.old, doc};
}

export async function mount(el, ctx) {
  try { await ctx.meta(); } catch (e) { /* Korean names fall back to the codes */ }
  if (!ctx.alive()) return;
  const q = ctx.params.query || {};
  const fromQ = groupFromQuery(q);
  const st = {g: fromQ ? fromQ.g : okGroup(local.get("rank-group", "core")) || "core", sub: fromQ ? fromQ.sub : okSub(local.get("rank-sub", "all")),
    view: local.get("rank-view", "card") === "table" ? "table" : "card", d: null, ix: null, allowed: false, sparks: new Map(), sparkAt: null,
    sparkNew: false, prevRet: null, moved: new Map(), memo: rankMemo("rank-memo")};
  const pills = new Set();
  const save = () => { local.set("rank-group", st.g); local.set("rank-sub", st.sub); ctx.setQuery(st.g === "core" ? {} : st.g === "cmp" && st.sub !== "all" ? {g: st.g, sub: st.sub} : {g: st.g}); };

  // ---------------------------------------------------------------- the frame
  const csvBtn = h("button", {class: "btn-line", type: "button", title: "고른 묶음의 계좌 전부 (엑셀로 열림; 숨긴 딥시크 금액은 빈 칸)", onclick: csv}, "순위표 CSV");
  const liveDot = K4.liveDot("시세 기다리는 중", "off");
  liveDot.classList.add("rk-live");
  const banner = h("div", {class: "rk-banner"});
  const allBtn = h("button", {type: "button", class: "btn-line k4-allbtn", "aria-pressed": "false", onclick: () => pick("all")}, "전체 보기");
  const cards = rankCards({onPick: (id) => pick(id)});
  const tiles = rankTiles();
  const subSeg = h("div", {class: "seg rk-sub", role: "tablist", "aria-label": "비교 계좌 고르기"},
    [{id: "all", label: "셋 다"}, {id: "quarter", label: "1/4 크기"}, {id: "exitonly", label: "청산만"}, {id: "base", label: "기본값"}].map((x) =>
      h("button", {type: "button", role: "tab", dataset: {id: x.id}, "aria-selected": String(x.id === st.sub), onclick: () => { st.sub = x.id; save(); render(true); }}, x.label)));
  const tb = topBottom();
  const moNote = h("div");
  const tbCard = ui.card({plate: "상위 · 하위", cls: "rk-tbcard", acts: [liveDot, subSeg]}, tiles, tb.el, moNote);
  const filters = listFilters({onChange: () => paintList(false)});
  const countEl = h("span", {class: "rk-count"});
  const viewSeg = h("div", {class: "seg rk-view", role: "tablist", "aria-label": "보기 고르기"},
    [{id: "card", label: "카드"}, {id: "table", label: "표"}].map((x) => h("button", {type: "button", role: "tab", dataset: {id: x.id},
      "aria-selected": String(x.id === st.view), onclick: () => { st.view = x.id; local.set("rank-view", x.id); paintView(); paintList(false); }}, x.label)));
  const list = ui.pager({size: 10, empty: "맞는 계좌가 없습니다", render: (items) => h("div", {role: "list", class: "rk-list"}, items.map((a) => row(a)))});
  const table = rankTable({onRow: (a) => { location.hash = `#/account/${encodeURIComponent(a.id)}`; }, pill: (a) => mkPill(a)});
  const listNote = h("div");
  const listCard = ui.card({plate: "전체 목록", acts: [viewSeg, countEl], cls: "rk-listcard"}, filters.el, list.el, table.el, listNote,
    h("p", {class: "assume"}, "모의 · 실제 시세 · 수수료·펀딩·슬리피지·강제청산 포함 · 10/01부터 실제 시세로 이어 돌린 기록 (백테스트 아님) · " +
      "순위·수익률·잔고는 닫힌 거래 기준 (열린 포지션 손익 제외) · 포지션 ROE는 지금 마크 가격 기준 (나갈 때 수수료 전)"));
  const tfBody = h("div", {class: "rk-tfbody"});
  const tfSub = h("span", {class: "sub"});
  const tfCard = ui.card({plate: "봉별 요약", cls: "rk-tfcard"}, tfBody,
    h("p", {class: "note"}, "잔고 중앙값·최고 계좌는 닫힌 거래 기준 · 동전보다 위·아래 = 자기 후보의 동전 계좌보다 한 번 평균이 위·아래인 계좌 수 (참고, 판정 아님) · 숨긴 딥시크 계좌는 돈 숫자에서 뺌"));
  tfCard.querySelector(".card-h").append(tfSub);
  const links = h("nav", {class: "rk-links", "aria-label": "다른 화면으로"}, h("span", {class: "muted"}, "더 보기"),
    h("a", {class: "btn-line", href: "#/compare"}, "5계좌 비교"), h("a", {class: "btn-line", href: "#/check"}, "점검 진행"),
    h("a", {class: "btn-line", href: "#/positions"}, "포지션"), h("a", {class: "btn-line", href: "#/fills"}, "체결 기록"));

  el.append(
    ui.screenHead("순위표", "묶음을 고르면 아래가 모두 그 묶음으로 바뀝니다", csvBtn),
    afterBar({cls: "rk-after"}),
    banner,
    h("section", {class: "k4-sec rk-sec", "aria-label": "묶음"}, K4.secRow("묶음", "같은 후보의 동전·기본값 계좌와 비교한 숫자는 모두 참고입니다 (판정은 점검 날에만)", allBtn), cards),
    tbCard, listCard, links, tfCard);

  // ---------------------------------------------------------------- pieces
  function mkPill(a) {
    // a hidden DeepSeek account: the pill reads only its coin and side (poskit posPill hidden), whatever the snapshot carries
    // 설치 뒤 진입만: a position entered before the install gets the muted "설치 전 진입 · 숨김" chip instead of its pill
    // (never a silent gap that reads as "no position"; the row's rank and numbers stay as they are)
    if (openBefore(a)) return beforeChip(a);
    if (!openAfter(a)) return null;
    const p = posPill(a, {allowed: st.allowed, hidden: hidden(a, st.d)});
    if (p) pills.add(p);
    return p;
  }
  function tickPills() {
    for (const p of pills) {
      if (!p.isConnected) { pills.delete(p); continue; }
      p.update({allowed: st.allowed});
    }
  }
  function spark(a) {
    const v = st.sparks.get(a.id);
    return v && v.length > 1 ? K4.miniSpark(v, {w: 56, h: 18, base: 5000, draw: st.sparkNew, label: "시작부터 지금까지 잔고 흐름 (닫힌 거래마다)"}) : null;
  }
  let flashQ = [];
  function row(a, rk) {
    const r = st.rk;
    const rank = rk != null ? rk : r && r.rank.has(a.id) ? r.rank.get(a.id) : null;
    const mixed = st.g === "cmp" || st.g === "all";
    return rankRow(a, {d: st.d, ix: st.ix, rk: rank, delta: rank != null ? st.deltas[a.id] : null, spark, pill: mkPill,
      role: mixed, kind: st.g === "cmp" || st.g === "flip" || st.g === "all", moved: st.moved, flash: flashQ});
  }
  function flushFlash() {
    const q2 = flashQ;
    flashQ = [];
    if (q2.length) requestAnimationFrame(() => { for (const [e, tone] of q2) K4.flashPrice(e, tone); });
  }
  function paintView() {
    list.el.hidden = st.view === "table";
    table.el.hidden = st.view !== "table";
    for (const b of viewSeg.querySelectorAll("button")) b.setAttribute("aria-selected", String(b.dataset.id === st.view));
    filters.show({kinds: st.g === "cmp" || st.g === "flip" || st.g === "all", sort: st.view === "card"});
  }
  function paintList(keep) {
    if (!st.d || !st.rk) return;
    const f = filters.value();
    const rows = filterRows(st.rows, f);
    countEl.textContent = `${groupKo(st.g, st.sub)} · ${fmt.int(rows.length)}계좌`;
    if (st.view === "table") table.set(rows, st.d, st.ix, st.rk.rank, keep, st.g === "cmp" || st.g === "all");
    else list.set(sortRows(rows, f.sort, st.d, st.rk.rank), keep);
    flushFlash();
  }
  let bannerKey = null;
  /** The live-ROE switch, the freshness line, and the banner (rebuilt only when its state changed, or with force). */
  function paintBanner(force) {
    const ls = liveState(st.d);
    const px = priceState();
    const fresh = pricesLive(px);
    st.allowed = ls.allowed && fresh;
    const ok = px.state === "ok" || px.state === "fake";
    if (ls.doc && ls.doc.status) liveDot.set("엔진 기록 준비 중", "off");
    else if (!ls.allowed) liveDot.set(ls.doc && ls.doc.catching_up ? "포지션 ROE 감춤 · 다시 계산 중" : "포지션 ROE 감춤 · 엔진 기록 멈춤", "warn");
    else if (ok) liveDot.set(`${px.state === "fake" ? "시험용 시세" : "실시간 시세"}${px.age_s == null ? "" : ` ${px.age_s < 60 ? `${Math.round(px.age_s)}초` : fmt.dur(px.age_s)} 전`} · ROE 5초마다`, "ok");
    else if (fresh) liveDot.set(`${pxAgeKo(px)} · ROE는 그 시세 기준`, "warn");
    else liveDot.set(`${px.state === "stale" ? pxAgeKo(px) : px.ko} · 포지션 ROE 감춤`, px.state === "stale" ? "warn" : "off");
    liveDot.title = "열린 포지션의 ROE = 지금 마크 가격 기준 (나갈 때 수수료 전) · 엔진이 10/01부터 다시 계산하는 동안, 기록이 15분 넘게 멈추거나 시세가 1분 넘게 지난 값이면 감춥니다";
    const key = ls.doc ? `${ls.doc.status || ""}|${ls.doc.catching_up}|${ls.doc.old}|${ls.doc.done_ms}` : "";
    if (force || key !== bannerKey) { bannerKey = key; put(banner, ls.doc ? staleBanner(ls.doc) : null); }
  }

  // ---------------------------------------------------------------- render
  function render(userSwitch) {
    const d = st.d;
    if (!d || !d.accounts) { put(tb.el.firstChild, ui.missing()); return; }
    if (st.g !== "cmp") st.sub = "all";
    st.ix = LK.index(d);
    st.rows = groupRows(d, st.g, st.sub);
    st.rk = ranking(d, st.rows);
    st.deltas = rankDeltas(st.memo.base, st.rk.shown, d);
    paintBanner(true);
    cards.update(d, st.ix, st.g);
    allBtn.setAttribute("aria-pressed", String(st.g === "all"));
    allBtn.textContent = `전체 ${fmt.int(d.accounts.length)}개 보기`;
    subSeg.hidden = st.g !== "cmp";
    for (const b of subSeg.querySelectorAll("button")) b.setAttribute("aria-selected", String(b.dataset.id === st.sub));
    const label = groupKo(st.g, st.sub);
    tiles.update(d, st.rows, label);
    const hidRow = (a) => row(a, null);
    tb.set({label, rk: st.rk, row: (a, rk) => row(a, rk), hidRow});
    put(moNote, motionNote(st.memo.base, st.rk.shown, {sparks: st.sparks.size > 0}));
    paintView();
    paintList(!userSwitch);
    put(listNote, h("p", {class: "refnote"}, h("b", null, "참고"),
      " · 동전 ▲▼ = 같은 후보의 동전 계좌(방향만 동전)보다 거래 한 번 평균이 위·아래 · 1/4 크기는 낙폭으로만 비교 · 판정이 아닙니다. 판정은 점검 날(",
      cpDates(d), ")에 점검 진행 화면의 기준으로만 합니다.", dsMoneyHidden(d) ? " 딥시크는 금액 숨김 설정이라 개수와 점검 라벨만 보입니다 (순위 없이 맨 뒤)." : ""));
    put(tfBody, tfSummary(d, st.ix, st.g, st.sub));
    tfSub.textContent = `${label} · 참고`;
    if (userSwitch) { K4.swap(tb.el); K4.swap(tfBody); }
    flushFlash();
  }
  /** The snapshot hides DeepSeek money (its switch, or a DeepSeek account without its wallet): the footnote says so only then. */
  const dsMoneyHidden = (d) => !(d && d.ds_money) || ((d && d.accounts) || []).some((a) => a.kind === "ds" && hidden(a, d));
  const cpDates = (d) => ((((d && d.watch) || {}).checkpoints) || []).map((c) => `${String(c.ko || c.id).replace(" 점검", "")} ${fmt.mmdd(c.ms).replace(/^0/, "").replace("/0", "/")}`).join(" · ") || "11/11 · 12/11 · 1/11";
  function pick(id) {
    const g = okGroup(id);
    if (!g) return;
    st.g = g;
    if (g !== "cmp") st.sub = "all";
    save();
    render(true);
  }
  function csv() {
    if (!st.d) return;
    const rows = filterRows(st.rows, {});
    const ordered = st.rk.shown.concat(st.rk.waiting, st.rk.hid).filter((a) => rows.includes(a));
    K4.downloadCsv(`candleague-rank-${st.g}${st.g === "cmp" && st.sub !== "all" ? "-" + st.sub : ""}.csv`, CSV_HEAD, csvRows(st.d, st.ix, ordered, st.rk.rank));
  }
  async function loadSparks(d) {
    if (!d || !d.generated_ms || st.sparkAt === d.generated_ms) return;
    st.sparkAt = d.generated_ms;
    try {
      const v = await ctx.api("/api/sparks");
      if (!ctx.alive() || !v || !v.sparks) return;
      const had = st.sparks.size > 0;
      st.sparks = new Map(Object.entries(v.sparks).filter(([id, xs]) => Array.isArray(xs) && !hidden((st.ix && st.ix.byId[id]) || null, st.d)));
      st.sparkNew = !had;
      render(false);
      st.sparkNew = false;
    } catch (e) {
      st.sparkAt = null;                        // ask again with the next snapshot
    }
  }

  // ---------------------------------------------------------------- data
  ctx.onLeague((d) => {
    if (!d || !d.accounts) { st.d = d; render(false); return; }
    const cur = Object.fromEntries(d.accounts.map((a) => [a.id, walletRet(a, d)]).filter(([, v]) => v != null));
    st.moved = new Map();
    if (st.prevRet) for (const [id, v] of Object.entries(cur)) {
      const p = st.prevRet[id];
      if (p != null && Math.abs(p - v) > 1e-9) st.moved.set(id, v > p ? "up" : "down");
    }
    st.prevRet = cur;
    st.d = d;
    render(false);
    st.moved = new Map();
    st.memo.save(Object.fromEntries(ranking(d, d.accounts).shown.map((a) => [a.id, walletRet(a, d)])));
    loadSparks(d);
  });
  ctx.onLive(() => { if (st.d) { paintBanner(); tickPills(); } });
  ctx.every(30000, () => { if (st.d) { paintBanner(true); tickPills(); } });
}
