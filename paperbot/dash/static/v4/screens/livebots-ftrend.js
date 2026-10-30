// 실거래 › 바이비트 봇 › 친구 추세판 (#/ftrend, owners 10-29): the friend's trend indicator per coin, as the two bots that use
// it saw it (dash/more/liveftrend.py, /api/v4/livebots/ftrend every 30 s), read-only:
//   30분   the 바이비트 봇's last close: the trend and its four votes (하늘·보라 선 · EMA RSI · 찹존 · 슈퍼트렌드), the OBV
//          pane's colour (연한 / 진한 초록 · 빨강, the light -> dark turn the OBV rule enters on), its 50 line's value (the
//          rule of 10-30), the Stoch RSI pane when the bot reads it (K, D, 50선 아래 / 위, a golden / dead ●) and each
//          rule's answer in the bot's words
//   1시간  the 레인지 봇's last closed hour (its trend check), once its config uses the indicator
//   owners 10-30: the 친구 30분 봇's own 30m read (WOO X Pro 2: its trend, OBV colour and answer) and the 레인지 봇's
//          ROC 30분 read per coin (the ROC entry: 롱 신호 / 숏 신호 / the bar's colour, the purple line)
// HONESTY: a bot that is off or has not written its row yet says so; an old row says how old; never a vote of our own.
import {h, put, ui, fmt, serverNow} from "../core/pb.js";

export const FTREND_API = "/api/v4/livebots/ftrend";
const REFRESH_MS = 30 * 1000;
const MIN = 60 * 1000;
const ok = (x) => x != null && x !== "" && Number.isFinite(Number(x));
const TONE = {1: "up", "-1": "down", 0: "side"};

// ---------------------------------------------------------------- pure (node tests: tests/test_dash_liveftrend.py)
/** "3분 전" / "1시간 5분 전" (ms ago); "" when unknown. */
export function agoKo(ms) {
  if (!ok(ms)) return "";
  const m = Math.max(0, Math.round(Number(ms) / MIN));
  return m < 1 ? "방금" : m < 60 ? `${m}분 전` : `${Math.floor(m / 60)}시간${m % 60 ? ` ${m % 60}분` : ""} 전`;
}
/** A coin's trend cell in words and tone: {text, tone ("up" / "down" / "side" / "na"), sub}. */
export function trendCell(x) {
  if (!x || x.state !== "ok") return {text: x && x.state === "error" ? "못 읽음" : "—", tone: "na", sub: (x && x.ko) || ""};
  const n = (x.votes || []).filter((v) => v.side === x.trend).length;
  return {text: x.trend_ko || "모름", tone: TONE[x.trend] || "na",
    sub: x.trend === 0 ? "추세 없음 · 진입 안 함" : `${n}표가 ${x.trend > 0 ? "상승" : "하락"}`};
}
/** The OBV pane in words: {text, tone, turn} (turn: the light -> dark bar the OBV rule enters on). */
export function obvCell(o) {
  if (!o) return {text: "—", tone: "na", turn: null};
  return {text: o.ko, tone: o.cs > 0 ? "up" : o.cs < 0 ? "down" : "side", dark: !!o.dark, turn: o.turn_ko || null};
}
/** The Stoch RSI pane in words: {text, tone, cross}. */
export function stochCell(s) {
  if (!s) return {text: "—", tone: "na", cross: null};
  const kd = ok(s.k) && ok(s.d) ? `K ${fmt.num(s.k, 1)} / D ${fmt.num(s.d, 1)}` : "K·D 모름";
  return {text: `${kd}${s.side50_ko ? ` · ${s.side50_ko}` : ""}`, tone: s.xs > 0 ? "up" : s.xs < 0 ? "down" : "side",
    cross: s.cross_ko ? `${s.cross_ko}${s.cross === "gold" ? (Number(s.k) < 50 ? " (50선 아래: 롱 신호)" : " (50선 위: 신호 아님)") : (Number(s.k) > 50 ? " (50선 위: 숏 신호)" : " (50선 아래: 신호 아님)")}` : null};
}
/** Each rule's answer on the bar: [{ko, side, why, tone}] ("진입" when the bot took the signal's side, else its reason). */
export function ruleLines(m) {
  return Object.values((m && m.rules) || {}).map((r) => ({ko: r.ko, side: r.side,
    text: r.side ? `${r.side > 0 ? "롱" : "숏"} 신호` : (r.why || "신호 없음"), tone: r.side ? "good" : "thin"}));
}

