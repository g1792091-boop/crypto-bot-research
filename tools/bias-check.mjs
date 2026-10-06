// 🔎 미래 데이터 누설(look-ahead) · 앞부분 길이 의존(recursive) 검사 — 개념: freqtrade lookahead/recursive analysis (코드 복사 없음)
//   왜: 백테스트가 좋아 보이는데 실전이 안 되는 가장 흔한 원인이 '신호 계산에 미래 봉이 섞인 것'. 뉴럴 데스크 매매법(strategies.js LIB)을 전부 검사한다.
//   ① look-ahead: 전체 데이터로 계산한 i 봉의 신호 == i 봉까지만 자른 데이터로 계산한 신호 여야 한다(다르면 미래 봉을 봄).
//   ② recursive: 앞부분을 199/499/999 봉만 남겨도 마지막 봉의 지표·신호가 같아야 한다(다르면 지표가 시작 길이에 의존 — EMA 워밍업 등).
// 쓰는 법: node tools/bias-check.mjs <캔들 JSON 폴더> [코인=BTCUSDT] [봉=1h]
//   캔들 JSON = [{t,o,h,l,c,v}, ...] 파일 이름 kl_<코인>_<봉>.json
globalThis.window = globalThis; globalThis.localStorage = { getItem() { return null; }, setItem() {} };
import fs from "fs";
const root = new URL("../", import.meta.url).href;
const Q = await import(root + "nuri-ai/quant.js"), E = await import(root + "gh-coin/strategies.js");
const dir = process.argv[2], sym = process.argv[3] || "BTCUSDT", tf = process.argv[4] || "1h";
const cs = JSON.parse(fs.readFileSync(`${dir}/kl_${sym}_${tf}.json`, "utf8")).slice(-3000);
const sigAt = (rule, I, cs2, i) => { rule.prep?.(cs2); const s = rule.sig(I, i); return s ? `${s.side}|${(+s.sl).toPrecision(8)}` : "-"; };
const KEYS = ["ema9", "ema20", "ema50", "ema200", "rsi", "atr", "adx", "macd", "stTrend", "bbWPct", "swH", "swL", "psar"];
const full = E.prepare(Q, cs), rows = [];
// ① look-ahead: 무작위 40개 시점에서 잘라 비교
const pts = []; for (let k = 0; k < 40; k++) pts.push(600 + Math.floor(Math.random() * (cs.length - 700)));
const cut = Object.fromEntries(pts.map(p => [p, E.prepare(Q, cs.slice(0, p + 1))]));
for (const r of E.LIB) { let diff = 0, sigs = 0;
  for (const p of pts) { const a = sigAt(r, full, cs, p), b = sigAt(r, cut[p], cs.slice(0, p + 1), p); if (a !== "-" || b !== "-") sigs++; if (a !== b) diff++; }
  rows.push({ 매매법: r.key, 시점: pts.length, 신호: sigs, 미래누설: diff }); }
const ind = []; for (const k of KEYS) { let diff = 0; for (const p of pts) { const a = JSON.stringify(full[k]?.[p]), b = JSON.stringify(cut[p][k]?.[p]); if (a !== b) diff++; } ind.push({ 지표: k, 미래누설: diff }); }
// ② recursive: 마지막 봉 기준 시작 길이 199/499/999/1999
const rec = []; const last = cs.length - 1;
for (const n of [199, 499, 999, 1999]) { const sub = cs.slice(-n - 1), I = E.prepare(Q, sub), j = sub.length - 1; const o = { 시작봉: n };
  for (const k of ["ema50", "ema200", "rsi", "atr", "adx"]) { const a = full[k]?.[last], b = I[k]?.[j]; o[k] = a == null || b == null ? "—" : `${((b / a - 1) * 100).toFixed(3)}%`; } rec.push(o); }
console.log(`[${sym} ${tf}] 매매법 ${E.LIB.length}개 · 무작위 시점 ${pts.length}개`);
console.table(rows.filter(r => r.미래누설 > 0).length ? rows.filter(r => r.미래누설 > 0) : [{ 결과: "미래 데이터 누설 없음 (전 매매법)" }]);
console.table(ind.filter(r => r.미래누설 > 0).length ? ind.filter(r => r.미래누설 > 0) : [{ 결과: "지표 미래 누설 없음" }]);
console.log("앞부분 길이에 따른 마지막 봉 지표 차이(전체 3000봉 대비):"); console.table(rec);
