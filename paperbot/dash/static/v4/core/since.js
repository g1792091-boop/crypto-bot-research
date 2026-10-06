// "지난번 본 뒤로": when the app opens (or comes back after more than 30 minutes hidden), a small sheet lists what
// happened since this viewer last looked: closed trades per group (count and summed P&L for 기존 36 / 5분봉 / 추가 계좌,
// counts for 딥시크 and 동전 봇), busts and liquidations, the best / worst trade, meetings that finished, the bot's
// warnings and the day count. Never on the very first visit (the time is only recorded), at most once per opening,
// nothing when nothing happened, never over the story (#/story is the catch-up itself). The last-visit time is a
// per-viewer convenience in local storage (dom.js local: try/catch inside); the server clamps it to the run and to
// 7 days: GET /api/v4/since?after=<ms> (dash/more/since.py). Its look: core/since.css (linked here, once).
// "자는 동안" (conv-a, owners 10/06 "클릭이 너무 많다"): away 3 hours or more, the same answer opens as the full card
// instead: EVERY section is listed and an empty one says 없음 (trades of 기존 36 and 5분봉 with P&L, 딥시크 · 동전 봇
// counted only, the biggest win and loss, busts, meetings that concluded, the bot's alerts, server issues: the bot's
// stops and restarts and the nightly checks from the server, the timers' failed runs from /api/v4/jobs and the health
// problems of now, and the verdict countdown); each line links to its place. The top bar's moon button (PC) and the
// 설정 panel's 바로가기 open it on demand for the last absence, the last 8 or 24 hours. Nothing is invented.
import {h, s, local, $} from "./dom.js";
import {api, serverNow} from "./api.js";
import {store} from "./store.js";
import {money, int, kst, hm, mmdd, dur, idName, reasonKo, coin, tone, pct} from "./fmt.js";
import {href} from "./routes.js";
import {alertKo} from "./alerts.js";
import {ASSUME_KO, toast} from "./ui.js";
import {reduced} from "./motion.js";

const KEY = "since-last";
const AWAY_KEY = "since-away";      // the last real absence {from, to} (30 minutes or more): the button's first range
const GAP_MS = 30 * 60000;          // away at least this long before the sheet is worth showing
const AWAY_MS = 3 * 3600000;        // away at least this long: the full 자는 동안 card
const HOUR_MS = 3600000, DAY_MS = 86400000;
const MARK_MS = 60000;
const GROUPS = [["core", "기존 36", "core"], ["ds200", "딥시크 44", "ds"], ["reel", "5분봉", "m5"], ["flip", "동전 봇", "coin"], ["extra", "추가 계좌", "extra"]];
const MONEY = new Set(["core", "reel", "extra"]);       // P&L shown per group (D10 / D11: DeepSeek and coin flips counted)
// the paperbot timers in Korean (the 서버·비용 screen's names, screens/server-kit.js JOBS)
const JOB_KO = {"paperbot-daily3": "매일 점검", "paperbot-backup": "DB 백업", "paperbot-offsite": "바깥 백업", "paperbot-obsidian": "옵시디언 노트",
  "paperbot-shadow200": "딥시크 200 그림자", "paperbot-agents": "에이전트 점검", "paperbot-checkpoint": "체크포인트 판정",
  "paperbot-dscheck": "딥시크 밤 재계산", "paperbot-evening": "저녁 회의", "paperbot-rehearsal": "판정 미리 연습", "paperbot-labmonthly": "매달 재검사"};

let sheet = null;
let busy = false;

const lastSeen = () => { const v = local.get(KEY, null); return typeof v === "number" && Number.isFinite(v) ? v : null; };
const mark = () => local.set(KEY, Math.round(serverNow()));
/** The last absence of 30 minutes or more on this device ({from, to} ms), null when none was seen yet. */
export const lastAway = () => { const v = local.get(AWAY_KEY, null); return v && Number.isFinite(v.from) && Number.isFinite(v.to) && v.to > v.from ? v : null; };

