// 🧠 뉴럴 데스크 대시보드 — 연결된 AI 모델/피처 뉴런이 직접 데모 매매·학습하는 모습을 풀스크린으로.
// 디자인: 다크 터미널 + NEURAL SHELL(피처 → 결정 코어 → 확률 셸) 애니메이션. 전부 가상자금.
let root = null, raf = 0, loop = 0, N = null, ST = null;
const E = (s) => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const money = (v) => (v >= 0 ? "+" : "−") + "$" + Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 });
const ago = (t) => { const s = (Date.now() - t) / 1000 | 0; return s < 60 ? s + "s" : (s / 60 | 0) + "m"; };
const fmtp = (v) => v == null ? "–" : v >= 1000 ? Math.round(v).toLocaleString() : v >= 1 ? (+v).toFixed(2) : (+v).toPrecision(4);

export async function openNeural(ctx = {}) {
  N = await import("./neural.js");
  close();
  root = document.createElement("div"); root.id = "ndesk"; root.innerHTML = SHELL; document.body.appendChild(root);
  inject();
  root.querySelector("[data-x]").onclick = close;
  root.querySelector("[data-reset]").onclick = () => { if (confirm("뉴럴 데스크의 가상 성적·학습 가중치를 모두 초기화할까요?")) { N.reset(); render(); } };
  // 🧠 뇌 그래프 호버(Obsidian식: 올린 노드와 이웃만 강조) + .canvas 내보내기(Obsidian에서 열기)
  const bcv = root.querySelector("canvas[data-brain]");
  if (bcv) { bcv.onmousemove = (e) => { const r = bcv.getBoundingClientRect(); bmouse = { x: e.clientX - r.left, y: e.clientY - r.top }; }; bcv.onmouseleave = () => { bmouse = null; }; }
  // ⚙ 한도(siropkin 식 제약): 동시 포지션·하루 진입·쿨다운·제외 코인
  const gbtn = root.querySelector("[data-cfg]");
  if (gbtn) gbtn.onclick = () => { const c = N.cfg();
    const a = prompt(`동시 포지션 상한(1~6), 하루 최대 진입(1~50), 재진입 쿨다운 분(0~240), 제외 코인(쉼표)\n예: 4, 12, 30, DOGE`, `${c.maxPos}, ${c.dailyMax}, ${c.coolMin}, ${c.exclude.join(" ")}`);
    if (a == null) return; const [mp, dm, cm, ...ex] = a.split(","); const n = N.setCfg({ maxPos: mp, dailyMax: dm, coolMin: cm, exclude: ex.join(" ") });
    feed(`⚙ 한도: 동시 ${n.maxPos}개 · 하루 ${n.dailyMax}회 · 쿨다운 ${n.coolMin}분 · 제외 ${n.exclude.join(",") || "없음"}`); };
  // 💻 로컬 전용 토글 (설치된 Ollama 모델만)
  const lbtn = root.querySelector("[data-local]");
  const paintLocal = () => { if (lbtn) { const on = N.localOnly(); lbtn.textContent = on ? "💻 로컬 전용: 켜짐" : "💻 로컬 전용"; lbtn.style.background = on ? "#1e3a1e" : ""; lbtn.style.color = on ? "#7fe08a" : ""; } };
  paintLocal();
  if (lbtn) lbtn.onclick = async () => {
    const turningOn = !N.localOnly();
    if (turningOn) { const ols = await N.refreshOllama().catch(() => []); if (!ols.length) { alert("설치된 Ollama 로컬 모델이 없습니다. 먼저 '🖥 로컬 모델 설치'를 눌러 받으세요."); return; } }
    N.setLocalOnly(turningOn); paintLocal();
    feed(turningOn ? "💻 로컬 전용 ON — 설치된 Ollama 모델만 거래합니다 (무료·오프라인)" : "💻 로컬 전용 OFF — 클라우드+로컬 혼합");
    ST = N.state(); render();
  };
  // 🖥 추천 로컬(Ollama) 모델 자동 설치 → 받으면 바로 트레이더로
  const obtn = root.querySelector("[data-ollama]");
  if (obtn) obtn.onclick = async () => {
    const names = N.RECOMMENDED_OLLAMA.map(r => `· ${r.model} (${r.size}) — ${r.desc}`).join("\n");
    if (!confirm(`내 PC Ollama에 GH Coin용 추천 무료 모델을 자동으로 받습니다:\n\n${names}\n\n총 수 GB, 몇 분 걸릴 수 있어요. 받는 즉시 AI 모델 트레이더·직원으로 쓰입니다.\n(Ollama가 설치/실행돼 있어야 합니다 — ollama.com)\n\n시작할까요?`)) return;
    obtn.disabled = true; const o0 = obtn.textContent;
    const res = await N.installRecommended(p => {
      obtn.textContent = `🖥 ${E(String(p.model).slice(0, 14))} ${p.status}${p.pct != null ? " " + p.pct + "%" : ""}`;
      if (p.status === "완료" || p.status === "이미 있음") feed(`🖥 로컬 모델 ${p.model} ${p.status} — 트레이더로 투입`);
    }).catch(e => ({ done: [], failed: ["" + (e?.message || e)] }));
    obtn.disabled = false; obtn.textContent = o0;
    const connErr = res.failed.some(f => /응답 오류|연결|fetch|Failed|load failed|NetworkError/i.test(f));
    if (!res.done.length && connErr) alert("Ollama에 연결하지 못했습니다.\n\n1) ollama.com 에서 Ollama를 설치하세요.\n2) 설치하면 자동 실행됩니다(트레이 아이콘 확인).\n3) 다시 이 버튼을 누르면 추천 모델을 알아서 받습니다.");
    else alert(`완료: ${res.done.join(", ") || "없음"}${res.failed.length ? "\n실패: " + res.failed.join(", ") : ""}\n\n이제 리더보드에 로컬 모델이 보이고, 직접 거래·학습합니다.`);
    render();
  };
  const cbtn = root.querySelector("[data-canvas]");
  if (cbtn) cbtn.onclick = () => {
    const c = N.brainCanvas();
    if (!c.nodes.length) { alert("아직 뇌가 비어 있습니다 — 모델들이 거래·복기하며 지식이 쌓이면 내보낼 수 있어요."); return; }
    const blob = new Blob([JSON.stringify(c, null, 1)], { type: "application/json" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
    a.download = `GHCoin-brain-${new Date().toISOString().slice(0, 10)}.canvas`; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  };
  try { N.seedKnowledge(); } catch (e) {}   // 📚 매매법 지식베이스를 뇌에 한 번 심기
  ST = N.state();
  render();
  // 엔진은 백그라운드에서 상시 실행(N.startAuto) — 패널은 상태를 보여주기만 한다. 패널을 닫아도 매매·학습·리서치는 계속된다.
  try { N.startAuto?.(); } catch (e) {}
  seedShell();
  const tick = () => { try { ST = N.state(); sampleShell(ST); render(); } catch (e) {} };
  tick(); loop = setInterval(tick, 3000);
  raf = requestAnimationFrame(draw);
  window.addEventListener("keydown", esc);
}
function close() { if (loop) clearInterval(loop); if (raf) cancelAnimationFrame(raf); loop = raf = 0; window.removeEventListener("keydown", esc); if (root) root.remove(); root = null; }
const esc = (e) => { if (e.key === "Escape") close(); };

function engineTable(s) {
  const rows = (s.engine || []).slice(0, 12);
  const head = `<div class="nsub">📊 전략 엔진 — 자체 백테스트+실전 최근 20건 (기대값 > +0.1R 만 실전)${s.calib ? ` <span class="dim">· ${ago(s.calib.at)} 전 보정</span>` : ""}</div>`;
  if (!rows.length) return head + `<div class="dim" style="padding:4px 0">${s.calibrating ? "🔬 자체 백테스트 중…" : "보정 대기 — 곧 실제 데이터로 모든 매매법을 시험합니다"}</div>`;
  return head + rows.map(e => `<div class="nrow eng"><span class="nk" title="${E(e.name)} · ${e.cat} · 손익비 1:${e.rr} · 백테스트 ${e.bt}건·실전 ${e.live}건">${e.paused ? "⏸" : e.active ? "✅" : "··"} ${E(e.name)}<small class="dim"> ${e.tf === "60" ? "1H" : e.tf === "240" ? "4H" : e.tf + "m"}</small></span><span class="nbar"><i style="width:${Math.max(3, Math.min(100, 50 + e.mean * 50))}%;${e.mean < 0 ? "background:linear-gradient(90deg,#ff4d64,#ff8a9a)" : ""}"></i></span><b class="${e.mean >= 0 ? "up" : "dn"}">${e.mean >= 0 ? "+" : ""}${e.mean.toFixed(2)}R</b><small>승${e.wr}%·${e.n}</small></div>`).join("")
    + (s.review ? `<div class="nsub">🧠 AI 전략 회의 <span class="dim">${ago(s.review.t)} 전${s.review.by ? " · " + E(s.review.by) : ""}</span></div><div class="brow"><span class="bt pur">결정</span><span class="btx" title="${E(s.review.text)}">${E(s.review.text)}${s.review.actions?.length ? " · " + E(s.review.actions.join(", ")) : ""}</span><small></small></div>` : "")
    + (s.news ? `<div class="brow"><span class="bt ${s.news.score > 0 ? "up" : s.news.score < 0 ? "warn" : "dim"}">뉴스</span><span class="btx" title="${E((s.news.heads || []).join(" / "))}">${s.news.score > 0 ? "+" : ""}${s.news.score} ${E(s.news.reason || "")}${s.news.event ? " · ⚠ 신규진입 일시중지" : ""}</span><small>${ago(s.news.t)}</small></div>` : "");
}
// 🧠 뉴트론(MCP·옵시디언) 연결 상태 + 검증된 셋업 순위(ocean-agent 개념)
let NT = null; import("./neutron.js").then(m => NT = m).catch(() => {});
function robinLine(s) {
  const w = s.whale, tr = w?.trust, c = s.cfg || {}, rv = s.review2;
  return `<div class="nsub">🐋 고래 카피 · 🗂 포지션 관리 · ⚙ 한도</div>`
    + `<div class="brow"><span class="bt pur">고래</span><span class="btx" title="감지→필터→리스크→신호 · 30분 뒤 채점">${(w?.last || []).map(x => `${E(x.sym.replace("USDT", ""))} ${x.dir > 0 ? "▲" : "▼"}${Math.abs(x.netPct)}%`).join(" · ") || "승인된 고래 신호 없음"} <small class="dim">· 적중 ${tr?.n ? Math.round(tr.acc * 100) + "% (" + tr.n + "회)" : "학습 중"}</small></span></div>`
    + (rv ? `<div class="brow"><span class="bt up">관리</span><span class="btx" title="${E((rv.dropped || []).join(" / "))}">${E(rv.by)}: ${E((rv.done || []).join(" · ") || "모두 유지")}${rv.dropped?.length ? ` <small class="dim">· 환각 필터 ${rv.dropped.length}건</small>` : ""} <small class="dim">${ago(rv.t)} 전</small></span></div>` : "")
    + `<div class="brow"><span class="bt dim">한도</span><span class="btx">동시 ${c.maxPos ?? 4}개 · 오늘 진입 ${s.dayN ?? 0}/${c.dailyMax ?? 12} · 쿨다운 ${c.coolMin ?? 30}분${c.exclude?.length ? " · 제외 " + c.exclude.join(",") : ""}</span></div>`;
}
function neutronLine(s) {
  const st = NT?.neutronStatus?.(), top = (s.setups || []).slice(0, 3);
  const a = st?.on ? `내보내기 ${st.exported}회${st.at ? ` · ${ago(st.at)} 전` : ""} · 볼트 ${st.vault}회 · 받은 제안 ${st.inbox}건${st.err ? ` · ⚠ ${E(st.err)}` : ""}` : "exe 로 실행하면 켜짐 (문서/GHNano 사무실/GHCoin 뇌)";
  return `<div class="nsub">🧠 뉴트론 — Claude Code·옵시디언 연결(MCP)</div><div class="brow"><span class="bt ${st?.on ? "up" : "dim"}">${st?.on ? "연결" : "대기"}</span><span class="btx">${a}</span></div>`
    + (top.length ? `<div class="brow"><span class="bt pur">셋업</span><span class="btx" title="기대값 × 승률 × 신뢰도(표본)">${top.map(x => `${E(x.name)}@${x.tf} ${x.score}`).join(" · ")}</span></div>` : "");
}
// 🧬 매매법 진화(개선·수정·조합) 현황
function evoLine(s) {
  const ev = s.evo; if (!ev) return "";
  const L = ev.log?.[0];
  const head = `<div class="nsub">🧬 매매법 진화 — 개선·수정·조합 <span class="dim">· 채택 ${ev.n}개${ev.seeds ? ` · AI 제안 대기 ${ev.seeds}` : ""}${L ? ` · ${ago(L.t)} 전` : ""}</span></div>`;
  if (!L) return head + `<div class="dim" style="padding:4px 0">다음 자체 백테스트 때 매매법을 고치고 섞어 봅니다 (앞 70% 선택 → 뒤 30% 검증 통과만 채택)</div>`;
  const rows = (L.adopted || []).map(a => `<div class="brow"><span class="bt ${a.src === "조합" ? "pur" : a.src === "수정" ? "warn" : "up"}">${E(a.src || "변형")}</span><span class="btx" title="${E(a.name)}">${E(a.name)} <small class="dim">원본 ${a.base}R → 검증 ${a.oos >= 0 ? "+" : ""}${a.oos}R(${a.n}건)</small></span></div>`).join("");
  return head + `<div class="brow"><span class="bt dim">시험</span><span class="btx">변형 ${L.tested}개 → 학습구간 통과 ${L.passedIS} → 채택 ${(L.adopted || []).length}</span></div>` + rows;
}
function riskLearnLine() {
  let r; try { r = N.brainRisk(); } catch (e) { return ""; }
  if (!r) return "";
  const rk = (r.risk || []).slice(0, 2).map(x => `${E(x.regime)} ${x.lev}x·시드${x.seed}%·SL${x.sl}/TP${x.tp}(승${x.wr}%)`).join(" · ");
  const bh = (r.bestHours || []).map(h => `${h.hr}시(${h.wr}%)`).join(" ");
  const wh = (r.worstHours || []).map(h => `${h.hr}시(${h.wr}%)`).join(" ");
  const sp = r.vol?.spike; const spStr = sp && sp.n >= 4 ? `뉴스성 급변동 승률 ${Math.round(sp.wins / sp.n * 100)}%(${sp.n}판)` : "";
  if (!rk && !bh && !spStr) return `<div class="nsub dim">💹 리스크·시간대 학습 중 — 거래가 쌓이면 상황별 최적 레버·시드·손절·익절·시간대를 스스로 찾습니다</div>`;
  return `<div class="nsub">💹 AI가 학습한 리스크·시간대 (스스로 조정)</div>`
    + (rk ? `<div class="brow"><span class="bt up">리스크</span><span class="btx" title="국면별로 학습된 레버리지·시드·손절·익절">${rk}</span></div>` : "")
    + ((bh || wh) ? `<div class="brow"><span class="bt warn">시간대</span><span class="btx">잘됨 ${bh || "–"} · 안됨 ${wh || "–"}</span></div>` : "")
    + (spStr ? `<div class="brow"><span class="bt dim">뉴스성</span><span class="btx">${spStr}</span></div>` : "");
}
function render() {
  if (!root || !ST) return;
  const s = ST, up = s.pnl >= 0, eq = s.equity ?? (1000 + s.pnl);
  const dmode = s.riskMode && s.riskMode !== "정상";
  root.querySelector("[data-pnl]").innerHTML = `<b class="${eq >= (s.bankroll || 1000) ? "up" : "dn"}">$${eq.toLocaleString(undefined, { maximumFractionDigits: 0 })}</b> <small class="${up ? "up" : "dn"}">${money(s.pnl)}</small>`;
  root.querySelector("[data-kpi]").innerHTML =
    `<span>시작 <b>$${(s.bankroll || 1000).toLocaleString()}</b></span><span>낙폭 <b class="${(s.drawdown || 0) > 7 ? "dn" : "dim"}">${s.drawdown || 0}%</b></span><span>모드 <b class="${dmode ? "dn" : "up"}">${s.riskMode || "정상"}</b></span><span>승률 <b class="${s.winRate >= 50 ? "up" : "dn"}">${s.winRate}%</b></span><span>체결 <b>${s.fills}</b></span><span>AI <b>${s.nModels}</b></span><span>매매법 <b>${s.nDesigns}</b><small>(인계 ${s.handed})</small></span><span>가동 <b>${ago(s.since)}</b></span>`;
  // 트레이더 리더보드 = 연결된 AI 모델 각각 + 자체 신호. PnL 순. (교훈 = 복기로 배운 수 · 보유 = 현재 포지션)
  root.querySelector("[data-neurons]").innerHTML =
    s.traders.map((tr, i) => { const u = tr.pnl >= 0;
      return `<div class="nrow trd"><span class="rk">${i + 1}</span><span class="nk" title="${E(tr.full || tr.name)}">${tr.prov === "self" ? "⚙️ " : tr.prov === "ollama" ? "🖥 " : "☁ "}${E(tr.name)}${tr.last && tr.last.bias != null ? ` <small class="${tr.last.bias > 0 ? "up" : tr.last.bias < 0 ? "dn" : "dim"}" title="${E(tr.last.note || "")}">🔍${E(tr.last.ko)} ${tr.last.bias > 0 ? "▲" : tr.last.bias < 0 ? "▼" : "·"}${tr.last.conf}%</small>` : tr.idle ? ' <small class="dim">스캔 순번 대기</small>' : ""}${tr.scanAcc != null ? ` <small class="dim">읽기적중 ${tr.scanAcc}%</small>` : ""}</span><b class="${u ? "up" : "dn"}">${money(tr.pnl)}</b><small>${tr.hit == null ? "–" : "승" + tr.hit + "%"}${tr.approved != null ? ` ·승인${tr.approved}/거절${tr.rejected}` : ""}${(typeof tr.pos === "number" ? tr.pos : tr.pos?.length) ? ` ·보유${typeof tr.pos === "number" ? tr.pos : tr.pos.length}` : ""}</small></div>`;
    }).join("") +
    (s.nModels === 0 ? `<div class="nsub dim">연결된 AI 모델이 없습니다 — 자체 엔진이 검증된 신호만 집행합니다</div>` : "") +
    engineTable(s) + evoLine(s) + robinLine(s) + neutronLine(s) +
    (s.brain ? `<div class="nsub">🧠 자체 뇌 · 지능 <b style="color:#b79cff">${s.brain.iq?.score ?? 0}/100</b> <span class="dim">정확도 ${s.brain.iq?.acc ?? 0}% · ${s.brain.iq?.n ?? 0}판 학습 · 손절회피 ${s.brain.traps ?? 0}</span></div>` +
      `<div class="nsub">누적 기억 ${s.brain.n}개 <span class="dim">${Object.entries(s.brain.byType || {}).map(([t, c]) => t + " " + c).join(" · ") || "비어있음"}</span></div>` +
      (s.brain.top.length ? s.brain.top.slice(0, 7).map(m => `<div class="brow"><span class="bt ${m.type === "패턴" ? "up" : m.type === "교훈" ? "warn" : m.type === "전략" || m.type === "매매법" ? "pur" : m.type === "지식" ? "warn" : "dim"}">${E(m.type)}</span><span class="btx" title="${E(m.text)}${m.model ? " · " + E(m.model) : ""}">${E(m.text)}</span><small>×${m.w}</small></div>`).join("")
        : `<div class="dim" style="padding:4px 0">아직 비어있음 — 모델들이 복기·거래하며 기억을 쌓습니다</div>`) : "")
    + riskLearnLine();
  // 코인별 결정(스캔) 그리드
  const grid = N.COINS.map(([ko, sym]) => {
    const d = s.dec[sym], r = s.regime?.[sym];
    const col = r ? (r.key === "상승추세" ? "up" : r.key === "하락추세" ? "dn" : "dim") : "dim";
    return `<div class="mrow" title="1시간봉 국면 · 4시간 상위추세 · ADX"><b>${ko} <small class="${r?.htf > 0 ? "up" : r?.htf < 0 ? "dn" : "dim"}">${r?.htf > 0 ? "4H↑" : r?.htf < 0 ? "4H↓" : "4H·"}</small></b><span class="${col}">${E(r?.label || "판단중")}${r?.adx != null ? " · ADX " + r.adx : ""}</span><em class="dim">${d ? "$" + fmtp(d.price) : "–"}</em></div>`;
  }).join("");
  // 🔴 열린 포지션 (거래소 스타일: 레버리지·증거금·진입/현재·ROE·PnL·청산가) — 자체 + 모델 전부
  const allPos = [];
  for (const p of (s.pos || [])) allPos.push({ ...p, who: "자체" });
  for (const tr of (s.traders || [])) if (tr.prov !== "self" && Array.isArray(tr.pos)) for (const p of tr.pos) allPos.push({ ...p, who: tr.name });
  const posList = allPos.length ? allPos.map(p => {
    const uPnl = p.margin != null ? p.margin * (p.roe || 0) / 100 : 0;
    return `<div class="prow ${p.roe >= 0 ? "up" : "dn"}"><div class="pr1"><b>${E(p.ko)}</b> <span class="${p.side > 0 ? "up" : "dn"}">${p.side > 0 ? "롱" : "숏"} ${p.lev || "?"}x</span> <small class="dim">${E(p.who)}</small><span class="pr-roe ${p.roe >= 0 ? "up" : "dn"}">${p.roe >= 0 ? "+" : ""}${(p.roe || 0).toFixed(1)}%</span></div><div class="pr2 dim">증거금 $${(p.margin || 0).toFixed(0)} · 진입 ${fmtp(p.entry)} → ${fmtp(p.price)} · <span class="${uPnl >= 0 ? "up" : "dn"}">${uPnl >= 0 ? "+" : "−"}$${Math.abs(uPnl).toFixed(2)}</span> · 청산 ${fmtp(p.liq)}</div>${p.name ? `<div class="pr2 dim">${E(p.name)} · 손절 ${fmtp(p.sl)}${p.be ? "(본절)" : ""} · 익절 ${fmtp(p.tp)} · 1:${p.rr} · 리스크 $${p.risk}</div>` : ""}</div>`;
  }).join("") : `<div class="dim" style="padding:6px">열린 포지션 없음 — 신호가 나오면 진입합니다</div>`;
  root.querySelector("[data-markets]").innerHTML = `<div class="nd-mgrid">${grid}</div><div class="pos-h">열린 포지션 ${allPos.length}</div>${posList}`;
  // 모델이 설계한 매매법·커스텀 지표 (백테스트 → 사무실 인계)
  const des = (s.designs || []).map(d => `<div class="trow des"><span class="dim">${ago(d.t)}</span><b style="color:#b79cff">${E(d.model)}</b><span>${d.cls ? `<em style="color:#7ea6ff">${E(d.cls)}</em> ` : ""}${E(d.coin || "")}${d.tf ? "·" + E(d.tf) : ""}${d.win != null ? " 승" + d.win + "%" : ""}${d.mdd != null ? " 낙" + d.mdd + "%" : ""}</span><b class="${d.ret >= 0 ? "up" : "dn"}">${d.ret}%</b><span>${E(d.name)} <em class="${d.handed ? "up" : d.pass ? "" : "dim"}">${d.handed ? "→ 사무실 인계" : d.pass ? "통과" : "불통과"}</em></span></div>`).join("");
  // 거래
  root.querySelector("[data-trades]").innerHTML = des + (s.trades.length ? s.trades.map(t =>
    `<div class="trow"><span class="dim">${ago(t.t)}</span><b>${t.ko}</b><span>${t.side > 0 ? "롱" : "숏"}${t.lev ? " " + t.lev + "x" : ""}</span><b class="${t.roe >= 0 ? "up" : "dn"}">${t.roe >= 0 ? "+" : ""}${t.roe}%</b><span class="${t.pnl >= 0 ? "up" : "dn"}">${t.pnl >= 0 ? "+" : "−"}$${Math.abs(t.pnl || 0).toFixed(2)}</span><span class="dim" title="${E(t.name || "")}">${t.R != null ? (t.R >= 0 ? "+" : "") + t.R + "R · " : ""}${E(t.why)}</span></div>`
  ).join("") : (des ? "" : `<div class="dim" style="padding:10px">아직 거래 없음 — 신호가 쌓이면 자동 진입합니다</div>`));
  // 🔍 스캔 중 — 어떤 모델이 무슨 종목을 어느 국면에서 보고 있나 (오른쪽 위)
  const scEl = root.querySelector("[data-scan]");
  if (scEl) { const sc = s.scan;
    scEl.innerHTML = sc
      ? `🔍 <b>${E(sc.model)}</b> 가 <b>${E(sc.ko)}</b> 스캔 중 <span class="dim">· ${E(sc.regime)} 국면</span>`
      : `<span class="dim">스캔 대기 중 — 모델이 종목을 고르면 여기에 표시됩니다</span>`;
    // 모델 순환 스캔 현황: 모델마다 최근에 읽은 코인·방향·확신 (모든 모델이 차례로 돎)
    const ro = (s.traders || []).filter(t => t.prov !== "self");
    scEl.innerHTML += `<div class="scan-roster">${ro.map(t => { const L = t.last; return `<span class="sr ${L?.bias > 0 ? "up" : L?.bias < 0 ? "dn" : "dim"}" title="${E(t.full || t.name)}${L?.note ? " · " + E(L.note) : ""}">${E(t.name)} ${L ? (L.err ? "⚠" : `${E(L.ko)}${L.bias > 0 ? "▲" : L.bias < 0 ? "▼" : "·"}${L.conf}%`) : "대기"}</span>`; }).join("")}</div>`;
  }
  // ⚙️ AI 자동 조절 상태 (레버리지·시드)
  const au = root.querySelector("[data-auto]");
  if (au) { const nw = s.news; au.innerHTML = `⚙️ 청산공식 <b>${s.fw?.minLev ?? 20}x+</b> · 1회 리스크 <b>${s.fw?.risk ?? 0.5}~${s.fw?.maxRisk ?? 1}%</b> · 실전 전략 <b>${s.nActive ?? 0}</b>${s.calibrating ? " (백테스트 중)" : ""} · 평균 <b>${s.avgLev != null ? s.avgLev + "x" : "—"}</b>${nw ? ` · 📰 <b class="${nw.score > 0 ? "up" : nw.score < 0 ? "dn" : ""}">${nw.score > 0 ? "+" : ""}${nw.score}</b>${nw.event ? " ⚠일정" : ""}` : ""}`; }
  // 🧠 뇌 그래프 데이터 갱신 + 요약 (오른쪽 아래)
  brainG = N.brainGraph();
  const bi = root.querySelector("[data-braininfo]");
  if (bi && s.brain) { const iq = s.brain.iq || {};
    bi.innerHTML = `지능 <b style="color:#b79cff">${iq.score ?? 0}</b>/100 <span class="dim">(정확도 ${iq.acc ?? 0}% ·${iq.n ?? 0}판)</span> · 지식 ${s.brain.n} · 연결 ${(brainG && brainG.edges.length) || 0} · 🛑회피 ${s.brain.traps ?? 0}`; }
  // 라이브 피드 티커
  root.querySelector("[data-feed]").innerHTML = s.feed.map(f => `<span>▸ ${E(f.text)}</span>`).join(" ");
}

// ── NEURAL SHELL (마켓 인셋 → 피처 추출 48유닛 → 결정 코어 입자 구 → 활성 마켓) ──
// 전부 실데이터: 1분봉 가격·피처 뉴런(모멘텀·추세·RSI·거래흐름·호가압력·변동성)·국면·포지션·동시 리스크.
const HIST = {};   // key → 최근 값(스파크라인)
const pushH = (k, v, n = 90) => { if (!Number.isFinite(v)) return; const a = HIST[k] ||= []; a.push(v); if (a.length > n) a.shift(); };
let shellSym = 0, shellAt = 0, parts = null, t = 0, units = null, routes = null;
function sampleShell(s) {
  for (const [, sym] of N.COINS) { const d = s.dec?.[sym]; if (d?.price) pushH("px:" + sym, d.price); }
  const f = s.feat?.[N.COINS[shellSym][1]] || {};
  for (const k of N.NEURONS) pushH("f:" + k, f[k] ?? 0);
  pushH("heat", s.heat || 0);
}
async function seedShell() {   // 처음 열 때 1분봉 90개로 스파크라인을 채움
  try { const A = await import("../nuri-ai/agent.js");
    for (const [, sym] of N.COINS) { const cs = (await A.candlesFor({ market: sym, exchange: "binancef", timeframe: "1" }, 90)).cs; if (cs?.length) HIST["px:" + sym] = cs.map(b => +b.c); } } catch (e) {}
}
const SH = { bg: "#f3f4ef", grid: "rgba(40,50,60,.06)", ink: "#23272e", dim: "#7c838f", blue: "59,111,216", orange: "240,138,36", red: "229,72,77", green: "58,167,109", purple: "130,90,220" };
function spark(g, arr, x, y, w, h, col) {
  if (!arr || arr.length < 2) { g.strokeStyle = `rgba(${col},.3)`; g.beginPath(); g.moveTo(x, y + h / 2); g.lineTo(x + w, y + h / 2); g.stroke(); return; }
  let lo = Math.min(...arr), hi = Math.max(...arr); if (hi - lo < 1e-9) { hi += 1; lo -= 1; }
  g.beginPath(); arr.forEach((v, i) => { const px = x + (i / (arr.length - 1)) * w, py = y + h - ((v - lo) / (hi - lo)) * h; i ? g.lineTo(px, py) : g.moveTo(px, py); });
  g.strokeStyle = `rgb(${col})`; g.lineWidth = 1.3; g.stroke();
  g.lineTo(x + w, y + h); g.lineTo(x, y + h); g.closePath(); g.fillStyle = `rgba(${col},.10)`; g.fill();
}
function bez(g, x0, y0, x1, y1) { const mx = (x0 + x1) / 2; g.beginPath(); g.moveTo(x0, y0); g.bezierCurveTo(mx, y0, mx, y1, x1, y1); }
function bezPt(x0, y0, x1, y1, u) { const mx = (x0 + x1) / 2, a = 1 - u; return [a * a * a * x0 + 3 * a * a * u * mx + 3 * a * u * u * mx + u * u * u * x1, a * a * a * y0 + 3 * a * a * u * y0 + 3 * a * u * u * y1 + u * u * u * y1]; }
function rrect(g, x, y, w, h, r) { g.beginPath(); if (g.roundRect) g.roundRect(x, y, w, h, r); else g.rect(x, y, w, h); }
function draw() {
  raf = requestAnimationFrame(draw);
  drawBrain();
  const cv = root && root.querySelector("canvas[data-shell]"); if (!cv || !ST) return;
  const dpr = Math.min(2, window.devicePixelRatio || 1), W = cv.clientWidth, H = cv.clientHeight; if (W < 50 || H < 50) return;
  if (cv.width !== W * dpr || cv.height !== H * dpr) { cv.width = W * dpr; cv.height = H * dpr; }
  const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0);
  t += 0.016;
  if (performance.now() - shellAt > 9000) { shellAt = performance.now(); if (ST.pos?.length) { const i = N.COINS.findIndex(c => c[1] === ST.pos[0].sym); if (i >= 0) shellSym = i; } else shellSym = (shellSym + 1) % N.COINS.length; }
  const [ko, sym] = N.COINS[shellSym], feat = ST.feat?.[sym] || {}, rg = ST.regime?.[sym] || {}, neur = ST.neurons || [];
  // 공정확률: 피처 뉴런 가중 합의 → 로지스틱 (뉴런 가중치는 거래 결과로 학습된 값)
  let z = 0, ws = 0; for (const n of neur) { const v = feat[n.name] || 0; z += v * n.w; ws += Math.abs(n.w); }
  const pUp = 1 / (1 + Math.exp(-2.4 * (ws ? z / ws : 0))), charge = Math.min(1, Math.abs(pUp - 0.5) * 2 + (rg.adx || 0) / 120);
  // 배경(종이 + 격자)
  g.fillStyle = SH.bg; g.fillRect(0, 0, W, H);
  g.strokeStyle = SH.grid; g.lineWidth = 1;
  for (let x = 0; x < W; x += 24) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, H); g.stroke(); }
  for (let y = 0; y < H; y += 24) { g.beginPath(); g.moveTo(0, y); g.lineTo(W, y); g.stroke(); }
  const top = 30, botH = Math.max(78, H * 0.17), mainB = H - botH - 22;
  g.font = "600 10px ui-monospace,monospace"; g.fillStyle = SH.ink; g.textAlign = "left";
  g.fillText("MARKET INSET", 12, 18); g.fillText("FEATURE EXTRACTION · 48 UNITS", W * 0.36, 18);
  g.textAlign = "right"; g.fillStyle = SH.dim; g.fillText(`${ko} · ${rg.label || "판단중"} · 4H ${rg.htf > 0 ? "↑" : rg.htf < 0 ? "↓" : "→"}`, W - 200, 18);
  // ① 마켓 인셋 7장
  const ref = shellSym ? "BTCUSDT" : "ETHUSDT";
  const IN = [
    { k: `${ko} 1M`, sub: "가격", arr: HIST["px:" + sym], v: ST.dec?.[sym]?.price, col: SH.blue, fmt: v => fmtp(v) },
    { k: `${shellSym ? "BTC" : "ETH"} 1M`, sub: "기준 코인", arr: HIST["px:" + ref], v: ST.dec?.[ref]?.price, col: SH.orange, fmt: v => fmtp(v) },
    { k: "ORDER BOOK", sub: "호가압력", arr: HIST["f:호가압력"], v: feat["호가압력"], col: SH.blue, fmt: v => (v * 100).toFixed(0) },
    { k: "TAPE", sub: "거래흐름", arr: HIST["f:거래흐름"], v: feat["거래흐름"], col: SH.green, fmt: v => (v * 100).toFixed(0) },
    { k: "VOLATILITY", sub: "변동성", arr: HIST["f:변동성"], v: feat["변동성"], col: SH.red, fmt: v => (v * 100).toFixed(0) },
    { k: "MOMENTUM", sub: "모멘텀", arr: HIST["f:모멘텀"], v: feat["모멘텀"], col: SH.purple, fmt: v => (v * 100).toFixed(0) },
    { k: "INVENTORY", sub: "동시 리스크 %", arr: HIST["heat"], v: ST.heat, col: SH.green, fmt: v => (+v).toFixed(2) },
  ];
  const iw = Math.min(170, W * 0.17), ih = (mainB - top) / IN.length - 6, ix = 12;
  const UX = W * 0.42, uTop = top + 6, uBot = mainB - 6, NU = 48, uy = i => uTop + (uBot - uTop) * (i / (NU - 1));
  if (!units) units = Array.from({ length: NU }, (_, i) => ({ src: i % IN.length, ph: Math.random() * 7 }));
  const SX = W * 0.75, SY = (top + mainB) / 2, SR = Math.max(40, Math.min((mainB - top) / 2 - 6, W * 0.2));
  if (!routes) routes = Array.from({ length: 30 }, () => ({ u: Math.floor(Math.random() * NU), th: Math.random() * 7, ph: Math.random() * 7, sp: 0.15 + Math.random() * 0.25 }));
  // 인셋 → 유닛 연결선 + 흐르는 점
  IN.forEach((c, j) => { const cy = top + j * (ih + 6) + ih / 2;
    for (let u = j; u < NU; u += IN.length) { const y1 = uy(u), act = Math.min(1, Math.abs(c.v || 0) + 0.15);
      g.strokeStyle = `rgba(${c.col},${0.10 + act * 0.25})`; g.lineWidth = 0.8; bez(g, ix + iw, cy, UX - 4, y1); g.stroke();
      if (u % 2 === 0) { const [px, py] = bezPt(ix + iw, cy, UX - 4, y1, (t * 0.22 + u * 0.071) % 1); g.fillStyle = `rgba(${c.col},.75)`; g.beginPath(); g.arc(px, py, 1.8, 0, 7); g.fill(); } } });
  // 인셋 카드
  IN.forEach((c, j) => { const y = top + j * (ih + 6);
    g.fillStyle = "#ffffff"; g.strokeStyle = "rgba(40,50,60,.18)"; g.lineWidth = 1; rrect(g, ix, y, iw, ih, 4); g.fill(); g.stroke();
    g.fillStyle = `rgb(${c.col})`; g.fillRect(ix, y, 3, ih);
    g.font = "700 9px ui-monospace,monospace"; g.textAlign = "left"; g.fillStyle = `rgb(${c.col})`; g.fillText(c.k, ix + 8, y + 11);
    g.font = "8px ui-monospace,monospace"; g.fillStyle = SH.dim; g.fillText(c.sub, ix + 8, y + 21);
    g.font = "700 11px ui-monospace,monospace"; g.textAlign = "right"; g.fillStyle = SH.ink; g.fillText(c.v == null ? "–" : c.fmt(c.v), ix + iw - 6, y + 12);
    if (ih > 30) spark(g, c.arr, ix + 8, y + 24, iw - 16, ih - 28, c.col); });
  // ② 유닛 → 구 (라우팅 곡선)
  const coreN = 0.25 + charge * 0.35, up = pUp >= 0.5, cc = up ? SH.blue : SH.red;
  for (const r of routes) { const y0 = uy(r.u), a = r.th + t * 0.05, tx = SX + Math.cos(a) * SR * 0.95, ty = SY + Math.sin(a) * SR * 0.95;
    const col = (r.u % 3 === 0) ? SH.orange : SH.blue; g.strokeStyle = `rgba(${col},.22)`; g.lineWidth = 0.9; bez(g, UX + 4, y0, tx, ty); g.stroke();
    const [px, py] = bezPt(UX + 4, y0, tx, ty, (t * r.sp + r.ph) % 1); g.fillStyle = `rgba(${col},.85)`; g.beginPath(); g.arc(px, py, 2, 0, 7); g.fill(); }
  // 유닛 열 + 라벨
  const lab = ["Δ 가격", ...N.NEURONS, "국면", "4H 추세", "스프레드", "리스크"];
  for (let i = 0; i < NU; i++) { const y = uy(i), src = IN[units[i].src], act = Math.min(1, Math.abs(src.v || 0) * 1.4 + 0.2 * (1 + Math.sin(t * 2 + units[i].ph)) / 2);
    g.fillStyle = `rgba(${src.col},${0.35 + act * 0.65})`; g.beginPath(); g.arc(UX, y, 2.4 + act * 1.6, 0, 7); g.fill(); }
  g.font = "600 9px ui-monospace,monospace"; g.textAlign = "left";
  lab.forEach((l, k) => { const y = uy(Math.round(k * (NU - 1) / (lab.length - 1))); g.fillStyle = "rgba(243,244,239,.85)"; g.fillRect(UX + 7, y - 7, g.measureText(l).width + 6, 11); g.fillStyle = SH.ink; g.fillText(l, UX + 10, y + 2); });
  // ③ 결정 코어: 3D 입자 구 (바깥 = 합의 방향색 · 코어 = 주황, 합의가 셀수록 코어가 커지고 밀집)
  const M = 900; if (!parts) parts = Array.from({ length: M }, (_, i) => ({ th: Math.random() * Math.PI * 2, ph: Math.acos(2 * Math.random() - 1), r: Math.pow(Math.random(), 0.33), core: i < M * 0.42, j: Math.random() }));
  const rot = t * 0.12, pts = [];
  for (const p of parts) { const rr = p.core ? p.r * coreN * (0.92 + 0.08 * Math.sin(t * 2 + p.j * 9)) : 0.45 + p.r * 0.55;
    const x3 = Math.sin(p.ph) * Math.cos(p.th + rot), z3 = Math.sin(p.ph) * Math.sin(p.th + rot), y3 = Math.cos(p.ph);
    pts.push({ x: SX + x3 * rr * SR, y: SY + y3 * rr * SR, z: z3, core: p.core }); }
  pts.sort((a, b) => a.z - b.z);
  for (const q of pts) { const d = (q.z + 1) / 2;
    g.fillStyle = q.core ? `rgba(${SH.orange},${0.45 + d * 0.5})` : `rgba(${cc},${0.18 + d * 0.45})`;
    g.beginPath(); g.arc(q.x, q.y, (q.core ? 1.6 : 1.3) + d * 1.4, 0, 7); g.fill(); }
  // 코어 상태 박스
  const bx = W - 182, by = top - 22, bw = 168, bh = 66;
  g.fillStyle = "rgba(255,255,255,.94)"; g.strokeStyle = "rgba(40,50,60,.2)"; rrect(g, bx, by, bw, bh, 5); g.fill(); g.stroke();
  g.font = "600 9px ui-monospace,monospace"; g.textAlign = "left"; g.fillStyle = SH.dim; g.fillText("CORE CHARGE", bx + 9, by + 14);
  g.fillStyle = "rgba(40,50,60,.12)"; g.fillRect(bx + 9, by + 19, bw - 18, 6); g.fillStyle = `rgb(${SH.green})`; g.fillRect(bx + 9, by + 19, (bw - 18) * charge, 6);
  g.fillStyle = SH.dim; g.fillText(`FAIR P(UP) · ${ko}`, bx + 9, by + 40);
  g.font = "800 18px ui-monospace,monospace"; g.fillStyle = `rgb(${up ? SH.green : SH.red})`; g.fillText((pUp * 100).toFixed(1) + "%", bx + 9, by + 59);
  g.font = "9px ui-monospace,monospace"; g.textAlign = "right"; g.fillStyle = SH.dim; g.fillText(`대기 신호 ${ST.queue || 0}`, bx + bw - 9, by + 59);
  // ④ 활성 마켓 (코인별 최근 1분 가격 틱 + 보유 포지션 ◆)
  const ay = mainB + 14, ah = (botH - 6) / N.COINS.length, ax0 = 70, ax1 = W - 150;
  g.font = "600 9px ui-monospace,monospace"; g.textAlign = "left"; g.fillStyle = SH.ink; g.fillText("ACTIVE MARKETS", 12, mainB + 8);
  g.textAlign = "right"; g.fillStyle = SH.dim; g.fillText("1분 틱 · ◆ 보유 포지션 · 파랑 상승 / 빨강 하락", W - 12, mainB + 8);
  N.COINS.forEach(([k2, s2], r) => { const y = ay + r * ah + ah / 2, arr = HIST["px:" + s2] || [], P = (ST.pos || []).find(p => p.sym === s2);
    g.fillStyle = r === shellSym ? `rgb(${SH.orange})` : SH.dim; g.textAlign = "left"; g.font = "600 9px ui-monospace,monospace"; g.fillText(k2 + " 1M", 12, y + 3);
    g.strokeStyle = "rgba(40,50,60,.14)"; g.lineWidth = 3; g.beginPath(); g.moveTo(ax0, y); g.lineTo(ax1, y); g.stroke();
    for (let i = 1; i < arr.length; i++) { const x = ax0 + (ax1 - ax0) * (i / Math.max(1, arr.length - 1)), upk = arr[i] >= arr[i - 1];
      g.strokeStyle = `rgba(${upk ? SH.blue : SH.red},.75)`; g.lineWidth = 1.2; g.beginPath(); g.moveTo(x, y - 4); g.lineTo(x, y + 4); g.stroke(); }
    if (P) { const x = ax1 - 6; g.fillStyle = `rgb(${SH.orange})`; g.beginPath(); g.moveTo(x, y - 6); g.lineTo(x + 6, y); g.lineTo(x, y + 6); g.lineTo(x - 6, y); g.closePath(); g.fill();
      g.textAlign = "left"; g.fillStyle = SH.ink; g.fillText(`${P.side > 0 ? "롱" : "숏"} ${P.lev}x`, ax1 + 8, y + 3); } });
  g.font = "9px ui-monospace,monospace"; g.textAlign = "left"; g.fillStyle = SH.dim; g.fillText("신호가 바깥 셸로 들어와 · 활성이 안쪽으로 스며들고 · 코어가 공정확률을 낸다", 12, H - 6);
  g.textAlign = "right"; g.fillText(`보유 ${(ST.pos || []).length} · 실전 매매법 ${ST.nActive || 0} · 체결 ${ST.fills || 0}`, W - 12, H - 6);
}

