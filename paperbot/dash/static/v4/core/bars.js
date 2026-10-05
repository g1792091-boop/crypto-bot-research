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
/** US stocks 09:30-16:00 New York on weekdays: {open: bool, text} in Korean. */
export function usMarket(now) {
  const ny = new Intl.DateTimeFormat("en-US", {timeZone: "America/New_York", hour12: false, weekday: "short", hour: "2-digit", minute: "2-digit"})
    .formatToParts(new Date(now)).reduce((o, p) => (o[p.type] = p.value, o), {});
  const mins = (+ny.hour % 24) * 60 + +ny.minute, wk = !["Sat", "Sun"].includes(ny.weekday);
  const hm = (m) => `${Math.floor(m / 60)}시간 ${m % 60}분`;
  if (wk && mins < 570) return {open: false, text: `${hm(570 - mins)} 후 개장`};
  if (wk && mins < 960) return {open: true, text: `열려 있음 · 마감까지 ${hm(960 - mins)}`};
  return {open: false, text: ny.weekday === "Fri" || !wk ? "닫힘 · 다음 개장 월요일 밤 (한국)" : "닫힘 · 다음 개장 오늘 밤 (한국)"};
}
