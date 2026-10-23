// 실거래 › 진입 근거 (owners 10/20 "진입하면 왜 진입했는지 어떤 근거로 진입했는지 대시보드에 보여?" → "응 만들어줘"): one entry's
// reasons, opened from a position card (livebots-pos.js) or a closed trade (livebots-trades.js; a live trade shows the paper
// entry it followed). GET /api/v4/livebots/why (dash/more/livewhy.py), asked when the panel is first opened:
//   1 신호        the setting (number, A / B group, entry mode, stop), the strategy and its timeframe, the signal bar, where
//                the signal came from, the reference price → the fill and the delay, the entry strength score
//   2 매매법 조건  the strategy's own entry conditions on the signal bar ✓ / ✗ and its indicator values there (worked out
//                again on Binance bars: said so; a condition that comes out off says the bars may differ)
//   3 그때 차트    the chart as the rule bot recorded it with the signal (장세, ADX, DI, EMA20, the range), the descriptive marks
//   4 진입 전 검사 the weekend, the macro releases (the nearest one), the NYSE open, a B setting's chase test with its numbers,
//                one position at a time
//   5 같은 때 다른 신호, 6 성적 (this setting / strategy in this bot before this entry; the 5-year numbers apart, labelled)
// HONESTY: a part without its record says why (수집 전 / 못 읽음); descriptive marks are never called a rule; no buttons that
// change anything.
// The 'VWAP 개선판' (owners 10/23; the server's ``gate``): the strategy in the owners' words (signal.strategy_ko), no A / B
// group, its checks in its own order with the numbers its gates read ("4시간 추세: 상승 3·하락 0·중립 1 → 롱 통과", "변동성
// 30분 ATR 0.45% · 30일 80% 위치 0.62% → 통과"), the hold limit as information (·, not a pass); an entry recorded before the
// gates' numbers were kept says so, never a made-up number (the server's words).
import {h, put, ui, fmt} from "../core/pb.js";
import {sourceState} from "./livebots-kit.js";

export const WHY_API = "/api/v4/livebots/why";
const KEEP = 60;
const RETRY_MS = 60 * 1000;             // an answer with a part that failed (Binance bars) is asked again after a minute
const cache = new Map();                // url -> {d, at}: an entry's reasons do not change
const opened = new Set();               // urls whose panel is open (a redraw of the card or the row keeps it open)

/** The answer's url for a {bot, symbol, entry} reference (null without one). */
export function whyUrl(ref) {
  if (!ref || !ref.bot || !ref.symbol || ref.entry == null) return null;
  return `${WHY_API}?bot=${encodeURIComponent(ref.bot)}&symbol=${encodeURIComponent(ref.symbol)}&entry=${encodeURIComponent(String(ref.entry))}`;
}

const yes = (ok) => h("i", {class: ["lbw-ok", ok === true ? "on" : ok === false ? "off" : "na"], "aria-label": ok === true ? "맞음" : ok === false ? "아님" : "모름"},
  ok === true ? "✓" : ok === false ? "✗" : "?");
const sec = (n, title, ...kids) => h("section", {class: "lbw-sec"}, h("h4", {class: "lbw-h"}, h("span", {class: "lbw-n"}, String(n)), title), ...kids);
const note = (text) => (text ? h("p", {class: "note lbw-note"}, text) : null);

/** An indicator's value in a short form (prices with their own digits, small numbers with two). */
function val(v) {
  const x = Number(v);
  if (!Number.isFinite(x)) return "—";
  return Math.abs(x) >= 100 ? fmt.price(x) : fmt.num(x, Math.abs(x) >= 10 ? 1 : 2);
}

/** "3일 전" / "2시간 뒤" of a gap in ms. */
function gapKo(ms) {
  const s = Math.abs(Number(ms) || 0) / 1000;
  return `${fmt.dur(s)} ${Number(ms) < 0 ? "전" : "뒤"}`;
}

function recLine(r, what) {
  if (!r || !r.n) return `${what}: 아직 닫힌 거래 없음`;
  return `${what}: ${fmt.int(r.n)}번 ${fmt.int(r.wins)}승 ${fmt.int(r.losses)}패 (승률 ${fmt.pct(r.win_rate, 0, false)} · 손익 ${fmt.money(r.pnl, true)} USDT)`;
}

