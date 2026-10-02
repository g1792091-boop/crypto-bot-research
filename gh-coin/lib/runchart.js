// 런 차트(run chart) 이동 감지 — runcharter(johnmackintosh) 의 규칙을 전략 성과 감시에 맞게 다시 만든 것.
//   ① 처음 medRows 개 점으로 기준 중앙값(baseline median)을 잡는다
//   ② 중앙값 위(또는 아래)로 runLength 개 '연속'(중앙값과 같은 점은 건너뜀)이면 지속적 이동(shift)으로 본다
//   ③ 이동이 확인되면 그 runLength 개 점으로 새 중앙값을 잡고(re-base), 그 다음부터 다시 본다
// direction: "above"(개선만) · "below"(악화만) · "both"
export function runChart(values, {medRows = 13, runLength = 9, direction = "both"} = {}){
  const v = values.filter(x => Number.isFinite(+x)).map(Number);
  const med = a => { const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
  if (v.length < medRows + runLength) return {enough: false, median: v.length ? med(v) : null, shifts: [], baselines: []};
  let base = med(v.slice(0, medRows)), start = medRows;
  const shifts = [], baselines = [{from: 0, to: medRows - 1, median: base}];
  for (;;){
    let run = 0, side = 0, runStart = -1, found = null;
    for (let i = start; i < v.length; i++){
      const s = v[i] > base ? 1 : v[i] < base ? -1 : 0;
      if (s === 0) continue;                                   // 중앙값 위의 점은 런을 끊지도 늘리지도 않는다
      if (s === side) run++; else { side = s; run = 1; runStart = i; }
      if (run >= runLength && (direction === "both" || (direction === "above" ? side > 0 : side < 0))){ found = {from: runStart, to: i, side}; break; }
    }
    if (!found) break;
    const seg = v.slice(found.from, found.to + 1), nb = med(seg);
    shifts.push({...found, oldMedian: base, newMedian: nb, dir: found.side > 0 ? "개선(위로 이동)" : "악화(아래로 이동)"});
    base = nb; baselines.push({from: found.from, to: found.to, median: nb}); start = found.to + 1;
  }
  return {enough: true, median: base, shifts, baselines, last: shifts.at(-1) || null};
}
