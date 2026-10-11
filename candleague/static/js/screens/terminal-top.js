// 터미널 top (the rule bot's v4 terminal-top.js + terminal-stats.js + terminal-band.js, copied and adapted): one calm
// line — the coin (BTCUSDT · 무기한 · 모의), its big price (a glow only when the price really moved), the 24 h change,
// 24시간 거래대금, 마크, 펀딩 (who pays) / 다음까지, 미결제약정, the 24 h range, the league's open positions on this coin
// (롱 n · 숏 n, the crowding dot), the price feed's state, the bar-close countdown and the KST clock — and under it the
// band "후보 리그 지금": the engine's state, D+n and the next checkpoint, the open positions, the 후보 accounts' unrealized
// total, today's closed 후보 trades and "엔진 기준 HH:MM (n분 전 씀) · 시세 n초 전". A banner says when the positions are
// not "now" (the engine replaying from 10/01, or stopped): then no live P&L anywhere on the terminal.
// The rule bot's market-wide cells (급등 · 급락 · 음펀비, AI 회의 줄) have no data source here: left out, never faked.
// Data: the page's one /api/live poll (5 s), /api/positions (30 s and on each new snapshot), the shared snapshot.
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as LK from "../lk.js";
import {liveRow, liveState, serverNow} from "../live.js";
import {freshLine, staleBanner, liveOk, waitKo, sums, crowd, inGroup, POS_GROUPS} from "../poskit.js";
import {tickPrice} from "../v4kit.js";
import {coinShort} from "../labels.js";
import {usdt, usdKo, mmss, clockKst, kstMidnight, TF_MS, TF_SHORT} from "./terminal-kit.js";

const FUND_HOT = 0.0005;                    // 5 times the usual 0.01 %: the caution colour, nothing below it
const GROUP_KO = Object.fromEntries(POS_GROUPS.map((g) => [g.id, g.id === "all" ? "190계좌" : g.ko]));

