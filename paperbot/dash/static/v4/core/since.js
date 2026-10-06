// "지난번 본 뒤로": when the app opens (or comes back after more than 30 minutes hidden), a small sheet lists what
// happened since this viewer last looked: closed trades per group (count and summed P&L for 기존 36 / 5분봉 / 추가 계좌,
// counts for 딥시크 and 동전 봇), busts and liquidations, the best / worst trade, meetings that finished, the bot's
// warnings and the day count. Never on the very first visit (the time is only recorded), at most once per opening,
// nothing when nothing happened, never over the story (#/story is the catch-up itself). The last-visit time is a
// per-viewer convenience in local storage (dom.js local: try/catch inside); the server clamps it to the run and to
// 7 days: GET /api/v4/since?after=<ms> (dash/more/since.py). Its look: core/since.css (linked here, once).
import {h, local} from "./dom.js";
import {api, serverNow} from "./api.js";
import {money, int, kst, dur, idName, reasonKo, coin, tone, pct} from "./fmt.js";
import {href} from "./routes.js";
import {alertKo} from "./alerts.js";
import {ASSUME_KO} from "./ui.js";
import {reduced} from "./motion.js";

const KEY = "since-last";
const GAP_MS = 30 * 60000;          // away at least this long before the sheet is worth showing
const MARK_MS = 60000;
const GROUPS = [["core", "기존 36", "core"], ["ds200", "딥시크 44", "ds"], ["reel", "5분봉", "m5"], ["flip", "동전 봇", "coin"], ["extra", "추가 계좌", "extra"]];
const MONEY = new Set(["core", "reel", "extra"]);       // P&L shown per group (D10 / D11: DeepSeek and coin flips counted)

let sheet = null;
let busy = false;

const lastSeen = () => { const v = local.get(KEY, null); return typeof v === "number" && Number.isFinite(v) ? v : null; };
const mark = () => local.set(KEY, Math.round(serverNow()));

function loadCss() {
  if (document.querySelector("link[data-since]")) return;
  const l = document.createElement("link");
  l.rel = "stylesheet";
  l.href = "/static/v4/core/since.css";
  l.dataset.since = "1";
  document.head.append(l);
}

export function startSince() {
  loadCss();
  const prev = lastSeen();
  mark();
  if (prev != null && serverNow() - prev >= GAP_MS) show(prev);          // the very first visit only records the time
  let hiddenAt = document.visibilityState === "hidden" ? Date.now() : null;
  setInterval(() => { if (document.visibilityState === "visible") mark(); }, MARK_MS);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") { hiddenAt = Date.now(); mark(); return; }
    const away = hiddenAt != null && Date.now() - hiddenAt >= GAP_MS;
    const before = lastSeen();
    hiddenAt = null;
    mark();
    if (away && before != null) show(before);
  });
  window.addEventListener("pagehide", mark);
}

