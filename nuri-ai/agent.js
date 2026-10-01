// 누리 AI 에이전트: 어떤 모델이든 쓸 수 있는 글자 기반 도구 호출 규약 + 도구 모음 + 반복 실행
// 모델이 <tool name="도구">{"인자":"값"}</tool> 를 쓰면 실행하고 <tool_result>로 결과를 돌려준다.
import { settings, brainStream, brainCtx, brainAnswerLen, splitThink, search, docs, apiBase, codeCall, ls } from "./engine.js";
import { exchanges, computeAll, quantScore, levels, backtest, STRATS, fmtNum } from "./trade.js";

const TF = {"1":"1분","5":"5분","15":"15분","60":"1시간","240":"4시간","D":"일봉","W":"주봉"};
const r6 = v => v == null || !isFinite(v) ? null : +(+v).toPrecision(6);
const lastOf = a => { for (let i = a.length - 1; i >= 0; i--) if (a[i] != null) return a[i]; return null; };
let EXS = null;
const ex = name => (EXS || (EXS = exchanges(apiBase)))[name || "upbit"];
function normMarket(m, exn = "upbit"){
  m = String(m || "").trim().toUpperCase();
  if (!m) return exn === "upbit" ? "KRW-BTC" : "BTCUSDT";
  if (exn === "upbit"){ if (/^[A-Z0-9]+$/.test(m)) return "KRW-" + m; return m; }
  return m.replace(/^KRW-|-/g, "").replace(/(USDT)?$/, "USDT");
}
async function candlesFor(input, total){
  const exn = input.exchange === "binance" ? "binance" : "upbit";
  const market = normMarket(input.market, exn), tf = TF[input.timeframe] ? String(input.timeframe) : "60";
  const cs = await ex(exn).candles(market, tf, total);
  if (cs.length < 30) throw new Error("캔들 데이터가 부족합니다");
  return {exn, market, tf, cs};
}

