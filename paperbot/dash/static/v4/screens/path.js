// 졸업 길 (#/path, 매매법 › 졸업 길; grad-path): how far the project is from "a strategy that does not lose", as five
// stages from /api/v4/gradpath (dash/more/gradpath.py, read-only, background + cached): 아이디어 → 5년 시험 → 모의 계좌 →
// 30일 판정 → 실전 후보. On top a funnel in the AI-terminal look (one block per stage, its real count, the stage that is
// furthest along lit as 지금 여기; a stage with nothing says 아직 없음, the verdict before its day says 판정 전 and the
// date). Under it one card per stage: what it counts, a short list (most advanced / newest first) and for every row where
// it is stuck ("거래 12건 더 필요", "관찰 기간 10/27까지 제안 없음"); every row opens the screen that already shows its
// detail (토론방, 에이전트 방, 순위표, 계좌, 판정, 분석 › 실전 준비도). No money numbers on this page (so no assume caption);
// DeepSeek appears only as counts (owners' D10 / D11, the server leaves the rest out). 표시만, 판정 아님.
import {h, put, ui, fmt, motion} from "../core/pb.js";

const API = "/api/v4/gradpath";
const REFRESH_MS = 2 * 60 * 1000;
const PENDING_MS = 3000;
const ROWS = 6;
const STEP = ["①", "②", "③", "④", "⑤"];

/** The words a stage block shows for its count: a number, 판정 전, or 아직 없음 (never a made-up zero). */
export function countWords(st) {
  if (!st) return {big: "—", small: "아직 없음"};
  if (st.state === "wait") return {big: "판정 전", small: st.when_ko || st.none_ko || ""};
  if (st.state === "pending") return {big: "…", small: "계산 중"};
  if (st.state === "off") return {big: "—", small: "아직 없음"};
  if (!st.count) return {big: "0", small: "아직 없음"};
  return {big: fmt.int(st.count), small: st.unit || ""};
}

/** {name, arg, query} from the server -> an in-app link (null when the screen is unknown). */
export function linkOf(ctx, g) {
  if (!g || !g.name) return null;
  return ctx.href(g.name, g.arg || null, g.query || null);
}

function funnel(d, ctx) {
  const st = d.stages || [];
  const front = d.frontier;
  const blocks = st.map((x, i) => {
    const w = countWords(x);
    const here = x.id === front;
    // a button, not an anchor: the hash belongs to the router (#/path), the block only scrolls to its card
    return h("button", {type: "button", class: ["path-fseg", here ? "here" : "", x.count ? "has" : "dim", x.state === "wait" ? "wait" : ""],
      style: {"--i": String(i)}, "aria-label": `${x.ko}: ${w.big} ${here ? "지금 여기" : w.small}`,
      onclick: () => { const t = document.getElementById("path-" + x.id); if (t) t.scrollIntoView({behavior: motion.reduced() ? "auto" : "smooth", block: "start"}); }},
    h("span", {class: "path-fno"}, STEP[i] || ""),
    h("span", {class: "path-fko"}, x.ko),
    h("b", {class: "path-fbig num"}, w.big),
    h("span", {class: "path-fsm"}, here ? "지금 여기" : w.small));
  });
  const day = d.dplus != null ? `D+${fmt.int(d.dplus)}` : "";
  // the next verdict: after the first one "다음 판정"; its day passed without a record yet (hourly job) -> say so
  const nc = d.next_checkpoint;
  const nxt = !nc || !nc.ts ? "" : d.verdict_ready ? `다음 판정 ${fmt.mmdd(nc.ts)}`
    : (nc.k || 1) > 1 ? "첫 판정 기록 기다림" : `첫 판정 ${fmt.mmdd(nc.ts)}`;
  const obs = d.observe && d.observe.observing ? `관찰 기간 ${d.observe.until_ko}까지 (제안 없음)` : "";
  return h("section", {class: "path-term", "aria-label": "졸업 길 깔때기"},
    h("div", {class: "path-tline"}, h("span", {class: "path-prompt"}, "›"), h("span", {class: "path-tcmd"}, "졸업 길"),
      ...[day, nxt, obs].filter(Boolean).map((t) => h("span", {class: "path-tchip"}, t))),
    h("div", {class: "path-funnel", role: "list"}, blocks.map((b) => h("div", {role: "listitem", class: "path-fcell"}, b))),
    h("p", {class: "path-tnote"}, front
      ? "숫자는 지금 장부와 계좌에 실제로 있는 것만 셉니다. 밝은 칸이 지금 가장 멀리 온 단계입니다."
      : "아직 어느 단계에도 기록이 없습니다."));
}

