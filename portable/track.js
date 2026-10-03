// 예측 기록·채점 — 자체 AI·단타/스윙·위원회 같은 '방향 예측'이 실제로 맞았는지 추적하고,
// 확신도 캘리브레이션("확신 80%일 때 진짜 80% 맞나?")을 낸다. 외부 라이브러리 0개 · 저장소 주입식({get,set}).
// 흐름: record(예측) → (horizon 지나면) settle(현재가로 채점) → stats(적중률·확신도 구간별).
const CONF_BANDS = [[0, 40], [40, 55], [55, 70], [70, 85], [85, 101]];
const bandLabel = (lo, hi) => `${lo}~${hi > 100 ? 95 : hi}%`;

export function makeTracker(store, {key = "coinPredict", max = 600, neutralPct = 2} = {}){
  const read = () => { try { const v = store.get(key, []); return Array.isArray(v) ? v : []; } catch(e){ return []; } };
  const write = l => { try { store.set(key, l.slice(-max)); } catch(e){} };
  return {
    // 예측 하나 기록. p: {source, coin, ko?, dir(-1/0/1), confidence(0~100), price, horizonMs?}
    // 같은 소스·코인에 '열린(미채점)' 예측이 이미 있고 방향이 같으면 중복으로 안 쌓는다.
    record(p){
      if (!p || !(+p.price > 0) || p.dir == null) return null;
      const list = read(), dir = Math.sign(p.dir), source = p.source || "?", coin = p.coin || "";
      if (list.some(x => x.status === "pending" && x.source === source && x.coin === coin && x.dir === dir)) return null;
      const item = {id: Date.now().toString(36) + Math.random().toString(36).slice(2, 5), source, coin, ko: p.ko || coin, dir, confidence: Math.round(+p.confidence || 0), p0: +p.price, t: Date.now(), due: Date.now() + (p.horizonMs || 864e5), status: "pending"};
      list.push(item); write(list); return item;
    },
    // horizon 지난 예측을 현재가로 채점. getPrice(coin) → 현재가(숫자) 또는 null
    async settle(getPrice){
      const list = read(); let changed = false;
      for (const d of list){
        if (d.status !== "pending" || Date.now() < d.due) continue;
        let px = null; try { px = await getPrice(d.coin); } catch(e){}
        if (!(+px > 0)) continue;
        const move = (px / d.p0 - 1) * 100;
        d.p1 = +(+px).toFixed(8); d.move = +move.toFixed(2);
        d.hit = d.dir === 0 ? Math.abs(move) < neutralPct : Math.sign(move) === d.dir;
        d.status = "resolved"; d.resolved = Date.now(); changed = true;
      }
      if (changed) write(list);
      return changed;
    },
    // 적중률 + 확신도 구간별 캘리브레이션
    stats(source){
      const all = read(), done = all.filter(d => d.status === "resolved" && (!source || d.source === source));
      const n = done.length, hits = done.filter(d => d.hit).length;
      const bands = CONF_BANDS.map(([lo, hi]) => { const b = done.filter(d => d.confidence >= lo && d.confidence < hi), h = b.filter(d => d.hit).length;
        return {band: bandLabel(lo, hi), n: b.length, rate: b.length ? Math.round(h / b.length * 100) : null, avgConf: b.length ? Math.round(b.reduce((s, x) => s + x.confidence, 0) / b.length) : null}; });
      const avgMove = done.length ? +(done.reduce((s, d) => s + (d.hit ? Math.abs(d.move) : -Math.abs(d.move)), 0) / done.length).toFixed(2) : null;
      return {n, hits, winRate: n ? Math.round(hits / n * 100) : null, bands, avgEdge: avgMove, open: all.filter(d => d.status === "pending" && (!source || d.source === source)).length};
    },
    bySource(){ const s = {}; for (const d of read()) if (d.status === "resolved") (s[d.source] ||= {n: 0, hits: 0}), s[d.source].n++, d.hit && s[d.source].hits++;
      return Object.entries(s).map(([src, v]) => ({source: src, n: v.n, winRate: Math.round(v.hits / v.n * 100)})).sort((a, b) => b.winRate - a.winRate); },
    recent(n = 20){ return read().filter(d => d.status === "resolved").slice(-n).reverse(); },
    all(){ return read(); }, pending(){ return read().filter(d => d.status === "pending"); }
  };
}
