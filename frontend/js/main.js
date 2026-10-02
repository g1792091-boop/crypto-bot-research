// 진입점: 상태 불러오기 → 화면 초기화 → 탭 전환
import { initAgents } from "./agents.js";
import { initAiAuto } from "./aiauto.js";
import { initAiDock } from "./aidock.js";
import { initAiModels } from "./aimodels.js";
import { initAlerts } from "./alerts.js";
import { initAutopilot } from "./autopilot.js";
import { $, $$, api, emit, esc, on, state, syncAutopilot, toast } from "./core.js";
import { initLab } from "./lab.js";
import { initMarket } from "./market.js";
import { initOffice } from "./office.js";
import { initQuant } from "./quant.js";
import { initTrade } from "./trade.js";

function go(view) {
  $$("#nav button").forEach((b) => b.classList.toggle("on", b.dataset.view === view));
  $$(".view").forEach((v) => v.classList.toggle("on", v.id === `v-${view}`));
  emit("view", view);
}

function renderStatus() {
  const s = state.status;
  const src = state.tickerSource;
  $("#status").innerHTML = [
    [src === "synthetic" ? "warn" : src ? "ok" : "warn", src === "synthetic" ? "가상 데이터 (테스트 모드)" : src ? `${{ binance: "바이낸스", bybit: "바이빗", okx: "OKX" }[src] || src} 실시간` : "거래소 연결 안 됨",
      src === "synthetic" ? "DATA_SOURCE=synthetic 이라 가상 시세입니다" : src === "binance" || !src ? (src ? "바이낸스 선물 실시간 시세" : "바이낸스·바이빗·OKX 모두 응답이 없습니다") : "바이낸스에 닿지 않아 다른 거래소의 실제 시세를 쓰고 있습니다"],
    [s.coinglass ? "ok" : "", s.coinglass ? "CoinGlass" : "CoinGlass 미연결", s.coinglass ? "" : "settings.txt 에 COINGLASS_API_KEY 를 넣으면 연결됩니다"],
    [s.llm ? "ok" : "", s.llm ? s.llm_label : "AI 미연결", s.llm ? `${s.model}${s.llm_provider === "gemini" ? " · 무료 등급은 분당 요청 수가 적어 느릴 수 있습니다" : s.llm_provider === "nvidia" ? " · NVIDIA 무료 크레딧 · 분당 약 40회" : ""}`
      : "settings.txt 에 NVIDIA_API_KEY(무료) · GEMINI_API_KEY(무료) 또는 ANTHROPIC_API_KEY 를 넣으면 연결됩니다"],
  ].map(([c, l, t], i) => `<span class="${c}" title="${esc(t)}${i === 2 ? " · 누르면 AI 모델 설정" : ""}" ${i === 2 ? 'data-open-ai style="cursor:pointer"' : ""}><i></i>${l}</span>`).join("");
}

async function init() {
  state.status = await api("/api/status");
  const br = document.querySelector(".brand");
  if (br && state.status.build) br.insertAdjacentHTML("beforeend", ` <small class="muted" style="font-size:10px;font-weight:400" title="빌드 번호 — 새 버전이 실행 중인지 확인용">${esc(state.status.build)}</small>`);
  initAlerts();
  initAiModels();
  initTrade();
  initAiDock();
  syncAutopilot();
  initAutopilot();
  initLab();
  initAgents();
  initOffice();
  initMarket();
  initQuant();
  initAiAuto();
  renderStatus();
  on("tickers", renderStatus);
  on("goto", go);
  $("#nav").onclick = (e) => e.target.dataset.view && go(e.target.dataset.view);
}

// 설치형 웹앱: 바탕화면·시작 메뉴 아이콘으로 따로 된 창에서 열기 (브라우저가 '설치'를 허락할 때만 버튼이 보임)
function initInstall() {
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  let ask = null;
  const btn = $("#install-app");
  window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); ask = e; btn.hidden = false; });
  window.addEventListener("appinstalled", () => { btn.hidden = true; toast("앱 설치 완료", "바탕화면·시작 메뉴의 GH Quant 아이콘으로 열 수 있습니다 (프로그램이 켜져 있어야 함)."); });
  btn.onclick = async () => { if (!ask) return; ask.prompt(); await ask.userChoice.catch(() => null); ask = null; btn.hidden = true; };
}

initInstall();
init().catch((e) => toast("시작 실패", e.message, "err"));
