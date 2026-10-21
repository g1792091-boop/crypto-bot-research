// 실거래 › 기록 › 일지 (#/journal; owners 10/21: they look in now and then, often on a phone: "what happened while I was
// away?"): one feed, newest first with a line for each Korea-time day, of everything the 추세판단 봇 and the two
// real-money executors (바이비트 · WOO X Pro) did, from /api/v4/livebots/journal (dash/more/livejournal.py; every 60 s,
// every 15 s while the judgments are still being fetched). Read-only, like every 실거래 tab.
//   첫 줄    the span (24시간 · 3일 · 7일) and its count in one line: 신호 · 점검 통과 · 되돌림 대기 (옴) · 진입 · 청산 (순손익) ·
//            판단 바뀜; a count tapped shows its rows; what was not read says so (꺼짐 / 못 읽음 as —, never a 0)
//   고르기   전체 · 추세 · 신호 · 거래 · 실행기 · 안전 (with how many), a coin, 동전 쌍둥이도 보기 (the coin-flip twin's trades)
//   일지     20 rows a page: the Korea time, the kind's dot on a line, one sentence in the bots' own words (the 신호 tab's
//            reasons, the ⏳ message's wait words, the Telegram exit words), a second line with the why, the setting, the
//            gap to the paper's price, and a link to the tab that shows it (다시보기 · 추세 차트 · 신호 · 거래 · 안전 …)
// HONESTY: every row is a record the bots wrote (or a judgment change the 추세 차트 tab recomputes the same way); the
// paper's money is never shown as real money (페이퍼(연습) on its rows, 실거래 on the executors', a caption line for each);
// a source that is not there yet says 수집 전, one that cannot be read 못 읽음 with why; when the server had to cut rows it
// says which and from when; a failed refresh keeps the last answer dimmed with its age.
import {h, put, ui, fmt, local, serverNow, href} from "../core/pb.js";
import {acctKo, sourceState} from "./livebots-kit.js";

export const API = "/api/v4/livebots/journal";
const REFRESH_MS = 60 * 1000;
const BUSY_MS = 15 * 1000;                 // while judgments are still being fetched (the server asks Binance a little at a time)
const PAGE = 20;
const DAY = 24 * 3600 * 1000;
const KST_MS = 9 * 3600 * 1000;
const DOW = "일월화수목금토";
const COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"];
export const SPANS = [{id: "24", label: "24시간"}, {id: "72", label: "3일"}, {id: "168", label: "7일"}];
export const KINDS = [["all", "전체"], ["trend", "추세"], ["signal", "신호"], ["trade", "거래"], ["exec", "실행기"], ["safety", "안전"]];
const KIND_KO = Object.fromEntries(KINDS);
// the tab a row's link opens, in the menu's words
const LINK_KO = {replay: "다시보기", tchart: "추세 차트", signals: "신호", trades: "거래", pos: "포지션", cost: "비용", safety: "안전",
  health: "봇 상태", review: "검토"};
const has = (x) => x != null && x !== "" && Number.isFinite(Number(x));

// ================================================================ pure (node tests: tests/test_livejournal.py)
/** The rows a viewer asked for: a kind ("all" or one of KINDS), a coin ("" = every coin; a coin hides rows of no coin),
 *  the coin-flip twin's trades only when ``twin``. */
export function filterEvents(events, f) {
  return (events || []).filter((e) => (f.kind === "all" || !f.kind || e.kind === f.kind) && (!f.coin || e.symbol === f.coin)
    && (f.twin || !e.twin));
}

/** How many rows of each kind (the twin's trades counted only when shown): {all, trend, signal, ...}. */
export function kindCounts(events, f) {
  const out = Object.fromEntries(KINDS.map(([k]) => [k, 0]));
  for (const e of filterEvents(events, {...f, kind: "all"})) { out.all += 1; out[e.kind] = (out[e.kind] || 0) + 1; }
  return out;
}

/** Money with its sign: "+$12.30" / "−$4.00". */
export const signed = (x) => (has(x) ? `${Number(x) > 0 ? "+" : Number(x) < 0 ? "−" : ""}${fmt.usd(Math.abs(Number(x)))}` : "—");

