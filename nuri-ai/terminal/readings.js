// 차트 터미널 보조지표 → 봉마다 방향 읽기(+1 롱 쪽 / −1 숏 쪽 / 0 중립)
// 사용자가 차트에 띄운 지표(nuri:term:state.inds)를 그대로 계산해, '지금 내 지표들이 어느 쪽을 가리키는지'와
// '과거에 같은 상태였던 봉'을 찾을 수 있게 한다. ⚡ 시장가 분석(gh-coin/liveentry.js)이 쓴다.
import { DEFS, labelOf, paneOf } from "./registry.js";

export const TERM_KEY = "nuri:term:state";
export function userInds() { try { const s = JSON.parse(localStorage.getItem(TERM_KEY) || "null"); return Array.isArray(s?.inds) ? s.inds.filter(x => x && DEFS[x.key]) : []; } catch (e) { return []; } }
// {t,o,h,l,c,v}(ms) → 터미널 형식 {time(초), open, high, low, close, volume}
export const toTerm = cs => cs.map(b => ({ time: Math.floor(b.t / 1000), open: b.o, high: b.h, low: b.l, close: b.c, volume: b.v }));

const sg = x => x > 0 ? 1 : x < 0 ? -1 : 0;
const MID = { rsi: 50, mfi: 50, stoch: 50, stochrsi: 50, willr: -50, cci: 0, roc: 0, cmf: 0 };
const NONDIR = new Set(["atr", "volume_sma", "obv_none"]);

// 한 지표의 봉별 방향 배열
function dirSeries(spec, res, c) {
  const n = c.length, out = new Int8Array(n), d = DEFS[spec.key], plots = (res?.plots || []).filter(p => Array.isArray(p.data) && p.data.length === n);
  const close = i => c[i].close, v = (p, i) => (p && p.data[i] != null && Number.isFinite(+p.data[i])) ? +p.data[i] : null;
  const by = name => plots.find(p => p.name === name);
  const sigPl = plots.find(p => p.type === "signals");
  const type = d?.type, src = d?.src;
  if (src === "q" && NONDIR.has(type)) return out;
  for (let i = 0; i < n; i++) {
    let r = 0;
    if (src === "q") {
      if (by("상승") || by("하락")) r = v(by("상승"), i) != null ? 1 : v(by("하락"), i) != null ? -1 : 0;           // 슈퍼트렌드·UT봇
      else if (type === "psar") { const s = v(plots[0], i); r = s == null ? 0 : sg(close(i) - s); }
      else if (type === "ichimoku") { const a = v(by("span_a"), i), b = v(by("span_b"), i); r = a == null || b == null ? 0 : close(i) > Math.max(a, b) ? 1 : close(i) < Math.min(a, b) ? -1 : 0; }
      else if (type === "macd") r = sg(v(by("hist"), i) ?? 0);
      else if (type === "stoch" || type === "stochrsi") { const k = v(by("k"), i), dd = v(by("d"), i); r = k == null || dd == null ? 0 : sg(k - dd); }
      else if (type === "adx") { const p = v(by("plus_di"), i), m = v(by("minus_di"), i); r = p == null || m == null ? 0 : sg(p - m); }
      else if (type === "aroon") { const u = v(by("up"), i), dn = v(by("down"), i); r = u == null || dn == null ? 0 : sg(u - dn); }
      else if (type === "obv") { const a = v(plots[0], i), b = i >= 5 ? v(plots[0], i - 5) : null; r = a == null || b == null ? 0 : sg(a - b); }
      else if (MID[type] != null) { const x = v(plots[0], i); r = x == null ? 0 : sg(x - MID[type]); }
      else if (paneOf(spec) === "main") { const mid = by("middle") || plots.find(p => p.type === "line"); const x = v(mid, i); r = x == null ? 0 : sg(close(i) - x); }
      else { const x = v(plots[0], i); r = x == null ? 0 : sg(x); }
    } else {
      if (sigPl) { r = 0; for (let j = i; j >= Math.max(0, i - 12); j--) { const s = sigPl.data[j]; if (s && s.dir) { r = sg(s.dir); break; } } }   // 최근 12봉 안 마지막 신호 유지
      else {
        const lines = plots.filter(p => p.type === "line"), hist = plots.find(p => p.type === "hist");
        if (paneOf(spec) === "main" && lines[0]) { const x = v(lines[0], i); r = x == null ? 0 : sg(close(i) - x); }
        else if (hist && src !== "c") r = sg(v(hist, i) ?? 0);
        else if (lines.length >= 2) { const a = v(lines[0], i), b = v(lines[1], i); r = a == null || b == null ? 0 : sg(a - b); }
        else if (lines[0]) { const a = v(lines[0], i), b = i >= 3 ? v(lines[0], i - 3) : null; r = a == null || b == null ? 0 : sg(a - b); }   // 단일 선: 기울기
      }
    }
    out[i] = r;
  }
  return out;
}

// 캔들(터미널 형식) + 지표 목록 → {items:[{name, dir, series}], vecAt(i)}
export function readings(c, specs = userInds()) {
  const items = [];
  for (const s of specs) {
    const d = DEFS[s.key]; if (!d) continue;
    let res; try { res = d.compute(c, { ...d.params, ...(s.params || {}) }, { color: s.color, id: s.id }); } catch (e) { continue; }
    if (res && typeof res.then === "function") continue;
    const series = dirSeries(s, res, c); if (!series.some(x => x !== 0)) continue;   // 방향이 없는 지표는 제외
    { let up = 0, dn = 0; for (const x of series) { if (x > 0) up++; else if (x < 0) dn++; } if (Math.max(up, dn) / Math.max(1, up + dn) > 0.95) continue; }   // 늘 같은 방향(거래량 막대 등) = 정보 없음
    items.push({ name: labelOf(s) + (s.params?.length ? ` ${s.params.length}` : ""), dir: series[c.length - 1], series });
  }
  return { items, n: c.length, vecAt: i => items.map(x => x.series[i]) };
}
// 두 시점의 지표 상태가 얼마나 같은지 (0이 아닌 지표 기준 일치 비율)
export function agree(R, i, j) { let k = 0, m = 0; for (const x of R.items) { const a = x.series[i], b = x.series[j]; if (!a) continue; m++; if (a === b) k++; } return m ? k / m : 0; }
