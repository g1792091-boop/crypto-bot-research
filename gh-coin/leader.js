// 👑 엔진은 한 창에서만 — 같은 PC에서 GH Coin 창이 둘 이상 열리면(실행 파일을 두 번 켜거나, 예전 창이 남은 채 다시 켠 경우)
// 창마다 매매 엔진·사무실 업무·저장이 따로 돌아 서로의 데모 장부를 덮어쓰고 로컬 모델을 두 배로 쓴다. (2026-10-05 실제로 겪음: 실험 리그 전략이 사라지고 응답이 느려짐)
// 브라우저의 Web Locks 로 '엔진 주인'을 한 창만 정한다. 주인 창이 닫히면 기다리던 다른 창이 자동으로 이어받는다. 나머지 창은 보기 전용.
let state = "pending";   // pending → leader | viewer
const waiters = [];
function become() { if (state === "leader") return; state = "leader"; for (const f of waiters.splice(0)) { try { f(); } catch (e) { console.warn(e); } } try { window.dispatchEvent(new CustomEvent("gh-leader", { detail: { leader: true } })); } catch (e) {} }
function init() {
  if (init.done) return; init.done = true;
  try {
    if (typeof navigator === "undefined" || !navigator.locks?.request) return become();   // 잠금을 못 쓰는 환경이면 예전처럼 그냥 실행
    // 지금 바로 얻을 수 있는지 먼저 확인(못 얻으면 보기 전용으로 표시) → 그다음 줄 서서 기다린다(주인 창이 닫히면 이어받음)
    navigator.locks.request("ghcoin-engine", { ifAvailable: true }, lock => { if (!lock && state === "pending") { state = "viewer"; try { window.dispatchEvent(new CustomEvent("gh-leader", { detail: { leader: false } })); } catch (e) {} } }).catch(() => {});
    navigator.locks.request("ghcoin-engine", () => { become(); return new Promise(() => {}); }).catch(() => become());   // 창이 살아 있는 동안 계속 쥐고 있음
  } catch (e) { become(); }
}
/** 이 창이 엔진 주인이 되면(대부분 즉시) fn 실행. 주인이 아니면 주인이 될 때까지 미룬다. */
export function onLeader(fn) { init(); if (state === "leader") { try { fn(); } catch (e) { console.warn(e); } } else waiters.push(fn); }
export const isLeader = () => { init(); return state === "leader"; };
export const leaderState = () => { init(); return state; };   // "pending"(확인 중) · "leader" · "viewer"(다른 창이 주인)
