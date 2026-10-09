// #/strategies 매매법 (CONTRACT 9.8): one card per strategy (S2_ST_ROC, N02_ST_KST, N04_ST_KLINGER): what its indicators
// do in plain Korean, when it goes in, the settings grid (/api/grid), the default / friend / 5-year pick values, their
// 5-year results with the house exit (/api/setting: the shipped past5y files) and the accounts that run it; then the
// private plug-in accounts (kind "private"): their name and rule_ko only (their rules never enter this code).
// Round 5 stage 2B (the rule bot's v4 매매법 list → detail look): the three strategies as v4 group cards (the pixel
// character, settings and accounts, the median P&L % of their accounts' 20배 lines); the chosen one opens below in
// two columns (what it reads and when it goes in · the settings grid, the marked values, the 5-year table, its accounts
// as tiles). The long indicator texts are cut to three lines with 더 보기. The choice is remembered on this device.
import {h, put, local} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
import * as K4 from "../v4kit.js";
import {isMissing} from "../api.js";
import {STRAT_KO, SUB_KO, KIND_KO, tfKo} from "../labels.js";

// written for the two owners: what each indicator measures, in plain words (the locked rules: research/entry_study)
const ABOUT = {
  S2: {
    parts: [
      ["슈퍼트렌드 (Supertrend)", "가격 위아래로 '평균 흔들림 폭(ATR) × 배수'만큼 떨어진 선을 긋습니다. 가격이 그 선을 뚫으면 선이 반대편으로 뒤집힙니다. 뒤집히는 순간이 '추세가 바뀌었다'는 신호이고, 선이 아래에 있으면 오름세, 위에 있으면 내림세로 봅니다."],
      ["ROC (변화 속도)", "Rate of Change: 지금 가격이 몇 봉 전보다 몇 % 올랐나(내렸나)입니다. 0보다 크면 오르는 힘, 작으면 내리는 힘이 있다는 뜻입니다."],
    ],
    rule: "롱: 슈퍼트렌드가 오름세이고 ROC가 0보다 클 때, 슈퍼트렌드가 막 위로 뒤집혔거나 ROC가 막 0을 위로 넘은 봉에서 들어갑니다. 숏은 그 반대입니다.",
    dims: {st_atr_len: "ATR을 재는 봉 수 (짧을수록 빨리 반응)", st_mult: "선을 얼마나 멀리 둘지 (클수록 덜 뒤집힘 = 신호 적음)", roc_len: "몇 봉 전 가격과 비교할지"},
  },
  N02: {
    parts: [
      ["슈퍼트렌드 (Supertrend)", "S2와 같은 추세선입니다. 선이 뒤집히면 추세가 바뀐 것으로 봅니다."],
      ["KST (Know Sure Thing)", "길이가 다른 ROC 네 개(10·15·20·30봉)를 각각 부드럽게 만든 뒤 무게를 달리해 더한 '힘의 선'입니다. 이 선이 자기 평균선(신호선)을 위로 뚫으면 오르는 힘이 붙었다고, 아래로 뚫으면 내리는 힘이 붙었다고 봅니다."],
    ],
    rule: "롱: 슈퍼트렌드가 오름세이고 최근 2봉 안에 KST가 신호선을 위로 뚫었으며, 그 봉에 KST가 뚫었거나 슈퍼트렌드가 위로 뒤집혔을 때 들어갑니다. 숏은 그 반대입니다.",
    dims: {st_atr_len: "슈퍼트렌드 ATR 봉 수", st_mult: "슈퍼트렌드 선의 거리 배수", kst_scale: "KST 네 기간(10·15·20·30봉)을 몇 배로 늘릴지 (크면 느리고 부드러움)", kst_signal_len: "신호선(평균)을 낼 봉 수"},
  },
  N04: {
    parts: [
      ["슈퍼트렌드 (Supertrend)", "S2와 같은 추세선입니다. 선이 뒤집히면 추세가 바뀐 것으로 봅니다."],
      ["클링거 (Klinger 거래량 오실레이터)", "가격이 오르는 봉의 거래량은 더하고 내리는 봉의 거래량은 빼서 '돈이 들어오나 나가나'를 잽니다. 빠른 평균(34봉)과 느린 평균(55봉)의 차이를 보고, 그 차이가 신호선을 위로 뚫으면 거래량이 오름을 받쳐 준다고 봅니다."],
    ],
    rule: "롱: 슈퍼트렌드가 오름세이고 최근 2봉 안에 클링거가 신호선을 위로 뚫었으며, 그 봉에 클링거가 뚫었거나 슈퍼트렌드가 위로 뒤집혔을 때 들어갑니다. 숏은 그 반대입니다.",
    dims: {st_atr_len: "슈퍼트렌드 ATR 봉 수", st_mult: "슈퍼트렌드 선의 거리 배수", kvo_scale: "클링거의 34·55봉 평균을 몇 배로 늘릴지", kvo_signal_len: "클링거 신호선(평균) 봉 수"},
  },
};
const PERIODS_SHOWN = ["2020", "2021-23", "2024-26"];
const valKo = (v) => (Number.isInteger(v) ? String(v) : fmt.num(v, v < 1 ? 2 : 1).replace(/0$/, "").replace(/\.$/, ""));

