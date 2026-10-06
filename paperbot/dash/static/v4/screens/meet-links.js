// 손실 거래 <-> 회의 (review addition 9): a losing trade's row says which loss meeting looked at it ("이 손실을 다룬
// 회의 · 10:41 손실 묶음 복기 →", to that meeting's record in 회의 요약), and a loss meeting's conclusion lists the
// trades it was about ("근거 거래 3건", each to its replay). Data: GET /api/v4/losslinks (dash/more/losslinks.py: the
// trade ids the loss meetings stored, each checked against the trade's own exit time).
// Every slot is asked for in ONE request per moment (the ids queued while a page draws are sent together), and the
// answers are kept a minute. HONESTY: a trade with no meeting shows nothing (never "회의 없음": a meeting may still be
// coming); a round whose trades cannot be read says so; DeepSeek and coin-flip trades are listed without money.
import {h, fmt} from "../core/pb.js";

export const LOSS_TRIGGERS = ["loss_cluster", "group_loss"];
const TTL = 60000;
const cache = {trades: new Map(), rounds: new Map()};        // id -> {at, v}
const queue = {trades: new Map(), rounds: new Map()};        // id -> [fill functions]
let timer = null, ctxRef = null;

/** An account id's name; a copy ("S@15m~c1") reads "<name> · 15분 복제 c1". */
export function nameOf(id) {
  const m = /^(.*)~(c\d+)$/.exec(String(id || ""));
  return m ? `${fmt.idName(m[1])} 복제 ${m[2]}` : fmt.idName(id);
}

/** "#/digest/day?d=2026-10-06&r=12": the meeting's own record (회의 요약 › 하루, opened at that meeting). */
export const meetingHref = (ctx, m) => ctx.href("digest", "day", {d: fmt.dayKey(m.started_ts), r: m.round_id});

function flush() {
  timer = null;
  const ctx = ctxRef;
  const wt = [...queue.trades], wr = [...queue.rounds];
  queue.trades.clear(); queue.rounds.clear();
  if (!ctx) return;
  // the server takes at most 200 trade ids and 50 rounds per request: larger batches go in several
  for (let i = 0; i < Math.max(wt.length / 200, wr.length / 50); i++) send(ctx, wt.slice(i * 200, i * 200 + 200), wr.slice(i * 50, i * 50 + 50));
}

function send(ctx, wt, wr) {
  if (!wt.length && !wr.length) return;
  const q = [wt.length ? `trades=${wt.map(([id]) => id).join(",")}` : "", wr.length ? `rounds=${wr.map(([id]) => id).join(",")}` : ""].filter(Boolean).join("&");
  ctx.api(`/api/v4/losslinks?${q}`).then((d) => {
    const now = Date.now();
    for (const [id, fns] of wt) { const v = ((d && d.trades) || {})[id] || []; cache.trades.set(id, {at: now, v}); fns.forEach((f) => f(v, null)); }
    for (const [id, fns] of wr) { const v = ((d && d.rounds) || {})[id] || null; cache.rounds.set(id, {at: now, v}); fns.forEach((f) => f(v, null)); }
  }).catch((e) => {
    if (e && e.name === "AbortError") return;
    for (const [, fns] of wt) fns.forEach((f) => f(null, e));
    for (const [, fns] of wr) fns.forEach((f) => f(null, e));
  });
}

function ask(ctx, kind, id, fill) {
  const key = String(id);
  const hit = cache[kind].get(key);
  if (hit && Date.now() - hit.at < TTL) { fill(hit.v, null); return; }
  ctxRef = ctx;
  if (!queue[kind].has(key)) queue[kind].set(key, []);
  queue[kind].get(key).push(fill);
  if (!timer) timer = setTimeout(flush, 0);
}

/** The meeting chip of one losing trade (empty until an answer names a meeting). nested: inside another link (a home
 *  row), so the chip is a span that opens the meeting itself (never an <a> inside an <a>). */
export function tradeMeetSlot(ctx, t, o = {}) {
  const slot = h("span", {class: "ml-slot"});
  if (!t || t.id == null || !(Number(t.pnl) < 0 || o.always)) return slot;
  ask(ctx, "trades", t.id, (v) => {
    const m = (v || [])[0];                     // the newest meeting that looked at this trade
    if (m) slot.replaceChildren(chip(ctx, m, o));
  });
  return slot;
}

function chip(ctx, m, o) {
  const words = [h("span", {class: "ml-k"}, "이 손실을 다룬 회의"), ` · ${fmt.hm(m.started_ts)} ${m.trigger_ko || "손실 복기"}`, h("span", {class: "ml-go", "aria-hidden": "true"}, " →")];
  const title = `${m.room_title || m.room_id} · ${fmt.kst(m.started_ts)}${m.summary_ko ? ` · ${String(m.summary_ko).replace(/^\s*🧾\s*/u, "").split("\n")[0]}` : ""}`;
  if (o.nested) {
    const go = (e) => { e.preventDefault(); e.stopPropagation(); window.location.hash = meetingHref(ctx, m); };
    return h("span", {class: "ml-chip", role: "link", tabindex: "0", title, onclick: go, onkeydown: (e) => { if (e.key === "Enter") go(e); }}, words);
  }
  return h("a", {class: "ml-chip", href: meetingHref(ctx, m), title}, words);
}

/** "근거 거래 n건" of a loss meeting (round id): a folded list, each trade to its replay. */
export function roundTradesSlot(ctx, roundId) {
  const slot = h("div", {class: "ml-round"});
  if (roundId == null) return slot;
  ask(ctx, "rounds", roundId, (v, err) => {
    if (err) { slot.replaceChildren(h("p", {class: "ml-note"}, "근거 거래를 불러오지 못했습니다 (다음에 다시 봅니다)")); return; }
    if (!v || !v.stored) return;                                   // this meeting stored no trade ids: nothing to link
    const ts = v.trades || [];
    if (!ts.length) { slot.replaceChildren(h("p", {class: "ml-note"}, `근거 거래 ${fmt.int(v.stored)}건 · 지금 기록에서 찾지 못함 (다시 시작하기 전 거래)`)); return; }
    const open = h("button", {class: "ml-open", type: "button", "aria-expanded": "false"}, `근거 거래 ${fmt.int(ts.length)}건 →`);
    const list = h("div", {class: "ml-list", hidden: true, role: "list"}, ts.map((t) => h("a", {class: "ml-trow", role: "listitem", href: ctx.href("replay", String(t.id)),
      title: "이 거래를 봉 차트에서 다시 보기"},
      h("span", {class: "ml-tt"}, fmt.kst(t.exit_time)), h("span", null, nameOf(t.account_id)), h("span", null, `${fmt.coin(t.symbol)} ${t.side ? fmt.sideKo(t.side) : ""}`),
      h("span", {class: t.exit_reason === "LIQ" ? "down" : ""}, fmt.reasonKo(t.exit_reason)),
      t.count_only ? h("span", {class: "muted"}, "개수만") : h("b", {class: ["num", fmt.tone(t.pnl)]}, fmt.money(t.pnl, true)),
      h("span", {class: "ml-go"}, "▶ 다시보기"))));
    open.addEventListener("click", () => { const o = list.hidden; list.hidden = !o; open.setAttribute("aria-expanded", String(o)); });
    // (replaceChildren would print a null as the text "null")
    slot.replaceChildren(...[open, list, ts.some((t) => t.count_only) ? h("p", {class: "ml-note"}, "딥시크·동전 봇 거래는 개수만 (돈 숫자는 그 묶음 화면에서)") : null].filter(Boolean));
  });
  return slot;
}
