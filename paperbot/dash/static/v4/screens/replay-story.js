// 거래 다시보기: the words of each moment (plain Korean, the 두 분 voice), built from /api/v4/replay/<id> only. Every
// number is the trade's own record or a bar of the chart; what the page rebuilt from bars (lock times, the reel's
// breach bar) says so. Pure functions (no DOM): replay.js draws them.
import {fmt} from "../core/pb.js";

const side2 = (side) => (side > 0 ? "롱" : "숏");
const pctOf = (r) => fmt.pct(r, 2, false);

/** The exit reason in the app's words (fmt.reasonKo), with the reel's target named: "익절 (윗밴드)". */
export function exitKo(d) {
  const r = d.trade.exit_reason;
  if (d.exits === "reel" && r === "TP") return "익절 (윗밴드)";
  if (d.exits === "reel" && r === "TIME") return `시간 청산 (${d.reel_bars || 96}봉)`;
  if (r === "LOCK" && d.trade.lock_roe != null) return `${fmt.reasonKo(r)} +${fmt.num(d.trade.lock_roe * 100, 0)}%`;
  return fmt.reasonKo(r);
}

/** What the account's entry is, in a few words (house strategy / DeepSeek / the reel / a coin flip). */
export function entryWho(d) {
  const a = d.account || {};
  if (a.kind === "random") return d.exits === "reel" ? "동전 봇 (5분봉, 롱만)" : "동전 봇";
  if (a.kind === "reel") return "5분봉 매매법 (볼린저 띠 + 200선)";
  return fmt.stratKo(a.strategy);
}

/** The stop in force on each bar (null outside the holding bars) and whether it is a lock by then. The bot checks
 *  every 1m bar, so a lock raised inside a chart bar is drawn from that bar on. */
export function stopPath(d) {
  const n = d.bars.length, {entry: ie, exit: ix} = d.idx;
  const out = Array.from({length: n}, () => null);
  if (ie == null) return out;
  const end = ix == null ? n - 1 : ix;
  const first = d.levels.stop_initial;
  const steps = d.steps || [];
  let cur = first, lock = null, si = 0;
  for (let j = ie; j <= end; j++) {
    while (si < steps.length && steps[si].bar <= j) { cur = steps[si].price; lock = steps[si].level; si++; }
    out[j] = cur == null ? null : {v: cur, lock};
  }
  return out;
}

