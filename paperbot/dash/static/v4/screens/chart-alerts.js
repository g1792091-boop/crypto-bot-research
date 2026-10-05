// chart (builder B): the 가격 알림 pane. The owners set a price; the Telegram sender (paperbot-tgtrades) rings once
// when the price reaches it. List / add / delete / re-arm through the existing endpoints (/api/price-alerts), showing
// the server's own Korean message on an error. Delete asks once more (a second tap within 4 s).
import {h, ui, fmt, store} from "../core/pb.js";

/**
 * alertsPane(ctx, {sym, onData(d)}) -> element with .setSym(sym), .load(). onData gets every /api/price-alerts answer
 * (the chart draws the armed ones of its coin as lines).
 */
export function alertsPane(ctx, o = {}) {
  let sym = o.sym, data = null, busy = false;
  const title = h("p", {class: "chart-al-t"});
  const priceIn = h("input", {class: "search chart-al-in", inputmode: "decimal", autocomplete: "off", "aria-label": "알림 가격", placeholder: "가격"});
  const noteIn = h("input", {class: "search chart-al-in", maxlength: "100", autocomplete: "off", "aria-label": "메모 (선택)", placeholder: "메모 (선택)"});
  const addBtn = h("button", {class: "btn-y", type: "button"}, "알림 걸기");
  const msg = h("p", {class: "pos-note", role: "status", "aria-live": "polite"});
  const warn = h("div");
  const count = h("span", {class: "sub"});
  const list = h("div", {class: "chart-al-list", role: "list"});
  const el = h("div", {class: "stack"}, title,
    h("div", {class: "chart-al-form"}, priceIn, noteIn, addBtn), msg, warn,
    h("div", {class: "card-h"}, ui.plate("걸어 둔 알림"), count), list);

  const say = (t, bad) => { msg.textContent = t || ""; msg.classList.toggle("down", !!bad); };
  const last = () => { const t = (store.get("ticker") || {})[sym]; return t ? (t.c ?? t.mark) : null; };
  const head = () => {
    title.textContent = `${fmt.coin(sym)} 가격이 닿으면 텔레그램으로 알림이 갑니다 (소리 있음, 한 번 울리면 꺼짐).`;
    const p = last();
    priceIn.placeholder = p ? fmt.price(p) : "가격";
    if (!msg.textContent && p) say(`지금 ${fmt.price(p)} · 지금보다 높게 적으면 오를 때, 낮게 적으면 내릴 때 울립니다.`);
  };

  const row = (a) => {
    let armDel = 0;
    const del = h("button", {class: "btn-line", type: "button"}, "지우기");
    del.addEventListener("click", async () => {
      if (Date.now() - armDel > 4000) { armDel = Date.now(); del.textContent = "정말 지우기"; del.classList.add("bad");
        setTimeout(() => { if (del.isConnected) { del.textContent = "지우기"; del.classList.remove("bad"); } }, 4000); return; }
      await act(`/api/price-alerts/${encodeURIComponent(a.id)}/delete`, `${fmt.coin(a.symbol)} ${fmt.price(a.price)} 알림을 지웠습니다.`);
    });
    const rearm = a.armed ? null : h("button", {class: "btn-line", type: "button", onclick: () =>
      act(`/api/price-alerts/${encodeURIComponent(a.id)}/rearm`, `${fmt.coin(a.symbol)} ${fmt.price(a.price)} 알림을 다시 켰습니다.`)}, "다시 켜기");
    return h("div", {class: ["chart-al-row", a.symbol === sym ? "mine" : ""], role: "listitem"},
      h("b", null, fmt.coin(a.symbol), " ", a.direction === "above" ? "↑" : "↓"),
      h("span", {class: "num"}, fmt.price(a.price)),
      h("span", {class: a.armed ? "accent" : "muted"}, a.armed ? "대기 중" : `울림 ${fmt.kst(a.fired_ts)}`),
      h("span", {class: "chart-al-acts"}, rearm, del),
      a.note ? h("small", {class: "chart-al-note"}, a.note) : null);
  };
  const render = () => {
    const d = data;
    warn.replaceChildren(d && !d.sender_alive ? h("p", {class: "chart-warn"},
      "텔레그램 보내는 프로그램(paperbot-tgtrades)이 꺼져 있어 알림이 가지 않습니다. 걸어 둔 알림은 남아 있고, 켜지면 그때부터 울립니다.") : null);
    const rows = ((d && d.alerts) || []).slice().sort((x, y) => (x.symbol === sym ? 0 : 1) - (y.symbol === sym ? 0 : 1) || y.id - x.id);
    count.textContent = d ? `${fmt.int(rows.length)} / ${fmt.int(d.max || 50)}개` : "";
    list.replaceChildren(...(rows.length ? rows.slice(0, 20).map(row) : [ui.empty("걸어 둔 알림이 없습니다")]));
    if (rows.length > 20) list.append(h("p", {class: "pos-note"}, `오래된 ${fmt.int(rows.length - 20)}개는 줄였습니다.`));
  };
  async function load() {
    try {
      data = await ctx.api("/api/price-alerts");
      if (!ctx.alive()) return;
      render();
      if (o.onData) o.onData(data);
    } catch (e) {
      if (e && e.name === "AbortError") return;
      if (!data) list.replaceChildren(ui.errorBox(e, load));
    }
  }
  async function act(path, okText) {
    if (busy) return;
    busy = true;
    try { await ctx.post(path, {}); say(okText); await load(); }
    catch (e) { if (!(e && e.name === "AbortError")) say((e && e.detail) || "처리하지 못했습니다. 잠시 뒤 다시 해 주세요.", true); }
    finally { busy = false; }
  }
  async function add() {
    const v = parseFloat(String(priceIn.value).replace(/[,\s]/g, ""));
    if (!(v > 0)) { say("가격을 숫자로 적어 주세요.", true); priceIn.focus(); return; }
    if (busy) return;
    busy = true; addBtn.disabled = true;
    try {
      const r = await ctx.post("/api/price-alerts", {symbol: sym, price: v, note: noteIn.value});
      priceIn.value = ""; noteIn.value = "";
      say(`${fmt.coin(sym)} ${fmt.price(v)} ${r && r.direction === "above" ? "위로 오르면" : "아래로 내리면"} 알립니다.`);
      await load();
    } catch (e) {
      if (!(e && e.name === "AbortError")) say((e && e.detail) || "알림을 저장하지 못했습니다.", true);
    } finally { busy = false; addBtn.disabled = false; }
  }
  addBtn.addEventListener("click", add);
  priceIn.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.isComposing) add(); });
  noteIn.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.isComposing) add(); });

  el.setSym = (s) => { sym = s; say(""); head(); render(); };
  el.load = load;
  el.tick = head;
  head();
  return el;
}
