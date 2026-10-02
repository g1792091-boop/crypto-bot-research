// AI 사무실 — 27개 팀 277명이 24시간 일하는 모습 · 회의록 · 매매법 파이프라인 · 실거래 · 결과·다운로드 · AI 배정
import { $, $$, api, busy, esc, hhmm, mdhm, on, toast } from "./core.js";
import { showOnChart } from "./trade.js";

let R = null;                 // roster
let S = null;                 // 마지막 state
const LOG = new Map();        // id → entry
let cursor = 0, timer = null, tab = "log", ch = "all", visible = false, cardOpen = null, pipeCustom = "all";
const SKIN = "#f2c8a0";

// ------------------------------------------------------------------ 픽셀 캐릭터
const ROWS = ["...HHHHHH...", "..HHHHHHHH..", "..HHSSSSHH..", "..HSESSESH..", "...SSSSSS...", "....SSSS....", "..TTTTTTTT..", ".TTTTTTTTTT.",
  ".STTTTTTTTS.", ".STTTTTTTTS.", "..TTTTTTTT..", "..PPPPPPPP..", "..PPP..PPP..", "..PPP..PPP..", "..BBB..BBB.."];
const LONG = { 3: ".HHSESSESHH.", 4: ".HHSSSSSSHH.", 5: ".HH.SSSS.HH." };
const spriteCache = new Map();
function sprite(a, w = 24) {
  const key = `${a.id}:${w}`;
  if (spriteCache.has(key)) return spriteCache.get(key);
  const col = { H: a.look[0], S: SKIN, E: "#222", T: a.look[1], P: "#3b3f58", B: "#2a2a2a" };
  let rects = "";
  ROWS.forEach((row, y) => {
    const r = a.long && LONG[y] ? LONG[y] : row;
    let x = 0;
    while (x < 12) {
      const c = r[x];
      if (c === ".") { x++; continue; }
      let e = x;
      while (e < 12 && r[e] === c) e++;
      rects += `<rect x="${x}" y="${y}" width="${e - x}" height="1" fill="${col[c]}"/>`;
      x = e;
    }
  });
  const svg = `<svg class="spr" viewBox="0 0 12 15" width="${w}" height="${w * 1.25}" shape-rendering="crispEdges">${rects}</svg>`;
  spriteCache.set(key, svg);
  return svg;
}
const A = (id) => R?.agents.find((a) => a.id === id);
const T = (id) => R?.teams.find((t) => t.id === id);

