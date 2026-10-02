// AI 팀 분석 → 차트 터미널 연결 통로. GH Coin 직원들이 낸 분석(타점·지지저항·패턴·위원회 결정·리스크·거래소 비교·최적화)을
// 코인 심볼별로 저장하면, 차트 터미널의 '🤖 AI 팀' 탭이 읽어 차트 위에 선·표시로 그린다. (같은 실행기 주소 = 같은 저장소)
// 모양: localStorage "ghAnalysis:<SYMBOL>" = {[section]: {t, team, title, text, lines:[{price,label,color,style}], markers:[{t(ms),price?,text,dir,color}], segs:[{a:{t,p},b:{t,p},color,label}], rows?}}
const KEY = s => "ghAnalysis:" + String(s || "").toUpperCase().replace(/^KRW-(\w+)$/, "$1USDT");
export const SECTIONS = {combo: "⚡ 실시간 종합 지표 타점", sr: "📏 지지·저항", entry: "🎯 진입 타점", pattern: "🕯 차트 패턴", ic: "🏛 투자위원회", qrisk: "📐 퀀트 리스크", data: "🔌 거래소 비교", opt: "🎛 전략 최적화", trend: "📈 다중 시간대 추세", calls: "🎯 타점 기록장"};
export function read(sym){ try { return JSON.parse(localStorage.getItem(KEY(sym)) || "{}"); } catch(e){ return {}; } }
export function publish(sym, section, data){
  try {
    const all = read(sym); all[section] = {...data, t: Date.now()};
    localStorage.setItem(KEY(sym), JSON.stringify(all));
    if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent("gh-analysis", {detail: {sym: KEY(sym).slice(11), section}}));
  } catch(e){}
}
// 다른 창(새 탭 터미널)과 같은 창(본부 안 터미널) 모두에서 바뀌면 알림
export function onChange(fn){
  const a = e => fn(e.detail || {}), b = e => { if (e.key && e.key.startsWith("ghAnalysis:")) fn({sym: e.key.slice(11)}); };
  addEventListener("gh-analysis", a); addEventListener("storage", b);
  return () => { removeEventListener("gh-analysis", a); removeEventListener("storage", b); };
}
