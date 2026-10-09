// 🔬 지표 최적화 백테스트 창 — 코인·기간·시간봉·레버리지·조합을 골라 직접 커스텀 최적값을 뽑고 🧪 조합 연구소에 적용한다.
//   계산은 optlab.js → lib/comboopt.js (앱 기본 5년 값을 만든 tools/combo-opt.mjs 와 같은 함수). 데모용 값 — 실주문 경로 없음.
import * as OL from "./optlab.js";
import * as CB from "./lib/combos.js";

const E = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const day = t => new Date(t).toISOString().slice(0, 10), sg = v => `${v >= 0 ? "+" : ""}${v}`;
const PRESETS = [["3개월", 91], ["6개월", 182], ["1년", 365], ["2년", 730], ["3년", 1096], ["5년", 1826]];
const ALL_LEVS = [20, 30, 40, 50];
let root = null, cur = null, busy = false, onChange = null, calcT0 = 0;
const F = { sym: "BTCUSDT", days: 365, start: Date.now() - 365 * 864e5, end: Date.now(), tfs: ["15", "30", "60"], levs: [30, 40, 50], combos: CB.COMBOS.map(c => c.key) };

export function openOptLab(opts = {}) {
  onChange = opts.onChange || null;
  if (opts.sym) F.sym = OL.normSym(opts.sym);
  closeOptLab(); inject();
  root = document.createElement("div"); root.id = "optlab"; root.innerHTML = shell(); document.body.appendChild(root);
  root.addEventListener("click", onClick); root.addEventListener("change", onInput); root.addEventListener("input", onInput);
  form(); renderRuns(); renderApplied(); if (cur) renderRes();
}
export function closeOptLab() { root?.remove(); root = null; }
const $ = s => root?.querySelector(s);