/** A text cut to `lines` lines with 더 보기 (v4 ui.moreText; components.css .clamp / .more). */
function moreText(text, lines = 3, cls) {
  const body = h("p", {class: ["clamp", cls], style: {"--lines": lines}}, text);
  const btn = h("button", {class: "more", type: "button", hidden: true, "aria-expanded": "false"}, "더 보기");
  btn.addEventListener("click", () => {
    const open = btn.getAttribute("aria-expanded") !== "true";
    btn.setAttribute("aria-expanded", String(open));
    btn.textContent = open ? "접기" : "더 보기";
    body.style.setProperty("--full", K4.reduced() ? "none" : body.scrollHeight + "px");
    body.classList.toggle("open", open);
  });
  const check = () => { if (btn.getAttribute("aria-expanded") !== "true" && body.isConnected) btn.hidden = !(body.scrollHeight > body.clientHeight + 2); };
  requestAnimationFrame(check);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(check, () => {});
  return h("div", {class: "s2-moretext"}, body, btn);
}

export async function mount(el, ctx) {
  ctx.setTitle("매매법");
  const cardsSec = h("section", {class: "k4-sec", "aria-label": "세 매매법"});
  const box = h("div", {class: "stack"});
  const priv = h("div");
  el.append(ui.screenHead("매매법", "세 매매법이 무엇을 보고 들어가나"),
    ui.card({hero: true, plate: "한 줄로"},
      h("p", {class: "dl-lead"}, "세 매매법 모두 ", h("b", null, "슈퍼트렌드로 추세 방향"), "을 잡고, 두 번째 지표(ROC · KST · 클링거)로 ",
        h("b", null, "힘이 붙는 순간"), "을 골라 들어갑니다. 나가는 방법(청산 14가지)은 따로 고르고, 설정 순위가 모든 설정 × 청산을 실시간으로 겨룹니다.")),
    cardsSec, box, priv,
    ui.note("5년 성적: 5년 연구에서 같은 설정을 사다리 청산으로 돌렸을 때의 평균 R (수수료 후, 코인 7개 합침). 기간마다 시장이 달라서, 세 기간 모두 비슷해야 믿을 만합니다."));

  let grid, accts;
  try {
    [grid, accts] = await Promise.all([ctx.api("/api/grid"), ctx.api("/api/accounts").catch(() => null)]);
  } catch (e) {
    if (e && e.name === "AbortError") return;
    put(box, ui.errorBox(e, () => location.reload()));
    return;
  }
  const list = accts && !isMissing(accts) ? accts.accounts || [] : [];
  const strats = grid.strategies || [];
  let sel = String(local.get("strategies-pick", strats[0] ? strats[0].short : "S2"));
  if (!strats.some((s) => s.short === sel)) sel = strats[0] ? strats[0].short : sel;
  const cards = new Map(strats.map((s) => [s.short, {s, past: h("div", {class: "g4-past"}, ui.empty("5년 성적을 읽는 중…"))}]));
  const pnl20 = (a) => { const x = (a.lines || {})["20"]; return x && x.pnl_pct != null && Number.isFinite(Number(x.pnl_pct)) ? Number(x.pnl_pct) : null; };

  // the three strategies as v4 group cards (tap one: it opens below)
  const groups = K4.groupCards({label: "매매법 고르기", onPick: (id) => { if (id === sel) return; sel = id; local.set("strategies-pick", id); paintCards(); paintDetail(true); }});
  function paintCards() {
    groups.update(strats.map((s) => {
      const mine = list.filter((a) => a.short === s.short);
      const meds = mine.map(pnl20).filter((v) => v != null);
      return {id: s.short, name: `${s.short} · ${STRAT_KO[s.short] || s.id}`, count: `설정 ${fmt.int(s.settings)}가지 · 계좌 ${fmt.int(mine.length)}개`,
        med: K4.median(meds), vs: meds.length ? `계좌 ${fmt.int(meds.length)}개의 20배 줄 손익 %` : "계좌 자료 준비 중",
        foot: `기본값 ${s.default || "—"}`, title: s.id};
    }), sel);
    // each card's name after its pixel character: the same character as its accounts (v4 stratFigure)
    for (const b of groups.querySelectorAll(".k4-gcard")) {
      const s = strats.find((x) => x.short === b.dataset.kind), gn = b.querySelector(".gn");
      if (s && gn && !gn.querySelector(".sfig")) gn.prepend(K4.acctFig({kind: "fixed", id: s.short, short: s.short}, 20));
    }
  }
  put(cardsSec, K4.secRow("세 매매법", "카드를 누르면 아래에 그 매매법이 펼쳐집니다"), groups);
  paintCards();

  function paintDetail(user) {
    const c = cards.get(sel);
    if (!c) { put(box, ui.none("매매법 정보가 없습니다")); return; }
    put(box, stratDetail(c.s, c.past, list, grid, ctx));
    if (user) K4.swap(box);
  }
  paintDetail(false);

  const pv = list.filter((a) => a.kind === "private");
  put(priv, ui.card({plate: KIND_KO.private || "비공개 매매법", sub: "서버에만 있는 매매법: 이름과 한 줄 설명만"},
    pv.length ? h("div", {class: "s2-rows"}, pv.map((a) => h("div", {class: "s2-row"},
      h("div", {class: "s2-rowh"}, K4.acctFig(a, 20), h("a", {href: ctx.href("account", a.id)}, a.name || a.id), a.tf ? K4.tfChip(a.tf) : null),
      a.rule_ko ? h("div", {class: "s2-line"}, a.rule_ko) : null))) : ui.none(accts ? "비공개 매매법 계좌가 없습니다" : "준비 중"),
    h("p", {class: "note"}, "비공개 매매법의 규칙은 공개 저장소와 이 화면에 들어오지 않습니다. 판정은 같은 봉의 동전 던지기와 비교합니다.")));
  // the 5-year numbers of the marked settings (house exit), every strategy at once
  await Promise.all([...cards.values()].map(async ({s, past}) => {
    const picks = [];
    for (const tf of grid.tfs) {
      picks.push({ko: "기본값", tf, c: s.default_c, label: s.default});
      if (s.friend_c != null) picks.push({ko: "친구 값", tf, c: s.friend_c, label: s.friend});
      if (s.pick_c && s.pick_c[tf] != null) picks.push({ko: "5년 1등 값", tf, c: s.pick_c[tf], label: s.pick[tf]});
    }
    const ok = picks.filter((p) => Number.isInteger(p.c));
    if (!ok.length) { put(past, ui.none("서버가 설정 번호를 아직 알려 주지 않습니다 (새로 띄워야 합니다)")); return; }
    const res = await Promise.all(ok.map((p) => ctx.api(`/api/setting?${new URLSearchParams({strat: s.short, tf: p.tf, c: String(p.c), exit: "0"})}`).catch(() => null)));
    if (!ctx.alive()) return;
    const rows = ok.map((p, i) => ({...p, d: res[i]}));
    if (rows.every((r) => !r.d || !r.d.past5y)) { put(past, ui.none("5년 자료 파일이 없습니다")); return; }
    put(past, ui.table([
      {label: "설정", l: true, get: (r) => h("span", {class: "dl-kn"}, h("b", null, `${r.ko} · ${tfKo(r.tf)}`), h("small", {class: "mono muted"}, r.label || "—"))},
      ...PERIODS_SHOWN.map((per, i) => ({label: (grid.periods_ko || [])[grid.periods.indexOf(per)] || per, get: (r) => {
        const x = r.d && r.d.exits && r.d.exits[0] && r.d.exits[0].past ? r.d.exits[0].past[per] : null;
        if (!x || x.mean_R == null) return h("span", {class: "muted"}, "—");
        return h("span", {class: "dl-5y"}, ui.signed(fmt.r(x.mean_R), fmt.tone(x.mean_R, fmt.r(x.mean_R)), "b"), h("small", {class: "muted"}, `${fmt.int(x.n)}건`));
      }, cls: i === 0 ? "dl-5y0" : ""})),
      {label: "실시간", get: (r) => {
        const w = r.d && r.d.exits && r.d.exits[0] && r.d.exits[0].w ? r.d.exits[0].w.live : null;
        if (!w || !w.n) return h("span", {class: "muted"}, "—");
        return h("span", {class: "dl-5y"}, ui.signed(fmt.r(w.mean_R), fmt.tone(w.mean_R, fmt.r(w.mean_R)), "b"), h("small", {class: "muted"}, `${fmt.int(w.n)}건`));
      }},
    ], rows, {cls: "g4-pt5 s2-dense"}));
  }));
}

