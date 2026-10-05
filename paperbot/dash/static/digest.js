// ------------------------------------------------------------ meeting digest tab (/api/digest/*)
// Code-only views of the agent rooms (owners' choice 2026-10-03): one day's meeting conclusions, the staff
// scorecard, the last 7 days (what the Sunday Telegram report sends) and each strategy's timeframe split.
// Read-only: nothing here changes a meeting or an account.
const dg = {tab: "day", day: null, days: 7, data: {}, open: {}, tfOpen: null, req: 0};
const DG_STANCE = {agree: "동의", disagree: "반대", add: "보완"};
const DG_STATUS = {done: ["끝", "ok"], no_action: ["행동 없음", ""], failed: ["실패", "bad"],
  stopped_budget: ["한도로 멈춤", "acc"], running: ["진행 중", "live"]};
const DG_ACTION = {note: "메모", hypothesis: "가설", request_test: "5년 시험", propose_copy: "복제 제안",
  flag_owners: "두 분께 알림", no_action: "행동 없음", team_meeting: "", newlab_tests: "새 매매법 시험"};
const DG_TFS = CORE_TFS;    // app.js: the 36's traded timeframes (the meetings' strategies; never 5m)

function dgKstDay(ms) {   // 'YYYY-MM-DD' in Korea time
  const d = new Date(ms + 9 * 3600e3);
  return d.toISOString().slice(0, 10);
}
function dgShift(day, n) { return dgKstDay(Date.parse(day + "T00:00:00+09:00") + n * 864e5 + 3600e3); }
function dgDayKo(day) {   // a KST date shown as itself, whatever the browser's time zone
  return new Date(Date.parse(day + "T12:00:00+09:00")).toLocaleDateString("ko-KR",
    {month: "long", day: "numeric", weekday: "short", timeZone: "Asia/Seoul"});
}
const dgRate = (x) => x == null ? "—" : Math.round(x * 100) + "%";
const dgPill = (txt, c) => `<span class="pill ${c || ""}">${esc(txt)}</span>`;
function dgOpenRoom(id) {
  show("rooms");
  if (typeof openRoom === "function") openRoom(id, "chat");
}

// what is on screen belongs to this tab (and day / period): a refresh keeps it until the new answer comes
const dgHave = (tab) => { const d = dg.data[tab]; return !!d && (tab !== "day" || d.day === dg.day) && (tab !== "staff" || d.days === dg.days); };
async function loadDigest() {
  const tab = dg.tab, req = ++dg.req;
  if (!dg.day) dg.day = dgKstDay(Date.now());
  const path = tab === "day" ? `/api/digest/day?day=${dg.day}` : tab === "staff" ? `/api/digest/staff?days=${dg.days}`
    : tab === "week" ? "/api/digest/week" : "/api/digest/tf";
  renderDigest(true);                     // the toggles follow the tab at once; cached data stays on screen
  let d;
  try { d = await api(path); } catch (e) {
    if (req === dg.req && !dgHave(tab)) $("dg-body").innerHTML = '<p class="empty">불러오지 못했습니다. 잠시 뒤 다시 시도해 주세요.</p>';
    return;
  }
  if (req !== dg.req) return;
  dg.data[tab] = d;
  renderDigest();
}
function renderDigest(loading) {
  const d = dg.data[dg.tab];
  $("dg-day").hidden = dg.tab !== "day";
  $("dg-days").hidden = dg.tab !== "staff";
  $("dg-dlabel").textContent = dg.day ? dgDayKo(dg.day) + (dg.day === dgKstDay(Date.now()) ? " (오늘)" : "") : "";
  $("dg-next").disabled = !dg.day || dg.day >= dgKstDay(Date.now());
  if (loading && !dgHave(dg.tab)) { $("dg-body").innerHTML = '<p class="empty">불러오는 중…</p>'; return; }
  if (!d || (loading && dg.body === dg.tab + ":" + (d.computed_at || d.day || ""))) return;   // already shown
  dg.body = dg.tab + ":" + (d.computed_at || d.day || "");
  $("dg-body").innerHTML = dg.tab === "day" ? dgDayHtml(d) : dg.tab === "staff" ? dgStaffHtml(d)
    : dg.tab === "week" ? dgWeekHtml(d) : dgTfHtml(d);
  dgBind();
}

