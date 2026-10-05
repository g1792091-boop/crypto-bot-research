// Builder D's shared agent helpers (office, rooms, digest, debate): Korean names of message kinds / meeting results /
// stances, short staff labels and avatars, a model rule (JSON) turned into a readable Korean line with its raw text
// folded away, the agents' running state, the unread dot of the rooms tab. Used only by the 에이전트 screens.
// Every string here becomes a TEXT node (h()); nothing is parsed as HTML. Model text is shown as written.
import {h, ui, fmt, local, setBadge, hueOf, TEAM_HUE, figure} from "../core/pb.js";
// Its css (rooms-kit.css) is @imported by office.css, rooms.css, digest.css and debate.css.

// ---------------------------------------------------------------- words
export const KIND_KO = {analysis: "분석", challenge: "반론", expert: "전문가 의견", revision: "최종안", verdict: "판정",
  summary: "요약", action: "실행", code_result: "코드 계산", decision: "결정", owner: "두 분", system: "알림", trigger: "회의 시작"};
export const SPEAKING = new Set(["analysis", "challenge", "expert", "revision", "verdict", "summary"]);
/** meeting results (rounds.status): [Korean, pill class] */
export const STATUS = {done: ["결정", "done"], no_action: ["행동 없음", "none"], failed: ["멈춤", "bad"],
  stopped_budget: ["한도로 멈춤", "warn"], running: ["진행 중", "live"]};
export const STANCE = {agree: ["동의", "good"], disagree: ["반대", "bad"], add: ["보완", "accent"]};
export const VERDICT_KO = {agree: "동의", disagree: "반대", needs_test: "시험 필요", unreadable: "읽을 수 없음"};
/** the step strip of a meeting: lit only for the kinds that were really spoken */
export const STEPS = [{id: "analysis", label: "분석"}, {id: "challenge", label: "반론"}, {id: "revision", label: "최종안"}, {id: "verdict", label: "판정"}];
export const ACTION_KO = {note: "메모", hypothesis: "가설", request_test: "5년 시험", propose_copy: "복제 제안",
  flag_owners: "두 분께 알림", no_action: "행동 없음", newlab_tests: "새 매매법 시험"};
// short avatar labels of the roles that speak in rooms (others: the first letters of the name)
export const ROLE_AV = {validator: "검증", approver: "승인", devils_advocate: "반론", entry_timing: "진입", exit_timing: "청산",
  whatif: "가정", strategist: "전략", team_lead: "팀장", chart_regime: "차트", derivs_flow: "파생", ops_auditor: "감사",
  pnl_reviewer: "복기", risk_officer: "위험", data_quality: "품질", code_reviewer: "코드", league_referee: "심판",
  rule_keeper: "규칙", performance: "성과", researcher: "연구", bull: "낙관", bear: "비관", macro_corr: "매크로",
  news_calendar: "뉴스", combo_synergy: "조합", tf_compare: "봉비교", coin_compare: "코인", regime_perf: "장세",
  exec_cost: "비용", test_writer: "테스트", learning: "학습", self_improve: "개선", security: "보안"};
// the five group specialists the owners added for v4 (paperbot/groups.py V4_ROLES); drawn only once the server lists them
export const GROUP_ROLES = [["ds_structure", "구조·유동성"], ["ds_trend", "추세·눌림"], ["ds_session", "세션·시가"],
  ["ds_reversal", "반전·되돌림"], ["reel_5m", "5분봉 단타"]];
/** Rooms whose schedule the server leaves empty (old rooms.js ROOM_SCHEDULE). */
export const ROOM_SCHEDULE = {"team:lab": "남는 AI 한도로 하루 여러 번 (1시간에 한 번까지): 연구원이 새 매매법을 3개까지 제안 → 반론 검토관이 " +
  "비슷한 실패작과 데이터 뒤지기를 거름 → 코드가 5년 자료로 시험 → 팀장 요약. 두 분 글에도 답합니다."};
export const scheduleOf = (id, ...xs) => xs.map((x) => x && x.schedule_ko).find(Boolean) || ROOM_SCHEDULE[id] || "";
export const TEAM_AV = {"team:market": "시장", "team:risk": "위험", "team:ops": "운영", "team:review": "복기", "team:lead": "총괄", "team:lab": "연구"};

