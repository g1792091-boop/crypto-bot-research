// 분석 (builder C, CONTRACT.md section 4, INVENTORY sections 6-7). #/analysis/<view>[?account=<id>]: one view at a time,
// chosen in a scrolling tab row, every view in the same card style (analysis-kit.js viewHead → content cards).
// Views and their routes (all read-only, descriptive):
//   손익비·위험 risk · 실전 준비도 readiness · 충격 테스트 shock      (analysis-risk.js)
//   코인·장세 지도 map · 코인·시간대 /api/breakdown · 진입 순간 entry · 상황 태그 /api/cards/stats   (analysis-where.js)
//   좋은 자리 vs 보통 levrule · 그림자 비교 shadows · 계좌 겹침 /api/overlap · 조합 시너지 synergy (analysis-rules.js)
//   GH Coin /api/ghcoin (only while its recorder runs) · 45개 질문 questions (only when filled)
// 건강 점검 moved to 서버·비용 and 알림 기록 to 알림 기록 (builder E). A {pending: true} answer shows the shimmer and asks
// again after 3 s (the server computes heavy views in the background). The last view is remembered (local).
import {h, put, ui, motion, local} from "../core/pb.js";
import * as R from "./analysis-risk.js";
import * as W from "./analysis-where.js";
import * as X from "./analysis-rules.js";
import * as C from "./analysis-costs.js";

const VIEWS = [
  {id: "risk", label: "손익비·위험", path: "/api/analysis/risk", render: R.risk, desc: "이길 때와 질 때의 크기, 낙폭과 파산 위험"},
  {id: "map", label: "코인·장세 지도", path: "/api/analysis/map", render: W.map, desc: "코인·장세·시간대·방향·봉별로 어디서 벌고 잃었나"},
  {id: "sessions", label: "코인·시간대", path: "/api/breakdown", render: W.sessions, desc: "코인별, 평일·주말 × 시간대, 펀딩·미국장 개장·지표 발표 시간"},
  {id: "entry", label: "진입 순간", path: "/api/analysis/entry", render: W.entry, desc: "들어가는 봉의 모습별 성적"},
  {id: "tags", label: "상황 태그", path: "/api/cards/stats?days=30", render: W.tags, desc: "손실과 이익에 붙은 상황 표시 (경제지표 발표 전후 등)"},
  {id: "levrule", label: "좋은 자리 vs 보통", path: "/api/analysis/levrule", render: X.levrule, desc: "좋은 자리에서 배수를 높인 레버리지 규칙 B의 중간 숫자"},
  {id: "shadows", label: "그림자 비교", path: "/api/analysis/shadows", render: X.shadows, desc: "같은 거래를 손절·잠금·익절·레버리지 하나만 바꿔 다시 계산"},
  {id: "overlap", label: "계좌 겹침", path: "/api/overlap?days=7", render: X.overlap, desc: "같이 움직이는 계좌와 한 코인에 몰린 순간"},
  {id: "synergy", label: "조합 시너지", path: "/api/analysis/synergy", render: X.synergy, desc: "매매법 여러 개를 같이 돌렸다면"},
  {id: "shock", label: "충격 테스트", path: "/api/analysis/shock", render: R.shock, desc: "가격이 한 번에 크게 움직이면 지금 포지션은"},
  {id: "ready", label: "실전 준비도", path: "/api/analysis/readiness", render: R.ready, desc: "실거래 전에 정한 조건 8개를 계좌마다"},
  {id: "costs", label: "비용", path: "/api/v4/costs", render: C.costs, desc: "수수료·펀딩이 깎아 먹는 몫과 실제 호가였다면 (추정)"},
  {id: "ghcoin", label: "GH Coin", path: "/api/ghcoin", render: X.ghcoin, feature: "ghcoin", desc: "GH Coin 타점 기록 (따로 도는 기록기)"},
  {id: "questions", label: "45개 질문", path: "/api/analysis/questions", render: X.questions, feature: "questions", desc: "질문마다 답이 있는지"},
];
const FRESH_MS = 5 * 60 * 1000;

let current = null;

