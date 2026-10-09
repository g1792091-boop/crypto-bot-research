// 🧪 보조지표 조합 커스텀 최적값 찾기 — 코인별 · 시간봉별(15분·30분·1시간) · 레버리지별, 과거 5년 바이낸스 선물 캔들.
//   쓰는 법: node tools/combo-opt.mjs [데이터 폴더=data/oos5y] [결과 파일=gh-coin/lib/combo-opt.js]
//   데이터: START=2021-10-01 node tools/fetch-oos.mjs data/oos5y 15m,1h BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,DOGEUSDT,BNBUSDT  (30분봉은 15분봉을 묶어서 만듦)
//
// 고르는 법(노이즈 줄이기):
//   ① 5년을 1년씩 5구간으로 나눔. 앞 4년(학습)만 보고 고르고, 마지막 1년(검증)은 고를 때 안 봄.
//   ② 점수 = 연도별 평균 R 의 평균 − 0.5×연도 간 편차 → 한 해만 좋은 값보다 매년 고르게 좋은 값.
//   ③ 이웃 평균(그리드에서 한 칸씩 옆 값까지 평균) → 한 점만 튀는 우연한 값 대신 '평평한 고원'.
//   ④ 지표 값(1단계) → 상위 3개마다 손절·익절·청산 방식(2단계, 레버리지마다) → 후보 9개를 앱에 넘김(라운드마다 최근 데이터로 다시 순위).
//   ⑤ 통과 = 학습 점수 > 0 그리고 검증 1년 평균 R > 0(10건 이상). 운 보정: 시험한 경우의 수(K)만큼 '최고값이 운으로도 나오는 폭'을 넘었는지 따로 표시.
import fs from "fs";
import * as CB from "../gh-coin/lib/combos.js";
import { expMaxZ } from "../gh-coin/lib/robust.js";
const DIR = process.argv[2] || "data/oos5y", OUT = process.argv[3] || "gh-coin/lib/combo-opt.js";
const Y = 365.25 * 864e5, START = Date.UTC(2021, 9, 1);
const B = [START, START + Y, START + 2 * Y, START + 3 * Y, START + 4 * Y, Infinity];   // 5구간: 0~3 학습, 4 검증
const REF = { k: 1.5, rr: 1.5, ex: 1 };   // 1단계 기준 청산(지표 값만 비교)
const r3 = v => Math.round(v * 1000) / 1000;
const EXITS = CB.gridList(CB.EXIT_GRID);
const out = {}, summary = [], t0 = Date.now();

function evalSet(T, end) {
  const f = CB.foldStats(T, B), tr = CB.robust(f.slice(0, 4)), all = CB.robust(f, 40), ho = f[4];
  // lb = 최근 1·2·3·4·5년 [건수, 평균R, 승률%] · yr = 연도 구간별 [건수, 평균R] (파일 크기 때문에 배열로)
  const lb = [1, 2, 3, 4, 5].map(y => { const s = CB.stat(T.filter(t => t.t >= end - y * Y)); return [s.n, s.mean, s.wr]; });
  const trT = T.filter(t => t.t < B[4]), st = CB.stat(trT);
  return { tr: { score: r3(tr.score), n: tr.n, mean: r3(tr.mean), sd: st.sd }, ho: { n: ho.n, mean: r3(ho.mean), wr: Math.round(ho.wr * 100) }, all: { score: r3(all.score), n: all.n, mean: r3(all.mean) },
    yr: f.map(x => [x.n, r3(x.mean)]), lb };
}