// ---------------------------------------------------------------- people
/** {id, name, label, team} from office.roles (a map) or roster.roles (a list). */
export function roleOf(roles, id) {
  let r = null;
  if (Array.isArray(roles)) r = roles.find((x) => x.id === id) || null;
  else if (roles) r = roles[id] || null;
  if (id === "code") return {id, name: "코드(자동 계산)", label: "코드", team: "code"};
  if (id === "owner") return {id, name: "두 분", label: "두 분", team: "owner"};
  // the five group specialists: the server's label is the raw key ("ds_structure"), so their names come from here
  const grp = String(id).startsWith("spec_") ? GROUP_ROLES.find((g) => g[0] === String(id).slice(5)) : null;
  if (grp) return {id, name: `${grp[1]} 담당`, label: grp[1].split(/[·\s]/)[0], team: "specialist", group: true};
  if (!r && String(id).startsWith("spec_")) return {id, name: `${fmt.stratKo(String(id).slice(5))} 전담`, label: fmt.stratKo(String(id).slice(5)), team: "specialist"};
  return {id, name: (r && r.name) || String(id), label: (r && r.label) || null, team: (r && r.team) || ""};
}
export const roleName = (roles, id) => roleOf(roles, id).name;
/** A short label (2-5 characters) for a figure's name plate or an avatar. */
export function shortName(roles, id) {
  const r = roleOf(roles, id);
  if (id === "code") return "코드";
  if (id === "owner") return "두 분";
  // cut at a word boundary ("볼린저 스…" read as a broken word on the name plates)
  if (r.label) return String(r.label).split(/[·\s]/)[0].slice(0, 5);
  if (ROLE_AV[id]) return ROLE_AV[id];
  return String(r.name || id).replace(/[·()\s]/g, "").slice(0, 3);
}
export const hueFor = (roles, id) => TEAM_HUE[roleOf(roles, id).team] ?? hueOf(id);
/** A round avatar for a speaker: code = square "C", owners = yellow ring. */
export function avatarFor(roles, id, name) {
  if (id === "code" || id === "system") return ui.avatar("C", null, "code");
  if (id === "owner") return ui.avatar("대표", null, "owner");
  const lab = ROLE_AV[id] || (String(id).startsWith("spec_") ? "전담" : String(name || roleOf(roles, id).name).replace(/[·()\s]/g, "").slice(0, 2));
  return ui.avatar(lab, hueFor(roles, id));
}
/** A small pixel person for a speaker (digest step rows). */
export function miniFigure(roles, id) {
  if (id === "code") return h("span", {class: "rk-code-av", "aria-hidden": "true"}, "C");
  const r = roleOf(roles, id);
  return figure({team: r.team, hue: hueFor(roles, id), kind: r.team === "specialist" ? "spec" : id === "owner" ? "owner" : "staff", size: 14});
}
/** A room's avatar label. */
export function roomAvatar(r) {
  if (!r) return ui.avatar("?", 210);
  if (r.kind === "team") return ui.avatar(TEAM_AV[r.room_id] || String(r.title || "").slice(0, 2), hueOf(r.room_id));
  return ui.avatar(String(r.strategy || r.title || "").split("_")[0].slice(0, 3), TEAM_HUE.specialist, "strat");
}
export const roomTitle = (rooms, id) => ((rooms || []).find((r) => r.room_id === id) || {}).title || roomIdKo(id);
export function roomIdKo(id) {
  const s = String(id || "");
  if (s.startsWith("strat:")) return `${fmt.stratKo(s.slice(6))} 방`;
  return s;
}

// ---------------------------------------------------------------- message data
export function dataOf(m) {
  const d = m && m.data;
  if (d && typeof d === "object") return d;
  if (typeof d === "string") { try { const x = JSON.parse(d); return x && typeof x === "object" ? x : {}; } catch { return {}; } }
  return {};
}
export function answerOf(m) {
  const a = dataOf(m).answer;
  return a && typeof a === "object" ? a : {};
}
/** {stance, ko, cls, to, point} from the answer's responds_to, or null. */
export function stanceOf(m) {
  const rt = answerOf(m).responds_to;
  if (!rt || typeof rt !== "object" || !STANCE[rt.stance]) return null;
  return {stance: rt.stance, ko: STANCE[rt.stance][0], cls: STANCE[rt.stance][1], to: rt.role ? String(rt.role) : null, point: String(rt.point || "")};
}
/** The text's lines, without the first "↳ …에게 반대: …" line when the stance is shown as a pill instead. */
export function bodyLines(m) {
  const lines = String((m && m.text) || "").split("\n");
  if (stanceOf(m) && /^\s*↳/.test(lines[0] || "")) lines.shift();
  return lines;
}
/** A meeting kind's Korean name (the server's trigger_ko, with the few it leaves in English). */
const TRIGGER_KO = {lab: "새 매매법 연구", debate_call: "낙관·비관 판정"};
export const triggerKo = (x) => !x ? "" : (x.trigger_ko && x.trigger_ko !== x.trigger ? x.trigger_ko : TRIGGER_KO[x.trigger] || x.trigger_ko || x.trigger || "");
/** The meeting's reason, unless it only repeats the kind ("순위 검토 (14:00)" under 순위 검토). */
export const whyOf = (x) => { const w = String((x && x.why) || "").trim(); return w && !w.startsWith(triggerKo(x)) ? w : ""; };
export const stripLead = (t) => String(t || "").replace(/^\s*(📣\s*회의 시작:\s*|🧾\s*)/u, "").trim();

