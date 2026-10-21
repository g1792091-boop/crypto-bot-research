// 실거래 › 분석팀 (#/livebots/team, owners 10/19 "실거래 분석 팀 ... 실거래 대시보드 화면 안에"): the 실거래 분석 팀
// (paperbot/liveteam.py), read-only from its own liveteam.db through /api/v4/livebots/team (dash/more/livebots.py team()).
// Four AI members read the packet of facts the code builds from the live records and explain it in plain Korean; they
// never trade (no tools, no order key). 방패 (리스크) · 저울 (통계) · 나침반 (시장) speak in order, 등대 (팀장) writes the
// conclusion. Meetings: 손실 회의 (a live executor's last two closed trades both lost), 판단 회의 (every 40 paper trades),
// 주간 보고 (Mondays 10:00 KST; a week without trades is one quiet line, no AI). The 추세판단 봇 (d.bot.trend, owners 10/21):
// its checkpoints are 거래 점검 on its own trades (no 88 % rule: when.checkpoint_ko / checkpoint_sub_ko), the intro names
// what the team reads of it (d.bot.about_ko) and an idea is tested by a shadow bot or at the review (idea.how_ko).
//   본부      the four members as pixel characters on their coloured pads (core/figure.js figure: a stable hue each), name,
//             title, focus, and the last line each really said (ui.bubble: stored lines only); the switch (timer on / off,
//             the one command), the login check, the AI used today / in 7 days against the owners' caps, the next meetings
//   결론      the newest finished meeting: verdict (정상 범위 · 지켜보기 · 주의), the lead's headline, summary, 잘된 점 /
//             걱정 / 다음에 볼 것, 시험해 볼 아이디어 (가설 · 근거 · 시험 방법 · 상태; the owners adopt by the ledger's order)
//   회의 기록  10 a page; one opens into its transcript: each member's bubble in speaking order (headline bold, points as
//             bullets, 걱정 / 우연일 정도 tinted), a member that gave no answer as a muted line; quiet weeks one line;
//             a failed meeting says why; a dry run says 연습
// HONESTY: every word is a stored line (nothing typed out, no invented activity: 회의 중 only for a meeting the database
// says is running); a file not there yet = 수집 전 with what the team is and how to turn it on (installed off); one not
// read = 못 읽음 + why; usage counts only from the team's own records; AI opinion, 참고 only: trading follows the fixed rules.
import {h, s, put, ui, fmt, motion, figure, serverNow} from "../core/pb.js";
import {sourceState} from "./livebots-kit.js";

export const API = "/api/v4/livebots/team";
const REFRESH_MS = 60 * 1000;
const PAGE = 10;
/** The members' looks: a figure hue (core/figure.js) and a token colour (livebots-team.css .lbt-*[data-role]). */
export const LOOK = {risk: {hue: 220, emblem: "shield"}, stats: {hue: 42, emblem: "scale"}, market: {hue: 172, emblem: "compass"},
  lead: {hue: 300, emblem: "light"}};
export const ORDER = ["risk", "stats", "market", "lead"];
/** The verdict words' tones (liveteam.VERDICTS order: 정상 범위, 지켜보기, 주의). */
export const VERDICT_TONE = {"정상 범위": "ok", "지켜보기": "watch", "주의": "warn"};
const STATE_KO = {done: ["결론 나옴", "ok"], quiet: ["조용히 넘어감", "thin"], failed: ["멈춤", "bad"], running: ["회의 중", "live"]};
const KIND_T = {weekly: "weekly", loss: "loss", checkpoint: "check"};

// ---------------------------------------------------------------- pure functions (node tests: tests/test_dash_livebots_team.py)
const numOr = (x) => (x == null || x === "" || typeof x === "boolean" || !Number.isFinite(Number(x)) ? null : Number(x));

/**
 * A member's stored text (liveteam.member_text: the headline, "· " points, "걱정: ...", "우연일 정도: ...") in parts:
 * {head, points: [], worry, luck, other: []}. A line that fits none of them is kept in other (never dropped).
 */
