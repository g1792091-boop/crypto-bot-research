// One colour rule and one money format for MARKET liquidations (review 10/06: "강제청산 색이 터미널과 시장 화면에서 정반대",
// "같은 금액이 화면마다 다른 단위"). Pure (no DOM): the terminal's 강제청산 feed and its ratio bar, the chart's flash and
// bubbles, the 시장 강제청산 board and the chart screen's list all read it, so they can never disagree again.
//
//   COLOUR = the SIDE that was liquidated, the same colour 롱 / 숏 have everywhere else on the terminal (the side tags,
//   the long / short bars, 이 코인 포지션): 롱 청산 = the "up" colour (mint / teal), 숏 청산 = the "down" colour (pink).
//   It says WHO got liquidated, not which way the price moved: that is in the words (LIQ_TIP), once.
//
//   MONEY = "$" + a 3-significant-digit number + K / M / B, capital letters always: $893 · $2.45K · $42.0K · $126K ·
//   $1.25M · $5.94B (usdShort). The unit is always shown (it is dollars of the Binance market, never our paper USDT).
import {num} from "./fmt.js";

/** liquidated side -> the colour class every surface uses ("up" | "down", the tokens' meaning colours). */
export const LIQ_TONE = Object.freeze({long: "up", short: "down"});
export const liqTone = (liquidated) => LIQ_TONE[liquidated] || "";
/** "롱 청산" / "숏 청산" */
export const liqKo = (liquidated) => (liquidated === "long" ? "롱 청산" : liquidated === "short" ? "숏 청산" : "—");
/** the English tag of the terminal's dense rows */
export const liqTag = (liquidated) => (liquidated === "long" ? "LONG" : liquidated === "short" ? "SHORT" : "—");
/** A Binance forced order's side (SELL closes a long, BUY closes a short: the server's rule) -> "long" | "short". */
export const liquidatedOf = (orderSide) => (orderSide === "SELL" ? "long" : orderSide === "BUY" ? "short" : null);

/** What '롱 청산' means, said once (tooltips of the terminal's panel, the chart's flash legend, the 시장 board). */
export const LIQ_TIP = "롱 청산 = 가격이 오른다는 쪽(롱)에 걸었던 포지션이 가격이 내려 거래소에 강제로 정리된 것 · "
  + "숏 청산 = 내린다는 쪽(숏)에 걸었던 포지션이 가격이 올라 강제로 정리된 것 · "
  + "색은 정리된 쪽입니다: 롱 = 청록, 숏 = 분홍 (바이낸스 실제 강제청산, 우리 봇 아님)";
/** One side in plain words (a row's tooltip). */
export const LIQ_WHAT = Object.freeze({long: "롱(오른다에 건 쪽)이 가격이 내려 강제로 정리됨", short: "숏(내린다에 건 쪽)이 가격이 올라 강제로 정리됨"});
/** the same words short enough for a legend line */
export const LIQ_TIP_SHORT = "색 = 정리된 쪽 (롱 청산 = 청록, 숏 청산 = 분홍)";

const UNITS = [[1e9, "B"], [1e6, "M"], [1e3, "K"]];
/** Dollars of the market, short: 893 -> "$893", 2450 -> "$2.45K", 42000 -> "$42.0K", 126000 -> "$126K", 1.25e6 -> "$1.25M",
 *  5.94e9 -> "$5.94B" (3 significant digits; "—" when there is no number, never "$0" for a missing one). */
export function usdShort(x) {
  if (x == null || typeof x === "boolean" || x === "" || !Number.isFinite(Number(x))) return "—";
  const v = Number(x), a = Math.abs(v);
  for (const [f, u] of UNITS) {
    if (a >= f * 0.9995) {                            // 999.96K rounds up to 1.00M, never "1000K"
      const s = a / f;
      return (v < 0 ? "−" : "") + "$" + num(s, s < 9.995 ? 2 : s < 99.95 ? 1 : 0) + u;
    }
  }
  return (v < 0 ? "−" : "") + "$" + num(a, 0);
}
