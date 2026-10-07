#!/usr/bin/env node
// 🦫 GH Coin 성적·예측 채점 보고서 — bennyjo/phil 의 core/score.py 를 GH Coin 에 맞게 다시 만든 것(코드 복사 없음).
// 보호 파일: 자기개선 루프(Claude Code)는 이 파일을 고치면 안 된다(loop 가 되돌림).
//
// 읽는 것: ../neutron/state.json (GH Coin 앱이 1분마다 내보내는 상태 — 데모 거래·예측 장부·정책·관망 규칙)
// 첫 줄  : settled=<청산 거래 수> win_rate=<승률> pnl=$<손익> roi=<손익/시작자본 1000$>
// 둘째 줄: brier: agent=<우리 예측> market=<기준선> delta=<차이> (BEATING market | behind market)
//          delta 가 음수면 우리 확률이 기준선(무작위 걸음 1/(1+손익비) · 동전 0.5)보다 잘 맞힌 것.
// 쓰는 법: node core/score.mjs [--json]
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
const HERE = path.dirname(fileURLToPath(import.meta.url)), ROOT = path.resolve(HERE, "..");
const STATE = process.env.GHCOIN_STATE || path.resolve(ROOT, "..", "neutron", "state.json");
const JSON_OUT = process.argv.includes("--json");
let S; try { S = JSON.parse(fs.readFileSync(STATE, "utf8")); } catch (e) { console.log(`settled=0 win_rate=0 pnl=$0 roi=0`); console.log(`brier: agent=— market=— delta=— (상태 파일을 못 읽음: ${STATE} — GHCoin.exe 를 켜면 1분마다 생김)`); process.exit(0); }
const n = S.neural || {}, trades = (n.trades || []).filter(t => t && t.t), fc = (n.forecasts || []).filter(r => r.status === "won" || r.status === "lost");
const r3 = x => Math.round(x * 1000) / 1000, r4 = x => Math.round(x * 10000) / 10000;
function bstats(rows) { const k = rows.length; if (!k) return null; let ba = 0, bm = 0, w = 0, ex = 0, v = 0;
  for (const r of rows) { const y = r.status === "won" ? 1 : 0; ba += (r.p - y) ** 2; bm += (r.base - y) ** 2; w += y; ex += r.p; v += r.p * (1 - r.p); }
  return { n: k, win_rate: r3(w / k), brier_agent: r4(ba / k), brier_market: r4(bm / k), brier_delta: r4((ba - bm) / k), expected_wins: r3(ex), actual_wins: w, z: v > 0 ? Math.round((w - ex) / Math.sqrt(v) * 100) / 100 : 0 }; }
function tstats(rows) { const k = rows.length; if (!k) return null; const pnl = rows.reduce((a, t) => a + (+t.pnl || 0), 0), R = rows.reduce((a, t) => a + (+t.R || 0), 0);
  return { n: k, win_rate: r3(rows.filter(t => (+t.R || 0) > 0).length / k), pnl: Math.round(pnl * 100) / 100, R: Math.round(R * 100) / 100, avgR: r3(R / k) }; }
const group = (rows, key) => { const o = {}; for (const r of rows) (o[r[key] || "?"] ||= []).push(r); return o; };
const tradeFc = fc.filter(r => r.src === "데모 거래"), headFc = tradeFc.length ? tradeFc : fc;
const all = tstats(trades) || { n: 0, win_rate: 0, pnl: 0 }, head = bstats(headFc);
const rep = { at: new Date(S.t || 0).toISOString(), overall: all, roi: r3((all.pnl || 0) / 1000), brier: head, brier_scope: tradeFc.length ? "데모 거래" : fc.length ? "전체 예측" : "없음",
  by_source: Object.fromEntries(Object.entries(group(fc, "src")).map(([k, v]) => [k, bstats(v)])),
  by_forecaster: Object.fromEntries(Object.entries(group(fc, "who")).map(([k, v]) => [k, bstats(v)])),
  by_style: Object.fromEntries(Object.entries(group(trades, "style")).map(([k, v]) => [k, tstats(v)])),
  by_strategy: Object.fromEntries(Object.entries(group(trades, "name")).map(([k, v]) => [k, tstats(v)]).sort((a, b) => b[1].n - a[1].n).slice(0, 12)),
  by_policy_rev: Object.fromEntries(Object.entries(group(fc.filter(r => r.src === "데모 거래"), "rev")).map(([k, v]) => [k || "(정책 전)", bstats(v)])),
  calibration: (() => { const b = {}; for (const r of fc) (b[Math.min(9, Math.floor(r.p * 10))] ||= []).push(r); return Object.keys(b).sort().map(k => ({ range: `${k / 10}-${(+k + 1) / 10}`, n: b[k].length, realized: r3(b[k].filter(r => r.status === "won").length / b[k].length) })); })(),
  open_forecasts: (n.forecasts || []).filter(r => r.status === "open").length,
  policy: n.phil?.policy || null, policy_log: (n.phil?.policyLog || []).slice(0, 5),
  hold_rules: (n.hold?.rules || []).map(r => ({ id: r.id, on: r.on, text: r.text })), hold_log: (n.hold?.log || []).slice(0, 5).map(x => `${x.kind} ${x.src}: ${x.e} — ${x.why}`),
  styles_cfg: n.cfg?.styles || null, ai_auto: n.aiAuto || null, mood: n.mood || null };
