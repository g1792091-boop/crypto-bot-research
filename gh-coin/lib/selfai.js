// GH Coin 자체 AI (GHCoinAI) — 외부 LLM 키 없이 이 앱 안에서만 도는 앙상블 판단 엔진.
// 여러 신호를 하나의 '방향 + 확신도'로 합친다:
//   · 기술 평점(ta_rating, 트레이딩뷰식)         [-1..1]
//   · 멀티 시간대 종합 점수(combo.analyzeTF)      [-1..1] (높은 시간대에 가중)
//   · ML 확률(nuri-ai/ml.js walk-forward)          0..1 → [-1..1], 우위(edge)만큼만 신뢰
//   · 알파 팩터 합성(vnpy Alpha158 계열)           tanh 로 [-1..1]
// 아이디어 출처(코드 복사 없음): TLSRUF/ai-trader-team(여러 에이전트 의견을 합의로),
//   jnMetaCode/agency-agents-ko(역할 분담), anthropics/claude-cookbooks(앙상블·LLM-판정 패턴),
//   anthropics/financial-services(리스크·확신도 프레이밍), continuedev/continue(여러 모델 합치기).
// 중요: 이 엔진은 '판단 보조'다. 실제 주문은 그대로 live.js(한도·승인·긴급정지)만 낸다 — 자체 AI 가 주문을 내지 않는다.

const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
const tanh = x => { const e = Math.exp(2 * x); return (e - 1) / (e + 1); };
const sgn = (x, eps = 0.05) => x > eps ? 1 : x < -eps ? -1 : 0;

// 시간대 가중 (높은 시간대일수록 추세로서 무게가 크다)
const TF_W = {"1": 0.05, "5": 0.1, "15": 0.2, "30": 0.25, "60": 0.3, "240": 0.4, "D": 0.5};
// ML 우위에 따른 신뢰 배수: 통계적으로 유의하면 그대로, 약하면 절반, 없으면 거의 무시
const EDGE_W = {edge: 1, weak: 0.5};

export const LABELS = [
  {min: 0.5, label: "강한 롱", dir: 1}, {min: 0.18, label: "롱", dir: 1},
  {min: -0.18, label: "중립", dir: 0}, {min: -0.5, label: "숏", dir: -1}, {min: -Infinity, label: "강한 숏", dir: -1}
];
export function labelOf(score){ for (const L of LABELS) if (score >= L.min) return L; return LABELS.at(-1); }