function shell() {
  return `<div class="ol-box">
  <div class="ol-h"><b>🔬 지표 최적화 백테스트</b><small>슈퍼트렌드+ROC · 슈퍼트렌드+클링거 · VWMA+MACD · 슈퍼트렌드+KST — 원하는 코인·기간으로 직접 돌려 코인별 커스텀 최적값을 뽑고, 🧪 조합 연구소 데모에 적용합니다</small><button class="ol-x" data-olx title="닫기(계산은 계속됨)">✕</button></div>
  <div class="ol-form" data-olform></div>
  <div class="ol-how">고르는 법: 고른 기간을 같은 길이 <b>5구간</b>으로 나눠 <b>앞 4구간으로만 고르고</b>, 마지막 1구간(고를 때 안 본 구간)으로 검증합니다 · 점수 = 구간별 평균R − 0.5×구간 간 편차(꾸준함) · 그리드 이웃 평균(튀는 값 제외) · 레버리지 L 은 손절 ≤ 청산거리 40% = 0.4/L(20배 2% · 30배 1.33% · 40배 1% · 50배 0.8%), 넘으면 진입 안 함 · 수수료·슬리피지 0.08% 포함 · 다음 봉 시가 진입 · 앱 기본 5년 값과 같은 계산</div>
  <div class="ol-res" data-olres></div>
  <div class="ol-runs" data-olruns></div>
</div>`;
}
function chk(name, val, on, label, dis = false) { return `<label class="ol-ck${on ? " on" : ""}${dis ? " dis" : ""}"><input type="checkbox" data-ol${name}="${val}"${on ? " checked" : ""}${dis ? " disabled" : ""}>${label}</label>`; }
function form() {
  const el = $("[data-olform]"); if (!el) return;
  const coinBtns = CB.COINS.map(([ko, sym]) => `<button class="ol-b${F.sym === sym ? " on" : ""}" data-olcoin="${sym}">${ko}</button>`).join("");
  const other = CB.COINS.some(c => c[1] === F.sym) ? "" : F.sym.replace(/USDT$/, "");
  el.innerHTML = `
  <div class="ol-row"><span class="ol-l">코인</span>${coinBtns}<input class="ol-in" data-olsym placeholder="다른 코인(예: ADA, LINK, 1000PEPE)" value="${E(other)}"></div>
  <div class="ol-row"><span class="ol-l">기간</span>${PRESETS.map(([k, d]) => `<button class="ol-b${F.days === d ? " on" : ""}" data-olpre="${d}">${k}</button>`).join("")}
    <input class="ol-in" type="date" data-olfrom value="${day(F.start)}"> ~ <input class="ol-in" type="date" data-olto value="${day(F.end)}"></div>
  <div class="ol-row"><span class="ol-l">시간봉</span>${CB.TFS.map(tf => chk("tf", tf, F.tfs.includes(tf), CB.TF_KO[tf])).join("")}
    <span class="ol-l" style="margin-left:14px">레버리지</span>${ALL_LEVS.map(l => chk("lev", l, F.levs.includes(l), l + "배" + (l === 20 ? "<small>(1시간만)</small>" : ""))).join("")}</div>
  <div class="ol-row"><span class="ol-l">조합</span>${CB.COMBOS.map(c => chk("cb", c.key, F.combos.includes(c.key), c.ko)).join("")}</div>
  <div class="ol-row ol-est" data-olest>${estimate()}</div>
  <div class="ol-row"><button class="ol-go" data-olgo${busy ? " disabled" : ""}>${busy ? "계산 중…" : "▶ 최적화 실행"}</button><button class="ol-b" data-olstop${busy ? "" : " disabled"}>■ 중지</button><span class="ol-pt" data-olprog></span></div>
  <div class="ol-bar"><i data-olbar></i></div>
  <div class="ol-row" data-olapplied></div>`;
}
// 예상: 요청 수(캐시 없을 때) · 계산 시간(이 PC 의 노드 실측: 5년·전부 ≈ 70초를 기준으로 비례)
function estimate() {
  const span = Math.max(0, F.end - F.start), need15 = F.tfs.some(t => t !== "60"), need60 = F.tfs.includes("60");
  const req = (need15 ? OL.reqEstimate(F.start, F.end, "15m") : 0) + (need60 ? OL.reqEstimate(F.start, F.end, "1h") : 0);
  const sims = tf => { const nl = CB.LEVS[tf].filter(l => F.levs.includes(l)).length; return CB.COMBOS.filter(c => F.combos.includes(c.key)).reduce((a, c) => a + CB.gridList(c.grid).length * nl + 180 * nl, 0); };
  const bars = { "15": span / 900e3, "30": span / 1800e3, "60": span / 3600e3 }, full = 1826 * 864e5;
  const unit = tfs => tfs.reduce((a, tf) => a + sims(tf) * bars[tf], 0);
  const ref = (["15", "30", "60"]).reduce((a, tf) => a + (CB.COMBOS.reduce((x, c) => x + CB.gridList(c.grid).length * CB.LEVS[tf].length + 180 * CB.LEVS[tf].length, 0)) * full / { "15": 900e3, "30": 1800e3, "60": 3600e3 }[tf], 0);
  const sec = Math.max(2, Math.round(70 * unit(F.tfs) / ref)), days = Math.round(span / 864e5), lanes = F.tfs.reduce((a, tf) => a + CB.LEVS[tf].filter(l => F.levs.includes(l)).length * F.combos.length, 0);
  return `${E(F.sym.replace(/USDT$/, ""))} · ${days}일(구간 ${Math.round(days / 5)}일 × 5) · 칸 ${lanes}개 · 캔들 요청 최대 ${req}번(받은 구간은 저장돼 다음엔 안 받음, 약 ${Math.ceil(req * 0.45)}초) · 계산 약 ${sec >= 90 ? Math.round(sec / 60) + "분" : sec + "초"}${days < 120 ? " · ⚠ 기간이 짧으면 구간마다 거래가 적어 결과가 흔들립니다" : ""}`;
}
function setRange(days) { F.days = days; F.end = Date.now(); F.start = F.end - days * 864e5; }
function onInput(ev) {
  const t = ev.target;
  if (t.matches("[data-olsym]")) { const v = OL.normSym(t.value); if (v) F.sym = v; else F.sym = "BTCUSDT"; root.querySelectorAll("[data-olcoin]").forEach(b => b.classList.toggle("on", b.dataset.olcoin === F.sym)); }
  else if (t.matches("[data-olfrom]")) { const v = Date.parse(t.value); if (v) { F.start = v; F.days = 0; } }
  else if (t.matches("[data-olto]")) { const v = Date.parse(t.value); if (v) { F.end = Math.min(Date.now(), v + 864e5 - 1); F.days = 0; } }
  else if (t.matches("[data-oltf]")) F.tfs = toggle(F.tfs, t.dataset.oltf, t.checked);
  else if (t.matches("[data-ollev]")) F.levs = toggle(F.levs, +t.dataset.ollev, t.checked).sort((a, b) => a - b);
  else if (t.matches("[data-olcb]")) F.combos = toggle(F.combos, t.dataset.olcb, t.checked);
  else return;
  if (ev.type === "change" && !t.matches("[data-olsym]")) { form(); renderApplied(); } else { const e = $("[data-olest]"); if (e) e.innerHTML = estimate(); }
}
const toggle = (a, v, on) => on ? [...new Set([...a, v])] : a.filter(x => x !== v);

