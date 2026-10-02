// GH Quant 앱 창(설치형 웹앱)용 서비스 워커 — 화면 파일은 늘 서버에서 새로 받는다 (데이터를 캐시하지 않음).
// 프로그램이 꺼져 있을 때만 안내 화면을 보여 준다.
const OFFLINE = `<!doctype html><meta charset="utf-8"><title>GH Quant</title>
<style>body{margin:0;height:100vh;display:grid;place-items:center;background:#0f1218;color:#d1d4dc;font-family:system-ui,"Malgun Gothic",sans-serif;text-align:center}
b{color:#2962ff}button{margin-top:16px;padding:8px 18px;border:0;border-radius:6px;background:#2962ff;color:#fff;font-size:14px;cursor:pointer}</style>
<div><h2>GH <b>QUANT</b> 프로그램이 꺼져 있습니다</h2><p>GHQuant 실행 파일을 다시 실행한 뒤 아래 버튼을 누르세요.</p><button onclick="location.reload()">다시 연결</button></div>`;

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (e) => {
  if (e.request.mode !== "navigate") return;
  e.respondWith(fetch(e.request).catch(() => new Response(OFFLINE, { headers: { "Content-Type": "text/html; charset=utf-8" } })));
});