// ---------------------------------------------------------------- one day's meetings
function dgMeetingHtml(m) {
  const [st, sc] = DG_STATUS[m.status] || [m.status, ""];
  const key = String(m.round_id), open = !!dg.open[key];
  const replies = (m.replies || []).map((r) => `<li><b>${esc(r.from_name)}</b> → ${esc(r.to_name)}
      <span class="pill ${r.stance === "disagree" ? "bad" : r.stance === "agree" ? "ok" : "acc"}">${DG_STANCE[r.stance] || r.stance}</span>
      ${esc(r.point)}</li>`).join("");
  const asks = (m.asks || []).map((a) => `<li><b>${esc(a.from_name)}</b>의 질문: ${esc(a.text)}</li>`).join("");
  const who = (m.speakers || []).map((s) => esc(s.name)).join(" → ");
  const summary = String(m.summary_ko || "").trim();
  return `<div class="dg-m" data-room="${esc(m.room_id)}">
    <div class="dg-mh"><b class="dg-room">${esc(m.title)}</b>${dgPill(m.trigger_ko, "acc")}${dgPill(st, sc)}
      ${m.action && DG_ACTION[m.action] !== "" ? dgPill(DG_ACTION[m.action] || m.action) : ""}<span class="grow"></span>
      <time class="muted">${hm(m.started_ts)}</time></div>
    ${m.why ? `<div class="dg-why">${esc(m.why)}</div>` : ""}
    ${(m.lead || []).length ? `<ol class="dg-lead">${m.lead.map((x) => `<li>${esc(x)}</li>`).join("")}</ol>` : ""}
    ${m.open_disagreement ? `<div class="dg-dis">갈린 의견: ${esc(m.open_disagreement)}</div>` : ""}
    ${summary ? `<pre class="dg-sum ${open ? "open" : ""}">${esc(summary)}</pre>` : ""}
    ${replies || asks ? `<ul class="dg-rep">${replies}${asks}</ul>` : ""}
    ${(m.results || []).length ? `<div class="dg-res">${m.results.map((x) => `<div>🧮 ${esc(x)}</div>`).join("")}</div>` : ""}
    <div class="dg-mf"><span class="muted">${who ? "발언: " + who : "발언 없음"} · AI ${m.calls}회</span><span class="grow"></span>
      ${summary ? `<button class="lnk" data-more="${key}" ${open ? "" : "hidden"}>${open ? "접기" : "결론 전부 보기"}</button>` : ""}
      <button class="lnk" data-go="${esc(m.room_id)}">방 열기 →</button></div>
  </div>`;
}
function dgDayHtml(d) {
  if (d.error) return `<p class="empty">${esc(d.error)}</p>`;
  const ms = (d.meetings || []).slice().reverse();
  const kinds = Object.values(d.by_trigger || {}).sort((a, b) => b.meetings - a.meetings)
    .map((k) => `${esc(k.trigger_ko)} ${k.meetings}`).join(" · ");
  const disOpen = ms.filter((m) => m.open_disagreement).length;
  return `<div class="tiles">
      <div class="tile"><div class="k">회의</div><div class="v">${d.n || 0}</div><div class="s">${kinds || "없음"}</div></div>
      <div class="tile"><div class="k">반대 의견 (직원끼리)</div><div class="v">${d.disagreements || 0}</div><div class="s">갈린 채 끝난 회의 ${disOpen}</div></div>
      <div class="tile"><div class="k">AI 호출</div><div class="v">${fmt(d.calls || 0, 0)}</div><div class="s">토큰 ${kfmt(d.tokens || 0)}</div></div>
    </div>
    ${ms.length ? ms.map(dgMeetingHtml).join("") : '<p class="empty">이날 열린 회의가 없습니다</p>'}
    <p class="muted dg-note">최신 회의가 위. 숫자와 결론 요약은 코드가 정리한 것이고, 직원 발언 전문은 '방 열기'에서 봅니다.</p>`;
}