// ------------------------------------------------------------------ 마크다운 (안전하게: 먼저 escape)
function md(s) {
  let h = esc(s || "");
  h = h.replace(/```([\s\S]*?)```/g, (_, c) => `<pre>${c}</pre>`);
  const lines = h.split("\n");
  const out = [];
  let tbl = [];
  const flush = () => {
    if (!tbl.length) return;
    const rows = tbl;
    out.push(`<table class="of-md-t">${rows.map((r, i) => `<tr>${r.replace(/^\||\|$/g, "").split("|").map((c) => (i ? `<td>${c.trim()}</td>` : `<th>${c.trim()}</th>`)).join("")}</tr>`).join("")}</table>`);
    tbl = [];
  };
  for (const l of lines) {
    if (/^\s*\|.*\|\s*$/.test(l)) { if (/^\s*\|[\s:|-]+\|\s*$/.test(l)) continue; tbl.push(l.trim()); continue; }
    flush();
    if (/^#{1,4}\s/.test(l)) out.push(`<b class="of-h">${l.replace(/^#+\s/, "")}</b>`);
    else if (/^\s*[-*•]\s/.test(l)) out.push(`<div class="of-li">• ${l.replace(/^\s*[-*•]\s/, "")}</div>`);
    else out.push(l ? `<div>${l}</div>` : "<div class='of-sp'></div>");
  }
  flush();
  return out.join("").replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
}

// ------------------------------------------------------------------ 상태 폴링
async function poll() {
  if (!visible) return;
  try {
    const d = await api(`/api/office/state?since=${cursor}`);
    S = d;
    cursor = Math.max(cursor, d.cursor);
    let fresh = false;
    for (const e of d.log) {
      const prev = LOG.get(e.id);
      if (!prev || (e.rev || 0) !== (prev.rev || 0)) fresh = true;
      LOG.set(e.id, e);
    }
    if (LOG.size > 1500) [...LOG.keys()].slice(0, LOG.size - 1200).forEach((k) => LOG.delete(k));
    renderTop();
    renderFloor();
    if (tab === "log" && fresh) renderLog();
    if (tab === "term" && Date.now() - (poll.termAt || 0) > 15000 && !document.querySelector("#v-office .of-pane select:focus")) { poll.termAt = Date.now(); renderTerm().catch(() => {}); }
  } catch (e) {
    $("#of-status").textContent = "서버 응답 없음: " + e.message;
  }
}

function renderTop() {
  const d = S;
  const m = d.meeting;
  $("#of-mode").textContent = m ? `회의 중 · #${m.name}` : d.job || d.team_job ? "업무 중" : "자동 운영";
  $("#of-mode").className = m ? "of-rec on" : "of-rec";
  const st = [];
  if (!d.ai) st.push("⚠ AI 키 없음 — 코드 업무(차트·백테스트·데이터)만 합니다 · 'AI 배정' 탭에서 키 넣기");
  if (d.paused) st.push(`⏸ AI 한도로 ${Math.ceil(d.paused / 60)}분 쉬는 중 (질문은 받음)`);
  if (d.job_ko) st.push(`▶ 지금: ${d.job_ko}`);
  if (d.team_job) st.push(`▶ ${T(d.team_job)?.name || d.team_job} 업무`);
  if (m) st.push(`🎙 ${T(m.room)?.name || "전체"} · ${m.done.length}/${m.order.length} 발언 · 대기 ${d.queue}`);
  else st.push(d.cfg.auto ? `다음 자동 회의 ${d.next_auto_min ?? "-"}분 뒤 · 다음 업무: ${d.next_job}` : "자동 회의 꺼짐 · 메시지를 보내면 바로 회의합니다");
  $("#of-status").textContent = st.join("  ·  ");
  const u = d.usage;
  $("#of-foot").innerHTML = `오늘 AI 호출 <b>${u.calls}</b>/${d.cfg.call_max} · 회의 ${u.meetings} (자동 ${u.auto}/${d.cfg.daily_max}) · 수다 ${u.chats}/${d.cfg.chat_max} · 팀 회의 ${u.team_meet || 0}/${d.cfg.team_meet_max}
    · 예측 채점 ${d.forecast.n}건${d.forecast.rate != null ? ` 적중 ${d.forecast.rate}%` : ""} · 파이프라인 ${Object.entries(d.pipe || {}).map(([k, v]) => `${STAGE[k.replace("c_", "")] || k}${k.startsWith("c_") ? "(커스텀)" : ""} ${v}`).join(" · ") || "-"}`;
  $("#of-tab-growth").textContent = `성장 과제${d.backlog_open ? ` ${d.backlog_open}` : ""}`;
}
const STAGE = { backtest: "백테스트 대기", demo: "데모", candidate: "승인 대기", live: "실거래", rejected: "불통과", retired: "퇴출" };

// ------------------------------------------------------------------ 사무실 바닥
function renderFloor() {
  const el = $("#of-floor");
  if (!R || !S) return;
  const m = S.meeting;
  const talking = new Set(m ? m.order : []);
  const huddle = new Set(S.huddle ? S.huddle.ids : []);
  if (!el.dataset.built) {
    el.innerHTML = R.teams.map((t) => `<div class="of-zone" data-team="${t.id}" style="--tc:${t.color}">
      <div class="of-zh"><i></i><b>${esc(t.name)}</b><span class="dim">${R.agents.filter((a) => a.team === t.id).length}명</span><div class="grow"></div>
        <button class="flat sm" data-run="${t.id}" title="이 팀 업무 지금 시키기">▶</button></div>
      <div class="of-desks">${R.agents.filter((a) => a.team === t.id).map((a) => `<div class="of-ag${a.lead ? " lead" : ""}" data-ag="${a.id}" title="${esc(a.name)} · ${esc(a.title)}">
        <div class="of-bub" hidden></div>${sprite(a)}<span class="of-nm">${a.lead ? "♛" : ""}${esc(a.name)}</span></div>`).join("")}</div></div>`).join("");
    el.dataset.built = "1";
  }
  $("#of-meet").innerHTML = m ? `<div class="of-meet-h">🎙 회의 · #${esc(m.name)} <span class="dim">${esc(T(m.room)?.name || "")}</span></div>
      <div class="of-meet-row">${m.order.map((id, i) => { const a = A(id); return a ? `<div class="of-seat ${m.speaking === id ? "on" : m.done.includes(id) ? "done" : ""}" data-ag="${id}">${sprite(a, 28)}<span>${esc(a.name)}</span><small>${i === m.order.length - 1 && id === R.closer ? "정리" : esc(a.title.split(" · ")[0]).slice(0, 10)}</small></div>` : ""; }).join("<i class='of-arrow'>→</i>")}</div>`
    : S.presenting ? `<div class="of-meet-h">📢 ${esc(S.presenting.title)} — 민재(CSO)가 발표 중</div>` : `<div class="of-meet-h dim">회의 없음 · 팀마다 정해진 업무를 돌아가며 하는 중</div>`;
  const bubbles = S.agents || {};
  $$(".of-ag", el).forEach((n) => {
    const id = n.dataset.ag, b = bubbles[id];
    n.classList.toggle("talk", talking.has(id));
    n.classList.toggle("hud", huddle.has(id));
    n.classList.toggle("busy", !!(b && b.busy));
    const bb = n.querySelector(".of-bub");
    if (b) { bb.hidden = false; bb.textContent = b.bubble; } else bb.hidden = true;
  });
  $$(".of-zone", el).forEach((z) => z.classList.toggle("on", !!(m && z.dataset.team === m.room) || z.dataset.team === S.team_job));
}

// ------------------------------------------------------------------ 회의록
function chanOptions() {
  const sel = $("#of-ch");
  sel.innerHTML = `<option value="all">#전체</option><option value="work">#업무(관찰)</option><option value="hq">#총괄</option>`
    + R.teams.map((t) => `<option value="${t.id}">#${esc(t.name)}</option>`).join("");
  sel.value = ch;
}

function entryHtml(e) {
  const a = A(e.agent), t = T(e.ch);
  const who = a ? `<span class="of-who" style="color:${T(a.team)?.color}">${a.lead ? "♛" : ""}${esc(a.name)}</span><span class="dim"> ${esc(a.title)}${e.model ? " · " + esc(e.model.split(":").slice(1).join(":").slice(-28)) : ""} · ${hhmm(e.t)}</span>` : "";
  const room = ch === "all" && t ? `<span class="of-room" style="--tc:${t.color}">#${esc(t.name)}</span>` : "";
  switch (e.kind) {
    case "user": return `<div class="of-e user"><div class="of-av me">나</div><div><div>${room}<span class="dim">${hhmm(e.t)}</span></div><div class="of-bubtxt">${md(e.text)}</div></div></div>`;
    case "system": case "alert": return `<div class="of-e sys">${room}${esc(e.text)}</div>`;
    case "divider": return `<div class="of-e div ${e.chat ? "chat" : ""}">— ${room}${esc(e.text)} —</div>`;
    case "work": return `<div class="of-e work">${room}${a ? `<b>${esc(a.name)}</b> ` : ""}${esc(e.icon || "")} ${e.url ? `<a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.text)}</a>` : esc(e.text)}${e.src ? ` <span class="dim">· ${esc(e.src)}</span>` : ""} <span class="dim">${hhmm(e.t)}</span></div>`;
    case "trade": case "pipe": return `<div class="of-e trade">${room}${a ? `<b>${esc(a.name)}</b> ` : ""}${esc(e.text)} <span class="dim">${hhmm(e.t)}</span></div>`;
    case "task": return `<div class="of-e work">${room}🌱 과제 ${{ todo: "등록", doing: "시작", done: "완료" }[e.status] || ""}: <b>${esc(e.title)}</b>${e.result ? ` — ${esc(e.result.slice(0, 160))}` : ""}</div>`;
    case "files": return `<div class="of-e card"><div class="of-ch">💾 ${esc(e.title)} ${a ? `· ${esc(a.name)}` : ""} <span class="dim">${hhmm(e.t)}</span></div>
      ${e.files?.length ? `<div class="dim">${e.files.map((f) => `<a href="/api/office/results/file?path=${encodeURIComponent(f)}" download>${esc(f)}</a>`).join(" · ")}</div>` : ""}${e.md ? `<div class="of-md">${md(e.md)}</div>` : ""}</div>`;
    case "report": return `<div class="of-e card rep"><div class="of-ch">📢 ${esc(e.title)} <span class="dim">${hhmm(e.t)}</span></div><div class="of-md clamp">${md(e.text)}</div></div>`;
    case "bt": {
      const row = (n, s) => s ? `<tr><td>${n}</td><td class="${(s.ret ?? 0) >= 0 ? "up" : "down"}">${s.ret ?? "-"}%</td><td>${s.dd ?? "-"}%</td><td>${s.win ?? "-"}%</td><td>${s.pf ?? "-"}</td><td>${s.n ?? "-"}</td></tr>` : "";
      return `<div class="of-e card ${e.pass ? "pass" : "fail"}">${room}<div class="of-ch">${e.pass ? "✅ 검증 통과" : "❌ 불통과"} · ${esc(e.name)} ${e.grade ? `<span class="of-grade g-${esc(e.grade)}">시나리오 ${esc(e.grade)}</span>` : ""}</div>
        <div class="dim">${esc(e.mname || e.market)} ${esc(e.tf)}봉 · 레버리지 ${e.lev}배 · 개발 ${esc(A(e.author)?.name || e.author || "-")} · ${esc(e.hist || "")}</div>
        <table class="of-bt"><tr><th></th><th>수익</th><th>최대낙폭</th><th>승률</th><th>손익비</th><th>거래</th></tr>${row("전체", e.all)}${row("개발 70%", e.is_)}${row("검증 30%", e.oos)}</table>
        <div class="of-reasons">${(e.reasons || []).map((r) => `<div>${esc(r)}</div>`).join("")}</div>
        ${e.scen ? `<details><summary>시나리오 (모든 레버리지 · 장세 · 연도 · 스트레스)</summary><pre>${esc(e.scen)}</pre></details>` : ""}
        <details><summary>전략 JSON</summary><pre>${esc(JSON.stringify(e.spec, null, 1))}</pre></details></div>`;
    }
    case "term": {
      const p = e.plan || {}, x = p.entry;
      return `<div class="of-e card term">${room}<div class="of-ch">🎯 ${esc(e.symbol)} 터미널 지표 147종 타점 <span class="of-grade ${p.side === "long" ? "g-견고" : "g-취약"}">${p.side === "long" ? "롱" : "숏"}</span></div>
        <div>${esc(p.verdict || "")}</div>
        <div class="dim">${Object.entries(e.per_tf || {}).map(([iv, a]) => `${iv} ${a.score > 0 ? "+" : ""}${a.score}`).join(" · ")} · 전체 ${p.trend > 0 ? "+" : ""}${p.trend} ${esc(p.trend_label || "")}</div>
        ${x ? `<div class="dim">${esc(x.trigger)} · ${esc(x.reason)}</div>` : ""}
        <button class="flat sm" data-chart="${esc(e.symbol)}" data-iv="${esc(x?.tf || "1h")}">차트에서 보기</button></div>`;
    }
    case "ml": return `<div class="of-e card">${room}<div class="of-ch">🧠 머신러닝 · ${esc(e.market)} ${esc(e.tf)} · ${esc(e.model)} <span class="of-grade g-${e.edge === "edge" ? "견고" : e.edge === "weak" ? "보통" : "취약"}">${{ edge: "우위", weak: "약한 신호", none: "우위 없음" }[e.edge]}</span></div>
      <div class="of-tiles"><div><small>정확도</small><b>${e.acc}%</b></div><div><small>기준(동전)</small><b>${e.base}%</b></div><div><small>차이</small><b>${(e.acc - e.base).toFixed(1)}%p</b></div><div><small>AUC</small><b>${e.auc ?? "-"}</b></div></div>
      <details><summary>자세히</summary><pre>${esc(e.text)}</pre></details></div>`;
    case "forecast": return `<div class="of-e card">${room}<div class="of-ch">🔮 ${e.scored ? "예측 채점" : "24시간 방향 예측"}</div>
      ${e.items.map((x) => `<div class="of-fc">${{ up: "▲", down: "▼", flat: "■" }[x.dir]} <b>${esc(x.asset)}</b> ${{ up: "상승", down: "하락", flat: "횡보" }[x.dir]} ${x.prob}% <span class="dim">${esc(x.by)} · 마감 ${mdhm(x.due)}</span> ${x.result ? `<b class="${x.result === "hit" ? "up" : "down"}">${x.result === "hit" ? "적중" : "빗나감"} ${x.ret > 0 ? "+" : ""}${x.ret}%</b>` : "<span class='dim'>대기</span>"}</div>`).join("")}
      ${e.score?.n ? `<div class="dim">채점 ${e.score.n}건 · 적중 ${e.score.hit} (${e.score.rate}%) · Brier ${e.score.brier} · 1배 가상 손익 ${e.score.paper}%</div>` : ""}</div>`;
    case "agent": {
      if (e.chat) return `<div class="of-e chatl">${a ? sprite(a, 16) : ""}<b style="color:${T(a?.team)?.color}">${esc(a?.name || "")}</b> ${esc(e.text)}</div>`;
      const steps = (e.steps || []).map((s) => `<div class="of-step ${s.status}">${esc(s.icon || "🔧")} ${esc(s.act)} ${s.status === "running" ? "하는 중…" : s.status === "error" ? `실패: ${esc((s.summary || "").slice(0, 60))}` : `→ ${esc(s.summary || "")}`}
        ${(s.sources || []).slice(0, 3).map((x) => `<a href="${esc(x.url)}" target="_blank" rel="noopener">📰 ${esc(x.title.slice(0, 50))}</a>`).join(" ")}</div>`).join("");
      return `<div class="of-e agent" data-id="${e.id}"><div class="of-av">${a ? sprite(a, 26) : ""}</div><div class="of-ebody">${room}${who}
        ${e.think ? `<div class="of-think">💭 ${esc(e.think)}</div>` : ""}${steps}
        ${e.live ? `<div class="dim of-typing">생각 중<i>.</i><i>.</i><i>.</i></div>` : `<div class="of-md clamp">${md(e.text)}</div>`}
        ${e.live ? "" : `<div class="of-rate"><button class="flat sm ${e.rating === 1 ? "on" : ""}" data-rate="${e.id}" data-v="1">👍</button><button class="flat sm ${e.rating === -1 ? "on" : ""}" data-rate="${e.id}" data-v="-1">👎</button></div>`}</div></div>`;
    }
    default: return "";
  }
}

