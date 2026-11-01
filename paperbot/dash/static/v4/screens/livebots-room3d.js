// 실거래 › 회의실 in real 3D (owners 2026-11-01, their video of an AI office: "이렇게는 안되는거야? 3d로"): the browser's own
// WebGL, no library. A small renderer for the room: a perspective camera circling (and slowly swaying) round a glowing
// round table on a stage, at each seat a pod of light, a desk with a lit monitor, a chair and a figure typing at it, a
// column of light with a green and cyan vortex in the middle, a beam to every running program, and floating screens round
// the room with the programs' own numbers (their words come from screens/livebots-room.js). Everything drawn is decoration (said on the screen): the words on the name tags (screens/
// livebots-room.js) are the programs' own records. The pure parts (matrices, meshes, the seats' poses, a point on the
// screen) are tested in node (tests/test_dash_liveroom.py); create3d returns null where WebGL cannot start (the 2D picture
// stays then).

// ---------------------------------------------------------------- matrices (column-major, as WebGL reads them)
export function m4ident() { return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]; }
/** a · b */
export function m4mul(a, b) {
  const o = new Array(16).fill(0);
  for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) {
    let s = 0;
    for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k];
    o[c * 4 + r] = s;
  }
  return o;
}
/** A perspective projection (fovy in radians). */
export function m4persp(fovy, aspect, near, far) {
  const f = 1 / Math.tan(fovy / 2), nf = 1 / (near - far);
  return [f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * nf, -1, 0, 0, 2 * far * near * nf, 0];
}
/** The view from ``eye`` looking at ``at``. */
export function m4look(eye, at, up = [0, 1, 0]) {
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const nrm = (v) => { const l = Math.hypot(v[0], v[1], v[2]) || 1; return [v[0] / l, v[1] / l, v[2] / l]; };
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const z = nrm(sub(eye, at)), x = nrm(cross(up, z)), y = cross(z, x);
  return [x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0, -dot(x, eye), -dot(y, eye), -dot(z, eye), 1];
}
/** translate(t) · rotateY(ry) · scale(s) */
export function m4trs(t, ry, s) {
  const c = Math.cos(ry), n = Math.sin(ry);
  return [c * s[0], 0, -n * s[0], 0, 0, s[1], 0, 0, n * s[2], 0, c * s[2], 0, t[0], t[1], t[2], 1];
}
/** m · [x, y, z, 1] */
export function m4apply(m, v) {
  const [x, y, z] = v;
  return [0, 1, 2, 3].map((r) => m[r] * x + m[4 + r] * y + m[8 + r] * z + m[12 + r]);
}
/** A point of the room on a W × H screen: [X, Y, depth] (depth: its distance along the view), null behind the camera. */
export function screenOf(vp, x, y, z, W, H) {
  const c = m4apply(vp, [x, y, z]);
  if (c[3] <= 1e-6) return null;
  return [(c[0] / c[3] * 0.5 + 0.5) * W, (1 - (c[1] / c[3] * 0.5 + 0.5)) * H, c[3]];
}
/** A token's colour ("#rrggbb", "#rgb" or "rgb(r, g, b)") -> [r, g, b] in 0..1; null when not a colour. */
export function hexRgb(s) {
  const t = String(s || "").trim();
  let m = t.match(/^#([0-9a-f]{6})$/i);
  if (m) return [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16) / 255);
  m = t.match(/^#([0-9a-f]{3})$/i);
  if (m) return [0, 1, 2].map((i) => parseInt(m[1][i] + m[1][i], 16) / 255);
  m = t.match(/^rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)/i);
  return m ? [1, 2, 3].map((i) => Number(m[i]) / 255) : null;
}
/** Seat i of n round the table: where it sits and which way it faces (towards the middle). */
export function seatPose(i, n, r = 1.85) {
  const a = Math.PI / 2 + (i / Math.max(1, n)) * Math.PI * 2;
  return {a, x: Math.cos(a) * r, z: Math.sin(a) * r, yaw: Math.PI / 2 - a};
}

// ---------------------------------------------------------------- meshes ({pos, nrm, idx}: flat arrays)
export function meshBox() {
  const f = [[[1, 0, 0], [0, 1, 0], [0, 0, 1]], [[-1, 0, 0], [0, 1, 0], [0, 0, -1]], [[0, 1, 0], [0, 0, 1], [1, 0, 0]],
    [[0, -1, 0], [0, 0, -1], [1, 0, 0]], [[0, 0, 1], [0, 1, 0], [-1, 0, 0]], [[0, 0, -1], [0, 1, 0], [1, 0, 0]]];
  const pos = [], nrm = [], idx = [];
  for (const [n, u, v] of f) {
    const b = pos.length / 3;
    for (const [su, sv] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) {
      pos.push(0.5 * (n[0] + su * u[0] + sv * v[0]), 0.5 * (n[1] + su * u[1] + sv * v[1]), 0.5 * (n[2] + su * u[2] + sv * v[2]));
      nrm.push(...n);
    }
    idx.push(b, b + 1, b + 2, b, b + 2, b + 3);
  }
  return {pos, nrm, idx};
}
/** A cylinder of radius 1 from y = 0 to y = 1, with its caps. */
export function meshCyl(seg = 28) {
  const pos = [], nrm = [], idx = [];
  for (let i = 0; i <= seg; i++) {
    const a = (i / seg) * Math.PI * 2, c = Math.cos(a), s = Math.sin(a);
    pos.push(c, 0, s, c, 1, s); nrm.push(c, 0, s, c, 0, s);
  }
  for (let i = 0; i < seg; i++) { const b = i * 2; idx.push(b, b + 1, b + 3, b, b + 3, b + 2); }
  for (const [y, ny] of [[1, 1], [0, -1]]) {
    const ctr = pos.length / 3;
    pos.push(0, y, 0); nrm.push(0, ny, 0);
    for (let i = 0; i <= seg; i++) { const a = (i / seg) * Math.PI * 2; pos.push(Math.cos(a), y, Math.sin(a)); nrm.push(0, ny, 0); }
    for (let i = 0; i < seg; i++) idx.push(ctr, ctr + 1 + i, ctr + 2 + i);
  }
  return {pos, nrm, idx};
}
export function meshSphere(lat = 10, lon = 16) {
  const pos = [], nrm = [], idx = [];
  for (let i = 0; i <= lat; i++) {
    const t = (i / lat) * Math.PI;
    for (let j = 0; j <= lon; j++) {
      const p = (j / lon) * Math.PI * 2, x = Math.sin(t) * Math.cos(p), y = Math.cos(t), z = Math.sin(t) * Math.sin(p);
      pos.push(x, y, z); nrm.push(x, y, z);
    }
  }
  for (let i = 0; i < lat; i++) for (let j = 0; j < lon; j++) {
    const a = i * (lon + 1) + j, b = a + lon + 1;
    idx.push(a, b, a + 1, b, b + 1, a + 1);
  }
  return {pos, nrm, idx};
}
/** A ring lying flat (the floor's plane): radius 1, tube ``tube``. */
export function meshTorus(tube = 0.02, seg = 72, sides = 6) {
  const pos = [], nrm = [], idx = [];
  for (let i = 0; i <= seg; i++) {
    const a = (i / seg) * Math.PI * 2, ca = Math.cos(a), sa = Math.sin(a);
    for (let j = 0; j <= sides; j++) {
      const b = (j / sides) * Math.PI * 2, cb = Math.cos(b), sb = Math.sin(b);
      pos.push((1 + tube * cb) * ca, tube * sb, (1 + tube * cb) * sa); nrm.push(cb * ca, sb, cb * sa);
    }
  }
  for (let i = 0; i < seg; i++) for (let j = 0; j < sides; j++) {
    const a = i * (sides + 1) + j, b = a + sides + 1;
    idx.push(a, b, a + 1, b, b + 1, a + 1);
  }
  return {pos, nrm, idx};
}


