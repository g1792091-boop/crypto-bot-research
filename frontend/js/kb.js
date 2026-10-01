// 연구 지식 패널: 백테스트 연구 카드 + AI 시그널 성적(학습 메모리). AI 프롬프트에 그대로 들어가는 내용.
import { IV_LABEL, api, esc } from "./core.js";

const ST = { validated: ["검증", "up"], rejected: ["기각", "down"], hypothesis: ["가설", "accent"] };
let filter = "rel";

function lessonRows(list, title) {
  if (!list?.length) return "";
  return `<div class="kb-h">${title}</div><table class="kb-t">${list.slice(0, 8).map((x) => `<tr class="${x.pattern ? "" : "dim"}">
    <td>${esc(x.key)}</td><td>${x.n}건</td><td class="${x.win_rate >= 50 ? "up" : "down"}">${x.win_rate}%</td>
    <td class="${x.avg_r >= 0 ? "up" : "down"}">${x.avg_r > 0 ? "+" : ""}${x.avg_r}R</td></tr>`).join("")}</table>`;
}

export async function renderKb(el, symbol, interval) {
  el.innerHTML = `<div class="empty">불러오는 중…</div>`;
  let d;
  try { d = await api(`/api/knowledge?symbol=${symbol}&interval=${interval}`); } catch (e) { el.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  const draw = () => {
    const rel = new Set(d.relevant);
    const cards = d.cards.filter((c) => filter === "all" || (filter === "rel" ? rel.has(c.id) : c.status === filter));
    const L = d.lessons;
    el.innerHTML = `<div class="kb">
      <div class="kb-head">${esc(d.headline)}</div>
      ${d.warnings.length ? `<div class="kb-warn">${d.warnings.map((w) => `<div>⚠ ${esc(w)}</div>`).join("")}</div>` : ""}
      <div class="kb-h">AI 학습 메모리 <span class="muted">· 시그널이 실제로 익절/손절된 결과</span></div>
      ${L && L.total ? lessonRows(L.overall, "전체") + lessonRows(L.by_engine, "엔진별") + lessonRows(L.by_interval, "봉별")
        + lessonRows(L.by_confidence, "확신도별") + lessonRows(L.by_symbol_interval_side, "코인·봉·방향별")
        + `<div class="help">흐린 줄 = 30건 미만 (연구 카드 k23: 패턴이라 부르지 않음). 이 표는 10분마다 다시 계산되어 모든 AI 에게 전달됩니다.</div>`
        : `<div class="help">아직 결과가 확정된 시그널이 없습니다. AI 가 24시간 시그널을 내고, 익절·손절이 나면 여기에 쌓여 AI 가 스스로 확신도를 조정합니다.</div>`}
      <div class="kb-h">연구 카드 <span class="muted">· ${d.cards.length}장 · ${d.enabled ? "AI 프롬프트에 적용 중" : "꺼짐 (KNOWLEDGE=0)"}</span></div>
      <div class="seg kb-seg">${[["rel", `${IV_LABEL[interval] || interval} 관련`], ["all", "전체"], ["validated", "검증"], ["rejected", "기각"], ["hypothesis", "가설"]]
        .map(([k, l]) => `<button class="flat sm ${filter === k ? "on" : ""}" data-kf="${k}">${l}</button>`).join("")}</div>
      ${cards.map((c) => `<div class="kb-card"><div class="row"><b class="${ST[c.status]?.[1] || ""}">${ST[c.status]?.[0] || c.status}</b>
        <span class="muted">${c.id} · ${esc(c.topic)}</span></div><div>${esc(c.rule)}</div>
        <details><summary class="muted">근거</summary><div class="dim">${esc(c.evidence)}</div></details></div>`).join("")}
      <details class="kb-prompt"><summary class="muted">AI 에게 실제로 들어가는 내용 보기</summary><pre>${esc(d.prompt)}</pre></details>
    </div>`;
    el.querySelectorAll("[data-kf]").forEach((b) => (b.onclick = () => { filter = b.dataset.kf; draw(); }));
  };
  draw();
}