function renderLog() {
  const box = $("#of-log");
  const near = box.scrollHeight - box.scrollTop - box.clientHeight < 120;
  const items = [...LOG.values()].sort((a, b) => a.id - b.id).filter((e) =>
    ch === "all" ? e.kind !== "work" : ch === "work" ? e.kind === "work" : e.ch === ch).slice(-180);
  box.innerHTML = items.length ? items.map(entryHtml).join("") : `<div class="empty">아직 기록이 없습니다. 아래에 질문을 보내거나 '지금 일 시키기'를 눌러 보세요.<br>AI 키가 없으면 차트·백테스트·데이터 같은 코드 업무만 돌아갑니다.</div>`;
  $$(".of-md.clamp", box).forEach((m) => { if (m.scrollHeight > m.clientHeight + 4) { const b = document.createElement("button"); b.className = "flat sm of-more"; b.textContent = "펼치기"; b.onclick = () => { m.classList.toggle("clamp"); b.textContent = m.classList.contains("clamp") ? "펼치기" : "접기"; }; m.after(b); } });
  if (near) box.scrollTop = box.scrollHeight;
}

// ------------------------------------------------------------------ 터미널 지표 추세·타점
let termOpen = null;
async function renderTerm() {
  const d = await api("/api/office/termind");
  const sc = (v) => `<b class="${v > 0 ? "up" : v < 0 ? "down" : ""}">${v > 0 ? "+" : ""}${v}</b>`;
  const items = d.items.slice().sort((a, b) => Math.abs(b.trend) - Math.abs(a.trend));
  const tfs = ["15m", "1h", "4h", "1d"];
  $("#of-pane").innerHTML = `<div class="of-pane-h"><b>터미널 지표 추세·타점</b><span class="dim">차트 터미널의 보조지표 147종 × 15분·1시간·4시간·일봉 · 코인 하나씩 ${d.interval_sec}초마다 실시간</span>
      <div class="grow"></div><select id="tm-sym">${d.coins.map((c) => `<option>${c}</option>`).join("")}</select><button class="sm pri" id="tm-scan">지금 계산</button>
      <a class="btn sm" href="/api/office/results" id="tm-files">기록 CSV</a></div>
    ${d.available ? "" : `<div class="help">⚠ 지표 엔진을 열지 못했습니다: ${esc(d.error)}</div>`}
    <div class="help">지표마다 방향 표(가격 위 선은 가격이 선 위/아래, 화살표 신호는 최근 신호 방향, 오실레이터는 기준선 위/아래)를 모아 그룹별 평균 → 가중 합 = 점수(-100~+100).
      타점은 4시간·일봉 추세 방향으로만: 작은 봉이 침체(롱)·과열(숏)로 되돌리면 눌림 진입, 합의가 강하면 추세 추종. 손절은 ATR·스윙, 목표는 지표가 그린 레벨. 손익비 1.5 미만이면 관망.
      새 타점은 트레이드 차트의 AI 시그널(보라 표시)로도 올라가 가상 체결로 채점됩니다.</div>
    <table class="of-tbl"><tr><th>코인</th><th>전체</th>${tfs.map((t) => `<th>${t}</th>`).join("")}<th>판정 · 타점</th><th></th></tr>
    ${items.map((p) => `<tr data-tm="${p.symbol}" style="cursor:pointer"><td><b>${p.symbol.replace("USDT", "")}</b><div class="dim">${mdhm(p.time)}</div></td><td>${sc(p.trend)}<div class="dim">${esc(p.trend_label)}</div></td>
      ${tfs.map((t) => `<td>${p.per_tf[t] ? sc(p.per_tf[t].score) : "-"}${p.per_tf[t] ? `<div class="dim">${p.per_tf[t].up}↑ ${p.per_tf[t].down}↓</div>` : ""}</td>`).join("")}
      <td>${esc(p.verdict || "")}${p.entry ? `<div class="dim">${esc(p.entry.trigger)}</div>` : ""}</td>
      <td><button class="flat sm" data-chart="${p.symbol}" data-iv="${p.entry?.tf || "1h"}">차트</button></td></tr>
      ${termOpen === p.symbol ? `<tr><td colspan="8">${tfs.filter((t) => p.per_tf[t]).map((t) => { const a = p.per_tf[t]; return `<div class="of-sub">${t} ${sc(a.score)} ${esc(a.label)} <span class="dim">투표 ${a.voters}개</span></div>
        <div class="dim">${Object.entries(a.groups).map(([g, v]) => `${esc(g)} ${v > 0 ? "+" : ""}${v}`).join(" · ")}</div>
        ${a.overbought.length || a.oversold.length ? `<div>과열: ${esc(a.overbought.join(", ") || "-")} · 침체: ${esc(a.oversold.join(", ") || "-")}</div>` : ""}
        <div>강한 표: ${a.top.map((x) => `${esc(x.name)} <span class="${x.vote > 0 ? "up" : "down"}">${x.vote > 0 ? "+" : ""}${x.vote}</span>`).join(", ")}</div>
        ${Object.keys(a.regime || {}).length ? `<div class="dim">장세: ${Object.entries(a.regime).map(([k, v]) => `${esc(k)} ${v}`).join(" · ")}</div>` : ""}`; }).join("")}
        ${p.entry ? `<div class="of-sub">타점</div><div>${p.entry.action === "long" ? "롱" : "숏"} ${esc(p.entry.kind)} · 진입 ${p.entry.entry} · 손절 ${p.entry.stop} · 목표 ${p.entry.targets.map((t) => `${(+t.price).toPrecision(6)}(${esc(t.src.slice(0, 18))})`).join(" / ")} · 손익비 ${p.entry.rr} · 확신 ${p.entry.confidence}%</div>` : ""}</td></tr>` : ""}`).join("")
      || `<tr><td colspan="8" class="dim">계산 중… (코인 하나씩 ${d.interval_sec}초마다. '지금 계산'을 누르면 바로)</td></tr>`}</table>`;
  $("#tm-scan").onclick = (e) => busy(e.target, async () => { await api(`/api/office/termind/scan?symbol=${$("#tm-sym").value}`, { method: "POST" }); termOpen = $("#tm-sym").value; renderTerm(); });
  $("#tm-files").onclick = (ev) => { ev.preventDefault(); setTab("results"); };
  $$("[data-tm]").forEach((r) => (r.onclick = (ev) => { if (ev.target.closest("[data-chart]")) return; termOpen = termOpen === r.dataset.tm ? null : r.dataset.tm; renderTerm(); }));
}

