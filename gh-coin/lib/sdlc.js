// 전략 버전 관리(SDLC) + 데이터 모델 제약 검사 — Legend(goldmansachs/finos) 의
//   ① 모델(클래스 + 제약 constraint) 로 데이터가 맞는지 검사하는 방식, ② 작업공간(workspace) → 검토(review) → 승인 → 버전(version) 흐름
// 을 우리 전략 JSON 에 맞게 다시 만든 것. 모든 변경은 감사 기록(journal.js)에도 남긴다.
import * as J from "./journal.js";

/* ---- ① 데이터 모델 제약: 이름 → [조건 함수, 설명] (Legend 클래스의 constraint 처럼 '항상 참이어야 하는 식') ---- */
export const MODELS = {
  Strategy: {
    name_present: [s => !!String(s?.name || "").trim(), "이름이 있어야 한다"],
    has_entry: [s => !!(s?.long_entry || s?.short_entry), "롱 또는 숏 진입 조건이 하나 이상"],
    indicators_unique: [s => { const ids = (s?.indicators || []).map(i => i.id); return new Set(ids).size === ids.length; }, "지표 id 는 겹치지 않는다"],
    leverage_range: [s => { const l = +(s?.risk?.leverage ?? 1); return l >= 1 && l <= 200; }, "레버리지 1~200배"],
    has_stop: [s => !!(s?.risk?.stop_loss_pct || s?.risk?.atr_stop_mult || s?.risk?.trailing_stop_pct), "손절 규칙(손절 % · ATR 손절 · 추적손절 중 하나)이 있어야 한다"],
    position_pct_range: [s => { const p = +(s?.risk?.position_pct ?? 20); return p > 0 && p <= 100; }, "진입 비중 0~100%"],
    fee_realistic: [s => +(s?.risk?.fee_pct ?? 0.04) >= 0.02, "수수료를 0.02% 미만으로 낙관하지 않는다", "Warn"],
  },
  Trade: {
    prices_positive: [t => t?.entryP > 0 && t?.exitP > 0, "진입·청산가 > 0"],
    time_order: [t => !t?.exitT || t.exitT >= t.entryT, "청산 시각 ≥ 진입 시각"],
    side_valid: [t => t?.side === "long" || t?.side === "short", "방향은 롱·숏"],
  },
  Candle: {
    ohlc_sane: [b => b && b.h >= Math.max(b.o, b.c) && b.l <= Math.min(b.o, b.c) && b.l > 0, "고가 ≥ 시가·종가 ≥ 저가 > 0"],
    volume_nonneg: [b => !(b?.v < 0), "거래량 ≥ 0"],
  }
};
export function validate(model, obj){
  const M = MODELS[model] || {};
  // Legend 제약처럼 결함을 모두 모은다: Error 는 막고, Warn 은 경고만
  const fails = Object.entries(M).filter(([, [f]]) => { try { return !f(obj); } catch(e){ return true; } }).map(([k, [, d, lv]]) => ({rule: k, text: d, level: lv || "Error"}));
  return {ok: !fails.some(f => f.level === "Error"), fails};
}
// 캔들 묶음 품질 검사: 제약 위반 + 빈 봉(시간 간격) + 이상값(직전 대비 ±25% 초과)
export function candleQuality(cs, stepMs){
  let bad = 0, gaps = 0, spikes = 0;
  for (let i = 0; i < cs.length; i++){
    if (!validate("Candle", cs[i]).ok) bad++;
    if (i && stepMs && cs[i].t - cs[i - 1].t > stepMs * 1.5) gaps += Math.round((cs[i].t - cs[i - 1].t) / stepMs) - 1;
    if (i && Math.abs(cs[i].c / cs[i - 1].c - 1) > 0.25) spikes++;
  }
  const stale = stepMs && cs.length ? Date.now() - cs.at(-1).t > stepMs * 3 : false;
  return {n: cs.length, bad, gaps, spikes, stale, ok: !bad && !gaps && !spikes && !stale};
}