// ---------------------------------------------------------------- rules written as JSON -> one Korean line
const FAM_KO = {ema_cross: "EMA 빠른선·느린선 교차", sma_cross: "SMA 빠른선·느린선 교차", macd_cross: "MACD선·시그널선 교차",
  macd_hist_zero: "MACD 히스토그램 0선 교차", supertrend_flip: "슈퍼트렌드 방향 전환", donchian_break: "직전 N봉 최고가·최저가 돌파",
  keltner_break: "켈트너 돌파", psar_flip: "파라볼릭 SAR 방향 전환", dmi_cross: "+DI/−DI 교차 (ADX 25 위)", ichimoku_tk: "일목 전환선·기준선 교차",
  aroon_cross: "아룬 업·다운 교차", hma_turn: "HMA 기울기 전환", rsi_reversal: "RSI 과매도·과매수 되돌림", rsi_cross50: "RSI 50선 교차",
  stoch_zone: "스토캐스틱 교차 (20 아래 롱 / 80 위 숏)", stochrsi_zone: "스토캐스틱 RSI 교차", cci_extreme: "CCI ±100 되돌림",
  williams_r: "윌리엄스 %R 되돌림", mfi_reversal: "MFI 되돌림", roc_zero: "ROC 0선 교차", cmo_zero: "CMO 0선 교차",
  bb_break: "볼린저 밴드 밖으로 돌파", bb_revert: "볼린저 밴드 안으로 복귀", squeeze_break: "스퀴즈 뒤 밴드 돌파",
  obv_cross: "OBV가 20봉 평균 교차", volume_spike: "거래량 급증 캔들 방향", engulfing: "장악형 캔들", hammer_star: "망치형·유성형",
  inside_break: "인사이드바 돌파", three_same: "같은 색 캔들 3연속"};
