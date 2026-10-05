// 매매법 상세 #/strategies/<name> (builder C): the rule in plain words → the chart (indicator lines and lower panes
// when the server has a view, this account's entries and exits, its open position's lines) → the last closed bar's
// conditions → its timeframe accounts and live record → wins vs losses by coin / side / timeframe / session → its
// signal log → the 5-year card → loss cards / loss patterns. Old strat.js, everything kept (INVENTORY section 5).
// HONESTY: money has assume(); the coin-flip comparison is the 참고 pill + refNote (36 only, never ✓/✕); DeepSeek accounts
// get no per-account comparison; small samples say 표본 적음; what the server lacks says 준비 전 / 수집 전.
import {h, put, ui, fmt, motion, local, bars} from "../core/pb.js";
import {DS_DEFS, FAMILY, REEL, STATUS_KO} from "./strategies-defs.js";
import {paramsCard} from "./strategies-params.js";
import {accountsOf, record, splitTrades, nameKo, groupOfStrategy, strategyIndex, TF_ORDER} from "./strategies-calc.js";
import {stratChart, loadView} from "./strategies-chart.js";
import {ruleBody, condBody, profileBody, researchBody, lossCard, tagRows} from "./strategies-panels.js";
import {profileCard} from "./grid-kit.js";
import {reelDuel} from "./reel-duel.js";
import {vs5yCard} from "./vs5y-kit.js";
import {exitsCard} from "./strategies-exits.js";
import {priorPanel} from "./strategies-prior.js";
import {stratShadows} from "./strategies-shadows.js";

const GROUP_PLATE = {core: "기존 36", ds: "딥시크 44", m5: "5분봉"};
const DIMS = [{id: "coin", label: "코인"}, {id: "side", label: "방향"}, {id: "tf", label: "봉"}, {id: "session", label: "시간대"}];

/** A scope that can be closed before the screen leaves (a detail replaced by the list or another strategy). */
function scopeOf(ctx) {
  const stops = [];
  let alive = true;
  return {
    alive: () => alive && ctx.alive(),
    every: (ms, fn, o) => { stops.push(ctx.every(ms, () => alive && fn(), o)); },
    on: (evt, fn) => { stops.push(ctx.on(evt, (d) => alive && fn(d))); },
    track: (fn) => { stops.push(fn); },
    close: () => { alive = false; for (const f of stops.splice(0)) { try { f(); } catch (e) { console.error(e); } } },
  };
}

