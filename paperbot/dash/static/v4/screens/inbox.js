// #/inbox[?p=<proposal id>] — 결재함 (review addition 8; hidden tab: the header bell opens it, the room's proposal card
// links to it). Every proposal that waits for the two owners as one card with what they need to decide (inbox-card.js:
// the change, the 5-year test per period, the staff's for / against lines, the code gate, 승인하면 / 안 누르면, then
// 승인 / 거절 with a confirm step through the existing POST /api/proposals/<id>/decide), the clicks the agents tick has
// not applied yet, and the past decisions (who, when; an approved copy's same-period return next to its parent's).
// The top line says which period the run is in: 관찰 기간 (no proposals), 두 분 OK 기간 (every copy needs the owners'
// click), after it (the approver may approve a copy alone; a new strategy always needs the owners).
// Data: GET /api/v4/approvals (dash/more/approvals.py, read-only), polled every 60 s and after a room change.
// HONESTY: a failed load is an error box with a retry (never "제안 없음"); nothing is decided by this page.
import {h, ui, fmt, motion} from "../core/pb.js";
import {proposalCard, titleOf} from "./inbox-card.js";

const STATUS_KO = {approved: "승인됨", rejected: "거절됨"};

/** The run's period in words (pure): {key: "observe" | "owner" | "after" | null, text}. */
export function periodLine(p, now = Date.now()) {
  if (!p || p.start == null) return {key: null, text: "봇이 아직 시작하지 않았습니다. 시작하면 처음 21일은 관찰 기간이라 제안이 오지 않습니다."};
  const obs = p.observe_until, ok = p.owner_ok_until;
  // the periods end at the run's start time + N days (not at midnight): "10/27 00:00" style, Korea time
  const at = (ms) => fmt.kst(ms);
  if (obs && now < obs) return {key: "observe", text: `관찰 기간 · ${at(obs)}까지는 복제 계좌 제안이 오지 않습니다 (직원들은 시험만 하고 장부에 남김). 그 뒤 ${ok ? `${at(ok)}까지는 ` : ""}제안마다 두 분의 OK가 필요합니다.`};
  if (ok && now < ok) return {key: "owner", text: `두 분 OK 기간 · ${at(ok)}까지는 복제 계좌 제안마다 두 분이 승인해야 시작합니다 (그 뒤에는 자율 승인관이 혼자 승인할 수 있음). 새 매매법 계좌는 언제나 두 분 승인.`};
  return {key: "after", text: "두 분 OK 기간이 끝났습니다 · 복제 계좌는 자율 승인관이 혼자 승인할 수 있고, 새 매매법 계좌는 언제나 두 분 승인이 필요합니다."};
}

let current = null;

