// #/server — 서버·비용 (builder E, mockup screen 08). Where the health dot leads: what is down or worth a look, every
// part of the health card as a tile, the gauges (signal time vs limit, AI calls / tokens vs caps, debate spend vs cap;
// CPU / memory / disk / DB / Telegram show 수집 전 until /api/v4/server exists), the scheduled jobs, the run facts and
// 로그아웃. Old homes: 분석 › 건강 점검, 서버 상태 tiles + 24시간 신호, the agents-stopped banner (INVENTORY.md 7, 9, 12).
import {h, ui, fmt, features} from "../core/pb.js";
import {summaryCard, tilesCard} from "./server-health.js";
import {gaugeBoard} from "./server-gauges.js";
import {jobsCard, factsCard} from "./server-jobs.js";

export async function mount(el, ctx) {
  ctx.setTitle("서버·비용");
  const head = ui.screenHead("서버·비용", "봇·시세·에이전트가 버티는지 한 화면에");
  const sub = head.querySelector(".sub");
  const sum = summaryCard(ctx);
  const tiles = tilesCard();
  const gauges = gaugeBoard(ctx);
  const jobs = jobsCard();
  const facts = factsCard();
  const out = h("div", {class: "row wrap server-out"},
    h("button", {class: "btn-line", type: "button", onclick: logout}, "로그아웃"),
    h("a", {class: "btn-line", href: "/"}, "예전 대시보드"),
    h("span", {class: "muted"}, "로그아웃하면 다시 비밀번호를 넣어야 합니다."));
  el.append(head, sum,
    // phone: tiles, gauges, jobs, facts; wide PC: the gauges in their own column (server.css grid areas)
    h("div", {class: "server-cols"}, tiles, ui.card({cls: "server-gcard", label: "서버·비용 계기판"}, gauges), jobs, facts),
    out);

  const st = {health: null, healthErr: null, status: null, board: null};
  const paintHealth = () => { sum.update(st.health, st.healthErr); tiles.update(st.health); jobs.update(st.health); };
  ctx.watch("health", (v, k, err) => { if (v) st.health = v; st.healthErr = err || null; paintHealth(); });
  ctx.watch("status", (v) => { if (!v) return; st.status = v; gauges.setSignals(v, null); facts.update(v, st.board); });
  ctx.watch("board", (b) => {
    if (!b) return;
    st.board = b;
    facts.update(st.status, b);
    sub.textContent = `계좌 ${fmt.int((b.accounts || []).length)}개 기준 · 봇·시세·에이전트가 버티는지 한 화면에`;
  });
  ctx.watch("usage", (u) => gauges.setUsage(u));

  // the debate room's spend: only once the room has run (features.debate); before that '꺼짐 · 0'
  let unDebate = null;
  const debateFeature = () => {
    if (features.debate && !unDebate) unDebate = ctx.watch("debate", (d) => gauges.setDebate(d, true));
    if (!features.debate) gauges.setDebate(null, false);
  };
  debateFeature();
  ctx.on("features", debateFeature);

  // the live stream's heartbeat is newer than the 60 s health card: the bot / 1m / connection tiles follow it
  ctx.on("stream:state", paintHealth);
  ctx.every(5000, paintHealth, {now: false});

  // NEEDS SERVER #4: probed once per visit; a 404 stops the polling (the gauges stay 수집 전), an answer keeps it every
  // 60 s, so the gauges light up by themselves the day the server adds the route
  let v4Server = true;
  ctx.every(60000, async () => {
    if (!v4Server) return;
    try { const v = await ctx.api("/api/v4/server"); gauges.setServer(v); gauges.setSignals(st.status, v); } catch (e) { if (e && e.status === 404) v4Server = false; }
  });

  async function logout() {
    try { await ctx.post("/api/logout", {}); } catch { /* the cookie is cleared or gone either way */ }
    location.href = "/login";
  }
}

export function unmount() {}
