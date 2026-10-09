// The top bar's tools (round 4, CONTRACT 9.8; ideas from the rule bot's v4 shell, written again here):
//   D+n pill    live days, the goal stage (home.json goal) and a countdown to the next tick (status.json next_tick_ms);
//               a tap opens the goal line, the five stages and the tick times
//   찾기        the search box (find.js; also the "/" key)
//   ★           the starred screens and accounts (favs.js)
//   자는 동안   what happened since this viewer last looked (last-visit time in local storage): closed trades
//               (trades.json), setting switches (home.json), passes and confirmation results (judge.json); "다 봤어요"
//   종          the Telegram messages (telegram.json): unread since the list was last opened, the latest 20
//   소리        a short beep when trades.json gets a new trade while the page is open; OFF until turned on (per device)
// The data is read again only when the engine wrote a new tick (status.json changed; app.js polls it every 30 s), so
// these cost four small requests per 15 minutes. Every text is set as text (h()), never parsed. On a phone the top bar
// keeps the pill, 자는 동안, the bell and the status dot; 찾기 and ★ sit at the start of the menu row, 소리 at its end.
import {h, s, put, local} from "./dom.js";
import {getJSON, isMissing} from "./api.js";
import * as fmt from "./fmt.js";
import {favs, onFavs, setFav} from "./favs.js";
import {openFind} from "./find.js";
import {TEXT_SIZES, textNow, applyText, textSwitch, navSwitch, skinSwitch} from "./prefs.js";
import {tgKindKo, sideKo, reasonKo, TG_STATUS_KO} from "./labels.js";

const HOUR = 3600000, DAY = 86400000;
const SINCE_KEY = "since-last";       // the end of the viewer's last visit (or the last "다 봤어요")
const BELL_KEY = "bell-seen";         // the newest message time when the bell's list was last opened
const SOUND_KEY = "sound";            // true: beep on a new trade (default off)
const AWAY_GAP = 30 * 60000;          // a hidden tab back after this long starts a new "자는 동안"
const FIRST_LOOK = 8 * HOUR;          // the very first visit: the last 8 hours

const D = {status: null, trades: null, home: null, judge: null, tg: null, accts: null, key: null, keys: null};
const ui = {pop: null, which: null, btn: null, pill: null, cd: null, cdk: null, away: null, awayN: null, bell: null, bellN: null, snd: [],
  menu: () => [], onText: null, onNav: null, onSkin: null};
let since = null, firstVisit = false, hiddenAt = null;

// ---------------------------------------------------------------- pixel icons (fill = currentColor)
const R = (x, y, w, hh) => s("rect", {x, y, width: w, height: hh});
const icon = (rects) => s("svg", {viewBox: "0 0 16 16", width: "16", height: "16", fill: "currentColor", "shape-rendering": "crispEdges",
  "aria-hidden": "true"}, rects.map((r) => R(...r)));
const MOON = [[6, 1, 4, 1], [4, 2, 3, 1], [3, 3, 2, 2], [2, 5, 2, 6], [3, 11, 2, 2], [4, 13, 3, 1], [6, 14, 4, 1], [10, 13, 3, 1], [12, 12, 2, 1],
  [11, 3, 1, 1], [13, 6, 1, 1], [12, 8, 1, 1]];
const BELL = [[7, 1, 2, 1], [5, 2, 6, 1], [4, 3, 8, 1], [4, 4, 8, 4], [3, 8, 10, 2], [2, 10, 12, 2], [6, 13, 4, 2]];