// 핵심 융합 — 순수 함수(숫자만 받음 → 테스트 쉬움)
// inputs: { ta:number|null, tfScores:[{tf,score}], ml:{prob:0..1, edge:"edge"|"weak"|null}|null, alpha:number|null,
//           ai:{score:-1..1, confidence:0..100}|null (외부 LLM API 의견 — 선택), regime?:string }
export function fuse(inputs = {}){
  const { ta = null, tfScores = [], ml = null, alpha = null, ai = null, regime = null } = inputs;
  const parts = [];

  if (Number.isFinite(ta))
    parts.push({name: "기술 평점", key: "ta", w: 0.28, v: clamp(ta, -1, 1), text: `지표 종합 ${fmtSigned(ta)}`});

  const tfs = (tfScores || []).filter(x => x && Number.isFinite(x.score));
  if (tfs.length){
    const wsum = tfs.reduce((s, x) => s + (TF_W[String(x.tf)] || 0.2), 0) || 1;
    const trend = tfs.reduce((s, x) => s + (TF_W[String(x.tf)] || 0.2) * clamp(x.score, -1, 1), 0) / wsum;
    const aligned = tfs.length > 1 && tfs.every(x => sgn(x.score) === sgn(tfs[0].score) && sgn(tfs[0].score) !== 0);
    parts.push({name: "멀티 시간대", key: "trend", w: 0.30, v: clamp(trend, -1, 1), aligned,
      text: tfs.map(x => `${tfKo(x.tf)} ${fmtSigned(x.score)}`).join(" · ") + (aligned ? " · 시간대 정렬" : "")});
  }

  if (ml && Number.isFinite(ml.prob)){
    const edgeW = EDGE_W[ml.edge] ?? 0.15, v = clamp((ml.prob - 0.5) * 2, -1, 1);
    parts.push({name: "ML 확률", key: "ml", w: 0.27 * edgeW, v, edge: ml.edge || null,
      text: `상승확률 ${(ml.prob * 100).toFixed(0)}% · 우위 ${ml.edge === "edge" ? "있음" : ml.edge === "weak" ? "약함" : "없음"}`});
  }

  if (Number.isFinite(alpha))
    parts.push({name: "알파 팩터", key: "alpha", w: 0.15, v: tanh(alpha / 2), text: `합성 ${fmtSigned(tanh(alpha / 2))}`});

  // 외부 LLM API 의견 (선택) — 확신도만큼 가중. 자체 신호와 별개의 한 표로만 반영(과신 방지 상한 0.25)
  if (ai && Number.isFinite(ai.score)){
    const conf = clamp(Number(ai.confidence) || 0, 0, 100) / 100;
    parts.push({name: "외부 AI", key: "ai", w: 0.25 * conf, v: clamp(ai.score, -1, 1), aiConf: Math.round(conf * 100),
      text: `LLM 의견 ${fmtSigned(clamp(ai.score, -1, 1))} · 확신 ${Math.round(conf * 100)}%`});
  }

  const W = parts.reduce((s, p) => s + p.w, 0);
  const score = W ? clamp(parts.reduce((s, p) => s + p.w * p.v, 0) / W, -1, 1) : 0;
  const L = labelOf(score);

  // 확신도: 점수 크기(0.6) + 신호 일치도(0.4), ML 우위면 +, 데이터 적으면 벌점. 단정 피하려 최대 95.
  const voters = parts.filter(p => sgn(p.v) !== 0);
  const agree = voters.length ? voters.filter(p => sgn(p.v) === sgn(score) && sgn(score) !== 0).length / voters.length : 0;
  const edgeBonus = ml?.edge === "edge" ? 1.08 : ml?.edge === "weak" ? 1.0 : 0.96;
  const dataPenalty = parts.length >= 3 ? 1 : parts.length === 2 ? 0.88 : 0.72;
  const confidence = Math.round(clamp((Math.abs(score) * 0.6 + agree * 0.4) * 100 * edgeBonus * dataPenalty, 0, 95));

  const reasons = parts.map(p => `${p.name}: ${p.text}`);
  if (regime) reasons.push(`장세: ${regime}`);
  return {score: +score.toFixed(4), dir: L.dir, label: L.label, confidence, agree: +agree.toFixed(2), parts, reasons, inputs: {ta, tfScores: tfs, ml, alpha, regime}};
}

// 사람이 읽는 한 줄 요약
export function summary(j){
  return `자체 AI: ${j.label} (점수 ${fmtSigned(j.score)} · 확신도 ${j.confidence}%) — ${j.reasons.join(" / ")}`;
}

// 캔들에서 바로 판단 (브라우저·Node 공용). candlesByTf: {"60":cs, "240":cs, ...}
//   ml: 미리 돌린 {prob, edge} (선택) · alpha: 미리 계산한 합성 z (선택, 코인 여러 개 횡단면일 때만 의미)
export async function analyze(candlesByTf = {}, {ml = null, alpha = null, taTf = "60"} = {}){
  const TA = await import("./ta_rating.js"), CB = await import("../combo.js");
  const tfScores = [];
  let ta = null, regime = null;
  for (const [tf, cs] of Object.entries(candlesByTf)){
    if (!Array.isArray(cs) || cs.length < 60) continue;
    if (tf === taTf){ try { const r = TA.rating(cs); if (r) ta = r.all; } catch(e){} }
    try { const a = await CB.analyzeTF(cs); tfScores.push({tf, score: a.score}); if (tf === taTf) regime = a.regime?.label || a.regime || null; } catch(e){}
  }
  return fuse({ta, tfScores, ml, alpha, regime});
}

function fmtSigned(v){ return v == null || !Number.isFinite(v) ? "—" : (v >= 0 ? "+" : "") + (+v).toFixed(2); }
function tfKo(tf){ return ({"1": "1분", "5": "5분", "15": "15분", "30": "30분", "60": "1시간", "240": "4시간", "D": "일"})[String(tf)] || tf + ""; }