/* ================= 도구 ================= */
export const TOOLS = {
  /* ---- 채팅 모드 ---- */
  coin_markets: {mode:"chat", label:"코인 시장 순위", args:'{"exchange":"upbit|binance","top":10}',
    desc:"거래대금 상위 코인 목록과 현재가·24시간 변동률",
    async run(a){
      const list = (await ex(a.exchange === "binance" ? "binance" : "upbit").list()).sort((x, y) => y.vol - x.vol).slice(0, Math.min(30, a.top || 10));
      return {text: JSON.stringify(list.map(m => ({종목: `${m.name} (${m.id})`, 현재가: r6(m.price), "24h변동%": +(m.chg * 100).toFixed(2), 거래대금: Math.round(m.vol)}))), summary: `${list.length}개 종목`};
    }},
  coin_price: {mode:"chat", label:"코인 현재가", args:'{"markets":["KRW-BTC","KRW-ETH"],"exchange":"upbit"}',
    desc:"코인 현재가, 24시간 고가·저가·변동률. 업비트는 KRW-기호, 바이낸스는 BTCUSDT 형식",
    async run(a){
      const exn = a.exchange === "binance" ? "binance" : "upbit";
      const ids = (Array.isArray(a.markets) ? a.markets : [a.markets || a.market]).filter(Boolean).map(m => normMarket(m, exn)).slice(0, 20);
      const t = await ex(exn).tickers(ids.length ? ids : [normMarket("", exn)]);
      return {text: JSON.stringify(t.map(x => ({종목: x.id, 현재가: r6(x.price), "24h변동%": +(x.chg * 100).toFixed(2), 고가: r6(x.hi), 저가: r6(x.lo)}))), summary: t.map(x => `${x.id} ${fmtNum(x.price, exn === "upbit" ? "KRW" : "USDT")}`).join(", ")};
    }},
  coin_analyze: {mode:"chat", label:"차트 분석", args:'{"market":"KRW-BTC","timeframe":"60","exchange":"upbit"}',
    desc:"캔들을 받아 이동평균·RSI·MACD·볼린저·ATR·지지저항·퀀트점수를 계산하고 오른쪽 패널에 차트를 연다. timeframe: 1,5,15,60,240,D,W",
    async run(a, ctx){
      const {exn, market, tf, cs} = await candlesFor(a, 200);
      const I = computeAll(cs), q = quantScore(cs, I), n = cs.length - 1, p = cs[n].c, lv = levels(cs.slice(-150), p);
      ctx.openArtifact({type:"trading", title:`${market} ${TF[tf]} 차트`, ex: exn, market, tf});
      const data = {종목: market, 봉: TF[tf], 현재가: r6(p), 기간: `${new Date(cs[0].t).toLocaleString("ko-KR")} ~ ${new Date(cs[n].t).toLocaleString("ko-KR")}`,
        MA20: r6(I.ma20[n]), MA60: r6(I.ma60[n]), MA120: r6(I.ma120[n]), RSI14: r6(I.rsi[n]), MACD히스토그램: r6(I.macd.hist[n]),
        볼린저상단: r6(I.bb.up[n]), 볼린저하단: r6(I.bb.lo[n]), "ATR%": I.atr[n] ? +(I.atr[n] / p * 100).toFixed(2) : null,
        거래량_20평균대비: I.vma[n] ? +(cs[n].v / I.vma[n]).toFixed(2) : null,
        퀀트점수: q.score, 판단: q.label, 근거: q.factors.map(f => `${f.label}(${f.pts > 0 ? "+" : ""}${f.pts})`),
        저항: lv.res.map(l => r6(l.p)), 지지: lv.sup.map(l => r6(l.p)), 최근종가20: cs.slice(-20).map(k => r6(k.c))};
      return {text: JSON.stringify(data), summary: `${market} ${TF[tf]} · 퀀트 ${q.score} ${q.label}`};
    }},
  coin_backtest: {mode:"chat", label:"전략 백테스트", args:'{"market":"KRW-BTC","timeframe":"60","strategy":"ma|rsi|bb|macd","params":{"fast":20,"slow":60},"fee":0.05,"stop_loss":0,"take_profit":0,"candles":500}',
    desc:"과거 캔들로 매매 전략을 시험해 수익률·최대낙폭·승률을 계산. 전략 params: ma{fast,slow} rsi{low,high} bb{n,k} macd{f,s,g}",
    async run(a, ctx){
      const key = STRATS[a.strategy] ? a.strategy : "ma";
      const {exn, market, tf, cs} = await candlesFor(a, Math.max(100, Math.min(1000, a.candles || 500)));
      const P = Object.fromEntries(STRATS[key].params.map(([k, , d]) => [k, a.params?.[k] ?? d]));
      const r = backtest(cs, key, P, {fee: a.fee ?? 0.05, sl: a.stop_loss || 0, tp: a.take_profit || 0});
      ctx.openArtifact({type:"trading", title:`${market} ${TF[tf]} 차트`, ex: exn, market, tf});
      const pf = r.pf === Infinity ? "∞" : +r.pf.toFixed(2);
      const res = {전략: STRATS[key].name, 조건: P, 종목: market, 봉: TF[tf], 캔들수: cs.length, "전략수익률%": +(r.ret * 100).toFixed(2), "그냥보유%": +(r.hold * 100).toFixed(2), "최대낙폭%": +(r.mdd * 100).toFixed(2), "보유시최대낙폭%": +(r.holdMdd * 100).toFixed(2), "승률%": +(r.win * 100).toFixed(1), 거래수: r.trades.length, 손익비: pf, 현재보유중: r.open,
        최근거래: r.trades.slice(-5).map(t => ({매수: r6(t.entry), 매도: r6(t.exit), "수익%": +(t.ret * 100).toFixed(2), 사유: t.why}))};
      return {text: JSON.stringify(res), summary: `${STRATS[key].name} ${res["전략수익률%"]}% (보유 ${res["그냥보유%"]}%)`};
    }},
  paper_trade: {mode:"chat", label:"모의투자", args:'{"action":"status|buy|sell","market":"KRW-BTC","amount":1000000,"percent":100}',
    desc:"가상 계좌(업비트 원화, 시작 1,000만원)로 모의 매수·매도·잔고 확인. buy는 amount(원), sell은 percent(보유 대비 %). 실제 돈은 쓰지 않는다",
    async run(a){
      const key = "tr:acct:upbit", fee = 0.0005;
      const acct = ls.get(key, null) || {cash: 1e7, pos: {}, hist: [], start: 1e7, created: Date.now()};
      const act = a.action || "status";
      if (act !== "status"){
        const m = normMarket(a.market, "upbit"); const [t] = await ex("upbit").tickers([m]); const px = t.price;
        if (act === "buy"){
          const v = Math.min(+a.amount || 0, acct.cash); if (!(v > 0)) throw new Error("매수 금액이 없거나 현금이 부족합니다");
          const qty = v * (1 - fee) / px, p = acct.pos[m] || {qty: 0, avg: 0};
          p.avg = (p.avg * p.qty + px * qty) / (p.qty + qty); p.qty += qty; acct.pos[m] = p; acct.cash -= v;
          acct.hist.push({t: Date.now(), id: m, side: "buy", price: px, qty});
        } else if (act === "sell"){
          const p = acct.pos[m]; if (!p) throw new Error(m + " 보유 수량이 없습니다");
          const pct = Math.min(100, Math.max(0, a.percent ?? 100)), qty = p.qty * pct / 100;
          acct.cash += qty * px * (1 - fee); p.qty -= qty; if (pct >= 100 || p.qty <= 1e-12) delete acct.pos[m];
          acct.hist.push({t: Date.now(), id: m, side: "sell", price: px, qty});
        }
        ls.set(key, acct);
      }
      const ids = Object.keys(acct.pos); const prices = ids.length ? await ex("upbit").tickers(ids) : [];
      const pos = ids.map(id => { const px = prices.find(x => x.id === id)?.price || acct.pos[id].avg; const p = acct.pos[id]; return {종목: id, 수량: +p.qty.toPrecision(6), 평균가: Math.round(p.avg), 현재가: r6(px), 평가금액: Math.round(p.qty * px), "수익률%": +((px / p.avg - 1) * 100).toFixed(2)}; });
      const total = acct.cash + pos.reduce((s, p) => s + p.평가금액, 0);
      return {text: JSON.stringify({동작: act, 현금: Math.round(acct.cash), 보유: pos, 총자산: Math.round(total), "총수익률%": +((total / acct.start - 1) * 100).toFixed(2), 거래수: acct.hist.length}), summary: `총자산 ${fmtNum(total, "KRW")}원`};
    }},
  design_building: {mode:"chat", label:"건물 설계", args:'{"name":"판교 3층 주택","use":"house|multi|mixed|office|cafe","zone":"제1종전용주거|제2종일반주거|제3종일반주거|준주거|일반상업|계획관리 등","site":{"w":18,"d":22},"building":{"w":12,"d":10},"floors":3,"floorH":3,"style":"modern|concrete|brick|wood|glass","roof":"flat|gable","interior":"modern|scandi|industrial|natural|hanok|luxury","rooms":[{"floor":0,"name":"거실","type":"living|kitchen|bed|master|bath|study|shop|cafe|office|storage|terrace|garage","area":35}]}',
    desc:"건물 설계안을 3D·평면도·인테리어로 오른쪽 패널에 그리고 건폐율·용적률·연면적·공사비를 계산. 단위 m·㎡, 1평=3.3058㎡. 계단·복도는 자동. Revit·AutoCAD·SketchUp 파일은 패널에서 내려받는다",
    async run(a, ctx){
      const spec = a.spec || a;
      const m = await ctx.openArtifact({type:"building", title: spec.name || "건물 설계", spec}, true);
      if (!m) return {text: JSON.stringify({결과: "패널에 설계를 표시했습니다"}), summary: "설계 표시"};
      return {text: JSON.stringify(m), summary: `연면적 ${m["연면적_㎡"]}㎡ · 건폐율 ${m["건폐율%"]}% · 용적률 ${m["용적률%"]}%`};
    }},
  search_knowledge: {mode:"both", label:"내 문서 검색", args:'{"query":"검색어"}',
    desc:"사용자가 '내 지식'에 올린 문서에서 관련 부분을 찾는다",
    async run(a){
      if (!docs.length) return {text: "저장된 문서가 없습니다.", summary: "문서 없음"};
      const hits = search(a.query || "", 5);
      return {text: hits.length ? hits.map((h, i) => `[${i+1}] 문서: ${h.name}\n${h.text}`).join("\n\n") : "관련 내용을 찾지 못했습니다.", summary: `${hits.length}건`};
    }},
  calculate: {mode:"both", label:"계산", args:'{"expression":"(1200000*0.035)/12"}',
    desc:"사칙연산·거듭제곱·Math 함수(sqrt, log, sin 등) 계산. 숫자 계산은 추측하지 말고 이 도구를 쓴다",
    async run(a){
      const e = String(a.expression || "");
      if (!/^[\d\s+\-*/%().,^eE]*$/.test(e.replace(/\b(Math\.)?(sqrt|log|log10|log2|exp|sin|cos|tan|abs|min|max|pow|round|floor|ceil|PI|E)\b/g, ""))) throw new Error("숫자와 연산자, Math 함수만 쓸 수 있습니다");
      const expr = e.replace(/\^/g, "**").replace(/\b(sqrt|log|log10|log2|exp|sin|cos|tan|abs|min|max|pow|round|floor|ceil|PI|E)\b/g, m => "Math." + m).replace(/Math\.Math\./g, "Math.");
      const v = Function(`"use strict"; return (${expr});`)();
      return {text: String(v), summary: `= ${typeof v === "number" ? v.toLocaleString("ko-KR", {maximumFractionDigits: 8}) : v}`};
    }},

  /* ---- 코드 모드 ---- */
  list_files: {mode:"code", label:"목록", risk:"read", args:'{"path":".","depth":2}', desc:"폴더 안 파일·하위 폴더 목록",
    async run(a){ const r = await codeCall("ls", a); return {text: r.entries.join("\n") + (r.truncated ? "\n…(더 있음)" : ""), summary: `${r.entries.length}개 항목`}; }},
  read_file: {mode:"code", label:"읽기", risk:"read", args:'{"path":"src/app.js","offset":1,"limit":1500}', desc:"파일 내용을 줄 번호와 함께 읽는다",
    async run(a){ const r = await codeCall("read", a); return {text: r.content + (r.to < r.total_lines ? `\n…(${r.total_lines}줄 중 ${r.from}~${r.to}줄)` : ""), summary: `${r.to - r.from + 1}줄${r.to < r.total_lines ? ` / 전체 ${r.total_lines}줄` : ""}`}; }},
  find_files: {mode:"code", label:"파일 찾기", risk:"read", args:'{"pattern":"**/*.py"}', desc:"글롭 패턴으로 파일 경로를 찾는다",
    async run(a){ const r = await codeCall("glob", a); return {text: r.files.join("\n") || "없음", summary: `${r.files.length}개 파일`}; }},
  search_code: {mode:"code", label:"검색", risk:"read", args:'{"pattern":"정규식","glob":"*.js"}', desc:"파일 내용에서 정규식을 찾는다",
    async run(a){ const r = await codeCall("grep", a); return {text: r.matches.join("\n") || "일치하는 줄이 없습니다", summary: `${r.matches.length}곳`}; }},
  write_file: {mode:"code", label:"쓰기", risk:"write", args:'{"path":"src/new.js","content":"전체 내용"}', desc:"파일을 새로 만들거나 전체를 덮어쓴다. 기존 파일은 가능하면 edit_file을 쓴다",
    async before(a){ const r = await codeCall("raw", {path: a.path}); return {old: r.content || "", exists: r.exists}; },
    async run(a, ctx, pre){ const r = await codeCall("write", a); return {text: `${r.created ? "생성" : "저장"}: ${r.path} (${r.bytes}바이트)`, summary: r.created ? "새 파일" : "덮어씀", diff: {path: r.path, old: pre?.old ?? r.old ?? "", new: a.content || ""}}; }},
  edit_file: {mode:"code", label:"수정", risk:"write", args:'{"path":"src/app.js","old_string":"바꿀 부분(정확히)","new_string":"새 내용","replace_all":false}', desc:"파일의 일부를 정확히 찾아 바꾼다. 먼저 read_file로 내용을 확인한다",
    async before(a){ const r = await codeCall("raw", {path: a.path}); return {old: r.content || ""}; },
    async run(a, ctx, pre){ const r = await codeCall("edit", a); const old = pre?.old || ""; const nw = a.replace_all ? old.split(a.old_string).join(a.new_string) : old.replace(a.old_string, a.new_string); return {text: `수정: ${r.path} ${r.line}번째 줄 부근 (${r.replaced}곳)`, summary: `${r.replaced}곳 수정`, diff: {path: r.path, old, new: nw}}; }},
  run_command: {mode:"code", label:"실행", risk:"exec", args:'{"command":"npm test","timeout":120}', desc:"작업 폴더에서 명령을 실행한다 (윈도우는 cmd). 출력과 종료 코드를 돌려준다",
    async run(a){ const r = await codeCall("exec", a); return {text: `종료 코드 ${r.exit_code}${r.timed_out ? " (시간 초과)" : ""}\n${r.output}`, summary: `종료 코드 ${r.exit_code} · ${(r.ms/1000).toFixed(1)}초`, output: r.output, code: r.exit_code}; }},
  todo_write: {mode:"code", label:"할 일", risk:"read", args:'{"todos":[{"content":"할 일","status":"pending|in_progress|completed"}]}', desc:"여러 단계 작업의 할 일 목록을 만들고 진행 상황을 갱신한다",
    async run(a){ const t = (a.todos || []).slice(0, 30); return {text: "할 일 목록을 갱신했습니다", summary: `${t.filter(x => x.status === "completed").length}/${t.length} 완료`, todos: t}; }}
};

