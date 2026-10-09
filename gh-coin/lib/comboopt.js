// 🔬 지표 최적화 백테스트 엔진(공용) — 도구(tools/combo-opt.mjs)와 앱(optlab.js → optworker.js)이 '같은 함수'를 쓴다 → 같은 데이터면 같은 결과.
//
// 고르는 법(노이즈 줄이기):
//   ① 기간을 같은 길이 5구간으로 나눔. 앞 4구간(학습)만 보고 고르고, 마지막 1구간(검증)은 고를 때 안 봄.
//   ② 점수 = 구간별 평균 R 의 평균 − 0.5×구간 간 편차 → 한 구간만 좋은 값보다 고르게 좋은 값.
//   ③ 이웃 평균(그리드에서 한 칸씩 옆 값까지) → 한 점만 튀는 우연한 값 대신 '평평한 고원'.
//   ④ 레버리지마다 따로: 지표 값 + 노이즈 거르기(1단계, 그 레버리지의 손절 상한) → 상위 3개마다 손절·익절·청산(2단계) → 후보 9개.
//   ⑤ 통과 = 학습 점수 > 0 그리고 검증 구간 평균 R > 0(10건 이상). 운 보정: 시험한 경우의 수(K)만큼 '최고값이 운으로도 나오는 폭'을 넘었는지.
//   ⑥ ⭐ 대표: 레버리지마다 (조합 × 시간봉) 중 학습 점수 1위 — 검증 구간은 고를 때 안 봄.
import * as CB from "./combos.js";
import { expMaxZ } from "./robust.js";

export const REF = { k: 1.5, rr: 1.5, ex: 1 };   // 1단계 기준 청산(지표 값만 비교)
export const EXITS = CB.gridList(CB.EXIT_GRID);
const r3 = v => Math.round(v * 1000) / 1000;

// [시작, 시작+w, …, 시작+4w, ∞] — 마지막 구간 = 검증
export function foldBounds(start, end, k = 5) { const w = (end - start) / k, B = []; for (let i = 0; i < k; i++) B.push(start + i * w); B.push(Infinity); return { B, span: w }; }

// 한 후보의 성적: 학습(앞 4구간) · 검증(마지막) · 전체 · 구간별 · 최근 1~5구간 누적(lb: [건수, 평균R, 승률%])
export function evalSet(T, end, B, span, minN = 30) {
  const f = CB.foldStats(T, B), tr = CB.robust(f.slice(0, 4), minN), all = CB.robust(f, Math.round(minN * 4 / 3)), ho = f[4];
  const lb = [1, 2, 3, 4, 5].map(y => { const s = CB.stat(T.filter(t => t.t >= end - y * span)); return [s.n, s.mean, s.wr]; });
  const trT = T.filter(t => t.t < B[4]), st = CB.stat(trT);
  return { tr: { score: r3(tr.score), n: tr.n, mean: r3(tr.mean), sd: st.sd }, ho: { n: ho.n, mean: r3(ho.mean), wr: Math.round(ho.wr * 100) }, all: { score: r3(all.score), n: all.n, mean: r3(all.mean) },
    yr: f.map(x => [x.n, r3(x.mean)]), lb };
}

