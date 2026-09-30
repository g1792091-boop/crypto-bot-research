// 진입점: 상태 불러오기 → 화면 초기화 → 탭 전환
import { initAgents } from "./agents.js";
import { initAlerts } from "./alerts.js";
import { $, $$, api, emit, esc, on, state, toast } from "./core.js";
import { initLab } from "./lab.js";
import { initMarket } from "./market.js";
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
    [s.llm ? "ok" : "", s.llm ? "Claude" : "Claude 미연결", s.llm ? s.model : "settings.txt 에 ANTHROPIC_API_KEY 를 넣으면 연결됩니다"],
  ].map(([c, l, t]) => `<span class="${c}" title="${esc(t)}"><i></i>${l}</span>`).join("");
}

async function init() {
  state.status = await api("/api/status");
  initAlerts();
  initTrade();
  initLab();
  initAgents();
  initMarket();
  renderStatus();
  on("tickers", renderStatus);
  on("goto", go);
  $("#nav").onclick = (e) => e.target.dataset.view && go(e.target.dataset.view);
}

init().catch((e) => toast("시작 실패", e.message, "err"));
