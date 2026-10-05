// 거래소 차트 (TradingView opt-in, owners 10/06 00:25): TradingView's own chart page in a cross-origin IFRAME on the
// 차트 screen's second tab. No outside script ever runs in our page: the frame is TradingView's document in its own
// origin, sandboxed (its scripts, its own storage and new-tab popups only: it cannot move our page, submit forms or
// start downloads), sent with no referrer. The frame exists only while the 거래소 차트 tab is open: built on open, rebuilt on a coin or
// interval change (a fresh element, so the browser's back button never steps through the frame), removed when the
// tab is left and on unmount. The page's CSP must list the frame hosts in frame-src (INVENTORY "거래소 차트").
import {h} from "../core/pb.js";

/** Our interval keys -> TradingView's (the same table as the old dashboard's charts.js). */
export const TV_IV = {"1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "2h": "120", "4h": "240", "6h": "360",
  "8h": "480", "12h": "720", "1d": "D", "3d": "3D", "1w": "W", "1M": "M"};
export const TV_CAPTION = "트레이딩뷰 화면 (바깥 사이트) · 우리 봇의 진입·손절선은 '우리 차트' 탭에";
const EMBED = "https://s.tradingview.com/widgetembed/";
const SANDBOX = "allow-scripts allow-same-origin allow-popups";

/** The embed page for a coin ("BTC") and our interval: Binance perpetual, Korean, Korea time, dark, drawing tools on. */
export function tvEmbedUrl(coin, tf) {
  const q = new URLSearchParams({symbol: `BINANCE:${coin}USDT.P`, interval: TV_IV[tf] || "15", timezone: "Asia/Seoul",
    theme: "dark", style: "1", locale: "kr", hidesidetoolbar: "0", symboledit: "1", saveimage: "0", withdateranges: "1",
    details: "0", hotlist: "0", calendar: "0", hideideas: "1"});
  return `${EMBED}?${q}`;
}

/** tvFrame() -> {el, show(coin, tf), hide(), isOpen()}. el holds no iframe until show(); hide() removes it again. */
export function tvFrame() {
  const slot = h("div", {class: "chart-tv-slot"});
  const el = h("div", {class: "chart-tv", hidden: true}, slot, h("p", {class: "chart-tv-cap"}, TV_CAPTION));
  let frame = null, url = "";
  function show(coin, tf) {
    el.hidden = false;
    const want = tvEmbedUrl(coin, tf);
    if (frame && url === want) return;
    url = want;
    // sandbox and referrerpolicy are set before src, and the element is attached only after all three are on it
    frame = h("iframe", {sandbox: SANDBOX, referrerpolicy: "no-referrer", title: `트레이딩뷰 ${coin} 차트 (바깥 사이트)`,
      class: "chart-tv-frame", src: want});
    slot.replaceChildren(frame);
  }
  function hide() {
    el.hidden = true;
    if (frame) frame.remove();
    slot.replaceChildren();
    frame = null; url = "";
  }
  return {el, show, hide, isOpen: () => !!frame};
}
