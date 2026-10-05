// 🧠 뉴럴 데스크 대시보드 — 연결된 AI 모델/피처 뉴런이 직접 데모 매매·학습하는 모습을 풀스크린으로.
// 디자인: 다크 터미널 + NEURAL SHELL(피처 → 결정 코어 → 확률 셸) 애니메이션. 전부 가상자금.
import * as VZ from "./neural-viz.js";
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
  // ⚡ 실시간 진입: 지금 분석 (사무실 runLiveEntry 와 같은 엔진·토론)
  const rtb = root.querySelector("[data-rtgo]");
  if (rtb) rtb.onclick = async () => { try { if (typeof Notification !== "undefined" && Notification.permission === "default") Notification.requestPermission(); } catch (e) {}
    rtb.disabled = true; rtb.textContent = "⏳ 분석·토론 중…"; try { const O = await import("./coin-office.js"); await O.runLiveEntry({ debate: true, by: "user" }); } catch (e) { feed("⚡ 실시간 진입 실패: " + (e?.message || e)); } rtb.disabled = false; rtb.textContent = "⚡ 지금 분석"; render(); };
  // ⚡ 시장가(코인별): 누르면 그 코인을 바로 분석 → 에이전트 팀 ↔ 뉴트론 토론 → 시장가 추천
  const rc = root.querySelector("[data-rtcoins]");
  if (rc) { rc.innerHTML = N.COINS.map(([ko, sym]) => `<button class="nd-mini rt-mk" data-mkt="${sym}" title="${ko} 시장가: 지금 들어간다면 롱/숏·손절·익절·승률 + 팀↔뉴트론 토론">⚡ ${ko}</button>`).join("");
    rc.onclick = async (ev) => { const b = ev.target.closest("[data-mkt]"); if (!b || b.disabled) return; const t0 = b.textContent; b.disabled = true;
      try { const O = await import("./coin-office.js"); await O.marketEntryNow({ sym: b.dataset.mkt, by: "user", onStep: (t) => { b.textContent = "⏳ " + t.replace(/^\S+\s*/, "").slice(0, 10); } }); } catch (e) { feed("⚡ 시장가 실패: " + (e?.message || e)); }
      b.disabled = false; b.textContent = t0; ST = N.state(); render(); }; }
  // 📈 내 차트 지표 데스크 버튼(지금 점검·복사) — 렌더가 3초마다 바뀌므로 위임
  root.querySelector("[data-neurons]")?.addEventListener("click", async (ev) => {
    const cp = ev.target.closest("[data-cdcopy]"); if (cp) { try { await navigator.clipboard.writeText(cp.dataset.cdcopy); cp.textContent = "복사됨"; } catch (e) {} return; }
    const go = ev.target.closest("[data-cdgo]"); if (go) { go.disabled = true; go.textContent = "점검 중…"; try { await N.chartDesk(true); } catch (e) { feed("📈 점검 실패: " + (e?.message || e)); } ST = N.state(); render(); }
  });
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
// 📈 내 차트 지표 데스크: 값 튜닝 추천 · 보조지표 추천 · AI 설계 시도 · AI 실험 진입 (차트 적용은 사용자가 직접)
function chartDeskLine(s) {
  const D = s.chartDesk, X = s.aiExp || {}, st = X.stat || {};
  let h = `<div class="nsub">📈 내 차트 지표 데스크 <span class="dim">${D ? `${E(D.sym.replace("USDT", ""))} ${E(D.interval)} · ${ago(D.t)} 전 점검` : "차트 터미널에 지표를 띄우면 15분 안에 점검"}</span><button class="nd-mini" data-cdgo style="margin-left:6px">지금 점검</button></div>`;
  if (D) {
    const ch = (D.rows || []).filter(r => r.changed);
    h += `<div class="brow"><span class="bt warn">값</span><span class="btx" title="처음 보는 뒤 30% 에서도 나아진 것만 · 차트 적용은 직접 하세요">${ch.length ? ch.map(r => `${E(r.name)}: <b>${E(r.changed)}</b> <small class="dim">(가짜 신호 ${r.before.whip}→${r.after.whip}% · 적중 ${r.before.hit}→${r.after.hit}%)</small>`).join(" · ") : "지금 값이 가장 좋음(바꿀 것 없음)"}</span>${ch.length ? `<button class="nd-mini" data-cdcopy="${E(ch.map(r => r.name + ": " + r.changed).join(" / "))}">복사</button>` : ""}</div>`;
    const top = D.recs?.top || [];
    h += `<div class="brow"><span class="bt pur">추천</span><span class="btx" title="넣었을 때 내 지표 합의 매매법의 처음 보는 구간 성적 변화 + 다른 코인 2개 확인">${top.length ? top.map(x => `<b>${E(x.name)}</b> ${E(Object.entries(x.params || {}).filter(([k]) => k !== "source").map(([k, v]) => k + " " + v).join(", "))} <small class="dim">(+${x.delta}R · 다른 코인 ${(x.crossDelta || []).map(d => (d >= 0 ? "+" : "") + d).join("/")})</small>`).join(" · ") : "넣어서 확실히 좋아지는 지표 없음"}</span>${top.length ? `<button class="nd-mini" data-cdcopy="${E(top.map(x => x.name + " " + JSON.stringify(x.params)).join(" / "))}">복사</button>` : ""}</div>`;
    for (const a of (D.attempts || []).slice(0, 3)) h += `<div class="brow"><span class="bt ${a.pass ? "up" : "dim"}">AI설계</span><span class="btx" title="${E(a.reason)}">${E(a.model)}: ${E(a.names.join("+"))} ${a.k}/${a.n} · 손익비 ${a.rr} → 처음 보는 구간 ${a.test.mean >= 0 ? "+" : ""}${a.test.mean}R(${a.test.n}) · 다른 코인 ${a.crossPos}/5 ${a.pass ? "✅ 데모 투입" : "❌"}</span><small>${ago(a.t)}</small></div>`;
  }
  h += `<div class="brow"><span class="bt dim">AI실험</span><span class="btx" title="스캔한 모델이 확신 75%↑ + 내 지표 60%↑ 동조일 때 리스크 0.25% 데모 진입 · 실전 10건 평균이 마이너스면 24시간 중지">${X.pausedUntil > Date.now() ? "⏸ 중지 중 · " : ""}오늘 ${X.n || 0}/4회 · 실전 ${st.live || 0}건 ${st.live ? `평균 ${st.mean >= 0 ? "+" : ""}${st.mean}R · 승률 ${st.wr}%` : ""}</span></div>`;
  return h;
}
function robinLine(s) {
  const w = s.whale, tr = w?.trust, c = s.cfg || {}, rv = s.review2;
  return `<div class="nsub">🐋 고래 카피 · 🗂 포지션 관리 · ⚙ 한도</div>`
    + `<div class="brow"><span class="bt pur">고래</span><span class="btx" title="감지→필터→리스크→신호 · 30분 뒤 채점">${(w?.last || []).map(x => `${E(x.sym.replace("USDT", ""))} ${x.dir > 0 ? "▲" : "▼"}${Math.abs(x.netPct)}%`).join(" · ") || "승인된 고래 신호 없음"} <small class="dim">· 적중 ${tr?.n ? Math.round(tr.acc * 100) + "% (" + tr.n + "회)" : "학습 중"}</small></span></div>`
    + (rv ? `<div class="brow"><span class="bt up">관리</span><span class="btx" title="${E((rv.dropped || []).join(" / "))}">${E(rv.by)}: ${E((rv.done || []).join(" · ") || "모두 유지")}${rv.dropped?.length ? ` <small class="dim">· 환각 필터 ${rv.dropped.length}건</small>` : ""} <small class="dim">${ago(rv.t)} 전</small></span></div>` : "")
    + (() => { let cs = []; try { cs = N.chartStrategies?.() || []; } catch (e) {} return cs.length ? `<div class="brow"><span class="bt up">내지표</span><span class="btx" title="차트 터미널 🔬 내 지표 연구소에서 데모 투입한 매매법 — 자체 백테스트 + 최근 기대값 +0.1R↑ 이어야 실제 데모 진입">${cs.map(x => `${x.active ? "✅" : "··"} ${E(x.name)}@${x.tf}${x.stat.n ? ` ${x.stat.mean >= 0 ? "+" : ""}${x.stat.mean}R/${x.stat.n}` : " (검증 대기)"}`).join(" · ")}</span></div>` : ""; })()
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
    engineTable(s) + evoLine(s) + chartDeskLine(s) + robinLine(s) + neutronLine(s) +
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
  // ⚡ 실시간 진입 카드
  const rtEl = root.querySelector("[data-rt]");
  if (rtEl) { let R = null; try { R = JSON.parse(localStorage.getItem("coinLiveEntry") || "null"); } catch (e) {}
    const gc = g => ({ "유력": 3, "보통": 2, "대기": 1 }[g] ?? 0);
    if (!R?.list?.length) rtEl.innerHTML = `<div class="dim" style="padding:6px">아직 분석 전 — 앱이 켜지면 40초 뒤부터 3분마다 자동 분석합니다. [⚡ 지금 분석]을 누르면 바로 합니다.</div>`;
    else rtEl.innerHTML = `<div class="dim" style="grid-column:1/-1;font-size:11px">${ago(R.t)} 전 분석${R.by === "user" ? " (직접 요청)" : ""} · <b>유력</b> = 워크포워드 검증을 통과한 매매법 신호가 지금 같은 방향 · <b>보통</b> = 추세 동행(우위 미확인) · 그 외 관망 · 2개월·6코인 표본외 검증: 지표·지지저항·호가 스냅샷 조합만으로는 우위 없음(−0.12R) · 승률은 과거 통계일 뿐 보장 아님 · 15분 유효</div>`
      + [...R.list].filter(r => r.best).sort((a, b) => ((b.market && Date.now() - b.t < 15 * 60e3) ? b.t : 0) - ((a.market && Date.now() - a.t < 15 * 60e3) ? a.t : 0) || gc(b.best.grade) - gc(a.best.grade) || b.best.exp - a.best.exp).map(r => { const b = r.best, g = gc(b.grade), L = b.side > 0, live = Date.now() < b.validUntil;
        const cur = s.dec?.[r.sym]?.price, gone = cur && b.invalidPx && (L ? cur >= b.invalidPx : cur <= b.invalidPx);
        const txt = `${r.ko} ${L ? "롱" : "숏"} 시장가 ${fmtp(b.entry)} / 손절 ${fmtp(b.sl)} / 익절1 ${fmtp(b.tp1)} / 익절2 ${fmtp(b.tp2)} / 레버 ≤${b.lev}x`;
        const d = b.debate;
        const mk = r.market && Date.now() - r.t < 15 * 60e3 ? `<div class="kv" style="margin:2px 0 4px;font-weight:700;color:${r.market.go ? "#4ff0a0" : "#ffcf6a"}">⚡ 시장가 판정: ${E(r.market.label)}</div>` : "";
        return `<div class="rtc g${g}">${mk}<div class="rh"><b>${E(r.ko)}</b><span class="${L ? "up" : "dn"}" style="font-weight:700">${L ? "▲ 롱" : "▼ 숏"}</span><span class="gb g${g}">${E(b.grade)}</span>${!live || gone ? `<span class="gb g0">${gone ? "가격 이탈·무효" : "만료"}</span>` : ""}<span class="dim" style="margin-left:auto;font-size:10px">합류 ${b.score}/100</span><button class="cp" data-copy="${E(txt)}">복사</button></div>`
          + `<div class="px"><div><small>시장가 진입</small><b>${fmtp(b.entry)}</b></div><div><small>손절 −${b.slPct}%</small><b class="dn">${fmtp(b.sl)}</b></div><div><small>익절1 +${b.tp1Pct}% (${b.rr1}R)</small><b class="up">${fmtp(b.tp1)}</b></div><div><small>익절2 +${b.tp2Pct}% (${b.rr}R)</small><b class="up">${fmtp(b.tp2)}</b></div></div>`
          + `<div class="kv"><span title="보정값 = 조건 없는 기준값 쪽으로 축소한 값(표본외 검증에서 날것 통계가 과대평가되어 적용)">익절1 도달률 <b>${b.wr}%</b> <small class="dim">(보정 · 과거 통계 ${b.wrRaw ?? b.wr}% · ${b.n}표본)</small></span><span>계획 기대값 <b class="${b.exp >= 0 ? "up" : "dn"}">${b.exp >= 0 ? "+" : ""}${b.exp}R</b></span><span>권장 레버 <b>≤${b.lev}x</b> · 청산 ${fmtp(b.liq)}</span>${r.book ? `<span>호가 ±1% <b>${(r.book.imb1 * 100).toFixed(0)}%</b></span>` : ""}</div>`
          + `<div class="kv" style="margin-top:4px;color:${b.sig ? "#8fe6b8" : "#9aa4b6"}">📌 ${E(b.evidence || "")}</div>`
          + (b.limitAlt ? `<div class="kv" style="margin-top:4px;color:#ffcf6a">⏳ ${E(b.limitAlt.note)} (지정가 ${fmtp(b.limitAlt.entry)})</div>` : "")
          + `<div class="chips">${b.why.slice(0, 6).map(x => `<span>${E(x)}</span>`).join("")}${b.warn.slice(0, 4).map(x => `<span class="w">${E(x)}</span>`).join("")}</div>`
          + (d ? `<div class="db">⚖ ${E(d.verdict)} · 팀(${E(d.team?.who || "")}) <b class="${d.team?.stance === "찬성" ? "up" : d.team?.stance === "반대" ? "dn" : ""}">${E(d.team?.stance || "—")}</b> ${E(d.team?.reason || "")}${d.team?.applied ? ` <span class="dim">(${E(d.team.applied)})</span>` : ""}<br>뉴럴(${E(d.neural?.model || "—")}) <b class="${d.neural?.stance === "찬성" ? "up" : d.neural?.stance === "반대" ? "dn" : ""}">${E(d.neural?.stance || "—")}</b> ${E(d.neural?.reason || "")}</div>` : "")
          + `</div>`; }).join("");
    rtEl.querySelectorAll("[data-copy]").forEach(bt => bt.onclick = () => { try { navigator.clipboard.writeText(bt.dataset.copy); bt.textContent = "복사됨"; } catch (e) {} });
  }
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
  try { VZ.renderShell(root.querySelector("[data-vzshell]"), s, N); } catch (e) { console.warn(e); }
  try { VZ.renderBrain(root.querySelector("[data-vzbrain]"), s, brainG); } catch (e) { console.warn(e); }
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
  if (!root || !ST) return;
  try { VZ.frameShell(root.querySelector("[data-vzshell]")); } catch (e) {}
  try { VZ.frameBrain(root.querySelector("[data-vzbrain]")); } catch (e) {}
}