function loadCss() {
  if (document.querySelector("link[data-since]")) return;
  const l = document.createElement("link");
  l.rel = "stylesheet";
  l.href = "/static/v4/core/since.css";
  l.dataset.since = "1";
  document.head.append(l);
}

// a 16 x 16 pixel moon with two small stars (fill = currentColor)
const R = (x, y, w, hh) => s("rect", {x, y, width: w, height: hh});
const moonIcon = () => s("svg", {viewBox: "0 0 16 16", width: "16", height: "16", fill: "currentColor", "shape-rendering": "crispEdges", "aria-hidden": "true"},
  [R(6, 1, 4, 1), R(4, 2, 3, 1), R(3, 3, 2, 2), R(2, 5, 2, 6), R(3, 11, 2, 2), R(4, 13, 3, 1), R(6, 14, 4, 1), R(10, 13, 3, 1), R(12, 12, 2, 1),
    R(11, 3, 1, 1), R(13, 6, 1, 1), R(12, 8, 1, 1)]);
/** The top bar's 자는 동안 button (from 1200 px; core/settings.css): the card on demand. */
export function awayButton() {
  return h("button", {class: "awaybtn", id: "awaybtn", type: "button", "aria-haspopup": "dialog", "aria-label": "자는 동안: 자리 비운 사이 바뀐 것",
    title: "자는 동안 (자리 비운 사이 바뀐 것)", onclick: () => openAway()}, moonIcon(), h("span", {class: "awaybtn-t"}, "자는 동안"));
}

export function startSince() {
  loadCss();
  const prev = lastSeen();
  mark();
  if (prev != null && serverNow() - prev >= GAP_MS) arrive(prev);          // the very first visit only records the time
  let hiddenAt = document.visibilityState === "hidden" ? Date.now() : null;
  setInterval(() => { if (document.visibilityState === "visible") mark(); }, MARK_MS);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") { hiddenAt = Date.now(); mark(); return; }
    const away = hiddenAt != null && Date.now() - hiddenAt >= GAP_MS;
    const before = lastSeen();
    hiddenAt = null;
    mark();
    if (away && before != null) arrive(before);
  });
  window.addEventListener("pagehide", mark);
  const anchor = $("#findbtn");
  if (anchor && !$("#awaybtn")) anchor.after(awayButton());
}

/** Back after an absence that began at ``prev``: remembered for the button; 3 hours or more opens the full card. */
function arrive(prev) {
  const now = Math.round(serverNow());
  local.set(AWAY_KEY, {from: Math.round(prev), to: now});
  if (now - prev >= AWAY_MS) openAway("away", {auto: true});
  else show(prev);
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
      : h("span", {class: "s muted"}, n ? (MONEY.has(g) ? `이긴 거래 ${int(x.wins)}` : `건수만 · 이긴 거래 ${int(x.wins)}`) : "거래 없음"),
    w != null ? h("span", {class: "wb", title: `이긴 비율 ${pct(w, 0, false)}`}, h("i", {style: {"--w": (w * 100).toFixed(1) + "%"}})) : null);
}
function row(ic, cls, title, detail, value, link, vcls) {
  return h("a", {class: "since-row", href: link, "data-close": "1"},
    h("span", {class: ["since-ic", cls], "aria-hidden": "true"}, ic),
    h("span", {class: "since-t"}, h("b", null, title), detail ? h("span", null, detail) : null),
    value != null ? h("span", {class: ["since-v", "num", vcls]}, value) : h("span", {class: "since-go", "aria-hidden": "true"}, "›"));
}
/** A section of the 자는 동안 card with nothing in it: its name and 없음 (still a link to its place); `word` says
 *  확인 못 함 where the record to tell is missing. */
const noneRow = (ic, title, detail, link, word = "없음") => h("a", {class: "since-row none", href: link, "data-close": "1"},
  h("span", {class: "since-ic", "aria-hidden": "true"}, ic),
  h("span", {class: "since-t"}, h("b", null, title), detail ? h("span", null, detail) : null),
  h("span", {class: "since-v since-none"}, word));

