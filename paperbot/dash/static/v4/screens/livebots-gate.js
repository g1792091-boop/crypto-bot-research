// 실거래 › 게이트 봇 (#/gatebot; owners 11-01 "일단 게이트 대시보드 화면 만드는거 진행해줘야지"): the friend's own Gate
// positions and what the 게이트 봇 (paperbot/gateguard.py, docs/gate-bot-ko.md) put on them, from its state file and config
// (dash/more/livegate.py, /api/v4/livebots/gate every 5 s), read-only. There is no trading rule: the friend enters by
// hand on Gate; the bot puts the stop (15분봉 ATR(14) × 3, pulled inside the liquidation price) and the ladder (+10 % ->
// the stop at +8 %, then 2 % steps) on each position, counted in the ROE ``rules.basis`` names: "gross" = 거래소 ROE
// (Gate's own, before fees; owners 11-03 "게이트 아이오봇 거래소 수익률 기준 10%로 2%로 마다 계단식 익절로 바꿔줘"),
// "net" = 순ROE (both fees paid).
//   상태         the bot's unit, its last loop, the Gate account, the rules in one line
//   포지션       one card each: Gate's own numbers (평단 · 수량 · 증거금 · 마크가 · 청산가 · 미실현), the bot's stop and its
//                basis, how far it is, the ROE if it fires; the ladder's rungs (locked · next), the best ROE so
//                far and the price of the next rung; what the bot is not doing (손 뗌 · 아직 안 봄 · 손절 없음 · 닫는 중)
//   끝난 포지션   Gate's record of each ended position (손익 수수료 포함), the bot's best ROE and lock on it
//   봇 메시지    the bot's own messages (the ones sent to Telegram), newest first
// HONESTY: a bot not installed, not switched on or not run yet says so and how to start it (docs/gate-bot-ko.md 4장);
// an old loop says how old; the screen never trades and the site has no Gate key.
import {h, put, ui, fmt, serverNow} from "../core/pb.js";

export const GATE_API = "/api/v4/livebots/gate";
const REFRESH_MS = 5 * 1000;
const ok = (x) => x != null && x !== "" && Number.isFinite(Number(x));
const UNIT_TONE = {run: "good", fail: "bad", stop: "warn", off: "thin", unknown: "thin"};
const LEVEL_TONE = {INFO: "thin", WARN: "warn", CRITICAL: "bad"};
const LEVEL_KO = {INFO: "알림", WARN: "주의", CRITICAL: "긴급"};

