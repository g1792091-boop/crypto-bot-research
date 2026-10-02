// 화면 도우미 (GH Nano 사무실 · GH Coin 본부 공용)
// ① hscroll: 가로로 넘치는 줄(방 탭·위쪽 버튼 막대)을 마우스 휠·끌기·◀ ▶ 버튼으로 옆으로 움직이게 한다
// ② stageZoom: 픽셀 사무실을 확대·축소·끌어서 이동 (Ctrl+휠 확대, 더블클릭 그 자리 확대, 배율 기억)
export function hscroll(el, {arrows = true} = {}){
  if (!el || el._hs) return; el._hs = true;
  el.classList.add("hs-row");
  // 휠: 세로 휠도 가로로 (가로로 더 갈 곳이 있을 때만 → 끝에 닿으면 페이지 스크롤에 양보)
  el.addEventListener("wheel", e => {
    if (el.scrollWidth <= el.clientWidth + 2 || e.ctrlKey) return;
    const d = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
    const before = el.scrollLeft; el.scrollLeft += d; if (el.scrollLeft !== before) e.preventDefault();
  }, {passive: false});
  // 끌기 (마우스) — 5px 넘게 움직이면 클릭 대신 이동
  let sx = 0, sl = 0, down = false, moved = false;
  el.addEventListener("pointerdown", e => { if (e.pointerType !== "mouse" || e.button !== 0) return; down = true; moved = false; sx = e.clientX; sl = el.scrollLeft; });
  addEventListener("pointermove", e => { if (!down) return; const dx = e.clientX - sx; if (Math.abs(dx) > 5) moved = true; if (moved) el.scrollLeft = sl - dx; });
  addEventListener("pointerup", () => { down = false; });
  el.addEventListener("click", e => { if (moved){ e.stopPropagation(); e.preventDefault(); moved = false; } }, true);
  if (!arrows) return;
  // ◀ ▶ 버튼: 넘칠 때만 보임
  const wrap = document.createElement("div"); wrap.className = "hs-wrap";
  el.parentNode.insertBefore(wrap, el); wrap.appendChild(el);
  const mk = (cls, txt, dir) => { const b = document.createElement("button"); b.type = "button"; b.className = "hs-arrow " + cls; b.textContent = txt; b.setAttribute("aria-label", dir < 0 ? "왼쪽으로" : "오른쪽으로"); b.onclick = e => { e.stopPropagation(); el.scrollBy({left: dir * Math.max(160, el.clientWidth * 0.7), behavior: "smooth"}); }; wrap.appendChild(b); return b; };
  const L = mk("hs-l", "◀", -1), R = mk("hs-r", "▶", 1);
  const sync = () => { const over = el.scrollWidth > el.clientWidth + 2; L.hidden = !over || el.scrollLeft <= 2; R.hidden = !over || el.scrollLeft + el.clientWidth >= el.scrollWidth - 2; };
  el.addEventListener("scroll", sync, {passive: true});
  if ("ResizeObserver" in window) new ResizeObserver(sync).observe(el); else addEventListener("resize", sync);
  new MutationObserver(sync).observe(el, {childList: true, subtree: true});
  setTimeout(sync, 50);
  return {sync};
}
// 선택된 탭이 보이게 가운데로
export function revealIn(el, child){ if (!el || !child) return; const l = child.offsetLeft - el.clientWidth / 2 + child.offsetWidth / 2; el.scrollTo({left: Math.max(0, l), behavior: "smooth"}); }

