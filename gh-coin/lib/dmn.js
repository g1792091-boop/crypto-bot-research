// 결정표(DMN Decision Table) 계산기 — jdmn(goldmansachs) 이 실행하는 OMG DMN 표준의 결정표를 우리 앱에 맞게 작게 다시 만든 것.
// 규칙(행)마다 입력 칸에 '단항 검사(unary test)'를 쓰고, 맞은 규칙들의 출력을 '적중 정책(hit policy)'으로 합친다.
//   단항 검사 문법(FEEL 부분집합): "-" (아무거나) · "<10" "<=10" ">=1.2" ">0" · "[1..5]" "(1..5)" "]1..5[" (구간, 괄호는 열림·닫힘)
//     · "1.2" (같음) · "\"BTC\"" · "true"/"false" · "not(<3)" · "a, b, c" (여럿 중 하나)
//   적중 정책: U(UNIQUE 하나만) · F(FIRST 첫 번째) · P(PRIORITY 출력 값 우선순위) · A(ANY 모두 같은 값) · R(RULE ORDER 순서대로 모두)
//     · O(OUTPUT ORDER 우선순위순 모두) · C(COLLECT 모두) · C+ C< C> C# (합·최소·최대·개수)
// 판정 근거(어느 규칙이 맞았는지)를 함께 돌려줘서 화면과 회의에서 '왜'를 보여 준다.
const num = v => typeof v === "number" ? v : v != null && v !== "" && Number.isFinite(+v) ? +v : NaN;
function unary(test, v){
  test = String(test ?? "-").trim();
  if (test === "-" || test === "") return true;
  const nm = test.match(/^not\((.*)\)$/i); if (nm) return !unary(nm[1], v);
  // 쉼표 목록 (구간 안 쉼표는 없음)
  if (/,/.test(test) && !/^[\[\]\(]/.test(test)) return test.split(",").some(t => unary(t, v));
  let m = test.match(/^([\[\]\(])(.+)\.\.(.+)([\[\]\)])$/);
  if (m){
    const lo = num(m[2].trim()), hi = num(m[3].trim()), x = num(v); if (!Number.isFinite(x)) return false;
    const loOk = m[1] === "[" ? x >= lo : x > lo, hiOk = m[4] === "]" ? x <= hi : x < hi;
    return loOk && hiOk;
  }
  m = test.match(/^(<=|>=|<|>|=|!=)\s*(.+)$/);
  if (m){
    const r = m[2].replace(/^"(.*)"$/, "$1"), x = num(v), y = num(r);
    if (Number.isFinite(x) && Number.isFinite(y)) return {"<": x < y, "<=": x <= y, ">": x > y, ">=": x >= y, "=": x === y, "!=": x !== y}[m[1]];
    return m[1] === "=" ? String(v) === r : m[1] === "!=" ? String(v) !== r : false;
  }
  if (/^(true|false)$/i.test(test)) return String(!!v) === test.toLowerCase() || v === (test.toLowerCase() === "true");
  const s = test.replace(/^"(.*)"$/, "$1");
  return Number.isFinite(num(s)) && Number.isFinite(num(v)) ? num(s) === num(v) : String(v) === s;
}
export const unaryTest = unary;

// table: {name, hit:"U|F|P|A|R|O|C|C+|C<|C>|C#", inputs:[{key, label}], outputs:[{key, label, values?:[우선순위 높은 순]}], rules:[{when:[...], then:[...], note}]}
export function evaluate(table, ctx){
  const matched = [];
  table.rules.forEach((r, i) => { if (table.inputs.every((inp, k) => unary(r.when[k], ctx[inp.key]))) matched.push({i, rule: r, out: Object.fromEntries(table.outputs.map((o, k) => [o.key, r.then[k]]))}); });
  const hit = (table.hit || "U").toUpperCase(), o0 = table.outputs[0];
  const prio = v => { const L = o0.values || []; const i = L.indexOf(v); return i < 0 ? 1e9 : i; };
  let result = null, error = "";
  if (!matched.length) result = table.default ?? null;   // 맞은 규칙이 없으면 기본 출력
  else if (hit === "U"){ if (matched.length > 1) error = `UNIQUE 위반: 규칙 ${matched.map(m => m.i + 1).join(", ")} 이 동시에 맞음`; result = matched[0].out; }
  else if (hit === "F") result = matched[0].out;
  else if (hit === "P") result = [...matched].sort((a, b) => prio(a.out[o0.key]) - prio(b.out[o0.key]))[0].out;
  else if (hit === "A"){ const s = new Set(matched.map(m => JSON.stringify(m.out))); if (s.size > 1) error = "ANY 위반: 맞은 규칙의 출력이 서로 다름"; result = matched[0].out; }
  else if (hit === "R") result = matched.map(m => m.out);
  else if (hit === "O") result = [...matched].sort((a, b) => prio(a.out[o0.key]) - prio(b.out[o0.key])).map(m => m.out);
  else if (hit[0] === "C"){
    const vals = matched.map(m => m.out[o0.key]), ns = vals.map(num).filter(Number.isFinite);
    result = hit === "C" ? matched.map(m => m.out) : hit === "C+" ? ns.reduce((s, x) => s + x, 0) : hit === "C<" ? Math.min(...ns) : hit === "C>" ? Math.max(...ns) : hit === "C#" ? new Set(vals).size : null;
  }
  return {result, matched: matched.map(m => ({row: m.i + 1, note: m.rule.note || "", out: m.out})), error, hit};
}
// 사람이 읽는 표 (화면 카드용)
export function tableRows(table){ return table.rules.map((r, i) => [String(i + 1), ...r.when.map(x => String(x ?? "-")), ...r.then.map(x => String(x)), r.note || ""]); }
export function tableCols(table){ return ["#", ...table.inputs.map(x => x.label || x.key), ...table.outputs.map(x => "→ " + (x.label || x.key)), "근거"]; }
