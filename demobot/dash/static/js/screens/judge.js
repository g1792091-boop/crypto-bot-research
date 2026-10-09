// #/judge 판정 (round 5 stage 2: the rule bot's v4 30일 판정 look, checkpoint.js / checkpoint-stage.js / checkpoint.css):
//   the verdict card (the verdict line, candidates first, the 실전 금지 stamp until the owners decide, the note on judging
//   many lines at once), the stage strip with real counts (판정한 줄 → 우리 기준 통과 → 확인 기간 → 실전 후보; a stage is
//   lit only when a line is really there, the furthest one says 지금 여기; 친구 기준 beside it), the "실전 후보" cards (a
//   line that passed and then its 4-week confirmation: the window's P&L as an LED number, mean R, drawdown, the stop-rule
//   result and the measured cost), the confirmation periods with their progress (CONTRACT 8.1), the three rule sets as
//   numbered steps ("우리 기준" / "친구 기준" / "정지 규칙", 8.2), then per account and leverage every check as a light (✓ /
//   ✗ / — and its value), the line's confirmation badge and its stop-rule twin (P&L, drawdown, "우리 기준" on the twin).
// judge.json every 60 s. Read-only; a missing file shows "준비 중".
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
import {isMissing} from "../api.js";
import {LEVS, KINDS, kindOfId} from "../labels.js";

const DAY = 86400000;

/** An account-like object for the pixel figure and the name chip, from a row that only carries id and name. */
function acctOf(id, name) {
  const x = String(id || "");
  const tf = /-(15m|30m)$/.exec(x), sh = /(?:^|-)(S2|N02|N04)(?:-|$)/.exec(x);
  return {id: x, name: name || x, kind: kindOfId(x), tf: tf ? tf[1] : null, short: sh ? sh[1] : null};
}
const levTag = (L) => (L ? h("span", {class: "dl-levtag", dataset: {lev: L}}, fmt.lev(L)) : null);
/** A check as a small light: the dot AND ✓ / ✗ / — (never colour alone). */
const light = (ok, text) => h("span", {class: ["s2a-lt", ok == null ? "na" : ok ? "ok" : "no"]}, h("i", {"aria-hidden": "true"}),
  ok == null ? "—" : ok ? "✓" : "✗", text ? h("small", null, text) : null);

