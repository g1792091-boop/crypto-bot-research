// 누리 AI 서비스 워커
// 1) 앱 파일을 저장해 인터넷 없이도 열리게 하고 (항상 최신본 우선, 연결이 없을 때만 저장본)
// 2) COOP/COEP 헤더를 붙여 멀티스레드(SharedArrayBuffer) CPU 추론을 켠다 (GitHub Pages는 헤더를 직접 설정할 수 없음)
const CACHE = "nuri-app-v19";
const ASSETS = ["./", "./index.html", "./trade.js", "./engine.js", "./agent.js", "./templates.js", "./train.js", "./nvskills.js", "./skills/nvidia/index.json", "./app.js", "./office.js", "./office-ui.js", "./office.css", "./paper.js", "./quant.js", "./quant-cards.json", "./history.js", "./scenarios.js", "./flow.js", "./biz.js", "./customind.js", "./ml.js", "./macro.js", "./realestate.js", "./media.js", "./live.js", "./live-ui.js", "./live.css", "./terminal/terminal.js", "./terminal/chart.js", "./terminal/data.js", "./terminal/draw.js", "./terminal/ind.js", "./terminal/registry.js", "./terminal/terminal.css", "./vendor/lightweight-charts/lightweight-charts.standalone.production.js", "./vendor/wllama/index.js", "./vendor/fonts/PretendardVariable.woff2", "./vendor/wllama/wllama.wasm", "./manifest.webmanifest", "./icon.svg"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS.map(u => new Request(u, {cache: "reload"})))).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k.startsWith("nuri-app-") && k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});

function isolate(res) {
  if (!res || res.status === 0 || res.type === "opaque") return res;
  const h = new Headers(res.headers);
  h.set("Cross-Origin-Embedder-Policy", "credentialless");
  h.set("Cross-Origin-Opener-Policy", "same-origin");
  h.set("Cross-Origin-Resource-Policy", "same-origin");
  return new Response(res.body, { status: res.status, statusText: res.statusText, headers: h });
}

self.addEventListener("fetch", e => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin) return; // 모델 다운로드 등 외부 요청은 건드리지 않음
  if (url.pathname.startsWith("/__nuri/")) return;                          // 실행기(exe)의 연결 확인·중계 경로
  e.respondWith((async () => {
    const cache = await caches.open(CACHE);
    try {
      const net = await fetch(req, {cache: "no-cache"});
      if (net.ok) cache.put(req, net.clone());
      return isolate(net);
    } catch (err) {
      const hit = await cache.match(req, {ignoreSearch: true}) || (req.mode === "navigate" ? await cache.match("./index.html") : null);
      return isolate(hit || Response.error());
    }
  })());
});