// ── 🧠 뇌 지식 그래프 (Obsidian 그래프 뷰 스타일) ──
// 발광 노드 · 연결 수(degree)로 크기 · 유형별 색 그룹 · 부드러운 물리 이동 · 호버 시 이웃만 강조(나머지 흐리게) · 새 지식 펄스.
let brainG = null, bnodes = {}, bmouse = null;
const BCOL = { "교훈": [224, 165, 62], "패턴": [46, 194, 126], "전략": [183, 156, 255], "핵심": [255, 120, 120], "관찰": [120, 150, 220], "매매법": [94, 214, 255], "지식": [255, 200, 120] };
function drawBrain() {
  const cv = root && root.querySelector("canvas[data-brain]"); if (!cv) return;
  const dpr = Math.min(2, window.devicePixelRatio || 1), W = cv.clientWidth, H = cv.clientHeight;
  if (cv.width !== W * dpr) { cv.width = W * dpr; cv.height = H * dpr; }
  const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
  if (!brainG || !brainG.nodes.length) { g.fillStyle = "#5a6374"; g.font = "11px ui-monospace,monospace"; g.textAlign = "center"; g.fillText("뇌가 비어있음 — 모델들이 복기·거래하며 지식이 쌓입니다", W / 2, H / 2); return; }
  const cx = W / 2, cy = H / 2, ids = new Set(brainG.nodes.map(n => n.id));
  for (const n of brainG.nodes) { if (!bnodes[n.id]) bnodes[n.id] = { x: cx + (Math.random() - 0.5) * 30, y: cy + (Math.random() - 0.5) * 30, vx: 0, vy: 0, born: performance.now() }; bnodes[n.id].node = n; }
  for (const id in bnodes) if (!ids.has(+id)) delete bnodes[id];
  const arr = brainG.nodes.map(n => bnodes[n.id]);
  const rOf = (n) => 2.4 + Math.min(7, (n.deg || 0) * 0.9 + n.w * 0.7);
  const KR = (W * H) / Math.max(12, brainG.nodes.length) * 0.55;   // 이상적 간격² (면적 / 노드 수)
  const LBL = new Set([...brainG.nodes].sort((a, b) => (b.deg || 0) - (a.deg || 0) || b.w - a.w).slice(0, 12).map(n => n.id));   // 라벨은 허브 12개만   // 연결 많을수록 큰 허브 노드(obsidian식)
  // 물리: 반발 + 중심 인력 + 엣지 스프링
  for (let it = 0; it < 2; it++) {
    for (let i = 0; i < arr.length; i++) { const a = arr[i];
      for (let j = i + 1; j < arr.length; j++) { const b = arr[j]; let dx = a.x - b.x, dy = a.y - b.y; const d2 = dx * dx + dy * dy + 0.01; if (d2 < KR * 3) { const f = KR * 0.05 / d2; a.vx += dx * f; a.vy += dy * f; b.vx -= dx * f; b.vy -= dy * f; } }
      a.vx += (cx - a.x) * 0.006 * (W > H ? Math.sqrt(H / W) : 1); a.vy += (cy - a.y) * 0.008; }
    for (const [i, j, kind] of brainG.edges) { const a = arr[i], b = arr[j]; if (!a || !b) continue; const k = kind === "link" ? 0.018 : 0.010, dx = b.x - a.x, dy = b.y - a.y; a.vx += dx * k; a.vy += dy * k; b.vx -= dx * k; b.vy -= dy * k; }
    for (const a of arr) { a.vx *= 0.85; a.vy *= 0.85; a.x += Math.max(-3, Math.min(3, a.vx)); a.y += Math.max(-3, Math.min(3, a.vy)); a.x = Math.max(12, Math.min(W - 12, a.x)); a.y = Math.max(14, Math.min(H - 12, a.y)); }
  }
  // 호버된 노드 찾기(가장 가까운 것) + 이웃 집합
  let hov = -1, hd = 1e9;
  if (bmouse) arr.forEach((a, i) => { const d = (a.x - bmouse.x) ** 2 + (a.y - bmouse.y) ** 2; if (d < hd && d < 900) { hd = d; hov = i; } });
  const nb = new Set(); if (hov >= 0) { nb.add(hov); for (const [i, j] of brainG.edges) { if (i === hov) nb.add(j); if (j === hov) nb.add(i); } }
  const lit = (i) => hov < 0 || nb.has(i);
  // 엣지
  for (const [i, j, kind] of brainG.edges) { const a = arr[i], b = arr[j]; if (!a || !b) continue;
    const on = hov < 0 ? false : (i === hov || j === hov), base = kind === "link" ? 0.30 : 0.14;
    g.strokeStyle = on ? "rgba(150,180,235,0.75)" : `rgba(100,112,135,${hov < 0 ? base : base * 0.35})`;
    g.lineWidth = on ? 1.4 : (kind === "link" ? 0.9 : 0.6);
    g.beginPath(); g.moveTo(a.x, a.y); g.lineTo(b.x, b.y); g.stroke(); }
  // 노드(발광)
  for (let i = 0; i < arr.length; i++) { const a = arr[i], n = a.node, c = BCOL[n.type] || [130, 140, 160], r = rOf(n);
    const on = lit(i), al = on ? 1 : 0.22;
    const age = (performance.now() - a.born) / 700, pop = age < 1 ? 1 + (1 - age) * 1.3 : 1;
    if (age < 1 && on) { g.strokeStyle = `rgba(${c},${(1 - age) * 0.5})`; g.lineWidth = 1; g.beginPath(); g.arc(a.x, a.y, r * pop + 4 + (1 - age) * 7, 0, 7); g.stroke(); }   // 새 지식 = 퍼지는 펄스
    g.save(); g.shadowColor = `rgba(${c},${on ? 0.9 : 0.2})`; g.shadowBlur = on ? 10 + r : 4;
    g.fillStyle = `rgba(${c},${al})`; g.beginPath(); g.arc(a.x, a.y, r * pop, 0, 7); g.fill(); g.restore();
    if (on) { g.fillStyle = `rgba(255,255,255,${0.5 * al})`; g.beginPath(); g.arc(a.x - r * 0.3, a.y - r * 0.3, r * 0.34, 0, 7); g.fill(); }   // 하이라이트 점
    if (i === hov || (hov < 0 && LBL.has(n.id))) { const tx = String(n.text).slice(0, i === hov ? 40 : 16); g.font = (i === hov ? "600 " : "") + "10px ui-monospace,monospace"; g.textAlign = "center"; const tw = g.measureText(tx).width; g.fillStyle = "rgba(7,11,18,.78)"; g.fillRect(a.x - tw / 2 - 3, a.y - r - 15, tw + 6, 13); g.fillStyle = i === hov ? "#eef2f8" : "#aab3c3"; g.fillText(tx, a.x, a.y - r - 5); }
  }
  // 범례(좌하단)
  g.font = "9px ui-monospace,monospace"; g.textAlign = "left"; let lx = 8;
  for (const [t, c] of Object.entries(BCOL)) { g.fillStyle = `rgba(${c},0.9)`; g.beginPath(); g.arc(lx + 3, H - 7, 3, 0, 7); g.fill(); g.fillStyle = "#6b7488"; g.fillText(t, lx + 9, H - 4); lx += 20 + t.length * 11; }
}