export async function mount(el, ctx) {
  ctx.setTitle("판정");
  const saved = local.get("judge", {}) || {};
  const f = {lev: saved.lev || "20", kind: saved.kind || "all", only: !!saved.only};
  const keep = () => local.set("judge", f);
  const verdict = h("section", {class: "card hero dl-verdict s2a-hero s2a-vhead", "aria-label": "판정"});
  const strip = h("div", {class: "s2a-stage"});
  const candBox = h("div", {class: "stack"});
  const confBox = h("div");
  const rules = h("div", {class: "s2a-rules"});
  const levSeg = ui.seg([...LEVS.map((L) => ({id: String(L), label: `${L}배`})), {id: "all", label: "전체"}], f.lev,
    (v) => { f.lev = v; keep(); paintTable(); }, {label: "배수"});
  const kindSeg = ui.seg([{id: "all", label: "전체"}, ...KINDS.map((k) => ({id: k.id, label: k.ko}))], f.kind,
    (v) => { f.kind = v; keep(); paintTable(); }, {label: "계좌 종류", cls: "scroll"});
  const only = K4.chipToggle("통과·확인 중인 것만", f.only, (v) => { f.only = v; keep(); paintTable(); }, "우리 기준·친구 기준을 통과했거나 확인 기간이 있는 줄만");
  const count = h("span", {class: "s2a-count"});
  let build = null;                                   // (rows) -> table, set by paintTable for the current columns
  const pg = ui.pager({size: 48, empty: "맞는 줄이 없습니다", render: (part) => (build ? build(part) : ui.empty("—"))});
  el.append(ui.screenHead("판정", "실전에 써도 되는지 두 가지 기준으로 봅니다"), verdict,
    h("section", {class: "k4-sec", "aria-label": "단계"}, K4.secRow("단계", "줄마다 실전 후보까지 · 실제로 거기 있는 줄만 불이 켜집니다",
      h("a", {class: "btn-line", href: "#/path"}, "졸업 길 →")), strip),
    candBox,
    ui.card({plate: "확인 기간", sub: "기준을 처음 넘은 줄: 그 뒤 4주 (거래 20건 이상)를 다시 봅니다"}, confBox),
    rules,
    ui.card({plate: "계좌 × 배수", cls: "s2a-jcard", acts: [count]},
      h("div", {class: "s2a-bar"}, h("span", {class: "s2a-barg"}, h("span", {class: "k4-k"}, "배수"), levSeg),
        h("span", {class: "s2a-barg"}, h("span", {class: "k4-k"}, "계좌 종류"), kindSeg), only), pg.el,
      h("p", {class: "assume"}, "✓ 통과 · ✗ 못 미침 · — 해당 없음. 기준을 모두 넘어야 그 기준의 \"통과\"입니다. 정지 규칙 칸은 같은 줄을 정지 규칙으로 돌렸다면의 결과입니다.")));

  let data = null, seen = null;
  async function load() {
    let d;
    try { d = await ctx.api("/api/judge"); } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!data) put(verdict, ui.errorBox(e, load));
      return;
    }
    if (d && d.generated_ms != null && d.generated_ms === seen) return;
    seen = d ? d.generated_ms : null;
    data = d;
    if (isMissing(d)) {
      put(verdict, h("div", {class: "s2a-hrow"}, ui.plate("오늘의 판정")), h("p", {class: "dl-vbig no"}, "실전 금지"), ui.missing("판정 자료"));
      put(strip, ui.empty("준비 중")); put(rules); put(candBox); put(confBox, ui.none("준비 중")); pg.set([]); count.textContent = "";
      return;
    }
    const rowsAll = d.rows || [];
    const nOurs = rowsAll.filter((r) => r.ours && r.ours.pass).length;
    const nFr = rowsAll.filter((r) => r.friend && r.friend.pass).length;
    const conf = Array.isArray(d.confirm) ? d.confirm : null;
    const cands = Array.isArray(d.candidates) ? d.candidates : [];
    const nConf = conf ? conf.filter((c) => c.status === "confirming").length : null;
    const judged = d.lines_judged ?? rowsAll.length;
    put(verdict,
      h("div", {class: "s2a-hrow"}, ui.plate("오늘의 판정"), d.generated_ms ? h("span", {class: "muted s2a-small"}, `${fmt.kst(d.generated_ms)} 기준`) : null),
      h("div", {class: "s2a-stamp", "aria-hidden": "true"}, h("b", null, "실전 금지"), h("small", null, "두 분 결정 전")),
      cands.length ? h("p", {class: "dl-vbig ok"}, "실전 후보 ", h("em", null, `${fmt.int(cands.length)}줄`))
        : nConf ? h("p", {class: "dl-vbig warn"}, "확인 기간 ", h("em", null, `${fmt.int(nConf)}줄`))
          : nOurs > 0 ? h("p", {class: "dl-vbig ok"}, "통과 ", h("em", null, `${fmt.int(nOurs)}줄`)) : h("p", {class: "dl-vbig no"}, "실전 금지"),
      h("p", {class: "dl-vline"}, d.verdict_ko || "—"),
      d.multi_note_ko ? h("p", {class: "refnote"}, h("b", null, "여러 줄을 한꺼번에 보면: "), d.multi_note_ko) : null,
      h("p", {class: "note"}, "실제 돈을 쓸지는 두 분이 정합니다. 정하기 전까지는 실전 금지입니다 (도장은 그 뜻입니다)."));
    paintStrip(judged, nOurs, nConf, cands.length, nFr);
    paintCands(cands);
    paintConfirm(conf);
    const rk = d.rules_ko || {};
    put(rules,
      ruleCard("우리 기준", "모두 넘어야 통과", rk.ours),
      ruleCard("친구 기준", "모두 넘어야 통과", rk.friend),
      ruleCard("정지 규칙", "실제 돈에 쓸 멈춤 규칙 · 새 진입만 막음", d.stop_rules_ko, "정지 규칙 문구가 아직 없습니다"));
    paintTable(true);
  }

  /** The stage strip: real counts only; a stage is lit when a line is there, the furthest lit one is 지금 여기. */
  function paintStrip(judged, nOurs, nConf, nCand, nFr) {
    const st = [
      {ko: "판정한 줄", n: judged, sub: "계좌 × 배수 4줄"},
      {ko: "우리 기준 통과", n: nOurs, sub: "지금 5개 모두 넘은 줄"},
      {ko: "확인 기간", n: nConf, sub: "4주 다시 보는 중"},
      {ko: "실전 후보", n: nCand, sub: "확인 기간까지 넘은 줄"},
    ];
    let here = -1;
    st.forEach((x, i) => { if (Number(x.n) > 0) here = i; });
    put(strip, h("ol", {class: "s2a-funnel", "aria-label": "판정 단계"}, st.map((x, i) => h("li", {class: ["s2a-fseg", Number(x.n) > 0 ? "has" : "dim", i === here ? "here" : ""],
      style: {"--i": String(i)}, "aria-current": i === here ? "step" : null},
    h("span", {class: "s2a-fno"}, i === here ? `0${i + 1} · 지금 여기` : `0${i + 1}`),
    h("span", {class: "s2a-fko"}, x.ko),
    h("b", {class: "s2a-fbig num"}, x.n == null ? "준비 중" : fmt.int(x.n)),
    h("span", {class: "s2a-fsm"}, x.n == null ? "엔진이 아직 쓰지 않음" : Number(x.n) > 0 ? x.sub : "아직 없음")))),
    h("div", {class: "s2a-fside"}, h("span", {class: "k4-k"}, "친구 기준 통과"), h("b", {class: "num"}, `${fmt.int(nFr)}줄`),
      h("small", {class: "muted"}, `전체 ${fmt.int(judged)}줄 중 · 우리 기준과 따로 봄`)));
  }

  function paintCands(cands) {
    if (!cands.length) { put(candBox); return; }
    put(candBox, K4.secRow("실전 후보", "확인 기간까지 넘은 줄 · 두 분이 정할 차례"), h("div", {class: "s2a-wrap even"}, cands.map((c) => {
      const w = c.window || {}, co = c.costs || {}, sp = c.stops || null;
      const a = acctOf(c.id, c.name);
      const pT = fmt.pct(w.pnl_pct, true);
      return ui.card({hero: true, cls: "dl-cand s2a-cand", plate: "실전 후보", sub: c.decided_ms ? `${fmt.kst(c.decided_ms)} 확인 끝` : ""},
        h("div", {class: "s2a-candn"}, h("a", {class: "s2a-nm", href: ctx.href("account", c.id), title: c.id}, K4.acctFig(a, 26), K4.acctName(a)), levTag(c.L)),
        h("div", {class: "pnl s2a-ledbox"}, h("div", null, h("span", {class: "k"}, "확인 기간 손익"), h("b", {class: ["led-num", "num", fmt.tone(w.pnl_pct, pT)]}, pT)),
          h("div", {class: "r"}, h("span", {class: "k"}, "거래"), h("b", {class: "led-sm num"}, `${fmt.int(w.n)}건`))),
        h("div", {class: "stats s2a-s3"},
          K4.stat("평균 R", fmt.r(w.mean_R), "수수료 뺀 뒤"),
          K4.stat("최대 낙폭", fmt.ratio(w.max_dd), "확인 기간 안"),
          K4.stat("정지 규칙이면", sp ? fmt.pct(sp.pnl_pct, true) : "기록 없음", sp ? `낙폭 ${fmt.ratio(sp.max_dd)} · 전체 기간` : "준비 중")),
        h("p", {class: "s2a-costline"}, h("b", null, "실제 비용 "),
          co.entry_bps == null ? "기록 없음 (호가를 잰 진입이 없음: 지정가 진입이거나 기록 전)" : `진입 한 번 ${fmt.num(co.entry_bps, 2)}bp (가정 2bp)`,
          co.roundtrip_pct_of_pnl == null ? "" : ` · 가정보다 더 든 왕복 비용 = 번 돈의 ${fmt.pct(co.roundtrip_pct_of_pnl, false, 1)}`),
        h("p", {class: "note"}, "실제 돈을 쓸지는 두 분이 정합니다. 정하기 전까지는 실전 금지입니다."));
    })));
  }

  function paintConfirm(conf) {
    if (conf == null) { put(confBox, ui.none("준비 중 (엔진이 아직 확인 기간을 쓰지 않습니다)")); return; }
    if (!conf.length) { put(confBox, ui.none("아직 확인 기간에 들어간 줄이 없습니다")); return; }
    const now = Date.now();
    put(confBox, h("div", {class: "s2a-confl"}, conf.map((c) => {
      const left = c.status === "confirming" && c.min_end_ms ? Math.max(0, (c.min_end_ms - now) / DAY) : null;
      const pT = fmt.pct(c.pnl_pct, true);
      const a = acctOf(c.id, c.name);
      return h("div", {class: ["s2a-conf", "st-" + c.status]},
        h("div", {class: "s2a-confh"}, ui.confirmBadge(c), h("a", {class: "s2a-nm", href: ctx.href("account", c.id), title: c.id}, K4.acctFig(a, 18), K4.acctName(a)),
          levTag(c.L), h("span", {class: "grow"}),
          h("span", {class: "s2a-t num"}, `${fmt.mmdd(c.start_ms)} 시작${c.decided_ms ? ` · ${fmt.mmdd(c.decided_ms)} 끝` : ""}`)),
        c.status === "confirming"
          ? ui.progress(c.progress, `${fmt.ratio(c.progress, 0)} · 거래 ${fmt.int(c.n)} / ${fmt.int(c.need_n ?? 20)}건 · `
            + (left == null ? "" : left > 0 ? `${fmt.num(left, 1)}일 남음` : "28일 지남"))
          : ui.progress(1, `거래 ${fmt.int(c.n)}건`, c.status === "failed" ? "bad" : "ok"),
        h("div", {class: "s2a-confs"},
          h("span", null, h("span", {class: "muted"}, "손익 "), ui.signed(pT, fmt.tone(c.pnl_pct, pT), "b")),
          h("span", null, h("span", {class: "muted"}, "평균 "), fmt.r(c.mean_R)),
          h("span", null, h("span", {class: "muted"}, "낙폭 "), fmt.ratio(c.max_dd)),
          Number(c.liqs) ? h("span", {class: "down"}, `강제청산 ${fmt.int(c.liqs)}`) : null,
          Number(c.ruins) ? h("span", {class: "down"}, `파산 ${fmt.int(c.ruins)}`) : null),
        c.why_ko ? h("p", {class: "s2a-why"}, c.why_ko) : null);
    })), ui.disclosure("확인 기간이 끝나는 규칙", h("p", {class: "note"}, "확인 기간: 처음 통과한 때부터 들어간 거래만 셉니다. 28일이 지나고 거래가 20건 이상이면 끝 (모자라면 20건이 될 때, 길어도 56일). "
      + "끝날 때 거래 20건 이상 · 평균 R > 0 · 손익 + · 낙폭 30% 미만 · 파산·강제청산 없음이면 실전 후보, 아니면 실패입니다.")));
  }

  function paintTable(keepPage) {
    if (!data || isMissing(data)) { pg.set([]); return; }
    let rows = data.rows || [];
    if (f.lev !== "all") rows = rows.filter((r) => String(r.L) === f.lev);
    if (f.kind !== "all") rows = rows.filter((r) => kindOfId(r.id) === f.kind);
    if (f.only) rows = rows.filter((r) => (r.ours && r.ours.pass) || (r.friend && r.friend.pass) || (r.confirm && r.confirm.status));
    count.textContent = `${fmt.int(rows.length)}줄`;
    const names = (side) => {
      const out = [];
      for (const r of data.rows || []) for (const c of (r[side] && r[side].checks) || []) if (!out.includes(c.name_ko)) out.push(c.name_ko);
      return out;
    };
    const ours = names("ours"), friend = names("friend");
    const hasStops = (data.rows || []).some((r) => r.stops);
    const cellOf = (r, side, name) => {
      const c = ((r[side] && r[side].checks) || []).find((x) => x.name_ko === name);
      return c ? light(c.ok, c.value_ko || "") : h("span", {class: "muted"}, "—");
    };
    const verdictCell = (v) => (v == null ? h("span", {class: "muted"}, "해당 없음") : v ? ui.pill("통과", "good") : ui.pill("미통과", "bad"));
    const confCell = (r) => (r.confirm && r.confirm.status ? h("span", {class: "dl-kn"}, ui.confirmBadge(r.confirm),
      h("small", {class: "muted"}, `${fmt.mmdd(r.confirm.start_ms)}~${fmt.mmdd(r.confirm.end_ms)}`)) : h("span", {class: "muted"}, "—"));
    const stopCells = (r) => {
      const sp = r.stops;
      if (!sp) return [h("td", {class: "dl-jg muted"}, "준비 중"), h("td", {class: "muted"}, "—"), h("td", {class: "muted"}, "—")];
      const pT = fmt.pct(sp.pnl_pct, true);
      return [h("td", {class: "dl-jg"}, ui.signed(pT, fmt.tone(sp.pnl_pct, pT), "b")), h("td", null, fmt.ratio(sp.max_dd)),
        h("td", null, light(sp.ours_pass == null ? null : !!sp.ours_pass))];
    };
    const head2 = [h("th", {class: "l dl-c2", scope: "col"}, "계좌"), h("th", {scope: "col"}, "배수"),
      h("th", {scope: "col", title: "가장 최근 확인 기간"}, "확인"),
      h("th", {class: "dl-jg", scope: "col"}, "결과"), ...ours.map((n) => h("th", {scope: "col", title: n}, n)),
      h("th", {class: "dl-jg", scope: "col"}, "결과"), ...friend.map((n) => h("th", {scope: "col", title: n}, n)),
      ...(hasStops ? [h("th", {class: "dl-jg", scope: "col"}, "손익"), h("th", {scope: "col"}, "최대 낙폭"), h("th", {scope: "col"}, "우리 기준")] : [])];
    const head1 = h("tr", {class: "dl-htop"}, h("th", {colspan: "3", class: "l dl-c2"}, ""),
      h("th", {colspan: String(ours.length + 1), class: "dl-jg dl-jgh"}, "우리 기준"),
      h("th", {colspan: String(friend.length + 1), class: "dl-jg dl-jgh"}, "친구 기준"),
      hasStops ? h("th", {colspan: "3", class: "dl-jg dl-jgh"}, "정지 규칙 적용 시") : null);
    build = (part) => h("div", {class: "tbl-wrap"}, h("table", {class: "tbl dl-judge s2a-judge"},
      h("thead", null, head1, h("tr", null, head2)), h("tbody", null, part.map((r) => h("tr", {class: (r.ours && r.ours.pass) || (r.friend && r.friend.pass) ? "dl-passrow" : ""},
      h("td", {class: "l dl-c2"}, h("a", {class: "s2a-nm", href: ctx.href("account", r.id), title: r.id}, K4.acctFig(acctOf(r.id, r.name), 18), K4.acctName(acctOf(r.id, r.name)))),
      h("td", null, levTag(r.L)),
      h("td", null, confCell(r)),
      h("td", {class: "dl-jg"}, verdictCell(r.ours ? r.ours.pass : null)),
      ...ours.map((n) => h("td", null, cellOf(r, "ours", n))),
      h("td", {class: "dl-jg"}, verdictCell(r.friend ? r.friend.pass : null)),
      ...friend.map((n) => h("td", null, cellOf(r, "friend", n))),
      ...(hasStops ? stopCells(r) : []))))));
    pg.set(rows, keepPage);
  }

  await load();
  ctx.every(60000, load);
}

/** A rule set as numbered steps (v4 ck-steps: the pixel number plate, then the words). */
function ruleCard(plateText, sub, items, empty = "기준 문구가 아직 없습니다") {
  return ui.card({plate: plateText, sub}, !items || !items.length ? ui.empty(empty)
    : h("ol", {class: "s2a-nlist"}, items.map((x, i) => h("li", null, h("span", {class: "s2a-n", "aria-hidden": "true"}, String(i + 1).padStart(2, "0")), h("span", null, x)))));
}
