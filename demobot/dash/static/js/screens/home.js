// #/home 요약 (round 5 stage 2: the rule bot's v4 홈 · 요약 layout, home.js / home-live.js / home-shared.js / goal-kit.js):
//   PC: two columns on top (the 판정 head card | the 12/31 goal with its stage strip and the closest line), the green LED
//   bar (the sum of every line's wallet from home.json equity_total / pnl_total, its curve, and the six counts on its
//   right), 지금 시장 as one tile per coin (8.5) with the measured entry cost in one line (8.3), 상위 · 하위 in the v4 rank
//   rows (pixel figure, timeframe chip, name, leverage), 종류별 평균 손익 as one tile per kind (a bar per leverage), the
//   ranking leaders against the luck line, and recent switches / recent trades (five each, the rest behind 더 보기; a
//   trade opens its chart). Phone: one column in that order.
// home.json + judge.json, every 60 s (drawn again only when the engine wrote a new one). Read-only; a missing file or
// field shows "준비 중". HONESTY: the LED bar is every line together (coin flips and private ones too), as its caption says.
import {h, s, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
import {isMissing} from "../api.js";
import {LEVS, KIND_KO, shortOf, tfKo, WINDOW_KO, reasonKo, sideKo, STRAT_KO, kindOfId} from "../labels.js";
import {divBar} from "../g4.js";

const STAGES_KO = ["설치", "데모 진행", "우리 기준 통과", "확인 기간", "실전 후보"];
const SHOW = 5;                       // rows before 더 보기

/** An account-like object for the pixel figure and the name chip, from a row that only carries id and name. */
function acctOf(id, name) {
  const x = String(id || "");
  const tf = /-(15m|30m)$/.exec(x), sh = /(?:^|-)(S2|N02|N04)(?:-|$)/.exec(x);
  return {id: x, name: name || x, kind: kindOfId(x), tf: tf ? tf[1] : null, short: sh ? sh[1] : null};
}
const nameEl = (a, size = 18) => [K4.acctFig(a, size), K4.acctName(a)];
const levTag = (L) => (L ? h("span", {class: "dl-levtag", dataset: {lev: L}}, fmt.lev(L)) : null);

export async function mount(el, ctx) {
  ctx.setTitle("요약");
  const verdict = h("section", {class: "card hero dl-verdict s2a-hero", "aria-label": "판정"});
  const goal = h("section", {class: "card s2a-goal", "aria-label": "12/31 목표"});
  const led = ledBar();
  const market = h("div", {class: "s2a-mktwrap"});
  const tb = h("div", {class: "k4-tb"});
  const kinds = h("div", {class: "s2a-kinds"});
  const leaders = h("div"), switches = h("div"), trades = h("div");
  el.append(
    ui.screenHead("요약", "데모 랩 한눈에 보기"),
    h("div", {class: "s2a-wrap s2a-top"}, verdict, goal),
    led,
    ui.card({plate: "지금 시장", sub: "코인마다 추세와 변동 · 실제 진입 비용", acts: h("a", {class: "btn-line", href: "#/regime"}, "시장 국면")}, market),
    ui.card({plate: "상위 · 하위", sub: "계좌 × 배수 손익 (시작 $1,000 대비)", acts: h("a", {class: "btn-line", href: "#/accounts"}, "순위표 →")}, tb),
    h("section", {class: "k4-sec", "aria-label": "종류별 평균 손익"}, K4.secRow("종류별 평균 손익", "배수마다 계좌 평균 (시작 $1,000 대비)"), kinds),
    ui.card({plate: "설정 순위 1등", sub: "매매법 × 봉마다 주변 평균 1등과 운 기준선",
      acts: h("a", {class: "btn-line", href: "#/rank"}, "설정 순위 보기")}, leaders),
    h("div", {class: "s2a-wrap"},
      ui.card({plate: "최근 교체", sub: "자동 교체·친구 규칙 계좌가 바꾼 설정"}, switches),
      ui.card({plate: "최근 거래", sub: "모든 계좌 · 코인을 누르면 거래 차트", acts: h("a", {class: "btn-line", href: "#/trades"}, "거래 기록")}, trades)),
    h("p", {class: "assume"}, "모의 계좌입니다. 바이낸스 실제 시세로 계산하고 수수료·슬리피지·펀딩을 뺍니다. 주문은 넣지 않습니다."));

  let seen = null;
  async function load() {
    let home, judge;
    try {
      [home, judge] = await Promise.all([ctx.api("/api/home"), ctx.api("/api/judge")]);
    } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!seen) put(verdict, ui.errorBox(e, load));
      return;
    }
    const key = `${home && home.generated_ms}|${judge && judge.generated_ms}`;
    if (key === seen) return;
    seen = key;
    paintVerdict(home, judge);
    if (isMissing(home)) {
      put(goal, h("div", {class: "card-h"}, ui.plate("12/31 목표")), ui.none("준비 중"));
      led.update(null);
      for (const box of [market, tb, kinds, leaders, switches, trades]) put(box, ui.empty("준비 중"));
      return;
    }
    paintGoal(home.goal);
    led.update(home);
    paintMarket(home.regime_now, home.costs_now);
    paintTopBottom(home.best, home.worst);
    paintKinds(home.by_kind);
    put(leaders, leaderTable(home.leaders, ctx));
    put(switches, more(home.recent_switches, switchRow, "아직 교체가 없습니다"));
    put(trades, more(home.recent_trades, (t) => tradeRow(t, ctx), "아직 거래가 없습니다"));
  }

  function paintVerdict(home, judge) {
    const t = home && !isMissing(home) && home.totals ? home.totals : {};
    const passed = Number(t.passed || 0), cands = Number(t.candidates || 0), conf = Number(t.confirming || 0);
    const text = judge && !isMissing(judge) && judge.verdict_ko ? judge.verdict_ko : "판정 자료 준비 중";
    const big = cands > 0
      ? h("p", {class: "dl-vbig ok"}, "실전 후보 ", h("em", null, `${fmt.int(cands)}줄`))
      : conf > 0 ? h("p", {class: "dl-vbig warn"}, "확인 기간 ", h("em", null, `${fmt.int(conf)}줄`))
        : passed > 0 ? h("p", {class: "dl-vbig ok"}, "통과 ", h("em", null, `${fmt.int(passed)}줄`))
          : h("p", {class: "dl-vbig no"}, "실전 금지");
    put(verdict,
      h("div", {class: "s2a-hrow"}, ui.plate("판정"), h("span", {class: "muted s2a-small"}, "두 가지 기준으로 매일 확인")),
      big,
      h("p", {class: "dl-vline"}, text),
      h("p", {class: "note"}, cands > 0
        ? "실전 후보는 통과 뒤 4주 확인 기간까지 넘은 줄입니다. 그래도 실제 돈은 두 분이 정하기 전까지 쓰지 않습니다."
        : conf > 0 ? "기준을 넘은 줄이 4주 확인 기간을 지나는 중입니다. 운으로 넘었을 수 있어서, 끝날 때까지 실전에 쓰지 않습니다."
          : passed > 0 ? "통과한 줄이 있어도 실전은 두 분이 정합니다. 판정 화면에서 무엇이 통과했는지 보세요."
            : "아직 어떤 계좌·배수도 기준을 넘지 못했습니다. 넘기 전까지는 실전에 쓰지 않습니다."),
      h("div", {class: "row wrap"}, h("a", {class: "btn-y", href: "#/judge"}, "판정 자세히"),
        h("a", {class: "btn-line", href: "#/path"}, "졸업 길"), h("a", {class: "btn-line", href: "#/howto"}, "기준이 뭔가요?")));
  }

  function paintGoal(g) {
    if (!g) { put(goal, h("div", {class: "card-h"}, ui.plate("12/31 목표")), ui.none("준비 중")); return; }
    const stages = Array.isArray(g.stages_ko) && g.stages_ko.length ? g.stages_ko : STAGES_KO;
    const at = Number.isInteger(Number(g.stage)) ? Number(g.stage) : -1;
    const c = g.closest;
    const a = c ? acctOf(c.id, c.name) : null;
    const missingKo = c && Array.isArray(c.missing_ko) ? c.missing_ko : [];
    put(goal,
      h("div", {class: "s2a-hrow"}, ui.plate("12/31 목표"),
        g.days_left != null ? h("span", {class: "s2a-dcount", title: g.deadline_ms ? `${fmt.date(g.deadline_ms - 1)}까지` : null},
          h("b", null, `D-${fmt.int(g.days_left)}`), " 남음") : null),
      h("p", {class: "s2a-goalline"}, g.line_ko || "—", g.deadline_ms ? h("small", {class: "muted"}, ` · ${fmt.date(g.deadline_ms - 1)}까지`) : null),
      h("ol", {class: "steps dl-steps s2a-steps", "aria-label": "단계"}, stages.map((x, i) => h("li", {class: i < at ? "done" : i === at ? "now" : "",
        "aria-current": i === at ? "step" : null}, h("span", {class: "s2a-sn"}, String(i + 1).padStart(2, "0")), x))),
      c ? h("div", {class: "s2a-close"},
        h("div", {class: "s2a-closeh"}, h("span", {class: "k4-k"}, "가장 가까운 줄"),
          h("a", {class: "s2a-nm", href: ctx.href("account", c.id), title: c.id}, nameEl(a, 20)), levTag(c.L), h("span", {class: "grow"}),
          ui.pill(`${fmt.int(c.of)}개 중 ${fmt.int(c.ok)}개 통과`, Number(c.ok) >= Number(c.of) ? "good" : "thin")),
        ui.progress(Number(c.of) ? Number(c.ok) / Number(c.of) : 0, null),
        missingKo.length ? h("ul", {class: "s2a-miss"}, missingKo.map((x) => h("li", null, h("span", {class: "down", "aria-hidden": "true"}, "✗ "), x)))
          : h("p", {class: "note"}, "모든 항목을 넘었습니다.")) : null);
  }

  function paintMarket(rows, costs) {
    const list = Array.isArray(rows) ? rows : [];
    const cost = costs && costs.median_entry_bps != null
      ? h("a", {class: "s2a-costline", href: "#/costs"}, h("b", null, "실제 진입 비용 "), h("span", {class: "num"}, `중간값 ${fmt.num(costs.median_entry_bps, 2)}bp`),
        h("span", {class: "muted"}, ` · 봇의 가정 ${fmt.num(costs.assumed_bps ?? 2, 0)}bp · `), h("span", {class: "s2a-go"}, "실제 비용 →"))
      : h("p", {class: "s2a-costline muted"}, "실제 진입 비용: 기록 없음");
    put(market, list.length ? h("div", {class: "s2a-mkt", style: {"--n": String(list.length)}}, list.map((r) => h("a", {class: "s2a-coin", href: "#/regime",
      title: `${fmt.coin(r.coin)} · ${r.since_ms ? `${fmt.kst(r.since_ms)}부터` : "시작 시각 기록 없음"}`},
    h("b", {class: "s2a-cn"}, fmt.coin(r.coin)), ui.regimeChips(r.trend, r.vol)))) : ui.none("준비 중"), cost);
  }

  function paintTopBottom(best, worst) {
    const col = (label, sub, rows) => h("div", {class: "k4-tbcol"}, h("div", {class: "k4-tbh"}, h("b", null, label), h("span", null, sub)),
      rows && rows.length ? h("div", {role: "list"}, rows.map((r, i) => rankRow(r, i, ctx))) : ui.empty("아직 없습니다"));
    put(tb, col("잘 되는 줄", "손익 상위 5", best), col("안 되는 줄", "손익 하위 5", worst));
  }

  function paintKinds(rows) {
    if (!rows || !rows.length) { put(kinds, ui.empty("아직 없습니다")); return; }
    const vals = rows.flatMap((r) => LEVS.map((L) => Number((r.mean_pnl_pct || {})[String(L)]))).filter(Number.isFinite);
    const max = Math.max(5, ...vals.map(Math.abs));
    put(kinds, rows.map((r) => h("div", {class: "s2a-kt", dataset: {kind: r.kind}},
      h("div", {class: "s2a-kth"}, h("i", {class: "k4-sw", "aria-hidden": "true"}), h("b", null, KIND_KO[r.kind] || r.kind_ko || r.kind),
        r.accounts ? h("span", {class: "muted"}, `${fmt.int(r.accounts)}개`) : null),
      LEVS.map((L) => {
        const v = r.mean_pnl_pct ? r.mean_pnl_pct[String(L)] : null;
        const t = fmt.pct(v, true);
        return h("div", {class: "s2a-ktr"}, levTag(L), divBar(v, max, `${L}배 평균 ${t}`, true), h("b", {class: ["num", fmt.tone(v, t)]}, t));
      }))));
  }

  await load();
  ctx.every(60000, load);
}