/** A setting's group in words ("A그룹 · "), '' for a bot without groups (the server's group null: the VWAP bot). */
const groupKo = (st) => (st.group === "B" ? "B그룹 (추격 진입 막기) · " : st.group === "A" ? "A그룹 · " : "");

function signalPart(d) {
  const s = d.signal || {}, st = d.setting;
  const delay = s.ref_time && s.bar_close ? (s.ref_time - s.bar_close) / 1000 : s.delay_ms != null ? s.delay_ms / 1000 : null;
  const pairs = [
    ["매매법", `${s.strategy_ko || fmt.stratKo(s.strategy)} (${s.strategy}) · ${fmt.tfKo(s.tf)}봉`],
    ["설정", st ? `${st.order}번 설정 · ${groupKo(st)}${st.entry_ko} 진입${st.invert ? " · 반대 방향" : ""}`
      : s.order ? `${s.order}번 설정 (지금 설정 파일과 달라 자세한 내용은 못 보여 드려요)` : "설정 기록 없음"],
    ["손절 방식", st && st.stop ? st.stop.ko : null],
    ["신호 봉", s.bar_close ? `${fmt.kst(s.bar_close)} 마감 · ${s.side_ko || fmt.sideKo(s.side)} 신호` : null],
    ["신호 출처", s.source_ko || null],
    ["기준 가격 → 체결", s.ref_price || s.fill ? `${fmt.price(s.ref_price)} → ${fmt.price(s.fill)}${delay != null ? ` (봉 마감 ${fmt.dur(delay)} 뒤 신호)` : ""}` : null],
    ["진입 세기 점수", s.score != null ? `${fmt.num(s.score, 1)} / 5 ${s.score_used ? "(이 봇은 점수 높은 신호를 먼저 골라요)" : "(참고: 이 봇은 점수가 아니라 설정 순서로 골라요)"}` : "점수 없음"],
    ["배수 · 증거금", s.leverage ? `${fmt.lev(s.leverage)}${s.margin != null ? ` · ${fmt.money(s.margin)} USDT` : ""}` : null],
  ];
  return sec(1, "어떤 신호였나", ui.kv(pairs.filter(([, v]) => v != null)),
    st && st.custom && st.numbers ? note(`커스텀 숫자: ${Object.entries(st.numbers).map(([k, v]) => `${k} ${v}`).join(" · ")}`) : null);
}

function condPart(d) {
  const c = d.conditions || {};
  if (c.state !== "ok") {
    const why = c.reason_ko || "다시 계산하지 못했어요";
    return sec(2, "매매법 조건 (신호 봉에서)", c.state === "error" ? h("p", {class: "note"}, ui.pill("못 읽음", "bad", c.reason || why), ` ${why}`)
      : h("p", {class: "note"}, ui.notYet("—", why), ` ${why}`));
  }
  const items = c.items || [];
  const head = c.all_on ? h("p", {class: "lbw-verdict good"}, `조건 ${fmt.int(items.length)}개가 모두 맞아 ${c.side_ko} 신호가 났어요`)
    : h("p", {class: "lbw-verdict warn"}, `다시 계산하니 ${fmt.int(items.length)}개 중 ${fmt.int(c.n_on)}개만 맞아요 · 규칙봇 봉과 바이낸스 봉이 조금 달랐을 수 있어요`);
  return sec(2, "매매법 조건 (신호 봉에서)", head,
    c.inverted ? note(`반대 방향 설정: 매매법은 ${c.side_ko} 신호를 냈고, 봇은 그 반대로 들어갔어요`) : null,
    h("ul", {class: "lbw-conds"}, items.map((x) => h("li", {class: x.on ? "on" : "off"}, yes(x.on), h("span", null, x.name)))),
    c.values && c.values.length ? h("div", {class: "lbw-vals"}, c.values.map((v) => h("span", {class: "pp thin", title: v.group || ""},
      `${v.name} `, h("b", {class: "num"}, val(v.value))))) : null,
    note(c.note_ko));
}