// 사무실 확대·축소. fitScale(): 화면에 다 들어가는 배율. 반환: {apply(), zoomBy(f, cx, cy), set(z), get()}
// mode: "fit"(맞춤) 이거나 숫자 배율. 기본은 '읽을 수 있는 크기' — 맞춤 배율이 너무 작으면 readable 배율로 열고 끌어서 본다.
export function stageZoom({stage, floor, W, H, key, readable = 0.85, min = 0.3, max = 2.2, onScale}){
  let z = null; try { const v = localStorage.getItem(key); z = v === "fit" ? "fit" : v ? +v : null; } catch(e){}
  const sizer = document.createElement("div"); sizer.className = "of-sizer"; stage.appendChild(sizer);
  const fitS = () => Math.min(stage.clientWidth / W, stage.clientHeight / H) || 1;
  const cur = () => { const f = fitS(); if (z === "fit") return f; if (typeof z === "number" && z > 0) return Math.max(min, Math.min(max, z)); return f < readable * 0.8 ? readable : f; };
  function apply(){
    const s = cur(), w = W * s, h = H * s, pan = w > stage.clientWidth + 1 || h > stage.clientHeight + 1;
    stage.classList.toggle("pan", pan);
    floor.style.transform = `scale(${s})`;
    floor.style.left = Math.max(0, (stage.clientWidth - w) / 2) + "px"; floor.style.top = Math.max(0, (stage.clientHeight - h) / 2) + "px";
    sizer.style.width = w + "px"; sizer.style.height = h + "px";
    onScale?.(s, pan);
    return s;
  }
  function set(nz, cx, cy){
    const s0 = cur(), r = stage.getBoundingClientRect();
    const px = cx == null ? stage.clientWidth / 2 : cx - r.left, py = cy == null ? stage.clientHeight / 2 : cy - r.top;
    const wx = (stage.scrollLeft + px) / s0, wy = (stage.scrollTop + py) / s0;   // 확대 기준점(세계 좌표)
    z = nz; try { localStorage.setItem(key, String(z)); } catch(e){}
    const s1 = apply();
    if (z !== "fit"){ stage.scrollLeft = wx * s1 - px; stage.scrollTop = wy * s1 - py; }
  }
  const zoomBy = (f, cx, cy) => set(Math.max(min, Math.min(max, +(cur() * f).toFixed(3))), cx, cy);
  stage.addEventListener("wheel", e => { if (!e.ctrlKey) return; e.preventDefault(); zoomBy(e.deltaY < 0 ? 1.12 : 1 / 1.12, e.clientX, e.clientY); }, {passive: false});
  // 빈 바닥을 끌어서 이동 (직원·버튼 위에서는 원래 클릭)
  let drag = null;
  stage.addEventListener("pointerdown", e => { if (e.button !== 0 || e.target.closest("[data-ag], button, a, input, select, .of-bub")) return; if (!stage.classList.contains("pan")) return; drag = {x: e.clientX, y: e.clientY, l: stage.scrollLeft, t: stage.scrollTop, moved: false}; stage.classList.add("grabbing"); });
  addEventListener("pointermove", e => { if (!drag) return; const dx = e.clientX - drag.x, dy = e.clientY - drag.y; if (Math.abs(dx) + Math.abs(dy) > 4) drag.moved = true; stage.scrollLeft = drag.l - dx; stage.scrollTop = drag.t - dy; });
  addEventListener("pointerup", () => { if (drag){ stage.classList.remove("grabbing"); drag = null; } });
  stage.addEventListener("dblclick", e => { if (e.target.closest("[data-ag], button")) return; zoomBy(1.5, e.clientX, e.clientY); });
  return {apply, set, zoomBy, get: cur, fit: () => set("fit"), readable: () => set(readable)};
}
// ☰ 모든 방: 탭이 많으면 한 번에 보고 고르기 (원래 탭 버튼을 대신 눌러 준다)
export function roomPicker(chans){
  if (!chans || chans._rp) return; chans._rp = true;
  const host = chans.closest(".hs-wrap") || chans, btn = document.createElement("button"), panel = document.createElement("div");
  btn.type = "button"; btn.className = "rp-btn"; btn.textContent = "☰ 모든 방"; btn.title = "모든 방 한눈에 보기";
  panel.className = "rp-panel"; panel.hidden = true;
  host.parentNode.insertBefore(btn, host); host.parentNode.insertBefore(panel, host.nextSibling);
  const render = () => { panel.innerHTML = [...chans.querySelectorAll("[data-ch]")].map(b => `<button type="button" data-rp="${b.dataset.ch}" class="${b.getAttribute("aria-pressed") === "true" ? "on" : ""}" style="${b.getAttribute("style") || ""}">${b.innerHTML.replace(/ id="[^"]*"/g, "")}</button>`).join(""); };
  btn.onclick = e => { e.stopPropagation(); if (panel.hidden) render(); panel.hidden = !panel.hidden; btn.classList.toggle("on", !panel.hidden); };
  panel.addEventListener("click", e => { const b = e.target.closest("[data-rp]"); if (!b) return; e.stopPropagation(); panel.hidden = true; btn.classList.remove("on"); chans.querySelector(`[data-ch="${b.dataset.rp}"]`)?.click(); });
}