function shortMd(m) { return String(m).split("/").pop().replace(/-instruct|-chat/i, "").slice(0, 18); }

const SHELL = `
<div class="nd-top"><span class="nd-brand"><span class="nd-live"></span>GH&nbsp;COIN <em>뉴럴 데스크</em></span><span class="nd-tag">AI 모델이 직접 매매·복기·학습 · 집단 뇌 · 가상자금</span>
  <marquee class="nd-feed" data-feed scrollamount="5"></marquee><span class="nd-clock"></span>
  <span class="nd-cfg" data-auto title="레버리지·시드비중·손절·익절은 AI 모델이 상황에 맞게 스스로 정합니다 (사용자 조절 아님)"></span>
  <button class="nd-btn" data-cfg title="동시 포지션 상한 · 하루 최대 진입 · 재진입 쿨다운 · 제외 코인">⚙ 한도</button><button class="nd-btn" data-local title="켜면 설치된 Ollama 로컬 모델만 트레이더로 씁니다 (무료·오프라인·한도 없음). 끄면 클라우드+로컬 혼합.">💻 로컬 전용</button><button class="nd-btn" data-ollama title="내 PC Ollama에 GH Coin용 추천 무료 모델을 자동으로 받아 트레이더로 씁니다">🖥 로컬 모델 설치</button><button class="nd-btn" data-reset>초기화</button><button class="nd-btn nd-x" data-x>✕</button></div>
<div class="nd-grid">
  <div class="nd-card nd-pnl"><div class="nd-h">가상 자본 <small>(데모 · $1000 시작 · 나만 초기화)</small></div><div class="nd-big" data-pnl></div><div class="nd-kpi" data-kpi></div></div>
  <div class="nd-card nd-mkt"><div class="nd-h">🔍 스캔 · 포지션</div><div class="nd-scan" data-scan></div><div class="nd-markets" data-markets></div></div>
  <div class="nd-card nd-shell"><div class="nd-h">NEURAL SHELL <small>마켓 피드 → 피처 레이어 → 결정 코어 · 실데이터</small></div><canvas data-shell></canvas></div>
  <div class="nd-card nd-trd"><div class="nd-h">AI 모델 트레이더 리더보드 <small>(직접 거래·복기·학습 · PnL 순)</small></div><div class="nd-neurons" data-neurons></div></div>
  <div class="nd-card nd-trades"><div class="nd-h">최근 데모 거래 · 매매법 설계</div><div class="nd-tr" data-trades></div></div>
  <div class="nd-card nd-brain"><div class="nd-h">🧠 뇌 지식 그래프 <small data-braininfo></small><button class="nd-mini" data-canvas title="JSON Canvas로 내보내기 — Obsidian에서 열 수 있어요">.canvas ↓</button></div><canvas data-brain></canvas></div>
</div>`;

