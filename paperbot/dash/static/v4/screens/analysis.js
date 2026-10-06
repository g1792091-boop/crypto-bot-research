// 분석 (builder C, CONTRACT.md section 4, INVENTORY sections 6-7). #/analysis/<view>[?account=<id>]: one view at a time,
// chosen in a scrolling tab row, every view in the same card style (analysis-kit.js viewHead → content cards).
// Views and their routes (all read-only, descriptive):
//   손익비·위험 risk · 실전 준비도 readiness · 충격 테스트 shock      (analysis-risk.js)
//   청산 이유 exits (/api/v4/exits?group=, analysis-exits.js; 조합 시너지 adds analysis-synplus.js's cards)
//   장세 스위치 regime (/api/v4/regime5y + /live, analysis-regime.js; the 36 only, 5-year study + paper trades by regime)
//   코인·장세 지도 map · 코인·시간대 /api/breakdown · 진입 순간 entry · 상황 태그 /api/cards/stats   (analysis-where.js)
//   좋은 자리 vs 보통 levrule · 그림자 비교 shadows · 계좌 겹침 /api/overlap · 조합 시너지 synergy (analysis-rules.js)
//   운 vs 실력 luck (/api/v4/luck, luck-kit.js: every place that tests many things, luck alone vs really passed)
//   손실 크기 규칙 size (/api/v4/size5y + /cell, analysis-size.js; the 36 only, the same 5-year trades under other sizes)
//   GH Coin /api/ghcoin (only while its recorder runs) · 45개 질문 questions (only when filled)
// 건강 점검 moved to 서버·비용 and 알림 기록 to 알림 기록 (builder E). A {pending: true} answer shows the shimmer and asks
// again after 3 s (the server computes heavy views in the background). The last view is remembered (local).
// 묶음 (gapA, the 20:09 promise): 기존 36 / 딥시크 44 / 5분봉 above the view. Views marked `groups` ask the server for
// that group (?group=, paperbot/dash/analysis.py: each against its own coin flips; DeepSeek with no money); views marked
// `core` are computed for the 36 only and, under another group, say so with one tap back to 기존 36 (never the 36's
// numbers under another group's name); views marked `any` are not about a group (the switch is hidden there). No coin-
// flip group (they are the baseline line inside each view) and no mixed 전체 (different exits, different flips).
import {h, put, ui, motion, local, fmt} from "../core/pb.js";
import {tradeProgress, runDays, waitCard} from "./analysis-kit.js";
import * as R from "./analysis-risk.js";
import * as W from "./analysis-where.js";
import * as X from "./analysis-rules.js";
import * as SZ from "./analysis-size.js";
import * as C from "./analysis-costs.js";
import * as E from "./analysis-exits.js";
import * as RG from "./analysis-regime.js";
import * as L from "./luck-kit.js";

