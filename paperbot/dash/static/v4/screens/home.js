// 홈 · 요약 (builder A, CONTRACT.md section 4; reordered in the v4 additions, wave 1 ⑤). Phone order: the
// "지난번 본 뒤로" sheet (core/since.js, over the page) → the story rings (오늘의 하이라이트) → the head card (the 30-day
// question, the group race with the coin flips' band, above / below the same-timeframe coin median, the checkpoint
// progress in one line) → 오늘 per group → the group cards (each with its median line) → 상위·하위 of the chosen group
// (the 5분봉 group shows its 1:3 card with its three 5m coin flips instead) → the green LED balance bar → 최근 회의 →
// the way into '어떻게 돌아가나'. The full ranked list lives on 순위표 only (one link here, no second copy).
// HONESTY: every comparison is '참고' with refNote; every money card has assume(); LIVE / 회의 중 only from real state
// (stream.live(), /api/office running); numbers count to new values and tint only when the server's data changed; the
// race legend is the lines' own right ends (the legend always matches the curve, U1).
import {h, put, ui, fmt, derive, motion, stream, startTour, local} from "../core/pb.js";
import {groupCards, topBottom, groupKo, savedGroup, expInfo, judgedProgress, ORDER, MIN_TRADES} from "./home-shared.js";
import {todayStats, TODAY_KO, TODAY_ORDER} from "./home-today.js";
import {storyRing} from "./story-kit.js";
import {raceParts} from "./flow-kit.js";
import {rowMotion} from "./board-motion.js";
import {reelDuel} from "./reel-duel.js";
import {pixelRoad} from "./road-kit.js";

const DECISION_KO = {done: "결정", no_action: "행동 없음", failed: "멈춤", stopped_budget: "한도로 멈춤"};