/** The camera's own turn at the start (radians): the floating screens and the floor's words stand behind the table as
 * seen from it, as in the owners' video. */
export const YAW0 = 0.35;
/** The stage's radius, the seats' ring and the seats' size (as in the video: a big stage, small figures far apart). */
export const STAGE = 3.25;
export const SEAT_RING = 2.5;
export const SEAT_K = 0.8;
/** A turn about x (the floor's words lie flat). */
export function m4rotx(a) {
  const c = Math.cos(a), s = Math.sin(a);
  return [1, 0, 0, 0, 0, c, s, 0, 0, -s, c, 0, 0, 0, 0, 1];
}
/** A floating screen's place from its pose {off (radians from straight behind the table), y, w, h, r}: {b, x, z, yaw, y, w, h}. */
export function layoutPose(p) {
  const b = 1.5 * Math.PI - YAW0 + (p.off || 0), r = p.r || 3.3;
  return {b, x: Math.cos(b) * r, z: Math.sin(b) * r, yaw: Math.atan2(-Math.cos(b), -Math.sin(b)), y: p.y == null ? 1.25 : p.y,
    w: p.w || 1.7, h: p.h || 1.06};
}
/** An arc of light from a to b, lifted at its middle: n points on the curve (the energy dome's strands). */
export function arcPts(a, b, lift, n = 16) {
  const m = [(a[0] + b[0]) / 2, Math.max(a[1], b[1]) + lift, (a[2] + b[2]) / 2], out = [];
  for (let i = 0; i < n; i++) {
    const f = i / (n - 1), g = 1 - f;
    out.push([0, 1, 2].map((k) => g * g * a[k] + 2 * g * f * m[k] + f * f * b[k]));
  }
  return out;
}
/** The energy dome (the owners' video): n twisted arcs from the top of the middle down to the open floor's edge, turning
 * with t (s); each [[x, y, z] × m] with its brightness. */
export function domeArcs(t, n = 40, m = 28, top = 1.55, rim = 1.45) {
  const out = [];
  for (let j = 0; j < n; j++) {
    const th0 = (j / n) * Math.PI * 2 + t * 0.12, twist = (j % 2 ? 1 : -1) * (0.9 + 0.5 * ((j * 7) % 5) / 5), pts = [];
    for (let i = 0; i < m; i++) {
      const f = i / (m - 1), th = th0 + twist * f, r = rim * Math.pow(Math.sin(f * Math.PI / 2), 0.75) * (0.92 + 0.08 * Math.sin(t * 1.7 + j));
      pts.push([Math.cos(th) * r, top - (top - 0.06) * Math.pow(f, 1.7), Math.sin(th) * r]);
    }
    out.push({pts, glow: 0.45 + 0.55 * Math.abs(Math.sin(t * (0.9 + (j % 4) * 0.35) + j * 1.3))});
  }
  return out;
}
/** A ribbon of light along pts, turned to the eye: [[x, y, z, edge (0 at its sides, 1 at its middle)], …] as triangles. */
export function ribbon(pts, eye, w) {
  const out = [], sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const side = pts.map((p, i) => {
    const tg = sub(pts[Math.min(pts.length - 1, i + 1)], pts[Math.max(0, i - 1)]), c = cross(tg, sub(eye, p)), l = Math.hypot(c[0], c[1], c[2]) || 1;
    return [c[0] / l * w, c[1] / l * w, c[2] / l * w];
  });
  for (let i = 0; i + 1 < pts.length; i++) {
    const a = pts[i], b = pts[i + 1], sa = side[i], sb = side[i + 1];
    const L = (p, s, k) => [p[0] + s[0] * k, p[1] + s[1] * k, p[2] + s[2] * k];
    const aL = [...L(a, sa, 1), 0], aC = [...a, 1], aR = [...L(a, sa, -1), 0], bL = [...L(b, sb, 1), 0], bC = [...b, 1], bR = [...L(b, sb, -1), 0];
    out.push(aL, aC, bL, aC, bC, bL, aC, aR, bC, aR, bR, bC);
  }
  return out;
}
/** Panel i of n hanging round the room (the floating screens): where it hangs and its turn to face the middle. */
export function panelPose(i, n, r = 3.3) {
  const b = -Math.PI / 2 + ((i + 0.5) / Math.max(1, n)) * Math.PI * 2;
  return {b, x: Math.cos(b) * r, z: Math.sin(b) * r, yaw: Math.atan2(-Math.cos(b), -Math.sin(b))};
}
/** The middle's energy: ``strands`` helices of ``n`` points each, turning with t (s): [[x, y, z], …] per strand. */
export function helix(t, strands = 6, n = 48) {
  const out = [];
  for (let k = 0; k < strands; k++) {
    const pts = [];
    for (let j = 0; j < n; j++) {
      const f = j / (n - 1), y = 0.18 + f * 1.45, a = t * (1.2 + 0.25 * (k % 3)) + (k / strands) * Math.PI * 2 + f * 7.5 * (k % 2 ? 1 : -1);
      const r = 0.1 + 0.22 * Math.sin(f * Math.PI) * (0.75 + 0.25 * Math.sin(t * 1.3 + k));
      pts.push([Math.cos(a) * r, y, Math.sin(a) * r]);
    }
    out.push(pts);
  }
  return out;
}