const VIEWS = [
  {id: "risk", label: "손익비·위험", path: "/api/analysis/risk", render: R.risk, groups: "groups", desc: "이길 때와 질 때의 크기, 낙폭과 파산 위험"},
  {id: "exits", label: "청산 이유", path: "/api/v4/exits", render: E.exits, groups: "groups", desc: "청산 이유(손절·익절 잠금 단계·시간 청산·강제청산)별 성적, 끝나기 전에 얼마나 밀렸나"},
  {id: "map", label: "코인·장세 지도", path: "/api/analysis/map", render: W.map, groups: "groups", desc: "코인·장세·시간대·방향·봉별로 어디서 벌고 잃었나"},
  {id: "regime", label: "장세 스위치", path: "/api/v4/regime5y", render: RG.regime, groups: "core", desc: "잃는 게 '맞지 않는 장' 탓일까? 5년 자료로 장세별 성적과, 맞는 장에서만 켜는 스위치를 손대지 않은 기간에서 확인"},
  {id: "sessions", label: "코인·시간대", path: "/api/breakdown", render: W.sessions, groups: "groups", gpath: "/api/analysis/breakdown", desc: "코인별, 평일·주말 × 시간대, 펀딩·미국장 개장·지표 발표 시간"},
  {id: "entry", label: "진입 순간", path: "/api/analysis/entry", render: W.entry, groups: "groups", desc: "들어가는 봉의 모습별 성적"},
  {id: "tags", label: "상황 태그", path: "/api/cards/stats?days=30", render: W.tags, groups: "any", desc: "손실과 이익에 붙은 상황 표시 (경제지표 발표 전후 등)"},
  {id: "levrule", label: "좋은 자리 vs 보통", path: "/api/analysis/levrule", render: X.levrule, groups: "core", desc: "좋은 자리에서 배수를 높인 레버리지 규칙 B의 중간 숫자"},
  {id: "size", label: "손실 크기 규칙", path: "/api/v4/size5y", render: SZ.size, groups: "core", fixed: true, desc: "같은 5년 거래에 크기만 바꾸면: 손절 한 번 = 잔고 0.5·1·2%, 배수 절반, 지금 v4"},
  {id: "shadows", label: "그림자 비교", path: "/api/analysis/shadows", render: X.shadows, groups: "core", desc: "같은 거래를 손절·잠금·익절·레버리지 하나만 바꿔 다시 계산"},
  {id: "overlap", label: "계좌 겹침", path: "/api/overlap?days=7", render: X.overlap, groups: "core", desc: "같이 움직이는 계좌와 한 코인에 몰린 순간"},
  {id: "synergy", label: "조합 시너지", path: "/api/analysis/synergy", render: X.synergy, groups: "core", desc: "매매법 여러 개를 같이 돌렸다면"},
  {id: "shock", label: "충격 테스트", path: "/api/analysis/shock", render: R.shock, groups: "core", desc: "가격이 한 번에 크게 움직이면 지금 포지션은"},
  {id: "ready", label: "실전 준비도", path: "/api/analysis/readiness", render: R.ready, groups: "core", desc: "실거래 전에 정한 조건 8개를 계좌마다"},
  {id: "luck", label: "운 vs 실력", path: "/api/v4/luck", render: L.luckView, groups: "any", desc: "여러 개를 한꺼번에 시험하는 곳마다: 운으로 통과할 수와 실제로 통과한 수"},
  {id: "costs", label: "비용", path: "/api/v4/costs", render: C.costs, groups: "any", desc: "수수료·펀딩이 깎아 먹는 몫과 실제 호가였다면 (추정)"},
  {id: "ghcoin", label: "GH Coin", path: "/api/ghcoin", render: X.ghcoin, feature: "ghcoin", groups: "any", desc: "GH Coin 타점 기록 (따로 도는 기록기)"},
  {id: "questions", label: "45개 질문", path: "/api/analysis/questions", render: X.questions, feature: "questions", groups: "any", desc: "질문마다 답이 있는지"},
];
// the server's group keys (paperbot/groups.py), labels as on 격자 (grid.js) and 홈's group cards
const GROUPS = [
  {id: "core", label: "기존 36", title: "잠긴 매매법 36개 × 15분·30분·1시간·4시간"},
  {id: "ds200", label: "딥시크 44", title: "딥시크 44개 정의 · 거래 수와 비율만 (돈 숫자 없음)"},
  {id: "reel", label: "5분봉", title: "릴스 5분 단타 1개 · 비교: 5분봉 동전 봇 3개"},
];
const okGroup = (g) => (GROUPS.some((x) => x.id === g) ? g : "core");
const GROUP_N = {core: "기존 36", ds200: "딥시크", reel: "릴스"};