async function onClick(ev) {
  const t = ev.target.closest("button"); if (!t) return;
  if (t.matches("[data-olx]")) return closeOptLab();
  if (t.matches("[data-olcoin]")) { F.sym = t.dataset.olcoin; form(); renderApplied(); return; }
  if (t.matches("[data-olpre]")) { setRange(+t.dataset.olpre); form(); renderApplied(); return; }
  if (t.matches("[data-olgo]")) return go();
  if (t.matches("[data-olstop]")) { OL.stop(); prog({ phase: "stop", f: 0, msg: "중지하는 중…" }); return; }
  if (t.matches("[data-olapply]")) { if (!cur) return; try { const r = OL.apply(cur); flash(`✅ ${cur.ko} 직접 최적화 값을 🧪 연구소에 적용 — 칸 ${r.lanes}개(🔬 표시). 라운드 재채점에도 이 후보들이 쓰입니다.`); onChange?.(); renderApplied(); } catch (e) { flash("❌ " + e.message); } return; }
  if (t.matches("[data-olunapply]")) { OL.unapply(t.dataset.olunapply); flash(`${t.dataset.olunapply.replace(/USDT$/, "")} 직접 최적화 적용 해제`); onChange?.(); renderApplied(); return; }
  if (t.matches("[data-olcsv]")) { if (!cur) return; const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([OL.csv(cur)], { type: "text/csv;charset=utf-8" })); a.download = `GHCoin_지표최적화_${cur.ko}_${day(cur.start)}_${day(cur.end)}.csv`; document.body.appendChild(a); a.click(); a.remove(); return; }
  if (t.matches("[data-oljson]")) { if (!cur) return; try { await navigator.clipboard.writeText(JSON.stringify({ sym: cur.sym, start: day(cur.start), end: day(cur.end), best: cur.best, summary: cur.summary }, null, 1)); t.textContent = "복사됨"; } catch (e) { t.textContent = "복사 실패"; } return; }
  if (t.matches("[data-olopen]")) { const r = await OL.loadRun(t.dataset.olopen); if (r) { cur = r; renderRes(); $("[data-olres]")?.scrollIntoView({ block: "start" }); } else flash("저장된 결과를 못 찾았습니다"); return; }
  if (t.matches("[data-oldel]")) { await OL.deleteRun(t.dataset.oldel); if (cur?.id === t.dataset.oldel) { cur = null; renderRes(); } renderRuns(); return; }
  if (t.matches("[data-olredo]")) { const m = OL.runs().find(x => x.id === t.dataset.olredo); if (m) { Object.assign(F, { sym: m.sym, start: m.start, end: m.end, days: 0, tfs: m.tfs, levs: m.levs, combos: m.combos }); form(); renderApplied(); } return; }
}
function flash(msg) { const e = $("[data-olprog]"); if (e) e.textContent = msg; }
function prog(p) {
  const bar = $("[data-olbar]"), pt = $("[data-olprog]"); if (!bar || !pt) return;
  if (p.phase === "down") { bar.style.width = (p.f * 25).toFixed(1) + "%"; pt.textContent = "📥 " + p.msg; }
  else if (p.phase === "calc") { if (!calcT0 || p.f === 0) calcT0 = Date.now(); const el = (Date.now() - calcT0) / 1000, left = p.f > 0.03 ? Math.round(el / p.f * (1 - p.f)) : null;
    bar.style.width = (25 + p.f * 75).toFixed(1) + "%"; pt.textContent = `🧮 ${Math.round(p.f * 100)}% · ${p.msg}${left != null ? ` · 약 ${left >= 90 ? Math.round(left / 60) + "분" : left + "초"} 남음` : ""}`; }
  else pt.textContent = p.msg;
}
async function go() {
  if (busy) return; busy = true; calcT0 = 0; form();
  try { cur = await OL.run({ ...F }, prog); flash(`✅ 끝 — ${Math.round(cur.ms / 1000)}초 · 아래 결과`); const b = $("[data-olbar]"); if (b) b.style.width = "100%"; renderRes(); renderRuns(); }
  catch (e) { flash("❌ " + (e?.message || e)); }
  finally { busy = false; const g = $("[data-olgo]"), s = $("[data-olstop]"); if (g) { g.disabled = false; g.textContent = "▶ 최적화 실행"; } if (s) s.disabled = true; }
}
function renderApplied() {
  const el = $("[data-olapplied]"); if (!el) return; const L = OL.applied();
  el.innerHTML = L.length ? `<span class="ol-l">적용 중</span>${L.map(u => `<span class="ol-tag${u.off ? " off" : ""}">🔬 ${E(u.ko)} ${day(u.start)}~${day(u.end)}${u.extra ? " (새 코인)" : ""}${u.off ? " · 해제 대기(보유 중)" : ""} <button class="ol-mini" data-olunapply="${u.sym}">해제</button></span>`).join("")}` : `<span class="dim">🧪 연구소는 지금 앱 기본 5년 값으로 돌고 있습니다(직접 최적화 적용 없음)</span>`;
}