if (JSON_OUT) { console.log(JSON.stringify(rep, null, 2)); process.exit(0); }
console.log(`settled=${all.n} win_rate=${all.win_rate} pnl=$${all.pnl} roi=${rep.roi}`);
console.log(head ? `brier: agent=${head.brier_agent} market=${head.brier_market} delta=${head.brier_delta} (${head.brier_delta < 0 ? "BEATING market" : "behind market"}) [${rep.brier_scope} ${head.n}건]`
  : `brier: agent=— market=— delta=— (아직 채점된 예측 없음 — 새 버전 앱이 예측 기록을 시작함 · 열린 예측 ${rep.open_forecasts}건)`);
if (head) console.log(`luck-adjusted: expected wins (own ests)=${head.expected_wins} actual=${head.actual_wins} z=${head.z >= 0 ? "+" : ""}${head.z}`);
console.log(`\n상태 시각: ${new Date(S.t || 0).toLocaleString("ko-KR")} · 열린 예측 ${rep.open_forecasts}건`);
const pr = (lab, o, f) => { const e = Object.entries(o).filter(([, v]) => v); if (!e.length) return; console.log(`\n${lab}:`); for (const [k, v] of e) console.log("  " + f(k, v)); };
pr("예측 출처별(브라이어 — delta 음수 = 기준선보다 잘 맞힘)", rep.by_source, (k, s) => `${k.padEnd(8)} n=${String(s.n).padStart(4)} 적중=${s.win_rate} agent=${s.brier_agent} 기준선=${s.brier_market} delta=${s.brier_delta >= 0 ? "+" : ""}${s.brier_delta} z=${s.z}`);
pr("예측한 쪽별", rep.by_forecaster, (k, s) => `${k.padEnd(16)} n=${String(s.n).padStart(4)} delta=${s.brier_delta >= 0 ? "+" : ""}${s.brier_delta}`);
pr("스타일별 데모 거래", rep.by_style, (k, s) => `${({ scalp: "스캘핑", day: "단타", swing: "스윙" })[k] || k} n=${s.n} 승률=${s.win_rate} 평균=${s.avgR}R 손익=$${s.pnl}`);
pr("매매법별(거래 많은 순)", rep.by_strategy, (k, s) => `${k.slice(0, 34).padEnd(34)} n=${s.n} 평균=${s.avgR}R 손익=$${s.pnl}`);
pr("정책 판(rev)별 데모 거래 예측", rep.by_policy_rev, (k, s) => `${k.padEnd(10)} n=${s.n} delta=${s.brier_delta >= 0 ? "+" : ""}${s.brier_delta}`);
if (rep.calibration.length) console.log("\n보정(예측 확률 구간 vs 실제 비율): " + rep.calibration.map(c => `${c.range}:n=${c.n},실제=${c.realized}`).join("  "));
console.log(`\n지금 정책: ${JSON.stringify(rep.policy || "기본값")}`);
if (rep.policy_log.length) console.log("최근 정책 적용: " + rep.policy_log.map(x => `${x.rev || "-"} ${(x.done || []).join("·") || "변경 없음"}${(x.dropped || []).length ? " (거부 " + x.dropped.join(",") + ")" : ""}`).join(" | "));
console.log("관망 규칙: " + rep.hold_rules.map(r => `${r.on ? "✅" : "⬜"}${r.id}`).join(" "));