export function parseText(text) {
  const out = {head: null, points: [], worry: null, luck: null, other: []};
  for (const raw of String(text || "").split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    if (/^[·•-]\s*/.test(line) && line.length > 1) out.points.push(line.replace(/^[·•-]\s*/, ""));
    else if (/^걱정\s*:/.test(line)) out.worry = line.replace(/^걱정\s*:\s*/, "");
    else if (/^우연일 정도\s*:/.test(line)) out.luck = line.replace(/^우연일 정도\s*:\s*/, "");
    else if (out.head == null && !out.points.length) out.head = line;
    else out.other.push(line);
  }
  return out;
}

/** The newest meeting with a conclusion (state done and the lead's result), or null. meetings: newest first. */
export function latestDone(meetings) {
  return (meetings || []).find((m) => m && m.state === "done" && m.result && (m.result.headline || m.headline)) || null;
}

/** Each member's last real line (an answer, not an error), from the newest meeting it spoke in: {role: {head, ts, kind_ko, id}}. */
export function lastLines(meetings) {
  const out = {};
  for (const m of meetings || []) {
    for (const x of (m && m.messages) || []) {
      if (!x || x.error || out[x.role]) continue;
      const head = parseText(x.text).head;
      if (head) out[x.role] = {head, ts: x.ts, kind_ko: m.kind_ko, id: m.id};
    }
  }
  return out;
}

/** The timer in words: {ko, tone, on}. active null = systemctl could not be asked (never read as off or on). */
export function timerWord(t) {
  if (!t) return {ko: "확인 못 함", tone: "thin", on: null};
  if (t.on) return {ko: "켜짐", tone: "good", on: true};
  if (t.active == null && t.enabled == null) return {ko: "켜짐 여부 확인 못 함", tone: "thin", on: null};
  return {ko: "꺼짐", tone: "warn", on: false};
}

/** The login check in words: {ko, tone, title}. null = not checked yet. */
export function authWord(a) {
  if (!a) return {ko: "로그인 확인 전", tone: "thin", title: "분석팀이 아직 한 번도 돌지 않았어요"};
  if (a.ok) return {ko: "로그인 확인됨", tone: "good", title: `${a.why || "Claude 로그인"} · ${fmt.kst(a.ts)}`};
  return {ko: "로그인 문제", tone: "bad", title: a.why || "로그인을 확인하지 못했어요"};
}

/** AI use against the caps: [{id, k, n, cap, ratio}]; n null when the team's records were not read (never a 0). */
export function usageOf(d) {
  const u = d && d.state === "ok" ? d.usage || {} : null, b = (d && d.budget) || {};
  const row = (id, k, n, cap) => ({id, k, n: u ? numOr(n) ?? 0 : null, cap: numOr(cap),
    ratio: u && numOr(cap) ? Math.max(0, Math.min(1, (numOr(n) ?? 0) / numOr(cap))) : null});
  return [row("day", "오늘", u && u.day_calls, b.day), row("week", "7일", u && u.week_calls, b.week),
    row("tokens", "오늘 토큰", u && u.day_tokens, b.tokens_day)];
}

/** Progress to the next 판단 회의: {n, prev, next, ratio} or null when the paper count is unknown. */
export function checkpointOf(w) {
  const n = numOr(w && w.paper_n), every = numOr(w && w.checkpoint_every) || 40;
  if (n == null) return null;
  const next = numOr(w.checkpoint_next) ?? (Math.floor(n / every) + 1) * every, prev = next - every;
  return {n, prev, next, ratio: Math.max(0, Math.min(1, (n - prev) / every))};
}

/** A meeting's state chip: {ko, tone}. A meeting still running after 30 minutes may have died: it says so. */
export function stateOf(m, now) {
  const [ko, tone] = STATE_KO[m && m.state] || [String((m && m.state) || "—"), "thin"];
  if (m && m.state === "running" && now && m.started_ts && now - m.started_ts > 30 * 60000) return {ko: "회의 중으로 남음 (멈췄을 수 있음)", tone: "warn"};
  return {ko, tone};
}

/** The answer without its clock: the same records again draw nothing (an open transcript stays open). */
export const sameKey = (d) => (d ? JSON.stringify({...d, now_ms: 0}) : "");

