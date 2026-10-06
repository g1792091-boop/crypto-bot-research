// The shell around every screen: the 5-group nav (top on a PC, each group with a dropdown of all its screens,
// core/topnav.js; or the left rail by choice, core/rail.js + core/navpos.js; bottom tab bar on a phone), the current
// group's sub tabs, the one-line "D+n/30 · 판정 날짜 · 관찰 ~날짜" chip that expands to the rules, the ONE health dot (red when
// something is down; it pulses once per real new heartbeat), the speaker button of the live sound (core/sound.js) and
// the sticky red banner for critical alerts (bust, liquidation burst, feed stale).
import {h, put, clear, $, local} from "./dom.js";
import {api, bus, stream} from "./api.js";
import {store} from "./store.js";
import {features} from "./features.js";
import {GROUPS, SCREENS, href, icon, parseHash, screenIcon, landing} from "./routes.js";
import {mmdd, kst} from "./fmt.js";
import {expand, pulseLive} from "./motion.js";
import {soundButton, startSound} from "./sound.js";
import {bellButton, startBell} from "./bell.js";
import {setMethod, botsKo, methodKo} from "./ui.js";
import {criticalLines} from "./alerts.js";
import {skinSwitch} from "./skin.js";
import {textCycle, textSwitch} from "./textsize.js";
import {remount} from "./router.js";
import {renderRail, visibleScreens} from "./rail.js";
import {renderGroups} from "./topnav.js";
import {navPosSwitch} from "./navpos.js";
import {openFind} from "./find.js";

const badges = {};       // screen -> true (a small dot on its tab, e.g. new room messages)

function renderNav() {
  const p = parseHash(location.hash);
  const meta = SCREENS[p.name] || SCREENS.home;
  const gid = meta.group;
  const link = (g, cls) => h("a", {href: href(visibleScreens(g)[0] || g.screens[0]), class: cls, "aria-current": g.id === gid ? "page" : null,
    dataset: {group: g.id}}, icon(g.id), h("span", null, g.ko),
    g.screens.some((n) => badges[n]) ? h("i", {class: "ndot", "aria-label": "새 소식"}) : null);
  // the top bar's groups, each opening a list of all its screens (one click to any screen; core/topnav.js)
  renderGroups(p.name, badges);
  // the left rail (a choice, "메뉴 위치", >= 1200 px) and the "묶음 › 화면" line that stands in for the group bar there
  renderRail(p.name, badges, () => remount());
  // the brand mark opens the start screen (the 터미널; the phone's 차트), named as such: 홈 is one click away in its group
  const brand = $(".brand");
  if (brand) {
    const to = landing();
    brand.setAttribute("href", href(to));
    brand.setAttribute("aria-label", `Paper v4 첫 화면 (${SCREENS[to].ko})`);
    brand.title = `첫 화면: ${SCREENS[to].ko}`;
  }
  const crumb = $("#crumb");
  if (crumb) put(crumb, h("span", {class: "crumb-g"}, (GROUPS.find((x) => x.id === gid) || GROUPS[0]).ko), h("span", {class: "crumb-s", "aria-hidden": "true"}, "›"),
    h("b", null, meta.ko));
  put($("#botbar"), GROUPS.map((g) => link(g)));
  const g = GROUPS.find((x) => x.id === gid) || GROUPS[0];
  put($("#subtabs"), textCycle(() => remount()), findTab(), visibleScreens(g).map((n) => h("a", {href: href(n), "aria-current": n === p.name ? "page" : null, dataset: {screen: n}},
    SCREENS[n].ko, SCREENS[n].soft && !features[SCREENS[n].soft] ? h("span", {class: "pp thin", style: {marginLeft: "6px", opacity: ".75"}, title: "아직 켜지지 않음"}, "꺼짐") : null, badges[n] ? h("i", {class: "ndot", "aria-label": "새 소식"}) : null)),
  // 글자 크기 (보통 / 크게 / 아주 크게, core/textsize.js) at the end of every group's tabs, so it is one tap away on the
  // screen being read (on a phone the one-button textCycle at the start of the row stands in for it); the screen colours (AI / 클래식, core/skin.js) and the old dashboard (served at /v3; '/' is this
  // page) stay one tap away next to it at the end of the 서버 group's menu
  textSwitch(() => remount()),
  g.id === "server" ? skinSwitch(() => remount()) : null,
  g.id === "server" ? h("a", {class: "oldui", href: "/v3", title: "지금까지 쓰던 대시보드 (/v3, 같은 로그인)"}, "예전 화면", h("span", {"aria-hidden": "true"}, " ↗")) : null,
  // 메뉴 위치 위 / 왼쪽 (core/navpos.js) at the very end: shown from 1200 px, where the left rail can be chosen
  navPosSwitch());
}
/** 찾기 at the start of the phone's sub-tab row (the top bar has no room for it under 460 px): two taps to any
 *  account or strategy. Shown below 760 px only (core/nav.css). */
const findTab = () => h("button", {type: "button", class: "findsub", "aria-label": "찾기: 화면, 매매법, 계좌", onclick: () => openFind()},
  screenIcon("analysis"), "찾기");
