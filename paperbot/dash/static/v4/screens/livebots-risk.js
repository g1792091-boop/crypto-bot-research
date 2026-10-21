// 실거래 › 위험 (#/livebots/risk, owners 10/19 night): information only, nothing here halts or sends anything (the owners
// took the loss-streak and drawdown halts out on 10/19). From /api/v4/livebots/risk (dash/more/liveinsight.py risk()):
//   지금 포지션   per account its open position: what the stop costs if it is hit now (USDT, the share of the account, the
//                 net ROE: the paper's own ladder formula; the executors' at the exchange's listed fee), a locked stop as
//                 the gain it keeps, the liquidation price and how far it sits past the stop (the paper's; the executors
//                 do not record one: said so)
//   계좌          the loss streak now, the drawdown from the highest balance (추세판단 봇, owners 10/21: the paper's count its
//                 own trades only, from its start: 새 봇 시작 뒤; the executors' are their real accounts' and stay whole)
//   손절이 연달아 1, 2, 3, 4 stops in a row at the config's margin (30 %) and stop (-50 % net): the share of the account
//                 left, compounded, and what it is in each account's money
//   비상 정지     the kill file (/var/lib/paperbot/STOP) there or not, and the one command that stops both executors
// HONESTY: what is not recorded is said (never a 0); paper (연습) and real (진짜 돈) money carry their own captions; a
// failed refresh keeps the last answer dimmed with its age.
import {h, put, ui, fmt, motion, serverNow} from "../core/pb.js";
import {acctKo, acctTag, sourceState} from "./livebots-kit.js";

export const RISK_API = "/api/v4/livebots/risk";
const REFRESH_MS = 30 * 1000;


// ================================================================ pure functions (node tests)
const has = (x) => x != null && Number.isFinite(Number(x));

/** What the stop does to a position if it is hit now, in one line: {ko, tone}. */
export function stopWords(pos) {
  if (!pos) return {ko: "포지션 없음", tone: ""};
  if (!has(pos.stop_money)) return {ko: "손절선이 기록에 없어 계산하지 못했어요", tone: "warn"};
  const share = has(pos.stop_share) ? ` (계좌의 ${fmt.pct(pos.stop_share, 1)})` : "";
  const roe = has(pos.stop_roe) ? ` · 순ROE ${fmt.pct(pos.stop_roe, 1)}` : "";
  if (pos.stop_money >= 0) return {ko: `손절선이 잠금선이라 닿아도 ${fmt.money(pos.stop_money, true)} USDT${share}${roe}`, tone: "up"};
  return {ko: `지금 손절에 닿으면 ${fmt.money(pos.stop_money, true)} USDT${share}${roe}`, tone: "down"};
}

/** The liquidation line: the paper's price and distance, or why there is none. */
export function liqWords(a, pos) {
  if (!pos) return null;
  if (a.kind === "live") return "강제청산가: 실행기 기록에 없어요 (거래소 앱에서 보세요)";
  if (!has(pos.liq)) return "강제청산가 기록 없음";
  const parts = [`강제청산 ${fmt.price(pos.liq)}`];
  if (has(pos.liq_dist)) parts.push(`마크에서 ${fmt.pct(pos.liq_dist, 2, false)}`);
  if (has(pos.stop_dist)) parts.push(`손절은 ${fmt.pct(pos.stop_dist, 2, false)}`);
  if (has(pos.stop_to_liq)) parts.push(`손절선보다 ${fmt.pct(pos.stop_to_liq, 2, false)} 더 멀리`);
  return parts.join(" · ");
}

/** The paper card's line while the 추세판단 봇 runs (the server's from_ms / from_ko / n): what the streak and the peak count. */
export function fromWords(a) {
  if (!a || !has(a.from_ms)) return null;
  return `연속 손실과 최고점은 새 봇 시작(${fmt.kst(a.from_ms)}) 뒤 거래만 세요${has(a.n) ? ` · 새 봇 닫힌 거래 ${fmt.int(a.n)}번` : ""} · 잔고는 계좌 전체예요`;
}

