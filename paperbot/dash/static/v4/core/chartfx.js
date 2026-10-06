// The chart deck (owners 10/06: "선이 너무 크고 투박하다, 누르면 숨기게, 차트가 비어 보인다, 간지나게"): one helper the
// terminal chart and the 차트 screen share on top of the vendored lightweight-charts (v4.2 series primitives).
//   glow       AI skin only: candles and wicks get a soft neon glow in their up / down colours, the forming candle a
//              little brighter, the last price a glowing line, our entry / exit marks a halo; a faint depth gradient.
//              Drawn under the candles (primitive zOrder "bottom"), so the candles and every text stay crisp.
//   ambient    AI skin only, like the reference terminal: the pane is split at the equilibrium of the current dealing
//              range (core/smc.js splitOf; fallback the middle of the visible high / low): the Premium part above is
//              washed red (strongest at the top edge), the Discount part below sky blue (strongest at the bottom edge),
//              a soft seam between, faint 'Premium' / 'Discount' words at the right. The split follows the price scale
//              (pan / zoom) and moves when the dealing range really changes (a new closed bar).
//              The two halves BLINK (owners 10/06 13:27 "깜박깜박하는 느낌", core/blink.js): each lights up and goes
//              dark on its own — a real taker SELL burst of the server's relay (/api/v4/ticks, the page's one
//              connection in core/ticks.js, opened for the light even with the sound off) lights the red top, a BUY
//              burst the sky-blue bottom, a bigger one brighter and longer; with no relay event for 2 s a soft
//              decorative blink (no label, no number; the chip's tooltip says it is decoration). '조명: 깜박 (기본) /
//              계속 켜짐 / 끄기' per device in the light menu next to '번쩍임'; reduced motion: slow calm fades; a hidden
//              page: dark, no timer. Two absolutely positioned layers with CSS opacity transitions (no canvas work).
//   flash      AI skin only: a real market event of this coin (a big taker trade from the server relay, a market
//              liquidation, our own bot's fill) washes the pane once (core/flash.js scheduler: 0.2 s in, a 0.6 s hold
//              or 1.5 s for a 고래 / a large liquidation, 0.4 s out; '번쩍임 자주 / 보통 / 끄기' per device). Reduced
//              motion: no flash.
//   lines      our position / stop / support-resistance / alert lines: 1 px, low alpha (a faint glow in AI), a compact
//              pill at the LEFT edge inside the pane, only a small tag on the right axis; never in the autoscale (the
//              candles keep filling the pane); a line off the price range becomes a small ▲ / ▼ edge marker.
//              Nearby pills are offset, then merged ("+N"), never overlapping. Clicking a pill (or its ×) hides it.
//   names      (owners 10/06 ~14:00: "손절 · OB · FVG · 저항 · 지지 … 겹쳐서 지저분하다") every named line and the drawn
//              OB / FVG zones get ONE small name next to the price axis, laid out by core/edgelabels.js: lines at
//              almost the same price share a name ("손절 ×2"), names closer than one label height are nudged apart
//              (with a thin leader to their line), at most 6 are shown (the nearest to the price); the others, the
//              equilibrium and the liquidity lines show their name and price on hover / tap of the line, and a "+N"
//              chip lists them.
//   menu       '선' in the chart header: the line groups on / off, 기본으로, 모두 보기 / 모두 숨기기, the hidden lines
//              back. Remembered per device (dom.js local, try/catch inside).
//   smc        프리미엄 지표: core/smc.js on the closed candles shown, drawn by core/smcdraw.js (an indicator, labelled).
//              Calm by default (owners 10/06 ~14:00, "기본"): the equilibrium line and the nearest OB and FVG above and
//              below the price; BSL / SSL, BoS / CHoCH, OTE, trendlines, leg %, Premium / Discount words and the
//              other OB / FVG boxes are opt-in items of the '프리미엄 지표 ▾' menu (SMC_PARTS, per device).
//   보기 ▾     the same light / flash / 프리미엄 지표 items in one menu for a narrow header (the terminal: every
//              timeframe button stays visible down to a 1200 px window).
//   volume     translucent up / down volume bars along the bottom (an overlay price scale of their own).
// HONESTY: every motion answers a real change (a new price, a real event); the one exception is the light's soft
// decorative blink while no real trade arrives (core/blink.js), which carries no label or number and is named
// decoration in the chip's tooltip. Colours are tokens (tokens.css), font sizes the --t-* tokens.
import {h, local} from "./dom.js";
import {tok} from "./lwc.js";
import {price as fmtPrice} from "./fmt.js";
import {reduced, visible} from "./motion.js";
import {flashScheduler, ENVELOPE, FLASH_MODES, DEFAULT_FLASH, modeOf} from "./flash.js";
import {blinker, relayBlink, LIGHT_MODES, DEFAULT_LIGHT, lightModeOf} from "./blink.js";
import {listenTicks} from "./ticks.js";
import {smcAll, splitOf, zoneOf, nearestZones} from "./smc.js";
import {smcPrimitive} from "./smcdraw.js";
import {edgeLayout} from "./edgelabels.js";
import {onPref, tellPref, setPref} from "./prefs.js";

export const GROUP_KO = {pos: "포지션 선", risk: "손절·잠금", sr: "지지·저항", smc: "프리미엄 지표", ev: "경제지표", vol: "거래량", al: "가격 알림 선",
  vp: "매물대"};                   // vp: screens/chart-vp.js (the 설정 panel names it too, before any chart was opened)
export const AMBIENT_TIP = "위쪽 빨간 빛 = Premium (지금 범위의 중간값 위) / 아래쪽 하늘색 = Discount (중간값 아래)";
export const FLASH_TIP = "하늘색 번쩍 = 큰 매수 · 롱 청산, 빨간 번쩍 = 큰 매도 · 숏 청산 (강제청산은 정리된 쪽의 색: 롱 = 하늘색, 숏 = 빨강) · 바이낸스 실제 체결";
export const LIGHT_REAL = "조명 깜박: 지금 바이낸스 실제 체결을 따라 깜박 (파는 쪽이 많으면 위 빨강, 사는 쪽이 많으면 아래 하늘색, 클수록 밝고 길게 · 7개 코인 중 이 코인이 가장 밝게)";
export const LIGHT_DECO = "조명 깜박: 지금은 따라갈 체결이 2초 넘게 없어 은은한 장식 깜박 (시장 자료 아님)";
export const LIGHT_NOTE = "깜박: 바이낸스 실제 체결을 따라 파는 쪽이 많으면 위 빨강, 사는 쪽이 많으면 아래 하늘색이 잠깐 켜집니다 "
  + "(클수록 밝고 길게 · 7개 코인 중 지금 코인이 가장 밝게). 따라갈 체결이 2초 넘게 없으면 은은한 장식 깜박 (시장 자료 아님). 이 기기에만 기억합니다.";
const LIGHT_SHORT = {blink: "깜박", steady: "켜짐", off: "끔"};
const LIGHT_SUB = {blink: "실제 체결 따라", steady: "예전처럼"};
const FLASH_SUB = {often: "큰 체결마다", normal: "고래·큰 청산·우리 체결만"};
export const SMC_NOTE = "프리미엄 지표: 화면의 캔들로 계산한 참고선 (스윙·구조·OB·FVG·OTE) · 매매 신호 아님";
/** 프리미엄 지표 parts (owners 10/06 ~14:00): `def` = on in the calm default ("기본"); every other part is opt-in. */
export const SMC_PARTS = [
  {id: "eq", ko: "중간선 (Equilibrium)", sub: "빨강·하늘색이 나뉘는 값", def: true},
  {id: "near", ko: "가까운 OB·FVG", sub: "지금 가격 위·아래 하나씩", def: true},
  {id: "zones", ko: "OB·FVG 최근 것 모두", def: false},
  {id: "liq", ko: "유동성 BSL·SSL", def: false},
  {id: "struct", ko: "구조 BoS·CHoCH", def: false},
  {id: "ote", ko: "되돌림 OTE 0.62·0.79", def: false},
  {id: "trend", ko: "추세선 (대각선)", def: false},
  {id: "legs", ko: "스윙 등락 %", def: false},
  {id: "words", ko: "Premium·Discount 글자", def: false},
];
const SMC_DEF = SMC_PARTS.filter((x) => x.def).map((x) => x.id);
/** The right edge shows at most this many line names (the nearest to the price); the rest on hover / tap. */
export const NAMES_MAX = 6;
const DECK_V = 2;                  // the saved per-device state's version: 2 = the calm default of 10/06 ~14:00
const SMC_KEY = "프리미엄 지표 · 계산한 참고선 · 신호 아님";
/** The AI skin (the default) has the light; 클래식 stays plain. */
export const isAi = () => typeof document !== "undefined" && document.documentElement.dataset.skin !== "classic";
const narrow = () => typeof matchMedia === "function" && matchMedia("(max-width: 599px)").matches;
const TONES = ["up", "down", "flat", "accent", "warn"];
const PILL_H = 20, PILL_GAP = 2, EDGE_MAX = 3, TOP_GAP = 26, FLASH_KEY = "chart-flash", LIGHT_KEY = "chart-light";

