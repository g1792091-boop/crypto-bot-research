// 30일 판정 (builder A, CONTRACT.md section 4). Before the verdict: the countdown, which accounts will be judged with
// how many already have the 30 closed trades a verdict needs (counts only: "진행 상황, 판정 아님"), and how the verdict
// works in plain words. After /api/checkpoint says ready: counts by status, the luck numbers and warnings, the paged
// rows with p, q and the reason, and the snapshot hash.
// HONESTY: nothing here hints at a pass or a fail before the verdict (no p-values, no ticks, no green/red per
// account); progress bars are the neutral accent colour; DeepSeek accounts appear only as group counts.
import {h, put, ui, fmt, motion} from "../core/pb.js";
import {expInfo, judgedProgress, progBar, verdictDate as vDate, MIN_TRADES} from "./home-shared.js";
import {seatsCard, powerCard, stamp, luckDots} from "./checkpoint-stage.js";

const ST_CLS = {"2차 통과": "good", "1차 합격": "good", "불합격": "bad", "보류": "thin", "관찰용": "thin"};
const ST_ORDER = ["2차 통과", "1차 합격", "불합격", "보류", "관찰용"];
const ST_MEAN = {"2차 통과": "1차 합격 뒤 다음 30일에도 통과", "1차 합격": "30건 이상 · 시작보다 많음 · 파산 아님 · 운 시험 통과",
  "불합격": "판정했지만 조건을 못 채움", "보류": "거래 30건 미만: 다음 판정 때 다시", "관찰용": "4시간봉 등 판정 밖 계좌"};
const FILTERS = [{id: "judged", label: "판정한 계좌"}, {id: "pass", label: "합격"}, {id: "불합격", label: "불합격"},
  {id: "보류", label: "보류"}, {id: "관찰용", label: "관찰용"}, {id: "all", label: "전체"}];

function steps() {
  const items = [
    ["사진 찍듯 저장", "30일째 09:00(한국)에 모든 계좌의 상태를 그대로 저장하고 해시로 잠급니다. 판정은 이 저장본만 읽습니다."],
    ["평가 금액", "잔고 + 열린 포지션의 손익(마크 가격) − 그 포지션을 닫을 때 드는 수수료·슬리피지."],
    ["거래 30건", `닫힌 거래가 ${MIN_TRADES}건이 안 되는 계좌는 '보류'입니다. 다음 판정 때 다시 봅니다.`],
    ["운 시험", `계좌마다 같은 봉, 같은 신호 횟수로 아무렇게나 사고파는 ${ui.botsKo().replace("같은 봉 ", "")}를 같은 기간 실제 시세로 돌립니다. 계좌보다 잘한 동전 봇의 비율이 p입니다.`],
    ["여러 계좌 보정", `계좌가 많으면 운으로 붙는 계좌가 생기므로 묶음(기존 36 · 딥시크 · 5분봉)마다 따로 보정합니다. 보정한 값이 q입니다. 서버 기준: ${ui.methodKo()}.`],
    ["1차 합격", "거래 30건 이상 · 시작 잔고보다 많음 · 파산 아님 · 운 시험 통과. 이 넷을 다 채워야 합니다."],
    ["2차 확인", "1차 합격 계좌는 다음 30일만 따로 다시 봅니다: 30건 이상, 그 기간 손익 플러스, 운 시험 다시 통과 → 2차 통과."],
  ];
  return h("ol", {class: "ck-steps"}, items.map(([t, p], i) => h("li", null, h("span", {class: "ck-n", "aria-hidden": "true"}, String(i + 1).padStart(2, "0")),
    h("div", null, h("b", null, t), h("p", null, p)))));
}

