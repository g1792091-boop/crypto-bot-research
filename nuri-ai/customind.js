// 누리 사용자 수식 지표: 안전한 수식 언어 (자체 토크나이저 · 파서 · 배열 계산기. eval / new Function 은 쓰지 않는다)
// - 결과는 봉마다 값 하나인 시리즈 Array<number|null> (워밍업·계산 불가 = null). 참/거짓은 1/0.
// - ind("rsi", {length:14}) 는 quant.js computeInd 를 부른다. quant.js 가 로드될 때 setIndProvider 로 연결해 준다
//   (이 파일은 quant.js 를 import 하지 않는다 → 순환 import 없음. opts.computeInd 로 직접 넘겨도 된다).
// - 의존성 없음. 브라우저와 Node 22 에서 import 로 쓴다.

const isNil = v => v === null || v === undefined;
const nulls = n => new Array(n).fill(null);
const fin = v => typeof v === "number" && Number.isFinite(v) ? v : null;    // NaN·무한대 → null
const truthy = v => !isNil(v) && v !== 0 && !Number.isNaN(v);

// 폭주 방지 한도: 식 길이 · 중첩 깊이 · 노드 수 · 기간 인자 범위 · 계산량(대략 원소 연산 수)
export const LIMITS = {maxLen: 2000, maxDepth: 40, maxNodes: 400, minWin: 1, maxWin: 2000, maxCost: 1e8};

// quant.js 연결 ({computeInd, registry}). quant.js 가 import 될 때 자동으로 호출된다
let PROVIDER = null;
export function setIndProvider(p){ PROVIDER = p && typeof p.computeInd === "function" ? p : null; }

export const BUILTIN_VARS = ["open", "high", "low", "close", "volume", "hl2", "hlc3", "ohlc4", "bar", "hour", "dow"];
const BANNED = /^(?:__\w*|constructor|prototype|toString|valueOf|hasOwnProperty)$/;   // 객체 내부 이름은 아예 막는다

function fail(msg, pos){ const e = new Error(`수식 오류 (${pos + 1}번째 글자): ${msg}`); e.pos = pos; return e; }

