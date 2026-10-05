// 🧠 뉴트론 브리지 — 앱 안의 뇌(자체 뇌 + 뉴럴 데스크 + 에이전트 팀 판정)를 디스크로 내보내
//   ① Claude Code / Claudian(옵시디언) 이 MCP 로 읽고  ② 옵시디언 볼트(마크다운·위키링크)로 보고  ③ 받은 편지함으로 제안을 돌려받는다.
// 폴더: 문서/GHNano 사무실/neutron (state.json · inbox.jsonl) + 문서/GHNano 사무실/GHCoin 뇌 (옵시디언 볼트)
// 안전: 내보내기는 읽기 전용 사본. 받은 편지함은 '지식 메모 · 매매법 실험 제안 · 팀 과제' 세 가지만 받는다 — 주문·설정 변경·키는 절대 없음.
import { LAUNCHER, codeCall, webGet } from "../nuri-ai/engine.js";

const VAULT = "GHCoin 뇌", DIR = "neutron";
const VERDICT_KEYS = { riskVerdict: "coinRiskVerdict", taRating: "coinTARating", patterns: "coinPatterns", alpha: "coinAlpha", data: "coinDataV", ml: "coinML", selfAI: "coinSelfAI", calendar: "coinCalendar", sentiment: "coinSentiment", liveEntry: "coinLiveEntry" };
const readJ = (k, d = null) => { try { return JSON.parse(localStorage.getItem(k) || "null") ?? d; } catch (e) { return d; } };
const W = (path, content) => codeCall("write", { ws: "office", path, content });
const day = (t = Date.now()) => new Date(t).toLocaleDateString("sv-SE");
let started = false, lastErr = "", stats = { exported: 0, vault: 0, inbox: 0, at: 0 };
export const neutronStatus = () => ({ on: started, ...stats, err: lastErr });

// ── 상태 사본 ──
export async function snapshot() {
  const N = await import("./neural.js"), BR = await import("./brain.js"), ENG = await import("./strategies.js");
  const s = N.state(), brain = BR.dump();
  let book = []; try { const P = await import("../nuri-ai/paper.js"); book = (await P.loadBook()).strategies.map(x => ({ id: x.id, name: x.name, market: x.market, tf: x.tf, status: x.status, author: x.author, lane: x.lane || "std", trades: (x.trades || []).length, equity: Math.round(P.equityOf(x)), lev: x.spec?.risk?.leverage ?? null, sl: x.spec?.risk?.stop_loss_pct ?? null, tp: x.spec?.risk?.take_profit_pct ?? null })); } catch (e) {}
  let limits = null; try { const L = await import("../nuri-ai/live.js"); const c = L.liveCfg?.() || {}; limits = { limits: c.limits || null, halted: !!c.halted }; } catch (e) {}
  const verdicts = Object.fromEntries(Object.entries(VERDICT_KEYS).map(([k, key]) => [k, readJ(key)]));
  return {
    v: 1, t: Date.now(), app: "GH Coin",
    neural: { equity: s.equity, bankroll: s.bankroll, pnl: s.pnl, drawdown: s.drawdown, fills: s.fills, winRate: s.winRate, heat: s.heat, dayPnl: s.dayPnl, riskMode: s.riskMode,
      positions: (s.pos || []).map(p => ({ sym: p.sym, side: p.side > 0 ? "long" : "short", lev: p.lev, entry: p.entry, sl: p.sl, tp: p.tp, strategy: p.name, riskPct: p.riskPct })),
      regime: s.regime, news: s.news, review: s.review, review2: s.review2, research: s.research, whale: s.whale, cfg: s.cfg, dayN: s.dayN, calls: s.calls || null, engine: (s.engine || []).slice(0, 40), setups: s.setups || [], evo: s.evo, trades: (s.trades || []).slice(0, 40), feed: (s.feed || []).slice(0, 20) },
    brain, verdicts, demo: book,
    policy: { framework: ENG.FW, live: limits, rules: ["AI 는 주문하지 않는다(주문은 live.js 코드가 한도·승인 안에서만)", "실거래 기본 꺼짐 · 테스트넷 먼저", "최소 20배·손절 ≤ 청산거리 40%·1회 리스크 0.5~1%·동시 리스크 4%·일일 손실 3%"] },
    lib: { strategies: ENG.LIB.map(r => ({ key: r.key, name: r.name, cat: r.cat, tf: r.tf, rr: r.rr })), filters: Object.fromEntries(Object.entries(ENG.FILTERS).map(([k, f]) => [k, f.ko])) },
  };
}