// ---------------------------------------------------------------- the one popover under the top bar
function popEl() {
  if (ui.pop) return ui.pop;
  ui.pop = h("div", {class: "tb-pop", id: "tb-pop", role: "dialog", hidden: true});
  (document.querySelector(".shell-top") || document.body).append(ui.pop);
  document.addEventListener("mousedown", (e) => {
    if (!ui.which) return;
    const t = e.target;
    if (ui.pop.contains(t) || (t.closest && t.closest("[data-pop]"))) return;
    closePop();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && ui.which) { closePop(true); } });
  window.addEventListener("hashchange", () => closePop());
  return ui.pop;
}
const BUILD = {pill: pillPanel, fav: favPanel, away: awayPanel, bell: bellPanel, view: viewPanel};
const POP_KO = {pill: "목표와 처리 시각", fav: "즐겨찾기", away: "자는 동안", bell: "알림", view: "보기 설정"};
function openPop(which, btn) {
  const el = popEl();
  if (ui.which === which) { closePop(true); return; }
  if (ui.btn) ui.btn.setAttribute("aria-expanded", "false");
  ui.which = which;
  ui.btn = btn;
  btn.setAttribute("aria-expanded", "true");
  el.setAttribute("aria-label", POP_KO[which]);
  el.dataset.which = which;
  el.hidden = false;
  paintPop();
  if (which === "bell") markBellSeen();
  if (which === "fav" && !D.accts) loadAccts();
  const f = el.querySelector("button, a");
  if (f) f.focus({preventScroll: true});
}
function closePop(focusBtn) {
  if (!ui.which) return;
  const b = ui.btn;
  ui.which = null;
  ui.btn = null;
  if (b) b.setAttribute("aria-expanded", "false");
  if (ui.pop) { ui.pop.hidden = true; ui.pop.replaceChildren(); }
  if (focusBtn && b && b.isConnected) b.focus({preventScroll: true});
}
function paintPop() {
  if (!ui.which || !ui.pop) return;
  const keep = ui.pop.scrollTop;
  put(ui.pop, h("div", {class: "tb-pin"}, h("div", {class: "tb-ph"}, h("b", null, POP_KO[ui.which]), h("span", {class: "grow"}),
    h("button", {type: "button", class: "btn-line tb-x", onclick: () => closePop(true), "aria-label": "닫기"}, "닫기")),
  BUILD[ui.which]()));
  ui.pop.scrollTop = keep;
}

