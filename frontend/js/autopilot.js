// 오토파일럿 화면: 차트 지표 → 매매법 탐색 결과, 돌고 있는 오토 봇, 시그널, 설정
import { $, IV_LABEL, api, busy, esc, fmt, hhmm, mdhm, on, px, toast } from "./core.js";
import { showOnChart } from "./trade.js";

let S = null, timer = null, visible = false;
const STAGE = { pass: ["3구간 통과", "up"], hold_fail: ["최종 확인 탈락", "down"], valid_fail: ["검증 탈락", "down"], train_pass: ["학습만 통과", "muted"], train_fail: ["학습 탈락", "muted"] };
const KIND = { pass: ["✅ 검증 통과", "up"], observe: ["👀 관찰(미통과)", "accent"] };
const SIGT = { entry: "진입", exit: "청산", deploy: "봇 시작", ai: "AI", ai_note: "AI 코멘트", ai_auto: "AI 자동", ai_entry: "AI 진입", aibot: "AI 봇" };

export function initAutopilot() {
  on("view", (v) => { visible = v === "autopilot"; if (visible) load(); });
  $("#v-autopilot").addEventListener("click", onClick);
  $("#ap-on").onchange = (e) => save({ enabled: e.target.checked });
  $("#ap-search").onclick = (e) => busy(e.target, async () => { const r = await api("/api/autopilot/search", { method: "POST" }); toast(r.msg); setTimeout(load, 1500); });
  load();
  timer = setInterval(() => (visible && !document.hidden) ? load() : dot(), 5000);
}

async function load() {
  try { S = await api("/api/autopilot"); } catch { return; }
  dot();
  if (visible) render();
}

function dot() {
  const d = $("#ap-dot");
  if (!d || !S) return;
  d.className = `ap-dot ${S.settings.enabled ? (S.searching ? "busy" : "on") : ""}`;
  d.title = S.settings.enabled ? (S.searching ? "매매법 찾는 중" : `켜짐 · 오토 봇 ${S.bots.length}개`) : "꺼짐";
}

async function save(body) {
  S.settings = await api("/api/autopilot/settings", { method: "POST", body });
  toast("오토파일럿 설정 저장");
  load();
}

function seg(s) {
  if (!s) return "–";
  return `<span class="${s.net > 0 ? "up" : "down"}">${s.trades}건 · 손익비 ${s.pf ?? "–"} · ${s.net > 0 ? "+" : ""}${fmt(s.net, 0)}</span>`;
}

