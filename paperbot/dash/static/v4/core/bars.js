// Bar clocks and market sessions (from the old app.js / panels.js; same definitions as paperbot/sessions.py).
// Binance bars are aligned to UTC: up to 3 days the epoch modulo works, a week starts Monday 00:00 UTC, a month on
// the 1st 00:00 UTC. Use serverNow() (core/api.js) as `now` so a phone whose clock is off still counts right.

export const TF_MS = {"1m": 6e4, "3m": 18e4, "5m": 3e5, "15m": 9e5, "30m": 18e5, "1h": 36e5, "2h": 72e5, "4h": 144e5, "6h": 216e5,
  "8h": 288e5, "12h": 432e5, "1d": 864e5, "3d": 2592e5};
export const ALL_TFS = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"];
export const SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT", "XRPUSDT"];   // XRP: record only
export const TRADE_SYMS = SYMS.slice(0, 6);

/** End of the bar that holds `now` (ms), or null. */
export function barEnd(tf, now) {
  if (TF_MS[tf]) return now - (now % TF_MS[tf]) + TF_MS[tf];
  if (tf === "1w") { const w = 6048e5, mon = 3456e5; return now - ((now - mon) % w) + w; }
  if (tf === "1M") { const d = new Date(now); return Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1); }
  return null;
}
/** "12:34" / "1:02:03" / "2일 3:04:05" until the bar closes. */
export function closeIn(tf, now) {
  const end = barEnd(tf, now);
  if (end == null) return "—";
  const left = Math.max(0, Math.ceil((end - now) / 1000));
  const dd = Math.floor(left / 86400), hh = Math.floor((left % 86400) / 3600), mm = Math.floor((left % 3600) / 60), ss = left % 60;
  const two = (x) => String(x).padStart(2, "0");
  return dd ? `${dd}일 ${hh}:${two(mm)}:${two(ss)}` : hh ? `${hh}:${two(mm)}:${two(ss)}` : `${two(mm)}:${two(ss)}`;
}

// sessions.py, in Korea time: asia 09-16, europe 16-22, us 22-05, dawn 05-09; weekend Sat/Sun
export const SESSION_KO = {asia: "아시아장", europe: "유럽장", us: "미국장", dawn: "새벽"};
export function session(now) {
  const k = new Date(now + 9 * 3.6e6), hh = k.getUTCHours(), wd = k.getUTCDay();
  const id = hh >= 9 && hh < 16 ? "asia" : hh >= 16 && hh < 22 ? "europe" : hh >= 5 && hh < 9 ? "dawn" : "us";
  return {id, ko: SESSION_KO[id], weekend: wd === 0 || wd === 6};
}
// NYSE full-day closures and 13:00 early closes for 2026-2027 (NYSE's published holiday calendar; the same lists as
// NYSE_HOLIDAYS / NYSE_EARLY_CLOSE in paperbot/sessions.py: add the next year's dates there and here each December).
// 2027-12-31 is a normal day: New Year's Day 2028 falls on a Saturday and NYSE does not move it to the Friday.
export const NYSE_HOLIDAYS = {
  "2026-01-01": "새해", "2026-01-19": "마틴 루서 킹 데이", "2026-02-16": "대통령의 날", "2026-04-03": "성금요일",
  "2026-05-25": "현충일", "2026-06-19": "준틴스", "2026-07-03": "독립기념일 대체", "2026-09-07": "노동절",
  "2026-11-26": "추수감사절", "2026-12-25": "성탄절",
  "2027-01-01": "새해", "2027-01-18": "마틴 루서 킹 데이", "2027-02-15": "대통령의 날", "2027-03-26": "성금요일",
  "2027-05-31": "현충일", "2027-06-18": "준틴스 대체", "2027-07-05": "독립기념일 대체", "2027-09-06": "노동절",
  "2027-11-25": "추수감사절", "2027-12-24": "성탄절 대체"};
/** New York minutes of the 13:00 early closes. */
export const NYSE_EARLY = {"2026-11-27": 780, "2026-12-24": 780, "2027-11-26": 780};
const isoAdd = (iso, n) => new Date(Date.parse(iso + "T12:00:00Z") + n * 864e5).toISOString().slice(0, 10);
const weekdayIso = (iso) => { const d = new Date(iso + "T12:00:00Z").getUTCDay(); return d !== 0 && d !== 6; };
/** Is the New York date `iso` ("YYYY-MM-DD") a trading day (a weekday that is not a NYSE holiday)? */
export function nyseOpenDay(iso) { return weekdayIso(iso) && !NYSE_HOLIDAYS[iso]; }
/** US stocks 09:30-16:00 New York on trading days (13:00 on early-close days): {open, text, holiday} in Korean. */
export function usMarket(now) {
  const ny = new Intl.DateTimeFormat("en-US", {timeZone: "America/New_York", hour12: false, weekday: "short", hour: "2-digit",
    minute: "2-digit", year: "numeric", month: "2-digit", day: "2-digit"})
    .formatToParts(new Date(now)).reduce((o, p) => (o[p.type] = p.value, o), {});
  const mins = (+ny.hour % 24) * 60 + +ny.minute, wk = !["Sat", "Sun"].includes(ny.weekday);
  const day = `${ny.year}-${ny.month}-${ny.day}`, hol = NYSE_HOLIDAYS[day] || null, close = NYSE_EARLY[day] || 960;
  const hm = (m) => `${Math.floor(m / 60)}시간 ${m % 60}분`;
  if (wk && !hol && mins < 570) return {open: false, holiday: null, text: `${hm(570 - mins)} 후 개장`};
  if (wk && !hol && mins < close) return {open: true, holiday: null,
    text: `열려 있음 · 마감까지 ${hm(close - mins)}${close < 960 ? " (단축 마감)" : ""}`};
  let nx = isoAdd(day, 1);
  for (let i = 0; i < 10 && !nyseOpenDay(nx); i++) nx = isoAdd(nx, 1);
  // 09:30 New York is the same calendar day's night in Korea (22:30 / 23:30)
  let plain = isoAdd(day, 1);
  while (!weekdayIso(plain)) plain = isoAdd(plain, 1);
  if (!hol && nx === plain)                   // no holiday in the way: the old wording
    return {open: false, holiday: null, text: ny.weekday === "Fri" || !wk ? "닫힘 · 다음 개장 월요일 밤 (한국)" : "닫힘 · 다음 개장 오늘 밤 (한국)"};
  const [, m, d] = nx.split("-");
  return {open: false, holiday: hol, text: `${hol ? `휴장 (${hol})` : "닫힘"} · 다음 개장 ${+m}월 ${+d}일 밤 (한국)`};
}
