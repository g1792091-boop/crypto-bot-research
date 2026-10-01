// GH Coin 앱 시작: 트레이딩 본부(픽셀 사무실) 화면을 바로 열고, AI 연결·차트 터미널·실거래·학습 데이터를 붙인다.
// AI 연결(API 키)·실거래 키는 같은 컴퓨터의 GH Nano 와 같은 설정을 쓴다(같은 실행기 주소일 때). 대화 기록·데모 장부·과제는 GH Coin 것만 따로 쓴다.
import { esc, md, settings, saveSettings, PROVIDERS, SEARCH_KEYS, addApiKey, removeApiKey, detectLauncher, LAUNCHER, idb } from "../nuri-ai/engine.js";
import { openOffice, openComboBoard } from "./coin-ui.js";

const $ = s => document.querySelector(s);
const toast = m => { const t = $("#toast"); t.textContent = m; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => t.hidden = true, 3200); };
const openTerminal = async (o = {}) => { try { const T = await import("../nuri-ai/terminal/terminal.js"); T.openTerminal({market: o.market || "BTCUSDT", exchange: o.exchange || "binancef", interval: o.interval || "1h"}, {esc}); } catch(e){ toast("차트 터미널을 열 수 없습니다: " + e.message); } };
const openLive = async () => { try { const L = await import("../nuri-ai/live-ui.js"); L.openLive({md, esc, toast}); } catch(e){ toast("실거래 화면을 열 수 없습니다: " + e.message); } };
import("../nuri-ai/live-ui.js").then(L => L.initLive({toast, esc, md})).catch(() => {});   // 주문 승인 창은 화면을 안 열어도 등록

/* ---- AI 연결 · 학습 데이터 창 ---- */
function keysHTML(){
  const conn = Object.entries(PROVIDERS).filter(([id]) => settings.keys[id]);
  const sk = Object.entries(SEARCH_KEYS).filter(([id]) => settings.keys[id]);
  return `<div class="gc-box" role="dialog" aria-label="AI 연결">
    <h3>🔑 AI 연결 · 설정</h3><p>API 키를 붙여 넣으면 어느 회사 것인지 알아서 연결합니다. 여러 회사를 넣을수록 한도에 덜 걸립니다. 유튜브·공공데이터 키는 'youtube: 키' 처럼 이름을 붙여 넣습니다.</p>
    <div class="gc-row"><input id="gcKey" placeholder="API 키 붙여넣기 (nvapi-… · gsk_… · sk-ant-… · sk-or-… 등)" autocomplete="off"><button class="gc-btn pri" id="gcAdd">연결</button></div>
    <h4>연결된 AI ${conn.length}곳</h4>
    ${conn.map(([id, p]) => `<div class="gc-prov"><span><b>${esc(p.name)}</b> <small>모델 ${(settings.provModels[id] || []).length}개</small></span><button class="gc-btn" data-rm="${id}">삭제</button></div>`).join("") || `<p>아직 없습니다. 아래에서 무료 키를 받아 붙여 넣으세요.</p>`}
    ${sk.map(([id, p]) => `<div class="gc-prov"><span><b>${esc(p.name)}</b></span><button class="gc-btn" data-rm="${id}">삭제</button></div>`).join("")}
    <h4>키 받는 곳</h4><div class="gc-links">${Object.entries(PROVIDERS).map(([id, p]) => `<a class="${settings.keys[id] ? "on" : ""}" href="${p.url}" target="_blank" rel="noopener">${esc(p.name)}${settings.keys[id] ? " ✓" : ""}</a>`).join("")}</div>
    <h4>학습 데이터 (GH Nano 만들기)</h4><p>GH Coin 직원들의 분석·회의·검증된 매매법이 학습 예시로 쌓입니다(Claude·Gemini·GPT 유료 모델이 쓴 글은 약관 때문에 제외). GH Nano 의 학습 탭에서도 함께 보이고, 여기서 따로 내려받을 수 있습니다.</p>
    <div class="gc-row"><button class="gc-btn" id="gcTrain">GH Coin 학습 데이터 내려받기 (.jsonl)</button><span id="gcTrainN" style="color:#8a93a6;align-self:center"></span></div>
    <h4>실행</h4><p>${LAUNCHER.on ? "GHCoin.exe 로 실행 중 — 외부 AI·거래소 연결, 컴퓨터 작업(문서/GHNano 사무실/ghcoin), 코드 수정 적용이 됩니다." : "웹 버전 — 브라우저 보안 때문에 외부 AI·거래소에 바로 연결되지 않을 수 있습니다. GHCoin.exe 로 실행하세요."}</p>
    <div class="gc-row" style="justify-content:flex-end"><button class="gc-btn" id="gcClose">닫기</button></div></div>`;
}
async function trainCount(){ const all = await idb.all("train:").catch(() => []); return all.filter(x => x.app === "ghcoin" && !(x.rating < 0)); }
function openKeys(){
  let m = $("#gcModal");
  if (!m){ m = document.createElement("div"); m.id = "gcModal"; m.className = "gc-modal"; document.body.appendChild(m);
    m.addEventListener("click", async e => {
      if (e.target === m || e.target.closest("#gcClose")){ m.hidden = true; return; }
      const rm = e.target.closest("[data-rm]"); if (rm){ removeApiKey(rm.dataset.rm); m.innerHTML = keysHTML(); return; }
      if (e.target.closest("#gcAdd")){
        const v = $("#gcKey").value.trim(); if (!v) return; const b = e.target.closest("#gcAdd"); b.disabled = true; b.textContent = "확인 중…";
        try { const r = await addApiKey(v); toast(r.kind === "search" ? `${r.name} 연결됨` : `${r.name || PROVIDERS[r.id]?.name || "AI"} 연결됨 · 모델 ${r.models ?? ""}개`); }
        catch(err){ toast(err.message || "연결하지 못했습니다"); }
        m.innerHTML = keysHTML(); return;
      }
      if (e.target.closest("#gcTrain")){
        const list = await trainCount();
        if (!list.length){ toast("아직 학습 예시가 없습니다 · 직원들이 일하면 쌓입니다"); return; }
        const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([list.map(x => JSON.stringify({messages: x.messages})).join("\n") + "\n"], {type: "application/jsonl"}));
        a.download = "ghcoin-train.jsonl"; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 3000); toast(`학습 예시 ${list.length}개를 내려받았습니다`);
      }
    });
    m.addEventListener("keydown", e => { if (e.key === "Enter" && e.target.id === "gcKey") $("#gcAdd")?.click(); if (e.key === "Escape") m.hidden = true; });
  }
  m.innerHTML = keysHTML(); m.hidden = false;
  trainCount().then(l => { const n = $("#gcTrainN"); if (n) n.textContent = `${l.length}개 쌓임`; });
  setTimeout(() => $("#gcKey")?.focus(), 50);
}