/** Event texts (one line each): {bar, kind, text, tone: "up"|"down"|"warn"|"accent"|""}. */
export function eventLines(d) {
  const t = d.trade, lv = d.levels, bars = d.bars, side = t.side;
  const dec = (p) => fmt.price(p);
  const out = [];
  let nLock = 0;
  for (const e of d.events) {
    let text = "", tone = "";
    if (e.kind === "breach") {
      text = `준비: 종가 ${dec(e.price)}가 볼린저 아래 띠(${dec(e.band)}) 밖에서 마감했습니다. 가운데 선이 200선 위라 사기를 준비합니다.`;
      tone = "warn";
    } else if (e.kind === "breach_again") {
      text = "또 아래 띠 밖에서 마감: 기다리는 12봉을 다시 셉니다.";
      tone = "warn";
    } else if (e.kind === "signal") {
      if (e.how === "reel") text = e.ok === false
        ? "신호 봉: 봇이 이 봉 끝에 신호를 냈습니다 (이 화면의 봉으로 다시 재면 조건이 딱 맞지는 않습니다)."
        : "신호: 양봉이 볼린저 띠 안에서 마감했습니다 (아래에서 반등). 다음 봉이 시작할 때 삽니다.";
      else if (e.how === "flip") text = `동전 던지기: ${side2(side)}${d.exits === "reel" ? " (5분봉 동전 봇은 롱만)" : ""}. 비교용 무작위 진입입니다.`;
      else text = `신호: ${entryWho(d)}가 이 봉이 닫힐 때 ${side2(side)} 신호를 냈습니다.`;
      tone = "accent";
    } else if (e.kind === "entry") {
      const st = lv.stop_initial;
      const dist = st && t.entry_price ? Math.abs(t.entry_price - st) / t.entry_price : null;
      text = `진입: ${dec(t.entry_price)}에 ${side2(side)} · ${fmt.lev(t.leverage)} · 첫 손절 ${dec(st)}` +
        (dist != null ? ` (${pctOf(dist)} ${side > 0 ? "아래" : "위"})` : "");
      if (d.exits === "reel") {
        const tg = d.lines && d.lines.target ? d.lines.target[e.bar] : null;
        text += tg ? ` · 목표 윗밴드 ${dec(tg)}` : "";
      } else if (lv.lock_start) {
        text += ` · 고정 익절 없음, ${dec(lv.lock_start)}에 닿으면 잠금 시작`;
      }
    } else if (e.kind === "lock") {
      const L = fmt.num(e.level * 100, 0);
      text = nLock++ === 0
        ? `손절선을 ${side > 0 ? "올림" : "내림"} (익절 잠금 +${L}%): 이제 ${dec(e.price)}에 닿아도 증거금 대비 +${L}%를 지키고 나갑니다.`
        : `잠금을 한 칸 더: +${L}% (손절선 ${dec(e.price)})`;
      tone = "up";
    } else if (e.kind === "exit") {
      const r = e.reason;
      const head = r === "SL" ? "손절에 닿아 청산" : r === "LOCK" ? "익절 잠금선에 닿아 청산" : r === "TP" && d.exits === "reel" ? "윗밴드 목표에 닿아 익절"
        : r === "TP" ? "익절가에 닿아 청산" : r === "TIME" ? `${d.reel_bars || 96}봉이 지나 시간 청산` : r === "LIQ" ? "강제청산: 증거금을 모두 잃었습니다"
        : `${fmt.reasonKo(r)}로 청산`;
      text = `${head} · ${dec(e.price)} · 손익 ${fmt.money(t.pnl, true)} USDT (ROE ${fmt.pct(t.roe, 1)})`;
      tone = t.pnl > 0 ? "up" : t.pnl < 0 ? "down" : "";
    }
    if (text) out.push({bar: e.bar, kind: e.kind, text, tone, t: bars[e.bar] ? bars[e.bar][0] * 1000 : null, rebuilt: !!e.rebuilt});
  }
  return out;
}

/** The caption of bar k: its events, or where the trade stands (before / holding / after). */
export function caption(d, k, evs, stops) {
  const here = evs.filter((e) => e.bar === k);
  if (here.length) return {text: here.map((e) => e.text).join(" → "), tone: here[here.length - 1].tone, kind: here[here.length - 1].kind};
  const t = d.trade, {entry: ie, exit: ix, signal: is} = d.idx, b = d.bars[k];
  if (!b) return {text: "", tone: ""};
  const close = b[4];
  if (ie == null || k < ie) {
    const firstEv = evs.length ? evs[0].bar : ie;
    const left = firstEv != null ? firstEv - k : null;
    if (d.exits === "reel" && d.lines && d.lines.bb_dn && d.lines.bb_dn[k] != null) {
      const ma = d.lines.ma200 && d.lines.ma200[k];
      const where = close < d.lines.bb_dn[k] ? "아래 띠 밖" : close > d.lines.bb_up[k] ? "위 띠 밖" : "띠 안";
      return {text: `진입 전 · 종가 ${fmt.price(close)} (${where})` + (ma ? ` · 200선 ${fmt.price(ma)}` : " · 200선은 아직 200봉이 안 모여 없음") +
        (left != null && left > 0 ? ` · ${fmt.int(left)}봉 뒤 ${is != null && evs[0] && evs[0].kind === "signal" ? "신호" : "준비"}` : ""), tone: ""};
    }
    return {text: `진입 전 · 종가 ${fmt.price(close)}` + (left != null && left > 0 ? ` · ${fmt.int(left)}봉 뒤 신호` : ""), tone: ""};
  }
  if (ix == null || k < ix) {
    const n = k - ie + 1;
    const move = t.side * (close / t.entry_price - 1);
    const roe = move * t.leverage;
    const st = stops[k];
    let s = `보유 ${fmt.int(n)}봉째 · 종가 ${fmt.price(close)} · 진입가 대비 ${fmt.pct(move, 2)} (레버리지 곱하면 약 ${fmt.pct(roe, 1)}, 비용 전)`;
    if (st) s += st.lock != null ? ` · 잠금 +${fmt.num(st.lock * 100, 0)}% 유지 (${fmt.price(st.v)})` : ` · 손절 ${fmt.price(st.v)}`;
    if (d.exits === "reel" && d.lines && d.lines.target && d.lines.target[k] != null) s += ` · 목표 ${fmt.price(d.lines.target[k])}`;
    return {text: s, tone: ""};
  }
  const after = k - ix;
  const m = t.exit_price ? (close / t.exit_price - 1) : null;
  return {text: `청산 뒤 ${fmt.int(after)}봉 · 종가 ${fmt.price(close)}` + (m != null ? ` (청산가 대비 ${fmt.pct(m, 2)}, 참고)` : "") +
    " · 청산 뒤 움직임은 이 거래의 손익과 상관없습니다.", tone: ""};
}

