// #/alerts — 알림 기록 (builder E). Only what is really stored somewhere the dashboard can read (/api/analysis/alerts):
// the bot's alerts (paper3.db, every level, in Korean through alertKo), the nightly checks (daily3.db), the checkpoint
// job log, the agents tick, scheduled-job failure warnings and fired price alerts. New alerts from the live stream
// slide in at the top. Old homes: 분석 › 알림 기록, 서버 상태 › 경고 table (INVENTORY.md 7, 12).
// 다듬기 7-7: identical alerts (same level, same text) fold into one row "×12 · 처음 03:10 · 마지막 05:40" that opens to
// every time (alerts-group.js; different texts never merge), and a "여기부터 새 알림 n개" line marks what came after this
// device's last look (local "alerts-seen": per viewer, wrapped storage).
import {h, ui, fmt, motion, alertKo, local, put} from "../core/pb.js";
import {LEVEL_KO, LEVEL_CLS, dayTime, rel, note} from "./server-kit.js";
import {groupAlerts, withDivider} from "./alerts-group.js";

const TABS = [{id: "bot", label: "경고"}, {id: "nightly", label: "밤 점검"}, {id: "jobs", label: "작업 기록"}, {id: "price", label: "가격 알림"}];
const LEVELS = [{id: "all", label: "전부"}, {id: "CRITICAL", label: "긴급"}, {id: "WARN", label: "주의"}, {id: "INFO", label: "정보"}];
const key = (a) => `${a.ts}|${a.text}`;
const md = (day) => String(day || "").slice(5).replace("-", "/");

