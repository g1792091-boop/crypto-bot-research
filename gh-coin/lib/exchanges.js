// 멀티 거래소 공개 시세 — ccxt(MIT) 의 '통일 API'(fetchTicker · fetchFundingRate · fetchOpenInterest) 개념을 공개 REST 몇 개로 작게 다시 만든 것.
// 거래소마다 심볼·필드·단위가 다른 것을 한 모양 {ex, sym, last, chg24(%), vol24Quote, funding8h(%), oiCoin, next} 으로 맞춘다.
// 함정 처리: OKX 계약 수 → 코인(ctVal 0.01 BTC 등), Bybit·Bitget 변동률은 소수 → %, 펀딩 주기가 다르면 8시간 기준으로 환산,
//           업비트·빗썸 변동률은 한국 09:00(UTC 00:00) 기준, 크라켄 'o'는 UTC 하루 시가.
// 요청 간격은 거래소별로 띄운다(ccxt 기본 지연: 바이낸스 50ms · 바이비트 20 · OKX 110 · 비트겟 50 · 크라켄 1000 · 업비트 50).
const GAP = {binance: 50, bybit: 20, okx: 110, bitget: 50, coinbase: 120, kraken: 1000, upbit: 50, bithumb: 60};
const lastAt = {};
async function paced(ex, fn){ const w = (lastAt[ex] || 0) + (GAP[ex] || 100) - Date.now(); if (w > 0) await new Promise(r => setTimeout(r, w)); lastAt[ex] = Date.now(); return fn(); }
const n = v => v == null || v === "" || !Number.isFinite(+v) ? null : +v;
const OKX_CT = {BTC: 0.01, ETH: 0.1, SOL: 1, XRP: 100, DOGE: 1000, BNB: 0.01};
const KRAKEN = {BTC: ["XBTUSD", "XXBTZUSD"], ETH: ["ETHUSD", "XETHZUSD"], SOL: ["SOLUSD", "SOLUSD"], XRP: ["XRPUSD", "XXRPZUSD"], DOGE: ["XDGUSD", "XDGUSD"]};

// get(url) → JSON (앱에서는 engine.webGet(url, "json"))
export const VENUES = {
  binance: {ko: "바이낸스 선물", quote: "USDT", perp: true, async fetch(get, base){
    const s = base + "USDT", [t, f, o] = await Promise.all([get(`https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=${s}`), get(`https://fapi.binance.com/fapi/v1/premiumIndex?symbol=${s}`).catch(() => null), get(`https://fapi.binance.com/fapi/v1/openInterest?symbol=${s}`).catch(() => null)]);
    return {last: n(t.lastPrice), chg24: n(t.priceChangePercent), vol24Quote: n(t.quoteVolume), funding8h: f ? n(f.lastFundingRate) * 100 : null, next: n(f?.nextFundingTime), mark: n(f?.markPrice), oiCoin: n(o?.openInterest)};
  }},
  bybit: {ko: "바이비트", quote: "USDT", perp: true, async fetch(get, base){
    const r = await get(`https://api.bybit.com/v5/market/tickers?category=linear&symbol=${base}USDT`), x = r?.result?.list?.[0]; if (!x) throw new Error("없음");
    return {last: n(x.lastPrice), chg24: n(x.price24hPcnt) * 100, vol24Quote: n(x.turnover24h), funding8h: n(x.fundingRate) * 100, next: n(x.nextFundingTime), oiCoin: n(x.openInterest)};
  }},
  okx: {ko: "OKX", quote: "USDT", perp: true, async fetch(get, base){
    const id = `${base}-USDT-SWAP`, [t, f, o] = await Promise.all([get(`https://www.okx.com/api/v5/market/ticker?instId=${id}`), get(`https://www.okx.com/api/v5/public/funding-rate?instId=${id}`).catch(() => null), get(`https://www.okx.com/api/v5/public/open-interest?instType=SWAP&instId=${id}`).catch(() => null)]);
    const x = t?.data?.[0]; if (!x) throw new Error("없음");
    const fr = f?.data?.[0], oi = o?.data?.[0], ct = OKX_CT[base] || 1;
    // OKX 펀딩 주기가 8시간이 아닐 수 있다: fundingTime ~ nextFundingTime 간격으로 환산
    const hrs = fr && n(fr.nextFundingTime) && n(fr.fundingTime) ? (n(fr.nextFundingTime) - n(fr.fundingTime)) / 36e5 : 8;
    return {last: n(x.last), chg24: n(x.open24h) ? (n(x.last) / n(x.open24h) - 1) * 100 : null, vol24Quote: n(x.volCcy24h) && n(x.last) ? n(x.volCcy24h) * n(x.last) : null, funding8h: fr ? n(fr.fundingRate) * 100 * (8 / (hrs || 8)) : null, next: n(fr?.fundingTime), oiCoin: oi ? (n(oi.oiCcy) ?? n(oi.oi) * ct) : null};
  }},
  bitget: {ko: "비트겟", quote: "USDT", perp: true, async fetch(get, base){
    const r = await get(`https://api.bitget.com/api/v2/mix/market/ticker?symbol=${base}USDT&productType=USDT-FUTURES`), x = Array.isArray(r?.data) ? r.data[0] : r?.data; if (!x) throw new Error("없음");
    return {last: n(x.lastPr), chg24: n(x.change24h) * 100, vol24Quote: n(x.quoteVolume) ?? n(x.usdtVolume), funding8h: n(x.fundingRate) * 100, oiCoin: n(x.holdingAmount)};
  }},
  coinbase: {ko: "코인베이스", quote: "USD", perp: false, async fetch(get, base){
    const [t, s] = await Promise.all([get(`https://api.exchange.coinbase.com/products/${base}-USD/ticker`), get(`https://api.exchange.coinbase.com/products/${base}-USD/stats`).catch(() => null)]);
    return {last: n(t.price), chg24: s && n(s.open) ? (n(t.price) / n(s.open) - 1) * 100 : null, vol24Quote: n(t.volume) && n(t.price) ? n(t.volume) * n(t.price) : null};
  }},
  kraken: {ko: "크라켄", quote: "USD", perp: false, async fetch(get, base){
    const k = KRAKEN[base]; if (!k) throw new Error("미상장");
    const r = await get(`https://api.kraken.com/0/public/Ticker?pair=${k[0]}`), x = r?.result?.[k[1]] || Object.values(r?.result || {})[0]; if (!x) throw new Error("없음");
    return {last: n(x.c?.[0]), chg24: n(x.o) ? (n(x.c?.[0]) / n(x.o) - 1) * 100 : null, vol24Quote: n(x.v?.[1]) && n(x.c?.[0]) ? n(x.v[1]) * n(x.c[0]) : null, note: "변동 = UTC 하루 시가 기준"};
  }},
  upbit: {ko: "업비트", quote: "KRW", perp: false, async fetch(get, base){
    const r = await get(`https://api.upbit.com/v1/ticker?markets=KRW-${base},KRW-USDT`), x = r.find(y => y.market === `KRW-${base}`), u = r.find(y => y.market === "KRW-USDT");
    return {last: n(x?.trade_price), chg24: n(x?.signed_change_rate) * 100, vol24Quote: n(x?.acc_trade_price_24h), usdtKrw: n(u?.trade_price), note: "변동 = 한국 09:00 기준"};
  }},
  bithumb: {ko: "빗썸", quote: "KRW", perp: false, async fetch(get, base){
    const r = await get(`https://api.bithumb.com/v1/ticker?markets=KRW-${base}`), x = Array.isArray(r) ? r[0] : null; if (!x) throw new Error("없음");
    return {last: n(x.trade_price), chg24: n(x.signed_change_rate) * 100, vol24Quote: n(x.acc_trade_price_24h)};
  }}
};