// ---------------------------------------------------------------- pieces
// 8 x 8 pixel emblems (a shield, a balance, a compass, a lighthouse), drawn in the member's colour
const EMBLEM = {
  shield: [".######.", "########", "##.##.##", "##.##.##", "########", ".######.", "..####..", "...##..."],
  scale: ["...##...", "########", ".#.##.#.", "#..##..#", "###..###", "...##...", "...##...", ".######."],
  compass: ["..####..", ".#....#.", "#....###", "#..###.#", "#.###..#", "###....#", ".#....#.", "..####.."],
  light: ["..#..#..", "...##...", "..####..", "...##...", "..#..#..", "..####..", ".##..##.", "########"],
};
function emblem(id) {
  const rows = EMBLEM[id] || EMBLEM.shield, kids = [];
  rows.forEach((r, y) => [...r].forEach((c, x) => { if (c === "#") kids.push(s("rect", {x, y, width: 1, height: 1})); }));
  return s("svg", {class: "lbt-emb", viewBox: "0 0 8 8", width: 16, height: 16, "shape-rendering": "crispEdges", "aria-hidden": "true"}, kids);
}
/** A member's character on its ringed pad (size: the figure's width in px). */
export function avatar(role, size = 34, o = {}) {
  const look = LOOK[role] || {hue: 210, emblem: "shield"};
  return h("span", {class: ["lbt-av", o.cls], dataset: {role}, "aria-hidden": "true"},
    h("span", {class: "lbt-pad"}), figure({hue: look.hue, size, kind: "staff", cls: "lbt-fig"}), o.emblem === false ? null : h("span", {class: "lbt-badge"}, emblem(look.emblem)));
}
const verdictChip = (v, big) => (v ? h("span", {class: ["lbt-verdict", big ? "big" : ""], dataset: {v: VERDICT_TONE[v] || "watch"}},
  h("i", {"aria-hidden": "true"}), v) : null);
const kindBadge = (m) => h("span", {class: "lbt-kind", dataset: {k: KIND_T[m.kind] || "other"}}, h("i", {"aria-hidden": "true"}), m.kind_ko || m.kind || "회의");

/** One member's words as a bubble body: the headline bold, the points as bullets, 걱정 / 우연일 정도 tinted. */
export function textBlock(text) {
  const p = parseText(text);
  return [p.head ? h("p", {class: "lbt-head"}, p.head) : null,
    p.points.length ? h("ul", {class: "lbt-pts"}, p.points.map((t) => h("li", null, t))) : null,
    p.other.length ? p.other.map((t) => h("p", {class: "lbt-oth"}, t)) : null,
    p.worry ? h("p", {class: "lbt-worry"}, h("b", null, "걱정 "), p.worry) : null,
    p.luck ? h("p", {class: "lbt-luck"}, h("b", null, "우연일 정도 "), p.luck) : null];
}

/** A meeting's transcript: the members' bubbles in speaking order, then the ideas. */
export function transcript(m) {
  const msgs = [...((m && m.messages) || [])].sort((a, b) => (a.seq || 0) - (b.seq || 0));
  const lines = msgs.map((x) => h("div", {class: ["lbt-msg", x.error ? "err" : "", x.role === "lead" ? "lead" : ""], dataset: {role: x.role}, role: "listitem"},
    avatar(x.role, 22, {emblem: false, cls: "sm"}),
    h("div", {class: "lbt-mbody"},
      h("div", {class: "lbt-mwho"}, h("b", null, x.name || x.role), h("span", null, x.title || ""), h("span", {class: "lbt-mt num"}, fmt.hm(x.ts))),
      h("div", {class: "lbt-say"}, x.error ? h("p", {class: "lbt-noans"}, `(답 없음: ${x.error})`) : textBlock(x.text)))));
  const ideas = (m && m.ideas) || [];
  return h("div", {class: "lbt-tr"},
    m && m.state === "failed" ? h("p", {class: "lb-warn"}, `회의가 멈췄어요: ${m.why || "이유 기록 없음"}`) : null,
    m && m.why && m.state === "done" ? h("p", {class: "note"}, `열린 이유: ${m.why}`) : null,
    lines.length ? h("div", {class: "lbt-chat", role: "list", "aria-label": "회의 발언"}, lines) : ui.note("기록된 발언이 없어요"),
    ideas.length ? h("div", {class: "lbt-tideas"}, h("h4", null, `시험해 볼 아이디어 ${fmt.int(ideas.length)}개`), ideas.map(ideaCard)) : null,
    h("p", {class: "lbt-meta"}, [`AI 호출 ${fmt.int(m.calls || 0)}번`, m.tokens ? `토큰 ${fmt.compact(m.tokens)}` : null,
      m.sent === true ? "텔레그램에 결론 보냄" : m.sent === false ? "텔레그램 못 보냄" : null, m.dry ? "연습 (기록 안 함)" : null].filter(Boolean).join(" · ")));
}

