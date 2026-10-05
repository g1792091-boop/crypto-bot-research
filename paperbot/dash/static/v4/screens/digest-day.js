// 회의 요약 · 회의 결론 (builder D): one row per meeting of a KST day (newest first, 10 per page). A row opens smoothly to
// the lead's three lines, the step strip (lit only for the kinds really spoken), who spoke in order, the stored text of
// one turn ("회의 기록 원문"), the disagreement left open (amber), replies with 동의 / 반대 / 보완, questions, code
// results and 방 열기. Result: 결정 / 행동 없음 / 멈춤 / 한도로 멈춤, and 진행 중 only while the meeting really runs.
// GET /api/digest/day?day=YYYY-MM-DD; a row's turns come from the room's stored messages when it is opened.
import {h, put, ui, fmt, motion, serverNow} from "../core/pb.js";
import {STEPS, KIND_KO, SPEAKING, STANCE, statusPill, stripLead, triggerKo, whyOf, miniFigure, ACTION_KO, bodyLines, messageBody, roleName} from "./rooms-kit.js";

const dayKeyNow = () => fmt.dayKey(serverNow());
const shift = (day, n) => fmt.dayKey(Date.parse(`${day}T12:00:00+09:00`) + n * 86400000);
const dayMs = (day) => Date.parse(`${day}T12:00:00+09:00`);