/**
 * fill-strat: the real thresholds of the views that wait for trades, and how far the accounts are now (board
 * trades), as filling bars: 손익비·위험 (파산 확률 흉내: 계좌마다 거래 N건), 계좌 겹침 (계좌마다 거래 N건 + 같이 쌓인 기록
 * N일), 조합 시너지 (36 계좌 평균 N건). Null once every bar is full (the view then stands on its own numbers).
 * Thresholds come from the server's answer (d.drawdown.min_trades, d.rules.min_trades / min_days, d.min_trades),
 * with the server's constants as fallbacks (agents/survival.MIN_TRADES 20, overlap 20 / 7, SYNERGY_MIN_TRADES 5).
 */
export function waitBars(id, d, group, board, now = Date.now()) {
  d = d || {};
  const gk = GROUP_N[group] || "기존 36";
  const perAcct = (need, why) => {
    const p = tradeProgress(board, group, need);
    if (!p.total) return null;
    return {label: `${why} · 계좌마다 거래 ${fmt.int(need)}건 필요`, share: p.share, full: p.done >= p.total,
      words: `지금 가장 많은 계좌 ${fmt.int(p.max)}건 · ${fmt.int(need)}건 넘은 ${gk} 계좌 ${fmt.int(p.done)}/${fmt.int(p.total)}`};
  };
  let bars = [];
  if (id === "risk") {
    bars = [perAcct((d.drawdown && d.drawdown.min_trades) || 20, "파산 확률 흉내")];
  } else if (id === "overlap") {
    const r = d.rules || {}, days = runDays(board, "core", now), need = r.min_days || 7;
    bars = [perAcct(r.min_trades || 20, "계좌끼리 비교"),
      days == null ? null : {label: `같이 쌓인 기록 ${fmt.int(need)}일 필요`, share: Math.min(1, days / need), full: days >= need,
        words: `지금 ${fmt.num(days, 1)}일째`}];
  } else if (id === "synergy") {
    const need = d.min_trades || 5, p = tradeProgress(board, "core", need);
    if (p.total) bars = [{label: `조합 점수 · 36 계좌 평균 거래 ${fmt.int(need)}건 필요`, share: Math.min(1, p.avg / need), full: !d.waiting && p.avg >= need,
      words: `지금 계좌당 평균 ${fmt.num(p.avg, 1)}건 · 가장 많은 계좌 ${fmt.int(p.max)}건`}];
  }
  bars = bars.filter(Boolean);
  return bars.length && bars.some((b) => !b.full) ? bars : null;
}
const FRESH_MS = 5 * 60 * 1000;

let current = null;

