// The 에이전트 콘솔 of the 회의실 (builder D): real records only, today (KST) and newest at the bottom.
//   - room messages of today (GET /api/rooms/<id>/messages, then after_id when the stream says a room changed):
//     [회의 시작] (tap: only that meeting), staff turns (cyan, 2 lines + 더 보기, 방 열기), disagreements (amber:
//     responds_to stance "disagree" and the lead's open disagreement), code results, decisions, actions, owner posts
//   - closed trades of today: [거래] lines for the 36, the reel and the extras; DeepSeek and the coin flips are counted,
//     not listed (owners' D10); a liquidation is always listed
//   - the 24-hour debate room's rounds under 토론, only while it really runs (features.debateRunning)
// NEEDS SERVER #3 (CONTRACT.md): one /api/v4/console feed would replace the per-room reads below.
import {fmt, serverNow} from "../core/pb.js";
import {SPEAKING, stanceOf, answerOf, bodyLines, readableText, stripLead, roleName, roomIdKo} from "./rooms-kit.js";

const LINE_KINDS = new Set(["strategy", "reel", "copy", "newlab"]);
const FIRST_ROOMS = 14;          // rooms read at the start (the most recent today); later ones are read as they change

export function makeFeed(ctx, onChange) {
  const st = {rooms: new Map(), titles: {}, trades: new Map(), debate: null, owner: null, day: 0, busy: new Set(), again: new Set(),
    seeded: false, tradesLoaded: false};
  const today0 = () => fmt.kstMidnight(serverNow());
  let changeT = null;
  const changed = () => { cancelAnimationFrame(changeT); changeT = requestAnimationFrame(() => ctx.alive() && onChange()); };

  function roll() {          // a new KST day: yesterday's lines leave
    const d0 = today0();
    if (d0 === st.day) return;
    st.day = d0;
    for (const r of st.rooms.values()) for (const [id, m] of r.msgs) if (m.ts < d0) r.msgs.delete(id);
    for (const [id, t] of st.trades) if (t.exit_time < d0) st.trades.delete(id);
  }

  async function fetchRoom(id) {
    if (st.busy.has(id)) { st.again.add(id); return; }
    st.busy.add(id);
    try {
      const r = st.rooms.get(id) || {msgs: new Map(), lastId: 0};
      const q = r.lastId ? `after_id=${r.lastId}&limit=200` : "limit=80";
      const d = await ctx.api(`/api/rooms/${encodeURIComponent(id)}/messages?${q}`);
      roll();
      for (const m of d.messages || []) {
        r.lastId = Math.max(r.lastId, m.id);
        if (m.ts >= st.day) r.msgs.set(m.id, m);
      }
      if (d.room && d.room.title) st.titles[id] = d.room.title;
      st.rooms.set(id, r);
      changed();
    } catch { /* the next change or poll retries */ } finally {
      st.busy.delete(id);
      if (st.again.delete(id) && ctx.alive()) fetchRoom(id);
    }
  }

  /** From /api/rooms: read the rooms that spoke today (first time) and every room whose newest id grew. */
  function syncRooms(ov) {
    if (!ov || !Array.isArray(ov.rooms)) return;
    roll();
    for (const r of ov.rooms) st.titles[r.room_id] = r.title;
    const today = ov.rooms.filter((r) => r.last_ts && r.last_ts >= st.day).sort((a, b) => b.last_ts - a.last_ts);
    const pick = st.seeded ? today.filter((r) => (r.last_id || 0) > ((st.rooms.get(r.room_id) || {}).lastId || 0)) : today.slice(0, FIRST_ROOMS);
    st.seeded = true;
    pick.forEach((r) => fetchRoom(r.room_id));
    if (!pick.length) changed();
  }
  /** The stream: {room_id: newest message id}. */
  function onRooms(map) {
    for (const [id, top] of Object.entries(map || {})) if (top > ((st.rooms.get(id) || {}).lastId || 0)) fetchRoom(id);
  }

  async function loadTrades() {
    try {
      const rows = await ctx.api("/api/trades?limit=200");
      roll();
      for (const t of rows || []) if (t.exit_time >= st.day) st.trades.set(t.id, t);
    } catch { /* trades stay as they come from the stream */ }
    st.tradesLoaded = true;
    changed();
  }
  function onTrades(rows) {
    roll();
    let n = 0;
    for (const t of rows || []) if (t.exit_time >= st.day && !st.trades.has(t.id)) { st.trades.set(t.id, t); n++; }
    if (n) changed();
  }
  function onDebate(d) { st.debate = d || null; changed(); }

  /** Console lines (core consolePanel shape) and the counts the foot shows. roles: office roles; board: /api/board. */
  function lines(roles, board, debateRunning) {
    const out = [];
    let owner = null;
    for (const [rid, r] of st.rooms) {
      const title = st.titles[rid] || roomIdKo(rid);
      const open = () => ctx.go("rooms", rid);
      for (const m of [...r.msgs.values()].sort((a, b) => a.id - b.id)) {
        const key = m.round_id != null ? `${rid}#${m.round_id}` : null;
        const who = m.speaker_name || roleName(roles, m.role);
        if (m.kind === "trigger") {
          out.push({id: `m${m.id}`, type: "ev", start: key != null, meeting: key, ts: m.ts, tabs: ["agent"], text: `[회의 시작] ${title} · ${stripLead(m.text)}`});
        } else if (SPEAKING.has(m.kind)) {
          out.push({id: `m${m.id}`, type: "st", meeting: key, ts: m.ts, tabs: ["agent"], who, text: readableText(bodyLines(m)), onOpen: open});
          const s = stanceOf(m);
          if (s && s.stance === "disagree") out.push({id: `d${m.id}`, type: "dis", label: "반대", meeting: key, ts: m.ts, tabs: ["agent"],
            text: `${who} → ${roleName(roles, s.to)}: ${s.point}`});
          const od = answerOf(m).open_disagreement;
          if (m.kind === "summary" && od) out.push({id: `o${m.id}`, type: "dis", label: "갈린 의견", meeting: key, ts: m.ts, tabs: ["agent"], text: String(od)});
        } else if (m.kind === "code_result") {
          out.push({id: `m${m.id}`, type: "ev", meeting: key, ts: m.ts, tabs: ["agent"], text: `[코드 계산] ${title} · ${String(m.text || "").split("\n")[0]}`});
        } else if (m.kind === "decision") {
          out.push({id: `m${m.id}`, type: "ev", meeting: key, ts: m.ts, tabs: ["agent"], text: `[결정] ${title} · ${stripLead(m.text)}`});
        } else if (m.kind === "action") {
          out.push({id: `m${m.id}`, type: "ev", meeting: key, ts: m.ts, tabs: ["agent"], text: `[실행] ${title} · ${stripLead(m.text)}`});
        } else if (m.kind === "owner") {
          out.push({id: `m${m.id}`, type: "st", meeting: key, ts: m.ts, tabs: ["agent"], who: `두 분 → ${title}`, text: String(m.text || ""), onOpen: open});
          if (!owner || m.ts > owner.ts) owner = {id: m.id, ts: m.ts, text: String(m.text || ""), room: title};
        }
      }
    }
    st.owner = owner;
    const idx = new Map(((board && board.accounts) || []).map((a) => [a.account_id, a]));
    const quiet = {ds: 0, coin: 0};
    const trades = [];
    for (const t of [...st.trades.values()].sort((a, b) => a.exit_time - b.exit_time)) {
      const a = idx.get(t.account_id);
      const kind = t.kind || (a && a.kind);
      const liq = t.exit_reason === "LIQ";
      if (!liq && !LINE_KINDS.has(kind)) { if (kind === "ds200") quiet.ds++; else quiet.coin++; continue; }
      trades.push({id: `tr${t.id}`, type: liq || t.pnl < 0 ? "bad" : "ev", ts: t.exit_time, tabs: ["trade"],
        text: `[${liq ? "강제청산" : "거래"}] ${a ? fmt.acctName(a) : fmt.idName(t.account_id)} · ${fmt.coin(t.symbol)} ${fmt.reasonKo(t.exit_reason)} ${fmt.pct(t.roe)}`});
    }
    out.push(...trades.slice(-25));         // the meetings of today stay in view on a busy trading day
    if (debateRunning && st.debate && Array.isArray(st.debate.rounds)) {
      for (const rd of st.debate.rounds) {
        if (!rd.ts || rd.ts < st.day || !(rd.messages || []).length) continue;
        const key = `deb#${rd.round_id}`;
        out.push({id: `db${rd.round_id}`, type: "ev", start: true, meeting: key, ts: rd.ts, tabs: ["debate"], text: `[토론] ${rd.topic || "24시간 토론방"}`});
        rd.messages.forEach((x, i) => out.push({id: `db${rd.round_id}-${i}`, type: "st", meeting: key, ts: rd.ts + i + 1, tabs: ["debate"],
          who: `${x.speaker}${x.stance ? ` (${x.stance})` : ""}`, text: String(x.text || ""), onOpen: () => ctx.go("debate")}));
      }
    }
    return {lines: out.sort((a, b) => (a.ts || 0) - (b.ts || 0)), quiet, loaded: st.seeded && st.tradesLoaded};
  }

  return {syncRooms, onRooms, loadTrades, onTrades, onDebate, lines, owner: () => st.owner};
}