// ── 옵시디언 볼트 (위키링크로 서로 연결된 노트) ──
const coinOf = m => (m.coin || "").replace(/USDT$/, "").toUpperCase();
const esc = t => String(t ?? "").replace(/\|/g, "/").replace(/\n/g, " ");
export function vaultNotes(S) {
  const now = new Date(S.t).toLocaleString("ko-KR"), n = S.neural, B = S.brain, out = {};
  const coins = [...new Set(["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", ...B.mem.map(coinOf).filter(Boolean)])];
  const types = [...new Set(B.mem.map(m => m.type || "관찰"))];
  out["00 홈.md"] = `# 🧠 GHCoin 뇌 (뉴트론)\n_자동 생성 · ${now} · 앱이 10분마다 다시 씀 (직접 고친 내용은 덮어써짐 → 메모는 [[받은 편지함 사용법]] 참고)_\n\n`
    + `## 지금\n- 자본 $${n.equity} (시작 $${n.bankroll}) · 낙폭 ${n.drawdown}% · 거래 ${n.fills}회 승률 ${n.winRate}% · 동시 리스크 ${n.heat}%\n- 뇌 지능 ${B.iq.score}/100 (정확도 ${B.iq.acc}% · ${B.iq.n}판) · 기억 ${B.mem.length}개\n\n`
    + `## 지도\n- 코인: ${coins.map(c => `[[코인/${c}|${c}]]`).join(" · ")}\n- 지식: ${types.map(t => `[[지식/${t}|${t}]]`).join(" · ")}\n- 뇌: [[뇌/핵심 규칙·교훈·추천 채점]]
- 매매법: [[매매법/전략 엔진]] · [[매매법/매매법 진화]] · [[매매법/검증된 셋업]]\n- 리스크: [[리스크/정책]] · [[리스크/학습된 리스크·시간대]]\n- 에이전트 팀: [[에이전트팀/데모 전략]] · [[에이전트팀/팀 판정]]\n- 일지: [[일지/${day(S.t)}]]\n- ✍ 내가 쓰는 메모(→ 뇌가 학습): [[내 메모/사용법]]\n`;
  for (const t of types) out[`지식/${t}.md`] = `# ${t}\n[[00 홈]]\n\n` + B.mem.filter(m => (m.type || "관찰") === t).slice(0, 120).map(m => `- ${m.text} ${coinOf(m) ? `[[코인/${coinOf(m)}|${coinOf(m)}]]` : ""}${m.regime ? ` #${String(m.regime).replace(/\s/g, "_")}` : ""} _(가중 ${m.w}·확인 ${m.hits}회·${m.model || "?"})_`).join("\n");
  for (const c of coins) { const sym = c + "USDT", id = c.toLowerCase(), rg = n.regime?.[sym], V = S.verdicts;
    const vd = [["리스크 결정표", V.riskVerdict?.[id]?.act], ["TA 평점", V.taRating?.[id]?.label], ["차트 패턴", V.patterns?.[id] ? `${V.patterns[id].dir > 0 ? "상승" : V.patterns[id].dir < 0 ? "하락" : "중립"} ${(V.patterns[id].names || []).join(",")}` : null],
      ["알파 순위", V.alpha?.[id] ? `${V.alpha[id].rank}/${V.alpha[id].n}` : null], ["자체 AI", V.selfAI?.[id] ? `${V.selfAI[id].dir > 0 ? "롱" : V.selfAI[id].dir < 0 ? "숏" : "중립"} ${V.selfAI[id].conf}%` : null], ["ML", V.ml?.[id] ? `상승확률 ${Math.round((V.ml[id].prob ?? 0) * 100)}%` : null]].filter(x => x[1] != null);
    out[`코인/${c}.md`] = `# ${c}\n[[00 홈]]\n\n- 국면: ${rg ? `${rg.label} (ADX ${rg.adx ?? "?"} · 4H 추세 ${rg.htf > 0 ? "상승" : rg.htf < 0 ? "하락" : "중립"})` : "판단 전"}\n${vd.map(([k, v]) => `- ${k}: ${esc(v)}`).join("\n")}\n\n## 기억\n`
      + (B.mem.filter(m => coinOf(m) === c).slice(0, 40).map(m => `- (${m.type}) ${m.text} → [[지식/${m.type}|${m.type}]]`).join("\n") || "- (아직 없음)"); }
  out["매매법/전략 엔진.md"] = `# 전략 엔진 (자체 백테스트 + 실전 최근 20건)\n[[00 홈]] · 실전 기준: 기대값 > +0.1R\n\n| 상태 | 매매법 | 봉 | 기대값 | 건수 | 승률 | 손익비 |\n|---|---|---|---|---|---|---|\n`
    + (n.engine || []).map(e => `| ${e.active ? "✅ 실전" : e.paused ? "⏸ 정지" : "대기"} | ${esc(e.name)} | ${e.tf} | ${e.mean}R | ${e.n} | ${e.wr}% | 1:${e.rr} |`).join("\n");
  out["매매법/매매법 진화.md"] = `# 🧬 매매법 진화 (개선·수정·조합)\n[[00 홈]] · 채택 ${n.evo?.n ?? 0}개 · 앞 70% 선택 → 뒤 30% 검증 통과만\n\n` + (n.evo?.log || []).map(L => `## ${new Date(L.t).toLocaleString("ko-KR")}\n변형 ${L.tested}개 → 학습구간 통과 ${L.passedIS} → 채택 ${(L.adopted || []).length}\n` + (L.adopted || []).map(a => `- [${a.src}] ${a.name}: 원본 ${a.base}R → 검증 ${a.oos}R (${a.n}건)`).join("\n")).join("\n\n");
  out["매매법/검증된 셋업.md"] = `# 검증된 셋업 순위 (기대값 × 승률 × 신뢰도)\n[[00 홈]]\n\n| 순위 | 매매법 | 봉 | 점수 | 기대값 | 승률 | 건수 |\n|---|---|---|---|---|---|---|\n` + (n.setups || []).map((x, i) => `| ${i + 1} | ${esc(x.name)} | ${x.tf} | ${x.score} | ${x.mean}R | ${x.wr}% | ${x.n} |`).join("\n");
  const P = S.policy;
  out["리스크/정책.md"] = `# 리스크 정책 (읽기 전용 — 코드에 고정, AI 가 바꿀 수 없음)\n[[00 홈]]\n\n${P.rules.map(r => "- " + r).join("\n")}\n\n## 청산공식 프레임워크\n\`\`\`json\n${JSON.stringify(P.framework, null, 2)}\n\`\`\`\n## 실거래 한도 (live.js)\n\`\`\`json\n${JSON.stringify(P.live, null, 2)}\n\`\`\``;
  const hours = Object.entries(B.hours || {}).filter(([, h]) => h.n >= 3).map(([hr, h]) => `| ${hr}시 | ${h.n} | ${Math.round(h.wins / h.n * 100)}% | ${h.pnl.toFixed(2)} |`).join("\n");
  out["리스크/학습된 리스크·시간대.md"] = `# 학습된 리스크·시간대\n[[00 홈]] · [[리스크/정책]]\n\n## 시간대별 성적\n| 시간 | 거래 | 승률 | 손익$ |\n|---|---|---|---|\n${hours || "| — | | | |"}\n\n## 손절 함정 (비슷한 자리 회피)\n` + ((B.traps || []).slice(0, 30).map(t => `- ${esc(t.coin || "")} ${esc(t.regime || "")} ${t.dir > 0 ? "롱" : "숏"} ROE ${t.roe ?? ""}`).join("\n") || "- (없음)");
  { const mem = B.mem || [], st = B.st || {}, C = n.calls || {}, ln = (t) => mem.filter(m => m.type === t).slice(0, 12).map(m => `- ${esc(m.text)} _(강도 ${m.w} · ${m.hits}회)_`).join("\n") || "- 아직 없음";
    out["뇌/핵심 규칙·교훈·추천 채점.md"] = `# 🧠 뇌가 진입 전에 쓰는 것\n[[00 홈]] · 누적: 교훈 ${st.lessons || 0} · 함정 ${st.traps || 0} · 승격 ${st.promoted || 0} · 진입 차단 ${st.avoided || 0} · 리스크 절반 ${st.softened || 0} · 망각 ${st.forgot || 0}\n\n## 핵심 규칙 (같은 결과 3회↑)\n${ln("핵심")}\n\n## 교훈\n${ln("교훈")}\n\n## ⚡ 손매매 추천 채점 (시장가 · 실시간 진입)\n익절1 먼저 ${C.wr ?? "—"}% · 채점 ${C.done || 0}건 · 합계 ${C.sumR || 0}R · 추적 중 ${C.open || 0}\n\n| 코인 | 방향 | 출처 | 등급 | 결과 | R |\n|---|---|---|---|---|---|\n`
      + (C.list || []).map(c => `| ${c.ko} | ${c.side > 0 ? "롱" : "숏"} | ${c.src} | ${c.grade || ""} | ${c.res || "추적 중"} | ${c.R ?? ""} |`).join("\n"); }
  out["에이전트팀/데모 전략.md"] = `# 에이전트 팀 데모 전략\n[[00 홈]]\n\n| 상태 | 전략 | 코인 | 봉 | 거래 | 평가금 | 레버 | 손절/익절 | 개발 |\n|---|---|---|---|---|---|---|---|---|\n` + S.demo.map(d => `| ${d.status} | ${esc(d.name)} | [[코인/${String(d.market).replace(/USDT$/, "")}\\|${d.market}]] | ${d.tf} | ${d.trades} | ${d.equity} | ${d.lev ?? "—"} | ${d.sl ?? "—"}/${d.tp ?? "—"} | ${esc(d.author)} |`).join("\n");
  out["에이전트팀/팀 판정.md"] = `# 팀 판정 (진입 관문이 실제로 읽는 값)\n[[00 홈]]\n\n` + Object.entries(S.verdicts).map(([k, v]) => `## ${k}\n\`\`\`json\n${JSON.stringify(v, null, 1)?.slice(0, 1500)}\n\`\`\``).join("\n");
  const todays = (n.trades || []).filter(t => day(t.t || t.t1 || S.t) === day(S.t));
  out[`일지/${day(S.t)}.md`] = `# 거래 일지 ${day(S.t)}\n[[00 홈]]\n\n` + (todays.map(t => `- ${t.ko || t.sym} ${t.side > 0 ? "롱" : "숏"} ${t.lev ?? ""}x · ${esc(t.name || t.strategy || "")} · ${t.why || ""} · ${t.pnl >= 0 ? "+" : ""}${(+t.pnl || 0).toFixed(2)}$ (${(+t.R || 0).toFixed(2)}R)`).join("\n") || "- 오늘 거래 없음") + `\n\n## 최근 활동\n` + (n.feed || []).slice(0, 15).map(f => `- ${esc(f.text)}`).join("\n");
  out["받은 편지함 사용법.md"] = `# 받은 편지함 (Claude Code · Claudian → 앱)\n[[00 홈]]\n\n이 볼트의 노트는 앱이 다시 쓰므로, 앱에 전하고 싶은 것은 뉴트론 MCP 도구로 보낸다:\n- \`neutron_log_note\` — 지식 메모 → 자체 뇌에 학습\n- \`neutron_propose_experiment\` — 매매법 개선·수정·조합 실험 → 다음 자체 백테스트에서 검증, 통과해야 채택\n- \`neutron_add_task\` — 에이전트 팀 과제\n\n주문·설정 변경·키 관련 요청은 받지 않는다(안전 규칙).`;
  return out;
}

const CLAUDE_MD = `# GHCoin 뇌 (뉴트론) — Claude Code · Claudian 작업 규칙

이 폴더는 GH Coin 앱이 자동으로 쓰는 옵시디언 볼트다. 사용자와는 한국어로 짧게.

- 앱 상태·뇌 기억·팀 판정·매매법 성적은 **neutron MCP 도구**로 읽는다 (neutron_status, neutron_query_knowledge, neutron_top_setups, neutron_learned_winrates, neutron_team_verdicts, neutron_risk_policy, neutron_funding_scan, brain_search_notes, brain_read_note …).
- 앱에 전할 것은 neutron_log_note / neutron_propose_experiment / neutron_add_task 로만 보낸다. 노트를 직접 고쳐도 10분 뒤 앱이 덮어쓴다.
- **안전 규칙(변경 금지)**: AI 는 주문하지 않는다. 실거래 기본 꺼짐·테스트넷 먼저. 주문·레버리지 한도·API 키를 바꾸는 요청은 거절한다.
- 숫자는 도구가 준 값만 쓰고, 수익은 확률로 말한다(보장 없음).
`;

export async function installFiles(force) {
  if (!force && sessionStorage.getItem("neutronInstalled")) return;
  // MCP 서버 스크립트를 볼트 안 숨김 폴더로 복사 (exe 사용자도 저장소 없이 쓰도록)
  for (const [src, dst] of [["mcp/neutron-mcp.mjs", ".neutron/mcp/neutron-mcp.mjs"], ["lib/fundscan.js", ".neutron/lib/fundscan.js"]]) {
    const r = await fetch(new URL("./" + src, import.meta.url), { cache: "no-store" }); if (r.ok) await W(`${VAULT}/${dst}`, await r.text()); }
  let abs = ""; try { const e = await codeCall("exec", { ws: "office", command: "cd", timeout: 5 }); abs = String(e.output || "").trim().split(/\r?\n/).pop(); } catch (e) {}
  const script = abs ? `${abs}\\${VAULT}\\.neutron\\mcp\\neutron-mcp.mjs` : "./.neutron/mcp/neutron-mcp.mjs";
  await W(`${VAULT}/.mcp.json`, JSON.stringify({ mcpServers: { neutron: { command: "node", args: [script], env: abs ? { NEUTRON_DIR: abs } : {} } } }, null, 2));
  await W(`${VAULT}/CLAUDE.md`, CLAUDE_MD);
  await W(`${MEMO}/사용법.md`, "# 내 메모 (옵시디언 → 뇌)\n\n이 폴더에 노트를 쓰면 GH Coin 이 10분 안에 읽어 자체 뇌에 학습합니다.\n- 한 줄에 하나씩 쓰면 각각 기억이 됩니다 (예: '- BTC 는 미국장 개장 직후 가짜 돌파가 많다').\n- 손절·실패·주의·금지 같은 말이 있으면 '교훈'으로, 아니면 '지식'으로 저장합니다.\n- 코인 이름(BTC·ETH…)을 쓰면 그 코인 기억에 연결됩니다.\n- 이 폴더는 앱이 덮어쓰지 않습니다.\n");
  try { sessionStorage.setItem("neutronInstalled", "1"); localStorage.setItem("neutronPath", abs); } catch (e) {}
}

export async function exportState() { const S = await snapshot(); await W(`${DIR}/state.json`, JSON.stringify(S)); stats.exported++; stats.at = Date.now(); return S; }
export async function writeVault(S) { S ||= await snapshot(); const notes = vaultNotes(S); for (const [p, c] of Object.entries(notes)) await W(`${VAULT}/${p}`, c); stats.vault++; try { await ingestMemos(); } catch (e) {} return Object.keys(notes).length; }

// ── 옵시디언 → 뇌: 볼트의 '내 메모' 폴더에 사용자·Claudian 이 쓴 노트를 읽어 자체 뇌에 학습 (바뀐 파일만, 앱은 이 폴더를 덮어쓰지 않음) ──
const MEMO = `${VAULT}/내 메모`;
const hashOf = t => { let h = 5381; for (let i = 0; i < t.length; i++) h = ((h << 5) + h + t.charCodeAt(i)) >>> 0; return h.toString(36); };
export async function ingestMemos() {
  let files = []; try { files = ((await codeCall("glob", { ws: "office", pattern: `${MEMO}/**` })).files || []).filter(f => String(f).startsWith(MEMO + "/") && /\.md$/i.test(f) && !/사용법\.md$/.test(f)); } catch (e) { return 0; }
  let seen = {}; try { seen = JSON.parse(localStorage.getItem("neutronMemoSeen") || "{}"); } catch (e) {}
  const BR = await import("./brain.js"); let n = 0;
  for (const f of files.slice(0, 30)) {
    let t = ""; try { t = (await codeCall("raw", { ws: "office", path: f })).content || ""; } catch (e) { continue; }
    const h = hashOf(t); if (seen[f] === h) continue; seen[f] = h;
    const title = (t.match(/^#\s+(.+)$/m)?.[1] || f.split("/").pop().replace(/\.md$/i, "")).trim();
    const coin = (title + " " + t).match(/\b(BTC|ETH|SOL|XRP|DOGE|BNB)\b/i)?.[1]?.toUpperCase() || "";
    const lines = t.split(/\r?\n/).filter(l => !/^\s*(#|\||```|---)/.test(l)).map(l => l.replace(/^[-*#>\s]+/, "").replace(/\[\[([^\]|]+)(\|[^\]]+)?\]\]/g, "$1").trim()).filter(l => l.length >= 6 && !/^---/.test(l)).slice(0, 6);
    for (const l of lines) { BR.learn({ type: /손절|실패|주의|하지 마|금지/.test(l) ? "교훈" : "지식", coin, text: l.slice(0, 140), model: "옵시디언:" + title.slice(0, 20), w: 1.4 }); n++; }
  }
  try { localStorage.setItem("neutronMemoSeen", JSON.stringify(seen)); } catch (e) {}
  if (n) { stats.memos = (stats.memos || 0) + n; try { (await import("./coin-office.js")).addNote("hq", `🧠 옵시디언 '내 메모' ${n}줄을 자체 뇌에 학습`, "뉴트론"); } catch (e) {} }
  return n;
}

// ── 받은 편지함: Claude Code·Claudian 이 MCP 로 보낸 제안을 앱에 반영 (허용 3종만) ──
export async function pollInbox() {
  let raw = ""; try { raw = (await codeCall("raw", { ws: "office", path: `${DIR}/inbox.jsonl` })).content || ""; } catch (e) { return 0; }
  if (!raw.trim()) return 0;
  await W(`${DIR}/inbox.jsonl`, "");   // 먼저 비워 중복 반영 방지
  const items = raw.split(/\r?\n/).filter(Boolean).slice(0, 30).map(l => { try { return JSON.parse(l); } catch (e) { return null; } }).filter(Boolean);
  const BR = await import("./brain.js"), N = await import("./neural.js"), O = await import("./coin-office.js"), done = [];
  try { await O.loadLog?.(); } catch (e) {}
  for (const it of items) try {
    const by = String(it.by || "Claude").slice(0, 30);
    if (it.type === "note" && it.text) { BR.learn({ type: ["교훈", "패턴", "지식", "관찰", "전략"].includes(it.kind) ? it.kind : "지식", coin: String(it.coin || "").toUpperCase().slice(0, 6), text: String(it.text).slice(0, 140), model: "MCP:" + by, w: 1.2 }); done.push("메모"); }
    else if (it.type === "experiment" && it.gene?.base) { if (N.proposeEvo({ base: it.gene.base, ...(it.gene.with ? { with: it.gene.with, win: 3 } : {}), ...(Array.isArray(it.gene.filters) ? { filters: it.gene.filters.slice(0, 3) } : {}), ...(Number.isFinite(+it.gene.rr) ? { rr: Math.max(1.3, Math.min(3, +it.gene.rr)) } : {}), src: "MCP 제안" })) done.push("실험"); }
    else if (it.type === "task" && it.title) { O.addTask({ team: String(it.team || "dev").slice(0, 10), title: String(it.title).slice(0, 80), why: String(it.why || "").slice(0, 160), owner: "" }); done.push("과제"); }
  } catch (e) {}   // 그 외 종류(주문 등)는 무시
  if (done.length) { stats.inbox += done.length; try { O.addNote("hq", `🧠 뉴트론 받은 편지함: ${done.join(", ")} 반영 (Claude Code·Claudian 제안)`, "뉴트론"); } catch (e) {} }
  return done.length;
}

export function startNeutron() {
  if (started || !LAUNCHER.on) return false; started = true;
  const safe = f => () => f().then(() => { lastErr = ""; }).catch(e => { lastErr = String(e?.message || e).slice(0, 80); });
  setTimeout(safe(async () => { await installFiles(); const S = await exportState(); await writeVault(S); }), 20e3);
  setInterval(safe(exportState), 60e3);
  setInterval(safe(pollInbox), 30e3);
  setInterval(safe(() => writeVault()), 10 * 60e3);
  return true;
}
// 거래소 간 펀딩 스캔 (앱 안에서 쓸 때)
export async function fundingScan(sym) { const F = await import("./lib/fundscan.js"); return F.fundingScan(sym, u => webGet(u, "json")); }
