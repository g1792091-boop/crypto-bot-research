// 실거래 › 포지션 (#/pos on the 실거래 site; owners 10/19: "규칙봇 대시보드 보면 포지션 대시보드 화면 있잖아 그것도 …
// 포지션 진입하고 최대 %까지 갔는지 최대 -%까지 갔는지도 보였으면 좋겠고 진입가 익절가 손절가도 보였으면 좋겠어!!"). The
// rule bot's 포지션 card (screens/positions-kit.js posCard: the Binance-style card) for the live setup, one card per
// account: 페이퍼(연습) COMBO@mix, 바이비트, MEXC (real money), 동전 쌍둥이 COMBOFLIP@mix (참고).
//   head      coin, 무기한, 롱/숏, 격리 배수, the setting's group (A, or B = 추격 진입 막기), the strategy, its timeframe
//   money     미실현 손익 (the mark price now, before the exit fee) and 순ROE (the ladder's definition: after fees and slippage
//             of both sides and the funding paid), rolling with the mark (/api/ticker, the store's 5 s poll)
//   prices    진입가 · 지금 가격 · 손절가 (the stop before the first lock: the recorded first stop, the config's net-ROE stop
//             beside it) or the lock line after it · 익절가 = the next ladder step (the price where the next lock arms and the
//             lock it sets) · 청산가 (the paper's; an executor does not record one) · 증거금 · 크기
//   meter     손절 → 진입 → 지금 → 익절 on one line (the share of the way, distances in %)
//   최대 +% / 최대 −%   since the entry, net ROE and the price move, with where they come from (the paper engine's own
//             record, else the rule bot's 1m Binance bars: "바이낸스 1분봉 기준")
//   ladder    every step: the net ROE that arms it → the lock, its price; locked steps lit, the next one outlined
//   secured   the lock as net ROE and money; 빠른 손절 (the strategy's own reverse signal before the first lock, then off)
//   gap       the paper-vs-live entry gap of this position (price, seconds)
//   거래소 기준 (owners 10/20 "거래소 기준으로 익절해야지"): an executor that runs the ladder on its own position
//             (ladder_from "exchange") shows ITS lock, ITS next step and ITS ladder (its fill, its exchange's prices and
//             costs), its own best price, and that it stays open after the paper's price exit
//   진입 근거 (owners 10/20 "왜 진입했는지 어떤 근거로 진입했는지"): the button under the strategy line opens the entry's
//             reasons (livebots-why.js; an executor's: the paper entry it followed)
//   친구봇    (owners 10-27 "친구봇 대시보드 화면에 실시간 포지션도 안뜨고"): WOO X Pro 2's own 30-minute bot (``self``: it trades
//             by itself, no paper behind it): its own position, stop, ladder and net ROE at its own fee round trip
// Data: GET /api/v4/livebots/positions (dash/more/livepos.py; asked every 10 s, the server caches 5 s). HONESTY: no file =
// 수집 전, unreadable = 못 읽음 + why, a value the records do not have is '—' with the reason; no order buttons.
import {h, put, ui, fmt, motion, serverNow} from "../core/pb.js";
import {acctTag, sourceState, execsKo, isPaperId} from "./livebots-kit.js";
import {netRoe, unrealized, distTo} from "./livebots-calc.js";
import {whyBox} from "./livebots-why.js";

export const POS_API = "/api/v4/livebots/positions";
const REFRESH_MS = 10 * 1000;
const NAME = {paper: "페이퍼(연습)", bybit: "바이비트", mexc: "WOO X Pro", deepcoin: "딥코인", wooxpro2: "WOO X Pro 2",
  toobit: "투비트", flip: "동전 쌍둥이"};

