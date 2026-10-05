"use strict";
// Checkpoint verdicts (paperbot/checkpoint.py via /api/checkpoint): read-only, on the 순위표 view.
// Uses the helpers of app.js ($, api, esc, fmt, idName, state, TF_KO, JUDGED_BY_GROUP: the 36 and DeepSeek 15m / 30m / 1h,
// the reel 5m; paper v4: three verdict families with their own FDR, core 0.07 · DeepSeek 0.025 · reel 0.005).
(function () {
  const CK_TAG = {"2차 통과": "long", "1차 합격": "acc", "불합격": "bust", "보류": "", "관찰용": ""};
  let open = false;   // show every row (default: the judged ones only)
  const num = (x, d) => (x == null ? "—" : Number(x).toFixed(d));
  // Before the first verdict: how many of the judged accounts of each verdict family (checkpoint.py: the 36 and
  // DeepSeek on 15m / 30m / 1h, the reel on 5m; 4h and the coin flips only observed) have the 30 closed trades a
  // verdict needs, from the board. Counts only, never a pass/fail preview (and no P&L: DeepSeek's stays in its group).
  const FAMILIES = [["core", "strategy", "기존 36"], ["ds200", "ds200", "딥시크"], ["reel", "reel", "5분봉 단타"]];
  function progress() {
    const accts = (state.board || {}).accounts || [];
    const fams = FAMILIES.map(([g, kind, ko]) => {
      const tfs = JUDGED_BY_GROUP[g] || [];
      return {g, ko, tfs, list: accts.filter((a) => a.kind === kind && tfs.includes(a.timeframe))};
    }).filter((f) => f.list.length);
    const judged = fams.flatMap((f) => f.list);
    if (!judged.length) return "";
    const line = (f) => `${f.ko} <b>${f.list.filter((a) => a.trades >= 30).length}/${f.list.length}</b> (` +
      f.tfs.map((tf) => `${TF_KO[tf]} ${f.list.filter((a) => a.timeframe === tf && a.trades >= 30).length}`).join(" · ") + ")";
    return `<p><b>진행 상황, 판정 아님:</b> 판정 대상 ${judged.length}개(4시간봉과 동전 봇은 관찰용) 중 지금까지 끝난 거래가
      30건 이상인 계좌 <b>${judged.filter((a) => a.trades >= 30).length}개</b>: ${fams.map(line).join(" · ")}.</p>
      <p class="muted">거래 수만 센 것입니다. 합격·불합격은 판정일에 계좌마다 같은 조건의 동전 봇과 비교해서 정하고(그룹마다 따로 보정:
      기존 36 · 딥시크 · 5분봉 단타), 그때 30건이 안 된 계좌는 "보류"입니다.</p>`;
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
    const tr = rows.map((r) => `<tr><td class="l" title="${esc(r.account_id)}">${esc(idName(r.account_id))}${r.group && r.group !== "core" ? ` <small class="muted">${esc((typeof GROUP_ROW_KO === "object" && GROUP_ROW_KO[r.group]) || r.group)}</small>` : ""}</td><td class="l"><span class="tag ${CK_TAG[r.status] || ""}">${esc(r.status)}</span>${r.stage ? ` <small class="muted">${esc(r.stage)}</small>` : ""}</td>
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
