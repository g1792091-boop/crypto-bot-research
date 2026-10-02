// 차트 패턴 스캐너 — stock-pattern(BennyThadikaran) 의 피벗·허용오차 규칙과 chart_patterns(zeta-zetra) 의 회귀선 분류를
// 코인에 맞게 다시 만든 것(코드 복사 없음, 규칙만 재구현).
//   · 피벗: 좌우 L·R 봉 안에서 가장 높은 고가/낮은 저가 (오른쪽 R 봉이 '마감'된 뒤에만 확정 → 미래 참조 없음)
//   · 허용오차 abl: 패턴 구간 봉 길이(고가-저가)의 중앙값 — 코인 가격 크기와 상관없이 '거의 같다'를 판단
//   · 기울기: ATR(14) / 봉 단위로 정규화 (원본의 FX 가격 단위 문턱값을 그대로 쓰지 않음)
//   · 상태: 형성 중(forming) → 돌파(breakout) → 목표 도달(target) / 실패(failed) — 원본은 '형성 중'에서 멈추고, 알림은 돌파부터
// 패턴: 쌍봉·쌍바닥 · 헤드앤숄더(역) · 삼각수렴(상승·하락·대칭) · VCP(변동성 수축) · 상승·하락 깃발 · 쐐기 · 채널 · 페넌트 · 추세선
const median = a => { const s = a.filter(Number.isFinite).sort((x, y) => x - y), m = s.length >> 1; return s.length ? (s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2) : 0; };
const abl = (c, a, b) => median(c.slice(Math.max(0, a), b + 1).map(k => k.h - k.l));
function atrAt(c, i, n = 14){ let s = 0, k = 0; for (let j = Math.max(1, i - n + 1); j <= i; j++){ s += Math.max(c[j].h - c[j].l, Math.abs(c[j].h - c[j - 1].c), Math.abs(c[j].l - c[j - 1].c)); k++; } return k ? s / k : 0; }
const sma = (c, i, n) => { if (i < n - 1) return null; let s = 0; for (let j = i - n + 1; j <= i; j++) s += c[j].c; return s / n; };

export function pivots(c, L = 6, R = 6){
  const out = [];
  for (let i = L; i < c.length - R; i++){
    let hi = true, lo = true;
    for (let j = i - L; j <= i + R && (hi || lo); j++){ if (j === i) continue; if (c[j].h > c[i].h) hi = false; if (c[j].l < c[i].l) lo = false; }
    // 같은 봉이 고점·저점 피벗이 동시에 되는 바깥 봉은 버린다 (원본의 well-formedness 검사)
    if (hi && lo) continue;
    if (hi) out.push({i, t: c[i].t, p: c[i].h, v: c[i].v, type: "H"});
    if (lo) out.push({i, t: c[i].t, p: c[i].l, v: c[i].v, type: "L"});
  }
  return out;
}
function fitLine(pts){
  const n = pts.length; if (n < 2) return null;
  let sx = 0, sy = 0, sxx = 0, sxy = 0, syy = 0;
  for (const p of pts){ sx += p.i; sy += p.p; sxx += p.i * p.i; sxy += p.i * p.p; syy += p.p * p.p; }
  const d = n * sxx - sx * sx; if (!d) return null;
  const m = (n * sxy - sx * sy) / d, b = (sy - m * sx) / n;
  const vy = n * syy - sy * sy, r = vy > 0 ? (n * sxy - sx * sy) / Math.sqrt(d * vy) : 1;
  return {m, b, r, at: i => m * i + b};
}
const pt = (c, i, p) => ({i, t: c[i].t, p});
const lineThrough = (a, b) => { const m = (b.p - a.p) / ((b.i - a.i) || 1); return {m, b: a.p - m * a.i, at: i => a.p + m * (i - a.i)}; };

