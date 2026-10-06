// ⏱ 장시간 구동 점검(soak) — GH Coin 앱 전체를 머리 없는 Edge(별도 프로필)에서 오래 켜 두고, 몇 분마다 상태를 기록한다.
//   왜: 기능 확인은 짧은 하네스로만 했다. 하루 이상 켜 두면 메모리가 계속 늘거나, 저장소가 차거나, 오류가 쌓이는 문제는 짧은 시험에 안 보인다.
//   기록: JS 힙 · DOM 노드 수 · localStorage 크기 · IndexedDB 사용량 · 콘솔 오류/경고 수(새로 생긴 종류) · 뉴럴 데스크 상태(체결·포지션·피드)
//   사용자 앱 창·저장소는 건드리지 않는다(별도 프로필, 창 안 뜸). 로컬 Ollama 는 실제로 쓴다.
// 쓰는 법: python devserver.py (다른 터미널) → node tools/soak.mjs [분=120] [간격분=5] [결과.json]
import { spawn } from "child_process";
import fs from "fs";
const MIN = +(process.argv[2] || 120), EVERY = +(process.argv[3] || 5), OUT = process.argv[4] || "";
const PORT = 9700 + Math.floor(Math.random() * 200), UD = (process.env.TEMP || ".") + "/ghcoin-soak-profile";
const EDGE = process.env.EDGE_PATH || "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", `--remote-debugging-port=${PORT}`, `--user-data-dir=${UD}`, "--window-size=1500,950", "--no-first-run", "about:blank"], { stdio: "ignore" });
const sleep = ms => new Promise(r => setTimeout(r, ms));
let ws, id = 0; const pend = new Map(), errs = new Map(); let errN = 0, warnN = 0;
// 응답이 안 오면(연결 끊김 등) 20초 뒤 null — 한 번 멈춘 요청 때문에 기록 전체가 멈추지 않게(2026-10-06 첫 시도에서 실제로 멈췄음)
const send = (method, params = {}) => new Promise(res => { const i = ++id; const to = setTimeout(() => { pend.delete(i); res(null); }, 20000); pend.set(i, v => { clearTimeout(to); res(v); }); try { ws.send(JSON.stringify({ id: i, method, params })); } catch (e) { clearTimeout(to); res(null); } });
const ev = async expr => (await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true }))?.result?.value;
const rows = [];
try {
  let ver = null; for (let k = 0; k < 40 && !ver; k++) { await sleep(300); try { ver = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json(); } catch (e) {} }
  const tgt = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: "PUT" })).json();
  ws = new WebSocket(tgt.webSocketDebuggerUrl); await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result || m.error); pend.delete(m.id); return; }
    const key = m.method === "Runtime.exceptionThrown" ? "EXC " + (m.params.exceptionDetails?.exception?.description || m.params.exceptionDetails?.text || "").slice(0, 160)
      : m.method === "Runtime.consoleAPICalled" && ["error", "warning"].includes(m.params.type) ? m.params.type.toUpperCase() + " " + m.params.args.map(a => a.value ?? a.description ?? "").join(" ").slice(0, 160) : null;
    if (!key) return; if (key.startsWith("WARN")) warnN++; else errN++; errs.set(key, (errs.get(key) || 0) + 1); };
  await send("Runtime.enable"); await send("Page.enable"); await send("Performance.enable");
  await send("Page.navigate", { url: "http://127.0.0.1:8777/gh-coin/index.html?soak=1" });
  await sleep(4000); await ev(`localStorage.setItem("coinTeamLocal", "1")`); await send("Page.reload");   // 로컬 Ollama 모델로 팀·뉴럴 데스크가 실제로 일하게
  const t0 = Date.now();
  console.log(`⏱ ${MIN}분 동안 ${EVERY}분마다 기록 시작`);
  while (Date.now() - t0 < MIN * 60e3) {
    await sleep(Math.min(EVERY * 60e3, Math.max(1000, MIN * 60e3 - (Date.now() - t0))));
    const pm = (await send("Performance.getMetrics"))?.metrics || [], g = k => pm.find(x => x.name === k)?.value;
    const app = await ev(`(async () => { let ls = 0; for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); ls += k.length + (localStorage.getItem(k) || "").length; }
      let q = null; try { q = await navigator.storage.estimate(); } catch (e) {}
      let n = null; try { const N = await import("/gh-coin/neural.js"); const s = N.state(); n = { fills: s.fills, open: s.openN, feed: s.feed.length, eq: s.equity, trades: s.trades.length }; } catch (e) { n = String(e.message || e).slice(0, 60); }
      return { ls: Math.round(ls * 2 / 1024), idb: q ? Math.round(q.usage / 1024) : null, n }; })()`);
    if (!pm.length && ws.readyState !== 1) { console.log("연결 끊김 — 다시 연결"); try { const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json(), pg = list.find(t => t.type === "page" && /gh-coin/.test(t.url)); ws = new WebSocket(pg.webSocketDebuggerUrl); await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; }); } catch (e) {} }
    const row = { min: Math.round((Date.now() - t0) / 60e3), heapMB: +(g("JSHeapUsedSize") / 1048576).toFixed(1), nodes: g("Nodes"), listeners: g("JSEventListeners"), lsKB: app?.ls, idbKB: app?.idb, errN, warnN, kinds: errs.size, neural: app?.n };
    rows.push(row); console.log(JSON.stringify(row));
  }
  const first = rows[0], last = rows.at(-1);
  console.log(`\n결과: 힙 ${first?.heapMB}→${last?.heapMB}MB · DOM ${first?.nodes}→${last?.nodes} · localStorage ${first?.lsKB}→${last?.lsKB}KB · IndexedDB ${first?.idbKB}→${last?.idbKB}KB · 오류 ${errN}건(${errs.size}종) · 경고 ${warnN}건`);
  console.log([...errs.entries()].sort((a, b) => b[1] - a[1]).slice(0, 15).map(([k, v]) => `${v}× ${k}`).join("\n"));
  if (OUT) fs.writeFileSync(OUT, JSON.stringify({ rows, errs: [...errs.entries()] }, null, 1));
} catch (e) { console.log("SOAK ERR", e.message); }
finally { try { ws?.close(); } catch (e) {} edge.kill(); setTimeout(() => process.exit(0), 300); }