/** The span's count line: [{id, ko, v (text), sub, kind (the filter a tap sets), title, tone}]; a count the server did
 *  not read (null) is "—" with why, never 0. */
export function countLine(d) {
  const c = (d && d.counts) || {};
  const off = d && d.state === "off";
  const why = off ? "추세판단 봇이 아니라 신호·판단 기록이 없어요" : "읽지 못했어요";
  const n = (x) => (has(x) ? fmt.int(x) : "—");
  const judgeH = d && d.judge ? d.judge.covers_h : 72;
  return [
    {id: "signals", ko: "신호", v: n(c.signals), kind: "signal", title: has(c.signals) ? "진입 매매법이 낸 신호" : why},
    {id: "passed", ko: "점검 통과", v: n(c.passed), kind: "signal", title: has(c.passed) ? "추세 판단과 진입 자리 검사를 통과 (그 신호는 모두 되돌림을 기다려요)" : why},
    {id: "waits", ko: "되돌림 대기", v: n(c.waits), sub: has(c.touched) ? `옴 ${fmt.int(c.touched)}` : null, kind: "signal",
      title: has(c.waits) ? "되돌림을 기다린 신호 · 옴 = 기다린 가격에 닿음" + (c.waiting ? ` · 지금 기다리는 중 ${fmt.int(c.waiting)}` : "") : why},
    {id: "entered", ko: "진입", v: n(c.entered), kind: "trade", title: has(c.entered) ? "페이퍼(연습) 진입" : "페이퍼 기록을 읽지 못했어요"},
    {id: "closed", ko: "청산", v: n(c.closed), sub: has(c.closed) && c.closed ? signed(c.pnl) : null, kind: "trade",
      tone: has(c.closed) && c.closed ? fmt.tone(c.pnl, signed(c.pnl)) : "",
      title: has(c.closed) ? "페이퍼(연습) 청산과 그 순손익 (진짜 돈 아님)" : "페이퍼 기록을 읽지 못했어요"},
    {id: "changes", ko: "판단 바뀜", v: n(c.changes), kind: "trend",
      title: has(c.changes) ? `코인별 1시간·4시간 추세 판단이 바뀐 수 (최근 ${judgeH}시간 안)` + (d.judge && d.judge.state !== "ok" ? " · 일부 코인은 아직 못 읽음" : "")
        : off ? why : "판단 기록을 아직 못 읽었어요"},
  ];
}

/** The Korea-time day of a time (days since 1970-01-01 KST). */
export const kstDay = (ms) => Math.floor((Number(ms) + KST_MS) / DAY);
/** A day line: "10/21 (화) · 오늘" / "· 어제" / "10/19 (일)". */
export function dayLabel(ms, now) {
  const d = kstDay(ms), today = kstDay(now);
  const tail = d === today ? " · 오늘" : d === today - 1 ? " · 어제" : "";
  return `${fmt.mmdd(ms)} (${DOW[(d + 4) % 7]})${tail}`;
}

/** The span in words: "최근 24시간 · 10/20 14:05부터". */
export function spanWords(d) {
  if (!d || !has(d.hours)) return "";
  const h0 = Number(d.hours);
  return `최근 ${h0 >= 48 ? `${fmt.int(h0 / 24)}일` : `${fmt.int(h0)}시간`} · ${fmt.kst(d.t0)}부터`;
}

