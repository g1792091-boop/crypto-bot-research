// 홈 · 요약의 살아 있는 칸 (fill-home): 시장 지금 (7 coins from the store ticker), 지금 열린 포지션 (/api/board positions at
// the ticker's mark price), 방금 끝난 거래 (/api/trades?group=main, new rows on the stream's trade event) with today's best /
// worst 기존 36 accounts, and 오늘 회의 일정 (/api/office schedule: a countdown to the next fixed meeting and today's
// timeline). Also used by 회의 요약 › 회의 결론 (digest-day.js) for the countdown before the first meeting.
// HONESTY (CONTRACT.md §1): every number comes from the server; a countdown only counts down to a time the server sent
// (funding time, meeting hour); flashes only when a value really changed; DeepSeek and coin flips are counts only here
// (owners' D10 / D11: no money, no ROE for them outside the DeepSeek screen).
import {h, put, ui, fmt, motion} from "../core/pb.js";
import {tradeMeetSlot} from "./meet-links.js";

const COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"];
const LIVE_GROUPS = new Set(["core", "m5", "extra"]);        // money shown: 기존 36 / 5분봉 / 추가 계좌

/** "1:02:03" / "12:03" from a millisecond span (never negative). */
export function clock(ms) {
  const s = Math.max(0, Math.floor(ms / 1000));
  const hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
  const two = (x) => String(x).padStart(2, "0");
  return hh ? `${hh}:${two(mm)}:${two(ss)}` : `${two(mm)}:${two(ss)}`;
}

/** Unrealized ROE of an open position at a mark price (gross, before the exit fee): side x move / entry x leverage. */
export function liveRoe(pos, mark) {
  const e = Number(pos && pos.entry), m = Number(mark), lev = Number(pos && pos.leverage);
  if (!(e > 0) || !(m > 0) || !(lev > 0)) return null;
  return (Number(pos.side) > 0 ? 1 : -1) * (m - e) / e * lev;
}

/** The group of a board row as this page names it (fmt.groupOf). */
const gid = (a) => fmt.groupOf(a);

/** Open positions of a board: the money groups' rows (sorted by live ROE, best first) and the counts of the others. */
export function openRows(board, ticker) {
  const rows = [], other = {ds: 0, coin: 0};
  for (const a of (board && board.accounts) || []) {
    const p = a.position;
    if (!p) continue;
    const g = gid(a);
    if (LIVE_GROUPS.has(g)) {
      const t = ticker && ticker[p.symbol];
      const mark = t ? (t.mark ?? t.c) : null;
      rows.push({a, p, g, mark, roe: liveRoe(p, mark)});
    } else if (g in other) other[g]++;
  }
  rows.sort((x, y) => (y.roe ?? -1e9) - (x.roe ?? -1e9));
  return {rows, other};
}

/** Today's (KST) closed-trade P&L per 기존 36 account, best 3 and worst 3 ({id, pnl, n}). */
export function bestWorst(trades, since) {
  const by = new Map();
  for (const t of trades || []) {
    if (t.kind !== "strategy" || !(Number(t.exit_time) >= since)) continue;
    const x = by.get(t.account_id) || {id: t.account_id, strategy: t.strategy, timeframe: t.timeframe, kind: t.kind, pnl: 0, n: 0};
    x.pnl += Number(t.pnl) || 0; x.n++;
    by.set(t.account_id, x);
  }
  const xs = [...by.values()].sort((a, b) => b.pnl - a.pnl);
  return {best: xs.filter((x) => x.pnl > 0).slice(0, 3), worst: xs.filter((x) => x.pnl < 0).slice(-3).reverse(), accounts: xs.length,
    trades: xs.reduce((s, x) => s + x.n, 0)};
}

