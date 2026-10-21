// 실거래 › 재현 비교 (#/expect; owners 10/21 night: the 추세판단 봇 replayed on 7/1~10/20 before it went live): the replay
// (data/trend_replay_0701_1020.json: the bot's exact rules on real Binance 1m bars) next to what the live bot really does
// since its start. Does the live bot behave like the replay, and does the cost problem play out? Read-only, from
// /api/v4/livebots/replayref (dash/more/livereplayref.py; every 60 s):
//   첫 줄        the key sentence (what the replay made before costs, what the costs took: from the file), the replay's
//               window, 가상(재현) vs 실제, each account's mean net ROE a trade, every caveat of the file in small print
//   진입 횟수     entries a weekday: the replay's 1.1 and its weekday histogram against the paper's since the start, the
//               band the replay leaves for that many weekdays (inside / above / below), the weekend apart, day by day
//   깔때기        signals → after the pauses and the chase block → passed the checks → pullback touched → entered, the
//               replay's shares against the paper's (a stage the live records cannot tell says so), where the rest stopped
//   거래 결과     n, win rate, mean / median net ROE, the exits by reason with their median hold: the replay, the paper,
//               each executor; the band the replay leaves for the mean of that many trades (표본 적음 under 20)
//   비용 쪼개기   per trade: before costs → slippage → fees (→ funding) → net as a horizontal waterfall on one scale
//   나눠 보기     by member / coin / side: the replay's count and mean net ROE against one live account's
//   누적         the cumulative net ROE sum by trade number: the replay's 89, the live accounts', the band the replay leaves
// HONESTY: every replay number carries 가상(재현); paper money is 페이퍼(연습), the executors' 실거래 only on mainnet; under
// 20 trades 표본 적음 · 아직 판단 못 함; a value not read is — or 수집 전 / 못 읽음 with why, never a zero; a failed
// refresh keeps the last answer dimmed with its age.
import {h, s, put, ui, fmt, serverNow} from "../core/pb.js";
import {acctKo, sourceState} from "./livebots-kit.js";

export const API = "/api/v4/livebots/replayref";
const REFRESH_MS = 60 * 1000;
const has = (x) => x != null && x !== "" && Number.isFinite(Number(x));
const SIDE = (x) => (Number(x) > 0 ? "롱" : "숏");
const DOW = "일월화수목금토";
const DAY = 24 * 3600 * 1000;
const KST_MS = 9 * 3600 * 1000;
const SPLITS = [["member", "매매법"], ["coin", "코인"], ["side", "방향"]];

// ================================================================ pure (node tests: tests/test_livereplayref.py)
/** A ratio as a signed percent: −0.0492 -> "−4.9%". */
export const pc = (x, dec = 1) => (has(x) ? fmt.pct(Number(x), dec, true) : "—");
/** A cost as percentage points: 0.0448 -> "4.5%p". */
export const pp = (x, dec = 1) => (has(x) ? `${fmt.num(Number(x) * 100, dec)}%p` : "—");
/** A sum of net ROE as signed percentage points: −4.38 -> "−438%p". */
export const psum = (x, dec = 0) => (has(x) ? `${fmt.num(Number(x) * 100, dec, true)}%p` : "—");
/** A cost taken (positive = paid) as it moves the result: 0.0128 -> "−1.3%p", a funding received -> "+0.1%p". */
export function costKo(x) {
  if (!has(x)) return "—";
  const v = Math.round(Number(x) * 1000) / 1000;
  return v > 0 ? `−${pp(v)}` : v < 0 ? `+${pp(-v)}` : pp(0);
}
/** A share 0..1 as a plain percent: "34%". */
export const share = (x, dec = 0) => (has(x) ? fmt.pct(Number(x), dec, false) : "—");
/** Minutes held, in words: 49 -> "49분", 120 -> "2시간", 167 -> "2시간 47분". */
export function holdKo(m) {
  if (!has(m)) return "—";
  const v = Math.round(Number(m));
  if (v < 60) return `${fmt.int(v)}분`;
  const hh = Math.floor(v / 60), mm = v % 60;
  return mm ? `${fmt.int(hh)}시간 ${mm}분` : `${fmt.int(hh)}시간`;
}
/** A KST day's label: "10/22 (목)". */
export const dayKo = (ms) => (has(ms) ? `${fmt.mmdd(ms)} (${DOW[(Math.floor((Number(ms) + KST_MS) / DAY) + 4) % 7]})` : "—");
/** An account's name on this page. */
export function accName(id) {
  if (id === "replay") return "재현 (가상)";
  if (id === "paper") return "페이퍼(연습)";
  return acctKo(id);
}

/** The waterfall of one account's costs on a shared scale [lo, hi]: the steps before → slippage → fees → funding → net,
 *  each {k, ko, v, from, to, left, width} (left / width: fractions of the scale), or null without numbers. */
