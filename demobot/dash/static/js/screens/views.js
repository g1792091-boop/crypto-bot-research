// #/views 관점 기록 (CONTRACT 7.3): the owners' one-line views from the Telegram group, followed and scored by the
// engine. The verdict line, the summary (direction hits at 4h / 24h / 48h with p, zone reached, the two follow modes),
// the format to type, and every view newest first (zones, stop, targets, the memo as TEXT, the moves, the two follow
// results). views.json every 60 s.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {isMissing} from "../api.js";
import {COINS} from "../labels.js";

const MODES = [
  {id: "touch", ko: "구간 바로 진입", desc: "가장 가까운 구간 끝에 지정가"},
  {id: "confirm", ko: "15분 종가 확인 진입", desc: "구간을 건드린 뒤 15분 종가가 다시 진입 쪽에서 닫히면"},
];
const HORIZONS = [["4h", "4시간"], ["24h", "24시간"], ["48h", "48시간"]];
const STATUS_KO = {watching: "지켜보는 중", done: "끝남", cancelled: "취소"};
const STATUS_CLS = {watching: "accent", done: "thin", cancelled: "warn"};
const FSTATUS_KO = {waiting: "기다리는 중", open: "들어감", closed: "끝남", missed: "놓침"};
const FSTATUS_CLS = {waiting: "thin", open: "accent", closed: "", missed: "warn"};
const FORMAT_KO = "관점 [MM/DD HH:MM] 코인 롱|숏 [A 가격-가격] [B 가격-가격] [C 가격-가격] [손절 가격] [목표 가격,가격] [메모 글]";
const EXAMPLES = [
  "관점 BTC 숏 A 84750-84840 C 85300 손절 85600 메모 4시간 저항",
  "관점 10/09 21:30 ETH 롱 B 4,050~4,060 목표 4150,4200",
];