// 코인 하나: data = { "15": 캔들[], "30": 캔들[], "60": 캔들[] } (필요한 것만) · tick(진행 0~1, 글) 은 가끔 불림(await 가능 — 화면 멈춤 방지·중지)
// minN = 학습(앞 4구간) 최소 거래 수 — 기본 30(도구·5년). 짧은 기간은 앱이 줄여서 넘김(그래도 10 이상).
export async function optimizeCoin({ sym, ko = sym, data, B, span, tfs = CB.TFS, levs = null, combos = null, bestLevs = [30, 40, 50], minN = 30, tick = null }) {
  const CS = CB.COMBOS.filter(c => !combos || combos.includes(c.key)), TF = tfs.filter(tf => data[tf]?.length);
  const levOf = tf => CB.LEVS[tf].filter(l => !levs || levs.includes(l));
  const out = {}, summary = [];
  // 진행률: 1단계(지표 값 × 레버리지) + 2단계(3 × 청산 × 레버리지) 시뮬레이션 수
  let total = 0, done = 0, lastT = 0;
  for (const tf of TF) for (const C of CS) { const g = CB.gridList(C.grid).length, nl = levOf(tf).length; total += g * nl + 3 * EXITS.length * nl; }
  const step = async (n, msg) => { done += n; const now = Date.now(); if (tick && now - lastT > 150) { lastT = now; await tick(total ? done / total : 1, msg); } };
  for (const tf of TF) {
    const D = CB.cols(data[tf]), end = D.t[D.n - 1], LV = levOf(tf); if (!LV.length) continue;
    out[tf] = {};
    for (const C of CS) {
      const G = CB.gridList(C.grid), K = G.length * EXITS.length, sc = Object.fromEntries(LV.map(l => [l, new Map()])), levsOut = {};
      // ① 지표 값 + 노이즈 거르기 — 신호를 한 번 만들고 레버리지마다 기준 청산으로 (메모리: 신호는 바로 버림)
      for (let gi = 0; gi < G.length; gi++) { const p = G[gi], sig = CB.comboDir(D, C.key, p);
        for (const lev of LV) { const T = CB.simulate(D, sig, REF, lev), f = CB.foldStats(T, B); sc[lev].set(CB.pkey(p), { p, ...CB.robust(f.slice(0, 4), minN) }); }
        await step(LV.length, `${CB.TF_KO[tf]} ${C.ko} · 지표 값 ${gi + 1}/${G.length}`); }
      for (const lev of LV) {
        const pl = CB.plateau(C.grid, sc[lev]), ind = [...pl.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3).map(([k, v]) => ({ p: sc[lev].get(k).p, plat: r3(v) }));
        // ② 상위 3개마다 손절(ATR×k)·손익비·청산 방식
        const cands = [];
        for (const it of ind) {
          const sig = CB.comboDir(D, C.key, it.p), es = new Map(), res = new Map();
          for (const x of EXITS) { const T = CB.simulate(D, sig, x, lev), f = CB.foldStats(T, B); es.set(CB.pkey(x), { p: x, ...CB.robust(f.slice(0, 4), minN) }); res.set(CB.pkey(x), T); }
          const epl = CB.plateau(CB.EXIT_GRID, es);
          for (const [k, v] of [...epl.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3)) {
            const ev = evalSet(res.get(k), end, B, span, minN), luckBar = ev.tr.n > 1 ? ev.tr.sd / Math.sqrt(ev.tr.n) * expMaxZ(K) : 9;
            cands.push({ p: it.p, x: es.get(k).p, plat: r3((v + it.plat) / 2), ...ev, pass: ev.tr.score > 0 && ev.ho.n >= 10 && ev.ho.mean > 0 ? 1 : 0, luck: ev.tr.mean <= luckBar ? 1 : 0 });
          }
          await step(EXITS.length, `${CB.TF_KO[tf]} ${C.ko} ${lev}배 · 손절·익절`);
        }
        await step((3 - ind.length) * EXITS.length, "");
        cands.sort((a, b) => b.plat - a.plat);
        levsOut[lev] = cands;
        const c = cands[0]; if (!c) continue;
        summary.push({ coin: ko, sym, tf, combo: C.key, lev, plat: c.plat, p: CB.paramText(C.key, c.p), x: CB.exitText(c.x), tr: c.tr.mean, trN: c.tr.n, ho: c.ho.mean, hoN: c.ho.n, lb: c.lb.map((l, i) => `${i + 1}y ${l[1]}(${l[0]})`).join(" "), pass: !!c.pass, luck: !!c.luck });
      }
      out[tf][C.key] = { levs: levsOut, K };
    }
  }
  // ⭐ 대표: 레버리지마다 (조합 × 시간봉) 중 학습 점수 1위. 운 보정은 칸 수 × K 로 더 엄하게.
  const best = {};
  for (const lev of bestLevs) {
    const rows = summary.filter(r => r.sym === sym && r.lev === lev).sort((a, b) => b.plat - a.plat), r = rows[0]; if (!r) continue;
    const c = out[r.tf][r.combo].levs[lev][0], K = out[r.tf][r.combo].K * rows.length, bar = c.tr.n > 1 ? c.tr.sd / Math.sqrt(c.tr.n) * expMaxZ(K) : 9;
    best[lev] = { c: r.combo, tf: r.tf, plat: r.plat, pass: c.pass, luck: c.tr.mean <= bar ? 1 : 0, of: rows.length };
  }
  if (tick) await tick(1, "끝");
  return { out, best, summary };
}
