// 실거래 › 봇별 화면의 '목표 연구' (owners 10/26: "필요한 연구 부분들 각 봇마다 내 목표 수익률을 위해 필요한 분석부분들이나 연구
// 부분들 다 대시보드 화면에 추가해줘"), from /api/v4/livebots/goalres?bot=trend|range|vwap|mix|v39|bybit (dash/more/livegoalres.py).
// One section at the bottom of each bot's own screen (추세판단 봇 · 레인지 봇 · VWAP 개선판 · 친구 30분 봇 · V3.9 투비트):
//   목표까지     per account of that bot (its paper bot, each executor that follows it): the record, the wallet a win and a
//               loss move, entries a day, and the goal arithmetic (한 달 ×6): the 30-day multiple at this pace, the win rate,
//               the average win and the entries a day ×6 needs, this month against the ×6 path, one verdict line
//   연구 칸      the bot's research questions, each: the question, what the record says now (one line), its numbers, a
//               table, when it can be read, what decision it feeds, how it is measured, a link to the screen that goes deeper
// HONESTY: every number is the server's; arithmetic is labelled 가상 계산 (never a forecast), a small sample says so, a
// source not there says 수집 전 / 못 읽음 with its reason (never a zero), paper money (연습) and real money (진짜 돈) carry
// their own captions; a failed refresh keeps the last answer dimmed with its age.
import {h, put, ui, fmt, motion, serverNow} from "../core/pb.js";

export const GOALRES_API = "/api/v4/livebots/goalres";
const REFRESH_MS = 60 * 1000;
const has = (x) => x != null && Number.isFinite(Number(x));


// ================================================================ pure functions (node tests)
/** One value in a table or a chip by the server's ``fmt``: pct (signed), pct0 (unsigned whole %), pctp (signed %p),
 *  pctneg (a loss share shown as −x%), n, usd, mult, text. Nothing known: "—". */
export function cellKo(v, f) {
  if (f === "text") return v == null || v === "" ? "—" : String(v);
  if (!has(v)) return "—";
  const x = Number(v);
  switch (f) {
    case "pct": return fmt.pct(x, 1);
    case "pct0": return fmt.pct(x, 0, false);
    case "pctp": return `${fmt.pct(x, 1)}p`;
    case "pctneg": return x === 0 ? "0.0%" : `−${fmt.pct(Math.abs(x), 1, false)}`;
    case "n": return fmt.int(x);
    case "usd": return `${x < 0 ? "−" : ""}$${fmt.money(Math.abs(x))}`;
    case "mult": return multKo(x);
    default: return String(v);
  }
}

/** A cell's colour: a signed percentage up / down; the rest none. */
export function cellTone(v, f) {
  if (!has(v) || !["pct", "pctp", "usd"].includes(f)) return "";
  return Number(v) > 0 ? "up" : Number(v) < 0 ? "down" : "";
}

/** A multiple in words: "×1.84"; under ×0.01 "×0.01 미만". */
export const multKo = (m) => (!has(m) ? "—" : m < 0.01 ? "×0.01 미만" : `×${fmt.num(m, 2)}`);

/** The goal card's rows [[label, value, tone]] of one account answer (the server's goal_numbers). */
export function acctRows(a) {
  if (!a || a.state !== "ok") return [];
  const wil = Array.isArray(a.wilson) ? ` (90% 범위 ${fmt.pct(a.wilson[0], 0, false)}~${fmt.pct(a.wilson[1], 0, false)})` : "";
  const g = has(a.growth) ? Math.expm1(Number(a.growth)) : null;
  const rows = [
    ["닫힌 거래", a.n ? `${fmt.int(a.n)}번 · ${fmt.int(a.wins)}승 ${fmt.int(a.losses)}패` : "아직 없음", ""],
    ["승률", has(a.win_rate) ? `${fmt.pct(a.win_rate, 0, false)}${wil}` : "—", ""],
    ["이길 때 잔고", has(a.avg_win) ? `${fmt.pct(a.avg_win, 1)}${has(a.avg_win_roe) ? ` (순ROE ${fmt.pct(a.avg_win_roe, 1)})` : ""}` : "—", has(a.avg_win) ? "up" : ""],
    ["질 때 잔고", has(a.avg_loss) ? `−${fmt.pct(a.avg_loss, 1, false)}${has(a.avg_loss_roe) ? ` (순ROE −${fmt.pct(a.avg_loss_roe, 1, false)})` : ""}` : "—",
      has(a.avg_loss) ? "down" : ""],
    ["거래당 잔고 (복리 평균)", has(g) ? fmt.pct(g, 2) : "—", cellTone(g, "pct")],
    ["하루 진입", has(a.per_day) ? `${fmt.num(a.per_day, 1)}번 (${fmt.num(a.days, 1)}일에 ${fmt.int(a.entries)}번)`
      : `하루가 지나면 계산해요${has(a.entries) ? ` (지금 ${fmt.int(a.entries)}번)` : ""}`, ""],
  ];
  return rows;
}

/** The goal arithmetic rows [[label, value, tone]] (가상 계산): 30 days at this pace, the win rate / average win / entries
 *  a day ×N needs. */