export function setBadge(screen, on) {
  if (!!badges[screen] === !!on) return;
  badges[screen] = !!on;
  renderNav();
}

// ---------------------------------------------------------------- the D+n chip and its rules
function chipText(s) {
  if (!s || s.start == null) return {main: "봇 시작 전", opt: "", obs: ""};
  const rs = s.restart;
  const d = rs && rs.ready ? `D+${rs.day}/${rs.of}` : `D+${(s.day || 1) - 1}/${s.period_days || 30}`;
  const verdict = rs && rs.ready ? rs.verdict_mmdd : mmdd(s.next_checkpoint && s.next_checkpoint.ts);
  const obs = s.observing && s.observe_until ? ` · 관찰 ~${mmdd(s.observe_until - 1)}` : "";
  return {main: d, opt: ` · 판정 ${verdict}`, obs};
}
function renderChip(s) {
  const t = chipText(s);
  const b = $("#dchip");
  put(b, h("b", null, t.main), h("span", {class: "opt"}, t.opt), t.obs ? h("span", {class: "obs"}, t.obs) : null,
    h("span", {class: "car", "aria-hidden": "true"}, "▾"));
  b.setAttribute("aria-label", `실험 ${t.main}${t.opt}${t.obs}. 누르면 규칙을 펼칩니다`);
  const panel = $("#rules");
  if (!panel.hidden) renderRules(s);
}
function renderRules(s) {
  const panel = $("#rules");
  if (!s || s.start == null) { put(panel, h("div", {class: "rules-in"}, "봇이 아직 첫 계좌를 만들지 않았습니다.")); return; }
  const rs = s.restart || {};
  const cp = s.next_checkpoint || {};
  const verdictTs = rs.ready ? rs.verdict_ts : cp.ts;
  const items = [
    h("li", null, h("b", null, rs.ready ? rs.text : `실험 ${s.day}일째`), ` · ${kst(s.start)} 시작 (한국 시각)`),
    h("li", null, h("b", null, `판정 ${mmdd(verdictTs)} 09:00`),
      ` · 그날 계좌마다 ${botsKo()}와 비교해서 합격·불합격을 정합니다 (${methodKo()}). 그 전의 모든 비교는 '참고'입니다. 거래가 30건이 안 된 계좌는 '보류'입니다.`),
    h("li", null, "4시간봉 계좌는 관찰용(판정 밖), 동전 봇은 비교 기준입니다."),
    s.observing ? h("li", null, h("b", null, `관찰 기간 ${mmdd(s.observe_until - 1)}까지`), " · 에이전트는 기록만 하고 새 계좌를 제안하지 않습니다.")
      : h("li", null, "관찰 기간이 끝났습니다: 에이전트가 새 계좌를 제안할 수 있고, 두 분이 승인해야 시작합니다."),
    rs.rules_ko ? h("li", null, h("b", null, `${rs.rules_label || "규칙"} · `), rs.rules_ko,
      rs.doc ? [" · ", h("a", {href: rs.doc, target: "_blank", rel: "noopener"}, "원문 보기")] : null) : null,
    h("li", null, "모든 계좌는 모의(가상 돈)입니다. AI 직원은 회의만 하고 주문하지 않습니다."),
  ];
  put(panel, h("div", {class: "rules-in"}, h("ul", null, items),
    h("div", {class: "row wrap"}, h("a", {class: "btn-line", href: href("checkpoint")}, "판정 화면"), h("a", {class: "btn-line", href: href("howto")}, "어떻게 돌아가나"),
      h("span", {class: "grow"}), h("button", {class: "btn-line", type: "button", onclick: () => setRules(false, true)}, "닫기"))));
}
/** Open / close the rules panel (it lives in the sticky header: it closes itself on a route change and when the
 *  page is scrolled on, so it never keeps covering the screen). */
let rulesY = 0;
function setRules(open, focusChip) {
  const chip = $("#dchip"), panel = $("#rules");
  if ((chip.getAttribute("aria-expanded") === "true") === open) return;
  chip.setAttribute("aria-expanded", String(open));
  if (open) { renderRules(store.get("summary")); rulesY = window.scrollY; }
  expand(panel, open);
  if (!open && focusChip) chip.focus({preventScroll: true});
}