/* ---- 쌍봉 / 쌍바닥 (stock-pattern 규칙) ---- */
function doubleTop(c, P, bear = true){
  const last = c.length - 1, F = c[last].c, H = P.filter(p => p.type === (bear ? "H" : "L"));
  const ext = arr => arr.reduce((m, p) => !m || (bear ? p.p > m.p : p.p < m.p) ? p : m, null);
  let A = ext(H);
  for (let guard = 0; A && guard < 8; guard++){
    const C = ext(H.filter(p => p.i > A.i)); if (!C) return null;
    const mids = P.filter(p => p.type === (bear ? "L" : "H") && p.i > A.i && p.i < C.i);
    const B = mids.reduce((m, p) => !m || (bear ? p.p < m.p : p.p > m.p) ? p : m, null);
    if (B){
      const tol = abl(c, A.i, C.i), atr = atrAt(c, C.i, 15);
      const deepOk = bear ? C.p - B.p < 4 * atr : B.p - C.p < 4 * atr;
      const eq = Math.abs(A.p - C.p) <= 0.5 * tol, volDiv = !(C.v >= A.v);
      // 원본은 넥라인(B) 이탈 전만 보고하지만, 우리는 돌파 후에도 목표가 전까지는 '돌파' 상태로 계속 추적한다
      const h0 = Math.abs(C.p - B.p), tgt = bear ? B.p - h0 : B.p + h0;
      const inside = bear ? (B.p < Math.min(A.p, C.p) && F < C.p && F > tgt) : (B.p > Math.max(A.p, C.p) && F > C.p && F < tgt);
      if (C.i < last - 60) return null;   // 오래된 패턴은 버림
      const intact = c.slice(C.i + 1).every(k => bear ? k.c <= C.p : k.c >= C.p);
      if (deepOk && eq && volDiv && inside && intact){
        const h = Math.abs(C.p - B.p);
        return {code: bear ? "DTOP" : "DBOT", name: bear ? "쌍봉" : "쌍바닥", dir: bear ? -1 : 1, points: {A: pt(c, A.i, A.p), B: pt(c, B.i, B.p), C: pt(c, C.i, C.p)},
          trigger: B.p, target: B.p - (bear ? h : -h), invalid: C.p, why: `두 ${bear ? "고점" : "저점"} 차이 ${(Math.abs(A.p - C.p)).toPrecision(3)} ≤ 0.5×봉중앙값 · 두 번째 거래량 감소`};
      }
    }
    A = C;
  }
  return null;
}
/* ---- 헤드앤숄더 (역) ---- */
function hns(c, P, bear = true){
  const last = c.length - 1, F = c[last].c, T = bear ? "H" : "L", U = bear ? "L" : "H";
  const tops = P.filter(p => p.type === T); if (tops.length < 3) return null;
  const C = tops.reduce((m, p) => !m || (bear ? p.p > m.p : p.p < m.p) ? p : m, null);
  const left = tops.filter(p => p.i < C.i), right = tops.filter(p => p.i > C.i); if (!left.length || !right.length) return null;
  const A = left.reduce((m, p) => !m || (bear ? p.p > m.p : p.p < m.p) ? p : m, null), E = right.reduce((m, p) => !m || (bear ? p.p > m.p : p.p < m.p) ? p : m, null);
  const ext = (a, b) => P.filter(p => p.type === U && p.i > a && p.i < b).reduce((m, p) => !m || (bear ? p.p < m.p : p.p > m.p) ? p : m, null);
  const B = ext(A.i, C.i), D = ext(C.i, E.i); if (!B || !D) return null;
  const tol = abl(c, B.i, D.i), neck = lineThrough(B, D);
  const ok = bear ? (C.p > Math.max(A.p, E.p) && Math.max(B.p, D.p) < Math.min(A.p, E.p) && F < E.p && Math.abs(B.p - D.p) < tol && C.p - E.p > 0.6 * tol)
                  : (C.p < Math.min(A.p, E.p) && Math.min(B.p, D.p) > Math.max(A.p, E.p) && F > E.p && Math.abs(B.p - D.p) < tol && E.p - C.p > 0.6 * tol);
  if (!ok || E.i < last - 40) return null;
  const h = Math.abs(C.p - neck.at(C.i)), nk = neck.at(last);
  if (bear ? F < nk - h : F > nk + h) return null;   // 이미 목표까지 다 간 지난 패턴
  return {code: bear ? "HNSD" : "HNSU", name: bear ? "헤드앤숄더" : "역헤드앤숄더", dir: bear ? -1 : 1, points: {A: pt(c, A.i, A.p), B: pt(c, B.i, B.p), C: pt(c, C.i, C.p), D: pt(c, D.i, D.p), E: pt(c, E.i, E.p)},
    lines: [{name: "넥라인", from: pt(c, B.i, B.p), to: pt(c, last, nk)}], trigger: nk, target: nk - (bear ? h : -h), invalid: bear ? E.p : E.p, why: `머리가 어깨보다 ${(Math.abs(C.p - E.p) / tol).toFixed(1)}×봉중앙값 · 넥라인 거의 평평`};
}
/* ---- VCP 변동성 수축 (강세·약세) ---- */
function vcp(c, P, bull = true){
  const last = c.length - 1, E = c[last].c, T = bull ? "H" : "L", U = bull ? "L" : "H";
  const tops = P.filter(p => p.type === T); if (!tops.length) return null;
  const better = (a, b) => bull ? a > b : a < b;
  const A = tops.reduce((m, p) => !m || better(p.p, m.p) ? p : m, null);
  const lows = P.filter(p => p.type === U && p.i > A.i); if (lows.length < 2) return null;
  const B = lows.reduce((m, p) => !m || better(m.p, p.p) ? p : m, null);   // 가장 깊은 되돌림
  const after = lows.filter(p => p.i > B.i); if (!after.length) return null;
  const D = after.reduce((m, p) => !m || better(m.p, p.p) ? p : m, null);
  const Cs = tops.filter(p => p.i > B.i && p.i < D.i); if (!Cs.length) return null;
  const C = Cs.reduce((m, p) => !m || better(p.p, m.p) ? p : m, null), tol = abl(c, A.i, C.i);
  if (better(C.p, A.p) && Math.abs(A.p - C.p) >= 0.5 * tol) return null;
  if (!(Math.abs(A.p - C.p) <= tol && Math.abs(B.p - D.p) >= 0.8 * tol)) return null;
  if (!(bull ? E < C.p : E > C.p)) return null;
  return {code: bull ? "VCPU" : "VCPD", name: bull ? "VCP(강세 수축)" : "VCP(약세 수축)", dir: bull ? 1 : -1, points: {A: pt(c, A.i, A.p), B: pt(c, B.i, B.p), C: pt(c, C.i, C.p), D: pt(c, D.i, D.p)},
    trigger: C.p, target: C.p + (bull ? 1 : -1) * Math.abs(A.p - B.p), invalid: D.p, why: "두 번째 되돌림이 첫 번째보다 얕음(변동성 수축) · 저항 아래에서 응축"};
}
/* ---- 깃발 (고폴 플래그) ---- */
function flag(c, P, bull = true){
  const n = c.length, last = n - 1; if (n < 90) return null;
  const w = c.slice(-7), ext = bull ? Math.max(...w.map(k => k.h)) : Math.min(...w.map(k => k.l));
  const ei = n - 7 + w.findIndex(k => (bull ? k.h : k.l) === ext);
  if (ei === last || last - ei < 5) return null;
  const hi30 = bull ? Math.max(...c.slice(-30).map(k => k.h)) : Math.min(...c.slice(-30).map(k => k.l)), hi90 = bull ? Math.max(...c.slice(-90).map(k => k.h)) : Math.min(...c.slice(-90).map(k => k.l));
  if (bull ? ext < hi30 || ext < hi90 : ext > hi30 || ext > hi90) return null;
  const s20 = sma(c, last, 20), s50 = sma(c, last, 50); if (!s20 || !s50 || (bull ? s20 < 1.08 * s50 : s20 > 0.92 * s50)) return null;
  const base = P.filter(p => p.type === (bull ? "L" : "H") && p.i < ei).at(-1); if (!base) return null;
  const fib50 = base.p + (ext - base.p) / 2, flagExt = bull ? Math.min(...c.slice(ei + 1).map(k => k.l)) : Math.max(...c.slice(ei + 1).map(k => k.h));
  if (bull ? flagExt < fib50 : flagExt > fib50) return null;
  return {code: bull ? "FLAGU" : "FLAGD", name: bull ? "상승 깃발" : "하락 깃발", dir: bull ? 1 : -1, points: {A: pt(c, base.i, base.p), B: pt(c, ei, ext)},
    trigger: ext, target: ext + (ext - base.p), invalid: fib50, why: `깃대 ${((ext / base.p - 1) * 100).toFixed(1)}% · 되돌림 50% 이내 · SMA20/50 ${(s20 / s50).toFixed(2)}`};
}
/* ---- 회귀선 기하 패턴 (chart_patterns 방식 + 쐐기·채널 추가, 기울기는 ATR/봉) ---- */
function geometry(c, P, {lookback = 40, rMin = 0.85, flat = 0.02} = {}){
  const last = c.length - 1, hs = P.filter(p => p.type === "H" && p.i >= last - lookback), ls = P.filter(p => p.type === "L" && p.i >= last - lookback);
  if (hs.length < 3 || ls.length < 3) return null;                      // 양쪽 모두 3점 이상 (원본 버그 수정)
  const Uf = fitLine(hs), Df = fitLine(ls), atr = atrAt(c, last); if (!Uf || !Df || !atr) return null;
  if (Math.abs(Uf.r) < rMin && Math.abs(Uf.m / atr) > flat) return null;
  if (Math.abs(Df.r) < rMin && Math.abs(Df.m / atr) > flat) return null;
  const su = Uf.m / atr, sd = Df.m / atr, up = Uf.at(last), dn = Df.at(last), F = c[last].c;
  if (up <= dn || F > up + atr * 0.5 || F < dn - atr * 0.5) return null;   // 이미 교차했거나 크게 벗어나면 끝난 패턴
  const width0 = Uf.at(last - lookback) - Df.at(last - lookback), width1 = up - dn, conv = width1 < width0 * 0.8;
  const pole = (() => { const k = Math.min(...hs.concat(ls).map(p => p.i)), j = Math.max(0, k - 15); return Math.abs(c[k].c / c[j].c - 1) > 3 * atr / c[k].c * 3 ? Math.sign(c[k].c - c[j].c) : 0; })();
  let code = null, name = "", dir = 0;
  if (sd > flat && Math.abs(su) <= flat){ code = "TRIA"; name = "상승 삼각수렴"; dir = 1; }
  else if (su < -flat && Math.abs(sd) <= flat){ code = "TRID"; name = "하락 삼각수렴"; dir = -1; }
  else if (sd > flat && su < -flat){ const q = Math.abs(su / sd); if (pole && q > 0.95 && q < 1.05){ code = "PENN"; name = "페넌트"; dir = pole; } else { code = "TRIS"; name = "대칭 삼각수렴"; dir = 0; } }
  else if (Math.sign(su) === Math.sign(sd) && Math.abs(su) > flat){
    const q = su / sd;
    if (q > 0.9 && q < 1.1){ code = su > 0 ? "CHUP" : "CHDN"; name = su > 0 ? "상승 채널" : "하락 채널"; dir = su > 0 ? 1 : -1; if (pole && pole === -Math.sign(su)){ code = "FLAG"; name = pole > 0 ? "상승 깃발(채널)" : "하락 깃발(채널)"; dir = pole; } }
    else if (conv){ code = su > 0 ? "WEDU" : "WEDD"; name = su > 0 ? "상승 쐐기" : "하락 쐐기"; dir = su > 0 ? -1 : 1; }   // 상승 쐐기는 하락 반전 경향
  }
  if (!code) return null;
  const h = width0;
  return {code, name, dir, lines: [{name: "윗선", from: pt(c, last - lookback, Uf.at(last - lookback)), to: pt(c, last, up)}, {name: "아랫선", from: pt(c, last - lookback, Df.at(last - lookback)), to: pt(c, last, dn)}],
    trigger: dir >= 0 ? up : dn, trigger2: dir >= 0 ? dn : up, target: dir >= 0 ? up + h : dn - h, invalid: dir >= 0 ? dn : up,
    why: `윗선 기울기 ${su.toFixed(3)}·아랫선 ${sd.toFixed(3)} ATR/봉 · 상관 ${Uf.r.toFixed(2)}/${Df.r.toFixed(2)}`};
}
/* ---- 추세선 (3번 이상 닿음, 0.1% 허용, 종가 이탈 없음, 현재가 10% 이내) ---- */
function trendline(c, P, up = true){
  const last = c.length - 1, F = c[last].c, pts = P.filter(p => p.type === (up ? "L" : "H"));
  if (pts.length < 3) return null;
  const A = pts.reduce((m, p) => !m || (up ? p.p < m.p : p.p > m.p) ? p : m, null); let best = null;
  for (const B of pts.filter(p => p.i > A.i)){
    const L = lineThrough(A, B), y = L.at(last);
    if (up ? !(F > y && F <= y * 1.1) : !(F < y && F >= y * 0.9)) continue;
    if (c.slice(A.i).some((k, j) => up ? k.c < L.at(A.i + j) * 0.999 : k.c > L.at(A.i + j) * 1.001)) continue;
    const touches = pts.filter(p => p.i >= A.i && Math.abs(p.p - L.at(p.i)) <= A.p * 0.001).length;
    if (touches >= 3 && (!best || touches > best.touches)) best = {B, touches, y};
  }
  if (!best) return null;
  return {code: up ? "UPTL" : "DNTL", name: up ? "상승 추세선" : "하락 추세선", dir: up ? 1 : -1, lines: [{name: "추세선", from: pt(c, A.i, A.p), to: pt(c, last, best.y)}],
    trigger: best.y, target: null, invalid: best.y, why: `${best.touches}번 닿은 선 · 현재가와 ${((Math.abs(F / best.y - 1)) * 100).toFixed(1)}%`};
}

