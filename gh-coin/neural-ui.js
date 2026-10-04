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
  N.startAuto();
  const tick = () => { try { ST = N.state(); render(); } catch (e) {} };
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
      return `<div class="nrow trd"><span class="rk">${i + 1}</span><span class="nk" title="${E(tr.full || tr.name)}">${tr.prov === "self" ? "⚙️ " : ""}${E(tr.name)}</span><b class="${u ? "up" : "dn"}">${money(tr.pnl)}</b><small>${tr.hit == null ? "–" : "승" + tr.hit + "%"}${tr.approved != null ? ` ·승인${tr.approved}/거절${tr.rejected}` : ""}${(typeof tr.pos === "number" ? tr.pos : tr.pos?.length) ? ` ·보유${typeof tr.pos === "number" ? tr.pos : tr.pos.length}` : ""}</small></div>`;
    }).join("") +
    (s.nModels === 0 ? `<div class="nsub dim">연결된 AI 모델이 없습니다 — 자체 엔진이 검증된 신호만 집행합니다</div>` : "") +
    engineTable(s) + evoLine(s) + neutronLine(s) +
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

// ── NEURAL SHELL 캔버스 애니메이션 ──
let parts = null, t = 0;
function draw() {
  raf = requestAnimationFrame(draw);
  drawBrain();
  const cv = root && root.querySelector("canvas[data-shell]"); if (!cv || !ST) return;
  const dpr = Math.min(2, window.devicePixelRatio || 1), W = cv.clientWidth, H = cv.clientHeight;
  if (cv.width !== W * dpr) { cv.width = W * dpr; cv.height = H * dpr; }
  const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
  t += 0.016;
  const feats = ST.feat[N.COINS[0][1]] || {}, names = (N.NEURONS && N.NEURONS.length ? N.NEURONS : Object.keys(feats));
  const nn = names.length || 6, coreX = W * 0.42, coreY = H / 2, coreR = Math.min(70, H * 0.12);
  // 전체 합의(BTC 기준) 색/세기
  const dec = ST.dec[N.COINS[0][1]] || { dir: 0, conf: 0, score: 0 };
  const bull = dec.dir > 0, col = dec.dir === 0 ? "120,130,150" : bull ? "41,110,255" : "242,54,69";
  // 피처 노드 (왼쪽) → 코어로 엣지
  names.forEach((k, i) => {
    const y = H * (0.18 + 0.64 * (i / Math.max(1, nn - 1))), x = W * 0.08, v = feats[k] || 0;
    const c2 = v > 0 ? "41,110,255" : v < 0 ? "242,54,69" : "120,130,150";
    g.strokeStyle = `rgba(${c2},${0.12 + Math.abs(v) * 0.5})`; g.lineWidth = 0.6 + Math.abs(v) * 2.2;
    g.beginPath(); g.moveTo(x + 10, y);
    const midX = W * 0.26, pulse = (Math.sin(t * 2 + i) + 1) / 2;
    g.bezierCurveTo(midX, y, midX, coreY, coreX - coreR, coreY + (y - coreY) * 0.15); g.stroke();
    // 흐르는 점
    const fp = (t * 0.25 + i * 0.13) % 1; const px = x + 10 + (coreX - coreR - x - 10) * fp, py = y + (coreY - y) * fp * 0.9;
    g.fillStyle = `rgba(${c2},${0.5 * Math.abs(v) + 0.2})`; g.beginPath(); g.arc(px, py, 1.6, 0, 7); g.fill();
    // 노드
    g.fillStyle = `rgb(${c2})`; g.beginPath(); g.arc(x, y, 4 + Math.abs(v) * 3, 0, 7); g.fill();
    g.fillStyle = "#8a93a6"; g.font = "10px ui-monospace,monospace"; g.textAlign = "left"; g.fillText(k, x + 10, y - 8);
    g.fillStyle = v > 0 ? "#4d82ff" : v < 0 ? "#f2364b" : "#788899"; g.fillText((v >= 0 ? "+" : "") + v.toFixed(2), x + 10, y + 12);
  });
  // 결정 코어
  const glow = 0.3 + Math.abs(dec.score) * 0.7;
  const grd = g.createRadialGradient(coreX, coreY, 2, coreX, coreY, coreR); grd.addColorStop(0, `rgba(${col},${glow})`); grd.addColorStop(1, `rgba(${col},0)`);
  g.fillStyle = grd; g.beginPath(); g.arc(coreX, coreY, coreR, 0, 7); g.fill();
  g.strokeStyle = `rgba(${col},0.9)`; g.lineWidth = 1.5; g.beginPath(); g.arc(coreX, coreY, coreR * 0.5 * (1 + 0.04 * Math.sin(t * 3)), 0, 7); g.stroke();
  g.fillStyle = "#e6ebf5"; g.textAlign = "center"; g.font = "bold 20px ui-monospace,monospace"; g.fillText(dec.conf + "%", coreX, coreY - 2);
  g.font = "10px ui-monospace,monospace"; g.fillStyle = `rgb(${col})`; g.fillText(dec.dir > 0 ? "LONG" : dec.dir < 0 ? "SHORT" : "FLAT", coreX, coreY + 14);
  g.fillStyle = "#6b7488"; g.fillText("DECISION CORE", coreX, coreY + coreR + 14);
  // 확률 셸 (오른쪽 입자 구름)
  const shX = W * 0.74, shR = Math.min(H * 0.4, W * 0.22), M = 420;
  if (!parts || parts.length !== M) parts = Array.from({ length: M }, () => ({ a: Math.random() * 7, r: Math.pow(Math.random(), 0.5), sp: 0.1 + Math.random() * 0.5, rd: 1 + Math.random() * 1.6 }));
  for (const p of parts) {
    p.a += 0.002 * p.sp * (bull ? 1 : -1);
    const r = p.r * shR * (1 + 0.03 * Math.sin(t + p.a * 3)), x = shX + Math.cos(p.a) * r, y = coreY + Math.sin(p.a) * r;
    const near = p.r < (0.35 + Math.abs(dec.score) * 0.5);
    g.fillStyle = `rgba(${near ? col : "150,160,175"},${near ? 0.8 : 0.35})`;
    g.beginPath(); g.arc(x, y, p.rd, 0, 7); g.fill();
  }
  // 코어→셸 연결선
  g.strokeStyle = `rgba(${col},0.25)`; g.lineWidth = 1; g.beginPath(); g.moveTo(coreX + coreR, coreY); g.lineTo(shX - shR, coreY); g.stroke();
  g.fillStyle = "#6b7488"; g.font = "10px ui-monospace,monospace"; g.textAlign = "center"; g.fillText("확률 셸 · 합의가 강할수록 코어 색으로 응집", shX, coreY + shR + 16);
  g.textAlign = "left"; g.fillText("FEATURE NEURONS", W * 0.06, H * 0.12);
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
  const rOf = (n) => 2.6 + Math.min(9, (n.deg || 0) * 1.5 + n.w * 0.9);   // 연결 많을수록 큰 허브 노드(obsidian식)
  // 물리: 반발 + 중심 인력 + 엣지 스프링
  for (let it = 0; it < 2; it++) {
    for (let i = 0; i < arr.length; i++) { const a = arr[i];
      for (let j = i + 1; j < arr.length; j++) { const b = arr[j]; let dx = a.x - b.x, dy = a.y - b.y; const d2 = dx * dx + dy * dy + 0.01; if (d2 < 11000) { const f = 170 / d2; a.vx += dx * f; a.vy += dy * f; b.vx -= dx * f; b.vy -= dy * f; } }
      a.vx += (cx - a.x) * 0.0020; a.vy += (cy - a.y) * 0.0020; }
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
    if (i === hov || (hov < 0 && (n.deg >= 3 || r > 8.5))) { g.fillStyle = i === hov ? "#eef2f8" : "#9aa4b6"; g.font = (i === hov ? "600 " : "") + "10px ui-monospace,monospace"; g.textAlign = "center"; g.fillText(String(n.text).slice(0, i === hov ? 34 : 15), a.x, a.y - r - 4); }
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
  <button class="nd-btn" data-local title="켜면 설치된 Ollama 로컬 모델만 트레이더로 씁니다 (무료·오프라인·한도 없음). 끄면 클라우드+로컬 혼합.">💻 로컬 전용</button><button class="nd-btn" data-ollama title="내 PC Ollama에 GH Coin용 추천 무료 모델을 자동으로 받아 트레이더로 씁니다">🖥 로컬 모델 설치</button><button class="nd-btn" data-reset>초기화</button><button class="nd-btn nd-x" data-x>✕</button></div>
<div class="nd-grid">
  <div class="nd-card nd-pnl"><div class="nd-h">가상 자본 <small>(데모 · $1000 시작 · 나만 초기화)</small></div><div class="nd-big" data-pnl></div><div class="nd-kpi" data-kpi></div></div>
  <div class="nd-card nd-mkt"><div class="nd-h">🔍 스캔 · 포지션</div><div class="nd-scan" data-scan></div><div class="nd-markets" data-markets></div></div>
  <div class="nd-card nd-shell"><div class="nd-h">뉴럴 셸 · 피처 → 결정 코어 → 확률 셸</div><canvas data-shell></canvas></div>
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
.nd-grid{flex:1;display:grid;grid-template-columns:1.05fr 1fr;grid-template-rows:auto 1.05fr 0.82fr;gap:12px;padding:12px;min-height:0;position:relative;z-index:1}
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
.nd-shell{grid-column:1/2;grid-row:2/3}.nd-trd{grid-column:2/3;grid-row:2/3}
.nd-trades{grid-column:1/2;grid-row:3/4}.nd-brain{grid-column:2/3;grid-row:3/4}
.nd-shell canvas,.nd-brain canvas{flex:1;width:100%;height:100%;min-height:0;display:block}
.nd-scan{font-size:11px;color:var(--accent);margin-bottom:9px;min-height:16px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.nd-scan b{color:#bdeefb}
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
.des{grid-template-columns:36px 68px 118px 48px 1fr}
#ndesk .warn{color:#e0a53e}#ndesk .pur{color:var(--accent2)}
.brow{display:grid;grid-template-columns:48px 1fr 34px;gap:8px;align-items:center;margin:4px 0;font-size:11px}
.bt{font-size:9px;padding:2px 6px;border-radius:5px;background:rgba(22,30,44,.8);border:1px solid var(--line);text-align:center}
.bt.up{color:var(--up);border-color:rgba(38,208,124,.25)}.bt.warn{color:#e0a53e;border-color:rgba(224,165,62,.25)}.bt.pur{color:var(--accent2);border-color:rgba(124,159,255,.25)}
.btx{color:#b3bccb;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.brow small{color:#5a6374;text-align:right}
.nsub{color:#7f8ca3;font-size:10px;margin:10px 0 4px;letter-spacing:1px;text-transform:uppercase}
.nd-tr{display:flex;flex-direction:column;gap:1px}
.trow{display:grid;grid-template-columns:38px 40px 52px 58px 62px 1fr;gap:7px;align-items:center;padding:4px 4px;border-bottom:1px solid rgba(20,28,42,.7)}
.trow>b:first-of-type{color:#e6ebf5}
@media(max-width:760px){.nd-grid{grid-template-columns:1fr;grid-template-rows:none}.nd-grid>.nd-card{grid-column:1 !important;grid-row:auto !important;min-height:220px}.nd-pnl,.nd-mkt{min-height:auto}.nd-brand{font-size:12px;letter-spacing:1px}}`;
  document.head.appendChild(st);
  // 시계
  const clk = root.querySelector(".nd-clock"); const upd = () => { if (clk) clk.textContent = new Date().toUTCString().slice(17, 25) + " UTC"; };
  upd(); setInterval(upd, 1000);
}