function chartPart(d) {
  const c = d.chart || {};
  if (c.state !== "ok") return sec(3, "그때 차트", sourceState(c, "규칙봇 신호 기록"));
  return sec(3, "그때 차트",
    h("dl", {class: "lbw-chart"}, (c.items || []).map((x) => h("div", {class: ["lbw-ci", x.tone || ""]},
      h("dt", null, x.k), h("dd", null, h("b", null, String(x.v)), x.ko ? h("small", {class: "muted"}, ` ${x.ko}`) : null)))),
    c.tags && c.tags.length ? h("p", {class: "lbw-tags"}, c.tags.map((t) => ui.pill(t, "thin", c.tags_ko || "")), " ", ui.infoTip(c.tags_ko || "", "설명용 표시")) : null,
    note(c.note_ko));
}

function checkDetail(x) {
  const t = x.detail;
  if (!t) return null;
  if (x.id === "macro" && t.ts) return `가장 가까운 발표: ${t.kind_ko} ${fmt.kst(t.ts)} (진입 ${gapKo(t.gap_ms)})`;
  if (x.id === "chase" && t.state === "ok") {
    const l = t.limits || {};
    const p24 = t.d24 ? `24시간 범위 ${fmt.pct(t.d24.place, 0, false)} 위치` : "24시간 범위 모름";
    const p7 = t.d7 ? `7일 범위 ${fmt.pct(t.d7.place, 0, false)} 위치` : "7일 범위 모름";
    return `기준 가격 ${fmt.price(t.price)}: ${p24} · ${p7} (롱은 24시간 ${fmt.pct(l.h24_hi, 0, false)}·7일 ${fmt.pct(l.d7_hi, 0, false)}부터, `
      + `숏은 24시간 ${fmt.pct(l.h24_lo, 0, false)}·7일 ${fmt.pct(l.d7_lo, 0, false)}까지 막아요)`;
  }
  if (x.id === "chase") return t.reason_ko || null;
  if (x.id === "hold" && t.hold_ko) return `이 거래는 ${fmt.tfKo(t.tf)}봉이라 ${t.hold_ko}`;
  return null;
}

function checksPart(d) {
  const xs = d.checks || [];
  // x.info: a rule it runs under, not a check it passed (the VWAP bot's hold limit): a dot, never ✓
  return sec(4, "진입 전에 통과한 검사", h("ul", {class: "lbw-checks"}, xs.map((x) => h("li", {class: x.info ? "na info" : x.ok === false ? "off" : x.ok ? "on" : "na"},
    x.info ? h("i", {class: "lbw-ok na", "aria-label": "알아 둘 것"}, "·") : yes(x.ok),
    h("span", null, x.ko, checkDetail(x) ? h("small", {class: "muted"}, ` · ${checkDetail(x)}`) : null)))),
  d.combo && d.combo.state !== "ok" ? sourceState(d.combo, "봇 설정") : null);
}

function rivalsPart(d) {
  const r = d.rivals || {};
  if (r.state !== "ok") return sec(5, "같은 때 나온 다른 신호", sourceState(r, "봇 신호 기록"));
  const rows = r.rows || [];
  return sec(5, "같은 때 나온 다른 신호", rows.length
    ? h("ul", {class: "lbw-rivals"}, rows.map((x) => h("li", null, h("b", null, `${fmt.stratKo(x.strategy)} ${fmt.tfKo(x.tf)}`), ` ${fmt.coin(x.symbol)} ${fmt.sideKo(x.side)} → `,
      h("span", {class: x.cat === "entered" ? "up" : "muted"}, x.ko), x.why_ko ? h("small", {class: "muted"}, ` (${x.why_ko})`) : null)))
    : h("p", {class: "note"}, "같은 봉 마감에 다른 신호는 없었어요"));
}