// ---------------------------------------------------------------- the renderer
const VS = `attribute vec3 aP; attribute vec3 aN; uniform mat4 uVP; uniform mat4 uM; varying vec3 vN; varying vec3 vW;
void main() { vec4 w = uM * vec4(aP, 1.0); vW = w.xyz; vN = (uM * vec4(aN, 0.0)).xyz; gl_Position = uVP * w; }`;
const FS = `precision mediump float; uniform vec3 uC; uniform vec3 uE; uniform float uA; uniform vec3 uEye; uniform vec3 uFog; uniform vec2 uFogR;
varying vec3 vN; varying vec3 vW;
void main() {
  vec3 n = normalize(vN); vec3 l = normalize(vec3(0.35, 1.0, 0.25)); vec3 v = normalize(uEye - vW);
  float dif = max(dot(n, l), 0.0); float rim = pow(1.0 - max(dot(n, v), 0.0), 2.0);
  vec3 col = uC * (0.30 + 0.70 * dif) + uE + uC * rim * 0.45;
  float fg = clamp((length(uEye - vW) - uFogR.x) / (uFogR.y - uFogR.x), 0.0, 1.0);
  gl_FragColor = vec4(mix(col, uFog, fg * 0.8), uA);
}`;
// points and lines: a colour and a size each; mode 0 a hard dot, 1 a soft glow, 2 a line
const PVS = `attribute vec3 aP; attribute vec4 aC; attribute float aS; uniform mat4 uVP; uniform float uScale; varying vec4 vC;
void main() { vC = aC; gl_Position = uVP * vec4(aP, 1.0); gl_PointSize = max(1.0, aS * uScale / max(gl_Position.w, 0.1)); }`;
const PFS = `precision mediump float; uniform float uMode; varying vec4 vC;
void main() {
  if (uMode < 1.5) { vec2 c = gl_PointCoord - 0.5; float d = length(c);
    if (uMode < 0.5) { if (d > 0.5) discard; gl_FragColor = vC; return; }
    float g = 1.0 - smoothstep(0.0, 0.5, d); gl_FragColor = vec4(vC.rgb, vC.a * g * g); return; }
  gl_FragColor = vC;
}`;
// the floating screens: a picture of words (a 2D canvas) on a quad
const TVS = `attribute vec3 aP; attribute vec2 aT; uniform mat4 uVP; uniform mat4 uM; varying vec2 vT;
void main() { vT = aT; gl_Position = uVP * uM * vec4(aP, 1.0); }`;
const TFS = `precision mediump float; uniform sampler2D uTex; uniform float uA; varying vec2 vT;
void main() { vec4 c = texture2D(uTex, vT); gl_FragColor = vec4(c.rgb, c.a * uA); }`;

function program(gl, vs, fs) {
  const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); return gl.getShaderParameter(s, gl.COMPILE_STATUS) ? s : null; };
  const v = sh(gl.VERTEX_SHADER, vs), f = sh(gl.FRAGMENT_SHADER, fs);
  if (!v || !f) return null;
  const p = gl.createProgram();
  gl.attachShader(p, v); gl.attachShader(p, f); gl.linkProgram(p);
  return gl.getProgramParameter(p, gl.LINK_STATUS) ? p : null;
}

const PW = 512, PH = 320;                              // a floating screen's picture, in pixels

/** One floating screen's picture: its title, then rows of words, bars, a table (cols, rows of cells) or coin cards (each
 * coin's price, change and 24-hour line); the screen module gives the words and numbers: the programs' records and
 * Binance's closed bars. css: the token colours as CSS strings; font: the page's terminal font. */
function paintPanel(g, spec, css, font) {
  const W = g.canvas.width, H = g.canvas.height, tone = (t) => css[t] || css.ink;
  const fit = (text, w) => { let s = String(text == null ? "" : text); if (g.measureText(s).width <= w) return s; while (s.length > 1 && g.measureText(s + "…").width > w) s = s.slice(0, -1); return s + "…"; };
  g.clearRect(0, 0, W, H);
  g.globalAlpha = 0.84; g.fillStyle = css.panel; g.fillRect(4, 4, W - 8, H - 8);
  g.globalAlpha = 1; g.strokeStyle = css.cyan; g.lineWidth = 3; g.strokeRect(4, 4, W - 8, H - 8);
  g.fillStyle = css.cyan; g.fillRect(4, 4, W - 8, 4);
  g.textBaseline = "top"; g.textAlign = "left";
  g.font = `700 22px ${font}`; g.fillStyle = css.ink; g.fillText(fit(spec.title, W - 40), 18, 20);
  if (spec.sub) { g.font = `16px ${font}`; g.fillStyle = css.muted; g.fillText(fit(spec.sub, W - 40), 18, 48); }
  let y = 78;
  for (const b of spec.bars || []) {
    g.font = `17px ${font}`; g.fillStyle = css.muted; g.fillText(String(b[0]), 18, y + 2);
    g.fillStyle = css.line; g.fillRect(110, y + 4, W - 210, 14);
    g.fillStyle = css.cyan; g.fillRect(110, y + 4, Math.max(2, (W - 210) * Math.max(0, Math.min(1, b[1]))), 14);
    g.fillStyle = css.ink; g.textAlign = "right"; g.fillText(String(b[2]), W - 20, y + 2); g.textAlign = "left";
    y += 34;
  }
  if (spec.table) {                                    // a table: the header, then one line a row
    const cols = spec.table.cols || [], xs = spec.table.x || cols.map((_c, k) => 18 + k * ((W - 36) / Math.max(1, cols.length)));
    g.font = `15px ${font}`; g.fillStyle = css.muted;
    cols.forEach((c, k) => g.fillText(String(c), xs[k], y));
    y += 26;
    for (const row of spec.table.rows || []) {
      if (y > H - 30) break;
      g.fillStyle = css.line; g.fillRect(14, y - 4, W - 28, 1);
      row.forEach((cell, k) => {
        g.font = `${k === 0 ? "700 " : ""}20px ${font}`; g.fillStyle = tone(cell.tone);
        g.fillText(fit(cell.t, (xs[k + 1] || W - 18) - xs[k] - 10), xs[k], y + 2);
      });
      y += 34;
    }
  }
  if (spec.cards) {                                    // coin cards: 3 x 2 tiles
    const cw = (W - 36 - 16) / 3, ch = (H - y - 18 - 8) / 2;
    spec.cards.slice(0, 6).forEach((c, k) => {
      const x0 = 18 + (k % 3) * (cw + 8), y0 = y + Math.floor(k / 3) * (ch + 8);
      g.fillStyle = css[c.tone + "Tile"] || css.line; g.fillRect(x0, y0, cw, ch);
      g.strokeStyle = tone(c.tone); g.lineWidth = 1.5; g.strokeRect(x0, y0, cw, ch);
      g.font = `700 16px ${font}`; g.fillStyle = css.ink; g.fillText(fit(c.coin, cw - 16), x0 + 8, y0 + 6);
      g.font = `700 24px ${font}`; g.fillText(fit(c.price, cw - 16), x0 + 8, y0 + 26);
      g.font = `15px ${font}`; g.fillStyle = tone(c.tone); g.fillText(fit(c.chg, cw - 16), x0 + 8, y0 + 54);
      const v = (c.spark || []).filter((q) => Number.isFinite(q));
      if (v.length > 1) {
        const lo = Math.min(...v), hi = Math.max(...v), sp = hi - lo || 1, top = y0 + 74, bot = y0 + ch - 8;
        g.beginPath();
        v.forEach((q, i2) => { const px = x0 + 8 + (i2 / (v.length - 1)) * (cw - 16), py = bot - ((q - lo) / sp) * (bot - top); if (i2) g.lineTo(px, py); else g.moveTo(px, py); });
        g.strokeStyle = tone(c.tone); g.lineWidth = 2; g.stroke();
      }
    });
  }
  for (const r of spec.rows || []) {
    if (y > H - 30) break;
    const big = r.big, x = r.k != null ? 170 : 18;
    if (r.k != null) { g.fillStyle = css.muted; g.font = `16px ${font}`; g.fillText(String(r.k), 18, y + (big ? 8 : 2)); }
    g.font = `${big ? "700 30px" : "18px"} ${font}`; g.fillStyle = tone(r.tone);
    g.fillText(fit(r.t, W - x - 18), x, y);
    y += big ? 42 : 30;
  }
}