// ---------------------------------------------------------------- the view
function votesRow(vs) {
  return h("span", {class: "lft-votes", role: "list"}, (vs || []).map((v) => h("span", {class: ["lft-vote", TONE[v.side] || "na"], role: "listitem",
    title: `${v.ko}: ${v.side_ko}`}, h("i", {"aria-hidden": "true"}), v.ko, " ", h("b", null, v.side_ko))));
}

/** ftrendView(ctx) -> {el, set()}: its own endpoint, read now and every 30 s. */
export function ftrendView(ctx) {
  const st = {d: null, okAt: 0, busy: false};
  const slot = h("div", {class: "lb-slot"});
  const head = h("div", {class: "lft-head"});
  const grid = h("div", {class: "lft-grid"});
  const rules = h("ul", {class: "lft-rules"});
  const main = h("div", {class: "lft-body"},
    ui.card({title: "코인별 친구 추세", sub: "30분: 바이비트 봇이 마지막 30분봉 마감에 본 값 · 1시간: 레인지 봇이 마지막 1시간봉에 본 값 · ROC 30분: 레인지 봇의 ROC 진입 값 · 친구 30분 봇: WOO X Pro 2가 본 값 · 봇 기록 그대로", cls: "lft-card"}, head, grid),
    ui.card({title: "읽는 법", cls: "lft-rcard"}, rules));
  const el = h("div", {class: "lft stack"}, slot, main,
    ui.note("보기만 하는 화면 · 30초마다 새로 읽어요 · 트레이딩뷰 차트와 같은 식(친구 지표 그대로)으로 봇이 계산한 값이에요 · 거래소 봉 기준이라 차트와 한 봉 차이가 날 수 있어요"));

  function srcLine(s, what) {
    if (!s) return null;
    if (s.state !== "ok") return h("p", {class: ["lft-src", s.state === "error" ? "bad" : ""]}, ui.pill(s.state === "off" ? "꺼짐" : s.state === "error" ? "못 읽음" : "아직 없음", s.state === "error" ? "bad" : "thin"), ` ${what}: ${s.ko || ""}`);
    const at = s.last_close_ms || s.at;
    const age = ok(at) ? serverNow() - Number(at) : null;
    return h("p", {class: ["lft-src", s.stale ? "warn" : ""]}, ui.pill(s.stale ? "기록 오래됨" : "최신", s.stale ? "warn" : "good"),
      ` ${what}${s.bot_ko ? ` (${s.bot_ko})` : ""}: ${ok(at) ? `${fmt.kst(at)} 마감 봉 · ${agoKo(age)}` : "시각 모름"}`);
  }
  function coinCard(r) {
    const m = r.m30 || {}, t1 = r.h1 || {};
    const c30 = trendCell(m), c1 = trendCell(t1), ob = obvCell(m.obv), sk = stochCell(m.stoch);
    return h("section", {class: ["lft-coin", c30.tone], "aria-label": `${r.coin} 친구 추세`},
      h("header", {class: "lft-ch"}, h("b", {class: "lft-cn"}, r.coin),
        h("span", {class: ["lft-big", c30.tone]}, c30.text), h("small", {class: "lft-sub"}, `30분 · ${c30.sub}`),
        r.in30 ? null : h("small", {class: "lft-sub"}, " (바이비트 봇 코인 아님)")),
      m.state === "ok" ? votesRow(m.votes) : m.ko ? h("p", {class: "lft-sub"}, m.ko) : null,
      m.state === "ok" ? h("dl", {class: "lft-kv"},
        h("dt", null, "OBV"), h("dd", null, h("span", {class: ["lft-obv", ob.tone, ob.dark ? "dark" : "light"]}, h("i", {"aria-hidden": "true"}), ob.text),
          ob.turn ? h("b", {class: ["lft-turn", ob.tone]}, ` 바뀜: ${ob.turn}`) : null),
        ok(m.obv50) ? h("dt", null, "OBV 50선") : null,
        ok(m.obv50) ? h("dd", {class: "num"}, `${fmt.num(m.obv50, 1)} (${Number(m.obv50) < 50 ? "50 아래: 롱 쪽" : "50 위: 숏 쪽"})`) : null,
        m.stoch ? h("dt", null, "스톡RSI") : null,
        m.stoch ? h("dd", null, h("span", {class: ["lft-stoch", sk.tone]}, sk.text), sk.cross ? h("b", {class: "lft-turn"}, ` ${sk.cross}`) : null) : null,
        ok(m.ema_rsi) ? h("dt", null, "EMA RSI") : null, ok(m.ema_rsi) ? h("dd", {class: "num"}, fmt.num(m.ema_rsi, 1)) : null,
        ok(m.stop_pct) ? h("dt", null, "손절 폭") : null,
        ok(m.stop_pct) ? h("dd", {class: "num"}, `${fmt.num(m.stop_pct, 2)}% (ATR × 3)`, m.liq_ok === false ? h("small", {class: "lft-bad"}, " · 청산가보다 멀어 진입 안 함") : null) : null) : null,
      m.state === "ok" ? h("ul", {class: "lft-rl"}, ruleLines(m).map((x) => h("li", null, ui.pill(x.ko, "thin"), h("span", {class: x.tone === "good" ? "lft-go" : "lft-sub"}, ` ${x.text}`)))) : null,
      h("div", {class: "lft-h1"}, h("span", {class: "lft-sub"}, "1시간 (레인지 봇)"),
        t1.state === "ok" ? [h("b", {class: ["lft-mid", c1.tone]}, c1.text), votesRow(t1.votes)] : h("span", {class: "lft-sub"}, ` ${t1.ko || "—"}`)),
      r.roc ? h("div", {class: "lft-h1"}, h("span", {class: "lft-sub"}, "ROC 30분 (레인지 봇)"), rocCell(r.roc)) : null,
      r.inf && r.f30 ? h("div", {class: "lft-h1"}, h("span", {class: "lft-sub"}, "30분 (친구 30분 봇)"), ...friendCell(r.f30)) : null);
  }
  function rocCell(x) {
    if (x.state !== "ok") return h("span", {class: "lft-sub"}, ` ${x.ko || "못 읽음"}`);
    const tone = TONE[x.side] || "side";
    return [h("b", {class: ["lft-mid", tone]}, x.ko || "—"), h("small", {class: "lft-sub"}, ` ${x.osc_ko || ""}`)];
  }
  function friendCell(f) {
    if (f.state !== "ok") return [h("span", {class: "lft-sub"}, ` ${f.ko || "아직 없음"}`)];
    const c = trendCell(f), ob = obvCell(f.obv), rl = ruleLines(f);
    return [h("b", {class: ["lft-mid", c.tone]}, c.text),
      ob.tone !== "na" ? h("span", {class: ["lft-obv", ob.tone, ob.dark ? "dark" : "light"]}, h("i", {"aria-hidden": "true"}), `OBV ${ob.text}`) : null,
      ...rl.map((x) => h("small", {class: x.tone === "good" ? "lft-go" : "lft-sub"}, ` ${x.text}`))];
  }
  function draw() {
    const d = st.d;
    if (!d) return;
    put(head, srcLine(d.m30, "30분"), srcLine(d.h1, "1시간"), d.f30 && d.f30.state !== "off" ? srcLine(d.f30, "친구 30분 봇") : null,
      d.roc && d.roc.state === "ok" ? srcLine(d.roc, "ROC 30분 (레인지 봇)") : null,
      (d.agree || []).length ? h("p", {class: "lft-src"}, ui.pill("30분 = 1시간", "accent"), ` 두 추세가 같은 코인: ${(d.coins || []).filter((c) => d.agree.includes(c.symbol)).map((c) => c.coin).join(" · ")}`) : null);
    const cs = d.coins || [];
    put(grid, cs.length ? cs.map(coinCard) : ui.empty("보여 줄 코인이 없어요 · 바이비트 봇 설정을 읽지 못했어요"));
    put(rules, (d.rules_ko || []).map((x) => h("li", null, x)));
  }
  async function load() {
    if (st.busy) return;
    st.busy = true;
    let d;
    try { d = await ctx.api(FTREND_API); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      if (st.d) { put(slot, ui.staleNote(e, st.okAt, () => load().catch(() => {}))); ui.dim(main, true); }
      else put(slot, ui.errorBox(e, () => load()));
      throw e;
    } finally { st.busy = false; }
    if (!ctx.alive()) return;
    put(slot);
    ui.dim(main, false);
    st.d = d; st.okAt = Date.now();
    draw();
  }
  put(grid, ui.empty("불러오는 중"));
  load().catch(() => {});
  ctx.every(REFRESH_MS, () => load().catch(() => {}), {now: false});
  return {el, set() {}};
}