function stratDetail(s, past, accts, grid, ctx) {
  const a = ABOUT[s.short] || {parts: [], rule: "", dims: {}};
  const mine = accts.filter((x) => x.short === s.short);
  const tfs = grid.tfs || ["15m", "30m"];
  const fig = K4.acctFig({kind: "fixed", id: s.short, short: s.short}, 34);
  return h("div", {class: "s2-strat", "aria-label": `${s.short} 자세히`},
    h("div", {class: "s2-strath"}, fig, h("div", {class: "s2-stratt"}, h("h2", null, `${s.short} · ${STRAT_KO[s.short] || s.id}`),
      h("span", {class: "muted mono"}, s.id))),
    h("div", {class: "s2-cols"},
      h("div", {class: "s2-col"},
        ui.card({plate: "무엇을 보나", cls: "g4-strat"},
          a.parts.map(([name, text]) => h("div", {class: "g4-ind"}, h("b", null, name), moreText(text, 3)))),
        ui.card({plate: "들어가는 때"}, h("div", {class: "g4-rule"}, h("p", null, a.rule))),
        ui.card({plate: "5년 성적 (사다리 청산)", sub: "기본값 · 친구 값 · 5년 1등 값, 봉마다"}, past)),
      h("div", {class: "s2-col"},
        ui.card({plate: "설정 격자", sub: `${fmt.int(s.settings)}가지`},
          h("dl", {class: "g4-dims s2-dims"}, (s.dims || []).map((d) => h("div", null, h("dt", null, d.ko),
            h("dd", null, h("span", {class: "s2-vals"}, d.values.map((v) => h("span", {class: "s2-val"}, valKo(v)))),
              a.dims[d.key] ? h("small", {class: "muted"}, a.dims[d.key]) : null))))),
        ui.card({plate: "표시된 값"},
          h("dl", {class: "kv g4-marks s2-marks"},
            h("div", null, h("dt", null, "기본값"), h("dd", {class: "mono"}, s.default || "—")),
            h("div", null, h("dt", null, "친구 값"), h("dd", {class: "mono"}, s.friend || "없음")),
            tfs.map((tf) => h("div", null, h("dt", null, `5년 1등 · ${tfKo(tf)}`), h("dd", {class: "mono"}, (s.pick || {})[tf] || "—"))))),
        mine.length ? ui.card({plate: `이 매매법을 쓰는 계좌 ${mine.length}개`, sub: "20배 줄 손익 % · 거래"},
          h("div", {class: "s2-atiles"}, mine.map((x) => {
            const ln = (x.lines || {})["20"] || {};
            const t = fmt.pct(ln.pnl_pct, true);
            return h("a", {class: "s2-atile g4-al", href: ctx.href("account", x.id), title: x.rule_ko || x.name || x.id},
              h("span", {class: "s2-atn"}, K4.acctFig(x, 18), K4.tfChip(x.tf), h("span", {class: "an-n"}, SUB_KO[x.sub] || x.sub || "")),
              h("span", {class: "s2-atv"}, h("b", {class: ["num", fmt.tone(ln.pnl_pct, t)]}, t), h("small", {class: "muted"}, `거래 ${fmt.int(ln.trades)}`)));
          }))) : null)));
}