// ------------------------------------------------------------------ 파이프라인
async function renderPipe() {
  const d = await api("/api/office/pipeline");
  const items = d.items.filter((p) => pipeCustom === "all" || (pipeCustom === "custom") === p.custom);
  const cols = [["backtest", "🧪 백테스트 대기"], ["demo", "📗 데모거래"], ["candidate", "🏁 실거래 승인 대기"], ["live", "💰 실거래(승인됨)"], ["rejected", "❌ 불통과"], ["retired", "📕 데모 퇴출"]];
  const card = (p) => {
    const bt = p.bt || {}, dm = p.demo || {};
    return `<div class="of-pc ${p.custom ? "custom" : ""}"><b>${esc(p.name)}</b>${p.custom ? ' <span class="of-tag">커스텀</span>' : ""}
      <div class="dim">${esc(p.spec.symbol)} ${esc(p.spec.interval)} · ${esc(A(p.author)?.name || p.author)} · ${mdhm(p.created)}</div>
      ${bt.oos ? `<div>검증 30%: ${bt.oos.ret ?? "-"}% · 손익비 ${bt.oos.pf ?? "-"} · ${bt.oos.n ?? "-"}건 ${bt.grade ? `· 시나리오 ${esc(bt.grade)}` : ""}</div>` : ""}
      ${dm.trades != null ? `<div>데모: ${dm.trades}건 · ${dm.ret > 0 ? "+" : ""}${dm.ret}% · 손익비 ${dm.pf ?? "-"} · 낙폭 ${dm.dd}% · ${dm.days}일</div>` : ""}
      ${p.history?.length ? `<div class="dim">${esc(p.history[p.history.length - 1].why || "")}</div>` : ""}</div>`;
  };
  $("#of-pane").innerHTML = `<div class="of-pane-h"><b>매매법 파이프라인</b><span class="dim">개발 → 백테스트(전체 과거 · 70/30 · 시나리오) → 데모(실제 시세 가상 체결) → 승인 대기 → 실거래(사람 승인)</span>
      <div class="grow"></div><select id="of-pc-f"><option value="all">전체</option><option value="basic">보조지표</option><option value="custom">커스텀 지표</option></select>
      <a class="btn sm" href="/api/office/results/file?path=pipeline.csv" download>CSV 받기</a></div>
    <div class="help">데모 승격 기준: 거래 ${d.rules.promote.trades}건 이상 · 손익비 ${d.rules.promote.pf} 이상 · 수익 > 0 · 낙폭 ${d.rules.promote.dd}% 미만 · ${d.rules.promote.days}일 이상. 퇴출: 낙폭 ${d.rules.retire.dd}% 초과 또는 ${d.rules.retire.trades}건 이상인데 손익비 ${d.rules.retire.pf} 미만. 동시에 데모 ${d.rules.demo_max}개까지.</div>
    <div class="of-cols">${cols.map(([k, l]) => { const xs = items.filter((p) => p.stage === k); return `<div class="of-col"><div class="of-col-h">${l} <span class="dim">${xs.length}</span></div>${xs.slice(0, 40).map(card).join("") || "<div class='dim'>없음</div>"}</div>`; }).join("")}</div>`;
  $("#of-pc-f").value = pipeCustom;
  $("#of-pc-f").onchange = (e) => { pipeCustom = e.target.value; renderPipe(); };
}

