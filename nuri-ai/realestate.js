// 재개발·재건축 후보지 발굴과 부동산 자체 지표
// 웹 검색으로 지역별 정비사업 근거(지정·해제·신통기획·모아타운·조합·관리처분·교통 호재)를 모으고,
// AI가 근거에서 후보지 JSON을 뽑으면(EXTRACT_PROMPT) 코드가 '재개발 잠재력 지수'로 점수를 매겨 연구 노트(IndexedDB "re:")에 쌓는다.
// AI는 여기서 부르지 않는다(사무실이 부른다). 시험할 때는 opts.search · opts.fetchText · opts.fetchJson · opts.store 를 주입한다.
// 숫자는 모두 코드가 계산하고, AI에게는 짧은 한국어 설명(text)과 한 줄 요약(summary), 출처(sources)만 넘긴다.

/* ============ 공용: 엔진(브라우저 전용)은 늦게 불러온다 ============ */
let ENG = null;
const engine = async () => { if (ENG === null){ try { ENG = await import("./engine.js"); } catch(e){ ENG = false; } } return ENG || null; };
async function io(o = {}){
  const E = (o.search && o.fetchText && o.fetchJson) ? null : await engine();
  const need = n => { throw new Error(`${n} 를 쓸 수 없습니다 (엔진 없음 — 시험에서는 opts.${n} 를 주입)`); };
  return {
    search: o.search || (E ? E.webSearch : () => need("search")),
    fetchText: o.fetchText || (E ? u => E.webGet(u, "text") : () => need("fetchText")),
    fetchJson: o.fetchJson || (E ? u => E.webGet(u, "json") : () => need("fetchJson"))
  };
}
const MEM = new Map();
const memStore = {async put(k, v){ MEM.set(k, v); }, async del(k){ MEM.delete(k); }, async all(p){ return [...MEM].filter(([k]) => k.startsWith(p)).map(([, v]) => v); }};
async function storeOf(o = {}){ if (o.store) return o.store; const E = await engine(); return E?.idb || memStore; }
// 동시에 k개씩만 요청한다 (검색엔진 차단 방지)
async function pool(items, k, fn){
  const out = new Array(items.length); let i = 0;
  await Promise.all(Array.from({length: Math.min(k, items.length)}, async () => { while (i < items.length){ const j = i++; try { out[j] = await fn(items[j], j); } catch(e){ out[j] = {error: e}; } } }));
  return out;
}
const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
const r1 = x => Math.round(x * 10) / 10;
const DAY = 864e5;

/* ============ 지역: 서울 25개 구 + 경기·인천 주요 도시 (lawd = 실거래가 법정동코드 앞 5자리) ============ */
const SEOUL = [["종로구", "11110"], ["중구", "11140"], ["용산구", "11170"], ["성동구", "11200"], ["광진구", "11215"], ["동대문구", "11230"], ["중랑구", "11260"], ["성북구", "11290"], ["강북구", "11305"], ["도봉구", "11320"], ["노원구", "11350"], ["은평구", "11380"], ["서대문구", "11410"], ["마포구", "11440"], ["양천구", "11470"], ["강서구", "11500"], ["구로구", "11530"], ["금천구", "11545"], ["영등포구", "11560"], ["동작구", "11590"], ["관악구", "11620"], ["서초구", "11650"], ["강남구", "11680"], ["송파구", "11710"], ["강동구", "11740"]];
// 경기·인천 코드는 참고용. 구 개편(예: 부천 2024년 구 재설치)으로 바뀌었을 수 있으니 결과가 비면 lawd_cd 를 직접 준다
const GG = [["성남시", [["수정구", "41131"], ["중원구", "41133"], ["분당구", "41135"]]], ["수원시", [["장안구", "41111"], ["권선구", "41113"], ["팔달구", "41115"], ["영통구", "41117"]]], ["용인시", [["처인구", "41461"], ["기흥구", "41463"], ["수지구", "41465"]]],
  ["고양시", [["덕양구", "41281"], ["일산동구", "41285"], ["일산서구", "41287"]]], ["부천시", [["", "41190"]]], ["안양시", [["만안구", "41171"], ["동안구", "41173"]]], ["광명시", [["", "41210"]]], ["과천시", [["", "41290"]]],
  ["하남시", [["", "41450"]]], ["구리시", [["", "41310"]]], ["의왕시", [["", "41430"]]], ["군포시", [["", "41410"]]]];
const IC = [["미추홀구", "28177"], ["연수구", "28185"], ["남동구", "28200"], ["부평구", "28237"], ["계양구", "28245"], ["서구", "28260"], ["중구", "28110"], ["동구", "28140"]];
export const REGIONS = [
  ...SEOUL.map(([name, c]) => ({name, full: "서울 " + name, sido: "서울", lawd: [c]})),
  ...GG.map(([name, subs]) => ({name, full: "경기 " + name, sido: "경기", lawd: subs.map(x => x[1])})),
  ...GG.flatMap(([city, subs]) => subs.filter(x => x[0]).map(([g, c]) => ({name: g, city, full: `경기 ${city} ${g}`, sido: "경기", lawd: [c], sub: true}))),
  ...IC.map(([name, c]) => ({name, full: "인천 " + name, sido: "인천", lawd: [c]}))
];
export const SEOUL_LAWD = Object.fromEntries(SEOUL);
// "성북", "성북구", "서울 성북구", "인천 서구", "성남 분당구", "분당" → 지역 항목 (같은 이름(중구·서구)은 시·도를 보고 고른다. 없으면 서울 우선)
export function findRegion(q){
  const s = String(q || "").replace(/\s+/g, " ").trim();
  if (!s) return null;
  const sido = /^인천/.test(s) ? "인천" : /^경기/.test(s) ? "경기" : /^서울/.test(s) ? "서울" : "";
  const body = s.replace(/^(서울|경기|인천)(특별시|광역시|도)?\s*/, ""), bare = x => x.replace(/[구시]$/, "");
  const words = body.split(" "), cityHit = words.length > 1 ? REGIONS.find(r => r.sub && bare(r.city) === bare(words[0]) && bare(r.name) === bare(words[1])) : null;
  if (cityHit) return cityHit;
  const hit = REGIONS.filter(r => (!sido || r.sido === sido) && (r.name === words[0] || bare(r.name) === bare(words[0])));
  return hit.find(r => !r.sub) || hit[0] || null;
}