const ONLY = process.env.COINS ? process.env.COINS.split(",") : null;   // 빠른 시험: COINS=BTCUSDT
const BEST = {}, BEST_LEVS = [30, 40, 50];
for (const [ko, sym] of CB.COINS) {
  if (ONLY && !ONLY.includes(sym)) continue;
  const c15 = JSON.parse(fs.readFileSync(`${DIR}/kl_${sym}_15m.json`, "utf8")), c60 = JSON.parse(fs.readFileSync(`${DIR}/kl_${sym}_1h.json`, "utf8"));
  const DATA = { "15": c15, "30": CB.agg30(c15), "60": c60 };
  out[sym] = {};
  for (const tf of CB.TFS) {
    const D = CB.cols(DATA[tf]), end = D.t[D.n - 1];
    out[sym][tf] = {};
    for (const C of CB.COMBOS) {
      const G = CB.gridList(C.grid), K = G.length * EXITS.length, sigs = new Map(), levs = {};   // K = 이 칸에서 시험한 경우의 수(운 보정용)
      for (const p of G) sigs.set(CB.pkey(p), CB.comboDir(D, C.key, p));
      for (const lev of CB.LEVS[tf]) {
        // ① 지표 값 + 노이즈 거르기 — 이 레버리지의 손절 상한(0.4/L) 그대로, 기준 청산으로
        const sc = new Map();
        for (const p of G) { const T = CB.simulate(D, sigs.get(CB.pkey(p)), REF, lev), f = CB.foldStats(T, B); sc.set(CB.pkey(p), { p, ...CB.robust(f.slice(0, 4)) }); }
        const pl = CB.plateau(C.grid, sc), ind = [...pl.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3).map(([k, v]) => ({ p: sc.get(k).p, plat: r3(v) }));
        // ② 상위 3개마다 손절(ATR×k)·손익비·청산 방식
        const cands = [];
        for (const it of ind) {
          const sig = sigs.get(CB.pkey(it.p)), es = new Map(), res = new Map();
          for (const x of EXITS) { const T = CB.simulate(D, sig, x, lev), f = CB.foldStats(T, B); es.set(CB.pkey(x), { p: x, ...CB.robust(f.slice(0, 4)) }); res.set(CB.pkey(x), T); }
          const epl = CB.plateau(CB.EXIT_GRID, es);
          for (const [k, v] of [...epl.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3)) {
            const ev = evalSet(res.get(k), end), luckBar = ev.tr.n > 1 ? ev.tr.sd / Math.sqrt(ev.tr.n) * expMaxZ(K) : 9;
            cands.push({ p: it.p, x: es.get(k).p, plat: r3((v + it.plat) / 2), ...ev, pass: ev.tr.score > 0 && ev.ho.n >= 10 && ev.ho.mean > 0 ? 1 : 0, luck: ev.tr.mean <= luckBar ? 1 : 0 });
          }
        }
        cands.sort((a, b) => b.plat - a.plat);
        levs[lev] = cands;
        const c = cands[0];
        summary.push({ coin: ko, sym, tf, combo: C.key, lev, plat: c.plat, p: CB.paramText(C.key, c.p), x: CB.exitText(c.x), tr: c.tr.mean, trN: c.tr.n, ho: c.ho.mean, hoN: c.ho.n, lb: c.lb.map((l, i) => `${i + 1}y ${l[1]}(${l[0]})`).join(" "), pass: !!c.pass, luck: !!c.luck });
      }
      out[sym][tf][C.key] = { levs, K };
      process.stdout.write(`${ko} ${tf} ${C.key} ✓ (${Math.round((Date.now() - t0) / 1000)}s)\n`);
    }
  }
  // ⭐ 코인별 대표: 레버리지마다 (조합 4 × 시간봉 3) 중 '앞 4년 학습 점수' 1위 — 고를 때 검증 1년은 안 봄. 운 보정은 12칸 × K 로 더 엄하게.
  BEST[sym] = {};
  for (const lev of BEST_LEVS) {
    const rows = summary.filter(r => r.sym === sym && r.lev === lev).sort((a, b) => b.plat - a.plat), r = rows[0]; if (!r) continue;
    const c = out[sym][r.tf][r.combo].levs[lev][0], K = out[sym][r.tf][r.combo].K * rows.length, bar = c.tr.n > 1 ? c.tr.sd / Math.sqrt(c.tr.n) * expMaxZ(K) : 9;
    BEST[sym][lev] = { c: r.combo, tf: r.tf, plat: r.plat, pass: c.pass, luck: c.tr.mean <= bar ? 1 : 0, of: rows.length };
  }
}
const meta = { made: new Date().toISOString(), from: new Date(START).toISOString().slice(0, 10), folds: B.slice(0, 5).map(t => new Date(t).toISOString().slice(0, 10)), ref: REF, exits: CB.EXIT_GRID,
  note: "레버리지마다 따로: 지표 값+노이즈 거르기(ADX·EMA200·1봉 확인)를 그 레버리지의 손절 상한으로 고르고 → 손절·익절·청산. 앞 4년 학습(연도별 꾸준함 + 이웃 평균) → 마지막 1년 검증. 후보 9개를 앱이 라운드마다 다시 순위. BEST = 코인·레버리지별 대표(학습 점수 1위)." };
fs.writeFileSync(OUT, `// 자동 생성: node tools/combo-opt.mjs (${meta.made}) — 손으로 고치지 마세요\nexport const META = ${JSON.stringify(meta)};\nexport const OPT = ${JSON.stringify(out)};\nexport const BEST = ${JSON.stringify(BEST)};\n`);
fs.writeFileSync("data/combo-opt-summary.json", JSON.stringify(summary, null, 0).replace(/\},\{/g, "},\n{"));
const pass = summary.filter(s => s.pass), np = summary.filter(s => s.pass && !s.luck);
console.log(`\n칸 ${summary.length}개 · 통과 ${pass.length} · 통과+운 범위 밖 ${np.length} · ${Math.round((Date.now() - t0) / 1000)}초`);
console.log("\n⭐ 코인별 대표(30·40·50배, 학습 점수 1위 → 검증 1년):");
for (const [sym, m] of Object.entries(BEST)) for (const [lev, b] of Object.entries(m)) { const c = out[sym][b.tf][b.c].levs[lev][0];
  console.log(`${sym.replace("USDT", "")} ${lev}x | ${b.c} ${b.tf}분 | ${CB.paramText(b.c, c.p)} | ${CB.exitText(c.x)} | 학습 ${c.tr.mean}R(${c.tr.n}) 검증 ${c.ho.mean}R(${c.ho.n}) 1~5년 ${c.lb.map(l => l[1]).join("/")} ${b.pass ? "통과" : "실패"}${b.luck ? "·운범위" : ""}`); }
for (const s of summary.filter(s => s.pass).sort((a, b) => b.ho - a.ho).slice(0, 30)) console.log(`${s.coin} ${s.tf} ${s.combo} ${s.lev}x | ${s.p} | ${s.x} | 학습 ${s.tr}R(${s.trN}) 검증 ${s.ho}R(${s.hoN})${s.luck ? " 운범위" : ""}`);
