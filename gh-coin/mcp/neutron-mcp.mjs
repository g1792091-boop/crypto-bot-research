#!/usr/bin/env node
// 🧠 뉴트론 MCP 서버 — GH Coin 앱의 뇌(자체 뇌·뉴럴 데스크·에이전트 팀 판정·옵시디언 볼트)를 Claude Code / Claudian 에 도구로 연다.
// 의존성 없음(Node 18+). stdio JSON-RPC (MCP 2024-11-05 / 2025-03-26 호환).
// 데이터: NEUTRON_DIR(기본 문서/GHNano 사무실)/neutron/state.json — 앱(GHCoin.exe)이 1분마다 씀.
// 쓰기: neutron/inbox.jsonl 에 '지식 메모 · 매매법 실험 제안 · 팀 과제' 만 넣는다 → 앱이 30초마다 반영.
// 안전: 주문·레버리지·한도·API 키 도구는 일부러 없다. (참고 개념: brain-mcp 노트 도구, Sharpe 펀딩 스캔, ocean-agent 실측 셋업·승률 — 코드 복사 없음)
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import readline from "node:readline";

const BASE = process.env.NEUTRON_DIR || path.join(os.homedir(), "Documents", "GHNano 사무실");
const STATE = path.join(BASE, "neutron", "state.json"), INBOX = path.join(BASE, "neutron", "inbox.jsonl"), VAULT = path.join(BASE, "GHCoin 뇌");
const VERSION = "1.0.0";

function state() {
  let raw; try { raw = fs.readFileSync(STATE, "utf8"); } catch (e) { throw new Error(`앱 상태 파일이 없습니다: ${STATE}\nGHCoin.exe 를 켜 두면 1분 안에 생깁니다.`); }
  const s = JSON.parse(raw); s._ageSec = Math.round((Date.now() - s.t) / 1000); return s;
}
const age = s => s._ageSec > 300 ? `\n⚠ 상태가 ${Math.round(s._ageSec / 60)}분 전 것입니다 (앱이 꺼져 있을 수 있음)` : "";
const J = o => JSON.stringify(o, null, 1);
const coinId = c => String(c || "").toUpperCase().replace(/USDT$/, "").toLowerCase();
function inbox(item) {
  fs.mkdirSync(path.dirname(INBOX), { recursive: true });
  fs.appendFileSync(INBOX, JSON.stringify({ ...item, by: process.env.NEUTRON_BY || "Claude", t: Date.now() }) + "\n");
}
function walk(dir, out = []) {
  let ents = []; try { ents = fs.readdirSync(dir, { withFileTypes: true }); } catch (e) { return out; }
  for (const e of ents) { if (e.name.startsWith(".")) continue; const p = path.join(dir, e.name); if (e.isDirectory()) walk(p, out); else if (e.name.endsWith(".md")) out.push(p); }
  return out;
}
const rel = p => path.relative(VAULT, p).replace(/\\/g, "/");
const toks = q => String(q || "").toLowerCase().split(/[\s,·]+/).filter(x => x.length >= 1);

