// A tiny DOM for rendering the ana-syn analysis cards in node (tests/test_dash_ana_syn.py): enough of Node / document
// for core/dom.js h() and the ui helpers, plus walk() to read the text and class names back. Not a browser: layout,
// CSS and events are not simulated (the screenshots check those).
class Node {
  constructor(tag) {
    this.tagName = tag ? String(tag).toUpperCase() : "";
    this.childNodes = []; this.attributes = {}; this.dataset = {}; this.className = ""; this.parentNode = null;
    this.style = {setProperty(k, v) { this[k] = v; }, removeProperty(k) { delete this[k]; }};
  }
  appendChild(c) { this.childNodes.push(c); c.parentNode = this; return c; }
  append(...cs) { for (const c of cs) if (c != null) this.appendChild(c instanceof Node ? c : new Text(String(c))); }
  prepend(...cs) { const old = this.childNodes; this.childNodes = []; this.append(...cs); this.childNodes.push(...old); }
  replaceChildren(...cs) { this.childNodes = []; this.append(...cs); }
  remove() { if (this.parentNode) this.parentNode.childNodes = this.parentNode.childNodes.filter((x) => x !== this); }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  getAttribute(k) { return k in this.attributes ? this.attributes[k] : null; }
  removeAttribute(k) { delete this.attributes[k]; }
  hasAttribute(k) { return k in this.attributes; }
  addEventListener() {} removeEventListener() {} dispatchEvent() { return true; }
  getBoundingClientRect() { return {width: 0, height: 0, left: 0, top: 0, right: 0, bottom: 0}; }
  animate() { return {finished: Promise.resolve(), cancel() {}, onfinish: null}; }
  focus() {} scrollIntoView() {}
  get firstChild() { return this.childNodes[0] || null; }
  get lastChild() { return this.childNodes[this.childNodes.length - 1] || null; }
  get children() { return this.childNodes.filter((c) => !(c instanceof Text)); }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  set textContent(v) { this.childNodes = [new Text(String(v))]; }
  set innerHTML(v) { this.childNodes = []; }
  get classList() {
    const self = this, list = () => String(self.className || "").split(/\s+/).filter(Boolean);
    return {add: (...c) => { self.className = [...new Set([...list(), ...c])].join(" "); },
      remove: (...c) => { self.className = list().filter((x) => !c.includes(x)).join(" "); },
      contains: (c) => list().includes(c), toggle: (c, on) => { const has = list().includes(c); const want = on == null ? !has : on; if (want && !has) self.classList.add(c); if (!want && has) self.classList.remove(c); return want; }};
  }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  closest() { return null; }
  contains() { return false; }
}
class Text extends Node {
  constructor(t) { super(); this.t = t; }
  get textContent() { return this.t; }
  set textContent(v) { this.t = String(v); }
}
globalThis.Node = Node;
globalThis.Text = Text;
globalThis.HTMLElement = Node;
const store = {};
globalThis.localStorage = {getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); }, removeItem: (k) => { delete store[k]; }};
globalThis.document = {
  createElement: (t) => new Node(t), createElementNS: (_ns, t) => new Node(t), createTextNode: (t) => new Text(t),
  createRange: () => ({selectNodeContents() {}, getBoundingClientRect: () => ({width: 0, height: 0})}),
  addEventListener() {}, removeEventListener() {}, querySelector: () => null, querySelectorAll: () => [],
  head: new Node("head"), body: new Node("body"), documentElement: new Node("html"), visibilityState: "hidden", hidden: true,
};
globalThis.window = globalThis;
globalThis.requestAnimationFrame = () => 0;
globalThis.cancelAnimationFrame = () => {};
globalThis.matchMedia = () => ({matches: true, addEventListener() {}, removeEventListener() {}});
globalThis.getComputedStyle = () => ({getPropertyValue: () => ""});

/** {text, classes: [className...]} of a node or a list of nodes. */
export function walk(nodes) {
  const texts = [], classes = [];
  const go = (n) => {
    if (n == null) return;
    if (Array.isArray(n)) { n.forEach(go); return; }
    if (n instanceof Text) { texts.push(n.t); return; }
    if (n.className) classes.push(String(n.className));
    n.childNodes.forEach(go);
  };
  go(nodes);
  return {text: texts.join(" "), classes};
}
