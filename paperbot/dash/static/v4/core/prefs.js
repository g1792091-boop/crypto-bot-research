// Per-device preferences that more than one control changes (설정 한 곳, core/settings.js, owners 10/06 "클릭이 너무
// 많다"): a control writes the SAME storage key it always did (dom.js `local`, try/catch inside; nothing is migrated)
// and tells the other places that show that preference, so a change in the 설정 panel applies at once to a chart deck
// already on screen (core/chartfx.js), the 차트 screen's own toggles, the phone swipe, the start screen.
//   setPref(key, value)  writes local storage, then every onPref(key) listener gets the value
//   onPref(key, fn)      -> off(): fn(value) after every setPref of that key (a screen passes off to ctx.track)
// The keys that live only here (new in this panel): START_KEY (첫 화면) and SWIPE_KEY (휴대폰 옆으로 밀기).
import {local} from "./dom.js";

export const START_KEY = "start";          // a screen name, "" = automatic (routes.js landing)
export const SWIPE_KEY = "swipe";          // false = the phone's sideways swipe between screens is off (default on)
export const GRID_KEY = "charts-grid";     // 여러 차트 (screens/charts.js): {layout: "2x2" | "3x3", cells: [{sym, tf, acct}]}

const subs = new Map();                    // key -> Set(fn)

export function onPref(key, fn) {
  if (!subs.has(key)) subs.set(key, new Set());
  subs.get(key).add(fn);
  return () => { const s = subs.get(key); if (s) s.delete(fn); };
}

/** Tell the listeners of ``key`` without writing (a control that already wrote its own key). */
export function tellPref(key, value) {
  for (const fn of [...(subs.get(key) || [])]) {
    try { fn(value); } catch (e) { console.error(`pref ${key}`, e); }
  }
}

export function setPref(key, value) {
  local.set(key, value);
  tellPref(key, value);
}

/** The phone swipe between a group's screens: on unless this device turned it off. */
export const swipeOn = () => local.get(SWIPE_KEY, true) !== false;
