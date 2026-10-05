"use strict";
// Experiment progress strip (every view) and today's summary card (순위표), from /api/summary.
// Uses the helpers of app.js ($, api, esc, fmt, idName, topHeight, state, inView, GROUP_ROW_KO, RUN).
// Today's numbers follow the 순위표's group switch (today.by_group): the DeepSeek P&L only in its own view (D11).
(function () {
  const DAY = 86400000;
  const kdate = (ms) => { const d = new Date(ms + 9 * 3600e3); return `${d.getUTCMonth() + 1}월 ${d.getUTCDate()}일`; };
  const usd = (x) => (x >= 0 ? "+$" : "-$") + fmt(Math.abs(x), 0);
  let last = null;
  // the groups the switch shows (app.js inView): "main" = the 36, the reel and the extras; "5분봉" = the reel's own
  // numbers (its 5m coin flips are the yardstick, counted under 동전 봇)
  const shownGroups = () => typeof inView !== "function" ? ["core", "reel", "extra"]
    : ["core", "ds200", "reel", "flip", "extra"].filter((g) => inView({group: g, timeframe: ""}));
  function render(v) {
    last = v;
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
        ? `<span class="rs-rules">${esc(rs.rules_label || "규칙")}: ${esc(rs.rules_ko)} · <a href="${esc(rs.doc)}" target="_blank" rel="noopener">원문 보기</a></span>` : "");
    }
    if (typeof topHeight === "function") topHeight();
    const t = v.today;
    $("today-at").textContent = `${kdate(t.since)} 0시부터`;
    const li = (arr) => arr.map((r) => `<span title="${esc(r.account_id)}">${esc(idName(r.account_id))}</span> <span class="${r.pnl >= 0 ? "up" : "down"}">${usd(r.pnl)}</span>`).join(" · ") || "—";
    const by = t.by_group;
    if (!by) {      // an older server: the 36's numbers as before
      $("today-tiles").innerHTML = [
        ["오늘 거래", t.trades, `매매법 계좌 ${t.strategy_trades}건`],
        ["매매법 계좌 손익", `<span class="${t.pnl >= 0 ? "up" : "down"}">${usd(t.pnl)}</span>`, `수수료·펀딩 포함, ${RUN.strategy_accounts}개 합계`],
        ["이긴 거래", t.strategy_trades ? `${Math.round(t.wins / t.strategy_trades * 100)}%` : "—", `${t.wins} / ${t.strategy_trades}`],
        ["강제청산", t.liquidations, "오늘 청산된 거래"],
      ].map(([k, val, s]) => `<div class="tile"><div class="k">${k}</div><div class="v">${val}</div><div class="s">${s}</div></div>`).join("");
      $("today-list").innerHTML = `<p class="muted">오늘 가장 잘한 계좌: ${li(t.best)}<br>오늘 가장 못한 계좌: ${li(t.worst)}</p>`;
      return;
    }
    const gs = shownGroups().filter((g) => by[g]);
    const sum = (k) => gs.reduce((s, g) => s + (by[g][k] || 0), 0);
    const n = sum("trades"), pnl = sum("pnl"), wins = sum("wins");
    const label = gs.map((g) => (typeof GROUP_ROW_KO === "object" && GROUP_ROW_KO[g]) || g).join(" · ");
    $("today-tiles").innerHTML = [
      ["오늘 거래", n, label],
      ["손익", `<span class="${pnl >= 0 ? "up" : "down"}">${usd(pnl)}</span>`, "수수료·펀딩 포함, 고른 그룹 합계"],
      ["이긴 거래", n ? `${Math.round(wins / n * 100)}%` : "—", `${wins} / ${n}`],
      ["강제청산", sum("liquidations"), `고른 그룹 · 모든 그룹 ${t.liquidations}건`],
    ].map(([k, val, s]) => `<div class="tile"><div class="k">${k}</div><div class="v">${val}</div><div class="s">${s}</div></div>`).join("");
    const lines = gs.length === 1 ? [[by[gs[0]].best, by[gs[0]].worst]] : [[t.best, t.worst]];
    const other = ["core", "ds200", "reel", "flip", "extra"].filter((g) => by[g] && by[g].trades && !gs.includes(g))
      .map((g) => `${(typeof GROUP_ROW_KO === "object" && GROUP_ROW_KO[g]) || g} ${by[g].trades}건`);
    $("today-list").innerHTML = `<p class="muted">오늘 가장 잘한 계좌: ${li(lines[0][0])}<br>오늘 가장 못한 계좌: ${li(lines[0][1])}` +
      (other.length ? `<br>다른 그룹 거래(손익은 그 그룹을 고르면): ${other.join(" · ")}` : "") + "</p>";
  }
  // the 순위표's group switch redraws today's numbers at once
  document.addEventListener("pb-group", () => { if (last) render(last); });
  async function load() {
    try { render(await api("/api/summary")); } catch (e) { /* login redirect or server down */ }
  }
  // the board's Korean names arrive with /api/board, after the first load
  document.querySelectorAll('#nav button[data-v="board"]').forEach((b) => b.addEventListener("click", load));
  load();
  setInterval(load, 60000);
})();