const TOOLS = [
  { name: "neutron_status", description: "GH Coin 뉴럴 데스크 현재 상태: 자본·낙폭·승률·동시 리스크·보유 포지션(레버리지·손절·익절)·코인별 국면·뉴스·뇌 지능", input: {},
    run: () => { const s = state(), n = s.neural; return `자본 $${n.equity} (시작 $${n.bankroll}) · 손익 ${n.pnl}$ · 낙폭 ${n.drawdown}% · 거래 ${n.fills}회 승률 ${n.winRate}% · 동시 리스크 ${n.heat}% · 오늘 ${n.dayPnl}$ · 모드 ${n.riskMode}
뇌 지능 ${s.brain.iq.score}/100 (정확도 ${s.brain.iq.acc}% · ${s.brain.iq.n}판) · 기억 ${s.brain.mem.length}개
포지션: ${n.positions.length ? n.positions.map(p => `${p.sym} ${p.side} ${p.lev}x @${p.entry} SL ${p.sl} TP ${p.tp} (${p.strategy})`).join(" | ") : "없음"}
국면: ${Object.entries(n.regime || {}).map(([k, r]) => `${k.replace("USDT", "")} ${r.label}(4H ${r.htf > 0 ? "↑" : r.htf < 0 ? "↓" : "→"})`).join(" · ")}
뉴스: ${n.news ? `${n.news.score} ${n.news.reason || ""}` : "없음"}${age(s)}`; } },
  { name: "neutron_query_knowledge", description: "자체 뇌 기억 검색(교훈·패턴·지식·전략·핵심 규칙). 가중치(확인 횟수) 높은 순", input: { query: { type: "string", description: "검색어 (예: 'BTC 손절 횡보')" }, type: { type: "string", description: "교훈|패턴|지식|전략|핵심|관찰 (선택)" }, coin: { type: "string" }, limit: { type: "number" } }, required: ["query"],
    run: a => { const s = state(), q = toks(a.query), c = coinId(a.coin);
      const hits = s.brain.mem.filter(m => (!a.type || m.type === a.type) && (!c || coinId(m.coin) === c)).map(m => ({ m, sc: q.reduce((x, t) => x + ((`${m.text} ${m.coin} ${m.regime} ${m.type}`).toLowerCase().includes(t) ? 1 : 0), 0) }))
        .filter(x => x.sc > 0 || !q.length).sort((x, y) => y.sc - x.sc || y.m.w - x.m.w).slice(0, Math.min(50, a.limit || 15));
      return hits.length ? hits.map(({ m }) => `- [${m.type}] ${m.coin ? m.coin + " " : ""}${m.regime ? "(" + m.regime + ") " : ""}${m.text} · 가중 ${m.w} · 확인 ${m.hits}회 · ${m.model}`).join("\n") : "일치하는 기억 없음"; } },
  { name: "neutron_top_setups", description: "검증된 셋업 순위 = 기대값(R) × 승률 × 신뢰도(표본). 자체 백테스트 + 실전 최근 20건 실측", input: { limit: { type: "number" } },
    run: a => { const s = state(); return (s.neural.setups || []).slice(0, a.limit || 10).map((x, i) => `${i + 1}. ${x.name} @${x.tf} · 점수 ${x.score} · 기대값 ${x.mean}R · 승률 ${x.wr}% · ${x.n}건${x.active ? " · ✅실전" : ""}`).join("\n") || "아직 검증된 셋업 없음 (보정 대기)"; } },
  { name: "neutron_learned_winrates", description: "매매법 × 시장 국면별 실측 승률·기대값 (어떤 장에서 통하는지). 손실 검증된 국면은 앱이 자동으로 진입을 건너뜀", input: { regime: { type: "string", description: "상승추세|하락추세|횡보|수축|전환" }, strategy: { type: "string" } },
    run: a => { const s = state(); return (s.neural.winrates || []).filter(w => (!a.regime || w.regime === a.regime) && (!a.strategy || (w.vkey + w.name).includes(a.strategy))).map(w => `${w.name} | ${w.regime} | ${w.n}건 승률 ${w.wr}% | ${w.mean}R`).join("\n") || "해당 자료 없음"; } },
  { name: "neutron_strategy_engine", description: "전략 엔진 전체 성적표(매매법별 기대값·건수·승률·손익비·실전 여부)", input: {},
    run: () => { const s = state(); return (s.neural.engine || []).map(e => `${e.active ? "✅" : e.paused ? "⏸" : "··"} ${e.vkey} | ${e.name} | ${e.mean}R ${e.n}건 승률${e.wr}% 손익비1:${e.rr}`).join("\n"); } },
  { name: "neutron_strategy_library", description: "매매법 키·필터 목록 (neutron_propose_experiment 에 쓸 이름)", input: {},
    run: () => { const s = state(); return `매매법 키:\n${s.lib.strategies.map(r => `${r.key} — ${r.name} (${r.cat}, ${r.tf}분봉, 손익비 ${r.rr})`).join("\n")}\n\n필터:\n${Object.entries(s.lib.filters).map(([k, v]) => `${k} — ${v}`).join("\n")}\n\n최근 진화: ${J(s.neural.evo?.log?.[0] || null)}`; } },
  { name: "neutron_team_verdicts", description: "에이전트 팀 판정(리스크 결정표·TA 평점·차트 패턴·알파 순위·김치/펀딩·ML·자체 AI·경제 캘린더·심리) — 진입 관문이 실제로 읽는 값", input: { coin: { type: "string", description: "BTC 등 (선택)" } },
    run: a => { const s = state(), c = coinId(a.coin); if (!c) return J(s.verdicts);
      return J(Object.fromEntries(Object.entries(s.verdicts).map(([k, v]) => [k, v && typeof v === "object" && v[c] !== undefined ? v[c] : (k === "calendar" || k === "sentiment" ? v : null)]))); } },
  { name: "neutron_risk_policy", description: "리스크 정책(읽기 전용, 코드에 고정): 청산공식 20x+ 프레임워크·실거래 한도·안전 규칙", input: {},
    run: () => { const s = state(); return `${s.policy.rules.map(r => "- " + r).join("\n")}\n\n프레임워크: ${J(s.policy.framework)}\n실거래 한도: ${J(s.policy.live)}`; } },
  { name: "neutron_demo_strategies", description: "에이전트 팀 데모거래 전략 목록(상태·거래수·평가금·레버리지·손절/익절)", input: {},
    run: () => { const s = state(); return s.demo.map(d => `${d.status} | ${d.name} | ${d.market} ${d.tf} | ${d.trades}거래 | ${d.equity} | ${d.lev ?? "—"}x | SL ${d.sl ?? "—"} TP ${d.tp ?? "—"} | ${d.author}`).join("\n") || "데모 전략 없음"; } },
  { name: "neutron_recent_trades", description: "뉴럴 데스크 최근 거래(손익·R·청산 사유·매매법)", input: { limit: { type: "number" } },
    run: a => { const s = state(); return (s.neural.trades || []).slice(0, a.limit || 20).map(t => `${new Date(t.t).toLocaleString("ko-KR")} ${t.ko} ${t.side > 0 ? "롱" : "숏"} ${t.lev}x ${t.name} → ${t.why} ${t.pnl >= 0 ? "+" : ""}${t.pnl}$ (${t.R}R)`).join("\n") || "거래 없음"; } },
  { name: "neutron_coin_research", description: "코인 리서치 카드(1년 범위·현재 위치·7/30/365일 수익·거래소 펀딩) + 고래 카피 신호 + 팀 판정 + 국면", input: { symbol: { type: "string", description: "BTC 등" } }, required: ["symbol"],
    run: a => { const s = state(), ko = String(a.symbol || "").toUpperCase().replace(/USDT$/, ""), sym = ko + "USDT", r = s.neural.research?.[sym], rg = s.neural.regime?.[sym], w = (s.neural.whale?.last || []).find(x => x.sym === sym), id = ko.toLowerCase();
      return `# ${ko} 리서치
국면: ${rg ? `${rg.label} (ADX ${rg.adx ?? "?"} · 4H ${rg.htf > 0 ? "상승" : rg.htf < 0 ? "하락" : "중립"})` : "판단 전"}
`
        + (r ? `1년 범위 ${r.lo} ~ ${r.hi} · 현재 ${r.pos}% 위치 · 7일 ${r.r7}% · 30일 ${r.r30}% · 1년 ${r.r365}%${r.fund ? ` · 펀딩 평균 ${r.fund.avg}% (${r.fund.ko})` : ""}
` : `리서치 카드 없음(앱이 스캔할 때 만들어짐)
`)
        + `고래: ${w ? `${w.dir > 0 ? "순매수" : "순매도"} ${Math.abs(w.netPct)}% (${w.count}건)` : "승인된 신호 없음"} · 고래 흐름 적중 ${s.neural.whale?.trust?.n ? Math.round(s.neural.whale.trust.acc * 100) + "% (" + s.neural.whale.trust.n + "회)" : "학습 중"}
`
        + `팀 판정: 결정표 ${s.verdicts.riskVerdict?.[id]?.act ?? "—"} · TA ${s.verdicts.taRating?.[id]?.label ?? "—"} · 자체AI ${s.verdicts.selfAI?.[id] ? (s.verdicts.selfAI[id].dir > 0 ? "롱 " : s.verdicts.selfAI[id].dir < 0 ? "숏 " : "중립 ") + s.verdicts.selfAI[id].conf + "%" : "—"}${age(s)}`; } },
  { name: "neutron_funding_scan", description: "거래소 간 펀딩비 실시간 스캔(바이낸스·바이빗·OKX·비트겟): 전 거래소 과열·거래소 간 차이·차익 후보(정보용)", input: { symbol: { type: "string", description: "BTCUSDT 등" } }, required: ["symbol"],
    run: async a => { const F = await import(new URL("../lib/fundscan.js", import.meta.url)); return F.fundingText(await F.fundingScan(String(a.symbol || "BTCUSDT").toUpperCase(), async u => (await fetch(u, { signal: AbortSignal.timeout(8000) })).json())); } },
  // brain-mcp 호환 노트 도구 (옵시디언 볼트)
  { name: "brain_get_structure", description: "옵시디언 볼트(GHCoin 뇌) 구조: 폴더별 노트", input: {},
    run: () => { const fsx = walk(VAULT), by = {}; for (const p of fsx) { const d = path.dirname(rel(p)); (by[d] ||= []).push(path.basename(p, ".md")); } return Object.entries(by).map(([d, ns]) => `${d === "." ? "" : d}/ (${ns.length}): ${ns.join(", ")}`).join("\n") || `볼트 없음: ${VAULT}`; } },
  { name: "brain_search_notes", description: "볼트 전문 검색(문맥 포함)", input: { query: { type: "string" }, limit: { type: "number" } }, required: ["query"],
    run: a => { const q = toks(a.query), out = [];
      for (const p of walk(VAULT)) { const t = fs.readFileSync(p, "utf8"), lines = t.split("\n"); lines.forEach((l, i) => { const sc = q.filter(x => l.toLowerCase().includes(x)).length; if (sc) out.push({ sc, s: `${rel(p)}:${i + 1}: ${l.slice(0, 200)}` }); }); }
      return out.sort((x, y) => y.sc - x.sc).slice(0, a.limit || 25).map(x => x.s).join("\n") || "결과 없음"; } },
  { name: "brain_read_note", description: "볼트 노트 읽기 (경로 또는 제목, 예: '코인/BTC')", input: { note: { type: "string" } }, required: ["note"],
    run: a => { const want = String(a.note).replace(/\.md$/, "").replace(/\\/g, "/"), p = walk(VAULT).find(x => rel(x).replace(/\.md$/, "") === want) || walk(VAULT).find(x => path.basename(x, ".md") === path.basename(want));
      if (!p || !path.resolve(p).startsWith(path.resolve(VAULT))) return `노트 없음: ${a.note}`; return fs.readFileSync(p, "utf8").slice(0, 20000); } },
  { name: "brain_find_backlinks", description: "이 노트를 [[위키링크]]로 가리키는 노트들", input: { note: { type: "string" } }, required: ["note"],
    run: a => { const n = String(a.note).replace(/\.md$/, ""), b = path.basename(n); return walk(VAULT).filter(p => { const t = fs.readFileSync(p, "utf8"); return t.includes(`[[${n}`) || t.includes(`[[${b}`) || t.includes(`/${b}|`) || t.includes(`/${b}]]`); }).map(rel).join("\n") || "역링크 없음"; } },
  // 받은 편지함 (앱에 제안 — 허용 3종)
  { name: "neutron_log_note", description: "자체 뇌에 지식 메모를 보냄(앱이 30초 안에 학습). 주문·설정 변경은 불가", input: { text: { type: "string" }, kind: { type: "string", description: "교훈|패턴|지식|관찰|전략" }, coin: { type: "string" } }, required: ["text"],
    run: a => { inbox({ type: "note", text: String(a.text).slice(0, 140), kind: a.kind, coin: a.coin }); return "받은 편지함에 넣음 → 앱이 30초 안에 뇌에 학습"; } },
  { name: "neutron_propose_experiment", description: "매매법 개선·수정·조합 실험 제안 → 다음 자체 백테스트(2시간마다 또는 사무실 진화 업무)에서 앞 70%·뒤 30% 검증, 통과해야 채택. 키·필터는 neutron_strategy_library 참고", input: { base: { type: "string" }, with: { type: "string", description: "조합할 두 번째 매매법 키(선택)" }, filters: { type: "array", items: { type: "string" } }, rr: { type: "number" } }, required: ["base"],
    run: a => { const s = state(), keys = s.lib.strategies.map(r => r.key), fk = Object.keys(s.lib.filters);
      if (!keys.includes(a.base)) return `모르는 매매법 키: ${a.base}\n가능: ${keys.join(", ")}`;
      const gene = { base: a.base, ...(keys.includes(a.with) && a.with !== a.base ? { with: a.with } : {}), ...(Array.isArray(a.filters) ? { filters: a.filters.filter(f => fk.includes(f)).slice(0, 3) } : {}), ...(Number.isFinite(+a.rr) ? { rr: +a.rr } : {}) };
      inbox({ type: "experiment", gene }); return `실험 제안 접수: ${J(gene)} → 다음 보정에서 검증`; } },
  { name: "neutron_add_task", description: "에이전트 팀에 과제 추가(dev 매매법개발 · cdev 커스텀지표 · bot 봇 · opt 최적화 · qrisk 리스크 · news 뉴스 · hq 본부)", input: { team: { type: "string" }, title: { type: "string" }, why: { type: "string" } }, required: ["title"],
    run: a => { inbox({ type: "task", team: a.team || "dev", title: String(a.title).slice(0, 80), why: a.why || "" }); return "과제 접수 → 앱이 30초 안에 팀 과제 목록에 추가"; } },
];