export async function mount(el, ctx) {
  ctx.setTitle("결재함");
  const st = {d: null, gen: 0, focus: (ctx.params.query || {}).p || null, first: true};
  const top = h("div", {class: "stack ibx-top"});
  const body = h("div", {class: "stack ibx-body"}, motion.shimmer(4, true));
  el.append(ui.screenHead("결재함", "두 분 승인을 기다리는 제안 · 근거를 보고 여기서 바로 승인·거절"), top, body);

  // an owner in the middle of a decision (confirm step open, a note being written): a poll never redraws under them
  const editing = () => !!body.querySelector(".ibx-confirm") || [...body.querySelectorAll(".ibx-note")].some((x) => x.value || x === document.activeElement);
  async function load(force) {
    if (force !== true && st.d && editing()) return;
    const gen = ++st.gen;
    let d, ov = null;
    try {
      [d, ov] = await Promise.all([ctx.api("/api/v4/approvals"), ctx.store.need("rooms", 20000).catch(() => null)]);
    } catch (e) {
      if (e && e.name === "AbortError") return;
      if (gen === st.gen && !st.d) body.replaceChildren(ui.errorBox(e, () => load(true)));
      return;
    }
    if (gen !== st.gen || !ctx.alive()) return;
    st.d = d;
    paint(d, ov);
  }

  function paint(d, ov) {
    const pl = periodLine(d.period, d.now);
    top.replaceChildren(h("p", {class: ["ibx-period", pl.key || ""]}, pl.text));
    const kids = [];
    if (!d.ready) kids.push(ui.card({plate: "결재함"}, h("p", {class: "muted"}, "에이전트 기록(agents3.db)을 아직 읽지 못했습니다. 잠시 뒤 다시 봅니다.")));
    const w = d.waiting || [];
    kids.push(h("div", {class: "row wrap ibx-count"}, ui.plate(w.length ? `두 분 결정을 기다리는 제안 ${fmt.int(w.length)}건` : "기다리는 제안 없음"),
      w.length ? null : h("span", {class: "muted"}, d.period && d.period.observing ? "관찰 기간이라 아직 제안이 오지 않습니다." : "에이전트가 새 계좌를 제안하면 여기에 카드가 생기고 위쪽 종에 숫자가 뜹니다.")));
    const onDone = () => load(true);
    for (const c of w) kids.push(proposalCard(c, {ctx, period: d.period, ov, onDone}));
    if ((d.decided || []).length) {
      kids.push(ui.card({plate: "두 분이 결정함 · 반영 대기"}, (d.decided || []).map((c) => proposalCard(c, {ctx, period: d.period, ov, onDone}))));
    }
    kids.push(pastCard(d.past || []));
    body.replaceChildren(...kids);
    if (st.first) {
      st.first = false;
      const t = st.focus ? body.querySelector(`#ibx-${CSS.escape(String(st.focus))}`) : null;
      if (t) { t.scrollIntoView({block: "start", behavior: motion.reduced() ? "auto" : "smooth"}); motion.play(t, "enter"); }
    }
  }

  function pastCard(rows) {
    if (!rows.length) return ui.card({plate: "지난 결정"}, ui.empty("아직 결정된 제안이 없습니다"));
    const pg = ui.pager({size: 8, row: (c) => {
      const cmp = c.cmp;
      return h("div", {class: "lrow ibx-past", role: "listitem"},
        h("span", {class: "rk"}, `#${c.id}`),
        h("span", {class: "lname"}, `${c.parent ? fmt.idName(c.parent) : c.room_title || ""} · ${titleOf(c)}`),
        h("span", {class: "ret"}, ui.pill(STATUS_KO[c.status] || c.status, c.status === "approved" ? "good" : "thin")),
        h("span", {class: "meta"}, h("span", null, `${c.decider_ko || "—"} · ${fmt.kst(c.decided_ts || c.ts)}`),
          c.account_running ? h("a", {href: ctx.href("account", c.account_running.account_id)}, "계좌 보기 →") : null,
          cmp && !cmp.count_only && cmp.copy_ret != null ? h("span", null, `같은 기간 원본 `, h("b", {class: ["num", fmt.tone(cmp.parent_ret)]}, fmt.pct(cmp.parent_ret, 1)),
            " · 복제 ", h("b", {class: ["num", fmt.tone(cmp.copy_ret)]}, fmt.pct(cmp.copy_ret, 1)), ` (${fmt.mmdd(cmp.since)}부터, 거래 ${fmt.int(cmp.copy_trades)}건) `,
            cmp.small ? ui.smallSample(cmp.copy_trades) : null) : null));
    }});
    pg.set(rows);
    return ui.card({plate: "지난 결정", sub: "최근 20건 · 승인·거절한 쪽과 시각"}, pg.el,
      rows.some((c) => c.cmp && !c.cmp.count_only) ? ui.assume("closed", "복제 계좌와 원본의 같은 기간 수익률 (판정 아님)") : null);
  }

  current = (params) => {
    const p = (params.query || {}).p;
    if (p && st.d) { const t = body.querySelector(`#ibx-${CSS.escape(String(p))}`); if (t) t.scrollIntoView({block: "start"}); }
  };
  ctx.track(() => { current = null; });
  await load();
  ctx.every(60000, load);
  ctx.on("rooms", () => ctx.timeout(load, 2500));
}

export function update(params) { if (current) current(params); }

export function unmount() { current = null; }
