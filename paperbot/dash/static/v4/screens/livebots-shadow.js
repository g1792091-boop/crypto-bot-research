// 실거래 › 그림자 (#/livebots/shadows; /api/v4/livebots/shadows: dash/more/liveshadow.py and livebots.shadows).
//   추세판단 봇 그림자 (owners 10/21: rule variants side by side, at no money cost, so the 2-week review decides with
//   numbers): paper bots that each change ONE rule of the live trend bot (since the 10/22 design one: 되돌림 기다림),
//   each next to the live paper (COMBO@mix) counted from that shadow's own start. Each starts with
//   its own fresh wallet, so they are compared by trade and net ROE, never by dollars: closed trades, win rate, mean and
//   summed net ROE, entries a KST weekday, the exit reasons, the deepest fall of the summed net ROE and both summed-ROE
//   lines; each card says its one difference in plain words and what its own start record really differs in; under 20
//   closed trades on either side: 표본 적음 · 아직 판단 못 함. Not on yet: 아직 안 켬 and the one command that starts it,
//   never a zero.
//   예전 봇 비교용 (folded): the old bots' shadows (A+C 합본 · 규칙봇 15 · the 10/21 trend design's three) as before
//   (trades, win rate, money, both lines),
//   next to the live paper only over the old bot's days (they compare with the old bot, not this one).
//   VWAP 개선판 그림자 (owners 10/26 "둘 다 해줘", research/opentime REPORT_KO.md): the VWAP paper with ONE change
//   (4시간 정리: closed when not at its first lock 4 hours after entry), every paper trade and, apart, the trades the
//   executor's signal light would have followed on each side's own sequence (the research's A3 helped only there).
// The page starts and stops nothing: it shows the commands to paste on the server.
import {h, s, put, ui, fmt, motion} from "../core/pb.js";
import {sourceState} from "./livebots-kit.js";
import {smallFloor} from "./livebots-calc.js";

const REFRESH_MS = 60 * 1000;

function loader(ctx, path, st, stateSlot, draw, every = REFRESH_MS) {
  async function load() {
    try { st.d = await ctx.api(path); st.okAt = Date.now(); put(stateSlot); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      put(stateSlot, st.d ? ui.staleNote(e, st.okAt, () => load()) : ui.errorBox(e, () => load()));
      throw e;
    }
    if (ctx.alive()) draw();
  }
  draw();
  load().catch(() => {});
  ctx.every(every, () => load().catch(() => {}), {now: false});
}

