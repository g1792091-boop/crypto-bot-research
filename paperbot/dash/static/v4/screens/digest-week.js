// 회의 요약 · 주간 성적표 and 봉 비교 (builder D). Week: the last 7 days against the 7 before (what the Sunday Telegram
// report sends, with that text as a preview behind a fold); top / bottom strategies, per timeframe, the staff's week.
// 봉 비교: each strategy's timeframe accounts side by side, the ones that disagree marked 봉마다 갈림.
// Money: closed trades, so every block carries assume(); the comparison with the coin flips is '참고' with refNote.
// GET /api/digest/week, /api/digest/tf (computed by the server, answered from its cache when it is fresh).
import {h, put, ui, fmt, motion, store, features} from "../core/pb.js";

const signMoney = (x) => fmt.money(x, true);
const verdictTs = () => { const s = store.get("summary"); return s ? ((s.restart && s.restart.ready && s.restart.verdict_ts) || (s.next_checkpoint && s.next_checkpoint.ts)) : null; };

export function makeWeek(ctx) {
  const st = {d: null, req: 0};
  const body = h("div", {class: "stack"}, motion.shimmer(5));
  const el = h("div", {class: "dg-week stack"}, body);

  const rankRows = (rows) => rows.map((r) => {
    let mv = null;
    if (r.prev_rank) { const dl = r.prev_rank - r.rank; mv = dl > 0 ? h("span", {class: "up"}, `▲${dl}`) : dl < 0 ? h("span", {class: "down"}, `▼${-dl}`) : h("span", {class: "muted"}, "="); }
    return h("div", {class: "lrow click", role: "listitem", onclick: () => ctx.go("strategies", r.strategy)},
      h("span", {class: "rk"}, String(r.rank)), h("span", {class: "lname"}, r.name_ko || r.strategy),
      h("span", {class: ["ret", fmt.tone(r.pnl)]}, signMoney(r.pnl)),
      h("span", {class: "meta"}, h("span", null, `거래 ${fmt.int(r.trades)}`), h("span", null, `승률 ${fmt.pct(r.win_rate, 0, false)}`), ui.smallSample(r.trades),
        mv ? h("span", null, "지난주 대비 ", mv) : null));
  });

  function render(d) {
    const t = d.strategies_total || {}, tp = d.strategies_total_prev || {}, cf = d.coin_flips || {}, s = d.staff;
    const prevKo = tp.trades ? `지난주 ${signMoney(tp.pnl)} USDT` : d.run_start > d.from - 7 * 86400000 ? "지난주: 실험 시작 전후라 비교 안 함" : "지난주 기록 없음";
    const kids = [];
    if (d.error) kids.push(h("p", {class: "rk-banner bad"}, String(d.error)));
    kids.push(ui.card({plate: "최근 7일", sub: `${fmt.mmdd(d.from)} ~ ${fmt.mmdd(d.to)} · 기존 36개 매매법 계좌`},
      h("div", {class: "stats s4"},
        ui.stat("매매법 계좌 손익", h("b", {class: ["num", fmt.tone(t.pnl)]}, `${signMoney(t.pnl)} USDT`), prevKo),
        ui.stat("거래 · 승률", fmt.int(t.trades || 0), `승률 ${fmt.pct(t.win_rate, 0, false)}${tp.trades ? ` (지난주 ${fmt.pct(tp.win_rate, 0, false)})` : ""}`),
        ui.stat("같은 봉 동전 봇 중앙값보다 위", cf.strategy_accounts ? `${fmt.int(cf.strategy_accounts_beating_median)}/${fmt.int(cf.strategy_accounts)}` : "—",
          h("span", {class: "s"}, ui.pill("7일", "ref"), ` 동전 봇 평균 ${signMoney(cf.mean_pnl)}`)),
        ui.stat("파산", fmt.int((d.busts || []).length), "최근 7일")),
      ui.refNote(verdictTs(), "7일 성적은 운이 큽니다."), ui.assume()));
    kids.push(h("div", {class: "grid2"},
      ui.card({plate: "이번 주 상위"}, h("div", {class: "plist", role: "list"}, rankRows(d.top || [])), ui.assume()),
      ui.card({plate: "이번 주 하위"}, h("div", {class: "plist", role: "list"}, rankRows(d.bottom || [])), ui.assume())));
    const tfs = Object.entries(d.timeframes || {});
    kids.push(h("div", {class: "grid2"},
      ui.card({plate: "봉별 합계"}, tfs.length ? ui.kv(tfs.map(([tf, v]) => [fmt.tfKo(tf),
        h("span", {class: fmt.tone(v.pnl)}, `${signMoney(v.pnl)} `, h("small", {class: "muted"}, `${fmt.int(v.trades)}건 · 승률 ${fmt.pct(v.win_rate, 0, false)}`))])) : ui.empty("기록 없음"), ui.assume()),
      ui.card({plate: "직원의 한 주"}, s ? ui.kv([["회의", `${fmt.int(s.meetings_total)}번`], ["AI 호출", `${fmt.int(s.ai_calls)}번`], ["토큰", fmt.compact(s.ai_tokens)],
        ["가설 기록", `${fmt.int(s.hypotheses)}건`], ["예측 채점", `${fmt.int(s.predictions_correct)}/${fmt.int(s.predictions_graded)} 맞음`],
        ["5년 시험", `${fmt.int(s.tests)}건 (통과 ${fmt.int(s.tests_passed)})`], ["새 매매법 시험", `${fmt.int(s.lab_tests)}건 (통과 ${fmt.int(s.lab_passed)})`]]) : ui.empty("기록 없음"))));
    const gh = d.ghcoin;
    if (features.ghcoin && gh && gh.all && gh.all.calls) {
      kids.push(ui.card({plate: "GH Coin 기록기", sub: "친구 봇 타점, 기록만 · 수수료 뒤 R"}, ui.kv([["최근 7일", gh.week], ["시작부터", gh.all]].map(([k, x]) =>
        [k, x && x.calls ? `${fmt.int(x.calls)}타점 · ${fmt.num(x.net_r, 1, true)}R (동전 ${fmt.num(x.coin_flip_net_r, 1, true)}R)` : "끝난 타점 없음"])), ui.pill("참고", "ref")));
    }
    const hrs = d.hours || {}, wh = hrs.weekly_report_hour_kst;
    const when = wh == null ? "일요일 텔레그램으로 가는 글" : wh < 0 ? "텔레그램 주간 성적표는 꺼져 있음" : `일요일 ${String(wh).padStart(2, "0")}:00 텔레그램으로 가는 글`;
    if (d.telegram_text) kids.push(ui.card({plate: "텔레그램 미리보기", sub: `${when} · 지금 기준`}, ui.disclosure("펼쳐 보기", h("pre", {class: "dg-tg"}, d.telegram_text))));
    if (d.note) kids.push(h("p", {class: "rk-note"}, d.note));
    body.replaceChildren(...kids);
  }
  async function load() {
    const req = ++st.req;
    try {
      const d = await ctx.api("/api/digest/week");
      if (req !== st.req || !ctx.alive()) return;
      if (st.d && st.d.computed_at === d.computed_at) return;
      st.d = d; render(d);
    } catch (e) { if (req === st.req && ctx.alive() && !(e && e.name === "AbortError") && !st.d) body.replaceChildren(ui.errorBox(e, load)); }
  }
  return {el, show: () => (st.d ? null : load()), refresh: load};
}