/* ---- ② 전략 SDLC: 초안(workspace) → 검토 요청(review) → 승인(approve) → 버전(vN) ---- */
const KEY = "coinSDLC";
const load = () => { try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch(e){ return {}; } };
const save = o => { try { localStorage.setItem(KEY, JSON.stringify(o)); } catch(e){} };
const keyOf = name => String(name || "전략").trim().slice(0, 60);
// 두 전략 JSON 의 차이(평평하게 펼친 경로 기준)
export function diff(a, b){
  const flat = (o, p = "", out = {}) => { if (o && typeof o === "object") for (const [k, v] of Object.entries(o)) flat(v, p ? p + "." + k : k, out); else out[p] = JSON.stringify(o); return out; };
  const A = flat(a || {}), B = flat(b || {}), keys = [...new Set([...Object.keys(A), ...Object.keys(B)])];
  return keys.filter(k => A[k] !== B[k]).map(k => ({path: k, from: A[k] == null ? "—" : A[k], to: B[k] == null ? "—" : B[k]}));
}
export function project(name){ return load()[keyOf(name)] || null; }
export function projects(){ return Object.values(load()).sort((a, b) => (b.t || 0) - (a.t || 0)); }
// 초안 제출: 모델 제약을 먼저 통과해야 검토로 간다
export function propose(spec, {author = "", why = ""} = {}){
  const all = load(), k = keyOf(spec?.name), p = all[k] || {name: k, versions: [], reviews: [], t: 0};
  const v = validate("Strategy", spec), base = p.versions.at(-1)?.spec || null;
  const rv = {id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6), spec, author, why, t: Date.now(), status: v.ok ? "review" : "rejected", fails: v.fails, diff: diff(base, spec)};
  p.reviews.push(rv); p.reviews = p.reviews.slice(-20); p.t = Date.now(); all[k] = p; save(all);
  J.record("strategy-review", k + "#" + rv.id, {status: rv.status, author, changes: rv.diff.length}, {who: author, why: why || (v.ok ? "검토 요청" : "제약 위반: " + v.fails.map(f => f.text).join(", "))});
  return rv;
}
// 승인 = 새 버전 발행 (승인자는 코드 관문 또는 사람). 반려 = 이유와 함께 닫힘
export function decide(name, reviewId, ok, {who = "", why = ""} = {}){
  const all = load(), p = all[keyOf(name)]; if (!p) return null;
  const rv = p.reviews.find(r => r.id === reviewId); if (!rv || rv.status !== "review") return rv || null;
  rv.status = ok ? "approved" : "rejected"; rv.by = who; rv.reason = why; rv.decided = Date.now();
  if (ok){
    // 버전 번호: 조건·지표 종류(논리)가 바뀌면 MAJOR, 숫자 파라미터만 바뀌면 MINOR, 위험 설정만 바뀌면 PATCH
    const prev = p.versions.at(-1)?.semver || "0.0.0", [ma, mi, pa] = prev.split(".").map(Number), d = rv.diff;
    const logic = !p.versions.length || d.some(x => /(entry|exit)\.(conditions\.\d+\.(left|op)|logic)|indicators\.\d+\.(type|id)/.test(x.path) || /^indicators$|_entry$|_exit$/.test(x.path));
    const params = d.some(x => !/^risk\./.test(x.path));
    const semver = logic ? `${ma + 1}.0.0` : params ? `${ma}.${mi + 1}.0` : `${ma}.${mi}.${pa + 1}`;
    const ver = {v: p.versions.length + 1, semver, spec: rv.spec, t: Date.now(), by: who, author: rv.author, why: rv.why || why, changes: rv.diff.length}; p.versions.push(ver); p.versions = p.versions.slice(-30);
    J.record("strategy", p.name, {version: ver.v, changes: rv.diff.map(d => d.path).slice(0, 8)}, {who, why: why || "승인 → 버전 v" + ver.semver}); }
  else J.record("strategy-review", p.name + "#" + rv.id, {status: "rejected"}, {who, why});
  p.t = Date.now(); save(all); return rv;
}
export const latest = name => project(name)?.versions.at(-1) || null;
