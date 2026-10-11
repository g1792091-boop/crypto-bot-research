// One number format everywhere: money "$1,234.56", R with 3 decimals "+0.123R", percents with 1 decimal "41.3%",
// the true minus sign "−", Korea time. Screens never format numbers themselves.

export const MINUS = "−";
const KST_MS = 9 * 3600 * 1000;

export const bad = (x) => x == null || typeof x === "boolean" || x === "" || !Number.isFinite(Number(x));

function grouped(abs, dec) {
  const [i, f] = abs.toFixed(dec).split(".");
  const g = i.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return f ? `${g}.${f}` : g;
}
/** 1234.5 -> "1,234.50"; sign: "+1,234.50" / "−1,234.50"; null -> "—". */
export function num(x, dec = 2, sign = false) {
  if (bad(x)) return "—";
  const v = Number(x), t = grouped(Math.abs(v), dec);
  const zero = !/[1-9]/.test(t);
  return (v < 0 && !zero ? MINUS : sign && v > 0 && !zero ? "+" : "") + t;
}
export const int = (x) => num(x, 0);
/** Money: "$1,234.56", with sign "+$12.30" / "−$12.30". */
export function money(x, sign = false) {
  if (bad(x)) return "—";
  const t = num(Math.abs(Number(x)), 2);
  const zero = !/[1-9]/.test(t);
  return (Number(x) < 0 && !zero ? MINUS : sign && Number(x) > 0 && !zero ? "+" : "") + "$" + t;
}
/** R in units of the stop distance: "+0.123R". */
export const r = (x, sign = true) => (bad(x) ? "—" : num(x, 3, sign) + "R");
/** A value already in percent: 12.34 -> "12.3%" (sign: "+12.3%"). */
export const pct = (x, sign = false, dec = 1) => (bad(x) ? "—" : num(x, dec, sign) + "%");
/** A ratio as percent: 0.413 -> "41.3%". */
export const ratio = (x, dec = 1) => (bad(x) ? "—" : num(Number(x) * 100, dec) + "%");
/** A price with decimals by size (BTC 112,301.5 · DOGE 0.24112). */
export function price(x) {
  if (bad(x)) return "—";
  const a = Math.abs(Number(x));
  return num(x, a < 1 ? 5 : a < 10 ? 4 : a < 1000 ? 2 : 1);
}
export const lev = (L) => (bad(L) ? "—" : `${num(L, 0)}배`);
/** "up" / "down" / "" for a signed value (a value that shows as zero gets no colour). */
export const tone = (x, shown) => (bad(x) || Number(x) === 0 || (shown != null && !/[1-9]/.test(String(shown))) ? "" : Number(x) > 0 ? "up" : "down");

// ---------------------------------------------------------------- Korea time, whatever the device says
function kp(ms) {
  const d = new Date(Number(ms) + KST_MS);
  return {y: d.getUTCFullYear(), mo: d.getUTCMonth() + 1, d: d.getUTCDate(), h: d.getUTCHours(), mi: d.getUTCMinutes(), s: d.getUTCSeconds(), wd: d.getUTCDay()};
}
const two = (n) => String(n).padStart(2, "0");
const WD = ["일", "월", "화", "수", "목", "금", "토"];
const okT = (ms) => !bad(ms) && Number(ms) > 0;
export const hm = (ms) => (okT(ms) ? ((p) => `${two(p.h)}:${two(p.mi)}`)(kp(ms)) : "—");
export const hms = (ms) => (okT(ms) ? ((p) => `${two(p.h)}:${two(p.mi)}:${two(p.s)}`)(kp(ms)) : "—");
export const kst = (ms) => (okT(ms) ? ((p) => `${two(p.mo)}/${two(p.d)} ${two(p.h)}:${two(p.mi)}`)(kp(ms)) : "—");
export const mmdd = (ms) => (okT(ms) ? ((p) => `${two(p.mo)}/${two(p.d)}`)(kp(ms)) : "—");
export const date = (ms) => (okT(ms) ? ((p) => `${p.y}년 ${p.mo}월 ${p.d}일 (${WD[p.wd]})`)(kp(ms)) : "—");
/** Seconds -> "3분" / "2시간 5분" / "4일 3시간". */
export function dur(sec) {
  if (bad(sec)) return "—";
  const t = Math.max(0, Math.round(Number(sec)));
  if (t < 60) return `${t}초`;
  if (t < 3600) return `${Math.floor(t / 60)}분`;
  if (t < 86400) { const hh = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60); return m ? `${hh}시간 ${m}분` : `${hh}시간`; }
  const dd = Math.floor(t / 86400), hh = Math.floor((t % 86400) / 3600);
  return hh ? `${dd}일 ${hh}시간` : `${dd}일`;
}
export const ago = (ms, now = Date.now()) => (okT(ms) ? (now >= ms ? `${dur((now - ms) / 1000)} 전` : `${dur((ms - now) / 1000)} 뒤`) : "—");
export const coin = (c) => String(c ?? "—").replace(/USD$/, "");
export const mb = (x) => (bad(x) ? "—" : Number(x) >= 1024 ? `${num(Number(x) / 1024, 1)} GB` : `${num(x, 0)} MB`);
