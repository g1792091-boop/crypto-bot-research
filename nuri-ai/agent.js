// 누리 AI 에이전트: 어떤 모델이든 쓸 수 있는 글자 기반 도구 호출 규약 + 도구 모음 + 스킬 + 반복 실행
// 모델이 <tool name="도구">{"인자":"값"}</tool> 를 쓰면 실행하고 <tool_result>로 결과를 돌려준다.
import { settings, saveSettings, brainStream, brainCtx, brainAnswerLen, splitThink, search, docs, apiBase, codeCall, ls, bus, esc,
         webGet, webSearch, readPage, PROVIDERS, shortModel } from "./engine.js";
import { exchanges, computeAll, quantScore, levels, backtest, STRATS, fmtNum, YAHOO_LIST } from "./trade.js";

const TF = {"1":"1분","5":"5분","15":"15분","60":"1시간","240":"4시간","D":"일봉","W":"주봉"};
const r6 = v => v == null || !isFinite(v) ? null : +(+v).toPrecision(6);
const pct2 = v => v == null || !isFinite(v) ? null : +(v * 100).toFixed(2);
const won = v => Math.round(v).toLocaleString("ko-KR");
const host = u => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch(e){ return String(u || "").slice(0, 40); } };
const activity = detail => bus.dispatchEvent(new CustomEvent("activity", {detail}));
let EXS = null;
const ex = name => (EXS || (EXS = exchanges(apiBase, webGet)))[name || "upbit"];
const EX_LABEL = {upbit:"업비트 현물", binance:"바이낸스 현물", binancef:"바이낸스 선물", yahoo:"주식·지수·해외선물"};

/* ================= 종목 이름 → 시장 ================= */
const COIN_KO = {"비트코인":"BTC","이더리움":"ETH","이더":"ETH","리플":"XRP","솔라나":"SOL","도지코인":"DOGE","도지":"DOGE","에이다":"ADA","트론":"TRX","아발란체":"AVAX",
  "체인링크":"LINK","폴리곤":"POL","수이":"SUI","비트코인캐시":"BCH","이더리움클래식":"ETC","스텔라루멘":"XLM","시바이누":"SHIB","페페":"PEPE","폴카닷":"DOT","니어":"NEAR",
  "앱토스":"APT","아비트럼":"ARB","옵티미즘":"OP","샌드박스":"SAND","헤데라":"HBAR","월드코인":"WLD","온도":"ONDO","세이":"SEI","톤코인":"TON","유니스왑":"UNI","에이브":"AAVE"};
const CRYPTO = new Set([...Object.values(COIN_KO), "BNB","USDT","USDC","FIL","ATOM","ALGO","EOS","XTZ","SAND","MANA","AXS","IMX","INJ","TIA","JUP","BONK","WIF","FLOKI","ENA","STX","XEC","BTT","CRO","MKR","LDO","GRT","KAVA","QTUM","IOTA","NEO","ZIL","VET","THETA","CHZ","ICP","FET","RNDR","RENDER","TAO"]);
const KR_NAMES = Object.assign(Object.fromEntries(YAHOO_LIST.map(([s, n]) => [n.replace(/\s/g, ""), s])), {
  "코스피":"^KS11","코스닥":"^KQ11","나스닥":"^IXIC","나스닥100":"^NDX","s&p":"^GSPC","s&p500":"^GSPC","에스앤피":"^GSPC","다우":"^DJI","닛케이":"^N225","항셍":"^HSI","상해종합":"000001.SS",
  "금":"GC=F","은":"SI=F","원유":"CL=F","유가":"CL=F","wti":"CL=F","브렌트":"BZ=F","천연가스":"NG=F","구리":"HG=F","나스닥선물":"NQ=F","s&p선물":"ES=F","다우선물":"YM=F","미국채":"ZN=F",
  "환율":"KRW=X","달러":"KRW=X","원달러":"KRW=X","엔화":"JPYKRW=X","유로":"EURKRW=X","달러인덱스":"DX-Y.NYB","vix":"^VIX","미국금리":"^TNX",
  "삼성":"005930.KS","하이닉스":"000660.KS","카카오":"035720.KS","셀트리온":"068270.KS","기아":"000270.KS","포스코홀딩스":"005490.KS","lg화학":"051910.KS","삼성바이오로직스":"207940.KS","현대모비스":"012330.KS","kb금융":"105560.KS",
  "에코프로":"086520.KQ","에코프로비엠":"247540.KQ","알테오젠":"196170.KQ",
  "애플":"AAPL","엔비디아":"NVDA","마이크로소프트":"MSFT","테슬라":"TSLA","아마존":"AMZN","구글":"GOOGL","알파벳":"GOOGL","메타":"META","넷플릭스":"NFLX","브로드컴":"AVGO","amd":"AMD","팔란티어":"PLTR","tsmc":"TSM","코카콜라":"KO","버크셔":"BRK-B","마이크로스트래티지":"MSTR","코인베이스":"COIN","스타벅스":"SBUX","인텔":"INTC","퀄컴":"QCOM"
});
function normExchange(e){
  e = String(e || "").toLowerCase();
  if (/binancef|futures?|선물|perp/.test(e)) return "binancef";
  if (/binance|바이낸스/.test(e)) return "binance";
  if (/upbit|업비트/.test(e)) return "upbit";
  if (/yahoo|stock|주식|index|지수|해외|fx|환율/.test(e)) return "yahoo";
  return "";
}
// 어떤 이름이 와도 {거래소, 시장 코드}로 바꾼다
export function resolveMarket(input, exHint = ""){
  let raw = String(input || "").trim(), exn = normExchange(exHint);
  const key = raw.replace(/\s/g, "").toLowerCase();
  if (!raw) return exn === "yahoo" ? {exn, market: "^GSPC"} : exn === "binance" || exn === "binancef" ? {exn, market: "BTCUSDT"} : {exn: "upbit", market: "KRW-BTC"};
  const coinKo = COIN_KO[raw.replace(/\s/g, "")];
  const yName = KR_NAMES[key] || KR_NAMES[raw.replace(/\s/g, "")];
  let sym = raw.toUpperCase();
  if (coinKo) sym = coinKo;
  else if (yName && exn !== "upbit" && exn !== "binance" && exn !== "binancef") return {exn: "yahoo", market: yName};
  if (/^\d{6}$/.test(sym)) return {exn: "yahoo", market: sym + ".KS"};
  if (/[\^=]|\.(KS|KQ|T|HK|SS|SZ|L|PA|DE)$/.test(sym)) return {exn: "yahoo", market: sym};
  if (/^KRW-/.test(sym)) return exn === "binance" || exn === "binancef" ? {exn, market: sym.slice(4) + "USDT"} : {exn: "upbit", market: sym};
  sym = sym.replace(/[-/_ ]/g, "");
  if (/USDT$/.test(sym)) return {exn: exn === "binancef" ? "binancef" : exn === "upbit" ? "upbit" : "binance", market: exn === "upbit" ? "KRW-" + sym.replace(/USDT$/, "") : sym};
  if (exn === "yahoo") return {exn, market: sym};
  if (exn === "binance" || exn === "binancef") return {exn, market: sym + "USDT"};
  if (exn === "upbit" || CRYPTO.has(sym) || coinKo) return {exn: "upbit", market: "KRW-" + sym};
  return {exn: "yahoo", market: sym};
}
async function candlesFor(a, total){
  const {exn, market} = resolveMarket(a.market || a.symbol, a.exchange);
  const tf = TF[a.timeframe] ? String(a.timeframe) : exn === "yahoo" ? "D" : "60";
  const cs = await ex(exn).candles(market, tf, total);
  if (cs.length < 30) throw new Error("캔들 데이터가 부족합니다 (" + market + ")");
  return {exn, market, tf, cs};
}
const quoteOf = (exn, cs) => exn === "upbit" ? "KRW" : exn === "yahoo" ? (cs?.currency || "USD") : "USDT";

