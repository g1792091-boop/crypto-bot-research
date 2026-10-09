// #/whatif 만약 실험실 (CONTRACT 9.8): pick a fixed account (accounts.json combo / exit_i); its setting under all 14 exits
// in the ranking's three windows (/api/setting: the rank arrays, the same numbers as the 설정 순위 rows; scope all coins),
// its own exit marked; and its four leverage lines side by side (P&L, max drawdown, liquidations, skipped entries,
// ruins, the stop-rule line's P&L). What the ranking saw, not a new simulation of the wallet: said on the screen.
// Round 5 stage 2B (the rule bot's v4 만약 실험실 look): the caveat first, big and calm (warn ground); the account and the
// window as one filter bar; the chosen account's head with its pixel character; an LED strip of the view's key numbers
// (its own exit's mean R, the best exit, the luck line, how many exits beat it); the 14 exits as bars; the exit × window
// table and the four leverage lines (each with its small equity line) in the v4 dense table look.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
import {isMissing} from "../api.js";
import {LEVS, WINDOW_KO, tfKo} from "../labels.js";
import {divBar, fewNote, FEW} from "../g4.js";

const WINS = ["live", "26w", "4w"];
const grp = (label, ...kids) => h("span", {class: "k4-barg s2-g"}, h("span", {class: "k4-k"}, label), ...kids);