function colours() {
  const c = {};
  for (const [k, n] of [["up", "--up"], ["down", "--down"], ["upGlow", "--up-glow"], ["downGlow", "--down-glow"], ["accent", "--accent"],
    ["accentGlow", "--accent-glow"], ["warn", "--warn"], ["flat", "--muted"], ["ink", "--ink-2"], ["axisInk", "--accent-ink"],
    ["volUp", "--vol-up"], ["volDown", "--vol-down"], ["font", "--f-term"], ["fs", "--t-2xs"], ["bg", "--bg"],
    ["ob", "--smc-ob"], ["fvg", "--smc-fvg"], ["liq", "--smc-liq"], ["bos", "--smc-bos"], ["choch", "--smc-choch"], ["trend", "--smc-trend"],
    ["prem", "--smc-prem"], ["disc", "--smc-disc"], ["ote", "--smc-ote"]]) c[k] = tok(n);
  c.fs = parseFloat(c.fs) || 12;
  return c;
}

/**
 * glowPrimitive({chart, series, data, marks, idx, col, ai, onUpdate}) -> a series primitive (zOrder "bottom"): the
 * candles' neon glow in their up / down colours, the forming candle brighter with a faint column of light, a glowing
 * hairline at the last price, a halo on our entry / exit marks. Draws nothing unless ai() (the AI skin).
 *   data() -> the bars on the series (logical index = array index); marks() / idx(time) -> the series markers
 */
export function glowPrimitive(o) {
  const {chart, series} = o;
const gv = {bars: [], last: null, w: 2, py: null, halos: []};
const smalls = new Map();                   // the reused small canvases of the candle glow, by scale
const small = (S, w, hh) => {
  let cv = smalls.get(S);
  if (!cv) { cv = document.createElement("canvas"); smalls.set(S, cv); }
  if (cv.width !== w) cv.width = w;
  if (cv.height !== hh) cv.height = hh;
  return cv;
};
const glowR = {
  draw() {},
  drawBackground(target) {
    if (!o.ai() || !gv.bars.length) return;
    target.useBitmapCoordinateSpace(({context: c, horizontalPixelRatio: hr, verticalPixelRatio: vr, bitmapSize}) => {
      const col = o.col();
      const bw = Math.max(1, Math.round(gv.w * hr));
      c.save();
      // the candles' glow: the bodies and wicks drawn small (1/4 and 1/8 of the size) and stretched back with
      // smoothing, a soft light in their own colours for the cost of two image copies (no per-frame blur filter)
      c.imageSmoothingEnabled = true;
      try { c.imageSmoothingQuality = "high"; } catch (e) { /* older browsers: default smoothing */ }
      for (const [S, a] of (o.lite ? LITE_PASSES : GLOW_PASSES)) {
        const ow = Math.max(1, Math.ceil(bitmapSize.width / S)), oh = Math.max(1, Math.ceil(bitmapSize.height / S));
        const off = small(S, ow, oh), o2 = off.getContext("2d");
        o2.clearRect(0, 0, ow, oh);
        const sw = Math.max(1, bw / S + 1), ww = Math.max(0.8, (2 * hr) / S);
        for (const tone of ["up", "down"]) {
          o2.fillStyle = col[tone];
          o2.beginPath();
          for (const b of gv.bars) {
            if (b.up !== (tone === "up")) continue;
            const X = (b.x * hr) / S;
            o2.rect(X - sw / 2, (b.t * vr) / S, sw, Math.max(0.8, ((b.b - b.t) * vr) / S));
            o2.rect(X - ww / 2, (b.hi * vr) / S, ww, Math.max(0.8, ((b.lo - b.hi) * vr) / S));
          }
          o2.fill();
        }
        c.globalAlpha = a;
        c.drawImage(off, 0, 0, ow, oh, 0, 0, ow * S, oh * S);
      }
      // the forming candle: a little brighter, a faint column of light behind it
      const f = gv.last;
      if (f) {
        const X = Math.round(f.x * hr), cw = Math.max(6 * hr, bw * 4);
        const g = c.createLinearGradient(0, 0, 0, bitmapSize.height);
        g.addColorStop(0, "transparent"); g.addColorStop(0.5, f.up ? col.upGlow : col.downGlow); g.addColorStop(1, "transparent");
        c.shadowBlur = 0; c.globalAlpha = 0.07; c.fillStyle = g;
        c.fillRect(X - cw / 2, 0, cw, bitmapSize.height);
        c.shadowColor = f.up ? col.upGlow : col.downGlow; c.shadowBlur = 14 * hr; c.globalAlpha = 0.9; c.fillStyle = col[f.up ? "up" : "down"];
        c.fillRect(X - bw / 2, Math.round(f.t * vr), bw, Math.max(1, Math.round((f.b - f.t) * vr)));
      }
      // the last price: a glowing hairline under the series' own dashed price line
      if (gv.py != null && f) {
        c.shadowColor = f.up ? col.upGlow : col.downGlow; c.shadowBlur = 6 * hr; c.globalAlpha = 0.45; c.fillStyle = col[f.up ? "up" : "down"];
        c.fillRect(0, Math.round(gv.py * vr) - Math.floor(vr / 2), bitmapSize.width, Math.max(1, Math.round(vr)));
      }
      // our entry / exit marks: a soft halo where the series draws them
      for (const m of gv.halos) {
        c.shadowColor = m.color; c.shadowBlur = 12 * hr; c.globalAlpha = 0.5; c.fillStyle = m.color;
        c.beginPath(); c.arc(m.x * hr, m.y * vr, 3.5 * hr, 0, Math.PI * 2); c.fill();
      }
      c.restore();
    });
  },
};
return {
  paneViews: () => [{zOrder: () => "bottom", renderer: () => glowR}],
  updateAllViews() {
    gv.bars = []; gv.last = null; gv.py = null; gv.halos = [];
    if (o.onUpdate) o.onUpdate();
    const data = o.data();
    if (!o.ai() || !data.length) return;
    const ts = chart.timeScale(), r = ts.getVisibleLogicalRange();
    if (!r) return;
    const sp = ts.options().barSpacing || 6;
    gv.w = Math.max(1, sp * 0.72);
    const n = data.length, a = Math.max(0, Math.floor(r.from)), z = Math.min(n - 1, Math.ceil(r.to));
    const Y = (p) => series.priceToCoordinate(p);
    for (let i = a; i <= z; i++) {
      const d = data[i], x = ts.logicalToCoordinate(i);
      const yo = Y(d.open), yc = Y(d.close), yh = Y(d.high), yl = Y(d.low);
      if (x == null || yo == null || yc == null || yh == null || yl == null) continue;
      const b = {x, t: Math.min(yo, yc), b: Math.max(yo, yc), hi: yh, lo: yl, up: d.close >= d.open};
      gv.bars.push(b);
      if (i === n - 1) gv.last = b;
    }
    const ld = data[n - 1];
    gv.py = ld ? Y(ld.close) : null;
    const size = Math.min(Math.max(sp, 12), 30), seen = new Set();
    for (const m of o.marks ? o.marks() : []) {
      const i = o.idx(m.time);
      if (i == null || i < a || i > z || m.position === "inBar") continue;
      const k = i + m.position;
      if (seen.has(k)) continue;                           // the first mark of a bar side (stacked ones sit further out)
      seen.add(k);
      const d = data[i], x = ts.logicalToCoordinate(i);
      const y = m.position === "aboveBar" ? Y(d.high) - size / 2 - 3 : Y(d.low) + size / 2 + 3;
      if (x != null && y != null && m.glow !== false) gv.halos.push({x, y, color: m.color});
    }
  },
};}

// the candle glow's soft passes [scale, alpha]: two for a big chart; ONE for a small cell of 여러 차트 (screens/charts.js,
// `lite`), where up to nine charts redraw together
const GLOW_PASSES = [[3, 0.5], [8, 0.6]], LITE_PASSES = [[6, 0.7]];

/** The '선' menu's choices of one deck key on this device: {off: Set of groups, hide: Set of line ids, parts: Set of
 *  프리미엄 지표 parts}. The same rule chartDeck starts from (nothing stored yet, or stored before the calm default
 *  (DECK_V): the calm default, on a phone the position / stop / level / 프리미엄 지표 groups off, unless `defaults` says
 *  otherwise). The 설정 panel (core/settings.js) reads it and writes {v, off, hide, smc} back (deckValue) under the same
 *  key ("cfx-" + key) through core/prefs.js, so a deck on screen follows at once. */
export function deckState(key, groups, defaults) {
  const raw = local.get("cfx-" + key, null);
  const saved = raw && typeof raw === "object" ? raw : {};
  const fresh = saved.v !== DECK_V;
  const defOff = groups.filter((g) => (defaults && g in defaults ? !defaults[g] : (narrow() && ["pos", "risk", "sr", "smc"].includes(g))));
  const partIds = SMC_PARTS.map((x) => x.id);
  return {off: new Set(!fresh && Array.isArray(saved.off) ? saved.off.filter((g) => groups.includes(g)) : defOff),
    hide: new Set(Array.isArray(saved.hide) ? saved.hide.slice(-60) : []),
    parts: new Set(!fresh && Array.isArray(saved.smc) ? saved.smc.filter((x) => partIds.includes(x)) : SMC_DEF)};
}
/** What a deck stores under "cfx-" + key (the shape chartDeck's save writes): deckState's sets as arrays, the version. */
export const deckValue = (now) => ({v: DECK_V, off: [...now.off], hide: [...now.hide].slice(-60), smc: [...now.parts]});
export {FLASH_KEY};
export {LIGHT_KEY};

