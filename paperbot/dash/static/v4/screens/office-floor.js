// 회의실 floor (builder D): the warm wooden pixel office from /api/office. One room per team zone (plate, 오늘 N회),
// 전문가실 for the strategy rooms (a few specialists at desks + "+N", the five group specialists once the server lists
// them), 대표실 with the window, real KST / UTC / NYC clocks and the two owners. Rooms with no meeting today sit small
// and dimmed in the bottom row. HONESTY: a room is LIVE only while /api/office lists its meeting in `running`; people
// stand at the table only as that meeting's participants; bubbles are the stored last line of a speaker (first
// sentence) and pop only when that line changed; staff walk to the table only when a meeting id is NEW since the last
// poll; "다음 차례" only when the meeting's own order names the next speaker. Every text is a text node.
// Wave 2 ⑧: the 대표실 window follows Korea time (core/figure.js skyPhase), a wall plate names the market session now and
// the US stock market's next open / close (core/bars.js), every room's floor carries its team's colour (TEAM_HUE), and
// only a room holding a real meeting (/api/office running) has its lamp on (after dark the others dim). The desk holds
// today's report (screens/meetboard-kit.js deskReport: finished meetings' conclusions -> 회의 결론).
import {h, ui, fmt, motion, figure, clock, windowArt, bars, hueOf, TEAM_HUE, skyPhase, PHASE_KO} from "../core/pb.js";
import {roleOf, shortName, hueFor, roleName, GROUP_ROLES, KIND_KO, triggerKo, whyOf} from "./rooms-kit.js";
import {deskReport} from "./meetboard-kit.js";

const SPEC_SHOWN = 5;

/** The zones of the floor: the team rooms of /api/office and one 전문가실 for the strategy rooms. */
export function zonesOf(o, roster) {
  const run = [...(o.running || [])].sort((a, b) => (b.started_ts || 0) - (a.started_ts || 0));
  const byRoom = (o.today && o.today.by_room) || {};
  const zones = (o.zones || []).map((z) => ({key: z.room_id, kind: "team", title: z.title, room: z.room_id, members: z.members || [], group: !!z.group_role,
    meeting: run.find((m) => m.room_id === z.room_id) || null, others: 0, count: byRoom[z.room_id] || 0,
    last: (o.recent || []).find((r) => r.room_id === z.room_id) || null}));
  const sruns = run.filter((m) => m.kind === "strategy" || String(m.room_id).startsWith("strat:"));
  const latest = o.latest_strategy || [];
  const specs = specialists(o, roster);
  zones.push({key: "spec", kind: "spec", title: "전문가실", room: sruns[0] ? sruns[0].room_id : null, members: specs,
    meeting: sruns[0] || null, others: Math.max(0, sruns.length - 1),
    count: Object.entries(byRoom).filter(([k]) => k.startsWith("strat:")).reduce((s, [, v]) => s + v, 0),
    last: latest.find((r) => r.status !== "running") || null, latest});
  return zones;
}

const GROUP_IDS = new Set(GROUP_ROLES.map((g) => `spec_${g[0]}`));
/** The strategy specialists (roster order; the office's own roles when the roster did not load), without the five
 *  group specialists (they have their own rooms or their own row). */
function specialists(o, roster) {
  const list = roster && Array.isArray(roster.roles) ? roster.roles.filter((r) => r.team === "specialist").map((r) => r.id)
    : Object.keys(o.roles || {}).filter((k) => k.startsWith("spec_"));
  return list.filter((id) => !GROUP_IDS.has(id));
}
/** The five v4 group specialists as the server lists them (roster, office roles or a room's members; never drawn
 *  before that). ownRooms: they sit in their own team rooms on this floor, so the 전문가실 does not draw them again. */
export function groupSpecs(o, roster) {
  const ids = new Set();
  let ownRooms = false;
  for (const z of (o && o.zones) || []) for (const m of z.members || []) if (GROUP_IDS.has(m)) { ids.add(m); ownRooms = true; }
  for (const r of (roster && Array.isArray(roster.roles) ? roster.roles : [])) if (GROUP_IDS.has(r.id)) ids.add(r.id);
  for (const k of Object.keys((o && o.roles) || {})) if (GROUP_IDS.has(k)) ids.add(k);
  return {ids: [...ids], ownRooms};
}