// ------------------------------------------------------------------ 실거래
async function renderLive() {
  const d = await api("/api/live");
  const s = d.settings;
  $("#of-pane").innerHTML = `<div class="of-pane-h"><b>실거래</b><span class="of-tag ${s.enabled ? "warn" : ""}">${s.enabled ? "켜짐" : "꺼짐"}</span><span class="of-tag">${s.testnet ? "테스트넷(가짜 돈)" : "실제 돈"}</span>
      <div class="grow"></div><button class="danger sm" id="lv-kill">🛑 비상 정지 (모두 청산)</button></div>
    <div class="help">데모거래를 통과한 매매법만 여기 올라옵니다. <b>사람이 승인한 것만</b> 실거래로 따라 주문하고, AI 는 켜거나 승인할 수 없습니다.
      키는 settings.txt 의 <code>BINANCE_API_KEY</code> / <code>BINANCE_API_SECRET</code> — 선물 거래 권한만 주고 <b>출금 권한은 절대 주지 마세요</b>. 키: ${d.has_keys ? "✅ 있음" : "❌ 없음"} · 접속: ${esc(d.base)}</div>
    <div class="of-form">
      <label>주문 한 번 최대 (USDT)<input id="lv-o" type="number" value="${s.max_order_usdt}"></label>
      <label>전체 노출 한도 (USDT)<input id="lv-t" type="number" value="${s.max_total_usdt}"></label>
      <label>최대 레버리지<input id="lv-l" type="number" value="${s.max_leverage}" min="1" max="20"></label>
      <label>하루 손실 한도 (USDT)<input id="lv-d" type="number" value="${s.daily_loss_usdt}"></label>
      <button class="sm" id="lv-save">한도 저장</button>
      <button class="sm ${s.enabled ? "" : "pri"}" id="lv-on">${s.enabled ? "실거래 끄기" : "실거래 켜기"}</button>
      <button class="sm" id="lv-net">${s.testnet ? "테스트넷 끄기(실제 돈)" : "테스트넷으로 돌아가기"}</button></div>
    <div class="dim">오늘 실현 손익(추정) ${d.realized_today} USDT · 열린 실거래 ${Object.keys(d.positions).length}개</div>
    <table class="of-tbl"><tr><th>매매법</th><th>코인</th><th>단계</th><th>데모 성과</th><th>지금 데모</th><th></th></tr>
      ${d.items.map((x) => `<tr><td>${esc(x.name)}${x.custom ? ' <span class="of-tag">커스텀</span>' : ""}</td><td>${esc(x.symbol)}</td><td>${STAGE[x.stage]}</td>
        <td>${x.demo ? `${x.demo.trades}건 · ${x.demo.ret}% · PF ${x.demo.pf}` : "-"}</td><td>${x.side > 0 ? "롱" : x.side < 0 ? "숏" : "대기"}</td>
        <td><button class="sm ${x.approved ? "" : "pri"}" data-appr="${x.id}" data-ok="${x.approved ? 0 : 1}">${x.approved ? "승인 취소" : "승인"}</button></td></tr>`).join("") || `<tr><td colspan="6" class="dim">아직 데모를 통과한 매매법이 없습니다</td></tr>`}</table>
    <div class="of-sub">기록</div><div class="of-lvlog">${d.log.map((l) => `<div><span class="dim">${mdhm(l.t)}</span> ${esc(l.text)}</div>`).join("") || "<div class='dim'>없음</div>"}</div>`;
  const save = (body) => api("/api/live/settings", { method: "POST", body }).then(renderLive).catch((e) => toast("실거래", e.message, "err"));
  $("#lv-save").onclick = () => save({ max_order_usdt: +$("#lv-o").value, max_total_usdt: +$("#lv-t").value, max_leverage: +$("#lv-l").value, daily_loss_usdt: +$("#lv-d").value });
  $("#lv-on").onclick = () => {
    if (s.enabled) return save({ enabled: false });
    const c = prompt(`실거래를 켭니다 (${s.testnet ? "테스트넷 — 가짜 돈" : "실제 돈!"}).\n승인한 매매법의 신호대로 주문이 나갑니다. 계속하려면 '실거래 켜기' 를 입력하세요.`);
    if (c) save({ enabled: true, confirm: c.trim() });
  };
  $("#lv-net").onclick = () => {
    if (!s.testnet) return save({ testnet: true });
    const c = prompt("테스트넷을 끄면 실제 돈으로 주문합니다. 손실은 되돌릴 수 없습니다. 계속하려면 '실제 돈' 을 입력하세요.");
    if (c) save({ testnet: false, confirm: c.trim() });
  };
  $("#lv-kill").onclick = () => confirm("모든 실거래 포지션을 시장가로 청산하고 실거래를 끕니다.") && api("/api/live/kill", { method: "POST" }).then(renderLive);
  $$("[data-appr]").forEach((b) => (b.onclick = () => {
    const ok = b.dataset.ok === "1";
    if (ok && !confirm("이 매매법을 실거래로 승인합니다. 실거래가 켜져 있으면 다음 신호부터 주문이 나갑니다.")) return;
    busy(b, () => api(`/api/live/approve/${b.dataset.appr}?ok=${ok}`, { method: "POST" }).then(renderLive));
  }));
}

// ------------------------------------------------------------------ 결과 · 다운로드
async function renderResults() {
  const d = await api("/api/office/results");
  const bycat = {};
  d.files.forEach((f) => (bycat[f.category] = bycat[f.category] || []).push(f));
  const size = (n) => n > 1e6 ? `${(n / 1e6).toFixed(1)}MB` : n > 1e3 ? `${(n / 1e3).toFixed(0)}KB` : `${n}B`;
  $("#of-pane").innerHTML = `<div class="of-pane-h"><b>결과 · 다운로드</b><div class="grow"></div>
      <a class="btn sm pri" href="/api/office/results/zip" download>전체 ZIP 받기</a>${d.can_open ? '<button class="sm" id="rs-open">📂 폴더 열기</button>' : ""}</div>
    <div class="help">모든 결과는 이 컴퓨터(서버)의 아래 폴더에 저장됩니다. 파일 이름을 누르면 바로 받습니다. CSV 는 엑셀에서 바로 열립니다.<br><code class="of-path">${esc(d.root)}</code>
      <button class="flat sm" id="rs-copy">경로 복사</button></div>
    ${d.categories.concat(["기타"]).filter((c) => bycat[c]).map((c) => `<div class="of-sub">${esc(c)} <span class="dim">${bycat[c].length}개</span></div>
      <div class="of-files">${bycat[c].slice(0, 60).map((f) => `<a href="/api/office/results/file?path=${encodeURIComponent(f.path)}" download><span>${esc(f.path)}</span><span class="dim">${size(f.size)} · ${mdhm(f.mtime)}</span></a>`).join("")}</div>`).join("")
      || "<div class='empty'>아직 결과 파일이 없습니다. 팀들이 일하면 여기 쌓입니다.</div>"}`;
  $("#rs-copy").onclick = () => navigator.clipboard?.writeText(d.root).then(() => toast("경로를 복사했습니다", d.root));
  if ($("#rs-open")) $("#rs-open").onclick = (e) => busy(e.target, () => api("/api/office/results/open", { method: "POST" }));
}

