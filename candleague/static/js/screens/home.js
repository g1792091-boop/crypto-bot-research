// #/home 요약 (the rule bot's v4 홈 layout, as the demo lab's): the next checkpoint and the two pools as they stand now
// (hero card), the schedule road with each pool's trades toward 300, the LED bar of the 38 picks' wallets, the two pools'
// five roles side by side, the picks' 상위 · 하위 5 by mean per trade, and the newest fills. Data: the shared snapshot
// (league.json, app.js) and /api/fills. HONESTY: every number is the snapshot's; a pool's "지금이면" is a preview of the
// pre-registered rule, never the checkpoint's verdict (that is computed on the day).
// The league starts at its install time (owners 10/12): the 일정 card's first step, D+n and "n일째" come from the
// snapshot's start_ms. 설치 뒤 진입만 (js/after.js, the switch under the head) shows only for an older record that
// replayed from 10/01 before its install: the 최근 체결 list, the 자리 비운 사이 trade count and the 후보 열린 포지션 count
// then keep only what was entered after the install (labelled 설치 뒤만); the wallets, the pools, the ranking and the
// checkpoint numbers stay the full record from its start.
import {h, s, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
import * as LK from "../lk.js";
import {serverNow} from "../live.js";
import {ROLES, ROLE_KO, KIND_LONG, sideKo, reasonKo, coinOf, coinShort} from "../labels.js";
import {afterBar, afterFills, afterOn, afterSuffix, afterEmpty, openAfter} from "../after.js";

const SHOW = 5;

export async function mount(el, ctx) {
  try { await ctx.meta(); } catch (e) { /* names fall back to the codes */ }
  const hero = h("section", {class: "card hero dl-verdict s2a-hero", "aria-label": "다음 점검"});
  const goal = h("section", {class: "card s2a-goal", "aria-label": "일정"});
  const led = ledBar();
  const pools = h("div", {class: "s2a-wrap"});
  const tb = h("div", {class: "k4-tb"});
  const fills = h("div");
  const away = h("div");
  const fillsCard = ui.card({plate: "최근 체결", sub: "모든 계좌 · 누르면 그 계좌", acts: h("a", {class: "btn-line", href: "#/fills"}, "체결 기록 →")}, fills);
  el.append(
    ui.screenHead("요약", "후보 리그 한눈에 보기 · 커스텀값 후보 38개 × 계좌 5개"),
    afterBar({cls: "s2a-after"}),
    away,
    h("div", {class: "s2a-wrap s2a-top"}, hero, goal),
    led,
    h("section", {class: "k4-sec", "aria-label": "묶음"}, K4.secRow("묶음", "기존 36 · 딥시크 따로 (점검도 묶음마다 따로)",
      h("a", {class: "btn-line", href: "#/check"}, "점검 진행 →")), pools),
    ui.card({plate: "상위 · 하위", sub: "후보 계좌의 거래 한 번 평균 (지갑 대비)", acts: h("a", {class: "btn-line", href: "#/rank"}, "순위표 →")}, tb),
    fillsCard,
    h("p", {class: "assume"}, "모의 계좌입니다 (가상 돈). 바이낸스 실제 시세로 계산하고 수수료·슬리피지·펀딩을 뺍니다. 주문은 넣지 않습니다."));

  // 자리 비운 사이 state and the 최근 체결 rows (declared before the first snapshot callback runs)
  const prev = local.get("home-seen", null);
  /** The previous visit saw this same record (same start): a record that started over (10/12: from the install time)
   *  is never compared with the one before it. */
  const samePrev = (d) => !!(prev && prev.t && d && prev.start === d.start_ms);
  let awayDone = false, awayTrades = null;
  let fillRows = null, fillsKey = "";
  ctx.onLeague((d) => {
    if (!d.accounts) {
      put(hero, h("div", {class: "s2a-hrow"}, ui.plate("후보 리그")), h("p", {class: "dl-vbig warn"}, "준비 중"),
        h("p", {class: "note"}, "엔진이 시작(설치한 때)부터 계산해 첫 기록을 쓰면 여기에 나옵니다 (몇 분)."));
      return;
    }
    paintAway(d);
    paintHero(d);
    paintGoal(d);
    led.update(d);
    paintPools(d);
    paintTopBottom(d);
    paintFills();                       // the install time may come with this snapshot (설치 뒤 진입만)
  });

  // 자리 비운 사이: what changed since this viewer's previous visit (this device only; nothing is sent anywhere)
  function paintAway(d) {
    const ix = LK.index(d);
    const now = {t: d.done_ms, start: d.start_ms, judge: Object.fromEntries(ix.cands.map((c) => {
      const j = ix.judge[c.id] || {};
      return [c.id, [j.verdict || "early", !!(j.band && j.band.below)]];
    })), bust: d.accounts.filter((a) => a.bust).map((a) => a.id)};
    // saved once per visit, never while the engine catches up (that visit's numbers are not the record's yet)
    if (!awayDone && !LK.catchingUp(d)) { local.set("home-seen", now); awayDone = true; }
    if (!samePrev(d) || prev.t >= d.done_ms) { put(away, null); return; }
    const changes = [];
    for (const c of ix.cands) {
      const was = (prev.judge || {})[c.id], is = now.judge[c.id];
      if (!was) continue;
      if (was[0] !== is[0]) changes.push(h("li", null, h("b", null, LK.pickKo(c)), ` 기준: ${was[0] === "early" ? "아직" : was[0] === "ok" ? "통과" : "미달"} → `, LK.verdictPill(ix.judge[c.id])));
      if (!was[1] && is[1]) changes.push(h("li", null, h("b", null, LK.pickKo(c)), " 경고등 켜짐"));
    }
    const newBust = now.bust.filter((id) => !(prev.bust || []).includes(id));
    for (const id of newBust) { const a = ix.byId[id]; if (a) changes.push(h("li", null, h("b", null, LK.pickKo(LK.pickOf(a, ix) || a)), ` ${a.role === "cand" ? "후보" : "비교"} 계좌 파산`)); }
    put(away, ui.card({plate: "자리 비운 사이", sub: `${fmt.kst(prev.t)} → ${fmt.kst(d.done_ms)} KST 처리분 · 이 기기에서 지난번에 본 뒤`, cls: "cl-away"},
      h("div", {class: "stats cl-stats3"},
        ui.stat(`닫힌 거래${afterSuffix()}`, awayTrades == null ? "…" : `${fmt.int(awayTrades.n)}번${awayTrades.more ? "+" : ""}`, awayTrades ? `이긴 거래 ${fmt.int(awayTrades.w)}번` : null),
        ui.stat("기준 · 경고등 변화", `${fmt.int(changes.length)}건`, changes.length ? "아래 목록" : "변화 없음"),
        ui.stat("파산", `${fmt.int(newBust.length)}개`, "새로 멈춘 계좌")),
      changes.length ? h("ul", {class: "cl-notes"}, changes) : null));
  }
  async function loadAwayTrades() {
    if (!prev || !prev.t || (LK.league() && LK.league().start_ms && !samePrev(LK.league()))) return;
    let f;
    try { f = await ctx.api("/api/fills"); } catch (e) { return; }
    const all = f.fills || [];
    const rows = afterFills(all).filter((t) => t.exit_time > prev.t);      // 설치 뒤 진입만: entered after the install
    awayTrades = {n: rows.length, w: rows.filter((t) => (t.pnl != null ? t.pnl > 0 : t.roe != null ? t.roe > 0 : !!t.win)).length,
      more: all.filter((t) => t.exit_time > prev.t).length >= all.length && all.length >= 300};
    const d = LK.league();
    if (d && d.accounts) paintAway(d);
  }
  loadAwayTrades();

  function paintHero(d) {
    const w = d.watch || {};
    const cps = w.checkpoints || [];
    const next = cps.find((c) => c.days_left > 0) || null;
    const H = LK.health(d);
    const line = (kind) => {
      const p = (w.pools || {})[kind];
      if (!p) return null;
      const c = p.roles.cand;
      return h("p", {class: "dl-vline"}, h("b", null, kind === "core" ? "기존 36" : "딥시크"), " · 후보 ",
        h("span", {class: "num"}, `${fmt.int(c.n)}번`), " · 한 번 평균 ", LK.ret(c.mean, {hiddenIf: !p.money}), " · ",
        LK.vsMark(p.c2.beats_base, "기본값"), " ", LK.vsMark(p.c2.beats_flip, "동전"), " · ",
        p.c1_stop == null ? h("span", {class: "muted"}, "아직 비교 전") : p.c1_stop
          ? ui.pill("지금이면 멈춤 조건", "bad", "후보 평균이 기본값과 동전 둘 다보다 나쁨 (11/11에 이러면 그 묶음을 멈춥니다)")
          : ui.pill("지금이면 계속", "good", "후보 평균이 기본값이나 동전 중 하나보다는 나음"));
    };
    put(hero,
      h("div", {class: "s2a-hrow"}, ui.plate("다음 점검"), h("span", {class: "muted s2a-small"}, H.ko)),
      next ? h("p", {class: "dl-vbig ok"}, `${next.ko} `, h("em", null, fmt.mmdd(next.ms)), h("small", {class: "cl-dleft"}, ` D-${Math.ceil(next.days_left)}`))
        : h("p", {class: "dl-vbig warn"}, "점검 일정 끝"),
      next ? h("p", {class: "note"}, next.after ? `${next.after} · ${next.what}` : next.what) : null,
      line("core"), line("ds"),
      h("p", {class: "note"}, "‘지금이면’은 미리 정한 규칙을 오늘 숫자에 대어 본 참고입니다. 판정은 점검 날 한 번만 합니다. 실제 돈은 2차 통과 뒤 두 분이 정합니다."),
      h("div", {class: "row wrap"}, h("a", {class: "btn-y", href: "#/check"}, "점검 진행 자세히"),
        h("a", {class: "btn-line", href: "#/custom"}, "커스텀값 보기"), h("a", {class: "btn-line", href: "#/howto"}, "읽는 법")));
  }

  function paintGoal(d) {
    const w = d.watch || {};
    const cps = w.checkpoints || [];
    const nextI = cps.findIndex((c) => c.days_left > 0);
    const first = LK.replayedBefore(d) ? [{ko: "다시 돌리기 시작", ms: d.start_ms, done: true}, {ko: "설치", ms: d.started_ms, done: true}]
      : [{ko: `${fmt.hm(d.start_ms)} 시작 (설치)`, ms: d.start_ms, done: true}];
    const steps = [...first, ...cps.map((c, i) => ({ko: c.ko, ms: c.ms, done: c.days_left <= 0, now: i === nextI}))];
    const min = w.min_trades || 300;
    const prog = (kind) => {
      const p = (w.pools || {})[kind];
      if (!p) return null;
      const n = p.roles.cand.n;
      return h("div", {class: "cl-prog"}, h("div", {class: "cl-progh"}, h("b", null, kind === "core" ? "기존 36 후보 거래" : "딥시크 후보 거래"),
        h("span", {class: "num"}, `${fmt.int(n)} / ${fmt.int(min)}번`)), ui.progress(n / min, null), LK.paceLine(d, n, min));
    };
    put(goal,
      h("div", {class: "s2a-hrow"}, ui.plate("일정"), h("span", {class: "s2a-dcount"}, h("b", null, `D+${LK.dPlus(d, serverNow())}`),
        ` (${LK.calDay(d, serverNow())}일째, 한국 날짜)`)),
      h("p", {class: "s2a-goalline"}, LK.replayedBefore(d) ? `${fmt.mmdd(d.start_ms)}부터 다시 돌린 뒤 5분마다 이어 갑니다. 날짜와 기준은 시작 전에 고정했습니다.`
        : `봇을 켠 때(${LK.startKo(d)})부터 모든 계좌 $5,000으로 시작해 5분마다 이어 갑니다. 날짜와 기준은 시작 전에 고정했습니다.`,
        h("small", {class: "muted"}, ` · 처리 ${fmt.kst(d.done_ms)} KST까지`)),
      h("ol", {class: "steps dl-steps s2a-steps", "aria-label": "일정"}, steps.map((x, i) => h("li", {class: x.now ? "now" : x.done ? "done" : "",
        "aria-current": x.now ? "step" : null}, h("span", {class: "s2a-sn"}, x.ms ? fmt.mmdd(x.ms) : String(i + 1)), x.ko))),
      h("p", {class: "note"}, `2차 점검은 묶음마다 후보 거래 ${fmt.int(min)}번 이상이 조건 중 하나입니다.`),
      prog("core"), prog("ds"));
  }

  function paintPools(d) {
    const w = d.watch || {};
    put(pools, ["core", "ds"].map((kind) => {
      const p = (w.pools || {})[kind];
      if (!p) return ui.card({plate: KIND_LONG[kind]}, ui.none("준비 중"));
      const rows = ROLES.map((r) => {
        const x = p.roles[r];
        return h("div", {class: ["cl-prow", `r-${r}`]}, LK.roleChip(r), h("span", {class: "num"}, `${fmt.int(x.n)}번`),
          h("span", {class: "num muted"}, x.n ? fmt.pct((100 * x.wins) / x.n, false, 0) : "—"), LK.ret(x.mean, {hiddenIf: !p.money}));
      });
      return ui.card({plate: KIND_LONG[kind], sub: `후보 ${fmt.int(p.picks)}개 · 계좌 ${fmt.int(p.accounts)}개`},
        h("div", {class: "cl-prow hd"}, h("span", null, "계좌"), h("span", null, "거래"), h("span", null, "승률"), h("span", null, "한 번 평균")),
        rows,
        h("div", {class: "row wrap cl-marks"}, h("span", {class: "muted"}, "후보가"), LK.vsMark(p.c2.positive, "0보다"),
          LK.vsMark(p.c2.beats_base, "기본값보다"), LK.vsMark(p.c2.beats_flip, "동전보다")),
        h("p", {class: "note"}, "묶음 평균 = 그 묶음 모든 계좌의 닫힌 거래를 한데 모은 거래 한 번 평균 (지갑 대비 %)."));
    }));
  }

  function paintTopBottom(d) {
    const ix = LK.index(d);
    const ranked = ix.cands.filter((c) => c.trades && c.mean_ret != null).sort((a, b) => b.mean_ret - a.mean_ret);
    const early = ranked.length && Math.max(...ranked.map((c) => c.trades)) < 30;   // no pick judged yet: say it is luck
    const col = (label, sub, rows, off) => h("div", {class: "k4-tbcol"}, h("div", {class: "k4-tbh"}, h("b", null, label), h("span", null, sub)),
      rows.length ? h("div", {role: "list"}, rows.map((c, i) => rankRow(c, off(i), ix))) : ui.empty("아직 끝난 거래가 없습니다"));
    const top = ranked.slice(0, SHOW), bot = ranked.slice(-SHOW).reverse().filter((c) => !top.includes(c));
    put(tb, col("한 번 평균 높은 후보", early ? "상위 5 · 거래가 적어 아직 운이 큼" : "상위 5", top, (i) => i + 1),
      col("한 번 평균 낮은 후보", early ? "하위 5 · 30번 전에는 판단하지 않음" : "하위 5", bot, (i) => ranked.length - i));
  }

  async function loadFills() {
    let f;
    try { f = await ctx.api("/api/fills"); } catch (e) { return; }
    fillRows = f.fills || [];
    fillsKey = "";
    paintFills();
  }
  /** the 8 newest (설치 뒤 진입만: of those entered after the install; filtered again when the install time comes) */
  function paintFills() {
    if (!fillRows) return;
    const aft = afterOn();
    const key = `${fillRows.length}|${fillRows.length ? fillRows[0].exit_time : ""}|${aft}`;
    if (key === fillsKey) return;
    fillsKey = key;
    const ix = LK.index();
    const rows = afterFills(fillRows).slice(0, 8);
    const fsub = fillsCard.querySelector(".sub");
    if (fsub) fsub.textContent = aft ? "모든 계좌 · 설치 뒤만 · 누르면 그 계좌" : "모든 계좌 · 누르면 그 계좌";
    if (!rows.length) {
      put(fills, aft && fillRows.length ? afterEmpty("설치 뒤에 들어간 끝난 거래가 아직 없습니다", `최근 거래 ${fmt.int(fillRows.length)}번은 설치 전에 들어간 것이라 '설치 뒤 진입만'에서 숨겼습니다`)
        : ui.empty("아직 끝난 거래가 없습니다"));
      return;
    }
    put(fills, h("div", {class: "s2a-rows", role: "list"}, rows.slice(0, SHOW).map((t) => fillRow(t, ix))),
      rows.length > SHOW ? ui.disclosure(`${rows.length - SHOW}개 더 보기`, h("div", {class: "s2a-rows", role: "list"}, rows.slice(SHOW).map((t) => fillRow(t, ix)))) : null);
  }
  await loadFills();
  ctx.every(60000, loadFills);
}

function rankRow(c, rank, ix) {
  const t = LK.retTxt(c.mean_ret);
  const j = ix.judge[c.id];
  return h("a", {class: "k4-row", role: "listitem", href: `#/account/${encodeURIComponent(c.id)}`, title: `${c.name} · ${c.id}`},
    h("span", {class: "rk"}, String(rank)),
    h("span", {class: "lname"}, LK.pickName(c, {code: false})),
    h("span", {class: "ret"}, h("b", {class: ["num", fmt.tone(c.mean_ret, t)]}, t)),
    h("span", {class: "meta"}, LK.kindChip(c.kind), h("span", null, `거래 ${fmt.int(c.trades)} · 승률 ${LK.winTxt(c)} · 잔고 `), LK.wallet(c),
      LK.smallN(c.trades), j && j.band && j.band.below ? LK.bandMark(j) : null));
}

function fillRow(t, ix) {
  const a = ix.byId[t.account];
  const pT = t.pnl == null ? "숨김" : fmt.money(t.pnl, true);
  return h("div", {class: "s2a-ev", role: "listitem"},
    h("div", {class: "s2a-evh"}, h("span", {class: "s2a-t num"}, fmt.kst(t.exit_time)),
      a ? h("a", {class: "s2a-nm", href: `#/account/${encodeURIComponent(a.id)}`, title: a.id}, LK.pickName(a, {code: false})) : h("span", null, t.account),
      a ? LK.roleChip(a.role, undefined) : null, h("span", {class: "grow"}), h("b", {class: ["num", "s2a-pnl", fmt.tone(t.pnl, pT)]}, pT)),
    h("div", {class: "s2a-evb"}, h("b", null, coinShort(coinOf(t.symbol))),
      h("span", {class: ["side", Number(t.side) > 0 ? "long" : "short"]}, sideKo(t.side)),
      t.leverage ? h("span", {class: "pp thin"}, `${fmt.int(t.leverage)}배`) : null,
      h("span", {class: "muted"}, reasonKo(t.exit_reason)),
      t.roe == null ? null : h("span", {class: ["num", fmt.tone(t.roe)]}, `증거금 대비 ${fmt.pct(t.roe * 100, true, 1)}`)));
}

/** The green LED bar: the 38 picks' wallets together (DeepSeek too when shown), the counts on its right. */
function ledBar() {
  const total = h("b", {class: "num"}, "—"), pctEl = h("span", {class: "led-box num"}), absEl = h("span", {class: "num"});
  const live = h("span", {class: "led-live"}, "■ 준비 중");
  const mid = h("div", {class: "led-m"});
  const right = h("div", {class: "led-r"});
  const cap = h("p", {class: "led-cap"});
  const el = h("section", {class: "ledbar s2a-led", "aria-label": "후보 38개 합계 잔고"},
    h("div", null, h("div", {class: "led-k"}, h("span", {class: "t"}, "후보 계좌 합계 잔고"), live),
      h("div", {class: "led-n"}, total, h("span", null, "USDT")), h("div", {class: "led-chg"}, pctEl, absEl)),
    mid, right, cap);
  const cells = new Map();
  const cell = (k, title, label = k) => {
    if (!cells.has(k)) {
      const v = h("b", {class: "num"}, "—");
      const kEl = h("span", null, label);
      const box = h("div", {title}, kEl, v);
      right.append(box);
      cells.set(k, {v, box, kEl});
    }
    const c = cells.get(k);
    c.box.title = title;
    c.kEl.textContent = label;
    return c.v;
  };
  el.update = (d) => {
    const ix = LK.index(d);
    const shown = ix.cands.filter((c) => c.wallet != null);
    const sum = shown.reduce((a, c) => a + c.wallet, 0), init = shown.length * LK.EQUITY;
    K4.countTo(total, shown.length ? sum : null, {format: (v) => fmt.num(v, 2), flash: true});
    pctEl.hidden = !shown.length;
    if (shown.length) K4.countTo(pctEl, (sum / init - 1) * 100, {format: K4.pctFmt(2), tone: true});
    K4.countTo(absEl, shown.length ? sum - init : null, {format: (v) => fmt.money(v, true), tone: true});
    const H = LK.health(d);
    live.className = ["led-live", H.lv === "ok" ? "" : "off"].filter(Boolean).join(" ");
    // the wallet is a closed-trade figure (open positions are not in it): "닫힌 거래 기준", never "실시간"
    live.textContent = H.lv === "ok" ? "■ 닫힌 거래 기준" : H.lv === "warn" ? (LK.catchingUp(d) ? "■ 따라잡는 중" : "■ 늦음") : "■ 멈춤";
    live.title = `엔진 상태: ${H.ko} · 합계 잔고는 닫힌 거래까지 (열린 포지션 손익은 포지션 화면)`;
    const wins = ix.cands.filter((c) => c.wallet != null && c.wallet > LK.EQUITY).length;
    put(mid, barRow(ix.cands), h("div", {class: "led-stats"}, h("span", null, `후보 ${fmt.int(ix.cands.length)}개 · 계좌마다 $5,000에서 시작`),
      h("span", null, `시작보다 많은 후보 ${fmt.int(wins)}개`)));
    // this card is the 38 picks': their own open positions and closed trades (190계좌 totals are on 서버 상태 · 포지션)
    const open = ix.cands.filter((a) => openAfter(a)).length;          // 설치 뒤 진입만: entered after the install
    const closed = ix.cands.reduce((a, x) => a + (x.trades || 0), 0);
    const ok = Object.values(d.judge || {}).filter((j) => j.verdict === "ok").length;
    const warn = Object.values(d.judge || {}).filter((j) => j.band && j.band.below).length;
    cell("시작부터", `${LK.fromKo(d)} 처리한 날 수 (시작한 날 = 1일째)`).textContent = `${fmt.int(LK.leagueDay(d))}일째`;
    cell("후보 열린 포지션", `후보 ${ix.cands.length}개 계좌의 열린 포지션${afterOn() ? " (설치 뒤에 들어간 것만)" : ""} (190계좌 전체: ${fmt.int(d.accounts.filter((a) => openAfter(a)).length)}개)`,
      `후보 열린 포지션${afterOn() ? " (설치 뒤만)" : ""}`).textContent = fmt.int(open);
    cell("후보 닫힌 거래", `후보 ${ix.cands.length}개 계좌의 닫힌 거래 (190계좌 전체: ${fmt.int(d.accounts.reduce((a, x) => a + (x.trades || 0), 0))}번)`).textContent = fmt.int(closed);
    cell("기준 통과", "30번 이상 거래한 후보 중 평균 > 0 · 기본값보다 · 동전보다").textContent = fmt.int(ok);
    cell("경고등", "기존 36 후보 중 백테스트 예상 범위(하위 5%) 아래").textContent = fmt.int(warn);
    cell("파산 (190계좌)", "190개 계좌 중 파산한 계좌").textContent = fmt.int(d.accounts.filter((a) => a.bust).length);
    cap.textContent = shown.length < ix.cands.length
      ? `합계는 금액이 보이는 후보 ${shown.length}개만 (딥시크 금액 숨김) · 수수료·슬리피지·펀딩 뺀 뒤 · 가상 돈 (주문 없음)`
      : "후보 38개 계좌의 지갑 합계 (닫힌 거래까지) · 수수료·슬리피지·펀딩 뺀 뒤 · 가상 돈 (주문 없음)";
  };
  return el;
}

/** One small bar per pick (its wallet against the $5,000 start), sorted: the spread of the 38 at a glance. */
function barRow(cands) {
  const vals = cands.map((c) => (c.wallet == null ? null : c.wallet / LK.EQUITY - 1)).filter((v) => v != null).sort((a, b) => b - a);
  if (!vals.length) return h("div", {class: "led-stats"}, h("span", null, "후보 잔고 준비 중"));
  const W = 300, H = 56, n = vals.length, max = Math.max(0.05, ...vals.map(Math.abs));
  const bw = W / n;
  const mid = H / 2;
  return s("svg", {viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img", class: "cl-ledbars",
    "aria-label": `후보 ${n}개의 잔고 변화 (큰 순서): 위로 = 시작보다 많음`},
  s("line", {class: "bl", x1: 0, x2: W, y1: mid, y2: mid}),
  vals.map((v, i) => {
    const hgt = Math.max(1, (Math.abs(v) / max) * (mid - 2));
    return s("rect", {class: v >= 0 ? "u" : "d", x: (i * bw + 0.6).toFixed(1), width: Math.max(0.8, bw - 1.2).toFixed(1),
      y: (v >= 0 ? mid - hgt : mid).toFixed(1), height: hgt.toFixed(1)});
  }));
}