/* ---- 시작 ---- */
(async () => {
  await detectLauncher().catch(() => false);
  openOffice({md, esc, toast, openTerminal, openLive});
  $("#gcSplash")?.remove();
  // 사무실 위쪽 바에 AI 연결 버튼
  const top = document.querySelector(".of-top"), set = document.querySelector("#ofSetBtn")?.closest(".of-pick");
  if (top && !$("#gcKeys")){ const b = document.createElement("button"); b.className = "of-btn"; b.id = "gcKeys"; b.textContent = "🔑 AI 연결"; b.onclick = openKeys; set ? top.insertBefore(b, set) : top.appendChild(b); }
  if (top && !$("#gcCombo")){ const b = document.createElement("button"); b.className = "of-btn"; b.id = "gcCombo"; b.textContent = "⚡ 실시간 타점"; b.title = "모든 보조지표 × 4개 시간대 → 추세·타점 (60초마다)"; b.onclick = () => openComboBoard(true); top.insertBefore(b, top.querySelector(".of-btn") || null); }
  if (!Object.keys(PROVIDERS).some(id => settings.keys[id])) setTimeout(() => { openKeys(); toast("먼저 AI 키를 하나 이상 연결하세요 (NVIDIA·Groq·Cerebras 무료)"); }, 600);
  document.title = "GH Coin";
})();
addEventListener("unhandledrejection", e => { const m = String(e.reason?.message || e.reason || ""); if (m && !/abort/i.test(m)) toast("오류: " + m.slice(0, 120)); });
// 앱이 끝까지 열렸다는 표시 (index.html 의 코드 수정 안전장치가 본다)
window.__ghReady = true; try { localStorage.removeItem("ghn:boot"); } catch(e){}
