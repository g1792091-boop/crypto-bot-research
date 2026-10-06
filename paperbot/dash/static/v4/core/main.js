// Boot: the skin (core/skin.js), the live stream, the server clock, the feature probe, the shell (nav, chip, health dot, banner), the router,
// the first-visit tour and the "지난번 본 뒤로" sheet (core/since.js). The Google Fonts stylesheet is attached only after
// boot (index.html preloads it), so a font host that hangs instead of failing never holds back the first paint or the data.
import {startStream, syncClock} from "./api.js";
import {startFeatureProbe} from "./features.js";
import {startShell} from "./shell.js";
import {startRouter} from "./router.js";
import {maybeStartTour} from "./tour.js";
import {startSince} from "./since.js";
import {applySkin} from "./skin.js";
import {applyText} from "./textsize.js";
import {applyNavPos} from "./navpos.js";
import {startDrawer} from "./drawer.js";
import {startFind} from "./find.js";
import {startNavKeys} from "./navkeys.js";
import {startVersion} from "./version.js";

function attachFonts() {
  const pre = document.getElementById("gfonts");
  if (!pre || document.querySelector("link[data-gfonts]")) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = pre.href;
  link.dataset.gfonts = "1";
  document.head.append(link);
}

function boot() {
  applySkin();            // the viewer's skin (tokens.css: "ai" by default, "classic" by choice) before anything draws
  applyText();            // the viewer's 글자 크기 (tokens.css: "md" by default, "lg" / "xl" by choice), same moment
  applyNavPos();          // the viewer's 메뉴 위치 (core/navpos.js: the top bar by default, the left rail by choice)
  startShell();
  startDrawer();           // account / strategy / trade links open in the side panel (before the router: its links)
  startRouter();
  startFind();             // '/' and the 찾기 button
  startNavKeys();          // 1-9, and the phone's sideways swipe between a group's screens
  startStream();
  startFeatureProbe();
  startVersion();          // '새 버전 준비됨 · 눌러서 새로고침' when the server has newer code (before the first clock check)
  syncClock();
  setInterval(syncClock, 600000);
  maybeStartTour();
  startSince();            // "지난번 본 뒤로" sheet (never on the first visit)
  attachFonts();
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();