// ------------------------------------------------------------------ 성장 과제 · 발표
async function renderGrowth() {
  const d = await api("/api/office/backlog");
  const col = (st, l) => { const xs = d.items.filter((b) => b.status === st); return `<div class="of-col"><div class="of-col-h">${l} <span class="dim">${xs.length}</span></div>${xs.slice(0, 50).map((b) => `<div class="of-pc"><b>${esc(b.title)}</b><div class="dim">${esc(T(b.team)?.name || b.team)} · ${esc(A(b.owner)?.name || "")} · ${mdhm(b.t)}</div>${b.why ? `<div>${esc(b.why)}</div>` : ""}${b.result ? `<div>→ ${esc(b.result.slice(0, 200))}</div>` : ""}</div>`).join("") || "<div class='dim'>없음</div>"}</div>`; };
  $("#of-pane").innerHTML = `<div class="of-pane-h"><b>성장 과제</b><span class="dim">팀장이 회고에서 부족한 점을 과제로 만들고, 담당자가 다음 주기에 해냅니다</span></div>
    <div class="of-cols three">${col("doing", "🔨 진행 중")}${col("todo", "📋 할 일")}${col("done", "✅ 완료")}</div>`;
}

async function renderReports() {
  const d = await api("/api/office/reports");
  $("#of-pane").innerHTML = `<div class="of-pane-h"><b>시간별 성과 발표</b><div class="grow"></div><button class="sm pri" id="rp-now">지금 발표하기</button></div>
    ${d.items.map((r) => `<details class="of-rep" ${r === d.items[0] ? "open" : ""}><summary><b>${esc(r.title)}</b> <span class="dim">${mdhm(r.t)} · 팀 ${r.sections.length}개</span></summary>
      <div class="of-md">${md(r.text)}</div>${r.sections.map((s) => `<div class="of-repsec"><b>${esc(s.name)}</b> <span class="dim">팀장 ${esc(s.lead)}</span>${s.items.map((x) => `<div>• ${esc(x)}</div>`).join("")}${s.next.length ? `<div class="dim">다음: ${esc(s.next.join(" / "))}</div>` : ""}</div>`).join("")}</details>`).join("")
    || "<div class='empty'>아직 발표가 없습니다. 매시 정각 무렵 자동으로 발표합니다.</div>"}`;
  $("#rp-now").onclick = (e) => busy(e.target, async () => { await api("/api/office/report", { method: "POST" }); toast("발표를 준비합니다", "30초~1분 뒤 회의록과 이 탭에 나옵니다"); });
}

// ------------------------------------------------------------------ AI 배정 (직원·팀별 키·모델)
async function renderModels() {
  R = await api("/api/office/roster");
  const ks = R.key_slots;
  const sug = [...new Set([...(R.suggest?.nvidia || []), ...(R.suggest?.gemini || []), ...(R.suggest?.claude || [])])];
  const slotRoutes = [];
  for (const [p, arr] of Object.entries(ks)) for (const s of arr) slotRoutes.push(`${p}${s.slot === 1 ? "" : "#" + s.slot}:${p === "claude" ? "claude-opus-5-5" : "auto"}`);
  const opts = [...new Set([...slotRoutes, ...sug])];
  $("#of-pane").innerHTML = `<div class="of-pane-h"><b>직원 AI 배정</b><div class="grow"></div><button class="sm pri" id="md-even">키 골고루 나누기</button><button class="sm" id="md-save">저장</button></div>
    <div class="help">① 아래에서 공급자별로 키를 여러 개 넣습니다 (1번 = 기본 키, 2~9번 = 추가 키). 무료 키는 분당 한도가 <b>키마다 따로</b>라 여러 개를 나눠 쓰면 덜 막힙니다.<br>
      ② 팀마다 모델을 고릅니다. 형식: <code>공급자#키번호:모델</code> (예: <code>nvidia#2:auto</code> = NVIDIA 2번 키로 자동 모델, <code>gemini:auto</code> = Gemini 1번 키). 비우면 'AI 모델' 창의 기본 배정을 씁니다.<br>
      ③ 직원 한 명만 따로 정하려면 팀 이름을 눌러 펼친 뒤 그 사람 칸에 적습니다 (직원 &gt; 팀 &gt; 기본 순서). '키 골고루 나누기'는 넣어 둔 키들을 팀마다 차례로 나눠 줍니다.</div>
    <div class="of-keys">${["nvidia", "gemini", "claude"].map((p) => `<div class="of-key"><b>${{ nvidia: "NVIDIA (무료)", gemini: "Gemini (무료)", claude: "Claude" }[p]}</b>
      ${(ks[p] || []).map((s) => `<div class="dim">${s.slot}번 · ${esc(s.env)} · ${esc(s.masked)}</div>`).join("") || "<div class='dim'>키 없음</div>"}
      <div class="row"><select data-kp="${p}">${[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => `<option value="${n}">${n}번</option>`).join("")}</select><input data-kv="${p}" placeholder="키 붙여넣기 ('-' = 지우기)" style="flex:1"><button class="sm" data-kadd="${p}">넣기</button></div></div>`).join("")}</div>
    <datalist id="md-opts">${opts.map((o) => `<option value="${esc(o)}">`).join("")}</datalist>
    ${R.ai ? "" : `<div class="of-warn">⚠ 아직 AI 키가 하나도 없습니다. 위 칸에 키를 붙여넣고 '넣기'를 누르면 직원들에게 자동으로 골고루 배정됩니다. (키가 없으면 차트·백테스트·데이터 같은 코드 업무만 합니다)</div>`}
    <table class="of-tbl of-mtbl"><colgroup><col style="width:30%"><col style="width:34%"><col></colgroup><tr><th>팀</th><th>배정 모델</th><th>실제로 답한 AI (오늘)</th></tr>${R.teams.map((t) => { const us = R.agents.filter((a) => a.team === t.id && a.used); const ok = us.filter((a) => a.used.route).sort((x, y) => y.used.t - x.used.t);
      const calls = us.reduce((n, a) => n + a.used.calls, 0), fails = us.reduce((n, a) => n + a.used.fails, 0);
      return `<tr><td><button class="flat sm" data-mexp="${t.id}">▸</button> <span style="color:${t.color}">■</span> ${esc(t.name)}</td>
      <td><input list="md-opts" data-mk="team:${t.id}" value="${esc(R.models["team:" + t.id] || "")}" placeholder="기본 배정"></td>
      <td class="${ok.length ? "" : "dim"}">${ok.length ? `${esc(ok[0].used.route)} · ${calls}번${fails ? ` · 실패 ${fails}` : ""} · ${ago(ok[0].used.t)}` : fails ? `실패 ${fails}번 · ${esc(us[0].used.err || "")}` : "아직 없음"}</td></tr>
      <tr class="of-mrow" data-mt="${t.id}" hidden><td colspan="3"><div class="of-mgrid">${R.agents.filter((a) => a.team === t.id).map((a) => `<label>${a.lead ? "♛" : ""}${esc(a.name)} <span class="dim">${esc(a.title)}</span><input list="md-opts" data-mk="${a.id}" value="${esc(R.models[a.id] || "")}" placeholder="팀 배정"><span class="dim">${esc(usedText(a.used))}</span></label>`).join("")}</div></td></tr>`; }).join("")}</table>`;
  $$("[data-mexp]").forEach((b) => (b.onclick = () => { const r = $(`[data-mt="${b.dataset.mexp}"]`); r.hidden = !r.hidden; b.textContent = r.hidden ? "▸" : "▾"; }));
  $("#md-save").onclick = (e) => busy(e.target, async () => {
    const models = {};
    $$("[data-mk]").forEach((i) => { if (i.value.trim()) models[i.dataset.mk] = i.value.trim(); });
    await api("/api/office/cfg", { method: "POST", body: { models } });
    toast("저장했습니다", `${Object.keys(models).length}개 배정`);
  });
  $("#md-even").onclick = (e) => busy(e.target, async () => { await api("/api/office/models/even", { method: "POST" }); toast("키를 팀마다 나눴습니다"); renderModels(); });
  $$("[data-kadd]").forEach((b) => (b.onclick = () => busy(b, async () => {
    const p = b.dataset.kadd, v = $(`[data-kv="${p}"]`).value.trim(), slot = +$(`[data-kp="${p}"]`).value;
    if (!v) return toast("키를 붙여넣으세요");
    const r = await api("/api/ai/keys", { method: "POST", body: { [p === "claude" ? "anthropic" : p]: v, slot } });
    let even = "";
    if (v !== "-" && !Object.keys(R.models || {}).some((k) => k.startsWith("team:"))) {   // 아직 팀 배정이 없으면 넣은 키를 바로 팀마다 나눠 준다
      await api("/api/office/models/even", { method: "POST" }).then(() => (even = " · 팀마다 자동 배정함")).catch(() => {});
    }
    toast(v === "-" ? "키를 지웠습니다" : "키를 넣었습니다", (r.saved_to_file ? "settings.txt 에도 저장됨" : "이번 실행에만 적용 (settings.txt 위치를 찾지 못함)") + even);
    renderModels();
  })));
}