// ---------------------------------------------------------------------------------------------------- 시장 지금
export function marketStrip(ctx) {
  const cells = new Map();
  const box = h("div", {class: "hl-mkt", role: "list", "aria-label": "시장 지금: 7개 코인"});
  const el = h("section", {class: "hl-mktwrap", "aria-label": "시장 지금"},
    h("div", {class: "hl-mhead"}, ui.plate("시장 지금"), h("span", {class: "muted hl-small"}, "바이낸스 선물 · 5초마다 · 펀딩은 8시간마다 정산")),
    box);
  let tk = null;
  function cell(sym) {
    let c = cells.get(sym);
    if (c) return c;
    const px = h("b", {class: "num hl-px"}, "—"), ch = h("span", {class: "num hl-ch"}), fr = h("span", {class: "num"}), cd = h("span", {class: "num"});
    c = {el: h("a", {class: "hl-coin", role: "listitem", href: ctx.href("chart", sym), title: `${fmt.coin(sym)} 차트 열기`},
      h("span", {class: "hl-cn"}, fmt.coin(sym)), px, ch, h("span", {class: "hl-fund muted"}, "펀딩 ", fr), h("span", {class: "hl-fund muted"}, "정산까지 ", cd)), px, ch, fr, cd, last: null};
    cells.set(sym, c);
    return c;
  }
  function render() {
    if (!tk) { put(box, ui.notYet("시세 수집 전")); return; }
    const syms = COINS.filter((s) => tk[s]);
    if (!syms.length) { put(box, ui.notYet("시세 수집 전")); return; }
    if (box.querySelectorAll(".hl-coin").length !== syms.length) { put(box, syms.map((s) => cell(s).el)); box.style.setProperty("--n", String(syms.length)); }
    for (const s of syms) {
      const t = tk[s], c = cell(s);
      const p = t.mark ?? t.c;
      const txt = fmt.price(p);
      if (c.last != null && txt !== c.px.textContent) motion.flashPrice(c.px, p > c.last ? "up" : "down");
      c.px.textContent = txt; c.last = p;
      c.ch.textContent = t.p != null ? fmt.pctOf(t.p, 2, true) : "—";
      c.ch.className = ["num", "hl-ch", fmt.tone(t.p, c.ch.textContent)].join(" ");
      c.fr.textContent = t.r != null ? fmt.pctOf(t.r * 100, 4, true) : "—";
    }
    tick();
  }
  function tick() {
    if (!tk) return;
    const now = Date.now();
    for (const [s, c] of cells) { const T = tk[s] && tk[s].T; c.cd.textContent = T ? clock(T - now) : "—"; }
  }
  ctx.watch("ticker", (t) => { if (t && typeof t === "object") { tk = t; render(); } });
  ctx.every(1000, tick, {now: false});
  render();
  return el;
}