export function needRows(a) {
  if (!a || a.state !== "ok") return [];
  const T = has(a.target) ? `×${fmt.num(a.target, 0)}` : "목표";
  const nw = a.need_win;
  return [
    ["이 속도로 30일이면", multKo(a.pace_mult), has(a.pace_mult) ? (a.pace_mult >= (a.target || 6) ? "up" : a.pace_mult < 1 ? "down" : "") : ""],
    [`${T}에 필요한 승률`, !has(nw) ? "—" : nw > 1 ? "승률 100%여도 모자람" : nw <= 0 ? "지금 이익만으로 넘음" : fmt.pct(nw, 0, false),
      has(nw) && nw > 1 ? "down" : ""],
    [`지금 승률이면 필요한 평균 이익`, has(a.need_avg_win) ? `잔고 ${fmt.pct(a.need_avg_win, 1)}` : "—", ""],
    [`지금 거래당 성장이면 필요한 하루 진입`, has(a.need_per_day) ? `${fmt.num(a.need_per_day, 1)}번` : has(a.growth) && a.growth <= 0 ? "거래가 잃는 중이라 횟수로는 안 돼요" : "—",
      has(a.growth) && a.growth <= 0 ? "down" : ""],
  ];
}

/** This month against the ×N path in words: {ko, tone, at, path} (at / path on a 0..1 log scale of the goal), or null. */
export function monthWords(a) {
  const m = a && a.month;
  if (!m || !has(m.mult)) return null;
  const T = Number(a.target || 6);
  const lg = (x) => (x <= 1 ? 0 : Math.min(1, Math.log(x) / Math.log(T)));
  const ahead = m.mult >= m.path_now;
  return {at: lg(m.mult), path: lg(m.path_now), tone: ahead ? "up" : m.mult < 1 ? "down" : "",
    ko: `이번 달 ${multKo(m.mult)} (${fmt.kst(m.from_ms)}부터) · ×${fmt.num(T, 0)} 경로라면 지금 ${multKo(m.path_now)} → `
      + (ahead ? "경로보다 앞서요" : `경로보다 ${fmt.pct(-m.vs_path, 1, false)} 뒤예요`)};
}

/** The kind caption of an account: real money / practice money / off. */
export const kindKo = (a) => (a.kind === "live" ? (a.real === false ? "실거래 테스트넷" : "실거래 · 진짜 돈") : "모의 · 연습 돈");