const TRADE_KO = {best: ["▲", "up", "가장 크게 번 거래"], worst: ["▼", "down", "가장 크게 잃은 거래"]};
/** The best ("best") or worst ("worst") closed trade of 기존 36 · 5분봉 · 추가 계좌 (the server never names another
 *  group's trade), null when there is none. */
function tradeRow(d, k) {
  const t = d[k], [ic, cls, word] = TRADE_KO[k];
  return t ? row(ic, cls, word, `${idName(t.account_id)} · ${coin(t.symbol)} · ${reasonKo(t.exit_reason)}`,
    `${money(t.pnl, true)}`, href("account", t.account_id), tone(t.pnl, money(t.pnl, true))) : null;
}
const tradeRows = (d) => [tradeRow(d, "best"), tradeRow(d, "worst")].filter(Boolean);
function bustRow(d) {
  const T = d.trades || {}, B = d.busts || {n: 0};
  if (!B.n && !T.liquidations) return null;
  const named = (B.named || []).map((a) => idName(a.account_id));
  const by = Object.entries(B.by_group || {}).filter(([g]) => !MONEY.has(g)).map(([g, n]) => `${(GROUPS.find((x) => x[0] === g) || [g, g])[1]}: ${int(n)}개 파산`);
  return row("✕", "down", `파산 ${int(B.n)}개 · 강제청산 ${int(T.liquidations || 0)}건`, [...named, ...by].join(" · ") || "파산 없음, 강제청산만", null, href("alerts"));
}
function meetingRow(d) {
  const M = d.meetings || {finished: 0};
  if (!M.finished) return null;
  const l = (M.lines || [])[0];
  return row("◆", "accent", `회의 ${int(M.finished)}번 끝남 · 결정 ${int(M.decided)}번`, l ? `${l.title} · ${l.line}` : null, null, href("digest"));
}
function alertRow(d) {
  const A = d.alerts || {n: 0};
  if (!A.n) return null;
  const l = (A.latest || [])[0];
  const lv = A.by_level || {};
  const split = [lv.CRITICAL ? `긴급 ${int(lv.CRITICAL)}` : null, lv.WARN ? `주의 ${int(lv.WARN)}` : null].filter(Boolean).join(" · ");
  return row("!", "warn", `봇 알림 ${int(A.n)}${A.capped ? "+" : ""}개${split ? " · " + split : ""}`, l ? alertKo(l.text) : null, null, href("alerts"));
}
function milestoneRows(d) {
  const out = [];
  for (const m of d.milestones || []) {
    if (m.kind === "day") out.push(row("D+", "accent", `실험 D+${m.from} → D+${m.to}`, d.verdict_ts ? `첫 판정 ${kst(d.verdict_ts)}` : null, null, href("checkpoint")));
    else if (m.kind === "verdict") out.push(row("◆", "accent", `${int(m.k * (d.of || 30))}일째 판정 날이 지났습니다`, "판정 화면에서 결과를 봅니다", null, href("checkpoint")));
    else if (m.kind === "observe_end") out.push(row("◆", "accent", "관찰 기간이 끝났습니다", "이제 에이전트가 새 계좌를 제안할 수 있습니다 (두 분 승인 후 시작)", null, href("rooms")));
  }
  return out;
}
/** The server's own records of the window: the bot's stops and restarts, the nightly checks; the timers' failed runs
 *  (jobs: /api/v4/jobs, may be null) and the health problems of now (health: the store's /api/analysis/health). */
