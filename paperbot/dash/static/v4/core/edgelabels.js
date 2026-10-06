// The chart's right-edge line names (owners 10/06 ~14:00, from their 1920x1080 screenshot: "손절 · OB · FVG · FVG · 저항
// · 지지 · 손절 · OB- · 손절" stacked over each other at the right edge). Pure layout, no DOM: core/chartfx.js draws
// the result next to the price axis and node tests it (tests/test_dash_declutter.py).
//   merge   lines at almost the same price (within `near` of the price, or `nearPx` on screen) share ONE name:
//           "손절 ×2", "손절 · 지지"; its tooltip lists every member with its price;
//   pick    at most `max` names, the ones nearest to the current price first; the rest stay reachable by hovering /
//           tapping their line (chartfx.js) and through the small "+N" chip;
//   dodge   names closer than one label height are nudged apart around their lines (clusters centred on the mean of
//           their lines, kept inside the pane); a nudged name gets a thin leader to its line.

/** How a group of names reads: each word once with its count ("손절 ×2 · 지지"), in the order they come. An item may
 *  stand for several lines already (``n``: e.g. two stops at one price drawn as one line). */
export function groupText(items) {
  const n = new Map();
  for (const it of items) n.set(it.text, (n.get(it.text) || 0) + (Number(it.n) > 1 ? Number(it.n) : 1));
  return [...n].map(([t, k]) => (k > 1 ? `${t} ×${k}` : t)).join(" · ");
}

/** The tone most of a group's members have (the first one on a tie). */
function toneOf(items) {
  const n = new Map();
  let best = items[0].tone, bn = 0;
  for (const it of items) {
    const k = (n.get(it.tone) || 0) + 1;
    n.set(it.tone, k);
    if (k > bn) { best = it.tone; bn = k; }
  }
  return best;
}

/**
 * mergeNames(items, {near, nearPx}) -> groups, top to bottom. items: [{id, price, y, text, tone, title, n}] (y in px,
 * the line's height on screen; n: lines it already stands for). A group: {key, ids, items, price (mean), y (mean),
 * text, tone}. A line joins the group when it is within ``near`` of the group's first price or ``nearPx`` of its first
 * line on screen (measured from the first, so a long run of close lines never chains into one huge name).
 */
export function mergeNames(items, o = {}) {
  const near = o.near ?? 0.0005, nearPx = o.nearPx ?? 4;
  const list = (items || []).filter((x) => x && Number.isFinite(x.y) && Number.isFinite(x.price)).slice().sort((a, b) => a.y - b.y || a.price - b.price);
  const out = [];
  for (const it of list) {
    const g = out[out.length - 1];
    const first = g && g.items[0];
    if (g && (Math.abs(it.price - first.price) <= near * Math.abs(first.price) || Math.abs(it.y - first.y) < nearPx)) { g.items.push(it); continue; }
    out.push({items: [it]});
  }
  for (const g of out) {
    g.ids = g.items.map((x) => x.id);
    g.key = g.ids.join("|");
    g.price = g.items.reduce((s, x) => s + x.price, 0) / g.items.length;
    g.y = g.items.reduce((s, x) => s + x.y, 0) / g.items.length;
    g.text = groupText(g.items);
    g.tone = toneOf(g.items);
  }
  return out;
}

/**
 * dodge(ys, H, lo, hi) -> label centres for targets ``ys`` (ascending): no two closer than H (squeezed when the pane
 * cannot hold them all), each run of touching labels centred on the mean of its targets, kept within [lo, hi].
 */
export function dodge(ys, H, lo, hi) {
  const n = ys.length;
  if (!n) return [];
  const h = Math.max(1, Math.min(H, (hi - lo) / n));
  const place = (c) => { c.s = Math.max(lo + h / 2, Math.min(c.sum / c.n - ((c.n - 1) * h) / 2, hi - h / 2 - (c.n - 1) * h)); };
  const cl = ys.map((y) => ({n: 1, sum: y, s: y}));
  cl.forEach(place);
  for (let i = 1; i < cl.length;) {
    const a = cl[i - 1], b = cl[i];
    if (a.s + a.n * h > b.s + 1e-6) {               // a's last label would touch b's first: one run, centred again
      a.n += b.n; a.sum += b.sum; cl.splice(i, 1); place(a);
      i = Math.max(1, i - 1);                          // the wider run may now touch the one above it
    } else i++;
  }
  const out = [];
  for (const c of cl) for (let k = 0; k < c.n; k++) out.push(c.s + k * h);
  return out;
}

/**
 * edgeLayout(items, {price, max, H, lo, hi, near, nearPx}) -> {shown: [group + {ly}], hidden: [group]}
 *   price: the current price (the nearest names win a place); max: names shown at most (6); H: one label's height;
 *   lo / hi: the pane's usable top and bottom (px). Shown groups come top to bottom with their label centre ``ly``.
 */
export function edgeLayout(items, o = {}) {
  const groups = mergeNames(items, o);
  const max = o.max ?? 6, cur = Number(o.price);
  const rank = groups.slice().sort((a, b) => (Number.isFinite(cur) ? Math.abs(a.price - cur) - Math.abs(b.price - cur) : 0) || a.y - b.y);
  const keep = new Set(rank.slice(0, max));
  const shown = groups.filter((g) => keep.has(g)), hidden = groups.filter((g) => !keep.has(g));
  const ys = dodge(shown.map((g) => g.y), o.H ?? 16, o.lo ?? 0, o.hi ?? 400);
  shown.forEach((g, i) => { g.ly = ys[i]; });
  return {shown, hidden};
}