// a phone draws quiet rooms (no meeting today, none running) as one-line chips
const phone = typeof matchMedia === "function" ? matchMedia("(max-width: 559px)") : {matches: false};

export function makeFloor(ctx) {
  const grid = h("div", {class: "of-grid"});
  const quietRow = h("div", {class: "of-quiet", role: "group", "aria-label": "오늘 회의가 없는 방"});
  const el = h("div", {class: "of-floor", role: "region", "aria-label": "픽셀 사무실"}, grid, quietRow);
  const st = {nodes: new Map(), sig: new Map(), seenRun: null, shown: new Set(), ceo: null, owner: null};

  const openRoom = (id) => { if (id) ctx.go("rooms", id); else ctx.go("rooms"); };

  function person(z, role, roles, o) {
    const r = roleOf(roles, role);
    const spec = r.team === "specialist";
    const state = o.away ? ` · ${o.away}에서 회의 중` : o.talk ? " · 방금 말함" : o.next ? " · 다음 차례" : "";
    const room = spec && String(role).startsWith("spec_") && z.kind === "spec" && !o.atTable ? `strat:${String(role).slice(5)}` : z.room;
    const b = h("button", {class: ["of-person", o.away ? "away" : "", o.talk ? "talk" : ""], type: "button",
      title: `${r.name}${state} · 누르면 방 대화`, "aria-label": `${r.name}${state}. 누르면 방 대화를 엽니다`,
      dataset: {k: role}, onclick: () => openRoom(room)},
    figure({team: r.team, hue: hueFor(roles, role), kind: spec ? "spec" : "staff", size: o.small ? 18 : 24, i: o.i || 0, breathe: true}),
    h("span", {class: "nm"}, shortName(roles, role)));
    return b;
  }
  const seat = (p) => h("div", {class: "of-seat"}, p, h("i", {class: "of-desk", "aria-hidden": "true"}, h("i", {class: "of-mon"})));

  /** The bubbles of a live meeting: the stored last lines of its last two speakers (never typed out). */
  function bubbles(m, roles, first) {
    const lines = Object.values(m.lines || {}).filter((x) => x && x.line).sort((a, b) => (a.ts || 0) - (b.ts || 0)).slice(-2);
    const out = [];
    lines.forEach((x, i) => {
      const key = `${m.round_id}|${x.role}|${x.ts}`;
      const fresh = !first && !st.shown.has(key);
      st.shown.add(key);
      out.push(ui.bubble({who: `${roleName(roles, x.role)} · ${KIND_KO[x.kind] || "발언"}`, time: fmt.hm(x.ts), text: x.line,
        tail: i === lines.length - 1 && lines.length > 1 ? "tr" : "tl", fresh, cls: "of-say"}));
    });
    if (!out.length && m.code && m.code.line) {
      const key = `${m.round_id}|code|${m.code.ts}`;
      out.push(ui.bubble({who: "코드", time: fmt.hm(m.code.ts), text: m.code.line, tail: "tl", fresh: !first && !st.shown.has(key), cls: "of-say"}));
      st.shown.add(key);
    }
    return out;
  }

  function zoneModel(z, o, roster, busy) {
    const m = z.meeting;
    const at = m ? (m.participants || []) : [];
    let desks, plus = 0, groups = null;
    if (z.kind === "spec") {
      const featured = new Set((z.latest || []).map((r) => `spec_${r.strategy}`));
      const pool = z.members.filter((r) => !at.includes(r));
      const order = [...pool.filter((r) => featured.has(r)), ...pool.filter((r) => !featured.has(r))];
      desks = order.slice(0, SPEC_SHOWN);
      plus = Math.max(0, pool.length - desks.length);
      groups = groupSpecs(o, roster);
    } else {
      desks = z.members.filter((r) => !at.includes(r));
    }
    const away = {};
    for (const r of desks) if (busy.has(r) && busy.get(r) !== z.room) away[r] = busy.get(r + "#title");
    let sub = "";
    if (m) {
      const why = whyOf(m);
      sub = z.kind === "spec" ? `${m.title} · ${triggerKo(m)} · ${fmt.hm(m.started_ts)} 시작${z.others ? ` · 다른 매매법 방 ${z.others}곳도 회의 중` : ""}`
        : `${triggerKo(m)} · ${fmt.hm(m.started_ts)} 시작${why ? ` · ${why}` : ""}`;
    } else if (z.last) {
      sub = `${z.kind === "spec" ? z.last.title + " · " : ""}${triggerKo(z.last)} · ${fmt.hm(z.last.ended_ts || z.last.started_ts)} 끝`;
    } else if (z.kind === "spec") {
      sub = `매매법 방 ${fmt.int(z.members.length)}개 · 방마다 전담 1명`;
    }
    const lineKeys = m ? Object.values(m.lines || {}).map((x) => `${x.role}|${x.ts}`).sort().join(",") + (m.code ? `|c${m.code.ts}` : "") : "";
    const quiet = !m && !z.count;
    return {z, m, at, desks, plus, groups, away, sub, live: !!m, quiet, chip: quiet && phone.matches,
      sig: JSON.stringify([m && m.round_id, at, desks, plus, groups, away, sub, lineKeys, m && m.next_role, z.count, z.title, quiet && phone.matches])};
  }

  /** A quiet room on a phone: one line ("리스크팀 · 오늘 0회 ›") that opens its talk; no figures drawn. */
  function chipNode(md) {
    const {z} = md;
    return h("a", {class: "of-chip", href: ctx.href("rooms", z.room || null, z.room ? null : {f: "strategy"}), dataset: {zone: z.key},
      title: `${z.title} 대화 열기`}, h("b", null, z.title), h("span", null, `· 오늘 ${fmt.int(z.count)}회`), h("i", {"aria-hidden": "true"}, "›"));
  }

  function roomNode(md, o, first) {
    if (md.chip) return chipNode(md);
    const {z, m} = md;
    const roles = o.roles || {};
    const small = md.quiet;
    const head = h("div", {class: "of-room-h"},
      h("a", {class: "plate of-plate", href: ctx.href("rooms", z.room || null, z.room ? null : {f: "strategy"}), title: `${z.title} 대화 열기`}, z.title),
      md.live ? ui.livePill("LIVE") : null,
      h("span", {class: "of-cnt"}, "오늘 ", h("b", null, fmt.int(z.count)), "회"));
    const kids = [head];
    if (md.sub) kids.push(h("p", {class: "of-sub"}, md.sub));
    let i = 0;
    const deskEls = md.desks.map((r) => seat(person(z, r, roles, {away: md.away[r], small, i: i++})));
    if (md.plus) deskEls.push(h("span", {class: "of-plus", title: `나머지 전담 직원 ${md.plus}명`}, `+${fmt.int(md.plus)}`));
    kids.push(h("div", {class: "of-desks"}, deskEls));
    // the five group specialists: in their own rooms when the server gives them one (nothing more here), at desks in
    // this room when they are only listed, a "준비 중" note when the server does not list them yet
    const gs = md.groups;
    if (z.kind === "spec" && !small && gs && !gs.ownRooms) {
      kids.push(gs.ids.length
        ? h("div", {class: "of-groups"}, h("span", {class: "of-glabel"}, "그룹 전담"),
          h("div", {class: "of-desks"}, gs.ids.map((r) => seat(person(z, r, roles, {i: i++})))))
        : h("p", {class: "of-gnote", title: "paperbot/groups.py에 정해진 다섯 역할: 서버 명단에 들어오면 자리에 앉습니다"},
          "그룹 전담 5명 (구조·유동성 · 추세·눌림 · 세션·시가 · 반전·되돌림 · 5분봉 단타): 준비 중"));
    }
    if (m) {
      const bs = bubbles(m, roles, first);
      if (bs.length) kids.push(h("div", {class: "of-bubbles"}, bs));
      else kids.push(h("p", {class: "of-note"}, "회의를 열었습니다. 첫 발언이 기록되면 말풍선이 나옵니다."));
      const ppl = md.at.map((r) => person(z, r, roles, {talk: m.last_role === r, next: m.next_role === r, atTable: true, i: i++}));
      const half = Math.ceil(ppl.length / 2);
      kids.push(h("div", {class: "of-tz"}, h("div", {class: "of-side l"}, ppl.slice(0, half)), h("i", {class: "of-table", "aria-hidden": "true"}),
        h("div", {class: "of-side r"}, ppl.slice(half))));
      if (m.next_role) kids.push(h("p", {class: "of-next"}, `다음 차례 · ${roleName(roles, m.next_role)}`));
    }
    return h("section", {class: ["of-room", "tint", md.live ? "live" : "", small ? "quiet" : "", z.kind === "spec" ? "spec" : ""], "aria-label": z.title,
      dataset: {zone: z.key}, style: {"--h": zoneHue(z)}}, h("i", {class: "of-lamp", "aria-hidden": "true", title: md.live ? "회의 중: 불 켜짐" : null}), kids);
  }
  /** The team colour of a room's floor: its team (TEAM_HUE), a group specialist room, the strategy rooms. */
  function zoneHue(z) {
    if (z.kind === "spec") return TEAM_HUE.specialist;
    const t = String(z.room || "").replace(/^team:/, "");
    return TEAM_HUE[t] ?? (z.group ? TEAM_HUE.group : hueOf(z.room));
  }

  function ceoNode() {
    const say = h("div", {class: "of-ceo-say"});
    const win = h("div", {class: "of-win"}, windowArt(), h("span", {class: "of-phase"}));
    const node = h("section", {class: "of-room of-ceo", "aria-label": "대표실"},
      h("div", {class: "of-room-h"}, h("span", {class: "plate"}, "대표실")),
      h("div", {class: "of-ceo-in"},
        h("div", {class: "of-wall"}, win, h("div", {class: "of-wallr"},
          h("div", {class: "of-clocks"}, clock("KST", "Asia/Seoul"), clock("UTC", "UTC"), clock("NYC", "America/New_York")), sess)),
        h("div", {class: "of-boss"}, say,
          h("div", {class: "of-boss-figs"}, h("span", null, figure({kind: "owner", size: 28, i: 3, breathe: true})), h("span", null, figure({kind: "owner", size: 28, i: 5, breathe: true}))),
          h("div", {class: "of-bigdesk"}, deskReport(ctx), h("span", {class: "of-deskplate"}, "두 분")),
          h("p", {class: "of-boss-note"}, "주문 버튼 없음 · 모든 계좌는 모의"))));
    node._say = say;
    node._phase = win.lastChild;
    return node;
  }

  // the wall plate and the floor's time of day: Korea time, checked once a minute (paused while the page is hidden)
  const sess = h("div", {class: "of-sess", "aria-live": "off"});
  const SESS_KO = {asia: "아시아장", europe: "유럽장", us: "미국장", dawn: "장 사이 (새벽)"};
  function tickTime() {
    const now = Date.now();
    const se = bars.session(now), us = bars.usMarket(now), ph = skyPhase(now);
    el.dataset.ph = ph;
    sess.replaceChildren(h("b", null, `지금 ${SESS_KO[se.id] || se.ko}${se.weekend ? " · 주말" : ""}`), h("span", null, `미국 증시 ${us.text}`));
    if (st.ceo) st.ceo._phase.textContent = `창밖: 한국 ${PHASE_KO[ph]}`;
  }
  ctx.every(60000, tickTime);

  /** The owners' latest post today as their bubble (a real stored post), or nothing. */
  function setOwner(post, first) {
    if (!st.ceo) return;
    const key = post ? `${post.id}` : "";
    if (key === st.owner) return;
    st.owner = key;
    st.ceo._say.replaceChildren(post ? ui.bubble({who: `두 분 · ${post.room}`, time: fmt.hm(post.ts), text: post.text, tail: "tl", fresh: !first, cls: "of-say"}) : "");
  }

  /** Redraw what changed. o: /api/office; roster: /api/agents/roster (or null); owner: the owners' latest post today. */
  function update(o, roster, owner) {
    st.args = [o, roster, owner];
    const first = st.seenRun === null;
    const run = o.running || [];
    const runIds = new Set(run.map((m) => m.round_id));
    const fresh = first ? new Set() : new Set([...runIds].filter((id) => !st.seenRun.has(id)));
    st.seenRun = runIds;
    const busy = new Map();
    for (const m of run) for (const r of m.participants || []) { busy.set(r, m.room_id); busy.set(r + "#title", m.title); }
    const models = zonesOf(o, roster).map((z) => zoneModel(z, o, roster, busy));
    // where everybody stands now (only needed when a meeting just started: they walk from there)
    // zone|role -> where that person stood and where its room was; role -> the first place it stood (another room)
    const before = new Map(), rooms0 = new Map();
    if (fresh.size) {
      for (const [k, node] of st.nodes) rooms0.set(k, node.getBoundingClientRect());
      for (const p of el.querySelectorAll(".of-person[data-k]")) {
        const zone = p.closest(".of-room") && p.closest(".of-room").dataset.zone, r = p.getBoundingClientRect();
        if (!before.has(`${zone}|${p.dataset.k}`)) before.set(`${zone}|${p.dataset.k}`, r);
        if (!before.has(p.dataset.k)) before.set(p.dataset.k, r);
      }
    }
    const ordered = [...models].sort((a, b) => (b.live - a.live) || ((b.m && b.m.started_ts) || 0) - ((a.m && a.m.started_ts) || 0) || b.z.count - a.z.count);
    const walkers = [];
    ordered.forEach((md, idx) => {
      let node = st.nodes.get(md.z.key);
      if (!node || st.sig.get(md.z.key) !== md.sig) {
        const nn = roomNode(md, o, first);
        if (node) node.replaceWith(nn);
        node = nn;
        st.nodes.set(md.z.key, node); st.sig.set(md.z.key, md.sig);
        if (md.m && fresh.has(md.m.round_id)) for (const p of node.querySelectorAll(".of-tz .of-person")) walkers.push([p, md.z.key, node]);
      }
      const box = md.quiet ? quietRow : grid;
      if (node.parentNode !== box) box.append(node);
      node.style.order = String(idx);
    });
    if (!st.ceo) { st.ceo = ceoNode(); grid.append(st.ceo); tickTime(); }
    st.ceo.style.order = "999";
    // fill-people: the 상황판 wall screen in the wood next to the 대표실 (office-wall.js)
    if (st.wall) { if (st.wall.parentNode !== grid) grid.append(st.wall); st.wall.style.order = "1000"; }
    setOwner(owner, first);
    quietRow.hidden = !quietRow.children.length;
    // real meeting start: its members walk from where they stood to the table
    for (const [p, zone, node] of walkers) {
      // from its own desk in this room (mapped into the room's new place: a room may move up when its meeting starts),
      // else from wherever it stood in another room
      const own = before.get(`${zone}|${p.dataset.k}`), r0 = rooms0.get(zone);
      let from = before.get(p.dataset.k);
      if (own && r0) { const r1 = node.getBoundingClientRect(); from = {left: own.left - r0.left + r1.left, top: own.top - r0.top + r1.top}; }
      if (!from) continue;
      const to = p.getBoundingClientRect();
      const dx = from.left - to.left, dy = from.top - to.top;
      if (Math.abs(dx) + Math.abs(dy) < 2) continue;
      p.style.transition = "none"; p.style.left = `${dx}px`; p.style.top = `${dy}px`;
      void p.offsetWidth;
      p.style.transition = "";
      p.classList.add("walking");
      motion.walkTo(p, "0px", "0px");
      setTimeout(() => p.classList.remove("walking"), 1500);
    }
  }
  // crossing the phone width redraws the quiet rooms as chips or as rooms
  const onWidth = () => { if (st.args) update(...st.args); };
  if (phone.addEventListener) { phone.addEventListener("change", onWidth); ctx.track(() => phone.removeEventListener("change", onWidth)); }
  return {el, update, setWall: (node) => { st.wall = node; }};
}