export async function mount(el, ctx) {
  ctx.setTitle("분석");
  const st = {tab: null, cache: {}, gen: 0, disposers: [], summary: null, ready: false, group: "core"};
  const shown = () => VIEWS.filter((v) => !v.feature || ctx.features[v.feature]);
  const pick = (id) => (shown().some((v) => v.id === id) ? id : "risk");
  st.tab = pick(ctx.params.arg || local.get("an-tab", "risk"));
  st.group = okGroup(((ctx.params && ctx.params.query) || {}).group || local.get("an-group", "core"));
  local.set("an-group", st.group);   // a ?group= link is remembered like a tap (a later tab change drops it from the address)

  const segSlot = h("div", {class: "an-tabs"});
  const groupSeg = ui.seg(GROUPS.map((g) => ({id: g.id, label: g.label, title: g.title})), st.group, (id) => setGroup(id), {label: "묶음 고르기"});
  const groupRow = h("div", {class: "an-gsel"}, h("span", {class: "an-glabel"}, "묶음"), groupSeg);
  const desc = h("p", {class: "an-desc"});
  const body = h("div", {class: "stack an-body"}, motion.shimmer(5, true));     // 불러오는 중 (never a blank page)
  el.append(ui.screenHead("분석", "매매법 계좌의 거래를 여러 방향으로 나눠 봅니다 · 설명용, 판정 아님"), segSlot, groupRow, desc, body);

  function setGroup(id) {
    id = okGroup(id);
    if (id === st.group) return;
    st.group = id;
    local.set("an-group", id);
    groupSeg.set(id);
    // an old ?group= in the address would bring the old group back on reload: drop it (the choice is remembered)
    const q = (ctx.params && ctx.params.query) || {};
    if (q.group != null) {
      const rest = {...q};
      delete rest.group;
      try { window.history.replaceState(null, "", ctx.href("analysis", st.tab, rest)); } catch { /* keep the hash */ }
      ctx.params = {...ctx.params, query: rest};
    }
    load(false);
  }

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
    let path = v.id === "shadows" && q.account ? `${v.path}?account=${encodeURIComponent(q.account)}` : v.path;
    const g = ++st.gen;
    desc.textContent = v.desc;
    groupRow.hidden = v.groups === "any";
    if (v.groups === "core" && st.group !== "core") {   // the 5-minute refresh (force) changes nothing here: no motion
      closeTab(); put(body, coreOnly(v)); if (!force) motion.swap(body); return;
    }
    if (v.groups === "groups" && st.group !== "core") {
      path = v.gpath || path;
      path += `${path.includes("?") ? "&" : "?"}group=${encodeURIComponent(st.group)}`;
    }
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
    const env = {ctx, verdictTs: verdictTs(), ready: st.ready, query: q, group: v.groups === "groups" ? st.group : "core",
      track: (f) => st.disposers.push(f),
      reload: (nq) => { ctx.go("analysis", v.id, nq); }};
    let nodes;
    try { nodes = v.render(d || {}, env); } catch (e) {
      console.error(e);
      nodes = [ui.card({plate: v.label}, h("p", {class: "muted"}, "이 화면을 그리지 못했습니다 (자료 모양이 바뀌었을 수 있음)."))];
    }
    // a view that waits for trades: its real thresholds as filling bars right under its head, and the 5-year past
    // test that can be seen today (한눈 지도 › 5년 시험, 참고)
    const bars = waitBars(v.id, d, env.group, ctx.store.get("board"));
    if (bars && Array.isArray(nodes)) {
      const y5 = env.group === "reel" ? null : h("p", {class: "an-note"}, h("b", null, "5년 과거 시험 · 참고 "),
        "지금 계좌가 쌓이는 동안 과거 5년 시험 결과는 바로 볼 수 있습니다: ",
        h("a", {href: ctx.href("grid", null, {g: env.group === "ds200" ? "ds" : "core"}), onclick: () => local.set(env.group === "ds200" ? "grid-dscolor" : "grid-color", "y5")}, "한눈 지도 › 5년 시험 →"));
      nodes = [nodes[0], waitCard(v.label, bars, y5), ...nodes.slice(1)];
    }
    put(body, ...nodes);
    motion.swap(body);
  }

  // a view computed for the 36 only, while another group is chosen: say so, one tap to 기존 36 or to a view that has it
  function coreOnly(v) {
    const gl = (GROUPS.find((x) => x.id === st.group) || GROUPS[0]).label;
    const has = shown().filter((x) => x.groups === "groups");
    return ui.card({plate: v.label},
      h("p", null, `이 보기는 기존 36만 계산합니다. ${gl} 묶음으로 나눈 숫자는 아직 없습니다.`),
      h("div", {class: "an-gacts"},
        h("button", {class: "btn-y", type: "button", onclick: () => setGroup("core")}, "기존 36으로 보기"),
        has.map((x) => h("button", {class: "btn-line", type: "button", onclick: () => go(x.id, true)}, `${gl} · ${x.label}`))));
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
    const qg = (params.query || {}).group;
    if (qg && okGroup(qg) !== st.group) { st.group = okGroup(qg); local.set("an-group", st.group); groupSeg.set(st.group); }
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
  // (a view of a committed file, fixed: true, is left alone: a refresh would only close what the owner opened)
  ctx.every(FRESH_MS, () => { if (!(VIEWS.find((x) => x.id === st.tab) || {}).fixed) load(true); }, {now: false});
}

export function update(params) { if (current) current(params); }

export function unmount() { current = null; }