export function waterfall(c, lo, hi) {
  if (!c || !has(c.before) || !has(c.net)) return null;
  const span = hi - lo || 1;
  const pos = (a, b) => ({left: (Math.min(a, b) - lo) / span, width: Math.abs(a - b) / span});
  const out = [];
  let at = Number(c.before);
  out.push({k: "before", ko: "비용 전", v: at, from: 0, to: at, ...pos(0, at)});
  for (const [k, ko] of [["slip", "미끄러짐"], ["fee", "수수료"], ["funding", "펀딩비"]]) {
    if (!has(c[k])) { out.push({k, ko, v: null, from: null, to: null, left: 0, width: 0}); continue; }
    const nx = at - Number(c[k]);
    out.push({k, ko, v: Number(c[k]), from: at, to: nx, ...pos(at, nx)});
    at = nx;
  }
  out.push({k: "net", ko: "순", v: Number(c.net), from: 0, to: Number(c.net), ...pos(0, Number(c.net))});
  return out;
}
/** The shared scale of several accounts' waterfalls: {lo, hi, zero} (zero: the fraction where 0 is). */
export function waterScale(list) {
  const vals = [0];
  for (const c of list) {
    if (!c || !has(c.before) || !has(c.net)) continue;
    let at = Number(c.before);
    vals.push(at, Number(c.net));
    for (const k of ["slip", "fee", "funding"]) if (has(c[k])) { at -= Number(c[k]); vals.push(at); }
  }
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi - lo < 1e-9) { hi += 0.01; lo -= 0.01; }
  const pad = (hi - lo) * 0.04;
  lo -= pad; hi += pad;
  return {lo, hi, zero: (0 - lo) / (hi - lo)};
}

/** 진입 횟수 per count of a day: [{k, replay: {days, share}, live: {days, share}}] over 0..max (the live side counts the
 *  whole weekdays only). */
export function histRows(rep, live) {
  const r = new Map((rep || []).map(([k, v]) => [Number(k), Number(v)]));
  const l = new Map((live || []).map(([k, v]) => [Number(k), Number(v)]));
  const rn = [...r.values()].reduce((a, b) => a + b, 0), ln = [...l.values()].reduce((a, b) => a + b, 0);
  const top = Math.max(0, ...r.keys(), ...[...l].filter(([, v]) => v > 0).map(([k]) => k));
  return Array.from({length: top + 1}, (_, k) => ({k, replay: {days: r.get(k) || 0, share: rn ? (r.get(k) || 0) / rn : null},
    live: {days: l.get(k) || 0, share: ln ? (l.get(k) || 0) / ln : null}}));
}

/** The weekdays since the start in words: "평일 2.5일", under one day "평일 3시간" / "평일 30분" (never "0.0일"). */
export function weekdaysKo(d) {
  if (!has(d)) return "평일 —";
  const x = Number(d);
  if (x >= 1) return `평일 ${fmt.num(x, 1)}일`;
  const m = x * 24 * 60;
  return m < 60 ? `평일 ${Math.round(m)}분` : `평일 ${Math.round(m / 60)}시간`;
}
/** The entries scale: {max, lo, hi, mean, live} as fractions of 0..max (the band, the replay's mean, the live count). */
export function entryScale(band, live) {
  if (!band) return null;
  const max = Math.max(1, Number(band.hi) + 1, Number(live) + 1, Math.ceil(Number(band.mean) || 0));
  const f = (x) => Math.max(0, Math.min(1, Number(x) / max));
  return {max, lo: f(band.lo), hi: f(band.hi), mean: f(band.mean), live: f(live)};
}

/** A mean net ROE against its band on a scale around both: {lo, hi, band: [l, r], mark, ref} (fractions). */
export function bandScale(band, mean, ref) {
  if (!band || !has(mean)) return null;
  const vals = [band[0], band[1], Number(mean), has(ref) ? Number(ref) : band[0], 0];
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = (hi - lo) * 0.08 || 0.01;
  lo -= pad; hi += pad;
  const f = (x) => (Number(x) - lo) / (hi - lo);
  return {lo, hi, band: [f(band[0]), f(band[1])], mark: f(mean), ref: has(ref) ? f(ref) : null, zero: f(0)};
}

/** The cumulative lines in a W x H box up to trade ``upto``: {n, paths: {id: d}, band, zero, lo, hi, last: {id: v}}. */
export function curveModel(c, W, H, upto) {
  if (!c || !c.replay) return null;
  const lines = [["replay", c.replay], ["paper", c.paper || []], ...Object.entries(c.execs || {})];
  const longest = Math.max(...lines.map(([, v]) => v.length)) - 1;
  const n = Math.max(1, Math.min(longest, has(upto) ? Number(upto) : longest));
  const cut = lines.map(([id, v]) => [id, v.slice(0, n + 1)]);
  const blo = ((c.band || {}).lo || []).slice(0, n + 1), bhi = ((c.band || {}).hi || []).slice(0, n + 1);
  const all = [0, ...cut.flatMap(([, v]) => v), ...blo, ...bhi].filter(has).map(Number);
  let lo = Math.min(...all), hi = Math.max(...all);
  if (hi - lo < 1e-9) { hi += 0.05; lo -= 0.05; }
  const pad = (hi - lo) * 0.06;
  lo -= pad; hi += pad;
  const X = (i) => (i / n) * W, Y = (v) => H - ((v - lo) / (hi - lo)) * H;
  const path = (v) => (v.length < 2 ? "" : v.map((y, i) => `${i ? "L" : "M"}${X(i).toFixed(1)} ${Y(y).toFixed(1)}`).join(" "));
  const paths = Object.fromEntries(cut.map(([id, v]) => [id, path(v)]));
  const band = blo.length > 1 && bhi.length === blo.length
    ? `${bhi.map((y, i) => `${i ? "L" : "M"}${X(i).toFixed(1)} ${Y(y).toFixed(1)}`).join(" ")} `
      + `${blo.map((y, i) => [i, y]).reverse().map(([i, y]) => `L${X(i).toFixed(1)} ${Y(y).toFixed(1)}`).join(" ")} Z` : "";
  const last = Object.fromEntries(cut.map(([id, v]) => [id, v.length > 1 ? v[v.length - 1] : null]));
  const count = Object.fromEntries(cut.map(([id, v]) => [id, Math.max(0, v.length - 1)]));
  return {n, paths, band, zero: Y(0), lo, hi, last, count, end: {lo: blo[blo.length - 1], hi: bhi[bhi.length - 1]}};
}