function render() {
  const s = S.settings, c = S.context;
  $("#ap-on").checked = s.enabled;
  $("#ap-sub").textContent = s.enabled ? (S.searching ? ` · 매매법 찾는 중…${S.progress ? ` (${S.progress.done + 1}/${S.progress.total} · ${S.progress.current})` : ""}` : ` · 켜짐 · 다음 탐색 ${mdhm(S.next_search)}`) : " · 꺼짐";
  $("#ap-ctx").textContent = `${c.symbol.replace("USDT", "")} ${IV_LABEL[c.interval] || c.interval}` + (S.targets.length > 4 ? ` 외 ${S.targets.length - 1}개 (코인 ${new Set(S.targets.map((t) => t[0])).size}개 · 봉 ${[...new Set(S.targets.map((t) => IV_LABEL[t[1]] || t[1]))].join("·")})`
    : S.targets.length > 1 ? ` (+ ${S.targets.slice(1).map(([a, b]) => `${a.replace("USDT", "")} ${IV_LABEL[b] || b}`).join(", ")})` : "");
  const u = S.usable;
  $("#ap-inds").innerHTML = `<div class="chips">${u.usable.map((k) => `<span class="ai-chip up">${esc(k)}</span>`).join("")}${u.unusable.map((k) => `<span class="ai-chip muted" title="이 지표는 아직 자동 매매법에 못 씀">${esc(k)}</span>`).join("")}</div>
    <div class="help" style="margin-top:6px">${u.usable.length ? `초록색 지표로 진입 규칙·필터를 만들어 손절·익절 방식 4가지와 조합합니다 (최대 240개).` : "자동 매매법에 쓸 수 있는 지표가 차트에 없어 기본 지표(EMA50·RSI·슈퍼트렌드·MACD·거래량)로 찾습니다."}
    ${u.unusable.length ? ` 회색은 자동 매매법에 아직 못 쓰는 지표입니다.` : ""} 트레이드 화면에서 지표를 바꾸면 1분 뒤 자동으로 다시 찾습니다.</div>`;
  $("#ap-bots").innerHTML = S.bots.length ? `<table class="ap-tbl"><tr><th>봇</th><th>과거 검증 (최종 구간)</th><th>실전 모의</th><th>포지션</th><th></th></tr>
    ${S.bots.map((b) => `<tr><td style="text-align:left"><span class="ai-chip ${KIND[b.kind][1]}">${KIND[b.kind][0]}</span> <b>${esc(b.rule)}</b>
      <div class="muted">${b.symbol.replace("USDT", "")} ${IV_LABEL[b.interval] || b.interval} · ${mdhm(b.created)} 시작</div></td>
      <td>${seg(b.backtest?.hold)}</td><td>${b.forward.trades ? seg(b.forward) : '<span class="muted">아직 거래 없음</span>'}</td>
      <td>${b.position ? `<span class="${b.position.side === "long" ? "up" : "down"}">${b.position.side === "long" ? "롱" : "숏"}</span> ${px(b.position.entry)}<div class="muted">손절 ${b.position.stop ? px(b.position.stop) : "–"} · 익절 ${b.position.take ? px(b.position.take) : "–"}</div>` : '<span class="muted">대기</span>'}</td>
      <td style="white-space:nowrap"><button class="sm" data-chart="${b.symbol}|${b.interval}">차트</button> <button class="flat sm" data-retire="${b.id}">정리</button></td></tr>`).join("")}</table>`
    : `<div class="empty">아직 돌고 있는 오토 봇이 없습니다. ${S.searching ? "매매법을 찾는 중입니다…" : "탐색이 끝나면 통과한 매매법으로 시작합니다."}</div>`;
  $("#ap-when").textContent = S.last_search ? `${mdhm(S.last_search)} 탐색` : "";
  const res = [...S.results].sort((a, b) => (b.passed?.length || 0) - (a.passed?.length || 0));
  $("#ap-results").innerHTML = res.length ? res.map((r) => r.error ? `<div class="down">${r.symbol} ${r.interval}: ${esc(r.error)}</div>` : `
    <div class="ap-res"><div class="row"><b>${r.symbol.replace("USDT", "")} ${IV_LABEL[r.interval] || r.interval}</b><span class="muted">${r.bars}봉 · 후보 ${r.tried}개 → 학습 통과 ${r.train_pass} → 상위 ${r.finalists}개 검증 → 통과 ${r.passed.length}${r.ai?.proposed ? ` · 🤖 AI 제안 ${r.ai.proposed}개 (통과 ${r.ai.passed})` : r.ai?.note ? ` · AI 제안 ${esc(r.ai.note)}` : ""}${r.used_default ? " · 기본 지표 사용" : ""}${r.data_source === "synthetic" ? " · ⚠ 가상 데이터" : ""}</span></div>
      ${[...r.passed, ...(r.passed.length ? [] : r.observe.slice(0, 2))].map((x) => `<div class="ap-cand"><span class="ai-chip ${STAGE[x.stage][1]}">${STAGE[x.stage][0]}</span> ${esc(x.name)}
        <div class="muted">학습 ${seg(x.seg.train)} · 검증 ${seg(x.seg.valid)} · 최종 ${seg(x.seg.hold)}</div></div>`).join("") || '<div class="muted">학습 구간을 통과한 후보도 없습니다.</div>'}</div>`).join("")
    + `<div class="help">통과 기준 — 학습: ${S.gate.train.trades}건·손익비 ${S.gate.train.pf} · 검증: ${S.gate.valid.trades}건·${S.gate.valid.pf} · 최종: ${S.gate.hold.trades}건·${S.gate.hold.pf}, 모두 순이익 · 낙폭 35% 미만. 학습 구간 상위 15개만 뒤 구간을 봅니다(많이 시험할수록 우연히 좋아 보이는 것을 줄이기 위해). 과거에 통과해도 앞으로 벌 보장은 없어서 모의 매매로 계속 확인합니다.</div>`
    : `<div class="empty">${S.searching ? "찾는 중…" : "아직 탐색 전"}</div>`;
  $("#ap-set").innerHTML = `
    <label>탐색 범위 <select data-set="scope"><option value="all" ${s.scope === "all" ? "selected" : ""}>관심 종목의 모든 코인</option><option value="chart" ${s.scope === "chart" ? "selected" : ""}>지금 차트 코인</option><option value="chart+watch" ${s.scope === "chart+watch" ? "selected" : ""}>차트 코인 + 관심 종목 3개</option></select></label>
    <label><input type="checkbox" data-set="extra_interval" ${s.extra_interval ? "checked" : ""}> 한 단계 긴 봉도 같이 찾기</label>
    <label>오토 봇 최대 <input type="number" data-set="max_bots" value="${s.max_bots}" min="0" max="30" style="width:56px">개</label>
    <label>다시 찾는 간격 <input type="number" data-set="search_every_hours" value="${s.search_every_hours}" min="1" max="72" style="width:56px">시간</label>
    <label><input type="checkbox" data-set="observe_if_none" ${s.observe_if_none ? "checked" : ""}> 통과가 없으면 가장 나은 후보를 관찰 봇으로</label>
    <label><input type="checkbox" data-set="team_review" ${s.team_review ? "checked" : ""}> 에이전트 팀 검토 뒤 배치 (승인관이 거부하면 안 함)</label>
    <label>에이전트 팀 상시 감시 회의 <input type="number" data-set="team_monitor_min" value="${s.team_monitor_min}" min="0" style="width:64px">분마다 (0=끔)</label>
    <label title="AI 자동 모드의 '차트 실시간 AI'가 켜져 있으면 그쪽이 맡습니다">실시간 AI 감시 <input type="number" data-set="copilot_every_min" value="${s.copilot_every_min}" min="0" style="width:56px">분마다 (0=끔 · AI 자동 모드가 켜져 있으면 그쪽 간격)</label>
    <label><input type="checkbox" data-set="ai_candidates" ${s.ai_candidates ? "checked" : ""}> AI 가 차트 지표로 매매법 후보 제안 (같은 관문으로 검증) · 앞의 <input type="number" data-set="ai_candidate_targets" value="${s.ai_candidate_targets ?? 4}" min="0" max="40" style="width:48px">개 코인·봉만</label>
    <label><input type="checkbox" data-set="ai_signal_comment" ${s.ai_signal_comment ? "checked" : ""}> 진입 시그널마다 AI 코멘트</label>
    <label>봇 레버리지 <input type="number" data-set="leverage" value="${s.leverage}" min="1" max="50" style="width:56px">배 · 증거금 <input type="number" data-set="position_pct" value="${s.position_pct}" min="1" max="100" style="width:56px">%</label>
    <button class="sm" id="ap-save">설정 저장</button>`;
  api("/api/autopilot/signals?since=0").then((d) => {
    $("#ap-signals").innerHTML = d.items.length ? d.items.map((x) => `<div class="ap-sig ${x.type}"><span class="muted">${hhmm(x.created)}</span>
      <span class="ai-chip ${x.type === "entry" || x.type === "ai_entry" ? (x.side === "long" ? "up" : "down") : x.type === "exit" ? (x.pnl > 0 ? "up" : "down") : "accent"}">${SIGT[x.type] || x.type}</span>
      <b>${(x.symbol || "").replace("USDT", "")} ${IV_LABEL[x.interval] || x.interval || ""}</b> ${esc(x.text)}
      ${x.symbol && x.interval ? `<button class="flat sm" data-chart="${x.symbol}|${x.interval}" title="이 코인·봉 차트로">차트</button>` : ""}
      <div class="muted">${esc(x.strategy || "")}${x.status === "observe" ? " · 관찰(검증 미통과) — 참고용" : ""}</div></div>`).join("") : `<div class="empty">아직 시그널이 없습니다.</div>`;
  }).catch(() => {});
  $("#ap-log").innerHTML = S.log.map((l) => `<div><span class="muted">${hhmm(l.time)}</span> ${esc(l.msg)}</div>`).join("") || '<div class="muted">기록 없음</div>';
}

async function onClick(e) {
  const ch = e.target.closest("[data-chart]");
  if (ch) { const [s, iv] = ch.dataset.chart.split("|"); showOnChart(s, iv); return; }
  const rt = e.target.closest("[data-retire]");
  if (rt) {
    if (!confirm("이 오토 봇을 정리할까요? (기록은 남습니다)")) return;
    await busy(rt, async () => { await api(`/api/autopilot/retire/${rt.dataset.retire}`, { method: "POST" }); load(); });
    return;
  }
  if (e.target.id === "ap-save") {
    const body = {};
    document.querySelectorAll("#ap-set [data-set]").forEach((x) => (body[x.dataset.set] = x.type === "checkbox" ? x.checked : x.type === "number" ? +x.value : x.value));
    await busy(e.target, () => save(body));
  }
}