/** The green LED bar (v4 ui.ledBar): the sum of every line's wallet, its change from the start, its curve, six counts. */
function ledBar() {
  const total = h("b", {class: "num"}, "—"), pctEl = h("span", {class: "led-box num"}), absEl = h("span", {class: "num"});
  const live = h("span", {class: "led-live off"}, "■ 준비 중");
  const mid = h("div", {class: "led-m"});
  const right = h("div", {class: "led-r"});
  const cap = h("p", {class: "led-cap"});
  const el = h("section", {class: "ledbar s2a-led", "aria-label": "모든 줄 합계 잔고"},
    h("div", null, h("div", {class: "led-k"}, h("span", {class: "t"}, "모든 줄 합계 잔고"), live),
      h("div", {class: "led-n"}, total, h("span", null, "USD")), h("div", {class: "led-chg"}, pctEl, absEl)),
    mid, right, cap);
  const cells = new Map();
  const cell = (k, title) => {
    if (!cells.has(k)) {
      const v = h("b", {class: "num"}, "—");
      const w = h("div", {title}, h("span", null, k), v);
      cells.set(k, v); right.append(w);
    }
    return cells.get(k);
  };
  el.update = (home) => {
    const eq = home && Array.isArray(home.equity_total) ? home.equity_total : [];
    const pn = home && Array.isArray(home.pnl_total) ? home.pnl_total : [];
    const lastEq = eq.length ? Number(eq[eq.length - 1][1]) : null, lastPn = pn.length ? Number(pn[pn.length - 1][1]) : null;
    const init = lastEq != null && lastPn != null ? lastEq - lastPn : null;
    K4.countTo(total, lastEq, {format: (v) => fmt.num(v, 2), flash: true});
    pctEl.hidden = init == null || !(init > 0);
    if (init > 0) K4.countTo(pctEl, lastPn / init * 100, {format: K4.pctFmt(2), tone: true});
    K4.countTo(absEl, lastPn, {format: (v) => fmt.money(v, true), tone: true});
    live.className = ["led-live", home && home.phase === "live" ? "" : "off"].filter(Boolean).join(" ");
    live.textContent = !home ? "■ 준비 중" : home.phase === "live" ? "■ 실시간" : home.phase === "warm" ? "■ 과거 채우는 중" : "■ 멈춤";
    const vs = eq.map((p) => Number(p[1])).filter(Number.isFinite);
    const step = Math.max(1, Math.floor(vs.length / 160));
    put(mid, vs.length > 1 ? curve(vs.filter((_, i) => i % step === 0 || i === vs.length - 1), init) : h("div", {class: "led-stats"}, h("span", null, "잔고 곡선 준비 중")),
      h("div", {class: "led-stats"}, h("span", null, home && home.totals ? `계좌 ${fmt.int(home.totals.accounts)}개 × 배수 4줄` : "계좌 —"),
        h("span", null, "줄마다 $1,000에서 시작")));
    const t = (home && home.totals) || {};
    const opt = (v) => (v == null ? "준비 중" : fmt.int(v));
    cell("실시간", home && home.phase === "warm" ? "과거 채우는 중" : "실시간이 돈 날 수").textContent = home && home.live_days != null ? `${fmt.num(home.live_days, 1)}일` : "—";
    cell("열린 포지션", "모든 줄 합계").textContent = home ? fmt.int(t.open_positions) : "—";
    cell("닫힌 거래", "모든 줄 합계").textContent = home ? fmt.int(t.trades) : "—";
    cell("우리 기준 통과", "지금 넘은 줄").textContent = home ? fmt.int(t.passed) : "—";
    cell("확인 기간", "4주 확인 중인 줄").textContent = home ? opt(t.confirming) : "—";
    cell("실전 후보", "확인 기간까지 넘은 줄").textContent = home ? opt(t.candidates) : "—";
    cap.textContent = "모든 줄 = 동전 던지기·비공개 매매법까지 모든 계좌의 배수 4줄 · 지갑 + 열린 포지션 평가금 · 수수료·슬리피지·펀딩 뺀 뒤 · 가상 돈 (주문 없음)";
  };
  return el;
}