/* ============ 1. 근거 수집 ============ */
// 지역마다 돌리는 검색어 (2025년부터 '안전진단'은 '재건축진단'으로 이름이 바뀌어 둘 다 넣는다)
export const SIGNALS = {
  정비구역: "재개발 정비구역 지정", 해제: "정비구역 해제 직권해제", 신통: "신속통합기획 후보지 선정", 모아타운: "모아타운 선정 관리계획",
  공공: "공공재개발 후보지", 안전진단: "재건축 안전진단 재건축진단 통과", 조합: "재개발 재건축 조합설립인가", 관리처분: "관리처분인가 이주",
  역세권: "역세권 개발 역세권 활성화사업", 교통: "GTX 신설역 개통 착공"
};
// 검색 결과 날짜·스니펫 속 날짜 → "YYYY-MM-DD" (모르면 "")
export function parseDate(s, now = Date.now()){
  s = String(s || "").trim(); if (!s) return "";
  const iso = d => isNaN(d) ? "" : new Date(d).toISOString().slice(0, 10);
  let m = s.match(/(20\d\d)\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})/);
  if (m) return `${m[1]}-${m[2].padStart(2, "0")}-${m[3].padStart(2, "0")}`;
  m = s.match(/(\d+)\s*(분|시간|일|주|개월|달|년)\s*전/) || s.match(/(\d+)\s*(minute|hour|day|week|month|year)s?\s*ago/i);
  if (m){ const u = {분: 6e4, minute: 6e4, 시간: 36e5, hour: 36e5, 일: DAY, day: DAY, 주: 7 * DAY, week: 7 * DAY, 개월: 30 * DAY, 달: 30 * DAY, month: 30 * DAY, 년: 365 * DAY, year: 365 * DAY}[m[2].toLowerCase()]; return iso(now - m[1] * u); }
  if (/^\d{4}-\d\d-\d\dT/.test(s)) return s.slice(0, 10);
  m = s.match(/^(20\d\d)-(\d\d)$/); if (m) return `${m[1]}-${m[2]}-01`;
  const t = Date.parse(s); return /20\d\d/.test(s) && !isNaN(t) ? iso(t) : "";
}
const normUrl = u => { try { const x = new URL(u); x.hash = ""; [...x.searchParams.keys()].filter(k => /^(utm_|fbclid|gclid|ref$)/.test(k)).forEach(k => x.searchParams.delete(k)); return x.href.replace(/\/$/, ""); } catch(e){ return String(u || ""); } };

// 지역별로 정비사업 신호 검색 → 근거 목록 {region, query, title, url, snippet, date} (주소 중복 제거, 날짜 최신순)
export async function gatherRedev({region, signals, n = 6, maxChars = 7000, now = Date.now(), ...o} = {}){
  const {search} = await io(o);
  const regs = [].concat(region || "서울").map(r => findRegion(r) || {name: String(r), full: String(r)});
  const sig = (signals?.length ? signals : Object.keys(SIGNALS)).map(k => SIGNALS[k] || String(k));
  const jobs = []; for (const r of regs) for (const q of sig) jobs.push({r, q: `${r.full} ${q}`});
  const res = await pool(jobs, o.concurrency || 3, j => search(j.q, n));
  const seen = new Map(), items = [], errors = [];
  res.forEach((r, i) => {
    if (!r || r.error){ errors.push(jobs[i].q); return; }
    for (const x of r.results || []){
      if (!/^https?:/.test(x.url || "")) continue;
      const key = normUrl(x.url), date = parseDate(x.date, now) || parseDate(x.snippet, now) || parseDate(x.title, now);
      const prev = seen.get(key);
      if (prev){ if (!prev.date && date) prev.date = date; if (!prev.queries.includes(jobs[i].q)) prev.queries.push(jobs[i].q); continue; }
      const it = {region: jobs[i].r.full, query: jobs[i].q, queries: [jobs[i].q], title: String(x.title || "").trim().slice(0, 160), url: x.url, snippet: String(x.snippet || "").replace(/\s+/g, " ").trim().slice(0, 300), date};
      seen.set(key, it); items.push(it);
    }
  });
  items.sort((a, b) => (b.date || "").localeCompare(a.date || ""));
  return {items, errors, text: evidenceText(items, maxChars), sources: items.map(x => ({title: x.title, url: x.url}))};
}
// AI에게 줄 근거 묶음: [번호] (날짜) 제목 — 요약 / 주소
export function evidenceText(items, maxChars = 7000){
  let out = "";
  for (let i = 0; i < items.length; i++){
    const x = items[i], line = `[${i + 1}] ${x.date ? "(" + x.date + ") " : ""}${x.title}${x.snippet ? " — " + x.snippet.slice(0, 180) : ""}\n${x.url}\n`;
    if (out.length + line.length > maxChars){ out += `…(나머지 ${items.length - i}건 생략)`; break; }
    out += line;
  }
  return out.trim();
}

