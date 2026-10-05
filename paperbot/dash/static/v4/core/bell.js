// 결재함 종 (wave 3): the header bell counts the proposals that wait for the two owners' approval (GET /api/v4/bell,
// dash/more/bell.py: the same rule as the room side panel). Tapping it opens a short list (newest five) with a link to
// each room; approving itself stays in the room's side panel with its confirm step. Asked every 60 s (paused while the
// page is hidden) and shortly after a real room change on the live stream. The bell rings once only when the count
// really went up (never on a timer); the look lives in core/bell.css (linked by index.html).
import {h, s, put} from "./dom.js";
import {api, bus, poll} from "./api.js";
import {href} from "./routes.js";
import {kst} from "./fmt.js";
import {ring, reduced} from "./motion.js";

const POLL_MS = 60000;
const ROOMS_GAP_MS = 20000;

// a 16 x 16 pixel bell (fill = currentColor)
const BELL = [[7, 1, 2, 1], [5, 2, 6, 1], [4, 3, 8, 1], [4, 4, 8, 4], [3, 8, 10, 2], [2, 10, 12, 2], [6, 13, 4, 2]];
const bellIcon = () => s("svg", {viewBox: "0 0 16 16", width: "16", height: "16", fill: "currentColor", "shape-rendering": "crispEdges",
  "aria-hidden": "true"}, BELL.map(([x, y, w, hh]) => s("rect", {x, y, width: w, height: hh})));

const st = {d: null, n: null, open: false, lastRooms: 0};
let btn = null, badge = null, pop = null;

export function bellButton() {
  badge = h("span", {class: "bell-n", hidden: true});
  btn = h("button", {class: "bell-btn", id: "bellbtn", type: "button", "aria-haspopup": "dialog", "aria-expanded": "false",
    "aria-controls": "bellpop", dataset: {state: "none"}, title: "두 분 승인을 기다리는 제안", "aria-label": "결재함: 확인 중"}, bellIcon(), badge);
  pop = h("div", {class: "bell-pop", id: "bellpop", role: "dialog", "aria-label": "두 분 승인을 기다리는 제안", hidden: true});
  btn.addEventListener("click", () => setOpen(!st.open));
  document.addEventListener("click", (e) => { if (st.open && !e.target.closest(".bell")) setOpen(false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && st.open) { setOpen(false); btn.focus({preventScroll: true}); } });
  bus.on("route", () => setOpen(false));
  return h("div", {class: "bell"}, btn, pop);
}

function setOpen(open) {
  st.open = open;
  btn.setAttribute("aria-expanded", String(open));
  pop.hidden = !open;
  if (open) { renderPop(); place(); }
}

// the list is fixed under the bell and kept inside the window (a phone's header has no room to its left)
function place() {
  const r = btn.getBoundingClientRect(), vw = document.documentElement.clientWidth, w = Math.min(320, vw - 32);
  pop.style.width = w + "px";
  pop.style.left = Math.max(16, Math.min(r.right + 40 - w, vw - 16 - w)) + "px";
  pop.style.top = Math.round(r.bottom + 8) + "px";
}

function paint() {
  const d = st.d;
  const n = d && d.ready ? d.n : null;
  btn.dataset.state = n == null ? "none" : n > 0 ? "wait" : "zero";
  badge.hidden = !(n > 0);
  badge.textContent = n > 99 ? "99+" : String(n || 0);
  const t = n == null ? "결재함: 아직 모름" : n > 0 ? `결재함: 두 분 승인을 기다리는 제안 ${n}개` : "결재함: 승인을 기다리는 제안 없음";
  btn.title = t;
  btn.setAttribute("aria-label", t + ". 누르면 목록");
  if (st.open) renderPop();
}

function renderPop() {
  const d = st.d;
  if (!d) { put(pop, h("p", {class: "note"}, "불러오는 중입니다.")); return; }
  if (!d.ready) { put(pop, h("b", {class: "bell-h"}, "결재함"), h("p", {class: "note"}, "에이전트 기록을 아직 읽지 못했습니다. 잠시 뒤 다시 봅니다.")); return; }
  const items = d.items || [];
  put(pop, h("b", {class: "bell-h"}, d.n > 0 ? `두 분 승인을 기다리는 제안 ${d.n}개` : "승인을 기다리는 제안 없음"),
    items.length ? h("ul", {class: "bell-list"}, items.map((p) => h("li", null,
      h("a", {href: href("rooms", p.room_id)},
        h("span", {class: "bell-t"}, `제안 #${p.id}`, p.strategy_ko || p.strategy ? ` · ${p.strategy_ko || p.strategy}` : ""),
        h("span", {class: "bell-s"}, `${p.room_title || p.room_id}${p.ts ? " · " + kst(p.ts) : ""}`),
        h("span", {class: "bell-go", "aria-hidden": "true"}, "→"))))) : null,
    d.n > items.length ? h("p", {class: "note"}, `나머지 ${d.n - items.length}개는 각 방의 옆 칸에 있습니다.`) : null,
    h("p", {class: "note"}, d.n > 0
      ? "승인·거절은 그 방 옆 칸 '두 분 확인이 필요한 제안'에서 한 번 더 확인하고 합니다. 여기서는 세기만 합니다."
      : "에이전트가 새 계좌를 제안하면 여기에 숫자가 뜹니다. 관찰 기간에는 제안이 나오지 않습니다."));
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