// ================================================================ the view
/** riskView(ctx) -> {el, set()}: its own endpoint, read now and every 30 s. */
export function riskView(ctx) {
  const st = {d: null, okAt: 0, sig: ""};
  const stateSlot = h("div", {class: "lb-slot"});
  const head = h("div", {class: "lbv-intro"});
  const cards = h("div", {class: "lbv-cards"});
  const table = h("div", {class: "lbv-slot"});
  const kill = h("div", {class: "lbv-slot"});
  const body = h("div", {class: "lbv-body stack"}, head, cards,
    ui.card({title: "손절이 연달아 오면", sub: "설정의 증거금 · 손절로 계산 (복리)", cls: "lbv-card lbv-next"}, table),
    ui.card({title: "비상 정지", sub: "두 실행기를 한 번에 멈추는 파일", cls: "lbv-card lbv-kill"}, kill),
    h("div", {class: "lb-foot"}, ui.assumeLine(["open"], "페이퍼(연습): 손절 손익은 잠금 계산과 같은 순ROE 식"),
      ui.assumeLive("바이비트 · WOO X Pro: 손절 손익은 거래소 기본 수수료로 어림")));
  const el = h("div", {class: "lbv stack"}, stateSlot, body);

  function acctCard(a) {
    const name = [acctTag(a.id), h("span", {class: ["lbv-kind", a.kind]}, a.kind === "live" ? "실거래 · 진짜 돈" : "모의 · 연습 돈")];
    if (a.state !== "ok") {
      return h("section", {class: ["card", "lbv-acct", "off", "lbv-a-" + a.id]}, h("div", {class: "lbv-ah"}, ...name),
        sourceState(a, a.kind === "paper" ? "페이퍼 DB" : `${acctKo(a.id)} 실행기 DB`));
    }
    const p = a.position, w = stopWords(p);
    const dd = has(a.drawdown) ? fmt.pct(-a.drawdown, 1) : "—";
    return h("section", {class: ["card", "lbv-acct", "lbv-a-" + a.id]}, h("div", {class: "lbv-ah"}, ...name,
      h("span", {class: "lbv-bal"}, has(a.balance) ? `잔고 ${fmt.money(a.balance)} USDT` : "잔고 —")),
    p ? h("div", {class: ["lbv-pos", w.tone]},
      h("p", {class: "lbv-pl"}, h("b", null, fmt.coin(p.symbol)), ui.sideTag(p.side), ` ${fmt.lev(p.leverage)} · 진입 ${fmt.price(p.entry)} · ${p.locked ? "잠금선" : "손절선"} ${fmt.price(p.stop)}`,
        p.status === "entering" ? " · 진입 확인 중" : ""),
      h("p", {class: "lbv-stop"}, w.ko), liqWords(a, p) ? h("p", {class: "lbv-liq"}, liqWords(a, p)) : null,
      p.how_ko ? h("p", {class: "lbv-how"}, p.how_ko) : null)
      : h("p", {class: "lbv-nopos"}, "지금 포지션 없음"),
    h("div", {class: "lbv-acc"},
      h("span", null, "연속 손실 ", h("b", {class: ["num", a.streak ? "down" : ""]}, `${fmt.int(a.streak || 0)}번`),
        a.streak_from === "executor" ? h("small", {class: "muted"}, " (실행기 기록)") : a.from_ko ? h("small", {class: "muted"}, ` (${a.from_ko})`) : null),
      h("span", null, "최고점 대비 ", h("b", {class: ["num", has(a.drawdown) && a.drawdown > 0.0005 ? "down" : ""]}, dd),
        has(a.peak) ? h("small", {class: "muted"}, ` (${a.from_ko ? `${a.from_ko} ` : ""}최고 ${fmt.money(a.peak)})`) : null)),
    a.from_ko && has(a.from_ms) ? h("p", {class: "lbv-from"}, fromWords(a)) : null);
  }
  function drawTable(d) {
    const rows = d.table || [];
    if (!rows.length) { put(table, ui.note("설정의 손절이 순ROE 고정이 아니어서 (ATR 손절) 이 표는 계산하지 않아요")); return; }
    const ok = (d.accts || []).filter((a) => a.state === "ok" && has(a.balance));
    put(table, h("p", {class: "lbv-one"}, `손절 한 번 = 계좌의 약 ${fmt.pct(d.one_stop, 0, false)} (증거금 ${fmt.pct(d.margin, 0, false)} × 손절 ${fmt.pct(d.stop_roe, 0, false)}${d.stop_net ? " · 수수료·슬리피지 포함" : ""})`),
      h("div", {class: "tbl-wrap"}, h("table", {class: "tbl lbv-tbl"},
        h("thead", null, h("tr", null, h("th", {class: "l"}, "연속 손절"), h("th", null, "계좌 남는 몫"),
          ...ok.map((a) => h("th", null, acctKo(a.id))))),
        h("tbody", null, rows.map((r, i) => h("tr", null, h("td", {class: "l"}, `${fmt.int(r.n)}번`),
          h("td", {class: "num"}, `${fmt.pct(r.left, 1, false)} (${fmt.pct(-r.lost, 1)})`),
          ...ok.map((a) => h("td", {class: "num"}, has(((a.next || [])[i] || {}).money_left) ? fmt.money(a.next[i].money_left) : "—"))))))),
      ui.note(d.halts_ko || ""));
  }
  function drawKill(d) {
    const k = d.kill || {};
    put(kill, h("div", {class: "lbv-files"}, (k.files || []).map((f) => h("p", {class: ["lbv-file", f.present ? "on" : ""]},
      h("i", {class: "lbv-dot", "aria-hidden": "true"}), h("span", null, "비상 정지 파일"),
      f.present ? h("b", null, "있음 · 두 실행기 멈춤") : h("b", null, "없음"), ` ${f.path}`,
      f.from_config ? null : h("small", {class: "muted"}, " (실행기 설정을 못 읽어 기본 경로)")))),
    h("p", {class: "lbv-what"}, k.what_ko || ""),
    h("div", {class: "lbv-cmd"}, h("span", {class: "muted"}, "멈추는 명령 (서버에서)"), h("code", null, k.cmd || "sudo touch /var/lib/paperbot/STOP")));
  }
  function draw() {
    const d = st.d;
    if (!d) { put(head, motion.shimmer(1)); put(cards, motion.shimmer(3, true)); put(table); put(kill); return; }
    put(head, h("b", null, "위험 · 보여 주기만 해요"), h("span", {class: "muted"}, " · 이 화면은 아무것도 멈추지 않아요 (연패·낙폭으로 저절로 멈추는 장치 없음)"));
    put(cards, (d.accts || []).map(acctCard));
    drawTable(d); drawKill(d);
  }
  async function load() {
    let d;
    try { d = await ctx.api(RISK_API); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      put(stateSlot, st.d ? ui.staleNote(e, st.okAt, () => load()) : ui.errorBox(e, () => load()));
      ui.dim(body, !!st.d);
      throw e;
    }
    if (!ctx.alive()) return;
    st.okAt = serverNow();
    put(stateSlot);
    ui.dim(body, false);
    const sig = JSON.stringify({...d, now_ms: 0});
    if (st.d && sig === st.sig) return;
    st.d = d; st.sig = sig;
    draw();
  }
  draw();
  load().catch(() => {});
  ctx.every(REFRESH_MS, () => load().catch(() => {}), {now: false});
  return {el, set() {}};
}