// ---------------------------------------------------------------- the health dot and the critical banner
const st = {health: null, alerts: [], trades: [], streamErrSince: null};
/** An account's kind from the shared board (the live stream's trade rows carry none). */
function kindOf(id) {
  const b = store.get("board");
  if (!b) return null;
  if (!b._kinds) { try { Object.defineProperty(b, "_kinds", {value: new Map((b.accounts || []).map((a) => [a.account_id, a.kind]))}); } catch { return null; } }
  return b._kinds.get(id) || null;
}
const KO = {ok: "정상", warn: "확인할 것 있음", bad: "문제 있음", unknown: "확인 중"};
function level() {
  const hb = stream.heartbeat ? stream.heartbeat[0] : null;
  const streamDown = st.streamErrSince && Date.now() - st.streamErrSince > 30000;
  const lines = critical();
  if (lines.some((l) => l.kind === "stale") || streamDown || (st.health && st.health.level === "bad")) return "bad";
  if (!st.health) return hb ? "ok" : "unknown";
  return st.health.level === "warn" ? "warn" : "ok";
}
function critical() {
  return criticalLines({health: st.health, alerts: st.alerts, trades: st.trades, hb: stream.heartbeat,
    streamOk: stream.state === "open", now: Date.now(), kindOf});
}
function renderHealth() {
  const lv = level();
  const dot = $("#hdot");
  dot.dataset.level = lv;
  const first = st.health && (st.health.problems || [])[0];
  const down = st.streamErrSince && Date.now() - st.streamErrSince > 30000;
  dot.title = `서버 상태: ${KO[lv]}${down ? " · 실시간 연결 끊김(다시 연결 중)" : ""}${first ? " · " + first : ""}`;
  dot.setAttribute("aria-label", dot.title + ". 누르면 서버 화면");
  renderBanner();
}
function renderBanner() {
  const dismissed = new Set(local.get("crit-dismissed", []));
  const lines = critical().filter((l) => !(l.dismissable && dismissed.has(l.id)));
  const box = $("#crit");
  const sig = lines.map((l) => l.id + "|" + l.text).join("\n");
  if (sig === box._sig) return;               // unchanged: keep the DOM (and the focus) as it is
  box._sig = sig;
  if (!lines.length) { box.hidden = true; clear(box); return; }
  box.hidden = false;
  put(box, h("div", {class: "crit-in"}, lines.map((l) => h("div", {class: "crit-row"},
    h("span", {class: "ic", "aria-hidden": "true"}, "!"), h("span", {class: "grow"}, l.kind === "stale" ? h("b", null, "끊김 · ") : null, l.text),
    h("span", {class: "acts"}, h("a", {href: l.href}, "자세히"),
      l.dismissable ? h("button", {type: "button", onclick: () => {
        const d = new Set(local.get("crit-dismissed", [])); d.add(l.id); local.set("crit-dismissed", [...d].slice(-50)); renderBanner();
      }}, "확인") : null)))));
}

async function loadRecentTrades() {
  try { st.trades = await api("/api/trades?limit=200"); } catch (e) { /* keep */ }
  renderHealth();
}

export function startShell() {
  renderNav();
  bus.on("route", renderNav);
  bus.on("features", renderNav);
  // 메뉴 위치 changed (the control here, in the rail, or the settings panel through setNavPos): the menu and the screen
  // are drawn again (the screen's width changes by the rail's)
  bus.on("navpos", (id) => {
    const fromSwitch = !!(document.activeElement && document.activeElement.closest && document.activeElement.closest(".navsw"));
    renderNav(); remount();
    // a keyboard user who switched keeps the focus on the switch, now in its other place (the rail's foot / the tabs)
    if (fromSwitch) { const b = [...document.querySelectorAll(`.navsw button[data-nav="${id}"]`)].find((x) => x.offsetParent !== null); if (b) b.focus({preventScroll: true}); }
  });
  const chip = $("#dchip");
  chip.addEventListener("click", () => setRules(chip.getAttribute("aria-expanded") !== "true"));
  bus.on("route", () => setRules(false));
  window.addEventListener("scroll", () => { if (chip.getAttribute("aria-expanded") === "true" && Math.abs(window.scrollY - rulesY) > 120) setRules(false); }, {passive: true});
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && chip.getAttribute("aria-expanded") === "true") setRules(false, true); });
  $("#hdot").addEventListener("click", () => { location.hash = href("server"); });
  store.watch("summary", (s) => { if (s) { setMethod(s.restart); renderChip(s); } });
  store.watch("health", (v) => { if (v) { st.health = v; renderHealth(); } });
  store.watch("status", (v) => { if (v && Array.isArray(v.alerts)) { st.alerts = v.alerts; renderHealth(); } });
  store.watch("board", () => {});
  bus.on("alerts", (a) => { st.alerts = [...a, ...st.alerts].slice(0, 100); renderHealth(); });
  bus.on("trades", (t) => { st.trades = [...t, ...st.trades].slice(0, 300); renderHealth(); });
  bus.on("stream:state", (s) => { st.streamErrSince = s === "error" ? (st.streamErrSince || Date.now()) : null; renderHealth(); });
  // the live dot breathes once per REAL new heartbeat (the stream repeats the last one every 3 s: same ts, no pulse)
  let hbTs = null;
  bus.on("heartbeat", (hb) => {
    renderHealth();
    const ts = hb && hb[0];
    if (ts != null && hbTs != null && ts !== hbTs) pulseLive($("#hdot"));
    if (ts != null) hbTs = ts;
  });
  // the speaker (core/sound.js): before the health dot; off until the first tap, then remembered per device
  $("#hdot").before(soundButton());
  startSound();
  // the approval bell (core/bell.js): proposals waiting for the owners, before the speaker
  ($(".snd") || $("#hdot")).before(bellButton());
  startBell();
  setInterval(renderHealth, 15000);
  loadRecentTrades();
}