export async function mount(el, ctx) {
  ctx.setTitle("관점 기록");
  const saved = local.get("views", {}) || {};
  const f = {st: saved.st || "all", coin: saved.coin || "all"};
  const keep = () => local.set("views", f);
  const verdict = h("section", {class: "card hero dl-verdict vw-verdict", "aria-label": "관점 판정"});
  const sumBox = h("div", {class: "vw-sum"});
  const stSeg = ui.seg([{id: "all", label: "전체"}, {id: "watching", label: "지켜보는 중"}, {id: "done", label: "끝남"},
    {id: "cancelled", label: "취소"}], f.st, (v) => { f.st = v; keep(); apply(false); }, {label: "상태"});
  const coinSel = ui.select([{id: "all", label: "모든 코인"}, ...COINS.map((c) => ({id: c, label: fmt.coin(c)}))], f.coin,
    (v) => { f.coin = v; keep(); apply(false); }, "코인");
  const count = h("p", {class: "note"});
  const pg = ui.pager({size: 10, empty: "맞는 관점이 없습니다", render: (part) => h("div", {class: "vw-list"}, part.map(viewItem))});
  const howBox = ui.card({plate: "어떻게 적나", sub: "데모 랩 텔레그램 방에 한 줄로", cls: "vw-how"},
    h("p", {class: "vw-fmt mono"}, FORMAT_KO),
    h("div", {class: "vw-ex"}, h("span", {class: "dl-fk"}, "예"), EXAMPLES.map((x) => h("code", {class: "vw-code"}, x))),
    h("ul", {class: "dl-ul"},
      h("li", null, "구간은 하나 이상 (A · B · C). 가격 사이는 - 또는 ~, 쉼표는 있어도 됩니다."),
      h("li", null, "시각은 한국 시간, 없으면 보낸 시각. 코인은 BTC ETH SOL DOGE LTC BCH XRP."),
      h("li", null, "‘취소 번호’(예: 취소 12)로 지우고, ‘관점목록’은 최근 10개, ‘관점도움’은 쓰는 법을 보여 줍니다.")));
  el.append(ui.screenHead("관점 기록", "두 분이 텔레그램에 적은 관점을 봇이 따라가며 채점합니다"), verdict, sumBox,
    howBox,
    ui.card({plate: "관점 목록", sub: "새것부터", cls: "dl-controls"},
      h("div", {class: "dl-fields"}, ui.field("상태", stSeg), ui.field("코인", coinSel)), count, pg.el),
    ui.note("모의 채점입니다. 주문은 넣지 않습니다. 잔고 %는 20배 · 증거금 20% 규칙으로 계산한 값입니다."));

  let views = null, seen = null;
  function apply(keepPage) {
    if (!views) return;
    const out = views.filter((v) => (f.st === "all" || v.status === f.st) && (f.coin === "all" || v.coin === f.coin));
    count.textContent = `관점 ${fmt.int(views.length)}개 중 ${fmt.int(out.length)}개`;
    pg.set(out, keepPage);
  }
  async function load() {
    let d;
    try { d = await ctx.api("/api/views"); } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!views) put(verdict, ui.errorBox(e, load));
      return;
    }
    const key = d && !isMissing(d) ? `${d.generated_ms}|${(d.views || []).length}` : "missing";
    if (key === seen) return;
    seen = key;
    if (isMissing(d)) {
      put(verdict, h("div", {class: "card-h"}, ui.plate("관점 판정")), ui.missing("관점 기록 (views.json)"));
      put(sumBox);
      views = [];
      apply(false);
      return;
    }
    const first = views == null;
    paintVerdict(d);
    paintSummary(d.summary || {});
    views = d.views || [];
    apply(!first);
  }

  function paintVerdict(d) {
    const s = d.summary || {};
    const need = Number(s.need) || 30, done = Number(s.n_done) || 0;
    const short = done < need;
    put(verdict,
      h("div", {class: "card-h"}, ui.plate("관점 판정"), h("span", {class: "sub"}, `관점 ${fmt.int(s.n)}개 · 끝난 것 ${fmt.int(done)}개`)),
      short ? h("p", {class: "dl-vbig warn"}, "표본 부족") : null,
      h("p", {class: ["dl-vline", short ? "" : "vw-vtext"]}, s.verdict_ko || (short ? `표본 부족 (${done}/${need})` : "—")),
      h("div", {class: "vw-prog"}, h("span", {class: "muted"}, `끝난 관점 ${fmt.int(done)} / ${fmt.int(need)}`),
        h("div", {class: "prog", role: "img", "aria-label": `끝난 관점 ${done} / ${need}`},
          h("i", {style: {"--p": `${Math.min(100, (done / need) * 100)}%`}}))),
      d.rules_ko && d.rules_ko.length ? ui.disclosure("채점 규칙", h("ol", {class: "dl-rules"}, d.rules_ko.map((x) => h("li", null, x)))) : null);
  }

  function paintSummary(s) {
    const dir = s.dir || {};
    const dirCard = ui.card({plate: "방향 맞힘", sub: "말한 방향으로 움직였나 (50%가 운)"},
      h("div", {class: "stats vw-s3"}, HORIZONS.map(([k, ko]) => {
        const x = dir[k] || {};
        return ui.stat(ko, fmt.ratio(x.rate), `${fmt.int(x.n || 0)}건 중 ${fmt.int(x.hit || 0)}건${x.p != null ? ` · p ${fmt.num(x.p, 3)}` : ""}`,
          x.p != null && x.p < 0.05 && x.rate > 0.5 ? "dl-good" : null);
      })));
    const reachCard = ui.card({plate: "구간 도달", sub: "48시간 안에 가장 가까운 구간 끝을 건드렸나"},
      h("div", {class: "stats vw-s1"}, ui.stat("도달 비율", fmt.ratio(s.reached_rate), `끝난 관점 ${fmt.int(s.n_done || 0)}개 기준`)));
    const follow = s.follow || {};
    const modeCards = MODES.map((m) => {
      const x = follow[m.id] || {};
      const mT = fmt.r(x.mean_R), sT = fmt.r(x.sum_R), wT = fmt.pct(x.wallet20_pct, true);
      return ui.card({plate: m.ko, sub: m.desc},
        h("div", {class: "stats vw-s5"},
          ui.stat("진입", `${fmt.int(x.entered || 0)} / ${fmt.int(x.n || 0)}`, "들어간 관점 / 전체"),
          ui.stat("평균 R", h("b", {class: ["num", fmt.tone(x.mean_R, mT)]}, mT), x.ci_low != null ? `하한 ${fmt.r(x.ci_low)}` : "닫힌 거래 기준"),
          ui.stat("승률", fmt.ratio(x.win_rate), "닫힌 거래 기준"),
          ui.stat("합계 R", h("b", {class: ["num", fmt.tone(x.sum_R, sT)]}, sT), "닫힌 거래 합"),
          ui.stat("20배 잔고", h("b", {class: ["num", fmt.tone(x.wallet20_pct, wT)]}, wT), "시작 대비")));
    });
    put(sumBox, h("div", {class: "grid2"}, dirCard, reachCard), h("div", {class: "grid2"}, modeCards));
  }

  await load();
  ctx.every(60000, load);
}