/** The LED bar's curve: a thin green line over a dashed start line (fills its box's width). */
function curve(vs, base) {
  const w = 300, hh = 56, pad = 3;
  let lo = Math.min(...vs), hi = Math.max(...vs);
  if (base != null && Number.isFinite(base)) { lo = Math.min(lo, base); hi = Math.max(hi, base); }
  const span = hi - lo || 1;
  const X = (i) => pad + (w - 2 * pad) * i / Math.max(1, vs.length - 1);
  const Y = (v) => hh - pad - (hh - 2 * pad) * (v - lo) / span;
  const d = vs.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join("");
  const svg = s("svg", {viewBox: `0 0 ${w} ${hh}`, preserveAspectRatio: "none", role: "img", "aria-label": "모든 줄 합계 잔고 흐름 (시작부터 지금까지)"},
    base != null && Number.isFinite(base) ? s("line", {class: "bl", x1: 0, x2: w, y1: Y(base).toFixed(1), y2: Y(base).toFixed(1)}) : null,
    s("path", {class: "ln", d}));
  return K4.drawIn(svg);
}

/** A v4 rank row: rank, the pixel figure, the timeframe chip, the name, the leverage, the P&L %. */
function rankRow(r, i, ctx) {
  const a = acctOf(r.id, r.name);
  const t = fmt.pct(r.pnl_pct, true);
  return h("a", {class: "k4-row", role: "listitem", href: ctx.href("account", r.id), title: `${r.name || r.id} · ${r.id}`},
    h("span", {class: "rk"}, String(i + 1)),
    h("span", {class: "lname"}, nameEl(a, 22)),
    h("span", {class: "ret"}, h("b", {class: ["num", fmt.tone(r.pnl_pct, t)]}, t)),
    h("span", {class: "meta"}, levTag(r.L), h("span", null, "시작 $1,000 대비")));
}

