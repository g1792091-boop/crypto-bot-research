"use strict";
// Experiment progress strip (every view) and today's summary card (순위표), from /api/summary.
// Uses the helpers of app.js ($, api, esc, fmt, idName, topHeight).
(function () {
  const DAY = 86400000;
  const kdate = (ms) => { const d = new Date(ms + 9 * 3600e3); return `${d.getUTCMonth() + 1}월 ${d.getUTCDate()}일`; };
  const usd = (x) => (x >= 0 ? "+$" : "-$") + fmt(Math.abs(x), 0);
  function render(v) {
    const bar = $("expbar");
    if (v.start == null) { bar.innerHTML = '<span>봇이 아직 첫 계좌를 만들지 않았습니다</span>'; }
    else {
      const cp = v.next_checkpoint, dleft = Math.max(0, Math.ceil((cp.ts - v.now) / DAY)), rs = v.restart;
      // the restart banner (server: checkpoint.run_facts / checkpoint_ts): '새 실험 D+n / 30 · 첫 판정 MM/DD'
      const parts = rs && rs.ready ? [`<b class="rs-banner">${esc(rs.text)}</b> (${kdate(v.start)} 시작, 판정 09:00 · D-${dleft})`]
        : [`실험 <b>${v.day}일째</b> (${kdate(v.start)} 시작)`,
          `${cp.k === 1 ? "첫" : cp.k + "번째"} 판정 <b>${kdate(cp.ts)} 09:00</b> (${cp.day}일째, D-${dleft})`];
      if (v.observing) parts.push(`관찰 기간 <b>${kdate(v.observe_until - 1)}까지</b> (복사 제안 없이 기록만, ${Math.ceil((v.observe_until - v.now) / DAY)}일 남음)`);
      else parts.push("관찰 기간 끝: 에이전트 제안 가능");
      bar.innerHTML = parts.map((p) => `<span>${p}</span>`).join("") + (rs && rs.rules_ko
        ? `<span class="rs-rules">규칙 변경 1: ${esc(rs.rules_ko)} · <a href="${esc(rs.doc)}" target="_blank" rel="noopener">원문 보기</a></span>` : "");
    }
    if (typeof topHeight === "function") topHeight();
    const t = v.today;
    $("today-at").textContent = `${kdate(t.since)} 0시부터`;
    $("today-tiles").innerHTML = [
      ["오늘 거래", t.trades, `매매법 계좌 ${t.strategy_trades}건`],
      ["매매법 계좌 손익", `<span class="${t.pnl >= 0 ? "up" : "down"}">${usd(t.pnl)}</span>`, `수수료·펀딩 포함, ${RUN.strategy_accounts}개 합계`],
      ["이긴 거래", t.strategy_trades ? `${Math.round(t.wins / t.strategy_trades * 100)}%` : "—", `${t.wins} / ${t.strategy_trades}`],
      ["강제청산", t.liquidations, "오늘 청산된 거래"],
    ].map(([k, val, s]) => `<div class="tile"><div class="k">${k}</div><div class="v">${val}</div><div class="s">${s}</div></div>`).join("");
    const li = (arr) => arr.map((r) => `<span title="${esc(r.account_id)}">${esc(idName(r.account_id))}</span> <span class="${r.pnl >= 0 ? "up" : "down"}">${usd(r.pnl)}</span>`).join(" · ") || "—";
    $("today-list").innerHTML = `<p class="muted">오늘 가장 잘한 계좌: ${li(t.best)}<br>오늘 가장 못한 계좌: ${li(t.worst)}</p>`;
  }
  async function load() {
    try { render(await api("/api/summary")); } catch (e) { /* login redirect or server down */ }
  }
  // the board's Korean names arrive with /api/board, after the first load
  document.querySelectorAll('#nav button[data-v="board"]').forEach((b) => b.addEventListener("click", load));
  load();
  setInterval(load, 60000);
})();
