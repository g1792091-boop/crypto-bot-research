// 🧠 뉴럴 데스크 대시보드 — 연결된 AI 모델/피처 뉴런이 직접 데모 매매·학습하는 모습을 풀스크린으로.
// 디자인: 다크 터미널 + NEURAL SHELL(피처 → 결정 코어 → 확률 셸) 애니메이션. 전부 가상자금.
let root = null, raf = 0, loop = 0, N = null, ST = null;
const E = (s) => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const money = (v) => (v >= 0 ? "+" : "−") + "$" + Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 });
const ago = (t) => { const s = (Date.now() - t) / 1000 | 0; return s < 60 ? s + "s" : (s / 60 | 0) + "m"; };

export async function openNeural(ctx = {}) {
  N = await import("./neural.js");
  close();
  root = document.createElement("div"); root.id = "ndesk"; root.innerHTML = SHELL; document.body.appendChild(root);
  inject();
  root.querySelector("[data-x]").onclick = close;
  root.querySelector("[data-reset]").onclick = () => { if (confirm("뉴럴 데스크의 가상 성적·학습 가중치를 모두 초기화할까요?")) { N.reset(); render(); } };
  ST = N.state();
  render();
  let k = 0;
  const tick = async () => {
    try { ST = await N.step(); } catch (e) {}      // 자체 신호(뉴런) — 무료·빠름, 항상 돈다
    render();
    N.modelStep().then(render).catch(() => {});      // 연결 AI 모델이 코인 직접 판단(회전·fallback) — 한도 쿨다운 방지 위해 틱당 1명
    if (++k % 14 === 0) N.reflect().catch(() => {});  // 복기 → 교훈 학습(집단 뇌)
    if (k % 26 === 13) N.designStrategy().then(render).catch(() => {});  // 모델이 지표 조합→매매법 설계→백테스트→사무실 인계
  };
  tick(); loop = setInterval(tick, 6000);
  raf = requestAnimationFrame(draw);
  window.addEventListener("keydown", esc);
}
function close() { if (loop) clearInterval(loop); if (raf) cancelAnimationFrame(raf); loop = raf = 0; window.removeEventListener("keydown", esc); if (root) root.remove(); root = null; }
const esc = (e) => { if (e.key === "Escape") close(); };

