// Boot of the 실거래 site (static/live/index.html, paperbot/livedash): only the core pieces that work without the rule
// bot's routes. The skin and the text size (per device), the slim shell (static/live/shell.js), the router over the
// 실거래 menu (core/routes.js LIVE_SCREENS: <html data-site="live">, core/site.js), the number keys and the swipe, 찾기,
// the feature probe (here: the liquidation recorder and the price alerts only), '새 버전' (core/version.js) and the
// server clock, the 설정 panel. NOT started here: the rule bot's live stream (/api/stream), the D+n chip, the health dot
// and its banner, the bell, the side panel, the first-visit tour, "지난번 본 뒤로", the verdict band and TV 자동 넘김.
// The Google Fonts stylesheet is attached only after boot (index.html preloads it), as on the rule bot's page.
import {syncClock} from "../v4/core/api.js";
import {startFeatureProbe} from "../v4/core/features.js";
import {startRouter} from "../v4/core/router.js";
import {applySkin} from "../v4/core/skin.js";
import {applyText} from "../v4/core/textsize.js";
import {startFind} from "../v4/core/find.js";
import {startNavKeys} from "../v4/core/navkeys.js";
import {startSettings} from "../v4/core/settings.js";
import {startVersion} from "../v4/core/version.js";
import {startLiveShell} from "./shell.js";

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
  applySkin();             // the viewer's skin (tokens.css: "ai" by default) before anything draws
  applyText();             // the viewer's 글자 크기
  startLiveShell();
  startRouter();
  startFind();             // '/' and the 찾기 button: the 실거래 tabs by name
  startNavKeys();          // 1-9 (the menu's first nine tabs), the phone's sideways swipe inside a group
  startFeatureProbe();
  startVersion();          // '새 버전 준비됨 · 눌러서 새로고침' when the server has newer code
  syncClock();
  setInterval(syncClock, 600000);
  startSettings();         // 설정: the gear, the key ",", the speaker menu's link
  attachFonts();
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();
