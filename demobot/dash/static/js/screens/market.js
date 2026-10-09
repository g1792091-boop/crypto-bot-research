// #/market 시장 (CONTRACT 9.1, 9.8): the whole market of each coin (Binance, not our bots), read by the dashboard
// server and cached: price and 24 h change (/api/live, every 10 s), funding of the last three 8-hour rounds and the
// time to the next, open interest now and its 24 h change, and the share of accounts holding longs vs shorts over the
// last 24 hours (/api/market, every 60 s). One table with small line graphs, and a plain sentence for every column.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import {COINS} from "../labels.js";
import * as K from "../live-kit.js";

const EXPLAIN = [
  ["가격 · 24시간", "지금 가격과 24시간 전보다 몇 % 올랐나(내렸나)."],
  ["펀딩", "8시간마다 롱과 숏이 서로 주고받는 돈의 비율. +면 롱이 숏에게 냅니다. 보통은 +0.0100%이고, 0.05%를 넘으면 한쪽으로 많이 쏠렸다는 뜻이라 주황색으로 보입니다. 작은 그래프는 지난 세 번."],
  ["다음 펀딩까지", "다음에 펀딩을 주고받을 때까지 남은 시간 (한국 시간 01시 · 09시 · 17시)."],
  ["미결제약정", "아직 닫히지 않은 계약 전체의 크기(달러). 늘면 새 돈이 들어오는 중, 줄면 포지션을 정리하는 중. 작은 그래프는 지난 24시간(1시간마다)."],
  ["롱/숏 계정 비율", "바이낸스 계정 가운데 롱을 든 계정 수 ÷ 숏을 든 계정 수. 1보다 크면 롱 계정이 더 많습니다 (돈의 크기가 아니라 계정 수). 괄호 안은 롱 계정의 비율, 작은 그래프는 지난 24시간."],
];