/** The first SHOW rows, the rest behind 더 보기 (kept open across refreshes only until the next new file). */
function more(rows, row, empty) {
  if (!rows || !rows.length) return ui.empty(empty);
  const list = rows.slice(0, 8);
  const first = h("div", {class: "s2a-rows", role: "list"}, list.slice(0, SHOW).map(row));
  if (list.length <= SHOW) return first;
  return [first, ui.disclosure(`${fmt.int(list.length - SHOW)}개 더 보기`, h("div", {class: "s2a-rows", role: "list"}, list.slice(SHOW).map(row)))];
}

function switchRow(d) {
  const id = d.account || d.id;
  const a = acctOf(id, d.name);
  return h("div", {class: "s2a-ev", role: "listitem"},
    h("div", {class: "s2a-evh"}, h("span", {class: "s2a-t num"}, fmt.kst(d.t_ms)),
      id ? h("a", {class: "s2a-nm", href: `#/account/${encodeURIComponent(id)}`, title: id}, nameEl(a, 16)) : null,
      h("span", {class: "grow"}),
      h("span", {class: "pp thin"}, d.coin && d.coin !== "ALL" ? fmt.coin(d.coin) : "전체 코인"), levTag(d.L)),
    h("div", {class: "s2a-evb"}, h("span", {class: "mono muted"}, d.from_ko || "—"), h("span", {class: "s2a-arrow", "aria-hidden": "true"}, " → "),
      h("b", {class: "mono"}, d.to_ko || "—")),
    d.why_ko ? h("div", {class: "s2a-why"}, d.why_ko) : null);
}