/** Two cumulative lines on one scale (real width W): the shadow (accent) and the live paper (muted). */
export function twoLines(a, b, W = 600, label = "그림자와 실거래 페이퍼의 누적 손익") {
  const H = 120, pad = 6;
  const pts = [...(a || []), ...(b || [])];
  if (pts.length < 2) return null;
  const t0 = Math.min(...pts.map((p) => p[0])), t1 = Math.max(...pts.map((p) => p[0]));
  let lo = Math.min(0, ...pts.map((p) => p[1])), hi = Math.max(0, ...pts.map((p) => p[1]));
  if (hi === lo) hi = lo + 1;
  const X = (t) => pad + (t1 > t0 ? (t - t0) / (t1 - t0) : 1) * (W - 2 * pad), Y = (v) => pad + (1 - (v - lo) / (hi - lo)) * (H - 2 * pad);
  const path = (xs) => (xs || []).map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
  return s("svg", {class: "lb-two", viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": label},
    s("line", {class: "zero", x1: 0, x2: W, y1: Y(0), y2: Y(0)}),
    b && b.length > 1 ? s("path", {class: "main", d: path(b)}) : null, a && a.length > 1 ? s("path", {class: "shadow", d: path(a)}) : null);
}

// ---------------------------------------------------------------- 추세판단 봇 그림자
const NO_TRADE = "거래 아직 없음";
const roeS = (x) => (x == null ? NO_TRADE : fmt.pct(x, 1, true));

/** The exit reasons in the owners' words: "잠금 익절 5 · 손절 3" ("—" before any closed trade). */
export const exitsKo = (ex) => ((ex || []).length ? ex.map((e) => `${e.reason_ko || e.reason} ${fmt.int(e.n)}`).join(" · ") : "—");

/** Entries a KST weekday: "1.2번 (평일 3.5일 · 4번)"; before half a weekday has gone by only the count. */
export function perWeekday(r) {
  if (!r) return "—";
  const span = `평일 ${fmt.num(r.weekday_days, 1)}일 · ${fmt.int(r.entries)}번`;
  return r.per_weekday == null ? `${span} (평일 반나절이 지나면 하루 평균)` : `${fmt.num(r.per_weekday, 1)}번 (${span})`;
}

/** The comparison rows [{k, sh, mn}]: the shadow's and the live paper's numbers over the same span ("—" for a side not read). */
export function cmpRows(sh, mn) {
  const side = (r, f) => (r ? f(r) : "—");
  return [
    ["닫힌 거래", (r) => `${fmt.int(r.trades)}번`],
    ["이긴 비율", (r) => (r.trades ? `${fmt.pct(r.win_rate, 0, false)} (${fmt.int(r.wins)}/${fmt.int(r.trades)})` : NO_TRADE)],
    ["거래당 평균 순ROE", (r) => roeS(r.roe_mean)],
    ["순ROE 합", (r) => roeS(r.roe_sum)],
    ["평일 하루 진입", perWeekday],
    ["누적 순ROE 최대 낙폭", (r) => (r.max_dd_roe == null ? NO_TRADE : `${fmt.num(r.max_dd_roe * 100, 1)}%p`)],
    ["청산 이유", (r) => exitsKo(r.exits)],
  ].map(([k, f]) => ({k, sh: side(sh, f), mn: side(mn, f)}));
}

/** What the shadow's own start record differs in from the live bot's (the one difference, or a warning). */
export function cfgWords(x) {
  if (x.cfg_diff == null) return {ok: null, ko: "설정 확인: 시작 기록을 못 읽어 실거래 봇과 견주지 못했어요"};
  if (x.cfg_ok) return {ok: true, ko: `설정 확인 ✓ 시작 기록에서 실거래 봇과 다른 곳은 ${x.key} 하나`};
  const keys = x.cfg_diff.map((d) => d.key);
  if (!keys.length) return {ok: false, ko: `설정 확인: 실거래 봇과 설정이 같아요 (${x.key}가 바뀌지 않음) · 견줘도 차이가 없어요`};
  return {ok: false, ko: `설정 확인: 실거래 봇과 다른 곳이 ${keys.length}곳이에요 (${keys.join(", ")}) · 규칙 하나만 바꾼 비교가 아니에요`};
}

const diffBlock = (x) => h("div", {class: "lb-tsh-diff"},
  h("p", null, h("b", null, "다른 점 하나 · "), x.diff_ko), h("p", {class: "lb-tsh-live"}, x.live_ko));

const howTo = (label, cmd) => h("div", {class: "lb-tsh-how"}, h("span", null, label), h("code", {class: "lb-cmd"}, cmd));

function trendCard(x, W, t) {
  const title = `그림자 · ${x.name_ko}`;
  if (x.state !== "ok") {
    const bad = x.state === "error", how = x.state === "off" || x.state === "empty";
    return ui.card({title, cls: "lb-tsh", acts: [ui.pill(bad ? "못 읽음" : x.state === "starting" ? "켜는 중" : x.state === "empty" ? "첫 기록 전" : "아직 안 켬",
      bad ? "bad" : "")]},
      diffBlock(x),
      bad ? sourceState(x, "그림자 기록") : h("p", {class: "lb-tsh-state"}, h("b", null, x.state_ko || "기록 없음"),
        how ? [" · 켜는 법: ", h("code", {class: "lb-tsh-code"}, x.start_ko)] : null),
      how ? ui.note(t.wait_ko || "") : null);
  }
  const rows = cmpRows(x.shadow, x.main), cw = cfgWords(x);
  const n = x.shadow ? x.shadow.trades : null, m = x.main ? x.main.trades : null;
  return ui.card({title, sub: `${fmt.kst(x.from_ms)}부터 · 실거래 페이퍼도 같은 기간 · 모의`, cls: "lb-tsh",
    acts: [x.small ? ui.pill(x.small_ko, "thin", `닫힌 거래가 양쪽 다 ${t.small_n}번이 넘어야 견줘 볼 만해요`) : null,
      x.running === false ? ui.pill("꺼져 있음", "warn") : null,
      x.stale && x.running !== false ? ui.pill(`기록 멈춤 · ${fmt.ago(x.as_of_ms)}`, "warn") : null]},
    diffBlock(x),
    h("div", {class: "lb-tsh-grid", role: "table", "aria-label": `${title}와 실거래 페이퍼, 같은 기간`},
      h("div", {class: "lb-tsh-row lb-tsh-hd", role: "row"}, h("span", {role: "columnheader"}, "같은 기간"),
        h("span", {role: "columnheader", class: "lb-shk"}, "그림자"), h("span", {role: "columnheader", class: "lb-mk"}, "실거래 페이퍼")),
      rows.map((r) => h("div", {class: "lb-tsh-row", role: "row"}, h("span", {class: "lb-tsh-k", role: "rowheader"}, r.k),
        h("span", {class: "lb-tsh-sh", role: "cell"}, r.sh), h("span", {class: "lb-tsh-mn", role: "cell"}, r.mn)))),
    x.main ? null : ui.note(x.main_ko || "실거래 페이퍼 기록을 못 읽었어요"),
    twoLines(x.shadow && x.shadow.curve, x.main && x.main.curve, W, `${title}와 실거래 페이퍼의 순ROE 합`)
      || h("p", {class: "lb-flat"}, "닫힌 거래가 생기면 순ROE 합 선이 그려져요"),
    h("p", {class: "lb-tsh-key"}, h("b", {class: "lb-shk"}, "━ 그림자"), " ", h("b", {class: "lb-mk"}, "━ 실거래 페이퍼"),
      " · 거래마다 순ROE를 더한 선 (지갑 크기와 무관)"),
    x.small ? ui.note(`${x.small_ko}: 양쪽 다 닫힌 거래가 ${t.small_n}번은 넘어야 견줘 볼 만해요 · 지금 그림자 ${n == null ? "—" : fmt.int(n)}번 · 실거래 페이퍼 ${m == null ? "—" : fmt.int(m)}번`)
      : ui.note(`양쪽 다 ${t.small_n}번 넘음 · 그래도 우연일 수 있어요`),
    h("p", {class: ["lb-tsh-cfg", cw.ok === false ? "warn" : ""]}, cw.ko),
    x.running === false ? howTo("다시 켜는 법 (서버에서):", x.start_ko) : null);
}

function trendHead(t) {
  return ui.card({title: "추세판단 봇 그림자 비교", sub: t.review_ms ? `${fmt.date(t.review_ms)} 검토용 · 모의` : "모의", cls: "lb-tsh-top"},
    h("p", {class: "lb-flat"}, `실거래 봇의 규칙을 하나만 바꾼 페이퍼 봇 ${fmt.int((t.shadows || []).length)}개가 같은 시장에서 같이 돌아요 (돈 · 주문 · 텔레그램 없음). `,
      "그림자마다 켠 때부터 새 지갑이라 달러가 아니라 거래 수 · 이긴 비율 · 순ROE로 견주고, 실거래 페이퍼도 그 그림자를 켠 때부터만 세요."),
    t.on ? null : ui.note(t.main_ko || ""),
    t.start_all_ko ? howTo("안 켠 것 한 번에 켜기 (서버에서, 한 줄):", t.start_all_ko) : null,
    t.start_all_ko ? ui.note(t.wait_ko || "") : null);
}

// ---------------------------------------------------------------- VWAP 개선판 그림자
function cmpGrid(title, sh, mn, label) {
  const rows = cmpRows(sh, mn);
  return h("div", {class: "lb-tsh-grid", role: "table", "aria-label": label},
    h("div", {class: "lb-tsh-row lb-tsh-hd", role: "row"}, h("span", {role: "columnheader"}, title),
      h("span", {role: "columnheader", class: "lb-shk"}, "그림자"), h("span", {role: "columnheader", class: "lb-mk"}, "VWAP 페이퍼")),
    rows.map((r) => h("div", {class: "lb-tsh-row", role: "row"}, h("span", {class: "lb-tsh-k", role: "rowheader"}, r.k),
      h("span", {class: "lb-tsh-sh", role: "cell"}, r.sh), h("span", {class: "lb-tsh-mn", role: "cell"}, r.mn))));
}

/** One VWAP shadow: every paper trade, then the trades the executor's light would have followed (the money side). */
export function vwapCard(x, W, v) {
  if (x.state !== "ok") return trendCard(x, W, v);
  const title = `VWAP 그림자 · ${x.name_ko}`, cw = cfgWords(x);
  const n = x.shadow ? x.shadow.trades : null, m = x.main ? x.main.trades : null;
  return ui.card({title, sub: `${fmt.kst(x.from_ms)}부터 · VWAP 페이퍼도 같은 기간 · 모의`, cls: "lb-tsh",
    acts: [x.small ? ui.pill(x.small_ko, "thin", `닫힌 거래가 양쪽 다 ${v.small_n}번이 넘어야 견줘 볼 만해요`) : null,
      x.running === false ? ui.pill("꺼져 있음", "warn") : null,
      x.stale && x.running !== false ? ui.pill(`기록 멈춤 · ${fmt.ago(x.as_of_ms)}`, "warn") : null]},
    h("div", {class: "lb-tsh-diff"}, h("p", null, h("b", null, "다른 점 하나 · "), x.diff_ko),
      h("p", {class: "lb-tsh-live"}, x.live_ko.replace("실거래 VWAP 봇은", "VWAP 페이퍼(실거래가 따라가는 봇)는"))),
    cmpGrid("모든 페이퍼 거래", x.shadow, x.main, `${title}와 VWAP 페이퍼, 모든 거래`),
    cmpGrid("실행기가 따라갔을 거래", x.shadow_lit, x.main_lit, `${title}와 VWAP 페이퍼, 신호등을 거친 거래`),
    ui.note(`아래 표는 ${(v.light && v.light.ko) || "신호등"} · 각자 자기 거래 순서로 다시 계산 (실제 주문 아님)`),
    x.main ? null : ui.note(x.main_ko || "VWAP 페이퍼 기록을 못 읽었어요"),
    twoLines(x.shadow && x.shadow.curve, x.main && x.main.curve, W, `${title}와 VWAP 페이퍼의 순ROE 합`)
      || h("p", {class: "lb-flat"}, "닫힌 거래가 생기면 순ROE 합 선이 그려져요"),
    h("p", {class: "lb-tsh-key"}, h("b", {class: "lb-shk"}, "━ 그림자"), " ", h("b", {class: "lb-mk"}, "━ VWAP 페이퍼"),
      " · 모든 페이퍼 거래의 순ROE를 더한 선 (지갑 크기와 무관)"),
    x.small ? ui.note(`${x.small_ko}: 양쪽 다 닫힌 거래가 ${v.small_n}번은 넘어야 견줘 볼 만해요 · 지금 그림자 ${n == null ? "—" : fmt.int(n)}번 · VWAP 페이퍼 ${m == null ? "—" : fmt.int(m)}번`)
      : ui.note(`양쪽 다 ${v.small_n}번 넘음 · 그래도 우연일 수 있어요`),
    h("p", {class: ["lb-tsh-cfg", cw.ok === false ? "warn" : ""]}, cw.ko.replace(/실거래 봇/g, "VWAP 봇")),
    x.running === false ? howTo("다시 켜는 법 (서버에서):", x.start_ko) : null);
}

function vwapHead(v) {
  return ui.card({title: "VWAP 개선판 그림자 비교", sub: "모의 · 몇 주 지켜본 뒤 정하기", cls: "lb-tsh-top"},
    h("p", {class: "lb-flat"}, "5년 시험에서 '4시간 안에 첫 잠금 못 하면 닫기'는 신호등을 거친 실거래 쪽에서만 좋아졌고, 페이퍼 전체로는 차이가 없었어요. ",
      "그래서 실거래 규칙은 그대로 두고, 같은 시장에서 그 규칙 하나만 바꾼 페이퍼 봇을 같이 돌려 실제로도 그런지 봐요 (돈 · 주문 · 텔레그램 없음)."),
    v.on ? null : ui.note(v.main_ko || ""),
    v.start_all_ko ? howTo("안 켠 것 켜기 (서버에서, 한 줄):", v.start_all_ko) : null,
    v.start_all_ko ? ui.note(v.wait_ko || "") : null);
}

// ---------------------------------------------------------------- 예전 봇 비교용
const statLine = (x) => (x ? `${fmt.int(x.trades)}번 · 승률 ${x.win_rate == null ? "—" : fmt.pct(x.win_rate, 1, false)} · ${fmt.money(x.pnl, true)} USDT` : "—");

function oldCard(x, W) {
  if (x.state !== "ok") return ui.card({title: x.name_ko, cls: "lb-shcard"}, sourceState(x, x.name_ko));
  const fl = smallFloor(x.stats.trades);
  const diff = x.main && x.main.stats ? x.stats.pnl - x.main.stats.pnl : null;
  const span = x.no_overlap ? `${fmt.kst(x.since_ms)}부터 · 자기 기록만 · 모의`
    : x.until_ms ? `${fmt.kst(x.since_ms)}~${fmt.kst(x.until_ms)} 같은 기간 · 모의` : `${fmt.kst(x.since_ms)}부터 같은 기간 · 모의`;
  return ui.card({title: x.name_ko, sub: span, cls: "lb-shcard", acts: [ui.pill("", "ref")]},
    h("div", {class: "lb-recs"},
      h("div", {class: "lb-rec"}, h("b", {class: "lb-shk"}, "그림자"), h("span", null, statLine(x.stats)), fl ? ui.smallSample(x.stats.trades, fl) : null),
      h("div", {class: "lb-rec"}, h("b", {class: "lb-mk"}, "실거래 페이퍼"), h("span", null, x.main ? statLine(x.main.stats) : x.no_overlap ? "견줄 기간 없음" : "—"))),
    twoLines(x.curve, x.main && x.main.curve, W) || h("p", {class: "lb-flat"}, "닫힌 거래가 두 번 넘게 쌓이면 선이 그려져요"),
    x.no_overlap ? ui.note("예전 봇이 끝난 뒤에 켜져서 실거래 페이퍼(지금은 추세판단 봇)와 견줄 기간이 없어요") : null,
    x.later ? ui.note(`그 뒤 거래 ${fmt.int(x.later)}번은 지금 봇과 견주지 않아요`) : null,
    diff != null ? ui.note(`같은 기간 손익 차이 (그림자 − 실거래 페이퍼): ${fmt.money(diff, true)} USDT · 거래가 적을 때는 우연일 수 있어요`) : null,
    x.stale ? ui.pill(`기록 멈춤 · ${fmt.ago(x.as_of_ms)}`, "warn") : null);
}

function oldPart(d, W) {
  const rows = d.shadows || [];
  const on = rows.filter((x) => x.state === "ok").length;
  const content = h("div", {class: "lb-shadows"},
    ui.note((d.old_ko || "예전 봇의 그림자예요") + (d.old_until_ms ? ` · 실거래 페이퍼와는 예전 봇이 돌던 ${fmt.kst(d.old_until_ms)} 전까지만 견줘요` : "")),
    rows.map((x) => oldCard(x, W)));
  return h("div", {class: "lb-tsh-old"},
    ui.disclosure(`예전 봇 비교용 · 그림자 ${rows.length}개${on ? ` (기록 있는 것 ${on}개)` : " (기록 없음)"}`, content, false));
}

/** shadowsView(ctx) -> {el, set()} */
export function shadowsView(ctx) {
  const st = {d: null, okAt: 0};
  const stateSlot = h("div", {class: "lb-slot"});
  const body = h("div", {class: "lb-shadows"});
  const el = h("div", {class: "lb-shadowv stack"}, stateSlot, body,
    h("div", {class: "lb-foot"}, ui.assumeLine(["closed"], "그림자도 모의 · 참고")));
  function draw() {
    const d = st.d;
    if (!d) { put(body, motion.shimmer(3)); return; }
    const W = Math.max(260, Math.round((body.clientWidth || 600) - 40));
    const t = d.trend || {shadows: [], on: false, small_n: 20};
    const v = d.vwap || null;
    put(body, v ? [vwapHead(v), (v.shadows || []).map((x) => vwapCard(x, W, v))] : null,
      trendHead(t), (t.shadows || []).map((x) => trendCard(x, W, t)), oldPart(d, W));
  }
  loader(ctx, "/api/v4/livebots/shadows", st, stateSlot, draw);
  return {el, set() {}};
}