// ---------------------------------------------------------------- the D+n pill
function liveDays(st) {
  return st && st.phase === "live" && st.live_start_ms ? Math.max(0, Math.floor((Date.now() - st.live_start_ms) / DAY)) : null;
}
function stageKo() {
  const g = D.home && !isMissing(D.home) ? D.home.goal : null;
  if (!g || !Array.isArray(g.stages_ko)) return null;
  return g.stages_ko[Number(g.stage)] || null;
}
function countdown(st) {
  if (!st || !st.next_tick_ms) return null;
  const left = Math.round((Number(st.next_tick_ms) - Date.now()) / 1000);
  if (left <= 0) return "처리 중";
  if (left >= 3600) return fmt.dur(left);                  // a stale file far from now: hours, not a huge m:ss
  return `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
}
function paintPill() {
  const b = ui.pill;
  if (!b) return;
  const st = D.status;
  if (!st || isMissing(st)) { put(b, h("b", null, "준비 중")); b.setAttribute("aria-label", "엔진 상태 준비 중. 누르면 목표"); return; }
  const d = liveDays(st);
  const stage = stageKo();
  const cd = countdown(st);
  ui.cdk = h("span", {class: "tb-cdk", hidden: cd === "처리 중"}, "다음 처리 ");
  ui.cd = h("span", {class: "tb-cdv"}, cd || "");
  put(b, h("b", null, d != null ? `D+${d}` : st.phase === "warm" ? "준비" : "멈춤"),
    stage ? h("span", {class: "opt"}, ` · ${stage}`) : st.phase === "warm" ? h("span", {class: "opt"}, " · 과거 채우는 중") : null,
    cd ? h("span", {class: "tb-cd"}, " · ", ui.cdk, ui.cd) : null, h("span", {class: "car", "aria-hidden": "true"}, "▾"));
  b.setAttribute("aria-label", `실시간 ${d != null ? `${d}일째` : "전"}${stage ? `, 지금 단계 ${stage}` : ""}${cd ? `, 다음 처리 ${cd}` : ""}. 누르면 목표와 처리 시각`);
  b.title = st.live_start_ms ? `실시간 시작 ${fmt.kst(st.live_start_ms)} KST` : "";
}
function tickCountdown() {
  if (!ui.cd || document.visibilityState === "hidden") return;
  const cd = countdown(D.status);
  if (!cd || !ui.cd.isConnected) { paintPill(); return; }
  ui.cd.textContent = cd;
  ui.cdk.hidden = cd === "처리 중";
}
function pillPanel() {
  const st = D.status && !isMissing(D.status) ? D.status : null;
  const g = D.home && !isMissing(D.home) ? D.home.goal : null;
  const stages = g && Array.isArray(g.stages_ko) ? g.stages_ko : ["설치", "데모 진행", "우리 기준 통과", "확인 기간", "실전 후보"];
  const at = g && Number.isInteger(Number(g.stage)) ? Number(g.stage) : -1;
  return h("div", {class: "stack tight"},
    g && g.line_ko ? h("p", {class: "tb-lead"}, g.line_ko) : h("p", {class: "muted"}, "목표 자료 준비 중"),
    h("ol", {class: "steps dl-steps", "aria-label": "단계"}, stages.map((x, i) => h("li", {class: i < at ? "done" : i === at ? "now" : "",
      "aria-current": i === at ? "step" : null}, `${i + 1}. ${x}`))),
    h("dl", {class: "kv"},
      h("div", null, h("dt", null, "실시간 시작"), h("dd", null, st && st.live_start_ms ? `${fmt.kst(st.live_start_ms)} (D+${liveDays(st) ?? 0})` : "준비 중")),
      h("div", null, h("dt", null, "12/31까지"), h("dd", null, g && g.days_left != null ? `${fmt.int(g.days_left)}일` : "—")),
      h("div", null, h("dt", null, "마지막 처리"), h("dd", null, st && st.last_tick_ms ? `${fmt.hms(st.last_tick_ms)} (${fmt.ago(st.last_tick_ms)})` : "—")),
      h("div", null, h("dt", null, "다음 처리"), h("dd", null, st && st.next_tick_ms ? fmt.hms(st.next_tick_ms) : "—"))),
    h("p", {class: "note"}, "엔진은 15분봉이 닫힐 때마다 한 번 계산합니다 (처리). D+n은 실시간 시작부터 지난 날 수입니다."),
    h("div", {class: "row wrap"}, h("a", {class: "btn-line", href: "#/path"}, "졸업 길"), h("a", {class: "btn-line", href: "#/judge"}, "판정"),
      h("a", {class: "btn-line", href: "#/home"}, "홈 (요약)")));
}

// ---------------------------------------------------------------- 보기 설정 (글자 크기, 메뉴 위치, 화면 색) and the 가 button
function viewPanel() {
  return h("div", {class: "stack tight tb-view"},
    textSwitch((id) => { paintCycles(); if (ui.onText) ui.onText(id); }),
    navSwitch((id) => { if (ui.onNav) ui.onNav(id); }),
    skinSwitch((id) => { if (ui.onSkin) ui.onSkin(id); }),
    h("p", {class: "note"}, "이 기기에만 기억합니다. 메뉴를 왼쪽에 두는 것은 화면이 넓을 때(1000px 이상)만이고, 휴대폰에서는 늘 위에 있습니다."));
}
let cycles = [];
function paintCycle(b) {
  const id = textNow();
  const ko = (TEXT_SIZES.find((x) => x.id === id) || TEXT_SIZES[0]).ko;
  b.dataset.text = id;
  b.lastChild.textContent = ko;
  b.setAttribute("aria-label", `글자 크기: ${ko} (누르면 바뀝니다)`);
}
function paintCycles() {
  cycles = cycles.filter((b) => b.isConnected);        // a redrawn menu row leaves its old copy behind
  cycles.forEach(paintCycle);
}
/** "가 보통": each tap goes 보통 → 크게 → 아주 크게 → 보통 (remembered on this device). */
function textCycle(cls) {
  const b = h("button", {type: "button", class: ["tb-btn", "tb-text", cls], title: "글자 크기: 이 기기에만 기억합니다", onclick: () => {
    const i = TEXT_SIZES.findIndex((x) => x.id === textNow());
    const next = TEXT_SIZES[(i + 1) % TEXT_SIZES.length].id;
    local.set("text", next);
    applyText(next);
    paintCycles();
    if (ui.which === "view") paintPop();
    if (ui.onText) ui.onText(next);
  }}, h("span", {class: "tb-ga", "aria-hidden": "true"}, "가"), h("small", {"aria-hidden": "true"}, ""));
  paintCycle(b);
  cycles.push(b);
  return b;
}
const viewBtn = (cls) => popBtn("view", ["tb-view", cls], "보기 설정: 글자 크기, 메뉴 위치, 화면 색", h("span", {"aria-hidden": "true"}, "⚙"));

// ---------------------------------------------------------------- ★ favourites
function favPanel() {
  const f = favs();
  const menu = ui.menu();
  const names = new Map((D.accts || []).map((a) => [a.id, a.name || a.id]));
  const row = (kind, id, label, href) => h("li", {class: "tb-fav"}, h("a", {href}, h("span", {class: "tb-fk"}, kind === "page" ? "화면" : "계좌"), h("b", null, label)),
    h("button", {type: "button", class: "linkish", "aria-label": `${label} 즐겨찾기에서 빼기`, onclick: () => { setFav(kind, id, false); paintPop(); }}, "빼기"));
  const pages = f.page.map((id) => { const m = menu.find((x) => x.id === id); return m ? row("page", id, m.ko, `#/${id}`) : null; }).filter(Boolean);
  const accts = f.account.map((id) => row("account", id, names.get(id) || id, `#/account/${encodeURIComponent(id)}`));
  if (!pages.length && !accts.length) {
    return h("div", {class: "stack tight"}, h("p", {class: "muted"}, "아직 없습니다."),
      h("p", {class: "note"}, "화면 제목 옆이나 계좌 이름 옆의 ☆을 누르면 여기 모입니다. 이 기기에만 기억합니다."));
  }
  return h("div", {class: "stack tight"},
    pages.length ? [h("p", {class: "tb-sec"}, "화면"), h("ul", {class: "tb-list"}, pages)] : null,
    accts.length ? [h("p", {class: "tb-sec"}, "계좌"), h("ul", {class: "tb-list"}, accts)] : null,
    h("p", {class: "note"}, "찾기(/)를 빈칸으로 열어도 즐겨찾기가 먼저 나옵니다."));
}
function loadAccts() {
  getJSON("/api/accounts").then((d) => { D.accts = isMissing(d) ? [] : d.accounts || []; if (ui.which === "fav") paintPop(); }).catch(() => {});
}