export function makeDay(ctx) {
  const st = {day: dayKeyNow(), d: null, open: new Set(), msgs: new Map(), req: 0, roles: {}};
  const label = h("b", {class: "dg-dlabel"});
  const prev = h("button", {class: "btn-line", type: "button", "aria-label": "전날", onclick: () => go(shift(st.day, -1))}, "←");
  const next = h("button", {class: "btn-line", type: "button", "aria-label": "다음 날", onclick: () => go(shift(st.day, 1))}, "→");
  const today = h("button", {class: "btn-line", type: "button", onclick: () => go(dayKeyNow())}, "오늘");
  const sumLine = h("p", {class: "dg-sum"});
  const pager = ui.pager({size: 10, empty: "이날 열린 회의가 없습니다", row: (m) => row(m)});
  const body = h("div", {class: "dg-dbody"}, motion.shimmer(4));
  const el = h("div", {class: "dg-day stack"}, h("div", {class: "dg-nav"}, prev, label, next, today), sumLine, body,
    h("p", {class: "rk-note"}, "최신 회의가 위. 결론 요약과 숫자는 코드가 정리한 것이고, 발언 전문은 '방 열기'에서 봅니다. 단계는 실제로 말한 차례만 켜집니다."));

  function go(day) { if (day > dayKeyNow()) return; ctx.go("digest", "day", day === dayKeyNow() ? null : {d: day}); }

  // ---------------------------------------------------------------- one meeting row
  function row(m) {
    const key = String(m.round_id);
    const open = st.open.has(key);
    const trig = triggerKo(m), sum = stripLead(m.summary_ko).split("\n")[0];
    const line = !sum || sum === trig ? (m.status === "running" ? `${trig} · 회의 중` : trig) : sum.startsWith(trig) ? sum : `${trig} · ${sum}`;
    const btn = h("button", {class: "dg-rh", type: "button", "aria-expanded": String(open)},
      h("time", null, fmt.hm(m.started_ts)), h("span", {class: "dg-room"}, m.title || m.room_id),
      h("span", {class: "dg-line"}, line), statusPill(m.status));
    const region = h("div", {class: "region dg-rb", hidden: !open}, open ? detail(m) : null);
    btn.addEventListener("click", () => {
      const o = btn.getAttribute("aria-expanded") !== "true";
      btn.setAttribute("aria-expanded", String(o));
      if (o) { st.open.add(key); if (!region.firstChild) region.append(detail(m)); } else st.open.delete(key);
      li.classList.toggle("open", o);
      motion.expand(region, o);
    });
    const li = h("div", {class: ["dg-row", open ? "open" : ""], role: "listitem", dataset: {round: key}}, btn, region);
    return li;
  }

  function detail(m) {
    const kinds = new Set((m.speakers || []).map((s) => s.kind));
    const lead = (m.lead || []).length ? m.lead : stripLead(m.summary_ko).split("\n").filter(Boolean).slice(0, 3);
    const excerpt = h("div", {class: "dg-ex"}, h("span", {class: "muted"}, "발언을 고르면 회의 기록 원문이 여기에 나옵니다"));
    const srows = h("div", {class: "dg-srows", role: "list"});
    const why = whyOf(m);
    const box = h("div", {class: "dg-in"},
      why ? h("p", {class: "dg-why"}, `왜 열렸나 · ${why}`) : null,
      lead.length ? h("ol", {class: "dg-lead"}, lead.map((x) => h("li", null, x))) : null,
      stripLead(m.summary_ko).split("\n").filter(Boolean).length > ((m.lead || []).length ? 0 : 3)
        ? ui.disclosure("결론 전부 보기 (코드 요약)", h("pre", {class: "dg-full"}, stripLead(m.summary_ko))) : null,
      ui.stepStrip(STEPS, {done: STEPS.map((s) => s.id).filter((k) => kinds.has(k)), label: "회의 단계 (실제로 말한 차례만)"}),
      srows, excerpt,
      m.open_disagreement ? h("p", {class: "rk-amber"}, `◆ 갈린 의견 · ${m.open_disagreement}`) : null,
      (m.replies || []).length ? h("ul", {class: "dg-reps"}, m.replies.map((r) => h("li", null, ui.pill(...(STANCE[r.stance] || [r.stance, "thin"])),
        h("span", null, ` ${r.from_name} → ${r.to_name}`), r.point ? h("span", {class: "muted"}, ` · ${r.point}`) : null))) : null,
      (m.asks || []).length ? h("ul", {class: "dg-reps"}, m.asks.map((a) => h("li", null, `❓ ${a.from_name}의 질문 · ${a.text}`))) : null,
      (m.results || []).length ? h("div", {class: "rk-code"}, h("div", {class: "rk-code-h"}, h("b", null, "코드 계산 결과")),
        h("ul", null, m.results.map((x) => h("li", null, x)))) : null,
      h("div", {class: "dg-foot"}, h("span", null, (m.speakers || []).length ? `발언 ${(m.speakers || []).map((s) => s.name).join(" → ")}` : "발언 없음",
        ` · AI ${fmt.int(m.calls)}회`, m.action && ACTION_KO[m.action] ? ` · ${ACTION_KO[m.action]}` : ""),
      h("span", {class: "grow"}), h("a", {class: "btn-y", href: ctx.href("rooms", m.room_id)}, "방 열기")));
    // the speakers in order (names first; the stored turns fill in when the room's messages arrive)
    const pick = (turn, btn) => {
      for (const b of srows.querySelectorAll(".dg-srow")) b.classList.toggle("lit", b === btn);
      excerpt.replaceChildren(h("span", {class: "dg-exh"}, h("b", null, "● 회의 기록 원문"), ` · ${m.title}`),
        h("span", {class: "dg-exwho"}, `${turn.speaker_name || roleName(st.roles, turn.role)} · ${KIND_KO[turn.kind] || turn.kind} · ${fmt.hm(turn.ts)}`),
        messageBody(bodyLines(turn), {lines: 4}));
      motion.swap(excerpt);
    };
    const fill = (turns) => {
      srows.replaceChildren(...turns.map((t) => {
        const b = h("button", {class: "dg-srow", type: "button", role: "listitem"}, h("span", {class: "dg-sk"}, KIND_KO[t.kind] || t.kind),
          h("span", {class: "dg-who"}, miniFigure(st.roles, t.role), h("span", null, `${t.speaker_name || roleName(st.roles, t.role)}${t.ts ? ` · ${fmt.hm(t.ts)}` : ""}`)));
        if (t.text != null) b.addEventListener("click", () => pick(t, b)); else b.disabled = true;
        return b;
      }));
      const last = [...srows.querySelectorAll(".dg-srow:not(:disabled)")].pop();
      if (last) pick(turns[[...srows.children].indexOf(last)], last);
    };
    fill((m.speakers || []).map((s) => ({role: s.role, kind: s.kind, speaker_name: s.name, ts: null, text: null})));
    turnsOf(m).then((turns) => { if (turns && turns.length && box.isConnected) fill(turns); }).catch(() => {});
    return box;
  }

  /** The stored turns of one meeting (its room's messages, read when the row opens; older pages when needed). */
  async function turnsOf(m) {
    const k = String(m.round_id);
    if (st.msgs.has(k)) return st.msgs.get(k);
    let before = 0, got = [];
    for (let page = 0; page < 4; page++) {
      const d = await ctx.api(`/api/rooms/${encodeURIComponent(m.room_id)}/messages?limit=200${before ? `&before_id=${before}` : ""}`);
      const ms = d.messages || [];
      got = ms.filter((x) => x.round_id === m.round_id && (SPEAKING.has(x.kind) || x.kind === "code_result" || x.kind === "owner"));
      if (got.length || !ms.length || !d.has_more || ms[0].ts < m.started_ts) break;
      before = ms[0].id;
    }
    st.msgs.set(k, got);
    return got;
  }

  // ---------------------------------------------------------------- data
  async function load(query) {
    const want = query && /^\d{4}-\d{2}-\d{2}$/.test(query.d || "") ? query.d : dayKeyNow();
    if (want !== st.day) { st.day = want; st.d = null; st.open.clear(); }
    if (query && query.r) st.open.add(String(query.r));
    label.textContent = `${fmt.date(dayMs(st.day))}${st.day === dayKeyNow() ? " · 오늘" : ""}`;
    next.disabled = st.day >= dayKeyNow();
    const req = ++st.req;
    if (!st.d) body.replaceChildren(motion.shimmer(4));
    let d;
    try { d = await ctx.api(`/api/digest/day?day=${st.day}`); } catch (e) {
      if (req === st.req && ctx.alive() && !(e && e.name === "AbortError") && !st.d) body.replaceChildren(ui.errorBox(e, () => load({d: st.day})));
      return;
    }
    if (req !== st.req || !ctx.alive()) return;
    const same = st.d && JSON.stringify(st.d.meetings) === JSON.stringify(d.meetings);
    st.d = d;
    if (d.error) { body.replaceChildren(ui.empty(String(d.error))); sumLine.textContent = ""; return; }
    const ms = (d.meetings || []).slice().reverse();
    const kinds = Object.entries(d.by_trigger || {}).sort((a, b) => b[1].meetings - a[1].meetings).map(([tr, k]) => `${triggerKo({trigger: tr, trigger_ko: k.trigger_ko})} ${fmt.int(k.meetings)}`).join(" · ");
    const disOpen = ms.filter((m) => m.open_disagreement).length;
    put(sumLine,"회의 ", h("b", null, fmt.int(d.n || 0)), " · 갈린 채 끝남 ", h("b", null, fmt.int(disOpen)),
      " · 직원끼리 반대 ", h("b", null, fmt.int(d.disagreements || 0)), " · AI 호출 ", h("b", null, fmt.int(d.calls || 0)),
      ` · 토큰 ${fmt.compact(d.tokens || 0)}`, kinds ? h("span", {class: "muted"}, ` · ${kinds}`) : null);
    if (!pager.el.isConnected) body.replaceChildren(pager.el);
    if (!same) pager.set(ms, true);
    const target = query && query.r ? el.querySelector(`.dg-row[data-round="${window.CSS.escape(String(query.r))}"]`) : null;
    if (target) requestAnimationFrame(() => target.scrollIntoView({block: "start", behavior: motion.reduced() ? "auto" : "smooth"}));
  }

  return {el, show: load, refresh: () => { if (st.day === dayKeyNow()) load({d: st.day}); }, setRoles(r) { st.roles = r || {}; }};
}