/** A card's mark-dependent numbers (pure; node tests): unrealized money, net ROE, distances, the meter's places. */
export function atMark(p, mark) {
  if (!p || !(Number(mark) > 0)) return {mark: null, u: null, roe: null, dStop: null, dTp: null, dLiq: null, meter: null};
  const u = unrealized(p, mark);
  const roe = netRoe(p, mark);
  const tp = p.next && p.next.price;
  const stop = p.stop;
  const meter = meterOf(p.side, stop, p.entry, tp, mark);
  return {mark, u, roe, dStop: distTo(mark, stop), dTp: distTo(mark, tp), dLiq: distTo(mark, p.liq), meter};
}

/** Places (0-1) of the entry and the mark on the line from the stop (0) to the next ladder price (1); null without both
 *  ends. Beyond either end the mark sits at it (clamped) and `out` says which side. */
export function meterOf(side, stop, entry, tp, mark) {
  if (!(stop > 0) || !(tp > 0) || !side) return null;
  const span = side * (tp - stop);
  if (!(span > 0)) return null;
  const at = (px) => (px > 0 ? side * (px - stop) / span : null);
  const m = at(mark), e = at(entry);
  return {entry: e == null ? null : Math.max(0, Math.min(1, e)), mark: m == null ? null : Math.max(0, Math.min(1, m)),
    out: m == null ? null : m < 0 ? "stop" : m > 1 ? "tp" : null};
}

const pctOr = (x, dec = 1) => (x == null ? "—" : fmt.pct(x, dec));
const ago = (ms) => fmt.ago(ms, serverNow());

/** The source of 최대 +% / 최대 −% in words (or its missing / unreadable state). */
function excursionBox(ex) {
  if (!ex || ex.state !== "ok") {
    const why = (ex && ex.reason_ko) || "아직 계산하지 못했어요";
    const tag = !ex || ex.state === "missing" ? ui.notYet("수집 전", why) : ex.state === "error" ? ui.pill("못 읽음", "bad", ex.reason || why)
      : ui.pill("1분봉 없음", "thin", why);
    return h("div", {class: "lbp-ex none"}, h("span", {class: "lbp-exk"}, "최대 +% · 최대 −%"), tag, h("small", {class: "muted"}, ` ${why}`));
  }
  const bar = (v, cls) => h("i", {class: ["lbp-exbar", cls], style: {width: `${Math.round(Math.min(1, Math.abs(Number(v) || 0) / 0.5) * 100)}%`}});
  return h("div", {class: "lbp-ex"},
    h("div", {class: "lbp-exrow"}, h("span", {class: "lbp-exk"}, "최대 +%"), h("b", {class: ["num", fmt.tone(ex.mfe)]}, pctOr(ex.mfe)),
      h("span", {class: "lbp-extrack"}, bar(ex.mfe, "up")), h("small", {class: "num muted"}, `가격 ${pctOr(ex.mfe_move, 2)} · ${fmt.price(ex.mfe_px)}`)),
    h("div", {class: "lbp-exrow"}, h("span", {class: "lbp-exk"}, "최대 −%"), h("b", {class: ["num", fmt.tone(ex.mae)]}, pctOr(ex.mae)),
      h("span", {class: "lbp-extrack"}, bar(ex.mae, "down")), h("small", {class: "num muted"}, `가격 ${pctOr(ex.mae_move, 2)} · ${fmt.price(ex.mae_px)}`)),
    h("p", {class: "note lbp-exsrc"}, `진입 뒤 순ROE 기준 (수수료·슬리피지 왕복 포함) · ${ex.src === "engine" ? "페이퍼 엔진 기록" : "바이낸스 1분봉 기준"}`,
      ex.bars ? ` · 1분봉 ${fmt.int(ex.bars)}개` : "", " ", ui.infoTip(ex.src_ko || "", "최대 +% · 최대 −%의 출처")));
}

