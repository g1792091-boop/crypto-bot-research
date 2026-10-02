"use strict";
// GH Coin call recorder (paperbot/ghcoin.py via /api/ghcoin): read-only, on the 순위표 view.
// Uses the helpers of app.js ($, api, esc, fmt).
(function () {
  const ST = {long: "롱 타점", short: "숏 타점", longWait: "롱 대기", shortWait: "숏 대기", wait: "관망"};
  const RES = {win: "익절1", loss: "손절", expire: "24시간 만료", flip: "반대 신호"};
  const r2 = (x) => (x == null ? "—" : (x >= 0 ? "+" : "") + Number(x).toFixed(2) + "R");
  function render(v) {
    const body = $("gh-body"), t = v.total || {};
    $("gh-at").textContent = `${v.alive ? "기록 중" : "멈춤 또는 시작 전"} · GH Coin ${esc((v.commit || "?").slice(0, 7))}`;
    let html = "";
    if (!t.calls) {
      html += `<p class="muted">끝난 타점이 아직 없습니다 (열린 타점 ${v.open || 0}개). GH Coin 규칙 그대로 5분마다 기록합니다.</p>`;
    } else {
      const res = Object.entries(t.results).map(([k, n]) => `${RES[k] || esc(k)} ${n}`).join(" · ");
      const good = t.p_coin_flip != null && t.p_coin_flip < 0.05;
      html += `<p>끝난 타점 <b>${t.calls}</b>개 (${res}) · 열린 타점 ${v.open}개</p>
        <p>합계 <b class="${t.net_r >= 0 ? "up" : "down"}">${r2(t.net_r)}</b> (수수료·미끄러짐 뒤, 수수료 전 ${r2(t.gross_r)}) ·
        같은 시각 동전 던지기 ${r2(t.coin_flip_net_r)} · p=${Number(t.p_coin_flip).toFixed(4)}
        <span class="tag ${good ? "acc" : ""}">${good ? "동전보다 낫다는 근거 있음" : "우연과 구별 안 됨"}</span></p>`;
      const rows = Object.entries(v.by_coin).filter(([, s]) => s.calls).map(([sym, s]) =>
        `<tr><td class="l">${esc(sym)}</td><td>${s.calls}</td><td>${(s.win_rate * 100).toFixed(0)}%</td><td>${r2(s.net_r)}</td><td>${r2(s.coin_flip_net_r)}</td></tr>`).join("");
      html += `<table><thead><tr><th class="l">코인</th><th>타점</th><th>수익 비율</th><th>합계(수수료 뒤)</th><th>동전 던지기</th></tr></thead><tbody>${rows}</tbody></table>`;
    }
    const coins = Object.entries((v.board || {}).coins || {});
    if (coins.length) {
      html += `<table><thead><tr><th class="l">코인</th><th class="l">지금 GH Coin 판단</th><th>5분</th><th>15분</th><th>1시간</th><th>4시간</th><th class="l">패턴(1시간)</th></tr></thead><tbody>` +
        coins.map(([sym, c]) => `<tr><td class="l">${esc(sym)}</td><td class="l">${esc(ST[c.state] || c.state)} <small class="muted">${esc(c.why || "")}</small></td>` +
          ["5", "15", "60", "240"].map((k) => `<td>${c.scores[k] == null ? "—" : Math.round(c.scores[k] * 100)}</td>`).join("") +
          `<td class="l"><small>${esc(((c.patterns || {})["60"] || []).map((p) => p.name).join(", ") || "—")}</small></td></tr>`).join("") + "</tbody></table>";
    }
    html += `<p class="muted">GH Coin 코드를 고치지 않고 서버에서 따로 돌린 기록입니다. 195개 paper 계좌와는 섞이지 않습니다. 손익 단위 R = 손절까지 거리.</p>`;
    body.innerHTML = html;
  }
  async function load() {
    try { render(await api("/api/ghcoin")); } catch (e) { /* login redirect or server down */ }
  }
  document.querySelectorAll('#nav button[data-v="board"]').forEach((b) => b.addEventListener("click", load));
  load();
  setInterval(load, 300000);
})();