// ------------------------------------------------------------------ 직원 카드 · 팀 구성
const ago = (t) => { const m = Math.round((Date.now() / 1000 - t) / 60); return m < 1 ? "방금" : m < 60 ? `${m}분 전` : `${Math.round(m / 60)}시간 전`; };
// 직원이 실제로 답한 AI (키·모델) — 배정만 되고 안 쓰이는지 화면에서 바로 확인
const usedText = (u) => !u ? "아직 AI 호출 없음" : u.route ? `${u.route} · 오늘 ${u.calls}번 성공${u.fails ? ` · 실패 ${u.fails}번` : ""} · ${ago(u.t)}` : `실패 ${u.fails}번 · ${u.err || ""} · ${ago(u.t)}`;

async function agentCard(id) {
  R = await api("/api/office/roster").catch(() => R);
  const a = A(id);
  if (!a) return;
  const t = T(a.team);
  const box = $("#of-card");
  box.hidden = false;
  cardOpen = id;
  box.innerHTML = `<div class="of-cardin"><button class="flat of-x" id="of-cx">✕</button><div class="row" style="gap:12px">${sprite(a, 64)}
    <div><div style="font-size:16px"><b>${a.lead ? "♛ " : ""}${esc(a.name)}</b> ${a.lead ? "<span class='of-tag'>팀장</span>" : ""}</div><div class="dim">${esc(t.name)} · ${esc(a.title)}</div></div></div>
    <p>${esc(a.duty)}</p><dl class="of-dl"><dt>쓰는 도구</dt><dd>${esc(a.tools.join(", "))}</dd><dt>배정된 AI</dt><dd>${esc(a.model || "기본 배정 (막히면 다른 모델로 자동 전환)")} <button class="flat sm" id="of-to-models">바꾸기</button></dd>
    <dt>실제로 답한 AI</dt><dd class="${a.used?.route ? "" : "dim"}">${esc(R.ai ? usedText(a.used) : "AI 키 없음 — 'AI 배정' 탭에서 키를 넣으세요")}</dd>
    <dt>부르는 법</dt><dd>@${esc(a.name)}</dd></dl>
    <div class="of-sub">최근에 본 것</div>${(a.seen || []).slice().reverse().map((o) => `<div>${esc(o.icon)} ${o.url ? `<a href="${esc(o.url)}" target="_blank" rel="noopener">${esc(o.text)}</a>` : esc(o.text)} <span class="dim">${hhmm(o.t)}</span></div>`).join("") || "<div class='dim'>아직 없음</div>"}
    <div class="row" style="margin-top:10px"><button class="sm pri" id="of-ask-ag">이 사람에게 질문</button><button class="sm" id="of-run-team">이 팀 업무 시키기</button></div></div>`;
  $("#of-cx").onclick = () => (box.hidden = true);
  $("#of-to-models").onclick = () => { box.hidden = true; setTab("models"); };
  $("#of-ask-ag").onclick = () => { box.hidden = true; ch = a.team; chanOptions(); setTab("log"); $("#of-q").value = `@${a.name} `; $("#of-q").focus(); };
  $("#of-run-team").onclick = (e) => busy(e.target, () => api(`/api/office/team/${a.team}`, { method: "POST" }).then(() => toast(`${t.name} 업무를 시켰습니다`)));
}

function teamsModal() {
  const box = $("#of-card");
  box.hidden = false;
  box.innerHTML = `<div class="of-cardin wide"><button class="flat of-x" id="of-cx">✕</button><h3>팀 구성 · ${R.teams.length}개 팀 · ${R.agents.length}명</h3>
    <div class="help">질문 내용으로 담당자를 코드가 정하고, 투자·실행 판단은 담당 분석가 → 전략 총괄 → 반론 검토관 → 리스크 책임자 → 민재(CSO)가 정리합니다. 발언 속 @이름으로 동료를 부르면 그 사람이 회의에 들어옵니다. 매시 민재가 팀별 성과를 발표합니다.</div>
    <div class="of-teams">${R.teams.map((t) => `<div class="of-tcard" style="--tc:${t.color}"><b>${esc(t.name)}</b> <span class="dim">${R.agents.filter((a) => a.team === t.id).length}명</span><div class="dim">${esc(t.desc)}</div>
      ${R.agents.filter((a) => a.team === t.id).map((a) => `<div class="of-tm" data-ag="${a.id}">${sprite(a, 16)} ${a.lead ? "♛" : ""}${esc(a.name)} <span class="dim">${esc(a.title)}</span></div>`).join("")}</div>`).join("")}</div></div>`;
  $("#of-cx").onclick = () => (box.hidden = true);
}