/** The ladder as small steps: '11% → 10%' and the price; locked lit, the next one outlined. */
function ladderBox(p) {
  const steps = p.ladder || [];
  if (!steps.length) return h("p", {class: "note"}, "계단 잠금: 설정에 계단이 없어요");
  const from = p.ladder_from === "paper" ? " · 가격은 페이퍼 기준 (이 실행기 손절은 페이퍼 잠금을 따라 진입가 비율로 옮겨요)"
    : p.ladder_from === "own" ? " · 따라가는 페이퍼 포지션이 없어 이 실행기 진입가로 그린 계단"
    : p.ladder_from === "exchange" ? ` · 거래소 기준: 이 실행기 체결가 · 이 거래소 가격 · 이 거래소 수수료로 잠가요 (페이퍼 잠금은 안 따라요)${p.basis === "gross" ? " · 계단 숫자는 화면 ROE (수수료 전)" : ""}`
    : p.ladder_from === "bot" ? ` · ${p.bot_ko || "친구봇"} 기준: 자기 체결가 · 바이낸스 1분봉 · ${p.bot_ko || "친구봇"} 수수료로 잠가요${p.every_s ? ` (${fmt.int(p.every_s)}초마다)` : ""}` : "";
  return h("div", {class: "lbp-lad"},
    h("div", {class: "lbp-ladk"}, h("b", null, "계단 익절"), h("small", {class: "muted"}, `순ROE가 닿으면 → 그 잠금으로 손절을 올려요${from}`)),
    h("ol", {class: "lbp-steps"}, steps.map((s) => h("li", {class: ["lbp-step", s.state], title: `${s.n}단: 최고 순ROE ${fmt.pct(s.at, 0, false)} (${fmt.price(s.price)})에 닿으면 순ROE ${fmt.pct(s.lock, 0, false)} 잠금 (${fmt.price(s.lock_price)})`},
      h("span", {class: "lbp-sn"}, `${s.n}단`), h("b", {class: "num"}, `${fmt.pct(s.at, 0, false)}→${fmt.pct(s.lock, 0, false)}`),
      h("small", {class: "num"}, fmt.price(s.price)), s.state === "done" ? h("i", {class: "lbp-sok", "aria-label": "잠금됨"}, "잠금") : s.state === "next" ? h("i", {class: "lbp-sok"}, "다음") : null))));
}

/** One account's card; .update(mark) rolls its mark-dependent numbers. ``o.api`` (the screen's ctx.api): the 진입 근거
 *  button asks its answer with it (without one the card has no button). */