// ── 결과 ──
function renderRes() {
  const el = $("[data-olres]"); if (!el) return; const r = cur; if (!r) { el.innerHTML = ""; return; }
  const S = r.summary || [], pass = S.filter(x => x.pass).length, real = S.filter(x => x.pass && !x.luck).length, spanD = Math.round(r.span / 864e5), unit = spanD > 300 ? "년" : "구간";
  const byTL = []; for (const tf of r.tfs) for (const lev of CB.LEVS[tf].filter(l => r.levs.includes(l))) { const a = S.filter(x => x.tf === tf && x.lev === lev); if (!a.length) continue; const n = a.reduce((s, x) => s + x.hoN, 0);
    byTL.push(`${CB.TF_KO[tf]} ${lev}배: 통과 ${a.filter(x => x.pass).length}/${a.length} · 검증 평균 ${n ? sg(+(a.reduce((s, x) => s + x.ho * x.hoN, 0) / n).toFixed(3)) : "–"}R`); }
  const thin = c => c.tr.score <= -9 || c.plat <= -4;   // 학습 거래가 최소 수보다 적었던 칸(점수 없음)
  const yrs = c => c.yr.map((y, i) => `${i + 1}구간${i === 4 ? "(검증)" : ""} ${sg(y[1])}R(${y[0]}건)`).join(" · ");
  const tip = (c, cb, tf, lev) => `${r.ko} ${CB.TF_KO[tf]} ${lev}배 · ${CB.COMBO_BY[cb].ko}\n${CB.paramText(cb, c.p)}\n${CB.exitText(c.x)} · 손절 상한 ${(40 / lev).toFixed(2)}%\n학습(앞 4구간) ${sg(c.tr.mean)}R ${c.tr.n}건 · 검증(마지막 구간, 고를 때 안 봄) ${sg(c.ho.mean)}R ${c.ho.n}건 승률 ${c.ho.wr}%\n${yrs(c)}\n${c.luck ? "운 보정: 운 범위(시험한 경우의 수에 비해 우위가 작음)" : "운 보정 통과"}`;
  const bestRows = r.levs.filter(l => r.best?.[l]).map(lev => { const b = r.best[lev], c = r.out[b.tf][b.c].levs[lev][0];
    return `<tr class="${c.pass ? "ok" : "no"}" title="${E(tip(c, b.c, b.tf, lev))}"><th>${lev}배<br><small class="dim">손절 ≤${(40 / lev).toFixed(2)}%</small></th><td><b>${c.pass ? "✓" : "✗"} ${E(CB.COMBO_BY[b.c].ko)}</b> · ${CB.TF_KO[b.tf]}<br><small>${E(CB.paramText(b.c, c.p))}</small></td><td><small>${E(CB.exitText(c.x))}</small></td>
      <td>${thin(c) ? `<b class="warn">거래 부족</b> ` : ""}학습 ${sg(c.tr.mean)}R <small class="dim">(${c.tr.n})</small><br>검증 <b class="${c.ho.mean > 0 ? "up" : "dn"}">${sg(c.ho.mean)}R</b> <small class="dim">(${c.ho.n}건 · 승률 ${c.ho.wr}%)</small></td><td><small>${c.yr.map((y, i) => `<span class="${y[1] > 0 ? "up" : y[1] < 0 ? "dn" : "dim"}">${sg(y[1])}</span>`).join(" / ")}</small><br><small class="dim">${b.luck ? "운 범위" : "운 보정 통과"} · ${b.of}칸 중 학습 1위</small></td></tr>`; }).join("");
  const pairs = []; for (const tf of r.tfs) for (const lev of CB.LEVS[tf].filter(l => r.levs.includes(l))) pairs.push([tf, lev]);
  const CS = CB.COMBOS.filter(c => r.combos.includes(c.key));
  const grid = pairs.map(([tf, lev]) => `<tr><th>${CB.TF_KO[tf]} ${lev}배</th>${CS.map(C => { const c = r.out[tf]?.[C.key]?.levs?.[lev]?.[0]; if (!c) return `<td class="dim">–</td>`;
    const star = r.best?.[lev]?.c === C.key && r.best[lev].tf === tf;
    if (thin(c)) return `<td class="no dim" title="${E(tip(c, C.key, tf, lev))}">거래 부족(학습 ${c.tr.n}건) — 기간을 늘리세요</td>`;
    return `<td class="${c.pass ? "ok" : "no"}" title="${E(tip(c, C.key, tf, lev))}">${star ? "⭐" : ""}${c.pass ? "✓" : "✗"} <small>${E(CB.paramText(C.key, c.p))}</small><br><small class="dim">${E(CB.exitText(c.x))}</small><br>검증 <b class="${c.ho.mean > 0 ? "up" : "dn"}">${sg(c.ho.mean)}R</b><small class="dim">(${c.ho.n})</small> · 학습 ${sg(c.tr.mean)}R<small class="dim">(${c.tr.n})</small></td>`; }).join("")}</tr>`).join("");
  const applied = OL.applied().some(u => u.sym === r.sym && u.id === r.id);
  el.innerHTML = `<div class="ol-sec"><b>결과 — ${E(r.ko)} · ${day(r.start)} ~ ${day(r.end)}</b> <span class="dim">(${Math.round((r.end - r.start) / 864e5)}일 · 구간 ${spanD}일 × 5 · 캔들 ${Object.entries(r.bars || {}).map(([k, v]) => `${CB.TF_KO[k]} ${v.toLocaleString()}개`).join(" · ")} · 계산 ${Math.round(r.ms / 1000)}초 · ${day(Date.parse(r.made))} 실행)</span>${r.note ? `<br><span class="warn">⚠ ${E(r.note)}</span>` : ""}</div>
  <div class="ol-sum">칸 ${S.length}개 · <b class="up">통과 ${pass}</b>(학습 > 0 · 검증 구간 > 0, 10건↑) · 운 보정까지 통과 ${real}<br><small class="dim">${byTL.join(" · ")}</small></div>
  <div class="ol-act"><button class="ol-go" data-olapply>${applied ? "✅ 연구소에 적용됨(다시 적용)" : "🧪 이 값을 연구소에 적용"}</button><button class="ol-b" data-olcsv>CSV 내려받기</button><button class="ol-b" data-oljson>요약 JSON 복사</button>
    <small class="dim">적용하면 이 코인의 연구소 칸이 이 값(칸마다 후보 9개)으로 바뀌고, 라운드 재채점도 이 후보들로 합니다${CB.COINS.some(c => c[1] === r.sym) ? "" : " · 6코인 밖 코인이라 연구소에 새 칸이 생깁니다"}.</small></div>
  <div class="ol-sub">⭐ 레버리지별 대표 — (조합 × 시간봉) 중 앞 4구간 학습 점수 1위 · 검증 구간은 고를 때 안 봄</div>
  <div class="ol-tw"><table class="ol-t"><tr><th>배율</th><th>조합 · 커스텀 지표 값</th><th>손절·익절·청산</th><th>학습 → 검증</th><th>1~5${unit}(5 = 검증)</th></tr>${bestRows || `<tr><td colspan="5" class="dim">대표 없음</td></tr>`}</table></div>
  <div class="ol-sub">전체 칸 — 칸마다 1위 값(마우스를 올리면 구간별 성적)</div>
  <div class="ol-tw"><table class="ol-t"><tr><th></th>${CS.map(C => `<th>${E(C.ko)}</th>`).join("")}</tr>${grid}</table></div>`;
}
function renderRuns() {
  const el = $("[data-olruns]"); if (!el) return; const L = OL.runs();
  el.innerHTML = L.length ? `<div class="ol-sub">최근 실행 (${L.length}) — 결과는 이 PC 에 저장</div>${L.map(m => `<div class="ol-run"><span class="dim">${day(Date.parse(m.made))}</span><b>${E(m.ko)}</b><span>${day(m.start)}~${day(m.end)}</span><span class="dim">${m.tfs.map(t => CB.TF_KO[t]).join("·")} · ${m.levs.join("/")}배</span><span>통과 ${m.pass}/${m.n}</span><span class="dim">${Math.round((m.ms || 0) / 1000)}초</span><button class="ol-mini" data-olopen="${m.id}">열기</button><button class="ol-mini" data-olredo="${m.id}" title="같은 조건을 위 입력칸에">조건 불러오기</button><button class="ol-mini" data-oldel="${m.id}">삭제</button></div>`).join("")}` : "";
}