function tradeRow(t, ctx) {
  const open = t.status === "open";
  const a = acctOf(t.account, t.name);
  const rT = fmt.r(t.R), pT = fmt.money(t.pnl, true);
  return h("div", {class: "s2a-ev", role: "listitem"},
    h("div", {class: "s2a-evh"}, h("span", {class: "s2a-t num"}, fmt.kst(open ? t.entry_ms : t.exit_ms)),
      t.account ? h("a", {class: "s2a-nm", href: `#/account/${encodeURIComponent(t.account)}`, title: t.account}, nameEl(a, 16)) : null,
      h("span", {class: "grow"}), h("b", {class: ["num", "s2a-pnl", fmt.tone(t.pnl, pT)]}, pT)),
    h("div", {class: "s2a-evb"},
      t.account && t.key ? h("a", {class: "dl-tlink", href: ctx.href("trade", t.account, null, t.key), title: "거래 차트"}, fmt.coin(t.coin))
        : h("b", null, fmt.coin(t.coin)),
      h("span", {class: ["side", Number(t.side) > 0 ? "long" : "short"]}, sideKo(t.side)), levTag(t.L),
      open ? ui.pill("열림", "accent") : h("span", {class: "muted"}, reasonKo(t.reason)),
      h("span", {class: ["num", fmt.tone(t.R, rT)]}, rT)));
}

