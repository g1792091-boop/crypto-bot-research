// #/strategies 매매법 (CONTRACT 9.8): one card per strategy (S2_ST_ROC, N02_ST_KST, N04_ST_KLINGER): what its indicators
// do in plain Korean, when it goes in, the settings grid (/api/grid), the default / friend / 5-year pick values, their
// 5-year results with the house exit (/api/setting: the shipped past5y files) and the accounts that run it; then the
// private plug-in accounts (kind "private"): their name and rule_ko only (their rules never enter this code).
import {h, put} from "../dom.js";
import * as fmt from "../fmt.js";
import * as ui from "../ui.js";
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

export async function mount(el, ctx) {
  ctx.setTitle("매매법");
  const box = h("div", {class: "stack"});
  const priv = h("div");
  el.append(ui.screenHead("매매법", "세 매매법이 무엇을 보고 들어가나"),
    ui.card({hero: true, plate: "한 줄로"},
      h("p", {class: "dl-lead"}, "세 매매법 모두 ", h("b", null, "슈퍼트렌드로 추세 방향"), "을 잡고, 두 번째 지표(ROC · KST · 클링거)로 ",
        h("b", null, "힘이 붙는 순간"), "을 골라 들어갑니다. 나가는 방법(청산 14가지)은 따로 고르고, 설정 순위가 모든 설정 × 청산을 실시간으로 겨룹니다.")),
    box, priv,
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
  const cards = (grid.strategies || []).map((s) => ({s, past: h("div", {class: "g4-past"}, ui.empty("5년 성적을 읽는 중…"))}));
  put(box, cards.map(({s, past}) => stratCard(s, past, list, grid, ctx)));
  const pv = list.filter((a) => a.kind === "private");
  put(priv, ui.card({plate: KIND_KO.private || "비공개 매매법", sub: "서버에만 있는 매매법: 이름과 한 줄 설명만"},
    pv.length ? h("ul", {class: "dl-ul"}, pv.map((a) => h("li", null, h("a", {href: ctx.href("account", a.id)}, h("b", null, a.name || a.id)),
      a.rule_ko ? ` · ${a.rule_ko}` : ""))) : ui.none(accts ? "비공개 매매법 계좌가 없습니다" : "준비 중"),
    h("p", {class: "note"}, "비공개 매매법의 규칙은 공개 저장소와 이 화면에 들어오지 않습니다. 판정은 같은 봉의 동전 던지기와 비교합니다.")));
  // the 5-year numbers of the marked settings (house exit), every strategy at once
  await Promise.all(cards.map(async ({s, past}) => {
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
    ], rows, {cls: "g4-pt5"}));
  }));
}

function stratCard(s, past, accts, grid, ctx) {
  const a = ABOUT[s.short] || {parts: [], rule: "", dims: {}};
  const mine = accts.filter((x) => x.short === s.short);
  const tfs = grid.tfs || ["15m", "30m"];
  return ui.card({plate: `${s.short} · ${STRAT_KO[s.short] || s.id}`, sub: s.id, cls: "g4-strat"},
    h("div", {class: "grid2"},
      h("div", {class: "stack tight"}, a.parts.map(([name, text]) => h("div", {class: "g4-ind"}, h("b", null, name), h("p", null, text))),
        h("div", {class: "g4-rule"}, h("b", null, "들어가는 때"), h("p", null, a.rule))),
      h("div", {class: "stack tight"},
        h("p", {class: "dl-fk2"}, `설정 격자: ${fmt.int(s.settings)}가지`),
        h("dl", {class: "g4-dims"}, (s.dims || []).map((d) => h("div", null, h("dt", null, d.ko),
          h("dd", null, h("span", {class: "mono"}, d.values.map(valKo).join(" · ")), a.dims[d.key] ? h("small", {class: "muted"}, a.dims[d.key]) : null)))),
        h("dl", {class: "kv g4-marks"},
          h("div", null, h("dt", null, "기본값"), h("dd", {class: "mono"}, s.default || "—")),
          h("div", null, h("dt", null, "친구 값"), h("dd", {class: "mono"}, s.friend || "없음")),
          tfs.map((tf) => h("div", null, h("dt", null, `5년 1등 · ${tfKo(tf)}`), h("dd", {class: "mono"}, (s.pick || {})[tf] || "—")))))),
    h("p", {class: "dl-fk2"}, "5년 성적 (사다리 청산)"), past,
    mine.length ? h("div", {class: "stack tight"}, h("p", {class: "dl-fk2"}, `이 매매법을 쓰는 계좌 ${mine.length}개`),
      h("div", {class: "row wrap dl-pills"}, mine.map((x) => h("a", {class: "pp thin g4-al", href: ctx.href("account", x.id), title: x.rule_ko || ""},
        `${SUB_KO[x.sub] || x.sub || ""} · ${tfKo(x.tf)}`)))) : null);
}
