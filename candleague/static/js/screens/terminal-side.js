// 터미널 side panels (the rule bot's v4 terminal-side.js + terminal-pnl.js, copied and adapted to the 후보 리그):
//   selPanel       (left, the 후보 리그's own) 고른 포지션: the selected account — its name, role and exit rule; its open
//                  position (big 미실현 / ROE at the mark, 진입가 · 마크 · 청산가 · 손절/잠금 · 익절 · 크기 · 증거금 ·
//                  "손절에 닿으면 −x USDT", 왜 N배) or "열린 포지션 없음" with its last closed trade; its record and the
//                  five accounts of its pick (후보 · 1/4 · 청산만 · 기본값 · 동전).
//   coinPositions  (right) 이 코인 포지션: this coin's open positions of the chosen 묶음, live ROE (a row picks it).
//   pnlPanel       (right) 수익 차트: the 후보 accounts' REALIZED P&L (closed trades only; /api/pnl) — the cumulative
//                  line with a bar per hour (first 3 days), 4 hours (to 14 days) or day, 거래 · 승 · 패 · 최대 낙폭 (참고),
//                  24시간 / 7일 / 30일 / 전체, 오늘 수익 and the 수익 캘린더. 후보 전체 / 기존 36 / 딥시크.
// HONESTY: a running record, not a verdict (참고); loading, failed and really-empty are three different things, none of
// them a flat line or a 0. D11: a hidden DeepSeek account shows its side, coin and time only; the 수익 차트 of hidden
// DeepSeek accounts says so instead of drawing a zero line.
import {h, s, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as LK from "../lk.js";
import {markOf, serverNow} from "../live.js";
import {inGroup, livePnl, liveOk, waitKo} from "../poskit.js";
import {countTo} from "../v4kit.js";
import {coinShort, coinOf, sideKo, reasonKo, ROLE_KO, KIND_KO} from "../labels.js";
import {panel, acctLabel, sideTag, hiddenPos, hiddenFill, usdt, pctOf, short, fromApi, series, windowsFor, axisTicks, todayOf,
  calDays, failNote, H} from "./terminal-kit.js";

// ---------------------------------------------------------------- 고른 포지션
/** selPanel(ctx, st, hooks) -> {el, paint()} ; hooks: {selAcct(), selPos(), book(), doc()} */
export function selPanel(ctx, st, hooks) {
  const body = h("div", {class: "tm-selb"});
  const el = panel("고른 포지션", {cls: "tm-selp", scroll: true, tip: "표·차트·이 코인 포지션·체결에서 고른 계좌 (주소의 ?acct=로도 고름)"}, body);
  const led = {pnl: h("b", {class: "num tm-led"}), roe: h("b", {class: "num tm-ledsm"}), mark: h("b", {class: "num"}, "—")};
  let shownKey = null;
  const kv = (k, v, title) => h("div", {class: "tm-kv", title}, h("span", null, k), v instanceof Node ? v : h("b", {class: "num"}, v ?? "—"));
  function paint() {
    const a = hooks.selAcct();
    const p = hooks.selPos();
    const doc = hooks.doc();
    if (!a && !p) { put(body, h("p", {class: "tm-empty"}, LK.league() ? "표나 차트에서 포지션을 고르세요" : "불러오는 중")); el.sub.textContent = ""; return; }
    const acct = a || {id: p.id, role: p.role, kind: p.kind, name: p.name, tf: p.tf};
    el.sub.textContent = ROLE_KO[acct.role] || "";
    const kids = [h("div", {class: "tm-selh"}, acctLabel(acct, {role: false}), h("span", {class: ["tm-role", `r-${acct.role}`]}, ROLE_KO[acct.role] || ""),
      acct.kind ? h("span", {class: ["cl-kind", `k-${acct.kind}`]}, KIND_KO[acct.kind] || acct.kind) : null),
    acct.exit_ko || (p && p.exit_ko) ? h("p", {class: "tm-exit"}, acct.exit_ko || p.exit_ko) : null];
    if (p) {
      const hid = hiddenPos(p);
      kids.push(h("div", {class: "tm-selpos"}, sideTag(p.side), h("b", null, `${coinShort(p.coin)}USDT`), hid ? null : h("span", {class: "muted"}, ` · 격리 ${fmt.lev(p.lev)}`),
        h("span", {class: "muted num"}, ` · ${fmt.kst(p.since)} 진입`)));
      if (hid) {
        kids.push(h("p", {class: "tm-hidnote"}, h("b", null, "딥시크 금액 숨김"), " · 이 포지션은 방향·코인·시각만 보입니다 (가격·배수·손익은 두 분 설정으로 숨김, 개수만 셉니다)"));
      } else {
        const allowed = liveOk(doc);
        live();
        kids.push(h("div", {class: "tm-ledbox"}, h("div", null, h("span", {class: "tm-ledk"}, "미실현 손익 (USDT)"), led.pnl),
          h("div", {class: "r"}, h("span", {class: "tm-ledk"}, "ROE"), led.roe),
          !allowed ? h("small", {class: "tm-lednote warn-t"}, doc && doc.catching_up ? "엔진이 따라잡는 중: 지금 가격으로 계산하지 않음" : `${waitKo(doc) || "엔진 기록이 멈춤"}: 실시간 손익 감춤`) : null));
        kids.push(h("div", {class: "tm-kvs"},
          kv("진입가", fmt.price(p.entry)), kv("마크", led.mark, "마크 가격 (엔진이 강제청산을 보는 가격)"),
          kv("청산가", h("b", {class: "num warn-t"}, fmt.price(p.liq)), "진입 때 기준 (펀딩이 쌓이면 조금 달라짐)"),
          kv(p.stop_is_lock ? "잠금선" : "손절선", h("b", {class: ["num", p.stop_is_lock ? "up" : "down"]}, fmt.price(p.stop)), p.stop_is_lock ? "닿으면 수익으로 끝나는 선 (계단 잠금)" : null),
          p.tp != null ? kv("익절", h("b", {class: "num up"}, fmt.price(p.tp))) : null,
          kv("크기", p.qty == null ? "—" : `${fmt.num(p.qty, p.qty >= 100 ? 1 : 4)} ${coinShort(p.coin)}`, "진입 때 기준"),
          kv("증거금", p.margin == null ? "—" : `${fmt.num(p.margin, 2)} USDT · ${pctOf(p.margin_pct, 1, false)}`, "진입 때 잔고 대비 증거금"),
          p.stop_pnl != null ? kv(p.stop_is_lock ? "잠금에 닿으면" : "손절에 닿으면", h("b", {class: ["num", fmt.tone(p.stop_pnl)]}, `${usdt(p.stop_pnl)} USDT`),
            `증거금 대비 ${pctOf(p.stop_roe, 1)} · 나갈 때 수수료 전`) : null));
        if (p.why) {
          kids.push(h("div", {class: "tm-why"}, h("span", {class: "tm-whyk"}, `왜 ${fmt.lev(p.lev)}`), h("b", null, p.why.head_ko || ""),
            p.why.lev_ko ? h("small", null, p.why.lev_ko) : null, p.why.sub_ko ? h("small", {class: "muted"}, p.why.sub_ko) : null));
        }
      }
    } else {
      const book = hooks.book();
      const t = book && book.id === acct.id && book.trades ? book.trades[0] : null;
      const hidT = t ? hiddenFill(t, acct, doc && !doc.status ? !!doc.ds_money : !!(LK.league() && LK.league().ds_money)) : false;
      kids.push(h("p", {class: "tm-empty l"}, "지금 열린 포지션 없음"),
        t ? h("p", {class: "tm-last"}, "마지막 거래 ", sideTag(t.side), ` ${coinShort(coinOf(t.symbol))} · ${reasonKo(t.exit_reason)} · ${fmt.kst(t.exit_time)}`,
          hidT ? h("span", {class: "muted"}, " · 금액 숨김") : h("b", {class: ["num", fmt.tone(t.pnl, usdt(t.pnl))]}, ` ${usdt(t.pnl)} USDT`)) : null);
    }
    if (a) {
      kids.push(h("div", {class: "tm-kvs tm-rec"},
        kv("거래 · 승률", `${fmt.int(a.trades)}번 · ${LK.winTxt(a)}`), kv("잔고", LK.wallet(a)),
        kv("한 번 평균", LK.ret(a.mean_ret, {hiddenIf: LK.dsHidden(a)}), "닫힌 거래 한 번의 평균 손익 (거래 전 잔고 대비) · 점검의 단위"),
        kv("최대 낙폭", LK.ddTxt(a)), a.bust ? kv("상태", h("span", {class: "pp bad"}, "파산")) : null));
      const pk = LK.pickOf(a);
      const set = pk ? LK.index().sets[pk.id] : null;
      if (set) kids.push(h("div", {class: "tm-five"}, h("span", {class: "tm-fivek"}, "같은 후보의 5계좌"), LK.fiveRows(set, {short: true})));
    }
    kids.push(h("div", {class: "tm-links"}, h("a", {class: "btn-line", href: `#/account/${encodeURIComponent(acct.id)}`}, "계좌 자세히"),
      h("a", {class: "btn-line", href: "#/positions"}, "포지션 화면")));
    put(body, kids);
    shownKey = key();
  }
  /** the selection, its position and the snapshot it came from: a change rebuilds the panel, else only the live numbers move */
  const key = () => { const a = hooks.selAcct(), p = hooks.selPos(), d = hooks.doc(), b = hooks.book(); return `${a ? a.id : ""}|${p ? `${p.id}:${p.since}` : ""}|${d ? d.generated_ms : ""}|${b ? `${b.id}:${(b.trades || []).length}` : ""}|${a ? a.trades : ""}|${liveOk(d)}`; };
  /** the live numbers of the shown position at the mark (5 s): 미실현, ROE, 마크 */
  function live() {
    const p = hooks.selPos(), doc = hooks.doc();
    const allowed = liveOk(doc);
    const u = p && allowed && !hiddenPos(p) ? livePnl(p, markOf(p.coin)) : null;
    countTo(led.pnl, u ? u.pnl : null, {format: (v) => usdt(v), tone: true});
    countTo(led.roe, u && u.roe != null ? u.roe : null, {format: (v) => pctOf(v, 2), tone: true});
    led.mark.textContent = u ? fmt.price(u.mark) : "—";
  }
  return {el, paint, live, refresh() { if (key() !== shownKey) paint(); else live(); }};
}

// ---------------------------------------------------------------- 이 코인 포지션
/** coinPositions(ctx, st, onPick) -> {el, onPositions(doc), onLive(), setCoin(), setSel()} */
export function coinPositions(ctx, st, onPick) {
  const list = h("div", {class: "tm-cp", role: "list"});
  const other = h("p", {class: "tm-cpo muted", hidden: true});
  const el = panel("이 코인 포지션", {cls: "tm-mine", scroll: true, tip: "고른 묶음의 이 코인 열린 포지션 · ROE는 마크 가격 기준 (나갈 때 수수료 전) · 누르면 차트에 그 포지션의 선"}, list, other);
  const rows = new Map();
  let doc = null;
  function render() {
    if (!doc) { put(list, h("p", {class: "tm-empty"}, "불러오는 중")); return; }
    if (doc.status) { put(list, h("p", {class: "tm-empty"}, "엔진 기록 준비 중")); return; }
    const allowed = liveOk(doc);
    const all = (doc.positions || []).filter((p) => p.coin === st.coin && inGroup(p, st.grp));
    const xs = all.filter((p) => !hiddenPos(p)).sort((a, b) => (b.since || 0) - (a.since || 0));
    const L = all.filter((p) => Number(p.side) > 0).length;
    el.sub.textContent = `${coinShort(st.coin)} · ${fmt.int(all.length)}개 · 롱 ${fmt.int(L)} · 숏 ${fmt.int(all.length - L)}`;
    const nHid = all.length - xs.length;
    other.hidden = !nHid;
    other.textContent = `딥시크 ${fmt.int(nHid)}개도 열림 (금액 숨김: 개수만)`;
    if (!xs.length) { put(list, h("p", {class: "tm-empty"}, nHid ? "보이는 포지션 없음 (딥시크만)" : `고른 묶음은 ${coinShort(st.coin)}에 열린 포지션이 없습니다`)); return; }
    const nodes = xs.slice(0, 30).map((p) => {
      let r = rows.get(p.id);
      if (!r || r.key !== `${p.since}`) {
        const roe = h("b", {class: "num tm-roe"}, "—");
        const node = h("button", {type: "button", class: "tm-cr", role: "listitem", onclick: () => onPick(p.id),
          title: `${p.id} · 진입 ${fmt.price(p.entry)} · ${fmt.lev(p.lev)} · 청산가 ${fmt.price(p.liq)} (진입 때 기준) · ${fmt.kst(p.since)}`},
        sideTag(p.side), h("span", {class: "tm-cfn"}, h("i", {class: ["tm-rsq", `r-${p.role}`], title: ROLE_KO[p.role] || "", "aria-label": ROLE_KO[p.role] || ""}),
          acctLabel(LK.index().byId[p.id] || p, {role: false})), h("span", {class: "muted num"}, fmt.lev(p.lev)), roe);
        r = {key: `${p.since}`, node, roe};
        rows.set(p.id, r);
      }
      r.node.classList.toggle("on", p.id === st.sel);
      const u = allowed ? livePnl(p, markOf(p.coin)) : null;
      countTo(r.roe, u && u.roe != null ? u.roe : null, {format: (v) => pctOf(v, 1), tone: true});
      return r.node;
    });
    list.replaceChildren(h("div", {class: "tm-cr hd", "aria-hidden": "true"}, h("span", null, "방향"), h("span", null, "계좌"), h("span", null, "배수"),
      h("span", null, allowed ? "ROE" : "ROE (감춤)")), ...nodes);
  }
  return {el, onPositions(d) { doc = d; render(); }, onLive: render, setCoin() { rows.clear(); render(); }, setSel: render};
}

// ---------------------------------------------------------------- 수익 차트 (realized, the 후보 accounts)
const WD = ["월", "화", "수", "목", "금", "토", "일"];
const KINDS = [{id: "all", label: "후보 전체"}, {id: "core", label: "기존 36"}, {id: "ds", label: "딥시크"}];
let UID = 0;

/** pnlPanel(ctx) -> {el, onSnap(generated_ms), load()} */
export function pnlPanel(ctx) {
  const P = {kind: KINDS.some((k) => k.id === local.get("tm-pnl-kind", "all")) ? local.get("tm-pnl-kind", "all") : "all",
    win: local.get("tm-pnl-win", "all"), doc: null, state: "loading", at: 0, gen: null};
  const big = h("b", {class: "num tm-pbig"}, "—");
  const meta = h("p", {class: "tm-pmeta"}, "");
  const segBox = h("div", {class: "tm-pseg"});
  const chartBox = h("div", {class: "tm-pchart"});
  const todayV = h("b", {class: "num tm-tdv"}, "—"), todayK = h("span", {class: "tm-tdk"}, "");
  const calMonth = h("span", {class: "tm-calm num"}, "");
  const calBox = h("div", {class: "tm-cal"});
  const kindSel = h("select", {class: "select tm-sel tm-ksel", "aria-label": "어느 후보 계좌", title: "후보 38개 전체 · 기존 36의 후보 · 딥시크의 후보"},
    KINDS.map((k) => h("option", {value: k.id}, k.label)));
  kindSel.value = P.kind;
  kindSel.addEventListener("change", () => setKind(kindSel.value));
  const el = panel("수익 차트", {cls: "tm-pnl", tip: "후보 계좌가 닫은 거래의 실현 손익 합 (열린 포지션 빼고 · 수수료·펀딩 포함 · 한국 시간) · 선 = 누적, 막대 = 그 시간(또는 그날) 실현 · 중간 기록일 뿐 판정이 아닙니다",
    acts: [kindSel, h("span", {class: "pp ref"}, "")]},
  h("div", {class: "tm-phero"}, segBox, h("span", {class: "tm-pnum"}, big, h("span", {class: "tm-punit"}, "USDT"))),
  meta, chartBox,
  h("div", {class: "tm-today"}, h("span", {class: "tm-tdt"}, "오늘 수익"), todayK, h("span", {class: "grow"}), todayV, h("span", {class: "tm-punit"}, "USDT")),
  h("div", {class: "tm-calh"}, h("span", {class: "tm-calt"}, "수익 캘린더"), calMonth, h("span", {class: "grow"}), h("a", {class: "tm-more", href: "#/weekly"}, "주간 흐름 →")),
  calBox);

  function setKind(id) {
    if (id === P.kind) return;
    P.kind = id; local.set("tm-pnl-kind", id); kindSel.value = id;
    P.doc = null; P.state = "loading"; draw(); load();
  }
  const startMs = () => { const d = LK.league(); return d && d.start_ms ? d.start_ms : null; };
  const allHidden = () => P.doc && !P.doc.status && !P.doc.accounts && P.doc.hidden > 0;

  function drawSeg(opts, spanMs) {
    if (opts.length < 2) {
      put(segBox, h("span", {class: "tm-pwin"}, P.doc ? `${fmt.dur(Math.max(0, spanMs) / 1000)}째 · ${spanMs <= 3 * 86400000 ? "1시간마다" : spanMs <= 14 * 86400000 ? "4시간마다" : "하루마다"}` : ""));
      return;
    }
    const w = opts.find((o) => o.id === P.win) || opts[opts.length - 1];
    put(segBox, h("div", {class: "seg tm-seg", role: "tablist", "aria-label": "수익 차트 기간"}, opts.map((o) =>
      h("button", {type: "button", role: "tab", "aria-selected": String(o.id === w.id), onclick: () => { P.win = o.id; local.set("tm-pnl-win", o.id); draw(); }}, o.ko))));
  }
  function svgChart(sr) {
    const W = Math.max(200, chartBox.clientWidth || 300), Hh = Math.max(96, chartBox.clientHeight || 130);
    const bh = Math.round(Hh * 0.28), lh = Hh - bh - 18;
    const pad = (sr.hi - sr.lo) * 0.1 || 1, lo = sr.lo - pad, hi = sr.hi + pad;
    const pw = W - 50, ta = sr.x0, tb = sr.x1;
    const X = (t) => 4 + ((t - ta) / Math.max(1, tb - ta)) * pw, Y = (v) => 4 + (1 - (v - lo) / (hi - lo)) * (lh - 8);
    const dd = sr.pts.map(([t, v], i) => `${i ? "L" : "M"}${X(t).toFixed(1)},${Y(v).toFixed(1)}`).join("");
    const end = sr.pts[sr.pts.length - 1], up = end[1] >= 0, id = "tmg" + ++UID;
    const kids = [
      s("defs", null, s("linearGradient", {id, x1: 0, y1: 0, x2: 0, y2: 1}, s("stop", {offset: "0%", class: up ? "g-up" : "g-dn"}), s("stop", {offset: "100%", class: "g-0"}))),
      s("line", {class: "zero", x1: 0, x2: pw + 4, y1: Y(0).toFixed(1), y2: Y(0).toFixed(1)}),
      s("path", {class: "area", d: `${dd}L${X(tb).toFixed(1)},${Y(0).toFixed(1)}L${X(ta).toFixed(1)},${Y(0).toFixed(1)}Z`, fill: `url(#${id})`}),
      s("path", {class: ["ln", up ? "up" : "dn"], d: dd}),
      s("circle", {class: ["end", up ? "up" : "dn"], cx: X(end[0]).toFixed(1), cy: Y(end[1]).toFixed(1), r: 2.6}),
      s("text", {class: "ax", x: W - 42, y: Y(sr.hi) + 9}, short(sr.hi)),
      short(sr.lo) !== short(sr.hi) ? s("text", {class: "ax", x: W - 42, y: Y(sr.lo)}, short(sr.lo)) : null,
    ].filter(Boolean);
    const mx = Math.max(1, ...sr.bars.map((x) => Math.abs(x.pnl)));
    const base = lh + bh / 2;
    kids.push(s("line", {class: "zero", x1: 0, x2: pw + 4, y1: base, y2: base}));
    const col = Math.max(2, pw / Math.max(1, (tb - ta) / sr.step));
    for (const b of sr.bars) {
      const hgt = Math.max(1, (Math.abs(b.pnl) / mx) * (bh / 2 - 2)), cx = (X(b.t0) + X(b.t1)) / 2, bw = Math.max(2, Math.min(16, col - 1.5));
      const span = sr.step >= 24 * H ? fmt.date(b.t1 - 1) : `${fmt.kst(b.t0)} ~ ${fmt.hm(b.t1)}`;
      const tip = `${span} 실현 ${usdt(b.pnl)} USDT · 거래 ${fmt.int(b.n)} · 이김 ${fmt.int(b.w)} · 짐 ${fmt.int(b.l)} · 그때까지 누적 ${usdt(b.cum)} USDT`;
      kids.push(s("rect", {class: ["bar", b.pnl > 0 ? "up" : b.pnl < 0 ? "dn" : ""], x: (cx - bw / 2).toFixed(1), y: (b.pnl > 0 ? base - hgt : base).toFixed(1), width: bw.toFixed(1), height: hgt.toFixed(1)}),
        s("rect", {class: "hov", x: (cx - Math.max(bw, col) / 2).toFixed(1), y: 0, width: Math.max(bw, col).toFixed(1), height: lh + bh, fill: "transparent"}, s("title", null, tip)));
    }
    const leftLab = tb - ta > 3 * 86400000 ? fmt.mmdd(ta) : fmt.kst(ta);
    const fpx = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--t-2xs")) || 12;
    for (const k of axisTicks(ta, tb, pw, fpx, leftLab.length, fmt.hm, fmt.mmdd)) {
      kids.push(s("line", {class: "tk", x1: k.x.toFixed(1), x2: k.x.toFixed(1), y1: lh + bh, y2: lh + bh + 3}), s("text", {class: "ax mid", x: k.x.toFixed(1), y: Hh - 3}, k.label));
    }
    kids.push(s("text", {class: "ax", x: 4, y: Hh - 3}, leftLab), s("text", {class: "ax end", x: pw + 4, y: Hh - 3}, "지금"));
    return s("svg", {class: "tm-psvg", viewBox: `0 0 ${W} ${Hh}`, width: W, height: Hh, role: "img",
      "aria-label": `후보 실현 손익 누적 ${usdt(end[1])} USDT, ${fmt.int(sr.wins)}승 ${fmt.int(sr.losses)}패, 최대 낙폭 ${fmt.num(sr.mdd, 2)} USDT`}, kids);
  }
  function drawCurve() {
    const d = P.doc;
    if (!d || d.status || allHidden()) {
      drawSeg([], 0);
      countTo(big, null);
      todayV.textContent = "—";
      if (allHidden()) {
        meta.textContent = "";
        todayK.textContent = "금액 숨김";
        put(chartBox, h("div", {class: "tm-pnone"}, h("b", null, "딥시크 금액 숨김"), h("span", null, `딥시크 후보 ${fmt.int(d.hidden)}계좌의 돈은 두 분 설정으로 보이지 않습니다 (거래 수는 체결 기록에)`)));
      } else if (d && d.status) {
        meta.textContent = ""; todayK.textContent = "";
        put(chartBox, h("div", {class: "tm-pnone"}, h("b", null, "엔진 기록 준비 중"), h("span", null, "첫 계산이 끝나면 그려집니다")));
      } else {
        meta.textContent = ""; todayK.textContent = P.state === "failed" ? "불러오지 못함" : "불러오는 중";
        put(chartBox, P.state === "failed" ? failNote("수익 곡선 (닫힌 거래)", {retry: load, since: P.at || null}) : h("div", {class: "tm-pnone"}, h("span", null, "불러오는 중")));
      }
      return;
    }
    const now = serverNow();
    const cur = fromApi(d, startMs(), now);
    const span = now - cur.start;
    const opts = windowsFor(span);
    drawSeg(opts, span);
    const w = opts.find((o) => o.id === P.win) || opts[opts.length - 1];
    const sr = series(cur, w.ms);
    countTo(big, sr.empty ? 0 : sr.total, {format: (v) => usdt(v), tone: true});
    put(meta, h("span", null, `${fmt.int(d.accounts)}계좌 · ${w.ms ? `최근 ${w.ko} · ` : ""}`),
      sr.empty ? h("span", null, "아직 닫힌 거래 없음") : h("span", null, `거래 ${fmt.int(sr.trades)} · `, h("b", {class: "up"}, `${fmt.int(sr.wins)}승`), " ", h("b", {class: "down"}, `${fmt.int(sr.losses)}패`)),
      sr.empty ? null : h("span", {title: "최대 낙폭: 실현 손익 선이 그 전 최고점(시작 0 포함)에서 가장 깊게 내려간 만큼 (USDT) · 닫힌 거래만 · 참고"}, ` · 최대 낙폭 ${sr.mdd > 0 ? "−" : ""}${fmt.num(sr.mdd, 0)} (참고)`),
      d.hidden ? h("span", {class: "muted", title: "딥시크 금액을 숨기는 설정: 그 계좌들은 합계에서 뺍니다"}, ` · 딥시크 ${fmt.int(d.hidden)}계좌 뺌 (금액 숨김)`) : null,
      P.state === "failed" ? h("span", {class: "down"}, ` · 새로 받지 못함 (${fmt.ago(P.at, now)} 자료)`) : null);
    const td = todayOf(cur, now);
    countTo(todayV, td.pnl, {format: (v) => usdt(v), tone: true});
    todayK.textContent = td.n ? `거래 ${fmt.int(td.n)} · ${fmt.int(td.w)}승 ${fmt.int(td.l)}패` : "오늘 닫힌 거래 없음";
    todayK.title = todayK.textContent;
    put(chartBox, sr.empty ? h("div", {class: "tm-pnone"}, h("b", null, "아직 닫힌 거래 없음"), h("span", null, "후보의 첫 거래가 닫히면 그려집니다")) : svgChart(sr));
  }
  function drawCal() {
    const d = P.doc;
    if (!d || d.status) { calMonth.textContent = ""; put(calBox, null); return; }
    if (allHidden()) { calMonth.textContent = ""; put(calBox, h("p", {class: "tm-empty"}, "딥시크 금액 숨김")); return; }
    const now = serverNow();
    const cal = calDays(d.days, startMs() || now, now);
    calMonth.textContent = cal.label;
    const vs = cal.cells.filter((c) => !c.pad && c.v != null).map((c) => Math.abs(c.v)).sort((a, b) => a - b);
    const sc = vs.length ? Math.max(1, vs[Math.min(vs.length - 1, Math.floor(vs.length * 0.9))]) : 1;
    put(calBox, WD.map((w, i) => h("span", {class: ["tm-cw", i >= 5 ? "we" : ""]}, w)), cal.cells.map((c) => {
      if (c.pad) return h("span", {class: "tm-cc pad", "aria-hidden": "true"});
      const has = c.v != null, zero = !has || Math.abs(c.v) < 0.5;
      const a = zero ? 0 : 0.2 + 0.55 * Math.min(1, Math.abs(c.v) / sc);
      const lab = `${fmt.date(c.ms)} · ${c.state === "future" ? "아직 오지 않은 날" : c.state === "before" ? "시작 전" : !has ? "닫힌 거래 없음"
        : `실현 ${usdt(c.v)} USDT · 거래 ${fmt.int(c.n)} · 이김 ${fmt.int(c.w)}`}`;
      return h("span", {class: ["tm-cc", `s-${c.state}`, has ? (zero ? "flat" : c.v > 0 ? "up" : "down") : ""], style: {"--a": a.toFixed(3)}, title: lab, "aria-label": lab},
        h("span", {class: "dn num"}, String(c.d)), has ? h("span", {class: "dv num"}, zero ? "0" : short(c.v)) : null);
    }));
  }
  const draw = () => { drawCurve(); drawCal(); };
  async function load() {
    const kind = P.kind;
    try {
      const d = await ctx.api(`/api/pnl?role=cand&kind=${kind}`);
      if (!ctx.alive() || kind !== P.kind) return;
      P.doc = d; P.state = "ok"; P.at = Date.now();
    } catch (e) {
      if (e && e.name === "AbortError") return;
      P.state = "failed";
    }
    if (ctx.alive()) draw();
  }
  if (typeof ResizeObserver === "function") {
    let w = 0, hh = 0;
    const ro = new ResizeObserver(() => {
      const nw = chartBox.clientWidth, nh = chartBox.clientHeight;
      if ((Math.abs(nw - w) > 4 || Math.abs(nh - hh) > 4) && P.doc) { w = nw; hh = nh; drawCurve(); }
    });
    ro.observe(chartBox);
    if (ctx.signal && ctx.signal.addEventListener) ctx.signal.addEventListener("abort", () => ro.disconnect());
  }
  draw();
  return {
    el, load, draw,
    /** a new engine snapshot (its generated_ms): the realized line may have moved */
    onSnap(gen) { if (gen && gen !== P.gen) { P.gen = gen; load(); } },
  };
}