/* ============ 2. 후보지 추출 (AI 지시문 + 코드 검증) ============ */
export const PROJECT_TYPES = ["재개발", "재건축", "모아타운", "신속통합기획", "공공재개발", "가로주택", "역세권"];
export const STAGES = ["후보지", "구역지정", "조합설립", "사업시행", "관리처분", "이주·철거", "착공"];
export const EXTRACT_PROMPT = `아래 [근거]는 재개발·재건축 관련 검색 결과다. 근거에 실제로 나온 사업 구역만 골라 JSON 배열 하나로만 답한다.
형식: [{"area":"동 또는 구역 이름(예: 장위15구역, 신림1구역, 상계주공5단지)","region":"시·구(예: 서울 성북구)","project_type":"재개발|재건축|모아타운|신속통합기획|공공재개발|가로주택|역세권","stage":"후보지|구역지정|조합설립|사업시행|관리처분|이주·철거|착공","date":"가장 최근 근거 날짜 YYYY-MM-DD(모르면 빈 문자열)","signals":["근거에 나온 사실: 신통기획 선정, 안전진단 통과, GTX 역 등"],"positives":["호재"],"risks":["해제, 주민 갈등·비대위, 분담금·공사비 증액, 소송, 토지거래허가·규제지역 등"],"evidence_urls":["근거의 주소를 그대로"]}]
규칙:
- 근거에 없는 구역·단계·숫자는 만들지 않는다. 확실하지 않은 단계는 가장 이른 단계(후보지)로 적는다.
- evidence_urls 에는 그 구역을 직접 언급한 근거의 주소만 넣는다(최소 1개). 주소를 모르면 그 구역은 뺀다.
- 해제·취소·무산 소식은 risks 에 반드시 적는다. 광고성 분양 글, 지역 일반 뉴스는 뺀다.
- 같은 구역은 한 번만 적고 근거를 합친다. 설명 문장 없이 JSON 배열만 출력한다.`;

