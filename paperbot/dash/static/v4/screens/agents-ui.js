// 에이전트 공용 조각 (agents-ui): the pieces the agent screens share for the messenger look.
//   - msgTypes(m): the type badges of a stored message (결론 / 제안 / 가설 / 질문 / 데이터), read ONLY from what the
//     message really holds: its kind, the checked answer the agents stored in data.answer (findings fact / hypothesis,
//     proposal / suggestion, ask_next) and, for an older message without data, the lines the agents' render() writes
//     ("- [사실]", "- [가설]", "제안: …", "❓"). Nothing is guessed from tone.
//   - pixAvatar(roles, id): the office's own pixel person (core/figure.js) in a round frame of the role's colour
//   - refsOf(text, board) / miniCards(ctx, refs): small link cards for the strategies and accounts a message names
//     (exact ids only: "S2_ST_ROC", "S2_ST_ROC@15m"). DeepSeek and coin-flip accounts get the 참고 pill and no number
//     (CONTRACT §1.3); the 36 / 5분봉 / 추가 show return % and record from /api/board.
//   - dayLabel(ts): "오늘 · 10월 6일 (화)" / "어제 · …"
//   - wilsonLow(k, n), accuracySeries(grades): the staff leaderboard's order and sparkline (graded predictions only)
// Every string is a text node (h()); model text is never parsed.
import {h, ui, fmt, figure, stratFigure, stratHue} from "../core/pb.js";
import {roleOf, hueFor, answerOf, dataOf} from "./rooms-kit.js";

// ---------------------------------------------------------------- type badges
export const TYPES = {conclusion: "결론", proposal: "제안", hypothesis: "가설", question: "질문", data: "데이터"};
const ORDER = Object.keys(TYPES);

/** The badges of one message, in a fixed order (conclusion first). Only what the stored message says. */
export function msgTypes(m) {
  const out = new Set();
  if (!m) return [];
  const k = m.kind, a = answerOf(m), d = dataOf(m);
  if (["decision", "summary", "verdict"].includes(k)) out.add("conclusion");
  if (k === "code_result") out.add("data");
  if (k === "decision" && ["request_test", "propose_copy", "flag_owners"].includes(d.action)) out.add("proposal");
  for (const f of Array.isArray(a.findings) ? a.findings : []) if (f && typeof f === "object") out.add(f.kind === "fact" ? "data" : "hypothesis");
  for (const key of ["proposal", "suggestion"]) {
    const p = a[key];
    if (p && typeof p === "object" && p.action && p.action !== "no_action") out.add(p.action === "hypothesis" ? "hypothesis" : "proposal");
  }
  if (a.ask_next) out.add("question");
  if (k === "owner" && /[?？]\s*$/.test(String(m.text || "").trim())) out.add("question");
  if (!a || !Object.keys(a).length) {
    // an older message without the stored answer: the lines the agents' render() writes, nothing else
    for (const ln of String(m.text || "").split("\n")) {
      const t = ln.trim();
      if (/^-\s*\[사실\]/.test(t)) out.add("data");
      else if (/^-\s*\[가설\]/.test(t)) out.add("hypothesis");
      else if (/^(참고\s*)?제안:\s*(?!\s|없음|행동 없음)/.test(t)) out.add(/^(참고\s*)?제안:\s*가설/.test(t) ? "hypothesis" : "proposal");
      else if (/^❓/.test(t)) out.add("question");
    }
  }
  return ORDER.filter((x) => out.has(x));
}
/** The badge row (null when none). */
export function typeBadges(m, max = 3) {
  const ts = msgTypes(m).slice(0, max);
  return ts.length ? h("span", {class: "ag-types"}, ts.map((t) => h("span", {class: ["ag-t", `t-${t}`]}, TYPES[t]))) : null;
}
/** Does a message carry a note for / from the owners (두 분 메모)? Owner posts, a reply to them, a flag to them. */
export function forOwners(m) {
  if (!m) return false;
  if (m.kind === "owner") return true;
  const a = answerOf(m), d = dataOf(m);
  if (a.reply_to_owner || a.flag_owners || a.human_actions) return true;
  if (d.action === "flag_owners") return true;
  return /(^|\n)\s*(💬 두 분께|📣 두 분께|두 분이 할 일)/.test(String(m.text || ""));
}