// ------------------------------------------------------------------ 탭 · 설정
function setTab(t) {
  tab = t;
  $$("#of-tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === t));
  $("#of-logwrap").hidden = t !== "log";
  $("#of-pane").hidden = t === "log";
  const fn = { term: renderTerm, pipe: renderPipe, live: renderLive, results: renderResults, growth: renderGrowth, reports: renderReports, models: renderModels }[t];
  if (fn) fn().catch((e) => ($("#of-pane").innerHTML = `<div class="empty">${esc(e.message)}</div>`));
  else renderLog();
}

function settingsMenu() {
  const c = S?.cfg || {};
  const box = $("#of-set");
  box.hidden = !box.hidden;
  if (box.hidden) return;
  box.innerHTML = `<label><input type="checkbox" data-c="auto" ${c.auto ? "checked" : ""}> 자동 회의</label>
    <label>간격 <select data-c="every">${[15, 30, 60, 180].map((v) => `<option value="${v}" ${c.every === v ? "selected" : ""}>${v}분</option>`).join("")}</select></label>
    <label>하루 자동 회의 <input type="number" data-c="daily_max" value="${c.daily_max}" style="width:60px"></label>
    <label><input type="checkbox" data-c="cycle" ${c.cycle ? "checked" : ""}> 주기 업무 (기존 4개 팀)</label>
    <label>주기 <select data-c="cycle_min">${[1, 3, 5, 10].map((v) => `<option value="${v}" ${c.cycle_min === v ? "selected" : ""}>${v}분</option>`).join("")}</select></label>
    <label><input type="checkbox" data-c="team_cycle" ${c.team_cycle ? "checked" : ""}> 확장 팀 업무 (22개 팀 돌아가며)</label>
    <label>팀 업무 간격 <select data-c="team_cycle_min">${[1, 2, 4, 6, 10, 20].map((v) => `<option value="${v}" ${c.team_cycle_min === v ? "selected" : ""}>${v}분</option>`).join("")}</select></label>
    <label>하루 팀 회의 <input type="number" data-c="team_meet_max" value="${c.team_meet_max}" style="width:60px"></label>
    <label><input type="checkbox" data-c="chat" ${c.chat ? "checked" : ""}> 수다</label>
    <label>하루 AI 호출 <select data-c="call_max">${[600, 1500, 3000, 10000, 1000000].map((v) => `<option value="${v}" ${c.call_max === v ? "selected" : ""}>${v === 1000000 ? "제한 없음" : v.toLocaleString() + "번"}</option>`).join("")}</select></label>
    <label><input type="checkbox" data-c="enabled" ${c.enabled ? "checked" : ""}> 사무실 AI 켜기</label>
    <button class="flat sm danger" id="of-clear">기록 지우기</button>`;
  $$("[data-c]", box).forEach((i) => (i.onchange = () => {
    const v = i.type === "checkbox" ? i.checked : +i.value;
    api("/api/office/cfg", { method: "POST", body: { [i.dataset.c]: v } }).then((cfg) => { S.cfg = cfg; renderTop(); });
  }));
  $("#of-clear").onclick = () => confirm("회의록을 모두 지울까요? (결과 파일은 남습니다)") && api("/api/office/clear", { method: "POST" }).then(() => { LOG.clear(); cursor = 0; renderLog(); });
}

function menus() {
  const ag = $("#of-agenda");
  ag.innerHTML = R.agenda.map((g) => `<button class="flat" data-ag-run="${g.id}">#${esc(g.title)}</button>`).join("");
  const tm = $("#of-teammenu");
  tm.innerHTML = R.teams.map((t) => `<button class="flat" data-team-run="${t.id}"><span style="color:${t.color}">■</span> ${esc(t.name)}</button>`).join("");
}

export function initOffice() {
  on("view", async (v) => {
    visible = v === "office";
    if (!visible) { clearInterval(timer); timer = null; return; }
    if (!R) {
      R = await api("/api/office/roster");
      chanOptions();
      menus();
    }
    await poll();
    renderLog();
    clearInterval(timer);
    timer = setInterval(poll, 2500);
  });
  $("#of-tabs").onclick = (e) => e.target.dataset.tab && setTab(e.target.dataset.tab);
  $("#of-ch").onchange = (e) => { ch = e.target.value; renderLog(); };
  $("#of-floor").onclick = (e) => {
    const run = e.target.closest("[data-run]");
    if (run) return busy(run, () => api(`/api/office/team/${run.dataset.run}`, { method: "POST" }).then(() => toast(`${T(run.dataset.run)?.name} 업무를 시켰습니다`)));
    const ag = e.target.closest("[data-ag]");
    if (ag) agentCard(ag.dataset.ag);
  };
  $("#of-card").onclick = (e) => { const ag = e.target.closest(".of-tm[data-ag]"); if (ag) agentCard(ag.dataset.ag); else if (e.target.id === "of-card") $("#of-card").hidden = true; };
  document.querySelector("#v-office").addEventListener("click", (e) => {
    const ch2 = e.target.closest("[data-chart]");
    if (ch2) showOnChart(ch2.dataset.chart, ch2.dataset.iv);
  });
  $("#of-log").onclick = (e) => {
    const r = e.target.closest("[data-rate]");
    if (r) api(`/api/office/rate/${r.dataset.rate}?v=${r.dataset.v}`, { method: "POST" });
  };
  $("#of-send").onclick = async () => {
    const q = $("#of-q").value.trim();
    if (!q) return;
    $("#of-q").value = "";
    try { await api("/api/office/ask", { method: "POST", body: { text: q, room: ["all", "work"].includes(ch) ? "hq" : ch } }); await poll(); renderLog(); }
    catch (e) { toast("보내기 실패", e.message, "err"); }
  };
  $("#of-q").onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#of-send").click(); } };
  $("#of-job").onclick = (e) => busy(e.target, () => api("/api/office/job", { method: "POST" }).then(() => toast("다음 차례 업무를 시켰습니다")));
  $("#of-teams").onclick = () => R && teamsModal();
  $("#of-report").onclick = () => setTab("reports");
  $("#of-stop").onclick = () => api("/api/office/stop", { method: "POST" }).then(() => toast("회의를 멈춥니다"));
  $("#of-setbtn").onclick = settingsMenu;
  const dd = (btn, menu) => { $(btn).onclick = (e) => { e.stopPropagation(); $(menu).hidden = !$(menu).hidden; }; };
  dd("#of-agbtn", "#of-agenda");
  dd("#of-tmbtn", "#of-teammenu");
  document.addEventListener("click", (e) => { if (!e.target.closest(".of-dd")) { $("#of-agenda").hidden = true; $("#of-teammenu").hidden = true; } });
  $("#of-agenda").onclick = (e) => { const b = e.target.closest("[data-ag-run]"); if (b) api(`/api/office/agenda/${b.dataset.agRun}`, { method: "POST" }).then(() => toast("회의를 엽니다")).catch((x) => toast("회의", x.message, "err")); };
  $("#of-teammenu").onclick = (e) => { const b = e.target.closest("[data-team-run]"); if (b) api(`/api/office/team/${b.dataset.teamRun}`, { method: "POST" }).then(() => toast(`${T(b.dataset.teamRun)?.name} 업무를 시켰습니다`)); };
}
