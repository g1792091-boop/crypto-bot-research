// Which site this page is: the rule bot's dashboard (paperbot/dash, port 8080: "paper") or the separate 실거래 site
// (paperbot/livedash, port 8093, owners 10/19 "실거래용 봇 대시보드 사이트를 따로": "live"). The live page says so in its
// own markup (static/live/index.html: <html data-site="live">), read once here before any module draws; node tests and
// the rule bot's page have no such attribute (paper). The live site shares every core module and the 실거래 screens; only
// routes.js (its own menu), the router (the module behind a menu item), features / sound / settings / find (no rule-bot
// routes there) look at this.
const root = typeof document !== "undefined" && document ? document.documentElement : null;
export const SITE = root && root.dataset && root.dataset.site === "live" ? "live" : "paper";
export const LIVE = SITE === "live";
/** The page's name after a screen's title ("관제 · 실거래", "요약 · Paper v4"). */
export const BRAND = LIVE ? "실거래" : "Paper v4";
/** The 실거래 site's port (deploy/paperbot-livedash.service) and the rule bot's (deploy/paperbot-dash.service). */
export const LIVE_PORT = 8093;
export const PAPER_PORT = 8080;
/** The other site's address on this same host (the Tailscale name or address the page was opened with). */
export const siteUrl = (port, hash = "") => {
  const host = typeof location !== "undefined" && location.hostname ? location.hostname : "";
  return host ? `http://${host.includes(":") && !host.startsWith("[") ? `[${host}]` : host}:${port}/${hash}` : null;
};