/** One idea to test: the hypothesis, its reason, how to test it, its status (the owners decide). */
export function ideaCard(i) {
  return h("div", {class: "lbt-idea"},
    h("div", {class: "lbt-ih"}, h("span", {class: "lbt-ibulb", "aria-hidden": "true"}, "?"), h("b", null, i.idea || "—"),
      ui.pill(i.status || "제안", i.status === "제안" || !i.status ? "accent" : "thin", i.how_ko || "두 분이 개선 후보 장부 순서대로 정해요")),
    i.why ? h("p", null, h("span", {class: "muted"}, "근거 "), i.why) : null,
    i.test ? h("p", null, h("span", {class: "muted"}, "시험 방법 "), i.test) : null);
}

// ---------------------------------------------------------------- the view
/** teamView(ctx) -> {el, set()}: the 분석팀 tab (its own endpoint, every 60 s). */
export function teamView(ctx) {
  const st = {d: null, okAt: 0, key: "", open: new Set(), seen: false};
  const stateSlot = h("div", {class: "lb-slot"});
  const srcSlot = h("div", {class: "lb-slot"});
  const status = h("div", {class: "lbt-status"});
  const members = h("div", {class: "lbt-members", role: "list", "aria-label": "분석팀 네 명"});
  const next = h("div", {class: "lbt-next"});
  const intro = h("div", {class: "lbt-introslot"});
  const hero = h("div", {class: "lbt-heroslot"});
  const pg = ui.pager({size: PAGE, row: (m) => meetingRow(m), empty: () => (!st.d ? motion.shimmer(3)
    : st.d.state === "ok" ? ui.empty("아직 열린 회의가 없어요") : h("p", {class: "note"}, "회의 기록은 분석팀을 켜고 첫 회의가 열리면 생겨요"))});
  const listCount = h("span", {class: "lbt-lcount"});
  const body = h("div", {class: "lbt-body stack"},
    h("section", {class: "lbt-hq", "aria-label": "분석팀 본부"},
      h("div", {class: "lbt-hhead"}, ui.plate("실거래 분석팀"), h("span", {class: "lbt-hsub"}, "AI 넷이 실거래 기록을 읽고 쉬운 말로 설명해요 · 읽기만 하고 매매는 안 해요")),
      status, members, next),
    srcSlot, intro, hero,
    ui.card({title: "회의 기록", sub: "누르면 팀원들이 한 말이 순서대로 펼쳐져요", cls: "lbt-listcard", acts: [listCount]}, pg.el),
    h("div", {class: "lbt-foot"}));
  const foot = body.lastChild;
  const el = h("div", {class: "lbt stack"}, stateSlot, body);

  function chip(ko, tone, title) { return h("span", {class: ["lbt-chip", tone], title: title || null}, h("i", {"aria-hidden": "true"}), ko); }
  function meter(u) {
    return h("div", {class: "lbt-use", title: u.cap != null ? `${u.k} ${u.n == null ? "—" : fmt.int(u.n)} / 한도 ${fmt.int(u.cap)}` : null},
      h("span", {class: "lbt-usek"}, u.k),
      h("b", {class: "num"}, u.n == null ? "—" : u.id === "tokens" ? fmt.compact(u.n) : fmt.int(u.n),
        h("small", null, ` / ${u.cap == null ? "—" : u.id === "tokens" ? fmt.compact(u.cap) : fmt.int(u.cap)}`)),
      h("span", {class: ["lbt-ubar", u.ratio != null && u.ratio >= 0.85 ? "hi" : ""]}, u.ratio != null ? h("i", {style: {width: (u.ratio * 100).toFixed(1) + "%"}}) : null));
  }
  function cmdBox(cmd, label) {
    const copy = h("button", {type: "button", class: "btn-line lbt-copy", onclick: async () => {
      try { await navigator.clipboard.writeText(cmd); if (ctx.toast) ctx.toast("명령을 복사했어요"); }
      catch (e) { if (ctx.toast) ctx.toast("복사하지 못했어요: 길게 눌러 직접 복사해 주세요"); }
    }}, "복사");
    return h("div", {class: "lbt-cmd"}, label ? h("span", {class: "lbt-cmdk"}, label) : null, h("code", {class: "lb-cmd"}, cmd), copy);
  }

  function drawHq(d) {
    const tw = timerWord(d.timer), aw = authWord(d.auth);
    const lt = d.last_tick;
    put(status,
      h("div", {class: "lbt-chips"}, chip(`분석팀 ${tw.ko}`, tw.tone, d.timer && d.timer.unit), chip(aw.ko, aw.tone, aw.title),
        lt && lt.ts ? h("span", {class: "lbt-tick"}, `마지막으로 살펴본 때 ${fmt.kst(lt.ts)}`) : null,
        d.state === "ok" && d.ideas_open ? chip(`시험해 볼 아이디어 ${fmt.int(d.ideas_open)}개`, "accent", "두 분이 정할 때까지 '제안'") : null),
      h("div", {class: "lbt-uses", "aria-label": "AI 사용 (두 분의 Claude 요금제에서)"}, usageOf(d).map(meter)),
      d.budget_error ? h("p", {class: "lb-warn"}, `AI 사용 한도 설정(LIVETEAM_BUDGET)을 읽지 못해 기본값을 써요: ${d.budget_error}`) : null,
      tw.on && d.timer && d.timer.off_cmd ? h("div", {class: "lbt-offhow"}, ui.disclosure("끄는 법", cmdBox(d.timer.off_cmd, "끄기"))) : null);
    const said = lastLines(d.meetings);
    const roster = [...(d.roster || [])].sort((a, b) => ORDER.indexOf(a.id) - ORDER.indexOf(b.id));
    const enter = !st.seen;
    st.seen = true;
    put(members, roster.map((r, i) => {
      const line = said[r.id];
      return h("div", {class: ["lbt-mem", enter ? "lbt-enter" : ""], dataset: {role: r.id}, role: "listitem", style: {"--i": i}},
        line ? h("div", {class: "lbt-bub", title: `${line.kind_ko} · ${fmt.kst(line.ts)}`}, h("span", {class: "lbt-bubt"}, line.head)) : null,
        h("div", {class: "lbt-stage"}, avatar(r.id, 48, {cls: "md"})),
        h("div", {class: "lbt-tag"}, h("b", null, r.name), h("span", null, r.title)),
        h("p", {class: ["lbt-focus", line ? "" : "full"], title: r.focus}, r.focus));
    }));
    const cp = checkpointOf(d.when || {}), w = d.when || {};
    const off = tw.on === false;
    put(next,
      h("div", {class: "lbt-nhead"}, h("b", null, "다음 회의"), off ? h("span", {class: "muted"}, "· 지금은 꺼져 있어 열리지 않아요 (켜면 이 순서로 열려요)") : null),
      h("div", {class: "lbt-ntiles"},
        h("div", {class: "lbt-nt", dataset: {k: "weekly"}}, h("span", {class: "lbt-ntk"}, "주간 보고"), h("b", null, w.weekly_next_ms ? `${fmt.date(w.weekly_next_ms)} ${fmt.hm(w.weekly_next_ms)}` : "—"),
          h("span", {class: "lbt-nts"}, "매주 월요일 10:00 · 지난주 거래가 없으면 AI 없이 한 줄")),
        h("div", {class: "lbt-nt", dataset: {k: "check"}}, h("span", {class: "lbt-ntk"}, w.checkpoint_ko || "판단 회의"),
          h("b", {class: "num"}, cp ? `${fmt.int(cp.n)} / ${fmt.int(cp.next)}번` : "페이퍼 거래 수 못 읽음"),
          cp ? h("span", {class: "lbt-nbar", role: "img", "aria-label": `${cp.n} / ${cp.next}`}, h("i", {style: {width: (cp.ratio * 100).toFixed(1) + "%"}})) : null,
          h("span", {class: "lbt-nts"}, w.checkpoint_sub_ko || `페이퍼 닫힌 거래 ${fmt.int(w.checkpoint_every || 40)}번마다`)),
        h("div", {class: "lbt-nt", dataset: {k: "loss"}}, h("span", {class: "lbt-ntk"}, "손실 회의"), h("b", null, "두 번 연속 손실 때"),
          h("span", {class: "lbt-nts"}, w.loss_rule_ko || "실거래 실행기의 마지막 닫힌 거래 2개가 모두 손실이면"))));
  }

  function drawIntro(d) {
    const tw = timerWord(d.timer), b = d.budget || {}, timer = d.timer || {};
    const fresh = d.state === "missing" || (d.state === "ok" && !(d.meetings || []).length);
    if (!fresh && tw.on !== false) { put(intro); return; }
    if (!fresh) {                        // turned off after it ran: one line with the command to turn it back on
      put(intro, h("div", {class: "lbt-offline"}, h("span", null, "분석팀이 꺼져 있어요. 아래 기록은 켜져 있던 때의 것이에요."), cmdBox(timer.on_cmd, "다시 켜기")));
      return;
    }
    const bot = d.bot || {}, cpk = (d.when && d.when.checkpoint_ko) || "판단 회의";
    put(intro, ui.card({title: tw.on ? "분석팀이 켜졌어요: 첫 회의를 기다려요" : "분석팀은 아직 꺼져 있어요", cls: "lbt-intro"},
      h("ul", {class: "lbt-introl"},
        h("li", null, h("b", null, "무엇을 하나요? "), `${bot.about_ko || "실거래 기록(두 실행기, 페이퍼, 점검 기록, 5년 기준)"}을 코드가 모아 주면, AI 넷이 읽고 쉬운 말로 설명해요.`),
        h("li", null, h("b", null, "누가? "), (d.roster || []).map((r) => `${r.name}(${r.title})`).join(" · "), " · 셋이 차례로 말하고 팀장이 결론을 써요."),
        h("li", null, h("b", null, "언제? "), `실거래가 두 번 연속 지면 손실 회의, ${bot.trend ? "새 봇 시작 뒤 " : ""}페이퍼 거래 40번마다 ${cpk}, 매주 월요일 10:00 주간 보고.`),
        h("li", null, h("b", null, "매매는? "), "안 해요. 읽기만 하고 주문 권한도 설정을 바꿀 방법도 없어요. 매매는 지금처럼 고정 규칙대로예요."),
        h("li", null, h("b", null, "비용은? "), `두 분의 Claude 요금제를 함께 써요. 하루 ${fmt.int(b.day)}번 · 7일 ${fmt.int(b.week)}번까지만 부르고, 한도에 걸리면 다음으로 미뤄요.`)),
      tw.on ? ui.note("켜져 있어요. 회의 때가 되면 여기에 기록이 생겨요.")
        : [h("p", {class: "lbt-when"}, "실거래가 20번쯤 쌓인 뒤에 켜기를 권해요 (그 전에는 대부분 우연이라 결론을 안 내요). 서버에서 이 명령 하나면 돼요:"),
          cmdBox(timer.on_cmd, "켜기"), h("p", {class: "note"}, "끄기: ", h("code", {class: "lb-cmd"}, timer.off_cmd))],
      d.state === "missing" ? h("p", {class: "note"}, `기록 파일: ${d.reason_ko || "아직 없어요"}`) : null));
  }

  function drawHero(d) {
    const m = latestDone(d.meetings);
    if (!m) { put(hero); return; }
    const r = m.result || {};
    const lead = (d.roster || []).find((x) => x.id === "lead") || {name: "등대", title: "팀장"};
    const col = (k, title, xs, cls) => (xs && xs.length ? h("div", {class: ["lbt-col", cls]}, h("h4", null, title), h("ul", null, xs.map((t) => h("li", null, t)))) : null);
    const small = numOr(d.when && d.when.paper_n) != null && d.when.paper_n < (d.small_n || 20);
    put(hero, h("section", {class: "lbt-hero", dataset: {v: VERDICT_TONE[r.verdict || m.verdict] || "watch"}, "aria-label": "최근 결론"},
      h("div", {class: "lbt-hh"}, h("span", {class: "lbt-hk"}, "최근 결론"), kindBadge(m), h("span", {class: "lbt-ht num"}, fmt.kst(m.finished_ts || m.started_ts)),
        m.dry ? ui.pill("연습", "thin", "기록만 남긴 연습 회의") : null),
      h("div", {class: "lbt-hmain"},
        avatar("lead", 46, {cls: "lg"}),
        h("div", {class: "lbt-hbody"}, verdictChip(r.verdict || m.verdict, true),
          h("p", {class: "lbt-hline"}, r.headline || m.headline),
          h("span", {class: "lbt-hby"}, `${lead.name} · ${lead.title}의 결론`))),
      (r.summary || []).length ? h("ul", {class: "lbt-sum"}, r.summary.map((t) => h("li", null, t))) : null,
      h("div", {class: "lbt-cols"}, col("good", "잘된 점", r.good, "good"), col("worries", "걱정", r.worries, "worry"), col("watch", "다음에 볼 것", r.watch_next, "watch")),
      (m.ideas || []).length ? h("div", {class: "lbt-ideas"}, h("h4", null, `시험해 볼 아이디어 ${fmt.int(m.ideas.length)}개`),
        h("div", {class: "lbt-igrid"}, m.ideas.map(ideaCard)),
        ui.note(d.bot && d.bot.idea_how_ko ? `아이디어는 시험해 볼 가설이에요. ${d.bot.idea_how_ko}.`
          : "아이디어는 시험해 볼 가설이에요. 채택은 두 분이 개선 후보 장부 순서대로 (2020-24로 정하고 2025-26에서 확인, 그다음 그림자 봇) 정해요.")) : null,
      small ? h("p", {class: "lb-warn"}, `페이퍼 거래가 아직 ${fmt.int(d.when.paper_n)}번이라 우연이 큰 단계예요: 결론보다 기록으로 읽어 주세요`) : null,
      h("button", {type: "button", class: "linkish lbt-hopen", onclick: () => openMeeting(m.id)}, "이 회의에서 팀원들이 한 말 보기 ↓")));
  }

  function meetingRow(m) {
    const open = st.open.has(m.id), sw = stateOf(m, serverNow());
    const region = h("div", {class: "lbt-mdet", hidden: !open}, open ? transcript(m) : null);
    const quiet = m.state === "quiet";
    const head = h(quiet ? "div" : "button", {type: quiet ? null : "button", class: ["lbt-mh", quiet ? "quiet" : ""], "aria-expanded": quiet ? null : String(open),
      onclick: quiet ? null : () => {
        const on = !st.open.has(m.id);
        if (on) st.open.add(m.id); else st.open.delete(m.id);
        head.setAttribute("aria-expanded", String(on));
        if (on && !region.childNodes.length) put(region, transcript(m));
        motion.expand(region, on);
      }},
    h("span", {class: "lbt-mtop"}, kindBadge(m), h("span", {class: "lbt-mtime num"}, fmt.kst(m.started_ts)),
      h("span", {class: ["lbt-st", sw.tone]}, sw.ko), m.verdict ? verdictChip(m.verdict) : null, m.dry ? ui.pill("연습", "thin") : null,
      (m.ideas || []).length ? h("span", {class: "lbt-mi"}, `아이디어 ${fmt.int(m.ideas.length)}`) : null),
    h("span", {class: "lbt-mline"}, quiet ? (m.why || m.headline || "조용히 넘어감") : m.state === "failed" ? (m.why || "회의가 멈췄어요")
      : m.headline || (m.state === "running" ? "회의가 진행 중이에요 (팀원들이 차례로 말하는 중)" : "결론 없음")),
    quiet ? null : h("span", {class: "lbt-mfaces", "aria-hidden": "true"}, ((m.messages || []).length ? m.messages : []).map((x) => avatar(x.role, 14, {emblem: false, cls: ["xs", x.error ? "mute" : ""].join(" ")}))),
    quiet ? null : h("span", {class: "lbt-chev", "aria-hidden": "true"}, "▾"));
    return h("div", {class: ["lbt-mrow", m.state], role: "listitem", dataset: {mid: m.id}}, head, region);
  }
  function openMeeting(id) {
    const d = st.d, ms = (d && d.meetings) || [];
    const i = ms.findIndex((m) => m.id === id);
    if (i < 0) return;
    st.open.add(id);
    pg.set(ms, false);
    for (let k = 0; k < Math.floor(i / PAGE); k++) { const nb = pg.el.querySelector(".pager .btn-line:last-child"); if (nb) nb.click(); }
    requestAnimationFrame(() => {
      const row = pg.el.querySelector(`[data-mid="${Number(id)}"]`);
      if (row && row.scrollIntoView) row.scrollIntoView({behavior: motion.reduced() ? "auto" : "smooth", block: "start"});
    });
  }

  function drawFoot(d) {
    put(foot, ui.card({title: "읽는 법", cls: "lbt-how"},
      h("ul", {class: "lbt-howl"},
        h("li", null, h("b", null, "AI의 의견이라 참고만 해 주세요."), " 매매는 지금처럼 두 분이 정한 고정 규칙대로예요. 분석팀은 주문도, 설정 변경도 못 해요."),
        h("li", null, h("b", null, "숫자는 코드가 모은 사실만 보고 말해요."), " 팀원은 기록에 없는 숫자를 만들지 않고 '자료 없음'이라고 써요."),
        h("li", null, h("b", null, `거래가 ${fmt.int(d && d.small_n || 20)}번 미만이면 결론을 안 내요.`), " 그 전 차이는 대부분 우연이에요."),
        h("li", null, "말풍선은 저장된 실제 발언이에요 (꾸민 문장 없음). 회의 중 표시는 기록이 '진행 중'일 때만 나와요."),
        h("li", null, d && d.bot && d.bot.idea_how_ko ? `아이디어는 가설일 뿐이에요. ${d.bot.idea_how_ko}.` : "아이디어는 가설일 뿐이에요. 채택은 두 분이 개선 후보 장부 순서대로 정해요.")),
      h("div", {class: "lb-foot"}, ui.assumeLine(["closed"], "AI가 인용한 페이퍼(연습 돈) 숫자"), ui.assumeLive("AI가 인용한 바이비트 · WOO X Pro 숫자"))));
  }

  function drawLoading() {
    put(status, motion.shimmer(1)); put(members, motion.shimmer(2, true)); put(next); put(intro); put(hero); put(foot);
  }
  function draw() {
    const d = st.d;
    if (!d) { drawLoading(); return; }
    drawHq(d);
    put(srcSlot, d.state !== "ok" && d.state !== "missing" ? sourceState(d, "분석팀 기록 (liveteam.db)") : null);
    drawIntro(d);
    drawHero(d);
    const ms = d.state === "ok" ? d.meetings || [] : [];
    pg.set(ms, true);
    put(listCount, d.state === "ok" ? `${fmt.int(ms.length)}개${ms.length >= 40 ? " (최근 40개)" : ""}` : "");
    drawFoot(d);
  }

  async function load() {
    let d;
    try { d = await ctx.api(API); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      put(stateSlot, st.d ? ui.staleNote(e, st.okAt, () => load()) : ui.errorBox(e, () => load()));
      ui.dim(body, !!st.d);
      if (!st.d) body.hidden = true;
      throw e;
    }
    if (!ctx.alive()) return;
    put(stateSlot);
    ui.dim(body, false);
    body.hidden = false;
    st.okAt = Date.now();
    const key = sameKey(d);
    if (key === st.key) return;                             // the same records again: nothing redrawn (an open transcript stays open)
    st.key = key; st.d = d;
    draw();
  }
  draw();
  load().catch(() => {});
  ctx.every(REFRESH_MS, () => load().catch(() => {}), {now: false});
  return {el, set() {}};
}