// ---------------------------------------------------------------- 자는 동안
/** The last visit's end is stored when the page is hidden or closed after at least a minute in view (a quick reload
 *  keeps the old time, so 자는 동안 is still there after a refresh) and by "다 봤어요"; a tab hidden for 30 minutes or
 *  more starts a new 자는 동안 from the moment it was hidden. */
function initSince() {
  const v = local.get(SINCE_KEY, null);
  firstVisit = !(typeof v === "number" && Number.isFinite(v) && v > 0);
  since = firstVisit ? Date.now() - FIRST_LOOK : v;
  let shownAt = document.visibilityState === "visible" ? Date.now() : null;
  const leave = () => {
    const now = Date.now();
    if (shownAt && now - shownAt >= 60000) local.set(SINCE_KEY, now);
    shownAt = null;
    hiddenAt = now;
  };
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") { leave(); return; }
    if (hiddenAt && Date.now() - hiddenAt >= AWAY_GAP) { since = hiddenAt; firstVisit = false; paintBadges(); }
    hiddenAt = null;
    shownAt = Date.now();
  });
  window.addEventListener("pagehide", () => { if (shownAt) leave(); });
}
function awayEvents() {
  const t = since;
  const all = D.trades && !isMissing(D.trades) ? D.trades.trades || [] : [];
  const trades = all.filter((x) => x.status === "closed" && Number(x.exit_ms) > t).sort((a, b) => b.exit_ms - a.exit_ms);
  const closedAll = all.filter((x) => x.status === "closed");
  const oldest = closedAll.length ? Math.min(...closedAll.map((x) => Number(x.exit_ms) || Infinity)) : null;
  const cut = all.length >= 300 && oldest != null && oldest > t;      // the file holds the newest 300 only
  const sw = D.home && !isMissing(D.home) ? (D.home.recent_switches || []).filter((x) => Number(x.t_ms) > t) : [];
  const conf = D.judge && !isMissing(D.judge) ? D.judge.confirm || [] : [];
  const passes = conf.filter((c) => Number(c.start_ms) > t);
  const decided = conf.filter((c) => c.decided_ms && Number(c.decided_ms) > t && c.status !== "confirming");
  return {trades, cut, sw, passes, decided, count: trades.length + sw.length + passes.length + decided.length};
}
function awayPanel() {
  const ev = awayEvents();
  const have = D.trades || D.home || D.judge;
  const seen = h("button", {type: "button", class: "btn-y", onclick: () => {
    since = Date.now(); firstVisit = false; local.set(SINCE_KEY, since); paintBadges(); paintPop();
  }}, "다 봤어요");
  const head = h("p", {class: "tb-lead"}, firstVisit ? "처음 오셔서 지난 8시간을 보여 드립니다." : `${fmt.kst(since)}부터 (${fmt.ago(since)}) 바뀐 것`);
  if (!have) return h("div", {class: "stack tight"}, head, h("p", {class: "muted"}, "자료를 읽는 중이거나 아직 준비 중입니다."));
  const secs = [];
  if (ev.trades.length) {
    const ents = entries(ev.trades);
    const sum = ents.reduce((a, x) => a + x.pnl, 0);
    const wins = ents.filter((x) => x.pnl > 0).length;
    const bestT = ents.reduce((a, x) => (a && a.pnl >= x.pnl ? a : x), null);
    const worstT = ents.reduce((a, x) => (a && a.pnl <= x.pnl ? a : x), null);
    secs.push(h("section", {class: "tb-sec2"}, h("p", {class: "tb-sec"}, `닫힌 거래 ${fmt.int(ents.length)}건${ev.cut ? "+" : ""}`,
      h("span", {class: "muted"}, ` (배수 줄로는 ${fmt.int(ev.trades.length)}줄)`)),
      h("p", null, `이김 ${fmt.int(wins)} · 짐 ${fmt.int(ents.length - wins)} · 모든 줄 합계 `,
        h("b", {class: ["num", fmt.tone(sum, fmt.money(sum))]}, fmt.money(sum, true))),
      h("ul", {class: "tb-list"}, [bestT, worstT].filter((x, i, a) => x && a.indexOf(x) === i).map((x) => tradeLine(x, x === bestT ? "가장 좋은" : "가장 나쁜"))),
      h("ul", {class: "tb-list"}, ents.slice(0, 5).map((x) => tradeLine(x))),
      ev.cut ? h("p", {class: "note"}, "거래 파일은 최근 300건만 담아서, 그 전 것은 거래 기록 화면에서 보세요.") : null,
      h("a", {class: "linkish", href: "#/trades"}, "거래 기록 전체")));
  }
  if (ev.passes.length || ev.decided.length) {
    secs.push(h("section", {class: "tb-sec2"}, h("p", {class: "tb-sec"}, "판정"), h("ul", {class: "tb-list"},
      ev.passes.map((c) => h("li", null, h("span", {class: "pp accent"}, "기준 통과"), " ", lineLink(c), h("span", {class: "muted"}, ` · ${fmt.kst(c.start_ms)} 확인 기간 시작`))),
      ev.decided.map((c) => h("li", null, h("span", {class: ["pp", c.status === "confirmed" ? "good" : "bad"]}, c.status === "confirmed" ? "실전 후보" : "확인 실패"), " ",
        lineLink(c), h("span", {class: "muted"}, ` · ${fmt.kst(c.decided_ms)}`))))));
  }
  if (ev.sw.length) {
    secs.push(h("section", {class: "tb-sec2"}, h("p", {class: "tb-sec"}, `설정 교체 ${fmt.int(ev.sw.length)}번`), h("ul", {class: "tb-list"},
      ev.sw.slice(0, 5).map((d) => h("li", null, h("span", {class: "muted num"}, fmt.kst(d.t_ms)), " ",
        (d.id || d.account) ? h("a", {href: `#/account/${encodeURIComponent(d.id || d.account)}`}, d.name || d.id || d.account) : null,
        h("span", {class: "muted"}, ` → ${d.to_ko || "—"}`)))),
    h("p", {class: "note"}, "홈 파일은 최근 교체 10개만 담습니다.")));
  }
  return h("div", {class: "stack tight"}, h("div", {class: "row wrap"}, head, h("span", {class: "grow"}), seen),
    secs.length ? secs : h("p", {class: "muted"}, "그 사이에 닫힌 거래, 교체, 판정 변화가 없습니다."));
}
const lineLink = (c) => h("a", {href: `#/account/${encodeURIComponent(c.id)}`}, `${c.name || c.id} ${fmt.lev(c.L)}`);
/** Closed trade rows (one per leverage line) -> one per account entry (the lines share it; the key's last part is the
 *  leverage), newest first, with the lines' P&L summed and the lowest leverage's row kept for the chart link. */