export async function mount(el, ctx) {
  ctx.setTitle("알림 기록");
  const counts = h("div", {class: "server-counts"});
  el.append(ui.screenHead("알림 기록", "서버에 실제로 남아 있는 기록만"), counts);

  let tab = TABS.some((t) => t.id === local.get("alerts-tab")) ? local.get("alerts-tab") : "bot";
  let level = LEVELS.some((l) => l.id === local.get("alerts-level")) ? local.get("alerts-level") : "all";
  const panels = {bot: h("div", {class: "stack"}), nightly: h("div", {class: "stack"}), jobs: h("div", {class: "stack"}), price: h("div", {class: "stack"})};
  const body = h("div", {class: "alerts-body"});
  const showTab = (id, animate) => {
    tab = id; local.set("alerts-tab", id);
    put(body, panels[id]);
    if (animate) motion.swap(body);
  };
  el.append(ui.seg(TABS, tab, (id) => showTab(id, true), {label: "알림 종류", scroll: true}), body);

  // ---------------------------------------------------------------- 경고 (the bot's own alerts)
  const fresh = new Set();
  const seenRaw = local.get("alerts-seen", null);         // this device's last look (ms), null on the first visit
  const seenAt = seenRaw != null && Number.isFinite(Number(seenRaw)) ? Number(seenRaw) : null;
  const opened = new Set();             // group keys opened on this visit (kept through the 60 s refresh)
  const list = ui.searchList({size: 10, placeholder: "계좌·내용 찾기", empty: "이 수준의 기록이 없습니다",
    match: (g, q) => !g.divider && (String(g.ko).toLowerCase().includes(q) || String(g.text).toLowerCase().includes(q)),
    row: (g) => (g.divider ? newLine(g) : groupRow(g))});
  /** "▲ 여기부터 위로 새 알림 n개": after the groups that carry alerts newer than this device's last look. */
  const newLine = (d) => h("div", {class: "alerts-new", role: "listitem", "aria-label": `여기부터 위로 새 알림 ${d.n}개`},
    h("b", null, `▲ 여기부터 위로 새 알림 ${fmt.int(d.n)}개`), h("small", null, `아래는 지난번에 본 것 (${dayTime(d.seen)}까지)`));
  const sameDay = (x, y) => fmt.kstMidnight(x) === fmt.kstMidnight(y);
  function groupRow(g) {
    const acct = /^\[([^\]]+@[^\]]+)\]/.exec(g.text);
    const many = g.n > 1;
    let fold = null, region = null;
    if (many) {
      const when = sameDay(g.first, g.last) ? `처음 ${fmt.hm(g.first)} · 마지막 ${fmt.hm(g.last)} (${dayTime(g.last).split(" ")[0]})`
        : `처음 ${dayTime(g.first)} · 마지막 ${dayTime(g.last)}`;
      const open = opened.has(g.key);
      const shown = g.items.slice(0, 30);
      region = h("div", {class: "alerts-times", hidden: !open},
        shown.map((a) => h("span", {class: "num"}, sameDay(a.ts, g.last) ? fmt.hm(a.ts) : dayTime(a.ts))),
        g.n > shown.length ? h("span", {class: "muted"}, `외 ${fmt.int(g.n - shown.length)}번`) : null);
      fold = h("button", {class: "alerts-fold", type: "button", "aria-expanded": String(open), title: "같은 알림이 온 시각 모두 보기"},
        h("b", {class: "num"}, `×${fmt.int(g.n)}`), ` · ${when}`, h("i", {class: "alerts-car", "aria-hidden": "true"}));
      fold.addEventListener("click", () => {
        const o = fold.getAttribute("aria-expanded") !== "true";
        fold.setAttribute("aria-expanded", String(o));
        if (o) opened.add(g.key); else opened.delete(g.key);
        motion.expand(region, o);
      });
    }
    const r = h("div", {class: ["server-row", "alerts-row", many ? "many" : ""], role: "listitem"},
      h("div", {class: "body"}, ui.moreText(g.ko, 2)),
      h("div", {class: "side-r"}, ui.pill(LEVEL_KO[g.level] || String(g.level || "—"), LEVEL_CLS[g.level] || "thin")),
      h("div", {class: "meta"}, many ? fold : h("span", null, `${dayTime(g.last)} · ${rel(g.last)}`),
        acct ? h("a", {href: ctx.href("account", acct[1])}, "계좌 보기") : null),
      region);
    // a real new arrival (live stream) slides in once
    if (g.items.some((a) => fresh.delete(key(a)))) motion.slideIn(r);
    return r;
  }
  const levelSeg = ui.seg(LEVELS, level, (id) => { level = id; local.set("alerts-level", id); paintBot(true); }, {label: "수준"});
  const botNote = note();
  panels.bot.append(ui.card({plate: "봇 경고·기록", sub: "paper3.db · 최근 200건까지"}, levelSeg, list.el, botNote,
    ui.assume("closed", "경고 속 잔고·증거금은 모의 계좌의 숫자")));

  // ---------------------------------------------------------------- 밤 점검 (daily3.db)
  const nightPg = ui.pager({size: 7, empty: "밤 점검 기록이 없습니다 (daily3.db 없음)", row: nightRow});
  const mmPg = ui.pager({size: 10, empty: "", row: (m) => h("div", {class: "server-row", role: "listitem"},
    h("div", {class: "body"}, h("a", {href: ctx.href("account", m.account_id), title: m.account_id}, fmt.idName(m.account_id))),
    h("div", {class: "side-r"}, m.label ? ui.pill(m.label, "warn") : ui.pill("설명 없음", "bad")),
    h("div", {class: "meta"}, h("span", null, `${md(m.day)} 점검`)))});
  const mmCard = ui.card({plate: "재계산이 다른 계좌"}, mmPg.el, note("early_kline = 거래소 1분봉이 확정되기 전에 읽어서 생긴 차이로, 계산 오류가 아닙니다."));
  panels.nightly.append(ui.card({plate: "밤 점검", sub: "최근 14일"},
    note("매일 09:20 코드가 하루치 거래를 처음부터 다시 계산해 실제 기록과 맞춰 봅니다."), nightPg.el), mmCard);

  // ---------------------------------------------------------------- 작업 기록 (agents tick, job failures, checkpoint log)
  const tickEl = h("div", {class: "stack tight"});
  const failPg = ui.pager({size: 10, empty: "기록 없음 (이 서버에 실패 경고 기록이 없거나 읽을 수 없음)", row: (f) => h("div", {class: "server-row", role: "listitem"},
    h("div", {class: "body"}, h("b", null, f.job_ko || f.unit)), h("div", {class: "side-r"}, ui.pill(md(f.day), "warn")),
    h("div", {class: "meta"}, h("span", null, `알린 시각 ${dayTime(f.ts)}`), h("span", {class: "mono"}, String(f.unit || ""))))});
  const cpPg = ui.pager({size: 10, empty: "아직 기록 없음 (판정 날에만 남깁니다)", row: (j) => h("div", {class: "server-row", role: "listitem"},
    h("div", {class: "body"}, ui.moreText(String(j.text || ""), 2)), h("div", {class: "side-r"}, h("span", {class: "t"}, dayTime(j.ts))))});
  panels.jobs.append(ui.card({plate: "에이전트 마지막 점검"}, tickEl),
    ui.card({plate: "예약 작업 실패 경고", sub: "그날 첫 번만 남김"}, failPg.el),
    ui.card({plate: "체크포인트 작업 기록"}, cpPg.el));

  // ---------------------------------------------------------------- 가격 알림 (fired)
  const pricePg = ui.pager({size: 10, empty: "울린 가격 알림이 없습니다.", row: (a) => h("div", {class: "server-row", role: "listitem"},
    h("div", {class: "body"}, h("b", null, fmt.coin(a.symbol)), ` ${a.direction === "above" ? "↑ 위로" : "↓ 아래로"} `, h("b", {class: "num"}, fmt.price(a.price)),
      a.note ? h("span", {class: "muted"}, ` · ${a.note}`) : null),
    h("div", {class: "side-r"}, h("span", {class: "t"}, dayTime(a.fired_ts))))});
  panels.price.append(ui.card({plate: "울린 가격 알림"}, pricePg.el,
    h("div", {class: "row wrap"}, h("a", {class: "btn-line", href: ctx.href("chart")}, "가격 알림 정하기 (차트)"))));

  const notStored = note();
  el.append(notStored);
  showTab(tab, false);

  // ---------------------------------------------------------------- data
  const st = {rows: [], d: null, savedTop: null};
  const merge = (rows) => {
    const seen = new Set(st.rows.map(key));
    for (const a of rows || []) {
      if (!a || seen.has(key(a))) continue;
      seen.add(key(a));
      st.rows.push({ts: Number(a.ts), level: a.level, text: String(a.text ?? ""), ko: alertKo(a.text)});
    }
    st.rows.sort((x, y) => y.ts - x.ts);
  };
  function paintBot(reset) {
    const groups = groupAlerts(level === "all" ? st.rows : st.rows.filter((a) => a.level === level));
    const {rows, n} = withDivider(groups, seenAt);
    list.set(rows, !reset);
    botNote.textContent = `기록 ${fmt.int(st.rows.length)}건 · 같은 알림을 묶어 ${fmt.int(groups.length)}줄` +
      (n ? ` · 지난번 본 뒤 새 알림 ${fmt.int(n)}개` : "") + (st.d && st.d.sources ? ` · 읽은 곳: ${st.d.sources.join(", ")}` : "");
    // this device has now seen everything up to the newest alert (next visit draws the line there)
    const top = st.rows.length ? st.rows[0].ts : null;
    if (top != null && Number.isFinite(top) && top !== st.savedTop) { st.savedTop = top; local.set("alerts-seen", top); }
  }
  function nightRow(n) {
    const p = n.parity || {};
    const okN = p.accounts != null ? p.accounts - (p.mismatched_accounts || 0) - (p.crash_gaps || 0) - (p.early_kline || 0) : null;
    return h("div", {class: "server-row", role: "listitem"},
      h("div", {class: "body"}, p.accounts != null ? h("span", null, h("b", null, `${fmt.int(okN)}/${fmt.int(p.accounts)}`), " 계좌 일치")
        : h("span", {class: "warn-t"}, p.note || "재계산을 하지 못함")),
      h("div", {class: "side-r"}, h("span", {class: "t"}, md(n.day))),
      h("div", {class: "meta"}, p.mismatched_accounts ? ui.pill(`불일치 ${fmt.int(p.mismatched_accounts)}`, "bad") : null,
        p.early_kline ? ui.pill(`확정 전 1분봉 ${fmt.int(p.early_kline)}`, "warn", "early_kline: 계산 오류 아님") : null,
        p.crash_gaps ? ui.pill(`재시작 공백 ${fmt.int(p.crash_gaps)}`, "thin") : null,
        h("span", null, `빠진 1분봉 ${fmt.int(n.missing_bars || 0)}`)));
  }
  function paintRest(d) {
    nightPg.set(d.nightly || [], true);
    const mm = d.mismatches || [];
    mmCard.hidden = !mm.length;
    mmPg.set(mm, true);
    const tk = d.agents_tick, ai = d.agents_ai || {};
    put(tickEl, tk ? h("p", null, h("b", {class: tk.ok === false ? "down" : "up"}, tk.ok === false ? "실패" : "정상"), ` · ${dayTime(tk.ts)} (${rel(tk.ts)})`,
      tk.ok === false && tk.why ? h("span", {class: "muted"}, ` · ${tk.why}`) : null) : ui.empty("에이전트 점검 기록이 아직 없습니다"),
      ai.failed ? h("p", {class: "down"}, `AI 호출이 연속 ${fmt.int(ai.failed)}번 답을 받지 못했습니다${ai.since ? ` (${dayTime(ai.since)}부터)` : ""}`) : null);
    failPg.set(d.job_failures || [], true);
    cpPg.set(d.checkpoint_jobs || [], true);
    pricePg.set(d.price_alerts_fired || [], true);
    notStored.textContent = `${(d.not_stored || []).join(" ")}. 위에는 서버에 실제로 남은 기록만 나옵니다.`;
  }
  async function load() {
    try {
      const d = await ctx.api("/api/analysis/alerts");
      if (!ctx.alive()) return;
      st.d = d; merge(d.bot); paintBot(false); paintRest(d);
    } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!st.d) panels.bot.prepend(ui.errorBox(e, load));
    }
  }
  ctx.watch("status", (s) => { if (s && Array.isArray(s.alerts)) { merge(s.alerts); paintBot(false); } });
  ctx.watch("health", (hl) => {
    const al = (hl && hl.bot && hl.bot.alerts_24h) || {};
    put(counts, h("span", null, "지난 24시간 · 긴급 ", h("b", {class: al.CRITICAL ? "down" : ""}, fmt.int(al.CRITICAL || 0)),
      " · 주의 ", h("b", {class: al.WARN ? "warn-t" : ""}, fmt.int(al.WARN || 0))),
      h("a", {href: ctx.href("server")}, "서버 상태 보기"));
  });
  ctx.on("alerts", (rows) => { for (const a of rows) fresh.add(key(a)); merge(rows); paintBot(false); });
  await load();
  ctx.every(60000, load, {now: false});
}

export function unmount() {}
