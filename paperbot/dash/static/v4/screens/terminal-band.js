// 터미널 맨 위 '실험 잘 되고 있나' 한 줄 띠 (term-plus, owners' review 10/06: "PC에서 처음 뜨는 화면은 터미널인데 '어떻게 되고 있나'는
// 홈·흐름·판정을 돌아다녀야 보인다"). One slim line under the price row, made ONLY of numbers the page already has:
//   ● 상태 (이상 없음 / 확인할 것 있음 / 문제 있음 + 봇 생존 신호 n초 전)   D+9/30 · 판정 11/05   기존 36 중앙값 −19.3% / 동전 봇 −14.9% (참고)
//   같은 봉 동전 봇 중앙값보다 위 67/144 · 아직 운일 수 있음   오늘 기존 36 거래 124건   판정 대상 30건 넘음 11/241   결재 대기 1
// Each chip is a link (상태 → 서버, D+ → 판정, 중앙값·위 → 순위표, 오늘 → 흐름, 판정 대상 → 판정, 결재 대기 → the header bell's list).
// HONESTY: every chip says only what its data says. A number that was not read is "—" with the tooltip "불러오지 못함"
// (or "불러오는 중"), never 0; 이상 없음 appears ONLY when the health card was read and says ok, no critical line stands and
// the bot's heartbeat is known and fresh (terminal-band-calc.js statusOf); every comparison with the coin flips is marked
// 참고 + 아직 운일 수 있음 and is never a pass or a fail (CONTRACT §1); DeepSeek and coin-flip accounts are counted only.
// When the window is too narrow the lowest-priority chips go first (fit(): 결재 → 판정 대상 → 오늘 → 위 a/n → 중앙값), no
// text is ever clipped. Nothing moves except text: no animation, no timer that invents a change (the heartbeat age is
// recomputed from the stream's real last heartbeat every 5 s).
import {h, put, ui, fmt, derive, store, stream, serverNow, criticalLines} from "../core/pb.js";
import {dayInfo, judgedCounts, compareCounts, todayTrades, statusOf, MIN_TRADES} from "./terminal-band-calc.js";

const FAIL = "불러오지 못함";
const WAIT = "불러오는 중";