function leaderTable(rows, ctx) {
  if (!rows || !rows.length) return ui.empty("설정 순위 준비 중");
  return h("div", {class: "stack tight"},
    ui.table([
      {label: "매매법", l: true, get: (r) => h("span", {class: "s2a-strat", title: STRAT_KO[shortOf(r.strategy)]}, h("span", {class: "an-tf"}, tfKo(r.tf)), h("b", null, shortOf(r.strategy)))},
      {label: "1등 설정", l: true, get: (r) => h("span", {class: "mono"}, r.label || "—")},
      {label: "기간", get: (r) => h("span", {class: "pp thin"}, WINDOW_KO[r.window] || r.window || "—")},
      {label: "거래 수", get: (r) => h("span", {class: "num"}, fmt.int(r.n), K4.smallSample(r.n) ? h("small", {class: "muted"}, " 적음") : null)},
      {label: "승률", get: (r) => fmt.ratio(r.win_rate)},
      {label: "평균 R", get: (r) => ui.signed(fmt.r(r.mean_R), fmt.tone(r.mean_R, fmt.r(r.mean_R)))},
      {label: "운 기준선", get: (r) => fmt.r(r.luck95)},
      {label: "운보다", get: (r) => (r.beats_luck == null ? h("span", {class: "muted"}, "—")
        : ui.pill(r.beats_luck ? "✓ 위" : "✗ 아래", r.beats_luck ? "good" : "thin"))},
    ], rows, {cls: "s2a-tbl", onRow: (r) => { location.hash = ctx.href("rank", null,
      {strat: shortOf(r.strategy), tf: r.tf, window: r.window || "26w", exit: r.exit || "house", scope: "ALL"}); }}),
    h("p", {class: "note"}, "운 기준선: 설정 수만큼 무작위 선수를 세웠을 때 그 1등이 낼 법한 평균 R(95%). 이 선 위라야 운이 아닐 가능성이 큽니다. 줄을 누르면 설정 순위로 갑니다."));
}