export function serverRows(d, jobs, health, after) {
  const S = d.server || {};
  const out = [];
  const link = href("server");
  if (S.stops_n) {
    const L = S.longest;
    out.push(row("■", "down", `봇 멈춤 ${int(S.stops_n)}번 · 합 ${dur((S.stop_min || 0) * 60)}`,
      L ? `가장 긴 멈춤 ${dur(L.min * 60)} (${kst(L.from)}~${hm(L.to)})${L.ongoing ? " · 지금까지 이어짐" : ""}` : null, null, link));
  }
  if ((S.restarts || []).length) out.push(row("↻", "warn", `봇 다시 시작 ${int(S.restarts.length)}번`, `마지막 ${kst(S.restarts[S.restarts.length - 1])}`, null, link));
  for (const n of S.nightly || []) {
    if (n.accounts == null || n.mismatched == null) continue;
    if (n.mismatched > 0) out.push(row("≠", "warn", `밤 점검 ${n.day}: 다시 계산이 다른 계좌 ${int(n.mismatched)}개`, `${int(n.accounts)}개 중 · 서버 화면에서 자세히`, null, link));
  }
  const failed = jobs && jobs.available && jobs.jobs ? Object.entries(jobs.jobs).filter(([, j]) => j && j.ok === false && Number(j.last_ms) > after) : [];
  if (failed.length) out.push(row("!", "warn", `예약 작업 실패 ${int(failed.length)}개`, failed.map(([u, j]) => `${JOB_KO[u] || u} (${kst(j.last_ms)})`).join(" · "), null, link));
  // the health card's level: "bad" lists problems, "warn" only warnings (analysis.py health: problems first)
  const said = health ? (health.level === "bad" ? health.problems : health.level === "warn" ? health.warnings : null) : null;
  if (Array.isArray(said) && said.length) {
    out.push(row("!", health.level === "bad" ? "down" : "warn", health.level === "bad" ? "지금 문제 있음" : "지금 확인할 것 있음", String(said[0]), null, link));
  }
  return out;
}

function render(d, after) {
  const T = d.trades || {total: 0, groups: {}};
  const G = T.groups || {};
  const tiles = GROUPS.filter(([g]) => g !== "extra" || G.extra).map((x) => tile(x, G[x[0]]));
  const rows = [...tradeRows(d), bustRow(d), meetingRow(d), alertRow(d), ...serverRows(d, null, null, after), ...milestoneRows(d)].filter(Boolean);
  const title = !d.clamped ? `지난번(${kst(after)}) 본 뒤로` : d.clamped_by === "start" ? "실험 시작부터 바뀐 것" : "최근 7일 동안 바뀐 것";
  open(d, {cls: "", plate: "새 소식", title, sub: [`${dur((d.now - d.after) / 1000)} 동안 · 닫힌 거래 ${int(T.total)}건`,
    d.clamped_by === "week" ? " · 그보다 전 일은 알림 기록에" : ""], tiles, rows});
}

// ---------------------------------------------------------------- 자는 동안 (the full card)
const RANGES = [{id: "away", ko: "지난번 비운 뒤로"}, {id: "8h", ko: "최근 8시간"}, {id: "24h", ko: "최근 24시간"}];
/** The window of a range: [after ms, words]. "away": the last absence (none yet: 8 hours). */
export function rangeAfter(id, now = serverNow(), away = lastAway()) {
  if (id === "away" && away) return [away.from, `${kst(away.from)}부터`];
  if (id === "24h") return [now - 24 * HOUR_MS, "최근 24시간"];
  return [now - 8 * HOUR_MS, "최근 8시간"];
}

