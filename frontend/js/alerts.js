// 알림 센터: 뉴스 · 경제지표 · 시장 판단 변화 · 봇 체결 · 가격 알림
import { $, api, emit, esc, hhmm, on, px, state, toast } from "./core.js";

const load = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } };
const store = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* 무시 */ } };

const OPTS = [
  ["news_important", "중요 뉴스 (속보·연준·ETF·규제·해킹·급변)"],
  ["news_all", "모든 새 뉴스"],
  ["calendar", "경제지표 발표 (30분 전 · 5분 전 · 발표)"],
  ["regime", "시장 판단 변화 (롱/숏/횡보 전환)"],
  ["bots", "페이퍼 봇 체결"],
  ["scanner", "시그널 스캐너 (관심 코인 자동 분석 신호)"],
  ["scanner_strong", "└ 강한 신호(강도 2 이상)만"],
  ["ai_watch", "AI 포지션 감시 (손절·청산가 근접, 손절 없음, 반대 판단·신호)"],
  ["autopilot", "오토파일럿 (자동 매매법 진입·청산 시그널, AI 판단 변경)"],
  ["sound", "알림음"],
  ["desktop", "바탕화면 알림 (브라우저 창이 뒤에 있어도)"],
];
const opts = { news_important: true, news_all: false, calendar: true, regime: true, bots: true, scanner: true, scanner_strong: true, ai_watch: true, autopilot: true, sound: true, desktop: false,
  ...load("ft.alertOpts", {}) };
let log = load("ft.alertLog", []);
let priceAlerts = load("ft.priceAlerts", []);
const seen = new Set(load("ft.alertSeen", []));

function remember(key) {
  seen.add(key);
  store("ft.alertSeen", [...seen].slice(-500));
}

let audio;
function beep() {
  try {
    audio = audio || new (window.AudioContext || window.webkitAudioContext)();
    [880, 1320].forEach((f, i) => {
      const o = audio.createOscillator(), g = audio.createGain();
      o.frequency.value = f; o.connect(g); g.connect(audio.destination);
      const t = audio.currentTime + i * 0.12;
      g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.15, t + 0.01);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.1);
      o.start(t); o.stop(t + 0.11);
    });
  } catch { /* 오디오 불가 */ }
}

export function notify({ title, msg = "", kind = "", cat = "etc", url = "" }) {
  log.unshift({ t: Math.floor(Date.now() / 1000), title, msg, cat, url, read: false });
  log = log.slice(0, 150);
  store("ft.alertLog", log);
  toast(title, msg, kind);
  if (opts.sound) beep();
  if (opts.desktop && "Notification" in window && Notification.permission === "granted") {
    const n = new Notification(title, { body: msg, tag: title + msg });
    if (url) n.onclick = () => window.open(url, "_blank");
  }
  render();
}

function render() {
  const unread = log.filter((a) => !a.read).length;
  const c = $("#bell-cnt");
  c.hidden = !unread;
  c.textContent = unread > 99 ? "99+" : unread;
  $("#alerts-list").innerHTML = log.length ? log.map((a) => `<div class="alert-row ${a.read ? "" : "unread"}">
      <div class="row"><b class="grow">${a.url ? `<a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title)}</a>` : esc(a.title)}</b>
      <span class="tm">${hhmm(a.t)}</span></div>${a.msg ? `<div class="m">${esc(a.msg)}</div>` : ""}</div>`).join("")
    : `<div class="empty">알림이 없습니다.</div>`;
  emit("alertlog", log);
}

function renderOpts() {
  $("#alert-opts").innerHTML = OPTS.map(([k, l]) => `<label><input type="checkbox" data-opt="${k}" ${opts[k] ? "checked" : ""}> ${l}</label>`).join("");
}

// ---------------------------------------------------------------- 뉴스
let newsPrimed = false;
async function pollNews() {
  try {
    const d = await api("/api/news?limit=60");
    state.news = d.items;
    emit("news", d.items);
    const fresh = d.items.filter((n) => !seen.has("n:" + n.id));
    fresh.forEach((n) => remember("n:" + n.id));
    if (!newsPrimed) { newsPrimed = true; return; }   // 처음 불러온 기사로는 알림을 띄우지 않음
    for (const n of fresh.slice(0, 5).reverse()) {
      if ((n.important && opts.news_important) || opts.news_all) {
        notify({ title: `${n.tags?.length ? "[" + n.tags.join("·") + "] " : ""}${n.title}`, msg: n.source, cat: "news", url: n.url });
      }
    }
  } catch { /* 네트워크 오류는 다음 주기에 */ }
}