async function show(after) {
  if (sheet || busy || /^#\/story\b/.test(location.hash)) return;
  busy = true;
  let d = null;
  try { d = await api(`/api/v4/since?after=${Math.floor(after)}`); } catch (e) { d = null; }
  busy = false;
  // nothing to say, already open, the story itself, or the first-visit tour on screen: no sheet
  if (!d || d.empty || sheet || /^#\/story\b/.test(location.hash) || document.querySelector(".tour-card")) return;
  render(d, after);
}

// ---------------------------------------------------------------- the sheet
function tile([g, ko, page], x) {
  const n = x ? x.trades : 0;
  const money_ = x && MONEY.has(g) && x.pnl != null;
  const w = x && x.trades ? x.wins / x.trades : null;
  return h("a", {class: ["since-tile", n ? "" : "zero"], href: href("board", null, {g: page}), "data-close": "1"},
    h("span", {class: "k"}, ko),
    h("b", {class: "n num"}, int(n), h("small", null, "건")),
    money_ ? h("span", {class: ["s", "num", tone(x.pnl, money(x.pnl, true))]}, `${money(x.pnl, true)} USDT`)
      : h("span", {class: "s muted"}, n ? `이긴 거래 ${int(x.wins)}` : "거래 없음"),
    w != null ? h("span", {class: "wb", title: `이긴 비율 ${pct(w, 0, false)}`}, h("i", {style: {"--w": (w * 100).toFixed(1) + "%"}})) : null);
}
function row(ic, cls, title, detail, value, link, vcls) {
  return h("a", {class: "since-row", href: link, "data-close": "1"},
    h("span", {class: ["since-ic", cls], "aria-hidden": "true"}, ic),
    h("span", {class: "since-t"}, h("b", null, title), detail ? h("span", null, detail) : null),
    value != null ? h("span", {class: ["since-v", "num", vcls]}, value) : h("span", {class: "since-go", "aria-hidden": "true"}, "›"));
}

function render(d, after) {
  const prevFocus = document.activeElement;
  const phone = !matchMedia("(min-width: 760px)").matches;
  const T = d.trades || {total: 0, groups: {}};
  const G = T.groups || {};
  const tiles = GROUPS.filter(([g]) => g !== "extra" || G.extra).map((x) => tile(x, G[x[0]]));
  const rows = [];
  for (const [k, ic, cls, word] of [["best", "▲", "up", "가장 크게 번 거래"], ["worst", "▼", "down", "가장 크게 잃은 거래"]]) {
    const t = d[k];
    if (t) rows.push(row(ic, cls, word, `${idName(t.account_id)} · ${coin(t.symbol)} · ${reasonKo(t.exit_reason)}`,
      `${money(t.pnl, true)}`, href("account", t.account_id), tone(t.pnl, money(t.pnl, true))));
  }
  const B = d.busts || {n: 0};
  if (B.n || T.liquidations) {
    const named = (B.named || []).map((a) => idName(a.account_id));
    const by = Object.entries(B.by_group || {}).filter(([g]) => !MONEY.has(g)).map(([g, n]) => `${(GROUPS.find((x) => x[0] === g) || [g, g])[1]}: ${int(n)}개 파산`);
    rows.push(row("✕", "down", `파산 ${int(B.n)}개 · 강제청산 ${int(T.liquidations || 0)}건`,
      [...named, ...by].join(" · ") || "파산 없음, 강제청산만", null, href("alerts")));
  }
  const M = d.meetings || {finished: 0};
  if (M.finished) {
    const l = (M.lines || [])[0];
    rows.push(row("◆", "accent", `회의 ${int(M.finished)}번 끝남 · 결정 ${int(M.decided)}번`, l ? `${l.title} · ${l.line}` : null, null, href("digest")));
  }
  const A = d.alerts || {n: 0};
  if (A.n) {
    const l = (A.latest || [])[0];
    rows.push(row("!", "warn", `봇 알림 ${int(A.n)}${A.capped ? "+" : ""}개`, l ? alertKo(l.text) : null, null, href("alerts")));
  }
  // the day count and the verdict in the verdict-day clock's words (dash/more/verdictday.py, review 10/06 fix 1 and
  // change 13): a verdict day that passed says whether its result is stored yet, never "결과를 봅니다" before it is
  for (const m of d.milestones || []) {
    if (m.kind === "day") rows.push(row("D+", "accent", `실험 ${int(m.from)}일 → ${int(m.to)}일 지남`, d.line_ko || (d.verdict_ts ? `판정 ${kst(d.verdict_ts)}` : null), null, href("checkpoint")));
    else if (m.kind === "verdict") rows.push(m.judged
      ? row("◆", "accent", `${int(m.k * 30)}일 판정 결과가 나왔습니다`, "판정 화면에서 봅니다 (그래서 이제 뭐가 바뀌나까지)", null, href("checkpoint"))
      : row("◆", "accent", `${int(m.k * 30)}일 판정 날 · 결과 계산 중`, "계산은 09:35부터 · 결과가 저장되면 판정 화면에 바로 나옵니다 (지금 상황도 판정 화면에)", null, href("checkpoint")));
    else if (m.kind === "verdict_result") rows.push(row("◆", "accent", `${int(m.k * 30)}일 판정 결과가 나왔습니다`, `${kst(m.ts)} 저장 · 판정 화면에서 봅니다`, null, href("checkpoint")));
    else if (m.kind === "observe_end") rows.push(row("◆", "accent", "관찰 기간이 끝났습니다", "이제 에이전트가 새 계좌를 제안할 수 있습니다 (두 분 승인 후 시작)", null, href("rooms")));
  }
  const title = !d.clamped ? `지난번(${kst(after)}) 본 뒤로` : d.clamped_by === "start" ? "실험 시작부터 바뀐 것" : "최근 7일 동안 바뀐 것";
  const closeBtn = h("button", {class: "since-x", type: "button", "aria-label": "닫기"}, "✕");
  const okBtn = h("button", {class: "btn-y", type: "button"}, "확인");
  const scrim = h("div", {class: "since-scrim"});
  const el = h("section", {class: "since bsheet", role: "dialog", "aria-modal": phone ? "true" : "false", "aria-labelledby": "since-title", tabindex: "-1"},
    h("div", {class: "since-h"},
      h("span", {class: "since-plate"}, "새 소식"),
      h("h2", {id: "since-title"}, title),
      h("span", {class: "since-sub"}, `${dur((d.now - d.after) / 1000)} 동안 · 닫힌 거래 ${int(T.total)}건`,
        d.clamped_by === "week" ? " · 그보다 전 일은 알림 기록에" : ""),
      closeBtn),
    h("div", {class: "since-tiles"}, tiles),
    rows.length ? h("div", {class: "since-list"}, rows) : null,
    h("div", {class: "since-foot"},
      h("p", {class: "assume"}, ASSUME_KO, " · 딥시크·동전 봇은 건수만 · 합계는 닫힌 거래"),
      h("div", {class: "since-btns"}, h("a", {class: "btn-line", href: href("story"), "data-close": "1"}, "오늘의 하이라이트"), okBtn)));
  document.body.append(scrim, el);
  sheet = el;
  const close = () => {
    if (sheet !== el) return;
    sheet = null;
    document.removeEventListener("keydown", onKey);
    window.removeEventListener("hashchange", onRoute);
    const gone = () => { el.remove(); scrim.remove(); };
    if (reduced()) gone();
    else { el.classList.remove("in"); scrim.classList.remove("in"); setTimeout(gone, 340); }
    if (prevFocus && prevFocus.focus && document.contains(prevFocus)) prevFocus.focus({preventScroll: true});
  };
  const onKey = (e) => { if (e.key === "Escape") { e.preventDefault(); close(); } };
  const onRoute = () => { if (/^#\/story\b/.test(location.hash)) close(); };
  closeBtn.addEventListener("click", close);
  okBtn.addEventListener("click", close);
  scrim.addEventListener("click", close);
  el.addEventListener("click", (e) => { const a = e.target.closest && e.target.closest("[data-close]"); if (a) close(); });
  document.addEventListener("keydown", onKey);
  window.addEventListener("hashchange", onRoute);
  // swipe the sheet down to close it (phone)
  let y0 = null;
  el.addEventListener("pointerdown", (e) => { y0 = el.scrollTop <= 0 ? e.clientY : null; });
  el.addEventListener("pointerup", (e) => { if (y0 != null && e.clientY - y0 > 70) close(); y0 = null; });
  requestAnimationFrame(() => requestAnimationFrame(() => { el.classList.add("in"); scrim.classList.add("in"); okBtn.focus({preventScroll: true}); }));
}