/** The most closed trades of a live account on the cumulative lines. */
export const liveCount = (c) => Math.max(0, ((c && c.paper) || []).length - 1, ...Object.values((c && c.execs) || {}).map((v) => v.length - 1));

/** The page's headline: how many live trades and how far to trust them. */
export function headline(d) {
  if (!d || d.state !== "ok") return "재현 비교 기록을 기다리는 중";
  const n = ((d.results || {}).paper || {}).n || 0;
  const small = d.small_n || 20;
  if (!n) return "실제(페이퍼) 거래가 아직 없어요 · 재현 숫자만 먼저 보여 드려요";
  return `실제(페이퍼) 거래 ${fmt.int(n)}번 · ${n < small ? "표본 적음 · 아직 판단 못 함" : n < 40 ? "아직 적은 편 (40번부터 조금 더 믿을 만)" : "견줄 만한 수"}`;
}

// ================================================================ the view
/** expectView(ctx, hub) -> {el, set()}: its own endpoint every 60 s (the summary is not needed here). */
export function expectView(ctx) {
  const st = {d: null, okAt: 0, busy: false, sig: "", split: "member", acct: "paper", zoom: "all", zoomPicked: false};
  const stateSlot = h("div", {class: "lb-slot"});
  // the first block
  const kick = h("p", {class: "lex-kick"}, "재현 비교 · 추세판단 봇 · 가상(재현) vs 실제");
  const head = h("h2", {class: "lex-head"}, "불러오는 중");
  const hsub = h("p", {class: "lex-hsub"});
  const win = h("p", {class: "lex-win"});
  const tiles = h("div", {class: "lex-tiles", role: "list", "aria-label": "거래당 순ROE"});
  const honest = h("ul", {class: "lex-honest", "aria-label": "재현 결과를 볼 때 알아 둘 것"});
  const hero = h("section", {class: "lex-hero", "aria-label": "재현 비교"},
    h("div", {class: "lex-hmain"}, kick, head, hsub, win), tiles, honest);
  // the cards
  const entBox = h("div", {class: "lex-ent"});
  const funBox = h("div", {class: "lex-fun"});
  const resBox = h("div", {class: "lex-res"});
  const costBox = h("div", {class: "lex-cost"});
  const splitSeg = ui.seg(SPLITS.map(([id, label]) => ({id, label})), "member", (id) => { st.split = id; drawSplit(); }, {label: "나눠 보기"});
  const acctSlot = h("div", {class: "lex-acctseg"});
  const splitBox = h("div", {class: "lex-split"});
  const zoomSeg = ui.seg([{id: "all", label: "전체"}, {id: "live", label: "실제 거래 수만큼"}], "all",
    (id) => { st.zoom = id; drawCurve(); }, {label: "누적 선 범위"});
  const curveBox = h("div", {class: "lex-curve"});
  const cards = h("div", {class: "lex-cards"},
    ui.card({title: "진입 횟수", sub: "평일 하루에 몇 번 들어가나 · 재현은 평일 80일, 실제는 새 규칙 시작 뒤 (한국 시간)", cls: "lex-ecard"}, entBox),
    ui.card({title: "깔때기", sub: "신호가 진입까지 얼마나 남나 · 신호 수에 대한 비율", cls: "lex-fcard"}, funBox),
    ui.card({title: "거래 결과", sub: "순ROE = 수수료·미끄러짐 뺀 손익 ÷ 증거금 · 이긴 거래 = 순손익이 0보다 큼", cls: "lex-rcard"}, resBox),
    ui.card({title: "비용 쪼개기", sub: "거래 한 번 평균: 비용 전 → 미끄러짐 → 수수료 → 펀딩비 → 순", cls: "lex-ccard",
      acts: [ui.pill("핵심", "accent", "재현에서 손실은 대부분 비용에서 나왔어요: 실제도 그런지 보는 칸")]}, costBox),
    h("div", {class: "lex-two"},
      ui.card({title: "나눠 보기", sub: "거래 수와 거래당 평균 순ROE · 한 칸 20번 미만은 대부분 운", cls: "lex-scard"},
        h("div", {class: "lex-segs"}, splitSeg, acctSlot), splitBox),
      ui.card({title: "누적 순ROE", sub: "거래 번호대로 더한 순ROE · 띠 = 재현이라면 보통 이 범위 (5~95%)", cls: "lex-kcard"},
        zoomSeg, curveBox)));
  const foot = h("div", {class: "lb-foot"},
    ui.assumeLine(["closed"], "페이퍼(연습) 손익은 진짜 돈이 아니에요 · 재현 = 지난 기간을 규칙 그대로 다시 계산한 가상 결과(실제 체결 아님)"),
    ui.assumeLive("바이비트 · WOO X Pro: 새 규칙 시작 뒤 들어간 거래만 셈 · 실제 돈은 실행기가 메인넷일 때만"));
  const body = h("div", {class: "lex-body"}, hero, cards, foot);
  const el = h("div", {class: "lex stack"}, stateSlot, body);

  // ---------------------------------------------------------------- parts
  const accounts = () => {
    const d = st.d, r = d.results || {};
    return [{id: "replay", rec: r.replay, cost: (d.costs || {}).replay, state: "ok"},
      {id: "paper", rec: r.paper, cost: (d.costs || {}).paper, state: "ok"},
      ...(r.execs || []).map((x) => ({id: x.id, rec: x.record, cost: x.costs, state: x.state, x}))];
  };
  const kindPill = (a) => {
    if (a.id === "replay") return ui.pill("가상 · 재현", "warn", "지난 7/1~10/20을 규칙 그대로 다시 계산한 결과 (실제 체결 아님)");
    if (a.id === "paper") return ui.pill("실제 · 페이퍼(연습)", "thin", "실제로 돌고 있는 페이퍼 봇 (모의 돈)");
    const x = a.x || {};
    if (x.state !== "ok") return ui.pill("실거래", "thin");
    if (!x.real) return ui.pill(`실행기 · ${x.mode || "모드 모름"}`, "thin", "메인넷이 아니라 진짜 돈이 아니에요");
    return ui.pill("실거래 · 진짜 돈", "bad", "거래소 실제 체결 기록");
  };
  function drawHero() {
    const d = st.d;
    head.textContent = headline(d);
    if (!d || d.state !== "ok") { put(hsub); put(win); put(tiles); put(honest); return; }
    hsub.textContent = "새 규칙이 재현(가상)처럼 가고 있나요? · 핵심은 아래 비용 쪼개기";
    const ref = d.ref || {};
    const w = ref.window_kst || [];
    put(win, ui.pill("가상(재현)", "warn"), ` ${w[0] || "—"} ~ ${w[1] || "—"} (한국 시간) · 바이낸스 1분봉으로 규칙 그대로 다시 돌린 결과   `,
      ui.pill("실제", "accent"), ` 새 규칙 시작 ${fmt.kst(d.since)} 뒤 · 페이퍼와 두 실행기`);
    put(tiles, accounts().map((a) => {
      const r = a.rec || {};
      if (a.state !== "ok") {
        return h("div", {class: ["lex-tile", "na", "lex-a-" + a.id], role: "listitem"}, h("span", {class: "lex-tk"}, accName(a.id)),
          h("b", {class: "lex-tv"}, a.state === "missing" ? "수집 전" : "못 읽음"), h("span", {class: "lex-ts"}, (a.x || {}).reason_ko || ""));
      }
      return h("div", {class: ["lex-tile", "lex-a-" + a.id], role: "listitem"},
        h("span", {class: "lex-tk"}, h("i", {class: "lex-sw", "aria-hidden": "true"}), accName(a.id)),
        h("b", {class: ["lex-tv", "num", r.n ? fmt.tone(r.roe_mean, pc(r.roe_mean)) : ""]}, r.n ? pc(r.roe_mean) : "거래 없음"),
        h("span", {class: "lex-ts"}, r.n ? `거래당 평균 순ROE · ${fmt.int(r.n)}번${a.id !== "replay" && r.small ? " · 표본 적음" : ""}` : "새 규칙 뒤 닫힌 거래 없음"),
        kindPill(a));
    }));
    put(honest, h("li", {class: "lex-what"}, ref.what || ""), (ref.honest_ko || []).map((t) => h("li", null, t)));
  }

  function drawEntries() {
    const e = st.d.entries || {};
    const rep = e.replay || {}, live = e.live || {}, band = e.band;
    const sc = entryScale(band, live.entries);
    const big = (k, v, sub, cls) => h("div", {class: ["lex-big", cls]}, h("span", {class: "lex-bk"}, k), h("b", {class: "num"}, v), h("small", null, sub));
    const rows = histRows(rep.hist, live.hist);
    const topShare = Math.max(0.01, ...rows.flatMap((r) => [r.replay.share || 0, r.live.share || 0]));
    put(entBox,
      h("div", {class: "lex-bigs"},
        big("재현 (가상) · 평일 하루", has(rep.per_weekday) ? `${fmt.num(rep.per_weekday, 2)}번` : "—",
          `평일 ${fmt.int(rep.weekdays)}일 · ${fmt.int(rep.entries)}번 · 가운데 ${fmt.num(rep.median, 0)}번 · 가장 많은 날 ${fmt.int(rep.max)}번`, "replay"),
        big("실제 (페이퍼) · 평일 하루", has(live.per_weekday) && live.weekdays >= 1 ? `${fmt.num(live.per_weekday, 2)}번` : "—",
          `${weekdaysKo(live.weekdays)} · ${fmt.int(live.entries)}번${live.weekdays < 1 ? " (평일 하루가 다 지나면 하루 평균을 셈)" : ""}`
          + `${live.src === "trades" ? " · 진입 기록 표가 없어 거래로 셈" : ""}`, "live")),
      sc ? h("div", {class: ["lex-escale", band.where || ""]},
        h("div", {class: "lex-eline", role: "img", "aria-label": `재현이라면 보통 ${band.lo}~${band.hi}번 · 실제 ${live.entries}번`},
          h("span", {class: "lex-eband", style: {left: `${(sc.lo * 100).toFixed(2)}%`, width: `${(Math.max(0.006, sc.hi - sc.lo) * 100).toFixed(2)}%`}}),
          h("span", {class: "lex-emean", style: {left: `${(sc.mean * 100).toFixed(2)}%`}, title: `재현 평균 ${fmt.num(band.mean, 1)}번`}),
          h("span", {class: "lex-emark", style: {left: `${(sc.live * 100).toFixed(2)}%`}, title: `실제 ${live.entries}번`})),
        h("div", {class: "lex-ekeys num"}, h("span", null, "0번"), h("span", null, `${fmt.int(sc.max)}번`)),
        h("p", {class: "lex-say"}, h("b", null, e.ko || ""),
          h("small", null, ` · 띠 = 재현의 평일 80일로 같은 날 수를 계산한 5~95% 범위 (하루 안에서는 고르게 나온다고 침) · 세로선 = 재현 평균 ${fmt.num(band.mean, band.mean < 1 ? 2 : 1)}번`)))
        : h("p", {class: "lex-say"}, e.ko || "아직 견줄 수 없어요"),
      h("p", {class: ["lex-note", live.weekend_entries ? "warn" : ""]}, e.weekend_ko || ""),
      h("h3", {class: "lex-h3"}, "하루에 몇 번? (평일)"),
      h("div", {class: "lex-hist", role: "table", "aria-label": "평일 하루 진입 횟수별 날 수"},
        h("div", {class: "lex-hrow lex-hhead", role: "row"}, ["", "재현 (가상)", "실제 (평일 하루 전체)"].map((k) => h("span", {role: "columnheader"}, k))),
        rows.map((r) => h("div", {class: "lex-hrow", role: "row"},
          h("span", {class: "lex-hk num", role: "rowheader"}, `${r.k}번`),
          h("span", {class: "lex-hbar replay", role: "cell"}, h("i", {style: {"--v": ((r.replay.share || 0) / topShare).toFixed(4)}}),
            h("small", {class: "num"}, `${fmt.int(r.replay.days)}일 · ${share(r.replay.share)}`)),
          h("span", {class: "lex-hbar live", role: "cell"}, live.full_weekdays ? [h("i", {style: {"--v": ((r.live.share || 0) / topShare).toFixed(4)}}),
            h("small", {class: "num"}, `${fmt.int(r.live.days)}일 · ${share(r.live.share)}`)] : h("small", null, "—"))))),
      live.full_weekdays ? null : ui.note("실제 쪽은 하루 전체가 지난 평일만 세요 · 아직 그런 평일이 없어요"),
      (live.days || []).length ? h("div", {class: "lex-days", role: "list", "aria-label": "하루하루 진입"},
        live.days.slice(-14).map((x) => h("span", {class: ["lex-day", x.weekend ? "wk" : "", x.today ? "today" : "", x.n ? "has" : ""], role: "listitem",
          title: x.weekend ? "주말 (쉬는 규칙)" : x.frac < 0.999 ? `하루 중 ${share(x.frac)}만 지남` : "평일"},
        h("small", null, dayKo(x.d0)), h("b", {class: "num"}, `${fmt.int(x.n)}번`), x.today ? h("small", null, "오늘") : null))) : null,
      (rep.by_month || []).length ? h("p", {class: "lex-note"}, "재현 달마다 평일 하루: ",
        rep.by_month.map((m, i) => [i ? " · " : "", `${Number(String(m.month).slice(5))}월 `, h("b", {class: "num"}, `${fmt.num(m.per_weekday, 2)}번`)])) : null);
  }

  function drawFunnel() {
    const f = st.d.funnel || {};
    const rep = f.replay || [], live = f.live;
    const bar = (x, cls) => h("span", {class: ["lex-fbar", cls]}, h("i", {style: {"--v": has(x.share) ? Math.min(1, Math.max(0.004, Number(x.share))).toFixed(4) : "0"}}),
      h("small", {class: "num"}, x.n == null ? (x.why_ko || "모름") : `${fmt.int(x.n)} · ${has(x.share) ? fmt.pct(x.share, x.share < 0.1 ? 1 : 0, false) : "—"}`));
    const blocked = (list, top) => (list || []).map((b) => `${b.ko} ${fmt.int(b.n)}${top ? ` (${fmt.pct(b.n / top, b.n / top < 0.1 ? 1 : 0, false)})` : ""}`).join(" · ");
    put(funBox,
      h("div", {class: "lex-ftbl", role: "table", "aria-label": "깔때기"},
        h("div", {class: "lex-frow lex-fhead", role: "row"}, ["단계", "재현 (가상)", "실제 (페이퍼)", "앞 단계에서 남음"].map((k) => h("span", {role: "columnheader"}, k))),
        rep.map((x, i) => {
          const y = live ? live[i] : null;
          return h("div", {class: "lex-frow", role: "row"},
            h("span", {class: "lex-fk", role: "rowheader"}, x.ko),
            h("span", {role: "cell"}, bar(x, "replay")),
            h("span", {role: "cell"}, y ? bar(y, "live") : h("small", {class: "lex-mute"}, f.reason_ko || "수집 전")),
            h("span", {class: "lex-fprev num", role: "cell"}, i ? `${has(x.of_prev) ? fmt.pct(x.of_prev, 0, false) : "—"} / ${y && has(y.of_prev) ? fmt.pct(y.of_prev, 0, false) : "—"}` : "재현 / 실제"));
        })),
      live && live[0] && live[0].n < 200 ? ui.note(`실제 신호가 아직 ${fmt.int(live[0].n)}개라 비율이 크게 흔들려요 · 주말이 끼면 '쉬는 시간' 비율이 달라져요`) : null,
      h("p", {class: "lex-blk"}, h("b", null, "재현에서 걸린 곳: "), blocked(f.replay_blocked, rep[0] && rep[0].n) || "—"),
      live ? h("p", {class: "lex-blk"}, h("b", null, "실제에서 걸린 곳: "), blocked(f.live_blocked, live[0] && live[0].n) || "아직 없음") : null,
      f.skipped && has(f.skipped.live) ? h("p", {class: "lex-note"},
        `되돌림에 닿았지만 이미 포지션이 있어 못 탄 신호: 재현 ${fmt.int(f.skipped.replay)}개 · 실제 ${fmt.int(f.skipped.live)}개`) : null);
  }

  function exitBar(rec) {
    const ex = (rec && rec.exits) || [];
    return h("div", {class: "lex-xbar", role: "img", "aria-label": ex.map((x) => `${x.ko} ${x.n}번`).join(" · ") || "청산 없음"},
      ex.map((x) => h("i", {class: "lex-x-" + x.id, style: {"--v": Number(x.share).toFixed(4)}, title: `${x.ko} ${x.n}번`})));
  }
  function resCard(a, replay) {
    const r = a.rec;
    const name = h("div", {class: "lex-rhead"}, h("i", {class: "lex-sw", "aria-hidden": "true"}), h("b", null, accName(a.id)), kindPill(a));
    if (a.state !== "ok") {
      return h("article", {class: ["lex-rbox", "na", "lex-a-" + a.id]}, name, sourceState(a.x, accName(a.id)));
    }
    if (!r || !r.n) {
      return h("article", {class: ["lex-rbox", "lex-a-" + a.id]}, name, h("p", {class: "lex-empty"}, "새 규칙 뒤 닫힌 거래가 아직 없어요"));
    }
    const v = r.verdict || {};
    const sc = a.id === "replay" ? null : bandScale(r.band, r.roe_mean, replay && replay.roe_mean);
    return h("article", {class: ["lex-rbox", "lex-a-" + a.id, a.id === "replay" ? "ref" : ""]}, name,
      a.x && a.x.other_paper ? h("p", {class: "lex-note warn"}, "이 실행기는 지금 다른 페이퍼를 따라가요 (짝 거래·청산 이유는 그 페이퍼 기준)") : null,
      h("dl", {class: "lex-nums"},
        h("div", null, h("dt", null, "거래"), h("dd", {class: "num"}, `${fmt.int(r.n)}번`, r.estimated ? h("small", null, ` (${fmt.int(r.estimated)}번 어림)`) : null)),
        h("div", null, h("dt", null, "이긴 비율"), h("dd", {class: "num"}, share(r.win_rate), h("small", null, ` ${fmt.int(r.wins)}승`))),
        h("div", null, h("dt", null, "평균 순ROE"), h("dd", {class: ["num", fmt.tone(r.roe_mean, pc(r.roe_mean))]}, pc(r.roe_mean))),
        h("div", null, h("dt", null, "가운데 순ROE"), h("dd", {class: ["num", fmt.tone(r.roe_median, pc(r.roe_median))]}, pc(r.roe_median))),
        h("div", null, h("dt", null, "가운데 보유"), h("dd", {class: "num"}, holdKo(r.hold_med)))),
      exitBar(r),
      h("ul", {class: "lex-xlist"}, (r.exits || []).map((x) => h("li", null, h("i", {class: "lex-x-" + x.id, "aria-hidden": "true"}),
        h("span", null, x.ko), h("b", {class: "num"}, `${fmt.int(x.n)}번`), h("small", {class: "num"}, ` ${share(x.share)}`),
        h("small", {class: ["num", fmt.tone(x.roe_mean, pc(x.roe_mean))]}, ` · 평균 ${pc(x.roe_mean)}`), h("small", {class: "num"}, ` · 가운데 ${holdKo(x.hold_med)}`)))),
      sc ? h("div", {class: ["lex-band", v.kind || ""]},
        h("div", {class: "lex-bline", role: "img", "aria-label": `재현이라면 ${r.n}번 평균이 보통 ${pc(r.band[0])}~${pc(r.band[1])} · 지금 ${pc(r.roe_mean)}`},
          h("span", {class: "lex-bband", style: {left: `${(sc.band[0] * 100).toFixed(2)}%`, width: `${(Math.max(0.006, sc.band[1] - sc.band[0]) * 100).toFixed(2)}%`}}),
          has(sc.ref) ? h("span", {class: "lex-bref", style: {left: `${(sc.ref * 100).toFixed(2)}%`}, title: `재현 전체 평균 ${pc(replay.roe_mean)}`}) : null,
          h("span", {class: "lex-bmark", style: {left: `${(sc.mark * 100).toFixed(2)}%`}, title: `지금 ${pc(r.roe_mean)}`})),
        h("div", {class: "lex-ekeys num"}, h("span", null, pc(sc.lo)), h("span", null, pc(sc.hi))),
        h("p", {class: "lex-say"}, h("b", null, v.ko || ""), v.kind === "small" && v.where
          ? h("small", null, ` · 지금은 재현 범위(${pc(r.band[0])}~${pc(r.band[1])}) ${v.where === "inside" ? "안" : v.where === "above" ? "위" : "아래"}`) : null))
        : a.id === "replay" ? null : h("p", {class: "lex-say"}, v.ko || ""));
  }
  function drawResults() {
    const list = accounts();
    const rep = (st.d.results || {}).replay;
    put(resBox, h("div", {class: "lex-rgrid"}, list.map((a) => resCard(a, rep))),
      h("p", {class: "lex-note"}, (st.d.results || {}).band_how_ko || "", " · 세로선 = 재현 전체 평균 · 점 = 지금"),
      rep && rep.file && !rep.file.judge_exits ? h("p", {class: "lex-note"}, "재현에는 감독: 추세 뒤집힘 청산이 한 번도 없었어요 (실제에서 나오면 새로 보는 것)") : null);
  }

  function drawCosts() {
    const list = accounts();
    const sc = waterScale(list.map((a) => a.cost));
    const c = st.d.costs || {};
    const rows = list.map((a) => {
      const w = a.state === "ok" ? waterfall(a.cost, sc.lo, sc.hi) : null;
      const x = a.cost || {};
      const name = h("div", {class: "lex-whead"}, h("i", {class: "lex-sw", "aria-hidden": "true"}), h("b", null, accName(a.id)),
        h("small", null, a.state !== "ok" ? "" : a.id === "replay" ? ` ${fmt.int(x.n)}번 평균` : x.n ? ` ${fmt.int(x.n)}번 평균${x.of > x.n ? ` (닫힌 ${fmt.int(x.of)}번 중 비용을 잰 것)` : ""}${x.small ? " · 표본 적음" : ""}` : ""), kindPill(a));
      if (!w) {
        const why = a.state !== "ok" ? ((a.x || {}).reason_ko || "못 읽음") : !x.of ? "새 규칙 뒤 닫힌 거래가 아직 없어요" : "체결 기록으로 비용을 잰 거래가 아직 없어요";
        return h("div", {class: ["lex-wbox", "na", "lex-a-" + a.id]}, name, h("p", {class: "lex-empty"}, why));
      }
      return h("div", {class: ["lex-wbox", "lex-a-" + a.id]}, name,
        h("div", {class: "lex-wsteps", role: "list"}, w.map((p) => h("div", {class: ["lex-wrow", "k-" + p.k], role: "listitem"},
          h("span", {class: "lex-wk"}, p.ko),
          h("span", {class: "lex-wtrack"}, h("span", {class: "lex-wzero", style: {left: `${(sc.zero * 100).toFixed(2)}%`}}),
            p.v == null ? null : h("i", {class: ["lex-wbar", p.k === "before" || p.k === "net" ? fmt.tone(p.v, pc(p.v)) || "flat" : "cost"],
              style: {left: `${(p.left * 100).toFixed(2)}%`, width: `${(Math.max(0.004, p.width) * 100).toFixed(2)}%`}})),
          h("span", {class: ["lex-wv", "num", p.k === "before" || p.k === "net" ? fmt.tone(p.v, pc(p.v)) : ""]},
            p.v == null ? (a.id === "replay" && p.k === "funding" ? "계산 안 함" : "—")
              : p.k === "before" || p.k === "net" ? pc(p.v) : costKo(p.v))))));
    });
    const live = [["paper", c.paper_ko, false], ...((st.d.results || {}).execs || []).map((x) => [x.id, x.costs_ko, !!x.real])]
      .filter(([, t]) => t);
    put(costBox, h("p", {class: "lex-key"}, c.ko || ""),
      h("div", {class: "lex-wgrid"}, rows),
      h("p", {class: "lex-note"}, `막대는 모든 칸이 같은 눈금 (${pc(sc.lo)} ~ ${pc(sc.hi)}) · 가는 세로선 = 0 · 빗금 = 비용`),
      h("ul", {class: "lex-wlive"}, live.map(([id, t, real]) => h("li", null, h("b", null, `${accName(id)}${real ? " (진짜 돈)" : ""}: `), t))),
      ui.note(c.paper_slip_ko || "", " · ", c.exec_before_ko || "", " · 재현은 펀딩비를 넣지 않았어요"));
  }

  function drawSplit() {
    const d = st.d;
    if (!d || d.state !== "ok") return;
    const live = accounts().filter((a) => a.id !== "replay" && a.state === "ok");
    if (!live.some((a) => a.id === st.acct)) st.acct = "paper";
    put(acctSlot, live.length > 1 ? ui.seg(live.map((a) => ({id: a.id, label: accName(a.id)})), st.acct,
      (id) => { st.acct = id; drawSplit(); }, {label: "실제 쪽 계좌"}) : null);
    const rows = ((d.split || {})[st.split]) || [];
    const name = (r) => {
      if (r.id == null) return h("span", {class: "lex-mute"}, st.split === "member" ? "짝 페이퍼 거래 없음" : "모름");
      if (st.split === "member") return h("span", null, fmt.stratKo(r.strategy), h("small", null, ` ${fmt.tfKo(r.tf)}${r.role ? ` · ${r.role}` : ""}`));
      if (st.split === "coin") return fmt.coin(r.id);
      return SIDE(r.id);
    };
    const cell = (x, small) => (x && x.n ? [h("b", {class: "num"}, `${fmt.int(x.n)}번`), h("span", {class: ["num", fmt.tone(x.mean, pc(x.mean))]}, ` ${pc(x.mean)}`),
      small && x.n < (d.small_n || 20) ? h("small", {class: "lex-mute", title: "20번 미만: 대부분 운"}, " 적음") : null] : h("span", {class: "lex-mute"}, "없음"));
    put(splitBox, rows.length ? h("div", {class: "lex-stbl", role: "table", "aria-label": "나눠 보기"},
      h("div", {class: "lex-srow lex-shead", role: "row"}, ["", "재현 (가상)", `실제 · ${accName(st.acct)}`].map((k) => h("span", {role: "columnheader"}, k))),
      rows.map((r) => h("div", {class: ["lex-srow", (r[st.acct] || {}).n ? "" : "zero"], role: "row"},
        h("span", {class: "lex-sname", role: "rowheader"}, name(r)),
        h("span", {role: "cell"}, cell(r.replay, false)),
        h("span", {role: "cell"}, cell(r[st.acct], true)))))
      : ui.empty("나눠 볼 거래가 없어요"));
  }

  function drawCurve() {
    const d = st.d;
    if (!d || d.state !== "ok") return;
    const c = d.curve || {};
    const upto = st.zoom === "live" ? Math.max(10, liveCount(c)) : null;
    const W = 600, H = 200;
    const m = curveModel(c, W, H, upto);
    if (!m) { put(curveBox, ui.empty("재현 숫자가 없어요")); return; }
    const ids = ["replay", "paper", ...Object.keys(c.execs || {})];
    const lastKo = (id) => (m.count[id] ? `${psum(m.last[id])} (${fmt.int(m.count[id])}번)` : "거래 없음");
    put(curveBox,
      h("div", {class: "lex-ckeys"}, ids.map((id) => h("span", {class: "lex-a-" + id}, h("i", {"aria-hidden": "true"}), `${accName(id)} `,
        h("b", {class: ["num", m.count[id] ? fmt.tone(m.last[id], pc(m.last[id])) : ""]}, lastKo(id)))),
        h("span", {class: "lex-bandk"}, h("i", {"aria-hidden": "true"}), `재현이라면 ${fmt.int(m.n)}번째에 보통 ${psum(m.end.lo)} ~ ${psum(m.end.hi)}`)),
      h("div", {class: "lex-plot"},
        h("div", {class: "lex-yax", "aria-hidden": "true"}, h("span", {class: "num top"}, psum(m.hi)),
          m.zero / H > 0.18 && m.zero / H < 0.82 ? h("span", {class: "num", style: {top: `${((m.zero / H) * 100).toFixed(2)}%`}}, "0") : null,
          h("span", {class: "num bot"}, psum(m.lo))),
        h("div", {class: "lex-svgbox"}, s("svg", {class: "lex-svg", viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img",
          "aria-label": `누적 순ROE: ${ids.map((id) => `${accName(id)} ${lastKo(id)}`).join(" · ")}`},
        m.band ? s("path", {class: "lex-cband", d: m.band}) : null,
        s("line", {class: "lex-zero", x1: 0, x2: W, y1: m.zero.toFixed(1), y2: m.zero.toFixed(1)}),
        ids.map((id) => (m.paths[id] ? s("path", {class: ["lex-line", "lex-l-" + id], d: m.paths[id]}) : null))))),
      h("div", {class: "lex-xlab num"}, h("span", null, "0번"), h("span", null, `${fmt.int(m.n)}번째 거래`)),
      ui.note("재현 선은 지난 기간에 실제로 나온 순서 하나예요 · 띠는 재현 거래를 다시 뽑아 본 범위라 실제 선이 띠 안이면 '재현과 비슷하게 가는 중'"));
  }

  function draw() {
    const d = st.d;
    drawHero();
    if (!d || d.state !== "ok") {
      cards.hidden = true;
      put(stateSlot, d && d.state === "off" ? h("div", {class: "lb-state"}, ui.pill("꺼짐", "thin"), h("span", null, ` ${d.reason_ko}`))
        : sourceState(d, "재현 비교"));
      return;
    }
    cards.hidden = false;
    put(stateSlot);
    if (!st.zoomPicked) {                       // the first answer: a few live trades are seen only zoomed to their count
      st.zoomPicked = true;
      const n = liveCount(d.curve || {});
      if (n > 0 && n < ((d.curve || {}).replay || []).length - 1) { st.zoom = "live"; zoomSeg.set("live"); }
    }
    drawEntries(); drawFunnel(); drawResults(); drawCosts(); drawSplit(); drawCurve();
  }

  async function load() {
    if (st.busy) return;
    st.busy = true;
    let d;
    try { d = await ctx.api(API); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      if (st.d) { put(stateSlot, ui.staleNote(e, st.okAt, () => load().catch(() => {}))); ui.dim(body, true); }
      else put(stateSlot, ui.errorBox(e, () => load()));
      throw e;
    } finally { st.busy = false; }
    if (!ctx.alive()) return;
    ui.dim(body, false);
    st.okAt = serverNow();
    const sig = JSON.stringify({...d, now_ms: 0});
    if (st.d && sig === st.sig) { put(stateSlot); return; }      // the same records: nothing redrawn
    st.d = d; st.sig = sig;
    draw();
  }
  draw();
  load().catch(() => {});
  ctx.every(REFRESH_MS, () => load().catch(() => {}), {now: false});
  if (ctx.watch) ctx.watch("board", () => { if (st.d && st.d.state === "ok") drawSplit(); });     // the strategies' Korean names
  return {el, set() {}};
}
