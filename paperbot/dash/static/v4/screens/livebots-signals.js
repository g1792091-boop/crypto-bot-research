// 실거래 › 신호 (#/livebots/signals): "왜 안 들어갔지?". Every signal of the combined bot (the paper bot both executors
// follow) of the last 7 Korea-time days and what became of it (/api/v4/livebots/signals: its signal_log rows and the
// account's outcomes): 걸러짐 with the bot's own Korean why (연구 조건 밖 · 끈 구간 · 주말 · 경제 발표 앞뒤 · 돌파 없음 …),
// 돌파 기다림 / 돌파 확인, and for a submitted signal its outcome (진입 · 포지션 있음 · 같은 때 다른 신호에 밀림 · 늦음 · 손절
// 자리가 안 맞음 …). A funnel for today and the 7 days, the reasons counted, the newest 200 in a list of 10 a page.
// HONESTY: counts of real rows only; a signal whose outcome is not written yet says so; the executors follow only the
// paper's entries (their own skips are on 안전 and 거래).
// ⏳ 진입 대기 (owners 10/19 "진입 하기 전에 진입할 가능성이 있는 것"), on top: the break signals still waiting for the price
// to trade beyond the signal bar's high (long) / low (short) within one bar of their timeframe (/api/v4/livebots/now
// `pending`, paperbot/livecheck.py pending_entries): the level, the last 1m price, how far to go, a countdown to the
// deadline; the next bar closes per timeframe when nothing waits; the reason a wait cannot become an entry now (weekend,
// macro, a position open, the paper bot down). HONESTY: a wait is not an entry; a level the rule bot's bars cannot give
// is 기준가 못 읽음 (never a made-up price); the countdown is the real deadline (it says 시간 지남 · 진입 없음 at 0).
import {h, put, ui, fmt, local, motion} from "../core/pb.js";
import {sourceState} from "./livebots-kit.js";

const REFRESH_MS = 30 * 1000;
const STAGE = [["signals", "신호"], ["filtered", "걸러짐"], ["waiting", "돌파 기다림"], ["skipped", "밀림·건너뜀"], ["rejected", "거절"], ["entered", "진입"]];
const TONE = {entered: "good", filtered: "thin", waiting: "accent", broke: "accent", skipped: "warn", rejected: "bad", submitted: "thin", other: "thin"};
const LIST = [{id: "all", label: "전부"}, {id: "out", label: "안 들어감"}, {id: "entered", label: "진입"}];

/** Rows for a list filter: "all", "entered", or "out" (every signal that did not become an entry). */
export const rowsFor = (rows, f) => (rows || []).filter((r) => f === "all" || (f === "entered" ? r.stage === "entered" : r.stage !== "entered" && r.status !== "BROKE"));

// ---------------------------------------------------------------- ⏳ 진입 대기
export const NOW_API = "/api/v4/livebots/now";
const WAIT_REFRESH_MS = 15 * 1000;
const NEAR_SCALE = 0.03;                // the closeness bar: 3 % or more still to go = empty, at the level = full

/** How close the price is to its level, 0..1 (1 = at or beyond it), or null without a level or a price. */
export function closeness(toGo) {
  const v = Number(toGo);
  if (toGo == null || !Number.isFinite(v)) return null;
  return Math.max(0, Math.min(1, 1 - v / NEAR_SCALE));
}

/** The time left in words: "4분 05초 남음" / "1시간 02분 남음"; 0 or less: "시간 지남 · 진입 없음"; unknown: "—". */
export function countdownKo(ms) {
  if (ms == null || !Number.isFinite(Number(ms))) return "—";
  const sec = Math.floor(Number(ms) / 1000);
  if (sec <= 0) return "시간 지남 · 진입 없음";
  const hh = Math.floor(sec / 3600), mm = Math.floor((sec % 3600) / 60), ss = sec % 60, two = (n) => String(n).padStart(2, "0");
  return hh ? `${hh}시간 ${two(mm)}분 남음` : `${mm}분 ${two(ss)}초 남음`;
}