/** The floor's words and rings (painted once): the name round the stage, ticks, rings, facing the camera's start. */
function paintFloor(g, css, font, words) {
  const S = g.canvas.width, c = S / 2, unit = S / 7.2;           // the picture covers 7.2 x 7.2 of the room
  g.clearRect(0, 0, S, S);
  g.strokeStyle = css.cyan; g.fillStyle = css.cyan;
  for (const [r, w, a] of [[2.62, 3, 0.55], [2.9, 1.5, 0.35], [3.3, 1, 0.25]]) { g.globalAlpha = a; g.lineWidth = w; g.beginPath(); g.arc(c, c, r * unit, 0, Math.PI * 2); g.stroke(); }
  g.globalAlpha = 0.45;
  for (let i = 0; i < 120; i++) {                                // ticks round the outer ring
    const a = (i / 120) * Math.PI * 2, r0 = 3.3 * unit, r1 = (i % 5 ? 3.36 : 3.45) * unit;
    g.lineWidth = i % 5 ? 1 : 2; g.beginPath(); g.moveTo(c + Math.cos(a) * r0, c + Math.sin(a) * r0); g.lineTo(c + Math.cos(a) * r1, c + Math.sin(a) * r1); g.stroke();
  }
  // the words: on the arc nearest the camera at its start, each letter's top towards the middle (read from the camera)
  const th = Math.atan2(Math.cos(YAW0), Math.sin(YAW0)), R = 3.08 * unit, text = String(words || "");
  g.globalAlpha = 0.9; g.font = `700 ${Math.round(unit * 0.24)}px ${font}`; g.textAlign = "center"; g.textBaseline = "middle";
  const widths = [...text].map((ch) => g.measureText(ch).width + unit * 0.035), total = widths.reduce((a, b) => a + b, 0);
  let acc = -total / 2;
  [...text].forEach((ch, k) => {
    const mid = acc + widths[k] / 2, a = th - mid / R;             // left to right as the camera reads it
    g.save(); g.translate(c + Math.cos(a) * R, c + Math.sin(a) * R); g.rotate(a - Math.PI / 2); g.fillText(ch, 0, 0); g.restore();
    acc += widths[k];
  });
  g.globalAlpha = 1;
}

/** The room on ``canvas``: {draw(scene), panels(specs, css, font), vp, lost()}; null where WebGL cannot start.
 * scene: {W, H, dpr, t (ms), yaw, pitch, drift (the camera's own slow sway), col {name: [r, g, b]}, seats [{group, state, sel}]} */
