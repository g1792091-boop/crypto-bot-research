// 추세 사냥 dashboard: hash routes, five screens (라인업, 전체 기록, 포지션, 체결, 상태) and one system's page.
// Data: the runner's snapshots through /api/* (read-only). Every element is built with h() / s() from dom.js: strings
// always go in as text, never as HTML. DeepSeek systems come without money from the server (D11); the page only says so.
import {h, s, put, local} from "./dom.js";
import * as fmt from "./fmt.js";

const MENU = [
  {id: "lineup", ko: "라인업"}, {id: "all", ko: "전체 기록"}, {id: "positions", ko: "포지션"},
  {id: "fills", ko: "체결"}, {id: "status", ko: "상태"},
];
const SIDE = {"1": "롱", "-1": "숏"};
const REASON = {stop: "손절선", stop_gap_open: "갭 손절", liquidation: "청산가", period_end_marked: "보유 중",
  coin_end: "코인 거래 종료", bust_close: "파산 정리"};
const SRC = {first_stop: "첫 손절선", add_moved_stop: "추가로 올린 손절선", chandelier: "추적 손절선"};
const FAMILY = {F1: "사냥 E1-E3", F2: "기존 36", F3: "딥시크 44", F4: "관찰 후보 38", F5: "유명 추세 규칙"};
const TF = {"15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"};
const GATE = {G1: "추세장만", NONE: "장세 무관"};
const DS_NOTE = "딥시크 매매법: 금액·가격은 보이지 않게 정해져 있습니다 (D11)";