function entries(rows) {
  const by = new Map();
  for (const x of rows) {
    const k = `${x.account}|${String(x.key || "").split("|").slice(0, -1).join("|")}`;
    const e = by.get(k);
    if (!e) by.set(k, {...x, pnl: Number(x.pnl) || 0, levs: [x.L]});
    else {
      e.pnl += Number(x.pnl) || 0;
      e.levs.push(x.L);
      if (Number(x.L) < Number(e.L)) Object.assign(e, {key: x.key, L: x.L, reason: x.reason});
    }
  }
  return [...by.values()].sort((a, b) => b.exit_ms - a.exit_ms);
}
function tradeLine(x, tag) {
  return h("li", {class: "tb-tr"}, tag ? h("span", {class: "pp thin"}, tag) : h("span", {class: "muted num"}, fmt.hm(x.exit_ms)), " ",
    x.account && x.key ? h("a", {href: `#/trade/${encodeURIComponent(x.account)}/${encodeURIComponent(x.key)}`}, `${x.name || x.account}`) : h("b", null, x.name || x.account || "—"),
    h("span", {class: "muted"}, ` ${fmt.coin(x.coin)} ${sideKo(x.side)} ${reasonKo(x.reason)} · ${x.levs.length}줄 `),
    h("b", {class: ["num", fmt.tone(x.pnl, fmt.money(x.pnl))]}, fmt.money(x.pnl, true)));
}

