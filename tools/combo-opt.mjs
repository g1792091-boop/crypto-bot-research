// 🧪 보조지표 조합 커스텀 최적값 찾기 — 코인별 · 시간봉별(15분·30분·1시간) · 레버리지별, 과거 5년 바이낸스 선물 캔들.
//   쓰는 법: node tools/combo-opt.mjs [데이터 폴더=data/oos5y] [결과 파일=gh-coin/lib/combo-opt.js]   (빠른 시험: COINS=BTCUSDT)
//   데이터: START=2021-10-01 node tools/fetch-oos.mjs data/oos5y 15m,1h BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,DOGEUSDT,BNBUSDT  (30분봉은 15분봉을 묶어서 만듦)
//   계산 본체는 gh-coin/lib/comboopt.js — 앱의 '🔬 지표 최적화 백테스트' 창과 같은 함수(같은 데이터·구간이면 같은 결과).
//   구간: 2021-10-01 부터 1년씩 5구간(마지막 구간은 끝까지) — 앞 4년 학습, 마지막 1년 검증.
import fs from "fs";
import * as CB from "../gh-coin/lib/combos.js";
import * as OPTM from "../gh-coin/lib/comboopt.js";
const DIR = process.argv[2] || "data/oos5y", OUT = process.argv[3] || "gh-coin/lib/combo-opt.js";
const Y = 365.25 * 864e5, START = Date.UTC(2021, 9, 1);
const B = [START, START + Y, START + 2 * Y, START + 3 * Y, START + 4 * Y, Infinity];   // 5구간: 0~3 학습, 4 검증
const ONLY = process.env.COINS ? process.env.COINS.split(",") : null;
const out = {}, BEST = {}, summary = [], t0 = Date.now();

for (const [ko, sym] of CB.COINS) {
  if (ONLY && !ONLY.includes(sym)) continue;
  const c15 = JSON.parse(fs.readFileSync(`${DIR}/kl_${sym}_15m.json`, "utf8")), c60 = JSON.parse(fs.readFileSync(`${DIR}/kl_${sym}_1h.json`, "utf8"));
  let last = "";
  const r = await OPTM.optimizeCoin({ sym, ko, data: { "15": c15, "30": CB.agg30(c15), "60": c60 }, B, span: Y,
    tick: (f, msg) => { const m = msg.split(" · ")[0]; if (m && m !== last) { last = m; process.stdout.write(`${ko} ${m} (${Math.round((Date.now() - t0) / 1000)}s)\n`); } } });
  out[sym] = r.out; BEST[sym] = r.best; summary.push(...r.summary);
}
const meta = { made: new Date().toISOString(), from: new Date(START).toISOString().slice(0, 10), folds: B.slice(0, 5).map(t => new Date(t).toISOString().slice(0, 10)), ref: OPTM.REF, exits: CB.EXIT_GRID, span: Y,
  note: "레버리지마다 따로: 지표 값+노이즈 거르기(ADX·EMA200·1봉 확인)를 그 레버리지의 손절 상한으로 고르고 → 손절·익절·청산. 앞 4년 학습(연도별 꾸준함 + 이웃 평균) → 마지막 1년 검증. 후보 9개를 앱이 라운드마다 다시 순위. BEST = 코인·레버리지별 대표(학습 점수 1위)." };
fs.writeFileSync(OUT, `// 자동 생성: node tools/combo-opt.mjs (${meta.made}) — 손으로 고치지 마세요\nexport const META = ${JSON.stringify(meta)};\nexport const OPT = ${JSON.stringify(out)};\nexport const BEST = ${JSON.stringify(BEST)};\n`);
fs.writeFileSync("data/combo-opt-summary.json", JSON.stringify(summary, null, 0).replace(/\},\{/g, "},\n{"));
const pass = summary.filter(s => s.pass), np = summary.filter(s => s.pass && !s.luck);
console.log(`\n칸 ${summary.length}개 · 통과 ${pass.length} · 통과+운 범위 밖 ${np.length} · ${Math.round((Date.now() - t0) / 1000)}초`);
console.log("\n⭐ 코인별 대표(30·40·50배, 학습 점수 1위 → 검증 1년):");
for (const [sym, m] of Object.entries(BEST)) for (const [lev, b] of Object.entries(m)) { const c = out[sym][b.tf][b.c].levs[lev][0];
  console.log(`${sym.replace("USDT", "")} ${lev}x | ${b.c} ${b.tf}분 | ${CB.paramText(b.c, c.p)} | ${CB.exitText(c.x)} | 학습 ${c.tr.mean}R(${c.tr.n}) 검증 ${c.ho.mean}R(${c.ho.n}) 1~5년 ${c.lb.map(l => l[1]).join("/")} ${b.pass ? "통과" : "실패"}${b.luck ? "·운범위" : ""}`); }