// ---------------------------------------------------------------------------------------------------- 지금 열린 포지션
export function openCard(ctx) {
  const list = h("div", {class: "hl-pos", role: "list"}, motion.shimmer(3));
  const sub = h("span", {class: "sub"});
  const otherLine = h("p", {class: "muted hl-small"});
  const card = ui.card({plate: "지금 열린 포지션", cls: "hl-poscard", acts: [sub]}, list, otherLine, ui.assume("open"));
  const st = {b: null, t: null, seen: new Map()};
  const rowEls = new Map();
  function row(x) {
    const id = x.a.account_id;
    let r = rowEls.get(id);
    const key = `${x.p.symbol}|${x.p.entry_time}`;
    if (!r || r.key !== key) {
      const roe = h("b", {class: "num hl-roe"});
      const p = x.p;
      const name = fmt.acctParts(x.a);
      const guard = p.lock_roe != null ? h("span", {class: "up"}, `잠금 ROE ${fmt.pct(p.lock_roe, 0)}`)
        : p.stop != null ? h("span", {class: "muted"}, `손절 ${fmt.price(p.stop)}`) : h("span", {class: "muted"}, "손절선 —");
      r = {key, roe, last: null, el: h("a", {class: "hl-prow", role: "listitem", href: ctx.href("account", id), title: `${id} 계좌 열기`},
        h("span", {class: "hl-pname"}, h("span", {class: "hl-tf"}, name.tf), h("span", {class: "hl-nm"}, name.name)),
        h("span", {class: "hl-pcoin"}, h("b", null, fmt.coin(p.symbol)), " ", ui.sideTag(p.side), h("span", {class: "muted num"}, ` ${fmt.lev(p.leverage)}`)),
        h("span", {class: "hl-pent num muted"}, `진입 ${fmt.price(p.entry)}`), h("span", {class: "hl-pguard"}, guard), roe)};
      rowEls.set(id, r);
    }
    const shown = x.roe == null ? "—" : fmt.pct(x.roe, 1);
    if (r.last != null && r.last !== shown && x.roe != null) motion.flash(r.roe, x.roe > (r.lastV ?? 0) ? "up" : "down");
    r.roe.textContent = shown; r.roe.className = ["num", "hl-roe", fmt.tone(x.roe, shown)].join(" ");
    r.last = shown; r.lastV = x.roe;
    return r.el;
  }
  function render() {
    if (!st.b) return;
    const {rows, other} = openRows(st.b, st.t);
    const live = new Set(rows.map((x) => x.a.account_id));
    for (const k of [...rowEls.keys()]) if (!live.has(k)) rowEls.delete(k);
    sub.textContent = rows.length ? `${fmt.int(rows.length)}개 · ROE 높은 순` : "";
    if (!rows.length) put(list, ui.empty("기존 36 · 5분봉 · 추가 계좌에 지금 열린 포지션이 없습니다"));
    else put(list, rows.map(row));
    otherLine.textContent = `그 밖에 딥시크 ${fmt.int(other.ds)} · 동전 봇 ${fmt.int(other.coin)} 포지션 (개수만)`
      + " · ROE = 마크 가격 기준, 증거금 대비";
  }
  card.setBoard = (b) => { st.b = b; render(); };
  ctx.watch("ticker", (t) => { if (t && typeof t === "object") { st.t = t; render(); } });
  return card;
}

