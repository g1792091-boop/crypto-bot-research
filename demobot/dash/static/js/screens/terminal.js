// #/terminal[/<COIN>] 터미널 (CONTRACT 9.8, the rule bot's v4 terminal adapted to the demo lab): one screen for watching.
//   top     the coin strip (7 coins: live price, 24 h change, our long / short count of the 20x lines, the market
//           regime) and the chosen coin's line (big price, range, volume, funding and the time to it, open interest)
//   centre  the candle chart (/api/klines, 1분 ~ 일, 15분 first) with every open demo position on this coin as a price
//           line ("숏 20~50배 · −1.2% 손절", one per account entry), stops / targets on request, and entry / exit marks
//           of recent trades (trades.json); under it the tabs 포지션 (every coin, sortable) · 체결 · 확인 기간
//   right   이 코인 포지션 (P&L at the live price), 수익 차트 (home.json pnl_total, 24시간 / 전체), 수익 캘린더 (calendar.json)
//   left    신호 투표 of this coin (3 strategies x 2 timeframes, signals_now.json) and the demo fills feed (trades.json)
//   bottom  the status line: phase, live days, next tick countdown, data, the judge stage, the live data source
// Price every 5 s, candles and positions every 10 s, the snapshot files every 60 s, the clocks every second (text only).
// Paper only: no order button anywhere. Phone: one column (strip, chart, this coin, P&L, votes, fills, table).
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {isMissing} from "../api.js";
import {COINS, PHASE_KO, CONFIRM_KO, CONFIRM_CLS, reasonKo, sideKo, tfKo, trendKo} from "../labels.js";
import * as K from "../live-kit.js";

const CHART_TFS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"];
const SHORT = {S2_ST_ROC: "S2", N02_ST_KST: "N02", N04_ST_KLINGER: "N04"};