// ---------------------------------------------------------------- avatars
/** The pixel person of a speaker in a round frame of the role's colour (code: a square C; the owners: their figure). */
export function pixAvatar(roles, id, o = {}) {
  const size = o.size || 24;
  if (id === "code" || id === "system") return h("span", {class: "ag-av code", title: "코드 (자동 계산)", "aria-hidden": "true"}, h("b", null, "C"));
  if (id === "owner") return h("span", {class: "ag-av owner", title: "두 분", "aria-hidden": "true"}, figure({kind: "owner", size}));
  const r = roleOf(roles, id);
  return h("span", {class: "ag-av", style: {"--h": hueFor(roles, id)}, title: r.name, "aria-hidden": "true"},
    figure({team: r.team, hue: hueFor(roles, id), kind: r.team === "specialist" ? "spec" : "staff", size}));
}

// ---------------------------------------------------------------- strategies / accounts a message names
const TF_RE = "(?:5m|15m|30m|1h|4h)";
/** [{type: "account"|"strategy", id}] named in the text, exact ids that the board knows (first 3). */
export function refsOf(text, board) {
  const t = String(text || "");
  const accts = new Map(((board && board.accounts) || []).map((a) => [a.account_id, a]));
  if (!accts.size || !t) return [];
  const out = [], seen = new Set();
  const add = (type, id) => { const k = `${type}:${id}`; if (!seen.has(k) && out.length < 3) { seen.add(k); out.push({type, id}); } };
  const ra = new RegExp(`([A-Z][A-Z0-9_.]{1,40}@${TF_RE}(?:~c\\d+)?)(?![A-Za-z0-9_])`, "g");
  let m;
  while ((m = ra.exec(t))) if (accts.has(m[1])) add("account", m[1]);
  const strats = new Set([...accts.values()].map((a) => a.strategy));
  const rs = /([A-Z][A-Z0-9_.]{2,40})(?![A-Za-z0-9_.@])/g;
  while ((m = rs.exec(t))) {
    if (!strats.has(m[1])) continue;
    if ([...seen].some((k) => k.startsWith(`account:${m[1]}@`))) continue;      // the account card already names it
    add("strategy", m[1]);
  }
  return out;
}
const quietKinds = new Set(["ds200", "random"]);     // DeepSeek / coin flips: the 참고 pill only, never a number
/** Small link cards for refsOf() (null when none). */
export function miniCards(ctx, refs, board) {
  if (!refs || !refs.length || !board) return null;
  const init = board.initial || 5000;
  const accts = board.accounts || [];
  const cards = refs.map((r) => {
    if (r.type === "account") {
      const a = accts.find((x) => x.account_id === r.id);
      if (!a) return null;
      const quiet = quietKinds.has(a.kind);
      const ret = a.wallet / init - 1;
      const p = a.position;
      return h("a", {class: "ag-mini", href: ctx.href("account", a.account_id), title: `${a.account_id} 계좌 열기`},
        h("span", {class: "ag-mini-fig", "aria-hidden": "true"}, stratFigure({strategy: a.strategy, kind: a.kind, size: 22})),
        h("span", {class: "ag-mini-b"},
          h("b", null, `${fmt.stratKo(a.strategy)} · ${fmt.tfKo(a.timeframe)}`),
          quiet ? h("span", {class: "ag-mini-s"}, ui.pill(a.kind === "random" ? "동전 봇" : "딥시크", "ref"))
            : h("span", {class: "ag-mini-s"}, h("span", {class: ["num", fmt.tone(ret)]}, fmt.pct(ret, 1)),
              ` · ${fmt.int(a.trades || 0)}건 ${fmt.int(a.wins || 0)}승 ${fmt.int(a.losses || 0)}패`,
              p ? h("span", {class: "ag-mini-pos"}, ` · 열림 ${fmt.coin(p.symbol)} ${fmt.sideKo(p.side)} ${fmt.lev(p.leverage)}`) : null)),
        h("i", {class: "ag-mini-go", "aria-hidden": "true"}, "›"));
    }
    const mine = accts.filter((x) => x.strategy === r.id && !x.parent);
    if (!mine.length) return null;
    const kind = mine[0].kind, quiet = quietKinds.has(kind);
    const n = mine.reduce((s, x) => s + (x.trades || 0), 0), w = mine.reduce((s, x) => s + (x.wins || 0), 0);
    const open = mine.filter((x) => x.position).length;
    return h("a", {class: "ag-mini", href: ctx.href("strategies", r.id), title: `${fmt.stratKo(r.id)} 매매법 열기`},
      h("span", {class: "ag-mini-fig", style: {"--h": stratHue(r.id, kind) ?? 210}, "aria-hidden": "true"}, stratFigure({strategy: r.id, kind, size: 22})),
      h("span", {class: "ag-mini-b"}, h("b", null, fmt.stratKo(r.id)),
        quiet ? h("span", {class: "ag-mini-s"}, ui.pill("딥시크", "ref"))
          : h("span", {class: "ag-mini-s"}, `매매법 · 봉 ${fmt.int(mine.length)}개 · ${fmt.int(n)}건 ${fmt.int(w)}승 ${fmt.int(n - w)}패`,
            open ? ` · 열림 ${fmt.int(open)}` : "")),
      h("i", {class: "ag-mini-go", "aria-hidden": "true"}, "›"));
  }).filter(Boolean);
  return cards.length ? h("div", {class: "ag-minis"}, cards) : null;
}