// ---------------------------------------------------------------------------------------------------- 방금 끝난 거래
export function tradesCard(ctx) {
  const list = h("div", {class: "hl-trades", role: "list"}, motion.shimmer(4));
  const bw = h("div", {class: "hl-bw"});
  const card = ui.card({plate: "방금 끝난 거래", cls: "hl-trcard",
    acts: [h("a", {class: "btn-line", href: ctx.href("positions")}, "거래 전체 →")]}, h("div", {class: "hl-trgrid"}, bw, list),
  ui.note("기존 36 · 5분봉 · 추가 계좌만 · 딥시크와 동전 봇은 빠짐 · 누르면 그 계좌"), ui.assume());
  const seen = new Set();
  let first = true, busy = false, coreAt = 0;     // the day list (up to 2,000 rows) at most once a minute
  const tRow = (t) => {
    const ret = h("span", {class: ["num", "hl-tret", fmt.tone(t.roe)]}, t.roe != null ? fmt.pct(t.roe, 1) : "—");
    const usd = h("b", {class: ["num", fmt.tone(t.pnl)]}, fmt.money(t.pnl, true));
    const nm = fmt.acctParts(t);
    return h("a", {class: "hl-trow", role: "listitem", href: ctx.href("account", t.account_id), dataset: {id: String(t.id)}},
      h("span", {class: "num muted hl-tt"}, fmt.hm(t.exit_time)),
      h("span", {class: "hl-pname"}, h("span", {class: "hl-tf"}, nm.tf), h("span", {class: "hl-nm"}, nm.name)),
      h("span", {class: "hl-pcoin"}, h("b", null, fmt.coin(t.symbol)), " ", ui.sideTag(t.side), h("span", {class: "muted num"}, ` ${fmt.lev(t.leverage)}`)),
      h("span", {class: ["hl-why", t.exit_reason === "SL" || t.exit_reason === "LIQ" ? "down" : t.exit_reason === "LOCK" || t.exit_reason === "TP" ? "up" : "muted"]}, fmt.reasonKo(t.exit_reason)),
      ret, usd, tradeMeetSlot(ctx, t, {nested: true}));        // a losing trade: the loss meeting about it (meet-links.js)
  };
  function renderBW(rows) {
    const since = fmt.kstMidnight();
    const r = bestWorst(rows, since);
    if (!r.accounts) { put(bw, h("p", {class: "muted hl-small"}, "오늘 닫힌 기존 36 거래가 아직 없습니다 · 가장 잘한·못한 계좌는 첫 거래 뒤")); return; }
    // 표본 적음 is per account: a row ranked on fewer than 30 closed trades says so (every row on day 0-1)
    const thin = (x) => x.n < 30;
    const one = (x) => h("a", {class: "hl-bwr", href: ctx.href("account", x.id), title: thin(x) ? `오늘 거래 ${fmt.int(x.n)}건뿐 · 표본 적음` : null},
      h("span", {class: "hl-nm"}, fmt.acctName(x)),
      h("b", {class: ["num", fmt.tone(x.pnl)]}, fmt.money(x.pnl, true)), h("span", {class: "muted num"}, `${fmt.int(x.n)}건${thin(x) ? " · 표본 적음" : ""}`));
    const shown = r.best.concat(r.worst);
    // the day list is the newest 2,000 core trades: when that cuts off part of today, the note says so
    const cut = rows.length >= 2000 && rows.reduce((m, t) => Math.min(m, Number(t.exit_time) || Infinity), Infinity) > since;
    put(bw, h("div", {class: "hl-bwc"}, h("div", {class: "hl-bwk up"}, "오늘 가장 잘한 계좌"), r.best.length ? r.best.map(one) : h("span", {class: "muted"}, "아직 없음")),
      h("div", {class: "hl-bwc"}, h("div", {class: "hl-bwk down"}, "오늘 가장 못한 계좌"), r.worst.length ? r.worst.map(one) : h("span", {class: "muted"}, "아직 없음")),
      h("p", {class: "muted hl-small hl-bwn"}, ui.pill("참고", "thin"), ` 기존 36만 · 오늘 0시부터 닫힌 거래 손익 (USDT) · 계좌 ${fmt.int(r.accounts)}개 · 거래 ${fmt.int(r.trades)}건`,
        cut ? " · 최근 2,000건만 (오늘 일부)" : "",
        shown.some(thin) ? " · 계좌마다 거래가 30건 미만이라 표본 적음 (운일 수 있음)" : ""));
  }
  async function load() {
    if (busy) return;
    busy = true;
    try {
      const wantCore = Date.now() - coreAt > 55000;
      const [main, core] = await Promise.all([ctx.api("/api/trades?group=main&limit=12"), wantCore ? ctx.api("/api/trades?group=core&limit=2000") : null]);
      if (!ctx.alive()) return;
      const rows = (Array.isArray(main) ? main : []).slice().sort((a, b) => (Number(b.exit_time) || 0) - (Number(a.exit_time) || 0));  // newest close first
      if (!rows.length) put(list, ui.empty("아직 끝난 거래가 없습니다"));
      else {
        const els = rows.map((t) => { const e = tRow(t); if (!first && !seen.has(t.id)) motion.slideIn(e); seen.add(t.id); return e; });
        put(list, els);
      }
      first = false;
      if (wantCore) { coreAt = Date.now(); renderBW(Array.isArray(core) ? core : []); }
    } catch (e) {
      if (first && ctx.alive()) put(list, ui.errorBox(e, () => load()));
    } finally { busy = false; }
  }
  load();
  ctx.every(60000, load, {now: false});
  let t = null;
  ctx.on("trades", () => { clearTimeout(t); t = setTimeout(() => ctx.alive() && load(), 1500); });
  ctx.track(() => clearTimeout(t));
  return card;
}

