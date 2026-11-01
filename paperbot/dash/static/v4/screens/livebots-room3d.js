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

/** One floating screen's picture: its title, its rows of words, its bars (the screen module gives the words: the
 * programs' records). css: the token colours as CSS strings; font: the page's terminal font. */
function paintPanel(g, spec, css, font) {
  g.clearRect(0, 0, PW, PH);
  g.globalAlpha = 0.82; g.fillStyle = css.panel; g.fillRect(4, 4, PW - 8, PH - 8);
  g.globalAlpha = 1; g.strokeStyle = css.cyan; g.lineWidth = 3; g.strokeRect(4, 4, PW - 8, PH - 8);
  g.fillStyle = css.cyan; g.fillRect(4, 4, PW - 8, 4);
  g.font = `700 22px ${font}`; g.fillStyle = css.ink; g.textBaseline = "top";
  g.fillText(String(spec.title || ""), 18, 20);
  if (spec.sub) { g.font = `16px ${font}`; g.fillStyle = css.muted; g.fillText(String(spec.sub), 18, 48); }
  let y = 78;
  const tone = (t) => css[t] || css.ink;
  for (const b of spec.bars || []) {
    g.font = `17px ${font}`; g.fillStyle = css.muted; g.fillText(String(b[0]), 18, y + 2);
    g.fillStyle = css.line; g.fillRect(110, y + 4, PW - 210, 14);
    g.fillStyle = css.cyan; g.fillRect(110, y + 4, Math.max(2, (PW - 210) * Math.max(0, Math.min(1, b[1]))), 14);
    g.fillStyle = css.ink; g.textAlign = "right"; g.fillText(String(b[2]), PW - 20, y + 2); g.textAlign = "left";
    y += 34;
  }
  for (const r of spec.rows || []) {
    if (y > PH - 30) break;
    const big = r.big;
    g.font = `${big ? "700 30px" : "18px"} ${font}`;
    if (r.k != null) { g.fillStyle = css.muted; g.font = `16px ${font}`; g.fillText(String(r.k), 18, y + (big ? 8 : 2)); g.font = `${big ? "700 30px" : "18px"} ${font}`; }
    g.fillStyle = tone(r.tone);
    const x = r.k != null ? 170 : 18, text = String(r.t == null ? "" : r.t);
    let s = text;
    while (s.length > 1 && g.measureText(s).width > PW - x - 18) s = s.slice(0, -1);
    g.fillText(s === text ? s : s.slice(0, -1) + "…", x, y);
    y += big ? 42 : 30;
  }
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

  function panels(specs, css, font) {
    (specs || []).forEach((spec, i) => {
      let s = screens[i];
      if (!s) {
        const cv = document.createElement("canvas");
        cv.width = PW; cv.height = PH;
        s = screens[i] = {cv, g: cv.getContext("2d"), tex: gl.createTexture()};
      }
      if (!s.g) return;
      paintPanel(s.g, spec, css, font);
      gl.bindTexture(gl.TEXTURE_2D, s.tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, s.cv);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    });
    screens.length = Math.min(screens.length, (specs || []).length);
  }

  function draw(sc) {
    if (lost || (gl.isContextLost && gl.isContextLost())) return null;
    const {W, H, col: C} = sc, t = (sc.t || 0) / 1000;
    gl.viewport(0, 0, W, H);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST); gl.enable(gl.BLEND);
    // the camera: circling, and (drift) swaying slowly up and down and in and out, as in the owners' video
    const aspect = W / Math.max(1, H), sway = sc.drift ? 1 : 0;
    const dist = Math.max(6.2, (aspect < 1 ? 2.4 : 2.75) / (Math.tan(0.31) * aspect)) * (1 + 0.05 * sway * Math.sin(t * 0.13));
    const pitch = sc.pitch + 0.05 * sway * Math.sin(t * 0.21);
    const eye = [Math.sin(sc.yaw) * Math.cos(pitch) * dist, Math.sin(pitch) * dist, Math.cos(sc.yaw) * Math.cos(pitch) * dist];
    vp = m4mul(m4persp(0.62, aspect, 0.1, 60), m4look(eye, [0, aspect < 1 ? -0.35 : 0.42, 0]));
    gl.useProgram(P);
    gl.enableVertexAttribArray(aP); gl.enableVertexAttribArray(aN);
    gl.uniformMatrix4fv(u.VP, false, new Float32Array(vp));
    gl.uniform3fv(u.Eye, eye); gl.uniform3fv(u.Fog, C.bg); gl.uniform2fv(u.FogR, [dist * 0.75, dist * 2.4]);
    const cyan = C.cyan, blue = C.blue, green = C.green;
    // the floor, the stage the desks stand on, their glowing edges
    solid(mesh.cyl, m4trs([0, -0.06, 0], 0, [6, 0.04, 6]), C.floor, scale(C.floor, 0.15), 1);
    solid(mesh.cyl, m4trs([0, -0.03, 0], 0, [2.55, 0.03, 2.55]), C.desk, scale(blue, 0.04), 1);
    solid(mesh.fat, m4trs([0, 0.002, 0], 0, [2.55, 0.5, 2.55]), cyan, scale(cyan, 0.9), 0.8, true);
    for (const [r, a] of [[3.0, 0.4], [3.35, 0.22], [4.4, 0.16], [5.2, 0.1]]) solid(mesh.ring, m4trs([0, -0.018, 0], 0, [r, 1, r]), cyan, scale(cyan, 0.9), a, true);
    for (let i = 0; i < 48; i++) {                    // dashes round the stage's edge, turning slowly
      const a = (i / 48) * Math.PI * 2 - t * 0.04;
      solid(mesh.box, m4trs([Math.cos(a) * 2.75, -0.015, Math.sin(a) * 2.75], Math.PI / 2 - a, [0.12, 0.004, 0.02]), blue, scale(blue, 0.8), 0.5, true);
    }
    // the table: a dark round top, a glowing rim, rings and turning spokes on it
    solid(mesh.cyl, m4trs([0, 0, 0], 0, [1.25, 0.16, 1.25]), C.table, scale(blue, 0.05), 1);
    solid(mesh.fat, m4trs([0, 0.16, 0], 0, [1.25, 1, 1.25]), cyan, scale(cyan, 1.1), 0.95, true);
    solid(mesh.fat, m4trs([0, 0.16, 0], 0, [1.29, 3, 1.29]), cyan, scale(cyan, 0.5), 0.25, true);
    for (const [r, a] of [[0.38, 0.55], [0.66, 0.38], [0.95, 0.3]]) solid(mesh.ring, m4trs([0, 0.165, 0], t * 0.05, [r, 1, r]), cyan, scale(cyan, 0.7), a, true);
    for (let i = 0; i < 24; i++) {
      const a = (i / 24) * Math.PI * 2 + t * 0.08, r0 = i % 2 ? 0.4 : 0.68, rm = (r0 + 1.2) / 2;
      solid(mesh.box, m4trs([Math.cos(a) * rm, 0.163, Math.sin(a) * rm], -a, [1.2 - r0, 0.004, 0.01]), blue, scale(blue, 0.5), 0.22, true);
    }
    // the seats: a pod of light, a desk with its lit monitor, a chair, a figure at work
    const n = sc.seats.length, glows = [], glowC = [], glowS = [];
    sc.seats.forEach((s, i) => {
      const p = seatPose(i, n), st = C["s-" + s.state] || C.muted, tint = C["g-" + s.group] || C.ink;
      const off = s.state === "off", busy = s.state === "live" || s.state === "wait", pulse = s.state === "live" ? 0.65 + 0.35 * Math.sin(t * 3 + i) : 1;
      const out = [Math.cos(p.a), Math.sin(p.a)], side = [-Math.sin(p.a), Math.cos(p.a)];
      const at = (d, y, w = 0) => [p.x + out[0] * d + side[0] * w, y, p.z + out[1] * d + side[1] * w];
      solid(mesh.cyl, m4trs(at(0.12, 0.0), 0, [0.4, 0.05, 0.4]), C.desk, scale(blue, 0.05), 1);                     // the pod
      solid(mesh.fat, m4trs(at(0.12, 0.05), 0, [0.4, 0.8, 0.4]), st, scale(st, 0.75 * pulse), 0.75, true);
      solid(mesh.fat, m4trs(at(0.12, 0.05), 0, [0.43, 2.4, 0.43]), st, scale(st, 0.35 * pulse), 0.2, true);
      // the desk (towards the table) and its monitor, facing the figure
      solid(mesh.box, m4trs(at(-0.22, 0.22), p.yaw, [0.62, 0.34, 0.26]), C.desk, scale(blue, 0.03), 1);
      solid(mesh.box, m4trs(at(-0.09, 0.395), p.yaw, [0.64, 0.01, 0.014]), cyan, scale(cyan, 0.8), 0.8, true);
      solid(mesh.box, m4trs(at(-0.27, 0.56), p.yaw, [0.46, 0.29, 0.02]), C.desk, [0, 0, 0], 1);
      const flick = off ? 0.1 : 0.5 * pulse * (0.92 + 0.08 * Math.sin(t * 9 + i * 3));
      solid(mesh.box, m4trs(at(-0.255, 0.56), p.yaw, [0.43, 0.26, 0.006]), scale(off ? C.muted : st, 0.6), scale(off ? C.muted : st, flick), 1);
      for (let k = 0; k < 5; k++) {                                   // bars moving on the screen (decoration)
        const hgt = 0.03 + 0.05 * ((Math.sin(t * (0.8 + k * 0.35) + i * 1.7 + k) + 1) / 2) * (off ? 0 : 1);
        solid(mesh.box, m4trs(at(-0.25, 0.45 + hgt / 2, -0.14 + k * 0.07), p.yaw, [0.035, hgt, 0.004]), C.ink, scale(C.ink, off ? 0.1 : 0.6), 0.9, true);
      }
      if (!off) { glows.push(at(-0.2, 0.56)); glowC.push(rgba(st, 0.5 * pulse)); glowS.push(0.9); }
      // the chair
      solid(mesh.box, m4trs(at(0.14, 0.24), p.yaw, [0.26, 0.05, 0.24]), C.chair, [0, 0, 0], 1);
      solid(mesh.box, m4trs(at(0.27, 0.45), p.yaw, [0.26, 0.38, 0.04]), C.chair, [0, 0, 0], 1);
      solid(mesh.cyl, m4trs(at(0.14, 0.05), 0, [0.025, 0.19, 0.025]), C.chair, [0, 0, 0], 1);
      // the figure: a body, a big head with a cap in its group's colour and two eyes, arms typing while it works
      const fig = off ? scale(tint, 0.45) : tint, face = off ? scale(C.sand, 0.45) : C.sand;
      const bob = busy ? 0.008 * Math.sin(t * 2.2 + i) : off ? -0.02 : 0;
      solid(mesh.cyl, m4trs(at(0.13, 0.27), 0, [0.095, 0.25, 0.095]), fig, scale(fig, 0.12), 1);
      solid(mesh.sph, m4trs(at(0.13, 0.52), 0, [0.105, 0.075, 0.105]), fig, scale(fig, 0.12), 1);
      const hc = at(0.11, 0.68 + bob);
      solid(mesh.sph, m4trs(hc, 0, [0.12, 0.115, 0.12]), face, scale(face, 0.15), 1);
      solid(mesh.sph, m4trs([hc[0], hc[1] + 0.05, hc[2]], 0, [0.125, 0.075, 0.125]), fig, scale(fig, 0.2), 1);
      for (const k of [-1, 1]) {
        const e = at(0.0, 0.69 + bob, 0.045 * k);
        solid(mesh.sph, m4trs(e, 0, [0.017, 0.022, 0.017]), C.bg, [0, 0, 0], 1);
        const tap = busy ? 0.012 * Math.sin(t * (s.state === "live" ? 16 : 9) + k * Math.PI + i) : 0;
        solid(mesh.box, m4trs(at(-0.01, 0.47 + tap, 0.11 * k), p.yaw, [0.05, 0.05, 0.26]), fig, scale(fig, 0.12), 1);
        solid(mesh.sph, m4trs(at(-0.14, 0.47 + tap, 0.11 * k), 0, [0.035, 0.035, 0.035]), face, scale(face, 0.15), 1);
      }
      if (s.sel) solid(mesh.ring, m4trs(at(0.12, 0.92), t, [0.15, 1, 0.15]), C.ink, scale(C.ink, 1), 1, true);
    });
    // the middle: a column of light and floating rings
    solid(mesh.cyl, m4trs([0, 0.16, 0], 0, [0.34, 1.25, 0.34]), green, scale(green, 0.3), 0.1, true);
    solid(mesh.cyl, m4trs([0, 0.16, 0], 0, [0.12, 1.5, 0.12]), cyan, scale(cyan, 0.7), 0.16, true);
    for (const [y, r, k] of [[0.55, 0.42, 1], [0.9, 0.32, -1.4], [1.25, 0.24, 1.9], [1.55, 0.16, -2.4]]) solid(mesh.fat, m4trs([0, y, 0], t * k, [r, 0.6, r]), cyan, scale(cyan, 1), 0.7, true);
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
        const pp = panelPose(i, screens.length), y = 1.22 + 0.05 * Math.sin(t * 0.7 + i);
        const nx = -Math.cos(pp.b), nz = -Math.sin(pp.b), face = nx * (eye[0] - pp.x) + nz * (eye[2] - pp.z);
        if (face <= 0) return;
        gl.bindTexture(gl.TEXTURE_2D, s.tex);
        gl.uniformMatrix4fv(x.M, false, new Float32Array(m4trs([pp.x, y, pp.z], pp.yaw, [1.7, 1.06, 1])));
        gl.uniform1f(x.A, Math.min(0.95, 0.35 + face / dist));
        gl.drawArrays(gl.TRIANGLES, 0, 6);
      });
      gl.disableVertexAttribArray(xP); gl.disableVertexAttribArray(xT);
    }
    // glows, the energy in the middle, the motes, a beam to each running program
    gl.useProgram(Q);
    gl.disableVertexAttribArray(aN); gl.disableVertexAttribArray(aP);
    gl.enableVertexAttribArray(qP); gl.enableVertexAttribArray(qC); gl.enableVertexAttribArray(qS);
    gl.uniformMatrix4fv(q.VP, false, new Float32Array(vp));
    gl.uniform1f(q.Scale, H * 0.9);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE); gl.depthMask(false);
    for (const [k, strand] of helix(t).entries()) {                  // the vortex: helices of green and cyan
      const c = k % 2 ? rgba(cyan, 0.55) : rgba(green, 0.7);
      strokes(gl.LINE_STRIP, strand, [c], [1], 2);
    }
    const ms = [], mc = [];
    for (const [a0, r, y0, v] of motes) {
      const yy = (y0 + t * v * 0.12) % 1, a = a0 + t * 0.35;
      ms.push([Math.cos(a) * r, 0.18 + yy * 1.6, Math.sin(a) * r]); mc.push(yy > 0.6 ? rgba(C.sand, 0.8) : rgba(green, 0.75));
    }
    strokes(gl.POINTS, ms, mc, [0.02], 0);
    glows.push([0, 0.9, 0], [0, 0.2, 0]); glowC.push(rgba(green, 0.35), rgba(cyan, 0.4)); glowS.push(3.2, 2.4);
    strokes(gl.POINTS, glows, glowC, glowS, 1);
    const beams = [], beamC = [], dots = [];
    sc.seats.forEach((s, i) => {
      if (s.state !== "live" && s.state !== "wait") return;
      const p = seatPose(i, n), e = [p.x * 0.8, 0.7, p.z * 0.8], c = rgba(C["s-" + s.state] || green, 0.6);
      beams.push([0, 1.15, 0], e); beamC.push(c, c);
      const f = (t * 0.45 + i * 0.37) % 1;
      dots.push([e[0] * f, 1.15 + (0.7 - 1.15) * f, e[2] * f]);
    });
    strokes(gl.LINES, beams, beamC, [1], 2);
    strokes(gl.POINTS, dots, [rgba(green, 0.95)], [0.045], 1);
    gl.disableVertexAttribArray(qP); gl.disableVertexAttribArray(qC); gl.disableVertexAttribArray(qS);
    gl.depthMask(true);
    return vp;
  }
  return {draw, panels, get vp() { return vp; }, lost: () => lost};
}