// 한 코인을 모든 거래소에서 → 비교표 (기준 = 바이낸스 선물)
export async function compare(get, base = "BTC", only){
  const ids = only || Object.keys(VENUES), rows = [];
  await Promise.all(ids.map(id => paced(id, async () => { try { rows.push({ex: id, ko: VENUES[id].ko, quote: VENUES[id].quote, perp: VENUES[id].perp, ...(await VENUES[id].fetch(get, base))}); } catch(e){ rows.push({ex: id, ko: VENUES[id].ko, quote: VENUES[id].quote, err: String(e.message || e).slice(0, 60)}); } })));
  rows.sort((a, b) => ids.indexOf(a.ex) - ids.indexOf(b.ex));
  const ref = rows.find(r => r.ex === "binance" && r.last), up = rows.find(r => r.ex === "upbit" && r.last);
  const usdKrw = up?.usdtKrw || null;
  for (const r of rows){
    if (!r.last || !ref) continue;
    const usd = r.quote === "KRW" ? (usdKrw ? r.last / usdKrw : null) : r.last;
    r.usd = usd; r.spreadPct = usd ? (usd / ref.last - 1) * 100 : null;
  }
  // 김치 프리미엄 = 업비트 KRW / (바이낸스 USDT × 업비트 KRW-USDT) − 1
  const kimchi = up && ref && usdKrw ? (up.last / (ref.last * usdKrw) - 1) * 100 : null;
  const perps = rows.filter(r => r.funding8h != null);
  const fundSpread = perps.length >= 2 ? Math.max(...perps.map(r => r.funding8h)) - Math.min(...perps.map(r => r.funding8h)) : null;
  const okPx = rows.filter(r => r.spreadPct != null);
  return {base, rows, kimchi, usdKrw, fundSpread, maxGap: okPx.length >= 2 ? Math.max(...okPx.map(r => r.spreadPct)) - Math.min(...okPx.map(r => r.spreadPct)) : null, t: Date.now()};
}

// 펀딩 상태 (Vibe-Trading 코인 데스크 규칙): 7일 평균(8시간당 %) 과 최근 3번
export function fundingRegime(avg7d, last3 = []){
  if (avg7d == null) return {key: "na", ko: "자료 없음"};
  const allPos = last3.length >= 3 && last3.every(x => x > 0), allNeg = last3.length >= 3 && last3.every(x => x < 0);
  const ann = avg7d * 3 * 365;
  if (avg7d > 0.03 && allPos) return {key: "hotLong", ko: "롱 과열 (펀딩 높음)", ann};
  if (avg7d < -0.02 && allNeg) return {key: "hotShort", ko: "숏 과열 (펀딩 음수 큼)", ann};
  if (avg7d > 0.01) return {key: "bullCarry", ko: "강세 쪽 쏠림", ann};
  if (avg7d < -0.005) return {key: "bearCarry", ko: "약세 쪽 쏠림", ann};
  return {key: "neutral", ko: "중립", ann};
}