function zoneText(z) {
  if (!Array.isArray(z) || z.length < 2) return null;
  return z[0] === z[1] ? fmt.price(z[0]) : `${fmt.price(Math.min(z[0], z[1]))} – ${fmt.price(Math.max(z[0], z[1]))}`;
}

function viewItem(v) {
  const zones = ["A", "B", "C"].map((k) => [k, zoneText(v.zones && v.zones[k])]).filter((x) => x[1]);
  const side = Number(v.side) > 0;
  const dir = v.dir || {};
  const moves = HORIZONS.map(([k, ko]) => {
    const x = dir[k];
    const t = x == null ? "—" : fmt.pct(x, true, 2);
    return h("div", {class: "vw-mv"}, h("span", {class: "muted"}, ko), h("b", {class: ["num", fmt.tone(x, t)]}, t),
      x == null ? h("span", {class: "dl-mk na"}, "") : ui.mark(x > 0));
  });
  const reached = v.reached == null ? h("span", {class: "muted"}, v.status === "watching" ? "아직" : "—")
    : v.reached ? h("span", null, ui.mark(true, "예"), v.reached_ms ? h("span", {class: "muted"}, ` ${fmt.kst(v.reached_ms)}`) : null)
      : ui.mark(false, "아니오");
  const fol = v.follow || {};
  return h("article", {class: ["vw", v.status === "cancelled" ? "vw-off" : ""], "aria-label": `관점 ${v.id}`},
    h("div", {class: "vw-top"},
      h("b", {class: "vw-id"}, `#${v.id}`),
      h("span", {class: "num muted"}, fmt.kst(v.t_ms)),
      h("b", null, fmt.coin(v.coin)),
      h("span", {class: ["side", side ? "long" : "short"]}, side ? "롱" : "숏"),
      ui.pill(STATUS_KO[v.status] || v.status || "—", STATUS_CLS[v.status] || "")),
    h("div", {class: "vw-body"},
      h("div", {class: "vw-plan"},
        h("div", {class: "vw-zones"}, zones.length ? zones.map(([k, t]) => h("span", {class: "vw-z"}, h("b", null, k), " ", h("span", {class: "num"}, t))) : h("span", {class: "muted"}, "구간 없음")),
        h("div", {class: "vw-kv"},
          h("span", null, h("span", {class: "muted"}, "손절 "), h("b", {class: "num"}, v.stop != null ? fmt.price(v.stop) : "자동")),
          h("span", null, h("span", {class: "muted"}, "목표 "), h("b", {class: "num"}, v.targets && v.targets.length ? v.targets.map(fmt.price).join(" · ") : "자동 (1R 절반 · 2R)")),
          v.ref_price != null ? h("span", null, h("span", {class: "muted"}, "기준 가격 "), h("b", {class: "num"}, fmt.price(v.ref_price))) : null),
        v.memo ? h("p", {class: "vw-memo"}, v.memo) : null),
      h("div", {class: "vw-dir"}, moves, h("div", {class: "vw-mv"}, h("span", {class: "muted"}, "구간 도달"), reached)),
      h("div", {class: "vw-fol"}, MODES.map((m) => followBox(m, fol[m.id] || {})))));
}

function followBox(m, x) {
  const rT = fmt.r(x.R), wT = fmt.pct(x.wallet20_pct, true);
  return h("div", {class: "vw-f"},
    h("div", {class: "vw-fh"}, h("span", {class: "vw-fn"}, m.ko), ui.pill(FSTATUS_KO[x.status] || x.status || "—", FSTATUS_CLS[x.status] || "")),
    x.entry != null ? h("div", {class: "vw-fl"}, h("span", {class: "muted"}, "진입 "), h("span", {class: "num"}, fmt.price(x.entry)),
      x.entry_ms ? h("span", {class: "muted num"}, ` ${fmt.kst(x.entry_ms)}`) : null) : null,
    x.R != null ? h("div", {class: "vw-fl"}, h("b", {class: ["num", fmt.tone(x.R, rT)]}, rT), " · 20배 ",
      h("b", {class: ["num", fmt.tone(x.wallet20_pct, wT)]}, wT)) : null,
    x.legs_ko ? h("div", {class: "vw-fl muted"}, x.legs_ko) : null);
}
