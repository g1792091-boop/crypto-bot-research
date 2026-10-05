// 🕯 캔들 패턴 24종 — 널리 알려진 캔들 패턴(TA-Lib·pandas-ta 의 CDL 계열과 같은 이름)의 정의를 직접 구현(코드 복사 없음).
// 입력: 터미널 봉 [{time, open, high, low, close, volume}] · 출력: 봉마다 {dir:+1|-1, key, text} 또는 null (한 봉에 여럿이면 우선순위 높은 것)
// 추세 맥락: 반전형은 직전 흐름이 반대여야 인정(EMA20 기준 + 직전 5봉 방향). 몸통·꼬리 크기는 ATR(14) 대비.
// AUDIT = 2026-10-05 실측(바이낸스 선물 6코인 × 1시간·4시간·일봉, 패턴 뒤 6봉 방향 적중률 vs 같은 방향 기준선). 숫자는 candle 감사 스크립트로 다시 잴 수 있다.
export const PATTERNS = {
  engulf: "장악형", hammer: "망치형", hanging: "교수형", invhammer: "역망치형", star: "유성형", morning: "샛별형", evening: "석별형", dragonfly: "잠자리 도지", gravestone: "비석 도지",
  harami: "잉태형", piercing: "관통형", darkcloud: "흑운형", soldiers: "적삼병", crows: "흑삼병", tweezer: "집게형", marubozu: "장대봉(마루보주)", methods: "삼법형", kicker: "키커",
  inside3: "삼내형", outside3: "삼외형", belt: "샅바형(벨트 홀드)",
};
function atr14(c) { const o = new Array(c.length).fill(null); let a = 0; for (let i = 1; i < c.length; i++) { const tr = Math.max(c[i].high - c[i].low, Math.abs(c[i].high - c[i - 1].close), Math.abs(c[i].low - c[i - 1].close)); a = i <= 14 ? a + tr / 14 : (a * 13 + tr) / 14; if (i >= 14) o[i] = a; } return o; }
function ema20(c) { const o = new Array(c.length).fill(null), k = 2 / 21; let e = c[0]?.close; for (let i = 0; i < c.length; i++) { e = i ? c[i].close * k + e * (1 - k) : c[0].close; if (i >= 19) o[i] = e; } return o; }
/** 모든 패턴 감지 → 봉마다 배열(여러 개 가능). only = 키 집합(주면 그것만) */
export function detectAll(c, { minBodyAtr = 0.5, only = null } = {}) {
  const n = c.length, A = atr14(c), E = ema20(c), out = new Array(n).fill(null);
  const push = (i, dir, key) => { if (only && !only.has(key + (dir > 0 ? "+" : "-"))) return; (out[i] ||= []).push({ dir, key, text: PATTERNS[key] }); };
  for (let i = 5; i < n; i++) {
    const a = A[i], e = E[i]; if (!a || e == null) continue;
    const b = c[i], q = c[i - 1], r = c[i - 2];
    const body = x => Math.abs(x.close - x.open), rng = x => (x.high - x.low) || 1e-12, up = x => x.high - Math.max(x.open, x.close), lw = x => Math.min(x.open, x.close) - x.low, bull = x => x.close > x.open, bear = x => x.close < x.open;
    const big = x => body(x) >= minBodyAtr * a, small = x => body(x) <= 0.3 * a, mid = x => (x.open + x.close) / 2;
    const down5 = c[i - 1].close < c[i - 5].close && q.close < E[i - 1], up5 = c[i - 1].close > c[i - 5].close && q.close > E[i - 1];   // 직전 흐름(패턴 봉 제외)
    // 1) 장악형
    if (big(b) && bull(b) && bear(q) && b.close >= q.open && b.open <= q.close && down5) push(i, 1, "engulf");
    if (big(b) && bear(b) && bull(q) && b.close <= q.open && b.open >= q.close && up5) push(i, -1, "engulf");
    // 2) 망치형 / 교수형 (긴 아래꼬리)
    if (lw(b) >= 2 * body(b) && up(b) <= 0.3 * rng(b) && rng(b) >= a) { if (down5) push(i, 1, "hammer"); else if (up5) push(i, -1, "hanging"); }
    // 3) 역망치형 / 유성형 (긴 위꼬리)
    if (up(b) >= 2 * body(b) && lw(b) <= 0.3 * rng(b) && rng(b) >= a) { if (down5) push(i, 1, "invhammer"); else if (up5) push(i, -1, "star"); }
    // 4) 샛별형 / 석별형
    if (bear(r) && body(r) >= 0.8 * a && small(q) && bull(b) && b.close > mid(r) && c[i - 2].close < c[i - 6]?.close) push(i, 1, "morning");
    if (bull(r) && body(r) >= 0.8 * a && small(q) && bear(b) && b.close < mid(r) && c[i - 2].close > c[i - 6]?.close) push(i, -1, "evening");
    // 5) 잠자리 / 비석 도지
    if (body(b) <= 0.1 * rng(b) && rng(b) >= 0.8 * a) { if (lw(b) >= 0.6 * rng(b) && down5) push(i, 1, "dragonfly"); else if (up(b) >= 0.6 * rng(b) && up5) push(i, -1, "gravestone"); }
    // 6) 잉태형 (큰 봉 안에 작은 반대 봉)
    if (body(q) >= 0.8 * a && body(b) <= 0.5 * body(q) && Math.max(b.open, b.close) <= Math.max(q.open, q.close) && Math.min(b.open, b.close) >= Math.min(q.open, q.close)) { if (bear(q) && bull(b) && down5) push(i, 1, "harami"); else if (bull(q) && bear(b) && up5) push(i, -1, "harami"); }
    // 7) 관통형 / 흑운형
    if (bear(q) && body(q) >= 0.8 * a && bull(b) && b.open <= q.close && b.close > mid(q) && b.close < q.open && down5) push(i, 1, "piercing");
    if (bull(q) && body(q) >= 0.8 * a && bear(b) && b.open >= q.close && b.close < mid(q) && b.close > q.open && up5) push(i, -1, "darkcloud");
    // 8) 적삼병 / 흑삼병
    if ([r, q, b].every(x => bull(x) && body(x) >= 0.5 * a && up(x) <= 0.4 * body(x)) && q.close > r.close && b.close > q.close && q.open > r.open && b.open > q.open) push(i, 1, "soldiers");
    if ([r, q, b].every(x => bear(x) && body(x) >= 0.5 * a && lw(x) <= 0.4 * body(x)) && q.close < r.close && b.close < q.close && q.open < r.open && b.open < q.open) push(i, -1, "crows");
    // 9) 집게형 (같은 저가/고가 두 번)
    if (Math.abs(b.low - q.low) <= 0.05 * a && bear(q) && bull(b) && down5 && rng(q) >= 0.7 * a) push(i, 1, "tweezer");
    if (Math.abs(b.high - q.high) <= 0.05 * a && bull(q) && bear(b) && up5 && rng(q) >= 0.7 * a) push(i, -1, "tweezer");
    // 10) 장대봉(마루보주): 꼬리가 거의 없는 큰 몸통
    if (body(b) >= 1.2 * a && up(b) <= 0.08 * body(b) && lw(b) <= 0.08 * body(b)) push(i, bull(b) ? 1 : -1, "marubozu");
    // 11) 삼법형: 큰 봉 → 작은 반대 봉 3개가 그 범위 안 → 같은 방향 큰 봉이 돌파
    { const f = c[i - 4], mids = [c[i - 3], c[i - 2], c[i - 1]];
      if (bull(f) && body(f) >= a && mids.every(x => x.high <= f.high && x.low >= f.low && body(x) <= 0.6 * body(f)) && bull(b) && b.close > f.close) push(i, 1, "methods");
      if (bear(f) && body(f) >= a && mids.every(x => x.high <= f.high && x.low >= f.low && body(x) <= 0.6 * body(f)) && bear(b) && b.close < f.close) push(i, -1, "methods"); }
    // 12) 키커: 반대 방향 큰 봉이 직전 봉 시가 너머에서 시작(코인은 갭이 드물어 '시가가 직전 시가 이상'으로 완화)
    if (bear(q) && big(q) && bull(b) && body(b) >= a && b.open >= q.open) push(i, 1, "kicker");
    if (bull(q) && big(q) && bear(b) && body(b) >= a && b.open <= q.open) push(i, -1, "kicker");
    // 13) 삼내형: 잉태형 뒤 확인 봉
    if (bear(r) && body(r) >= 0.8 * a && bull(q) && body(q) <= 0.5 * body(r) && q.close <= r.open && q.open >= r.close && bull(b) && b.close > r.open) push(i, 1, "inside3");
    if (bull(r) && body(r) >= 0.8 * a && bear(q) && body(q) <= 0.5 * body(r) && q.close >= r.open && q.open <= r.close && bear(b) && b.close < r.open) push(i, -1, "inside3");
    // 14) 삼외형: 장악형 뒤 확인 봉
    if (bear(r) && bull(q) && q.close >= r.open && q.open <= r.close && body(q) >= minBodyAtr * a && bull(b) && b.close > q.close) push(i, 1, "outside3");
    if (bull(r) && bear(q) && q.close <= r.open && q.open >= r.close && body(q) >= minBodyAtr * a && bear(b) && b.close < q.close) push(i, -1, "outside3");
    // 15) 샅바형: 시가가 저가(고가)인 큰 봉이 흐름을 뒤집음
    if (bull(b) && body(b) >= a && lw(b) <= 0.05 * body(b) && down5) push(i, 1, "belt");
    if (bear(b) && body(b) >= a && up(b) <= 0.05 * body(b) && up5) push(i, -1, "belt");
  }
  return out;
}
// 실측 감사표: key+방향 → [표본 수, 6봉 뒤 방향 적중률 %, 기준선 %, 전반 우위 %p, 후반 우위 %p]. 우위 = 적중률 − 기준선. (채워 넣는 값은 감사 스크립트 결과)
export const AUDIT = { t: "2026-10-05", horizon: 6, note: "바이낸스 선물 6코인 × 1시간·4시간·일봉 · 패턴 뒤 6봉 방향 적중률 · 기준선 = 같은 흐름(직전 5봉)에서 아무 봉이나 골랐을 때", rows: {"harami+":[1431,54.3,52.2,2.3,1.9],"morning+":[314,54.5,50,5.6,3.6],"star-":[1253,52.2,51.9,-1.7,2],"gravestone-":[607,55.7,51.9,5.3,2.6],"tweezer+":[1106,53.3,52.2,2.9,-0.7],"methods-":[158,41.8,50,-18.8,1.9],"hanging-":[743,49.9,51.9,-4.4,0.3],"dragonfly+":[737,52,52.2,-0.5,0],"engulf+":[2059,49.8,52.2,-2.4,-2.3],"belt+":[393,50.9,52.2,-2.5,-0.3],"outside3+":[2064,48.3,50,-0.5,-2.9],"soldiers+":[120,52.5,50,5.8,0],"engulf-":[2233,49.3,51.9,-2.6,-2.6],"tweezer-":[1182,51.9,51.9,0.2,-0.1],"outside3-":[2175,47.1,50,-2,-3.8],"marubozu-":[361,49.6,50,-3.1,2.7],"belt-":[534,52.4,51.9,-5,5.5],"darkcloud-":[518,51.5,51.9,-4.1,3.8],"harami-":[1402,54.4,51.9,2.3,2.6],"marubozu+":[341,48.7,50,-0.9,-1.6],"hammer+":[1421,53.7,52.2,0.5,2.5],"piercing+":[503,50.9,52.2,-1.6,-1.1],"crows-":[87,51.7,50,1,2.6],"invhammer+":[544,57,52.2,8.2,1],"methods+":[103,50.5,50,9.2,-7.4],"inside3+":[93,40.9,50,-6.4,-13.2],"evening-":[359,50.1,50,2,-1.6],"inside3-":[135,45.9,50,-9.6,-0.6]} };
export const gradeOf = r => !r ? "미측정" : r[0] >= 300 && r[3] >= 1.5 && r[4] >= 1.5 ? "약한 우위" : r[0] >= 300 && r[3] <= -1.5 && r[4] <= -1.5 ? "역효과" : r[0] < 300 ? "표본 부족" : "우위 없음";
export const verified = () => new Set(Object.entries(AUDIT.rows).filter(([, r]) => gradeOf(r) === "약한 우위").map(([k]) => k));
export const statOf = (key, dir) => AUDIT.rows[key + (dir > 0 ? "+" : "-")] || null;