/* ================= 견적서 ================= */
const COST = {  // 원/㎡ (2025년 전후 민간 공사 평균에 가까운 대략값, 지역·시기에 따라 크게 다름)
  new: {house: 2.45e6, multi: 2.25e6, mixed: 2.35e6, office: 2.55e6, cafe: 2.6e6, warehouse: 1.35e6, factory: 1.45e6},
  remodel: {house: 1.35e6, multi: 1.25e6, mixed: 1.3e6, office: 1.2e6, cafe: 1.5e6, warehouse: 0.7e6, factory: 0.8e6},
  interior: {house: 1.05e6, multi: 0.95e6, mixed: 1.0e6, office: 0.85e6, cafe: 1.35e6, warehouse: 0.4e6, factory: 0.45e6}
};
const STRUCT = {RC: 1, "철근콘크리트": 1, steel: 0.9, "철골": 0.9, wood: 0.96, "목조": 0.96, masonry: 0.88, "조적": 0.88, steelrc: 1.08, "SRC": 1.08};
const GRADE = {economy: 0.82, "보급": 0.82, standard: 1, "표준": 1, premium: 1.32, "고급": 1.32, luxury: 1.7, "최고급": 1.7};
const BREAK = {
  new: [["가설공사", 4], ["토공사·기초", 8], ["철근콘크리트·골조", 27], ["조적·방수·단열", 7], ["창호·유리", 9], ["내외부 마감(미장·타일·도장·수장)", 15], ["기계설비(급배수·냉난방)", 11], ["전기·통신", 9], ["소방", 3], ["외부·조경·부대", 4], ["기타·잡공사", 3]],
  remodel: [["철거·폐기물", 8], ["보강·구조", 12], ["방수·단열", 10], ["창호", 12], ["마감", 22], ["설비", 15], ["전기·조명", 12], ["외부·기타", 9]],
  interior: [["철거·폐기물", 6], ["목공·가벽·천장", 18], ["전기·조명", 11], ["설비·욕실", 15], ["주방 가구", 12], ["타일", 9], ["도장·도배", 9], ["바닥재", 9], ["창호·문", 7], ["붙박이 가구·기타", 4]]
};
function estimate(a){
  const scope = /리모델|remodel/.test(a.scope || "") ? "remodel" : /인테리어|interior/.test(a.scope || "") ? "interior" : "new";
  const use = COST[scope][a.use] ? a.use : "house";
  const area = +a.area_m2 || (+a.area_py ? a.area_py * 3.3058 : 0);
  if (!(area > 0)) throw new Error("면적(area_m2 또는 area_py)이 필요합니다");
  const sf = STRUCT[a.structure] || 1, gf = GRADE[a.grade] || 1;
  const regionF = /서울|강남|seoul/i.test(a.region || "") ? 1.08 : /제주|도서|섬/.test(a.region || "") ? 1.15 : /경기|인천|부산|대구|광주|대전|울산|세종/.test(a.region || "") ? 1.02 : 1;
  const floorsF = (+a.floors || 1) >= 6 ? 1.06 : 1;
  const unit = COST[scope][use] * (scope === "new" ? sf : 1) * gf * regionF * floorsF;
  const direct = unit * area;
  const custom = Array.isArray(a.extra) ? a.extra.filter(x => x && x.name && +x.amount > 0) : [];
  const rows = BREAK[scope].map(([n, p]) => ({name: n, pct: p, amount: direct * p / 100}));
  custom.forEach(x => rows.push({name: x.name, pct: null, amount: +x.amount}));
  const dsum = rows.reduce((s, r) => s + r.amount, 0);
  const overhead = dsum * 0.06, profit = (dsum + overhead) * 0.08;
  const design = scope === "interior" ? 0 : dsum * (a.design_fee_pct != null ? a.design_fee_pct / 100 : 0.05);
  const supply = dsum + overhead + profit + design, vat = (use === "house" && area <= 85 && scope === "new" && a.vat !== true) ? 0 : supply * 0.1;
  const total = supply + vat;
  return {scope, use, area, unit, rows, dsum, overhead, profit, design, vat, total, regionF, perPy: total / (area / 3.3058), name: a.name || "공사", client: a.client || "", region: a.region || "", grade: a.grade || "standard", structure: a.structure || "RC", floors: +a.floors || null, months: Math.max(1, Math.round(scope === "new" ? 3 + area / 220 : scope === "remodel" ? 1.5 + area / 400 : 0.7 + area / 500))};
}
const USE_KO = {house: "단독주택", multi: "다가구·다세대", mixed: "상가주택", office: "근린생활·업무시설", cafe: "카페·상가", warehouse: "창고", factory: "공장"};
const STRUCT_KO = {RC: "철근콘크리트", steel: "철골", wood: "목조", masonry: "조적", steelrc: "철골철근콘크리트", SRC: "철골철근콘크리트"};
const GRADE_KO = {economy: "보급형", standard: "표준", premium: "고급", luxury: "최고급"};
function estimateHTML(e){
  const SC = {new: "신축", remodel: "리모델링", interior: "인테리어"}, d = new Date();
  const no = `NURI-${d.getFullYear()}${String(d.getMonth()+1).padStart(2,"0")}${String(d.getDate()).padStart(2,"0")}-${Math.floor(Math.random()*900+100)}`;
  const tr = (n, v, cls = "") => `<tr class="${cls}"><td>${n}</td><td class="r">${won(v)}</td></tr>`;
  return `<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>견적서 · ${esc(e.name)}</title><style>
:root{--ink:#22201c;--mut:#6b655c;--line:#e4ddd2;--acc:#c2410c;--bg:#fff}
*{box-sizing:border-box}body{margin:0;background:#f4f1ec;font:14px/1.6 "Pretendard","Malgun Gothic",system-ui,sans-serif;color:var(--ink)}
.page{max-width:820px;margin:24px auto;background:var(--bg);padding:44px 48px;border-radius:10px;box-shadow:0 2px 18px rgba(0,0,0,.08)}
h1{font-size:30px;letter-spacing:.4em;text-align:center;margin:0 0 6px}.no{text-align:center;color:var(--mut);font-size:12px;margin-bottom:26px}
.meta{display:grid;grid-template-columns:1fr 1fr;gap:4px 24px;margin-bottom:20px}.meta div{display:flex;gap:10px;border-bottom:1px solid var(--line);padding:5px 0}.meta b{min-width:76px;color:var(--mut);font-weight:500}
.total{display:flex;justify-content:space-between;align-items:center;background:#fbf4ee;border:1px solid #f0d9c8;border-radius:8px;padding:14px 18px;margin:18px 0}.total b{font-size:22px;color:var(--acc)}
table{width:100%;border-collapse:collapse;margin:10px 0}th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left}th{background:#f7f4ef;font-weight:600;font-size:13px}.r{text-align:right;font-variant-numeric:tabular-nums}
tr.sum td{font-weight:700;background:#faf8f5}tr.grand td{font-weight:800;font-size:15px;border-top:2px solid var(--ink)}
.note{color:var(--mut);font-size:12px;margin-top:18px}.note li{margin:2px 0}.btn{position:fixed;right:18px;bottom:18px;background:var(--acc);color:#fff;border:0;border-radius:8px;padding:10px 16px;font-weight:600;cursor:pointer}
@media(max-width:600px){.page{padding:24px 18px;margin:0;border-radius:0}.meta{grid-template-columns:1fr}h1{font-size:24px}}
@media print{body{background:#fff}.page{box-shadow:none;margin:0;max-width:none}.btn{display:none}}
</style></head><body><div class="page">
<h1>견 적 서</h1><div class="no">No. ${no} · ${d.toLocaleDateString("ko-KR")}</div>
<div class="meta"><div><b>공사명</b>${esc(e.name)}</div><div><b>구분</b>${SC[e.scope]} · ${esc(USE_KO[e.use] || e.use)}</div><div><b>발주처</b>${esc(e.client || "—")}</div><div><b>지역</b>${esc(e.region || "—")}</div>
<div><b>면적</b>${e.area.toFixed(1)}㎡ (${(e.area/3.3058).toFixed(1)}평)</div><div><b>구조·등급</b>${esc(e.scope === "new" ? (STRUCT_KO[e.structure] || e.structure) + " · " : "")}${esc(GRADE_KO[e.grade] || e.grade)}${e.floors ? " · " + e.floors + "층" : ""}</div><div><b>예상 공기</b>약 ${e.months}개월</div><div><b>유효기간</b>발행일로부터 30일</div></div>
<div class="total"><span>합계 금액 (부가세 ${e.vat ? "포함" : "면세"})</span><b>₩ ${won(e.total)}</b></div>
<table><thead><tr><th>공종</th><th class="r">비율</th><th class="r">금액(원)</th></tr></thead><tbody>
${e.rows.map(r => `<tr><td>${esc(r.name)}</td><td class="r">${r.pct == null ? "추가" : r.pct + "%"}</td><td class="r">${won(r.amount)}</td></tr>`).join("")}
</tbody></table>
<table><tbody>${tr("직접공사비 계", e.dsum, "sum")}${tr("일반관리비 (6%)", e.overhead)}${tr("이윤 (8%)", e.profit)}${e.design ? tr("설계·감리비", e.design) : ""}${tr("공급가액", e.dsum + e.overhead + e.profit + e.design, "sum")}${tr(e.vat ? "부가가치세 (10%)" : "부가가치세 (국민주택규모 주거 면세)", e.vat)}${tr("총 합계", e.total, "grand")}</tbody></table>
<p>㎡당 약 <b>${won(e.unit)}원</b> (직접공사비 기준) · 평당 총액 약 <b>${won(e.perPy)}원</b></p>
<ul class="note"><li>이 견적은 누리 AI가 면적·용도·등급으로 산출한 <b>개략 견적</b>입니다. 실제 금액은 도면·물량 산출·현장 조건·자재 시세에 따라 달라집니다.</li>
<li>토지 매입비, 인허가 수수료, 각종 부담금(학교용지·하수도 원인자 등), 측량·지반조사, 인입 공사비, 가구·가전은 포함하지 않았습니다.</li>
<li>정확한 금액은 시공사 2~3곳의 상세 내역 견적을 비교하세요.</li></ul>
</div><button class="btn" onclick="print()">인쇄 · PDF 저장</button></body></html>`;
}

/* ================= 용도지역 · 재개발 ================= */
const ZONES = [["제1종전용주거",50,100],["제2종전용주거",50,150],["제1종일반주거",60,200],["제2종일반주거",60,250],["제3종일반주거",50,300],["준주거",70,500],
  ["중심상업",90,1500],["일반상업",80,1300],["근린상업",70,900],["유통상업",80,1100],["전용공업",70,300],["일반공업",70,350],["준공업",70,400],
  ["보전녹지",20,80],["생산녹지",20,100],["자연녹지",20,100],["보전관리",20,80],["생산관리",20,80],["계획관리",40,100],["농림",20,80],["자연환경보전",20,80]];
