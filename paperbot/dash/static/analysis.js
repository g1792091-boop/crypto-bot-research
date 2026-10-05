"use strict";
// 분석 tab (/api/analysis/*, paperbot/dash/analysis.py) and the 24-hour debate room under 회의실 (/api/debate).
// Read-only views of the numbers the agents' code computes; every view says how many trades it stands on and,
// where they are few, that the numbers can be chance. Nothing here changes an account.
// Uses app.js helpers ($, api, esc, fmt, tsKo, idName, coin, alertKo, state, TF_KO).
(function () {
  const ROUTE = {health: "health", risk: "risk", ready: "readiness", shock: "shock", map: "map", entry: "entry",
    synergy: "synergy", levrule: "levrule", shadows: "shadows", questions: "questions", alerts: "alerts"};
  const an = {tab: "health", data: {}, busy: {}, retry: null, alertLevel: "", curveSet: "lev", shadowAcct: "", charts: []};
  try { const t = localStorage.getItem("pb-an-tab"); if (t && ROUTE[t]) an.tab = t; } catch (e) { /* storage blocked */ }
  const pc = (x, d = 0) => (x == null || isNaN(x) ? "—" : (x * 100).toFixed(d) + "%");
  const pcs = (x, d = 1) => (x == null || isNaN(x) ? "—" : (x > 0 ? "+" : "") + (x * 100).toFixed(d) + "%");
  const usd = (x) => (x == null || isNaN(x) ? "—" : (x < 0 ? "-$" : "+$") + fmt(Math.abs(x), 0));
  const num = (x, d = 2) => (x == null || isNaN(x) ? "—" : Number(x).toFixed(d));
  const ucls = (x) => (x == null ? "" : x > 0 ? "up" : x < 0 ? "down" : "");
  const ago = (s) => s == null ? "—" : s < 90 ? `${Math.round(s)}초 전` : s < 5400 ? `${Math.round(s / 60)}분 전` : s < 172800 ? `${Math.round(s / 3600)}시간 전` : `${Math.round(s / 86400)}일 전`;
  const tile = (k, v, s, c = "") => `<div class="tile"><div class="k">${k}</div><div class="v ${c}">${v}</div><div class="s">${s || ""}</div></div>`;
  const small = (on) => (on ? ' <small class="muted">(표본 적음)</small>' : "");
  // one caution line wherever the sample is thin
  const thin = (n, need, what) => (n == null || n < need
    ? `<p class="an-warn">표본이 적습니다: ${what} ${n || 0}건 (${need}건 미만). 숫자가 우연일 수 있어 여기서 결론을 내리지 않습니다.</p>` : "");
  const head = (title, sub) => `<div class="an-h"><b>${title}</b>${sub ? `<span class="muted">${sub}</span>` : ""}</div>`;
  const section = (title, body, sub) => `<div class="card"><div class="ph"><span class="t">${title}</span>${sub ? `<span class="grow"></span><small class="muted">${sub}</small>` : ""}</div><div class="body">${body}</div></div>`;

  // ------------------------------------------------------------ data
  async function load(force) {
    const t = an.tab;
    if (an.busy[t]) return;
    if (force || !an.data[t]) render();
    an.busy[t] = true;
    try {
      an.data[t] = await api("/api/analysis/" + ROUTE[t] + (t === "shadows" && an.shadowAcct ? "?account=" + encodeURIComponent(an.shadowAcct) : ""));
    } catch (e) {
      an.data[t] = {error: "불러오지 못했습니다 (로그인이 끝났거나 서버가 응답하지 않음)"};
    }
    an.busy[t] = false;
    if (an.tab === t && state.view === "analysis") render();
    clearTimeout(an.retry);
    if (an.data[t] && an.data[t].pending) an.retry = setTimeout(() => { if (an.tab === t && state.view === "analysis") load(); }, 5000);
  }
  function render() {
    const d = an.data[an.tab], el = $("an-body");
    $("an-at").textContent = d && d.computed_at ? `${tsKo(d.computed_at)} 계산${d.stale ? " (예전 값, 다시 계산 중)" : ""}` : "";
    an.charts.forEach((c) => c.remove()); an.charts = [];
    if (!d) { el.innerHTML = '<p class="empty">불러오는 중…</p>'; return; }
    if (d.pending) { el.innerHTML = `<p class="empty">${esc(d.note || "계산 중입니다")}</p>`; return; }
    if (d.unavailable) { el.innerHTML = `<p class="empty">준비 중입니다. ${esc(d.note || "")}</p>`; return; }
    if (d.error) { el.innerHTML = `<p class="empty">${esc(d.error)}</p>`; return; }
    try {
      el.innerHTML = ({health: rHealth, risk: rRisk, ready: rReady, shock: rShock, map: rMap, entry: rEntry,
        synergy: rSynergy, levrule: rLevrule, shadows: rShadows, questions: rQuestions, alerts: rAlerts})[an.tab](d);
      if (an.tab === "shadows") drawCurves(d);
    } catch (e) {
      console.error(e);
      el.innerHTML = '<p class="empty">이 화면을 그리지 못했습니다 (자료 모양이 바뀌었을 수 있음)</p>';
    }
    bind(el);
  }
  function bind(el) {
    el.querySelectorAll("button[data-lv]").forEach((b) => b.onclick = () => { an.alertLevel = b.dataset.lv; render(); });
    el.querySelectorAll("[data-acct]").forEach((b) => b.onclick = () => { if (typeof openAccount === "function") openAccount(b.dataset.acct); });
    el.querySelectorAll("button[data-cset]").forEach((b) => b.onclick = () => { an.curveSet = b.dataset.cset; render(); });
    const pick = el.querySelector("#an-curve-acct");
    if (pick) pick.onchange = () => { an.shadowAcct = pick.value; delete an.data.shadows; load(true); };
  }

  // ------------------------------------------------------------ ① 건강 점검
  function rHealth(d) {
    const lv = {ok: ["모두 정상", "up"], warn: ["확인할 것이 있습니다", "accent"], bad: ["문제가 있습니다", "down"]}[d.level] || ["—", ""];
    let h = `<div class="an-status ${lv[1]}"><b>● ${lv[0]}</b><span class="muted">${tsKo(d.now)} 기준</span></div>`;
    if (d.problems && d.problems.length) h += `<ul class="an-list down">${d.problems.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
    if (d.warnings && d.warnings.length) h += `<ul class="an-list accent">${d.warnings.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
    const b = d.bot || {}, ag = d.agents || {}, n = d.nightly || {}, cp = d.checkpoint || {}, u = d.usage, lq = d.liq_recorder;
    const tiles = [];
    tiles.push(b.ready ? tile("봇 생존 신호", b.alive ? "정상" : "멈춤", ago(b.heartbeat_age_s), b.alive ? "up" : "down")
      : tile("봇 생존 신호", "없음", "paper3.db를 열지 못함", "down"));
    if (b.ready) {
      tiles.push(tile("1분봉 (시세 자료)", b.data_age_s == null ? "—" : b.data_fresh ? "들어옴" : "끊김",
        b.data_age_s == null ? "기록 없음" : `마지막 봉 ${ago(b.data_age_s)}`, b.data_age_s == null ? "" : b.data_fresh ? "up" : "down"));
      tiles.push(tile("신호 (24시간)", fmt(b.signals_24h, 0), `늦음 ${b.signals_late_24h || 0}건 · 평균 지연 ${b.avg_delay_s == null ? "—" : b.avg_delay_s + "초"}`));
      const al = b.alerts_24h || {};
      tiles.push(tile("경고 (24시간)", `${al.CRITICAL || 0} / ${al.WARN || 0}`, "긴급 / 주의", al.CRITICAL ? "down" : al.WARN ? "accent" : ""));
    }
    tiles.push(!ag.configured ? tile("에이전트", "설정 안 됨", "agents3.db 경로 없음")
      : tile("에이전트", ag.tick_age_s == null ? "기록 없음" : ag.tick_age_s > 2700 ? "멈춤" : ag.last_tick && ag.last_tick.ok === false ? "실패" : "도는 중",
        `마지막 점검 ${ago(ag.tick_age_s)}${ag.ai && ag.ai.failed ? ` · AI 연속 실패 ${ag.ai.failed}` : ""}`,
        ag.tick_age_s != null && ag.tick_age_s <= 2700 && !(ag.last_tick && ag.last_tick.ok === false) ? "up" : "down"));
    if (n.ready) {
      const p = n.parity || {};
      const okN = p.accounts != null ? p.accounts - (p.mismatched_accounts || 0) - (p.crash_gaps || 0) - (p.early_kline || 0) : null;
      tiles.push(tile(`밤 점검 (${esc(n.day)})`, p.accounts != null ? `${okN}/${p.accounts}` : "재계산 못 함",
        (p.mismatched_accounts ? `<span class="down">불일치 ${p.mismatched_accounts}</span>` : "재계산 일치") +
        (p.early_kline ? ` · <span class="accent" title="거래소 1분봉이 확정되기 전에 읽은 차이: 계산 오류 아님">early_kline ${p.early_kline}</span>` : "") +
        (n.missing_bars ? ` · 빠진 1분봉 ${n.missing_bars}` : ""), p.mismatched_accounts ? "down" : "up"));
    } else tiles.push(tile("밤 점검", "기록 없음", esc(n.why || "")));
    const nx = cp.next;
    tiles.push(tile("체크포인트 판정", cp.ready ? esc(cp.date) : nx ? `D-${Math.max(0, Math.ceil((nx.ts - d.now) / 864e5))}` : "—",
      cp.ready ? Object.entries(cp.counts || {}).map(([k, v]) => `${esc(k)} ${v}`).join(" · ")
        : nx ? `첫 판정 ${tsKo(nx.ts)} (${nx.day}일째)${cp.run_day ? ` · 지금 ${cp.run_day}일째` : ""}` : "아직 시작 전"));
    if (u) tiles.push(tile("AI 사용 (오늘)", `${fmt(u.calls, 0)}${u.cap_calls ? ` / ${fmt(u.cap_calls, 0)}` : ""}`,
      `토큰 ${fmt(u.tokens, 0)} · 7일 ${u.week ? fmt(u.week.calls, 0) : "—"}번`));
    if (lq) tiles.push(tile("강제청산 기록기", lq.age_s == null ? "기록 없음" : lq.age_s < 3600 ? "도는 중" : "조용함", ago(lq.age_s)));
    h += `<div class="tiles">${tiles.join("")}</div>`;
    if (cp.last_job) h += `<p class="muted">체크포인트 작업 마지막 기록 ${tsKo(cp.last_job.ts)}: ${esc(cp.last_job.text)}</p>`;
    if ((d.job_failures || []).length) h += `<p class="muted">예약 작업 실패 경고(그날 첫 번): ${d.job_failures.map((f) => `${esc(f.job_ko)} ${esc(f.day)}`).join(" · ")}</p>`;
    h += '<p class="muted">각 부분은 따로 읽습니다: 하나가 없어도 나머지는 보입니다. 경고 원문은 \'알림 기록\'에 있습니다.</p>';
    return h;
  }

  // ------------------------------------------------------------ ② 손익비·위험
  function rrRow(label, r) {
    if (!r || !r.trades) return `<tr><td class="l" data-k="">${label}</td><td colspan="6" class="l muted">끝난 거래 없음</td></tr>`;
    return `<tr><td class="l name">${label}${small(r.small)}</td><td data-k="거래">${fmt(r.trades, 0)}</td><td data-k="승률">${pc(r.win_rate)}</td>
      <td data-k="손익비">${num(r.payoff)}</td><td data-k="본전 승률">${pc(r.breakeven_win_rate)}</td>
      <td data-k="차이" class="${ucls(r.gap_pp)}">${r.gap_pp == null ? "—" : (r.gap_pp > 0 ? "+" : "") + r.gap_pp + "%p"}</td>
      <td data-k="거래당 평균(자금 대비)" class="${ucls(r.expectancy_eq)}">${pcs(r.expectancy_eq, 2)}</td></tr>`;
  }
  function rRisk(d) {
    const a = d.all || {}, f = d.coin_flips || {}, dd = d.drawdown || {}, g = a.giveback || {};
    let h = head("손익비와 낙폭 · 매매법 계좌 전체", `끝난 거래 ${fmt(d.trades, 0)}건 · 동전 봇 ${fmt(d.flip_trades, 0)}건`);
    h += thin(d.trades, 30, "매매법 계좌 끝난 거래");
    h += `<div class="card scroll"><table class="cards"><thead><tr><th class="l"></th><th>거래</th><th>승률</th><th title="평균 이익 ÷ |평균 손실| (자금 대비)">손익비</th>
      <th title="이 손익비라면 이만큼 이겨야 본전">본전 승률</th><th title="실제 승률 − 본전 승률">차이</th><th>거래당 평균</th></tr></thead>
      <tbody>${rrRow("매매법 계좌 전체", a)}${rrRow("동전 봇 (같은 규칙, 무작위 진입)", f)}</tbody></table></div>`;
    h += `<p class="muted">차이가 플러스면 실제 승률이 본전 승률보다 높아 남는 쪽입니다. 지금 규칙(손절 ${esc(d.rules && d.rules.stop_atr)} ATR, 레버리지 ${esc(d.rules && d.rules.leverage)}, 최고 ROE +${pc(d.rules && d.rules.first_trigger)}에서 +${pc(d.rules && d.rules.first_lock)} 잠금)은 손익비가 낮고 본전 승률이 높게 나오는 것이 설계상 자연스럽습니다.</p>`;
    if (g.winners) h += `<p>이긴 거래 ${fmt(g.winners, 0)}건: 거래 중 최고 ROE 평균 <b>${pcs(g.mean_best_roe)}</b> → 실제 <b>${pcs(g.mean_roe)}</b> (최고점의 <b>${pc(g.kept_share)}</b>를 지킴, 나머지는 돌려줌).
      ${a.losers_reached_first_lock != null ? `진 거래 중 첫 잠금 발동선까지 갔다가 진 것 ${fmt(a.losers_reached_first_lock, 0)}건.` : ""}</p>`;
    // drawdown and bust probability
    const tfRows = Object.entries(dd.timeframes || {}).map(([tf, x]) => ddRow(TF_KO[tf] || tf, x)).join("");
    h += section("낙폭·파산 위험", `<p class="muted">봉별 = 그 봉의 매매법 계좌 36개를 합친 자금 곡선. 파산 확률 = 계좌마다 지금까지 끝난 거래를 다시 뽑아 앞으로 ${dd.horizon_days || 30}일을 ${fmt(dd.paths || 10000, 0)}번 흉내 냈을 때 파산선 아래로 간 비율(거래 ${dd.min_trades || 20}건 이상 계좌만, 가장 높은 계좌). 예측이 아니라 설명용입니다.</p>
      <p>흉내 낸 계좌 <b>${fmt(dd.simulated, 0)}</b>개 · 거래가 적어 못 한 계좌 ${fmt(dd.too_few, 0)}개 · 파산 확률 5% 이상 <b class="${dd.p_bust_over_5pct ? "down" : ""}">${fmt(dd.p_bust_over_5pct, 0)}</b>개 · -50% 확률 10% 이상 ${fmt(dd.p_dd50_over_10pct, 0)}개 · 이미 파산 <b class="${(dd.busted || []).length ? "down" : ""}">${(dd.busted || []).length}</b>개</p>
      ${!dd.simulated ? '<p class="an-warn">아직 거래 20건이 넘은 계좌가 없어 파산 확률을 계산하지 않았습니다.</p>' : ""}
      <div class="scroll"><table class="cards"><thead><tr><th class="l">봉</th><th>거래</th><th>지금 낙폭</th><th>최대 낙폭</th><th>파산 확률(최고)</th><th>파산 계좌</th></tr></thead>
      <tbody>${tfRows}${ddRow("동전 봇", dd.coin_flips || {})}</tbody></table></div>`);
    // per strategy
    const ss = (d.strategies || []).map((s) => `<tr><td class="l name">${esc(s.name_ko)}${small(s.small)}</td><td data-k="거래">${fmt(s.trades, 0)}</td>
      <td data-k="승률">${pc(s.win_rate)}</td><td data-k="손익비">${num(s.payoff)}</td><td data-k="본전 승률">${pc(s.breakeven_win_rate)}</td>
      <td data-k="차이" class="${ucls(s.gap_pp)}">${s.gap_pp == null ? "—" : (s.gap_pp > 0 ? "+" : "") + s.gap_pp + "%p"}</td>
      <td data-k="최대 낙폭">${s.max_dd_pct ? "-" + pc(s.max_dd_pct, 1) : "—"}</td>
      <td data-k="파산 확률" class="${s.p_bust_max && s.p_bust_max.p >= 0.05 ? "down" : ""}">${s.p_bust_max ? pc(s.p_bust_max.p, 1) : "—"}</td></tr>`).join("");
    h += section("매매법별", ss ? `<div class="scroll"><table class="cards"><thead><tr><th class="l">매매법 (5개 봉 합계)</th><th>거래</th><th>승률</th><th>손익비</th><th>본전 승률</th><th>차이</th><th>최대 낙폭</th><th>파산 확률</th></tr></thead><tbody>${ss}</tbody></table></div>
      <p class="muted">거래 ${d.small_n || 10}건 미만 매매법은 '표본 적음': 우연일 수 있습니다. ${esc(d.label || "")}</p>` : '<p class="muted">끝난 거래가 없습니다.</p>');
    return h;
  }
  function ddRow(label, x) {
    if (!x || !x.trades && !x.max_dd_pct) return `<tr><td class="l name">${label}</td><td colspan="5" class="l muted">기록 없음</td></tr>`;
    return `<tr><td class="l name">${label}</td><td data-k="거래">${fmt(x.trades, 0)}</td><td data-k="지금 낙폭">${x.dd_now_pct ? "-" + pc(x.dd_now_pct, 1) : "0%"}</td>
      <td data-k="최대 낙폭">${x.max_dd_pct ? "-" + pc(x.max_dd_pct, 1) : "—"}</td>
      <td data-k="파산 확률(최고)" class="${x.p_bust_max && x.p_bust_max.p >= 0.05 ? "down" : ""}">${x.p_bust_max ? pc(x.p_bust_max.p, 1) : "—"}</td>
      <td data-k="파산 계좌">${x.busted || 0}</td></tr>`;
  }

  // ------------------------------------------------------------ ③ 실전 준비도
  const MARK_CLS = {"✅": "up", "❌": "down"};
  function rReady(d) {
    const s = d.summary || {}, conds = d.conditions || [];
    let h = head(esc(s.headline || "실거래 조건"), `계좌 ${fmt(s.accounts, 0)}개 · ${s.days_running ?? "—"}일째 · ${esc(d.label || "")}`);
    h += `<p class="an-warn">표시만 합니다: 이 표는 아무것도 켜거나 바꾸지 않고, 실거래는 두 분이 정합니다. 체크포인트 판정 전에는 대부분 '아직 판단 불가'입니다.</p>`;
    if (s.q6_6) h += `<p><b>${esc(s.q6_6)}</b></p>`;
    const bc = s.by_condition || {};
    h += `<div class="card scroll"><table class="cards"><thead><tr><th class="l">#</th><th class="l">조건 (문서 그대로)</th><th>✅</th><th>❌</th><th>?</th></tr></thead><tbody>` +
      conds.map((c, i) => { const v = bc[c.id] || {}; return `<tr><td class="l muted" data-k="순서">${i + 1}</td><td class="l name">${esc(c.label)}<br><small class="muted">"${esc(c.quote)}" · ${esc(c.doc)}${c.line ? ":" + c.line : ""}</small></td>
        <td data-k="✅" class="up">${v["✅"] || 0}</td><td data-k="❌" class="down">${v["❌"] || 0}</td><td data-k="?">${v["아직 판단 불가"] || 0}</td></tr>`; }).join("") + "</tbody></table></div>";
    const order = d.order || [];
    const marks = (m) => [...(m || "")].map((x, i) => `<span class="${MARK_CLS[x] || "muted"}" title="${esc((conds[i] || {}).label || "")}">${x}</span>`).join("");
    h += section("조건에 가장 가까운 계좌", `<p class="muted">표시 순서: ${conds.map((c, i) => `${i + 1} ${esc(c.label)}`).join(" · ")}. ✅ 충족 · ❌ 아님 · ? 아직 판단 불가</p>
      <div class="scroll"><table class="cards"><thead><tr><th class="l">계좌</th><th>거래</th><th>손익</th><th class="l">조건</th><th>충족</th></tr></thead><tbody>` +
      (d.accounts || []).map((r) => `<tr class="click" data-acct="${esc(r.account)}"><td class="l name">${esc(r.name_ko)} · ${esc(TF_KO[r.timeframe] || r.timeframe)}${r.bust ? ' <span class="tag bust">파산</span>' : ""}</td>
        <td data-k="거래">${fmt(r.trades, 0)}${r.trades < 30 ? ' <small class="muted">(적음)</small>' : ""}</td><td data-k="손익" class="${ucls(r.pnl)}">${usd(r.pnl)}</td>
        <td class="l an-marks" data-k="조건" title="${esc(order.map((k) => (r.conditions[k] || {}).why).filter(Boolean).join(" / "))}">${marks(r.marks)}</td>
        <td data-k="충족">${r.met}/${r.of}</td></tr>`).join("") +
      `</tbody></table></div>${d.accounts_total > (d.accounts || []).length ? `<p class="muted">외 ${d.accounts_total - d.accounts.length}개 계좌</p>` : ""}`);
    return h;
  }

  // ------------------------------------------------------------ ④ 충격 테스트
  function rShock(d) {
    const shocks = d.shocks || [];
    let h = head("가격이 한 번에 움직이면", `지금 열린 포지션 ${fmt(d.open_positions, 0)}개 · 매매법 계좌 평가 자금 $${fmt(d.equity_total, 0)} · ${esc(d.label || "")}`);
    if (!d.open_positions) h += '<p class="an-warn">지금 열린 포지션이 없어 충격을 받을 것이 없습니다 (모든 칸이 0).</p>';
    else if (d.open_positions < 10) h += `<p class="an-warn">열린 포지션이 ${d.open_positions}개뿐이라 숫자가 작고, 포지션이 바뀌면 크게 달라집니다.</p>`;
    const by = {};
    (d.rows || []).forEach((r) => { (by[r.coin] = by[r.coin] || {})[r.shock] = r; });
    const coins = Object.keys(by).sort((a, b) => (a === "ALL" ? -1 : b === "ALL" ? 1 : a.localeCompare(b)));
    const cell = (r) => !r ? "—" : `<span class="${ucls(r.change_usd)}">${usd(r.change_usd)}</span><br><small class="muted">${pcs(r.share_of_equity, 2)}${r.liquidated ? ` · 청산 ${r.liquidated}` : ""}${r.stopped ? ` · 손절 ${r.stopped}` : ""}${r.busted ? ` · <b class="down">파산 ${r.busted}</b>` : ""}</small>`;
    h += `<div class="card scroll"><table class="an-grid"><thead><tr><th class="l">코인 (포지션)</th>${shocks.map((s) => `<th>${pcs(s, 0)}</th>`).join("")}</tr></thead><tbody>` +
      coins.map((c) => { const any = Object.values(by[c])[0] || {}; return `<tr><td class="l"><b>${c === "ALL" ? "전체" : esc(c)}</b> <small class="muted">${any.positions || 0}개</small></td>${shocks.map((s) => `<td>${cell(by[c][s])}</td>`).join("")}</tr>`; }).join("") +
      "</tbody></table></div>";
    const ex = Object.entries(d.exposure || {});
    if (ex.length) h += `<p class="muted">지금 노출: ${ex.map(([c, e]) => `${esc(c)} 롱 ${e.long}·숏 ${e.short} (증거금 $${fmt(e.margin, 0)})`).join(" · ")}</p>`;
    h += '<p class="muted">갭으로 본 계산입니다: 청산가를 지나면 증거금 전부, 손절선을 지나면 손절가가 아니라 충격 뒤 가격에 체결(수수료·슬리피지 포함). 실제 급변은 여러 번에 나눠 움직여 다를 수 있습니다. 설명용, 판정 아님.</p>';
    return h;
  }

  // ------------------------------------------------------------ ⑤ 코인·장세·변동성·요일 지도
  const GROUPS = [["by_coin", "코인"], ["by_regime", "진입 때 장세"], ["by_session", "시간대 (한국)"], ["by_weekday", "평일·주말"],
    ["by_side", "방향"], ["by_timeframe", "봉"]];
  const VOL_KO = {low: "낮음", mid: "보통", high: "높음", unknown: "모름"};
  function cmpCell(c) {
    if (!c || !c.trades) return '<span class="muted">—</span>';
    return `${fmt(c.trades, 0)}건 · ${pc(c.win_rate)} · <span class="${ucls(c.pnl)}">${usd(c.pnl)}</span>${small(c.small)}`;
  }
  function rMap(d) {
    const s = d.strategy || {}, f = d.coin_flips || {};
    let h = head("어디서 벌고 어디서 잃었나", `최근 끝난 거래 최대 ${fmt(d.cap, 0)}건 기준 · 매매법 ${fmt(s.trades || 0, 0)}건 · 동전 봇 ${fmt(f.trades || 0, 0)}건`);
    h += thin(s.trades || 0, 30, "매매법 계좌 끝난 거래");
    if (!s.trades) return h + '<p class="empty">아직 끝난 거래가 없습니다.</p>';
    h += `<p class="muted">칸 = 거래 수 · 이긴 비율 · 손익 합계. ${d.small_n || 10}건 미만 칸은 '표본 적음'(결론 없음). 동전 봇(무작위 진입)은 같은 칸의 기준입니다.</p><div class="an-2">`;
    for (const [k, title] of GROUPS) {
      const keys = [...new Set([...Object.keys(s[k] || {}), ...Object.keys(f[k] || {})])];
      if (!keys.length) continue;
      h += section(title, `<table class="an-t"><thead><tr><th class="l"></th><th class="l">매매법</th><th class="l">동전 봇</th></tr></thead><tbody>` +
        keys.map((x) => `<tr><td class="l"><b>${esc(k === "by_timeframe" ? TF_KO[x] || x : x)}</b></td><td class="l">${cmpCell((s[k] || {})[x])}</td><td class="l">${cmpCell((f[k] || {})[x])}</td></tr>`).join("") + "</tbody></table>");
    }
    const eb = d.entry_buckets;
    if (eb) {
      const row = (lab, c) => `<tr><td class="l"><b>${esc(lab)}</b></td><td class="l">${c && c.n ? `${fmt(c.n, 0)}건 · ${pc(c.wr)} · 평균 ROE <span class="${ucls(c.roe)}">${pcs(c.roe)}</span>${small(c.small)}` : "—"}</td></tr>`;
      if (eb.volatility) h += section("진입 때 변동성 (같은 코인·봉의 지난 30일 대비)", `<table class="an-t"><tbody>${Object.entries(eb.volatility).map(([b, c]) => row(VOL_KO[b] || b, c)).join("")}</tbody></table>`);
      if (eb.weekday) h += section("진입 요일 (한국 시간)", `<table class="an-t"><tbody>${Object.entries(eb.weekday).map(([b, c]) => row(b, c)).join("")}</tbody></table>`);
    } else h += section("변동성·요일별", '<p class="muted">\'진입 순간\' 화면을 한 번 열면 그 계산(모든 매매법 거래)으로 변동성·요일별 칸이 여기에 붙습니다.</p>');
    h += "</div>";
    return h;
  }

  // ------------------------------------------------------------ ⑥ 진입 순간
  const DIM_KO = {strength: "진입 강도", volatility: "변동성", body: "몸통 크기(ATR 대비)", wick_against: "반대쪽 꼬리", wick_with: "같은 쪽 꼬리",
    close_loc: "종가 위치", streak: "연속 봉", pattern: "봉 모양", liq: "직전 강제청산 몰림", hold: "보유 시간", funding: "펀딩비", weekday: "요일"};
  const BK_KO = {weak: "약함", mid: "중간", strong: "강함", unknown: "모름", low: "낮음", high: "높음", with_1: "같은 방향 1개", with_2: "같은 방향 2개",
    "with_3+": "같은 방향 3개+", against_1: "반대 1개", "against_2+": "반대 2개+", doji: "도지", engulf_with: "장악형(같은 방향)",
    engulf_against: "장악형(반대)", pin_with: "망치형(같은 방향)", pin_against: "망치형(반대)", none: "없음", burst_with: "몰림(같은 방향)",
    burst_against: "몰림(반대)", neg: "마이너스", base: "기본", "<30m": "30분 미만", "30m-2h": "30분~2시간", "2h-8h": "2~8시간", "8h+": "8시간+"};
  function rEntry(d) {
    const cov = d.coverage || {}, mc = d.multiple_comparisons || {};
    let h = head("진입 순간의 모습별 성적", `끝난 매매법 거래 ${fmt(d.trades || 0, 0)}건 · 칸 최소 ${d.min_n || 10}건`);
    h += thin(d.trades || 0, 100, "끝난 매매법 거래");
    if (!d.trades) return h + `<p class="empty">${esc(d.note || "아직 끝난 거래가 없습니다")}</p>`;
    if (mc.note) h += `<p class="an-warn">${esc(mc.note)}</p>`;
    const T = cov.trades || d.trades || 1;
    h += `<p class="muted">자료가 붙은 비율: 봉 모양 ${pc((cov.candle || 0) / T)} · 변동성 ${pc((cov.volatility || 0) / T)} · 진입 강도 ${pc((cov.strength || 0) / T)} · 강제청산 ${pc((cov.liq || 0) / T)}${cov.liq_note ? ` (${esc(cov.liq_note)})` : ""}</p><div class="an-2">`;
    for (const dim of d.dims || Object.keys(d.all || {})) {
      const t = (d.all || {})[dim];
      if (!t || !Object.keys(t).length) continue;
      h += section(DIM_KO[dim] || esc(dim), `<table class="an-t"><thead><tr><th class="l"></th><th>거래</th><th>승률</th><th>평균 ROE</th></tr></thead><tbody>` +
        Object.entries(t).map(([b, c]) => `<tr class="${c.small ? "muted" : ""}"><td class="l">${esc(BK_KO[b] || b)}${small(c.small)}</td><td>${fmt(c.n, 0)}</td><td>${pc(c.wr)}</td><td class="${ucls(c.roe)}">${pcs(c.roe)}</td></tr>`).join("") +
        "</tbody></table>");
    }
    h += "</div>";
    if ((d.notable || []).length) h += section("매매법마다 평소와 가장 달랐던 칸 (가설일 뿐)", `<div class="scroll"><table class="cards"><thead><tr><th class="l">매매법</th><th class="l">칸</th><th>거래</th><th>평균 ROE</th><th>매매법 평균</th></tr></thead><tbody>` +
      d.notable.map((x) => `<tr><td class="l name">${esc(x.name_ko || x.strategy)}</td><td class="l" data-k="칸">${esc(DIM_KO[x.dim] || x.dim)}: ${esc(BK_KO[x.bucket] || x.bucket)}</td>
        <td data-k="거래">${fmt(x.n, 0)}</td><td data-k="평균 ROE" class="${ucls(x.roe)}">${pcs(x.roe)}</td><td data-k="매매법 평균">${pcs(x.strategy_roe)} (${fmt(x.strategy_n, 0)}건)</td></tr>`).join("") + "</tbody></table></div>");
    const sk = d.skipped_signals;
    if (sk) {
      const so = sk.skipped_outcome || {};
      h += section("들어가지 않은 신호", `<p>${Object.entries(sk.not_taken || {}).filter(([, v]) => typeof v === "number").map(([k, v]) => `${esc(k)} <b>${fmt(v, 0)}</b>`).join(" · ") || "—"}</p>
        ${so.signals != null ? `<p>건너뛴 신호 ${fmt(so.signals, 0)}개 중 결과가 나온 ${fmt(so.resolved, 0)}개: 승률 ${pc(so.wr)} · 평균 ROE <span class="${ucls(so.roe)}">${pcs(so.roe)}</span>${so.entered_roe != null ? ` (들어간 거래 평균 ${pcs(so.entered_roe)})` : ""}${small(so.small)}</p>` : `<p class="muted">${esc(so.note || "")}</p>`}
        <p class="muted">${esc(sk.note || "")}</p>`);
    }
    h += `<p class="muted">${esc(d.note || "")}</p>`;
    return h;
  }

  // ------------------------------------------------------------ 조합 시너지
  function rSynergy(d) {
    let h = head("매매법 여러 개를 같이 돌렸다면", `${fmt(d.days || 0, 0)}일 · 매매법 ${fmt(d.units || 0, 0)}개 · ${esc(d.label || "")}`);
    h += thin(d.days || 0, 14, "날 수(하루 손익)");
    if (d.note) h += `<p class="muted">${esc(d.note)}</p>`;
    const top = d.top || [];
    if (top.length) h += `<div class="card scroll"><table class="cards"><thead><tr><th class="l">조합</th><th>수익</th><th>최대 낙폭</th><th title="총손익 ÷ 최대 낙폭($)">점수</th><th title="구성 매매법 각자의 최대 낙폭 합 ÷ 합친 곡선의 최대 낙폭 (1 = 위험이 안 나뉨)">분산 효과</th></tr></thead><tbody>` +
      top.map((r) => `<tr><td class="l name">${r.names.map(esc).join(" + ")}${r.same_bet ? ' <span class="tag bust" title="같은 코인·같은 방향을 대부분 같이 들고 있던 쌍이 들어 있음">같은 베팅 포함</span>' : ""}</td>
        <td data-k="수익" class="${ucls(r.return_pct)}">${pcs(r.return_pct)}</td><td data-k="최대 낙폭">${r.max_dd_pct ? "-" + pc(r.max_dd_pct, 1) : "—"}</td>
        <td data-k="점수">${num(r.score)}</td><td data-k="분산 효과">${r.combined_never_fell ? "내려간 적 없음" : num(r.div_ratio)}</td></tr>`).join("") + "</tbody></table></div>";
    const sh = d.shuffled_days;
    if (sh) h += `<p>날짜를 섞은 자료로 같은 탐색을 ${sh.runs}번: 섞은 최고 점수 중앙값 ${num(sh.null_best_median)}, 진짜 최고 ${num(sh.real_best)} · <b>rank_p ${num(sh.rank_p, 3)}</b>
      ${sh.rank_p > 0.1 ? '<span class="accent">(우연히 찾아지는 정도: 이 조합이 특별하다고 보기 어려움)</span>' : '<span class="muted">(섞은 자료보다 드물게 높음, 그래도 기간이 짧으면 우연일 수 있음)</span>'}</p>`;
    if (d.coin_flips) h += `<p class="muted">동전 봇 ${d.coin_flips.units}개로 같은 탐색: 최고 점수 ${num(d.coin_flips.best_score)} (조건이 같지 않은 참고 기준)</p>`;
    if ((d.same_bet_pairs || []).length) h += `<p class="muted">사실상 같은 베팅 쌍: ${d.same_bet_pairs.slice(0, 6).map((p) => esc(p.strategies.join(" · "))).join(" / ")}</p>`;
    if ((d.clusters || []).length) h += `<p class="muted">하루 손익이 같이 움직이는 묶음(상관 0.7 이상): ${d.clusters.slice(0, 5).map((g) => esc(g.join(", "))).join(" / ")}</p>`;
    h += '<p class="muted">수만 개 조합 중 고른 최고값이라 실제보다 좋아 보이기 쉽습니다. 계좌를 묶거나 바꾸지 않습니다: 설명용, 판정 아님.</p>';
    return h;
  }

  // ------------------------------------------------------------ 좋은 자리 vs 보통 (규칙 B, docs/levrule-eval.md)
  const GKO = {best: "좋은 자리", normal: "보통"};
  const rp = (x) => (x == null || isNaN(x) ? "—" : (x > 0 ? "+" : "") + (x * 100).toFixed(3) + "%");   // per unit exposure
  function rLevrule(d) {
    if (d.status === "no_run") return `<p class="empty">${esc(d.status_ko || "아직 계좌 없음")}</p>`;
    const g = d.groups || {}, b = g.best || {}, n = g.normal || {}, c = d.cells || {}, tr = d.trades || {};
    let h = head("좋은 자리 vs 보통 · 레버리지 규칙 B", `매매법 거래 ${fmt(tr.strategy || 0, 0)}건 · 동전 봇 ${fmt(tr.coin_flips || 0, 0)}건`);
    h += d.status === "decided"
      ? `<div class="an-status ${d.decision === "keep" ? "up" : "accent"}"><b>● ${esc(d.status_ko)}</b><span class="muted">미리 정한 방법 그대로의 코드 판정 · 다음 창은 규칙 버전에 따라 새 계좌, 두 분 확인</span></div>`
      : `<p class="an-warn"><b>30일 판정 전 결론 없음.</b> 아래는 중간 숫자입니다. 규칙 B는 첫 판정(30일 체크포인트)에서 미리 정한 방법으로 한 번만 판정하고, 그 전에는 아무것도 바꾸지 않습니다.</p>`;
    h += `<div class="tiles">${tile("매매법 차이 D_s", rp(d.d_s), `좋은 자리 − 보통, 노출당 · 적격 칸 ${c.strategy_eligible || 0}/${c.strategy_total || 0}`, ucls(d.d_s))}
      ${tile("한쪽 p", d.p_s == null ? "—" : num(d.p_s, 3), `기준 ≤ ${num((d.conditions || {}).alpha, 2)} · 주 단위 블록 부트스트랩`)}
      ${tile("동전 봇 차이 D_c", rp(d.d_c), `같은 구분의 우연 기준 · 적격 칸 ${c.coin_flips_eligible || 0}/${c.coin_flips_total || 0}`, ucls(d.d_c))}
      ${tile("조건", `${(d.conditions || {}).a_best_beats_normal ? "✅" : "❌"} ${(d.conditions || {}).b_beats_coin_flips ? "✅" : "❌"}`, "(가) 좋은 자리가 낫고 p ≤ 0.10 · (나) 동전 봇 차이보다 큼")}</div>`;
    const row = (k, f) => `<tr><td class="l name">${k}</td>${[b.strategy, n.strategy, b.coin_flips, n.coin_flips].map((x, i) => `<td data-k="${["좋은 자리(매매법)", "보통(매매법)", "좋은 자리(동전 봇)", "보통(동전 봇)"][i]}">${x && x.trades ? f(x) : "—"}</td>`).join("")}</tr>`;
    h += section("묶음별 숫자", `<div class="scroll"><table class="cards"><thead><tr><th class="l"></th><th>좋은 자리 · 매매법</th><th>보통 · 매매법</th><th>좋은 자리 · 동전 봇</th><th>보통 · 동전 봇</th></tr></thead><tbody>
      ${row("거래", (x) => fmt(x.trades, 0) + small(x.small))}${row("승률", (x) => pc(x.win_rate))}${row("평균 ROE", (x) => `<span class="${ucls(x.mean_roe)}">${pcs(x.mean_roe)}</span>`)}
      ${row("거래당 자금 대비", (x) => `<span class="${ucls(x.mean_eq)}">${pcs(x.mean_eq, 2)}</span>`)}${row("노출 1단위당 수익", (x) => `<b class="${ucls(x.mean_r)}">${rp(x.mean_r)}</b>`)}
      </tbody></table></div><p class="muted">노출 1단위당 수익 = 손익 ÷ (증거금 × 레버리지) = ROE ÷ 레버리지 (수수료·펀딩 뺀 순). 레버리지가 다른 거래를 같은 크기로 맞춰 비교하는 숫자입니다.</p>`);
    const mix = d.leverage_mix || {}, rk = d.reason_ko || {};
    const mixRows = ["best", "normal"].map((k) => {
      const m = mix[k] || {}, bl = m.by_leverage || {}, wl = m.why_lower || {}, tot = Object.values(bl).reduce((a, x) => a + x, 0);
      const flips = (g[k] || {}).coin_flips_by_leverage || {}, ftot = Object.values(flips).reduce((a, x) => a + x[0], 0);
      const cells = ["50", "40", "30", "20"].map((lv) => {
        const why = Object.entries(wl[lv] || {}).map(([code, v]) => `${esc(rk[code] || code)} ${v}`).join(", ");
        const f = flips[lv];
        return `<td data-k="${lv}배">${bl[lv] ? `${fmt(bl[lv], 0)} <small class="muted">(${pc(bl[lv] / tot)})</small>` : "—"}${why ? `<span class="why">왜 낮게: ${why}</span>` : ""}${f ? `<span class="why">동전 봇 ${f[0]}건 (${pc(f[0] / ftot)}) · 노출당 ${rp(f[1])}</span>` : ""}</td>`;
      }).join("");
      const rw = (g[k] || {}).coin_flips_at_strategy_mix || {};
      return `<tr><td class="l name">${GKO[k]}${tot ? ` <small class="muted">${tot}건</small>` : ""}</td>${cells}<td data-k="동전 봇(같은 배수 구성)">${rw.mean_r == null ? "—" : `노출당 ${rp(rw.mean_r)} · 자금 대비 ${pcs(rw.mean_eq, 2)}${rw.coverage < 1 ? ` <small class="muted">(맞춘 비율 ${pc(rw.coverage)})</small>` : ""}`}</td></tr>`;
    }).join("");
    h += section("실제로 들어간 배수와 이유 (매매법 계좌)", `<div class="scroll"><table class="cards"><thead><tr><th class="l">묶음</th><th>50배</th><th>40배</th><th>30배</th><th>20배</th><th>동전 봇 · 같은 배수 구성</th></tr></thead><tbody>${mixRows}</tbody></table></div>
      <p class="muted">좋은 자리는 50배·50%부터, 보통은 30배·30%부터 시도하고 안전 조건(거래소 구간, 손절이 청산가보다 안쪽, 손절 손실 ≤ 자금 15%)에 막히면 내려갑니다. '왜 낮게' = 첫 후보를 막은 조건(진입 기록). 동전 봇 · 같은 배수 구성 = 동전 봇의 같은 묶음을 매매법의 배수 비중으로 다시 맞춘 기준.</p>`);
    const cr = Object.entries(d.cell_rows || {});
    h += section("적격 칸 (두 묶음 모두 10건 이상)", cr.length ? `<div class="scroll"><table class="cards"><thead><tr><th class="l">계좌</th><th>좋은 자리</th><th>보통</th><th>차이(노출당)</th></tr></thead><tbody>` +
      cr.map(([a, r]) => `<tr class="click" data-acct="${esc(a)}"><td class="l name">${esc(idName(a))}</td><td data-k="좋은 자리">${fmt(r[0], 0)}</td><td data-k="보통">${fmt(r[1], 0)}</td><td data-k="차이" class="${ucls(r[2])}">${rp(r[2])}</td></tr>`).join("") + "</tbody></table></div>"
      : '<p class="muted">아직 두 묶음 모두 10건이 넘은 계좌가 없습니다.</p>');
    h += `<p class="muted">${esc(d.note || "")} · <a href="/api/doc/levrule-eval" target="_blank" rel="noopener">미리 정한 방법 원문 (docs/levrule-eval.md)</a></p>`;
    return h;
  }

  // ------------------------------------------------------------ 그림자 비교 (새 실험, 그림자 모두 vs base)
  const CURVE_SETS = {lev: ["base", "lev10", "lev20", "lev30", "lev40", "lev50"], levm: ["base", "lev20m20", "lev30m30", "lev40m40", "lev50m50"]};
  const CURVE_KO = {base: "base(실제 규칙)", lev10: "10배", lev20: "20배", lev30: "30배", lev40: "40배", lev50: "50배",
    lev20m20: "20배·20%", lev30m30: "30배·30%", lev40m40: "40배·40%", lev50m50: "50배·50%"};
  const share = (x) => (x == null ? "—" : Math.round(x * 100) + "%");
  function rShadows(d) {
    const base = d.base || {};
    let h = head("그림자 비교 · 새 실험의 같은 거래를 규칙 하나만 바꿔", `base 그림자 ${fmt(base.trades || 0, 0)}건 · 거래당 자금 대비 ${pcs(base.mean_eq, 2)} · ${esc(d.label || "")}`);
    if (d.error) h += `<p class="an-warn">${esc(d.error)}</p>`;
    h += thin(base.trades || 0, 30, "base 그림자 거래");
    h += '<div class="an-2">';
    for (const g of d.groups || []) {
      const rows = (g.rows || []).map((r) => `<tr class="${r.small || !r.trades ? "muted" : ""}"><td class="l name">${esc(r.ko)}${small(r.small)}</td>
        <td data-k="거래">${fmt(r.trades || 0, 0)}${r.not_entered ? ` <small class="muted">진입 안 함 ${r.not_entered}</small>` : ""}</td>
        <td data-k="거래당 자금 대비" class="${ucls(r.mean_eq)}">${pcs(r.mean_eq, 2)}</td>
        <td data-k="base와 차이" class="${ucls(r.vs_base_eq)}">${pcs(r.vs_base_eq, 2)}</td>
        <td data-k="나음 / 나쁨">${share(r.better_share)} / ${share(r.worse_share)}</td></tr>`).join("");
      h += section(esc(g.title), `<table class="cards"><thead><tr><th class="l">그림자</th><th>거래</th><th>자금 대비</th><th>base와 차이</th><th>나음 / 나쁨</th></tr></thead><tbody>${rows}</tbody></table>
        <p class="an-ref">5년 기준: ${esc(g.five_year || "—")}</p>`);
    }
    h += "</div>";
    const cv = d.curves || {}, set = CURVE_SETS[an.curveSet] || CURVE_SETS.lev;
    const vs = set.filter((v) => (cv.variants || []).includes(v));
    const acc = cv.account;
    const opts = `<option value="">매매법 계좌 중앙값 (전체)</option>` + (d.accounts || []).map((a) => `<option value="${esc(a)}"${a === an.shadowAcct ? " selected" : ""}>${esc(idName(a))}</option>`).join("");
    let body = `<div class="an-pick"><div class="seg"><button data-cset="lev" class="${an.curveSet === "lev" ? "on" : ""}">레버리지 고정(티어 비중)</button><button data-cset="levm" class="${an.curveSet === "levm" ? "on" : ""}">레버리지 = 비중</button></div>
      <select id="an-curve-acct" aria-label="계좌 고르기">${opts}</select></div>`;
    if (!(cv.days || []).length || !vs.length) body += '<p class="muted">아직 그림자 자금 곡선이 없습니다 (밤 점검이 하루 이상 돈 뒤 생김).</p>';
    else {
      body += `<div class="an-legend">${vs.map((v, i) => `<span><i style="background:var(--c${i + 1})"></i>${esc(CURVE_KO[v] || v)}</span>`).join("")}</div><div class="an-chart" id="an-curve"></div>`;
      const last = cv.days.length - 1;
      body += `<div class="scroll"><table class="cards"><thead><tr><th class="l">그림자</th><th>${acc ? "이 계좌" : "중앙값"} (${esc(cv.days[last])})</th><th>파산</th></tr></thead><tbody>` +
        vs.map((v) => { const b = (cv.by_variant || {})[v] || {}; const val = acc ? ((acc.curves || {})[v] || [])[last] : (b.median || [])[last];
          const bust = acc ? ((acc.bust_day || {})[v] ? `파산 ${esc(acc.bust_day[v])}` : "없음") : `${(b.busts || [])[last] || 0} / ${b.accounts || 0}`;
          return `<tr><td class="l name">${esc(CURVE_KO[v] || v)}</td><td data-k="자금">${val == null ? "—" : "$" + fmt(val, 0)}</td><td data-k="파산">${bust}</td></tr>`; }).join("") + "</tbody></table></div>";
    }
    h += section(acc ? `레버리지 자금 곡선 · ${esc(idName(acc.account_id))}` : "레버리지 자금 곡선 · 매매법 계좌 중앙값", body + `<p class="muted">같은 거래를 레버리지만(왼쪽 묶음: 증거금 20·20·30·40·40%, 오른쪽: 증거금 = 레버리지 %) 바꿔 $${fmt(cv.start || 5000, 0)}부터 굴린 자금. 파산 = $${fmt(cv.bust_below || 10, 0)} 아래. ${esc(d.note || "")}</p>`);
    return h;
  }
  function drawCurves(d) {
    const el = document.getElementById("an-curve"), cv = d.curves || {};
    if (!el || !window.LightweightCharts || typeof chartOpts !== "function") return;
    const vs = (CURVE_SETS[an.curveSet] || CURVE_SETS.lev).filter((v) => (cv.variants || []).includes(v));
    const c = LightweightCharts.createChart(el, chartOpts(el)); an.charts.push(c);
    const t = (cv.days || []).map((x) => Math.floor(Date.parse(x + "T00:00:00Z") / 1000));
    vs.forEach((v, i) => {
      const ys = cv.account ? ((cv.account.curves || {})[v] || []) : (((cv.by_variant || {})[v] || {}).median || []);
      const s = c.addLineSeries({color: css(`--c${i + 1}`), lineWidth: 2, title: CURVE_KO[v] || v, lastValueVisible: false,
        priceLineVisible: false, priceFormat: {type: "price", precision: 0, minMove: 1}});
      s.setData(t.map((x, k) => ({time: x, value: ys[k]})).filter((p) => p.value != null));
      if (i === 0) s.createPriceLine({price: cv.start || 5000, color: css("--muted"), lineStyle: 2, lineWidth: 1, title: "시작"});
    });
    c.timeScale().fitContent();
  }

  // ------------------------------------------------------------ ⑦ 45개 질문
  const QST = {done: ["✅", "답 있음", "up"], partial: ["△", "일부", "accent"], todo: ["☐", "아직", "down"], na: ["—", "해당 없음", "muted"]};
  function rQuestions(d) {
    if (!d.ready) return `<p class="empty">${esc(d.note || "준비 중")}</p><p class="muted" style="text-align:center">원본 목록이 들어오면 질문마다 답이 있는지(✅ 답 있음 · △ 일부 · ☐ 아직)를 여기서 봅니다.</p>`;
    const c = d.counts || {};
    let h = head(`질문 ${d.total}개 점검표`, `${d.source ? "출처 " + esc(d.source) : ""}${d.updated ? " · " + esc(d.updated) : ""}`);
    h += `<div class="tiles">${tile("답 있음", c.done || 0, "", "up")}${tile("일부", c.partial || 0, "", "accent")}${tile("아직", c.todo || 0, "", "down")}${tile("해당 없음", c.na || 0, "")}</div>`;
    let group = null;
    h += '<div class="card"><ul class="an-q">' + (d.questions || []).map((q) => {
      const s = QST[q.status] || QST.todo;
      const g = q.group && q.group !== group ? `<li class="an-qg">${esc(q.group)}</li>` : "";
      group = q.group || group;
      return `${g}<li><span class="an-qs ${s[2]}" title="${s[1]}">${s[0]}</span><div><b>${q.n}.</b> ${esc(q.q)}${q.where ? `<div class="muted">어디서: ${esc(q.where)}</div>` : ""}${q.note ? `<div class="muted">${esc(q.note)}</div>` : ""}</div></li>`;
    }).join("") + "</ul></div>";
    return h;
  }

  // ------------------------------------------------------------ 알림 기록
  function rAlerts(d) {
    const lv = an.alertLevel;
    const bot = (d.bot || []).filter((a) => !lv || (lv === "bad" ? a.level !== "INFO" : a.level === "INFO"));
    let h = head("알림 기록", `읽은 곳: ${(d.sources || []).map(esc).join(", ") || "없음"}`);
    h += `<p class="muted">${(d.not_stored || []).map(esc).join(" ")}. 아래는 서버에 실제로 남아 있는 기록만 보여 줍니다.</p>`;
    h += section("봇 경고·기록 (paper3.db)", `<div class="seg" style="margin-bottom:8px"><button data-lv="" class="${lv ? "" : "on"}">전체</button><button data-lv="bad" class="${lv === "bad" ? "on" : ""}">긴급·주의</button><button data-lv="info" class="${lv === "info" ? "on" : ""}">정보</button></div>` +
      (bot.length ? `<div class="scroll"><table class="cards"><thead><tr><th class="l">시각</th><th class="l">수준</th><th class="l">내용</th></tr></thead><tbody>` +
        bot.map((a) => `<tr><td class="l" data-k="시각">${tsKo(a.ts)}</td><td class="l ${a.level === "CRITICAL" ? "down" : a.level === "WARN" ? "accent" : "muted"}" data-k="수준">${a.level === "CRITICAL" ? "긴급" : a.level === "WARN" ? "주의" : "정보"}</td>
          <td class="l an-wrap" data-k="내용">${esc(typeof alertKo === "function" ? alertKo(a.text) : a.text)}</td></tr>`).join("") + "</tbody></table></div>" : '<p class="muted">기록 없음</p>'));
    const nl = d.nightly || [];
    h += section("밤 점검 (daily3.db, 최근 14일)", nl.length ? `<div class="scroll"><table class="cards"><thead><tr><th class="l">날</th><th class="l">재계산</th><th>빠진 1분봉</th></tr></thead><tbody>` +
      nl.map((n) => { const p = n.parity || {}; return `<tr><td class="l" data-k="날">${esc(n.day)}</td><td class="l" data-k="재계산">${p.accounts != null ? `${p.mismatched_accounts ? `<b class="down">불일치 ${p.mismatched_accounts}</b>` : "일치"} / ${p.accounts}${p.early_kline ? ` · <span class="accent">early_kline ${p.early_kline}</span>` : ""}${p.crash_gaps ? ` · 재시작 공백 ${p.crash_gaps}` : ""}` : `<span class="accent">${esc(p.note || "재계산 못 함")}</span>`}</td>
        <td data-k="빠진 1분봉">${n.missing_bars || 0}</td></tr>`; }).join("") + "</tbody></table></div>" : '<p class="muted">기록 없음 (daily3.db 없음)</p>');
    const mm = d.mismatches || [];
    if (mm.length) h += section("재계산 불일치 계좌", `<p class="an-wrap">${mm.slice(0, 60).map((m) => `${esc(m.day)} <span title="${esc(m.account_id)}">${esc(idName(m.account_id))}</span>${m.label ? ` <span class="tag acc">${esc(m.label)}</span>` : ' <span class="tag bust">설명 없음</span>'}`).join("<br>")}</p>`);
    const cj = d.checkpoint_jobs || [];
    if (cj.length) h += section("체크포인트 작업 기록", `<p class="an-wrap">${cj.map((j) => `${tsKo(j.ts)} ${esc(j.text)}`).join("<br>")}</p>`);
    const tk = d.agents_tick;
    if (tk) h += section("에이전트 마지막 점검", `<p>${tsKo(tk.ts)} · ${tk.ok === false ? `<b class="down">실패</b>${tk.why ? " · " + esc(tk.why) : ""}` : "정상"}${d.agents_ai && d.agents_ai.failed ? ` · AI 연속 실패 ${d.agents_ai.failed}번` : ""}</p>`);
    const jf = d.job_failures || [];
    h += section("예약 작업 실패 경고", jf.length ? `<p>${jf.map((f) => `${esc(f.job_ko)}: ${esc(f.day)}`).join("<br>")}</p>` : '<p class="muted">기록 없음 (이 서버에 실패 경고 기록이 없거나 읽을 수 없음)</p>');
    const pf = d.price_alerts_fired || [];
    if (pf.length) h += section("울린 가격 알림", `<p>${pf.map((a) => `${tsKo(a.fired_ts)} ${esc(coin(a.symbol || ""))} ${a.direction === "above" ? "↑" : "↓"} ${fmt(a.price, 2)}${a.note ? " · " + esc(a.note) : ""}`).join("<br>")}</p>`);
    return h;
  }

  // ------------------------------------------------------------ 24시간 토론방 (회의실 view)
  // paperbot-debate (own paid-API service, docs/debate-room.md). Read-only: debate.db is opened read-only by the server.
  const DB_CLS = {"돌고 있음": "up", "멈춤": "down", "키 없음": "down", "꺼짐": "muted"};
  const hm = (ts) => { const d = new Date(ts + 9 * 3600000); return `${d.getUTCMonth() + 1}/${d.getUTCDate()} ${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`; };
  const money = (x) => (x == null || isNaN(x) ? "—" : "$" + Number(x).toFixed(2));
  function debateHtml(d) {
    const st = d.state_ko || "꺼짐";
    let h = `<p><b class="${DB_CLS[st] || ""}">${esc(st)}</b>${d.reason ? ` <span class="muted">· ${esc(d.reason)}</span>` : ""}</p>`;
    const sp = d.spend;
    if (sp) {
      h += `<p class="muted">이번 달 ${money(sp.month)} / 한도 ${money(sp.cap)}${sp.pct != null ? ` (${sp.pct}%)` : ""} · 오늘 ${money(sp.day)} · 모델 ${esc(d.model || "—")} · ${d.every_min || "—"}분마다` +
        `${d.last_round_ts ? ` · 마지막 토론 ${hm(d.last_round_ts)}` : ""}${d.skipped_24h ? ` · 하루 안에 건너뜀 ${d.skipped_24h}번(바뀐 것 없음)` : ""}</p>`;
    }
    h += `<p class="an-warn">${esc(d.caution || "")}</p>`;
    const rs = d.rounds || [];
    const ok = rs.filter((r) => r.messages && r.messages.length);
    const skipped = rs.filter((r) => r.status === "skipped").length;
    const bad = rs.filter((r) => r.status === "error" || r.status === "aborted").slice(0, 3);
    if (ok.length) {
      h += `<div class="an-h"><b>최근 토론</b><span class="muted">새것부터</span></div>` + ok.slice(0, 4).map((r) =>
        `<div class="an-wrap"><small class="muted">${hm(r.ts)} · ${esc(r.topic || "")} · ${money(r.cost_usd)}</small></div>` +
        `<ul class="an-q">${r.messages.map((m) => `<li><span class="an-qs muted">${esc(m.stance || "·")}</span><div><b>${esc(m.speaker)}</b><div class="an-wrap">${esc(m.text)}</div></div></li>`).join("")}</ul>`).join("");
    } else {
      h += `<p class="muted">${esc(d.note || "아직 토론 글이 없습니다")}</p>`;
    }
    if (skipped) h += `<p class="muted">건너뛴 회차 ${skipped}번: 새 청산·알림·밤 점검이 없어 같은 이야기를 되풀이하지 않았습니다.</p>`;
    if (bad.length) h += `<p class="muted">최근 오류: ${bad.map((r) => `${hm(r.ts)} ${esc((r.error || r.status).slice(0, 80))}`).join(" / ")}</p>`;
    const hy = d.hypotheses || [];
    h += `<div class="an-h"><b>가설 (코드가 채점)</b><span class="muted">메뉴에 있는 것만 · 결론 아님</span></div>`;
    h += hy.length ? `<ul class="an-q">${hy.slice(0, 12).map((x) => {
      const c = x.status === "graded" ? (String(x.outcome).startsWith("hit") ? "up" : "down") : "muted";
      return `<li><div class="an-wrap"><b class="${c}">${esc(x.status_ko)}</b> <span class="tag">${esc(x.speaker || "")}</span> ${esc(x.claim || x.kind || "")}` +
        `<br><small class="muted">${esc(x.horizon || "")}${x.status === "dropped" ? " · " + esc(x.outcome || "") : ""}</small></div></li>`; }).join("")}</ul>` : '<p class="muted">아직 없음</p>';
    const sb = d.scoreboard;
    if (sb && sb.speakers && Object.keys(sb.speakers).length) {
      h += `<p class="muted">적중 기록: ${Object.entries(sb.speakers).map(([k, v]) => `${esc(k)} ${v.hit}/${v.graded}${v.small ? "(표본 적음)" : ""}`).join(" · ")}` +
        ` — 채점된 가설이 ${sb.small_below || 10}개 미만이면 표본이 적어 아무것도 말해 주지 못합니다.</p>`;
    }
    const id = d.ideas || [];
    h += `<div class="an-h"><b>새 매매법 연구실에 줄 아이디어</b><span class="muted">시험 전의 생각</span></div>`;
    h += id.length ? `<ul class="an-q">${id.slice(0, 8).map((x) => `<li><span class="an-qs muted">${hm(x.ts).split(" ")[0]}</span><div class="an-wrap">${esc(x.text)}${x.tag ? ` <span class="tag">${esc(x.tag)}</span>` : ""}</div></li>`).join("")}</ul>` : '<p class="muted">아직 없음</p>';
    return h;
  }
  async function loadDebate() {
    const el = $("debate-body");
    if (!el) return;
    let d;
    try { d = await api("/api/debate"); } catch (e) { return; }
    $("debate-at").textContent = d.state_ko || (d.ready ? `${(d.messages || []).length}개 글` : "꺼짐");
    if (!d.ready) { el.innerHTML = `<p><b class="muted">꺼짐</b></p><p class="muted">${esc(d.note || "24시간 토론방 — 꺼짐")}. 에이전트와 별도로, 두 분이 API 키를 넣고 켜면 하루 종일 장을 두고 토론하는 방입니다 (docs/debate-room.md).</p>`; return; }
    el.innerHTML = debateHtml(d);
  }

  // ------------------------------------------------------------ start
  document.querySelectorAll("#an-tabs button").forEach((b) => {
    b.classList.toggle("on", b.dataset.t === an.tab);
    b.onclick = () => {
      an.tab = b.dataset.t;
      try { localStorage.setItem("pb-an-tab", an.tab); } catch (e) { /* private window */ }
      document.querySelectorAll("#an-tabs button").forEach((x) => x.classList.toggle("on", x === b));
      render(); load();
    };
  });
  document.querySelectorAll('#nav button[data-v="analysis"]').forEach((b) => b.addEventListener("click", () => load()));
  // the curves take the theme's colors when drawn: draw them again after the theme changes
  const th = document.getElementById("theme");
  if (th) th.addEventListener("click", () => setTimeout(() => { if (state.view === "analysis" && an.tab === "shadows") render(); }, 0));
  document.querySelectorAll('#nav button[data-v="office"]').forEach((b) => b.addEventListener("click", loadDebate));
  setInterval(() => {
    if (document.visibilityState !== "visible") return;
    if (state.view === "analysis" && an.tab === "health") load();
    if (state.view === "office") loadDebate();
  }, 60000);
})();