// 상태 머신: 형성 중 → 돌파 → 목표 도달 / 실패 (패턴이 확인된 마지막 피벗 이후의 마감 종가로 판정)
function stateOf(pat, c){
  if (pat.trigger == null) return "forming";
  const F = c.at(-1).c, d = pat.dir || 0;
  if (!d) return F > pat.trigger ? "breakout↑" : F < (pat.trigger2 ?? pat.trigger) ? "breakout↓" : "forming";
  if (pat.target != null && (d > 0 ? F >= pat.target : F <= pat.target)) return "target";
  if (pat.invalid != null && pat.code !== "UPTL" && pat.code !== "DNTL" && (d > 0 ? F < pat.invalid : F > pat.invalid) && !(pat.code === "DTOP" || pat.code === "DBOT")) return "failed";
  return (d > 0 ? F > pat.trigger : F < pat.trigger) ? "breakout" : "forming";
}
export const STATE_KO = {forming: "형성 중", breakout: "돌파", "breakout↑": "위로 돌파", "breakout↓": "아래로 돌파", target: "목표 도달", failed: "실패(무효)"};

// 전체 스캔: 마감된 봉만, 최근 160봉
export function scan(candles, {lookback = 160, L = 6, R = 6} = {}){
  const c = candles.slice(-lookback - R).filter(b => b && b.h >= b.l);
  if (c.length < 60) return [];
  const P = pivots(c, L, R), out = [];
  const tryP = f => { try { const r = f(); if (r){ r.state = stateOf(r, c); out.push(r); } } catch(e){} };
  tryP(() => doubleTop(c, P, true)); tryP(() => doubleTop(c, P, false));
  tryP(() => hns(c, P, true)); tryP(() => hns(c, P, false));
  tryP(() => vcp(c, P, true)); tryP(() => vcp(c, P, false));
  tryP(() => flag(c, P, true)); tryP(() => flag(c, P, false));
  tryP(() => geometry(c, pivots(c, 3, 3)));
  tryP(() => trendline(c, P, true)); tryP(() => trendline(c, P, false));
  return out;
}
