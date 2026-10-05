// Which optional features really run (owners: hide what is not active yet). Probed from the existing endpoints at
// start and every 10 minutes; bus event "features" after each probe. A screen or tab with `feature` is hidden while
// it is false. Nothing is guessed: a probe that fails leaves the feature hidden.
import {api, bus} from "./api.js";

export const features = {
  debate: false,        // /api/debate ready (debate.db exists): the 24-hour debate room has run at least once
  debateRunning: false, // its state is "running" right now
  questions: false,     // /api/analysis/questions has questions (the 45-question page is empty until filled)
  ghcoin: false,        // the GH Coin recorder has a board or finished calls
  liq: false,           // the liquidation recorder's liq.db exists
  priceSender: false,   // the price-alert sender (tgtrades) is alive
  probed: false,
};

async function one(path) {
  try { return await api(path); } catch (e) { return null; }
}

export async function probeFeatures() {
  const [deb, q, gh, liq, pa] = await Promise.all([one("/api/debate"), one("/api/analysis/questions"),
    one("/api/ghcoin/board"), one("/api/liq?symbol=BTCUSDT&minutes=60"), one("/api/price-alerts")]);
  features.debate = !!(deb && deb.ready);
  features.debateRunning = !!(deb && deb.ready && deb.state === "running");
  features.questions = !!(q && Array.isArray(q.questions) && q.questions.length);
  features.ghcoin = !!(gh && (gh.alive || (gh.coins && Object.keys(gh.coins).length)));
  features.liq = !!(liq && liq.recorder);
  features.priceSender = !!(pa && pa.sender_alive);
  features.probed = true;
  bus.emit("features", {...features});
  return features;
}

let timer = null;
export function startFeatureProbe() {
  if (timer) return;
  probeFeatures();
  timer = setInterval(() => { if (document.visibilityState === "visible") probeFeatures(); }, 600000);
}
