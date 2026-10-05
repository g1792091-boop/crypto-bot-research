// 알림 기록 (다듬기 7-7): pure helpers, no DOM. Identical alerts (the same level AND the same text, character for
// character) fold into one row with how many times, the first and the last time; different texts never merge. The
// "여기부터 새 알림" line counts the alerts after this device's last look (kept per viewer by alerts.js through local).

/** The fold key: level + exact text (a number or a word that differs keeps two rows). */
export const groupKey = (a) => `${String((a && a.level) || "")}\u0000${String((a && a.text) ?? "")}`;

/**
 * rows: [{ts, level, text, ko}] (any order) -> groups, newest last-time first:
 * [{key, level, text, ko, n, first, last, items}] with items newest first (the same row objects).
 */
export function groupAlerts(rows) {
  const by = new Map();
  for (const a of rows || []) {
    if (!a) continue;
    const k = groupKey(a), ts = Number(a.ts) || 0;
    let g = by.get(k);
    if (!g) { g = {key: k, level: a.level, text: String(a.text ?? ""), ko: a.ko, n: 0, first: ts, last: ts, items: []}; by.set(k, g); }
    g.n++;
    g.items.push(a);
    if (ts < g.first) g.first = ts;
    if (ts > g.last) { g.last = ts; g.ko = a.ko; }
  }
  const out = [...by.values()];
  for (const g of out) g.items.sort((x, y) => (Number(y.ts) || 0) - (Number(x.ts) || 0));
  return out.sort((x, y) => y.last - x.last || (x.key < y.key ? -1 : 1));
}

/**
 * Where the "여기부터 새 알림 n개" line goes: {n: alerts newer than seen, at: how many groups (newest first) carry at
 * least one of them}. seen null / undefined (the first visit on this device): nothing is new.
 */
export function newSince(groups, seen) {
  if (seen == null || !Number.isFinite(Number(seen))) return {n: 0, at: 0};
  let n = 0, at = 0;
  for (const g of groups || []) {
    const k = g.items.filter((a) => (Number(a.ts) || 0) > seen).length;
    if (k) { n += k; at++; }
  }
  return {n, at};
}

/** The list the page pages through: the groups with the divider row put after the new ones (none when nothing is new
 *  or everything is). */
export function withDivider(groups, seen) {
  const {n, at} = newSince(groups, seen);
  if (!n || at >= (groups || []).length) return {rows: (groups || []).slice(), n};
  const rows = groups.slice();
  rows.splice(at, 0, {divider: true, n, seen});
  return {rows, n};
}