const DIR_KO = {long: "롱만", short: "숏만", both: "롱·숏"};
const SESS_KO = {asia: "아시아 시간", europe: "유럽 시간", us: "미국 시간"};
const HTF = {"5m": "30분", "15m": "1시간", "30m": "4시간", "1h": "4시간", "4h": "일"};
function filterKo(f, tf) {
  if (!f || typeof f !== "object") return "";
  if (f.kind === "trend_ema") return `EMA${f.length} 추세 방향만`;
  if (f.kind === "adx") return `ADX ${f.level} ${f.mode === "above" ? "이상(추세장)" : "미만(횡보장)"}만`;
  if (f.kind === "htf_trend") return `위 시간봉(${HTF[tf] || "위"}봉) EMA${f.length} 추세 방향만`;
  if (f.kind === "vol_regime") return `변동성 ${f.mode === "high" ? "높을" : "낮을"} 때만 (${f.lookback}봉)`;
  if (f.kind === "session") return `${SESS_KO[f.window] || f.window}만`;
  return String(f.kind || "");
}
const short = (v) => {
  if (v == null) return "—";
  if (typeof v === "object") return Array.isArray(v) ? v.map(short).join(", ") : Object.entries(v).map(([k, x]) => `${k} ${short(x)}`).join(", ");
  return String(v).slice(0, 60);
};
/** One Korean line for a rule / test spec (new-lab grammar, copy-test templates); a generic key list otherwise. */
export function specKo(t) {
  if (!t || typeof t !== "object") return "내용 없음";
  if (t.entry && t.timeframe) {
    const e = t.entry || {}, ps = Object.values(e.params || {});
    return [fmt.tfKo(t.timeframe), `${FAM_KO[e.family] || e.family || "?"}${ps.length ? ` (${ps.join(", ")})` : ""}`,
      ...(t.filters || []).map((f) => filterKo(f, t.timeframe)).filter(Boolean), DIR_KO[t.direction] || t.direction || ""].filter(Boolean).join(" · ");
  }
  if (t.from_trial != null) return t.test ? `${specKo(t.test)} (시험 #${t.from_trial})` : `시험 #${t.from_trial} 결과로`;
  if (t.template === "stop_atr") return `손절 거리 ${t.k} ATR로`;
  if (t.template === "lock_start") return `첫 익절 잠금 ${fmt.pct(t.first_lock || 0, 0)}부터`;
  if (t.template === "skip_tag") return `'${t.tag}' 진입 건너뛰기`;
  if (t.template === "timeframe_only") return "봉별 성적 보기 (설명용)";
  if (t.text || t.template) return String(t.text || t.template);
  return Object.entries(t).slice(0, 6).map(([k, v]) => `${k}: ${short(v)}`).join(" · ");
}
/** A line holding a JSON object -> {label, obj, raw}; null otherwise. */
export function ruleFrom(line) {
  const s = String(line || ""), i = s.indexOf("{"), j = s.lastIndexOf("}");
  if (i < 0 || j <= i) return null;
  let obj;
  try { obj = JSON.parse(s.slice(i, j + 1)); } catch { return null; }
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return null;
  return {label: s.slice(0, i).replace(/[:：]\s*$/, "").trim(), obj, raw: s.slice(i, j + 1)};
}
/** Plain text for one-line places (console): JSON lines become their Korean line, lines are joined. */
export function readableText(lines) {
  return lines.map((ln) => { const r = ruleFrom(ln); return r ? `규칙: ${specKo(r.obj)}` : ln.trim(); }).filter(Boolean).join(" · ");
}
/** A rule card: the readable line, with the raw JSON behind 원문 보기 (never shown by default). */
export function ruleCard(label, obj, raw, extra) {
  let pretty = raw;
  try { pretty = JSON.stringify(obj, null, 1); } catch { /* keep raw */ }
  return h("div", {class: "rk-rule"}, h("span", {class: "rk-rule-h"}, h("b", null, label || "규칙"), extra || null),
    h("span", {class: "rk-rule-t"}, specKo(obj)), ui.disclosure("원문 보기", h("pre", {class: "rk-raw"}, pretty)));
}
/**
 * A message body: the text clamped to `lines` lines with 더 보기, and every JSON rule line as a readable card below
 * (labelled with the nearest "후보 N" line above it). Returns a node.
 */
export function messageBody(lines, o = {}) {
  const text = [], rules = [];
  let cand = null;
  for (const ln of lines) {
    const r = ruleFrom(ln);
    const c = /^\s*(후보\s*\d+)/.exec(ln);
    if (c && !r) cand = c[1];
    if (r) rules.push(ruleCard(cand || (r.label === "문법" ? "규칙" : r.label) || "규칙", r.obj, r.raw));
    else text.push(ln);
  }
  const body = text.join("\n").trim();
  return h("div", {class: "rk-body"}, body ? ui.moreText(body, o.lines || 2, "rk-pre") : null,
    rules.length ? h("div", {class: "rk-rules"}, rules) : null);
}

// ---------------------------------------------------------------- the agents' running state (rooms.js agentsState)
/**
 * From /api/rooms: "ok" | "new" (never ran) | "stopped" (no tick for three rounds, no meeting) | "login" (the login
 * check refused) | "error" (the last pass crashed) | "noai" (every AI call failed for 6 h+). Only "ok" may promise a
 * reply soon.
 */
