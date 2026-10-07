// 표본외 검증용 캔들 내려받기(바이낸스 선물 · 2023-01 부터) — tools/oos-check.mjs 의 입력.
//   쓰는 법: node tools/fetch-oos.mjs <폴더> [봉들=1h,4h,15m] [코인들=기본 10개]
//   바이낸스 무게 한도(분당 2400) 때문에 요청 사이 0.45초 쉬고, 429/418 이면 70초 기다린다(2026-10-06 빠르게 받다가 막힌 적 있음).
import fs from "fs";
const OUT = process.argv[2] || "data/oos", IVS = (process.argv[3] || "1h,4h,15m").split(","), SY = (process.argv[4] || "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,DOGEUSDT,BNBUSDT,ADAUSDT,AVAXUSDT,LINKUSDT,LTCUSDT").split(",");
const MS = { "5m": 300e3, "15m": 900e3, "1h": 3600e3, "4h": 14400e3, "1d": 864e5 }, START = Date.UTC(2023, 0, 1), END = Date.now();
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function get(sym, iv, from) { const out = []; let t = from;
  while (t < END) { let r = null;
    for (let k = 0; k < 4 && !r; k++) { try { const res = await fetch(`https://fapi.binance.com/fapi/v1/klines?symbol=${sym}&interval=${iv}&limit=1500&startTime=${t}`); if (res.status === 429 || res.status === 418) { console.log("한도 — 70초 대기"); await sleep(70000); continue; } r = await res.json(); } catch (e) { await sleep(1500); } }
    if (!Array.isArray(r) || !r.length) break; out.push(...r.map(k => ({ t: k[0], o: +k[1], h: +k[2], l: +k[3], c: +k[4], v: +k[5] }))); t = r.at(-1)[0] + MS[iv]; await sleep(450); if (r.length < 1500) break; }
  return out; }
fs.mkdirSync(OUT, { recursive: true });
for (const s of SY) for (const iv of IVS) { const f = `${OUT}/kl_${s}_${iv}.json`; if (fs.existsSync(f) && fs.statSync(f).size > 1000) continue;
  const cs = await get(s, iv, iv === "5m" ? Date.UTC(2025, 5, 1) : START); fs.writeFileSync(f, JSON.stringify(cs)); console.log(s, iv, cs.length); }
console.log("done");