export function makeTf(ctx) {
  const st = {d: null, req: 0, open: new Set()};
  const intro = h("p", {class: "ink2 dg-tfintro"});
  const list = ui.pager({size: 10, empty: "아직 끝난 거래가 없습니다", row: (r) => row(r)});
  const body = h("div", {class: "stack"}, motion.shimmer(5));
  const el = h("div", {class: "dg-tf stack"}, intro, body);
  const TFS = ["15m", "30m", "1h", "4h"];

  function tfDetail(r) {
    return h("div", {class: "dg-tfg"}, TFS.filter((tf) => (r.timeframes[tf] || {}).trades).map((tf) => {
      const v = r.timeframes[tf];
      return h("div", {class: "dg-tfc"}, h("b", null, `${fmt.tfKo(tf)} `, h("small", {class: "muted"}, `${fmt.int(v.trades)}건`), " ", ui.smallSample(v.trades)),
        ui.kv([["손익", h("span", {class: fmt.tone(v.pnl)}, signMoney(v.pnl))], ["승률", fmt.pct(v.win_rate, 0, false)], ["거래당 평균 ROE", fmt.pct(v.mean_roe, 2)],
          ["비용 전 가격 움직임", fmt.pct(v.move_before_costs, 3)], ["거래당 비용", fmt.money(v.cost_per_trade)],
          ["비용 ÷ 비용 전 손익", v.cost_vs_gross == null ? "—" : h("span", {class: v.cost_vs_gross > 1 ? "down" : ""}, fmt.num(v.cost_vs_gross, 2))],
          ["평균 보유", fmt.dur((v.hold_min || 0) * 60)],
          ["롱 · 숏", Object.entries(v.sides || {}).map(([k, x]) => `${k} ${fmt.int(x.trades)}건 ${signMoney(x.pnl)}`).join(" · ") || "—"],
          ["청산", Object.entries(v.exits || {}).map(([k, n]) => `${k} ${fmt.int(n)}`).join(" · ") || "—"]]));
    }));
  }
  function row(r) {
    const key = r.strategy, open = st.open.has(key);
    const region = h("div", {class: "region", hidden: !open}, open ? tfDetail(r) : null);
    const btn = h("button", {class: "linkish", type: "button", "aria-expanded": String(open)}, open ? "접기" : "자세히");
    btn.addEventListener("click", () => {
      const o = btn.getAttribute("aria-expanded") !== "true";
      btn.setAttribute("aria-expanded", String(o)); btn.textContent = o ? "접기" : "자세히";
      if (o) { st.open.add(key); if (!region.firstChild) region.append(tfDetail(r)); } else st.open.delete(key);
      motion.expand(region, o);
    });
    return h("div", {class: "dg-tfrow", role: "listitem"},
      h("div", {class: "lrow"}, h("span", {class: "rk"}, r.split ? "갈림" : ""), h("span", {class: "lname"}, h("a", {href: ctx.href("strategies", r.strategy)}, r.name_ko || r.strategy)),
        h("span", {class: ["ret", fmt.tone(r.pnl)]}, signMoney(r.pnl)),
        h("span", {class: "meta"}, r.split ? ui.pill("봉마다 갈림", "warn") : null,
          TFS.map((tf) => { const v = r.timeframes[tf]; return v && v.trades ? h("span", {class: "dg-tfchip"}, `${fmt.tfKo(tf)} `, h("b", {class: fmt.tone(v.pnl)}, signMoney(v.pnl)), ` · ${fmt.int(v.trades)}건${v.bust ? " · 파산" : ""}`) : null; }),
          r.spread != null ? h("span", null, `최고−최저 ${fmt.money(r.spread)}`) : null, btn)),
      region);
  }
  async function load() {
    const req = ++st.req;
    let d;
    try { d = await ctx.api("/api/digest/tf"); } catch (e) {
      if (req === st.req && ctx.alive() && !(e && e.name === "AbortError") && !st.d) body.replaceChildren(ui.errorBox(e, load));
      return;
    }
    if (req !== st.req || !ctx.alive()) return;
    if (st.d && st.d.computed_at === d.computed_at) return;
    st.d = d;
    if (d.error) { body.replaceChildren(ui.empty(String(d.error))); return; }
    const th = d.hours && d.hours.tf_split_hour_kst;
    intro.textContent = `같은 매매법이 봉마다 정반대 결과를 내면 (한 봉은 이익, 다른 봉은 손실, 둘 다 거래 ${fmt.int(d.min_trades)}건 이상, 차이가 시작 자금의 ` +
      `${fmt.pct(d.min_spread_pct || 0, 0, false)} 이상, 파산 계좌 제외) '봉마다 갈림'으로 표시합니다. ` +
      (th != null && th < 0 ? "봉 비교 회의는 꺼져 있습니다." : `매일 ${String(th == null ? 18 : th).padStart(2, "0")}:00에 가장 크게 갈린 매매법 2개의 방에서 '봉 비교 회의'가 열립니다.`);
    if (!list.el.isConnected) put(body, ui.card({plate: "매매법별 봉 비교", sub: "차이 큰 순 · 10개씩 · 기존 36개"}, list.el, ui.assume()), d.note ? h("p", {class: "rk-note"}, d.note) : null);
    list.set(d.strategies || [], true);
  }
  return {el, show: () => (st.d ? null : load()), refresh: load};
}
