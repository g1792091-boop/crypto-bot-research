// 홈 · 요약 (builder A, CONTRACT.md section 4), trimmed to the owners' approved order: the 30-day headline
// (strategy-account median vs coin-flip median, above / below the same-timeframe coin median, the checkpoint progress
// in one line), the green LED balance bar, the group cards, top 5 / bottom 5, today per group (the server's own count),
// a three-line "최근 회의" strip that opens 회의실, the searchable full list, and the way into '어떻게 돌아가나'.
// HONESTY: every comparison is '참고' with refNote; every money card has assume(); LIVE / 회의 중 only from real state
// (stream.live(), /api/office running); numbers count to new values only when the server's data changed.
import {h, put, ui, fmt, derive, motion, stream, startTour, local} from "../core/pb.js";
import {groupCards, topBottom, rankList, groupKo, savedGroup, expInfo, judgedProgress, ORDER, MIN_TRADES} from "./home-shared.js";
import {todayStats, TODAY_KO, TODAY_ORDER} from "./home-today.js";

const DECISION_KO = {done: "결정", no_action: "행동 없음", failed: "멈춤", stopped_budget: "한도로 멈춤"};

export async function mount(el, ctx) {
  ctx.setTitle("홈");
  const st = {board: null, gs: null, summary: null, office: null, officeTried: false, ck: null, sel: savedGroup("home-group"), led: null};
  const href = (n, a, q) => ctx.href(n, a, q);

  // ---------------------------------------------------------------- 1. headline card
  const dcount = h("span", {class: "home-dcount"}, h("b", null, "D+—"), " / 30");
  const prog = h("div", {class: "prog", role: "progressbar", "aria-label": "30일 중 지난 날", "aria-valuemin": "0", "aria-valuemax": "30"}, h("i"));
  const hsub = h("p", {class: "home-hsub"});
  // the two median curves from /api/v4/curves (loadCurves); until it answers with two real points: one small pill, not
  // a box (the numbers below are the current values)
  const curve = h("div", {class: "home-curve1"}, ui.notYet("곡선 수집 전", "시간에 따른 두 중앙값 곡선은 서버가 그 기록을 보내면 그립니다. 아래 숫자는 지금 값입니다."));
  const leg = (cls) => ({name: h("span"), val: ui.liveNum(null, {dec: 2}), ret: ui.liveNum(null, {format: "pct", tone: true, tag: "span"}), cls});
  const legS = leg(""), legC = leg("c");
  const legend = h("div", {class: "legend"}, [legS, legC].map((x) => h("div", null, h("i", {class: ["sw", x.cls]}), x.name, x.val, x.ret)));
  const wlA = ui.liveNum(null, {format: "int", cls: "up"}), wlB = ui.liveNum(null, {format: "int", cls: "down"});
  const wlBar = h("i");
  const wl = h("div", {class: "home-wl"},
    h("div", {class: "home-hrow"}, h("span", {class: "muted"}, "같은 봉 동전 봇 중앙값보다"), h("span", null, "위 ", wlA, " · 아래 ", wlB)),
    h("div", {class: "wl-bar", role: "img", "aria-label": "동전 봇 중앙값보다 위와 아래의 비율"}, wlBar));
  const ckLine = h("div", {class: "home-ckline"});           // the checkpoint in one line (progress, never a verdict)
  const refBox = h("div");
  const hero = ui.card({hero: true, cls: "home-hero home-o1", label: "30일 실험 요약"},
    h("div", {class: "home-hrow"}, ui.plate("30일 실험"), dcount), prog,
    h("h2", null, "동전 봇보다 나은 ", h("em", null, "매매법"), "이 있나?"), hsub, curve, legend, wl, ckLine, refBox, ui.assume());
  hero.dataset.tour = "headline";                       // the first-visit tour points here (core/tour.js)

  // ---------------------------------------------------------------- 2. LED balance bar
  const led = ui.ledBar({label: "모의 계좌 잔고"});
  led.classList.add("home-o2");

  // ---------------------------------------------------------------- 3. group cards
  const groups = groupCards({onPick: (id) => { st.sel = id; local.set("home-group", id); renderGroupParts(true); }});
  const toBoard = h("a", {class: "btn-line", href: href("board", null, {g: st.sel})}, "순위표 전체 보기");
  const groupSec = h("section", {class: "home-sec home-o3", "aria-label": "묶음", dataset: {tour: "groups"}},
    h("div", {class: "home-sec-row"}, ui.plate("묶음"), h("span", {class: "muted home-hint"}, "누르면 아래 목록이 그 묶음으로 바뀝니다"), h("span", {class: "grow"}), toBoard),
    groups);

  // ---------------------------------------------------------------- 4. top 5 / bottom 5 + the full list
  const tb = topBottom(ctx);
  const ranksCard = ui.card({plate: "상위·하위", cls: "home-o4"}, tb);
  const list = rankList(ctx, {memo: "home-list"});
  const listCard = ui.card({plate: "전체 목록", cls: "home-o7", acts: [list.countEl]}, list.el,
    h("p", {class: "assume"}, "수익률은 시작 잔고 대비 (닫힌 거래 기준) · 10개씩 나눠 보여 줍니다 · 누르면 계좌 화면"));

  // ---------------------------------------------------------------- 5. today (the server's per-group count)
  const todayBody = h("div", {class: "stack tight"}, motion.shimmer(3));
  const nextEl = h("div", {class: "home-next"});
  const todaySub = h("span", {class: "sub"});
  const todayCard = ui.card({plate: "오늘", cls: "home-today home-o5", acts: [todaySub]}, todayBody, nextEl, ui.assume());

  // ---------------------------------------------------------------- 6. 최근 회의 (three stored lines -> 회의실)
  const meetBody = h("div", {class: "home-meets", role: "list"}, motion.shimmer(2));
  const meetCard = ui.card({plate: "최근 회의", cls: "home-o6", acts: [h("a", {class: "btn-line", href: href("office")}, "회의실 →")]}, meetBody);

  // ---------------------------------------------------------------- 7. 어떻게 돌아가나
  const flow = ["신호", "진입", "레버리지", "청산", "손실 회의", "판정"];
  const howCard = ui.card({plate: "처음이라면", cls: "home-o8 home-how"},
    h("ol", {class: "home-flow", "aria-label": "봇의 하루 여섯 단계"}, flow.map((t, i) => h("li", null, h("span", {class: "n"}, String(i + 1).padStart(2, "0")), t))),
    h("div", {class: "row wrap"}, h("a", {class: "btn-y", href: href("howto")}, "어떻게 돌아가나"),
      h("a", {class: "btn-line", href: href("faq")}, "자주 묻는 질문"),
      h("button", {class: "btn-line", type: "button", onclick: () => startTour()}, "안내 다시 보기")),
    h("p", {class: "muted home-small"}, "AI 직원은 회의와 기록만 하고 거래하지 않습니다. 모든 계좌는 모의(가상 돈)입니다."));

  el.append(ui.screenHead("요약", "30일 모의 실험을 한눈에"),
    h("div", {class: "home-wrap home-top"}, h("div", {class: "home-col"}, hero), h("div", {class: "home-col"}, todayCard)),
    led, groupSec,
    h("div", {class: "home-wrap"}, h("div", {class: "home-col"}, ranksCard, listCard), h("div", {class: "home-col"}, meetCard, howCard)));

  // ================================================================ renderers
  function renderHero() {
    const s = st.summary, gs = st.gs;
    const x = expInfo(s);
    if (x) {
      put(dcount, h("b", null, `D+${x.day}`), ` / ${x.of}`);
      prog.firstChild.style.setProperty("--p", Math.max(0, Math.min(100, x.day / x.of * 100)) + "%");
      prog.setAttribute("aria-valuemax", String(x.of)); prog.setAttribute("aria-valuenow", String(x.day));
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
    legS.name.textContent = `매매법 ${fmt.int(gs.strat.n)}개 중앙값`;
    legC.name.textContent = `동전 봇 ${fmt.int(gs.coin.n)}개 중앙값`;
    legS.val.update(gs.strat.medWallet); legS.ret.update(gs.strat.medRet);
    legC.val.update(gs.coin.medWallet); legC.ret.update(gs.coin.medRet);
    wlA.update(gs.strat.above); wlB.update(gs.strat.below);
    const tot = gs.strat.above + gs.strat.below;
    wlBar.style.setProperty("--w", (tot ? gs.strat.above / tot * 100 : 0) + "%");
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
    toBoard.setAttribute("href", href("board", null, {g: st.sel}));
    tb.set(b, gs, st.sel);
    list.set(b, gs, st.sel, !animate);
    if (animate) motion.swap(tb);
  }

  // today: one line per group (P&L, trades, wins, liquidations, busts) from the server's own count
  const trows = new Map();
  function tRow(id) {
    let r = trows.get(id);
    if (r) return r;
    const v = ui.liveNum(null, {dec: 2, sign: true, tone: true, cls: "tv"});
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
        h("p", {class: "muted home-small"}, "서버 집계 기준 · 5분봉 단타는 릴스 1개, 동전 봇은 5분봉 3개 포함"));
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
  let sumT = null;
  ctx.on("trades", () => { clearTimeout(sumT); sumT = setTimeout(() => ctx.alive() && ctx.store.need("summary", 20000).catch(() => {}), 2000); });
  ctx.track(() => clearTimeout(sumT));
  ctx.on("heartbeat", relive);
  ctx.on("stream:state", relive);
  ctx.every(60000, () => { renderHero(); renderNext(); }, {now: false});

  // /api/v4/curves (paper3.db equity, hourly steps): the 36's and the coin flips' median balance over the run, and the
  // total for the LED bar. Real points only; a 404 (an older server) stops asking and the pills stay.
  let curvesOn = true;
  async function loadCurves() {
    if (!curvesOn) return;
    let c;
    try { c = await ctx.api("/api/v4/curves?step=3600000"); } catch (e) { if (e && e.status === 404) curvesOn = false; return; }
    if (!ctx.alive() || !c || !Array.isArray(c.t) || c.t.length < 2) return;
    const md = c.median || {};
    const ms = md.strategy || [], mc = md.random || [];
    const real = (xs) => xs.filter((v) => v != null && Number.isFinite(v)).length;
    if (real(ms) >= 2 || real(mc) >= 2) {
      put(curve, ui.curves({series: [{values: ms, cls: "ls", label: "기존 36 중앙값"}, {values: mc, cls: "lc", label: "동전 봇 중앙값"}],
        base: c.initial, height: 120, xlabels: [fmt.mmdd(c.t[0]), "", "지금"], label: "기존 36과 동전 봇의 잔고 중앙값 흐름"}),
      h("p", {class: "muted small"}, "곡선(1시간마다): 실선 = 기존 36 중앙값 · 점선 = 동전 봇 중앙값. 아래 숫자는 지금 값"));
    }
    if (real(c.total || []) >= 2) { st.total = c.total; if (st.led) { st.led.curve = c.total; led.update(st.led); } }
  }
  ctx.every(300000, loadCurves);
}

export function unmount() {}