// ---------------------------------------------------------------- data
async function api(path) {
  const r = await fetch(path, {credentials: "same-origin", cache: "no-store", headers: {Accept: "application/json"}});
  if (r.status === 401) { location.href = "/login"; throw new Error("login"); }
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
const missing = (d) => !d || d.missing === true;

// ---------------------------------------------------------------- small pieces
const coin = (sym) => String(sym || "—").replace(/USDT$/, "");
const side = (x) => SIDE[String(x)] || "—";
function stat(k, v, sub, cls) {
  return h("div", {class: "stat"}, h("div", {class: "k"}, k), h("div", {class: ["v", cls]}, v), sub ? h("div", {class: "s"}, sub) : null);
}
function pill(text, cls) { return h("span", {class: ["pill", cls]}, text); }
function labelPill(lb) { return lb ? pill(lb, lb === "정식" ? "main" : "ref") : null; }
function head(title, sub) { return h("div", {class: "head"}, h("h1", null, title), sub ? h("p", null, sub) : null); }
function card(title, ...kids) { return h("section", {class: "card"}, title ? h("h2", null, title) : null, ...kids); }
function table(cols, rows, opts = {}) {
  const thead = h("thead", null, h("tr", null, cols.map((c) => h("th", {class: [c.num ? "num" : "", c.sort ? "sort" : ""],
    onclick: c.sort ? () => opts.onSort && opts.onSort(c.key) : null, title: c.title || null},
    c.ko + (c.sort && opts.sortKey === c.key ? (opts.sortDir > 0 ? " ▲" : " ▼") : "")))));
  const tbody = h("tbody", null, rows.map((r) => h("tr", {class: [opts.rowClass ? opts.rowClass(r) : "", opts.onRow ? "click" : ""],
    onclick: opts.onRow ? () => opts.onRow(r) : null},
    cols.map((c) => { const v = c.get(r); return h("td", {class: [c.num ? "num" : "", c.cls ? c.cls(r) : ""]}, v == null ? "—" : v); }))));
  return h("div", {class: "tw"}, h("table", null, thead, tbody));
}
const tone = (x) => (x == null ? "" : x > 0 ? "up" : x < 0 ? "down" : "");
const mult = (x) => (x == null ? "—" : `×${fmt.num(x, 3)}`);
const pctOf = (x) => (x == null ? "—" : fmt.ratio(x, 1));

function spark(eq, startMs, stepMs) {
  const W = 600, H = 120, P = 6;
  if (!eq || eq.length < 2) return h("p", {class: "note"}, "곡선은 거래가 쌓이면 그려집니다");
  let lo = Math.min(...eq, 5000), hi = Math.max(...eq, 5000);
  if (hi - lo < 1e-9) { hi += 1; lo -= 1; }
  const x = (i) => P + (W - 2 * P) * i / (eq.length - 1);
  const y = (v) => H - P - (H - 2 * P) * (v - lo) / (hi - lo);
  let d = "";
  eq.forEach((v, i) => { d += `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`; });
  return s("svg", {class: "spark", viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img",
    "aria-label": `지갑 곡선 (1시간마다, ${fmt.kst(startMs)}부터)`},
    s("line", {class: "base", x1: P, x2: W - P, y1: y(5000), y2: y(5000)}),
    s("path", {class: "line", d}),
    s("text", {x: P + 2, y: 12}, fmt.money(hi)), s("text", {x: P + 2, y: H - 4}, fmt.money(lo)));
}

function tradeCols(money, withAcct) {
  const cols = [];
  if (withAcct) cols.push({ko: "계좌·시스템", get: (t) => t.label_ko || t.account});
  cols.push({ko: "코인", get: (t) => coin(t.coin)}, {ko: "방향", get: (t) => side(t.side), cls: (t) => (t.side > 0 ? "up" : "down")},
    {ko: "진입 봉 (KST)", get: (t) => fmt.kst(t.in_ms)});
  if (money) cols.push({ko: "진입가", num: true, get: (t) => (t.ds ? "숨김" : fmt.price(t.fill))});
  cols.push({ko: "추가", num: true, get: (t) => fmt.int(t.adds)});
  cols.push({ko: "청산 봉 (KST)", get: (t) => (t.open ? "보유 중" : fmt.kst(t.out_ms))},
    {ko: "이유", get: (t) => (t.open ? "—" : (REASON[t.reason] || t.reason) + (t.reason === "stop" && t.stop_source ? ` (${SRC[t.stop_source] || ""})` : ""))});
  if (money) cols.push({ko: "청산가", num: true, get: (t) => (t.ds ? "숨김" : t.open ? "—" : fmt.price(t.exit_px))},
    {ko: "손익", num: true, get: (t) => (t.ds ? (t.open ? "—" : t.win ? "이김" : "짐") : fmt.money(t.pnl, true)), cls: (t) => (t.ds ? (t.win ? "up" : "down") : tone(t.pnl))},
    {ko: "R", num: true, get: (t) => (t.ds ? "숨김" : fmt.r(t.r_mult)), cls: (t) => (t.ds ? "" : tone(t.r_mult))});
  else cols.push({ko: "결과", get: (t) => (t.open ? "—" : t.win ? "이김" : "짐"), cls: (t) => (t.open ? "" : t.win ? "up" : "down")});
  return cols;
}
function posCols(withAcct) {
  const cols = [];
  if (withAcct) cols.push({ko: "계좌·시스템", get: (p) => h("span", null, labelPill(p.lineup), " ", p.label_ko || p.account)});
  cols.push({ko: "코인", get: (p) => coin(p.coin)}, {ko: "방향", get: (p) => side(p.side), cls: (p) => (p.side > 0 ? "up" : "down")},
    {ko: "진입 봉 (KST)", get: (p) => fmt.kst(p.in_ms)},
    {ko: "진입가", num: true, get: (p) => (p.ds ? "숨김" : fmt.price(p.fill))},
    {ko: "지금 손절선", num: true, get: (p) => (p.ds ? "숨김" : stopText(p))},
    {ko: "첫 손절선", num: true, get: (p) => (p.ds ? "숨김" : fmt.price(p.first_stop))},
    {ko: "추가", num: true, get: (p) => fmt.int(p.adds)},
    {ko: "레버리지", num: true, get: (p) => (p.ds ? "숨김" : fmt.lev(p.lev))},
    {ko: "마지막 종가", num: true, get: (p) => (p.ds ? "숨김" : fmt.price(p.exit_px))},
    {ko: "평가 손익", num: true, get: (p) => (p.ds ? "숨김" : fmt.money(p.pnl, true)), cls: (p) => (p.ds ? "" : tone(p.pnl))});
  return cols;
}
function stopText(p) {
  const st = p.stop_now;
  if (!st) return "—";
  if (st.kind === "gap") return "종가 너머 (다음 봉 시가에 정리)";
  return fmt.price(st.stop) + (st.kind === "liq" ? " (청산가)" : "");
}

// ---------------------------------------------------------------- screens
const screens = {};

screens.lineup = async (el) => {
  const d = await api("/api/lineup");
  if (missing(d)) { put(el, head("라인업"), card(null, h("p", {class: "empty"}, "준비 중: 엔진이 첫 계산을 하고 있습니다"))); return; }
  const kids = [head("라인업", `10/01부터의 종이 매매 · ${fmt.kst(d.complete_ms)} KST 봉까지 반영`)];
  if (d.lineup_error) kids.push(h("p", {class: "errbox"}, `라인업 파일 오류: ${d.lineup_error} (전체 기록은 그대로 계속됩니다)`));
  if (!d.accounts || !d.accounts.length) {
    kids.push(card("라인업이 아직 비어 있습니다",
      h("p", null, "백테스트 결과(픽)가 나오면 정식·참고 계좌가 여기 먼저 나오고 텔레그램으로 진입·청산을 알립니다."),
      h("p", null, "그 사이에도 사냥 시스템 전체를 10/01부터 같은 규칙으로 기록하고 있어, 픽이 정해지는 순간 그 계좌의 기록이 이미 있습니다."),
      h("p", null, h("a", {href: "#/all"}, "전체 기록 보기 →"))));
    put(el, kids);
    return;
  }
  for (const a of d.accounts) kids.push(accountCard(a));
  put(el, kids);
};

function accountCard(a) {
  const title = [labelPill(a.label), a.name_ko, pill(a.variant_ko, a.read ? "warn" : ""), a.ds ? pill("딥시크 · 금액 숨김", "ds") : null,
    a.pick_no ? h("span", {class: "muted small"}, `픽 ${a.pick_no}번`) : null];
  if (!a.ok) return card(title, h("p", {class: "errbox"}, "이번 계산에서 오류가 났습니다 (상태 화면의 오류 참고)"));
  const st = [stat("거래", `${fmt.int(a.closed)}번`, `이김 ${fmt.int(a.wins)} · 승률 ${pctOf(a.win_share)}`),
    stat("열린 포지션", `${fmt.int(a.open_n)}개`), stat("파산", a.bust ? `예 (${a.bust_month})` : "아니오", null, a.bust ? "down" : "")];
  if (a.money) {
    st.unshift(stat("지갑 (평가)", fmt.money(a.equity_now), `시작 $5,000 · ${mult(a.multiple)}`, tone(a.multiple - 1)),
      stat("이번 달 배수", mult(a.month_M), null, tone((a.month_M || 1) - 1)),
      stat("최대 낙폭", pctOf(a.max_dd)));
  }
  const kids = [h("div", {class: "stats"}, st)];
  if (a.money) kids.push(spark(a.hourly && a.hourly.eq, a.hourly && a.hourly.start_ms));
  else kids.push(h("p", {class: "note"}, DS_NOTE));
  kids.push(h("h3", null, "열린 포지션"), a.positions && a.positions.length ? table(posCols(false), a.positions.map((p) => ({...p, ds: a.ds})))
    : h("p", {class: "note"}, "없음"));
  kids.push(h("h3", null, "오늘 체결 (KST)"), a.today && a.today.length ? table(tradeCols(a.money, false), a.today) : h("p", {class: "note"}, "없음"));
  if (a.money && a.months && a.months.length) {
    kids.push(h("h3", null, "달마다 배수"), h("p", {class: "mono small"}, a.months.map(([m, x]) => `${m} ×${fmt.num(x, 3)}`).join(" · ")));
  }
  kids.push(h("p", {class: "note"}, h("a", {href: `#/sys/${encodeURIComponent(a.system || (a.basket || [])[0] || "")}`}, "이 시스템의 전체 거래 →"),
    a.basket ? ` (바구니: ${a.basket.join(" + ")})` : ""));
  return card(title, ...kids);
}

screens.all = async (el) => {
  const d = await api("/api/systems");
  if (missing(d)) { put(el, head("전체 기록"), card(null, h("p", {class: "empty"}, "준비 중"))); return; }
  const f = local.get("allf", {fam: "", tf: "", gate: "", q: "", lu: false, sort: "closed", dir: -1});
  const box = h("div");
  const sel = (key, opts) => h("select", {onchange: (e) => { f[key] = e.target.value; draw(); }},
    opts.map(([v, ko]) => h("option", {value: v, selected: f[key] === v}, ko)));
  const filters = h("div", {class: "filters"},
    sel("fam", [["", "묶음 전체"], ...Object.entries(FAMILY)]), sel("tf", [["", "봉 전체"], ...Object.entries(TF)]),
    sel("gate", [["", "장세 전체"], ...Object.entries(GATE)]),
    h("input", {type: "search", placeholder: "이름 찾기", value: f.q, oninput: (e) => { f.q = e.target.value; draw(); }}),
    h("label", {class: "chk"}, h("input", {type: "checkbox", checked: f.lu, onchange: (e) => { f.lu = e.target.checked; draw(); }}), "라인업만"));
  const cols = [
    {ko: "시스템", key: "id", sort: true, get: (r) => h("span", null, labelPill(r.lineup), " ", r.label_ko)},
    {ko: "묶음", key: "family", sort: true, get: (r) => FAMILY[r.family] || r.family},
    {ko: "진입 신호", key: "events", sort: true, num: true, get: (r) => fmt.int(r.events), title: "장세 문 통과 전 신호 수"},
    {ko: "거래", key: "closed", sort: true, num: true, get: (r) => fmt.int(r.closed)},
    {ko: "열림", key: "open_n", sort: true, num: true, get: (r) => fmt.int(r.open_n)},
    {ko: "승률", key: "win_share", sort: true, num: true, get: (r) => pctOf(r.win_share)},
    {ko: "배수", key: "multiple", sort: true, num: true, get: (r) => (r.ds ? "숨김" : mult(r.multiple)), cls: (r) => (r.ds ? "" : tone((r.multiple || 1) - 1))},
    {ko: "이번 달", key: "month_M", sort: true, num: true, get: (r) => (r.ds ? "숨김" : mult(r.month_M))},
    {ko: "최대 낙폭", key: "max_dd", sort: true, num: true, get: (r) => (r.ds ? "숨김" : pctOf(r.max_dd))},
    {ko: "파산", key: "bust", sort: true, get: (r) => (r.bust ? "예" : "")},
  ];
  function draw() {
    local.set("allf", f);
    const q = (f.q || "").toLowerCase();
    let rows = (d.rows || []).filter((r) => (!f.fam || r.family === f.fam) && (!f.tf || r.tf === f.tf) && (!f.gate || r.gate === f.gate)
      && (!f.lu || r.lineup) && (!q || `${r.id} ${r.label_ko}`.toLowerCase().includes(q)));
    const key = f.sort, dir = f.dir;
    rows = rows.slice().sort((a, b) => {
      const va = a[key], vb = b[key];
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      return (va > vb ? 1 : va < vb ? -1 : 0) * dir;
    });
    put(box, h("p", {class: "note"}, `${fmt.int(rows.length)}개 / 전체 ${fmt.int((d.rows || []).length)}개 · 행을 누르면 그 시스템의 거래`),
      table(cols, rows, {sortKey: key, sortDir: dir, onSort: (k) => { if (f.sort === k) f.dir = -f.dir; else { f.sort = k; f.dir = -1; } draw(); },
        onRow: (r) => { location.hash = `#/sys/${encodeURIComponent(r.id)}`; }, rowClass: (r) => (r.lineup ? "lineup" : "")}));
  }
  put(el, head("전체 기록", `사냥 시스템 ${fmt.int((d.rows || []).length)}개, 10/01부터 각 $5,000 · 위험 0.5% · ${fmt.kst(d.complete_ms)} KST 봉까지`),
    card(null, filters, box, h("p", {class: "note"}, `${DS_NOTE}. 딥시크 시스템은 거래 수·승률·파산 여부만 보입니다.`)));
  draw();
};

screens.sys = async (el, arg) => {
  const d = await api(`/api/system/${encodeURIComponent(arg || "")}`).catch(() => null);
  if (!d || !d.row) { put(el, head("시스템"), card(null, h("p", {class: "empty"}, "찾을 수 없습니다"))); return; }
  const r = d.row;
  const st = [stat("거래", `${fmt.int(r.closed)}번`, `이김 ${fmt.int(r.wins)} · 승률 ${pctOf(r.win_share)}`), stat("열림", fmt.int(r.open_n)),
    stat("진입 신호", fmt.int(r.events), `장세 문 통과 ${fmt.int(r.gated)}`), stat("파산", r.bust ? "예" : "아니오")];
  if (!r.ds) st.unshift(stat("지갑 (평가)", fmt.money(r.equity_now), mult(r.multiple), tone((r.multiple || 1) - 1)), stat("최대 낙폭", pctOf(r.max_dd)));
  put(el, head(r.label_ko, `${r.id} · ${FAMILY[r.family] || r.family}`),
    card([labelPill(r.lineup), r.ds ? pill("딥시크 · 금액 숨김", "ds") : null, "요약"], h("div", {class: "stats"}, st),
      r.ds ? h("p", {class: "note"}, DS_NOTE) : spark(d.hourly && d.hourly.eq && d.hourly.eq.length > 1 ? d.hourly.eq : r.day_eq,
        d.hourly ? d.hourly.start_ms : null)),
    card("거래 (최근 100개, 새것 먼저)", d.trades.length ? table(tradeCols(!r.ds, false), d.trades) : h("p", {class: "note"}, "아직 없음")));
};

screens.positions = async (el) => {
  const d = await api("/api/positions");
  if (missing(d)) { put(el, head("포지션"), card(null, h("p", {class: "empty"}, "준비 중"))); return; }
  const rows = d.rows || [];
  const lu = rows.filter((p) => p.lineup_account);
  const rest = rows.filter((p) => !p.lineup_account);
  put(el, head("포지션", `지금 열린 포지션 · 마지막 종가로 평가 · ${fmt.kst(d.complete_ms)} KST 봉까지`),
    card("라인업 계좌", lu.length ? table(posCols(true), lu) : h("p", {class: "note"}, "없음")),
    card(`전체 시스템 (${fmt.int(rest.length)}개)`, rest.length ? table(posCols(true), rest.slice(0, 500)) : h("p", {class: "note"}, "없음"),
      rest.length > 500 ? h("p", {class: "note"}, "처음 500개만 보입니다") : null,
      h("p", {class: "note"}, "지금 손절선 = 다음 5분봉에 적용되는 손절선 (추적 손절선·추가 진입으로 옮겨진 값).")));
};

screens.fills = async (el) => {
  const [lu, tr] = await Promise.all([api("/api/lineup"), api("/api/trades")]);
  const mine = [];
  for (const a of (lu && lu.accounts) || []) for (const t of a.trades || []) if (!t.open) mine.push({...t, label_ko: `${a.label} · ${a.name_ko} (${a.variant_ko})`, ds: a.ds});
  mine.sort((x, y) => y.out_ms - x.out_ms);
  const all = ((tr && tr.recent) || []);
  const money = all.filter((t) => !t.ds), ds = all.filter((t) => t.ds);
  put(el, head("체결", "닫힌 거래, 새것 먼저"),
    card("라인업 계좌", mine.length ? table(tradeCols(true, true), mine)
      : h("p", {class: "note"}, "없음")),
    card(`전체 시스템 · 기존 매매법과 사냥 진입 (${fmt.int(money.length)}개)`, money.length ? table(tradeCols(true, true), money) : h("p", {class: "note"}, "없음")),
    card(`전체 시스템 · 딥시크 (${fmt.int(ds.length)}개)`, ds.length ? table(tradeCols(false, true), ds) : h("p", {class: "note"}, "없음"),
      h("p", {class: "note"}, DS_NOTE)));
};

screens.status = async (el) => {
  const d = await api("/api/status");
  if (missing(d)) { put(el, head("상태"), card(null, h("p", {class: "empty"}, "준비 중: 엔진이 아직 상태를 쓰지 않았습니다"))); return; }
  const run = d.run || {}, feed = d.feed || {}, eng = d.engine || {}, ev = d.events || {}, sv = d.server || {};
  const lagMin = d.complete_ms ? (Date.now() - d.complete_ms) / 60000 : null;
  const runAgo = run.finished_ms ? (Date.now() - run.finished_ms) / 60000 : null;
  const pins = eng.pins || {};
  const coinRows = (feed.coins || []);
  put(el, head("상태", "자료 · 엔진 · 서버"),
    h("div", {class: "grid2"},
      card("자료와 엔진", h("div", {class: "stats"},
        stat("자료 지연", lagMin == null ? "—" : `${fmt.int(lagMin)}분`, "5분봉 마감부터 (보통 1분 안팎)", lagMin > 30 ? "down" : lagMin > 12 ? "warn" : "up"),
        stat("마지막 계산", run.finished_ms ? fmt.ago(run.finished_ms) : "—", run.seconds != null ? `${fmt.num(run.seconds, 1)}초 걸림` : null, runAgo > 15 ? "warn" : ""),
        stat("반영한 봉", d.complete_ms ? fmt.kst(d.complete_ms) : "—", "KST (이 시각 전까지의 5분봉)"),
        stat("오류", fmt.int((run.errors || []).length), null, (run.errors || []).length ? "down" : "")),
        h("dl", {class: "kv"},
          h("dt", null, "시작"), h("dd", null, `${fmt.kst(d.forward_start_ms)} KST부터 기록 · 지표용 과거 자료 ${fmt.kst(d.warmup_start_ms)}부터`),
          h("dt", null, "단계별 시간"), h("dd", {class: "mono small"}, run.phase ? Object.entries(run.phase).map(([k, v]) => `${k} ${v}s`).join(" · ") : "—"),
          h("dt", null, "따라잡는 중"), h("dd", null, run.catching_up ? "예 (10/01부터 다시 계산 중)" : "아니오"),
          h("dt", null, "작업 프로세스"), h("dd", null, fmt.int(run.procs)),
          h("dt", null, "시스템"), h("dd", null, `${fmt.int((d.systems || {}).n)}개 (진입 칸 ${fmt.int((d.systems || {}).cells)}개)`),
          h("dt", null, "라인업 파일"), h("dd", null, (d.lineup || {}).error ? `오류: ${d.lineup.error}` : `${fmt.int((d.lineup || {}).accounts)}개 계좌 (정식 ${fmt.int(((d.lineup || {}).labels || {})["정식"])} · 참고 ${fmt.int(((d.lineup || {}).labels || {})["참고"])})`),
          h("dt", null, "이벤트 기록"), h("dd", null, `${fmt.int(ev.events)}개 (세대 ${ev.generation}, 나중에 채운 것 ${fmt.int(ev.backfilled)}, 결과 대기 ${fmt.int(ev.pending)})`),
          h("dt", null, "다시 그려진 신호"), h("dd", {class: ev.repaints ? "warn" : ""}, ev.repaints ? `${fmt.int(ev.repaints)}개 (기록은 처음 본 대로 유지)` : "없음")),
        (run.errors || []).length ? h("ul", {class: "log"}, run.errors.slice(0, 10).map((e) => h("li", null, e))) : null),
      card("코드와 서버", h("dl", {class: "kv"},
        h("dt", null, "엔진 (hunt.py)"), h("dd", {class: "mono small"}, (eng.hunt_sha256 || "—").slice(0, 16)),
        h("dt", null, "진입 (entries_wide.py)"), h("dd", {class: "mono small"}, (eng.entries_wide_sha256 || "—").slice(0, 16)),
        h("dt", null, "커밋"), h("dd", {class: "mono small"}, ((eng.installed || {}).commit || eng.commit || "—").slice(0, 12)),
        h("dt", null, "v1 고정"), h("dd", null, pinText(pins.v1)), h("dt", null, "넓게 고정"), h("dd", null, pinText(pins.wide)),
        h("dt", null, "코인 목록"), h("dd", null, `${fmt.int((d.universe || {}).n)}개 중 ${fmt.int((d.universe || {}).in_market)}개 거래 중 · ${(d.universe || {}).source || ""}`),
        h("dt", null, "부하"), h("dd", null, sv.load ? `${sv.load.join(" · ")} (CPU ${sv.cpus}개)` : "—"),
        h("dt", null, "메모리"), h("dd", null, sv.mem ? `남음 ${fmt.int(sv.mem.available_mb)} MB / ${fmt.int(sv.mem.total_mb)} MB · 엔진 최대 ${fmt.int(sv.runner_rss_mb)} MB` : "—"),
        h("dt", null, "디스크"), h("dd", null, sv.disk_free_gb != null ? `남음 ${fmt.num(sv.disk_free_gb, 1)} GB` : "—")))),
    card("코인별 자료", table([
      {ko: "코인", get: (c) => coin(c.symbol)}, {ko: "거래소 상태", get: (c) => c.status || "—"},
      {ko: "계산에 씀", get: (c) => (c.in_market ? "예" : "아니오")},
      {ko: "마지막 5분봉", get: (c) => (c.last_ms ? fmt.kst(c.last_ms) : "—")},
      {ko: "봉 수", num: true, get: (c) => fmt.int(c.bars)},
      {ko: "거래 종료", get: (c) => (c.end_ms ? fmt.kst(c.end_ms) : "")},
      {ko: "펀딩 기다림", get: (c) => (c.expect_funding_ms ? fmt.kst(c.expect_funding_ms) : "")}], coinRows),
      (feed.stalled || []).length ? h("p", {class: "errbox"}, `봉이 안 들어오는 코인: ${feed.stalled.map(coin).join(", ")}`) : null),
    card("자료 수집 기록 (최근)", (feed.log || []).length ? h("ul", {class: "log"}, feed.log.map((r) => h("li", null, `${fmt.kst(r.ts_ms)} ${r.level} ${r.msg}`)))
      : h("p", {class: "note"}, "없음")));
}
function pinText(p) {
  if (!p) return "—";
  if (!p.pinned) return p.note || "고정 전";
  return p.same_code ? `고정됨, 같은 코드${p.picks_line ? " · 픽 기록됨" : ""}` : "고정됨, 하지만 설치된 코드가 다름 (다시 설치 필요)";
}

// ---------------------------------------------------------------- shell
const menu = document.getElementById("menu");
const main = document.getElementById("screen");
const hdot = document.getElementById("hdot");
const clock = document.getElementById("clock");
put(menu, MENU.map((m) => h("a", {href: `#/${m.id}`, dataset: {id: m.id}}, m.ko)));

function route() {
  const raw = (location.hash || "").replace(/^#\/?/, "");
  const [name, ...rest] = raw.split("/");
  let arg = rest.join("/");
  try { arg = decodeURIComponent(arg); } catch (e) { arg = ""; }
  return {name: screens[name] ? name : "lineup", arg};
}
let busy = 0;
async function show() {
  const {name, arg} = route();
  for (const a of menu.querySelectorAll("a")) {
    if (a.dataset.id === name || (name === "sys" && a.dataset.id === "all")) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
  const my = ++busy;
  const box = h("div");
  try { await screens[name](box, arg); } catch (e) { if (e.message !== "login") put(box, card(null, h("p", {class: "errbox"}, `불러오지 못했습니다: ${e.message}`))); }
  if (my === busy) put(main, box);
}
async function health() {
  try {
    const d = await api("/api/status");
    const lag = d.complete_ms ? (Date.now() - d.complete_ms) / 60000 : null;
    const errs = ((d.run || {}).errors || []).length;
    const lv = lag == null ? "unknown" : lag > 30 ? "bad" : lag > 12 || errs ? "warn" : "ok";
    hdot.dataset.level = lv;
    hdot.setAttribute("aria-label", `상태: 자료 지연 ${lag == null ? "모름" : Math.round(lag) + "분"}${errs ? `, 오류 ${errs}개` : ""}`);
    clock.textContent = d.complete_ms ? `${fmt.kst(d.complete_ms)} KST 봉까지` : "";
  } catch (e) { hdot.dataset.level = "unknown"; }
}
window.addEventListener("hashchange", show);
show();
health();
// the tables with filters (전체 기록, one system) are not redrawn under the viewer's hands: they refresh on the next visit
setInterval(() => { if (!document.hidden) { if (!["all", "sys"].includes(route().name)) show(); health(); } }, 60000);