// ---------------------------------------------------------------- the bell (telegram.json)
function bellSeen() {
  const v = local.get(BELL_KEY, null);
  return typeof v === "number" && Number.isFinite(v) ? v : Date.now() - 24 * HOUR;
}
function tgItems() { return D.tg && !isMissing(D.tg) ? D.tg.items || [] : []; }
function markBellSeen() {
  const top = tgItems().reduce((a, x) => Math.max(a, Number(x.ts_ms) || 0), 0);
  if (top) local.set(BELL_KEY, top);
  paintBadges();
}
function bellPanel() {
  const items = tgItems().slice(0, 20);
  if (!D.tg) return h("p", {class: "muted"}, "알림 기록을 읽는 중이거나 아직 준비 중입니다.");
  if (!items.length) return h("p", {class: "muted"}, "기록 없음");
  return h("div", {class: "stack tight"}, h("ul", {class: "tb-tg"}, items.map((x) => h("li", {class: ["tb-tgi", x.status === "error" ? "err" : ""]},
    h("div", {class: "tb-tgh"}, h("span", {class: "pp thin"}, tgKindKo(x.kind)), h("span", {class: "muted num"}, fmt.kst(x.ts_ms)),
      x.status && x.status !== "sent" ? h("span", {class: ["pp", x.status === "error" ? "bad" : "warn"]}, TG_STATUS_KO[x.status] || x.status) : null),
    h("p", {class: "tb-tgt"}, String(x.text ?? ""))))),
  h("a", {class: "btn-line", href: "#/telegram"}, "알림 기록 전체"));
}

