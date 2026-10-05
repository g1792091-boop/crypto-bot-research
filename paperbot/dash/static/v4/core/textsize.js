// 글자 크기 (owners, 10/06: "예전 대시보드보다 글자가 작아 보이고 보기 힘들다"): three steps 보통 / 크게 / 아주 크게
// (about 100 / 112 / 125 %). tokens.css redefines the --t-* font tokens under <html data-text="md|lg|xl">, and every
// v4 font size reads those tokens, so one switch scales the whole page. The choice is a per-device convenience (local
// storage through dom.js `local`, wrapped in try/catch): a private window or blocked storage simply gets 보통. Applied
// at boot (core/main.js) before the shell draws; switched from the small control next to 화면 색 (core/shell.js).
import {h, local} from "./dom.js";

export const TEXT_SIZES = [{id: "md", ko: "보통"}, {id: "lg", ko: "크게"}, {id: "xl", ko: "아주 크게"}];
export const DEFAULT_TEXT = "md";
const KEY = "text";

/** The viewer's text size id ("md" unless this device chose "lg" or "xl"). */
export function currentText() {
  const v = local.get(KEY, DEFAULT_TEXT);
  return TEXT_SIZES.some((x) => x.id === v) ? v : DEFAULT_TEXT;
}

/** Put a text size on <html data-text>. */
export function applyText(id = currentText()) {
  const root = document.documentElement;
  root.dataset.text = TEXT_SIZES.some((x) => x.id === id) ? id : DEFAULT_TEXT;
  return root.dataset.text;
}

/**
 * textSwitch(onChange) -> a small three-button control "글자 크기 보통 | 크게 | 아주 크게" (aria-pressed). Choosing one
 * applies it, remembers it on this device and calls onChange(id) (the shell draws the current screen again, so the
 * charts measure their labels at the new size).
 */
export function textSwitch(onChange) {
  const cur = currentText();
  const btns = TEXT_SIZES.map((x) => h("button", {type: "button", "aria-pressed": String(x.id === cur), dataset: {text: x.id},
    onclick: () => {
      if (document.documentElement.dataset.text === x.id) return;
      local.set(KEY, x.id);
      applyText(x.id);
      for (const b of btns) b.setAttribute("aria-pressed", String(b.dataset.text === x.id));
      if (onChange) onChange(x.id);
    }}, x.ko));
  return h("span", {class: "skinsw textsw", role: "group", "aria-label": "글자 크기", title: "글자 크기: 이 기기에만 기억합니다"},
    h("span", {class: "k"}, "글자 크기"), btns);
}
