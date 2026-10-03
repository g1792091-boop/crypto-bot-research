"use strict";
// Checkpoint verdicts (paperbot/checkpoint.py via /api/checkpoint): read-only, on the 순위표 view.
// Uses the helpers of app.js ($, api, esc, fmt, idName, state, TF_KO).
(function () {
  const CK_TAG = {"2차 통과": "long", "1차 합격": "acc", "불합격": "bust", "보류": "", "관찰용": ""};
  let open = false;   // show every row (default: the judged ones only)
  const num = (x, d) => (x == null ? "—" : Number(x).toFixed(d));
  // Before the first verdict: how many of the judged accounts (the strategies' accounts, 4h only observed) have
  // the 30 closed trades a verdict needs, from the board. A count only, never a pass/fail preview.
  function progress() {
    const judged = ((state.board || {}).accounts || []).filter((a) => a.kind === "strategy" && a.timeframe !== "4h");
    if (!judged.length) return "";
    const tfs = ["5m", "15m", "30m", "1h"].map((tf) => `${TF_KO[tf]} ${judged.filter((a) => a.timeframe === tf && a.trades >= 30).length}`);
    return `<p><b>진행 상황, 판정 아님:</b> 판정 대상 ${judged.length}개(매매법 계좌, 4시간봉은 관찰용) 중 지금까지 끝난 거래가
      30건 이상인 계좌 <b>${judged.filter((a) => a.trades >= 30).length}개</b> (${tfs.join(" · ")}).</p>
      <p class="muted">거래 수만 센 것입니다. 합격·불합격은 판정일에 계좌마다 동전 봇 2,000개와 비교해서 정하고, 그때 30건이 안 된 계좌는 "보류"입니다.</p>`;
  }
  function render(v) {
    const body = $("ckpt-body");
    if (!v.ready) {
      $("ckpt-at").textContent = "";
      body.innerHTML = '<p class="muted">아직 판정이 없습니다. 첫 판정은 시작 후 30일째 09:00(한국)입니다.</p>' + progress();
      return;
    }
    const c = v.counts;
    $("ckpt-at").textContent = `${v.day}일째 · ${v.date} 09:00 · 스냅샷 ${v.snapshot_sha256.slice(0, 12)}`;
    const head = `<p>1차 합격 <b>${c["1차 합격"]}</b> · 2차 통과 <b>${c["2차 통과"]}</b> · 불합격 ${c["불합격"]} · 보류 ${c["보류"]} · 관찰용 ${c["관찰용"]}</p>
      <p class="muted">우연 기준: 계좌마다 동전 봇 ${fmt(v.n_bots, 0)}개와 비교, FDR ${Math.round(v.alpha * 100)}% 보정. 검정 ${v.tested}개 중 통과 ${v.luck_passed}개,
      우연으로 기대되는 합격 수 ≤ ${num(v.lucky_expected, 1)}개 (보정 없이였다면 ${num(v.lucky_if_uncorrected, 1)}개).</p>` +
      (v.warnings.length ? `<p class="down">${v.warnings.map(esc).join("<br>")}</p>` : "");
    const rows = v.rows.filter((r) => open || (r.status !== "보류" && r.status !== "관찰용"));
    const tr = rows.map((r) => `<tr><td class="l" title="${esc(r.account_id)}">${esc(idName(r.account_id))}</td><td class="l"><span class="tag ${CK_TAG[r.status] || ""}">${esc(r.status)}</span>${r.stage ? ` <small class="muted">${esc(r.stage)}</small>` : ""}</td>
      <td>${r.trades ?? "—"}</td><td>${r.equity == null ? "—" : "$" + fmt(r.equity, 0)}</td><td>${num(r.p, 4)}</td><td>${num(r.q, 3)}</td>
      <td class="l"><small>${esc(r.reason)}</small></td></tr>`).join("");
    body.innerHTML = head + `<table><thead><tr><th class="l">계좌</th><th class="l">판정</th><th>거래</th><th>평가금</th><th>p</th><th>보정 q</th><th class="l">이유</th></tr></thead>
      <tbody>${tr || '<tr><td colspan="7" class="muted l">판정한 계좌 없음 (모두 보류·관찰용)</td></tr>'}</tbody></table>
      <p><button id="ckpt-all">${open ? "판정한 계좌만" : `전체 ${v.rows.length}개 보기`}</button></p>`;
    $("ckpt-all").onclick = () => { open = !open; render(v); };
  }
  async function load() {
    try { render(await api("/api/checkpoint")); } catch (e) { /* login redirect or server down: the board shows it */ }
  }
  document.querySelectorAll('#nav button[data-v="board"]').forEach((b) => b.addEventListener("click", load));
  load();
  setInterval(load, 600000);
})();
