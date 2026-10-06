// '새 버전 준비됨 · 눌러서 새로고침' (review 10/06, addition 7). The page knows the fingerprint of the code it was opened
// with (<meta name="pb-ver">, dash/assets.py); the server says what is on disk now (/api/time ver, core/api.js
// syncClock: every 10 minutes, when the page is shown again after a minute away, and when the live stream comes back
// after a gap, e.g. the dashboard restarted for an update). When they differ, a small chip offers the reload. A tab
// nobody is looking at reloads by itself, on the same screen (the address keeps the #/screen): a hidden tab at once,
// a shown one after 5 minutes without a touch, a click, a key or a scroll (the 터미널 or a TV left open), unless a text
// box has something typed in it. Nothing is invented: no chip without a real, different fingerprint from the server.
import {h} from "./dom.js";
import {bus, syncClock} from "./api.js";

export const IDLE_RELOAD_MS = 5 * 60 * 1000;
export const AUTO_AGAIN_MS = 10 * 60 * 1000;
const AWAY_CHECK_MS = 60 * 1000;
const AUTO_KEY = "pb4-autoreload";

/** The fingerprint the page was opened with (null when the page was not served by '/', e.g. a direct file link). */
export const pageVer = () => {
  const m = typeof document !== "undefined" && document.querySelector('meta[name="pb-ver"]');
  return m && m.content ? m.content : null;
};

/** Whether a newer page should load by itself now: a hidden page, or one left alone for IDLE_RELOAD_MS with nothing
 *  typed into a text box. Once per new version: last = {ver, at} of this tab's last reload by itself; a page that
 *  comes back still behind the server for the same version (something in between answered with older code) does not
 *  reload itself again within AUTO_AGAIN_MS (the chip stays for a click), so a tab can never loop. */
export function autoReloadOk({hidden, idleMs, typing, ver = null, last = null, now = Date.now()}) {
  if (typing) return false;
  if (last && ver && last.ver === ver && now - Number(last.at || 0) < AUTO_AGAIN_MS) return false;
  return !!hidden || idleMs >= IDLE_RELOAD_MS;
}
const lastAuto = () => { try { return JSON.parse(sessionStorage.getItem(AUTO_KEY) || "null"); } catch (e) { return null; } };

let chip = null, newVer = null, lastInput = Date.now(), timer = null;
const typing = () => [...document.querySelectorAll("input:not([type=checkbox]):not([type=radio]):not([type=search]), textarea")]
  .some((x) => x.value && x.value.trim() && !x.disabled && x.offsetParent !== null);
function reload() { try { location.reload(); } catch (e) { /* nothing */ } }
function check() {
  if (!newVer) return;
  if (!autoReloadOk({hidden: document.visibilityState === "hidden", idleMs: Date.now() - lastInput, typing: typing(),
    ver: newVer, last: lastAuto()})) return;
  try { sessionStorage.setItem(AUTO_KEY, JSON.stringify({ver: newVer, at: Date.now()})); } catch (e) { /* no storage: still once per check */ }
  reload();
}
function show(ver) {
  newVer = ver;
  if (!chip) {
    chip = h("button", {class: "verchip", type: "button", title: "대시보드 화면 코드가 새로 올라왔습니다. 누르면 지금 보던 화면 그대로 새로 불러옵니다.",
      onclick: reload}, h("b", null, "새 버전 준비됨"), " · 눌러서 새로고침");
    document.body.append(chip);
  }
  if (!timer) timer = setInterval(check, 30000);
  check();
}
function hide() {
  newVer = null;
  if (chip) { chip.remove(); chip = null; }
  if (timer) { clearInterval(timer); timer = null; }
}

export function startVersion() {
  const mine = pageVer();
  if (!mine) return;
  // (the server back on this page's own code, e.g. an update rolled back before the reload: nothing new to offer)
  bus.on("version", (v) => { if (!v) return; if (v !== mine) show(v); else hide(); });
  for (const ev of ["pointerdown", "keydown", "wheel", "touchstart"]) window.addEventListener(ev, () => { lastInput = Date.now(); }, {passive: true, capture: true});
  // back after a while away: ask at once (the 10-minute clock check may be far off)
  let hiddenAt = null;
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") { hiddenAt = Date.now(); if (newVer) check(); return; }
    if (hiddenAt != null && Date.now() - hiddenAt >= AWAY_CHECK_MS) syncClock();
    hiddenAt = null;
  });
  // the live stream back after a gap (an update restarts the dashboard: 20-25 s without it)
  let downSince = null;
  bus.on("stream:state", (s) => {
    if (s === "open") { if (downSince != null && Date.now() - downSince >= 5000) syncClock(); downSince = null; }
    else if (s === "error" || s === "reconnecting") downSince = downSince ?? Date.now();
  });
}