/** The candle glow alone, for a chart without the deck (매매법 / 계좌 charts): the AI skin only, null otherwise. */
export function candleGlow(chart, series) {
  if (!isAi()) return null;
  const col = colours();
  let data = [];
  const p = glowPrimitive({chart, series, data: () => data, col: () => col, ai: () => true,
    onUpdate: () => { try { data = series.data(); } catch (e) { data = []; } }});
  series.attachPrimitive(p);
  return p;
}

/**
 * chartDeck({chart, series, wrap, box, ctx, key, groups, defaults, tag, sym, lite}) -> deck
 *   wrap: the positioned box around the chart element `box` (the layers sit in it, the pills over the pane)
 *   key: per-device memory name ("term" | "chart" | "grid"); groups: the ids the '선' menu lists (GROUP_KO)
 *   defaults: {group: on?} the "기본" state of those groups (else all on; on a phone pos / risk / sr / smc off)
 *   tag: true draws our own last-price tag on the right axis (glows, pulses on a real new price)
 *   sym: () -> the coin on screen (its relay events light the halves at full strength; others dimmer)
 *   legend: the screen's OHLC legend element over the chart (the right-edge names start under it when it reaches them)
 *   lite: a small cell of 여러 차트: the same glow and flash, the glow drawn in one soft pass instead of two
 * deck: {setData, update, setMarkers, setLines, flash, shown(g), onToggle(fn), onData(fn), menuEl, menuBtn, smcBtn ('프리미엄 지표 ▾'),
 *        lightChip, lightMenu (the '조명 · 번쩍임' menu; flashSel is the same element, its old name), viewBtn (one
 *        '보기 ▾' menu with the light, the flash and the 프리미엄 지표 parts, for a narrow header), place, ready}
 *        The 설정 panel (core/settings.js) changes the '선' choices, 번쩍임 and 조명 of a deck on screen through
 *        core/prefs.js under the deck's own storage keys; the deck's menus follow at once, and the deck's own menus tell
 *        the panel (and the other decks of this key) the same way.
 *        onToggle(fn): fn(group) after one group changed; fn(null, how) after several at once, how = "all" | "none" (모두 보기 /
 *        모두 숨기기), "default" (기본으로) or "pref" (the 설정 panel or another deck of this key): a subscriber that only
 *        redraws ignores how; screens/chart-plus.js turns its add-ons off on "default" / "none".
 */
