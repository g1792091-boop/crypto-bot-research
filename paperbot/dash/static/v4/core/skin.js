// The look of the whole dashboard (owners, 10/05: "미래 AI 느낌"): two skins, the colours in tokens.css.
//   "ai"      the default: charcoal, teal accent, mint up / pink down, a faint grid
//   "classic" the first navy + yellow look
// The viewer's choice is a per-device convenience (local storage through dom.js `local`, wrapped in try/catch): a
// private window simply gets the default. Applied at boot (core/main.js) before the shell draws; switched from the
// small "화면 색" control in the top bar on a PC, at the menu strip's end below 1200 px (core/shell.js). Charts read their colours from the tokens
// when they are drawn, so a switch draws the current screen again (router.remount).
import {h, local} from "./dom.js";

export const SKINS = [{id: "ai", ko: "AI"}, {id: "classic", ko: "클래식"}];
export const DEFAULT_SKIN = "ai";
const KEY = "skin";

/** The viewer's skin id ("ai" unless this device chose "classic"). */
export function currentSkin() {
  const v = local.get(KEY, DEFAULT_SKIN);
  return SKINS.some((x) => x.id === v) ? v : DEFAULT_SKIN;
}

/** Put a skin on <html data-skin> and the browser bar colour (meta theme-color) from its own --bg token. */
export function applySkin(id = currentSkin()) {
  const root = document.documentElement;
  root.dataset.skin = SKINS.some((x) => x.id === id) ? id : DEFAULT_SKIN;
  const meta = document.querySelector('meta[name="theme-color"]');
  const bg = getComputedStyle(root).getPropertyValue("--bg").trim();
  if (meta && bg) meta.setAttribute("content", bg);
  return root.dataset.skin;
}

/**
 * skinSwitch(onChange) -> a small two-button control "화면 색 AI | 클래식" (aria-pressed). Choosing one applies it,
 * remembers it on this device and calls onChange(id) (the shell draws the current screen again).
 */
export function skinSwitch(onChange) {
  const cur = document.documentElement.dataset.skin || currentSkin(); // what is applied wins over storage (blocked storage)
  const btns = SKINS.map((x) => h("button", {type: "button", "aria-pressed": String(x.id === cur), dataset: {skin: x.id},
    onclick: () => {
      if (document.documentElement.dataset.skin === x.id) return;
      local.set(KEY, x.id);
      applySkin(x.id);
      for (const b of btns) b.setAttribute("aria-pressed", String(b.dataset.skin === x.id));
      if (onChange) onChange(x.id);
    }}, x.ko));
  return h("span", {class: "skinsw", role: "group", "aria-label": "화면 색 고르기", title: "화면 색: 이 기기에만 기억합니다"},
    h("span", {class: "k"}, "화면 색"), btns);
}

/** skinCycle(onChange) -> one small round button for the PC rail's foot (core/rail.js): each click switches to the
 *  other skin, remembers it on this device and calls onChange(id). */
export function skinCycle(onChange) {
  const at = () => document.documentElement.dataset.skin || currentSkin();
  const ko = (id) => (SKINS.find((x) => x.id === id) || SKINS[0]).ko;
  const label = (id) => `화면 색: ${ko(id)} (누르면 바뀝니다)`;
  const btn = h("button", {type: "button", class: "skincyc", dataset: {skin: at()}, "aria-label": label(at()), title: label(at()),
    onclick: () => {
      const i = SKINS.findIndex((x) => x.id === at());
      const next = SKINS[(i + 1) % SKINS.length].id;
      local.set(KEY, next);
      applySkin(next);
      btn.dataset.skin = next;
      btn.setAttribute("aria-label", label(next)); btn.title = label(next);
      if (onChange) onChange(next);
    }}, h("i", {"aria-hidden": "true"}));
  return btn;
}
