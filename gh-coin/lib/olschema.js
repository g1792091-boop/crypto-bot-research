// 🧾 Ollama 구조화 출력 — 로컬 모델에 JSON '스키마'를 직접 넘겨, 정해진 칸·값(enum) 밖의 글자를 아예 못 쓰게 한다.
//   왜: 공용 엔진(engine.js, 보호 파일)은 OpenAI 호환 주소에 "JSON 모드"만 건다. JSON 모양은 지켜도 칸 이름이 틀리거나
//   보유하지 않은 코인·모르는 결정을 쓰는 일이 남는다. Ollama 0.5+ 의 /api/chat format=스키마 는 그 자체를 막는다.
//   개념 출처: tripolskypetr/backtest-kit(@backtest-kit/ollama 의 format=JSON 스키마 강제) · Ollama structured outputs 문서. 코드 복사 없음.
import { apiBase } from "../../nuri-ai/engine.js";

const ST = { ok: 0, fail: 0, last: "" };
export const schemaStats = () => ({ ...ST });

/** 로컬 Ollama 모델에 스키마 강제 호출. 성공하면 {text, json} · 실패하면 throw */
export async function olJSON({ model, messages, schema, maxTokens = 300, temperature = 0.2, timeoutMs = 240e3, signal } = {}) {
  const ctl = new AbortController(), to = setTimeout(() => ctl.abort(), timeoutMs);
  if (signal) { if (signal.aborted) ctl.abort(); else signal.addEventListener("abort", () => ctl.abort(), { once: true }); }
  try {
    const r = await fetch(apiBase("ollama") + "/api/chat", { method: "POST", headers: { "content-type": "application/json" }, signal: ctl.signal,
      body: JSON.stringify({ model, messages: messages.map(m => ({ role: m.role, content: m.content })), stream: false, format: schema, keep_alive: "10m", options: { num_predict: maxTokens, temperature } }) });
    if (!r.ok) { const e = new Error(`Ollama ${r.status}`); e.status = r.status; throw e; }
    const j = await r.json(), text = String(j.message?.content || "");
    const json = JSON.parse(text);
    ST.ok++; return { text, json };
  } catch (e) { ST.fail++; ST.last = String(e?.message || e).slice(0, 60); throw e; }
  finally { clearTimeout(to); }
}

/** 대상이 로컬(Ollama)이면 스키마 강제, 아니면(또는 실패하면) 기존 brainStream(JSON 모드)으로. 반환 {raw, route, schema:bool} */
export async function askJSON(brainStream, { target, messages, schema, maxTokens = 300, temperature = 0.2, role = "fast", fallback = true }) {
  if (target?.id === "ollama" && schema) {
    try { const r = await olJSON({ model: target.model, messages, schema, maxTokens, temperature }); return { raw: r.text, route: target, schema: true }; }
    catch (e) { /* 스키마를 모르는 옛 Ollama · 시간초과 → 기존 방식으로 한 번 더 */ }
  }
  let raw = "";
  const route = await brainStream({ messages, role, target, fallback, json: true, maxTokens, temperature, noThink: true, onContent: d => raw += d, onThink: () => {} });
  return { raw, route, schema: false };
}

// ── 뉴럴 데스크용 스키마 ──
export const APPROVE_SCHEMA = { type: "object", properties: { approve: { type: "boolean" }, risk: { type: "number", enum: [0.5, 1] }, reason: { type: "string" } }, required: ["approve", "risk", "reason"] };
export const SCAN_SCHEMA = { type: "object", properties: { bias: { type: "integer", enum: [-1, 0, 1] }, conf: { type: "integer", minimum: 0, maximum: 100 }, note: { type: "string" } }, required: ["bias", "conf", "note"] };
export const NEWS_SCHEMA = { type: "object", properties: { score: { type: "integer", enum: [-2, -1, 0, 1, 2] }, event: { type: "boolean" }, reason: { type: "string" } }, required: ["score", "event", "reason"] };
/** 포지션 관리: 보유 코인만(enum) · 허용 결정만(enum) */
export const posSchema = syms => ({ type: "object", properties: { decisions: { type: "array", minItems: syms.length, maxItems: Math.max(1, syms.length), items: { type: "object", properties: {
  symbol: { type: "string", enum: syms }, decision: { type: "string", enum: ["hold", "keep_tp", "close", "breakeven", "run", "trail", "tp"] }, price: { type: "number" }, reason: { type: "string" } }, required: ["symbol", "decision", "reason"] } } }, required: ["decisions"] });
