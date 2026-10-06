// 차트 위 얹기 (chart-plus): the pieces its three parts share: the per-device choice, Korean amounts, the words that must
// stay honest (market-wide, only what our recorder heard, DeepSeek and coin flips counted without money), a tooltip.
import {h, fmt, local, tok} from "../core/pb.js";

/** "12.3억" / "420만" / "8,200": USDT amounts in Korean units (the market screens' rule: no 'B' / 'K' beside 만 / 억). */
export function koUsd(x) {
  const v = Number(x);
  if (x == null || !Number.isFinite(v)) return "—";
  const a = Math.abs(v), sg = v < 0 ? "−" : "";
  if (a >= 1e12) return `${sg}${fmt.num(a / 1e12, 2)}조`;
  if (a >= 1e8) return `${sg}${fmt.num(a / 1e8, a >= 1e10 ? 0 : 1)}억`;
  if (a >= 1e4) return `${sg}${fmt.num(a / 1e4, a >= 1e6 ? 0 : 1)}만`;
  return `${sg}${fmt.num(a, 0)}`;
}
/** "420만 USDT" */
export const koUsdt = (x) => (x == null || !Number.isFinite(Number(x)) ? "—" : `${koUsd(x)} USDT`);

/** The words that stay on screen whenever the overlay is on (the owners' honesty rule: say what it is and what it is not). */
export const WORDS = {
  liq: "바이낸스 시장 전체 (우리 봇 아님)",
  liqLimit: "기록기가 켜진 뒤 들은 것만 · 코인마다 1초에 1건만 알려 줘서 실제보다 적음",
  stops: "우리 모의 계좌의 열린 포지션 손절·청산가 (이 코인)",
  stopsMath: "마크 가격 기준 산수 · 나갈 때 수수료·미끄러짐 전 · 예측이 아님",
  countOnly: (n) => `딥시크·동전 봇 ${n}개는 개수만`,
  both: (n) => `손절가·청산가를 둘 다 지나는 ${n}개는 먼저 닿는 쪽 하나로만 셉니다 (보통 손절이 먼저)`,
};

/** The per-device choice of one chart ("term" | "chart"): {liq, stops, panes: [at most 2 of cvd / oi / fund / ls]}. */
const PANE_IDS = ["cvd", "oi", "fund", "ls"];
export function readState(key) {
  const raw = local.get("cfxp-" + key, null);
  const s = raw && typeof raw === "object" ? raw : {};
  const panes = Array.isArray(s.panes) ? s.panes.filter((x, i, a) => PANE_IDS.includes(x) && a.indexOf(x) === i).slice(0, 2) : [];
  return {liq: s.liq === true, stops: s.stops === true, panes};
}
export function saveState(key, st) { local.set("cfxp-" + key, {v: 1, liq: !!st.liq, stops: !!st.stops, panes: st.panes.slice(0, 2)}); }
export {PANE_IDS};

/** One floating tooltip inside ``wrap`` (text nodes only): show(lines, x, y) puts it near a point, kept inside the box. */
export function tipBox(wrap) {
  const el = h("div", {class: "cfxp-tip", hidden: true, role: "tooltip"});
  wrap.append(el);
  return {
    el,
    show(lines, x, y, maxRight) {
      el.replaceChildren(...lines.map((l) => (l && l.nodeType ? l : h("div", null, l))));
      el.hidden = false;
      const w = el.offsetWidth, hh = el.offsetHeight, right = maxRight == null ? wrap.clientWidth : maxRight;
      const left = Math.max(6, Math.min(right - w - 6, x + 14));
      const top = Math.max(6, Math.min(wrap.clientHeight - hh - 6, y - hh - 10 < 6 ? y + 14 : y - hh - 10));
      el.style.transform = `translate(${Math.round(left)}px, ${Math.round(top)}px)`;
    },
    hide() { el.hidden = true; },
  };
}

/** Colours and the font for canvas drawing, read from the tokens when drawn (a skin switch redraws the screen). */
export function palette() {
  const fs = parseFloat(tok("--t-2xs")) || 12;
  return {up: tok("--up"), down: tok("--down"), upGlow: tok("--up-glow") || tok("--up"), downGlow: tok("--down-glow") || tok("--down"),
    warn: tok("--warn"), ink: tok("--ink"), ink2: tok("--ink-2"), muted: tok("--muted"), line: tok("--line-2"), surface: tok("--surface"),
    surface2: tok("--surface-2"), accent: tok("--accent"), fs, font: tok("--f-term") || "monospace"};
}
