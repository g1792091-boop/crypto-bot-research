// 내 지갑 보기 (읽기 전용)
// - 공개 주소만 붙여 넣어 목록으로 보관한다. 개인키·시드문구는 절대 받지 않고(입력하면 막음), 저장하지도 않는다.
// - 잔액은 공개 블록 익스플로러에서 본다(새 탭). 지원되는 체인은 그 자리에서 공개 API로 잔액을 한 번 읽어 보여 주되, 실패하면 익스플로러 링크로 넘어간다.
// - 이 앱에는 출금·서명·송금 기능이 없다. 순수하게 '내 주소의 잔액을 보는' 용도다.
const LS_KEY = "ghcoin:wallets";

// 체인 판별: 공개 주소 형식만 본다
const CHAINS = {
  evm:    {name: "이더리움/EVM", re: /^0x[0-9a-fA-F]{40}$/, badge: "EVM"},
  btc:    {name: "비트코인", re: /^(bc1[0-9a-z]{11,71}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$/, badge: "BTC"},
  tron:   {name: "트론 (TRC)", re: /^T[1-9A-HJ-NP-Za-km-z]{33}$/, badge: "TRX"},
  xrp:    {name: "리플", re: /^r[1-9A-HJ-NP-Za-km-z]{23,34}$/, badge: "XRP"},
  doge:   {name: "도지코인", re: /^D[1-9A-HJ-NP-Za-km-z]{32,34}$/, badge: "DOGE"},
  sol:    {name: "솔라나", re: /^[1-9A-HJ-NP-Za-km-z]{32,44}$/, badge: "SOL"}   // base58 폴백 (맨 마지막에 본다)
};
const ORDER = ["evm", "btc", "tron", "xrp", "doge", "sol"];
function detectChain(addr){
  for (const id of ORDER) if (CHAINS[id].re.test(addr)) return id;
  return null;
}
// 익스플로러 링크 (여러 개면 사용자가 네트워크를 고를 수 있게 모두 준다)
function explorers(chain, addr){
  const a = encodeURIComponent(addr);
  switch (chain){
    case "evm":  return [["Etherscan", `https://etherscan.io/address/${a}`], ["BscScan", `https://bscscan.com/address/${a}`], ["Arbiscan", `https://arbiscan.io/address/${a}`], ["Polygonscan", `https://polygonscan.com/address/${a}`]];
    case "btc":  return [["mempool.space", `https://mempool.space/address/${a}`], ["Blockchair", `https://blockchair.com/bitcoin/address/${a}`]];
    case "tron": return [["Tronscan", `https://tronscan.org/#/address/${a}`]];
    case "xrp":  return [["XRPScan", `https://xrpscan.com/account/${a}`]];
    case "doge": return [["Blockchair", `https://blockchair.com/dogecoin/address/${a}`]];
    case "sol":  return [["Solscan", `https://solscan.io/account/${a}`], ["Solana Explorer", `https://explorer.solana.com/address/${a}`]];
    default:     return [];
  }
}

// 개인키·시드문구로 보이면 막는다 (실수로라도 저장되지 않게)
function looksSecret(s){
  const t = s.trim();
  if (/^(0x)?[0-9a-fA-F]{64}$/.test(t)) return "개인키(64자리)로 보입니다";
  if (/^(xprv|yprv|zprv|tprv)[0-9A-Za-z]+$/.test(t)) return "확장 개인키(xprv…)로 보입니다";
  const words = t.split(/\s+/);
  if (words.length >= 12 && words.length <= 24 && words.every(w => /^[a-z]{3,8}$/.test(w))) return "시드(복구) 문구로 보입니다";
  return null;
}

const load = () => { try { return JSON.parse(localStorage.getItem(LS_KEY) || "[]"); } catch(e){ return []; } };
const save = list => { try { localStorage.setItem(LS_KEY, JSON.stringify(list)); } catch(e){} };

let ctx = {toast: m => console.log(m), esc: s => String(s ?? "")};
const esc = s => ctx.esc(s);
const toast = m => { try { ctx.toast(m); } catch(e){ console.log(m); } };
const short = a => a.length > 16 ? a.slice(0, 8) + "…" + a.slice(-6) : a;

function cssOnce(){
  if (typeof document === "undefined" || document.querySelector("link[data-wallet-css]")) return;
  const l = document.createElement("link"); l.rel = "stylesheet"; l.href = new URL("./wallet.css", import.meta.url).href; l.dataset.walletCss = "1";
  document.head.appendChild(l);
}

// 공개 API로 잔액 한 번 읽어 보기 (실패하면 null → 익스플로러로)
async function fetchBalance(chain, addr){
  const to = (p, ms = 8000) => Promise.race([p, new Promise((_, r) => setTimeout(() => r(new Error("시간 초과")), ms))]);
  try {
    if (chain === "btc"){
      const r = await to(fetch(`https://mempool.space/api/address/${addr}`)); if (!r.ok) throw 0;
      const j = await r.json(), s = (j.chain_stats?.funded_txo_sum || 0) - (j.chain_stats?.spent_txo_sum || 0);
      return `${(s / 1e8).toLocaleString("ko-KR", {maximumFractionDigits: 8})} BTC`;
    }
    if (chain === "evm"){
      const r = await to(fetch("https://cloudflare-eth.com", {method: "POST", headers: {"content-type": "application/json"}, body: JSON.stringify({jsonrpc: "2.0", id: 1, method: "eth_getBalance", params: [addr, "latest"]})}));
      if (!r.ok) throw 0; const j = await r.json(); if (!j.result) throw 0;
      return `${(Number(BigInt(j.result)) / 1e18).toLocaleString("ko-KR", {maximumFractionDigits: 6})} ETH`;
    }
  } catch(e){}
  return null;
}

function listHTML(){
  const list = load();
  return `<div class="wl-box" role="dialog" aria-label="내 지갑 보기 (읽기 전용)">
    <div class="wl-h"><b>👛 내 지갑 보기</b><span class="wl-pill">읽기 전용 · 개인키 저장 안 함</span><span class="wl-sp"></span><button class="wl-x" data-wx aria-label="닫기">✕</button></div>
    <p class="wl-warn">⚠ <b>공개 주소만</b> 붙여 넣으세요. <b>개인키·시드(복구) 문구는 절대 입력하지 마세요</b> — 이 화면은 주소만 보관하고 잔액은 블록 익스플로러에서 봅니다. 이 앱에는 송금·출금·서명 기능이 없습니다.</p>
    <div class="wl-add"><input id="wlAddr" placeholder="공개 지갑 주소 (0x… · bc1… · T… · r… 등)" autocomplete="off" spellcheck="false">
      <input id="wlLabel" placeholder="별명 (선택)" autocomplete="off" maxlength="24">
      <button class="wl-btn pri" data-wadd>추가</button></div>
    <div class="wl-list">${list.length ? list.map((w, i) => {
      const ch = CHAINS[w.chain] || {name: w.chain, badge: "?"}, ex = explorers(w.chain, w.addr);
      return `<div class="wl-item" data-i="${i}">
        <div class="wl-item-h"><span class="wl-badge">${esc(ch.badge)}</span><b>${esc(w.label || ch.name)}</b><span class="wl-sp"></span>
          <button class="wl-btn sm" data-wbal="${i}">잔액 보기</button><button class="wl-btn sm" data-wcopy="${i}">주소 복사</button><button class="wl-btn sm" data-wdel="${i}">삭제</button></div>
        <div class="wl-addr">${esc(w.addr)}</div>
        <div class="wl-bal" id="wlBal${i}"></div>
        <div class="wl-ex">${ex.map(([n, u]) => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(n)} ↗</a>`).join("")}</div>
      </div>`;
    }).join("") : `<p class="wl-empty">아직 저장한 주소가 없습니다. 위에 공개 주소를 붙여 넣으세요.</p>`}</div>
  </div>`;
}

export function openWallet(c){
  if (c) ctx = {...ctx, ...c};
  cssOnce();
  let m = document.getElementById("wlModal");
  if (!m){ m = document.createElement("div"); m.id = "wlModal"; m.className = "wl-modal"; document.body.appendChild(m);
    m.addEventListener("click", async e => {
      if (e.target === m || e.target.closest("[data-wx]")){ m.hidden = true; return; }
      if (e.target.closest("[data-wadd]")){ addAddr(m); return; }
      const del = e.target.closest("[data-wdel]"); if (del){ const list = load(); list.splice(+del.dataset.wdel, 1); save(list); m.innerHTML = listHTML(); return; }
      const cp = e.target.closest("[data-wcopy]"); if (cp){ const w = load()[+cp.dataset.wcopy]; if (w){ try { await navigator.clipboard.writeText(w.addr); toast("주소를 복사했습니다"); } catch(err){ toast("복사하지 못했습니다"); } } return; }
      const bal = e.target.closest("[data-wbal]"); if (bal){ await showBalance(+bal.dataset.wbal); return; }
    });
    m.addEventListener("keydown", e => { if (e.key === "Enter" && (e.target.id === "wlAddr" || e.target.id === "wlLabel")) addAddr(m); if (e.key === "Escape") m.hidden = true; });
  }
  m.innerHTML = listHTML(); m.hidden = false;
  setTimeout(() => document.getElementById("wlAddr")?.focus(), 50);
}

function addAddr(m){
  const ai = document.getElementById("wlAddr"), li = document.getElementById("wlLabel");
  const addr = (ai.value || "").trim(), label = (li.value || "").trim();
  if (!addr) return;
  const secret = looksSecret(addr);
  if (secret){ toast(`${secret} — 공개 주소만 넣으세요. 개인키·시드는 저장하지 않습니다`); ai.value = ""; return; }
  const chain = detectChain(addr);
  if (!chain){ toast("알 수 없는 주소 형식입니다. 공개 주소를 다시 확인하세요"); return; }
  const list = load();
  if (list.some(w => w.addr === addr)){ toast("이미 저장된 주소입니다"); return; }
  list.push({addr, label, chain, at: Date.now()});
  save(list);
  const ch = CHAINS[chain];
  toast(`${ch.name} 주소를 추가했습니다`);
  m.innerHTML = listHTML();
}

async function showBalance(i){
  const w = load()[i]; if (!w) return;
  const el = document.getElementById("wlBal" + i); if (!el) return;
  const ch = CHAINS[w.chain] || {};
  if (w.chain !== "btc" && w.chain !== "evm"){ el.innerHTML = `<span class="wl-dim">${esc(ch.name || "")} 잔액은 위 익스플로러 링크에서 확인하세요.</span>`; return; }
  el.innerHTML = `<span class="wl-dim">불러오는 중…</span>`;
  const bal = await fetchBalance(w.chain, w.addr);
  el.innerHTML = bal != null ? `잔액 <b>${esc(bal)}</b> <span class="wl-dim">· 자세한 내역은 익스플로러에서</span>`
    : `<span class="wl-dim">바로 불러오지 못했습니다 — 아래 익스플로러 링크에서 확인하세요.</span>`;
}