// ================================================================ the section
/** goalResSection(ctx, bot): the 목표 연구 section of one bot's screen (trend · range · vwap · mix · v39). */
export function goalResSection(ctx, bot) {
  const st = {d: null, sig: "", okAt: null};
  const stateSlot = h("div", {class: "lgr-state"});
  const head = h("div", {class: "lgr-head"});
  const accts = h("div", {class: "lgr-accts"});
  const items = h("div", {class: "lgr-items"});
  const foot = h("div", {class: "lgr-foot"});
  const body = h("div", {class: "lgr-body"}, head, accts, items, foot);
  const el = h("section", {class: "lgr", "data-goalres-bot": bot, "aria-label": "목표 연구"},
    h("h2", {class: "lgr-title"}, "목표 연구", h("small", {class: "muted"}, " · 두 분 목표(한 달 ×6)에 닿으려면 이 봇에서 무엇을 봐야 하나")), stateSlot, body);

  function acctCard(a) {
    const name = h("div", {class: "lgr-ah"}, h("b", null, a.name_ko || a.id), h("span", {class: ["lgr-kind", a.kind]}, kindKo(a)));
    if (a.state !== "ok") {
      return h("section", {class: ["card", "lgr-acct", "off"]}, name,
        h("p", {class: "lgr-reason"}, a.state === "off" ? (a.reason_ko || "아직 꺼져 있어요") : `${a.state === "error" ? "못 읽음" : "수집 전"} · ${a.reason_ko || ""}`));
    }
    const mw = monthWords(a);
    const pct = (x) => `${Math.round(Math.max(0, Math.min(1, x || 0)) * 1000) / 10}%`;
    return h("section", {class: ["card", "lgr-acct"]}, name,
      h("p", {class: ["lgr-verdict", a.tone || ""]}, a.verdict_ko || ""),
      a.few ? h("div", null, ui.smallSample(a.n, st.d.few_n || 20)) : null,
      h("dl", {class: "lgr-kv"}, acctRows(a).map(([k, v, t]) => h("div", null, h("dt", null, k), h("dd", {class: t}, v)))),
      h("div", {class: "lgr-need"}, h("b", {class: "lgr-need-k"}, "가상 계산 (예측 아님)"),
        h("dl", {class: "lgr-kv"}, needRows(a).map(([k, v, t]) => h("div", null, h("dt", null, k), h("dd", {class: t}, v))))),
      mw ? h("div", {class: "lgr-month"}, h("div", {class: "lgr-mbar", role: "img", "aria-label": mw.ko},
        h("i", {class: mw.tone, style: {width: pct(mw.at)}}), h("em", {style: {left: pct(mw.path)}, title: "×6 경로의 지금 자리"})),
      h("p", {class: ["lgr-mko", mw.tone]}, mw.ko)) : null,
      a.est ? ui.note(`≈ 체결 기록 전이라 지갑 변화로 어림한 거래 ${fmt.int(a.est)}번이 섞여 있어요`) : null,
      a.equity_ko ? ui.note(a.equity_ko) : null,
      a.since_ms != null ? h("small", {class: "muted"}, `${fmt.kst(a.since_ms)}부터 센 기록`) : null);
  }

  function table(t) {
    if (!t || !Array.isArray(t.rows) || !t.rows.length) return null;
    return h("div", {class: "tbl-wrap"}, t.title_ko ? h("b", {class: "lgr-t2"}, t.title_ko) : null,
      h("table", {class: "tbl lgr-t"},
        h("thead", null, h("tr", null, t.cols.map((c, i) => h("th", {class: i ? "" : "l"}, c.label_ko)))),
        h("tbody", null, t.rows.map((r) => h("tr", {class: r.few ? "few" : ""}, t.cols.map((c, i) => h("td", {class: [i ? "num" : "l", cellTone(r[c.key], c.fmt)]},
          cellKo(r[c.key], c.fmt), i === 0 && r.few ? h("small", {class: "muted"}, " (표본 적음)") : null)))))));
  }

  function itemCard(it) {
    const kp = (it.kpis || []).filter((k) => k);
    return h("section", {class: ["card", "lgr-item", it.state !== "ok" ? "off" : ""], "data-item": it.id},
      h("div", {class: "lgr-ih"}, h("h3", null, it.title_ko), it.link ? h("a", {class: "lgr-link", href: it.link}, "자세히 →") : null),
      it.q_ko ? h("p", {class: "lgr-q"}, it.q_ko) : null,
      h("p", {class: ["lgr-lead", it.tone || ""]}, it.state === "ok" ? it.lead_ko || "" : `${it.state === "error" ? "못 읽음" : "수집 전"} · ${it.lead_ko || it.reason_ko || ""}`),
      kp.length ? h("div", {class: "lgr-kpis"}, kp.map((k) => h("div", {class: "lgr-kpi"}, h("span", {class: "k"}, k.label_ko),
        h("b", {class: ["num", k.tone || cellTone(k.value, k.fmt)]}, cellKo(k.value, k.fmt)), k.sub_ko ? h("small", {class: "muted"}, k.sub_ko) : null))) : null,
      table(it.table), table(it.table2),
      it.need_ko ? h("p", {class: "lgr-when"}, h("b", null, "언제 판단: "), it.need_ko) : null,
      it.use_ko ? h("p", {class: "lgr-use"}, h("b", null, "어디에 쓰나: "), it.use_ko) : null,
      it.how_ko ? h("small", {class: "muted lgr-how"}, it.how_ko) : null,
      it.reason ? h("small", {class: "muted"}, it.reason) : null);
  }

  function draw() {
    const d = st.d;
    if (!d) { put(head, motion.shimmer(1)); put(accts, motion.shimmer(2, true)); put(items); put(foot); return; }
    if (d.state !== "ok") {
      put(head, h("p", {class: "lgr-off"}, d.ko || "이 봇의 기록이 아직 없어요", d.reason ? h("small", {class: "muted"}, ` · ${d.reason}`) : null));
      put(accts); put(items); put(foot);
      return;
    }
    put(head, h("p", {class: "lgr-goal"}, h("b", null, (d.goal || {}).ko || "두 분 목표: 한 달 ×6"), h("span", {class: "muted"}, ` · ${d.note_ko || ""}`)));
    put(accts, (d.accounts || []).map(acctCard));
    put(items, (d.items || []).map(itemCard));
    put(foot, (d.links || []).length ? h("p", {class: "lgr-links"}, "더 깊게 보기: ",
      ...(d.links || []).flatMap((l, i) => [i ? " · " : null, h("a", {href: l.href}, l.ko)])) : null);
  }

  async function load() {
    let d;
    try { d = await ctx.api(`${GOALRES_API}?bot=${encodeURIComponent(bot)}`); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      put(stateSlot, st.d ? ui.staleNote(e, st.okAt, () => load()) : ui.errorBox(e, () => load()));
      ui.dim(body, !!st.d);
      throw e;
    }
    if (!ctx.alive()) return;
    st.okAt = serverNow();
    put(stateSlot);
    ui.dim(body, false);
    const sig = JSON.stringify({...d, now_ms: 0});
    if (st.d && sig === st.sig) return;
    st.d = d; st.sig = sig;
    draw();
  }
  draw();
  load().catch(() => {});
  ctx.every(REFRESH_MS, () => load().catch(() => {}), {now: false});
  return el;
}

/** goalresView(ctx): the section alone as a screen (its bot from the query: ?bot=trend|range|vwap|mix|v39). */
export function goalresView(ctx) {
  const q = (ctx.params && ctx.params.query) || {};
  const bot = ["trend", "range", "vwap", "mix", "v39", "bybit"].includes(q.bot) ? q.bot : "trend";
  return {el: h("div", {class: "lgr-page"}, goalResSection(ctx, bot)), set() {}};
}