/* ============ 토크나이저 ============ */
const RE_WS = /\s+/y, RE_NUM = /(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?/y, RE_ID = /[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*/y;
const RE_STR = /"([\w .\-]{0,64})"|'([\w .\-]{0,64})'/y;
const OPS2 = ["&&", "||", ">=", "<=", "==", "!="], OPS1 = "+-*/^%><!?:(),{}[]";
const WORD_OPS = {and: "&&", or: "||", not: "!"};
function tokenize(src){
  const T = [];
  let i = 0;
  const at = re => { re.lastIndex = i; const m = re.exec(src); return m; };
  while (i < src.length){
    let m;
    if ((m = at(RE_WS))){ i += m[0].length; continue; }
    const pos = i;
    if ((m = at(RE_NUM))){ T.push({t: "num", v: Number(m[0]), pos}); i += m[0].length; continue; }
    if ((m = at(RE_ID))){
      const w = m[0]; i += w.length;
      if (WORD_OPS[w]) T.push({t: "op", v: WORD_OPS[w], pos});
      else if (w === "true" || w === "false") T.push({t: "num", v: w === "true" ? 1 : 0, pos});
      else if (w === "na") T.push({t: "na", pos});
      else T.push({t: "id", v: w, pos});
      continue;
    }
    if (src[i] === '"' || src[i] === "'"){
      if (!(m = at(RE_STR))) throw fail("문자열은 따옴표로 닫고 영문/숫자/_/-/. 만 64자까지 씁니다", pos);
      T.push({t: "str", v: m[1] ?? m[2], pos}); i += m[0].length; continue;
    }
    const two = src.slice(i, i + 2);
    if (OPS2.includes(two)){ T.push({t: "op", v: two, pos}); i += 2; continue; }
    if (src[i] === "=") throw fail("같다는 == 로 씁니다", pos);
    if (src[i] === "&" || src[i] === "|") throw fail(`${src[i]}${src[i]} 또는 and/or 를 쓰세요`, pos);
    if (OPS1.includes(src[i])){ T.push({t: "op", v: src[i], pos}); i++; continue; }
    throw fail(`알 수 없는 문자 '${src[i]}'`, pos);
  }
  T.push({t: "end", pos: src.length});
  return T;
}

/* ============ 함수 표 ============ */
// a: 인자 종류 문자열 (s = 시리즈, w = 기간 상수 1..2000, d = 지연 상수 0..2000, k = 횟수 상수 0..100), req: 필수 개수, vararg: s 반복
// 기간 인자는 숫자 상수(또는 상수 계산식)여야 한다. 생략된 d 는 1, k 는 0.
const FN_SPEC = {
  sma: {a: "sw", req: 2}, ema: {a: "sw", req: 2}, wma: {a: "sw", req: 2}, rma: {a: "sw", req: 2},
  stdev: {a: "sw", req: 2}, highest: {a: "sw", req: 2}, lowest: {a: "sw", req: 2}, sum: {a: "sw", req: 2},
  roc: {a: "sw", req: 2}, change: {a: "sd", req: 1}, delay: {a: "sd", req: 1}, ref: {a: "sd", req: 1},
  zscore: {a: "sw", req: 2}, rank: {a: "sw", req: 2}, percentile: {a: "sw", req: 2},
  corr: {a: "ssw", req: 3}, slope: {a: "sw", req: 2}, linreg: {a: "sw", req: 2},
  abs: {a: "s", req: 1}, sqrt: {a: "s", req: 1}, log: {a: "s", req: 1}, log10: {a: "s", req: 1}, exp: {a: "s", req: 1},
  sign: {a: "s", req: 1}, round: {a: "s", req: 1}, floor: {a: "s", req: 1}, ceil: {a: "s", req: 1}, pow: {a: "ss", req: 2},
  min: {a: "s", req: 1, vararg: true}, max: {a: "s", req: 1, vararg: true}, clamp: {a: "sss", req: 3},
  crossover: {a: "ss", req: 2}, crossunder: {a: "ss", req: 2}, barssince: {a: "s", req: 1},
  valuewhen: {a: "ssk", req: 2}, cum: {a: "s", req: 1}, nz: {a: "ss", req: 1}, iff: {a: "sss", req: 3},
  ind: {a: "", req: 1},   // 따로 검사 (문자열 · 객체 인자)
};
const FN_NAMES = Object.keys(FN_SPEC);

/* ============ 파서 ============ */
// 우선순위 (낮음→높음): ?: · or · and · == != · > < >= <= · + - · * / % · 단항 - ! not · ^ (오른쪽 결합) · x[n] · 기본
// opts.vars: 추가로 허용할 변수 이름 (배열 · Set · 함수). 기본 변수는 BUILTIN_VARS.
export function parseExpr(src, opts = {}){
  if (typeof src !== "string") throw fail("수식은 문자열이어야 합니다", 0);
  if (src.length > LIMITS.maxLen) throw fail(`수식이 너무 깁니다 (${src.length}자, 최대 ${LIMITS.maxLen}자)`, LIMITS.maxLen);
  if (!src.trim()) throw fail("빈 수식입니다", 0);
  const varOk = varChecker(opts.vars);
  const T = tokenize(src);
  let p = 0, depth = 0, nodes = 0;
  const cur = () => T[p];
  const isOp = v => T[p].t === "op" && T[p].v === v;
  const expect = v => { if (!isOp(v)) throw fail(`'${v}' 가 필요합니다`, T[p].pos); return T[p++]; };
  const mk = o => { if (++nodes > LIMITS.maxNodes) throw fail(`수식이 너무 큽니다 (요소 ${LIMITS.maxNodes}개 초과)`, o.pos); return o; };
  const enter = pos => { if (++depth > LIMITS.maxDepth) throw fail(`중첩이 너무 깊습니다 (최대 ${LIMITS.maxDepth}단계)`, pos); };
  function ternary(){
    enter(cur().pos);
    let c = binary(0);
    if (isOp("?")){ const pos = T[p++].pos; const a = ternary(); expect(":"); const b = ternary(); c = mk({k: "tern", c, a, b, pos}); }
    depth--;
    return c;
  }
  const LEVELS = [["||"], ["&&"], ["==", "!="], [">", "<", ">=", "<="], ["+", "-"], ["*", "/", "%"]];
  function binary(lv){
    if (lv >= LEVELS.length) return unary();
    let a = binary(lv + 1);
    while (T[p].t === "op" && LEVELS[lv].includes(T[p].v)){ const {v, pos} = T[p++]; a = mk({k: "bin", op: v, a, b: binary(lv + 1), pos}); }
    return a;
  }
  function unary(){
    if (isOp("-") || isOp("+") || isOp("!")){
      const {v, pos} = T[p++]; enter(pos);
      const a = unary(); depth--;
      return v === "+" ? a : mk({k: "un", op: v, a, pos});
    }
    return power();
  }
  function power(){
    const a = postfix();
    if (isOp("^")){ const pos = T[p++].pos; enter(pos); const b = unary(); depth--; return mk({k: "bin", op: "^", a, b, pos}); }
    return a;
  }
  function postfix(){
    let a = primary();
    while (isOp("[")){
      const pos = T[p++].pos, e = ternary(); expect("]");
      a = mk({k: "call", fn: "delay", args: [a, e], w: [null, win(e, pos, 0)], pos});
    }
    return a;
  }
  // 기간 인자: 숫자 상수만 (1..2000 으로 자름)
  function win(e, pos, lo = LIMITS.minWin, hi = LIMITS.maxWin){
    const v = constOf(e);
    if (v === undefined) throw fail("기간·횟수 인자는 숫자 상수여야 합니다 (예: 20)", e.pos ?? pos);
    return Math.min(hi, Math.max(lo, Math.round(v)));
  }
  function primary(){
    const tk = T[p];
    if (tk.t === "num"){ p++; return mk({k: "num", v: tk.v, pos: tk.pos}); }
    if (tk.t === "na"){ p++; return mk({k: "na", pos: tk.pos}); }
    if (tk.t === "str" || isOp("{")) throw fail("문자열·{ } 는 ind() 인자에서만 쓸 수 있습니다", tk.pos);
    if (isOp("(")){ p++; const e = ternary(); expect(")"); return e; }
    if (tk.t === "id"){
      p++;
      const name = tk.v;
      if (BANNED.test(name)) throw fail(`허용되지 않는 이름: ${name}`, tk.pos);
      if (isOp("(")) return call(name, tk.pos);
      if (Object.hasOwn(FN_SPEC, name)) throw fail(`${name} 은 함수입니다. ${name}(...) 로 부르세요`, tk.pos);
      if (!BUILTIN_VARS.includes(name) && !varOk(name))
        throw fail(`알 수 없는 변수: ${name} (가능: ${BUILTIN_VARS.join(", ")}${opts.vars ? " 와 넘겨준 시리즈" : ""})`, tk.pos);
      return mk({k: "var", name, pos: tk.pos});
    }
    if (tk.t === "end") throw fail("수식이 중간에 끝났습니다", tk.pos);
    throw fail(`예상하지 못한 '${tk.v ?? tk.t}'`, tk.pos);
  }
  function call(name, pos){
    const S = Object.hasOwn(FN_SPEC, name) ? FN_SPEC[name] : null;
    if (!S) throw fail(`알 수 없는 함수: ${name}() (가능: ${FN_NAMES.join(", ")})`, pos);
    p++;   // (
    enter(pos);
    const args = [];
    if (name === "ind"){ const node = indCall(pos); depth--; return node; }
    if (!isOp(")")){
      for (;;){ args.push(ternary()); if (isOp(",")){ p++; continue; } break; }
    }
    expect(")");
    depth--;
    const max = S.vararg ? Infinity : S.a.length;
    if (args.length < S.req || args.length > max)
      throw fail(`${name}() 인자 개수가 맞지 않습니다 (${S.req === max ? S.req : S.req + "~" + (S.vararg ? "" : max)}개, 받은 것 ${args.length}개)`, pos);
    const w = args.map((a, i) => { const kind = S.vararg ? "s" : S.a[i]; return kind === "w" ? win(a, pos) : kind === "d" ? win(a, pos, 0) : kind === "k" ? win(a, pos, 0, 100) : null; });
    return mk({k: "call", fn: name === "ref" ? "delay" : name === "percentile" ? "rank" : name, args, w, pos});
  }
  // ind("type", {k: 값, ...}, "출력") — 문자열·객체 리터럴만
  function indCall(pos){
    const lit = () => { const tk = T[p]; if (tk.t !== "str") throw fail("ind() 의 지표 종류·출력 이름은 \"문자열\" 이어야 합니다", tk.pos); p++; return tk.v; };
    const type = lit().toLowerCase();
    let params = {}, out = null;
    if (isOp(",")){
      p++;
      if (isOp("{")) params = objLit();
      else out = lit();
      if (out === null && isOp(",")){ p++; out = lit(); }
    }
    expect(")");
    if (type === "custom") throw fail("ind() 안에서 custom 은 쓸 수 없습니다 (식을 직접 쓰세요)", pos);
    const reg = PROVIDER?.registry;
    if (reg){
      if (!Object.hasOwn(reg, type)) throw fail(`ind(): 지원하지 않는 지표 "${type}"`, pos);
      if (out !== null && !reg[type].outputs.includes(out)) throw fail(`ind("${type}"): 출력 "${out}" 이 없습니다 (가능: ${reg[type].outputs.join(", ")})`, pos);
    }
    return mk({k: "ind", type, params, out, pos});
  }
  function objLit(){
    const pos = T[p++].pos, o = {};
    let cnt = 0;
    while (!isOp("}")){
      const tk = T[p];
      if (tk.t !== "id" && tk.t !== "str") throw fail("{ } 의 키는 이름이어야 합니다", tk.pos);
      if (BANNED.test(tk.v) || !/^[A-Za-z_]\w*$/.test(tk.v)) throw fail(`허용되지 않는 키: ${tk.v}`, tk.pos);
      p++; expect(":");
      const vt = T[p];
      let v;
      if (vt.t === "str"){ v = vt.v; p++; }
      else { const e = ternary(); v = constOf(e); if (v === undefined) throw fail("ind() 파라미터 값은 숫자 상수 또는 문자열이어야 합니다", vt.pos); }
      o[tk.v] = v;
      if (++cnt > 12) throw fail("ind() 파라미터가 너무 많습니다", tk.pos);
      if (isOp(",")){ p++; continue; }
      if (!isOp("}")) throw fail("',' 또는 '}' 가 필요합니다", T[p].pos);
    }
    p++;
    void pos;
    return o;
  }
  const ast = ternary();
  if (T[p].t !== "end") throw fail(`예상하지 못한 '${T[p].v ?? T[p].t}' (연산자가 빠졌나요?)`, T[p].pos);
  return ast;
}
function varChecker(v){
  if (!v) return () => false;
  if (typeof v === "function") return name => !!v(name);
  const s = v instanceof Set ? v : new Set(Array.isArray(v) ? v : Object.keys(v));
  return name => s.has(name);
}
// 상수 계산식이면 값, 아니면 undefined
function constOf(e){
  if (e.k === "num") return e.v;
  if (e.k === "un" && e.op === "-"){ const a = constOf(e.a); return a === undefined ? undefined : -a; }
  if (e.k === "bin" && "+-*/^".includes(e.op)){
    const a = constOf(e.a), b = constOf(e.b);
    if (a === undefined || b === undefined) return undefined;
    const r = e.op === "+" ? a + b : e.op === "-" ? a - b : e.op === "*" ? a * b : e.op === "/" ? a / b : a ** b;
    return Number.isFinite(r) ? r : undefined;
  }
  return undefined;
}

/* ============ 시리즈 함수 (quant.js 와 같은 공식) ============ */
// SMA: null 을 만나면 창을 비우고 다시 쌓는다 (quant.js sma 와 같은 계산 순서 → 같은 값)
function sma(x, n){
  const out = nulls(x.length), w = [];
  let s = 0, cnt = 0, head = 0;
  for (let i = 0; i < x.length; i++){
    const v = x[i];
    if (isNil(v)){ w.length = 0; head = 0; s = 0; cnt = 0; continue; }
    w.push(v); s += v; cnt++;
    if (cnt > n){ s -= w[head++]; cnt--; }
    if (cnt === n) out[i] = s / n;
  }
  return out;
}
// EMA/RMA: null 은 건너뛰고 처음 n개 평균으로 시드 (quant.js smoothed)
function smoothed(x, n, alpha){
  const out = nulls(x.length), seed = [];
  let prev = null;
  for (let i = 0; i < x.length; i++){
    const v = x[i];
    if (isNil(v)) continue;
    if (prev === null){
      seed.push(v);
      if (seed.length === n){ let s = 0; for (const q of seed) s += q; prev = s / n; out[i] = prev; }
      continue;
    }
    prev = alpha * v + (1 - alpha) * prev;
    out[i] = prev;
  }
  return out;
}
function stdev(x, n){   // 모집단 표준편차 (quant.js 와 같음)
  const m = sma(x, n), out = nulls(x.length);
  for (let i = 0; i < x.length; i++){
    if (m[i] === null) continue;
    let s = 0;
    for (let j = i - n + 1; j <= i; j++){ const d = x[j] - m[i]; s += d * d; }
    out[i] = Math.sqrt(s / n);
  }
  return out;
}
function wma(x, n){
  const d = n * (n + 1) / 2, out = nulls(x.length);
  for (let i = n - 1; i < x.length; i++){
    let s = 0, ok = true;
    for (let k = 0; k < n; k++){ const v = x[i - n + 1 + k]; if (isNil(v)){ ok = false; break; } s += v * (k + 1); }
    if (ok) out[i] = s / d;
  }
  return out;
}
// 창(i-n+1..i) 안에 null 이 없을 때만 f(i) — 아니면 null
function rolling(x, n, f){
  const L = x.length, out = nulls(L);
  let bad = 0;
  for (let i = 0; i < L; i++){
    if (isNil(x[i])) bad++;
    if (i >= n && isNil(x[i - n])) bad--;
    if (i >= n - 1 && !bad) out[i] = fin(f(i));
  }
  return out;
}
function rolling2(x, y, n, f){
  const z = x.map((v, i) => isNil(v) || isNil(y[i]) ? null : 0);
  return rolling(z, n, f);
}
const shift = (x, n) => x.map((_, i) => i >= n ? x[i - n] : null);
const map1 = (x, f) => x.map(v => isNil(v) ? null : fin(f(v)));
const mapN = (xs, f) => xs[0].map((_, i) => { const a = xs.map(x => x[i]); return a.some(isNil) ? null : fin(f(...a)); });

// 함수 구현: (args 시리즈들, w 상수들, n 봉 수) → 시리즈. cost 는 대략 연산 수 (한도 검사용)
const IMPL = {
  sma: ([x], [, n]) => sma(x, n),
  ema: ([x], [, n]) => smoothed(x, n, 2 / (n + 1)),
  rma: ([x], [, n]) => smoothed(x, n, 1 / n),
  wma: ([x], [, n]) => wma(x, n),
  stdev: ([x], [, n]) => stdev(x, n),
  highest: ([x], [, n]) => rolling(x, n, i => { let m = -Infinity; for (let j = i - n + 1; j <= i; j++) if (x[j] > m) m = x[j]; return m; }),
  lowest: ([x], [, n]) => rolling(x, n, i => { let m = Infinity; for (let j = i - n + 1; j <= i; j++) if (x[j] < m) m = x[j]; return m; }),
  sum: ([x], [, n]) => rolling(x, n, i => { let s = 0; for (let j = i - n + 1; j <= i; j++) s += x[j]; return s; }),
  roc: ([x], [, n]) => x.map((v, i) => i >= n && !isNil(v) && truthy(x[i - n]) ? fin((v / x[i - n] - 1) * 100) : null),
  change: ([x], [, n = 1]) => x.map((v, i) => i >= n && !isNil(v) && !isNil(x[i - n]) ? fin(v - x[i - n]) : null),
  delay: ([x], [, n = 1]) => shift(x, n),
  zscore: ([x], [, n]) => { const m = sma(x, n), sd = stdev(x, n); return x.map((v, i) => m[i] === null || isNil(v) ? null : sd[i] > 0 ? fin((v - m[i]) / sd[i]) : 0); },
  // 백분위 순위 (Pine ta.percentrank): 직전 n개 값 중 지금 값 이하인 비율 % (0~100)
  rank: ([x], [, n]) => rolling(x, n + 1, i => { let k = 0; for (let j = i - n; j < i; j++) if (x[j] <= x[i]) k++; return 100 * k / n; }),
  corr: ([x, y], [, , n]) => rolling2(x, y, n, i => {
    let mx = 0, my = 0; for (let j = i - n + 1; j <= i; j++){ mx += x[j]; my += y[j]; } mx /= n; my /= n;
    let sxy = 0, sxx = 0, syy = 0; for (let j = i - n + 1; j <= i; j++){ const a = x[j] - mx, b = y[j] - my; sxy += a * b; sxx += a * a; syy += b * b; }
    return sxx > 0 && syy > 0 ? sxy / Math.sqrt(sxx * syy) : null;
  }),
  // 선형회귀 기울기 (봉당 변화량) · linreg = 회귀선의 지금 봉 값 (Pine ta.linreg(x, n, 0))
  slope: ([x], [, n]) => rolling(x, n, i => linfit(x, i, n)[0]),
  linreg: ([x], [, n]) => rolling(x, n, i => { const [b, a] = linfit(x, i, n); return a + b * (n - 1); }),
  abs: ([x]) => map1(x, Math.abs), sqrt: ([x]) => map1(x, v => v < 0 ? null : Math.sqrt(v)),
  log: ([x]) => map1(x, v => v > 0 ? Math.log(v) : null), log10: ([x]) => map1(x, v => v > 0 ? Math.log10(v) : null),
  exp: ([x]) => map1(x, Math.exp), sign: ([x]) => map1(x, Math.sign), round: ([x]) => map1(x, Math.round),
  floor: ([x]) => map1(x, Math.floor), ceil: ([x]) => map1(x, Math.ceil), pow: xs => mapN(xs, Math.pow),
  min: xs => mapN(xs, Math.min), max: xs => mapN(xs, Math.max),
  clamp: xs => mapN(xs, (v, a, b) => Math.min(Math.max(v, a), b)),
  // 교차: 지금 a>b 이고 직전 a<=b 면 1, 아니면 0 (null 이 끼면 0 — quant.js crosses_above 와 같다)
  crossover: ([a, b]) => a.map((v, i) => i > 0 && !isNil(v) && !isNil(b[i]) && !isNil(a[i - 1]) && !isNil(b[i - 1]) && v > b[i] && a[i - 1] <= b[i - 1] ? 1 : 0),
  crossunder: ([a, b]) => a.map((v, i) => i > 0 && !isNil(v) && !isNil(b[i]) && !isNil(a[i - 1]) && !isNil(b[i - 1]) && v < b[i] && a[i - 1] >= b[i - 1] ? 1 : 0),
  // 조건이 마지막으로 참이었던 뒤 지난 봉 수 (그 봉이면 0, 한 번도 없으면 null)
  barssince: ([c]) => { let last = -1; return c.map((v, i) => { if (truthy(v)) last = i; return last < 0 ? null : i - last; }); },
  // 조건이 참이었던 k번째 최근 봉(0 = 가장 최근)의 x 값
  valuewhen: ([c, x], [, , k = 0]) => { const hist = []; return c.map((v, i) => { if (truthy(v)){ hist.push(isNil(x[i]) ? null : x[i]); if (hist.length > k + 1) hist.shift(); } return hist.length > k ? hist[hist.length - 1 - k] : null; }); },
  // 누적합 (null 봉은 null, 합에서는 건너뜀)
  cum: ([x]) => { let s = 0; return x.map(v => { if (isNil(v)) return null; s += v; return fin(s); }); },
  nz: ([x, y]) => x.map((v, i) => isNil(v) ? (y ? y[i] : 0) : v),
  iff: ([c, a, b]) => c.map((v, i) => isNil(v) ? null : truthy(v) ? a[i] : b[i]),
};
// 창 [i-n+1..i] 에 대한 최소제곱 직선 (x = 0..n-1) → [기울기, 절편]
function linfit(y, i, n){
  if (n < 2) return [null, null];
  const xm = (n - 1) / 2;
  let ym = 0; for (let j = i - n + 1; j <= i; j++) ym += y[j]; ym /= n;
  let sxy = 0, sxx = 0;
  for (let k = 0; k < n; k++){ const dx = k - xm; sxy += dx * (y[i - n + 1 + k] - ym); sxx += dx * dx; }
  const b = sxy / sxx;
  return [b, ym - b * xm];
}
// 창 길이에 비례하는 함수 (계산량 = 봉 수 × 창)
const WINDOWED = new Set(["stdev", "highest", "lowest", "sum", "zscore", "rank", "corr", "slope", "linreg", "wma"]);

/* ============ 계산 ============ */
const FIELD = {open: ["o", "open", 1], high: ["h", "high", 2], low: ["l", "low", 3], close: ["c", "close", 4], volume: ["v", "volume", 5], t: ["t", "time", 0]};
function column(cs, f){
  const [s, l, k] = FIELD[f];
  return cs.map(b => { const v = Array.isArray(b) ? b[k] : (b[s] ?? b[l]); return f === "volume" && isNil(v) ? 0 : isNil(v) ? null : fin(+v); });
}
const tsMs = t => Math.abs(t) < 1e11 ? t * 1000 : t;   // 초/밀리초 (quant.js 와 같은 기준)

// 외부 시리즈 맞추기: 숫자 배열이면 봉 순서대로(앞에서부터, 모자라면 null), [{t, value}] 면 시각 기준 forward-fill
function alignExtra(arr, cs){
  const n = cs.length;
  if (!Array.isArray(arr)) return nulls(n);
  const first = arr.find(v => !isNil(v));
  if (first && typeof first === "object"){
    const pts = arr.filter(p => p && !isNil(p.t ?? p.time)).map(p => ({t: tsMs(+(p.t ?? p.time)), v: p.value ?? p.v}))
      .filter(p => Number.isFinite(p.t)).sort((a, b) => a.t - b.t);
    const ts = column(cs, "t").map(t => t === null ? null : tsMs(t));
    let j = 0, last = null;
    return ts.map(t => { while (j < pts.length && t !== null && pts[j].t <= t){ last = isNil(pts[j].v) ? null : fin(+pts[j].v); j++; } return last; });
  }
  const out = nulls(n);
  for (let i = 0; i < Math.min(n, arr.length); i++){ const v = arr[i]; out[i] = isNil(v) ? null : typeof v === "boolean" ? +v : fin(+v); }
  return out;
}

// 수식 계산 → 시리즈. extra: {이름: 시리즈} (예: {ml_prob: [...], funding: [...]})
// opts: {computeInd (기본: quant.js 연결), allow(이름) → true 면 없는 시리즈도 허용(null 시리즈), ast (미리 파싱한 것)}
export function evalExpr(src, candles, extra = {}, opts = {}){
  if (!Array.isArray(candles)) throw new Error("캔들 배열이 필요합니다");
  extra = extra || {};
  const hasExtra = name => Object.hasOwn(extra, name) && !BANNED.test(name);
  const allow = typeof opts.allow === "function" ? opts.allow : () => false;
  const ast = opts.ast || parseExpr(src, {vars: name => hasExtra(name) || allow(name)});
  const n = candles.length, cache = new Map();
  let cost = 0;
  const spend = k => { cost += k; if (cost > LIMITS.maxCost) throw new Error(`수식 계산량이 너무 큽니다 (한도 ${LIMITS.maxCost.toExponential(0)}: 봉 수 × 기간을 줄이세요)`); };
  const variable = (name, pos) => {
    if (cache.has(name)) return cache.get(name);
    let v;
    switch (name){
      case "open": case "high": case "low": case "close": case "volume": v = column(candles, name); break;
      case "hl2": { const h = variable("high"), l = variable("low"); v = h.map((a, i) => isNil(a) || isNil(l[i]) ? null : (a + l[i]) / 2); break; }
      case "hlc3": { const h = variable("high"), l = variable("low"), c = variable("close"); v = mapN([h, l, c], (a, b, d) => (a + b + d) / 3); break; }
      case "ohlc4": { const o = variable("open"), h = variable("high"), l = variable("low"), c = variable("close"); v = mapN([o, h, l, c], (a, b, d, e) => (a + b + d + e) / 4); break; }
      case "bar": v = candles.map((_, i) => i); break;
      case "hour": case "dow": v = column(candles, "t").map(t => { if (t === null) return null; const d = new Date(tsMs(t)); return name === "hour" ? d.getUTCHours() : d.getUTCDay(); }); break;
      default:
        if (hasExtra(name)) v = alignExtra(extra[name], candles);
        else if (allow(name)) v = nulls(n);
        else throw fail(`알 수 없는 변수: ${name}`, pos ?? 0);
    }
    cache.set(name, v);
    return v;
  };
  const computeInd = opts.computeInd || PROVIDER?.computeInd;
  const ev = node => {
    spend(n);
    switch (node.k){
      case "num": return new Array(n).fill(fin(node.v));
      case "na": return nulls(n);
      case "var": return variable(node.name, node.pos);
      case "un": {
        const a = ev(node.a);
        return node.op === "-" ? a.map(v => isNil(v) ? null : -v) : a.map(v => truthy(v) ? 0 : 1);   // not: null 은 거짓 취급
      }
      case "bin": {
        const a = ev(node.a), b = ev(node.b), op = node.op;
        if (op === "&&") return a.map((v, i) => truthy(v) && truthy(b[i]) ? 1 : 0);   // and/or: null 은 거짓
        if (op === "||") return a.map((v, i) => truthy(v) || truthy(b[i]) ? 1 : 0);
        const f = BIN[op];
        return a.map((v, i) => isNil(v) || isNil(b[i]) ? null : fin(f(v, b[i])));
      }
      case "tern": {   // 조건이 null 이면 null
        const c = ev(node.c), a = ev(node.a), b = ev(node.b);
        return c.map((v, i) => isNil(v) ? null : truthy(v) ? a[i] : b[i]);
      }
      case "call": {
        const args = node.args.map((a, i) => node.w[i] === null || node.w[i] === undefined ? ev(a) : null);
        const w = node.w.find(v => v !== null && v !== undefined) ?? 1;
        spend(WINDOWED.has(node.fn) ? n * w : n);
        return IMPL[node.fn](args, node.w, n);
      }
      case "ind": {
        if (!computeInd) throw fail("ind() 를 쓰려면 quant.js 를 함께 불러와야 합니다", node.pos);
        const key = "ind:" + node.type + JSON.stringify(node.params);
        let res = cache.get(key);
        if (!res){ spend(n * 50); res = computeInd(candles, node.type, node.params); cache.set(key, res); }
        const out = node.out ?? ("value" in res ? "value" : Object.keys(res)[0]);
        if (!Object.hasOwn(res, out)) throw fail(`ind("${node.type}"): 출력 "${out}" 이 없습니다 (가능: ${Object.keys(res).join(", ")})`, node.pos);
        return res[out].map(v => isNil(v) ? null : fin(v));
      }
    }
    throw new Error("수식 내부 오류: " + node.k);
  };
  const out = ev(ast);
  return out.map(v => isNil(v) ? null : fin(v));
}
const BIN = {
  "+": (a, b) => a + b, "-": (a, b) => a - b, "*": (a, b) => a * b,
  "/": (a, b) => b === 0 ? null : a / b, "%": (a, b) => b === 0 ? null : a % b, "^": (a, b) => a ** b,
  ">": (a, b) => +(a > b), "<": (a, b) => +(a < b), ">=": (a, b) => +(a >= b), "<=": (a, b) => +(a <= b),
  "==": (a, b) => +(a === b), "!=": (a, b) => +(a !== b),
};

// 식이 참조하는 변수 · 함수 · ind() 목록 (검증·설명용)
export function exprRefs(src){
  const ast = typeof src === "string" ? parseExpr(src, {vars: () => true}) : src;
  const vars = new Set(), fns = new Set(), inds = [];
  const walk = e => {
    if (!e || typeof e !== "object") return;
    if (e.k === "var") vars.add(e.name);
    if (e.k === "call") fns.add(e.fn);
    if (e.k === "ind") inds.push({type: e.type, params: e.params, out: e.out});
    for (const x of [e.a, e.b, e.c, ...(e.args || [])]) walk(x);
  };
  walk(ast);
  return {vars: [...vars], fns: [...fns], inds};
}

/* ============ LLM 프롬프트용 설명 ============ */
export const CUSTOM_DOC = `사용자 수식 지표 (type "custom") — 지표를 수식으로 직접 만든다
선언: {"id": "이름", "type": "custom", "expr": "수식"} → 조건식에서 "이름" 으로 참조 (봉마다 값 1개, 참/거짓은 1/0)
- 변수: open high low close volume hl2 hlc3 ohlc4, bar(봉 번호), hour·dow(UTC 시·요일 0=일)
  · 앞에서 선언한 지표 id ("rsi", "macd.hist" 처럼), 파생 funding oi oi_change_pct long_short
  · 외부 시리즈: ml_prob(머신러닝 상승확률 0~1), ml_signal(+1/0/-1) 등 ml_*, ext_* 이름 — 데이터가 없으면 null
- 연산: + - * / ^ %, > < >= <= == !=, and or not (&& || !), 조건 ? a : b, 괄호, x[n] = n봉 전 값
- null(워밍업·데이터 없음)은 계산에 퍼진다. and/or/not 은 null 을 거짓으로 본다. 0으로 나누면 null.
- 함수 (n 은 숫자 상수 1~2000):
  sma ema wma rma stdev highest lowest sum (x,n) · roc(x,n) 변화율% · change(x,n) · delay(x,n)=ref
  zscore(x,n) · rank(x,n)=percentile 직전 n개 중 백분위 0~100 · corr(x,y,n) · slope(x,n) 회귀 기울기 · linreg(x,n) 회귀값
  abs sqrt log log10 exp sign round floor ceil, pow(a,b), min(a,b,..) max(a,b,..), clamp(x,lo,hi), nz(x,대체값=0), iff(c,a,b)
  crossover(a,b) crossunder(a,b) (1/0) · barssince(조건) · valuewhen(조건, x, k=0) · cum(x) 누적합
  ind("지표", {파라미터}, "출력") — 내장 지표 표의 아무 지표 (예: ind("rsi",{length:14}), ind("macd",{},"hist"), ind("bb",{length:20},"upper"))
- 길이 2000자 이하. 함수·변수 이름 외의 코드는 쓸 수 없다.
예시
1) 변동성 조정 모멘텀: (close - close[20]) / (ind("atr", {length:14}) * sqrt(20))
2) Z점수 평균회귀 (-2 아래면 과매도): zscore(close, 50)
3) 거래량 충격 (방향 포함): zscore(log(volume), 50) * sign(close - open)
4) 추세 강도 종합 (-1~1): (sign(close - ema(close,50)) + sign(ema(close,20) - ema(close,50)) + (ind("adx",{length:14},"adx") > 25 ? sign(slope(close,20)) : 0)) / 3
5) 20봉 신고가 돌파 후 경과 봉 수: barssince(crossover(close, highest(high, 20)[1]))
6) ML 확률 + 추세 필터 (1이면 롱 후보): ml_prob > 0.6 and close > ema(close, 200) and zscore(funding, 30) < 2
전략 예: indicators 에 {"id":"vmom","type":"custom","expr":"(close - close[20]) / (ind(\\"atr\\",{length:14}) * sqrt(20))"} → 조건 {"left":"vmom","op":"crosses_above","right":"1"}`;