function row(it, ctx) {
  const href = linkOf(ctx, it.go);
  const title = it.acct ? fmt.idName(it.acct) : it.title;
  const kids = [
    h("span", {class: "rk"}, it.tag || ""),
    h("span", {class: "lname path-title"}, title),
    it.ts ? h("span", {class: "ret path-when"}, fmt.mmdd(it.ts)) : h("span"),
    h("span", {class: "meta"}, it.sub ? h("span", null, it.sub) : null),
    // 기다리는 것 / 멈춘 이유 / 결과 / 지금 상태 (the server says which: a failed test waits for nothing)
    h("span", {class: ["path-wait", it.tone || ""]}, h("b", null, `${it.lab || "기다리는 것"} `), it.wait || "—"),
  ];
  return href ? h("a", {class: "lrow click path-row", role: "listitem", href}, kids) : h("div", {class: "lrow path-row", role: "listitem"}, kids);
}

function stageCard(x, i, d, ctx) {
  const w = countWords(x);
  const parts = (x.parts || []).filter((p) => p && p.ko);
  const more = linkOf(ctx, x.go);
  const items = (x.items || []).slice(0, ROWS + 2);
  const body = [];
  if (x.head) body.push(h("p", {class: "path-head"}, x.head));
  if (parts.length) {
    body.push(h("div", {class: "path-parts"}, parts.map((p) => {
      const href = linkOf(ctx, p.go);
      const words = [h("span", null, p.ko), h("b", {class: "num"}, fmt.int(p.n))];
      if (p.good != null && p.n) words.push(h("span", {class: "muted"}, `통과 ${fmt.int(p.good)} · 탈락 ${fmt.int(p.bad || 0)}`));
      if (p.enough != null && x.id === "paper") words.push(h("span", {class: "muted"}, `거래 ${fmt.int(d.min_trades || 30)}건 넘음 ${fmt.int(p.enough)}`));
      return href ? h("a", {class: "path-part", href}, words) : h("span", {class: "path-part"}, words);
    })));
  }
  if (x.id === "paper" && x.flips) {
    body.push(h("p", {class: "path-note"}, `비교용 동전 봇 ${fmt.int(x.flips)}개도 같이 돕니다 (후보가 아니라 기준선).`));
  }
  if (items.length) {
    body.push(h("div", {class: "plist path-list", role: "list"}, items.map((it) => row(it, ctx))));
  } else {
    body.push(h("p", {class: "path-none"}, x.none_ko || "아직 없음"));
  }
  if (x.id === "ready" && x.q6_6) body.push(h("p", {class: "path-note"}, x.q6_6));
  if (x.id === "verdict" && !d.verdict_ready) body.push(h("p", {class: "path-note"}, "판정 전에는 합격·불합격을 보여 주지 않습니다. 판정 최소 거래 수는 판정 규칙(체크포인트) 그대로입니다."));
  if (x.id === "paper") body.push(h("p", {class: "path-note"}, "딥시크는 계좌 수와 거래 수만 셉니다 (돈 숫자 없음)."));
  return ui.card({plate: `${STEP[i] || ""} ${x.ko}`, sub: `${w.big}${w.small && x.state !== "wait" ? " · " + w.small : ""}`,
    cls: ["path-stage", x.id === d.frontier ? "here" : "", x.count ? "" : "path-empty"].filter(Boolean).join(" "),
    acts: more ? [h("a", {class: "path-more", href: more}, "자세히 →")] : null, id: "path-" + x.id}, ...body);
}

export async function mount(el, ctx) {
  ctx.setTitle("졸업 길");
  el.append(ui.screenHead("졸업 길", "아이디어가 '돈을 잃지 않는 매매법'이 되기까지 어디쯤 왔나 · 설명용, 판정 아님"));
  const top = h("div", {class: "path-top"});
  const body = h("div", {class: "path-grid"});
  const foot = h("p", {class: "path-foot"});
  // round 2: what a next version could carry, with evidence grades (screens/nextver.js, its own read-only route)
  const next = h("a", {class: "btn-line path-next", href: ctx.href("nextver")}, "다음 버전 후보 장부 · 주장별 성적표 · 못 하는 아이디어 →");
  el.append(top, body, next, foot);
  put(top, motion.shimmer(3, true));
  let first = true;

  async function load() {
    let d;
    try { d = await ctx.api(API); } catch (e) {
      if (!ctx.alive()) return;
      put(top, ui.errorBox(e, load));
      return;
    }
    if (!ctx.alive()) return;
    if (!d || d.pending) {
      put(top, ui.card({plate: "졸업 길"}, h("p", {class: "muted"}, (d && d.note) || "서버가 계산하는 중입니다. 잠시 뒤 다시 봅니다."), motion.shimmer(3)));
      ctx.timeout(load, PENDING_MS);
      return;
    }
    if (d.error) { put(top, ui.card({plate: "졸업 길"}, h("p", {class: "muted"}, String(d.error)))); return; }
    put(top, funnel(d, ctx));
    put(body, ...(d.stages || []).map((x, i) => stageCard(x, i, d, ctx)));
    foot.textContent = `${d.label || "표시만"} · ${d.computed_at ? fmt.kst(d.computed_at) + " 계산" : ""}${d.stale ? " (예전 값, 다시 계산 중)" : ""}`;
    if (first) { motion.swap(body); first = false; }
  }
  await load();
  ctx.every(REFRESH_MS, load);
}

export function unmount() {}