/** The notes above the feed, in order: [{text, tone}]: the bot's state, how far the judgments go, what was cut. */
export function notesOf(d) {
  if (!d) return [];
  const out = [];
  if (d.state === "off") out.push({text: d.reason_ko || "추세판단 봇이 아니에요", tone: "thin", pill: "꺼짐"});
  else if (d.state === "missing" && d.sources && d.sources.paper && d.sources.paper.state === "ok") out.push({text: d.reason_ko, tone: "thin", pill: "수집 전"});
  const j = d.judge || {};
  if (j.note_ko) out.push({text: `${j.note_ko} (그 전 판단 바뀜은 안 보여요)`, tone: "thin"});
  if (j.pending) out.push({text: `추세 판단을 불러오는 중이에요 · ${fmt.int(j.read)}/${fmt.int(j.of)} (몇 초 뒤 더 보여요)`, tone: "warn"});
  else if (j.state === "error" || j.state === "partial") {
    const e = (j.errors || [])[0];
    out.push({text: `추세 판단 ${fmt.int((j.of || 12) - (j.read || 0))}칸을 못 읽었어요` + (e && e.reason_ko ? ` · ${e.reason_ko}` : ""), tone: "warn"});
  }
  for (const n of d.notes || []) out.push({text: n, tone: "thin"});
  const cp = d.capped;
  if (cp) {
    out.push({text: `기록이 많아 ${fmt.int(cp.cut)}개를 뺐어요 (전체 ${fmt.int(cp.total)}개) · `
      + (has(cp.low_from) ? `신호·판단 바뀜은 ${fmt.kst(cp.low_from)}부터만` : "신호·판단 바뀜은 빼고")
      + (has(cp.hi_from) ? ` · 나머지는 ${fmt.kst(cp.hi_from)}부터만` : " · 거래·실행기·안전은 모두 있어요"), tone: "warn"});
  }
  return out;
}

/** A row's link: {href, ko} or null. */
export function linkOf(e, mk = href) {
  if (!e || !e.link || !e.link.tab) return null;
  return {href: mk("livebots", e.link.tab, e.link.q || undefined), ko: LINK_KO[e.link.tab] || e.link.tab};
}

/** The small tag after a row's kind: whose money (페이퍼(연습) · 동전 쌍둥이 · 실거래) or nothing. */
export function moneyTag(e) {
  if (e.kind === "trade") return e.twin ? {ko: "동전 쌍둥이 (참고)", cls: "thin"} : {ko: acctKo("paper"), cls: "thin"};
  if (e.kind === "exec" && e.acct) return e.real ? {ko: "실거래", cls: "warn"} : {ko: "실행기 (실거래 아님)", cls: "thin"};
  return null;
}