function inject() {
  if (document.getElementById("nd-css")) return;
  const st = document.createElement("style"); st.id = "nd-css";
  st.textContent = `
#ndesk{position:fixed;inset:0;z-index:99999;color:var(--txt);font:12px/1.45 "SF Mono",ui-monospace,Menlo,Consolas,monospace;display:flex;flex-direction:column;overflow:hidden;font-variant-numeric:tabular-nums;
  --txt:#d4dcea;--dim:#5b6678;--line:#15202f;--line2:#1f2c40;--accent:#22d3ee;--accent2:#7c9fff;--up:#26d07c;--dn:#ff4d64;
  background:radial-gradient(1100px 560px at 82% -12%,rgba(34,211,238,.07),transparent 60%),radial-gradient(900px 520px at -5% 112%,rgba(124,159,255,.07),transparent 60%),linear-gradient(#070b12,#05080e)}
#ndesk::before{content:"";position:absolute;inset:0;pointer-events:none;opacity:.45;background-image:linear-gradient(rgba(120,160,220,.028) 1px,transparent 1px),linear-gradient(90deg,rgba(120,160,220,.028) 1px,transparent 1px);background-size:34px 34px}
#ndesk .up{color:var(--up)}#ndesk .dn{color:var(--dn)}#ndesk .dim{color:var(--dim)}
#ndesk *{scrollbar-width:thin;scrollbar-color:#1e2a3c transparent}
#ndesk ::-webkit-scrollbar{width:8px;height:8px}#ndesk ::-webkit-scrollbar-thumb{background:#1b2636;border-radius:5px}#ndesk ::-webkit-scrollbar-thumb:hover{background:#28374e}
.nd-top{display:flex;align-items:center;gap:14px;padding:10px 16px;background:rgba(7,11,19,.82);backdrop-filter:blur(12px);border-bottom:1px solid var(--line2);flex:0 0 auto;position:relative;z-index:2}
.nd-brand{display:flex;align-items:center;gap:9px;font-weight:700;letter-spacing:2px;color:#eef3fb;font-size:13px;white-space:nowrap}
.nd-brand em{font-style:normal;font-weight:800;background:linear-gradient(90deg,var(--accent),var(--accent2));-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
.nd-live{width:8px;height:8px;border-radius:50%;background:var(--up);box-shadow:0 0 8px var(--up);animation:ndpulse 2.2s infinite}
@keyframes ndpulse{0%{box-shadow:0 0 0 0 rgba(38,208,124,.55)}70%{box-shadow:0 0 0 7px rgba(38,208,124,0)}100%{box-shadow:0 0 0 0 rgba(38,208,124,0)}}
.nd-tag{color:var(--dim);font-size:10.5px;letter-spacing:.3px}
.nd-feed{flex:1;color:#8793a8;font-size:11px;-webkit-mask-image:linear-gradient(90deg,transparent,#000 4%,#000 96%,transparent)}
.nd-feed span{margin-right:28px}.nd-clock{color:#6b7a92;font-size:11px;letter-spacing:1px}
.nd-btn{background:rgba(22,30,44,.65);border:1px solid var(--line2);color:#aeb8c9;padding:5px 11px;border-radius:7px;cursor:pointer;font:inherit;font-size:11px;transition:background .15s,border-color .15s,color .15s}
.nd-btn:hover{background:rgba(34,46,66,.9);border-color:#32455f;color:#dbe4f1}.nd-x{color:var(--dn)}.nd-x:hover{background:rgba(255,77,100,.15);border-color:rgba(255,77,100,.4)}
.nd-grid{flex:1;display:grid;grid-template-columns:1.05fr 1fr;grid-template-rows:minmax(250px,auto) minmax(580px,64vh) 500px 560px;gap:12px;padding:12px;min-height:0;overflow-y:auto;position:relative;z-index:1}
.nd-card{position:relative;background:linear-gradient(180deg,rgba(14,20,33,.92),rgba(9,13,22,.92));border:1px solid var(--line);border-radius:12px;padding:12px 14px;min-height:0;overflow:auto;display:flex;flex-direction:column;box-shadow:0 1px 0 rgba(255,255,255,.03) inset,0 14px 36px -24px rgba(0,0,0,.9)}
.nd-card::before{content:"";position:absolute;left:14px;right:14px;top:0;height:1px;background:linear-gradient(90deg,transparent,rgba(34,211,238,.45),transparent)}
.nd-h{color:#8291a8;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:10px;flex:0 0 auto;display:flex;align-items:center;gap:8px;padding-left:10px;position:relative}
.nd-h::before{content:"";position:absolute;left:0;top:0;width:3px;height:12px;border-radius:2px;background:linear-gradient(var(--accent),var(--accent2));box-shadow:0 0 6px rgba(34,211,238,.4)}
.nd-h small{color:#4b5568;letter-spacing:.3px;text-transform:none}
.nd-mini{margin-left:auto;background:rgba(22,30,44,.7);border:1px solid var(--line2);color:#8a93a6;padding:2px 8px;border-radius:5px;cursor:pointer;font:10px ui-monospace,monospace;letter-spacing:0;text-transform:none;transition:.15s}.nd-mini:hover{background:#1c2740;color:var(--accent);border-color:rgba(34,211,238,.4)}
.nd-brain canvas{cursor:crosshair}
.nd-pnl .nd-big b{font-size:42px;font-weight:800;line-height:1;letter-spacing:-.5px}
.nd-pnl .nd-big b.up{background:linear-gradient(90deg,#26d07c,#86f7bd);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
.nd-pnl .nd-big small{font-size:14px;font-weight:600;margin-left:8px;letter-spacing:0}
.nd-kpi{display:flex;flex-wrap:wrap;gap:8px 16px;margin-top:12px;color:#6f7b90;font-size:11px}.nd-kpi b{color:#dbe2ef;font-weight:700}.nd-kpi>span{display:flex;gap:5px;align-items:baseline}.nd-kpi small{color:#495468}
.nd-pnl{grid-column:1/2;grid-row:1/2}.nd-mkt{grid-column:2/3;grid-row:1/2}
.nd-shell{grid-column:1/3;grid-row:2/3;background:#f3f4ef !important;border-color:#d9dcd3 !important}.nd-shell .nd-h{color:#23272e}.nd-shell .nd-h small{color:#7c838f}.nd-trd{grid-column:2/3;grid-row:3/4}
.nd-trades{grid-column:1/2;grid-row:3/4}.nd-brain{grid-column:1/3;grid-row:4/5}
.nd-shell canvas,.nd-brain canvas{flex:1;width:100%;height:100%;min-height:0;display:block}
.nd-scan{font-size:11px;color:var(--accent);margin-bottom:9px;min-height:16px;flex:0 0 auto}.nd-markets{flex:0 0 auto}.scan-roster{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}.scan-roster .sr{font-size:10px;padding:1px 6px;border:1px solid var(--line2);border-radius:4px;background:rgba(20,28,42,.6);white-space:nowrap}.nd-scan b{color:#bdeefb}
.nd-markets{display:block}
.nd-mgrid{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-bottom:9px}
.mrow{background:linear-gradient(180deg,rgba(16,22,34,.9),rgba(12,17,27,.9));border:1px solid var(--line);border-radius:8px;padding:6px 9px;display:flex;flex-direction:column;gap:2px}
.mrow>b{color:#e6ebf5;font-weight:700}.mrow em{font-style:normal;font-size:11px}
.pos-h{color:#7f8ca3;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;margin:6px 0 5px}
.prow{background:linear-gradient(180deg,rgba(16,22,34,.9),rgba(12,17,27,.9));border:1px solid var(--line);border-left:3px solid #2a3344;border-radius:8px;padding:6px 10px;margin:5px 0}
.prow.up{border-left-color:var(--up);box-shadow:-6px 0 18px -14px var(--up)}.prow.dn{border-left-color:var(--dn);box-shadow:-6px 0 18px -14px var(--dn)}
.pr1{display:flex;align-items:center;gap:7px}.pr1 b{color:#eef3fb;font-weight:700}.pr-roe{margin-left:auto;font-weight:800}
.pr2{font-size:10.5px;margin-top:3px;color:#6f7b90}
.nd-cfg{color:#8a93a6;font-size:11px;white-space:nowrap}.nd-cfg b{color:var(--accent)}
.nrow.eng{grid-template-columns:minmax(0,1.7fr) 1fr 50px 54px}
.nrow{display:grid;grid-template-columns:90px 1fr 42px 54px;align-items:center;gap:8px;margin:4px 0}
.nk{color:#b3bccb;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.nbar{height:6px;background:#121a28;border-radius:4px;overflow:hidden}.nbar i{display:block;height:100%;background:linear-gradient(90deg,var(--accent2),var(--accent))}
.nrow>b{text-align:right;color:#eef3fb}.nrow small{color:#5a6374;text-align:right}.nrow small em{font-style:normal;color:#3d4454;margin-left:4px}
.trd{grid-template-columns:18px 1fr 78px auto}.rk{color:#4b86ff;text-align:center;font-weight:700}.trd .nk{color:#dbe2ef}.trd small{white-space:nowrap}
.des{grid-template-columns:44px minmax(90px,130px) minmax(140px,1.1fr) 62px minmax(0,1.6fr)}.trow>*{min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#ndesk .warn{color:#e0a53e}#ndesk .pur{color:var(--accent2)}
.brow{display:grid;grid-template-columns:48px 1fr 34px;gap:8px;align-items:center;margin:4px 0;font-size:11px}
.bt{font-size:9px;padding:2px 6px;border-radius:5px;background:rgba(22,30,44,.8);border:1px solid var(--line);text-align:center}
.bt.up{color:var(--up);border-color:rgba(38,208,124,.25)}.bt.warn{color:#e0a53e;border-color:rgba(224,165,62,.25)}.bt.pur{color:var(--accent2);border-color:rgba(124,159,255,.25)}
.btx{color:#b3bccb;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.brow small{color:#5a6374;text-align:right}
.nsub{color:#7f8ca3;font-size:10px;margin:10px 0 4px;letter-spacing:1px;text-transform:uppercase}
.nd-tr{display:flex;flex-direction:column;gap:1px}
.trow{display:grid;grid-template-columns:44px 52px 74px 64px 76px minmax(0,1fr);gap:7px;align-items:center;padding:4px 4px;border-bottom:1px solid rgba(20,28,42,.7)}
.trow>b:first-of-type{color:#e6ebf5}
@media(max-width:760px){.nd-grid{grid-template-columns:1fr;grid-template-rows:none}.nd-grid>.nd-card{grid-column:1 !important;grid-row:auto !important;min-height:220px}.nd-pnl,.nd-mkt{min-height:auto}.nd-brand{font-size:12px;letter-spacing:1px}}`;
  document.head.appendChild(st);
  // 시계
  const clk = root.querySelector(".nd-clock"); const upd = () => { if (clk) clk.textContent = new Date().toUTCString().slice(17, 25) + " UTC"; };
  upd(); setInterval(upd, 1000);
}
