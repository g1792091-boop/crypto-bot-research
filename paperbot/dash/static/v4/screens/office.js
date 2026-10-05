// 회의실 (builder D, CONTRACT.md section 4): the warm wooden pixel office (office-floor.js) with the 에이전트 콘솔 on the
// right on a PC and below on a phone (office-feed.js), a status line, today's finished meetings with step strips that
// light only the kinds that were really spoken, and the honesty note.
// HONESTY: LIVE / 지금 회의 only from /api/office `running`; bubbles are stored lines; console lines are stored
// records that slide in only when they are really new; no typing, no endless activity. AI never trades.
import {h, put, ui, fmt, store, features, consolePanel} from "../core/pb.js";
import {makeFloor} from "./office-floor.js";
import {makeFeed} from "./office-feed.js";
import {makeWall, countdown} from "./office-wall.js";
import {STEPS, statusPill, stripLead, agentsState, agentsBanner, syncUnread, roomIdKo, triggerKo} from "./rooms-kit.js";

const NOTE = "말풍선은 회의 기록에 저장된 실제 마지막 발언(첫 문장)입니다. 직원의 AI 차례가 끝나 기록될 때마다 바뀌며 실시간 타이핑이 아닙니다. " +
  "'다음 차례'는 회의 순서상 다음 직원이고, 순서가 앞 사람의 답에 달려 있으면 표시하지 않습니다. 흐린 직원은 다른 방 회의에 가 있는 사람입니다. " +
  "직원이나 방 이름을 누르면 그 방 대화가 열립니다. AI 직원은 회의와 기록만 하고 주문하지 않습니다.";

let rosterCache = null;          // /api/agents/roster is the code's fixed roster: read once per page