export async function mount(el, ctx) {
  ctx.setTitle("분석");
  const st = {tab: null, cache: {}, gen: 0, disposers: [], summary: null, ready: false};
  const shown = () => VIEWS.filter((v) => !v.feature || ctx.features[v.feature]);
  const pick = (id) => (shown().some((v) => v.id === id) ? id : "risk");
  st.tab = pick(ctx.params.arg || local.get("an-tab", "risk"));

  const segSlot = h("div", {class: "an-tabs"});
  const desc = h("p", {class: "an-desc"});
  const body = h("div", {class: "stack an-body"});
  el.append(ui.screenHead("분석", "매매법 계좌의 거래를 여러 방향으로 나눠 봅니다 · 설명용, 판정 아님"), segSlot, desc, body);

  function renderSeg() {
    put(segSlot, ui.seg(shown().map((v) => ({id: v.id, label: v.label})), st.tab, (id) => go(id, true), {label: "분석 보기", scroll: true}));
    // bring the chosen tab into the row's own view (never scroll the page sideways)
    requestAnimationFrame(() => {
      const row = segSlot.firstChild, on = segSlot.querySelector('[aria-selected="true"]');
      if (row && on && row.scrollWidth > row.clientWidth) row.scrollLeft = Math.max(0, on.offsetLeft - row.offsetLeft - (row.clientWidth - on.offsetWidth) / 2);
    });
  }

  function closeTab() { for (const f of st.disposers.splice(0)) { try { f(); } catch (e) { console.error(e); } } }

  function verdictTs() {
    const s = st.summary || {};
    return (s.restart && s.restart.ready && s.restart.verdict_ts) || (s.next_checkpoint && s.next_checkpoint.ts) || null;
  }

  async function load(force) {
    const v = VIEWS.find((x) => x.id === st.tab) || VIEWS[0];
    const q = (ctx.params && ctx.params.query) || {};
    const path = v.id === "shadows" && q.account ? `${v.path}?account=${encodeURIComponent(q.account)}` : v.path;
    const g = ++st.gen;
    desc.textContent = v.desc;
    const hit = st.cache[path];
    if (hit && !force && Date.now() - hit.at < FRESH_MS) { paint(v, hit.d, q); return; }
    closeTab();
    put(body, motion.shimmer(5, true));
    let d;
    try { d = await ctx.api(path); } catch (e) {
      if (!ctx.alive() || g !== st.gen) return;
      put(body, ui.errorBox(e, () => load(true)));
      return;
    }
    if (!ctx.alive() || g !== st.gen) return;
    if (d && d.pending) {
      put(body, ui.card({plate: v.label}, h("p", {class: "muted"}, d.note || "서버가 계산하는 중입니다. 잠시 뒤 다시 봅니다."), motion.shimmer(4)));
      ctx.timeout(() => { if (g === st.gen) load(true); }, 3000);
      return;
    }
    st.cache[path] = {d, at: Date.now()};
    paint(v, d, q);
  }

  function paint(v, d, q) {
    closeTab();
    if (d && d.unavailable) { put(body, ui.card({plate: v.label}, h("p", {class: "muted"}, "준비 중입니다. ", d.note || ""))); return; }
    if (d && d.error && v.id !== "shadows") { put(body, ui.card({plate: v.label}, h("p", {class: "muted"}, String(d.error)))); return; }
    const env = {ctx, verdictTs: verdictTs(), ready: st.ready, query: q,
      track: (f) => st.disposers.push(f),
      reload: (nq) => { ctx.go("analysis", v.id, nq); }};
    let nodes;
    try { nodes = v.render(d || {}, env); } catch (e) {
      console.error(e);
      nodes = [ui.card({plate: v.label}, h("p", {class: "muted"}, "이 화면을 그리지 못했습니다 (자료 모양이 바뀌었을 수 있음)."))];
    }
    put(body, ...nodes);
    motion.swap(body);
  }

  function go(id, user) {
    id = pick(id);
    if (id === st.tab && !user) return;
    st.tab = id;
    local.set("an-tab", id);
    if (user) {
      try { window.history.replaceState(null, "", ctx.href("analysis", id)); } catch { /* keep the hash */ }
      ctx.params = {...ctx.params, arg: id, query: {}};
    }
    renderSeg();
    load(false);
  }

  current = (params) => {
    const id = pick(params.arg || st.tab);
    const changed = id !== st.tab;
    st.tab = id; local.set("an-tab", id);
    renderSeg();
    load(!changed);           // same view, new query (the shadow account): fetch it
  };
  ctx.track(() => { closeTab(); current = null; });

  renderSeg();
  const [s0, cp] = await Promise.all([ctx.store.need("summary", 60000).catch(() => null), ctx.store.need("checkpoint", 600000).catch(() => null)]);
  if (!ctx.alive()) return;
  st.summary = s0; st.ready = !!(cp && cp.ready);
  ctx.watch("summary", (s) => { if (s) st.summary = s; });
  ctx.on("features", () => { const t = pick(st.tab); renderSeg(); if (t !== st.tab) go(t, false); });
  await load(false);
  // views go stale with new trades: refresh the visible one every 5 minutes (each route is cached on the server too)
  ctx.every(FRESH_MS, () => load(true), {now: false});
}

export function update(params) { if (current) current(params); }

export function unmount() { current = null; }
