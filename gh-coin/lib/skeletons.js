// 🦴 매매법 뼈대 — AI(특히 작은 로컬 모델)가 전략 JSON 형식을 못 맞출 때, 시도를 버리지 않고 코드가 '뼈대 + 값 변형'으로 대신 시험한다.
// 널리 알려진 고전 규칙(돈치안·EMA 정렬·슈퍼트렌드·MACD·볼린저·켈트너·RSI 되돌림)의 개념만 우리 전략 JSON 으로 표현 — 코드 복사 없음.
// 통과 판정은 여전히 코드 관문(워크포워드·견고성·교차코인)이 한다. 뼈대라고 통과가 보장되지 않는다.
const c = (left, op, right) => ({ left, op, right: String(right) }), G = L => ({ logic: "all", conditions: L });
const pick = (rnd, a) => a[Math.floor(rnd() * a.length)];
// 각 뼈대: fam(trend|revert) + build(rnd) → {name, indicators, long_entry, short_entry, long_exit?, short_exit?}
export const SKELETONS = [
  { key: "donchian_adx", fam: "trend", build: r => { const n = pick(r, [20, 30, 40]), a = pick(r, [18, 22, 25]), e = pick(r, [100, 200]);
    return { name: `돈치안 ${n} 돌파 + ADX ${a} + EMA${e}`, indicators: [{ id: "hh", type: "highest", length: n }, { id: "ll", type: "lowest", length: n }, { id: "adx", type: "adx", length: 14 }, { id: "e", type: "ema", length: e }],
      long_entry: G([c("close", ">", "hh[1]"), c("adx.adx", ">", a), c("close", ">", "e")]), short_entry: G([c("close", "<", "ll[1]"), c("adx.adx", ">", a), c("close", "<", "e")]) }; } },
  { key: "ema_stack_pull", fam: "trend", build: r => { const f = pick(r, [9, 12, 20]), m = pick(r, [50, 55]), s = pick(r, [150, 200]);
    return { name: `EMA ${f}>${m}>${s} 정렬 + ${f}EMA 눌림`, indicators: [{ id: "f", type: "ema", length: f }, { id: "m", type: "ema", length: m }, { id: "s", type: "ema", length: s }],
      long_entry: G([c("f", ">", "m"), c("m", ">", "s"), c("low", "<=", "f"), c("close", ">", "f")]), short_entry: G([c("f", "<", "m"), c("m", "<", "s"), c("high", ">=", "f"), c("close", "<", "f")]) }; } },
  { key: "st_flip", fam: "trend", build: r => { const n = pick(r, [10, 14]), k = pick(r, [2.5, 3, 3.5]), e = pick(r, [100, 200]);
    return { name: `슈퍼트렌드(${n},${k}) 전환 + EMA${e}`, indicators: [{ id: "st", type: "supertrend", length: n, mult: k }, { id: "e", type: "ema", length: e }],
      long_entry: G([c("st.trend", "crosses_above", 0), c("close", ">", "e")]), short_entry: G([c("st.trend", "crosses_below", 0), c("close", "<", "e")]) }; } },
  { key: "macd_adx", fam: "trend", build: r => { const a = pick(r, [18, 20, 25]), e = pick(r, [100, 200]);
    return { name: `MACD 교차 + ADX ${a} + EMA${e}`, indicators: [{ id: "mc", type: "macd" }, { id: "adx", type: "adx", length: 14 }, { id: "e", type: "ema", length: e }],
      long_entry: G([c("mc.line", "crosses_above", "mc.signal"), c("adx.adx", ">", a), c("close", ">", "e")]), short_entry: G([c("mc.line", "crosses_below", "mc.signal"), c("adx.adx", ">", a), c("close", "<", "e")]) }; } },
  { key: "bb_break_vol", fam: "trend", build: r => { const k = pick(r, [1.3, 1.5, 2]), e = pick(r, [100, 200]);
    return { name: `볼린저 돌파 + 거래량 ×${k} + EMA${e}`, indicators: [{ id: "bb", type: "bb", length: 20, mult: 2 }, { id: "vm", type: "volume_sma", length: 20 }, { id: "e", type: "ema", length: e }],
      long_entry: G([c("close", "crosses_above", "bb.upper"), c("volume", ">", `vm*${k}`), c("close", ">", "e")]), short_entry: G([c("close", "crosses_below", "bb.lower"), c("volume", ">", `vm*${k}`), c("close", "<", "e")]) }; } },
  { key: "rsi50_trend", fam: "trend", build: r => { const f = pick(r, [50, 55]), s = pick(r, [150, 200]);
    return { name: `EMA${f}>EMA${s} 추세 + RSI 50 재돌파`, indicators: [{ id: "r", type: "rsi", length: 14 }, { id: "f", type: "ema", length: f }, { id: "s", type: "ema", length: s }],
      long_entry: G([c("f", ">", "s"), c("r", "crosses_above", 50)]), short_entry: G([c("f", "<", "s"), c("r", "crosses_below", 50)]) }; } },
  { key: "kelt_revert", fam: "revert", build: r => { const k = pick(r, [1.8, 2, 2.5]), a = pick(r, [20, 25, 30]);
    return { name: `켈트너(${k}) 하단 복귀 + ADX<${a}`, indicators: [{ id: "k", type: "keltner", length: 20, mult: k }, { id: "adx", type: "adx", length: 14 }],
      long_entry: G([c("close", "crosses_above", "k.lower"), c("adx.adx", "<", a)]), short_entry: G([c("close", "crosses_below", "k.upper"), c("adx.adx", "<", a)]) }; } },
  { key: "bb_revert", fam: "revert", build: r => { const k = pick(r, [2, 2.5]), a = pick(r, [20, 25, 30]);
    return { name: `볼린저(${k}) 하단 복귀 + ADX<${a}`, indicators: [{ id: "bb", type: "bb", length: 20, mult: k }, { id: "adx", type: "adx", length: 14 }],
      long_entry: G([c("close", "crosses_above", "bb.lower"), c("adx.adx", "<", a)]), short_entry: G([c("close", "crosses_below", "bb.upper"), c("adx.adx", "<", a)]),
      long_exit: { logic: "any", conditions: [c("close", ">", "bb.middle")] }, short_exit: { logic: "any", conditions: [c("close", "<", "bb.middle")] } }; } },
  { key: "rsi_revert", fam: "revert", build: r => { const lo = pick(r, [25, 30, 35]), a = pick(r, [25, 30]);
    return { name: `RSI ${lo}/${100 - lo} 복귀 + ADX<${a}`, indicators: [{ id: "r", type: "rsi", length: 14 }, { id: "adx", type: "adx", length: 14 }],
      long_entry: G([c("r", "crosses_above", lo), c("adx.adx", "<", a)]), short_entry: G([c("r", "crosses_below", 100 - lo), c("adx.adx", "<", a)]) }; } },
  { key: "rsi2_trend", fam: "revert", build: r => { const lo = pick(r, [5, 10, 15]), e = pick(r, [100, 200]);
    return { name: `추세 속 RSI(2)<${lo} 눌림 + EMA${e}`, indicators: [{ id: "r2", type: "rsi", length: 2 }, { id: "e", type: "ema", length: e }, { id: "s5", type: "sma", length: 5 }],
      long_entry: G([c("r2", "<", lo), c("close", ">", "e")]), short_entry: G([c("r2", ">", 100 - lo), c("close", "<", "e")]),
      long_exit: { logic: "any", conditions: [c("close", ">", "s5")] }, short_exit: { logic: "any", conditions: [c("close", "<", "s5")] } }; } },
];
// seed 로 재현 가능한 난수
function rng(seed) { let x = (seed >>> 0) || 1; return () => { x ^= x << 13; x >>>= 0; x ^= x >> 17; x ^= x << 5; x >>>= 0; return x / 4294967296; }; }
// n 번째 시도용 뼈대 변형. fam = "trend" | "revert" | null(둘 다). 손절·익절은 코인 선물 프레임워크(손절 ≤ 2%)에 맞춘 값 중에서 고른다.
export function variant(n, fam = null, tag = "") {
  const r = rng(1234567 + n * 7919), pool = SKELETONS.filter(s => !fam || s.fam === fam), sk = pool[n % pool.length], b = sk.build(r);
  const [sl, tp] = pick(r, sk.fam === "trend" ? [[1.5, 3], [1.5, 4.5], [2, 4], [2, 6]] : [[1.5, 1.5], [1.5, 2.25], [2, 2], [2, 3]]);
  return { name: `${tag ? tag + " " : ""}${b.name} [손절 ${sl}% · 익절 ${tp}%]`, description: `뼈대 변형(${sk.key}) — AI 형식 실패 시 코드가 대신 구성`, indicators: b.indicators, long_entry: b.long_entry, short_entry: b.short_entry,
    long_exit: b.long_exit || null, short_exit: b.short_exit || null, risk: { leverage: Math.floor(40 / sl), stop_loss_pct: sl, take_profit_pct: tp }, _skeleton: sk.key };
}
