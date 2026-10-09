// 🔬 지표 최적화 백테스트 작업자(Web Worker) — 화면이 멈추지 않게 따로 계산. 계산은 lib/comboopt.js 그대로(도구와 같은 함수).
// 받는 것: { k15: {t,o,h,l,c,v}, k60: {…}, tfs, opt: {sym, ko, B, span, levs, combos, bestLevs} } → 보내는 것: prog / done / err
import * as CB from "./combos.js";
import * as OPTM from "./comboopt.js";

const rows = c => { const n = c.t.length, out = new Array(n); for (let i = 0; i < n; i++) out[i] = { t: c.t[i], o: c.o[i], h: c.h[i], l: c.l[i], c: c.c[i], v: c.v[i] }; return out; };
self.onmessage = async ev => {
  const q = ev.data;
  try {
    const d = {};
    if (q.k15) { const c15 = rows(q.k15); if (q.tfs.includes("15")) d["15"] = c15; if (q.tfs.includes("30")) d["30"] = CB.agg30(c15); }
    if (q.k60 && q.tfs.includes("60")) d["60"] = rows(q.k60);
    const r = await OPTM.optimizeCoin({ ...q.opt, tfs: q.tfs, data: d, tick: (f, msg) => self.postMessage({ type: "prog", f, msg }) });
    self.postMessage({ type: "done", r, bars: Object.fromEntries(Object.entries(d).map(([k, v]) => [k, v.length])) });
  } catch (e) { self.postMessage({ type: "err", msg: String(e?.message || e) }); }
};