/* ================= 시스템 지침 ================= */
export function systemPrompt(mode, extra = {}){
  const d = new Date();
  const tools = Object.entries(TOOLS).filter(([, t]) => t.mode === mode || t.mode === "both");
  const toolDoc = tools.map(([n, t]) => `- ${n}: ${t.desc}\n  인자 예: ${t.args}`).join("\n");
  const common = `오늘은 ${d.getFullYear()}년 ${d.getMonth()+1}월 ${d.getDate()}일이다. 사용자가 쓰는 언어로 답한다(기본 한국어).
${settings.instructions ? `\n사용자 지침:\n${settings.instructions}\n` : ""}
## 도구
필요할 때 도구를 쓸 수 있다. 도구를 쓰려면 답변 중에 아래 형식으로 **한 번에 하나만** 쓰고, 바로 멈춘다.
<tool name="도구이름">{"인자":"값"}</tool>
그러면 <tool_result name="도구이름">결과</tool_result>가 돌아온다. 결과를 보고 이어서 답하거나 다른 도구를 쓴다. 도구 결과는 사용자에게 보이지 않으므로 중요한 내용은 답변에 정리한다.
도구 없이 답할 수 있으면 도구를 쓰지 않는다. 도구 결과를 지어내지 않는다.
사용 가능한 도구:
${toolDoc}`;
  if (mode === "code") return `너는 '누리 코드'다. 사용자의 컴퓨터에 있는 작업 폴더(${extra.workspace || "미지정"})에서 코드를 읽고 고치고 실행하는 숙련된 소프트웨어 엔지니어다.
${common}

## 일하는 방식
- 먼저 list_files, find_files, search_code, read_file로 필요한 만큼 살펴본 뒤 고친다. 읽지 않은 파일을 고치지 않는다.
- 기존 파일은 edit_file로 필요한 부분만 바꾼다. old_string은 read_file에서 본 내용을 줄 번호 없이 정확히 옮긴다.
- 여러 단계 작업은 todo_write로 계획을 세우고 진행하면서 상태를 갱신한다.
- 고친 뒤에는 가능하면 테스트나 실행으로 확인한다(run_command). 실패하면 원인을 찾아 다시 고친다.
- 위험한 명령(대량 삭제, 포맷, 시스템 설정 변경)은 쓰지 않는다. 비밀번호·키를 출력하지 않는다.
- 답변은 짧고 분명하게. 끝나면 무엇을 바꿨는지 파일 기준으로 요약한다.`;
  return `너는 '누리'라는 이름의 똑똑하고 친절한 AI 어시스턴트다. 무엇이든 돕는다: 질문 답변, 글쓰기, 번역, 공부, 코딩, 코인 시장 분석, 건축 설계.
${common}

## 결과물(아티팩트)
사용자가 따로 보관하거나 실행할 만한 긴 결과물(웹페이지·HTML 앱, 20줄 넘는 코드, 문서, SVG 그림)은 아래처럼 감싸면 오른쪽 패널에 따로 표시된다. 짧은 코드나 일반 대화에는 쓰지 않는다.
<artifact type="html|code|markdown|svg" title="제목" lang="python">내용</artifact>
HTML은 하나의 완결된 파일로 만든다(외부 파일 없이, 필요하면 CDN 스크립트는 가능).

## 코인·투자
시세와 지표는 반드시 도구로 확인하고 숫자를 지어내지 않는다. 가격 예측은 확률적으로 말하고, 투자 판단의 책임은 사용자에게 있음을 짧게 알린다. 실제 주문 기능은 없고 모의투자만 가능하다.

## 건축
설계 요청은 design_building으로 그린다. 건폐율·용적률은 국토계획법 시행령 상한 기준이며 지자체 조례로 더 낮을 수 있다고 알린다.`;
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

export async function runAgent({mode, history, msg, signal, onUpdate, openArtifact, askPermission, workspace, think}){
  const maxSteps = mode === "code" ? 30 : 8;
  const sys = systemPrompt(mode, {workspace});
  for (let step = 0; step < maxSteps; step++){
    if (signal.aborted) break;
    const budget = brainCtx() - brainAnswerLen() - Math.ceil(sys.length / 1.6) - 64;
    const messages = [{role: "system", content: sys}, ...toModelMessages([...history, msg], Math.max(800, budget))];
    const part = {type: "text", text: ""}; msg.parts.push(part);
    let raw = "", cut = false;
    await brainStream({messages, maxTokens: brainAnswerLen(), temperature: mode === "code" ? 0.2 : settings.temp, signal, think, stop: ["</tool>", "<tool_result"],
      onContent: d => { raw += d; part.text = visibleText(raw); onUpdate(); },
      onThink: d => { part.think = (part.think || "") + d; onUpdate(); },
      onStats: st => { if (st.cut) cut = true; if (st.tps) msg.tps = st.tps; }});
    const body = splitThink(raw).body;
    const m = body.match(TOOL_RE);
    if (!m || !TOOLS[m[1]]){
      part.text = visibleText(raw);
      if (cut) part.text += "\n\n*(답변 길이 한도에 닿아 끊겼습니다. '계속'이라고 보내면 이어서 씁니다.)*";
      if (m && !TOOLS[m[1]]) part.text += `\n\n*(알 수 없는 도구 '${m[1]}'를 부르려 해서 멈췄습니다.)*`;
      onUpdate(); return;
    }
    // 도구 호출
    part.text = visibleText(raw).trim();
    if (!part.text && !part.think) msg.parts.pop();
    const name = m[1], tool = TOOLS[name];
    const tp = {type: "tool", id: Math.random().toString(36).slice(2), name, label: tool.label, input: {}, status: "running"};
    msg.parts.push(tp);
    try { tp.input = parseArgs(m[2]); } catch(e){ tp.status = "error"; tp.error = e.message; onUpdate(); continue; }
    let pre = null;
    try {
      if (tool.before) pre = await tool.before(tp.input);
      if (tool.risk && tool.risk !== "read"){
        const need = settings.permission === "ask" || (settings.permission === "edits" && tool.risk === "exec");
        if (need){
          tp.status = "pending"; if (pre?.old !== undefined && tp.input.content !== undefined) tp.preview = {path: tp.input.path, old: pre.old, new: tp.input.content};
          if (name === "edit_file" && pre) tp.preview = {path: tp.input.path, old: pre.old, new: tp.input.replace_all ? pre.old.split(tp.input.old_string).join(tp.input.new_string) : pre.old.replace(tp.input.old_string, tp.input.new_string)};
          onUpdate();
          const ok = await askPermission(tp);
          delete tp.preview;
          if (!ok){ tp.status = "denied"; onUpdate(); continue; }
        }
      }
      tp.status = "running"; onUpdate();
      const r = await tool.run(tp.input, {openArtifact: (spec, wait) => { tp.artifact = spec; onUpdate(); return openArtifact(spec, wait); }, signal}, pre);
      tp.status = "done"; tp.modelText = r.text; tp.summary = r.summary; if (r.diff) tp.diff = r.diff; if (r.todos) tp.todos = r.todos; if (r.output !== undefined){ tp.output = r.output; tp.code = r.code; }
    } catch (e){
      if (signal.aborted){ tp.status = "error"; tp.error = "중단됨"; onUpdate(); break; }
      tp.status = "error"; tp.error = e.message || String(e);
    }
    onUpdate();
  }
}
