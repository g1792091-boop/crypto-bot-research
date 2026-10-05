// 에이전트 방 (builder D, CONTRACT.md section 4 / INVENTORY section 9): the agents' rooms as a messenger inside the
// console frame (mockup section 06). Room list → chat → info: three panes side by side on a wide screen, one at a time
// on a phone (#/rooms = list, #/rooms/<room_id> = chat, ?p=info = info; update() switches in place).
// The list: 전체 / 팀 / 매매법, search, unread dots (per viewer, local), "회의 중" only from /api/rooms `running`,
// proposals waiting for the owners. Chat: rooms-chat.js. Info: rooms-side.js. The agents' stopped / failing banners.
import {h, ui, fmt, local, store} from "../core/pb.js";
import {roomAvatar, agentsState, agentsBadge, agentsBanner, syncUnread, markSeen} from "./rooms-kit.js";
import {makeChat} from "./rooms-chat.js";
import {makeSide} from "./rooms-side.js";

const NARROW = "(max-width: 1099px)";
let cur = null;           // the mounted screen's update hook (update() is module-level by contract)

export async function mount(el, ctx) {
  ctx.setTitle("에이전트 방");
  const mq = matchMedia(NARROW);
  const narrow = () => mq.matches;
  const st = {ov: null, id: null, pane: "list", filter: local.get("rooms-filter", "all"), q: "", seen: {}, roles: {}, room: null};

  el.append(ui.screenHead("에이전트 방", "직원들의 회의 대화 · 두 분이 끼어들 수도 있습니다 (선택)"));
  // ---------------------------------------------------------------- frame + panes
  const badge = h("span", {class: "rm-badge"});
  const banner = h("div", {class: "rm-banner", hidden: true});
  const waitAll = h("button", {class: "rm-wait", type: "button", hidden: true});
  const listPane = h("aside", {class: "rm-lpane", "aria-label": "방 목록"});
  const hooks = {
    pane: (p, toProps) => setPane(p, toProps),
    narrow, ov: () => st.ov, cur: () => (st.ov && st.ov.rooms || []).find((r) => r.room_id === st.id),
    roles: () => st.roles,
    seen: (id, top) => { if (narrow() && st.pane !== "chat") return; st.seen = markSeen(id, top); syncUnread(st.ov); renderList(); },
    sideChanged: () => side.load(), refreshOv: () => store.refresh("rooms").catch(() => {}),
  };
  const chat = makeChat(ctx, {...hooks, roomInfo: (r) => { st.room = r; side.setRoom(r); }});
  const side = makeSide(ctx, hooks);
  const panes = h("div", {class: "rm-panes", dataset: {pane: "list"}}, listPane, chat.el, side.el);
  const frame = h("section", {class: "console rm-frame", "aria-label": "에이전트 방"},
    h("div", {class: "con-head"}, h("span", {class: "con-title"}, "에이전트 방"), h("span", {class: "grow"}), badge), banner, waitAll, panes);
  el.append(frame, h("p", {class: "rk-note"}, "대화는 직원들이 회의 기록에 저장한 글 그대로입니다 (실시간 타이핑 아님). 숫자와 판정은 코드가 계산하고, AI 직원은 주문하지 않습니다. 두 분 글은 선택이며 다음 차례에 직원들이 읽습니다."));

  // ---------------------------------------------------------------- the list
  const seg = ui.seg([{id: "all", label: "전체"}, {id: "team", label: "팀"}, {id: "strategy", label: "매매법"}], st.filter,
    (f) => { st.filter = f; local.set("rooms-filter", f); renderList(true); }, {label: "방 종류"});
  const search = h("input", {class: "search", type: "search", placeholder: "방 이름 찾기", "aria-label": "방 이름 찾기", autocomplete: "off"});
  search.addEventListener("input", () => { st.q = search.value; renderList(true); });
  const teamBox = h("div", {class: "rm-rows", role: "list"});
  const teamHead = h("p", {class: "rm-lsec"});
  const stratHead = h("p", {class: "rm-lsec"});
  const pager = ui.pager({size: 8, empty: "찾는 방이 없습니다", row: (r) => roomRow(r)});
  listPane.append(seg, search, teamHead, teamBox, stratHead, pager.el);

  function lastLine(r) {
    if (!r.last_text) return h("span", {class: "muted"}, "아직 회의 없음");
    const who = r.last_speaker && !["code", "system"].includes(r.last_role) ? `${r.last_speaker}: ` : "";
    const lines = String(r.last_text).split("\n");
    if (lines.length > 1 && /^\s*↳/.test(lines[0])) lines.shift();
    return who + lines.join(" ").replace(/\s+/g, " ").trim();
  }
  function roomRow(r) {
    const unread = (r.last_id || 0) > (st.seen[r.room_id] || 0);
    return h("button", {class: ["rm-row", r.room_id === st.id ? "sel" : "", unread ? "unread" : ""], type: "button", role: "listitem",
      "aria-current": r.room_id === st.id ? "true" : null, onclick: () => ctx.go("rooms", r.room_id)},
    roomAvatar(r),
    h("span", {class: "rm-rb"}, h("span", {class: "rm-r1"}, h("b", null, r.title), h("time", null, r.last_ts ? fmt.hm(r.last_ts) : "")),
      h("span", {class: "rm-r2"}, h("span", {class: "rm-lt"}, lastLine(r)),
        r.running ? h("span", {class: "live-pill rm-livepill"}, "회의 중") : null,
        r.open_proposals ? ui.pill(`승인 대기 ${fmt.int(r.open_proposals)}`, "accent") : null,
        unread ? h("i", {class: "rm-udot", title: "새 대화", "aria-label": "새 대화"}) : null)));
  }
  function renderList(resetPage) {
    const ov = st.ov;
    if (!ov) return;
    const q = st.q.trim().toLowerCase();
    const match = (r) => (st.filter === "all" || r.kind === st.filter) &&
      (!q || String(r.title).toLowerCase().includes(q) || String(r.strategy || "").toLowerCase().includes(q));
    const team = ov.rooms.filter((r) => r.kind === "team" && match(r));
    const strat = ov.rooms.filter((r) => r.kind !== "team" && match(r))
      .sort((a, b) => (b.running - a.running) || ((b.last_ts || 0) - (a.last_ts || 0)) || (b.last_id - a.last_id));
    teamHead.hidden = teamBox.hidden = !team.length;
    teamHead.replaceChildren("팀 방 ", h("small", null, fmt.int(team.length)));
    teamBox.replaceChildren(...team.map(roomRow));
    stratHead.hidden = !strat.length && team.length > 0;
    stratHead.replaceChildren("매매법 방 ", h("small", null, fmt.int(strat.length)), h("span", null, "최근 대화 순"));
    pager.set(strat, !resetPage);
    const waiting = ov.rooms.reduce((s, r) => s + (r.open_proposals || 0), 0);
    waitAll.hidden = !waiting;
    waitAll.replaceChildren("두 분 확인을 기다리는 제안 ", h("b", null, `${fmt.int(waiting)}건`), h("span", null, "보기 →"));
    waitAll.onclick = () => { const r = ov.rooms.find((x) => x.open_proposals); if (r) { ctx.go("rooms", r.room_id, {p: "info"}); } };
  }
  function renderState() {
    const a = agentsState(st.ov);
    badge.replaceChildren(agentsBadge(a));
    const b = a.st === "ok" ? null : agentsBanner(a);
    banner.replaceChildren(...(b ? [b] : []));
    banner.hidden = !b;
  }

  // ---------------------------------------------------------------- panes and routing
  function setPane(p, toProps) {
    st.pane = p;
    panes.dataset.pane = p;
    if (narrow()) {
      const want = p === "list" ? ctx.href("rooms") : ctx.href("rooms", st.id, p === "info" ? {p: "info"} : null);
      if (location.hash !== want) window.history.replaceState(null, "", want);
      window.scrollTo(0, Math.max(0, frame.getBoundingClientRect().top + window.scrollY - 120));
    }
    if (p === "chat" && st.id) hooks.seen(st.id, ((hooks.cur() || {}).last_id) || 0);
    if (p === "info" && toProps) requestAnimationFrame(() => side.scrollToProps());
  }
  function defaultRoom() {
    const saved = local.get("rooms-last", null);
    const rooms = (st.ov && st.ov.rooms) || [];
    if (saved && rooms.some((r) => r.room_id === saved)) return saved;
    const best = rooms.reduce((b, r) => (!b || r.last_id > b.last_id ? r : b), null);
    return best && best.last_id ? best.room_id : "team:lead";
  }
  async function route(params) {
    let id = params.arg || null;
    const wantInfo = params.query && params.query.p === "info";
    if (!id && !narrow()) id = defaultRoom();
    if (id && id !== st.id) {
      st.id = id; local.set("rooms-last", id);
      chat.open(id); side.open(id, null);
      renderList();
    }
    setPane(id ? (wantInfo ? "info" : "chat") : "list", wantInfo);
  }
  cur = route;
  ctx.track(() => { if (cur === route) cur = null; });
  ctx.listen(mq, "change", () => { if (!narrow() && !st.id) route({arg: null, query: {}}); });

  // ---------------------------------------------------------------- data
  ctx.watch("rooms", (ov, k, err) => {
    if (!ov) { if (err && !st.ov) listPane.append(ui.errorBox(err, () => store.refresh("rooms").catch(() => {}))); return; }
    st.ov = ov;
    st.seen = syncUnread(ov);
    chat.setOv(ov);
    renderState(); renderList();
    side.render();
  });
  ctx.watch("usage", (u) => { if (u) side.setUsage(u); });
  ctx.on("rooms", (map) => {
    if (st.id && (map[st.id] || 0) > 0) chat.fetchNew();
  });
  // staff names for avatars and stances (the office's role map; a missing name falls back to the role id)
  Promise.all([store.need("office", 30000).catch(() => null), ctx.api("/api/agents/roster").catch(() => null)]).then(([o, ro]) => {
    const m = {};
    for (const r of (ro && ro.roles) || []) m[r.id] = r;
    Object.assign(m, (o && o.roles) || {});
    st.roles = m;
  });
  const ov0 = await store.need("rooms", 20000).catch(() => null);
  if (!ctx.alive()) return;
  if (ov0) { st.ov = ov0; st.seen = syncUnread(ov0); chat.setOv(ov0); renderState(); renderList(); }
  await route(ctx.params);
}

/** Same screen, new #/rooms/<id> or ?p=: switch rooms / panes in place. */
export function update(params) { if (cur) return cur(params); }

export function unmount() {}
