// 뉴럴 데스크 시각화 2종 — 사용자가 보낸 레퍼런스(atsmatrix 릴 2개)의 화면 구성을 그대로 따라 실제 데이터로 그린다.
//  ① NEURAL SHELL = "GRAPH REPO-RUN" : 밝은 종이 + 파일 카드 열 + 가운데 검은 SHARED SURFACE 버스(노란 틱) + 수백 개 흔들리는 머리카락 선 + RUN LOG / DISPATCH / GRAPH STATS
//  ② 뇌 = "DE NOVO BINDER FOUNDRY" : 어두운 실험실 + 단계 탭·타일 + 가운데 회전 3D 이중 나선 + 기억 분자 클러스터 + 산점도 / 공정 라인 / 플레이트 판독 + 하단 티커
const E = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const ago = t => { const s = Math.max(0, (Date.now() - t) / 1000 | 0); return s < 60 ? s + "s" : s < 3600 ? (s / 60 | 0) + "m" : (s / 3600 | 0) + "h"; };
const fx = v => v == null || !Number.isFinite(+v) ? "—" : Math.abs(v) >= 1000 ? Math.round(v).toLocaleString() : Math.abs(v) >= 1 ? (+v).toFixed(3) : (+v).toFixed(3);
const HC = { pink: "#f06a8a", red: "#e8505b", blue: "#4f7df5", teal: "#22b8b0", purple: "#9b6cf0", green: "#2fb36d", orange: "#f39c28", gray: "#8a93a3" };
const PILL = ["#f06a8a", "#2fb36d", "#9b6cf0", "#4f7df5", "#f39c28", "#22b8b0"];
let frameN = 0, t0 = performance.now();
// 성능: 화면 밖이면 그리지 않고(0.5초마다 확인), 초당 30장으로 제한
function due(el, ms = 33) { const now = performance.now();
  if (el._visAt == null || now - el._visAt > 500) { el._visAt = now; const r = el.getBoundingClientRect(); el._vis = r.bottom > 0 && r.top < (window.innerHeight || 900) && r.width > 0; }
  if (!el._vis || now - (el._ft || 0) < ms) return false; el._ft = now; return true; }
// 구슬 스프라이트: 프레임마다 그라디언트를 새로 만들지 않고 한 번 그려 둔 그림을 찍는다
const SPR = new Map();
function sprite(c0, c1, c2) { const k = c0 + c1 + (c2 || ""); let cv = SPR.get(k); if (cv) return cv;
  cv = document.createElement("canvas"); cv.width = cv.height = 48; const g = cv.getContext("2d"), gr = g.createRadialGradient(24 - 7, 24 - 7, 1, 24, 24, 23);
  gr.addColorStop(0, c0); if (c2) { gr.addColorStop(0.35, c1); gr.addColorStop(1, c2); } else gr.addColorStop(1, c1); g.fillStyle = gr; g.beginPath(); g.arc(24, 24, 23, 0, 7); g.fill(); SPR.set(k, cv); return cv; }