export async function mount(el, ctx) {
  ctx.setTitle("회의실");
  const st = {o: null, ov: null, roster: rosterCache, done: null, doneKey: "", debateTab: features.debateRunning, err: null};

  el.append(ui.screenHead("회의실", "AI 직원들이 실제로 회의하는 모습 · 거래는 하지 않습니다"));
  const top = h("div", {class: "of-top", "aria-live": "polite"});
  const banner = h("div", {class: "of-banner"});
  const floor = makeFloor(ctx);
  const wall = makeWall(ctx);
  floor.setWall(wall.el);
  // the status line's live countdown to the next fixed meeting (a real scheduled time from /api/office)
  const cdEl = h("b", {class: "of-cd num"});
  const paintCd = () => { const n = st.o && st.o.schedule && st.o.schedule.next; const t = countdown(n && n.at_ms); cdEl.textContent = t ? ` · ${t} 남음` : ""; };
  ctx.every(1000, paintCd);
  const feed = makeFeed(ctx, () => renderConsole());
  let con = makeConsole();
  const main = h("div", {class: "of-main"}, floor.el, con);
  floor.el.dataset.tour = "office";                     // the first-visit tour points here (core/tour.js)
  const office = h("div", {class: "of-office"}, top, banner, main);
  const doneBody = h("div", {class: "of-done"}, ui.empty("불러오는 중"));
  const doneCard = ui.card({plate: "오늘 끝난 회의", sub: "단계는 실제로 말한 차례만 켜집니다",
    acts: [h("a", {class: "btn-line", href: ctx.href("digest", "day")}, "회의 요약")]}, doneBody);
  const slotsEl = h("p", {class: "rk-note of-honest"});
  el.append(office, doneCard, slotsEl, h("p", {class: "rk-note of-honest"}, NOTE));

  function makeConsole() {
    return consolePanel({title: "에이전트 콘솔", max: 80,
      tabs: [{id: "all", label: "전체"}, {id: "agent", label: "에이전트"}, {id: "debate", label: "토론", hidden: !features.debateRunning}],
      foot: "회의 시작 줄을 누르면 그 회의만 봅니다"});
  }

  // ---------------------------------------------------------------- status line
  function renderTop() {
    const o = st.o;
    if (!o) return;
    const run = o.running || [];
    const nx = o.schedule && o.schedule.next;
    const next = nx ? `다음 정기 ${nx.tomorrow ? "내일 " : ""}${nx.hhmm} ${triggerKo(nx)} (${nx.where})` : "정해진 시각의 회의 없음";
    const today = o.today || {};
    put(top,
      ui.plate("회의실"),
      run.length ? ui.livePill("LIVE") : null,
      h("b", {class: "of-now"}, run.length ? `지금 회의 ${fmt.int(run.length)}개` : "지금 회의 없음"),
      run.length ? h("span", {class: "of-now-t"}, run.map((m) => `${m.title} ${triggerKo(m)}`).join(" · ")) : null,
      h("span", {class: "grow"}),
      h("span", {class: "of-stats"}, "오늘 회의 ", h("b", null, fmt.int(today.meetings || 0)), " · AI 호출 ", h("b", null, fmt.int(today.ai_calls || 0)), ` · ${next}`, cdEl),
      h("button", {class: "btn-line of-jump", type: "button", onclick: () => con.scrollIntoView({block: "start", behavior: "smooth"})}, "콘솔 ↓"));
    const slots = (o.schedule && o.schedule.slots) || [];
    slotsEl.textContent = slots.length ? `정기 회의 (한국 시간): ${slots.map((x) => `${x.hhmm} ${triggerKo(x)}`).join(" · ")}. 손실·사고·두 분 글·연구 회의는 정해진 시각 없이 열립니다.` : "";
    const notes = [];
    if (o.ready === false) notes.push(h("p", {class: "rk-banner"}, "에이전트 기록(agents3.db)이 아직 없습니다. 직원들이 첫 회의를 하면 여기에 나옵니다."));
    if (o.error) notes.push(h("p", {class: "rk-banner bad"}, String(o.error)));
    const a = st.ov ? agentsState(st.ov) : null;
    if (a && a.st !== "ok" && !(a.st === "new" && o.ready === false)) notes.push(agentsBanner(a));
    banner.replaceChildren(...notes);
    banner.hidden = !notes.length;
  }

  function renderFloor() {
    if (!st.o) return;
    try { floor.update(st.o, st.roster, feed.owner()); } catch (e) { console.error("office floor", e); }
  }

  // ---------------------------------------------------------------- console
  function renderConsole() {
    const r = feed.lines((st.o && st.o.roles) || {}, store.get("board"), features.debateRunning);
    if (!r.loaded) return;                         // the first fill waits for rooms and trades (nothing slides in by mistake)
    con.setLines(r.lines);
    if (!r.lines.length) con.showEmpty("오늘(한국 0시 이후) 회의와 거래 기록이 아직 없습니다");
    const run = (st.o && st.o.running) || [];
    con.setFoot(`${run.length ? `회의 중 · ${run.map((m) => m.title).join(", ")} · ` : ""}회의 시작 줄을 누르면 그 회의만 봅니다 · ` +
      `딥시크·동전 봇 거래는 개수만: 오늘 딥시크 ${fmt.int(r.quiet.ds)}건 · 동전 봇 ${fmt.int(r.quiet.coin)}건`);
    renderFloor();                                  // the owners' latest post is the 대표실 bubble
  }

  // ---------------------------------------------------------------- today's finished meetings
  const pager = ui.pager({size: 5, empty: "오늘(한국 0시 이후) 끝난 회의가 아직 없습니다", row: (m) => doneRow(m)});
  function doneRow(m) {
    const kinds = new Set((m.speakers || []).map((s) => s.kind));
    const sum = stripLead(m.summary_ko) || (m.lead || [])[0] || "";
    return h("div", {class: "of-drow", role: "listitem"},
      h("div", {class: "of-drow-h"}, h("time", null, fmt.hm(m.ended_ts || m.started_ts)), h("b", null, m.title || roomIdKo(m.room_id)),
        h("span", {class: "muted"}, triggerKo(m)), h("span", {class: "grow"}), statusPill(m.status)),
      sum ? h("p", {class: "of-drow-s"}, sum) : null,
      ui.stepStrip(STEPS, {done: STEPS.map((s) => s.id).filter((k) => kinds.has(k)), label: "회의 단계 (실제로 말한 차례만)"}),
      h("div", {class: "of-drow-f"}, h("span", {class: "muted"}, `AI ${fmt.int(m.calls)}회${(m.speakers || []).length ? ` · 발언 ${fmt.int(m.speakers.length)}번` : ""}`),
        h("span", {class: "grow"}),
        h("a", {class: "btn-line", href: ctx.href("digest", "day", {r: m.round_id})}, "요약"),
        h("a", {class: "btn-line", href: ctx.href("rooms", m.room_id)}, "방 열기")));
  }
  async function loadDone() {
    try {
      const d = await ctx.api("/api/digest/day");
      if (!ctx.alive()) return;
      st.done = d;
      if (d.error) { doneBody.replaceChildren(ui.empty(String(d.error))); return; }
      const ms = (d.meetings || []).filter((m) => m.status !== "running").sort((a, b) => (b.ended_ts || b.started_ts) - (a.ended_ts || a.started_ts));
      if (!pager.el.isConnected) doneBody.replaceChildren(pager.el);
      pager.set(ms, true);
    } catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      if (!st.done) doneBody.replaceChildren(ui.errorBox(e, loadDone));
    }
  }

  // ---------------------------------------------------------------- data
  ctx.watch("office", (o, k, err) => {
    if (!o) { if (err && !st.o) floor.el.replaceChildren(ui.errorBox(err, () => store.refresh("office").catch(() => {}))); return; }
    st.o = o;
    renderTop(); renderFloor(); wall.update(o); paintCd();
    const key = (o.recent || []).map((r) => r.round_id).join(",");
    if (key !== st.doneKey) { const firstLoad = !st.doneKey && st.done === null; st.doneKey = key; if (!firstLoad) loadDone(); }
  });
  ctx.watch("rooms", (ov) => { if (!ov) return; st.ov = ov; feed.syncRooms(ov); syncUnread(ov); renderTop(); });
  ctx.on("rooms", (map) => feed.onRooms(map));
  ctx.on("trades", (rows) => feed.onTrades(rows));
  if (features.debate) ctx.watch("debate", (d) => feed.onDebate(d));
  ctx.on("features", () => {
    if (features.debateRunning === st.debateTab) return;
    st.debateTab = features.debateRunning;
    const nc = makeConsole(); con.replaceWith(nc); con = nc; renderConsole();
  });
  feed.loadTrades();
  if (!st.roster) {
    ctx.api("/api/agents/roster").then((r) => { rosterCache = r; st.roster = r; renderFloor(); }).catch(() => { /* drawn from /api/office alone */ });
  }
  ctx.every(60000, loadDone, {now: false});
  // first paint: wait for the office (the router shows a shimmer meanwhile), then the finished meetings
  await Promise.all([store.need("office", 6000).catch(() => null), loadDone()]);
}

export function unmount() {}