const zoneOf = z => { z = String(z || "").replace(/\s|지역/g, ""); return ZONES.find(x => z && (x[0] === z || z.includes(x[0]) || x[0].includes(z))); };
const LINKS = {
  "토지이음 (용도지역·규제 확인)": "https://www.eum.go.kr",
  "국토부 실거래가": "https://rt.molit.go.kr",
  "부동산 공시가격 알리미": "https://www.realtyprice.kr",
  "대법원 법원경매정보": "https://www.courtauction.go.kr",
  "온비드 (공매)": "https://www.onbid.co.kr",
  "정비사업 정보몽땅 (서울)": "https://cleanup.seoul.go.kr",
  "국가법령정보센터": "https://www.law.go.kr",
  "일사편리 (부동산 종합 정보)": "https://kras.go.kr"
};
async function searchMany(queries, n = 5){
  const seen = new Set(), out = [];
  const rs = await Promise.all(queries.map(q => webSearch(q, n).catch(() => ({results: []}))));
  for (const r of rs) for (const x of r.results || []) if (!seen.has(x.url)){ seen.add(x.url); out.push(x); }
  return out;
}

/* ================= 도구 ================= */
const srcText = rs => rs.map((x, i) => `[${i+1}] ${x.title}\n${x.url}${x.date ? " · " + x.date : ""}\n${x.snippet || ""}`).join("\n\n");
export const TOOLS = {
  /* ---- 인터넷 ---- */
  web_search: {mode:"both", label:"웹 검색", args:'{"query":"검색어","n":8}', act: a => `‘${a.query}’ 검색`,
    desc:"인터넷 검색. 최신 정보·뉴스·가격·법령·사실 확인이 필요하면 먼저 쓴다. 결과의 [번호]로 출처를 단다",
    async run(a){
      const r = await webSearch(String(a.query || "").slice(0, 300), Math.min(12, a.n || 8));
      if (!r.results.length) return {text: "검색 결과가 없습니다.", summary: "결과 없음"};
      return {text: `검색엔진: ${r.engine}\n\n` + srcText(r.results), summary: `${r.engine} · ${r.results.length}건`, sources: r.results};
    }},
  web_fetch: {mode:"both", label:"웹페이지 읽기", args:'{"url":"https://...","max":12000}', act: a => `${host(a.url)} 읽기`,
    desc:"웹페이지 본문을 읽는다. 검색 결과만으로 부족할 때 중요한 페이지 1~3개를 읽는다",
    async run(a){
      if (!/^https?:\/\//.test(a.url || "")) throw new Error("http(s) 주소가 필요합니다");
      const p = await readPage(a.url, Math.min(30000, a.max || 12000));
      return {text: `제목: ${p.title}\n주소: ${p.url}${p.date ? "\n작성: " + p.date : ""}\n\n${p.text}${p.truncated ? "\n…(잘림)" : ""}`, summary: `${host(p.url)} · ${p.text.length.toLocaleString()}자`, sources: [{title: p.title, url: p.url}]};
    }},

  /* ---- 시장: 코인 현물·선물 · 주식 · 지수 · 해외선물 · 환율 ---- */
  market_list: {mode:"chat", label:"시장 순위", args:'{"exchange":"upbit|binance|binancef|yahoo","top":10,"sort":"volume|gain|loss"}', act: a => `${EX_LABEL[normExchange(a.exchange) || "upbit"]} 순위`,
    desc:"거래소별 종목 순위. upbit=국내 코인 현물(원화), binance=해외 코인 현물, binancef=코인 무기한 선물, yahoo=주요 주가지수·국내외 대형주·해외선물(원유·금·지수선물)·환율",
    async run(a){
      const exn = normExchange(a.exchange) || "upbit";
      let list = await ex(exn).list();
      const s = a.sort === "gain" ? (x, y) => y.chg - x.chg : a.sort === "loss" ? (x, y) => x.chg - y.chg : (x, y) => y.vol - x.vol;
      list = (exn === "yahoo" && !a.sort ? list : list.sort(s)).slice(0, Math.min(40, a.top || 10));
      return {text: JSON.stringify(list.map(m => ({종목: `${m.name} (${m.id})`, 현재가: r6(m.price), "변동%": pct2(m.chg), 거래대금: Math.round(m.vol || 0), ...(m.currency ? {통화: m.currency} : {})}))), summary: `${EX_LABEL[exn]} ${list.length}개`};
    }},
  market_quote: {mode:"chat", label:"현재가", args:'{"symbols":["비트코인","KRW-ETH","BTCUSDT","NVDA","005930","^KS11","CL=F"],"exchange":""}', act: a => `${[].concat(a.symbols || a.symbol || []).slice(0, 3).join(", ")} 시세`,
    desc:"현재가·변동률·고가·저가. 한글 이름(비트코인, 삼성전자, 나스닥, 금, 환율)이나 코드 모두 된다. 코인 선물은 exchange:'binancef'",
    async run(a){
      const items = [].concat(a.symbols || a.symbol || a.markets || a.market || "비트코인").slice(0, 15).map(s => resolveMarket(s, a.exchange));
      const groups = {}; items.forEach(x => (groups[x.exn] ||= []).push(x.market));
      const out = [];
      for (const [exn, ids] of Object.entries(groups)){
        const t = await ex(exn).tickers([...new Set(ids)]).catch(e => { out.push({거래소: EX_LABEL[exn], 오류: e.message}); return []; });
        t.forEach(x => out.push({종목: x.name ? `${x.name} (${x.id})` : x.id, 시장: EX_LABEL[exn], 현재가: r6(x.price), "변동%": pct2(x.chg), 고가: r6(x.hi), 저가: r6(x.lo), ...(x.currency ? {통화: x.currency} : {})}));
      }
      return {text: JSON.stringify(out), summary: out.filter(x => x.현재가 != null).slice(0, 3).map(x => `${x.종목.split(" (")[0]} ${x.현재가?.toLocaleString("ko-KR")}${x["변동%"] != null ? ` (${x["변동%"] >= 0 ? "+" : ""}${x["변동%"]}%)` : ""}`).join(", ") || "시세 없음"};
    }},
  market_search: {mode:"chat", label:"종목 찾기", args:'{"query":"팔란티어"}', act: a => `‘${a.query}’ 종목 찾기`,
    desc:"이름으로 주식·ETF·지수·선물 코드를 찾고 관련 최신 뉴스 제목을 받는다",
    async run(a){
      const q = String(a.query || "").trim(); const local = resolveMarket(q);
      let quotes = [], news = [];
      try {
        const j = await webGet(`https://query2.finance.yahoo.com/v1/finance/search?q=${encodeURIComponent(q)}&quotesCount=8&newsCount=6&lang=ko-KR&region=KR`, "json");
        quotes = (j.quotes || []).map(x => ({코드: x.symbol, 이름: x.shortname || x.longname, 종류: x.quoteType, 거래소: x.exchDisp}));
        news = (j.news || []).map(x => ({title: x.title, url: x.link, snippet: x.publisher, date: x.providerPublishTime ? new Date(x.providerPublishTime * 1000).toLocaleDateString("ko-KR") : ""}));
      } catch(e){}
      return {text: JSON.stringify({추천: `${local.market} (${EX_LABEL[local.exn]})`, 검색결과: quotes, 뉴스: news.map(n => `${n.title} · ${n.snippet} · ${n.date}`)}), summary: `${quotes.length}개 종목 · 뉴스 ${news.length}건`, sources: news};
    }},
  market_analyze: {mode:"chat", label:"차트 분석", args:'{"market":"비트코인|BTCUSDT|NVDA|005930|ES=F","exchange":"upbit|binance|binancef|yahoo","timeframe":"1|5|15|60|240|D|W"}', act: a => `${a.market || ""} ${TF[a.timeframe] || ""} 차트 분석`,
    desc:"캔들로 이동평균·RSI·MACD·볼린저·ATR·지지저항·퀀트점수를 계산하고 오른쪽 패널에 차트를 연다. 선물(binancef)은 펀딩비·미결제약정·롱숏비율도 준다. 주식은 timeframe D 추천",
    async run(a, ctx){
      const {exn, market, tf, cs} = await candlesFor(a, 220);
      const I = computeAll(cs), q = quantScore(cs, I), n = cs.length - 1, p = cs[n].c, lv = levels(cs.slice(-150), p);
      ctx.openArtifact({type:"trading", title:`${cs.name || market} ${TF[tf]} 차트`, ex: exn, market, tf});
      const chg = k => cs.length > k ? pct2(p / cs[n - k].c - 1) : null;
      const data = {종목: cs.name ? `${cs.name} (${market})` : market, 시장: EX_LABEL[exn], 통화: quoteOf(exn, cs), 봉: TF[tf], 현재가: r6(p), 기간: `${new Date(cs[0].t).toLocaleString("ko-KR")} ~ ${new Date(cs[n].t).toLocaleString("ko-KR")}`,
        "변동%_5봉": chg(5), "변동%_20봉": chg(20), "변동%_60봉": chg(60),
        MA20: r6(I.ma20[n]), MA60: r6(I.ma60[n]), MA120: r6(I.ma120[n]), RSI14: r6(I.rsi[n]), MACD히스토그램: r6(I.macd.hist[n]),
        볼린저상단: r6(I.bb.up[n]), 볼린저하단: r6(I.bb.lo[n]), "ATR%": I.atr[n] ? +(I.atr[n] / p * 100).toFixed(2) : null,
        거래량_20평균대비: I.vma[n] ? +(cs[n].v / I.vma[n]).toFixed(2) : null,
        퀀트점수: q.score, 판단: q.label, 근거: q.factors.map(f => `${f.label}(${f.pts > 0 ? "+" : ""}${f.pts})`),
        저항: lv.res.map(l => r6(l.p)), 지지: lv.sup.map(l => r6(l.p)), 최근종가20: cs.slice(-20).map(k => r6(k.c))};
      if (exn === "binancef"){
        try { const x = await ex("binancef").extra(market); Object.assign(data, {"펀딩비%": +(x.funding * 100).toFixed(4), 마크가격: r6(x.mark), 다음펀딩: new Date(x.nextFunding).toLocaleString("ko-KR"), 미결제약정_코인: r6(x.oi), 미결제약정_USDT: Math.round(x.oi * p), 롱숏계정비율: x.longShort}); } catch(e){}
      }
      return {text: JSON.stringify(data), summary: `${cs.name || market} ${TF[tf]} · 퀀트 ${q.score} ${q.label}`};
    }},
  market_backtest: {mode:"chat", label:"전략 백테스트", args:'{"market":"KRW-BTC","exchange":"","timeframe":"60","strategy":"ma|rsi|bb|macd","params":{"fast":20,"slow":60},"fee":0.05,"stop_loss":0,"take_profit":0,"candles":500}', act: a => `${a.market || ""} ${STRATS[a.strategy]?.name || "전략"} 백테스트`,
    desc:"과거 캔들로 매매 전략을 시험해 수익률·최대낙폭·승률·손익비를 계산(코인·주식·선물 모두). params: ma{fast,slow} rsi{low,high} bb{n,k} macd{f,s,g}. stop_loss·take_profit은 %",
    async run(a, ctx){
      const key = STRATS[a.strategy] ? a.strategy : "ma";
      const {exn, market, tf, cs} = await candlesFor(a, Math.max(100, Math.min(1000, a.candles || 500)));
      const P = Object.fromEntries(STRATS[key].params.map(([k, , d]) => [k, a.params?.[k] ?? d]));
      const r = backtest(cs, key, P, {fee: a.fee ?? (exn === "yahoo" ? 0.015 : 0.05), sl: a.stop_loss || 0, tp: a.take_profit || 0});
      ctx.openArtifact({type:"trading", title:`${cs.name || market} ${TF[tf]} 차트`, ex: exn, market, tf});
      const pf = r.pf === Infinity ? "∞" : +r.pf.toFixed(2);
      const res = {전략: STRATS[key].name, 조건: P, 종목: market, 시장: EX_LABEL[exn], 봉: TF[tf], 캔들수: cs.length, "전략수익률%": pct2(r.ret), "그냥보유%": pct2(r.hold), "최대낙폭%": pct2(r.mdd), "보유시최대낙폭%": pct2(r.holdMdd), "승률%": +(r.win * 100).toFixed(1), 거래수: r.trades.length, 손익비: pf, 현재보유중: r.open,
        최근거래: r.trades.slice(-5).map(t => ({매수: r6(t.entry), 매도: r6(t.exit), "수익%": pct2(t.ret), 사유: t.why}))};
      return {text: JSON.stringify(res), summary: `${STRATS[key].name} ${res["전략수익률%"]}% (보유 ${res["그냥보유%"]}%)`};
    }},
  econ_calendar: {mode:"chat", label:"경제 발표 일정", args:'{"week":"this|next","impact":"high|medium|all","country":"USD"}', act: a => `${a.week === "next" ? "다음 주" : "이번 주"} 경제 발표 일정`,
    desc:"이번 주/다음 주 주요국 경제지표 발표(CPI·고용·FOMC·GDP 등) 일정과 예상치·이전치. 시간은 한국시간",
    async run(a){
      const url = `https://nfs.faireconomy.media/ff_calendar_${a.week === "next" ? "next" : "this"}week.json`;
      const rows = await webGet(url, "json");
      const imp = a.impact === "all" ? /./ : a.impact === "medium" ? /High|Medium/ : /High/;
      const cc = a.country ? String(a.country).toUpperCase().split(/[,\s]+/) : null;
      const IMP = {High: "높음", Medium: "중간", Low: "낮음", Holiday: "휴일"};
      const list = (rows || []).filter(r => imp.test(r.impact) && (!cc || cc.includes(r.country))).slice(0, 60)
        .map(r => ({한국시간: new Date(r.date).toLocaleString("ko-KR", {timeZone: "Asia/Seoul", month: "numeric", day: "numeric", weekday: "short", hour: "2-digit", minute: "2-digit"}), 국가: r.country, 지표: r.title, 중요도: IMP[r.impact] || r.impact, 예상: r.forecast || "", 이전: r.previous || "", 지났음: Date.parse(r.date) < Date.now()}));
      return {text: list.length ? JSON.stringify(list) : "해당 조건의 일정이 없습니다.", summary: `${list.length}건`, sources: [{title: "ForexFactory 경제 캘린더", url: "https://www.forexfactory.com/calendar"}]};
    }},
  paper_trade: {mode:"chat", label:"모의투자", args:'{"action":"status|buy|sell","market":"비트코인","exchange":"upbit|binance","amount":1000000,"percent":100}', act: a => a.action === "buy" ? `${a.market} 모의 매수` : a.action === "sell" ? `${a.market} 모의 매도` : "모의 계좌 확인",
    desc:"가상 계좌로 코인 현물 모의 매수·매도·잔고 확인 (업비트 1,000만원 / 바이낸스 10,000 USDT로 시작). buy는 amount(원화 또는 USDT), sell은 percent(보유 대비 %). 실제 돈은 쓰지 않는다",
    async run(a){
      const exn = normExchange(a.exchange) === "binance" ? "binance" : "upbit";
      const key = "tr:acct:" + exn, fee = exn === "upbit" ? 0.0005 : 0.001, start = exn === "upbit" ? 1e7 : 1e4, Q = exn === "upbit" ? "KRW" : "USDT";
      const acct = ls.get(key, null) || {cash: start, pos: {}, hist: [], start, created: Date.now()};
      const act = a.action || "status";
      if (act !== "status"){
        const m = resolveMarket(a.market, exn).market; const [t] = await ex(exn).tickers([m]); if (!t) throw new Error(m + " 시세를 받지 못했습니다"); const px = t.price;
        if (act === "buy"){
          const v = Math.min(+a.amount || 0, acct.cash); if (!(v > 0)) throw new Error("매수 금액이 없거나 현금이 부족합니다");
          const qty = v * (1 - fee) / px, p = acct.pos[m] || {qty: 0, avg: 0};
          p.avg = (p.avg * p.qty + px * qty) / (p.qty + qty); p.qty += qty; acct.pos[m] = p; acct.cash -= v;
          acct.hist.push({t: Date.now(), id: m, side: "buy", price: px, qty});
        } else if (act === "sell"){
          const p = acct.pos[m]; if (!p) throw new Error(m + " 보유 수량이 없습니다");
          const pc = Math.min(100, Math.max(0, a.percent ?? 100)), qty = p.qty * pc / 100;
          acct.cash += qty * px * (1 - fee); p.qty -= qty; if (pc >= 100 || p.qty <= 1e-12) delete acct.pos[m];
          acct.hist.push({t: Date.now(), id: m, side: "sell", price: px, qty});
        }
        ls.set(key, acct);
      }
      const ids = Object.keys(acct.pos); const prices = ids.length ? await ex(exn).tickers(ids) : [];
      const pos = ids.map(id => { const px = prices.find(x => x.id === id)?.price || acct.pos[id].avg; const p = acct.pos[id]; return {종목: id, 수량: +p.qty.toPrecision(6), 평균가: r6(p.avg), 현재가: r6(px), 평가금액: r6(p.qty * px), "수익률%": pct2(px / p.avg - 1)}; });
      const total = acct.cash + pos.reduce((s, p) => s + p.평가금액, 0);
      return {text: JSON.stringify({계좌: EX_LABEL[exn], 동작: act, 현금: r6(acct.cash), 보유: pos, 총자산: r6(total), "총수익률%": pct2(total / acct.start - 1), 거래수: acct.hist.length}), summary: `총자산 ${fmtNum(total, Q)} ${Q === "KRW" ? "원" : Q}`};
    }},

  /* ---- 건축 · 부동산 ---- */
  design_building: {mode:"chat", label:"건물 설계", args:'{"name":"판교 3층 주택","use":"house|multi|mixed|office|cafe","zone":"제2종일반주거","site":{"w":18,"d":22},"building":{"w":12,"d":10},"floors":3,"floorH":3,"style":"modern|concrete|brick|wood|glass","roof":"flat|gable","interior":"modern|scandi|industrial|natural|hanok|luxury","rooms":[{"floor":0,"name":"거실","type":"living|kitchen|bed|master|bath|study|shop|cafe|office|storage|terrace|garage","area":35}]}', act: a => `${a.name || "건물"} 설계`,
    desc:"건물 설계안을 3D·평면도·인테리어로 오른쪽 패널에 그리고 건폐율·용적률·연면적을 계산. 단위 m·㎡, 1평=3.3058㎡. 계단·복도는 자동. 패널에서 AutoCAD(DXF)·Revit(IFC)·SketchUp/루미온(DAE·OBJ) 파일을 내려받는다",
    async run(a, ctx){
      const spec = a.spec || a;
      const m = await ctx.openArtifact({type:"building", title: spec.name || "건물 설계", spec}, true);
      if (!m) return {text: JSON.stringify({결과: "패널에 설계를 표시했습니다"}), summary: "설계 표시"};
      ls.set("lastBuilding", {spec, metrics: m});
      return {text: JSON.stringify(m), summary: `연면적 ${m["연면적_㎡"]}㎡ · 건폐율 ${m["건폐율%"]}% · 용적률 ${m["용적률%"]}%`};
    }},
  cost_estimate: {mode:"chat", label:"견적서", args:'{"name":"판교 3층 주택 신축","scope":"신축|리모델링|인테리어","use":"house|multi|mixed|office|cafe|warehouse|factory","area_m2":250,"floors":3,"structure":"RC|steel|wood|masonry","grade":"economy|standard|premium|luxury","region":"경기 성남","client":"","extra":[{"name":"엘리베이터","amount":45000000}]}', act: a => `${a.name || "공사"} 견적서 작성`,
    desc:"면적·용도·구조·등급·지역으로 공종별 개략 공사비를 계산하고 인쇄 가능한 견적서를 패널에 연다. 방금 설계한 건물이면 그 연면적을 쓴다",
    async run(a, ctx){
      if (!a.area_m2 && !a.area_py){ const lb = ls.get("lastBuilding", null); if (lb?.metrics?.["연면적_㎡"]){ a.area_m2 = lb.metrics["연면적_㎡"]; a.use ||= lb.spec.use; a.floors ||= lb.spec.floors; a.name ||= (lb.spec.name || "설계안") + " 신축"; } }
      const e = estimate(a);
      ctx.openArtifact({type:"html", title:`견적서 · ${e.name}`, content: estimateHTML(e)});
      return {text: JSON.stringify({공사명: e.name, 구분: e.scope, "면적㎡": +e.area.toFixed(1), "㎡당직접공사비": Math.round(e.unit), 직접공사비: Math.round(e.dsum), 일반관리비: Math.round(e.overhead), 이윤: Math.round(e.profit), 설계감리비: Math.round(e.design), 부가세: Math.round(e.vat), 총액: Math.round(e.total), 평당총액: Math.round(e.perPy), 예상공기_개월: e.months, 공종: e.rows.map(r => `${r.name} ${won(r.amount)}`)}),
        summary: `총 ${(e.total / 1e8).toFixed(2)}억원 · 평당 ${Math.round(e.perPy / 1e4).toLocaleString()}만원`};
    }},
  land_check: {mode:"chat", label:"토지·재개발 분석", args:'{"address":"서울 성북구 장위동 123-4","zone":"제2종일반주거","area_m2":165,"question":"재개발 가능성"}', act: a => `${a.address || "토지"} 규제·재개발 조사`,
    desc:"주소·용도지역으로 건폐율·용적률 상한, 지을 수 있는 규모, 재개발·재건축·모아타운·가로주택 등 정비사업 가능성과 관련 법, 최신 뉴스를 조사한다",
    async run(a){
      const addr = String(a.address || "").trim(), z = zoneOf(a.zone), area = +a.area_m2 || (+a.area_py ? a.area_py * 3.3058 : 0);
      const region = addr.split(/\s+/).slice(0, 3).join(" ");
      const qs = addr ? [`${region} 재개발 정비구역 지정`, `${region} 신속통합기획 모아타운`, `${addr} 토지이용계획 용도지역`] : [`${a.question || "재개발 요건"} 도시정비법`];
      const results = (await searchMany(qs, 5)).slice(0, 12);
      const data = {
        주소: addr || "미입력", 용도지역: z ? z[0] + "지역" : (a.zone || "미확인 — 토지이음에서 확인 필요"),
        ...(z ? {"건폐율상한%": z[1], "용적률상한%": z[2], 비고: "국토계획법 시행령 상한. 실제는 지자체 도시계획조례로 더 낮음(예: 서울 제2종일반주거 용적률 200%)"} : {}),
        ...(z && area ? {"대지㎡": area, "최대건축면적㎡": +(area * z[1] / 100).toFixed(1), "최대연면적㎡(지상)": +(area * z[2] / 100).toFixed(1)} : {}),
        정비사업_판단요소: ["정비구역 또는 정비예정구역(도시·주거환경정비기본계획) 포함 여부", "노후·불량 건축물 비율(대개 전체의 2/3 이상, 조례로 다름)", "주택 접도율·과소/부정형 필지 비율·호수밀도", "신속통합기획·공공재개발 후보지 선정 여부(서울)", "모아타운(소규모주택정비 관리지역)·가로주택정비사업 요건(빈집및소규모주택정비법)", "토지등소유자 동의율(구역 지정 제안 시 대개 2/3, 조합설립 3/4)", "권리산정기준일 이후 지분 쪼개기 시 입주권 제한", "토지거래허가구역 지정 여부"],
        관련법: ["국토의 계획 및 이용에 관한 법률(용도지역·건폐율·용적률)", "건축법(대지·도로·높이·일조)", "도시 및 주거환경정비법(재개발·재건축)", "빈집 및 소규모주택 정비에 관한 특례법(가로주택·소규모재건축·모아타운)", "도시재정비 촉진을 위한 특별법(재정비촉진지구)", "부동산 거래신고 등에 관한 법률(토지거래허가)"],
        직접확인: LINKS,
        검색결과: srcText(results)
      };
      return {text: JSON.stringify(data), summary: `${z ? z[0] + " " + z[1] + "/" + z[2] + "% · " : ""}자료 ${results.length}건`, sources: results};
    }},
  realestate_search: {mode:"chat", label:"부동산 정보", args:'{"query":"마포구 아파트","kind":"listing|auction|price|news|policy"}', act: a => `${a.query} ${{listing:"매물", auction:"경매", price:"실거래가", news:"뉴스", policy:"정책"}[a.kind] || "부동산"} 조사`,
    desc:"부동산 매물 시세·법원경매/공매 물건·실거래가·개발 뉴스·정책을 인터넷에서 조사한다(공개 검색 기반, 실시간 매물 데이터베이스는 아님)",
    async run(a){
      const q = String(a.query || "").trim(), k = a.kind || "news";
      const Q = {listing: [`${q} 매물 시세 호가`, `${q} 아파트 시세`], auction: [`${q} 법원경매 감정가 매각기일`, `${q} 경매 물건 유찰`], price: [`${q} 실거래가 최근`, `${q} 매매 신고가`], news: [`${q} 부동산 개발 호재`, `${q} 부동산 뉴스`], policy: [`${q} 부동산 정책 규제`, `${q} 대출 규제 세금`]}[k] || [q + " 부동산"];
      const results = (await searchMany(Q, 6)).slice(0, 12);
      const links = k === "auction" ? {"대법원 법원경매정보": LINKS["대법원 법원경매정보"], "온비드 (공매)": LINKS["온비드 (공매)"]} : k === "price" ? {"국토부 실거래가": LINKS["국토부 실거래가"], "공시가격 알리미": LINKS["부동산 공시가격 알리미"]} : {"네이버 부동산": "https://new.land.naver.com", "국토부 실거래가": LINKS["국토부 실거래가"]};
      return {text: JSON.stringify({조회: q, 종류: k, 공식사이트: links, 검색결과: srcText(results)}), summary: `자료 ${results.length}건`, sources: results};
    }},
  render_image: {mode:"chat", label:"AI 렌더링", args:'{"prompt":"photorealistic exterior rendering of a 3-story modern concrete house, golden hour, lush landscaping","width":1024,"height":768}', act: () => "이미지 렌더링",
    desc:"NVIDIA 무료 이미지 AI로 투시도·인테리어 렌더 이미지를 만든다(NVIDIA 키 필요). prompt는 영어로 자세히(건물 형태·재료·층수·조명·시점). 방금 설계한 건물이면 그 특징을 담는다",
    async run(a, ctx){
      const key = settings.keys?.nvidia; if (!key) throw new Error("이미지 렌더링에는 NVIDIA API 키가 필요합니다 (설정 → AI 두뇌)");
      const model = settings.imageModel || "black-forest-labs/flux.1-dev";
      const W = Math.min(1344, Math.max(512, Math.round((+a.width || 1024) / 64) * 64)), H = Math.min(1344, Math.max(512, Math.round((+a.height || 768) / 64) * 64));
      const body = /schnell/.test(model) ? {prompt: a.prompt, width: W, height: H, seed: a.seed || 0, steps: 4} : /flux/.test(model) ? {prompt: a.prompt, mode: "base", cfg_scale: 3.5, width: W, height: H, seed: a.seed || 0, steps: 40} : {prompt: a.prompt, width: W, height: H, seed: a.seed || 0, steps: 30, cfg_scale: 5};
      const r = await fetch(apiBase("nvgenai") + "/" + model, {method: "POST", headers: {authorization: "Bearer " + key, "content-type": "application/json", accept: "application/json"}, body: JSON.stringify(body), signal: ctx.signal});
      if (!r.ok){ let m = ""; try { m = (await r.json()).detail || ""; } catch(e){} throw new Error(`이미지 AI 오류 ${r.status} ${String(m).slice(0, 120)}`); }
      const j = await r.json();
      const b64 = j.artifacts?.[0]?.base64 || j.image || j.data?.[0]?.b64_json;
      if (!b64) throw new Error("이미지를 받지 못했습니다" + (j.artifacts?.[0]?.finishReason ? " (" + j.artifacts[0].finishReason + ")" : ""));
      const src = b64.startsWith("data:") ? b64 : `data:image/${b64.startsWith("iVBOR") ? "png" : "jpeg"};base64,${b64}`;
      ctx.openArtifact({type: "image", title: a.title || "AI 렌더링", src, prompt: a.prompt});
      return {text: "이미지를 만들어 오른쪽 패널에 표시했습니다.", summary: `${shortModel(model)} · ${W}×${H}`};
    }},

  /* ---- 공용 ---- */
  search_knowledge: {mode:"both", label:"내 문서 검색", args:'{"query":"검색어"}', act: a => `내 문서에서 ‘${a.query}’ 찾기`,
    desc:"사용자가 '내 지식'에 올린 문서에서 관련 부분을 찾는다",
    async run(a){
      if (!docs.length) return {text: "저장된 문서가 없습니다.", summary: "문서 없음"};
      const hits = search(a.query || "", 5);
      return {text: hits.length ? hits.map((h, i) => `[${i+1}] 문서: ${h.name}\n${h.text}`).join("\n\n") : "관련 내용을 찾지 못했습니다.", summary: `${hits.length}건`};
    }},
  remember: {mode:"both", label:"기억하기", args:'{"fact":"사용자는 업비트를 쓰고 단타보다 스윙을 선호한다"}', act: () => "기억 저장",
    desc:"사용자가 기억해 달라고 하거나 앞으로도 도움이 될 사용자 정보·선호를 한 문장으로 저장한다. forget에 문구를 주면 그 기억을 지운다",
    async run(a){
      settings.memory ||= [];
      if (a.forget){ const before = settings.memory.length; settings.memory = settings.memory.filter(m => !m.text.includes(a.forget)); saveSettings(); return {text: `${before - settings.memory.length}개 기억을 지웠습니다.`, summary: "기억 삭제"}; }
      const fact = String(a.fact || "").trim().slice(0, 300); if (!fact) throw new Error("기억할 내용이 없습니다");
      if (!settings.memory.some(m => m.text === fact)) settings.memory.push({text: fact, t: Date.now()});
      settings.memory = settings.memory.slice(-60); saveSettings();
      return {text: "기억했습니다.", summary: fact.slice(0, 40)};
    }},
  calculate: {mode:"both", label:"계산", args:'{"expression":"(1200000*0.035)/12"}', act: a => String(a.expression || "계산").slice(0, 40),
    desc:"사칙연산·거듭제곱·Math 함수(sqrt, log, sin 등) 계산. 숫자 계산은 추측하지 말고 이 도구를 쓴다",
    async run(a){
      const e = String(a.expression || "");
      if (!/^[\d\s+\-*/%().,^eE]*$/.test(e.replace(/\b(Math\.)?(sqrt|log|log10|log2|exp|sin|cos|tan|abs|min|max|pow|round|floor|ceil|PI|E)\b/g, ""))) throw new Error("숫자와 연산자, Math 함수만 쓸 수 있습니다");
      const expr = e.replace(/\^/g, "**").replace(/\b(sqrt|log|log10|log2|exp|sin|cos|tan|abs|min|max|pow|round|floor|ceil|PI|E)\b/g, m => "Math." + m).replace(/Math\.Math\./g, "Math.");
      const v = Function(`"use strict"; return (${expr});`)();
      return {text: String(v), summary: `= ${typeof v === "number" ? v.toLocaleString("ko-KR", {maximumFractionDigits: 8}) : v}`};
    }},
  todo_write: {mode:"both", label:"할 일", risk:"read", args:'{"todos":[{"content":"할 일","status":"pending|in_progress|completed"}]}', act: () => "계획 갱신",
    desc:"여러 단계 작업(조사·분석·코딩)의 할 일 목록을 만들고 진행하면서 상태를 갱신한다. 3단계 이상일 때만 쓴다",
    async run(a){ const t = (a.todos || []).slice(0, 30); return {text: "할 일 목록을 갱신했습니다", summary: `${t.filter(x => x.status === "completed").length}/${t.length} 완료`, todos: t}; }},

  /* ---- 코드 모드 ---- */
  list_files: {mode:"code", label:"목록", risk:"read", args:'{"path":".","depth":2}', desc:"폴더 안 파일·하위 폴더 목록", act: a => `${a.path || "."} 둘러보기`,
    async run(a){ const r = await codeCall("ls", a); return {text: r.entries.join("\n") + (r.truncated ? "\n…(더 있음)" : ""), summary: `${r.entries.length}개 항목`}; }},
  read_file: {mode:"code", label:"읽기", risk:"read", args:'{"path":"src/app.js","offset":1,"limit":1500}', desc:"파일 내용을 줄 번호와 함께 읽는다", act: a => `${a.path} 읽기`,
    async run(a){ const r = await codeCall("read", a); return {text: r.content + (r.to < r.total_lines ? `\n…(${r.total_lines}줄 중 ${r.from}~${r.to}줄)` : ""), summary: `${r.to - r.from + 1}줄${r.to < r.total_lines ? ` / 전체 ${r.total_lines}줄` : ""}`}; }},
  find_files: {mode:"code", label:"파일 찾기", risk:"read", args:'{"pattern":"**/*.py"}', desc:"글롭 패턴으로 파일 경로를 찾는다", act: a => `${a.pattern} 찾기`,
    async run(a){ const r = await codeCall("glob", a); return {text: r.files.join("\n") || "없음", summary: `${r.files.length}개 파일`}; }},
  search_code: {mode:"code", label:"검색", risk:"read", args:'{"pattern":"정규식","glob":"*.js"}', desc:"파일 내용에서 정규식을 찾는다", act: a => `‘${a.pattern}’ 코드 검색`,
    async run(a){ const r = await codeCall("grep", a); return {text: r.matches.join("\n") || "일치하는 줄이 없습니다", summary: `${r.matches.length}곳`}; }},
  write_file: {mode:"code", label:"쓰기", risk:"write", args:'{"path":"src/new.js","content":"전체 내용"}', desc:"파일을 새로 만들거나 전체를 덮어쓴다. 기존 파일은 가능하면 edit_file을 쓴다", act: a => `${a.path} 쓰기`,
    async before(a){ const r = await codeCall("raw", {path: a.path}); return {old: r.content || "", exists: r.exists}; },
    async run(a, ctx, pre){ const r = await codeCall("write", a); return {text: `${r.created ? "생성" : "저장"}: ${r.path} (${r.bytes}바이트)`, summary: r.created ? "새 파일" : "덮어씀", diff: {path: r.path, old: pre?.old ?? r.old ?? "", new: a.content || ""}}; }},
  edit_file: {mode:"code", label:"수정", risk:"write", args:'{"path":"src/app.js","old_string":"바꿀 부분(정확히)","new_string":"새 내용","replace_all":false}', desc:"파일의 일부를 정확히 찾아 바꾼다. 먼저 read_file로 내용을 확인한다", act: a => `${a.path} 수정`,
    async before(a){ const r = await codeCall("raw", {path: a.path}); return {old: r.content || ""}; },
    async run(a, ctx, pre){ const r = await codeCall("edit", a); const old = pre?.old || ""; const nw = a.replace_all ? old.split(a.old_string).join(a.new_string) : old.replace(a.old_string, a.new_string); return {text: `수정: ${r.path} ${r.line}번째 줄 부근 (${r.replaced}곳)`, summary: `${r.replaced}곳 수정`, diff: {path: r.path, old, new: nw}}; }},
  run_command: {mode:"code", label:"실행", risk:"exec", args:'{"command":"npm test","timeout":120}', desc:"작업 폴더에서 명령을 실행한다 (윈도우는 cmd). 출력과 종료 코드를 돌려준다", act: a => `$ ${String(a.command || "").slice(0, 50)}`,
    async run(a){ const r = await codeCall("exec", a); return {text: `종료 코드 ${r.exit_code}${r.timed_out ? " (시간 초과)" : ""}\n${r.output}`, summary: `종료 코드 ${r.exit_code} · ${(r.ms/1000).toFixed(1)}초`, output: r.output, code: r.exit_code}; }}
};

/* ================= 스킬: 분야별 전문가 지침 (질문에 맞는 것만 켜진다) ================= */
export const BUILTIN_SKILLS = [
  {id: "market", name: "시장 분석가", icon: "📈", keys: /코인|비트|이더|리플|솔라나|알트|업비트|바이낸스|선물|롱|숏|레버리지|펀딩|주식|주가|종목|나스닥|코스피|코스닥|s&p|다우|원유|금값|환율|차트|매수|매도|시세|전망|분석|etf|btc|eth|nvda|tsla/i,
    tools: ["market_quote", "market_analyze", "market_list", "market_search", "web_search", "econ_calendar"],
    prompt: `- 순서: market_quote나 market_analyze로 실제 숫자를 확인 → 필요하면 web_search로 최근 뉴스·이슈 확인 → 정리.
- 답변 구성: ①현재 상황(가격·추세·지표 핵심 3~5개) ②강세/약세 근거 ③시나리오별 대응(상승·하락·횡보, 진입·손절·목표 구간) ④리스크.
- 코인 선물(binancef)은 펀딩비·미결제약정·롱숏비율을 해석하고, 레버리지 청산 위험과 포지션 크기(계좌의 1~2% 손실 한도)를 꼭 언급한다.
- 주식·지수·해외선물은 yahoo 시장이다. 한국 종목은 6자리 코드, 미국은 티커. 장 마감 시간대에는 마지막 종가임을 밝힌다.
- 확률적 표현을 쓰고 확정적 예언을 하지 않는다. 마지막에 한 줄로 '투자 판단과 책임은 본인에게 있다'고 알린다.`},
  {id: "macro", name: "거시경제 해설", icon: "🌐", keys: /경제|발표|지표|cpi|ppi|fomc|금리|연준|고용|실업|gdp|pce|인플레|파월|한국은행|기준금리|캘린더|일정/i,
    tools: ["econ_calendar", "web_search", "web_fetch", "market_quote"],
    prompt: `- 일정은 econ_calendar로, 결과·해석은 web_search로 최신 기사를 확인한다.
- 지표마다 '예상 대비 높으면/낮으면 → 달러·금리·주식·코인에 어떤 영향'을 표로 정리한다. 시간은 한국시간.`},
  {id: "backtest", name: "퀀트 전략", icon: "🧪", keys: /백테스트|전략|퀀트|승률|수익률|손절|익절|자동매매|모의투자|시스템/i,
    tools: ["market_backtest", "market_analyze", "paper_trade", "calculate"],
    prompt: `- 전략은 market_backtest로 실제 시험하고, 여러 조건을 비교할 땐 2~3번 돌려 표로 비교한다. 과최적화 위험을 알린다.
- 그냥 보유 대비 초과수익과 최대낙폭을 함께 본다. 수수료·슬리피지를 반영한다.`},
  {id: "arch", name: "건축 설계·견적", icon: "🏗️", keys: /건물|건축|설계|주택|집|평면|도면|층|카페|상가|사무실|인테리어|캐드|cad|레빗|revit|스케치업|sketchup|루미온|lumion|렌더|투시도|견적|공사비|시공|리모델링/i,
    tools: ["design_building", "cost_estimate", "render_image", "land_check", "calculate"],
    prompt: `- 설계 요청: 조건(대지 크기·용도지역·층수·용도·방 구성)이 부족하면 합리적 기본값을 가정해 바로 design_building으로 그리고, 가정한 내용을 밝힌다.
- 공사비·견적: cost_estimate로 견적서를 만든다(방금 설계했으면 면적 생략 가능).
- 렌더링(루미온 같은 투시도): render_image에 건물 특징을 영어로 자세히 묘사한다. 루미온·트윈모션에서 직접 렌더하려면 패널의 'SketchUp·루미온(DAE)' 또는 OBJ를 내려받아 가져오면 된다고 안내한다.
- 캐드는 DXF(AutoCAD에서 바로 열림), 레빗은 IFC(삽입 → IFC 열기), 스케치업은 DAE 가져오기.
- 건폐율·용적률은 법정 상한이고 조례로 더 낮을 수 있으며, 실제 인허가는 건축사 검토가 필요하다고 알린다.`},
  {id: "land", name: "부동산·토지·법규", icon: "🏘️", keys: /부동산|토지|땅|대지|용도지역|재개발|재건축|정비|모아타운|가로주택|신통|신속통합|경매|공매|낙찰|매물|시세|실거래|아파트|빌라|오피스텔|분양|청약|전세|월세|임대|양도세|취득세|보유세|종부세|법|규제|허가/i,
    tools: ["land_check", "realestate_search", "web_search", "web_fetch", "calculate"],
    prompt: `- 특정 토지·주소는 land_check로 규제와 재개발 판단요소를 정리하고, 정비구역·후보지 선정 여부는 검색 결과로 확인한다. 확인 못 한 것은 '토지이음에서 확인 필요'라고 분명히 쓴다.
- 매물·경매·실거래는 realestate_search로 조사한다. 실시간 매물 데이터베이스가 아니므로 날짜와 출처를 밝히고 공식 사이트 링크를 준다.
- 법·세금은 web_search로 국가법령정보센터(law.go.kr)·국세청 자료를 찾아 조문 이름을 인용하고, 개정 가능성과 전문가(세무사·변호사·법무사) 확인을 권한다.
- 재개발 가능성은 '높음/보통/낮음'처럼 단정하지 말고 근거별로 평가한다.`},
  {id: "research", name: "인터넷 리서치", icon: "🔎", keys: /검색|찾아|최신|뉴스|오늘|어제|요즘|현재|202\d|누구|언제|어디|가격|출시|발표|조사|리서치|비교|추천|후기|리뷰/i,
    tools: ["web_search", "web_fetch", "todo_write"],
    prompt: `- 최신·사실 정보는 기억으로 답하지 말고 web_search → 중요한 출처 1~3개 web_fetch → 종합한다.
- 문장 끝에 [1], [2]처럼 출처 번호를 달고, 마지막에 '출처' 목록(제목 — 주소)을 쓴다. 출처끼리 다르면 차이를 밝힌다.`},
  {id: "coding", name: "코딩", icon: "💻", keys: /코드|코딩|프로그램|함수|버그|에러|오류|파이썬|python|자바스크립트|javascript|typescript|html|css|react|sql|자바|c\+\+|api|스크립트|앱 만들|웹페이지|게임/i,
    tools: ["web_search"],
    prompt: `- 완결된 코드를 쓴다. 20줄 넘는 코드나 실행 가능한 웹페이지는 <artifact>로 감싼다. 웹앱·게임·계산기·대시보드는 type="html" 하나의 파일로 만들면 패널에서 바로 실행된다.
- 사용자 컴퓨터의 파일을 직접 고치려면 '코드' 모드를 쓰라고 안내한다.`}
];
export function activeSkills(text, mode = "chat"){
  const t = String(text || "");
  const out = mode === "code" ? [] : BUILTIN_SKILLS.filter(s => !(settings.skillsOff || []).includes(s.id) && s.keys.test(t));
  for (const s of settings.skills || []){
    if (s.off) continue;
    const keys = String(s.keys || "").split(/[,\s]+/).filter(Boolean);
    if (s.always || keys.some(k => t.toLowerCase().includes(k.toLowerCase()))) out.push({id: s.id, name: s.name, icon: "✨", tools: [], prompt: s.prompt, custom: true});
  }
  return out;
}
const CORE_TOOLS = ["web_search", "web_fetch", "calculate", "search_knowledge", "remember"];

/* ================= 시스템 지침 ================= */
export function systemPrompt(mode, extra = {}){
  const d = new Date(), skills = extra.skills || [];
  let tools = Object.entries(TOOLS).filter(([, t]) => t.mode === mode || t.mode === "both");
  // 작은 모델은 기억 공간이 좁으니 지금 필요한 도구만 알려준다
  if (mode === "chat" && brainCtx() < 16000){ const need = new Set([...CORE_TOOLS, ...skills.flatMap(s => s.tools || [])]); tools = tools.filter(([n]) => need.has(n)); }
  const toolDoc = tools.map(([n, t]) => `- ${n}: ${t.desc}\n  인자 예: ${t.args}`).join("\n");
  const mem = (settings.memory || []).slice(-30);
  const common = `오늘은 ${d.getFullYear()}년 ${d.getMonth()+1}월 ${d.getDate()}일 (${"일월화수목금토"[d.getDay()]}요일) ${d.getHours()}시다. 사용자가 쓰는 언어로 답한다(기본 한국어).
${settings.instructions ? `\n사용자 지침:\n${settings.instructions}\n` : ""}${mem.length ? `\n사용자에 대해 기억하는 것:\n${mem.map(m => "- " + m.text).join("\n")}\n` : ""}
## 도구
필요할 때 도구를 쓸 수 있다. 도구를 쓰려면 답변 중에 아래 형식으로 **한 번에 하나만** 쓰고, 바로 멈춘다.
<tool name="도구이름">{"인자":"값"}</tool>
그러면 <tool_result name="도구이름">결과</tool_result>가 돌아온다. 결과를 보고 이어서 답하거나 다른 도구를 쓴다. 도구 결과는 사용자에게 보이지 않으므로 중요한 내용은 답변에 정리한다.
도구 없이 답할 수 있으면 도구를 쓰지 않는다. 도구 결과를 지어내지 않는다. 모르는 최신 정보는 추측하지 말고 web_search를 쓴다.
사용자가 자신에 대해 오래 기억할 만한 정보(선호·상황)를 말하면 remember로 저장한다.
사용 가능한 도구:
${toolDoc}`;
  const skillDoc = skills.length ? `\n\n## 지금 켜진 전문 스킬\n${skills.map(s => `### ${s.name}\n${s.prompt}`).join("\n\n")}` : "";
  if (mode === "code") return `너는 '누리 코드'다. 사용자의 컴퓨터에 있는 작업 폴더(${extra.workspace || "미지정"})에서 코드를 읽고 고치고 실행하는 숙련된 소프트웨어 엔지니어다.
${common}

## 일하는 방식
- 먼저 list_files, find_files, search_code, read_file로 필요한 만큼 살펴본 뒤 고친다. 읽지 않은 파일을 고치지 않는다.
- 기존 파일은 edit_file로 필요한 부분만 바꾼다. old_string은 read_file에서 본 내용을 줄 번호 없이 정확히 옮긴다.
- 여러 단계 작업은 todo_write로 계획을 세우고 진행하면서 상태를 갱신한다.
- 라이브러리 사용법·오류 메시지가 낯설면 web_search로 확인한다.
- 고친 뒤에는 가능하면 테스트나 실행으로 확인한다(run_command). 실패하면 원인을 찾아 다시 고친다.
- 위험한 명령(대량 삭제, 포맷, 시스템 설정 변경)은 쓰지 않는다. 비밀번호·키를 출력하지 않는다.
- 답변은 짧고 분명하게. 끝나면 무엇을 바꿨는지 파일 기준으로 요약한다.${skillDoc}`;
  return `너는 '누리'라는 이름의 똑똑하고 친절한 AI 어시스턴트다. 무엇이든 자유롭게 대화하고 돕는다: 질문 답변, 글쓰기, 번역, 공부, 코딩, 인터넷 리서치, 코인·주식·선물·경제 분석, 건축 설계·견적·렌더링, 부동산·토지·법규.
${common}

## 결과물(아티팩트)
사용자가 따로 보관하거나 실행할 만한 긴 결과물(웹페이지·HTML 앱, 20줄 넘는 코드, 문서·보고서, SVG 그림)은 아래처럼 감싸면 오른쪽 패널에 따로 표시된다. 짧은 코드나 일반 대화에는 쓰지 않는다.
<artifact type="html|code|markdown|svg" title="제목" lang="python">내용</artifact>
HTML은 하나의 완결된 파일로 만든다(외부 파일 없이, 필요하면 CDN 스크립트는 가능).

## 답변 스타일
핵심부터 말하고, 비교·수치는 표로, 단계는 번호 목록으로. 불확실한 것은 불확실하다고 말한다. 투자·법률·세무는 일반 정보이며 최종 판단은 전문가 확인이 필요하다고 짧게 알린다. 실제 주문 기능은 없고 모의투자만 가능하다.${skillDoc}`;
}

/* ================= 대화 → 모델 메시지 ================= */
export function toModelMessages(history, budgetTokens){
  const approx = s => Math.ceil(s.length / 1.6);
  const turns = [];
  for (const m of history){
    if (m.role === "user"){
      let c = m.content || "";
      if (m.attach) c += m.attach.map(a => `\n\n[첨부 파일: ${a.name}]\n${a.text.slice(0, 60000)}`).join("");
      turns.push({role: "user", content: c});
      continue;
    }
    const parts = m.parts || [{type: "text", text: m.content || ""}];
    let buf = "";
    for (const p of parts){
      if (p.type === "text") buf += splitThink(p.text).body;
      else if (p.type === "tool" && p.status !== "pending"){
        buf += `\n<tool name="${p.name}">${JSON.stringify(p.input)}</tool>`;
        turns.push({role: "assistant", content: buf.trim()}); buf = "";
        const out = p.status === "denied" ? "사용자가 이 도구 실행을 거부했습니다." : p.status === "error" ? "오류: " + (p.error || "") : (p.modelText || "");
        turns.push({role: "user", content: `<tool_result name="${p.name}">${out.slice(0, 24000)}</tool_result>`});
      }
    }
    if (buf.trim()) turns.push({role: "assistant", content: buf.trim()});
  }
  // 기억 한도 안에서 최근 것부터
  const out = []; let used = 0;
  for (let i = turns.length - 1; i >= 0; i--){
    const t = approx(turns[i].content) + 8;
    if (used + t > budgetTokens && out.length){ break; }
    used += t; out.unshift(turns[i]);
  }
  while (out.length && out[0].role !== "user") out.shift();
  return out.reduce((acc, m) => { const l = acc[acc.length-1]; if (l && l.role === m.role) l.content += "\n\n" + m.content; else acc.push({...m}); return acc; }, []);
}

/* ================= 에이전트 실행 ================= */
const TOOL_RE = /<tool\s+name\s*=\s*["']?([\w-]+)["']?\s*>\s*([\s\S]*?)\s*(?:<\/tool>|$)/;
function parseArgs(s){
  s = String(s || "").trim().replace(/^```(?:json)?|```$/g, "").trim();
  if (!s) return {};
  try { return JSON.parse(s); } catch(e){}
  for (let k = 1; k <= 3; k++){ try { return JSON.parse(s + "}".repeat(k)); } catch(e){} }
  const m = s.match(/\{[\s\S]*\}/); if (m){ try { return JSON.parse(m[0]); } catch(e){} }
  throw new Error("도구 인자를 해석하지 못했습니다");
}
// 스트리밍 중 화면에 보일 글: 도구 호출 태그가 시작되면 그 앞까지만
export function visibleText(t){
  const i = t.search(/<tool[\s>]|<tool_result/);
  return i >= 0 ? t.slice(0, i) : t.replace(/<t?o?o?l?$/, "");
}
// 질문 종류 → 모델 역할 (자동 선택이 이 역할에 맞는 모델을 고른다)
export function roleFor(mode, text, think){
  if (mode === "code") return "code";
  if (think) return "reason";
  if (/코드|코딩|함수|버그|에러|파이썬|python|자바스크립트|javascript|html|css|sql|react|스크립트|프로그램/i.test(text)) return "code";
  if (/증명|수학|미적분|방정식|논리|퍼즐|최적화|알고리즘/.test(text)) return "reason";
  return "general";
}
const ROLE_KO = {general: "일반", code: "코딩", reason: "추론", fast: "빠름"};
const routeName = c => !c ? "" : c.id === "local" ? "내 기기" : c.id === "ollama" ? "Ollama" : (PROVIDERS[c.id]?.name || c.id);

export async function runAgent({mode, history, msg, signal, onUpdate, openArtifact, askPermission, workspace, think}){
  const maxSteps = mode === "code" ? 30 : 12;
  const userText = [...history].reverse().find(m => m.role === "user")?.content || "";
  const recent = history.filter(m => m.role === "user").slice(-3).map(m => m.content).join("\n");
  const skills = activeSkills(userText, mode).concat(activeSkills(recent, mode).filter(s => !activeSkills(userText, mode).some(x => x.id === s.id))).slice(0, 4);
  const role = roleFor(mode, userText, think);
  msg.skills = skills.map(s => ({id: s.id, name: s.name, icon: s.icon})); msg.qrole = role; msg.t0 = Date.now();
  if (skills.length) activity({kind: "skill", text: skills.map(s => s.name).join(" · ")});
  const sys = systemPrompt(mode, {workspace, skills});
  for (let step = 0; step < maxSteps; step++){
    if (signal.aborted) break;
    const budget = brainCtx() - brainAnswerLen() - Math.ceil(sys.length / 1.6) - 64;
    const messages = [{role: "system", content: sys}, ...toModelMessages([...history, msg], Math.max(800, budget))];
    const part = {type: "text", text: "", t0: Date.now()}; msg.parts.push(part);
    msg.phase = step ? "생각 정리 중" : "답변 준비 중"; onUpdate();
    let raw = "", cut = false;
    const route = await brainStream({messages, role, maxTokens: brainAnswerLen(), temperature: mode === "code" ? 0.2 : settings.temp, signal, think, stop: ["</tool>", "<tool_result"],
      onContent: d => { raw += d; part.tf ||= Date.now(); part.text = visibleText(raw); msg.phase = "답변 작성 중"; onUpdate(); },
      onThink: d => { part.tf ||= Date.now(); part.think = (part.think || "") + d; msg.phase = "생각하는 중"; onUpdate(); },
      onStats: st => { if (st.cut) cut = true; if (st.tps) msg.tps = st.tps; }});
    if (route && route.id){ msg.route = {id: route.id, model: route.model, name: routeName(route), role: ROLE_KO[role]}; }
    part.t1 = Date.now();
    const body = splitThink(raw).body;
    const m = body.match(TOOL_RE);
    if (!m || !TOOLS[m[1]]){
      part.text = visibleText(raw);
      if (cut) part.text += "\n\n*(답변 길이 한도에 닿아 끊겼습니다. '계속'이라고 보내면 이어서 씁니다.)*";
      if (m && !TOOLS[m[1]]) part.text += `\n\n*(알 수 없는 도구 '${m[1]}'를 부르려 해서 멈췄습니다.)*`;
      msg.phase = ""; msg.t1 = Date.now(); onUpdate(); return;
    }
    // 도구 호출
    part.text = visibleText(raw).trim();
    if (!part.text && !part.think) msg.parts.pop();
    const name = m[1], tool = TOOLS[name];
    const tp = {type: "tool", id: Math.random().toString(36).slice(2), name, label: tool.label, input: {}, status: "running", t0: Date.now()};
    msg.parts.push(tp);
    try { tp.input = parseArgs(m[2]); } catch(e){ tp.status = "error"; tp.error = e.message; tp.t1 = Date.now(); onUpdate(); continue; }
    try { tp.act = tool.act ? tool.act(tp.input) : tool.label; } catch(e){ tp.act = tool.label; }
    msg.phase = tp.act; activity({kind: "tool", text: tp.act, name});
    let pre = null;
    try {
      if (tool.before) pre = await tool.before(tp.input);
      if (tool.risk && tool.risk !== "read"){
        const need = settings.permission === "ask" || (settings.permission === "edits" && tool.risk === "exec");
        if (need){
          tp.status = "pending"; if (pre?.old !== undefined && tp.input.content !== undefined) tp.preview = {path: tp.input.path, old: pre.old, new: tp.input.content};
          if (name === "edit_file" && pre) tp.preview = {path: tp.input.path, old: pre.old, new: tp.input.replace_all ? pre.old.split(tp.input.old_string).join(tp.input.new_string) : pre.old.replace(tp.input.old_string, tp.input.new_string)};
          msg.phase = "허락 기다리는 중"; onUpdate();
          const ok = await askPermission(tp);
          delete tp.preview;
          if (!ok){ tp.status = "denied"; tp.t1 = Date.now(); onUpdate(); continue; }
        }
      }
      tp.status = "running"; msg.phase = tp.act; onUpdate();
      const r = await tool.run(tp.input, {openArtifact: (spec, wait) => { tp.artifact = spec; onUpdate(); return openArtifact(spec, wait); }, signal}, pre);
      tp.status = "done"; tp.modelText = r.text; tp.summary = r.summary; if (r.diff) tp.diff = r.diff; if (r.todos){ tp.todos = r.todos; msg.todos = r.todos; } if (r.output !== undefined){ tp.output = r.output; tp.code = r.code; }
      if (r.sources?.length){ tp.sources = r.sources.slice(0, 12).map(s => ({title: s.title, url: s.url})); msg.sources = [...(msg.sources || []), ...tp.sources.filter(s => !(msg.sources || []).some(x => x.url === s.url))].slice(0, 30); }
    } catch (e){
      if (signal.aborted){ tp.status = "error"; tp.error = "중단됨"; tp.t1 = Date.now(); onUpdate(); break; }
      tp.status = "error"; tp.error = e.message || String(e);
    }
    tp.t1 = Date.now();
    onUpdate();
  }
  msg.phase = ""; msg.t1 = Date.now(); onUpdate();
}