export function posCard(c, o = {}) {
  const name = (c.label_ko || "").split(" (")[0] || NAME[c.id] || c.name_ko || c.id;     // two paper bots: "페이퍼 −35%"
  const tag = c.id === "flip" ? h("span", {class: "lb-acct lb-a-flip", title: c.note_ko || ""}, h("i", {class: "lb-sw", "aria-hidden": "true"}), name)
    : c.self ? h("span", {class: `lb-acct lb-a-${c.tag || "wooxpro2"}`, title: c.tag === "bybit" ? "바이비트 계정의 바이비트 봇 (실거래 · 진짜 돈 · 스스로 매매)"
      : c.tag === "mexc" ? "WOO X Pro 계정의 레인지 봇 (실거래 · 진짜 돈 · 스스로 매매)"         // owners 10-31 night
        : "WOO X Pro 두 번째 계정의 친구봇 (실거래 · 진짜 돈 · 스스로 매매)"}, h("i", {class: "lb-sw", "aria-hidden": "true"}), name)
    : acctTag(c.id);
  const kindPill = c.kind === "live" ? ui.pill("진짜 돈", "warn") : c.id === "flip" ? ui.pill("", "ref") : ui.pill("모의", "thin");     // ("ref" prints 참고 itself)
  // owners 10/20 "거래소 기준으로 익절해야지": an executor that locks on its own position says so on its card
  const basisPill = c.position && c.position.ladder_from === "exchange" ? ui.pill(c.position.basis_ko || "거래소 기준", "accent", c.position.ladder_ko || "") : null;
  // two paper bots: the executor's card names the paper bot it follows (its ladder and stop are that bot's)
  const follows = c.kind === "live" && c.follows_ko ? h("small", {class: "muted"}, `따라감 · ${c.follows_ko}`) : null;
  if (c.state !== "ok") {
    const el = ui.card({cls: "lbp-card none"}, h("div", {class: "lbp-top"}, tag, kindPill), sourceState(c, c.kind === "live" ? `${name} 실행기 기록` : "페이퍼 DB"));
    el.update = () => {};
    return el;
  }
  const p = c.position;
  if (!p) {
    const el = ui.card({cls: "lbp-card none"}, h("div", {class: "lbp-top"}, tag, kindPill, follows, h("span", {class: "grow"}),
      c.halted ? ui.pill(`멈춤${c.halt_reason ? `: ${c.halt_reason}` : ""}`, "bad") : null),
    h("p", {class: "lbp-flat"}, "포지션 없음"),
    c.kind === "live" && !c.halted ? h("p", {class: "note"}, c.self ? `${c.tf_ko || "30분"}봉 신호를 기다려요 · 스스로 매매 (한 번에 포지션 하나)${c.stale ? " (기록 오래됨)" : ""}`
      : `따라가는 중 · 다음 페이퍼 진입을 기다려요${c.stale ? " (기록 오래됨)" : ""}`) : null,
    h("p", {class: "note"}, c.wallet != null ? `잔고 ${c.kind === "live" ? fmt.usd(c.wallet) : `${fmt.money(c.wallet)} USDT`} · ` : "",
      c.as_of_ms ? `마지막 기록 ${ago(c.as_of_ms)}` : "", c.stale ? " · 기록 멈춤" : ""),
    c.note_ko ? h("p", {class: "note"}, c.note_ko) : null);
    el.update = () => {};
    return el;
  }
  const live = c.kind === "live";
  const st = p.setting;
  // the 추세판단 봇's members by role (눌림 · 자리 · 돌파 · 횡보); the A/B groups were the bot before it's
  const grp = st && st.role ? ui.pill(st.role, "accent", "추세판단 봇의 매매법 역할")
    : st ? (st.group === "B" ? ui.pill("B그룹 · 추격 막기", "accent", st.no_chase_ko || "추격 진입 막기 매매법")
      : st.group === "A" ? ui.pill("A그룹", "thin", "추격 진입 막기 없는 매매법") : null) : null;     // (no group: the VWAP bot)
  const stratLine = p.strategy_id
    ? `${fmt.stratKo(p.strategy_id)} · ${fmt.tfKo(p.timeframe)}봉${st ? ` · ${st.order}번 설정` : p.member_order ? ` · ${p.member_order}번 설정` : ""}`
    : p.rule_ko ? p.rule_ko : live ? "매매법 모름 (따라가는 페이퍼 포지션을 못 찾았어요)" : "매매법 기록 없음";
  // money: unrealized (before the exit fee) and net ROE, rolling with the mark
  const uEl = h("b", {class: "led-num num"}, "—"), rEl = h("b", {class: "led-sm num"}, "—");
  const markEl = h("span", {class: "num"}, "—");
  const dStopEl = h("small", {class: "num muted"}), dTpEl = h("small", {class: "num muted"}), dLiqEl = h("small", {class: "num muted"});
  const nx = p.next;
  const own = p.ladder_from === "exchange";
  const stopK = p.locked ? (own && p.lock_roe != null ? `잠금선 (거래소 기준 ${p.basis === "gross" ? "화면 " : ""}+${fmt.pct(p.lock_roe, 0, false)} 잠금)` : "잠금선 (손절이 올라간 자리)") : "손절가";
  const stopV = h("span", null, h("b", {class: ["num", p.locked ? "up" : "down"]}, fmt.price(p.stop)), " ", dStopEl,
    p.locked && p.stop_initial ? h("small", {class: "muted"}, ` · 처음 손절 ${fmt.price(p.stop_initial)}`) : null,
    !p.locked && p.stop50 && p.stop_rule_cfg ? h("small", {class: "muted", title: "설정의 손절: 수수료·슬리피지 포함 순ROE"},
      ` · 설정 −${fmt.pct(p.stop_rule_cfg.roe, 0, false)}${p.stop_rule_cfg.net ? " 순ROE" : ""} 자리 ${fmt.price(p.stop50)}`) : null);
  // the exchange screen's ROE at that price (leverage x the move, before fees: what the app shows; owners 10-27)
  const screenAt = nx && nx.screen_at != null ? ` · 거래소 화면 ROE 약 +${fmt.pct(nx.screen_at, 1, false)}` : "";
  const tpV = nx && nx.fixed && nx.price ? h("span", null, h("b", {class: "num up"}, fmt.price(nx.price)), " ", dTpEl,
    h("small", {class: "muted"}, ` · 순ROE +${fmt.pct(nx.at, 0, false)} 고정 익절${screenAt} (닿으면 시장가로 전부 닫음 · 계단 없음${nx.from === "exchange" ? " · 거래소 마지막 체결가 기준" : ""})`))
    : nx && nx.price ? h("span", null, h("b", {class: "num up"}, fmt.price(nx.price)), " ", dTpEl,
    h("small", {class: "muted"}, ` · 순ROE ${fmt.pct(nx.at, 0, false)}에 닿으면 ${fmt.pct(nx.lock, 0, false)} 잠금 (손절 → ${fmt.price(nx.lock_price)})${nx.from === "paper" && live ? " · 페이퍼 기준" : nx.from === "exchange" ? " · 거래소 기준 (자기 체결가)" : ""}${screenAt}`))
    : ui.notYet("—", "다음 잠금 자리를 계산하지 못했어요 (설정에 계단이 없거나 포지션 기록이 모자라요)");
  const liqV = p.liq ? h("span", null, h("b", {class: "num down"}, fmt.price(p.liq)), " ", dLiqEl) : h("span", {class: "muted"}, p.liq_ko || "—");
  const held = p.entry_time ? fmt.dur((serverNow() - p.entry_time) / 1000) : null;
  const pairs = [
    ["진입가", h("b", {class: "num"}, fmt.price(p.entry))], ["지금 가격 (마크)", markEl],
    [stopK, stopV], [nx && nx.fixed ? "익절가 (고정 익절)" : "익절가 (다음 잠금 자리)", tpV], ["청산가", liqV],
    ["증거금", p.margin == null ? null : live ? fmt.usd(p.margin) : `${fmt.money(p.margin)} USDT`],
    [`크기 (${fmt.coin(p.symbol)})`, p.qty == null ? null : String(Number(p.qty))],
    ["진입", p.entry_time ? `${fmt.kst(p.entry_time)}${held ? ` · ${held} 보유` : ""}` : null],
  ];
  // the meter: 손절 → 진입 → 지금 → 익절
  const mEntry = h("i", {class: "lbp-mt entry", "aria-hidden": "true"}), mNow = h("i", {class: "lbp-mt now", "aria-hidden": "true"});
  const meterNote = h("small", {class: "muted lbp-mnote"});
  const meter = h("div", {class: "lbp-meter"},
    h("div", {class: "lbp-mk"}, h("span", {class: "down"}, p.locked ? "잠금선" : "손절"), h("span", null, "진입 ▸ 지금"), h("span", {class: "up"}, nx && nx.fixed ? "익절(고정)" : "익절(다음 잠금)")),
    h("div", {class: "lbp-mtrack"}, mEntry, mNow), meterNote);
  const secured = p.secured ? h("p", {class: "lbp-sec"}, h("b", {class: "up"}, "확보한 수익 "),
    h("b", {class: "num up"}, `순ROE ${pctOr(p.secured.roe)}`), p.secured.usd != null ? h("span", {class: "num"}, ` · ${live ? fmt.usd(p.secured.usd) : `${fmt.money(p.secured.usd, true)} USDT`}`) : null,
    h("small", {class: "muted"}, own ? " (지금 손절선에서 닫히면 · 거래소 비용 기준)" : c.self ? ` (지금 손절선에서 닫히면 · ${c.short_ko || "친구봇"} 비용 기준)`
      : live ? " (지금 손절선에서 닫히면 · 페이퍼 비용 가정)" : " (잠금선에서 닫혀도 남는 순이익)"))
    : h("p", {class: "lbp-sec"}, h("b", null, "확보한 수익 "), h("span", {class: "muted"}, "아직 없음 · 첫 잠금 전"),
      nx && nx.fixed && nx.price ? h("small", {class: "muted"}, ` (계단 없음 · 순ROE +${fmt.pct(nx.at, 0, false)} · ${fmt.price(nx.price)}에 닿으면 전부 익절)`)
        : nx && nx.price ? h("small", {class: "muted"}, ` (순ROE ${fmt.pct(nx.at, 0, false)} · ${fmt.price(nx.price)}에 닿으면 ${fmt.pct(nx.lock, 0, false)} 잠금)`) : null);
  const fast = p.fast ? h("p", {class: ["lbp-fast", p.fast.state]}, h("b", null, "빠른 손절 "), p.fast.ko) : null;
  // 거래소 기준: its own best price so far (its own exchange's 1m candles) and, after the paper's price exit, that it stays
  const ownBest = own && p.own_best && p.own_best.price ? h("p", {class: "note"}, `거래소 기준 최고 ${p.basis === "gross" ? "화면 ROE" : "순ROE"} ${pctOr(p.own_best.roe)} (${fmt.price(p.own_best.price)}, `,
    p.own_best.src === "last" ? "1분봉을 못 읽어 지금 가격" : "이 거래소 1분봉", ")") : null;
  const staying = own && p.staying ? h("p", {class: "note"}, p.staying.ko) : null;
  const gaps = live ? [] : (p.execs || []).filter((x) => x.state === "following");
  const gapEl = c.self ? (p.stop_id_missing ? h("p", {class: "note"}, `상태 파일에 손절 주문 번호가 없어요 · ${c.app_ko || "WOO X Pro"} 앱에서 손절을 확인하세요`) : null)
    : live
    ? h("p", {class: "note lbp-gap"}, p.gap ? ["페이퍼 진입 ", h("b", {class: "num"}, fmt.price(p.gap.paper_entry)), " → 이 실행기 ", h("b", {class: "num"}, fmt.price(p.gap.live_entry)),
      " · ", h("b", {class: ["num", fmt.tone(p.gap.slip)]}, fmt.pct(p.gap.slip, 3)), p.gap.slip >= 0 ? " (페이퍼보다 유리)" : " (페이퍼보다 불리)",
      p.gap.delay_ms != null ? ` · ${fmt.dur(p.gap.delay_ms / 1000)} 뒤 체결` : ""] : "페이퍼와 진입 차이: 따라가는 페이퍼 포지션이 없어요")
    : isPaperId(c.id) ? h("p", {class: "note lbp-gap"}, gaps.length ? gaps.map((g, i) => [i ? " · " : "", `${g.name_ko} `, h("b", {class: "num"}, fmt.price(g.live_entry)),
      " (", h("span", {class: ["num", fmt.tone(g.slip)]}, fmt.pct(g.slip, 3)), g.delay_ms != null ? `, ${fmt.dur(g.delay_ms / 1000)} 뒤` : "", ")"])
      : (p.execs || []).length && (p.execs || []).every((x) => x.why_ko) ? "실거래 실행기는 이 포지션을 따라가지 않았어요 (이 손익은 페이퍼에만 남아요)"
        : "실행기가 따라 들어간 기록이 아직 없어요 (따라가는 중이 아니거나 아직 진입 확인 중)",
    (p.execs || []).filter((x) => x.state !== "following").map((x) => ` · ${x.name_ko}: ${x.state === "unknown" ? `기록 못 읽음${x.reason_ko ? ` (${x.reason_ko})` : ""}`
      : x.state === "other" ? "다른 페이퍼를 따라가요" : x.why_ko ? `안 따라감 · ${x.why_ko}${x.why_text ? ` (실행기 기록: ${x.why_text})` : ""}` : "이 포지션 없음"}`))
      : null;
  const capText = c.self ? `${c.short_ko || "친구봇"} 기록 · 손익은 마크 가격으로 어림 (나갈 때 수수료 전)` : live ? ui.ASSUME_LIVE_KO : ui.ASSUME_OPEN_KO;
  const el = ui.card({cls: `lbp-card ${live ? "live" : c.id}`},
    h("div", {class: "lbp-top"}, tag, kindPill, basisPill, follows, h("span", {class: "lbp-sym"}, `${fmt.coin(p.symbol)}USDT`), h("span", {class: "muted lbp-perp"}, "무기한"),
      ui.sideTag(p.side), h("span", {class: "muted"}, `격리 ${fmt.lev(p.leverage)}`), grp, p.status === "entering" ? ui.pill("진입 확인 중", "warn") : null),
    h("p", {class: "lbp-strat"}, stratLine, st && st.no_chase ? h("small", {class: "muted"}, " · 추격 진입 막기") : null),
    p.inherited ? h("p", {class: "lbp-inh"}, p.inherited_ko || "전환 전 포지션",
      h("small", null, " · 새 봇이 손절 · 계단 익절 · 추세 뒤집힘 청산(첫 잠금 전)으로 닫아요 · 닫힐 때까지 새 진입 없음 (한 번에 하나)")) : null,
    whyBox(o.api, p.why, {label: live ? "진입 근거 보기 (따라간 페이퍼 진입)" : "진입 근거 보기"}),
    h("div", {class: "pnl lbp-led"},
      h("div", null, h("span", {class: "k"}, "미실현 손익", live ? " ($)" : " (USDT)", " ", ui.infoTip(`${capText} · 마크 = 바이낸스 가격 (거래소 가격과 조금 다를 수 있어요)`, "미실현 손익")), uEl),
      h("div", {class: "r"}, h("span", {class: "k"}, "순ROE", " ", ui.infoTip(live ? `${p.cost_ko || "페이퍼 비용 가정"} · 레버리지 x (가격 변화 − 왕복 비용)` : "레버리지 x (가격 변화 − 왕복 수수료·슬리피지 − 낸 펀딩) · 계단 잠금과 같은 식", "순ROE")), rEl)),
    ui.kv(pairs), meter, excursionBox(p.excursion), ownBest, secured, ladderBox(p), fast, staying, gapEl,
    c.note_ko ? h("p", {class: "note"}, c.note_ko) : null);
  el.update = (mark) => {
    const m = atMark(p, mark);
    motion.countTo(uEl, m.u, {dec: 2, sign: true, tone: true});
    motion.countTo(rEl, m.roe, {format: "pct", dec: 1, tone: true});
    motion.tickPrice(markEl, m.mark, m.mark ? fmt.price(m.mark) : "—", p.symbol);
    const dist = (d) => (d == null ? "" : `(지금부터 ${fmt.pct(d, 2, false)})`);
    dStopEl.textContent = dist(m.dStop); dTpEl.textContent = dist(m.dTp); dLiqEl.textContent = dist(m.dLiq);
    if (m.meter) {
      meter.classList.remove("na");
      mEntry.style.left = `${((m.meter.entry ?? 0) * 100).toFixed(1)}%`;
      mNow.style.left = `${((m.meter.mark ?? 0) * 100).toFixed(1)}%`;
      meterNote.textContent = m.meter.out === "tp" ? "지금 가격이 다음 잠금 자리를 넘었어요 (다음 1분봉에 잠금이 올라가요)"
        : m.meter.out === "stop" ? "지금 가격이 손절선 밖이에요 (청산 처리 중일 수 있어요)" : `손절에서 익절 자리까지 ${fmt.pct(m.meter.mark, 0, false)} 왔어요`;
    } else {
      meter.classList.add("na");
      meterNote.textContent = m.mark ? "익절 자리나 손절선이 없어 그리지 못했어요" : "마크 가격을 기다리는 중";
    }
  };
  el.update(null);
  return el;
}

