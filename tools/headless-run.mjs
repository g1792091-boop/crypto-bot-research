// 개발용 확인 도구 — 머리 없는 Edge(별도 프로필)를 원격 디버깅으로 몰아 테스트 페이지를 끝까지 실행하고 결과·콘솔 오류를 받는다.
// 왜: GHCoin.exe 를 다시 켜면 사용자 화면에 앱 창이 뜨고(Edge 앱 창), 예전 창이 남아 있으면 엔진이 두 번 돈다. 이 도구는 사용자의 앱 창·저장소를 건드리지 않는다.
// 쓰는 법:  python devserver.py  (다른 터미널, 포트 8777)
//           node tools/headless-run.mjs "http://127.0.0.1:8777/tools/harness.html?t=trader" 120
//           node tools/headless-run.mjs "http://127.0.0.1:8777/tools/harness.html?t=mission&ai=1" 1700     (로컬 Ollama 로 지시 한 건을 끝까지)
//   인자: <url> [기다릴 초=120] [스크린샷.png] · 환경변수 MAXOUT(출력 글자 수) · HEADLESS_PROFILE(프로필 폴더)
//   페이지는 끝나면 document.title 을 "DONE"(또는 OK…/ERR…)으로 바꾸고 결과를 document.body 에 쓴다.
import { spawn } from "child_process";
import fs from "fs";
const url = process.argv[2], TO = +(process.argv[3] || 120), shot = process.argv[4] || "", PORT = 9333 + Math.floor(Math.random() * 300);
const UD = process.env.HEADLESS_PROFILE || ((process.env.TEMP || "/tmp") + "/ghcoin-headless-profile");
const EDGE = process.env.EDGE_PATH || "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", `--remote-debugging-port=${PORT}`, `--user-data-dir=${UD}`, "--window-size=1500,950", "--no-first-run", "about:blank"], { stdio: "ignore" });
const sleep = ms => new Promise(r => setTimeout(r, ms));
let ws, id = 0; const pend = new Map(), logs = [];
const send = (method, params = {}) => new Promise((res, rej) => { const i = ++id; pend.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params })); });
try {
  let ver = null; for (let k = 0; k < 40 && !ver; k++) { await sleep(300); try { ver = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json(); } catch (e) {} }
  if (!ver) throw new Error("edge 디버깅 포트 연결 실패");
  const tgt = await (await fetch(`http://127.0.0.1:${PORT}/json/new?${encodeURIComponent("about:blank")}`, { method: "PUT" })).json();
  ws = new WebSocket(tgt.webSocketDebuggerUrl); await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  ws.onmessage = ev => { const m = JSON.parse(ev.data); if (m.id && pend.has(m.id)) { pend.get(m.id).res(m.result || m.error); pend.delete(m.id); }
    else if (m.method === "Runtime.exceptionThrown") logs.push("EXC " + (m.params.exceptionDetails?.exception?.description || m.params.exceptionDetails?.text || "").slice(0, 400));
    else if (m.method === "Runtime.consoleAPICalled" && ["error", "warning"].includes(m.params.type)) logs.push(m.params.type.toUpperCase() + " " + m.params.args.map(a => a.value ?? a.description ?? "").join(" ").slice(0, 300)); };
  await send("Runtime.enable"); await send("Page.enable");
  await send("Page.navigate", { url });
  const t0 = Date.now(); let title = "";
  while (Date.now() - t0 < TO * 1000) { await sleep(1000); const r = await send("Runtime.evaluate", { expression: "document.title", returnByValue: true }); title = r?.result?.value || ""; if (/^(DONE|OK|ERR)/.test(title)) break; }
  const body = (await send("Runtime.evaluate", { expression: "document.body.innerText", returnByValue: true }))?.result?.value || "";
  if (shot) { const s = await send("Page.captureScreenshot", { format: "png" }); if (s?.data) fs.writeFileSync(shot, Buffer.from(s.data, "base64")); }
  console.log("TITLE:", title, `(${Math.round((Date.now() - t0) / 1000)}초)`); console.log(body.slice(0, +(process.env.MAXOUT || 3000)));
  if (logs.length) console.log("--- 콘솔 오류/경고 " + logs.length + "건 ---\n" + [...new Set(logs)].slice(0, 12).join("\n"));
} catch (e) { console.log("HARNESS ERR", e.message); }
finally { try { ws?.close(); } catch (e) {} edge.kill(); setTimeout(() => process.exit(0), 300); }