/** topBar(ctx, st) -> {el, setCoin(), onLive(), onPositions(doc), onLeague(), onFills(rows), tick()} */
export function topBar(ctx, st) {
  const sym = h("b", {class: "tm-sym"}), perp = h("span", {class: "tm-perp"}, "무기한 · 모의");
  const px = h("b", {class: "tm-px num"}, "—"), chg = h("span", {class: "tm-chg num"}, "");
  const stat = (k, cls, title) => { const v = h("b", {class: "num"}, "—"); const kEl = h("span", null, k); return {v, k: kEl, el: h("div", {class: ["tm-st", cls || ""], title}, kEl, v)}; };
  const vol = stat("24시간 거래대금", "x-vol"), mark = stat("마크", "x-mark", "마크 가격: 엔진이 강제청산을 이 가격으로 봅니다 · 미실현 손익도 이 가격 기준");
  const fund = stat("펀딩 / 다음까지", "x-fund"), oi = stat("미결제약정", "x-oi", "바이낸스 이 코인 미결제약정 (코인 수 × 마크, 시장 전체 · 우리 봇 아님)");
  const range = stat("24시간 범위", "x-rng");
  // our positions on this coin, in the 묶음 the table below shows (후보 by default), with the 묶음 on screen: the coin
  // strip, the chart's chips and 이 코인 포지션 count the same positions
  const ours = stat("우리 포지션", "x-ours");
  const feed = h("span", {class: "tm-feedst"}, "시세 확인 중");
  const barK = h("span", null, "봉 마감까지"), barV = h("b", {class: "num"}, "—");
  const barBox = h("div", {class: "tm-st x-bar", title: "차트의 지금 봉이 닫히기까지 (한국 시각)"}, barK, barV);
  const dot = h("i", {class: "tm-live", "aria-hidden": "true"});
  const clock = h("b", {class: "tm-clock num"}, "—");
  const clockBox = h("div", {class: "tm-clockbox", title: "한국 시각 (대시보드 서버 시계 기준)"}, dot, clock, h("small", null, "KST"));
  const row = h("div", {class: "tm-row"},
    h("div", {class: "tm-id"}, sym, perp),
    h("div", {class: "tm-pxbox"}, px, chg),
    h("div", {class: "tm-stats"}, vol.el, mark.el, fund.el, oi.el, range.el, ours.el),
    h("i", {class: "tm-vsep", "aria-hidden": "true"}), feed,
    h("span", {class: "grow"}), barBox, clockBox);

  // ---- the band "후보 리그 지금" (each chip a link; a number that is not known is "—", never 0)
  const chip = (key, href, title) => h("a", {class: ["tm-bc", `c-${key}`], href, title});
  const cStatus = chip("status", "#/status", "엔진 상태 (누르면 서버 상태)");
  const cDay = chip("day", "#/check", "10/01부터 한국 날짜로 며칠째 · 다음 점검까지 (누르면 점검 진행)");
  const cOpen = chip("open", "#/positions", "지금 열린 포지션: 후보 리그 190계좌 전체 (묶음 고르기와 상관없이 · 누르면 포지션 화면)");
  const cUpnl = chip("upnl", "#/positions", "후보 계좌들의 미실현 손익 합계 (마크 가격, 나갈 때 수수료 전 · 딥시크 금액 숨김이면 뺌)");
  const cToday = chip("today", "#/fills", "오늘(한국 날짜) 닫힌 후보 계좌 거래 (누르면 체결 기록)");
  const fresh = freshLine(null, {cls: "tm-fresh"});
  const band = h("div", {class: "tm-band", role: "group", "aria-label": "후보 리그 한 줄 요약"},
    h("span", {class: "tm-bl"}, "후보 리그 지금"), cStatus, cDay, cOpen, cUpnl, cToday, h("span", {class: "grow"}), fresh);
  const banner = h("div", {class: "tm-banner"});
  const el = h("header", {class: "tm-top", "aria-label": "시세와 후보 리그 요약"}, row, band, banner);

  let doc = null, fills = [];
  function paintCoin() {
    const r = liveRow(st.coin);
    sym.textContent = `${coinShort(st.coin)}USDT`;
    const ok = r && r.ok !== false && r.price != null;
    if (!ok) {
      px.textContent = "—"; px.className = "tm-px num"; chg.textContent = "";
      for (const x of [vol, mark, fund, oi, range]) x.v.textContent = "—";
      el.dataset.noprice = "1";
      return;
    }
    delete el.dataset.noprice;
    tickPrice(px, Number(r.price), fmt.price(r.price), st.coin);
    px.classList.toggle("up", Number(r.change_pct) > 0); px.classList.toggle("down", Number(r.change_pct) < 0);
    chg.textContent = r.change_pct == null ? "" : fmt.pct(r.change_pct, true, 2);
    chg.className = "tm-chg num " + fmt.tone(r.change_pct);
    put(vol.v, r.quote_volume != null ? [usdKo(r.quote_volume), h("span", {class: "tm-unit"}, " USDT")] : "—");
    mark.v.textContent = fmt.price(r.mark);
    const fr = Number(r.funding_rate), hot = Number.isFinite(fr) && Math.abs(fr) >= FUND_HOT;
    put(fund.k, "펀딩", Number.isFinite(fr) && fr !== 0 ? h("span", {class: "tm-fwho"}, fr > 0 ? " (롱이 냄)" : " (숏이 냄)") : null, " / 다음까지");
    put(fund.v, h("span", {class: hot ? "warn-t" : ""}, Number.isFinite(fr) ? `${fmt.num(fr * 100, 4, true)}%` : "—"), " ",
      h("span", {class: "tm-fcd"}, r.next_funding_ms ? mmss(r.next_funding_ms - serverNow()) : ""));
    fund.el.title = Number.isFinite(fr) ? `펀딩 ${fmt.num(fr * 100, 4, true)}%: ${fr > 0 ? "롱이 숏에게" : fr < 0 ? "숏이 롱에게" : "아무도 안"} 냅니다 (8시간마다) · 보통 +0.0100% · 0.05% 이상이면 주의 색` : "펀딩 모름";
    const oiUsd = r.open_interest != null && r.mark != null ? Number(r.open_interest) * Number(r.mark) : null;
    put(oi.v, oiUsd != null ? [usdKo(oiUsd), h("span", {class: "tm-unit"}, " USDT")] : "—");
    const lo = Number(r.low), hi = Number(r.high), p = Number(r.price);
    if (Number.isFinite(lo) && Number.isFinite(hi) && hi > lo) {
      const at = Math.max(0, Math.min(1, (p - lo) / (hi - lo)));
      put(range.v, h("span", {class: "tm-rng"}, h("span", {class: "num"}, fmt.price(lo)),
        h("i", {class: "tm-rngbar", "aria-hidden": "true"}, h("i", {style: {left: `${(at * 100).toFixed(1)}%`}})), h("span", {class: "num"}, fmt.price(hi))));
      range.el.title = `24시간 저가 ${fmt.price(lo)} · 고가 ${fmt.price(hi)} · 지금 ${fmt.price(p)} (범위의 ${Math.round(at * 100)}% 자리)`;
    } else range.v.textContent = "—";
  }
  function paintFeed() {
    const ls = liveState();
    feed.textContent = ls.state === "ok" ? "실시간 시세" : ls.state === "fake" ? "시험용 가짜 시세" : ls.state === "stale" ? "시세 지난 값" :
      ls.state === "off" ? "시세 꺼짐" : ls.state === "unavailable" ? "시세 끊김" : "시세 기다리는 중";
    feed.className = `tm-feedst s-${ls.state}`;
    feed.title = `${ls.ko}${ls.age_s != null ? ` · ${Math.round(ls.age_s)}초 전 값` : ""} (대시보드 서버가 5초마다 바이낸스 공개 시세를 받습니다)`;
    dot.dataset.s = ls.state === "ok" || ls.state === "fake" ? "live" : "down";
  }
  function paintOurs() {
    const g = GROUP_KO[st.grp] || "후보";
    ours.k.textContent = `우리 포지션 · ${g}`;
    ours.el.title = `${st.grp === "all" ? "후보 리그 190계좌 전체" : `${g} 묶음`}가 이 코인에 연 포지션 (아래 표의 묶음 고르기를 따름 · 딥시크 금액 숨김이어도 개수는 셉니다)`;
    if (!doc || doc.status) { ours.v.textContent = "—"; return; }
    const ps = (doc.positions || []).filter((p) => p.coin === st.coin && inGroup(p, st.grp));
    const L = ps.filter((p) => Number(p.side) > 0).length, S = ps.length - L;
    const k = crowd({long: L, short: S});
    put(ours.v, L + S ? [h("span", {class: "up"}, `롱 ${fmt.int(L)}`), " · ", h("span", {class: "down"}, `숏 ${fmt.int(S)}`),
      k.on ? h("i", {class: "tm-crowd", title: `한 방향 몰림: ${k.n}개 중 ${Math.round(k.share * 100)}%가 ${k.side > 0 ? "롱" : "숏"}`}) : null] : h("span", {class: "muted"}, "없음"));
  }
  function paintBand() {
    const d = LK.league();
    const H = LK.health(d);
    put(cStatus, h("i", {class: ["tm-hdot", `l-${H.lv}`], "aria-hidden": "true"}), H.lv === "ok" ? "엔진 정상" : H.lv === "warn" ? "엔진 확인" : "엔진 문제");
    cStatus.title = `엔진 상태: ${H.ko} (누르면 서버 상태)`;
    const now = serverNow();
    const cps = (d && d.watch && d.watch.checkpoints) || [];
    const next = cps.find((c) => c.ms > now);
    if (d && d.start_ms) {
      put(cDay, h("b", null, `D+${LK.dPlus(d, now)}`), next ? ` · ${String(next.ko || next.id).replace(" 점검", "")} ${fmt.mmdd(next.ms).replace(/^0/, "").replace("/0", "/")}까지 ${Math.ceil((next.ms - now) / 86400000)}일` : " · 점검 끝");
    } else put(cDay, h("b", null, "D+—"));
    if (!doc || doc.status) { put(cOpen, "열린 —"); put(cUpnl, "후보 미실현 —"); }
    else {
      const c = doc.counts || {};
      put(cOpen, "190계좌 열린 ", h("b", {class: "num"}, fmt.int(c.open || 0)), " · ", h("span", {class: "up"}, `롱 ${fmt.int(c.long || 0)}`), " · ",
        h("span", {class: "down"}, `숏 ${fmt.int(c.short || 0)}`));
      const cand = (doc.positions || []).filter((p) => inGroup(p, "cand"));
      if (!liveOk(doc)) put(cUpnl, "후보 미실현 ", h("span", {class: "warn-t"}, doc.catching_up ? "따라잡는 중" : doc.old ? "엔진 멈춤" : `감춤 (${waitKo(doc)})`));
      else {
        const s = sums(cand);
        put(cUpnl, "후보 미실현 ", s.priced ? h("b", {class: ["num", fmt.tone(s.pnl, usdt(s.pnl))]}, `${usdt(s.pnl)} USDT`) : h("span", {class: "muted"}, cand.length ? "시세 없음" : "포지션 없음"),
          s.priced && s.unpriced ? h("small", {class: "warn-t"}, ` · 시세 없는 ${fmt.int(s.unpriced)}개 뺌`) : null,
          s.hidden ? h("small", {class: "muted"}, ` · 딥시크 ${fmt.int(s.hidden)}개 뺌`) : null);
      }
    }
    // today's closed 후보 trades (counts are fine for every account; wins from the sign or the server's "win")
    const ix = LK.index();
    const t0 = kstMidnight(now);
    let n = 0, w = 0, known = !!(fills && fills.length);
    for (const f of fills || []) {
      if (!(f.exit_time >= t0)) continue;
      const a = ix.byId[f.account];
      if (!a || a.role !== "cand") continue;
      n += 1;
      if (f.pnl != null ? f.pnl > 0 : !!f.win) w += 1;
    }
    put(cToday, "오늘 후보 거래 ", known || n ? h("b", {class: "num"}, `${fmt.int(n)}건`) : "—",
      n ? h("span", {class: "muted"}, ` · ${fmt.int(w)}승 ${fmt.int(n - w)}패`) : null);
    fresh.update(doc);
  }
  function paintBanner() { put(banner, staleBanner(doc)); }

  return {
    el,
    setCoin() { px.dataset.pk = ""; paintCoin(); paintOurs(); },
    onLive() { paintCoin(); paintFeed(); paintBand(); },
    onPositions(d) { doc = d; paintOurs(); paintBand(); paintBanner(); },
    setGroup() { paintOurs(); },
    onLeague() { paintBand(); },
    onFills(rows) { fills = rows || []; paintBand(); },
    tick() {
      const now = serverNow();
      clock.textContent = clockKst(now);
      const tf = TF_MS[st.tf] ? st.tf : "15m";
      barK.textContent = `${TF_SHORT[tf]} 봉 마감까지`;
      barV.textContent = mmss(TF_MS[tf] - (now % TF_MS[tf]));
      const r = liveRow(st.coin);
      const cd = fund.v.querySelector(".tm-fcd");
      if (cd && r && r.next_funding_ms) cd.textContent = mmss(r.next_funding_ms - now);
    },
    /** for tests: the band's text */
    bandText: () => band.textContent,
  };
}