// ---------------------------------------------------------------- pure (node tests: tests/test_dash_livegate.py)
/** Net ROE on margin at ``price``, both fees paid (paperbot/ladder.py net_roe); null when a number is missing. */
export function netRoe(side, entry, price, lev, fee) {  // (fee 0: the exchange's own ROE)
  if (![side, entry, price, lev].every(ok) || !Number(entry) || !Number(lev) || !Number(side)) return null;
  return Number(lev) * (Number(side) * (Number(price) / Number(entry) - 1) - 2 * (Number(fee) || 0));
}
/** The ROE the bot's ladder counts in, in words (rules.basis: gross → 거래소 ROE, else 순ROE). */
export const roeWord = (rules) => ((rules || {}).basis === "gross" ? "거래소 ROE" : "순ROE");
/** The fee per side the bot's ladder takes off (gross: none), for netRoe. */
export const ladderFee = (rules, fee) => ((rules || {}).basis === "gross" ? 0 : fee);
/** The ladder's rungs to show: [{trigger, lock, on (locked), next}], from the first up to two past the next (at least 5). */
export function rungs(rules, lock) {
  if (!rules || ![rules.first_trigger, rules.first_lock, rules.step].every(ok) || !(Number(rules.step) > 0)) return [];
  const t0 = Number(rules.first_trigger), l0 = Number(rules.first_lock), st = Number(rules.step);
  const got = ok(lock) ? Math.round((Number(lock) - l0) / st) : -1;          // the rung locked (-1: none yet)
  return Array.from({length: Math.max(5, got + 3)}, (_, k) => ({trigger: t0 + k * st, lock: l0 + k * st, on: k <= got, next: k === got + 1}));
}
/** How far the ROE (on the bot's basis) is on the way from 0 to the next rung's trigger: 0..1 (null without both). */
export function toward(roe, next) {
  if (!ok(roe) || !next || !ok(next.trigger) || !(Number(next.trigger) > 0)) return null;
  return Math.max(0, Math.min(1, Number(roe) / Number(next.trigger)));
}
/** "+8%" (a lock or a trigger, whole percents unless it is not). */
export const roeKo = (x) => (ok(x) ? fmt.pct(x, Math.abs(Number(x) * 100 - Math.round(Number(x) * 100)) > 0.05 ? 1 : 0) : "—");
/** "12초 전" / "3분 전" / "1시간 5분 전" from seconds. */
export function agoS(s) {
  if (!ok(s)) return "—";
  const v = Math.max(0, Math.round(Number(s)));
  if (v < 60) return `${v}초 전`;
  const m = Math.round(v / 60);
  return m < 60 ? `${m}분 전` : `${Math.floor(m / 60)}시간${m % 60 ? ` ${m % 60}분` : ""} 전`;
}
/** The bot's state in one pill and one line: {tone, pill, line}. */
export function statusOf(d) {
  const u = (d && d.unit) || {}, loop = (d && d.loop) || {};
  if (!d) return {tone: "thin", pill: "불러오는 중", line: ""};
  if (d.state === "error") return {tone: "bad", pill: "못 읽음", line: `${d.ko || "게이트 봇 파일을 못 읽었어요"}${d.reason ? ` (${d.reason})` : ""}`};
  if (d.state !== "ok") return {tone: UNIT_TONE[u.state] || "thin", pill: d.state === "missing" ? "설치 전" : "켜기 전", line: d.ko || ""};
  const kept = "이미 걸린 손절 주문은 게이트에 그대로 남아 있어요";
  if (u.state === "fail") return {tone: "bad", pill: "오류로 멈춤", line: `봇이 오류로 멈췄어요 · 새 진입에 손절이 안 걸리고 계단 익절이 안 올라가요 · ${kept}`};
  if (u.state === "stop" || u.state === "off") return {tone: "warn", pill: "꺼져 있음", line: `봇이 꺼져 있어요 · 새 진입에 손절이 안 걸리고 계단 익절이 안 올라가요 · ${kept}`};
  const every = ok((d.rules || {}).poll_s) ? `${fmt.int(d.rules.poll_s)}초마다` : "몇 초마다";
  if (!loop.fresh) return {tone: "warn", pill: "확인 늦음", line: `봇의 마지막 확인이 ${agoS(loop.ago_s)}예요 (${every} 확인해요) · 서버 기록을 봐 주세요`};
  return {tone: "good", pill: "지키는 중", line: `${every} 게이트 포지션을 확인해요 · 마지막 확인 ${agoS(loop.ago_s)}`};
}
/** A stop's basis in words: "15분봉 ATR 2 × 3" / "ATR × 3 자리 94가 청산가 너머라 청산가 안쪽으로 당김" / "계단 잠금 거래소 ROE +10%". */
export function stopWhy(b, rules) {
  if (!b) return "";
  const r = rules || {}, tf = r.atr_tf_ko || "15분봉", n = ok(r.stop_atr) ? fmt.num(r.stop_atr, 0) : "3";
  if (b.kind === "lock") return `계단 잠금 ${roeWord(r)} ${roeKo(b.lock)}`;
  if (b.kind === "liq") return `${tf} ATR × ${n} 자리 ${fmt.price(b.atr_stop)}가 청산가 너머라 청산가 안쪽으로 당김`;
  return `${tf} ATR ${fmt.price(b.atr)} × ${n}`;
}
/** What the bot is not doing on a position, in words: [{tone, text}]. */
export function warnsOf(p) {
  const out = [], b = (p && p.bot) || null;
  if (!p) return out;
  if (!p.guarded) out.push({tone: "warn", text: "봇이 아직 이 포지션을 기록하지 않았어요 · 다음 확인에 손절을 걸어요 (봇이 켜져 있을 때)"});
  if (b && b.hands_off) out.push({tone: "bad", text: "봇이 손을 뗐어요: 봇 손절을 직접 취소했거나, 늦게 본 포지션이 이미 손절 자리를 지났어요 · 이 포지션은 직접 정리해 주세요 (새로 진입하거나 추가 진입하면 다시 지켜요)"});
  else if (b && !b.has_stop) out.push({tone: "warn", text: "손절 주문이 아직 게이트에 걸리지 않았어요 · 봇이 다시 걸고 있어요"});
  if (b && b.closing) out.push({tone: "warn", text: "가격이 잠금 자리를 이미 지나 시장가로 닫는 중이에요"});
  if (b && b.late && !b.hands_off) out.push({tone: "thin", text: "봇이 늦게 본 포지션이에요 · 최고가는 봇이 본 때부터 셌어요"});
  if (ok(p.to_liq) && Number(p.to_liq) < 0.02) out.push({tone: "bad", text: `청산가까지 ${fmt.pct(p.to_liq, 2, false)}밖에 안 남았어요`});
  return out;
}
/** The ended positions' line: "끝난 포지션 3개 · 이익 2 · 손실 1 · 합계 +1.20 USDT (게이트 기록 · 수수료 포함)". */
export function totalsKo(t) {
  if (!t || !t.n) return "아직 끝난 포지션이 없어요";
  return `끝난 포지션 ${fmt.int(t.n)}개 · 이익 ${fmt.int(t.wins)} · 손실 ${fmt.int(t.losses)}${t.unknown ? ` · 손익 모름 ${fmt.int(t.unknown)}` : ""}`
    + ` · 합계 ${fmt.usdt(t.pnl, true)} (게이트 기록 · 수수료 포함)`;
}