function recordPart(d) {
  const r = d.record || {}, f = d.five_year || {};
  const bt = [];
  if (f.state === "ok") {
    if (f.member && f.member.trades) bt.push(`이 설정 ${fmt.int(f.member.trades)}번 · 승률 ${fmt.pct(f.member.win, 1, false)} (전체 기간에 맞춘 값 · 낙관적)`);
    const s = f.strategy;
    if (s && s.honest_n) bt.push(`이 매매법 안 본 2025-26: ${fmt.int(s.honest_n)}번 · 승률 ${fmt.pct(s.honest_win, 1, false)} (정직한 값)`);
    if (f.break_even != null) bt.push(`본전 승률 ${fmt.pct(f.break_even, 1, false)}`);
  }
  return sec(6, "이 진입 전까지 성적",
    h("ul", {class: "lbw-rec"}, h("li", null, recLine(r.setting, "이 설정"), " ", ui.smallSample(r.setting ? r.setting.n : 0, 20)),
      h("li", null, recLine(r.strategy, "이 매매법 (모든 봉)")), h("li", null, recLine(r.all, "이 봇 전체"))),
    f.state === "ok" ? h("p", {class: "note"}, "5년 백테스트: ", bt.length ? bt.join(" · ") : "이 설정의 숫자가 기준표에 없어요") : note(f.reason_ko || null));
}

/** The panel's content for one answer (pure; node tests). */
export function whyBody(d) {
  if (!d || d.state !== "ok") {
    return h("div", {class: "lbw-in"}, sourceState(d || {state: "missing"}, "진입 근거"));
  }
  const s = d.signal || {};
  return h("div", {class: "lbw-in"},
    h("p", {class: "lbw-head"}, h("b", null, `${s.strategy_ko || fmt.stratKo(s.strategy)} · ${fmt.tfKo(s.tf)}봉`), " ", ui.sideTag(s.side), " ",
      d.setting && d.setting.group ? ui.pill(d.setting.group === "B" ? "B그룹" : "A그룹", d.setting.group === "B" ? "accent" : "thin") : null,
      h("small", {class: "muted"}, ` ${d.bot_ko || ""} · ${fmt.kst(s.bar_close)} 봉 마감 신호 → ${fmt.hm(d.entry)} 진입`)),
    signalPart(d), condPart(d), chartPart(d), checksPart(d), rivalsPart(d), recordPart(d));
}

function fresh(hit) {
  if (!hit) return false;
  const d = hit.d || {};
  const failed = (d.conditions && d.conditions.state === "error") || (d.rivals && d.rivals.state === "error");
  return !failed || Date.now() - hit.at < RETRY_MS;
}

/** The 진입 근거 button and its panel for a {bot, symbol, entry} reference; ``api`` (the screen's ctx.api) asks the answer
 *  the first time it is opened. null without a reference. */
export function whyBox(api, ref, o = {}) {
  const url = whyUrl(ref);
  if (!url || typeof api !== "function") return null;
  const region = h("div", {class: "lbw-body", hidden: true});
  const btn = h("button", {type: "button", class: "btn-line lbw-btn", "aria-expanded": "false"}, o.label || "진입 근거 보기");
  const el = h("div", {class: "lbw"}, btn, region);
  async function load() {
    const hit = cache.get(url);
    if (fresh(hit)) { put(region, whyBody(hit.d)); return; }
    put(region, h("p", {class: "note"}, "진입 근거를 불러오는 중… (매매법 조건을 바이낸스 봉으로 다시 계산해요: 처음 몇 초)"));
    let d;
    try { d = await api(url); }
    catch (e) {
      if (e && e.name === "AbortError") return;
      put(region, h("p", {class: "note"}, ui.pill("못 읽음", "bad"), " 진입 근거를 불러오지 못했어요 ",
        h("button", {type: "button", class: "linkish", onclick: () => load()}, "다시")));
      return;
    }
    cache.set(url, {d, at: Date.now()});
    while (cache.size > KEEP) cache.delete(cache.keys().next().value);
    if (btn.getAttribute("aria-expanded") === "true") put(region, whyBody(d));
  }
  function show(on) {
    btn.setAttribute("aria-expanded", String(on));
    btn.textContent = on ? "진입 근거 접기" : (o.label || "진입 근거 보기");
    region.hidden = !on;
    if (on) { opened.add(url); load(); } else opened.delete(url);
  }
  btn.addEventListener("click", () => show(btn.getAttribute("aria-expanded") !== "true"));
  if (opened.has(url)) show(true);
  return el;
}