export function create3d(canvas) {
  let gl = null;
  try { gl = canvas.getContext && (canvas.getContext("webgl", {antialias: true, alpha: true, premultipliedAlpha: false}) || canvas.getContext("experimental-webgl")); }
  catch (e) { gl = null; }
  if (!gl) return null;
  const P = program(gl, VS, FS), Q = program(gl, PVS, PFS), X = program(gl, TVS, TFS);
  if (!P || !Q || !X) return null;
  const U = (p, n) => gl.getUniformLocation(p, n);
  const u = {VP: U(P, "uVP"), M: U(P, "uM"), C: U(P, "uC"), E: U(P, "uE"), A: U(P, "uA"), Eye: U(P, "uEye"), Fog: U(P, "uFog"), FogR: U(P, "uFogR")};
  const q = {VP: U(Q, "uVP"), Scale: U(Q, "uScale"), Mode: U(Q, "uMode")};
  const x = {VP: U(X, "uVP"), M: U(X, "uM"), Tex: U(X, "uTex"), A: U(X, "uA")};
  const aP = gl.getAttribLocation(P, "aP"), aN = gl.getAttribLocation(P, "aN");
  const qP = gl.getAttribLocation(Q, "aP"), qC = gl.getAttribLocation(Q, "aC"), qS = gl.getAttribLocation(Q, "aS");
  const xP = gl.getAttribLocation(X, "aP"), xT = gl.getAttribLocation(X, "aT");
  const upload = (m) => {
    const b = (data, T, kind) => { const o = gl.createBuffer(); gl.bindBuffer(kind, o); gl.bufferData(kind, new T(data), gl.STATIC_DRAW); return o; };
    return {p: b(m.pos, Float32Array, gl.ARRAY_BUFFER), n: b(m.nrm, Float32Array, gl.ARRAY_BUFFER), i: b(m.idx, Uint16Array, gl.ELEMENT_ARRAY_BUFFER), c: m.idx.length};
  };
  const mesh = {box: upload(meshBox()), cyl: upload(meshCyl()), sph: upload(meshSphere()), ring: upload(meshTorus(0.012)), fat: upload(meshTorus(0.05, 72, 8))};
  const quadP = gl.createBuffer(), quadT = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, quadP); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-0.5, -0.5, 0, 0.5, -0.5, 0, 0.5, 0.5, 0, -0.5, -0.5, 0, 0.5, 0.5, 0, -0.5, 0.5, 0]), gl.STATIC_DRAW);
  gl.bindBuffer(gl.ARRAY_BUFFER, quadT); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, 1, 1, 1, 1, 0, 0, 1, 1, 0, 0, 0]), gl.STATIC_DRAW);
  const vb = {p: gl.createBuffer(), c: gl.createBuffer(), s: gl.createBuffer()};
  const motes = [];
  for (let i = 0; i < 320; i++) motes.push([(i * 2.39996) % (Math.PI * 2), 0.04 + ((i * 37) % 100) / 100 * 0.34, ((i * 53) % 100) / 100, 0.12 + ((i * 17) % 10) / 30]);
  const screens = [];                                  // the floating screens: {tex, canvas, g}
  let vp = m4ident(), lost = false;
  canvas.addEventListener && canvas.addEventListener("webglcontextlost", (e) => { e.preventDefault(); lost = true; });

  function solid(m, M, c, e, a, glow) {
    gl.uniformMatrix4fv(u.M, false, new Float32Array(M));
    gl.uniform3fv(u.C, c); gl.uniform3fv(u.E, e || [0, 0, 0]); gl.uniform1f(u.A, a == null ? 1 : a);
    if (glow) { gl.blendFunc(gl.SRC_ALPHA, gl.ONE); gl.depthMask(false); } else { gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA); gl.depthMask(true); }
    gl.bindBuffer(gl.ARRAY_BUFFER, m.p); gl.vertexAttribPointer(aP, 3, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, m.n); gl.vertexAttribPointer(aN, 3, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, m.i);
    gl.drawElements(gl.TRIANGLES, m.c, gl.UNSIGNED_SHORT, 0);
  }
  /** points or lines: ps [[x, y, z]], cs [[r, g, b, a]] (one each, or one for all), ss sizes (room units). */
  function strokes(kind, ps, cs, ss, mode) {
    if (!ps.length) return;
    const P3 = [], C4 = [], S1 = [];
    ps.forEach((p, i) => { P3.push(p[0], p[1], p[2]); C4.push(...(cs[i] || cs[0])); S1.push(ss[i] == null ? ss[0] : ss[i]); });
    const put = (buf, data, loc, n) => { gl.bindBuffer(gl.ARRAY_BUFFER, buf); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(data), gl.DYNAMIC_DRAW); gl.vertexAttribPointer(loc, n, gl.FLOAT, false, 0, 0); };
    put(vb.p, P3, qP, 3); put(vb.c, C4, qC, 4); put(vb.s, S1, qS, 1);
    gl.uniform1f(q.Mode, mode);
    gl.drawArrays(kind, 0, ps.length);
  }
  const scale = (c, k) => [c[0] * k, c[1] * k, c[2] * k];
  const rgba = (c, a) => [c[0], c[1], c[2], a];

  const texOf = (tex, cv) => {
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, cv);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  };
  let floor = null;
  function panels(specs, css, font, words) {
    if (!floor && typeof document !== "undefined") {    // the floor's words and rings, once
      const cv = document.createElement("canvas");
      cv.width = cv.height = 1024;
      const g = cv.getContext("2d");
      if (g) { paintFloor(g, css, font, words || "PAPERBOT"); floor = {tex: gl.createTexture()}; texOf(floor.tex, cv); }
    }
    (specs || []).forEach((spec, i) => {
      const [w, hh] = spec.px || [PW, PH];
      let s = screens[i];
      if (!s || s.cv.width !== w || s.cv.height !== hh) {
        const cv = document.createElement("canvas");
        cv.width = w; cv.height = hh;
        s = screens[i] = {cv, g: cv.getContext("2d"), tex: (s && s.tex) || gl.createTexture()};
      }
      if (!s.g) return;
      s.pose = spec.pose || null;
      paintPanel(s.g, spec, css, font);
      texOf(s.tex, s.cv);
    });
    screens.length = Math.min(screens.length, (specs || []).length);
  }

  // ---- the glow (bloom, as in the owners' video): the room drawn into a picture, its bright parts blurred and added back;
  // where the browser cannot make the pictures, the room is drawn straight onto the canvas
  const QV = `attribute vec2 aQ; varying vec2 vU; void main() { vU = aQ * 0.5 + 0.5; gl_Position = vec4(aQ, 0.0, 1.0); }`;
  const BF = `precision mediump float; uniform sampler2D uT; varying vec2 vU;
void main() { vec3 c = texture2D(uT, vU).rgb; float l = max(max(c.r, c.g), c.b); gl_FragColor = vec4(c * smoothstep(0.5, 1.0, l), 1.0); }`;
  const GF = `precision mediump float; uniform sampler2D uT; uniform vec2 uD; varying vec2 vU;
void main() { vec3 s = texture2D(uT, vU).rgb * 0.227; s += (texture2D(uT, vU + uD * 1.384).rgb + texture2D(uT, vU - uD * 1.384).rgb) * 0.316;
  s += (texture2D(uT, vU + uD * 3.23).rgb + texture2D(uT, vU - uD * 3.23).rgb) * 0.07; gl_FragColor = vec4(s, 1.0); }`;
  const CF = `precision mediump float; uniform sampler2D uS; uniform sampler2D uB; uniform float uK; varying vec2 vU;
void main() { vec3 c = texture2D(uS, vU).rgb + texture2D(uB, vU).rgb * uK; float v = smoothstep(0.45, 1.0, length((vU - 0.5) * vec2(1.25, 1.0)) * 1.35);
  gl_FragColor = vec4(c * (1.0 - 0.45 * v), 1.0); }`;
  const BP = program(gl, QV, BF), GP = program(gl, QV, GF), CP = program(gl, QV, CF);
  const quad2 = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, quad2); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, 1, 1, -1, -1, 1, 1, -1, 1]), gl.STATIC_DRAW);
  let fx = null;                                       // {w, h, scene, a, b}: the pictures (made at the canvas's size)
  function target(w, h, depth) {
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
    for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, k, v);
    const fb = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
    if (depth) {
      const rb = gl.createRenderbuffer();
      gl.bindRenderbuffer(gl.RENDERBUFFER, rb); gl.renderbufferStorage(gl.RENDERBUFFER, gl.DEPTH_COMPONENT16, w, h);
      gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.RENDERBUFFER, rb);
    }
    const okFb = gl.checkFramebufferStatus(gl.FRAMEBUFFER) === gl.FRAMEBUFFER_COMPLETE;
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    return okFb ? {tex, fb, w, h} : null;
  }
  function pictures(W, H) {
    if (!BP || !GP || !CP) return null;
    if (fx && fx.w === W && fx.h === H) return fx.ok ? fx : null;
    const q4 = [Math.max(1, Math.round(W / 4)), Math.max(1, Math.round(H / 4))];
    const sceneT = target(W, H, true), a = target(q4[0], q4[1], false), b = target(q4[0], q4[1], false);
    fx = {w: W, h: H, ok: !!(sceneT && a && b), scene: sceneT, a, b};
    return fx.ok ? fx : null;
  }
  function pass(prog, src, dst, setup) {
    gl.bindFramebuffer(gl.FRAMEBUFFER, dst ? dst.fb : null);
    gl.viewport(0, 0, dst ? dst.w : fx.w, dst ? dst.h : fx.h);
    gl.useProgram(prog);
    const aQ = gl.getAttribLocation(prog, "aQ");
    gl.bindBuffer(gl.ARRAY_BUFFER, quad2); gl.enableVertexAttribArray(aQ); gl.vertexAttribPointer(aQ, 2, gl.FLOAT, false, 0, 0);
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, src.tex); gl.uniform1i(gl.getUniformLocation(prog, prog === CP ? "uS" : "uT"), 0);
    if (setup) setup();
    gl.drawArrays(gl.TRIANGLES, 0, 6);
    gl.disableVertexAttribArray(aQ);
  }

  const ST = STAGE, RING = SEAT_RING, K = SEAT_K;
  function draw(sc) {
    if (lost || (gl.isContextLost && gl.isContextLost())) return null;
    const {W, H, col: C} = sc, t = (sc.t || 0) / 1000;
    const pic = pictures(W, H);
    gl.bindFramebuffer(gl.FRAMEBUFFER, pic ? pic.scene.fb : null);
    gl.viewport(0, 0, W, H);
    if (pic) gl.clearColor(C.bg[0], C.bg[1], C.bg[2], 1); else gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST); gl.enable(gl.BLEND);
    // the camera: swaying slowly round its start (drift), up and down, in and out, as in the owners' video
    const aspect = W / Math.max(1, H), sway = sc.drift ? 1 : 0, fitA = aspect * (sc.fit || 1);
    const dist = Math.max(6.4, (fitA < 1 ? 3.0 : 3.45) / (Math.tan(0.31) * fitA)) * (1 + 0.05 * sway * Math.sin(t * 0.13));
    const pitch = sc.pitch + 0.05 * sway * Math.sin(t * 0.21);
    const yaw = sc.yaw + 0.3 * sway * Math.sin(t * 0.075);
    const eye = [Math.sin(yaw) * Math.cos(pitch) * dist, Math.sin(pitch) * dist, Math.cos(yaw) * Math.cos(pitch) * dist];
    vp = m4mul(m4persp(0.62, aspect, 0.1, 80), m4look(eye, [0, aspect < 1 ? -0.5 : 0.35, 0]));
    gl.useProgram(P);
    gl.enableVertexAttribArray(aP); gl.enableVertexAttribArray(aN);
    gl.uniformMatrix4fv(u.VP, false, new Float32Array(vp));
    gl.uniform3fv(u.Eye, eye); gl.uniform3fv(u.Fog, C.bg); gl.uniform2fv(u.FogR, [dist * 0.8, dist * 2.4]);
    const cyan = C.cyan, blue = C.blue, green = C.green, neon0 = () => C.neon || green;
    // the floor and the big stage, its glowing edge, dashes turning round it
    solid(mesh.cyl, m4trs([0, -0.06, 0], 0, [9, 0.04, 9]), C.floor, scale(C.floor, 0.15), 1);
    solid(mesh.cyl, m4trs([0, -0.04, 0], 0, [ST, 0.04, ST]), C.desk, scale(blue, 0.05), 1);
    solid(mesh.fat, m4trs([0, 0.0, 0], 0, [ST, 0.5, ST]), cyan, scale(cyan, 0.55), 0.55, true);
    for (const [r, a] of [[ST + 0.45, 0.4], [ST + 0.85, 0.22], [ST + 1.9, 0.14], [ST + 3.0, 0.08]]) solid(mesh.ring, m4trs([0, -0.018, 0], 0, [r, 1, r]), cyan, scale(cyan, 0.9), a, true);
    for (let i = 0; i < 64; i++) {
      const a = (i / 64) * Math.PI * 2 - t * 0.04;
      solid(mesh.box, m4trs([Math.cos(a) * (ST + 0.22), -0.015, Math.sin(a) * (ST + 0.22)], Math.PI / 2 - a, [0.14, 0.004, 0.022]), blue, scale(blue, 0.8), 0.5, true);
    }
    if (floor) {                                       // the floor's words and rings (a picture lying flat)
      gl.useProgram(X);
      gl.disableVertexAttribArray(aN); gl.disableVertexAttribArray(aP);
      gl.enableVertexAttribArray(xP); gl.enableVertexAttribArray(xT);
      gl.uniformMatrix4fv(x.VP, false, new Float32Array(vp));
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE); gl.depthMask(false);
      gl.bindBuffer(gl.ARRAY_BUFFER, quadP); gl.vertexAttribPointer(xP, 3, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ARRAY_BUFFER, quadT); gl.vertexAttribPointer(xT, 2, gl.FLOAT, false, 0, 0);
      gl.activeTexture(gl.TEXTURE0); gl.uniform1i(x.Tex, 0); gl.bindTexture(gl.TEXTURE_2D, floor.tex);
      gl.uniformMatrix4fv(x.M, false, new Float32Array(m4mul(m4trs([0, 0.004, 0], 0, [9.2, 1, 9.2]), m4rotx(-Math.PI / 2))));
      gl.uniform1f(x.A, 0.9);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
      gl.disableVertexAttribArray(xP); gl.disableVertexAttribArray(xT);
      gl.useProgram(P);
      gl.enableVertexAttribArray(aP); gl.enableVertexAttribArray(aN);
    }
    // the open middle: a low round floor of light with rings and turning spokes, a small pedestal with its core
    solid(mesh.cyl, m4trs([0, 0, 0], 0, [1.55, 0.05, 1.55]), C.table, scale(blue, 0.06), 1);
    solid(mesh.fat, m4trs([0, 0.05, 0], 0, [1.55, 0.7, 1.55]), neon0(), scale(neon0(), 0.7), 0.6, true);
    for (const [r, a] of [[0.55, 0.5], [0.9, 0.35], [1.25, 0.28]]) solid(mesh.ring, m4trs([0, 0.055, 0], t * 0.05, [r, 1, r]), cyan, scale(cyan, 0.7), a, true);
    for (let i = 0; i < 32; i++) {
      const a = (i / 32) * Math.PI * 2 + t * 0.08, r0 = i % 2 ? 0.55 : 0.9, rm = (r0 + 1.5) / 2;
      solid(mesh.box, m4trs([Math.cos(a) * rm, 0.054, Math.sin(a) * rm], -a, [1.5 - r0, 0.004, 0.012]), blue, scale(blue, 0.5), 0.25, true);
    }
    solid(mesh.cyl, m4trs([0, 0.05, 0], 0, [0.32, 0.22, 0.32]), C.desk, scale(blue, 0.08), 1);
    solid(mesh.fat, m4trs([0, 0.27, 0], 0, [0.32, 0.8, 0.32]), neon0(), scale(neon0(), 0.8), 0.8, true);
    solid(mesh.sph, m4trs([0, 0.46, 0], 0, [0.13, 0.13, 0.13]), neon0(), scale(neon0(), 0.9), 1);
    // the seats round the ring: a pod of light, a desk with its lit monitor, a chair, a figure at work
    const n = sc.seats.length, glows = [], glowC = [], glowS = [];
    sc.seats.forEach((s, i) => {
      const p = seatPose(i, n, RING), st = C["s-" + s.state] || C.muted, tint = C["g-" + s.group] || C.ink;
      const off = s.state === "off", busy = s.state === "live" || s.state === "wait", pulse = s.state === "live" ? 0.65 + 0.35 * Math.sin(t * 3 + i) : 1;
      const out = [Math.cos(p.a), Math.sin(p.a)], side = [-Math.sin(p.a), Math.cos(p.a)];
      const at = (d, y, w = 0) => [p.x + (out[0] * d + side[0] * w) * K, y * K, p.z + (out[1] * d + side[1] * w) * K];
      const part = (m, pos, yw, sz, c, e, a, glow) => solid(m, m4trs(pos, yw, [sz[0] * K, sz[1] * K, sz[2] * K]), c, e, a, glow);
      part(mesh.cyl, at(0.06, 0.0), 0, [0.5, 0.06, 0.5], C.desk, scale(blue, 0.05), 1);                                // the pod
      part(mesh.fat, at(0.06, 0.06), 0, [0.5, 0.6, 0.5], st, scale(st, 0.45 * pulse), 0.55, true);
      part(mesh.fat, at(0.06, 0.06), 0, [0.54, 2.0, 0.54], st, scale(st, 0.2 * pulse), 0.12, true);
      part(mesh.box, at(-0.22, 0.22), p.yaw, [0.62, 0.34, 0.26], C.desk, scale(blue, 0.03), 1);                          // the desk
      part(mesh.box, at(-0.09, 0.395), p.yaw, [0.64, 0.01, 0.014], cyan, scale(cyan, 0.8), 0.8, true);
      part(mesh.box, at(-0.27, 0.56), p.yaw, [0.46, 0.29, 0.02], C.desk, [0, 0, 0], 1);                                  // the monitor
      const flick = off ? 0.1 : 0.55 * pulse * (0.92 + 0.08 * Math.sin(t * 9 + i * 3));
      part(mesh.box, at(-0.255, 0.56), p.yaw, [0.43, 0.26, 0.006], scale(off ? C.muted : st, 0.6), scale(off ? C.muted : st, flick), 1);
      for (let k = 0; k < 5; k++) {
        const hgt = 0.03 + 0.05 * ((Math.sin(t * (0.8 + k * 0.35) + i * 1.7 + k) + 1) / 2) * (off ? 0 : 1);
        part(mesh.box, at(-0.25, 0.45 + hgt / 2, -0.14 + k * 0.07), p.yaw, [0.035, hgt, 0.004], C.ink, scale(C.ink, off ? 0.1 : 0.6), 0.9, true);
      }
      if (!off) { glows.push(at(-0.2, 0.56)); glowC.push(rgba(st, 0.5 * pulse)); glowS.push(0.75); }
      part(mesh.box, at(0.14, 0.24), p.yaw, [0.26, 0.05, 0.24], C.chair, [0, 0, 0], 1);                                  // the chair
      part(mesh.box, at(0.27, 0.45), p.yaw, [0.26, 0.38, 0.04], C.chair, [0, 0, 0], 1);
      part(mesh.cyl, at(0.14, 0.05), 0, [0.025, 0.19, 0.025], C.chair, [0, 0, 0], 1);
      // the figure: a body, a big head with a cap in its group's colour and two eyes, arms typing while it works
      const fig = off ? scale(tint, 0.45) : tint, face = off ? scale(C.sand, 0.45) : C.sand;
      const bob = busy ? 0.01 * Math.sin(t * 2.2 + i) : off ? -0.02 : 0;
      part(mesh.cyl, at(0.13, 0.27), 0, [0.095, 0.25, 0.095], fig, scale(fig, 0.12), 1);
      part(mesh.sph, at(0.13, 0.52), 0, [0.105, 0.075, 0.105], fig, scale(fig, 0.12), 1);
      const hc = at(0.11, 0.68 + bob);
      part(mesh.sph, hc, 0, [0.125, 0.12, 0.125], face, scale(face, 0.15), 1);
      part(mesh.sph, at(0.11, 0.73 + bob), 0, [0.13, 0.078, 0.13], fig, scale(fig, 0.2), 1);
      for (const k of [-1, 1]) {
        part(mesh.sph, at(-0.005, 0.69 + bob, 0.047 * k), 0, [0.018, 0.024, 0.018], C.bg, [0, 0, 0], 1);
        const tap = busy ? 0.012 * Math.sin(t * (s.state === "live" ? 16 : 9) + k * Math.PI + i) : 0;
        part(mesh.box, at(-0.01, 0.47 + tap, 0.11 * k), p.yaw, [0.05, 0.05, 0.26], fig, scale(fig, 0.12), 1);
        part(mesh.sph, at(-0.14, 0.47 + tap, 0.11 * k), 0, [0.035, 0.035, 0.035], face, scale(face, 0.15), 1);
      }
      const kind = i % 5;                                           // a touch of its own (decoration)
      if (kind === 0) for (const k of [-1, 1]) part(mesh.sph, at(0.11, 0.79 + bob, 0.078 * k), 0, [0.042, 0.042, 0.042], fig, scale(fig, 0.2), 1);
      if (kind === 1) {
        for (const k of [-1, 1]) part(mesh.sph, at(0.11, 0.68 + bob, 0.12 * k), 0, [0.036, 0.048, 0.036], C.chair, scale(st, 0.4), 1);
        part(mesh.sph, at(0.02, 0.62 + bob, 0.085), 0, [0.016, 0.016, 0.016], st, scale(st, 1), 1);
      }
      if (kind === 2) { part(mesh.cyl, at(0.11, 0.78 + bob), 0, [0.008, 0.09, 0.008], C.ink, [0, 0, 0], 1); part(mesh.sph, at(0.11, 0.89 + bob), 0, [0.026, 0.026, 0.026], st, scale(st, 1.2), 1); }
      if (kind === 3) part(mesh.sph, at(0.21, 0.73 + bob), 0, [0.056, 0.056, 0.056], fig, scale(fig, 0.2), 1);
      if (kind === 4) part(mesh.cyl, at(0.04, 0.715 + bob), p.yaw, [0.14, 0.012, 0.14], fig, scale(fig, 0.2), 1);
      if (s.sel) part(mesh.ring, at(0.06, 1.0), t, [0.18, 1, 0.18], C.ink, scale(C.ink, 1), 1, true);
    });
    solid(mesh.sph, m4trs([0, 0.05, 0], 0, [1.5, 1.35, 1.5]), green, scale(green, 0.45), 0.045, true);    // the dome's haze
    // the floating screens round the room: the programs' own numbers (paintPanel), facing the middle; the ones turned
    // away from the camera are not drawn
    if (screens.length) {
      gl.useProgram(X);
      gl.disableVertexAttribArray(aN);
      gl.enableVertexAttribArray(xP); gl.enableVertexAttribArray(xT);
      gl.uniformMatrix4fv(x.VP, false, new Float32Array(vp));
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA); gl.depthMask(false);
      gl.bindBuffer(gl.ARRAY_BUFFER, quadP); gl.vertexAttribPointer(xP, 3, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ARRAY_BUFFER, quadT); gl.vertexAttribPointer(xT, 2, gl.FLOAT, false, 0, 0);
      gl.activeTexture(gl.TEXTURE0); gl.uniform1i(x.Tex, 0);
      screens.forEach((s, i) => {
        const pp0 = s.pose ? layoutPose({...s.pose, r: (s.pose.r || 3.3) + 1.05, y: (s.pose.y == null ? 1.25 : s.pose.y) + 0.35}) : {...panelPose(i, screens.length, 4.3), y: 1.6, w: 1.7, h: 1.06};
        const pp = {...pp0, w: pp0.w * 1.12, h: pp0.h * 1.12};
        const y = pp.y + 0.04 * Math.sin(t * 0.7 + i);
        const nx = -Math.cos(pp.b), nz = -Math.sin(pp.b), facing = nx * (eye[0] - pp.x) + nz * (eye[2] - pp.z);
        if (facing <= 0) return;
        gl.bindTexture(gl.TEXTURE_2D, s.tex);
        gl.uniformMatrix4fv(x.M, false, new Float32Array(m4trs([pp.x, y, pp.z], pp.yaw, [pp.w, pp.h, 1])));
        gl.uniform1f(x.A, Math.min(0.95, 0.35 + facing / dist));
        gl.drawArrays(gl.TRIANGLES, 0, 6);
      });
      gl.disableVertexAttribArray(xP); gl.disableVertexAttribArray(xT);
    }
    // glows, the energy in the middle, the motes, the energy dome
    gl.useProgram(Q);
    gl.disableVertexAttribArray(aN); gl.disableVertexAttribArray(aP);
    gl.enableVertexAttribArray(qP); gl.enableVertexAttribArray(qC); gl.enableVertexAttribArray(qS);
    gl.uniformMatrix4fv(q.VP, false, new Float32Array(vp));
    gl.uniform1f(q.Scale, H * 0.9);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE); gl.depthMask(false);
    for (const [k, strand] of helix(t, 6, 40).entries()) {
      const c = k % 2 ? rgba(cyan, 0.5) : rgba(green, 0.65);
      strokes(gl.LINE_STRIP, strand.map((q2) => [q2[0] * 0.8, 0.3 + (q2[1] - 0.18) * 0.7, q2[2] * 0.8]), [c], [1], 2);
    }
    const ms = [], mc = [];
    for (const [a0, r, y0, v] of motes) {
      const yy = (y0 + t * v * 0.12) % 1, a = a0 + t * 0.35;
      ms.push([Math.cos(a) * r * 1.3, 0.3 + yy * 1.4, Math.sin(a) * r * 1.3]); mc.push(yy > 0.6 ? rgba(C.sand, 0.8) : rgba(green, 0.75));
    }
    strokes(gl.POINTS, ms, mc, [0.02], 0);
    glows.push([0, 0.46, 0], [0, 0.9, 0]); glowC.push(rgba(green, 0.7), rgba(green, 0.25)); glowS.push(1.6, 4.0);
    strokes(gl.POINTS, glows, glowC, glowS, 1);
    // the energy dome (the owners' video): thick ribbons of mint-green light with white-hot middles, a twisted cage from the
    // top of the middle down to the open floor's edge, turning and flickering; three bright bundles to every running program
    const neon = C.neon || green, hot = [Math.min(1, neon[0] * 0.5 + 0.55), Math.min(1, neon[1] * 0.4 + 0.62), Math.min(1, neon[2] * 0.45 + 0.55)];
    const tri = [], triC = [];
    const add = (pts, w, c, a, core) => { for (const v of ribbon(pts, eye, w)) { tri.push([v[0], v[1], v[2]]); triC.push(rgba(core && v[3] > 0.5 ? hot : c, a * v[3])); } };
    for (const arc of domeArcs(t, 30, 26)) {
      add(arc.pts, 0.04, neon, 0.16 * arc.glow, false);
      add(arc.pts, 0.01, neon, 0.55 * arc.glow, arc.glow > 0.85);
    }
    const core = [0, 1.55, 0], dots = [];
    sc.seats.forEach((s, i) => {
      if (s.state !== "live" && s.state !== "wait") return;
      const p = seatPose(i, n, RING), to = [p.x * 0.86, 0.5 * K, p.z * 0.86];
      for (let m = 0; m < 3; m++) {
        const lift = 0.35 + 0.15 * m + 0.08 * Math.sin(t * 2.3 + i + m), wob = 0.05 * Math.sin(t * 9 + i * 1.7 + m * 2.1);
        const pts = arcPts(core, [to[0] + wob, to[1], to[2] - wob], lift, 26), flick = 0.6 + 0.4 * Math.abs(Math.sin(t * (2.2 + m) + i * 0.9));
        add(pts, 0.045, neon, 0.25 * flick, false);
        add(pts, 0.012, neon, 0.8 * flick, true);
      }
      const f = (t * 0.45 + i * 0.37) % 1;
      dots.push(arcPts(core, to, 0.35, 26)[Math.floor(f * 25)]);
    });
    strokes(gl.TRIANGLES, tri, triC, [1], 2);
    strokes(gl.POINTS, dots, [rgba(hot, 0.95)], [0.07], 1);
    strokes(gl.POINTS, [core, [0, 0.46, 0]], [rgba(neon, 0.45), rgba(neon, 0.5)], [0.7, 1.4], 1);
    gl.disableVertexAttribArray(qP); gl.disableVertexAttribArray(qC); gl.disableVertexAttribArray(qS);
    gl.depthMask(true);
    if (pic) {                                         // the glow: bright parts, blurred twice each way, added back
      gl.disable(gl.DEPTH_TEST); gl.disable(gl.BLEND);
      pass(BP, pic.scene, pic.a);
      for (let r = 0; r < 2; r++) {
        pass(GP, pic.a, pic.b, () => gl.uniform2fv(gl.getUniformLocation(GP, "uD"), [1 / pic.a.w, 0]));
        pass(GP, pic.b, pic.a, () => gl.uniform2fv(gl.getUniformLocation(GP, "uD"), [0, 1 / pic.a.h]));
      }
      pass(CP, pic.scene, null, () => {
        gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, pic.a.tex); gl.uniform1i(gl.getUniformLocation(CP, "uB"), 1);
        gl.uniform1f(gl.getUniformLocation(CP, "uK"), 1.05);
        gl.activeTexture(gl.TEXTURE0);
      });
      gl.enable(gl.DEPTH_TEST); gl.enable(gl.BLEND);
    }
    return vp;
  }
  return {draw, panels, get vp() { return vp; }, lost: () => lost};
}