export async function mount(el, ctx) {
  ctx.setTitle("홈");
  const st = {board: null, gs: null, summary: null, office: null, officeTried: false, ck: null, sel: savedGroup("home-group"), led: null, race: null};
  const href = (n, a, q) => ctx.href(n, a, q);

  // ---------------------------------------------------------------- 0. the story rings (오늘의 하이라이트)
  const ring = storyRing(ctx);
  ring.classList.add("home-ring", "home-o0");

  // ---------------------------------------------------------------- 1. headline card
  const dcount = h("span", {class: "home-dcount"}, h("b", null, "D+—"), " / 30");
  // the 30-day road (road-kit.js, wave 3) in place of the progress bar: one pixel cell per day, the owners on today
  const road = pixelRoad(ctx);
  const hsub = h("p", {class: "home-hsub"});
  // the group race (/api/v4/flow/race: each group's median balance, the coin flips' middle 50 % as a band); its legend
  // is the order now = the lines' right ends, so the numbers always match the curve. Until two real points: the
  // designed empty road (nothing made up). Its model also feeds the small line in each group card.
  const race = raceParts(ctx, {height: 92, css: false, short: true, onModel: (m) => { st.race = m; renderSparks(); }});
  const raceBox = h("div", {class: "home-race"}, h("div", {class: "home-rtop"}, h("span", {class: "home-rk"}, "묶음 레이스"), race.sub,
    h("span", {class: "grow"}), h("a", {class: "home-more", href: href("flow")}, "흐름 자세히 →")), race.chart, race.list);
  const wlA = ui.liveNum(null, {format: "int", cls: "up", flash: "accent"}), wlB = ui.liveNum(null, {format: "int", cls: "down", flash: "accent"});
  const wlBar = h("i");
  const wl = h("div", {class: "home-wl"},
    h("div", {class: "home-hrow"}, h("span", {class: "muted"}, "같은 봉 동전 봇 중앙값보다"), h("span", null, "위 ", wlA, " · 아래 ", wlB)),
    h("div", {class: "wl-bar", role: "img", "aria-label": "동전 봇 중앙값보다 위와 아래의 비율"}, wlBar));
  const wlNote = h("p", {class: "muted home-small"});
  const ckLine = h("div", {class: "home-ckline"});           // the checkpoint in one line (progress, never a verdict)
  const refBox = h("div");
  const hero = ui.card({hero: true, cls: "home-hero home-o1", label: "30일 실험 요약"},
    h("div", {class: "home-hrow"}, ui.plate("30일 실험"), dcount), road,
    h("h2", null, "동전 봇보다 나은 ", h("em", null, "매매법"), "이 있나?"), hsub, raceBox,
    ui.note("선 = 묶음 계좌 평가금(열린 포지션 포함)의 중앙값 · 회색 띠 = 동전 봇 가운데 50%"), wl, wlNote, ckLine, refBox, ui.assume());
  hero.dataset.tour = "headline";                       // the first-visit tour points here (core/tour.js)

  // ---------------------------------------------------------------- 2. LED balance bar
  const led = ui.ledBar({label: "모의 계좌 잔고"});
  led.classList.add("home-o6");

  // ---------------------------------------------------------------- 3. group cards
  const groups = groupCards({onPick: (id) => { st.sel = id; local.set("home-group", id); renderGroupParts(true); }});
  const toBoard = h("a", {class: "btn-line", href: href("board", null, {g: st.sel})}, "순위표 전체 보기");
  const groupSec = h("section", {class: "home-sec home-o4", "aria-label": "묶음", dataset: {tour: "groups"}},
    h("div", {class: "home-sec-row"}, ui.plate("묶음"), h("span", {class: "muted home-hint"}, "누르면 아래 상위·하위가 그 묶음으로 바뀝니다"), h("span", {class: "grow"}), toBoard),
    groups);

  // ---------------------------------------------------------------- 4. top 5 / bottom 5 (or the 5분봉 1:3 card)
  // the full ranked list is on 순위표 only (one link, no second copy here). Rank arrows since the last visit, small
  // balance lines and a tint on a return that really changed: board-motion.js (shared with 순위표).
  const tb = topBottom(ctx, {compact: true});
  const moNote = h("div");
  const toBoard2 = h("a", {class: "btn-line", href: href("board", null, {g: st.sel})}, "순위표 →");
  const ranksCard = ui.card({plate: "상위·하위", cls: "home-o5 home-ranks", acts: [toBoard2]}, tb, moNote);
  // the small balance lines only where the row has room for them (a PC); the caption follows
  const wide = typeof matchMedia === "function" && matchMedia("(min-width: 760px)").matches;
  const rowMo = rowMotion(ctx, ranksCard, {sparks: wide});
  const duel = reelDuel(ctx, {lazy: true, link: {href: href("strategies", "REEL_H1"), text: "5분봉 매매법 →"}});
  duel.classList.add("home-o5");
  duel.hidden = true;

  // ---------------------------------------------------------------- 5. today (the server's per-group count)
  const todayBody = h("div", {class: "stack tight"}, motion.shimmer(3));
  const nextEl = h("div", {class: "home-next"});
  const todaySub = h("span", {class: "sub"});
  const todayCard = ui.card({plate: "오늘", cls: "home-today home-o2", acts: [todaySub]}, todayBody, nextEl, ui.assume());

  // ---------------------------------------------------------------- 6. 최근 회의 (three stored lines -> 회의실)
  const meetBody = h("div", {class: "home-meets", role: "list"}, motion.shimmer(2));
  const meetCard = ui.card({plate: "최근 회의", cls: "home-o7", acts: [h("a", {class: "btn-line", href: href("office")}, "회의실 →")]}, meetBody);

  // ---------------------------------------------------------------- 7. 어떻게 돌아가나 (one compact card)
  const flow = ["신호", "진입", "레버리지", "청산", "손실 회의", "판정"];
  const howCard = ui.card({plate: "처음이라면", cls: "home-o8 home-how"},
    h("ol", {class: "home-flow", "aria-label": "봇의 하루 여섯 단계"}, flow.map((t, i) => h("li", null, h("span", {class: "n"}, String(i + 1).padStart(2, "0")), t))),
    h("div", {class: "row wrap"}, h("a", {class: "btn-y", href: href("howto")}, "어떻게 돌아가나"),
      h("a", {class: "btn-line", href: href("faq")}, "자주 묻는 질문"),
      h("button", {class: "btn-line", type: "button", onclick: () => startTour()}, "안내 다시 보기")),
    h("p", {class: "muted home-small"}, "AI 직원은 회의와 기록만 하고 거래하지 않습니다. 모든 계좌는 모의(가상 돈)입니다."));

  // PC: two columns (head card | 오늘 + 최근 회의), the LED bar, the group cards, then (상위·하위 or 1:3 | 처음이라면).
  // Phone: one column in the order of the home-o* classes (home.css).
  el.append(ui.screenHead("요약", "30일 모의 실험을 한눈에"), ring,
    h("div", {class: "home-wrap home-top"}, h("div", {class: "home-col"}, hero), h("div", {class: "home-col"}, todayCard, meetCard)),
    led, groupSec,
    h("div", {class: "home-wrap"}, h("div", {class: "home-col"}, ranksCard, duel), h("div", {class: "home-col"}, howCard)));

  // ================================================================ renderers
  function renderHero() {
    const s = st.summary, gs = st.gs;
    const x = expInfo(s);
    if (x) {
      put(dcount, h("b", null, `D+${x.day}`), ` / ${x.of}`);
      const n = gs ? gs.total.n : null;
      const xn = gs && gs.groups.extra ? gs.groups.extra.n : 0;
      hsub.textContent = `${x.k > 1 ? `${x.k}번째` : "첫"} 판정 ${fmt.date(x.verdictTs)} 09:00 · ${fmt.int(x.left)}일 남음`
        + (n != null ? ` · 계좌 ${fmt.int(n - xn)}개${xn ? ` + 추가 ${fmt.int(xn)}개` : ""}` : "");
      put(refBox, ui.refNote(x.verdictTs));
    } else {
      put(dcount, h("b", null, "시작 전"));
      hsub.textContent = "봇이 아직 첫 계좌를 만들지 않았습니다.";
      put(refBox, ui.refNote(null));
    }
    if (!gs) return;
    // U1: the race legend above is the lines' own right ends; these counts are every strategy account (기존 36 ·
    // 딥시크 · 5분봉) against the coin-flip median of its own timeframe
    wlA.update(gs.strat.above); wlB.update(gs.strat.below);
    const tot = gs.strat.above + gs.strat.below;
    wlBar.style.setProperty("--w", (tot ? gs.strat.above / tot * 100 : 0) + "%");
    wlNote.textContent = `매매법 계좌 ${fmt.int(gs.strat.n)}개(기존 36 · 딥시크 · 5분봉)를 각자 같은 봉 동전 봇 3개와 비교 · 닫힌 거래 기준`;
  }

  // the small median line in each group card: the race's own series (one request serves the head card and the cards)
  function renderSparks() {
    const m = st.race;
    if (!m) return;
    groups.sparks(Object.fromEntries(m.lanes.map((l) => [l.id, l.v])));
  }

  // the checkpoint, one line: progress before the verdict (counts only), the verdict's counts after it
  function renderCheckpoint() {
    const ck = st.ck, b = st.board;
    if (!b) return;
    if (ck && ck.ready) {
      const c = ck.counts || {};
      put(ckLine, h("a", {class: "home-ckl", href: href("checkpoint")}, h("span", {class: "muted"}, `${ck.day ?? "—"}일째 판정`),
        ui.pill(`통과 ${fmt.int((c["2차 통과"] || 0) + (c["1차 합격"] || 0))}`, "good"), ui.pill(`불합격 ${fmt.int(c["불합격"] || 0)}`, "bad"),
        ui.pill(`보류 ${fmt.int(c["보류"] || 0)}`, "thin"), h("span", {class: "home-cka", "aria-hidden": "true"}, "→")));
      return;
    }
    const p = judgedProgress(b);
    put(ckLine, h("a", {class: "home-ckl", href: href("checkpoint"), title: `거래 ${MIN_TRADES}건이 안 된 계좌는 판정 날 '보류' · 진행 상황일 뿐 판정 아님`},
      h("span", null, "판정 대상 ", h("b", {class: "num"}, fmt.int(p.n))), h("span", {class: "muted"}, " · "),
      h("span", null, `${MIN_TRADES}건 넘음 `, h("b", {class: "num"}, fmt.int(p.ready))), h("span", {class: "home-cka", "aria-hidden": "true"}, " →")));
  }

  function renderLed() {
    const gs = st.gs;
    if (!gs) return;
    const t = todayStats(st.summary, st.board);
    let stats = [`계좌 ${fmt.int(gs.total.n)}개 합계`];
    if (t.ready && t.byGroup) stats = stats.concat([`오늘 거래 ${fmt.int(t.total.trades)}`, `이긴 거래 ${fmt.int(t.total.wins)}`, `강제청산 ${fmt.int(t.total.liq)}`]);
    else if (t.ready) stats = stats.concat([`오늘 거래 ${fmt.int(t.total.trades)}`, `강제청산 ${fmt.int(t.total.liq)}`]);
    st.led = {total: gs.total.wallet, initialTotal: gs.total.initial, live: stream.live(), curve: st.total || null, stats,
      right: ORDER.filter((g) => gs.groups[g]).map((g) => ({k: groupKo(g), v: gs.groups[g].pnl})),
      caption: `${ui.ASSUME_KO} · 잔고 = 닫힌 거래 기준 (열린 포지션 손익 제외) · 아래·옆 숫자는 묶음별 시작부터 손익`};
    led.update(st.led);
  }
  const relive = () => { if (st.led) { st.led.live = stream.live(); led.update(st.led); } };

  function renderGroupParts(animate) {
    const b = st.board, gs = st.gs;
    if (!b || !gs) return;
    if (st.sel !== "all" && !gs.groups[st.sel]) st.sel = "core";
    groups.update(b, gs, st.sel);
    renderSparks();
    toBoard.setAttribute("href", href("board", null, {g: st.sel}));
    toBoard2.setAttribute("href", href("board", null, {g: st.sel}));
    // 5분봉 is one account: its 1:3 card (the reel vs its three 5m coin flips) takes the top / bottom list's place
    const m5 = st.sel === "m5";
    const was = !duel.hidden;
    ranksCard.hidden = m5;
    duel.hidden = !m5;
    duel.set(b);
    duel.show(m5);
    if (m5) { if (animate && !was) motion.swap(duel); return; }
    rowMo.update(b, st.sel);
    tb.set(b, gs, st.sel);
    put(moNote, rowMo.note(st.sel));
    if (animate) motion.swap(tb);
  }

  // today: one line per group (P&L, trades, wins, liquidations, busts) from the server's own count
  const trows = new Map();
  function tRow(id) {
    let r = trows.get(id);
    if (r) return r;
    const v = ui.liveNum(null, {dec: 2, sign: true, tone: true, cls: "tv", flash: true});
    const meta = h("span", {class: "tm"});
    r = {el: h("div", {class: "home-trow", role: "listitem"}, h("span", {class: "tn"}, TODAY_KO[id] || groupKo(id)), v, meta), v, meta};
    trows.set(id, r);
    return r;
  }
  function renderToday() {
    const s = st.summary;
    if (!s || !s.today || !st.board) return;
    todaySub.textContent = `${fmt.date(s.today.since)} 0시부터`;
    const t = todayStats(s, st.board);
    if (t.byGroup) {
      // 추가 계좌 only once one has traded or gone bust today (none exist before the first approval)
      const ids = TODAY_ORDER.filter((id) => id === "extra" ? !!(t.groups.extra && (t.groups.extra.trades || t.groups.extra.busts))
        : !!(t.groups[id] || (st.gs && st.gs.groups[id])));
      const rows = ids.map((id) => {
        const x = t.groups[id] || {trades: 0, wins: 0, pnl: 0, liq: 0, busts: 0};
        const r = tRow(id);
        r.v.update(x.pnl);
        put(r.meta, h("span", null, `거래 ${fmt.int(x.trades)}`),
          h("span", null, `이김 ${fmt.int(x.wins)}${x.trades ? ` (${fmt.pct(x.wins / x.trades, 0, false)})` : ""}`),
          x.liq ? h("span", {class: "down"}, `강제청산 ${fmt.int(x.liq)}`) : null,
          x.busts ? h("span", {class: "down"}, `파산 ${fmt.int(x.busts)}`) : null);
        return r.el;
      });
      put(todayBody, h("div", {role: "list", class: "home-tlist"}, rows),
        h("p", {class: "muted home-small"}, "5분봉 = 릴스 1개 · 동전 봇 = 5분봉 3개 포함 (서버 집계)"));
    } else {
      put(todayBody, h("p", {class: "ink2"}, `모든 묶음: 거래 ${fmt.int(t.total.trades)} · 강제청산 ${fmt.int(t.total.liq)}`),
        h("p", {class: "muted home-small"}, "묶음별 오늘 숫자는 서버가 묶음별 합계를 보내면 보입니다."));
    }
  }

  function renderNext() {
    const items = [];
    const nx = st.office && st.office.schedule && st.office.schedule.next;
    if (nx) items.push(h("li", null, h("b", null, `${nx.tomorrow ? "내일 " : ""}${nx.hhmm}`), ` 정기 회의 · ${nx.trigger_ko}`, nx.where ? ` (${nx.where})` : ""));
    const now = Date.now();
    for (const e of ((st.summary && st.summary.events) || []).slice(0, 2)) {
      const d = Math.ceil((e.ts_ms - now) / 86400000);
      items.push(h("li", null, h("b", null, fmt.kst(e.ts_ms)), ` ${e.name_ko}`, d >= 1 ? h("span", {class: "muted"}, ` · ${fmt.int(d)}일 뒤`) : h("span", {class: "accent"}, " · 오늘")));
    }
    put(nextEl, items.length ? h("div", {class: "home-bwh"}, "다음 일정") : null, items.length ? h("ul", {class: "home-nextl"}, items) : null);
  }

  // 최근 회의: the running meetings (회의 중 only from /api/office running) and the newest finished ones, three lines
  function renderMeetings() {
    if (!st.officeTried) return;
    const o = st.office;
    if (!o || o.ready === false) { put(meetBody, ui.empty("아직 회의 기록이 없습니다")); return; }
    const line = (m, running) => h("a", {class: "home-mrow", role: "listitem", href: href("rooms", m.room_id)},
      h("span", {class: "rk num"}, fmt.hm(running ? m.started_ts : m.ended_ts || m.started_ts)),
      h("span", {class: "home-mt"}, h("b", null, m.title || m.room_id), ` · ${running ? m.trigger_ko || "" : String(m.decision || DECISION_KO[m.status] || m.trigger_ko || "").replace(/^\s*🧾\s*/u, "")}`),
      running ? ui.pill("회의 중", "accent") : null);
    const rows = [...(o.running || []).map((m) => line(m, true)), ...(o.recent || []).map((m) => line(m, false))].slice(0, 3);
    put(meetBody, rows.length ? rows : ui.empty("오늘 회의가 아직 없습니다"));
  }

  // ================================================================ data
  const onBoard = (b) => {
    if (!b) return;
    st.board = b; st.gs = derive.groupStats(b);
    renderHero(); renderLed(); renderGroupParts(false); renderCheckpoint(); renderToday();
  };
  const onSummary = (s) => {
    if (!s) return;
    st.summary = s;
    renderHero(); renderNext(); renderToday(); renderLed();
  };

  // first data before the first paint (the router's shimmer covers this wait); the shell keeps board and summary warm
  const [b0, s0] = await Promise.all([ctx.store.need("board", 60000).catch((e) => e), ctx.store.need("summary", 60000).catch((e) => e)]);
  if (!ctx.alive()) return;
  if (b0 instanceof Error) {
    el.insertBefore(ui.errorBox(b0, () => ctx.store.refresh("board").catch(() => {})), el.children[1] || null);
  }
  ctx.watch("board", onBoard);
  ctx.watch("summary", onSummary);
  ctx.watch("checkpoint", (ck) => { if (ck) { st.ck = ck; renderCheckpoint(); } });
  if (s0 instanceof Error) put(todayBody, ui.errorBox(s0, () => ctx.store.refresh("summary").catch(() => {})));

  // the office: refreshed every 30 s (shared cache) and when a room has a new message
  const office = async (maxAge) => {
    try { st.office = await ctx.store.need("office", maxAge); } catch { /* the strip says so below */ }
    if (!ctx.alive()) return;
    st.officeTried = true;
    renderMeetings(); renderNext();
  };
  office(25000);
  ctx.every(30000, () => office(25000), {now: false});
  let roomT = null;
  ctx.on("rooms", () => { clearTimeout(roomT); roomT = setTimeout(() => ctx.alive() && office(0), 900); });
  ctx.track(() => clearTimeout(roomT));

  // live: the balance bar's LIVE follows the real stream; a closed trade refreshes the server's day count
  // A closed trade (a real stream event) also shows its amount once next to the LED total: one chip at most every
  // 3 s (a burst is summed), never on a timer, skipped under prefers-reduced-motion and while the page is hidden.
  let sumT = null, chipAt = 0, chipSum = 0, chipT = null;
  const chip = () => {
    chipT = null;
    const total = led.querySelector(".led-n b");
    if (total && Math.abs(chipSum) >= 0.005) motion.floatChip(total.parentNode, fmt.money(chipSum, true), chipSum > 0 ? "up" : "down");
    chipSum = 0; chipAt = Date.now();
  };
  ctx.on("trades", (rows) => {
    clearTimeout(sumT); sumT = setTimeout(() => ctx.alive() && ctx.store.need("summary", 20000).catch(() => {}), 2000);
    for (const t of Array.isArray(rows) ? rows : []) if (Number.isFinite(Number(t.pnl))) chipSum += Number(t.pnl);
    if (!chipT) chipT = setTimeout(() => ctx.alive() && chip(), Math.max(0, 3000 - (Date.now() - chipAt)));
  });
  ctx.track(() => clearTimeout(chipT));
  ctx.track(() => clearTimeout(sumT));
  ctx.on("heartbeat", relive);
  ctx.on("stream:state", relive);
  ctx.every(60000, () => { renderHero(); renderNext(); }, {now: false});

  // /api/v4/curves (paper3.db equity, hourly steps): the total of every wallet over the run for the LED bar's line (the
  // head card's lines come from the race). Real points only; a 404 (an older server) stops asking and the pill stays.
  let curvesOn = true;
  async function loadCurves() {
    if (!curvesOn) return;
    let c;
    try { c = await ctx.api("/api/v4/curves?step=3600000"); } catch (e) { if (e && e.status === 404) curvesOn = false; return; }
    if (!ctx.alive() || !c || !Array.isArray(c.t) || c.t.length < 2) return;
    const real = (xs) => xs.filter((v) => v != null && Number.isFinite(v)).length;
    if (real(c.total || []) >= 2) { st.total = c.total; if (st.led) { st.led.curve = c.total; led.update(st.led); } }
  }
  ctx.every(300000, loadCurves);
}

export function unmount() {}