// ── NEURAL SHELL: 실행 그래프 (노드 = 코인·피처·내 지표·매매법·AI 모델·게이트·포지션 / 엣지 = 실제 데이터 흐름) ──
//   노란 '공유 면'(GATE) = 주문 대기열: 게이트가 초록일 때만 진입이 써진다(일일 손실·동시 리스크·모드 통과).
const GN = {};   // id → {x, y, vx, vy}
let gEdges = [], gNodes = [], gAt = 0, pulses = [];
const GC = { coin: [80, 160, 255], feat: [150, 160, 180], ind: [255, 150, 60], strat: [120, 200, 255], stratOn: [60, 230, 150], model: [190, 140, 255], gate: [255, 214, 0], pos: [255, 120, 90] };
function buildGraph() {
  const s = ST, nodes = [], edges = [], add = (id, kind, label, extra = {}) => nodes.push({ id, kind, label, ...extra });
  for (const [ko, sym] of N.COINS) add("c:" + sym, "coin", ko, { sym, reg: s.regime?.[sym] });
  for (const f of N.NEURONS) add("f:" + f, "feat", f);
  const myInd = (s.chartDesk?.now?.["15"] || []).slice(0, 8);
  myInd.forEach((x, i) => add("i:" + i, "ind", x.name, { dir: x.dir }));
  const eng = (s.engine || []).slice(0, 40);
  eng.forEach(e => add("s:" + e.vkey, e.active ? "stratOn" : "strat", e.name, { mean: e.mean, n: e.n, active: e.active }));
  const models = (s.traders || []).filter(x => x.prov !== "self").slice(0, 10);
  models.forEach(m => add("m:" + m.name, "model", m.name, { busy: s.scan?.model === m.name, last: m.last }));
  add("gate", "gate", "GATE");
  (s.pos || []).concat(...(s.traders || []).filter(x => Array.isArray(x.pos)).map(x => x.pos)).forEach(p => add("p:" + p.sym, "pos", `${p.ko} ${p.side > 0 ? "롱" : "숏"} ${p.lev}x`, { sym: p.sym, roe: p.roe }));
  for (const [ko, sym] of N.COINS) { for (const f of N.NEURONS) edges.push(["c:" + sym, "f:" + f, 0]); myInd.forEach((_, i) => edges.push(["c:" + sym, "i:" + i, 0])); }
  eng.forEach((e, k) => { for (const f of N.NEURONS.slice(k % 3, k % 3 + 2)) edges.push(["f:" + f, "s:" + e.vkey, 0]); if (String(e.vkey).startsWith("chart_")) myInd.forEach((_, i) => edges.push(["i:" + i, "s:" + e.vkey, 0])); if (e.active) edges.push(["s:" + e.vkey, "gate", 1]); });
  models.forEach(m => { edges.push(["m:" + m.name, "gate", 1]); const sym = N.COINS.find(c => c[0] === (m.last?.ko || ""))?.[1]; if (sym) edges.push(["m:" + m.name, "c:" + sym, m.busy ? 2 : 0]); });
  nodes.filter(n => n.kind === "pos").forEach(n => { edges.push(["gate", n.id, 2]); edges.push([n.id, "c:" + n.sym, 1]); });
  return { nodes, edges };
}
function anchor(kind, W, H) {
  return ({ coin: [0.1, 0.5], feat: [0.26, 0.5], ind: [0.26, 0.82], strat: [0.47, 0.5], stratOn: [0.55, 0.42], model: [0.72, 0.62], gate: [0.78, 0.36], pos: [0.9, 0.4] })[kind].map((v, i) => v * (i ? H : W));
}
function drawGraph(g, W, H) {
  if (!gAt || performance.now() - gAt > 2500) { gAt = performance.now(); const b = buildGraph(); gNodes = b.nodes; gEdges = b.edges; }
  const idx = {}; gNodes.forEach((n, i) => { idx[n.id] = i; if (!GN[n.id]) { const [ax, ay] = anchor(n.kind, W, H); GN[n.id] = { x: ax + (Math.random() - 0.5) * 60, y: ay + (Math.random() - 0.5) * 60, vx: 0, vy: 0 }; } });
  const P = gNodes.map(n => GN[n.id]);
  // 물리: 그룹 앵커 인력 + 반발 + 엣지 스프링
  for (let it = 0; it < 2; it++) {
    for (let i = 0; i < P.length; i++) { const a = P[i], [ax, ay] = anchor(gNodes[i].kind, W, H); a.vx += (ax - a.x) * 0.006; a.vy += (ay - a.y) * 0.006;
      for (let j = i + 1; j < P.length; j++) { const b = P[j], dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy + 0.1; if (d2 < 2600) { const f = 60 / d2; a.vx += dx * f; a.vy += dy * f; b.vx -= dx * f; b.vy -= dy * f; } } }
    for (const [u, v] of gEdges) { const a = P[idx[u]], b = P[idx[v]]; if (!a || !b) continue; const dx = b.x - a.x, dy = b.y - a.y; a.vx += dx * 0.0008; a.vy += dy * 0.0008; b.vx -= dx * 0.0008; b.vy -= dy * 0.0008; }
    for (const a of P) { a.vx *= 0.82; a.vy *= 0.82; a.x = Math.max(16, Math.min(W - 16, a.x + a.vx)); a.y = Math.max(46, Math.min(H - 54, a.y + a.vy)); }
  }
  // 배경: 유리판 + 격자
  const bg = g.createLinearGradient(0, 0, 0, H); bg.addColorStop(0, "#07101c"); bg.addColorStop(1, "#04070d"); g.fillStyle = bg; g.fillRect(0, 0, W, H);
  g.strokeStyle = "rgba(90,140,200,.05)"; g.lineWidth = 1; for (let x = 0; x < W; x += 28) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, H); g.stroke(); } for (let y = 0; y < H; y += 28) { g.beginPath(); g.moveTo(0, y); g.lineTo(W, y); g.stroke(); }
  // 게이트 상태
  const gateOpen = (ST.riskMode || "정상") === "정상" && (ST.heat ?? 0) < 4 && !(ST.news?.blockUntil > Date.now());
  // 엣지
  for (const [u, v, w] of gEdges) { const a = P[idx[u]], b = P[idx[v]]; if (!a || !b) continue;
    const toGate = v === "gate" || u === "gate";
    g.strokeStyle = w === 2 ? "rgba(255,214,0,.55)" : w === 1 ? (toGate ? "rgba(120,220,255,.28)" : "rgba(120,220,255,.2)") : "rgba(110,140,190,.07)";
    g.lineWidth = w === 2 ? 1.4 : w === 1 ? 0.9 : 0.6; g.beginPath(); g.moveTo(a.x, a.y); g.lineTo(b.x, b.y); g.stroke(); }
  // 흐름 펄스 (활성 엣지 위로 이동)
  const live = gEdges.filter(e => e[2] > 0);
  if (live.length && Math.random() < 0.35) pulses.push({ e: live[Math.floor(Math.random() * live.length)], u: 0, sp: 0.008 + Math.random() * 0.012 });
  pulses = pulses.filter(p => (p.u += p.sp) < 1).slice(-120);
  for (const p of pulses) { const a = P[idx[p.e[0]]], b = P[idx[p.e[1]]]; if (!a || !b) continue; const x = a.x + (b.x - a.x) * p.u, y = a.y + (b.y - a.y) * p.u;
    g.fillStyle = p.e[2] === 2 ? "rgba(255,214,0,.95)" : "rgba(130,230,255,.9)"; g.beginPath(); g.arc(x, y, 1.8, 0, 7); g.fill(); }
  // 노드
  gNodes.forEach((n, i) => { const a = P[i], c = GC[n.kind], r = n.kind === "gate" ? 13 : n.kind === "coin" ? 7 : n.kind === "model" ? 6 : n.kind === "pos" ? 7 : n.kind === "stratOn" ? 5 : 3.2;
    if (n.kind === "gate") { const gc = gateOpen ? [60, 230, 150] : [255, 80, 90];
      g.save(); g.shadowColor = `rgba(${GC.gate},.9)`; g.shadowBlur = 18; g.fillStyle = `rgba(${GC.gate},.95)`; g.beginPath(); g.arc(a.x, a.y, r, 0, 7); g.fill(); g.restore();
      g.strokeStyle = `rgb(${gc})`; g.lineWidth = 2.5; g.beginPath(); g.arc(a.x, a.y, r + 5 + Math.sin(t * 3) * 1.5, 0, 7); g.stroke();
      g.fillStyle = "#111"; g.font = "bold 12px ui-monospace,monospace"; g.textAlign = "center"; g.fillText(gateOpen ? "✓" : "🔒", a.x, a.y + 4);
      g.fillStyle = `rgb(${GC.gate})`; g.font = "600 10px ui-monospace,monospace"; g.fillText("GATE · 주문 대기열 " + (ST.queue || 0), a.x, a.y - r - 9); g.fillStyle = `rgb(${gc})`; g.fillText(gateOpen ? "초록 = 진입 가능" : "잠김 = 진입 보류", a.x, a.y + r + 16); return; }
    g.save(); if (n.kind === "stratOn" || n.busy || n.kind === "pos") { g.shadowColor = `rgba(${c},.9)`; g.shadowBlur = 10; }
    g.fillStyle = `rgba(${c},${n.kind === "strat" ? 0.5 : 0.95})`; g.beginPath(); g.arc(a.x, a.y, r * (n.busy ? 1.3 + 0.2 * Math.sin(t * 6) : 1), 0, 7); g.fill(); g.restore();
    const showLabel = n.kind === "coin" || n.kind === "model" || n.kind === "pos" || n.kind === "stratOn" || n.kind === "ind" || n.kind === "feat";
    if (showLabel) { g.font = (n.kind === "coin" ? "700 " : "") + "10px ui-monospace,monospace"; g.textAlign = n.kind === "coin" ? "right" : "left"; g.fillStyle = n.kind === "pos" ? (n.roe >= 0 ? "#4ff0a0" : "#ff7a8a") : n.kind === "ind" ? (n.dir > 0 ? "#4ff0a0" : n.dir < 0 ? "#ff7a8a" : "#9aa") : "#b8c4d8";
      const lbl = n.kind === "stratOn" ? `${String(n.label).slice(0, 18)} ${n.mean >= 0 ? "+" : ""}${n.mean}R` : n.kind === "pos" ? `${n.label} ${n.roe >= 0 ? "+" : ""}${(+n.roe || 0).toFixed(1)}%` : n.kind === "coin" ? `${n.label} ${n.reg?.htf > 0 ? "▲" : n.reg?.htf < 0 ? "▼" : "·"}` : n.kind === "ind" ? `${String(n.label).slice(0, 14)} ${n.dir > 0 ? "↑" : n.dir < 0 ? "↓" : "·"}` : String(n.label).slice(0, 16);
      g.fillText(lbl, a.x + (n.kind === "coin" ? -10 : 9), a.y + 3); } });
  // 상단 머리글 (그래프 메타)
  const nAct = (ST.engine || []).filter(e => e.active).length, models = (ST.traders || []).filter(x => x.prov !== "self"), busy = models.filter(m => ST.scan?.model === m.name).length;
  g.font = "700 11px ui-monospace,monospace"; g.textAlign = "left"; g.fillStyle = "#7fd3ff"; g.fillText(`GRAPH NEURAL-RUN-${ST.epoch || 0}`, 14, 20);
  g.font = "10px ui-monospace,monospace"; g.fillStyle = "#6f7f99";
  g.fillText(`${gNodes.length} 노드 · ${gEdges.length} 엣지 · 매매법 ${(ST.engine || []).length}개 중 실전 ${nAct} · 워커(AI 모델) ${models.length} · 작업 중 ${busy} · 대기 ${ST.queue || 0}`, 14, 34);
  g.textAlign = "right"; g.fillStyle = gateOpen ? "#4ff0a0" : "#ff7a8a"; g.fillText(gateOpen ? "게이트 초록 — 공유 면(주문 대기열)에 쓸 수 있음" : "게이트 잠김 — 조건 통과 전엔 진입이 써지지 않음", W - 14, 20);
  g.fillStyle = "#6f7f99"; g.fillText(`동시 리스크 ${ST.heat ?? 0}% · 오늘 ${ST.dayN ?? 0}회 진입 · 모드 ${ST.riskMode || "정상"}`, W - 14, 34);
  // 하단 파이프라인 (단계별 실제 숫자)
  const st = [["SCAN", models.reduce((a, m) => a + (m.scans || 0), 0)], ["REGIME", Object.keys(ST.regime || {}).length], ["SIGNAL", ST.queue || 0], ["VALIDATE", `${nAct}/${(ST.engine || []).length}`], ["GATE", gateOpen ? "OPEN" : "LOCK"], ["APPROVE", models.reduce((a, m) => a + (m.approved || 0), 0)], ["EXECUTE", ST.fills || 0], ["MANAGE", (ST.pos || []).length + models.reduce((a, m) => a + (Array.isArray(m.pos) ? m.pos.length : 0), 0)]];
  const bw = (W - 28) / st.length, by = H - 40;
  st.forEach(([k, v], i) => { const x = 14 + i * bw, on = k === "GATE" ? gateOpen : +v || (typeof v === "string" && v !== "0/0");
    g.fillStyle = k === "GATE" ? (gateOpen ? "rgba(60,230,150,.12)" : "rgba(255,80,90,.12)") : "rgba(120,180,255,.06)"; g.fillRect(x + 2, by, bw - 4, 30);
    g.fillStyle = k === "GATE" ? `rgb(${GC.gate})` : on ? "#7fd3ff" : "#4b5a70"; g.fillRect(x + 2, by, bw - 4, 2);
    g.textAlign = "left"; g.font = "600 9px ui-monospace,monospace"; g.fillStyle = "#6f7f99"; g.fillText(`${String(i + 1).padStart(2, "0")} ${k}`, x + 8, by + 13);
    g.font = "700 11px ui-monospace,monospace"; g.fillStyle = "#dbe6f5"; g.fillText(String(v), x + 8, by + 26);
    if (i < st.length - 1) { g.fillStyle = "#33445c"; g.fillText("›", x + bw - 8, by + 19); } });
}