/** One wait in words: coin, side, setting, the level line, the price now, how far to go, closeness, touched. */
export function waitWords(w, rulePath) {
  const long = Number(w.side) > 0;
  const lv = w.level == null ? null : fmt.price(w.level);
  const tg = w.to_go == null || !Number.isFinite(Number(w.to_go)) ? null : Number(w.to_go);
  return {coin: fmt.coin(w.symbol), long, name: fmt.stratKo(w.strategy), tf: fmt.tfKo(w.tf),
    line: lv ? `${lv} ${long ? "위로 올라가면" : "아래로 내려가면"} 진입` : `기준가 못 읽음 (규칙봇 1분봉: ${rulePath || "—"})`,
    now: w.last == null ? "—" : fmt.price(w.last),
    left: w.touched === true && lv ? "한 번 넘었어요" : tg == null ? (lv ? "지금 가격 못 읽음" : "—") : tg > 0 ? `${fmt.pct(tg, 2, false)} 남음` : "기준가를 넘었어요",
    near: w.touched === true && lv ? 1 : closeness(tg), touched: w.touched === true, noLevel: w.level == null};
}

/** A timeframe's next bar close: "15분봉 마감 19:15 KST · 바로 진입 0개 · 돌파 대기 1개 설정". */
export const closeWords = (c) => `${fmt.tfKo(c.tf)}봉 마감 ${fmt.hm(c.next_ms)} KST · 바로 진입 ${fmt.int(c.now || 0)}개 · 돌파 대기 ${fmt.int(c.break || 0)}개 설정`;

/** The part of /now this section shows, without what changes every second (left_ms, now_ms): the same waits draw nothing. */
export function waitKey(d) {
  if (!d) return "";
  const p = d.pending || null;
  return JSON.stringify({p: p ? {...p, waits: (p.waits || []).map(({left_ms: _l, ...w}) => w)} : null, b: d.pending_blocked_ko || null});
}

/** The fraction of a wait's bar still left (1 = just signalled, 0 = deadline), from the ms left. */
export const timeLeftFrac = (w, leftMs) => {
  const span = Number(w.until) - Number(w.t0);
  return span > 0 && leftMs != null && Number.isFinite(Number(leftMs)) ? Math.max(0, Math.min(1, Number(leftMs) / span)) : null;
};

