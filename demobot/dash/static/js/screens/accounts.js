// #/accounts 계좌: the 48 accounts grouped by kind (고정 / 자동 교체 / 친구 규칙 / 동전 던지기), each with its four
// leverage lines (equity, P&L %, trades, win rate, max drawdown, open, 파산), or one line with the leverage switch.
// accounts.json every 60 s. A row opens #/account/<id>.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {isMissing} from "../api.js";
import {LEVS, KINDS, SUB_KO, kindOfId} from "../labels.js";

export async function mount(el, ctx) {
  ctx.setTitle("계좌");
  let lev = String(local.get("acct-lev", "all"));
  if (!["all", ...LEVS.map(String)].includes(lev)) lev = "all";
  const levSeg = ui.seg([...LEVS.map((L) => ({id: String(L), label: `${L}배`})), {id: "all", label: "전체"}], lev,
    (v) => { lev = v; local.set("acct-lev", v); if (data) paint(data); }, {label: "배수"});
  const sum = h("div");
  const body = h("div", {class: "stack"});
  const head = ui.screenHead("계좌", "계좌마다 배수 4줄 (각 $1,000에서 시작)");
  const headSub = head.querySelector(".sub");
  el.append(head,
    h("div", {class: "row wrap dl-levbar"}, h("span", {class: "dl-fk"}, "배수"), levSeg), sum, body,
    ui.note("잔고 = 지갑 + 열린 포지션 평가금. 손익은 시작 $1,000 대비. 파산 = 잔고가 $100 아래로 떨어져 멈춘 줄. 수수료·슬리피지·펀딩 포함, 주문 없음."));

  let data = null, seen = null;
  async function load() {
    let d;
    try { d = await ctx.api("/api/accounts"); } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!data) put(body, ui.errorBox(e, load));
      return;
    }
    if (d && d.generated_ms != null && d.generated_ms === seen) return;
    seen = d ? d.generated_ms : null;
    data = d;
    paint(d);
  }

  function paint(d) {
    if (isMissing(d)) { put(sum); put(body, ui.missing("계좌 목록")); return; }
    const accts = d.accounts || [];
    headSub.textContent = `${fmt.int(accts.length)}개 계좌 · 계좌마다 배수 4줄 (각 $1,000에서 시작)`;
    const levs = lev === "all" ? LEVS : [Number(lev)];
    const lines = accts.flatMap((a) => levs.map((L) => (a.lines || {})[String(L)]).filter(Boolean));
    const ruined = lines.filter((x) => x.ruined).length;
    const up = lines.filter((x) => Number(x.pnl_pct) > 0).length;
    put(sum, h("div", {class: "stats dl-s4"},
      ui.stat("계좌", fmt.int(accts.length), `보이는 줄 ${fmt.int(lines.length)}개`),
      ui.stat("이익 중인 줄", fmt.int(up), lines.length ? `${fmt.num(up / lines.length * 100, 0)}%` : null),
      ui.stat("파산한 줄", fmt.int(ruined), null, ruined ? "dl-bad" : null),
      ui.stat("열린 포지션", fmt.int(lines.reduce((s, x) => s + (Number(x.open) || 0), 0)), "보이는 줄 합계")));
    const known = new Set(KINDS.map((k) => k.id));
    const kinds = [...KINDS, ...(accts.some((a) => !known.has(a.kind || kindOfId(a.id))) ? [{id: "__other", ko: "기타", desc: "이 화면이 아직 모르는 종류"}] : [])];
    const kindOf = (a) => (known.has(a.kind || kindOfId(a.id)) ? a.kind || kindOfId(a.id) : "__other");
    const cards = kinds.map((k) => {
      const rows = accts.filter((a) => kindOf(a) === k.id);
      if (!rows.length) return null;
      const means = levs.map((L) => {
        const v = rows.map((a) => (a.lines || {})[String(L)]).filter(Boolean).map((x) => Number(x.pnl_pct)).filter(Number.isFinite);
        return v.length ? v.reduce((s, x) => s + x, 0) / v.length : null;
      });
      const mean = lev === "all" ? null : means[0];
      return ui.card({plate: k.ko, sub: `${rows.length}개 · ${k.desc}`,
        acts: mean != null ? h("span", {class: "dl-kmean"}, "평균 ", ui.signed(fmt.pct(mean, true), fmt.tone(mean, fmt.pct(mean)), "b")) : null},
      acctTable(rows, levs, ctx));
    });
    put(body, cards);
  }

  await load();
  ctx.every(60000, load);
}

function nameCell(a, ctx) {
  return h("div", {class: "dl-an"},
    h("a", {href: ctx.href("account", a.id), class: "dl-aname"}, a.name || a.id),
    h("span", {class: "dl-asub"}, SUB_KO[a.sub] ? h("span", {class: "pp thin"}, SUB_KO[a.sub]) : null,
      a.switches ? h("span", {class: "muted"}, ` 교체 ${fmt.int(a.switches)}회`) : null),
    h("span", {class: "dl-aset mono", title: a.setting_ko || ""}, a.setting_ko || "—"));
}

function lineCells(x) {
  if (!x) return [h("td", {colspan: "7", class: "muted"}, "—")];
  const pnlT = fmt.pct(x.pnl_pct, true);
  return [
    h("td", null, h("b", {class: ["num", fmt.tone(x.pnl_pct, pnlT)]}, pnlT)),
    h("td", null, h("span", {class: "num"}, fmt.money(x.equity))),
    h("td", null, fmt.int(x.trades)),
    h("td", null, fmt.ratio(x.win_rate)),
    h("td", null, fmt.ratio(x.max_dd)),          // max_dd: a 0-1 ratio of the peak (engine)
    h("td", null, x.open ? h("span", {class: "pp accent"}, fmt.int(x.open)) : "0"),
    h("td", null, x.ruined ? ui.pill("파산", "bad") : x.liqs ? ui.pill(`강제청산 ${x.liqs}`, "warn") : h("span", {class: "muted"}, "정상")),
  ];
}

function acctTable(rows, levs, ctx) {
  const heads = ["계좌", ...(levs.length > 1 ? ["배수"] : []), "손익", "잔고", "거래", "승률", "최대 낙폭", "열림", "상태"];
  const body = [];
  for (const a of rows) {
    levs.forEach((L, i) => {
      const x = (a.lines || {})[String(L)];
      const cells = [];
      if (i === 0) cells.push(h("td", {class: "l dl-c2 dl-acol", rowspan: String(levs.length)}, nameCell(a, ctx)));
      if (levs.length > 1) cells.push(h("td", {class: "dl-lev"}, h("span", {class: "dl-levtag", dataset: {lev: L}}, `${L}배`)));
      cells.push(...lineCells(x));
      const tr = h("tr", {class: ["click", i === levs.length - 1 ? "dl-last" : "dl-mid", x && x.ruined ? "dl-ruined" : ""]}, cells);
      tr.addEventListener("click", (e) => { if (!e.target.closest("a")) location.hash = ctx.href("account", a.id); });
      body.push(tr);
    });
  }
  return h("div", {class: "tbl-wrap"}, h("table", {class: ["tbl", "dl-accts", levs.length > 1 ? "dl-all" : ""]},
    h("thead", null, h("tr", null, heads.map((x, i) => h("th", {class: i === 0 ? "l dl-c2" : "", scope: "col"}, x)))),
    h("tbody", null, body)));
}