/* ══════════════════════ ① NEURAL SHELL ══════════════════════ */
export const SHELL_CSS = `
.vz-shell{position:relative;background:#f1f2ef;background-image:radial-gradient(rgba(0,0,0,.09) 1px,transparent 1.2px);background-size:14px 14px;color:#1d2128;border-radius:8px;padding:10px 12px 8px;font:11px/1.35 "JetBrains Mono",ui-monospace,Menlo,Consolas,monospace;display:flex;flex-direction:column;gap:10px}
.vz-top{display:flex;gap:16px;flex-wrap:wrap;font-size:11px;color:#59606b;border-bottom:1px solid #d7d9d3;padding-bottom:6px;letter-spacing:.3px}.vz-top b{color:#111;font-weight:800}
.vz-stage{position:relative;flex:0 0 auto;min-height:520px;display:grid;grid-template-columns:150px 30px 160px 160px 160px;justify-content:space-between;gap:0 10px;align-items:start;padding:4px 0 10px}
.vz-wires{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;overflow:visible}
.vz-col{position:relative;display:flex;flex-direction:column;gap:16px;z-index:1}.vz-col.c0{padding-left:2px}.vz-col.c1{padding-top:8px;gap:26px}.vz-col.c2{padding-top:60px;gap:22px}.vz-col.c3{padding-top:30px;gap:30px}
.vz-card{background:#fff;border:1.5px solid #1d2128;border-radius:3px;box-shadow:2px 2px 0 rgba(0,0,0,.12);font-size:10px;min-width:0;width:100%}
.vz-ch{display:flex;justify-content:space-between;align-items:center;padding:3px 6px;color:#fff;font-weight:800;font-size:11px;border-bottom:1.5px solid #1d2128;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.vz-ch i{width:7px;height:7px;border-radius:50%;background:#fff;flex:0 0 auto;margin-left:6px}
.vz-cb{padding:4px 6px 5px;display:flex;flex-direction:column;gap:3px}
.vz-pill{display:flex;align-items:center;gap:6px}.vz-pill s{display:block;height:6px;border-radius:3px;text-decoration:none}.vz-pill span{color:#59606b}
.vz-ck{display:flex;align-items:center;gap:5px;color:#3c424c}.vz-ck b{width:9px;height:9px;border:1.5px solid #1d2128;border-radius:1px;display:inline-block}.vz-ck b.on{background:#1d2128}
.vz-kv{display:flex;justify-content:space-between;color:#59606b}.vz-kv b{color:#111;font-weight:700}
.vz-bus{position:relative;align-self:stretch;background:#111;border-radius:2px;display:flex;align-items:center;justify-content:center;z-index:2;min-height:480px;box-shadow:0 0 0 2px #f1f2ef,0 0 0 3.5px #111}
.vz-bus span{writing-mode:vertical-rl;transform:rotate(180deg);color:#fff;font-weight:800;letter-spacing:5px;font-size:11px}.vz-bus.open span{color:#7dffb6}
.vz-tick{position:absolute;left:5px;right:5px;height:22px;background:#f6c20a;border:1.5px solid #fff;transition:top 1.2s ease}
.vz-panels{display:grid;grid-template-columns:1.25fr 1fr 1fr;gap:12px}
.vz-p{background:#fff;border:1.5px solid #1d2128;border-radius:4px;padding:7px 9px;box-shadow:2px 2px 0 rgba(0,0,0,.1);min-width:0}
.vz-ph{display:flex;justify-content:space-between;align-items:center;font-weight:800;font-size:11px;margin-bottom:6px;letter-spacing:.4px}.vz-ph em{font-style:normal;font-size:9.5px;padding:1px 7px;border-radius:9px;color:#fff;background:#e8505b}.vz-ph em.blk{background:#1d2128}.vz-ph em.bl{background:#4f7df5}
.vz-log div{display:grid;grid-template-columns:38px 1fr 1fr 44px 34px;gap:6px;align-items:center;font-size:10px;padding:1.5px 0;color:#3c424c;white-space:nowrap}.vz-log div>*{overflow:hidden;text-overflow:ellipsis}
.vz-st{font-size:9px;padding:0 5px;border-radius:7px;color:#fff;text-align:center;font-weight:700}.vz-st.ok{background:#2fb36d}.vz-st.run{background:#4f7df5}.vz-st.go{background:#f39c28}.vz-st.park{background:#f6c20a;color:#111}.vz-st.idle{background:#c9ccd2;color:#333}.vz-st.err{background:#e8505b}
.vz-dsp div.r{display:grid;grid-template-columns:26px 1fr 34px 36px;gap:6px;align-items:center;font-size:10px;padding:2px 0}
.vz-bar{height:7px;background:#e4e6ea;border-radius:2px;overflow:hidden}.vz-bar i{display:block;height:100%;background:repeating-linear-gradient(90deg,#4f7df5 0 6px,#6f95ff 6px 8px)}
.vz-sts div.r{display:flex;justify-content:space-between;font-size:10.5px;padding:1.5px 0;color:#3c424c}.vz-sts b{color:#111}
.vz-cost{display:flex;gap:2px;margin:4px 0}.vz-cost i{flex:1;height:9px;background:#1d2128}.vz-cost i.off{background:#e4e6ea}
.vz-foot{font-size:10px;color:#6b717c;letter-spacing:.6px}
`;
function card(id, color, name, pills, checks, kvs) {
  return `<div class="vz-card" data-vz="${E(id)}"><div class="vz-ch" style="background:${color}">${E(name)}<i></i></div><div class="vz-cb">`
    + pills.map(([lab, f, c]) => `<div class="vz-pill"><s style="width:${Math.round(14 + Math.max(0, Math.min(1, f)) * 46)}px;background:${c}"></s><span>${E(lab)}</span></div>`).join("")
    + checks.map(([lab, on]) => `<div class="vz-ck"><b class="${on ? "on" : ""}"></b>${E(lab)}</div>`).join("")
    + kvs.map(([k, v]) => `<div class="vz-kv"><span>${E(k)}</span><b>${E(v)}</b></div>`).join("") + `</div></div>`;
}
const opOf = txt => /익절/.test(txt) ? ["close.tp", "ok"] : /손절|청산\(/.test(txt) ? ["close.sl", "err"] : /진입|▲롱|▼숏/.test(txt) ? ["entry.open", "go"] : /시장 읽기/.test(txt) ? ["scan.read", "ok"] : /거절/.test(txt) ? ["gate.reject", "park"] : /승인|수급/.test(txt) ? ["approve.flow", "run"]
  : /차단|보류|취소/.test(txt) ? ["gate.block", "park"] : /백테스트|보정/.test(txt) ? ["calib.run", "run"] : /진화|설계/.test(txt) ? ["evolve.split", "ok"] : /뇌|학습|기억/.test(txt) ? ["brain.link", "ok"] : /뉴스|웹/.test(txt) ? ["news.parse", "ok"] : ["emit.event", "ok"];
export function renderShell(el, s, N) {
  if (!el || !s) return;
  if (!el._init) { el._init = 1; el.innerHTML = `<div class="vz-top"></div><div class="vz-stage"><svg class="vz-wires"></svg><div class="vz-col c0"></div><div class="vz-bus"><span>SHARED SURFACE LOCKED</span><i class="vz-tick"></i></div><div class="vz-col c1"></div><div class="vz-col c2"></div><div class="vz-col c3"></div></div><div class="vz-panels"><div class="vz-p vz-log"></div><div class="vz-p vz-dsp"></div><div class="vz-p vz-sts"></div></div><div class="vz-foot"></div>`; }
  const coins = N.COINS, reg = s.regime || {}, dec = s.dec || {}, eng = s.engine || [], models = (s.traders || []).filter(x => x.prov !== "self");
  const allPos = [...(s.pos || []), ...(s.traders || []).filter(x => Array.isArray(x.pos)).flatMap(x => x.pos)];
  const gateOpen = (s.riskMode || "정상") === "정상" && (s.heat ?? 0) < 4 && !(s.news?.blockUntil > Date.now());
  // 열 0: 입력(코인 피드 3 + 내 지표 + 수급 + 뉴스)
  const c0 = [];
  for (const [ko, sym] of coins.slice(0, 3)) { const r = reg[sym] || {}, f = s.feat?.[sym] || {};
    c0.push(card("c:" + sym, [HC.pink, HC.red, HC.blue][c0.length % 3], `${ko.toLowerCase()}_feed.ts`, [[r.key || "regime", (r.adx || 0) / 50, PILL[c0.length]]], [["locked", allPos.some(p => p.sym === sym)]], [["adx", fx(r.adx ?? 0)]])); }
  const ind = s.chartDesk?.now?.["15"] || [];
  c0.push(card("i:chart", HC.teal, "chart_inds.json", ind.slice(0, 3).map((x, k) => [x.name.slice(0, 10), x.dir > 0 ? 1 : x.dir < 0 ? 0.15 : 0.5, x.dir > 0 ? "#2fb36d" : x.dir < 0 ? "#e8505b" : "#c9ccd2"]), [], [["inds", String(ind.length)]]));
  const wl = (s.whale?.last || []).length, tr = s.whale?.trust || {};
  c0.push(card("w:flow", HC.blue, "whale_flow.ts", [["copy", Math.min(1, wl / 4), "#9b6cf0"]], [["trust_ok", (tr.n || 0) < 20 || tr.acc >= 0.45]], [["signals", String(wl)]]));
  c0.push(card("n:news", HC.orange, "news_hook.json", [["sentiment", ((s.news?.score ?? 0) + 3) / 6, "#f39c28"]], [["blocked", s.news?.blockUntil > Date.now()]], [["score", String(s.news?.score ?? 0)]]));
  // 열 1: 매매법(실전 통과 우선)
  const strat = [...eng].sort((a, b) => (b.active - a.active) || (b.mean - a.mean)).slice(0, 5);
  const c1 = strat.map((e, k) => card("s:" + e.vkey, e.active ? HC.green : HC.gray, `${String(e.vkey).replace(/@/, ".").slice(0, 20)}.rule`, [["score", Math.max(0, Math.min(1, (e.mean + 0.2) / 0.9)), e.active ? "#2fb36d" : "#c9ccd2"]], [["gate", e.active]], [["mean", (e.mean >= 0 ? "+" : "") + e.mean + "R"]]));
  // 열 2: AI 워커
  const maxAct = Math.max(1, ...models.map(m => (m.scans || 0) + (m.approved || 0) + (m.rejected || 0)));
  const c2 = models.slice(0, 5).map((m, k) => card("m:" + m.name, [HC.purple, HC.blue, HC.teal, HC.purple, HC.blue][k], `${m.name}.ai`, [["scan", ((m.scans || 0) + (m.approved || 0)) / maxAct, "#4f7df5"]], [["busy", s.scan?.model === m.name]], [["reads", String(m.scans || 0)]]));
  // 열 3: 출력(포지션·실시간 진입·뇌·리스크)
  const c3 = allPos.slice(0, 3).map(p => card("p:" + p.sym, p.roe >= 0 ? HC.green : HC.red, `${p.ko.toLowerCase()}_${p.side > 0 ? "long" : "short"}.pos`, [["roe", Math.max(0, Math.min(1, ((p.roe || 0) + 50) / 100)), p.roe >= 0 ? "#2fb36d" : "#e8505b"]], [["breakeven", p.be]], [["roe", (p.roe >= 0 ? "+" : "") + (+p.roe || 0).toFixed(1) + "%"]]));
  let le = null; try { le = JSON.parse(localStorage.getItem("coinLiveEntry") || "null"); } catch (e) {}
  const g3 = (le?.list || []).filter(x => x.best?.grade === "유력").length, g2 = (le?.list || []).filter(x => x.best?.grade === "보통").length;
  c3.push(card("o:live", HC.orange, "live_entry.json", [["strong", g3 / 6, "#f39c28"]], [["fresh", le && Date.now() - le.t < 10 * 60e3]], [["fair", String(g2)]]));
  c3.push(card("o:brain", HC.purple, "brain.md", [["iq", (s.brain?.iq?.score || 0) / 100, "#9b6cf0"]], [["learning", true]], [["memories", String(s.brain?.n || 0)]]));
  c3.push(card("o:risk", gateOpen ? HC.teal : HC.red, "risk.gate", [["heat", (s.heat || 0) / 4, gateOpen ? "#22b8b0" : "#e8505b"]], [["open", gateOpen]], [["today", `${s.dayN ?? 0}/${s.cfg?.dailyMax ?? 12}`]]));
  const set = (sel, html) => { const n = el.querySelector(sel); if (n && n._h !== html) { n.innerHTML = html; n._h = html; } };
  set(".c0", c0.join("")); set(".c1", c1.join("")); set(".c2", c2.join("")); set(".c3", c3.join(""));
  const bus = el.querySelector(".vz-bus"); bus.classList.toggle("open", gateOpen); bus.querySelector("span").textContent = gateOpen ? "SHARED SURFACE OPEN" : "SHARED SURFACE LOCKED";
  el._q = s.queue || 0; el._live = { scan: s.scan?.model ? "m:" + s.scan.model : null, scanCoin: s.scan?.sym ? "c:" + s.scan.sym : null };
  // 패널
  const feed = (s.feed || []).slice(0, 15);
  set(".vz-log", `<div class="vz-ph">RUN LOG <em>LIVE</em></div>` + feed.map(f => { const [op, st] = opOf(f.text), tg = (f.text.match(/\b(BTC|ETH|SOL|XRP|DOGE|BNB)\b/) || [])[1] || (f.text.match(/\[([^\]]+)\]/) || [])[1] || "neural";
    return `<div><span>${ago(f.t)}</span><span>${op}</span><span title="${E(f.text)}">${E(tg)}</span><span>${(String(f.text).length * 7) % 900 + 60}ms</span><span class="vz-st ${st}">${st === "err" ? "fail" : st}</span></div>`; }).join(""));
  set(".vz-dsp", `<div class="vz-ph">DISPATCH <em class="blk">${models.length} WORKERS</em></div>` + models.slice(0, 7).map((m, k) => { const a = (m.scans || 0) + (m.approved || 0) + (m.rejected || 0), pct = Math.round(a / maxAct * 100), st = s.scan?.model === m.name ? "run" : m.idle ? "idle" : a ? "park" : "idle";
    return `<div class="r"><span>w${k + 1}</span><div class="vz-bar" title="${E(m.name)}"><i style="width:${pct}%"></i></div><span>${pct}%</span><span class="vz-st ${st}">${st}</span></div>`; }).join("")
    + `<div class="vz-kv" style="margin-top:5px"><span>parallel ${Math.min(5, models.length)}</span><span>queued ${s.queue || 0}</span><span>steps ${s.epoch || 0}</span></div>`);
  const trades = s.trades || [], strikes = trades.filter(t => t.R < 0).length, eq = []; let c = 0; for (const t of [...trades].reverse()) { c += t.pnl || 0; eq.push(c); }
  const cost = Math.min(100, Math.round((s.heat || 0) / 4 * 100));
  const W = 150, H = 26, mn = Math.min(0, ...eq), mx = Math.max(0.01, ...eq), sp = eq.length > 1 ? eq.map((v, i) => `${(i / (eq.length - 1) * W).toFixed(1)},${(H - (v - mn) / (mx - mn || 1) * H).toFixed(1)}`).join(" ") : `0,${H} ${W},${H}`;
  set(".vz-sts", `<div class="vz-ph">GRAPH STATS <em class="bl">v${(s.epoch || 0) % 9}.${(s.fills || 0) % 10}.${models.length}</em></div>`
    + [["edges", el._edges || 0], ["bus readers", models.length], ["imports", (N.NEURONS?.length || 0) + ind.length], ["runs", s.fills || 0], ["locked", gateOpen ? 0 : 1], ["strikes", strikes]].map(([k, v]) => `<div class="r"><span>${k}</span><b>${v}</b></div>`).join("")
    + `<div class="r"><span>relative cost</span><b>${cost}%</b></div><div class="vz-cost">${Array.from({ length: 24 }, (_, i) => `<i class="${i < cost / 100 * 24 ? "" : "off"}"></i>`).join("")}</div><svg width="100%" height="${H}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><polyline points="${sp}" fill="none" stroke="#4f7df5" stroke-width="1.2"/></svg>`);
  set(".vz-top", `<span>GRAPH <b>NEURAL-RUN-${s.epoch || 0}</b></span><span>FILES <b>${c0.length + c1.length + c2.length + c3.length}</b></span><span>EDGES <b>${el._edges || 0}</b></span><span>BUS READERS <b>${models.length}</b></span><span>DEPTH <b>4</b></span><span>T <b data-vzt></b></span><span>FRAME <b data-vzf></b></span><span style="margin-left:auto">${gateOpen ? "게이트 초록 — 공유 면(주문 대기열)에 쓸 수 있음" : "게이트 잠김 — 조건 통과 전엔 진입이 써지지 않음"}</span>`);
  set(".vz-foot", `SHARED SURFACE · ${c0.length + c1.length + c2.length + c3.length} FILES · ${gateOpen ? "LIVE CURRENT" : "LOCKED"} · 카드 = 실제 입력·매매법·AI 워커·출력 · 선 = 데이터 흐름`);
}
// 머리카락 선: 카드 앵커 사이를 베지어로 잇고, 매 프레임 조금씩 흔들림. 지금 일하는 흐름은 색으로 강조.
export function frameShell(el) {
  if (!el?._init || !due(el)) return;
  frameN++; const T = (performance.now() - t0) / 1000;
  const tt = el.querySelector("[data-vzt]"), ff = el.querySelector("[data-vzf]"); if (tt) tt.textContent = `${String(Math.floor(T / 60) % 60).padStart(2, "0")}.${String(Math.floor(T) % 60).padStart(2, "0")}`; if (ff) ff.textContent = frameN;
  const stage = el.querySelector(".vz-stage"), svg = el.querySelector(".vz-wires"), bus = el.querySelector(".vz-bus"); if (!stage || !svg || !bus) return;
  // 카드 위치는 0.6초마다만 다시 잰다(매 프레임 측정은 레이아웃 계산을 강제해 느림)
  let lay = el._lay; if (!lay || performance.now() - lay.t > 600) { const r0 = stage.getBoundingClientRect(); if (!r0.width) return;
    const bx = n => { const r = n.getBoundingClientRect(); return { l: r.left - r0.left, r: r.right - r0.left, t: r.top - r0.top, b: r.bottom - r0.top, y: (r.top + r.bottom) / 2 - r0.top }; };
    lay = el._lay = { t: performance.now(), R0: { width: r0.width, height: r0.height }, cols: [0, 1, 2, 3].map(i => [...el.querySelectorAll(`.c${i} .vz-card`)].map(n => ({ id: n.dataset.vz, ...bx(n) }))), B: bx(bus) }; }
  const { R0, cols, B } = lay, tick = bus.querySelector(".vz-tick"); if (tick) tick.style.top = `${10 + Math.min(1, (el._q || 0) / 3) * (B.b - B.t - 50) + (el._q ? Math.sin(T * 2) * 6 : 0)}px`;
  if (!el._wires || el._wires.sig !== cols.map(c => c.length).join(",")) {
    const W = [], rnd = (a, b) => a + Math.random() * (b - a);
    for (const c of cols[0]) for (let k = 0; k < 16; k++) W.push({ a: c.id, side: "r", b: "bus", ya: rnd(0.2, 0.8), yb: rnd(0.02, 0.98), ph: rnd(0, 7), k: rnd(0.3, 0.7) });
    for (let k = 0; k < 70; k++) W.push({ a: "left", b: "bus", ya: rnd(0, 1), yb: rnd(0, 1), ph: rnd(0, 7), k: rnd(0.2, 0.8) });   // 왼쪽 가장자리에서 들어오는 배경 선(레퍼런스의 촘촘한 팬)
    for (const c of cols[1]) for (let k = 0; k < 9; k++) W.push({ a: "bus", b: c.id, ya: rnd(0.02, 0.98), yb: rnd(0.25, 0.75), ph: rnd(0, 7), k: rnd(0.3, 0.7) });
    for (const a of cols[1]) for (const b of cols[2]) if (Math.random() < 0.6) for (let k = 0; k < 2; k++) W.push({ a: a.id, side: "r", b: b.id, ya: rnd(0.3, 0.7), yb: rnd(0.3, 0.7), ph: rnd(0, 7), k: 0.5 });
    for (const a of cols[2]) for (const b of cols[3]) if (Math.random() < 0.55) for (let k = 0; k < 2; k++) W.push({ a: a.id, side: "r", b: b.id, ya: rnd(0.3, 0.7), yb: rnd(0.3, 0.7), ph: rnd(0, 7), k: 0.5 });
    for (const a of cols[1]) for (const b of cols[3]) if (Math.random() < 0.3) W.push({ a: a.id, side: "r", b: b.id, ya: rnd(0.3, 0.7), yb: rnd(0.3, 0.7), ph: rnd(0, 7), k: 0.5 });
    el._wires = { sig: cols.map(c => c.length).join(","), W }; el._edges = W.length;
    svg.innerHTML = W.map(() => `<path fill="none"/>`).join("");
  }
  const byId = {}; for (const c of cols.flat()) byId[c.id] = c;
  const paths = svg.children, live = el._live || {};
  el._wires.W.forEach((w, i) => {
    let x1, y1, x2, y2;
    if (w.a === "left") { x1 = -10; y1 = w.ya * (R0.height - 40); } else if (w.a === "bus") { x1 = B.r; y1 = B.t + w.ya * (B.b - B.t); } else { const a = byId[w.a]; if (!a) return; x1 = a.r; y1 = a.t + w.ya * (a.b - a.t); }
    if (w.b === "bus") { x2 = B.l; y2 = B.t + w.yb * (B.b - B.t); } else { const b = byId[w.b]; if (!b) return; x2 = b.l; y2 = b.t + w.yb * (b.b - b.t); }
    const sw = Math.sin(T * 0.9 + w.ph) * 10, dx = (x2 - x1) * w.k;
    const p = paths[i]; if (!p) return;
    p.setAttribute("d", `M${x1.toFixed(1)},${y1.toFixed(1)} C${(x1 + dx).toFixed(1)},${(y1 + sw).toFixed(1)} ${(x2 - dx).toFixed(1)},${(y2 - sw).toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)}`);
    const hot = (live.scan && (w.b === live.scan || w.a === live.scan)) || (live.scanCoin && w.a === live.scanCoin);
    if (w.hot !== !!hot) { w.hot = !!hot; p.setAttribute("stroke", hot ? "#4f7df5" : "rgba(20,22,28,.42)"); p.setAttribute("stroke-width", hot ? "1.3" : w.a === "left" ? "0.45" : "0.6"); }
  });
}

