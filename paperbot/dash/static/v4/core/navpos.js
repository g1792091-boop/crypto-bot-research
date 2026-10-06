// 메뉴 위치 (owners 10/06 13:27: "클릭하는 버튼들이 다 왼쪽으로 바꼈네?? ... 불편해졌는데"): on a PC window (1200 px and
// up) the menu is on top by default (10/06 ~14:00: every screen its own text button in one strip, like v3;
// core/strip.js), and the left rail (core/rail.js: the same buttons with icon + Korean name, group headings) is a choice:
//   "top"   위 (the default)
//   "left"  왼쪽
// The choice is a per-device convenience (local storage through dom.js `local`, wrapped in try/catch): a private
// window or blocked storage simply gets 위. Applied at boot (core/main.js) on <html data-nav> before the shell draws;
// core/nav.css shows the rail only under [data-nav="left"] at 1200 px and up (below that the menu is the same in both).
// Switched from the small "메뉴 위치 위 | 왼쪽" control in the top bar and in the rail's foot (core/shell.js,
// core/rail.js). Other code (the settings panel) calls setNavPos("top" | "left"): it stores, applies and emits the bus
// event "navpos", on which the shell redraws the menu and the screen (core/shell.js).
import {h, local} from "./dom.js";
import {bus} from "./api.js";

export const NAV_POS = [{id: "top", ko: "위"}, {id: "left", ko: "왼쪽"}];
export const DEFAULT_NAV = "top";
const KEY = "nav";
const valid = (id) => NAV_POS.some((x) => x.id === id);

/** The viewer's menu position id ("top" unless this device chose "left"). */
export function currentNavPos() {
  const v = local.get(KEY, DEFAULT_NAV);
  return valid(v) ? v : DEFAULT_NAV;
}

/** Put a menu position on <html data-nav> (what is applied wins over storage: blocked storage still switches). */
export function applyNavPos(id = currentNavPos()) {
  const root = document.documentElement;
  root.dataset.nav = valid(id) ? id : DEFAULT_NAV;
  return root.dataset.nav;
}

/** The position applied now (falls back to the stored one before boot). */
export const navPosNow = () => (valid(document.documentElement.dataset.nav) ? document.documentElement.dataset.nav : currentNavPos());

/**
 * setNavPos("top" | "left") -> the id applied. Remembers it on this device, applies it and emits bus "navpos" (the
 * shell redraws the menu and the screen). An unknown id is ignored (returns the current one); the same one is a no-op.
 */
export function setNavPos(id) {
  if (!valid(id)) return navPosNow();
  local.set(KEY, id);
  if (navPosNow() === id) return id;
  applyNavPos(id);
  bus.emit("navpos", id);
  return id;
}

/** navPosSwitch() -> the small two-button control "메뉴 위치 위 | 왼쪽" (aria-pressed), the same look as 글자 크기. */
export function navPosSwitch() {
  const cur = navPosNow();
  const btns = NAV_POS.map((x) => h("button", {type: "button", "aria-pressed": String(x.id === cur), dataset: {nav: x.id},
    title: x.id === "top" ? "메뉴를 위에 (모든 화면이 글자 버튼 한 줄)" : "메뉴를 왼쪽 줄에 (그림 + 이름, 세로로)",
    onclick: () => {
      if (navPosNow() === x.id) return;
      for (const b of btns) b.setAttribute("aria-pressed", String(b.dataset.nav === x.id));
      setNavPos(x.id);
    }}, x.ko));
  return h("span", {class: "skinsw navsw", role: "group", "aria-label": "메뉴 위치", title: "메뉴 위치: 이 기기에만 기억합니다"},
    h("span", {class: "k"}, "메뉴 위치"), btns);
}