// ---------------------------------------------------------------- the view
function tile(k, v, sub, cls) {
  return h("div", {class: ["lmx-tile", "lgt-tile", cls || ""], role: "listitem"}, h("span", {class: "lmx-tk"}, k), h("b", {class: "lmx-tv num"}, v),
    sub ? h("span", {class: "lmx-ts"}, sub) : null);
}
function statusCard(d) {
  const s = statusOf(d), u = d.unit || {}, a = d.account || null, r = d.rules || null, ps = d.positions || [];
  const guarded = ps.filter((p) => p.guarded && !(p.bot || {}).hands_off).length;
  return ui.card({title: "게이트 봇", sub: "친구가 게이트에서 직접 진입 · 봇은 손절과 계단 익절만 걸어요 (진입하지 않음)", cls: `lgt-status ${s.tone}`},
    h("div", {class: "lgt-st"}, h("span", {class: ["lgt-dot", s.tone], "aria-hidden": "true"}), ui.pill(s.pill, s.tone), h("span", {class: "lgt-line"}, s.line)),
    h("div", {class: "lmx-money lgt-tiles", role: "list"},
      tile("서버 서비스", u.ko || "—", "paperbot-gateguard", UNIT_TONE[u.state] === "bad" ? "bad" : ""),
      tile("마지막 확인", d.loop && ok(d.loop.ago_s) ? agoS(d.loop.ago_s) : "—", d.loop && d.loop.ms ? fmt.kst(d.loop.ms) : "아직 없음", d.loop && !d.loop.fresh ? "na" : ""),
      tile("게이트 선물 잔고", a && ok(a.total) ? fmt.usdt(a.total) : "—", a && ok(a.available) ? `주문 가능 ${fmt.usdt(a.available)}` : "봇이 돌면 보여요", "real"),
      tile("지키는 포지션", d.state === "ok" ? `${fmt.int(guarded)} / ${fmt.int(ps.length)}` : "—", d.state === "ok" ? "봇이 손절을 건 것 / 게이트에 열린 것" : "")),
    r && r.words ? h("p", {class: "lgt-rules"}, ui.pill("규칙", "accent"), ` ${r.words}`) : null,
    r && r.refused_ko ? h("p", {class: "lgt-bad"}, ui.pill("설정 거부", "bad"), ` 봇이 이 설정으로는 시작하지 않아요: ${r.refused_ko}`) : null);
}
function startCard(d) {
  const missing = d.state === "missing";
  const steps = [
    ["코드 받기와 설치 (켜지지는 않아요)", "cd /root/crypto-bot-research && git pull && sudo bash deploy/install.sh", missing],
    ["설정 파일 복사", "docs/gate-bot-ko.md 4장 A-2", missing],
    ["키 넣기 (서버에서만 · 채팅에 쓰지 않기)", "sudoedit /etc/paperbot/executor-gate.env", missing],
    ["읽기만 하는 점검 (주문 없음)", "docs/gate-bot-ko.md 4장 A-4", true],
    ["친구가 가장 작은 수량으로 진입 → 켜기", "sudo systemctl start paperbot-gateguard (4장 B)", true],
  ];
  return ui.card({title: missing ? "아직 설치 전이에요" : "아직 켜기 전이에요", cls: "lgt-start"},
    h("p", {class: "lgt-line"}, d.ko || ""),
    h("ol", {class: "lgt-steps"}, steps.map(([k, cmd, todo]) => h("li", {class: todo ? "" : "done"}, h("b", null, k), h("code", null, cmd)))),
    ui.note("켜면 이 화면에 친구의 게이트 포지션, 봇이 건 손절과 계단 익절, 끝난 포지션, 봇 메시지가 보여요 · 순서는 두 분이 한 단계씩 결과를 보며 진행해요"));
}
function ladderBlock(p, b, rules) {
  const rs = rungs(rules, b.lock), nx = b.next || null, w = toward(b.roe_now, nx), rw = roeWord(rules);
  return h("div", {class: "lgt-lad"},
    h("div", {class: "lgt-lh"}, h("span", {class: "lgt-k"}, "계단 익절"),
      h("span", {class: "lgt-roe"}, `지금 ${rw} `, h("b", {class: ["num", fmt.tone(b.roe_now)]}, roeKo(b.roe_now)),
        " · 최고 ", h("b", {class: ["num", fmt.tone(b.best_roe)]}, roeKo(b.best_roe)))),
    rs.length ? h("ol", {class: "lgt-rungs", "aria-label": "계단 (닿으면 → 잠금)"}, rs.map((x) => h("li", {class: ["lgt-rung", x.on ? "on" : "", x.next ? "next" : ""],
      title: `${rw} ${roeKo(x.trigger)}에 닿으면 손절을 ${rw} ${roeKo(x.lock)} 자리로`},
      h("small", null, roeKo(x.trigger)), h("b", null, `→ ${roeKo(x.lock)}`)))) : null,
    w != null ? h("span", {class: "lgt-meter", style: {"--v": String(w)}, role: "img", "aria-label": `다음 계단까지 ${Math.round(w * 100)}%`}, h("i")) : null,
    nx ? h("p", {class: "lgt-next"}, `다음: ${rw} ${roeKo(nx.trigger)}${ok(nx.price) ? ` (가격 ${fmt.price(nx.price)})` : ""}에 닿으면 손절을 ${rw} ${roeKo(nx.lock)} 자리로 올려요`)
      : h("p", {class: "lgt-next"}, "계단 규칙을 읽지 못했어요 (설정 파일)"));
}
function posCard(p, rules) {
  const b = p.bot || null, side = Number(p.side), ws = warnsOf(p);
  const sr = b ? netRoe(side, p.entry, b.stop, p.lev, ladderFee(rules, b.fee)) : null;
  const gross = (rules || {}).basis === "gross";
  return h("section", {class: ["card", "lgt-pos", side > 0 ? "long" : "short", b && b.hands_off ? "off" : ""], "aria-label": `${p.coin} ${p.side_ko}`},
    h("header", {class: "lgt-ph"}, h("b", {class: "lgt-coin"}, p.coin), ui.sideTag(side), h("span", {class: "lgt-lev num"}, fmt.lev(p.lev)),
      ui.pill(p.cross ? "교차" : "격리", "thin"), b && !b.hands_off ? ui.pill("봇이 지킴", "good") : b ? ui.pill("손 뗌", "bad") : ui.pill("아직 안 봄", "warn"),
      h("span", {class: "lgt-upnl"}, h("small", null, "미실현 (게이트)"), h("b", {class: ["num", fmt.tone(p.upnl)]}, ok(p.upnl) ? fmt.usdt(p.upnl, true) : "—"))),
    h("dl", {class: "lgt-kv"},
      h("dt", null, "평단"), h("dd", {class: "num"}, fmt.price(p.entry)),
      h("dt", null, "수량"), h("dd", {class: "num"}, ok(p.size) ? fmt.num(Math.abs(Number(p.size)), 0) + "계약" : "—"),
      h("dt", null, "증거금"), h("dd", {class: "num"}, ok(p.margin) ? fmt.usdt(p.margin) : "—"),
      h("dt", null, "마크가"), h("dd", {class: "num"}, fmt.price(p.mark)),
      h("dt", null, "청산가"), h("dd", {class: "num"}, ok(p.liq) ? `${fmt.price(p.liq)}${ok(p.to_liq) ? ` (${fmt.pct(p.to_liq, 2, false)} 남음)` : ""}` : "없음 · 못 읽음"),
      h("dt", null, "진입"), h("dd", {class: "num"}, p.opened_ms ? fmt.kst(p.opened_ms) : "—")),
    b ? h("div", {class: ["lgt-stop", b.kind || ""]},
      h("span", {class: "lgt-k"}, "봇 손절"), h("b", {class: "lgt-sp num"}, fmt.price(b.stop)),
      h("span", {class: "lgt-why"}, stopWhy(b, rules)),
      h("span", {class: "lgt-sub"}, [ok(p.to_stop) ? `지금가에서 ${fmt.pct(Math.abs(p.to_stop), 2, false)}` : null,
        sr != null ? `닿으면 ${roeWord(rules)} ${fmt.pct(sr, 1)} (${gross ? "수수료 빼기 전" : "수수료 포함"} 어림)` : null].filter(Boolean).join(" · "))) : null,
    b ? ladderBlock(p, b, rules) : null,
    ws.length ? h("ul", {class: "lgt-warns"}, ws.map((x) => h("li", {class: x.tone}, x.text))) : null);
}
function closedCard(d) {
  const rows = d.closed || [];
  return ui.card({title: "끝난 포지션", sub: totalsKo(d.totals), cls: "lgt-closed"},
    rows.length ? ui.table([
      {label: "끝난 때", l: true, get: (r) => fmt.kst(r.end_ms)},
      {label: "코인", l: true, get: (r) => h("span", null, h("b", null, r.coin), " ", ui.sideTag(r.side))},
      {label: "손익 (게이트)", get: (r) => h("b", {class: ["num", fmt.tone(r.pnl)]}, ok(r.pnl) ? fmt.usdt(r.pnl, true) : "모름")},
      {label: "어떻게", l: true, get: (r) => r.cause || "—"},
      {label: "평단 → 종료", get: (r) => `${fmt.price(r.entry)} → ${fmt.price(r.exit)}`},
      {label: `최고 ${roeWord(d.rules)}`, get: (r) => roeKo(r.best_roe)},
      {label: "잠금", get: (r) => (ok(r.lock) ? roeKo(r.lock) : "—")},
    ], rows) : ui.empty("봇이 지키던 포지션이 끝나면 여기에 게이트 기록(손익 · 수수료)이 쌓여요"));
}
function logCard(d) {
  const rows = d.log || [];
  return ui.card({title: "봇 메시지", sub: "텔레그램으로 간 것과 같은 말 · 새 것부터", cls: "lgt-log"},
    rows.length ? h("ul", {class: "lgt-feed"}, rows.map((x) => h("li", {class: ["lgt-msg", LEVEL_TONE[x.level] || "thin"]},
      h("time", {class: "num"}, x.ms ? fmt.kst(x.ms) : "—"), ui.pill(LEVEL_KO[x.level] || x.level || "알림", LEVEL_TONE[x.level] || "thin"),
      h("span", {class: "lgt-mt"}, x.text || "")))) : ui.empty("아직 메시지가 없어요"));
}