/** waitView(ctx) -> {el}: the ⏳ 진입 대기 card (its own 15 s poll of /now; a 1 s countdown that changes only text). */
export function waitView(ctx) {
  const st = {d: null, key: "", okAt: 0, clocks: []};
  const slot = h("div", {class: "lb-slot"});
  const body = h("div", {class: "lbw-body"}, motion.shimmer(2));
  const el = ui.card({title: "⏳ 진입 대기", sub: "신호는 나왔고 돌파를 기다리는 진입 · 한국 시간", cls: "lbw-card"}, slot, body,
    ui.note("진입 대기 = 신호는 나왔고 돌파를 기다리는 중. 진입 확정이 아니에요. 시간 안에 못 넘으면 진입 없음. "
      + "텔레그램에도 ⏳ 알림이 한 번 가요 (끄기: PAPERBOT_LIVE_WAIT_MSGS=0)."));

  function tick() {
    const now = Date.now();
    for (const c of st.clocks) {
      const left = c.deadline - now;
      c.text.textContent = countdownKo(left);
      const f = timeLeftFrac(c.w, left);
      if (f != null) c.bar.style.width = (f * 100).toFixed(1) + "%";
      c.card.classList.toggle("lbw-lapsed", left <= 0);
    }
  }
  function waitCard(w, p, fetched) {
    const x = waitWords(w, p.rule_path);
    const deadline = fetched + Number(w.left_ms);
    const text = h("b", {class: "lbw-cd num"}, countdownKo(deadline - Date.now()));
    const bar = h("i");
    const card = h("div", {class: ["lbw-wait", x.long ? "long" : "short", x.touched ? "touched" : "", x.noLevel ? "nolevel" : "",
      x.near != null && x.near >= 0.8 ? "near" : ""], role: "listitem"},
    h("div", {class: "lbw-top"}, h("b", {class: "lbw-coin"}, x.coin), ui.sideTag(w.side),
      h("span", {class: "lbw-strat", title: w.member || ""}, `${x.name} · ${x.tf}`),
      x.touched ? h("span", {class: "lbw-touch", title: "신호 뒤 1분봉이 이미 기준가를 넘었어요: 봇이 진입하는 중이어야 해요"}, h("i", {"aria-hidden": "true"}), "돌파함 · 진입 확인 중") : null),
    h("p", {class: ["lbw-line", x.noLevel ? "muted" : ""]}, x.line),
    x.noLevel ? null : h("div", {class: "lbw-near", title: "기준가까지 남은 거리 (3% 이상이면 막대가 비어요)"},
      h("span", {class: "lbw-now"}, "지금 ", h("b", {class: "num"}, x.now)),
      h("span", {class: "lbw-bar", role: "img", "aria-label": x.left}, x.near != null ? h("i", {style: {width: (x.near * 100).toFixed(1) + "%"}}) : null),
      h("b", {class: "lbw-left num"}, x.left)),
    h("div", {class: "lbw-clock"}, text, h("span", {class: "lbw-tbar", "aria-hidden": "true"}, bar),
      h("span", {class: "lbw-t0"}, `신호 ${fmt.kst(w.t0)} · ${fmt.hm(w.until)}까지`)));
    st.clocks.push({w, deadline, text, bar, card});
    return card;
  }
  function draw() {
    const d = st.d;
    st.clocks = [];
    if (!d) { put(body, motion.shimmer(2)); return; }
    const p = d.pending || {state: "missing", reason_ko: "서버가 진입 대기를 보내지 않았어요"};
    const block = d.pending_blocked_ko ? h("p", {class: "lbw-block", role: "status"}, h("b", null, "지금은 넘어도 진입 안 해요: "), d.pending_blocked_ko) : null;
    if (p.state !== "ok") { put(body, block, sourceState(p, "페이퍼 DB (진입 대기)")); return; }
    const waits = p.waits || [], closes = p.closes || [];
    const closeList = (cls) => (closes.length ? h("ul", {class: ["lbw-closes", cls]}, closes.map((c) => h("li", {dataset: {tf: c.tf}}, closeWords(c)))) : null);
    if (!waits.length) {
      put(body, block, h("div", {class: "lbw-empty"}, h("b", null, "지금 기다리는 진입 없음"),
        closes.length ? h("span", {class: "muted"}, "다음 봉 마감 때 봇이 다시 신호를 봐요") : null), closeList("big"));
      return;
    }
    const fetched = st.okAt;
    put(body, block, h("div", {class: "lbw-list", role: "list"}, waits.map((w) => waitCard(w, p, fetched))),
      p.rule_state && p.rule_state !== "ok" ? h("p", {class: "note"}, `규칙봇 1분봉 파일을 ${p.rule_state === "missing" ? "아직 못 찾아" : "못 읽어"} 기준가를 못 보여 드려요 (봇이 보는 기준가는 그 파일의 신호봉 고가·저가)`) : null,
      closeList("small"));
    tick();
  }
  async function load() {
    let d;
    try { d = await ctx.api(NOW_API); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      put(slot, st.d ? ui.staleNote(e, st.okAt, () => load()) : ui.errorBox(e, () => load()));
      ui.dim(body, !!st.d);
      if (!st.d) put(body);
      throw e;
    }
    if (!ctx.alive()) return;
    put(slot);
    ui.dim(body, false);
    const key = waitKey(d);
    if (key === st.key) {                             // the same waits: keep the cards, move each deadline to the new answer
      const at = Date.now(), by = new Map(((d.pending || {}).waits || []).map((w) => [w.key, w]));
      for (const c of st.clocks) { const w = by.get(c.w.key); if (w) c.deadline = at + Number(w.left_ms); }
      st.okAt = at;
      return;
    }
    st.key = key; st.d = d; st.okAt = Date.now();
    draw();
  }
  load().catch(() => {});
  ctx.every(WAIT_REFRESH_MS, () => load().catch(() => {}), {now: false});
  ctx.every(1000, tick, {now: false});
  return {el};
}