// ================================================================ the view
/** journalView(ctx) -> {el, set()}: its own endpoint every 60 s (15 s while judgments are still being fetched). */
export function journalView(ctx) {
  const span0 = String(local.get("ljr-span", "24"));
  const st = {hours: SPANS.some((x) => x.id === span0) ? span0 : "24", kind: local.get("ljr-kind", "all"), coin: local.get("ljr-coin", ""),
    twin: !!local.get("ljr-twin", false), d: null, sig: "", okAt: 0, busy: false, lastAt: 0, want: null};
  if (!KIND_KO[st.kind]) st.kind = "all";
  if (st.coin && !COINS.includes(st.coin)) st.coin = "";
  const stateSlot = h("div", {class: "lb-slot"});
  // ---- the first block: the span, the count line, the notes
  const spanSeg = ui.seg(SPANS, st.hours, (id) => { st.hours = id; local.set("ljr-span", id); load().catch(() => {}); }, {label: "기간"});
  const spanTxt = h("p", {class: "ljr-span"});
  const countsBox = h("div", {class: "ljr-counts", role: "group", "aria-label": "이 기간에 있었던 일 (누르면 그 종류만)"});
  const notesBox = h("div", {class: "ljr-notes"});
  const hero = h("section", {class: "ljr-hero", "aria-label": "일지 요약"},
    h("div", {class: "ljr-hhead"}, h("div", {class: "ljr-htxt"}, h("h2", {class: "ljr-h2"}, "자리 비운 동안 있었던 일"), spanTxt), spanSeg),
    countsBox, notesBox);
  // ---- the pickers
  const kindSlot = h("div", {class: "ljr-kinds"});
  const coinSel = h("select", {class: "select ljr-coin", "aria-label": "코인"},
    h("option", {value: ""}, "모든 코인"), COINS.map((c) => h("option", {value: c}, fmt.coin(c))));
  coinSel.value = st.coin;
  coinSel.addEventListener("change", () => { st.coin = coinSel.value; local.set("ljr-coin", st.coin); drawFeed(true); });
  const twinBtn = h("button", {type: "button", class: "btn-line ljr-twin", "aria-pressed": String(st.twin),
    title: "동전 쌍둥이(COMBOFLIP@mix): 봇과 같은 때 같은 코인에 들어가고 방향만 동전으로 정한 비교용 페이퍼 계좌"}, "동전 쌍둥이도 보기");
  twinBtn.addEventListener("click", () => { st.twin = !st.twin; local.set("ljr-twin", st.twin); twinBtn.setAttribute("aria-pressed", String(st.twin)); drawFeed(true); });
  const picks = h("div", {class: "ljr-picks"}, kindSlot, h("div", {class: "ljr-pick2"}, coinSel, twinBtn));
  // ---- the feed
  const pg = ui.pager({size: PAGE, row: (e, i) => rowOf(e, i), empty: () => (st.d ? ui.empty(emptyKo()) : ui.empty("불러오는 중"))});
  const srcBox = h("div", {class: "ljr-srcs"});
  const feed = ui.card({title: "일지", sub: "최신이 위 · 한국 시간 · 줄마다 그 일을 자세히 보는 탭으로 가요", cls: "ljr-card"}, picks, srcBox,
    h("div", {class: "ljr-feed"}, pg.el));
  const foot = h("div", {class: "lb-foot"},
    ui.assumeLine(["closed", "open"], "페이퍼(연습) 손익은 진짜 돈이 아니에요"),
    ui.assumeLive("바이비트 · WOO X Pro 줄의 손익만 진짜 돈"));
  const body = h("div", {class: "ljr-body"}, hero, feed, foot);
  const el = h("div", {class: "ljr stack"}, stateSlot, body);
  let shown = [];

  function emptyKo() {
    const all = (st.d && st.d.events) || [];
    if (!all.length) return "이 기간에 기록된 일이 없어요";
    return "고른 조건에 맞는 기록이 없어요";
  }
  function rowOf(e, i) {
    const prev = i > 0 ? shown[i - 1] : null;
    const now = (st.d && st.d.now_ms) || serverNow();
    const first = i % PAGE === 0;
    const dayHead = (!prev || kstDay(prev.t) !== kstDay(e.t) || first)
      ? h("div", {class: "ljr-day", role: "presentation"}, h("span", null, dayLabel(e.t, now)), prev && kstDay(prev.t) === kstDay(e.t) ? h("small", null, " (이어서)") : null)
      : null;
    const lk = linkOf(e, ctx.href || href);
    const tag = moneyTag(e);
    const setting = e.strategy && (e.kind === "signal" || e.kind === "trade") ? `${fmt.stratKo(e.strategy)} ${fmt.tfKo(e.tf)}` : null;
    return h("div", {class: "ljr-item", role: "listitem"}, dayHead,
      h("div", {class: ["ljr-row", "k-" + e.kind, e.tone ? "t-" + e.tone : "", e.twin ? "twin" : ""]},
        h("time", {class: "ljr-t num", title: fmt.kst(e.t)}, fmt.hm(e.t)),
        h("span", {class: "ljr-dot", "aria-hidden": "true"}),
        h("div", {class: "ljr-main"},
          h("p", {class: "ljr-top"}, h("span", {class: "ljr-kind"}, KIND_KO[e.kind] || e.kind),
            tag ? ui.pill(tag.ko, tag.cls) : null, h("span", {class: "ljr-text"}, e.text)),
          setting || e.detail ? h("p", {class: "ljr-sub"}, setting ? h("span", {class: "ljr-set"}, setting) : null,
            setting && e.detail ? " · " : null, e.detail || null) : null),
        lk ? h("a", {class: "ljr-go", href: lk.href, title: `${lk.ko} 탭에서 보기`, "aria-label": `${lk.ko} 탭에서 보기`},
          h("span", {class: "ljr-go-t"}, lk.ko), h("b", {"aria-hidden": "true"}, "→")) : h("span", {class: "ljr-go none", "aria-hidden": "true"})));
  }

  // ---------------------------------------------------------------- parts
  function drawHero() {
    const d = st.d;
    spanTxt.textContent = d ? spanWords(d) : "";
    put(countsBox, countLine(d).map((c) => h("button", {type: "button", class: ["ljr-count", c.v === "—" ? "na" : ""],
      title: c.title, onclick: () => setKind(c.kind)},
    h("span", {class: "ljr-ck"}, c.ko), h("b", {class: "ljr-cv num"}, c.v), c.sub ? h("small", {class: ["ljr-cs num", c.tone || ""]}, c.sub) : null)));
    put(notesBox, notesOf(d).map((n) => h("p", {class: ["ljr-note", n.tone]}, n.pill ? ui.pill(n.pill, "thin") : null, n.pill ? " " : null, n.text)));
  }
  function setKind(k) {
    st.kind = KIND_KO[k] ? k : "all";
    local.set("ljr-kind", st.kind);
    drawFeed(true);
  }
  function drawSources() {
    const s = (st.d && st.d.sources) || {};
    const bad = [];
    if (s.paper && s.paper.state !== "ok") bad.push(sourceState(s.paper, "페이퍼 봇 기록"));
    for (const x of s.execs || []) {
      if (x.state !== "ok") bad.push(sourceState(x, `${acctKo(x.id) || x.name_ko} 실행기 기록`));
      else if (x.steps_ko) bad.push(h("p", {class: "ljr-note warn"}, `${acctKo(x.id) || x.name_ko}: ${x.steps_ko}`));
    }
    if (s.checks && s.checks.state !== "ok") bad.push(sourceState(s.checks, "아침 점검·감시 기록"));
    put(srcBox, bad.length ? bad : null);
  }
  function drawFeed(resetPage) {
    const d = st.d;
    const f = {kind: st.kind, coin: st.coin, twin: st.twin};
    const counts = kindCounts(d ? d.events : [], f);
    // a kind the server did not read (꺼짐, 못 읽음) has no count: never a 0
    const c = (d && d.counts) || {};
    const unread = {signal: !has(c.signals), trend: !has(c.changes)};
    put(kindSlot, ui.seg(KINDS.map(([id, ko]) => ({id, label: d ? `${ko} ${unread[id] ? "—" : fmt.int(counts[id] || 0)}` : ko})), st.kind,
      (id) => setKind(id), {label: "종류", scroll: true}));
    shown = filterEvents(d ? d.events : [], f);
    pg.set(d ? shown : undefined, !resetPage);
  }
  const pending = () => !!(st.d && st.d.judge && st.d.judge.pending);
  async function load() {
    const want = st.hours;
    if (st.busy) { st.want = want; return; }
    st.busy = true;
    let d;
    try { d = await ctx.api(`${API}?hours=${want}`); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      if (st.d) { put(stateSlot, ui.staleNote(e, st.okAt, () => load().catch(() => {}))); ui.dim(body, true); }
      else put(stateSlot, ui.errorBox(e, () => load()));
      throw e;
    } finally {
      st.busy = false; st.lastAt = Date.now();
    }
    if (!ctx.alive()) return;
    if (st.want && st.want !== want) { st.want = null; return load(); }       // the span changed while this one was on its way
    st.want = null;
    if (String(d.hours) !== st.hours) return;
    put(stateSlot);
    ui.dim(body, false);
    st.okAt = serverNow();
    const sig = JSON.stringify({...d, now_ms: 0});
    const spanChanged = !st.d || String(st.d.hours) !== String(d.hours);
    if (st.d && sig === st.sig) return;                                       // the same records: nothing redrawn
    st.d = d; st.sig = sig;
    drawHero();
    drawSources();
    drawFeed(spanChanged);
  }
  drawHero();
  drawFeed(true);
  load().catch(() => {});
  ctx.every(BUSY_MS, () => { if (pending() || Date.now() - st.lastAt >= REFRESH_MS - 500) load().catch(() => {}); }, {now: false});
  if (ctx.watch) ctx.watch("board", () => { if (st.d) drawFeed(false); });          // the strategies' Korean names
  return {el, set() {}};
}