export async function mount(el, ctx) {
  await K.needCss();
  ctx.setTitle("터미널");
  const st = {
    coin: COINS.includes(ctx.params.arg) ? ctx.params.arg : COINS.includes(local.get("term-coin")) ? local.get("term-coin") : "BTCUSD",
    tf: CHART_TFS.includes(local.get("term-tf")) ? local.get("term-tf") : "15m",
    stops: local.get("term-stops", false) === true, targets: local.get("term-targets", false) === true,
    tab: local.get("term-tab", "pos"), sort: local.get("term-sort", {key: "unreal", desc: true}) || {key: "unreal", desc: true},
    win: local.get("term-pnl-win", "all"), month: null, day: null,
  };
  const D = {live: null, pos: null, trades: null, sig: null, home: null, cal: null, judge: null, status: null, regime: null};
  const priceOf = (c) => { const r = D.live && (D.live.coins || []).find((x) => x.coin === c); return r && r.ok ? r.price : null; };
  const rowOf = (c) => (D.live && (D.live.coins || []).find((x) => x.coin === c)) || null;

  // ---------------------------------------------------------------- the coin strip + the chosen coin's line
  const stripBtns = new Map();
  const strip = h("div", {class: "lv-strip", role: "tablist", "aria-label": "코인 고르기"}, COINS.map((c) => {
    const b = h("button", {type: "button", role: "tab", class: "lv-sc", "aria-selected": String(c === st.coin), onclick: () => pick(c)},
      h("b", {class: "lv-scn"}, fmt.coin(c)), h("span", {class: "lv-scp num"}, "—"), h("span", {class: "lv-scc num"}, ""),
      h("span", {class: "lv-scl num"}, ""), h("span", {class: "lv-scr"}, ""));
    stripBtns.set(c, b);
    return b;
  }));
  const hName = h("b", {class: "lv-hn"}), hPx = h("b", {class: "lv-hpx num"}, "—"), hChg = h("span", {class: "lv-hchg num"});
  const stat = (k, title) => { const v = h("b", {class: "num"}, "—"); return {v, el: h("div", {class: "lv-hs", title}, h("span", null, k), v)}; };
  const sRange = stat("24시간 범위", "24시간 동안 가장 낮은 값 ~ 가장 높은 값");
  const sVol = stat("24시간 거래대금", "24시간 동안 거래된 금액 (USDT)");
  const sFund = stat("펀딩 / 다음까지", "8시간마다 롱과 숏이 주고받는 돈. +면 롱이 숏에게 냅니다 (보통 +0.0100%)");
  const sOi = stat("미결제약정", "아직 열려 있는 계약 전체 (시장 전체, 우리 봇 아님)");
  const sOurs = stat("우리 포지션", "데모 계좌들이 이 코인에 열어 둔 진입 (20배 줄 기준 롱 / 숏 개수)");
  const hRegime = h("span", {class: "lv-hreg"});
  const headLine = h("div", {class: "lv-head"},
    h("div", {class: "lv-hid"}, hName, h("span", {class: "lv-hsub"}, "무기한 · 모의")),
    h("div", {class: "lv-hpxbox"}, hPx, hChg),
    h("div", {class: "lv-hstats"}, sRange.el, sVol.el, sFund.el, sOi.el, sOurs.el),
    hRegime);

  // ---------------------------------------------------------------- the chart
  const tfBtns = new Map();
  const tfBar = h("div", {class: "lv-tfs", role: "tablist", "aria-label": "봉 길이"}, CHART_TFS.map((tf) => {
    const b = h("button", {type: "button", role: "tab", "aria-selected": String(tf === st.tf), onclick: () => setTf(tf)}, K.TF_SHORT[tf]);
    tfBtns.set(tf, b);
    return b;
  }));
  const togStops = ui.toggle("손절선", st.stops, (v) => { st.stops = v; local.set("term-stops", v); drawLines(); }, "열린 포지션의 손절 가격을 점선으로");
  const togTgt = ui.toggle("목표선", st.targets, (v) => { st.targets = v; local.set("term-targets", v); drawLines(); }, "고정 익절(익절 xR) 포지션의 목표 가격");
  const chartBox = h("div", {class: "lv-cbox", role: "img", "aria-label": "가격 차트와 우리 포지션"});
  const legend = h("div", {class: "lv-legend num"});
  const chartMsg = h("div", {class: "lv-cmsg", hidden: true});
  const chartKey = h("div", {class: "lv-ckey"},
    h("span", null, h("i", {class: "k-up"}), "롱 진입선"), h("span", null, h("i", {class: "k-dn"}), "숏 진입선"),
    h("span", null, h("i", {class: "k-st"}), "손절선"), h("span", null, h("i", {class: "k-ar"}), "최근 진입"),
    h("span", null, h("i", {class: "k-dot"}), "청산 (익 · 손)"));
  const chartP = K.panel("차트", {cls: "lv-chartp", acts: [tfBar]},
    h("div", {class: "lv-cwrap"}, chartBox, legend, chartMsg), h("div", {class: "lv-cfoot"}, togStops, togTgt, chartKey));

  // ---------------------------------------------------------------- right: this coin, P&L, calendar
  const mineList = h("div", {class: "lv-mine"});
  const mineP = K.panel("이 코인 포지션", {cls: "lv-minep", scroll: true}, mineList);
  const pnlBig = h("b", {class: "lv-pbig num"}, "—"), pnlMeta = h("span", {class: "lv-pmeta"}), pnlBox = h("div", {class: "lv-pchart"});
  const pnlSeg = ui.seg([{id: "24h", label: "24시간"}, {id: "all", label: "전체"}], st.win, (v) => { st.win = v; local.set("term-pnl-win", v); paintPnl(); }, {label: "수익 차트 기간", cls: "lv-mseg"});
  const pnlP = K.panel("수익 차트", {cls: "lv-pnlp", sub: "모든 줄 합계"}, h("div", {class: "lv-phero"}, pnlSeg, h("span", {class: "grow"}), pnlBig), pnlMeta, pnlBox);
  const calTitle = h("span", {class: "lv-calm num"});
  const calPrev = h("button", {type: "button", class: "lv-calnav", "aria-label": "이전 달", onclick: () => moveMonth(-1)}, "◀");
  const calNext = h("button", {type: "button", class: "lv-calnav", "aria-label": "다음 달", onclick: () => moveMonth(1)}, "▶");
  const calGrid = h("div", {class: "lv-cal", role: "grid", "aria-label": "수익 캘린더"});
  const calDay = h("div", {class: "lv-calday"});
  const calP = K.panel("수익 캘린더", {cls: "lv-calp", acts: [calPrev, calTitle, calNext]}, calGrid, calDay);

  // ---------------------------------------------------------------- left: votes, fills
  const voteBox = h("div", {class: "lv-votes"});
  const voteRecent = h("div", {class: "lv-vrec"});
  const voteP = K.panel("신호 투표", {cls: "lv-votep", sub: "마지막 봉"}, voteBox, voteRecent,
    h("a", {class: "lv-more", href: "#/signals"}, "신호 화면 →"));
  const fillList = h("div", {class: "lv-feed"});
  const fillP = K.panel("데모 체결", {cls: "lv-fillp", sub: "모든 계좌 · 새것부터", scroll: true}, fillList);

  // ---------------------------------------------------------------- bottom tabs
  const tabs = ui.seg([{id: "pos", label: "포지션"}, {id: "fills", label: "체결"}, {id: "conf", label: "확인 기간"}], st.tab,
    (v) => { st.tab = v; local.set("term-tab", v); paintTable(); }, {label: "아래 표", cls: "lv-tabs"});
  const tabSum = h("span", {class: "lv-tabsum"});
  const tabBody = h("div", {class: "lv-tabbody"});
  const tableP = h("section", {class: "lv-p lv-tablep", "aria-label": "포지션 · 체결 · 확인 기간"},
    h("div", {class: "lv-ph"}, tabs, tabSum), h("div", {class: "lv-pb"}, tabBody));

  // ---------------------------------------------------------------- status line
  const stLine = h("div", {class: "lv-status", role: "status", "aria-live": "off"});
  const stNote = h("span", {class: "lv-stnote"});

  const root = h("div", {class: "lv-term"},
    h("h1", {class: "sr"}, "터미널"),
    h("div", {class: "lv-top"}, h("div", {class: "lv-stripwrap"}, strip), headLine),
    h("div", {class: "lv-grid"}, chartP,
      h("aside", {class: "lv-right", "aria-label": "이 코인과 수익"}, mineP, pnlP, calP),
      h("aside", {class: "lv-left", "aria-label": "신호 투표와 데모 체결"}, voteP, fillP),
      tableP),
    h("div", {class: "lv-foot"}, stLine, stNote));
  el.append(root);

  // ---------------------------------------------------------------- the chart object
  let chart = null;
  try { chart = await K.liveChart(chartBox, {volume: true}); } catch (e) { put(chartBox, ui.empty("차트를 그리지 못했습니다.")); }
  if (!ctx.alive()) { if (chart) chart.dispose(); return; }

  // ---------------------------------------------------------------- painting
  function pick(c) {
    if (c === st.coin || !COINS.includes(c)) return;
    st.coin = c;
    local.set("term-coin", c);
    history.replaceState(null, "", ctx.href("terminal", c));
    for (const [k, b] of stripBtns) b.setAttribute("aria-selected", String(k === c));
    paintHead(); paintMine(); paintVotes(); paintTable();
    loadKlines(false);
  }
  function setTf(tf) {
    if (tf === st.tf) return;
    st.tf = tf;
    local.set("term-tf", tf);
    for (const [k, b] of tfBtns) b.setAttribute("aria-selected", String(k === tf));
    loadKlines(false);
  }
  const posRows = () => (D.pos && !isMissing(D.pos) ? D.pos.positions || [] : []);
  const byCoin = (c) => (D.pos && !isMissing(D.pos) ? (D.pos.by_coin || []).find((x) => x.coin === c) : null);
  const regimeOf = (c) => (D.regime && !isMissing(D.regime) ? (D.regime.now || []).find((x) => x.coin === c) : null);

  function paintStrip() {
    for (const c of COINS) {
      const b = stripBtns.get(c), r = rowOf(c), bc = byCoin(c), rg = regimeOf(c);
      const [, p, chg, cnt, reg] = b.children;
      p.textContent = r && r.ok ? K.px(r.price) : "—";
      chg.textContent = r && r.ok ? fmt.pct(r.change_pct, true, 2) : "";
      chg.className = `lv-scc num ${r && r.ok ? fmt.tone(r.change_pct) : ""}`;
      put(cnt, bc ? [h("span", {class: "up"}, `롱 ${bc.long}`), " ", h("span", {class: "down"}, `숏 ${bc.short}`)] : "");
      reg.textContent = rg ? trendKo(rg.trend).replace(" 추세", "") : "";
      reg.className = `lv-scr t-${rg ? rg.trend : "none"}`;
      b.title = `${fmt.coin(c)}: ${r && r.ok ? K.px(r.price) : "시세 없음"}${bc ? ` · 우리 롱 ${bc.long} / 숏 ${bc.short} (20배 줄)` : ""}${rg ? ` · ${trendKo(rg.trend)}` : ""}`;
    }
  }
  function paintHead() {
    const r = rowOf(st.coin), bc = byCoin(st.coin), rg = regimeOf(st.coin);
    hName.textContent = `${fmt.coin(st.coin)}USDT`;
    hPx.textContent = r && r.ok ? K.px(r.price) : "—";
    hPx.className = `lv-hpx num ${r && r.ok ? fmt.tone(r.change_pct) : ""}`;
    hChg.textContent = r && r.ok ? fmt.pct(r.change_pct, true, 2) : D.live && D.live.off ? "시세 꺼짐" : D.live && D.live.unavailable ? "시세 받지 못함" : "";
    hChg.className = `lv-hchg num ${r && r.ok ? fmt.tone(r.change_pct) : "muted"}`;
    sRange.v.textContent = r && r.ok ? `${K.px(r.low)} ~ ${K.px(r.high)}` : "—";
    sVol.v.textContent = r && r.ok ? `${K.usdKo(r.quote_volume)} USDT` : "—";
    put(sFund.v, r && r.funding_rate != null ? [h("span", {class: Math.abs(r.funding_rate) >= 0.0005 ? "warn-t" : ""}, K.fundPct(r.funding_rate)), " ",
      h("span", {class: "lv-fcd"}, K.countdown(r.next_funding_ms))] : "—");
    sOi.v.textContent = r && r.open_interest != null ? `${K.usdKo(r.open_interest * (r.price || 0))} USDT` : "—";
    put(sOurs.v, bc ? [h("span", {class: "up"}, `롱 ${bc.long}`), " · ", h("span", {class: "down"}, `숏 ${bc.short}`)] : D.pos && isMissing(D.pos) ? "준비 중" : "—");
    put(hRegime, rg ? ui.regimeChips(rg.trend, rg.vol) : h("span", {class: "muted"}, "국면 기록 없음"));
  }
  function drawLines() {
    if (!chart) return;
    const groups = K.groupEntries(posRows().filter((p) => p.coin === st.coin));
    chart.lines(groups, {stops: st.stops, targets: st.targets, price: priceOf(st.coin), labels: chartBox.clientWidth < 640 ? 3 : 5});
    chart.marks([...K.tradeMarks(D.trades && !isMissing(D.trades) ? D.trades.trades : [], st.coin),
      ...groups.map((g) => ({t_ms: g.entry_ms, kind: "in", side: g.side}))]);
  }
  function paintLegend(msg) {
    const b = chart && chart.last();
    if (!b) { legend.textContent = msg || ""; return; }
    const ch = b.open ? (b.close - b.open) / b.open * 100 : null;
    put(legend, h("b", null, `${fmt.coin(st.coin)} · ${K.TF_SHORT[st.tf]}`), ` 시 ${K.px(b.open)} 고 ${K.px(b.high)} 저 ${K.px(b.low)} 종 ${K.px(b.close)} `,
      h("span", {class: fmt.tone(ch)}, fmt.pct(ch, true, 2)), msg ? h("span", {class: "muted"}, ` · ${msg}`) : null);
  }

  function paintMine() {
    const rows = posRows().filter((p) => p.coin === st.coin);
    const groups = K.groupEntries(rows);
    const price = priceOf(st.coin);
    const L = groups.filter((g) => g.side > 0).length;
    mineP.sub.textContent = D.pos && !isMissing(D.pos) ? `${fmt.coin(st.coin)} · 진입 ${groups.length}개 · 롱 ${L} · 숏 ${groups.length - L}` : "";
    if (!D.pos) { put(mineList, ui.empty("불러오는 중")); return; }
    if (isMissing(D.pos)) { put(mineList, ui.missing("포지션 자료")); return; }
    if (!groups.length) { put(mineList, ui.empty(`${fmt.coin(st.coin)}에 열린 데모 포지션이 없습니다`)); return; }
    put(mineList, h("div", {class: "lv-mr hd", "aria-hidden": "true"}, h("span", null, "방향"), h("span", null, "계좌"), h("span", null, "배수"), h("span", null, "평가 손익")),
      groups.slice(0, 40).map((g) => {
        const u = g.rows.reduce((a, p) => a + (K.liveUnreal(p, price) || 0), 0);
        const v = fmt.money(u, true);
        return h("a", {class: "lv-mr", href: K.tradeHref(ctx, g.first, "terminal"),
          title: `${g.name} · ${sideKo(g.side)} · 진입 ${K.px(g.entry)} · 손절 ${K.px(g.stop)} (${K.stopText(g, price)}) · ${g.setting_ko || ""} · ${g.exit_ko || ""}`},
        K.sideTag(g.side), h("span", {class: "lv-mn"}, g.name || g.id), h("span", {class: "muted num"}, K.levText(g.Ls)),
        h("b", {class: ["num", fmt.tone(u, v)]}, v));
      }), groups.length > 40 ? h("p", {class: "note"}, `외 ${groups.length - 40}개는 포지션 화면에서`) : null);
  }

  // the P&L chart (home.json pnl_total, every plain line summed)
  function paintPnl() {
    const pts = D.home && !isMissing(D.home) && Array.isArray(D.home.pnl_total) ? D.home.pnl_total.filter((p) => Array.isArray(p) && Number.isFinite(Number(p[1]))) : null;
    if (!D.home) { put(pnlBox, ui.empty("불러오는 중")); return; }
    if (!pts || pts.length < 2) { pnlBig.textContent = "—"; pnlMeta.textContent = ""; put(pnlBox, h("div", {class: "lv-pnone"}, h("b", null, "준비 중"), " · 수익 기록이 아직 없습니다")); return; }
    const end = Number(pts[pts.length - 1][0]);
    const win = st.win === "24h" ? pts.filter((p) => Number(p[0]) >= end - 86400000) : pts;
    const use = win.length >= 2 ? win : pts.slice(-2);
    const v0 = Number(use[0][1]), v1 = Number(use[use.length - 1][1]);
    const show = st.win === "24h" ? v1 - v0 : v1;
    const big = fmt.money(show, true);
    pnlBig.textContent = big;
    pnlBig.className = `lv-pbig num ${fmt.tone(show, big)}`;
    pnlMeta.textContent = st.win === "24h" ? `지난 24시간 변화 · 지금 누적 ${fmt.money(v1, true)}` : `실시간 시작부터 누적 · ${fmt.kst(use[0][0])} ~ ${fmt.kst(end)}`;
    put(pnlBox, pnlSvg(use));
  }
  function pnlSvg(pts) {
    const W = 300, H = 100;
    const vals = pts.map((p) => Number(p[1]));
    let lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
    if (hi === lo) { hi += 1; lo -= 1; }
    const span = hi - lo;
    hi += span * 0.06; lo -= span * 0.06;
    const t0 = Number(pts[0][0]), t1 = Number(pts[pts.length - 1][0]) || t0 + 1;
    const X = (t) => ((Number(t) - t0) / Math.max(1, t1 - t0)) * W;
    const Y = (v) => (1 - (v - lo) / (hi - lo)) * H;
    const d = pts.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)} ${Y(Number(p[1])).toFixed(1)}`).join(" ");
    const last = vals[vals.length - 1], tone = last >= 0 ? "up" : "dn";
    const zero = Y(0);
    // the lines stretch with the box; the words are HTML on top (an SVG text would stretch with it)
    return h("div", {class: "lv-pwrap"},
      K.svgOf("lv-psvg", W, H, `수익 차트: 끝 ${fmt.money(last, true)}`, [
        ["path", {class: `area ${tone}`, d: `${d} L${W} ${zero.toFixed(1)} L0 ${zero.toFixed(1)} Z`}],
        ["line", {class: "zero", x1: 0, x2: W, y1: zero, y2: zero, "vector-effect": "non-scaling-stroke"}],
        ["path", {class: `ln ${tone}`, d, "vector-effect": "non-scaling-stroke"}]]),
      h("span", {class: "lv-pax tl num"}, K.shortNum(Math.max(...vals, 0))), h("span", {class: "lv-pax bl num"}, K.shortNum(Math.min(...vals, 0))),
      h("span", {class: "lv-pax t0 num"}, fmt.kst(t0)), h("span", {class: "lv-pax t1"}, "지금"));
  }

  // the P&L calendar (calendar.json): one month, Monday first, a cell per KST day coloured by its P&L
  function months() {
    const days = D.cal && !isMissing(D.cal) ? D.cal.days || [] : [];
    return [...new Set(days.map((d) => String(d.day).slice(0, 7)))].sort();
  }
  function moveMonth(k) {
    const ms = months();
    const i = ms.indexOf(st.month);
    if (i < 0) return;
    const j = Math.max(0, Math.min(ms.length - 1, i + k));
    if (j !== i) { st.month = ms[j]; paintCal(); }
  }
  function paintCal() {
    if (!D.cal) { put(calGrid, ui.empty("불러오는 중")); return; }
    if (isMissing(D.cal) || !(D.cal.days || []).length) { put(calGrid, h("div", {class: "lv-pnone"}, h("b", null, "준비 중"), " · 날마다 기록이 아직 없습니다")); calTitle.textContent = ""; put(calDay); return; }
    const ms = months();
    if (!ms.includes(st.month)) st.month = ms[ms.length - 1];
    const byDay = new Map(D.cal.days.map((d) => [String(d.day), d]));
    const today = D.cal.days[D.cal.days.length - 1].day;
    if (!st.day || !byDay.has(st.day)) st.day = today;
    const [y, m] = st.month.split("-").map(Number);
    calTitle.textContent = `${y}년 ${m}월`;
    calPrev.disabled = ms.indexOf(st.month) <= 0;
    calNext.disabled = ms.indexOf(st.month) >= ms.length - 1;
    const first = new Date(Date.UTC(y, m - 1, 1));
    const pad = (first.getUTCDay() + 6) % 7;
    const n = new Date(Date.UTC(y, m, 0)).getUTCDate();
    const inMonth = D.cal.days.filter((d) => String(d.day).startsWith(st.month));
    const maxAbs = Math.max(1, ...inMonth.map((d) => Math.abs(Number(d.pnl_sum) || 0)));
    const cells = ["월", "화", "수", "목", "금", "토", "일"].map((w, i) => h("span", {class: ["lv-cw", i >= 5 ? "we" : ""]}, w));
    for (let i = 0; i < pad; i++) cells.push(h("span", {class: "lv-cc pad", "aria-hidden": "true"}));
    for (let dd = 1; dd <= n; dd++) {
      const key = `${st.month}-${String(dd).padStart(2, "0")}`;
      const d = byDay.get(key);
      if (!d) { cells.push(h("span", {class: "lv-cc none", title: `${m}/${dd}: 기록 없음`}, h("span", {class: "dn"}, String(dd)))); continue; }
      const v = Number(d.pnl_sum) || 0;
      const tone = !d.trades || v === 0 ? "flat" : v > 0 ? "up" : "down";
      const b = h("button", {type: "button", class: ["lv-cc", tone, key === today ? "today" : "", key === st.day ? "on" : ""],
        style: {"--a": (0.1 + 0.55 * Math.min(1, Math.abs(v) / maxAbs)).toFixed(3)},
        title: `${m}/${dd}: 거래 ${fmt.int(d.trades)}건 · 손익 합 ${fmt.money(v, true)} · 오른 줄 ${fmt.int(d.lines_up)} · 내린 줄 ${fmt.int(d.lines_down)}`,
        onclick: () => { st.day = key; paintCal(); }},
      h("span", {class: "dn"}, String(dd)), h("span", {class: "dv num"}, d.trades ? K.shortNum(v) : "—"));
      cells.push(b);
    }
    put(calGrid, cells);
    const d = byDay.get(st.day);
    if (!d) { put(calDay); return; }
    const v = fmt.money(d.pnl_sum, true);
    put(calDay, h("div", {class: "lv-cdl"}, h("b", null, d.day.slice(5).replace("-", "/")), " · 거래 ", h("b", {class: "num"}, fmt.int(d.trades)),
      "건 · 손익 합 ", ui.signed(v, fmt.tone(d.pnl_sum, v), "b"), ` · 오른 줄 ${fmt.int(d.lines_up)} · 내린 줄 ${fmt.int(d.lines_down)}`),
    d.best && d.best.id ? h("div", {class: "lv-cdl muted"}, "가장 잘 된 줄 ", h("a", {href: ctx.href("account", d.best.id)}, `${d.best.name} ${d.best.L}배`),
      ` ${fmt.money(d.best.pnl, true)}`) : null,
    d.worst && d.worst.id ? h("div", {class: "lv-cdl muted"}, "가장 안 된 줄 ", h("a", {href: ctx.href("account", d.worst.id)}, `${d.worst.name} ${d.worst.L}배`),
      ` ${fmt.money(d.worst.pnl, true)}`) : null);
  }

  // signal votes of this coin
  function paintVotes() {
    if (!D.sig) { put(voteBox, ui.empty("불러오는 중")); return; }
    if (isMissing(D.sig)) { put(voteBox, ui.missing("신호 자료")); put(voteRecent); return; }
    const vs = (D.sig.votes || []).filter((v) => v.coin === st.coin);
    if (!vs.length) { put(voteBox, ui.empty("기록 없음")); put(voteRecent); return; }
    const scale = Math.max(1, ...vs.map((v) => Math.max(Number(v.long) || 0, Number(v.short) || 0)));
    const rows = [];
    for (const strat of K.STRATS) {
      for (const tf of ["15m", "30m"]) {
        const v = vs.find((x) => x.strategy === strat && x.tf === tf);
        rows.push(h("div", {class: "lv-vrow"}, h("span", {class: "lv-vn"}, `${SHORT[strat]} · ${tfKo(tf)}`),
          v ? K.voteBar(v.long, v.short, v.settings, {scale}) : h("span", {class: "muted"}, "기록 없음")));
      }
    }
    voteP.sub.textContent = D.sig.bar_ms && D.sig.bar_ms["15m"] ? `${fmt.hm(D.sig.bar_ms["15m"])} 봉 (15분)` : "마지막 봉";
    put(voteBox, rows);
    const rec = (D.sig.recent || []).filter((r) => r.coin === st.coin).slice(0, 5);
    put(voteRecent, h("div", {class: "lv-vrh"}, "계좌가 들어간 신호 (24시간)"), rec.length ? rec.map((r) => h("div", {class: "lv-vr",
      title: (r.accounts || []).map((a) => `${a.name} (${a.setting_ko || ""})`).join("\n")},
    h("span", {class: "num muted"}, fmt.hm(r.t_ms)), K.sideTag(r.side), h("span", {class: "muted"}, tfKo(r.tf)),
    h("span", null, `계좌 ${fmt.int((r.accounts || []).length)}개`))) : h("p", {class: "lv-none"}, "없음"));
  }

  // the demo fills feed (trades.json: one row per account entry; an exit and an entry are separate events)
  function paintFills() {
    if (!D.trades) { put(fillList, ui.empty("불러오는 중")); return; }
    if (isMissing(D.trades)) { put(fillList, ui.missing("거래 자료")); return; }
    const seen = new Map();
    for (const t of D.trades.trades || []) {
      const k = `${t.account}|${t.coin}|${t.entry_ms}|${t.side}`;
      const cur = seen.get(k);
      if (!cur || Number(t.L) === 20) seen.set(k, t);
    }
    const ev = [];
    for (const t of seen.values()) {
      if (t.status === "closed" && t.exit_ms) ev.push({t_ms: Number(t.exit_ms), kind: "out", t});
      ev.push({t_ms: Number(t.entry_ms), kind: "in", t});
    }
    ev.sort((a, b) => b.t_ms - a.t_ms);
    put(fillList, ev.slice(0, 50).map((e) => {
      const t = e.t, win = Number(t.pnl) > 0;
      const tag = e.kind === "in" ? h("span", {class: "lv-tag in"}, "진입") : h("span", {class: ["lv-tag", win ? "up" : "down"]}, reasonKo(t.reason));
      const res = e.kind === "in" ? h("span", {class: "num muted"}, K.px(t.entry)) : ui.signed(fmt.r(t.R), fmt.tone(t.R, fmt.r(t.R)));
      return h("a", {class: ["lv-fr", t.coin === st.coin ? "mine" : ""], href: ctx.href("trade", t.account, {from: "terminal"}, t.key),
        title: `${fmt.kst(e.t_ms)} · ${t.name || t.account} · ${fmt.coin(t.coin)} ${sideKo(t.side)} · 20배 줄 ${e.kind === "in" ? "진입" : `손익 ${fmt.money(t.pnl, true)}`}`},
      h("span", {class: "lv-age num", dataset: {t: String(e.t_ms)}}, K.age(e.t_ms)), tag,
      h("span", {class: "lv-fc"}, h("b", null, fmt.coin(t.coin)), " ", h("span", {class: Number(t.side) > 0 ? "up" : "down"}, sideKo(t.side))),
      h("span", {class: "lv-fn"}, t.name || t.account), res);
    }));
    if (!ev.length) put(fillList, ui.empty("기록 없음"));
  }

  // the bottom table
  function paintTable() {
    const rows = posRows();
    const tradesRows = D.trades && !isMissing(D.trades) ? D.trades.trades || [] : [];
    const conf = D.judge && !isMissing(D.judge) ? D.judge.confirm || [] : [];
    tabs.querySelectorAll("button").forEach((b) => {
      const n = b.dataset.id === "pos" ? rows.length : b.dataset.id === "fills" ? tradesRows.length : conf.length;
      b.textContent = `${{pos: "포지션", fills: "체결", conf: "확인 기간"}[b.dataset.id]} ${n ? fmt.int(n) : ""}`.trim();
    });
    if (st.tab === "pos") {
      if (!D.pos) { put(tabBody, ui.empty("불러오는 중")); put(tabSum); return; }
      if (isMissing(D.pos)) { put(tabBody, ui.missing("포지션 자료")); put(tabSum); return; }
      const val = (p) => K.liveUnreal(p, priceOf(p.coin));
      const tot = rows.reduce((a, p) => a + (val(p) || 0), 0);
      const tv = fmt.money(tot, true);
      const L = rows.filter((p) => Number(p.side) > 0).length;
      put(tabSum, h("span", {class: "lv-ut"}, `줄 ${fmt.int(rows.length)}개 · 롱 ${fmt.int(L)} · 숏 ${fmt.int(rows.length - L)} · 평가 손익 합 `), ui.signed(tv, fmt.tone(tot, tv), "b"));
      if (!rows.length) { put(tabBody, ui.empty("열린 데모 포지션이 없습니다")); return; }
      const narrow = typeof matchMedia === "function" && matchMedia("(max-width: 759px)").matches;
      if (narrow) {                                 // a phone: cards (this coin first, then the biggest P&L)
        const byU = [...rows].sort((a, b) => (b.coin === st.coin) - (a.coin === st.coin) || Math.abs(val(b) || 0) - Math.abs(val(a) || 0));
        put(tabBody, K.posCards(byU.slice(0, 60), {ctx, priceOf, from: "terminal"}),
          rows.length > 60 ? h("a", {class: "lv-more", href: "#/positions"}, `나머지 ${fmt.int(rows.length - 60)}줄은 포지션 화면에서 →`) : null);
        return;
      }
      put(tabBody, K.sortTable([
        {key: "coin", label: "코인", l: true, val: (p) => p.coin, get: (p) => h("button", {type: "button", class: ["lv-coinbtn", p.coin === st.coin ? "on" : ""], onclick: () => pick(p.coin)}, fmt.coin(p.coin))},
        {key: "side", label: "방향", l: true, val: (p) => Number(p.side), get: (p) => K.sideTag(p.side)},
        {key: "name", label: "계좌", l: true, val: (p) => String(p.name || p.id), get: (p) => h("a", {href: ctx.href("account", p.id), class: "lv-an", title: p.id}, p.name || p.id)},
        {key: "L", label: "배수", val: (p) => Number(p.L), get: (p) => fmt.lev(p.L)},
        {key: "entry", label: "진입가", cls: "lv-xw", hcls: "lv-xw", get: (p) => h("span", {class: "num"}, K.px(p.entry))},
        {key: "now", label: "지금", cls: "lv-xw", hcls: "lv-xw", get: (p) => h("span", {class: "num"}, K.px(priceOf(p.coin) ?? p.last))},
        {key: "stop", label: "손절까지", val: (p) => Number(p.stop_dist_pct), get: (p) => h("span", {class: "num warn-t"}, K.stopText(p, priceOf(p.coin)))},
        {key: "unreal", label: "평가 손익", val: (p) => val(p), get: (p) => { const v = fmt.money(val(p), true); return ui.signed(v, fmt.tone(val(p), v)); }},
        {key: "roe", label: "증거금 대비", val: (p) => (Number(p.margin) ? val(p) / Number(p.margin) : null), get: (p) => {
          const r = Number(p.margin) ? val(p) / Number(p.margin) : null; const v = fmt.ratio(r); return ui.signed(v, fmt.tone(r, v)); }},
        {key: "held", label: "보유", cls: "lv-xw", hcls: "lv-xw", val: (p) => Number(p.held_ms), get: (p) => fmt.dur(Number(p.held_ms) / 1000)},
      ], rows, {sort: st.sort, cls: "lv-dense", wrapCls: "lv-flat", rowCls: (p) => (p.coin === st.coin ? "lv-on" : ""),
        onSort: (s2) => { st.sort = s2; local.set("term-sort", s2); paintTable(); },
        onRow: (p) => { location.hash = K.tradeHref(ctx, p, "terminal"); }}));
    } else if (st.tab === "fills") {
      put(tabSum, h("span", {class: "lv-ut"}, "모든 계좌의 최근 거래 (배수마다 한 줄)"));
      if (!D.trades) { put(tabBody, ui.empty("불러오는 중")); return; }
      if (isMissing(D.trades)) { put(tabBody, ui.missing("거래 자료")); return; }
      put(tabBody, ui.table([
        {label: "때", l: true, get: (t) => h("span", {class: "num"}, fmt.kst(t.status === "open" ? t.entry_ms : t.exit_ms))},
        {label: "계좌", l: true, get: (t) => h("a", {href: ctx.href("account", t.account), class: "lv-an"}, t.name || t.account)},
        {label: "코인", l: true, get: (t) => h("span", null, h("b", null, fmt.coin(t.coin)), " ", K.sideTag(t.side))},
        {label: "배수", get: (t) => fmt.lev(t.L)},
        {label: "진입 → 청산", get: (t) => h("span", {class: "num"}, K.px(t.entry), " → ", t.exit != null ? K.px(t.exit) : "—")},
        {label: "상태", get: (t) => (t.status === "open" ? ui.pill("열림", "accent") : reasonKo(t.reason))},
        {label: "R", get: (t) => ui.signed(fmt.r(t.R), fmt.tone(t.R, fmt.r(t.R)))},
        {label: "손익", get: (t) => ui.signed(fmt.money(t.pnl, true), fmt.tone(t.pnl, fmt.money(t.pnl)))},
      ], tradesRows.slice(0, 120), {cls: "lv-dense", wrapCls: "lv-flat", onRow: (t) => { location.hash = ctx.href("trade", t.account, {from: "terminal"}, t.key); }}));
    } else {
      put(tabSum, h("span", {class: "lv-ut"}, "우리 기준을 통과한 줄의 확인 기간 (통과 뒤 4주 · 거래 20건 이상)"));
      if (!D.judge) { put(tabBody, ui.empty("불러오는 중")); return; }
      if (isMissing(D.judge)) { put(tabBody, ui.missing("판정 자료")); return; }
      if (!conf.length) { put(tabBody, ui.empty("아직 확인 기간에 들어간 줄이 없습니다")); return; }
      put(tabBody, ui.table([
        {label: "줄", l: true, get: (c) => h("a", {href: ctx.href("account", c.id), class: "lv-an"}, `${c.name} ${c.L}배`)},
        {label: "상태", l: true, get: (c) => ui.pill(CONFIRM_KO[c.status] || c.status, CONFIRM_CLS[c.status] || "thin")},
        {label: "진행", l: true, get: (c) => ui.progress(c.progress, `${fmt.int(c.n)}/${fmt.int(c.need_n)}건`, "lv-prog")},
        {label: "평균 R", get: (c) => ui.signed(fmt.r(c.mean_R), fmt.tone(c.mean_R, fmt.r(c.mean_R)))},
        {label: "손익", get: (c) => ui.signed(fmt.pct(c.pnl_pct, true), fmt.tone(c.pnl_pct, fmt.pct(c.pnl_pct, true)))},
        {label: "최대 낙폭", get: (c) => fmt.ratio(c.max_dd)},
        {label: "시작", get: (c) => h("span", {class: "num"}, fmt.mmdd(c.start_ms))},
        {label: "끝 (예정)", get: (c) => h("span", {class: "num"}, fmt.mmdd(c.decided_ms || c.end_ms))},
        {label: "이유", l: true, cls: "dl-wrap2", get: (c) => h("span", {class: "muted"}, c.why_ko || "—")},
      ], conf, {cls: "lv-dense", wrapCls: "lv-flat", onRow: (c) => { location.hash = ctx.href("account", c.id); }}));
    }
  }

  // the status line
  function paintStatus() {
    const s = D.status, g = D.home && !isMissing(D.home) ? D.home.goal : null;
    const items = [];
    if (!s || isMissing(s)) items.push(h("span", {class: "lv-sti"}, h("b", null, "엔진"), " 준비 중"));
    else {
      items.push(h("span", {class: "lv-sti"}, h("i", {class: ["lv-dot", s.phase === "live" ? "ok" : s.phase === "stopped" ? "bad" : "warn"]}), h("b", null, PHASE_KO[s.phase] || "—"),
        s.phase === "live" && s.live_start_ms ? ` ${fmt.num(Math.max(0, (Date.now() - s.live_start_ms) / 86400000), 1)}일째` : ""));
      items.push(h("span", {class: "lv-sti", title: "엔진이 다음 15분봉을 처리할 때까지"}, "다음 처리까지 ", h("b", {class: "num", dataset: {cd: String(s.next_tick_ms || "")}}, K.countdown(s.next_tick_ms))));
      const okData = s.data_ok !== false && !(s.data_issues || []).length;
      items.push(h("a", {class: "lv-sti", href: "#/dataq", title: (s.data_issues || []).join("\n") || "자료 문제 없음"},
        h("i", {class: ["lv-dot", okData ? "ok" : "warn"]}), okData ? "자료 정상" : `자료 문제 ${fmt.int((s.data_issues || []).length || 1)}건`));
    }
    if (g && Array.isArray(g.stages_ko)) {
      items.push(h("a", {class: "lv-sti", href: "#/judge", title: g.line_ko || ""}, "판정 단계 ", h("b", null, g.stages_ko[g.stage] || "—"),
        h("span", {class: "muted"}, ` (${fmt.int((g.stage || 0) + 1)}/${fmt.int(g.stages_ko.length)})`)));
    } else items.push(h("span", {class: "lv-sti muted"}, "판정 단계 준비 중"));
    put(stLine, items);
    stNote.textContent = `${K.liveNote(D.live)} · 주문 버튼 없음 (모의)`;
  }

  // ---------------------------------------------------------------- loading
  async function get(path) {
    try { return await ctx.api(path); } catch (e) { if (e && e.name === "AbortError") throw e; return undefined; }
  }
  let klTok = 0, klKey = "";
  async function loadKlines(keep) {
    if (!chart) return;
    const tk = ++klTok, coin = st.coin, tf = st.tf;
    const d = await get(`/api/klines?${new URLSearchParams({coin, tf, limit: "500"})}`);
    if (tk !== klTok || !ctx.alive()) return;
    if (d === undefined) { chartMsg.hidden = false; put(chartMsg, ui.errorBox({status: 0}, () => loadKlines(false))); return; }
    if (d.off || d.unavailable || !d.bars || !(d.bars.t || []).length) {
      chartMsg.hidden = false;
      put(chartMsg, h("div", {class: "dl-missing"}, h("b", null, d.off ? "꺼짐" : "준비 중"),
        h("span", null, d.off ? " · 실시간 시세가 꺼져 있습니다 (DEMOBOT_DASH_LIVE=off)" : " · 바이낸스 봉을 아직 받지 못했습니다. 잠시 뒤 다시 받습니다.")));
      chart.set({t: []}, tf, false);
      return;
    }
    chartMsg.hidden = true;
    const key = `${coin}|${tf}`;
    chart.set(d.bars, tf, keep && key === klKey);
    klKey = key;
    drawLines();
    paintLegend(d.stale ? "새로 받지 못한 값" : "");
  }
  async function loadLive() {
    const d = await get("/api/live");
    if (d === undefined || !ctx.alive()) return;
    D.live = d;
    paintStrip(); paintHead();
    if (chart) { chart.tick(priceOf(st.coin)); paintLegend(); }
    if (st.tab === "pos") paintTable();
    paintMine(); paintStatus();
  }
  async function loadPositions() {
    const d = await get("/api/positions");
    if (d === undefined || !ctx.alive()) return;
    D.pos = d;
    paintStrip(); paintHead(); paintMine(); drawLines(); paintTable();
  }
  async function loadSnaps() {
    const [home, cal, trades, sig, judge, regime] = await Promise.all(["/api/home", "/api/calendar", "/api/trades", "/api/signals_now",
      "/api/judge", "/api/regime"].map(get));
    if (!ctx.alive()) return;
    if (home !== undefined) D.home = home;
    if (cal !== undefined) D.cal = cal;
    if (trades !== undefined) D.trades = trades;
    if (sig !== undefined) D.sig = sig;
    if (judge !== undefined) D.judge = judge;
    if (regime !== undefined) D.regime = regime;
    paintStrip(); paintHead(); paintPnl(); paintCal(); paintVotes(); paintFills(); drawLines(); paintTable(); paintStatus();
  }
  ctx.onStatus((s) => { D.status = s; paintStatus(); });

  paintHead(); paintStatus();
  await Promise.all([loadLive(), loadPositions(), loadSnaps()]);
  await loadKlines(false);
  ctx.every(5000, loadLive);
  ctx.every(10000, () => loadKlines(true));
  ctx.every(10000, loadPositions);
  ctx.every(60000, loadSnaps);
  // the clocks: countdowns and ages, text only (no request)
  ctx.every(1000, async () => {
    for (const b of root.querySelectorAll("[data-cd]")) b.textContent = K.countdown(Number(b.dataset.cd) || null);
    for (const a of root.querySelectorAll(".lv-age[data-t]")) a.textContent = K.age(Number(a.dataset.t));
    const r = rowOf(st.coin);
    const cd = sFund.v.querySelector(".lv-fcd");
    if (cd && r) cd.textContent = K.countdown(r.next_funding_ms);
  });
  return () => { if (chart) chart.dispose(); };
}