export function chartDeck(o) {
  const {chart, series, wrap, box, ctx} = o;
  const key = "cfx-" + (o.key || "chart");
  const groups = o.groups || ["pos", "risk", "sr", "smc", "ev", "vol"];
  const raw = local.get(key, null);
  const saved = raw && typeof raw === "object" ? raw : {};
  // a device that saved its choice before the calm default (10/06 ~14:00) starts once from the new "기본"; the lines it
  // hid one by one stay hidden
  const fresh = saved.v !== DECK_V;
  const defOff = groups.filter((g) => (o.defaults && g in o.defaults ? !o.defaults[g] : (narrow() && ["pos", "risk", "sr", "smc"].includes(g))));
  const partIds = SMC_PARTS.map((x) => x.id);
  const st = {
    off: new Set(!fresh && Array.isArray(saved.off) ? saved.off.filter((g) => groups.includes(g)) : defOff),
    hide: new Set(Array.isArray(saved.hide) ? saved.hide.slice(-60) : []),
    parts: new Set(!fresh && Array.isArray(saved.smc) ? saved.smc.filter((x) => partIds.includes(x)) : SMC_DEF),
    data: [], col: colours(), ai: isAi(), smc: null, smcAt: null, range: null, zone: null, split: null, lastPx: null, raf: 0, marks: [], idx: new Map(),
  };
  const subs = [];
  // the same storage key as before; core/prefs.js then tells the other decks of this key on the screen (the 여러 차트
  // cells share "grid"), so they follow at once and a later save of theirs cannot drop a line hidden here; this deck
  // skips its own echo (`saving`)
  let saving = false;
  const save = () => {
    const v = {v: DECK_V, off: [...st.off], hide: [...st.hide].slice(-60), smc: [...st.parts]};
    local.set(key, v);
    saving = true;
    try { tellPref(key, v); } finally { saving = false; }
  };
  const shown = (g) => !st.off.has(g);
  /** a 프리미엄 지표 part is drawn: the indicator on and that part chosen */
  const part = (id) => shown("smc") && st.parts.has(id);

  // ---------------------------------------------------------------- layers (under the transparent chart canvas)
  wrap.classList.add("cfx");
  wrap.dataset.fx = st.ai ? "ai" : "plain";
  const depth = h("i", {class: "cfx-depth", "aria-hidden": "true"});
  const ambUp = h("i", {class: "cfx-amb", dataset: {tone: "up"}, "aria-hidden": "true"});
  const ambDn = h("i", {class: "cfx-amb", dataset: {tone: "down"}, "aria-hidden": "true"});
  const flashEl = h("i", {class: "cfx-flash", "aria-hidden": "true"});
  const wPrem = h("span", {class: "cfx-zw", dataset: {tone: "down"}}, "Premium");
  const wDisc = h("span", {class: "cfx-zw", dataset: {tone: "up"}}, "Discount");
  const under = h("div", {class: "cfx-under", "aria-hidden": "true"}, depth, ambDn, ambUp, wPrem, wDisc, flashEl);
  const pills = h("div", {class: "cfx-pills"});
  // the ▼ markers and the names' "+N" chip share the bottom-right corner (paintEdge fills only its own list)
  const edgeTop = h("div", {class: "cfx-edge top"}), edgeBot = h("div", {class: "cfx-edgel"});
  const namesMore = h("button", {type: "button", class: "cfx-nmore num", hidden: true, "aria-expanded": "false", onclick: (e) => { e.stopPropagation(); openNames(namesList.hidden); }});
  const namesList = h("div", {class: "cfx-nlist", hidden: true, role: "list", "aria-label": "가려진 선 이름"});
  const edgeBotRow = h("div", {class: "cfx-edge bot"}, edgeBot, namesMore, namesList);
  const smcKey = h("div", {class: "cfx-smckey", hidden: true, title: SMC_NOTE}, SMC_KEY);
  // the right-edge names (core/edgelabels.js): a few reused name tags and their leaders, and the hover / tap tag
  const names = h("div", {class: "cfx-names"});
  const hoverTag = h("div", {class: "cfx-ntag num", hidden: true, role: "status"});
  const over = h("div", {class: "cfx-over"}, pills, names, hoverTag, edgeTop, edgeBotRow, smcKey);
  const tagEl = o.tag ? h("div", {class: "cfx-tag", hidden: true}, h("b", {class: "num"}, "—")) : null;
  wrap.prepend(under);
  wrap.append(over);
  if (tagEl) wrap.append(tagEl);
  box.classList.add("cfx-box");
  if (st.ai) chart.applyOptions({layout: {background: {type: "solid", color: "transparent"}}});

  // ---------------------------------------------------------------- volume (an overlay scale along the bottom)
  let vol = null;
  try {
    vol = chart.addHistogramSeries({priceScaleId: "cfxvol", priceFormat: {type: "volume"}, lastValueVisible: false, priceLineVisible: false});
    chart.priceScale("cfxvol").applyOptions({scaleMargins: {top: 0.86, bottom: 0}, visible: false});
  } catch (e) { vol = null; }
  const hasVol = () => st.data.some((b) => Number(b.volume) > 0);
  const volRow = (b) => ({time: b.time, value: Number(b.volume) || 0, color: b.close >= b.open ? st.col.volUp : st.col.volDown});
  function paintVol() {
    if (!vol) return;
    const on = shown("vol") && hasVol();
    vol.applyOptions({visible: on});
    chart.priceScale("right").applyOptions({scaleMargins: {top: 0.08, bottom: on ? 0.16 : 0.08}});
    if (on) vol.setData(st.data.filter((b) => b.volume != null).map(volRow)); else vol.setData([]);
  }

  // ---------------------------------------------------------------- the glow (under the candles; glowPrimitive below)
  series.attachPrimitive(glowPrimitive({chart, series, data: () => st.data, marks: () => st.marks, idx: (t) => st.idx.get(t),
    col: () => st.col, ai: () => st.ai, onUpdate: () => schedule(), lite: !!o.lite}));

  // ---------------------------------------------------------------- lines (our positions, stops, levels, alerts)
  const lines = new Map();                    // id -> {spec, y, vis}
  const axisViews = [];
  const lineR = {
    draw(target) {
      target.useBitmapCoordinateSpace(({context: c, horizontalPixelRatio: hr, verticalPixelRatio: vr, bitmapSize, mediaSize}) => {
        const col = st.col;
        c.save();
        for (const L of lines.values()) {
          if (!L.vis || L.y == null || L.y < 0 || L.y > mediaSize.height) continue;
          const sp = L.spec, colr = col[sp.tone] || col.flat;
          const y = Math.round(L.y * vr) + 0.5 * (Math.round(vr) % 2), lw = Math.max(1, Math.round(vr));
          c.setLineDash(sp.dash === 1 ? [5 * hr, 4 * hr] : sp.dash === 2 ? [1.5 * hr, 3 * hr] : []);
          c.lineWidth = lw;
          c.strokeStyle = colr;
          if (st.ai && sp.glow !== false) {
            c.shadowColor = sp.tone === "up" ? col.upGlow : sp.tone === "down" ? col.downGlow : col.accentGlow;
            c.shadowBlur = 5 * hr; c.globalAlpha = (sp.alpha ?? 0.6) * 0.7;
            c.beginPath(); c.moveTo(0, y); c.lineTo(bitmapSize.width, y); c.stroke();
            c.shadowBlur = 0;
          }
          c.globalAlpha = sp.alpha ?? 0.6;
          c.beginPath(); c.moveTo(0, y); c.lineTo(bitmapSize.width, y); c.stroke();
        }
        c.restore();
      });
    },
  };
  const linePrim = {
    paneViews: () => [{zOrder: () => "normal", renderer: () => lineR}],
    priceAxisViews: () => axisViews,
    updateAllViews() {
      for (const L of lines.values()) L.y = L.vis ? series.priceToCoordinate(L.spec.price) : null;
      schedule();
    },
  };
  series.attachPrimitive(linePrim);

  const isVis = (sp) => shown(sp.group) && !st.hide.has(sp.id) && !(sp.alias || []).some((x) => st.hide.has(x)) && !(sp.parent && st.hide.has(sp.parent));
  function rebuildAxis() {
    axisViews.length = 0;
    for (const L of lines.values()) {
      if (!L.spec.axis) continue;
      axisViews.push({
        coordinate: () => (L.y == null ? -1000 : L.y), text: () => fmtPrice(L.spec.price), textColor: () => st.col.axisInk,
        backColor: () => st.col[L.spec.tone] || st.col.flat, visible: () => !!L.vis && L.y != null, tickVisible: () => false,
      });
    }
  }
  /**
   * setLines([{id, group, price, tone, dash: 0 | 1 | 2, alpha, axis, label, parent, edge,
   *            pill: {text, title, chips: [{text, ids: [child line ids], title}]}}]) — the whole set of this kind
   *   (``kind`` names the caller's own set, so the terminal's positions and its levels can be set separately).
   */
  function setLines(kind, list) {
    for (const [id, L] of lines) if (L.kind === kind && !list.some((x) => x.id === id)) { lines.delete(id); if (L.pill) L.pill.remove(); }
    for (const sp of list) {
      if (!Number.isFinite(sp.price)) continue;
      const L = lines.get(sp.id) || {kind, y: null, vis: false, pill: null};
      L.kind = kind; L.spec = sp; L.vis = isVis(sp);
      if (sp.pill) L.pill = paintPill(L, L.pill); else if (L.pill) { L.pill.remove(); L.pill = null; }
      lines.set(sp.id, L);
    }
    rebuildAxis();
    linePrim.updateAllViews();
    smcP.request();
    refresh();
  }
  function hideLine(id, on = true) {
    if (on) st.hide.add(id); else st.hide.delete(id);
    save(); revis();
  }
  function revis() {
    for (const L of lines.values()) {
      L.vis = isVis(L.spec);
      if (L.pill) for (const ch of L.pill.querySelectorAll(".cfx-chip")) ch.setAttribute("aria-pressed", String((ch._ids || []).some((x) => !st.hide.has(x))));
    }
    linePrim.updateAllViews(); smcP.request(); paintMenu(); refresh();
  }
  function paintPill(L, old) {
    const sp = L.spec, p = sp.pill;
    const chips = (p.chips || []).map((ch) => {
      const b = h("button", {type: "button", class: "cfx-chip", title: ch.title || `${ch.text} 선 보이기·숨기기`, "aria-pressed": String(ch.ids.some((x) => !st.hide.has(x))),
        onclick: (e) => { e.stopPropagation(); const on = ch.ids.some((x) => !st.hide.has(x)); for (const x of ch.ids) { if (on) st.hide.add(x); else st.hide.delete(x); } save(); revis(); }}, ch.text);
      b._ids = ch.ids;
      return b;
    });
    const el = h("div", {class: "cfx-pill", dataset: {tone: TONES.includes(sp.tone) ? sp.tone : "flat"}, title: (p.title ? p.title + " · " : "") + "누르면 이 선을 숨깁니다 (선 메뉴에서 다시 보기)"},
      h("button", {type: "button", class: "cfx-pt num", onclick: () => hideLine(sp.id)}, p.text), ...chips,
      h("button", {type: "button", class: "cfx-x", "aria-label": "이 선 숨기기", title: "이 선 숨기기", onclick: () => hideLine(sp.id)}, "×"),
      h("span", {class: "cfx-more num", hidden: true}));
    if (old) old.replaceWith(el); else pills.append(el);
    return el;
  }

  // ---------------------------------------------------------------- placing the DOM overlays (one frame per change)
  let pane = {w: 0, h: 0};
  function schedule() {
    if (st.raf) return;
    st.raf = requestAnimationFrame(() => { st.raf = 0; place(); });
  }
  function measure() {
    let sw = 0, th = 0;
    try { sw = chart.priceScale("right").width(); th = chart.timeScale().height(); } catch (e) { /* mid-layout */ }
    pane = {w: Math.max(0, box.clientWidth - sw), h: Math.max(0, box.clientHeight - th), sw, x: box.offsetLeft, y: box.offsetTop};
  }
  function place() {
    measure();
    for (const el of [under, over]) {
      el.style.left = pane.x + "px"; el.style.top = pane.y + "px"; el.style.width = pane.w + "px"; el.style.height = pane.h + "px";
    }
    layoutPills();
    placeSplit();
    layoutNames();
    if (tagEl) {
      const d = st.data[st.data.length - 1], y = d ? series.priceToCoordinate(d.close) : null;
      if (y == null || y < 0 || y > pane.h) tagEl.hidden = true;
      else {
        tagEl.hidden = false;
        tagEl.style.left = (pane.x + pane.w) + "px"; tagEl.style.width = pane.sw + "px";
        tagEl.style.transform = `translateY(${Math.round(pane.y + y - 10)}px)`;
      }
    }
  }
  function layoutPills() {
    const on = [], above = [], below = [];
    for (const L of lines.values()) {
      if (!L.pill) continue;
      const y = L.vis ? L.y : null;
      if (!L.vis || y == null) { L.pill.hidden = true; continue; }
      if (y < 0) { L.pill.hidden = true; above.push(L); continue; }
      if (y > pane.h) { L.pill.hidden = true; below.push(L); continue; }
      on.push({L, y});
    }
    on.sort((a, b) => a.y - b.y);
    let prev = null, bottom = -Infinity;
    for (const it of on) {
      const want = Math.max(TOP_GAP, it.y - PILL_H / 2);              // under the OHLC legend line
      const top = Math.max(want, bottom + PILL_GAP);
      if (prev && top - want > PILL_H * 1.6) {             // too far from its own line: merge into the pill above
        it.L.pill.hidden = true;
        prev.more.push(it.L);
        continue;
      }
      it.L.pill.hidden = false;
      it.L._top = Math.round(Math.min(top, pane.h - PILL_H));       // (the right-edge names keep clear of it)
      it.L.pill.style.transform = `translateY(${it.L._top}px)`;
      it.L.pill.classList.toggle("off", Math.abs(top - want) > 1);
      bottom = top + PILL_H;
      prev = {L: it.L, more: []};
      it.prev = prev;
      it.L._grp = prev;
    }
    for (const it of on) {
      if (!it.prev) continue;
      const m = it.L.pill.querySelector(".cfx-more");
      const more = it.prev.more;
      m.hidden = !more.length;
      if (more.length) { m.textContent = `+${more.length}`; m.title = more.map((x) => x.spec.pill.text).join("\n"); }
    }
    paintEdge(edgeTop, above, "▲");
    paintEdge(edgeBot, below, "▼");
  }
  function paintEdge(el, list, arrow) {
    list.sort((a, b) => (arrow === "▲" ? a.spec.price - b.spec.price : b.spec.price - a.spec.price));
    const key = list.map((L) => L.spec.id + L.spec.pill.text).join("|");
    if (el._key === key) return;
    el._key = key;
    el.replaceChildren(...[...list.slice(0, EDGE_MAX).map((L) => h("span", {class: "cfx-em num", dataset: {tone: L.spec.tone}, title: `${L.spec.pill.title || L.spec.pill.text} · 화면 ${arrow === "▲" ? "위" : "아래"}`},
      `${arrow} ${fmtPrice(L.spec.price)} · ${L.spec.pill.short || L.spec.pill.text}`)),
    list.length > EDGE_MAX ? h("span", {class: "cfx-em num", dataset: {tone: "flat"}}, `+${list.length - EDGE_MAX}`) : null].filter(Boolean));
  }

  // ---------------------------------------------------------------- the right-edge names (core/edgelabels.js)
  // One small name per line next to the price axis: our named lines (저항 / 지지 / 잠금 / 손절 / 알림 …, lineWords
  // below) and the OB / FVG zones 프리미엄 지표 draws now. Merged, nudged apart, at most NAMES_MAX (the nearest to the
  // price); a nudged name has a thin leader to its line. Reused nodes, moved with a transform: no DOM churn per frame.
  const pool = [];
  let shownNames = [], hiddenNames = [], hov = null;
  const nameH = () => Math.round(st.col.fs * 1.25 + 4);             // .cfx-name: --t-2xs, line-height 1.25, 2 px padding
  let mctx = null;
  /** a name tag's width without reading the DOM (.cfx-name: 600 --t-2xs --f-term, 11 px padding) */
  function nameW(s) {
    if (mctx == null) { try { mctx = document.createElement("canvas").getContext("2d") || false; } catch (e) { mctx = false; } }
    if (!mctx) return s.length * st.col.fs * 0.9 + 12;
    mctx.font = `600 ${st.col.fs}px ${st.col.font || "monospace"}`;
    return mctx.measureText(s).width + 12;
  }
  function nameItems() {
    const out = lineWords();
    const v = smcView();
    const ts = chart.timeScale();
    for (const z of (v && v.zones) || []) {
      const x = ts.logicalToCoordinate(z.i);
      if (x == null || x > pane.w) continue;                        // not drawn (scrolled back before it): no name
      const mid = (z.top + z.bot) / 2, text = z.kind === "ob" ? (z.dir > 0 ? "OB+" : "OB−") : "FVG";
      out.push({id: `z:${z.kind}:${z.i}:${z.dir}`, price: mid, y: series.priceToCoordinate(mid), text, tone: z.kind,
        title: `${text} ${z.kind === "ob" ? "주문 블록" : "가격 공백"} ${fmtPrice(z.bot)} – ${fmtPrice(z.top)} (프리미엄 지표 · 신호 아님)`});
    }
    return out;
  }
  function layoutNames() {
    const items = nameItems().filter((x) => x.y != null && x.y >= 0 && x.y <= pane.h);
    const last = st.data[st.data.length - 1], H = nameH();
    // the screen's OHLC legend line (o.legend, top left): when it reaches the names' column, the names start under it
    let lo = 2, hi = pane.h - 2;
    const lg = o.legend;
    if (lg && lg.textContent && lg.offsetLeft + lg.offsetWidth - pane.x > pane.w - 180) lo = Math.max(lo, lg.offsetTop + lg.offsetHeight - pane.y + 2);
    // our ▲ / ▼ markers (lines off the price range, layoutPills) hold the top / bottom right corners; the "+N" chip shares
    // the bottom one: the names keep clear of them
    const rowH = H + 6;
    if (edgeTop.childElementCount) lo = Math.max(lo, 4 + edgeTop.offsetHeight + 2);
    if (edgeBot.childElementCount) hi = Math.min(hi, pane.h - 4 - Math.max(rowH, edgeBotRow.offsetHeight) - 2);
    // a narrow pane (the left menu with bigger type): a name that would sit on one of our left pills goes to the "+N"
    // list and the hover tag instead, so a name and a pill never cover each other
    const pb = [];
    for (const L of lines.values()) if (L.pill && !L.pill.hidden && L._top != null) pb.push({t: L._top, b: L._top + PILL_H, r: 6 + L.pill.offsetWidth});
    const run = (top) => {
      // a short pane shows only as many names as fit one under another (dodge would squeeze them onto each other)
      const fitN = Math.max(0, Math.min(NAMES_MAX, Math.floor((top - lo) / (H + 1))));
      const lay = edgeLayout(items, {price: last ? last.close : null, max: fitN, H: H + 1, lo, hi: top});
      if (pb.length) {
        const keep = [];
        for (const g of lay.shown) {
          const y0 = g.ly - H / 2, y1 = y0 + H, left = pane.w - 4 - nameW(g.text);
          if (pb.some((q) => q.t < y1 + 2 && y0 - 2 < q.b && left - 6 < q.r)) lay.hidden.push(g); else keep.push(g);
        }
        lay.shown = keep;
      }
      return lay;
    };
    let lay = run(hi);
    if (lay.hidden.length && !edgeBot.childElementCount) {            // the "+N" chip will show: keep its corner free
      const hi2 = pane.h - 4 - rowH - 2;
      if (lay.shown.some((g) => g.ly + H / 2 > hi2)) lay = run(hi2);
    }
    shownNames = lay.shown; hiddenNames = lay.hidden;
    while (pool.length < shownNames.length) {
      const lead = h("i", {class: "cfx-lead", "aria-hidden": "true"}), el = h("span", {class: "cfx-name num"}, h("span"), lead);
      names.append(el);
      pool.push({el, txt: el.firstChild, lead});
    }
    pool.forEach((t, i) => {
      const g = shownNames[i];
      if (!g) { t.el.hidden = true; return; }
      if (t.txt.textContent !== g.text) t.txt.textContent = g.text;
      if (t.el.dataset.tone !== g.tone) t.el.dataset.tone = g.tone;
      const tt = g.items.map((x) => x.title || `${x.text} ${fmtPrice(x.price)}`).join("\n");
      if (t.el.title !== tt) t.el.title = tt;
      t.el.hidden = false;
      const top = Math.round(g.ly - H / 2), rel = g.y - top;          // the line's height inside the name's box
      t.el.style.transform = `translateY(${top}px)`;
      const off = Math.abs(g.ly - g.y) >= 3;
      t.lead.hidden = !off;
      if (off) {
        t.lead.dataset.dir = rel < H / 2 ? "up" : "down";
        t.lead.style.top = Math.round(Math.min(rel, H / 2)) + "px";
        t.lead.style.height = Math.max(1, Math.round(Math.abs(rel - H / 2))) + "px";
      }
    });
    paintNamesMore();
    if (hov) showHover(hov.y, 0, hov);
  }
  // the names that did not get a place: a "+N" chip (its list on a tap), and each one on hover / tap of its line
  function paintNamesMore() {
    const n = hiddenNames.length;
    namesMore.hidden = !n;
    over.classList.toggle("nmore", !!n);
    if (!n) { if (!namesList.hidden) openNames(false); return; }
    const t = `이름 +${n}`;
    if (namesMore.textContent !== t) namesMore.textContent = t;
    namesMore.title = `가려진 선 이름 ${n}개 · 선에 마우스를 올리거나 누르면 보입니다\n` + hiddenNames.map((g) => `${g.text} ${fmtPrice(g.price)}`).join("\n");
    if (!namesList.hidden) fillNames();
  }
  function fillNames() {
    const key = hiddenNames.map((g) => g.text + fmtPrice(g.price)).join("|");
    if (namesList._key === key) return;
    namesList._key = key;
    namesList.replaceChildren(...hiddenNames.slice().sort((a, b) => b.price - a.price).map((g) =>
      h("span", {class: "cfx-nli num", role: "listitem", dataset: {tone: g.tone}}, `${g.text} `, h("b", null, fmtPrice(g.price)))));
  }
  function openNames(on) {
    namesList.hidden = !on;
    namesMore.setAttribute("aria-expanded", String(on));
    if (on) { namesList._key = null; fillNames(); }
  }
  // lines named only on hover / tap: the equilibrium, the liquidity lines, the OTE edges (when they are drawn)
  function hoverOnly() {
    const v = smcView(), out = [];
    if (!v) return out;
    if (v.eq && v.range) out.push({text: "중간선 (Equilibrium)", price: v.range.eq, tone: "flat"});
    for (const q of v.liq || []) out.push({text: q.kind === "BSL" ? "BSL 위쪽 유동성" : "SSL 아래쪽 유동성", price: q.price, tone: "flat"});
    if (v.ote && v.range) v.range.ote.forEach((p, i) => out.push({text: `OTE ${i ? "0.79" : "0.62"}`, price: p, tone: "flat"}));
    return out;
  }
  /** The hover / tap tag: the name and price of the hidden name or hover-only line nearest to ``y`` (within tol px). */
  function showHover(y, tol, keep) {
    let it = keep || null;
    if (!keep && y != null) {
      let bd = tol;
      for (const g of hiddenNames) { const d = Math.abs(g.y - y); if (d <= bd) { it = {text: g.text, price: g.price, tone: g.tone}; bd = d; } }
      for (const x of hoverOnly()) { const yy = series.priceToCoordinate(x.price); if (yy != null && Math.abs(yy - y) < bd) { it = x; bd = Math.abs(yy - y); } }
    }
    const yy = it ? series.priceToCoordinate(it.price) : null;
    if (!it || yy == null || yy < 0 || yy > pane.h) { hov = null; hoverTag.hidden = true; return; }
    hov = {...it, y: yy};
    const t = `${it.text} ${fmtPrice(it.price)}`;
    if (hoverTag.textContent !== t) hoverTag.textContent = t;
    hoverTag.dataset.tone = it.tone;
    hoverTag.hidden = false;
    hoverTag.style.transform = `translateY(${Math.round(yy - nameH() / 2)}px)`;
  }
  chart.subscribeCrosshairMove((p) => showHover(p && p.point ? p.point.y : null, 6));
  chart.subscribeClick((p) => showHover(p && p.point ? p.point.y : null, 14));
  if (ctx && ctx.listen) ctx.listen(document, "pointerdown", (e) => { if (!namesList.hidden && !edgeBotRow.contains(e.target)) openNames(false); });

  // ---------------------------------------------------------------- ambient (blinking halves) + flash
  let fmode = modeOf(local.get(FLASH_KEY, DEFAULT_FLASH)).id;
  let lmode = lightModeOf(local.get(LIGHT_KEY, DEFAULT_LIGHT)).id;
  const sched = flashScheduler({
    reduced, visible, mode: () => fmode,
    play(ev, T) {
      if (!st.ai || typeof flashEl.animate !== "function") return;
      flashEl.dataset.tone = ev.tone;
      try {
        if (flashEl._a) flashEl._a.cancel();
        const hold = T - ENVELOPE.inMs - ENVELOPE.outMs;
        flashEl._a = flashEl.animate([{opacity: 0}, {opacity: ev.k, offset: ENVELOPE.inMs / T, easing: "ease-in-out"},
          {opacity: ev.k, offset: (ENVELOPE.inMs + hold) / T, easing: "ease-in"}, {opacity: 0}], {duration: T, easing: "linear"});
      } catch (e) { /* an old browser: no flash */ }
    },
  });
  // the blinking halves (core/blink.js): tone "down" (red) is the Premium top, tone "up" (sky blue) the Discount bottom;
  // each blink is one CSS opacity transition on its layer (chartfx.css .cfx-amb), nothing is redrawn
  const halfEl = {top: ambDn, bottom: ambUp};
  // a deck built after its screen was left (the chart loads asynchronously) must not start anything: ctx.track would
  // never run its cleanup, so a relay listener or a blink timer would outlive the screen
  const gone = () => !!(ctx && typeof ctx.alive === "function" && !ctx.alive());
  const blink = blinker({
    reduced, visible, mode: () => (st.ai && !gone() ? lmode : "off"),
    apply(half, k, ms, kind) {
      const el = halfEl[half];
      // "important": under prefers-reduced-motion components.css stops every transition (!important), which would
      // turn the calm slow fade (blink.js CALM) into an abrupt on / off; this one opacity fade is the calm version
      el.style.setProperty("transition", ms > 0 ? `opacity ${Math.round(ms)}ms ${kind === "in" ? "ease-out" : "ease-in"}` : "none", "important");
      el.style.opacity = String(Math.round(k * 1000) / 1000);
    },
    onSrc: () => paintChip(),
  });
  // the real market trades for the light: the page's ONE relay connection (core/ticks.js; shared with the sound and the
  // terminal's lists), listened to only while the light blinks in the AI skin, left when the screen is left
  let relayOff = null;
  function relaySync() {
    const want = st.ai && lmode === "blink" && !gone();
    if (want && !relayOff) {
      relayOff = listenTicks((m) => {
        if (!m || m.state !== "live" || !Array.isArray(m.ev)) return;
        const sym = typeof o.sym === "function" ? o.sym() : null;
        for (const ev of m.ev) blink.real(relayBlink(ev, sym));
      });
    } else if (!want && relayOff) { const off = relayOff; relayOff = null; off(); }
  }
  if (ctx && ctx.listen) ctx.listen(document, "visibilitychange", () => blink.sync());      // hidden: dark, no timer
  if (ctx && ctx.track) ctx.track(() => { sched.cancel(); if (flashEl._a) flashEl._a.cancel(); blink.stop(); if (relayOff) { relayOff(); relayOff = null; } });

  // '조명 · 번쩍임' menu (per device): 조명 깜박 (기본) / 계속 켜짐 / 끄기 and 번쩍임 자주 / 보통 / 끄기. Reduced motion:
  // calm slow fades, no flash whatever is chosen.
  const radio = (label, sub, fn) => h("button", {type: "button", class: "cfx-mi", role: "menuitemradio", "aria-checked": "false", onclick: fn},
    h("i", {class: "cfx-ck cfx-rd", "aria-hidden": "true"}), h("span", null, label), sub ? h("small", {class: "cfx-msub"}, sub) : null);
  // (the same items are built twice: here and in the '보기 ▾' menu below; paintLight sets every copy)
  const lItems = new Map(LIGHT_MODES.map((m) => [m.id, []])), fItems = new Map(FLASH_MODES.map((m) => [m.id, []])), lNotes = [];
  const lightItems = () => {
    const note = h("p", {class: "cfx-mnote"});
    lNotes.push(note);
    return [h("p", {class: "cfx-mhd"}, "조명 (위 빨강 · 아래 하늘색)"),
      h("div", {class: "cfx-mgrp", role: "group", "aria-label": "조명"}, LIGHT_MODES.map((m) => {
        const b = radio(m.id === DEFAULT_LIGHT ? `${m.ko} (기본)` : m.ko, LIGHT_SUB[m.id], () => setLight(m.id));
        lItems.get(m.id).push(b);
        return b;
      })),
      h("p", {class: "cfx-mhd"}, "번쩍임 (큰 체결 · 청산 · 우리 체결)"),
      h("div", {class: "cfx-mgrp", role: "group", "aria-label": "번쩍임"}, FLASH_MODES.map((m) => {
        const b = radio(m.ko, FLASH_SUB[m.id], () => setFlash(m.id));
        fItems.get(m.id).push(b);
        return b;
      })),
      note];
  };
  const lmenu = h("div", {class: "cfx-menu cfx-lmenu", role: "menu", hidden: true, "aria-label": "조명과 번쩍임"}, lightItems());
  const lNow = h("b", {class: "cfx-lnow"}), fNow = h("b", {class: "cfx-lnow"});
  const lbtn = h("button", {type: "button", class: "cfx-mbtn cfx-lbtn", "aria-haspopup": "menu", "aria-expanded": "false", "aria-label": "조명과 번쩍임",
    onclick: (e) => { e.stopPropagation(); openLight(lmenu.hidden); }},
  "조명 ", lNow, h("span", {class: "cfx-lf"}, " · 번쩍임 ", fNow), " ▾");
  const flashSel = h("span", {class: "cfx-mwrap cfx-lwrap", hidden: !st.ai}, lbtn, lmenu);
  function openLight(on) {
    lmenu.hidden = !on;
    lbtn.setAttribute("aria-expanded", String(on));
    if (on) { paintLight(); const f = lmenu.querySelector('[aria-checked="true"]') || lmenu.querySelector("button"); if (f) f.focus(); }
  }
  if (ctx && ctx.listen) {
    ctx.listen(document, "pointerdown", (e) => { if (!lmenu.hidden && !flashSel.contains(e.target)) openLight(false); });
    ctx.listen(document, "keydown", (e) => { if (e.key === "Escape" && !lmenu.hidden) { openLight(false); lbtn.focus(); } });
  }
  // the menu's choice goes through core/prefs.js (it stores under the same key, then every listener of it follows: this
  // deck's onPref handlers below, the other decks on screen, the 설정 panel's rows)
  function setLight(id) { setPref(LIGHT_KEY, lightModeOf(id).id); }
  function setFlash(id) { setPref(FLASH_KEY, modeOf(id).id); }
  function paintLight() {
    for (const [id, bs] of lItems) for (const b of bs) b.setAttribute("aria-checked", String(id === lmode));
    for (const [id, bs] of fItems) for (const b of bs) b.setAttribute("aria-checked", String(id === fmode));
    lNow.textContent = LIGHT_SHORT[lmode]; fNow.textContent = modeOf(fmode).ko;
    lbtn.title = `조명: ${lightModeOf(lmode).ko} · 번쩍임: ${modeOf(fmode).ko} (누르면 바꾸기 · 이 기기에만 기억)`;
    for (const n of lNotes) n.textContent = LIGHT_NOTE + (reduced() ? " 움직임 줄이기 설정이라 천천히 바뀝니다." : "");
    paintChip();
  }
  /** the mode on the layers (CSS: the words go with the light when it is off), the halves, the relay listener */
  function lightSync() { under.dataset.light = st.ai ? lmode : "off"; blink.sync(); relaySync(); paintLight(); }
  const lightChip = h("span", {class: "cfx-light", hidden: !st.ai, tabindex: "0"}, h("i", {"aria-hidden": "true"}), h("span", null, "빛"));
  /** The chip's tooltip: what the halves mean, where they split, what the light follows right now, the flashes. */
  function paintChip() {
    const sp = st.split;
    const now = lmode === "blink" ? (blink.src() === "real" ? LIGHT_REAL : blink.src() === "deco" ? LIGHT_DECO : "조명 깜박: 체결 소식을 기다리는 중")
      : lmode === "steady" ? "조명: 계속 켜짐" : "조명: 꺼짐";
    const parts = [AMBIENT_TIP, sp ? `나누는 선: ${sp.src === "range" ? "지금 범위의 중간값" : "화면 고가·저가의 중간"} ${fmtPrice(sp.eq)}` : null, now, FLASH_TIP].filter(Boolean);
    lightChip.title = parts.join("\n");
    lightChip.setAttribute("aria-label", parts.join(". "));
  }
  wPrem.title = AMBIENT_TIP;
  /** The Premium / Discount split at the price scale's current position (called with every redraw: pan, zoom, data). */
  function placeSplit() {
    if (!st.ai || !st.data.length) { under.dataset.split = ""; return; }
    let vis = st.data;
    const r = chart.timeScale().getVisibleLogicalRange();
    if (r) vis = st.data.slice(Math.max(0, Math.floor(r.from)), Math.max(0, Math.ceil(r.to) + 1));
    const sp = splitOf(st.range, vis);
    const y = sp ? series.priceToCoordinate(sp.eq) : null;
    if (y == null) { under.dataset.split = ""; return; }
    const Y = Math.round(Math.max(0, Math.min(pane.h, y)));
    under.dataset.split = "1";
    under.style.setProperty("--split", Y + "px");
    wPrem.hidden = Y < 22; wDisc.hidden = pane.h - Y < 22;
    // the chip says which side the price is on now (and the split's source in its tooltip)
    const z = zoneOf(st.data[st.data.length - 1].close, sp.eq);
    if (z !== st.zone || sp.src !== st.zoneSrc || !st.split || sp.eq !== st.split.eq) {
      st.zone = z; st.zoneSrc = sp.src; st.split = sp;
      lightChip.dataset.tone = z === "premium" ? "down" : "up";
      lightChip.lastChild.textContent = z === "premium" ? "Premium 구간" : "Discount 구간";
      paintChip();
    }
  }

  // ---------------------------------------------------------------- 프리미엄 지표
  // the names of our lines (저항 / 지지 / 잠금 / 손절 / 알림 …) go to the right edge with the zones' (layoutNames)
  const lineWords = () => [...lines.values()].filter((L) => L.vis && L.spec.label && L.y != null)
    .map((L) => ({id: L.spec.id, price: L.spec.price, y: L.y, text: L.spec.label, tone: TONES.includes(L.spec.tone) ? L.spec.tone : "flat", n: L.spec.count || 1,
      title: `${L.spec.label}${L.spec.count > 1 ? ` ×${L.spec.count}` : ""} ${fmtPrice(L.spec.price)}`}));
  /** What 프리미엄 지표 draws now (core/smcdraw.js): the parts that are on; "가까운 OB·FVG" = the nearest live order block
   *  and open gap above and below the price now (core/smc.js nearestZones). null while the indicator is off. */
  function smcView() {
    const r = st.smc;
    if (!r || !shown("smc")) return null;
    const P = st.parts, last = st.data[st.data.length - 1], px = last ? last.close : null;
    const zones = [], seen = new Set();
    const add = (z, kind) => {
      if (!z) return;
      const k = `${kind}:${z.i}:${z.dir}:${z.top}`;
      if (!seen.has(k)) { seen.add(k); zones.push({...z, kind}); }
    };
    if (P.has("near")) { for (const z of nearestZones(r.obsAll, px)) add(z, "ob"); for (const z of nearestZones(r.fvgsAll, px)) add(z, "fvg"); }
    if (P.has("zones")) { for (const z of r.obs) add(z, "ob"); for (const z of r.fvgs) add(z, "fvg"); }
    // the AI skin's light already washes the halves and carries the Premium / Discount words (CSS, data-words)
    return {range: r.range, eq: P.has("eq"), ote: P.has("ote"), words: P.has("words") && !st.ai, tint: !st.ai, zones,
      liq: P.has("liq") ? r.liq : [], structure: P.has("struct") ? r.structure : [], trend: P.has("trend") ? r.trend : [], legs: P.has("legs") ? r.legs : []};
  }
  const smcP = smcPrimitive({chart, series, get: smcView, col: () => st.col});
  series.attachPrimitive(smcP);
  function computeSmc() {
    // closed candles only (a forming bar can still change); the AI skin's split uses the dealing range even with the
    // indicator itself turned off
    const need = shown("smc") || st.ai;
    const r = need && st.data.length >= 31 ? smcAll(st.data.slice(0, -1)) : null;
    st.range = r && r.range;
    st.smc = shown("smc") ? r : null;
    st.smcAt = st.data.length ? st.data[st.data.length - 1].time : null;
    smcP.request(); schedule();
  }

  // ---------------------------------------------------------------- the '선' menu, '프리미엄 지표 ▾' and '보기 ▾'
  const mItems = new Map();
  const hiddenBtn = h("button", {type: "button", class: "cfx-mi cfx-mback", onclick: () => { st.hide.clear(); save(); revis(); }});
  const menu = h("div", {class: "cfx-menu", role: "menu", hidden: true, "aria-label": "차트 선 보이기"},
    groups.map((g) => {
      const b = h("button", {type: "button", class: "cfx-mi", role: "menuitemcheckbox", "aria-checked": String(shown(g)), onclick: () => toggle(g)},
        h("i", {class: "cfx-ck", "aria-hidden": "true"}), GROUP_KO[g] || g);
      mItems.set(g, b);
      return b;
    }),
    h("div", {class: "cfx-mrow"},
      h("button", {type: "button", class: "cfx-mi", title: "처음 모습: 차분한 차트 (지지·저항 등은 꺼 둠)", onclick: () => setDefault()}, "기본으로"),
      h("button", {type: "button", class: "cfx-mi", onclick: () => setAll(true)}, "모두 보기"),
      h("button", {type: "button", class: "cfx-mi", onclick: () => setAll(false)}, "모두 숨기기")),
    hiddenBtn,
    h("p", {class: "cfx-mnote"}, "선의 이름표를 누르면 그 선만 숨깁니다 · 이 기기에만 기억"));
  const menuBtn = h("button", {type: "button", class: "cfx-mbtn", "aria-haspopup": "menu", "aria-expanded": "false", title: "차트에 보일 선 고르기",
    onclick: (e) => { e.stopPropagation(); openMenu(menu.hidden); }}, "선 ", h("span", {class: "cfx-mcount num"}), " ▾");
  const menuWrap = h("span", {class: "cfx-mwrap"}, menuBtn, menu);
  function openMenu(on) {
    menu.hidden = !on;
    menuBtn.setAttribute("aria-expanded", String(on));
    if (on) { paintMenu(); keepInView(); const f = menu.querySelector("button"); if (f) f.focus(); }
  }
  /** the menu hangs from the button's right edge; with chart-plus's second column it is ~520 px wide, and on a 1280 px
   *  terminal the button sits too far left for that: the menu is moved right until it is inside the window (8 px air) */
  function keepInView() {
    menu.style.removeProperty("right");
    const r = menu.getBoundingClientRect();
    if (r.left < 8) menu.style.right = `${Math.round(r.left - 8)}px`;
  }
  if (ctx && ctx.listen) {
    ctx.listen(document, "pointerdown", (e) => { if (!menu.hidden && !menuWrap.contains(e.target)) openMenu(false); });
    ctx.listen(document, "keydown", (e) => { if (e.key === "Escape" && !menu.hidden) { openMenu(false); menuBtn.focus(); } });
  }
  /** An open menu stays inside the window (review: '보기 ▾' opens to the right of its button and, two columns wide, ran
   *  past the right edge when the head had wrapped or the left menu was on: the page scrolled sideways). */
  function fit(box) {
    box.style.transform = "";
    const r = box.getBoundingClientRect(), vw = document.documentElement.clientWidth;
    let dx = 0;
    if (r.right > vw - 8) dx = vw - 8 - r.right;
    if (r.left + dx < 8) dx = 8 - r.left;
    if (dx) box.style.transform = `translateX(${Math.round(dx)}px)`;
  }
  /** One more header menu (프리미엄 지표 ▾, 보기 ▾): its button opens / closes it, a tap outside or Escape closes it. */
  function dropdown(btn, box, wrapEl) {
    const open = (on) => {
      box.hidden = !on;
      btn.setAttribute("aria-expanded", String(on));
      if (on) { paintMenu(); paintLight(); fit(box); const f = box.querySelector('[aria-checked="true"]') || box.querySelector("button"); if (f) f.focus(); }
    };
    btn.addEventListener("click", (e) => { e.stopPropagation(); open(box.hidden); });
    if (ctx && ctx.listen) {
      ctx.listen(document, "pointerdown", (e) => { if (!box.hidden && !wrapEl.contains(e.target)) open(false); });
      ctx.listen(document, "keydown", (e) => { if (e.key === "Escape" && !box.hidden) { open(false); btn.focus(); } });
    }
  }
  // 프리미엄 지표 parts: clear on / off items (menuitemcheckbox), 기본으로 / 모두 끄기; built for each menu that lists them
  const smcItems = new Map(SMC_PARTS.map((x) => [x.id, []]));
  const smcList = () => [
    h("p", {class: "cfx-mhd"}, "프리미엄 지표 (화면 캔들로 계산한 참고선)"),
    h("div", {class: "cfx-mgrp", role: "group", "aria-label": "프리미엄 지표"}, SMC_PARTS.map((x) => {
      const b = h("button", {type: "button", class: "cfx-mi", role: "menuitemcheckbox", "aria-checked": String(part(x.id)), onclick: () => setPart(x.id, !part(x.id))},
        h("i", {class: "cfx-ck", "aria-hidden": "true"}), h("span", null, x.ko), x.sub ? h("small", {class: "cfx-msub"}, x.sub) : null);
      smcItems.get(x.id).push(b);
      return b;
    })),
    h("div", {class: "cfx-mrow"},
      h("button", {type: "button", class: "cfx-mi", title: "중간선 + 가까운 OB·FVG만", onclick: () => smcDefault()}, "기본으로"),
      h("button", {type: "button", class: "cfx-mi", onclick: () => smcOff()}, "모두 끄기")),
    h("p", {class: "cfx-mnote"}, "매매 신호가 아닌 참고선입니다 · 선에 마우스를 올리거나 누르면 이름과 가격 · 이 기기에만 기억")];
  let smcBtn = null, smcB = null;
  if (groups.includes("smc")) {
    const box = h("div", {class: "cfx-menu cfx-smcmenu", role: "menu", hidden: true, "aria-label": "프리미엄 지표 고르기"}, smcList());
    smcB = h("button", {type: "button", class: ["cfx-smcbtn", shown("smc") ? "on" : ""], "aria-haspopup": "menu", "aria-expanded": "false", title: SMC_NOTE},
      "프리미엄 지표 ▾");
    smcBtn = h("span", {class: "cfx-mwrap cfx-smcwrap"}, smcB, box);
    dropdown(smcB, box, smcBtn);
  }
  // '보기 ▾' (a narrow header, the terminal): the light and the flash (AI skin) and the 프리미엄 지표 parts in one menu
  const vbox = h("div", {class: ["cfx-menu", "cfx-vmenu", st.ai ? "two" : ""], role: "menu", hidden: true, "aria-label": "차트 보기 고르기"},
    st.ai ? h("div", {class: "cfx-vcol"}, lightItems()) : null,
    groups.includes("smc") ? h("div", {class: "cfx-vcol"}, smcList()) : null);
  const vbtn = h("button", {type: "button", class: "cfx-mbtn cfx-vbtn", "aria-haspopup": "menu", "aria-expanded": "false",
    title: `${st.ai ? "조명 · 번쩍임 · " : ""}프리미엄 지표 고르기 (이 기기에만 기억)`}, "보기 ▾");
  const viewBtn = h("span", {class: "cfx-mwrap cfx-vwrap"}, vbtn, vbox);
  dropdown(vbtn, vbox, viewBtn);
  function paintMenu() {
    for (const [g, b] of mItems) b.setAttribute("aria-checked", String(shown(g)));
    for (const [id, bs] of smcItems) for (const b of bs) b.setAttribute("aria-checked", String(part(id)));
    if (smcB) smcB.classList.toggle("on", shown("smc"));            // (a menu button: the "on" look is a class, not aria-pressed)
    vbtn.classList.toggle("on", shown("smc"));
    under.dataset.words = part("words") ? "1" : "";                // the AI light's Premium / Discount words: opt-in
    const nHid = [...lines.values()].filter((L) => st.hide.has(L.spec.id)).length;
    hiddenBtn.hidden = !nHid;
    hiddenBtn.textContent = `숨긴 선 ${nHid}개 다시 보기`;
    const offN = groups.filter((g) => !shown(g) && !defOff.includes(g)).length;        // off beyond the calm default
    menuBtn.querySelector(".cfx-mcount").textContent = offN || nHid ? `${offN ? "끔 " + offN : ""}${offN && nHid ? " · " : ""}${nHid ? "숨김 " + nHid : ""}` : "";
    smcKey.hidden = !shown("smc") || !st.smc;
  }
  function toggle(g, on = !shown(g)) {
    if (on) st.off.delete(g); else st.off.add(g);
    if (g === "smc" && on && !st.parts.size) st.parts = new Set(SMC_DEF);
    save(); applyGroup(g);
  }
  function setAll(on) {
    for (const g of groups) if (on) st.off.delete(g); else st.off.add(g);
    if (on) st.hide.clear();
    if (on && !st.parts.size) st.parts = new Set(SMC_DEF);
    save();
    for (const g of groups) applyGroup(g, true);
    revis();
    for (const fn of subs) fn(null, on ? "all" : "none");
  }
  /** 기본으로: the calm default of every group and part, the hidden lines back */
  function setDefault() {
    st.off = new Set(defOff); st.parts = new Set(SMC_DEF); st.hide.clear();
    save();
    for (const g of groups) applyGroup(g, true);
    revis();
    for (const fn of subs) fn(null, "default");
  }
  /** one 프리미엄 지표 part on / off: with the indicator off, choosing a part turns it on with that part alone */
  function setPart(id, on) {
    if (!shown("smc")) { if (!on) return; st.off.delete("smc"); st.parts = new Set([id]); }
    else if (on) st.parts.add(id);
    else { st.parts.delete(id); if (!st.parts.size) st.off.add("smc"); }
    save(); applyGroup("smc");
  }
  function smcDefault() { st.off.delete("smc"); st.parts = new Set(SMC_DEF); save(); applyGroup("smc"); }
  function smcOff() { st.off.add("smc"); save(); applyGroup("smc"); }
  function applyGroup(g, quiet) {
    if (g === "vol") paintVol();
    if (g === "smc") computeSmc();
    if (!quiet) { revis(); for (const fn of subs) fn(g); }
  }
  function refresh() { paintMenu(); schedule(); }

  // 설정 한 곳 (core/settings.js through core/prefs.js): the panel changes this device's '선' choices and '번쩍임' while
  // the deck is on screen, under the same storage keys as the deck's own menu and select; the deck follows at once
  const prefOffs = [
    onPref(key, (v) => {
      if (saving) return;
      const x = v && typeof v === "object" ? v : {};
      const was = st.off;
      st.off = new Set(Array.isArray(x.off) ? x.off.filter((g) => groups.includes(g)) : []);
      st.hide = new Set(Array.isArray(x.hide) ? x.hide.slice(-60) : []);
      // the 프리미엄 지표 parts travel with it (a value without them keeps this deck's)
      const wasParts = st.parts;
      if (Array.isArray(x.smc)) st.parts = new Set(x.smc.filter((id) => partIds.includes(id)));
      const partsMoved = [...st.parts].some((id) => !wasParts.has(id)) || [...wasParts].some((id) => !st.parts.has(id));
      // only the groups that changed are drawn again (a line hidden in another 여러 차트 cell: no 프리미엄 지표 recount)
      const moved = groups.filter((g) => was.has(g) !== st.off.has(g) || (g === "smc" && partsMoved));
      for (const g of moved) applyGroup(g, true);
      revis();
      if (moved.length) for (const fn of subs) fn(null, "pref");
    }),
    // 번쩍임 and 조명 changed in the 설정 panel (or in another deck's menu): this deck's menu words, the flash scheduler,
    // the blinking halves and the relay listener follow (flashSel is the span of the light menu, not a select)
    onPref(FLASH_KEY, (v) => {
      fmode = modeOf(v).id;
      if (fmode === "off") sched.cancel();
      paintLight();
    }),
    onPref(LIGHT_KEY, (v) => {
      lmode = lightModeOf(v).id;
      lightSync();
    }),
  ];
  if (ctx && ctx.track) ctx.track(() => { for (const off of prefOffs) off(); });

  // ---------------------------------------------------------------- data in
  function index() { st.idx = new Map(st.data.map((b, i) => [b.time, i])); }
  const dataSubs = [];
  function setData(data) {
    st.col = colours();
    st.data = (data || []).slice();
    index();
    series.setData(st.data);
    st.lastPx = null;
    st.zone = null;
    paintVol(); computeSmc(); if (tagEl) paintTag(false); schedule();
    for (const fn of dataSubs) fn("set");
  }
  /** A newer or the forming bar. real: the price came from a real new trade / poll (the tag pulses once if it moved). */
  function update(c, real = true) {
    const n = st.data.length, last = st.data[n - 1];
    if (last && c.time < last.time) return false;
    try { series.update(c); } catch (e) { return false; }
    const isNew = !last || c.time > last.time;
    if (isNew) { st.data.push(c); st.idx.set(c.time, st.data.length - 1); } else st.data[n - 1] = {...last, ...c};
    if (vol && shown("vol") && c.volume != null) { try { vol.update(volRow(c)); } catch (e) { /* older */ } }
    if (isNew) computeSmc();
    if (tagEl) paintTag(real);
    schedule();
    for (const fn of dataSubs) fn(isNew ? "new" : "bar");
    return true;
  }
  function paintTag(real) {
    const d = st.data[st.data.length - 1];
    if (!d) return;
    tagEl.firstChild.textContent = fmtPrice(d.close);
    tagEl.dataset.tone = d.close >= d.open ? "up" : "down";
    if (real && st.lastPx != null && d.close !== st.lastPx && !reduced() && visible()) {
      tagEl.removeAttribute("data-hit"); void tagEl.offsetWidth; tagEl.dataset.hit = d.close > st.lastPx ? "up" : "down";
    }
    st.lastPx = d.close;
  }
  if (tagEl) tagEl.addEventListener("animationend", () => tagEl.removeAttribute("data-hit"));
  function setMarkers(marks) {
    st.marks = marks || [];
    series.setMarkers(st.marks.map(({glow, ...m}) => m));
  }

  if (typeof ResizeObserver === "function") {
    const ro = new ResizeObserver(() => schedule());
    ro.observe(box);
    if (ctx && ctx.track) ctx.track(() => ro.disconnect());
  }
  chart.timeScale().subscribeVisibleLogicalRangeChange(() => schedule());
  if (ctx && ctx.track) ctx.track(() => { if (st.raf) cancelAnimationFrame(st.raf); });
  paintMenu();
  lightSync();

  /** Show the most recent ``n`` bars with room on the right for the line labels (like the reference terminal). */
  function showRecent(n = 220, right = 24) {
    const len = st.data.length, ts = chart.timeScale();
    if (len <= n) { ts.fitContent(); ts.scrollToPosition(Math.min(right, Math.round(len / 10)), false); return; }
    ts.setVisibleLogicalRange({from: len - n, to: len - 1 + right});
  }

  return {
    setData, update, setMarkers, setLines, showRecent, place: schedule, shown, data: () => st.data,
    /** A real event of the coin on screen: {tone: "up" | "down" | "accent", k: 0..1, why} (AI skin only). */
    flash(ev) { if (st.ai) sched.push(ev); },
    onToggle(fn) { subs.push(fn); },
    /** fn(how) after the candles were replaced ("set") or a bar changed / arrived ("bar" / "new"): the add-ons of
     *  screens/chart-plus.js (liquidation bubbles, our stop map, the lower panes) follow the candles through it. */
    onData(fn) { dataSubs.push(fn); },
    /** the '선' menu's box: chart-plus.js adds its own section (겹쳐 보기 · 아래 칸) to it */
    menuEl: menu,
    menuBtn: menuWrap, smcBtn, lightChip, lightMenu: flashSel, flashSel, viewBtn,
  };
}