function inject() {
  if (document.getElementById("ol-css")) return;
  const st = document.createElement("style"); st.id = "ol-css";
  st.textContent = `
#optlab{position:fixed;inset:0;z-index:100003;background:rgba(2,5,10,.72);display:flex;align-items:flex-start;justify-content:center;padding:28px 12px;overflow:auto;font:12px/1.5 "SF Mono",ui-monospace,Menlo,Consolas,monospace;color:#d4dcea}
#optlab .ol-box{width:min(1240px,100%);background:linear-gradient(180deg,#0e1421,#090d16);border:1px solid #1f2c40;border-radius:14px;padding:14px 16px;box-shadow:0 30px 80px -30px #000}
#optlab .ol-h{display:flex;gap:12px;align-items:baseline;flex-wrap:wrap;border-bottom:1px solid #1f2c40;padding-bottom:8px;margin-bottom:10px}#optlab .ol-h b{font-size:15px;color:#eef3fb}#optlab .ol-h small{color:#7b8799;flex:1;min-width:240px}
#optlab .ol-x{background:none;border:1px solid #2a3a52;color:#d4dcea;border-radius:8px;padding:2px 10px;cursor:pointer;font:inherit}
#optlab .ol-row{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:6px 0}#optlab .ol-l{color:#7b8799;min-width:52px}
#optlab .ol-b,#optlab .ol-mini{background:#0b1320;border:1px solid #23324a;color:#d4dcea;border-radius:7px;padding:4px 10px;cursor:pointer;font:inherit}#optlab .ol-mini{padding:1px 7px;font-size:11px}
#optlab .ol-b.on{border-color:#22d3ee;color:#22d3ee}#optlab .ol-b:disabled{opacity:.4;cursor:default}
#optlab .ol-in{background:#060b13;border:1px solid #23324a;color:#d4dcea;border-radius:7px;padding:4px 8px;font:inherit;color-scheme:dark}
#optlab .ol-ck{display:inline-flex;gap:4px;align-items:center;border:1px solid #23324a;border-radius:7px;padding:3px 8px;cursor:pointer}#optlab .ol-ck.on{border-color:#22d3ee}#optlab .ol-ck small{color:#7b8799}
#optlab .ol-go{background:linear-gradient(90deg,#0e7490,#1d4ed8);border:0;color:#fff;border-radius:8px;padding:6px 16px;cursor:pointer;font:inherit;font-weight:700}#optlab .ol-go:disabled{opacity:.5;cursor:default}
#optlab .ol-est{color:#9fb0c6}#optlab .ol-pt{color:#cbd5e1}#optlab .ol-bar{height:6px;background:#0b1320;border-radius:4px;overflow:hidden;margin:4px 0 8px}#optlab .ol-bar i{display:block;height:100%;width:0;background:linear-gradient(90deg,#22d3ee,#7c9fff);transition:width .3s}
#optlab .ol-how{color:#7b8799;border:1px dashed #1f2c40;border-radius:8px;padding:6px 9px;margin:8px 0}
#optlab .ol-sec{margin:10px 0 4px;font-size:13px}#optlab .ol-sum{margin:4px 0}#optlab .ol-sub{color:#9fb0c6;margin:12px 0 4px;font-weight:700}
#optlab .ol-act{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0}
#optlab .ol-tw{overflow-x:auto}#optlab .ol-t{border-collapse:collapse;width:100%;font-size:11px}#optlab .ol-t th,#optlab .ol-t td{border:1px solid #15202f;padding:5px 6px;vertical-align:top;text-align:left}#optlab .ol-t th{color:#7b8799;background:#08101a;white-space:nowrap}
#optlab .ol-t td.ok,#optlab .ol-t tr.ok td{background:rgba(38,208,124,.07)}#optlab .ol-t td.no,#optlab .ol-t tr.no td{opacity:.8}
#optlab .ol-tag{border:1px solid #23324a;border-radius:7px;padding:2px 6px}#optlab .ol-tag.off{opacity:.6}
#optlab .ol-run{display:flex;flex-wrap:wrap;gap:8px;align-items:center;border-bottom:1px solid #121b29;padding:4px 0}
#optlab .up{color:#26d07c}#optlab .dn{color:#ff4d64}#optlab .dim{color:#5b6678}#optlab .warn{color:#f5b84b}
@media(max-width:760px){#optlab{padding:8px}#optlab .ol-box{padding:10px}}`;
  document.head.appendChild(st);
}