export function agentsState(ov) {
  if (!ov || !ov.ready) return {st: "new", age: null};
  const lt = ov.last_tick, running = (ov.rooms || []).some((r) => r.running);
  const age = lt && lt.ts ? Math.max(0, (ov.now || Date.now()) - lt.ts) : null;
  if (lt && lt.ok === false) return {st: lt.why === "login" ? "login" : "error", age};
  if (!running && (age == null || age > 3 * (ov.tick_every_ms || 900000))) return {st: "stopped", age};
  const ai = ov.ai, now = ov.now || Date.now();
  if (ai && ai.failed >= 3 && ai.since && now - ai.since >= 6 * 3600000) return {st: "noai", age: now - ai.since};
  return {st: "ok", age};
}
const agoKo = (age) => age == null ? "점검 기록 없음" : `마지막 점검 ${fmt.dur(age / 1000)} 전`;
/** A short pill + a banner (null when ok) for the agents' state. */
export function agentsBadge(a) {
  if (a.st === "ok") return ui.pill("자동 회의 켜짐", "good");
  if (a.st === "new") return ui.pill("에이전트 시작 전", "thin");
  return ui.pill("에이전트 멈춤", "bad");
}
export function agentsBanner(a) {
  const t = {
    new: ["자동 회의 시작 전", "서버에서 에이전트가 돌기 시작하면 직원들이 스스로 회의를 엽니다. 지금 남긴 글은 그때 읽습니다."],
    stopped: ["자동 회의가 멈춰 있습니다", `에이전트 순번이 돌지 않습니다 (${agoKo(a.age)}). 남긴 글은 다시 돌기 시작하면 읽습니다. 서버 화면을 확인해 주세요.`],
    login: ["로그인 확인에서 멈춤", "Claude 구독 로그인을 확인해 주세요 (서버 안내서). 그 전에는 회의가 열리지 않습니다."],
    noai: ["AI 호출이 계속 실패합니다", `직원들의 AI 호출이 ${fmt.dur(a.age / 1000)}째 모두 실패해 회의가 열리지 않습니다. 승인·거절은 코드가 그대로 반영합니다.`],
    error: ["에이전트 실행 중 오류로 멈춤", `서버 기록을 확인해 주세요 (${agoKo(a.age)}). 남긴 글은 다시 돌기 시작하면 읽습니다.`],
  }[a.st];
  if (!t) return null;
  return h("div", {class: ["rk-banner", a.st === "new" ? "" : "bad"], role: "status"}, h("b", null, t[0]), h("span", null, t[1]));
}
export function keptHoursKo(hrs) {
  if (!hrs) return "08:00·12:00·14:00·22:00";
  return [hrs.morning_hour_kst, hrs.bull_bear_hour_kst, hrs.ranking_hour_kst, hrs.evening_hour_kst]
    .filter((x) => Number.isInteger(x) && x >= 0 && x <= 23).sort((a, b) => a - b).map((x) => String(x).padStart(2, "0") + ":00").join("·");
}
/** Why the staff have not answered an owner post yet (rooms.js pendingHint). */
export function pendingHint(st, wait, perDay, kept) {
  if (st === "ok" && wait === "room_full") return `이 방은 오늘 회의를 다 해서 (하루 ${perDay || 3}번) 한국 시간 자정 뒤 첫 차례에 답합니다`;
  if (st === "ok" && wait === "budget") return `오늘 두 분 글에 쓸 AI 한도 (사고 점검·${kept} 회의 몫을 남긴 나머지)를 다 써서, 한도가 풀리는 대로 답합니다`;
  if (st === "ok" && wait === "given_up") return "이 글들을 다루는 회의를 두 번 마치지 못해 멈췄습니다. 글을 하나 더 남기시면 다시 모입니다";
  if (st === "ok" && wait === "retrying") return "이 방 회의의 첫 호출이 잇달아 실패해 잠시 쉬었다가 (최대 4시간) 다시 열고 답합니다";
  if (st === "ok" && wait === "paused") return "Claude 사용 한도나 연결 문제로 회의를 잠시 멈췄습니다. 다시 열리면 답합니다";
  if (st === "ok") return "직원들이 다음 차례에 읽고 답합니다";
  if (st === "new") return "에이전트가 돌기 시작하면 읽고 답합니다";
  return "에이전트가 멈춰 있어 아직 전달되지 않습니다";
}

// ---------------------------------------------------------------- the rooms tab's unread dot (per viewer)
/** Marks the 에이전트 방 tab when a room has messages newer than this viewer has seen. First visit: nothing unread. */
export function syncUnread(ov) {
  if (!ov || !Array.isArray(ov.rooms)) return {};
  let seen = local.get("room-seen", null);
  if (!seen || typeof seen !== "object") {
    seen = {};
    for (const r of ov.rooms) seen[r.room_id] = r.last_id || 0;
    local.set("room-seen", seen);
  }
  setBadge("rooms", ov.rooms.some((r) => (r.last_id || 0) > (seen[r.room_id] || 0)));
  return seen;
}
export function markSeen(roomId, lastId) {
  const seen = local.get("room-seen", {}) || {};
  if ((seen[roomId] || 0) >= lastId) return seen;
  seen[roomId] = lastId;
  local.set("room-seen", seen);
  return seen;
}

// ---------------------------------------------------------------- small pieces
export const stancePill = (s) => ui.pill(s.ko, s.cls);
export const statusPill = (status) => { const [ko, cls] = STATUS[status] || [status || "—", "none"]; return h("span", {class: ["rk-res", cls]}, ko); };
