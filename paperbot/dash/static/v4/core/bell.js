// 결재함 종 (wave 3; add-accounts: opens the 결재함): the header bell counts the proposals that wait for the two owners'
// approval (GET /api/v4/bell, dash/more/bell.py: the same rule as the room side panel). Tapping it opens the 결재함
// (#/inbox, screens/inbox.js: every waiting proposal with its 5-year table, the staff's for / against lines and what
// approving does, approved / rejected there with a confirm step through the same POST /api/proposals/<id>/decide).
// Asked every 60 s (paused while the page is hidden) and shortly after a real room change on the live stream. The bell
// rings once only when the count really went up (never on a timer); the look lives in core/bell.css (linked by
// index.html).
import {h, s} from "./dom.js";
import {api, bus, poll} from "./api.js";
import {href} from "./routes.js";
import {ring, reduced} from "./motion.js";

const POLL_MS = 60000;
const ROOMS_GAP_MS = 20000;

// a 16 x 16 pixel bell (fill = currentColor)
const BELL = [[7, 1, 2, 1], [5, 2, 6, 1], [4, 3, 8, 1], [4, 4, 8, 4], [3, 8, 10, 2], [2, 10, 12, 2], [6, 13, 4, 2]];
const bellIcon = () => s("svg", {viewBox: "0 0 16 16", width: "16", height: "16", fill: "currentColor", "shape-rendering": "crispEdges",
  "aria-hidden": "true"}, BELL.map(([x, y, w, hh]) => s("rect", {x, y, width: w, height: hh})));

const st = {d: null, n: null, lastRooms: 0};
let btn = null, badge = null;

export function bellButton() {
  badge = h("span", {class: "bell-n", hidden: true});
  btn = h("a", {class: "bell-btn", id: "bellbtn", href: href("inbox"), dataset: {state: "none"}, title: "결재함: 두 분 승인을 기다리는 제안",
    "aria-label": "결재함: 확인 중"}, bellIcon(), badge);
  return h("div", {class: "bell"}, btn);
}

function paint() {
  const d = st.d;
  const n = d && d.ready ? d.n : null;
  btn.dataset.state = n == null ? "none" : n > 0 ? "wait" : "zero";
  badge.hidden = !(n > 0);
  badge.textContent = n > 99 ? "99+" : String(n || 0);
  const t = n == null ? "결재함: 아직 모름" : n > 0 ? `결재함: 두 분 승인을 기다리는 제안 ${n}개` : "결재함: 승인을 기다리는 제안 없음";
  btn.title = t;
  btn.setAttribute("aria-label", t + ". 누르면 결재함");
}

async function load() {
  let d;
  try { d = await api("/api/v4/bell"); } catch (e) {
    if (e && e.status === 404) { stop(); if (btn) btn.closest(".bell").hidden = true; }   // an older server: no bell
    return;
  }
  const prev = st.n;
  st.d = d;
  st.n = d && d.ready ? d.n : null;
  paint();
  // ring once only when the count really went up since the last answer (never on the first load or a timer)
  if (prev != null && st.n != null && st.n > prev && !reduced()) {
    btn.classList.remove("ringing");
    void btn.offsetWidth;
    btn.classList.add("ringing");
    ring(btn);
  }
}

let stop = () => {};
export function startBell() {
  if (!btn) return;
  stop = poll(load, POLL_MS, {now: true});
  bus.on("rooms", () => {
    if (Date.now() - st.lastRooms < ROOMS_GAP_MS || document.visibilityState === "hidden") return;
    st.lastRooms = Date.now();
    setTimeout(load, 2000);
  });
}