// ---------------------------------------------------------------- 시그널 스캐너
let sigSince = null;
const IVK = { "1m": "1분", "3m": "3분", "5m": "5분", "15m": "15분", "30m": "30분", "1h": "1시간", "2h": "2시간", "4h": "4시간", "6h": "6시간", "12h": "12시간", "1d": "일봉", "3d": "3일", "1w": "주봉", "1M": "월봉" };
async function pollSignals() {
  try {
    if (sigSince == null) { sigSince = (await api("/api/scanner/signals?limit=1")).now; return; }   // 켜기 전 신호로는 알림 안 띄움
    const d = await api(`/api/scanner/signals?since=${sigSince}`);
    sigSince = d.now;
    if (!d.items.length) return;
    emit("signals", d.items);
    if (!opts.scanner) return;
    const show = d.items.filter((s) => !opts.scanner_strong || s.strength >= 2);
    for (const s of show.slice(0, 5).reverse()) {
      notify({ title: `[시그널] ${s.symbol.replace(/USDT$/, "")} ${IVK[s.interval] || s.interval} ${s.dir === "long" ? "▲ 롱" : s.dir === "short" ? "▼ 숏" : "●"} · ${s.label}`,
        msg: `${s.text} · 강도 ${"●".repeat(s.strength)}${s.confluence ? ` (${s.confluence}개 겹침)` : ""}`, cat: "signal", kind: s.dir === "long" ? "up" : s.dir === "short" ? "err" : "" });
    }
    if (show.length > 5) notify({ title: `[시그널] 새 신호 ${show.length - 5}개 더`, msg: "'퀀트 → 시그널 스캐너'에서 전체를 볼 수 있습니다", cat: "signal" });
  } catch { /* 다음 주기에 */ }
}

// ---------------------------------------------------------------- AI 포지션 감시 (서버가 30초마다 계산)
let aiSince = Math.floor(Date.now() / 1000) - 120;
async function pollAiWatch() {
  try {
    const d = await api(`/api/copilot/alerts?since=${aiSince}`);
    aiSince = d.now;
    if (!opts.ai_watch) return;
    for (const a of d.items.slice(0, 4).reverse()) {
      notify({ title: `[AI 감시] ${a.text}`, msg: a.ai || "트레이드 오른쪽 '실시간 AI' 탭에서 자세한 분석과 조치 버튼을 볼 수 있습니다", cat: "ai",
        kind: a.level === "high" ? "err" : "" });
    }
  } catch { /* 다음 주기에 */ }
}

// ---------------------------------------------------------------- 오토파일럿 시그널
let apSince = Math.floor(Date.now() / 1000) - 120;
async function pollAutopilot() {
  try {
    const d = await api(`/api/autopilot/signals?since=${apSince}`);
    apSince = d.now;
    emit("apsignals", d.items);
    if (!opts.autopilot) return;
    for (const x of d.items.slice(0, 4).reverse()) {
      const head = { entry: "오토 진입", exit: "오토 청산", deploy: "오토 봇 시작", ai: "AI 판단", ai_note: "오토 진입 · AI 코멘트" }[x.type] || "오토";
      notify({ title: `[${head}] ${x.symbol.replace(/USDT$/, "")} ${IVK[x.interval] || x.interval || ""} · ${x.text}`,
        msg: `${x.strategy || ""}${x.status === "observe" ? " · 관찰(검증 미통과) — 참고용" : x.status === "pass" ? " · 검증 통과 매매법 (모의)" : ""}`, cat: "autopilot",
        kind: x.type === "entry" ? (x.side === "long" ? "up" : "err") : x.type === "exit" ? (x.pnl > 0 ? "up" : "err") : "" });
    }
  } catch { /* 다음 주기에 */ }
}

// ---------------------------------------------------------------- 경제지표
let calendar = [];
async function loadCalendar() {
  try {
    const d = await api("/api/calendar");
    calendar = d.items || [];
    emit("calendar", calendar);
  } catch { /* 무시 */ }
}
function checkCalendar() {
  if (!opts.calendar) return;
  const now = Date.now();
  for (const e of calendar) {
    const t = Date.parse(e.date);
    if (!t) continue;
    const mins = (t - now) / 60000;
    const stage = mins <= 30 && mins > 25 ? "30" : mins <= 5 && mins > 0 ? "5" : mins <= 0 && mins > -3 ? "0" : null;
    if (!stage) continue;
    const key = `c:${e.title}:${e.date}:${stage}`;
    if (seen.has(key)) continue;
    remember(key);
    const when = stage === "0" ? "발표" : `${stage}분 전`;
    notify({ title: `[경제지표 ${when}] ${e.country} ${e.title}`,
      msg: `예상 ${e.forecast || "–"} · 이전 ${e.previous || "–"} — 발표 전후 변동성 주의`, cat: "calendar", kind: "err" });
  }
}