/** The fixed rules over the cards, from the config the bot runs (never typed in here). */
function rulesLine(r) {
  if (!r || r.state !== "ok") return h("p", {class: "note"}, "설정을 읽지 못해 규칙 줄을 그리지 못했어요");
  const parts = [r.name ? `${r.name}` : null,
    r.stop ? `손절 ${r.stop.net ? "순ROE " : "ROE "}−${fmt.pct(r.stop.roe, 0, false)} 고정${r.stop.net ? " (수수료·슬리피지 포함)" : ""}` : null,
    r.ladder_ko ? `계단 익절: ${r.ladder_ko}` : null,
    r.early_exit ? `빠른 손절: ${r.early_exit === "own" ? "같은 매매법" : "아무 매매법"} 반대 신호${r.early_exit_until_lock ? " (첫 잠금 전까지만)" : ""}` : "빠른 손절 없음",
    typeof r.margin === "number" ? `증거금 잔고의 ${fmt.pct(r.margin, 0, false)}` : null,
    r.leverage_btc ? `BTC ${fmt.lev(r.leverage_btc)} · 나머지 ${fmt.lev(r.leverage_alt)}` : null, "한 번에 포지션 하나",
    r.n_members ? `매매법 ${fmt.int(r.n_members)}개${!r.n_no_chase ? "" : r.trend ? (r.n_no_chase === r.n_members ? " (모두 추격 막기)" : ` (추격 막기 ${fmt.int(r.n_no_chase)}개)`)
      : ` (B그룹 추격 막기 ${fmt.int(r.n_no_chase)}개)`}` : null];
  return h("p", {class: "lbp-rules"}, parts.filter(Boolean).join(" · "));
}

