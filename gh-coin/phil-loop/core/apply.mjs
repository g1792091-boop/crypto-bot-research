#!/usr/bin/env node
// 🦫 정책 적용 요청 — strategy/policy.json 을 검사해 GH Coin 앱의 받은 편지함(../neutron/inbox.jsonl)으로 보낸다.
// 보호 파일: 자기개선 루프(Claude Code)는 이 파일을 고치면 안 된다(loop 가 되돌림).
// 앱이 다시 한 번 범위를 검사하므로, 여기서 범위를 넘겨도 앱에서 거부된다. 주문·실거래·엔진 설정은 이 경로로 바꿀 수 없다.
// 쓰는 법: node core/apply.mjs
import fs from "fs";
import path from "path";
import { execSync } from "child_process";
import { fileURLToPath } from "url";
const HERE = path.dirname(fileURLToPath(import.meta.url)), ROOT = path.resolve(HERE, "..");
const INBOX = process.env.GHCOIN_INBOX || path.resolve(ROOT, "..", "neutron", "inbox.jsonl");
const BOUNDS = { aiConf: [60, 90], aiPerDay: [0, 5], riskScale: [0.5, 1] };
const COINS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB"], HOLD = ["htf", "align", "streak", "adx", "vol", "rsiN", "rsiX", "fng", "ltf", "scalp"];
let P; try { P = JSON.parse(fs.readFileSync(path.join(ROOT, "strategy", "policy.json"), "utf8")); } catch (e) { console.log("❌ strategy/policy.json 을 읽지 못함: " + e.message); process.exit(1); }
const out = {}, errs = [];
for (const [k, [lo, hi]] of Object.entries(BOUNDS)) if (P[k] != null) { const v = +P[k]; if (Number.isFinite(v) && v >= lo && v <= hi) out[k] = v; else errs.push(`${k}=${P[k]} (허용 ${lo}~${hi})`); }
if (P.exclude != null) { if (!Array.isArray(P.exclude) || P.exclude.some(x => !COINS.includes(String(x).toUpperCase()))) errs.push(`exclude 는 ${COINS.join("/")} 중에서만`); else out.exclude = P.exclude.map(x => String(x).toUpperCase()); }
if (P.hold) { if (!HOLD.includes(P.hold.rule)) errs.push(`hold.rule 은 ${HOLD.join("/")} 중 하나`); else out.hold = { rule: P.hold.rule, ...(typeof P.hold.on === "boolean" ? { on: P.hold.on } : {}), ...(P.hold.p != null ? { p: P.hold.p } : {}) }; }
const extra = Object.keys(P).filter(k => !k.startsWith("_") && !["aiConf", "aiPerDay", "riskScale", "exclude", "hold"].includes(k)); if (extra.length) errs.push(`허용되지 않은 손잡이: ${extra.join(", ")} (레버리지·손절 규칙·스타일·실거래는 사람만 바꿈 → journal/proposals.md 에 쓰기)`);
if (errs.length) { console.log("❌ 정책 검사 실패 — 보내지 않음:\n  " + errs.join("\n  ")); process.exit(1); }
let rev = ""; try { rev = execSync("git rev-parse --short HEAD", { cwd: ROOT }).toString().trim(); } catch (e) {}
const item = { type: "policy", policy: out, rev, by: "Claude Code(자기개선 루프)", why: String(P._why || "").slice(0, 160), t: Date.now() };
fs.mkdirSync(path.dirname(INBOX), { recursive: true }); fs.appendFileSync(INBOX, JSON.stringify(item) + "\n");
console.log(`✅ 정책 적용 요청 보냄(rev ${rev || "-"}) → ${INBOX}\n   ${JSON.stringify(out)}\n   앱(GHCoin.exe)이 켜져 있으면 30초 안에 읽고, 뉴럴 데스크 피드에 '🦫 자기개선 루프 정책 적용'으로 남깁니다. 범위 밖 값은 앱에서도 거부됩니다.`);
