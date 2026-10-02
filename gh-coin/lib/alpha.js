// 알파 팩터 — vnpy(MIT) alpha 모듈의 Alpha158 데이터셋에서 대표 팩터를 골라 다시 만든 것.
// 봉 모양 9종 중 KMID·KLEN·KUP·KLOW, 가격 비율, 롤링 계열(ROC·MA·STD·BETA·RSV·CORR) × 창 {5, 20}
// 코인 여러 개를 '같은 시점'에서 비교(횡단면): 견고한 z점수(중앙값/MAD) → 순위. 라벨은 Alpha158 과 같은 C[t+3]/C[t+1] − 1 (검증용).
const med = a => { const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
export function factors(cs){
  const n = cs.length, i = n - 1, b = cs[i], C = cs.map(x => x.c), V = cs.map(x => x.v || 0), f = {};
  if (n < 30) return f;
  f.KMID = (b.c - b.o) / b.o; f.KLEN = (b.h - b.l) / b.o; f.KUP = (b.h - Math.max(b.o, b.c)) / b.o; f.KLOW = (Math.min(b.o, b.c) - b.l) / b.o;
  for (const w of [5, 20]){
    const s = C.slice(-w), m = s.reduce((x, y) => x + y, 0) / w, sd = Math.sqrt(s.reduce((x, y) => x + (y - m) ** 2, 0) / w);
    f["ROC" + w] = C[i - w] / C[i]; f["MA" + w] = m / C[i]; f["STD" + w] = sd / C[i];
    let sx = 0, sy = 0, sxx = 0, sxy = 0; s.forEach((y, k) => { sx += k; sy += y; sxx += k * k; sxy += k * y; }); f["BETA" + w] = (w * sxy - sx * sy) / (w * sxx - sx * sx) / C[i];
    const hh = Math.max(...cs.slice(-w).map(x => x.h)), ll = Math.min(...cs.slice(-w).map(x => x.l)); f["RSV" + w] = (C[i] - ll) / (hh - ll + 1e-12);
    const lv = V.slice(-w).map(v => Math.log(v + 1)), ml = lv.reduce((x, y) => x + y, 0) / w; let cv = 0, vx = 0, vy = 0; s.forEach((y, k) => { cv += (y - m) * (lv[k] - ml); vx += (y - m) ** 2; vy += (lv[k] - ml) ** 2; }); f["CORR" + w] = vx && vy ? cv / Math.sqrt(vx * vy) : 0;
  }
  return f;
}
// 횡단면 견고 z점수: (x − 중앙값) / (1.4826 × MAD), ±3 에서 자름
export function crossRank(byCoin){
  const names = [...new Set(Object.values(byCoin).flatMap(f => Object.keys(f)))], out = {};
  for (const k of Object.keys(byCoin)) out[k] = {};
  for (const nm of names){
    const vals = Object.entries(byCoin).map(([k, f]) => [k, f[nm]]).filter(([, v]) => Number.isFinite(v)); if (vals.length < 3) continue;
    const m = med(vals.map(x => x[1])), mad = med(vals.map(x => Math.abs(x[1] - m))) * 1.4826 || 1e-12;
    for (const [k, v] of vals) out[k][nm] = Math.max(-3, Math.min(3, (v - m) / mad));
  }
  return out;
}
// 간단 합성 점수: 모멘텀(ROC 역수 → 상승) + 추세 기울기 + RSV − 변동성 (Alpha158 계열을 사람이 읽을 수 있게 묶음)
export function composite(z){ const g = k => z[k] ?? 0; return (-g("ROC5") - g("ROC20")) * 0.25 + (g("BETA5") + g("BETA20")) * 0.25 + (g("RSV5") + g("RSV20")) * 0.15 - (g("STD20")) * 0.2 + g("KMID") * 0.1; }