/** signalsView(ctx) -> {el, set()} */
export function signalsView(ctx) {
  const st = {span: local.get("lb-sspan", "today"), list: "out", d: null, okAt: 0};
  if (!["today", "week"].includes(st.span)) st.span = "today";
  const spanSeg = ui.seg([{id: "today", label: "오늘"}, {id: "week", label: "최근 7일"}], st.span, (id) => { st.span = id; local.set("lb-sspan", id); draw(); }, {label: "기간"});
  const funnel = h("div", {class: "lb-funnel"});
  const reasons = h("div", {class: "lb-reasons"});
  const stateSlot = h("div", {class: "lb-slot"});
  const listSeg = ui.seg(LIST, st.list, (id) => { st.list = id; drawList(true); }, {label: "목록 고르기"});
  const pg = ui.pager({size: 10, row: (r) => rowOf(r), empty: () => (st.d ? ui.empty("맞는 신호가 없어요") : motion.shimmer(3))});
  const wait = waitView(ctx);
  const el = h("div", {class: "lb-signals stack"}, wait.el,
    ui.card({title: "신호가 어디까지 갔나", sub: "합친 봇(페이퍼)의 신호 · 한국 시간", cls: "lb-fcard", acts: [spanSeg]}, stateSlot, funnel,
      h("p", {class: "lb-rhead"}, "이유별"), reasons,
      ui.note("실거래 실행기는 페이퍼가 진입한 것만 따라가요 (신호등이 빨강이거나 멈춤이면 그것도 건너뜀: 거래 · 안전 탭)")),
    ui.card({title: "왜 안 들어갔지?", sub: "최근 신호 200개까지 · 10개씩", cls: "lb-scard", acts: [listSeg]}, pg.el));

  function rowOf(r) {
    return h("div", {class: ["lb-srow", r.stage], role: "listitem"},
      h("span", {class: "num muted lb-st"}, fmt.kst(r.t)), h("b", {class: "lb-tc"}, fmt.coin(r.symbol)), ui.sideTag(r.side),
      h("span", {class: "lb-ss", title: r.member}, `${fmt.stratKo(r.strategy)} · ${fmt.tfKo(r.tf)}`),
      ui.pill(r.ko, TONE[r.stage] || "thin"),
      r.why && r.why !== r.ko ? h("span", {class: "lb-sw2 muted", title: r.why}, ui.moreText(r.why_ko || r.why, 2)) : null);
  }
  function drawList(user) { pg.set(st.d && st.d.state === "ok" ? rowsFor(st.d.rows, st.list) : st.d ? [] : undefined, !user); }
  function draw() {
    spanSeg.set(st.span);
    const d = st.d;
    if (!d) { put(funnel, motion.shimmer(2)); put(reasons); drawList(false); return; }
    if (d.state !== "ok") { put(stateSlot, sourceState(d, "페이퍼 DB (신호 기록)")); put(funnel); put(reasons); drawList(false); return; }
    put(stateSlot);
    const sg = d.stages[st.span] || {};
    const top = Math.max(1, sg.signals || 0);
    put(funnel, STAGE.map(([k, ko]) => h("div", {class: ["lb-fstep", k]}, h("span", {class: "lb-fk"}, ko),
      h("span", {class: "lb-fbar"}, h("i", {style: {width: `${((sg[k] || 0) / top * 100).toFixed(1)}%`}})), h("b", {class: "num"}, fmt.int(sg[k] || 0)))));
    const cs = (d.counts[st.span] || []);
    const mx = Math.max(1, ...cs.map((c) => c.n));
    put(reasons, cs.length ? cs.map((c) => h("div", {class: ["lb-rsn", c.stage]}, h("span", {class: "lb-rk"}, c.ko),
      h("span", {class: "lb-rbar"}, h("i", {style: {width: `${(c.n / mx * 100).toFixed(1)}%`}})), h("b", {class: "num"}, fmt.int(c.n))))
      : ui.empty(st.span === "today" ? "오늘은 아직 신호가 없어요" : "최근 7일 신호가 없어요"));
    drawList(false);
  }
  async function load() {
    try { st.d = await ctx.api("/api/v4/livebots/signals"); st.okAt = Date.now(); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      put(stateSlot, st.d ? ui.staleNote(e, st.okAt, () => load()) : ui.errorBox(e, () => load()));
      throw e;
    }
    if (ctx.alive()) draw();
  }
  draw();
  load().catch(() => {});
  ctx.every(REFRESH_MS, () => load().catch(() => {}), {now: false});
  return {el, set() {}};
}