function render() {
  if (!root || !ST) return;
  const s = ST, up = s.pnl >= 0;
  root.querySelector("[data-pnl]").innerHTML = `<b class="${up ? "up" : "dn"}">${money(s.pnl)}</b>`;
  root.querySelector("[data-kpi]").innerHTML =
    `<span>체결 <b>${s.fills}</b></span><span>승률 <b class="${s.winRate >= 50 ? "up" : "dn"}">${s.winRate}%</b></span><span>AI 모델 <b>${s.nModels}</b></span><span>매매법 설계 <b>${s.nDesigns}</b><small>(사무실 인계 ${s.handed})</small></span><span>에폭 <b>${s.epoch}</b></span><span>가동 <b>${ago(s.since)}</b></span>`;
  // 트레이더 리더보드 = 연결된 AI 모델 각각 + 자체 신호. PnL 순. (교훈 = 복기로 배운 수 · 보유 = 현재 포지션)
  root.querySelector("[data-neurons]").innerHTML =
    s.traders.map((tr, i) => { const u = tr.pnl >= 0;
      return `<div class="nrow trd"><span class="rk">${i + 1}</span><span class="nk" title="${E(tr.full || tr.name)}">${tr.prov === "self" ? "🧠 " : ""}${E(tr.name)}</span><b class="${u ? "up" : "dn"}">${money(tr.pnl)}</b><small>${tr.hit == null ? "–" : tr.hit + "%"}${tr.lessons ? ` ·교훈${tr.lessons}` : ""}${tr.pos && tr.pos.length ? ` ·보유${tr.pos.length}` : ""}</small></div>`;
    }).join("") +
    (s.nModels === 0 ? `<div class="nsub dim">연결된 AI 모델이 없습니다 — 설정 → AI 연결에 무료 NVIDIA 키를 넣으면 모델들이 직접 거래·복기합니다 (지금은 자체 신호만)</div>` : "") +
    `<div class="nsub">피처 뉴런 가중치 (학습으로 변함)</div>` +
    s.neurons.map(nu => `<div class="nrow"><span class="nk">${E(nu.name)}</span><span class="nbar"><i style="width:${Math.round(nu.w / 3 * 100)}%"></i></span><b>${nu.w.toFixed(2)}</b><small>${nu.hit == null ? "–" : nu.hit + "%"}</small></div>`).join("") +
    (s.brain ? `<div class="nsub">🧠 자체 뇌 · 누적 기억 ${s.brain.n}개 <span class="dim">${Object.entries(s.brain.byType || {}).map(([t, c]) => t + " " + c).join(" · ") || "비어있음"}</span></div>` +
      (s.brain.top.length ? s.brain.top.slice(0, 7).map(m => `<div class="brow"><span class="bt ${m.type === "패턴" ? "up" : m.type === "교훈" ? "warn" : m.type === "전략" ? "pur" : "dim"}">${E(m.type)}</span><span class="btx" title="${E(m.text)}${m.model ? " · " + E(m.model) : ""}">${E(m.text)}</span><small>×${m.w}</small></div>`).join("")
        : `<div class="dim" style="padding:4px 0">아직 비어있음 — 모델들이 복기·거래하며 기억을 쌓습니다</div>`) : "");
  // 코인별 결정
  root.querySelector("[data-markets]").innerHTML = N.COINS.map(([ko, sym]) => {
    const d = s.dec[sym], p = s.pos.find(x => x.ko === ko);
    const dir = d ? (d.dir > 0 ? "▲" : d.dir < 0 ? "▼" : "·") : "·", col = d ? (d.dir > 0 ? "up" : d.dir < 0 ? "dn" : "dim") : "dim";
    return `<div class="mrow"><b>${ko}</b><span class="${col}">${dir} ${d ? d.conf + "%" : "–"}</span>${p ? `<em class="${p.roe >= 0 ? "up" : "dn"}">${p.side > 0 ? "롱" : "숏"} ${p.roe >= 0 ? "+" : ""}${p.roe}%</em>` : `<em class="dim">무포</em>`}</div>`;
  }).join("");
  // 모델이 설계한 매매법·커스텀 지표 (백테스트 → 사무실 인계)
  const des = (s.designs || []).map(d => `<div class="trow des"><span class="dim">${ago(d.t)}</span><b style="color:#b79cff">${E(d.model)}</b><span>매매법</span><b class="${d.ret >= 0 ? "up" : "dn"}">${d.ret}%</b><span>${E(d.name)} <em class="${d.handed ? "up" : d.pass ? "" : "dim"}">${d.handed ? "→ 사무실 인계" : d.pass ? "통과" : "불통과"}</em></span></div>`).join("");
  // 거래
  root.querySelector("[data-trades]").innerHTML = des + (s.trades.length ? s.trades.map(t =>
    `<div class="trow"><span class="dim">${ago(t.t)}</span><b>${t.ko}</b><span>${t.side > 0 ? "롱" : "숏"}</span><b class="${t.roe >= 0 ? "up" : "dn"}">${t.roe >= 0 ? "+" : ""}${t.roe}%</b><span class="dim">${E(t.why)}</span></div>`
  ).join("") : (des ? "" : `<div class="dim" style="padding:10px">아직 거래 없음 — 신호가 쌓이면 자동 진입합니다</div>`));
  // 라이브 피드 티커
  root.querySelector("[data-feed]").innerHTML = s.feed.map(f => `<span>▸ ${E(f.text)}</span>`).join(" ");
}