// ---------------------------------------------------------------- the sound
let actx = null;
const soundOn = () => local.get(SOUND_KEY, false) === true;
function audio() {
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) return null;
  if (!actx) { try { actx = new AC(); } catch (e) { actx = null; } }
  if (actx && actx.state === "suspended") actx.resume().catch(() => {});
  return actx;
}
/** One short soft beep (WebAudio; nothing to download). */
export function beep(freq = 880) {
  const a = audio();
  if (!a) return;
  try {
    const t = a.currentTime + 0.01;
    const o = a.createOscillator(), g = a.createGain();
    o.type = "sine";
    o.frequency.setValueAtTime(freq, t);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(0.16, t + 0.015);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.2);
    o.connect(g);
    g.connect(a.destination);
    o.start(t);
    o.stop(t + 0.22);
  } catch (e) { /* no sound: never an error in the page */ }
}
function paintSnd(b) {
  const on = soundOn();
  b.dataset.state = on ? "on" : "off";
  b.setAttribute("aria-pressed", String(on));
  b.title = on ? "새 거래 소리 켜짐 (누르면 끔)" : "새 거래 소리 꺼짐 (누르면 켬: 이 화면이 열려 있는 동안 새 거래마다 짧게 삑)";
  b.setAttribute("aria-label", b.title);
}
function paintSound() {
  ui.snd = ui.snd.filter((b) => b.isConnected);       // a redrawn menu row leaves its old copy behind
  ui.snd.forEach(paintSnd);
}
function soundBtn(cls) {
  const b = h("button", {type: "button", class: ["snd-btn", "tb-snd", cls], dataset: {state: "off"}, onclick: () => {
    const on = !soundOn();
    local.set(SOUND_KEY, on);
    if (on) beep(990);                       // the click lets the browser start the sound, and says it works
    paintSound();
  }}, h("span", {class: "snd-ic", "aria-hidden": "true"}));
  paintSnd(b);
  ui.snd.push(b);
  return b;
}

// ---------------------------------------------------------------- badges
function badge(el, n) {
  if (!el) return;
  el.hidden = !(n > 0);
  el.textContent = n > 99 ? "99+" : String(n || 0);
}
function paintBadges() {
  const ev = awayEvents();
  // the number counts what the owners act on (판정 changes, setting switches); closed trades alone (dozens a night over
  // 200 lines) only light a dot
  const big = ev.count - ev.trades.length;
  badge(ui.awayN, big);
  if (ui.awayN && !big && ev.trades.length) { ui.awayN.hidden = false; ui.awayN.textContent = ""; }
  if (ui.awayN) ui.awayN.classList.toggle("dot", !big && ev.trades.length > 0);
  if (ui.away) {
    const t = ev.count ? `자는 동안: ${fmt.ago(since)}부터 닫힌 거래 ${ev.trades.length}건, 판정·교체 ${big}가지` : "자는 동안: 지난번 본 뒤로 바뀐 것 없음";
    ui.away.title = t;
    ui.away.setAttribute("aria-label", t);
  }
  const seen = bellSeen();
  const n = tgItems().filter((x) => Number(x.ts_ms) > seen).length;
  badge(ui.bellN, n);
  if (ui.bell) {
    const t = n ? `알림: 새 메시지 ${n}개` : "알림: 새 메시지 없음";
    ui.bell.title = t;
    ui.bell.setAttribute("aria-label", t);
  }
}