// ---------------------------------------------------------------- staff scorecard
function dgStaffHtml(d) {
  if (d.error) return `<p class="empty">${esc(d.error)}</p>`;
  const t = d.total || {};
  const rows = (d.staff || []).map((s) => {
    const p = s.predictions || {}, r = s.replies || {}, rb = s.replied_by || {}, pr = s.proposals || {};
    const props = Object.entries(pr).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${DG_ACTION[k] || k} ${v}`).join(", ");
    const verd = Object.entries(s.verdicts || {}).map(([k, v]) => `${({agree: "동의", disagree: "반대", needs_test: "시험 필요"})[k] || k} ${v}`).join(", ");
    return `<tr><td class="l" data-k="직원">${typeof roleAv === "function" ? roleAv(s.role, s.name) : ""} <b>${esc(s.name)}</b></td>
      <td data-k="발언">${s.turns}</td><td data-k="회의">${s.meetings}</td>
      <td data-k="반응(동의·반대·보완)">${r.agree || 0}·<span class="down">${r.disagree || 0}</span>·${r.add || 0}</td>
      <td data-k="받은 반대">${rb.disagree || 0}</td><td data-k="질문">${s.asks}</td>
      <td data-k="사실·가설">${s.facts}·${s.hypotheses_said}</td>
      <td data-k="못 읽은 답" class="${s.unreadable ? "down" : ""}">${s.unreadable}</td>
      <td data-k="예측 맞음/채점">${p.graded ? `<b>${p.correct}/${p.graded}</b> (${dgRate(p.hit_rate)})` : "—"}${p.waiting ? ` <small class="muted">대기 ${p.waiting}</small>` : ""}</td>
      <td class="l" data-k="제안·판정"><small>${esc(props || verd || "—")}${props && verd ? " · " + esc(verd) : ""}</small></td>
      <td data-k="마지막 발언"><small class="muted">${s.last_ts ? tsKo(s.last_ts) : "—"}</small></td></tr>`;
  }).join("");
  const grades = (d.recent_grades || []).map((g) => `<tr><td class="l" data-k="채점">${g.status === "expired" ? dgPill("기간 만료")
      : g.correct ? dgPill("맞음", "ok") : dgPill("틀림", "bad")}</td>
      <td class="l" data-k="직원">${esc(g.name || "—")}</td><td class="l" data-k="매매법">${esc(g.strategy || "")}</td>
      <td class="l" data-k="예측">${esc(g.prediction_ko)}${g.value != null ? ` <small class="muted">(실제 ${fmt(g.value, 3)}, ${g.n}건)</small>` : ""}
        ${g.text ? `<div class="muted"><small>${esc(g.text)}</small></div>` : ""}</td>
      <td data-k="때"><small class="muted">${tsKo(g.ts)}</small></td></tr>`).join("");
  return `<div class="tiles">
      <div class="tile"><div class="k">예측 채점 (실험 전체)</div><div class="v">${t.graded ? `${t.correct}/${t.graded}` : "—"}</div>
        <div class="s">적중률 ${dgRate(t.hit_rate)} · 기다리는 예측 ${t.waiting || 0}</div></div>
      <div class="tile"><div class="k">말한 직원 (최근 ${d.days}일)</div><div class="v">${(d.staff || []).filter((s) => s.turns).length}</div>
        <div class="s">발언 ${fmt((d.staff || []).reduce((a, s) => a + s.turns, 0), 0)}번</div></div>
    </div>
    <div class="card scroll"><div class="ph"><span class="t">직원별 (최근 ${d.days}일 발언, 예측은 실험 전체)</span></div>
      <table class="cards dg-t"><thead><tr><th class="l">직원</th><th>발언</th><th>회의</th><th>반응 동의·반대·보완</th><th>받은 반대</th>
        <th>질문</th><th>사실·가설</th><th>못 읽은 답</th><th>예측 맞음/채점</th><th class="l">제안·판정</th><th>마지막</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="11" class="empty">아직 발언이 없습니다</td></tr>'}</tbody></table></div>
    <div class="card scroll"><div class="ph"><span class="t">최근 채점된 예측</span></div>
      <table class="cards dg-t"><thead><tr><th class="l">결과</th><th class="l">직원</th><th class="l">매매법</th><th class="l">예측</th><th>채점</th></tr></thead>
        <tbody>${grades || '<tr><td colspan="5" class="empty">아직 채점된 예측이 없습니다. 예측은 정해 둔 거래 수(30~300건)가 쌓여야 채점됩니다.</td></tr>'}</tbody></table></div>
    <p class="muted dg-note">${esc(d.note || "")}</p>`;
}

// ---------------------------------------------------------------- the last 7 days
function dgRankRows(rows) {
  return rows.map((r) => {
    let mv = "";
    if (r.prev_rank) { const dl = r.prev_rank - r.rank; mv = dl > 0 ? `<span class="up">▲${dl}</span>` : dl < 0 ? `<span class="down">▼${-dl}</span>` : "="; }
    return `<tr><td data-k="순위">${r.rank}</td><td class="l" data-k="매매법"><button class="lnk" data-strat="${esc(r.strategy)}">${esc(r.name_ko)}</button></td>
      <td data-k="손익" class="${cls(r.pnl)}">${usd(r.pnl)}</td><td data-k="승률">${dgRate(r.win_rate)}</td><td data-k="거래">${r.trades}</td>
      <td data-k="지난주 대비">${mv}</td></tr>`;
  }).join("");
}
function dgWeekHtml(d) {
  const t = d.strategies_total || {}, tp = d.strategies_total_prev || {}, cf = d.coin_flips || {}, st = d.staff;
  const head = `<thead><tr><th>순위</th><th class="l">매매법</th><th>손익</th><th>승률</th><th>거래</th><th>지난주 대비</th></tr></thead>`;
  const tfs = Object.entries(d.timeframes || {}).map(([tf, v]) => `<div class="mk-row"><span>${TF_KO[tf] || tf}</span>
      <b class="${cls(v.pnl)}">${usd(v.pnl)} <small class="muted">(${v.trades}건, 승률 ${dgRate(v.win_rate)})</small></b></div>`).join("");
  return `${d.error ? `<p class="down">${esc(d.error)}</p>` : ""}
    <div class="tiles">
      <div class="tile"><div class="k">매매법 계좌 손익 (7일)</div><div class="v ${cls(t.pnl)}">${usd(t.pnl)}</div>
        <div class="s">${tp.trades ? `지난주 ${usd(tp.pnl)}` : d.run_start > d.from - 7 * 86400000 ? "지난주: 실험 시작 전후라 비교 안 함" : "지난주 기록 없음"}</div></div>
      <div class="tile"><div class="k">거래 · 승률</div><div class="v">${fmt(t.trades || 0, 0)}</div>
        <div class="s">승률 ${dgRate(t.win_rate)}${tp.trades ? ` (지난주 ${dgRate(tp.win_rate)})` : ""}</div></div>
      <div class="tile"><div class="k">같은 봉 동전 봇 중간값보다 나은 계좌</div><div class="v">${cf.strategy_accounts ? `${cf.strategy_accounts_beating_median}/${cf.strategy_accounts}` : "—"}</div>
        <div class="s">동전 봇 평균 ${usd(cf.mean_pnl)}</div></div>
      <div class="tile"><div class="k">파산</div><div class="v">${(d.busts || []).length}</div><div class="s">최근 7일</div></div>
    </div>
    <div class="dg-2">
      <div class="card scroll"><div class="ph"><span class="t">이번 주 상위</span></div><table class="cards dg-t">${head}<tbody>${dgRankRows(d.top || [])}</tbody></table></div>
      <div class="card scroll"><div class="ph"><span class="t">이번 주 하위</span></div><table class="cards dg-t">${head}<tbody>${dgRankRows(d.bottom || [])}</tbody></table></div>
    </div>
    <div class="dg-2">
      <div class="mk-card"><div class="mk-name">봉별 합계</div>${tfs || '<div class="muted">기록 없음</div>'}</div>
      <div class="mk-card"><div class="mk-name">직원의 한 주</div>${st ? `
        <div class="mk-row"><span>회의</span><b>${st.meetings_total}번</b></div>
        <div class="mk-row"><span>AI 호출</span><b>${fmt(st.ai_calls, 0)}번 · ${kfmt(st.ai_tokens)} 토큰</b></div>
        <div class="mk-row"><span>가설 기록</span><b>${st.hypotheses}건</b></div>
        <div class="mk-row"><span>예측 채점</span><b>${st.predictions_correct}/${st.predictions_graded} 맞음</b></div>
        <div class="mk-row"><span>5년 시험</span><b>${st.tests}건 (통과 ${st.tests_passed})</b></div>
        <div class="mk-row"><span>새 매매법 시험</span><b>${st.lab_tests}건 (통과 ${st.lab_passed})</b></div>` : '<div class="muted">기록 없음</div>'}</div>
    </div>
    ${d.ghcoin && d.ghcoin.all && d.ghcoin.all.calls ? `<div class="mk-card" style="margin-bottom:10px"><div class="mk-name">GH Coin 기록기 <small class="muted">친구 봇 타점, 기록만 · 수수료 뒤 R</small></div>
      ${[["최근 7일", d.ghcoin.week], ["시작부터", d.ghcoin.all]].map(([k, x]) => `<div class="mk-row"><span>${k}</span><b>${x && x.calls ? `${x.calls}타점 · <span class="${cls(x.net_r)}">${(x.net_r >= 0 ? "+" : "") + fmt(x.net_r, 1)}R</span> (동전 ${fmt(x.coin_flip_net_r, 1)}R${x.p_coin_flip != null ? ", p=" + fmt(x.p_coin_flip, 2) : ""})` : "끝난 타점 없음"}</b></div>`).join("")}</div>` : ""}
    <div class="card"><div class="ph"><span class="t">${dgWeekWhen(d.hours)} (지금 기준 미리보기)</span></div>
      <pre class="dg-tg">${esc(d.telegram_text || "")}</pre></div>
    <p class="muted dg-note">${esc(d.note || "")}</p>`;
}

function dgWeekWhen(h) {
  const x = h && h.weekly_report_hour_kst;
  return x == null ? "일요일 텔레그램으로 가는 글" : x < 0 ? "텔레그램 주간 성적표는 꺼져 있음 (AGENTS_WEEKLY_REPORT_HOUR=off)"
    : `일요일 ${String(x).padStart(2, "0")}:00 텔레그램으로 가는 글`;
}

// ---------------------------------------------------------------- timeframe split
function dgTfCell(v) {
  if (!v || !v.trades) return '<span class="muted">—</span>';
  return `<b class="${cls(v.pnl)}">${usd(v.pnl)}</b><br><small class="muted">${v.trades}건 · ${dgRate(v.win_rate)}${v.bust ? " · 파산" : ""}</small>`;
}
function dgTfDetail(r) {
  return `<tr class="dg-tfd"><td colspan="9"><div class="dg-tfg">${DG_TFS.filter((tf) => (r.timeframes[tf] || {}).trades).map((tf) => {
    const v = r.timeframes[tf];
    return `<div class="mk-card"><div class="mk-name">${TF_KO[tf] || tf} <small class="muted">${v.trades}건</small></div>
      <div class="mk-row"><span>손익</span><b class="${cls(v.pnl)}">${usd(v.pnl)}</b></div>
      <div class="mk-row"><span>승률</span><b>${dgRate(v.win_rate)}</b></div>
      <div class="mk-row"><span>거래당 평균 ROE</span><b class="${cls(v.mean_roe)}">${pct(v.mean_roe)}</b></div>
      <div class="mk-row" title="비용(수수료·펀딩) 빼기 전, 거래 방향으로 움직인 가격의 평균"><span>비용 전 가격 움직임</span><b>${pct(v.move_before_costs, 2)}</b></div>
      <div class="mk-row"><span>거래당 비용</span><b>$${fmt(v.cost_per_trade, 2)}</b></div>
      <div class="mk-row" title="1이 넘으면 비용이 가격 움직임으로 번 것보다 큼"><span>비용 ÷ 비용 전 손익 크기</span><b class="${v.cost_vs_gross > 1 ? "down" : ""}">${v.cost_vs_gross == null ? "—" : v.cost_vs_gross.toFixed(2)}</b></div>
      <div class="mk-row"><span>평균 보유</span><b>${fmt(v.hold_min, 0)}분</b></div>
      <div class="mk-row"><span>롱 · 숏</span><b>${Object.entries(v.sides || {}).map(([k, s]) => `${k} ${s.trades}건 ${usd(s.pnl)}`).join(" · ")}</b></div>
      <div class="mk-row"><span>청산</span><b>${Object.entries(v.exits || {}).map(([k, n]) => `${esc(k)} ${n}`).join(" · ")}</b></div>
    </div>`;
  }).join("")}</div></td></tr>`;
}
function dgTfHtml(d) {
  if (d.error) return `<p class="empty">${esc(d.error)}</p>`;
  const rows = (d.strategies || []).map((r) => `<tr class="dg-tfr ${dg.tfOpen === r.strategy ? "sel" : ""}" data-tf="${esc(r.strategy)}">
      <td class="l" data-k="매매법"><button class="lnk" data-strat="${esc(r.strategy)}">${esc(r.name_ko)}</button>
        ${r.split ? dgPill("봉마다 갈림", "bad") : ""}</td>
      ${DG_TFS.map((tf) => `<td data-k="${TF_KO[tf] || tf}">${dgTfCell(r.timeframes[tf])}</td>`).join("")}
      <td data-k="합계" class="${cls(r.pnl)}">${usd(r.pnl)}</td>
      <td data-k="최고−최저">${r.spread != null ? usd(r.spread).replace("+", "") : "—"}</td>
      <td data-k=""><button class="lnk" data-tfx="${esc(r.strategy)}">${dg.tfOpen === r.strategy ? "접기" : "자세히"}</button></td></tr>
      ${dg.tfOpen === r.strategy ? dgTfDetail(r) : ""}`).join("");
  const th = d.hours && d.hours.tf_split_hour_kst;
  const when = th != null && th < 0 ? "봉 비교 회의는 꺼져 있습니다(AGENTS_TF_SPLIT_HOUR=off)."
    : `매일 ${String(th == null ? 18 : th).padStart(2, "0")}:00에 가장 크게 갈린 매매법 2개의 방에서 전담이 이유를 분석하는 '봉 비교 회의'가 열립니다(같은 매매법은 3일에 한 번).`;
  return `<p class="dg-note">같은 매매법이 봉마다 정반대 결과를 내면(한 봉은 이익, 다른 봉은 손실, 둘 다 거래 ${d.min_trades}건 이상, 차이가
      시작 자금의 ${Math.round((d.min_spread_pct || 0) * 100)}% 이상, 파산한 계좌는 빼고) <b>봉마다 갈림</b>으로 표시합니다. ${when}</p>
    <div class="card scroll"><table class="cards dg-t"><thead><tr><th class="l">매매법 (차이 큰 순)</th>
      ${DG_TFS.map((tf) => `<th>${TF_KO[tf] || tf}</th>`).join("")}<th>합계</th><th>최고−최저</th><th></th></tr></thead>
      <tbody>${rows || '<tr><td colspan="9" class="empty">아직 끝난 거래가 없습니다</td></tr>'}</tbody></table></div>
    <p class="muted dg-note">${esc(d.note || "")}</p>`;
}

// ---------------------------------------------------------------- wiring
function dgBind() {
  // '결론 전부 보기' only where the summary really is cut (long lines wrap on a phone)
  document.querySelectorAll("#dg-body .dg-m").forEach((c) => {
    const s = c.querySelector(".dg-sum"), b = c.querySelector("[data-more]");
    if (s && b && !s.classList.contains("open")) b.hidden = s.scrollHeight <= s.clientHeight + 2;
  });
  document.querySelectorAll("#dg-body [data-go]").forEach((b) => b.onclick = () => dgOpenRoom(b.dataset.go));
  document.querySelectorAll("#dg-body [data-more]").forEach((b) => b.onclick = () => {
    dg.open[b.dataset.more] = !dg.open[b.dataset.more]; dg.body = null; renderDigest();
  });
  document.querySelectorAll("#dg-body [data-strat]").forEach((b) => b.onclick = (e) => {
    e.stopPropagation();
    if (typeof openStrategy === "function") openStrategy(b.dataset.strat);
  });
  document.querySelectorAll("#dg-body [data-tfx]").forEach((b) => b.onclick = () => {
    dg.tfOpen = dg.tfOpen === b.dataset.tfx ? null : b.dataset.tfx; dg.body = null; renderDigest();
  });
}
seg("dg-tabs", "t", (t) => { dg.tab = t; dg.body = null; loadDigest(); });
seg("dg-days", "d", (n) => { dg.days = +n; dg.body = null; loadDigest(); });
$("dg-prev").onclick = () => { dg.day = dgShift(dg.day || dgKstDay(Date.now()), -1); dg.body = null; loadDigest(); };
$("dg-next").onclick = () => {
  const today = dgKstDay(Date.now());
  if ((dg.day || today) >= today) return;
  dg.day = dgShift(dg.day, 1); dg.body = null; loadDigest();
};
$("dg-today").onclick = () => { dg.day = dgKstDay(Date.now()); dg.body = null; loadDigest(); };
setInterval(() => { if (state.view === "digest" && document.visibilityState === "visible") loadDigest(); }, 120000);
