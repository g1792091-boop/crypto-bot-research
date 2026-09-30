// AI 분석팀
import { $, api, busy, esc, px, state, toast } from "./core.js";

const STANCE = { bullish: ["강세", "up"], bearish: ["약세", "down"], neutral: ["중립", "dim"] };
const ACTION = { long: ["롱", "up"], short: ["숏", "down"], stay_flat: ["관망", "accent"] };

async function run() {
  const r = await api("/api/agents/run", { method: "POST", body: { symbol: state.symbol } });
  $("#agents-meta").textContent = `${state.symbol} · ${r.engine === "rules" ? "기본 분석기" : r.model} · ${r.elapsed_sec}초${r.snapshot.data_source === "synthetic" ? " · 가상 데이터" : ""}`;
  const cards = Object.values(r.reports).map((a) => {
    const [l, c] = STANCE[a.stance];
    return `<div class="panel agent"><div class="ph"><span class="t">${esc(a.name)}</span><div class="grow"></div>
      <span class="stance ${c}">${l}</span><span class="muted">확신 ${a.confidence}</span></div>
      <div class="pb"><div>${esc(a.summary)}</div><ul>${a.key_points.map((k) => `<li>${esc(k)}</li>`).join("")}</ul></div></div>`;
  }).join("");
  const rk = r.risk, d = r.decision, [al, ac] = ACTION[d.action];
  const kv = (k, v, c = "") => `<span class="k">${k}</span><span class="${c}">${v}</span>`;
  const errs = [...new Set(Object.values(r.errors || {}).map((e) => e.replace(/^AI 실패 → [^:]+: /, "AI 실패 → 기본 규칙으로 대체: ")))];
  $("#agents-out").innerHTML = `${errs.length ? `<div class="help accent" style="margin-bottom:8px">${errs.map(esc).join("<br>")}</div>` : ""}<div class="cols-3">${cards}</div>
    <div class="cols-2" style="margin-top:12px">
      <div class="panel"><div class="ph"><span class="t">리스크 한도</span></div><div class="pb">
        <div class="kv">${kv("최대 레버리지", rk.max_leverage + "x")}${kv("권장 비중", rk.position_pct + "%")}${kv("이벤트 위험", rk.event_risk ? "있음" : "없음", rk.event_risk ? "down" : "")}</div>
        <div style="margin-top:8px">${esc(rk.summary)}</div><ul class="reasons">${rk.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div></div>
      <div class="panel"><div class="ph"><span class="t">최종 결정</span><div class="grow"></div>
        ${d.action !== "stay_flat" ? `<button class="pri sm" id="exec-decision">페이퍼 계좌로 주문</button>` : ""}</div><div class="pb">
        <div class="row"><span class="regime" style="padding:0;border:none"><span class="state ${d.action === "long" ? "long" : d.action === "short" ? "short" : "range"}">${al}</span></span>
          <span class="muted">확신 ${d.confidence}</span></div>
        ${d.action !== "stay_flat" ? `<div class="kv" style="margin-top:8px">${kv("진입", px(d.entry))}${kv("손절", px(d.stop_loss), "down")}
          ${kv("목표", d.take_profits.map(px).join(" → "), "up")}${kv("레버리지·비중", `${d.leverage}x · ${d.position_pct}%`)}</div>` : ""}
        <div style="margin-top:8px">${esc(d.rationale)}</div>
        ${d.invalidation ? `<div class="help" style="margin-top:6px">무효 조건: ${esc(d.invalidation)}</div>` : ""}</div></div></div>`;
  const ex = $("#exec-decision");
  if (ex) ex.onclick = () => busy(ex, async () => {
    await api("/api/agents/execute", { method: "POST", body: { symbol: state.symbol, decision: d } });
    toast("페이퍼 계좌에 주문했습니다", `${state.symbol} ${al}`);
  });
}

export function initAgents() {
  $("#agents-run").onclick = (e) => busy(e.target, run);
}