/** Where the replay starts when ▶ is pressed: a few bars before the first event. */
export const startBar = (d, evs) => Math.max(0, Math.min(evs.length ? evs[0].bar : d.idx.entry ?? 0, d.bars.length - 1) - 6);

/** Notes under the chart (how to read it, where the bars come from, what was rebuilt). */
export function notes(d) {
  const out = [];
  const tfKo = fmt.tfKo(d.tf);
  if (d.source === "live_bars") out.push(`봉: 봇이 실제로 받은 1분봉을 ${tfKo}봉으로 묶었습니다.`);
  else if (d.source === "binance") out.push(`봉: 바이낸스 공개 시세 ${tfKo}봉 (서버가 받아 옴).`);
  if (d.stepped) out.push(`거래가 길어서 ${tfKo}봉으로 보여 드립니다 (계좌는 ${fmt.tfKo(d.tf_own)}봉).`);
  if (d.exits === "reel") out.push("볼린저 띠(20, 2)와 200선은 같은 봉으로 이 화면에서 계산했습니다. 목표는 직전 봉의 윗밴드라 봉마다 옮겨집니다. 사다리 잠금은 없습니다.");
  if ((d.steps || []).length) out.push("잠금 시점은 봉으로 다시 맞춘 것입니다 (봇은 1분마다 확인합니다). 마지막 잠금선은 기록 그대로입니다.");
  if (d.events.some((e) => e.kind === "breach")) out.push("'밴드 밖' 표시는 이 화면의 봉으로 다시 찾은 것입니다.");
  if (d.partial) out.push("마지막 봉은 아직 만들어지는 중입니다.");
  return out;
}

/** The first caption, with the whole trade on screen: the story in one line and how to play it. */
export function summary(d, evs) {
  const t = d.trade;
  const at = (k) => evs.find((e) => e.kind === k);
  const sig = at("signal"), ent = at("entry"), ex = at("exit");
  const locks = evs.filter((e) => e.kind === "lock").length;
  const parts = [];
  if (sig && sig.t) parts.push(`${fmt.hm(sig.t)} 신호`);
  if (ent && ent.t) parts.push(`${fmt.hm(ent.t)} 진입 ${fmt.price(t.entry_price)}`);
  if (locks) parts.push(`잠금 ${fmt.int(locks)}번`);
  if (ex && ex.t) parts.push(`${fmt.hm(ex.t)} ${exitKo(d)} ${fmt.price(t.exit_price)}`);
  return `한눈에: ${parts.join(" → ")} · 손익 ${fmt.money(t.pnl, true)} USDT. ▶ 재생을 누르면 신호 몇 봉 전부터 봉이 하나씩 나옵니다.`;
}