/** Open the 자는 동안 card (range "away" | "8h" | "24h"; the button: the last absence when there is one). */
export async function openAway(range, o = {}) {
  if (busy || /^#\/story\b/.test(location.hash)) return;
  if (sheet && !o.keep) return;
  const away = lastAway();
  const id = range || (away ? "away" : "8h");
  const [after, words] = rangeAfter(id === "away" && !away ? "8h" : id, Math.round(serverNow()), away);
  busy = true;
  const [d, jobs, health] = await Promise.all([api(`/api/v4/since?after=${Math.floor(after)}`).catch(() => null),
    api("/api/v4/jobs").catch(() => null), store.need("health", 120000).catch(() => null)]);
  busy = false;
  if (o.auto && (sheet || /^#\/story\b/.test(location.hash) || document.querySelector(".tour-card"))) return;
  // the server did not answer: say so on a press (an open card stays as it was); nothing on the automatic opening
  if (!d) { if (!o.auto) toast("자는 동안 요약을 불러오지 못했습니다 · 잠시 뒤 다시 눌러 주세요"); return; }
  if (sheet && o.keep) closeSheet(true);
  renderAway(d, {after: d.after, id: id === "away" && !away ? "8h" : id, words, jobs, health, away});
}

function renderAway(d, o) { open(d, awayParts(d, o)); }
/** "29일" to the next verdict (the server's whole days), "5시간" on its last day (09:00 Korea time). */
export function verdictLeft(d) {
  const ms = Number(d.verdict_ts) - Number(d.now);
  return Number.isFinite(ms) && ms < 86400000 ? dur(Math.max(0, ms) / 1000) : `${int(d.days_left)}일`;
}

/** The 자는 동안 card's parts {plate, title, sub, seg, tiles, rows} for one /api/v4/since answer (o: {id, words, jobs,
 *  health, away}): every section is there, an empty one as a 없음 row. */
export function awayParts(d, o = {}) {
  const T = d.trades || {total: 0, groups: {}};
  const G = T.groups || {};
  const tiles = GROUPS.filter(([g]) => g !== "extra" || G.extra).map((x) => tile(x, G[x[0]]));
  const M = d.meetings || {};
  const S = d.server || {};
  // the bot's stops need its 1-minute records, the timers' runs need systemd (/api/v4/jobs): without them the card
  // says it could not tell (never "no stop", never "no failed job")
  const jobsKnown = !!(o.jobs && o.jobs.available);
  const srv = [...serverRows(d, o.jobs, o.health, d.after),
    S.known === false ? noneRow("■", "봇 멈춤", "봇 가동 기록(1분봉)이 아직 없습니다", href("server"), "확인 못 함") : null,
    jobsKnown ? null : noneRow("!", "예약 작업", "이 서버의 예약 작업 기록을 읽지 못했습니다", href("server"), "확인 못 함")].filter(Boolean);
  const vts = d.verdict_ts;
  const leftKo = verdictLeft(d);
  const sh = (t) => h("p", {class: "since-sh"}, t);
  const rows = [
    sh("거래 · 파산"),
    tradeRow(d, "best") || noneRow("▲", "가장 크게 번 거래", "기존 36 · 5분봉 · 추가 계좌의 닫힌 거래", href("board")),
    tradeRow(d, "worst") || noneRow("▼", "가장 크게 잃은 거래", "기존 36 · 5분봉 · 추가 계좌의 닫힌 거래", href("board")),
    bustRow(d) || noneRow("✕", "파산 · 강제청산", null, href("alerts")),
    sh("회의 · 알림"),
    meetingRow(d) || (M.error ? noneRow("◆", "끝난 회의", "회의 기록을 읽지 못했습니다", href("digest"), "확인 못 함")
      : noneRow("◆", "끝난 회의", "결론을 내고 끝난 회의", href("digest"))),
    alertRow(d) || noneRow("!", "봇 알림", "주의 · 긴급 알림", href("alerts")),
    sh("서버"),
    ...(srv.length ? srv : [noneRow("■", "서버 문제", "멈춤 · 재시작 · 실패한 작업", href("server"))]),
    sh("판정"),
    ...milestoneRows(d),
    // after the first verdict the server names the next one (restart_banner): "D+35 · 다음 판정 12/04", not "D+35 / 30"
    vts ? row("D-", "accent", `판정까지 ${leftKo}`, (Number(d.dn) > Number(d.of || 30) ? `D+${int(d.dn)} · 다음 판정 ` : `D+${int(d.dn ?? 0)} / ${int(d.of || 30)} · 판정 `)
      + `${mmdd(vts)} 09:00 (한국)`, null, href("checkpoint"))
      : noneRow("D-", "판정까지", "봇이 아직 첫 계좌를 만들지 않았습니다", href("checkpoint")),
  ];
  const span = dur((d.now - d.after) / 1000);
  const title = d.clamped ? (d.clamped_by === "start" ? "실험 시작부터 지금까지" : "최근 7일 동안") : o.id === "away" ? `${kst(d.after)}부터 지금까지` : `${o.words} 동안`;
  const seg = h("div", {class: "seg since-seg", role: "group", "aria-label": "볼 기간"},
    RANGES.filter((r) => r.id !== "away" || o.away).map((r) => h("button", {type: "button", "aria-pressed": String(r.id === o.id),
      title: r.id === "away" && o.away ? `${kst(o.away.from)} ~ ${kst(o.away.to)} 자리 비움` : null,
      onclick: () => { if (r.id !== o.id) openAway(r.id, {keep: true}); }}, r.ko)));
  return {cls: "away", plate: "자는 동안", title, sub: [`${span} 동안 · 닫힌 거래 ${int(T.total)}건`, vts ? ` · 판정까지 ${leftKo}` : "",
    d.clamped_by === "week" ? " · 그보다 전 일은 알림 기록에" : ""], seg, tiles, rows};
}

// ---------------------------------------------------------------- the frame both use
function closeSheet(now) {
  if (sheet && sheet._close) sheet._close(now);
}
function open(d, o) {
  const prevFocus = document.activeElement;
  const phone = !matchMedia("(min-width: 760px)").matches;
  const closeBtn = h("button", {class: "since-x", type: "button", "aria-label": "닫기"}, "✕");
  const okBtn = h("button", {class: "btn-y", type: "button"}, "확인");
  const scrim = h("div", {class: "since-scrim"});
  const el = h("section", {class: ["since", "bsheet", o.cls], role: "dialog", "aria-modal": phone ? "true" : "false", "aria-labelledby": "since-title",
    tabindex: "-1"},
    h("div", {class: "since-h"},
      h("span", {class: "since-plate"}, o.plate),
      h("h2", {id: "since-title"}, o.title),
      h("span", {class: "since-sub"}, o.sub),
      closeBtn),
    o.seg ? h("div", {class: "since-segrow"}, o.seg) : null,
    h("div", {class: "since-tiles"}, o.tiles),
    o.rows.length ? h("div", {class: "since-list"}, o.rows) : null,
    h("div", {class: "since-foot"},
      h("p", {class: "assume"}, ASSUME_KO, " · 딥시크·동전 봇은 건수만 · 합계는 닫힌 거래"),
      h("div", {class: "since-btns"}, h("a", {class: "btn-line", href: href("story"), "data-close": "1"}, "오늘의 하이라이트"), okBtn)));
  document.body.append(scrim, el);
  sheet = el;
  const close = (instant) => {
    if (sheet !== el) return;
    sheet = null;
    document.removeEventListener("keydown", onKey);
    window.removeEventListener("hashchange", onRoute);
    const gone = () => { el.remove(); scrim.remove(); };
    if (reduced() || instant) gone();
    else { el.classList.remove("in"); scrim.classList.remove("in"); setTimeout(gone, 340); }
    if (!instant && prevFocus && prevFocus.focus && document.contains(prevFocus)) prevFocus.focus({preventScroll: true});
  };
  el._close = close;
  const onKey = (e) => { if (e.key === "Escape") { e.preventDefault(); close(); } };
  const onRoute = () => { if (/^#\/story\b/.test(location.hash)) close(); };
  closeBtn.addEventListener("click", () => close());
  okBtn.addEventListener("click", () => close());
  scrim.addEventListener("click", () => close());
  el.addEventListener("click", (e) => { const a = e.target.closest && e.target.closest("[data-close]"); if (a) close(); });
  document.addEventListener("keydown", onKey);
  window.addEventListener("hashchange", onRoute);
  // swipe the sheet down to close it (phone)
  let y0 = null;
  el.addEventListener("pointerdown", (e) => { y0 = el.scrollTop <= 0 ? e.clientY : null; });
  el.addEventListener("pointerup", (e) => { if (y0 != null && e.clientY - y0 > 70) close(); y0 = null; });
  requestAnimationFrame(() => requestAnimationFrame(() => { el.classList.add("in"); scrim.classList.add("in"); okBtn.focus({preventScroll: true}); }));
}
