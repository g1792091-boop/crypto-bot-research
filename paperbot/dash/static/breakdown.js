"use strict";
// By coin / weekday-weekend x session / windows / volatility spike (paperbot/breakdown.py via /api/breakdown).
// Read-only, descriptive; on the 순위표 view. Uses the helpers of app.js ($, api, esc, fmt).
(function () {
  const SES = {asia: "아시아 09~16시", europe: "유럽 16~22시", us: "미국 22~05시", dawn: "새벽 05~09시"};
  const WIN = {funding: "펀딩 정산 ±10분", us_open: "미국장 개장 ±1시간", macro: "미국 지표 시각(08:30 NY) ±30분"};
  const usd = (x) => (x == null ? "—" : (x >= 0 ? "+$" : "-$") + fmt(Math.abs(x), 0));
  const pc = (x) => (x == null ? "—" : Math.round(x * 100) + "%");
  const cell = (c) => c && c.n ? `${c.n}건 · 수익 ${pc(c.win_rate)} · <span class="${c.pnl >= 0 ? "up" : "down"}">${usd(c.pnl)}</span>${c.status === "ok" ? "" : ' <small class="muted">(표본 적음)</small>'}` : '<span class="muted">—</span>';
  function render(v) {
    $("bd-at").textContent = `거래 ${v.trades}건 · ${v.min_n}건 미만 칸은 결론 아님`;
    const coins = Object.entries(v.by_coin).map(([s, c]) => `<tr><td class="l">${esc(s)}</td><td class="l">${cell(c.strategies)}</td><td class="l">${cell(c.coin_flips)}</td>
      <td class="l"><small>${c.best.map((b) => `${esc(b.account)} ${usd(b.pnl)}`).join("<br>") || "—"}</small></td></tr>`).join("");
    let html = `<table><thead><tr><th class="l">코인</th><th class="l">매매법 계좌 전체</th><th class="l">동전 봇</th><th class="l">이 코인에서 잘 된 계좌 (${10}건 이상)</th></tr></thead><tbody>${coins}</tbody></table>`;
    if (v.sessions) {
      const p = v.sessions.primary;
      html += `<table><thead><tr><th class="l">시간대 (진입, 한국 시간)</th><th class="l">평일</th><th class="l">주말</th></tr></thead><tbody>` +
        Object.keys(SES).map((s) => `<tr><td class="l">${SES[s]}</td><td class="l">${cell(p.find((c) => c.day === "weekday" && c.session === s))}</td><td class="l">${cell(p.find((c) => c.day === "weekend" && c.session === s))}</td></tr>`).join("") + "</tbody></table>";
      html += `<table><thead><tr><th class="l">특별 시간</th><th class="l">그 시간에 진입</th><th class="l">그 밖</th></tr></thead><tbody>` +
        v.sessions.windows.map((w) => `<tr><td class="l">${WIN[w.window] || esc(w.window)}</td><td class="l">${cell(w.inside)}</td><td class="l">${cell(w.outside)}</td></tr>`).join("") + "</tbody></table>";
    }
    const vo = v.volatility;
    html += `<p>변동성 급등 때 진입: ${cell(vo.spike)} · 평소: ${cell(vo.normal)} <small class="muted">(판단 못 함 ${vo.unknown}건: 최근 30일 신호 50개 이상 필요)</small></p>
      <p class="muted">설명용 표입니다. 이 표로 계좌 규칙을 바꾸지 않습니다. 패턴이 보이면 에이전트가 5년치로 시험하고, 통과하면 새 계좌로 비교합니다.</p>`;
    $("bd-body").innerHTML = html;
  }
  async function load() {
    try { render(await api("/api/breakdown")); } catch (e) { /* login redirect or server down */ }
  }
  document.querySelectorAll('#nav button[data-v="board"]').forEach((b) => b.addEventListener("click", load));
  load();
  setInterval(load, 600000);
})();