// ---------------------------------------------------------------- data (on a new tick only)
async function load(key) {
  const get = (p) => getJSON(p).catch(() => undefined);
  const [tr, hm, jd, tg] = await Promise.all([get("/api/trades"), get("/api/home"), get("/api/judge"), get("/api/telegram")]);
  if (tr !== undefined) {
    const keys = new Set((isMissing(tr) ? [] : tr.trades || []).map((x) => `${x.account}|${x.key}`));
    if (D.keys && soundOn() && [...keys].some((k) => !D.keys.has(k))) beep();
    D.keys = keys;
    D.trades = tr;
  }
  if (hm !== undefined) D.home = hm;
  if (jd !== undefined) D.judge = jd;
  if (tg !== undefined) D.tg = tg;
  if (tr === undefined && hm === undefined) D.key = null;          // try again on the next status poll
  else D.key = key;
  paintPill();
  paintBadges();
  if (ui.which && ui.which !== "fav") paintPop();
}

/** app.js: after every /api/status poll (null when it failed). */
export function onStatus(st) {
  D.status = st;
  paintPill();
  if (!st || isMissing(st)) return;
  const key = `${st.last_tick_ms}|${st.generated_ms}`;
  if (key !== D.key) { D.key = key; load(key); }
}

// ---------------------------------------------------------------- the buttons
function popBtn(which, cls, label, kids) {
  const b = h("button", {type: "button", class: ["tb-btn", ...[].concat(cls)], "aria-haspopup": "dialog", "aria-expanded": "false", "aria-controls": "tb-pop",
    "aria-label": label, title: label, dataset: {pop: which}, onclick: () => openPop(which, b)}, kids);
  return b;
}
const findBtn = (cls) => h("button", {type: "button", class: ["tb-btn", "tb-find", cls], title: "찾기: 화면·계좌 (단축키 /)", "aria-label": "찾기 (단축키 /)",
  "aria-keyshortcuts": "/", onclick: () => openFind()}, h("span", {"aria-hidden": "true"}, "⌕"), h("span", {class: "tb-t"}, "찾기"), h("kbd", null, "/"));
const favBtn = (cls) => popBtn("fav", ["tb-star", cls], "즐겨찾기 목록", h("span", {"aria-hidden": "true"}, "★"));

/** initTopbar({menu: () => [{id, ko}]}) -> builds the top bar's tools into #toptools and the pill (#livechip). */
export function initTopbar(o) {
  ui.menu = o.menu || (() => []);
  ui.onText = o.onText || null;
  ui.onNav = o.onNav || null;
  ui.onSkin = o.onSkin || null;
  ui.pill = document.getElementById("livechip");
  if (ui.pill) {
    ui.pill.dataset.pop = "pill";
    ui.pill.setAttribute("aria-haspopup", "dialog");
    ui.pill.setAttribute("aria-expanded", "false");
    ui.pill.setAttribute("aria-controls", "tb-pop");
    ui.pill.addEventListener("click", () => openPop("pill", ui.pill));
  }
  ui.awayN = h("span", {class: "tb-n", hidden: true});
  ui.away = popBtn("away", "tb-away", "자는 동안", [icon(MOON), ui.awayN]);
  ui.bellN = h("span", {class: "tb-n", hidden: true});
  ui.bell = popBtn("bell", "tb-bell", "알림", [icon(BELL), ui.bellN]);
  const box = document.getElementById("toptools");
  if (box) put(box, findBtn("tb-wide"), favBtn("tb-wide"), textCycle("tb-big"), viewBtn("tb-big"), ui.away, ui.bell, soundBtn("tb-wide"));
  initSince();
  paintSound();
  paintPill();
  paintCycles();
  onFavs(() => { if (ui.which === "fav") paintPop(); });
  setInterval(tickCountdown, 1000);
}

/** Copies in the menu row for narrower windows (demo4b.css): 찾기 and ★ at its start below 560 px (kept in view while
 *  the row scrolls; the top bar has no room for them there); 소리 (below 560 px), 가 and ⚙ (below 1000 px) at its end. */
export const stripLead = () => [findBtn("tb-phone"), favBtn("tb-phone")];
export const stripTools = () => [soundBtn("tb-phone"), textCycle("tb-small"), viewBtn("tb-small")];
