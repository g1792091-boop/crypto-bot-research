// #/faq — 자주 묻는 질문 (builder E). Short questions that open smoothly (motion.expand), including what '참고',
// '표본 적음' and '수집 전' mean; the 'what costs money' table (free / Max subscription / paid API / server rental) with
// today's real usage; the rule documents (read as plain text, never parsed as HTML); 안내 다시 보기; 로그아웃.
// Old homes: the summary strip's 원문 link, the 로그아웃 button (INVENTORY.md 1, 13).
import {h, ui, motion, features, apiText, startTour, local, put} from "../core/pb.js";
import {note} from "./server-kit.js";
import {FAQ, costRows} from "./faq-items.js";
import {termsCard} from "./faq-terms.js";

const DOCS = [["doc", "실험 규칙 원문"], ["verdict_doc", "판정 방법 원문"], ["levrule_doc", "좋은 자리 vs 보통 평가 계획"]];

export async function mount(el, ctx) {
  ctx.setTitle("자주 묻는 질문");
  const f = {verdict: null, usage: null, debate: null, debateOn: !!features.debate};
  el.append(ui.screenHead("자주 묻는 질문", "짧게 묻고 짧게 답합니다"));
  // 용어 사전 first: #/faq?q=<term> (the "?" chips on the account screen) opens that term and brings it into view
  const terms = termsCard((ctx.params.query || {}).q);
  el.append(terms);

  // ---------------------------------------------------------------- questions (smooth expand; open ones remembered)
  const opened = new Set(local.get("faq-open", []));
  const answers = [];
  let n = 0;
  const qa = FAQ.map((g) => h("section", {class: "faq-group", "aria-label": g.group}, h("h2", {class: "faq-gh"}, g.group),
    g.items.map((it) => {
      const id = `faq-a${n++}`;
      const open = opened.has(it.q);
      const region = h("div", {class: "faq-a", id, role: "region", hidden: !open});
      const btn = h("button", {class: "faq-q", type: "button", "aria-expanded": String(open), "aria-controls": id},
        h("span", null, it.q), h("i", {class: "faq-car", "aria-hidden": "true"}));
      const fill = () => put(region, h("div", {class: "faq-in"}, it.a(f, ctx)));
      fill();
      answers.push(fill);
      btn.addEventListener("click", () => {
        const o = btn.getAttribute("aria-expanded") !== "true";
        btn.setAttribute("aria-expanded", String(o));
        if (o) opened.add(it.q); else opened.delete(it.q);
        local.set("faq-open", [...opened].slice(-20));
        motion.expand(region, o);
      });
      return h("div", {class: "faq-item"}, btn, region);
    })));
  const qaCard = ui.card({plate: "질문과 답", cls: "faq-qa"}, qa);

  // ---------------------------------------------------------------- what costs money
  const costBox = h("div", {class: "faq-cost", role: "table", "aria-label": "돈이 드는 것"});
  const paintCost = () => put(costBox, costRows(f).map((r) => h("div", {class: "faq-crow", role: "row"},
    h("span", {role: "cell"}, ui.pill(r.tag, r.cls)),
    h("div", {role: "cell", class: "faq-cwhat"}, h("span", null, r.what), r.now ? h("b", {class: "faq-cnow"}, r.now) : null))));
  const costCard = ui.card({plate: "돈이 드는 것", sub: "실제 돈 기준"}, costBox,
    note("모의 계좌의 손익은 가상 돈이라 실제로 나가거나 들어오는 돈이 아닙니다."));

  // ---------------------------------------------------------------- rule documents (plain text)
  const docBox = h("div", {class: "stack tight"});
  const docCard = ui.card({plate: "규칙 원문", sub: "서버에 있는 문서 그대로"}, docBox);
  const paintDocs = (s) => {
    const rs = (s && s.restart) || {};
    const seen = new Set();
    const rows = DOCS.map(([k, label]) => [rs[k], label]).filter(([u]) => u && /^\/api\/doc\/[\w-]+$/.test(u) && !seen.has(u) && seen.add(u));
    // the server's own links only (restart.doc / verdict_doc / levrule_doc): never a guessed older document
    put(docBox, rows.length ? rows.map(([url, label]) => docRow(url, label)) : h("p", {class: "muted"}, "서버가 아직 규칙 문서 주소를 보내지 않았습니다."));
  };
  function docRow(url, label) {
    const body = h("div", {class: "faq-docbody", hidden: true});
    let loaded = false;
    const btn = h("button", {class: "btn-line", type: "button", "aria-expanded": "false"}, "펼쳐 읽기");
    btn.addEventListener("click", async () => {
      const o = btn.getAttribute("aria-expanded") !== "true";
      btn.setAttribute("aria-expanded", String(o)); btn.textContent = o ? "접기" : "펼쳐 읽기";
      if (o && !loaded) {
        put(body, motion.shimmer(4));
        motion.expand(body, true);
        try {
          const t = await apiText(url, {signal: ctx.signal});
          loaded = true;
          if (ctx.alive()) put(body, h("pre", {class: "faq-doc"}, t));          // text node: never parsed as HTML
        } catch (e) {
          if (ctx.alive()) put(body, ui.errorBox(e));
        }
        return;
      }
      motion.expand(body, o);
    });
    return h("div", {class: "faq-docrow"}, h("div", {class: "row wrap"}, h("b", {class: "grow"}, label), btn,
      h("a", {class: "btn-line", href: url, target: "_blank", rel: "noopener"}, "새 탭")), body);
  }

  // ---------------------------------------------------------------- tour + logout
  const tourCard = ui.card({plate: "안내와 로그아웃"},
    h("p", {class: "ink2"}, "처음 들어왔을 때 나온 7단계 안내를 다시 볼 수 있습니다. 메뉴의 다섯 묶음을 하나씩 짚어 줍니다."),
    h("div", {class: "row wrap"},
      h("button", {class: "btn-y", type: "button", onclick: () => { window.scrollTo(0, 0); startTour(); }}, "안내 다시 보기"),
      h("button", {class: "btn-line", type: "button", onclick: logout}, "로그아웃")),
    note("로그아웃하면 다음에 비밀번호를 다시 넣어야 합니다."));

  el.append(h("div", {class: "faq-cols"}, qaCard, h("div", {class: "stack"}, costCard, docCard, tourCard)));
  if ((ctx.params.query || {}).q) requestAnimationFrame(() => { if (ctx.alive()) terms.focusTerm(); });
  paintCost();
  paintDocs(ctx.store.get("summary"));

  // ---------------------------------------------------------------- live facts
  ctx.watch("summary", (s) => {
    if (!s) return;
    const v = s.restart && s.restart.ready ? s.restart.verdict_ts : s.next_checkpoint ? s.next_checkpoint.ts : null;
    paintDocs(s);
    if (v !== f.verdict) { f.verdict = v; answers.forEach((fill) => fill()); }
  });
  ctx.watch("usage", (u) => { f.usage = u; paintCost(); });
  let unDebate = null;
  const debateFeature = () => {
    f.debateOn = !!features.debate;
    if (f.debateOn && !unDebate) unDebate = ctx.watch("debate", (d) => { f.debate = d; paintCost(); });
    paintCost();
  };
  debateFeature();
  ctx.on("features", debateFeature);

  async function logout() {
    try { await ctx.post("/api/logout", {}); } catch { /* the cookie is cleared or gone either way */ }
    location.href = "/login";
  }
}

export function unmount() {}
