// The look of the whole dashboard (owners, 10/05: "미래 AI 느낌"): two skins, the colours in tokens.css.
//   "ai"      the default: charcoal, teal accent, mint up / pink down, a faint grid
//   "classic" the first navy + yellow look
// The viewer's choice is a per-device convenience (local storage through dom.js `local`, wrapped in try/catch): a
// private window simply gets the default. Applied at boot (core/main.js) before the shell draws; switched from the
// small "화면 색" control at the end of the 서버 group's tabs (core/shell.js). Charts read their colours from the tokens
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
