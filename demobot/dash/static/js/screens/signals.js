// #/signals 신호 (CONTRACT 9.4, 9.8): how many settings of each strategy fired long / short at the last closed bar,
// for every coin x timeframe x strategy (signals_now.json): a heat table (the colour leans to the side with more votes;
// the numbers are always written), each coin's last 96 bars of 15m votes as a small line (long minus short, three
// strategies together), and the entries the accounts really took in the last 24 hours. Every 60 s.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {isMissing} from "../api.js";
import {COINS, STRAT_KO, tfKo} from "../labels.js";
import * as K from "../live-kit.js";

const SHORT = {S2_ST_ROC: "S2", N02_ST_KST: "N02", N04_ST_KLINGER: "N04"};
const COLS = K.STRATS.flatMap((s) => ["15m", "30m"].map((tf) => ({strat: s, tf})));

export async function mount(el, ctx) {
  await K.needCss();
  ctx.setTitle("신호");
  const heatBox = h("div"), barLine = h("p", {class: "note"});
  const recPg = ui.pager({size: 20, empty: "지난 24시간에 계좌가 들어간 신호가 없습니다", render: (part) => recentList(part, ctx)});
  el.append(ui.screenHead("신호", "매매법마다 설정 몇 개가 지금 롱 / 숏을 말하나"),
    ui.card({plate: "신호 투표", sub: "마지막으로 닫힌 봉 · 칸 = 롱 개수 · 숏 개수"}, barLine, heatBox,
      ui.note("투표 = 그 봉에서 새 신호가 난 설정의 수입니다 (S2 343개, N02 735개, N04 588개 중). 많은 설정이 같은 쪽을 말해도 "
        + "그것이 맞는다는 뜻은 아닙니다: 순위표의 성적과 같이 보세요. 오른쪽 작은 선 = 지난 96개 15분봉의 (롱 − 숏), 세 매매법 합.")),
    ui.card({plate: "계좌가 들어간 신호", sub: "지난 24시간 · 새것부터 · 20배 줄 기준"}, recPg.el),
    ui.note(`${Object.entries(STRAT_KO).map(([k, v]) => `${k} = ${v}`).join(" · ")}. 주문은 넣지 않습니다.`));

  let seen = null;
  async function load() {
    let d;
    try { d = await ctx.api("/api/signals_now"); } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!seen) put(heatBox, ui.errorBox(e, load));
      return;
    }
    const key = d && !isMissing(d) ? String(d.generated_ms) : "missing";
    if (key === seen) return;
    const first = seen == null;
    seen = key;
    if (isMissing(d)) { put(heatBox, ui.missing("신호 자료")); barLine.textContent = ""; recPg.set([]); return; }
    const bm = d.bar_ms || {};
    barLine.textContent = `15분봉 ${fmt.kst(bm["15m"])} · 30분봉 ${fmt.kst(bm["30m"])} (봉이 열린 시각, 한국 시간)`;
    const votes = d.votes || [];
    const at = (c, s, tf) => votes.find((v) => v.coin === c && v.strategy === s && v.tf === tf);
    const head = h("tr", null, h("th", {class: "l", scope: "col"}, "코인"),
      COLS.map((x) => h("th", {scope: "col", title: `${STRAT_KO[SHORT[x.strat]] || x.strat} · ${tfKo(x.tf)}`}, `${SHORT[x.strat]} ${tfKo(x.tf)}`)),
      h("th", {scope: "col"}, "흐름 (15분, 96봉)"));
    const body = COINS.map((c) => {
      const hist = new Map();
      for (const s of K.STRATS) {
        const v = at(c, s, "15m");
        for (const p of (v && v.history) || []) hist.set(p[0], (hist.get(p[0]) || 0) + Number(p[1]) - Number(p[2]));
      }
      const pts = [...hist.entries()].sort((a, b) => a[0] - b[0]);
      const net = pts.reduce((a, p) => a + p[1], 0);
      return h("tr", null, h("td", {class: "l"}, h("a", {href: ctx.href("terminal", c), title: "터미널에서 보기"}, h("b", null, fmt.coin(c)))),
        COLS.map((x) => {
          const v = at(c, x.strat, x.tf);
          if (!v) return h("td", {class: "lv-hc none"}, h("span", {class: "muted"}, "—"));
          const L = Number(v.long) || 0, S = Number(v.short) || 0, n = Number(v.settings) || 1;
          const lean = (L - S) / Math.max(1, L + S);
          const strength = Math.min(1, (L + S) / (n * 0.04));
          return h("td", {class: ["lv-hc", lean > 0.15 ? "up" : lean < -0.15 ? "down" : "flat"], style: {"--a": (0.08 + 0.5 * strength * Math.abs(lean)).toFixed(3)},
            title: `${fmt.coin(c)} · ${SHORT[x.strat]} · ${tfKo(x.tf)}: 설정 ${fmt.int(n)}개 중 롱 ${L} · 숏 ${S}`},
          h("span", {class: "lv-hv num"}, h("span", {class: "up"}, String(L)), h("span", {class: "muted"}, " · "), h("span", {class: "down"}, String(S))));
        }),
        h("td", {class: "lv-hsp"}, K.spark(pts, {w: 120, h: 24, zero: true, area: true, cls: net >= 0 ? "up" : "down", label: `${fmt.coin(c)} 지난 96봉 롱 − 숏`})));
    });
    put(heatBox, h("div", {class: "tbl-wrap"}, h("table", {class: "tbl lv-heat"}, h("thead", null, head), h("tbody", null, body))));
    recPg.set(d.recent || [], !first);
  }
  await load();
  ctx.every(60000, load);
}

function recentList(rows, ctx) {
  return h("div", {class: "lv-rlist"}, rows.map((r) => h("div", {class: "lv-rrow"},
    h("span", {class: "num muted"}, fmt.kst(r.t_ms)),
    h("a", {href: ctx.href("terminal", r.coin)}, h("b", null, fmt.coin(r.coin))), K.sideTag(r.side), h("span", {class: "pp thin"}, tfKo(r.tf)),
    h("span", {class: "lv-racc"}, (r.accounts || []).map((a, i) => [i ? ", " : "", h("a", {href: ctx.href("account", a.id), title: a.setting_ko || ""}, a.name || a.id)])))));
}