export async function mount(el, ctx) {
  await K.needCss();
  ctx.setTitle("시장");
  const tableBox = h("div"), liveLine = h("p", {class: "note"}), stamp = h("p", {class: "note"});
  el.append(ui.screenHead("시장", "코인마다 시장 전체의 숫자 (우리 봇이 아니라 바이낸스 전체)"),
    ui.card({plate: "코인 7개", sub: "가격 10초마다 · 나머지 1분마다"}, tableBox, liveLine, stamp),
    ui.card({plate: "칸마다 뜻"}, h("dl", {class: "lv-explain"}, EXPLAIN.map(([k, v]) => h("div", null, h("dt", null, k), h("dd", null, v))))),
    ui.note("대시보드 서버가 바이낸스 공개 시세(키 없음)를 읽어 잠시 보관합니다. 이 화면은 우리 서버에만 묻습니다. 주문은 넣지 않습니다."));

  let mkt = null, live = null, failed = false;
  const liveOf = (c) => (live && (live.coins || []).find((x) => x.coin === c)) || null;
  function paint() {
    if (!mkt && !live) { put(tableBox, failed ? ui.errorBox({status: 0}, load) : ui.empty("불러오는 중")); return; }
    if ((mkt && mkt.off) || (live && live.off)) { put(tableBox, h("div", {class: "dl-missing"}, h("b", null, "꺼짐"), h("span", null, " · 실시간 시세가 꺼져 있습니다 (DEMOBOT_DASH_LIVE=off)."))); return; }
    const rows = COINS.map((c) => ({coin: c, m: mkt && (mkt.coins || []).find((x) => x.coin === c), l: liveOf(c)}));
    if (rows.every((r) => !(r.m && r.m.ok) && !(r.l && r.l.ok))) {
      put(tableBox, h("div", {class: "dl-missing"}, h("b", null, "준비 중"), h("span", null, " · 바이낸스 시세를 아직 받지 못했습니다. 잠시 뒤 다시 받습니다.")));
      return;
    }
    const cell = {
      price: (r) => {
        const p = r.l && r.l.ok ? r.l : r.m;
        if (!p || p.price == null) return h("span", {class: "muted"}, "—");
        return h("span", {class: "lv-mc"}, h("b", {class: "num"}, K.px(p.price)), h("span", {class: ["num", fmt.tone(p.change_pct)]}, fmt.pct(p.change_pct, true, 2)));
      },
      fund: (r) => {
        const rate = (r.l && r.l.funding_rate != null) ? r.l.funding_rate : r.m && r.m.funding_rate;
        const hist = r.m && r.m.funding ? r.m.funding : [];
        return h("span", {class: "lv-mc"}, h("b", {class: ["num", Math.abs(Number(rate)) >= 0.0005 ? "warn-t" : ""]}, K.fundPct(rate)),
          hist.length ? h("span", {class: "lv-msp", title: hist.map((x) => `${fmt.kst(x[0])} ${K.fundPct(x[1])}`).join("\n")},
            K.spark(hist, {w: 60, h: 22, zero: true, dots: true, label: "지난 세 번의 펀딩"})) : null);
      },
      next: (r) => {
        const t = (r.l && r.l.next_funding_ms) || (r.m && r.m.next_funding_ms);
        return h("span", {class: "num", dataset: {cd: String(t || "")}}, K.countdown(t));
      },
      oi: (r) => {
        const m = r.m;
        if (!m || !m.ok) return h("span", {class: "muted"}, "—");
        const usd = m.oi_value_usd != null ? m.oi_value_usd : m.open_interest != null && m.price ? m.open_interest * m.price : null;
        return h("span", {class: "lv-mc"}, h("b", {class: "num"}, `$${K.usdKo(usd)}`),
          h("span", {class: ["num", fmt.tone(m.oi_change_24h_pct)]}, fmt.pct(m.oi_change_24h_pct, true, 1)),
          h("span", {class: "lv-msp"}, K.spark(m.oi_hist || [], {w: 90, h: 22, area: true, cls: Number(m.oi_change_24h_pct) >= 0 ? "up" : "down", label: "지난 24시간 미결제약정"})));
      },
      ls: (r) => {
        const m = r.m;
        if (!m || !m.ok || m.ls_now == null) return h("span", {class: "muted"}, "—");
        return h("span", {class: "lv-mc"}, h("b", {class: "num"}, fmt.num(m.ls_now, 2)),
          h("span", {class: "muted num"}, `(롱 ${fmt.ratio(m.long_share, 0)})`),
          h("span", {class: "lv-msp"}, K.spark(m.ls_ratio || [], {w: 90, h: 22, label: "지난 24시간 롱/숏 계정 비율"})));
      },
    };
    const name = (r) => h("a", {href: ctx.href("terminal", r.coin), title: "터미널에서 보기"}, fmt.coin(r.coin));
    // a PC: one table; a phone: one card per coin with the same cells (no sideways scrolling)
    put(tableBox, h("div", {class: "lv-only-wide"}, ui.table([
      {label: "코인", l: true, get: name},
      {label: "가격 · 24시간", get: cell.price},
      {label: "펀딩", get: cell.fund},
      {label: "다음 펀딩까지", get: cell.next},
      {label: "미결제약정 · 24시간", get: cell.oi},
      {label: "롱/숏 계정 비율", get: cell.ls},
    ], rows, {cls: "lv-mtbl"})),
    h("div", {class: "lv-only-narrow"}, h("div", {class: "lv-mcards"}, rows.map((r) => h("div", {class: "lv-mcard"},
      h("div", {class: "lv-mch"}, h("b", null, name(r)), h("span", {class: "grow"}), cell.price(r)),
      h("div", {class: "lv-mrow"}, h("span", {class: "k"}, "펀딩"), cell.fund(r)),
      h("div", {class: "lv-mrow"}, h("span", {class: "k"}, "다음 펀딩까지"), cell.next(r)),
      h("div", {class: "lv-mrow"}, h("span", {class: "k"}, "미결제약정"), cell.oi(r)),
      h("div", {class: "lv-mrow"}, h("span", {class: "k"}, "롱/숏 계정"), cell.ls(r)))))));
    stamp.textContent = mkt && mkt.generated_ms ? `펀딩 · 미결제약정 · 롱/숏: ${fmt.hms(mkt.generated_ms)} KST에 받은 값${mkt.stale ? " (새로 받지 못해 예전 값)" : ""}` : "";
  }
  async function load() {
    try { mkt = await ctx.api("/api/market"); failed = false; } catch (e) { if (e && e.name === "AbortError") return; failed = true; }
    paint();
  }
  async function loadLive() {
    try { live = await ctx.api("/api/live"); } catch (e) { if (e && e.name === "AbortError") return; }
    liveLine.textContent = `가격: ${K.liveNote(live)}`;
    paint();
  }
  paint();
  await Promise.all([loadLive(), load()]);
  ctx.every(10000, loadLive);
  ctx.every(60000, load);
  ctx.every(1000, async () => { for (const b of el.querySelectorAll("[data-cd]")) b.textContent = K.countdown(Number(b.dataset.cd) || null); });
}
