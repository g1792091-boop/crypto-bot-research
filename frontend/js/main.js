// 진입점: 상태 불러오기 → 화면 초기화 → 탭 전환
import { initAgents } from "./agents.js";
import { initAiAuto } from "./aiauto.js";
import { initAiModels } from "./aimodels.js";
import { initAlerts } from "./alerts.js";
import { initAutopilot } from "./autopilot.js";
import { $, $$, api, emit, esc, on, state, syncAutopilot, toast } from "./core.js";
import { initLab } from "./lab.js";
import { initMarket } from "./market.js";
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
    [src === "synthetic" ? "warn" : "ok", src === "synthetic" ? "가상 데이터" : "바이낸스 연결", src === "synthetic" ? "거래소에 연결되지 않아 가상 시세를 보여주고 있습니다" : ""],
    [s.coinglass ? "ok" : "", s.coinglass ? "CoinGlass" : "CoinGlass 미연결", s.coinglass ? "" : "settings.txt 에 COINGLASS_API_KEY 를 넣으면 연결됩니다"],
    [s.llm ? "ok" : "", s.llm ? s.llm_label : "AI 미연결", s.llm ? `${s.model}${s.llm_provider === "gemini" ? " · 무료 등급은 분당 요청 수가 적어 느릴 수 있습니다" : s.llm_provider === "nvidia" ? " · NVIDIA 무료 크레딧 · 분당 약 40회" : ""}`
      : "settings.txt 에 NVIDIA_API_KEY(무료) · GEMINI_API_KEY(무료) 또는 ANTHROPIC_API_KEY 를 넣으면 연결됩니다"],
  ].map(([c, l, t], i) => `<span class="${c}" title="${esc(t)}${i === 2 ? " · 누르면 AI 모델 설정" : ""}" ${i === 2 ? 'data-open-ai style="cursor:pointer"' : ""}><i></i>${l}</span>`).join("");
}

async function init() {
  state.status = await api("/api/status");
  initAlerts();
  initAiModels();
  initTrade();
  syncAutopilot();
  initAutopilot();
  initLab();
  initAgents();
  initMarket();
  initQuant();
  initAiAuto();
  renderStatus();
  on("tickers", renderStatus);
  on("goto", go);
  $("#nav").onclick = (e) => e.target.dataset.view && go(e.target.dataset.view);
}

init().catch((e) => toast("시작 실패", e.message, "err"));