/** posView(ctx, hub) -> {el, set()}: its own endpoint (every 10 s); the summary answer (hub) is not needed here. */
export function posView(ctx) {
  const st = {d: null, okAt: 0, sig: null, cards: []};
  const rules = h("div", {class: "lbp-head"});
  const stateSlot = h("div", {class: "lb-slot"});
  const grid = h("div", {class: "lbp-grid"}, motion.shimmer(2));
  const foot = h("div", {class: "lb-foot"}, ui.assumeLive(`${execsKo()} · 마크 = 바이낸스 가격`),
    ui.assumeLine(["open"], "페이퍼(연습) · 동전 쌍둥이 (참고)"));
  const el = h("div", {class: "lbp stack"}, rules, stateSlot, grid, foot);
  const roll = () => { for (const c of st.cards) c.el.update(c.sym ? ctx.store.mark(c.sym) : null); };
  function draw(d) {
    put(rules, rulesLine(d.rules),
      d.bars && d.bars.state !== "ok" ? h("p", {class: "note"}, "최대 +% · 최대 −%의 1분봉: ", sourceState(d.bars, "규칙봇 1분봉")) : null);
    st.cards = (d.cards || []).map((c) => ({el: posCard(c, {api: ctx.api}), sym: c.position ? c.position.symbol : null}));
    grid.replaceChildren(...st.cards.map((c) => c.el));
    roll();
  }
  async function load() {
    let d;
    try { d = await ctx.api(POS_API); st.okAt = Date.now(); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      if (!st.d) { put(stateSlot, ui.errorBox(e, () => load())); grid.replaceChildren(); }
      else { put(stateSlot, ui.staleNote(e, st.okAt, () => load())); ui.dim(grid, true); }
      throw e;
    }
    if (!ctx.alive()) return;
    put(stateSlot); ui.dim(grid, false);
    // the same records again redraw nothing (the numbers that roll with the mark keep rolling)
    const sig = JSON.stringify({...d, now_ms: 0});
    if (sig === st.sig) return;
    st.d = d; st.sig = sig;
    draw(d);
  }
  ctx.watch("ticker", () => roll());
  ctx.every(30000, () => { for (const c of st.cards) if (c.sym) c.el.update(ctx.store.mark(c.sym)); }, {now: false});
  load().catch(() => {});
  ctx.every(REFRESH_MS, () => load().catch(() => {}), {now: false});
  return {el, set() {}};
}