/** gateView(ctx) -> {el, set()}: its own endpoint, read now and every 5 s. */
export function gateView(ctx) {
  const st = {d: null, okAt: 0, busy: false};
  const slot = h("div", {class: "lb-slot"});
  const main = h("div", {class: "lgt-body"});
  const el = h("div", {class: "lgt stack"}, slot, main,
    ui.note("보기만 하는 화면 · 5초마다 새로 읽어요 · 봇 상태 파일과 설정만 읽어요 (이 사이트에는 게이트 키가 없고 주문 버튼도 없어요)"));
  function draw() {
    const d = st.d;
    if (!d) return;
    const ps = d.positions || [], rules = d.rules || null;
    put(main, statusCard(d),
      d.state === "ok" ? h("div", {class: "lgt-grid"}, ps.length ? ps.map((p) => posCard(p, rules))
        : [ui.card({title: "열린 포지션 없음", cls: "lgt-none"}, h("p", {class: "lgt-line"}, "친구가 게이트에서 진입하면 봇이 다음 확인에 손절을 걸고, 여기에 카드가 생겨요"))])
        : d.state === "error" ? null : startCard(d),
      d.state === "ok" ? h("div", {class: "lgt-two"}, closedCard(d), logCard(d)) : null);
  }
  async function load() {
    if (st.busy) return;
    st.busy = true;
    let d;
    try { d = await ctx.api(GATE_API); }
    catch (e) {
      if (!ctx.alive() || (e && e.name === "AbortError")) return;
      if (st.d) { put(slot, ui.staleNote(e, st.okAt, () => load().catch(() => {}))); ui.dim(main, true); }
      else put(slot, ui.errorBox(e, () => load()));
      throw e;
    } finally { st.busy = false; }
    if (!ctx.alive()) return;
    put(slot);
    ui.dim(main, false);
    st.d = d; st.okAt = serverNow();
    draw();
  }
  put(main, ui.empty("불러오는 중"));
  load().catch(() => {});
  ctx.every(REFRESH_MS, () => load().catch(() => {}), {now: false});
  return {el, set() {}};
}