const TYPE_SYN = [[/신속\s*통합|신통/, "신속통합기획"], [/모아\s*타운|모아주택|소규모\s*주택\s*정비\s*관리/, "모아타운"], [/공공\s*(재개발|재건축)|공공\s*정비/, "공공재개발"], [/가로\s*주택|소규모\s*재건축/, "가로주택"], [/역세권/, "역세권"], [/재건축/, "재건축"], [/재개발|재정비|뉴타운|정비/, "재개발"]];
const STAGE_SYN = [[/착공|공사\s*중|준공|분양/, "착공"], [/이주|철거/, "이주·철거"], [/관리\s*처분/, "관리처분"], [/사업\s*시행|시행\s*인가/, "사업시행"], [/조합\s*설립/, "조합설립"], [/구역\s*지정|추진\s*위|정비\s*구역|정비\s*계획|지정\s*고시|결정\s*고시/, "구역지정"], [/후보|선정|예정|검토|추진|신청|공모|제안/, "후보지"]];
const normType = t => { t = String(t || "").trim(); if (PROJECT_TYPES.includes(t)) return t; for (const [re, v] of TYPE_SYN) if (re.test(t)) return v; return ""; };
const normStage = s => { s = String(s || "").trim(); if (STAGES.includes(s)) return s; for (const [re, v] of STAGE_SYN) if (re.test(s)) return v; return ""; };
const strArr = (v, max = 8) => [].concat(v ?? []).map(x => typeof x === "string" ? x.trim() : typeof x === "number" ? String(x) : "").filter(Boolean).slice(0, max);
// 문자열 안을 건너뛰며 짝 맞는 괄호까지 자른다
function sliceBalanced(s, start){
  const open = s[start], close = open === "[" ? "]" : "}"; let depth = 0, inStr = false, q = "";
  for (let i = start; i < s.length; i++){
    const c = s[i];
    if (inStr){ if (c === "\\"){ i++; continue; } if (c === q) inStr = false; continue; }
    if (c === '"'){ inStr = true; q = c; continue; }
    if (c === open) depth++; else if (c === close && --depth === 0) return s.slice(start, i + 1);
  }
  return null;
}
const lenientParse = s => { try { return JSON.parse(s); } catch(e){} try { return JSON.parse(s.replace(/[“”]/g, '"').replace(/[‘’]/g, "'").replace(/\/\/[^\n"]*\n/g, "\n").replace(/,\s*([\]}])/g, "$1")); } catch(e){ return undefined; } };
// AI 답(코드 블록·앞뒤 설명 섞여도 됨) → 검증된 후보 배열. opts.evidence(근거 목록)를 주면 근거에 없는 주소는 버리고 [3] 같은 번호를 주소로 바꾼다
// strict(기본 true): 근거 목록에 없는 주소는 버리고, 주소가 하나도 안 남은 후보도 버린다
export function parseCandidates(text, {evidence, strict = true} = {}){
  if (Array.isArray(text)) return validate(text, evidence, strict);
  let s = String(text || "").replace(/<think>[\s\S]*?<\/think>/g, "");
  const fence = [...s.matchAll(/```(?:json)?\s*([\s\S]*?)```/g)].map(m => m[1]);
  const tries = [...fence, s];
  for (const t of tries){
    for (let i = 0; i < t.length; i++){
      if (t[i] !== "[" && t[i] !== "{") continue;
      const chunk = sliceBalanced(t, i); if (!chunk) continue;
      const v = lenientParse(chunk);
      if (v === undefined) continue;
      const arr = Array.isArray(v) ? v : Array.isArray(v?.candidates) ? v.candidates : v && typeof v === "object" && v.area ? [v] : null;
      if (arr && arr.some(x => x && typeof x === "object")) return validate(arr, evidence, strict);
      i += chunk.length - 1;
    }
  }
  return [];
}
function validate(arr, evidence, strict = true){
  const ev = evidence?.length ? evidence : null, urlSet = ev ? new Set(ev.map(x => normUrl(x.url))) : null, seen = new Set(), out = [];
  for (const c of arr){
    if (!c || typeof c !== "object" || Array.isArray(c)) continue;
    const area = String(c.area || c.name || "").trim().slice(0, 60);
    if (!area || area.length < 2) continue;
    let urls = strArr(c.evidence_urls ?? c.sources ?? c.urls, 12).map(u => { const k = u.match(/^\[?(\d+)\]?$/); return k && ev ? ev[k[1] - 1]?.url || "" : u; }).filter(u => /^https?:\/\//.test(u));
    if (urlSet && strict) urls = urls.filter(u => urlSet.has(normUrl(u)));
    urls = [...new Set(urls)];
    if (ev && strict && !urls.length) continue;                       // 근거 없는 후보는 버린다(지어낸 것일 수 있음)
    const stage = normStage(c.stage), region = String(c.region || "").trim().slice(0, 30);
    const key = (region + "|" + area).replace(/\s+/g, ""); if (seen.has(key)) continue; seen.add(key);
    out.push({area, region, project_type: normType(c.project_type || c.type) || "재개발", stage: stage || "후보지", ...(stage ? {} : {stage_unknown: true}),
      date: parseDate(c.date) || "", signals: strArr(c.signals), positives: strArr(c.positives), risks: strArr(c.risks), evidence_urls: urls});
  }
  return out;
}

/* ============ 3. 재개발 잠재력 지수 (코드가 계산) ============ */
// 확실성(사업이 끝까지 갈 가능성)과 상승여력(아직 가격에 덜 반영된 정도)을 따로 0~100으로 매기고 가중 평균한다.
// 단계가 늦을수록 확실성↑ 상승여력↓. 근거 수·최신성은 확실성에, 정책(신통·모아타운·공공)은 둘 다, 교통 호재는 상승여력에, 위험은 감점.
// 고치려면 REDEV_INDEX 의 숫자·키워드를 바꾼다 (weights.certainty + weights.upside = 1).
export const REDEV_INDEX = {
  name: "재개발 잠재력 지수",
  weights: {certainty: 0.5, upside: 0.5},
  stageCertainty: {후보지: 15, 구역지정: 35, 조합설립: 50, 사업시행: 65, 관리처분: 80, "이주·철거": 90, 착공: 95},
  stageUpside: {후보지: 90, 구역지정: 78, 조합설립: 65, 사업시행: 52, 관리처분: 38, "이주·철거": 25, 착공: 12},
  evidence: {perUrl: 3, max: 12, none: -10},
  recency: [[90, 8], [180, 5], [365, 2], [730, 0], [Infinity, -6]],      // [며칠 이내, 확실성 점수]
  policy: [
    {k: "신속통합기획", re: /신속\s*통합|신통/, cert: 8, up: 6},
    {k: "모아타운", re: /모아\s*타운|모아주택/, cert: 6, up: 6},
    {k: "공공 시행", re: /공공\s*(재개발|재건축|정비)|LH|SH공사|주택도시공사/, cert: 8, up: 3},
    {k: "안전진단 통과", re: /(안전진단|재건축\s*진단).{0,6}(통과|적정|D등급|E등급|조건부)/, cert: 6, up: 0},
    {k: "정비계획 수립", re: /정비\s*계획.{0,6}(수립|결정|고시|입안)/, cert: 4, up: 0}
  ],
  policyCap: {cert: 15, up: 10},
  transport: [
    {k: "GTX", re: /GTX/i, up: 10}, {k: "신설역·연장선", re: /신설\s*역|신안산선|연장\s*선?|경전철|트램|위례신사|동북선|서부선|면목선|강북횡단/, up: 6},
    {k: "역세권", re: /역세권|도보\s*\d+\s*분|초역세권/, up: 4}
  ],
  transportCap: 14,
  risks: [
    {k: "해제·무산", re: /해제|취소|철회|무산|좌초|백지화|일몰/, sig: /(구역|정비|지정|후보지?|선정)\s*(해제|취소|철회)|직권\s*해제|무산|좌초|백지화/, cert: -25, up: -10},
    {k: "주민 갈등", re: /갈등|반대|비대위|비상대책|내홍|동의율\s*(부족|미달)|해임/, cert: -8, up: 0},
    {k: "소송", re: /소송|무효|가처분|행정심판|패소/, cert: -10, up: 0},
    {k: "분담금·공사비", re: /분담금|공사비\s*(증액|인상|갈등)|추가\s*부담|사업성\s*(부족|악화|낮)/, cert: -4, up: -8},
    {k: "거래 규제", re: /토지\s*거래\s*허가|규제\s*지역|투기\s*과열|조정\s*대상|실거주\s*의무/, cert: 0, up: -5},
    {k: "지분 쪼개기·권리산정", re: /지분\s*쪼개기|권리\s*산정|현금\s*청산/, cert: 0, up: -4}
  ],
  riskCap: {cert: -40, up: -25}
};
// 후보 하나 → {score, certainty, upside, breakdown:[{factor, points, cert, up, why}]} (breakdown 의 points 합 = score)
export function scoreCandidate(c, {now = Date.now(), index = REDEV_INDEX} = {}){
  const W = index.weights, wc = W.certainty / (W.certainty + W.upside), wu = 1 - wc;
  const rows = [], add = (factor, cert, up, why) => rows.push({factor, cert, up, why});
  const stage = STAGES.includes(c.stage) ? c.stage : "후보지";
  add("사업 단계", index.stageCertainty[stage], index.stageUpside[stage], `${stage}${c.stage_unknown ? "(단계 불명 → 후보지로 봄)" : ""}: 늦을수록 확실성↑ 상승여력↓`);
  // 근거 수 (노트에 쌓인 근거 포함)
  const urls = new Set([...(c.evidence_urls || []), ...(c.evidence || []).map(e => e.url)].filter(Boolean)), nU = urls.size;
  add("근거 수", nU ? Math.min(index.evidence.max, nU * index.evidence.perUrl) : index.evidence.none, 0, nU ? `근거 ${nU}건` : "근거 주소 없음");
  // 최신성: 후보 날짜·근거 날짜 중 가장 최근
  const dates = [c.date, c.last_date, ...(c.evidence || []).map(e => e.date)].map(d => Date.parse(d || "")).filter(t => !isNaN(t));
  if (dates.length){
    const age = (now - Math.max(...dates)) / DAY, pts = index.recency.find(([d]) => age <= d)[1];
    add("근거 최신성", pts, 0, `가장 최근 근거 ${new Date(Math.max(...dates)).toISOString().slice(0, 10)} (${Math.max(0, Math.round(age))}일 전)`);
  } else add("근거 최신성", 0, 0, "날짜 모름");
  // 정책·교통·위험은 글자에서 찾는다 (같은 요인은 한 번만)
  const good = [c.project_type, ...(c.signals || []), ...(c.positives || [])].join(" · "), bad = [...(c.risks || [])].join(" · ");
  let pc = 0, pu = 0; const pol = [];
  for (const p of index.policy) if (p.re.test(good)){ pc += p.cert; pu += p.up; pol.push(p.k); }
  if (pol.length) add("정책 신호", Math.min(pc, index.policyCap.cert), Math.min(pu, index.policyCap.up), pol.join(", "));
  let tu = 0; const tr = [];
  for (const t of index.transport) if (t.re.test(good)){ tu += t.up; tr.push(t.k); }
  if (tr.length) add("교통 호재", 0, Math.min(tu, index.transportCap), tr.join(", "));
  let rc = 0, ru = 0; const rk = [];
  // 위험은 risks 글에서 찾고, 해제·무산처럼 치명적인 것은 signals 에 적혀 있어도 잡는다 ('토지거래허가 해제' 같은 호재는 제외)
  for (const r of index.risks) if (r.re.test(bad) || (r.sig && r.sig.test((c.signals || []).join(" · ")))){ rc += r.cert; ru += r.up; rk.push(r.k); }
  if (rk.length) add("위험 감점", Math.max(rc, index.riskCap.cert), Math.max(ru, index.riskCap.up), rk.join(", "));
  // 확실성·상승여력은 0~100으로 자르고, 자른 만큼은 '범위 보정'으로 적어 합이 맞게 한다
  const rawC = rows.reduce((a, r) => a + r.cert, 0), rawU = rows.reduce((a, r) => a + r.up, 0);
  const certainty = clamp(rawC, 0, 100), upside = clamp(rawU, 0, 100);
  if (certainty !== rawC || upside !== rawU) add("범위 보정(0~100)", certainty - rawC, upside - rawU, "확실성·상승여력은 0~100 사이로 자름");
  const breakdown = rows.map(r => ({factor: r.factor, points: r1(wc * r.cert + wu * r.up), cert: r.cert, up: r.up, why: r.why}));
  const score = r1(breakdown.reduce((a, b) => a + b.points, 0));
  return {score, certainty: r1(certainty), upside: r1(upside), breakdown};
}
// 점수 높은 순 정렬 (각 후보에 index 를 붙인다)
export const rankCandidates = (list, opts = {}) => (list || []).map(c => ({...c, index: scoreCandidate(c, opts)})).sort((a, b) => b.index.score - a.index.score || b.index.certainty - a.index.certainty);

/* ============ 4. 연구 노트 (IndexedDB "re:cand:") ============ */
const PREFIX = "re:cand:";
const keyOf = c => PREFIX + (String(c.region || "") + "|" + String(c.area || "")).replace(/\s+/g, "");
const union = (a = [], b = [], max = 12) => [...new Set([...a, ...b])].slice(-max);
// 같은 구역(지역+이름)은 합치고, 단계 변화·새 근거·새 위험은 날짜와 함께 history 에 남긴다. opts.evidence 를 주면 근거 날짜를 붙인다
export async function saveCandidates(list, {now = Date.now(), evidence = [], ...o} = {}){
  const store = await storeOf(o), old = new Map((await store.all(PREFIX)).map(c => [keyOf(c), c])), dateOf = new Map(evidence.map(e => [normUrl(e.url), e]));
  const out = [];
  for (const c of list || []){
    if (!c?.area) continue;
    const k = keyOf(c), p = old.get(k), ev = (c.evidence_urls || []).map(u => ({url: u, date: dateOf.get(normUrl(u))?.date || "", title: dateOf.get(normUrl(u))?.title || ""}));
    let m;
    if (!p) m = {...c, evidence: ev, first_seen: now, updated: now, history: [{t: now, what: "처음 발견", stage: c.stage, urls: c.evidence_urls || []}]};
    else {
      const h = [...(p.history || [])], known = new Set((p.evidence || []).map(e => normUrl(e.url)));
      const newEv = ev.filter(e => !known.has(normUrl(e.url))), newRisk = (c.risks || []).filter(r => !(p.risks || []).includes(r));
      const later = STAGES.indexOf(c.stage) > STAGES.indexOf(p.stage);
      // 단계는 근거가 '더 진행됨'을 말할 때만 올린다 (단계 불명 추출로 되돌리지 않는다)
      const takeC = !!(c.stage && !c.stage_unknown && (later || p.stage_unknown)), stage = takeC ? c.stage : p.stage;
      if (stage !== p.stage) h.push({t: now, what: "단계 변화", from: p.stage, to: stage});
      if (newEv.length) h.push({t: now, what: "새 근거", urls: newEv.map(e => e.url)});
      if (newRisk.length) h.push({t: now, what: "새 위험", risks: newRisk});
      m = {...p, project_type: c.project_type || p.project_type, stage, stage_unknown: takeC ? false : p.stage_unknown,
        date: [p.date, c.date].filter(Boolean).sort().pop() || "", signals: union(p.signals, c.signals), positives: union(p.positives, c.positives), risks: union(p.risks, c.risks),
        evidence_urls: union(p.evidence_urls, c.evidence_urls, 20), evidence: [...(p.evidence || []), ...newEv].slice(-20), updated: now, history: h.slice(-30)};
      if (!m.stage_unknown) delete m.stage_unknown;
    }
    await store.put(k, m); old.set(k, m); out.push(m);
  }
  return out;
}
export async function loadCandidates(o = {}){ return (await (await storeOf(o)).all(PREFIX)).filter(c => c && c.area); }
export async function removeCandidate(c, o = {}){ await (await storeOf(o)).del(keyOf(c)); }
const host = u => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch(e){ return ""; } };
// 순위 목록 (2,000자 미만): 지수·확실성·상승여력·핵심 신호·위험·출처
export function candidateText(list, n = 10, opts = {}){
  const ranked = (list || []).length && list[0]?.index ? list : rankCandidates(list, opts);
  if (!ranked.length) return "저장된 재개발 후보지가 없습니다. redev_scan 으로 지역 근거를 모은 뒤 후보를 뽑아 redev_rank 에 candidates 로 넘기면 저장됩니다.";
  const head = `[${REDEV_INDEX.name}] 0~100 · 확실성 ${REDEV_INDEX.weights.certainty * 100}% + 상승여력 ${REDEV_INDEX.weights.upside * 100}% (검색 근거 기반 추정, 투자 권유 아님)\n`;
  const lines = ranked.slice(0, n).map((c, i) => {
    const x = c.index, sig = [...(c.signals || []), ...(c.positives || [])].slice(0, 3).join(", "), rk = (c.risks || []).slice(0, 2).join(", "), src = (c.evidence_urls || []).slice(0, 2).map(host).filter(Boolean).join(" ");
    return `${i + 1}. ${c.region ? c.region + " " : ""}${c.area} (${c.project_type}·${c.stage}) 지수 ${Math.round(x.score)} [확실성 ${Math.round(x.certainty)}·상승여력 ${Math.round(x.upside)}] 근거 ${(c.evidence_urls || []).length}건${sig ? " · " + sig : ""}${rk ? " / 위험: " + rk : ""}${src ? " · " + src : ""}`;
  });
  let out = head; for (const l of lines){ const s = l.length > 230 ? l.slice(0, 228) + "…" : l; if (out.length + s.length + 1 > 1950) break; out += s + "\n"; }
  return out.trim();
}
// 지수 설명과 고치는 법
export function customIndicatorText(index = REDEV_INDEX){
  const st = STAGES.map(s => `${s} ${index.stageCertainty[s]}/${index.stageUpside[s]}`).join(", ");
  return `[${index.name}] 검색 근거로 뽑은 정비사업 후보지에 코드가 매기는 0~100 점수.
- 확실성(끝까지 갈 가능성)과 상승여력(아직 덜 반영된 정도)을 따로 0~100으로 계산하고 ${index.weights.certainty}:${index.weights.upside} 로 섞는다.
- 단계(확실성/상승여력): ${st}.
- 근거: 주소 1건당 확실성 +${index.evidence.perUrl}(최대 +${index.evidence.max}), 근거 없음 ${index.evidence.none}. 최신성: 90일 이내 +8, 180일 +5, 1년 +2, 2년 넘으면 -6.
- 정책: ${index.policy.map(p => `${p.k}(+${p.cert}/+${p.up})`).join(", ")} (합계 상한 +${index.policyCap.cert}/+${index.policyCap.up}).
- 교통(상승여력): ${index.transport.map(t => `${t.k} +${t.up}`).join(", ")} (상한 +${index.transportCap}).
- 위험: ${index.risks.map(r => `${r.k}(${r.cert}/${r.up})`).join(", ")} (하한 ${index.riskCap.cert}/${index.riskCap.up}).
- 점수표(breakdown)의 합이 곧 지수다. 실수요라면 확실성 비중을, 초기 투자라면 상승여력 비중을 올린다(REDEV_INDEX.weights). 단계표·키워드·상한도 REDEV_INDEX 에서 바꾼다.
- 한계: 검색 요약에 의존하므로 구역 경계·동의율·권리산정기준일·분담금은 정비사업 정보몽땅(cleanup.seoul.go.kr)·구청 고시로 꼭 확인한다.`;
}

/* ============ 5. (선택) 공공데이터: 국토부 아파트 매매 실거래가 ============ */
const RTMS = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade";
export const KEY_NOTE = "실거래가 조회에는 공공데이터포털(data.go.kr) 인증키가 필요합니다. data.go.kr 가입 → '국토교통부_아파트 매매 실거래가 자료' 검색 → 활용신청(자동 승인, 반영까지 1~2시간) → 마이페이지의 일반 인증키(Decoding 또는 Encoding)를 설정에 넣으세요. 그 전에는 rt.molit.go.kr 에서 직접 확인할 수 있습니다.";
let SETTINGS = null;
export function setRealestateSettings(s){ SETTINGS = s; }
const dataKey = () => SETTINGS?.keys?.datagokr || SETTINGS?.keys?.data_go_kr || SETTINGS?.datagokrKey || "";
// 정규식 XML 읽기 (DOMParser 없는 환경에서도 동작)
const unxml = s => String(s ?? "").replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;|&apos;/g, "'").replace(/&#(\d+);/g, (_, d) => String.fromCodePoint(+d)).replace(/&amp;/g, "&").trim();
const tagsOf = block => { const o = {}; for (const m of block.matchAll(/<([\w가-힣:.-]+)(?:\s[^>]*)?>([\s\S]*?)<\/\1>/g)) o[m[1]] = unxml(m[2]); return o; };
// 실거래가 XML → 거래 목록 (새 영문 태그와 예전 한글 태그 모두, 해제된 거래는 뺀다)
export function parseTradesXml(xml){
  xml = String(xml || "");
  const code = (xml.match(/<resultCode>([^<]*)<\/resultCode>/) || [])[1], msg = (xml.match(/<resultMsg>([^<]*)<\/resultMsg>/) || [])[1];
  const auth = (xml.match(/<returnAuthMsg>([^<]*)<\/returnAuthMsg>/) || [])[1];
  if (auth || (code && !/^0+$/.test(code.trim()))) { const e = new Error(`실거래가 API 오류: ${auth || msg || code}`); e.code = auth || code; throw e; }
  const total = +((xml.match(/<totalCount>(\d+)<\/totalCount>/) || [])[1] || 0);
  const deals = [];
  for (const m of xml.matchAll(/<item>([\s\S]*?)<\/item>/g)){
    const t = tagsOf(m[1]), g = (...ks) => { for (const k of ks) if (t[k] != null && t[k] !== "") return t[k]; return ""; };
    if (/^O$/i.test(g("cdealType", "해제여부"))) continue;
    const price = +String(g("dealAmount", "거래금액")).replace(/[^\d]/g, ""), area = +g("excluUseAr", "전용면적");
    const y = g("dealYear", "년"), mo = String(g("dealMonth", "월")).padStart(2, "0"), d = String(g("dealDay", "일")).padStart(2, "0");
    if (!price || !area || !y) continue;
    deals.push({apt: g("aptNm", "아파트"), dong: g("umdNm", "법정동"), jibun: g("jibun", "지번"), area, floor: +g("floor", "층") || null, built: +g("buildYear", "건축년도") || null,
      price, ym: `${y}${mo}`, date: `${y}-${mo}-${d}`, perM2: price * 1e4 / area});
  }
  return {deals, total};
}
const ymList = (months, now) => { const d = new Date(now), out = []; for (let i = 0; i < months; i++){ const x = new Date(d.getFullYear(), d.getMonth() - i, 1); out.push(`${x.getFullYear()}${String(x.getMonth() + 1).padStart(2, "0")}`); } return out.reverse(); };
// 월별로 실거래가를 가져온다. key 없으면 {needKey, note}
export async function aptTrades({lawdCd, months = 6, key, now = Date.now(), rows = 1000, maxPages = 3, ...o} = {}){
  key = key || dataKey();
  if (!key) return {deals: [], needKey: true, note: KEY_NOTE};
  if (!/^\d{5}$/.test(String(lawdCd || ""))) throw new Error("법정동코드(LAWD_CD) 5자리가 필요합니다 (예: 마포구 11440)");
  const {fetchText} = await io(o), k = /%[0-9A-F]{2}/i.test(key) ? key : encodeURIComponent(key);   // Encoding 키는 그대로, Decoding 키는 인코딩
  const yms = ymList(clamp(+months || 6, 1, 24), now), deals = [], errors = [];
  await pool(yms, o.concurrency || 2, async ym => {
    for (let page = 1; page <= maxPages; page++){
      try {
        const r = parseTradesXml(await fetchText(`${RTMS}?serviceKey=${k}&LAWD_CD=${lawdCd}&DEAL_YMD=${ym}&pageNo=${page}&numOfRows=${rows}`));
        deals.push(...r.deals);
        if (page * rows >= r.total || !r.deals.length) break;
      } catch(e){ errors.push(`${ym}: ${e.message}`); if (/KEY|인증|SERVICE/i.test(e.message)) throw e; break; }
    }
  });
  deals.sort((a, b) => b.date.localeCompare(a.date));
  return {lawdCd, months: yms, deals, errors};
}
const median = a => { if (!a.length) return null; const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
// 가격 모멘텀: 월별 ㎡당 가격 중앙값 → 처음 대비 변화, 최근 3개월 대 그 전 3개월
export function priceMomentum(deals, {minN = 5} = {}){
  const by = {}; for (const d of deals || []) (by[d.ym] ||= []).push(d.perM2 ?? d.price * 1e4 / d.area);
  const series = Object.keys(by).sort().map(ym => ({ym, n: by[ym].length, median: Math.round(median(by[ym]))}));
  const ok = series.filter(s => s.n >= minN);
  const chg = (a, b) => a && b ? r1((b / a - 1) * 100) : null;
  const change_pct = ok.length >= 2 ? chg(ok[0].median, ok.at(-1).median) : null;
  const yms = Object.keys(by).sort(), last3 = yms.slice(-3), prev3 = yms.slice(-6, -3);
  const pooled = ks => median(ks.flatMap(k => by[k]));
  const recent_vs_prior_pct = prev3.length && last3.length ? chg(pooled(prev3), pooled(last3)) : null;
  const m = recent_vs_prior_pct ?? change_pct;
  const signal = m == null ? "판단 불가" : m >= 3 ? "상승" : m <= -3 ? "하락" : "보합";
  return {series, change_pct, recent_vs_prior_pct, signal, n: (deals || []).length, note: ok.length < series.length ? `거래 ${minN}건 미만인 달은 변화율 계산에서 뺌` : ""};
}
const won = v => v >= 1e4 ? `${(v / 1e4).toFixed(v >= 1e5 ? 1 : 2)}억` : `${Math.round(v).toLocaleString("ko-KR")}만`;
export function tradesText(r, mo, label = ""){
  if (r.needKey) return r.note;
  if (!r.deals.length) return `${label} 실거래 신고가 없습니다(기간 ${r.months?.[0]}~${r.months?.at(-1)}).${r.errors?.length ? " 오류: " + r.errors.slice(0, 2).join(" / ") : ""}`;
  const py = v => Math.round(v * 3.3058 / 1e4).toLocaleString("ko-KR");
  const ser = mo.series.map(s => `${s.ym.slice(2, 4)}.${s.ym.slice(4)} ${py(s.median)}만/평(${s.n}건)`).join(" → ");
  const top = r.deals.slice(0, 6).map(d => `${d.date} ${d.dong} ${d.apt} ${d.area}㎡ ${d.floor ?? "?"}층 ${won(d.price)}`).join("\n");
  return `[아파트 매매 실거래가 · ${label}] ${r.deals.length}건 (국토교통부, 해제 거래 제외)\n월별 ㎡당 중앙값(평 환산): ${ser}\n가격 모멘텀: ${mo.signal}${mo.recent_vs_prior_pct != null ? ` · 최근3개월 대 이전3개월 ${mo.recent_vs_prior_pct > 0 ? "+" : ""}${mo.recent_vs_prior_pct}%` : ""}${mo.change_pct != null ? ` · 기간 처음→끝 ${mo.change_pct > 0 ? "+" : ""}${mo.change_pct}%` : ""}${mo.note ? " (" + mo.note + ")" : ""}\n최근 거래:\n${top}\n※ 최근 1~2개월은 신고 기한(계약 후 30일) 때문에 덜 채워져 있다. 단지·면적 구성이 달라지면 중앙값도 흔들린다.`.slice(0, 1790);
}

/* ============ 6. 도구 (agent.js 모양) ============ */
// 이번 세션에서 모은 근거: 날짜 붙이기에 쓰고, [번호]→주소 변환은 마지막 탐색 목록 기준(AI가 본 번호)
const SESSION_EV = new Map(); let LAST_SCAN = [];
const coerceList = v => { if (Array.isArray(v)) return v; if (typeof v === "string") return parseCandidates(v); return []; };
export const REALESTATE_TOOLS = {
  redev_scan: {mode: "both", label: "재개발 후보지 탐색", args: '{"region":"성북구","signals":["신통","모아타운","해제","교통"]}', act: a => `${a.region || "서울"} 재개발·재건축 근거 수집`,
    desc: "지역(서울 25개 구·경기·인천 주요 도시)의 정비구역 지정·해제, 신속통합기획·모아타운·공공재개발 선정, 안전진단, 조합설립, 관리처분, 역세권·GTX 소식을 검색해 근거 목록을 준다. 이 근거에서 후보지를 JSON으로 뽑아 redev_rank 의 candidates 로 넘기면 저장·점수화된다",
    async run(a, ctx = {}){
      const r = await gatherRedev({region: a.region || "서울", signals: a.signals, n: Math.min(8, a.n || 6), ...(ctx.io || {})});
      LAST_SCAN = r.items; for (const x of r.items) SESSION_EV.set(normUrl(x.url), x); while (SESSION_EV.size > 600) SESSION_EV.delete(SESSION_EV.keys().next().value);
      if (!r.items.length) return {text: "근거를 찾지 못했습니다(검색 차단일 수 있음). 지역 이름을 바꾸거나 web_search 로 찾아보세요.", summary: "근거 없음"};
      return {text: `[근거 ${r.items.length}건 · ${[].concat(a.region || "서울").join(", ")}]\n${r.text}\n\n[다음 단계]\n${EXTRACT_PROMPT}\n뽑은 배열은 redev_rank 의 candidates 로 넘긴다.`, summary: `근거 ${r.items.length}건`, sources: r.sources.slice(0, 20), evidence: r.items};
    }},
  redev_rank: {mode: "both", label: "재개발 잠재력 순위", args: '{"candidates":[{"area":"장위15구역","region":"서울 성북구","project_type":"재개발","stage":"구역지정","signals":["신속통합기획"],"positives":[],"risks":[],"evidence_urls":["https://..."]}],"n":10,"explain":false}', act: () => "재개발 잠재력 지수 계산",
    desc: "연구 노트에 쌓인 재개발·재건축 후보지를 '재개발 잠재력 지수'(확실성·상승여력, 0~100)로 순위를 매긴다. candidates 를 주면 먼저 저장(같은 구역은 합치고 단계 변화 기록)한다. explain:true 면 지수 계산법과 1위의 점수표도 준다",
    async run(a, ctx = {}){
      const o = ctx.io || {}, ev = [...SESSION_EV.values()], add = parseCandidates(coerceList(a.candidates), {evidence: LAST_SCAN, strict: false});
      if (add.length) await saveCandidates(add, {evidence: ev, ...o});
      const ranked = rankCandidates(await loadCandidates(o));
      let text = candidateText(ranked, Math.min(20, a.n || 10));
      if (ranked.length && (a.explain || a.area)){
        const c = (a.area && ranked.find(x => x.area.includes(a.area))) || ranked[0];
        text += `\n\n[${c.area} 점수표] ` + c.index.breakdown.map(b => `${b.factor} ${b.points > 0 ? "+" : ""}${b.points} (${b.why})`).join(" / ");
        if (a.explain) text += "\n\n" + customIndicatorText();
      }
      const sources = ranked.slice(0, 8).flatMap(c => (c.evidence_urls || []).slice(0, 1).map(u => ({title: `${c.area} 근거`, url: u})));
      return {text: text.slice(0, 3800), summary: ranked.length ? `후보 ${ranked.length}곳 · 1위 ${ranked[0].area} ${Math.round(ranked[0].index.score)}점` : "후보 없음", sources, ...(add.length ? {saved: add.length} : {})};
    }},
  apt_trades: {mode: "both", label: "아파트 실거래가", args: '{"region":"마포구","lawd_cd":"선택: 11440","months":6}', act: a => `${a.region || a.lawd_cd || ""} 아파트 실거래가 조회`,
    desc: "국토교통부 아파트 매매 실거래가(공공데이터포털 인증키 필요)로 지역의 최근 거래와 월별 ㎡당 가격 중앙값, 가격 모멘텀(상승·보합·하락)을 계산한다. 키가 없으면 발급 방법을 알려준다",
    async run(a, ctx = {}){
      const reg = a.region ? findRegion(a.region) : null, codes = a.lawd_cd ? [String(a.lawd_cd)] : reg?.lawd || [];
      const label = reg?.full || (a.lawd_cd ? "법정동코드 " + a.lawd_cd : String(a.region || ""));
      if (!codes.length) throw new Error(`지역을 찾지 못했습니다: ${a.region || ""} (서울 25개 구·경기·인천 주요 도시, 또는 lawd_cd 5자리)`);
      const o = ctx.io || {}, months = clamp(+a.months || 6, 1, 12);
      const parts = [];
      for (const c of codes.slice(0, 4)){ const r = await aptTrades({lawdCd: c, months, key: o.key, ...o}); if (r.needKey) return {text: r.note, summary: "인증키 필요", sources: [{title: "공공데이터포털 아파트 매매 실거래가", url: "https://www.data.go.kr/tcs/dss/selectDataSetList.do?keyword=" + encodeURIComponent("아파트 매매 실거래가")}, {title: "국토부 실거래가 공개시스템", url: "https://rt.molit.go.kr"}]}; parts.push(r); }
      const all = {deals: parts.flatMap(p => p.deals).sort((x, y) => y.date.localeCompare(x.date)), months: parts[0].months, errors: parts.flatMap(p => p.errors)};
      const mo = priceMomentum(all.deals);
      return {text: tradesText(all, mo, label), summary: `${label} ${all.deals.length}건 · ${mo.signal}`, sources: [{title: "국토교통부 실거래가 공개시스템", url: "https://rt.molit.go.kr"}], momentum: mo};
    }}
};