// ── 🧠 뇌 파운드리: 레이더 (기억 = 블립 · 유형별 구역 · 안쪽일수록 강한 기억 · 스윕이 지나갈 때 밝아짐) ──
let brainG = null, bmouse = null;
const BCOL = { "교훈": [224, 165, 62], "패턴": [46, 194, 126], "전략": [183, 156, 255], "핵심": [255, 120, 120], "관찰": [120, 150, 220], "매매법": [94, 214, 255], "지식": [255, 200, 120] };
const TYPES = Object.keys(BCOL);
const hash = s => { let h = 2166136261; for (const ch of String(s)) h = Math.imul(h ^ ch.charCodeAt(0), 16777619); return (h >>> 0) / 4294967296; };
function drawBrain() {
  const cv = root && root.querySelector("canvas[data-brain]"); if (!cv) return;
  const dpr = Math.min(2, window.devicePixelRatio || 1), W = cv.clientWidth, H = cv.clientHeight; if (W < 50 || H < 50) return;
  if (cv.width !== W * dpr) { cv.width = W * dpr; cv.height = H * dpr; }
  const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.fillStyle = "#04080e"; g.fillRect(0, 0, W, H);
  const B = ST?.brain || {}, nodes = brainG?.nodes || [], iq = B.iq || {};
  const R = Math.min(H * 0.42, W * 0.22), cx = W * 0.36, cy = H * 0.52, sweep = (performance.now() / 1000 * 0.9) % (Math.PI * 2);
  // 레이더 판
  for (let k = 1; k <= 4; k++) { g.strokeStyle = `rgba(80,200,140,${0.08 + k * 0.03})`; g.lineWidth = 1; g.beginPath(); g.arc(cx, cy, R * k / 4, 0, 7); g.stroke(); }
  TYPES.forEach((tp, i) => { const a = i / TYPES.length * Math.PI * 2 - Math.PI / 2; g.strokeStyle = "rgba(80,200,140,.12)"; g.beginPath(); g.moveTo(cx, cy); g.lineTo(cx + Math.cos(a) * R, cy + Math.sin(a) * R); g.stroke();
    const am = a + Math.PI / TYPES.length, c = BCOL[tp]; g.fillStyle = `rgba(${c},.85)`; g.font = "600 10px ui-monospace,monospace"; g.textAlign = "center"; g.fillText(`${tp} ${B.byType?.[tp] || 0}`, cx + Math.cos(am) * (R + 16), cy + Math.sin(am) * (R + 16) + 3); });
  // 스윕
  const sg = g.createConicGradient ? g.createConicGradient(sweep - 0.6, cx, cy) : null;
  if (sg) { sg.addColorStop(0, "rgba(80,255,160,0)"); sg.addColorStop(0.095, "rgba(80,255,160,.22)"); sg.addColorStop(0.1, "rgba(80,255,160,0)"); g.fillStyle = sg; g.beginPath(); g.arc(cx, cy, R, 0, 7); g.fill(); }
  g.strokeStyle = "rgba(120,255,180,.7)"; g.lineWidth = 1.5; g.beginPath(); g.moveTo(cx, cy); g.lineTo(cx + Math.cos(sweep) * R, cy + Math.sin(sweep) * R); g.stroke();
  // 블립 (기억)
  let hov = null, hd = 1e9;
  const perType = {};
  for (const n of nodes) { const ti = Math.max(0, TYPES.indexOf(n.type)), k = (perType[n.type] = (perType[n.type] || 0) + 1) - 1, a0 = ti / TYPES.length * Math.PI * 2 - Math.PI / 2;
    const a = a0 + (0.1 + ((k * 0.6180339 + hash(n.id) * 0.15) % 1) * 0.8) * (Math.PI * 2 / TYPES.length);   // 같은 유형끼리 황금각으로 고르게
    const rr = R * Math.min(0.95, 0.14 + 0.55 * (1 - Math.min(1, (n.w || 1) / 6)) + 0.3 * ((k * 0.381966) % 1)), x = cx + Math.cos(a) * rr, y = cy + Math.sin(a) * rr;
    let da = (sweep - ((a % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2)); da = ((da % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2);
    const glow = Math.max(0.25, 1 - da / (Math.PI * 1.2)), c = BCOL[n.type] || [140, 160, 180], sz = 2 + Math.min(4, (n.deg || 0) * 0.6 + (n.w || 1) * 0.5);
    g.save(); g.shadowColor = `rgba(${c},${glow})`; g.shadowBlur = 8 * glow; g.fillStyle = `rgba(${c},${0.35 + 0.65 * glow})`; g.beginPath(); g.arc(x, y, sz, 0, 7); g.fill(); g.restore();
    if (bmouse) { const d = (x - bmouse.x) ** 2 + (y - bmouse.y) ** 2; if (d < hd && d < 200) { hd = d; hov = { n, x, y }; } } }
  if (hov) { g.strokeStyle = "#fff"; g.lineWidth = 1; g.beginPath(); g.arc(hov.x, hov.y, 7, 0, 7); g.stroke(); }
  // 오른쪽 판독 패널
  const px = W * 0.66, total = B.total || 0, kept = B.n || 0, core = B.byType?.["핵심"] || 0;
  g.textAlign = "left"; g.font = "700 12px ui-monospace,monospace"; g.fillStyle = "#7dffb6"; g.fillText("BRAIN FOUNDRY · 자체 뇌", px, 26);
  const lines = [["지능", `${iq.score ?? 0}/100`], ["예측 정확도", `${iq.acc ?? 0}% (${iq.n ?? 0}판)`], ["기억(남음 / 만든 수)", `${kept} / ${total}`], ["잊혀짐(정리)", `${Math.max(0, total - kept)}`], ["연결(링크)", `${brainG?.edges?.length || 0}`], ["핵심 규칙", `${core} of ${kept} through the gate`], ["손절 함정 회피", `${B.traps ?? 0}`]];
  lines.forEach(([k, v], i) => { const y = 50 + i * 20; g.font = "10px ui-monospace,monospace"; g.fillStyle = "#5f7a6c"; g.fillText(k, px, y); g.font = "700 11px ui-monospace,monospace"; g.fillStyle = "#cfeedd"; g.fillText(v, px + 130, y); });
  // 파이프라인
  const steps = ["관찰", "학습", "연결", "정리", "회상", "정제"], y0 = 50 + lines.length * 20 + 10;
  g.font = "600 10px ui-monospace,monospace"; steps.forEach((s, i) => { const on = Math.floor(performance.now() / 700) % steps.length === i; g.fillStyle = on ? "#7dffb6" : "#3d5a4a"; g.fillText((i ? "→ " : "") + s, px + i * 46, y0); });
  // 최근 / 호버 기억
  const showN = hov?.n || nodes[0]; if (showN) { g.font = "10px ui-monospace,monospace"; g.fillStyle = "#5f7a6c"; g.fillText(hov ? "가리킨 기억" : "가장 강한 기억", px, y0 + 22); g.fillStyle = "#e6f5ec"; g.font = "11px ui-monospace,monospace";
    const txt = String(showN.text || ""), maxW = W - px - 14; let line = "", yy = y0 + 38; for (const ch of txt) { if (g.measureText(line + ch).width > maxW) { g.fillText(line, px, yy); line = ""; yy += 14; if (yy > H - 10) break; } line += ch; } if (yy <= H - 10) g.fillText(line, px, yy);
    g.fillStyle = `rgba(${BCOL[showN.type] || [150, 150, 150]},.9)`; g.font = "9px ui-monospace,monospace"; g.fillText(`${showN.type} · 가중 ${(+showN.w || 0).toFixed(1)} · 연결 ${showN.deg || 0}`, px, Math.min(H - 6, yy + 16)); }
  if (!nodes.length) { g.fillStyle = "#5a6374"; g.font = "11px ui-monospace,monospace"; g.textAlign = "center"; g.fillText("뇌가 비어있음 — 모델들이 복기·거래하며 기억이 쌓입니다", cx, cy); }
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
  <div class="nd-card nd-shell"><div class="nd-h">NEURAL SHELL <small>입력 카드 → SHARED SURFACE(주문 대기열 게이트) → 매매법 → AI 워커 → 출력 · 실데이터</small></div><div class="vz-shell" data-vzshell></div></div>
  <div class="nd-card nd-rtcard"><div class="nd-h">⚡ 실시간 진입 <small>손매매용 · 시장가 기준 · 에이전트 팀 ↔ 뉴럴 데스크 토론 · 주문은 직접</small><span class="rt-coins" data-rtcoins></span><button class="nd-mini" data-rtgo title="지금 모든 코인을 다시 분석하고 토론합니다">전체 분석</button></div><div class="nd-rt" data-rt></div></div>
  <div class="nd-card nd-trd"><div class="nd-h">AI 모델 트레이더 리더보드 <small>(직접 거래·복기·학습 · PnL 순)</small></div><div class="nd-neurons" data-neurons></div></div>
  <div class="nd-card nd-trades"><div class="nd-h">최근 데모 거래 · 매매법 설계</div><div class="nd-tr" data-trades></div></div>
  <div class="nd-card nd-brain"><div class="nd-h">🧠 자체 뇌 FOUNDRY <small data-braininfo></small><button class="nd-mini" data-canvas title="JSON Canvas로 내보내기 — Obsidian에서 열 수 있어요">.canvas ↓</button></div><div class="vb" data-vzbrain></div></div>
</div>`;

function inject() {
  if (document.getElementById("nd-css")) return;
  const st = document.createElement("style"); st.id = "nd-css";
  st.textContent = VZ.SHELL_CSS + VZ.BRAIN_CSS + `
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
.nd-grid{flex:1;display:grid;grid-template-columns:1.05fr 1fr;grid-template-rows:minmax(250px,auto) minmax(860px,auto) minmax(540px,auto) 500px minmax(900px,auto);gap:12px;padding:12px;min-height:0;overflow-y:auto;position:relative;z-index:1}
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
.nd-shell{grid-column:1/3;grid-row:2/3;background:#04070d !important;border-color:rgba(127,211,255,.25) !important;box-shadow:0 0 30px -12px rgba(127,211,255,.35) inset}.nd-rtcard{grid-column:1/3;grid-row:3/4}.nd-trd{grid-column:2/3;grid-row:4/5}
.nd-trades{grid-column:1/2;grid-row:4/5}.nd-brain{grid-column:1/3;grid-row:5/6}
.rt-coins{display:flex;gap:4px;margin-left:auto}.rt-coins+.nd-mini{margin-left:6px}.rt-mk{border-color:rgba(247,181,0,.5)!important;color:#ffcf6a!important}
.nd-rt{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:10px}
.rtc{border:1px solid var(--line2);border-radius:10px;padding:10px 12px;background:rgba(12,18,30,.7)}.rtc.g3{border-color:rgba(38,208,124,.55);box-shadow:0 0 0 1px rgba(38,208,124,.25) inset}.rtc.g2{border-color:rgba(124,159,255,.4)}
.rtc .rh{display:flex;align-items:center;gap:8px;font-size:13px}.rtc .rh b{font-size:14px}.rtc .gb{font-size:10px;padding:1px 7px;border-radius:4px;font-weight:700}.gb.g3{background:#13402a;color:#4ff0a0}.gb.g2{background:#1d2a4d;color:#9db6ff}.gb.g1{background:#3a2f12;color:#ffcf6a}.gb.g0{background:#20262f;color:#8a93a6}
.rtc .px{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin:8px 0}.rtc .px div{background:rgba(20,28,42,.7);border-radius:6px;padding:5px 7px}.rtc .px small{display:block;color:var(--dim);font-size:9px}.rtc .px b{font-size:12px}
.rtc .kv{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:11px;color:#9aa4b6}.rtc .kv b{color:#dbe2ef}
.rtc .chips{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}.rtc .chips span{font-size:10px;padding:1px 6px;border-radius:4px;background:rgba(38,208,124,.12);color:#8fe6b8}.rtc .chips span.w{background:rgba(255,77,100,.12);color:#ff9aa8}
.rtc .db{margin-top:6px;font-size:11px;color:#aab3c3;border-top:1px dashed var(--line2);padding-top:5px}.rtc .db b.up{color:var(--up)}.rtc .db b.dn{color:var(--dn)}
.rtc .cp{float:right;font-size:10px;cursor:pointer;color:var(--accent);background:none;border:1px solid var(--line2);border-radius:4px;padding:0 6px}
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