/* ══════════════════════ ② BRAIN FOUNDRY ══════════════════════ */
export const BRAIN_CSS = `
.vb{position:relative;background:#03070d;color:#cfd6e2;border-radius:8px;font:11px/1.35 "JetBrains Mono",ui-monospace,Menlo,Consolas,monospace;display:flex;flex-direction:column;min-height:820px;overflow:hidden;border:1px solid #1a2433}
.vb-head{display:grid;grid-template-columns:auto 1fr auto;gap:18px;align-items:start;padding:10px 14px 6px;border-bottom:1px solid #1a2433}
.vb-head .k{color:#ff8a3d;font-size:10px;letter-spacing:1px}.vb-head h3{margin:2px 0 0;font-size:22px;letter-spacing:2px;color:#f2f4f8;font-weight:800}.vb-head .s{color:#6d7a8f;font-size:10px;margin-top:3px}
.vb-tabs{display:flex;gap:18px;font-size:10.5px;letter-spacing:1.2px;color:#55627a;padding-top:6px}.vb-tabs b{display:block;color:#7d8aa0;font-weight:600}.vb-tabs .on{color:#ff8a3d}.vb-tabs .on b{color:#ffb070}.vb-tabs small{display:block;color:#56637a;font-size:9px;margin-top:2px}
.vb-t{text-align:right}.vb-t b{font-size:26px;color:#f2f4f8;font-weight:800}.vb-t small{display:block;color:#6d7a8f;font-size:9.5px}
.vb-tiles{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;padding:8px 14px}
.vb-tile{border:1px solid #1f2b3d;border-radius:4px;padding:6px 8px;background:#060c15}.vb-tile.on{border-color:#ff8a3d;background:#1a0f06}.vb-tile b{display:block;font-size:10px;letter-spacing:1px;color:#9aa6ba}.vb-tile.on b{color:#ffb070}.vb-tile small{color:#56637a;font-size:9px}.vb-tile i{display:block;font-style:normal;font-size:18px;color:#ffb070;font-weight:800;margin-top:2px}
.vb-stage{position:relative;flex:1;min-height:440px;margin:0 14px;border:1px solid #1a2433;border-radius:4px;background:radial-gradient(ellipse at 50% 45%,#0d1a2c 0%,#03070d 70%)}
.vb-stage canvas{position:absolute;inset:0;width:100%;height:100%}
.vb-ov{position:absolute;font-size:10px;letter-spacing:1px;color:#8d9ab0}.vb-ov.tl{left:10px;top:8px}.vb-ov.tr{right:10px;top:8px;color:#ff5a5a}.vb-ov.bl{left:10px;bottom:8px;color:#56637a}
.vb-panels{display:grid;grid-template-columns:1fr 1.25fr 1fr;gap:10px;padding:10px 14px}
.vb-rl{display:flex;flex-direction:column;gap:3px;max-height:250px;overflow:auto}.vb-rl div{display:grid;grid-template-columns:44px 1fr 34px;gap:6px;font-size:10px;color:#b8c2d3;align-items:start;padding:2px 0;border-bottom:1px dashed #141c28}
.vb-rl em{font-style:normal;font-size:9px;padding:0 4px;border-radius:3px;text-align:center;color:#0b0f16;font-weight:700}.vb-rl em.c{background:#ff5a6a}.vb-rl em.t{background:#f6c20a}.vb-rl em.l{background:#ff9a3c}.vb-rl b{color:#6d7a8f;font-weight:400;text-align:right;font-size:9px}
.vb-rl .x{color:#56637a;font-size:9.5px;padding:3px 0}
.vb-call div{display:grid;grid-template-columns:34px 24px 1fr 84px;gap:6px;font-size:10px;color:#b8c2d3;padding:2px 0;align-items:center}.vb-call span:last-child{text-align:right;white-space:nowrap}.vb-call .w{color:#3fd18a}.vb-call .l{color:#ff5a6a}.vb-call .o{color:#56637a}
.vb-sum{display:flex;gap:12px;font-size:10px;color:#8d9ab0;margin:2px 0 6px}.vb-sum b{color:#e6ebf3;font-size:13px}
.vb-p{border:1px solid #1f2b3d;border-radius:4px;padding:8px 10px;background:#060c15;min-width:0}.vb-ph{display:flex;justify-content:space-between;font-size:10.5px;letter-spacing:1px;color:#e6ebf3;font-weight:700;margin-bottom:6px}.vb-ph em{font-style:normal;color:#ff5a5a;font-size:9.5px}
.vb-line div.r{display:grid;grid-template-columns:72px 1fr 64px;gap:8px;align-items:center;font-size:10px;padding:2px 0;color:#9aa6ba}.vb-line s{display:block;height:6px;background:#1a2433;border-radius:3px;overflow:hidden;text-decoration:none}.vb-line s i{display:block;height:100%;background:linear-gradient(90deg,#ff8a3d,#ffb070)}
.vb-plate{display:grid;grid-template-columns:repeat(16,10px);gap:5px;margin:6px 0;justify-content:start}.vb-plate i{width:10px;height:10px;border-radius:50%;background:#141c28}.vb-plate i.a{background:#ff9a3c;box-shadow:0 0 6px #ff9a3c}.vb-plate i.s{background:#f6c20a}.vb-plate i.d{background:#8a1f2b}.vb-plate i.r{background:#9b6cf0}
.vb-leg{display:flex;flex-wrap:wrap;gap:4px 10px;font-size:9.5px;color:#6d7a8f}.vb-leg span{white-space:nowrap}.vb-leg i{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:3px;vertical-align:middle}
.vb-tick{border-top:1px solid #1a2433;padding:6px 14px;font-size:10.5px;color:#8d9ab0;white-space:nowrap;overflow:hidden}.vb-tick span{display:inline-block;animation:vbt 60s linear infinite;padding-left:100%}@keyframes vbt{to{transform:translateX(-100%)}}
.vb-tick b{color:#ff8a3d;font-weight:700}
`;
const BT = { "교훈": "#ff9a3c", "패턴": "#3fd18a", "전략": "#a98bff", "핵심": "#ff5a6a", "관찰": "#5aa0ff", "매매법": "#46d6ff", "지식": "#ffd166" };
const STAGES = [["SCAN", "관찰", "스캔·뉴스·내 지표"], ["DESIGN", "학습", "패턴 + 교훈"], ["SYNTH", "연결", "기억 사이 링크"], ["DOSE", "망각", "안 쓰여 정리됨"], ["READ", "채점", "결과로 맞춤 확인"], ["RECUT", "승격", "핵심 규칙"]];
export function renderBrain(el, s, G) {
  if (!el || !s) return;
  if (!el._init) { el._init = 1; el.innerHTML = `<div class="vb-head"></div><div class="vb-tiles"></div><div class="vb-stage"><canvas></canvas><div class="vb-ov tl">TARGET STRUCTURE · LIVE<br><span style="color:#56637a">기억 나선 · 유형별 분자 클러스터</span></div><div class="vb-ov tr">● ROTATING</div><div class="vb-ov bl">마우스를 올리면 기억 내용</div></div><div class="vb-panels"><div class="vb-p vb-line"></div><div class="vb-p vb-rules"></div><div class="vb-p vb-pl"></div></div><div class="vb-tick"></div>`;
    const cv = el.querySelector("canvas"); cv.onmousemove = e => { const r = cv.getBoundingClientRect(); el._m = { x: e.clientX - r.left, y: e.clientY - r.top }; }; cv.onmouseleave = () => { el._m = null; }; }
  const B = s.brain || {}, iq = B.iq || {}, st = B.st || {}, bt = B.byType || {}, nodes = G?.nodes || [], links = G?.edges?.length || 0, core = bt["핵심"] || 0, total = B.total || 0, kept = B.n || 0;
  const vals = [bt["관찰"] || 0, (bt["패턴"] || 0) + (bt["교훈"] || 0), links, st.forgot || 0, iq.n || 0, core];
  const stage = Math.floor(Date.now() / 4000) % 6; el._G = G; el._B = B;
  const set = (sel, html) => { const n = el.querySelector(sel); if (n && n._h !== html) { n.innerHTML = html; n._h = html; } };
  set(".vb-head", `<div><div class="k">RUN ${String(s.epoch || 0).padStart(2, "0")} · NEUTRON MEMORY PROGRAM</div><h3>자체 뇌 FOUNDRY</h3><div class="s">IQ ${iq.score ?? 0}/100 · 정확도 ${iq.acc ?? 0}% · 채점 ${iq.n ?? 0}판 · 함정 ${B.traps ?? 0}개 · 진입 차단 ${st.avoided || 0} · 리스크 절반 ${st.softened || 0}</div></div>
    <div class="vb-tabs">${STAGES.map(([en, ko], i) => `<div class="${i === stage ? "on" : ""}"><b>${en}</b>${ko}<small>${vals[i]}</small></div>`).join("")}</div>
    <div class="vb-t"><small>T+</small><b>${String(Math.min(99, iq.acc ?? 0)).padStart(2, "0")}.${String(iq.score ?? 0).padStart(2, "0")}</b><small>ARM CYCLE ${Math.round(((Date.now() / 1000) % 60) / 60 * 100)}%</small></div>`);
  set(".vb-tiles", STAGES.map(([en, ko, sub], i) => `<div class="vb-tile ${i === stage ? "on" : ""}"><b>${en} · ${ko}</b><small>${sub}</small><i>${String(vals[i]).padStart(3, "0")}</i></div>`).join(""));
  // ① 학습 라인: 지금 남아 있는 수 + (누적) — 무엇이 실제로 돌아가는지
  const steps = [["관찰 수집", bt["관찰"] || 0, ""], ["결과 채점", iq.n || 0, ""], ["패턴", bt["패턴"] || 0, ""], ["교훈", bt["교훈"] || 0, st.lessons], ["함정 기록", B.traps || 0, st.traps], ["규칙 승격", core, st.promoted], ["함정 회피", (st.avoided || 0) + (st.softened || 0), null], ["망각 정리", st.forgot || 0, null]];
  const mx = Math.max(1, ...steps.map(x => x[1]));
  set(".vb-line", `<div class="vb-ph">학습 라인 <em style="color:#6d7a8f">walking down the loop</em></div>` + steps.map(([k, v, cum]) => `<div class="r"><span>${k}</span><s><i style="width:${Math.round(v / mx * 100)}%"></i></s><b style="color:#e6ebf3">${v}${cum != null && cum !== "" && cum > v ? `<small style="color:#56637a"> /누적 ${cum}</small>` : ""}</b></div>`).join("")
    + `<div class="vb-leg" style="margin-top:6px"><span>방향 정확도 ${iq.acc ?? 0}%</span><span>채점 ${iq.n ?? 0}판</span><span style="margin-left:auto">brier ${iq.brier ?? "—"}</span></div>
    <div style="margin-top:4px;color:#56637a;font-size:9.5px">교훈 = 손절·과신·검증 탈락 · 함정 = 손절난 자리 모양 · 승격 = 같은 결과 3회↑</div>`);
  // ② 뇌가 지금 진입에 쓰는 것: 핵심 규칙(리스크 절반/근거) · 손절 함정(닮으면 차단) · 최근 교훈
  const dk = d => d > 0 ? "롱" : "숏", rows = [
    ...(B.rules || []).slice(0, 5).map(m => `<div><em class="c">핵심</em><span>${E(m.text)}</span><b>${m.hits || 1}회</b></div>`),
    ...(B.trapList || []).slice(0, 4).map(t => `<div><em class="t">함정</em><span>${E(t.coin || "")} ${E(t.regime || "일반")} ${dk(t.dir)} · ${E(t.keys)} · 손절 ${t.roe}%</span><b>${t.hits}회</b></div>`),
    ...(B.lessons || []).slice(0, 5).map(m => `<div><em class="l">교훈</em><span>${E(m.text)}</span><b>${ago(m.t || Date.now())}</b></div>`)];
  set(".vb-rules", `<div class="vb-ph">뇌가 지금 쓰는 규칙 · 함정 · 교훈 <em style="color:#6d7a8f">진입 전 자동 점검</em></div><div class="vb-rl">${rows.join("") || `<div class="x">아직 없음 — 손절·과신 스캔·검증 탈락·추천 손절이 생기면 교훈과 함정이 쌓이고, 같은 결과가 3번 나오면 핵심 규칙으로 승격됩니다.</div>`}</div>
    <div class="vb-leg" style="margin-top:6px"><span><i style="background:#ff5a6a"></i>핵심 = 손절 쪽이면 리스크 절반</span><span><i style="background:#f6c20a"></i>함정 60%↑ 닮으면 진입 차단</span></div>`);
  // ③ 내 손매매 추천 채점(⚡ 시장가 · 실시간 진입) + 데모 거래 판독
  const C = s.calls || {}, cl = C.list || [];
  const callRows = cl.slice(0, 6).map(c => `<div><span>${E(c.ko)}</span><span>${c.side > 0 ? "롱" : "숏"}</span><span style="color:#6d7a8f">${E(c.src)}${c.grade ? "·" + E(c.grade) : ""} · ${ago(c.t)}</span><span class="${c.res === "익절1" ? "w" : c.res === "손절" ? "l" : "o"}">${c.res ? c.res + " " + (c.R >= 0 ? "+" : "") + c.R + "R" : "추적 중"}</span></div>`).join("");
  const tr = (s.trades || []).slice(0, 32), open = [...(s.pos || []), ...(s.traders || []).filter(x => Array.isArray(x.pos)).flatMap(x => x.pos)];
  const cells = [...open.map(() => "r"), ...tr.map(t => t.R >= 0.5 ? "a" : t.R <= -0.5 ? "d" : "s")].slice(0, 32); while (cells.length < 32) cells.push("");
  set(".vb-pl", `<div class="vb-ph">⚡ 내 손매매 추천 채점 <em>● LIVE</em></div>
    <div class="vb-sum"><span>익절1 먼저 <b>${C.wr == null ? "—" : C.wr + "%"}</b></span><span>채점 <b>${C.done || 0}</b></span><span>합계 <b style="color:${(C.sumR || 0) >= 0 ? "#3fd18a" : "#ff5a6a"}">${(C.sumR || 0) >= 0 ? "+" : ""}${C.sumR || 0}R</b></span><span>추적 중 <b>${C.open || 0}</b></span></div>
    ${Object.keys(C.byGrade || {}).length ? `<div class="vb-leg" style="margin-bottom:5px">${Object.entries(C.byGrade).map(([g, x]) => `<span>${E(g)} <b style="color:#e6ebf3">${Math.round(x.w / x.n * 100)}%</b> (${x.n}건 · ${x.R >= 0 ? "+" : ""}${x.R}R)</span>`).join("")}</div>` : ""}
    <div class="vb-call">${callRows || `<div style="grid-template-columns:1fr;color:#56637a">⚡ 시장가 버튼을 누르거나 실시간 진입이 '유력·보통'을 내면 여기서 손절/익절1 중 먼저 닿은 쪽으로 채점 → 뇌가 학습</div>`}</div>
    <div class="vb-ph" style="margin-top:8px">데모 거래 판독 <em style="color:#6d7a8f">최근 32</em></div><div class="vb-plate">${cells.map(c => `<i class="${c}"></i>`).join("")}</div>
    <div class="vb-leg"><span><i style="background:#ff9a3c"></i>익절</span><span><i style="background:#f6c20a"></i>소폭</span><span><i style="background:#8a1f2b"></i>손절</span><span><i style="background:#9b6cf0"></i>보유</span></div>`);
  const ev = (s.feed || []).filter(f => /뇌|학습|기억|교훈|패턴|설계|진화|익절|손절|채점|함정/.test(f.text)).slice(0, 8).map(f => `${new Date(f.t).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })} · ${f.text.slice(0, 60)}`);
  set(".vb-tick", `<span>${ev.map(x => E(x)).join(" &nbsp;<b>›</b>&nbsp; ")} &nbsp;<b>·</b>&nbsp; 목표는 사람이 정했다. 나머지는 루프가 한다. — A HUMAN SET THE GOAL. THE LOOP DID EVERYTHING ELSE.</span>`);
}
// 3D 이중 나선 + 기억 분자 클러스터 (깊이 정렬)
export function frameBrain(el) {
  const cv = el?.querySelector?.(".vb-stage canvas"); if (!cv || !due(el)) return;
  const dpr = Math.min(2, window.devicePixelRatio || 1), W = cv.clientWidth, H = cv.clientHeight; if (W < 50 || H < 50) return;
  if (cv.width !== W * dpr || cv.height !== H * dpr) { cv.width = W * dpr; cv.height = H * dpr; }
  const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
  const T = (performance.now() - t0) / 1000, rot = T * 0.45, cx = W / 2, top = 26, bot = H - 26, R = Math.min(W * 0.11, 90), nodes = el._G?.nodes || [];
  const M = 120, items = [], fov = 520;
  const proj = (x, y, z) => { const s = fov / (fov - z); return { X: cx + x * s, Y: (top + bot) / 2 + (y - (top + bot) / 2) * s, s, z }; };
  // 나선 가닥(구슬) + 가로대
  const sorted = [...nodes].sort((a, b) => (a.t || 0) - (b.t || 0));
  for (let k = 0; k < M; k++) {
    const y = top + (bot - top) * (k / (M - 1)), a = k * 0.16 + rot;
    for (const [st, off] of [[0, 0], [1, Math.PI]]) { const x = Math.cos(a + off) * R, z = Math.sin(a + off) * R; const p = proj(x, y, z);
      items.push({ z, draw: () => { const r = (6.5 + 3 * (z / R + 1) / 2) * p.s;
        const c = st ? (k % 3 ? ["#ffe7d6", "#c9b1a8"] : ["#ff6b4a", "#8a1f1f"]) : ["#ffd27a", "#d96a12"]; g.globalAlpha = 0.55 + 0.45 * (z / R + 1) / 2; g.drawImage(sprite(c[0], c[1]), p.X - r, p.Y - r, r * 2, r * 2); g.globalAlpha = 1; } }); }
    if (k % 5 === 0) { const m = sorted[Math.floor(k / M * sorted.length)], col = m ? BT[m.type] || "#8899aa" : "#334"; const pa = proj(Math.cos(a) * R, y, Math.sin(a) * R), pb = proj(Math.cos(a + Math.PI) * R, y, Math.sin(a + Math.PI) * R);
      items.push({ z: (Math.sin(a) + Math.sin(a + Math.PI)) * R / 2 - 1, draw: () => { g.strokeStyle = col; g.globalAlpha = 0.35; g.lineWidth = 1; g.beginPath(); g.moveTo(pa.X, pa.Y); g.lineTo(pb.X, pb.Y); g.stroke(); g.globalAlpha = 1; } }); }
  }
  // 기억 분자: 강한 기억 상위 16개가 나선 둘레를 함께 돌며 붙어 있음
  const top16 = [...nodes].sort((a, b) => (b.w || 0) - (a.w || 0) || (b.deg || 0) - (a.deg || 0)).slice(0, 16), hovC = [];
  top16.forEach((n, i) => {
    const k = Math.floor((i + 0.5) / top16.length * (M - 2)) + 1, y = top + (bot - top) * (k / (M - 1)), ang = k * 0.16 + rot + (i % 2 ? Math.PI : 0) + 0.5, dist = R * (2.0 + (i % 3) * 0.45);
    const base = { x: Math.cos(ang) * dist, y, z: Math.sin(ang) * dist }, col = BT[n.type] || "#8899aa", nAt = 3 + ((n.deg || 1) % 4);
    const atoms = Array.from({ length: nAt }, (_, j) => ({ x: base.x + Math.cos(j * 2.1 + i) * 16, y: base.y + Math.sin(j * 1.7 + i) * 14, z: base.z + Math.sin(j * 2.9) * 14 }));
    const anchor = proj(Math.cos(ang - 0.5) * R, y, Math.sin(ang - 0.5) * R), pb = proj(base.x, base.y, base.z);
    items.push({ z: base.z - 2, draw: () => { g.strokeStyle = "rgba(255,120,180,.35)"; g.lineWidth = 0.8; g.beginPath(); g.moveTo(anchor.X, anchor.Y); for (let q = 1; q <= 6; q++) { const u = q / 6; g.lineTo(anchor.X + (pb.X - anchor.X) * u + Math.sin(T * 2 + q + i) * 3, anchor.Y + (pb.Y - anchor.Y) * u + Math.cos(T * 2 + q) * 3); } g.stroke(); } });
    atoms.forEach((a, j) => { const p = proj(a.x, a.y, a.z);
      items.push({ z: a.z, draw: () => { const r = (j ? 4.2 : 6.5) * p.s;
        g.globalAlpha = 0.5 + 0.5 * Math.max(0, Math.min(1, (a.z / (R * 2.6) + 1) / 2)); g.drawImage(sprite("#ffffff", col, "rgba(0,0,0,.6)"), p.X - r, p.Y - r, r * 2, r * 2); g.globalAlpha = 1;
        if (j) { const p0 = proj(atoms[0].x, atoms[0].y, atoms[0].z); g.strokeStyle = col; g.globalAlpha = 0.4; g.lineWidth = 0.8; g.beginPath(); g.moveTo(p0.X, p0.Y); g.lineTo(p.X, p.Y); g.stroke(); g.globalAlpha = 1; } } }); });
    hovC.push({ n, p: pb, col });
    items.push({ z: base.z + 0.5, draw: () => { if (base.z < -R) return; g.font = "600 10px ui-monospace,monospace"; g.fillStyle = "#e9eef6"; g.textAlign = "left"; const tx = pb.X + 12, ty = pb.Y - 6;
      g.fillText(String(n.text || "").slice(0, 16), tx, ty); g.font = "9px ui-monospace,monospace"; g.fillStyle = col; g.fillText(`${n.type} · w ${(+n.w || 0).toFixed(1)} · 링크 ${n.deg || 0}`, tx, ty + 11); } });
  });
  items.sort((a, b) => a.z - b.z).forEach(it => it.draw());
  // 왼쪽 대기열 눈금(레퍼런스의 POUR QUEUE)
  g.font = "9px ui-monospace,monospace"; g.textAlign = "left"; g.fillStyle = "#3a475c";
  for (let i = 0; i < 12; i++) { const y = 70 + i * ((H - 110) / 12); g.fillText(i % 3 ? "·" : (i === 0 ? "학습 대기열" : `q${String(i).padStart(2, "0")}`), 10, y); g.fillRect(70, y - 3, 18 + ((i * 37 + Math.floor(T)) % 30), 1); }
  // 호버
  const m = el._m; if (m) { const h = hovC.find(c => Math.hypot(c.p.X - m.x, c.p.Y - m.y) < 26); if (h) { g.fillStyle = "rgba(3,7,13,.92)"; g.strokeStyle = h.col; const tx = String(h.n.text || ""), w = Math.min(W - 20, g.measureText(tx).width + 20);
    const bx = Math.min(W - w - 10, m.x + 12), by = Math.max(10, m.y - 40); g.fillRect(bx, by, w, 34); g.strokeRect(bx, by, w, 34); g.fillStyle = "#e9eef6"; g.font = "11px ui-monospace,monospace"; g.fillText(tx.slice(0, 80), bx + 10, by + 15); g.fillStyle = h.col; g.font = "9px ui-monospace,monospace"; g.fillText(`${h.n.type} · ${h.n.model || ""}`, bx + 10, by + 28); } }
}
