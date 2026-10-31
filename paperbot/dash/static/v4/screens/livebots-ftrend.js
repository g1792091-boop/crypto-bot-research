// 실거래 › 바이비트 봇 › 친구 추세판 (#/ftrend, owners 10-29): the friend's trend indicator per coin, as the two bots that use
// it saw it (dash/more/liveftrend.py, /api/v4/livebots/ftrend every 30 s), read-only:
//   30분   the 바이비트 봇's last close: the trend and its four votes (하늘·보라 선 · EMA RSI · 찹존 · 슈퍼트렌드), the OBV
//          pane's colour (연한 / 진한 초록 · 빨강, the light -> dark turn the OBV rule enters on), its 50 line's value (the
//          rule of 10-30), the Stoch RSI pane when the bot reads it (K, D, 50선 아래 / 위, a golden / dead ●) and each
//          rule's answer in the bot's words
//   1시간  the 레인지 봇's last closed hour (its trend check), once its config uses the indicator
//   owners 10-30: the friend bot's own read (WOO X Pro 2: its trend, OBV colour, AC bar and answers) and the 레인지 봇's
//          ROC 30분 read per coin (the ROC entry: 롱 신호 / 숏 신호 / the bar's colour, the purple line)
//   owners 10-31 night: the three mix bots' boards (바이비트 봇, 친구 15분 봇, 레인지 봇: each source's ``name_ko`` /
//          ``tf_ko`` / ``trend_tf_ko`` from its config; owners 10-31, last: all on 15분 signals, the trend on 30분: whoLabel) on the '추세 바' 종합 (trendCell / barRows: 종합 상승 초록 · 하락 빨강 ·
//          횡보 노랑 = 진입 금지, and its six rows) and rule "h0x" (h0xKo: the histogram's 0 cross and its value); once the
//          레인지 봇 trades WOO X Pro by itself (the answer's ``moved``) its old paper's 1시간 / ROC rows leave the cards
// HONESTY: a bot that is off or has not written its row yet says so; an old row says how old; never a vote of our own.
import {h, put, ui, fmt, serverNow} from "../core/pb.js";

export const FTREND_API = "/api/v4/livebots/ftrend";
const REFRESH_MS = 30 * 1000;
const MIN = 60 * 1000;
const ok = (x) => x != null && x !== "" && Number.isFinite(Number(x));
const TONE = {1: "up", "-1": "down", 0: "side"};
const BAR_TONE = {1: "up", "-1": "down", 0: "flat"};    // the trend bar's 종합: 초록 / 빨강 / 노랑
/** A board source's bot and bars: {name, tf, ttf} (its answer's ``name_ko`` / ``tf_ko`` / ``trend_tf_ko``: its signal bar
 *  and the bar its trend is read on, owners 10-31, last: 15분 and 30분; an answer from before 10-31 night: the words of then). */
export function srcWho(src, name, tf) {
  return {name: (src && src.name_ko) || name, tf: (src && src.tf_ko) || tf, ttf: (src && src.trend_tf_ko) || null};
}
/** A bot's label on a coin card: "15분 신호 · 추세 30분 (바이비트 봇)" (the row's own ``tf`` / ``trend_tf`` first); the
 *  trend's bar left out when it is the signal's own ("30분 (친구 30분 봇)"). */
export function whoLabel(w, row) {
  return `${barsKo(w, row)} (${w.name})`;
}
/** A bot's bars: "15분 신호 · 추세 30분" / "30분" (whoLabel without the name). */
export function barsKo(w, row) {
  const tf = (row && row.tf) || w.tf, ttf = (row && row.trend_tf) || w.ttf;
  return ttf && ttf !== tf ? `${tf} 신호 · 추세 ${ttf}` : tf;
}
/** Rule "h0x" (owners 10-31 night): "히스토그램 0선 아래로 돌파 (−4.08)"; null without it. */
export function h0xKo(x) {
  if (!x) return null;
  return `히스토그램 ${x.ko || "0선 돌파 없음"}${ok(x.h6) ? ` (${fmt.num(x.h6, 2)})` : ""}`;
}
/** OBV MACD's AC bar in the owners' words (10-31 evening): "플러스 양봉 (0.42)" / "마이너스 음봉 (-0.31)" … */
export function acKo(ac, col) {
  if (!ok(ac)) return "못 읽음";
  const a = Number(ac), c = Number(col);
  return `${a > 0 ? "플러스" : a < 0 ? "마이너스" : "0"} ${c > 0 ? "양봉" : c < 0 ? "음봉" : "보합"} (${fmt.num(a, 2)})`;
}