// ---------------------------------------------------------------- time
/** "오늘 · 10월 6일 (화)", "어제 · 10월 5일 (월)", else the date. */
export function dayLabel(ts, now = Date.now()) {
  const k = fmt.dayKey(ts);
  if (k === fmt.dayKey(now)) return `오늘 · ${fmt.date(ts)}`;
  if (k === fmt.dayKey(now - 86400000)) return `어제 · ${fmt.date(ts)}`;
  return fmt.date(ts);
}

// ---------------------------------------------------------------- staff accuracy
/** Wilson score lower bound (95 %) of k hits in n: the leaderboard's order, so 2 of 2 does not beat 30 of 40. */
export function wilsonLow(k, n) {
  if (!n) return 0;
  const z = 1.96, p = k / n, d = 1 + z * z / n;
  return Math.max(0, (p + z * z / (2 * n) - z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / d);
}
/** Graded hypotheses (/api/trials rows of kind 'hypothesis') per role -> {role: [{ts, correct}]} oldest first, and the
 *  cumulative hit rate after each grade (the sparkline). Waiting / expired / not gradable are counted apart. */
export function gradesByRole(trials) {
  const by = {};
  for (const t of trials || []) {
    if (!t || t.kind !== "hypothesis") continue;
    const spec = t.spec && typeof t.spec === "object" ? t.spec : {};
    const role = spec.by || "";
    if (!role) continue;
    const k = by[role] || (by[role] = {role, grades: [], waiting: 0, expired: 0, notGradable: 0, latest: null});
    const res = t.result && t.result.result && typeof t.result.result === "object" ? t.result.result : null;
    const st = t.result ? t.result.status : null;
    if (!spec.prediction || typeof spec.prediction !== "object") k.notGradable++;
    else if (!t.result) k.waiting++;
    else if (st === "expired") k.expired++;
    else if (st === "graded" && res) k.grades.push({ts: t.result.ts || t.ts, correct: !!res.correct});
    if (!k.latest || (t.ts || 0) > (k.latest.ts || 0)) k.latest = t;
  }
  for (const k of Object.values(by)) {
    k.grades.sort((a, b) => a.ts - b.ts);
    let hit = 0;
    k.series = k.grades.map((g, i) => { hit += g.correct ? 1 : 0; return hit / (i + 1); });
    k.correct = hit;
    k.graded = k.grades.length;
  }
  return by;
}
/** One hypothesis' status: [ko, pill class] (맞음 / 틀림 / 진행 중 / 기간 만료 / 채점 불가). */
export function hypStatus(t) {
  const spec = (t && t.spec) || {};
  if (!spec.prediction || typeof spec.prediction !== "object") return ["채점 불가", "thin", "none"];
  if (!t.result) return ["진행 중", "accent", "wait"];
  if (t.result.status === "expired") return ["기간 만료", "thin", "exp"];
  const r = t.result.result || {};
  return r.correct ? ["맞음", "good", "hit"] : ["틀림", "bad", "miss"];
}