/** bandLine(ctx) -> {el, fit()} */
export function bandLine(ctx) {
  const chips = new Map();
  const mk = (key, pri, attrs) => {
    const el = h("a", {class: ["term-bc2", "c-" + key], "data-pri": String(pri), ...attrs});
    chips.set(key, el);
    return el;
  };
  const status = mk("status", 1, {href: ctx.href("server")});
  const day = mk("day", 2, {href: ctx.href("checkpoint")});
  const med = mk("med", 3, {href: ctx.href("board")});
  const above = mk("above", 4, {href: ctx.href("board")});
  const today = mk("today", 5, {href: ctx.href("flow")});
  const judged = mk("judged", 6, {href: ctx.href("checkpoint")});
  // the header bell opens its own list of proposals that wait for the owners (core/bell.js): this chip presses it
  const appr = mk("appr", 7, {href: "#", role: "button", onclick: (e) => { e.preventDefault(); const b = document.getElementById("bellbtn"); if (b) b.click(); }});
  const el = h("div", {class: "term-band", role: "group", "aria-label": "실험 진행 한 줄 요약"},
    h("span", {class: "term-bl"}, "실험 상황"), status, day, med, above, today, judged, appr);

  let bell = {n: null, failed: false, loaded: false};
  const sep = (t) => h("span", {class: "term-bsep", "aria-hidden": "true"}, t);
  const state = (key) => { const m = store.meta(key); return {v: store.get(key), failed: !!(m && m.err)}; };
  const dash = (why) => h("span", {class: "num"}, "—");

  function paintStatus() {
    const hs = state("health"), st = state("status");
    const hb = stream.heartbeat;
    let hbAge = hb ? Math.max(0, (serverNow() - Number(hb[0])) / 1000) : null;
    if (hbAge == null && hs.v && hs.v.bot && hs.v.bot.ready && hs.v.bot.heartbeat_age_s != null) hbAge = Number(hs.v.bot.heartbeat_age_s);
    const crit = criticalLines({health: hs.v || null, alerts: (st.v && st.v.alerts) || [], trades: [], hb, streamOk: stream.state === "open",
      now: Date.now(), kindOf: () => null});
    const s = statusOf({health: hs.v || null, healthFailed: hs.failed, hbAgeS: hbAge, critical: crit});
    status.className = `term-bc2 c-status ${s.level}`;
    put(status, h("i", {class: "term-bdot", "aria-hidden": "true"}), h("b", null, s.text),
      hbAge != null ? h("span", {class: "muted num"}, ` · 봇 신호 ${fmt.dur(hbAge)} 전`) : null);
    status.title = `${s.text}${s.detail ? `: ${s.detail}` : ""}${hbAge != null ? ` · 봇 생존 신호 ${fmt.dur(hbAge)} 전` : ""} · 누르면 서버 화면`
      + (s.level === "ok" ? " (상태 카드가 정상이고 빨간 알림이 없고 봇 신호가 방금 왔을 때만 '이상 없음')" : "");
  }
  function paintDay(sm) {
    const d = dayInfo(sm.v, serverNow());
    if (!d) { put(day, h("b", {class: "num"}, "D+—")); day.title = `실험 날짜: ${sm.failed ? FAIL : WAIT}`; return; }
    put(day, h("b", {class: "num"}, `D+${fmt.int(d.day)}/${fmt.int(d.of)}`), d.verdictTs ? h("span", {class: "muted num"}, ` · 판정 ${fmt.mmdd(d.verdictTs)}`) : null);
    day.title = `30일 실험 ${fmt.int(d.day)}일째${d.verdictTs ? ` · 다음 판정 ${fmt.kst(d.verdictTs)}${d.left != null ? ` (${fmt.int(d.left)}일 남음)` : ""}` : ""} · 누르면 판정 화면`;
  }
  function paintBoard(bd) {
    const gs = bd.v ? derive.groupStats(bd.v) : null;
    const c = compareCounts(gs), j = judgedCounts(bd.v);
    const why = bd.failed ? FAIL : WAIT;
    if (!c) {
      put(med, h("span", null, "기존 36 중앙값 "), dash()); med.title = `기존 36 중앙값: ${why}`;
      put(above, h("span", null, "동전 봇 중앙값보다 위 "), dash()); above.title = `같은 봉 동전 봇 중앙값보다 위인 계좌 수: ${why}`;
    } else {
      put(med, h("span", null, "기존 36 중앙값 "), c.medRet == null ? dash() : h("b", {class: ["num", fmt.tone(c.medRet, fmt.pct(c.medRet))]}, fmt.pct(c.medRet)),
        c.coinRet == null ? null : [h("span", {class: "muted"}, " / 동전 봇 "), h("b", {class: ["num", fmt.tone(c.coinRet, fmt.pct(c.coinRet))]}, fmt.pct(c.coinRet))],
        ui.pill("", "ref"));
      med.title = "닫힌 거래까지 반영한 잔고 기준 중앙값 (기존 36 계좌 vs 동전 봇 계좌) · 참고일 뿐 판정(30일째) 전에는 합격·불합격이 아닙니다 · 누르면 순위표";
      if (!c.vsN) { put(above, h("span", null, "동전 봇 중앙값보다 위 "), dash()); above.title = "같은 봉 동전 봇이 아직 없어 비교할 수 없습니다"; }
      else {
        put(above, h("span", null, "같은 봉 동전 봇 중앙값보다 위 "), h("b", {class: "num"}, `${fmt.int(c.above)}/${fmt.int(c.vsN)}`),
          h("span", {class: "muted"}, " · 아직 운일 수 있음"));
        above.title = `기존 36의 계좌 ${fmt.int(c.vsN)}개 중 ${fmt.int(c.above)}개가 같은 봉 동전 봇 중앙값보다 잔고가 위 (아래 ${fmt.int(c.below)}개) · 참고 · `
          + "거래가 적을 때는 운으로도 이만큼 나옵니다: 아직 운일 수 있음 · 합격·불합격은 30일째 판정이 정합니다 · 누르면 순위표";
      }
    }
    if (!j) { put(judged, h("span", null, `판정 대상 ${MIN_TRADES}건 넘음 `), dash()); judged.title = `판정 대상 계좌: ${why}`; }
    else {
      put(judged, h("span", null, `판정 대상 ${MIN_TRADES}건 넘음 `), h("b", {class: "num"}, `${fmt.int(j.ready)}/${fmt.int(j.n)}`));
      judged.title = `판정 대상 계좌 ${fmt.int(j.n)}개(36개 매매법의 판정 봉 + 딥시크 + 5분봉) 중 닫힌 거래가 ${MIN_TRADES}건 이상인 계좌 ${fmt.int(j.ready)}개 · 진행 상황일 뿐 판정이 아닙니다 (${MIN_TRADES}건이 안 되면 판정 날 '보류') · 누르면 판정 화면`;
    }
  }
  function paintToday(sm) {
    const t = todayTrades(sm.v);
    if (!t) { put(today, h("span", null, "오늘 기존 36 거래 "), dash()); today.title = `오늘 거래: ${sm.failed ? FAIL : WAIT}`; return; }
    put(today, h("span", null, "오늘 기존 36 거래 "), h("b", {class: "num"}, `${fmt.int(t.trades)}건`));
    today.title = `오늘(한국 시간 0시부터) 기존 36 계좌가 닫은 거래 ${fmt.int(t.trades)}건 중 이긴 거래 ${fmt.int(t.wins)}건 · 누르면 흐름(수익 달력)`;
  }
  function paintAppr() {
    if (!bell.loaded) { put(appr, h("span", null, "결재 대기 "), dash()); appr.title = `결재함: ${WAIT}`; return; }
    if (bell.failed && bell.n == null) { put(appr, h("span", null, "결재 대기 "), dash()); appr.title = `결재함: ${FAIL}`; return; }
    const n = bell.n || 0;
    appr.classList.toggle("wait", n > 0);
    put(appr, h("span", null, "결재 대기 "), h("b", {class: "num"}, n > 0 ? fmt.int(n) : "없음"));
    appr.title = n > 0 ? `두 분 승인을 기다리는 제안 ${fmt.int(n)}개 · 누르면 목록` : "승인을 기다리는 제안이 없습니다";
  }

  function render() {
    paintStatus();
    paintDay(state("summary"));
    paintBoard(state("board"));
    paintToday(state("summary"));
    paintAppr();
    requestAnimationFrame(fit);
  }

  // hide the lowest-priority chips while the band would clip one (never a cut word)
  function fit() {
    const all = [...chips.values()].sort((a, b) => Number(b.dataset.pri) - Number(a.dataset.pri));       // 결재 대기 first
    for (const c of all) c.hidden = false;
    for (const c of all) {
      if (Number(c.dataset.pri) <= 2) break;                    // 상태 and D+ never go
      if (el.scrollWidth <= el.clientWidth + 1) break;
      c.hidden = true;
    }
  }

  async function loadBell() {
    try {
      const d = await ctx.api("/api/v4/bell");
      bell = {n: d && d.ready ? Number(d.n) || 0 : null, failed: !(d && d.ready), loaded: true};
    } catch (e) {
      if (e && e.name === "AbortError") return;
      bell = {n: bell.n, failed: true, loaded: true};
    }
    if (ctx.alive()) paintAppr(), requestAnimationFrame(fit);
  }

  for (const k of ["summary", "board", "health", "status"]) ctx.watch(k, () => render());
  ctx.on("heartbeat", () => paintStatus());
  ctx.on("stream:state", () => paintStatus());
  ctx.every(5000, paintStatus, {now: false});        // the heartbeat's age is recomputed from its real timestamp (text only)
  ctx.every(60000, loadBell, {now: true});
  ctx.on("rooms", () => loadBell());
  if (typeof ResizeObserver === "function") { const ro = new ResizeObserver(() => fit()); ro.observe(el); ctx.track(() => ro.disconnect()); }
  render();
  return {el, fit};
}