// ---------------------------------------------------------------- pure (node tests: tests/test_dash_liveftrend.py)
/** "3분 전" / "1시간 5분 전" (ms ago); "" when unknown. */
export function agoKo(ms) {
  if (!ok(ms)) return "";
  const m = Math.max(0, Math.round(Number(ms) / MIN));
  return m < 1 ? "방금" : m < 60 ? `${m}분 전` : `${Math.floor(m / 60)}시간${m % 60 ? ` ${m % 60}분` : ""} 전`;
}
/** A coin's trend cell in words and tone: {text, tone ("up" / "down" / "side" / "na"; the trend bar's 횡보: "flat"), sub}. */
export function trendCell(x) {
  if (!x || x.state !== "ok") return {text: x && x.state === "error" ? "못 읽음" : "—", tone: "na", sub: (x && x.ko) || ""};
  if (x.bar) {                                       // owners 10-31 night: the trend bar's 종합
    const b = x.bar, n = Array.isArray(b.n) && b.n.every(ok) ? `상승 ${b.n[0]} · 하락 ${b.n[1]} · 횡보 ${b.n[2]}` : "";
    return {text: `종합 ${b.ko || "모름"}${b.colour_ko ? ` ${b.colour_ko}` : ""}`, tone: BAR_TONE[x.trend] || "na",
      sub: [n, x.trend === 0 ? "진입 금지" : ""].filter(Boolean).join(" · ")};
  }
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
/** The trend bar's six rows as chips (owners 10-31 night): "3개 점수 횡보 (−1)" · "6종 평균 하락" · …; the same chips as the votes. */
function barRows(b) {
  return votesRow(((b && b.rows) || []).map((r) => ({ko: r.ko, side: r.side, side_ko: r.side_ko})));
}

/** ftrendView(ctx) -> {el, set()}: its own endpoint, read now and every 30 s. */
export function ftrendView(ctx) {
  const st = {d: null, okAt: 0, busy: false};
  const slot = h("div", {class: "lb-slot"});
  const head = h("div", {class: "lft-head"});
  const grid = h("div", {class: "lft-grid"});
  const rules = h("ul", {class: "lft-rules"});
  const cardSub = h("span");
  const main = h("div", {class: "lft-body"},
    ui.card({title: "코인별 친구 추세", sub: "봇마다 마지막 봉 마감에 본 값 · 봇 기록 그대로", cls: "lft-card"}, h("p", {class: "lft-src"}, cardSub), head, grid),
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
  function coinCard(r, w) {
    const m = r.m30 || {}, t1 = r.h1 || {};
    const c30 = trendCell(m), c1 = trendCell(t1), ob = obvCell(m.obv), sk = stochCell(m.stoch);
    const old = !(st.d && st.d.moved);                 // the old 레인지 봇 paper's rows (before its move, 10-31 night)
    return h("section", {class: ["lft-coin", c30.tone], "aria-label": `${r.coin} 추세`},
      h("header", {class: "lft-ch"}, h("b", {class: "lft-cn"}, r.coin),
        h("span", {class: ["lft-big", c30.tone]}, c30.text), h("small", {class: "lft-sub"}, `${whoLabel(w.m, m)}${c30.sub ? ` · ${c30.sub}` : ""}`),
        r.in30 ? null : h("small", {class: "lft-sub"}, ` (${w.m.name} 코인 아님)`)),
      m.state === "ok" ? (m.bar ? barRows(m.bar) : votesRow(m.votes)) : m.ko && m.ko !== c30.sub ? h("p", {class: "lft-sub"}, m.ko) : null,
      m.state === "ok" ? h("dl", {class: "lft-kv"},
        m.obv ? h("dt", null, "OBV") : null,
        m.obv ? h("dd", null, h("span", {class: ["lft-obv", ob.tone, ob.dark ? "dark" : "light"]}, h("i", {"aria-hidden": "true"}), ob.text),
          ob.turn ? h("b", {class: ["lft-turn", ob.tone]}, ` 바뀜: ${ob.turn}`) : null) : null,
        ok(m.obv50) ? h("dt", null, "OBV 50선") : null,
        ok(m.obv50) ? h("dd", {class: "num"}, `${fmt.num(m.obv50, 1)} (${Number(m.obv50) < 50 ? "50 아래: 롱 쪽" : "50 위: 숏 쪽"})`) : null,
        ok(m.ac) ? h("dt", null, "AC 막대") : null,
        ok(m.ac) ? h("dd", {class: "num"}, acKo(m.ac, m.ac_col)) : null,
        m.h0x ? h("dt", null, "히스토그램") : null,
        m.h0x ? h("dd", {class: "num"}, h0xKo(m.h0x)) : null,
        m.stoch ? h("dt", null, "스톡RSI") : null,
        m.stoch ? h("dd", null, h("span", {class: ["lft-stoch", sk.tone]}, sk.text), sk.cross ? h("b", {class: "lft-turn"}, ` ${sk.cross}`) : null) : null,
        ok(m.ema_rsi) ? h("dt", null, "EMA RSI") : null, ok(m.ema_rsi) ? h("dd", {class: "num"}, fmt.num(m.ema_rsi, 1)) : null,
        ok(m.stop_pct) ? h("dt", null, "손절 폭") : null,
        ok(m.stop_pct) ? h("dd", {class: "num"}, `${fmt.num(m.stop_pct, 2)}% (ATR × 3)`, m.liq_ok === false ? h("small", {class: "lft-bad"}, " · 청산가보다 멀어 진입 안 함") : null) : null) : null,
      m.state === "ok" ? h("ul", {class: "lft-rl"}, ruleLines(m).map((x) => h("li", null, ui.pill(x.ko, "thin"), h("span", {class: x.tone === "good" ? "lft-go" : "lft-sub"}, ` ${x.text}`)))) : null,
      old && st.d && st.d.h1 ? h("div", {class: "lft-h1"}, h("span", {class: "lft-sub"}, "1시간 (레인지 봇)"),
        t1.state === "ok" ? [h("b", {class: ["lft-mid", c1.tone]}, c1.text), votesRow(t1.votes)] : h("span", {class: "lft-sub"}, ` ${t1.ko || "—"}`)) : null,
      old && r.roc ? h("div", {class: "lft-h1"}, h("span", {class: "lft-sub"}, r.roc.kind === "ema3" ? "추세 3개 15분 (레인지 봇)" : "ROC 30분 (레인지 봇)"), rocCell(r.roc)) : null,
      r.inf && r.f30 ? h("div", {class: "lft-h1"}, h("span", {class: "lft-sub"}, whoLabel(w.f, r.f30)), ...friendCell(r.f30)) : null,
      r.inrg && r.rg ? h("div", {class: "lft-h1"}, h("span", {class: "lft-sub"}, whoLabel(w.r, r.rg)), ...friendCell(r.rg)) : null);
  }
  function rocCell(x) {
    if (x.state !== "ok") return h("span", {class: "lft-sub"}, ` ${x.ko || "못 읽음"}`);
    const tone = TONE[x.side] || "side";
    return [h("b", {class: ["lft-mid", tone]}, x.ko || "—"), h("small", {class: "lft-sub"}, ` ${x.osc_ko || ""}`)];
  }
  function friendCell(f) {
    if (f.state !== "ok") return [h("span", {class: "lft-sub"}, ` ${f.ko || "아직 없음"}`)];
    const c = trendCell(f), ob = obvCell(f.obv), rl = ruleLines(f);
    return [h("b", {class: ["lft-mid", c.tone]}, c.text), c.sub && f.bar ? h("small", {class: "lft-sub"}, ` ${c.sub}`) : null,
      f.bar ? barRows(f.bar) : null,
      ob.tone !== "na" ? h("span", {class: ["lft-obv", ob.tone, ob.dark ? "dark" : "light"]}, h("i", {"aria-hidden": "true"}), `OBV ${ob.text}`) : null,
      ok(f.ac) ? h("small", {class: "lft-sub"}, ` AC ${acKo(f.ac, f.ac_col)}`) : null,
      f.h0x ? h("small", {class: "lft-sub"}, ` ${h0xKo(f.h0x)}`) : null,
      ...rl.map((x) => h("small", {class: x.tone === "good" ? "lft-go" : "lft-sub"}, ` ${x.text}`))];
  }
  /** The bots of this answer, each {name, tf} (its board's source; the words of before 10-31 night for an older answer). */
  const whoOf = (d) => ({m: srcWho(d.m30, "바이비트 봇", "30분"), f: srcWho(d.f30, "친구 30분 봇", "30분"), r: srcWho(d.r15, "레인지 봇", "15분")});
  function draw() {
    const d = st.d;
    if (!d) return;
    const w = whoOf(d);
    const old = !d.moved;
    cardSub.textContent = [`${w.m.name}: ${barsKo(w.m)}`,
      d.f30 && d.f30.state !== "off" ? `${w.f.name}: ${barsKo(w.f)}` : null,
      d.r15 && d.r15.state !== "off" ? `${w.r.name}: ${barsKo(w.r)}` : null, old && d.h1 ? "1시간: 레인지 봇 페이퍼의 마지막 1시간봉" : null,
      old && d.roc && d.roc.state === "ok" ? "ROC 30분: 레인지 봇 페이퍼의 ROC 진입 값" : null].filter(Boolean).join(" · ");
    put(head, srcLine(d.m30, w.m.name), old ? srcLine(d.h1, "1시간") : null,
      d.f30 && d.f30.state !== "off" ? srcLine(d.f30, w.f.name) : null,
      d.r15 && d.r15.state !== "off" ? srcLine(d.r15, w.r.name) : null,
      old && d.roc && d.roc.state === "ok" ? srcLine(d.roc, "ROC 30분 (레인지 봇)") : null,
      (d.agree || []).length ? h("p", {class: "lft-src"}, ui.pill("30분 = 1시간", "accent"), ` 두 추세가 같은 코인: ${(d.coins || []).filter((c) => d.agree.includes(c.symbol)).map((c) => c.coin).join(" · ")}`) : null);
    const cs = d.coins || [];
    put(grid, cs.length ? cs.map((r) => coinCard(r, w)) : ui.empty(`보여 줄 코인이 없어요 · ${w.m.name} 설정을 읽지 못했어요`));
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