// ---------------------------------------------------------------- 시장 판단 · 봇 · 가격
const lastRegime = {};
on("analysis", (a) => {
  const k = `${a.symbol}:${a.interval}`;
  const prev = lastRegime[k];
  lastRegime[k] = a.regime.state;
  if (prev && prev !== a.regime.state && opts.regime) {
    notify({ title: `${a.symbol} ${a.interval} 시장 판단 변경: ${a.regime.label}`,
      msg: `점수 ${a.regime.score} · ${a.regime.reasons.slice(0, 2).join(" / ")}`, cat: "regime",
      kind: a.regime.state === "long" ? "up" : a.regime.state === "short" ? "err" : "" });
  }
});

const botTrades = {};
on("bots", (bots) => {
  for (const b of bots) {
    const n = `${b.account.trades.length}:${b.account.position?.entry_time ?? ""}`;
    if (b.id in botTrades && botTrades[b.id] !== n && opts.bots) {
      const p = b.account.position;
      const t = b.account.trades[b.account.trades.length - 1];
      notify({ title: `페이퍼 봇 ${b.name}`, cat: "bot",
        msg: p ? `${p.side === "long" ? "롱" : "숏"} 진입 ${px(p.entry_price)} (${b.symbol})`
          : t ? `${t.side === "long" ? "롱" : "숏"} 청산 ${px(t.exit_price)} · 손익 ${t.pnl.toFixed(2)}` : "상태 변경" });
    }
    botTrades[b.id] = n;
  }
});

export function addPriceAlert(symbol, price) {
  const cur = state.tickers[symbol]?.price;
  if (!cur || !price) return;
  priceAlerts.push({ symbol, price, dir: price > cur ? "up" : "down" });
  store("ft.priceAlerts", priceAlerts);
  emit("pricealerts", priceAlerts);
}
export function removePriceAlert(i) {
  priceAlerts.splice(i, 1);
  store("ft.priceAlerts", priceAlerts);
  emit("pricealerts", priceAlerts);
}
export const getPriceAlerts = () => priceAlerts;
on("tickers", (t) => {
  const hit = [];
  priceAlerts = priceAlerts.filter((a) => {
    const p = t[a.symbol]?.price;
    if (p == null) return true;
    if ((a.dir === "up" && p >= a.price) || (a.dir === "down" && p <= a.price)) { hit.push({ ...a, now: p }); return false; }
    return true;
  });
  if (hit.length) {
    store("ft.priceAlerts", priceAlerts);
    emit("pricealerts", priceAlerts);
    hit.forEach((a) => notify({ title: `[가격 알림] ${a.symbol} ${px(a.price)} ${a.dir === "up" ? "돌파" : "이탈"}`,
      msg: `현재가 ${px(a.now)}`, cat: "price", kind: a.dir === "up" ? "up" : "err" }));
  }
});

export function initAlerts() {
  renderOpts();
  render();
  $("#bell").onclick = (e) => { e.stopPropagation(); $("#alerts").classList.toggle("on"); };
  document.addEventListener("click", (e) => { if (!e.target.closest("#alerts")) $("#alerts").classList.remove("on"); });
  $("#alerts-read").onclick = () => { log.forEach((a) => (a.read = true)); store("ft.alertLog", log); render(); };
  $("#alert-opts").onchange = async (e) => {
    const k = e.target.dataset.opt;
    if (!k) return;
    opts[k] = e.target.checked;
    if (k === "desktop" && opts.desktop && "Notification" in window && Notification.permission !== "granted") {
      const p = await Notification.requestPermission();
      if (p !== "granted") { opts.desktop = false; e.target.checked = false; toast("바탕화면 알림이 차단되어 있습니다", "브라우저 주소창의 사이트 설정에서 알림을 허용하세요.", "err"); }
    }
    store("ft.alertOpts", opts);
  };
  pollNews(); setInterval(pollNews, 60_000);
  pollSignals(); setInterval(pollSignals, 20_000);
  pollAiWatch(); setInterval(pollAiWatch, 20_000);
  pollAutopilot(); setInterval(pollAutopilot, 15_000);
  loadCalendar(); setInterval(loadCalendar, 10 * 60_000);
  setInterval(checkCalendar, 20_000);
}