// ── NEURAL SHELL 캔버스 애니메이션 ──
let parts = null, t = 0;
function draw() {
  raf = requestAnimationFrame(draw);
  const cv = root && root.querySelector("canvas"); if (!cv || !ST) return;
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

function shortMd(m) { return String(m).split("/").pop().replace(/-instruct|-chat/i, "").slice(0, 18); }

const SHELL = `
<div class="nd-top"><b>🧠 GH COIN // NEURAL DESK</b><span class="nd-tag">AI 모델·피처 뉴런이 직접 데모매매·학습 · 가상자금</span>
  <marquee class="nd-feed" data-feed scrollamount="5"></marquee><span class="nd-clock"></span>
  <button class="nd-btn" data-reset>초기화</button><button class="nd-btn nd-x" data-x>✕</button></div>
<div class="nd-grid">
  <div class="nd-card nd-pnl"><div class="nd-h">ALL-TIME PnL <small>(데모)</small></div><div class="nd-big" data-pnl></div><div class="nd-kpi" data-kpi></div></div>
  <div class="nd-card"><div class="nd-h">코인별 결정 · 포지션</div><div class="nd-markets" data-markets></div></div>
  <div class="nd-card nd-shell"><div class="nd-h">NEURAL SHELL · 피처 → 결정 코어 → 확률 셸</div><canvas></canvas></div>
  <div class="nd-card"><div class="nd-h">AI 모델 트레이더 리더보드 <small>(각 모델이 직접 거래·복기·학습 · PnL 순)</small></div><div class="nd-neurons" data-neurons></div></div>
  <div class="nd-card nd-trades"><div class="nd-h">최근 데모 거래 · 청산 시 학습 반영</div><div class="nd-tr" data-trades></div></div>
</div>`;

function inject() {
  if (document.getElementById("nd-css")) return;
  const st = document.createElement("style"); st.id = "nd-css";
  st.textContent = `
#ndesk{position:fixed;inset:0;z-index:99999;background:#080b11;color:#c9d1e0;font:12px ui-monospace,Menlo,Consolas,monospace;display:flex;flex-direction:column;overflow:hidden}
#ndesk .up{color:#2ec27e}#ndesk .dn{color:#f2364b}#ndesk .dim{color:#5a6374}
.nd-top{display:flex;align-items:center;gap:12px;padding:8px 14px;background:#0c1018;border-bottom:1px solid #1a2130;flex:0 0 auto}
.nd-top>b{color:#e6ebf5;letter-spacing:1px}.nd-tag{color:#5a6374;font-size:11px}
.nd-feed{flex:1;color:#8a93a6}.nd-feed span{margin-right:26px}.nd-clock{color:#788;font-size:11px}
.nd-btn{background:#141a26;border:1px solid #28303f;color:#9aa4b6;padding:4px 10px;border-radius:5px;cursor:pointer}
.nd-btn:hover{background:#1c2434}.nd-x{color:#f2364b}
.nd-grid{flex:1;display:grid;grid-template-columns:1.1fr 1fr;grid-template-rows:auto 1fr auto;gap:10px;padding:10px;min-height:0}
.nd-card{background:#0c1119;border:1px solid #1a2130;border-radius:8px;padding:10px 12px;min-height:0;overflow:auto;display:flex;flex-direction:column}
.nd-h{color:#6b7488;font-size:10px;letter-spacing:1px;text-transform:uppercase;margin-bottom:8px;flex:0 0 auto}.nd-h small{color:#454c5c}
.nd-pnl .nd-big b{font-size:40px;font-weight:700;line-height:1}
.nd-kpi{display:flex;gap:16px;margin-top:10px;color:#788;font-size:11px}.nd-kpi b{color:#c9d1e0}
.nd-shell{grid-column:1 / 2;grid-row:2 / 3}.nd-shell canvas{flex:1;width:100%;height:100%;min-height:0}
.nd-grid>.nd-card:nth-child(4){grid-column:2 / 3;grid-row:2 / 3}
.nd-trades{grid-column:1 / 3;grid-row:3 / 4;max-height:170px}
.nd-markets{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}
.mrow{background:#0f1521;border:1px solid #1a2130;border-radius:6px;padding:6px 8px;display:flex;flex-direction:column;gap:2px}
.mrow>b{color:#e6ebf5}.mrow em{font-style:normal;font-size:11px}
.nrow{display:grid;grid-template-columns:90px 1fr 42px 54px;align-items:center;gap:8px;margin:3px 0}
.nk{color:#aeb6c6;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.nbar{height:7px;background:#141a26;border-radius:4px;overflow:hidden}.nbar i{display:block;height:100%;background:#4d82ff}
.nrow>b{text-align:right;color:#e6ebf5}.nrow small{color:#5a6374;text-align:right}.nrow small em{font-style:normal;color:#3d4454;margin-left:4px}
.trd{grid-template-columns:18px 1fr 78px auto}.rk{color:#5a6374;text-align:center}.trd .nk{color:#dbe2ef}.trd small{white-space:nowrap}
#ndesk .warn{color:#e0a53e}#ndesk .pur{color:#b79cff}
.brow{display:grid;grid-template-columns:46px 1fr 34px;gap:8px;align-items:center;margin:3px 0;font-size:11px}
.bt{font-size:9px;padding:1px 5px;border-radius:4px;background:#141a26;text-align:center}
.btx{color:#aeb6c6;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.brow small{color:#5a6374;text-align:right}
.nsub{color:#6b7488;font-size:10px;margin:8px 0 4px;letter-spacing:1px}
.nd-tr{display:flex;flex-direction:column;gap:2px}
.trow{display:grid;grid-template-columns:40px 42px 36px 64px 1fr;gap:8px;align-items:center;padding:3px 4px;border-bottom:1px solid #121824}
.trow>b:first-of-type{color:#e6ebf5}
@media(max-width:760px){.nd-grid{grid-template-columns:1fr;grid-template-rows:auto auto 260px auto auto}.nd-shell,.nd-trades,.nd-grid>.nd-card:nth-child(4){grid-column:1}.nd-shell{grid-row:auto}}`;
  document.head.appendChild(st);
  // 시계
  const clk = root.querySelector(".nd-clock"); const upd = () => { if (clk) clk.textContent = new Date().toUTCString().slice(17, 25) + " UTC"; };
  upd(); setInterval(upd, 1000);
}