export async function mount(el, ctx) {
  ctx.setTitle("30일 판정");
  const st = {summary: null, board: null, ck: null, mode: null, filter: "judged"};
  const head = ui.screenHead("30일 판정", "계좌마다 동전 봇과 비교해 합격·불합격을 정하는 날");
  const body = h("div", {class: "ck-body"});
  el.append(head, body);

  // ================================================================ before the verdict
  const big = h("b", {class: "ck-d"}, "D-—");
  const when = h("span", {class: "ck-when"});
  const left = h("span", {class: "ck-left"});
  const dprog = h("div", {class: "prog", role: "progressbar", "aria-label": "30일 중 지난 날", "aria-valuemin": "0", "aria-valuemax": "30"}, h("i"));
  const dtext = h("span", {class: "ck-dtext"});
  const heroCard = ui.card({hero: true, cls: "ck-hero", label: "판정까지 남은 날"},
    h("div", {class: "home-hrow"}, ui.plate("30일 판정"), dtext),
    h("div", {class: "ck-big"}, big, h("div", {class: "ck-bigt"}, when, left)), dprog,
    h("p", {class: "ink2"}, `그날 계좌마다 ${ui.botsKo()}와 비교해서 합격·불합격을 정합니다. 그 전까지는 어떤 계좌도 합격도 불합격도 아닙니다. 지금 다른 화면에서 보이는 동전 봇 비교는 모두 '참고'입니다.`));
  const targetBody = h("div", {class: "stack"});
  const targetCard = ui.card({plate: "판정 대상", sub: "진행 상황, 판정 아님"}, targetBody);
  const howCard = ui.card({plate: "판정 방법", sub: "쉬운 말로"}, steps(),
    ui.disclosure("동전 봇은 어떻게 돌리나요 (자세히)", h("div", {class: "stack tight ink2 home-small"},
      h("p", null, "동전 봇은 계좌와 같은 규칙으로 거래합니다: 신호가 난 봉이 닫힐 때 다음 1분 시가에 들어가고, 손절은 신호 봉 ATR의 2배, 레버리지·비중 규칙, 사다리 익절 잠금, 마크 가격 강제청산, 잔고 10 USDT 미만 파산까지 같습니다."),
      h("p", null, "다른 점은 방향과 시점뿐입니다. 계좌가 그 기간에 낸 신호 횟수만큼 무작위로 롱·숏을 고릅니다 (롱 비율은 그 계좌 신호와 같게). 그래서 '같은 횟수로 아무렇게나 했을 때보다 나은가'를 묻는 시험입니다."),
      h("p", null, "5분봉 단타(릴스)의 동전 봇은 롱만, 릴스와 같은 청산 규칙(스윙 저점 손절 · 윗밴드 목표 · 96봉 시간 청산, 사다리 잠금 없음)으로 돕니다."),
      h("p", null, "4시간봉 계좌는 관찰용이라 판정하지 않고, 실제로 돌고 있는 동전 봇 계좌는 비교 기준입니다. 추가 계좌(복제·새 매매법)는 자기 시작일부터 30일이 지난 판정일에 따로 묶어 봅니다."))),
    h("p", {class: "muted home-small"}, "판정이 나오면 이 화면에 상태별 개수, 계좌마다 p·q·이유, 저장본 해시가 나옵니다."));

  // 판정 무대 (wave 2 part B): the seat map and what a 30-day verdict can tell (checkpoint-stage.js)
  const seats = seatsCard();
  const power = powerCard(ctx);
  power.load();

  function renderCountdown() {
    const x = expInfo(st.summary);
    if (!x) {
      big.textContent = "시작 전"; put(when, "봇이 아직 첫 계좌를 만들지 않았습니다"); put(left); dtext.textContent = "";
      return;
    }
    const ms = Math.max(0, x.verdictTs - Date.now());
    const dTxt = `D-${fmt.int(x.left)}`;
    if (big.textContent !== dTxt && /^D-\d/.test(big.textContent)) motion.flash(big);    // a new day, not the first paint
    big.textContent = dTxt;
    when.textContent = `${x.k > 1 ? `${x.k}번째 판정 · ` : "첫 판정 · "}${fmt.date(x.verdictTs)} 09:00 (한국 시각)`;
    left.textContent = ms > 0 ? `${fmt.dur(ms / 1000)}${ms >= 86400000 ? ` ${fmt.dur((ms % 86400000) / 1000)}` : ""} 남음` : "판정 시각이 지났습니다 · 결과를 기다리는 중";
    dtext.replaceChildren(h("b", null, `D+${x.day}`), ` / ${x.of}`);
    dprog.firstChild.style.setProperty("--p", Math.max(0, Math.min(100, x.day / x.of * 100)) + "%");
    dprog.setAttribute("aria-valuemax", String(x.of)); dprog.setAttribute("aria-valuenow", String(x.day));
  }

  const prevReady = new Map();          // group id -> the count shown last time (it counts from there when it grows)
  function renderTargets() {
    if (!st.board) return;
    const p = judgedProgress(st.board);
    const ready = (key, v) => { const el = ui.numFrom(prevReady.get(key), v, {format: "int"}); prevReady.set(key, v); return el; };
    const blocks = p.groups.map((g) => h("div", {class: "ck-grp"},
      h("div", {class: "ck-grph"}, h("b", null, g.ko), h("span", {class: "muted"}, `${g.tfs.map(fmt.tfKo).join("·")} · ${fmt.int(g.n)}개`)),
      h("div", {class: "home-ckp"}, h("span", null, `거래 ${MIN_TRADES}건을 넘은 계좌`), h("b", {class: "num"}, ready(g.id, g.ready), ` / ${fmt.int(g.n)}`)),
      progBar(g.n ? g.ready / g.n : 0, `${g.ko}: 거래 30건을 넘은 계좌 비율`),
      g.byTf.length > 1 ? h("div", {class: "ck-tfs"}, g.byTf.map((t) => h("span", null, `${fmt.tfKo(t.tf)} ${fmt.int(t.ready)}/${fmt.int(t.n)}`))) : null));
    const out = [
      h("div", {class: "ck-total"}, h("span", null, "판정 대상"), h("b", {class: "num"}, `${fmt.int(p.n)}개`),
        h("span", {class: "muted"}, `그중 거래 ${MIN_TRADES}건 넘음 `, ready("all", p.ready), "개")),
      h("div", {class: "ck-grps"}, blocks),
      h("ul", {class: "ck-out"},
        p.obs4h ? h("li", null, h("b", null, `4시간봉 ${fmt.int(p.obs4h)}개`), " · 관찰용 (판정 밖)") : null,
        p.flips ? h("li", null, h("b", null, `동전 봇 ${fmt.int(p.flips)}개`), " · 비교 기준 (판정 안 함)") : null,
        p.extras ? h("li", null, h("b", null, `추가 계좌 ${fmt.int(p.extras)}개`), " · 자기 시작일부터 30일 지난 판정일에 따로") : null),
      h("p", {class: "muted home-small"}, `거래 수만 셉니다. 합격·불합격을 미리 보여 주지 않습니다. 판정일에 ${MIN_TRADES}건이 안 된 계좌는 '보류'입니다. 판정 대상은 서버 설정(15분·30분·1시간, 5분봉 매매법은 5분)을 따릅니다.`),
    ];
    put(targetBody, out);
    const x = expInfo(st.summary);
    seats.update(st.board, st.summary, x && x.verdictTs);
  }

  // ================================================================ after the verdict
  const vHead = h("div", {class: "stack tight"});
  const vCounts = h("div", {class: "ck-counts"});
  const vLuck = h("div", {class: "stack tight"});
  const vWarn = h("div");
  const filt = ui.seg(FILTERS, st.filter, (id) => { st.filter = id; applyRows(false); }, {label: "판정 결과 고르기", scroll: true});
  const rows = ui.searchList({size: 10, placeholder: "계좌 이름·코드 찾기",
    match: (r, q) => r._name.toLowerCase().includes(q) || String(r.account_id).toLowerCase().includes(q),
    row: verdictRow, filters: filt, empty: "맞는 계좌가 없습니다"});
  const verdictCards = [
    ui.card({hero: true, plate: "판정 결과", cls: "ck-vhead"}, vHead, vCounts),
    ui.card({plate: "운으로 붙을 수 있는 수"}, vLuck, vWarn),
    ui.card({plate: "계좌별 결과"}, rows.el, ui.assume(null, "평가금 = 잔고 + 열린 포지션 손익 − 나갈 때 비용")),
  ];

  function nameOf(id) {
    const a = st.board && (st.board.accounts || []).find((x) => x.account_id === id);
    return a ? fmt.acctName(a) : fmt.idName(id);
  }
  function verdictRow(r) {
    const meta = [h("span", null, fmt.tfKo(r.timeframe)), r.stage ? h("span", null, String(r.stage)) : null,
      h("span", null, `거래 ${fmt.int(r.trades)}`), r.equity != null ? h("span", null, `평가금 ${fmt.money(r.equity)}`) : null,
      r.p != null ? h("span", {class: "mono"}, `p ${fmt.num(r.p, 4)}`) : null, r.q != null ? h("span", {class: "mono"}, `q ${fmt.num(r.q, 3)}`) : null];
    return h("div", {class: "lrow ck-row", role: "listitem"},
      h("span", {class: "rk"}, ui.pill(r.status, ST_CLS[r.status] || "", ST_MEAN[r.status])),
      h("a", {class: "lname", href: ctx.href("account", r.account_id), title: r.account_id}, r._name),
      h("span", {class: "ret"}),
      h("span", {class: "meta"}, meta),
      r.reason ? h("div", {class: "ck-reason"}, ui.moreText(String(r.reason), 2)) : null);
  }
  function applyRows(keep) {
    const v = st.ck;
    if (!v || !v.ready) return;
    const all = (v.rows || []).map((r) => ({...r, _name: nameOf(r.account_id)}));
    const f = st.filter;
    const pick = all.filter((r) => f === "all" ? true : f === "judged" ? r.status !== "보류" && r.status !== "관찰용"
      : f === "pass" ? r.status === "1차 합격" || r.status === "2차 통과" : r.status === f);
    rows.set(pick, keep);
  }
  function renderVerdict() {
    const v = st.ck;
    const c = v.counts || {};
    const x = expInfo(st.summary);
    put(vHead, stamp(v),
      h("p", {class: "ck-vt"}, `${v.day ?? "—"}일째 판정 · ${vDate(v.date)} 09:00 (한국 시각)`),
      h("p", {class: "muted home-small"}, "저장본 해시 ", h("span", {class: "mono", title: v.snapshot_sha256 || ""}, String(v.snapshot_sha256 || "—").slice(0, 12)),
        " · 판정은 이 저장본만 읽었습니다", x && x.verdictTs ? ` · 다음 판정 ${fmt.date(x.verdictTs)} 09:00` : ""));
    put(vCounts, ST_ORDER.map((s) => h("div", {class: ["stat", "ck-st", ST_CLS[s]]}, h("span", {class: "k"}, s), h("b", null, fmt.int(c[s] || 0)),
      h("span", {class: "s"}, ST_MEAN[s]))));
    put(vLuck,
      h("p", {class: "ink2"}, `검정한 계좌 ${fmt.int(v.tested)}개 중 운 시험 통과 ${fmt.int(v.luck_passed)}개. 운만으로도 합격처럼 보일 수 있는 수는 많아야 ${fmt.num(v.lucky_expected, 1)}개입니다 (보정을 안 했다면 ${fmt.num(v.lucky_if_uncorrected, 1)}개).`),
      h("p", {class: "muted home-small"}, v.method_ko ? `${v.method_ko} · p = 계좌보다 잘한 동전 봇 비율, q = 보정한 값`
        : `${v.n_bots ? `계좌마다 동전 봇 ${fmt.int(v.n_bots)}개와 비교` : ui.methodKo()}${v.alpha != null ? ` · 오류 한도 ${fmt.pct(v.alpha, 1, false)} 보정` : ""} · p = 계좌보다 잘한 동전 봇 비율, q = 보정한 값`),
      luckDots(v));
    const w = v.warnings || [];
    put(vWarn, w.length ? h("div", {class: "ck-warn", role: "note"}, h("b", null, "주의할 점"), h("ul", null, w.map((t) => h("li", null, String(t))))) : null);
    applyRows(true);
  }

  // ================================================================ which view
  function render() {
    const mode = st.ck && st.ck.ready ? "after" : "before";
    if (mode !== st.mode) {
      st.mode = mode;
      if (mode === "before") put(body, h("div", {class: "ck-grid"}, h("div", {class: "stack"}, heroCard, seats, targetCard), h("div", {class: "stack"}, power, howCard)));
      else put(body, h("div", {class: "stack"}, verdictCards, power, ui.card({plate: "판정 방법"}, ui.disclosure("일곱 단계 다시 보기", steps()))));
      motion.swap(body);
    }
    if (mode === "before") { renderCountdown(); renderTargets(); } else renderVerdict();
  }

  put(body, motion.shimmer(4, true));
  const [ck] = await Promise.all([ctx.store.need("checkpoint", 600000).catch((e) => e), ctx.store.need("summary", 60000).catch(() => null),
    ctx.store.need("board", 60000).catch(() => null)]);
  if (!ctx.alive()) return;
  if (ck instanceof Error) {
    put(body, ui.errorBox(ck, () => ctx.store.refresh("checkpoint").catch(() => {})));
  } else st.ck = ck;
  ctx.watch("summary", (s) => { if (s) { st.summary = s; if (st.ck) render(); } });
  ctx.watch("board", (b) => { if (b) { st.board = b; if (st.ck) render(); } });
  ctx.watch("checkpoint", (v) => { if (v) { st.ck = v; render(); } });
  ctx.every(60000, () => { if (st.mode === "before") renderCountdown(); }, {now: false});
}

export function unmount() {}