// ---------------------------------------------------------------------------------------------------- 오늘 회의 일정
const WHAT_KO = {
  morning: "장세 → 파생·쏠림 → 전략가 → 반론 → 팀장 요약 (텔레그램)",
  bull_bear: "코인 하나씩 낙관·비관 토론 (24시간 뒤 코드가 채점, 거래 없음)",
  ranking: "기존 36 상위·하위 매매법 검토 (텔레그램)",
  tf_split: "같은 매매법의 봉별 성적이 크게 갈렸을 때만 봉 비교",
  evening: "하루 손익 복기 → 가정 분석 → 리스크 → 팀장 3줄 요약",
};

/** Today's fixed meetings with their state: 끝 (a finished meeting of that kind today), 진행 중 (running now),
 *  지남 (the hour passed, no record of it), 예정 (later today). */
export function timeline(office, now = Date.now()) {
  const sc = office && office.schedule;
  const slots = (sc && sc.slots) || [];
  const day0 = fmt.kstMidnight(now);
  const ran = new Set(((office && office.recent) || []).map((m) => m.trigger));
  const run = new Set(((office && office.running) || []).map((m) => m.trigger));
  return slots.map((s) => {
    const at = day0 + s.hour * 3600000;
    const state = run.has(s.trigger) ? "run" : ran.has(s.trigger) ? "done" : at <= now ? "past" : "next";
    return {...s, at, state, what: WHAT_KO[s.trigger] || s.where || ""};
  });
}
const STATE_KO = {run: ["진행 중", "live"], done: ["끝", "good"], past: ["지남 · 기록 없음", "thin"], next: ["예정", "thin"]};

export function meetSchedule(ctx, o = {}) {
  const cd = h("b", {class: "num hl-cd"}, "—");
  const cdk = h("span", {class: "hl-cdk"});
  const tl = h("ol", {class: "hl-tl"});
  const el = ui.card({plate: o.plate || "오늘 회의 일정", cls: ["hl-meet", o.cls].filter(Boolean).join(" "),
    acts: [h("a", {class: "btn-line", href: ctx.href("office")}, "회의실 →")]},
  h("div", {class: "hl-cdrow"}, h("span", {class: "muted"}, "다음 정기 회의까지"), cd, cdk), tl,
  ui.note("정기 회의 시간은 서버가 보낸 오늘 일정 · 손실·사고·두 분 글 회의는 시간 없이 따로 열립니다"));
  let of = null;
  function tick() {
    const nx = of && of.schedule && of.schedule.next;
    if (!nx || !nx.at_ms) { cd.textContent = "—"; return; }
    cd.textContent = clock(nx.at_ms - Date.now());
  }
  el.set = (office) => {
    of = office || null;
    const nx = of && of.schedule && of.schedule.next;
    if (!of || !of.schedule) { put(tl, h("li", null, ui.notYet("일정 수집 전"))); cdk.textContent = ""; tick(); return; }
    cdk.textContent = nx ? `${nx.tomorrow ? "내일 " : ""}${nx.hhmm} ${nx.trigger_ko}` : "";
    put(tl, timeline(of).map((s) => {
      const [ko, cls] = STATE_KO[s.state];
      return h("li", {class: ["hl-tli", s.state]}, h("b", {class: "num"}, s.hhmm),
        h("span", {class: "hl-tlb"}, h("span", {class: "hl-tln"}, s.trigger_ko, h("span", {class: "muted"}, ` · ${s.where}`)), h("span", {class: "muted hl-small"}, s.what)),
        s.state === "run" ? ui.livePill("진행 중") : ui.pill(ko, cls));
    }));
    tick();
  };
  ctx.every(1000, tick, {now: false});
  return el;
}