export async function mount(el, ctx) {
  ctx.setTitle("만약 실험실");
  let id = ctx.params.query.id || local.get("whatif-id", "fx-def-S2-15m");
  let win = local.get("whatif-win", "26w");
  if (!WINS.includes(win)) win = "26w";
  const acctBox = h("span", {class: "s2-g k4-barg"});
  const head = h("div");
  const led = h("div");
  const bars = h("div");
  const tbl = h("div");
  const levs = h("div");
  const winSeg = ui.seg(WINS.map((w) => ({id: w, label: WINDOW_KO[w]})), win,
    (v) => { win = v; local.set("whatif-win", v); paintExits(true); }, {label: "기간"});
  el.append(ui.screenHead("만약 실험실", "같은 설정에 다른 청산을 썼다면, 다른 배수였다면"),
    ui.card({cls: "s2-caveat dl-cand g4-honest", plate: "먼저 읽기"}, h("p", {class: "s2-big dl-vline"},
      "여기 숫자는 설정 순위가 본 것입니다. 같은 신호에서 청산만 바꿔 거래마다 R로 센 것이고, 지갑을 새로 돌린 시뮬레이션이 아닙니다."),
    h("p", {class: "s2-lead"}, "실제 계좌는 배수, 진입 검사로 건너뛴 거래, 실제 펀딩 때문에 설정 순위 숫자와 다를 수 있습니다. 아래 '배수 4줄'이 그 계좌가 실제로 낸 결과입니다.")),
    h("div", {class: "s2-ctl", role: "group", "aria-label": "계좌 고르기"}, h("div", {class: "k4-bar"}, acctBox, grp("기간", winSeg))),
    head, led,
    h("div", {class: "s2-cols s2-wicols"},
      ui.card({plate: "청산 14가지", sub: "평균 R (수수료 후, 코인 7개 합침) · 굵은 줄 = 이 계좌가 쓰는 청산"}, bars),
      h("div", {class: "s2-col"},
        ui.card({plate: "배수 4줄 나란히", sub: "이 계좌의 실제 결과 (각 $1,000에서 시작)"}, levs),
        ui.card({plate: "청산 × 기간 표", sub: "실시간 · 최근 26주 · 최근 4주"}, tbl))));

  let accts = null, setting = null, req = 0;
  async function loadAccts() {
    try { accts = await ctx.api("/api/accounts"); } catch (e) {
      if (e && e.name === "AbortError") return;
      put(acctBox, ui.errorBox(e, loadAccts));
      return;
    }
    paintControls();
    await loadSetting();
  }
  const fixed = () => (accts && !isMissing(accts) ? (accts.accounts || []).filter((a) => a.kind === "fixed") : []);
  const acct = () => fixed().find((a) => a.id === id) || fixed()[0] || null;

  function paintControls() {
    const list = fixed();
    if (!list.length) { put(acctBox, accts && !isMissing(accts) ? ui.none("고정 계좌가 없습니다") : ui.missing("계좌 목록")); return; }
    if (!list.some((a) => a.id === id)) id = list[0].id;
    put(acctBox, h("span", {class: "k4-k"}, "계좌"), ui.select(list.map((a) => ({id: a.id, label: a.name || a.id})), id, (v) => {
      id = v; local.set("whatif-id", v); ctx.setQuery({id: v}); loadSetting();
    }, "고정 계좌"));
  }

  async function loadSetting() {
    const a = acct();
    setting = null;
    paintLevs(a);
    if (!a) { put(head); put(led); put(bars, ui.none("준비 중")); put(tbl, ui.none("준비 중")); return; }
    put(head, h("div", {class: "s2-whead"}, K4.acctFig(a, 34),
      h("div", {class: "s2-wtitle"}, h("h2", null, a.tf ? K4.tfChip(a.tf) : null, " ", K4.shortName(a)),
        h("p", {class: "s2-meta"}, h("b", {class: "mono"}, a.setting_ko || "—"), ` · ${a.short || ""} · ${tfKo(a.tf)}`,
          a.combo == null ? " · 설정 번호 준비 중" : ` · 설정 번호 ${a.combo}`, a.rule_ko ? ` · ${a.rule_ko}` : "")),
      h("span", {class: "grow"}),
      h("div", {class: "row wrap s2-acts"}, h("a", {class: "btn-line", href: ctx.href("account", a.id)}, "계좌 자세히"),
        a.combo != null ? h("a", {class: "btn-line", href: ctx.href("rank", null, {strat: a.short, tf: a.tf, window: win, scope: "ALL", q: a.setting_ko || ""})}, "설정 순위에서 보기") : null)));
    if (a.combo == null || !Number.isInteger(Number(a.combo))) {
      put(led);
      put(bars, ui.none("준비 중: 엔진이 이 계좌의 설정 번호(combo)를 아직 쓰지 않습니다"));
      put(tbl);
      return;
    }
    const my = ++req;
    put(bars, ui.empty("읽는 중…"));
    try {
      const d = await ctx.api(`/api/setting?${new URLSearchParams({strat: a.short, tf: a.tf, c: String(a.combo)})}`);
      if (my !== req) return;
      setting = d;
    } catch (e) {
      if (e && e.name === "AbortError") return;
      if (my === req) put(bars, ui.errorBox(e, loadSetting));
      return;
    }
    paintExits(false);
  }

  function paintExits(user) {
    const a = acct();
    if (!setting || !a) return;
    if (!setting.rank) { put(led); put(bars, ui.missing(`${a.short} · ${tfKo(a.tf)} 순위 파일`)); put(tbl); return; }
    const own = Number(a.exit_i ?? 0);
    const rows = setting.exits || [];
    const cell = (r, w) => (r.w && r.w[w]) || null;
    const max = Math.max(0.05, ...rows.map((r) => { const c = cell(r, win); return c && c.mean_R != null && c.n >= 5 ? Math.abs(c.mean_R) : 0; }));
    const best = rows.map((r) => cell(r, win)).filter((c) => c && c.mean_R != null && c.min_ok).reduce((m, c) => Math.max(m, c.mean_R), -Infinity);
    const bestRow = rows.find((r) => { const c = cell(r, win); return c && c.mean_R === best && c.min_ok; });
    const luck = rows.map((r) => cell(r, win)).find((c) => c && c.luck95 != null);
    const ownRow = rows.find((r) => r.i === own), ownC = ownRow ? cell(ownRow, win) : null;
    const beat = ownC && ownC.mean_R != null ? rows.filter((r) => r.i !== own && cell(r, win) && cell(r, win).min_ok && cell(r, win).mean_R > ownC.mean_R).length : null;
    // the LED strip (v4 LED numbers): the view in four numbers
    const ledCell = (k, v, tone, sub) => h("div", null, h("span", {class: "k"}, k), h("b", {class: ["num", tone]}, v), sub ? h("span", {class: "s"}, sub) : null);
    put(led, h("div", {class: "s2-led", style: {"--n": "4"}, role: "group", "aria-label": `${WINDOW_KO[win]}의 숫자`},
      ledCell("이 계좌 청산", ownC ? fmt.r(ownC.mean_R) : "—", ownC ? fmt.tone(ownC.mean_R, fmt.r(ownC.mean_R)) : "",
        `${ownRow ? `${own}. ${ownRow.ko}` : "—"}${ownC ? ` · ${fmt.int(ownC.n)}건` : ""}`),
      ledCell("가장 좋은 청산", best > -Infinity ? fmt.r(best) : "—", best > -Infinity ? fmt.tone(best, fmt.r(best)) : "",
        bestRow ? `${bestRow.i}. ${bestRow.ko}` : "최소 거래 수를 채운 청산이 없습니다"),
      ledCell("이 계좌보다 나은 청산", beat == null ? "—" : `${fmt.int(beat)}개`, "", "최소 거래 수를 채운 것 가운데"),
      ledCell("운 기준선", luck ? fmt.r(luck.luck95) : "—", "", "설정 전체의 1등이 운으로도 낼 법한 값")));
    put(bars, h("ol", {class: "g4-ex"}, rows.map((r) => {
      const c = cell(r, win);
      return h("li", {class: ["g4-exr", r.i === own ? "own" : "", c && !c.min_ok ? "g4-dim" : ""]},
        h("span", {class: "g4-exn"}, h("span", null, h("span", {class: "muted"}, `${r.i}.`), ` ${r.ko}`), r.i === own ? ui.pill("이 계좌", "accent") : null),
        divBar(c && c.mean_R, max, c ? fmt.r(c.mean_R) : "—"),
        h("span", {class: "g4-exm muted"}, c ? `${fmt.int(c.n)}건 · 승률 ${fmt.ratio(c.win_rate, 0)}` : "—",
          c && c.beats_luck ? h("span", {class: "up"}, " · 운 위") : null, c && c.mean_R === best && best > -Infinity ? h("b", {class: "accent-t"}, " · 1등") : null));
    })),
    h("p", {class: "note"}, `${WINDOW_KO[win]}: 거래가 그 기간 최소 거래 수(${fmt.int((setting.min_n || [])[WINS.indexOf(win)])}건)보다 적은 청산은 흐리게 보입니다.`,
      luck ? ` 운 기준선 ${fmt.r(luck.luck95)} (설정 전체의 1등이 운으로도 낼 법한 값).` : ""));
    if (user) K4.swap(bars);
    put(tbl, ui.table([
      {label: "청산", l: true, cls: "dl-c2", get: (r) => h("span", {class: "dl-kn"}, h("b", null, `${r.i}. ${r.ko}`), r.i === own ? h("small", {class: "accent-t"}, "이 계좌") : null)},
      ...WINS.map((w, i) => ({label: WINDOW_KO[w], cls: i === 0 ? "dl-5y0" : "", hcls: w === win ? "s2-on" : "", get: (r) => {
        const c = cell(r, w);
        if (!c || !c.n) return h("span", {class: "muted"}, "—");
        return h("span", {class: "dl-5y"}, ui.signed(fmt.r(c.mean_R), fmt.tone(c.mean_R, fmt.r(c.mean_R)), "b"),
          h("small", {class: "muted"}, `${fmt.int(c.n)}건${c.beats_luck ? " · 운 위" : ""}`));
      }})),
      {label: "5년 24–26", get: (r) => {
        const p = r.past && r.past["2024-26"];
        return p && p.mean_R != null ? h("span", {class: "dl-5y"}, ui.signed(fmt.r(p.mean_R), fmt.tone(p.mean_R, fmt.r(p.mean_R))), h("small", {class: "muted"}, `${fmt.int(p.n)}건`))
          : h("span", {class: "muted"}, "—");
      }},
    ], rows, {cls: "g4-wt s2-dense", rowCls: (r) => (r.i === own ? "dl-marked" : "")}));
  }

  function paintLevs(a) {
    if (!a) { put(levs, ui.none("계좌를 고르면 나옵니다")); return; }
    const L4 = LEVS.map((L) => ({L, x: (a.lines || {})[String(L)] || null}));
    const row = (label, get, title) => h("tr", null, h("th", {scope: "row", class: "l", title}, label), L4.map(({x}) => h("td", null, x ? get(x) : "—")));
    put(levs, h("div", {class: "tbl-wrap"}, h("table", {class: "tbl dl-cmp g4-lev4 s2-dense s2-lev4"},
      h("thead", null, h("tr", null, h("th", {class: "l"}, ""), L4.map(({L}) => h("th", null, h("span", {class: "dl-levtag", dataset: {lev: L}}, `${L}배`))))),
      h("tbody", null,
        row("흐름", (x) => K4.miniSpark(x.spark, {w: 64, h: 20, base: 1000, label: "시작부터 지금까지 잔고 흐름 (30점)"}), "시작부터 지금까지 잔고 (30점)"),
        row("손익", (x) => h("span", {class: "dl-kn"}, ui.signed(fmt.pct(x.pnl_pct, true), fmt.tone(x.pnl_pct, fmt.pct(x.pnl_pct)), "b"), h("small", {class: "muted"}, fmt.money(x.pnl, true)))),
        row("최대 낙폭", (x) => fmt.ratio(x.max_dd), "잔고가 가장 높았던 때에서 가장 많이 떨어진 비율"),
        row("거래", (x) => h("span", {class: "dl-kn"}, fmt.int(x.trades), fewNote(x.trades))),
        row("평균 R", (x) => ui.signed(fmt.r(x.mean_R), fmt.tone(x.mean_R, fmt.r(x.mean_R)))),
        row("강제청산", (x) => (x.liqs ? ui.pill(fmt.int(x.liqs), "warn") : "0"), "손절 전에 거래소가 강제로 정리한 횟수"),
        row("건너뜀", (x) => fmt.int(x.skipped), "진입 검사(손절이 강제청산 가격 안쪽, 최대 배수)로 들어가지 못한 신호"),
        row("파산", (x) => (x.ruins ? ui.pill(`${fmt.int(x.ruins)}번`, "bad") : "없음"), "잔고가 $100 아래로 떨어져 $1,000에서 다시 시작한 횟수"),
        row("정지 규칙 손익", (x) => (x.stops ? ui.signed(fmt.pct(x.stops.pnl_pct, true), fmt.tone(x.stops.pnl_pct, fmt.pct(x.stops.pnl_pct))) : "준비 중"),
          "계좌 −20% · 하루 −5% · 5연패에서 새 진입을 멈췄다면")))),
    h("p", {class: "note"}, `배수가 클수록 같은 진입에서 손익이 커지고, 손절이 강제청산 가격보다 바깥이면 들어가지 못해 '건너뜀'이 늘어납니다. 거래가 ${FEW}건보다 적으면 우연일 수 있습니다.`));
  }

  await loadAccts();
}