// 받은 편지함에 쓰는 도구(앱에 제안만 함 — 파괴적이지 않음). 나머지는 전부 읽기 전용
const WRITES = new Set(["neutron_log_note", "neutron_propose_experiment", "neutron_add_task"]);
// ── MCP stdio JSON-RPC ──
const send = m => process.stdout.write(JSON.stringify(m) + "\n");
const schema = t => ({ type: "object", properties: t.input || {}, ...(t.required ? { required: t.required } : {}) });
async function handle(msg) {
  const { id, method, params } = msg;
  if (id === undefined || id === null) return;   // 알림(notifications/*)은 응답 없음
  try {
    if (method === "initialize") return send({ jsonrpc: "2.0", id, result: { protocolVersion: params?.protocolVersion || "2024-11-05", capabilities: { tools: {} }, serverInfo: { name: "neutron", version: VERSION },
      instructions: "GH Coin 앱의 뇌(뉴트론). 읽기 도구로 상태·기억·성적·판정을 보고, 제안은 neutron_log_note / neutron_propose_experiment / neutron_add_task 로만 보낸다. 주문 도구는 없다(안전 규칙)." } });
    if (method === "ping") return send({ jsonrpc: "2.0", id, result: {} });
    if (method === "tools/list") return send({ jsonrpc: "2.0", id, result: { tools: TOOLS.map(t => { const w = WRITES.has(t.name), net = t.name === "neutron_funding_scan";
      return { name: t.name, description: t.description, inputSchema: schema(t), annotations: { title: t.name, readOnlyHint: !w, destructiveHint: false, idempotentHint: !w, openWorldHint: net } }; }) } });
    if (method === "tools/call") {
      const t = TOOLS.find(x => x.name === params?.name); if (!t) return send({ jsonrpc: "2.0", id, error: { code: -32602, message: `알 수 없는 도구: ${params?.name}` } });
      try { const text = String(await t.run(params.arguments || {})); return send({ jsonrpc: "2.0", id, result: { content: [{ type: "text", text }] } }); }
      catch (e) { return send({ jsonrpc: "2.0", id, result: { content: [{ type: "text", text: "오류: " + (e?.message || e) }], isError: true } }); }
    }
    if (method === "resources/list") return send({ jsonrpc: "2.0", id, result: { resources: [] } });
    if (method === "prompts/list") return send({ jsonrpc: "2.0", id, result: { prompts: [] } });
    send({ jsonrpc: "2.0", id, error: { code: -32601, message: `지원하지 않는 메서드: ${method}` } });
  } catch (e) { send({ jsonrpc: "2.0", id, error: { code: -32603, message: String(e?.message || e) } }); }
}
const rl = readline.createInterface({ input: process.stdin });
rl.on("line", l => { if (!l.trim()) return; let m; try { m = JSON.parse(l); } catch (e) { return send({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "parse error" } }); } handle(m); });