export function detailView(ctx, st, name) {
  const sc = scopeOf(ctx);
  const q = (ctx.params && ctx.params.query) || {};
  const first = accountsOf(st.board, name);
  const kind = first.length ? first[0].kind : DS_DEFS[name] ? "ds200" : name === REEL.id ? "reel" : "strategy";
  const group = groupOfStrategy(name, kind);
  const meta = (st.list36 || []).find((s) => s.strategy === name) || null;
  const ko = nameKo(name, st.list36);
  const tfsOf = (rows) => (rows.length ? rows.map((a) => a.timeframe) : kind === "reel" ? ["5m"] : ["15m", "30m", "1h", "4h"]);
  let tfs = tfsOf(first);
  const pickTf = (want) => (tfs.includes(want) ? want : tfs.includes("1h") ? "1h" : tfs[0]);
  const v = {tf: pickTf(q.tf || local.get("strat-tf", "1h")), sym: bars.TRADE_SYMS.includes(q.sym) ? q.sym : local.get("strat-sym", "BTCUSDT"),
    markers: local.get("strat-mk", true) !== false, dim: local.get("strat-dim", "coin"), side: local.get("strat-side", "cards"),
    view: undefined, bars: [], sigs: [], trades: {}, profile: undefined, gen: 0};
  if (!bars.TRADE_SYMS.includes(v.sym)) v.sym = "BTCUSDT";
  // the old 매매법 tab's habit (owners 10/06 04:10, v3 photo): opened without a coin, the chart goes where this strategy
  // is IN a position right now (its account on the chosen timeframe first, else the first timeframe that holds one)
  if (!bars.TRADE_SYMS.includes(q.sym)) {
    const held = first.filter((a) => a.position && bars.TRADE_SYMS.includes(a.position.symbol));
    const here = held.find((a) => a.timeframe === v.tf) || (q.tf ? null : held[0]);
    if (here) { v.tf = here.timeframe; v.sym = here.position.symbol; }
  }

  // ---------------------------------------------------------------- head
  const famLine = kind === "ds200" && DS_DEFS[name] ? ui.pill(`${DS_DEFS[name].fam} ${FAMILY[DS_DEFS[name].fam].ko}`, "thin") : null;
  // jump to another strategy of the same group (the old strat.js picker)
  const peers = strategyIndex(st.board, st.list36).filter((x) => x.group === group);
  const jump = peers.length > 1 ? h("select", {class: "select strat-jump", "aria-label": "다른 매매법"},
    peers.map((x) => h("option", {value: x.id}, `${x.fam ? x.fam + " " : ""}${x.ko}`))) : null;
  if (jump) { jump.value = name; jump.addEventListener("change", () => ctx.go("strategies", jump.value)); }
  const head = h("div", {class: "strat-dhead"},
    h("div", {class: "row wrap strat-nav"}, h("a", {class: "btn-line strat-back", href: ctx.href("strategies", null, group !== "core" ? {g: group} : null)}, "← 매매법 목록"), jump),
    h("div", {class: "strat-dtitle"}, h("div", {class: "row wrap"}, ui.plate(GROUP_PLATE[group]), famLine,
      meta && meta.rare ? ui.pill("신호 드묾", "warn") : null),
      h("h1", null, ko), h("span", {class: "muted mono small"}, name)));

  // ---------------------------------------------------------------- cards (phone order by CSS 'order')
  const ruleEl = h("div", {class: "stack tight"});
  const ruleCard = ui.card({plate: "규칙", sub: "쉬운 말로", cls: "strat-o1"}, ruleEl);

  const tfSeg = h("div");
  const symSel = h("select", {class: "select", "aria-label": "코인"}, bars.TRADE_SYMS.map((s) => h("option", {value: s}, fmt.coin(s))));
  symSel.value = v.sym;
  const mkBtn = h("button", {type: "button", class: "btn-line strat-mk", "aria-pressed": String(v.markers)}, "이 계좌 진입·청산");
  const chart = stratChart(ctx);
  sc.track(chart.dispose);
  const liveEl = h("div", {class: "row wrap strat-live", "aria-live": "polite"});
  const chartCard = ui.card({plate: "차트", cls: "strat-o2 strat-chartcard", acts: [symSel, mkBtn]}, liveEl, tfSeg, chart.el);

  const condEl = h("div", {class: "stack tight"}, motion.shimmer(3));
  const condCard = ui.card({plate: "지금 조건", sub: "마지막으로 닫힌 봉", cls: "strat-o3"}, condEl);

  const acctEl = h("div", {class: "stack"});
  const acctCard = ui.card({plate: "봉별 계좌", sub: "실전 모의 기록", cls: "strat-o4"}, acctEl);

  const splitSeg = ui.seg(DIMS, v.dim, (id) => { v.dim = id; local.set("strat-dim", id); renderSplit(true); }, {label: "나눠 볼 기준"});
  const splitEl = h("div", {class: "stack tight"}, motion.shimmer(3));
  const splitCard = ui.card({plate: "이긴 거래 · 진 거래", cls: "strat-o5"}, splitSeg, splitEl);
  const exits = exitsCard(ctx, {kind});   // 어떻게 끝났나: exit reason / leverage / time windows + the 5-year reference

  const sigEl = h("div", {class: "stack tight"}, motion.shimmer(3));
  const sigPg = ui.pager({size: 8, empty: "이 봉에서 최근 신호가 없습니다", row: sigRow});
  const sigCard = ui.card({plate: "신호 기록", cls: "strat-o6"}, sigEl, sigPg.el);

  const profEl = h("div", {class: "stack tight"});
  const profCard = ui.card({plate: "5년 성적", sub: kind === "strategy" ? "과거 시험 · v3 크기 규칙 (모든 신호 50배부터)" : "과거 연구 · 레버리지 없이 가격 %", cls: "strat-o7"}, profEl);
  paramsCard(ctx, name, kind, {after: profCard, scope: sc});      // 숫자(파라미터) 시험 결과, placed after the 5-year card

  const lossSeg = ui.seg([{id: "cards", label: "손실 카드"}, {id: "tags", label: "손실 패턴"}], v.side, (id) => { v.side = id; local.set("strat-side", id); loadLoss(); });
  const lossEl = h("div", {class: "stack tight"});
  const lossPg = ui.pager({size: 4, empty: "최근 30일 손실 거래가 없습니다", row: lossCard});
  const lossCardEl = ui.card({plate: "손실 카드", sub: "최근 30일", cls: "strat-o8"}, kind === "strategy" ? lossSeg : null, lossEl);

  // the top card: the reel's 1:3 card (it against its three 5m coin flips, with the 5-year study), else the profile card
  // (combined return and curve, drawdown, win rate, trades, one cell per timeframe; v4 additions, grid-kit.js)
  const duel = kind === "reel" ? reelDuel(ctx, {wide: true, scope: sc, link: {href: ctx.href("account", "REEL_H1@5m"), text: "계좌 보기 →"}}) : null;
  const prof = duel ? null : profileCard(ctx, name, {cls: "strat-prof"});
  const top = duel || prof.el;

  const left = h("div", {class: "strat-col"}, chartCard, condCard, sigCard);
  // wave 2 ⑨: 5년 시험 vs 지금 vs 동전 봇, per timeframe (vs5y-kit.js), next to the 5-year card
  const vs = vs5yCard(ctx, name, kind, {tf: v.tf, verdictTs: () => verdictTs()});
  const right = h("div", {class: "strat-col"}, ruleCard, acctCard, splitCard, vs.el, exits.el, profCard, lossCardEl);
  { const ss = stratShadows(ctx, name, kind); if (ss) right.append(ss); }     // ana8B: this strategy's shadows + 5-year cells
  const el = h("div", {class: "strat-detail stack"}, head, top, h("div", {class: "strat-grid"}, left, right));

  // ---------------------------------------------------------------- renderers
  function renderRule() { put(ruleEl, ...ruleBody(name, kind, meta, v.view)); }

  function renderTfSeg() {
    put(tfSeg, ui.seg(tfs.map((tf) => ({id: tf, label: fmt.tfKo(tf)})), v.tf, (tf) => { v.tf = tf; local.set("strat-tf", tf); loadChart(); loadSignals(); renderAccounts(); vs.setTf(tf); }, {label: "봉"}));
  }

  function verdictTs() {
    const s = st.summary || {};
    return (s.restart && s.restart.ready && s.restart.verdict_ts) || (s.next_checkpoint && s.next_checkpoint.ts) || null;
  }

  /** 지금 진입 중: one button per open position of this strategy (any timeframe); a tap puts the chart on it. */
  function renderLive(rows) {
    const held = rows.filter((a) => a.position && bars.TRADE_SYMS.includes(a.position.symbol));
    put(liveEl, ...(held.length ? [h("span", {class: "muted small"}, "지금 진입 중")].concat(held.map((a) => {
      const p = a.position, on = a.timeframe === v.tf && p.symbol === v.sym;
      return h("button", {type: "button", class: ["btn-line strat-livebtn", on ? "on" : ""], "aria-pressed": String(on),
        title: "이 포지션의 차트로", onclick: () => setChart(a.timeframe, p.symbol)},
        `● ${fmt.tfKo(a.timeframe)} ${fmt.coin(p.symbol)} ${fmt.sideKo(p.side)} ${fmt.lev(p.leverage)}`, on ? " · 보는 중" : " · 차트 보기");
    })) : [h("span", {class: "muted small"}, "지금 진입한 포지션 없음 · 진입하면 여기서 바로 그 차트로 갑니다")]));
  }
  function setChart(tf, sym) {
    if (tf === v.tf && sym === v.sym) return;
    const tfMoved = tf !== v.tf;
    v.tf = tf; v.sym = sym; symSel.value = sym; local.set("strat-sym", sym); local.set("strat-tf", tf);
    loadChart(); loadSignals(); renderAccounts();
    if (tfMoved) vs.setTf(tf);
  }

  const recNums = {};
  function renderAccounts() {
    const rows = accountsOf(st.board, name);
    renderLive(rows);
    const dsK = kind === "ds200";
    const init = (st.board && st.board.initial) || 5000;
    const gs = st.gs;
    const tiles = rows.map((a) => {
      const w = a.wallet == null ? init : a.wallet;
      let vs = null;
      if (a.kind === "strategy" && gs && gs.flipMedByTf[a.timeframe] != null) {
        const m = gs.flipMedByTf[a.timeframe];
        vs = ui.pill(w > m ? "동전 봇 중앙값 위" : w < m ? "동전 봇 중앙값 아래" : "동전 봇 중앙값과 같음", "ref", "같은 봉 동전 봇 3개의 잔고 중앙값과 비교 (참고, 판정 아님)");
      }
      const p = a.position;
      return h("a", {class: ["strat-tile", a.timeframe === v.tf ? "sel" : ""], href: ctx.href("account", a.account_id), title: a.account_id},
        h("span", {class: "k"}, fmt.tfKo(a.timeframe)),
        // DeepSeek: counts only here (owners' D11: its money only on the DeepSeek group screen)
        dsK ? h("b", {class: "num"}, `거래 ${fmt.int(a.trades || 0)}`) : h("b", {class: ["num", fmt.tone(w - init)]}, fmt.money(w)),
        dsK ? null : h("span", {class: ["num small", fmt.tone(w - init)]}, fmt.pct(w / init - 1)),
        h("span", {class: "s"}, a.trades ? `${fmt.int(a.wins)}승 ${fmt.int(a.losses)}패` : "거래 없음", " ", ui.smallSample(a.trades || 0)),
        a.bust ? ui.pill("파산", "bad") : p ? h("span", {class: "s accent"}, `● ${fmt.coin(p.symbol)} ${fmt.sideKo(p.side)} ${fmt.lev(p.leverage)}`) : null,
        vs);
    });
    const r = record(rows, init);
    const lr = v.profile && v.profile.live_risk && !v.profile.live_risk.error ? v.profile.live_risk : null;
    const num = (key, val, o) => { if (!recNums[key]) recNums[key] = ui.liveNum(val, o); else recNums[key].update(val); return recNums[key]; };
    const stats = dsK ? h("div", {class: "strat-stats"},
      ui.stat("거래", r.trades ? `${fmt.int(r.wins)}승 ${fmt.int(r.losses)}패` : "거래 없음", r.rate == null ? "—" : `승률 ${fmt.pct(r.rate, 0, false)}`),
      ui.stat("파산", `${fmt.int(rows.filter((a) => a.bust).length)}개`, `봉 계좌 ${fmt.int(r.n)}개 중`),
      ui.stat("손익", "딥시크 화면에서", h("a", {href: ctx.href("board", null, {g: "ds"})}, "딥시크 순위표 →")))
    : h("div", {class: "strat-stats"},
      ui.stat("거래", r.trades ? `${fmt.int(r.wins)}승 ${fmt.int(r.losses)}패` : "거래 없음", r.rate == null ? "—" : `승률 ${fmt.pct(r.rate, 0, false)}`),
      ui.stat("손익 합계", num("pnl", r.pnl, {dec: 2, sign: true, tone: true}), `봉 계좌 ${fmt.int(r.n)}개 합`),
      ui.stat("평균 이익 · 손실", h("b", {class: "num"}, h("span", {class: "up"}, fmt.money(r.avgW, true)), " · ", h("span", {class: "down"}, fmt.money(r.avgL, true))),
        r.ratio == null ? "손익비 —" : `손익비 ${fmt.num(r.ratio, 2)}`),
      ui.stat("본전 승률", r.be == null ? "—" : fmt.pct(r.be, 0, false), "이 평균이면 이만큼 이겨야 본전"),
      lr && lr.max_dd_pct != null ? ui.stat("최대 낙폭", fmt.pct(-lr.max_dd_pct, 1), lr.max_dd_at ? `바닥 ${lr.max_dd_at}` : "봉 계좌 합친 자금") : null,
      lr && lr.p_bust != null ? ui.stat("파산 확률", fmt.pct(lr.p_bust, 1, false), "지난 거래로 30일 흉내 · 설명용") : null);
    const list = rows.length ? h("div", {class: "strat-tiles"}, tiles) : ui.empty("이 매매법의 계좌가 아직 없습니다");
    put(acctEl, list, stats, ui.smallSample(r.trades) ? h("p", {class: "muted small"}, ui.smallSample(r.trades), " 거래가 30건 미만이라 숫자가 우연일 수 있습니다.") : null,
      kind === "strategy" ? ui.refNote(verdictTs()) : kind === "ds200" ? h("p", {class: "refnote"}, h("b", null, "참고"), " · 딥시크 계좌는 계좌마다 동전 봇과 비교하지 않습니다. 묶음 숫자는 순위표에 있습니다.") : null,
      dsK ? null : ui.assume(null, "잔고·손익은 닫힌 거래 기준"));
  }

  function renderSplit(animate) {
    const all = [];
    for (const [tf, d] of Object.entries(v.trades)) for (const t of d || []) all.push({...t, _tf: tf});
    const sp = splitTrades(all);
    const rows = sp[v.dim] || [];
    if (!sp.n) { put(splitEl, ui.empty("아직 끝난 거래가 없습니다")); return; }
    put(splitEl, 
      h("p", {class: "muted small"}, `끝난 거래 ${fmt.int(sp.n)}건 (봉 계좌마다 최근 500건까지). 10건 미만 칸은 표본 적음: 결론 없이 참고만.`),
      h("div", {class: "strat-split", role: "list"}, rows.map((c) => h("div", {class: "strat-srow", role: "listitem"},
        h("span", {class: "nm2"}, c.ko), h("span", {class: "wl-bar", title: `이긴 비율 ${fmt.pct(c.rate, 0, false)}`}, h("i", {style: {"--w": Math.round((c.rate || 0) * 100) + "%"}})),
        h("span", {class: "num small"}, `${fmt.int(c.wins)}승 ${fmt.int(c.losses)}패`),
        kind === "ds200" ? null : h("b", {class: ["num", fmt.tone(c.pnl)]}, fmt.money(c.pnl, true)), h("span", {class: "strat-sp"}, ui.smallSample(c.n, 10))))),
      kind === "ds200" ? null : ui.assume());
    if (animate) motion.swap(splitEl);
  }

  function sigRow(r) {
    return h("div", {class: "lrow strat-sig", role: "listitem"},
      h("span", {class: "rk"}, fmt.kst(r.bar_close)),
      h("span", {class: "lname"}, fmt.coin(r.symbol), " ", ui.sideTag(r.side)),
      h("span", {class: ["ret small", r.status === "SUBMITTED" ? "accent" : "muted"]}, STATUS_KO[r.status] || String(r.status || "")),
      h("span", {class: "meta"}, r.ref_price != null ? h("span", null, `기준가 ${fmt.price(r.ref_price)}`) : null,
        r.delay_ms != null ? h("span", null, `봉 마감 뒤 ${fmt.dur(r.delay_ms / 1000)}`) : null));
  }

  // ---------------------------------------------------------------- loaders
  async function loadChart() {
    const g = ++v.gen;
    renderTfSeg();
    put(condEl, motion.shimmer(3));
    const [bs, view] = await Promise.all([
      ctx.api(`/api/candles?symbol=${v.sym}&interval=${v.tf}&limit=500`).catch(() => []),
      loadView(ctx, name, v.tf, v.sym, st.list36, kind).catch(() => null),
    ]);
    if (!sc.alive() || g !== v.gen) return;
    const firstView = v.view === undefined;
    v.view = view; v.bars = Array.isArray(bs) ? bs : [];
    if (firstView || kind === "strategy") renderRule();
    await drawChart();
    put(condEl, ...condBody(view, v.sigs, v.tf));
  }
  async function drawChart() {
    const acct = accountsOf(st.board, name).find((a) => a.timeframe === v.tf);
    await chart.draw({name, ko, tf: v.tf, sym: v.sym, bars: v.bars, view: v.view, trades: v.trades[v.tf] || [],
      position: acct && acct.position, markers: v.markers});
  }
  async function loadTrades(only) {
    const rows = accountsOf(st.board, name).filter((a) => !only || only.has(a.account_id));
    const got = await Promise.all(rows.map((a) => ctx.api(`/api/account/${encodeURIComponent(a.account_id)}`).then((d) => [a.timeframe, d.trades || []]).catch(() => [a.timeframe, null])));
    if (!sc.alive()) return;
    for (const [tf, tr] of got) if (tr) v.trades[tf] = tr;
    renderSplit(false);
    exits.trades(v.trades);
    if (v.bars.length) drawChart();
  }
  async function loadSignals() {
    const tf = v.tf;
    put(sigEl, motion.shimmer(2));
    let rows = [];
    try { rows = await ctx.api(`/api/signals?tf=${tf}&limit=1000`); } catch { rows = null; }
    if (!sc.alive() || tf !== v.tf) return;
    if (rows == null) { put(sigEl, ui.errorBox(null, loadSignals)); sigPg.set([]); return; }
    const mine = rows.filter((r) => r.strategy === name);
    v.sigs = mine.filter((r) => r.symbol === v.sym);
    put(sigEl, h("p", {class: "muted small"}, `${fmt.tfKo(tf)}봉 신호 최근 ${fmt.int(rows.length)}개 중 이 매매법 ${fmt.int(mine.length)}개 (모든 코인). 진입 요청 = 봇이 주문을 낸 신호, 늦음 = 시간이 지나 들어가지 않은 신호.`));
    sigPg.set(mine);
    if (v.view) put(condEl, ...condBody(v.view, v.sigs, v.tf));
  }
  async function loadProfile() {
    put(profEl, motion.shimmer(3));
    try { v.profile = await ctx.api(`/api/profile/${encodeURIComponent(name)}`); } catch { v.profile = null; }
    if (!sc.alive()) return;
    // DeepSeek and the reel: their 5-year research card (paperbot/ds_profiles.py), research exits labelled as such
    put(profEl, ...(kind === "strategy" ? profileBody(v.profile, v.tf) : researchBody(v.profile, v.tf)));
    profEl.append(priorPanel(v.profile, kind));   // 이미 해 본 시험 (strategies-prior.js)
    exits.profile(v.profile);
    renderAccounts();
  }
  async function loadLoss() {
    if (kind !== "strategy") {
      // DeepSeek and the reel: whatever /api/cards sends (the reel's cards carry its own exits and stop: lossCard)
      put(lossEl, motion.shimmer(3));
      const cards = await ctx.api(`/api/cards?strategy=${encodeURIComponent(name)}&days=30&limit=40`).catch(() => null);
      if (!sc.alive()) return;
      if (cards && cards.length) {
        put(lossEl, h("p", {class: "muted small"}, `손실 거래 ${fmt.int(cards.length)}건 (최근 30일, 최대 40건).`));
        lossEl.append(lossPg.el); lossPg.el.hidden = false;
        lossPg.set(cards);
      } else {
        put(lossEl, h("p", {class: "muted"}, "최근 30일 손실 카드가 없습니다."));
        lossPg.el.hidden = true;
      }
      return;
    }
    put(lossEl, motion.shimmer(3));
    const n = encodeURIComponent(name), want = v.side;
    if (want === "cards") {
      const cards = await ctx.api(`/api/cards?strategy=${n}&days=30&limit=40`).catch(() => null);
      if (!sc.alive() || v.side !== want) return;
      put(lossEl, cards == null ? ui.errorBox(null, loadLoss) : h("p", {class: "muted small"}, `손실 거래 ${fmt.int(cards.length)}건 (최근 30일, 최대 40건). 손실이 날 때마다 코드가 만든 카드입니다.`));
      lossEl.append(lossPg.el); lossPg.el.hidden = false;
      lossPg.set(cards || []);
    } else {
      const s = await ctx.api(`/api/cards/stats?strategy=${n}&days=30`).catch(() => null);
      if (!sc.alive() || v.side !== want) return;
      lossPg.el.hidden = true;
      put(lossEl, ...(s == null ? [ui.errorBox(null, loadLoss)] : tagRows(s)));
    }
    motion.swap(lossEl);
  }

  // ---------------------------------------------------------------- wiring
  symSel.addEventListener("change", () => { v.sym = symSel.value; local.set("strat-sym", v.sym); loadChart(); loadSignals(); });
  mkBtn.addEventListener("click", () => { v.markers = !v.markers; local.set("strat-mk", v.markers); mkBtn.setAttribute("aria-pressed", String(v.markers)); drawChart(); });

  let tradeT = null;
  sc.on("trades", (rows) => {
    const mine = new Set(accountsOf(st.board, name).map((a) => a.account_id));
    const hit = new Set((rows || []).map((t) => t.account_id).filter((id) => mine.has(id)));
    if (!hit.size) return;
    clearTimeout(tradeT);
    tradeT = setTimeout(() => loadTrades(hit), 1500);
  });
  sc.track(() => clearTimeout(tradeT));
  // the view and the conditions follow the bar closes (the server caches one per closed bar)
  sc.every(60000, () => loadChart(), {now: false});

  renderRule();
  renderTfSeg();
  renderAccounts();
  if (kind === "strategy") lossSeg.set(v.side);

  return {
    el,
    start() {
      loadChart(); loadTrades(); loadSignals(); loadProfile(); loadLoss(); if (duel) duel.set(st.board); else prof.load();
      sc.every(300000, () => vs.load());                // the server keeps it 60 s; a closed trade moves it slowly
    },
    /** New board (or summary): tiles and record update in place; a strategy whose timeframes changed redraws its tabs. */
    refresh() {
      const nt = tfsOf(accountsOf(st.board, name));
      if (nt.join() !== tfs.join()) { tfs = nt; v.tf = pickTf(v.tf); renderTfSeg(); }
      renderAccounts();
      if (duel) duel.set(st.board);
    },
    dispose: () => sc.close(),
    get tfOrder() { return TF_ORDER; },
  };
}
